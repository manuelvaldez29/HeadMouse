# HEADMOUSE v0.3 — arquitectura desktop y motores compartidos

## Capa de escritorio

```text
app.py → QApplication → MainWindow / widgets / QSS
                           ↕ señales y mailbox de último snapshot
                     DesktopBridge
                           ↕ comandos encolados
                     ControllerWorker (QThread + QTimer)
                           ↓
                     ApplicationController
                     ├── ProfileManager → ProfileStore / AppConfig
                     ├── CalibrationSession → Samples / CalibrationValidation
                     ├── ExperimentEngine / JitterMeasurement → ResultStore
                     ├── SessionMetrics
                     └── VisionEngine → GestureEngine → ActionMapping → ControlEngine
```

`desktop/window.py` presenta datos y emite comandos. `desktop/widgets.py` dibuja
preview y objetivos sin ejecutar MediaPipe ni PyAutoGUI. La lógica de estados,
perfiles, calibración, experimentos y ciclo de vida pertenece a
`application_controller.py`, independiente de Qt y con dependencias inyectables.

`desktop/bridge.py` mueve un QObject worker a un QThread y entrega comandos por
señales encoladas. Un QTimer del worker conduce el controlador cada 33 ms; la
captura sigue en VisionEngine y la inferencia sigue siendo asíncrona. Arranque,
descarga explícita del modelo y cierre ocurren en el worker, no en el hilo GUI.
La presentación consulta un mailbox de capacidad uno: un snapshot nuevo
reemplaza al anterior y no se acumula una cola de frames. El frame se copia al
publicarse y QImage copia su almacenamiento antes del dibujo.

El controlador tiene estados HOME, PREVIEW, DIAGNOSTIC, CALIBRATING, CONTROL,
EXPERIMENT, JITTER, ERROR y CLOSED. La navegación entre páginas es presentación;
las acciones de inicio/cancelación cambian el modo de trabajo. Entrar a
diagnóstico detiene control, experimento y jitter. Calibrar o validar también
detiene salida real y mediciones incompatibles. Aplicar configuración o cambiar
perfil cierra los motores antes de reconstruirlos con el perfil correspondiente.

El arranque no construye VisionEngine ni el backend. Solo tras confirmación y
con un perfil validado se crea ControlEngine. En desktop su ciclo `_tick` se
conduce desde el worker; no se inicia su hilo CLI y no hay dos consumidores del
detector. Un `threading.Event` permite revocar la salida inmediatamente desde
el botón/atajo, antes de procesar el comando encolado. La autorización vuelve a
comprobarse después de inicializar la cámara y el backend para que detener
durante el arranque no reactive el control. No se puede cancelar una llamada
nativa que ya esté ejecutándose. La ventana espera la finalización del worker
al cerrar; la liberación de recursos intenta cerrar cámara y métricas incluso
si falla uno de esos pasos.

`ProfileManager` admite borradores sin umbrales, nombres visibles separados del
identificador estable y borrado confirmado. El mismo JSON contiene calibración,
validación y settings; no hay otra base de configuración. `CalibrationSession`
reutiliza las estadísticas y el validador CLI. `ActionMapping` conserva la
identidad del gesto y selecciona una de once acciones permitidas. El contrato
`TrackingStrategy` admite nuevas implementaciones; únicamente `nose` está
habilitado y mantiene las coordenadas y fórmula existentes. La sensibilidad
por eje, si no está definida, hereda la sensibilidad v0.2.

Los resultados experimentales JSONL son independientes de los resúmenes de
sesión JSON. Ninguno guarda frames. El preview contiene landmarks relevantes
volátiles; jitter guarda agregados y adquisición guarda trayectoria del cursor.
Ver [GUI](GUI.md), [acciones](ACTION_MAPPING.md) y [experimentos](EXPERIMENTS.md).

## Base v0.2 conservada

## Flujo y responsabilidades

```text
Camera → VisionEngine → FaceData → GestureEngine → GestureEvent
                                                    ↓
                                              ControlEngine → Operating System
```

Se conservan los seis scripts originales. `main.py` compone los módulos, el
overlay y el ciclo de vida. `calibrate.py` conserva sus fases y visualización;
`debug_cursor.py` usa la misma lógica nasal sin crear ControlEngine.

| Módulo | Responsabilidad |
|---|---|
| vision_engine.py | Webcam, espejo horizontal, MediaPipe Face Landmarker LIVE_STREAM, extracción de ratios y último frame volátil. Reexporta FaceData. |
| face_data.py | Snapshot inmutable, timestamps monotónicos, validación de finitud y frescura; sin dependencias externas. |
| gesture_engine.py | EMA, zona muerta, curva de aceleración y máquinas hold/cooldown. Reexporta GestureConfig. Reloj y tracking inyectables. |
| tracking.py | Contrato TrackingStrategy y NoseTrackingStrategy: exclusivamente coordenadas del landmark 1 existente. |
| control_engine.py | Backend PyAutoGUI inyectable, pausa, límites, failsafe y acciones. Reexporta ControlConfig. Importar el módulo no inicializa PyAutoGUI. |
| config.py | Dataclasses validadas, defaults, mezcla JSON y rutas del repositorio. |
| profiles.py | Identidad, esquema, validación, JSON local y reemplazo atómico. |
| calibration_logic.py | Muestras únicas, mediana, percentiles, MAD y thresholds personalizados. |
| calibration_validation.py | Prueba guiada de eventos/retorno al neutral sin SO. |
| metrics.py | Agregados acotados, protegidos por lock, un JSON por sesión. |

## Hilos y sincronización

En los entrypoints CLI, el hilo principal maneja OpenCV y coordina inicio/cierre. VisionEngine es un hilo
daemon que captura a una frecuencia máxima configurable. MediaPipe procesa de
forma asíncrona y llama un callback propio; no se asume un callback por captura.
El callback publica un FaceData inmutable bajo lock. Hay un único frame BGR en
RAM; `get_frame()` entrega una copia. Nunca se escribe a disco.

ControlEngine tiene otro hilo daemon, por defecto a 60 Hz. Lee **un** snapshot por
tick y lo pasa a GestureEngine; cada timestamp válido se procesa una sola vez.
No hay cola de frames o eventos que crezca si el consumidor tarda. Las métricas
y las estadísticas comparten datos con locks. El backend SO se usa desde el
hilo de control; solo la inicialización consulta el tamaño de pantalla.

`wait_ready()` espera el primer callback (aunque no detecte cara) o un error,
con timeout; reemplaza las esperas fijas. ExitStack registra limpieza antes de
iniciar cada recurso. Los errores de hilo se propagan al principal. `stop()`
funciona antes de `start()`; después espera de forma acotada. Un driver nativo
bloqueado puede no responder al join: se informa el fallo, no se afirma cierre
exitoso. Aislar la captura en proceso queda como posible mejora posterior.

## Cursor conservado y cambios deliberados

Se conserva espejo, landmark nasal, normalización entre orejas y fórmula:

```text
smooth = alpha * anterior + (1 - alpha) * nariz
d = smooth - neutral
d = 0 si |d| <= dead_zone; de otro modo d -= signo(d) * dead_zone
delta_px = d * sensitivity + d * |d| * acceleration
```

La zona muerta común es 0.03, el valor que ya usaba main.py; el default aislado
de GestureConfig antes era 0.06. El filtro se actualiza una vez por detección
nueva: antes un loop de 60 Hz podía aplicar repetidamente una detección de 30 Hz.
Esto puede reducir la velocidad observada respecto del comportamiento anterior;
se debe revisar sensibilidad en la validación manual. No se ha cambiado a pose
ni a otro landmark. La dependencia de velocidad respecto de FPS permanece como
deuda experimental explícita para no introducir otro modelo en esta iteración.

NoseTrackingStrategy abre el punto de extensión; EyeCenterTrackingStrategy y
HeadPoseTrackingStrategy requerirán nuevas observaciones de visión y comparación
experimental futura. No están implementadas.

## Seguridad y eventos

- Inicio pausado; ambas cejas alternan pausa. Un toggle suprime otras acciones
  del mismo frame, incluso al reanudar.
- Ausencia, datos no finitos o timestamp vencido (0.25 s) bloquean acciones de
  inmediato y reinician hold y smoothing. La autopausa visible conserva su
  timeout de 2 s; al recuperar tracking se levanta, sin modificar la pausa manual.
  Una brecha entre detecciones mayor que el límite de frescura también reinicia
  hold, aunque el consumidor no haya podido ejecutar durante ese intervalo.
- Se suprimen ambos clicks cuando ambos ojos están cerrados para reducir
  parpadeos bilaterales. No constituye una garantía de ausencia de falsos positivos.
- Ambas cejas suprimen scroll individual; hold y cooldown requieren liberación.
  El scroll existente era un evento por elevación, **no** repetición sostenida.
- Deltas se limitan a ±60 px y se rechazan NaN/Inf. Se conserva truncado entero.
- Failsafe PyAutoGUI queda activo y detiene el hilo cuando una llamada lo dispara;
  no es un detector independiente mientras el control está pausado. Ctrl+C o Q
  con overlay cierran la sesión.
- Un error inesperado del backend detiene el control; ya no continúa silenciosamente.
- CLI requiere perfil válido. El constructor legacy de GestureEngine todavía
  admite fallback genérico con advertencia para preservar compatibilidad.

## Configuración, privacidad y límites

Precedencia: defaults → archivo `--config` → `settings` del perfil → CLI
(`--camera`, `--log-level`, `--no-metrics`). Claves desconocidas, tipos erróneos,
NaN/Inf y valores fuera de rango fallan con explicación. Rutas de datos/modelo
son relativas al repositorio, no al directorio desde el cual se lanza Python.

Sin red en funcionamiento normal. Descarga explícita del modelo solo durante
preparación. No hay voz, cloud, backend web ni modelos nuevos. Logs van a la
terminal; DEBUG puede mostrar umbrales locales. Perfiles/métricas están ignorados
por Git; esto no equivale a cifrado ni a permisos especiales del filesystem.

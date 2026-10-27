# Continuación HeadMouse — 26 de octubre de 2026

## Evidencia de partida y alcance

Ruta auditada: `C:\Users\julian\Desktop\HeadMouse`. Rama
`experiment/eye-tracking`, HEAD `b663fcc5165bedf03e041e63f70d63434bd006a4`.
El árbol estaba limpio. No había `AGENTS.md` aplicable, perfiles locales,
`calibration.json`, `config.local.json`, logs de fallos o dumps dentro del proyecto.
Estaban ignorados `.venv/`, cachés Python y `models/`. No se cambió de rama,
no se modificaron dependencias ni se realizaron commits/push/merge/releases.
Las pruebas crean perfiles temporales; no usan perfiles reales.

Entorno inspeccionado, distinto del lock histórico:

| Componente | Versión local |
|---|---|
| Python | 3.12.6 |
| MediaPipe | 1.1.1 |
| OpenCV contrib | 5.0.0.93 |
| NumPy | 2.5.4 |
| PySide6 / shiboken6 | 6.12.0 |
| PyAutoGUI | 0.9.54 |

Esta implementación es experimental. El usuario informó que el joystick ocular
ya movió físicamente el cursor en Windows. Se conserva esa implementación y
no se interpreta una prueba sintética como medida de precisión de la webcam.

## Fase 0 — arquitectura auditada

Se leyeron README, arquitectura, auditoría histórica, experimento ocular,
experimentos y las rutas de código correspondientes. El flujo real continúa:

```text
QApplication / MainWindow
  ↔ DesktopBridge / mailbox de capacidad uno
  ↔ ControllerWorker (QObject + QTimer dentro de QThread)
  → ApplicationController
    → VisionEngine (thread de captura + callback nativo LIVE_STREAM)
      → eye_geometry → FaceData inmutable
      → TrackingStrategy → GestureEngine → ActionMapping → ControlEngine
      → backend PyAutoGUI, creado solamente al autorizar control
```

El diagnóstico, la calibración facial y la calibración ocular no crean backend
de mouse. Los callbacks no manipulan widgets. La captura conserva cámara y
detector en su hilo y los cierra mediante `with`/`finally`. Un evento revoca
salida desde Qt antes de procesar el comando encolado.

Riesgos que siguen abiertos: drivers nativos bloqueados, excepciones nativas no
recuperables desde Python, cambios físicos de posición/iluminación no detectados
por una simple identidad de webcam, y atajos que requieren foco de HeadMouse.
El hilo de descarga de voz existente continúa siendo daemon; la descarga no
ejecuta mouse ni teclado. No se sustituyó MediaPipe ni su modo de inferencia.

## Fase 1 — estabilidad y límites de la evidencia

No se reprodujo el cierre original con webcam y mirada reales. No se conoce su
causa ni se declara resuelto. Se corrigieron riesgos demostrables por inspección
y regresiones automatizadas:

- Excepciones de inicio/publicación de snapshot ahora quedan dentro de las
  barreras del worker; una excepción no controlada revoca salida.
- Si `VisionEngine.stop()` vence, el controlador conserva la referencia para
  reintentar; no permite sustituir silenciosamente una cámara todavía viva.
- Si shutdown falla, el worker detiene su timer de inferencia y reintenta la
  limpieza. No emite finalización prematura ni fuerza `terminate()`.
- El cierre normal de ventana espera al worker. `QApplication.quit()` también
  solicita limpieza y espera; un driver que nunca retorna puede mantener el
  proceso esperando. No hay garantía de recuperación de un driver nativo colgado.
- El loop CLI de control revoca `output_allowed` ante failsafe/error de backend.
- Escape/F8 también cierran la pantalla de calibración; el atajo global antes
  consumía Escape sin cancelar esa captura nueva. El test de GUI lo reprodujo.

Archivos principales: `runtime_diagnostics.py`, `app.py`, `desktop/bridge.py`,
`desktop/window.py`, `application_controller.py`, `control_engine.py`, `.gitignore`.

Al ejecutar `app.py`, `data/logs/headmouse.log` rota a 2 MB, con tres backups.
Registra inicio, versiones, excepciones y thread. `fault-<UTC>.log` mantiene un
descriptor abierto para `faulthandler` y stacks Python ante fallos nativos que
pueda interceptar. Estos últimos archivos no rotan durante un proceso; se crea
uno por ejecución y se pueden archivar manualmente con la aplicación cerrada.
No son minidumps de Windows ni capturan todos los posibles cierres. No guardan
frames, video, landmarks ni muestras de fijación. DEBUG heredado puede incluir
umbrales; usar INFO para el diagnóstico ordinario. Los archivos quedan ignorados.

Una ejecución aislada de los tres tests nuevos de GUI imprimió `OK` y retornó
código 1 sin traceback adicional. Repetida con `-X faulthandler -u`, retornó 0.
Esto queda registrado como observación sin causa establecida; no demuestra el
origen del cierre físico informado por el usuario.

Pruebas físicas pendientes: abrir/cerrar repetidamente con sesión activa,
desconectar/reconectar webcam, cambiar modos durante preview/control, cerrar al
guiñar, ocultar el rostro, probar F8/Escape y failsafe. Revisar logs tras un cierre.

## Fase 2 — joystick ocular conservado

Se conserva geometría, espejo, neutral, zona muerta, sensibilidad, aceleración
y EMA de la rama. Los nombres left/right siguen siendo los históricos; la
lateralidad anatómica debe confirmarse físicamente, sin renombrar gestos.

El backend suma residuos fraccionarios exclusivamente en modo `eye`:

```text
s = delta_nuevo_limitado + residuo_anterior
movimiento_entero = trunc(s)
residuo = s - movimiento_entero
```

Los ticks duplicados no suman ni descartan residuos. Neutral sin movimiento,
pausa, señal inválida o vencida los descartan. No se integra la posición del EMA;
el comportamiento nasal conserva el truncado histórico.

El movimiento ocular exige ambos iris. La geometría y la estrategia relativa
siguen pudiendo inspeccionar una señal monocular, pero GestureEngine se abstiene
de mover con ella. Esto evita saltos por cambiar de promedio binocular a un ojo.
El guiño/parpadeo físico, incluso si su acción está deshabilitada, elimina eventos
de movimiento del mismo frame y mantiene una guarda de 180 ms después de abrir.
Los eventos de clic explícito, cejas y boca se conservan.

La captura neutral anterior sigue disponible. Una captura guiada opcional de
cinco puntos (centro, izquierda, derecha, arriba, abajo) mide cuatro rangos
asimétricos. Los JSON antiguos con `ranges_measured=false` siguen válidos.
Los rangos insuficientes o de signo incorrecto no se guardan.

Diagnóstico muestra iris, señales por ojo, cobertura, neutral, desvío suavizado,
zona muerta, delta calculado, predicción, autorización, pausa y bloqueo.
Archivos: tracking, calibración, GestureEngine, ControlEngine, ventana y tests.

Pendiente: contrastar físicamente dirección, sensibilidad y tolerancia a guiños;
la exigencia binocular puede reducir disponibilidad respecto de la rama anterior.

## Fases 3 y 4 — mapeo absoluto y persistencia independiente

`gaze_mapping.py` separa características, captura, ajuste, predicción y validación.
`AbsoluteGazeTrackingStrategy` predice `(u,v)` normalizado, y GestureEngine emite
`CURSOR_ABSOLUTE`. ActionMapping conserva ese evento. ControlEngine lo transforma
a `x=u*(ancho-1), y=v*(alto-1)` y usa `moveTo` con paso euclidiano limitado,
tolerancia de vibración y el failsafe original. No hay clic por fijación.

La primera implementación está limitada a un monitor primario con origen (0,0).
La GUI entrega resolución física (geometría Qt multiplicada por DPR), nombre de
pantalla y DPI; el backend debe informar la misma resolución. La calibración
también identifica índice de cámara y resolución real del frame. Un desacuerdo
bloquea activación. Cambios de pantalla/DPI durante control lo detienen desde la
GUI; cambios de tamaño de frame también se verifican en el controlador.
La comprobación no identifica modelo/serial físico de webcam ni distancia exacta.
`main.py` rechaza explícitamente ojos absolutos: por ahora se activan desde Qt,
donde están disponibles estas comprobaciones. El diagnóstico CLI heredado sigue
siendo nasal; usar Diagnóstico de la GUI para ojos.

La captura coloca objetivos en el 10%, 50% y 90% de cada eje, en orden por filas.
Cada uno tiene 1,5 s de cuenta regresiva, 0,6 s de estabilización y una ventana de
al menos 1 s y 20 muestras distintas. Se requieren ambos iris, rostro reciente,
ojos abiertos y estabilidad. Una pérdida limpia la ventana y añade guarda de
180 ms. La dispersión p90−p10 por coordenada ocular debe ser <=0,10; la calidad
mostrada usa `max(0, 1-dispersión/0,10)`. Es un indicador heurístico de estabilidad,
no probabilidad de acierto. Se puede repetir un punto por índice; al repetir un
punto de ajuste se descartan modelo y validación dependientes. Un intento sin
ventana válida en 15 s entra en error repetible. No escribe imágenes/video.

Las características conservan ambos `(iris_x,iris_y)`, nariz, escala facial y
yaw/pitch/roll opcionales. Para el regresor se usa el promedio binocular de dos
coordenadas; los otros valores definen un dominio de abstención. No se aplican
coeficientes de compensación de cabeza inventados. Las señales de cabeza
ausentes se representan como cero en esta versión, una limitación de la puerta.

Sobre las nueve medianas se centra y escala la mirada por eje:

```text
z = (gaze - media_calibrada) / (rango_calibrado / 2)
Phi_lineal = [1, zx, zy]
Phi_cuadrática = [1, zx, zy, zx², zx*zy, zy²]
B = (Phiᵀ Phi + lambda*P)^(-1) Phiᵀ T
lambda = 0,01; P no penaliza el intercepto
```

Se usa `numpy.linalg.solve`, sin invertir explícitamente. Se rechaza rango
insuficiente o matriz degenerada. La selección usa leave-one-target-out sobre
los nueve objetivos; el modelo cuadrático exige mejorar error al menos 10%.
Después se ajusta el seleccionado con los nueve puntos. Este análisis interno
no sustituye la siguiente validación física independiente.

Cinco fijaciones adicionales: `(0,3;0,3)`, `(0,7;0,3)`, `(0,3;0,7)`, `(0,7;0,7)`
y `(0,5;0,3)`, ninguna igual a un objetivo de entrenamiento. Se registran por
zona error horizontal/vertical absoluto medio, euclidiano medio/p95, RMS de
dispersión, deriva entre primer/último cuarto de fijación, rechazos y latencia
de procesamiento de visión. La deriva es intrafijación, no deriva entre sesiones.
No es latencia de extremo a extremo.

La puerta inicial exige error medio global <=10% de diagonal y peor zona <=18%.
Son límites experimentales permisivos para navegación por zonas; NO certifican
seleccionar botones pequeños. La GUI informa error elevado y bloquea guardado
del modelo como aprobado. Es necesario ajustar criterios con datos físicos.
También se abstiene fuera de envolventes calibradas con márgenes explícitos:
0,06 en iris/nariz, 25% de escala (mínimo 0,02) y 10 grados de pose. Estos márgenes
son puertas heurísticas de seguridad, no una probabilidad ni corrección de pose.
Predicciones fuera de [-0,05;1,05] se rechazan; la tolerancia residual se recorta
a pantalla. Un modelo no validado nunca emite posicionamiento real.

El perfil conserva `absolute_calibration` (coeficientes, centro, escala, dominio,
condiciones y validación), separado de `tracking_calibration` (joystick ocular).
`settings.methods` guarda bancos `nose`, `eye` y `eye_absolute` con gesture,
control, calibration, actions, eye y absolute. Las secciones superiores describen
el modo activo para conservar compatibilidad con los entrypoints existentes.
Al guardar un formulario se actualiza el banco vigente; al cambiar selector se
recupera el otro. Conviene guardar una edición antes de cambiar el selector.

`gesture_modes` conserva calibraciones y validación facial por modalidad. La
primera escritura copia el estado histórico a tres bancos independientes; las
lecturas no migran ni reescriben perfiles. Los campos raíz nasales siguen siendo
compatibles. Recalibrar gestos preserva ambos modelos oculares y otros bancos.
Cambiar tiempos invalida solamente la validación de gestos del modo editado.
El guardado sigue validado y atómico mediante ProfileStore.

## Fases 5 y 6 — gestos e interfaz

Se conservan seis gestos y todas las acciones existentes, incluido dictado local
opcional. Sensibilidad, suavizado, acciones, tiempos y calibración se editan por
modalidad guardada. La página Configuración permite neutral, cinco rangos,
nueve puntos y preview absoluto a pantalla completa. La interfaz dibuja una
predicción celeste sin backend del mouse. Los objetivos amarillos son conocidos;
el usuario puede repetir un índice y guardar solo al aprobar.

Activar desde Inicio ahora también pide confirmación explícita, igual que el
botón superior. El comportamiento previo de un clic directo se actualizó y su
test comprueba rechazo/aceptación. F8/Escape y Detener revocan salida al instante;
los atajos no son globales a otras aplicaciones de Windows. No puede cancelarse
una llamada nativa de SO que ya esté ejecutándose.

Capturas de revisión: `screenshots/gaze-calibration-synthetic.png` y
`screenshots/gaze-diagnostic-synthetic.png`, generadas con fijaciones sintéticas.
No representan una medición de mirada real.

## Fase 7 — verificación

Suite inicial: **219 tests, OK**, 18,147 s. Suite final: **251 tests, OK**,
21,489 s, salida de Python 0, ejecutada con `-X faulthandler -u -B`.
Los tests de núcleo absoluto/persistencia, estabilidad y GUI también se ejecutaron
por separado durante la implementación. `app.py --check` offscreen terminó con
salida 0; `compileall` y `git diff --check` pasaron. Se renderizaron y revisaron
las dos capturas sintéticas. El log completo local está en
`data/logs/verification-2026-10-26/final-tests.txt` (ignorado por Git).

Las pruebas cubren geometría/espejo heredados, neutral y rangos, calibración
multipunto, selección de modelo, validación externa, modelos corruptos,
persistencia, bancos, compatibilidad, fracciones, duplicados, guiños, iris perdido,
pantalla/DPI, límites de movimiento, autorización, diagnóstico, cierre y fallos
de cámara/MediaPipe simulados. El backend real está sustituido por mocks.

El smoke nativo pasó con `-X faulthandler`: cargó el modelo local y procesó una
imagen negra mediante callback MediaPipe LIVE_STREAM; no abrió cámara ni ejecutó
acciones del SO. Hubo warnings de feedback tensors del modelo, sin fallo de esa
prueba. Esto no prueba exactitud ocular ni estabilidad durante sesiones largas.

```powershell
.\.venv\Scripts\python.exe -X faulthandler -u -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X faulthandler -B tests/smoke_runtime.py
.\.venv\Scripts\python.exe app.py --check
.\.venv\Scripts\python.exe -B tests/render_gaze_review.py
```

## Fases 8 y 9 — evaluación y siguientes pasos

El laboratorio ahora admite mouse convencional real sin activar HeadMouse,
además de teclado y tres modalidades de HeadMouse. Congela configuración,
calibración y notas de condiciones por serie, junto con los resultados existentes.
La telemetría de calibración multipunto aprobada/fallida queda en
`data/calibration/*.jsonl`, sin muestras oculares individuales.

Seguir [el protocolo experimental](GAZE_EXPERIMENT_PROTOCOL.md). Antes de medir
participantes, el usuario debe ejecutar nueve puntos y validar físicamente los
cinco objetivos, revisar la predicción segura y recién entonces confirmar
control. No se obtuvieron resultados con participantes, no se calcularon mejoras
estadísticas y no se declara precisión física.

Siguiente trabajo guiado por evidencia: analizar logs del cierre original si
reaparece; medir exactitud/deriva a distintas distancias y revisar umbrales de
aceptación; comprobar DPI real de esta PC y disponibilidad binocular; decidir
si hacen falta características adicionales o aislamiento de cámara en proceso.
No aumentar complejidad del modelo antes de esas mediciones.

## Archivos y estado Git de entrega

| Área/fase | Archivos modificados o nuevos |
|---|---|
| Estabilidad (1) | `.gitignore`, `app.py`, `runtime_diagnostics.py`, `desktop/bridge.py`, `application_controller.py`, `control_engine.py` |
| Joystick/gestos (2, 5) | `gesture_engine.py`, `tracking_calibration.py`, `tracking.py`, `control_engine.py` |
| Mapeo absoluto (3) | `gaze_mapping.py`, `tracking.py`, `action_mapping.py`, `application_controller.py`, `control_engine.py` |
| Bancos/compatibilidad (4) | `config.py`, `profiles.py`, `profile_manager.py`, `application_controller.py`, `main.py`, `calibrate.py` |
| Interfaz (6) | `desktop/window.py`, `desktop/gaze_overlay.py` |
| Tests (7) | `tests/test_gaze_mapping.py`, `tests/test_gaze_gui.py`, `tests/test_runtime_stability.py`, `tests/test_home.py`, `tests/test_entrypoints.py`, `tests/render_gaze_review.py` |
| Experimentos (8) | `experiment_engine.py`, `application_controller.py`, `desktop/window.py` |
| Documentación (0, 9) | `README.md`, `docs/ARCHITECTURE.md`, `docs/EYE_TRACKING_EXPERIMENT.md`, `docs/ROADMAP.md`, `docs/EXPERIMENTS.md`, este informe, `docs/GAZE_EXPERIMENT_PROTOCOL.md`, dos PNG sintéticos en `docs/screenshots/` |

Git queda en `experiment/eye-tracking`, mismo HEAD `b663fcc`: **23 archivos
versionados modificados y 11 nuevos sin seguimiento**, todos sin stage/commit.
No se hizo push, merge ni release. Los registros de verificación y diagnóstico
se conservan localmente en rutas ignoradas. No se borraron perfiles/calibraciones
reales ni se reinstaló el entorno. El siguiente paso es el pilotaje físico del
protocolo; la exactitud y los cierres originales permanecen pendientes.

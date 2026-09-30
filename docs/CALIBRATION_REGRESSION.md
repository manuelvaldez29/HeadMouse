# Diagnóstico y reparación de regresión de calibración

Fecha: 2026-09-29. Base investigada: `0422bee`, comparada con `4ccb18a` sin
checkout. Repositorio `C:/Users/juliand/Desktop/headmouse/HeadMouse`, rama
`tesis-v0.2`. Al comenzar, árbol limpio. No se hicieron commits ni push.

## Baseline y alcance de la conclusión

La suite inicial ejecutó 82 tests: 82 aprobados, 0 fallidos, 0 errores, sin
warnings relevantes en esa ejecución. Eso no cubría pérdidas periódicas durante
captura ni una persona que siguiera sosteniendo el gesto después de reconocerlo.
No hay registro de webcam del fallo reportado: las causas siguientes están
demostradas con secuencias deterministas; no se afirma haber identificado todos
los factores de la prueba física.

## Fallos demostrados y cambio que los introdujo

1. **Pérdida breve borra toda la captura.** En `CalibrationSession.update`
   (ahora `_update`), `0422bee` agregó `_reset_window()` ante cualquier muestra
   inválida o neutral fuera del margen. Se borraban muestras y comienzo de la
   ventana. Una pérdida de 50 ms cada 650 ms impedía completar los 4 s iniciales
   y las ventanas de gestos: progreso reiniciado hasta timeout de 30 s. No era
   un bucle literalmente infinito, pero repetir bajo las mismas condiciones
   reproducía el bloqueo. Afectaba neutral y los seis gestos.
   En `4ccb18a`, `Samples.add` omitía el frame inválido sin borrar lo acumulado.
   Ejecutando esa clase histórica en memoria, la misma secuencia avanzó del
   neutral en **4,15 s**. No se restauró el algoritmo anterior.
2. **Ventana termina antes de juntar muestras.** El nuevo `_update` comprobaba
   duración y fallaba inmediatamente si faltaban ocho muestras. A 5 FPS, con
   timestamps válidos separados 200 ms, la ventana neutral terminaba con seis
   muestras y la activa también podía quedar corta. Reintentar no corregía la
   tasa de captura. El mecanismo afecta todos los adaptadores.
3. **Retorno a neutral confundido con gesto incorrecto.** En
   `CalibrationValidation.update`, `0422bee` agregó un fallo cuando la señal no
   se liberaba durante 0,35 s, incluso si era el gesto recién reconocido. Una
   persona que lo sostenía 1,2 s recibía error después del reconocimiento.
   El paso quedaba esperando retry. Antes, el neutral no liberado esperaba;
   el cooldown evitaba otro evento del gesto sostenido. Afecta los seis gestos.
4. **Referencia experimental ausente.** La captura inicial podía terminar sin
   muestras blendshape. Después `_neutral_ok` devolvía siempre False por falta
   de referencia, incluso si reaparecía la señal; repetir solo ese gesto no
   reconstruía el neutral inicial. El mensaje genérico ocultaba la causa.
5. **Snapshot de validación conserva datos de captura.** `snapshot` seguía
   mostrando paso 7, intento 3 y muestras del último gesto, aunque el validador
   avanzaba. `_meter_key` mostraba el gesto siguiente durante el retorno del
   anterior. Era un problema de representación del backend; no se encontró
   desconexión de señales Qt ni reinicio producido por `MainWindow.refresh`.

## Fix acotado

Solo se modifica lógica productiva en `calibration_session.py` y
`calibration_validation.py`. No se modifican el ajuste estadístico, los
extractores, el arbitraje, los umbrales globales, la histéresis ni el esquema.

- Cortes de hasta `validation_noise_s` (0,15 s) pausan captura sin borrar las
  muestras válidas. Los intervalos inválidos no se acumulan como tiempo válido.
  Cortes mayores y saltos de timestamp mayores a `stale_after_s` reinician la
  ventana, conservando repeticiones ya terminadas. El timeout de fase no se
  reinicia por frames: sigue siendo 30 s por defecto.
- Completar una ventana exige **duración válida y mínimo de muestras**. Si la
  duración termina antes, continúa recolectando hasta el mínimo o timeout,
  indicando cuántas faltan. No se aceptan datos insuficientes.
- Antes de terminar el neutral inicial se exigen las señales de todos los
  gestos habilitados. Una fuente ausente se identifica explícitamente y tiene
  timeout/retry; no se cambian escalas mediante un fallback silencioso.
- `returning_from` identifica el gesto recién reconocido y permite soltarlo
  dentro del timeout existente. Un gesto distinto sostenido sigue fallando;
  su temporizador empieza con ese gesto, sin heredar el tiempo del retorno.
- El snapshot presenta fase, progreso neutral y medidor correspondientes a
  validación, sin intentos/muestras obsoletos. Las instrucciones distinguen
  «Esperando gesto», «Detectado. Volvé a neutral», error, timeout y retry.
- DEBUG registra cambios de estado y un resumen como máximo una vez por segundo
  entre transiciones. Incluye estado anterior/siguiente, gesto, repeticiones,
  muestras/requeridas, tiempo válido, señal, referencias y ambos umbrales.

## Máquina de estados auditada

Flujo: START → neutral inicial → [neutral → activo] × 3 por gesto habilitado
→ mediciones completas → validación (neutral → gesto → retorno) → guardar.

| Estado | Entrada, señal y captura | Duración/contador y éxito | Fallo, timeout y salida |
|---|---|---|---|
| `ready` | Constructor; espera comando START | No captura ni repeticiones | Mensaje y botones; `start()` entra a `countdown`, cancelar cierra cámara |
| `countdown/baseline` | `_enter('baseline')`; reloj monotónico | Preparación `countdown_s=3`; no muestras | `_update` cambia a `measuring` al vencer; cancelar disponible |
| `measuring/baseline` | FaceData fresco + extractores disponibles; `Samples.add` y referencias | 4 s válidos y ≥20 muestras únicas; `_advance()` selecciona primer habilitado | Dato malo breve pausa, sostenido reinicia; 30 s → error explícito |
| `settling/neutral` | `_select` o repetición anterior terminada | Transición 0,3 s; no muestras; contador de repeticiones se conserva | `_update` pasa a medición, no resetea el modelo |
| `measuring/neutral` | Señal cruda y `_neutral_ok` contra referencia inicial | 1 s válido y ≥8 muestras; copia `_neutral_rows`, `_enter('active')` | Mismo presupuesto de interrupción/timeout; no usa umbral aún inexistente |
| `settling/active` | Neutral capturado | Transición 0,3 s, sin muestras | `_update` pasa a medición; mensaje de preparación |
| `measuring/active` | Extractor continuo, sin GestureEvent ni cooldown | 0,8 s válidos y ≥8 muestras; `add_repetition`, ajuste provisional | Repeticiones 1→2→3; a la tercera `fit`, calidad débil → error, buena → `_advance` |
| `measured` | Todos los habilitados ajustados; `_build_profile` | Espera explícita de botón Validar | No guarda automáticamente; repetir, omitir o cancelar disponibles |
| `validation/neutral` | `validate`, inicio o gesto reconocido | 2 s de neutral válido; interrupciones ≤0,15 s no suman tiempo | Retorno del gesto aceptado permitido; otro sostenido ≥0,35 s falla; timeout 30 s |
| `validation/gesture` | Neutral completado; GestureEngine real | Hold, histéresis y arbitraje runtime; evento esperado suma `recognized` | Incorrecto aislado tolerado; sostenido ≥0,35 s falla; timeout 30 s; pasa a retorno |
| `validated` | Último retorno neutral completado | `result()` habilita guardar y marca registros validados | Espera explícita de Guardar; nunca se guarda por timeout |
| `error` | Captura insuficiente al timeout, fuente ausente o calidad débil | No sigue capturando datos malos | Retry actual; opcional no disponible; cancelar; validación expone su error aunque el estado contenedor sea `validation` |
| Guardado/cancelación | `ApplicationController.save_calibration` / `stop_camera` | Guardado atómico del perfil validado / liberación de cámara | Error de E/S llega al worker/UI; sin acciones SO durante calibración |

`repeat()` en captura reemplaza solo el modelo del gesto elegido e incrementa
retries; `_enter` limpia solo la ventana. `retry_current()` en validación conserva
reconocimientos anteriores. `restart()` es el único reinicio total explícito.
Los estados de espera humana no tienen timeout automático: muestran la acción
necesaria y permiten cancelar. Los estados automáticos están acotados.

## Señales, relojes y desacoplamiento

| Gesto | Valor crudo | Dirección activa |
|---|---|---|
| LEFT_WINK | `eye_left_ratio` | Disminuye |
| RIGHT_WINK | `eye_right_ratio` | Disminuye |
| LEFT_BROW | `brow_left_lift` o adaptador de fuente izquierda | Aumenta |
| RIGHT_BROW | `brow_right_lift` o adaptador de fuente derecha | Aumenta |
| BOTH_BROWS | Vector de dos canales, capturados juntos | Ambos aumentan |
| MOUTH_OPEN | `mouth_open` | Aumenta |

GEOMETRIC conserva ratios. BLENDSHAPE/HYBRID conservan sus fórmulas y se calibran
y detectan con la misma fuente. No se mezclan ratios con scores 0..1 a mitad de
sesión. Ausencia de fuente devuelve None y ahora impide construir una referencia
vacía con mensaje explícito. Los cinco nombres `browInnerUp`,
`browOuterUpLeft/Right`, `browDownLeft/Right` se verificaron en el modelo local;
el enum instalado asigna sus índices 1–5. No se infirió que una imagen negra
devuelva scores faciales: solo se usa para comprobar la integración nativa.

Adquisición usa `GestureSignal.extract`, no GestureEngine. El ajuste provisional
solo alimenta el medidor; no condiciona aceptar muestras activas. Histéresis,
hold, cooldown y arbitraje se usan al validar/controlar, después del ajuste.
No se encontró una dependencia circular de thresholds durante captura.

VisionEngine marca frames con `time.monotonic()*1000`; sesión, validador y hold
usan reloj monotónico. `time.time()` queda para fechas de telemetría, no duración.
Duplicados no suman muestras ni completan hold. Worker Qt cada 33 ms y refresh
GUI cada 50 ms pueden leer el mismo frame: eso no reinicia repeticiones.
`ControllerWorker.tick → publish → Mailbox → MainWindow.refresh` comunica el
snapshot; casillas/perfiles bloquean señales al reflejarlo. La prueba Qt verifica
publicación y widgets por separado de las pruebas existentes del QThread real.

## Pruebas de regresión y reproducción

`tests/test_calibration_regression.py` incluye el test solicitado
`test_complete_calibration_session_advances_all_phases`: neutral, tres intentos
por cada uno de los seis gestos, ambas cejas propias, validación con hold de
1,2 s y retorno gradual de 0,6 s, `result()` y guardado/carga por controller.
Se ejecuta con y sin pérdidas de frames. También cubre 5 FPS, gesto débil/fuerte,
timeout, retry, opcional omitido, blendshapes ausentes/reaparición, duplicados,
gesto incorrecto sostenido/aislado durante retorno y limitación de logs DEBUG.
Una sesión adicional combina ruido numérico continuo y excursiones breves fuera
del neutral para los seis gestos, verificando tres repeticiones y calidad válida.

Antes del fix, la primera ejecución de seis métodos produjo seis fallos
(incluyendo dos subcasos del test completo): pérdida de progreso, fallo por
muestras, retorno rechazado y ausencia de mensajes específicos. La prueba de
gesto débil ya pasaba. No se presentan fallos de mensajes como causas de captura.
Después del fix esos seis métodos pasaron. Se agregaron controles negativos
adicionales para asegurar que no se acepten errores sostenidos ni esperas infinitas.

`tests/test_calibration_gui_regression.py` conduce el worker y widgets reales
con reloj/cámara sintéticos: 18 intentos visibles, inicio de validación en paso
1, reconocimiento, retorno y siguiente gesto. Verifica que refresh no cambie
estado ni mande comandos. La prueba previa de pérdida de tracking se ajustó
para exigir reset tras una pérdida **sostenida**, manteniendo el control de
duplicados; su expectativa de borrar por un solo frame era parte de la regresión.

Comandos reproducibles desde la raíz, sin webcam:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_calibration*regression.py' -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m compileall -q -x '[\\/](\.venv|\.git|venv)[\\/]' .
.\.venv\Scripts\python.exe -B -m pip check
git diff --check
.\.venv\Scripts\python.exe -B app.py --check
.\.venv\Scripts\python.exe -B tests/smoke_runtime.py
```

Para reproducir físicamente con diagnóstico: `python app.py --log-level DEBUG`
o `python calibrate.py --user <ID> --log-level DEBUG`. Los logs contienen ratios
y estadísticas personales: compartir solo lo necesario, sin imágenes.

Resultados finales verificados: **93 tests aprobados**, 0 fallos, 0 errores,
sin omisiones de Qt; `compileall` sin errores; `pip check`: «No broken
requirements found»; `app.py --check` aprobado. La integración de GUI conserva
las siete pruebas existentes de QThread además de la nueva prueba de publicación.
`tests/smoke_runtime.py` también aprobó: modelo local e inferencia sobre imagen
negra con blendshapes habilitados, sin webcam ni entradas SO. MediaPipe informó
warnings no fatales sobre inicialización del logging y feedback tensors no
soportados; el callback terminó correctamente. `git diff --check` no mostró errores.

## Verificación física y riesgos restantes

No se abrió la webcam ni se enviaron entradas reales al SO. Volver a probar:

1. Neutral y tres repeticiones de **cada uno de los seis gestos**, observando
   intento 1→2→3 y cambio de instrucción. Sostener normalmente, sin apurarse a
   soltar cuando aparece Detectado; volver a neutral de forma gradual.
2. Cortes breves y pérdida sostenida de tracking: pausa breve, reinicio de
   ventana sostenido, timeout explícito, retry y cancelación.
3. Equipo con pocos FPS: contador llega al mínimo sin error prematuro. Si todos
   los frames exceden 250 ms de antigüedad, se rechazan y aparece timeout; no se
   desactivó la protección de frescura.
4. Omitir un gesto, repetir uno débil conservando los demás, validar y guardar;
   comprobar reconocimiento al cargar el perfil guardado.
5. Si se usa BLENDSHAPE/HYBRID, comprobar disponibilidad real de scores y el
   mensaje de ausencia. GEOMETRIC debe avanzar sin blendshapes.
6. Confirmar pausa, acciones y seguridad en una sesión real separada después
   de calibrar; las pruebas sintéticas no miden precisión, fatiga ni latencia física.

El margen de retorno neutral y el ajuste robusto no se relajaron; un neutral
que derive persistentemente puede seguir requiriendo recalibración. Las ventanas
pueden durar más a bajos FPS. La tolerancia breve permite reunir muestras
discontinuas, pero excluye el tiempo perdido y sigue exigiendo calidad y validación.
Si persiste un bloqueo físico, el log ahora distingue fuente ausente, frescura,
neutral, muestras, calidad y retorno, sin atribuirlo automáticamente a las cejas.

# Cámara Logitech C270: inicialización y cierre en Windows

Trabajo del 26/10/2026, sobre `experiment/eye-tracking`, HEAD `b663fcc`.
Se conservaron los 51 archivos locales previos y se respaldaron con ZIP,
manifest SHA-256 y patch en:
`data/logs/checkpoints/pre-camera-20261027T003902970134Z/`.
No se cambió de rama ni se hicieron commits, pushes, merges o instaladores.

## Evidencia y alcance de la reparación

El usuario confirmó video en Cámara de Windows y **30/30 lecturas OpenCV con
DirectShow**. Eso prueba captura física en esa prueba; no prueba el backend que
utilizaba HeadMouse, la carga del grafo o la llegada del callback. No hay base
para atribuir el problema al hardware o afirmar que permisos generales lo causan.

Se inspeccionó `data/logs/headmouse.log`. Hay errores de `wait_ready()` seguidos de
cierre pendiente y aperturas que terminan después de solicitar cancelación. Por
ejemplo, a las 21:27:22.344 se registra la excepción de arranque/cierre, y a las
21:27:22.727 el hilo registra «Cámara 0 abierta». También se conserva el episodio
de las 21:35. El tiempo entre inicio de app y apertura NO permite medir la llamada
de apertura: incluye interacción y imports que antes no tenían marcas separadas.

Causas demostradas en el código anterior y reproducidas con dobles:

- Usaba `VideoCapture(index)` con elección automática; no registraba backend real.
  No se puede deducir retrospectivamente que fuera MSMF.
- El mismo timeout incluía apertura, modelo y callback sin indicar la etapa.
- Después de una apertura nativa lenta no se volvía a comprobar cancelación antes
  de construir MediaPipe. Por eso podían aparecer mensajes de carga tras cancelar.
- El mensaje de join llamaba «driver de cámara» a cualquier hilo aún vivo, aunque
  podía estar dentro de la inicialización o cierre del detector.
- El worker Qt esperaba readiness en una llamada bloqueante. El hilo GUI seguía
  vivo, pero sus comandos encolados de cierre debían esperar esa llamada.
- Una excepción de cleanup podía ocultar el mensaje principal de timeout.

Se corrigieron esas rutas. Después de que el usuario confirmó libre la webcam,
se verificaron captura, inferencia y cierres físicos con DirectShow en tres ciclos
y apertura desde calibración Qt. La causa exacta del backend automático anterior
no quedó medida retrospectivamente. No se tocó la geometría ni las fórmulas de
mirada, nariz o gestos; no se declara validado el seguimiento facial/ocular humano.

## Backend y negociación

`VisionConfig.capture_backend`: `auto`, `dshow`, `msmf`. En Windows, el default
nuevo es `dshow`, apoyado en la prueba concreta del usuario; en otros sistemas,
`auto`. Es una política inicial configurable, no una afirmación de superioridad
de DirectShow para todas las webcams. Una selección ya guardada se respeta.
No hay fallback automático ni cambio de backend mientras la sesión siga activa.

El uso de preferencia de API, `getBackendName()`, propiedades solicitadas y valores
reportados se basa en la [API de VideoCapture](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html).
`set()` no garantiza por sí solo el formato efectivo. Se registran backend,
resolución/FPS reportados por el driver y tamaño REAL del frame recibido.
Los FPS de captura y de resultados procesados se muestran por separado.

La configuración agrega `frame_width`, `frame_height` (cero/cero = negociación
del dispositivo) y `shutdown_timeout_s`. El timeout inicial predeterminado pasa
a 20 s, pero perfiles existentes que guardaron 10 s conservan ese valor hasta
editarlo. No se sobrescribieron perfiles para alterar sus límites.

Configuración ofrece **Preparar prueba C270 · DirectShow · 640 × 480 · 15 FPS**.
El botón solo prepara el formulario; Guardar lo aplica y detiene los motores.
El ejemplo JSON también usa esos valores. El default de FPS del motor sigue en
30 para conservar el comportamiento previo cuando no se elige el preset.
Cambiar FPS puede cambiar la velocidad percibida del joystick, dependiente de
frames; no se ajustaron sus fórmulas. Cambiar resolución puede exigir recalibrar.

## Readiness y máquina de estados

```text
CREATED → CAMERA_OPENING → CAMERA_OPEN → FIRST_FRAME
  → MEDIAPIPE_INITIALIZING → MEDIAPIPE_READY → FIRST_SUBMISSION
  → FIRST_RESULT → READY
  ↘ RECOVERABLE_ERROR (lectura recuperable)
  ↘ TERMINAL_ERROR
  → CLOSING (detector_close / camera_release) → STOPPED
```

Cada marca incluye tiempo monotónico desde creación, operación en curso y duración
de la operación previa. El diagnóstico conserva un timeline acotado, contadores,
resolución/FPS solicitados/reportados y tamaño efectivo, sin imágenes ni landmarks.

El motor prueba primero una lectura OpenCV antes de cargar MediaPipe para aislar
esas etapas. Descarta ese primer frame de prueba al terminar la carga, porque
podría haberse envejecido, y envía una captura nueva. Una lectura inicialmente
vacía se puede recuperar dentro del plazo inicial: el límite normal de fallos
consecutivos no corta prematuramente el calentamiento de la webcam.

Readiness requiere las tres condiciones: **frame recibido, detector creado y
resultado extraído/publicado**. Una inferencia correcta sin rostro también cuenta
como pipeline preparado: la presencia de rostro/iris y la autorización siguen
siendo condiciones independientes para calibrar o ejecutar acciones.
La API asíncrona y callback siguen el contrato de
[MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python).
No se supone un resultado por cada captura; puede haber frames omitidos.

`ready` despierta a quien espera tanto al completar como al cancelar/fallar.
`wait_ready()` comprueba cancelación, error y el evento interno de usabilidad;
la GUI usa `camera_status.ready`, no el simple estado de ese evento de despertar.
Un timeout invalida el motor y nombra la etapa, operación y contadores. Un
callback retrasado, incluso si ya estaba extrayendo al cancelar, no puede publicar
FaceData ni restaurar readiness. Hay una regresión para esa carrera.

## Arranque Qt, cierre y recuperación

El worker inicia la captura sin bloquearse en `wait_ready()`. Publica
`CAMERA_STARTING` y consulta readiness con su timer; la acción de calibrar,
diagnosticar o activar se difiere hasta estar preparado. Detener/cerrar cancela
el comando pendiente antes de cualquier reintento. Una activación conserva su
autorización explícita y se revoca al detener, también durante el arranque.

`request_stop()` solo cambia eventos y anula datos; no llama a close/release
desde Qt. El propietario de VideoCapture y del detector sigue siendo VisionEngine:
comprueba cancelación después de apertura, primera lectura y creación del grafo;
cierra detector y cámara en su propio hilo, en ese orden.

Si vence el join, el error indica, por ejemplo, `detector_init`, `camera_read`,
`detector_close` o `camera_release`. Se conserva la referencia y no se permite
abrir otra cámara sobre recursos vivos. El estado de error conserva el diagnóstico
principal y no procesa eventos faciales ni salida al SO. Después de cerrar el
propietario anterior, se puede iniciar otro motor y una nueva calibración.

No se usa `terminate()`, ni release cruzado, ni descarga de modelos al arrancar.
Si una llamada nativa nunca retorna, una Event no puede cancelarla de forma
segura. El cierre puede quedar pendiente: el proceso espera al propietario y no
promete un deadline de terminación. Aislar captura/inferencia en un proceso
supervisado es una alternativa posterior si los nuevos registros demuestran
ese bloqueo; no se introdujo ahora una arquitectura de procesos sin evidencia.

## Pruebas automatizadas

Inicio: **279 tests, OK, salida 0**, 30,267 s. Verificación intermedia de la misma
suite tras integrar captura/worker: **279 tests, OK, salida 0**, 32,867 s.
Se agregaron regresiones de motor, controlador y Qt para apertura, calentamiento,
primer frame tardío, detector lento/erróneo, callback tardío/ausente, carrera al
cancelar, propietario de cierre, read bloqueado, fallo de lectura posterior a ready,
backend explícito, doble apertura, cierre fallido, recuperación y nueva calibración.

Resultado final: **300 tests, OK, salida de proceso 0**, 36,605 s.
Log completo: `data/logs/camera-final-tests.txt`. Hay 19 regresiones de motor/
controlador y dos de Qt adicionales a los 279 tests iniciales. Un intento de
desarrollo con una expectativa incorrecta en un test quedó conservado en
`data/logs/camera-test-expectation-corrected.txt`; se corrigió y la suite completa
se volvió a ejecutar. No se contó una ejecución fallida como éxito.
Los tests usan cámaras/detectores simulados y backend del mouse mock.

Además se ejecutó `tests/smoke_runtime.py` con MediaPipe REAL y VideoCapture
SINTÉTICO, sin abrir webcam. En una ejecución observada, detector preparado y
primer resultado alrededor de 0,031 s, detenido alrededor de 0,094 s, salida 0.
Esos tiempos pertenecen a una imagen negra en RAM y NO a la C270 ni a una cara.
`app.py --check`, compilación de fuentes y ayuda del diagnóstico también pasaron.

## Pruebas físicas realizadas

Al principio se detectó una instancia antigua de HeadMouse iniciada a las 21:35
(PID Python 6296 y lanzador 38320). No se cerró ni se mató automáticamente.
Posteriormente el usuario confirmó que todas las aplicaciones de cámara estaban
cerradas; se comprobó que esos procesos ya no existían y se ejecutó el diagnóstico.

**C270, DirectShow, tamaño real 640×480, 15 FPS de procesamiento**, tres ciclos
con cinco segundos de observación cada uno, sin mouse. Resultado: **3/3 OK,
salida de proceso 0**. El driver reportó 15,000015 FPS nominales.

| Ciclo | Cámara abierta (s) | Primer frame (s) | Carga MediaPipe (s) | Primer resultado (s) | Frames / resultados | Cierre (s) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0,969 | 3,266 | 0,062 | 3,359 | 77 / 76 | 0,485 |
| 2 | 0,797 | 3,140 | 0,032 | 3,218 | 76 / 75 | 0,329 |
| 3 | 0,796 | 3,093 | 0,032 | 3,171 | 77 / 76 | 0,313 |

Tiempos desde creación del motor excepto carga del grafo y duración de cierre.
La negociación de propiedades tomó alrededor de 2,2 s; en esta configuración el
tiempo dominante no fue la carga del grafo. Esto no demuestra qué ocurría con el
backend automático del código anterior. No se probó ese backend en paralelo.

Evidencia local: `data/logs/c270-hardware-run.txt` y
`data/logs/camera-diagnostic-20261027T005911782798Z.json`.

También se probó la apertura REAL desde el worker de Qt con un perfil temporal,
sin persistir calibración ni crear el backend del mouse. Llegó a `EYE_CALIBRATING`,
primer resultado a los 3,360 s desde crear el motor, 121 frames / 120 resultados,
15 FPS, cierre limpio y salida 0. **No se detectó rostro; neutral no completado,
cero muestras aceptadas.** Esa ausencia no se interpreta como defecto del modelo
sin confirmar si el usuario estaba frente a la webcam.

Evidencia: `data/logs/c270-calibration-hardware-run.txt` y
`data/logs/camera-calibration-check-20261027T010117769070Z.json`.
La prueba es reproducible con `tests/smoke_camera_calibration.py --confirm-camera-free`;
usa Qt offscreen, cámara física, fuente `both` por defecto y perfil temporal que
descarta al cerrar. No requiere la presencia de rostro para aprobar APERTURA y
CIERRE; `neutral_ready` y `face_observed` se reportan por separado.

## Repetición manual y validación humana pendiente

1. Cerrar HeadMouse anterior, Cámara de Windows y cualquier otra app de cámara.
   Confirmar que terminaron. Si el HeadMouse anterior queda esperando un cierre
   nativo, no iniciar otra captura en paralelo; conservar logs y reportar ese estado.
2. Desde este repositorio ejecutar el diagnóstico serial, sin control del mouse:

```cmd
.venv\Scripts\python.exe -X faulthandler -u camera_diagnostic.py --backend dshow --width 640 --height 480 --fps 15 --startup-timeout 20 --duration 5 --cycles 3 --confirm-camera-free
```

3. Cada ciclo debe informar `backend_effective=DSHOW`, frames OpenCV >0,
   `processed_results` >0, `ready=true` antes del cierre y `stopped=true` después.
   Revisar formato solicitado, reportado y real; no presumir que el driver aceptó
   15 FPS. El JSON de `data/logs/camera-diagnostic-<UTC>.json` conserva los tres ciclos.
   La latencia inicial es `timeline.FIRST_RESULT`; el tiempo del grafo se deriva
   entre `MEDIAPIPE_INITIALIZING` y `MEDIAPIPE_READY`. No mide latencia ocular real.
4. Si falla un ciclo, no se abre el siguiente. Si el cierre queda pendiente, el
   informe se escribe antes de esperar; se conservan referencias y no se fuerza
   destrucción. No abrir otro diagnóstico mientras ese proceso siga vivo.
5. Con diagnóstico ya cerrado, ejecutar la aplicación:

```cmd
.venv\Scripts\python.exe -X faulthandler -u app.py
```

6. Seleccionar perfil, Configuración → preset C270 → Guardar. Abrir cámara y
   comprobar estados, formato, FPS y señales en Diagnóstico. No activar control
   para esta prueba. Iniciar calibración facial y ocular; comprobar que comienza
   después de READY y que registra la fuente elegida.
7. Detener/cancelar durante arranque, cerrar cámara y reabrir tres veces, una de
   ellas desde calibración. Probar nariz y las seis combinaciones oculares en
   diagnóstico, sin sobrescribir calibraciones válidas con pruebas incompletas.
8. Registrar duración de apertura/primer frame/grafo/primer resultado/cierre,
   contadores por ciclo, texto de error si lo hay, y rutas de logs. Si cambiar
   resolución invalida el modelo anterior, recalibrar únicamente la fuente elegida.

El diagnóstico importa VisionEngine, pero nunca ControlEngine ni construye
PyAutoGUI; no tiene opción de mover/clicar. La captura no guarda imágenes/video.
`--confirm-camera-free` exige confirmar que otras capturas están cerradas; no
detecta automáticamente exclusividad de hardware entre procesos externos.

## Archivos principales y siguiente paso

`vision_engine.py`, `config.py`, `config.example.json`, `application_controller.py`,
`desktop/bridge.py`, `desktop/window.py`, `camera_diagnostic.py`,
`tests/test_camera_startup.py`, `tests/test_camera_gui.py`, adaptaciones de fixtures
en `tests/test_gui.py`/`tests/test_safety.py` y ampliación de `tests/smoke_runtime.py`.

El siguiente paso es validar rostro, señales, neutral/modelo ocular e interacción
desde la GUI con el usuario presente, y sesiones más largas. Captura/inferencia/
cierre con la C270 y DirectShow ya tienen la evidencia física limitada anterior;
eso no demuestra precisión ocular ni resuelve por sí solo todo cierre intermitente.
No iniciar integración ni instalador.

Git de entrega: `experiment/eye-tracking`, mismo HEAD `b663fcc`, **33 archivos
versionados modificados y 27 nuevos sin seguimiento** (60 en total), sin stage,
commit ni push. Se verificaron los hashes del respaldo de los 51 archivos de
partida y su presencia. Geometría ocular, características/modelos, estrategias,
gestos, ControlEngine y persistencia ocular permanecen idénticos a ese respaldo;
la reparación se limita a captura, configuración, coordinación, interfaz y pruebas.

## Seguimiento posterior: rostro visible y prueba coordinada

El usuario confirmó que estaba visible durante el intento anterior. Se investigó
sin dar por hecho que su ausencia fuera una condición del usuario:

1. Un probe independiente registró **121 callbacks sin landmarks crudos**. No
   había rostros que HeadMouse estuviera descartando durante validación.
2. En modo IMAGE, las variantes de orientación/espejo y los cambios de iluminación
   probados solo en memoria tampoco obtuvieron landmarks en ese frame de cámara.
   No se aplicaron esos cambios ni umbrales inferiores a la aplicación.
3. El mismo modelo local detectó un rostro y **478 landmarks válidos** en cada
   una de dos imágenes públicas de referencia usadas por MediaPipe,
   [portrait.jpg](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/test/vision/face_landmarker_test.py)
   y el retrato del [ejemplo oficial](https://github.com/google-ai-edge/mediapipe-samples/blob/main/examples/face_landmarker/python/%5BMediaPipe_Python_Tasks%5D_Face_Landmarker.ipynb).
   La extracción propia también produjo `FaceData` válida y señal de iris en
   ambos casos. Las referencias se descargaron a RAM, sin subir imágenes del usuario.
4. Tras coordinar un «Listo» con el usuario frente a la C270, la prueba física
   produjo **150/150 resultados con rostro, extracción válida y datos válidos;
   146/150 con señal de iris disponible**, durante aproximadamente diez segundos
   de observación. Cierre limpio y salida 0. No se cambiaron modelo, umbrales ni
   fórmulas entre el probe sin rostro y esta prueba. Por tanto, no se atribuye la
   diferencia a una reparación del detector ni se afirma una causa ambiental no medida.
5. Otra apertura real mediante Qt inició neutral ocular con rostro observado,
   pero **no completó el neutral en la ventana de ocho segundos**. El campo
   `samples=0` del informe representa la ventana vigente al terminar, no una
   medida acumulada de todas las muestras recibidas. La calibración se descartó
   junto con su perfil temporal. No se declara calibración aprobada ni precisión.

Evidencia local, sin imágenes de webcam ni landmarks persistidos:

- `data/logs/face-pipeline-probe-20261027T010911330401Z.json`
- `data/logs/face-image-comparison.json`
- `data/logs/reference-face-check.json` y `reference-face-extraction.json`
- `data/logs/face-conditions-check.json` (condiciones de diagnóstico, no parámetros aplicados)
- `data/logs/controlled-face-check-20261027T011506879901Z.json`
- `data/logs/camera-calibration-check-20261027T011530145690Z.json`

Para no confundir estos casos en adelante, VisionEngine y Diagnóstico agregan
`raw_face_results`, `valid_face_results`, `rejected_face_results` y `face_status`.
Los estados distinguen ausencia de landmarks, rechazo geométrico, FaceData
inválida y rostro válido. Son contadores/etiquetas, sin debilitar validaciones,
autorización, filtros o failsafe. Una regresión prueba las cuatro posibilidades.

Verificación posterior: **301 tests, OK, salida 0, 35,069 s**, log
`data/logs/face-followup-tests.txt`. Se conservaron los 60 archivos de partida
de este seguimiento en `data/logs/checkpoints/pre-face-20261027T010857867454Z/`.
No se hicieron commits/push ni se alteraron perfiles o calibraciones reales.
Queda validar y guardar el neutral y el modelo ocular desde la GUI con el usuario,
además de evaluar estabilidad prolongada. La detección física de rostro y señal
ocular sí tiene ahora la evidencia limitada de la prueba coordinada.

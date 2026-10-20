# Experimento de tracking ocular relativo

## Estado y objetivo

Rama local: `experiment/eye-tracking`, creada desde
`32caef6fd14401b7520036cfd2267daa145da81a` de `tesis-v0.2`, después de un
`pull --ff-only`. La rama no existía localmente ni en origin al crearla.
No se realizó commit, push ni merge del experimento.

Primera etapa: joystick de velocidad por desviación ocular respecto de un
neutral. No estima el punto de pantalla observado. Nariz sigue siendo el
default y se conserva su fórmula. No hay resultados físicos ni evaluación con
personas de este experimento; las comprobaciones son sintéticas.

## Auditoría previa

Se revisaron tracking, visión, FaceData, GestureEngine, controlador,
configuración, perfiles, desktop (bridge, ventana, widgets, estilos),
ExperimentEngine y sus tests. La base actualizada pasó **188 tests** antes de
editar. El flujo previo era:

```text
MediaPipe LIVE_STREAM (imagen ya espejada)
  → VisionEngine._extract / callback / último snapshot bajo lock
  → FaceData (inmutable, timestamp monotónico)
  → NoseTrackingStrategy.position (landmark 1)
  → GestureEngine (EMA, dead zone, aceleración, CURSOR_MOVE)
  → ActionMapping → ControlEngine (autorización, pausa, límites, failsafe)
```

La cámara ya entregaba landmarks de iris, pero no se extraían. Había apertura
de párpados, cejas 2D/3D y head_pitch/yaw/roll aproximados. Faltaban coordenadas
oculares relativas, disponibilidad por ojo, neutral ocular y una estrategia
que las interpretara. El recentrado nasal también ajusta umbrales de gestos;
por eso no debe usarse para recentrar los ojos.

## Arquitectura

```text
VisionEngine → eye_geometry.extract_gaze → FaceData
                                             ↓
                                   EyeGazeTrackingStrategy
                                             ↓
                         GestureEngine._update_eye_cursor
                                             ↓
                           CURSOR_MOVE → ControlEngine

EyeTrackingCalibrationSession → TrackingCalibration → perfil.tracking_calibration
```

`eye_geometry.py` usa objetos con x/y, sin importar MediaPipe. El filtro y la
curva de velocidad siguen en GestureEngine; la estrategia normaliza el desvío
contra el neutral/rango, sin inferencia ni acciones del sistema. Ambos métodos
implementan `TrackingStrategy.position`: una posición utilizable o `None`.
Nariz devuelve exactamente nose_x/nose_y como antes.

Los detectores de LEFT_WINK, RIGHT_WINK, LEFT_BROW, RIGHT_BROW, BOTH_BROWS y
MOUTH_OPEN mantienen sus señales, gates, thresholds, arbitraje, acciones y
calibración. La puerta de movimiento de cejas sigue midiendo cabeza/nariz,
también en modo eye. El historial facial guarda nariz y el recentrado se
rechaza en modo eye; nunca ajusta neutral ocular ni umbrales faciales.

## Landmarks y fuentes

El paquete actual de Face Landmarker estima 478 landmarks, según la
[guía oficial](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker).
Las conexiones de iris pueden consultarse en el
[código oficial de FaceLandmarker](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/vision/face_landmarker.py).
Los centros 468/473 y la agrupación de los diez puntos también están en el
[grafo oficial de refinamiento](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/modules/face_landmark/tensors_to_face_landmarks_with_attention.pbtxt).
La fórmula de joystick de esta rama es una decisión propia, no una función de
gaze absoluto provista por MediaPipe.

| Lado histórico del proyecto | Comisuras | Superior / inferior | Centro iris | Contorno iris |
|---|---|---|---|---|
| left | 33, 133 | 159, 145 | 468 | 469–472 |
| right | 362, 263 | 386, 374 | 473 | 474–477 |

Se mantienen los nombres históricos de apertura de ojos de HeadMouse para no
renombrar gestos. En las conexiones oficiales, 469–472 se llama RIGHT_IRIS y
474–477 LEFT_IRIS; no interpretar left/right de esta tabla como un cambio de
lateralidad anatómica. Verificar con una persona frente al preview espejado.

## Fórmula de mirada relativa

Convertir x/y normalizadas a píxeles con ancho y alto reales; así un frame no
cuadrado no deforma los ángulos. Sean A/B las comisuras ordenadas por X de la
imagen, U/L los párpados superior/inferior e I el centro del iris:

```text
h = B - A
v = L - U
D = cross(h, v)
x_eye = cross(I - A, v) / D
y_eye = cross(h, I - U) / D
```

Esto resuelve coordenadas en la base ocular incluso con inclinación moderada
en el plano de imagen. Traslación y escala común se cancelan algebraicamente;
los tests verifican esa propiedad en geometría sintética. No garantiza
invariancia a yaw/pitch, perspectiva, movimiento de párpados ni error del modelo.

El extractor recibe `mirrored`: True en VisionEngine, porque cv2.flip ocurre
antes de inferir. Con entrada sin espejo invierte X (`1-x_eye`) para mantener
la misma convención de dirección del usuario. El preview conserva sus
coordenadas de imagen originales. No se modifica el espejo del modo nasal.

Se exige ancho ocular >=2 px y D > 0.08·ancho². Se descartan coordenadas no
finitas, fuera de [0,1], apertura degenerada/cerrada, centros fuera del ojo y
contornos de iris incompletos/ilegibles. Cada ojo falla de manera independiente.
Con dos ojos se promedian las coordenadas; con uno se usa ese ojo.

## FaceData

Campos nuevos, al final del dataclass para preservar argumentos anteriores:

- left_gaze_x/y y right_gaze_x/y: [0,1] o None por ojo.
- gaze_x/y: señal combinada [0,1] o None.
- gaze_confidence: 1 con ambos ojos, .5 con uno y 0 sin datos.
- iris_points: centros normalizados para dibujar, tupla volátil.
- gaze_available: propiedad validada; False sin rostro válido o sin señal
  completa y finita. No es suficiente por sí sola: el consumidor exige frescura.

La confianza representa **cobertura**, no precisión ni probabilidad de
MediaPipe. Los datos oculares opcionales se validan aparte de FaceData.valid:
un fallo de iris no invalida nariz y gestos. Un fallo de coordenadas faciales
base sí conserva el bloqueo de seguridad previo. Las observaciones y muestras
quedan en RAM; no se persisten iris, imágenes ni video.

## Calibración y perfiles

`EyeTrackingCalibrationSession` recoge ambos ojos abiertos durante al menos
2 s y 20 muestras únicas. Usa timestamp monotónico, comprueba frescura y exige
una ventana con rango máximo .06 por eje. Pérdida de señal o brecha de frames
reinicia la ventana; el timeout total de 20 s nunca se reinicia por pérdida.
A pocos FPS se extiende la ventana hasta reunir el mínimo de muestras: a 5 FPS
son unos 4 segundos. El progreso exige tanto duración como cantidad.
Con captura a 30 FPS se conserva el frame anterior al borde temporal para
evitar esperar una duración que no sea múltiplo exacto de un frame.

El resultado `TrackingCalibration` se guarda explícitamente en
`profile.tracking_calibration`, por reemplazo atómico del ProfileStore existente:

```json
{
  "method": "eye", "schema_version": 1,
  "neutral_x": 0.5, "neutral_y": 0.5,
  "left_range": 0.2, "right_range": 0.2,
  "up_range": 0.2, "down_range": 0.2,
  "ranges_measured": false
}
```

Se persiste el neutral agregado, no las muestras. En esta etapa los cuatro
rangos son **nominales**, no extremos medidos. La captura guiada de extremos
cómodos queda pendiente. El esquema permite separarlos después. Calibrar gestos
desde el controlador conserva esta sección independiente. Cancelar una nueva
captura ocular conserva la calibración anterior.

Perfiles anteriores sin tracking_method usan nose. Seleccionar eye no exige
alterar su validación facial. Activar control o iniciar mediciones headmouse
sin neutral ocular se rechaza; el diagnóstico permanece disponible para
inspeccionar señal. Configuración permite volver a nariz en cualquier momento,
cerrando los motores antes de reconstruirlos y sin activar control por sí sola.

## Joystick y parámetros

La estrategia resta neutral y divide cada desvío por el rango correspondiente
según su signo, limitando la salida a [-1,1]. GestureEngine aplica:

```text
smooth = alpha·anterior + (1-alpha)·desvío_normalizado
d = signo(smooth)·max(0, abs(smooth)-dead_zone)
delta = limitar(d·sensitivity + d·abs(d)·acceleration, ±max_delta)
```

`settings.eye`: sensitivity=12, acceleration=8, dead_zone=.15,
smoothing_alpha=.65, max_delta=20 px/detección. Son valores iniciales a medir,
independientes de settings.gesture. También sigue el tope de ControlEngine
(60 px por defecto). Velocidad depende de la frecuencia de detecciones, igual
que el modo nasal; no se introdujo un protocolo temporal distinto aquí.

Una señal ocular inválida borra inmediatamente el EMA ocular y no emite
CURSOR_MOVE, sin cola del filtro que empuje hacia una esquina. Rostro perdido,
datos vencidos o FaceData inválido conservan el reset previo. El control inicia
desactivado, requiere autorización explícita y mantiene pausa, failsafe y F8.
Los gestos pueden seguir funcionando con iris ausente si la cara es válida.

## GUI y diagnóstico

Configuración ofrece Nariz / Ojos — Experimental, aviso de modo experimental,
parámetros oculares y una sección **Calibrar tracking ocular**, con preview,
progreso, guardar y cancelar. El inicio guía hacia esa captura si falta neutral.
La sección tiene acceso directo y desplazamiento automático al estado de
captura; Diagnóstico usa scroll para mantener el contenido accesible en ventanas
compactas.
La calibración normal de gestos mantiene su página y su motor.

Diagnóstico muestra ambos pares de gaze, señal combinada, cobertura y
disponibilidad efectiva (incluye frescura), método activo, neutral ocular,
desvío suavizado en unidades de rango, dead zone, yaw/pitch y que no hay
compensación de pose. Los centros de iris aparecen en el preview con landmarks
habilitados. Los valores faciales/nasales existentes siguen identificados.
No se construye backend de mouse en diagnóstico ni durante calibración.

El CLI main.py respeta tracking_method y exige neutral antes de abrir la cámara
en modo eye. El script histórico debug_cursor.py continúa siendo el diagnóstico
nasal; para diagnóstico ocular se usa la GUI.

## ExperimentEngine y métricas

Los registros de adquisición JSONL incluyen tracking_method=nose/eye para
headmouse; para entrada manual por teclado vale null. No se cambia secuencia
de objetivos, radios, tiempo límite ni criterio de selección. Jitter utiliza
la estrategia elegida: normalized_frame para nariz, comfortable_eye_range para
ojos. Sus valores crudos NO son directamente comparables entre unidades.

Comparar en tareas iguales: tasa de finalización, tiempo hasta objetivo,
clicks fallidos, overshoots, distancia del cursor, jitter en pantalla y FPS.
processing_ms es latencia del pipeline, no latencia física extremo a extremo.
Medir precisión angular/píxeles respecto de objetivos con ground truth y
recoger esfuerzo/fatiga con una escala explícita; esas medidas físicas no se
deducen de confidence. Contrabalancear el orden nariz/ojos y guardar condiciones
de luz, distancia, cámara, DPI, parámetros y duración.

El contador de pérdidas de tracking de SessionMetrics sigue describiendo
pérdida de rostro/frescura, como en la baseline; no separa fallos de iris.
La disponibilidad ocular se ve en Diagnóstico. Medir tasa/duración de pérdida
de iris en sesiones comparativas requiere añadir esa métrica explícitamente.

## Limitaciones y pruebas manuales pendientes

La normalización geométrica reduce dependencias de traslación/escala en el
modelo ideal; no elimina acoplamiento de cabeza en una webcam real. Se dispone
de head_pitch/yaw/roll, pero no se implementó compensación. Una extensión
posible sería un adaptador de features con coeficientes estimados y comparación
on/off; no aplicar coeficientes inventados ni afirmar mejora sin medirla.

Parpadeos, guiños, párpados móviles, reflejos de lentes, oclusiones y estimaciones
incorrectas pero finitas pueden distorsionar el gaze. Cambiar de dos ojos a uno
puede cambiar el sesgo si difieren las señales; la cobertura no cuantifica ese
error. La calibración neutral actual requiere ambos ojos; una persona con solo
un ojo utilizable necesita una futura captura monocular explícita. Usar ojo
único durante tracking no certifica accesibilidad monocular completa.

Prueba con una persona, empezando en Diagnóstico seguro:

1. Nariz: abrir un perfil anterior, verificar neutral, movimiento, gestos,
   scroll, dictado y recentrado según su comportamiento previo.
2. Ojos: seleccionar método, guardar settings, capturar neutral cómodo,
   comprobar derecha/izquierda/arriba/abajo y ausencia de deriva en reposo.
3. Parpadear y hacer guiños; tapar un ojo y después ambos. Verificar que sin
   señal no hay movimiento y que recupera sin saltos del EMA.
4. Trasladar suavemente la cabeza y cambiar distancia; luego yaw/pitch/roll.
   Cuantificar deriva residual en vez de inferir robustez física por los tests.
5. Repetir con distintas luces, lentes, distancia y postura; guardar nuevos
   neutrales cuando cambie la cámara. Revisar fatiga y comodidad.
6. Tras comprobar diagnóstico, activar explícitamente: límites, pérdida de
   rostro, pausa por gestos, F8, detener, cierre y failsafe. Probar DPI/monitores.
7. Comparar tareas y esfuerzo, incluyendo errores por sesgo binocular/monocular
   y adaptación de sensibilidad. No reemplazar la baseline sin esos resultados.

## Evolución a gaze absoluto de nueve puntos (no implementada)

Presentar una cuadrícula 3×3 con fijaciones conocidas en coordenadas de pantalla.
Separar un futuro método/mapeador del joystick y una versión nueva de
TrackingCalibration. Recoger por punto features de ambos iris + pose, descartar
parpadeos y transitorios y estimar un mapeo local ligero (p. ej. regresión ridge
lineal/polinómica) a screen X/Y. No requiere cloud ni red neuronal pesada.

Reservar fijaciones o sesiones de validación fuera del ajuste, medir error y
deriva, detectar condiciones fuera de calibración, aplicar límites/abstención
y conservar joystick/nariz como alternativas. Validar con personas, distancias,
DPI y monitores diferentes antes de habilitar control absoluto. Faltan tanto
la captura de nueve puntos como el ajuste, validación y evaluación física.

## Validación automatizada

Base: 188 tests aprobados. Se agregan `tests/test_eye_tracking.py` (29 tests) y
`tests/test_eye_gui.py` (2 tests Qt), sin cámara real, mouse real ni personas.
Cubre geometría, contrato, direcciones, espejo, traslación/escala/roll,
binocular/monocular, ausencia, inválidos, filtro, límites, perfiles anteriores,
cambio de método, calibración con timeout (también a 5 FPS), persistencia,
conservación del neutral ocular al guardar gestos, selección de estrategia en
CLI y diagnóstico seguro.

Comandos de revisión desde la raíz, con el entorno local:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_eye*.py' -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m compileall -q -x '[\\/](\.venv|\.git|venv)[\\/]' .
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe app.py --check
.\.venv\Scripts\python.exe tests/smoke_runtime.py
```

Resultado final del 2026-10-17:

| Verificación | Resultado |
|---|---|
| Suite completa antes de implementar | 188 tests OK |
| Tests nuevos por separado | 31 tests OK, 16.606 s |
| Suite completa final | 219 tests OK, 83.087 s, sin fallos/errores/skips |
| compileall | OK |
| pip check | No broken requirements found |
| git diff --check | OK |
| app.py --check | OK, sin webcam/control |
| tests/smoke_runtime.py | PASS, callback MediaPipe real sin webcam/acciones SO |

El smoke usa el modelo real con una imagen negra en RAM: comprueba importación
y callback, no detección ocular física. Dependencias observadas: MediaPipe
1.0.1, OpenCV contrib 5.0.0.93, NumPy 2.5.3 y PyAutoGUI 0.9.54. El runtime
imprime avisos nativos de XNNPACK/feedback tensors, sin fallo del smoke.

## Inventario de archivos

Nuevos (5): eye_geometry.py, tracking_calibration.py,
tests/test_eye_tracking.py, tests/test_eye_gui.py y este documento.

Modificados (14): tracking.py, vision_engine.py, face_data.py, gesture_engine.py,
application_controller.py, config.py, profiles.py, main.py, experiment_engine.py,
desktop/bridge.py, desktop/window.py, desktop/widgets.py,
docs/ARCHITECTURE.md y docs/ROADMAP.md.

No se edita el motor estadístico ni la sesión/validación/arbitraje de gestos,
sus extractores ni ControlEngine. Los archivos de tests existentes se conservan.

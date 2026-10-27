# Fuentes oculares — Etapa A, 26/10/2026

Estado: implementación y verificación automatizada completas; pilotaje físico
pendiente. No se realizaron commits, pushes, merges, cambios de rama ni releases.
Las etapas de integración e instalador siguen condicionadas al pilotaje y a la
autorización del usuario. Este documento actualiza el informe de continuación
anterior; conserva sus limitaciones de precisión y de cierre físico sin resolver.

## Protección del trabajo de partida

Se confirmó `experiment/eye-tracking`, HEAD
`b663fcc5165bedf03e041e63f70d63434bd006a4`, con los 34 archivos previos intactos
al inicio. Antes de editar se guardaron ZIP, hashes SHA-256 y patch binario en:

`data/logs/checkpoints/20261026T234635579986Z/`

El ZIP conserva tanto archivos versionados modificados como nuevos sin seguimiento.
El respaldo es local e ignorado por Git; no incluye `.venv` ni perfiles personales.
No hubo reset, clean ni sustitución del árbol por una rama histórica.

## Diseño y comportamiento

Se conservan exactamente tres métodos: `nose`, `eye`, `eye_absolute`. El selector
independiente `settings.ui.eye_source` acepta `both` (predeterminado), `left` o
`right`. Es una selección explícita persistente, compartida por los dos métodos
oculares; no es un modo de cierre físico de un ojo. Al cambiar método/fuente y
guardar, se detienen motores y se reconstruyen estrategia y filtros. Los bancos
de parámetros, acciones y calibración facial por modalidad se mantienen.

`gaze_source.py` centraliza selección, validación de cada iris, promedio binocular,
apertura del ojo elegido y lateralidad. La fuente `both` exige dos pares válidos
y usa media aritmética con pesos iguales; no hay confianza por iris con la que
justificar otros pesos. Si falta uno, se detiene y explica el bloqueo. No hay
fallback monocular implícito.

En `left`/`right` se lee exclusivamente el par del ojo seleccionado. Un NaN,
ausencia o cambio del iris no elegido no interviene en las características ni en
la predicción. La validación global de rostro/frescura y la seguridad del backend
siguen vigentes. Los gestos siguen usando ambos párpados cuando están disponibles.

### Lateralidad anatómica y espejo

Se conserva `cv2.flip(frame, 1)` ANTES de MediaPipe para no modificar el joystick
nasal. `FaceData.gaze_mirrored` registra esa convención; el default `true` conserva
la interpretación del pipeline existente. El grupo histórico `left` usa centro
468 y el histórico `right`, 473. En las conexiones oficiales esos grupos son
RIGHT_IRIS y LEFT_IRIS respectivamente para entrada sin espejo. La selección
anatómica cambia su asignación según el espejo de entrada:

| Fuente física | Entrada espejada, actual | Entrada sin espejo |
|---|---|---|
| Izquierdo | canal histórico left, 468 | canal histórico right, 473 |
| Derecho | canal histórico right, 473 | canal histórico left, 468 |

Las conexiones se contrastaron con el [código oficial de MediaPipe](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/vision/face_landmarker.py).
La [documentación oficial](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)
advierte además que espejar la entrada invierte los lados de los blendshapes.
Esta tabla es la convención implementada e inferida del espejo y del índice;
NO es una comprobación física en esta webcam. El preview marca I/D y resalta los
iris elegidos para verificarla con el pilotaje antes de mover el mouse.
No se renombraron señales históricas de gestos ni sus mapeos.

## Calibración y modelos

Neutral, cinco rangos, nueve objetivos y cinco validaciones reciben la misma
fuente que las estrategias de runtime. Solo se exige apertura/validez de los
ojos elegidos. Neutral/rangos conservan la fórmula asimétrica anterior.
Las nuevas calibraciones relativas registran la cámara y el tamaño de frame
cuando están disponibles; la activación comprueba esas condiciones. El control
también se detiene si cambia el tamaño de captura registrado. El CLI relativo
comprueba índice y tamaño antes de habilitar su backend.

El mapeador absoluto conserva ridge y selección lineal/cuadrática por validación
leave-one-target-out. Las características son realmente distintas:

- Binocular: cuatro coordenadas de iris + seis valores de nariz, escala y pose,
  diez entradas para dominio; el regresor usa la media de los dos pares.
- Monocular: solo dos coordenadas del iris elegido + esos seis valores faciales,
  ocho entradas para dominio; el regresor usa directamente el par seleccionado.

No se duplica artificialmente un ojo para aparentar binocularidad. Se adaptaron
el dominio de abstención, dispersión, ajuste, predicción y validación a esas
dimensiones. Los modelos nuevos usan `schema_version=2` y `eye_source`; la carga
rechaza dimensiones/fuente incompatibles. Los modelos absolutos v1 sin fuente se
interpretan exclusivamente como binoculares. No se convierten en monoculares.
Se conservan la limitación a un monitor y los controles de pantalla/DPI/cámara.

Los cinco objetivos de validación siguen siendo distintos de los nueve usados
en ajuste. Se conservan métricas y límites experimentales del informe anterior:
son una puerta para navegación por zonas, no certificación de selección fina.
Pasar tests sintéticos no demuestra precisión física de ninguna fuente.

## Persistencia y compatibilidad

Se añadieron `tracking_calibrations` y `absolute_calibrations`, cada uno con bancos
`both`, `left`, `right`. `ocular_profiles.py` resuelve/guarda el banco elegido.
Calibrar un ojo preserva el otro y el binocular. Los campos singulares previos
`tracking_calibration` y `absolute_calibration` permanecen como alias binoculares
para compatibilidad. Guardar una nueva calibración binocular actualiza su banco
y su alias; guardar una monocular no toca el alias binocular.

Un perfil antiguo sigue cargando sin reescritura/migración automática. Solo
`both` puede usar sus campos históricos. Seleccionar un ojo sin calibración propia
deja disponible diagnóstico y bloquea la activación. Un banco que declara una
fuente distinta de su clave se rechaza. Las condiciones no registradas en una
calibración relativa antigua no se pueden reconstruir: se conserva compatibilidad
y se recomienda repetirla en el pilotaje, sin afirmar que se verificó su cámara.

El perfil entregado a la GUI es una copia con los alias resueltos para la fuente
seleccionada; el controlador mantiene el perfil íntegro. Los experimentos congelan
la configuración (incluida fuente) y las calibraciones elegidas. Guardar una
calibración facial desde GUI o CLI sigue preservando todos los bancos oculares.
No se migraron datos de usuario a LocalAppData en esta etapa.

## Pérdidas de señal y gestos

La pérdida del iris seleccionado (o de cualquiera en `both`) anula el movimiento
de inmediato, limpia EMA/predicción y descarta residuos de píxeles. La recuperación
exige al menos tres frames distintos, >=60 ms y dispersión máxima de 0,04 en la
ventana de hasta cuatro muestras; luego se reinicia el filtro. Estos parámetros
son guardas heurísticas, pendientes de evaluar físicamente.

Un guiño del ojo utilizado bloquea mientras esté cerrado y durante 180 ms después.
Un guiño del otro ojo protege su inicio/acción durante 180 ms, pero una oclusión
sostenida del ojo no elegido no impone visibilidad permanente de su iris.
Tras la guarda se exige recuperar estabilidad. Las acciones explícitas de guiño
se conservan incluso cuando se elimina el movimiento de ese frame. No hay clic
por fijación ni sustitución de cejas/boca. Pausa, F8, Escape, parada, autorización,
failsafe y límites de paso siguen presentes.

## Interfaz

Configuración muestra Fuente ocular para Ojos relativos y absolutos, oculta para
Nariz. Siempre ofrece volver a Ambos ojos. Se debe guardar antes de calibrar.
La calibración indica la fuente y el diagnóstico muestra disponibilidad anatómica
por iris, par realmente usado, calibración, neutral/modelo, predicción, delta,
FPS, pausa, autorización y motivo de bloqueo. El preview dibuja I/D; verde
identifica los iris seleccionados. Las capturas en `docs/screenshots/eye-source-*-synthetic.png`
son exclusivamente sintéticas.

## Investigación de estabilidad: evidencia nueva

La ejecución inicial de esta etapa imprimió `251 tests / OK`, pero terminó DESPUÉS
con `Fatal Python error: Aborted` y `Windows fatal exception: access violation`,
código -1073741819 (`0xC0000005`). Se conserva el log completo en
`data/logs/binocular-baseline-tests.txt`. No se abrió cámara. El listado de módulos
nativos del fallo incluía Qt/Shiboken, NumPy y `_wmi`; no mostraba MediaPipe.
Esto no identifica una función culpable ni prueba que sea el cierre físico previo.

Se midió una retención concreta: después de los 14 tests de Inicio quedaban 22
MainWindow, 22 DictationOverlay y 330 contenedores de combo cerrados. Procesar
eventos/GC no los liberaba. Ahora los overlays tienen propietario Qt y las
ventanas se destruyen explícitamente después de finalizar el worker y mientras
QApplication sigue viva. Se usa DeferredDelete según la [documentación de Qt](https://doc.qt.io/qt-6/qobject.html#deleteLater).
El mismo experimento terminó con cero top-level widgets. `dispose_window` se
niega a destruir una ventana cuyo worker siga activo; hay test específico.

Esta es una corrección acotada de ciclo de vida, no una sustitución de MediaPipe
ni una supuesta solución definitiva del cierre original. Los logs/faulthandler y
la conservación/reintento de recursos nativos del trabajo anterior permanecen.

## Verificación y archivos

La suite pasó de 251 a **279 tests**, todos aprobados, 33,579 s y salida 0 en la
verificación completa de esta etapa. La ejecución inicial con aborto nativo NO se
contabiliza como éxito de proceso aunque unittest haya imprimido OK. También
pasaron los tres tests iniciales del selector Qt, `app.py --check` y el smoke
nativo de MediaPipe sobre imagen negra sin webcam ni entradas del SO.
Los resultados finales y cualquier repetición posterior se conservan en
`data/logs/eye-sources-*.txt`. El backend del mouse de todos los tests es un mock.

| Área | Archivos principales |
|---|---|
| Fuente/geometría | `gaze_source.py`, `face_data.py`, `eye_geometry.py`, `tracking.py` |
| Captura/modelos | `tracking_calibration.py`, `gaze_mapping.py` |
| Persistencia/configuración | `ocular_profiles.py`, `profiles.py`, `config.py` |
| Coordinación/salida | `application_controller.py`, `gesture_engine.py`, `main.py` |
| Interfaz/cierre | `desktop/window.py`, `desktop/widgets.py`, `desktop/gaze_overlay.py`, `desktop/lifecycle.py`, `app.py` |
| Tests nuevos | `tests/test_eye_sources.py`, `tests/test_eye_source_gui.py` |
| Regresiones adaptadas | `tests/test_eye_tracking.py`, `tests/test_gaze_mapping.py`, `tests/test_runtime_stability.py`, `tests/test_home.py`, `tests/test_gui.py`, `tests/test_gaze_gui.py`, `tests/test_calibration_gui_regression.py` |
| Revisión visual | `tests/render_eye_sources.py`, dos capturas sintéticas |

El test previo que aceptaba fallback monocular directo se actualizó para exigir
selección explícita; el de recuperación de guiño ahora comprueba la ventana
estable. No se eliminaron verificaciones del comportamiento nasal.

Comandos reproducibles:

```powershell
.\.venv\Scripts\python.exe -X faulthandler -u -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X faulthandler -u app.py --check
.\.venv\Scripts\python.exe -X faulthandler -B tests/smoke_runtime.py
.\.venv\Scripts\python.exe -B tests/render_eye_sources.py
```

Seguir [pilotaje de fuentes](EYE_SOURCE_PILOT.md). Registrar los resultados reales
antes de aprobar funcionalidad. La [consolidación y distribución](INTEGRATION_DISTRIBUTION_PLAN.md)
son planes, no integraciones ni instaladores ya producidos.

Git de entrega: misma rama `experiment/eye-tracking` y HEAD `b663fcc`, **29 archivos
versionados modificados y 22 nuevos sin seguimiento** (51 en total), sin stage,
commit ni push. Los 34 archivos de partida siguen presentes y el respaldo ZIP
pasó la verificación de todos sus hashes. Los logs/backups no se agregaron a Git.

# Corrección acotada de calibración ocular 9+5 — 27/10/2026

## Estado auditado y respaldo

Repositorio abierto en macOS: `/Users/juliandomfrocht/Desktop/HeadMouse`.
Rama `experiment/eye-tracking`, HEAD `9c605b5bf6190f179a2413714239683b98379eb3`.
El árbol estaba limpio y `git ls-remote` confirmó el mismo hash remoto.
No se cambiaron ramas ni se hicieron commits, pushes o merges.
Respaldo anterior a la edición: `/tmp/headmouse-backup-20261027/sources.tgz`
y `local.patch` (vacío porque no había modificaciones locales).

Se contrastaron el controlador, geometría, modelos, overlay, perfiles, tests y
los informes `CONTINUATION_2026-10-26.md`, `TWO_METHOD_ORGANIZATION.md` y
`GAZE_CALIBRATION_SAVE_REPAIR.md`. La documentación de continuación describe un
estado anterior: el código actual ya captura el centro primero y ya ofrece
preview y diagnóstico vertical. No es necesario agregar otro asistente.

## Fórmula exacta del error

Ruta: `GazeCalibrationSession.update` → `_point_problem` en `gaze_mapping.py`.
En binocular las características comienzan por `[xI,yI,xD,yD]`.

```text
mediana_j = mediana temporal de cada coordenada ocular j
spread = max_j(percentil90_j - percentil10_j)
gaze = ((mediana_xI+mediana_xD)/2, (mediana_yI+mediana_yD)/2)
neutral = gaze del centro de ESTA sesión
expected = sign(target - 0.5)
delta = gaze - neutral
medido = expected[eje] * delta[eje]
mínimo_anterior_absoluto = max(2.220446049250313e-16, spread_punto, spread_centro)
mínimo_relativo = max(0.02, spread_punto, spread_centro)
```

Para arriba `expected[Y]=-1`: `0.008967` significa que `gaze_y` está
0.008967 por debajo del neutral en coordenadas oculares, con el signo esperado.
`0.089158` es el máximo de las dos dispersiones, redondeado a seis decimales;
no es una constante ni un porcentaje de pantalla ni un rango antiguo guardado.

No existen logs de la sesión física ocular en el repositorio. No se puede
atribuir el máximo a una coordenada o a una fijación concreta sin ese registro.
La captura tampoco permite reconstruir los percentiles originales. La siguiente
es una reproducción **sintética**, no una medición recuperada:

| Componente | Valor reproducido |
|---|---:|
| Neutral binocular Y | 0.500000 |
| Mediana binocular Y del objetivo | 0.491033 |
| Delta Y | -0.008967 |
| Signo esperado Y | -1 |
| Desplazamiento firmado | 0.008967 |
| Dispersión del punto | 0.002000 |
| Dispersión del centro | 0.089158 |
| Piso absoluto | 2.220446049250313e-16 |
| Máximo | 0.089158 |

El mínimo es aproximadamente 9.94 veces la excursión. Además, 0.089158 pasa el
límite de estabilidad existente de 0.10: una fijación podía considerarse estable
y después bloquear todas las excursiones menores que su ruido máximo.

Ambos números son adimensionales, pero no representan la misma estadística:
una diferencia entre medianas binoculares verticales se comparaba contra el peor
intervalo temporal de cualquier ojo/eje. La X se normaliza mediante comisuras;
la Y mediante apertura de párpados. No hay justificación para usar el ruido de X
como desplazamiento mínimo de Y, ni para exigir el signo de joystick a un
regresor que aprende una correspondencia bidimensional.

## Orden y neutral

Los índices persistidos son por filas: 0..8 en posiciones 10%, 50%, 90%.
El orden real es **4, 0, 1, 2, 3, 5, 6, 7, 8**. El centro se capturaba primero,
pero figuraba como 5/9; la esquina siguiente figuraba como 1/9. El overlay ahora
separa número de captura e identificador de objetivo. Se conservan los nueve
puntos y su orden canónico para el ajuste y los perfiles.

El constructor comienza con `points={}`; no recibe un neutral guardado.
La ausencia de centro sigue bloqueando cualquier objetivo que lo requiera.
Repetir el centro conserva las fijaciones compatibles en postura; repetir un
objetivo invalida modelo y validación dependientes, sin borrar el resto.
No se agregó un límite temporal arbitrario para invalidar el centro a mitad del
recorrido. Se mantiene la comprobación de postura respecto del centro.

## Cambio matemático y puertas de calidad

En absoluto se registra el criterio anterior como diagnóstico, con
`threshold_applied=false`; no decide aceptación por signo o excursión individual.
Se aceptan fijaciones recientes, ojos abiertos, iris seleccionado, al menos 20
muestras en un segundo, dispersión <=0.10 y cabeza estable. La comprobación de
postura respecto del centro permanece para ajuste y validación.

Para el conjunto se mantienen semirrango >=0.025 por eje (rango total >=0.05),
selección lineal/cuadrática por leave-one-target-out y ridge 0.01.
Se agrega cobertura total estrictamente mayor que la mayor dispersión
intrafijación **binocular por eje**, sin mezclar X/Y. Se rechazan matrices sin
rango completo o con condición >1000 tras normalizar ambos ejes. Ese límite es
una guarda numérica experimental frente a casi colinealidad, no una certificación
física. Los rangos, dispersión y condicionamiento quedan en `fit_diagnostics`.

Los cinco objetivos independientes conservan su dominio y evaluación por cada
frame: media global <=10% de diagonal y peor zona <=18%. El modelo no se guarda
como aprobado si falla. Son tolerancias experimentales para zonas; no demuestran
precisión sobre botones pequeños. Una señal que sólo varía 0.009 en todo el eje
seguirá fallando por cobertura global: no se redujo ese umbral sin datos reales.

El joystick conserva íntegramente sus requisitos de dirección y rango; Nariz,
gestos, filtros, ejes y acciones no cambian. No se usa `abs` para fabricar señal.

## Geometría vertical y dispositivos

`eye_geometry.py` calcula Y por párpados usando el producto cruzado del eje de
comisuras con iris−párpado superior, dividido por el determinante de ambos ejes.
El movimiento de párpados puede cambiar numerador y denominador aunque el iris
cambie poco. La alternativa por comisuras usa iris−centro de comisuras dividido
por ancho ocular al cuadrado. Tiene otra normalización; no se intercambian
modelos ni rangos entre ambas referencias.

La calibración absoluta continúa usando párpados. El diagnóstico vertical
existente compara ambos ojos y ambas referencias en centro/arriba/abajo, con
medianas, ruido, geometría, postura y traza simulada. Sin nueva captura física
no puede determinarse cuál referencia mejora la precisión. No se modificó la
geometría ni se invirtió Y.

Los modelos absolutos nuevos incluyen `capture_host`, hash de sistema y nombre
del equipo, junto con pantalla/DPI, índice y resolución real de webcam.
La activación compara el contexto; un modelo absoluto de otro equipo, o antiguo
sin identificación del equipo, requiere recalibrar. El modelo viejo sigue
siendo legible y se conserva; no hay migración ni reescritura al leerlo.
La huella no es un número de serie de cámara: dos cámaras con igual índice y
resolución en el mismo equipo, nombres de equipo clonados, cambios de postura,
distancia e iluminación no se identifican automáticamente. Los bancos relativos
históricos mantienen su contrato de contexto existente. Recalibrar al cambiar
webcam o posición sigue siendo necesario.

## Telemetría, preview y prueba física pendiente

Se registra cada avance y cada error en `data/calibration/*.jsonl`, sin imágenes,
video ni muestras individuales: objetivos y coordenadas normalizadas, muestras,
rechazos, medianas, dispersiones por coordenada y por eje binocular, MAD,
neutral de sesión, diferencias, fórmula, componentes, referencia, motivo y
contexto. `saved_neutral=null` indica que no se utiliza para esta comparación.
Cada punto conserva su `direction_check`; el umbral histórico no se presenta
como requisito absoluto. Las fijaciones aceptadas y rechazadas se distinguen.

El overlay reutiliza `CameraPreview` alimentado por la misma señal Qt del
VisionEngine, mostrando iris, fuente, detección y estabilidad. Se conserva
Escape/F8. El texto se dispone entre filas de objetivos y es desplazable para
mensajes largos; la cámara sigue en el lado opuesto al objetivo.

Prueba breve, sin mouse real:

1. Elegir perfil y Ojos, con fuente fija y webcam en posición definitiva.
2. Ejecutar «Diagnóstico vertical · centro / arriba / abajo» en Calibración → Ojos.
3. Mantener cabeza quieta y mirar cada objetivo; revisar el JSON de diagnóstico:
   medianas de párpados/comisuras por ojo, delta arriba/abajo, ruido y postura.
4. Repetir una vez con misma postura. No cambiar referencia durante la captura.
   Si delta cambia de signo o queda dentro del ruido, revisar encuadre/luz/
   distancia y repetir. Conservar ambos registros; no inferir mejora sin medir.
5. Ejecutar nueve fijaciones y las cinco validaciones; revisar telemetría del
   centro, objetivo superior y objetivo inferior. Si falla cobertura, el modelo
   permanece sin aprobar; repetir el objetivo afectado desde el selector.
6. Sólo después de aprobación revisar predicción segura y, con autorización del
   usuario, activar control. La validación física sigue pendiente.

## Verificación automatizada y visual

Suite final: **372 tests, OK (2 omitidos)**, 30.808 segundos, código de salida 0.
No se abrió webcam ni se accionó el mouse real. Incluye el recorrido 9+5,
fuentes monoculares/binoculares, regresión exacta 0.008967/0.089158,
centro ausente/reciente, cobertura/ruido/degeneración, contexto antiguo y otro
equipo/cámara, rechazo y repetición, cancelación, nariz y preview desde una sola
instancia de VisionEngine. Se añadió una comprobación de que el panel de texto
no tapa ninguno de los 14 objetivos, en 1280×800 y 800×600.

Se corrigió un test anterior de selección de DirectShow/MSMF que asumía Windows
sin simular la plataforma: ahora limita la simulación a `_open_capture`, con
capturador mock. No se cambió el comportamiento real de `vision_engine.py`.

En este macOS Qt podía cargar explícitamente su plugin pero no lo enumeraba en
la carpeta original. Se copió el plugin existente a `/tmp/headmouse-qt-plugins`
para la ejecución, sin reinstalar ni cambiar dependencias:

```sh
QT_PLUGIN_PATH=/tmp/headmouse-qt-plugins QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -X faulthandler -u -B -m unittest discover -s tests
```

Log final: `/tmp/headmouse-tests-delivery-20261027.txt`.
`git diff --check` sin errores. Revisión visual offscreen realizada con datos
sintéticos; captura `/tmp/headmouse-overlay-final-20261027.png`.
Los artefactos de `/tmp` son temporales. El informe y las regresiones quedan en
el repositorio, sin commit. No se declara aprobada ninguna calibración física.

## Corrección posterior de inicio en macOS

Se reprodujo el cierre nativo `Could not find the Qt platform plugin "cocoa"`.
Los `.dylib` instalados tenían la marca de filesystem `UF_HIDDEN`: QDir no los
listaba salvo pidiendo Hidden explícitamente. QPluginLoader podía cargar el
archivo por ruta completa. Quitar la marca permitió un arranque, pero ésta
reapareció inmediatamente; no se identificó el proceso que la repone.

`app.py` llama ahora a `desktop.qt_runtime.prepare_qt_platform_plugins` antes
de crear QApplication. Sólo en macOS, si hay plugins de plataforma ocultos y
no hay una ruta explícita del usuario, copia los plugins instalados a un
directorio temporal privado y configura `QT_QPA_PLATFORM_PLUGIN_PATH`.
Se limpia al salir normalmente; un cierre forzado puede dejar la carpeta
hasta la limpieza temporal del sistema. No reinstala paquetes, no cambia
Windows y no acciona cámara/mouse.

Verificación: inicio nativo `app.py --check` sin variables Qt externas,
código 0; tres tests específicos de bootstrap OK (ruta explícita respetada,
Windows sin cambios, copia visible de plugin oculto conservando original).
Respaldo de app.py anterior: `/tmp/headmouse-backup-20261027/app-before-mac-fix.py`.

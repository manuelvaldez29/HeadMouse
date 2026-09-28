# HeadMouse v0.3.1 — calibración facial adaptativa

## Auditoría inicial (2026-09-25)

Antes de modificar archivos se verificó la raíz con `git rev-parse --show-toplevel`
y la rama con `git branch --show-current`: repositorio
`C:/Users/juliand/Desktop/headmouse/HeadMouse`, rama `tesis-v0.2`. El árbol estaba
limpio. No se cambia de rama ni se realizan commits o push.

La suite inicial ejecutó 53 tests: 51 aprobados y 2 fallidos,
`test_invalid_thresholds` y `test_thresholds_and_noise`. Ambos fallos son
anteriores a esta implementación. `validate_calibration` tenía un `pass` en la
condición de separación insuficiente; por ello aceptaba umbrales defectuosos.

### Por qué puede resultar difícil calibrar las cejas

El flujo anterior exigía una captura continua de cuatro segundos por gesto. El
umbral era una fracción fija entre neutral y un percentil extremo; no optimizaba la
separación de distribuciones ni evaluaba consistencia entre repeticiones. Ambas
cejas se validaban usando los umbrales unilaterales aunque no tenían una captura
propia. No había histéresis ni ventana de arbitraje para activaciones levemente
desfasadas. La validación fallaba ante un evento inesperado aislado y obligaba a
realizar todos los gestos. La validación inmediata de cada fase y la validación
final tampoco eran consistentes debido al `pass` mencionado.

Estos hechos explican mecanismos plausibles de dificultad; no prueban cuál fue
la causa dominante en la prueba física reportada. No se bajarán umbrales
globales ni se afirmará una mejora de precisión sin medición con usuarios.

## Diseño genérico

La unidad es `GestureCalibration`: identidad, disponibilidad, muestras
neutrales/activas en memoria, repeticiones, estadísticas robustas, umbrales de
activación/liberación, calidad y estado de validación. Un único motor estadístico
procesa las señales de todos los gestos. Los adaptadores encapsulan la
extracción, dirección de activación y composición de señales; el motor no
contiene algoritmos duplicados para ojos, cejas o boca.

El flujo incorpora tres repeticiones por defecto, ventanas de transición,
retorno a neutral, captura explícita de ambas cejas, repetición selectiva y
gestos opcionales. La misma señal calibrada se usa al detectar y validar.
Los perfiles anteriores conservan compatibilidad explícita; una señal ausente
no se sustituye silenciosamente por otra con una escala distinta.

`gesture_signals.py` registra los seis gestos: LEFT_WINK, RIGHT_WINK, LEFT_BROW,
RIGHT_BROW, MOUTH_OPEN y BOTH_BROWS. Agregar una señal futura requiere declarar
su extractor, canales y dirección, y conectar su identidad/instrucción/evento a
la aplicación; no reescribir el ajuste ni la histéresis. Una prueba usa una señal
nueva sin modificar el motor estadístico. Los guiños activan al disminuir;
cejas y boca, al aumentar. Ambas cejas usan dos canales y decisión AND.

## Motor estadístico compartido

`GestureCalibration` acepta vectores de canales y su dirección de activación.
Trabaja en coordenadas orientadas para que un valor mayor signifique más gesto;
devuelve umbrales en las unidades originales. Para cada canal y repetición usa
mediana, MAD y percentiles 10/90. El límite neutral es el máximo entre p90 y
mediana + max(separación mínima, multiplicador × 1.4826 × MAD). Se toma el mayor
límite neutral de las repeticiones y el menor p10 activo. Si no queda un hueco
mayor a la separación mínima, se solicita repetir ese gesto.

Dentro del hueco se evalúan puntos medios entre valores observados. Se maximiza
la exactitud balanceada de la peor repetición; luego la media; los empates se
resuelven por mayor distancia a los bordes del hueco. La liberación está a mitad
de camino entre el límite neutral y la activación. No depende de un único frame
extremo ni de la amplitud máxima unilateral para construir ambas cejas.

La calidad es la menor exactitud balanceada `(sensibilidad + especificidad)/2`
entre repeticiones y canales, incluyendo la decisión conjunta AND. BUENA ≥ 0.95,
ACEPTABLE ≥ 0.85; por debajo es DÉBIL y no se acepta. Son criterios de ingeniería
explícitos sobre las muestras de calibración: no probabilidades, validación
externa ni estimaciones clínicas. El margen robusto es una condición adicional;
un score alto no permite aceptar distribuciones sin separación suficiente.

El registro exporta estadísticas, repeticiones capturadas/válidas, score,
umbrales, causas y reintentos; no las muestras individuales.

## Detector y compatibilidad

`GestureEngine` consume `gesture_calibrations` por identidad, usa el adaptador
indicado en el registro y aplica `HysteresisGate` por canal. Un gesto compuesto
se activa cuando todos sus canales están activos. Los gestos deshabilitados no
generan eventos. Los perfiles sin estos registros siguen usando los cinco
umbrales geométricos anteriores, con activación y liberación iguales; para ambas
cejas el fallback es la conjunción de los dos umbrales unilaterales existentes.
Este fallback mantiene la posibilidad de usar el perfil anterior, pero no se
presenta como calibración explícita de ambas cejas.

Si solo un guiño está disponible, el ojo omitido conserva su neutral observado.
Para suprimir el parpadeo bilateral se transporta la proporción de cierre del
ojo calibrado: `umbral_otro = neutral_otro × umbral_calibrado / neutral_calibrado`,
tanto para activación como liberación. Es un fallback de veto, nunca genera un
evento del guiño omitido ni afirma calibrarlo. Evita que un umbral genérico
interprete el ojo abierto como cerrado. Requiere prueba física en asimetrías;
sin referencias válidas se conserva el fallback anterior.

La ventana `gesture.brow_decision_ms` vale 200 ms por defecto. El detector mide
hold durante esa espera; no suma otro hold después de resolver. Si aparece la
señal bilateral dentro de la ventana, descarta los eventos unilaterales pendientes.
Después de resolver un gesto unilateral, el otro lado tardío no lo convierte en
pausa: se requiere soltar el episodio para decidir de nuevo. La ventana solo
afecta cejas, no guiños ni boca. Frescura inválida reinicia gates, hold y arbitraje.

El formato sigue siendo esquema 2, con `calibration_version: "0.3.1"` y
`gesture_calibrations`. Los cinco thresholds se conservan como compatibilidad de
estructura, pero los registros nuevos son la fuente de verdad del detector.
El esquema anterior válido sigue funcionando sin migración automática. No se
garantiza abrir perfiles nuevos con ejecutables antiguos, especialmente si usan
blendshapes. Un perfil antiguo con separación inválida ahora se rechaza: se
puede recalibrar el mismo ID mediante CLI, conservando el archivo hasta aprobar
y guardar, o crear un perfil nuevo desde GUI. No se relaja la validación global.

## Captura repetida y validación en GUI y CLI

El wizard captura primero neutral para el punto nasal y la referencia de retorno.
Después alterna neutral y gesto durante tres repeticiones por gesto habilitado.
Por defecto descarta 0.3 s de transición y captura 1 s neutral / 0.8 s activo;
exige al menos ocho muestras válidas por ventana. Tracking inválido reinicia la
ventana; timestamps duplicados no suman muestras. Una guardia de retorno compara
la señal con neutral usando el mayor margen entre 3 × separación mínima,
multiplicador × 1.4826 × MAD y 10% del valor neutral. Es una condición de captura,
no sustituye el ajuste estadístico final.

Tras cada repetición se calcula una estimación provisional para el medidor;
guardar sigue requiriendo las tres repeticiones, calidad suficiente y validación.
Repetir un gesto conserva los otros. Marcarlo no disponible lo excluye y asigna
NONE inicialmente. La GUI ofrece casillas de disponibilidad, fuente experimental,
selector de reintento, calidad y medidor; diagnóstico permite consultar datos
avanzados sin mostrar JSON.

En GUI, **Gestos disponibles y tipo de señal** despliega las opciones; se ocultan
al comenzar para dejar visibles cámara y medidor. Los controles de repetir,
validar, guardar y cancelar permanecen fuera del área desplazable. El marcador
verde representa el extremo cómodo robusto (p90 activo, o p10 para señales
decrecientes), no el máximo absoluto. Calidad provisional no habilita guardar.
Repetir la validación conserva los gestos ya reconocidos; volver a medir uno
dentro de la sesión conserva sus otras capturas, pero exige validar nuevamente.
Revalidar un perfil cargado no recupera muestras crudas: para volver a medir hay
que comenzar una calibración nueva.

CLI: SPACE inicia, valida y guarda según el estado; R repite el paso actual;
C reinicia; S omite el gesto de captura actual; Q descarta. Las teclas 1–6
permiten volver a medir guiño izquierdo, derecho, ceja izquierda, derecha, boca
y ambas cejas respectivamente. `--disable LEFT_BROW` (repetible) configura
disponibilidad inicial; `--brow-signal HYBRID` selecciona una fuente experimental.
La CLI conduce la misma `CalibrationSession`, sin otro algoritmo estadístico.

La validación acumula tiempo neutral válido; los intervalos de ruido no cuentan
como neutral. Tolera interrupciones de hasta 0.15 s; una interrupción mayor
reinicia la estabilidad. Un gesto incorrecto mantenido durante 0.35 s genera
error, aunque el detector ya esté en cooldown. Un evento aislado no lo hace.
Solo se solicitan gestos habilitados. La prueba anterior de evento incorrecto
se amplió para verificar tanto la tolerancia aislada como el rechazo sostenido.

Cada ajuste terminado guarda agregados en `data/calibration/<sesión>.jsonl`,
incluidos los intentos débiles, y conserva el historial de ajustes en el perfil
guardado. No se serializan los vectores de muestras, frames ni landmarks.

La telemetría incluye repeticiones capturadas/válidas, mediana y MAD neutral,
mediana activa, percentiles, separación, ruido, ambos umbrales, score y reintentos.
Es un registro por ajuste completo de gesto, incluidos ajustes débiles; las
ventanas parciales canceladas no se exportan. Puede leerse con cualquier lector
JSONL para comparar gestos, fuentes y usuarios. La carpeta está excluida de Git.

## Fuentes experimentales de cejas

La geometría conserva los ratios existentes. BLENDSHAPE usa por lado
`(browOuterUp + browInnerUp - browDown) / 2`. HYBRID usa
`(geometría / 0.25 + blendshape) / 2`. La constante 0.25 define una escala fija,
no un threshold adaptativo; estas fórmulas son hipótesis experimentales que
requieren calibración propia y comparación física. No se afirma superioridad.
Si falta un score requerido, el adaptador devuelve señal ausente: nunca aplica
umbrales blendshape a geometría como fallback silencioso.

Se habilita `output_face_blendshapes` y se conservan en memoria los cinco nombres
`browInnerUp`, `browOuterUpLeft`, `browOuterUpRight`, `browDownLeft`, `browDownRight`.
Se verificaron los índices 1–5 de `Blendshapes` en MediaPipe 1.0.1 instalado y los
nombres `category_name` en el [grafo oficial](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/cc/vision/face_landmarker/face_blendshapes_graph.cc).
La [opción de salida](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerOptions)
y el [formato de resultados](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarkerResult)
están documentados por MediaPipe. No se necesita cambiar el modelo ni reemplazar
los ratios geométricos.

## Límites y prueba física pendiente

El score usa las mismas muestras con que se ajusta el umbral, por lo que puede
ser optimista. La validación posterior es una comprobación funcional, no un
estudio de exactitud. El margen absoluto mínimo y las escalas experimentales
requieren evaluar distintas caras, iluminación y cámaras. No hay adaptación
automática durante el uso ni estimación de fatiga. El neutral inicial sigue
capturándose durante 4 s; los gestos usan ventanas cortas. Un timeout se puede
resolver repitiendo u omitiendo ese gesto.

Con webcam y usuario real se debe volver a probar:

1. Neutral y tres repeticiones cómodas de cada gesto disponible: lateralidad,
   facilidad de retorno, fatiga, tiempo total, cantidad de reintentos y omisión.
   Incluir el caso de un único guiño disponible y el parpadeo natural de ambos ojos.
2. Ambas cejas con amplitud distinta a la unilateral; desfases de izquierda y
   derecha, falsos scroll antes de pausa, y ajuste de la ventana de 200 ms.
3. Estabilidad cerca de los umbrales, parpadeos naturales, detecciones aisladas y
   gestos incorrectos sostenidos durante validación; retomar y guardar el perfil.
4. Comparar GEOMETRIC, BLENDSHAPE y HYBRID con recalibración propia, iguales
   condiciones y ground truth: sensibilidad, especificidad, FP/minuto y latencia.
5. Cambios de iluminación, pose, distancia, anteojos, pérdida/retorno de rostro,
   cámara desconectada y permisos. Medir FPS/CPU con blendshapes habilitados.
6. Medidor y opciones a escalas de Windows/DPI reales, incluyendo 125/150/200%,
   accesibilidad de los controles, selección de gestos y mensajes de repetición.
7. Acciones reales, pausa/reanudación, Detener, atajos locales, failsafe y varios
   monitores. Con PAUSE omitido, asignarlo a otro gesto disponible si se necesita.

Las pruebas automáticas no usan webcam ni ejecutan entradas reales de mouse o
teclado. La inferencia sobre imagen negra solo verifica carga/integración nativa.

La verificación final aprobó 82 tests, el arranque GUI sin cámara y la prueba
nativa sobre imagen negra. Ver [informe de implementación](IMPLEMENTATION_REPORT_V031.md)
para evidencia, cambios de pruebas y revisión visual.

# Modelo ocular: comparación con datos reales — 27/10/2026

## Qué se investigó y qué se encontró

Se preservó la rama `experiment/eye-tracking`, sin commits ni pushes. Respaldo de
las fuentes antes de esta intervención: `/tmp/headmouse-model-backup-20261027/`.
Se analizaron los registros locales, sin capturar imágenes o video ni mover el
mouse. Se mantuvieron Nariz/Ojos, pestañas, gestos y perfiles.

Hay dos conjuntos de evidencia distintos:

1. La sesión anterior que produjo **400.499711 px de error global independiente**
   y **477.976782 px en la peor zona**. Esas cifras no corresponden al objetivo
   4 individual; éste tenía error **446.292522 px**, 28 muestras y estabilidad
   92.3 %. En esa sesión sólo estaba guardada la referencia por párpados.
2. La nueva sesión, posterior a agregar instrumentación, que termina con
   **601.124300 px de error de aprendizaje**. Ahora hay registros de párpados,
   comisuras, postura y rectángulo real del overlay. Esto permite comparar
   referencias usando las mismas fijaciones, sin pedir otra calibración para
   hacer la comparación ni usar los cinco objetivos para entrenar.

## Tabla de la sesión que produjo 400.5 px

Nueve objetivos de aprendizaje, índices canónicos por filas. Se capturó primero
el centro (índice 4), pero el ajuste reconstruyó las filas 0..8 correctamente.
Las predicciones se reconstruyen con las medianas registradas y el mismo
regresor lineal; las variables de cabeza no son entradas de sus coeficientes.
| Punto | Objetivo px | Predicción px | Error X px | Error Y px | Distancia px |
|---|---|---|---:|---:|---:|
| 1 | 293.9, 191.1 | 480.6, 992.2 | 186.7 | 801.1 | 822.6 |
| 2 | 1469.5, 191.1 | 1425.1, 965.9 | 44.4 | 774.8 | 776.1 |
| 3 | 2645.1, 191.1 | 3008.9, 841.7 | 363.8 | 650.6 | 745.4 |
| 4 | 293.9, 955.5 | 354.3, 1093.9 | 60.4 | 138.4 | 151.0 |
| 5 | 1469.5, 955.5 | 1447.2, 923.6 | 22.3 | 31.9 | 38.9 |
| 6 | 2645.1, 955.5 | 2455.1, 902.3 | 190.0 | 53.2 | 197.3 |
| 7 | 293.9, 1719.9 | 292.7, 1068.4 | 1.2 | 651.5 | 651.5 |
| 8 | 1469.5, 1719.9 | 1290.7, 960.1 | 178.8 | 759.8 | 780.6 |
| 9 | 2645.1, 1719.9 | 2471.0, 851.3 | 174.1 | 868.6 | 885.8 |

Cinco objetivos independientes; los errores X/Y y euclidianos son las medias
por frame guardadas en el registro. La predicción mostrada es la del vector de
medianas oculares, no la media temporal exacta (no guardada en aquella versión).
| Objetivo | Destino físico px | Predicción de mediana px¹ | Error X medio | Error Y medio | Euclidiano medio | Muestras | Estabilidad |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | 881.7, 573.3 | 1138.8, 987.4 | 224.0 | 419.2 | 478.0 | 29 | 84.3% |
| 2 | 2057.3, 573.3 | 2110.7, 896.4 | 55.8 | 326.4 | 332.3 | 27 | 89.0% |
| 3 | 881.7, 1337.7 | 818.7, 1016.2 | 86.9 | 319.2 | 335.5 | 28 | 86.6% |
| 4 | 2057.3, 1337.7 | 2149.3, 901.5 | 89.2 | 435.8 | 446.3 | 28 | 92.3% |
| 5 | 1469.5, 573.3 | 1409.0, 972.5 | 75.8 | 401.7 | 410.4 | 27 | 88.1% |

La Y predicha se comprime hacia la mitad de pantalla. En ese aprendizaje la
correlación entre señal ocular Y y objetivo Y fue **0.0772**; X fue **0.9813**.
La estabilidad intrafijación no describe la correspondencia entre fijaciones.
La matriz no es singular y quitar ridge cambia el error de aprendizaje de
561.0 a 560.8 px. El cuadrático mejora ajuste pero empeora al dejar objetivos
fuera: no se justificó sustituirlo por un modelo de mayor complejidad.

## Comparación sobre la nueva sesión

El objetivo y la señal no se reasignan: se usan los mismos nueve registros.
Horizontal se conserva exactamente. La referencia vertical por párpados usa
apertura ocular como denominador; puede cambiar cuando cambian los párpados.
La alternativa existente por comisuras usa ancho ocular y no usa apertura en el
denominador. Sus amplitudes no están en la misma normalización geométrica.

Comparación lineal, ridge 0.01, normalizando cada fold sólo con sus ocho puntos
de entrenamiento; sin usar validación independiente:

| Características | Error medio de ajuste px | Error medio dejando un objetivo fuera px |
|---|---:|---:|
| Promedio binocular, párpados | 601.1 | 909.1 |
| Promedio binocular, comisuras¹ | 239.0 | 344.7 |
| Cuatro coordenadas, párpados² | 310.3 | 621.6 |
| Cuatro coordenadas, comisuras² | 173.3 | 356.8 |
| Binocular párpados + pitch² | 566.3 | 1034.8 |

¹ El candidato implementado combina las medianas por ojo, igual que la extracción
binocular habitual. El análisis exploratorio con mediana del promedio daba
239.3/345.5 px; la pequeña diferencia se debe a que mediana de promedio y promedio
de medianas no son la misma estadística.

² Comparaciones exploratorias, sin incorporarlas al runtime; para comisuras se
utilizaron las medianas por ojo. El menor error de ajuste no se traduce en mejor
resultado dejando puntos fuera. No se agrega una compensación de cabeza con
coeficientes inventados ni se elige una configuración por los cinco objetivos.
El pitch varió aproximadamente 13 grados entre estas fijaciones. Una ventana
estable no implica idéntica postura entre todos los objetivos.

En la comparación exploratoria con mediana binocular la correlación Y fue
0.3286 usando párpados frente a 0.9663 con comisuras. El rango canthi fue 0.04867
y el mayor ruido intrafijación P90−P10 fue 0.004566: aproximadamente 10.7 veces
más rango que ruido. Esto fundamenta evaluar esta referencia; no demuestra
precisión independiente ni autoriza a activar el mouse todavía.

Predicciones sobre las nueve medianas de la nueva sesión:
| Punto | Objetivo px | Párpados: predicción px | Error X/Y px | Comisuras: predicción px | Error X/Y px |
|---|---|---|---|---|---|
| 1 | 293.9, 191.1 | 389.3, 763.8 | 95.4 / 572.7 | 313.1, 277.0 | 19.2 / 85.9 |
| 2 | 1469.5, 191.1 | 1751.4, 792.9 | 281.9 / 601.8 | 1668.6, 114.0 | 199.1 / 77.1 |
| 3 | 2645.1, 191.1 | 2683.5, 1088.7 | 38.4 / 897.6 | 2635.7, 308.5 | 9.4 / 117.4 |
| 4 | 293.9, 955.5 | 217.6, 1334.7 | 76.3 / 379.2 | 247.3, 1183.6 | 46.6 / 228.1 |
| 5 | 1469.5, 955.5 | 1722.6, 598.3 | 253.1 / 357.2 | 1702.5, 880.1 | 233.0 / 75.4 |
| 6 | 2645.1, 955.5 | 2077.5, 650.1 | 567.6 / 305.4 | 2059.5, 859.7 | 585.6 / 95.8 |
| 7 | 293.9, 1719.9 | 249.9, 1143.9 | 44.0 / 576.0 | 292.1, 1400.3 | 1.8 / 319.6 |
| 8 | 1469.5, 1719.9 | 1416.2, 1010.1 | 53.3 / 709.8 | 1505.0, 1895.5 | 35.5 / 175.6 |
| 9 | 2645.1, 1719.9 | 2717.4, 1217.1 | 72.3 / 502.8 | 2801.8, 1680.8 | 156.7 / 39.1 |

## Defecto geométrico confirmado y corrección

La telemetría nueva muestra pantalla lógica de 1470×956 con DPR 2, pero overlay
real en **(0,37), 1470×919**. Antes se dibujaba `t*(tamaño_ventana-1)` desde ese
origen, mientras el modelo aprendía `t*(tamaño_pantalla_física-1)`.

Ejemplos anteriores en Y, píxeles físicos:

| Objetivo Y normalizado | Y que suponía el modelo | Y realmente dibujada | Diferencia |
|---|---:|---:|---:|
| 0.1 | 191.1 | 257.6 | +66.5 |
| 0.5 | 955.5 | 992.0 | +36.5 |
| 0.9 | 1719.9 | 1726.4 | +6.5 |

Es un defecto real, pero su magnitud no explica por sí sola los 400 px.
`target_in_viewport` ahora convierte el destino físico del modelo a posición
local del overlay, restando el origen real Qt e incorporando el rectángulo lógico
del monitor. No se reaplica DPR al error ni se invierten ejes. La telemetría usa
la misma posición que se dibuja. Un cambio incompatible de DPI cierra la captura
con un mensaje, sin dejar una excepción escapar del pintado Qt.

## Cambio mínimo de modelo y compatibilidad

- Al terminar los nueve puntos se ajustan dos candidatos: párpados y comisuras.
  Se selecciona por error normalizado dejando un objetivo fuera. Párpados sigue
  siendo la referencia salvo que comisuras mejore al menos 10 %, o que el candidato
  por párpados no tenga cobertura válida. La decisión queda en el registro y la
  referencia elegida se muestra en el overlay. No hay otro selector público.
- Cada fold usa centro y escala calculados con sus ocho puntos, evitando usar el
  objetivo dejado fuera incluso para normalizar. Los cinco puntos independientes
  no intervienen en selección, normalización ni entrenamiento.
- El piso de semirrango 0.025 de párpados no se aplica a comisuras: normalizan por
  ancho, no por apertura. Comisuras exige dispersión medida en los nueve puntos,
  rango por eje mayor que su ruido máximo, rango numérico no degenerado y matriz
  con rango completo/condición <=1000. No se redujo el límite de precisión.
- Los candidatos por comisuras usan esquema ocular **v3** con referencia explícita.
  Los modelos v1/v2 conservan párpados y no se migran al leer. El perfil personal
  no cambia de identidad. La predicción, dominio y cinco validaciones usan la
  referencia guardada; si falta la señal requerida, el modelo se abstiene.
- Repetir aprendizaje vuelve a la captura común por párpados registrando también
  comisuras; después se comparan nuevamente. La comparación neutral de validación
  transforma el centro de esa sesión a la referencia seleccionada.
- La validación independiente conserva límites anteriores. La mejora de ajuste
  no basta para guardar: sólo tras cinco objetivos nuevos aprobados se permite
  guardar y usar el diagnóstico seguro; el control requiere confirmación.

## Revisión visual y guardado de intento fallido

Se conserva el preview de la misma webcam. Cuando termina una evaluación, elegir
un punto del selector muestra el objetivo amarillo, la predicción celeste y el
segmento entre ambos, con X/Y, distancia media, estabilidad y estado. Se puede
ver compresión, sesgo o inversión sin leer logs. Durante la captura se mantiene
el objetivo de fijación sin añadir una predicción que distraiga.

«Guardar diagnóstico» exporta un JSON en `data/calibration` con métricas, fuentes,
referencia, comparaciones y estados del intento, incluso rechazado. Sus campos
`approved_calibration=false` y `authorizes_control=false` son explícitos. No es
un perfil ni un modelo cargable y no escribe calibraciones personales.

Se preservan repetición individual, retorno a aprendizaje con mediciones útiles,
validación completa 5/5 después de repetir el cuarto y bloqueo real de modelos
rechazados, implementados en la intervención anterior.

## Próxima prueba física y comparación antes/después

1. Reiniciar HeadMouse para cargar los cambios. Mantener cámara, distancia y luz.
2. Medir centro/arriba/abajo en Diagnóstico vertical y guardar el registro.
3. Realizar nueve puntos. Leer la referencia elegida y errores de ajuste; exportar
   diagnóstico aunque falle. Los registros anteriores permanecen intactos.
4. Si el aprendizaje pasa, medir cinco objetivos nuevos. Revisar en el selector
   cada objetivo/predicción y X/Y; exportar también este resultado.
5. Comparar error independiente global y por eje contra el intento anterior de
   400.5 px. Comparar las condiciones: el nuevo modelo de referencia no debe darse
   por mejorado físicamente usando sólo su ajuste sobre los mismos nueve puntos.
6. Si pasa validación, guardar, comprobar predicción segura y confirmar control.
   Si no pasa, conservar exportación: no repetir indefinidamente una fijación sin
   revisar si el error es global o una distracción concreta.

No se obtuvo todavía una nueva validación física de cinco puntos con esta versión.
No se garantiza precisión para botones pequeños con las tolerancias experimentales
existentes; su adecuación requiere medir tareas reales con el usuario.

## Verificación final

- Suite completa: **394 tests, OK (2 omitidos)**, 52.169 segundos, salida 0.
  Log local: `/tmp/headmouse-model-complete.txt`.
- Se agregaron regresiones para selección por aprendizaje sin usar validación,
  señal palpebral estable pero no discriminativa con comisuras útiles, comisuras
  con ruido excesivo, escalas geométricas distintas, v3 y perfiles personales,
  modelos antiguos, falta de comisuras durante runtime, correspondencia real
  overlay/pantalla con origen (0,37), resguardo de texto, revisión visual de un
  punto seleccionado y exportación de intento fallido sin tocar el perfil.
- Las regresiones anteriores conservan calibración nasal, guiños, cancelación,
  contexto de cámara/DPI, rechazo global, error de 400 px con 28 muestras,
  repetición 4/5, guardado/relectura y autorización con backend simulado.
- `app.py --check` nativo en macOS: salida 0; `git diff --check`: sin errores.
- Revisión gráfica realizada con datos sintéticos, sin webcam ni mouse real.
- La aplicación que ya esté abierta requiere reiniciarse; no se interrumpió
  por la fuerza una sesión del usuario ni se descartaron mediciones en RAM.
- Las versiones anteriores de los informes describen sus respectivas etapas.
  Este informe incorpora la nueva evidencia por comisuras y el rectángulo real
  del overlay que antes no estaban disponibles. No se afirma aprobación física.

# Validación ocular: diagnóstico físico y corrección — 27/10/2026

## Evidencia encontrada

Se analizaron los JSON locales de `data/calibration`, sin imágenes ni video.
El último resultado completo coincide con la captura: error medio
**400.499711 px**, peor zona **477.976782 px**, pantalla Retina de **2940×1912
píxeles físicos**, DPR **2**, webcam **1920×1080**. Los cinco objetivos estaban
medidos. El índice visible 4/5 era el último objetivo repetido, no la cantidad
de validaciones realizadas. El estado `invalid` se refería al resultado global.

En esta pantalla los límites existentes son media <= **350.704206 px** y peor
zona <= **631.267571 px**. Falla la media; la peor zona no supera su límite.
**No se modificaron esos límites.** Ninguna de estas medidas certifica precisión
para botones pequeños; son criterios experimentales de navegación por zonas.

## Cálculo exacto y datos por objetivo

Para cada muestra j se predice `(u_j,v_j)` normalizado y se calcula:

```text
predicho_px_j = (u_j*(W-1), v_j*(H-1))
objetivo_px = (objetivo_u*(W-1), objetivo_v*(H-1))
dx_j, dy_j = predicho_px_j - objetivo_px
error_X = media(abs(dx_j)); error_Y = media(abs(dy_j))
error_objetivo = media(sqrt(dx_j² + dy_j²))
error_global = media de los cinco errores_objetivo (igual peso por zona)
peor_zona = max de los cinco errores_objetivo
calidad_captura = max(0, 1 - dispersión_máxima/0.10)
```

La calidad es una heurística de estabilidad, **no exactitud de mirada**. Veintiocho
muestras estables del lugar incorrecto también producen un error elevado.
No debe confundirse media de distancias con distancia de la predicción media.
| Objetivo | Destino físico px | Predicción de mediana px¹ | Error X medio | Error Y medio | Euclidiano medio | Muestras | Estabilidad |
|---|---|---|---:|---:|---:|---:|---:|
| 1 | 881.7, 573.3 | 1138.8, 987.4 | 224.0 | 419.2 | 478.0 | 29 | 84.3% |
| 2 | 2057.3, 573.3 | 2110.7, 896.4 | 55.8 | 326.4 | 332.3 | 27 | 89.0% |
| 3 | 881.7, 1337.7 | 818.7, 1016.2 | 86.9 | 319.2 | 335.5 | 28 | 86.6% |
| 4 | 2057.3, 1337.7 | 2149.3, 901.5 | 89.2 | 435.8 | 446.3 | 28 | 92.3% |
| 5 | 1469.5, 573.3 | 1409.0, 972.5 | 75.8 | 401.7 | 410.4 | 27 | 88.1% |

¹ El registro antiguo conserva errores por muestra agregados y las medianas
oculares, pero no todas las predicciones ni los coeficientes. Se reconstruyó el
mismo regresor a partir de las nueve medianas oculares; las variables de cabeza
no participan en sus coeficientes, sólo en la puerta de dominio. La columna de
predicción es la salida del vector de medianas, no la media exacta de las salidas
por frame. Esa media y sus sesgos se registran explícitamente desde esta reparación.
No se reconstruyen muestras temporales que el registro no contiene.

El objetivo 4 apunta a `(0.7,0.7)`, es decir `(2057.3,1337.7)` px; su predicción
sobre medianas es aproximadamente `(2149.3,901.5)`. El problema principal es
vertical: error Y medio **435.8 px**, frente a error X **89.2 px**.
| Objetivo | Medianas xI, yI, xD, yD | Dispersión máxima P90−P10 |
|---|---|---:|
| 1 | 0.436837, 0.432867, 0.533090, 0.472521 | 0.015659 |
| 2 | 0.494746, 0.415621, 0.571645, 0.460053 | 0.011010 |
| 3 | 0.426499, 0.448752, 0.511389, 0.464613 | 0.013369 |
| 4 | 0.502164, 0.416518, 0.570075, 0.471417 | 0.007738 |
| 5 | 0.461267, 0.443218, 0.537870, 0.469871 | 0.011918 |

La mediana binocular de aprendizaje tiene rango X **0.137979**, rango Y
**0.070858**, y matriz lineal normalizada con condición **1.706881**. Hay rango
numérico y no hay singularidad, pero eso no demuestra que la señal represente
la posición del objetivo. La correlación señal/objetivo es **0.9813 en X** y
**0.0772 en Y** en esta sesión. No basta con acumular fijaciones estables.

## Modelo: prueba comparativa sin reutilizar validación

Se compararon exclusivamente las nueve medianas de aprendizaje:

| Modelo | Ridge | Error medio de ajuste px | Error medio dejando un objetivo fuera px |
|---|---:|---:|---:|
| Lineal vigente | 0.01 | 561.0 | 855.5 |
| Lineal sin ridge | 0 | 560.8 | 856.2 |
| Cuadrático | 0.01 | 413.4 | 1459.0 |
| Cuadrático sin ridge | 0 | 411.8 | 1487.0 |

El regularizador no explica cientos de píxeles de error. La mayor complejidad
sobreajusta estas medianas y generaliza peor. Se conserva el algoritmo vigente,
su selección por leave-one-target-out y los modelos históricos. No se entrenó
con objetivos de validación ni se ajustó un sesgo usando esa evaluación.

El defecto demostrado de flujo era permitir que un modelo incapaz de explicar
sus propios puntos llegara a validación sin mostrar el error de aprendizaje.
La señal vertical de esta sesión no discrimina las filas de pantalla. Los datos
históricos no permiten atribuirlo exclusivamente a párpados, cabeza o conducta
de fijación: no guardaban la geometría comparativa de ambas referencias y la
postura mediana completa. No se invierte Y ni se cambia la normalización a ciegas.

## Asociación, espejo y geometría

- Los índices de aprendizaje son canónicos por filas 0..8; la captura comienza
  por el centro: 4,0,1,2,3,5,6,7,8. Se reconstruyen las filas para ajustar usando
  esos índices, nunca el orden de inserción del diccionario.
- Validación independiente: `(0.3,0.3)`, `(0.7,0.3)`, `(0.3,0.7)`, `(0.7,0.7)`,
  `(0.5,0.3)`. Son distintos de los nueve puntos de aprendizaje.
- `[1,1]` es `sign(objetivo-0.5)`: derecha y abajo. Ahora el texto lo llama
  explícitamente «signos direccionales». No son coordenadas ni se aplican como
  requisito al regresor absoluto.
- VisionEngine espeja una sola vez antes de inferir. La extracción recibe
  `mirrored=True`; el regresor y la validación usan la misma geometría. No se
  identificó una inversión ni desplazamiento de índices.
- El error se calcula en píxeles físicos; no se vuelve a multiplicar por DPR.
  Qt dibuja sobre el área lógica del overlay. Si éste ocupa la pantalla completa,
  usar `t*(ancho_lógico-1)*DPR` frente a `t*(ancho_físico-1)` difiere en menos de
  un píxel con DPR 2. Eso no explica los 400 px observados.
- El registro viejo no permite comprobar el tamaño real histórico del overlay.
  Desde ahora se guarda rectángulo lógico/origen real, DPR, posición dibujada
  lógica/global y local/física, y tamaño esperado. Es telemetría; no se inventa
  una corrección de DPI sin comprobar el dato.
- Windows conserva la comprobación de monitor primario, rectángulo físico y
  transformación Qt/Win32. No se cambia el escritorio virtual ni el método Nariz.

## Correcciones implementadas

1. El modelo nuevo conserva un `training_report` por cada uno de los nueve
   objetivos: destino, predicción, sesgos y errores X/Y/euclidiano. Si el ajuste
   no cumple los mismos límites de media y peor zona, se detiene antes de las
   validaciones y se señala el peor objetivo para repetir. La sesión física
   analizada ahora se detectaría como aprendizaje insuficiente, sin hacer repetir
   una validación condenada por un modelo ya inadecuado.
2. Cada validación guarda medianas oculares y de postura, dispersión, estabilidad,
   índice, secuencia de captura, destino px, predicción media/mediana px y sesgo
   firmado. Se registran también medianas y dispersiones de párpados y comisuras
   para ambos ojos y el promedio binocular. No se cambian las características
   utilizadas por el modelo ni se capturan imágenes.
3. Una fijación válida con error elevado sigue siendo una medición útil para
   evaluar: se completan los cinco objetivos y se muestran errores individuales,
   conservando el rechazo global. Una fijación fuera de dominio se rechaza como
   tal, con repetición del objetivo y conservación de los otros datos.
4. La pantalla distingue estabilidad de precisión, muestra cada error en el
   selector, indica «validación completa 5/5» aunque el último punto repetido
   sea el cuarto, y muestra los límites que bloquean el guardado.
5. «Repetir punto» conserva los otros objetivos. «Revisar aprendizaje» vuelve
   al peor objetivo de aprendizaje del modelo, preserva los otros ocho y elimina
   modelo/validaciones dependientes. Después de ajustar se requieren cinco
   validaciones nuevas. No toca el perfil guardado. El centro sigue disponible
   en el selector si hace falta volver a medirlo.
6. `outcome` distingue captura, punto aceptado/rechazado, aprendizaje rechazado,
   recalibración necesaria y validación completa aprobada/rechazada, manteniendo
   los estados históricos por compatibilidad con controlador y GUI.

No se modificaron gestos, nariz, acciones, filtros de cursor, consentimiento de
activación ni persistencia de perfiles. Un modelo rechazado sigue sin emitir
movimiento real. Se conservan contexto de equipo/cámara/pantalla, pausa, failsafe,
abstención por iris perdido, gestos no validados y límites de salto existentes.

## Prueba física concreta

1. Con el control detenido, ejecutar **Diagnóstico vertical · centro / arriba /
   abajo** desde Calibración → Ojos. Mantener la cabeza y distancia; mirar sólo
   el objetivo, no el panel de cámara. Comparar en el JSON los deltas y el ruido
   de párpados/comisuras por ojo. Repetir una vez con iguales condiciones.
2. Si arriba/abajo no son distinguibles del ruido o cambian entre intentos,
   revisar posición de webcam, distancia y luz. No insistir sobre cinco objetivos
   de validación con una señal que no permite aprender Y.
3. Medir las nueve fijaciones. Si falla aprendizaje, revisar el error por punto
   y repetir el señalado, o el centro desde el selector si cambió la postura.
   Si fallan varias zonas repetidamente, repetir las mediciones verticales antes
   de atribuir mejora a un nuevo algoritmo.
4. Si el aprendizaje pasa, completar los cinco objetivos nuevos. En rechazo
   global, repetir sólo una distracción reconocida; si persiste error en varias
   zonas, usar **Revisar aprendizaje**. No se aprende con esas validaciones.
5. Guardar únicamente tras aprobación, revisar la predicción segura y activar
   el cursor con confirmación explícita. Probar detención y pérdida de iris.

No se declara mejorada la precisión física por haber cambiado la interfaz o
aprobado tests. Esta sesión tiene una limitación vertical demostrada; la nueva
instrumentación permite distinguir sus causas en una próxima captura real.

## Verificación y entrega

- Rama conservada: `experiment/eye-tracking`. Sin commits, pushes ni merges.
- Respaldo antes de esta intervención: `/tmp/headmouse-validation-backup-20261027/`.
  Incluye fuentes y diff de los cambios previos; no se modificaron perfiles reales.
- Suite completa: **383 tests, OK (2 omitidos)**, 36.774 s, salida 0.
  Log: `/tmp/headmouse-validation-delivery.txt`.
- Se cubren errores de 400 px con 28 muestras estables, sesgo de validación,
  normalizado/píxeles con distintos DPR, asociación canónica, fallo de aprendizaje
  con variación Y incoherente, repetición 4/5 sin perder el resto, regreso a
  aprendizaje, separación de entrenamiento/validación y botón de recuperación.
  Las pruebas existentes conservan guardado/relectura, contexto, nariz,
  preservación del perfil, cancelación y autorización con backend simulado.
- `app.py --check` nativo macOS: salida 0. `git diff --check`: sin errores.
- Revisión visual con datos sintéticos, sin webcam ni entrada del SO:
  `/tmp/headmouse-validation-review.png`.
- Una instancia ya abierta debe reiniciarse para cargar estos cambios. No se
  cerró por la fuerza la sesión física del usuario ni se descartaron datos en RAM.

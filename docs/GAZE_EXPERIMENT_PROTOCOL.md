# Protocolo reproducible: mouse, nariz y mirada

Estado: preparado para pilotaje, sin resultados físicos. Separar práctica,
calibración, validación del modelo y evaluación de interacción. Un test sintético
no cuenta como participante ni como ensayo de precisión.

## Preparación y registro

1. Asignar un identificador de participante y sesión sin datos personales.
   Registrar consentimiento y condiciones de participación según el protocolo
   universitario aplicable. Permitir detener o descansar en cualquier momento.
2. Registrar fecha, rama/commit y diff utilizado (esta entrega no tiene commit),
   Python/dependencias, PC, webcam/modelo/índice, resolución y FPS, monitor,
   resolución física, DPR/escalado Windows, iluminación, distancia ocular a la
   webcam en cm, postura, anteojos, ubicación de cámara y duración de preparación.
3. Conservar una copia local del perfil por sesión para análisis. No compartir
   perfiles ni resultados individuales en Git. No registrar fotos/video por
   defecto. Registrar motivos de exclusión sin inventar datos faltantes.
4. Usar un solo monitor para absoluto. Mantener luz, distancia y posición durante
   cada bloque. Guardar condiciones en el campo de notas de Experimentos; cada
   ensayo congela esas notas, parámetros y calibraciones en JSONL local.

## Pilotaje de seguridad previo

Con mouse físico disponible, verificar nariz sin regresiones y ojo relativo
(cuatro direcciones, neutral, amplitudes, guiños). Cambiar modos y comprobar que
acciones/sensibilidad vuelven a sus valores anteriores. Probar pausa, Detener,
F8/Escape con foco, pérdida y recuperación de rostro/iris, desconexión y cierre
durante control. Para failsafe, ejecutar una prueba deliberada y supervisada con
cursor en esquina; nunca deshabilitar `FAILSAFE`. Los atajos no son hooks globales.

Abrir con `.\.venv\Scripts\python.exe -X faulthandler -u app.py` y conservar
logs tras cualquier cierre. No evaluar participantes antes de completar este
pilotaje. Una falla de driver que exceda el cierre queda como incidente abierto.

## Calibración y evaluación de punto de mirada

1. Elegir perfil; elegir y guardar Ojos absolutos. Calibrar/validar gestos para
   esa modalidad si hace falta. La calibración facial y la direccional son
   independientes. El diagnóstico puede abrirse sin modelo absoluto.
2. Ejecutar nueve puntos mirando el centro del objetivo amarillo sin seguir
   el puntero físico. Esperar cuenta regresiva, estabilización y captura.
   Repetir puntos con baja calidad o errores. No mover el mouse al capturar.
3. Capturar los cinco objetivos independientes. Conservar error por eje,
   euclidiano medio/p95, peor zona, jitter RMS, deriva intrafijación, rechazos,
   número de muestras y tiempo de procesamiento. Si falla la puerta de error,
   repetir calibración o usar ojos relativos; no excluir silenciosamente fallos.
4. Guardar únicamente al aprobar. Verificar predicción segura a pantalla completa
   antes de confirmar control real. Probar primero objetivos grandes. No esperar
   precisión para controles pequeños a partir del umbral permisivo inicial.
5. Para medir deriva temporal, repetir una captura/validación al inicio y al
   final de un bloque sin cambiar condiciones, conservando ambos registros. La
   métrica `drift_px` de una fijación por sí sola no mide deriva de toda la sesión.

Los objetivos de validación automática son distintos de los de ajuste, pero
una validación repetida hasta aprobar pierde independencia estadística. Para la
tesis reservar además una serie final de objetivos nunca usada para seleccionar
modelo/umbrales, y reportar todos los reintentos y el tiempo total de calibración.
La GUI actual ofrece la validación de cinco objetivos; esa serie final requiere
instrumentación adicional o una tarea de evaluación previamente definida.

## Comparación de interacción

Cuatro condiciones: A mouse convencional, B nariz, C ojos relativos, D ojos
absolutos. Usar bloques contrabalanceados, por ejemplo secuencias de Williams
`A B D C`, `B C A D`, `C D B A`, `D A C B`, asignadas sucesivamente entre
participantes. Registrar el orden real. Las ausencias de una condición se
registran como tales, sin sustituir resultados.

- Dar la misma práctica inicial por condición (propuesta piloto: dos series),
  sin incluirla en la comparación. Conceder descansos y registrar fatiga 0–10
  antes/después de cada bloque y cualquier malestar o abandono.
- Propuesta piloto: cuatro series medidas de los cinco objetivos por condición,
  con radio/ventana iguales y 60 s máximos por objetivo. Estos números son un
  plan inicial que debe fijarse antes del estudio definitivo, no una estimación
  del tamaño muestral necesario. Usar un análisis de potencia acorde al diseño.
- En Experimentos elegir Mouse convencional para A, o Control real · HeadMouse
  con modalidad guardada y confirmada para B/C/D. Mantener visible el canvas.
  Los clics son físicos en A y gestos explícitos equivalentes en B/C/D.
- Registrar tiempos, distancia de trayectoria, entradas/salidas del objetivo,
  clics erróneos, éxito/timeout/cancelación, número de ensayos completados y
  fatiga. Incluir tiempo/reintentos de calibración como costo de la modalidad.
- El canvas usa 800×500 unidades lógicas: sus distancias no son píxeles físicos.
  Documentar su tamaño real, radio y escala. Los movimientos fuera del canvas
  pueden observarse por polling, pero no hay registro global de clics fuera de
  la aplicación. Esa limitación puede subestimar errores de selección.
- Los objetivos de adquisición actuales tienen secuencia fija; reportar posible
  aprendizaje. Un estudio definitivo puede requerir más posiciones, tamaños y
  orden aleatorio con semilla persistida antes de la recogida de datos.

## Métricas y análisis

Analizar primero por participante y condición para evitar tratar todos los
ensayos de una persona como participantes independientes. Reportar dispersión,
intervalos de confianza y datos faltantes además de medias/medianas. Predefinir
criterios de exclusión y análisis pareado acorde al diseño; no declarar mejoras
estadísticas sin los datos y supuestos correspondientes.

| Variable | Fuente y límite |
|---|---|
| Error gaze X/Y/euclidiano | Validación independiente en píxeles físicos, por zona |
| Estabilidad | RMS de dispersión de predicción por fijación; jitter del laboratorio declara unidades distintas |
| Deriva | Intrafijación automática; comparar sesiones separadas para deriva temporal |
| Tiempo, trayectoria, selección | `data/experiments/*.jsonl`; unidades lógicas del canvas |
| Pérdida de tracking | Rechazos por fijación y `data/metrics` para pérdidas de rostro; cobertura de iris requiere analizar ambos registros |
| Latencia | `processing_ms` mide envío a MediaPipe→extracción; no incluye toda la captura, Qt, backend y monitor |
| Fatiga/carga | Registro subjetivo antes/después y cuestionario definido para la tesis; sin inferirlo de FPS |

Para latencia extremo a extremo o ground truth ocular independiente hace falta
instrumentación adicional. La posición del objetivo conocido supone que la
persona lo mira; no verifica fisiológicamente su fijación. Webcam RGB, reflejos,
resolución, párpados, anteojos y postura limitan el sistema. Registrar fracasos y
abstenciones como resultados, no como ausencia de observaciones.

# Experimentos locales v0.3

Esta versión incorpora infraestructura para adquisición de objetivos y estabilidad. No contiene resultados con participantes ni demuestra precisión con una cámara real. Los tests usan datos sintéticos y entradas simuladas.

## Adquisición de objetivos

Desde **Experimentos**, elegí simulación con HeadMouse, simulación con teclado o HeadMouse real. Iniciá la serie y seleccioná los cinco círculos sucesivos. En práctica con teclado, las flechas desplazan el cursor interno y Espacio/Enter seleccionan. No requiere cámara. La simulación con HeadMouse usa la cámara y el detector, pero no construye el backend del sistema. Para seleccionar, asociá un gesto a clic izquierdo o doble clic.

El modo real requiere activar y confirmar el control antes de iniciar. La posición del puntero se transforma al espacio del área experimental. Solo se cuentan clics recibidos dentro de esa superficie; los clics fuera del área o sobre otras aplicaciones no se observan. No hay captura global de entradas.

El espacio lógico es de 800 × 500 unidades, independiente del tamaño dibujado. Los objetivos tienen radio 35 y centros `(640,120)`, `(160,380)`, `(650,380)`, `(150,120)` y `(400,250)`. Cada ensayo tiene un máximo de 60 segundos. El cursor conserva su posición entre objetivos. Completar o agotar un ensayo inicia el siguiente; cancelar guarda el ensayo actual como incompleto.

## Formato de resultados

Cada ensayo se agrega inmediatamente a `data/experiments/<session_id>.jsonl`, una línea JSON por objetivo. No se almacenan imágenes ni video. La trayectoria del puntero sí es información del experimento y queda local junto al identificador del perfil.

| Campo | Definición |
|---|---|
| schema_version, experiment | Versión 1 y `target_acquisition`. |
| session_id, profile_id | Identificadores de sesión y perfil; `demo` si la práctica no tiene perfil. |
| mode, input_source, tracking_method | Simulación/real, HeadMouse/teclado y estrategia nasal disponible. En práctica con teclado no se realiza tracking facial. |
| trial, target, radius, coordinate_space | Número de ensayo, centro, radio y espacio lógico. |
| started_at, ended_at | Fechas ISO 8601 UTC del inicio y cierre. |
| duration_s | Tiempo transcurrido hasta clic exitoso, timeout o cancelación, con reloj monotónico. |
| trajectory | Lista `[segundos_desde_inicio, x, y]` con posición inicial y observaciones. |
| distance_px | Suma de distancias euclidianas entre posiciones; unidades lógicas del canvas, no píxeles físicos del monitor. |
| overshoots | Transiciones desde dentro del círculo hacia fuera antes de finalizar. |
| failed_clicks | Selecciones observadas fuera del círculo. |
| completed, reason | Éxito y motivo `completed`, `timeout` o `cancelled`. |
| fps_mean, processing_ms_mean | Promedio aritmético de las muestras de rendimiento recibidas. `null` si no se suministraron, como en práctica con teclado. |

La latencia representa procesamiento del motor de visión; no es latencia extremo a extremo hasta la respuesta del sistema. Las muestras de rendimiento pueden tener distinta frecuencia en modo real y simulado. No deben compararse como benchmarks sin controlar hardware, FPS, condiciones de captura y frecuencia de observación. La configuración completa no se congela en cada registro: conservá una copia del perfil y la versión del código para un protocolo reproducible.

## Estabilidad / jitter

En **Diagnóstico**, iniciá la medición y mantené la cabeza en posición neutral durante diez segundos. Se usan coordenadas nasales normalizadas, previas al suavizado del cursor. Solo se aceptan frames válidos, recientes y con timestamp nuevo. Con menos de dos muestras el resultado es inválido.

Para cada muestra, `dx` y `dy` son la diferencia respecto de la posición neutral calibrada. El resumen contiene:

- `mean_deviation`: media de `sqrt(dx² + dy²)`.
- `std_deviation`: desviación estándar poblacional de esas distancias radiales.
- `std_x`, `std_y`: desviación estándar poblacional por eje.
- `range_x`, `range_y`: máximo menos mínimo por eje.
- `jitter_rms`: raíz de la media de los cuadrados de las distancias entre muestras consecutivas.
- `dead_zone_exits`: entradas al exterior del rectángulo `abs(dx) <= dead_zone` y `abs(dy) <= dead_zone`.

Se guarda únicamente el resumen JSONL con número de muestras, duración y unidades `normalized_frame`, perfil y método. No se guardan landmarks ni muestras faciales individuales. Dos muestras permiten calcular las fórmulas, pero no garantizan cobertura suficiente de los diez segundos: revisá el número de muestras y las pérdidas de tracking antes de interpretar el resultado. El jitter depende de la frecuencia de muestreo; no es una medida normalizada por segundo.

## Verificación pendiente con personas

Comprobar tamaño y accesibilidad de objetivos, lateralidad, iluminación, timeout, selección real, coordenadas en distintos DPI/monitores y recuperación ante pérdida de cámara. Para la tesis aún hacen falta protocolo, consentimiento, ground truth, repetición de condiciones y análisis estadístico; la infraestructura no sustituye esas etapas.

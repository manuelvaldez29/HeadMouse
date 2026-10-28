# Métricas locales de sesión

Cada ejecución normal de main.py produce `data/metrics/session-<uuid>.json`
al cerrar, incluso ante errores si el cierre Python se ejecuta. `--no-metrics`
desactiva recolección y escritura. No se guarda video, fotos, frames, landmarks
ni secuencias de ratios. Solo identificación de perfil y agregados de sesión.

En v0.3, abrir una cámara desde la GUI inicia una sesión; cerrarla, cambiar perfil
o aplicar configuración cierra y guarda esa sesión. **Métricas** muestra FPS
actual de captura, FPS medio, latencia media de procesamiento, sesiones cerradas,
eventos, pérdidas, clics y scrolls. Los contadores suman historial y sesión activa;
las medias se calculan con frames y duraciones acumulados, no promediando medias
de sesiones de diferente duración. El listado contiene las sesiones cerradas.
Diagnóstico y simulación pueden generar eventos sin acciones reales, por lo que
no deben interpretarse como clics ejecutados en el sistema.

| Campo | Definición |
|---|---|
| profile_id, started_at, duration_s | Perfil, inicio UTC y duración monotónica; incluye inicio de cámara y pausas. |
| frames_processed | Callbacks de MediaPipe entregados y procesados, con o sin rostro; no frames capturados. |
| fps_mean | Callbacks / duración total. No equivale a frecuencia del loop de control ni al FPS del overlay (captura, ventana de 1 s). |
| processing_ms_mean/max | Desde timestamp de envío (antes de conversión RGB) hasta fin de extracción del callback. Incluye espera asíncrona y procesamiento, no adquisición física. |
| detection_to_action_ms_mean/max | Fin de extracción → retorno de llamada del backend, solo acciones realizadas con origen conocido. Incluye espera del loop; no tiempo físico de pantalla. |
| latency_samples | Acciones con latencia disponible; si no hubo, mean/max son null. |
| events_generated, events_total | Eventos del GestureEngine, incluyendo cursor y pausa, aunque se bloqueen por pausa. |
| actions_executed | Eventos realmente ejecutados; cursor solo si el delta entero no es cero; incluye toggle interno. |
| clicks, scrolls | Acciones de click y llamadas de scroll, no número de líneas desplazadas. |
| tracking_losses | Transiciones de dato utilizable a ausente/inválido/vencido; no cuenta ausencia inicial repetidamente. |

El costo de memoria no crece con la duración: contadores, sumas, máximos y
diccionarios de tipos de evento/acción permitidos. Hay lock entre callback y consumidor.
No hay escritura por frame; una terminación abrupta del proceso puede perder la
sesión. `ControlStats.events_total` del overlay conserva el contador de acciones
discretas ejecutadas, ahora incluyendo pausa; para análisis usar los campos
definidos del JSON.

## Uso académico y límites

No hay números de rendimiento real todavía. Para comparar sesiones registrar
por separado hardware, resolución, iluminación, versiones, cámara y configuración
del perfil; controlar pausas y duración. No comparar FPS medios como si fueran
inferencias por segundo activo. La latencia reportada no incluye el hold completo
del gesto: toma la detección del frame que finalmente generó el evento.

v0.3 incorpora adquisición de objetivos y jitter neutral en un formato separado
documentado en [EXPERIMENTS](EXPERIMENTS.md). Para v0.5 quedan tareas anotadas,
eventos esperados vs observados, precisión/recall, falsos positivos por minuto y
cuestionarios de esfuerzo/usabilidad. Estos resultados requieren
ground truth y protocolo consentido, no pueden inferirse de los contadores actuales.
Percentiles de latencia, exportación CSV y persistencia periódica son extensiones
pendientes, no métricas implementadas.

## Pantalla Métricas (2026-10-28)

`metrics_summary.py` lee los resúmenes de `data/metrics/` sin modificarlos. Una
sesión entra en las tasas si ejecutó alguna acción (control activo, aunque haya
estado en pausa) y duró al menos 30 s. Las de vista previa, diagnóstico o
calibración no ejecutan acciones y se informan aparte. Para cada sesión se calculan
clicks, scrolls, pausas (acción `PAUSE`) y pérdidas de rostro por minuto, dividiendo
por su duración. Los indicadores agregados dividen el total de eventos por el total
de minutos, para que una sesión corta no pese igual que una larga.

Las pausas por minuto cuentan todas las pausas ejecutadas, intencionales o no: no
hay ground truth para distinguirlas. Sirven para comparar la misma persona antes y
después de un cambio (por ejemplo, `brow_motion_gate`), no como tasa de falsos
positivos.

Gráficos: tres franjas con la misma escala, una por serie, en lugar de tres líneas
superpuestas, porque con decenas de sesiones esas líneas se cruzan. Colores
validados con la guía de visualización sobre el fondo de tarjeta `#172337`: azul,
naranja y verde azulado pasan separación para daltonismo (ΔE 9,4) y contraste. La
serie única de pérdidas de rostro va en gris neutro, porque con cuatro colores
ninguna combinación pasa entre todos los pares. La tabla de sesiones es la vista
accesible de los mismos datos.


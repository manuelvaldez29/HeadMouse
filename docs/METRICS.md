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

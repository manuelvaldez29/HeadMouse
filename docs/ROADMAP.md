# Roadmap de tesis

La contribución se centra en personalización, supresión de activaciones
involuntarias, interacción multimodal, accesibilidad y evaluación cuantitativa
sobre hardware convencional. Todas las etapas mantienen funcionamiento local.

| Versión | Objetivo | Evidencia de aceptación propuesta |
|---|---|---|
| v0.2 | Baseline y consolidación | Tests sintéticos, perfiles validados, configuración, métricas definidas y protocolo manual documentado. Medición física pendiente. |
| v0.3 | Desktop Accessibility Application | GUI PySide6, perfiles y calibración visual, diagnóstico, configuración, acciones, experimentos y jitter implementados. Pruebas automáticas con hardware simulado; evaluación física y con usuarios pendiente. |
| v0.4 | VoiceEngine offline y arquitectura multimodal | Comandos locales opcionales, arbitraje temporal voz/gesto, cancelación segura, comparación unimodal/multimodal. |
| v0.5 | Sistema experimental y benchmarking | Protocolo reproducible, ground truth, precisión/recall por gesto, FP/minuto, latencia, tareas de selección y usabilidad. |
| v0.6 | Comparación de tracking | Implementar EyeCenterTrackingStrategy y HeadPoseTrackingStrategy; comparar con NoseTrackingStrategy en precisión, jitter, estabilidad y latencia, con igual protocolo. |
| v0.7 | Rendimiento CPU | Perfilar captura/inferencia/control, medir consumo CPU/RAM, percentiles de latencia y estabilidad en sesiones largas; optimizar contra baseline. |
| v1.0 | Distribución y evaluación final | Instalador Windows, modelo incluido/licencias, funcionamiento offline, recuperación de fallos, documentación y evaluación final reproducible. |

Prioridad inmediata: prueba física de v0.3 y evaluación de accesibilidad. Verificar
lateralidad de gestos, sensibilidad tras eliminar frames duplicados, thresholds
por usuario, pérdida/recuperación de rostro, desconexión de cámara, failsafe,
DPI/monitores y cierre. No reemplazar tracking por una alternativa sin medirla.

Mantener una baseline etiquetada por el equipo cuando corresponda, sin asumir
que esta implementación ya contiene resultados experimentales. Adaptación
continua del perfil durante uso, selección accesible de gestos y normalización
de velocidad respecto de FPS requieren diseño y experimentos futuros.

# Auditoría inicial — HEADMOUSE v0.2

Se inspeccionaron todos los archivos versionados antes de modificar código.
Rama inicial: `tesis-v0.2`; árbol limpio. No había tests, configuración externa,
perfiles individuales ni infraestructura de métricas.

| Archivo | Responsabilidad y hallazgos iniciales |
|---|---|
| main.py | Composición y overlay OpenCV. Configuración duplicada, espera fija de inicio, limpieza fuera del alcance de errores de inicialización; no detecta hilos muertos. |
| vision_engine.py | Captura en hilo daemon y callback MediaPipe LIVE_STREAM. Lock sobre último snapshot/frame. Descarga implícita en constructor, ruta relativa al cwd, sin timeout. Sin finally para cámara/detector; fallos de captura reintentados indefinidamente. Snapshot mutable y sin validación de finitud; escala degenerada sustituida por 1. FPS de captura confundible con detección. |
| gesture_engine.py | Joystick nasal, EMA, zona muerta, curva lineal/cuadrática y seis máquinas hold/cooldown. Reutiliza frames; no reinicia hold al perder rostro; dos ojos cerrados pueden producir ambos clicks. Lee calibración dos veces, una con except Exception silencioso. |
| control_engine.py | Acciones PyAutoGUI en otro hilo, inicio pausado, failsafe y autopausa. Dos lecturas de FaceData por tick pueden diferir. Detección congelada mantiene control; excepciones inesperadas se ignoran. Toggle puede mezclarse con acciones. FPS mide loop, eventos excluyen cursor y pausa. Configura PyAutoGUI al importar. |
| calibrate.py | Seis fases, medianas y percentiles 10/90, interpolación al 60%. Buena base personalizada bilateral. Repite snapshots, acepta muestras vacías como cero, no registra variabilidad, guarda inmediatamente un único JSON global. Sin finally ni detección de fallo del hilo. |
| debug_cursor.py | Diagnóstico sin SO; replica fórmula y parámetros y carga global; puede quedar esperando cámara indefinidamente. |
| requirements.txt | Cuatro dependencias sin techo de versiones; compatibilidad no reproducible entre entornos. |
| README.md | Instrucciones mínimas; faltan entorno, modelo offline, seguridad, tests y arquitectura. |
| .gitignore | Excluye modelo y calibración global, no futuros perfiles/métricas. |

## Riesgos y prioridades

1. Alta: datos antiguos/NaN, hold sobreviviente a pérdida, parpadeo bilateral,
   excepciones de control ignoradas y recursos no liberados.
2. Alta: calibraciones sin muestras suficientes o con umbrales indistinguibles
   del neutral; sobreescritura entre usuarios.
3. Media: acoplamiento de lógica pura a librerías de cámara/SO, timestamps de
   pared, configuración dispersa, ausencia de pruebas y métricas definidas.
4. No se identificó acumulación ilimitada de imágenes: se conserva un frame.
   Las listas FPS se recortan a un segundo. El riesgo principal es liberación
   de recursos nativos frente a excepciones, no un leak Python demostrado.
5. Windows es el objetivo inicial; permisos de cámara, DPI, monitores múltiples,
   latencia y reconocimiento real requieren validación física.

## Plan incremental

Mantener módulos e imports públicos; extraer dataclasses/configuración y lógica
pura a archivos auxiliares. Preservar landmark 1, espejo y fórmula del cursor.
Consolidar parámetros y rutas; perfiles JSON versionados con escritura atómica
y lectura legacy; validar datos y tiempos monotónicos. Conservar estadística de
calibración, agregar MAD neutral y validación interactiva sin ControlEngine.
Instrumentar agregados locales sin frames. Probar por inyección de reloj,
backend SO y datos sintéticos. Documentar cambios y límites manuales.

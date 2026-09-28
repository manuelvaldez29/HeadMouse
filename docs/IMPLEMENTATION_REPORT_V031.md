# HeadMouse v0.3.1 — informe de implementación

Fecha de cierre técnico: 2026-09-26. Repositorio existente
`C:/Users/juliand/Desktop/headmouse/HeadMouse`, rama `tesis-v0.2`.
Todos los cambios quedan locales, sin commit, push ni cambio de rama.

## Resultado

La calibración comparte un motor genérico para los seis gestos actuales y
señales futuras. `GestureCalibration` recibe canales orientados y ventanas de
repeticiones; los adaptadores encapsulan las diferencias de ojos, cejas y boca.
GUI y CLI usan la misma sesión. Se conservaron MediaPipe, PyAutoGUI, tracking
nasal, perfiles, mapeos, métricas, experimentos y controles de seguridad.

| Requisito | Implementación y evidencia |
|---|---|
| Separación insuficiente | `validate_calibration` vuelve a rechazarla; los dos tests iniciales que fallaban ahora pasan. |
| Ambas cejas explícitas | Captura propia de dos canales; prueba donde su amplitud es menor que la unilateral. |
| Repeticiones | Tres por defecto, neutral/activo, descarte de transiciones, muestras únicas y recuperación de tracking. |
| Ajuste adaptativo | Mediana/MAD/percentiles, margen robusto y optimización de exactitud balanceada de la peor repetición. |
| Histéresis | Compuerta genérica para señales crecientes/decrecientes y compuestas; pruebas de oscilación. |
| Arbitraje | Ventana de 200 ms configurable; secuencias simultáneas, 80/120 ms y mayores que la ventana, ambos lados. |
| Blendshapes | Cinco nombres oficiales, salida habilitada, adaptadores GEOMETRIC/BLENDSHAPE/HYBRID; captura y detección probadas en la misma escala. |
| Calidad | Score, clases, causas, repeticiones válidas y repetición selectiva; no se interpreta como precisión clínica. |
| Feedback | Medidor, instrucciones, intento, calidad provisional, diagnóstico avanzado y controles persistentes. |
| Validación tolerante | Ruido aislado tolerado, gesto incorrecto sostenido rechazado y neutral contabilizado sin sumar intervalos ruidosos. |
| Gestos opcionales | Omitidos de captura/detección/validación, mapeados inicialmente a NONE; caso de un solo guiño probado. |
| Compatibilidad | Lectura de perfiles anteriores válidos, umbral único y conjunción unilateral para ambas cejas; rechazos claros de perfiles deficientes. |
| Telemetría | JSONL local por ajuste, incluye intentos débiles y reintentos, sin duplicados ni muestras individuales. |
| Documentación | Método y limitaciones en CALIBRATION_V031; README, GUI, calibración, arquitectura, mapeo y roadmap actualizados. |

## Verificación ejecutada

- Suite inicial: 53 tests, 51 aprobados y 2 fallidos por el `pass` de separación.
- Suite final: **82 tests aprobados**, sin omisiones de Qt, con webcam/backend
  simulados. Incluye 18 tests del motor adaptativo, 10 de sesión y 7 de GUI.
- La prueba anterior de evento incorrecto se actualizó para comprobar tanto
  tolerancia aislada como rechazo sostenido; la del wizard se actualizó a las
  siete fases y tres repeticiones. Se conserva la cobertura anterior.
- `app.py --check`: aprobado, sin cámara ni control real.
- `tests/smoke_runtime.py`: aprobado con MediaPipe 1.0.1 y modelo local,
  blendshapes habilitados e imagen negra en RAM; llamadas de mouse/teclado
  bloqueadas. No verifica detección de gestos sobre caras reales.
- `config.example.json` cargado mediante `load_config`: válido, tres repeticiones,
  GEOMETRIC y ventana de 200 ms. `noise_multiplier=1.5` conserva el default que
  ya tenía el repositorio; el ejemplo se alineó con él.
- `git diff --check`: sin errores. Raíz y rama verificadas nuevamente al cierre.
- Revisión visual offscreen: calibración con medidor bilateral a 1240×850 y
  980×700, diagnóstico normal/avanzado. En tamaño compacto se desplaza el
  contenido; las acciones principales permanecen visibles. Capturas sintéticas
  en `docs/screenshots/v031-*.png`, sin imágenes de usuarios.

No se validó físicamente ni se midió una mejora de precisión. El protocolo
pendiente está enumerado en [CALIBRATION_V031](CALIBRATION_V031.md#límites-y-prueba-física-pendiente):
repeticiones cómodas y fatiga, ambas cejas y desfases, histéresis/ruido, fuentes
experimentales con ground truth, iluminación/pose/tracking, DPI/accesibilidad,
acciones reales y seguridad. Los perfiles antiguos deficientes deben recalibrarse;
un perfil cargado requiere captura nueva para volver a medir, porque no guarda
muestras crudas. Las ventanas parciales canceladas no se exportan a telemetría.

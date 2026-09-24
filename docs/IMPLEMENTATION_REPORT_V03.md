# Informe — HEADMOUSE v0.3 — DESKTOP ACCESSIBILITY APPLICATION

Fecha: 2026-09-23. Repositorio existente, rama `tesis-v0.2`. No se creó otro proyecto, no se cambió de rama y no se realizaron commits ni push. El informe v0.2 se conserva como documento histórico.

## 1. Estado inicial

v0.2 tenía VisionEngine, GestureEngine, ControlEngine, perfiles JSON, configuración central, calibración estadística y validación, métricas y CLI. Se inspeccionaron los archivos y la documentación antes de editar y se ejecutaron los **33 tests existentes**, todos correctos. El diseño y los hallazgos iniciales quedaron en [V03_AUDIT_PLAN](V03_AUDIT_PLAN.md). Los cambios previos de v0.2 ya estaban sin commit: la lista de Git no equivale a una lista exclusiva de cambios v0.3.

## 2. Arquitectura implementada

PySide6 agrega una capa de presentación sobre los motores existentes. MainWindow y widgets dibujan y emiten comandos; DesktopBridge los entrega a un QObject en QThread; ApplicationController coordina perfiles, estados, motores, calibración y experimentos. VisionEngine conserva su hilo de captura y MediaPipe asíncrono. Un mailbox de capacidad uno transporta el último snapshot sin acumular frames.

ActionMapping separa identidad facial de acción. TrackingStrategy formaliza el contrato con NoseTrackingStrategy como única opción habilitada. CalibrationSession reutiliza estadísticas y validación CLI. ExperimentEngine y JitterMeasurement son lógica independiente de Qt y hardware. El backend PyAutoGUI se construye únicamente al activar explícitamente el control. Ver [arquitectura](ARCHITECTURE.md).

## 3. Archivos nuevos de v0.3

- Entrada y lanzamiento: `app.py`, `HeadMouse.vbs`.
- Coordinación y lógica: `application_controller.py`, `profile_manager.py`, `calibration_session.py`, `action_mapping.py`, `experiment_engine.py`.
- Presentación: `desktop/__init__.py`, `desktop/bridge.py`, `desktop/window.py`, `desktop/widgets.py`, `desktop/style.py`, `desktop/theme.qss`.
- Verificación: `tests/test_desktop_logic.py`, `tests/test_gui.py`, `tests/render_gui.py`.
- Documentación: `docs/V03_AUDIT_PLAN.md`, `docs/GUI.md`, `docs/EXPERIMENTS.md`, `docs/ACTION_MAPPING.md`, este informe y capturas `docs/screenshots/v03-*.png`.

## 4. Archivos modificados respecto de la base v0.2

`config.py` y `config.example.json` incorporan sensibilidad por eje, UI y acciones. `profiles.py` admite borradores y metadatos visuales. `gesture_engine.py` conserva identidad de gesto y expone diagnóstico; `tracking.py` formaliza la estrategia. `control_engine.py` aplica mappings y revocación de salida. `face_data.py` y `vision_engine.py` transportan landmarks relevantes volátiles. `calibration_validation.py` permite repetir el gesto actual. `calibrate.py` conserva settings y nombre del perfil. `main.py` incorpora mapping y rechazo temprano de borradores. Se actualizan `requirements.txt`, `requirements-windows.lock.txt`, `.gitignore`, README, arquitectura, calibración, métricas y roadmap.

Los scripts `main.py`, `calibrate.py` y `debug_cursor.py` permanecen disponibles. MediaPipe y PyAutoGUI no fueron reemplazados. PySide6 es la única dependencia directa nueva; sus paquetes Qt y shiboken son dependencias transitivas.

## 5. Pantallas creadas

Ocho páginas: Inicio, Perfiles, Calibración, Diagnóstico, Configuración, Gestos y acciones, Experimentos y Métricas. Todas comparten navegación lateral y controles persistentes de activación/detención. Tema oscuro QSS, botones grandes, foco visible, formularios desplazables e instrucciones en español.

## 6. Funcionalidades implementadas

- Preview de cámara con estados, FPS, procesamiento y gesto/acción; overlays opcionales de landmarks, nariz, neutral, dead zone y dirección.
- Crear, seleccionar, renombrar sin cambiar identidad, eliminar con confirmación y recalibrar perfiles. Estados de borrador, calibrado sin validar y listo.
- Wizard de seis fases, cuenta regresiva, captura, validación de seis gestos, repetición, recalibración y guardado restringido a validación aprobada.
- Diagnóstico sin salida real, coordenadas faciales y virtuales, ratios, umbrales, desplazamiento y filtros.
- Configuración persistida en el mismo perfil: cámara, sensibilidad X/Y, smoothing, dead zone, timeout, hold/cooldowns y dibujo. Restaurar defaults con confirmación.
- Seis identidades de gesto asignables a once acciones, con defaults compatibles. Solo tracking nasal habilitado.
- Serie de cinco objetivos con simulación HeadMouse, práctica de teclado y modo real; registro JSONL de trayectoria, tiempo, distancia, overshoots, errores, éxito y rendimiento observado.
- Medición de estabilidad de diez segundos y resumen local de desviación, rango, jitter y salidas de zona muerta.
- Dashboard de sesiones, FPS, latencia, eventos, pérdidas, clics y scrolls.
- Control inicialmente desactivado, confirmación explícita, detención persistente, F8/Escape locales, failsafe y rechazo de datos vencidos o inválidos.

## 7. Tests anteriores

Se conservan **33 tests**: 20 en `test_core.py`, 4 en `test_entrypoints.py` y 9 en `test_safety.py`. Cubren perfiles, configuración, calibración, filtros, hold/cooldown, frescura, pausa, failsafe, cleanup y entradas CLI.

## 8. Tests nuevos

**14 tests de lógica** cubren mapping, nuevas acciones con backend mock, protocolo nasal y sensibilidad compatible, borradores/renombrado/borrado, settings e invalidación de validación, adquisición y persistencia, timeout/cancelación, jitter conocido, calibración completa con guardado a través del controlador, inicio seguro, activación/detención, interrupción durante arranque y limpieza ante error.

**6 tests Qt offscreen** cubren las ocho páginas, creación de perfil y estados de botones, preview y diagnóstico con cámara sintética, configuración y mapping desde widgets, inicio de calibración y detención, y una serie experimental completa con persistencia. No abren cámara física ni envían entradas reales.

## 9. Cantidad total

**53 tests unitarios/de integración: 33 anteriores + 20 nuevos.** El smoke nativo, la apertura/cierre de la app y las capturas son comprobaciones adicionales, no se suman artificialmente al conteo de tests.

## 10. Resultados y evidencia

- Suite completa de 53 tests: aprobada sin omisiones en el entorno con PySide6. Se volvieron a ejecutar pruebas relevantes tras cambios de lógica.
- `python app.py --check`: apertura y cierre correctos, sin cámara ni backend de control.
- `python tests/smoke_runtime.py`: aprobado; importa dependencias, comprueba CLI y procesa una imagen negra sintética con el modelo MediaPipe real. Entradas de mouse/teclado bloqueadas.
- `python -m pip check`: sin dependencias incompatibles.
- `git diff --check`: sin errores de whitespace; Git informa solamente normalización futura LF/CRLF del entorno Windows.
- Revisión visual de ocho páginas vacías y de Inicio, Calibración, Diagnóstico y Experimentos con datos sintéticos. Se corrigieron carga de fuentes offscreen, recorte de tarjetas y aspecto de botones primarios deshabilitados. Capturas locales disponibles en `docs/screenshots/`.

Entorno: Windows, Python 3.14.4, MediaPipe 1.0.1, OpenCV contrib 5.0.0.93, NumPy 2.5.3, PyAutoGUI 0.9.54 y PySide6 6.11.2. El lock incluye las dependencias de Qt. No se atribuye a estas pruebas evidencia de funcionamiento de una webcam real.

### Correspondencia con los requisitos

| Requisito | Evidencia de implementación y verificación |
|---|---|
| 1. Arquitectura GUI | `desktop/bridge.py`, `application_controller.py`; Qt real con worker en tests. |
| 2. Pantalla principal | `MainWindow.refresh`, CameraPreview; preview sintético en test GUI y capturas. |
| 3. Home | Accesos, estados y control persistente; test de navegación e inicio seguro. |
| 4. Perfiles | ProfileManager + página Perfiles; tests de CRUD y actualización visual. |
| 5. Wizard | CalibrationSession + CalibrationValidation; seis fases y validación completa en test, inicio Qt y guardado vía controlador. |
| 6. Diagnóstico | Snapshot diagnóstico y página dedicada; test verifica preview y ausencia de backend. |
| 7. Configuración | Formulario, AppConfig y perfil; test de edición/persistencia desde widgets. |
| 8. ActionMapping | Módulo independiente, once acciones y combos; tests de defaults, opciones y backend mock. |
| 9. Tracking | TrackingStrategy/NoseTrackingStrategy; prueba de contrato, coordenadas y sensibilidad anterior. |
| 10. Experimentos | ExperimentEngine/ResultStore/canvas; métricas conocidas y serie Qt completa persistida. Modo real implementado, prueba física pendiente. |
| 11. Jitter | JitterMeasurement; valores exactos, frames únicos y salidas de dead zone en test. |
| 12. Dashboard | Página Métricas, SessionMetrics e historial; render y tests anteriores de métricas. |
| 13. Seguridad | Confirmación, Event de revocación, botón y atajos, failsafe; tests de activación, interrupción, pausa y pérdida. |
| 14. UX | QSS organizado y capturas revisadas; accesibilidad con usuarios aún no evaluada. |
| 15. Tests | 53 tests sin cámara ni clics reales. |
| 16. Documentación | README, arquitectura, roadmap, GUI, experimentos y acciones actualizados/creados. |
| 17. Entry point | `app.py --check` y launcher; tests de preservación CLI y smoke nativo. |
| 18. Dependencias | requirements + lock, PySide6 autorizado, pip check correcto; sin servidor web/cloud/Docker. |
| 19. Finalización funcional | Evidencia combinada anterior cubre flujo desktop y motores; las verificaciones físicas se declaran pendientes sin simularlas. |

## 11. Limitaciones

La instalación inicial requiere Python y dependencias; el launcher depende de Windows Script Host. No hay instalador empaquetado. F8/Escape son locales a la aplicación. Una llamada nativa en curso no se puede cancelar instantáneamente y un driver bloqueado puede retrasar el cierre. Solo hay tracking nasal y la validación todavía exige los seis gestos, aunque se cambien sus acciones.

Los clics fuera del canvas no se contabilizan en el experimento real. Las coordenadas experimentales son lógicas, no píxeles físicos. La configuración completa no se congela en cada registro. Jitter requiere revisar cobertura de muestras y depende de la frecuencia de muestreo. No hay precisión/recall ni falsos positivos/minuto sin ground truth. No hay voz, macros, tracking ocular o head pose implementados.

La GUI reduce la necesidad de terminal durante el uso, pero no se afirma accesibilidad universal ni aptitud clínica. La calibración inicial puede requerir asistencia según las capacidades de la persona.

## 12. Validaciones manuales pendientes

Webcam y permisos; luz y lateralidad; seis gestos con usuarios; sensibilidad y smoothing; pérdida y recuperación de rostro; desconexión y cierre; movimiento/clic/scroll/teclas reales; failsafe; atajos con foco; DPI y múltiples monitores; objetivos en modo real; sesiones largas; evaluación de contraste, navegación y esfuerzo con personas usuarias. No se ejecutó webcam real automáticamente.

## 13. Instrucciones exactas para abrir

Con el entorno ya preparado: doble clic en `HeadMouse.vbs` dentro del repositorio. Alternativa PowerShell desde la carpeta actual:

```powershell
.\.venv\Scripts\python.exe app.py
```

Con `.venv` activado: `python app.py`. Preparación inicial, si hace falta:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --download-model
.\.venv\Scripts\python.exe app.py
```

No hace falta recrear el entorno existente. La descarga del modelo también está disponible mediante Configuración, con confirmación. Crear/seleccionar perfil → calibrar → validar → guardar → diagnóstico → activar control. Guía ampliada en [GUI](GUI.md).

## 14. Siguiente objetivo recomendado: v0.4

Primero completar la validación física y de accesibilidad de v0.3. Después incorporar VoiceEngine offline opcional, comandos acotados y arbitraje temporal voz/gesto con cancelación segura, manteniendo ApplicationController como coordinador. Comparar interacción unimodal y multimodal con el mismo protocolo de objetivos y estabilidad, sin cambiar el tracking de referencia antes de medirlo.

# Informe — HEADMOUSE v0.2

Fecha: 2026-09-23. Trabajo incremental sobre la rama existente `tesis-v0.2`.
Sin proyecto nuevo, sin otro directorio HeadMouse, sin commit ni push.

## 1. Estado inicial

Nueve archivos versionados, árbol limpio. Se leyeron completos antes de editar.
Pipeline funcional en tres módulos, calibración estadística por gestos, diagnóstico
y overlay; no había tests ni métricas persistentes. Configuración dispersa,
calibración global, cierre incompleto ante errores y riesgos de detecciones
reutilizadas. La auditoría detallada está en [AUDIT.md](AUDIT.md).

## 2. Archivos creados

- `config.py`, `config.example.json`: parámetros validados y ejemplo JSON.
- `requirements-windows.lock.txt`: versiones exactas del entorno nativo verificado.
- `face_data.py`: contrato inmutable y validación de datos/frescura.
- `profiles.py`: perfiles individuales y compatibilidad legacy, guardado atómico.
- `calibration_logic.py`: estadística pura, muestras únicas y calidad de umbrales.
- `calibration_validation.py`: reconocimiento guiado de seis gestos y neutral.
- `tracking.py`: contrato de estrategia y tracking nasal existente.
- `metrics.py`: agregados locales sin imágenes.
- `tests/test_core.py`, `tests/test_safety.py`, `tests/test_entrypoints.py`.
- `tests/smoke_runtime.py`: comprobación opt-in del runtime nativo sin webcam/SO.
- `docs/AUDIT.md`, `ARCHITECTURE.md`, `CALIBRATION.md`, `METRICS.md`,
  `ROADMAP.md`, `IMPLEMENTATION_REPORT.md`.

El entorno `.venv` de verificación está dentro del repositorio e ignorado por Git.
También se preparó `models/face_landmarker.task` mediante la descarga explícita;
el modelo está ignorado por Git y permite iniciar sin red.
Los directorios de perfiles/métricas se crean al usarlos; no se entrega un perfil
personal ficticio como si hubiera sido calibrado.

## 3. Archivos modificados

- `main.py`: selección de perfil/config, logging, chequeo sin hardware, descarga
  explícita de preparación, métricas, inicio coordinado y limpieza estructurada.
- `vision_engine.py`: conserva extracción MediaPipe; agrega validación,
  snapshots inmutables, timestamps monotónicos, límite de captura, readiness,
  errores observables y liberación en finally.
- `gesture_engine.py`: conserva fórmulas y máquinas; configura desde módulo
  central, procesa una detección única, reinicia ante pérdida/brechas, suprime
  parpadeo bilateral y admite estrategia/reloj inyectados.
- `control_engine.py`: backend inyectado, una lectura facial, bloqueo inmediato
  de datos inválidos, prioridad de toggle, métricas y detención ante error.
- `calibrate.py`: conserva fases y dibujo, delega estadística, repite fases
  incompletas, valida gestos sin acciones SO y guarda solo tras confirmación.
- `debug_cursor.py`: usa configuración/perfil y GestureEngine compartidos, con
  limpieza y detección de errores de captura.
- `requirements.txt`: OpenCV contrib en lugar de instalar dos proveedores de cv2.
- `.gitignore`: perfiles, métricas y configuración local.
- `README.md`: instalación, preparación offline, calibración, uso, tests y límites.

## 4. Decisiones arquitectónicas

No se agregó framework, paquete web, voz ni modelo. Se conservaron los módulos
públicos, reexportando FaceData/GestureConfig/ControlConfig. Los auxiliares puros
usan biblioteca estándar, para probar en un entorno sin cámara ni PyAutoGUI.
NoseTrackingStrategy devuelve las mismas coordenadas; las otras estrategias
quedan para experimentación futura.

Se conserva interpolación al 60% y percentiles bilaterales; MAD permite rechazar
umbrales inseguros. Se exige una prueba interactiva antes del guardado de nuevos
perfiles. El runtime CLI falla ante perfil ausente/inválido en lugar de habilitar
acciones con thresholds genéricos. El fallback del constructor legacy se conserva
con warning para compatibilidad de código.

Los cambios de comportamiento deliberados están explicados en ARCHITECTURE:
no reutilizar frames, bloquear datos vencidos, suprimir ambos ojos cerrados,
priorizar pausa y descargar el modelo solo mediante orden explícita. La velocidad
percibida puede cambiar al dejar de procesar dos veces el mismo snapshot.

## 5. Tests agregados

33 tests automatizados sobre thresholds, ruido neutral, configuración/precedencia,
perfiles/identidad/legacy, persistencia atómica y recuperación de JSON dañado,
FaceData inválido, muestras únicas, EMA/zona muerta, hold/cooldown/liberación,
parpadeo bilateral, ambas cejas, pérdida/brechas de tracking, métricas y desactivación,
límites del cursor, pausa, failsafe, errores de backend, cámara/detector/callback,
validación guiada completa y limpieza de puntos de entrada.

Todos usan datos sintéticos o mocks. No abren webcam ni mueven el cursor real.

## 6. Verificaciones ejecutadas

- `python -m unittest discover -s tests -v`: 33 tests aprobados.
- `python -m compileall -q` con los módulos y tests: aprobado.
- `git diff --check`: aprobado; Git avisa conversión LF→CRLF del entorno, sin
  errores de whitespace del diff.
- `main.py --help`, `calibrate.py --help`, `debug_cursor.py --help`: ejecutables
  incluso sin bibliotecas nativas instaladas.
- Arranque/errores/cierre de main y calibrate: verificados con mocks, sin hardware.
- Comprobaciones iniciales reales sin dependencias/perfil: salida 1 con explicación
  por ausencia de perfil y de cv2, sin apertura de cámara.

- Instalación de dependencias en `.venv`: completada con `--no-compile`.
- `.venv\Scripts\python.exe -B -m pip check`: `No broken requirements found`.
- Imports reales y reexports públicos: aprobados.
- `.venv\Scripts\python.exe -B main.py --download-model`: completado.
- `.venv\Scripts\python.exe -B tests\smoke_runtime.py`: aprobado. Ejecuta
  main/calibrate con `--check`, renderiza overlay en RAM y carga el modelo real
  en LIVE_STREAM con una imagen negra sintética. Hubo callback sin rostro,
  timestamp y duración de procesamiento válidos. Todas las llamadas SO del test
  están bloqueadas y no se construyó ninguna VideoCapture.
- Entorno: Windows / Python 3.14.4, MediaPipe 1.0.1, OpenCV contrib 5.0.0.93,
  NumPy 2.5.3, PyAutoGUI 0.9.54. Versiones transitivas en el lock.

MediaPipe emitió mensajes de inicialización XNNPACK CPU y feedback tensors; el
test terminó con código 0. Estos checks no sustituyen una sesión real ni un
benchmark. No se guardó ninguna imagen sintética o facial.

## 7. Problemas encontrados

Se corrigieron los riesgos detallados en AUDIT y los casos adicionales encontrados
durante pruebas: hold después de una pausa del consumidor, guardado fallido,
perfil corrupto que impedía recalibrar y coinstalación de OpenCV normal/contrib.
El entorno inicial tenía Python 3.14.4 y ninguna dependencia del proyecto; se
preparó un entorno separado dentro del repositorio. Un primer intento de pip
ocurrió antes de terminar venv y reportó `No module named pip`; se esperó la
finalización y se reintentó.
La instalación con compilación anticipada de bytecode fue muy lenta; se detuvo
solo ese instalador y se completó con `--no-compile`, seguido de `pip check`,
imports e inferencia nativa correctos.

## 8. Deuda técnica y validación manual

- Webcam física, lateralidad real, iluminaciones, usuarios, sensibilidad, DPI y
  monitores múltiples, pausa/retorno y desconexión requieren pruebas manuales.
- No hay números de latencia/FPS reales ni garantía de reducción cuantificada
  de falsos positivos. Métricas agregadas no contienen ground truth.
- Velocidad del joystick depende de FPS y trunca subpíxeles, como baseline.
- Gestos bilaterales con comienzo asimétrico aún pueden producir un scroll antes
  del toggle; medirlo antes de diseñar arbitraje temporal adicional.
- Driver nativo bloqueado puede exceder join; se informa, no se fuerza cierre.
- UI de calibración todavía requiere teclado y todos los gestos; accesibilidad
  configurable y GUI son v0.3.
- Perfiles sin cifrar, sin bloqueo entre procesos; no calibrar el mismo usuario
  simultáneamente. JSON de sesión puede perderse por terminación abrupta.
- Validación estadística heurística, no clínica; adaptación continua queda pendiente.

## 9. Comandos exactos

Desde la carpeta actual, PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --download-model
.\.venv\Scripts\python.exe calibrate.py --check
.\.venv\Scripts\python.exe calibrate.py --user julian --camera 0
.\.venv\Scripts\python.exe debug_cursor.py --user julian
.\.venv\Scripts\python.exe main.py --user julian --check
.\.venv\Scripts\python.exe main.py --user julian
python -m unittest discover -s tests -v
```

Si `.venv` ya está preparado, omitir su creación. Para thresholds antiguos con
identidad `julian`: `main.py --user julian --legacy-calibration calibration.json`.
Para opciones y configuración completa, consultar README y `--help`.

## 10. Siguiente objetivo

Validar físicamente esta baseline con al menos dos perfiles y un protocolo
documentado antes de v0.3. Luego implementar GUI accesible y gestión visual de
perfiles; conservar estas pruebas como regresión. ROADMAP detalla v0.3 a v1.0.

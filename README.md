# HEADMOUSE v0.3 — DESKTOP ACCESSIBILITY APPLICATION

Control local de PC con movimiento de cabeza y gestos faciales.
Tesis UNSTA 2026 — Bloj · Domfrocht · Petrelli · Valdez.

Esta versión conserva MediaPipe Face Landmarker, tracking nasal y PyAutoGUI;
agrega una aplicación PySide6 con perfiles, calibración visual, diagnóstico,
configuración, mapeo de acciones y experimentos locales. Plataforma inicial:
Windows con webcam RGB y CPU. No se requiere servicio cloud durante el uso.

## Abrir la aplicación

Después de preparar el entorno, hacé doble clic en **HeadMouse.vbs**. También
podés ejecutar desde este repositorio:

```powershell
.\.venv\Scripts\python.exe app.py
```

Con el entorno activado, funciona `python app.py`. Creá o seleccioná un perfil,
calibrá y validá los gestos, probá el diagnóstico y confirmá **Activar control**.
El control real comienza desactivado. **Detener control**, F8 o Escape lo
detienen; los atajos requieren que HeadMouse reciba el teclado.

La [guía visual](docs/GUI.md) explica el flujo completo. Los
[experimentos](docs/EXPERIMENTS.md) guardan JSONL en `data/experiments/` sin
imágenes. La instalación inicial todavía requiere preparar Python; no se
incluye un instalador independiente.

## Instalación en Windows (PowerShell)

Para una instalación nueva:

```powershell
git clone https://github.com/manuelvaldez29/HeadMouse.git
cd HeadMouse
```

Si ya tenés el repositorio, empezá directamente desde su carpeta actual:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --download-model
```

La última orden descarga una vez el modelo oficial en
`models/face_landmarker.task`. Requiere Internet solo durante la preparación;
también se puede copiar ese archivo desde una instalación preparada. El inicio
normal nunca intenta descargarlo. No se envían imágenes ni ratios a servidores.
Se usa la ruta del repositorio aunque Python se invoque desde otro directorio.

Entorno verificado: Windows, Python 3.14.4, MediaPipe 1.0.1, OpenCV contrib
5.0.0.93, NumPy 2.5.3, PyAutoGUI 0.9.54 y PySide6 6.11.2. Para reproducir exactamente esas
dependencias en Windows con esa versión de Python, usar
`-r requirements-windows.lock.txt` en lugar de `-r requirements.txt`.
El archivo general conserva rangos de versiones; otras combinaciones requieren
verificación. Si instalar demora por bytecode, pip acepta `--no-compile`.

Los comandos siguientes usan directamente el Python del entorno, sin cambiar
la política de ejecución de PowerShell ni necesitar activar el entorno.

## Calibrar y ejecutar por CLI (conservado)

```powershell
.\.venv\Scripts\python.exe calibrate.py --user julian --camera 0
.\.venv\Scripts\python.exe debug_cursor.py --user julian
.\.venv\Scripts\python.exe main.py --user julian
```

Calibración: SPACE comienza; seguir las seis fases. Después, SPACE inicia la
validación de gestos y retorno al neutral. Solo al aprobar, SPACE guarda en
`data/profiles/julian.json`; Q descarta. R permite repetir y C recalibrar durante
validación. `debug_cursor.py` muestra el resultado sin mover el mouse.

El sistema **arranca pausado**. Ambas cejas lo activan o pausan.

| Acción facial | Resultado |
|---|---|
| Desplazar cabeza | Cursor; nariz como joystick |
| Guiño izquierdo / derecho | Click izquierdo / derecho |
| Ceja izquierda / derecha | Scroll arriba / abajo, una acción por elevación |
| Ambas cejas | Pausa / reanudación |
| Boca abierta | Tecla Windows |

Ctrl+C termina. Q termina con el overlay enfocado. El failsafe de PyAutoGUI
permanece activo: una llamada de control detecta el cursor en una esquina y
detiene el sistema. Si no hay datos faciales recientes, no se ejecutan acciones.
Tras 2 s aparece autopausa, que se levanta al recuperar tracking; la pausa manual
se conserva. Los datos inválidos reinician gestos y filtro.

## Configuración y perfiles

```powershell
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe calibrate.py --user julian --config config.local.json
.\.venv\Scripts\python.exe main.py --user julian --config config.local.json --log-level DEBUG
.\.venv\Scripts\python.exe main.py --user julian --no-overlay --no-metrics
```

Todos los defaults están en `config.py`. Precedencia: defaults → archivo →
`settings` del perfil → flags CLI. La calibración conserva settings personales
existentes; para cambiarlos editar `settings` del perfil antes de recalibrar.
JSON inválido, parámetros desconocidos o umbrales incoherentes se rechazan.
Niveles de logging: DEBUG, INFO, WARNING, ERROR.

Calibración antigua: `--user default` busca `calibration.json` si falta su perfil.
Si el archivo antiguo identifica otro usuario, especificarlo:

```powershell
.\.venv\Scripts\python.exe main.py --user julian --legacy-calibration calibration.json
```

No se sobreescribe ni migra automáticamente. Para producir un perfil v2 con
validación, ejecutar `calibrate.py`. Sin perfil válido, main.py informa el error
y sale antes de abrir cámara. Los perfiles y métricas están excluidos de Git.

## Verificación sin cámara ni movimiento del mouse

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe app.py --check
python -m compileall -q main.py calibrate.py debug_cursor.py vision_engine.py gesture_engine.py control_engine.py config.py profiles.py face_data.py tracking.py calibration_logic.py calibration_validation.py metrics.py tests
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe calibrate.py --help
.\.venv\Scripts\python.exe calibrate.py --check
.\.venv\Scripts\python.exe main.py --user julian --check
.\.venv\Scripts\python.exe tests/smoke_runtime.py
```

Los tests usan FaceData sintético y mocks; nunca abren webcam ni llaman al
mouse real. Los tests de GUI requieren PySide6 y NumPy y se ejecutan offscreen;
si PySide6 falta se omiten, por lo que hay que usar el entorno completo para
verificar v0.3. Los tests de motores siguen siendo independientes de Qt. `--help` de los CLI tampoco
requiere bibliotecas nativas. `--check` verifica imports, configuración y archivo
de modelo; main verifica además el perfil. No prueba webcam, inferencia ni SO.
`tests/smoke_runtime.py` es una prueba opcional adicional: carga el modelo y
ejecuta inferencia real sobre una imagen negra sintética en RAM, sin cámara y
con las llamadas de mouse/teclado bloqueadas. Requiere dependencias y modelo;
no se incluye en el descubrimiento de tests unitarios.

Las métricas de sesiones normales se guardan en `data/metrics/`: FPS procesados,
tiempos aproximados, eventos, acciones y pérdidas de tracking. No se guardan
frames ni fotos. Ver definiciones y límites en [METRICS](docs/METRICS.md).

## Documentación y validación manual pendiente

- [Auditoría inicial](docs/AUDIT.md)
- [Arquitectura y cambios de comportamiento](docs/ARCHITECTURE.md)
- [Calibración y perfiles](docs/CALIBRATION.md)
- [Métricas](docs/METRICS.md)
- [Roadmap de tesis](docs/ROADMAP.md)
- [Uso de la GUI](docs/GUI.md)
- [Experimentos y jitter](docs/EXPERIMENTS.md)
- [Mapeo de gestos y acciones](docs/ACTION_MAPPING.md)
- [Informe v0.3: implementación, pruebas y limitaciones](docs/IMPLEMENTATION_REPORT_V03.md)
- [Informe histórico v0.2](docs/IMPLEMENTATION_REPORT.md)

Antes de usarlo como control habitual: calibrar con buena iluminación, revisar
en diagnóstico la lateralidad y la sensibilidad, probar cada gesto, pausa,
pérdida/retorno del rostro, desconexión de cámara y cierre. Verificar DPI y
monitores del equipo. Eliminar detecciones duplicadas puede cambiar la velocidad
percibida respecto de la versión anterior. No se presentan resultados de
rendimiento físico ni evaluación con usuarios que no hayan sido medidos.

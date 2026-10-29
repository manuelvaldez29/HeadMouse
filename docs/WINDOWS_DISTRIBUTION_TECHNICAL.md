# HeadMouse 0.4.0 — Distribución Windows, tesis V0.2

## Arquitectura y límites

Base integrada: `tesis-v0.2`, `500032e`. No se repite el merge ocular. Se conservan
VisionEngine, GestureEngine, estrategias, modelos y calibradores. DesktopBridge
sigue serializando las operaciones en el worker Qt. Los nuevos módulos son:

- app_paths: recursos de lectura, datos por usuario y comando de arranque.
- user_storage: copia validada sin sobreescritura, conflictos y marcadores por origen.
- startup_preferences: preferencias, autorización ligada al hash del perfil y registro HKCU.
- startup_safety: estabilidad facial/ocular sin backend ni cámara propios.
- desktop/resident: formulario, pregunta posterior, bandeja y coordinación de inicio.
- desktop/windows_session: avisos WTS/energía, consulta del escritorio y F8 nativo.
- desktop/single_instance: QLockFile y QLocalServer por usuario/directorio de datos.
- distribution_check: inferencia nativa sobre imagen negra en RAM, sin cámara/acciones.

## Almacenamiento

Recursos: app_paths.RESOURCE_ROOT, que PyInstaller resuelve dentro de _internal.
Datos: `%LOCALAPPDATA%\HeadMouse`. HEADMOUSE_DATA_DIR permite aislar pruebas; no
se necesita para el uso normal. Los datos nunca se escriben en Program Files o
en el directorio de recursos. La configuración y calibraciones por método/fuente
permanecen dentro del perfil JSON; las preferencias de inicio son por equipo.
Las preferencias puramente visuales existentes conservan QSettings UNSTA/HeadMouse.

La migración valida el perfil, copia bytes con creación exclusiva, fsync y SHA-256,
y registra el resultado por origen. Nunca modifica el original ni aprueba gestos.
Un conflicto se conserva fuera del banco activo, en migration-conflicts. Un perfil
inválido se informa y no se importa. No se exportan fotos ni landmarks.

## Inicio y autorización

Se usa `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, valor HeadMouse,
con ejecutable absoluto entre comillas y --autostart. En fuente se utiliza pythonw
y app.py. No hay servicio, HKLM ni Session 0. Desactivar elimina sólo ese valor.
Una escritura fallida de preferencias restaura la entrada anterior.

startup.json guarda las opciones apagadas inicialmente. La autorización explícita
incluye fecha y SHA-256 del perfil completo. Un cambio exige reautorizar; no es
una firma criptográfica contra el propio usuario del equipo. El worker comprueba
la autorización vigente sobre su perfil real antes de construir el control.

Se exige cámara lista, frames frescos/distintos, ausencia de bloqueos, al menos
10 frames/700 ms y dispersión de nariz <=.025 y mirada <=.04. No sustituye la
validación del modelo ni demuestra precisión. El controlador vuelve a comprobar
iris/fuente/contexto. Sólo movimiento sigue bloqueando acciones no autorizadas.

WM_WTSSESSION_CHANGE, WM_POWERBROADCAST y consulta OpenInputDesktop permiten
revocar la salida. Cada ciclo con control consulta además el escritorio antes de
ejecutar acciones. Al regresar se repite la puerta completa si había autorización
y no hubo detención manual. No se simularon un bloqueo/suspensión físicos del equipo
del usuario: los eventos se prueban con dobles. F8 usa RegisterHotKey, comprueba el
resultado y lo informa; nunca se promete global si falla el registro.

## Reconstrucción

Usar Windows x64 y el entorno de proyecto probado. Python no es un requisito
del usuario final, sí del equipo de compilación. Dependencias de ejecución:
requirements.txt; herramientas fijadas en requirements-build.txt. Preparar antes
models/face_landmarker.task desde la fuente oficial documentada por el proyecto.
`packaging/requirements-windows-py312-build.lock.txt` registra las versiones exactas
del entorno utilizado; es distinto del lock histórico para Python 3.14.4.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-build.txt
.\.venv\Scripts\python.exe main.py --download-model
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Iscc "RUTA\ISCC.exe"
```

El modelo puede copiarse desde una instalación preparada; el inicio habitual no
lo descarga. Si se descargó al directorio de datos, copiarlo a models para construir.
No se incluye ningún perfil personal, logs o preferencias en el spec.

PyInstaller genera dist/HeadMouse/HeadMouse.exe y _internal (debe distribuirse la
carpeta entera). Inno Setup genera dist/installer/HeadMouse-Setup-0.4.0-win64.exe.
Incluye icono, recursos y Qt. Es onedir/windowed, sin consola. La compilación limpia
el PATH para no tomar DLL de otras herramientas. No se distribuyen las ICU genéricas
de Poppler: Qt usa la API del Windows objetivo. Esto se verifica ejecutando el binario.

La aplicación básica no incluye los paquetes opcionales de dictado (faster-whisper,
comtypes) ni un modelo Whisper. El control por gestos no depende de esa extensión.
Los avisos sobre módulos opcionales en warn-HeadMouse.txt deben revisarse, no ignorar
un import requerido. Para habilitar dictado en otra distribución hay que instalar
requirements-voice.txt y agregar sus recursos/hook de empaquetado y pruebas.

## Instalador y actualización

packaging/HeadMouse.iss usa AppId estable y PrivilegesRequired=lowest. La instalación
por usuario conserva datos externos y sólo remapea una entrada Run preexistente;
no la crea ni autoriza al instalar. Ofrece escritorio y ejecución final desmarcados.
El desinstalador elimina el valor Run y conserva perfiles. No se firma esta edición.
Conservar licencias y metadatos de terceros distribuidos en _internal; revisar
sus condiciones al redistribuir fuera del contexto de tesis.

## Verificación reproducible

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\dist\HeadMouse\HeadMouse.exe --check
.\dist\HeadMouse\HeadMouse.exe --verify-runtime
.\dist\HeadMouse\HeadMouse.exe --check-resident
```

--check construye/cierra Qt sin cámara, residente ni autoactivación. --verify-runtime
importa el backend, Qt, OpenCV, NumPy y MediaPipe y ejecuta el modelo con imagen
sintética. Produce logs/distribution-check.json; no abre VideoCapture.
--check-resident comprueba el arranque con bandeja, registro temporal de F8 y
notificaciones de sesión, sin abrir cámara ni autoactivar. Sale por cierre normal
y deja logs/resident-check.json con el resultado real del registro nativo.

Para pruebas instaladas usar HEADMOUSE_DATA_DIR aislado y PATH reducido a System32,
sin PYTHONHOME/PYTHONPATH. Esto verifica autonomía del paquete en ese host, no
equivale a una máquina limpia. Instalar, ejecutar, actualizar y desinstalar en una
carpeta de ensayo; comparar bytes de perfiles y preferencias antes/después. El
informe detalla las pruebas ejecutadas y las pendientes en otros sistemas.

## Fuentes técnicas

- [PyInstaller: runtime y recursos](https://pyinstaller.org/en/stable/runtime-information.html).
- [PyInstaller: archivos spec](https://pyinstaller.org/en/stable/spec-files.html).
- [Inno Setup: instalación sin elevación](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).
- [Inno Setup: registro y desinstalación](https://jrsoftware.org/ishelp/topic_registrysection.htm).
- [Microsoft: Run por usuario](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).
- [Microsoft: cambios de sesión](https://learn.microsoft.com/en-us/windows/win32/termserv/wm-wtssession-change).
- [Microsoft: RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey).
- [Qt: bandeja del sistema](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html).

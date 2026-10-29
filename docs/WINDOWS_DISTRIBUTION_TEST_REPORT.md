# HeadMouse 0.4.0 — Informe de distribución Windows

Fecha: 28/10/2026, Argentina. Rama integrada: `tesis-v0.2`; base `500032e`.
No se hicieron commits, pushes ni merges. Las otras ramas se conservaron.

## Artefactos finales

- `dist/HeadMouse/HeadMouse.exe`: 9,501,303 bytes.
  SHA-256: `2ec52a53871ca1086a60fc368831ccc0cc81ca7325fe6b6559d9ebe7ac654b8d`.
- `dist/installer/HeadMouse-Setup-0.4.0-win64.exe`: 111,723,072 bytes.
  SHA-256: `3235149058d3d90355dfadb08c483d18adf409c0806860de4046b3807f549b4d`.
- `dist/release-manifest.json` y `dist/SHA256SUMS.txt` permiten verificar identidad.
  La prueba real del instalador corresponde exactamente al SHA-256 anterior.

El ejecutable es onedir/windowed: conservar toda la carpeta HeadMouse y _internal.
El instalador contiene esa carpeta, iconos, manual local y desinstalador. No está
firmado digitalmente; no se adquirieron certificados ni servicios.

## Equipo y herramientas realmente utilizados

Windows 10 Pro x64, versión 10.0.19045 (22H2), Python de compilación 3.12.6,
PyInstaller 6.22.3, hooks-contrib 2026.9 e Inno Setup 7.1.1 x64. El compilador de
Inno Setup se obtuvo del sitio oficial y se comprobó firma Authenticode válida
con editor Pyrsys B.V. Dependencias completas: lock de compilación versionado.

## Suite automatizada

**465 pruebas en 147.234 s, OK, salida 0; 2 omitidas.** Incluye 24 nuevas pruebas
de almacenamiento, importación, consentimiento, preferencias, estabilidad,
autoarranque, cámara ocupada, instancia única, bandeja, bloqueo/desbloqueo y
reanudación que debe esperar al desbloqueo real. Continúan las regresiones de
Nariz/Ojos, guiños, cejas, guardado, pausa, pérdida de tracking y failsafe.

Las omisiones son: mini cámara que requiere plataforma Windows nativa en lugar
de offscreen; y marca UF_HIDDEN exclusiva de macOS. No son dos fallos ocultos.
Los bloqueos adicionales de PyAutoGUI y VideoCapture registraron **cero intentos**
de acciones/captura físicas. Log: `data/logs/windows-package-full-tests.txt`.
Pruebas específicas: `data/logs/windows-package-focused-tests.txt`.

## Binario instalado y ciclo real del instalador

Se ejecutó `packaging/verify_installer.py` contra este instalador, en una carpeta
única dentro de build y con HEADMOUSE_DATA_DIR separado. La herramienta rechaza
una instalación externa o una entrada real de inicio preexistente antes de actuar.

1. Instalación nueva real en modo por usuario: salida 0, sin autoarranque ni control.
2. Se crearon accesos de programa y manual, y registro de desinstalación en HKCU.
3. HeadMouse.exe --check: Qt nativo construido y cerrado, salida 0.
4. HeadMouse.exe --verify-runtime: MediaPipe y modelo facial sobre imagen sintética,
   OpenCV, NumPy y Qt correctos, sin webcam ni acciones, salida 0.
5. HeadMouse.exe --check-resident: bandeja, sesión nativa y cierre normal, salida 0.
   En el ensayo nativo se registraron F8 global y notificaciones WTS correctamente.
6. Se creó un perfil sintético y preferencias desactivadas fuera del programa.
7. Actualización real con el mismo instalador: salida 0. Perfil, preferencias y
   último perfil conservaron sus bytes; el residente instalado volvió a iniciar.
8. Desinstalación real: salida 0. Se retiraron programa, acceso y registro de
   desinstalación; los datos de ensayo se conservaron. Run no quedó habilitado.
9. Se comprobaron los datos personales reales antes/después: sin modificaciones.

Todos los procesos de este ciclo terminaron con código 0. Se redujo PATH a
System32 y se quitaron PYTHONHOME/PYTHONPATH al ejecutar los binarios: no utilizaron
el Python del proyecto para correr. Eso **no equivale a una máquina limpia**,
pues el host de pruebas tiene Python y otras herramientas instaladas.

Evidencia: `build/installer-verification.json`, `data/logs/installer-verification-run.txt`,
`installer-first-install.txt`, `installer-update.txt` e `installer-uninstall.txt`.
Los ensayos quedan fuera del directorio de datos real del usuario.

## Inicio y datos personales

El adaptador HKCU se probó además con set/read/delete bajo una subclave aislada,
sin habilitar el inicio automático real. Los casos de consentimiento y activación
usan registro/cámara/backend simulados. La autorización depende del perfil exacto
que conserva el worker y del equipo actual; un cambio requiere reautorizar.

Se copiaron los perfiles antiguos a %LOCALAPPDATA%\HeadMouse con validación y
SHA-256. El perfil personal y last_profile originales conservaron sus bytes.
Los parámetros/calibradores y estrategias principales no se modificaron.
La copia conserva modelos anteriores y bancos independientes. Los conflictos
se guardan aparte, sin reemplazar calibraciones. Marcadores por origen detectan
nuevas modificaciones y permiten conservarlas como conflictos al importar otra vez.

**Las opciones reales del usuario siguen desactivadas**. No se autorizó ni ejecutó
control automático físico. Los perfiles personales no se incluyen en los binarios.

## Problemas de empaquetado encontrados y resueltos

- Una ICU de Poppler del PATH de herramientas provocaba error de carga de Qt.
  Se aisló PATH en el spec y se dejó que Qt utilice la API ICU del Windows objetivo.
- MediaPipe de este entorno importa matplotlib en sus utilidades de visión.
  Se incluyó con backend Agg; excluirlo hacía fallar la inferencia empaquetada.
- Se verificaron cierre del residente y liberación de archivos antes de actualizar
  o desinstalar. La reanudación no pierde el desbloqueo si el aviso de energía
  llegó mientras el escritorio seguía bloqueado. Detener manualmente revoca reintentos.

## Pruebas pendientes y límites de esta entrega

- Máquina limpia real sin Python y sin herramientas de desarrollo.
- Windows 11 y otros equipos, cámaras, pantallas y escalados.
- Inicio real de sesión y reanudación física de suspensión/bloqueo con el usuario.
  No se reinició ni bloqueó por la fuerza su equipo para esta prueba.
- Activación automática física únicamente tras consentimiento del usuario y con
  su calibración compatible. La suite no demuestra precisión ocular física.
- Prueba de tareas reales de accesibilidad y precisión, hardware físico y sesiones
  prolongadas. No se ampliaron tolerancias para aprobar calibraciones deficientes.
- Firma digital de distribución y validación de SmartScreen en otro equipo.
- El motor opcional de dictado no se incluye en esta edición básica.

La guía técnica explica cómo reconstruir y repetir los ensayos. Los archivos de
build/dist y los logs se excluyen de Git. El respaldo anterior está en
`data/logs/checkpoints/pre-windows-package-20261028T233945Z/`.

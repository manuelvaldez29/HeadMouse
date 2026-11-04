# HeadMouse 0.5.0 · Informe de distribución para Windows

Fecha del ensayo: 3 de noviembre de 2026, Argentina.

La rama integrada `tesis-v0.2` se actualizó por fast-forward de `9ea29ed`
a `9833bba`. Los diez commits incorporan mejoras de gestos, arrastre, foco
de dictado en Windows, filtrado ocular, calibración de voz y huella. El
empaquetado 0.4.0 ya estaba versionado. Los ejecutables, modelos y registros
se conservan como artefactos locales. La versión 0.5.0 se construyó con cambios
locales sobre ese commit.

Antes de actualizar se creó el respaldo `build/checkpoint-20261104T013814Z`
con 426 archivos y un manifiesto por archivo. SHA-256 del ZIP:
`7544bc324cd80f1fd4757ba5a48d96f51acbbc5422a0308b0b18c52a7f56dc96`.
Se verificó la lectura de un perfil antiguo y uno en AppData. El respaldo
contiene datos personales y debe conservarse localmente.

## Entorno y compilación

Windows 10 Pro 22H2 x64 (10.0.19045). Entorno virtual nuevo de Python
3.12.6 con las versiones del lock y `pip check` correcto. PyInstaller 6.22.3
y hooks 2026.9. Inno Setup 7.1.1 x64 con firma válida de Pyrsys B.V.

Se conservaron los artefactos de 0.4.0. El instalador y el ejecutable nuevos
informan 0.5.0 en sus metadatos. Los modelos se verificaron con los valores
publicados para revisiones fijas y con el SHA-256 de WeSpeaker. El log del
build está en `build/windows-050-build.log`. El [inventario](WINDOWS_DEPENDENCIES.md)
documenta procedencia, licencias y arquitectura. Los avisos de las ruedas
están en `_internal/licenses`. Los binarios de PyAV y OpenCV declaran
respectivamente LGPL 3 o posterior y LGPL 2.1 o posterior para sus bibliotecas
FFmpeg, según la consulta de las DLL de esta compilación.

## Pruebas automatizadas y ejecución portable

- Suite final: **539 pruebas, 2 omitidas, 0 fallos**, 244,068 segundos.
  El bloqueo de llamadas físicas registró **0 intentos** de webcam,
  micrófono, movimiento, clics o teclado. Evidencia: `build/windows-050-tests-final.log`.
- Omisiones: mini cámara en Qt offscreen y `UF_HIDDEN` exclusivo de macOS.
  La prueba de mini cámara se ejecutó por separado con Qt nativo de Windows y pasó.
- Casos de voz: selección guardada, dispositivo ausente, error al abrir,
  pérdida de tramas, cambio de foco, cancelación, interpretación de comandos,
  detección por voz, huella, persistencia y prevención de escucha al activar
  el control facial desde el inicio automático. Se usaron dobles de hardware.
  Una prueba aislada de un ONNX inválido devolvió un error de parseo.
- El portable pasó `--check`, `--verify-runtime` y `--check-resident` con PATH
  reducido a System32 y sin PYTHONHOME/PYTHONPATH. Cargó los cuatro modelos
  Whisper incluidos, MediaPipe, Silero, WeSpeaker, PortAudio y UI Automation.
  Los cuatro modelos devolvieron una transcripción de la misma frase de prueba
  generada en un WAV con SAPI en español. Medium transcribió íntegra la frase.
  Tiny, Base y Small transcribieron con diferencias. Esto comprueba la
  integración de inferencia, con una sola frase sintética.
- Se bloquearon conexiones y resolución de red de Python en la prueba de
  inferencia. Los pesos se cargaron desde `_internal`, sin cachés de AppData.
  Se registraron bandeja, F8 global y notificaciones WTS en el Windows de prueba.
  Evidencia en `build/portable-runtime-050/logs`.

## Instalación, actualización y desinstalación verificadas

Se instaló 0.5.0 en una carpeta de ensayo, arrancó con la bandeja y se
desinstaló. Se instaló luego el binario real de 0.4.0 y se actualizó a 0.5.0
en esa misma carpeta. Se verificaron el acceso de Inicio, el registro de
desinstalación, el arranque de la versión instalada y las cuatro
transcripciones con el WAV de prueba. El SHA-256 del ejecutable instalado
coincidió con el del portable. Los diez procesos del ciclo devolvieron 0.

El ensayo usó datos aislados. La actualización y la desinstalación
conservaron el perfil sintético, preferencias, último perfil, consentimiento
y un log anterior. El consentimiento del ensayo usó un registro simulado.
Los perfiles reales permanecieron intactos. El ensayo retiró el programa
de prueba, el acceso directo y su entrada de desinstalación.

La evidencia completa está en `build/installer-verification-0.5.0.json`,
`build/windows-050-install-test.log` y los logs de Inno Setup
`build/installer-9cc2d44e-*.txt`.

| Artefacto | Ruta | SHA-256 |
| --- | --- | --- |
| Instalador, 2.264.678.913 bytes | `dist/installer/HeadMouse-Setup-0.5.0-win64.exe` | `13444b520809cf965788a81d1a2c1d3068fbc83c07a8539b281873e1b27d51b4` |
| Portable, conservar toda la carpeta | `dist/windows-0.5.0/HeadMouse` | `4caa9b77cbf41bbf4fefab5c55e95c3097992ad959de062e6a6890d59efb6bd3` (HeadMouse.exe) |

Manifiesto e inventario completo: `dist/release-manifest-0.5.0.json`,
`dist/SHA256SUMS-0.5.0.txt` y `dist/windows-0.5.0/dependency-inventory.json`.

## Compatibilidad y pruebas pendientes

El instalador declara Windows x64 desde el build 19041. La verificación real
corresponde a Windows 10 19045. Quedan pendientes una máquina limpia sin
herramientas, Windows 11, micrófonos y cámaras reales, permisos y desconexión
físicos, dictado en aplicaciones reales, inicio de sesión y suspensión reales,
así como pruebas prolongadas de precisión ocular y de voz. No se midió un
mínimo universal de CPU o RAM. La edición está sin firma digital.

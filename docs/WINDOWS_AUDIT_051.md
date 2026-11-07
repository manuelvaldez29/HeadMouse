# Auditoría de la distribución local HeadMouse v0.5.1

Ensayos del 5 al 6 de noviembre de 2026 en Windows 10 x64. Rama
`tesis-v0.2`, base `4445643`. El árbol local conserva los cambios previos
de inicio accesible y teclado. La auditoría quedó sin commit ni publicación.

## Alcance y correcciones

| Área | Evidencia y alcance |
| --- | --- |
| Nariz | Regresiones de cámara simulada, captura y calibración, centrado, movimiento, sensibilidad, zona muerta, suavizado, gestos, persistencia y detención. MediaPipe nativo ejecutó inferencia con imagen de prueba. |
| Ojos | Pruebas de binocular y ambos monoculares, nueve puntos, cinco puntos independientes, recuperación de perfiles, rangos horizontal/vertical, DPI y pérdida del iris. |
| Gestos | Regresiones de guiños y cejas en Nariz y Ojos sin iris presente, calibraciones por modalidad, gestos de boca y arbitraje de acciones. Se mantuvieron algoritmos y umbrales. |
| Inicio | Regresiones de consentimiento, perfil recordado, registro real frente al JSON, cambio de ubicación, instancia única, cámara ocupada y bloqueo de sesión. Se mantuvo Ctrl+Mayús+Intro y la confirmación. |
| Teclado y dictado | Pruebas de modos, Unicode, foco, datos privados, aprendizaje voluntario, frecuencia, contexto, aislamiento y borrado por perfil. Panel real de Windows probado sobre un Bloc de notas temporal. |

- `keyboard_input.py`: el Bloc de notas clásico tenía foco editable pero
  no ofrecía TextPattern. Se agregó lectura acotada mediante mensajes del
  control Edit, con tiempo límite, sólo en campos admitidos para predicción.
  La sugerencia comprueba otra vez el cursor y la autorización antes de editar.
- `desktop/keyboard_service.py`: se descartan solicitudes de una sesión
  de control anterior y se reintenta una lectura de cursor que aún no refleja
  la tecla encolada por Windows.
- `distribution_check.py`: la prueba empaquetada verifica el diccionario
  español, SQLite y aprendizaje contextual sobre datos sintéticos.
- `packaging/HeadMouse.spec`: se excluyeron 8 archivos incidentales de caché
  y enlace C/C++ que sumaban 425.262 bytes en el portable previo. Se conservaron
  los modelos, las DLL necesarias y los textos de licencia.
- Se agregaron regresiones en `tests/test_virtual_keyboard.py`, un ensayo
  nativo repetible en `tests/smoke_keyboard_windows.py` y una prueba guiada en
  el manual de usuario.

## Verificación

**565 pruebas ejecutadas, 2 omitidas, 0 fallos.** La suite bloqueó captura,
micrófono y salida física, con cero intentos. Las omisiones corresponden a
mini cámara nativa en Qt offscreen y atributos de archivos exclusivos de
macOS. Registro: `build/audit-tests-051.log`.

En Bloc de notas clásico, el panel conservó el foco, aprendió `HeadMouse`,
completó `Hea` sin duplicarlo, escribió Ñ, números y símbolos y ejecutó Enter
y retroceso. El ensayo envió teclas sólo a la instancia temporal verificada.
Registro: `build/audit-panel-notepad-051.log`.

El portable se movió a una carpeta con espacios y pasó `--check`,
`--check-resident` y `--verify-runtime` con PATH reducido y sin PYTHONHOME
ni PYTHONPATH. Cargó MediaPipe, Qt, SQLite, el diccionario español y los cuatro
modelos de voz. Se hizo transcripción sintética sin micrófono. Evidencia:
`build/audit-runtime-051/logs` y `build/audit-051-candidate/verified.json`.

Se ejecutó Inno Setup con un AppId, una clave de registro y un contenido
mínimo de ensayo. La actualización reutilizó la ruta personalizada, conservó
el acceso, el registro de inicio y los bytes de perfil, preferencias y SQLite.
La desinstalación quitó la entrada propia y conservó un valor vecino. El ciclo
aislado verifica las directivas del instalador. El instalador completo 0.5.1
queda pendiente de probar sobre la instalación personal 0.5.0. Registro:
`build/audit-inno-isolated-051.log`.

## Rendimiento medido

- 5.000 palabras sintéticas: p95 de consultas entre 0,51 y 2,16 ms según el prefijo.
- Bloc de notas, 13 teclas: mediana de 17,9 ms desde tecla hasta texto visible,
  máximo de 669,8 ms.
- Portable con bandeja y sin captura: 1,12 s acumulados de CPU y pico muestreado
  de 96,1 MiB. Carga y transcripción sintética de los cuatro modelos en el
  mismo proceso: 123,09 s acumulados de CPU, 20,24 s de reloj y 1.765,8 MiB
  de pico muestreado. Son ensayos de arranque e inferencia, no medidas de FPS
  ni de una sesión habitual con un solo modelo.

## Entrega local

- Instalador único: `dist/installer/HeadMouse-Setup-0.5.1-win64.exe`, 2.264.654.589 bytes.
- SHA-256: `728256183c5f2b0a5d48a33f416ef0ef73297d9d9b29fa1957a7b733766dc2d0`.
- Portable completo: `dist/windows-0.5.1/HeadMouse`.
- Manifiesto: `dist/release-manifest-0.5.1.json`.
- Recuperación de ambas entregas anteriores 0.5.1: `build/recovery-051-20261106-000059`.

Quedan pendientes webcam y micrófono físicos, precisión y FPS comparativos
con Nariz/Ojos, selección por gestos reales, navegadores y WhatsApp Web,
reinicio real de sesión y actualización/desinstalación con el instalador
completo en un equipo de ensayo. Para probar en este equipo, seguir la
sección «Prueba guiada después de actualizar» del [manual](Manual.html).

**HeadMouse v0.5.1 — teclado, composición y ventanas flotantes**

Trabajo local del 7 de noviembre de 2026 sobre `tesis-v0.2`, base `bb66d88`.
La versión sigue siendo 0.5.1. El informe registra la verificación y construcción
previas a publicar estas mejoras.

| Problema | Causa comprobada | Implementación |
| --- | --- | --- |
| Escritura sin suficiente confirmación visual | El servicio publicaba sugerencias y estados, pero no composición ni resultado del envío. El panel sólo tenía botones. | Vista de composición en RAM, cursor, desplazamiento, selección azul, envío aceptado verde y fallo rojo. La ampliación de la última tecla es opcional. |
| El teclado no reaparecía sobre el mismo campo | `hidden` conservaba la identidad del campo. Un click posterior no cambiaba esa identidad ni llegaba al servicio. | Estado de ocultación independiente de apertura automática, apertura manual y cierre. Los clicks efectivamente ejecutados por HeadMouse permiten reabrir el mismo campo. Un botón flotante «Abrir teclado» ofrece otra vía accesible. |
| Cámara inmóvil en una esquina | `MiniCameraWindow.present()` colocaba la ventana abajo a la derecha sólo al mostrarla. | Esquina preferida, tamaño, evasión del cursor, histéresis y retorno con demora. Se conserva la condición existente de mini cámara durante el control nasal. |
| El teclado tapaba el campo | Se elegían arriba/abajo y el monitor del cursor sin consultar geometría UIA. | Rectángulo físico del campo convertido al monitor lógico Qt. El modo automático prueba espacio real y superposición. Un coordinador común reserva el espacio del teclado antes de colocar la cámara. |

Se reprodujo el bloqueo de reapertura ejecutando el servicio del commit base con
foco y salida simulados. Tras ocultarlo, una nueva selección del mismo campo
dejaba el teclado oculto. Ese servicio tampoco publicaba composición.

La vista contiene exclusivamente caracteres enviados por este teclado durante
la sesión. Conserva hasta 2.048 caracteres, sin truncar el texto de la aplicación
externa. No utiliza el portapapeles ni captura globalmente pulsaciones. El foco
actual se vuelve a comprobar antes de escribir. Cuando el provider lo permite,
se comparan caracteres propios alrededor del cursor, con límites de 180 por
lado. Para el control Edit clásico existe una lectura de línea acotada a 1.023
unidades UTF-16. No se importa el documento completo.

«Enviada; destino sin confirmar» indica aceptación del envío por Windows.
«Cursor comprobado» indica coincidencia del segmento propio con el cursor
consultado. Ninguna etiqueta afirma que se leyó y verificó todo el documento.
Selecciones externas, cambios de campo o aplicación, revocación de control y
ocultación limpian o invalidan la composición. Los campos sensibles no muestran
vista previa, sugerencias ni ampliación de caracteres. Una combinación no
admitida, como Ctrl+Ñ, informa fallo en lugar de confirmar un envío inexistente.
El dictado conserva su módulo y no alimenta esta composición ni el diccionario.

La cámara usa un margen de evasión de 24 píxeles lógicos y un margen de retorno
de 48, con un mínimo de 600 ms entre cambios de esquina. La posición se anima
durante 120 ms. El retorno predeterminado requiere un segundo despejado y es
configurable entre 0,3 y 5 segundos. La geometría se evalúa a 10 Hz mientras la
cámara está visible. El teclado conserva su ubicación al escribir e ignora
variaciones del campo inferiores a 24 píxeles lógicos. Se detienen los timers
al cerrar y se comprueba la validez de los widgets antes de acceder a ellos.

El modo de evasión del cursor puede desactivarse. La reserva de espacio para el
teclado sigue teniendo prioridad sobre la cámara. Un campo que ocupa toda la
pantalla puede seguir parcialmente cubierto. Se mantiene el tamaño accesible
de las teclas y se ofrece la composición visible y la posición fija como ayuda.
Las esquinas permanecen en el monitor de la ventana principal. El teclado sigue
el monitor del campo y recupera una pantalla disponible si se desconecta la anterior.

| Configuración | Persistencia |
| --- | --- |
| Apertura automática, posición Automática/Siempre arriba/Siempre abajo, tamaño, opacidad 100/90/80/70 %, vista previa, confirmación y ampliación | Configuración del perfil mediante `KeyboardConfig`. Una posición superior o inferior previamente guardada se conserva. Automática es el valor nuevo cuando no existe posición guardada. |
| Visibilidad de mini cámara, esquina preferida, tamaño, evasión y demora de retorno | Las preferencias visuales existentes por equipo mediante QSettings. Se conserva la elección previa de visibilidad. |
| Calibraciones, bancos de Nariz/Ojos y diccionario | Conservan su almacenamiento existente. Se ejecutó una comprobación aislada de guardado y recuperación de opciones del teclado sin modificar los demás datos del perfil. |

La suite final ejecutó **591 pruebas, cero fallos, dos omisiones y cero intentos
de usar cámara, micrófono o entrada física**. El log es
`build/overlays-051-tests-final.log`. Las omisiones corresponden a visibilidad
nativa de mini cámara durante minimización y atributos exclusivos de macOS.
La primera se cubrió además ejecutando por separado las ocho pruebas de mini
cámara con Qt nativo de Windows, todas correctas. También pasaron las 25 pruebas
nuevas de `test_overlay_accessibility.py` con Qt nativo y datos simulados.

Durante el desarrollo se detectaron y corrigieron la recuperación manual con
apertura automática desactivada, callbacks posteriores a la destrucción de la
cámara, recuperación después de desconectar un monitor y confirmación de una
combinación de teclas no admitida. No se modificaron expectativas de pruebas
existentes para ocultar fallos.

Se verificó el portable mediante `--check`, `--check-resident` y
`--verify-runtime`, con directorio de datos aislado y PATH limitado a Windows,
sin PYTHONHOME ni PYTHONPATH. La verificación usa imagen y audio sintéticos y
carga los cuatro modelos de voz, MediaPipe, Qt, SQLite, el diccionario, la
composición y las funciones de colocación. El instalador se compiló desde ese
portable. Se verificaron versión PE y hashes. La instalación completa sobre el
HeadMouse personal queda pendiente. La copia anterior está preservada y comprobada.

| Medición ejecutada | Resultado y alcance |
| --- | --- |
| 300 actualizaciones de presentación del teclado con texto sintético, Qt nativo | Mediana 0,1805 ms, p95 0,3032 ms, 62,5 ms de CPU acumulada. No mide el envío a una aplicación externa. |
| 5.000 pares de decisiones geométricas teclado/cámara | Media 0,0420 ms por par. |
| Movimientos del teclado durante esas 300 actualizaciones | Un posicionamiento inicial. |
| Working set muestreado del proceso de render | 69,99 MiB. No incluye seguimiento facial ni reconocimiento de voz. |
| Render nativo | Área útil real 1920×1040 con DPR 1 y geometría simulada 640×480. Teclas de al menos 32 píxeles lógicos, contenido dentro del área visible. |
| Escalado 125/150 % y varios monitores | Pruebas geométricas simuladas con orígenes negativos y escalas mixtas. Pendiente ensayo físico. |
| FPS y latencia real de entrada, con Nariz/Ojos | Pendientes de una sesión supervisada con cámara. |

Las imágenes de revisión están en `build/overlays-051-keyboard.png` y
`build/overlays-051-keyboard-640.png`. Las cifras se registraron en
`build/overlays-051-render.json`. El control de aplicaciones desde esta sesión
falló al inicializar el runtime con «failed to write kernel assets». No se
ejecutaron conversaciones reales de WhatsApp, formularios de navegador ni Word.
Tampoco se ejecutó escritura nativa en Bloc de notas en esta intervención.

Los archivos modificados son `app.py`, `config.py`, `control_engine.py`,
`keyboard_input.py`, `distribution_check.py`, `desktop/keyboard.py`,
`desktop/keyboard_service.py`, `desktop/window.py`, `desktop/widgets.py`,
`desktop/lifecycle.py` y los dos manuales Windows Markdown/HTML. Se agregaron
`desktop/overlay_layout.py`, `tests/test_overlay_accessibility.py` y este informe.
Los scripts y logs de construcción quedan bajo `build/` y en el área temporal
`D:\HeadMouse-builds\overlays-0.5.1-20261107`, fuera del historial de Git.

Para probarlo con una sesión supervisada en Windows, usar un documento temporal
o un borrador que no se envíe y seguir estos pasos.

1. Activar HeadMouse con su confirmación habitual. Abrir Bloc de notas y elegir
   el editor. Escribir Ñ, tildes, números y un emoji. Comprobar el texto en el
   editor y en la composición. Probar retroceso y una sugerencia aprendida.
2. Ocultar el teclado. Reabrir con «Abrir teclado» y, por separado, con un nuevo
   click de HeadMouse en el mismo campo. Probar otro campo, otra aplicación,
   Ctrl+Alt+K y la bandeja. F8 debe detener el control y ocultar el teclado y su botón.
3. En un borrador de WhatsApp Web, elegir Posición automática y enfocar el campo
   inferior. Verificar si UIA proporciona geometría y el teclado aparece arriba.
   Repetir con un campo superior de un formulario. Si falta geometría, probar las
   posiciones fijas. Probar opacidad y cerrar/reabrir HeadMouse para comprobar preferencias.
4. Con la mini cámara nasal visible, elegir Inferior derecha y activar evasión.
   Llevar el cursor a esa zona, comprobar la esquina alternativa y alejarlo para
   comprobar el retorno. Repetir con el teclado arriba y abajo. Probar desactivar
   la evasión y verificar también el cierre, la minimización y un cambio de monitor.

Repetir la escritura con Nariz y Ojos, incluyendo foco, precisión, gestos y FPS.
La mini cámara conserva el alcance nasal existente. Una prueba de contraseña
debe usar un campo de ensayo y comprobar ausencia de vista previa y aprendizaje.
El instalador completo debe probarse en un equipo de ensayo antes de distribuir
esta compilación. La aplicación instalada previamente no fue actualizada durante
estas verificaciones.

Las transformaciones se basan en los rectángulos físicos publicados por UIA y
en la geometría lógica por pantalla de Qt, que en Windows conserva los orígenes
y escala los tamaños. Referencias de Microsoft y Qt al final de esta explicación.
[Coordenadas de UI Automation](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-screenscaling),
[DPI y geometría de Qt](https://doc.qt.io/qtforpython-6/overviews/qtdoc-highdpi.html).

La entrega final quedó promovida y comprobada en las rutas habituales.

| Archivo o respaldo | Ubicación y verificación |
| --- | --- |
| Instalador actualizado | `dist/installer/HeadMouse-Setup-0.5.1-win64.exe`, 2.264.677.605 bytes. SHA-256 `be3ee4cb29b3d9643d21a9094790556ab90bf70f5e54b66ede0862ee019ecd1e`. |
| Portable completo | `dist/windows-0.5.1/HeadMouse`. Se verificó el arranque nativo desde esta ubicación final. El ejecutable tiene SHA-256 `9d4ab86b08d75b9273722a654e20cbddeb35579baed86ab40595785c296284b7`. Se debe conservar toda la carpeta. |
| Manifiesto de integridad | `dist/SHA256SUMS-0.5.1.txt` y `dist/release-manifest-0.5.1.json`. El manifiesto registra 3.146 archivos del portable y la suite final de 591 pruebas. |
| Entrega original recuperable | `D:\HeadMouse-builds\overlays-0.5.1-20261107\Entrega anterior`. Conserva instalador, portable, inventario y manifiestos anteriores. El instalador original mantiene SHA-256 `728256183c5f2b0a5d48a33f416ef0ef73297d9d9b29fa1957a7b733766dc2d0`. |
| Evidencia de promoción | `D:\HeadMouse-builds\overlays-0.5.1-20261107\verified.json` y `promotion.json`. Se compararon hashes completos antes de reemplazar las rutas finales. También se conserva una candidata intermedia en `Entrega anterior al ajuste final`. |

Los hashes registrados de perfiles, preferencias de inicio, último perfil y
SQLite en el directorio de datos del usuario coinciden antes y después del
trabajo. El instalador y los modelos siguen excluidos de Git. Al terminar esta
verificación, el estado era `tesis-v0.2`, HEAD `bb66d8807dcd0a13c570883507b178a603c234b3`, con 15 archivos
fuente, pruebas o documentación modificados/nuevos, sin staging ni nuevos
commits. Durante esa verificación no se hicieron pushes, merges, publicaciones
ni cambios en OneDrive.

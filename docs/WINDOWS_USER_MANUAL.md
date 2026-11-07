# HeadMouse 0.5.1 — Manual de usuario para Windows

HeadMouse es un proyecto de tesis de Ingeniería en Informática de UNSTA. Permite
controlar el puntero mediante Nariz u Ojos y realizar acciones faciales calibradas.
El seguimiento ocular continúa siendo experimental: aprobar una calibración no
garantiza precisión suficiente para cualquier tarea o persona.

## Requisitos e instalación

Windows x64, versión 10 2004 o posterior, o Windows 11; webcam RGB y buena luz.
El instalador incluye Python, Qt, MediaPipe, OpenCV, NumPy, PyAutoGUI y el modelo
facial. No hace falta instalar Python ni usar una terminal. La primera versión
se verificó en el equipo de desarrollo indicado en el informe de pruebas;
la matriz completa de equipos y Windows 10/11 requiere pruebas adicionales.

Abrir `HeadMouse-Setup-0.5.1-win64.exe` y seguir el asistente. Se instala para el
usuario actual en `%LOCALAPPDATA%\Programs\HeadMouse`. Crea acceso en Inicio,
ofrece acceso de escritorio y registra un desinstalador. Abrir al finalizar es
opcional; la instalación no habilita el control ni el inicio con Windows.
La compilación de tesis no está firmada digitalmente: Windows puede mostrar
el aviso de editor desconocido. No se contrató un certificado de firma.

## Primera ejecución

Inicio indica el siguiente paso. Crear o seleccionar un perfil personal, elegir
Nariz u Ojos y entrar en Calibración. La navegación original sigue disponible:
Inicio, Perfiles, Calibración, Diagnóstico, Configuración, Gestos y acciones,
Experimentos y Métricas.

Cada persona conserva un perfil con bancos independientes por método. Cambiar
de método no convierte ni aprueba automáticamente sus calibraciones.

## Calibrar Nariz y los gestos

En Calibración → Nariz, mantener postura cómoda y seguir los neutrales y tres
repeticiones por gesto. Elegir disponibilidad y fuente según corresponda. Realizar
la prueba de reconocimiento y guardar sólo cuando apruebe. Un gesto que no pueda
calibrarse puede marcarse no disponible: no generará su acción.

En Gestos y acciones se asignan las acciones del método seleccionado. Cambiar
tiempos de reconocimiento puede exigir validar nuevamente. Diagnóstico muestra
las señales y el comportamiento esperado sin mover el puntero del sistema.

## Calibrar Ojos

Elegir Ambos ojos, Ojo izquierdo u Ojo derecho. No cambiar cámara, distancia,
pantalla o fuente durante la captura. Calibrar movimiento y gestos por separado.
La respuesta por posición utiliza nueve fijaciones de aprendizaje y cinco de
validación independiente. Las respuestas históricas por dirección conservan su
procedimiento y modelo: no se sustituyen silenciosamente.

Si la comprobación falla, revisar el objetivo o aprendizaje señalado y usar
Guardar diagnóstico. No se habilita Guardar por una puntuación artificial.
Probar la predicción segura antes de activar. Durante guiños o pérdida de iris
se inhibe el movimiento y se espera recuperación estable. Ojos puede funcionar
sólo con movimiento si sus gestos siguen pendientes; no se habilitan clics por
tener aprobados los gestos de Nariz.

## Iniciar, pausar y detener

Iniciar HeadMouse o Activar control muestra una confirmación antes de controlar
el sistema. Las acciones requieren su calibración y autorización correspondientes.
Ambas cejas permiten pausa/reanudación si ese gesto está habilitado y validado.

Detener control, F8 y Escape detienen la salida y apagan la cámara, incluso en
vista previa. F8 global se intenta registrar en Windows; Ver estado en bandeja
informa si se consiguió. Si otra aplicación lo tiene reservado, F8 requiere foco
en HeadMouse. Siempre hay Detener en la bandeja y en la ventana. El failsafe de
PyAutoGUI permanece activo. El mouse y teclado físicos siguen disponibles.

## Inicio con Windows

Después de guardar la primera calibración válida aparece una pregunta, una vez
por equipo/usuario. Elegí Sí, iniciar automáticamente, o No, iniciar manualmente. También se puede
cambiar en Configuración → Básico → Inicio y accesibilidad:

- Iniciar HeadMouse automáticamente con Windows.
- Activar automáticamente el seguimiento.
- Recordar el último perfil elegido.
- Perfil para activación automática.
- Iniciar minimizado en la bandeja del sistema.

Guardar preferencias modifica sólo la entrada HeadMouse del inicio del usuario.
La segunda casilla requiere la primera y un perfil calibrado. Además muestra una
confirmación explícita: autoriza movimiento y únicamente las acciones validadas
de ese perfil. Se aplica al próximo inicio de sesión, no empieza a mover el
puntero al guardar estas preferencias.

Con sólo apertura automática se recupera el último perfil si habilitaste recordarlo y se prepara la cámara,
pero el control permanece desactivado. Con activación autorizada se comprueba
el perfil, cámara, contexto y al menos diez frames faciales estables durante
700 ms antes de solicitar activación. El controlador vuelve a validar la
autorización y sus requisitos. Si falla, la ventana informa el problema.

Cambiar el perfil/calibración invalida la autorización anterior: volver a guardar
las preferencias y autorizar. Nunca se controla la pantalla de bloqueo. Bloqueo
y suspensión revocan salida y cierran captura; al regresar, sólo una autorización
vigente permite repetir las comprobaciones. Detener manualmente impide reanudación
automática durante esa ejecución.

El estado de inicio se consulta en el registro de Windows. Si movés la carpeta
portable, abrí HeadMouse desde la nueva ubicación, marcá la opción y guardá.
Para iniciar el control con el teclado, poné HeadMouse en foco y presioná
Ctrl+Mayús+Intro. Elegí Sí con Tab y confirmá con Espacio.

## Bandeja y cierre

El menú de bandeja permite Abrir, Ver estado, Activar, Pausar, Detener,
Configuración y Salir completamente. Si se eligió iniciar minimizado y existe
bandeja disponible, X oculta la ventana y conserva el estado indicado en bandeja;
puede seguir el control si ya estaba autorizado. Sin esa preferencia, X termina
la aplicación. Salir y Salir completamente siempre cierran cámara y aplicación.
Si la bandeja no está disponible, la ventana permanece accesible.

## Teclado virtual y diccionario personal

Con el control activo, seleccioná un campo editable con Nariz u Ojos. HeadMouse
muestra el teclado sin quitarle el foco al campo. También podés abrirlo desde la
bandeja o con Ctrl+Alt+K si Windows permite registrar el atajo. Elegí las teclas
con el clic configurado de HeadMouse. Las pestañas ABC, ?123, símbolos, acentos
y emoji permiten escribir sin mantener teclas presionadas. F8 oculta el teclado
y detiene el control.

En Configuración → Básico → Teclado virtual y escritura podés ajustar la
apertura automática, tamaño, posición y visibilidad del micrófono. El botón
Dictar usa el módulo de voz del perfil cuando lo seleccionás. Durante la
escucha podés terminar con tu gesto de clic o cancelar con el gesto de pausa
o F8. Con la apertura automática del teclado desactivada, el dictado anterior
por clic sigue disponible cuando el teclado está oculto.

En Predicción y aprendizaje de palabras podés activar el aprendizaje local
por perfil. El teclado aprende al terminar una palabra, no cada letra. Las
tres sugerencias combinan el vocabulario personal, su uso reciente, el contexto
de hasta dos palabras y una lista base en español. Las correcciones se marcan
con ✓ y sólo se aplican al elegirlas. Administrar diccionario personal permite
eliminar una palabra o borrar todo. Desactivar el aprendizaje conserva lo
aprendido hasta que decidas borrarlo.

HeadMouse sólo aprende de sus propias teclas y en campos que identifican
el foco y permiten verificar el cursor. Los campos de contraseña, los
identificados como sensibles y los no verificables quedan en modo privado.
El diccionario guarda frecuencias y combinaciones cortas en SQLite bajo
`%LOCALAPPDATA%\HeadMouse\keyboard`, fuera de la instalación. El dictado
no alimenta el diccionario. En aplicaciones que no exponen bien el foco,
la apertura manual permite escritura directa sin aprendizaje.

La zona superior muestra únicamente texto compuesto por el teclado durante esta
sesión, con un cursor de composición y desplazamiento para textos largos. El
indicador distingue texto enviado a Windows y cursor comprobado en el destino.
La comprobación contrasta caracteres propios y no importa conversaciones. Si
cambia el campo, el cursor externo o la autorización, la composición se limpia.
Los campos sensibles no muestran vista previa. El texto de esta vista no se
guarda. Una tecla azul está seleccionada; verde indica que Windows aceptó el
envío; rojo indica que no se pudo enviar. Esto no garantiza que una aplicación
externa haya conservado el texto.

Ocultar deja disponible el botón flotante «Abrir teclado». También podés volver
a seleccionar el mismo campo con el clic de HeadMouse, cambiar de campo, usar
Ctrl+Alt+K, la bandeja o Mostrar u ocultar teclado en Configuración. Desactivar
la apertura automática conserva la apertura manual. F8 revoca el control y
oculta ambos elementos del teclado.

Posición del teclado virtual ofrece Automática, Siempre arriba y Siempre abajo.
Automática utiliza el rectángulo del campo y el monitor correspondiente para
elegir espacio libre o menor superposición. El teclado conserva su posición
mientras escribís. Cuando falta geometría se usa una ubicación inferior en el
monitor disponible; las posiciones fijas permiten ajustar el caso particular.
Un editor que ocupa toda la pantalla puede seguir parcialmente cubierto. El
tamaño de las teclas se conserva y la vista previa permite ver la composición.
La opacidad opcional de 70 a 100 % conserva los clics sobre el teclado.

En Cámara flotante podés elegir esquina, tamaño y «Evitar que la cámara tape
el cursor». La cámara se aparta a una esquina libre y regresa cuando la zona
principal lleva despejada el intervalo elegido. Un margen de retorno mayor y
una espera entre movimientos evitan oscilaciones. El teclado tiene prioridad
de espacio sobre la cámara, incluso cuando desactivás la evasión del cursor.
Estas preferencias visuales se guardan por equipo mediante la configuración
existente; las preferencias del teclado se conservan en el perfil.

## Dictado y calibración de voz

En Configuración → Básico → Dictado por voz, podés usar el micrófono
predeterminado de Windows o buscar y elegir otro. Guardá la configuración.
La aplicación incluye los cuatro modelos de Whisper y el reconocimiento de
voz. Small es la opción recomendada. Base y Tiny consumen menos recursos.

En Calibración → Voz, tocá Calibrar voz. Quedate en silencio tres segundos y
leé las cuatro frases que aparecen. Guardá el resultado en tu perfil. Se
guardan medidas de ruido, precisión y una huella que ayuda a detectar el final
de tu frase aunque haya otras voces de fondo. El audio se procesa en memoria.

Para dictar, marcá la casilla de Dictado por voz y guardá. Iniciá el control
manualmente, hacé click con HeadMouse en un campo editable y hablá al ver
«Escuchando…». También podés asignar la acción Dictar a un gesto. Un silencio
termina la frase. El gesto de click termina el dictado después de empezar a
hablar. Ambas cejas cancelan el dictado. Pausar desde la bandeja o pulsar F8
interrumpe la escucha. El arranque automático del control sólo habilita Nariz u Ojos.

Decí sólo «borrar», «borrar dos palabras», «borrar tres letras», «borrar todo»
o «deshacer» para editar. La palabra final que presiona Enter se puede configurar
en Configuración. Por defecto está vacía. La ayuda completa está en Gestos y acciones.

Si falta el micrófono, está ocupado o se desconecta, revisá la conexión y usá
Buscar micrófonos. El botón Permisos de micrófono en Windows abre la configuración
de privacidad. Activá el acceso al micrófono para aplicaciones de escritorio
si querés dictar. Podés seguir usando Nariz y Ojos con el dictado desmarcado.

## Datos, importación y actualización

Los datos están en `%LOCALAPPDATA%\HeadMouse`: profiles, último perfil, métricas,
experimentos, diagnósticos, logs y startup.json. No se guardan fotos ni vídeo.
El programa usa los modelos incluidos en la instalación y procesa el dictado
sin conexión. Las descargas gráficas quedan disponibles para reparar modelos
faltantes.

Desde el código fuente se copian los perfiles antiguos de data de forma verificable.
En una instalación nueva, usar Importar perfiles anteriores en Inicio y accesibilidad
y elegir la carpeta anterior de HeadMouse o data. Los originales no se borran.
Si ya existe un perfil diferente con el mismo identificador, se conserva el
existente y la copia en migration-conflicts; revisar antes de reemplazar manualmente.

Para actualizar, cerrar HeadMouse y ejecutar el nuevo instalador. Conserva los
datos del usuario. No copiar perfiles dentro de la carpeta de programa. Se puede
hacer una copia de seguridad de la carpeta de datos con la aplicación cerrada.

## Prueba guiada después de actualizar

1. Cerrá HeadMouse y conservá una copia de `%LOCALAPPDATA%\HeadMouse` antes de
   actualizar. Abrí el instalador v0.5.1 y mantené la carpeta de la instalación
   anterior. Los perfiles, las calibraciones y el diccionario están fuera de
   esa carpeta.
2. Abrí HeadMouse, elegí tu perfil y revisá Nariz y Ojos por separado. Confirmá
   que aparece la calibración guardada. En Diagnóstico revisá la cámara y los
   gestos. Activá el control sólo al confirmar y comprobá que F8 lo detiene.
3. Abrí un documento temporal en Bloc de notas. Con el control activo, enfocá
   el campo y probá ABC, números, símbolos, Ñ, tildes, Enter y retroceso.
   Si habilitaste el aprendizaje, escribí `HeadMouse ` y después `Hea`.
   Elegí la sugerencia y comprobá el texto. El Bloc clásico usa la lectura
   acotada de la línea cuando Windows no ofrece un patrón de cursor.
4. Probá por separado un formulario del navegador y un borrador de WhatsApp
   Web. Comprobá que el foco no cambia y que un campo de contraseña no muestra
   sugerencias ni permite dictar. El comportamiento depende de lo que el
   campo expone a Windows.
5. Si querés usar voz, activá el dictado del perfil y seleccioná Dictar en
   el teclado. Probá una frase inocua, cancelá con tu gesto de pausa y
   comprobá que el indicador de escucha se apaga.
6. Si elegís iniciar con Windows, verificá la opción en Inicio y
   accesibilidad. En el próximo inicio de sesión comprobá que se abre con el
   perfil esperado y que el control espera confirmación cuando sólo elegiste
   la apertura automática.

## Desinstalar y resolver problemas

Usar Aplicaciones instaladas de Windows o Desinstalar HeadMouse en Inicio.
Se elimina el programa y su entrada de inicio automático. Los datos personales
se conservan para reinstalar; borrarlos manualmente sólo si se desea perderlos.

- Cámara ocupada: cerrar Cámara, videollamadas y otras instancias que la usen.
- Cámara no detectada: revisar permisos de cámara y dispositivo en Configuración.
- Calibración incompatible: recalibrar en el equipo/pantalla/cámara actuales.
- Gestos rechazados: revisar Diagnóstico, fuente, neutral, señal y repeticiones;
  no copiar umbrales de otra persona o método.
- No inicia automáticamente: revisar casilla, perfil, autorización y permisos
  de inicio en Administrador de tareas de Windows. Se inicia después de ingresar,
  no antes de iniciar sesión; Windows puede demorar las aplicaciones de inicio.
- No hay icono visible: revisar los iconos ocultos de notificaciones de Windows.
- Error de arranque: conservar `%LOCALAPPDATA%\HeadMouse\logs\headmouse.log` y
  los registros fault. Compartirlos sólo tras revisar los datos personales incluidos.

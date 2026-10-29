# HeadMouse 0.4.0 — Manual de usuario para Windows

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

Abrir `HeadMouse-Setup-0.4.0-win64.exe` y seguir el asistente. Se instala para el
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
por equipo/usuario. Ahora no conserva ambas opciones apagadas. También se puede
cambiar en Configuración → Básico → Inicio con Windows:

- Iniciar HeadMouse automáticamente con Windows.
- Activar automáticamente el seguimiento.
- Perfil de inicio.
- Iniciar minimizado en la bandeja del sistema.

Guardar preferencias modifica sólo la entrada HeadMouse del inicio del usuario.
La segunda casilla requiere la primera y un perfil calibrado. Además muestra una
confirmación explícita: autoriza movimiento y únicamente las acciones validadas
de ese perfil. Se aplica al próximo inicio de sesión, no empieza a mover el
puntero al guardar estas preferencias.

Con sólo apertura automática se carga el perfil elegido y se prepara la cámara,
pero el control permanece desactivado. Con activación autorizada se comprueba
el perfil, cámara, contexto y al menos diez frames faciales estables durante
700 ms antes de solicitar activación. El controlador vuelve a validar la
autorización y sus requisitos. Si falla, la ventana informa el problema.

Cambiar el perfil/calibración invalida la autorización anterior: volver a guardar
las preferencias y autorizar. Nunca se controla la pantalla de bloqueo. Bloqueo
y suspensión revocan salida y cierran captura; al regresar, sólo una autorización
vigente permite repetir las comprobaciones. Detener manualmente impide reanudación
automática durante esa ejecución.

## Bandeja y cierre

El menú de bandeja permite Abrir, Ver estado, Activar, Pausar, Detener,
Configuración y Salir completamente. Si se eligió iniciar minimizado y existe
bandeja disponible, X oculta la ventana y conserva el estado indicado en bandeja;
puede seguir el control si ya estaba autorizado. Sin esa preferencia, X termina
la aplicación. Salir y Salir completamente siempre cierran cámara y aplicación.
Si la bandeja no está disponible, la ventana permanece accesible.

## Datos, importación y actualización

Los datos están en `%LOCALAPPDATA%\HeadMouse`: profiles, último perfil, métricas,
experimentos, diagnósticos, logs y startup.json. No se guardan fotos ni vídeo.
Los modelos faciales distribuidos son recursos de lectura; los modelos opcionales
de voz se descargan dentro del directorio de datos. El dictado requiere sus
dependencias opcionales y modelos: no se incluye un motor de voz completo en
este instalador básico.

Desde el código fuente se copian los perfiles antiguos de data de forma verificable.
En una instalación nueva, usar Importar perfiles anteriores en Inicio con Windows
y elegir la carpeta anterior de HeadMouse o data. Los originales no se borran.
Si ya existe un perfil diferente con el mismo identificador, se conserva el
existente y la copia en migration-conflicts; revisar antes de reemplazar manualmente.

Para actualizar, cerrar HeadMouse y ejecutar el nuevo instalador. Conserva los
datos del usuario. No copiar perfiles dentro de la carpeta de programa. Se puede
hacer una copia de seguridad de la carpeta de datos con la aplicación cerrada.

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

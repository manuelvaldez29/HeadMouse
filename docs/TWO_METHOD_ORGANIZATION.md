# Organización Nariz / Ojos — 27/10/2026

## Alcance e interfaz

La navegación lateral y las páginas originales permanecen. Inicio y Configuración
presentan únicamente **Nariz** y **Ojos**. No hay selector público relativo/absoluto
ni un asistente global. Inicio conserva perfil, bienvenida, webcam, estado y sus
botones originales de iniciar/detener. Cuando falta movimiento ocular, su acción
principal lleva a **Calibración → Ojos** sin mostrar controles técnicos en Inicio.

Calibración tiene exactamente dos pestañas:

- **Nariz:** la página original de gestos, sus medidores, validación y guardado.
- **Ojos:** fuente ocular, movimiento, prueba segura, diagnóstico vertical,
  preparación y acceso a calibración de gestos. Los gestos utilizan los mismos
  widgets y procedimiento originales, con el banco ocular activo. El panel puede
  volver a movimiento sin crear una página por algoritmo.

La vista de movimiento mantiene la cámara al lado de los controles; éstos pueden
desplazarse en pantallas pequeñas sin desplazar la cámara. En capturas de pantalla
completa, el mismo preview aparece en una esquina opuesta al objetivo. Su posición
se actualiza al cambiar de objetivo, sin esperar al próximo frame. El caption
muestra fuente, iris I/D, disponibilidad, encuadre, estabilidad medida y muestras.
Si no hay suficientes muestras para medir estabilidad, dice «midiendo».

Los marcadores oculares se muestran durante la calibración aunque estén ocultos
en la vista normal. Es una preferencia local de presentación: no modifica lo
guardado para Inicio, Nariz ni Diagnóstico. No se abrió un capturador adicional.

## Un perfil personal, dos bancos públicos

El `user_id`, nombre y archivo del perfil personal permanecen. Seleccionar un
método no crea otra persona ni otro archivo de perfil.

| Datos | Conservación / presentación nueva |
|---|---|
| Parámetros y acciones nasales | `settings.methods.nose`, sin reinterpretarlos |
| Parámetros y acciones de Ojos | `settings.methods.eyes` |
| Gestos/validación de Ojos | `gesture_modes.eyes`, con origen de medición propio |
| Parámetros experimentales anteriores | `settings.methods.eye` y `eye_absolute` permanecen |
| Gestos experimentales anteriores | Bancos `eye` y `eye_absolute` permanecen |
| Movimiento por dirección | `tracking_calibrations[both/left/right]`, sin convertir |
| Movimiento por posición | `absolute_calibrations[both/left/right]`, sin convertir |

El banco público Ojos guarda los parámetros de ambas implementaciones internas
en secciones distintas (`eye` y `absolute`). Esto conserva sensibilidad, filtros,
acciones y datos experimentales sin mezclar modelos matemáticos. El selector
público no cambia la identidad de un modelo ni convierte sus coeficientes.

Los cambios de tiempos de gestos invalidan sólo la aprobación del banco editado.
Las acciones oculares se configuran en la página original **Gestos y acciones**.
Cambiar una acción de Ojos no modifica su equivalente nasal.

## Migración explícita y compatible

La lectura de un perfil antiguo no lo reescribe. La migración ocurre al elegir
Ojos mediante la interfaz o al entrar en su calibración. `migrate_public_eyes`
crea copias independientes de los parámetros y gestos del banco interno elegido;
no fusiona los bancos anteriores. La operación se guarda mediante el mecanismo
atómico y la lectura posterior existentes.

Campos de presentación:

- `ui.unified_eyes`: activa el banco público Ojos.
- `ui.ocular_engine`: recuerda la implementación interna elegida.
- `ui.tracking_method`: conserva sus identificadores internos históricos para
  las estrategias, CLI experimental, protocolos y modelos.
- `ocular_migration`: versión, banco de gestos de origen y estado de aprobación.

Si el perfil estaba utilizando `eye`, continúa con esa respuesta por dirección.
Si utilizaba `eye_absolute`, conserva su respuesta por posición. Al pasar a Nariz
y volver a Ojos se recupera esa elección, los parámetros y las acciones de Ojos.

En una persona nueva, o un perfil antiguo sin una respuesta ocular recordada,
Ojos prepara el aprendizaje de posición en pantalla: nueve fijaciones y cinco
comprobaciones independientes. Ésa es la dirección de convergencia funcional,
pero **no implica precisión física ya aprobada**.

La presentación indica «respuesta guardada: posición en pantalla» o «dirección
conservada del perfil anterior». Un perfil heredado puede preparar una respuesta
por zonas desde una acción avanzada con confirmación. Se conservan sus modelos
anteriores. No hay cambio automático de comportamiento al perder el iris o al
fallar la validación: se detiene/deniega el movimiento correspondiente.

Una aprobación nasal nunca se convierte en una aprobación ocular. Sólo se
conserva aprobación al migrar un banco ocular con origen explícitamente medido.
En los demás casos, se retienen las mediciones existentes pero la aprobación de
Ojos queda pendiente. Los gestos nuevos se guardan únicamente en el banco Ojos;
no crean copias aprobadas en los algoritmos heredados.

Los modelos continúan separados por fuente. Ninguna migración convierte un
modelo izquierdo en binocular, ni reutiliza un ajuste relativo como absoluto.
Los alias singulares históricos siguen siendo binoculares.

## Vista en vivo y concurrencia

`VisionEngine` continúa siendo el único propietario de webcam e inferencia.
`ControllerWorker` publica en el mailbox existente de capacidad uno y emite una
notificación Qt sin transportar imágenes encoladas. `DesktopBridge` la entrega
al hilo de GUI; `MainWindow.update_live_preview` consume el último snapshot.
Las notificaciones repetidas del mismo snapshot se descartan.

Así no se acumulan frames si la interfaz tarda en dibujar. La conversión QImage
se realiza en GUI y no se ejecuta MediaPipe allí. El preview de ejercicios, el de
gestos y el de pantalla completa reciben el flujo ya abierto. Se verificó con
un factory simulado que abrir una captura ocular crea un único motor.
Los scripts CLI conservados consultan el mismo banco seleccionado. La CLI ocular
requiere aprobación de gestos propia antes de arrancar; para movimiento sin gestos
se utiliza la GUI con confirmación y parada disponibles. Nariz conserva su ruta.

Se mantienen las transformaciones lógico/físico del monitor principal y sus
verificaciones con otros monitores conectados. Las pruebas comprueban que la
imagen y su caption no cubren los objetivos de la calibración. No se modifica
la ubicación normalizada de los puntos para acomodar la webcam.

## Vertical: datos, asimetría y ruido

Se conserva el diagnóstico real anterior, sin reescribirlo:
`data/logs/vertical-physical-20261027T035048834692Z.json`.

Para la referencia binocular de comisuras, esa medición mostró:

| Fijación | Excursión respecto del centro | Dispersión p10–p90 |
|---|---:|---:|
| Centro | 0 | 0,003223 |
| Arriba | −0,026290 | 0,001685 |
| Abajo | +0,014815 | 0,006419 |

El diagnóstico ahora compara amplitud y dispersión por ojo, referencia y
dirección. Hacia abajo, amplitud / máximo ruido de centro y objetivo es ≈2,31.
No supera una separación conservadora de tres dispersiones (≈0,01926).
Esta comparación descriptiva no es una probabilidad estadística ni una nueva
aprobación de calibración.

No se justificó bajar el mínimo 0,02 con esos datos. Se mantiene el rechazo de
signos incorrectos, amplitud insuficiente, parpadeos, iris ausente, cabeza móvil
y frames viejos. No se usó `abs()` para aprobar un rango negativo.

Los rangos izquierdo/derecho/arriba/abajo ya son independientes y medidos; no se
fuerza simetría. La referencia por comisuras continúa siendo una opción
experimental de la respuesta heredada, con recaptura obligatoria. Los modelos
de posición existentes conservan su referencia: cambiarlos requeriría un modelo
y evaluación explícitos, no reinterpretar coeficientes ya persistidos.

Configuración avanzada incorpora zonas muertas horizontal y vertical opcionales.
Con `None`, cada eje conserva exactamente la zona común histórica. Cambiar la
vertical no cambia X. No se alteraron sus valores predeterminados ni se ajustaron
automáticamente a esta medición. Sensibilidad, suavizado, estabilización, fuente,
referencia y parámetros de posición siguen disponibles y validados; los que no
usa la respuesta activa se conservan y aparecen deshabilitados.

La calibración neutral y multipunto informa estabilidad a partir de muestras
reales de posición de cabeza. El diagnóstico muestra señal cruda por ojo,
combinación, señal normalizada/filtrada, delta calculado y salida entera simulada,
incluyendo acumulación fraccional. La comparación no mueve el mouse real.
La simulación utiliza la respuesta actualmente seleccionada; si falta ese modelo,
informa el bloqueo y no utiliza el otro. Los informes identifican implementación,
perfil, parámetros, contexto guardado, duración de captura, edad del frame y
tiempo de procesamiento, para no mezclar evaluaciones de algoritmos distintos.

## Activación y guardado

Una calibración de movimiento compatible permite probar sólo movimiento sin
gestos. Los detectores y el motor bloquean acciones pendientes en dos capas;
también queda deshabilitado el dictado dependiente de clics. Autorizar control
requiere la confirmación original. F8/Escape son de HeadMouse en foco; el
failsafe existente permanece activo.

Los botones de guardado conservan su validación previa, reemplazo atómico y
relectura. Una sesión rechazada no sustituye un modelo válido. Calibración y
diagnóstico seguro no pueden activar el backend del sistema. Los guiños y otros
gestos interfiriendo con la mirada suspenden el movimiento y exigen recuperación
estable antes de reanudar.

## Pruebas y revisión visual

Se mantuvo la suite previa, actualizando únicamente las expectativas gráficas
que ahora deben mostrar dos métodos públicos. Nuevas pruebas:

- `test_two_method_profiles.py`: un perfil personal, migración idempotente,
  separación de parámetros/acciones, retorno exacto a Nariz, seis modelos
  conservados, persistencia, aprobación ocular y transición explícita.
- `test_two_method_ui.py`: selectores y pestañas, widgets de gestos originales,
  frames por señal Qt en GUI, un solo motor y preview fuera de los objetivos.
- `test_vertical_diagnostic.py`: zonas por eje, señal pequeña frente a ruido y
  las regresiones verticales, monoculares y de protección anteriores.

Capturas reproducibles con un rostro **dibujado**, no una webcam:

- `screenshots/two-methods-home-synthetic.png`
- `screenshots/two-methods-calibration-synthetic.png`
- `screenshots/two-methods-live-preview-synthetic.png`

Se generan con `python tests/render_two_methods.py`. No acreditan exactitud ocular
física. Los resultados de la suite y prueba nativa quedan en
`data/logs/two-methods-full-tests.txt` y `data/logs/two-methods-native-smoke.txt`.

Resultado: **364 pruebas aprobadas**, 49,708 s, **código de salida 0**.
Prueba nativa con MediaPipe real y captura sintética: **código 0**.
La revisión final de diagnóstico, captura y preview también pasó por separado
(16 pruebas verticales, 24 de modelos/captura y 4 gráficas), sin acciones del SO.

## Pilotaje físico pendiente

1. Abrir el perfil personal, seleccionar Ojos y entrar en Calibración → Ojos.
   Comprobar que conserva la respuesta anterior y fuente, sin duplicar el perfil.
2. Abrir Diagnóstico vertical, mantener cabeza y cámara fijas, y seguir
   centro/arriba/abajo. Confirmar que la webcam y los marcadores I/D permanecen
   visibles sin tapar el objetivo. Registrar amplitud, dispersión y rechazos.
3. Pulsar Calibrar movimiento. Completar las capturas que corresponden a la
   respuesta guardada y su comprobación. Repetir puntos deficientes; no aprobar
   una amplitud insuficiente por bajar la zona muerta.
4. Guardar, comprobar la confirmación y Probar movimiento de forma segura.
5. Si está preparado, autorizar sólo movimiento y detener con el botón/F8.
   Verificar cuatro direcciones, pérdida del iris, límites y pausa.
6. Calibrar gestos, validarlos y guardarlos dentro de Ojos; configurar sus
   acciones en la página original. Comprobar guiños y recuperación sin saltos.
7. Volver a Nariz y verificar sus ajustes originales. Reiniciar y repetir con
   fuente izquierda/derecha, conservando resultados y fallos para la tesis.

No se ejecutó un nuevo pilotaje físico en este cambio. No se declara resuelto el
posicionamiento absoluto ni la precisión vertical con la webcam.

## Preservación

Respaldo completo previo de fuentes, archivos nuevos, modelos, datos y perfiles:
`data/logs/checkpoints/pre-two-methods-20261027T043720139179Z/workspace.zip`,
414 archivos y manifiesto SHA-256. Se excluyeron `.git`, `.venv`, cachés y la
carpeta de checkpoints para evitar recursión; los anteriores siguen disponibles.
Se comprobaron hashes del perfil personal y último perfil: no cambiaron durante
la implementación. `NoseTrackingStrategy` también coincide con el estado previo.
La migración real del perfil se realiza cuando el usuario elige Ojos.

Sin cambio de rama, commits, pushes, merges ni instalador.

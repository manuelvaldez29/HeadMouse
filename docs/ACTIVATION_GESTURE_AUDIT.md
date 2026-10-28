# Activación y gestos de Ojos en Windows

Auditoría del 27/10/2026 sobre `b32aa47`, rama `experiment/eye-tracking`.
Se compararon `b663fcc` (antes de la integración), `9c605b5` y `b32aa47`.
Esta intervención no hace commits, pushes, cambios de rama ni pruebas con entrada
real del sistema. La precisión ocular física no queda aprobada por estos tests.

## Error demostrado de activación

El controlador comprobaba correctamente el contexto antes de construir el backend.
Al refrescar la ventana, una segunda comprobación reconstruía el contexto con
pantalla y cámara, pero omitía `capture_host`, añadido en `b32aa47`. `same_context`
comparaba la huella guardada con `None`: daba incompatible en el mismo equipo y
la GUI ordenaba detener el control recién autorizado.

En el log local se observan activaciones a las 22:33:20.622 y 22:33:32.677,
seguidas de detenciones a las 22:33:20.778 y 22:33:32.793. El patrón se repite.
La regresión Qt reproduce el recorrido completo: perfil, modelo, cámara simulada,
diálogo Sí, backend simulado y múltiples refrescos. Antes de la corrección la
comparación sin huella rechaza ese contexto. La prueba corregida exige que siga
activo y que un cambio real de DPI todavía lo detenga.

Corrección: la GUI compara la huella del equipo actual y las dimensiones reales
de captura publicadas por el controlador. No copia la huella del modelo para
aprobar la comparación. La fuente seleccionada sigue determinando el modelo.
La detención por incompatibilidad conserva su motivo en el mensaje del controlador.

La frase «Falta confirmación explícita de activación» es esperable mientras no hay
control autorizado; no significaba que el diálogo estuviera roto. En este caso,
volvía a aparecer porque el control se detenía inmediatamente. El diálogo con
respuesta predeterminada No, F8, Detener y las comprobaciones de contexto permanecen.

Inicio distingue modelo pendiente/incompatible, requisitos pendientes, listo para
confirmar, activo y pausado. El estado de movimiento se calcula después de
comprobar resolución y equipo, corrigiendo además un indicador preparado obsoleto.
Los gestos pendientes de Ojos son una advertencia: permiten sólo movimiento,
con detectores de acciones y salida de clics/teclado bloqueados. En Nariz siguen
siendo obligatorias la calibración y validación originales.

## Respuestas a la auditoría de gestos

1. **Cálculo de guiños:** no cambió la señal facial ni su detector de cierre.
   `LEFT_WINK` y `RIGHT_WINK` siguen usando `eye_left_ratio` y `eye_right_ratio`,
   respectivamente, con dirección decreciente, histéresis y los tiempos personales.
   Se agregaron antes protecciones del movimiento ocular durante cierre/recuperación;
   estas no son un requisito del calibrador facial.
2. **Calibración de cejas:** el calibrador, sus adaptadores, el arbitraje y la
   validación facial son compartidos. Los blobs Git de `calibration_session.py`,
   `calibration_validation.py`, `adaptive_calibration.py`, `gesture_signals.py`,
   `gesture_arbitration.py` y `calibration_logic.py` son idénticos entre `b663fcc`
   y `b32aa47`. En esta intervención sólo se añade diagnóstico a la sesión;
   no se modifica su captura, ajuste, neutral, rechazo ni validación.
3. **Umbrales:** no se reducen ni se cambian los defaults faciales. Los valores
   personales sí pueden diferir porque cada método tiene mediciones independientes.
   La lectura local encontró la misma configuración de captura en Nariz/Ojos:
   tres repeticiones, ventana activa 1 s, neutral 3 s, transición 2 s, mínimo
   8 muestras por ventana, separación .002 y multiplicador de ruido 1.5.
4. **Nuevas validaciones:** no se agregó exigencia de fijación ocular o iris al
   calibrador de guiños/cejas. El movimiento de Ojos sí exige fuente/iris/contexto
   compatibles y recuperación estable; las acciones oculares exigen medición y
   validación explícitas del banco seleccionado. Aprobar Nariz no autoriza Ojos.
5. **Guardado:** sí cambió durante la integración: `gesture_modes.nose` y
   `gesture_modes.eyes` conservan parámetros/resultados independientes dentro del
   mismo perfil. Siguen presentes los bancos históricos `eye`/`eye_absolute` y los
   modelos de movimiento por fuente. Ahora se verifica además la relectura del
   banco guardado y se informa el método y error exactos si no puede confirmarse.
6. **Exclusivo de Ojos:** fuente seleccionada, modelo de movimiento, compatibilidad
   de equipo/cámara/pantalla, iris fresco y supresión del movimiento durante
   expresiones. Sin gestos autorizados hay sólo movimiento. El validador facial
   construye el detector compartido sin estrategia ocular ni backend de acciones.
7. **Por qué la diferencia observada:** no se encontró una puerta exclusiva de
   Ojos que rechace estos gestos por ausencia de iris. Hay bancos y mediciones
   diferentes. La evidencia local muestra rechazos estadísticos reales de guiños
   y cejas individuales previamente deshabilitadas también en Nariz. No permite
   atribuir una causa física exacta ni declarar que las cejas individuales estaban
   funcionando en la calibración nasal guardada. Se necesita comparación controlada.

## Evidencia local del intento físico existente

Se leyó, sin modificar, `data/calibration/9766c2464ad246f3a49305597c584ae4.jsonl`.
El archivo anterior no etiqueta modalidad: su asociación con Ojos se infiere de
los horarios y del banco ocular guardado, no de una etiqueta inexistente.

- Guiño izquierdo: inicialmente BUENA, posteriormente rechazado al recomprobar
  el reposo acumulado: «el reposo de la sesión se superpone con el gesto».
- Guiño derecho: varios intentos débiles, por superposición o neutral inestable.
  En uno, el ratio activo p10 era .00359 y p90 .08148, frente a neutral mediano
  .08807. Llegar a un cierre profundo en algunos frames no garantiza sostener una
  expresión separable durante todas las repeticiones. Esto es compatible con una
  captura mezclada/transitoria, pero no prueba por sí solo su causa.
- Ambas cejas: BUENA, calidad .9667. Boca: BUENA, calidad 1.
- El banco nasal conserva guiños habilitados y cejas individuales deshabilitadas.
  El último banco público Ojos conserva boca/ambas cejas aprobadas, con guiños y
  cejas individuales deshabilitados. No se habilitó ninguno por modificación JSON.

El ajuste original ya revisaba el reposo acumulado de toda la sesión, también en
Nariz. No se eliminó esa protección para lograr guardar intentos rechazados.

## Diagnóstico agregado

Los JSONL de `data/calibration/` incluyen ahora modalidad pública, banco y fuente
de parámetros. Los registros `gesture_calibration` siguen conservando los ajustes
y sus motivos; los nuevos `gesture_diagnostic` muestran:

- gesto solicitado, actividad detectada y gestos reconocidos por el validador;
- canal, valor, referencia neutral, umbral de activación/liberación y fuente;
- frames faciales aceptados/rechazados acumulados y motivos de rechazo;
- fase, estado y resultado del intento.

Se registra un agregado al cambiar de paso/motivo y como máximo una actualización
periódica por segundo entre cambios. Los contadores de validación indican frames
faciales utilizables, no gestos aprobados: éstos constan en `recognized`/resultado.
Las transiciones y los motivos de guardado también quedan en el log de aplicación.
No se guardan fotos, vídeo, landmarks ni coordenadas personales de iris.

## Prueba controlada preparada

La regresión `tests/test_activation_gesture_audit.py` reproduce exactamente la
misma secuencia de seis gestos y sus neutrales en ambos métodos, sin iris. Exige
los mismos parámetros aprendidos, las seis validaciones y ausencia de diferencias
de estado. También prueba ambos guiños con iris ausente en ejecución ocular relativa
y por posición: el evento facial sigue detectándose, el cursor se inhibe y sólo
regresa tras el plazo y los tres frames estables existentes.

Para comparar físicamente, usar **una sola instancia de HeadMouse**, sin activar
control, las demás aplicaciones de webcam cerradas y cámara/luz/postura fijas:

1. Reiniciar la app para cargar estos cambios cuando no haya una captura sin guardar.
2. En Nariz, iniciar la calibración facial con los gestos que se deseen comparar.
   Medir neutral y tres repeticiones cómodas de cada guiño/ceja. Mantener la expresión
   durante la ventana activa; soltar durante el neutral. No forzar ni copiar umbrales.
3. Conservar el intento/log. Para una comparación sin escribir el perfil personal,
   no pulsar Guardar; seleccionar Ojos y repetir con la misma disponibilidad/fuente.
   Cambiar método detiene la cámara anterior antes de abrir otra.
4. Comparar `gesture_bank`, `requested_gesture`, fuente, valores, umbrales, dispersión,
   rechazos y resultado. Si falla un gesto, repetir sólo ese gesto y conservar los
   registros. Un gesto deshabilitado no demuestra una validación exitosa.
5. Guardar Ojos únicamente si su prueba facial aprueba. Comprobar el mensaje de
   relectura y, tras reiniciar, los gestos habilitados del banco Ojos. El guardado
   ocular no sustituye el banco nasal ni los modelos de movimiento.
6. Con movimiento ocular válido, Inicio → Iniciar HeadMouse → confirmar Sí.
   Este último paso puede accionar el cursor y requiere autorización del usuario;
   no se ejecutó durante esta intervención. Probar F8/Detener y pérdida de tracking.

No se cerró ni reinició por la fuerza la ventana del usuario: podría contener
mediciones aún no guardadas. Una instancia abierta conserva el código anterior.

## Verificación

Suite final: **403 tests en 69.498 s, OK, una prueba omitida** (`UF_HIDDEN`
exclusivo de macOS), código de salida **0**. El bloqueo adicional de PyAutoGUI
y `VideoCapture` registró **cero intentos de entrada/captura físicas**. Arranque
Qt nativo de Windows con perfil personal y control desactivado: salida **0**.
Los nueve casos nuevos cubren activación sostenida y rechazo del diálogo,
detención por cambio real de contexto, Nariz, ausencia de iris, paridad de
guiños/cejas, sólo movimiento sin clics, telemetría, guardado fallido y relectura.

Resultados finales y código de salida: ver los logs ignorados por Git en
`data/logs/activation-gesture-full-tests.txt`, `activation-gesture-focused.txt`
y `activation-gesture-native-app.txt`.

Respaldo previo de fuentes y perfiles con SHA-256:
`data/logs/checkpoints/pre-activation-gesture-audit-20261028T014239Z/`.
El sufijo del respaldo está en UTC; la auditoría corresponde al 27/10 en Argentina.

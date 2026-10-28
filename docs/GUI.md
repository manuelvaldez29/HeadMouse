# HeadMouse v0.3.1 — aplicación de escritorio

Después de instalar las dependencias en `.venv`, abrí `HeadMouse.vbs` con doble clic en Windows. El lanzador utiliza el entorno del repositorio y no requiere escribir comandos. Si Windows Script Host está deshabilitado, ejecutá `.venv\Scripts\python.exe app.py` desde la carpeta del repositorio. Con el entorno activado, el comando equivalente es `python app.py`.

La instalación inicial todavía requiere preparar Python y las dependencias; esta versión no incluye un instalador ejecutable independiente.

## Primer uso

1. En **Inicio**, el botón principal indica el próximo paso: **Crear mi perfil**, **Calibrar mis gestos**, **Validar mi calibración** o **Iniciar HeadMouse**. El último perfil usado queda elegido al abrir la aplicación (`data/last_profile.json`); si hay un solo perfil, se elige solo. El selector de Inicio permite cambiarlo. Un perfil nuevo aparece como «Sin calibrar».
2. En **Configuración → Básico**, elegí el método (Nariz u Ojos) y la cámara, y guardá. Si falta un modelo, **Configuración → Modelos** lo descarga con confirmación previa.
3. En **Calibración**, tocá **Comenzar calibración**. A la izquierda, una lista muestra cada gesto en orden de captura: ✓ listo, ● en curso (intento N de 3), ✗ hay que repetir, ○ pendiente, — no disponible. La cámara y el medidor muestran la señal actual, el neutral, la activación, la liberación y el extremo cómodo. Un único botón grande indica el próximo paso; mientras mide aparece como estado ("Midiendo…") y al lado queda **Cancelar**.
4. Si un gesto falla, el botón pasa a **Repetir este gesto** y al lado aparece **No puedo hacer este gesto**, que lo marca no disponible sin perder los demás. Al terminar de medir, **la prueba de gestos arranca sola**: la lista pasa a "Prueba de gestos" y marca cada uno como detectado. Si la prueba falla, el botón ofrece **Reintentar la prueba**. Al aprobarla aparece **Guardar perfil**, y después **Ir a Inicio**. **Más opciones** (plegado, muestra la señal de cejas elegida) agrupa los gestos disponibles, la señal de cejas, volver a medir un gesto específico, recalibrar desde cero y cancelar.
5. En **Diagnóstico** (menú izquierdo), elegí **Iniciar diagnóstico**. El panel dice si la cámara te ve, hacia dónde se movería el cursor y, con una barra por gesto, cuánto falta para que se active (la marca amarilla es el umbral). El último gesto muestra la acción que habría hecho, sin ejecutarla. Los números técnicos están en **Mostrar detalles técnicos**.
6. Cuando estés listo, tocá **Iniciar HeadMouse** en Inicio: un solo click enciende la cámara y activa el control **en pausa** (levantá ambas cejas para mover el cursor). El mismo botón pasa a **Detener HeadMouse**. **Activar control**, en la barra superior, conserva su diálogo de confirmación.

## Seguridad y estados

Al abrir la aplicación, la cámara y el control están desactivados. Abrir la cámara, calibrar, diagnosticar o usar simulación no habilita acciones del sistema. El control requiere un perfil validado y una acción explícita: el botón **Iniciar HeadMouse**, o **Activar control** con su confirmación. En ambos casos arranca en pausa.

**Detener control** interrumpe la salida. **F8** y **Escape** también la detienen cuando la aplicación recibe el teclado: son atajos locales a la aplicación, no atajos globales de Windows. Se conserva el failsafe de PyAutoGUI al llevar el puntero a una esquina. Una llamada al sistema que ya esté en ejecución puede terminar antes de que se aplique la detención.

La línea de estado superior es un solo renglón: un indicador (● DESACTIVADO, ● EN PAUSA o ● ACTIVO), un mensaje y los botones Activar control y Detener. El mensaje sigue este orden: un error, en rojo y fijo; un aviso reciente (por ejemplo, «Centro ajustado»), durante 8 s; y si no hay ninguno, el próximo paso en lenguaje simple, tomado de la primera condición que bloquea de verdad (`status_message` y `CONDITION_STEPS` en `desktop/window.py`). No cuentan como bloqueo la cámara apagada, porque se enciende al iniciar, ni «falta confirmación». La lista completa de condiciones se ve al pasar el mouse por Activar control. La pausa por gesto utiliza el mapeo configurado; por defecto corresponde a ambas cejas. La pérdida de un rostro válido impide continuar el movimiento y se conserva el timeout de seguridad del motor.

## Pantallas

| Pantalla | Uso |
|---|---|
| Inicio | Saludo, selector de perfil, botón principal con el próximo paso (crear, calibrar, validar, iniciar o detener), estado (listo, en pausa, activo) con su indicación, rostro detectado y vista de cámara. Los datos técnicos (FPS, procesamiento, MediaPipe) están en Diagnóstico; la navegación, solo en el menú izquierdo. |
| Perfiles | Una tarjeta por perfil, con el que está en uso primero y resaltado: nombre, estado de Nariz y de Ojos, y fecha de la última calibración en hora local. El perfil en uso ofrece Calibrar, Renombrar y Eliminar (con confirmación); los demás, **Usar este perfil**. Un perfil que no se puede leer muestra el motivo y no ofrece acciones. **Nuevo perfil** está arriba a la derecha. Renombrar conserva el identificador interno y los resultados históricos. |
| Calibración | Lista de gestos con su estado, botón con el próximo paso (comenzar, repetir, reintentar, guardar), prueba automática al terminar de medir y opciones avanzadas plegadas. La página se desplaza al abrir las opciones. |
| Diagnóstico | Cámara a la izquierda y panel en lenguaje simple a la derecha: si te ve la cara (y los FPS), hacia dónde iría el cursor o si está quieto, una barra por gesto desde el reposo calibrado hasta el umbral de activación vigente (incluido el recentrado; ambas cejas avanzan lo que avance la más atrasada), el último gesto con su acción sin ejecutar y la estabilidad medida en 10 s. **Mostrar detalles técnicos** despliega coordenadas, umbrales, cámara, ojos y la calibración avanzada por gesto. El diagnóstico vertical aparece sólo con el método Ojos. |
| Configuración | Cinco pestañas. **Básico**: método, cámara, velocidad del cursor, zona quieta, suavizado, dictado y vista de cámara. **Gestos y scroll**: tiempos de sostener y esperar, scroll y pausa sin cara. **Ojos** (experimental; avisa cuando el método es Nariz): fuente ocular, joystick, posición en pantalla. **Cámara**: backend, resolución, FPS, tiempos y preset USB. **Modelos**: descarga de los modelos facial y de voz. Guardar y Restaurar quedan siempre visibles. |
| Gestos y acciones | Seleccionar la acción de cada gesto y guardar en el perfil. |
| Experimentos | Adquisición de objetivos con cursor interno, práctica con teclado o control real explícitamente activado. |
| Métricas | Sesiones con control activo de este perfil o de todos: cuatro indicadores (sesiones, tiempo de uso, clicks y pausas por minuto, ponderados por duración), acciones por minuto por sesión en tres franjas con la misma escala (clicks, scrolls, pausas), pérdidas de rostro por minuto y tabla con la sesión más reciente arriba. Al pasar el mouse por un gráfico se ven los valores de esa sesión. |

Los cambios se guardan en el mismo perfil JSON utilizado por los motores. La interfaz no exige editar JSON. Cambiar los tiempos de reconocimiento requiere validar nuevamente el perfil. Restaurar valores predeterminados pide confirmación.

Los overlays y los landmarks se pueden alternar por separado. Las imágenes de preview permanecen en memoria; no se guardan fotografías ni video.

Los ajustes terminados guardan estadísticas locales en `data/calibration/`.
El [detalle de v0.3.1](CALIBRATION_V031.md) explica calidad, compatibilidad y
límites. Revalidar un perfil anterior no recupera sus muestras: para volver a
medirlo hay que iniciar una calibración nueva.

## Experimentos y resultados

En **Experimentos**, seleccioná el modo e iniciá una serie. En simulación con teclado usá flechas para mover el cursor interno y Espacio o Enter para seleccionar. En simulación con HeadMouse usá el movimiento facial y un gesto asociado a clic izquierdo o doble clic. Los resultados se guardan automáticamente en `data/experiments/` como JSONL. Las sesiones de métricas se guardan en `data/metrics/`.

El experimento real requiere activar el control previamente. Su superficie registra clics recibidos dentro del área experimental; no registra clics sobre otras aplicaciones ni fuera de esa superficie. Al finalizar o cancelar, detené el control con el botón persistente.

## Verificación y límites

Las pruebas automatizadas utilizan cámara y backend de mouse simulados. Las capturas de revisión de interfaz no contienen imágenes faciales. La comprobación `python app.py --check` abre y cierra la ventana sin iniciar cámara ni control.

Quedan para validación manual con el equipo del usuario: webcam y permisos, lateralidad de gestos, iluminación, funcionamiento a diferentes escalas de Windows, acciones reales, failsafe y accesibilidad con personas usuarias. Las pruebas simuladas no demuestran precisión clínica ni rendimiento con una webcam real.

Los scripts `main.py`, `calibrate.py` y `debug_cursor.py` siguen disponibles para uso técnico.

# HeadMouse v0.3.1 — aplicación de escritorio

Después de instalar las dependencias en `.venv`, abrí `HeadMouse.vbs` con doble clic en Windows. El lanzador utiliza el entorno del repositorio y no requiere escribir comandos. Si Windows Script Host está deshabilitado, ejecutá `.venv\Scripts\python.exe app.py` desde la carpeta del repositorio. Con el entorno activado, el comando equivalente es `python app.py`.

La instalación inicial todavía requiere preparar Python y las dependencias; esta versión no incluye un instalador ejecutable independiente.

## Primer uso

1. En **Inicio**, elegí **Nuevo perfil**, escribí un nombre y confirmá. También podés seleccionar uno existente desde **Perfiles**. Un perfil nuevo aparece como «Sin calibrar».
2. En **Configuración**, seleccioná el índice de cámara y guardá. Si falta el modelo local, usá **Preparar modelo**, que solicita confirmación antes de descargarlo.
3. En **Calibración**, desplegá **Gestos disponibles y tipo de señal** y desmarcá los que no podés realizar. GEOMETRIC es la fuente predeterminada; las otras son experimentales. Elegí **Comenzar / recalibrar** y seguí neutral y tres intentos cómodos por gesto: guiños, cejas individuales, boca y ambas cejas. La cámara y el medidor muestran la señal actual, neutral, activación, liberación y extremo cómodo.
4. Si un gesto tiene calidad débil, usá **Repetir gesto**; el selector permite volver a medir uno específico conservando los demás. También podés marcarlo no disponible desde las opciones. Iniciá **Validar** y realizá solamente los gestos habilitados, volviendo a neutral entre ellos. El ruido breve se tolera; un gesto incorrecto sostenido requiere repetir. **Guardar perfil** se habilita solamente después de superar la validación.
5. Elegí **Probar HeadMouse** para abrir el diagnóstico. Revisá la posición, las proporciones faciales, los umbrales y el desplazamiento esperado sin mover el mouse del sistema.
6. Cuando estés listo, elegí **Activar control** y confirmá «HeadMouse comenzará a controlar el puntero del sistema.».

## Seguridad y estados

Al abrir la aplicación, la cámara y el control están desactivados. Abrir la cámara, calibrar, diagnosticar o usar simulación no habilita acciones del sistema. El control requiere un perfil validado y una confirmación explícita.

**Detener control** interrumpe la salida. **F8** y **Escape** también la detienen cuando la aplicación recibe el teclado: son atajos locales a la aplicación, no atajos globales de Windows. Se conserva el failsafe de PyAutoGUI al llevar el puntero a una esquina. Una llamada al sistema que ya esté en ejecución puede terminar antes de que se aplique la detención.

El estado superior distingue control desactivado, activo y pausado. La pausa por gesto utiliza el mapeo configurado; por defecto corresponde a ambas cejas. La pérdida de un rostro válido impide continuar el movimiento y se conserva el timeout de seguridad del motor.

## Pantallas

| Pantalla | Uso |
|---|---|
| Inicio | Preview, perfil, cámara, MediaPipe, rostro, FPS, procesamiento, gesto y acción prevista. |
| Perfiles | Crear, seleccionar, renombrar, eliminar con confirmación y consultar calibración. Renombrar conserva el identificador interno y los resultados históricos. |
| Calibración | Captura guiada, repetición, validación y guardado. También permite validar perfiles anteriores. |
| Diagnóstico | Coordenadas faciales, cursor virtual esperado, desplazamientos, ratios, umbrales, smoothing y dead zone. Incluye medición de estabilidad y datos avanzados de señal, histéresis y calidad por gesto. |
| Configuración | Cámara, sensibilidad por eje, smoothing, dead zone, timeout, duración y cooldown de gestos, overlays y landmarks. El método disponible es Nariz. |
| Gestos y acciones | Seleccionar la acción de cada gesto y guardar en el perfil. |
| Experimentos | Adquisición de objetivos con cursor interno, práctica con teclado o control real explícitamente activado. |
| Métricas | Indicadores de la sesión y resúmenes históricos locales. |

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

# Reparación del guardado ocular — 26/10/2026

## Causa confirmada y alcance

El traceback entra en la rama `relative=True` de `GazeCalibrationSession.result()`:
es la **medición de cinco puntos del joystick**, que debe construir un
`TrackingCalibration`. No corresponde al modelo absoluto.

Antes, la captura aceptaba cualquier fijación suficientemente estable y, al
reunir cinco puntos, anunciaba `ready`. Recién al guardar restaba las medianas y
construía el modelo. Este exige rangos positivos entre 0,02 y 1. Los errores
`up_range=0.0038342737639921465` y `down_range=-0.017683836886550786`
demuestran incompatibilidad de las mediciones con ese contrato. La validación
del modelo estaba funcionando; se ejecutaba demasiado tarde para la interfaz.

Los logs históricos no conservaban las medianas oculares por objetivo. No
permiten atribuir esos valores a párpados, postura, objetivo incorrecto o una
inversión física concreta. La cámara C270 ya estaba funcionando; esta reparación
no cambia su backend, resolución, FPS, modelo ni umbrales de detección facial.

## Botones y modelos

| Botón / etapa | Callback Qt y comando | Sesión y guardado | Banco |
|---|---|---|---|
| Calibrar tracking ocular | `start_eye_tracking_calibration` → `start_eye_calibration` | `EyeTrackingCalibrationSession` → `save_eye_calibration` → `TrackingCalibration` | `tracking_calibrations[fuente]` |
| Guardar neutral ocular | `save_eye_calibration` | Guarda neutral con rangos nominales identificados por `ranges_measured=False` | Relativo |
| Medir rangos del joystick ocular · 5 puntos | `start_absolute_calibration(relative=True)` → `start_gaze_calibration(relative=True)` | `GazeCalibrationSession` → `save_gaze_calibration` → `TrackingCalibration`, esquema 1, `ranges_measured=True` | Relativo |
| Calibrar ojos absolutos · 9 puntos + validación | `start_absolute_calibration(relative=False)` → `start_gaze_calibration(relative=False)` | La misma clase de sesión en modalidad absoluta → `GazeModel`, esquema 2 | `absolute_calibrations[fuente]` |
| Validación absoluta de cinco puntos | Transición interna tras ajustar los nueve | Cinco objetivos independientes; no construye un modelo relativo | Absoluto |

La superposición ahora indica modalidad, fuente y tipo de guardado. El nombre
histórico del callback `start_absolute_calibration` no determina el modelo: lo
determina el argumento explícito `relative`. Los bancos `both`, `left` y `right`
son independientes, al igual que las calibraciones de gestos por método. Los
campos singulares históricos siguen siendo alias exclusivamente binoculares.

El mínimo relativo 0,02 **no se aplica al absoluto**. Este conserva su mínimo
de semirrango global 0,025 en `GazeModel.fit`, control de dominio y errores de
validación independiente. Una regresión comprueba un absoluto válido cuyos
objetivos de validación desplazan la señal 0,016.

## Auditoría de ejes y señal vertical

`VisionEngine` espeja horizontalmente antes de MediaPipe. `extract_gaze` forma
una base con las comisuras (`h`) y los párpados superior/inferior (`v`). Calcula
`y = cross(h, iris-top) / cross(h, v)`. Rechaza geometría degenerada; no invierte
Y. Con párpados horizontales equivale a `(iris_y-top_y)/(bottom_y-top_y)`.
Y crece hacia abajo. El espejo afecta X y la atribución de canales anatómicos,
no Y. `gaze_source` promedia ambos pares o utiliza exclusivamente el elegido;
no reemplaza un iris ausente por el otro. `FaceData` valida números y frescura.

Los cinco puntos relativos conservan orden centro, izquierda, derecha, arriba,
abajo. Los rangos son `neutral_x-left_x`, `right_x-neutral_x`,
`neutral_y-up_y`, `down_y-neutral_y`. La estrategia divide ΔY negativo por
`up_range` y positivo por `down_range`; los eventos y el backend conservan el
signo. No se aplicaron `abs()` correctivos ni inversiones de ejes.

Muestras **sintéticas**, generadas pasando landmarks por el extractor real:

| Objetivo | Y normalizada | ΔY contra neutral |
|---|---:|---:|
| Centro | 0,50 | 0 |
| Arriba | 0,30 | −0,20 |
| Abajo | 0,70 | +0,20 |

Se repiten para ambos espejados y las tres fuentes. Evidencia local:
`data/logs/gaze-save-sign-audit.json` (19 muestras; ninguna imagen ni webcam).
Otra muestra mueve el iris en imagen de 0,400 a 0,398 y cambia los párpados de
0,370/0,430 a 0,360/0,410: la señal normalizada pasa de 0,50 a 0,76. Demuestra
que el marco de referencia móvil puede invertir una medición sin una inversión
del código. No demuestra que ésa haya sido la causa del caso físico del usuario.

## Captura, repetición y guardado

- También el absoluto captura primero su centro (índice 4 de la grilla). Los
  índices canónicos de los nueve puntos, objetivos y ajuste se conservan.
- Cada fijación requiere duración y cantidad mínima de frames distintos y
  frescos, iris seleccionado y ojos abiertos. Un parpadeo, pérdida o salto
  temporal vacía la ventana y aplica el resguardo de recuperación existente.
- Se conserva el límite ocular p10–p90 de 0,10. La amplitud direccional debe
  superar la dispersión de la fijación y del centro; en relativo además debe
  alcanzar 0,02. Cada eje requerido se comprueba con su signo esperado.
- Se controla estabilidad de cabeza dentro de la ventana y cambio contra el
  centro: nariz 0,06 normalizada, escala 25 % (mínimo 0,02), pose disponible
  10 grados. Son límites conservadores basados en la envolvente que ya usa el
  absoluto, no una validación física del movimiento de cabeza. Cuando la pose
  opcional está ausente, nariz y escala siguen siendo las señales disponibles.
- Una dirección incorrecta o insuficiente queda en `invalid`, sin avanzar y con
  Guardar deshabilitado. Se muestra dirección, desplazamiento firmado y motivo.
  La sesión conserva los puntos útiles y el resumen del intento rechazado.
- Repetir un punto elimina sólo ese punto. Repetir el centro reevalúa las otras
  fijaciones: retiene las compatibles y pide recapturar las incompatibles.
- `ready` relativo exige construir correctamente el modelo antes de anunciarlo;
  al guardar vuelve a comprobar los puntos. El absoluto exige ajuste y aprobación
  independiente. La sesión no fabrica amplitudes ni reduce mínimos.
- El controlador verifica método, esquema, fuente y contexto de cámara, prepara
  una copia del perfil y usa el reemplazo atómico existente. El JSON temporal se
  vuelve a leer y validar antes del reemplazo. Después carga el perfil final y
  compara el registro de calibración guardado antes de descartar la sesión.
- Un rechazo de mediciones conserva perfil anterior y sesión. Un fallo de disco
  anterior al reemplazo deja el archivo previo y permite reintentar. Si el archivo
  se escribió pero falla la lectura posterior, el mensaje distingue ese caso:
  no anuncia éxito ni descarta la sesión o sustituye el perfil en memoria.
- Los resúmenes de `data/calibration/` incluyen objetivo, tiempos, muestras,
  dispersión, mediana seleccionada, ΔX/ΔY, dirección esperada e intentos
  rechazados; no guardan imágenes ni secuencias individuales de frames.

## Activación: segundo bloqueo encontrado

Inspección de sólo lectura del perfil local durante esta reparación:

- Método seleccionado: `eye`, fuente `both`.
- Relativo binocular existente: sólo neutral, `ranges_measured=False`.
- **Gestos de Ojos relativos: validación pendiente**.
- Absoluto binocular existente: marcado validado; esto no acredita rendimiento
  físico actual. No hay calibraciones monoculares persistidas en ese perfil.

Por lo tanto el rechazo al guardar no era el único bloqueo. También falta
validar los gestos en el banco de Ojos relativos. No se copiaron aprobaciones
de Nariz/Absoluto ni se alteró el perfil personal para habilitarlo artificialmente.

La ventana enumera calibración ausente/incompatible, gestos pendientes, cámara
no lista, iris ausente/frame vencido, medición en curso, pausa y confirmación
explícita. La activación ocular comprueba frescura e iris antes de crear el
backend. Conserva comprobaciones de contexto, autorización, F8, pausa y límites
de movimiento. Calibración y diagnóstico seguro no crean salida al mouse.
Al guardar una modalidad distinta de la seleccionada, el mensaje pide seleccionar
y guardar ese método para utilizar el banco correspondiente.

## Prueba física C270 pendiente — la realiza el usuario

1. Abrir la aplicación actualizada. Seleccionar el perfil y guardar en
   Configuración **Ojos relativos / Ambos ojos**. Conservar la captura DirectShow
   que ya funciona; no cambiar resolución entre medición y uso.
2. En Calibración, completar/validar los gestos de este método si la ventana los
   indica pendientes. Guardarlos. La validación de gestos y la ocular son distintas.
3. Calibrar neutral ocular y guardarlo. Mantener cabeza, distancia y cámara fijas.
4. Pulsar **Medir rangos del joystick ocular · 5 puntos**. Seguir centro,
   izquierda, derecha, arriba y abajo. Mirar el objetivo amarillo moviendo los
   ojos, manteniendo los párpados abiertos sin forzarlos.
5. Si aparece señal incompatible o amplitud insuficiente, registrar el ΔY y la
   dirección. Pulsar **Repetir punto**: los otros puntos útiles se conservan.
   Una señal repetidamente invertida requiere analizar estos registros; no
   aprobarla invirtiendo ejes o inventando rangos.
6. Guardar sólo cuando el botón esté habilitado y comprobar el mensaje
   **guardada y releída**. Abrir Diagnóstico seguro y observar ΔX/ΔY y delta de
   cursor: izquierda/arriba negativos, derecha/abajo positivos. No mueve el mouse.
7. Revisar las condiciones bajo Activar control. Cuando se cumplan, confirmar
   explícitamente. Probar desplazamientos pequeños en cuatro direcciones y
   detener con **F8 / DETENER CONTROL**. Verificar también pausa y pérdida del iris.
8. Seleccionar y guardar **Ojos absolutos / Ambos ojos**. Revisar la validación
   de sus gestos. Mantener la misma pantalla primaria, DPI y resolución de cámara.
9. Pulsar **Calibrar ojos absolutos · 9 puntos + validación**. Capturar primero
   centro y luego los restantes objetivos de ajuste; completar los cinco
   objetivos independientes de validación.
10. Si falla una fijación, repetirla. Si la validación global falla, no guardar ni
    activar: repetir validación o recalibrar los nueve puntos según el mensaje.
11. Guardar el modelo aprobado y abrir predicción segura: comprobar si el punto
    celeste sigue distintas zonas de la mirada sin mover el mouse real.
12. Activar absoluto sólo tras revisar diagnóstico, aprobación y condiciones;
    hacer una prueba breve y detener con F8.
13. Repetir ambos recorridos con **Ojo izquierdo** y después **Ojo derecho**,
    guardando cada selección. No es necesario cerrar el ojo no seleccionado.
14. Tras reiniciar, comprobar que cada método/fuente recupera su calibración.
    Conservar los registros y anotar comodidad, fallos de dirección, luz y
    postura. Esta prueba física todavía no está realizada por esta reparación.

## Verificación automatizada y preservación

Pruebas nuevas en `tests/test_gaze_save.py` y `tests/test_gaze_gui.py`: los dos
valores exactos del traceback, signos, inversión simulada, párpados móviles,
fuentes, frescura, parpadeo, dispersión, postura, repetición, cambio de neutral,
guardado/relectura, disco ocupado, bancos independientes, errores visibles y
activación con backend simulado en las cuatro direcciones. La suite completa
incluye las regresiones previas de nariz, gestos, cámara, F8 y ciclo Qt.

Resultado final: **326 pruebas aprobadas**, 43,296 s, **código de salida 0**.
La prueba nativa con MediaPipe real y captura sintética también terminó con
**código 0**. La revisión visual sintética muestra el motivo firmado, el punto
rechazado y Guardar deshabilitado (`data/logs/gaze-save-error-synthetic.png`).
Los textos de Configuración ahora usan **DirectShow · Webcams USB en Windows**,
**Media Foundation · Windows** y **Preparar captura USB**, sin una marca/modelo
de cámara específico. El cambio es de nombres; conserva los valores de captura.

Respaldo previo: `data/logs/checkpoints/pre-gaze-save-20261027T021412428069Z/`
(ZIP y manifiesto SHA). Se preservaron rama, HEAD, cambios locales y perfiles.
No hubo commits, pushes, mezcla de ramas, instalador ni ejecución del mouse real.
Los resultados finales y códigos de salida se registran en
`data/logs/gaze-save-full-tests.txt` y `data/logs/gaze-save-native-smoke.txt`.

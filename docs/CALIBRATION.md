# Calibración personalizada

La implementación actual es [v0.3.1: calibración adaptativa genérica](CALIBRATION_V031.md).
GUI y CLI comparten captura, ajuste estadístico y validación. El documento
detalla fórmulas, calidad, histéresis, ambas cejas, blendshapes, telemetría y límites.

## Procedimiento

Abrir la [GUI](GUI.md) o ejecutar `python calibrate.py --user julian`.
Primero se captura neutral: preparación de 3 s y ventana válida de 4 s con
al menos 20 muestras. Luego se realizan tres repeticiones por gesto habilitado:
1 s neutral y 0.8 s activo, descartando 0.3 s de transición y exigiendo ocho
muestras por ventana. Se descartan duplicados, datos no finitos y vencidos.
La pérdida de tracking reinicia la ventana actual. No se pide sostener un gesto
facial durante cuatro segundos.

La disponibilidad es configurable; no realizar un gesto no impide calibrar los
demás. La calidad débil permite repetir solo ese gesto u omitirlo. La captura de
ambas cejas es independiente de las dos unilaterales. No se usan extremos de un
solo frame ni una fracción fija como único criterio de ajuste.

En CLI, SPACE comienza, valida y guarda según el estado; R repite el paso
actual; C reinicia; S omite el gesto actual; Q descarta. Las teclas 1–6 vuelven
a medir guiño izquierdo, derecho, ceja izquierda, derecha, boca y ambas cejas.
Ejemplo: `python calibrate.py --user julian --disable LEFT_BROW --disable RIGHT_BROW`.
`--brow-signal BLENDSHAPE` o `HYBRID` son experimentales y requieren calibración propia.

## Validación antes de guardar

Se usa **GestureEngine real**, sin ControlEngine ni entradas al sistema. Se
exigen 2 s de neutral válido entre gestos habilitados y al final. Interrupciones
breves de hasta 0.15 s no cuentan como tiempo neutral pero se toleran; un gesto
incorrecto sostenido 0.35 s genera error. Cada paso tiene timeout de 30 s.
Se respetan hold/cooldown, liberación e histéresis. Un evento aislado no rechaza
inmediatamente la validación. R repite el paso conservando los ya reconocidos.

Solo guardar después de aprobar escribe el perfil. Cerrar o interrumpir antes
conserva el archivo previo. La GUI muestra botones y el estado de cada gesto;
la CLI requiere teclado. Las muestras crudas viven solo durante la sesión.

## Perfiles y compatibilidad

`data/profiles/<user_id>.json` conserva esquema 2 y agrega:

- `calibration_version: "0.3.1"` y `gesture_calibrations` por identidad;
- disponibilidad, fuente, canales, dirección, estadísticas neutral/activa;
- repeticiones, activación/liberación, calidad, separación, ruido, reintentos;
- `neutral_nose_x/y`, settings personales, resultado y fecha de validación;
- cinco `thresholds` de compatibilidad y agregados de `calibration_telemetry`.

No se serializan muestras individuales, fotos ni video. Las fechas de creación
válidas se conservan al recalibrar. El guardado usa temporal, flush/fsync y
`os.replace`; un fallo no trunca el perfil anterior. No hay bloqueo multiproceso:
no calibrar el mismo usuario desde dos instancias simultáneas. IDs: 1–64
caracteres ASCII alfanuméricos, guion/guion bajo; se rechazan rutas y nombres
reservados de Windows.

Perfiles anteriores válidos con cinco thresholds siguen funcionando con umbral
único. Ambas cejas usan como fallback los dos umbrales unilaterales. Si contienen
neutral/extremos, se comprueba separación: una calibración claramente deficiente
ya no se acepta silenciosamente. Recalibrar el mismo ID por CLI permite reparar
un perfil inválido; desde GUI se puede crear uno nuevo sin borrar el anterior.

`--user default` busca `calibration.json` si falta su perfil. Para otro ID,
usar `python main.py --user julian --legacy-calibration calibration.json`.
La identidad debe coincidir. Un perfil individual tiene prioridad; no se migra
ni sobreescribe automáticamente. La compatibilidad permite leer perfiles viejos
con la aplicación nueva, no garantiza usar registros nuevos con versiones viejas.

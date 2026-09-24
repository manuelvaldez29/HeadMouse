# Calibración personalizada

## Procedimiento

Ejecutar `python calibrate.py --user julian`. Se mantienen las seis fases:
neutral, guiño izquierdo, derecho, ceja izquierda, derecha y boca. Defaults:
3 s de preparación y 4 s de captura. Se requieren 20 detecciones únicas y
recientes por fase; la UI permite repetir una fase incompleta con R.

La mediana estima neutral. Los percentiles 10 de ojos y 90 de cejas/boca
representan extremos: resisten muestras aisladas anómalas sin eliminar el
movimiento deliberado. Son los estadísticos originales, ahora sin aceptar
listas vacías como cero. Se descartan duplicados, datos no finitos y vencidos.
No son robustos a cualquier proporción de contaminación ni prueban que el gesto
solicitado se realizó: por eso se incorpora validación posterior.

Para cada lado se conserva `threshold = neutral + 0.6 * (extremo - neutral)`.
El factor es configurable, no se entrena un modelo. Se registra MAD neutral de
ojos, cejas, boca y coordenadas nasales. La distancia del umbral al neutral debe
superar `max(min_separation, noise_multiplier * 1.4826 * MAD)`. Defaults: 0.002
y 3. El extremo debe estar más allá del umbral en la dirección correcta. Esta
regla es una comprobación heurística de calidad, no una validación clínica.

## Validación antes de guardar

Después de calcular umbrales, SPACE inicia una prueba con **GestureEngine real**,
sin ControlEngine ni PyAutoGUI. Se exige neutral durante 2 s; luego guiño izq.,
guiño der., ceja izq., ceja der., boca y ambas cejas. Entre cada gesto, y al final,
se exige volver al neutral. Cada paso tiene timeout de 30 s configurable;
`validation_neutral_s` permite ajustar los 2 s de neutral.

Los eventos inesperados rechazan la prueba. Se usan hold/cooldown configurados;
no basta cruzar el umbral un instante. La liberación se comprueba por ratios,
para no confundir silencio durante cooldown con neutral. Pérdida de rostro
reinicia la espera de neutral. R repite validación, C vuelve a calibrar, Q
descarta. Solo SPACE después de aprobar escribe el perfil. Cerrar o interrumpir
antes conserva intacto el archivo anterior.

La UI CLI exige teclado. En v0.3, el wizard de [la aplicación desktop](GUI.md)
ofrece botones e instrucciones visuales y reutiliza Samples, build_calibration
y CalibrationValidation. Los seis gestos de validación siguen siendo obligatorios;
el mapeo de acciones no elimina esa exigencia. Algunos gestos pueden resultar
inaccesibles para ciertas personas: la selección de un subconjunto de gestos
y la validación de accesibilidad con usuarios siguen pendientes.

## Perfiles

`data/profiles/<user_id>.json`, esquema 2:

- `user_id`, `created_at`, `calibrated_at`;
- `neutral_nose_x/y`, `neutral`, `neutral_variability` (MAD);
- `gesture_extremes`, cinco `thresholds`, `sample_counts`;
- `settings.gesture`: sensibilidad, smoothing, dead zone, tiempos;
- `settings.calibration`: parámetros usados para la calibración;
- `validation`: resultado, eventos reconocidos, fecha.

Se conservan fechas de creación al recalibrar. Se escribe primero un temporal
en el mismo directorio, se hace flush/fsync y `os.replace`; si falla no se
trunca el perfil previo. No hay bloqueo multiproceso: no calibrar el mismo
usuario en dos instancias a la vez. IDs: 1–64 caracteres ASCII alfanuméricos,
guion/guion bajo; nombres reservados Windows y rutas se rechazan.

Perfiles legacy con los cinco thresholds siguen siendo legibles. Si contienen
neutral/extremos se valida su separación; un perfil viejo inválido debe
recalibrarse. La identidad debe coincidir con `--user`. Para un archivo global
de un usuario identificado:

```powershell
python main.py --user julian --legacy-calibration calibration.json
```

Un perfil individual existente tiene prioridad sobre ese fallback. Para el
usuario `default`, `calibration.json` se busca automáticamente si falta el nuevo
perfil. No se migra ni sobreescribe silenciosamente: para crear un perfil v2
validado, ejecutar calibración. Los perfiles no contienen imágenes.

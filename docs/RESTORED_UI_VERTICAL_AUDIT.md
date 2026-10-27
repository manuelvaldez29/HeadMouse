# Interfaz restaurada y auditoría vertical — 27/10/2026

## Restauración selectiva y respaldo

Se tomó como base local el estado inmediatamente anterior al rediseño:
`data/logs/checkpoints/pre-eye-wizard-20261027T031304210380Z/source.zip`.
No se volvió a HEAD ni se usaron comandos Git de restauración general.

Antes de restaurar se guardaron **378 archivos**, incluidos fuentes, archivos
nuevos, modelos locales, perfiles, configuración y logs, en:

`data/logs/checkpoints/pre-selective-ui-restore-20261027T034508702947Z/workspace.zip`

El manifiesto SHA-256 está en `manifest.json` junto al ZIP. Se excluyeron `.git`,
`.venv`, cachés reproducibles y la carpeta de checkpoints para evitar recursión;
los checkpoints anteriores permanecen en su lugar.

| Cambio del rediseño | Resultado |
|---|---|
| Selector general y botones nuevos de configuración ocular en Inicio | Retirados; Inicio recuperado del checkpoint |
| Asistente `EyeSetupDialog` y navegación por pasos global | Retirados |
| `eye_setup.py`, comandos del asistente, autosalvado y telemetría exclusiva de ese asistente | Retirados |
| Overlay nuevo con modo guiado, anillos y controles especiales del asistente | Restaurado al archivo exacto anterior |
| Pruebas exclusivas del asistente global | Retiradas; permanecen recuperables en el respaldo |
| Expectativas de textos de Inicio alteradas durante el rediseño | Restauradas desde checkpoint |
| Captura, logs, liberación de cámara, persistencia atómica y rechazo temprano de rangos | Conservados |
| Monitor principal con otros monitores conectados | Conservado como corrección funcional ocular |
| Movimiento ocular con clics pendientes, acciones deshabilitadas en dos capas | Conservado; no afecta Nariz |
| Nariz, gestos nasales, acciones, experimentos y calibración originales | Conservados |

`tests/test_eye_gui.py` no tenía modificaciones locales antes del rediseño y no
formaba parte del ZIP de cambios: su único cambio era el texto esperado de un
botón. Se recuperó ese archivo concreto mediante lectura de `git show`, tras
comprobar el diff. No se sobrescribió trabajo anterior por inferencia.

La navegación vuelve a tener las ocho secciones originales y los botones
**Activar control / DETENER CONTROL**. Las únicas adiciones visuales son locales:
referencia vertical del joystick, diagnóstico vertical y acceso explícito a
calibración de gestos oculares desde Configuración. No hay asistente global.

Se verificó por hashes que el perfil personal y `data/last_profile.json` no
cambiaron. `NoseTrackingStrategy` coincide con el checkpoint, normalizando sólo
finales de línea. La suite comprueba también sensibilidad, suavizado, gestos,
acciones, pausa, experimentos y failsafe nasales.

## Prueba física realizada, sin movimiento del mouse

El usuario autorizó la prueba e indicó que la cámara estaba libre. Se ejecutó
un único `VisionEngine` y se mostraron centro, arriba y abajo en el monitor
principal. Cada fijación reunió **31 muestras**, durante aproximadamente dos
segundos, después de un tiempo para acomodar la mirada. Se filtraron frames
viejos, iris ausente, ojos cerrados y movimiento excesivo dentro de la ventana.

Archivo completo, sin imágenes:
`data/logs/vertical-physical-20261027T035048834692Z.json`.
Salida del proceso: `data/logs/vertical-physical-run.txt`, **código 0**.
En ese primer archivo el campo `quality=1` era un marcador fijo de captura
completa, no una medición de precisión; no se utiliza en las conclusiones.
La herramienta integrada ya deriva ese indicador de la dispersión observada.

| Fuente | ΔY arriba, párpados | ΔY abajo, párpados | ΔY arriba, comisuras | ΔY abajo, comisuras |
|---|---:|---:|---:|---:|
| Izquierdo | −0,016236 | +0,004585 | −0,027453 | +0,014715 |
| Derecho | −0,014936 | +0,008031 | −0,025358 | +0,014890 |
| Ambos | −0,015546 | +0,006308 | −0,026290 | +0,014815 |

Las seis comparaciones tienen signo correcto. La prueba no respalda invertir Y.
La referencia de comisuras aumenta la excursión observada, pero sus unidades
usan el ancho ocular en lugar de la apertura de párpados: no se debe interpretar
el cociente de amplitudes como una mejora equivalente de precisión.

El movimiento de cabeza entre fijaciones no fue cero: la nariz pasó de
Y=0,4627 a 0,4691 y 0,4735, y el pitch mediano de −13,58° a −14,10° y −16,05°.
Esto limita la atribución del resultado exclusivamente a los párpados. En imagen,
el iris izquierdo pasó de Y=173,06 a 173,93 y 177,78 píxeles; las comisuras y los
párpados también se desplazaron. El desplazamiento del iris en imagen aislado
no equivale al desplazamiento ocular relativo a la cara.

## Por qué no subía con la configuración guardada

La calibración utilizada por la prueba tenía:

- Neutral Y guardado: **0,388475**.
- Rangos superior/inferior: **0,2 / 0,2**, nominales (`ranges_measured=False`).
- Zona muerta: **0,15** del rango; sensibilidad 12, aceleración 8, suavizado 0,65.

En la medición actual, el centro binocular fue **0,411604** y arriba
**0,396058**. Por lo tanto, mirar arriba seguía dejando la señal **por encima del
neutral guardado**. El delta normalizado era aproximadamente +0,0379, dentro de
la zona muerta, y el motor calculó **0 píxeles hacia arriba**. No fue PyAutoGUI
invirtiendo un movimiento negativo: el movimiento negativo no se había generado.

Además, recapturar únicamente el neutral no garantiza resolverlo: la excursión
superior observada, dividida por el rango nominal 0,2, equivale a 0,0777, todavía
menor que la zona muerta 0,15. Hay una combinación comprobada de neutral
desactualizado y excursión pequeña frente a rangos nominales. No se redujo la
zona muerta para ocultar el problema.

Los valores históricos `up_range=0,003834...` y `down_range=−0,017684...` siguen
siendo capturas rechazadas. No se reinterpretaron como calibraciones válidas.

## Corrección acotada de referencia vertical

Se conserva como predeterminada la referencia original entre párpados, para no
reinterpretar calibraciones existentes. Se añadió una opción experimental,
**Comisuras**, exclusivamente para el joystick relativo:

`Y = 0,5 + cross(h, iris − centro_comisuras) / |h|²`

`h` es el vector entre comisuras. El cálculo mantiene el signo de pantalla,
normaliza escala y rotación en el plano y no divide por la apertura instantánea
de los párpados. El 0,5 establece el origen de coordenadas; no añade movimiento
ni fabrica amplitud. El eje X conserva exactamente su fórmula anterior.

Un caso controlado desplaza el iris hacia arriba en imagen, de 0,400 a 0,398,
mientras cambian los párpados. La normalización anterior aumenta de 0,50 a 0,76;
la referencia nueva disminuye de 0,50 a 0,490625. Esto reproduce y evita una
inversión causada por el marco móvil, sin invertir el eje.

La selección queda en `eye.vertical_reference` y en cada `TrackingCalibration`.
Una calibración antigua se interpreta como `eyelids`. Cambiar de referencia
invalida su uso hasta recapturar. **Comisuras exige cinco rangos medidos**; un
neutral con rangos nominales no habilita esa opción. Se mantienen mínimo 0,02,
estabilidad, dirección y guardado atómico. En esta prueba, el rango inferior de
comisuras fue 0,014815: **todavía no alcanza para aprobar un modelo completo**.

El modelo absoluto de nueve puntos y cinco validaciones conserva su señal
original y sus bancos independientes. No se migraron ni reescribieron modelos.

## Diagnóstico disponible en la interfaz original

En **Diagnóstico → Diagnóstico vertical · centro / arriba / abajo** se utiliza
la superposición ocular existente. Permite repetir sólo un objetivo y guarda
resúmenes en `data/experiments/`. No ofrece Guardar calibración.

El panel técnico muestra cada ojo y la combinación binocular, ambas referencias,
iris/párpados/comisuras crudos en píxeles, posición normalizada, posición filtrada,
delta calculado y delta entero que enviaría el motor, incluyendo su acumulador
fraccional y límites. `DiagnosticMovementTrace` ejecuta el `ControlEngine` real
contra `MemoryMouse`: ninguna acción puede llegar al sistema operativo.

También puede ejecutarse la herramienta independiente:

```powershell
.\.venv\Scripts\python.exe -X faulthandler -B vertical_diagnostic.py --confirm-camera-free
```

La herramienta conserva los resúmenes de mediciones incompletas al salir. No
abre otro capturador en paralelo, no guarda fotos ni modifica perfiles.

## Gestos oculares, acciones y autorización

**Configuración → Calibrar gestos para control ocular** abre la misma página,
medidores, capturas, repeticiones, validación y guardado facial que se utilizaban
antes. Se aplica a la modalidad que esté seleccionada y guardada. No crea
acciones nuevas. Los bancos `gesture_modes` y de configuraciones se conservan.

Se registra `gesture_mode_origin[modalidad]="measured"` cuando se guarda la
calibración/validación de esa modalidad. Una aprobación nasal o una copia
histórica de compatibilidad no autoriza silenciosamente clics oculares. Los
registros existentes se conservan; para habilitar sus acciones oculares hace
falta validarlos y guardarlos explícitamente en la modalidad ocular.

Con movimiento compatible y autorización explícita puede activarse sólo
movimiento. Gestos y `ControlEngine` bloquean las acciones pendientes, incluido
dictado. Nariz conserva sus requisitos y comportamiento anteriores.

Los guiños del ojo seguido suspenden el movimiento y requieren recuperación
estable. El otro ojo conserva su tratamiento monocular existente. Los demás
gestos habilitados también suspenden temporalmente el movimiento ocular mientras
están activos, conservando sus acciones autorizadas y su recuperación posterior.
Estas protecciones no se aplican a la estrategia nasal.

## Pantalla principal y seguridad

Se conservó el soporte funcional para el principal con otros monitores conectados.
El diagnóstico del entorno registró dos monitores 1920×1080 al 100 %, con el
principal en (0,0) y el segundo en (1920,0). Qt y Win32 utilizan nombres de
monitor diferentes, por lo que se comprueban selección primaria, cantidad,
dimensiones y transformación explícita; no se supone igualdad textual de nombres.

No se multiplica el origen Qt por el DPR. Se guardan rectángulos lógico y físico
y se limita el control absoluto al principal. Las pruebas cubren orígenes
negativos/no coincidentes y escalados 100/125/150/200 %. Se conserva el failsafe.
Referencias: [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html) y
[SetThreadDpiAwarenessContext](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setthreaddpiawarenesscontext).

## Prueba física que falta para aprobar la mejora

1. Abrir la interfaz original y seleccionar/guardar **Ojos relativos / Ambos ojos**.
2. Repetir el diagnóstico vertical con la cabeza apoyada y luz estable; comparar
   señal y dispersión por ojo. Revisar si el centro coincide con el neutral guardado.
3. Para probar la referencia alternativa, seleccionar **Comisuras** y guardar la
   configuración. Capturar los cinco puntos; repetir únicamente los rechazados.
4. Guardar sólo si todos los rangos son válidos. Si abajo sigue por debajo de
   0,02, informar señal insuficiente para ese modelo; no habilitarlo artificialmente.
5. Probar direcciones en diagnóstico seguro. Calibrar/validar gestos oculares en
   su página original y guardar; revisar asignación de acciones de esa modalidad.
6. Con aprobación explícita, probar movimiento breve en cuatro direcciones y
   detener con F8/botón. Comprobar guiños, recuperación y pérdida de iris.
7. Repetir izquierdo/derecho y, después, absoluto 9+5 en el monitor principal.

Se midió señal física y se identificó por qué la configuración anterior generaba
cero movimiento hacia arriba. **No se afirma que el control físico con la nueva
referencia ya esté aprobado**: falta una calibración completa válida y su prueba
de cursor. Las pruebas automatizadas usan siempre backend simulado.

Logs de regresión: `data/logs/selective-restore-full-tests.txt` y
`data/logs/selective-restore-native-smoke.txt`. Capturas de interfaz sintética:
`data/logs/restored-home-synthetic.png` y `data/logs/restored-ocular-settings-synthetic.png`.

Resultado de la suite: **346 pruebas aprobadas, código de salida 0** (38,735 s).
Prueba nativa con MediaPipe real y captura sintética: **código 0**. No se ejecutó
el backend real del mouse. Los tests de la herramienta vertical se vuelven a
ejecutar tras el ajuste del indicador de dispersión.

# Dictado por voz local

Cuando un click de HeadMouse (guiño) deja el foco en un campo de texto
editable, se abre el micrófono. El usuario habla, el fin de la frase se
detecta por silencio, el audio se transcribe en la computadora y el texto se
escribe en ese campo. No hace falta nada más que la voz para escribir un
mensaje o una búsqueda.

## Preparación (una sola vez, con Internet)

```powershell
python -m pip install -r requirements-voice.txt
python dictation.py --download-model          # modelo small, ≈ 464 MB
python dictation.py --test                    # hablar después del tono
```

El modelo también se puede preparar desde Configuración → "Preparar modelo de
voz". Después se marca **Dictado por voz** y se guarda la configuración. Desde
0.4.0 el modelo se descarga en `%LOCALAPPDATA%\HeadMouse\models\whisper\<modelo>`
(fuera del proyecto y de Git). Los ya descargados en `models/whisper/<modelo>` del
proyecto se siguen usando sin copiarlos; esa carpeta se revisa una sola vez por
ejecución. En uso normal se carga con `local_files_only` y no hay tráfico de red.
El instalador de Windows incluye el motor de dictado, pero no el modelo.

## Flujo

1. Con el control activo, un `LEFT_CLICK` o `DOUBLE_CLICK` ejecutado por
   HeadMouse arma el dictado. La acción `DICTATE`, asignable a un gesto en
   "Gestos y acciones", dicta en el campo que ya tiene el foco.
2. Durante `focus_window_ms` (800 ms), Windows UI Automation consulta el
   elemento con foco. Se dicta solo si es un `Edit`, o un `Document`/`ComboBox`
   con ValuePattern editable. **Nunca si `IsPassword` es verdadero.**
3. Suena un tono agudo y aparece el aviso flotante "Escuchando…", que no toma
   el foco ni recibe clicks. `Endpointer` decide trama por trama si hay voz (ver
   "Detección de voz" abajo). Termina tras `silence_s` (1,2 s) sin voz, a los
   `max_utterance_s` (20 s) o con el **gesto de click** (terminar ya), y cierra
   si no hubo habla en `no_speech_timeout_s` (6 s).
4. Suena un tono grave y faster-whisper transcribe (CPU, int8, 8 hilos, greedy,
   filtro VAD, segmentos de no-habla descartados). Se filtran las frases que
   Whisper inventa ante el silencio ("Gracias por ver el video").
5. El texto se escribe con `SendInput` y `KEYEVENTF_UNICODE`: tildes, ñ y
   signos de apertura, sin tocar el portapapeles. Con `send_word` (por ejemplo,
   "enviar") como última palabra, esa palabra se quita y se presiona Enter.

### Comandos de edición

Si la frase **entera** es un comando, no se escribe: se ejecuta. Dentro de una
frase más larga ("hay que borrar la pizarra"), se escribe como texto normal. Se
desactivan con `voice.commands: false`.

| Frase | Teclas |
|---|---|
| "borrar", "borrar eso", "borrar lo último" | Retroceso × largo del último dictado (solo lo que escribió HeadMouse) |
| "borrar palabra", "borrar tres palabras" | Ctrl+Retroceso × N |
| "borrar letra", "borrar 5 letras" | Retroceso × N |
| "borrar todo" | Ctrl+A, Retroceso |
| "deshacer" | Ctrl+Z |

Dónde se ve la ayuda: en "Gestos y acciones" hay una sección "Comandos de voz
para corregir" (con avisos si el dictado o los comandos están apagados, y la
palabra de Enter si está configurada). En Configuración hay un resumen debajo
de "Dictado por voz", y el aviso flotante sugiere «borrar» al escuchar y
después de escribir. La lista sale de `dictation.VOICE_COMMANDS`, y un test
verifica que cada ejemplo lo reconozca `parse_command`.

N va de 1 a 50, en dígitos o palabras ("una" a "diez"). Se ignoran mayúsculas,
tildes y puntuación ("Borrá dos letras." funciona). Sin hablar, las acciones
**Borrar letra** y **Borrar palabra** se pueden asignar a un gesto en "Gestos y
acciones".

Mientras se dicta, y `after_dictation_ms` después, **solo se mueve el cursor**:
hablar mueve boca, ojos y cejas, y abriría Inicio, haría clicks o scroll. Dos
gestos sí cuentan mientras escucha:
- El gesto de pausa (ambas cejas) **cancela el dictado** en lugar de pausar. F8
  y "Detener control" también lo cancelan, y no se escribe nada después.
- El gesto de click **termina ya y transcribe** lo dicho, sin esperar el
  silencio (2026-11-03). Con otra persona o la tele hablando de fondo, el
  silencio puede no llegar nunca.

### Detección de voz (2026-11-03)

`voice.detector` elige cómo se decide que hay voz. Se cambia en Configuración →
Dictado por voz → "Detección de voz".
- **`neural` (predeterminada):** Silero VAD v6, el modelo ONNX que viene con
  faster-whisper (no se descarga nada más). Tramas de 32 ms, empieza a 0,5 y
  sigue mientras no baje de 0,35.
- **`energy`:** la anterior. Mide el ruido en los primeros 300 ms y considera
  voz lo que supera 3 veces ese nivel (unos 10 dB).
- Si Silero no se puede cargar, se usa `energy` y queda un aviso en el log.

Banco del 2026-11-03: voces sintéticas de Windows (Helena, español) más ruido a
distintas relaciones voz/ruido. La tabla muestra palabras bien transcriptas con
Whisper `small`, 4 frases por caso:

| Situación | Por volumen | Neuronal |
|---|---|---|
| Ventilador, voz 15 dB sobre el ruido | 97 % | 97 % |
| Ventilador, 8 dB | 67 % (1 sin detectar) | 97 % |
| Ventilador, 3 dB | 0 % (ninguna detectada) | 97 % |
| Golpes y vajilla, 10 y 5 dB | 0 % (no corta nunca) | 97 % |
| Tele con voces de fondo, 10 dB | 92 % | 0 % (no corta nunca) |

Una voz de fondo también es habla para la red. Para ese caso está el gesto de
terminar, y el pendiente de reconocer la voz del usuario. Medir la energía en
paralelo para terminar no alcanzó: la tele también la supera en sus sílabas.

Cada dictado deja en el log una línea "Dictado: detector … · fin … · voz … s",
sin audio ni texto. El fin es `silence`, `max`, `gesture` o `timeout`.

## Cuando un campo no dicta

Cada click que no encuentra un campo de texto deja en `data/logs/headmouse.log` una
línea «Click sin campo de texto para dictar» con el tipo, el framework y la clase
del elemento que tenía el foco (nunca su nombre ni su texto). Para ver en vivo qué
reporta UI Automation al hacer click en una aplicación:

```
python dictation.py --probe-focus 30
```

Muestra el elemento con foco y el que está bajo el puntero (con cuatro ancestros)
cada vez que cambian.

**Guiño largo = arrastre (2026-11-02).** Con el click sostenido (modo Nariz), un
guiño de más de `control.drag_hold_ms` aprieta el botón y lo deja apretado hasta el
próximo guiño. Con el valor inicial de 400 ms, los clicks deliberados del usuario
quedaban como `LEFT_DRAG_START` en el log y el dictado nunca se activaba. Ahora el
valor inicial es 1 s, el log anota la duración de cada guiño ("Guiño de … ms → click")
y un arrastre que se suelta sin mover el cursor también avisa al dictado, porque para
Windows es un click.

**WebView2 dentro de WinUI 3 (WhatsApp Desktop 2.2640, 2026-10-28).** Con el cursor
de texto ya parpadeando en el cuadro de mensaje, `GetFocusedElement` devuelve el
puente de WinUI (`Microsoft.UI.Content.DesktopChildSiteBridge`, un Pane sin Value)
y no entra al contenido web. El cuadro (Edit de framework Chrome, editable) sí
informa `HasKeyboardFocus` cuando se lo busca por posición. Por eso, si el foco no
es un campo de texto, `UIAFocusProbe` mira el elemento bajo el puntero y hasta tres
ancestros y toma el primero con foco de teclado, sólo si esa ventana es la activa.
Un click fuera del campo (un mensaje, el título del chat) no dicta aunque el cuadro
conserve el foco, y las contraseñas siguen excluidas. En el diagnóstico, un foco
hallado así aparece con `via: puntero`.

## Privacidad

El audio existe solo en RAM durante el dictado. No se guardan audio ni texto.
Las métricas de sesión registran cantidades por resultado (`typed`,
`cancelled`, `no_speech`, `empty`, `error`), segundos de audio, tiempo medio de
transcripción y cantidad de caracteres.

## Verificado en este equipo (2026-10-12)

- Transcripción de una frase generada con la voz de Windows (Helena, es-ES):
  *"Hola, quería saber si mañana podemos juntarnos a las 5 para terminar la
  tesis."* Fue exacta. El modelo small carga en 2,6 s y transcribe en 2,8 s con
  8 hilos (12 hilos no mejoran). Whisper procesa una ventana fija de 30 s, así
  que la demora casi no depende del largo de la frase. Con `base` debería
  bajar a alrededor de 1 s, a costa de precisión.
- UI Automation sobre una ventana Qt: campo de texto → editable; contraseña →
  `password=True`, no se dicta; botón → no editable; área de texto → editable.
- `SendInput` escribió "Mañana, ¿podés? ñandú á é" exacto en el campo.
- El aviso flotante no cambia la ventana en primer plano ni el foco del campo.

## Pendiente de prueba física

Micrófono real en distintos ambientes (umbral de energía, cortes de frase),
navegadores (Chrome/Edge: buscador, WhatsApp Web y otros `contenteditable`),
Word y apps de mensajería. También ventanas con permisos de administrador:
Windows bloquea SendInput y se informa el error. Falta medir la demora completa
(fin del habla → texto escrito) y la tasa de errores de palabra con usuarios.

Limitación conocida: si un click no cambia el foco y el foco ya estaba en un
campo de texto (por ejemplo, un click sobre una zona no enfocable), el dictado
se abre igual. Se cierra solo si no se habla, o se cancela con ambas cejas.

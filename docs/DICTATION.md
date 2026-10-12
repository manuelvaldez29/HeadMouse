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
voz". Después se marca **Dictado por voz** y se guarda la configuración. El
modelo queda en `models/whisper/<modelo>` (excluido de Git). En uso normal se
carga con `local_files_only` y no hay tráfico de red.

## Flujo

1. Con el control activo, un `LEFT_CLICK` o `DOUBLE_CLICK` ejecutado por
   HeadMouse arma el dictado. La acción `DICTATE`, asignable a un gesto en
   "Gestos y acciones", dicta en el campo que ya tiene el foco.
2. Durante `focus_window_ms` (800 ms), Windows UI Automation consulta el
   elemento con foco. Se dicta solo si es un `Edit`, o un `Document`/`ComboBox`
   con ValuePattern editable. **Nunca si `IsPassword` es verdadero.**
3. Suena un tono agudo y aparece el aviso flotante "Escuchando…", que no toma
   el foco ni recibe clicks. `Endpointer` mide el ruido de fondo en los primeros
   300 ms, detecta el habla por energía y termina tras `silence_s` (1,2 s) de
   silencio, a los `max_utterance_s` (20 s), o cierra si no hubo habla en
   `no_speech_timeout_s` (6 s).
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
hablar mueve boca, ojos y cejas, y abriría Inicio, haría clicks o scroll. El
gesto de pausa (ambas cejas) **cancela el dictado** en lugar de pausar. F8 y
"Detener control" también lo cancelan, y no se escribe nada después.

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

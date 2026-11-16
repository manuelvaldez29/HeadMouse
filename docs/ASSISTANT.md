# Gema, la asistente de voz de CONFA (etapa 1, 2026-11-11)

**Gema** (con una m: `app_paths.ASSISTANT_NAME`) es la asistente de voz de CONFA,
nombre elegido por el equipo el 2026-11-13. En la app se presenta así: mientras
escucha muestra «Gema te escucha…» y firma cada respuesta («Gema: abriendo Bloc de
notas.»). Las respuestas están en primera persona («No encontré…», «No entendí…»);
`assistant.as_gema` las pone en minúscula después de los dos puntos sin tocar siglas
ni marcas (CONFA, WhatsApp). También se la llama diciendo «Oye Gema» (abajo).

Comandos dichos en español para manejar Windows, sin IA generativa: todo corre en
la PC, sin Internet ni costo. Se activa con la acción **Hablar con Gema**, que se
asigna a un gesto en "Gestos y acciones". Para escuchar reutiliza el dictado:
micrófono, detector de voz, huella de voz, aviso flotante, el gesto de click para
terminar y el gesto de pausa para cancelar. Por eso el dictado por voz tiene que
estar activado.

## Comandos

La lista sale de `assistant.ASSISTANT_COMMANDS` (la misma que se ve en la ayuda de
"Gestos y acciones"), y un test verifica que cada ejemplo se entienda.

| Se dice | Hace |
|---|---|
| «abrir Bloc de notas» · «abrí WhatsApp» · «abrime el navegador» | abre un programa del menú Inicio |
| «buscar recetas de empanadas» | busca en Google con el navegador |
| «cerrar ventana» | Alt+F4 en la ventana de adelante (nunca en CONFA) |
| «minimizar» · «maximizar» · «mostrar escritorio» · «cambiar de ventana» | ventanas |
| «subir volumen» · «bajar volumen» · «silenciar» | volumen (5 teclas, ~10 %) |
| «pausa» · «siguiente canción» · «anterior» | teclas multimedia |
| «captura de pantalla» | recorte de pantalla (Win+Shift+S) |
| «escribir …» | escribe el texto donde está el cursor |
| «qué hora es» | muestra la hora |

- Se aceptan formas rioplatenses y cortesía: «che», «abrime», «por favor».
- Lo que no coincide con un comando no hace nada: se muestra «No entendí…».
- "Poné" no es sinónimo de abrir, porque «poné pausa» buscaría un programa
  llamado "pausa".

## Programas

`AppIndex` lee el menú Inicio con `Get-StartApps` (unos 1,5 s, en segundo plano al
iniciar el control). Incluye las apps de la Microsoft Store (WhatsApp, Spotify) y las
abre con `explorer.exe shell:AppsFolder\<AppID>`.

- La búsqueda es aproximada: «watsap» encuentra WhatsApp, y «blog de notas» (como lo
  escribió Whisper) encuentra el Bloc de notas.
- Hay alias para nombres genéricos: navegador, internet, correo, archivos, notas,
  música, ajustes.
- **Los desinstaladores, instaladores y páginas de ayuda quedan fuera del índice**:
  una coincidencia aproximada nunca puede abrir «Desinstalar Java».

## Seguridad

- Solo se ejecutan las acciones de la lista. El texto dicho nunca se ejecuta como
  comando.
- Un programa se abre únicamente si está en el menú Inicio.
- Ni el log ni las métricas guardan lo dicho: solo si hubo acción.

## Verificación

- Tests en `tests/test_assistant.py`: reconocedor, índice, ejecutor, modo asistente
  del dictado y acción del control.
- Prueba de punta a punta sin abrir nada: 10 comandos dichos por la voz sintética
  de Windows, transcriptos con Whisper `small` y pasados por el índice real.
  9 de 10 se ejecutaron, en 2,2 a 3,2 s cada uno.
- Falló «escribir hola»: la voz sintética pega las palabras y Whisper escribió
  «escribirola». Con una persona, una pausa breve después de «escribir» lo evita.

## Pendiente

- Frase de activación ("Oye …") con openWakeWord.
- Opcional: pedidos libres con IA en la nube, mediante una lista cerrada de
  herramientas.

## «Oye Gema» (2026-11-15)

Opcional y apagado por defecto (`voice.wake_word`, Configuración → Dictado por voz):
es un micrófono abierto y lo elige el usuario. Código en `wake_word.py`, conectado al
dictado en `Dictation.wake_allowed` / `wake_heard`.

**Cuándo escucha.** Sólo con el control activo, sin pausa, sin F8 y sin otro dictado o
pedido en curso (`_dictation_allowed` + `Dictation.busy`). Fuera de eso cierra el
micrófono. La línea de estado avisa «Decí «Oye Gema» para hablarle a Gema».

**Cómo decide, de lo barato a lo caro.**

1. Silero VAD corta frases: pausa de 0,7 s, entre 0,35 y 6 s de voz. Con 0,45 s la
   pausa natural después de «Oye Gema,» partía la frase y el pedido se perdía.
2. Whisper chico: `base` si está instalado (lo trae el instalador), con un contexto de
   ejemplo (`WAKE_PROMPT`: «Oye Gema, abrí el bloc de notas. Oye Gema, ¿qué hora es?»).
3. `find_wake` compara por sonido (`sound_key`): h muda; g/c ante e/i, j, k, qu, ll e y
   son una sola letra (el «oye» rioplatense salió «Hoje»); letras dobles cuentan una,
   también entre dos palabras («Hoy llegé a ma»). «Hoy es» / «Hoy e» al principio se
   leen como «oye» (`OYE_HEARD_AS`). El fragmento tiene que empezar y terminar en borde
   de palabra («oye, gemelos» y «yo y Gema» no pasan).

**Sin huella de voz.** Se probó y se sacó: en frases de ~1 s la huella de Manu marcó
0,44–0,73 y voces sintéticas de otra persona 0,39–0,60. Rechazaba al usuario (2/24) y
dejaba pasar a otros. Cualquiera que diga «Oye Gema» la activa; el manual lo dice.

**Después de «Oye Gema».**

- Con pedido en la misma frase: si es simple (volumen, hora, ventanas, música, mouse)
  se hace con lo que entendió `base`. Si es `open`, `search` o `type` (`PRECISE_KINDS`)
  la frase se vuelve a transcribir con el modelo del dictado.
- Sin pedido: Gema escucha como con el gesto, empezando por el audio que llegó
  mientras se revisaba la frase, para no perder el comienzo si el usuario siguió hablando.
- Las métricas cuentan `assistant_oye_gema` / `assistant_unknown_oye_gema` aparte.

**Mediciones** (voces sintéticas de Windows, 36 frases a tres velocidades, esta PC):

| Modelo | Por frase | Comentario |
|---|---|---|
| tiny | ~0,45 s | escribe «hoy e gema», «oye quema» |
| base | ~0,85 s | 15/15 activaciones, 0/21 sin querer con frases parecidas |
| small | ~2,7 s | casi perfecto, demasiado lento para escuchar todo el tiempo |

- Cadena completa: pedidos simples en menos de 1 s después de hablar; abrir, buscar y
  escribir en unos 3 s.
- Escucha en silencio: 3,4 % de un núcleo.
- Límites conocidos: «Oye, Emma» suena igual que «Oye Hema» y activa a Gema. Cualquier
  voz puede activarla, y la tele hablando hace trabajar a Whisper.
- Voz de Manu (2026-11-16). Primera prueba: 3/6. Segunda, 24 frases grabadas: 8/12 con
  la versión anterior. Fallaban el «oye» rioplatense, que base escribe «Hoy es», y la
  huella. Con «Hoy es» leído como «oye», sin huella y con `WAKE_PROMPT`: 12/12 y 0/12
  sin querer sobre esas mismas grabaciones.

| Whisper base sobre las 24 frases de Manu | Activaciones | Sin querer |
|---|---|---|
| «Gema» como hotword | 10/12 | 0/12 |
| `WAKE_PROMPT` | 12/12 | 0/12 |
| «Oye, Gema» como hotword | 4/12 | 0/12 |

- Charla y noticiero sintéticos (20 frases con «oye», «hoy es jueves», «la gema más
  grande…», «oye, gemelos») y ruido blanco y rosa: 0 activaciones. Con el contexto de
  ejemplo, Whisper no inventó «Oye Gema».
- El log anota en INFO las frases que casi fueron «Oye Gema» (parecido ≥ 0,7), sin el texto.
- Falta medir con más voces reales y ruido: `python tools/banco_oye_gema.py --microfono`
  (guion de frases) y `--libre 120` (activaciones sin querer con la tele o una charla).


# Asistente de voz (etapa 1, 2026-11-11)

Comandos dichos en español para manejar Windows, sin IA generativa: todo corre en
la PC, sin Internet ni costo. Se activa con la acción **Asistente de voz**, que se
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
| «cerrar ventana» | Alt+F4 en la ventana de adelante (nunca en HeadMouse) |
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

# Gestos y acciones

`GestureEngine` reconoce gestos. `ActionMapping` convierte su identidad en una acción permitida y `ControlEngine` ejecuta la acción si las condiciones de seguridad lo permiten. La interfaz solamente edita las asociaciones.

| Identidad | Gesto | Acción predeterminada |
|---|---|---|
| LEFT_WINK | Guiño izquierdo | LEFT_CLICK |
| RIGHT_WINK | Guiño derecho | RIGHT_CLICK |
| LEFT_BROW | Ceja izquierda | SCROLL_UP |
| RIGHT_BROW | Ceja derecha | SCROLL_DOWN |
| BOTH_BROWS | Ambas cejas | PAUSE |
| MOUTH_OPEN | Boca abierta | OPEN_START_MENU |

Las once acciones disponibles son `LEFT_CLICK`, `RIGHT_CLICK`, `DOUBLE_CLICK`, `SCROLL_UP`, `SCROLL_DOWN`, `PAUSE`, `KEY_ENTER`, `KEY_ESCAPE`, `KEY_SPACE`, `OPEN_START_MENU` y `NONE`. No se admiten macros, comandos de shell ni nombres arbitrarios.

Desde **Gestos y acciones**, elegí una acción para cada uno de los seis gestos y guardá. Las asociaciones se persisten en `settings.actions.bindings` del perfil, usando la misma configuración que los motores. Un perfil anterior sin esa sección recibe los defaults. `NONE` conserva la detección y omite la acción del sistema.

`GestureEvent.gesture` contiene la identidad. Por compatibilidad con los consumidores v0.2 y la validación, `GestureEvent.type` emitido por el detector conserva los nombres anteriores; `ActionMapping.resolve` devuelve un evento nuevo con el tipo de acción elegido. `CURSOR_MOVE` pasa sin remapeo. La calibración reconoce gestos independientemente de la acción elegida.

La acción `PAUSE` tiene prioridad sobre las otras acciones del mismo ciclo. Un gesto asignado a pausa puede alternarla también cuando el motor está pausado. Cambiar la asociación de ambas cejas cambia esa vía de pausa; el botón Detener y los atajos locales F8/Escape siguen disponibles. La activación inicial continúa requiriendo confirmación explícita.

El doble clic usa el backend PyAutoGUI; las teclas usan su operación `press`. Abrir Inicio envía la tecla Windows. Estas acciones se prueban con un backend simulado, sin enviar entradas reales. El dashboard cuenta acciones de clic ejecutadas: un doble clic equivale a una acción de doble clic, no a dos detecciones de gesto.

Las duraciones de hold, cooldown, supresión de parpadeo bilateral y prioridad de ambas cejas pertenecen al detector. Cambiar el mapeo no cambia esos criterios. Cambiar los tiempos de reconocimiento desde Configuración invalida la validación anterior y requiere volver a validar.

# Pilotaje físico pendiente — fuentes oculares

No hay resultados físicos nuevos en esta entrega. El joystick relativo había
funcionado antes según informó el usuario; eso no valida automáticamente las
fuentes nuevas, el modelo absoluto ni el cierre.

Abrir desde el repositorio, con mouse físico disponible para detener:

```powershell
.\.venv\Scripts\python.exe -X faulthandler -u app.py
```

Registrar PC/webcam, índice y resolución de captura, FPS, monitor y resolución,
DPI, luz, distancia en cm, postura, anteojos si corresponde, rama/HEAD y fecha.
Guardar los resultados de este documento en una copia local bajo `data/experiments/`.
No sobrescribir perfiles históricos para hacer pruebas: crear un perfil de pilotaje.

## Confirmar I/D primero, sin control real

1. Abrir cámara/Diagnóstico. Elegir Ojos relativos y Ambos ojos; guardar.
2. Las letras **I/D representan tus lados físicos**, no los del observador.
   Guiñar brevemente el izquierdo y comprobar que corresponde a I y al indicador
   de iris izquierdo. Repetir con el derecho. Un guiño no garantiza que MediaPipe
   deje de estimar su iris; observar también párpados y gesto detectado.
3. Si hay dudas, ocultar temporalmente un ojo de forma cómoda sin tocar la cámara
   ni alterar la postura; registrar lo observado. No inferir ausencia real si el
   modelo sigue estimando landmarks. Si I/D se invierten, detener el pilotaje y
   reportar cuál ojo físico correspondió a cada etiqueta antes de recalibrar.
4. Elegir Izquierdo: solo I debe resaltarse. Elegir Derecho: solo D. Ambos debe
   resaltar los dos. Para operar normalmente podés mantener ambos ojos abiertos.

## Matriz mínima

Todos los estados siguientes son **PENDIENTES**. Anotar aprobado/fallo, condiciones,
error real y observaciones; no completar con resultados de tests sintéticos.

| Método | Fuente | Calibración | Diagnóstico/control/gestos/cierre |
|---|---|---|---|
| Nariz | No aplica | Facial | Pendiente |
| Ojos relativos | Ambos ojos | Neutral + 5 rangos | Pendiente |
| Ojos relativos | Izquierdo | Neutral + 5 rangos propios | Pendiente |
| Ojos relativos | Derecho | Neutral + 5 rangos propios | Pendiente |
| Ojos absolutos | Ambos ojos | 9 + 5 validaciones | Pendiente |
| Ojos absolutos | Izquierdo | 9 + 5 propias | Pendiente |
| Ojos absolutos | Derecho | 9 + 5 propias | Pendiente |

Para cada fila ocular, elegir método/fuente y **Guardar configuración** antes de
calibrar. Verificar que la captura anuncia la fuente elegida. Primero probar
diagnóstico, recién después confirmar Activar control. Absoluto requiere una sola
pantalla primaria. Anotar tiempo/reintentos, error X/Y/euclidiano por zona,
peor zona, jitter y rechazos; las métricas quedan locales. Si no aprueba, repetir
sin presentar ese intento como éxito o volver al joystick.

## Casos por fila

- Neutral quieto y direcciones: derecha/izquierda/arriba/abajo; absoluto también
  centro y zonas grandes. Registrar signo incorrecto, deriva o movimientos bruscos.
- Binocular: perder un iris debe detener movimiento y mostrar señal incompleta.
  No debe aparecer un cambio automático de fuente.
- Monocular: el otro iris puede faltar sin impedir seguimiento. Perder el elegido
  debe detener movimiento. Al recuperar, debe esperar estabilidad y evitar salto.
- Guiñar cada ojo: se conserva su acción configurada y el cursor se protege.
  El ojo elegido cerrado debe bloquear hasta recuperarlo. Un guiño del otro puede
  provocar una guarda breve; su ausencia sostenida no debe bloquear permanentemente.
- Probar cejas, ambas cejas, boca, clic/doble clic, scroll y pausa con los mapeos
  del perfil. Cambiar una acción ocular y verificar que no modifica la nasal.
- Cambiar fuente y volver: debe recuperar su calibración anterior. Una fuente
  nunca calibrada debe permitir diagnóstico y exigir calibrar para control.
- Cambiar método y volver a nariz: conservar sensibilidad, calibración y acciones.
- Probar Detener/F8/Escape con foco, pérdida/retorno de rostro, desconectar cámara,
  cerrar durante preview, calibración, control y guiño. Nunca desactivar failsafe.
- Cambiar DPI/resolución/cámara: debe exigir calibración compatible; identificar
  cuándo la condición es desconocida por tratarse de un perfil relativo antiguo.

Hacer primero un ciclo de cada caso. Antes de aprobar distribución, realizar
sesiones más largas y ciclos repetidos de abrir/cerrar y cambiar método, registrando
cantidad y duración reales. Los atajos requieren foco de HeadMouse; no son hooks
globales. Una llamada nativa ya en curso no es cancelable retroactivamente.

## Formato de devolución

Registrar para cada caso: método, fuente, qué hiciste, esperado, observado,
aprobado/fallo, tiempo, errores medidos y ruta del registro. Si se cierra, conservar
`data/logs/headmouse.log` y `fault-*.log`, con hora y último paso realizado. No
hace falta grabar cara/video. Anotar también cierres sin stack o logs vacíos.

La aprobación física y la autorización de integración son pasos distintos.
No integrar ramas ni preparar una release definitiva hasta completar ambos.

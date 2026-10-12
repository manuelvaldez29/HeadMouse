# Estudio de señales de cejas frente a la pose

## Problema

La señal GEOMETRIC mide la distancia vertical entre ceja y comisura del ojo
en la imagen, dividida por la distancia horizontal entre orejas. Las cejas
están por delante de las comisuras, así que al inclinar la cabeza esa distancia
proyectada cambia. Además, mucha gente levanta un poco las cejas al mirar hacia
arriba. En la sesión del 2026-10-11 hubo 20 detecciones de "ambas cejas" en
7 minutos (16 pausas ejecutadas) al subir el cursor con la cámara por debajo de
la cara. `brow_motion_gate` lo evita bloqueando las cejas mientras el cursor se
mueve. Este estudio busca una señal que no dependa de la pose.

## Señales comparadas

| Fuente | Cálculo |
|---|---|
| GEOMETRIC | Predeterminada. 2D, `face_geometry.brow_lift_2d`. |
| BLENDSHAPE | Puntajes de MediaPipe: `(browOuterUp + browInnerUp − browDown) / 2`. |
| HYBRID | Promedio de GEOMETRIC escalada y BLENDSHAPE. |
| GEOMETRIC_3D | Nueva, experimental. Ceja menos centro del ojo, proyectada sobre el eje vertical de la propia cara (tabique nasal, ortogonal a la línea entre comisuras) y dividida por la distancia interocular 3D. Usa la profundidad `z` de los landmarks. |

GEOMETRIC_3D no necesita referencia ni convenciones de la cámara: los ejes se
construyen con puntos rígidos de la cara. Con una cara sintética, la señal no
cambia ante pitch, yaw, roll ni distancia, mientras que GEOMETRIC se desplaza
cerca de la mitad de la amplitud del gesto cada 10° de pitch
(`tests/test_face_geometry.py`). Con landmarks reales, la `z` de MediaPipe es
una estimación y su error se mide en este estudio.

`FaceData` también registra `head_pitch`, `head_yaw` y `head_roll`
(aproximados, relativos al reposo). Por ahora solo se usan en el estudio.

## Protocolo

```powershell
python brow_study.py
```

Son dos rondas de nueve posturas, unos 2 minutos en total: neutral, mirar
arriba, abajo, izquierda y derecha **sin mover las cejas**; levantar ambas
cejas, solo la izquierda y solo la derecha; mirar arriba levantando ambas. Cada
postura tiene 2 s de preparación (no se analizan) y 4–5 s de captura. Se
guarda un JSONL por frame en `data/experiments/brow_study_<id>.jsonl` con nariz,
pose, las señales geométricas y los blendshapes de cejas. No se guardan
imágenes ni landmarks completos. Al terminar se imprime el informe y se guarda
como `..._report.md`. Para volver a analizar una captura:
`python brow_study.py --analyze data/experiments/brow_study_<id>.jsonl`.

## Métricas

Todas son relativas a la amplitud del gesto de cada señal, así que fuentes con
escalas distintas se pueden comparar.

- **AUC vs. mirar arriba**: probabilidad de que un frame con cejas levantadas
  supere a uno mirando arriba sin levantarlas. Es la métrica principal: 1 separa
  perfecto, 0.5 es azar.
- **Falsos al mirar arriba / en pose**: fracción de frames sin cejas
  levantadas que superan el umbral que detecta el 95 % de los frames levantados.
- **Desplazamiento al mirar arriba**: cuánto se mueve la mediana al mirar
  arriba, en porcentaje de la amplitud (100 % equivale a levantar las cejas).
- **Por cada 10° de pitch**: pendiente de la señal frente al pitch en los
  frames sin gesto.
- **Detecta arriba + cejas**: si el gesto se reconoce también con la cabeza
  inclinada. Es informativo, porque `brow_motion_gate` igual lo bloquea.

El orden final usa la peor de las dos cejas. Una señal solo sirve si separa
ambas.

## Criterio de decisión

Cambiar la fuente predeterminada solo si, en varias personas y posiciones de
cámara (en la cama y en un escritorio), la nueva supera a GEOMETRIC en AUC vs.
mirar arriba en ambas cejas sin perder amplitud útil, y si después se calibra y
valida con ella. Una sola captura alcanza para elegir qué probar, no para
afirmar una mejora en la tesis. Si GEOMETRIC_3D o BLENDSHAPE ganan, se pueden
elegir hoy en Calibración, en "Gestos disponibles y tipo de señal", y
recalibrar. Con una señal sin dependencia de la pose se podría evaluar
desactivar `brow_motion_gate`, para volver a permitir scroll mientras se mueve
el cursor.

## Primera captura (2026-10-11, n = 1)

Un participante en la cama, con la notebook y la cámara por debajo de la cara.
Fueron 2634 frames a 23 FPS, 1825 de ellos analizados, con pitch de +36° al
mirar arriba, −29° al mirar abajo y yaw de ±40°. Los valores ya usan la
lateralidad corregida de blendshapes (ver abajo).

| Fuente | AUC vs. mirar arriba (izq. / der.) | Falsos al mirar arriba | Desplazamiento al mirar arriba |
|---|---|---|---|
| GEOMETRIC | 0.53 / 0.26 | 82 % / 85 % | 84 % / 104 % |
| BLENDSHAPE | 0.87 / 0.88 | 81 % / 33 % | 27 % / 36 % |
| HYBRID | 0.80 / 0.61 | 81 % / 80 % | 45 % / 55 % |
| **GEOMETRIC_3D** | **0.96 / 0.96** | **20 % / 9 %** | 30 % / 43 % |

Lectura:

- Con GEOMETRIC, mirar arriba equivale a levantar las cejas (84–104 % de la
  amplitud), y mirar abajo da −105 a −145 %. Esto confirma el mecanismo de las
  pausas involuntarias.
- GEOMETRIC_3D elimina casi toda la dependencia lineal del pitch (2–6 % de la
  amplitud cada 10°). El desplazamiento que queda al mirar arriba (30–43 %)
  coincide con el de BLENDSHAPE (27–36 %), que no usa geometría. Lo más
  probable es que sea una elevación real de las cejas al mirar hacia arriba
  (frontal) y no un error de medición. Ninguna señal de la imagen puede
  separarla, así que `brow_motion_gate` sigue siendo necesario.
- Al girar la cabeza (yaw de ±40°), GEOMETRIC_3D baja la ceja más alejada de
  la cámara (−59 a −61 %), probablemente por error de la `z` estimada en el lado
  que se ve de costado. Va en la dirección opuesta a un falso positivo, pero
  puede impedir detectar una elevación con la cabeza girada. Mirar abajo da
  +7 a +26 %.
- Levantando cejas con la cabeza hacia arriba, GEOMETRIC_3D sigue en
  91–99 %. Las demás superan 130 %, porque suman el artefacto de la pose.

**Bug encontrado:** la fuente BLENDSHAPE tenía la lateralidad invertida.
VisionEngine espeja el frame antes de inferir, así que para MediaPipe la ceja
izquierda del usuario es "Right". Al levantar la ceja izquierda, el canal
"left" respondía 2 % y el "right" 44 %. Quedó corregido en
`gesture_signals.brow_signal`. Los perfiles calibrados con BLENDSHAPE o HYBRID
antes de esta corrección tienen que recalibrarse. El informe ahora avisa
"Lateralidad invertida" si vuelve a pasar.

Decisión provisoria: usar GEOMETRIC_3D para este participante (se elige en
Calibración y se recalibra) y mantener `brow_motion_gate`. Antes de cambiar la
fuente predeterminada, repetir el estudio con más participantes y con la cámara
a la altura de los ojos.

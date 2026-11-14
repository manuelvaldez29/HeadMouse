"""Zona de mando del joystick ocular: toda la pantalla.

Se mira hacia un borde para mover el puntero hacia ese lado; el centro amplio lo deja quieto.
Un recuadro chico en una esquina daba un recorrido del iris de alrededor de un píxel en una
webcam 640×480 y no alcanzaba para distinguir las zonas entre sí ni del resto de la pantalla.
"""


def pad_rect(screen):
    """[x, y, ancho, alto] lógico del monitor del contexto dado."""
    display = screen.get("display")
    if display:
        return list(display["logical_rect"])
    (x, y), dpr = screen["origin"], screen["dpr"]
    return [x, y, round(screen["width"] / dpr), round(screen["height"] / dpr)]

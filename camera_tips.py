"""Consejos simples sobre cámara, luz y distancia antes de calibrar los ojos.

Muchos fallos en otras PCs vienen de la cámara o la luz y no de la persona. Esto mira el
último cuadro y la cara detectada y devuelve frases cortas para corregirlo. Solo avisa: no
bloquea la calibración. Los límites son aproximados y conservadores.
"""

FACE_SMALL, FACE_LARGE = .17, .42   # ancho relativo de la cara (calibraciones reales: ~0,25)
DARK, BRIGHT = 55, 210              # brillo medio 0–255
BACKLIGHT = 45                      # los bordes del cuadro más claros que el centro
MIN_FPS = 12


def camera_tips(face, frame, fps):
    tips = []
    if face is None or not getattr(face, "detected", False):
        return ["No se ve tu cara: ubicate de frente a la cámara."]
    scale = getattr(face, "face_scale", None)
    if scale is not None and scale < FACE_SMALL:
        tips.append("Estás lejos de la cámara: acercate un poco.")
    elif scale is not None and scale > FACE_LARGE:
        tips.append("Estás muy cerca de la cámara: alejate un poco.")
    if frame is not None and getattr(frame, "size", 0):
        small = frame[::8, ::8]
        gray = small.mean(axis=2) if small.ndim == 3 else small
        mean = float(gray.mean())
        if mean < DARK:
            tips.append("Falta luz: prendé una luz de frente o al costado de la pantalla.")
        elif mean > BRIGHT:
            tips.append("Hay demasiada luz en la imagen: bajá el brillo o corré la lámpara.")
        h, w = gray.shape[:2]
        center = float(gray[h // 4:3 * h // 4, w // 4:3 * w // 4].mean())
        border = (float(gray.mean()) * gray.size - center * (gray[h // 4:3 * h // 4, w // 4:3 * w // 4].size)) / max(
            1, gray.size - gray[h // 4:3 * h // 4, w // 4:3 * w // 4].size)
        if border - center > BACKLIGHT:
            tips.append("La luz te da de atrás (ventana o lámpara): ponela adelante tuyo.")
    if fps and fps < MIN_FPS:
        tips.append(f"La cámara entrega pocos cuadros ({fps:.0f} por segundo): cerrá otros programas que la usen o probá con más luz.")
    return tips

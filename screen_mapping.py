"""Monitor primario: geometría lógica Qt y píxeles físicos Windows separados.

No mueve el cursor. Nunca multiplica el origen lógico por el DPR.
"""
from contextlib import contextmanager
import math
import os


def capture_host_id():
    """Huella local de entorno, sin persistir el nombre del equipo en claro."""
    import hashlib
    import platform
    return hashlib.sha256((platform.system()+":"+platform.node()).encode("utf-8")).hexdigest()


@contextmanager
def physical_coordinates():
    if os.name != "nt":
        yield
        return
    import ctypes
    api = ctypes.WinDLL("user32", use_last_error=True)
    setter = api.SetThreadDpiAwarenessContext
    setter.argtypes, setter.restype = [ctypes.c_void_p], ctypes.c_void_p
    previous = setter(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    if not previous:
        raise ValueError("Windows no permite verificar coordenadas físicas. Revisá el escalado de pantalla y reiniciá HeadMouse.")
    try:
        yield
    finally:
        setter(previous)


def windows_monitors():
    import ctypes
    from ctypes import wintypes
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD), ("device", wintypes.WCHAR*32)]
    api = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    api.GetMonitorInfoW.restype = wintypes.BOOL
    api.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM]
    api.EnumDisplayMonitors.restype = wintypes.BOOL
    monitors, errors = [], []
    def visit(handle, dc, rect, data):
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if not api.GetMonitorInfoW(handle, ctypes.byref(info)):
            errors.append("No se pudo consultar un monitor")
            return False
        r = info.monitor
        monitors.append(dict(screen=info.device, primary=bool(info.flags & 1),
                             rect=[r.left, r.top, r.right-r.left, r.bottom-r.top]))
        return True
    with physical_coordinates():
        if not api.EnumDisplayMonitors(None, None, callback_type(visit), 0) or errors:
            raise ValueError("No se pudo verificar la pantalla principal de Windows. Revisá Configuración de pantalla.")
    return monitors


def primary_context(qt, monitors=None):
    """Qt: screen, rect lógico, dpr y cantidad; nativo: lista de rect físicos."""
    rect, dpr = qt["rect"], qt["dpr"]
    if (len(rect) != 4 or any(type(v) is not int for v in rect) or
        rect[2] < 2 or rect[3] < 2 or not math.isfinite(dpr) or dpr <= 0):
        raise ValueError("Geometría de pantalla inválida")
    width, height = round(rect[2]*dpr), round(rect[3]*dpr)
    context = dict(width=width, height=height, dpr=dpr, screen=qt["screen"],
                   monitor_count=qt["monitor_count"], origin=rect[:2])
    if monitors is None:
        if qt["monitor_count"] != 1 or rect[:2] != [0, 0]:
            raise ValueError("No se pudo verificar la transformación al monitor principal. Usá una sola pantalla o revisá su escalado.")
        return context  # Compatibilidad con entorno único/fixtures sin Win32.
    primary = [m for m in monitors if m["primary"]]
    # Qt reciente expone nombres amigables (p.ej. modelo del monitor), Win32
    # expone DISPLAY1. Corroborar la selección primaria de ambas APIs y tamaño;
    # no confundir nombres pertenecientes a espacios de identidad distintos.
    if len(primary) != 1 or qt.get("primary") is not True or len(monitors) != qt["monitor_count"]:
        raise ValueError("Qt y Windows no identifican el mismo monitor principal. Revisá cuál está marcado como principal y reiniciá HeadMouse.")
    native = primary[0]["rect"]
    if len(native) != 4 or any(type(v) is not int for v in native) or any(abs(a-b) > 1 for a,b in zip(native[2:], (width,height))):
        raise ValueError("El tamaño físico de Windows no coincide con el escalado Qt. Revisá el escalado/DPI y reiniciá HeadMouse.")
    context.update(width=native[2], height=native[3], display=dict(
        version=1, physical_rect=list(native), logical_rect=list(rect), device=primary[0]["screen"]))
    return context


def screen_display(context):
    """Extraer una transformación validada; compatibilidad legacy sólo en origen cero."""
    display = context.get("display")
    if display is not None:
        if (not isinstance(display, dict) or display.get("version") != 1 or
            not isinstance(display.get("device"),str) or not display["device"]):
            raise ValueError("Transformación de pantalla incompatible")
        rect, logical = display.get("physical_rect"), display.get("logical_rect")
        if (not isinstance(rect,list) or len(rect)!=4 or any(type(v) is not int for v in rect) or
            rect[2:] != [context["width"],context["height"]] or
            not isinstance(logical,list) or len(logical)!=4 or any(type(v) is not int for v in logical) or
            any(abs(round(logical[i+2]*context["dpr"])-rect[i+2])>1 for i in (0,1))):
            raise ValueError("Transformación lógica/física de pantalla inválida")
        return display
    if context.get("monitor_count",1)!=1 or context.get("origin",[0,0]) != [0,0]:
        raise ValueError("Falta verificar la transformación física del monitor principal")
    return dict(version=1, device=context["screen"],physical_rect=[0,0,context["width"],context["height"]],
                logical_rect=[0,0,round(context["width"]/context["dpr"]),round(context["height"]/context["dpr"])])


def same_context(saved, current):
    keys=("width","height","dpr","screen","camera_index","frame_width","frame_height", "capture_host")
    if any(saved.get(k)!=current.get(k) for k in keys):
        return False
    # Los modelos antiguos se capturaron obligatoriamente en origen cero.
    if "display" not in saved:
        return screen_display(current)["physical_rect"][:2] == [0,0]
    return saved["display"] == screen_display(current)


def target_in_viewport(target, context, origin, dpr):
    """Destino físico del modelo → posición local del overlay Qt, incluido su origen."""
    display = screen_display(context)
    logical = display["logical_rect"]
    if not math.isclose(dpr,context["dpr"],rel_tol=0,abs_tol=.001):
        raise ValueError("Cambió el DPI del overlay: reiniciá la calibración")
    return (logical[0]+target[0]*(context["width"]-1)/dpr-origin[0],
            logical[1]+target[1]*(context["height"]-1)/dpr-origin[1])

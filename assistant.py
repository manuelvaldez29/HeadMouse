"""Asistente de voz, etapa 1: comandos en español sin IA generativa. Sin Qt ni micrófono.

Se activa con la acción ASSISTANT (un gesto) y reutiliza el dictado para escuchar:
micrófono, detector de voz, huella de voz, aviso flotante, guiño para terminar y
gesto de pausa para cancelar. Lo que se transcribe se interpreta acá y solo puede
terminar en una acción de una lista cerrada: nunca se ejecuta texto como comando.

Los programas salen del menú Inicio (Get-StartApps), incluidas las apps de la Store,
y se abren con explorer.exe shell:AppsFolder\\<id>. Los desinstaladores y las páginas
de ayuda quedan afuera del índice: con coincidencia aproximada, "abrir Java" no puede
terminar en "Desinstalar Java".
"""
import json
import logging
import re
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Lo que se muestra en la ayuda (Gestos y acciones) y verifican los tests.
ASSISTANT_COMMANDS = (
    ("«abrir Bloc de notas» · «abrí WhatsApp»", "abre un programa del menú Inicio", "Abrí el bloc de notas."),
    ("«buscar recetas de empanadas»", "busca en Google con el navegador", "Buscar recetas de empanadas."),
    ("«cerrar ventana»", "cierra la ventana de adelante", "Cerrar ventana."),
    ("«minimizar» · «maximizar»", "achica o agranda la ventana de adelante", "Minimizar."),
    ("«mostrar escritorio» · «cambiar de ventana»", "escritorio o siguiente ventana", "Cambiar de ventana."),
    ("«subir volumen» · «bajar volumen» · «silenciar»", "volumen del sistema", "Subí el volumen."),
    ("«pausa» · «siguiente canción»", "música y videos", "Siguiente canción."),
    ("«captura de pantalla»", "abre el recorte de pantalla", "Captura de pantalla."),
    ("«escribir hola qué tal»", "escribe el texto donde está el cursor", "Escribir hola qué tal."),
    ("«qué hora es»", "muestra la hora", "¿Qué hora es?"),
)

EXCLUDED = ("desinstal", "uninstall", "setup", "install", "readme", "leame", "license", "licencia",
            "release notes", "notas de la version", "documentation", "documentacion")
ALIASES = {
    "navegador": ("google chrome", "microsoft edge", "firefox"),
    "internet": ("google chrome", "microsoft edge", "firefox"),
    "chrome": ("google chrome",),
    "edge": ("microsoft edge",),
    "correo": ("outlook", "correo", "gmail"),
    "mail": ("outlook", "correo", "gmail"),
    "archivos": ("explorador de archivos",),
    "mis archivos": ("explorador de archivos",),
    "carpetas": ("explorador de archivos",),
    "explorador": ("explorador de archivos",),
    "notas": ("bloc de notas",),
    "musica": ("spotify",),
    "ajustes": ("configuracion",),
}


def normalize(text):
    """Minúsculas, sin tildes (salvo la ñ), sin puntuación ni espacios repetidos."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn" or c == "̃")
    text = unicodedata.normalize("NFC", text)
    return " ".join(re.sub(r"[^\wñ ]+", " ", text).split())


@dataclass(frozen=True)
class Command:
    kind: str
    argument: str = ""


ARTICLES = ("el ", "la ", "los ", "las ", "un ", "una ", "mi ", "programa ", "aplicacion ", "app ")
PATTERNS = (  # (regex sobre texto normalizado, tipo, grupo con el argumento)
    # Sin "poné": "poné pausa" buscaría un programa llamado "pausa".
    (r"^(?:abri|abrir|abre|abrime|abrilo|ejecuta|ejecutar|ejecutame|inicia|iniciar|lanza|lanzar)(?: (.+))?$", "open"),
    (r"^(?:busca|buscar|buscame|googlea|googlear)(?: en (?:google|internet))? (.+?)(?: en (?:google|internet))?$", "search"),
    (r"^(?:cerra|cerrar|cierra)(?: (?:la |el |esta |este )?(?:ventana|programa|esto|aplicacion))?$", "close"),
    (r"^(?:minimiza|minimizar|achica|achicar)(?: (?:la |esta )?ventana)?$", "minimize"),
    (r"^(?:maximiza|maximizar|agranda|agrandar)(?: (?:la |esta )?ventana)?$", "maximize"),
    (r"^(?:mostrar|mostra|ir al|ver el)? ?escritorio$", "desktop"),
    (r"^(?:cambiar de ventana|cambia de ventana|siguiente ventana|otra ventana)$", "switch"),
    (r"^(?:subi|subir|sube)(?: el)? volumen$|^mas volumen$", "volume_up"),
    (r"^(?:baja|bajar)(?: el)? volumen$|^menos volumen$", "volume_down"),
    (r"^(?:silenciar|silencia|mute|quitar sonido|sacar sonido|activar sonido|poner sonido)$", "mute"),
    (r"^(?:pausa|pausar|reproducir|play|reanudar musica|pausar musica)$", "play_pause"),
    (r"^(?:siguiente|proxima)(?: cancion| tema| video)?$", "next_track"),
    (r"^(?:anterior)(?: cancion| tema| video)?$", "previous_track"),
    (r"^(?:captura|sacar captura|saca una captura|captura de pantalla|hacer captura)(?: de pantalla)?$", "screenshot"),
    (r"^(?:escribi|escribir|escribe) (.+)$", "type"),
    (r"^(?:que hora es|decime la hora|hora)$", "time"),
)


def parse(text):
    """Texto transcripto → Command, o None si no es un comando conocido."""
    plain = normalize(text)
    for prefix in ("che ", "por favor ", "porfa "):
        plain = plain.removeprefix(prefix)
    plain = plain.removesuffix(" por favor").removesuffix(" porfa")
    for pattern, kind in PATTERNS:
        match = re.match(pattern, plain)
        if not match:
            continue
        argument = (match.group(1) if match.groups() else "") or ""
        if kind == "open":
            while argument.startswith(ARTICLES):
                argument = next(argument[len(a):] for a in ARTICLES if argument.startswith(a))
            if not argument:
                return None
        if kind == "type":  # el texto a escribir conserva mayúsculas y tildes del dictado
            spoken = re.sub(r"^\W*\w+[^\w¿¡]*", "", text.strip(), count=1)
            argument = spoken.strip().rstrip(".")
        return Command(kind, argument)
    return None


def load_start_apps():
    """(nombre, AppID) de todo el menú Inicio, apps de la Store incluidas (~1,5 s)."""
    if sys.platform != "win32":
        return []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
                             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                            capture_output=True, timeout=20, creationflags=flags)
    data = json.loads(result.stdout.decode("utf-8") or "[]")
    rows = data if isinstance(data, list) else [data]
    return [(row["Name"], row["AppID"]) for row in rows if row.get("Name") and row.get("AppID")]


class AppIndex:
    """Programas del menú Inicio para buscar por nombre aproximado. Carga en segundo plano."""
    THRESHOLD = .72

    def __init__(self, loader=load_start_apps):
        self._apps, self._ready = [], threading.Event()
        threading.Thread(target=self._load, args=(loader,), name="AppIndex", daemon=True).start()

    def _load(self, loader):
        try:
            self._apps = [(name, app_id, normalize(name)) for name, app_id in loader()
                          if not any(word in normalize(name) for word in EXCLUDED)]
        except Exception:
            logger.warning("No se pudo leer el menú Inicio para el asistente", exc_info=True)
        finally:
            self._ready.set()

    @staticmethod
    def score(query, name):
        if query == name:
            return 1.
        q, n = query.split(), name.split()
        if all(word in n for word in q):
            return .95 - .02 * (len(n) - len(q))
        if name.startswith(query):
            return .9
        return max(SequenceMatcher(None, query, name).ratio(),
                   max((SequenceMatcher(None, query, word).ratio() for word in n), default=0) - .05)

    def find(self, spoken, wait_s=5):
        """(nombre, AppID) del programa más parecido, o None."""
        self._ready.wait(wait_s)
        query = normalize(spoken)
        targets = ALIASES.get(query, (query,))
        best = None
        for rank, target in enumerate(targets):
            for name, app_id, plain in self._apps:
                score = self.score(target, plain) - .01 * rank  # el alias anterior gana los empates
                if score >= self.THRESHOLD and (best is None or (score, -len(plain)) > (best[0], -len(best[3]))):
                    best = (score, name, app_id, plain)
        return (best[1], best[2]) if best else None


def _foreground_is_ours():
    if sys.platform != "win32":
        return False
    import ctypes
    import os
    pid = ctypes.c_ulong()
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


class Assistant:
    """Interpreta lo dicho y ejecuta una acción de la lista. Devuelve (hizo algo, mensaje)."""

    def __init__(self, index=None, keys=None, typer=None, launch=None, browse=None,
                 own_window=_foreground_is_ours, clock=time.localtime):
        self.index = index if index is not None else AppIndex()
        self.keys = keys
        self.typer = typer
        self.launch = launch or (lambda app_id: subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + app_id]))
        self.browse = browse
        self.own_window = own_window
        self.clock = clock

    def _keys(self):
        if self.keys is None:
            import pyautogui
            self.keys = pyautogui
        return self.keys

    def __call__(self, text):
        command = parse(text)
        if command is None:
            return False, (f"No entendí «{text.strip()}». Probá «abrir …», «buscar …» o «cerrar ventana»."
                           if text.strip() else "No se entendió el comando.")
        handler = getattr(self, "_" + command.kind)
        return handler(command.argument)

    def _open(self, name):
        found = self.index.find(name)
        if not found:
            return False, f"No encontré «{name}» en el menú Inicio."
        title, app_id = found
        self.launch(app_id)
        return True, f"Abriendo {title}."

    def _search(self, query):
        from urllib.parse import quote_plus
        url = "https://www.google.com/search?q=" + quote_plus(query)
        if self.browse:
            self.browse(url)
        else:
            import webbrowser
            webbrowser.open(url)
        return True, f"Buscando «{query}»."

    def _close(self, _):
        if self.own_window():
            return False, "HeadMouse no se cierra por voz: usá el botón Salir."
        self._keys().hotkey("alt", "f4", _pause=False)
        return True, "Ventana cerrada."

    def _press(self, keys, message):
        backend = self._keys()
        backend.hotkey(*keys, _pause=False) if len(keys) > 1 else backend.press(keys[0], _pause=False)
        return True, message

    def _minimize(self, _): return self._press(("win", "down"), "Ventana minimizada.")
    def _maximize(self, _): return self._press(("win", "up"), "Ventana maximizada.")
    def _desktop(self, _): return self._press(("win", "d"), "Escritorio.")
    def _switch(self, _): return self._press(("alt", "tab"), "Siguiente ventana.")
    def _mute(self, _): return self._press(("volumemute",), "Sonido silenciado o activado.")
    def _play_pause(self, _): return self._press(("playpause",), "Pausa / reproducir.")
    def _next_track(self, _): return self._press(("nexttrack",), "Siguiente.")
    def _previous_track(self, _): return self._press(("prevtrack",), "Anterior.")
    def _screenshot(self, _): return self._press(("win", "shift", "s"), "Elegí la zona a capturar.")

    def _volume(self, key, message):
        backend = self._keys()
        for _ in range(5):  # cada tecla de volumen mueve 2 %
            backend.press(key, _pause=False)
        return True, message

    def _volume_up(self, _): return self._volume("volumeup", "Volumen más alto.")
    def _volume_down(self, _): return self._volume("volumedown", "Volumen más bajo.")

    def _type(self, text):
        if not text:
            return False, "¿Qué querés que escriba? Decí «escribir» y el texto."
        if self.typer is None:
            return False, "No hay dónde escribir."
        self.typer.type_text(text)
        return True, f"Escrito: {text}"

    def _time(self, _):
        now = self.clock()
        return True, f"Son las {now.tm_hour}:{now.tm_min:02d}."

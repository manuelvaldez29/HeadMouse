"""Preferencias de arranque por usuario, autorización ligada al perfil y registro HKCU."""
from datetime import datetime, timezone
import hashlib
import json
import ntpath
from pathlib import Path
import shlex
import subprocess
import sys
from app_paths import data_root, launch_command
from config import load_config, method_bank
from ocular_profiles import calibration_for
from profiles import gesture_profile
from user_storage import write_json
from screen_mapping import capture_host_id

DEFAULTS=dict(version=1,enabled=False,activate=False,minimized=False,profile_id=None,
              authorization=None,prompted=False,remember_profile=True)


def fingerprint(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()


def prepared(profile):
    c=load_config(overrides=profile.get("settings",{}))
    if c.ui.tracking_method in ("eye_absolute", "eye_joystick"):
        return False  # ambos modos oculares requieren confirmación en cada sesión
    if c.ui.tracking_method=="nose":
        p=gesture_profile(profile,method_bank(c))
        return p.get("status")!="draft" and p.get("validation",{}).get("passed") is True
    r=calibration_for(profile,c.ui.tracking_method,c.ui.eye_source)
    return bool(r and (r.get("validated") if c.ui.tracking_method=="eye_absolute" else
        r.get("vertical_reference","eyelids")==c.eye.vertical_reference and
        (c.eye.vertical_reference!="canthi" or r.get("ranges_measured"))))


class WindowsStartup:
    KEY=r"Software\Microsoft\Windows\CurrentVersion\Run"
    NAME="HeadMouse"
    APPROVAL_KEY=r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"

    def read(self):
        if sys.platform!="win32":return None
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.KEY) as key:return winreg.QueryValueEx(key,self.NAME)[0]
        except FileNotFoundError:return None

    def set(self,command):
        if sys.platform!="win32":
            if command:raise OSError("Inicio con Windows sólo está disponible en Windows")
            return
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,self.KEY) as key:
            if command:
                if len(command)>260:raise ValueError("La ruta de inicio supera 260 caracteres")
                winreg.SetValueEx(key,self.NAME,0,winreg.REG_SZ,command)
            else:
                try:winreg.DeleteValue(key,self.NAME)
                except FileNotFoundError:pass

    def disabled_by_windows(self):
        if sys.platform!="win32":return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,self.APPROVAL_KEY) as key:
                value,kind=winreg.QueryValueEx(key,self.NAME)
        except FileNotFoundError:
            return False
        # Reconocer marcas de deshabilitación sin cambiar la decisión de Windows.
        return kind==winreg.REG_BINARY and value[:1] in (b"\x03",b"\x07")


class StartupPreferences:
    def __init__(self,path=None,registry=None):
        self.path=Path(path) if path else data_root()/"startup.json"
        self.registry=registry if registry is not None else WindowsStartup()

    def registration(self):
        command=self.registry.read()
        if command is None:return "off"
        try:
            args=[ntpath.normcase(arg.strip('"')) for arg in shlex.split(command,posix=False)]
        except (ValueError,AttributeError,TypeError):
            return "other"
        if args!=[ntpath.normcase(arg) for arg in launch_command()]:return "other"
        if getattr(self.registry,"disabled_by_windows",lambda:False)():return "disabled"
        return "on"

    def load(self):
        if not self.path.exists():return dict(DEFAULTS)
        value=json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value,dict) or value.keys()-DEFAULTS.keys():raise ValueError("Preferencias de inicio inválidas")
        p=DEFAULTS|value
        if p["version"]!=1 or any(type(p[k]) is not bool for k in ("enabled","activate","minimized","prompted","remember_profile")):
            raise ValueError("Preferencias de inicio inválidas")
        if p["profile_id"] is not None and not isinstance(p["profile_id"],str):
            raise ValueError("Perfil de inicio inválido")
        if (p["authorization"] is not None and not isinstance(p["authorization"],dict)) or (
                p["activate"] and (not p["enabled"] or p["authorization"] is None)):
            raise ValueError("Activación automática sin autorización")
        return p

    def authorized(self,p,profile):
        a=p.get("authorization") or {}
        return bool(p.get("enabled") and p.get("activate") and p.get("profile_id")==profile.get("user_id") and
                    a.get("explicit") is True and a.get("capture_host")==capture_host_id() and
                    a.get("fingerprint")==fingerprint(profile) and prepared(profile))

    def save(self,enabled,activate,minimized,profile=None,confirmed=False,prompted=True,remember_profile=True):
        if any(type(v) is not bool for v in (enabled,activate,minimized,confirmed,prompted,remember_profile)):
            raise ValueError("Preferencias inválidas")
        if activate and (not enabled or not profile or not prepared(profile)):
            raise ValueError("Activación automática requiere inicio con Windows y un perfil calibrado")
        if activate and not confirmed and not self.authorized(self.load(),profile):
            raise ValueError("Falta autorización explícita de activación automática")
        authorization=None
        if activate:
            authorization=dict(explicit=True,fingerprint=fingerprint(profile),capture_host=capture_host_id(),
                recorded_at=datetime.now(timezone.utc).isoformat())
        p=dict(DEFAULTS,enabled=enabled,activate=activate,minimized=minimized,remember_profile=remember_profile,
               profile_id=profile["user_id"] if profile else None,authorization=authorization,prompted=prompted)
        previous=self.registry.read()
        command=subprocess.list2cmdline(launch_command()) if enabled else None
        try:
            self.registry.set(command)
            write_json(self.path,p)
        except Exception:
            self.registry.set(previous)
            raise
        return p

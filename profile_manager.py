"""Gestión visual de perfiles sin widgets ni segunda fuente de almacenamiento."""
import uuid
from copy import deepcopy
from dataclasses import asdict
from profiles import ProfileStore, validate_profile
from config import load_config


class ProfileManager:
    def __init__(self, store=None):
        self.store = store or ProfileStore()

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80:
            raise ValueError("Ingresá un nombre de entre 1 y 80 caracteres")
        if any(ord(c) < 32 for c in value):
            raise ValueError("El nombre contiene caracteres no permitidos")
        return value.strip()

    @staticmethod
    def status(profile):
        if profile.get("status") == "draft":
            return "Sin calibrar"
        if not profile.get("validation", {}).get("passed", False):
            return "Calibrado · sin validar"
        return "Listo para comenzar"

    def list_profiles(self):
        result = []
        for path in sorted(self.store.directory.glob("*.json")):
            try:
                p = self.store.load(path.stem)
                result.append(dict(user_id=path.stem, display_name=p.get("display_name", path.stem),
                                   status=self.status(p), calibrated_at=p.get("calibrated_at", "—"), error=""))
            except (OSError, ValueError) as exc:
                result.append(dict(user_id=path.stem, display_name=path.stem, status="Necesita reparación",
                                   calibrated_at="—", error=str(exc)))
        return result

    def create(self, name):
        p = dict(user_id="user_" + uuid.uuid4().hex[:12], display_name=self.name(name),
                 status="draft", settings={})
        self.store.save(p)
        return self.store.load(p["user_id"])

    def rename(self, user_id, name):
        p = self.store.load(user_id)
        p["display_name"] = self.name(name)
        self.store.save(p)
        return self.store.load(user_id)

    def delete(self, user_id, confirmed=False):
        if not confirmed:
            raise ValueError("Confirmá la eliminación del perfil")
        self.store.path(user_id).unlink()

    def save_settings(self, profile, settings):
        config = load_config(overrides=settings)
        p = deepcopy(profile)
        old = load_config(overrides=p.get("settings", {}))
        p["settings"] = asdict(config)
        # Un cambio de tiempos de reconocimiento exige volver a validar.
        timing = lambda c: {k: v for k, v in asdict(c.gesture).items() if k.endswith("_ms")}
        if timing(old) != timing(config) and p.get("validation"):
            p["validation"]["passed"] = False
        validate_profile(p)
        self.store.save(p)
        return self.store.load(p["user_id"])

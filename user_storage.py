"""Migración copiada y verificable: nunca reemplaza un perfil existente."""
import hashlib
import json
import os
from pathlib import Path
from app_paths import RESOURCE_ROOT, data_root


def write_json(path, value):
    from profiles import replace_with_retry
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".tmp")
    try:
        with temporary.open("w",encoding="utf-8") as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        replace_with_retry(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def migrate_legacy(source=None, destination=None):
    source=Path(source) if source else RESOURCE_ROOT/"data"
    destination=Path(destination) if destination else data_root()
    if source.resolve()==destination.resolve():return []
    source_id=hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:12]
    marker=destination/("migration-v1-"+source_id+".json")
    from profiles import validate_profile,validate_user_id
    records=[]
    paths=list((source/"profiles").glob("*.json"))
    if (source/"last_profile.json").is_file():paths.append(source/"last_profile.json")
    source_manifest={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if marker.exists():
        previous=json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("source_manifest")==source_manifest:return previous.get("files",[])
    for path in paths:
        raw=path.read_bytes();relative=path.relative_to(source);target=destination/relative
        try:
            value=json.loads(raw)
            if relative.parts[0]=="profiles":
                validate_profile(value)
                if value["user_id"]!=path.stem:raise ValueError("Identidad no coincide con archivo")
            else:validate_user_id(value.get("user_id"))
        except (ValueError,KeyError,TypeError) as exc:
            records.append(dict(file=str(relative),result="invalid",reason=str(exc)));continue
        digest=hashlib.sha256(raw).hexdigest()
        if target.exists():
            if target.read_bytes()==raw:
                records.append(dict(file=str(relative),sha256=digest,result="already_present"));continue
            target=destination/"migration-conflicts"/(path.stem+"-"+digest[:12]+".json")
            result="conflict_preserved"
        else:result="copied"
        target.parent.mkdir(parents=True,exist_ok=True)
        try:
            with target.open("xb") as f:f.write(raw);f.flush();os.fsync(f.fileno())
        except FileExistsError:
            if target.read_bytes()!=raw:raise ValueError("Conflicto de migración; no se reemplazó el archivo")
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError("Copia no verificada")
        records.append(dict(file=str(relative),sha256=digest,result=result))
    # No marcar un origen todavía vacío: permite importar cuando se encuentre después.
    if paths:write_json(marker,dict(version=1,source_manifest=source_manifest,files=records))
    return records

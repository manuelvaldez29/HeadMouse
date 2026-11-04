"""Download and verify the exact model files used by the Windows build."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def verify(path, expected):
    if not path.is_file() or ("bytes" in expected and path.stat().st_size != expected["bytes"]):
        return False
    if "sha256" in expected:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"]
    content = path.read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest() == expected["git_blob"]


def sources():
    manifest = json.loads((ROOT / "packaging/model_sources.json").read_text(encoding="utf-8"))
    for model, source in manifest["whisper"].items():
        for name, expected in source["files"].items():
            yield (ROOT / "models/whisper" / model / name,
                   f"https://huggingface.co/{source['repo']}/resolve/{source['revision']}/{name}", expected)
    for name, source in manifest["other"].items():
        yield ROOT / "models" / name, source["url"], source


def prepare(entry):
    target, url, expected = entry
    if not verify(target, expected):
        target.parent.mkdir(parents=True, exist_ok=True)
        print("Downloading", target.relative_to(ROOT), flush=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            urllib.request.urlretrieve(url, temporary)
            if not verify(temporary, expected):
                raise ValueError(f"Model integrity check failed: {target}")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print("Verified", target.relative_to(ROOT), target.stat().st_size, flush=True)


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(prepare, sources()))

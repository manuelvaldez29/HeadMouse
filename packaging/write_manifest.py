"""Record the Windows artifacts, bundled file hashes and build dependency inventory."""
import argparse
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import re
from runpy import run_path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = run_path(str(ROOT / "app_paths.py"))["VERSION"]
DIST = ROOT / "dist"
PORTABLE = DIST / f"windows-{VERSION}" / "HeadMouse"
INSTALLER = DIST / "installer" / f"HeadMouse-Setup-{VERSION}-win64.exe"


def file_info(path):
    with path.open("rb") as stream:
        return {"path": path.relative_to(DIST).as_posix(), "bytes": path.stat().st_size,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def dependencies():
    result = []
    for distribution in distributions():
        metadata = distribution.metadata
        files = (distribution.locate_file(entry) for entry in distribution.files or ())
        result.append({
            "name": metadata["Name"],
            "version": distribution.version,
            "license": metadata.get("License-Expression") or metadata.get("License") or
                       [v for v in metadata.get_all("Classifier", []) if v.startswith("License ::")],
            "installed_bytes": sum(path.stat().st_size for path in files if path.is_file()),
            "requires": distribution.requires or [],
        })
    return sorted(result, key=lambda item: item["name"].lower())


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--test-log", type=Path)
    args = parser.parse_args()
    artifacts = [file_info(INSTALLER), file_info(PORTABLE / "HeadMouse.exe")]
    files = [file_info(path) for path in sorted(PORTABLE.rglob("*")) if path.is_file()]
    inventory = DIST / f"windows-{VERSION}" / "dependency-inventory.json"
    write_json(inventory, {"kind": "build_environment", "python": platform.python_version(),
                           "dependencies": dependencies()})
    manifest = {
        "version": VERSION,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_has_local_changes": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "build_os": platform.platform(),
        "python": platform.python_version(),
        "artifacts": artifacts,
        "portable_bytes": sum(item["bytes"] for item in files),
        "portable_files": files,
        "dependency_inventory": file_info(inventory),
    }
    if args.verification:
        evidence = json.loads(args.verification.read_text(encoding="utf-8"))
        if evidence["result"] != "passed" or evidence["installer_sha256"] != artifacts[0]["sha256"]:
            raise ValueError("Installer evidence does not match this build")
        manifest["installer_verification"] = {
            key: value for key, value in evidence.items() if key not in ("data_dir", "steps")
        }
    if args.test_log:
        log = args.test_log.read_text(encoding="utf-8", errors="replace")
        summary = re.search(r"^Ran (\d+) tests in ([\d.]+)s\s+OK(?: \(skipped=(\d+)\))?", log, re.MULTILINE)
        if not summary or "PhysicalIOGuardAttempts: 0 []" not in log:
            raise ValueError("Test log does not show a successful run with the I/O guard")
        count, seconds, skipped = summary.groups()
        manifest["automated_tests"] = {"total": int(count), "seconds": float(seconds),
                                       "skipped": int(skipped or 0), "physical_io_attempts": 0}
    write_json(DIST / f"release-manifest-{VERSION}.json", manifest)
    (DIST / f"SHA256SUMS-{VERSION}.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in artifacts), encoding="utf-8")


if __name__ == "__main__":
    main()

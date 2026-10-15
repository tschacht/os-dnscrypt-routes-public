"""R-19: the manual kit (artifacts/, reference/) stays byte-identical."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_artifacts_match_reference_manifest():
    manifest = json.loads((ROOT / "reference" / "manifest.json").read_text())
    files = manifest["files"]
    assert files, "manifest lists no files"
    listed = set()
    for entry in files:
        dest = entry["destination"]
        listed.add(dest)
        path = ROOT / dest
        assert path.is_file(), f"missing {dest}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], dest
    on_disk = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "artifacts").rglob("*")
        if p.is_file()
    }
    listed_artifacts = {d for d in listed if d.startswith("artifacts/")}
    assert on_disk == listed_artifacts, f"artifacts/ differs from manifest: {on_disk ^ listed_artifacts}"

"""Verify explicitly provisioned local assets before any optional model loader runs."""
import hashlib
import json
from pathlib import Path


ASSET_ROLES = {"text": ("path",), "code": ("path",), "ratio": ("observer", "performer"), "code_match": ("corpus",), "semantic": ("path",)}


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:24]


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Use a dedicated immutable asset copy, not symlinks")
    if path.is_file():
        return {".": file_digest(path)}
    if not path.is_dir():
        raise ValueError("A local asset is missing")
    entries = list(path.rglob("*"))
    if any(entry.is_symlink() for entry in entries):
        raise ValueError("Asset snapshots cannot contain symlinks")
    files = {entry.relative_to(path).as_posix(): file_digest(entry) for entry in entries if entry.is_file()}
    if not files:
        raise ValueError("Empty local asset snapshot")
    return files


def verify_assets(config, roles):
    path = Path(config["asset_manifest"])
    if path.is_symlink() or file_digest(path) != config["asset_manifest_sha256"]:
        raise ValueError("Asset manifest integrity failed")
    value = json.loads(path.read_text())
    if value.get("schema_version") != 1 or set(value.get("assets", {})) != set(roles):
        raise ValueError("Asset manifest roles differ")
    for role in roles:
        if inventory(config[role]) != value["assets"][role]:
            raise ValueError("Local asset integrity failed")

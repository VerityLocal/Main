"""Immutable, relocatable Standard bundle configuration and offline policy."""
import json
import hashlib
import logging
import os
import sys
from pathlib import Path

APPROVED_PINS_SHA256 = "f23d53e7099644e433a148ac3133e5a23a05692e57a32afc347239fd5ae02143"


def offline_policy(root):
    # Some relocatable CPython builds derive Tcl paths from argv[0] under -m.
    # Frozen apps use PyInstaller's Tcl/Tk runtime hook instead.
    if not getattr(sys, "frozen", False):
        for parent in (Path(sys.base_prefix) / "lib", Path(sys.base_prefix) / "tcl"):
            for prefix, variable in (("tcl8.", "TCL_LIBRARY"), ("tk8.", "TK_LIBRARY")):
                candidates = sorted(parent.glob(prefix + "*"))
                if candidates:
                    os.environ[variable] = str(candidates[-1])
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        os.environ[key] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(root) / "browsers")
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["MKL_NUM_THREADS"] = "4"
    logging.disable(logging.CRITICAL)


def bundle_root():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "bundle"
    return Path(__file__).parents[1] / ".local/desktop-bundle"


def standard_config(root):
    root = Path(root).resolve()
    pins = json.loads((root / "model-pins.json").read_text())
    if hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != APPROVED_PINS_SHA256:
        raise ValueError("Standard bundle pins differ from this approved application build")
    if pins.get("schema_version") != 1:
        raise ValueError("Invalid Standard bundle pins")
    entries = {}
    # Never trust shipped absolute paths or enable excluded adapters.
    from product.engine.assets import file_digest
    for name in ("text", "semantic"):
        pin = pins["models"][name]
        revision = pin["revision"]
        if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError("Invalid snapshot revision")
        manifest = root / "models" / (name + "-manifest.json")
        expected = {"schema_version": 1, "assets": {"path": {key: value["sha256"] for key, value in pin["files"].items()}}}
        if json.loads(manifest.read_text()) != expected:
            raise ValueError("Bundle manifest differs from approved pins")
        entries[name] = {
            "enabled": True, "license_reviewed": True,
            "snapshot_id": revision, "managed_profile": "verity-standard-v1",
            "path": str(root / "models" / f"{name}-{revision}"),
            "asset_manifest": str(manifest), "asset_manifest_sha256": file_digest(manifest),
            "min_ram_gib": 8 if name == "text" else 4,
        }
    entries["text"].update(max_tokens=768, weight=0.7)
    return {"signals": {"text": entries["text"]}, "semantic": entries["semantic"], "max_queries": 24}

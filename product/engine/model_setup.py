"""Installer-only pinned model acquisition. Inference never calls this downloader."""
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .assets import file_digest, inventory
from .local_os import bootstrap_lock, private_opener, reject_link
from .native_host import save_config
from .resources import physical_memory

PROFILE = "verity-models-v1"
REPOSITORIES = {"text": "desklib/ai-text-detector-v1.01", "semantic": "BAAI/bge-small-en-v1.5", "observer": "tiiuae/falcon-7b", "performer": "tiiuae/falcon-7b-instruct"}
MIN_RAM = {"text": 8, "semantic": 4, "ratio": 64}


def validate_pins(value):
    if value.get("schema_version") != 1 or set(value.get("models", {})) != set(REPOSITORIES):
        raise ValueError("Unsupported model pins")
    for role, model in value["models"].items():
        if model.get("repository") != REPOSITORIES[role] or model.get("license") not in {"MIT", "Apache-2.0"} or not re.fullmatch("[a-f0-9]{40}", model.get("revision", "")):
            raise ValueError("Unapproved model identity")
        files = model.get("files", {})
        if not 1 <= len(files) <= 32 or "README.md" not in files:
            raise ValueError("Missing model files or notices")
        for name, pin in files.items():
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", name) or any(part in {"", ".", ".."} or part.endswith(".") for part in name.split("/")) or name.endswith((".bin", ".py")):
                raise ValueError("Unsafe model file")
            if type(pin.get("bytes")) is not int or not 0 < pin["bytes"] <= 10 * 1024 ** 3 or not re.fullmatch("[a-f0-9]{64}", pin.get("sha256", "")):
                raise ValueError("Invalid model file pin")
    return value


class ModelRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in {None, 443} or not (host == "huggingface.co" or host.endswith(".hf.co") or host.endswith(".huggingface.co")):
            raise ValueError("Unapproved model download redirect")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_file(model, name, pin, target):
    url = "https://huggingface.co/" + model["repository"] + "/resolve/" + model["revision"] + "/" + urllib.parse.quote(name, safe="/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ModelRedirects())
    digest, count, started = hashlib.sha256(), 0, time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "Verity-model-setup/0.2", "Accept-Encoding": "identity"})
    with opener.open(request, timeout=120) as response, open(target, "xb", opener=private_opener) as output:
        if response.status != 200:
            raise ValueError("Model download failed")
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            count += len(chunk)
            if count > pin["bytes"] or time.monotonic() - started > 1800:
                raise ValueError("Model download exceeds limits")
            digest.update(chunk)
            output.write(chunk)
    if count != pin["bytes"] or digest.hexdigest() != pin["sha256"]:
        raise ValueError("Model download integrity failed")


def snapshot(model, role, store, downloader):
    destination = store / (role + "-" + model["revision"])
    reject_link(destination)
    expected = {name: pin["sha256"] for name, pin in model["files"].items()}
    if destination.exists():
        if inventory(destination) != expected:
            raise ValueError("Changed model snapshot; review it before repair")
        return destination
    size = sum(pin["bytes"] for pin in model["files"].values())
    if shutil.disk_usage(store).free < size + 1024 ** 3:
        raise ValueError("Insufficient model download space")
    with tempfile.TemporaryDirectory(prefix=".model-", dir=store) as temporary:
        stage = Path(temporary)
        for name, pin in model["files"].items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            downloader(model, name, pin, target)
            if target.stat().st_size != pin["bytes"] or file_digest(target) != pin["sha256"]:
                raise ValueError("Unverified model download")
        if inventory(stage) != expected:
            raise ValueError("Unexpected model files")
        # Rename an immutable snapshot atomically. The outer installer lock serializes setup.
        stage.rename(destination)
    return destination


def signal_config(store, name, assets, revisions, **extra):
    contents = {"schema_version": 1, "assets": {key: inventory(path) for key, path in assets.items()}}
    identity = hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()[:24]
    manifest = store / (name + "-" + identity + "-manifest.json")
    save_config(manifest, contents)
    return {"enabled": True, "managed_profile": PROFILE, "license_reviewed": True, "snapshot_id": "+".join(revisions), "asset_manifest": str(manifest), "asset_manifest_sha256": file_digest(manifest), **{key: str(path) for key, path in assets.items()}, **extra}


def setup_models(root, pins, *, downloader=download_file, memory=None):
    pins = validate_pins(pins)
    root = Path(root).absolute()
    for parent in [root, *root.parents]:
        reject_link(parent)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = root / "models"
    reject_link(store)
    store.mkdir(exist_ok=True, mode=0o700)
    ram = physical_memory() if memory is None else memory
    profile = {"schema_version": 1, "signals": {}, "states": {"code": "checkpoint_required", "code_match": "corpus_required"}}
    with bootstrap_lock(store / "setup.lock"):
        for name, roles in [("text", ["text"]), ("semantic", ["semantic"]), ("ratio", ["observer", "performer"])]:
            if ram < MIN_RAM[name] * 1024 ** 3:
                profile["states"][name] = "insufficient_memory"
                continue
            paths = {role: snapshot(pins["models"][role], role, store, downloader) for role in roles}
            assets = {"path": paths[roles[0]]} if name != "ratio" else paths
            extra = {"min_ram_gib": MIN_RAM[name], "max_tokens": 512 if name != "text" else 768}
            if name != "semantic":
                extra["weight"] = 0.7 if name == "text" else 0.3
            value = signal_config(store, name, assets, [pins["models"][role]["revision"] for role in roles], **extra)
            if name == "semantic":
                profile["semantic"] = value
            else:
                profile["signals"][name] = value
            profile["states"][name] = "provisioned"
        save_config(root / "models-profile.json", profile)
    return profile


def apply_profile(config, profile):
    """Preserve tokens, pairing, private custom signals and operator-disabled settings."""
    value = copy.deepcopy(config)
    signals = value.setdefault("signals", {})
    for name in ["text", "ratio", "code", "code_match"]:
        current = signals.get(name)
        if name in profile.get("signals", {}) and (current is None or current.get("managed_profile") == PROFILE):
            signals[name] = {**profile["signals"][name], **({"enabled": current["enabled"]} if current and "enabled" in current else {})}
    current = value.get("semantic")
    if "semantic" in profile and (current is None or current.get("managed_profile") == PROFILE):
        value["semantic"] = {**profile["semantic"], **({"enabled": current["enabled"]} if current and "enabled" in current else {})}
    value["model_setup_states"] = {key: state for key, state in profile.get("states", {}).items() if key in {"text", "ratio", "code", "code_match", "semantic"} and state in {"provisioned", "insufficient_memory", "checkpoint_required", "corpus_required"}}
    return value


def main():
    parser = argparse.ArgumentParser(description="Acquire pinned local models during explicit setup, never during inference")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    profile = setup_models(args.root, json.loads(args.pins.read_text()))
    if args.config:
        with bootstrap_lock(args.config.with_name(args.config.name + ".lock")):
            save_config(args.config, apply_profile(json.loads(args.config.read_text()), profile))
    print(json.dumps(profile["states"], sort_keys=True))


if __name__ == "__main__":
    main()

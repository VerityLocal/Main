"""Assemble only approved pinned assets. Existing model originals are never changed."""
import argparse
import hashlib
import importlib.metadata
import json
import shutil
import ssl
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

PRODUCT = Path(__file__).parents[1]
REPOSITORIES = {"text": "desklib/ai-text-detector-v1.01", "semantic": "BAAI/bge-small-en-v1.5"}


class ApprovedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, url):
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username or parsed.password or not (host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co")):
            raise ValueError("Model download left approved HTTPS hosts")
        return super().redirect_request(request, fp, code, msg, headers, url)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def check_pin(name, pin):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or path.suffix not in {".json", ".md", ".safetensors", ".model", ".txt"}:
        raise ValueError("Unsupported pinned asset")
    if type(pin["bytes"]) is not int or pin["bytes"] <= 0 or len(pin["sha256"]) != 64:
        raise ValueError("Invalid file pin")


def prepare(target, models=None, browsers=None):
    target = Path(target)
    if target.exists():
        raise ValueError("Choose a new staging directory; existing builds are preserved")
    pins = json.loads((PRODUCT / "model-pins.json").read_text())
    selected = {"schema_version": 1, "models": {name: pins["models"][name] for name in REPOSITORIES}}
    from product.desktop.config import APPROVED_PINS_SHA256
    if hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != APPROVED_PINS_SHA256:
        raise ValueError("Preparation pins differ from the approved Standard build")
    target.mkdir(parents=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ApprovedRedirects(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    for role, model in selected["models"].items():
        if model["repository"] != REPOSITORIES[role] or model["license"] != "MIT" or len(model["revision"]) != 40:
            raise ValueError("Unapproved Standard model")
        relative = f"{role}-{model['revision']}"
        for name, pin in model["files"].items():
            check_pin(name, pin)
            destination = target / "models" / relative / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if models:
                source = Path(models) / relative / name
                if source.is_symlink() or source.stat().st_size != pin["bytes"] or digest(source) != pin["sha256"]:
                    raise ValueError("Original model differs from approved pin")
                shutil.copyfile(source, destination)
            else:
                url = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{name}"
                with opener.open(url, timeout=90) as stream, destination.open("xb") as output:
                    remaining = pin["bytes"]
                    while remaining:
                        block = stream.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        output.write(block)
                        remaining -= len(block)
                    if stream.read(1):
                        raise ValueError("Download exceeds pinned size")
            if destination.stat().st_size != pin["bytes"] or digest(destination) != pin["sha256"]:
                raise ValueError("Model download/copy integrity failed")
        manifest = {"schema_version": 1, "assets": {"path": {name: pin["sha256"] for name, pin in model["files"].items()}}}
        (target / "models" / (role + "-manifest.json")).write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    (target / "model-pins.json").write_text(json.dumps(selected, indent=2) + "\n")
    shutil.copyfile(PRODUCT / "THIRD-PARTY-NOTICES.txt", target / "THIRD-PARTY-NOTICES.txt")
    # Full installed package license files, without private direct_url metadata.
    licenses = target / "licenses"
    inventory = []
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        inventory.append({"name": name, "version": distribution.version})
        for file in distribution.files or ():
            upper = str(file).upper()
            if any(word in PurePosixPath(upper).name for word in ("LICENSE", "COPYING", "NOTICE", "AUTHORS")) and ".." not in file.parts:
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    destination = licenses / name / Path(str(file))
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
    (target / "dependency-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    if browsers:
        browsers = Path(browsers)
        for item in browsers.iterdir():
            if item.name.startswith(("chromium_headless_shell-", "ffmpeg-")) and item.is_dir():
                shutil.copytree(item, target / "browsers" / item.name, symlinks=True)
        if not list((target / "browsers").glob("chromium_headless_shell-*")):
            raise ValueError("Pinned retrieval browser is missing")
    else:
        raise ValueError("Provide the Playwright browser directory; runtime never downloads a browser")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--browsers", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.output, args.models, args.browsers))


if __name__ == "__main__":
    main()

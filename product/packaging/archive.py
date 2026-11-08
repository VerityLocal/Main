"""Create a new ZIP only after genuine frozen-app acceptance; verify shipped pins."""
import argparse
import hashlib
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from product.desktop.config import APPROVED_PINS_SHA256

LIMIT = 2 * 1024 ** 3


def verify_archive(path):
    path = Path(path)
    if not 0 < path.stat().st_size < LIMIT:
        raise ValueError("GitHub release ZIP must be under 2 GiB")
    with zipfile.ZipFile(path) as archive:
        entries = {info.filename: info for info in archive.infolist() if not info.filename.startswith("__MACOSX/")}
        for name in entries:
            parts = PurePosixPath(name).parts
            if PurePosixPath(name).is_absolute() or ".." in parts or "\\" in name:
                raise ValueError("Unsafe ZIP path")
            if any(part in {".env", ".git", ".runtime", ".desktop-runtime", ".local", "private", "helper.json", "models-profile.json", "direct_url.json", ".DS_Store", "chrome-extension"} for part in parts):
                raise ValueError("Private or obsolete material in ZIP")
        candidates = [name for name in entries if name.endswith("/bundle/model-pins.json")]
        if len(candidates) != 1:
            raise ValueError("Exactly one Standard pin inventory is required")
        base = candidates[0].removesuffix("model-pins.json")
        pins = json.loads(archive.read(candidates[0]))
        if hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != APPROVED_PINS_SHA256:
            raise ValueError("Archive pins differ from the approved build")
        if set(pins["models"]) != {"text", "semantic"}:
            raise ValueError("Non-Standard models in ZIP")
        verified = 0
        expected = set()
        for role, model in pins["models"].items():
            snapshot = base + f"models/{role}-{model['revision']}/"
            for relative, pin in model["files"].items():
                name = snapshot + relative
                expected.add(name)
                info = entries[name]
                if info.file_size != pin["bytes"] or stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("Invalid model file size/type")
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != pin["sha256"]:
                    raise ValueError("Archive model integrity failed")
                verified += 1
            actual = {name for name, info in entries.items() if name.startswith(snapshot) and not info.is_dir()}
            if actual != {name for name in expected if name.startswith(snapshot)}:
                raise ValueError("Unlisted files in model snapshot")
        if not any(name.startswith(base + "licenses/") for name in entries) or base + "THIRD-PARTY-NOTICES.txt" not in entries:
            raise ValueError("Missing license notices")
        for name in ("licenses/Python/LICENSE.txt", "licenses/Tcl-Tk/Tcl-license.terms", "licenses/Tcl-Tk/Tk-license.terms"):
            if base + name not in entries:
                raise ValueError("Missing Python/Tcl/Tk license")
        if not any("/browsers/chromium_headless_shell-" in name and name.endswith(("chrome-headless-shell", "headless_shell.exe")) for name in entries):
            raise ValueError("Missing self-contained retrieval browser")
        weights = [name for name in entries if name.endswith(".safetensors")]
        if set(weights) != {name for name in expected if name.endswith(".safetensors")}:
            raise ValueError("Unexpected model weights")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"asset": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest(), "verified_model_files": verified, "under_2_gib": True}


def create_archive(app, output, acceptance):
    app, output = Path(app), Path(output)
    report = json.loads(Path(acceptance).read_text())
    if not report.get("passed") or not report.get("frozen") or report.get("accuracy_claim"):
        raise ValueError("Actual frozen-app acceptance must pass before archiving")
    if output.exists():
        raise ValueError("Choose a new archive path; previous downloads are never replaced")
    output.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(output)], check=True)
    else:
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for file in sorted(app.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(app.parent).as_posix())
    return verify_archive(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify_archive(args.zip) if args.verify_only else create_archive(args.app, args.zip, args.acceptance)
    if args.report:
        with args.report.open("x") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

"""Build Verity Local release ZIPs from tracked source and verified local models."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import __version__
from backend.detectors.artifacts import ARTIFACT_HASHES, verify_artifacts

DIST = ROOT / "dist"
PREFIX = f"https://github.com/VerityLocal/Main/releases/download/v{__version__}"


def zip_files(path, files):
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for source, target in sorted(files, key=lambda item: item[1]):
            archive.write(source, target)
    if path.stat().st_size >= 2 * 1024 ** 3:
        raise ValueError(f"{path.name} exceeds GitHub's 2 GiB asset limit")
    print(f"Built {path.name}: {path.stat().st_size:,} bytes", flush=True)


def models():
    for kind, expected in ARTIFACT_HASHES.items():
        directory = ROOT / "models" / f"{kind}_detector"
        verify_artifacts(directory, expected)
        files = [(directory / name, f"models/{kind}_detector/{name}") for name in expected]
        if (directory / "metrics.json").is_file():
            files.append((directory / "metrics.json", f"models/{kind}_detector/metrics.json"))
        files.append((ROOT / "docs/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"))
        zip_files(DIST / f"Verity-Local-{kind.capitalize()}-Model-v{__version__}.zip", files)


def application():
    vendor = ROOT / "extension/vendor"
    if not (vendor / "pdf.mjs").is_file():
        raise ValueError("Build extension/vendor first with npm run build in extension/.")
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    files = [(ROOT / name, f"verity-local/{name}") for name in tracked if name]
    files += [(path, f"verity-local/{path.relative_to(ROOT).as_posix()}") for path in vendor.rglob("*") if path.is_file()]
    zip_files(DIST / f"Verity-Local-v{__version__}.zip", files)
    runtime = [(path, f"verity-local-extension/{path.name}") for path in (ROOT / "extension").iterdir()
               if path.suffix in {".html", ".js", ".css"} or path.name == "manifest.json"]
    for directory in (vendor, ROOT / "extension/icons"):
        runtime += [(path, f"verity-local-extension/{path.relative_to(ROOT / 'extension').as_posix()}")
                    for path in directory.rglob("*") if path.is_file()]
    runtime.append((ROOT / "docs/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"))
    with ZipFile(DIST / f"Verity-Local-Extension-v{__version__}.zip", "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
        for source, target in sorted(runtime, key=lambda item: item[1]):
            archive.write(source, target)
        archive.writestr("INSTALL.txt", "Verity Local v" + __version__ + "\n\n"
                        "Extract this ZIP, then Load unpacked the verity-local-extension folder in Chrome or Edge.\n"
                        "The extension needs the local Python backend and models.\n"
                        "Full illustrated setup: https://veritylocal.github.io/#setup\n")
    print("Built ready-to-load extension ZIP.", flush=True)


def manifest():
    entries = []
    for path in sorted(DIST.glob(f"*v{__version__}.zip")):
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        entries.append({"name": path.name, "bytes": path.stat().st_size, "sha256": digest,
                        "url": f"{PREFIX}/{path.name}"})
    (DIST / "SHA256SUMS.txt").write_text("".join(f"{entry['sha256']}  {entry['name']}\n" for entry in entries))
    (DIST / "release-metadata.json").write_text(json.dumps({"version": __version__, "assets": entries}, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--models-only", action="store_true")
    group.add_argument("--application-only", action="store_true")
    args = parser.parse_args()
    DIST.mkdir(exist_ok=True)
    if not args.application_only:
        models()
    if not args.models_only:
        application()
    manifest()

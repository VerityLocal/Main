"""Download the Verity Local release models and verify every inference artifact."""

import argparse
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

from backend import __version__
from backend.config import PROJECT_ROOT
from backend.detectors.artifacts import ARTIFACT_HASHES, ModelLoadError, verify_artifacts


RELEASE_URL = f"https://github.com/VerityLocal/Main/releases/download/v{__version__}"


def install_archive(archive: Path, kind: str, destination: Path, expected=None) -> None:
    """Validate a complete model in staging before replacing any installed file."""
    expected = ARTIFACT_HASHES[kind] if expected is None else expected
    prefix = f"models/{kind}_detector/"
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".verity-model-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        with ZipFile(archive) as bundle:
            members = [item for item in bundle.infolist() if not item.is_dir()]
            names = [item.filename for item in members]
            allowed = {prefix + name for name in expected} | {prefix + "metrics.json", "THIRD_PARTY_NOTICES.md"}
            if len(names) != len(set(names)) or any(name not in allowed for name in names):
                raise ValueError("Model archive contains unexpected or duplicate files.")
            if not {prefix + name for name in expected} <= set(names):
                raise ValueError("Model archive is incomplete.")
            if sum(item.file_size for item in members) > 2 * 1024 ** 3:
                raise ValueError("Model archive exceeds the size limit.")
            for item in members:
                if item.filename == "THIRD_PARTY_NOTICES.md":
                    continue
                target = staging / item.filename.removeprefix(prefix)
                with bundle.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        verify_artifacts(staging, expected)
        # Keep the inspected artifacts byte-identical, including tokenizer metadata.
        for source in staging.iterdir():
            source.replace(destination / source.name)
    verify_artifacts(destination, expected)


def download(url: str, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    request = Request(url, headers={"User-Agent": f"Verity-Local/{__version__}"})
    received = 0
    last_report = 0
    try:
        with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            length = int(response.headers.get("Content-Length", 0))
            while block := response.read(1024 * 1024):
                output.write(block)
                received += len(block)
                if received > 2 * 1024 ** 3:
                    raise ValueError("Download exceeds the model archive size limit.")
                if received - last_report >= 100 * 1024 ** 2:
                    total = f" / {length / 1024 ** 2:.0f} MiB" if length else " MiB"
                    print(f"  {received / 1024 ** 2:.0f}{total}", flush=True)
                    last_report = received
            if length and received != length:
                raise ValueError("Download was incomplete. Run the command again.")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify installed models without downloading.")
    parser.add_argument("--kind", choices=("text", "code"), help="Install or check just one detector.")
    parser.add_argument("--from-dir", type=Path, help="Install ZIPs downloaded manually, without network access.")
    parser.add_argument("--models-dir", type=Path, default=PROJECT_ROOT / "models")
    args = parser.parse_args()
    kinds = (args.kind,) if args.kind else ("text", "code")
    cache = PROJECT_ROOT / ".local" / "downloads"
    for kind in kinds:
        destination = args.models_dir / f"{kind}_detector"
        try:
            verify_artifacts(destination, ARTIFACT_HASHES[kind])
            print(f"{kind.capitalize()} detector: verified and ready.", flush=True)
            continue
        except ModelLoadError as error:
            if args.check:
                print(f"{kind.capitalize()} detector: {error}", file=sys.stderr)
                return 1
        name = f"Verity-Local-{kind.capitalize()}-Model-v{__version__}.zip"
        if args.from_dir:
            archive = args.from_dir.expanduser() / name
        else:
            cache.mkdir(parents=True, exist_ok=True)
            archive = cache / name
            if not archive.is_file():
                print(f"Downloading {name}…", flush=True)
                download(f"{RELEASE_URL}/{name}", archive)
        print(f"Verifying and installing the {kind} detector…", flush=True)
        try:
            install_archive(archive, kind, destination)
        except Exception:
            if not args.from_dir:
                archive.unlink(missing_ok=True)
            raise
        if not args.from_dir:
            archive.unlink()
        print(f"{kind.capitalize()} detector: verified and ready.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, BadZipFile, ModelLoadError) as error:
        print(f"Model setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)

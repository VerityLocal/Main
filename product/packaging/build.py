"""Freeze Python/Tk natively, then preserve Chromium's independent binary layout."""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, help="Reuse a maintainer-owned PyInstaller cache")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new build-output directory; existing packages are preserved")
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Build natively on macOS or Windows")
    if sys.platform == "darwin" and platform.machine() != "arm64":
        raise SystemExit("This Standard release targets Apple Silicon, not Intel macOS")
    root = Path(__file__).parents[2]
    environment = {**os.environ, "VERITY_BUNDLE": str(args.bundle.resolve())}
    subprocess.run([sys.executable, "-m", "PyInstaller", "--distpath", str(args.output), "--workpath", str(args.work or root / "product/build" / args.output.name), str(root / "product/packaging/verity.spec")], env=environment, check=True)
    app = args.output / ("Verity.app" if sys.platform == "darwin" else "Verity")
    contents = app / ("Contents/Resources/bundle" if sys.platform == "darwin" else "_internal/bundle")
    shutil.copytree(args.bundle / "browsers", contents / "browsers", symlinks=True)
    shutil.copytree(root / "product/packaging/licenses", contents / "licenses/Tcl-Tk", dirs_exist_ok=True)
    import sysconfig
    python_license = next((path for path in (Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt") if path.is_file()), None)
    if not python_license:
        raise SystemExit("The build interpreter's Python license notice is missing")
    (contents / "licenses/Python").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(python_license, contents / "licenses/Python/LICENSE.txt")
    if sys.platform == "darwin":
        # Ad-hoc signing is not Developer ID signing or notarization.
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(app)], check=True)
    print(f"Built {platform.system()} {platform.machine()}: {app}")


if __name__ == "__main__":
    main()

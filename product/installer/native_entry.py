"""Isolated installed entrypoint: only the installer-owned release is importable."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / "browsers")

mode = sys.argv.pop(1)
if mode == "server":
    from product.engine.server import main
elif mode == "native":
    from product.engine.native_host import main
else:
    raise SystemExit("Unsupported local operation")
main()

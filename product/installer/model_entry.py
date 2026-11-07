"""Isolated installer entrypoint for explicit, pinned model setup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from product.engine.model_setup import main

main()

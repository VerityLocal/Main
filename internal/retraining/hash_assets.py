"""Create a pinning manifest for an intentionally provisioned local asset copy."""
import argparse
import json
from pathlib import Path

from product.engine.assets import ASSET_ROLES, file_digest, inventory


def main():
    parser = argparse.ArgumentParser(description="Inventory local model/corpus assets; never download")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--signal", choices=ASSET_ROLES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a new output file; existing manifests are not overwritten")
    config = json.loads(args.config.read_text())
    selected = config["semantic"] if args.signal == "semantic" else config["signals"][args.signal]
    assets = {role: inventory(selected[role]) for role in ASSET_ROLES[args.signal]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump({"schema_version": 1, "assets": assets}, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"asset_manifest": str(args.output.resolve()), "asset_manifest_sha256": file_digest(args.output)}, indent=2))


if __name__ == "__main__":
    main()

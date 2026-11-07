"""Add only an exact Chrome extension origin, preserving existing credentials."""

import argparse
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Allow one exact unpacked Chrome extension origin")
    parser.add_argument("extension_id")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-p]{32}", args.extension_id):
        raise SystemExit("Invalid Chrome extension ID")
    lines = args.env.read_text(encoding="utf-8").splitlines()
    key = "LOCAL_AI_ALLOWED_ORIGINS="
    found = next((i for i, line in enumerate(lines) if line.startswith(key)), None)
    origins = json.loads(lines[found][len(key) :]) if found is not None else []
    origin = "chrome-extension://" + args.extension_id
    if origin not in origins:
        origins.append(origin)
    value = key + json.dumps(origins, separators=(",", ":"))
    if found is not None:
        lines[found] = value
    else:
        lines.append(value)
    # Preserve existing secrets; only the explicitly requested allowlist changes.
    with args.env.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    print("Exact extension origin allowed. Restart the backend; credentials were not displayed.")


if __name__ == "__main__":
    main()

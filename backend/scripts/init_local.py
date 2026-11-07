"""Create credentials without printing them or overwriting existing files."""

import argparse
import os
import secrets
from pathlib import Path


def initialize(path: Path) -> None:
    contents = (
        f"LOCAL_AI_AUTH_TOKEN={secrets.token_urlsafe(48)}\n"
        f"LOCAL_AI_CSRF_TOKEN={secrets.token_urlsafe(48)}\n"
        "LOCAL_AI_BIND_HOST=127.0.0.1\n"
        "LOCAL_AI_PORT=8787\n"
        "LOCAL_AI_ALLOWED_ORIGINS=[]\n"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(contents)


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize local secrets; never overwrite .env")
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    try:
        initialize(args.output)
    except FileExistsError:
        raise SystemExit("Credential file already exists; no changes made.") from None
    print(f"Created {args.output}. Keep this credential file private.")


if __name__ == "__main__":
    main()

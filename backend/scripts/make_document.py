"""Construct a canonical document from an explicitly selected UTF-8 text file."""

import argparse
from pathlib import Path

from backend.app.document.builder import build_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a manual document; no analysis or upload")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--document-id")
    parser.add_argument("--revision", type=int, default=0)
    parser.add_argument("--language", default="und")
    args = parser.parse_args()
    # Preserve original CR/LF instead of text-mode newline translation.
    text = args.input.read_bytes().decode("utf-8-sig")
    try:
        document = build_document(
            [text], document_id=args.document_id, revision=args.revision, language=args.language
        )
    except ValueError:
        raise SystemExit("Input cannot form a valid canonical document.") from None
    # Refuse to overwrite potentially private user work.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(document.model_dump_json(indent=2) + "\n")
    print(f"Document written to {args.output}. No analysis or transmission performed.")


if __name__ == "__main__":
    main()

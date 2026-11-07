"""Generate/check JSON Schema artifacts from executable Pydantic definitions."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import PROJECT_ROOT
from backend.app.schemas.analysis import AnalysisRequest, Source
from backend.app.schemas.document import Document
from backend.app.schemas.event import EventEnvelope
from backend.app.schemas.extraction import TextAnalysisRequest
from backend.app.schemas.finding import Finding

SCHEMA_MODELS = {
    "document.schema.json": Document,
    "finding.schema.json": Finding,
    "event.schema.json": EventEnvelope,
    "analysis.schema.json": AnalysisRequest,
    "text-analysis.schema.json": TextAnalysisRequest,
    "source.schema.json": Source,
}


def schema_artifacts() -> dict[str, str]:
    artifacts = {}
    for filename, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:local-ai-analysis-platform:1.0.0:{filename}"
        schema["x-contract-version"] = "1.0.0"
        artifacts[filename] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Export shared JSON Schema contracts")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "shared" / "schemas")
    args = parser.parse_args()
    artifacts = schema_artifacts()
    if args.check:
        mismatched = [
            filename
            for filename, text in artifacts.items()
            if not (args.output_dir / filename).is_file()
            or (args.output_dir / filename).read_text(encoding="utf-8") != text
        ]
        if mismatched:
            raise SystemExit("Contract artifacts differ: " + ", ".join(mismatched))
        print(f"All {len(artifacts)} JSON Schema artifacts match their executable contracts.")
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in artifacts.items():
        (args.output_dir / filename).write_text(text, encoding="utf-8", newline="\n")
    print(f"Exported {len(artifacts)} schemas to {args.output_dir}")


if __name__ == "__main__":
    main()

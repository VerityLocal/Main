import argparse
import json
from pathlib import Path

from backend.app.core.config import Settings, load_platform_config
from backend.app.engines.stylometry.extractor import FeatureExtractor
from backend.app.services.model_manager import ModelManager
from backend.scripts.dataset_utils import read_records


def main():
    parser = argparse.ArgumentParser(
        description="Extract pinned lightweight feature rows from approved JSONL"
    )
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from transformers import AutoTokenizer

    settings = Settings()
    models = ModelManager(settings, load_platform_config(settings.config_dir))
    tokenizer = AutoTokenizer.from_pretrained(
        models.path("ai_backbone"), local_files_only=True, use_fast=True
    )
    extractor = FeatureExtractor(tokenizer)
    with args.output.open("x", encoding="utf-8") as stream:
        for record in read_records(args.data):
            stream.write(
                json.dumps(
                    {
                        "id": record["id"],
                        "split": record["split"],
                        **extractor.extract(record["text"], record.get("language", "en")),
                    },
                    allow_nan=False,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()

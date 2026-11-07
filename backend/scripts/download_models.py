"""Explicit model download; never called by analysis or startup."""

import argparse

import yaml

from backend.app.core.config import Settings, load_platform_config


def main():
    parser = argparse.ArgumentParser(
        description="Download exact pinned model snapshots (network access)"
    )
    parser.add_argument("models", nargs="+")
    parser.add_argument(
        "--enable", action="store_true", help="Enable selected models after successful downloads"
    )
    args = parser.parse_args()
    from huggingface_hub import snapshot_download

    settings = Settings()
    config = load_platform_config(settings.config_dir)
    yaml_path = settings.config_dir / "models.yaml"
    content = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    for name in args.models:
        if name not in config.models.models:
            raise SystemExit("Unknown configured model")
        spec = config.models.models[name]
        if not all([spec.model_id, spec.revision, spec.tokenizer_revision, spec.license]):
            raise SystemExit("Model revision/license is not pinned")
        if spec.tokenizer_revision != spec.revision:
            raise SystemExit(
                "This downloader requires model and tokenizer at the same pinned revision"
            )
        target = settings.model_cache / name / spec.revision
        snapshot_download(
            repo_id=spec.model_id,
            revision=spec.revision,
            local_dir=target,
            ignore_patterns=["*.onnx", "*.h5", "*.ot", "*.msgpack", "openvino/*", "onnx/*"],
        )
        (target / ".download-complete").write_text(spec.revision, encoding="ascii")
        if args.enable:
            content["models"][name]["enabled"] = True
        print(f"Downloaded pinned {name}; runtime remains local-only.")
    if args.enable:
        temporary = yaml_path.with_suffix(".yaml.new")
        temporary.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
        temporary.replace(yaml_path)
        print("Restart the server to apply enabled model configuration.")


if __name__ == "__main__":
    main()

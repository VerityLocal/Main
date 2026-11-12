# Verity Local models

Tokenizers and inspected metadata live in this repository. Download the large weights from the [v0.4.0 release](https://github.com/VerityLocal/Main/releases/tag/v0.4.0):

```sh
python -m backend.scripts.download_models
python -m backend.scripts.download_models --check
```

Run from the project root. The downloader installs both complete detectors and verifies the pinned hashes. See [model notes](../docs/MODELS.md) and [third-party notices](../docs/THIRD_PARTY_NOTICES.md).

# Verity Local model reference

## Text

- Upstream: [`desklib/ai-text-detector-v1.01`](https://huggingface.co/desklib/ai-text-detector-v1.01).
- Backbone: Microsoft DeBERTa-v3-large; masked mean pooling and one-logit head.
- Label 1: AI-generated English text. Raw sigmoid output is not calibrated confidence.
- Upstream model card declares the MIT license. See [third-party notices](THIRD_PARTY_NOTICES.md).
- Verity Local's checkpoint is byte-identical to the inspected upstream model. The local inference cap is 512 tokens including special tokens.

## Code

- Backbone: [`microsoft/codebert-base`](https://huggingface.co/microsoft/codebert-base), revision `3b0952feddeffad0063f274080e3c23d75e7eb39`.
- Custom rank-16, alpha-32 query/value LoRA adapter, masked mean pooling, and a linear head.
- Label 1: synthetic AI-style code. This is **not an AI-authorship probability**.
- Supported scoring domain: Python and JavaScript. Other and uncertain languages are withheld.
- The original artifact metadata retains the training project's historical name as provenance.
- Both training labels came from one synthetic generator. The 160-example synthetic validation had 78.125% accuracy, with 20/80 human-style examples flagged. This does not establish performance on real submissions.

## Installation and integrity

```sh
python -m backend.scripts.download_models
python -m backend.scripts.download_models --check
```

The text and code ZIPs are separate release assets to stay below GitHub's per-asset limit. Every inference file is pinned in [`backend/detectors/artifacts.py`](../backend/detectors/artifacts.py). The installer checks extracted artifacts before replacing files; the runtime checks them again before loading. The runtime never downloads replacements. PyTorch binary loading uses `weights_only=True`.

Weights total about 2.1 GiB, excluding Python dependencies. Models load once per backend process, defaulting to CPU. MPS/CUDA are configurable but only CPU parity is established here.

## Reading results

**Flagged content share** is the token-weighted share of scored content in chunks with a raw score strictly above the selected threshold. The default threshold is 0.5. The text and code shares are never combined. Missing scores are `null`/“Not scored”. Short, unsupported, excluded, and unread content is visible in coverage.

These outputs can produce false positives and are not proof of AI authorship or misconduct. Neither detector is validated for university submissions. The original PDF sample collection has no authorship labels, so its processing statistics are not accuracy measurements.

# Standard models and calibration

The Python app ZIP includes actual approved weights, tokenizers and model cards.
No model download occurs at first launch or during inference. Config paths are
resolved inside the app after relocation; the build-bound pin digest prevents an
edited manifest/pins file from silently authorizing different weights.

| Model | Role | Exact revision | License |
| --- | --- | --- | --- |
| desklib/ai-text-detector-v1.01 | English prose feature, mean-pooling/single-logit head | `5fdea974cd4287c61674951ec78803aa274e2fb7` | MIT, as declared by retained model card |
| BAAI/bge-small-en-v1.5 | English semantic source similarity | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | MIT, as declared by retained model card |

The selected raw model assets total approximately 1.9 GB **before** Python,
dependencies/browser and ZIP compression. Final measured ZIP sizes are published
separately. Docling-parse supplies text-layer PDF extraction (MIT), Playwright
consented retrieval (Apache-2.0), and Sentence Transformers semantic loading
(Apache-2.0). All notices/model cards stay inside the bundle.

## Boundaries

- **No AI-written percentage or calibrated confidence ships.** The calibration
  artifact has no fitted heads. Genuine eligible inference reports
  `calibration_required`; missing assets or unsupported inputs abstain.
- Desklib requires 8 GiB physical / 3 GiB available RAM before cold load; BGE
  requires 4 GiB / 0.5 GiB. CPU-only inference is not an OOM guarantee.
- All snapshot files are hashed before a cold model load. Missing, changed, extra
  or linked files fail verification. Loading is local-only, safetensors-only and
  remote-code-disabled. Oversize token sequences abstain rather than truncate.
- English support is bounded; code/prose routing is heuristic. The Standard app
  **excludes Falcon/Binoculars, GPTSniffer and a production reference-code corpus**.
  Code review/source comparison works, but no code authorship detector is enabled.
- Semantic relatedness alone is not copying. Lexical evidence and human review
  remain necessary. Failed semantic loading does not invent a probability.

`product/model-pins.json` records per-file sizes/digests. Only the two Standard
snapshots are shipped. Build-time downloads use reviewed HTTPS hosts and disable
proxy inheritance; app analysis never invokes the acquisition code.

## Calibration research

`product.tools.extract_scores` extracts genuine features from externally labeled
JSONL against a Standard bundle. `product.tools.train_calibration` fits grouped
train/validation/test logistic heads with `production_approved: false` by default.
Neither tool is a user-facing app setup requirement. Independent evaluation,
license/data-rights review and matching signatures are required before any future
authorship probabilities can be enabled. Functional fixtures and controlled source
matches are not calibration data, detector accuracy or upstream endorsement.

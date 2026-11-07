# Models, calibration and attribution

The shipped development product has **no provisioned AI checkpoints or approved
calibration**. AI estimates show **Unavailable**. There is no detector accuracy,
fine-tuning or proprietary-base-model claim. Source overlap is lexical unless an
explicitly configured semantic model is available; similarity is not misconduct
proof, and missing coverage is not counted as original text.

`product/runtime-config.example.json` documents optional signal configuration.
Obtain snapshots intentionally under reviewed license terms, verify exact revisions
and label mappings, and install compatible optional ML dependencies separately.
Keep each asset directory immutable and free of symlinks. Inventory a provisioned
asset with:

```sh
python -m product.tools.hash_assets --config product/.local/helper.json --signal text --output private/manifests/text.json
```

Set the resulting manifest path and SHA-256 in the signal configuration. Repeat for
other signals or semantic comparison. Never treat a snapshot name alone as proof
of integrity. Missing assets and invalid manifests abstain.

`product.tools.extract_scores` extracts genuine locally computed features from
externally labeled JSONL. `product.tools.train_calibration` fits small logistic
heads, enforces grouped train/validation/test separation, and reports held-out
metrics. Outputs remain `production_approved: false`; independent review is required
before activating a matching-signature head. The controlled copying templates in
tests are development fixtures, not AI-authorship training or a quality benchmark.

## Dependencies and optional integrations

| Component | Use / licensing boundary |
| --- | --- |
| [docling-parse](https://github.com/docling-project/docling-parse) | Native PDF parser; MIT, with transitive native notices to review. Installed separately. |
| [Playwright](https://github.com/microsoft/playwright) | Headless source retrieval; Apache-2.0. Browser binaries have separate notices. Installed separately. |
| [GPTSniffer](https://github.com/MDEGroup/GPTSniffer) | Optional code-only trained classifier adapter; checkpoint/source permission is required, disabled. A base CodeBERT model is not a trained prose detector. |
| [SameCode](https://github.com/aboutcode-org/ai-gen-code-search) | Optional known-AI code-corpus matching; Apache-2.0 plus NOTICE. Not an AI probability. |
| [Binoculars](https://github.com/ahans30/Binoculars) | Optional causal-model ratio method; review source and both model licenses. Very memory-intensive; raw ratios are not probabilities. |
| [Desklib detector](https://huggingface.co/desklib/ai-text-detector-v1.01) | Optional English authorship checkpoint with explicit pooling/logit adapter; review its MIT model card and data terms. Not a plagiarism model. |
| Sentence Transformers | Optional semantic similarity; review both library and selected snapshot licenses. Disabled until provisioned. |

The extension contains first-party code and a disabled calibration artifact, not
upstream runtimes or weights. Windows installer/native-launcher compiler licensing
is retained in the package. Any additional bundled code, browser or model must ship
its required LICENSE/NOTICE/copyright files. This document alone is not license
compliance or permission to redistribute restricted assets.

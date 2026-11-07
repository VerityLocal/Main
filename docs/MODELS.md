# Models, calibration and attribution

The existing extension and local desktop companions are preserved. Setup acquires
permitted immutable snapshots; inference is offline and does not download weights.
**AI percentages remain Unavailable until independently calibrated.** Successful
inference is not a detector-accuracy, data-rights or fine-tuning claim.

## Components and actual availability

| Component | Role | Development status / license |
| --- | --- | --- |
| [Docling / docling-parse](https://github.com/docling-project/docling-parse) | PDF text extraction | Native text-layer parsing tested; MIT. No OCR or ML layout-ordering claim. Native/transitive notices remain in the installed runtime. |
| [Playwright](https://github.com/microsoft/playwright) | Consent-based source retrieval | Actual browser retrieval with public-network restrictions; Apache-2.0. Controlled-source fixtures do not prove live-search recall. Browser binaries retain separate notices. |
| [Desklib](https://huggingface.co/desklib/ai-text-detector-v1.01) | English prose authorship feature | MIT model-card license. Automatically acquired on 8 GiB+ machines; mean-pooling/single-logit adapter, not bare DeBERTa. Needs 3 GiB available RAM before a cold load. |
| [Binoculars](https://github.com/ahans30/Binoculars) | Prose causal-model ratio feature | BSD-3-Clause method attribution; Falcon-7B and Falcon-7B-Instruct cards specify Apache-2.0. Automatically skipped below 64 GiB physical RAM; CPU float32 loading additionally requires 56 GiB available RAM. Full-pair inference has **not** been tested on this 16 GiB Mac. |
| [GPTSniffer](https://github.com/MDEGroup/GPTSniffer) | Code-only trained classifier | Adapter exists, but **checkpoint/permission required**. Upstream license metadata was absent at review; no permitted trained checkpoint was supplied or downloaded. Bare CodeBERT or an initialized head is not a substitute. An explicit verified AI-label index is required. |
| [SameCode](https://github.com/aboutcode-org/ai-gen-code-search) | Offline reference-code matching | SameCode 0.5.1 installed; Apache-2.0 + NOTICE retained. **Production corpus required** with reviewed rights and known-AI provenance. A genuine first-party AI-authored development fixture tests matching only, not accuracy or independent calibration. |
| [Sentence Transformers](https://github.com/UKPLab/sentence-transformers) | Semantic source similarity | Apache-2.0 library; MIT BAAI/bge-small-en-v1.5 snapshot. Automatically acquired on 4 GiB+ machines; needs 0.5 GiB available RAM before a cold load. Lexical evidence remains available if semantic inference fails. |

The supported profile is English, bounded single passages. Code/prose domain
selection is heuristic, not a verified language classifier. Oversize token sequences
abstain instead of silently truncating. Related-topic semantic similarity and
reference-code matching are not proof of copying or authorship.

## Pinned acquisition and resource boundary

`product/model-pins.json` records exact revisions, selected files, byte counts and
SHA-256 digests. The curated downloader accepts only reviewed HTTPS model hosts,
disables proxy inheritance, rejects executable/pickle weight formats, verifies
complete snapshots, and atomically promotes them. Changed snapshots are never
silently repaired or overwritten. Keep downloaded assets private and immutable.

| Snapshot | Exact revision | Selected download |
| --- | --- | --- |
| desklib/ai-text-detector-v1.01 | `5fdea974cd4287c61674951ec78803aa274e2fb7` | ~1.74 GB |
| BAAI/bge-small-en-v1.5 | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | ~134 MB |
| tiiuae/falcon-7b | `ec89142b67d748a1865ea4451372db8313ada0d8` | ~14.44 GB |
| tiiuae/falcon-7b-instruct | `8782b5c5d8c9290412416618f36a133653e85285` | ~14.44 GB |

The normal model download is ~1.9 GB, **in addition to** Python, parser/browser and
ML wheels. The Falcon pair adds ~28.87 GB download and ~57.74 GB of float32 weights
alone. Free disk space is checked per snapshot, with 1 GiB reserve. These are
conservative gates, not validated minimum hardware recommendations; other running
applications and temporary allocations can still prevent inference. No quantized,
GPU, reduced-memory or Intel-macOS execution claim is made.

Models live outside versioned runtime directories: `models/` and
`models-profile.json` under the private install root. Reinstallation reuses verified
snapshots and preserves pairing, custom assets and operator-disabled choices.
The extension's Settings displays neutral setup states. **Setup complete** means
the managed acquisition finished, not a successful inference or calibrated result;
custom and disabled settings are labeled separately.

`product/model-requirements.txt` pins direct ML dependencies and NumPy/Pandas
compatibility. Intel macOS uses the last supported upstream Torch wheel, 2.2.2;
Apple Silicon and Windows use 2.7.0. Transitive locks, vulnerability review and
platform-specific runtime acceptance remain production gates.

## Local functional validation (Apple Silicon, 16 GiB RAM)

Genuine offline inference with the pinned Desklib trained head and BGE-small passed,
alongside complete asset-hash verification and overlength abstention. A controlled
source match used real semantic inference; all document AI percentages/confidence
remained unavailable without calibration. One smoke run measured ~19.3 seconds for
the cold Desklib feature, ~0.29 seconds for cold semantic inference, and ~1.83 GiB
process peak RSS. These single-run figures are not supported minimums, performance
guarantees or independently labeled detector evaluation. Binoculars resource
abstention and genuine SameCode development-fixture matching passed; full Falcon
and GPTSniffer inference remain unexecuted.

A fresh standalone-runtime macOS sandbox install also passed actual Chromium
native messaging, automatic pairing/start/restart, PDF extraction and JSON export.
All eligible exported prose segments reported `calibration_required` after genuine
inference; short segments reported `insufficient_text`, with null scores/confidence.
Installed Desklib/BGE offline inference and hash checks passed separately. Browser
toolbar/default-profile flows and other platform gates remain untested.

## Custom assets and independent calibration

`product/runtime-config.example.json` documents optional custom configuration.
Obtain snapshots intentionally under reviewed source/checkpoint/data terms. Do not
infer data rights from a model-card license. Review exact revisions, classifier
architecture and label mappings. Inventory each complete local asset with:

```sh
python -m product.tools.hash_assets --config product/.local/helper.json --signal text --output private/manifests/text.json
```

Set the resulting manifest path and SHA-256 in configuration. Repeat for other
signals or semantic comparison; snapshot names alone do not prove integrity.
Missing, changed, extra or linked assets abstain. Custom code-corpus records require
`text`, `label: "known_ai"` and nonempty `provenance`, with reviewed rights; an
invented or AI-generated reference collection must not be labeled a production
corpus or independent evaluation set.

`product.tools.extract_scores` computes real local features from externally labeled
JSONL. `product.tools.train_calibration` fits small logistic heads with grouped
train/validation/test separation and held-out metrics. Outputs remain
`production_approved: false`; independent review is required before a matching
signature head can activate. Tests and demonstration passages are not authorship
benchmarks. Never use raw sigmoid/ratio/corpus features as AI percentages.

The extension ships first-party UI and a disabled calibration artifact, not models
or upstream runtimes. Model cards remain with snapshots; installed packages retain
LICENSE/NOTICE files. Required adapter attributions ship in
`product/THIRD-PARTY-NOTICES.txt`. Restricted code/checkpoints are not bundled.

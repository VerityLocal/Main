# Internal model card and attribution — not distributed in extension

## Ownership and operational reality

First-party: capture/UI, segmentation, lexical comparison, ensemble orchestration,
calibration trainer, helper boundary, consent handling, aggregates and export.
Not first-party: pretrained detectors, language models, parser and headless runtime.
No proprietary-base-model claim is warranted. No requested AI weights or real
ensemble-score labels were supplied or downloaded during this rebuild. No AI
probability/fine-tuning marketing claim is permitted until they are configured and
independently evaluated. AI confidence = max(p, 1-p); AI-written % = word-weighted
mean p on scored segments. This is an estimate, not a measured fraction of authored
tokens. Plagiarism % = mean matched similarity, weighted by query words; match
confidence is a distinct calibrated field. Quotes/common phrases/citations are not
automatically misconduct. Short segments (<12 words) abstain.

## Upstream credits and gates

| Upstream | Integration | License / limitation |
|---|---|---|
| Docling project / docling-parse 7.24.2 | primary native parser path, line cells | MIT; review transitive native notices before helper redistribution |
| Microsoft Playwright 1.64.1 | isolated headless search/source DOM normalization | Apache-2.0; browser binary has separate notices |
| MDEGroup GPTSniffer | local trained sequence classifier adapter, code only | repository root license not found; permission/checkpoint license required, disabled |
| aboutcode-org ai-gen-code-search / SameCode 0.5.1 | known-AI code corpus approximate fingerprint signal, code only | Apache-2.0 + NOTICE; not a binary prose classifier |
| ahans30 Binoculars | local causal-LM cross-entropy ratio method adapter | source-license review required before redistribution; paper academic-use cautions; raw ratio not probability |
| desklib/ai-text-detector-v1.01 | explicit local mean-pooling/logit wrapper, prose only | HF card MIT, English, trained on RAID; not a plagiarism model |
| Sentence Transformers / configured embedding snapshot | optional local semantic comparison | review library AND selected snapshot licenses; disabled until provisioned |

Links: https://github.com/docling-project/docling-parse,
https://github.com/microsoft/playwright, https://github.com/MDEGroup/GPTSniffer,
https://github.com/aboutcode-org/ai-gen-code-search,
https://github.com/ahans30/Binoculars,
https://huggingface.co/desklib/ai-text-detector-v1.01.

GPTSniffer paper: Nguyen et al., *GPTSniffer: A CodeBERT-based classifier to detect
source code written by ChatGPT*, JSS 2024, DOI 10.1016/j.jss.2024.112059.
Binoculars paper: Hans et al., *Spotting LLMs With Binoculars: Zero-Shot Detection
of Machine-Generated Text*, arXiv:2401.12070.
Docling report: Docling Team, arXiv:2408.09869.

Weights are never silently downloaded or random-initialized into output. Local
loaders forbid remote code, use safetensors and validate classifier loading keys.
All optional loaders require a digest-pinned complete local-file manifest, checked
before initial load; no symlinks or unlisted files. Snapshots must remain immutable
while the helper runs. Configuration signatures include that manifest digest.
Binoculars defaults can need >50GB CPU memory; provision intentionally, not as a
lightweight browser dependency. Changing scoring models invalidates thresholds.
No full-ensemble model execution or external-domain quality has been established.

## License compliance boundary

Extension build allowlist contains no upstream runtime/code/weights. This internal
credit file is excluded from `product/dist/*`. Separately installed dependencies
retain their licenses. **Internal attribution does not satisfy redistribution
requirements**: if shipping a helper, browser binary or model, include applicable
LICENSE/NOTICE/copyright, review restricted weights and obtain missing permission.
The branding constraint never authorizes removing required notices. Release gate:
record exact commits, license texts, transitive notices and dataset terms before
vendoring/redistribution. Do not assert all upstream licenses are already cleared.

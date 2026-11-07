# Re-alignment audit — internal, 2026-11-07

Written before implementation. This file and the historical research material are
not extension distribution inputs. No credentials or existing private data were read.

## Existing map

- `extension_mv3/manifest.json`: Chrome MV3, Chrome 116+, activeTab/scripting/storage/
  sidePanel; loopback permission only. `src/background/index.js` opens a panel and
  stores revisions. `src/content/index.js` chooses editor/DOM adapters and applies
  overlay highlights. `src/ui/panel.js` is a pasted-text/API/SSE client.
- `extension_mv3/build.mjs`: three bundled entries, static HTML/CSS copy, no clean
  output boundary. `package.json` pins esbuild, jsdom and Playwright; existing
  node_modules includes Windows binaries. Generated dist and ZIP are old releases.
- `backend/app/main.py`: authenticated loopback FastAPI factory; `/api/v1` routes;
  bounded inference queue, SQLite replay and local source corpus. Schemas in
  `backend/app/schemas` and `shared/schemas` use original UTF-16 offsets.
- `backend/app/document`: text normalization, offsets, regex sentence/passage
  splitting, canonical document construction. **No PDF byte extraction exists.**
- `backend/app/engines`: AI detector/stylometry, local-library plagiarism and
  hallucination/claim verification. `services/model_manager.py` leases pinned local
  models. `runtime/calibration.py` and `backend/scripts/` support research training,
  export and grouped evaluation, not the requested multi-signal calibration head.
- `pyproject.toml`/`uv.lock`: Python 3.11, server dependencies; optional torch,
  transformers, sentence-transformers, peft, spaCy, FAISS and ONNX stacks.
  `configs/`: hardware, model/retrieval/stylometry/evaluation policies.
- `tests/`: unit, integration, performance; extension tests: adapters/SSE and UI.
  `docs/`, `artifacts/`: internal implementation/training claims and historical
  Windows-specific validation. `.models/`, `.local-data/`, `.venv*`, `.env` are
  private/local assets, not distributable inputs. This workspace has no Git history.

## Built versus intended

| Existing piece | Decision | Reason / destination |
|---|---|---|
| MV3 side-panel scaffolding | Adapt | New PDF-first package, module worker, popup fallback |
| Safe text rendering, URL checks | Keep principle | Never insert untrusted document HTML |
| UTF-16 offset handling | Keep | Copy dependency-free checked index into clean engine |
| DOM extraction | Adapt | Read-only current website fallback; PDF takes precedence |
| Revision rejection | Adapt | Bind scans to tab ID, URL and extraction digest |
| PDF parsing | New | None to salvage; browser bytes to local lightweight parser |
| Local-library similarity | Adapt | Lexical alignment idea; replace library-management UX with attributed web retrieval |
| Dense/STS wrappers | Adapt principle | Optional local semantic model; do not call lexical overlap semantic |
| AI checkpoint pilot | Research only | Not requested ensemble, machine path/dependency claims not verified here |
| Training provenance/split leakage checks | Keep principle | New tiny-head trainer rejects group leakage, reports held-out metrics |
| Claim verification / hallucination | Drop from product | Unrelated third analysis and external evidence routing |
| Editor integrations, textarea, rich editor state | Drop from product | No authoring/editor objective |
| Pasted text and source-library panels | Drop from product | Replace with active PDF/website flow |
| GPU budgets, LoRA/NLI/retriever training | Drop from build | Historical research retained, not imported or packaged |
| Legacy README / ZIP / dist | Superseded | Preserve history internally; never distribute old bundle |

## Hardcoded assumptions / off-target behavior

Port 8787, English manual input, 20k character profile; current page rejects file
and browser viewers; only rendered DOM, no frames; AI pilot rejects documents over
512 tokens; local similarity only scans first 32 passages; Wikipedia web queries
are routed to claims, not plagiarism. Document-level AI score is probability of
*containing* AI, not the requested estimated fraction. No overall plagiarism %, no
original-text dual highlight reader, no export. Adapter families and NLI/evidence
logic are outside the new product dependency graph (not necessarily dead in the
historical platform). Existing data/weights will not be deleted or silently reused.

## Backbone feasibility and licensing gates

Reviewed upstream source/readmes on 2026-11-07:

- Docling's SimplePipeline does not accept a PDF backend. Prefer its lightweight
  `docling-parse` parser API for text-bearing PDFs, not an invalid SimplePipeline
  configuration or default model downloads. OCR/layout enrichment is optional
  future work; extraction order must be visibly reviewable.
- GPTSniffer (MDEGroup, master) is a CodeBERT **source-code** classifier; no root
  license identified by the repository API. Require a licensed trained checkpoint
  and explicit AI label mapping; never use an unfitted base model for prose.
- aboutcode-org/ai-gen-code-search is SameCode approximate code matching, not a
  human/AI probabilistic classifier. Apache-2.0 license + NOTICE exist. An offline
  known-AI code corpus can supply an auxiliary code-only match signal, not a prose
  classifier or calibrated probability by itself.
- Binoculars compares two 7B causal models; raw score decreases with AI evidence,
  and is not a probability. CPU FP32 can require >50 GB for weights alone.
  Defaults download and enable remote code; a local-only wrapper must not do that.
- desklib/ai-text-detector-v1.01 is English AI authorship, **not plagiarism**.
  Its custom mean-pooling/single-logit architecture needs an explicit local wrapper.
- Playwright belongs in the helper, not MV3. Candidate retrieval must require
  consent, limit requests, normalize visible text, attribute URLs and reject private
  network destinations/redirects/subresources. Search failure means unavailable,
  not 0% plagiarism. No web snippets are treated as matched full sources.

Code-only signals are excluded for prose. Missing weights, unsupported input,
uncalibrated heads and partial web coverage must be explicit. No supplied real
ensemble-score training dataset exists here; do not fabricate calibrated weights,
accuracy or an in-house fine-tuning claim. Provide a genuine trainer and fail-closed
artifact until real held-out labels/scores are available.

Branding can omit implementation names, but required notices cannot be omitted
when redistributing upstream code/weights. The clean extension will contain only
first-party JavaScript + calibration artifacts, with upstream runtimes installed
separately. Any future redistributed helper/model bundle requires a separate
license/NOTICE review; internal attribution alone is not compliance.

## New development boundary / acceptance

`product/extension` is the only extension build input; `product/engine` is the
offline-first local helper; `internal/` holds model card, retraining and tests/demo.
Legacy trees remain archived in place, excluded by explicit build allowlist.
Target: active PDF (native viewer, PDF.js bytes, embed/iframe); read-only website
fallback; per-segment probability/status/source, word-weighted aggregates, both
highlight colors including overlap, export, permission/consent/cancellation and
safe failure. Automated fixture tests are not production detector validation.

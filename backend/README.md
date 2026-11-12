# Verity Local backend

The backend accepts complete PDF bytes, reports real job progress, extracts
all pages, separates prose/code/exclusions, chunks with the actual tokenizers,
and returns separate probabilistic detector summaries with page attribution.
The Manifest V3 extension is in `extension/`; see `extension/README.md` for setup.
Schema `2.0` adds original UTF-8 source provenance and visible unscored passages.

**[Install dependencies and models](../docs/SETUP.md)** · **[Downloads](https://github.com/VerityLocal/Main/releases/tag/v0.4.0)** · **[Website](https://veritylocal.github.io/)**

## Current capability and important limitations

- **Working/tested:** native extraction, both existing local
  detectors, analysis/progress API, unit/integration tests, resource limits, and
  coverage reporting. The default requirements use pdfplumber and Pillow.
  Optional isolated PyMuPDF/Tesseract extraction is also supported.
- **Optional:** Docling layout/table model assets.
  Learned layout inference is not enabled without
  explicitly configured, hash-manifested local assets. Multi-column/table/rotation
  parity is not established; installation is not proof of extraction quality.
- Raw UTF-8 `.py`, `.js`, and `.txt` uploads are supported. Source provenance uses
  original character offsets and line numbers, not fabricated PDF coordinates.
- Screenshot/scanned regions are reported as unread when OCR is unavailable.
  They do not receive invented scores. Recognized OCR code is withheld by default
  because punctuation/indentation errors can change source semantics.
- Language and segmentation gates are conservative heuristics, not validated
  language classifiers. Non-English/unknown prose and out-of-domain/unknown code
  are withheld. Python/JavaScript code remains an experimental synthetic-style
  signal, **not AI-authorship probability**.
- Native PDF whitespace is reconstructed from geometry and may not match the
  original source file. Extracted code is not normalized or silently rewritten.
- Tables, numeric/terminal outputs, repeated margin boilerplate, references,
  formulas, and metadata are excluded; ambiguous pseudocode is marked uncertain.
  Source listings in bordered or ruled form cells are recognized separately from
  data tables when sufficient syntax/language evidence is present.
  Heuristics can make mistakes: review both coverage and flagged passages.

See `backend/DEPENDENCIES.md` for default dependencies and optional tools.

## Run locally

From the project root:

```sh
source .venv/bin/activate
python -B -m backend.scripts.run_local --extension-id YOUR_EXTENSION_ID
```

Allow time and several GB of RAM for model startup. Use one worker and avoid
`--reload` during normal use; each worker/restart loads its own model copies.
Keep the server bound to loopback. Every API request requires the configured
bearer token; the service fails closed without it. Browser access is limited to
the exact configured extension origin, with restricted preflight and Host checks.
The launcher creates a private `.local/backend-token` without printing its value
and selects the installed isolated parser/OCR tools. Do not expose this service
to a LAN or the internet.

### Health

`GET /health`: 200 when **both models** are ready, 503 otherwise, with independent
model errors and PDF/OCR capability information. `analysis_available` can still
be true if one modality's model is ready; the other modality returns unavailable
instead of a zero score. It is false before startup or without a native parser.
`ocr_configured` is a tool probe; English language data is checked per job.

### Submit a PDF

```sh
curl -X POST 'http://127.0.0.1:8000/analyze?threshold=0.5' \
  -H "Authorization: Bearer $(cat .local/backend-token)" \
  -H 'Content-Type: application/pdf' \
  --data-binary '@test/16014225801 ML EXP 1.pdf'
```

Returns 202:

```json
{"job_id":"...","status":"queued","status_url":"/analyze/..."}
```

Poll the returned `status_url` to obtain `receiving/queued/running/completed/failed`
status, the actual stage, progress, and the eventual result/error:

```sh
curl -H "Authorization: Bearer $(cat .local/backend-token)" \
  'http://127.0.0.1:8000/analyze/REPLACE_WITH_JOB_ID'
```

Stages: validation → native/layout extraction → selective OCR if needed →
segmentation → text/code scoring → aggregation. Progress is a stage-weighted
indicator, not a completion-time estimate. `stages_seen` makes short phases
visible even if polling misses them. No multipart dependency is needed; URLs,
client-supplied local paths, HTML responses, and filename-only requests are not
accepted. Remote/file-viewer PDF acquisition belongs to the extension phase.

Uploads are size-limited while streaming and validated before queueing. Malformed
PDFs can still pass the basic signature check and then fail during parsing; the
job reports this explicitly. Encrypted PDFs are rejected, even with empty passwords.

### Result semantics

`text` and `code` are never combined into an authorship score. Each includes:

- `status`: scored, no content, model unavailable, insufficient/unsupported, or
  inference failed. Absent/unusable scores are **null**, never placeholder zeroes.
- `flagged_content_share`: sum of content tokens in scored chunks whose raw
  score is **strictly greater** than the threshold, divided by all scored content
  tokens. Special tokens/padding and source overlap are not counted.
- `raw_mean_model_score`: arithmetic mean of scored chunk probabilities; this is
  **not** the same measure as the length-weighted flagged share.
- `signal_band`: low (<20% flagged share), moderate (20–<50%), high (≥50%). These
  are documented heuristic detector-signal bands, not calibrated authorship verdicts.
- Candidate/analyzed counts, skipped-token reasons, and minimum-content policy.
- `chunk_scores` with provenance and expandable `flagged_passages` containing
  exact analyzed text, raw probability, section, pages, bounding boxes, extraction
  method, and character ranges. Coordinates are PDF points, top-left origin.

Coverage reports every processed page, native/OCR character counts, image-region
statuses, exclusions, and unread regions. **No percentage of unseen visual
content is estimated.** A completed job may contain no scores if content is
unsupported or insufficient. The disclaimer is always present.

If a batch fails, no partial scores are published for that modality. The other
modality can succeed. Parser/content/chunk/time limits fail the whole job rather
than silently scoring a subset.

## Configuration

All fields use `PDF_AI_` plus the uppercase name below, except where noted.
Invalid configuration fails immediately.

| Field | Default | Purpose |
| --- | --- | --- |
| `MODELS_DIR` | Project `models/` | Inspected local detector checkpoints |
| `DEVICE` | `cpu` | `cpu`, `mps`, or `cuda`; only CPU parity was tested |
| `MAX_TOKENS` | 512 | 8–512 including special tokens |
| `BATCH_SIZE` | 4 | 1–64 |
| `TORCH_THREADS` | 4 | 1–64 CPU threads |
| `THRESHOLD` | 0.5 | Finite, 0–1 |
| `MAX_UPLOAD_BYTES` | 52428800 | 50 MiB upload limit |
| `MAX_PAGES` | 500 | Reject larger documents, not truncate |
| `MAX_EXTRACTED_CHARS` | 2000000 | Content budget |
| `MAX_CHUNKS` | 4096 | Per-modality chunk budget |
| `MAX_ACTIVE_JOBS` | 3 | One running job plus uploads/queued work |
| `MAX_RETAINED_JOBS` | 16 | Bounded in-memory result count |
| `RESULT_TTL_SECONDS` | 900 | Completed result lifetime, subject to earlier capacity eviction |
| `UPLOAD_TIMEOUT_SECONDS` | 30 | Whole-upload deadline |
| `EXTRACTION_TIMEOUT_SECONDS` | 120 | Hard parser/OCR subprocess deadline |
| `JOB_TIMEOUT_SECONDS` | 600 | Checked between stages and inference batches |
| `MAX_RENDER_PIXELS` | 8000000 | OCR image/backing-page rendering budget |
| `MAX_OCR_REGIONS_PER_PAGE` | 20 | Excess regions explicitly reported unread |
| `MIN_TEXT_CHUNK_TOKENS` / `MIN_TEXT_TOTAL_TOKENS` | 80 / 150 | Conservative prose guards |
| `MIN_CODE_CHUNK_TOKENS` / `MIN_CODE_TOTAL_TOKENS` | 40 / 80 | Conservative code guards |
| `DOCLING_ASSETS_DIR` | Unset | Explicit approved local layout assets + manifest |
| `EXTRACTION_PYTHON` | Current interpreter | Isolated parser interpreter; keep venv symlinks intact |
| `TESSERACT_COMMAND` / `TESSDATA_DIR` | `tesseract` / unset | Explicit local executable and language data |
| `AUTH_TOKEN` | Unset; fails closed | At least 32 URL-safe characters; never sent to parser workers |
| `EXTENSION_ID` | Unset | Exact Chrome/Edge extension ID; no wildcard browser origins |
| `TEMP_DIR` | OS temp `verity-local` | Private per-job working directories |

Minimum-content guards are policy choices, **not validated reliability minima**.
Token budget changes can intentionally cause more fragments to be withheld.
Inference timeouts cannot preempt a currently running PyTorch call; they are
checked at batch boundaries. PDF parser/OCR work runs in a disposable process
with a hard deadline and Python network connections disabled. This is resource
isolation, **not a hardened OS sandbox** for hostile documents.

Temporary PDFs/OCR images/cache files are normally removed on completion, failure,
and shutdown. Cleanup errors explicitly fail the job and require checking logs
for manual cleanup. Results are in memory only and expire; restarts lose all jobs.
An abrupt process/OS crash can leave private temp directories requiring manual
cleanup. Documents are never sent to external inference services. API results are
not persisted. Clear-review does not cancel already submitted backend jobs.

## Model integrity and limitations

Both models still load once at startup with inspected SHA-256 checks for every
inference artifact. Missing/swapped weights or tokenizers fail explicitly and
are never auto-replaced. PyTorch `.bin` loads use `weights_only=True`, all weights
match strictly, and custom LoRA merges use `W += 2 * (B @ A)` in evaluation mode.

- Text: byte-identical to `desklib/ai-text-detector-v1.01`; attention-masked mean
  pooling → one-logit linear → sigmoid; **1 = AI text**. Original text training
  maximum is undocumented; 512 is a conservative inference cap.
- Code: CodeBERT + custom rank-16/alpha-32 query/value LoRA, masked mean pooling
  and linear/sigmoid head; **1 = synthetic AI-style code**. Both training labels
  came from one synthetic generator. Reproduced validation: 160 examples,
  accuracy 78.125%, TP 65, FP 20, FN 15, TN 60. The 25% synthetic human-style
  false-positive rate is **not** real student-code accuracy. C/C++, Java, HTML,
  SQL, and unknown code are withheld rather than presented as validated.

**Scores are probabilistic, can produce false positives, and are not proof of AI
authorship or academic misconduct. Raw sigmoid scores are not calibrated confidence.**

## Test and evaluate

Install `requirements-dev.txt` before running the test suite.

```sh
python3 -m unittest discover -s backend/tests -v
```

Include real-model offline tests:

```sh
PDF_AI_RUN_MODEL_TESTS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m unittest discover -s backend/tests -v
```

Tests include synthetic PDFs (generated in temporary directories with already
installed ReportLab/Pillow), real native extraction, encrypted/corrupt/empty/page
limits, prose/code/output segmentation, non-English/unsupported handling,
nonoverlapping Unicode chunks, page attribution, aggregation, upload validation,
bounded jobs, cleanup, expiry, and both real detectors end to end.

Read-only evaluation of the existing PDFs, with summaries but **no persisted
passage text** and **no authorship accuracy claims**:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python3 -m backend.scripts.evaluate_pdfs --input test --output backend/evaluation/new-report.json --score
```

Omit `--score` for extraction-only evaluation. Existing output files are not
overwritten unless explicitly requested with `--overwrite`. `models/` and the
original PDFs remain unchanged. Ground-truth authorship metrics remain null
because the 34 sample PDFs have no labels.

### Historical Phase 2 fallback results (2026-11-11)

- **59/59 tests passed**, including the opt-in real-model tests with offline settings.
- A temporary loopback Uvicorn server returned HTTP 200 health, HTTP 202 upload,
  and a completed two-page PDF result scored by both real detectors; it was stopped.
- `backend/evaluation/phase2.json`: **34/34 PDFs, 279 pages processed**, no parser failures.
  Prose scored in 31 documents (28,609 tokens); code scored in 16 (23,222 tokens).
  Other modality results were absent, too short, uncertain, or unsupported—not zero scores.
- **984 image regions remain unread** without OCR. Increased unread reporting
  reflects conservative image/text-overlap checks, not newly missing PDF pages.
  These are extraction/processing measurements, not detector accuracy.
- Extracted-text duplicate pairs: `WSAPI_EXP6.pdf` / `exp 6.pdf`, and
  `exp 8.pdf` / `exp 9.pdf`; originals were retained.
- Original `models/` (17 files) and `test/` (34 files) exactly match their initial
  recursive fingerprints. Private analysis/evaluation temporary directories were cleaned.

These historical native-fallback measurements predate the optional local OCR
integration. They measure processing coverage, not real-document authorship accuracy.

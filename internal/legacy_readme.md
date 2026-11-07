# Historical README — superseded, not distributed

The active product is documented in the repository root README. This research
baseline is retained for provenance, not installation or marketing.

# Verity Local — AI Analysis Platform

Chrome Manifest V3 side panel + authenticated local FastAPI backend, with three
independent analysis pipelines. **A local development baseline with a trained
English AI-detector pilot.** Model weights and datasets live in private local
storage and are not bundled with the extension. Production acceptance and full
editor compatibility remain outstanding.

## What works now

- Local source library, lexical winnowing/MinHash/BM25 retrieval, and original-offset alignment.
- Rule-based claim candidates, evidence retrieval, citations and insufficient-evidence handling.
- Optional pinned local BGE, STS, reranking, NLI and claim-decomposition model execution.
- Exactly 24 stylometric features, missingness, DeBERTa fusion/two heads,
  overflow-window aggregation and checkpoint compatibility checks.
- CPU/CUDA LoRA training tools, leakage checks, held-out calibration/evaluation, and FP32 ONNX export.
- Secured loopback API, revision checking, serial inference, cooperative cancellation and SQLite SSE replay.
- Built extension with pasted-text/page analysis, source management, safe result rendering,
  non-destructive highlights, domain exclusions, revision invalidation and reconnection.

**This machine is configured with the trained, calibrated English LLMTrace
checkpoint**, verified through the live API. Unconfigured installations report
AI detection as unavailable. Without NLI weights, claims return
`INSUFFICIENT_EVIDENCE`. Semantic paraphrase and NLI thresholds remain
experimental, uncalibrated proposals.

The pilot completed three CUDA BF16 epochs on the RTX 3050, with 1,536 successful
optimizer updates and zero skipped updates. On 1,536 held-out documents it measured
**79.82% accuracy, 0.7901 macro-F1 and a 21.96% human false-positive rate at 0.5**.
Scores estimate whether annotated AI content is present, including mixed writing.
The trained profile accepts English text up to **512 tokenizer tokens**.
See the [training, evaluation and deployment report](artifacts/llmtrace_pilot_validation_2026-11-05.md)
for sentence metrics, calibration limitations and within-corpus scope. The
[checksum and split audit](artifacts/llmtrace_import_validation_2026-11-05.md)
records 7,168 selected documents, span-derived labels and near-duplicate grouping.

See [implementation status](docs/implementation_status.md),
[architecture](docs/architecture.md), [training](docs/training.md),
[security/privacy](docs/security.md), [compatibility](docs/compatibility.md) and
[actual validation](artifacts/implementation_validation.md).

## Run on this Windows machine

From `local-ai-analysis-platform`:

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.app.main
```

The private `.env` has already been created; do not regenerate or publish it.
The server listens on `http://127.0.0.1:8787`. Run one worker, not a reverse proxy.
`LOCAL_AI_DETECTOR_CHECKPOINT` already points to
`%LOCALAPPDATA%\VerityLocal\models\llmtrace_detector_pilot_v1_retry1`.
Use `.venv-cuda` for a CUDA-trained checkpoint even though serving is FP32 CPU;
the artifact validates exact dependency versions, including the Torch build.

### Install the extension

1. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**.
2. Select `local-ai-analysis-platform\extension_mv3\dist`.
3. Copy its extension ID, then run from the project directory:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.scripts.pair_extension YOUR_EXTENSION_ID
   ```

4. Restart the backend. Open the extension side panel and its connection settings.
5. Copy `LOCAL_AI_AUTH_TOKEN` and `LOCAL_AI_CSRF_TOKEN` from your private `.env`
   into the corresponding fields. They are stored only in trusted extension storage.
6. Add a reference source to the local library, paste text or choose **Read current
   page**, and click **Analyze locally**.

If entering the tokens and sample is difficult, run this from the project directory
after starting the backend and pairing the extension:

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.setup_extension
```

It reads `.env` and copies a setup command to your clipboard. Right-click **inside
the Verity extension panel**, choose **Inspect**, select **Console**, paste and
press Enter. The command saves the connection, adds a sample reference and runs
AI/similarity analysis on matching text. Existing domain exclusions are preserved.
The helper prints no credentials; the copied command runs only in a paired Verity panel.

Only explicitly extracted rendered content is analyzed. Google Docs canvas,
iframes, closed shadow roots and unrendered virtualized text are unsupported.
The extension assumes the default backend port, 8787.

Runtime source and event databases default to
`%LOCALAPPDATA%\VerityLocal\data`, outside this workspace;
they are plaintext, not encrypted. Older `.local-data` directories are not migrated
or deleted automatically. Model downloads default to `.models` and can be redirected
with `LOCAL_AI_MODEL_CACHE`.

## Fresh installation / reproducible dependencies

Python 3.11 and Node.js with npm are required. The existing project-local uv is pinned:

```powershell
.\.tooling\Scripts\uv.exe sync --frozen --group dev --extra ml --extra faiss --extra export
.\.venv\Scripts\python.exe -m backend.scripts.init_local
```

The initializer refuses to overwrite an existing `.env`. On a fresh checkout
without `.tooling`, install `uv==0.6.17` in a separate tooling environment and run
the same frozen sync. `ml`, `faiss` and `export` are optional; lexical analysis
works without them. The `ml` extra pins the CPU PyTorch wheel. CUDA training uses
the mutually exclusive `ml-cuda` extra and `.venv-cuda`; see
[CUDA setup and training](docs/training.md#cuda-environment-on-this-windows-machine).
Actual RTX 3050 training-step measurements are recorded in
[CUDA validation](artifacts/cuda_training_validation_2026-11-05.md).
Do not run a uv sync that omits your desired extras: it may remove them.

From `extension_mv3`:

```powershell
npm.cmd ci
npm.cmd run build
```

`package-lock.json` pins dependencies. Build output is `dist`; Playwright tests
use installed Chrome and do not download browser binaries. A loadable ZIP is
also provided as `extension_mv3\verity-local.zip`.
Extract the ZIP first; Chrome's **Load unpacked** requires a directory, not a ZIP.

## Optional model downloads (explicit network access)

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.download_models dense_retriever similarity_verifier nli_verifier cross_encoder --enable
```

Review `configs/models.yaml` licenses and exact revisions first. The command
downloads weights, enables only named models, and requires a server restart.
Analysis/startup never downloads weights. `claim_extractor` is an unvalidated
FLAN-T5 decomposition candidate; it is not established as an atomic-fact extractor.
Download `ai_backbone` for training, not direct detection.

External evidence is **off by default**. Enabling requires both
`LOCAL_AI_EXTERNAL_SEARCH_ENABLED=true` and
`configs/retrieval.yaml: external_search.enabled: true`, plus per-request consent.
Up to three sentence queries (each limited to 256 characters) go to Wikipedia.
Returned evidence is unrated and is not automatically treated as authoritative.

## API

Every endpoint needs `X-Local-Token`. POST also needs `X-CSRF-Token` and JSON content.

| Route | Purpose |
|---|---|
| `GET /api/v1/health` | Hardware and component availability |
| `POST /api/v1/documents/register` | Canonical revision registration |
| `POST /api/v1/analyses` | Submit canonical document and selected engines |
| `POST /api/v1/analyses/text` | Submit browser extraction; server builds normalization maps |
| `GET /api/v1/analyses/{id}` | Terminal/request identity |
| `GET /api/v1/analyses/{id}/events` | Authenticated SSE replay; numeric `Last-Event-ID` |
| `POST /api/v1/analyses/{id}/cancel` | Cooperative cancellation |
| `GET /api/v1/models/status` / `POST /api/v1/models/unload` | CPU model lifecycle |
| `GET /api/v1/sources` / `POST /api/v1/sources` | Local reference library |
| `POST /api/v1/sources/{id}/remove` | Remove a reference source |

Schemas live in `shared/schemas`. Browser-facing ranges are original,
half-open **UTF-16 code units** with document/revision identity. AI scores are
not authorship proof; similarity is not misconduct proof; missing evidence is
not falsehood. Detailed claims are streamed once; the final claim event summarizes
the count rather than duplicating all evidence.

## Validate

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m backend.scripts.export_schemas --check
.\.venv\Scripts\python.exe -m backend.scripts.benchmark --synthetic --runs 3 --output artifacts/new-fixture-timing.json
```

From `extension_mv3`:

```powershell
npm.cmd test
npm.cmd run test:browser
npm.cmd audit
```

Historical Phase 0 results remain in [phase0_validation.md](artifacts/phase0_validation.md).
The [current pilot report](artifacts/llmtrace_pilot_validation_2026-11-05.md) records
the measured CUDA training, held-out metrics and live checkpoint verification.
Real editor-model integration and production performance remain acceptance work.

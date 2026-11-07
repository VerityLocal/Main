# Implementation and validation report

Date: **2026-11-04**. Outcome: executable local development baseline across the
three engine pipelines, secured runtime, training tools and MV3 extension.
**Not a production-readiness, model-accuracy or universal-browser certification.**
The [historical Phase 0 report](phase0_validation.md) is preserved unchanged.

This report records the **2026-11-04** state. Subsequent model installation, CUDA
setup, LLMTrace import, completed GPU training and live deployment measurements
are linked from [artifacts/README.md](README.md).
Use the main [README](../README.md) for current launch instructions and
[implementation status](../docs/implementation_status.md) for current capabilities.

## Delivered files and capabilities

- `backend/app/engines/ai_detection/`, `stylometry/`: exactly 24 features,
  missingness, training-only normalization, DeBERTa fusion/two heads, original
  UTF-16 sentence masks, overflow aggregation and compatible CPU checkpoint loading.
- `backend/app/engines/plagiarism/`: winnowing, MinHash LSH, lexical alignment,
  BM25 candidates and optional local BGE/FAISS/STS candidate verification.
- `backend/app/engines/hallucination/`: original-span sentence candidates,
  optional FLAN-T5 decomposition, related-pair retrieval, evidence retrieval,
  RRF/reranking, NLI and four-state evidence aggregation with citations.
- `backend/app/services/`, `runtime/`, `api/v1/`: bounded local corpus and replay,
  independent engine failures, one serial CPU worker, cooperative cancellation,
  restart termination, model leases/status/unload and authenticated SSE endpoints.
- `backend/scripts/`: AI/BGE/NLI CPU LoRA training, feature extraction, leakage
  checks, AI calibration/evaluation, FP32 cross-encoder ONNX export, explicit
  pinned downloads, extension pairing, synthetic timing and schema checks.
- `extension_mv3/`: buildable MV3 side panel, isolated content injection,
  pasted/rendered text extraction, local reference library, domain exclusions,
  revision invalidation, authenticated fetch SSE and non-destructive highlights.
- `shared/schemas/`: six exported JSON Schema contracts; tests and current
  architecture, privacy, feature/tensor, training and compatibility documentation.

## Executed checks — actual results

Commands below run from the project root unless noted otherwise. No fabricated
or skipped test results are substituted for missing model validation.

| Command | Observed result |
|---|---|
| `.venv\Scripts\pytest.exe -q` | **186 passed, 3 warnings in 24.41 seconds** |
| `.venv\Scripts\ruff.exe check .` | All checks passed |
| `.venv\Scripts\ruff.exe format --check .` | 96 files already formatted |
| `.venv\Scripts\python.exe -m backend.scripts.export_schemas --check` | All six artifacts match executable contracts |
| `.tooling\Scripts\uv.exe lock --check` | Frozen lock is current; 95 packages resolved |
| `.tooling\Scripts\uv.exe pip check` | 93 installed packages checked; all compatible |
| `npm.cmd run build` in `extension_mv3` | Built `dist` successfully |
| `npm.cmd test` in `extension_mv3` | **9 passed**, zero failures/skips |
| `npm.cmd run test:browser` in `extension_mv3` | **6 real-Chrome fixture checks passed** |
| `npm.cmd audit --json` in `extension_mv3` | Zero known vulnerabilities at check time |
| ZIP CRC/read-back and manifest checks | Six entries match `dist` byte-for-byte; manifest at archive root |

Frozen dependency sync was executed with `--group dev --extra ml --extra faiss
--extra export`. Installed examples: torch **2.7.0+cpu**, transformers 4.51.3,
sentence-transformers 4.1.0, peft 0.15.2, spaCy 3.7.5, NumPy 1.26.4, FAISS 1.11.0,
ONNX 1.17.0 and ONNX Runtime 1.21.1. Playwright was updated to pinned 1.64.1
after its prior version's download-certificate advisory was discovered.

The three Python warnings were **not suppressed**:

1. Starlette TestClient's deprecated AnyIO `BlockingPortal` alias.
2. spaCy's deprecated Click `parser.split_arg_string` import.
3. Legacy torch ONNX export logging deprecation.

npm installation also reported esbuild's install script as not covered by
`allowScripts`; the successful build is not a blanket approval of install scripts.
Dependency compatibility and npm audit do not constitute a complete Python
vulnerability, supply-chain or license audit.

### What the tests establish

Python tests cover strict Unicode/normalization contracts, security boundaries,
stale revisions, bounded storage/replay, authenticated analyses, real-loopback
CLI launch, cooperative serial cancellation, engine-error isolation, leakage,
feature missingness, tiny neural artifact execution and tiny CPU ONNX parity.
CLI help smoke checks cover the delivered training/evaluation/download tools.

Final scoring regression tests verify that STSB's one-label **sigmoid** matches
the pinned model card and installed CrossEncoder default while relevance logits
stay raw. Oversized STS pairs abstain. Claim prompts over 512 tokens and capped
generation without EOS fall back to the original complete sentence; omitted
propositions and coverage limitations are explicit. Calibrated AI findings now
also validate against the shared Finding contract and the original document.

These synthetic neural tests do **not** prove that pinned pretrained models load,
that a real detector is trained, or that any model has useful accuracy.

### Browser scope

Installed Chrome version: **156.0.8078.80**, Windows. Passed cases are recorded
in [browser_validation.json](browser_validation.json):

1. Static DOM Unicode/range geometry and non-destructive highlights.
2. Text-control mirror geometry, scroll/selection preservation and mutations.
3. Rendered editor-shaped DOM fixtures and mutation invalidation.
4. Content-script stale-highlight rejection.
5. Panel preview, UTF-16 counting and empty-submission rejection.
6. Synthetic panel transport, streamed results and manual-edit invalidation.

The fixtures use installed Chrome with synthetic content/transport mocks. They
do not install the actual MV3 package or integrate real ProseMirror/Lexical/Quill/
Slate document state. No browser-version range, universal website compatibility,
pixel-perfect geometry, zoom/RTL coverage or worker/panel restart certification
is claimed. [extension_panel.png](extension_panel.png) is a UI fixture screenshot.

## Synthetic CPU timing observation — not a model benchmark

[cpu_fixture_benchmark.json](cpu_fixture_benchmark.json) was recorded earlier
on the same date, before final scoring/coverage hardening. It is a small labeled
fixture observation, not a comparative performance or accuracy result.

- CPU: Intel i5-11400H, six physical / twelve logical cores; Python 3.11.9.
- RAM snapshot: 16,952,647,680 bytes total, 4,120,739,840 bytes available.
- GPU observed by driver: RTX 3050 Laptop, **4,294,967,296 bytes (4 GiB) VRAM**.
  Installed CPU torch has no CUDA; the GPU was not used for these functions.
- Input: 87 Python code points, one same-text synthetic source, two rule sentence
  candidates. No detector tokenizer: input model token count is unavailable.
- One synchronous function at a time, no concurrent API requests. No neural
  model batches executed; batch/FP32/FP16/provider comparisons are inapplicable.
  Feature arithmetic is Python scalar arithmetic, not a tensor precision benchmark.
- One first call and three repeats per function; no model weights enabled.
  The light extractor lacks the detector tokenizer, POS and reference LM.

| Function | First call (ms) | Median of three repeats (ms) |
|---|---:|---:|
| Lexical similarity fixture | 20.94 | 18.64 |
| Rule claims/local lexical evidence fixture | 13.91 | 13.47 |
| Light features without detector tokenizer | 898.36 | 0.152 |

First-call time includes incidental imports; it is **not model cold-load latency**.
RSS values are before/after observations, not sampled peaks. p95, throughput,
real-model peak RAM/VRAM, accuracy, full-corpus scaling and GPU fit were not measured.
Test-suite duration above is not inference latency.

## Package and run handoff

Extension ZIP: [`extension_mv3/verity-local.zip`](../extension_mv3/verity-local.zip),
**16,521 bytes**, containing only `background.js`, `content.js`, `manifest.json`,
`panel.css`, `panel.html` and `panel.js`. No credentials, datasets or model weights.
Entry order and archive timestamps were fixed for this package.

SHA-256:

```text
c54fa93e1874a0f90e4d9e023ff7475a876808c3b3170e04d2b36a6555ea6109
```

From `local-ai-analysis-platform`:

```powershell
.\.venv\Scripts\python.exe -m backend.app.main
```

Load `extension_mv3\dist` through Chrome Developer mode → **Load unpacked**.
Alternatively extract the ZIP and load that directory. Pair the displayed ID:

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.pair_extension YOUR_EXTENSION_ID
```

Restart the backend and enter the existing private `.env` auth/CSRF values in
the extension connection settings. Pairing preserves existing credentials.
Add a local reference source before testing similarity/evidence. See the
[README](../README.md) for full setup and optional explicit model downloads.

## Exact remaining blockers and limitations

- **No approved labeled data or real trained/calibrated AI detector.** AI
  detection is unavailable by default. An explicitly configured trained but
  uncalibrated artifact can expose scores for evaluation, never calibrated confidence.
- **No pretrained weights downloaded/enabled.** Semantic/NLI/decomposition
  execution against the actual pinned snapshots remains unvalidated. Claims
  without NLI are insufficient evidence, not truth judgments.
- STS 0.8 and NLI 0.85 thresholds are proposals, not fitted calibration.
  Claim atomicity, generated factual fidelity, temporal reasoning and user-asserted
  source trust are experimental. Similarity is not proof of plagiarism intent.
- Full rich-result typing, similarity/claim dataset evaluators, production
  retriever/NLI fine-tune registration and a multi-provider evidence abstraction
  remain incomplete. Exact/group leakage checks do not infer near-duplicate families.
- Google Docs canvas, iframes, closed roots and unrendered virtualized content
  are unsupported. Real editor state, MV3 lifecycle and exhaustive geometry
  acceptance remain outstanding. Default extension loopback port is fixed at 8787.
- GPU execution is disabled. ONNX verification used tiny synthetic CPU fixtures,
  not pinned-model exports or a quantization/accuracy comparison. No claimed model fit.
- Cancellation/deadlines cannot preempt native model calls; the next request
  waits for the thread to return. Detector weights currently load per analysis;
  corpus indexes rebuild per analysis, with dense embeddings cached only within it.
- Private corpus/replay SQLite is plaintext under `%LOCALAPPDATA%\VerityLocal\data`
   by default, not encrypted or securely erased. Existing older databases were
   not migrated/deleted. Correction: the workspace has a OneDrive-named parent
   directory, but the user reports OneDrive is not installed; the path alone
   does not establish active synchronization.
- External evidence is off by default. Both settings plus request consent must
  authorize Wikipedia queries. It receives up to three sentence queries capped
  at 256 characters each; returned sources remain unrated.

All changes remain local; no commit, push or issue publication was performed.
See [implementation_status.md](../docs/implementation_status.md) for runtime
bounds and production acceptance gates.

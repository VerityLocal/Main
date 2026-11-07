# Implementation status and remaining acceptance gates

This supersedes the Phase 0-only status notes. The historical report is retained.
The repository contains executable baseline code across all phases, but **not all
production acceptance gates are met**.

Local setup update, 2026-11-05: the four pinned BGE/STS/NLI/reranking snapshots
are now available and passed synthetic-input CPU smoke checks. See
[setup validation](../artifacts/model_setup_validation_2026-11-05.md).
The English LLMTrace pilot is now imported and registered, with span-derived
sentence labels and four isolated splits; see the
[import and grouping audit](../artifacts/llmtrace_import_validation_2026-11-05.md).
The first real-data attempt was interrupted by an NVIDIA driver update that
restarted the active GPU during epoch 1; see the
[interruption report](../artifacts/llmtrace_training_interruption_2026-11-05.md).
The retry **completed all three CUDA BF16 epochs, calibration and final testing**,
with 1,536 successful optimizer updates and zero skipped updates. Epoch 1 was
selected by validation loss. Its calibrated FP32 CPU checkpoint is configured in
`.env` and passed live authenticated HTTP/SSE deployment checks; see the
[pilot results](../artifacts/llmtrace_pilot_validation_2026-11-05.md).
Final-test document accuracy is **79.82%**, macro-F1 **0.790061**, and human
false-positive rate **21.96% at 0.5**. These are within-corpus pilot results.

| Component | Implemented | Not established / unavailable |
|---|---|---|
| Contracts | Strict extraction/document schemas, original UTF-16 offsets, normalization provenance | Arbitrary editor document-model mapping |
| AI engine | 24 features, missing masks, two heads, unique-coverage windows, trained/calibrated English pilot, verified CPU deployment, mixed-document score semantics | Independent generalization, validated low-FPR operating points, robust subgroup/sentence calibration |
| Training | CPU/CUDA LoRA AI/BGE/NLI, AMP, checkpointing, bounded allocator, pinned LLMTrace import/grouping, completed three-epoch GPU detector run and held-out evaluation | Hard-negative quality, production artifact registration for retriever/NLI fine-tunes |
| Similarity | Winnowing, MinHash, BM25, lexical alignment, optional BGE/FAISS + STS | Corpus-wide recall/precision/span benchmarks, calibrated paraphrase classifier, complete reordered-fragment aggregation across passages |
| Claims | Source-grounded sentence candidates, optional model decomposition, related-pair retrieval, RRF, reranking, NLI, four-state evidence aggregation | Validated atomicity, source authority, temporal reasoning, truth accuracy, fitted NLI thresholds |
| Runtime | Serial CPU model leases, explicit unload/status, bounded queue, replay, cancellation, restart termination | Preempting a native model call, GPU training/inference admission profiles, deployment load/latency guarantees |
| Extension | MV3 manifest/build, side panel, pasted text, rendered DOM/text-control adapters, revisions and non-destructive highlights | Real MV3 installation/lifecycle acceptance, framework state integrations, exhaustive zoom/RTL/transform tests |
| Optional techniques | FP32 cross-encoder ONNX export/parity tool | Full pinned-model ONNX compatibility, INT8/FP16 quality, CUDA provider placement, DoRA/ColBERT/GradCache benefit |

Rich similarity/evidence outputs currently use JSON dictionaries around base
contracts; comprehensive typed rich-result schemas, end-to-end similarity/claim
dataset evaluators and a configurable multi-provider evidence interface remain
hardening work. The only implemented external provider is Wikipedia.

## Bounds and interpretation

- Analysis: at most 20,000 Python code points; extension uses a more conservative
  20,000 UTF-16-unit cap. Detector: at most 128 sentence candidates and 64 windows
   at runtime; training defaults to four CPU windows or one CUDA window and rejects
   oversized examples. The LLMTrace pilot's explicit profile is at most 512
   tokenizer tokens per document; longer inputs receive no detector score.
- Lexical/semantic similarity: first 32 passage queries, at most 128 findings.
  Claims: first 48 sentence candidates, at most four model propositions per candidate;
  intrinsic contradiction output is capped at 48 candidates. Coverage caps are diagnostic.
- Corpus: 256 sources, 100,000 characters/source, two million total characters.
  Indexes are rebuilt per analysis; dense passage vectors are cached within that
  analysis, not persisted across requests.
- BGE: normalize embeddings, token-overflow chunks and unique-token-weighted
  averaging of window embeddings. This averaging is a proposed retrieval policy,
  not a benchmarked improvement or ColBERT late interaction.
- Cross-encoder/NLI pairs over 512 tokens abstain rather than silently truncate.
  Claim-model prompts over 512 tokens or generation capped without EOS fall back
  to the complete original sentence candidate and expose coverage diagnostics.
  More than four generated propositions are explicitly marked as omitted.
- The pinned STSB scorer applies its documented one-label sigmoid; its similarity
  scale is not calibrated confidence. MS MARCO relevance scores stay raw logits.
  A passage already fully explained by a lexical match from the same source
  passage is not also reported as a semantic paraphrase solely due to punctuation
  around its lexical span. Partial matches and different source passages are retained.
- Replay: default 32 retained requests, 1-hour TTL, at most 256 events/request,
  512,000 bytes/frame and four million bytes/request. Terminal records can be
  evicted under capacity pressure. SQLite can retain reusable deleted pages;
  record removal is not secure erasure.
- `0.8` STS and `0.85` NLI thresholds are **proposed, not calibration-fitted**.
  No calibrated claim/similarity confidence is exposed. Source trust is explicitly
  user-asserted; Wikipedia evidence remains unrated.
- `.venv-cuda` provides PyTorch 2.7.0+cu126 for explicit GPU training on the 4 GiB
  RTX 3050. See [training](training.md) for the allocator ceiling, mixed precision,
  checkpointing and FP32 CPU deployment contract. Each input/configuration still
  needs measured memory validation.

## Next gates before production

Evaluate against independently held-out domains/generators and corpora with
sufficient human samples for low-FPR claims; address measured false positives,
mixed-document misses and sentence/subgroup calibration; benchmark real corpora and models; validate
extraction atomicity and evidence-source policies; test actual editor framework
state and MV3 worker/panel restarts.

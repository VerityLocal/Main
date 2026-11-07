# Dataset and evaluation plan

See the [2026-11-05 dataset recommendation](dataset_recommendation.md) for
LLMTrace, OpAI-Bench and RAID roles, available annotations and integration needs.

The English LLMTrace pilot is registered in `backend/datasets/registry.yaml` and
stored under `%LOCALAPPDATA%\VerityLocal\datasets`. Its 4,096 training, 768 validation,
768 calibration and 1,536 final-test records have original UTF-16 sentence labels.
See the [completed import audit](../artifacts/llmtrace_import_validation_2026-11-05.md).
`configs/evaluation.yaml` defines the required separation and metrics. AI
evaluation/calibration tooling is executable; see [training](training.md).
Similarity and claim end-to-end dataset evaluation, fitted thresholds and full
task-specific acceptance metrics remain incomplete.

## Registry and leakage control

Each dataset entry must record name, version, source, license, language, record
count, label schema, collection method, preprocessing versions, known
limitations, checksums, and consent/provenance where relevant. Freeze author,
document, source, generator, domain, and near-duplicate grouping rules before
splitting. Use separate training, validation, calibration, and untouched final
test sets. Near-duplicate filtering applies across all splits, not just train.
Do not assign sentence labels from document labels or invent span annotations.

The LLMTrace importer groups all 40,317 English records before filtering or
sampling. Source-topic and normalized exact-text groups are merged with a
deterministic five-word-shingle Jaccard join at 0.85. Original test components
remain reserved; four cross-partition components caused 91 development records
to be excluded. Original validation components are hash-split between validation
and calibration. This is a within-corpus grouped holdout, not an unseen-generator
or independent-corpus test.

For this pilot, document label 1 means **contains annotated AI**, including mixed
writing. Only fully covered or zero-overlap sentences receive binary labels;
partial coverage is masked. Sentence metrics describe the labeled sentence
subset, not character-span localization accuracy. The final-test sample has 592
human documents, so its empirical ROC points cannot establish a 0.1% deployment
false-positive rate.

AI data: human, generated, human-edited AI, mixed-origin spans, unseen generators
and cross-domain examples. Similarity data: exact/partial copies, reordered
fragments, paraphrases, unrelated negatives, manually validated source spans.
Claim data: supported/contradicted/insufficient/conflicting claims, intrinsic
contradiction pairs, source reliability and passage annotations, temporal cases.
Datasets and source licenses must be approved before downloads or training.

## Task metrics

- AI: precision/recall/macro-F1, ROC-AUC, TPR at predeclared low FPR values,
  expected calibration error with recorded binning, mixed-document sentence
  span precision/recall, unseen-generator and cross-domain stratification.
- Similarity: retrieval Recall@K, precision/recall/F1, false positives,
  character-span precision/recall, source-alignment accuracy; Jaccard/dense/
  verification scores remain distinct.
- Claims: extraction atomicity and original-span accuracy, candidate-pair
  recall, retrieval recall, NLI class metrics/calibration, four-state label
  macro-F1, source attribution and temporal consistency. Measure conflicting
  evidence across independent credible sources, not one NLI distribution.
- Browser: extraction completeness claims, UTF-16/non-BMP ranges, mutation/
  stale-response safety, no text/value changes, geometry after scrolling,
  resizing, zoom, transforms and editor rerendering, per-surface fixtures.

Calibration is fitted on its own split after final PyTorch/ONNX deployment
precision and provider placement are selected. Calibrate separate classifier
heads where appropriate; unsupported calibration leaves confidence null.
AI detection is not proof of authorship; similarity is not proof of misconduct;
claim verification is conditional on evidence quality and context.

The pilot selects an epoch using combined validation document/sentence
cross-entropy. Separate temperatures are then fitted on calibration logits from
the merged FP32 CPU artifact. Calibration-split before/after metrics are fitting
diagnostics; final-test metrics use the frozen artifact and temperatures.
The evaluator reports observed false-positive rates and AI recall at 0.5,
alongside macro-F1, ROC-AUC, Brier score and 15-bin equal-width probability ECE.
These are dataset-specific observations, not prevalidated operating thresholds.

## Resource benchmark protocol

Record CPU/GPU model, physical VRAM, free RAM, OS, PyTorch/CUDA versions,
model/tokenizer revisions, document and token counts, B/L/S, precision,
concurrency, seed, warm/cold status, hardware power mode, and repetition count.
Separate CPU and GPU experiments; warm up, synchronize GPU timing, reset peaks,
then record p50/p95 latency, throughput, peak allocated/reserved VRAM, driver
usage, process RSS, and cold start. Publish raw observations and configuration,
not guessed figures. ONNX must record actual providers, operator failures,
partitioning, and accuracy changes. Thresholds require validation data.

## Phase 0 acceptance

Unit/regression: UTF-16 round trips, surrogate rejection, normalization expansions
and compositions, whitespace mapping, schema reproducibility, config/security
validation, memory guard boundaries, hardware optional-dependency/failure paths.
Integration/failure: authenticated health, document registration, malformed and
oversized streaming JSON, origin/host/CSRF/rate limits/timeouts, stale revisions,
safe error output. Resource tests check bounded registry and concurrent revision
updates. Actual results are recorded in `artifacts/phase0_validation.md` only
after commands run. New runtime and rendered-browser fixture results are recorded
in `artifacts/implementation_validation.md`; the Phase 0 report is historical.

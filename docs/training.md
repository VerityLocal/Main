# Training and evaluation tools

Training supports **CUDA mixed precision** and **CPU FP32**. The AI, BGE and NLI
trainers accept `--device cuda`. The English portion of
[LLMTrace Detection](dataset_recommendation.md) has completed a local GPU-trained,
calibrated and evaluated pilot. Dataset records and model weights live in private
local storage.

## Completed local pilot

`llmtrace_detector_pilot_v1_retry1` completed three CUDA BF16 epochs and 1,536
successful optimizer updates with zero skipped updates. The exported epoch is
**epoch 1**, selected by validation combined document/sentence cross-entropy.
Final-test document macro-F1 is **0.790061**, ROC-AUC **0.874420**, accuracy
**79.82%**, and human false-positive rate **21.96% at 0.5**. See the
[complete measurements](../artifacts/llmtrace_pilot_validation_2026-11-05.md)
for calibration diagnostics, sentence/stratum results and the 592-human-document
low-FPR limitation.

The private `.env` already configures this checkpoint. Start the backend from
`local-ai-analysis-platform` whenever it is stopped:

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.app.main
```

Checkpoint: `%LOCALAPPDATA%\VerityLocal\models\llmtrace_detector_pilot_v1_retry1`.
Raw reports: `%LOCALAPPDATA%\VerityLocal\evaluations\llmtrace_detector_pilot_v1_retry1`.
The [live deployment check](../artifacts/detector-deployment-2026-11-05.json)
passed all four cases. Serving uses FP32 CPU in `.venv-cuda`, matching calibration.

## Prepared English LLMTrace pilot

The pinned public corpus is now downloaded and converted locally. The
[import report](../artifacts/llmtrace_import_validation_2026-11-05.md) records
checksum verification, source/near-duplicate grouping, original UTF-16 sentence
labels, exclusions and sampling. The prepared data is:

```powershell
$data = "$env:LOCALAPPDATA\VerityLocal\datasets\llmtrace_detection\pilot_v1\english_pilot.jsonl"
```

It contains 4,096 training, 768 validation, 768 calibration and 1,536 final-test
documents. Document scores mean **contains annotated AI content**, including
mixed writing. Partially covered sentences are masked during supervision.
The initial artifact's input profile is English text up to 512 tokenizer tokens;
longer inputs return explicit unavailability rather than out-of-profile confidence.

To create another reproducible import, use a new output path:

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.scripts.prepare_llmtrace --output "$env:LOCALAPPDATA\VerityLocal\datasets\llmtrace_detection\reproduced\english_pilot.jsonl"
```

The importer accepts `--download` for an explicit pinned download and configurable
split caps. Frozen original test components always remain reserved. The manifest
and data checksums, label policy and input profile are copied into trained artifacts.

### Train and evaluate this prepared data

From `local-ai-analysis-platform`, these commands use the existing pilot and a
new timestamped checkpoint directory. Run each stage after the previous succeeds:

```powershell
$data = "$env:LOCALAPPDATA\VerityLocal\datasets\llmtrace_detection\pilot_v1\english_pilot.jsonl"
$run = 'llmtrace_detector_' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$checkpoint = "$env:LOCALAPPDATA\VerityLocal\models\$run"
$reports = "$env:LOCALAPPDATA\VerityLocal\evaluations\$run"
.\.venv-cuda\Scripts\python.exe -u -m backend.scripts.train_ai_detector --data $data --output $checkpoint --device cuda --precision bf16 --epochs 3 --accumulation 8 --max-windows 1 --log-every 256
.\.venv-cuda\Scripts\python.exe -u -m backend.scripts.evaluate --data $data --checkpoint $checkpoint --split validation --output "$reports\validation.json"
.\.venv-cuda\Scripts\python.exe -u -m backend.scripts.evaluate --data $data --checkpoint $checkpoint --split calibration --fit-calibration --output "$reports\calibration.json"
.\.venv-cuda\Scripts\python.exe -u -m backend.scripts.evaluate --data $data --checkpoint $checkpoint --split final_test --output "$reports\final_test.json"
```

The training directory preserves `progress.jsonl`, per-epoch `training_log.json`
and `best_trainable.pt`. A completed export also contains `weights.pt`, a tokenizer,
backbone config and `manifest.json`. There is no training-resume command; a failed
run's partial directory is retained and a new run needs a new output path.

## CUDA environment on this Windows machine

The `ml-cuda` extra installs **PyTorch 2.7.0+cu126** with its bundled CUDA 12.6
runtime in `.venv-cuda`. The existing NVIDIA driver supports this runtime.
These trainers use precompiled PyTorch kernels, so a separate `nvcc` compiler
installation is unnecessary. The `ml` extra selects the CPU wheel in `.venv`;
`ml` and `ml-cuda` are mutually exclusive.

The CUDA environment has been installed. To reproduce its installation, run
from `local-ai-analysis-platform`:

```powershell
$previousUvEnvironment = $env:UV_PROJECT_ENVIRONMENT
$env:UV_PROJECT_ENVIRONMENT = '.venv-cuda'
try {
    .\.tooling\Scripts\uv.exe sync --frozen --group dev --extra ml-cuda --extra faiss --extra export
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousUvEnvironment
}
```

Use the CUDA environment's Python explicitly:

```powershell
.\.venv-cuda\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
$report = 'artifacts/cuda-smoke-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
.\.venv-cuda\Scripts\python.exe -m backend.scripts.verify_cuda_training --output $report
```

The smoke command runs real backward/optimizer steps on the pinned DeBERTa
architecture with numeric fixture targets. It checks LoRA and both head updates,
records synchronized step times and peak VRAM, and verifies merged FP32 CPU
logits. It exports a measurement report, not detector weights or accuracy results.

The [2026-11-05 measured run](../artifacts/cuda_training_validation_2026-11-05.md)
completed three BF16 GPU optimizer steps on the pinned backbone, with 660.59 MiB
peak allocated and 704 MiB peak reserved VRAM for its short, two-sentence fixture.

### 4 GiB RTX 3050 training profile

- One document per microbatch; `--accumulation 8` averages eight documents before
  an optimizer update. Accumulation does not keep all eight computation graphs.
- AI training defaults to **one 512-token window** on CUDA, four on CPU. Inputs
  exceeding `--max-windows` fail rather than being silently truncated. Prepare a
  length-bounded pilot and report exclusions before increasing the window budget.
- CUDA defaults to BF16 on supported GPUs, otherwise FP16 with gradient scaling.
  `--precision bf16`, `fp16`, or `fp32` can be selected explicitly. CPU uses FP32.
- Non-reentrant gradient checkpointing is always enabled on CUDA. CPU users can
  opt in with `--checkpointing`. LoRA/master parameters and exported weights are FP32.
- The CUDA caching allocator is capped at **3.0 GiB** by default and further
  limited to current free VRAM minus 512 MiB. `--gpu-memory-gib` must be positive
  and below 3.6 GiB. Driver/context memory is additional; allocated and reserved
  peaks are recorded separately. A different input/configuration still needs profiling.
- A requested but unavailable CUDA device fails explicitly. Non-finite losses
  fail; FP16 gradient overflows skip the optimizer update and reduce its scale.
  The report counts successful/skipped updates. Zero successful updates cannot
  produce a trained artifact.

Run one training process at a time and stop costly live analysis while training
to give feature extraction, CPU export and GPU execution adequate memory.

Finish GPU driver installations before starting training. The first local pilot
was interrupted when the NVIDIA installer restarted the active RTX 3050; the
[timestamped diagnosis](../artifacts/llmtrace_training_interruption_2026-11-05.md)
matches the CUDA exception to that restart. Recovery required a fresh CUDA
process after installation, using a new output directory. The diagnostic retry
sets `CUDA_LAUNCH_BLOCKING=1` to make CUDA errors synchronous; that setting can
slow training and is not required for ordinary runs.

## Dataset JSONL

Every record needs `id`, `group_id`, and one of `train`, `validation`, `calibration`,
`final_test`. Groups must represent authors/sources/near-duplicate families and
must not cross splits. The loader rejects duplicated IDs, normalized exact-text
leakage and declared group leakage; **it does not infer near-duplicate clusters**.

AI records additionally need `text`, `label` (integer 0=human, 1=AI), optional
`language` (default English), and `sentence_labels` with original half-open UTF-16
`start_offset`, `end_offset`, and `label`. Sentence boundaries must match the pinned
rule segmenter. Missing sentence labels are masked, never copied from the document
label. Both document and annotated sentence classes must occur in training; the
script refuses to export an independently untrained sentence head. Optional
`domain`, `generator`, `mixed_document` metadata produces evaluation strata.

BGE records need `query` and positive `passage`; NLI records need `premise`,
`hypothesis`, and `label` in `entailment`, `contradiction`, `neutral`. Review false
in-batch negatives and hard negatives; duplicate passage rejection alone is not
an adequate negative-quality evaluation.

## AI baseline

Download `ai_backbone` explicitly first. Enable/download `pos_tagger` only if you
intend to freeze its features; `full_v1` also requires enabled `reference_lm`.

The following data/output paths are examples: replace them with the converted,
grouped JSONL and a new output directory. GPU training:

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.scripts.train_ai_detector --data C:\private-data\ai.jsonl --output C:\private-models\detector --device cuda --precision bf16 --profile light_v1 --epochs 3 --accumulation 8 --max-windows 1
```

The baseline uses inspected DeBERTa query/value LoRA targets, rank 8, alpha 16,
dropout 0.05, separate class-weighted losses and gradient clipping. Feature
extraction is on CPU and currently materializes the dataset, so start with a
bounded pilot. The artifact stores merged weights, local tokenizer and backbone
config, training-only normalizer statistics, model/resource revisions, split
identities, training logs and measured execution/VRAM details. Output must be new.
The trainer prints progress every `--log-every` documents and saves logs and best
trainable weights after each epoch. The exported epoch minimizes the validation
document-plus-sentence cross-entropy, never a calibration or final-test metric.

CPU training remains available with `.\.venv\Scripts\python.exe`, `--device cpu`
and `--precision fp32` (or omit precision). GPU weights are moved to FP32 CPU
before the LoRA merge and export.

## Calibration and deployment after CUDA training

Use **the same `.venv-cuda` environment** for calibration, evaluation and serving
a CUDA-trained detector. These operations explicitly execute on CPU in FP32.
The manifest checks exact package versions, including the `+cu126`/`+cpu` Torch
build suffix; an artifact from `.venv-cuda` cannot simply be loaded by `.venv`.

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.scripts.evaluate --data C:\private-data\ai.jsonl --checkpoint C:\private-models\detector --split calibration --fit-calibration --output C:\private-models\calibration.json
.\.venv-cuda\Scripts\python.exe -m backend.scripts.evaluate --data C:\private-data\ai.jsonl --checkpoint C:\private-models\detector --split final_test --output C:\private-models\final-test.json
```

Both heads need both classes for separate temperature fitting. The final test
never fits calibration. Metrics include macro precision/recall/F1, ROC-AUC,
low-FPR TPR with small-sample cautions, Brier score, equal-width probability ECE,
sentence metrics and available strata. Calibration is compatible only with the
stored FP32 CPU deployment. Missing/one-class strata are null, not invented.
Evaluation loads the checkpoint once and uses the same FP32 CPU forward path as
deployment. Temperature fitting uses raw logits; the calibration report labels
its before/after measurements as fit-split diagnostics. Single-class strata expose
observed false-positive or AI-recall rates, while undefined metrics are omitted.
After evaluation, launch with the trained checkpoint:

```powershell
$env:LOCAL_AI_DETECTOR_CHECKPOINT = 'C:\private-models\detector'
.\.venv-cuda\Scripts\python.exe -m backend.app.main
```

For a CPU-trained artifact, use its matching `.venv` environment throughout.

### Verify the configured pilot through the live API

The configured pilot passed this check on 2026-11-05. To repeat it with a running
backend, use a second PowerShell window in `local-ai-analysis-platform`:

```powershell
$report = 'artifacts/detector-deployment-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
.\.venv-cuda\Scripts\python.exe -m backend.scripts.verify_detector_deployment --data "$env:LOCALAPPDATA\VerityLocal\datasets\llmtrace_detection\pilot_v1\english_pilot.jsonl" --output $report
```

The command uses the existing private connection settings and writes no tokens
or document text to its report. It submits Unicode and exact 512/513-token
fixtures plus one original mixed validation document. Checks cover authenticated
HTTP, CSRF rejection, calibrated sentence probabilities, original UTF-16 offsets,
document/revision identity, terminal SSE replay, stale-revision rejection and
out-of-profile abstention. These are functional deployment checks; their single
request timings and fixture scores are not accuracy or latency benchmarks.

## Other tools

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.scripts.train_bge_retriever --data C:\private-data\retrieval.jsonl --output C:\private-models\bge --device cuda --batch-size 2
.\.venv-cuda\Scripts\python.exe -m backend.scripts.train_nli --data C:\private-data\nli.jsonl --output C:\private-models\nli --device cuda
.\.venv\Scripts\python.exe -m backend.scripts.extract_features --data C:\private-data\ai.jsonl --output C:\private-data\features.jsonl
.\.venv\Scripts\python.exe -m backend.scripts.export_onnx --model-dir C:\private-models\cross-encoder --output C:\private-models\cross-encoder.onnx
```

BGE/NLI fine-tunes produce experimental artifacts; they are not automatically
registered over the pinned runtime snapshots. A reviewed artifact registry,
retrieval/NLI calibration, and task-specific evaluation remain acceptance work.
ONNX export reports actual CPU-provider logit parity for one fixture; it does not
claim whole-dataset accuracy or quantization performance. The reference scorer
performs repeated causal CPU calls and must be profiled before adopting `full_v1`.

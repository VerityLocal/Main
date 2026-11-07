# English LLMTrace detector pilot — 2026-11-05

The CUDA retry **completed training, calibration, final-test evaluation and live
deployment verification**.
Run: `llmtrace_detector_pilot_v1_retry1`. These are measured results for a bounded
English subset of one corpus; independent generalization and production
acceptance remain outstanding.

## Data and intended use

- Dataset: `iitolstykh/LLMTrace_detection`, revision
  `332053804f8798177ff2ecb1148e1839ed429ba3`. Dataset-card license: Apache-2.0;
  original third-party source terms are not replaced.
- Prepared splits: **4,096 train / 768 validation / 768 calibration / 1,536 final
  test** documents. See the [import audit](llmtrace_import_validation_2026-11-05.md)
  for grouping, filtering, sampling and the original-test reservation policy.
- Document policy: `contains_annotated_ai_v1`. Positive means annotated AI content
  is present, including mixed writing. The document probability is neither the
  percentage of AI-written words nor proof of authorship.
- Sentence targets: fully covered non-whitespace content is AI, no annotated
  overlap is human, and partial coverage is masked. Sentence boundaries and
  returned findings use original half-open UTF-16 offsets.
- Intended use: local experimental analysis of English text within the trained
  **512-token / 128-sentence / 20,000-code-point** profile. Longer inputs receive
  explicit detector unavailability. In-profile acceptance alone does not
  establish reliability for a new domain, generator, language or writing style.

## Actual GPU training

Backbone: `microsoft/deberta-v3-small`, revision
`a36c739020e01763fe789b4b85e2df55d6180012`. The `light_v1` architecture combines
DeBERTa with exactly 24 stylometric features and missingness masks, using separate
document and sentence heads. POS/reference-LM features are unavailable in this
profile. Feature normalization is fitted only on training data.

Training used query/value LoRA, rank 8, alpha 16, dropout 0.05; one document per
microbatch, accumulation 8, one window, three epochs and the recorded seed/config.
CUDA enabled non-reentrant gradient checkpointing. The manifest's
`training_config.checkpointing: false` records omission of the optional CPU flag,
not disabled CUDA checkpointing.

| Measurement | Observed value |
| --- | --- |
| Device | NVIDIA GeForce RTX 3050 Laptop GPU, 4 GiB, `cuda:0` |
| Environment | `.venv-cuda`, PyTorch `2.7.0+cu126`, CUDA runtime `12.6`, driver `621.14` |
| Training precision | BF16 autocast; FP32 master/export weights |
| Completed epochs / successful optimizer updates | **3 / 1,536** |
| Skipped optimizer updates | **0** |
| Peak allocated / reserved GPU memory | **819,880,448 / 1,585,446,912 bytes** |
| Allocator ceiling | **2,929,406,772 bytes**, bounded by available-memory headroom |
| Training/validation-loop time | **2,141.3062 seconds** (35.69 minutes) |
| Pipeline start / finish, UTC | `09:42:58.073033` / `10:38:21.003568` |

The loop timing excludes feature preparation and export. Pipeline wall time also
includes validation, calibration and final-test CPU evaluation. Diagnostic
`CUDA_LAUNCH_BLOCKING=1` was enabled for training and can reduce throughput.
The [first attempt](llmtrace_training_interruption_2026-11-05.md) was interrupted
by an NVIDIA driver replacement; its partial output remains preserved separately.

### Epoch selection

The export restores **epoch 1**, selected by minimum validation combined
document/sentence cross-entropy. Calibration and final-test metrics did not
select the epoch. GPU BF16 validation observations during training:

| Epoch | Training loss | Combined validation loss | Document accuracy | Sentence accuracy |
| --- | ---: | ---: | ---: | ---: |
| **1 (exported)** | 0.898569 | **0.923327** | 0.802083 | 0.801727 |
| 2 | 0.677238 | 1.342873 | 0.790365 | 0.782869 |
| 3 | 0.635887 | 1.279888 | 0.805990 | 0.824286 |

The merged FP32 CPU checkpoint's separate pre-calibration validation evaluation
recorded document macro-F1 **0.794034** and ROC-AUC **0.880898**.

## Calibration fit diagnostics

The separate calibration split contains **768 documents / 5,471 labeled
sentences**. Raw-logit temperature fitting used the same FP32 CPU forward path as
deployment. Temperatures: document **1.8086415529251099**, sentence
**1.2488782405853271**. Calibration artifact:
`bae463d0cbc443e0aa990b724d183f25`.

| Fit-split metric | Before | After |
| --- | ---: | ---: |
| Document ECE, 15 equal-width probability bins | 0.062355 | 0.036425 |
| Document Brier score | 0.147730 | 0.145313 |
| Sentence ECE, same binning | 0.147488 | **0.151838** |
| Sentence Brier score | 0.142866 | 0.142435 |

Sentence ECE increased despite a slightly lower Brier score. Calibration did not
uniformly improve quality. Positive temperature scaling preserves the 0.5
classification decision; it does not solve the observed false-positive rate.
These before/after numbers are fitting diagnostics, not final-test performance.

## Frozen final-test results

The final test contains **592 human, 370 fully AI and 574 mixed documents**.
Sentence evaluation includes **7,138 human / 4,561 AI** labels; **100 partially
covered sentences are masked**, leaving 11,699 scored sentences. Evaluation ran
in FP32 CPU, loaded the checkpoint once and reported **567.9601 seconds** elapsed.
This is one evaluation-run observation, not a serving-latency benchmark.

| Metric | Documents | Labeled sentences |
| --- | ---: | ---: |
| Count | 1,536 | 11,699 |
| Accuracy at 0.5 | **79.82%** | **81.09%** |
| Macro precision | 0.787106 | 0.809467 |
| Macro recall | 0.794864 | 0.825187 |
| Macro-F1 | **0.790061** | **0.808299** |
| ROC-AUC | **0.874420** | **0.921444** |
| Human false-positive rate at 0.5 | **21.96% (130 / 592)** | **23.96% (1,710 / 7,138)** |
| AI recall at 0.5, including mixed documents | **80.93% (764 / 944)** | **88.99% (4,059 / 4,561)** |
| ECE, 15 equal-width AI-probability bins | 0.039726 | 0.167215 |
| Brier score | 0.142550 | 0.140904 |

Confusion matrices, in `TN / FP / FN / TP` order:

- Documents: **462 / 130 / 180 / 764**.
- Sentences: **5,428 / 1,710 / 502 / 4,059**.

Fully AI document recall was **95.95% (355 / 370)**; mixed-document recall was
**71.25% (409 / 574)**. Reported single-class strata do not have defined ROC-AUC
or both-class macro metrics. The non-mixed stratum combines human and fully AI
documents; its ECE was **0.234245**, showing that aggregate calibration quality
does not imply equally good subgroup calibration.

### Domain variation at the fixed 0.5 threshold

| Domain | Documents | Macro-F1 | Human false positives / human count | AI recall |
| --- | ---: | ---: | ---: | ---: |
| article | 192 | 0.752688 | 21 / 66 (31.82%) | 82.54% |
| factual | 167 | 0.781604 | 10 / 66 (15.15%) | 74.26% |
| news | 182 | 0.756250 | 31 / 80 (38.75%) | 89.22% |
| paper_abstract | 181 | 0.784502 | 18 / 62 (29.03%) | 85.71% |
| poetry | 176 | 0.744422 | 21 / 74 (28.38%) | 77.45% |
| question | 190 | 0.843194 | 4 / 69 (5.80%) | 79.34% |
| review | 152 | 0.848551 | 9 / 58 (15.52%) | 86.17% |
| short_form | 116 | 0.801591 | 3 / 51 (5.88%) | 69.23% |
| story | 180 | 0.790671 | 13 / 66 (19.70%) | 79.82% |

The raw report also includes all generator strata. They are imbalanced (one to
552 positive documents per generator); `gemini-2.5-flash` accounts for 552 records
and has 71.38% recall. These distributions and mixed-document composition do not
support a controlled generator ranking or held-out-generator generalization.

### Low-FPR interpretation and remaining quality work

The empirical document ROC reports TPR **0.471398** at FPR <= 0.01 and
**0.366525** at FPR <= 0.001. With only **592 human documents**, the latter bin
allows zero observed false positives and cannot establish a 0.1% population FPR.
These ROC summaries are not independently selected deployment thresholds.
No threshold was tuned on the final test; serving continues to expose probabilities.

Sentences within the same document/source are correlated. The raw sentence
report's count-only `low_fpr_small_sample_caution: false` is not evidence of
independent sample size or a validated low-FPR operating point. This pilot supplies
no cluster-aware uncertainty estimate or independent-corpus evaluation.

Measured false positives, mixed-document misses and sentence/subgroup calibration
remain material limitations. Next quality work requires independent held-out
corpora/domains/generators, adequate human samples, and a separate calibration
and threshold-selection protocol. Similarity/claim quality and real-editor/MV3
lifecycle acceptance are tracked in
[implementation status](../docs/implementation_status.md).

## Private artifacts and integrity

Checkpoint directory:
`%LOCALAPPDATA%\VerityLocal\models\llmtrace_detector_pilot_v1_retry1`.
Reports directory:
`%LOCALAPPDATA%\VerityLocal\evaluations\llmtrace_detector_pilot_v1_retry1`.
`pipeline_context.json` records all four successful stages and
`pipeline_completed: true`. Checkpoint weights occupy **566,207,455 bytes**.

| File | SHA-256 |
| --- | --- |
| Prepared `english_pilot.jsonl` | `e61b73e851e2a3359ce64955d773c633e7be5ad25b91beb7161dff0613f36b67` |
| Calibrated `manifest.json` | `5f07eb03abfb5f64765af609fed590ba399f40c8dd943ee2350ffc5eb59d3df9` |
| `weights.pt` | `4a06daf289a9e5517a2fe3a4fae62e87ac1ee7fb062010b3747a8d95fc2a20e4` |
| `training_log.json` | `16535f1f0b14d506428dbce518a45cbb99e1d2e18fb3f111ee581a7d540a5a8b` |
| `pipeline_context.json` | `5ed291d2e9497bbb03fae75188c1578d2102fb5a784b0c7e35745782500f2545` |
| `validation.json` | `1a5dac4db961eed3c6b2945e4c6588f600b8cf6f748745178e57df4d1c48f34f` |
| `calibration.json` | `a38cd69628ccf1f3f5f08d8b95faf74f36cb7066247d8beeddf12b1eb46beb87` |
| `final_test.json` | `c6fcb1285dcdfc4262a958ae1f0fe8e9115248ecb52817312ea70d70068cae73` |

The manifest was validated against installed `.venv-cuda` dependencies. Serving
and evaluation use FP32 CPU in that environment; exact Torch build suffixes are
part of compatibility checks.

## Live deployment and handoff

The private `.env` now points `LOCAL_AI_DETECTOR_CHECKPOINT` to the retry's
calibrated checkpoint. The backend was started with `.venv-cuda` at
`http://127.0.0.1:8787`. At **10:43:06 UTC**, the
[live deployment report](detector-deployment-2026-11-05.json) recorded all checks
passing through real authenticated HTTP/SSE:

| Case | Tokens | Result | Sentence findings |
| --- | ---: | --- | ---: |
| Unicode text, revision 7 | 17 | Completed | 3 |
| Exact trained-token boundary | 512 | Completed | 1 |
| One token above the trained profile | 513 | Unavailable; no score | 0 |
| Original mixed validation document | 56 | Completed | 2 |

All cases verified request/document/revision identity and terminal SSE replay.
Completed cases verified calibrated sentence probabilities, the matching
calibration artifact, original UTF-16 spans and mixed-document score semantics.
Unauthenticated access returned **401**, missing CSRF returned **403**, and a
stale revision returned **409**. The manifest/weights hashes match the evaluated
checkpoint. The validation example was not a final-test document.

Single-request timings and fixture probabilities in this functional report are
not quality or latency benchmarks. The first case includes initial model/import
work, and repeated-word boundary text only exercises input-profile handling.

From `local-ai-analysis-platform`, start the backend when stopped:

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.app.main
```

To repeat live verification against a running backend from another PowerShell:

```powershell
$report = 'artifacts/detector-deployment-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'
.\.venv-cuda\Scripts\python.exe -m backend.scripts.verify_detector_deployment --data "$env:LOCALAPPDATA\VerityLocal\datasets\llmtrace_detection\pilot_v1\english_pilot.jsonl" --output $report
```

Load or reload `extension_mv3\dist` in Chrome and open the Verity Local panel.
The [README](../README.md#install-the-extension) documents extension pairing and
private connection settings. The refreshed `extension_mv3\verity-local.zip` is
**16,644 bytes**, with six entries verified against `dist`; SHA-256:
`18b0144b2e89605b01fe8fafd2abb95ecdc9c12870ee1eaa72a692580922a822`.

Recorded regression checks before this live verification: **223 Python tests
passed / 3 GPU-only skips**, followed by **51 focused tests passed** after the
extractor/CLI changes; Ruff lint passed and **105 Python files** passed formatting.
All six JSON Schemas matched executable contracts. The refreshed extension
passed **9 tests and 6 installed-Chrome fixture checks**. Those browser checks
retain the fixture-only scope described in the implementation report.

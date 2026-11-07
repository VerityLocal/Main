# Initial LLMTrace training interruption — 2026-11-05

The first real-data attempt, `llmtrace_detector_pilot_v1`, exited during epoch 1
with `RuntimeError: CUDA error: unknown error`. Its reported location was the
CPU-to-CUDA batch transfer in `document_forward`; asynchronous CUDA reporting
means that location does not establish the failing kernel.

Last successfully written progress entry:

- Epoch 1, 2,304 of 4,096 training documents.
- 288 successful optimizer updates logged; zero skipped updates logged.
- Peak allocated GPU memory: **813,698,560 bytes**.
- Peak reserved GPU memory: **1,455,423,488 bytes**.
- Allocator ceiling: **2,929,406,772 bytes**.
- Elapsed training/validation-loop time at that entry: **216.0729 seconds**;
  this excludes feature preparation.

The failure was not reported as an out-of-memory exception. No epoch completed,
no weights or manifest were exported, and no calibration or final-test stage ran.
The original private output directory is preserved with `progress.jsonl`:

`%LOCALAPPDATA%\VerityLocal\models\llmtrace_detector_pilot_v1`

## Identified cause: driver replacement restarted the active GPU

The subsequent Windows installation-log inspection established that the NVIDIA
installer replaced the display driver while the first training process was
active. `C:\Windows\INF\setupapi.dev.log` records the RTX 3050 installation
section at lines 14583–15490, including replacement of CUDA/driver DLLs, modification
of the `nvlddmkm` service, and a verified device restart.

Observed timeline, local time **UTC+05:30**, on 2026-11-05:

| Event | Time | Evidence |
| --- | --- | --- |
| NVIDIA driver installation began | 15:04:52.642 | SetupAPI section start |
| Last original training progress was written | 15:10:04.875992 | Preserved progress file timestamp |
| RTX 3050 device restart began | 15:10:07.011 | SetupAPI `Restarting Devices` |
| Training exception output was written | 15:10:09.466325 | Original shell output timestamp |
| Device restart completed and was verified | 15:10:11.313 | SetupAPI restart completion |
| Display-driver installation completed successfully | 15:10:11.349 | SetupAPI section exit |

The CUDA exception occurred inside that device-restart interval. Replacing and
restarting the GPU invalidated the running process's CUDA context. Recovery uses
a fresh Python/CUDA process after the driver installation finishes.

## Recovery observations

A fresh CUDA process subsequently completed finite FP32 and BF16 matrix forward
and backward checks. `nvidia-smi` then reported **driver 621.14**; the earlier
[CUDA setup report](cuda_training_smoke_2026-11-05.json) recorded **621.01**.
The SetupAPI log confirms installation of Windows driver **32.0.16.2114**,
corresponding to NVIDIA 621.14.

A fresh retry was launched at
`%LOCALAPPDATA%\VerityLocal\models\llmtrace_detector_pilot_v1_retry1`, with the
same prepared data, seed, three epochs and BF16 configuration. It enables
`CUDA_LAUNCH_BLOCKING=1` for diagnostic synchronization. The
[feature-extraction optimization](feature_extraction_optimization_2026-11-05.json)
also applies to this new process; feature values, masks and offsets matched on
the recorded 32-document comparison.

At the first recovery inspection, the retry had logged **128 successful CUDA
optimizer updates**, zero skipped updates, and 1,024 epoch-1 documents. This is
an intermediate observation; final training/evaluation success is recorded
separately after the pipeline finishes.

The retry's stage commands, driver observation, environment override and outcome
are recorded in private storage under
`evaluations\llmtrace_detector_pilot_v1_retry1\pipeline_context.json`.
This interruption report is not a successful-training or accuracy result.

## Completed recovery

The fresh retry subsequently completed **all three CUDA BF16 epochs**, with
**1,536 successful optimizer updates and zero skipped updates**. Calibration,
final-test evaluation and live deployment verification also completed. See the
[pilot validation report](llmtrace_pilot_validation_2026-11-05.md) for measured
results and the configured checkpoint. The original failed run is retained.

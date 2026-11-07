# CUDA training setup and validation — 2026-11-05

## Installed environment

- NVIDIA GeForce RTX 3050 Laptop GPU; driver **621.01**; compute capability **8.6**.
- Driver-reported VRAM: **4,294,967,296 bytes (4 GiB)**. PyTorch reports
  4,294,443,008 usable device bytes; the report retains both measurements.
- Python **3.11.9**, **PyTorch 2.7.0+cu126**, bundled **CUDA 12.6** runtime in
  `.venv-cuda`. CUDA availability, native BF16 support and an actual device-local
  matrix operation passed. All 93 installed packages passed `uv pip check`.
- Transformers 4.51.3, PEFT 0.15.2, sentence-transformers 4.1.0, spaCy 3.7.5 and
  NumPy 1.26.4 imported successfully. The frozen lock resolves 111 packages
  across its platform/extra variants.
- PyTorch supplies the runtime used here. A system-wide CUDA Toolkit / `nvcc`
  compiler was not installed; these trainers execute precompiled kernels.

## Actual pinned-backbone GPU training check

Command, from the project directory:

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.scripts.verify_cuda_training --output artifacts/cuda_training_smoke_2026-11-05.json
```

The [raw report](cuda_training_smoke_2026-11-05.json) records the complete
configuration and before/after hardware snapshots.

| Observation | Measured result |
| --- | --- |
| Backbone | `microsoft/deberta-v3-small` |
| Immutable revision | `a36c739020e01763fe789b4b85e2df55d6180012` |
| Device / precision | `cuda:0` / BF16 autocast; FP32 parameters |
| LoRA | Query/value projections, rank 8, alpha 16, dropout 0.05 |
| Microbatch / windows | One document, one window padded to 512 tokens |
| Actual fixture | Two sentences; **19 non-padding tokens** |
| Feature profile | `light_v1`, 24 features plus missingness |
| Checkpointing | Non-reentrant |
| Optimizer updates | **3 successful, 0 skipped** |
| Trainable parameters / changed tensors | 383,876 / 34 |
| Peak PyTorch allocated VRAM | **692,679,168 bytes (660.59 MiB)** |
| Peak PyTorch reserved VRAM | **738,197,504 bytes (704 MiB)** |
| Effective allocator ceiling | 2,929,406,772 bytes, reduced from 3 GiB by free-memory headroom |
| Step seconds, synchronized | 0.9023, 0.2612, 0.1310 |
| FP32 CPU merge max absolute logit difference | **1.1921e-7** |

The check required a measured update in LoRA, the sentence head and the document
head. Both unmerged and merged CPU forwards used evaluation mode; logits matched
within `atol=1e-5, rtol=1e-4` and were finite. No detector checkpoint was exported.
Numeric fixture targets exercise gradients; they are not authorship annotations.
Losses and step times are smoke observations, not accuracy or dataset-throughput
benchmarks. This short fixture does not establish memory fit for every input.

Driver-wide used memory after the training steps was 936,378,368 bytes, which
includes other processes/context overhead and is not a measured driver peak.
Process RSS at that snapshot was 2,005,639,168 bytes; it is not peak RAM.
The pinned fast-tokenizer conversion emitted its documented byte-fallback warning;
the fixture does not validate uncommon-character tokenization quality.

## Code and regression coverage

- Shared training runtime: explicit device, native CUDA device index, AMP,
  gradient scaling, clipping, checkpointing, finite-loss/gradient checks,
  successful/skipped update counts and bounded allocation.
- AI document/window inputs, coverage weights and labels move to the model's
  device. AI/BGE/NLI trainers export merged FP32 CPU weights.
- Tiny neural regression fixtures exercise CPU, BF16 CUDA and FP16 CUDA LoRA
  updates across overlapping windows, frozen-backbone preservation, serialization
  and CPU reload parity. Other cases cover unavailable CUDA, invalid allocation
  ceilings, non-finite losses, FP16 overflow skipping and recovery.
- Focused CPU suite: **37 passed, 3 GPU-only cases skipped**. Config checks after
  correcting a stale all-models-disabled assumption: **19 passed**.
- Final full `.venv-cuda` suite: **208 passed**, including the actual CUDA
  BF16/FP16 regression cases. Three dependency deprecation warnings were emitted.
- Ruff lint and formatting: passed; **100 Python files** formatted consistently.
  All six exported JSON Schemas match their executable contracts; lock check passed.

The first full-backbone attempt identified PyTorch's requirement for an explicit
device index in the allocator API; `cuda:0` selection fixed it before training.
The config test now accepts the user's explicitly enabled pinned models.

## Training and deployment handoff

See [training commands](../docs/training.md) and the
[dataset recommendation](../docs/dataset_recommendation.md). English LLMTrace
Detection is the recommended starting data; its provenance review, grouped
conversion, sentence-span policy and mixed-document semantics still need to be
completed before real detector training and separate calibration/evaluation.

Training can use CUDA, while calibration and deployment execute in FP32 on CPU.
Use `.venv-cuda` for all three stages of a CUDA-trained artifact: the compatibility
manifest checks exact Torch build suffixes as well as resource versions.
The GPU check above covers the AI architecture. Full pinned BGE/NLI training
memory/quality and complete-dataset throughput have not been measured.

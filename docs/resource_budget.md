# Resource-budget methodology

Resource observations are configuration-specific, not accuracy or general
model-fit guarantees. CPU model setup checks and CUDA training measurements are
recorded under `artifacts/` with their fixture/input scope.
`python -m backend.app.runtime.profiling` measures the current host, and backend
startup records the same snapshot without importing or loading model weights.

The Phase 0 guard's process-allocated ceiling is **3.5 GiB**, strictly below 3.6 GiB.
The standalone CUDA trainers use a more conservative **3.0 GiB caching-allocator
ceiling**, limited further by free VRAM minus 512 MiB, plus post-step peak checks.
Report allocated, reserved, peak allocated, peak reserved separately for each
PyTorch CUDA device. Report driver total/free/used memory separately through
`nvidia-smi`. Driver usage includes other processes and is not PyTorch tensor
allocation. Driver version is not the CUDA toolkit version; PyTorch's CUDA
build version is reported separately. Missing PyTorch, missing driver tool,
driver errors/timeouts, and CUDA-disabled builds remain explicit diagnostics.

The Phase 0 guard checks measured allocation and raises a typed failure when
allocation reaches/exceeds the configured ceiling. It allocates no tensors and
does not silently retry or unload user models. A post-allocation check alone
cannot prevent an unknown model's transient peak. **Live GPU inference jobs
remain disabled**; explicit CLI training uses PyTorch's allocator limit before
model placement and records actual execution peaks. Live GPU admission requires a measured-safe
configuration, headroom, exclusive leases, and runtime monitoring; first-time
profiling of unknown configurations must be isolated and explicitly authorized.
The guard is not a claim that all proposed models can fit simultaneously.

## Estimation before isolated profiling

1. Count actual parameter elements and dtype bytes; include trainable LoRA
   parameters separately. Include gradients, master weights, optimizer state,
   and persistent buffers for the actual optimizer—not a guessed universal
   multiplier.
2. Estimate activation tensors from actual B,L,H,S,D, layer counts and dtype;
   include attention intermediates, tokenizer windows, temporary operator
   workspace, and precision-conversion buffers. Estimates are admission hints,
   not guarantees.
3. Measure idle driver free memory, PyTorch allocation/reservation, CPU RSS,
   then cold load. Reset peak stats and synchronize CUDA around timed sections.
4. Measure full forward/inference or forward/backward/optimizer sequence at the
   actual microbatch, sequence length, precision, and concurrent request count.
5. Record peak allocated and reserved, driver memory, CPU RSS, p50/p95 latency,
   throughput, cold/warm state, and exact configuration. Never add per-device
   peaks and describe the sum as an observed simultaneous peak.
6. On failure: reduce microbatch, reduce length with documented truncation,
   evaluate checkpointing for training, remove concurrent residency, move
   appropriate work to CPU, then CPU fallback. Record the failed setup and
   measured memory. Never silently exceed or suppress an OOM.

PyTorch is optional. `ml` selects `torch==2.7.0+cpu`; `ml-cuda` selects
`torch==2.7.0+cu126` with the bundled CUDA 12.6 runtime. The extras are mutually
exclusive and use separate local environments. See [training](training.md).
Without PyTorch, CUDA availability and allocator metrics are unknown (`null`)
even if the NVIDIA driver reports a GPU.
The startup snapshot is not an inference performance benchmark.

CPU leases serialize model residency and drop their stored reference on unload.
A later GPU release must drop all active Python references before
`gc.collect()` and `torch.cuda.empty_cache()`. Cache cleanup is not unloading.
Training and live inference remain mutually exclusive unless a measured,
explicitly enabled configuration proves otherwise.

"""Explicit CPU/CUDA training, bounded CUDA allocation, and AMP optimization."""

import math
from contextlib import nullcontext


def add_runtime_arguments(parser):
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument(
        "--precision",
        choices=["fp32", "fp16", "bf16"],
        help="Default: FP32 on CPU; BF16 on supported CUDA GPUs, otherwise FP16",
    )
    parser.add_argument(
        "--gpu-memory-gib", type=float, default=3.0, help="CUDA allocator ceiling, below 3.6 GiB"
    )
    parser.add_argument(
        "--checkpointing", action="store_true", help="Save activation memory; always on for CUDA"
    )


class TrainingRuntime:
    def __init__(self, device="cpu", precision=None, gpu_memory_gib=3.0):
        import torch

        self.torch = torch
        if device not in {"cpu", "cuda"}:
            raise ValueError("Training device must be cpu or cuda")
        if precision not in {None, "fp32", "fp16", "bf16"}:
            raise ValueError("Unknown training precision")
        if device == "cpu" and precision not in {None, "fp32"}:
            raise ValueError("CPU training requires fp32")
        self.device = torch.device(device)
        self.memory_ceiling_bytes = None
        self.optimizer_steps = 0
        self.skipped_optimizer_steps = 0
        if device == "cuda":
            if not torch.cuda.is_available():
                raise ValueError(
                    "CUDA is unavailable in this Python environment. "
                    "Use the ml-cuda environment and a compatible NVIDIA driver."
                )
            if not math.isfinite(gpu_memory_gib) or not 0 < gpu_memory_gib < 3.6:
                raise ValueError("GPU memory ceiling must be positive and below 3.6 GiB")
            torch.cuda.init()
            self.device = torch.device("cuda", torch.cuda.current_device())
            free, total = torch.cuda.mem_get_info(self.device)
            ceiling = min(int(gpu_memory_gib * 1024**3), free - 512 * 1024**2)
            if ceiling <= 0:
                raise ValueError("Insufficient currently free GPU memory for training")
            # This bounds the caching allocator; the driver/context uses additional memory.
            self.memory_ceiling_bytes = ceiling
            torch.cuda.set_per_process_memory_fraction(ceiling / total, self.device)
            torch.cuda.reset_peak_memory_stats(self.device)
            supports_bf16 = torch.cuda.is_bf16_supported()
            precision = precision or ("bf16" if supports_bf16 else "fp16")
            if precision == "bf16" and not supports_bf16:
                raise ValueError("This CUDA device does not support BF16 training")
        self.precision = precision or "fp32"
        self.scaler = torch.amp.GradScaler(
            "cuda", enabled=device == "cuda" and self.precision == "fp16"
        )

    def autocast(self):
        if self.precision == "fp32":
            return nullcontext()
        dtype = self.torch.bfloat16 if self.precision == "bf16" else self.torch.float16
        return self.torch.autocast(device_type="cuda", dtype=dtype)

    def enable_checkpointing(self, backbone, requested=False):
        if requested or self.device.type == "cuda":
            backbone.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
            backbone.enable_input_require_grads()

    def backward(self, loss):
        if not self.torch.isfinite(loss.detach()).all():
            raise ValueError("Non-finite training loss; no artifact will be exported")
        self.scaler.scale(loss).backward()
        self.check_memory()

    def step(self, optimizer, parameters):
        self.scaler.unscale_(optimizer)
        self.torch.nn.utils.clip_grad_norm_(
            parameters, 1.0, error_if_nonfinite=not self.scaler.is_enabled()
        )
        old_scale = self.scaler.get_scale()
        self.scaler.step(optimizer)
        self.scaler.update()
        if self.scaler.get_scale() < old_scale:
            self.skipped_optimizer_steps += 1
        else:
            self.optimizer_steps += 1
        self.check_memory()

    def check_memory(self):
        if self.device.type == "cuda":
            allocated = self.torch.cuda.max_memory_allocated(self.device)
            if allocated >= self.memory_ceiling_bytes:
                raise RuntimeError("Measured CUDA allocation reached the training ceiling")

    def measurements(self):
        result = {
            "device": str(self.device),
            "precision": self.precision,
            "torch_version": self.torch.__version__,
            "cuda_runtime": self.torch.version.cuda,
            "optimizer_steps": self.optimizer_steps,
            "skipped_optimizer_steps": self.skipped_optimizer_steps,
        }
        if self.device.type == "cuda":
            self.torch.cuda.synchronize(self.device)
            result.update(
                gpu_name=self.torch.cuda.get_device_name(self.device),
                memory_ceiling_bytes=self.memory_ceiling_bytes,
                peak_allocated_bytes=self.torch.cuda.max_memory_allocated(self.device),
                peak_reserved_bytes=self.torch.cuda.max_memory_reserved(self.device),
                free_bytes=self.torch.cuda.mem_get_info(self.device)[0],
            )
        return result

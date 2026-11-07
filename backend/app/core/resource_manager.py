"""Hardware snapshots and a measured process-allocation guard."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DriverGpu(SnapshotModel):
    index: int = Field(ge=0)
    name: str
    driver_version: str
    total_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    used_bytes: int = Field(ge=0)


class TorchGpu(SnapshotModel):
    index: int = Field(ge=0)
    name: str
    total_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    allocated_bytes: int = Field(ge=0)
    reserved_bytes: int = Field(ge=0)
    peak_allocated_bytes: int = Field(ge=0)
    peak_reserved_bytes: int = Field(ge=0)


class HardwareSnapshot(SnapshotModel):
    timestamp: datetime
    platform: str
    python_version: str
    cpu_model: str
    logical_cpu_count: int
    physical_cpu_count: int | None
    system_ram_total_bytes: int
    system_ram_available_bytes: int
    process_rss_bytes: int
    torch_installed: bool
    torch_version: str | None
    torch_cuda_build_version: str | None
    cuda_available: bool | None
    driver_gpus: tuple[DriverGpu, ...] = ()
    torch_gpus: tuple[TorchGpu, ...] = ()
    diagnostics: tuple[str, ...] = ()
    measurement_kind: Literal["hardware_snapshot_not_model_benchmark"] = (
        "hardware_snapshot_not_model_benchmark"
    )


class GpuBudgetExceeded(RuntimeError):
    def __init__(self, allocated_bytes: int, ceiling_bytes: int) -> None:
        self.allocated_bytes = allocated_bytes
        self.ceiling_bytes = ceiling_bytes
        super().__init__("Measured GPU process allocation reached the configured ceiling")


class GpuMeasurementsUnavailable(RuntimeError):
    """CUDA memory checks cannot succeed without actual allocator measurements."""


class GpuMemoryGuard:
    """No tensor allocation, model loading or cache clearing is performed here."""

    def __init__(self, ceiling_gib: float = 3.5) -> None:
        if not 0 < ceiling_gib < 3.6:
            raise ValueError("GPU allocation ceiling must be positive and strictly below 3.6 GiB")
        self.ceiling_bytes = int(ceiling_gib * 1024**3)

    def check(self, snapshot: HardwareSnapshot) -> int:
        if not snapshot.cuda_available or not snapshot.torch_gpus:
            raise GpuMeasurementsUnavailable("CUDA allocator measurements are unavailable")
        # Sum *current* per-device allocations, never per-device historical peaks.
        allocated = sum(device.allocated_bytes for device in snapshot.torch_gpus)
        if allocated >= self.ceiling_bytes:
            raise GpuBudgetExceeded(allocated, self.ceiling_bytes)
        return allocated

import pytest

from backend.app.core.resource_manager import (
    GpuBudgetExceeded,
    GpuMeasurementsUnavailable,
    GpuMemoryGuard,
    TorchGpu,
)


def synthetic_gpu(allocated, *, reserved=None, peak=None, index=0):
    return TorchGpu(
        index=index,
        name="synthetic",
        total_bytes=6 * 1024**3,
        free_bytes=2 * 1024**3,
        allocated_bytes=allocated,
        reserved_bytes=allocated if reserved is None else reserved,
        peak_allocated_bytes=allocated if peak is None else peak,
        peak_reserved_bytes=allocated if reserved is None else reserved,
    )


def test_guard_distinguishes_allocated_reserved_and_historical_peak(hardware):
    guard = GpuMemoryGuard()
    snapshot = hardware.model_copy(
        update={
            "cuda_available": True,
            "torch_gpus": (synthetic_gpu(100, reserved=5 * 1024**3, peak=4 * 1024**3),),
        }
    )
    assert guard.check(snapshot) == 100


@pytest.mark.parametrize("delta", [0, 1])
def test_guard_rejects_at_and_above_ceiling(hardware, delta):
    guard = GpuMemoryGuard()
    measured = guard.ceiling_bytes + delta
    snapshot = hardware.model_copy(
        update={
            "cuda_available": True,
            "torch_gpus": (synthetic_gpu(measured),),
        }
    )
    with pytest.raises(GpuBudgetExceeded) as failure:
        guard.check(snapshot)
    assert failure.value.allocated_bytes == measured


def test_guard_fails_closed_without_allocator_measurements(hardware):
    with pytest.raises(GpuMeasurementsUnavailable):
        GpuMemoryGuard().check(hardware)


def test_guard_adds_current_allocations_across_devices_not_peaks(hardware):
    guard = GpuMemoryGuard()
    snapshot = hardware.model_copy(
        update={
            "cuda_available": True,
            "torch_gpus": (synthetic_gpu(2 * 1024**3), synthetic_gpu(2 * 1024**3, index=1)),
        }
    )
    with pytest.raises(GpuBudgetExceeded) as failure:
        guard.check(snapshot)
    assert failure.value.allocated_bytes == 4 * 1024**3


@pytest.mark.parametrize("ceiling", [0, -1, 3.6, 4, float("nan")])
def test_invalid_memory_ceiling(ceiling):
    with pytest.raises(ValueError):
        GpuMemoryGuard(ceiling)

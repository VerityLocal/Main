"""Real host measurements; optional GPU dependencies do not load model weights."""

import argparse
import csv
import importlib
import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import psutil

from backend.app.core.resource_manager import DriverGpu, HardwareSnapshot, TorchGpu


def cpu_model() -> str:
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except (OSError, ImportError):
            pass
    return platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown")


def probe_driver(timeout: float = 3.0) -> tuple[tuple[DriverGpu, ...], tuple[str, ...]]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return (), ("nvidia_smi_unavailable",)
    command = [
        executable,
        "--query-gpu=index,name,driver_version,memory.total,memory.free,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        devices = []
        for row in csv.reader(result.stdout.splitlines(), skipinitialspace=True):
            if len(row) != 6:
                raise ValueError("Unexpected driver output")
            devices.append(
                DriverGpu(
                    index=int(row[0]),
                    name=row[1].strip(),
                    driver_version=row[2].strip(),
                    total_bytes=int(float(row[3]) * 1024**2),
                    free_bytes=int(float(row[4]) * 1024**2),
                    used_bytes=int(float(row[5]) * 1024**2),
                )
            )
        return tuple(devices), () if devices else ("driver_reports_no_gpu",)
    except subprocess.TimeoutExpired:
        return (), ("nvidia_smi_timeout",)
    except (OSError, subprocess.SubprocessError, ValueError):
        return (), ("nvidia_smi_probe_failed",)


def probe_torch() -> dict:
    result = {
        "torch_installed": False,
        "torch_version": None,
        "torch_cuda_build_version": None,
        "cuda_available": None,
        "torch_gpus": (),
        "diagnostics": (),
    }
    try:
        result["torch_version"] = metadata.version("torch")
    except metadata.PackageNotFoundError:
        result["diagnostics"] = ("torch_not_installed_allocator_metrics_unknown",)
        return result
    result["torch_installed"] = True
    try:
        torch = importlib.import_module("torch")
        result["torch_cuda_build_version"] = torch.version.cuda
        result["cuda_available"] = bool(torch.cuda.is_available())
        if not result["cuda_available"]:
            result["diagnostics"] = ("torch_cuda_unavailable",)
            return result
        devices = []
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            free, total = torch.cuda.mem_get_info(i)
            devices.append(
                TorchGpu(
                    index=i,
                    name=props.name,
                    total_bytes=total,
                    free_bytes=free,
                    allocated_bytes=torch.cuda.memory_allocated(i),
                    reserved_bytes=torch.cuda.memory_reserved(i),
                    peak_allocated_bytes=torch.cuda.max_memory_allocated(i),
                    peak_reserved_bytes=torch.cuda.max_memory_reserved(i),
                )
            )
        result["torch_gpus"] = tuple(devices)
    except Exception:
        # A failed optional binary import/probe must not expose exception data or
        # pretend complete allocator measurements were obtained.
        result["cuda_available"] = None
        result["torch_gpus"] = ()
        result["diagnostics"] = ("torch_probe_failed_allocator_metrics_unknown",)
    return result


def profile_hardware(timeout: float = 3.0) -> HardwareSnapshot:
    memory = psutil.virtual_memory()
    driver, diagnostics = probe_driver(timeout)
    torch_info = probe_torch()
    torch_diagnostics = torch_info.pop("diagnostics")
    return HardwareSnapshot(
        timestamp=datetime.now(UTC),
        platform=platform.platform(),
        python_version=platform.python_version(),
        cpu_model=cpu_model(),
        logical_cpu_count=psutil.cpu_count() or 1,
        physical_cpu_count=psutil.cpu_count(logical=False),
        system_ram_total_bytes=memory.total,
        system_ram_available_bytes=memory.available,
        process_rss_bytes=psutil.Process().memory_info().rss,
        driver_gpus=driver,
        diagnostics=diagnostics + torch_diagnostics,
        **torch_info,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile hardware without downloading models")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = profile_hardware().model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Hardware reports may be refreshed; they do not contain document text.
        args.output.write_text(report + "\n", encoding="utf-8")
        print(f"Hardware snapshot written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()

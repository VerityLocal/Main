"""Conservative physical-memory gate before loading optional local models."""
import ctypes
import os
import subprocess
import sys


class ResourceLimit(ValueError):
    pass


def physical_memory():
    try:
        if sys.platform == "darwin":
            result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, timeout=5, check=True)
            return int(result.stdout)
        if sys.platform == "win32":
            class Memory(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(name, ctypes.c_ulonglong) for name in ["total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended"]]
            memory = Memory()
            memory.length = ctypes.sizeof(memory)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                return memory.total
            return 0
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def available_memory():
    try:
        import psutil
        return psutil.virtual_memory().available
    except (ImportError, OSError):
        return 0


def require_memory(gib, available_gib=0):
    if not isinstance(gib, (int, float)) or not 0 < gib <= 256 or physical_memory() < gib * 1024 ** 3 or available_memory() < available_gib * 1024 ** 3:
        raise ResourceLimit("insufficient_memory")


def model_setup_states(config):
    """Setup is not inference readiness; never call a disabled/custom setting verified."""
    states = {}
    allowed = {"provisioned", "insufficient_memory", "checkpoint_required", "corpus_required"}
    for name in ["text", "ratio", "code", "code_match", "semantic"]:
        current = config.get("semantic") if name == "semantic" else config.get("signals", {}).get(name)
        if current is not None:
            if not current.get("enabled"):
                state = "disabled"
            elif current.get("managed_profile") != "verity-models-v1":
                state = "custom_configured"
            else:
                state = config.get("model_setup_states", {}).get(name, "not_configured")
                if state not in allowed:
                    state = "not_configured"
        else:
            state = config.get("model_setup_states", {}).get(name, "not_configured")
            # A historical profile alone does not establish a currently configured asset.
            if state not in allowed or state == "provisioned":
                state = "not_configured"
        states[name] = state
    return states

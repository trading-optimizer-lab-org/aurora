"""Cross-platform CPU and peak-memory receipts for catalog workers."""

from __future__ import annotations

import ctypes
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
import math
import sys
import time


def _windows_peak_working_set_bytes() -> int:
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    process = kernel32.GetCurrentProcess()
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    success = psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    if not success:
        raise OSError("CATALOG_PROCESS_MEMORY_UNAVAILABLE")
    return int(counters.PeakWorkingSetSize)


def _resource_values() -> tuple[float, int]:
    if sys.platform == "win32":
        return time.process_time(), _windows_peak_working_set_bytes()
    import resource

    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_seconds = own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime
    multiplier = 1 if sys.platform == "darwin" else 1024
    peak_memory_bytes = max(int(own.ru_maxrss), int(children.ru_maxrss)) * multiplier
    return float(cpu_seconds), max(1, peak_memory_bytes)


def _system_memory_bytes() -> int:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
            ctypes.byref(status)
        ):
            raise OSError("CATALOG_SYSTEM_MEMORY_UNAVAILABLE")
        return int(status.ullTotalPhys)
    pages = int(os.sysconf("SC_PHYS_PAGES"))
    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    return pages * page_size


@dataclass(frozen=True)
class ResourceUsageSnapshot:
    cpu_seconds: float
    peak_memory_bytes: int
    available_memory_bytes: int

    @classmethod
    def capture(cls) -> ResourceUsageSnapshot:
        cpu_seconds, peak_memory_bytes = _resource_values()
        available = max(_system_memory_bytes(), peak_memory_bytes)
        return cls(cpu_seconds, peak_memory_bytes, available)


def resource_usage_delta(
    started: ResourceUsageSnapshot,
    completed: ResourceUsageSnapshot,
) -> dict[str, float | int]:
    peak = max(started.peak_memory_bytes, completed.peak_memory_bytes)
    available = max(started.available_memory_bytes, completed.available_memory_bytes, peak)
    return {
        "cpu_seconds": max(0.0, completed.cpu_seconds - started.cpu_seconds),
        "peak_memory_bytes": peak,
        "available_memory_bytes": available,
        "peak_memory_fraction": peak / available,
    }


def aggregate_worker_evaluation(receipts: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Sum complete measured durations, never treating missing telemetry as zero.

    Callers must first verify the source receipts and their non-overlap. A legacy
    reduction's stage sum alone cannot prove all its source measurements existed.
    """
    unavailable: dict[str, object] = {"schema_version": "1", "worker_evaluation_seconds": None, "basis": "unavailable"}
    if not receipts:
        return unavailable
    values: list[float] = []
    for receipt in receipts:
        if "execution_metrics" in receipt:
            metric = receipt["execution_metrics"]
            if (not isinstance(metric, Mapping) or metric.get("schema_version") != "1"
                    or metric.get("basis") != "sum_of_verified_worker_evaluation_durations"):
                return unavailable
            value = metric.get("worker_evaluation_seconds")
        elif ("shard_index" in receipt and "checkpoint_slot_index" in receipt
              and "source_worker_receipt_count" not in receipt):
            stages = receipt.get("scientific_wall_stage_seconds")
            value = stages.get("evaluation") if isinstance(stages, Mapping) else None
        else:
            return unavailable
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return unavailable
        try:
            duration = float(value)
        except OverflowError:
            return unavailable
        if not math.isfinite(duration) or duration < 0:
            return unavailable
        values.append(duration)
    try:
        total = math.fsum(values)
    except OverflowError:
        return unavailable
    return {"schema_version": "1", "worker_evaluation_seconds": total,
            "basis": "sum_of_verified_worker_evaluation_durations"}


__all__ = ["ResourceUsageSnapshot", "resource_usage_delta", "aggregate_worker_evaluation"]

"""Position-sizing, file existence, and disk space checks."""
from __future__ import annotations

import os
import shutil

import numpy as np

from aurora.deployment.preflight._models import PreflightCheck


def check_position_sizing(weights_recent, max_pct: float = 1.0) -> PreflightCheck:
    """Verify max abs weight in recent signals does not exceed cap."""
    if weights_recent is None:
        return PreflightCheck("position_sizing", False, "weights is None")
    arr = np.asarray(weights_recent, dtype=float)
    if arr.size == 0:
        return PreflightCheck("position_sizing", False, "weights empty")
    if np.isnan(arr).any():
        return PreflightCheck("position_sizing", False, "NaN in weights")
    max_w = float(np.max(np.abs(arr)))
    if max_w > max_pct + 1e-9:
        return PreflightCheck(
            "position_sizing", False,
            f"max |weight|={max_w:.4f} > cap {max_pct:.4f}",
        )
    return PreflightCheck(
        "position_sizing", True,
        f"max |weight|={max_w:.4f} <= {max_pct:.4f}",
    )


def check_files_exist(paths: list) -> PreflightCheck:
    """All required files must exist."""
    if not paths:
        return PreflightCheck("files_exist", True, "no required files")
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        return PreflightCheck(
            "files_exist", False, f"missing: {', '.join(missing)}",
        )
    return PreflightCheck("files_exist", True, f"{len(paths)} files present")


def check_disk_space(path: str = ".", min_mb: int = 500) -> PreflightCheck:
    """Free disk space in MB on the volume containing `path`."""
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free / (1024 * 1024)
    except Exception as e:
        return PreflightCheck("disk_space", False, f"disk probe error: {e}")
    if free_mb < min_mb:
        return PreflightCheck(
            "disk_space", False,
            f"only {free_mb:.0f} MB free, need >= {min_mb} MB",
        )
    return PreflightCheck("disk_space", True, f"{free_mb:.0f} MB free")

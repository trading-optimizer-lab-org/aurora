"""Validation marker reader/writer for preflight."""
from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

from aurora.deployment.preflight._models import PreflightCheck


def _resolve_project_dir(project_dir: str = ".") -> str:
    """Resolve ``project_dir`` to a usable absolute path.

    Resolution order
    ----------------
    1. If ``project_dir`` is an absolute path, return it as-is (operators
       can pin a known location for the cache).
    2. Otherwise, walk upward from the current working directory looking
       for a ``pyproject.toml`` marker; the first directory containing it
       is treated as the project root.
    3. If no marker is found, fall back to ``os.path.abspath(project_dir)``
       so legacy behavior (relative paths joined with cwd) still works.

    This keeps ``check_validation_marker`` and ``write_validation_marker``
    co-located with the repository regardless of where the live process
    happens to be invoked from.
    """
    if os.path.isabs(project_dir):
        return project_dir
    here = os.path.abspath(os.getcwd())
    cur = here
    while True:
        if os.path.isfile(os.path.join(cur, "pyproject.toml")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(project_dir)


def _marker_path(strategy_name: str, project_dir: str = ".",
                 cache_dir: Optional[str] = None) -> str:
    """Compute the marker JSON path for ``strategy_name``.

    ``cache_dir`` (optional, absolute) overrides the ``project_dir`` resolution
    entirely so callers running outside the repo (e.g. CI containers) can pin
    the marker location explicitly.
    """
    if cache_dir is not None:
        if not os.path.isabs(cache_dir):
            cache_dir = os.path.abspath(cache_dir)
        return os.path.join(cache_dir, f".validation_passed_{strategy_name}.json")
    root = _resolve_project_dir(project_dir)
    cache = os.path.join(root, "aurora", "data_cache_qf")
    return os.path.join(cache, f".validation_passed_{strategy_name}.json")


def check_validation_marker(strategy_name: str,
                            project_dir: str = ".",
                            max_age_days: int = 7,
                            cache_dir: Optional[str] = None) -> PreflightCheck:
    """Look for marker JSON written by validate_pipeline on overall_passed=True.

    Marker staleness
    ----------------
    A marker older than ``max_age_days`` (default 7) FAILS the check so a
    stale validation cannot let an out-of-date strategy ship to live. The
    marker timestamp is parsed from the JSON ``timestamp`` field; markers
    without a parseable timestamp are treated as stale.

    Path resolution
    ---------------
    Relative ``project_dir`` values are walked upward from the current
    working directory until a ``pyproject.toml`` is found, so live processes
    started outside the repo still locate the cache. Absolute ``project_dir``
    or ``cache_dir`` values bypass the walk.
    """
    path = _marker_path(strategy_name, project_dir, cache_dir=cache_dir)
    if not os.path.exists(path):
        return PreflightCheck(
            "validation_marker", False,
            f"missing marker: {path} (run validate_pipeline first)",
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return PreflightCheck(
            "validation_marker", False, f"unreadable marker: {e}",
        )
    ts = data.get("timestamp", "?")
    # Staleness check: parse the ISO timestamp; if absent or unparseable,
    # treat as stale to err on the safe side.
    try:
        marker_ts = pd.Timestamp(ts)
        if marker_ts.tzinfo is None:
            marker_ts = marker_ts.tz_localize("UTC")
        now_ts = pd.Timestamp.now(tz="UTC")
        age = now_ts - marker_ts
        age_days = float(age.total_seconds()) / 86400.0
    except Exception:
        return PreflightCheck(
            "validation_marker", False,
            f"marker timestamp unparseable ({ts!r}); rerun validate_pipeline",
        )
    if age_days > float(max_age_days):
        return PreflightCheck(
            "validation_marker", False,
            f"stale marker: age {age_days:.2f}d > {max_age_days}d "
            f"(rerun validate_pipeline)",
        )
    return PreflightCheck(
        "validation_marker", True,
        f"present @ {ts} (age {age_days:.2f}d <= {max_age_days}d)",
    )


def write_validation_marker(strategy_name: str, metrics: dict,
                            project_dir: str = ".",
                            cache_dir: Optional[str] = None) -> str:
    """Write the marker JSON. Called by validate_pipeline when overall_passed.

    ``cache_dir`` (optional, absolute) bypasses ``project_dir`` and writes the
    marker directly into the supplied directory; useful when the caller knows
    the cache location regardless of the live process's working directory.
    """
    path = _marker_path(strategy_name, project_dir, cache_dir=cache_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "strategy_name": strategy_name,
        "metrics": metrics,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path

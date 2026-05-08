"""Centralized runtime path resolution.

All persistent QuantForge runtime artifacts (caches, snapshots, audit logs,
research archives, OOS locks) flow through this module. Paths are configurable
via environment variables and default to platformdirs locations isolated from
the package directory.

Env vars (override defaults):
    QF_DATA_DIR          base data dir (default: platformdirs.user_data_dir)
    QF_CACHE_DIR         price/data cache dir (default: $QF_DATA_DIR/cache)
    QF_CACHE             backwards-compat alias for QF_CACHE_DIR
    QF_SNAPSHOT_ROOT     SnapshotStore root_dir (default: $QF_DATA_DIR/snapshots)
    QF_AUDIT_LOG         audit trail JSONL (default: $QF_DATA_DIR/audit_trail.jsonl)
    QF_GATEWAY_AUDIT     agent gateway audit chain (default: $QF_DATA_DIR/gateway_audit.jsonl)
    QF_OOS_LOCK          OOSGuard lock file (default: $QF_DATA_DIR/.oos_lock.json)
    QF_RESEARCH_ARCHIVE  research factory archive (default: $QF_DATA_DIR/research_archive.jsonl)
    QF_REVIEW_QUEUE      research factory review queue (default: $QF_DATA_DIR/review_queue.jsonl)
    QF_CONFIG_DIR        user-overridable config dir (default: $QF_DATA_DIR/config)

These paths NEVER point inside the installed package (site-packages stays
read-only when installed from wheel).
"""
from __future__ import annotations
import os
from pathlib import Path


def _platformdirs_base() -> Path:
    """Default user data dir via platformdirs."""
    try:
        from platformdirs import user_data_dir
        return Path(user_data_dir("quantforge", appauthor=False))
    except ImportError:
        return Path(os.path.expanduser("~")) / ".quantforge"


def base_data_dir() -> Path:
    """Base dir for all runtime artifacts. Override via $QF_DATA_DIR."""
    raw = os.environ.get("QF_DATA_DIR")
    p = Path(raw) if raw else _platformdirs_base()
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    """Price/data cache dir. Override via $QF_CACHE_DIR or legacy $QF_CACHE."""
    raw = os.environ.get("QF_CACHE_DIR") or os.environ.get("QF_CACHE")
    p = Path(raw) if raw else base_data_dir() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def snapshot_root() -> Path:
    """SnapshotStore root_dir. Override via $QF_SNAPSHOT_ROOT.

    Contains parquet files + snapshots_index.sqlite. NOT just a single DB file.
    """
    raw = os.environ.get("QF_SNAPSHOT_ROOT")
    p = Path(raw) if raw else base_data_dir() / "snapshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def audit_log_path() -> Path:
    """SOC2 audit trail JSONL. Override via $QF_AUDIT_LOG."""
    raw = os.environ.get("QF_AUDIT_LOG")
    return Path(raw) if raw else base_data_dir() / "audit_trail.jsonl"


def gateway_audit_path() -> Path:
    """Agent gateway hash-chained audit JSONL. Override via $QF_GATEWAY_AUDIT."""
    raw = os.environ.get("QF_GATEWAY_AUDIT")
    return Path(raw) if raw else base_data_dir() / "gateway_audit.jsonl"


def oos_lock_path() -> Path:
    """OOSGuard cross-process lock file. Override via $QF_OOS_LOCK."""
    raw = os.environ.get("QF_OOS_LOCK")
    return Path(raw) if raw else base_data_dir() / ".oos_lock.json"


def research_archive_path() -> Path:
    """ResearchFactory rejection archive JSONL. Override via $QF_RESEARCH_ARCHIVE."""
    raw = os.environ.get("QF_RESEARCH_ARCHIVE")
    return Path(raw) if raw else base_data_dir() / "research_archive.jsonl"


def review_queue_path() -> Path:
    """ResearchFactory review queue JSONL. Override via $QF_REVIEW_QUEUE."""
    raw = os.environ.get("QF_REVIEW_QUEUE")
    return Path(raw) if raw else base_data_dir() / "research_review_queue.jsonl"


def user_config_dir() -> Path:
    """User-overridable config dir. Override via $QF_CONFIG_DIR.

    For built-in package configs (e.g. protocol_policy.yaml), use
    importlib.resources to read from the installed package directly.
    """
    raw = os.environ.get("QF_CONFIG_DIR")
    p = Path(raw) if raw else base_data_dir() / "config"
    p.mkdir(parents=True, exist_ok=True)
    return p


# Eager-evaluated module constants for backwards-compat with code that imports
# them as values rather than calling the functions. Tests using monkeypatch on
# these constants should switch to setenv on the corresponding $QF_* var.
__all__ = [
    "base_data_dir",
    "cache_dir",
    "snapshot_root",
    "audit_log_path",
    "gateway_audit_path",
    "oos_lock_path",
    "research_archive_path",
    "review_queue_path",
    "user_config_dir",
]

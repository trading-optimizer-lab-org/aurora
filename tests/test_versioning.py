"""Tests for quantforge.registry.versioning (Task K.2)."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

from quantforge.registry.versioning import (
    StrategyVersion,
    VersionRegistry,
    compute_strategy_version,
    diff_versions,
    hash_strategy_code,
    is_git_dirty,
)
from quantforge.strategies.base import Strategy


class _StratA(Strategy):
    def __init__(self, fast: int = 10, slow: int = 50):
        self.fast = int(fast)
        self.slow = int(slow)

    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.zeros(len(prices))


class _StratB(Strategy):
    def __init__(self, lookback: int = 20):
        self.lookback = int(lookback)

    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.ones(len(prices))


# ---------- pure functions ----------

def test_compute_version_deterministic():
    v1 = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    v2 = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    assert v1.version_id == v2.version_id
    assert v1.code_hash == v2.code_hash
    assert v1.params_hash == v2.params_hash


def test_param_change_changes_version():
    v1 = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    v2 = compute_strategy_version(_StratA, {"fast": 11, "slow": 50}, include_git=False)
    assert v1.version_id != v2.version_id
    assert v1.code_hash == v2.code_hash
    assert v1.params_hash != v2.params_hash


def test_code_hash_basic():
    h_a = hash_strategy_code(_StratA)
    h_b = hash_strategy_code(_StratB)
    assert isinstance(h_a, str) and len(h_a) == 64  # sha256 hex
    assert h_a != h_b


def test_code_hash_includes_base():
    """Different subclass with identical body still differs by name -> different hash."""
    h_a = hash_strategy_code(_StratA)
    h_b = hash_strategy_code(_StratB)
    assert h_a != h_b


def test_git_dirty_detection():
    """Smoke: returns a bool (may be True or False depending on workspace)."""
    try:
        result = is_git_dirty()
    except Exception:
        pytest.skip("git unavailable")
    assert isinstance(result, bool)


def test_compute_version_param_canonicalization():
    """Same params, different insertion order -> same version_id."""
    v1 = compute_strategy_version(_StratA, {"slow": 50, "fast": 10}, include_git=False)
    v2 = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    assert v1.version_id == v2.version_id


# ---------- registry persistence ----------

def test_register_and_get(tmp_path):
    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    v = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    reg.register(v)
    got = reg.get(v.version_id)
    assert got is not None
    assert got.version_id == v.version_id
    assert got.strategy_class == "_StratA"


def test_register_idempotent(tmp_path):
    path = tmp_path / "hist.jsonl"
    reg = VersionRegistry(history_path=str(path))
    v = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    reg.register(v)
    reg.register(v)
    reg.register(v)
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_lineage_chain(tmp_path):
    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    v_root = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    reg.register(v_root)
    v_child = compute_strategy_version(
        _StratA, {"fast": 12, "slow": 50}, include_git=False, parent_version=v_root.version_id,
    )
    reg.register(v_child)
    v_grand = compute_strategy_version(
        _StratA, {"fast": 12, "slow": 80}, include_git=False, parent_version=v_child.version_id,
    )
    reg.register(v_grand)

    chain = reg.lineage(v_grand.version_id)
    ids = [v.version_id for v in chain]
    assert ids == [v_root.version_id, v_child.version_id, v_grand.version_id]


def test_lineage_unknown_returns_empty(tmp_path):
    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    assert reg.lineage("deadbeefdeadbeef") == []


def test_all_versions_filter_by_class(tmp_path):
    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    va = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    vb = compute_strategy_version(_StratB, {"lookback": 20}, include_git=False)
    reg.register(va)
    reg.register(vb)

    assert len(reg.all_versions()) == 2
    only_a = reg.all_versions("_StratA")
    assert len(only_a) == 1 and only_a[0].strategy_class == "_StratA"
    only_b = reg.all_versions("_StratB")
    assert len(only_b) == 1 and only_b[0].strategy_class == "_StratB"


def test_mark_validated_updates_metrics(tmp_path):
    path = tmp_path / "hist.jsonl"
    reg = VersionRegistry(history_path=str(path))
    v = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    reg.register(v)
    metrics = {"sharpe": 1.42, "calmar": 0.85, "max_dd": -0.18}
    reg.mark_validated(v.version_id, metrics)

    got = reg.get(v.version_id)
    assert got.validated is True
    assert got.validation_metrics == metrics

    # File must remain valid JSON-lines
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                json.loads(line)


def test_mark_validated_unknown_raises(tmp_path):
    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    with pytest.raises(KeyError):
        reg.mark_validated("nonexistent_id", {"sharpe": 1.0})


# ---------- diff ----------

def test_diff_versions_shows_changes(tmp_path):
    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    v1 = compute_strategy_version(_StratA, {"fast": 10, "slow": 50}, include_git=False)
    v2 = compute_strategy_version(_StratA, {"fast": 12, "slow": 50}, include_git=False)
    reg.register(v1)
    reg.register(v2)
    reg.mark_validated(v1.version_id, {"sharpe": 1.0, "calmar": 0.5})
    reg.mark_validated(v2.version_id, {"sharpe": 1.3, "calmar": 0.5})

    v1f = reg.get(v1.version_id)
    v2f = reg.get(v2.version_id)
    d = diff_versions(v1f, v2f)
    assert d["params_changed"] is True
    assert d["code_changed"] is False
    assert d["strategy_class"]["changed"] is False
    assert d["metric_diff"] == {"sharpe": {"v1": 1.0, "v2": 1.3}}


def test_strategyversion_roundtrip():
    v = compute_strategy_version(_StratA, {"fast": 10}, include_git=False)
    d = v.to_dict()
    blob = json.dumps(d, sort_keys=True)
    v2 = StrategyVersion.from_dict(json.loads(blob))
    assert v2.version_id == v.version_id
    assert v2.code_hash == v.code_hash
    assert v2.params_hash == v.params_hash


def test_versioning_handles_numba_decorated_fn(monkeypatch):
    """If inspect.getsource raises (typical for numba/Cython artifacts), the
    hasher must fall back to a qualname-based key instead of crashing.

    Simulate by monkeypatching ``inspect.getsource`` to raise OSError.
    """
    import quantforge.registry.versioning as ver_mod

    def _raise_oserror(*args, **kwargs):
        raise OSError("could not get source code")

    monkeypatch.setattr(ver_mod.inspect, "getsource", _raise_oserror)

    # Should not raise; fall back to qualname-only hash for the strategy class.
    h = ver_mod.hash_strategy_code(_StratA)
    assert isinstance(h, str)
    assert len(h) == 64  # sha256 hex digest

    # Two distinct classes must still produce distinct hashes via fallback,
    # because their qualname differs.
    h_b = ver_mod.hash_strategy_code(_StratB)
    assert h != h_b


def test_versioning_handles_typeerror_fallback(monkeypatch):
    """TypeError from getsource (e.g., builtin/JIT object) also falls back."""
    import quantforge.registry.versioning as ver_mod

    def _raise_typeerror(*args, **kwargs):
        raise TypeError("module, class, method, function, traceback, ...")

    monkeypatch.setattr(ver_mod.inspect, "getsource", _raise_typeerror)
    h = ver_mod.hash_strategy_code(_StratA)
    assert isinstance(h, str) and len(h) == 64


def test_versioning_git_status_timeout(monkeypatch):
    """`git status` subprocess hang must be bounded; is_git_dirty falls back to False.

    Simulates a hung git invocation by patching ``_run_git_proc`` to behave
    as if the underlying ``Popen.communicate`` timed out, terminated, and
    returned ``(returncode=None, stdout="")``. The function must catch the
    timeout and not propagate it; ``_git_head`` returns the
    ``GIT_UNAVAILABLE`` sentinel.
    """
    import quantforge.registry.versioning as ver_mod

    def _fake_timeout(args, timeout):
        # The shipped helper uses Popen+communicate; on timeout it
        # terminates the child and returns ``(None, "")``. This matches
        # that contract so the higher-level callers exercise the
        # timeout-handling branch.
        assert isinstance(args, list)
        assert float(timeout) >= 5.0, (
            f"timeout must be >= 5.0s (was {timeout!r})"
        )
        return None, ""

    monkeypatch.setattr(ver_mod, "_run_git_proc", _fake_timeout)

    # is_git_dirty: timeout falls back to False (treat unknown as clean).
    assert ver_mod.is_git_dirty() is False

    # _git_head: timeout falls back to the sentinel.
    head = ver_mod._git_head()
    assert head == ver_mod.GIT_UNAVAILABLE


# ---------------------------------------------------------------------------
# Hardening: file lock + fsync
# ---------------------------------------------------------------------------


def test_versioning_concurrent_writes_no_duplicates(tmp_path):
    """Concurrent register() calls for the same version_id from multiple
    threads must produce exactly one line (no duplicates) thanks to the
    advisory file lock.
    """
    import threading

    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    v = compute_strategy_version(_StratA, {"fast": 10, "slow": 50},
                                 include_git=False)
    barrier = threading.Barrier(8)

    def _go():
        barrier.wait()
        reg.register(v)

    threads = [threading.Thread(target=_go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(reg.history_path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 1


def test_versioning_atomic_write(tmp_path, monkeypatch):
    """_write_all must call os.fsync before the rename so a crash between
    write and rename leaves a fully-flushed file on disk.
    """
    import quantforge.registry.versioning as ver_mod

    fsync_calls: list = []
    real_fsync = ver_mod.os.fsync

    def _spy_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(ver_mod.os, "fsync", _spy_fsync)

    reg = VersionRegistry(history_path=str(tmp_path / "hist.jsonl"))
    v = compute_strategy_version(_StratA, {"fast": 1}, include_git=False)
    reg.register(v)
    reg.mark_validated(v.version_id, {"sharpe": 1.0})
    # At least one fsync from register (append) and one from _write_all.
    assert len(fsync_calls) >= 2

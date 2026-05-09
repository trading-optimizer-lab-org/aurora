"""Tests for hardened OOSGuard with file-system lock (Task 6.3)."""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
import pytest

from aurora.core.data_layer import (
    OOSGuard, check_oos_integrity, load_asset, _get_git_hash,
)


def _read_lock(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_in_memory_basic():
    """Existing in-memory behavior preserved when ``lock_path=None``.

    The round-2 default for ``lock_path`` is ``DEFAULT_LOCK_PATH``; passing
    ``None`` is the explicit opt-out so unit tests stay self-contained.
    """
    with OOSGuard("optimization", lock_path=None) as g:
        assert g.violations == 0
        g.record_oos_read("synthetic_call_1")
        g.record_oos_read("synthetic_call_2")
        # ``record_oos_read`` bumps both legacy ``violations`` (kept for
        # backward compat with prior tests) and the new
        # ``authorized_reads`` counter introduced in round 2.
        assert g.violations == 2
        assert g.violation_log == ["synthetic_call_1", "synthetic_call_2"]
        assert g.authorized_reads == 2
    # After exit no file is required.
    assert g.violations == 2


def test_lock_file_created(tmp_path: Path):
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("optimization", lock_path=str(lock)) as g:
        pass
    assert lock.exists(), "lock file must exist after context exits"
    data = _read_lock(str(lock))
    assert data["phase"] == "optimization"
    # Round-2 schema: separate ``authorized_reads`` and ``violations`` arrays.
    assert data["violations"] == []
    assert data["authorized_reads"] == []
    assert "locked_at" in data
    assert "git_hash" in data


def test_authorized_read_persisted(tmp_path: Path):
    """``record_oos_read`` lands in ``authorized_reads`` (NOT ``violations``).

    Round 2 separates the audit trail from the contamination flag so a
    legitimate post-validation OOS read is logged but does not fail
    ``check_lock_clean``.
    """
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        g.record_oos_read("load_asset(SPY, include_oos=True)")
    data = _read_lock(str(lock))
    # No violations -- this was an authorized read, not contamination.
    assert data["violations"] == []
    assert len(data["authorized_reads"]) == 1
    rec = data["authorized_reads"][0]
    assert rec["where"] == "load_asset(SPY, include_oos=True)"
    assert rec["phase"] == "post_ga_validation"
    assert "timestamp" in rec


def test_violation_persisted(tmp_path: Path):
    """``record_oos_violation`` lands in ``violations`` and trips check_lock_clean."""
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("optimization", lock_path=str(lock)) as g:
        g.record_oos_violation("ga_fitness_peeked_at_oos")
    data = _read_lock(str(lock))
    assert len(data["violations"]) == 1
    assert data["authorized_reads"] == []
    v = data["violations"][0]
    assert v["where"] == "ga_fitness_peeked_at_oos"
    assert "timestamp" in v


def test_check_lock_clean_pass(tmp_path: Path):
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("optimization", lock_path=str(lock)):
        pass
    assert OOSGuard.check_lock_clean(str(lock)) is True
    assert check_oos_integrity(str(lock)) is True


def test_check_lock_clean_pass_with_authorized_reads(tmp_path: Path):
    """``check_lock_clean`` only inspects the violations array; authorized
    reads are an audit trail, not contamination."""
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("post_ga_validation", lock_path=str(lock)) as g:
        g.record_oos_read("load_asset(SPY, include_oos=True)")
        g.record_oos_read("load_asset(SPY, include_oos=True)")
    # Lots of authorized reads, zero violations -> still clean.
    assert OOSGuard.check_lock_clean(str(lock)) is True
    data = _read_lock(str(lock))
    assert len(data["authorized_reads"]) == 2
    assert data["violations"] == []


def test_check_lock_clean_fail(tmp_path: Path):
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("optimization", lock_path=str(lock)) as g:
        g.record_oos_violation("ga_fitness_peeked_at_oos")
    assert OOSGuard.check_lock_clean(str(lock)) is False
    assert check_oos_integrity(str(lock)) is False


def test_git_hash_captured_when_available(tmp_path: Path):
    """Inside the project repo we expect a real hash. The captured value either
    is None (no git available) or a valid 40-char hex string. Both are ok."""
    h = _get_git_hash()
    if h is None:
        # git not available in this environment — still acceptable
        assert h is None
    else:
        assert isinstance(h, str)
        assert len(h) >= 7  # short or full hash
        # all chars hex
        assert all(c in "0123456789abcdef" for c in h.lower())

    # And the lock file records whatever value was captured.
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("opt", lock_path=str(lock)):
        pass
    data = _read_lock(str(lock))
    assert "git_hash" in data
    assert data["git_hash"] == h or (data["git_hash"] is None and h is None)


def test_reset_lock(tmp_path: Path):
    """``reset_lock`` clears violations; authorized_reads survive as audit."""
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("optimization", lock_path=str(lock)) as g:
        g.record_oos_violation("snoop_call")
        g.record_oos_read("legit_audit_call")
    assert OOSGuard.check_lock_clean(str(lock)) is False
    OOSGuard.reset_lock(str(lock))
    assert OOSGuard.check_lock_clean(str(lock)) is True
    data = _read_lock(str(lock))
    assert data["violations"] == []
    # Authorized reads are an audit trail; reset preserves them so the
    # historical record of "who legitimately saw OOS" survives.
    assert any(r["where"] == "legit_audit_call" for r in data["authorized_reads"])


def test_reset_lock_missing(tmp_path: Path):
    """reset_lock on non-existent file is a no-op."""
    lock = tmp_path / "missing.json"
    OOSGuard.reset_lock(str(lock))
    assert not lock.exists()
    # And check_lock_clean treats absent file as clean.
    assert OOSGuard.check_lock_clean(str(lock)) is True


def test_concurrent_contexts(tmp_path: Path):
    """Nested OOSGuards: outer's in-memory counter sees inner's record,
    but only the innermost guard persists to its lock file.

    The round-2 schema splits the on-disk record into ``authorized_reads``
    vs ``violations``. ``record_oos_read`` writes to ``authorized_reads``
    (the legitimate audit path). The ownership rule still holds: only the
    innermost guard appends to its lock file; outer guards only mirror the
    in-memory counters so callers can see "an OOS event happened inside".
    """
    outer_lock = tmp_path / "outer.json"
    inner_lock = tmp_path / "inner.json"
    with OOSGuard("outer", lock_path=str(outer_lock)) as outer:
        with OOSGuard("inner", lock_path=str(inner_lock)) as inner:
            inner.record_oos_read("inner_call")
        # in-memory: outer still sees the propagated counter / log entry.
        assert inner.violations == 1
        assert outer.violations >= 1
        assert "inner_call" in outer.violation_log
        assert outer.authorized_reads >= 1
    inner_data = _read_lock(str(inner_lock))
    outer_data = _read_lock(str(outer_lock))
    # Innermost guard persisted exactly one authorized_read record.
    assert any(r["where"] == "inner_call" for r in inner_data["authorized_reads"])
    # Outer guard did NOT persist a duplicate copy.
    assert not any(r["where"] == "inner_call" for r in outer_data["authorized_reads"])
    # Neither guard recorded a violation -- this was a legit read.
    assert inner_data["violations"] == []
    assert outer_data["violations"] == []


def test_record_appends_across_sessions(tmp_path: Path):
    """Two consecutive sessions accumulate authorized_reads in the same lock file."""
    lock = tmp_path / ".oos_lock.json"
    with OOSGuard("opt", lock_path=str(lock)) as g:
        g.record_oos_read("session1_call")
    with OOSGuard("opt", lock_path=str(lock)) as g:
        g.record_oos_read("session2_call")
    data = _read_lock(str(lock))
    wheres = [r["where"] for r in data["authorized_reads"]]
    assert "session1_call" in wheres
    assert "session2_call" in wheres
    # Real violations array stays empty for legitimate reads.
    assert data["violations"] == []


@pytest.mark.integration
def test_backward_compat_load_asset_no_lock_path():
    """Existing OOSGuard usage in load_asset (no lock_path) keeps working
    without writing any file.

    Marked ``integration``: loads SPY parquet cache.
    """
    cache_dir = os.path.join(
        os.path.dirname(__file__), "..", "data_cache_qf"
    )
    spy_path = os.path.join(cache_dir, "SPY.parquet")
    if not os.path.exists(spy_path):
        pytest.skip("SPY parquet cache not present")
    # ``lock_path=None`` -> in-memory only (round-2 default lock_path is
    # DEFAULT_LOCK_PATH; pass None explicitly to opt out for unit tests).
    with OOSGuard("optimization", lock_path=None) as g:
        s = load_asset("SPY", include_oos=False)
        assert g.violations == 0
        assert len(s) > 0
        s_oos = load_asset("SPY", include_oos=True)
        # The OOS read was recorded as an authorized_read (legitimate
        # audit path inside the explicit guard); the legacy ``violations``
        # in-memory counter is still bumped for backward-compat with
        # tests that assert "the guard saw an OOS read".
        assert g.violations == 1
        assert g.authorized_reads == 1

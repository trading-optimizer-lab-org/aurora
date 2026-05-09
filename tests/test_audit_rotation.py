"""Tests for core.audit_rotation (R34)."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from aurora.core.audit_rotation import (
    RotationPolicy,
    prune_old_segments,
    rotate_if_needed,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def test_no_rotation_when_below_size_threshold(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    _write_jsonl(log, [{"chain_hash": "abc"}])
    policy = RotationPolicy(max_size_bytes=10_000_000, rotate_daily=False,
                            retention_days=None, compress=False)
    seg = rotate_if_needed(log, policy)
    assert seg is None


def test_size_based_rotation_creates_segment_and_anchors_chain(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    records = [{"chain_hash": f"h{i}"} for i in range(50)]
    _write_jsonl(log, records)
    policy = RotationPolicy(max_size_bytes=100, rotate_daily=False,
                            retention_days=None, compress=False)
    seg = rotate_if_needed(log, policy)
    assert seg is not None
    assert seg.exists()
    assert seg.suffix == ".jsonl"
    # Active file now contains a rotation_anchor referencing last chain.
    text = log.read_text(encoding="utf-8").strip()
    assert text
    anchor = json.loads(text)
    assert anchor["kind"] == "rotation_anchor"
    assert anchor["prior_chain_hash"] == "h49"


def test_rotation_compresses_when_policy_enables(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    _write_jsonl(log, [{"chain_hash": f"h{i}"} for i in range(20)])
    policy = RotationPolicy(max_size_bytes=10, rotate_daily=False,
                            retention_days=None, compress=True)
    seg = rotate_if_needed(log, policy)
    assert seg is not None
    assert seg.suffix == ".gz"
    # Read back through gzip to ensure content survived.
    with gzip.open(seg, "rt", encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip()]
    assert len(lines) == 20


def test_retention_prunes_old_segments(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    # Create three fake segments and force their mtimes to be old.
    old_seg = tmp_path / "audit.20200101-01.jsonl"
    recent_seg = tmp_path / "audit.20990101-01.jsonl"
    old_seg.write_text("{}\n", encoding="utf-8")
    recent_seg.write_text("{}\n", encoding="utf-8")
    import os
    os.utime(old_seg, (1577836800, 1577836800))  # 2020-01-01 UTC
    policy = RotationPolicy(retention_days=30)
    deleted = prune_old_segments(log, policy)
    assert deleted >= 1
    assert not old_seg.exists()
    assert recent_seg.exists()


def test_active_file_never_pruned(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    log.write_text("", encoding="utf-8")
    import os
    os.utime(log, (1577836800, 1577836800))
    policy = RotationPolicy(retention_days=30)
    deleted = prune_old_segments(log, policy)
    assert deleted == 0
    assert log.exists()

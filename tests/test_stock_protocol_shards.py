"""Shard and layer-freeze contract tests."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from aurora.research.stock_protocol.manifest import load_protocol_manifest
from scripts.merge_stock_protocol_phase import merge_phase
from scripts.run_stock_protocol_stage import enumerate_tasks


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


def test_task_assignment_is_deterministic_and_covers_supported_phase():
    manifest = load_protocol_manifest(MANIFEST)
    tasks = enumerate_tasks(manifest, "signal")
    assigned = [task for shard in range(360) for task in tasks[shard::360]]
    assert assigned == tasks
    assert all(task["test_id"] in {1, 2, 3, 8, 9, 13} for task in tasks)


def test_merge_rejects_missing_shard(tmp_path: Path):
    phase_root = tmp_path / "phase=signal" / "shard=000"
    phase_root.mkdir(parents=True)
    row = {"shard_id": 0, "locked_opened": False, "data_end": "2020-12-31", "dataset_hash": "h"}
    (phase_root / "stage_results.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing shard"):
        merge_phase(tmp_path, "signal", 2, tmp_path / "out", MANIFEST)

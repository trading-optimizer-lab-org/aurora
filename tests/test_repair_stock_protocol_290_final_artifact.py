"""Contracts for lossless final-artifact repair after fail-closed verification."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.merge_stock_protocol_290_event_study import (
    AUDIT_SUMMARY_NAME,
    FINAL_MANIFEST_NAME,
    OPPORTUNITIES_PARQUET,
    _artifact_manifest,
)
from scripts.repair_stock_protocol_290_final_artifact import (
    PRE_REPAIR_MANIFEST_NAME,
    REPAIR_AUDIT_NAME,
    repair_final_artifact,
)


def test_repair_materializes_censoring_and_preserves_reconciled_counts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    pd.DataFrame(
        {
            "status": [
                "completed",
                "right_censored",
                "failed_due_to_data",
            ],
            "combination_id": ["a", "a", "a"],
        }
    ).to_parquet(tmp_path / OPPORTUNITIES_PARQUET, index=False)
    (tmp_path / AUDIT_SUMMARY_NAME).write_text(
        json.dumps(
            {
                "opportunity_count": 3,
                "completed": 1,
                "censored": 1,
                "failed_due_to_data": 1,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / FINAL_MANIFEST_NAME).write_text(
        json.dumps(_artifact_manifest(tmp_path)),
        encoding="utf-8",
    )

    audit = repair_final_artifact(tmp_path, source_run_id="123")
    repaired = pd.read_parquet(tmp_path / OPPORTUNITIES_PARQUET)
    final_manifest = json.loads(
        (tmp_path / FINAL_MANIFEST_NAME).read_text(encoding="utf-8")
    )

    assert repaired["censored"].tolist() == [False, True, False]
    assert audit["rows"] == 3
    assert audit["opportunities_removed"] == 0
    assert audit["statistics_recomputed"] is False
    assert (tmp_path / PRE_REPAIR_MANIFEST_NAME).is_file()
    assert (tmp_path / REPAIR_AUDIT_NAME).is_file()
    assert REPAIR_AUDIT_NAME in final_manifest["files"]
    assert PRE_REPAIR_MANIFEST_NAME in final_manifest["files"]
    assert OPPORTUNITIES_PARQUET in final_manifest["files"]

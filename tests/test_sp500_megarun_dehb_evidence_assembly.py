from __future__ import annotations

import json
from pathlib import Path


def _worker(root: Path, job_id: str, marker: str, *, complete: bool = True) -> None:
    artifact = root / f"sp500-dehb-worker-{job_id}"
    artifact.mkdir(parents=True)
    (artifact / "marker.txt").write_text(marker, encoding="utf-8")
    if complete:
        (artifact / "worker_result.json").write_text(
            json.dumps({"job_id": job_id}), encoding="utf-8"
        )


def test_evidence_assembly_keeps_latest_complete_retry_and_ignores_partial(
    tmp_path: Path,
) -> None:
    from scripts.assemble_sp500_megarun_dehb_evidence import (
        assemble_worker_evidence,
    )

    first = tmp_path / "first"
    retry = tmp_path / "retry"
    first.mkdir()
    retry.mkdir()
    _worker(first, "J001", "old")
    _worker(first, "J002", "stable")
    _worker(retry, "J001", "new")
    _worker(retry, "J002", "partial", complete=False)

    output = tmp_path / "combined"
    receipt = assemble_worker_evidence([first, retry], output_dir=output)

    assert receipt["complete_worker_count"] == 2
    assert (output / "sp500-dehb-worker-J001" / "marker.txt").read_text() == "new"
    assert (output / "sp500-dehb-worker-J002" / "marker.txt").read_text() == "stable"
    assert receipt["validation_opened"] is False
    assert receipt["locked_opened"] is False

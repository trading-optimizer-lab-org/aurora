from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import gtbi_fast_strict_inventory as inventory


FINGERPRINT = "f" * 64


def _campaign(tmp_path: Path, worker_count: int = 4) -> Path:
    path = tmp_path / "campaign_manifest.json"
    path.write_text(
        json.dumps(
            {
                "campaign_fingerprint": FINGERPRINT,
                "counts": {"worker_count": worker_count},
            }
        ),
        encoding="utf-8",
    )
    return path


def _worker(
    root: Path,
    worker_id: int,
    *,
    canonical: int = 2,
    evaluated: int = 1,
    early: int = 1,
    fingerprint: str = FINGERPRINT,
) -> None:
    target = root / f"worker-{worker_id:03d}"
    target.mkdir(parents=True)
    (target / "worker_summary.json").write_text(
        json.dumps(
            {
                "worker_id": worker_id,
                "campaign_fingerprint": fingerprint,
                "canonical_group_count": canonical,
                "total_strategies_evaluated": evaluated,
                "total_strategies_early_rejected": early,
                "total_strategies_timed_out": 0,
                "total_strategies_runtime_error": 0,
                "total_strategies_unsupported": 0,
                "total_strategies_slow_deferred": 0,
            }
        ),
        encoding="utf-8",
    )
    (target / "campaign_manifest.json").write_text(
        json.dumps({"campaign_fingerprint": fingerprint}),
        encoding="utf-8",
    )


def test_inventory_reports_only_missing_workers_and_splits_matrices(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, worker_count=360)
    artifacts = tmp_path / "artifacts"
    for worker_id in range(360):
        if worker_id not in {7, 205}:
            _worker(artifacts, worker_id)

    result = inventory.inventory_workers(
        campaign_manifest_path=campaign,
        input_roots=[artifacts],
        output_dir=tmp_path / "out",
    )

    assert result["valid_worker_count"] == 358
    assert result["missing_worker_ids"] == [7, 205]
    assert json.loads((tmp_path / "out/matrix_a.json").read_text())["include"] == [{"worker_id": 7}]
    assert json.loads((tmp_path / "out/matrix_b.json").read_text())["include"] == [{"worker_id": 205}]


def test_inventory_accepts_complete_campaign(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path)
    artifacts = tmp_path / "artifacts"
    for worker_id in range(4):
        _worker(artifacts, worker_id)

    result = inventory.inventory_workers(
        campaign_manifest_path=campaign,
        input_roots=[artifacts],
        output_dir=tmp_path / "out",
    )

    assert result["complete"] is True
    assert result["missing_worker_ids"] == []
    assert json.loads((tmp_path / "out/matrix_a.json").read_text()) == {"include": []}
    assert json.loads((tmp_path / "out/matrix_b.json").read_text()) == {"include": []}


def test_inventory_accepts_exact_smoke_worker_subset(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, worker_count=360)
    artifacts = tmp_path / "artifacts"
    for worker_id in (0, 1, 180, 181):
        _worker(artifacts, worker_id)

    result = inventory.inventory_workers(
        campaign_manifest_path=campaign,
        input_roots=[artifacts],
        output_dir=tmp_path / "out",
        expected_worker_ids=[0, 1, 180, 181],
    )

    assert result["campaign_worker_count"] == 360
    assert result["expected_worker_count"] == 4
    assert result["valid_worker_count"] == 4
    assert result["missing_worker_ids"] == []
    assert result["complete"] is True


def test_inventory_rejects_worker_outside_explicit_subset(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, worker_count=360)
    artifacts = tmp_path / "artifacts"
    _worker(artifacts, 0)
    _worker(artifacts, 2)

    with pytest.raises(ValueError, match="outside explicitly expected worker set"):
        inventory.inventory_workers(
            campaign_manifest_path=campaign,
            input_roots=[artifacts],
            output_dir=tmp_path / "out",
            expected_worker_ids=[0, 1],
        )


def test_inventory_treats_nonterminal_artifact_as_missing(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, worker_count=1)
    artifacts = tmp_path / "artifacts"
    _worker(artifacts, 0, canonical=2, evaluated=1, early=0)

    result = inventory.inventory_workers(
        campaign_manifest_path=campaign,
        input_roots=[artifacts],
        output_dir=tmp_path / "out",
    )

    assert result["missing_worker_ids"] == [0]
    assert result["invalid_workers"][0]["reason"] == "terminal_count_mismatch"


def test_inventory_rejects_duplicate_worker_artifacts(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, worker_count=1)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _worker(first, 0)
    _worker(second, 0)

    with pytest.raises(ValueError, match="duplicate valid artifacts"):
        inventory.inventory_workers(
            campaign_manifest_path=campaign,
            input_roots=[first, second],
            output_dir=tmp_path / "out",
        )


def test_inventory_rejects_mixed_campaign_or_out_of_range_worker(tmp_path: Path) -> None:
    campaign = _campaign(tmp_path, worker_count=1)
    mixed = tmp_path / "mixed"
    _worker(mixed, 0, fingerprint="a" * 64)
    with pytest.raises(ValueError, match="campaign fingerprint mismatch"):
        inventory.inventory_workers(
            campaign_manifest_path=campaign,
            input_roots=[mixed],
            output_dir=tmp_path / "out-mixed",
        )

    outside = tmp_path / "outside"
    _worker(outside, 1)
    with pytest.raises(ValueError, match="outside expected range"):
        inventory.inventory_workers(
            campaign_manifest_path=campaign,
            input_roots=[outside],
            output_dir=tmp_path / "out-outside",
        )

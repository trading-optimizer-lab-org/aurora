from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_source as source
from tests import test_catalog_checkpoint_recovery_source as legacy
from tests import test_catalog_checkpoint_recovery_source353 as source353


def _selected_rows(count: int = 13) -> list[dict[str, object]]:
    return [
        {
            "configuration": {"candidate": index, "weight": 1.0},
            "lane_id": f"lane-{index:02d}",
            "result": {
                "fitness": 1.0,
                "info": {"validation_opened": False, "locked_opened": False},
            },
            "source_strategy_key": f"selected-{index:02d}",
        }
        for index in range(count)
    ]


def _write_sidecar(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _set_selected_count(
    fixture: source353.SourceFixture, *, slot_index: int, count: int
) -> None:
    checkpoint_root = fixture["checkpoint_root"]
    previous_receipt_sha256 = "0" * 64
    for current_slot in range(1, 3):
        artifact_root = checkpoint_root / source353._checkpoint_name(0, current_slot)
        receipt_path = artifact_root / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["previous_checkpoint_receipt_sha256"] = previous_receipt_sha256
        if current_slot == slot_index:
            receipt["selected_strategy_count"] = count
        else:
            receipt.pop("selected_strategy_count", None)
        legacy._write_json(receipt_path, receipt)
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        attempt_path = artifact_root / "shard_attempt_manifest.json"
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        attempt["previous_checkpoint_receipt_sha256"] = previous_receipt_sha256
        attempt["receipt_sha256"] = receipt_sha256
        legacy._write_json(attempt_path, attempt)

        chain_path = artifact_root / "checkpoint_chain_manifest.json"
        chain = json.loads(chain_path.read_text(encoding="utf-8"))
        chain["previous_receipt_sha256"] = previous_receipt_sha256
        chain["current_receipt_sha256"] = receipt_sha256
        chain_identity = {key: value for key, value in chain.items() if key != "chain_sha256"}
        chain["chain_sha256"] = canonical_sha256(chain_identity)
        legacy._write_json(chain_path, chain)
        previous_receipt_sha256 = receipt_sha256


def test_layout2_accepts_the_bounded_selected_results_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = source353._build_source353_fixture(tmp_path, monkeypatch)
    artifact_root = fixture["checkpoint_root"] / source353._checkpoint_name(0, 1)
    _set_selected_count(fixture, slot_index=1, count=13)
    _write_sidecar(artifact_root / "selected_results.jsonl", _selected_rows())

    result = source353._verify_source353(fixture)

    assert result.checkpoint_count == 120


def test_layout2_unit_fixture_without_declared_selection_remains_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = source353._build_source353_fixture(tmp_path, monkeypatch)

    result = source353._verify_source353(fixture)

    assert result.worker_count == 60


@pytest.mark.parametrize("mutation", ["wrong_coordinate", "missing_declared", "nonzero_elsewhere"])
def test_layout2_selected_sidecar_namespace_and_receipt_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    fixture = source353._build_source353_fixture(tmp_path, monkeypatch)
    checkpoint_root = fixture["checkpoint_root"]
    if mutation == "wrong_coordinate":
        _write_sidecar(
            checkpoint_root / source353._checkpoint_name(0, 2) / "selected_results.jsonl",
            _selected_rows(),
        )
    elif mutation == "missing_declared":
        _set_selected_count(fixture, slot_index=1, count=13)
    else:
        _set_selected_count(fixture, slot_index=2, count=13)

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID"):
        source353._verify_source353(fixture)


@pytest.mark.parametrize("mutation", [
    "duplicate_json_key",
    "nonfinite",
    "wrong_fields",
    "wrong_configuration_type",
    "open_result",
    "duplicate_source_key",
    "wrong_row_count",
])
def test_selected_results_sidecar_is_strict_json_and_exactly_bounded(
    tmp_path: Path, mutation: str
) -> None:
    path = tmp_path / "selected_results.jsonl"
    rows = _selected_rows()
    if mutation == "duplicate_json_key":
        path.write_text(
            '{"configuration":{},"configuration":{},"lane_id":"lane",'
            '"result":{"info":{"validation_opened":false,"locked_opened":false}},'
            '"source_strategy_key":"selected"}\n',
            encoding="utf-8",
        )
    elif mutation == "nonfinite":
        rows[0]["configuration"] = {"weight": float("inf")}
        path.write_text(
            json.dumps(rows[0], sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "wrong_fields":
        rows[0]["extra"] = True
        _write_sidecar(path, rows)
    elif mutation == "wrong_configuration_type":
        rows[0]["configuration"] = []
        _write_sidecar(path, rows)
    elif mutation == "open_result":
        rows[0]["result"] = {
            "fitness": 1.0,
            "info": {"validation_opened": True, "locked_opened": False},
        }
        _write_sidecar(path, rows)
    elif mutation == "duplicate_source_key":
        rows[1]["source_strategy_key"] = rows[0]["source_strategy_key"]
        _write_sidecar(path, rows)
    else:
        _write_sidecar(path, rows[:12])

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID"):
        source._validate_selected_results_sidecar(path)


def test_layout4_keeps_the_checkpoint_inventory_closed_to_the_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = legacy._build_fixture(tmp_path, monkeypatch)
    artifact_root = fixture["checkpoint_root"] / "checkpoint-worker-000-slot-01"
    _write_sidecar(artifact_root / "selected_results.jsonl", _selected_rows())

    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID"):
        legacy._verify(fixture)

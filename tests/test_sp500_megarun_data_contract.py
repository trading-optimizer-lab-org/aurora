from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from aurora.infra.sp500_megarun.data_contract import (
    DataContractError,
    load_and_validate_contract,
    load_and_validate_source_plan,
    validate_snapshot_manifest,
)
from aurora.infra.sp500_megarun.source_adapters import registered_adapter_names


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_120.json"
SOURCE_PLAN_PATH = REPO_ROOT / "config" / "sp500_megarun_free_sources.json"


def _minimal_contract() -> dict[str, object]:
    lanes = [
        {
            "lane_id": f"F{index:03d}",
            "required_datasets": ["FREE_DAILY"],
            "fidelity": "exact",
            "original_dependency": "free daily observations",
            "replacement_note": "",
        }
        for index in range(1, 121)
    ]
    return {
        "schema_version": 1,
        "boundaries": {
            "search_start": "1998-01-01",
            "search_end": "2005-12-31",
            "evaluation_start": "2006-01-01",
            "evaluation_end": "2010-12-31",
            "validation_opened": False,
            "locked_opened": False,
        },
        "datasets": {
            "FREE_DAILY": {
                "provider": "Example official source",
                "url": "https://example.test/free.csv",
                "cost": "free",
                "license_status": "reviewed_for_research_download",
                "coverage_start": "1990-01-01",
                "causal_coverage_start": "1990-01-01",
                "coverage_end": "current",
                "causal_lag": "next_session",
                "adapter": "csv_daily",
                "readiness": "source_and_adapter_ready",
            }
        },
        "lanes": lanes,
    }


def test_repository_contract_resolves_all_120_lanes_to_free_search_eligible_data() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)

    assert len(contract.lanes) == 120
    assert [lane.lane_id for lane in contract.lanes] == [
        f"F{index:03d}" for index in range(1, 121)
    ]
    assert all(dataset.cost == "free" for dataset in contract.datasets.values())
    assert all(dataset.readiness == "source_and_adapter_ready" for dataset in contract.datasets.values())
    assert contract.boundaries.validation_opened is False
    assert contract.boundaries.locked_opened is False


def test_every_contract_adapter_is_registered_as_executable_code() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)

    declared = {dataset.adapter for dataset in contract.datasets.values()}

    assert declared <= registered_adapter_names()


def test_source_plan_covers_every_contracted_dataset_and_is_github_only() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)

    source_plan = load_and_validate_source_plan(SOURCE_PLAN_PATH, contract)

    assert set(source_plan) == set(contract.datasets)
    assert all(item.execution == "github_actions_only" for item in source_plan.values())
    assert all(item.maximum_observation_date.isoformat() == "2010-12-31" for item in source_plan.values())


def test_contract_rejects_paid_dataset_even_when_only_one_lane_uses_it(tmp_path: Path) -> None:
    payload = _minimal_contract()
    payload["datasets"]["FREE_DAILY"]["cost"] = "paid"  # type: ignore[index]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataContractError, match="NON_FREE_DATASET:FREE_DAILY"):
        load_and_validate_contract(path)


def test_contract_rejects_dataset_that_starts_after_search_start(tmp_path: Path) -> None:
    payload = _minimal_contract()
    payload["datasets"]["FREE_DAILY"]["coverage_start"] = "2001-01-01"  # type: ignore[index]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataContractError, match="SEARCH_COVERAGE_GAP:FREE_DAILY"):
        load_and_validate_contract(path)


def test_contract_rejects_backfilled_history_not_disseminated_by_search_start(
    tmp_path: Path,
) -> None:
    payload = _minimal_contract()
    payload["datasets"]["FREE_DAILY"]["causal_coverage_start"] = "2003-09-22"  # type: ignore[index]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataContractError, match="CAUSAL_SEARCH_COVERAGE_GAP:FREE_DAILY"):
        load_and_validate_contract(path)


def test_contract_requires_disclosure_for_proxy_or_redesigned_lane(tmp_path: Path) -> None:
    payload = _minimal_contract()
    payload["lanes"][84]["fidelity"] = "proxy"  # type: ignore[index]
    payload["lanes"][84]["replacement_note"] = ""  # type: ignore[index]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataContractError, match="UNDISCLOSED_REPLACEMENT:F085"):
        load_and_validate_contract(path)


def test_contract_rejects_missing_dataset_reference(tmp_path: Path) -> None:
    payload = _minimal_contract()
    payload["lanes"][0]["required_datasets"] = ["DOES_NOT_EXIST"]  # type: ignore[index]
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataContractError, match="UNKNOWN_DATASET:F001:DOES_NOT_EXIST"):
        load_and_validate_contract(path)


def test_snapshot_manifest_requires_every_dataset_and_forbids_post_evaluation_rows() -> None:
    payload = _minimal_contract()
    contract_path = Path("contract.json")
    manifest: dict[str, Any] = {
        "contract_sha256": "a" * 64,
        "datasets": {
            "FREE_DAILY": {
                "sha256": "b" * 64,
                "row_count": 123,
                "minimum_date": "1990-01-01",
                "maximum_date": "2010-12-31",
                "schema_valid": True,
                "causal_valid": True,
            }
        },
    }

    validated = validate_snapshot_manifest(
        payload,
        manifest,
        expected_contract_path=contract_path,
        verify_contract_hash=False,
    )

    assert validated.dataset_count == 1
    broken = copy.deepcopy(manifest)
    broken["datasets"]["FREE_DAILY"]["maximum_date"] = "2011-01-03"
    with pytest.raises(DataContractError, match="POST_EVALUATION_DATA:FREE_DAILY"):
        validate_snapshot_manifest(
            payload,
            broken,
            expected_contract_path=contract_path,
            verify_contract_hash=False,
        )

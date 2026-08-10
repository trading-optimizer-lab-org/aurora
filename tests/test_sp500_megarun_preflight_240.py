from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import pandas as pd

from aurora.infra.sp500_megarun.data_contract import (
    DataContractError,
    load_and_validate_contract,
    load_and_validate_source_plan,
    validate_snapshot_partitions,
)
from aurora.infra.sp500_megarun.source_adapters import registered_adapter_names
from aurora.infra.sp500_megarun.preflight_240 import (
    Preflight240Error,
    build_derived_dataset,
    partition_dataset_frame,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
SOURCE_PLAN_PATH = REPO_ROOT / "config" / "sp500_megarun_free_sources_240.json"


def test_repository_contract_freezes_240_lanes_and_three_physical_periods() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)

    assert contract.expected_lane_count == 240
    assert [lane.lane_id for lane in contract.lanes] == [
        f"F{index:03d}" for index in range(1, 241)
    ]
    assert contract.boundaries.warmup_start.isoformat() == "1993-01-22"
    assert contract.boundaries.search_start.isoformat() == "1998-01-01"
    assert contract.boundaries.search_end.isoformat() == "2010-12-31"
    assert contract.boundaries.evaluation_start.isoformat() == "2011-01-01"
    assert contract.boundaries.evaluation_end.isoformat() == "2020-12-31"
    assert contract.boundaries.locked_start.isoformat() == "2021-01-01"
    assert contract.boundaries.validation_opened is False
    assert contract.boundaries.locked_opened is False
    assert all(dataset.cost == "free" for dataset in contract.datasets.values())
    assert all(dataset.available_at_rule for dataset in contract.datasets.values())
    assert "D_SEC_INDEX" not in contract.datasets
    lane_dependencies = {
        lane.lane_id: set(lane.required_datasets) for lane in contract.lanes
    }
    assert lane_dependencies["F231"] == {"D_PHILLY_RT"}
    assert lane_dependencies["F232"] == {"D_TREASURY_AUCTIONS"}
    assert lane_dependencies["F233"] == {"D_FOMC_PUBLIC"}
    assert lane_dependencies["F234"] == {"D_TIC"}
    assert "D_SEC_INDEX" not in lane_dependencies["F240"]


def test_repository_source_plan_is_github_only_and_stops_at_2020() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)
    source_plan = load_and_validate_source_plan(SOURCE_PLAN_PATH, contract)

    assert set(source_plan) == set(contract.datasets)
    assert all(item.execution == "github_actions_only" for item in source_plan.values())
    assert all(
        item.maximum_observation_date.isoformat() == "2020-12-31"
        for item in source_plan.values()
    )
    assert {dataset.adapter for dataset in contract.datasets.values()} <= registered_adapter_names()
    cftc_resources = {
        str(resource["id"]): tuple(resource.get("years", ()))
        for resource in source_plan["D_CFTC"].resources
    }
    assert min(cftc_resources["legacy_futures_only"]) == 1986
    assert min(cftc_resources["legacy_futures_options_early"]) == 1995
    french_resources = {
        str(resource["id"])
        for resource in source_plan["D_FRENCH_FACTORS"].resources
    }
    assert french_resources == {
        "ff3_daily",
        "size_daily",
        "book_to_market_daily",
        "profitability_daily",
        "investment_daily",
        "momentum_10_daily",
        "short_reversal_10_daily",
        "long_reversal_10_daily",
        "accruals_monthly",
        "beta_monthly",
        "net_share_issues_monthly",
        "variance_monthly",
        "residual_variance_monthly",
    }
    global_french_resources = {
        str(resource["id"])
        for resource in source_plan["D_FRENCH_GLOBAL"].resources
    }
    assert global_french_resources == {
        "developed_five_factors",
        "developed_momentum",
        "developed_ex_us",
        "europe",
        "japan",
        "asia_pacific_ex_japan",
        "developed_ex_us_momentum",
        "europe_momentum",
        "japan_momentum",
        "asia_pacific_ex_japan_momentum",
    }


def test_partition_gate_keeps_train_and_validation_separate_and_rejects_2021() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)
    dataset_rows = {
        dataset_id: {
            "sha256": "b" * 64,
            "row_count": 10,
            "minimum_date": "1993-01-22",
            "maximum_date": "2010-12-31",
            "schema_valid": True,
            "causal_valid": True,
        }
        for dataset_id in contract.datasets
    }
    train = {
        "contract_sha256": contract.sha256,
        "partition": "train",
        "mountable_by_first_cycle": True,
        "datasets": dataset_rows,
    }
    validation = {
        "contract_sha256": contract.sha256,
        "partition": "validation",
        "mountable_by_first_cycle": False,
        "datasets": {
            dataset_id: {
                **row,
                "minimum_date": "2011-01-01",
                "maximum_date": "2020-12-31",
            }
            for dataset_id, row in dataset_rows.items()
        },
    }

    result = validate_snapshot_partitions(contract, train, validation)

    assert result["train_maximum_date"] == "2010-12-31"
    assert result["validation_maximum_date"] == "2020-12-31"
    broken = copy.deepcopy(validation)
    broken["datasets"][next(iter(contract.datasets))]["maximum_date"] = "2021-01-04"
    with pytest.raises(DataContractError, match="LOCKED_DATA_PRESENT"):
        validate_snapshot_partitions(contract, train, broken)


def test_v2_contract_rejects_missing_available_at_rule(tmp_path: Path) -> None:
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    payload["extends"] = str(REPO_ROOT / "config" / "sp500_megarun_free_data_120.json")
    first_dataset = next(iter(payload["datasets"]))
    payload["datasets"][first_dataset]["available_at_rule"] = ""
    target = tmp_path / "broken.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DataContractError, match=f"MISSING_AVAILABLE_AT_RULE:{first_dataset}"):
        load_and_validate_contract(target)


def test_partitioning_is_physical_and_locked_rows_fail_instead_of_being_trimmed() -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["1993-01-22", "2010-12-31", "2011-01-03", "2020-12-31"]),
            "value": [1, 2, 3, 4],
        }
    )

    train, validation = partition_dataset_frame(frame, contract.boundaries, dataset_id="D_TEST")

    assert train["date"].max().date().isoformat() == "2010-12-31"
    assert validation["date"].min().date().isoformat() == "2011-01-03"
    assert set(train.index).isdisjoint(validation.index)
    locked = pd.concat(
        [frame, pd.DataFrame({"date": [pd.Timestamp("2021-01-04")], "value": [5]})],
        ignore_index=True,
    )
    with pytest.raises(Preflight240Error, match="LOCKED_DATA_PRESENT:D_TEST"):
        partition_dataset_frame(locked, contract.boundaries, dataset_id="D_TEST")


def test_derived_grouped_datasets_preserve_source_lineage() -> None:
    frames = {
        "D_RATES": pd.DataFrame({"date": pd.to_datetime(["2020-01-02"]), "value": [1.5]}),
        "D_FX": pd.DataFrame({"date": pd.to_datetime(["2020-01-02"]), "value": [1.1]}),
    }

    derived = build_derived_dataset("D_FED_H15_H10", frames)

    assert set(derived["source_dataset"]) == {"D_RATES", "D_FX"}
    assert derived["date"].dt.strftime("%Y-%m-%d").tolist() == ["2020-01-02", "2020-01-02"]

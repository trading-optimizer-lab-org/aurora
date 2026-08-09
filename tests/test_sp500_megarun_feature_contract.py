from __future__ import annotations

import importlib
import json
from pathlib import Path

import pandas as pd
import pytest

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
FEATURE_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json"


def _feature_contract_api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.feature_contract")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"feature contract implementation is missing: {exc}")


def test_repository_feature_contract_freezes_240_blueprints_and_tracks_executable_lanes() -> None:
    api = _feature_contract_api()
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)

    feature_contract = api.load_and_validate_feature_contract(
        FEATURE_CONTRACT_PATH,
        data_contract,
    )

    assert [lane.lane_id for lane in feature_contract.lanes] == [
        f"F{index:03d}" for index in range(1, 241)
    ]
    assert len({lane.canonical_sha256 for lane in feature_contract.lanes}) == 240
    assert all(lane.formula.strip() for lane in feature_contract.lanes)
    assert all(lane.operator in api.registered_operator_names() for lane in feature_contract.lanes)
    assert all(lane.minimum_history >= 1 for lane in feature_contract.lanes)
    assert all(lane.position_values == (-1, 1) for lane in feature_contract.lanes)
    assert all(lane.available_at_mode == "max_input_available_at" for lane in feature_contract.lanes)
    assert all(
        set(lane.required_datasets)
        == set(data_contract.lanes[index].required_datasets)
        for index, lane in enumerate(feature_contract.lanes)
    )
    assert feature_contract.validation_opened is False
    assert feature_contract.locked_opened is False
    assert feature_contract.search_end.isoformat() == "2010-12-31"
    assert feature_contract.lanes[31].lane_id == "F032"
    assert feature_contract.lanes[31].required_datasets == ("D_RATES",)
    assert [
        lane.lane_id for lane in feature_contract.lanes if lane.implementation_status == "executable"
    ] == [f"F{index:03d}" for index in range(1, 33)]
    assert all(
        lane.implementation_status == "blueprint_only"
        for lane in feature_contract.lanes[32:]
    )


def test_available_at_is_projected_to_sessions_without_looking_forward() -> None:
    api = _feature_contract_api()
    sessions = pd.DatetimeIndex(
        pd.to_datetime(["2010-12-23", "2010-12-27", "2010-12-28", "2010-12-29"])
    )
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-12-23", "2010-12-24"]),
            "value": [1.0, 2.0],
        }
    )

    projected = api.apply_available_at_policy(
        frame,
        policy="next_session",
        sessions=sessions,
    )

    assert projected["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-12-23",
        "2010-12-24",
    ]
    assert projected["available_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-12-27",
        "2010-12-27",
    ]
    assert projected["available_at"].ge(projected["observed_at"]).all()


def test_feature_availability_uses_the_slowest_input() -> None:
    api = _feature_contract_api()
    inputs = pd.DataFrame(
        {
            "price_available_at": pd.to_datetime(["2010-06-01", "2010-06-02"]),
            "macro_available_at": pd.to_datetime(["2010-06-03", "2010-06-02"]),
        }
    )

    result = api.maximum_input_available_at(
        inputs,
        ["price_available_at", "macro_available_at"],
    )

    assert result.dt.strftime("%Y-%m-%d").tolist() == ["2010-06-03", "2010-06-02"]


def test_monthly_publication_policy_waits_until_third_session_of_next_month() -> None:
    api = _feature_contract_api()
    sessions = pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2010-01-29",
                "2010-02-01",
                "2010-02-02",
                "2010-02-03",
                "2010-02-04",
            ]
        )
    )
    frame = pd.DataFrame({"date": pd.to_datetime(["2010-01-01"]), "value": [4.0]})

    projected = api.apply_available_at_policy(
        frame,
        policy="next_month_third_session",
        sessions=sessions,
    )

    assert projected["available_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-02-03"
    ]


def test_every_dataset_has_a_machine_readable_availability_policy() -> None:
    api = _feature_contract_api()
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)

    policies = api.dataset_available_at_policies()

    assert set(policies) == set(data_contract.datasets)
    assert all(policy in api.registered_available_at_policies() for policy in policies.values())
    assert policies["D_SPY"] == "next_session"
    assert policies["D_VIX"] == "next_session"
    assert policies["D_VXO"] == "next_session"
    assert policies["D_CBOE_VOL"] == "next_session"
    assert policies["D_CFTC_LEGACY"] == "friday_after_tuesday"
    assert policies["D_NOAA_NY"] == "two_calendar_days"


def test_cross_matrix_is_frozen_and_does_not_allow_a_cartesian_product() -> None:
    api = _feature_contract_api()
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)
    feature_contract = api.load_and_validate_feature_contract(
        FEATURE_CONTRACT_PATH,
        data_contract,
    )

    assert len(feature_contract.cross_rules) >= 10
    assert all(rule.max_features <= 5 for rule in feature_contract.cross_rules)
    assert api.is_cross_allowed(feature_contract, "F001", "F019") is True
    assert api.is_cross_allowed(feature_contract, "F009", "F022") is True
    assert api.is_cross_allowed(feature_contract, "F039", "F001") is True
    assert api.is_cross_allowed(feature_contract, "F001", "F239") is False


def test_feature_contract_rejects_a_duplicate_formula(tmp_path: Path) -> None:
    api = _feature_contract_api()
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)
    payload = json.loads(FEATURE_CONTRACT_PATH.read_text(encoding="utf-8"))
    payload["lanes"][1]["formula"] = payload["lanes"][0]["formula"]
    payload["lanes"][1]["operator"] = payload["lanes"][0]["operator"]
    target = tmp_path / "duplicate.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(api.FeatureContractError, match="DUPLICATE_CANONICAL_FORMULA"):
        api.load_and_validate_feature_contract(target, data_contract)


def test_feature_contract_rejects_validation_or_locked_access(tmp_path: Path) -> None:
    api = _feature_contract_api()
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)
    payload = json.loads(FEATURE_CONTRACT_PATH.read_text(encoding="utf-8"))
    payload["boundaries"]["validation_opened"] = True
    target = tmp_path / "opened.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(api.FeatureContractError, match="VALIDATION_MUST_REMAIN_CLOSED"):
        api.load_and_validate_feature_contract(target, data_contract)

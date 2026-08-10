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
    assert all(
        lane.available_at_mode == "max_input_available_at" for lane in feature_contract.lanes
    )
    assert all(
        set(lane.required_datasets) == set(data_contract.lanes[index].required_datasets)
        for index, lane in enumerate(feature_contract.lanes)
    )
    assert feature_contract.validation_opened is False
    assert feature_contract.locked_opened is False
    assert feature_contract.search_end.isoformat() == "2010-12-31"
    assert feature_contract.lanes[31].lane_id == "F032"
    assert feature_contract.lanes[31].required_datasets == ("D_RATES",)
    assert [
        lane.lane_id
        for lane in feature_contract.lanes
        if lane.implementation_status == "executable"
    ] == [f"F{index:03d}" for index in range(1, 231)]
    assert all(
        lane.implementation_status == "blueprint_only" for lane in feature_contract.lanes[230:]
    )
    model_lanes = feature_contract.lanes[50:60]
    assert all("approved_features" not in lane.formula for lane in model_lanes)
    assert all(lane.minimum_history >= 5 for lane in model_lanes)
    assert model_lanes[5].parameter_space["model"] == ("logit", "probit")
    assert model_lanes[6].parameter_space["model"] == ("gam", "pls")
    assert model_lanes[7].parameter_space["model"] == ("tree", "boosted_stumps")
    advanced_lanes = feature_contract.lanes[60:70]
    assert all(lane.required_datasets == ("D_SPY",) for lane in advanced_lanes)
    assert advanced_lanes[1].parameter_space["kind"] == (
        "local_level",
        "local_trend",
        "kalman_slope",
    )
    assert "states" not in advanced_lanes[1].parameter_space
    assert advanced_lanes[3].parameter_space == {
        "period": (5, 10, 20, 40, 63),
        "window": (126, 252, 504),
        "detrend": ("mean", "linear"),
        "phase_stability": (0.0, 0.25, 0.5, 0.75),
    }
    assert advanced_lanes[4].parameter_space["statistic"] == (
        "binary_entropy",
        "lempel_ziv",
    )
    assert "bins" not in advanced_lanes[5].parameter_space
    assert advanced_lanes[8].parameter_space["student_df"] == (5, 8, 12)
    assert advanced_lanes[9].parameter_space["estimator"] == (
        "close",
        "parkinson",
        "garman_klass",
        "rogers_satchell",
    )
    assert all(lane.minimum_history >= 252 for lane in advanced_lanes)
    microstructure_lanes = feature_contract.lanes[70:80]
    assert all(lane.required_datasets == ("D_SPY",) for lane in microstructure_lanes)
    assert microstructure_lanes[0].parameter_space["statistic"] == (
        "semivariance_imbalance",
        "bipower_share",
        "jump_proxy",
    )
    assert microstructure_lanes[2].parameter_space["length"] == (2, 3, 4, 5)
    assert microstructure_lanes[6].parameter_space["statistic"] == (
        "imbalance",
        "obv_slope",
        "pressure",
    )
    assert microstructure_lanes[7].parameter_space["estimator"] == (
        "roll",
        "corwin_schultz",
        "amihud",
    )
    assert microstructure_lanes[9].parameter_space["logic"] == (
        "gate",
        "attenuate",
    )
    assert all(lane.minimum_history >= 5 for lane in microstructure_lanes)
    positioning_lanes = feature_contract.lanes[80:90]
    assert positioning_lanes[0].required_datasets == (
        "D_SPY",
        "D_Z1",
        "D_FINRA_MARGIN",
    )
    assert positioning_lanes[2].parameter_space["statistic"] == (
        "noncommercial_short",
        "reportable_short",
        "short_pressure",
    )
    assert positioning_lanes[4].parameter_space["statistic"] == (
        "close_location",
        "range_volume_pressure",
        "signed_volume_shock",
        "persistence",
    )
    assert positioning_lanes[7].parameter_space["statistic"] == (
        "top4_level",
        "top8_level",
        "top4_top8_share",
        "combined_gap",
        "change",
    )
    assert positioning_lanes[9].parameter_space["statistic"] == (
        "common_correlation",
        "variance_gap",
        "correlation_gap",
        "interaction",
    )
    assert all(lane.minimum_history >= 4 for lane in positioning_lanes)
    tail_macro_lanes = feature_contract.lanes[90:100]
    assert tail_macro_lanes[0].parameter_space["statistic"] == (
        "vol_of_vol",
        "methodology_disagreement",
        "realized_tail",
        "convexity_interaction",
    )
    assert tail_macro_lanes[1].parameter_space["statistic"] == (
        "variance_premium",
        "continuous_premium",
        "jump_share",
        "risk_compensation",
    )
    assert tail_macro_lanes[4].parameter_space["statistic"] == (
        "rate_volatility",
        "volatility_ratio",
        "divergence",
        "shock",
    )
    assert tail_macro_lanes[7].parameter_space["statistic"] == (
        "surprise_breadth",
        "surprise_magnitude",
        "growth_surprise",
        "dispersion",
    )
    assert tail_macro_lanes[9].required_datasets == (
        "D_RATES",
        "D_MACRO_PIT",
        "D_CALENDAR",
        "D_FOMC_PUBLIC",
    )
    assert tail_macro_lanes[9].parameter_space["statistic"] == (
        "policy_change",
        "real_rate",
        "rule_gap",
        "event_interaction",
    )
    assert all(lane.minimum_history >= 13 for lane in tail_macro_lanes)
    fundamental_lanes = feature_contract.lanes[100:110]
    assert fundamental_lanes[0].parameter_space["statistic"] == (
        "news_seasonality",
        "earnings_news",
        "dividend_news",
        "quarterly_cycle",
    )
    assert fundamental_lanes[2].parameter_space["statistic"] == (
        "earnings_growth",
        "dividend_growth",
        "payout_change",
        "decomposition",
    )
    assert "no margin claim" in fundamental_lanes[2].formula.casefold()
    assert fundamental_lanes[3].required_datasets == ("D_GOYAL", "D_Z1")
    assert fundamental_lanes[6].parameter_space["statistic"] == (
        "recession_pressure",
        "growth_state",
        "labor_state",
        "curve_state",
    )
    assert fundamental_lanes[9].parameter_space["statistic"] == (
        "oil_gold_ratio",
        "relative_momentum",
        "inflation_impulse",
        "shock_divergence",
    )
    assert all(lane.minimum_history >= 20 for lane in fundamental_lanes)
    cross_section_lanes = feature_contract.lanes[110:120]
    assert cross_section_lanes[0].parameter_space["statistic"] == (
        "cyclical_defensive_spread",
        "leadership_breadth",
        "rotation",
        "dispersion_gap",
    )
    assert cross_section_lanes[8].required_datasets[1] == "D_CBOE_VOL"
    assert cross_section_lanes[8].parameter_space["statistic"] == (
        "mean_forecast",
        "median_forecast",
        "consensus",
        "disagreement",
    )
    assert cross_section_lanes[9].parameter_space["features"] == (3, 5, 7)
    technical_lanes = feature_contract.lanes[120:130]
    assert all(lane.required_datasets == ("D_SPY",) for lane in technical_lanes)
    assert technical_lanes[0].parameter_space["statistic"] == (
        "high_distance",
        "low_distance",
        "range_position",
        "confirmed_breakout",
    )
    assert "shift(1)" in technical_lanes[0].formula
    assert technical_lanes[3].parameter_space["statistic"] == (
        "conversion_base_spread",
        "cloud_position",
        "cloud_width",
        "cloud_breakout",
    )
    assert "never forward-shift" in technical_lanes[3].formula
    assert technical_lanes[6].parameter_space["statistic"] == (
        "heikin_ashi",
        "renko",
        "point_figure",
        "consensus",
    )
    assert technical_lanes[9].parameter_space["statistic"] == (
        "chaikin_money_flow",
        "money_flow_index",
        "force_index",
        "ease_of_movement",
        "klinger_oscillator",
        "consensus",
    )
    assert all(lane.minimum_history >= 20 for lane in technical_lanes)
    nonlinear_lanes = feature_contract.lanes[130:140]
    assert nonlinear_lanes[0].parameter_space["statistic"] == (
        "high_frequency_share",
        "low_frequency_share",
        "energy_entropy",
        "scale_concentration",
    )
    assert "trailing-only" in nonlinear_lanes[1].formula
    assert nonlinear_lanes[3].required_datasets == ("D_SPY", "D_CALENDAR")
    assert "exclude the current return" in nonlinear_lanes[3].formula
    assert "candidate continuation" in nonlinear_lanes[4].formula
    assert nonlinear_lanes[5].parameter_space["statistic"] == (
        "recurrence_rate",
        "recurrence_entropy",
        "determinism",
        "laminarity",
    )
    assert nonlinear_lanes[9].parameter_space["kind"] == (
        "setar",
        "star",
        "observable_threshold",
    )
    assert all(lane.minimum_history >= 63 for lane in nonlinear_lanes)
    predictive_lanes = feature_contract.lanes[140:150]
    assert predictive_lanes[0].parameter_space["kind"] == (
        "ar",
        "arma",
        "distributed_regression",
    )
    assert "known at decision t" in predictive_lanes[0].formula
    assert predictive_lanes[1].parameter_space["kind"] == ("var", "vecm")
    assert predictive_lanes[2].parameter_space["approved_feature_set"] == ("core_causal_5",)
    assert "F003,F015,F021,F032,F039" in predictive_lanes[2].formula
    assert predictive_lanes[4].parameter_space["kind"] == (
        "linear",
        "rbf",
        "polynomial",
    )
    assert predictive_lanes[5].parameter_space["kind"] == (
        "random_forest",
        "extra_trees",
    )
    assert predictive_lanes[8].parameter_space["kind"] == (
        "reservoir",
        "small_rnn",
    )
    assert predictive_lanes[9].parameter_space["kind"] == ("attention", "moe")
    assert all(lane.minimum_history >= 126 for lane in predictive_lanes)
    characteristic_lanes = feature_contract.lanes[150:160]
    assert all(lane.implementation_status == "executable" for lane in characteristic_lanes)
    global_factor_lanes = feature_contract.lanes[160:170]
    assert all(lane.implementation_status == "executable" for lane in global_factor_lanes)
    assert global_factor_lanes[0].parameter_space["mode"] == (
        "level",
        "change",
        "divergence",
    )
    assert global_factor_lanes[4].parameter_space["statistic"] == (
        "dispersion",
        "sign_disagreement",
        "regime_change",
        "mean_correlation",
    )
    assert global_factor_lanes[5].required_datasets == (
        "D_FRENCH_US",
        "D_FRENCH_GLOBAL",
    )
    assert "proxy only" in global_factor_lanes[5].formula
    assert global_factor_lanes[8].parameter_space["universe"] == (
        "regions_only",
        "developed_ex_us_plus_regions",
        "all_available",
    )
    cross_asset_lanes = feature_contract.lanes[170:180]
    assert all(lane.implementation_status == "executable" for lane in cross_asset_lanes)
    assert cross_asset_lanes[0].parameter_space["statistic"] == (
        "official_broad",
        "cross_mean",
        "breadth",
        "divergence",
        "dispersion",
    )
    assert cross_asset_lanes[1].parameter_space["statistic"] == (
        "cash_level",
        "offshore_basis",
        "carry_pressure",
        "fx_adjusted_pressure",
    )
    assert "not a cross-currency rate differential" in cross_asset_lanes[1].formula
    assert cross_asset_lanes[8].parameter_space["statistic"] == (
        "carry",
        "roll",
        "momentum",
        "total",
    )
    rates_credit_lanes = feature_contract.lanes[180:190]
    assert all(lane.implementation_status == "executable" for lane in rates_credit_lanes)
    assert rates_credit_lanes[0].parameter_space["statistic"] == (
        "level",
        "slope_10y_3m",
        "curvature_2_5_10",
        "long_curvature_5_10_20",
    )
    assert rates_credit_lanes[2].required_datasets == ("D_SPF",)
    assert "expected-real-rate proxy" in rates_credit_lanes[2].formula
    assert "not income velocity" in rates_credit_lanes[6].formula
    assert "not delinquency" in rates_credit_lanes[7].formula
    realtime_survey_lanes = feature_contract.lanes[190:200]
    assert all(lane.implementation_status == "executable" for lane in realtime_survey_lanes)
    assert realtime_survey_lanes[0].parameter_space["statistic"] == (
        "output_growth",
        "gdi_growth",
        "average_growth",
        "growth_spread",
        "revision_breadth",
        "growth_breadth",
    )
    assert realtime_survey_lanes[2].required_datasets == ("D_MACRO_PIT",)
    assert realtime_survey_lanes[8].required_datasets == ("D_SPF", "D_MACRO_PIT")
    assert "not claimed as historical-vintage PIT exact" in realtime_survey_lanes[9].formula


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

    assert projected["available_at"].dt.strftime("%Y-%m-%d").tolist() == ["2010-02-03"]


def test_h10_policy_waits_for_following_week_release_and_next_session() -> None:
    api = _feature_contract_api()
    sessions = pd.bdate_range("2010-01-04", "2010-01-20")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-04", "2010-01-08"]),
            "value": [1.0, 2.0],
        }
    )

    projected = api.apply_available_at_policy(
        frame,
        policy="h10_following_week_release_plus_session",
        sessions=sessions,
    )

    assert projected["available_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-12",
        "2010-01-12",
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
    assert policies["D_FX"] == "h10_following_week_release_plus_session"
    assert policies["D_NOAA_NY"] == "two_calendar_days"
    assert policies["D_SLOOS"] == "quarter_end_plus_60_days_next_session"


def test_sloos_policy_waits_sixty_days_after_quarter_end() -> None:
    api = _feature_contract_api()
    sessions = pd.DatetimeIndex(
        pd.to_datetime(["2010-05-27", "2010-05-28", "2010-06-01", "2010-06-02"])
    )
    frame = pd.DataFrame({"date": pd.to_datetime(["2010-03-31"]), "value": [1.0]})

    projected = api.apply_available_at_policy(
        frame,
        policy="quarter_end_plus_60_days_next_session",
        sessions=sessions,
    )

    assert projected["available_at"].dt.strftime("%Y-%m-%d").tolist() == ["2010-06-01"]


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

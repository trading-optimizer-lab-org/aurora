from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.financial_accounts_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"financial-accounts feature engine is missing: {exc}")


def _timed(dates: pd.DatetimeIndex, values: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    market = _timed(
        dates,
        {"close": 100.0 * np.exp(np.cumsum(0.0002 + 0.003 * np.sin(phase / 31.0)))},
    )
    quarterly = dates[60::63]
    q = np.arange(len(quarterly), dtype=float)
    financial = _timed(
        quarterly,
        {
            "household_equity": 8_000.0 + 200.0 * q + 500.0 * np.sin(q / 4.0),
            "household_financial_assets": 30_000.0 + 500.0 * q,
            "household_liabilities": 7_000.0 + 120.0 * q,
            "household_checkable": 1_000.0 + 20.0 * q,
            "household_time_deposits": 2_500.0 + 25.0 * q,
            "household_mmf": 800.0 + 15.0 * q,
            "corporate_financial_assets": 9_000.0 + 180.0 * q,
            "corporate_liabilities": 12_000.0 + 260.0 * q,
            "corporate_checkable": 600.0 + 18.0 * q,
            "corporate_time_deposits": 400.0 + 10.0 * q,
            "corporate_mmf": 250.0 + 8.0 * q,
            "corporate_debt": 5_000.0 + 130.0 * q,
            "corporate_net_issuance": 80.0 * np.sin(q / 3.0),
            "mutual_fund_total_assets": 6_000.0 + 220.0 * q,
            "mutual_fund_equity": 3_500.0 + 150.0 * q + 100.0 * np.sin(q / 3.0),
            "mutual_fund_flow": 120.0 * np.sin(q / 4.0),
            "etf_total_assets": 300.0 + 70.0 * q,
            "etf_equity": 220.0 + 50.0 * q,
            "etf_flow": 40.0 * np.cos(q / 4.0),
            "mmf_total_assets": 1_500.0 + 60.0 * q,
            "mmf_flow": 90.0 * np.cos(q / 5.0),
            "mmf_treasury": 500.0 + 30.0 * q,
            "mmf_commercial_paper": 350.0 + 5.0 * q,
            "broker_total_assets": 2_000.0 + 80.0 * q,
            "broker_liabilities": 1_850.0 + 75.0 * q,
            "broker_repo_assets": 600.0 + 25.0 * q,
            "broker_repo_liabilities": 750.0 + 30.0 * q,
            "foreign_treasury_purchases": 100.0 * np.sin(q / 3.5),
            "foreign_bond_purchases": 80.0 * np.cos(q / 4.0),
            "foreign_equity_purchases": 90.0 * np.sin((q + 1.0) / 4.5),
            "foreign_mutual_fund_purchases": 20.0 * np.cos(q / 5.0),
        },
    )
    monthly = dates[20::21]
    m = np.arange(len(monthly), dtype=float)
    tic = _timed(
        monthly,
        {
            "tic_treasury_net_purchases": 40.0 * np.sin(m / 6.0),
            "tic_equity_net_purchases": 30.0 * np.cos(m / 7.0),
            "tic_treasury_official": 10.0 * np.sin(m / 5.0),
            "tic_equity_official": 8.0 * np.cos(m / 6.0),
        },
    )
    return market, {"financial_accounts": financial, "tic": tic}


_DEFAULTS = {
    "F201": "household_equity_share",
    "F202": "household_leverage",
    "F203": "corporate_leverage",
    "F204": "issuance_to_assets",
    "F205": "mutual_fund_flow_rate",
    "F206": "etf_flow_rate",
    "F207": "mmf_flow_rate",
    "F208": "dealer_capacity",
    "F209": "combined_foreign_flow",
    "F210": "interconnection_composite",
}


def _parameters(lane: str) -> dict[str, object]:
    return {
        "statistic": _DEFAULTS[lane],
        "window": 8,
        "change_lag": 1,
        "normalization": "raw",
        "direction": "continuation",
    }


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(201, 211)])
def test_f201_f210_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_financial_accounts_lane(
        lane, market, panels, _parameters(lane)
    )

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(201, 211)])
def test_f201_f210_do_not_change_when_future_train_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[1300, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy() for name, panel in panels.items()
    }

    before = api.evaluate_financial_accounts_lane(
        lane, before_market, before_panels, _parameters(lane)
    )
    after = api.evaluate_financial_accounts_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "variants"),
    [
        ("F201", ("household_equity_share", "household_liquid_share", "equity_liquidity_ratio", "equity_share_change", "risk_appetite")),
        ("F202", ("household_leverage", "liquid_assets_to_liabilities", "liabilities_growth", "liquidity_growth", "household_balance_composite")),
        ("F203", ("corporate_leverage", "corporate_liquid_share", "corporate_debt_share", "corporate_liquidity_change", "corporate_balance_composite")),
        ("F204", ("corporate_net_issuance", "issuance_to_assets", "issuance_change", "issuance_pressure")),
        ("F205", ("mutual_fund_equity_share", "mutual_fund_flow_rate", "mutual_fund_assets_growth", "equity_flow_interaction")),
        ("F206", ("etf_equity_share", "etf_flow_rate", "etf_assets_growth", "etf_mutual_growth_spread")),
        ("F207", ("mmf_flow_rate", "mmf_assets_growth", "treasury_share", "commercial_paper_share", "liquidity_preference")),
        ("F208", ("broker_leverage", "repo_funding_share", "repo_asset_share", "broker_assets_growth", "dealer_capacity")),
        ("F209", ("tic_treasury_flow", "tic_equity_flow", "tic_total_flow", "z1_foreign_flow", "combined_foreign_flow", "equity_treasury_divergence")),
        ("F210", ("household_to_fund", "fund_to_broker", "broker_to_business", "interconnection_mean", "interconnection_max", "interconnection_composite")),
    ],
)
def test_f201_f210_frozen_statistics_are_executable(
    lane: str, variants: tuple[str, ...]
) -> None:
    market, panels = _inputs()
    for statistic in variants:
        parameters = {**_parameters(lane), "statistic": statistic}
        result = _api().evaluate_financial_accounts_lane(lane, market, panels, parameters)
        assert result["value"].notna().any(), f"{lane}:{statistic}"


def test_financial_accounts_engine_fails_closed() -> None:
    api = _api()
    market, panels = _inputs()
    with pytest.raises(api.FinancialAccountsFeatureEngineError, match="UNKNOWN_LANE"):
        api.evaluate_financial_accounts_lane("F211", market, panels, {})
    with pytest.raises(api.FinancialAccountsFeatureEngineError, match="UNKNOWN_PARAMETER"):
        api.evaluate_financial_accounts_lane(
            "F201", market, panels, {**_parameters("F201"), "statistic": "invented"}
        )
    future = market.copy()
    future.loc[len(future)] = future.iloc[-1]
    future.loc[len(future) - 1, ["date", "observed_at", "available_at"]] = pd.Timestamp(
        "2011-01-03"
    )
    with pytest.raises(api.FinancialAccountsFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_financial_accounts_lane("F201", future, panels, _parameters("F201"))

from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.policy_treasury_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"policy-Treasury feature engine is missing: {exc}")


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
    dates = pd.bdate_range("1997-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    market = _timed(
        dates,
        {"close": 100.0 * np.exp(np.cumsum(0.0002 + 0.004 * np.sin(phase / 31.0)))},
    )
    event_dates = dates[20::42]
    e = np.arange(len(event_dates), dtype=float)
    decisions = _timed(
        event_dates,
        {
            "meeting_count": np.ones(len(e)),
            "statement_count": (e % 3 != 0).astype(float),
            "conference_call": (e % 11 == 0).astype(float),
        },
    )
    policy_rate = _timed(
        dates[1::5],
        {"effective_fed_funds": 4.0 + 0.8 * np.sin(np.arange(len(dates[1::5])) / 19.0)},
    )
    statement_dates = dates[25::43]
    s = np.arange(len(statement_dates), dtype=float)
    statements = _timed(
        statement_dates,
        {
            "event_count": np.ones(len(s)),
            "gap_days": 42.0 + 6.0 * np.sin(s / 5.0),
            "frequency_per_year": 365.25 / (42.0 + 6.0 * np.sin(s / 5.0)),
        },
    )
    minute_dates = dates[37::44]
    m = np.arange(len(minute_dates), dtype=float)
    minutes = _timed(
        minute_dates,
        {
            "event_count": np.ones(len(m)),
            "gap_days": 45.0 + 5.0 * np.cos(m / 6.0),
            "frequency_per_year": 365.25 / (45.0 + 5.0 * np.cos(m / 6.0)),
            "decision_lag_days": 20.0 + 4.0 * np.sin(m / 8.0),
        },
    )
    auction_dates = dates[10::10]
    a = np.arange(len(auction_dates), dtype=float)
    offering = 20e9 + 4e9 * np.sin(a / 9.0) + 20e6 * a
    auctions = _timed(
        auction_dates,
        {
            "auction_count": 2.0 + (a % 3),
            "offering_amount": offering,
            "accepted_amount": offering * (1.01 + 0.01 * np.sin(a / 7.0)),
            "tendered_amount": offering * (2.4 + 0.3 * np.cos(a / 11.0)),
            "acceptance_to_offer": 1.01 + 0.01 * np.sin(a / 7.0),
            "bid_to_cover": 2.4 + 0.3 * np.cos(a / 11.0),
            "clearing_rate": 4.0 + 1.2 * np.sin(a / 17.0),
            "weighted_maturity_years": 3.0 + 2.0 * np.sin(a / 13.0),
            "bill_share": 0.45 + 0.1 * np.cos(a / 12.0),
            "note_bond_share": 0.55 - 0.1 * np.cos(a / 12.0),
            "long_term_share": 0.15 + 0.05 * np.sin(a / 15.0),
            "reopening_share": 0.25 + 0.08 * np.cos(a / 10.0),
            "maturity_hhi": 0.45 + 0.04 * np.sin(a / 14.0),
        },
    )
    debt_dates = dates[2::3]
    d = np.arange(len(debt_dates), dtype=float)
    total_debt = 5e12 * np.exp(0.0005 * d + 0.002 * np.sin(d / 23.0))
    public_share = 0.62 + 0.03 * np.sin(d / 41.0)
    debt = _timed(
        debt_dates,
        {
            "total_debt": total_debt,
            "public_debt": total_debt * public_share,
            "intragov_debt": total_debt * (1.0 - public_share),
        },
    )
    tic_dates = pd.DatetimeIndex(dates.to_series().groupby(dates.to_period("M")).first().iloc[2:])
    t = np.arange(len(tic_dates), dtype=float)
    tic = _timed(
        tic_dates,
        {
            "tic_treasury_net_purchases": 25_000.0 + 15_000.0 * np.sin(t / 7.0),
            "tic_treasury_official": 8_000.0 + 4_000.0 * np.cos(t / 9.0),
            "tic_equity_net_purchases": 10_000.0 + 12_000.0 * np.cos(t / 8.0),
            "tic_equity_official": 2_000.0 + 2_500.0 * np.sin(t / 10.0),
        },
    )
    monetary_dates = dates[3::5]
    q = np.arange(len(monetary_dates), dtype=float)
    monetary = _timed(
        monetary_dates,
        {
            "monetary_base": 500_000.0 * np.exp(0.0004 * q + 0.002 * np.sin(q / 13.0)),
            "total_reserves": 50_000.0 * np.exp(0.0006 * q + 0.004 * np.cos(q / 11.0)),
            "m2": 4_000_000.0 * np.exp(0.0003 * q),
        },
    )
    return market, {
        "decisions": decisions,
        "policy_rate": policy_rate,
        "statements": statements,
        "minutes": minutes,
        "auctions": auctions,
        "debt": debt,
        "tic": tic,
        "monetary": monetary,
    }


_VARIANTS = {
    "F221": ("decision_rate_change", "decision_direction", "decision_magnitude", "days_since_decision", "meeting_statement_balance", "conference_call"),
    "F222": ("statement_gap", "statement_gap_change", "statement_gap_zscore", "statement_frequency", "statement_irregularity", "days_since_statement"),
    "F223": ("publication_lag", "publication_lag_change", "publication_lag_zscore", "minutes_gap", "minutes_gap_zscore", "minutes_frequency", "days_since_minutes"),
    "F224": ("cadence_gap", "cadence_disagreement", "publication_recency_gap", "publication_order", "joint_irregularity"),
    "F225": ("offering_amount", "accepted_amount", "tendered_amount", "acceptance_to_offer", "offer_growth", "accepted_minus_offering"),
    "F226": ("bid_to_cover", "clearing_rate", "yield_change", "demand_change", "demand_yield_balance", "auction_count"),
    "F227": ("weighted_maturity", "bill_share", "note_bond_share", "long_term_share", "reopening_share", "maturity_hhi", "refinancing_pressure"),
    "F228": ("total_debt", "debt_growth", "debt_acceleration", "public_debt_share", "intragov_share", "composition_change", "debt_growth_zscore"),
    "F229": ("combined_net_purchases", "official_combined_flow", "private_combined_flow", "equity_flow_share", "treasury_official_share", "equity_official_share", "foreign_allocation_tilt"),
    "F230": ("policy_reserve_interaction", "reserve_issuance_balance", "foreign_absorption", "liquidity_foreign_alignment", "policy_issuance_interaction", "four_way_composite"),
}


def _parameters(lane: str) -> dict[str, object]:
    return {
        "statistic": _VARIANTS[lane][0],
        "window": 13,
        "change_lag": 1,
        "normalization": "raw",
        "direction": "continuation",
    }


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(221, 231)])
def test_f221_f230_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_policy_treasury_lane(lane, market, panels, _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(221, 231)])
def test_f221_f230_do_not_change_when_future_train_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[2200, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {name: panel.loc[panel["date"].le(cutoff)].copy() for name, panel in panels.items()}

    before = api.evaluate_policy_treasury_lane(lane, before_market, before_panels, _parameters(lane))
    after = api.evaluate_policy_treasury_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(("lane", "variants"), list(_VARIANTS.items()))
def test_f221_f230_frozen_statistics_are_executable(lane: str, variants: tuple[str, ...]) -> None:
    market, panels = _inputs()
    for statistic in variants:
        result = _api().evaluate_policy_treasury_lane(
            lane, market, panels, {**_parameters(lane), "statistic": statistic}
        )
        assert result["value"].notna().any(), f"{lane}:{statistic}"


@pytest.mark.parametrize(
    ("lane", "statistic"),
    (("F222", "days_since_statement"), ("F223", "days_since_minutes")),
)
def test_policy_treasury_batch_uses_full_coverage_publication_recency(
    lane: str, statistic: str
) -> None:
    api = _api()
    market, panels = _inputs()

    batch = api.evaluate_policy_treasury_family_batch(market, panels)
    expected = api.evaluate_policy_treasury_lane(
        lane,
        market,
        panels,
        {
            "statistic": statistic,
            "window": 13,
            "change_lag": 1,
            "normalization": "raw",
            "direction": "continuation",
        },
    )

    pd.testing.assert_frame_equal(batch[lane], expected)


def test_policy_treasury_engine_fails_closed() -> None:
    api = _api()
    market, panels = _inputs()
    with pytest.raises(api.PolicyTreasuryFeatureEngineError, match="UNKNOWN_LANE"):
        api.evaluate_policy_treasury_lane("F231", market, panels, {})
    with pytest.raises(api.PolicyTreasuryFeatureEngineError, match="UNKNOWN_PARAMETER"):
        api.evaluate_policy_treasury_lane(
            "F221", market, panels, {**_parameters("F221"), "statistic": "tone"}
        )
    future = market.copy()
    future.loc[len(future)] = future.iloc[-1]
    future.loc[len(future) - 1, ["date", "observed_at", "available_at"]] = pd.Timestamp("2011-01-03")
    with pytest.raises(api.PolicyTreasuryFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_policy_treasury_lane("F221", future, panels, _parameters("F221"))

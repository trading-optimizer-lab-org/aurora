from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.openap_93.historical_proxy_validation import (
    FIVE_PROXY_SIGNALS,
    _build_announcement_return,
    _build_earnings_streak,
    _rank_buckets,
    compare_to_reference,
)


def test_rank_buckets_are_cross_sectional_and_bounded() -> None:
    buckets = _rank_buckets(pd.Series([10.0, 20.0, 30.0, 40.0, 50.0]))
    assert buckets.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_missing_crosswalk_fails_closed_for_all_five() -> None:
    reference = pd.DataFrame(
        {
            "permno": [1],
            "yyyymm": [202001],
            "formation_month": [pd.Timestamp("2020-01-01")],
            **{signal: [1.0] for signal in FIVE_PROXY_SIGNALS},
        }
    )
    monthly, summary = compare_to_reference(reference, pd.DataFrame(), None)
    assert monthly.empty
    assert set(summary["validation_status"]) == {"blocked_missing_permno_crosswalk"}
    assert summary["paired_observations"].sum() == 0


def test_paired_reference_and_proxy_calculate_similarity() -> None:
    months = pd.date_range("2020-01-01", periods=2, freq="MS")
    reference = pd.DataFrame(
        {
            "permno": [1, 2, 3, 4, 1, 2, 3, 4],
            "yyyymm": [202001] * 4 + [202002] * 4,
            "formation_month": list(months[:1]) * 4 + list(months[1:]) * 4,
            **{signal: [1.0, 2.0, 3.0, 4.0] * 2 for signal in FIVE_PROXY_SIGNALS},
        }
    )
    crosswalk = pd.DataFrame(
        {
            "permno": [1, 2, 3, 4],
            "symbol": ["A", "B", "C", "D"],
            "effective_start": [pd.NaT] * 4,
            "effective_end": [pd.NaT] * 4,
        }
    )
    proxy = pd.DataFrame(
        [
            {
                "signal": signal,
                "symbol": symbol,
                "formation_month": month,
                "proxy_value": float(index + 1),
            }
            for signal in FIVE_PROXY_SIGNALS
            for month in months
            for index, symbol in enumerate(["A", "B", "C", "D"])
        ]
    )
    monthly, summary = compare_to_reference(reference, proxy, crosswalk, min_pairs=4)
    assert not monthly.empty
    assert set(summary["validation_status"]) == {"ok"}
    assert (summary["mean_monthly_spearman"] == 1.0).all()
    assert (summary["mean_quintile_agreement"] == 1.0).all()


def test_earnings_streak_uses_conservative_availability_lag() -> None:
    monthly = pd.DataFrame({
        "symbol": ["AAA", "AAA"],
        "completed_month": pd.to_datetime(["2016-09-30", "2016-10-31"]),
        "formation_month": pd.to_datetime(["2016-10-01", "2016-11-01"]),
    })
    history = pd.DataFrame({
        "act_symbol": ["AAA", "AAA"],
        "period_end_date": pd.to_datetime(["2016-03-31", "2016-06-30"]),
        "reported": [1.0, 1.2],
        "estimate": [0.8, 1.0],
    })
    result = _build_earnings_streak(monthly, history)
    assert result.loc[result["completed_month"].eq(pd.Timestamp("2016-09-30")), "proxy_value"].notna().all()
    assert result["reconstruction_status"].eq("reconstructed").all()
    assert result["caveat"].str.contains("90-day").all()


def test_announcement_return_uses_official_minus_two_plus_one_window() -> None:
    dates = pd.date_range("2020-01-06", periods=6, freq="B")
    prices = pd.DataFrame({
        "symbol": ["AAA"] * len(dates),
        "date": dates,
        "adj_close": [99.0, 100.0, 101.0, 103.0, 106.0, 110.0],
    })
    facts = pd.DataFrame({
        "cik": [1],
        "tag": ["NetIncomeLoss"],
        "form": ["10-Q"],
        "filed": [dates[3]],
    })
    monthly = pd.DataFrame({
        "symbol": ["AAA"],
        "completed_month": [pd.Timestamp("2020-01-31")],
        "formation_month": [pd.Timestamp("2020-02-01")],
    })
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})
    result = _build_announcement_return(monthly, facts, prices, None, master)
    # The official window is dates[1:5], not dates[2:6].
    expected = (100 / 99 - 1) + (101 / 100 - 1) + (103 / 101 - 1) + (106 / 103 - 1)
    assert result.iloc[0]["proxy_value"] == pytest.approx(expected)
    assert result.iloc[0]["proxy_formula_id"].endswith("window_exact")

from __future__ import annotations

import pandas as pd

from aurora.research.openap_93.historical_proxy_validation import (
    FIVE_PROXY_SIGNALS,
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


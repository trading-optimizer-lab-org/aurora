from __future__ import annotations

import pandas as pd

from aurora.research.openap_93.historical_proxy_validation import (
    compare_proxy_pairs,
)


def test_pairwise_similarity_measures_same_cross_sectional_ranking() -> None:
    symbols = [f"S{i:02d}" for i in range(30)]
    months = pd.date_range("2020-01-01", periods=2, freq="MS")
    rows = []
    for month in months:
        for index, symbol in enumerate(symbols):
            rows.extend([
                {"symbol": symbol, "formation_month": month, "signal": "DivSeason", "proxy_value": float(index)},
                {"symbol": symbol, "formation_month": month, "signal": "AnnouncementReturn", "proxy_value": float(index)},
            ])
    monthly, summary = compare_proxy_pairs(pd.DataFrame(rows), min_pairs=30)
    selected = summary.loc[
        summary["left_signal"].eq("DivSeason")
        & summary["right_signal"].eq("AnnouncementReturn")
    ].iloc[0]
    assert selected["validation_status"] == "ok"
    assert selected["mean_monthly_spearman"] == 1.0
    assert selected["mean_quintile_agreement"] == 1.0
    assert selected["mean_sign_consistency"] == 1.0
    assert len(monthly) == 2


def test_pairwise_similarity_marks_earnings_streak_unavailable() -> None:
    panel = pd.DataFrame({
        "symbol": ["A"],
        "formation_month": [pd.Timestamp("2020-01-01")],
        "signal": ["DivSeason"],
        "proxy_value": [1.0],
    })
    _, summary = compare_proxy_pairs(panel, min_pairs=1)
    row = summary.loc[
        summary["left_signal"].eq("EarningsStreak")
        & summary["right_signal"].eq("IndRetBig")
    ].iloc[0]
    assert row["validation_status"] == "unavailable_missing_proxy_column"

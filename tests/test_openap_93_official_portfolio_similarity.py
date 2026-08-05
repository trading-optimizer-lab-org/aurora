from __future__ import annotations

import pandas as pd
import pytest

from research.openap_93.official_portfolio_similarity import (
    build_official_spreads,
    build_proxy_spreads,
    compare_official_and_proxy,
    normalise_official_deciles,
)


def test_official_deciles_normalise_and_form_spread() -> None:
    raw = pd.DataFrame({
        "signalname": ["DivSeason"] * 4,
        "date": [202001] * 4,
        "port": [1, 2, 9, 10],
        "ret": [0.01, 0.02, 0.08, 0.10],
    })
    official = normalise_official_deciles(raw)
    spreads = build_official_spreads(official)
    assert len(spreads) == 1
    assert spreads.iloc[0]["official_spread_return"] == pytest.approx(0.09)


def test_official_low_high_labels_do_not_collapse() -> None:
    raw = pd.DataFrame({
        "signalname": ["DivSeason", "DivSeason"],
        "date": ["2020-01-31", "2020-01-31"],
        "port": ["Lo10", "Hi10"],
        "ret": [0.01, 0.09],
    })
    official = normalise_official_deciles(raw)
    spreads = build_official_spreads(official)
    assert set(official["decile"]) == {1.0, 10.0}
    assert spreads.iloc[0]["official_spread_return"] == pytest.approx(0.08)


def test_proxy_deciles_use_next_formation_month_return() -> None:
    proxy = pd.DataFrame({
        "symbol": ["A", "B", "C", "D"],
        "formation_month": pd.to_datetime(["2020-02-01"] * 4),
        "signal": ["DivSeason"] * 4,
        "proxy_value": [1.0, 2.0, 9.0, 10.0],
    })
    monthly = pd.DataFrame({
        "symbol": ["A", "B", "C", "D"],
        "completed_month": pd.to_datetime(["2020-02-01"] * 4),
        "month_return": [0.01, 0.02, 0.08, 0.10],
    })
    spreads = build_proxy_spreads(proxy, monthly)
    assert len(spreads) == 1
    assert spreads.iloc[0]["proxy_spread_return"] == pytest.approx(0.09)


def test_similarity_reports_high_match_without_claiming_identity() -> None:
    official = pd.DataFrame({
        "signal": ["DivSeason"] * 3,
        "formation_month": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"]),
        "official_spread_return": [0.01, -0.02, 0.03],
    })
    proxy = pd.DataFrame({
        "signal": ["DivSeason"] * 3,
        "formation_month": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"]),
        "proxy_spread_return": [0.01, -0.02, 0.03],
    })
    _, summary = compare_official_and_proxy(official, proxy)
    row = summary.query("signal == 'DivSeason' and period == 'all'").iloc[0]
    assert row["pearson_same_direction"] == 1.0
    assert row["orientation"] == "same"

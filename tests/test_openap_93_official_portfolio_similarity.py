from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from research.openap_93.historical_proxy_validation import FIVE_PROXY_SIGNALS
from research.openap_93.official_portfolio_similarity import (
    build_official_spreads,
    build_official_long_short_spreads,
    build_proxy_spreads,
    compare_official_and_proxy,
    normalise_official_deciles,
    normalise_official_long_short,
    download_official_long_short,
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


def test_official_long_short_wide_normalises_requested_signals() -> None:
    raw = pd.DataFrame({
        "yyyymm": [202001, 202002],
        "DivSeason": [0.10, -0.02],
        "AnnouncementReturn": [0.04, 0.03],
        "Unrelated": [0.99, 0.99],
    })
    official = normalise_official_long_short(raw)
    assert set(official["signal"]) == {"DivSeason", "AnnouncementReturn"}
    spreads = build_official_long_short_spreads(official)
    assert spreads["official_spread_return"].tolist() == pytest.approx([0.10, -0.02, 0.04, 0.03])


def test_official_long_short_can_load_staged_csv(tmp_path: Path) -> None:
    source = tmp_path / "PredictorLSretWide.csv"
    pd.DataFrame(
        {
            "yyyymm": [202001],
            "DivSeason": [0.10],
            "AnnouncementReturn": [0.04],
            "EarningsStreak": [0.03],
            "IndRetBig": [0.02],
            "DelNetFin": [-0.01],
        }
    ).to_csv(source, index=False)
    result = download_official_long_short(output_dir=tmp_path / "out", archive_path=source)
    assert set(result["signal"]) == set(FIVE_PROXY_SIGNALS)


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


def test_proxy_deciles_can_use_realized_returns_kept_in_panel() -> None:
    proxy = pd.DataFrame({
        "symbol": ["A", "B", "C", "D"],
        "formation_month": pd.to_datetime(["2020-02-01"] * 4),
        "signal": ["DivSeason"] * 4,
        "proxy_value": [1.0, 2.0, 9.0, 10.0],
        "realized_month_return": [0.01, 0.02, 0.08, 0.10],
    })
    spreads = build_proxy_spreads(proxy, pd.DataFrame())
    assert len(spreads) == 1
    assert spreads.iloc[0]["proxy_spread_return"] == pytest.approx(0.09)


def test_continuous_proxy_uses_openap_top_and_bottom_quintiles() -> None:
    symbols = list("ABCDEFGHIJ")
    proxy = pd.DataFrame(
        {
            "symbol": symbols,
            "completed_month": pd.to_datetime(["2020-01-31"] * 10),
            "formation_month": pd.to_datetime(["2020-02-01"] * 10),
            "signal": ["AnnouncementReturn"] * 10,
            "proxy_value": list(range(1, 11)),
            "realized_month_return": [0.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8, 1.0],
        }
    )

    spreads = build_proxy_spreads(proxy, pd.DataFrame())

    assert spreads.iloc[0]["proxy_spread_return"] == pytest.approx(0.8)
    assert spreads.iloc[0]["proxy_low_count"] == 2
    assert spreads.iloc[0]["proxy_high_count"] == 2


def test_divseason_uses_all_zero_and_one_observations() -> None:
    symbols = list("ABCDEFGHIJ")
    proxy = pd.DataFrame(
        {
            "symbol": symbols,
            "completed_month": pd.to_datetime(["2020-01-31"] * 10),
            "formation_month": pd.to_datetime(["2020-02-01"] * 10),
            "signal": ["DivSeason"] * 10,
            "proxy_value": [0.0] * 5 + [1.0] * 5,
            "realized_month_return": [0.0] * 5 + [0.1, 0.2, 0.3, 0.4, 0.5],
        }
    )

    spreads = build_proxy_spreads(proxy, pd.DataFrame())

    assert spreads.iloc[0]["proxy_spread_return"] == pytest.approx(0.3)
    assert spreads.iloc[0]["proxy_low_count"] == 5
    assert spreads.iloc[0]["proxy_high_count"] == 5


def test_delnetfin_keeps_june_portfolios_for_twelve_months() -> None:
    june_signal = {"A": 1.0, "B": 2.0, "C": 9.0, "D": 10.0}
    july_signal = {"A": 10.0, "B": 9.0, "C": 2.0, "D": 1.0}
    rows = []
    for symbol in "ABCD":
        rows.extend(
            [
                {
                    "symbol": symbol,
                    "completed_month": pd.Timestamp("2020-06-30"),
                    "formation_month": pd.Timestamp("2020-07-01"),
                    "signal": "DelNetFin",
                    "proxy_value": june_signal[symbol],
                    "realized_month_return": 0.1 if symbol == "D" else 0.0,
                },
                {
                    "symbol": symbol,
                    "completed_month": pd.Timestamp("2020-07-31"),
                    "formation_month": pd.Timestamp("2020-08-01"),
                    "signal": "DelNetFin",
                    "proxy_value": july_signal[symbol],
                    "realized_month_return": 0.1 if symbol == "D" else 0.0,
                },
            ]
        )

    spreads = build_proxy_spreads(pd.DataFrame(rows), pd.DataFrame())

    assert spreads["formation_month"].tolist() == [
        pd.Timestamp("2020-07-01"),
        pd.Timestamp("2020-08-01"),
    ]
    assert spreads["proxy_spread_return"].tolist() == pytest.approx([0.1, 0.1])


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


def test_reference_backed_proxy_is_explicitly_not_independent(tmp_path: Path) -> None:
    source = tmp_path / "PredictorLSretWide.csv"
    pd.DataFrame(
        {
            "yyyymm": [202001],
            "DivSeason": [0.10],
            "AnnouncementReturn": [0.04],
            "EarningsStreak": [0.03],
            "IndRetBig": [0.02],
            "DelNetFin": [-0.01],
        }
    ).to_csv(source, index=False)
    result = download_official_long_short(output_dir=tmp_path / "out", archive_path=source)
    mirror = result[["signal", "formation_month", "official_return"]].rename(
        columns={"official_return": "reference_return"}
    )
    assert mirror["reference_return"].equals(result["official_return"])

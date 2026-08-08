from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from aurora.research.openap_proxy44_historical import (
    HISTORICALLY_RECONSTRUCTED_PROXY_SIGNALS,
    build_price_event_proxy_panel,
    build_reconstruction_coverage,
)
from aurora.research.openap_proxy_real_correlation import CANONICAL_PROXY_SIGNALS


def _daily_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2016-01-01", "2021-03-31")
    rows: list[dict[str, object]] = []
    for symbol_index in range(15):
        symbol = f"S{symbol_index:02d}"
        offset = float(symbol_index * 5)
        for index, date in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "adj_close": (
                        100.0
                        + offset
                        + index * 0.05 * (1.0 + symbol_index / 20.0)
                        + 2.0 * np.sin(index / (10.0 + symbol_index))
                    ),
                    "volume": 1_000.0 + index * (1.0 + symbol_index / 10.0),
                    "dividends": 1.0 if date.month in {3, 6, 9, 12} and date.is_month_end else 0.0,
                }
            )
    return pd.DataFrame(rows)


def test_price_event_panel_is_causal_and_uses_following_month_return() -> None:
    panel = build_price_event_proxy_panel(_daily_prices())
    row = panel.loc[
        panel["signal"].eq("VolumeTrend")
        & panel["symbol"].eq("S00")
        & panel["formation_month"].eq(pd.Timestamp("2020-02-01"))
    ].iloc[0]
    daily = _daily_prices().query("symbol == 'S00'").set_index("date")["adj_close"]
    month_end = daily.resample("ME").last()
    expected = month_end.loc["2020-02-29"] / month_end.loc["2020-01-31"] - 1.0
    assert row["signal_cutoff"] == pd.Timestamp("2020-01-31")
    assert row["realized_month_return"] == expected
    assert row["available_at"] <= row["signal_cutoff"]


def test_market_reconstruction_emits_all_supported_signal_names() -> None:
    panel = build_price_event_proxy_panel(_daily_prices())
    assert set(HISTORICALLY_RECONSTRUCTED_PROXY_SIGNALS).issubset(set(panel["signal"]))
    assert np.isfinite(panel.loc[panel["signal"].eq("TrendFactor"), "proxy_value"]).any()


def test_volume_signals_use_official_monthly_windows() -> None:
    panel = build_price_event_proxy_panel(_daily_prices())
    symbol = panel.loc[panel["symbol"].eq("S00")]
    volsd = symbol.loc[symbol["signal"].eq("VolSD"), "proxy_value"]
    trend = symbol.loc[symbol["signal"].eq("VolumeTrend"), "proxy_value"]
    assert volsd.notna().sum() > 0
    assert trend.notna().sum() > 0


def test_current_score_proxy_threshold_matches_strict_project_policy() -> None:
    text = Path("config/openap_yfinance_sec_current.yaml").read_text(encoding="utf-8")
    assert "correlation_threshold: 0.95" in text


def test_coverage_has_exactly_one_row_for_every_canonical_proxy() -> None:
    panel = build_price_event_proxy_panel(_daily_prices())
    coverage = build_reconstruction_coverage(panel)
    assert coverage["signal"].tolist() == list(CANONICAL_PROXY_SIGNALS)
    assert len(coverage) == 44
    assert coverage["signal"].is_unique
    assert coverage.loc[coverage["signal"].eq("TrendFactor"), "status"].iloc[0] == "reconstructed"
    assert coverage.loc[coverage["signal"].eq("OptionVolume1"), "status"].iloc[0] == "not_reconstructible"


def test_full_workflow_runs_historical_audit_only_in_github() -> None:
    workflow = Path(
        ".github/workflows/openap-proxy44-historical-correlation.yml"
    ).read_text(encoding="utf-8")
    assert "GITHUB_ACTIONS: \"true\"" in workflow
    assert "run_openap_proxy44_historical.py" in workflow
    assert "openap_proxy44_correlation.csv" in workflow
    assert "canonical_proxy_count'] == 44" in workflow
    assert "download_official_long_short" in workflow
    assert "openap-five-proxy-historical-validation-results" not in workflow

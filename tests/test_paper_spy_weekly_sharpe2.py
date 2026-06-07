from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_paper_spy_weekly_sharpe2 import (
    LOCKED_START,
    PAPER_SOURCES,
    build_paper_feature_frame,
    paper_sources_for_features,
)


def test_paper_spy_features_are_lagged_and_paper_traced() -> None:
    idx = pd.date_range("1995-01-06", periods=220, freq="W-FRI")
    spy = pd.Series(100.0 + np.cumsum(np.sin(np.arange(len(idx)) / 7.0) + 0.2), index=idx)
    returns = pd.DataFrame({"SPY": spy.pct_change(fill_method=None)}, index=idx).dropna()
    prices = pd.DataFrame(
        {
            "SPY": spy,
            "cboe_volatility_vix": 20.0 + np.sin(np.arange(len(idx)) / 5.0),
            "cboe_options_derived_skew": 120.0 + np.cos(np.arange(len(idx)) / 6.0),
            "cboe_total_put_call_ratio": 0.9 + np.sin(np.arange(len(idx)) / 8.0) * 0.1,
            "cboe_benchmark_pput": 100.0 + np.cumsum(np.cos(np.arange(len(idx)) / 9.0)),
        },
        index=idx,
    )
    features, feature_papers = build_paper_feature_frame(prices, returns)
    assert not features.empty
    assert features.index.max() < LOCKED_START
    assert feature_papers
    assert all(keys for keys in feature_papers.values())
    assert any("put_call_sentiment" in keys for keys in feature_papers.values())
    assert any("skew_tail" in keys for keys in feature_papers.values())
    assert features.index.min() > returns.index.min()


def test_paper_sources_for_features_preserves_traceability() -> None:
    trace = {
        "vix_cboe_z_26w": ("vix_fear", "btz_vrp"),
        "spy_ma_gap_40w": ("faber_ma", "glabadanidis_ma"),
    }
    keys = paper_sources_for_features(["vix_cboe_z_26w", "spy_ma_gap_40w"], trace)
    assert keys == ("vix_fear", "btz_vrp", "faber_ma", "glabadanidis_ma")
    assert all(key in PAPER_SOURCES for key in keys)


def test_paper_spy_weekly_sharpe2_workflow_shape() -> None:
    path = Path(".github/workflows/paper-spy-weekly-sharpe2-360jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "Paper SPY Weekly Sharpe2 360 Jobs"
    assert "workflow_dispatch" in data[True]
    text = path.read_text(encoding="utf-8")
    assert "range(360)" in text
    assert "max-parallel: 180" in text
    assert "paper-spy-weekly-sharpe2-360jobs-results" in text
    assert "run_paper_spy_weekly_sharpe2.py" in text

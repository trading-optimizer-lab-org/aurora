"""Tests for extended tearsheet (generate_full_tearsheet + helpers).

Run: pytest aurora/tests/test_tearsheet_v2.py -v
"""
from __future__ import annotations
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from aurora.core.metrics import compute_metrics
from aurora.core.engine import BacktestResult
from aurora.reporting.tearsheet import (
    generate_tearsheet,
    generate_full_tearsheet,
    _extract_round_trips,
    _top_trades_table,
    _monthly_returns_table,
    _distribution_chart,
    _rolling_sharpe_multi,
    _rolling_mdd,
    _yoy_bar_chart,
    _risk_return_scatter,
    _top_drawdowns_table,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(n: int = 600, seed: int = 7,
                 with_trades: bool = True) -> BacktestResult:
    """Synthetic backtest with optional sign-changing weights to create trades."""
    rng = np.random.default_rng(seed)
    rets = np.zeros(n)
    rets[1:] = rng.normal(0.0006, 0.012, n - 1)
    nav = np.cumprod(1.0 + rets)
    nav[0] = 1.0
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    metrics = compute_metrics(rets[1:], ppy=252)

    if with_trades:
        # build weights with multiple long/short/flat regimes
        weights = np.zeros(n)
        block = max(20, n // 10)
        sign = 1
        for start in range(0, n, block):
            end = min(start + block, n)
            weights[start:end] = sign
            sign *= -1 if rng.random() > 0.3 else 1
            if rng.random() > 0.7:
                weights[start:end] = 0.0
    else:
        weights = np.ones(n)

    return BacktestResult(metrics=metrics, nav=nav, rets=rets,
                          weights=weights, timestamps=idx.values)


# ---------------------------------------------------------------------------
# Tests for new public function: generate_full_tearsheet
# ---------------------------------------------------------------------------


def test_full_tearsheet_runs():
    """Full tearsheet emits HTML containing all v2 section markers."""
    result = _make_result()
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "full.html")
        path = generate_full_tearsheet(result, out, title="Full Test")
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 8000

        with open(path, "r", encoding="utf-8") as f:
            html = f.read()

        # title + provenance
        assert "Full Test" in html

        # all v2 sections
        assert "Round-Trip Trades" in html
        assert "Monthly Returns Table" in html
        assert "Returns Distribution" in html
        assert "Rolling Sharpe (21" in html  # multi-window header
        assert "Rolling Max Drawdown" in html
        assert "Year-over-Year Returns" in html
        assert "Worst Drawdown Periods" in html

        # base64 PNG embeddings
        assert html.count("data:image/png;base64,") >= 7


def test_full_tearsheet_with_benchmark():
    """Benchmark comparison adds risk-return scatter section."""
    result = _make_result(seed=1)
    bench = _make_result(seed=2)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "ts.html")
        path = generate_full_tearsheet(result, out, benchmark_result=bench)
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        # risk-return section only present when benchmark provided
        assert "Risk vs Return" in html


def test_full_tearsheet_without_benchmark_no_scatter():
    """Without benchmark: scatter section is omitted."""
    result = _make_result(seed=3)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "no_bench.html")
        generate_full_tearsheet(result, out)
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        assert "Risk vs Return" not in html


# ---------------------------------------------------------------------------
# Tests for individual helpers
# ---------------------------------------------------------------------------


def test_monthly_table_shape():
    """Monthly returns table: row totals (YTD) included, year x 13 cols."""
    n = 24 * 21  # ~24 months of business days
    rng = np.random.default_rng(0)
    rets = np.zeros(n)
    rets[1:] = rng.normal(0.001, 0.01, n - 1)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    table = _monthly_returns_table(rets, idx.values)
    assert not table.empty
    # 12 month columns + YTD
    assert "YTD" in table.columns
    assert len(table.columns) == 13
    # months are short names, not ints
    expected = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "YTD"}
    assert set(table.columns) == expected
    # YTD finite where any month is finite
    for year, row in table.iterrows():
        if row.drop("YTD").notna().any():
            assert not np.isnan(row["YTD"])


def test_top_drawdowns_count():
    """Top drawdowns table caps at n requested."""
    # Construct returns with several distinct drawdown episodes.
    n = 400
    rng = np.random.default_rng(123)
    rets = rng.normal(0.0, 0.01, n)
    # inject a few large drops at known indices
    for i in (50, 120, 200, 280, 350):
        rets[i] = -0.08
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rows = _top_drawdowns_table(rets, idx.values, n=5)
    assert isinstance(rows, list)
    assert len(rows) <= 5
    # 5 fields now: (start, end, depth_pct, recovery_days, unrecovered)
    for r in rows:
        assert len(r) == 5
        # depth is negative
        assert r[2] <= 0
        # unrecovered flag is bool
        assert isinstance(r[4], bool)


def test_top_drawdowns_count_smaller_n():
    """n=2 returns at most 2 rows."""
    n = 200
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0, 0.01, n)
    rets[40] = -0.07
    rets[120] = -0.06
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    rows = _top_drawdowns_table(rets, idx.values, n=2)
    assert len(rows) <= 2


def test_round_trips_extracted_from_weights():
    """Sign-changing weights yield round-trip trades with valid fields."""
    n = 100
    weights = np.zeros(n)
    weights[10:30] = 1.0   # long block
    weights[40:60] = -1.0  # short block
    weights[70:90] = 1.0   # long block
    prices = np.linspace(100.0, 150.0, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = _extract_round_trips(weights, prices, idx.values)
    assert not df.empty
    # 3 distinct trades
    assert len(df) == 3
    # required columns
    for col in ("entry_date", "exit_date", "side", "bars", "pnl_pct"):
        assert col in df.columns
    # sides include both long and short
    sides = set(df["side"].tolist())
    assert sides == {"long", "short"}
    # bars are positive ints
    assert (df["bars"] > 0).all()
    # all PnL values finite
    assert df["pnl_pct"].notna().all()


def test_round_trips_zero_weights_returns_empty():
    """All-zero weights produce no trades."""
    n = 50
    weights = np.zeros(n)
    prices = np.linspace(100.0, 110.0, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = _extract_round_trips(weights, prices, idx.values)
    assert df.empty


def test_top_trades_table_returns_pair():
    """Top trades helper returns (best, worst) DataFrames."""
    result = _make_result(n=300, seed=11)
    best, worst = _top_trades_table(result.weights, result.nav,
                                     result.timestamps, n=5)
    if not best.empty:
        # best should be sorted descending by pnl
        assert best["pnl_pct"].is_monotonic_decreasing
    if not worst.empty:
        # worst should be sorted ascending (worst first)
        assert worst["pnl_pct"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# Backward compatibility test
# ---------------------------------------------------------------------------


def test_backward_compat_generate_tearsheet_unchanged():
    """Original generate_tearsheet API still works exactly as before."""
    result = _make_result(n=400, seed=42)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "legacy.html")
        path = generate_tearsheet(result, out, title="Legacy Test")
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        # all original sections present
        assert "Legacy Test" in html
        assert "Equity Curve" in html
        assert "Drawdown" in html
        assert "Monthly Returns Heatmap" in html
        assert "Rolling Sharpe" in html
        assert "Top 5 Drawdown" in html
        assert "Underwater Plot" in html
        # v2-only sections must NOT appear in basic tearsheet
        assert "Round-Trip Trades" not in html
        assert "Year-over-Year Returns" not in html
        assert "Rolling Max Drawdown" not in html


# ---------------------------------------------------------------------------
# Smoke tests for chart helpers (return non-empty base64)
# ---------------------------------------------------------------------------


def test_distribution_chart_non_empty():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.001, 0.01, 250)
    b64 = _distribution_chart(rets)
    assert isinstance(b64, str) and len(b64) > 200


def test_distribution_chart_with_benchmark():
    rng = np.random.default_rng(1)
    rets = rng.normal(0.001, 0.01, 250)
    bench = rng.normal(0.0008, 0.012, 250)
    b64 = _distribution_chart(rets, bench)
    assert isinstance(b64, str) and len(b64) > 200


def test_rolling_sharpe_multi_chart():
    rng = np.random.default_rng(2)
    rets = rng.normal(0.001, 0.01, 400)
    idx = pd.date_range("2020-01-01", periods=400, freq="B")
    b64 = _rolling_sharpe_multi(rets, idx, windows=(21, 63, 252))
    assert isinstance(b64, str) and len(b64) > 200


def test_rolling_mdd_chart():
    rng = np.random.default_rng(3)
    rets = rng.normal(0.0, 0.012, 300)
    idx = pd.date_range("2021-01-01", periods=300, freq="B")
    b64 = _rolling_mdd(rets, idx, window=120)
    assert isinstance(b64, str) and len(b64) > 200


def test_yoy_bar_chart_multi_year():
    n = 3 * 252
    rng = np.random.default_rng(4)
    rets = rng.normal(0.0006, 0.011, n)
    idx = pd.date_range("2018-01-02", periods=n, freq="B")
    b64 = _yoy_bar_chart(rets, idx.values)
    assert isinstance(b64, str) and len(b64) > 200


def test_risk_return_scatter_runs():
    rng = np.random.default_rng(5)
    rets = rng.normal(0.001, 0.01, 250)
    bench = rng.normal(0.0007, 0.012, 250)
    b64 = _risk_return_scatter(rets, bench)
    assert isinstance(b64, str) and len(b64) > 200


def test_risk_return_scatter_no_benchmark():
    rng = np.random.default_rng(6)
    rets = rng.normal(0.001, 0.01, 250)
    b64 = _risk_return_scatter(rets, None)
    assert isinstance(b64, str) and len(b64) > 200


# ---------------------------------------------------------------------------
# Flag toggles
# ---------------------------------------------------------------------------


def test_full_tearsheet_round_trips_disabled():
    """include_round_trips=False yields placeholder text."""
    result = _make_result(seed=8)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "no_rt.html")
        generate_full_tearsheet(result, out, include_round_trips=False)
        with open(out, "r", encoding="utf-8") as f:
            html = f.read()
        assert "Round-trip extraction disabled" in html


def test_full_tearsheet_short_series():
    """Short backtest still produces a valid tearsheet."""
    result = _make_result(n=80, seed=9)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "short.html")
        path = generate_full_tearsheet(result, out)
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 5000

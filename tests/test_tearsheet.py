"""Tests for aurora.reporting.tearsheet.

Run: pytest aurora/tests/test_tearsheet.py -v
"""
from __future__ import annotations
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from aurora.core.metrics import compute_metrics, Metrics
from aurora.core.engine import BacktestResult
from aurora.reporting.tearsheet import (
    generate_tearsheet,
    _drawdown_periods,
    _monthly_returns_matrix,
    _rolling_sharpe,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_result(n: int = 600, seed: int = 7) -> BacktestResult:
    rng = np.random.default_rng(seed)
    rets = np.zeros(n)
    rets[1:] = rng.normal(0.0006, 0.012, n - 1)
    nav = np.cumprod(1.0 + rets)
    nav[0] = 1.0
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    metrics = compute_metrics(rets[1:], ppy=252)
    weights = np.ones(n)
    return BacktestResult(metrics=metrics, nav=nav, rets=rets,
                          weights=weights, timestamps=idx.values)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_html_runs():
    """Tearsheet HTML must be created and contain expected sections."""
    result = _make_result()
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "tearsheet.html")
        path = generate_tearsheet(result, out, title="Test Sheet")
        assert os.path.isfile(path)
        assert os.path.getsize(path) > 5000  # non-trivial size

        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        # core section markers
        assert "Test Sheet" in html
        assert "Equity Curve" in html
        assert "Drawdown" in html


def test_tearsheet_html_escapes_user_input():
    """User-controlled strings (e.g. ``title``) must be HTML-escaped so a
    malicious or accidental ``<script>`` payload cannot execute when the
    tearsheet is opened in a browser.
    """
    result = _make_result()
    payload = "<script>alert(1)</script>"
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "tearsheet.html")
        path = generate_tearsheet(result, out, title=payload)
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        # Raw payload must not appear; the escaped form must.
        assert payload not in html, (
            "Unescaped user input rendered into tearsheet — XSS risk"
        )
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "Monthly Returns Heatmap" in html
        assert "Rolling Sharpe" in html
        assert "Top 5 Drawdown" in html
        # base64 PNG embeddings
        assert "data:image/png;base64," in html


def test_generate_html_with_benchmark():
    """Benchmark overlay path should not crash."""
    result = _make_result(seed=1)
    bench = _make_result(seed=2)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "ts.html")
        path = generate_tearsheet(result, out, benchmark_result=bench)
        assert os.path.isfile(path)


def test_drawdown_periods_known():
    """Known nav curve: peak at 1.2, trough at 0.9, recovers; second mini-dd.

    Recovered drawdowns get a finite recovery_days and unrecovered=False.
    """
    nav = np.array([1.0, 1.1, 1.2, 1.0, 0.9, 1.0, 1.2, 1.3, 1.25, 1.3])
    ts = pd.date_range("2024-01-01", periods=len(nav), freq="D")
    periods = _drawdown_periods(nav, ts.values)
    assert len(periods) >= 1
    # Worst (deepest) drawdown should be from peak 1.2 -> trough 0.9 = -25%
    worst = periods[0]
    # 5-tuple: (start, end, depth_pct, recovery_days, unrecovered)
    assert len(worst) == 5
    start, end, depth_pct, recovery_days, unrecovered = worst
    assert depth_pct < -20.0  # at least 20% drawdown
    assert depth_pct > -30.0  # but not deeper than 30
    # This drawdown does recover -> finite recovery_days, unrecovered False
    assert unrecovered is False
    assert isinstance(recovery_days, (int, float))
    assert not (isinstance(recovery_days, float) and np.isnan(recovery_days))
    assert recovery_days >= 0


def test_drawdown_no_drawdown():
    """All-monotonic-up nav: zero drawdown periods."""
    nav = np.array([1.0, 1.01, 1.02, 1.03, 1.04, 1.05])
    ts = pd.date_range("2024-01-01", periods=len(nav), freq="D")
    periods = _drawdown_periods(nav, ts.values)
    assert periods == []


def test_drawdown_unrecovered():
    """NAV ends below peak: end_date == last bar, unrecovered flag set,
    recovery_days is a finite sentinel (bars-since-trough), NOT NaN."""
    nav = np.array([1.0, 1.2, 1.0, 0.9, 0.85, 0.8])
    ts = pd.date_range("2024-01-01", periods=len(nav), freq="D")
    periods = _drawdown_periods(nav, ts.values)
    assert len(periods) >= 1
    worst = periods[0]
    # 5-tuple now: (start, end, depth_pct, recovery_days, unrecovered)
    assert len(worst) == 5
    rec_days = worst[3]
    unrecovered = worst[4]
    assert unrecovered is True, "expected unrecovered flag True"
    # recovery_days must be a finite sentinel, not NaN.
    assert not (isinstance(rec_days, float) and np.isnan(rec_days)), (
        "recovery_days must NOT be NaN for unrecovered drawdowns"
    )
    assert rec_days >= 0


def test_unrecovered_drawdown_marked():
    """Equity series ending below high: recovery_days set to a finite
    sentinel AND unrecovered flag is True in the report."""
    # NAV peaks at 1.5, falls and never recovers by series end.
    nav = np.array([1.0, 1.2, 1.5, 1.3, 1.1, 0.95, 0.90, 0.92, 0.88, 0.85])
    ts = pd.date_range("2024-01-01", periods=len(nav), freq="D")
    periods = _drawdown_periods(nav, ts.values)
    assert len(periods) >= 1
    # Peak at index 2 (val=1.5), trough at index 9 (val=0.85)
    # Find unrecovered period (must be exactly one for this curve)
    unrec_periods = [p for p in periods if p[4] is True]
    assert len(unrec_periods) == 1
    s, e, dpct, rec_days, unrec = unrec_periods[0]
    # Final bar must be the end_date for unrecovered DD.
    assert pd.Timestamp(e) == ts[-1]
    # Sentinel: bars from trough to last bar (here: index 9 - index 9 = 0).
    assert isinstance(rec_days, int)
    assert rec_days >= 0
    # Depth should reflect 0.85/1.5 - 1 = -43.3%
    assert -45.0 < dpct < -40.0
    assert unrec is True


def test_unrecovered_drawdown_html_renders_open_status():
    """The HTML rendering should mark unrecovered DDs with an 'open' status."""
    from aurora.reporting.tearsheet import _top_dd_html
    nav = np.array([1.0, 1.5, 1.2, 1.0, 0.9, 0.85])
    ts = pd.date_range("2024-01-01", periods=len(nav), freq="D")
    periods = _drawdown_periods(nav, ts.values)
    html = _top_dd_html(periods)
    # Status column "open" must appear for unrecovered DDs.
    assert "open" in html
    # Recovery-days suffix for unrecovered DD has a trailing '+'.
    assert "+" in html


def test_top_dd_html_handles_numpy_int_indexes():
    """Round V regression: when ``start``/``end`` are numpy integers (not
    Python ``int``), the date-vs-int branch must still pick the int path,
    so we get the raw integer rendered (and escaped) rather than crashing
    on ``pd.Timestamp(np.int64).date()`` for an integer bar index.
    """
    from aurora.reporting.tearsheet import _top_dd_html
    rows = [
        (np.int64(3), np.int64(7), -10.0, np.int64(2), False),
        # Float NaN coming through numpy must also not crash.
        (np.int64(8), np.int64(12), -5.0, np.float64("nan"), True),
    ]
    html = _top_dd_html(rows)
    # numpy ints render as ``3`` / ``7``, not as a 1970 epoch date.
    assert "<td>3</td>" in html
    assert "<td>7</td>" in html
    # NaN recovery-days is rendered as the literal "NaN".
    assert "NaN" in html
    # The status text "open" is HTML-escaped (still ASCII-clean).
    assert "<td>open</td>" in html


def test_top_dd_html_escapes_status_and_recovery():
    """Round V regression: every interpolated value must pass through
    ``_esc`` so a malicious/odd string in start/end/rec_days/status
    cannot break out of the surrounding ``<td>`` cell.
    """
    from aurora.reporting.tearsheet import _top_dd_html
    # Inject HTML metacharacters into the integer-rendered start/end
    # path by constructing a row whose start/end happen to be numpy ints
    # that would otherwise be cast to ``str`` directly.
    rows = [
        (np.int64(1), np.int64(2), -1.5, np.int64(0), False),
    ]
    html = _top_dd_html(rows)
    # ``_esc`` over the integer-cast strings must not produce raw ``<``/``>``
    # outside our intentional template.
    assert "<script>" not in html
    assert "&lt;" not in html  # there is nothing to escape here
    # Status / rec_days values are wrapped in <td>...</td>.
    assert "<td>recovered</td>" in html
    assert "<td>0</td>" in html


def test_monthly_matrix_known():
    """Synthetic returns over exactly 3 months: matrix has correct shape."""
    idx = pd.date_range("2024-01-01", "2024-03-31", freq="B")
    rets = np.full(len(idx), 0.001)  # 0.1% per business day
    pivot = _monthly_returns_matrix(rets, idx.values)
    assert not pivot.empty
    assert 2024 in pivot.index
    # months Jan, Feb, Mar should have non-NaN values
    for m in (1, 2, 3):
        v = pivot.loc[2024, m]
        assert not np.isnan(v)
        assert v > 0  # positive monthly return for steady positive daily


def test_monthly_matrix_empty():
    """Empty input: empty DataFrame returned."""
    idx = pd.date_range("2024-01-01", periods=0, freq="B")
    pivot = _monthly_returns_matrix(np.array([]), idx.values)
    assert pivot.empty


def test_rolling_sharpe_short_series():
    """Series shorter than window: returns all-NaN array of correct length."""
    r = np.array([0.001, -0.002, 0.003])
    sr = _rolling_sharpe(r, window=252)
    assert len(sr) == 3
    assert np.all(np.isnan(sr))


def test_rolling_sharpe_long_series():
    """Series long enough: tail values are finite numbers."""
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 500)
    sr = _rolling_sharpe(r, window=100)
    # First 99 should be NaN; rest finite (or NaN if std=0 but unlikely with random)
    assert np.all(np.isnan(sr[:99]))
    assert np.sum(~np.isnan(sr[99:])) > 0


def test_short_backtest_edge_case():
    """Backtest <60 bars: tearsheet still generates."""
    result = _make_result(n=40, seed=99)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "short.html")
        path = generate_tearsheet(result, out)
        assert os.path.isfile(path)


def test_all_positive_returns():
    """All-positive returns: no drawdown, tearsheet handles gracefully."""
    n = 250
    rets = np.zeros(n)
    rets[1:] = 0.0005  # constant tiny positive
    nav = np.cumprod(1.0 + rets)
    nav[0] = 1.0
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    metrics = compute_metrics(rets[1:], ppy=252)
    res = BacktestResult(metrics=metrics, nav=nav, rets=rets,
                         weights=np.ones(n), timestamps=idx.values)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "pos.html")
        path = generate_tearsheet(res, out)
        assert os.path.isfile(path)


# ---------------------------------------------------------------------------
# Backend isolation: tearsheet rendering must not leak Agg into other tests
# ---------------------------------------------------------------------------
def test_tearsheet_does_not_change_global_backend():
    """When generate_tearsheet runs under pytest, the global matplotlib
    backend must be the same after the call as it was before. This protects
    sibling tests / interactive sessions that depend on a specific backend
    from being silently flipped to Agg by tearsheet rendering."""
    import matplotlib

    prior = matplotlib.get_backend()
    result = _make_result(n=400)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "isolation.html")
        generate_tearsheet(result, out)
        assert os.path.isfile(out)

    after = matplotlib.get_backend()
    assert after == prior, (
        f"tearsheet rendering changed the global matplotlib backend from "
        f"{prior!r} to {after!r}; expected agg_backend_scope to restore it."
    )


def test_agg_backend_scope_restores_prior_backend():
    """The context manager itself must round-trip the current backend."""
    import matplotlib
    from aurora.reporting.tearsheet import agg_backend_scope

    prior = matplotlib.get_backend()
    with agg_backend_scope():
        # inside the scope we must be on Agg so plt.subplots() never tries Tk
        assert matplotlib.get_backend().lower() == "agg"
    # outside the scope the prior backend is restored
    assert matplotlib.get_backend() == prior

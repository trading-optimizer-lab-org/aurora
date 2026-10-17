from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import stocks_sepa as ss


def _panel(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
            "volume": close * 0 + 1e6, "dollar_volume": close * 1e6, "real_price": close}


def _dates(n: int, start: str = "1993-01-04") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


def _spec(**kw) -> dict:
    return {"mode": "daily", "slots": 1, "stop": 0.08, "target": None, **kw}


def _signals(dates, cols, entry_day: int) -> dict:
    entry = pd.DataFrame(False, index=dates, columns=cols)
    entry.iloc[entry_day, 0] = True
    return {"rs": pd.DataFrame(90.0, index=dates, columns=cols), "ma50": pd.DataFrame(0.0, index=dates, columns=cols),
            "template": entry, "breakout": entry, "market": pd.Series(True, index=dates)}


def test_uptrend_passes_template_and_downtrend_does_not() -> None:
    dates = _dates(600)
    up = 20 * np.exp(np.linspace(0, 1.5, 600))
    close = pd.DataFrame({"UP": up, "DOWN": up[::-1]}, index=dates)
    ind = ss.indicators(_panel(close), pd.Series(up, index=dates))
    assert ind["template"]["UP"].iloc[-1]
    assert not ind["template"]["DOWN"].iloc[-200:].any()
    assert ind["market"].iloc[-1]


def test_entry_executes_at_next_open_and_stop_fills_at_gap_open() -> None:
    dates = _dates(10, "1995-01-02")
    close = pd.DataFrame({"A": [100.0] * 10}, index=dates)
    panel = _panel(close)
    panel["open"] = close.copy()
    panel["open"].iloc[3, 0] = 101.0  # entry day open
    panel["open"].iloc[5, 0] = 80.0   # gap far below the 8% stop
    panel["low"] = panel["open"] * 0.99
    panel["low"].iloc[3, 0] = 100.0
    cash = pd.Series(0.0, index=dates)
    d = ss.run_candidate(panel, _signals(dates, ["A"], entry_day=2), cash, _spec(), start=dates[0])
    assert d["invested"].iloc[2] == 0 and d["invested"].iloc[3] > 0.9
    assert d["invested"].iloc[5] == 0
    # Bought at 101 with 10 bps, sold at the 80 open with 10 bps.
    expected = (80 / 101) * (1 - ss.COST) / (1 + ss.COST)
    assert (1 + d["return"]).prod() == pytest.approx(expected, rel=1e-9)


def test_profit_target_fills_at_target() -> None:
    dates = _dates(10, "1995-01-02")
    close = pd.DataFrame({"A": [100.0] * 4 + [130.0] * 6}, index=dates)
    panel = _panel(close)
    panel["open"] = close.copy()
    panel["open"].iloc[4, 0] = 110.0
    panel["high"] = close * 1.0
    panel["high"].iloc[4, 0] = 130.0
    panel["low"] = panel["open"] * 1.0
    d = ss.run_candidate(panel, _signals(dates, ["A"], entry_day=2), pd.Series(0.0, index=dates),
                         _spec(stop=0.07, target=0.25), start=dates[0])
    expected = 1.25 * (1 - ss.COST) / (1 + ss.COST)
    assert (1 + d["return"]).prod() == pytest.approx(expected, rel=1e-9)
    assert d["invested"].iloc[4] == 0


def test_close_below_ma50_sells_next_open() -> None:
    dates = _dates(8, "1995-01-02")
    close = pd.DataFrame({"A": [100.0] * 8}, index=dates)
    sig = _signals(dates, ["A"], entry_day=1)
    sig["ma50"].iloc[4:, 0] = 200.0
    d = ss.run_candidate(_panel(close), sig, pd.Series(0.0, index=dates), _spec(), start=dates[0])
    assert d["invested"].iloc[4] > 0.9 and d["invested"].iloc[5] == 0


def test_momentum_decile_is_labelled_by_holding_month() -> None:
    months = pd.period_range("2000-01", periods=15, freq="M")
    cols = [f"S{i}" for i in range(10)]
    growth = np.arange(1, 11) / 100
    close = pd.DataFrame(100 * (1 + growth) ** np.arange(15)[:, None], index=months, columns=cols)
    out = ss.momentum_top_decile(close, close * 0 + 50, pd.Index(cols))
    assert out.index[0] == pd.Period("2001-02", "M")
    assert out.iloc[0] == pytest.approx(0.10)


def test_adjust_removes_bias_in_proportion_to_exposure() -> None:
    dates = pd.bdate_range("2011-01-03", "2011-01-31")
    d = pd.DataFrame({"return": 0.0, "invested": 0.5}, index=dates)
    assert ss.adjust(d, 0.02).sum() == pytest.approx(-0.01)


def test_run_study_rejects_locked_data() -> None:
    dates = _dates(5, "2020-12-29")
    close = pd.DataFrame({"A": 100.0}, index=dates)
    with pytest.raises(ValueError, match="locked"):
        ss.run_study(_panel(close), close["A"], close["A"], close["A"], pd.Series(dtype=float),
                     pd.Series(dtype=float))

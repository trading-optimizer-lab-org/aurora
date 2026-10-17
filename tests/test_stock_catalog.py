from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research import stock_catalog as sc
from aurora.research import stock_data_checks as q


def _panel(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"open": close.copy(), "high": close * 1.01, "low": close * 0.99, "close": close.copy(),
            "volume": close * 0 + 1e6}


def _ind(close: pd.DataFrame, sma: float = 0.0) -> dict:
    z = close * 0 + sma
    return {"sma10": z, "sma20": z, "universe": close.notna(), "adr": close * 0 + 0.05,
            "rs": close * 0 + 90, "ind_rs": close * 0 + 80, "mf": pd.Series(True, index=close.index)}


def _entry(close: pd.DataFrame, day: int) -> pd.DataFrame:
    e = pd.DataFrame(False, index=close.index, columns=close.columns)
    e.iloc[day, 0] = True
    return e


def _run(panel, ind, entries, stops, rule, **kw):
    cash = pd.Series(0.0, index=panel["close"].index)
    return sc.simulate(panel, ind, entries, stops, rule, cash, ind["rs"], start=panel["close"].index[0], **kw)


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("1995-01-02", periods=n)


def test_entry_at_close_is_sized_by_risk_and_exits_after_five_days() -> None:
    idx = _dates(12)
    close = pd.DataFrame({"A": [100.0] * 12}, index=idx)
    panel = _panel(close)
    stops = close * 0 + 95.0  # 5% below: 0.5% risk -> 10% of equity
    d = _run(panel, _ind(close), _entry(close, 2), stops, "X5")
    assert d["invested"].iloc[2] == pytest.approx(0.10, rel=1e-3)
    assert d["invested"].iloc[6] > 0 and d["invested"].iloc[7] == 0
    assert (1 + d["return"]).prod() == pytest.approx(1 - 0.10 * 2 * sc.COST, rel=1e-4)


def test_position_is_capped_at_twenty_percent() -> None:
    idx = _dates(6)
    close = pd.DataFrame({"A": [100.0] * 6}, index=idx)
    d = _run(_panel(close), _ind(close), _entry(close, 1), close * 0 + 99.5, "X5")
    assert d["invested"].iloc[1] == pytest.approx(sc.CAP, rel=1e-3)


def test_stop_fills_at_gap_open_from_the_next_day() -> None:
    idx = _dates(8)
    close = pd.DataFrame({"A": [100.0] * 8}, index=idx)
    panel = _panel(close)
    panel["open"].iloc[4, 0] = 80.0
    panel["low"].iloc[4, 0] = 79.0
    d = _run(panel, _ind(close), _entry(close, 2), close * 0 + 95.0, "XS20")
    assert d["invested"].iloc[3] > 0 and d["invested"].iloc[4] == 0
    expected = 1 - 0.10 * (1 + sc.COST) + 0.10 * 0.80 * (1 - sc.COST)
    assert (1 + d["return"]).prod() == pytest.approx(expected, rel=1e-5)


def test_close_below_sma_exits_at_that_close() -> None:
    idx = _dates(8)
    close = pd.DataFrame({"A": [100.0] * 8}, index=idx)
    ind = _ind(close)
    ind["sma20"].iloc[5, 0] = 101.0
    d = _run(_panel(close), ind, _entry(close, 2), close * 0 + 95.0, "XS20")
    assert d["invested"].iloc[4] > 0 and d["invested"].iloc[5] == 0


def test_half_at_day_three_then_stop_moves_to_entry() -> None:
    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    panel = _panel(close)
    panel["low"].iloc[7, 0] = 99.0  # touches the break-even stop (entry 100)
    panel["low"].iloc[:7, 0] = 100.5
    d = _run(panel, _ind(close), _entry(close, 2), close * 0 + 95.0, "XH3")
    assert d["invested"].iloc[5] == pytest.approx(0.05, rel=1e-2)
    assert d["invested"].iloc[7] == 0


def test_bnf_limit_fills_next_day_and_exits_on_rsi() -> None:
    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    panel = _panel(close)
    limits = close * 0 + 99.5
    rsi = close * 0 + 50.0
    rsi.iloc[6, 0] = 90.0
    d = _run(panel, _ind(close), _entry(close, 2), None, "BNF", limits=limits, rsi=rsi)
    assert d["invested"].iloc[2] == 0 and d["invested"].iloc[3] == pytest.approx(sc.BNF_SIZE, rel=1e-2)
    assert d["invested"].iloc[6] == 0


def test_entry_mask_applies_filters() -> None:
    idx = _dates(3)
    close = pd.DataFrame({"A": [1.0] * 3, "B": [1.0] * 3}, index=idx)
    ind = _ind(close)
    ind["adr"]["B"] = 0.02
    ind["mf"].iloc[0] = False
    sig = pd.DataFrame(True, index=idx, columns=close.columns)
    m = sc.entry_mask(sig, ind, ("MF", "ADR4", "IND50"))
    assert not m.iloc[0].any() and m["A"].iloc[1:].all() and not m["B"].any()


def test_industry_rs_ranks_industries_weekly() -> None:
    idx = pd.bdate_range("2020-01-06", periods=5)  # one week, Friday last
    rs = pd.DataFrame([[90, 80, 70, 10, 20, 30]] * 5, index=idx, columns=list("abcdef"), dtype=float)
    industry = pd.Series(["X", "X", "X", "Y", "Y", "Y"], index=list("abcdef"))
    out = sc.industry_rs(rs, industry)
    assert out.iloc[-1]["a"] == 100 and out.iloc[-1]["d"] == 50
    assert out.iloc[0].isna().all()  # not known before the week's last day


def test_blend_resets_to_equal_weights_each_month() -> None:
    idx = pd.bdate_range("2020-01-30", periods=4)  # Thu, Fri | Mon, Tue (Feb)
    a = pd.Series([0.10, 0.10, 0.0, 0.0], index=idx)
    b = pd.Series([0.0, 0.0, 0.10, 0.0], index=idx)
    r = sc.blend({"a": a, "b": b}, ("a", "b"))
    assert r.iloc[1] == pytest.approx(0.10 * 1.1 / 2.1)
    assert r.iloc[2] == pytest.approx(0.05)


def test_run_study_rejects_locked_data() -> None:
    idx = pd.bdate_range("2020-12-30", periods=3)
    close = pd.DataFrame({"A": 1.0}, index=idx)
    with pytest.raises(ValueError, match="locked"):
        sc.run_study(_panel(close), close["A"], close["A"], close["A"], pd.Series({"A": "X"}))


def test_data_checks_flag_bad_series() -> None:
    idx = pd.bdate_range("2000-01-03", periods=10)
    df = pd.DataFrame({"open": 10.0, "high": 10.5, "low": 9.5, "close": 10.0, "adj_close": 10.0,
                       "volume": 1000.0, "stock_splits": 0.0}, index=idx)
    assert q.is_severe(q.check_series(df, idx)) == []
    bad = df.copy()
    bad.iloc[3, bad.columns.get_loc("adj_close")] = 30.0
    bad.iloc[6, bad.columns.get_loc("adj_close")] = 30.0
    assert any("spikes" in r for r in q.is_severe(q.check_series(bad, idx)))
    split = df.copy()
    split.iloc[5:, [0, 1, 2, 3, 4]] = 40.0
    split.iloc[5, split.columns.get_loc("stock_splits")] = 4.0
    assert any("split" in r for r in q.is_severe(q.check_series(split, idx)))


def test_setups_return_signal_and_stop_shapes() -> None:
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.001, 0.03, (400, 3)), axis=0), index=idx, columns=list("abc"))
    panel = _panel(close)
    ind = sc.indicators(panel, close["a"], pd.Series({"a": "X", "b": "X", "c": "X"}))
    for key, fn in sc.SETUPS.items():
        sig, stop = fn(*(panel[k] for k in ("open", "high", "low", "close", "volume")), ind)
        assert sig.shape == close.shape and stop.shape == close.shape, key
    sig, limit, dev = sc.bnf_signals(panel, ind)
    assert sig.shape == close.shape


def test_trade_list_skips_overlapping_signals_and_nets_costs() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(15)
    close = pd.DataFrame({"A": [100.0] * 6 + [110.0] * 9}, index=idx)
    panel = _panel(close)
    entries = _entry(close, 1)
    entries.iloc[3, 0] = True  # inside the first trade: skipped
    entries.iloc[9, 0] = True  # after it: a second trade
    t = st.trade_list(panel, _ind(close), entries, close * 0 + 95.0, "X5", start=idx[0])
    assert len(t) == 2
    assert t["return"].iloc[0] == pytest.approx(110 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1)
    assert t["R"].iloc[0] == pytest.approx(t["return"].iloc[0] / 0.05)
    assert t["days"].iloc[0] == 5


def test_trade_list_stop_and_half_exit() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0, 100, 100, 104, 104, 104, 104, 104, 104, 104]}, index=idx)
    panel = _panel(close)
    panel["low"] = close * 1.0
    panel["low"].iloc[7, 0] = 99.0  # break-even stop after the half exit
    t = st.trade_list(panel, _ind(close), _entry(close, 1), close * 0 + 95.0, "XH3", start=idx[0])
    half = 104 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1
    rest = 100 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1
    assert t["return"].iloc[0] == pytest.approx(0.5 * half + 0.5 * rest)


def test_trade_list_bnf_needs_a_fill() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    panel = _panel(close)
    entries = _entry(close, 1)
    entries.iloc[6, 0] = True
    limits = close * 0 + 99.5
    limits.iloc[6, 0] = 90.0  # never reached: no trade
    t = st.trade_list(panel, _ind(close), entries, None, "BNF", start=idx[0], limits=limits,
                      rsi=close * 0 + 50.0)
    assert len(t) == 1 and t["entry"].iloc[0] == pytest.approx(99.5) and t["days"].iloc[0] == 5


def test_trade_stats_profit_factor_and_total() -> None:
    from aurora.research import stock_trades as st

    t = pd.DataFrame({"return": [0.10, -0.05, 0.20, -0.05], "R": [2.0, -1.0, 4.0, -1.0], "days": [1, 2, 3, 4]})
    s = st.trade_stats(t)
    assert s["profit_factor"] == pytest.approx(3.0)
    assert s["total_return"] == pytest.approx(0.20)
    assert s["total_R"] == pytest.approx(4.0) and s["win_rate"] == 0.5


def test_short_profits_when_price_falls_and_stop_uses_the_high() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(8)
    close = pd.DataFrame({"A": [100.0, 100, 100, 90, 90, 90, 90, 90]}, index=idx)
    panel = _panel(close)
    ind = _ind(close, sma=95.0)  # cover when close <= SMA10 (95)
    stops = close * 0 + 105.0
    d = _run(panel, ind, _entry(close, 2), stops, "XPS", side=-1)
    expected_value = 1 - 0.10 * (1 + sc.COST) + 0.10 * (2 - 0.9) - 0.10 * 0.9 * sc.COST
    assert (1 + d["return"]).prod() == pytest.approx(expected_value, rel=1e-5)
    t = st.trade_list(panel, ind, _entry(close, 2), stops, "XPS", start=idx[0], side=-1)
    assert t["return"].iloc[0] == pytest.approx((2 - 0.9 - 0.9 * sc.COST) / (1 + sc.COST) - 1)
    up = pd.DataFrame({"A": [100.0, 100, 100, 100, 100, 100, 100, 100]}, index=idx)
    p2 = _panel(up)
    p2["high"].iloc[4, 0] = 106.0
    t2 = st.trade_list(p2, _ind(up, sma=50.0), _entry(up, 2), up * 0 + 105.0, "XPS", start=idx[0], side=-1)
    assert t2["exit"].iloc[0] == pytest.approx(105.0) and t2["return"].iloc[0] < 0


def test_sma50_exit_and_bnf_stop() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    ind = _ind(close)
    ind["sma50"] = close * 0 + 0.0
    ind["sma50"].iloc[6, 0] = 101.0
    t = st.trade_list(_panel(close), ind, _entry(close, 2), close * 0 + 95.0, "XS50", start=idx[0])
    assert t["days"].iloc[0] == 4
    panel = _panel(close)
    panel["low"].iloc[4, 0] = 90.0
    t2 = st.trade_list(panel, ind, _entry(close, 2), close * 0 + 92.0, "BNF", start=idx[0],
                       limits=close * 0 + 99.5, rsi=close * 0 + 50.0)
    assert t2["exit"].iloc[0] == pytest.approx(92.0)


def test_v2_parabolic_short_signal_and_breadth() -> None:
    from aurora.research import stock_catalog_v2 as v2

    idx = _dates(12)
    px = [10, 10, 10, 10, 10, 11, 13, 15, 18, 16, 15, 15]
    close = pd.DataFrame({"A": px}, index=idx, dtype=float)
    panel = _panel(close)
    sig, stop = v2.setup_s9(*(panel[k] for k in ("open", "high", "low", "close", "volume")), _ind(close))
    assert sig["A"].tolist() == [False] * 9 + [True, False, False]
    assert stop["A"].iloc[9] == pytest.approx(18 * 1.01)
    on = v2.breadth_on(close, close.notna())
    assert on.dtype == bool

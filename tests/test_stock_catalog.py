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


def test_v3_grid_size_shards_and_new_setups() -> None:
    from aurora.research import stock_catalog_v3 as v3

    names = [t.name for t in v3.trials()]
    assert len(names) == 326 and len(set(names)) == 326
    covered = sorted(g for k in range(12) for g in v3.shard_groups(k, 12))
    assert covered == sorted(v3.GROUPS)
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.001, 0.03, (400, 3)), axis=0), index=idx, columns=list("abc"))
    panel = _panel(close)
    ind = sc.indicators(panel, close["a"], pd.Series({"a": "X", "b": "X", "c": "X"}))
    for key, fn in v3.NEW_SETUPS.items():
        sig, stop = fn(*(panel[k] for k in ("open", "high", "low", "close", "volume")), ind)
        assert sig.shape == close.shape and stop.shape == close.shape, key


def test_trailing_stop_rises_with_the_close() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(8)
    close = pd.DataFrame({"A": [100.0, 100, 100, 110, 120, 120, 120, 120]}, index=idx)
    panel = _panel(close)
    panel["low"] = close * 1.0
    panel["low"].iloc[6, 0] = 100.0  # below 120 * (1 - 3 * 5%) = 102
    t = st.trade_list(panel, _ind(close), _entry(close, 2), close * 0 + 90.0, "XT3", start=idx[0])
    assert t["exit"].iloc[0] == pytest.approx(102.0) and t["exit_date"].iloc[0] == idx[6]


def test_v4_grid_and_new_setups() -> None:
    from aurora.research import stock_catalog_v4 as v4

    names = [t.name for t in v4.trials()]
    assert len(names) == 720 and len(set(names)) == 720
    assert sorted(g for k in range(15) for g in v4.shard_groups(k, 15)) == sorted(v4.SETUPS)
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.001, 0.03, (400, 3)), axis=0), index=idx, columns=list("abc"))
    panel = _panel(close)
    ind = sc.indicators(panel, close["a"], pd.Series({"a": "X", "b": "X", "c": "X"}))
    for key, fn in v4.NEW.items():
        sig, stop = fn(*(panel[k] for k in ("open", "high", "low", "close", "volume")), ind)
        assert sig.shape == close.shape and stop.shape == close.shape, key


def test_profit_target_half_then_sma50() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(8)
    close = pd.DataFrame({"A": [100.0, 100, 100, 120, 130, 130, 130, 130]}, index=idx)
    panel = _panel(close)
    panel["high"].iloc[4, 0] = 131.0  # reaches +25% (125) on day 4
    panel["open"].iloc[4, 0] = 121.0  # opens below the target
    ind = _ind(close)
    ind["sma50"] = close * 0 + 0.0
    ind["sma50"].iloc[6, 0] = 140.0
    t = st.trade_list(panel, ind, _entry(close, 2), close * 0 + 90.0, "XO25", start=idx[0])
    half = 125 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1
    rest = 130 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1
    assert t["return"].iloc[0] == pytest.approx(0.5 * half + 0.5 * rest)


def test_v5_grid_setups_and_exits() -> None:
    from aurora.research import stock_catalog_v5 as v5
    from aurora.research import stock_trades as st

    names = [t.name for t in v5.trials()]
    assert len(names) == 960 and len(set(names)) == 960
    assert sorted(g for k in range(20) for g in v5.shard_groups(k, 20)) == sorted(v5.SETUPS)
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.001, 0.03, (400, 3)), axis=0), index=idx, columns=list("abc"))
    panel = _panel(close)
    ind = sc.indicators(panel, close["a"], pd.Series({"a": "X", "b": "X", "c": "X"}))
    from aurora.research import stock_catalog_v2 as v2
    ctx = {"sma200": sc.sma(close, 200), "stage2": v2.stage2(close), "week_end": sc.week_ends(idx),
           "month_end": v5.month_ends(idx), "index": close["a"]}
    for key in v5.SETUPS:
        sig, stop = v5.build(key, *(panel[k] for k in ("open", "high", "low", "close", "volume")), ind, ctx)
        assert sig.shape == close.shape and stop.shape == close.shape, key
    # XR3: +3R target fills at the target
    d = _dates(8)
    c2 = pd.DataFrame({"A": [100.0, 100, 100, 104, 120, 120, 120, 120]}, index=d)
    p2 = _panel(c2)
    p2["open"].iloc[4, 0] = 104.0
    t = st.trade_list(p2, _ind(c2), _entry(c2, 2), c2 * 0 + 95.0, "XR3", start=d[0])
    assert t["exit"].iloc[0] == pytest.approx(115.0)
    # XTIME20 exits on day 20 at the latest
    d3 = _dates(30)
    c3 = pd.DataFrame({"A": [100.0] * 30}, index=d3)
    t3 = st.trade_list(_panel(c3), _ind(c3), _entry(c3, 2), c3 * 0 + 95.0, "XTIME20", start=d3[0])
    assert t3["days"].iloc[0] == 20


def test_v6_grid_and_volume_setups() -> None:
    from aurora.research import stock_catalog_v6 as v6

    names = [t.name for t in v6.trials()]
    assert len(set(names)) == len(names) == 51 * 23 * 10
    assert sorted(g for k in range(51) for g in v6.shard_groups(k, 51)) == sorted(v6.SETUPS)
    rng = np.random.default_rng(4)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.001, 0.03, (400, 3)), axis=0), index=idx, columns=list("abc"))
    panel = _panel(close)
    ind = sc.indicators(panel, close["a"], pd.Series({"a": "X", "b": "X", "c": "X"}))
    args = [panel[k] for k in ("open", "high", "low", "close", "volume")]
    vc = v6.volume_context(*args, ind)
    for key in v6.VOLUME_SETUPS:
        sig, stop = v6.build_volume(key, *args, ind, vc)
        assert sig.shape == close.shape and stop.shape == close.shape, key


def _v7_inputs(seed: int):
    from aurora.research import stock_catalog_v2 as v2
    from aurora.research import stock_catalog_v5 as v5
    from aurora.research import stock_catalog_v6 as v6

    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(100 * np.cumprod(1 + rng.normal(0.001, 0.03, (400, 3)), axis=0), index=idx, columns=list("abc"))
    panel = _panel(close)
    panel["volume"] = close * 0 + rng.uniform(5e5, 2e6, close.shape)
    industry = pd.Series({"a": "X", "b": "X", "c": "Y"})
    ind = sc.indicators(panel, close["a"], industry)
    ind["rsi14"] = v5.rsi(close, 14)
    ind["ema10"] = sc.ema(close, 10)
    args = [panel[k] for k in ("open", "high", "low", "close", "volume")]
    vc = v6.volume_context(*args, ind)
    ctx = {"sma200": sc.sma(close, 200), "stage2": v2.stage2(close), "week_end": sc.week_ends(idx),
           "month_end": v5.month_ends(idx), "index": close["a"], "index_close": close["a"], "industry": industry}
    return close, ind, args, vc, ctx


def test_v7_grid_shards_and_new_setups() -> None:
    from aurora.research import stock_catalog_v7 as v7

    names = [t.name for t in v7.trials()]
    assert len(set(names)) == len(names) == 235_200
    assert (len(v7.SETUPS), len(v7.EXITS), len(v7.FILTER_SETS), len(v7.STOPS)) == (80, 30, 14, 7)
    assert v7.SHARDS == 320
    assert sorted(t.name for k in range(v7.SHARDS) for t in v7.shard_trials(k)) == sorted(names)
    close, ind, args, vc, ctx = _v7_inputs(5)
    for key in v7.NEW_SETUPS:
        sig, stop = v7.build(key, *args, ind, ctx, vc)
        assert sig.shape == close.shape and stop.shape == close.shape, key


def test_v7_calendar_flags_masks_and_deflated_sharpe() -> None:
    from aurora.research import multiasset_baselines as mab
    from aurora.research import stock_catalog_v7 as v7

    idx = pd.DatetimeIndex(["2019-12-27", "2019-12-30", "2019-12-31", "2020-01-02", "2020-01-03"])
    assert list(v7._holiday_eves(idx)) == [False, False, True, False, False]
    assert list(v7._new_year_firsts(idx)) == [False, False, False, True, False]
    d = pd.bdate_range("2000-08-21", periods=60)
    sig = pd.DataFrame(True, index=d, columns=["a"])
    ind = {"universe": sig, "mf": pd.Series(True, index=d), "adr": sig * 0 + 0.05, "ind_rs": sig * 0 + 90}
    calm = pd.Series(d.day % 2 == 0, index=d)
    extra = {"calm": calm, "breadth": pd.Series(True, index=d)}
    m = v7.mask_v7(sig, ind, v7.FILTER_SETS["G13"], extra, own_universe=False)
    assert not m.loc[d.month.isin([9, 10])].any().any() and m.loc[d.month == 8].all().all()
    m = v7.mask_v7(sig, ind, v7.FILTER_SETS["G10"], extra, own_universe=False)
    assert (m["a"] == calm).all()
    pool = [0.2, 0.5, 0.9, 1.1, 1.4, 0.3, -0.2, 0.8]
    got = v7.deflated_sharpe(np.array([1.4, 0.5]), pool, np.array([2520, 2520]), np.array([-0.3, 0.1]),
                             np.array([5.0, 4.0]))
    want = [mab.deflated_sharpe(1.4, pool, 2520, -0.3, 5.0), mab.deflated_sharpe(0.5, pool, 2520, 0.1, 4.0)]
    assert got == pytest.approx(want)


def _v7_path() -> tuple[dict, dict, pd.DataFrame]:
    from aurora.research import stock_catalog_v5 as v5

    up = 100 * 1.01 ** np.arange(1, 51)
    down = up[-1] * 0.985 ** np.arange(1, 81)
    close = pd.DataFrame({"A": np.r_[np.full(150, 100.0) * (1 + 0.002 * np.sin(np.arange(150))), up, down]},
                         index=_dates(280))
    panel = _panel(close)
    ind = sc.indicators(panel, close["A"], pd.Series({"A": "X"}))
    ind.update(sma100=sc.sma(close, 100), ema10=sc.ema(close, 10), rsi14=v5.rsi(close, 14),
               low50=panel["low"].shift(1).rolling(50, min_periods=50).min())
    return panel, ind, close


@pytest.mark.parametrize("rule", ["XCH", "XSAR", "XDEC", "XS100", "XLOW50", "XKELL", "XT8H"])
def test_v7_exits_agree_between_portfolio_and_trade_engines(rule: str) -> None:
    from aurora.research import stock_trades as st

    panel, ind, close = _v7_path()
    entries, stops = _entry(close, 149), close * (1 - 2 * ind["adr"])
    trades: list[dict] = []
    _run(panel, ind, entries, stops, rule, trades=trades)
    t = st.trade_list(panel, ind, entries, stops, rule, start=close.index[0])
    assert trades and len(t) == 1
    assert trades[-1]["exit_date"] == t["exit_date"].iloc[0]
    assert trades[-1]["exit"] == pytest.approx(t["exit"].iloc[0], rel=1e-5)
    assert t["exit_date"].iloc[0] > close.index[150]
    if rule == "XT8H":
        assert len(trades) == 2 and trades[0]["fraction"] == 0.5
        assert trades[0]["exit"] >= 1.5 * close.iloc[149, 0] * (1 - 1e-6)


def test_intraday_fill_stops_the_same_day_or_moves_to_the_day_low() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    panel = _panel(close)
    entries, px = _entry(close, 2), close * np.nan
    px.iloc[2, 0] = 101.0
    stops = close * 0 + 96.0  # 101 x (1 - ~5%)
    # the day's low (97) stays above the stop: the stop moves up to 97, hit on day 5
    panel["low"].iloc[2, 0] = 97.0
    panel["low"].iloc[5, 0] = 96.5
    t = st.trade_list(panel, _ind(close), entries, stops, "XS20", start=idx[0], entry_px=px)
    assert t["entry"].iloc[0] == pytest.approx(101.0) and t["exit"].iloc[0] == pytest.approx(97.0)
    assert t["exit_date"].iloc[0] == idx[5]
    trades: list[dict] = []
    _run(panel, _ind(close), entries, stops, "XS20", trades=trades, entry_px=px)
    assert trades[0]["exit"] == pytest.approx(97.0) and trades[0]["exit_date"] == idx[5]
    # the day's low reaches the stop: out the same day at the stop
    panel["low"].iloc[2, 0] = 95.0
    t = st.trade_list(panel, _ind(close), entries, stops, "XS20", start=idx[0], entry_px=px)
    assert t["days"].iloc[0] == 0 and t["exit"].iloc[0] == pytest.approx(96.0)
    trades = []
    _run(panel, _ind(close), entries, stops, "XS20", trades=trades, entry_px=px)
    assert trades[0]["exit_date"] == idx[2] and trades[0]["exit"] == pytest.approx(96.0)


def test_qullamaggie_exit_sells_a_third_on_day_five_then_trails_the_sma20() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(14)
    close = pd.DataFrame({"A": [100.0, 100, 100, 104, 106, 108, 110, 115, 112, 112, 112, 112, 112, 112]}, index=idx)
    panel = _panel(close)
    ind = _ind(close)
    ind["sma20"].iloc[4, 0] = 200.0  # below SMA20 before the partial day: ignored
    ind["sma20"].iloc[10, 0] = 120.0  # first close below SMA20 after day 5
    entries, stops = _entry(close, 2), close * 0 + 95.0
    t = st.trade_list(panel, ind, entries, stops, "XQ5_20", start=idx[0])
    third = 115 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1
    rest = 112 * (1 - sc.COST) / (100 * (1 + sc.COST)) - 1
    assert t["exit_date"].iloc[0] == idx[10]
    assert t["return"].iloc[0] == pytest.approx(third / 3 + 2 * rest / 3)
    trades: list[dict] = []
    _run(panel, ind, entries, stops, "XQ5_20", trades=trades)
    assert [round(x["fraction"], 4) for x in trades] == [round(1 / 3, 4), 1.0]
    assert trades[0]["exit_date"] == idx[7] and trades[1]["exit_date"] == idx[10]


def test_qullamaggie_grid_and_signal_shapes() -> None:
    from aurora.research import qullamaggie as q

    names = [t.name for t in q.trials()]
    assert len(names) == len(set(names)) == 85 and len(q.groups()) == 12
    assert set(q.CANONICAL) <= set(names)
    assert {t.group for t in q.trials()} == set(q.groups())
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("1993-01-04", periods=400)
    close = pd.DataFrame(20 * np.cumprod(1 + rng.normal(0.002, 0.05, (400, 6)), axis=0), index=idx,
                         columns=list("abcdef"))
    panel = _panel(close)
    panel["volume"] = close * 0 + rng.uniform(2e5, 2e6, close.shape)
    panel["open"] = close.shift(1).fillna(close) * (1 + rng.normal(0, 0.03, close.shape))
    ind = sc.indicators(panel, close["a"], pd.Series(dict.fromkeys("abcdef", "X")))
    nasdaq = close.mean(axis=1)
    m1 = q.nasdaq_filter(nasdaq, idx)
    assert not m1.iloc[:20].any()
    ctx = q.context(panel, ind, nasdaq)
    for g in q.groups():
        for key, (e, s, px) in q.build_group(g, panel, ind, ctx).items():
            assert e.shape == close.shape and s.shape == close.shape, (g, key)
            assert px is None or px.shape == close.shape


def test_intraday_entry_rules() -> None:
    from aurora.research import qullamaggie_intraday as qi

    minute = np.arange(120)
    o = np.full(120, 10.0)
    h, low, v = o + 0.05, o - 0.05, np.full(120, 100.0)
    h[2] = 10.2  # opening-range high (5 minutes)
    h[12], o[12], low[12] = 10.6, 10.4, 10.3  # breaks the pivot 10.5
    low[3] = 9.8  # low of day before the entry
    low[40], o[40] = 9.7, 9.9  # later breaks the low of day
    entry, stop, m, exit_px = qi.intraday_entry(minute, o, h, low, v, k=5, level_min=10.5)
    assert (entry, stop, m, exit_px) == (10.5, 9.8, 12, pytest.approx(9.8))
    # EP with a volume pace: the first break (minute 12) lacks volume, a later one has it
    v2 = v.copy()
    v2[30] = 5000.0
    h[30] = 10.3
    entry, stop, m, _ = qi.intraday_entry(minute, o, h, low, v2, k=5, adv=6000.0, q_vol=1.0)
    assert m == 30 and entry == pytest.approx(10.2)
    # nothing before 11:00 -> no trade
    flat = np.full(120, 10.0)
    flat_h = flat + 0.01
    flat_h[100] = 11.0
    assert qi.intraday_entry(minute, flat, flat_h, flat - 0.01, v, k=5) is None


def test_same_day_exit_from_minutes_overrides_the_daily_low() -> None:
    from aurora.research import stock_trades as st

    idx = _dates(10)
    close = pd.DataFrame({"A": [100.0] * 10}, index=idx)
    panel = _panel(close)
    panel["low"].iloc[2, 0] = 90.0  # daily low far below the stop, but the minutes say it came first
    entries, px, sd = _entry(close, 2), close * np.nan, close * np.nan
    px.iloc[2, 0] = 101.0
    stops = close * 0 + 98.0
    t = st.trade_list(panel, _ind(close), entries, stops, "XS20", start=idx[0], entry_px=px, same_day_px=sd)
    assert t["days"].iloc[0] > 0  # held: the stop stays at 98 (lows of 99 afterwards)
    sd.iloc[2, 0] = 97.5
    t = st.trade_list(panel, _ind(close), entries, stops, "XS20", start=idx[0], entry_px=px, same_day_px=sd)
    assert t["days"].iloc[0] == 0 and t["exit"].iloc[0] == pytest.approx(97.5)
    trades: list[dict] = []
    _run(panel, _ind(close), entries, stops, "XS20", trades=trades, entry_px=px, same_day_px=sd)
    assert trades[0]["exit_date"] == idx[2] and trades[0]["exit"] == pytest.approx(97.5)


def test_qullamaggie_intraday_pipeline_on_synthetic_data() -> None:
    from aurora.research import qullamaggie_intraday as qi

    names = [t.name for t in qi.trials()]
    assert len(names) == len(set(names)) == 48
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2013-01-01", "2020-12-31")
    n = 12
    close = pd.DataFrame(10 * np.cumprod(1 + rng.normal(0.003, 0.06, (len(idx), n)), axis=0), index=idx,
                         columns=[f"s{i}" for i in range(n)])
    opn = close.shift(1).fillna(close) * (1 + rng.normal(0.01, 0.06, close.shape))
    high = np.maximum(close, opn) * 1.03
    low = np.minimum(close, opn) * 0.97
    vol = close * 0 + 1e6
    panel = {"open": opn, "high": high, "low": low, "close": close, "volume": vol}
    alp = {s: pd.DataFrame({"o": opn[s], "h": high[s], "l": low[s], "c": close[s], "v": vol[s]}) for s in close}

    def load(day: pd.Timestamp) -> pd.DataFrame:
        rows = []
        for s in close.columns:
            path = np.interp(np.arange(390), [0, 60, 200, 389],
                             [opn.at[day, s], high.at[day, s], low.at[day, s], close.at[day, s]])
            rows.append(pd.DataFrame({"symbol": s, "minute": np.arange(390), "o": path, "h": path * 1.0005,
                                      "l": path * 0.9995, "c": path, "v": 1e6 / 390}))
        return pd.concat(rows, ignore_index=True)

    cash = pd.Series(np.cumprod(np.full(len(idx), 1.0001)), index=idx)
    rows, info = qi.run(panel, close.mean(axis=1), close.mean(axis=1), close.mean(axis=1), cash,
                        pd.Series("X", index=close.columns), load, alp, workers=1)
    out = pd.DataFrame(rows)
    assert len(out) == 48 + 3 + 1 and out["name"].is_unique
    assert info["entries"] >= 0 and set(info["dropped"]) == {"no_minutes", "no_daily", "price_mismatch"}


def test_risk_scale_margin_and_cap() -> None:
    idx = _dates(8)
    close = pd.DataFrame({"A": [100.0] * 8, "B": [100.0] * 8, "C": [100.0] * 8}, index=idx)
    panel = _panel(close)
    entries = pd.DataFrame(False, index=idx, columns=close.columns)
    entries.iloc[2] = True
    stops = close * 0 + 99.0  # 1% stop: 0.5% risk wants 50% of equity per position
    ind = _ind(close)
    base = _run(panel, ind, entries, stops, "X5")
    assert base["invested"].iloc[2] == pytest.approx(3 * sc.CAP, rel=1e-3)
    off = _run(panel, ind, entries, stops, "X5", risk_scale=pd.Series(0.0, index=idx))
    assert (off["invested"] == 0).all()
    small = _run(panel, ind, entries, stops, "X5", cap=0.10)
    assert small["invested"].iloc[2] == pytest.approx(0.30, rel=1e-3)
    entries.iloc[2] = False
    entries.iloc[2, 0] = True
    half = _run(panel, ind, entries, close * 0 + 98.0, "X5", risk_scale=pd.Series(0.5, index=idx), cap=1.0)
    assert half["invested"].iloc[2] == pytest.approx(0.125, rel=1e-3)
    big = _run(panel, ind, entries, close * 0 + 99.5, "X5", max_gross=pd.Series(2.0, index=idx), cap=2.0)
    assert big["invested"].iloc[2] == pytest.approx(1.0, abs=2e-3)  # the cost is paid on margin
    lev = _run(panel, ind, entries, close * 0 + 99.75, "X5", max_gross=pd.Series(2.0, index=idx), cap=2.0)
    assert lev["invested"].iloc[2] > 1.5  # more than the whole account is invested on margin


def test_wind_has_no_lookahead_and_policies_follow_the_state() -> None:
    from aurora.research import qullamaggie as q
    from aurora.research import qullamaggie_wind as qw

    assert len({t.name for t in qw.trials()}) == 35
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("1993-01-04", periods=800)
    close = pd.DataFrame(20 * np.cumprod(1 + rng.normal(0.003, 0.05, (800, 40)), axis=0), index=idx,
                         columns=[f"s{i}" for i in range(40)])
    panel = _panel(close)
    panel["open"] = close.shift(1).fillna(close) * (1 + rng.normal(0, 0.02, close.shape))
    panel["high"], panel["low"] = np.maximum(close, panel["open"]) * 1.03, np.minimum(close, panel["open"]) * 0.97
    panel["volume"] = close * 0 + 1e7

    def wind_at(n: int) -> pd.DataFrame:
        p = {k: v.iloc[:n] for k, v in panel.items()}
        ind = sc.indicators(p, p["close"].mean(axis=1), pd.Series("X", index=close.columns))
        return qw.wind(p, ind, q.context(p, ind, p["close"].mean(axis=1)))

    full, cut = wind_at(800), wind_at(600)
    assert full["state"].iloc[:600].equals(cut["state"]) and set(full["state"]) <= {"green", "yellow", "red"}
    w = pd.DataFrame({"state": ["green", "yellow", "red", "green"], "m1": [True, True, True, False]})
    scale, gross, cap = qw.policy("E2", w)
    assert list(scale) == [1.0, 2.0, 1.0, 0.0] and cap == sc.CAP  # decided at the prior close
    scale, gross, cap = qw.policy("E4_C10", w)
    assert list(scale) == [1.0, 2.0, 1.0, 0.0] and list(gross) == [1.0, 2.0, 1.0, 1.0] and cap == 0.10
    assert list(qw.policy("E0", w)[0]) == [1.0] * 4 and list(qw.policy("E1", w)[0]) == [1.0, 1.0, 1.0, 0.0]

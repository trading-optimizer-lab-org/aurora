"""Checks of the earnings options study: SEC clock, events, history features, prices, returns, statistics, the
decision, the book, and one synthetic event end to end through the script's trade builder."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research import earnings_options as eo

T = pd.Timestamp


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_earnings_options.py"
    spec = importlib.util.spec_from_file_location("run_earnings_options_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sec_clock_is_converted_twice() -> None:
    assert eo.sec_time("2026-07-30T00:04:53.000Z") == T("2026-07-29 16:04:53")  # MSFT, summer
    assert eo.sec_time("2026-01-29T02:04:38.000Z") == T("2026-01-28 16:04:38")  # MSFT, winter
    assert eo.sec_time("2026-10-13T14:30:38.000Z") == T("2026-10-13 06:30:38")  # JPM before the open


def test_reaction_session() -> None:
    s = pd.bdate_range("2024-03-04", periods=10)
    assert eo.reaction_session(T("2024-03-05 07:00"), s) == T("2024-03-05")
    assert eo.reaction_session(T("2024-03-05 16:05"), s) == T("2024-03-06")
    assert eo.reaction_session(T("2024-03-05 11:00"), s) is None
    assert eo.reaction_session(T("2024-03-09 10:00"), s) == T("2024-03-11")  # a Saturday


def test_events_drop_repeats_and_flag_the_schedule() -> None:
    s = pd.bdate_range("2023-01-02", "2024-06-28")
    f = pd.DataFrame({"symbol": "X", "t": [T("2023-02-01 16:05"), T("2023-02-08 16:05"), T("2023-05-03 16:05"),
                                           T("2023-11-01 16:05")]})
    ev = eo.build_events(f, s)
    assert ev["t"].tolist() == [T("2023-02-01 16:05"), T("2023-05-03 16:05"), T("2023-11-01 16:05")]
    assert ev["scheduled"].tolist() == [False, True, False]  # 91 days, then 182
    assert (ev["R"] == [T("2023-02-02"), T("2023-05-04"), T("2023-11-02")]).all()
    assert (ev["E"] == [T("2023-02-01"), T("2023-05-03"), T("2023-11-01")]).all()


def test_history_features() -> None:
    s = pd.bdate_range("2022-01-03", "2024-12-31")
    c = pd.Series(100.0, index=s)
    rs = [s[100 + 63 * i] for i in range(6)]
    moves = [0.05, -0.10, 0.02, 0.08, -0.04, 0.03]
    for r, m in zip(rs, moves):
        c[c.index >= r] *= 1 + m
    ev = pd.DataFrame({"symbol": "X", "t": [r - pd.Timedelta(hours=1) for r in rs], "R": rs,
                       "E": [s[s.get_loc(r) - 1] for r in rs], "iR": [s.get_loc(r) for r in rs],
                       "scheduled": True})
    h = eo.history(ev, {"X": c}, s)
    assert h["reaction"].round(10).tolist() == pytest.approx(moves)
    assert np.isnan(h["hm"].iloc[3]) and h["hm"].iloc[4] == pytest.approx(np.median(np.abs(moves[:4])))
    assert h["last_sign"].iloc[2] == -1 and np.isnan(h["last_sign"].iloc[0])
    i = 5
    ie = int(ev["iR"].iloc[i]) - 1
    assert h["mom"].iloc[i] == pytest.approx(c[s[ie - 1]] / c[s[ie - 61]] - 1)


def _bars(day: str, times: list[str], vw: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"t": [T(f"{day} {x}") for x in times], "vw": vw, "c": vw})


def test_price_rules() -> None:
    d = _bars("2024-03-05", ["09:30", "09:45", "14:45", "15:30", "15:45"], [1, 2, 3, 4, 5])
    assert eo.price_entry(d) == 4 and eo.price_morning(d) == 2 and eo.price_eve_exit(d) == 4
    d2 = _bars("2024-03-05", ["10:15", "14:45", "15:45"], [1, 3, 5])
    assert eo.price_entry(d2) == 5 and eo.price_morning(d2) == 1 and eo.price_eve_exit(d2) == 5
    assert eo.price_entry(_bars("2024-03-05", ["10:15", "14:15"], [1, 3])) is None
    assert eo.last_close(d) == 5 and eo.price_morning(None) is None


def test_strikes() -> None:
    k = np.array([95.0, 100.0, 105.0, 110.0, 90.0])
    assert eo.atm(k, 102.5) == 100.0 and eo.atm(k, 103) == 105.0
    assert eo.wings(k, 100.0, 0.05) == (105.0, 90.0)  # 107.5 and 92.5 are ties: the lower strike
    assert eo.wings(k, 100.0, 0.08) == (110.0, 90.0)
    assert eo.wings(np.array([100.0, 105.0]), 100.0, 0.05) is None


def test_returns() -> None:
    r = eo.long_return([4.0, 4.0], [8.5, 0.6], eo.BASE)
    paid = 2 * (4.0 + 0.08 + eo.FEE)
    got = (8.5 - 0.17 - eo.FEE) + (0.6 - 0.025 - eo.FEE)
    assert r == pytest.approx((got - paid) / paid)
    f = eo.fly_return([4.0, 4.0], [1.0, 1.0], [8.0, 0.1], [0.5, 0.0], 10.0, eo.BASE)
    credit = 2 * (4.0 - 0.08 - eo.FEE) - 2 * (1.0 + 0.025 + eo.FEE)
    debit = (8.0 + 0.16 + eo.FEE) + (0.1 + 0.025 + eo.FEE) - (0.5 - 0.025 - eo.FEE) - (0.0 - eo.FEE)
    assert f == pytest.approx((credit - debit) / (10.0 - credit))
    assert eo.fly_return([4.0, 4.0], [0.0, 0.0], [4.0, 4.0], [0.0, 0.0], 5.0, eo.BASE) is None


def test_cluster_t_and_decision() -> None:
    r = np.array([0.1, 0.1, -0.05, 0.2])
    m, t = eo.cluster_t(r, np.array(["a", "a", "b", "b"]))
    sums = np.array([0.2 - 2 * m, 0.15 - 2 * m])
    assert m == pytest.approx(0.0875) and t == pytest.approx(m / (np.sqrt(2 * (sums ** 2).sum()) / 4))
    good = {"trades": 300, "mean": 0.02, "t": 3.0, "mean_high": 0.01}
    weak = dict(good, t=2.0)
    disc = {k: weak for k in eo.TRIALS} | {"H1_runup_3": good, "H2_hold_all": good}
    val = {k: dict(good, trades=50, t=1.0) for k in eo.TRIALS} | {"H1_runup_3": dict(good, trades=50, t=1.8)}
    d = eo.decide(disc, val)
    assert d == {"discovery_pass": ["H1_runup_3", "H2_hold_all"], "validation_pass": ["H1_runup_3"], "met": True}


def test_book_caps_risk() -> None:
    day = T("2024-03-05 15:30")
    trades = [eo.Trade(day, day + pd.Timedelta(hours=18), 1.0, float(i)) for i in range(10)]
    b = eo.book(trades)
    assert b["taken"] == 7  # 7 x 2% = 14% <= 15%; the 8th would be 16%
    assert b["end"] == pytest.approx(100_000 * (1 + 7 * 0.02))


def test_one_event_end_to_end(tmp_path: Path) -> None:
    S = _script()
    s = pd.bdate_range("2024-01-02", "2024-04-30")
    iR = 61
    R, E = s[iR], s[iR - 1]
    (tmp_path / "stock15").mkdir()
    (tmp_path / "opt").mkdir()
    pd.DataFrame({"session": s}).to_parquet(tmp_path / "sessions.parquet", index=False)
    (tmp_path / "gaps.json").write_text(json.dumps([]), encoding="utf-8")
    pd.DataFrame([{"symbol": "X", "t": E + pd.Timedelta(hours=16, minutes=5), "R": R, "E": E, "iR": iR,
                   "scheduled": True, "reaction": 0.0, "hm": 0.05, "last_sign": 1.0, "mom": 0.1,
                   "liq0": True, "liq3": True, "liq5": True, "dv0": 1e8, "dv3": 1e8, "dv5": 1e8}]
                 ).to_parquet(tmp_path / "events.parquet", index=False)
    pd.DataFrame([{"symbol": "X", "R": R, "exp": R + pd.Timedelta(days=7), "k0": 100.0, "k3": 100.0, "k5": 100.0,
                   "kc": 110.0, "kp": 90.0, "C0": "XC100", "P0": "XP100", "C3": "XC100", "P3": "XP100",
                   "C5": "XC100", "P5": "XP100", "WC": "XC110", "WP": "XP90"}]).to_parquet(tmp_path / "plan.parquet",
                                                                                         index=False)
    st = [dict(symbol="X", t=d + pd.Timedelta(hours=15, minutes=30), vw=100.0, c=100.0, v=1.0) for d in s[54:61]]
    st += [dict(symbol="X", t=R + pd.Timedelta(hours=9, minutes=45), vw=108.0, c=108.0, v=1.0),
           dict(symbol="X", t=R + pd.Timedelta(hours=15, minutes=45), vw=108.0, c=108.0, v=1.0)]
    pd.DataFrame(st).to_parquet(tmp_path / "stock15" / "a.parquet", index=False)

    def bar(sym, d, hhmm, px):
        h, m = map(int, hhmm.split(":"))
        return dict(symbol=sym, t=d + pd.Timedelta(hours=h, minutes=m), vw=px, c=px, v=1.0)

    ob = [bar("XC100", s[55], "15:30", 3.0), bar("XC100", s[57], "15:30", 3.2), bar("XC100", E, "15:30", 4.0),
          bar("XC100", R, "09:45", 8.5), bar("XP100", s[55], "15:30", 3.0), bar("XP100", s[57], "15:30", 3.1),
          bar("XP100", E, "15:30", 4.0), bar("XP100", R, "09:45", 0.6), bar("XC110", E, "15:30", 1.0),
          bar("XC110", R, "09:45", 0.4), bar("XP90", E, "15:30", 1.0)]  # XP90 has no exit bar: intrinsic 0
    pd.DataFrame(ob).to_parquet(tmp_path / "opt" / "A_x.parquet", index=False)
    tr, drop = S.trades(tmp_path)
    got = dict(zip(tr["trial"], tr["net"]))
    assert drop == {"events": 1, "no_plan": 0, "gap": 0}
    assert set(got) == {"H1_runup_3", "H1_runup_5", "H2_hold_all", "H3_momentum", "H3_last_reaction",
                        "H4_fly_all", "H4_fly_12", "H4_fly_15"}  # IM/HM = 0.08/0.05 = 1.6
    assert got["H2_hold_all"] == pytest.approx(eo.long_return([4, 4], [8.5, 0.6], eo.BASE))
    assert got["H1_runup_3"] == pytest.approx(eo.long_return([3.2, 3.1], [4.0, 4.0], eo.BASE))
    assert got["H1_runup_5"] == pytest.approx(eo.long_return([3.0, 3.0], [4.0, 4.0], eo.BASE))
    assert got["H3_momentum"] == pytest.approx(eo.long_return([4.0], [8.5], eo.BASE))
    assert got["H4_fly_all"] == pytest.approx(eo.fly_return([4, 4], [1, 1], [8.5, 0.6], [0.4, 0.0], 10, eo.BASE))
    fb = dict(zip(tr["trial"], tr["fallback"]))
    assert fb["H4_fly_all"] and not fb["H2_hold_all"]
    assert (tr["period"] == "discovery").all() and (tr["timing"] == "after_close").all()


def test_load_skips_files_without_bars(tmp_path: Path) -> None:
    S = _script()
    S._frame({}).to_parquet(tmp_path / "A_1.parquet", index=False)
    S._frame({"X": [{"t": "2024-03-05T20:30:00Z", "vw": 1.0, "c": 1.0, "v": 1}]}).to_parquet(
        tmp_path / "A_2.parquet", index=False)
    df = S._load(tmp_path, "A_")
    assert len(df) == 1 and df["t"].iloc[0] == T("2024-03-05 15:30") and df["vw"].dtype == float
    assert set(S._days(df)) == {("X", T("2024-03-05"))}

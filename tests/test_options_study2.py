"""Checks of options study 2: strikes, leg P&L, maximum loss, Black-Scholes, hedged and held returns, deciles,
statistics, the decision, and synthetic 0DTE, overnight and cross-section trades through the script."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research import earnings_options as eo
from aurora.research import options_study2 as os2

T = pd.Timestamp
KS = np.arange(490.0, 511.0)


def _script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_options_study2.py"
    spec = importlib.util.spec_from_file_location("run_options_study2_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_structures() -> None:
    assert os2.structure("Z1_short_straddle", KS, 500.2) == [("C", 500.0, -1), ("P", 500.0, -1)]
    assert os2.structure("Z3_iron_condor", KS, 500.2) == [("C", 503.0, -1), ("P", 498.0, -1), ("C", 505.0, 1),
                                                          ("P", 495.0, 1)]
    assert os2.structure("Z5_put_ratio", KS, 500.2) == [("P", 498.0, 1), ("P", 495.0, -2)]
    assert os2.structure("Z3_iron_condor", np.array([495.0, 500.0, 505.0]), 500.2) is None  # 503 and 505 collapse


def test_leg_pnl_and_max_loss() -> None:
    c = os2.ETF_BASE
    assert os2.leg_pnl(1, 2.0, 3.0, True, c) == pytest.approx((3.0 - 0.01 - eo.FEE) - (2.0 + 0.01 + eo.FEE))
    assert os2.leg_pnl(-2, 1.0, 0.4, False, c) == pytest.approx(2 * ((1.0 - 0.01 - eo.FEE) - 0.4))
    legs = [("C", 500.0, -1), ("P", 500.0, -1), ("C", 505.0, 1), ("P", 495.0, 1)]
    cash = 2 * (3.0 - 0.01 - eo.FEE) - 2 * (1.0 + 0.01 + eo.FEE)
    assert os2.max_loss(legs, [3.0, 3.0, 1.0, 1.0], c) == pytest.approx(5.0 - cash)
    assert os2.max_loss([("C", 500.0, -1)], [3.0], c) > 900  # naked: evaluated at three times the strike


def test_black_scholes() -> None:
    price = os2.bs_straddle(100.0, 100.0, 0.1, 0.2)
    assert os2.implied_vol(price, 100.0, 100.0, 0.1) == pytest.approx(0.2, abs=1e-6)
    assert os2.implied_vol(0.5, 101.0, 100.0, 0.1) is None  # below intrinsic
    assert 0 < os2.straddle_delta(100.0, 100.0, 0.1, 0.2) < 0.05
    assert os2.straddle_delta(110.0, 100.0, 0.1, 0.2) > 0.5


def test_hedged_and_held_returns() -> None:
    c = os2.ETF_BASE
    r = os2.hedged_return(-1, [4.0, 4.0], [3.5, 3.9], 500.0, 501.0, 0.1, c)
    opt = os2.leg_pnl(-1, 4.0, 3.5, True, c) + os2.leg_pnl(-1, 4.0, 3.9, True, c)
    assert r == pytest.approx((opt + 0.1 * 1.0 - 2 * 0.1 * os2.SHARE_COST) / 8.0)
    s = os2.STOCK_BASE
    paid = 5.0 + 5.0 + 0.1 + 0.1 + 2 * eo.FEE
    assert os2.hold_return(1, 5.0, 5.0, 100.0, 112.0, s) == pytest.approx((12.0 - paid) / paid)
    got = 10.0 - 0.2 - 2 * eo.FEE
    assert os2.hold_return(-1, 5.0, 5.0, 100.0, 103.0, s) == pytest.approx((got - 3.0) / 10.0)


def test_deciles_stats_and_decision() -> None:
    d = os2.deciles(pd.Series(np.arange(20.0)))
    assert (d.iloc[:2] == 0).all() and (d.iloc[-2:] == 9).all()
    m = pd.DataFrame({"month": [f"2024-{i:02d}" for i in range(1, 13)], "net": [0.02, 0.04] * 6,
                      "net_high": 0.01, "positions": 30})
    st = os2.stats(m, monthly=True)
    assert st["trades"] == 360 and st["months"] == 12 and st["mean"] == pytest.approx(0.03)
    assert st["t"] == pytest.approx(0.03 / (m["net"].std(ddof=1) / np.sqrt(12)))
    good = {"trades": 500, "mean": 0.01, "t": 3.0, "mean_high": 0.005}
    disc = {k: dict(good, t=1.0) for k in os2.TRIALS} | {"N1_overnight_short": good,
                                                          "X1_vol_spread": dict(good, months=12),
                                                          "X2_long_cheap": dict(good, months=20)}
    val = {k: dict(good, trades=100, t=2.0) for k in os2.TRIALS}
    assert os2.decide(disc, val) == {"discovery_pass": ["N1_overnight_short", "X2_long_cheap"],
                                     "validation_pass": ["N1_overnight_short", "X2_long_cheap"], "met": True}


def _bar(sym: str, d: pd.Timestamp, hh: int, mm: int, px: float) -> dict:
    return {"symbol": sym, "t": d + pd.Timedelta(hours=hh, minutes=mm), "vw": px, "c": px, "v": 1.0}


def test_etf_trades_end_to_end(tmp_path: Path) -> None:
    S = _script()
    d1, d2 = T("2024-03-08"), T("2024-03-11")  # Friday, then Monday: N1 is also a weekend trade
    pd.DataFrame({"session": [d1, d2]}).to_parquet(tmp_path / "sessions.parquet", index=False)
    pd.DataFrame([_bar("SPY", d1, 10, 0, 500.0), _bar("SPY", d1, 15, 45, 502.0), _bar("SPY", d2, 9, 45, 503.0)]
                 ).to_parquet(tmp_path / "etf15.parquet", index=False)
    plan = [{"und": "SPY", "d": "2024-03-08", "trial": "Z1_short_straddle", "s0": 500.0, "exp": "2024-03-08",
             "legs": [["C", 500.0, -1, "C500"], ["P", 500.0, -1, "P500"]]},
            {"und": "SPY", "d": "2024-03-08", "trial": "N1", "s0": 502.0, "exp": "2024-03-15",
             "legs": [["C", 502.0, 1, "WC502"], ["P", 502.0, 1, "WP502"]]}]
    (tmp_path / "etf_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "etf_opt").mkdir()
    ob = [_bar("C500", d1, 9, 30, 2.0), _bar("C500", d1, 10, 0, 2.0), _bar("C500", d1, 15, 45, 2.1),
          _bar("P500", d1, 10, 0, 2.0), _bar("P500", d1, 15, 45, 0.02),
          _bar("WC502", d1, 15, 45, 4.0), _bar("WP502", d1, 15, 45, 4.0),
          _bar("WC502", d2, 9, 45, 4.2)]  # WP502 has no Monday bar: intrinsic 0 + 10% of 4.0
    pd.DataFrame(ob).to_parquet(tmp_path / "etf_opt" / "x.parquet", index=False)
    rows, drop = S.etf_trades(tmp_path)
    got = {r["trial"]: r for r in rows}
    assert set(got) == {"Z1_short_straddle", "N1_overnight_short", "N3_weekend_short"} and drop["gap_days"] == 0
    z = os2.leg_pnl(-1, 2.0, 2.1, True, os2.ETF_BASE) + os2.leg_pnl(-1, 2.0, 0.0, False, os2.ETF_BASE)
    assert got["Z1_short_straddle"]["net"] == pytest.approx(z / 500.0)
    t = ((T("2024-03-15 16:00") - T("2024-03-08 15:45")) / pd.Timedelta(days=365))
    delta = os2.straddle_delta(502.0, 502.0, t, os2.implied_vol(8.0, 502.0, 502.0, t))
    n = os2.hedged_return(-1, [4.0, 4.0], [4.2, 0.4], 502.0, 503.0, delta, os2.ETF_BASE)
    assert got["N1_overnight_short"]["net"] == pytest.approx(n) and got["N1_overnight_short"]["fallback"]


def test_x_trades_end_to_end(tmp_path: Path) -> None:
    S = _script()
    F, E = T("2024-02-20"), T("2024-03-15")
    rows, ob = [], []
    for i in range(10):
        sym = f"S{i}"
        rows.append({"month": "2024-02", "F": F, "symbol": sym, "exp": E, "k": 100.0, "C": f"{sym}C",
                     "P": f"{sym}P", "s_f": 100.0, "raw_f": 100.0, "hv": 0.2 + 0.05 * i, "s_t": 100.0 + i})
        ob += [_bar(f"{sym}C", F, 15, 30, 3.0), _bar(f"{sym}P", F, 15, 30, 3.0)]
    pd.DataFrame(rows).to_parquet(tmp_path / "x_plan.parquet", index=False)
    (tmp_path / "x_drops.json").write_text(json.dumps({"split": 0}), encoding="utf-8")
    (tmp_path / "x_opt").mkdir()
    pd.DataFrame(ob).to_parquet(tmp_path / "x_opt" / "a.parquet", index=False)
    out, drop = S.x_trades(tmp_path)
    got = {r["trial"]: r for r in out}
    long9 = os2.hold_return(1, 3.0, 3.0, 100.0, 109.0, os2.STOCK_BASE)  # highest HV, same IV: top decile
    short0 = os2.hold_return(-1, 3.0, 3.0, 100.0, 100.0, os2.STOCK_BASE)
    assert got["X2_long_cheap"]["net"] == pytest.approx(long9) and got["X3_short_rich"]["net"] == pytest.approx(short0)
    assert got["X1_vol_spread"]["net"] == pytest.approx(long9 + short0) and got["X1_vol_spread"]["positions"] == 2
    assert drop["no_entry"] == 0 and got["X1_vol_spread"]["period"] == "discovery"


def test_report_renders(tmp_path: Path) -> None:
    S = _script()
    d = T("2024-03-05")
    rows = [{"trial": "Z2_iron_fly", "symbol": "SPY", "entry": d, "period": "discovery", "week": "2024-10",
             "year": 2024, "weekday": "Tue", "net": 0.001, "net_high": 0.0005, "fallback": False, "ret_ml": 0.1,
             "t_in": d + 10 * eo.H, "t_out": d + 16 * eo.H}]
    text = S.render(S.evaluate(pd.DataFrame(rows), {"etf": {}, "x": {}}))
    assert "Z2_iron_fly" in text and "Not met" in text

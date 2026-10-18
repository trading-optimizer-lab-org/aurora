"""Qullamaggie's literal rules (breakout, episodic pivot, parabolic short) on the
US stock panel: his stock selection scans, entries, low-of-day stops, partial
sells and Nasdaq market filter. Pre-registered in
docs/research/QULLAMAGGIE_PREREGISTRATION.md (85 trials, 12 shard groups).
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import stock_trades as st

MIN_PRICE, MIN_DV, MIN_HISTORY = 1.0, 1.5e6, 63
TOP, WATCH_DAYS = 0.98, 63
LONG_EXITS = ["XQ3_10", "XQ3_20", "XQ5_10", "XQ5_20"]
SHORT_EXITS = ["XQC10", "XQC20"]
BO_SELECTIONS = {"NOSCAN35": (0.035, False), "SCAN35": (0.035, True), "SCAN5": (0.05, True)}
EP_ADR = {"A35": 0.035, "A5": 0.05}
PS_RUN = {"P50": 1.5, "P100": 2.0}
CANONICAL = ["QBO_STOP_SCAN35_M1_XQ3_10", "QEP_N1_A35_M1_XQ3_10", "QPS_P50_XQC10", "QCOMBO"]
MIN_SELECT_TRADES = 100
TRADE_KEYS = v7.TRADE_KEYS + ("avg_R",)


@dataclass(frozen=True)
class Trial:
    name: str
    group: str   # signals are built once per group (one shard each)
    signal: str  # key of the group's signal variants
    exit: str


def groups() -> list[str]:
    return ([f"QBO_{f}_{s}" for f in ("STOP", "CLOSE") for s in BO_SELECTIONS]
            + [f"QEP_{n}_{a}" for n in ("N0", "N1") for a in EP_ADR] + ["QPS", "QCOMBO"])


def trials() -> list[Trial]:
    out = [Trial(f"{g}_{m}_{x}", g, m, x) for g in groups() if g.startswith(("QBO", "QEP"))
           for m in ("M0", "M1") for x in LONG_EXITS]
    out += [Trial(f"QPS_{p}_{x}", "QPS", p, x) for p in PS_RUN for x in SHORT_EXITS]
    return out + [Trial("QCOMBO", "QCOMBO", "M1", "XQ3_10")]


def nasdaq_filter(nasdaq: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """SMA10 > SMA20 and both rising, as of the prior close."""
    idx = nasdaq.reindex(dates).ffill()
    s10, s20 = idx.rolling(10, min_periods=10).mean(), idx.rolling(20, min_periods=20).mean()
    on = (s10 > s20) & (s10 > s10.shift(1)) & (s20 > s20.shift(1))
    return on.shift(1, fill_value=False).astype(bool)


def context(panel: dict[str, pd.DataFrame], ind: dict, nasdaq: pd.Series) -> dict:
    C, V = panel["close"], panel["volume"]
    dv = (C * V).rolling(20, min_periods=20).mean()
    base = (C >= MIN_PRICE) & (dv >= MIN_DV) & (C.notna().cumsum() >= MIN_HISTORY)
    top = None
    for n in (21, 63, 126):
        hit = (C / C.shift(n) - 1).rank(axis=1, pct=True) >= TOP
        top = hit if top is None else (top | hit)
    return {"dv": dv, "base": base, "top": top, "m1": nasdaq_filter(nasdaq, C.index)}


def _market(entries: pd.DataFrame, ctx: dict, market: str) -> pd.DataFrame:
    return entries.mul(ctx["m1"], axis=0).astype(bool) if market == "M1" else entries


def breakout_setup(panel: dict, ind: dict, ctx: dict, adr_min: float, scan: bool):
    """Breakout conditions as of the prior close, and the pivot (10-session high)."""
    H, L, C = (panel[k] for k in ("high", "low", "close"))
    adr, s10, s20 = ind["adr"], ind["sma10"], ind["sma20"]
    elig = ctx["base"] & (adr >= adr_min)
    chosen = elig
    if scan:
        chosen = elig & ((elig & ctx["top"]).astype(float).rolling(WATCH_DAYS, min_periods=1).max() > 0)
    move = C / L.shift(1).rolling(63, min_periods=63).min()
    runup = move.shift(1).rolling(63, min_periods=1).max() >= 1.30
    hi5, lo5 = H.shift(1).rolling(5, min_periods=5).max(), L.shift(1).rolling(5, min_periods=5).min()
    base = ((hi5 - lo5) < (hi5.shift(5) - lo5.shift(5))) & (lo5 > lo5.shift(5))
    trend = ((s10 > s20) & (s20 > s20.shift(5)) & (C >= s20)).shift(1, fill_value=False)
    pivot = H.shift(1).rolling(10, min_periods=10).max()
    return chosen.shift(1, fill_value=False) & runup & base & trend, pivot


def breakout(panel: dict, ind: dict, ctx: dict, fill: str, adr_min: float, scan: bool):
    O, H, L, C = (panel[k] for k in ("open", "high", "low", "close"))
    setup, pivot = breakout_setup(panel, ind, ctx, adr_min, scan)
    prior_adr = ind["adr"].shift(1)
    if fill == "STOP":
        hit = setup & (H >= pivot)
        px = np.maximum(O, pivot).where(hit)
        stops = px * (1 - prior_adr)
        return hit & px.notna() & stops.notna(), stops, px
    risk = (C - L) / C
    return setup & (C > pivot) & (risk > 0) & (risk <= prior_adr), L, None


def episodic_gap(panel: dict, ind: dict, ctx: dict, adr_min: float, neglect: bool) -> pd.DataFrame:
    """Gap of 10%+ at the open in a stock eligible the day before (no volume test)."""
    O, C = panel["open"], panel["close"]
    gap = (O / C.shift(1) - 1 >= 0.10) & (ctx["base"] & (ind["adr"] >= adr_min)).shift(1, fill_value=False)
    return gap & (C.shift(1) / C.shift(127) - 1 < 0.30) if neglect else gap


def episodic(panel: dict, ind: dict, ctx: dict, adr_min: float, neglect: bool):
    L, C, V = (panel[k] for k in ("low", "close", "volume"))
    adr = ind["adr"]
    sig = episodic_gap(panel, ind, ctx, adr_min, neglect) & (V >= 3 * V.shift(1).rolling(20, min_periods=20).mean())
    risk = (C - L) / C
    return sig & (risk > 0) & (risk <= 1.5 * adr.shift(1)), L, None


def parabolic(panel: dict, ctx: dict, mult: float):
    O, H, L, C = (panel[k] for k in ("open", "high", "low", "close"))
    run = C.shift(1) >= mult * L.shift(1).rolling(10, min_periods=10).min()
    up3 = (C.shift(1) > C.shift(2)) & (C.shift(2) > C.shift(3)) & (C.shift(3) > C.shift(4))
    liquid = ((C >= MIN_PRICE) & (ctx["dv"] >= MIN_DV)).shift(1, fill_value=False)
    return run & up3 & (C < O) & (C < C.shift(1)) & liquid & (H > C), H, None


def build_group(group: str, panel: dict, ind: dict, ctx: dict) -> dict:
    """{signal key: (entries, stops, entry prices or None)} for one group."""
    if group.startswith("QBO"):
        _, fill, sel = group.split("_")
        e, s, px = breakout(panel, ind, ctx, fill, *BO_SELECTIONS[sel])
        return {m: (_market(e, ctx, m), s, px) for m in ("M0", "M1")}
    if group.startswith("QEP"):
        _, neg, a = group.split("_")
        e, s, px = episodic(panel, ind, ctx, EP_ADR[a], neg == "N1")
        return {m: (_market(e, ctx, m), s, px) for m in ("M0", "M1")}
    if group == "QPS":
        return {p: parabolic(panel, ctx, mult) for p, mult in PS_RUN.items()}
    be, bs, bpx = breakout(panel, ind, ctx, "STOP", *BO_SELECTIONS["SCAN35"])
    ee, es, _ = episodic(panel, ind, ctx, EP_ADR["A35"], True)
    be, ee = _market(be, ctx, "M1"), _market(ee, ctx, "M1")
    return {"M1": (be | ee, bs.where(be, es), bpx.where(be))}


def _row(t: Trial, daily: pd.Series, trades: pd.DataFrame, cash: pd.Series, signals: int) -> dict:
    row: dict = {"name": t.name, "group": t.group, "signal": t.signal, "exit": t.exit, "signals": signals}
    for p, (a, b) in v7.PERIODS.items():
        m = sc.metrics(daily.loc[a:b], cash)
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        ts = st.trade_stats(trades[(trades["entry_date"] >= a) & (trades["entry_date"] <= b)])
        row.update({f"{p}_tl_{k}": ts.get(k, np.nan) for k in TRADE_KEYS})
    done = trades[trades["entry_date"] <= sc.VALIDATION_END]
    row["stopped_entry_day"] = float((done["days"] == 0).mean()) if len(done) else np.nan
    row["median_risk"] = float(done["risk"].median()) if len(done) else np.nan
    wins = done[done["return"] > 0]
    row["median_win_days"] = float(wins["days"].median()) if len(wins) else np.nan
    return row


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G
    e, s, px = g["signals"][t.signal]
    side = -1 if t.group == "QPS" else 1
    d = sc.simulate(g["panel"], g["ind"], e, s, t.exit, g["cash"], g["rank"], side=side, entry_px=px)
    tl = st.trade_list(g["panel"], g["ind"], e, s, t.exit, side=side, entry_px=px)
    return _row(t, d["return"], tl, g["cash"], int(e.loc[sc.TRAIN_START:].to_numpy().sum()))


def run_shard(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series, nasdaq: pd.Series,
              cash_index: pd.Series, industry: pd.Series, shard: int, workers: int = 4) -> list[dict]:
    if panel["close"].index.max() >= sc.LOCKED_START or nasdaq.index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the Qullamaggie study")
    group = groups()[shard]
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry)
    ctx = context(panel, ind, nasdaq)
    signals = build_group(group, panel, ind, ctx)
    del ctx
    signals = {k: (e.fillna(False).astype(bool), s.astype(np.float32), None if px is None else px.astype(np.float32))
               for k, (e, s, px) in signals.items()}
    momentum = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True)
    todo = [t for t in trials() if t.group == group]
    _G.update(panel=panel, ind=ind, signals=signals, cash=cash, rank=momentum.fillna(0.0).astype(np.float32))
    if workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(workers) as pool:
            rows = list(pool.imap_unordered(_run_trial, todo))
    else:
        rows = [_run_trial(t) for t in todo]
    _G.clear()
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[sc.TRAIN_START:].fillna(0.0)
    spy_row: dict = {"name": "spy", "group": "SPY"}
    for p, (a, b) in v7.PERIODS.items():
        m = sc.metrics(spy.loc[a:b], cash)
        spy_row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
    return rows + [spy_row]


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    spy = rows[rows["name"] == "spy"].iloc[0].to_dict()
    df = rows[rows["name"] != "spy"].drop_duplicates("name").set_index("name")
    df = df.loc[[t.name for t in trials() if t.name in df.index]]
    pool = np.concatenate([df["validation_sharpe"].to_numpy(dtype=float), np.asarray(prior_sharpes, dtype=float)])
    df["deflated_sharpe"] = v7.deflated_sharpe(df["validation_sharpe"], pool, df["validation_days"],
                                               df["validation_skew"], df["validation_kurtosis"])
    spy_v = {"cagr": spy["validation_cagr"]}
    df["passed"] = [all(sc.criteria({"sortino_monthly": s, "cagr": c, "max_drawdown": d}, spy_v).values())
                    for s, c, d in zip(df["validation_sortino_monthly"], df["validation_cagr"],
                                       df["validation_max_drawdown"])]
    selected = {}
    for setup in ("QBO", "QEP", "QPS"):
        sub = df[df.index.str.startswith(setup) & (df["train_tl_trades"] >= MIN_SELECT_TRADES)]
        if len(sub):
            selected[setup] = sub["train_sortino_monthly"].idxmax()
    return {"df": df, "spy": spy, "selected": selected, "passed": list(df.index[df["passed"]]),
            "n_trials": int(np.isfinite(pool).sum()), "expected": len(trials())}

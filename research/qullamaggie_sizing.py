"""Qullamaggie phase 4: his real size, adding to winners, a profit cushion and
selling into strength, on the phase 3 portfolio (all intraday episodic pivots
plus the three best model-scored breakouts of the day, 2016-2020).
Pre-registered in docs/research/QULLAMAGGIE_SIZING_PREREGISTRATION.md (16 trials).
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import stock_trades as st

SIZES = {"S1": (0.0025, 0.10), "S2": (sc.RISK, sc.CAP)}
EXTENDED = 1.30  # sell a third at 30% above the SMA10
TOOLS = ("pyramid", "cushion", "strength")


@dataclass(frozen=True)
class Trial:
    name: str
    size: str
    pyramid: bool
    cushion: bool
    strength: bool


def trials() -> list[Trial]:
    return [Trial(f"SIZE_{s}_{p}_{c}_{x}", s, p == "P1", c == "C1", x == "X1")
            for s in SIZES for p in ("P0", "P1") for c in ("C0", "C1") for x in ("X0", "X1")]


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G
    e, s, px, sd = g["signals"]
    risk, cap = SIZES[t.size]
    trades: list[dict] = []
    d = sc.simulate(g["panel"], g["ind"], e, s, qw.EXIT, g["cash"], g["rank"], start=qi.START, entry_px=px,
                    same_day_px=sd, risk=risk, cap=cap, pyramid=t.pyramid, cushion=t.cushion,
                    extended_sell=EXTENDED if t.strength else None, trades=trades)
    row: dict = {"name": t.name, "size": t.size, "pyramid": t.pyramid, "cushion": t.cushion, "strength": t.strength,
                 "best5_captured": qw._captured(g["all_trades"], trades, g["panel"]["close"].columns)}
    tl = g["all_trades"]
    for p, (a, b) in qi.PERIODS.items():
        m = sc.metrics(d["return"].loc[a:b], g["cash"])
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        row[f"{p}_total"] = float((1 + d["return"].loc[a:b]).prod() - 1)
        ts = st.trade_stats(tl[(tl["entry_date"] >= a) & (tl["entry_date"] <= b)])
        row.update({f"{p}_tl_{k}": ts.get(k, np.nan) for k in q.TRADE_KEYS})
    row["max_invested"] = float(d["invested"].max())
    return row


def run(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series, nasdaq: pd.Series,
        cash_index: pd.Series, industry: pd.Series, load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
        alp_daily: dict[str, pd.DataFrame], workers: int = 4) -> tuple[list[dict], dict]:
    if panel["close"].index.max() >= sc.LOCKED_START or nasdaq.index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the Qullamaggie sizing study")
    ind = sc.indicators(panel, index_close, industry)
    ctx = q.context(panel, ind, nasdaq)
    kept, info = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    prep = qi.prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    del ctx
    _, _, mix = qs.intraday_signals(prep, kept[("MODEL", 3)])
    del kept
    all_trades = st.trade_list(prep["panel"], prep["ind"], mix[0], mix[1], qw.EXIT, start=qi.START, entry_px=mix[2],
                               same_day_px=mix[3])
    _G.update(panel=prep["panel"], ind=prep["ind"], cash=prep["cash"], rank=prep["rank"], signals=mix,
              all_trades=all_trades)
    todo = trials()
    if workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(workers) as pool:
            rows = list(pool.imap_unordered(_run_trial, todo))
    else:
        rows = [_run_trial(t) for t in todo]
    dates = prep["panel"]["close"].index
    _G.clear()
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    spy_row: dict = {"name": "spy"}
    for p, (a, b) in qi.PERIODS.items():
        m = sc.metrics(spy.loc[a:b], prep["cash"])
        spy_row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        spy_row[f"{p}_total"] = float((1 + spy.loc[a:b]).prod() - 1)
    info["intraday"] = prep["info"]
    return rows + [spy_row], info


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    spy = rows[rows["name"] == "spy"].iloc[0].to_dict()
    df = rows[rows["name"] != "spy"].set_index("name")
    df = df.loc[[t.name for t in trials() if t.name in df.index]].copy()
    pool = np.concatenate([df["all_sharpe"].to_numpy(dtype=float), np.asarray(prior_sharpes, dtype=float)])
    df["deflated_sharpe"] = v7.deflated_sharpe(df["all_sharpe"], pool, df["all_days"], df["all_skew"],
                                               df["all_kurtosis"])
    df["passed"] = [all(sc.criteria({"sortino_monthly": s, "cagr": c, "max_drawdown": d},
                                    {"cagr": spy["all_cagr"]}).values())
                    for s, c, d in zip(df["all_sortino_monthly"], df["all_cagr"], df["all_max_drawdown"])]
    effects = {}
    for tool in TOOLS + ("size",):
        on = (df["size"] == "S1") if tool == "size" else df[tool].astype(bool)
        effects["S1 (his size)" if tool == "size" else tool] = {
            k: float(df.loc[on, k].mean() - df.loc[~on, k].mean())
            for k in ("all_sortino_monthly", "all_cagr", "all_max_drawdown", "p1_cagr", "p2_cagr")}
    return {"df": df, "spy": spy, "passed": list(df.index[df["passed"]]), "effects": effects,
            "n_trials": int(np.isfinite(pool).sum()), "expected": len(trials())}

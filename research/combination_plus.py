"""Phases 7b and 7c: the five new intraday streams alone, all 13 streams combined,
and constant leverage. Pre-registered in docs/research/COMBINATION_PLUS_PREREGISTRATION.md (18 trials).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import combination as cb
from aurora.research import intraday_more as im
from aurora.research import qullamaggie_intraday as qi
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7

STREAMS_7A = Path("docs/research/data/combination_streams_7a.csv")
SETS = {"INTRA8": cb.INTRADAY + im.NEW, "ALL13": cb.INTRADAY + im.NEW + cb.DAILY}
LEVERAGE = (1.5, 2.0, 3.0)
LEVERED = ("INTRADAY_EQ", "INTRA8_EQ", "ALL13_EQ")
PERIODS = {"p1": (qi.START, pd.Timestamp("2018-12-31")), "p2": (pd.Timestamp("2019-01-01"), qi.END),
           "all": (qi.START, qi.END)}


def trials() -> list[str]:
    combos = [f"{s}_{m}" for s in SETS for m in ("EQ", "RP")]
    return im.NEW + combos + [f"{c}_L{lev:g}" for c in LEVERED for lev in LEVERAGE]


def load_7a(path: Path = STREAMS_7A) -> pd.DataFrame:
    return pd.read_csv(path, index_col=0, parse_dates=True)


def leverage(r: pd.Series, cash: pd.Series, lev: float) -> pd.Series:
    """Account-level leverage: the excess return scaled, the borrowed part paying T-bills + the spread."""
    return cash + lev * (r - cash) - (lev - 1) * cb.SPREAD / sc.PPY


def results(streams: pd.DataFrame, spy: pd.Series, cash: pd.Series) -> tuple[list[dict], pd.DataFrame]:
    S = streams.loc[qi.START:qi.END].fillna(0.0)
    c, sp = cash.loc[qi.START:qi.END], spy.loc[qi.START:qi.END]
    rows: list[dict] = []
    for name in im.NEW:
        rows.append({"name": name, "kind": "stream", **cb.evaluate(S[name], c, PERIODS)})
    combos = {"INTRADAY_EQ": cb.combine(S[cb.INTRADAY], "EQ", sp, c)}
    for s, members in SETS.items():
        for m in ("EQ", "RP"):
            combos[f"{s}_{m}"] = cb.combine(S[members], m, sp, c)
            rows.append({"name": f"{s}_{m}", "kind": "combination", **cb.evaluate(combos[f"{s}_{m}"], c, PERIODS)})
    for base in LEVERED:
        for lev in LEVERAGE:
            rows.append({"name": f"{base}_L{lev:g}", "kind": "leverage",
                         **cb.evaluate(leverage(combos[base], c, lev), c, PERIODS)})
    rows.append({"name": "INTRADAY_EQ", "kind": "reference", **cb.evaluate(combos["INTRADAY_EQ"], c, PERIODS)})
    rows.append({"name": "SPY", "kind": "benchmark", **cb.evaluate(sp, c, PERIODS)})
    monthly = (1 + pd.concat([S, sp.rename("SPY")], axis=1)).groupby(S.index.to_period("M")).prod() - 1
    return rows, monthly.corr()


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    df = rows.set_index("name")
    tri = df.loc[[n for n in trials() if n in df.index]].copy()
    spy = df.loc["SPY"]
    pool = np.concatenate([tri["all_sharpe"].to_numpy(dtype=float), np.asarray(prior_sharpes, dtype=float)])
    tri["deflated_sharpe"] = v7.deflated_sharpe(tri["all_sharpe"], pool, tri["all_days"], tri["all_skew"],
                                                tri["all_kurtosis"])
    tri["passed"] = [all(sc.criteria({"sortino_monthly": s, "cagr": c, "max_drawdown": d},
                                     {"cagr": spy["all_cagr"]}).values())
                     for s, c, d in zip(tri["all_sortino_monthly"], tri["all_cagr"], tri["all_max_drawdown"])]
    return {"df": tri, "reference": df.loc["INTRADAY_EQ"], "spy": spy, "passed": list(tri.index[tri["passed"]]),
            "n_trials": int(np.isfinite(pool).sum()), "expected": len(trials())}

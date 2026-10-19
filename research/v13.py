"""v13: an honest estimate without overfitting. Pre-registered in docs/research/V13_PREREGISTRATION.md.

144 configurations fixed in advance, yearly walk-forward selection by plateau score, combinatorial cross-validation
with the probability of backtest overfitting, and walk-forward diversification.
"""
from __future__ import annotations

from itertools import combinations, product

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import v10

LAST = v10.LAST
START = pd.Timestamp("2016-01-04")
WF_YEARS = tuple(range(2018, 2027))
DIMS = {"set": ("MIX1", "MIX3", "EP_N1"), "exit": ("XQ3_20", "XQ5_20"), "regime": ("M1", "N50", "M1_N50"),
        "risk": (0.005, 0.01), "cap": (0.20, 0.35), "max_pos": (0, 8)}
N_BLOCKS, ENS_K, DIV_MIN = 10, 5, 1.5
SORTINO_CAP = 20.0  # a stretch without a losing month scores 20 instead of infinity


def grid() -> list[dict]:
    return [dict(zip(DIMS, v)) for v in product(*DIMS.values())]


def cname(g: dict) -> str:
    return (f"V13_{g['set']}_{g['exit']}_{g['regime']}_R{g['risk'] * 100:g}_C{g['cap'] * 100:g}_M{g['max_pos']}")


def neighbours(cfgs: list[dict]) -> list[list[int]]:
    """For each configuration, itself and every configuration that differs in exactly one dimension."""
    keys = [tuple(g.values()) for g in cfgs]
    out = []
    for k in keys:
        out.append([j for j, o in enumerate(keys) if sum(a != b for a, b in zip(k, o)) <= 1])
    return out


def lt_neighbours(names: list[str]) -> list[list[int]]:
    parts = [n.split("_") for n in names]
    out = []
    for p in parts:
        out.append([j for j, o in enumerate(parts) if len(o) == len(p) and sum(a != b for a, b in zip(p, o)) <= 1])
    return out


# ---------------------------------------------------------------- monthly matrices

def monthly(R: pd.DataFrame) -> pd.DataFrame:
    return (1 + R.fillna(0.0)).groupby(R.index.to_period("M")).prod() - 1


def sortino_cols(M: np.ndarray, cash_m: np.ndarray) -> np.ndarray:
    """Monthly Sortino of each column (the published convention), months in rows."""
    ex = M - cash_m[:, None]
    n = ex.shape[0]
    if n < 6:
        return np.full(M.shape[1], np.nan)
    dn = np.sqrt(np.sum(np.minimum(ex, 0.0) ** 2, axis=0) / (n - 1))
    mean = ex.mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(dn > 0, mean / dn * np.sqrt(12), np.where(mean > 0, SORTINO_CAP, 0.0))
    return np.minimum(s, SORTINO_CAP)


def score(M: np.ndarray, cash_m: np.ndarray) -> np.ndarray:
    """The smaller Sortino of the two halves of the rows."""
    h = M.shape[0] // 2
    s1, s2 = sortino_cols(M[:h], cash_m[:h]), sortino_cols(M[h:], cash_m[h:])
    return np.minimum(s1, s2)


def plateau(s: np.ndarray, nb: list[list[int]]) -> np.ndarray:
    return np.array([np.nanmean(s[ix]) if np.isfinite(s[ix]).any() else np.nan for ix in nb])


# ---------------------------------------------------------------- walk-forward

def walk_forward(R: pd.DataFrame, cash: pd.Series, nb: list[list[int]], k: int = ENS_K) -> dict:
    """Yearly re-selection on data before each year; returns the stitched daily records and the choices."""
    Mo = monthly(R)
    cm = monthly(cash.reindex(R.index).fillna(0.0).to_frame("c"))["c"]
    one, ens, picks = [], [], {}
    for y in WF_YEARS:
        train = Mo.index[(Mo.index >= pd.Period("2016-01", "M")) & (Mo.index < pd.Period(f"{y}-01", "M"))]
        s = plateau(score(Mo.loc[train].to_numpy(), cm.loc[train].to_numpy()), nb)
        order = [i for i in np.argsort(-np.nan_to_num(s, nan=-1e9)) if np.isfinite(s[i])]
        if not order:
            continue
        top = [R.columns[i] for i in order[:k]]
        picks[y] = {"one": top[0], "ens": top, "score": float(s[order[0]])}
        yr = R.loc[str(y)]
        one.append(yr[top[0]])
        ens.append(yr[top].mean(axis=1))
    return {"one": pd.concat(one), "ens": pd.concat(ens), "picks": picks}


def wf_family(R: pd.DataFrame, cash: pd.Series, nb: list[list[int]]) -> dict[int, tuple[str, float]]:
    """Best plateau score per year for a diversifier family."""
    Mo = monthly(R)
    cm = monthly(cash.reindex(R.index).fillna(0.0).to_frame("c"))["c"]
    out = {}
    for y in WF_YEARS:
        train = Mo.index[(Mo.index >= pd.Period("2016-01", "M")) & (Mo.index < pd.Period(f"{y}-01", "M"))]
        s = plateau(score(Mo.loc[train].to_numpy(), cm.loc[train].to_numpy()), nb)
        if np.isfinite(s).any():
            i = int(np.nanargmax(s))
            out[y] = (R.columns[i], float(s[i]))
    return out


def wf_div(R: pd.DataFrame, wf: dict, extras: list[tuple[pd.DataFrame, dict]]) -> pd.Series:
    """WF_ENS5 plus each diversifier family's yearly pick (if its score >= DIV_MIN), inverse-volatility weights from
    the 252 sessions before each year."""
    out = []
    for y in WF_YEARS:
        if y not in wf["picks"]:
            continue
        members = {"ENS": R[wf["picks"][y]["ens"]].mean(axis=1)}
        for fam_R, picks in extras:
            if y in picks and picks[y][1] >= DIV_MIN:
                members[picks[y][0]] = fam_R[picks[y][0]].reindex(R.index)
        M = pd.DataFrame(members)
        hist = M.loc[:f"{y - 1}-12-31"].tail(252)
        vol = hist.std().replace(0, np.nan)
        w = (1 / vol).fillna(0.0)
        w = w / w.sum() if w.sum() > 0 else pd.Series(1 / len(M.columns), index=M.columns)
        out.append((M.loc[str(y)].fillna(0.0) * w).sum(axis=1))
    return pd.concat(out)


# ---------------------------------------------------------------- CPCV and PBO

def cpcv(R: pd.DataFrame, cash: pd.Series, nb: list[list[int]]) -> dict:
    Mo = monthly(R.loc[START:LAST])
    cm = monthly(cash.reindex(R.loc[START:LAST].index).fillna(0.0).to_frame("c"))["c"].to_numpy()
    M = Mo.to_numpy()
    blocks = np.array_split(np.arange(len(M)), N_BLOCKS)
    test_s, ranks = [], []
    for tr in combinations(range(N_BLOCKS), N_BLOCKS // 2):
        tr_rows = np.concatenate([blocks[b] for b in tr])
        te_rows = np.concatenate([blocks[b] for b in range(N_BLOCKS) if b not in tr])
        s = plateau(score(M[tr_rows], cm[tr_rows]), nb)
        if not np.isfinite(s).any():
            continue
        i = int(np.nanargmax(s))
        te = sortino_cols(M[te_rows], cm[te_rows])
        te = np.where(np.isfinite(te), te, np.nan)
        valid = te[np.isfinite(te)]
        test_s.append(float(te[i]))
        ranks.append(float((valid < te[i]).sum() + 0.5 * (valid == te[i]).sum()) / len(valid))
    ranks_a, test_a = np.array(ranks), np.array(test_s)
    return {"splits": len(ranks_a), "pbo": float((ranks_a < 0.5).mean()), "test_median": float(np.nanmedian(test_a)),
            "test_p10": float(np.nanpercentile(test_a, 10)), "test_p90": float(np.nanpercentile(test_a, 90)),
            "share_test_ge4": float((test_a >= 4).mean())}


# ---------------------------------------------------------------- metrics

def stats(r: pd.Series, cash: pd.Series) -> dict:
    out = {}
    for p, (a, b) in {"wf": ("2018-01-01", LAST), "h1": ("2018-01-01", "2021-12-31"),
                      "h2": ("2022-01-01", LAST)}.items():
        x = r.loc[a:b].dropna()
        m = sc.metrics(x, cash)
        total = float((1 + x).prod() - 1)
        years = (x.index[-1] - x.index[0]).days / 365.25
        out.update({f"{p}_sortino": m.get("sortino_monthly"), f"{p}_cagr": (1 + total) ** (1 / years) - 1,
                    f"{p}_dd": m.get("max_drawdown"), f"{p}_total": total})
    x = r.loc["2018-01-01":LAST].dropna()
    out["yearly"] = {int(y): float(v) for y, v in ((1 + x).groupby(x.index.year).prod() - 1).items()}
    return out

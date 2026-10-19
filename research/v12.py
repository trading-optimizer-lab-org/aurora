"""v12: everything that could raise the Sortino of the intraday book. Pre-registered in
docs/research/V12_PREREGISTRATION.md. Base configurations are numbered and decoded on the fly.
"""
from __future__ import annotations

from math import prod

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import v10

LAST = v10.LAST
DIMS = {"set": ("MIX3", "MIX1", "MIXS3", "EP_N1", "EP_N0", "EP_EARN", "EP_NEWS", "BO_ALL", "ALL", "EP_CLOSE"),
        "exit": ("XQ3_20", "XQ5_20", "XQ3_10", "XQ1_20", "XQC20", "XG10_50_20_3", "XN1_2_20_0", "XN1_3_20_0",
                 "XN2_4_20_0", "XN1_2_20_5"),
        "regime": ("NONE", "M1", "NEMA", "N20", "N50", "M1_N50", "BR50", "NHNL", "VIX25", "M1_BR50"),
        "gapmin": (0.10, 0.15, 0.20), "rs": (0.0, 0.70, 0.90), "fresh": (False, True), "risk": (0.005, 0.01, 0.015),
        "cap": (0.20, 0.35), "max_pos": (0, 8, 12), "heat": (0.0, 0.04, 0.06), "sector": (0, 2)}
N_BASE = prod(len(v) for v in DIMS.values())
OVERLAYS = ("NONE", "EQ20", "EQ50", "DDH10", "DD15OFF")
HEDGES = (0.0, 0.5, 1.0)
SHARDS, TOP_PER_SHARD = 320, 1000
_T = pd.Timestamp
PERIODS = {"h1": (_T("2016-01-04"), _T("2018-12-31")), "h2": (_T("2019-01-01"), _T("2020-12-31")),
           "design": (_T("2016-01-04"), _T("2020-12-31")), "judge": (_T("2021-01-01"), LAST),
           "j1": (_T("2021-01-01"), _T("2023-12-31")), "j2": (_T("2024-01-01"), LAST)}
HIST_EDGES = np.linspace(-5, 15, 81)


def cfg(i: int) -> dict:
    vals = []
    for d in reversed(list(DIMS.values())):
        i, k = divmod(i, len(d))
        vals.append(d[k])
    return dict(zip(DIMS, reversed(vals)))


def name(g: dict, ov: str, h: float) -> str:
    return (f"Q12_{g['set']}_{g['exit']}_{g['regime']}_G{g['gapmin'] * 100:g}_RS{g['rs'] * 100:g}_F{int(g['fresh'])}"
            f"_R{g['risk'] * 100:g}_C{g['cap'] * 100:g}_M{g['max_pos']}_H{g['heat'] * 100:g}_S{g['sector']}_{ov}"
            f"_HG{h * 100:g}")


# ---------------------------------------------------------------- fast monthly metrics

def metric_plan(dates: pd.DatetimeIndex, cash: np.ndarray) -> dict:
    """Index ranges, month codes and monthly cash per period, computed once."""
    plan = {}
    for p, (a, b) in PERIODS.items():
        lo, hi = int(dates.searchsorted(a)), int(dates.searchsorted(b, side="right"))
        months = dates[lo:hi].to_period("M")
        codes = pd.factorize(months)[0]
        cm = np.expm1(np.bincount(codes, weights=np.log1p(cash[lo:hi])))
        plan[p] = (lo, hi, codes, cm, (dates[hi - 1] - dates[lo]).days / 365.25)
    return plan


def fast_metrics(r: np.ndarray, cash: np.ndarray, plan: dict) -> dict:
    """Monthly Sortino (the published convention) per period; CAGR, drawdown and Sharpe for the judgment."""
    out = {}
    lr = np.log1p(np.clip(r, -0.999999, None))
    for p, (lo, hi, codes, cm, years) in plan.items():
        m = np.expm1(np.bincount(codes, weights=lr[lo:hi]))
        ex = m - cm
        if len(ex) < 6:
            out[f"{p}_sortino"] = np.nan
            continue
        dn = np.sqrt(np.sum(np.minimum(ex, 0.0) ** 2) / (len(ex) - 1))
        out[f"{p}_sortino"] = float(ex.mean() / dn * np.sqrt(12)) if dn > 0 else (np.inf if ex.mean() > 0 else 0.0)
        if p in ("design", "judge"):
            eq = np.exp(np.cumsum(lr[lo:hi]))
            out[f"{p}_cagr"] = float(eq[-1] ** (1 / years) - 1) if years > 0 else np.nan
            out[f"{p}_dd"] = float((eq / np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:] - 1).min())
            d = r[lo:hi] - cash[lo:hi]
            out[f"{p}_sharpe"] = float(d.mean() / d.std(ddof=1) * np.sqrt(sc.PPY)) if d.std(ddof=1) > 0 else np.nan
    s1, s2 = out.get("h1_sortino", np.nan), out.get("h2_sortino", np.nan)
    out["robust"] = min(s1, s2) if np.isfinite(s1) and np.isfinite(s2) else np.nan
    return out


# ---------------------------------------------------------------- one base configuration

def entry_mask(g: dict, G: dict, X: dict) -> np.ndarray:
    m = G["sig"][g["set"]][0] & X["regime"][g["regime"]][:, None]
    if g["gapmin"] > 0.10:
        m = m & (~X["gap_ep"] | (X["gap"] >= g["gapmin"]))
    if g["rs"] > 0:
        m = m & (X["rs_prior"] >= g["rs"])
    if g["fresh"]:
        m = m & (~X["gap_ep"] | X["fresh"])
    return m


def overlay_scales(r: pd.Series) -> dict[str, pd.Series]:
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    return {"EQ20": (eq >= eq.rolling(20, min_periods=20).mean()).astype(float).shift(1).fillna(1.0),
            "EQ50": (eq >= eq.rolling(50, min_periods=50).mean()).astype(float).shift(1).fillna(1.0),
            "DDH10": pd.Series(np.where(dd < -0.10, 0.5, 1.0), index=r.index).shift(1).fillna(1.0),
            "DD15OFF": pd.Series(np.where(dd < -0.15, 0.0, 1.0), index=r.index).shift(1).fillna(1.0)}


def runs(i: int, G: dict, X: dict, overlays: tuple = OVERLAYS, trades: list | None = None) -> dict:
    """{overlay: (returns, invested)} for base configuration i."""
    g = cfg(i)
    _, s, px, sd = G["sig"][g["set"]]
    idx, cols = G["dates"], G["cols"]

    def df(a: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(a, index=idx, columns=cols)

    kw = dict(risk=g["risk"], cap=g["cap"], max_gross=G["gross"][1.0], max_pos=g["max_pos"] or None,
              max_heat=g["heat"] or None, groups=X["groups"] if g["sector"] else None,
              max_per_group=g["sector"] or None)
    args = (G["panel"], G["ind"], df(entry_mask(g, G, X)), df(s), g["exit"], G["cash"], G["rank"]["RS63"])
    d0 = sc.simulate(*args, start=v10.QB_START, entry_px=df(px), same_day_px=df(sd), trades=trades, **kw)
    out = {"NONE": (d0["return"], d0["invested"])}
    scales = overlay_scales(d0["return"]) if len(overlays) > 1 else {}
    for ov in overlays:
        if ov != "NONE":
            d = sc.simulate(*args, start=v10.QB_START, entry_px=df(px), same_day_px=df(sd), risk_scale=scales[ov], **kw)
            out[ov] = (d["return"], d["invested"])
    return out


def hedge(r: pd.Series, inv: pd.Series, h: float, qqq: pd.Series, cash: pd.Series) -> pd.Series:
    if h == 0:
        return r
    q = qqq.reindex(r.index).fillna(0.0)
    c = cash.reindex(r.index).fillna(0.0)
    return r - h * inv.shift(1).fillna(0.0) * (q - c)


def evaluate_base(i: int, G: dict, X: dict) -> list[dict]:
    rows = []
    for ov, (r, inv) in runs(i, G, X).items():
        for k, h in enumerate(HEDGES):
            rh = hedge(r, inv, h, X["qqq"], G["cash"])
            full = rh.reindex(G["dates"]).fillna(0.0).to_numpy()
            m = fast_metrics(full, X["cash_np"], X["plan"])
            rows.append({"id": i, "ov": OVERLAYS.index(ov), "hg": k, **m})
    return rows

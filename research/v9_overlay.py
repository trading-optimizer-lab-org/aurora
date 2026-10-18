"""v9 family 20 (loss brake on the phase 7 streams), the pre-registered
selection of one variant per family, the final combinations and the summary.
Pre-registered in docs/research/V9_PREREGISTRATION.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from aurora.research import combination as cb
from aurora.research import combination_plus as cp
from aurora.research import intraday_more as im
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import v9_common as c

STREAMS_7B = Path("docs/research/data/combination_streams_7b.csv")
BRAKE_COST = 0.001
ROLL_DAYS, ROLL_OFF = 21, 5
QUALIFY = 1.0
LEVERAGE = (1, 2, 3, 5)
PHASE7_DAILY = list(cb.DAILY)
PHASE7_INTRA = list(cb.INTRADAY) + list(im.NEW)


def phase7_streams() -> pd.DataFrame:
    return pd.concat([cp.load_7a(), pd.read_csv(STREAMS_7B, index_col=0, parse_dates=True)], axis=1).sort_index()


def brake_bases(S: pd.DataFrame) -> dict[str, pd.Series]:
    intra = S.loc[c.INTRA_START:c.INTRA_END]
    return {"INTRADAY_EQ": intra[cb.INTRADAY].fillna(0.0).mean(axis=1),
            "ALL13_EQ": intra[PHASE7_INTRA + PHASE7_DAILY].fillna(0.0).mean(axis=1),
            "EP_EARN": intra["EP_EARN"], "EP_NEWS": intra["EP_NEWS"], "BO_TOP3": intra["BO_TOP3"],
            "DAILY_RP": cb.risk_parity(S.loc[sc.TRAIN_START:sc.VALIDATION_END, PHASE7_DAILY].fillna(0.0))}


def brake(r: pd.Series, cash: pd.Series, mode: str, pct: float) -> pd.Series:
    """Cash after a loss of ``pct`` percent: month to date (until the month ends) or over the trailing 21 sessions
    (for the next 5 sessions); each trigger costs 10 bps."""
    r = r.dropna()
    vals, cv = r.to_numpy(), cash.reindex(r.index).fillna(0.0).to_numpy()
    out = vals.copy()
    thr = -pct / 100
    if mode == "MONTH":
        month = r.index.to_period("M")
        mtd, off = 1.0, False
        for i in range(len(vals)):
            if i and month[i] != month[i - 1]:
                mtd, off = 1.0, False
            if off:
                out[i] = cv[i]
                continue
            mtd *= 1 + vals[i]
            if mtd - 1 <= thr:
                off = True
                out[i] -= BRAKE_COST
    else:
        trail = (1 + r).rolling(ROLL_DAYS, min_periods=ROLL_DAYS).apply(np.prod, raw=True).to_numpy() - 1
        left = 0
        for i in range(len(vals)):
            if left:
                out[i] = cv[i]
                left -= 1
            elif trail[i] <= thr:
                out[i] -= BRAKE_COST
                left = ROLL_OFF
    return pd.Series(out, index=r.index)


def brake_trial(t: dict, bases: dict[str, pd.Series], cash: pd.Series) -> dict:
    return {0: brake(bases[t["B"]], cash, t["M"], float(t["X"]))}


# ---------------------------------------------------------------- selection and combination

def picks(rows: pd.DataFrame) -> pd.DataFrame:
    """Per family, the variant with the best monthly Sortino in its selection period (judgment never used)."""
    out = []
    for fam, g in rows[rows["family"] != "BRAKE"].groupby("family", sort=False):
        kind = g["kind"].iloc[0]
        col = f"{c.SELECT[kind]}_sortino_monthly"
        if col not in g.columns:
            continue
        g = g[np.isfinite(g[col].astype(float))]
        if len(g):
            best = g.loc[g[col].astype(float).idxmax()]
            out.append({"family": fam, "name": best["name"], "kind": kind, "select_sortino": float(best[col]),
                        "qualifies": bool(best[col] >= QUALIFY)})
    return pd.DataFrame(out)


def rp_available(R: pd.DataFrame) -> pd.Series:
    """Risk parity as in phase 7 (1 / prior 126-session volatility floored at 2% a year, reset monthly), over the
    members that are trading that day; members still without a volatility are left out. Each member's volatility
    uses its own sessions, so a missing day does not blank its window."""
    vol = pd.concat({k: R[k].dropna().rolling(cb.RP_LOOKBACK, min_periods=cb.RP_LOOKBACK).std().shift(1)
                     for k in R.columns}, axis=1).reindex(R.index).ffill()  # each member over its own sessions
    vol = vol.reindex(columns=R.columns).clip(lower=cb.VOL_FLOOR / np.sqrt(sc.PPY))
    starts = pd.DataFrame(np.broadcast_to(cb._month_starts(R.index)[:, None], R.shape), index=R.index, columns=R.columns)
    inv = (1 / vol).where(starts).ffill().where(R.notna())
    w = inv.div(inv.sum(axis=1), axis=0)
    eq = R.notna().astype(float).div(R.notna().sum(axis=1).replace(0, np.nan), axis=0)
    w = w.where(inv.notna().any(axis=1), eq, axis=0)
    return (R.fillna(0.0) * w.fillna(0.0)).sum(axis=1)


def combos(series: pd.DataFrame, rows: pd.DataFrame, phase7: pd.DataFrame, cash: pd.Series) -> tuple[dict, dict]:
    """The 18 combination trials and their members."""
    pk = picks(rows)
    p7 = {}
    for n in PHASE7_DAILY:
        p7[n] = ("daily", c.evaluate(phase7[n], cash, c.PERIODS["daily"]).get("train_sortino_monthly", np.nan))
    for n in PHASE7_INTRA:
        p7[n] = ("intraday", c.evaluate(phase7[n], cash, c.PERIODS["intraday"]).get("p1_sortino_monthly", np.nan))
    q = pk[pk["qualifies"]]
    daily_members = list(q.loc[q["kind"] == "daily", "name"])
    intra_members = list(q.loc[q["kind"] == "intraday", "name"])
    p7_daily = [n for n, (k, s) in p7.items() if k == "daily" and s >= QUALIFY]
    p7_intra = [n for n, (k, s) in p7.items() if k == "intraday" and s >= QUALIFY]
    sets = {"DAILY": (pd.concat([series[daily_members], phase7[p7_daily]], axis=1)
                      .loc[sc.TRAIN_START:sc.VALIDATION_END], "daily"),
            "ALL": (pd.concat([series[daily_members + intra_members], phase7[p7_daily + p7_intra]], axis=1)
                    .loc[c.INTRA_START:c.INTRA_END], "intraday")}
    out: dict[str, tuple[pd.Series, str]] = {}
    for s, (R, kind) in sets.items():
        if R.shape[1] == 0:
            continue
        R = R.astype(float)  # an empty pick frame would otherwise leave object columns (risk parity then fails)
        base = {"EQ": R.mean(axis=1), "RP": rp_available(R)}
        for m, r in base.items():
            r = r.where(R.notna().any(axis=1))
            for lev in LEVERAGE:
                out[f"COMBO_{s}_{m}_L{lev}"] = (cp.leverage(r, cash.reindex(r.index).fillna(0.0), lev), kind)
        out[f"COMBO_{s}_RP_BRK"] = (brake(base["RP"].where(R.notna().any(axis=1)), cash, "MONTH", 1.0), kind)
    members = {"picks": pk, "phase7_selection_sortino": {n: s for n, (_, s) in p7.items()},
               "DAILY": daily_members + p7_daily, "ALL": daily_members + intra_members + p7_daily + p7_intra}
    return out, members


def finish(rows: pd.DataFrame, spy: pd.Series, cash: pd.Series, prior_sharpes: list[float]) -> pd.DataFrame:
    """Deflated Sharpe over all v9 trials plus the earlier ones, and the pass criteria on the judgment period."""
    df = rows.set_index("name")
    spy_rows = {k: c.evaluate(spy, cash, c.PERIODS[k]) for k in c.PERIODS}
    pick = {f: np.array([df.at[n, f"{c.DSR_PERIOD[k]}_{f}"] if f"{c.DSR_PERIOD[k]}_{f}" in df.columns else np.nan
                         for n, k in zip(df.index, df["kind"])], dtype=float)
            for f in ("sharpe", "days", "skew", "kurtosis")}
    pool = np.concatenate([pick["sharpe"], np.asarray(prior_sharpes, dtype=float)])
    df["deflated_sharpe"] = v7.deflated_sharpe(pick["sharpe"], pool, pick["days"], pick["skew"], pick["kurtosis"])
    passed, ten = [], []
    for n, r in df.iterrows():
        p = c.JUDGE[r["kind"]]
        s = r.get(f"{p}_sortino_monthly", np.nan)
        v = {"sortino_monthly": s, "cagr": r.get(f"{p}_cagr", np.nan), "max_drawdown": r.get(f"{p}_max_drawdown", np.nan)}
        ok = all(np.isfinite(float(x)) for x in v.values())
        passed.append(ok and all(sc.criteria(v, {"cagr": spy_rows[r["kind"]][f"{p}_cagr"]}).values()))
        ten.append(bool(np.isfinite(float(s)) and s >= 10))
    df["passed"], df["sortino10"] = passed, ten
    df.attrs["n_trials"] = int(np.isfinite(pool).sum())
    df.attrs["spy"] = spy_rows
    return df

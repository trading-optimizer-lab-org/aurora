"""v11: a Sortino-first combination of independent strategies. Pre-registered in
docs/research/V11_PREREGISTRATION.md. Reuses v10's inputs, engine and families and v9's ETF families.
"""
from __future__ import annotations

from math import prod

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v5 as v5
from aurora.research import v9_common as c9
from aurora.research import v9_etf as vf
from aurora.research import v10

LAST = v10.LAST
COMBO = (pd.Timestamp("2016-01-04"), pd.Timestamp("2020-12-31"))
JUDGE = (pd.Timestamp("2021-01-01"), LAST)
_T = pd.Timestamp
HALVES = {"QB": ((_T("2016-01-04"), _T("2018-12-31")), (_T("2019-01-01"), _T("2020-12-31"))),
          "CT": ((_T("2016-01-01"), _T("2018-12-31")), (_T("2019-01-01"), _T("2020-12-31"))),
          "LT": ((_T("2000-01-01"), _T("2010-12-31")), (_T("2011-01-01"), _T("2020-12-31"))),
          "MR": ((_T("1995-01-01"), _T("2007-12-31")), (_T("2008-01-01"), _T("2020-12-31")))}
for _f in ("TSMOM", "XSETF", "SEASON"):
    HALVES[_f] = HALVES["LT"]
QB_DIMS = {**v10.QB_DIMS, "risk": (0.005, 0.01), "cap": (0.20, 0.35), "gross": (1.0,)}
QB_N = prod(len(v) for v in QB_DIMS.values())
SHORTLIST = {"QB": 30, "LT": 10, "MR": 10, "TSMOM": 5, "XSETF": 5, "SEASON": 5}
QB_PER_SET, MAX_STREAMS, MIN_GAIN = 6, 12, 0.05
ETF_FAMILIES = ("TSMOM", "XSETF", "SEASON")


def qb_cfg(i: int) -> dict:
    vals = []
    for d in reversed(list(QB_DIMS.values())):
        i, k = divmod(i, len(d))
        vals.append(d[k])
    return dict(zip(QB_DIMS, reversed(vals)))


def other_trials() -> list[dict]:
    etf = [{**t, "family": t["family"]} for t in c9.trials() if t["family"] in ETF_FAMILIES]
    return v10.other_trials() + etf


def shard_items(shard: int) -> tuple[str, list]:
    if shard < v10.QB_SHARDS:
        return "QB", list(range(shard, QB_N, v10.QB_SHARDS))
    return "OTHER", other_trials()[shard - v10.QB_SHARDS::v10.OTHER_SHARDS]


def _sortino(x: pd.Series, cash: pd.Series) -> float:
    x = x.dropna()
    if len(x) < 60:
        return np.nan
    v = sc.metrics(x, cash).get("sortino_monthly", np.nan)
    return float(v) if v is not None else np.nan


def score_row(name: str, family: str, r: pd.Series, cash: pd.Series) -> dict:
    (a1, b1), (a2, b2) = HALVES[family]
    s1, s2 = _sortino(r.loc[a1:b1], cash), _sortino(r.loc[a2:b2], cash)
    robust = min(s1, s2) if np.isfinite(s1) and np.isfinite(s2) else np.nan
    out = {"name": name, "family": family, "h1": s1, "h2": s2, "robust": robust,
           "combo_sortino": _sortino(r.loc[COMBO[0]:COMBO[1]], cash)}
    x = r.loc[JUDGE[0]:JUDGE[1]].dropna()
    if len(x) >= 60:
        m = sc.metrics(x, cash)
        total = float((1 + x).prod() - 1)
        years = (x.index[-1] - x.index[0]).days / 365.25
        out.update({"judge_sortino": m.get("sortino_monthly"), "judge_cagr": (1 + total) ** (1 / years) - 1 if total > -1
                    else -1.0, "judge_dd": m.get("max_drawdown"), "judge_total": total, "judge_sharpe": m.get("sharpe"),
                    "judge_days": len(x), "judge_skew": m.get("skew"), "judge_kurtosis": m.get("kurtosis")})
    return out


# ---------------------------------------------------------------- ETF families on data to 2026

def etf_context(opens: pd.DataFrame, closes: pd.DataFrame, cash_index: pd.Series) -> tuple[dict, dict]:
    dates = closes["SPY"].dropna().loc[:LAST].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    x = {"dates": dates, "cash": cash.to_numpy(), "cash_s": cash, "month_rows": np.flatnonzero(v5.month_ends(dates)),
         "week_rows": np.flatnonzero(sc.week_ends(dates))}
    return x, vf.context(opens, closes, x)


def etf_sim(t: dict, x: dict, e: dict) -> pd.Series:
    return vf.RUNNERS[t["family"]](t, x, e)[c9.COSTS["etf"][0]]


# ---------------------------------------------------------------- combination

def to_trading(r: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """A stream that also trades on weekends, compounded into the next session of ``calendar``."""
    r = r.dropna()
    nxt = calendar.searchsorted(r.index)
    ok = nxt < len(calendar)
    g = (1 + r[ok]).groupby(calendar[nxt[ok]]).prod() - 1
    return g.reindex(calendar)


def shortlist(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    ok = rows[np.isfinite(rows["robust"].astype(float))]
    for fam, n in SHORTLIST.items():
        g = ok[ok["family"] == fam].sort_values("robust", ascending=False)
        if fam == "QB":
            g = g.assign(set=g["name"].str.split("_").str[1]).groupby("set").head(QB_PER_SET)
            g = g.sort_values("robust", ascending=False)
        out.append(g.head(n))
    ct = rows[(rows["family"] == "CT") & rows["name"].str.endswith("_L1")]
    out.append(ct)
    return pd.concat(out, ignore_index=True)


def ivol_weights(R: pd.DataFrame) -> pd.Series:
    vol = R.std().replace(0, np.nan)
    w = (1 / vol).fillna(0.0)
    return w / w.sum()


def combine(R: pd.DataFrame, w: pd.Series) -> pd.Series:
    return (R[w.index].fillna(0.0) * w).sum(axis=1)


def greedy(R: pd.DataFrame, cash: pd.Series) -> tuple[list[str], list[float]]:
    D = R.loc[COMBO[0]:COMBO[1]]
    single = {k: _sortino(D[k], cash) for k in D.columns}
    first = max((k for k in single if np.isfinite(single[k])), key=lambda k: single[k])
    chosen, path = [first], [single[first]]
    while len(chosen) < MAX_STREAMS:
        best, best_s = None, path[-1]
        for k in D.columns:
            if k in chosen:
                continue
            members = chosen + [k]
            s = _sortino(combine(D, ivol_weights(D[members])), cash)
            if np.isfinite(s) and s > best_s:
                best, best_s = k, s
        if best is None or best_s - path[-1] < MIN_GAIN:
            break
        chosen.append(best)
        path.append(best_s)
    return chosen, path

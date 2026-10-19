"""v10: the Qullamaggie intraday book with every lever (QB), leveraged index trend (LT), leveraged crypto trend
(CT) and stock momentum rotation (MR). Pre-registered in docs/research/V10_PREREGISTRATION.md.

QB trials are numbered and decoded on the fly (2.1 million would not fit as a list of dicts).
"""
from __future__ import annotations

from itertools import product
from math import prod

import numpy as np
import pandas as pd

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v5 as v5
from aurora.research import v9_common as c

QB_START, LAST = pd.Timestamp("2016-01-04"), pd.Timestamp("2026-10-16")
DESIGN_END, JUDGE_START = pd.Timestamp("2020-12-31"), pd.Timestamp("2021-01-01")
DESIGN_START = {"QB": QB_START, "LT": pd.Timestamp("2000-01-01"), "CT": pd.Timestamp("2016-01-01"),
                "MR": sc.TRAIN_START}
DD_CAP, DD_CAPS, OWNER_DD = -0.40, (-0.30, -0.40, -0.50, -0.60), -0.60
SPREAD, CRYPTO_SPREAD, LT_FEE, LT_COST, MR_COST = 0.015, 0.05, 0.009, 2e-4, 1e-3
QB_SHARDS, OTHER_SHARDS = 300, 20

QB_SETS = ("EP_N1", "EP_N0", "EP_EARN", "EP_NEWS", "BO_ALL", "MIX1", "MIX3", "MIXS3", "ALL")
QB_EXITS = ("XQ3_20", "XQ5_20", "XQ3_10", "XQ5_10", "XQC10", "XQC20", "XE21", "XS50T60", "XO25") + tuple(
    f"XG{a}_{b}_{u}_{d}" for a in (10, 20) for b in (20, 50) for u in (20, 50, 100) for d in (0, 3, 5))
QB_DIMS = {"set": QB_SETS, "exit": QB_EXITS, "stop": ("DAY", "W1", "W2"), "rank": ("RS63", "GAP", "MODEL", "DV"),
           "regime": ("NONE", "M1", "WIND"), "risk": (0.005, 0.01, 0.015, 0.02), "cap": (0.20, 0.35, 0.50),
           "gross": (1.0, 2.0, 3.0), "pyramid": (False, True), "max_pos": (0, 8)}
QB_N = prod(len(v) for v in QB_DIMS.values())

LT_DIMS = {"u": ("QQQ", "SPY", "IWM"), "lev": (1.0, 1.5, 2.0, 2.5, 3.0),
           "filter": ("NONE", "SMA50", "SMA100", "SMA150", "SMA200", "SMA200B", "ABS12", "SMA200_ABS12"),
           "check": ("D", "W"), "vt": (0.0, 0.20, 0.30, 0.40), "off": ("CASH", "IEF")}
CT_BASES = ("ma_ensemble", "donchian_20_10", "ma_ensemble_alts", "tsmom_28", "btc_buy_hold")
CT_LEV = (1.0, 1.5, 2.0, 2.5, 3.0)
MR_DIMS = {"universe": (500, 1000), "look": ("63", "126", "252", "252S21"), "k": (5, 10, 20), "reb": ("M", "2W"),
           "filter": ("NONE", "SPY200"), "weight": ("EQ", "IV"), "lev": (1.0, 1.5, 2.0)}


# ---------------------------------------------------------------- trials

def qb_cfg(i: int) -> dict:
    """Decode trial number i in the order of the pre-registration (last dimension fastest)."""
    vals = []
    for d in reversed(list(QB_DIMS.values())):
        i, k = divmod(i, len(d))
        vals.append(d[k])
    return dict(zip(QB_DIMS, reversed(vals)))


def qb_name(g: dict) -> str:
    return (f"QB_{g['set']}_{g['exit']}_{g['stop']}_{g['rank']}_{g['regime']}_R{g['risk'] * 100:g}_C{g['cap'] * 100:g}"
            f"_G{g['gross']:g}_P{int(g['pyramid'])}_M{g['max_pos']}")


def other_trials() -> list[dict]:
    out: list[dict] = []
    for v in product(*LT_DIMS.values()):
        g = dict(zip(LT_DIMS, v))
        out.append({"family": "LT", "name": f"LT_{g['u']}_L{g['lev']:g}_{g['filter']}_{g['check']}_V{g['vt'] * 100:g}"
                                            f"_{g['off']}", **g})
    for b, lev in product(CT_BASES, CT_LEV):
        out.append({"family": "CT", "name": f"CT_{b}_L{lev:g}", "base": b, "lev": lev})
    for v in product(*MR_DIMS.values()):
        g = dict(zip(MR_DIMS, v))
        out.append({"family": "MR", "name": f"MR_U{g['universe']}_{g['look']}_K{g['k']}_{g['reb']}_{g['filter']}"
                                            f"_{g['weight']}_X{g['lev']:g}", **g})
    return out


def shard_items(shard: int) -> tuple[str, list]:
    """Shards 0-299 run QB trial numbers, shards 300-319 the other families."""
    if shard < QB_SHARDS:
        return "QB", list(range(shard, QB_N, QB_SHARDS))
    return "OTHER", other_trials()[shard - QB_SHARDS::OTHER_SHARDS]


# ---------------------------------------------------------------- metrics

def row(name: str, family: str, r: pd.Series, cash: pd.Series) -> dict:
    out: dict = {"name": name, "family": family}
    periods = {"design": (DESIGN_START[family], DESIGN_END), "judge": (JUDGE_START, LAST)}
    for p, (a, b) in periods.items():
        x = r.loc[a:b].dropna()
        if len(x) < 60:
            continue
        m = sc.metrics(x, cash)
        total = float((1 + x).prod() - 1)
        years = (x.index[-1] - x.index[0]).days / 365.25
        mo = (1 + x).groupby(x.index.to_period("M")).prod() - 1
        out.update({f"{p}_cagr": (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0,
                    f"{p}_sortino": m.get("sortino_monthly"), f"{p}_sharpe": m.get("sharpe"),
                    f"{p}_dd": m.get("max_drawdown"), f"{p}_total": total, f"{p}_worst_month": float(mo.min()),
                    f"{p}_worst_day": float(x.min()), f"{p}_days": int(len(x)), f"{p}_skew": m.get("skew"),
                    f"{p}_kurtosis": m.get("kurtosis")})
    x = r.loc[DESIGN_START[family]:LAST].dropna()
    for y, v in ((1 + x).groupby(x.index.year).prod() - 1).items():
        if y >= 2016:
            out[f"y{y}"] = float(v)
    return out


# ---------------------------------------------------------------- QB

def dense(sig: dict, shape: tuple) -> tuple:
    """Entries, stops, entry prices and same-day exits from their sparse form."""
    e = np.zeros(shape, dtype=bool)
    e[sig["r"], sig["c"]] = True
    arrays = []
    for k in ("stop", "px", "sd"):
        a = np.full(shape, np.nan, dtype=np.float32)
        a[sig["r"], sig["c"]] = sig[k]
        arrays.append(a)
    return (e, *arrays)


def sparse(sig: tuple) -> dict:
    e0, s, px, sd = (x.to_numpy() if isinstance(x, pd.DataFrame) else x for x in sig)
    e = sig[0].fillna(False).to_numpy(dtype=bool) if isinstance(sig[0], pd.DataFrame) else np.asarray(e0, dtype=bool)
    r, col = np.nonzero(e)
    return {"r": r.astype(np.int32), "c": col.astype(np.int32), "stop": np.asarray(s, np.float32)[r, col],
            "px": np.asarray(px, np.float32)[r, col], "sd": np.asarray(sd, np.float32)[r, col]}


def qb_sim(g: dict, G: dict, trades: list | None = None) -> pd.Series:
    e, s, px, sd = G["sig"][g["set"]]
    if g["regime"] == "M1":
        e = e & G["m1"][:, None]
    elif g["regime"] == "WIND":
        e = e & G["not_red"][:, None]
    same: np.ndarray | None = sd
    if g["stop"] != "DAY":
        k = 1.0 if g["stop"] == "W1" else 2.0
        s = np.fmin(s, px * (1 - k * G["adr_prior"])).astype(np.float32)
        same = None
    idx, cols = G["dates"], G["cols"]

    def df(a: np.ndarray) -> pd.DataFrame:
        return pd.DataFrame(a, index=idx, columns=cols)

    return sc.simulate(G["panel"], G["ind"], df(e), df(s), g["exit"], G["cash"], G["rank"][g["rank"]], start=QB_START,
                       entry_px=df(px), same_day_px=None if same is None else df(same), risk=g["risk"], cap=g["cap"],
                       max_gross=G["gross"][g["gross"]], pyramid=g["pyramid"], max_pos=g["max_pos"] or None,
                       trades=trades)["return"]


# ---------------------------------------------------------------- LT

def lt_sim(g: dict, etf: pd.DataFrame, cash: pd.Series) -> pd.Series:
    C = etf[g["u"]].dropna()
    r = C.pct_change(fill_method=None).fillna(0.0)
    cs = cash.reindex(C.index).fillna(0.0)
    sma = {n: C.rolling(n, min_periods=n).mean() for n in (50, 100, 150, 200)}
    f = g["filter"]
    if f == "NONE":
        sig = pd.Series(1.0, index=C.index)
    elif f == "SMA200B":
        state, vals = 0.0, []
        for cv, sv in zip(C.to_numpy(), sma[200].to_numpy()):
            if np.isfinite(sv):
                state = 1.0 if cv > 1.02 * sv else (0.0 if cv < 0.98 * sv else state)
            vals.append(state)
        sig = pd.Series(vals, index=C.index)
    else:
        ok, valid = pd.Series(True, index=C.index), pd.Series(True, index=C.index)
        for part in f.split("_"):
            if part.startswith("SMA"):
                n = int(part[3:])
                ok &= C > sma[n]
                valid &= sma[n].notna()
            else:  # ABS12
                mom = C / C.shift(252) - 1
                ok &= mom > 0
                valid &= mom.notna()
        sig = ok.astype(float).where(valid, 0.0)
    if g["check"] == "W":
        sig = sig.where(pd.Series(sc.week_ends(C.index), index=C.index)).ffill().fillna(0.0)
    lev = pd.Series(g["lev"], index=C.index)
    if g["vt"]:
        vol = r.rolling(20, min_periods=20).std() * np.sqrt(sc.PPY)
        lev = (g["vt"] / vol).clip(upper=g["lev"]).fillna(0.0)
    expo = (sig * lev).shift(1).fillna(0.0)
    off_w = ((1 - sig) if g["off"] == "IEF" else sig * 0).shift(1).fillna(0.0)
    ief = etf["IEF"].reindex(C.index).pct_change(fill_method=None).fillna(0.0)
    borrowed = (expo + off_w - 1).clip(lower=0)
    out = (expo * r + off_w * ief + (1 - expo - off_w) * cs - borrowed * SPREAD / sc.PPY
           - (LT_FEE / sc.PPY * expo / g["lev"] if g["lev"] > 1 else 0.0)
           - LT_COST * (expo.diff().abs().fillna(expo) + off_w.diff().abs().fillna(off_w)))
    return out.loc[out.index >= C.index[200]]


# ---------------------------------------------------------------- CT

def ct_sim(g: dict, crypto: pd.DataFrame, cash_cal: pd.Series) -> pd.Series:
    r = crypto[g["base"]].dropna()
    cs = cash_cal.reindex(r.index).fillna(0.0)
    return cs + g["lev"] * (r - cs) - (g["lev"] - 1) * CRYPTO_SPREAD / 365


# ---------------------------------------------------------------- MR

def mr_context(close: pd.DataFrame, volume: pd.DataFrame, spy: pd.Series, cash: pd.Series) -> dict:
    dates = close.index
    ranks = c.universe_ranks(close, volume)
    C = close.to_numpy(float)
    prev = np.full_like(C, np.nan)
    prev[1:] = C[:-1]
    r = C / prev - 1
    vol = pd.DataFrame(r, index=dates).rolling(63, min_periods=50).std().to_numpy()
    week = np.flatnonzero(sc.week_ends(dates))
    s = spy.reindex(dates).ffill()
    return {"dates": dates, "C": C, "r": r, "rank": ranks.to_numpy(np.float32), "vol": vol,
            "cash": cash.reindex(dates).fillna(0.0).to_numpy(), "cash_s": cash.reindex(dates).fillna(0.0),
            "spy_ok": (s > s.rolling(200, min_periods=200).mean()).to_numpy(),
            "rows": {"M": np.flatnonzero(v5.month_ends(dates)), "2W": week[::2]}}


def mr_sim(g: dict, M: dict) -> pd.Series:
    rows, C = M["rows"][g["reb"]], M["C"]
    look = {"63": (63, 0), "126": (126, 0), "252": (252, 0), "252S21": (231, 21)}[g["look"]]
    W_rows = np.zeros((len(rows), C.shape[1]))
    for k, t in enumerate(rows):
        a, b = t - look[1], t - look[1] - look[0]
        if b < 0 or (g["filter"] == "SPY200" and not M["spy_ok"][t]):
            continue
        ret = C[a] / C[b] - 1
        ok = (M["rank"][t] <= g["universe"]) & np.isfinite(ret)
        idx = np.flatnonzero(ok)
        if len(idx) < g["k"]:
            continue
        top = idx[np.argsort(-ret[idx], kind="stable")[:g["k"]]]
        w = np.ones(len(top)) if g["weight"] == "EQ" else 1 / np.where(np.isfinite(M["vol"][t, top]) & (M["vol"][t, top] > 0),
                                                                        M["vol"][t, top], np.nan)
        w = np.nan_to_num(w)
        if w.sum() > 0:
            W_rows[k, top] = g["lev"] * w / w.sum()
    W = c.monthly(W_rows, rows, len(M["dates"]))
    pnl, tv, _ = c.book(W, M["r"], M["cash"], lag=1)
    lev_used = np.zeros(len(W))
    lev_used[1:] = W[:-1].sum(axis=1)
    net = M["cash"] + pnl - MR_COST * tv - np.clip(lev_used - 1, 0, None) * SPREAD / sc.PPY
    s = pd.Series(net, index=M["dates"])
    first = np.flatnonzero(tv > 0)
    return s.iloc[first[0]:] if first.size else s.iloc[0:0]


# ---------------------------------------------------------------- selection

def pick(df: pd.DataFrame, cap: float = DD_CAP) -> pd.Series | None:
    ok = df[np.isfinite(df["design_cagr"].astype(float)) & (df["design_dd"].astype(float) >= cap)]
    return None if ok.empty else ok.loc[ok["design_cagr"].astype(float).idxmax()]


def plateau(df: pd.DataFrame, n: int = 100) -> dict:
    ok = df[np.isfinite(df["design_cagr"].astype(float)) & (df["design_dd"].astype(float) >= DD_CAP)]
    top = ok.nlargest(n, "design_cagr")
    return {k: float(top[f"judge_{k}"].astype(float).median()) for k in ("cagr", "sortino", "dd")} | {"n": len(top)}

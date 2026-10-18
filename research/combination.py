"""Phase 7a: rebuild the best strategy streams as daily portfolio returns and
combine them (equal weight, risk parity, SPY beta hedge, volatility target).
Pre-registered in docs/research/COMBINATION_PREREGISTRATION.md (12 trials).
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_catalyst as qc
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2
from aurora.research import stock_catalog_v4 as v4
from aurora.research import stock_catalog_v5 as v5
from aurora.research import stock_catalog_v6 as v6
from aurora.research import stock_catalog_v7 as v7

V7_STREAMS = {"ACCUM": ("S49", "XTIME60", "G10", "A3"), "SQUEEZE": ("S21", "XT8H", "G10", "A3"),
              "LOWVOL": ("S70", "XT8", "G5", "A8"), "IPO": ("S25", "XR3", "G0", "SS")}
INTRADAY = ["EP_EARN", "EP_NEWS", "BO_TOP3"]
DAILY = list(V7_STREAMS) + ["PARA_SHORT"]
SETS = {"INTRADAY": INTRADAY, "DAILY": DAILY, "ALL": INTRADAY + DAILY}
METHODS = ("EQ", "RP", "RPH", "RPH_VT")
RP_LOOKBACK, BETA_LOOKBACK, VT_LOOKBACK = 126, 126, 63
VT_TARGET, VT_MAX, SPREAD = 0.15, 3.0, sc.BORROW_SPREAD
VOL_FLOOR = 0.02  # annual: an idle stream (cash only) must not take all the risk-parity weight
INTRA_START, END = qi.START, qi.END


def trials() -> list[str]:
    return [f"{s}_{m}" for s in SETS for m in METHODS]


def v7_stream(panel: dict, index_close: pd.Series, industry: pd.Series, cash_index: pd.Series,
              setup: str, exit_rule: str, group: str, stop: str) -> pd.Series:
    """Daily returns of one catalog v7 trial, built exactly as in ``stock_catalog_v7.run_shard``."""
    keep = sc.ever_in_universe(panel)
    if setup == "S25":
        keep = keep.union(panel["close"].columns[v4.ipo_universe(panel["close"], panel["volume"]).any()])
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    ind["low10"] = L.shift(1).rolling(10, min_periods=10).min()
    ind["low20"] = L.shift(1).rolling(20, min_periods=20).min()
    ind["low50"] = L.shift(1).rolling(50, min_periods=50).min()
    ind["sma100"] = sc.sma(C, 100)
    ind["ema10"] = sc.ema(C, 10)
    ind["rsi14"] = v5.rsi(C, 14)
    ind["week_end"] = pd.Series(sc.week_ends(dates), index=dates)
    vc = v6.volume_context(O, H, L, C, V, ind)
    ind["XC_climax"] = ((V >= 3 * ind["vol50_prior"]) & (C / C.shift(1) >= 1.05)).fillna(False)
    ind["XC_obvweak"] = (vc["obv"] < sc.ema(vc["obv"], 20)).fillna(False)
    ctx = {"sma200": sc.sma(C, 200), "stage2": v2.stage2(C), "week_end": sc.week_ends(dates),
           "month_end": v5.month_ends(dates), "index": index_close.reindex(dates).ffill(),
           "index_close": index_close, "industry": industry.reindex(keep)}
    extra = {"liq500": v2.universe_top(panel, 500), "vol_ok": vc["vol_ok"], "calm": v7.calm(index_close, dates),
             "breadth": v2.breadth_on(C, ind["universe"])}
    sig, own_stop = v7.build(setup, O, H, L, C, V, ind, ctx, vc)
    mask = v7.mask_v7(sig.fillna(False).astype(bool), ind, v7.FILTER_SETS[group], extra, own_universe=(setup == "S25"))
    k = v7.STOPS[stop]
    stops = (own_stop if k is None else C * (1 - k * ind["adr"])).astype(np.float32)
    for key in v7.ENGINE_KEYS:
        ind[key] = ind[key].astype(np.float32)
    d = sc.simulate(panel, ind, mask, stops, exit_rule, cash, ind["rs"].fillna(0.0).astype(np.float32))
    return d["return"]


def para_short_stream(panel: dict, ind: dict, ctx: dict, cash: pd.Series) -> pd.Series:
    e, s, _ = q.parabolic(panel, ctx, q.PS_RUN["P100"])
    rank = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).fillna(0.0).astype(np.float32)
    d = sc.simulate(panel, ind, e.fillna(False).astype(bool), s.astype(np.float32), "XQC10", cash, rank, side=-1)
    return d["return"]


def intraday_streams(panel: dict, ind: dict, ctx: dict, nasdaq: pd.Series, cash_index: pd.Series,
                     load_minutes: Callable[[pd.Timestamp], pd.DataFrame], alp_daily: dict,
                     earnings: dict, covered: set, cik: dict, revenue: dict) -> dict[str, pd.Series]:
    kept, _ = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    prep = qi.prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    ib, _, _ = qs.intraday_signals(prep, kept[("MODEL", 3)])
    cand = prep["cands"]["IEP_N0"].stack()
    cells = cand[cand].index.to_frame(index=False)
    cells.columns = ["date", "symbol"]
    lab = qc.labels(cells, prep["panel"]["close"].index, earnings, covered, cik, revenue)
    args = (prep["m1"], prep["adr_prior"], prep["like"])
    out = {}
    for name, cat, n in (("EP_EARN", "EARN", "N0"), ("EP_NEWS", "NOEARN", "N1")):
        mask = qc.label_mask(lab, cat, prep["cands"]["IEP_N0"])
        cands = dict(prep["cands"])
        cands[f"IEP_{n}"] = cands[f"IEP_{n}"] & mask.reindex_like(cands[f"IEP_{n}"]).fillna(False)
        trial = qi.Trial(f"IEP_{n}_Q05_K5_XQ3_20", "IEP", n, "Q05", 5, qw.EXIT)
        e, s, px, sd = qi.trial_inputs(trial, prep["table"], cands, *args)[:4]
        out[name] = sc.simulate(prep["panel"], prep["ind"], e, s, qw.EXIT, prep["cash"], prep["rank"], start=qi.START,
                                entry_px=px, same_day_px=sd)["return"]
    out["BO_TOP3"] = sc.simulate(prep["panel"], prep["ind"], ib[0], ib[1], qw.EXIT, prep["cash"], prep["rank"],
                                 start=qi.START, entry_px=ib[2], same_day_px=ib[3])["return"]
    return out


def _month_starts(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    return s.groupby(index.to_period("M")).transform("min").eq(s).to_numpy()


def equal_weight(R: pd.DataFrame) -> pd.Series:
    return R.mean(axis=1)


def risk_parity(R: pd.DataFrame, lookback: int = RP_LOOKBACK) -> pd.Series:
    """Weights 1 / volatility (prior ``lookback`` sessions, floored at VOL_FLOOR a year), reset on the first
    session of each month and applied daily."""
    vol = R.rolling(lookback, min_periods=lookback).std().shift(1).clip(lower=VOL_FLOOR / np.sqrt(sc.PPY))
    inv = 1 / vol
    w = inv.where(pd.DataFrame(np.broadcast_to(_month_starts(R.index)[:, None], R.shape), index=R.index,
                               columns=R.columns)).ffill()
    w = w.div(w.sum(axis=1), axis=0)
    w = w.where(w.notna().all(axis=1), 1.0 / R.shape[1], axis=0)
    return (R * w).sum(axis=1)


def beta_hedge(r: pd.Series, spy: pd.Series, cash: pd.Series, lookback: int = BETA_LOOKBACK) -> pd.Series:
    beta = (r.rolling(lookback, min_periods=lookback).cov(spy) / spy.rolling(lookback, min_periods=lookback).var())
    beta = beta.shift(1).clip(0.0, 1.5).fillna(0.0)
    return r - beta * (spy - cash)


def vol_target(r: pd.Series, cash: pd.Series, target: float = VT_TARGET, lookback: int = VT_LOOKBACK,
               max_lev: float = VT_MAX) -> pd.Series:
    vol = r.rolling(lookback, min_periods=lookback).std().shift(1) * np.sqrt(sc.PPY)
    lev = (target / vol).clip(upper=max_lev).fillna(1.0)
    return cash + lev * (r - cash) - (lev - 1).clip(lower=0) * SPREAD / sc.PPY


def combine(R: pd.DataFrame, method: str, spy: pd.Series, cash: pd.Series) -> pd.Series:
    r = equal_weight(R) if method == "EQ" else risk_parity(R)
    if method in ("RPH", "RPH_VT"):
        r = beta_hedge(r, spy, cash)
    if method == "RPH_VT":
        r = vol_target(r, cash)
    return r


def monthly_stats(r: pd.Series) -> dict:
    m = (1 + r).groupby(r.index.to_period("M")).prod() - 1
    return {"worst_month": float(m.min()), "positive_months": float((m > 0).mean())}


def evaluate(r: pd.Series, cash: pd.Series, periods: dict) -> dict:
    row: dict = {}
    for p, (a, b) in periods.items():
        x = r.loc[a:b]
        m = sc.metrics(x, cash)
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        row[f"{p}_total"] = float((1 + x).prod() - 1)
        row.update({f"{p}_{k}": v for k, v in monthly_stats(x).items()})
    return row


PERIODS_ALL = {"all": (INTRA_START, END)}
PERIODS_DAILY = {"train": (sc.TRAIN_START, sc.TRAIN_END), "validation": (sc.VALIDATION_START, sc.VALIDATION_END),
                 "all": (INTRA_START, END)}


def results(streams: pd.DataFrame, spy: pd.Series, cash: pd.Series) -> tuple[list[dict], pd.DataFrame]:
    rows = []
    for name in streams.columns:
        periods = PERIODS_DAILY if name in DAILY else PERIODS_ALL
        rows.append({"name": name, "kind": "stream", **evaluate(streams[name].dropna(), cash, periods)})
    for set_name, members in SETS.items():
        start = sc.TRAIN_START if set_name == "DAILY" else INTRA_START
        R = streams.loc[start:END, members].fillna(0.0)
        for method in METHODS:
            r = combine(R, method, spy.loc[start:END], cash.loc[start:END])
            periods = PERIODS_DAILY if set_name == "DAILY" else PERIODS_ALL
            rows.append({"name": f"{set_name}_{method}", "kind": "combination", **evaluate(r, cash, periods)})
    rows.append({"name": "SPY", "kind": "benchmark", **evaluate(spy.loc[sc.TRAIN_START:END], cash, PERIODS_DAILY)})
    monthly = (1 + pd.concat([streams.loc[INTRA_START:END], spy.loc[INTRA_START:END].rename("SPY")], axis=1)
               .fillna(0.0)).groupby(streams.loc[INTRA_START:END].index.to_period("M")).prod() - 1
    return rows, monthly.corr()


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    df = rows.set_index("name")
    combo = df[df["kind"] == "combination"].copy()
    spy = df.loc["SPY"]
    daily = combo.index.str.startswith("DAILY")
    pick = {k: np.where(daily, combo[f"validation_{k}"], combo[f"all_{k}"]) for k in ("sharpe", "days", "skew", "kurtosis")}
    pool = np.concatenate([pick["sharpe"].astype(float), np.asarray(prior_sharpes, dtype=float)])
    combo["deflated_sharpe"] = v7.deflated_sharpe(pick["sharpe"], pool, pick["days"], pick["skew"], pick["kurtosis"])
    passed = []
    for n, r in combo.iterrows():
        p = "validation" if n.startswith("DAILY") else "all"
        v = {"sortino_monthly": r[f"{p}_sortino_monthly"], "cagr": r[f"{p}_cagr"], "max_drawdown": r[f"{p}_max_drawdown"]}
        passed.append(all(sc.criteria(v, {"cagr": spy[f"{p}_cagr"]}).values()))
    combo["passed"] = passed
    return {"streams": df[df["kind"] == "stream"], "combo": combo, "spy": spy, "passed": list(combo.index[combo["passed"]]),
            "n_trials": int(np.isfinite(pool).sum())}

"""Qullamaggie phase 2: size up when recent breakouts work, stay out when they
fail ("the wind"), with margin in green markets. Daily setups on 1995-2020 and
the phase 1 intraday setups on 2016-2020. Pre-registered in
docs/research/QULLAMAGGIE_WIND_PREREGISTRATION.md (35 trials).
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
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import stock_trades as st

POLICIES = ["E0", "E1", "E2", "E3_C20", "E3_C10", "E4_C20", "E4_C10"]
DAILY_SETUPS = ["D_BO", "D_EP"]
INTRADAY_SETUPS = ["I_BO", "I_EP", "I_MIX"]
EXIT = "XQ3_20"
OUTCOME_DAYS, WINDOW, MIN_BREAKOUTS = 3, 10, 5
PCT_WINDOW, GREEN_PCT, RED_PCT = 252, 0.70, 0.30
I_BO = qi.Trial("IBO_SCAN5_M0_K5_XQ3_20", "IBO", "SCAN5", "M0", 5, EXIT)
I_EP = qi.Trial("IEP_N1_Q05_K5_XQ3_20", "IEP", "N1", "Q05", 5, EXIT)


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str
    policy: str


def trials() -> list[Trial]:
    return [Trial(f"{s}_{p}", s, p) for s in DAILY_SETUPS + INTRADAY_SETUPS for p in POLICIES]


def wind(panel: dict, ind: dict, ctx: dict) -> pd.DataFrame:
    """Share of recent breakouts that worked, and the green / yellow / red state, both as of each close."""
    O, H, L, C = (panel[k] for k in ("open", "high", "low", "close"))
    setup, pivot = q.breakout_setup(panel, ind, ctx, *q.BO_SELECTIONS["SCAN35"])
    hit = (setup & (H >= pivot)).fillna(False).astype(bool)
    entry = np.maximum(O, pivot)
    stop = entry * (1 - ind["adr"].shift(1))
    low_through = L.rolling(OUTCOME_DAYS + 1, min_periods=OUTCOME_DAYS + 1).min().shift(-OUTCOME_DAYS)
    worked = hit & (C.shift(-OUTCOME_DAYS) > entry) & (low_through > stop)
    n = hit.sum(axis=1).shift(OUTCOME_DAYS).rolling(WINDOW, min_periods=WINDOW).sum()
    k = worked.sum(axis=1).shift(OUTCOME_DAYS).rolling(WINDOW, min_periods=WINDOW).sum()
    w = (k / n).where(n >= MIN_BREAKOUTS)
    # percentiles over the prior 252 sessions, needing at least half of them with a value
    hi = w.rolling(PCT_WINDOW, min_periods=PCT_WINDOW // 2).quantile(GREEN_PCT).shift(1)
    lo = w.rolling(PCT_WINDOW, min_periods=PCT_WINDOW // 2).quantile(RED_PCT).shift(1)
    state = pd.Series("yellow", index=C.index)
    state[(w >= hi).to_numpy()] = "green"
    state[((w <= lo) | (n < MIN_BREAKOUTS) | n.isna()).to_numpy()] = "red"
    return pd.DataFrame({"breakouts": n, "worked": w, "state": state, "m1": ctx["m1"]})


def policy(name: str, wind_df: pd.DataFrame) -> tuple[pd.Series, pd.Series, float]:
    """Risk multiplier and maximum gross exposure per day (decided at the prior close), and the position cap."""
    state = wind_df["state"].shift(1).fillna("yellow")
    m1 = wind_df["m1"].astype(bool)  # already as of the prior close
    green, red = (state == "green").to_numpy(), (state == "red").to_numpy()
    one = np.ones(len(state))
    if name.startswith("E4"):
        green, red = green & m1.to_numpy(), red | ~m1.to_numpy()
    if name == "E0":
        scale = one
    elif name == "E1":
        scale = np.where(red, 0.0, 1.0)
    else:
        scale = np.where(green, 2.0, np.where(red, 0.0, 1.0))
    gross = np.where(green, 2.0, 1.0) if name.startswith(("E3", "E4")) else one
    cap = 0.10 if name.endswith("C10") else sc.CAP
    return pd.Series(scale, index=state.index), pd.Series(gross, index=state.index), cap


def _captured(all_trades: pd.DataFrame, portfolio: list[dict], columns: pd.Index) -> float:
    """Share of the best 5% of all signals (by return) that the portfolio actually traded."""
    if all_trades.empty or not portfolio:
        return np.nan
    best = all_trades.nlargest(max(1, int(np.ceil(len(all_trades) * 0.05))), "return")
    took = {(columns[x["symbol"]], x["entry_date"]) for x in portfolio}
    return float(np.mean([(s, d) in took for s, d in zip(best["symbol"], best["entry_date"])]))


def _row(t: Trial, daily: pd.Series, trades: pd.DataFrame, cash: pd.Series, periods: dict, captured: float,
         state: pd.Series) -> dict:
    row: dict = {"name": t.name, "setup": t.setup, "policy": t.policy, "best5_captured": captured}
    for p, (a, b) in periods.items():
        m = sc.metrics(daily.loc[a:b], cash)
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        ts = st.trade_stats(trades[(trades["entry_date"] >= a) & (trades["entry_date"] <= b)])
        row.update({f"{p}_tl_{k}": ts.get(k, np.nan) for k in q.TRADE_KEYS})
        s = state.loc[a:b]
        row.update({f"{p}_share_{c}": float((s == c).mean()) for c in ("green", "yellow", "red")})
    return row


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G[t.setup]
    e, s, px, sd = g["signals"]
    scale, gross, cap = policy(t.policy, _G["wind"])
    allowed = e.mul((scale > 0).reindex(e.index).fillna(True), axis=0).astype(bool)
    trades: list[dict] = []
    d = sc.simulate(g["panel"], g["ind"], e, s, EXIT, g["cash"], g["rank"], start=g["start"], entry_px=px,
                    same_day_px=sd, risk_scale=scale, max_gross=gross, cap=cap, trades=trades)
    tl = st.trade_list(g["panel"], g["ind"], allowed, s, EXIT, start=g["start"], entry_px=px, same_day_px=sd)
    all_tl = g["all_trades"]
    return _row(t, d["return"], tl, g["cash"], g["periods"], _captured(all_tl, trades, g["panel"]["close"].columns),
                _G["wind"]["state"])


def run(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series, nasdaq: pd.Series,
        cash_index: pd.Series, industry: pd.Series, load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
        alp_daily: dict[str, pd.DataFrame], workers: int = 4) -> tuple[list[dict], dict]:
    if panel["close"].index.max() >= sc.LOCKED_START or nasdaq.index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the Qullamaggie wind study")
    ind = sc.indicators(panel, index_close, industry)
    ctx = q.context(panel, ind, nasdaq)
    wind_df = wind(panel, ind, ctx)
    cash = cash_index.reindex(panel["close"].index).ffill().pct_change(fill_method=None).fillna(0.0)
    rank = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).fillna(0.0).astype(np.float32)
    daily = {"D_BO": q.breakout(panel, ind, ctx, "STOP", *q.BO_SELECTIONS["SCAN5"]),
             "D_EP": q.episodic(panel, ind, ctx, q.EP_ADR["A35"], True)}
    prep = qi.prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    del ctx
    ib = qi.trial_inputs(I_BO, prep["table"], prep["cands"], prep["m1"], prep["adr_prior"], prep["like"])
    ie = qi.trial_inputs(I_EP, prep["table"], prep["cands"], prep["m1"], prep["adr_prior"], prep["like"])
    mix = (ib[0] | ie[0], ib[1].where(ib[0], ie[1]), ib[2].where(ib[0], ie[2]), ib[3].where(ib[0], ie[3]))
    groups: dict[str, dict] = {}
    for name, (e, s, px) in daily.items():
        e = e.fillna(False).astype(bool)
        s32, px32 = s.astype(np.float32), None if px is None else px.astype(np.float32)
        groups[name] = {"panel": panel, "ind": ind, "cash": cash, "rank": rank, "start": sc.TRAIN_START,
                        "periods": v7.PERIODS, "signals": (e, s32, px32, None),
                        "all_trades": st.trade_list(panel, ind, e, s32, EXIT, entry_px=px32)}
    for name, sig in (("I_BO", ib[:4]), ("I_EP", ie[:4]), ("I_MIX", mix)):
        groups[name] = {"panel": prep["panel"], "ind": prep["ind"], "cash": prep["cash"], "rank": prep["rank"],
                        "start": qi.START, "periods": qi.PERIODS, "signals": sig,
                        "all_trades": st.trade_list(prep["panel"], prep["ind"], sig[0], sig[1], EXIT, start=qi.START,
                                                    entry_px=sig[2], same_day_px=sig[3])}
    _G.update(groups, wind=wind_df)
    todo = trials()
    if workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(workers) as pool:
            rows = list(pool.imap_unordered(_run_trial, todo))
    else:
        rows = [_run_trial(t) for t in todo]
    _G.clear()
    spy = spy_close.reindex(panel["close"].index).ffill().pct_change(fill_method=None).fillna(0.0)
    spy_row: dict = {"name": "spy"}
    for p, (a, b) in {**v7.PERIODS, **qi.PERIODS}.items():
        m = sc.metrics(spy.loc[a:b], cash)
        spy_row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
    states = {p: wind_df["state"].loc[a:b].value_counts(normalize=True).round(3).to_dict()
              for p, (a, b) in {**v7.PERIODS, **qi.PERIODS}.items()}
    return rows + [spy_row], {"intraday": prep["info"], "states": states}


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    spy = rows[rows["name"] == "spy"].iloc[0].to_dict()
    df = rows[rows["name"] != "spy"].set_index("name")
    df = df.loc[[t.name for t in trials() if t.name in df.index]].copy()
    daily = df["setup"].str.startswith("D_").to_numpy()
    sharpe = np.where(daily, df["validation_sharpe"], df["all_sharpe"])
    days = np.where(daily, df["validation_days"], df["all_days"])
    skew = np.where(daily, df["validation_skew"], df["all_skew"])
    kurt = np.where(daily, df["validation_kurtosis"], df["all_kurtosis"])
    pool = np.concatenate([sharpe.astype(float), np.asarray(prior_sharpes, dtype=float)])
    df["deflated_sharpe"] = v7.deflated_sharpe(sharpe, pool, days, skew, kurt)
    passed = []
    for n, r in df.iterrows():
        p = "validation" if str(r["setup"]).startswith("D_") else "all"
        v = {"sortino_monthly": r[f"{p}_sortino_monthly"], "cagr": r[f"{p}_cagr"], "max_drawdown": r[f"{p}_max_drawdown"]}
        passed.append(all(sc.criteria(v, {"cagr": spy[f"{p}_cagr"]}).values()))
    df["passed"] = passed
    return {"df": df, "spy": spy, "passed": list(df.index[df["passed"]]), "n_trials": int(np.isfinite(pool).sum()),
            "expected": len(trials())}

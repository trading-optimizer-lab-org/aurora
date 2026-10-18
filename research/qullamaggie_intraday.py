"""Qullamaggie phase 1: his opening-range entries and low-of-day stops on
one-minute bars, 2016-2020. Candidates come from the daily study; the minute
bars decide the entry, the stop and a same-day stop-out, then the daily
engines take over. Pre-registered in
docs/research/QULLAMAGGIE_INTRADAY_PREREGISTRATION.md (48 trials).
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v7 as v7
from aurora.research import stock_trades as st

START, END = pd.Timestamp("2016-01-04"), pd.Timestamp("2020-12-31")
WARMUP = pd.Timestamp("2015-11-02")  # rows kept before START for the engines' moving averages
PERIODS = {"p1": (START, pd.Timestamp("2018-12-31")), "p2": (pd.Timestamp("2019-01-01"), END), "all": (START, END)}
OR_MINUTES = (1, 5, 30)
DEADLINE = 90  # minutes after the open: no entries from 11:00
EXITS = ("XQ3_10", "XQ3_20")
EP_Q = {"Q05": 0.5, "Q10": 1.0}
EP_ADR = q.EP_ADR["A35"]
MAX_DIFF = 0.03


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str  # "IBO" | "IEP"
    sel: str    # SCAN35 / SCAN5 | N0 / N1
    param: str  # M0 / M1 | Q05 / Q10
    k: int
    exit: str


def trials() -> list[Trial]:
    out = [Trial(f"IBO_{s}_{m}_K{k}_{x}", "IBO", s, m, k, x)
           for s in ("SCAN35", "SCAN5") for m in ("M0", "M1") for k in OR_MINUTES for x in EXITS]
    return out + [Trial(f"IEP_{n}_{p}_K{k}_{x}", "IEP", n, p, k, x)
                  for n in ("N0", "N1") for p in EP_Q for k in OR_MINUTES for x in EXITS]


def candidates(panel: dict, ind: dict, ctx: dict) -> dict[str, pd.DataFrame]:
    """Candidate days per variant (2016-2020) and the breakout pivot."""
    out: dict[str, pd.DataFrame] = {}
    pivot = None
    for sel in ("SCAN35", "SCAN5"):
        setup, pivot = q.breakout_setup(panel, ind, ctx, *q.BO_SELECTIONS[sel])
        out[f"IBO_{sel}"] = (setup & (panel["high"] >= pivot)).loc[START:END]
    assert pivot is not None
    out["pivot"] = pivot.loc[START:END]
    for n in ("N0", "N1"):
        out[f"IEP_{n}"] = q.episodic_gap(panel, ind, ctx, EP_ADR, n == "N1").loc[START:END]
    return out


def needed(cands: dict[str, pd.DataFrame]) -> dict[pd.Timestamp, list[str]]:
    """Symbols to fetch per day: the union of the widest variants."""
    m = (cands["IBO_SCAN35"] | cands["IEP_N0"]).fillna(False).astype(bool)
    rows, cols = np.nonzero(m.to_numpy())
    out: dict[pd.Timestamp, list[str]] = {}
    for r, c in zip(rows, cols):
        out.setdefault(m.index[r], []).append(str(m.columns[c]))
    return out


def intraday_entry(minute: np.ndarray, o: np.ndarray, h: np.ndarray, low: np.ndarray, v: np.ndarray, k: int,
                   level_min: float | None = None, adv: float | None = None, q_vol: float | None = None):
    """(entry, stop, entry minute, same-day exit or NaN) for one day of minute bars, or None.

    ``minute`` counts minutes after 9:30 ET. The trigger is the opening-range high (and ``level_min`` if
    higher); with ``q_vol`` the volume since the open must also keep pace with ``q_vol`` x ``adv``.
    """
    in_or = minute < k
    if not in_or.any():
        return None
    level = float(h[in_or].max())
    if level_min is not None:
        level = max(level, float(level_min))
    cum = np.cumsum(v)
    for j in np.flatnonzero((minute >= k) & (minute < DEADLINE)):
        if h[j] <= level:
            continue
        if q_vol is not None and adv is not None and cum[j] < q_vol * adv * min(1.0, (minute[j] + 1) / 15):
            continue
        entry = max(level, float(o[j]))
        stop = float(low[: j + 1].min())
        later = np.flatnonzero(low[j + 1:] < stop)
        exit_px = min(float(o[j + 1 + later[0]]), stop) if later.size else np.nan
        return entry, stop, int(minute[j]), exit_px
    return None


def entry_table(panel: dict, cands: dict[str, pd.DataFrame], load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
                alp_daily: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, int]]:
    """One row per candidate day, opening-range length and variant, on the panel's adjusted scale."""
    rows: list[dict] = []
    dropped = {"no_minutes": 0, "no_daily": 0, "price_mismatch": 0}
    pivot = cands["pivot"]
    for day, symbols in sorted(needed(cands).items()):
        bars = load_minutes(day)
        for sym in symbols:
            d = alp_daily.get(sym)
            mb = bars[bars["symbol"] == sym] if len(bars) else bars
            if d is None or day not in d.index:
                dropped["no_daily"] += 1
                continue
            if mb.empty:
                dropped["no_minutes"] += 1
                continue
            ratio = float(panel["close"].at[day, sym]) / float(d.at[day, "c"])
            hi, lo = float(mb["h"].max()) * ratio, float(mb["l"].min()) * ratio
            if (abs(hi / float(panel["high"].at[day, sym]) - 1) > MAX_DIFF
                    or abs(lo / float(panel["low"].at[day, sym]) - 1) > MAX_DIFF):
                dropped["price_mismatch"] += 1
                continue
            prior = d.loc[:day].iloc[:-1]
            adv = float(prior["v"].tail(20).mean()) if len(prior) >= 20 else np.nan
            arrays = (mb["minute"].to_numpy(), mb["o"].to_numpy(float), mb["h"].to_numpy(float),
                      mb["l"].to_numpy(float), mb["v"].to_numpy(float))
            variants: list[tuple[str, float | None, float | None]] = []
            if bool(cands["IBO_SCAN35"].at[day, sym]):
                variants.append(("IBO", float(pivot.at[day, sym]) / ratio, None))
            if bool(cands["IEP_N0"].at[day, sym]) and np.isfinite(adv):
                variants += [("IEP", None, qv) for qv in EP_Q.values()]
            for setup, level, qv in variants:
                for k in OR_MINUTES:
                    res = intraday_entry(*arrays, k=k, level_min=level, adv=adv, q_vol=qv)
                    if res is None:
                        continue
                    entry, stop, minute, exit_px = res
                    rows.append({"date": day, "symbol": sym, "setup": setup, "k": k, "q": qv, "entry": entry * ratio,
                                 "stop": stop * ratio, "minute": minute, "exit": exit_px * ratio})
    return pd.DataFrame(rows), dropped


def trial_inputs(t: Trial, table: pd.DataFrame, cands: dict, m1: pd.Series, adr_prior: pd.DataFrame,
                 like: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Entries, stops, entry prices and same-day exits (panel shape) for one trial, plus its chosen rows."""
    sub = table[(table["setup"] == t.setup) & (table["k"] == t.k)]
    if t.setup == "IEP":
        sub = sub[sub["q"] == EP_Q[t.param]]
    if len(sub):
        member = cands[f"{t.setup}_{t.sel}"].stack()
        keys = pd.MultiIndex.from_arrays([sub["date"], sub["symbol"]])
        sub = sub[member.reindex(keys).fillna(False).astype(bool).to_numpy()]
    if t.setup == "IBO" and t.param == "M1" and len(sub):
        sub = sub[m1.reindex(sub["date"]).fillna(False).astype(bool).to_numpy()]
    if len(sub):
        adr = adr_prior.stack().reindex(pd.MultiIndex.from_arrays([sub["date"], sub["symbol"]])).to_numpy()
        risk = (sub["entry"] - sub["stop"]) / sub["entry"]
        cap = 1.0 if t.setup == "IBO" else 1.5
        sub = sub[((risk > 0) & (risk <= cap * adr)).to_numpy()]
    shape = like.shape
    r = like.index.get_indexer(sub["date"])
    c = like.columns.get_indexer(sub["symbol"])
    ok = (r >= 0) & (c >= 0)
    r, c, sub = r[ok], c[ok], sub[ok]
    mats = []
    for col in ("entry", "stop", "exit"):
        a = np.full(shape, np.nan, dtype=np.float32)
        a[r, c] = sub[col].to_numpy(np.float32)
        mats.append(pd.DataFrame(a, index=like.index, columns=like.columns))
    e = np.zeros(shape, dtype=bool)
    e[r, c] = True
    return pd.DataFrame(e, index=like.index, columns=like.columns), mats[1], mats[0], mats[2], sub


def _metrics_row(name: str, daily: pd.Series, trades: pd.DataFrame, cash: pd.Series) -> dict:
    row: dict = {"name": name}
    for p, (a, b) in PERIODS.items():
        m = sc.metrics(daily.loc[a:b], cash)
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        ts = st.trade_stats(trades[(trades["entry_date"] >= a) & (trades["entry_date"] <= b)])
        row.update({f"{p}_tl_{k}": ts.get(k, np.nan) for k in q.TRADE_KEYS})
    row["stopped_entry_day"] = float((trades["days"] == 0).mean()) if len(trades) else np.nan
    row["median_risk"] = float(trades["risk"].median()) if len(trades) else np.nan
    wins = trades[trades["return"] > 0]
    row["median_win_days"] = float(wins["days"].median()) if len(wins) else np.nan
    return row


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G
    e, s, px, sd, sub = trial_inputs(t, g["table"], g["cands"], g["m1"], g["adr_prior"], g["like"])
    d = sc.simulate(g["panel"], g["ind"], e, s, t.exit, g["cash"], g["rank"], start=START, entry_px=px,
                    same_day_px=sd)
    tl = st.trade_list(g["panel"], g["ind"], e, s, t.exit, start=START, entry_px=px, same_day_px=sd)
    row = _metrics_row(t.name, d["return"], tl, g["cash"])
    row["exit_rule"] = t.exit
    row["median_entry_minute"] = float(sub["minute"].median()) if len(sub) else np.nan
    row["candidates_used"] = int(len(sub))
    return row


def _slice(obj, cols):
    out = obj.loc[WARMUP:]
    return out[cols] if isinstance(out, pd.DataFrame) and cols is not None else out


def prepare(panel: dict[str, pd.DataFrame], ind: dict, ctx: dict, cash_index: pd.Series,
            load_minutes: Callable[[pd.Timestamp], pd.DataFrame], alp_daily: dict[str, pd.DataFrame]) -> dict:
    """Intraday entry table and the 2016-2020 slices (candidate columns only) the trials run on."""
    cands = candidates(panel, ind, ctx)
    table, dropped = entry_table(panel, cands, load_minutes, alp_daily)
    ref = {f"REF_BO_SCAN35_{m}": q.breakout(panel, ind, ctx, "STOP", *q.BO_SELECTIONS["SCAN35"]) for m in ("M0", "M1")}
    ref = {k: (q._market(e, ctx, k[-2:]), s, px) for k, (e, s, px) in ref.items()}
    ref["REF_EP_N1_A35_M0"] = q.episodic(panel, ind, ctx, EP_ADR, True)
    cols = sorted(set(table["symbol"]) | {c for e, _, _ in ref.values() for c in e.columns[e.loc[START:END].any()]})
    small = {k: _slice(v, cols) for k, v in panel.items()}
    dates = small["close"].index
    rank = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).loc[WARMUP:, cols]
    info = {"candidate_days": int(sum(len(v) for v in needed(cands).values())), "entries": int(len(table)),
            "dropped": dropped}
    return {"panel": small, "ind": {k: _slice(v, cols) for k, v in ind.items()}, "table": table,
            "cands": {k: v[[c for c in cols if c in v.columns]] for k, v in cands.items()},
            "m1": ctx["m1"].loc[WARMUP:], "adr_prior": ind["adr"].shift(1).loc[WARMUP:, cols],
            "like": small["close"], "cash": cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0),
            "rank": rank.fillna(0.0).astype(np.float32), "ref": ref, "cols": cols, "info": info}


def run(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series, nasdaq: pd.Series,
        cash_index: pd.Series, industry: pd.Series, load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
        alp_daily: dict[str, pd.DataFrame], workers: int = 4) -> tuple[list[dict], dict]:
    if panel["close"].index.max() >= sc.LOCKED_START or nasdaq.index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the Qullamaggie intraday study")
    ind = sc.indicators(panel, index_close, industry)
    ctx = q.context(panel, ind, nasdaq)
    prep = prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    del ctx
    small, small_ind, cash, cols = prep["panel"], prep["ind"], prep["cash"], prep["cols"]
    _G.update({k: prep[k] for k in ("panel", "ind", "table", "cands", "m1", "adr_prior", "like", "cash", "rank")})
    todo = trials()
    if workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(workers) as pool:
            rows = list(pool.imap_unordered(_run_trial, todo))
    else:
        rows = [_run_trial(t) for t in todo]
    for name, (e, s, px) in prep["ref"].items():
        e2, s2 = _slice(e, cols).fillna(False).astype(bool), _slice(s, cols).astype(np.float32)
        px2 = None if px is None else _slice(px, cols).astype(np.float32)
        d = sc.simulate(small, small_ind, e2, s2, "XQ3_10", cash, _G["rank"], start=START, entry_px=px2)
        tl = st.trade_list(small, small_ind, e2, s2, "XQ3_10", start=START, entry_px=px2)
        rows.append(_metrics_row(name, d["return"], tl, cash))
    _G.clear()
    spy = spy_close.reindex(small["close"].index).ffill().pct_change(fill_method=None).loc[START:].fillna(0.0)
    spy_row: dict = {"name": "spy"}
    for p, (a, b) in PERIODS.items():
        m = sc.metrics(spy.loc[a:b], cash)
        spy_row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
    return rows + [spy_row], prep["info"]


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    spy = rows[rows["name"] == "spy"].iloc[0].to_dict()
    df = rows[rows["name"] != "spy"].set_index("name")
    names = [t.name for t in trials()]
    tri, ref = df.loc[[n for n in names if n in df.index]].copy(), df.drop(index=[n for n in names if n in df.index])
    pool = np.concatenate([tri["all_sharpe"].to_numpy(dtype=float), np.asarray(prior_sharpes, dtype=float)])
    tri["deflated_sharpe"] = v7.deflated_sharpe(tri["all_sharpe"], pool, tri["all_days"], tri["all_skew"],
                                                tri["all_kurtosis"])
    spy_all = {"cagr": spy["all_cagr"]}
    tri["passed"] = [all(sc.criteria({"sortino_monthly": s, "cagr": c, "max_drawdown": d}, spy_all).values())
                     for s, c, d in zip(tri["all_sortino_monthly"], tri["all_cagr"], tri["all_max_drawdown"])]
    return {"df": tri, "ref": ref, "spy": spy, "passed": list(tri.index[tri["passed"]]),
            "n_trials": int(np.isfinite(pool).sum()), "expected": len(names)}

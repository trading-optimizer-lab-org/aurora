"""Qullamaggie phase 5: episodic pivots that gap on a real earnings release
(SEC 8-K Item 2.02), with and without strong revenue growth, alone and mixed
with the phase 3 breakouts (2016-2020 intraday). Pre-registered in
docs/research/QULLAMAGGIE_CATALYST_PREREGISTRATION.md (16 trials).
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

CATALYSTS = ("ANY", "EARN", "EARNG", "NOEARN")
NEGLECT = ("N1", "N0")
BOOKS = ("EP", "MIX")
GROWTH = 0.25
QUARTER_LAG = (5, 120)  # the reported quarter ended 5 to 120 days before the gap


@dataclass(frozen=True)
class Trial:
    name: str
    catalyst: str
    neglect: str
    book: str


def trials() -> list[Trial]:
    return [Trial(f"CAT_{c}_{n}_{b}", c, n, b) for c in CATALYSTS for n in NEGLECT for b in BOOKS]


def quarter_frames(day: pd.Timestamp) -> tuple[str, str] | None:
    """Frame names (latest calendar quarter ended 5-120 days before ``day``, the same quarter a year earlier)."""
    ends = [pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0) for y in (day.year - 1, day.year) for m in (3, 6, 9, 12)]
    ok = [e for e in ends if day - pd.Timedelta(days=QUARTER_LAG[1]) <= e <= day - pd.Timedelta(days=QUARTER_LAG[0])]
    if not ok:
        return None
    e = max(ok)
    qn = (e.month - 1) // 3 + 1
    return f"CY{e.year}Q{qn}", f"CY{e.year - 1}Q{qn}"


def labels(cells: pd.DataFrame, dates: pd.DatetimeIndex, earnings: dict[str, list[pd.Timestamp]],
           covered: set[str], cik: dict[str, int], revenue: dict[str, dict[int, float]]) -> pd.DataFrame:
    """Catalyst label of each EP candidate (columns date, symbol): EARN / NOEARN / unknown, plus growth."""
    out = []
    pos = {d: i for i, d in enumerate(dates)}
    for day, sym in zip(cells["date"], cells["symbol"]):
        if sym not in covered:
            out.append((day, sym, "UNKNOWN", np.nan))
            continue
        i = pos[day]
        window = {dates[i]} | ({dates[i - 1]} if i > 0 else set())
        earn = any(d in window for d in earnings.get(sym, ()))
        growth = np.nan
        frames = quarter_frames(day)
        c = cik.get(sym)
        if frames is not None and c is not None:
            now, before = revenue.get(frames[0], {}).get(c), revenue.get(frames[1], {}).get(c)
            if now is not None and before is not None and before > 0:
                growth = now / before - 1
        out.append((day, sym, "EARN" if earn else "NOEARN", growth))
    return pd.DataFrame(out, columns=["date", "symbol", "label", "growth"])


def label_mask(lab: pd.DataFrame, catalyst: str, like: pd.DataFrame) -> pd.DataFrame:
    if catalyst == "ANY":
        keep = lab
    elif catalyst == "EARNG":
        keep = lab[(lab["label"] == "EARN") & (lab["growth"] >= GROWTH)]
    else:
        keep = lab[lab["label"] == catalyst]
    m = np.zeros(like.shape, dtype=bool)
    r, c = like.index.get_indexer(keep["date"]), like.columns.get_indexer(keep["symbol"])
    ok = (r >= 0) & (c >= 0)
    m[r[ok], c[ok]] = True
    return pd.DataFrame(m, index=like.index, columns=like.columns)


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G
    e, s, px, sd = g["signals"][(t.catalyst, t.neglect, t.book)]
    trades: list[dict] = []
    d = sc.simulate(g["panel"], g["ind"], e, s, qw.EXIT, g["cash"], g["rank"], start=qi.START, entry_px=px,
                    same_day_px=sd, trades=trades)
    tl = st.trade_list(g["panel"], g["ind"], e, s, qw.EXIT, start=qi.START, entry_px=px, same_day_px=sd)
    row: dict = {"name": t.name, "catalyst": t.catalyst, "neglect": t.neglect, "book": t.book}
    for p, (a, b) in qi.PERIODS.items():
        m = sc.metrics(d["return"].loc[a:b], g["cash"])
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in v7.PORT_KEYS})
        row[f"{p}_total"] = float((1 + d["return"].loc[a:b]).prod() - 1)
        ts = st.trade_stats(tl[(tl["entry_date"] >= a) & (tl["entry_date"] <= b)])
        row.update({f"{p}_tl_{k}": ts.get(k, np.nan) for k in q.TRADE_KEYS})
    return row


def run(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series, nasdaq: pd.Series,
        cash_index: pd.Series, industry: pd.Series, load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
        alp_daily: dict[str, pd.DataFrame], earnings: dict[str, list[pd.Timestamp]], covered: set[str],
        cik: dict[str, int], revenue: dict[str, dict[int, float]], workers: int = 4) -> tuple[list[dict], dict]:
    if panel["close"].index.max() >= sc.LOCKED_START or nasdaq.index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the Qullamaggie catalyst study")
    ind = sc.indicators(panel, index_close, industry)
    ctx = q.context(panel, ind, nasdaq)
    kept, _ = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    prep = qi.prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    del ctx
    ib, _, _ = qs.intraday_signals(prep, kept[("MODEL", 3)])
    del kept
    cand = prep["cands"]["IEP_N0"].stack()
    cells = cand[cand].index.to_frame(index=False)
    cells.columns = ["date", "symbol"]
    lab = labels(cells, prep["panel"]["close"].index, earnings, covered, cik, revenue)
    signals: dict = {}
    args = (prep["m1"], prep["adr_prior"], prep["like"])
    for c in CATALYSTS:
        mask = label_mask(lab, c, prep["cands"]["IEP_N0"])
        for n in NEGLECT:
            cands = dict(prep["cands"])
            cands[f"IEP_{n}"] = cands[f"IEP_{n}"] & mask.reindex_like(cands[f"IEP_{n}"]).fillna(False)
            trial = qi.Trial(f"IEP_{n}_Q05_K5_XQ3_20", "IEP", n, "Q05", 5, qw.EXIT)
            ie = qi.trial_inputs(trial, prep["table"], cands, *args)[:4]
            signals[(c, n, "EP")] = ie
            signals[(c, n, "MIX")] = (ib[0] | ie[0], ib[1].where(ib[0], ie[1]), ib[2].where(ib[0], ie[2]),
                                      ib[3].where(ib[0], ie[3]))
    _G.update(panel=prep["panel"], ind=prep["ind"], cash=prep["cash"], rank=prep["rank"], signals=signals)
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
    known = lab[lab["label"] != "UNKNOWN"]
    info = {"intraday": prep["info"], "ep_candidates": int(len(lab)), "with_filings": int(len(known)),
            "earn": int((lab["label"] == "EARN").sum()), "with_growth": int(known["growth"].notna().sum()),
            "earn_growth25": int(((lab["label"] == "EARN") & (lab["growth"] >= GROWTH)).sum())}
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
    return {"df": df, "spy": spy, "passed": list(df.index[df["passed"]]), "n_trials": int(np.isfinite(pool).sum()),
            "expected": len(trials())}

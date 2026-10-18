"""Phase 7b: five more intraday streams on one-minute bars (2016-2020): EP and
breakout day trades, intraday parabolic shorts (day and swing) and breakdown
shorts. Pre-registered in docs/research/COMBINATION_PLUS_PREREGISTRATION.md.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from aurora.research import qullamaggie as q
from aurora.research import qullamaggie_intraday as qi
from aurora.research import qullamaggie_stars as qs
from aurora.research import qullamaggie_wind as qw
from aurora.research import stock_catalog as sc

K, PS_RUN, BD_DROP, WEAK = 5, 1.5, 0.70, 0.02
PS_CAP, BD_CAP = 1.5, 1.0  # widest stop, in ADRs
NEW = ["EP_DAY", "BO_DAY", "PS_DAY", "PS_SWING", "BD_DAY"]


def parabolic_setup(panel: dict, ctx: dict) -> pd.DataFrame:
    """As of the prior close: 1.5x the lowest low of 10 sessions after 3 higher closes, liquid."""
    L, C = panel["low"], panel["close"]
    run = C.shift(1) >= PS_RUN * L.shift(1).rolling(10, min_periods=10).min()
    up3 = (C.shift(1) > C.shift(2)) & (C.shift(2) > C.shift(3)) & (C.shift(3) > C.shift(4))
    liquid = ((C >= q.MIN_PRICE) & (ctx["dv"] >= q.MIN_DV)).shift(1, fill_value=False)
    return (run & up3 & liquid).fillna(False).astype(bool)


def breakdown_setup(panel: dict, ind: dict, ctx: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mirror of the breakout setup (as of the prior close) and the pivot low (10-session low)."""
    H, L, C = panel["high"], panel["low"], panel["close"]
    adr, s10, s20 = ind["adr"], ind["sma10"], ind["sma20"]
    elig = ctx["base"] & (adr >= q.BO_SELECTIONS["SCAN35"][0])
    weak = None
    for n in (21, 63, 126):
        hit = (C / C.shift(n) - 1).rank(axis=1, pct=True) <= WEAK
        weak = hit if weak is None else (weak | hit)
    chosen = elig & ((elig & weak).astype(float).rolling(q.WATCH_DAYS, min_periods=1).max() > 0)
    drop = C / H.shift(1).rolling(63, min_periods=63).max()
    decline = drop.shift(1).rolling(63, min_periods=1).min() <= BD_DROP
    hi5, lo5 = H.shift(1).rolling(5, min_periods=5).max(), L.shift(1).rolling(5, min_periods=5).min()
    base = ((hi5 - lo5) < (hi5.shift(5) - lo5.shift(5))) & (hi5 < hi5.shift(5))
    trend = ((s10 < s20) & (s20 < s20.shift(5)) & (C <= s20)).shift(1, fill_value=False)
    pivot = L.shift(1).rolling(10, min_periods=10).min()
    setup = chosen.shift(1, fill_value=False) & decline & base & trend
    return setup.fillna(False).astype(bool), pivot


def short_candidates(panel: dict, ind: dict, ctx: dict) -> dict[str, pd.DataFrame]:
    ps = parabolic_setup(panel, ctx)
    bd, pivot = breakdown_setup(panel, ind, ctx)
    bd = bd & (panel["low"] <= pivot)
    return {"PS": ps.loc[qi.START:qi.END], "BD": bd.loc[qi.START:qi.END], "pivot_low": pivot.loc[qi.START:qi.END]}


def short_needed(cands: dict[str, pd.DataFrame]) -> dict[pd.Timestamp, list[str]]:
    m = (cands["PS"] | cands["BD"]).to_numpy()
    rows, cols = np.nonzero(m)
    out: dict[pd.Timestamp, list[str]] = {}
    idx, names = cands["PS"].index, cands["PS"].columns
    for r, c in zip(rows, cols):
        out.setdefault(idx[r], []).append(str(names[c]))
    return out


def intraday_short_entry(minute: np.ndarray, o: np.ndarray, h: np.ndarray, low: np.ndarray, k: int,
                         level_max: float | None = None):
    """(entry, stop, entry minute, same-day exit or NaN) for a short on the opening-range low, or None."""
    in_or = minute < k
    if not in_or.any():
        return None
    level = float(low[in_or].min())
    if level_max is not None:
        level = min(level, float(level_max))
    for j in np.flatnonzero((minute >= k) & (minute < qi.DEADLINE)):
        if low[j] >= level:
            continue
        entry = min(level, float(o[j]))
        stop = float(h[: j + 1].max())
        later = np.flatnonzero(h[j + 1:] > stop)
        exit_px = max(float(o[j + 1 + later[0]]), stop) if later.size else np.nan
        return entry, stop, int(minute[j]), exit_px
    return None


def short_table(panel: dict, cands: dict[str, pd.DataFrame], load_minutes: Callable[[pd.Timestamp], pd.DataFrame],
                alp_daily: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []
    for day, symbols in sorted(short_needed(cands).items()):
        bars = load_minutes(day)
        for sym in symbols:
            d = alp_daily.get(sym)
            mb = bars[bars["symbol"] == sym] if len(bars) else bars
            if d is None or day not in d.index or mb.empty:
                continue
            ratio = float(panel["close"].at[day, sym]) / float(d.at[day, "c"])
            hi, lo = float(mb["h"].max()) * ratio, float(mb["l"].min()) * ratio
            if (abs(hi / float(panel["high"].at[day, sym]) - 1) > qi.MAX_DIFF
                    or abs(lo / float(panel["low"].at[day, sym]) - 1) > qi.MAX_DIFF):
                continue
            arrays = (mb["minute"].to_numpy(), mb["o"].to_numpy(float), mb["h"].to_numpy(float), mb["l"].to_numpy(float))
            for setup, level in (("PS", None), ("BD", float(cands["pivot_low"].at[day, sym]) / ratio)):
                if not bool(cands[setup].at[day, sym]):
                    continue
                res = intraday_short_entry(*arrays, k=K, level_max=level)
                if res is not None:
                    entry, stop, minute, exit_px = res
                    rows.append({"date": day, "symbol": sym, "setup": setup, "entry": entry * ratio,
                                 "stop": stop * ratio, "minute": minute, "exit": exit_px * ratio})
    return pd.DataFrame(rows, columns=["date", "symbol", "setup", "entry", "stop", "minute", "exit"])


def _matrices(sub: pd.DataFrame, like: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    r, c = like.index.get_indexer(sub["date"]), like.columns.get_indexer(sub["symbol"])
    ok = (r >= 0) & (c >= 0)
    r, c, sub = r[ok], c[ok], sub[ok]
    mats = []
    for col in ("entry", "stop", "exit"):
        a = np.full(like.shape, np.nan, dtype=np.float32)
        a[r, c] = sub[col].to_numpy(np.float32)
        mats.append(pd.DataFrame(a, index=like.index, columns=like.columns))
    e = np.zeros(like.shape, dtype=bool)
    e[r, c] = True
    return pd.DataFrame(e, index=like.index, columns=like.columns), mats[1], mats[0], mats[2]


def short_inputs(table: pd.DataFrame, setup: str, adr_prior: pd.DataFrame, like: pd.DataFrame) -> tuple:
    sub = table[table["setup"] == setup]
    if len(sub):
        adr = adr_prior.stack().reindex(pd.MultiIndex.from_arrays([sub["date"], sub["symbol"]])).to_numpy()
        risk = (sub["stop"] - sub["entry"]) / sub["entry"]
        cap = PS_CAP if setup == "PS" else BD_CAP
        sub = sub[((risk > 0) & (risk <= cap * adr)).to_numpy()]
    return _matrices(sub, like)


def day_trade(sig: tuple, close: pd.DataFrame) -> tuple:
    """Same entries; every position not stopped during the day is closed at that day's close."""
    e, s, px, sd = sig
    return e, s, px, sd.where(sd.notna(), close.where(e))


def new_streams(panel: dict, ind: dict, ctx: dict, nasdaq: pd.Series, cash_index: pd.Series,
                load_minutes: Callable[[pd.Timestamp], pd.DataFrame], alp_daily: dict) -> tuple[dict[str, pd.Series], dict]:
    kept, _ = qs.selected_breakouts(panel, ind, ctx, nasdaq)
    prep = qi.prepare(panel, ind, ctx, cash_index, load_minutes, alp_daily)
    ib, _, _ = qs.intraday_signals(prep, kept[("MODEL", 3)])
    del kept
    args = (prep["table"], prep["cands"], prep["m1"], prep["adr_prior"], prep["like"])
    ep = qi.trial_inputs(qi.Trial("IEP_N0_Q05_K5_XQ3_20", "IEP", "N0", "Q05", K, qw.EXIT), *args)[:4]
    cands = short_candidates(panel, ind, ctx)
    cols = sorted(set(prep["panel"]["close"].columns) | {c for k in ("PS", "BD") for c in cands[k].columns[cands[k].any()]})
    small = {k: v.loc[qi.WARMUP:, cols] for k, v in panel.items()}
    small_ind = {k: (v.loc[qi.WARMUP:, cols] if isinstance(v, pd.DataFrame) else v.loc[qi.WARMUP:]) for k, v in ind.items()}
    like = small["close"]
    cash = cash_index.reindex(like.index).ffill().pct_change(fill_method=None).fillna(0.0)
    mom = (panel["close"] / panel["close"].shift(63) - 1).rank(axis=1, pct=True).loc[qi.WARMUP:, cols].fillna(0.0)
    table = short_table(panel, cands, load_minutes, alp_daily)
    adr_prior = ind["adr"].shift(1).loc[qi.WARMUP:, cols]

    def widen(sig: tuple) -> tuple:  # the long signals live on prep's columns: put them on the wider frame
        out = []
        for x in sig:
            flag = all(dt == bool for dt in x.dtypes)
            out.append(x.reindex(index=like.index, columns=cols, fill_value=False if flag else np.nan))
        return tuple(out)

    out: dict[str, pd.Series] = {}

    def run(name: str, sig: tuple, exit_rule: str, side: int, rank: pd.DataFrame) -> None:
        e, s, px, sd = sig
        d = sc.simulate(small, small_ind, e, s, exit_rule, cash, rank.astype(np.float32), start=qi.START,
                        entry_px=px, same_day_px=sd, side=side)
        out[name] = d["return"]

    run("EP_DAY", day_trade(widen(ep), like), qw.EXIT, 1, mom)
    run("BO_DAY", day_trade(widen(ib), like), qw.EXIT, 1, mom)
    ps = short_inputs(table, "PS", adr_prior, like)
    run("PS_DAY", day_trade(ps, like), "XQC10", -1, mom)
    run("PS_SWING", ps, "XQC10", -1, mom)
    run("BD_DAY", day_trade(short_inputs(table, "BD", adr_prior, like), like), "XQC10", -1, 1 - mom)
    counts = {"PS_candidates": int(cands["PS"].to_numpy().sum()), "BD_candidates": int(cands["BD"].to_numpy().sum()),
              "PS_entries": int((table["setup"] == "PS").sum()), "BD_entries": int((table["setup"] == "BD").sum())}
    return out, counts

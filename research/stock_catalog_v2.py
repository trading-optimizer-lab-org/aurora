"""Stock catalog v2, as pre-registered in
docs/research/STOCK_CATALOG_V2_PREREGISTRATION.md. Reuses v1 (stock_catalog)
for data handling, indicators, setups, engines and metrics.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab
from aurora.research import stock_catalog as sc
from aurora.research import stock_trades as st


@dataclass(frozen=True)
class CandidateV2:
    name: str
    setup: str
    exit: str
    filters: tuple[str, ...]
    rank: str = "RS"
    risk: float = sc.RISK
    trade_level: bool = True


SHARED = ("MF", "ADR4", "IND50")
CANDIDATES: list[CandidateV2] = [
    CandidateV2("pullback_stage2", "S3", "XS20", SHARED + ("STAGE2",)),
    CandidateV2("pullback_ind85", "S3", "XS20", ("MF", "ADR4", "IND85")),
    CandidateV2("pullback_rank_ind", "S3", "XS20", SHARED, rank="IND", trade_level=False),
    CandidateV2("pullback_rank_close", "S3", "XS20", SHARED, rank="CLOSE", trade_level=False),
    CandidateV2("pullback_rank_random", "S3", "XS20", SHARED, rank="RANDOM", trade_level=False),
    CandidateV2("pullback_risk025", "S3", "XS20", SHARED, risk=0.0025, trade_level=False),
    CandidateV2("weinstein_s50", "S7", "XS50", SHARED),
    CandidateV2("darvas_s50", "S6", "XS50", SHARED),
    CandidateV2("felipe_s50", "S1", "XS50", SHARED),
    CandidateV2("qulla_traits_s20", "S2T", "XS20", SHARED),
    CandidateV2("bnf_large", "S8L", "BNF", ()),
    CandidateV2("parabolic_short", "S9", "XPS", ("ADR4",)),
    CandidateV2("pullback_breadth", "S3", "XS20", ("BREADTH", "ADR4", "IND50")),
    CandidateV2("felipe_s20_breadth", "S1", "XS20", ("BREADTH", "ADR4", "IND50")),
]
V1_TRIALS = sc.N_TRIALS


def breadth_on(C: pd.DataFrame, universe: pd.DataFrame) -> pd.Series:
    e8, e20, e50 = sc.ema(C, 8), sc.ema(C, 20), sc.ema(C, 50)
    bull = (universe & (e8 > e20) & (e20 > e50) & (C > e20)).sum(axis=1)
    bear = (universe & (e8 < e20) & (e20 < e50) & (C < e20)).sum(axis=1)
    return bull > bear


def stage2(C: pd.DataFrame) -> pd.DataFrame:
    s150 = sc.sma(C, 150)
    return (C > s150) & (s150 > s150.shift(20))


def setup_s2t(O, H, L, C, V, ind, index_close: pd.Series):
    s10, s20 = ind["sma10"], ind["sma20"]
    runup = C.shift(1) >= 1.5 * L.shift(1).rolling(63, min_periods=63).min()
    trend = (C.shift(1) > s10.shift(1)) & (C.shift(1) > s20.shift(1)) & (s10 > s20) & (s20 > s20.shift(5))
    hi10, lo10 = H.shift(1).rolling(10, min_periods=10).max(), L.shift(1).rolling(10, min_periods=10).min()
    tight = (hi10 - lo10) / C.shift(1) <= 3 * ind["adr"].shift(1)
    quiet = C.shift(1) / C.shift(22) - 1 < 2 * ind["adr"].shift(1)
    no_gap = O / C.shift(1) - 1 < ind["adr"]
    idx = index_close.reindex(C.index).ffill()
    calm = idx / idx.shift(21) - 1 < 0.05
    sig = (runup & trend & tight & (C > hi10) & quiet & no_gap).mul(calm, axis=0).astype(bool)
    return sig, np.maximum(L, C * (1 - ind["adr"]))


def setup_s9(O, H, L, C, V, ind):
    up = C > C.shift(1)
    streak = up.shift(1, fill_value=False) & up.shift(2, fill_value=False) & up.shift(3, fill_value=False)
    sig = (C.shift(1) >= 1.5 * C.shift(6)) & streak & (C < C.shift(1))
    return sig, np.maximum(H, H.shift(1))


def universe_top(panel: dict[str, pd.DataFrame], n: int) -> pd.DataFrame:
    C, V = panel["close"], panel["volume"]
    dv50 = (C * V).rolling(50, min_periods=50).mean()
    eligible = (C.notna().cumsum() >= sc.MIN_HISTORY) & dv50.notna()
    return eligible & (dv50.where(eligible).rank(axis=1, ascending=False) <= n)


def mask_v2(sig: pd.DataFrame, ind: dict, filters: tuple[str, ...], extra: dict) -> pd.DataFrame:
    m = sc.entry_mask(sig, ind, tuple(f for f in filters if f in ("MF", "ADR4", "IND50")))
    if "IND85" in filters:
        m = m & (ind["ind_rs"] >= 85)
    if "STAGE2" in filters:
        m = m & extra["stage2"]
    if "BREADTH" in filters:
        m = m.mul(extra["breadth"], axis=0).astype(bool)
    return m.fillna(False).astype(bool)


def ranking(kind: str, ind: dict, C: pd.DataFrame) -> pd.DataFrame:
    if kind == "IND":
        return ind["ind_rs"]
    if kind == "CLOSE":
        return -(C / sc.ema(C, 21) - 1)
    if kind == "RANDOM":
        rng = np.random.default_rng(2026)
        return pd.DataFrame(rng.random(C.shape, dtype=np.float32), index=C.index, columns=C.columns)
    return ind["rs"]


def run_study(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series, v1_sharpes: list[float] | None = None) -> dict:
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the stock catalog v2")
    keep = sc.ever_in_universe(panel)
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    extra = {"stage2": stage2(C), "breadth": breadth_on(C, ind["universe"])}
    def build(key: str):
        if key == "S2T":
            return setup_s2t(O, H, L, C, V, ind, index_close)
        if key == "S9":
            return setup_s9(O, H, L, C, V, ind)
        return sc.SETUPS[key](O, H, L, C, V, ind)

    daily: dict[str, pd.Series] = {}
    trades: dict[str, pd.DataFrame] = {}
    info: dict[str, dict] = {}
    for key in dict.fromkeys(c.setup for c in CANDIDATES):
        if key == "S8L":
            sig, limit, dev = sc.bnf_signals(panel, ind)
            sig = (sig & universe_top(panel, 500)).fillna(False).astype(bool)
            stop = limit - 3 * ind["adr"] * C
            r2 = sc.rsi2(C)
            d = sc.simulate(panel, ind, sig, stop, "BNF", cash, -dev, limits=limit, rsi=r2)
            daily["bnf_large"] = d["return"]
            trades["bnf_large"] = st.trade_list(panel, ind, sig, stop, "BNF", limits=limit, rsi=r2)
            info["bnf_large"] = {"invested_mean": float(d["invested"].mean()),
                                 "signals": int(sig.loc[sc.TRAIN_START:].to_numpy().sum())}
            continue
        sig, stop = build(key)
        for cand in [c for c in CANDIDATES if c.setup == key]:
            side = -1 if key == "S9" else 1
            mask = mask_v2(sig, ind, cand.filters, extra)
            d = sc.simulate(panel, ind, mask, stop, cand.exit, cash, ranking(cand.rank, ind, C),
                            risk=cand.risk, side=side)
            daily[cand.name] = d["return"]
            if cand.trade_level:
                trades[cand.name] = st.trade_list(panel, ind, mask, stop, cand.exit, side=side)
            info[cand.name] = {"invested_mean": float(d["invested"].mean()),
                               "signals": int(mask.loc[sc.TRAIN_START:].to_numpy().sum())}
        del sig, stop
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[sc.TRAIN_START:].fillna(0.0)
    results: dict[str, dict] = {"spy": {p: sc.metrics(spy.loc[a:b], cash) for p, (a, b) in sc.PERIODS.items()}}
    names = [c.name for c in CANDIDATES]
    for n in names:
        r = daily[n]
        results[n] = {p: sc.metrics(r.loc[a:b], cash) for p, (a, b) in sc.PERIODS.items()}
        results[n]["annual"] = sc.annual_returns(r)
        results[n].update(info[n])
        if n in trades:
            results[n]["trade_level"] = st.summarize(trades[n])
    trial = [results[n]["validation"]["sharpe"] for n in names] + list(v1_sharpes or [])
    for n in names:
        v = results[n]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(v["sharpe"], trial, n_periods=v["days"], skew=v["skew"],
                                                   kurtosis=v["kurtosis"], ppy=sc.PPY)
        results[n]["checks"] = sc.criteria(v, results["spy"]["validation"])
        results[n]["passed"] = all(results[n]["checks"].values())
    return {"results": results, "daily_returns": {"spy": spy, **daily}, "candidates": names,
            "trades": trades, "n_trials": len(trial)}

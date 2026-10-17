"""Stock catalog v3: a wide grid of setups x exits x filters, as
pre-registered in docs/research/STOCK_CATALOG_V3_PREREGISTRATION.md.

The grid is split into shards by setup (``run_shard``) so it can run in
parallel; ``aggregate`` merges the shards, applies the train-only selection
rule and the pass criteria.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2
from aurora.research import stock_trades as st

LONG_SETUPS = ["S1", "S2", "S2T", "S3", "S4", "S5", "S6", "S7", "S10", "S11", "S12", "S13", "S14"]
LONG_EXITS = ["X5", "XS10", "XS20", "XS50", "XH3", "XT3"]
FILTER_SETS = {"F0": (), "F1": ("MF",), "F2": ("MF", "IND50"), "F3": ("MF", "IND50", "ADR4")}
SHORT_FILTERS = {"none": (), "ADR4": ("ADR4",)}
MIN_TRAIN_TRADES = 300
TOP_N = 15
# Heavy (signal-rich) setups first so round-robin sharding balances the load.
GROUPS = ["S3", "S12", "S4", "S11", "S1", "S2", "S6", "S7", "S10", "S13", "S5", "S14", "S2T", "S15",
          "S8", "S8L", "S9", "S17"]


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str
    exit: str
    filters: tuple[str, ...]
    side: int = 1


def trials() -> list[Trial]:
    out = [Trial(f"{s}_{x}_{f}", s, x, fs) for s in LONG_SETUPS for x in LONG_EXITS for f, fs in FILTER_SETS.items()]
    out += [Trial(f"S15_XRSI_{f}", "S15", "XRSI", fs) for f, fs in FILTER_SETS.items()]
    out += [Trial("S8_BNF_none", "S8", "BNF", ()), Trial("S8L_BNF_none", "S8L", "BNF", ())]
    for setup, exits in (("S9", ("XPS", "X5")), ("S17", ("XC20", "X5"))):
        out += [Trial(f"{setup}_{x}_{f}", setup, x, fs, side=-1) for x in exits for f, fs in SHORT_FILTERS.items()]
    return out


def shard_groups(shard: int, shards: int) -> list[str]:
    return [g for k, g in enumerate(GROUPS) if k % shards == shard]


def _trend_template(C, ind, s150, s200, s50) -> pd.DataFrame:
    hi252 = C.rolling(252, min_periods=252).max()
    lo252 = C.rolling(252, min_periods=252).min()
    return ((C > s150) & (C > s200) & (s150 > s200) & (s200 > s200.shift(21)) & (s50 > s150) & (s50 > s200)
            & (C > s50) & (C >= 1.3 * lo252) & (C >= 0.75 * hi252) & (ind["rs"] >= 70))


def _range(H, L, C, a: int, b: int) -> pd.DataFrame:
    """(max high - min low) / close over days t-b..t-a (a < b, both lags)."""
    n = b - a + 1
    hi = H.shift(a).rolling(n, min_periods=n).max()
    lo = L.shift(a).rolling(n, min_periods=n).min()
    return (hi - lo) / C.shift(1)


def setup_s10(O, H, L, C, V, ind):
    s50, s150, s200 = ind["sma50"], sc.sma(C, 150), sc.sma(C, 200)
    tmpl = _trend_template(C, ind, s150, s200, s50)
    contract = (_range(H, L, C, 1, 10) < _range(H, L, C, 11, 20)) & (_range(H, L, C, 11, 20) < _range(H, L, C, 21, 30))
    dry = V.shift(1).rolling(10, min_periods=10).mean() < 0.75 * ind["vol50_prior"]
    hi10 = H.shift(1).rolling(10, min_periods=10).max()
    stop = L.shift(1).rolling(10, min_periods=10).min()
    sig = tmpl & contract & dry & (C > hi10) & (V >= 1.5 * ind["vol50_prior"]) & ((C - stop) / C <= 3 * ind["adr"])
    return sig, stop


def setup_s11(O, H, L, C, V, ind):
    rng = H - L
    nr7 = rng.shift(1) <= rng.shift(1).rolling(7, min_periods=7).min()
    s50 = ind["sma50"]
    trend = (C.shift(1) > s50.shift(1)) & (s50 > s50.shift(10))
    return nr7 & trend & (C > H.shift(1)), L.shift(1)


def setup_s12(O, H, L, C, V, ind):
    sig = (C >= 0.98 * C.rolling(252, min_periods=252).max()) & (ind["rs"] >= 80) & (C > ind["sma50"])
    return sig, C * (1 - 2 * ind["adr"])


def setup_s13(O, H, L, C, V, ind):
    sig = (O / C.shift(1) >= 1.04) & (C > O) & (V >= 2 * ind["vol50_prior"]) & v2.stage2(C)
    return sig, L


def setup_s14(O, H, L, C, V, ind):
    run = C.shift(10).rolling(41, min_periods=41).max() >= 1.9 * C.shift(40).rolling(21, min_periods=21).min()
    hi10 = H.shift(1).rolling(10, min_periods=10).max()
    lo10 = L.shift(1).rolling(10, min_periods=10).min()
    flag = (hi10 - lo10) / hi10 <= 0.25
    return run & flag & (C > hi10), lo10


def setup_s15(O, H, L, C, V, ind):
    sig = (C > sc.sma(C, 200)) & (sc.rsi2(C) < 10)
    return sig, C * (1 - 3 * ind["adr"])


def setup_s17(O, H, L, C, V, ind):
    s150 = sc.sma(C, 150)
    stop = H.shift(1).rolling(10, min_periods=10).max()
    sig = ((C < s150) & (s150 < s150.shift(20)) & (C < L.shift(1).rolling(50, min_periods=50).min())
           & (V >= 1.5 * ind["vol50_prior"]) & ((stop - C) / C <= 3 * ind["adr"]))
    return sig, stop


NEW_SETUPS = {"S10": setup_s10, "S11": setup_s11, "S12": setup_s12, "S13": setup_s13, "S14": setup_s14,
              "S15": setup_s15, "S17": setup_s17}


def _summary(daily: pd.Series, trades: pd.DataFrame, cash: pd.Series, signals: int) -> dict:
    out: dict = {p: sc.metrics(daily.loc[a:b], cash) for p, (a, b) in sc.PERIODS.items()}
    out["annual"] = sc.annual_returns(daily)
    out["trade_level"] = st.summarize(trades)
    out["signals"] = signals
    return out


def run_shard(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series, groups: list[str]) -> dict:
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the stock catalog v3")
    keep = sc.ever_in_universe(panel)
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    extra = {"stage2": v2.stage2(C), "breadth": None}
    results: dict[str, dict] = {}
    daily_out: dict[str, pd.Series] = {}
    all_trials = trials()
    for g in groups:
        todo = [t for t in all_trials if t.setup == g]
        if g in ("S8", "S8L"):
            sig, limit, dev = sc.bnf_signals(panel, ind)
            stop = None
            if g == "S8L":
                sig = sig & v2.universe_top(panel, 500)
                stop = limit - 3 * ind["adr"] * C
            sig = sig.fillna(False).astype(bool)
            r2 = sc.rsi2(C)
            d = sc.simulate(panel, ind, sig, stop, "BNF", cash, -dev, limits=limit, rsi=r2)
            tl = st.trade_list(panel, ind, sig, stop, "BNF", limits=limit, rsi=r2)
            results[todo[0].name] = _summary(d["return"], tl, cash, int(sig.loc[sc.TRAIN_START:].to_numpy().sum()))
            daily_out[todo[0].name] = d["return"]
            continue
        if g == "S2T":
            sig, stop = v2.setup_s2t(O, H, L, C, V, ind, index_close)
        elif g == "S9":
            sig, stop = v2.setup_s9(O, H, L, C, V, ind)
        elif g in NEW_SETUPS:
            sig, stop = NEW_SETUPS[g](O, H, L, C, V, ind)
        else:
            sig, stop = sc.SETUPS[g](O, H, L, C, V, ind)
        for t in todo:
            mask = v2.mask_v2(sig, ind, t.filters, extra)
            d = sc.simulate(panel, ind, mask, stop, t.exit, cash, ind["rs"], side=t.side)
            tl = st.trade_list(panel, ind, mask, stop, t.exit, side=t.side)
            results[t.name] = _summary(d["return"], tl, cash, int(mask.loc[sc.TRAIN_START:].to_numpy().sum()))
            daily_out[t.name] = d["return"]
        del sig, stop
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[sc.TRAIN_START:].fillna(0.0)
    results["spy"] = {p: sc.metrics(spy.loc[a:b], cash) for p, (a, b) in sc.PERIODS.items()}
    return {"results": results, "daily_returns": daily_out}


def aggregate(parts: list[dict], prior_sharpes: list[float]) -> dict:
    """Merge shards; deflated Sharpe over every v3 trial plus the v1/v2 ones."""
    results: dict[str, dict] = {}
    for part in parts:
        results.update(part["results"])
    spy = results.pop("spy")
    names = [t.name for t in trials() if t.name in results]
    trial_pool = [results[n]["validation"]["sharpe"] for n in names] + list(prior_sharpes)
    n_trials = len(trial_pool)
    for n in names:
        v = results[n]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(v["sharpe"], trial_pool, n_periods=v["days"], skew=v["skew"],
                                                   kurtosis=v["kurtosis"], ppy=sc.PPY)
        results[n]["checks"] = sc.criteria(v, spy["validation"])
        results[n]["passed"] = all(results[n]["checks"].values())
    eligible = [n for n in names if results[n]["trade_level"]["train"].get("trades", 0) >= MIN_TRAIN_TRADES]
    selected = sorted(eligible, key=lambda n: -results[n]["trade_level"]["train"]["profit_factor"])[:TOP_N]
    return {"results": results, "spy": spy, "names": names, "selected": selected, "n_trials": n_trials,
            "expected": len(trials())}

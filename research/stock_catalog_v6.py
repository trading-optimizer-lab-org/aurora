"""Stock catalog v6: every long entry so far plus a volume family, x every
exit so far plus volume exits, x 10 filter sets. Pre-registered in
docs/research/STOCK_CATALOG_V6_PREREGISTRATION.md. One shard per setup;
inside a shard the trials run in parallel processes (fork) to use all cores.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2
from aurora.research import stock_catalog_v3 as v3
from aurora.research import stock_catalog_v4 as v4
from aurora.research import stock_catalog_v5 as v5
from aurora.research import stock_trades as st

OLD_SETUPS = (["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S2T", "S10", "S11", "S12", "S13", "S14"]
              + [f"S{n}" for n in range(18, 26)] + [f"S{n}" for n in range(26, 46)])
VOLUME_SETUPS = [f"S{n}" for n in range(46, 56)]
SETUPS = OLD_SETUPS + VOLUME_SETUPS
EXITS = ["X5", "XS10", "XS20", "XS50", "XH3", "XT2", "XT3", "XT5", "XT8", "XE21", "XS50T60", "XO25", "XBE",
         "XR3", "XTIME20", "XTIME60", "XLOW10", "XLOW20", "XRSI80", "XEXT", "XWK", "XC_climax", "XC_obvweak"]
FILTER_SETS = {
    "G0": (),
    "G1": ("MF", "IND50", "ADR4"),
    "G2": ("SPX200", "IND50", "ADR4"),
    "G3": ("MF", "IND85", "ADR4"),
    "G4": ("MF", "IND50", "ADR4", "RS80"),
    "G5": ("MF", "IND50", "LIQ500"),
    "G6": ("ADR4",),
    "G7": ("IND85",),
    "G8": ("MF", "VOL"),
    "G9": ("MF", "IND50", "ADR4", "VOL"),
}
MIN_TRAIN_TRADES = v3.MIN_TRAIN_TRADES
TOP_N = 25


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str
    exit: str
    filters: tuple[str, ...]


def trials() -> list[Trial]:
    return [Trial(f"{s}_{x}_{g}", s, x, fs) for s in SETUPS for x in EXITS for g, fs in FILTER_SETS.items()]


def shard_groups(shard: int, shards: int) -> list[str]:
    return [g for k, g in enumerate(SETUPS) if k % shards == shard]


def obv(C: pd.DataFrame, V: pd.DataFrame) -> pd.DataFrame:
    return (np.sign(C.diff()).fillna(0.0) * V).cumsum()


def volume_context(O, H, L, C, V, ind) -> dict:
    ob = obv(C, V)
    clv = ((C - L) - (H - C)) / (H - L).replace(0, np.nan)
    ad = (clv.fillna(0.0) * V).cumsum()
    upv = V.where(C > C.shift(1), 0.0).rolling(50, min_periods=50).sum()
    dnv = V.where(C < C.shift(1), 0.0).rolling(50, min_periods=50).sum()
    ud = upv / dnv.replace(0, np.nan)
    return {"obv": ob, "ad": ad, "ud": ud, "vol_ok": (ob > sc.sma(ob, 50)) & (ud >= 1.2)}


def build_volume(key: str, O, H, L, C, V, ind, vc: dict):
    adr, s50, v50 = ind["adr"], ind["sma50"], ind["vol50_prior"]
    s200 = sc.sma(C, 200)
    ob, ad, ud = vc["obv"], vc["ad"], vc["ud"]
    if key == "S46":  # OBV at a 50-day high while price is within 5% of its own
        sig = (ob >= ob.rolling(50, min_periods=50).max()) & (C >= 0.95 * C.rolling(50, min_periods=50).max()) & (C > s50)
        return sig, C * (1 - 2 * adr)
    if key == "S47":  # accumulation/distribution line at a 50-day high and rising, above EMA21
        sig = (ad >= ad.rolling(50, min_periods=50).max()) & (ad > ad.shift(20)) & (C > ind["ema21"])
        return sig, L.rolling(5, min_periods=5).min()
    if key == "S48":  # up/down volume ratio (50 days) >= 1.5 and a new 20-day high
        sig = (ud >= 1.5) & (C > s50) & (s50 > s50.shift(10)) & (C > H.shift(1).rolling(20, min_periods=20).max())
        return sig, L.rolling(10, min_periods=10).min()
    if key == "S49":  # >= 5 accumulation days and <= 2 distribution days in 20
        acc = ((C > C.shift(1)) & (V > v50)).astype(float).rolling(20, min_periods=20).sum()
        dist = ((C < C.shift(1)) & (V > v50)).astype(float).rolling(20, min_periods=20).sum()
        return (acc >= 5) & (dist <= 2) & (C > s50), C * (1 - 2 * adr)
    if key == "S50":  # close crosses above the 50-day volume-weighted average price
        vwap = (C * V).rolling(50, min_periods=50).sum() / V.rolling(50, min_periods=50).sum()
        return (C > vwap) & (C.shift(1) <= vwap.shift(1)) & (C > s200), L
    if key == "S51":  # pure volume spike closing strong
        return (V >= 5 * v50) & (C >= L + 0.8 * (H - L)) & (C > C.shift(1)), L
    if key == "S52":  # driest 20-day volume of 120 days, then 2 x volume breakout
        v20 = V.shift(1).rolling(20, min_periods=20).mean()
        dry = (v20 <= v20.rolling(120, min_periods=120).min() * 1.05).astype(float).rolling(10, min_periods=10).max() > 0
        sig = dry & (V >= 2 * v50) & (C > H.shift(1).rolling(20, min_periods=20).max())
        return sig, L.rolling(10, min_periods=10).min()
    if key == "S53":  # price-volume trend crosses above its 50-day EMA
        pvt = (C.pct_change(fill_method=None).fillna(0.0) * V).cumsum()
        e = sc.ema(pvt, 50)
        return (pvt > e) & (pvt.shift(1) <= e.shift(1)) & (C > s50), C * (1 - 2 * adr)
    if key == "S54":  # high-volume hammer after a 20% decline
        sig = (C / C.shift(20) <= 0.8) & (V >= 4 * v50) & (C >= L + 0.66 * (H - L))
        return sig, L
    if key == "S55":  # high-volume reclaim of SMA50
        sig = (C > s50) & (C.shift(1) <= s50.shift(1)) & (V >= 2 * v50) & (s200 < C)
        return sig, L.rolling(5, min_periods=5).min()
    raise KeyError(key)


def mask_v6(sig, ind, filters, extra, own_universe: bool) -> pd.DataFrame:
    m = v4.mask_v4(sig, ind, tuple(f for f in filters if f != "VOL"), extra, own_universe)
    if "VOL" in filters:
        m = m & extra["vol_ok"]
    return m.fillna(False).astype(bool)


_G: dict = {}


def _run_trial(t: Trial) -> tuple[str, dict]:
    g = _G
    mask = mask_v6(g["sig"], g["ind"], t.filters, g["extra"], own_universe=(t.setup == "S25"))
    d = sc.simulate(g["panel"], g["ind"], mask, g["stop"], t.exit, g["cash"], g["rank"])
    tl = st.trade_list(g["panel"], g["ind"], mask, g["stop"], t.exit)
    return t.name, v3._summary(d["return"], tl, g["cash"], int(mask.loc[sc.TRAIN_START:].to_numpy().sum()))


def run_shard(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series, groups: list[str], workers: int = 4,
              limit: int | None = None) -> dict:
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the stock catalog v6")
    keep = sc.ever_in_universe(panel)
    if "S25" in groups:
        keep = keep.union(panel["close"].columns[v4.ipo_universe(panel["close"], panel["volume"]).any()])
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    ind["low10"] = L.shift(1).rolling(10, min_periods=10).min()
    ind["low20"] = L.shift(1).rolling(20, min_periods=20).min()
    ind["rsi14"] = v5.rsi(C, 14)
    ind["week_end"] = pd.Series(sc.week_ends(dates), index=dates)
    vc = volume_context(O, H, L, C, V, ind)
    ind["XC_climax"] = ((V >= 3 * ind["vol50_prior"]) & (C / C.shift(1) >= 1.05)).fillna(False)
    ind["XC_obvweak"] = (vc["obv"] < sc.ema(vc["obv"], 20)).fillna(False)
    ctx = {"sma200": sc.sma(C, 200), "stage2": v2.stage2(C), "week_end": sc.week_ends(dates),
           "month_end": v5.month_ends(dates), "index": index_close.reindex(dates).ffill()}
    extra = {"liq500": v2.universe_top(panel, 500), "vol_ok": vc["vol_ok"]}
    results: dict[str, dict] = {}
    for g in groups:
        if g in VOLUME_SETUPS:
            sig, stop = build_volume(g, O, H, L, C, V, ind, vc)
        elif g in v5.SETUPS:
            sig, stop = v5.build(g, O, H, L, C, V, ind, ctx)
        elif g == "S2T":
            sig, stop = v2.setup_s2t(O, H, L, C, V, ind, index_close)
        else:
            sig, stop = v4.build_setup(g, O, H, L, C, V, ind)
        todo = [t for t in trials() if t.setup == g][:limit]
        _G.update(panel=panel, ind=ind, sig=sig.fillna(False).astype(bool), stop=stop, extra=extra, cash=cash,
                  rank=ind["rs"].fillna(0.0))
        if workers > 1 and os.name != "nt":
            with mp.get_context("fork").Pool(workers) as pool:
                for name, res in pool.imap_unordered(_run_trial, todo, chunksize=2):
                    results[name] = res
        else:
            for t in todo:
                name, res = _run_trial(t)
                results[name] = res
        print(f"{g}: {len(todo)} trials done", flush=True)
        _G.clear()
        del sig, stop
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[sc.TRAIN_START:].fillna(0.0)
    results["spy"] = {p: sc.metrics(spy.loc[a:b], cash) for p, (a, b) in sc.PERIODS.items()}
    return {"results": results}


def aggregate(parts: list[dict], prior_sharpes: list[float]) -> dict:
    results: dict[str, dict] = {}
    for part in parts:
        results.update(part["results"])
    spy = results.pop("spy")
    names = [t.name for t in trials() if t.name in results]
    pool = [results[n]["validation"]["sharpe"] for n in names] + list(prior_sharpes)
    for n in names:
        v = results[n]["validation"]
        v["deflated_sharpe"] = mab.deflated_sharpe(v["sharpe"], pool, n_periods=v["days"], skew=v["skew"],
                                                   kurtosis=v["kurtosis"], ppy=sc.PPY)
        results[n]["checks"] = sc.criteria(v, spy["validation"])
        results[n]["passed"] = all(results[n]["checks"].values())
    tl = lambda n, p: results[n]["trade_level"][p]  # noqa: E731
    eligible = [n for n in names if tl(n, "train").get("trades", 0) >= MIN_TRAIN_TRADES]
    selected = sorted(eligible, key=lambda n: -tl(n, "train")["profit_factor"])[:TOP_N]
    stable = sorted([n for n in names if all(tl(n, p).get("trades", 0) >= 200 and tl(n, p)["profit_factor"] >= 1.3
                                             for p in ("train", "validation"))],
                    key=lambda n: -min(tl(n, "train")["profit_factor"], tl(n, "validation")["profit_factor"]))
    return {"results": results, "spy": spy, "names": names, "selected": selected, "stable": stable,
            "n_trials": len(pool), "expected": len(trials())}

"""Stock catalog v4: 16 setups x 8 exits x 6 filter sets, as pre-registered
in docs/research/STOCK_CATALOG_V4_PREREGISTRATION.md. One shard per setup.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from aurora.research import multiasset_baselines as mab
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2
from aurora.research import stock_catalog_v3 as v3
from aurora.research import stock_trades as st

SETUPS = ["S1", "S3", "S6", "S7", "S12", "S13", "S14", "S18", "S19", "S20", "S21", "S22", "S23", "S24", "S25"]
EXITS = ["XS20", "XS50", "XT3", "XE21", "XT2", "XT5", "XS50T60", "XO25"]
FILTER_SETS = {
    "G0": (),
    "G1": ("MF", "IND50", "ADR4"),
    "G2": ("SPX200", "IND50", "ADR4"),
    "G3": ("MF", "IND85", "ADR4"),
    "G4": ("MF", "IND50", "ADR4", "RS80"),
    "G5": ("MF", "IND50", "LIQ500"),
}
MIN_TRAIN_TRADES = v3.MIN_TRAIN_TRADES
TOP_N = v3.TOP_N


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str
    exit: str
    filters: tuple[str, ...]


def trials() -> list[Trial]:
    return [Trial(f"{s}_{x}_{g}", s, x, fs) for s in SETUPS for x in EXITS for g, fs in FILTER_SETS.items()]


def setup_s18(O, H, L, C, V, ind):
    down_vol = V.where(C < C.shift(1), 0.0)
    s10, s50 = ind["sma10"], ind["sma50"]
    sig = ((C > C.shift(1)) & (V > down_vol.shift(1).rolling(10, min_periods=10).max()) & (C > s10) & (C > s50)
           & (s50 > s50.shift(10)) & (C / s10 - 1 < 0.05))
    return sig, L.rolling(3, min_periods=3).min()


def setup_s19(O, H, L, C, V, ind):
    e20, e50 = sc.ema(C, 20), sc.ema(C, 50)
    sig = (e20 > e50) & (e20.shift(1) <= e50.shift(1)) & (C > sc.sma(C, 200))
    return sig, C * (1 - 3 * ind["adr"])


def setup_s20(O, H, L, C, V, ind):
    return C > H.shift(1).rolling(55, min_periods=55).max(), C * (1 - 2 * ind["adr"])


def setup_s21(O, H, L, C, V, ind):
    m20 = ind["sma20"]
    sd = C.rolling(20, min_periods=20).std()
    width = 4 * sd / m20
    tight = (width <= 1.05 * width.rolling(120, min_periods=120).min()).astype(float)
    recent = tight.shift(1).rolling(5, min_periods=5).max() > 0
    sig = recent & (C > m20 + 2 * sd) & (V >= 1.5 * ind["vol50_prior"])
    return sig, m20


def setup_s22(O, H, L, C, V, ind):
    e10, e21, s50 = sc.ema(C, 10), ind["ema21"], ind["sma50"]
    sig = (e10 > e21) & (e21 > s50) & (s50 > s50.shift(10)) & (C.shift(1) < e21.shift(1)) & (C > e21)
    return sig, L


def setup_s23(O, H, L, C, V, ind):
    sig = ((O / C.shift(1) >= 1.08) & (V >= 4 * ind["vol50_prior"]) & (C >= L + 0.75 * (H - L))
           & (C.shift(1) < 1.2 * C.shift(64)))
    return sig, L


def setup_s24(O, H, L, C, V, ind):
    down = C < C.shift(1)
    s50 = ind["sma50"]
    sig = (ind["rs"] >= 90) & down & down.shift(1, fill_value=False) & down.shift(2, fill_value=False) \
        & (C > s50) & (s50 > s50.shift(10))
    return sig, C * (1 - 2 * ind["adr"])


def ipo_universe(C: pd.DataFrame, V: pd.DataFrame) -> pd.DataFrame:
    history = C.notna().cumsum()
    dv20 = (C * V).rolling(20, min_periods=20).mean()
    young = (history >= 20) & (history <= 250) & dv20.notna()
    return young & (dv20.where(young).rank(axis=1, ascending=False) <= sc.UNIVERSE_SIZE)


def setup_s25(O, H, L, C, V, ind):
    since_listing_high = H.shift(1).expanding(min_periods=19).max()
    sig = (ipo_universe(C, V) & (C > since_listing_high)
           & (V >= 1.5 * V.shift(1).rolling(20, min_periods=10).mean()))
    return sig, L.rolling(10, min_periods=1).min()


NEW = {"S18": setup_s18, "S19": setup_s19, "S20": setup_s20, "S21": setup_s21, "S22": setup_s22,
       "S23": setup_s23, "S24": setup_s24, "S25": setup_s25}


def mask_v4(sig: pd.DataFrame, ind: dict, filters: tuple[str, ...], extra: dict, own_universe: bool) -> pd.DataFrame:
    m = sig if own_universe else (sig & ind["universe"])
    if "MF" in filters:
        m = m.mul(ind["mf"], axis=0).astype(bool)
    if "SPX200" in filters:
        m = m.mul(ind["index_above_200"], axis=0).astype(bool)
    if "ADR4" in filters:
        m = m & (ind["adr"] >= 0.04)
    if "IND50" in filters:
        m = m & (ind["ind_rs"] >= 50)
    if "IND85" in filters:
        m = m & (ind["ind_rs"] >= 85)
    if "RS80" in filters:
        m = m & (ind["rs"] >= 80)
    if "LIQ500" in filters:
        m = m & extra["liq500"]
    return m.fillna(False).astype(bool)


def build_setup(key: str, O, H, L, C, V, ind):
    if key in NEW:
        return NEW[key](O, H, L, C, V, ind)
    if key in v3.NEW_SETUPS:
        return v3.NEW_SETUPS[key](O, H, L, C, V, ind)
    return sc.SETUPS[key](O, H, L, C, V, ind)


def run_shard(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series, groups: list[str]) -> dict:
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the stock catalog v4")
    keep = sc.ever_in_universe(panel)
    if "S25" in groups:  # young stocks may never reach the 260-day universe before 2020
        keep = keep.union(panel["close"].columns[ipo_universe(panel["close"], panel["volume"]).any()])
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    extra = {"liq500": v2.universe_top(panel, 500)}
    results: dict[str, dict] = {}
    daily_out: dict[str, pd.Series] = {}
    for g in groups:
        sig, stop = build_setup(g, O, H, L, C, V, ind)
        for t in [t for t in trials() if t.setup == g]:
            mask = mask_v4(sig, ind, t.filters, extra, own_universe=(g == "S25"))
            d = sc.simulate(panel, ind, mask, stop, t.exit, cash, ind["rs"].fillna(0.0))
            tl = st.trade_list(panel, ind, mask, stop, t.exit)
            results[t.name] = v3._summary(d["return"], tl, cash, int(mask.loc[sc.TRAIN_START:].to_numpy().sum()))
            daily_out[t.name] = d["return"]
        del sig, stop
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[sc.TRAIN_START:].fillna(0.0)
    results["spy"] = {p: sc.metrics(spy.loc[a:b], cash) for p, (a, b) in sc.PERIODS.items()}
    return {"results": results, "daily_returns": daily_out}


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


def shard_groups(shard: int, shards: int) -> list[str]:
    return [g for k, g in enumerate(SETUPS) if k % shards == shard]

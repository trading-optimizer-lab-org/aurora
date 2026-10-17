"""Stock catalog v5: 20 new entries x 12 exits x 4 filter sets, as
pre-registered in docs/research/STOCK_CATALOG_V5_PREREGISTRATION.md.
One shard per setup; merging reuses v4's aggregate logic.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from aurora.research import multiasset_baselines as mab
from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2
from aurora.research import stock_catalog_v3 as v3
from aurora.research import stock_catalog_v4 as v4
from aurora.research import stock_trades as st

SETUPS = [f"S{n}" for n in range(26, 46)]
EXITS = ["XT5", "XS50", "XT8", "XBE", "XR3", "XTIME20", "XTIME60", "XLOW10", "XLOW20", "XRSI80", "XEXT", "XWK"]
FILTER_SETS = {
    "G0": (),
    "G1": ("MF", "IND50", "ADR4"),
    "G3": ("MF", "IND85", "ADR4"),
    "G4": ("MF", "IND50", "ADR4", "RS80"),
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


def shard_groups(shard: int, shards: int) -> list[str]:
    return [g for k, g in enumerate(SETUPS) if k % shards == shard]


def rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def month_ends(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(index, index=index)
    return s.groupby(index.to_period("M")).transform("max").eq(s).to_numpy()


def _col(flags: np.ndarray, like: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.broadcast_to(flags[:, None], like.shape), index=like.index, columns=like.columns)


def build(key: str, O, H, L, C, V, ind, ctx: dict):
    adr, s50, e21, v50 = ind["adr"], ind["sma50"], ind["ema21"], ind["vol50_prior"]
    s200 = ctx["sma200"]
    rising50 = s50 > s50.shift(10)
    rng = (H - L).replace(0, np.nan)
    if key == "S26":  # three strong closes into a new 20-day high
        cr = (C - L) / rng
        strong = (cr >= 0.9) & (cr.shift(1) >= 0.9) & (cr.shift(2) >= 0.9)
        return strong & (C > H.shift(1).rolling(20, min_periods=20).max()), L.rolling(3, min_periods=3).min()
    if key == "S27":  # volume dry-up pullback to EMA21 in Stage 2, then an up day on rising volume
        quiet = V.shift(1).rolling(5, min_periods=5).mean() < 0.6 * v50
        near = (C.shift(1) / e21.shift(1) - 1).abs() < 0.03
        sig = ctx["stage2"] & quiet & near & (C > C.shift(1)) & (V > V.shift(1).rolling(5, min_periods=5).mean()) & (C > e21)
        return sig, L.rolling(5, min_periods=5).min()
    if key == "S28":  # bullish engulfing at the rising SMA50
        engulf = (O < C.shift(1)) & (C > O.shift(1)) & (C > O) & (C.shift(1) < O.shift(1))
        return engulf & rising50 & (C > s200) & (L <= s50 * 1.02), L
    if key == "S29":  # Larry Williams "oops": opens below yesterday's low, closes up, in an uptrend
        return (O < L.shift(1)) & (C > C.shift(1)) & (C.shift(1) > s50.shift(1)) & rising50, L
    if key == "S30":  # weekly close above the highest close of ~26 weeks
        sig = (C > C.shift(1).rolling(130, min_periods=130).max()) & _col(ctx["week_end"], C)
        return sig, C * (1 - 3 * adr)
    if key == "S31":  # RS line at a 1-year high before the price (O'Neil)
        rsl = C.div(ctx["index"], axis=0)
        sig = (rsl >= rsl.rolling(252, min_periods=252).max()) & (C < 0.95 * C.rolling(252, min_periods=252).max()) & (C > s50)
        return sig, C * (1 - 2 * adr)
    if key == "S32":  # 12-1 month momentum, top decile, month end
        mom = C.shift(21) / C.shift(252) - 1
        top = mom.where(ind["universe"]).rank(axis=1, pct=True) >= 0.9
        return top & (C > s200) & _col(ctx["month_end"], C), C * (1 - 3 * adr)
    if key == "S33":  # reclaim of SMA20 near the 52-week low on volume
        low52 = L.rolling(252, min_periods=252).min()
        s20 = ind["sma20"]
        sig = (C <= 1.15 * low52) & (C > s20) & (C.shift(1) <= s20.shift(1)) & (V >= 1.5 * v50)
        return sig, L.rolling(10, min_periods=10).min()
    if key == "S34":  # capitulation reversal
        sig = (C / C.shift(10) <= 0.75) & (V >= 3 * v50) & (C >= L + 0.5 * (H - L)) & (C > O)
        return sig, L
    if key == "S35":  # thrust day: range >= 2 x ADR, close near the high, in an uptrend
        sig = ((H - L) / C.shift(1) >= 2 * adr.shift(1)) & (C >= L + 0.8 * (H - L)) & (C > C.shift(1)) & (C > s50) & rising50
        return sig, L
    if key == "S36":  # golden cross
        return (s50 > s200) & (s50.shift(1) <= s200.shift(1)), C * (1 - 3 * adr)
    if key == "S37":  # MACD cross above signal while positive, above SMA200
        macd = sc.ema(C, 12) - sc.ema(C, 26)
        sig9 = sc.ema(macd, 9)
        return (macd > sig9) & (macd.shift(1) <= sig9.shift(1)) & (macd > 0) & (C > s200), C * (1 - 2 * adr)
    if key == "S38":  # Keltner breakout: close above EMA20 + 2 x ADR (in price)
        e20 = sc.ema(C, 20)
        upper = e20 + 2 * adr * C
        return (C > upper) & (C.shift(1) <= upper.shift(1)) & (C > s50), e20
    if key == "S39":  # pullback after a thrust (>= 15% in 3 days within the last 10 days)
        thrust = (C / C.shift(3) - 1).shift(3).rolling(8, min_periods=8).max() >= 0.15
        hi10 = H.shift(1).rolling(10, min_periods=10).max()
        pulled = (C.shift(1) <= 0.93 * hi10) & (C.shift(1) >= 0.85 * hi10)
        return thrust & pulled & (C > C.shift(1)), L.rolling(5, min_periods=5).min()
    if key == "S40":  # close below the lower Bollinger band while above SMA200
        sd = C.rolling(20, min_periods=20).std()
        return (C < ind["sma20"] - 2 * sd) & (C > s200), C * (1 - 3 * adr)
    if key == "S41":  # staircase: five higher lows in a tight range above EMA21
        hl = L > L.shift(1)
        five = hl & hl.shift(1, fill_value=False) & hl.shift(2, fill_value=False) & hl.shift(3, fill_value=False) & hl.shift(4, fill_value=False)
        tight = (H.rolling(5, min_periods=5).max() - L.rolling(5, min_periods=5).min()) / C <= 2 * adr
        return five & tight & (C > e21), L.rolling(5, min_periods=5).min()
    if key == "S42":  # top stock in a top industry breaking a 20-day high
        sig = (ind["ind_rs"] >= 90) & (ind["rs"] >= 95) & (C > H.shift(1).rolling(20, min_periods=20).max())
        return sig, L.rolling(10, min_periods=10).min()
    if key == "S43":  # breakout of a shallow 60-day base on volume
        hi60 = H.shift(1).rolling(60, min_periods=60).max()
        lo60 = L.shift(1).rolling(60, min_periods=60).min()
        sig = ((hi60 - lo60) / hi60 <= 0.15) & (C > hi60) & (V >= 1.5 * v50)
        return sig, L.rolling(10, min_periods=10).min()
    if key == "S44":  # two tight closes, then a break above both highs in an uptrend
        tight = ((C.shift(1) / C.shift(2) - 1).abs() < 0.005) & ((C.shift(2) / C.shift(3) - 1).abs() < 0.005)
        sig = tight & (C > np.maximum(H.shift(1), H.shift(2))) & (C > s50) & rising50
        return sig, np.minimum(L.shift(1), L.shift(2))
    if key == "S45":  # momentum ignition: top 1% 5-day return above SMA50
        r5 = (C / C.shift(5) - 1).where(ind["universe"]).rank(axis=1, pct=True)
        return (r5 >= 0.99) & (C > s50), C * (1 - 2 * adr)
    raise KeyError(key)


def run_shard(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series, groups: list[str]) -> dict:
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the stock catalog v5")
    keep = sc.ever_in_universe(panel)
    panel = {k: v[keep] for k, v in panel.items()}
    dates = panel["close"].index
    cash = cash_index.reindex(dates).ffill().pct_change(fill_method=None).fillna(0.0)
    ind = sc.indicators(panel, index_close, industry.reindex(keep))
    O, H, L, C, V = (panel[k] for k in ("open", "high", "low", "close", "volume"))
    ind["low10"] = L.shift(1).rolling(10, min_periods=10).min()
    ind["low20"] = L.shift(1).rolling(20, min_periods=20).min()
    ind["rsi14"] = rsi(C, 14)
    ind["week_end"] = pd.Series(sc.week_ends(dates), index=dates)
    ctx = {"sma200": sc.sma(C, 200), "stage2": v2.stage2(C), "week_end": sc.week_ends(dates),
           "month_end": month_ends(dates), "index": index_close.reindex(dates).ffill()}
    extra = {"liq500": None}
    results: dict[str, dict] = {}
    daily_out: dict[str, pd.Series] = {}
    for g in groups:
        sig, stop = build(g, O, H, L, C, V, ind, ctx)
        sig = sig.fillna(False).astype(bool)
        for t in [t for t in trials() if t.setup == g]:
            mask = v4.mask_v4(sig, ind, t.filters, extra, own_universe=False)
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

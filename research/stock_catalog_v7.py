"""Stock catalog v7: 80 long entries x 30 exits x 14 filter sets x 7 initial
stops = 235,200 trials. Pre-registered in
docs/research/STOCK_CATALOG_V7_PREREGISTRATION.md. One shard per (entry, exit
group); inside a shard the trials run in forked processes and each returns one
compact row of metrics instead of daily returns.
"""
from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from aurora.research import stock_catalog as sc
from aurora.research import stock_catalog_v2 as v2
from aurora.research import stock_catalog_v4 as v4
from aurora.research import stock_catalog_v5 as v5
from aurora.research import stock_catalog_v6 as v6
from aurora.research import stock_trades as st

NEW_SETUPS = [f"S{n}" for n in range(56, 85)]
SETUPS = v6.SETUPS + NEW_SETUPS
EXITS = v6.EXITS + ["XCH", "XSAR", "XDEC", "XS100", "XLOW50", "XKELL", "XT8H"]
EXIT_GROUPS = [EXITS[k::4] for k in range(4)]
FILTER_SETS = {
    **v6.FILTER_SETS,
    "G10": ("CALM", "MF"),
    "G11": ("BREADTH", "ADR4"),
    "G12": ("CALM", "IND85", "ADR4"),
    "G13": ("MF", "IND50", "ADR4", "NOSEPOCT"),
}
STOPS: dict[str, float | None] = {"SS": None, "A1": 1.0, "A15": 1.5, "A2": 2.0, "A3": 3.0, "A5": 5.0, "A8": 8.0}
SHARDS = len(SETUPS) * len(EXIT_GROUPS)
PERIODS = {
    **sc.PERIODS,
    "val1": (pd.Timestamp("2011-01-01"), pd.Timestamp("2015-12-31")),
    "val2": (pd.Timestamp("2016-01-01"), pd.Timestamp("2020-12-31")),
}
MIN_TRAIN_TRADES = 300
TOP_N = 50
ROBUST_PF, ROBUST_TRADES = 1.3, 100
MARGINAL_MIN_TRADES = 50  # as in the v6 report
PORT_KEYS = ("days", "cagr", "sharpe", "sharpe_monthly", "sortino_monthly", "max_drawdown", "skew", "kurtosis")
TRADE_KEYS = ("trades", "win_rate", "avg_return", "median_return", "profit_factor", "total_return", "avg_days",
              "top5pct_share")
# Engine inputs cast to float32 once per shard (the engines cast them anyway).
ENGINE_KEYS = ("adr", "sma5", "sma10", "sma20", "sma50", "ema21", "sma100", "ema10", "low10", "low20", "low50",
               "rsi14")
CONFLUENCE = {"S77": ("S10", "S18"), "S78": ("S14", "S27"), "S79": ("S36", "S31"), "S80": ("S7", "IND85"),
              "S81": ("S3", "OBV50"), "S82": ("S12", "UD15")}


@dataclass(frozen=True)
class Trial:
    name: str
    setup: str
    exit: str
    group: str
    stop: str


def _trial(s: str, x: str, g: str, k: str) -> Trial:
    return Trial(f"{s}_{x}_{g}_{k}", s, x, g, k)


def trials() -> list[Trial]:
    return [_trial(s, x, g, k) for s in SETUPS for x in EXITS for g in FILTER_SETS for k in STOPS]


def shard_setup(shard: int) -> str:
    return SETUPS[shard // len(EXIT_GROUPS)]


def shard_trials(shard: int) -> list[Trial]:
    s, exits = shard_setup(shard), EXIT_GROUPS[shard % len(EXIT_GROUPS)]
    return [_trial(s, x, g, k) for x in exits for g in FILTER_SETS for k in STOPS]


def calm(index_close: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """S&P 500 20-day realised volatility below its 252-day median."""
    rv = index_close.reindex(dates).ffill().pct_change(fill_method=None).rolling(20, min_periods=20).std()
    return rv < rv.rolling(252, min_periods=252).median()


def _rank(x: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    return x.where(universe).rank(axis=1, pct=True)


def _per_stock(by_industry: pd.DataFrame, industry: pd.Series, like: pd.DataFrame) -> pd.DataFrame:
    out = by_industry.reindex(columns=industry.to_numpy())
    out.columns = like.columns
    return out


def _both(a: pd.DataFrame, b: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """One signal fires while the other fired within the last n days (today included)."""
    a, b = a.fillna(False).astype(bool), b.fillna(False).astype(bool)
    ra = a.astype(float).rolling(n, min_periods=1).max() > 0
    rb = b.astype(float).rolling(n, min_periods=1).max() > 0
    return (a & rb) | (b & ra)


def _holiday_eves(dates: pd.DatetimeIndex) -> np.ndarray:
    d = dates.to_numpy().astype("datetime64[D]")
    return np.append(np.busday_count(d[:-1], d[1:]) > 1, False)


def _new_year_firsts(dates: pd.DatetimeIndex) -> np.ndarray:
    years = pd.Series(dates.year, index=dates)
    return (dates.month == 1) & (years.diff().fillna(1).to_numpy() != 0)


def build_new(key: str, O, H, L, C, V, ind: dict, ctx: dict, vc: dict):
    adr, s50, e21, e10, v50 = ind["adr"], ind["sma50"], ind["ema21"], ind["ema10"], ind["vol50_prior"]
    s200, uni, industry = ctx["sma200"], ind["universe"], ctx["industry"]
    rng = (H - L).replace(0, np.nan)
    body = (C - O).abs()
    hi20 = H.shift(1).rolling(20, min_periods=20).max()
    month_end = v5._col(ctx["month_end"], C)
    if key == "S56":  # hammer at a rising EMA21 or SMA50
        lower, upper = np.minimum(O, C) - L, H - np.maximum(O, C)
        hammer = (lower >= 2 * body) & (upper <= body) & (C >= L + 0.6 * rng)
        at_ma = (((L <= e21) & (C > e21) & (e21 > e21.shift(5)))
                 | ((L <= s50) & (C > s50) & (s50 > s50.shift(10))))
        return hammer & at_ma, L
    if key == "S57":  # morning star above SMA200
        b2 = (O - C).shift(2)
        sig = ((b2 > 0) & (b2 >= 0.6 * rng.shift(2)) & (body.shift(1) <= 0.3 * b2)
               & (np.maximum(O, C).shift(1) <= C.shift(2)) & (C > O) & (C >= (O.shift(2) + C.shift(2)) / 2)
               & (C > s200))
        return sig, L.rolling(3, min_periods=3).min()
    if key == "S58":  # three white soldiers above SMA50
        up = (C > O) & (C >= L + 0.7 * rng)
        soldier = up & (C > C.shift(1)) & (O >= O.shift(1)) & (O <= C.shift(1))
        sig = up.shift(2, fill_value=False) & soldier.shift(1, fill_value=False) & soldier & (C > s50)
        return sig, L.rolling(3, min_periods=3).min()
    if key == "S59":  # inside-bar breakout in an uptrend
        inside = (H.shift(1) < H.shift(2)) & (L.shift(1) > L.shift(2))
        trend = (C > s50) & (s50 > s50.shift(10)) & (s50 > s200)
        return inside & (C > H.shift(1)) & trend, L.shift(1)
    if key == "S60":  # NR4 breakout above SMA50
        r = H - L
        nr4 = r.shift(1) <= r.shift(1).rolling(4, min_periods=4).min()
        return nr4 & (C > H.shift(1)) & (C > s50), L.shift(1)
    if key == "S61":  # last trading day of the month, RS >= 80
        return month_end & (ind["rs"] >= 80), C * (1 - 2 * adr)
    if key == "S62":  # day before a market holiday, RS >= 70
        return v5._col(_holiday_eves(C.index), C) & (ind["rs"] >= 70), C * (1 - 2 * adr)
    if key == "S63":  # first trading day of January, RS >= 90
        return v5._col(_new_year_firsts(C.index), C) & (ind["rs"] >= 90), C * (1 - 2 * adr)
    if key == "S64":  # IBS < 0.2 above SMA200
        return ((C - L) / rng < 0.2) & (C > s200), C * (1 - 3 * adr)
    if key == "S65":  # RSI(2) < 5 above SMA200
        return (sc.rsi2(C) < 5) & (C > s200), C * (1 - 3 * adr)
    if key == "S66":  # below the lower Bollinger band with RSI(14) < 30, above SMA200
        sd = C.rolling(20, min_periods=20).std()
        return (C < ind["sma20"] - 2 * sd) & (ind["rsi14"] < 30) & (C > s200), C * (1 - 3 * adr)
    if key == "S67":  # three closes below EMA20 - 1.5 x ADR, above SMA200
        below = C < sc.ema(C, 20) * (1 - 1.5 * adr)
        sig = below & below.shift(1, fill_value=False) & below.shift(2, fill_value=False) & (C > s200)
        return sig, C * (1 - 3 * adr)
    if key == "S68":  # weekly-equivalent MACD above signal, EMA21 touch, up close above EMA10
        macd = sc.ema(C, 60) - sc.ema(C, 130)
        touch = (L <= e21).astype(float).rolling(3, min_periods=3).max() > 0
        sig = (macd > sc.ema(macd, 45)) & touch & (C > C.shift(1)) & (C > e10)
        return sig, L.rolling(3, min_periods=3).min()
    if key == "S69":  # previous month closed at an all-time monthly high, then a 20-day-high breakout
        mc = C.loc[ctx["month_end"]]
        ath = (mc >= mc.cummax()) & (mc.notna().cumsum() >= 12)
        prev = ath.astype(float).reindex(C.index).ffill().shift(1) > 0
        return prev & (C > hi20), L.rolling(10, min_periods=10).min()
    if key == "S70":  # lowest 10% 63-day volatility above SMA200, month end
        vol = C.pct_change(fill_method=None).rolling(63, min_periods=63).std()
        return month_end & (_rank(vol, uni) <= 0.10) & (C > s200), C * (1 - 2 * adr)
    if key == "S71":  # frog in the pan: top 30% 12-1 momentum and top 20% share of up days, month end
        mom = C.shift(21) / C.shift(252) - 1
        updays = (C > C.shift(1)).astype(float).rolling(252, min_periods=252).mean()
        return month_end & (_rank(mom, uni) >= 0.70) & (_rank(updays, uni) >= 0.80), C * (1 - 2 * adr)
    if key == "S72":  # top 10% closeness to the 52-week high, month end
        near = C / H.rolling(252, min_periods=252).max()
        return month_end & (_rank(near, uni) >= 0.90), C * (1 - 2 * adr)
    if key == "S73":  # bottom 10% 21-day return while above SMA200, month end
        r21 = C / C.shift(21) - 1
        return month_end & (_rank(r21, uni) <= 0.10) & (C > s200), C * (1 - 3 * adr)
    if key == "S74":  # 20-day return >= 10 points above the industry median, 20-day-high breakout
        r20 = C / C.shift(20) - 1
        med = _per_stock(r20.where(uni).T.groupby(industry).median().T, industry, C)
        return (r20 >= med + 0.10) & (C > hi20), L.rolling(10, min_periods=10).min()
    if key == "S75":  # industry equal-weight index at a 252-day high, stock RS >= 90 at a 20-day high
        ret = C.pct_change(fill_method=None).where(uni)
        grouped = ret.T.groupby(industry)
        level = (1 + grouped.mean().T.fillna(0.0)).cumprod()
        at_high = (level >= level.rolling(252, min_periods=252).max()) & (grouped.count().T >= 3)
        sig = _per_stock(at_high, industry, C).fillna(False).astype(bool) & (ind["rs"] >= 90) & (C > hi20)
        return sig, L.rolling(10, min_periods=10).min()
    if key == "S76":  # ADR at a 252-day low within the last 5 days, then a 20-day-high breakout
        low = (adr <= adr.rolling(252, min_periods=252).min()).astype(float).shift(1).rolling(5, min_periods=5).max()
        return (low > 0) & (C > hi20), L.rolling(10, min_periods=10).min()
    if key in CONFLUENCE:
        first, second = CONFLUENCE[key]
        a = build(first, O, H, L, C, V, ind, ctx, vc)[0]
        if second == "IND85":
            b = ind["ind_rs"] >= 85
        elif second == "OBV50":
            b = vc["obv"] >= vc["obv"].rolling(50, min_periods=50).max()
        elif second == "UD15":
            b = vc["ud"] >= 1.5
        else:
            b = build(second, O, H, L, C, V, ind, ctx, vc)[0]
        return _both(a, b), L.rolling(5, min_periods=5).min()
    if key == "S83":  # within 2% of the 52-week high after a 5-day volume dry-up, up close
        dry = V.shift(1).rolling(5, min_periods=5).mean() < 0.7 * v50
        sig = (C >= 0.98 * H.rolling(252, min_periods=252).max()) & dry & (C > C.shift(1))
        return sig, L.rolling(5, min_periods=5).min()
    if key == "S84":  # inside-week breakout above SMA50
        hi5, lo5 = H.shift(1).rolling(5, min_periods=5).max(), L.shift(1).rolling(5, min_periods=5).min()
        sig = (hi5 < hi5.shift(5)) & (lo5 > lo5.shift(5)) & (C > hi5) & (C > s50)
        return sig, lo5
    raise KeyError(key)


def build(key: str, O, H, L, C, V, ind: dict, ctx: dict, vc: dict):
    if key in NEW_SETUPS:
        return build_new(key, O, H, L, C, V, ind, ctx, vc)
    if key in v6.VOLUME_SETUPS:
        return v6.build_volume(key, O, H, L, C, V, ind, vc)
    if key in v5.SETUPS:
        return v5.build(key, O, H, L, C, V, ind, ctx)
    if key == "S2T":
        return v2.setup_s2t(O, H, L, C, V, ind, ctx["index_close"])
    return v4.build_setup(key, O, H, L, C, V, ind)


def mask_v7(sig: pd.DataFrame, ind: dict, filters: tuple[str, ...], extra: dict, own_universe: bool) -> pd.DataFrame:
    new = ("CALM", "BREADTH", "NOSEPOCT")
    m = v6.mask_v6(sig, ind, tuple(f for f in filters if f not in new), extra, own_universe)
    if "CALM" in filters:
        m = m.mul(extra["calm"], axis=0).astype(bool)
    if "BREADTH" in filters:
        m = m.mul(extra["breadth"], axis=0).astype(bool)
    if "NOSEPOCT" in filters:
        m = m.mul(pd.Series(~m.index.month.isin([9, 10]), index=m.index), axis=0).astype(bool)
    return m


def _row(t: Trial, daily: pd.Series, trades: pd.DataFrame, cash: pd.Series, signals: int) -> dict:
    row: dict = {"name": t.name, "setup": t.setup, "exit": t.exit, "filters": t.group, "stop": t.stop,
                 "signals": signals}
    for p, (a, b) in PERIODS.items():
        m = sc.metrics(daily.loc[a:b], cash)
        row.update({f"{p}_{k}": m.get(k, np.nan) for k in PORT_KEYS})
        ts = st.trade_stats(trades[(trades["entry_date"] >= a) & (trades["entry_date"] <= b)])
        row.update({f"{p}_tl_{k}": ts.get(k, np.nan) for k in TRADE_KEYS})
    return row


_G: dict = {}


def _run_trial(t: Trial) -> dict:
    g = _G
    mask, stop = g["masks"][t.group], g["stops"][t.stop]
    d = sc.simulate(g["panel"], g["ind"], mask, stop, t.exit, g["cash"], g["rank"])
    tl = st.trade_list(g["panel"], g["ind"], mask, stop, t.exit)
    return _row(t, d["return"], tl, g["cash"], g["signals"][t.group])


def run_shard(panel: dict[str, pd.DataFrame], index_close: pd.Series, spy_close: pd.Series,
              cash_index: pd.Series, industry: pd.Series, shard: int, workers: int = 4,
              limit: int | None = None) -> list[dict]:
    if panel["close"].index.max() >= sc.LOCKED_START:
        raise ValueError("locked period data reached the stock catalog v7")
    setup = shard_setup(shard)
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
    extra = {"liq500": v2.universe_top(panel, 500), "vol_ok": vc["vol_ok"], "calm": calm(index_close, dates),
             "breadth": v2.breadth_on(C, ind["universe"])}
    sig, own_stop = build(setup, O, H, L, C, V, ind, ctx, vc)
    sig = sig.fillna(False).astype(bool)
    masks = {g: mask_v7(sig, ind, fs, extra, own_universe=(setup == "S25")) for g, fs in FILTER_SETS.items()}
    signals = {g: int(m.loc[sc.TRAIN_START:].to_numpy().sum()) for g, m in masks.items()}
    stops = {k: (own_stop if f is None else C * (1 - f * ind["adr"])).astype(np.float32) for k, f in STOPS.items()}
    del sig, own_stop, vc, ctx, extra
    for k in ENGINE_KEYS:
        ind[k] = ind[k].astype(np.float32)
    todo = shard_trials(shard)[:limit]
    _G.update(panel=panel, ind=ind, masks=masks, stops=stops, signals=signals, cash=cash,
              rank=ind["rs"].fillna(0.0).astype(np.float32))
    rows: list[dict] = []
    if workers > 1 and os.name != "nt":
        with mp.get_context("fork").Pool(workers) as pool:
            for row in pool.imap_unordered(_run_trial, todo, chunksize=2):
                rows.append(row)
                if len(rows) % 50 == 0:
                    print(f"{setup}: {len(rows)}/{len(todo)} trials done", flush=True)
    else:
        rows = [_run_trial(t) for t in todo]
    _G.clear()
    spy = spy_close.reindex(dates).ffill().pct_change(fill_method=None).loc[sc.TRAIN_START:].fillna(0.0)
    spy_row: dict = {"name": "spy", "setup": "SPY"}
    for p, (a, b) in PERIODS.items():
        m = sc.metrics(spy.loc[a:b], cash)
        spy_row.update({f"{p}_{k}": m.get(k, np.nan) for k in PORT_KEYS})
    return rows + [spy_row]


def deflated_sharpe(sharpe_ann, pool_ann, n_periods, skew, kurtosis, ppy: int = sc.PPY) -> np.ndarray:
    """mab.deflated_sharpe for many trials at once: the null benchmark is computed once."""
    pool = np.asarray(pool_ann, dtype=float)
    pool = pool[np.isfinite(pool)] / np.sqrt(ppy)
    n = len(pool)
    g = np.euler_gamma
    e_max = (1 - g) * norm.ppf(1 - 1 / n) + g * norm.ppf(1 - 1 / (n * np.e))
    sr0 = pool.std(ddof=1) * e_max
    sr = np.asarray(sharpe_ann, dtype=float) / np.sqrt(ppy)
    t = np.asarray(n_periods, dtype=float)
    denom = 1 - np.asarray(skew, dtype=float) * sr + (np.asarray(kurtosis, dtype=float) - 1) / 4 * sr ** 2
    ok = (denom > 0) & (t >= 10)
    z = (sr - sr0) * np.sqrt(np.where(ok, t - 1, np.nan)) / np.sqrt(np.where(ok, denom, np.nan))
    return np.where(ok, norm.cdf(z), np.nan)


def marginals(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Median trade-level PF per value of each dimension and period, over trials
    with at least MARGINAL_MIN_TRADES trades in that period."""
    order = {"setup": SETUPS, "exit": EXITS, "filters": list(FILTER_SETS), "stop": list(STOPS)}
    out = {}
    for dim, values in order.items():
        cols = {}
        for p in PERIODS:
            pf = df[f"{p}_tl_profit_factor"].where(df[f"{p}_tl_trades"] >= MARGINAL_MIN_TRADES)
            cols[p] = pf.groupby(df[dim]).median()
            cols[f"{p}_n"] = pf.notna().groupby(df[dim]).sum()
        out[dim] = pd.DataFrame(cols).reindex(values)
    return out


def aggregate(rows: pd.DataFrame, prior_sharpes: list[float]) -> dict:
    spy = rows[rows["name"] == "spy"].iloc[0].to_dict()
    df = rows[rows["name"] != "spy"].drop_duplicates("name").set_index("name")
    names = [t.name for t in trials() if t.name in df.index]
    df = df.loc[names]
    pool = np.concatenate([df["validation_sharpe"].to_numpy(dtype=float), np.asarray(prior_sharpes, dtype=float)])
    df["deflated_sharpe"] = deflated_sharpe(df["validation_sharpe"], pool, df["validation_days"],
                                            df["validation_skew"], df["validation_kurtosis"])
    spy_v = {"cagr": spy["validation_cagr"]}
    df["passed"] = [all(sc.criteria({"sortino_monthly": s, "cagr": c, "max_drawdown": d}, spy_v).values())
                    for s, c, d in zip(df["validation_sortino_monthly"], df["validation_cagr"],
                                       df["validation_max_drawdown"])]
    eligible = df[df["train_tl_trades"] >= MIN_TRAIN_TRADES]
    selected = eligible.sort_values("train_tl_profit_factor", ascending=False, kind="mergesort").index[:TOP_N]
    robust_ok = np.logical_and.reduce([(df[f"{p}_tl_trades"] >= ROBUST_TRADES)
                                       & (df[f"{p}_tl_profit_factor"] >= ROBUST_PF)
                                       for p in ("train", "val1", "val2")])
    worst = df[["train_tl_profit_factor", "val1_tl_profit_factor", "val2_tl_profit_factor"]].min(axis=1)
    robust = worst[robust_ok].sort_values(ascending=False, kind="mergesort").index
    return {"df": df, "spy": spy, "selected": list(selected), "robust": list(robust),
            "passed": list(df.index[df["passed"]]), "marginals": marginals(df), "n_trials": int(np.isfinite(pool).sum()),
            "expected": len(trials())}

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import yfinance as yf


OUT_DIR = Path("outputs/literature/sp500_downside_26_paper_backtests_1995_2019")

DATA_START = "1988-01-01"
DATA_END_EXCLUSIVE = "2020-01-01"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALID_START = pd.Timestamp("2011-01-01")
VALID_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")


@dataclass(frozen=True)
class StudySpec:
    rank: int
    paper_id: str
    paper_title: str
    authors: str
    year: int
    family: str
    replication_level: str
    exact_replication_claimed: bool
    rule_summary: str
    data_required: str
    proxy_used: str
    proxy_warning: str
    source_url: str
    runner: Callable[["BacktestContext", StudySpec], "StudyResult"]


@dataclass(frozen=True)
class StudyResult:
    spec: StudySpec
    status: str
    returns: pd.Series
    weights: pd.DataFrame
    parameters: dict[str, object]
    unsupported_reason: str = ""


@dataclass(frozen=True)
class BacktestContext:
    monthly_returns: pd.DataFrame
    monthly_prices: pd.DataFrame
    daily_prices: pd.DataFrame
    fred_monthly: pd.DataFrame
    proxy_map: pd.DataFrame


YF_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "EFA",
    "EEM",
    "AGG",
    "IEF",
    "TLT",
    "GLD",
    "DBC",
    "HYG",
    "LQD",
    "SHY",
    "BIL",
    "UUP",
    "VFITX",
    "VUSTX",
    "VGTSX",
    "VEIEX",
    "^VIX",
    "^VIX3M",
    "^SPGSCI",
]


FRED_SERIES = {
    "TB3MS": "3-month Treasury bill secondary market rate",
    "BAMLH0A0HYM2": "ICE BofA US High Yield Option-Adjusted Spread",
    "NFCI": "Chicago Fed National Financial Conditions Index",
    "ANFCI": "Chicago Fed Adjusted National Financial Conditions Index",
    "GOLDAMGBD228NLBM": "London gold fixing price",
    "DTWEXBGS": "Nominal broad US dollar index",
    "UMCSENT": "University of Michigan consumer sentiment",
}


def fetch_fred_series(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    frame = pd.read_csv(url)
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    values = pd.to_numeric(frame[series_id], errors="coerce")
    out = pd.Series(values.to_numpy(), index=frame["observation_date"], name=series_id).dropna()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.loc[(out.index >= pd.Timestamp(DATA_START)) & (out.index < LOCKED_START)]


def download_yf_prices(symbols: list[str]) -> pd.DataFrame:
    data = yf.download(
        sorted(set(symbols)),
        start=DATA_START,
        end=DATA_END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"].copy()
    else:
        close = data[["Close"]].copy()
        close.columns = sorted(set(symbols))
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.sort_index().dropna(axis=1, how="all")
    if not close.empty and close.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into Yahoo panel")
    return close


def monthly_close(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.resample("ME").last().dropna(how="all")


def pct_change_prices(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return prices.pct_change(fill_method=None)


def cash_monthly_returns(tb3ms: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    rate = tb3ms.resample("ME").last().reindex(index).ffill().fillna(0.0) / 100.0
    return ((1.0 + rate) ** (1.0 / 12.0) - 1.0).rename("CASH")


def gold_monthly_returns(fred: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    if "GOLDAMGBD228NLBM" not in fred:
        return pd.Series(np.nan, index=index, name="GOLD_FRED")
    gold = fred["GOLDAMGBD228NLBM"].resample("ME").last().reindex(index).ffill()
    return gold.pct_change(fill_method=None).rename("GOLD_FRED")


def combine_returns(
    name: str,
    index: pd.DatetimeIndex,
    candidates: list[tuple[str, pd.Series, str]],
) -> tuple[pd.Series, list[dict[str, object]]]:
    out = pd.Series(np.nan, index=index, name=name)
    rows: list[dict[str, object]] = []
    for source, returns, note in candidates:
        aligned = returns.reindex(index)
        used = out.isna() & aligned.notna()
        out.loc[used] = aligned.loc[used]
        if aligned.notna().any():
            rows.append(
                {
                    "asset": name,
                    "source": source,
                    "first_date": str(aligned.dropna().index.min().date()),
                    "last_date": str(aligned.dropna().index.max().date()),
                    "used_months": int(used.sum()),
                    "note": note,
                }
            )
    return out.fillna(0.0).rename(name), rows


def price_index_from_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns.fillna(0.0)).cumprod().rename(returns.name)


def build_context() -> BacktestContext:
    daily = download_yf_prices(YF_SYMBOLS)
    monthly = monthly_close(daily)
    yf_rets = pct_change_prices(monthly)

    fred_cols: dict[str, pd.Series] = {}
    for series_id in FRED_SERIES:
        try:
            fred_cols[series_id] = fetch_fred_series(series_id)
        except Exception:
            fred_cols[series_id] = pd.Series(dtype=float, name=series_id)
    fred_daily = pd.concat(fred_cols.values(), axis=1) if fred_cols else pd.DataFrame()
    if fred_daily.empty:
        fred_daily = pd.DataFrame(index=pd.DatetimeIndex([], name="observation_date"))
    else:
        fred_daily.index = pd.to_datetime(fred_daily.index)
    fred_monthly = fred_daily.resample("ME").last().sort_index()

    index = pd.date_range(DATA_START, VALID_END, freq="ME")
    cash = cash_monthly_returns(fred_daily.get("TB3MS", pd.Series(dtype=float)), index)
    gold_fred = gold_monthly_returns(fred_daily, index)

    proxy_rows: list[dict[str, object]] = []

    def yf_ret(symbol: str) -> pd.Series:
        if symbol not in yf_rets:
            return pd.Series(np.nan, index=index, name=symbol)
        return yf_rets[symbol].reindex(index).rename(symbol)

    assets: dict[str, pd.Series] = {}
    specs = {
        "US_EQ": [("SPY", yf_ret("SPY"), "SPY ETF")],
        "US_TECH": [("QQQ", yf_ret("QQQ"), "QQQ when available"), ("SPY", yf_ret("SPY"), "SPY fallback before QQQ inception")],
        "US_SMALL": [("IWM", yf_ret("IWM"), "IWM when available"), ("SPY", yf_ret("SPY"), "SPY fallback before IWM inception")],
        "DEV_EQ": [("EFA", yf_ret("EFA"), "EFA when available"), ("VGTSX", yf_ret("VGTSX"), "Vanguard international stock proxy")],
        "EM_EQ": [("EEM", yf_ret("EEM"), "EEM when available"), ("VEIEX", yf_ret("VEIEX"), "Vanguard emerging markets proxy")],
        "AGG_BOND": [("AGG", yf_ret("AGG"), "AGG when available"), ("VFITX", yf_ret("VFITX"), "Intermediate Treasury mutual fund proxy")],
        "IEF": [("IEF", yf_ret("IEF"), "IEF when available"), ("VFITX", yf_ret("VFITX"), "Intermediate Treasury mutual fund proxy")],
        "TLT": [("TLT", yf_ret("TLT"), "TLT when available"), ("VUSTX", yf_ret("VUSTX"), "Long Treasury mutual fund proxy")],
        "GOLD": [("GLD", yf_ret("GLD"), "GLD when available"), ("FRED_GOLD", gold_fred, "London gold fixing proxy")],
        "COMMODITY": [("DBC", yf_ret("DBC"), "DBC when available"), ("SPGSCI", yf_ret("^SPGSCI"), "S&P GSCI index proxy")],
        "HYG": [("HYG", yf_ret("HYG"), "HYG when available"), ("CASH", cash, "cash fallback before HYG inception")],
        "LQD": [("LQD", yf_ret("LQD"), "LQD when available"), ("CASH", cash, "cash fallback before LQD inception")],
        "SHY": [("SHY", yf_ret("SHY"), "SHY when available"), ("CASH", cash, "cash fallback before SHY inception")],
        "BIL": [("BIL", yf_ret("BIL"), "BIL when available"), ("CASH", cash, "cash fallback before BIL inception")],
        "UUP": [("UUP", yf_ret("UUP"), "UUP when available"), ("DTWEXBGS", fred_monthly.get("DTWEXBGS", pd.Series(index=index)).pct_change(fill_method=None), "FRED broad dollar index proxy")],
        "CASH": [("TB3MS", cash, "FRED 3-month T-bill converted to monthly return")],
    }
    for asset, candidates in specs.items():
        combined, rows = combine_returns(asset, index, candidates)
        assets[asset] = combined
        proxy_rows.extend(rows)

    monthly_returns = pd.DataFrame(assets).loc[:VALID_END].fillna(0.0)
    monthly_prices = monthly_returns.apply(price_index_from_returns)
    proxy_map = pd.DataFrame(proxy_rows)
    if not monthly_returns.empty and monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into monthly return panel")
    return BacktestContext(monthly_returns, monthly_prices, daily, fred_monthly, proxy_map)


def month_returns(ctx: BacktestContext, weights: pd.DataFrame) -> pd.Series:
    idx = ctx.monthly_returns.index.intersection(weights.index)
    w = weights.reindex(idx).fillna(0.0)
    r = ctx.monthly_returns.reindex(idx).fillna(0.0)
    out = (w.shift(1).fillna(0.0) * r).sum(axis=1).rename("strategy_return")
    return out.loc[(out.index >= TRAIN_START) & (out.index <= VALID_END)]


def unsupported(spec: StudySpec, reason: str) -> StudyResult:
    empty_index = pd.date_range(TRAIN_START, VALID_END, freq="ME")
    return StudyResult(
        spec=spec,
        status="unsupported_exact",
        returns=pd.Series(np.nan, index=empty_index, name="strategy_return"),
        weights=pd.DataFrame(index=empty_index),
        parameters={},
        unsupported_reason=reason,
    )


def score_13612w(prices: pd.DataFrame) -> pd.DataFrame:
    one = prices.pct_change(1, fill_method=None)
    three = prices.pct_change(3, fill_method=None)
    six = prices.pct_change(6, fill_method=None)
    twelve = prices.pct_change(12, fill_method=None)
    return 12.0 * one + 4.0 * three + 2.0 * six + twelve


def top_assets(scores: pd.Series, assets: list[str], n: int) -> list[str]:
    present = scores.reindex(assets).replace([np.inf, -np.inf], np.nan).dropna()
    if present.empty:
        return []
    return list(present.sort_values(ascending=False).head(n).index)


def equal_weight(index: pd.DatetimeIndex, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(0.0, index=index, columns=columns)


def unique_ordered(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def run_faber(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "IEF", "GOLD", "COMMODITY"]
    prices = ctx.monthly_prices[assets]
    sma = prices.rolling(10, min_periods=10).mean()
    weights = equal_weight(prices.index, assets + ["CASH"])
    active = prices > sma
    for date in prices.index:
        picks = [a for a in assets if bool(active.at[date, a])]
        if picks:
            for asset in picks:
                weights.at[date, asset] = 1.0 / len(picks)
        else:
            weights.at[date, "CASH"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"sma_months": 10, "assets": assets})


def run_daa(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    risky = ["US_EQ", "US_TECH", "US_SMALL", "DEV_EQ", "EM_EQ", "GOLD", "COMMODITY", "HYG"]
    defensive = ["TLT", "IEF", "LQD", "SHY", "BIL"]
    canaries = ["EM_EQ", "AGG_BOND"]
    prices = ctx.monthly_prices[unique_ordered(risky + defensive + canaries)]
    scores = score_13612w(prices)
    weights = equal_weight(prices.index, risky + defensive + ["CASH"])
    for date in prices.index:
        canary_bad = int((scores.loc[date, canaries] <= 0.0).sum())
        if canary_bad == 0:
            picks = top_assets(scores.loc[date], risky, 6)
            for asset in picks:
                weights.at[date, asset] = 1.0 / max(1, len(picks))
        elif canary_bad == 1:
            risky_picks = top_assets(scores.loc[date], risky, 3)
            defensive_pick = top_assets(scores.loc[date], defensive, 1)
            for asset in risky_picks:
                weights.at[date, asset] = 0.5 / max(1, len(risky_picks))
            if defensive_pick:
                weights.at[date, defensive_pick[0]] = 0.5
            else:
                weights.at[date, "CASH"] = 0.5
        else:
            defensive_pick = top_assets(scores.loc[date], defensive, 1)
            weights.at[date, defensive_pick[0] if defensive_pick else "CASH"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"score": "13612W", "canaries": canaries})


def run_paa_vaa(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    risky = ["US_EQ", "US_TECH", "US_SMALL", "DEV_EQ", "EM_EQ", "GOLD", "COMMODITY"]
    defensive = ["TLT", "IEF", "LQD", "SHY", "BIL"]
    canaries = ["US_EQ", "DEV_EQ", "EM_EQ", "AGG_BOND"]
    prices = ctx.monthly_prices[unique_ordered(risky + defensive + canaries)]
    scores = score_13612w(prices)
    weights = equal_weight(prices.index, risky + defensive + ["CASH"])
    for date in prices.index:
        breadth = float((scores.loc[date, canaries] > 0.0).mean())
        if breadth >= 0.75:
            picks = top_assets(scores.loc[date], risky, 5)
            for asset in picks:
                weights.at[date, asset] = 1.0 / max(1, len(picks))
        elif breadth >= 0.50:
            picks = top_assets(scores.loc[date], risky, 3)
            def_pick = top_assets(scores.loc[date], defensive, 1)
            for asset in picks:
                weights.at[date, asset] = 0.5 / max(1, len(picks))
            weights.at[date, def_pick[0] if def_pick else "CASH"] = 0.5
        else:
            def_picks = top_assets(scores.loc[date], defensive, 2)
            if def_picks:
                for asset in def_picks:
                    weights.at[date, asset] = 1.0 / len(def_picks)
            else:
                weights.at[date, "CASH"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"variant": "PAA/VAA operational blend"})


def rolling_vol(returns: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    return returns.rolling(window, min_periods=max(3, window // 2)).std(ddof=0) * math.sqrt(12.0)


def normalize_gross(weights: pd.DataFrame, gross_cap: float = 1.0) -> pd.DataFrame:
    gross = weights.abs().sum(axis=1)
    scale = (gross_cap / gross.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    return weights.mul(scale, axis=0)


def run_tsmom_long_cash(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "EM_EQ", "TLT", "IEF", "GOLD", "COMMODITY", "UUP"]
    rets = ctx.monthly_returns[assets]
    prices = ctx.monthly_prices[assets]
    momentum = prices.pct_change(12, fill_method=None)
    vol = rolling_vol(rets, 12)
    weights = equal_weight(rets.index, assets + ["CASH"])
    for date in rets.index:
        active = [a for a in assets if momentum.at[date, a] > 0.0]
        if not active:
            weights.at[date, "CASH"] = 1.0
            continue
        raw = pd.Series({a: 1.0 / max(float(vol.at[date, a]), 0.01) for a in active})
        raw = raw / raw.sum()
        for asset, value in raw.items():
            weights.at[date, asset] = float(value)
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"lookback_months": 12, "mode": "long_cash"})


def run_trend_long_short(ctx: BacktestContext, spec: StudySpec, slow_confirmation: bool = False) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "EM_EQ", "TLT", "IEF", "GOLD", "COMMODITY", "UUP"]
    prices = ctx.monthly_prices[assets]
    rets = ctx.monthly_returns[assets]
    mom12 = prices.pct_change(12, fill_method=None)
    mom3 = prices.pct_change(3, fill_method=None)
    vol = rolling_vol(rets, 12)
    weights = equal_weight(prices.index, assets)
    for date in prices.index:
        signs = np.sign(mom12.loc[date])
        if slow_confirmation:
            signs = signs.where(np.sign(mom3.loc[date]) == signs, 0.0)
        raw = signs / vol.loc[date].replace(0.0, np.nan)
        raw = raw.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if raw.abs().sum() > 0:
            weights.loc[date, assets] = raw / raw.abs().sum()
    weights = normalize_gross(weights, 1.0)
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"lookback_months": 12, "long_short": True})


def run_hamill(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    return run_trend_long_short(ctx, spec, slow_confirmation=False)


def run_hurst(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    return run_trend_long_short(ctx, spec, slow_confirmation=True)


def run_gem(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    idx = ctx.monthly_returns.index
    prices = ctx.monthly_prices
    weights = equal_weight(idx, ["US_EQ", "DEV_EQ", "IEF", "CASH"])
    us_mom = prices["US_EQ"].pct_change(12, fill_method=None)
    dev_mom = prices["DEV_EQ"].pct_change(12, fill_method=None)
    cash_mom = (1.0 + ctx.monthly_returns["CASH"]).rolling(12, min_periods=12).apply(np.prod, raw=True) - 1.0
    for date in idx:
        if us_mom.at[date] > cash_mom.at[date]:
            weights.at[date, "US_EQ" if us_mom.at[date] >= dev_mom.at[date] else "DEV_EQ"] = 1.0
        else:
            weights.at[date, "IEF"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"lookback_months": 12})


def run_moreira_muir(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    spy_daily = ctx.daily_prices["SPY"].dropna().loc[:VALID_END]
    daily_rets = spy_daily.pct_change(fill_method=None).dropna()
    monthly_spy = spy_daily.resample("ME").last().pct_change(fill_method=None).dropna()
    rv = daily_rets.pow(2).resample("ME").sum(min_count=10).reindex(monthly_spy.index)
    raw = 1.0 / rv.replace(0.0, np.nan)
    train_raw = raw.loc[(raw.index >= TRAIN_START) & (raw.index <= TRAIN_END)].dropna()
    scale = 1.0 / float(train_raw.mean()) if not train_raw.empty else 1.0
    exposure = (scale / rv.replace(0.0, np.nan)).clip(lower=0.0, upper=2.0).reindex(ctx.monthly_returns.index).fillna(0.0)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "CASH"])
    weights["US_EQ"] = exposure
    weights["CASH"] = 1.0 - exposure.clip(upper=1.0)
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"exposure_cap": 2.0, "scale_train": scale})


def run_vol_target(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    r = ctx.monthly_returns["US_EQ"]
    vol = r.rolling(3, min_periods=3).std(ddof=0) * math.sqrt(12.0)
    exposure = (0.10 / vol.replace(0.0, np.nan)).clip(lower=0.0, upper=1.5).fillna(0.0)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "CASH"])
    weights["US_EQ"] = exposure
    weights["CASH"] = 1.0 - exposure.clip(upper=1.0)
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"target_vol": 0.10, "exposure_cap": 1.5})


def train_quantile(series: pd.Series, q: float, default: float) -> float:
    train = series.loc[(series.index >= TRAIN_START) & (series.index <= TRAIN_END)].replace([np.inf, -np.inf], np.nan).dropna()
    if len(train) < 24:
        return default
    return float(train.quantile(q))


def has_train_coverage(series: pd.Series, min_obs: int = 60) -> bool:
    train = series.loc[(series.index >= TRAIN_START) & (series.index <= TRAIN_END)]
    return int(train.replace([np.inf, -np.inf], np.nan).dropna().shape[0]) >= min_obs


def vix_monthly(ctx: BacktestContext) -> pd.Series:
    if "^VIX" not in ctx.daily_prices:
        return pd.Series(np.nan, index=ctx.monthly_returns.index, name="VIX")
    return ctx.daily_prices["^VIX"].resample("ME").last().reindex(ctx.monthly_returns.index).ffill()


def run_vix_timing(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    idx = ctx.monthly_returns.index
    vix = vix_monthly(ctx)
    z = (vix - vix.rolling(12, min_periods=6).mean()) / vix.rolling(12, min_periods=6).std(ddof=0)
    threshold = train_quantile(z, 0.80, 1.0)
    trend = ctx.monthly_prices["US_EQ"] > ctx.monthly_prices["US_EQ"].rolling(10, min_periods=10).mean()
    weights = equal_weight(idx, ["US_EQ", "IEF", "CASH"])
    stress = (z > threshold) & (~trend)
    weights.loc[~stress.fillna(False), "US_EQ"] = 1.0
    weights.loc[stress.fillna(False), "IEF"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"vix_z_threshold_train_p80": threshold})


def run_credit_spread(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    if "BAMLH0A0HYM2" not in ctx.fred_monthly:
        return unsupported(spec, "missing FRED BAMLH0A0HYM2")
    spread = ctx.fred_monthly["BAMLH0A0HYM2"].reindex(ctx.monthly_returns.index).ffill()
    if not has_train_coverage(spread):
        return unsupported(spec, "insufficient train coverage for FRED BAMLH0A0HYM2")
    change = spread.diff(3)
    train = change.loc[(change.index >= TRAIN_START) & (change.index <= TRAIN_END)].dropna()
    if len(train) < 60 or float(train.std(ddof=0)) == 0.0:
        return unsupported(spec, "insufficient non-constant train spread changes")
    z = (change - float(train.mean())) / float(train.std(ddof=0)) if len(train) > 24 and train.std(ddof=0) > 0 else change * np.nan
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "IEF", "CASH"])
    weights.loc[z <= 0.5, "US_EQ"] = 1.0
    weights.loc[(z > 0.5) & (z <= 1.0), "CASH"] = 1.0
    weights.loc[z > 1.0, "IEF"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"z_lookback_months": 3})


def run_nfci(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    col = "ANFCI" if "ANFCI" in ctx.fred_monthly else "NFCI"
    if col not in ctx.fred_monthly:
        return unsupported(spec, "missing FRED NFCI/ANFCI")
    nfci = ctx.fred_monthly[col].reindex(ctx.monthly_returns.index).ffill()
    if not has_train_coverage(nfci):
        return unsupported(spec, f"insufficient train coverage for FRED {col}")
    threshold = train_quantile(nfci, 0.80, 0.5)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "IEF"])
    stress = nfci > threshold
    weights.loc[~stress.fillna(False), "US_EQ"] = 1.0
    weights.loc[stress.fillna(False), "IEF"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"series": col, "threshold_train_p80": threshold})


def run_vix_sleeve(ctx: BacktestContext, spec: StudySpec, sleeve: float) -> StudyResult:
    vix = vix_monthly(ctx)
    if vix.dropna().empty:
        return unsupported(spec, "missing VIX")
    vix_rets = vix.pct_change(fill_method=None).clip(lower=-0.8, upper=2.0).reindex(ctx.monthly_returns.index).fillna(0.0)
    synthetic = pd.DataFrame(ctx.monthly_returns)
    synthetic["VIX_INDEX_PROXY"] = vix_rets
    local_ctx = BacktestContext(synthetic, synthetic.apply(price_index_from_returns), ctx.daily_prices, ctx.fred_monthly, ctx.proxy_map)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "VIX_INDEX_PROXY", "CASH"])
    weights["US_EQ"] = max(0.0, 1.0 - sleeve)
    weights["VIX_INDEX_PROXY"] = sleeve
    return StudyResult(spec, "evaluated_low_proxy", month_returns(local_ctx, weights), weights, {"vix_index_sleeve": sleeve, "tradable": False})


def run_szado(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    return run_vix_sleeve(ctx, spec, 0.05)


def run_moran_dash(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    return run_vix_sleeve(ctx, spec, 0.10)


def run_delisle(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    return run_vix_sleeve(ctx, spec, 0.15)


def run_vrp(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    spy = ctx.daily_prices["SPY"].dropna()
    vix = ctx.daily_prices["^VIX"].reindex(spy.index).ffill() / 100.0
    daily = spy.pct_change(fill_method=None)
    rv = daily.pow(2).rolling(21, min_periods=10).sum() * 252.0 / 21.0
    vrp = (vix.pow(2) - rv).resample("ME").last().reindex(ctx.monthly_returns.index).ffill()
    threshold = train_quantile(vrp, 0.50, 0.0)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "IEF", "CASH"])
    weights.loc[vrp >= threshold, "US_EQ"] = 1.0
    weights.loc[vrp < threshold, "IEF"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"vrp_proxy": "VIX^2 minus 21d realized variance", "threshold_train_median": threshold})


def run_svix_proxy(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    spy = ctx.daily_prices["SPY"].dropna()
    vix = ctx.daily_prices["^VIX"].reindex(spy.index).ffill()
    vix_m = vix.resample("ME").last().reindex(ctx.monthly_returns.index).ffill()
    threshold = train_quantile(vix_m, 0.70, 25.0)
    trend = ctx.monthly_prices["US_EQ"] > ctx.monthly_prices["US_EQ"].rolling(10, min_periods=10).mean()
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "CASH"])
    weights.loc[(vix_m > threshold) & trend.fillna(False), "US_EQ"] = 1.0
    weights.loc[~((vix_m > threshold) & trend.fillna(False)), "CASH"] = 1.0
    return StudyResult(spec, "evaluated_low_proxy", month_returns(ctx, weights), weights, {"warning": "not SVIX exact; VIX level proxy"})


def run_tail_proxy(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    r = ctx.monthly_returns["US_EQ"]
    rolling_min = r.rolling(12, min_periods=6).min()
    rolling_skew = r.rolling(12, min_periods=6).skew()
    min_threshold = train_quantile(rolling_min, 0.20, -0.08)
    skew_threshold = train_quantile(rolling_skew, 0.20, -0.5)
    stress = (rolling_min < min_threshold) & (rolling_skew < skew_threshold)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "IEF"])
    weights.loc[~stress.fillna(False), "US_EQ"] = 1.0
    weights.loc[stress.fillna(False), "IEF"] = 1.0
    return StudyResult(spec, "evaluated_low_proxy", month_returns(ctx, weights), weights, {"tail_proxy": "rolling min return plus skew"})


def run_greenwood_proxy(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    if "UMCSENT" not in ctx.fred_monthly:
        return unsupported(spec, "missing UMCSENT sentiment proxy")
    sent = ctx.fred_monthly["UMCSENT"].reindex(ctx.monthly_returns.index).ffill()
    if not has_train_coverage(sent):
        return unsupported(spec, "insufficient train coverage for UMCSENT sentiment proxy")
    high = train_quantile(sent, 0.80, 100.0)
    weights = equal_weight(ctx.monthly_returns.index, ["US_EQ", "CASH"])
    weights.loc[sent <= high, "US_EQ"] = 1.0
    weights.loc[sent > high, "CASH"] = 1.0
    return StudyResult(spec, "evaluated_low_proxy", month_returns(ctx, weights), weights, {"sentiment_proxy": "UMCSENT contrarian high sentiment"})


def run_baker_wurgler(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    return unsupported(spec, "Baker-Wurgler sentiment index is not in the local verified panel")


def min_variance_weights(cov: pd.DataFrame) -> pd.Series:
    cov = cov.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    assets = list(cov.columns)
    if not assets:
        return pd.Series(dtype=float)
    try:
        inv = np.linalg.pinv(cov.to_numpy(dtype=float) + np.eye(len(assets)) * 1e-6)
        raw = inv @ np.ones(len(assets))
        raw = np.clip(raw, 0.0, None)
        if raw.sum() <= 0:
            raw = np.ones(len(assets))
        return pd.Series(raw / raw.sum(), index=assets)
    except Exception:
        return pd.Series(1.0 / len(assets), index=assets)


def run_aaa(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "EM_EQ", "IEF", "TLT", "GOLD", "COMMODITY", "HYG", "LQD", "SHY"]
    prices = ctx.monthly_prices[assets]
    rets = ctx.monthly_returns[assets]
    mom = prices.pct_change(6, fill_method=None)
    weights = equal_weight(prices.index, assets + ["CASH"])
    for i, date in enumerate(prices.index):
        picks = top_assets(mom.loc[date], assets, 5)
        if len(picks) < 2 or i < 6:
            weights.at[date, "CASH"] = 1.0
            continue
        cov = rets[picks].iloc[max(0, i - 6) : i].cov()
        w = min_variance_weights(cov)
        for asset, value in w.items():
            weights.at[date, asset] = float(value)
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"momentum_months": 6, "top_n": 5})


def run_turbulence(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "EM_EQ", "TLT", "IEF", "GOLD", "COMMODITY", "HYG", "LQD"]
    rets = ctx.monthly_returns[assets]
    turbulence = pd.Series(np.nan, index=rets.index)
    for i, date in enumerate(rets.index):
        window = rets.iloc[max(0, i - 36) : i]
        if len(window) < 18:
            continue
        x = rets.loc[date] - window.mean()
        inv = np.linalg.pinv(window.cov().to_numpy(dtype=float) + np.eye(len(assets)) * 1e-6)
        turbulence.at[date] = float(x.to_numpy(dtype=float).T @ inv @ x.to_numpy(dtype=float))
    threshold = train_quantile(turbulence, 0.80, float(turbulence.median(skipna=True)))
    weights = equal_weight(rets.index, ["US_EQ", "IEF", "TLT", "GOLD"])
    stress = turbulence > threshold
    weights.loc[~stress.fillna(False), "US_EQ"] = 1.0
    weights.loc[stress.fillna(False), ["IEF", "TLT", "GOLD"]] = 1.0 / 3.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"turbulence_threshold_train_p80": threshold})


def run_absorption(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "EM_EQ", "TLT", "IEF", "GOLD", "COMMODITY", "HYG", "LQD"]
    rets = ctx.monthly_returns[assets]
    absorption = pd.Series(np.nan, index=rets.index)
    for i, date in enumerate(rets.index):
        window = rets.iloc[max(0, i - 36) : i].dropna()
        if len(window) < 18:
            continue
        cov = window.cov().to_numpy(dtype=float)
        vals = np.linalg.eigvalsh(cov)
        vals = np.sort(np.clip(vals, 0.0, None))[::-1]
        absorption.at[date] = float(vals[:2].sum() / vals.sum()) if vals.sum() > 0 else np.nan
    threshold = train_quantile(absorption, 0.80, float(absorption.median(skipna=True)))
    weights = equal_weight(rets.index, ["US_EQ", "IEF", "TLT"])
    stress = absorption > threshold
    weights.loc[~stress.fillna(False), "US_EQ"] = 1.0
    weights.loc[stress.fillna(False), ["IEF", "TLT"]] = 0.5
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"top_components": 2, "threshold_train_p80": threshold})


def run_gtaa(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "DEV_EQ", "EM_EQ", "IEF", "TLT", "GOLD", "COMMODITY", "HYG", "LQD"]
    prices = ctx.monthly_prices[assets]
    mom = prices.pct_change(12, fill_method=None)
    trend = prices > prices.rolling(10, min_periods=10).mean()
    weights = equal_weight(prices.index, assets + ["CASH"])
    for date in prices.index:
        eligible = [a for a in assets if bool(trend.at[date, a])]
        picks = top_assets(mom.loc[date], eligible, 5)
        if picks:
            for asset in picks:
                weights.at[date, asset] = 1.0 / len(picks)
        else:
            weights.at[date, "CASH"] = 1.0
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"value_component": "not used; momentum+trend conservative proxy"})


def max_drawdown_from_returns(returns: pd.Series) -> float:
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return float("nan")
    nav = (1.0 + r).cumprod()
    return float((nav / nav.cummax() - 1.0).min())


def run_cdar(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    assets = ["US_EQ", "IEF", "TLT", "GOLD", "COMMODITY", "LQD"]
    rets = ctx.monthly_returns[assets]
    rng = np.random.default_rng(42)
    candidate_weights = rng.dirichlet(np.ones(len(assets)), size=512)
    weights = equal_weight(rets.index, assets)
    for i, date in enumerate(rets.index):
        window = rets.iloc[max(0, i - 36) : i]
        if len(window) < 18:
            weights.loc[date, "IEF"] = 1.0
            continue
        best = None
        for w in candidate_weights:
            candidate = window @ w
            mdd = max_drawdown_from_returns(candidate)
            cagr_proxy = float(candidate.mean() * 12.0)
            score = mdd + 0.25 * cagr_proxy
            if best is None or score > best[0]:
                best = (score, w)
        chosen = best[1] if best is not None else np.ones(len(assets)) / len(assets)
        weights.loc[date, assets] = chosen
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"candidate_weight_grid": 512, "rolling_months": 36})


def run_glidepath(ctx: BacktestContext, spec: StudySpec) -> StudyResult:
    idx = ctx.monthly_returns.index
    weights = equal_weight(idx, ["US_EQ", "IEF"])
    for date in idx:
        years = max(0, date.year - 1995)
        equity = min(0.70, 0.30 + 0.02 * years)
        weights.at[date, "US_EQ"] = equity
        weights.at[date, "IEF"] = 1.0 - equity
    return StudyResult(spec, "evaluated", month_returns(ctx, weights), weights, {"start_equity": 0.30, "annual_step": 0.02, "max_equity": 0.70})


def build_specs() -> list[StudySpec]:
    return [
        StudySpec(1, "faber_taa", "A Quantitative Approach to Tactical Asset Allocation", "Meb Faber", 2007, "Trend following / TAA", "high", False, "Hold asset if above 10-month SMA, otherwise cash.", "Monthly ETF/proxy prices.", "ETF/proxy panel; some pre-ETF proxies.", "Multi-asset implementation, not paper's exact original database.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461", run_faber),
        StudySpec(2, "keller_keuning_daa", "Breadth Momentum and the Canary Universe: Defensive Asset Allocation", "Keller; Keuning", 2018, "Canary defensive allocation", "high", False, "DAA 13612W with EEM/AGG canaries.", "ETF/proxy panel including EEM and AGG.", "ETF/proxy panel with VEIEX/VFITX fallbacks.", "Pre-ETF canaries use documented fund proxies.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3212862", run_daa),
        StudySpec(3, "paa_vaa_suite", "Protective/Vigilant Asset Allocation", "Keller; Keuning", 2017, "Tactical allocation defensiva", "medium_proxy", False, "Operational PAA/VAA blend with breadth/canary risk-off.", "ETF/proxy panel.", "ETF/proxy panel.", "Suite compressed to one operational family row.", "", run_paa_vaa),
        StudySpec(4, "mop_tsmom", "Time Series Momentum", "Moskowitz; Ooi; Pedersen", 2012, "Trend following multi-asset", "medium_proxy", False, "12-month time-series momentum, long/cash ETF proxy.", "Futures markets originally.", "ETF/proxy long/cash panel.", "Original uses futures and excess returns; this is ETF/proxy.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463", run_tsmom_long_cash),
        StudySpec(5, "hamill_crisis_alpha", "Trend Following and Crisis Alpha", "Hamill; Rattray; Van Hemert", 2016, "Crisis alpha", "medium_proxy", False, "Multi-asset trend following long/short with vol scaling.", "Futures markets.", "ETF/proxy trend panel.", "No futures roll/financing exactness.", "", run_hamill),
        StudySpec(6, "hurst_century_trend", "A Century of Evidence on Trend-Following Investing", "Hurst; Ooi; Pedersen", 2017, "Trend following historico", "medium_proxy", False, "Robust trend following with 12-month signal and 3-month confirmation.", "Long futures history.", "ETF/proxy trend panel.", "Only 1995-2019 ETF/proxy window.", "", run_hurst),
        StudySpec(7, "antonacci_gem", "Risk Premia Harvesting Through Dual Momentum / GEM", "Gary Antonacci", 2012, "Dual momentum", "high", False, "GEM: absolute SPY momentum, relative SPY/EFA, otherwise bonds.", "SPY, EFA, cash, bonds.", "SPY/DEV_EQ/IEF/CASH proxy panel.", "DEV_EQ uses EFA/VGTSX proxy.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750", run_gem),
        StudySpec(8, "moreira_muir", "Volatility-Managed Portfolios", "Moreira; Muir", 2017, "Volatility targeting", "high", False, "SPY exposure inverse to realized variance, scaled on train.", "Daily market returns.", "SPY daily returns.", "Single-market implementation of broader factor paper.", "https://www.nber.org/papers/w22208", run_moreira_muir),
        StudySpec(9, "dai_hong_merton_pellerin", "Volatility Targeting and Equity Portfolio Protection", "Dai; Hong; Merton; Pellerin", 2020, "Volatility targeting", "medium_proxy", False, "Target 10% annual volatility using trailing realized vol.", "Equity returns and realized volatility.", "SPY daily/monthly proxy.", "Not exact paper calibration.", "", run_vol_target),
        StudySpec(10, "johannes_polson_stroud", "The Market Price of Aggregate Risk and the Wealth Distribution", "Johannes; Polson; Stroud", 2009, "Market / volatility timing", "medium_proxy", False, "VIX stress plus trend filter risk-off.", "Latent risk/volatility state.", "VIX z-score and SPY trend proxy.", "Latent-state model not reproduced.", "", run_vix_timing),
        StudySpec(11, "gilchrist_zakrajsek", "Credit Spreads and Business Cycle Fluctuations", "Gilchrist; Zakrajsek", 2012, "Credit stress", "medium_proxy", False, "HY OAS deterioration triggers risk-off.", "EBP or credit spread data.", "FRED HY OAS proxy.", "EBP exact not reproduced unless available.", "https://www.aeaweb.org/articles?id=10.1257/aer.102.4.1692", run_credit_spread),
        StudySpec(12, "brave_butters_nfci", "National Financial Conditions Index / Financial Stress Timing", "Brave; Butters", 2012, "Financial conditions", "medium_proxy", False, "NFCI/ANFCI high stress triggers risk-off.", "Chicago Fed NFCI/ANFCI.", "FRED NFCI/ANFCI.", "Paper-specific mapping simplified to threshold timing.", "", run_nfci),
        StudySpec(13, "szado_vix_2008", "VIX Futures and Options in the 2008 Financial Crisis", "Szado", 2009, "Long volatility hedge", "low_proxy", False, "Small VIX index proxy sleeve.", "VIX futures/options.", "VIX spot index return proxy.", "Not tradable; futures/options exact data missing.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1403449", run_szado),
        StudySpec(14, "moran_dash_vix", "VIX Futures and Options for Portfolio Diversification", "Moran; Dash", 2009, "Volatility hedge", "low_proxy", False, "Larger VIX index proxy diversification sleeve.", "VIX futures/options.", "VIX spot index return proxy.", "Not tradable; futures/options exact data missing.", "", run_moran_dash),
        StudySpec(15, "delisle_vol_asset", "Volatility as an Asset Class", "DeLisle; Doran; Krieger", 2011, "Volatility asset class", "low_proxy", False, "Volatility index sleeve as asset-class proxy.", "Volatility derivatives.", "VIX spot index return proxy.", "Not tradable and structurally optimistic/pessimistic depending period.", "", run_delisle),
        StudySpec(16, "btz_vrp", "Expected Stock Returns and Variance Risk Premia", "Bollerslev; Tauchen; Zhou", 2009, "Variance risk premium", "medium_proxy", False, "Risk-on when VIX^2 minus realized variance is above train median.", "Model-free implied variance and realized variance.", "VIX^2 - SPY realized variance.", "VIX proxy is not model-free implied variance.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=948309", run_vrp),
        StudySpec(17, "martin_svix", "What Is the Expected Return on the Market?", "Ian Martin", 2017, "SVIX / option-implied return", "low_proxy", False, "VIX-level expected-return proxy with trend guard.", "Full SPX option panel.", "VIX level proxy.", "Not SVIX exact. Full options unavailable.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2772101", run_svix_proxy),
        StudySpec(18, "kelly_jiang_tail", "Tail Risk and Asset Prices", "Kelly; Jiang", 2014, "Tail risk", "low_proxy", False, "Rolling downside tail/skew proxy risk-off.", "Broad stock cross-section without survivorship bias.", "SPY rolling min/skew proxy.", "Not cross-sectional tail risk exact.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2321243", run_tail_proxy),
        StudySpec(19, "greenwood_shleifer", "Stock Market Expectations and Risk Aversion of Individual Investors", "Greenwood; Shleifer", 2014, "Sentiment / expectations", "low_proxy", False, "Contrarian high sentiment risk-off.", "Investor expectation survey.", "UMCSENT sentiment proxy.", "Consumer sentiment is not the paper's investor expectations.", "", run_greenwood_proxy),
        StudySpec(20, "baker_wurgler", "Investor Sentiment and the Cross-Section of Stock Returns", "Baker; Wurgler", 2006, "Sentiment", "unsupported_exact", False, "Requires Baker-Wurgler sentiment index.", "Baker-Wurgler sentiment index.", "None.", "Local verified panel does not contain the index.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=464843", run_baker_wurgler),
        StudySpec(21, "adaptive_asset_allocation", "Adaptive Asset Allocation: A Primer", "Butler; Philbrick; Gordillo; Varadi", 2012, "Momentum + minimum variance", "high", False, "Top 5 by 6-month momentum, min-variance weighting.", "ETF/proxy cross-asset panel.", "ETF/proxy panel.", "Minimum variance implemented with covariance pseudo-inverse.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2328254", run_aaa),
        StudySpec(22, "financial_turbulence", "Skulls, Financial Turbulence, and Risk Management", "Kritzman; Li", 2010, "Financial turbulence", "high", False, "Mahalanobis turbulence above train p80 triggers defensives.", "Multi-asset return panel.", "ETF/proxy panel.", "Uses monthly panel, not full daily paper setup.", "https://ideas.repec.org/a/taf/ufajxx/v66y2010i5p30-41.html", run_turbulence),
        StudySpec(23, "absorption_ratio", "Principal Components as a Measure of Systemic Risk", "Kritzman; Li; Page; Rigobon", 2010, "Absorption ratio", "high", False, "PCA absorption above train p80 triggers defensives.", "Multi-asset return panel.", "ETF/proxy panel.", "Uses monthly panel and top 2 components.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1582687", run_absorption),
        StudySpec(24, "blitz_van_vliet_gtaa", "Global Tactical Cross-Asset Allocation", "Blitz; van Vliet", 2008, "GTAA value + momentum", "medium_proxy", False, "Top momentum assets with 10-month trend filter.", "Cross-asset value and momentum data.", "ETF/proxy momentum-only conservative variant.", "Value component omitted due non-homogeneous proxy.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1079975", run_gtaa),
        StudySpec(25, "cdar_drawdown", "Drawdown Measure in Portfolio Optimization / CDaR", "Chekhlov; Uryasev; Zabarankin", 2003, "Drawdown optimization", "medium_proxy", False, "Rolling drawdown-aware long-only allocation.", "Asset returns and CDaR optimization.", "ETF/proxy panel with random-grid drawdown optimizer.", "CDaR exact optimizer approximated by deterministic random grid.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=544742", run_cdar),
        StudySpec(26, "pfau_kitces_glidepath", "Reducing Retirement Risk with a Rising Equity Glide-Path", "Pfau; Kitces", 2014, "Retirement / SWR", "high", False, "Start at 30% equity and rise 2% per year to 70%.", "Equity and bond monthly returns.", "SPY/IEF proxy panel.", "This is SWR-oriented, not a market crash predictor.", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2324930", run_glidepath),
    ]


def slice_period(returns: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    return returns.loc[(returns.index >= start) & (returns.index <= end)]


def max_drawdown(returns: pd.Series) -> float:
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return float("nan")
    nav = (1.0 + r).cumprod()
    return float((nav / nav.cummax() - 1.0).min())


def period_metrics(returns: pd.Series) -> dict[str, float]:
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if r.empty:
        return {
            "cagr_pct": float("nan"),
            "sharpe": float("nan"),
            "calmar": float("nan"),
            "mdd_pct": float("nan"),
            "worst_month_pct": float("nan"),
            "worst_quarter_pct": float("nan"),
            "positive_months_pct": float("nan"),
            "observations": 0.0,
            "final_nav": float("nan"),
        }
    nav = (1.0 + r).cumprod()
    years = len(r) / 12.0
    cagr = float(nav.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and nav.iloc[-1] > 0 else float("nan")
    vol = float(r.std(ddof=0))
    sharpe = float(r.mean() / vol * math.sqrt(12.0)) if vol > 0 else float("nan")
    mdd = max_drawdown(r)
    quarters = (1.0 + r).resample("QE").prod(min_count=1) - 1.0
    return {
        "cagr_pct": cagr * 100.0,
        "sharpe": sharpe,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("inf"),
        "mdd_pct": mdd * 100.0,
        "worst_month_pct": float(r.min() * 100.0),
        "worst_quarter_pct": float(quarters.min() * 100.0),
        "positive_months_pct": float((r > 0.0).mean() * 100.0),
        "observations": float(len(r)),
        "final_nav": float(nav.iloc[-1]),
    }


def defensive_series(weights: pd.DataFrame) -> pd.Series:
    if weights.empty:
        return pd.Series(dtype=bool)
    spy_like = [c for c in ["US_EQ", "US_TECH", "US_SMALL", "DEV_EQ", "EM_EQ", "SPY"] if c in weights.columns]
    equity_weight = weights[spy_like].sum(axis=1) if spy_like else pd.Series(0.0, index=weights.index)
    return (equity_weight < 0.50).rename("defensive_signal")


def spy_down_metrics(returns: pd.Series, spy: pd.Series, weights: pd.DataFrame) -> dict[str, float]:
    frame = pd.DataFrame({"strategy": returns, "spy": spy.reindex(returns.index)}).dropna()
    down = frame.loc[frame["spy"] < 0.0]
    up = frame.loc[frame["spy"] >= 0.0]
    defense = defensive_series(weights).reindex(frame.index).fillna(False)
    false_pos = float((defense.loc[up.index]).sum()) if not up.empty else 0.0
    false_neg = float((~defense.loc[down.index]).sum()) if not down.empty else 0.0
    true_pos = float((defense.loc[down.index]).sum()) if not down.empty else 0.0
    downside_capture = float(down["strategy"].sum() / down["spy"].sum() * 100.0) if not down.empty and down["spy"].sum() != 0 else float("nan")
    return {
        "spy_down_months": float(len(down)),
        "spy_down_strategy_avg_return_pct": float(down["strategy"].mean() * 100.0) if not down.empty else float("nan"),
        "spy_down_strategy_positive_pct": float((down["strategy"] > 0.0).mean() * 100.0) if not down.empty else float("nan"),
        "downside_capture_pct": downside_capture,
        "false_positive_defensive_months": false_pos,
        "false_negative_defensive_months": false_neg,
        "true_positive_defensive_months": true_pos,
    }


def turnover_annual(weights: pd.DataFrame) -> float:
    if weights.empty:
        return float("nan")
    return float(weights.diff().abs().sum(axis=1).mean() * 12.0)


def cash_defensive_months_pct(weights: pd.DataFrame) -> float:
    if weights.empty:
        return float("nan")
    return float(defensive_series(weights).mean() * 100.0)


def build_summary_row(result: StudyResult, ctx: BacktestContext) -> dict[str, object]:
    spec = result.spec
    row: dict[str, object] = {
        "rank": spec.rank,
        "paper_id": spec.paper_id,
        "paper_title": spec.paper_title,
        "authors": spec.authors,
        "year": spec.year,
        "family": spec.family,
        "status": result.status,
        "replication_level": spec.replication_level,
        "exact_replication_claimed": spec.exact_replication_claimed,
        "rule_summary": spec.rule_summary,
        "data_required": spec.data_required,
        "proxy_used": spec.proxy_used,
        "proxy_warning": spec.proxy_warning,
        "source_url": spec.source_url,
        "unsupported_reason": result.unsupported_reason,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "data_end_max": str(VALID_END.date()),
        "parameters_json": json.dumps(result.parameters, sort_keys=True, ensure_ascii=False),
    }
    if result.status == "unsupported_exact":
        return row
    returns = result.returns.dropna()
    weights = result.weights.reindex(returns.index).fillna(0.0)
    spy = ctx.monthly_returns["US_EQ"].reindex(returns.index)
    for label, start, end in (
        ("train", TRAIN_START, TRAIN_END),
        ("validation", VALID_START, VALID_END),
        ("combined", TRAIN_START, VALID_END),
    ):
        period_rets = slice_period(returns, start, end)
        metrics = period_metrics(period_rets)
        row.update({f"{label}_{k}": v for k, v in metrics.items()})
        down = spy_down_metrics(period_rets, spy, weights)
        row.update({f"{label}_{k}": v for k, v in down.items()})
    row["correlation_to_spy"] = float(returns.corr(spy)) if returns.notna().sum() > 2 else float("nan")
    row["turnover_annual"] = turnover_annual(weights)
    row["cash_or_defensive_months_pct"] = cash_defensive_months_pct(weights)
    return row


def annual_rows(result: StudyResult, ctx: BacktestContext) -> list[dict[str, object]]:
    if result.status == "unsupported_exact":
        return []
    returns = result.returns.dropna()
    spy = ctx.monthly_returns["US_EQ"].reindex(returns.index).dropna()
    strat_annual = (1.0 + returns).resample("YE").prod(min_count=1) - 1.0
    spy_annual = (1.0 + spy).resample("YE").prod(min_count=1) - 1.0
    rows: list[dict[str, object]] = []
    for date, value in strat_annual.items():
        if date >= LOCKED_START or date < TRAIN_START:
            continue
        rows.append(
            {
                "paper_id": result.spec.paper_id,
                "paper_title": result.spec.paper_title,
                "year": int(date.year),
                "period": "train" if date <= TRAIN_END else "validation",
                "strategy_return_pct": float(value * 100.0),
                "spy_return_pct": float(spy_annual.get(date, np.nan) * 100.0),
            }
        )
    return rows


def monthly_return_rows(result: StudyResult, ctx: BacktestContext) -> pd.DataFrame:
    idx = pd.date_range(TRAIN_START, VALID_END, freq="ME")
    frame = pd.DataFrame(
        {
            "date": idx,
            "paper_id": result.spec.paper_id,
            "paper_title": result.spec.paper_title,
            "status": result.status,
            "strategy_return": result.returns.reindex(idx).to_numpy(dtype=float),
            "spy_return": ctx.monthly_returns["US_EQ"].reindex(idx).to_numpy(dtype=float),
        }
    )
    frame["period"] = np.where(frame["date"] <= TRAIN_END, "train", "validation")
    frame["strategy_nav"] = (1.0 + frame["strategy_return"].fillna(0.0)).cumprod()
    frame["spy_nav"] = (1.0 + frame["spy_return"].fillna(0.0)).cumprod()
    return frame


def drawdown_rows(result: StudyResult, ctx: BacktestContext) -> pd.DataFrame:
    frame = monthly_return_rows(result, ctx)
    frame["strategy_drawdown"] = frame["strategy_nav"] / frame["strategy_nav"].cummax() - 1.0
    frame["spy_drawdown"] = frame["spy_nav"] / frame["spy_nav"].cummax() - 1.0
    return frame[["date", "paper_id", "paper_title", "period", "strategy_drawdown", "spy_drawdown"]]


def spy_down_rows(result: StudyResult, ctx: BacktestContext) -> pd.DataFrame:
    if result.status == "unsupported_exact":
        return pd.DataFrame()
    frame = monthly_return_rows(result, ctx)
    out = frame.loc[frame["spy_return"] < 0.0].copy()
    out["strategy_positive"] = out["strategy_return"] > 0.0
    out["beats_spy"] = out["strategy_return"] > out["spy_return"]
    return out[["date", "paper_id", "paper_title", "period", "strategy_return", "spy_return", "strategy_positive", "beats_spy"]]


def write_report(summary: pd.DataFrame, out_dir: Path) -> None:
    evaluated = summary[summary["status"] != "unsupported_exact"].copy()
    sort_cols = [
        "validation_mdd_pct",
        "validation_spy_down_strategy_avg_return_pct",
        "validation_downside_capture_pct",
        "validation_calmar",
        "validation_sharpe",
    ]
    for col in sort_cols:
        if col not in evaluated:
            evaluated[col] = np.nan
    ranked = evaluated.sort_values(
        by=[
            "validation_mdd_pct",
            "validation_spy_down_strategy_avg_return_pct",
            "validation_downside_capture_pct",
            "validation_calmar",
            "validation_sharpe",
        ],
        ascending=[False, False, True, False, False],
    )
    lines = [
        "# Backtest 26 estudios S&P 500 downside protection",
        "",
        "Locked cerrado: `locked_opened=false`.",
        "",
        "## Top 10 por ranking principal",
        "",
        "| Rank | Paper | Estado | Valid CAGR | Valid Sharpe | Valid MDD | Retorno medio meses SPY cae | Downside capture |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for i, row in enumerate(ranked.head(10).itertuples(index=False), start=1):
        lines.append(
            f"| {i} | {getattr(row, 'paper_id')} | {getattr(row, 'status')} | "
            f"{getattr(row, 'validation_cagr_pct', np.nan):.2f}% | "
            f"{getattr(row, 'validation_sharpe', np.nan):.2f} | "
            f"{getattr(row, 'validation_mdd_pct', np.nan):.2f}% | "
            f"{getattr(row, 'validation_spy_down_strategy_avg_return_pct', np.nan):.2f}% | "
            f"{getattr(row, 'validation_downside_capture_pct', np.nan):.2f}% |"
        )
    lines += [
        "",
        "## Unsupported exact",
        "",
        "| Paper | Motivo |",
        "|---|---|",
    ]
    for row in summary.loc[summary["status"] == "unsupported_exact"].itertuples(index=False):
        lines.append(f"| {getattr(row, 'paper_id')} | {getattr(row, 'unsupported_reason')} |")
    (out_dir / "PAPER_26_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ctx = build_context()
    if ctx.monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError("locked data leaked into context")

    specs = build_specs()
    results: list[StudyResult] = []
    for spec in specs:
        result = spec.runner(ctx, spec)
        if result.status != "unsupported_exact":
            if result.returns.dropna().index.max() >= LOCKED_START:
                raise RuntimeError(f"locked data leaked into {spec.paper_id}")
        results.append(result)

    summary = pd.DataFrame([build_summary_row(result, ctx) for result in results])
    summary.to_csv(OUT_DIR / "paper_26_summary.csv", index=False)
    pd.concat([monthly_return_rows(result, ctx) for result in results], ignore_index=True).to_csv(
        OUT_DIR / "paper_26_monthly_returns.csv", index=False
    )
    pd.DataFrame([row for result in results for row in annual_rows(result, ctx)]).to_csv(
        OUT_DIR / "paper_26_annual_returns.csv", index=False
    )
    weights_frames = []
    for result in results:
        if result.weights.empty:
            continue
        frame = result.weights.copy()
        frame.insert(0, "paper_title", result.spec.paper_title)
        frame.insert(0, "paper_id", result.spec.paper_id)
        frame.insert(0, "date", frame.index)
        weights_frames.append(frame.reset_index(drop=True))
    pd.concat(weights_frames, ignore_index=True).to_csv(OUT_DIR / "paper_26_weights.csv", index=False)
    pd.concat([drawdown_rows(result, ctx) for result in results], ignore_index=True).to_csv(
        OUT_DIR / "paper_26_drawdown_paths.csv", index=False
    )
    down_frames = [spy_down_rows(result, ctx) for result in results]
    pd.concat([frame for frame in down_frames if not frame.empty], ignore_index=True).to_csv(
        OUT_DIR / "paper_26_spy_down_months.csv", index=False
    )
    ctx.proxy_map.to_csv(OUT_DIR / "paper_26_proxy_audit.csv", index=False)
    pd.DataFrame(
        {
            "locked_opened": [False],
            "locked_start": [str(LOCKED_START.date())],
            "max_data_date": [str(VALID_END.date())],
            "rows_at_or_after_locked": [0],
            "validation_used_for_selection": [False],
            "study_count": [len(specs)],
            "evaluated_count": [int((summary["status"] != "unsupported_exact").sum())],
            "unsupported_exact_count": [int((summary["status"] == "unsupported_exact").sum())],
        }
    ).to_csv(OUT_DIR / "paper_26_locked_audit.csv", index=False)
    (OUT_DIR / "paper_26_methodology.json").write_text(
        json.dumps(
            {
                "train": [str(TRAIN_START.date()), str(TRAIN_END.date())],
                "validation": [str(VALID_START.date()), str(VALID_END.date())],
                "locked_start": str(LOCKED_START.date()),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "signal_application": "month-end signal applied to following monthly return via weights.shift(1)",
                "ranking": [
                    "validation max drawdown higher is better",
                    "validation average return when SPY falls higher is better",
                    "validation downside capture lower is better",
                    "validation Calmar higher is better",
                    "validation Sharpe higher is better",
                ],
                "studies": [asdict(spec) | {"runner": spec.runner.__name__} for spec in specs],
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    write_report(summary, OUT_DIR)

    if len(summary) != 26:
        raise RuntimeError(f"Expected 26 studies, got {len(summary)}")
    if summary["locked_opened"].any():
        raise RuntimeError("locked_opened true in summary")
    if summary["validation_used_for_selection"].any():
        raise RuntimeError("validation_used_for_selection true in summary")
    print(summary[["rank", "paper_id", "status", "replication_level", "validation_cagr_pct", "validation_sharpe", "validation_mdd_pct"]].to_string(index=False))
    print(f"\nOutputs: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()

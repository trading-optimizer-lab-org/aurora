from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from aurora.core.runtime_paths import base_data_dir


CAMPAIGN_ID = "global_technical_buy_indicator_355jobs"
ARTIFACT_NAME = "global-technical-buy-indicator-355jobs-results"
DEFAULT_DATA_RUN_ID = "27936694743"
DEFAULT_DATA_ARTIFACT_NAME = "free-global-yahoo-daily-data-lake"
DEFAULT_TRAIN_END = "2010-12-31"
DEFAULT_VALIDATION_START = "2011-01-01"
DEFAULT_VALIDATION_END = "2020-12-31"
DEFAULT_LOCKED_START = "2021-01-01"
DEFAULT_SEARCH_METHOD = "surrogate_ml"
SEARCH_METHODS = ("surrogate_ml", "dehb_real")
DEFAULT_SELECTION_SPLIT = "train"
SELECTION_SPLITS = ("train", "validation")
DEFAULT_SCORING_PROFILE = "default"
SCORING_PROFILES = ("default", "strict_quality", "frequency_quality")
DEFAULT_FAMILIES = ("minervini_sepa", "oneil_canslim", "quallamaggie")
TRADINGVIEW_MINERVINI_FAMILIES = (
    "tv_minervini_qualifier",
    "tv_minervini_trend_template_ema",
    "tv_minervini_trend_template_sepa_pro",
    "tv_pocket_pivot_breakout",
    "tv_5ma_oneil_minervini",
    "tv_minervini_mtc",
    "tv_weinstein_stage",
    "tv_breakout_finder",
    "tv_rsi_strategy",
)
ALL_FAMILIES = DEFAULT_FAMILIES + TRADINGVIEW_MINERVINI_FAMILIES
FAMILY_SETS = ("default", "tradingview_minervini", "all")

PRICE_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume", "symbol"]
LEADERBOARD_COLUMNS = [
    "candidate_id",
    "stage",
    "search_method",
    "family",
    "score",
    "train_trades",
    "validation_trades",
    "train_avg_trade_return_pct",
    "validation_avg_trade_return_pct",
    "train_median_trade_return_pct",
    "validation_median_trade_return_pct",
    "train_win_rate",
    "validation_win_rate",
    "train_profit_factor",
    "validation_profit_factor",
    "train_trade_sharpe",
    "validation_trade_sharpe",
    "train_max_drawdown_pct",
    "validation_max_drawdown_pct",
    "train_avg_holding_days",
    "validation_avg_holding_days",
    "train_trades_per_year",
    "validation_trades_per_year",
    "selection_split",
    "selection_min_yearly_trades",
    "min_selection_trades_per_year",
    "strict_quality_pass",
    "strict_quality_failure_count",
    "strict_quality_failures",
    "validation_positive_years",
    "validation_median_positive_years",
    "validation_min_yearly_trades",
    "validation_min_yearly_profit_factor",
    "validation_max_profit_contribution_share",
    "train_2003_2010_positive_years",
    "train_2003_2010_min_profit_factor",
    "train_2003_2010_min_avg_trade_return_pct",
    "adjusted_return_time_risk",
    "scoring_profile",
    "locked_opened",
]
YEARLY_COLUMNS = [
    "candidate_id",
    "split",
    "year",
    "trades",
    "avg_trade_return_pct",
    "median_trade_return_pct",
    "win_rate",
    "profit_factor",
    "avg_holding_days",
    "spy_return_pct",
]
TRADE_COLUMNS = [
    "candidate_id",
    "symbol",
    "split",
    "entry_date",
    "exit_date",
    "entry_price",
    "exit_price",
    "return_pct",
    "holding_days",
    "exit_reason",
]


@dataclass(frozen=True)
class IndicatorConfig:
    family: str = "minervini_sepa"
    minervini_trend: bool = True
    require_rs: bool = True
    require_base_tight: bool = True
    require_breakout: bool = True
    require_pocket_pivot: bool = False
    require_oneil_stack: bool = False
    require_volume_dryup: bool = False
    require_prior_runup: bool = False
    require_episodic_gap: bool = False
    breakout_lookback: int = 50
    base_lookback: int = 20
    volume_lookback: int = 50
    rs_lookback: int = 63
    high_lookback: int = 252
    low_lookback: int = 252
    ma_short: int = 50
    ma_mid: int = 150
    ma_long: int = 200
    oneil_fast_ma: int = 10
    oneil_mid_ma: int = 21
    volume_multiple: float = 1.25
    max_base_range_pct: float = 0.18
    rs_near_high_pct: float = 0.98
    near_high_pct: float = 0.75
    above_low_multiple: float = 1.30
    rsi_period: int = 14
    rsi_max: float = 75.0
    prior_runup_lookback: int = 60
    prior_runup_min_pct: float = 0.30
    volume_dryup_lookback: int = 10
    volume_dryup_max_ratio: float = 0.75
    episodic_gap_pct: float = 0.06
    min_adr_pct: float = 0.02
    adr_lookback: int = 20
    stop_loss_pct: float = 0.08
    trailing_stop_pct: float = 0.18
    take_profit_pct: float = 0.0
    max_holding_days: int = 60
    use_exit_ma: bool = True
    exit_ma_days: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dt(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_convert(None)
    return ts.normalize()


def _prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    out = frame.copy()
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date"])
        out = out.set_index("date", drop=False)
    elif isinstance(out.index, pd.DatetimeIndex):
        out["date"] = out.index
    else:
        raise ValueError("price frame must have a date column or DatetimeIndex")
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index()
    for column in ("open", "high", "low", "close", "adj_close", "volume"):
        if column not in out.columns:
            if column in {"open", "high", "low", "adj_close"} and "close" in out.columns:
                out[column] = out["close"]
            elif column == "volume":
                out[column] = 0.0
            else:
                raise ValueError(f"missing price column {column!r}")
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[(out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0) & (out["close"] > 0)]
    return out


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / int(period), adjust=False, min_periods=int(period)).mean()
    avg_loss = loss.ewm(alpha=1 / int(period), adjust=False, min_periods=int(period)).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _safe_bool_series(value: bool, index: pd.Index) -> pd.Series:
    return pd.Series(bool(value), index=index, dtype=bool)


def _families_for_set(family_set: str) -> tuple[str, ...]:
    if family_set == "default":
        return DEFAULT_FAMILIES
    if family_set == "tradingview_minervini":
        return TRADINGVIEW_MINERVINI_FAMILIES
    if family_set == "all":
        return ALL_FAMILIES
    raise ValueError(f"unknown family_set {family_set!r}; expected one of {FAMILY_SETS}")


def entry_signal(prices: pd.DataFrame, benchmark_prices: pd.DataFrame, config: IndicatorConfig) -> pd.Series:
    """Return same-day buy indicator. Execution happens next session."""

    frame = _prepare_ohlcv(prices)
    if frame.empty:
        return pd.Series(dtype=bool)
    benchmark = _prepare_ohlcv(benchmark_prices)
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"].fillna(0.0)
    index = frame.index

    sma_short = close.rolling(config.ma_short, min_periods=config.ma_short).mean()
    sma_mid = close.rolling(config.ma_mid, min_periods=config.ma_mid).mean()
    sma_long = close.rolling(config.ma_long, min_periods=config.ma_long).mean()
    ema_short = close.ewm(span=config.ma_short, adjust=False, min_periods=config.ma_short).mean()
    ema_mid = close.ewm(span=config.ma_mid, adjust=False, min_periods=config.ma_mid).mean()
    ema_long = close.ewm(span=config.ma_long, adjust=False, min_periods=config.ma_long).mean()
    high_n = high.rolling(config.high_lookback, min_periods=min(config.high_lookback, len(frame))).max()
    low_n = low.rolling(config.low_lookback, min_periods=min(config.low_lookback, len(frame))).min()
    trend_ok = (
        (close > sma_short)
        & (close > sma_mid)
        & (close > sma_long)
        & (sma_short > sma_mid)
        & (sma_mid > sma_long)
        & (sma_long > sma_long.shift(21))
        & (close >= high_n * config.near_high_pct)
        & (close >= low_n * config.above_low_multiple)
    )
    if not config.minervini_trend:
        trend_ok = _safe_bool_series(True, index)

    if not benchmark.empty:
        spy_close = benchmark["close"].reindex(index).ffill()
        rs_line = close / spy_close.replace(0.0, np.nan)
        rs_avg = rs_line.rolling(config.rs_lookback, min_periods=min(config.rs_lookback, len(frame))).mean()
        rs_high = rs_line.rolling(config.rs_lookback, min_periods=min(config.rs_lookback, len(frame))).max()
        rs_ok = (rs_line > rs_avg) & (rs_line >= rs_high * config.rs_near_high_pct)
    else:
        rs_ok = _safe_bool_series(True, index)
    if not config.require_rs:
        rs_ok = _safe_bool_series(True, index)

    resistance = high.shift(1).rolling(config.breakout_lookback, min_periods=config.breakout_lookback).max()
    avg_vol = volume.rolling(config.volume_lookback, min_periods=min(config.volume_lookback, len(frame))).mean()
    base_range = (
        high.rolling(config.base_lookback, min_periods=config.base_lookback).max()
        - low.rolling(config.base_lookback, min_periods=config.base_lookback).min()
    )
    base_tight = (base_range / close) <= config.max_base_range_pct
    if not config.require_base_tight:
        base_tight = _safe_bool_series(True, index)
    breakout = (close > resistance) & (volume > avg_vol * config.volume_multiple) & base_tight
    if not config.require_breakout:
        breakout = _safe_bool_series(True, index)

    down_vol = volume.where(close < close.shift(1), 0.0)
    max_down_vol = down_vol.shift(1).rolling(10, min_periods=10).max()
    pocket_pivot = (close > close.shift(1)) & (volume > max_down_vol) & (close > sma_short) & (close > sma_long)
    if not config.require_pocket_pivot:
        pocket_pivot = _safe_bool_series(True, index)

    ma10 = close.rolling(config.oneil_fast_ma, min_periods=config.oneil_fast_ma).mean()
    ma21 = close.ewm(span=config.oneil_mid_ma, adjust=False, min_periods=config.oneil_mid_ma).mean()
    oneil_stack = (close > ma10) & (ma10 > ma21) & (ma21 > sma_short) & (sma_short > sma_long)
    if not config.require_oneil_stack:
        oneil_stack = _safe_bool_series(True, index)

    prior_runup = (close / close.shift(config.prior_runup_lookback) - 1.0) >= config.prior_runup_min_pct
    if not config.require_prior_runup:
        prior_runup = _safe_bool_series(True, index)

    recent_vol = volume.rolling(config.volume_dryup_lookback, min_periods=config.volume_dryup_lookback).mean()
    long_vol = volume.rolling(config.volume_lookback, min_periods=min(config.volume_lookback, len(frame))).mean()
    dryup = recent_vol <= long_vol * config.volume_dryup_max_ratio
    if not config.require_volume_dryup:
        dryup = _safe_bool_series(True, index)

    adr = close.pct_change().abs().rolling(config.adr_lookback, min_periods=config.adr_lookback).mean()
    adr_ok = adr >= config.min_adr_pct
    gap = (frame["open"] / close.shift(1) - 1.0) >= config.episodic_gap_pct
    gap = gap & (volume > avg_vol * max(config.volume_multiple, 1.5))
    if not config.require_episodic_gap:
        gap = _safe_bool_series(True, index)

    rsi_ok = _rsi(close, config.rsi_period).fillna(50.0) <= config.rsi_max
    rsi_line = _rsi(close, config.rsi_period).fillna(50.0)
    ema_trend_ok = (
        (close > ema_short)
        & (close > ema_mid)
        & (close > ema_long)
        & (ema_short > ema_mid)
        & (ema_mid > ema_long)
        & (ema_long > ema_long.shift(21))
        & (close >= high_n * config.near_high_pct)
        & (close >= low_n * config.above_low_multiple)
    )
    sma50 = close.rolling(50, min_periods=50).mean()
    sma150 = close.rolling(150, min_periods=150).mean()
    sma200 = close.rolling(200, min_periods=200).mean()
    ma10_sma = close.rolling(10, min_periods=10).mean()
    ma21_sma = close.rolling(21, min_periods=21).mean()
    oneil_buy = (
        (close > sma50)
        & (close > sma200)
        & (sma50 > sma50.shift(20))
        & (sma200 > sma200.shift(20))
        & (close >= high_n * max(config.near_high_pct, 0.85))
    )
    minervini_5ma_buy = (
        (ma10_sma > ma21_sma)
        & (ma21_sma > sma50)
        & (ma10_sma > ma10_sma.shift(5))
        & (ma21_sma > ma21_sma.shift(5))
        & (close >= high_n * max(config.near_high_pct, 0.75))
        & (close >= low_n * max(config.above_low_multiple, 1.25))
    )
    mtc_ok = (
        (close > sma50)
        & (close > sma150)
        & (close > sma200)
        & (sma50 > sma150)
        & (sma150 > sma200)
        & (sma200 > sma200.shift(21))
        & (close >= low_n * config.above_low_multiple)
        & (close >= high_n * config.near_high_pct)
    )
    stage2 = (close > sma150) & (sma150 > sma150.shift(20)) & (sma50 > sma150)
    stage2_minervini = stage2 & (close > sma50) & (sma50 > sma150) & (sma150 > sma200) & (sma200 > sma200.shift(21))
    pocket_pivot_3pct = (
        ((close / frame["open"].replace(0.0, np.nan) - 1.0) >= 0.03)
        & (volume > max_down_vol)
        & (close > ema_short)
        & (close > ema_long)
    )
    channel_high = high.shift(1).rolling(config.breakout_lookback, min_periods=config.breakout_lookback).max()
    channel_low = low.shift(1).rolling(config.breakout_lookback, min_periods=config.breakout_lookback).min()
    channel_width = ((channel_high - channel_low) / close).fillna(np.inf)
    tests = (high.shift(1) >= channel_high * (1.0 - max(config.max_base_range_pct, 0.02))).rolling(
        config.base_lookback, min_periods=max(2, min(config.base_lookback, 5))
    ).sum()
    breakout_finder = (
        (close > channel_high)
        & (tests >= 2)
        & (channel_width <= max(config.max_base_range_pct, 0.02))
        & (volume >= avg_vol * max(config.volume_multiple, 1.0))
    )
    oversold_level = max(15.0, min(45.0, 100.0 - float(config.rsi_max)))
    rsi_rebound = (rsi_line.shift(1) <= oversold_level) & (rsi_line > oversold_level) & (close > sma_long)

    if config.family == "oneil_canslim":
        signal = oneil_stack & rs_ok & breakout & rsi_ok
    elif config.family == "quallamaggie":
        signal = (trend_ok | (close > sma_short)) & prior_runup & dryup & (breakout | gap) & adr_ok & rsi_ok
    elif config.family == "tv_minervini_qualifier":
        signal = trend_ok & rs_ok & (close > close.rolling(20, min_periods=20).mean()) & rsi_ok
    elif config.family == "tv_minervini_trend_template_ema":
        signal = ema_trend_ok & (breakout if config.require_breakout else _safe_bool_series(True, index)) & rsi_ok
    elif config.family == "tv_minervini_trend_template_sepa_pro":
        signal = ema_trend_ok & rs_ok & (base_tight | dryup) & (breakout | gap) & rsi_ok
    elif config.family == "tv_pocket_pivot_breakout":
        signal = ema_trend_ok & (pocket_pivot | pocket_pivot_3pct) & rsi_ok
    elif config.family == "tv_5ma_oneil_minervini":
        signal = ((oneil_buy & minervini_5ma_buy) | (config.require_breakout and breakout)) & rsi_ok
    elif config.family == "tv_minervini_mtc":
        signal = mtc_ok & rsi_ok
    elif config.family == "tv_weinstein_stage":
        signal = (stage2_minervini if config.minervini_trend else stage2) & rsi_ok
    elif config.family == "tv_breakout_finder":
        signal = breakout_finder & rsi_ok
    elif config.family == "tv_rsi_strategy":
        signal = rsi_rebound
    else:
        signal = trend_ok & rs_ok & breakout & pocket_pivot & rsi_ok
    return signal.fillna(False).astype(bool)


def _open_or_close(frame: pd.DataFrame, idx: int) -> float:
    value = frame["open"].iloc[idx]
    if pd.isna(value) or float(value) <= 0:
        value = frame["close"].iloc[idx]
    return float(value)


def _record_trade(
    *,
    candidate_id: str,
    symbol: str,
    split: str,
    frame: pd.DataFrame,
    entry_idx: int,
    exit_idx: int,
    entry_price: float,
    exit_reason: str,
) -> dict[str, Any]:
    exit_price = _open_or_close(frame, exit_idx) if exit_idx > entry_idx else float(frame["close"].iloc[exit_idx])
    entry_date = pd.Timestamp(frame.index[entry_idx]).date().isoformat()
    exit_date = pd.Timestamp(frame.index[exit_idx]).date().isoformat()
    return {
        "candidate_id": candidate_id,
        "symbol": symbol,
        "split": split,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "return_pct": float((exit_price / entry_price - 1.0) * 100.0),
        "holding_days": int(exit_idx - entry_idx),
        "exit_reason": exit_reason,
    }


def simulate_trades(
    symbol: str,
    prices: pd.DataFrame,
    signal: pd.Series,
    config: IndicatorConfig,
    *,
    split: str,
    candidate_id: str = "",
) -> pd.DataFrame:
    """Simulate long/cash trades from a buy indicator, executing next session."""

    frame = _prepare_ohlcv(prices)
    if frame.empty or len(frame) < 3:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    signal = signal.reindex(frame.index).fillna(False).astype(bool)
    exit_ma = frame["close"].rolling(config.exit_ma_days, min_periods=config.exit_ma_days).mean()

    trades: list[dict[str, Any]] = []
    in_position = False
    entry_idx = -1
    entry_price = 0.0
    high_water = 0.0
    i = 0
    while i < len(frame) - 1:
        if not in_position:
            if bool(signal.iloc[i]):
                entry_idx = i + 1
                entry_price = _open_or_close(frame, entry_idx)
                high_water = float(frame["high"].iloc[entry_idx])
                in_position = True
                i = entry_idx
                continue
            i += 1
            continue

        high_water = max(high_water, float(frame["high"].iloc[i]))
        reason: str | None = None
        if float(frame["low"].iloc[i]) <= entry_price * (1.0 - config.stop_loss_pct):
            reason = "stop_loss"
        elif config.take_profit_pct > 0 and float(frame["high"].iloc[i]) >= entry_price * (1.0 + config.take_profit_pct):
            reason = "take_profit"
        elif config.trailing_stop_pct > 0 and float(frame["low"].iloc[i]) <= high_water * (1.0 - config.trailing_stop_pct):
            reason = "trailing_stop"
        elif config.use_exit_ma and pd.notna(exit_ma.iloc[i]) and float(frame["close"].iloc[i]) < float(exit_ma.iloc[i]):
            reason = "exit_ma"
        elif min(i + 1, len(frame) - 1) - entry_idx >= config.max_holding_days:
            reason = "max_holding"

        if reason is not None:
            exit_idx = min(i + 1, len(frame) - 1)
            trades.append(
                _record_trade(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    split=split,
                    frame=frame,
                    entry_idx=entry_idx,
                    exit_idx=exit_idx,
                    entry_price=entry_price,
                    exit_reason=reason,
                )
            )
            in_position = False
            i = exit_idx
            continue
        i += 1

    if in_position:
        trades.append(
            _record_trade(
                candidate_id=candidate_id,
                symbol=symbol,
                split=split,
                frame=frame,
                entry_idx=entry_idx,
                exit_idx=len(frame) - 1,
                entry_price=entry_price,
                exit_reason="end_of_data",
            )
        )
    return pd.DataFrame(trades, columns=TRADE_COLUMNS)


def split_trade_frame(
    trades: pd.DataFrame,
    *,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    out = trades.copy()
    exit_dates = pd.to_datetime(out["exit_date"], errors="coerce")
    train_mask = exit_dates <= _dt(train_end)
    valid_mask = (exit_dates >= _dt(validation_start)) & (exit_dates <= _dt(validation_end))
    out.loc[train_mask, "split"] = "train"
    out.loc[valid_mask, "split"] = "validation"
    out = out[train_mask | valid_mask].copy()
    return out


def summarize_trades(trades: pd.DataFrame, *, years: float) -> dict[str, float]:
    if trades.empty:
        return {
            "trades": 0.0,
            "avg_trade_return_pct": float("nan"),
            "median_trade_return_pct": float("nan"),
            "win_rate": float("nan"),
            "profit_factor": float("nan"),
            "trade_sharpe": float("nan"),
            "trade_sortino": float("nan"),
            "max_drawdown_pct": float("nan"),
            "avg_holding_days": float("nan"),
            "trades_per_year": 0.0,
            "return_concentration": float("nan"),
        }
    returns = pd.to_numeric(trades["return_pct"], errors="coerce").dropna() / 100.0
    if returns.empty:
        return summarize_trades(pd.DataFrame(), years=years)
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    profit_factor = float(wins.sum() / abs(losses.sum())) if float(losses.sum()) < 0 else float("inf")
    std = float(returns.std(ddof=0))
    trades_per_year = float(len(returns) / max(years, 1e-9))
    scale = math.sqrt(max(trades_per_year, 1.0))
    sharpe = float((returns.mean() / std) * scale) if std > 1e-12 else 0.0
    downside = returns[returns < 0]
    dstd = float(downside.std(ddof=0)) if len(downside) > 1 else std
    sortino = float((returns.mean() / dstd) * scale) if dstd > 1e-12 else 0.0
    nav = np.cumprod(1.0 + returns.to_numpy())
    dd = nav / np.maximum.accumulate(nav) - 1.0
    years_by_exit = pd.to_datetime(trades["exit_date"], errors="coerce").dt.year
    per_year = trades.assign(_year=years_by_exit).groupby("_year")["return_pct"].count()
    concentration = float(per_year.max() / len(trades)) if len(trades) else float("nan")
    return {
        "trades": float(len(returns)),
        "avg_trade_return_pct": float(returns.mean() * 100.0),
        "median_trade_return_pct": float(returns.median() * 100.0),
        "win_rate": float((returns > 0).mean()),
        "profit_factor": profit_factor,
        "trade_sharpe": sharpe,
        "trade_sortino": sortino,
        "max_drawdown_pct": float(dd.min() * 100.0),
        "avg_holding_days": float(pd.to_numeric(trades["holding_days"], errors="coerce").mean()),
        "trades_per_year": trades_per_year,
        "return_concentration": concentration,
    }


def _spy_return_by_year(benchmark_prices: pd.DataFrame) -> dict[int, float]:
    frame = _prepare_ohlcv(benchmark_prices)
    if frame.empty:
        return {}
    out: dict[int, float] = {}
    for year, group in frame.groupby(frame.index.year):
        close = group["close"].dropna()
        if len(close) >= 2 and float(close.iloc[0]) > 0:
            out[int(year)] = float((close.iloc[-1] / close.iloc[0] - 1.0) * 100.0)
    return out


def yearly_trade_performance(trades: pd.DataFrame, benchmark_prices: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=YEARLY_COLUMNS)
    frame = trades.copy()
    frame["exit_date"] = pd.to_datetime(frame["exit_date"], errors="coerce")
    frame = frame.dropna(subset=["exit_date"])
    frame["year"] = frame["exit_date"].dt.year.astype(int)
    spy_by_year = _spy_return_by_year(benchmark_prices)
    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_id", "split", "year"]
    for (candidate_id, split, year), group in frame.groupby(group_cols, dropna=False):
        ret = pd.to_numeric(group["return_pct"], errors="coerce").dropna()
        wins = ret[ret > 0]
        losses = ret[ret < 0]
        pf = float(wins.sum() / abs(losses.sum())) if float(losses.sum()) < 0 else float("inf")
        rows.append(
            {
                "candidate_id": candidate_id,
                "split": split,
                "year": int(year),
                "trades": int(len(group)),
                "avg_trade_return_pct": float(ret.mean()) if len(ret) else float("nan"),
                "median_trade_return_pct": float(ret.median()) if len(ret) else float("nan"),
                "win_rate": float((ret > 0).mean()) if len(ret) else float("nan"),
                "profit_factor": pf,
                "avg_holding_days": float(pd.to_numeric(group["holding_days"], errors="coerce").mean()),
                "spy_return_pct": spy_by_year.get(int(year), float("nan")),
            }
        )
    return pd.DataFrame(rows, columns=YEARLY_COLUMNS).sort_values(["candidate_id", "split", "year"]).reset_index(drop=True)


def _candidate_score(train: dict[str, float]) -> float:
    trades = train.get("trades", 0.0)
    if trades < 8:
        return -1e9 + trades
    pf = min(float(train.get("profit_factor", 0.0) or 0.0), 5.0)
    avg = float(train.get("avg_trade_return_pct", 0.0) or 0.0)
    med = float(train.get("median_trade_return_pct", 0.0) or 0.0)
    sharpe = float(train.get("trade_sharpe", 0.0) or 0.0)
    sortino = float(train.get("trade_sortino", 0.0) or 0.0)
    win_rate = float(train.get("win_rate", 0.0) or 0.0)
    mdd = abs(float(train.get("max_drawdown_pct", 0.0) or 0.0))
    holding = float(train.get("avg_holding_days", 0.0) or 0.0)
    tpy = float(train.get("trades_per_year", 0.0) or 0.0)
    concentration = float(train.get("return_concentration", 1.0) or 1.0)
    return (
        avg * 0.35
        + med * 0.20
        + sharpe * 2.0
        + sortino * 1.25
        + pf * 1.5
        + win_rate * 2.0
        + min(tpy, 80.0) * 0.02
        - mdd * 0.08
        - max(holding - 40.0, 0.0) * 0.02
        - max(concentration - 0.35, 0.0) * 8.0
    )


def _finite_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _yearly_for_split(yearly: pd.DataFrame, split: str, years: range) -> pd.DataFrame:
    cols = [col for col in YEARLY_COLUMNS if col != "candidate_id"]
    if yearly.empty:
        base = pd.DataFrame({"year": list(years)})
    else:
        selected = yearly[yearly["split"] == split].copy()
        base = selected.set_index("year").reindex(list(years)).reset_index()
    base["split"] = split
    for col in cols:
        if col not in base.columns:
            base[col] = np.nan
    base["trades"] = pd.to_numeric(base["trades"], errors="coerce").fillna(0).astype(int)
    for col in ("avg_trade_return_pct", "median_trade_return_pct", "profit_factor", "avg_holding_days", "spy_return_pct"):
        base[col] = pd.to_numeric(base[col], errors="coerce")
    return base


def _strict_quality_metrics(
    *,
    row: dict[str, Any],
    yearly: pd.DataFrame,
    validation_start: str,
    validation_end: str,
) -> dict[str, Any]:
    validation_years = range(_dt(validation_start).year, _dt(validation_end).year + 1)
    validation_yearly = _yearly_for_split(yearly, "validation", validation_years)
    train_yearly = _yearly_for_split(yearly, "train", range(2003, 2011))
    failures: list[str] = []

    validation_min_trades = int(validation_yearly["trades"].min()) if not validation_yearly.empty else 0
    if validation_min_trades < 100:
        failures.append("validation_yearly_trades_lt_100")
    validation_avg = pd.to_numeric(validation_yearly["avg_trade_return_pct"], errors="coerce")
    validation_positive_years = int((validation_avg > 0.0).sum())
    if validation_positive_years < len(list(validation_years)):
        failures.append("validation_not_10_positive_years")
    validation_median = pd.to_numeric(validation_yearly["median_trade_return_pct"], errors="coerce")
    validation_median_positive_years = int((validation_median > 0.0).sum())
    if validation_median_positive_years < 7:
        failures.append("validation_median_positive_years_lt_7")
    validation_pf = pd.to_numeric(validation_yearly["profit_factor"], errors="coerce")
    validation_min_pf = _finite_float(validation_pf.min(), default=float("-inf"))
    if validation_min_pf < 1.05:
        failures.append("validation_yearly_profit_factor_lt_1_05")

    validation_global_median = _finite_float(row.get("validation_median_trade_return_pct"), default=float("-inf"))
    if validation_global_median <= 0.0:
        failures.append("validation_global_median_not_positive")
    validation_global_pf = _finite_float(row.get("validation_profit_factor"), default=float("-inf"))
    if validation_global_pf < 1.4:
        failures.append("validation_profit_factor_lt_1_4")
    validation_tpy = _finite_float(row.get("validation_trades_per_year"), default=0.0)
    if validation_tpy < 150.0:
        failures.append("validation_trades_per_year_lt_150")
    validation_global_avg = _finite_float(row.get("validation_avg_trade_return_pct"), default=float("-inf"))
    if validation_global_median <= 0.0 or validation_global_avg > validation_global_median * 5.0:
        failures.append("validation_avg_gt_5x_median")

    annual_profit = validation_avg.fillna(0.0) * validation_yearly["trades"].astype(float)
    total_positive_profit = float(annual_profit[annual_profit > 0.0].sum())
    if total_positive_profit > 0.0:
        max_share = float(annual_profit.max() / total_positive_profit)
    else:
        max_share = 1.0
    if max_share > 0.25:
        failures.append("validation_profit_concentration_gt_25pct")

    train_avg = pd.to_numeric(train_yearly["avg_trade_return_pct"], errors="coerce")
    train_positive_years = int((train_avg > 0.0).sum())
    train_pf = pd.to_numeric(train_yearly["profit_factor"], errors="coerce")
    train_min_pf = _finite_float(train_pf.min(), default=float("-inf"))
    train_min_avg = _finite_float(train_avg.min(), default=float("-inf"))
    if train_positive_years < 8:
        failures.append("train_2003_2010_not_8_positive_years")
    if train_min_pf < 1.05:
        failures.append("train_2003_2010_profit_factor_lt_1_05")
    if train_min_avg < 0.0:
        failures.append("train_2003_2010_avg_return_negative")

    holding = max(_finite_float(row.get("validation_avg_holding_days"), default=0.0), 1.0)
    drawdown = max(abs(_finite_float(row.get("validation_max_drawdown_pct"), default=0.0)), 0.01)
    adjusted = validation_global_avg / (holding * drawdown) if math.isfinite(validation_global_avg) else float("-inf")
    failure_text = ";".join(failures)
    return {
        "strict_quality_pass": bool(not failures),
        "strict_quality_failure_count": int(len(failures)),
        "strict_quality_failures": failure_text,
        "validation_positive_years": int(validation_positive_years),
        "validation_median_positive_years": int(validation_median_positive_years),
        "validation_min_yearly_trades": int(validation_min_trades),
        "validation_min_yearly_profit_factor": float(validation_min_pf),
        "validation_max_profit_contribution_share": float(max_share),
        "train_2003_2010_positive_years": int(train_positive_years),
        "train_2003_2010_min_profit_factor": float(train_min_pf),
        "train_2003_2010_min_avg_trade_return_pct": float(train_min_avg),
        "adjusted_return_time_risk": float(adjusted),
    }


def _strict_quality_score(row: dict[str, Any]) -> float:
    adjusted = _finite_float(row.get("adjusted_return_time_risk"), default=-1e6)
    med = _finite_float(row.get("validation_median_trade_return_pct"), default=0.0)
    pf = min(_finite_float(row.get("validation_profit_factor"), default=0.0), 5.0)
    yearly_trades = min(_finite_float(row.get("validation_trades_per_year"), default=0.0), 500.0)
    concentration = _finite_float(row.get("validation_max_profit_contribution_share"), default=1.0)
    if bool(row.get("strict_quality_pass")):
        return 1_000_000.0 + adjusted * 10_000.0 + med * 100.0 + pf * 10.0 + yearly_trades * 0.1 - concentration * 100.0
    return (
        -1_000_000.0
        - float(row.get("strict_quality_failure_count", 99)) * 10_000.0
        + float(row.get("validation_positive_years", 0)) * 500.0
        + float(row.get("validation_median_positive_years", 0)) * 250.0
        + float(row.get("train_2003_2010_positive_years", 0)) * 250.0
        + min(float(row.get("validation_min_yearly_trades", 0)), 150.0)
        + med * 100.0
        + pf * 10.0
    )


def _frequency_quality_score(row: dict[str, Any]) -> float:
    if bool(row.get("strict_quality_pass")):
        return _strict_quality_score(row)
    min_trades = _finite_float(row.get("validation_min_yearly_trades"), default=0.0)
    trades_per_year = _finite_float(row.get("validation_trades_per_year"), default=0.0)
    val_pos = _finite_float(row.get("validation_positive_years"), default=0.0)
    med_pos = _finite_float(row.get("validation_median_positive_years"), default=0.0)
    train_pos = _finite_float(row.get("train_2003_2010_positive_years"), default=0.0)
    val_pf = min(_finite_float(row.get("validation_profit_factor"), default=0.0), 5.0)
    yearly_pf = min(_finite_float(row.get("validation_min_yearly_profit_factor"), default=0.0), 2.0)
    train_pf = min(_finite_float(row.get("train_2003_2010_min_profit_factor"), default=0.0), 2.0)
    med = _finite_float(row.get("validation_median_trade_return_pct"), default=0.0)
    avg = _finite_float(row.get("validation_avg_trade_return_pct"), default=0.0)
    concentration = _finite_float(row.get("validation_max_profit_contribution_share"), default=1.0)
    fail_count = _finite_float(row.get("strict_quality_failure_count"), default=99.0)
    return (
        -1_000_000.0
        - fail_count * 3_000.0
        + min(min_trades, 150.0) * 85.0
        + min(trades_per_year, 300.0) * 20.0
        + val_pos * 1_250.0
        + med_pos * 650.0
        + train_pos * 800.0
        + val_pf * 1_500.0
        + yearly_pf * 1_200.0
        + train_pf * 1_200.0
        + med * 500.0
        + avg * 100.0
        - max(concentration - 0.25, 0.0) * 4_000.0
    )


def _candidate_id(config: IndicatorConfig, stage: int, sequence: int) -> str:
    payload = {"config": config.to_dict(), "stage": int(stage), "sequence": int(sequence)}
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"gtbi_s{stage:03d}_{digest}"


def _min_yearly_trades_for_selection(
    yearly: pd.DataFrame,
    *,
    selection_split: str,
    train_end: str,
    validation_start: str,
    validation_end: str,
) -> int:
    if yearly.empty:
        return 0
    selected = yearly[yearly["split"] == selection_split].copy()
    if selected.empty:
        return 0
    if selection_split == "validation":
        years = range(_dt(validation_start).year, _dt(validation_end).year + 1)
    else:
        first_year = int(selected["year"].min())
        years = range(first_year, _dt(train_end).year + 1)
    trades = selected.set_index("year")["trades"].reindex(list(years), fill_value=0)
    return int(trades.min()) if len(trades) else 0


def evaluate_candidate(
    *,
    config: IndicatorConfig,
    candidate_id: str,
    stage: int,
    symbol_frames: dict[str, pd.DataFrame],
    benchmark_prices: pd.DataFrame,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
    search_method: str = DEFAULT_SEARCH_METHOD,
    selection_split: str = DEFAULT_SELECTION_SPLIT,
    min_selection_trades_per_year: int = 0,
    scoring_profile: str = DEFAULT_SCORING_PROFILE,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    all_trades: list[pd.DataFrame] = []
    for symbol, frame in symbol_frames.items():
        signal = entry_signal(frame, benchmark_prices, config)
        raw_trades = simulate_trades(symbol, frame, signal, config, split="unassigned", candidate_id=candidate_id)
        trades = split_trade_frame(
            raw_trades,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
        )
        if not trades.empty:
            all_trades.append(trades)
    trades_df = pd.concat(all_trades, ignore_index=True, sort=False) if all_trades else pd.DataFrame(columns=TRADE_COLUMNS)
    train_years = max((_dt(train_end) - pd.Timestamp("1900-01-01")).days / 365.25, 1.0)
    if not trades_df.empty:
        first_train = pd.to_datetime(trades_df.loc[trades_df["split"] == "train", "exit_date"], errors="coerce").min()
        if pd.notna(first_train):
            train_years = max((_dt(train_end) - first_train).days / 365.25, 1.0)
    validation_years = max((_dt(validation_end) - _dt(validation_start)).days / 365.25, 1.0)
    train = summarize_trades(trades_df[trades_df["split"] == "train"], years=train_years)
    validation = summarize_trades(trades_df[trades_df["split"] == "validation"], years=validation_years)
    yearly = yearly_trade_performance(trades_df, benchmark_prices)
    selected_metrics = validation if selection_split == "validation" else train
    score = _candidate_score(selected_metrics)
    selection_min_yearly_trades = _min_yearly_trades_for_selection(
        yearly,
        selection_split=selection_split,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
    )
    if int(min_selection_trades_per_year) > 0 and selection_min_yearly_trades < int(min_selection_trades_per_year):
        score = -1e9 + float(selection_min_yearly_trades)
    row = {
        "candidate_id": candidate_id,
        "stage": int(stage),
        "search_method": str(search_method),
        "family": config.family,
        "score": score,
        "selection_split": str(selection_split),
        "selection_min_yearly_trades": int(selection_min_yearly_trades),
        "min_selection_trades_per_year": int(min_selection_trades_per_year),
        "scoring_profile": str(scoring_profile),
        "locked_opened": False,
    }
    for prefix, metrics in (("train", train), ("validation", validation)):
        row[f"{prefix}_trades"] = int(metrics["trades"])
        row[f"{prefix}_avg_trade_return_pct"] = metrics["avg_trade_return_pct"]
        row[f"{prefix}_median_trade_return_pct"] = metrics["median_trade_return_pct"]
        row[f"{prefix}_win_rate"] = metrics["win_rate"]
        row[f"{prefix}_profit_factor"] = metrics["profit_factor"]
        row[f"{prefix}_trade_sharpe"] = metrics["trade_sharpe"]
        row[f"{prefix}_max_drawdown_pct"] = metrics["max_drawdown_pct"]
        row[f"{prefix}_avg_holding_days"] = metrics["avg_holding_days"]
        row[f"{prefix}_trades_per_year"] = metrics["trades_per_year"]
    row.update(
        _strict_quality_metrics(
            row=row,
            yearly=yearly,
            validation_start=validation_start,
            validation_end=validation_end,
        )
    )
    if scoring_profile == "strict_quality":
        score = _strict_quality_score(row)
    elif scoring_profile == "frequency_quality":
        score = _frequency_quality_score(row)
    elif scoring_profile != "default":
        raise ValueError(f"unknown scoring_profile {scoring_profile!r}; expected one of {SCORING_PROFILES}")
    row["score"] = score
    return row, trades_df, yearly


_NUMERIC_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "breakout_lookback": (10, 126, True),
    "base_lookback": (5, 80, True),
    "volume_lookback": (10, 100, True),
    "rs_lookback": (10, 126, True),
    "high_lookback": (63, 252, True),
    "low_lookback": (63, 252, True),
    "ma_short": (20, 80, True),
    "ma_mid": (80, 180, True),
    "ma_long": (120, 220, True),
    "oneil_fast_ma": (5, 20, True),
    "oneil_mid_ma": (10, 40, True),
    "volume_multiple": (1.0, 3.0, False),
    "max_base_range_pct": (0.06, 0.40, False),
    "rs_near_high_pct": (0.85, 1.0, False),
    "near_high_pct": (0.60, 0.98, False),
    "above_low_multiple": (1.0, 1.90, False),
    "rsi_period": (7, 21, True),
    "rsi_max": (55.0, 98.0, False),
    "prior_runup_lookback": (15, 126, True),
    "prior_runup_min_pct": (0.05, 1.20, False),
    "volume_dryup_lookback": (3, 30, True),
    "volume_dryup_max_ratio": (0.30, 1.10, False),
    "episodic_gap_pct": (0.02, 0.18, False),
    "min_adr_pct": (0.002, 0.08, False),
    "adr_lookback": (5, 40, True),
    "stop_loss_pct": (0.03, 0.16, False),
    "trailing_stop_pct": (0.04, 0.30, False),
    "take_profit_pct": (0.0, 1.50, False),
    "max_holding_days": (3, 90, True),
    "exit_ma_days": (5, 50, True),
}


def _sample_dehb_real_config(rng: np.random.Generator, family_set: str = "default") -> IndicatorConfig:
    family = str(rng.choice(_families_for_set(family_set)))
    params: dict[str, Any] = {
        "family": family,
        "breakout_lookback": int(rng.choice([10, 15, 20, 30, 50, 63, 100])),
        "base_lookback": int(rng.choice([5, 10, 15, 20, 30, 40])),
        "volume_lookback": int(rng.choice([10, 20, 30, 50, 80])),
        "rs_lookback": int(rng.choice([21, 42, 63, 126])),
        "volume_multiple": float(rng.uniform(1.0, 2.0)),
        "max_base_range_pct": float(rng.uniform(0.10, 0.32)),
        "rs_near_high_pct": float(rng.uniform(0.88, 1.0)),
        "near_high_pct": float(rng.uniform(0.65, 0.92)),
        "above_low_multiple": float(rng.uniform(1.00, 1.60)),
        "rsi_max": float(rng.uniform(65.0, 95.0)),
        "prior_runup_lookback": int(rng.choice([20, 30, 42, 63, 90])),
        "prior_runup_min_pct": float(rng.uniform(0.08, 0.65)),
        "volume_dryup_lookback": int(rng.choice([5, 10, 15, 20])),
        "volume_dryup_max_ratio": float(rng.uniform(0.45, 1.0)),
        "episodic_gap_pct": float(rng.uniform(0.03, 0.10)),
        "min_adr_pct": float(rng.uniform(0.003, 0.045)),
        "stop_loss_pct": float(rng.uniform(0.04, 0.12)),
        "trailing_stop_pct": float(rng.uniform(0.05, 0.22)),
        "take_profit_pct": float(rng.choice([0.0, 0.0, rng.uniform(0.18, 0.80)])),
        "max_holding_days": int(rng.choice([5, 8, 10, 15, 20, 30, 45, 60])),
        "exit_ma_days": int(rng.choice([10, 20, 21, 50])),
        "use_exit_ma": bool(rng.random() < 0.90),
    }
    if family == "minervini_sepa":
        params.update(
            minervini_trend=bool(rng.random() < 0.75),
            require_rs=bool(rng.random() < 0.55),
            require_base_tight=bool(rng.random() < 0.60),
            require_breakout=bool(rng.random() < 0.80),
            require_pocket_pivot=bool(rng.random() < 0.20),
        )
    elif family == "oneil_canslim":
        params.update(
            minervini_trend=bool(rng.random() < 0.35),
            require_rs=bool(rng.random() < 0.50),
            require_oneil_stack=bool(rng.random() < 0.85),
            require_base_tight=bool(rng.random() < 0.50),
            require_breakout=bool(rng.random() < 0.80),
        )
    elif family == "quallamaggie":
        params.update(
            minervini_trend=bool(rng.random() < 0.20),
            require_rs=bool(rng.random() < 0.25),
            require_base_tight=bool(rng.random() < 0.45),
            require_breakout=bool(rng.random() < 0.70),
            require_prior_runup=bool(rng.random() < 0.55),
            require_volume_dryup=bool(rng.random() < 0.35),
            require_episodic_gap=bool(rng.random() < 0.08),
        )
    elif family in {"tv_minervini_qualifier", "tv_minervini_mtc"}:
        params.update(
            minervini_trend=True,
            require_rs=bool(rng.random() < 0.45),
            require_base_tight=False,
            require_breakout=False,
            near_high_pct=float(rng.uniform(0.70, 0.85)),
            above_low_multiple=float(rng.uniform(1.15, 1.45)),
        )
    elif family in {"tv_minervini_trend_template_ema", "tv_minervini_trend_template_sepa_pro"}:
        params.update(
            minervini_trend=True,
            require_rs=bool(rng.random() < 0.50),
            require_base_tight=bool(rng.random() < 0.60),
            require_breakout=bool(rng.random() < 0.70),
            require_volume_dryup=bool(rng.random() < 0.40),
            near_high_pct=float(rng.uniform(0.70, 0.85)),
            above_low_multiple=float(rng.uniform(1.15, 1.45)),
        )
    elif family == "tv_pocket_pivot_breakout":
        params.update(
            minervini_trend=True,
            require_rs=bool(rng.random() < 0.35),
            require_pocket_pivot=True,
            require_breakout=False,
            near_high_pct=float(rng.uniform(0.65, 0.85)),
            above_low_multiple=float(rng.uniform(1.05, 1.45)),
        )
    elif family == "tv_5ma_oneil_minervini":
        params.update(
            minervini_trend=False,
            require_rs=False,
            require_breakout=bool(rng.random() < 0.35),
            near_high_pct=float(rng.uniform(0.75, 0.90)),
            above_low_multiple=float(rng.uniform(1.20, 1.50)),
        )
    elif family == "tv_weinstein_stage":
        params.update(
            minervini_trend=bool(rng.random() < 0.70),
            require_rs=False,
            require_breakout=False,
            near_high_pct=float(rng.uniform(0.70, 0.85)),
            above_low_multiple=float(rng.uniform(1.05, 1.35)),
        )
    elif family == "tv_breakout_finder":
        params.update(
            minervini_trend=False,
            require_rs=False,
            require_base_tight=True,
            require_breakout=True,
            breakout_lookback=int(rng.choice([20, 30, 50, 80, 100])),
            base_lookback=int(rng.choice([10, 20, 30, 50])),
            max_base_range_pct=float(rng.uniform(0.05, 0.18)),
        )
    elif family == "tv_rsi_strategy":
        params.update(
            minervini_trend=False,
            require_rs=False,
            require_breakout=False,
            rsi_max=float(rng.uniform(60.0, 80.0)),
            use_exit_ma=bool(rng.random() < 0.70),
        )
    return IndicatorConfig(**params)


def _mutate_config(rng: np.random.Generator, base: IndicatorConfig, family_set: str = "default") -> IndicatorConfig:
    data = base.to_dict()
    field_names = [field.name for field in fields(IndicatorConfig) if field.name != "family"]
    for name in rng.choice(field_names, size=int(rng.integers(3, 8)), replace=False):
        value = data[name]
        if isinstance(value, bool):
            if rng.random() < 0.35:
                data[name] = not value
            continue
        if name not in _NUMERIC_BOUNDS:
            continue
        low, high, is_int = _NUMERIC_BOUNDS[name]
        if isinstance(value, int) or is_int:
            step = int(max(1, round((high - low) * rng.uniform(-0.18, 0.18))))
            data[name] = int(np.clip(int(value) + step, low, high))
        else:
            scale = float(rng.uniform(0.75, 1.25))
            jitter = float(rng.normal(0.0, (high - low) * 0.04))
            data[name] = float(np.clip(float(value) * scale + jitter, low, high))
    if rng.random() < 0.08:
        data["family"] = str(rng.choice(_families_for_set(family_set)))
    return IndicatorConfig(**data)


def sample_config(
    rng: np.random.Generator,
    search_method: str = DEFAULT_SEARCH_METHOD,
    family_set: str = "default",
) -> IndicatorConfig:
    if search_method == "dehb_real":
        return _sample_dehb_real_config(rng, family_set=family_set)
    family = str(rng.choice(_families_for_set(family_set)))
    params: dict[str, Any] = {
        "family": family,
        "breakout_lookback": int(rng.integers(20, 126)),
        "base_lookback": int(rng.integers(10, 61)),
        "volume_lookback": int(rng.integers(20, 81)),
        "rs_lookback": int(rng.choice([21, 42, 63, 126])),
        "volume_multiple": float(rng.uniform(1.05, 3.0)),
        "max_base_range_pct": float(rng.uniform(0.08, 0.35)),
        "rs_near_high_pct": float(rng.uniform(0.90, 1.0)),
        "near_high_pct": float(rng.uniform(0.70, 0.95)),
        "above_low_multiple": float(rng.uniform(1.10, 1.80)),
        "rsi_max": float(rng.uniform(60.0, 95.0)),
        "prior_runup_lookback": int(rng.integers(20, 126)),
        "prior_runup_min_pct": float(rng.uniform(0.10, 1.00)),
        "volume_dryup_lookback": int(rng.integers(5, 26)),
        "volume_dryup_max_ratio": float(rng.uniform(0.35, 1.05)),
        "episodic_gap_pct": float(rng.uniform(0.03, 0.15)),
        "min_adr_pct": float(rng.uniform(0.005, 0.08)),
        "stop_loss_pct": float(rng.uniform(0.04, 0.15)),
        "trailing_stop_pct": float(rng.uniform(0.08, 0.35)),
        "take_profit_pct": float(rng.choice([0.0, rng.uniform(0.20, 1.50)])),
        "max_holding_days": int(rng.integers(10, 181)),
        "exit_ma_days": int(rng.choice([10, 20, 21, 50])),
        "use_exit_ma": bool(rng.random() < 0.80),
    }
    if family == "minervini_sepa":
        params.update(
            minervini_trend=bool(rng.random() < 0.90),
            require_rs=bool(rng.random() < 0.80),
            require_base_tight=bool(rng.random() < 0.85),
            require_breakout=True,
            require_pocket_pivot=bool(rng.random() < 0.35),
        )
    elif family == "oneil_canslim":
        params.update(
            minervini_trend=bool(rng.random() < 0.45),
            require_rs=bool(rng.random() < 0.85),
            require_oneil_stack=True,
            require_base_tight=bool(rng.random() < 0.70),
            require_breakout=True,
        )
    elif family == "quallamaggie":
        params.update(
            minervini_trend=bool(rng.random() < 0.35),
            require_rs=bool(rng.random() < 0.50),
            require_base_tight=bool(rng.random() < 0.80),
            require_breakout=bool(rng.random() < 0.80),
            require_prior_runup=bool(rng.random() < 0.85),
            require_volume_dryup=bool(rng.random() < 0.70),
            require_episodic_gap=bool(rng.random() < 0.20),
        )
    else:
        return _sample_dehb_real_config(rng, family_set=family_set)
    return IndicatorConfig(**params)


def _config_vector(config: IndicatorConfig) -> list[float]:
    vector = [1.0 if config.family == name else 0.0 for name in ALL_FAMILIES]
    for field in fields(IndicatorConfig):
        if field.name == "family":
            continue
        value = getattr(config, field.name)
        if isinstance(value, bool):
            vector.append(1.0 if value else 0.0)
        elif isinstance(value, (int, float)):
            vector.append(float(value))
    return vector


def _choose_surrogate_configs(
    rng: np.random.Generator,
    observed: list[tuple[IndicatorConfig, float]],
    count: int,
    search_method: str = DEFAULT_SEARCH_METHOD,
    family_set: str = "default",
) -> tuple[list[IndicatorConfig], bool]:
    if count <= 0:
        return [], False
    if search_method == "dehb_real":
        if not observed:
            return [sample_config(rng, search_method=search_method, family_set=family_set) for _ in range(count)], False
        ranked = sorted(observed, key=lambda item: item[1], reverse=True)
        parents = [cfg for cfg, _score in ranked[: min(12, max(3, len(ranked) // 4))]]
        configs: list[IndicatorConfig] = []
        for _ in range(count):
            if parents and rng.random() < 0.75:
                configs.append(_mutate_config(rng, parents[int(rng.integers(0, len(parents)))], family_set=family_set))
            else:
                configs.append(sample_config(rng, search_method=search_method, family_set=family_set))
        return configs, True
    if len(observed) < 12:
        return [sample_config(rng, search_method=search_method, family_set=family_set) for _ in range(count)], False
    try:
        from sklearn.ensemble import ExtraTreesRegressor
    except Exception:
        return [sample_config(rng, search_method=search_method, family_set=family_set) for _ in range(count)], False
    pool = [sample_config(rng, search_method=search_method, family_set=family_set) for _ in range(max(count * 5, 50))]
    x = np.asarray([_config_vector(cfg) for cfg, _score in observed], dtype=float)
    y = np.asarray([score for _cfg, score in observed], dtype=float)
    model = ExtraTreesRegressor(n_estimators=96, max_depth=8, random_state=int(rng.integers(0, 2**31 - 1)))
    model.fit(x, y)
    pred = model.predict(np.asarray([_config_vector(cfg) for cfg in pool], dtype=float))
    selected = [cfg for _score, cfg in sorted(zip(pred, pool, strict=False), key=lambda item: item[0], reverse=True)[:count]]
    return selected, True


def _load_symbol_frames(prices_path: Path) -> dict[str, pd.DataFrame]:
    prices = pd.read_parquet(prices_path)
    if prices.empty:
        return {}
    if "symbol" not in prices.columns:
        raise ValueError(f"{prices_path} does not contain a symbol column")
    return {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in prices.groupby("symbol", sort=True)
    }


def run_stage(
    *,
    pack_dir: Path,
    output_dir: Path,
    stage: int,
    configs_per_stage: int = 1500,
    time_budget_minutes: float = 25.0,
    top_per_stage: int = 50,
    seed: int = 42,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
    search_method: str = DEFAULT_SEARCH_METHOD,
    selection_split: str = DEFAULT_SELECTION_SPLIT,
    min_selection_trades_per_year: int = 0,
    family_set: str = "default",
    scoring_profile: str = DEFAULT_SCORING_PROFILE,
) -> dict[str, Any]:
    pack_dir = Path(pack_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if search_method not in SEARCH_METHODS:
        raise ValueError(f"unknown search_method {search_method!r}; expected one of {SEARCH_METHODS}")
    if selection_split not in SELECTION_SPLITS:
        raise ValueError(f"unknown selection_split {selection_split!r}; expected one of {SELECTION_SPLITS}")
    if scoring_profile not in SCORING_PROFILES:
        raise ValueError(f"unknown scoring_profile {scoring_profile!r}; expected one of {SCORING_PROFILES}")
    _families_for_set(family_set)
    symbol_frames = _load_symbol_frames(pack_dir / "prices.parquet")
    benchmark = pd.read_parquet(pack_dir / "benchmark.parquet")
    rng = np.random.default_rng(int(seed) + int(stage) * 1009)
    start = time.monotonic()
    deadline = start + max(float(time_budget_minutes), 0.01) * 60.0
    initial = min(int(configs_per_stage), max(24, int(configs_per_stage * 0.35)))
    remaining = max(int(configs_per_stage) - initial, 0)
    configs = [sample_config(rng, search_method=search_method, family_set=family_set) for _ in range(initial)]
    observed: list[tuple[IndicatorConfig, float]] = []
    rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    yearly_frames: list[pd.DataFrame] = []
    rules: list[dict[str, Any]] = []
    surrogate_used = False

    sequence = 0
    while configs and time.monotonic() < deadline:
        config = configs.pop(0)
        candidate_id = _candidate_id(config, stage, sequence)
        row, trades, yearly = evaluate_candidate(
            config=config,
            candidate_id=candidate_id,
            stage=stage,
            symbol_frames=symbol_frames,
            benchmark_prices=benchmark,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            search_method=search_method,
            selection_split=selection_split,
            min_selection_trades_per_year=min_selection_trades_per_year,
            scoring_profile=scoring_profile,
        )
        rows.append(row)
        observed.append((config, float(row["score"])))
        if not trades.empty:
            trade_frames.append(trades)
        if not yearly.empty:
            yearly_frames.append(yearly)
        rules.append(
            {
                "candidate_id": candidate_id,
                "stage": int(stage),
                "search_method": str(search_method),
                "selection_split": str(selection_split),
                "family_set": str(family_set),
                "scoring_profile": str(scoring_profile),
                "config": config.to_dict(),
                "score": row["score"],
            }
        )
        sequence += 1
        if sequence == initial and remaining > 0:
            extra, used = _choose_surrogate_configs(
                rng,
                observed,
                remaining,
                search_method=search_method,
                family_set=family_set,
            )
            surrogate_used = surrogate_used or used
            configs.extend(extra)
    leaderboard = pd.DataFrame(rows, columns=LEADERBOARD_COLUMNS)
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values(["score", "candidate_id"], ascending=[False, True]).head(top_per_stage)
    top_ids = set(leaderboard["candidate_id"].astype(str)) if not leaderboard.empty else set()
    trades_out = (
        pd.concat(trade_frames, ignore_index=True, sort=False)
        if trade_frames
        else pd.DataFrame(columns=TRADE_COLUMNS)
    )
    yearly_out = (
        pd.concat(yearly_frames, ignore_index=True, sort=False)
        if yearly_frames
        else pd.DataFrame(columns=YEARLY_COLUMNS)
    )
    if top_ids:
        trades_out = trades_out[trades_out["candidate_id"].astype(str).isin(top_ids)].copy()
        yearly_out = yearly_out[yearly_out["candidate_id"].astype(str).isin(top_ids)].copy()
        rules = [rule for rule in rules if str(rule["candidate_id"]) in top_ids]
    leaderboard.to_csv(output_dir / "leaderboard.csv", index=False)
    yearly_out.to_csv(output_dir / "yearly_trade_performance.csv", index=False)
    trades_out.head(5000).to_csv(output_dir / "top_trades_sample.csv", index=False)
    with (output_dir / "top_indicator_rules.jsonl").open("w", encoding="utf-8") as handle:
        for rule in rules:
            handle.write(json.dumps(rule, sort_keys=True) + "\n")
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "stage": int(stage),
        "symbols": int(len(symbol_frames)),
        "configs_requested": int(configs_per_stage),
        "configs_evaluated": int(len(rows)),
        "surrogate_used": bool(surrogate_used),
        "search_method": str(search_method),
        "locked_opened": False,
        "selection_split": str(selection_split),
        "family_set": str(family_set),
        "scoring_profile": str(scoring_profile),
        "min_selection_trades_per_year": int(min_selection_trades_per_year),
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _read_universe_symbols(lake_root: Path) -> list[str]:
    candidates = [
        lake_root / "universe" / "us_stock_like_universe.parquet",
        lake_root / "universe.parquet",
    ]
    for path in candidates:
        if path.exists():
            frame = pd.read_parquet(path)
            for column in ("canonical_symbol", "symbol", "yfinance_symbol"):
                if column in frame.columns:
                    return sorted({str(v) for v in frame[column].dropna().astype(str) if str(v).upper() != "SPY"})
    normalized = lake_root / "normalized"
    if normalized.exists():
        return sorted(p.stem for p in normalized.glob("*.parquet") if p.stem.upper() != "SPY")
    raise FileNotFoundError(f"could not find universe under {lake_root}")


def _filter_symbols_by_market_cap(lake_root: Path, symbols: list[str], min_market_cap: float) -> list[str]:
    if float(min_market_cap) <= 0:
        return symbols
    candidates = [
        lake_root / "metadata" / "company_metadata.parquet",
        lake_root / "company_metadata.parquet",
    ]
    metadata_path = next((path for path in candidates if path.exists()), None)
    if metadata_path is None:
        raise FileNotFoundError(f"min_market_cap requested but company metadata not found under {lake_root}")
    metadata = pd.read_parquet(metadata_path)
    if "market_cap" not in metadata.columns:
        raise ValueError(f"{metadata_path} does not contain market_cap")
    symbol_column = next((column for column in ("symbol", "canonical_symbol", "yfinance_symbol") if column in metadata.columns), None)
    if symbol_column is None:
        raise ValueError(f"{metadata_path} does not contain a symbol column")
    cap = pd.to_numeric(metadata["market_cap"], errors="coerce")
    eligible = set(metadata.loc[cap >= float(min_market_cap), symbol_column].dropna().astype(str))
    return [symbol for symbol in symbols if symbol in eligible]


def _load_benchmark(lake_root: Path, locked_start: str) -> pd.DataFrame:
    candidates = [
        lake_root / "normalized" / "SPY.parquet",
        lake_root / "benchmarks" / "SPY.parquet",
        lake_root / "benchmarks" / "GSPC.parquet",
    ]
    for path in candidates:
        if path.exists():
            frame = _prepare_ohlcv(pd.read_parquet(path))
            return frame[frame.index < _dt(locked_start)].reset_index(drop=True)
    raise FileNotFoundError("SPY benchmark not found; run free-us-daily build-benchmarks first")


def build_stage_packs(
    lake_root: Path,
    output_dir: Path,
    *,
    stage_count: int = 355,
    group_count: int = 1,
    locked_start: str = DEFAULT_LOCKED_START,
    min_rows: int = 260,
    min_market_cap: float = 0.0,
) -> dict[str, Any]:
    lake_root = Path(lake_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_symbols = _read_universe_symbols(lake_root)
    symbols = _filter_symbols_by_market_cap(lake_root, all_symbols, min_market_cap)
    normalized = lake_root / "normalized"
    benchmark = _load_benchmark(lake_root, locked_start)
    grouped: dict[int, list[str]] = {stage: [] for stage in range(stage_count)}
    for idx, symbol in enumerate(symbols):
        grouped[idx % stage_count].append(symbol)
    stage_rows: list[dict[str, Any]] = []
    for stage in range(stage_count):
        group_index = stage % max(int(group_count), 1)
        if group_count > 1:
            stage_dir = output_dir / f"group-{group_index:03d}" / f"stage-{stage:03d}"
        else:
            stage_dir = output_dir / f"stage-{stage:03d}"
        stage_dir.mkdir(parents=True, exist_ok=True)
        frames: list[pd.DataFrame] = []
        for symbol in grouped[stage]:
            path = normalized / f"{symbol}.parquet"
            if not path.exists():
                continue
            try:
                frame = _prepare_ohlcv(pd.read_parquet(path))
            except Exception:
                continue
            frame = frame[frame.index < _dt(locked_start)].copy()
            if len(frame) < min_rows:
                continue
            frame["symbol"] = symbol
            frames.append(frame.reset_index(drop=True)[PRICE_COLUMNS])
        prices = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
        prices.to_parquet(stage_dir / "prices.parquet", index=False)
        benchmark.to_parquet(stage_dir / "benchmark.parquet", index=False)
        stage_rows.append(
            {
                "stage": stage,
                "group": group_index,
                "symbols": int(prices["symbol"].nunique()) if not prices.empty else 0,
                "rows": int(len(prices)),
            }
        )
    manifest = {
        "campaign_id": CAMPAIGN_ID,
        "created_at": pd.Timestamp.utcnow().isoformat(),
        "lake_root": str(lake_root),
        "stage_count": int(stage_count),
        "group_count": int(group_count),
        "locked_start": str(locked_start),
        "min_market_cap": float(min_market_cap),
        "symbols_before_market_cap_filter": int(len(all_symbols)),
        "symbols_requested": int(len(symbols)),
        "stages": stage_rows,
        "locked_opened": False,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame(stage_rows).to_csv(output_dir / "manifest.csv", index=False)
    return manifest


def merge_stage_outputs(stage_dirs: Iterable[Path], output_dir: Path, *, top_n: int = 250) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    leaderboards: list[pd.DataFrame] = []
    yearly_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    rule_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for stage_dir in sorted(Path(p) for p in stage_dirs):
        lb = stage_dir / "leaderboard.csv"
        if lb.exists() and lb.stat().st_size:
            leaderboards.append(pd.read_csv(lb))
        yearly = stage_dir / "yearly_trade_performance.csv"
        if yearly.exists() and yearly.stat().st_size:
            yearly_frames.append(pd.read_csv(yearly))
        trades = stage_dir / "top_trades_sample.csv"
        if trades.exists() and trades.stat().st_size:
            trade_frames.append(pd.read_csv(trades))
        rules = stage_dir / "top_indicator_rules.jsonl"
        if rules.exists():
            for line in rules.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rule_rows.append(json.loads(line))
        summary_path = stage_dir / "summary.json"
        if summary_path.exists():
            summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))

    all_leaderboard = pd.concat(leaderboards, ignore_index=True, sort=False) if leaderboards else pd.DataFrame(columns=LEADERBOARD_COLUMNS)
    candidates_before = int(len(all_leaderboard))
    filtered_leaderboard = pd.DataFrame(columns=all_leaderboard.columns)
    if not all_leaderboard.empty and "strict_quality_pass" in all_leaderboard.columns:
        pass_mask = all_leaderboard["strict_quality_pass"].astype(str).str.lower().isin({"true", "1", "yes"})
        filtered_leaderboard = all_leaderboard.loc[pass_mask].copy()
        if not filtered_leaderboard.empty:
            filtered_leaderboard = filtered_leaderboard.sort_values(
                [
                    "adjusted_return_time_risk",
                    "validation_median_trade_return_pct",
                    "validation_median_positive_years",
                    "validation_max_profit_contribution_share",
                    "validation_max_drawdown_pct",
                    "validation_trades_per_year",
                    "candidate_id",
                ],
                ascending=[False, False, False, True, False, False, True],
            )
    leaderboard = all_leaderboard
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values(["score", "candidate_id"], ascending=[False, True]).head(top_n)
    top_ids = set(leaderboard["candidate_id"].astype(str)) if not leaderboard.empty else set()
    yearly = pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else pd.DataFrame(columns=YEARLY_COLUMNS)
    trades = pd.concat(trade_frames, ignore_index=True, sort=False) if trade_frames else pd.DataFrame(columns=TRADE_COLUMNS)
    if top_ids:
        yearly = yearly[yearly["candidate_id"].astype(str).isin(top_ids)].copy()
        trades = trades[trades["candidate_id"].astype(str).isin(top_ids)].copy()
        rule_rows = [row for row in rule_rows if str(row.get("candidate_id")) in top_ids]

    leaderboard.to_csv(output_dir / "leaderboard.csv", index=False)
    filtered_leaderboard.to_csv(output_dir / "filtered_leaderboard.csv", index=False)
    yearly.to_csv(output_dir / "yearly_trade_performance.csv", index=False)
    trades.to_csv(output_dir / "top_trades_sample.csv", index=False)
    with (output_dir / "top_indicator_rules.jsonl").open("w", encoding="utf-8") as handle:
        for row in sorted(rule_rows, key=lambda item: str(item.get("candidate_id", ""))):
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    if not leaderboard.empty and "family" in leaderboard.columns:
        family = (
            leaderboard.groupby("family", dropna=False)
            .agg(candidates=("candidate_id", "count"), best_score=("score", "max"), avg_score=("score", "mean"))
            .reset_index()
            .sort_values(["best_score", "family"], ascending=[False, True])
        )
    else:
        family = pd.DataFrame(columns=["family", "candidates", "best_score", "avg_score"])
    family.to_csv(output_dir / "family_summary.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "artifact_name": ARTIFACT_NAME,
        "stages_seen": int(len(summaries)),
        "candidates": candidates_before,
        "top_n": int(len(leaderboard)),
        "filtered_candidates": int(len(filtered_leaderboard)),
        "locked_opened": False,
        "selection_split": (
            None if leaderboard.empty or "selection_split" not in leaderboard.columns else str(leaderboard.iloc[0]["selection_split"])
        ),
        "search_method": (
            None if leaderboard.empty or "search_method" not in leaderboard.columns else str(leaderboard.iloc[0]["search_method"])
        ),
        "best_candidate_id": None if leaderboard.empty else str(leaderboard.iloc[0]["candidate_id"]),
        "best_score": None if leaderboard.empty else float(leaderboard.iloc[0]["score"]),
        "best_filtered_candidate_id": None if filtered_leaderboard.empty else str(filtered_leaderboard.iloc[0]["candidate_id"]),
        "best_filtered_adjusted_return_time_risk": (
            None if filtered_leaderboard.empty else float(filtered_leaderboard.iloc[0]["adjusted_return_time_risk"])
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _default_run_root() -> Path:
    return base_data_dir() / "runs" / CAMPAIGN_ID


def build_pack_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build stage packs for global technical buy indicator search.")
    parser.add_argument("--data-lake-root", type=Path, default=base_data_dir() / "prices" / "free_us_daily")
    parser.add_argument("--output-dir", type=Path, default=_default_run_root() / "pack")
    parser.add_argument("--stage-count", type=int, default=355)
    parser.add_argument("--group-count", type=int, default=32)
    parser.add_argument("--locked-start", default=DEFAULT_LOCKED_START)
    parser.add_argument("--min-rows", type=int, default=260)
    parser.add_argument("--min-market-cap", type=float, default=0.0)
    args = parser.parse_args(argv)
    manifest = build_stage_packs(
        args.data_lake_root,
        args.output_dir,
        stage_count=args.stage_count,
        group_count=args.group_count,
        locked_start=args.locked_start,
        min_rows=args.min_rows,
        min_market_cap=args.min_market_cap,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def run_stage_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one global technical buy indicator stage.")
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=_default_run_root() / "stage-output")
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--configs-per-stage", type=int, default=1500)
    parser.add_argument("--time-budget-minutes", type=float, default=25.0)
    parser.add_argument("--top-per-stage", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--validation-start", default=DEFAULT_VALIDATION_START)
    parser.add_argument("--validation-end", default=DEFAULT_VALIDATION_END)
    parser.add_argument("--search-method", choices=SEARCH_METHODS, default=DEFAULT_SEARCH_METHOD)
    parser.add_argument("--selection-split", choices=SELECTION_SPLITS, default=DEFAULT_SELECTION_SPLIT)
    parser.add_argument("--min-selection-trades-per-year", type=int, default=0)
    parser.add_argument("--family-set", choices=FAMILY_SETS, default="default")
    parser.add_argument("--scoring-profile", choices=SCORING_PROFILES, default=DEFAULT_SCORING_PROFILE)
    args = parser.parse_args(argv)
    summary = run_stage(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir,
        stage=args.stage,
        configs_per_stage=args.configs_per_stage,
        time_budget_minutes=args.time_budget_minutes,
        top_per_stage=args.top_per_stage,
        seed=args.seed,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        search_method=args.search_method,
        selection_split=args.selection_split,
        min_selection_trades_per_year=args.min_selection_trades_per_year,
        family_set=args.family_set,
        scoring_profile=args.scoring_profile,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def merge_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge global technical buy indicator stage outputs.")
    parser.add_argument("--stages-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=_default_run_root() / "final")
    parser.add_argument("--top-n", type=int, default=250)
    args = parser.parse_args(argv)
    stage_dirs = [p for p in args.stages_root.rglob("*") if p.is_dir() and (p / "leaderboard.csv").exists()]
    summary = merge_stage_outputs(stage_dirs, args.output_dir, top_n=args.top_n)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0

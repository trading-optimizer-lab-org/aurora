from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import math
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from aurora.core.runtime_paths import base_data_dir


CAMPAIGN_ID = "global_technical_buy_indicator_355jobs"
ARTIFACT_NAME = "global-technical-buy-indicator-355jobs-results"
EXTERNAL_PACK_ARTIFACT_NAME = "global-technical-buy-indicator-external-pack-72000-results"
DEFAULT_EXTERNAL_STRATEGY_PACK_PATH = Path("scripts/strategy_packs/gtbi_research_broad_72000")
DEFAULT_DATA_RUN_ID = "27936694743"
DEFAULT_DATA_ARTIFACT_NAME = "free-global-yahoo-daily-data-lake"
DEFAULT_TRAIN_END = "2010-12-31"
DEFAULT_VALIDATION_START = "2011-01-01"
DEFAULT_VALIDATION_END = "2020-12-31"
DEFAULT_LOCKED_START = "2021-01-01"
DEFAULT_EXTERNAL_CANDIDATE_TIMEOUT_SECONDS = 1_200
DEFAULT_SEARCH_METHOD = "surrogate_ml"
SEARCH_METHODS = ("surrogate_ml", "dehb_real")
EXTERNAL_SEARCH_METHOD = "external_strategy_pack"
DEFAULT_SELECTION_SPLIT = "train"
SELECTION_SPLITS = ("train", "validation")
DEFAULT_SCORING_PROFILE = "default"
SCORING_PROFILES = ("default", "strict_quality", "frequency_quality", "stability_quality")
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
STABILITY_FAMILIES = (
    "stability_pullback_rebound",
    "stability_trend_reclaim",
    "stability_market_dip",
    "stability_rs_momentum_pullback",
    "stability_rs_reclaim_frequent",
    "stability_rs_pullback_breakout",
)
STABILITY_RS_FAMILIES = (
    "stability_pullback_rebound",
    "stability_trend_reclaim",
    "stability_rs_momentum_pullback",
    "stability_rs_reclaim_frequent",
    "stability_rs_pullback_breakout",
)
ALL_FAMILIES = DEFAULT_FAMILIES + TRADINGVIEW_MINERVINI_FAMILIES + STABILITY_FAMILIES
FAMILY_SETS = ("default", "tradingview_minervini", "stability", "stability_rs", "all")

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
    "strategy_id",
    "shard_id",
    "slot_in_shard",
    "concept_id",
    "market_overlay_id",
    "trend_profile_id",
    "rs_profile_id",
    "exit_profile_id",
    "aggression_id",
    "source_quality_score",
    "external_strategy_pack",
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
UNSUPPORTED_COLUMNS = ["strategy_id", "shard_id", "slot_in_shard", "unsupported_rules", "reason"]
TIMEOUT_COLUMNS = [
    "strategy_id",
    "shard_id",
    "slot_in_shard",
    "family",
    "concept",
    "market_overlay",
    "trend_filter",
    "relative_strength_filter",
    "exit_rule",
    "aggressiveness",
    "reason",
    "seconds_until_timeout",
]
EARLY_REJECT_COLUMNS = [
    "strategy_id",
    "reason",
    "split",
    "year",
    "actual",
    "threshold",
    "stage",
    "seconds_until_reject",
    "symbols_processed",
]
RUNTIME_ERROR_COLUMNS = [
    "strategy_id",
    "shard_id",
    "slot_in_shard",
    "family",
    "concept",
    "market_overlay",
    "trend_filter",
    "relative_strength_filter",
    "exit_rule",
    "aggressiveness",
    "reason",
]
TIMING_DIAGNOSTIC_COLUMNS = [
    "strategy_id",
    "job_id",
    "shard_id",
    "slot_in_shard",
    "family",
    "concept",
    "market_overlay",
    "trend_filter",
    "relative_strength_filter",
    "exit_rule",
    "aggressiveness",
    "seconds_total",
    "seconds_feature_build",
    "seconds_signal",
    "seconds_simulation",
    "seconds_train",
    "seconds_validation",
    "symbols_total",
    "symbols_processed",
    "raw_signals_total",
    "trades_total",
    "train_trades",
    "validation_trades",
    "result_status",
    "reject_reason",
    "timeout",
    "early_rejected",
    "runtime_error",
]
DEDUPE_MAP_COLUMNS = [
    "strategy_id",
    "canonical_hash",
    "canonical_strategy_id",
    "deduped",
    "signal_hash",
    "signal_canonical_strategy_id",
    "signal_deduped",
]
JOB_WALL_CLOCK_SHUTDOWN_MARGIN_SECONDS = 60.0
JOB_MANIFEST_COLUMNS = [
    "job_id",
    "strategy_id",
    "shard_id",
    "slot_in_shard",
    "canonical_hash",
    "signal_hash",
    "cost_score",
    "estimated_cost_bucket",
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
    require_market_trend: bool = False
    strict_market_filter: bool = False
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
    use_market_exit: bool = False
    exit_ma_days: int = 20
    market_ma_days: int = 200
    market_momentum_days: int = 21

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EXTERNAL_REQUIRED_FIELDS = (
    "strategy_id",
    "shard_id",
    "slot_in_shard",
    "concept_id",
    "market_overlay_id",
    "trend_profile_id",
    "rs_profile_id",
    "exit_profile_id",
    "aggression_id",
    "entry_rules",
    "market_regime_rules",
    "stock_trend_rules",
    "relative_strength_rules",
    "exit_rules",
    "guardrails",
    "research_source_ids",
    "source_quality_score",
    "codex_notes",
)


EXTERNAL_SUPPORTED_RULE_KEYS = {
    "entry_rules": {
        "adx14_min",
        "atr20_vs_atr60_max",
        "atr_mult",
        "avg_pullback_volume_max_adv20_mult",
        "avoid_if_distance_above_slow_ma_pct_gt",
        "bandwidth_percentile_126d_max",
        "base_depth_pct_max",
        "base_depth_pct_min",
        "base_length_days_max",
        "base_length_days_min",
        "bb_length",
        "bb_std",
        "breakdown_level",
        "breakout_lookback_days",
        "close_above",
        "close_above_level",
        "close_above_support",
        "close_above_upper_band",
        "close_breaks_above_high_n",
        "close_crosses_above",
        "close_gt_gap_day_midpoint",
        "close_gt_open",
        "close_gt_prior_close",
        "close_gt_prior_high",
        "close_gt_sma150",
        "close_gt_sma200",
        "close_gt_sma50",
        "close_position_in_range_min",
        "close_reclaims",
        "close_reclaims_lower_band",
        "close_vs_prev_close_min_pct",
        "close_within_52w_high_pct_max",
        "close_within_ema20_pct",
        "close_within_pivot_pct_max",
        "contractions_max",
        "contractions_min",
        "ema_stack",
        "entry_trigger",
        "exit_default",
        "fast_ma",
        "gap_down_min_pct",
        "gap_open_vs_prev_close_min_pct",
        "handle_depth_pct_max",
        "handle_length_days_min",
        "higher_lows_required",
        "histogram_higher_than_prior",
        "histogram_prior_below_zero",
        "inside_days_max",
        "inside_days_min",
        "keltner_length",
        "last_10d_range_pct_max",
        "last_5d_return_max_pct",
        "last_contraction_pct_max",
        "low_below_level_pct_min",
        "low_holds_ema20_or_sma50",
        "low_touched_ema20_or_ema50",
        "low_undercuts_support_pct_min",
        "low_within_ma_pct",
        "ma_choice",
        "macd_fast",
        "macd_signal",
        "macd_slow",
        "max_close_to_close_range_pct",
        "max_consecutive_down_closes",
        "max_intraday_range_avg_pct",
        "max_single_pullback_volume_adv20_mult",
        "next_entry",
        "not_second_ep_within_days",
        "nr_days_lookback",
        "plus_di_crosses_above_minus_di",
        "price_below_50d_high_pct_max",
        "price_below_50d_high_pct_min",
        "price_within_52w_high_pct_max",
        "prior_10d_down_volume_dryup",
        "prior_20d_return_max_pct",
        "prior_close_below_lower_band_within_days",
        "prior_close_below_sma20_within_days",
        "prior_low_touched_lower_or_mid_channel",
        "prior_return_63d_min_pct",
        "prior_runup_lookback_days",
        "prior_runup_min_pct",
        "prior_trend_required",
        "prior_uptrend_min_pct",
        "pullback_days_max",
        "pullback_days_min",
        "pullback_from_52w_high_max_pct",
        "pullback_from_52w_high_min_pct",
        "pullback_from_gap_close_max_pct",
        "pullback_from_gap_close_min_pct",
        "pullback_from_recent_high_max_pct",
        "pullback_from_recent_high_min_pct",
        "range_20d_pct_max",
        "range_5d_pct_max",
        "range_contraction_ratio_max",
        "rebound_confirmation",
        "recent_gap_up_days_ago_max",
        "recent_gap_up_days_ago_min",
        "recent_gap_volume_min_adv20_mult",
        "red_candle_body_range_max",
        "red_days_count_min",
        "red_volume_spike_max_adv20_mult",
        "return_126d_min_pct",
        "return_21d_min_pct",
        "return_252d_ex_last_21d_min_pct",
        "return_252d_min_pct",
        "return_63d_min_pct",
        "rs_ratio_symbol_spy_gt_sma20",
        "rs_ratio_symbol_spy_gt_sma50",
        "rs_ratio_symbol_spy_new_high_50d",
        "rsi2_max",
        "rsi_max_signal",
        "rsi_period",
        "signal_volume_gt_max_down_volume_days",
        "signal_volume_min_adv20_mult",
        "signal_volume_min_adv50_mult",
        "slope_slow_ma_20d_min_pct",
        "slow_ma",
        "sma150_gt_sma200",
        "sma150_slope_30d_min_pct",
        "spy_3d_or_5d_down_required",
        "support_reference",
        "symbol_5d_minus_spy_5d_min_pct",
        "tight_days",
        "today_range_is_lowest_of_n_days",
        "volume_dryup_max_adv20_mult",
        "volume_dryup_prior_days",
        "volume_max_adv20_mult",
        "volume_on_signal_min_adv20_mult",
    },
    "market_regime_rules": {
        "spy_5d_return_max_pct",
        "spy_5d_return_min_pct",
        "spy_atr20_pct_max",
        "spy_close_gt_ema10_or_ema20",
        "spy_close_gt_ema20",
        "spy_close_gt_sma100",
        "spy_close_gt_sma200",
        "spy_close_gt_sma50",
        "spy_close_reclaims_ema10",
        "spy_distribution_days_20_max",
        "spy_drawdown_from_63d_high_max_pct",
        "spy_drawdown_from_63d_high_min_pct",
        "spy_ema20_gt_sma50",
        "spy_heavy_down_days_10_max",
        "spy_low_5d_below_ema10",
        "spy_max_drawdown_126d_pct",
        "spy_max_drawdown_63d_pct",
        "spy_no_20d_low",
        "spy_no_close_below_sma50_days",
        "spy_return_126d_min_pct",
        "spy_return_20d_min_pct",
        "spy_return_50d_min_pct",
        "spy_sma200_slope_20d_min_pct",
        "spy_sma50_gt_sma200",
    },
    "stock_trend_rules": {
        "atr20_pct_max",
        "close_gt_ema20",
        "close_gt_sma100",
        "close_gt_sma200",
        "close_gt_sma50",
        "close_vs_52w_low_min_pct",
        "close_within_52w_high_pct_max",
        "ema10_gt_ema20",
        "ema20_gt_ema50",
        "ema20_slope_10d_min_pct",
        "ema50_gt_sma100",
        "recent_low_touched_sma50_max_pct",
        "return_126d_min_pct",
        "return_63d_min_pct",
        "sma150_gt_sma200",
        "sma200_slope_20d_min_pct",
        "sma20_gt_sma50",
        "sma50_gt_sma150",
        "sma50_gt_sma200",
        "sma50_slope_20d_min_pct",
    },
    "relative_strength_rules": {
        "if_spy_5d_return_lt_pct",
        "price_not_more_than_pct_above_high_50d",
        "return_126d_minus_spy_126d_min_pct",
        "return_20d_minus_spy_20d_min_pct",
        "return_63d_minus_spy_63d_min_pct",
        "rs_ratio_slope_20d_min_pct",
        "rs_ratio_symbol_spy_gt_sma20",
        "rs_ratio_symbol_spy_gt_sma50",
        "rs_ratio_symbol_spy_within_high_50d_pct",
        "symbol_5d_minus_spy_5d_min_pct",
    },
    "exit_rules": {
        "atr_trailing_len",
        "atr_trailing_mult",
        "exit_if_no_followthrough_days",
        "exit_if_red_volume_spike_gt_adv20",
        "exit_on_close_below",
        "market_exit",
        "max_holding_days",
        "stop_loss_pct",
        "stop_reference",
        "take_profit_pct",
        "trailing_stop_pct",
    },
    "guardrails": {
        "data_scope",
        "do_not_load_or_use_data_on_or_after",
        "execution",
        "locked_start_exclusive",
        "min_market_cap_usd",
        "positioning",
        "train_end",
        "validation_end",
        "validation_start",
    },
}


@dataclass(frozen=True)
class ExternalStrategyCandidate:
    payload: dict[str, Any]
    config: IndicatorConfig
    unsupported_rules: tuple[str, ...]
    approximated_rules: tuple[str, ...]


def _dt(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_convert(None)
    return ts.normalize()


def _prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    if (
        isinstance(frame.index, pd.DatetimeIndex)
        and "date" in frame.columns
        and all(column in frame.columns for column in ("open", "high", "low", "close", "adj_close", "volume"))
        and all(pd.api.types.is_numeric_dtype(frame[column]) for column in ("open", "high", "low", "close", "adj_close", "volume"))
        and frame.index.is_monotonic_increasing
        and getattr(frame.index, "tz", None) is None
    ):
        return frame
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


def _frame_series_cache(frame: pd.DataFrame, namespace: str) -> dict[tuple[Any, ...], pd.Series]:
    cache = frame.attrs.get(namespace)
    if not isinstance(cache, dict):
        cache = {}
        frame.attrs[namespace] = cache
    return cache


@dataclass
class FeatureStore:
    """Per-job feature cache attached to prepared symbol frames."""

    symbol_frames: dict[str, pd.DataFrame]
    benchmark_prices: pd.DataFrame
    seconds_build: float = 0.0
    enabled: bool = True


class SignalPrimitiveStore:
    """Lazy boolean/numeric primitive cache for one prepared symbol frame."""

    def __init__(self, frame: pd.DataFrame, benchmark_prices: pd.DataFrame) -> None:
        self.frame = _prepare_ohlcv(frame)
        self.benchmark = _prepare_ohlcv(benchmark_prices)
        self.close = self.frame["close"] if not self.frame.empty else pd.Series(dtype=float)
        self.high = self.frame["high"] if not self.frame.empty else pd.Series(dtype=float)
        self.low = self.frame["low"] if not self.frame.empty else pd.Series(dtype=float)
        self.volume = self.frame["volume"].fillna(0.0) if not self.frame.empty else pd.Series(dtype=float)
        self.index = self.frame.index
        self.cache = _frame_series_cache(self.frame, "_gtbi_signal_primitive_cache")

    def const(self, value: bool) -> pd.Series:
        return _safe_bool_series(value, self.index)

    def sma(self, window: int) -> pd.Series:
        key = ("sma", int(window))
        if key not in self.cache:
            self.cache[key] = self.close.rolling(int(window), min_periods=int(window)).mean()
        return self.cache[key]

    def ema(self, window: int) -> pd.Series:
        key = ("ema", int(window))
        if key not in self.cache:
            self.cache[key] = self.close.ewm(span=int(window), adjust=False, min_periods=int(window)).mean()
        return self.cache[key]

    def adv(self, window: int, *, min_periods: int | None = None) -> pd.Series:
        key = ("adv", int(window), min_periods)
        if key not in self.cache:
            self.cache[key] = self.volume.rolling(
                int(window),
                min_periods=min_periods or min(int(window), len(self.frame)),
            ).mean()
        return self.cache[key]

    def rolling_high(self, window: int, *, shift: int = 0, min_periods: int | None = None) -> pd.Series:
        key = ("rolling_high", int(window), int(shift), min_periods)
        if key not in self.cache:
            source = self.high.shift(int(shift)) if shift else self.high
            self.cache[key] = source.rolling(
                int(window),
                min_periods=min_periods or min(int(window), len(self.frame)),
            ).max()
        return self.cache[key]

    def rolling_low(self, window: int, *, shift: int = 0, min_periods: int | None = None) -> pd.Series:
        key = ("rolling_low", int(window), int(shift), min_periods)
        if key not in self.cache:
            source = self.low.shift(int(shift)) if shift else self.low
            self.cache[key] = source.rolling(
                int(window),
                min_periods=min_periods or min(int(window), len(self.frame)),
            ).min()
        return self.cache[key]

    def rsi(self, period: int) -> pd.Series:
        key = ("rsi", int(period))
        if key not in self.cache:
            self.cache[key] = _rsi(self.close, int(period)).fillna(50.0)
        return self.cache[key]

    def close_gt_ema(self, window: int) -> pd.Series:
        key = ("close_gt_ema", int(window))
        if key not in self.cache:
            self.cache[key] = self.close > self.ema(int(window))
        return self.cache[key]

    def ema_gt_ema(self, fast: int, slow: int) -> pd.Series:
        key = ("ema_gt_ema", int(fast), int(slow))
        if key not in self.cache:
            self.cache[key] = self.ema(int(fast)) > self.ema(int(slow))
        return self.cache[key]

    def close_breaks_high(self, window: int) -> pd.Series:
        key = ("close_breaks_high", int(window))
        if key not in self.cache:
            self.cache[key] = self.close > self.rolling_high(int(window), shift=1, min_periods=int(window))
        return self.cache[key]

    def volume_gt_adv(self, window: int, multiple: float) -> pd.Series:
        key = ("volume_gt_adv", int(window), round(float(multiple), 8))
        if key not in self.cache:
            self.cache[key] = self.volume > self.adv(int(window)) * float(multiple)
        return self.cache[key]

    def rs_ratio_gt_ma(self, window: int) -> pd.Series:
        key = ("rs_ratio_gt_ma", int(window), id(self.benchmark), len(self.benchmark))
        if key not in self.cache:
            if self.benchmark.empty:
                self.cache[key] = self.const(True)
            else:
                spy_close = self.benchmark["close"].reindex(self.index).ffill()
                rs_line = self.close / spy_close.replace(0.0, np.nan)
                rs_avg = rs_line.rolling(int(window), min_periods=min(int(window), len(self.frame))).mean()
                self.cache[key] = rs_line > rs_avg
        return self.cache[key]


def _prewarm_common_features(frame: pd.DataFrame, benchmark_prices: pd.DataFrame) -> None:
    prepared = _prepare_ohlcv(frame)
    if prepared.empty:
        return
    close = prepared["close"]
    high = prepared["high"]
    low = prepared["low"]
    volume = prepared["volume"].fillna(0.0)
    entry_cache = _frame_series_cache(prepared, "_gtbi_entry_signal_series_cache")
    exit_cache = _frame_series_cache(prepared, "_gtbi_exit_series_cache")

    for window in (10, 20, 21, 50, 63, 80, 100, 126, 150, 180, 200, 220, 252):
        if window <= 0:
            continue
        entry_cache.setdefault(("sma", window), close.rolling(window, min_periods=window).mean())
        entry_cache.setdefault(("ema", window), close.ewm(span=window, adjust=False, min_periods=window).mean())
        min_periods = min(window, len(prepared))
        entry_cache.setdefault((f"high_0_{min_periods}", window), high.rolling(window, min_periods=min_periods).max())
        entry_cache.setdefault((f"low_0_{min_periods}", window), low.rolling(window, min_periods=min_periods).min())
        entry_cache.setdefault((f"vol_{min_periods}", window), volume.rolling(window, min_periods=min_periods).mean())
    for window in (10, 20, 21, 35, 50, 60):
        exit_cache.setdefault(("exit_ma", window), close.rolling(window, min_periods=window).mean())

    if not benchmark_prices.empty:
        benchmark = _prepare_ohlcv(benchmark_prices)
        spy_close = benchmark["close"].reindex(prepared.index).ffill()
        entry_cache.setdefault(("spy_close", id(benchmark), len(benchmark)), spy_close)


def build_feature_store(
    symbol_frames: dict[str, pd.DataFrame],
    benchmark_prices: pd.DataFrame,
    *,
    enabled: bool = True,
    prewarm: bool = True,
) -> FeatureStore:
    start = time.perf_counter()
    if enabled and prewarm:
        for frame in symbol_frames.values():
            _prewarm_common_features(frame, benchmark_prices)
    return FeatureStore(
        symbol_frames=symbol_frames,
        benchmark_prices=benchmark_prices,
        seconds_build=float(time.perf_counter() - start),
        enabled=bool(enabled),
    )


def _families_for_set(family_set: str) -> tuple[str, ...]:
    if family_set == "default":
        return DEFAULT_FAMILIES
    if family_set == "tradingview_minervini":
        return TRADINGVIEW_MINERVINI_FAMILIES
    if family_set == "stability":
        return STABILITY_FAMILIES
    if family_set == "stability_rs":
        return STABILITY_RS_FAMILIES
    if family_set == "all":
        return ALL_FAMILIES
    raise ValueError(f"unknown family_set {family_set!r}; expected one of {FAMILY_SETS}")


def _market_trend_ok(index: pd.Index, benchmark_prices: pd.DataFrame, config: IndicatorConfig) -> pd.Series:
    benchmark = _prepare_ohlcv(benchmark_prices)
    if benchmark.empty:
        return _safe_bool_series(True, index)
    spy_close = benchmark["close"].reindex(index).ffill()
    market_ma = spy_close.rolling(config.market_ma_days, min_periods=min(config.market_ma_days, len(spy_close))).mean()
    base = (spy_close > market_ma) & (spy_close > spy_close.shift(config.market_momentum_days))
    if not config.strict_market_filter:
        return base.fillna(False)
    short_window = max(20, min(50, int(config.market_ma_days // 2)))
    market_short = spy_close.rolling(short_window, min_periods=min(short_window, len(spy_close))).mean()
    regime_window = max(150, int(config.market_ma_days))
    market_regime = spy_close.rolling(regime_window, min_periods=min(regime_window, len(spy_close))).mean()
    recent_high = spy_close.rolling(63, min_periods=min(63, len(spy_close))).max()
    strict = (
        base
        & (spy_close > market_short)
        & (spy_close > market_regime)
        & (market_short > market_ma)
        & (market_ma > market_ma.shift(21))
        & (market_regime >= market_regime.shift(21))
        & (spy_close.pct_change(10) > -0.015)
        & (spy_close >= recent_high * 0.94)
    )
    return strict.fillna(False)


def _market_trend_ok_for_frame(frame: pd.DataFrame, benchmark_prices: pd.DataFrame, config: IndicatorConfig) -> pd.Series:
    prepared = _prepare_ohlcv(frame)
    if prepared.empty:
        return pd.Series(dtype=bool)
    benchmark = _prepare_ohlcv(benchmark_prices)
    key = (
        "market_trend",
        id(benchmark),
        len(benchmark),
        int(config.market_ma_days),
        int(config.market_momentum_days),
        bool(config.strict_market_filter),
    )
    cache = _frame_series_cache(prepared, "_gtbi_market_trend_cache")
    if key not in cache:
        cache[key] = _market_trend_ok(prepared.index, benchmark, config)
    return cache[key]


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
        spy_close = pd.Series(np.nan, index=index)
    if not config.require_rs:
        rs_ok = _safe_bool_series(True, index)
    if config.require_market_trend:
        market_trend = _market_trend_ok(index, benchmark_prices, config)
    else:
        market_trend = _safe_bool_series(True, index)

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
    stock_uptrend = (close > sma_long) & (sma_short > sma_long) & (sma_long >= sma_long.shift(21))
    soft_rs_ok = rs_ok if config.require_rs else _safe_bool_series(True, index)
    pullback_touch = (low <= sma_short) | (low <= ma21_sma) | (close <= ma21_sma)
    rsi_cap = max(35.0, min(70.0, float(config.rsi_max)))
    soft_rsi_rebound = (
        (rsi_line.shift(1) <= rsi_cap)
        & (rsi_line > rsi_line.shift(1))
        & (close > close.shift(1))
    )
    trend_reclaim = (
        stock_uptrend
        & ((close.shift(1) < ma10_sma.shift(1)) | (close.shift(1) < ma21_sma.shift(1)) | pullback_touch.shift(1))
        & (close > ma10_sma)
        & (close > ma21_sma)
        & (rsi_line <= max(rsi_cap, 55.0))
    )
    market_dip = (
        stock_uptrend
        & (rsi_line.shift(1) <= max(30.0, min(rsi_cap, 55.0)))
        & (rsi_line > rsi_line.shift(1))
        & (close > close.shift(1))
        & (close >= low_n * max(config.above_low_multiple, 1.05))
    )
    long_momentum = (close / close.shift(config.prior_runup_lookback) - 1.0) >= max(
        config.prior_runup_min_pct,
        0.08,
    )
    rs_momentum_pullback = (
        stock_uptrend
        & rs_ok
        & long_momentum
        & (close >= high_n * max(config.near_high_pct, 0.70))
        & (close <= high_n * 0.98)
        & pullback_touch.shift(1).fillna(False)
        & (close > ma10_sma)
        & (close > close.shift(1))
        & (rsi_line <= max(rsi_cap, 60.0))
    )
    if not benchmark.empty:
        rs_line_for_reclaim = close / spy_close.replace(0.0, np.nan)
        rs_avg_for_reclaim = rs_line_for_reclaim.rolling(
            config.rs_lookback,
            min_periods=min(config.rs_lookback, len(frame)),
        ).mean()
        rs_reclaim_ok = (
            (rs_line_for_reclaim > rs_avg_for_reclaim)
            & (rs_line_for_reclaim > rs_line_for_reclaim.shift(max(5, min(config.rs_lookback // 4, 21))))
        )
    else:
        rs_reclaim_ok = _safe_bool_series(True, index)
    frequent_runup = (close / close.shift(config.prior_runup_lookback) - 1.0) >= max(
        min(config.prior_runup_min_pct, 0.10),
        0.03,
    )
    frequent_reclaim = (
        stock_uptrend
        & rs_reclaim_ok
        & frequent_runup
        & (close >= high_n * max(config.near_high_pct, 0.50))
        & (close <= high_n * 1.01)
        & (pullback_touch.shift(1).fillna(False) | (close.shift(1) < ma10_sma.shift(1)) | (rsi_line.shift(1) <= rsi_cap))
        & (close > ma10_sma)
        & (close > close.shift(1))
        & (rsi_line <= max(rsi_cap, 68.0))
    )
    short_high = high.shift(1).rolling(max(5, min(config.breakout_lookback, 21)), min_periods=5).max()
    short_range = (
        high.rolling(max(5, min(config.base_lookback, 21)), min_periods=5).max()
        - low.rolling(max(5, min(config.base_lookback, 21)), min_periods=5).min()
    ) / close.replace(0.0, np.nan)
    controlled_pullback = (
        (low.shift(1) <= ma21_sma.shift(1))
        | (close.shift(1) <= ma21_sma.shift(1))
        | (short_range.shift(1) <= max(config.max_base_range_pct, 0.08))
    )
    reclaim_or_breakout = (
        ((close > ma10_sma) & (close.shift(1) <= ma10_sma.shift(1)))
        | ((close > ma21_sma) & (close.shift(1) <= ma21_sma.shift(1)))
        | (close > short_high)
    )
    rs_pullback_breakout = (
        stock_uptrend
        & rs_reclaim_ok
        & frequent_runup
        & controlled_pullback.fillna(False)
        & reclaim_or_breakout.fillna(False)
        & (close >= high_n * max(config.near_high_pct, 0.55))
        & (close <= high_n * 1.02)
        & (volume >= avg_vol * max(config.volume_multiple, 0.95))
        & (rsi_line <= max(rsi_cap, 72.0))
    )

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
    elif config.family == "stability_pullback_rebound":
        signal = stock_uptrend & soft_rs_ok & pullback_touch.shift(1).fillna(False) & soft_rsi_rebound
    elif config.family == "stability_trend_reclaim":
        signal = trend_reclaim & soft_rs_ok
    elif config.family == "stability_market_dip":
        signal = market_dip & soft_rs_ok
    elif config.family == "stability_rs_momentum_pullback":
        signal = rs_momentum_pullback
    elif config.family == "stability_rs_reclaim_frequent":
        signal = frequent_reclaim
    elif config.family == "stability_rs_pullback_breakout":
        signal = rs_pullback_breakout
    else:
        signal = trend_ok & rs_ok & breakout & pocket_pivot & rsi_ok
    return (signal & market_trend).fillna(False).astype(bool)


def _entry_signal_optimized(prices: pd.DataFrame, benchmark_prices: pd.DataFrame, config: IndicatorConfig) -> pd.Series:
    """Return same-day buy indicator with lazy per-family feature calculation."""

    frame = _prepare_ohlcv(prices)
    if frame.empty:
        return pd.Series(dtype=bool)
    benchmark = _prepare_ohlcv(benchmark_prices)
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"].fillna(0.0)
    index = frame.index
    cache = _frame_series_cache(frame, "_gtbi_entry_signal_series_cache")
    primitives = SignalPrimitiveStore(frame, benchmark)

    def const(value: bool) -> pd.Series:
        return primitives.const(value)

    def sma(window: int) -> pd.Series:
        key = ("sma", int(window))
        if key not in cache:
            cache[key] = primitives.sma(int(window))
        return cache[key]

    def ema(window: int) -> pd.Series:
        key = ("ema", int(window))
        if key not in cache:
            cache[key] = primitives.ema(int(window))
        return cache[key]

    def high_roll(window: int, *, shift: int = 0, min_periods: int | None = None) -> pd.Series:
        key = (f"high_{shift}_{min_periods}", int(window))
        if key not in cache:
            cache[key] = primitives.rolling_high(int(window), shift=shift, min_periods=min_periods)
        return cache[key]

    def low_roll(window: int, *, shift: int = 0, min_periods: int | None = None) -> pd.Series:
        key = (f"low_{shift}_{min_periods}", int(window))
        if key not in cache:
            cache[key] = primitives.rolling_low(int(window), shift=shift, min_periods=min_periods)
        return cache[key]

    def avg_volume(window: int, *, min_periods: int | None = None) -> pd.Series:
        key = (f"vol_{min_periods}", int(window))
        if key not in cache:
            cache[key] = primitives.adv(int(window), min_periods=min_periods)
        return cache[key]

    def rsi_line() -> pd.Series:
        key = ("rsi", int(config.rsi_period))
        if key not in cache:
            cache[key] = primitives.rsi(config.rsi_period)
        return cache[key]

    def high_n() -> pd.Series:
        return high_roll(config.high_lookback, min_periods=min(config.high_lookback, len(frame)))

    def low_n() -> pd.Series:
        return low_roll(config.low_lookback, min_periods=min(config.low_lookback, len(frame)))

    def rsi_ok() -> pd.Series:
        return rsi_line() <= config.rsi_max

    def spy_close() -> pd.Series:
        key = ("spy_close", id(benchmark), len(benchmark))
        if key not in cache:
            cache[key] = benchmark["close"].reindex(index).ffill() if not benchmark.empty else pd.Series(np.nan, index=index)
        return cache[key]

    def rs_ok() -> pd.Series:
        if not config.require_rs:
            return const(True)
        if benchmark.empty:
            return const(True)
        rs_line = close / spy_close().replace(0.0, np.nan)
        rs_avg = rs_line.rolling(config.rs_lookback, min_periods=min(config.rs_lookback, len(frame))).mean()
        rs_high = rs_line.rolling(config.rs_lookback, min_periods=min(config.rs_lookback, len(frame))).max()
        return (rs_line > rs_avg) & (rs_line >= rs_high * config.rs_near_high_pct)

    def market_trend() -> pd.Series:
        return _market_trend_ok_for_frame(frame, benchmark, config) if config.require_market_trend else const(True)

    def trend_ok() -> pd.Series:
        if not config.minervini_trend:
            return const(True)
        short = sma(config.ma_short)
        mid = sma(config.ma_mid)
        long = sma(config.ma_long)
        return (
            (close > short)
            & (close > mid)
            & (close > long)
            & (short > mid)
            & (mid > long)
            & (long > long.shift(21))
            & (close >= high_n() * config.near_high_pct)
            & (close >= low_n() * config.above_low_multiple)
        )

    def base_tight() -> pd.Series:
        if not config.require_base_tight:
            return const(True)
        base_range = (
            high_roll(config.base_lookback, min_periods=config.base_lookback)
            - low_roll(config.base_lookback, min_periods=config.base_lookback)
        )
        return (base_range / close) <= config.max_base_range_pct

    def breakout() -> pd.Series:
        if not config.require_breakout:
            return const(True)
        resistance = high.shift(1).rolling(config.breakout_lookback, min_periods=config.breakout_lookback).max()
        return (close > resistance) & (volume > avg_volume(config.volume_lookback) * config.volume_multiple) & base_tight()

    def prior_runup() -> pd.Series:
        return const(True) if not config.require_prior_runup else (close / close.shift(config.prior_runup_lookback) - 1.0) >= config.prior_runup_min_pct

    def dryup() -> pd.Series:
        if not config.require_volume_dryup:
            return const(True)
        recent_vol = avg_volume(config.volume_dryup_lookback, min_periods=config.volume_dryup_lookback)
        long_vol = avg_volume(config.volume_lookback)
        return recent_vol <= long_vol * config.volume_dryup_max_ratio

    def adr_ok() -> pd.Series:
        adr = close.pct_change().abs().rolling(config.adr_lookback, min_periods=config.adr_lookback).mean()
        return adr >= config.min_adr_pct

    def episodic_gap() -> pd.Series:
        if not config.require_episodic_gap:
            return const(True)
        gap = (frame["open"] / close.shift(1) - 1.0) >= config.episodic_gap_pct
        return gap & (volume > avg_volume(config.volume_lookback) * max(config.volume_multiple, 1.5))

    def pocket_pivot() -> pd.Series:
        if not config.require_pocket_pivot:
            return const(True)
        down_vol = volume.where(close < close.shift(1), 0.0)
        max_down_vol = down_vol.shift(1).rolling(10, min_periods=10).max()
        return (close > close.shift(1)) & (volume > max_down_vol) & (close > sma(config.ma_short)) & (close > sma(config.ma_long))

    def oneil_stack() -> pd.Series:
        if not config.require_oneil_stack:
            return const(True)
        ma10 = sma(config.oneil_fast_ma)
        ma21 = ema(config.oneil_mid_ma)
        return (close > ma10) & (ma10 > ma21) & (ma21 > sma(config.ma_short)) & (sma(config.ma_short) > sma(config.ma_long))

    def ema_trend_ok() -> pd.Series:
        short = ema(config.ma_short)
        mid = ema(config.ma_mid)
        long = ema(config.ma_long)
        return (
            (close > short)
            & (close > mid)
            & (close > long)
            & (short > mid)
            & (mid > long)
            & (long > long.shift(21))
            & (close >= high_n() * config.near_high_pct)
            & (close >= low_n() * config.above_low_multiple)
        )

    def sma50() -> pd.Series:
        return sma(50)

    def sma150() -> pd.Series:
        return sma(150)

    def sma200() -> pd.Series:
        return sma(200)

    def ma10_sma() -> pd.Series:
        return sma(10)

    def ma21_sma() -> pd.Series:
        return sma(21)

    def stock_uptrend() -> pd.Series:
        long = sma(config.ma_long)
        short = sma(config.ma_short)
        return (close > long) & (short > long) & (long >= long.shift(21))

    family = config.family
    if family == "oneil_canslim":
        signal = oneil_stack() & rs_ok() & breakout() & rsi_ok()
    elif family == "quallamaggie":
        signal = (trend_ok() | (close > sma(config.ma_short))) & prior_runup() & dryup() & (breakout() | episodic_gap()) & adr_ok() & rsi_ok()
    elif family == "tv_minervini_qualifier":
        signal = trend_ok() & rs_ok() & (close > sma(20)) & rsi_ok()
    elif family == "tv_minervini_trend_template_ema":
        signal = ema_trend_ok() & (breakout() if config.require_breakout else const(True)) & rsi_ok()
    elif family == "tv_minervini_trend_template_sepa_pro":
        signal = ema_trend_ok() & rs_ok() & (base_tight() | dryup()) & (breakout() | episodic_gap()) & rsi_ok()
    elif family == "tv_pocket_pivot_breakout":
        down_vol = volume.where(close < close.shift(1), 0.0)
        max_down_vol = down_vol.shift(1).rolling(10, min_periods=10).max()
        pocket_pivot_3pct = (
            ((close / frame["open"].replace(0.0, np.nan) - 1.0) >= 0.03)
            & (volume > max_down_vol)
            & (close > ema(config.ma_short))
            & (close > ema(config.ma_long))
        )
        signal = ema_trend_ok() & (pocket_pivot() | pocket_pivot_3pct) & rsi_ok()
    elif family == "tv_5ma_oneil_minervini":
        oneil_buy = (
            (close > sma50())
            & (close > sma200())
            & (sma50() > sma50().shift(20))
            & (sma200() > sma200().shift(20))
            & (close >= high_n() * max(config.near_high_pct, 0.85))
        )
        minervini_5ma_buy = (
            (ma10_sma() > ma21_sma())
            & (ma21_sma() > sma50())
            & (ma10_sma() > ma10_sma().shift(5))
            & (ma21_sma() > ma21_sma().shift(5))
            & (close >= high_n() * max(config.near_high_pct, 0.75))
            & (close >= low_n() * max(config.above_low_multiple, 1.25))
        )
        signal = ((oneil_buy & minervini_5ma_buy) | (breakout() if config.require_breakout else const(False))) & rsi_ok()
    elif family == "tv_minervini_mtc":
        mtc_ok = (
            (close > sma50())
            & (close > sma150())
            & (close > sma200())
            & (sma50() > sma150())
            & (sma150() > sma200())
            & (sma200() > sma200().shift(21))
            & (close >= low_n() * config.above_low_multiple)
            & (close >= high_n() * config.near_high_pct)
        )
        signal = mtc_ok & rsi_ok()
    elif family == "tv_weinstein_stage":
        stage2 = (close > sma150()) & (sma150() > sma150().shift(20)) & (sma50() > sma150())
        stage2_minervini = stage2 & (close > sma50()) & (sma50() > sma150()) & (sma150() > sma200()) & (sma200() > sma200().shift(21))
        signal = (stage2_minervini if config.minervini_trend else stage2) & rsi_ok()
    elif family == "tv_breakout_finder":
        short_high = high.shift(1).rolling(config.breakout_lookback, min_periods=config.breakout_lookback).max()
        short_low = low.shift(1).rolling(config.breakout_lookback, min_periods=config.breakout_lookback).min()
        channel_width = ((short_high - short_low) / close).fillna(np.inf)
        tests = (high.shift(1) >= short_high * (1.0 - max(config.max_base_range_pct, 0.02))).rolling(
            config.base_lookback,
            min_periods=max(2, min(config.base_lookback, 5)),
        ).sum()
        signal = (
            (close > short_high)
            & (tests >= 2)
            & (channel_width <= max(config.max_base_range_pct, 0.02))
            & (volume >= avg_volume(config.volume_lookback) * max(config.volume_multiple, 1.0))
            & rsi_ok()
        )
    elif family == "tv_rsi_strategy":
        oversold_level = max(15.0, min(45.0, 100.0 - float(config.rsi_max)))
        signal = (rsi_line().shift(1) <= oversold_level) & (rsi_line() > oversold_level) & (close > sma(config.ma_long))
    elif family == "stability_pullback_rebound":
        pullback_touch = (low <= sma(config.ma_short)) | (low <= ma21_sma()) | (close <= ma21_sma())
        rsi_cap = max(35.0, min(70.0, float(config.rsi_max)))
        soft_rsi_rebound = (rsi_line().shift(1) <= rsi_cap) & (rsi_line() > rsi_line().shift(1)) & (close > close.shift(1))
        signal = stock_uptrend() & (rs_ok() if config.require_rs else const(True)) & pullback_touch.shift(1).fillna(False) & soft_rsi_rebound
    elif family == "stability_trend_reclaim":
        pullback_touch = (low <= sma(config.ma_short)) | (low <= ma21_sma()) | (close <= ma21_sma())
        rsi_cap = max(35.0, min(70.0, float(config.rsi_max)))
        trend_reclaim = (
            stock_uptrend()
            & ((close.shift(1) < ma10_sma().shift(1)) | (close.shift(1) < ma21_sma().shift(1)) | pullback_touch.shift(1))
            & (close > ma10_sma())
            & (close > ma21_sma())
            & (rsi_line() <= max(rsi_cap, 55.0))
        )
        signal = trend_reclaim & (rs_ok() if config.require_rs else const(True))
    elif family == "stability_market_dip":
        rsi_cap = max(35.0, min(70.0, float(config.rsi_max)))
        market_dip = (
            stock_uptrend()
            & (rsi_line().shift(1) <= max(30.0, min(rsi_cap, 55.0)))
            & (rsi_line() > rsi_line().shift(1))
            & (close > close.shift(1))
            & (close >= low_n() * max(config.above_low_multiple, 1.05))
        )
        signal = market_dip & (rs_ok() if config.require_rs else const(True))
    elif family in {"stability_rs_momentum_pullback", "stability_rs_reclaim_frequent", "stability_rs_pullback_breakout"}:
        if not benchmark.empty:
            rs_line_for_reclaim = close / spy_close().replace(0.0, np.nan)
            rs_avg_for_reclaim = rs_line_for_reclaim.rolling(
                config.rs_lookback,
                min_periods=min(config.rs_lookback, len(frame)),
            ).mean()
            rs_reclaim_ok = (
                (rs_line_for_reclaim > rs_avg_for_reclaim)
                & (rs_line_for_reclaim > rs_line_for_reclaim.shift(max(5, min(config.rs_lookback // 4, 21))))
            )
        else:
            rs_reclaim_ok = const(True)
        pullback_touch = (low <= sma(config.ma_short)) | (low <= ma21_sma()) | (close <= ma21_sma())
        rsi_cap = max(35.0, min(70.0, float(config.rsi_max)))
        long_momentum = (close / close.shift(config.prior_runup_lookback) - 1.0) >= max(config.prior_runup_min_pct, 0.08)
        frequent_runup = (close / close.shift(config.prior_runup_lookback) - 1.0) >= max(min(config.prior_runup_min_pct, 0.10), 0.03)
        if family == "stability_rs_momentum_pullback":
            signal = (
                stock_uptrend()
                & rs_ok()
                & long_momentum
                & (close >= high_n() * max(config.near_high_pct, 0.70))
                & (close <= high_n() * 0.98)
                & pullback_touch.shift(1).fillna(False)
                & (close > ma10_sma())
                & (close > close.shift(1))
                & (rsi_line() <= max(rsi_cap, 60.0))
            )
        elif family == "stability_rs_reclaim_frequent":
            signal = (
                stock_uptrend()
                & rs_reclaim_ok
                & frequent_runup
                & (close >= high_n() * max(config.near_high_pct, 0.50))
                & (close <= high_n() * 1.01)
                & (pullback_touch.shift(1).fillna(False) | (close.shift(1) < ma10_sma().shift(1)) | (rsi_line().shift(1) <= rsi_cap))
                & (close > ma10_sma())
                & (close > close.shift(1))
                & (rsi_line() <= max(rsi_cap, 68.0))
            )
        else:
            short_high = high.shift(1).rolling(max(5, min(config.breakout_lookback, 21)), min_periods=5).max()
            short_range = (
                high.rolling(max(5, min(config.base_lookback, 21)), min_periods=5).max()
                - low.rolling(max(5, min(config.base_lookback, 21)), min_periods=5).min()
            ) / close.replace(0.0, np.nan)
            controlled_pullback = (
                (low.shift(1) <= ma21_sma().shift(1))
                | (close.shift(1) <= ma21_sma().shift(1))
                | (short_range.shift(1) <= max(config.max_base_range_pct, 0.08))
            )
            reclaim_or_breakout = (
                ((close > ma10_sma()) & (close.shift(1) <= ma10_sma().shift(1)))
                | ((close > ma21_sma()) & (close.shift(1) <= ma21_sma().shift(1)))
                | (close > short_high)
            )
            signal = (
                stock_uptrend()
                & rs_reclaim_ok
                & frequent_runup
                & controlled_pullback.fillna(False)
                & reclaim_or_breakout.fillna(False)
                & (close >= high_n() * max(config.near_high_pct, 0.55))
                & (close <= high_n() * 1.02)
                & (volume >= avg_volume(config.volume_lookback) * max(config.volume_multiple, 0.95))
                & (rsi_line() <= max(rsi_cap, 72.0))
            )
    else:
        signal = trend_ok() & rs_ok() & breakout() & pocket_pivot() & rsi_ok()
    signal = signal.fillna(False).astype(bool)
    if not bool(signal.any()):
        return signal
    return (signal & market_trend()).fillna(False).astype(bool)


entry_signal = _entry_signal_optimized


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
    exit_signal: pd.Series | None = None,
) -> pd.DataFrame:
    """Simulate long/cash trades from a buy indicator, executing next session."""

    frame = _prepare_ohlcv(prices)
    if frame.empty or len(frame) < 3:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    signal = signal.reindex(frame.index).fillna(False).astype(bool)
    exit_signal = (
        exit_signal.reindex(frame.index).fillna(False).astype(bool)
        if exit_signal is not None
        else _safe_bool_series(False, frame.index)
    )
    exit_ma_key = ("exit_ma", int(config.exit_ma_days))
    exit_ma_cache = _frame_series_cache(frame, "_gtbi_exit_series_cache")
    if exit_ma_key not in exit_ma_cache:
        exit_ma_cache[exit_ma_key] = frame["close"].rolling(config.exit_ma_days, min_periods=config.exit_ma_days).mean()
    exit_ma = exit_ma_cache[exit_ma_key]
    signal_values = signal.to_numpy(dtype=bool)
    signal_positions = np.flatnonzero(signal_values[:-1])
    if len(signal_positions) == 0:
        return pd.DataFrame(columns=TRADE_COLUMNS)

    trades: list[dict[str, Any]] = []
    in_position = False
    entry_idx = -1
    entry_price = 0.0
    high_water = 0.0
    i = 0
    next_signal = 0
    while i < len(frame) - 1:
        if not in_position:
            while next_signal < len(signal_positions) and int(signal_positions[next_signal]) < i:
                next_signal += 1
            if next_signal >= len(signal_positions):
                break
            i = int(signal_positions[next_signal])
            next_signal += 1
            entry_idx = i + 1
            entry_price = _open_or_close(frame, entry_idx)
            high_water = float(frame["high"].iloc[entry_idx])
            in_position = True
            i = entry_idx
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
        elif config.use_market_exit and bool(exit_signal.iloc[i]):
            reason = "market_exit"
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
    gross = np.maximum(1.0 + returns.to_numpy(dtype=float), 1e-12)
    log_nav = np.cumsum(np.log(gross))
    log_dd = log_nav - np.maximum.accumulate(log_nav)
    dd = np.exp(np.clip(log_dd, -745.0, 0.0)) - 1.0
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


def _external_pct(value: Any, default: float = 0.0) -> float:
    out = _finite_float(value, default=default)
    if not math.isfinite(out):
        return default
    return out / 100.0 if abs(out) > 1.0 else out


def _external_int(value: Any, default: int, *, low: int, high: int) -> int:
    out = _finite_float(value, default=float(default))
    if not math.isfinite(out):
        out = float(default)
    return int(np.clip(round(out), low, high))


def _ma_days(value: Any, default: int) -> int:
    text = str(value or "").lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else int(default)


def _external_strategy_files(pack_path: Path, shard_id: int | None, strategy_format: str) -> list[Path]:
    pack_path = Path(pack_path)
    fmt = strategy_format.lower()
    if fmt not in {"auto", "jsonl", "csv"}:
        raise ValueError("external_strategy_format must be auto, jsonl, or csv")
    if pack_path.is_file():
        return [pack_path]
    if not pack_path.exists():
        raise FileNotFoundError(f"external strategy pack path not found: {pack_path}")
    if shard_id is not None:
        shard_path = pack_path / "shards" / f"shard_{int(shard_id):03d}.jsonl"
        if shard_path.exists():
            return [shard_path]
        raise FileNotFoundError(f"external strategy shard not found: {shard_path}")
    shards = sorted((pack_path / "shards").glob("shard_*.jsonl"))
    if shards:
        return shards
    if fmt in {"auto", "jsonl"}:
        jsonl = pack_path / "aurora_gtbi_research_broad_strategies_72000.jsonl"
        if jsonl.exists():
            return [jsonl]
    if fmt in {"auto", "csv"}:
        csv_path = pack_path / "aurora_gtbi_research_broad_strategies_72000.csv"
        if csv_path.exists():
            return [csv_path]
    raise FileNotFoundError(f"no external strategy files found under {pack_path}")


def _decode_external_csv_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _iter_external_strategy_payloads(path: Path) -> Iterable[dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                yield {key: _decode_external_csv_value(value) for key, value in row.items()}
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _external_unknown_rules(payload: dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    missing = [field for field in EXTERNAL_REQUIRED_FIELDS if field not in payload]
    unknown.extend(f"missing_required.{field}" for field in missing)
    for section, supported in EXTERNAL_SUPPORTED_RULE_KEYS.items():
        rules = payload.get(section) or {}
        if not isinstance(rules, dict):
            unknown.append(f"{section}.__not_object__")
            continue
        for key in rules:
            if key not in supported:
                unknown.append(f"{section}.{key}")
    return unknown


def _family_for_external_strategy(payload: dict[str, Any]) -> str:
    concept = str(payload.get("concept_id", "")).lower()
    if any(token in concept for token in ("breakout", "vcp", "squeeze", "inside", "stair_step")):
        return "quallamaggie"
    if any(token in concept for token in ("rsi", "pullback", "reclaim", "shakeout", "failed_breakdown", "keltner")):
        return "oneil_canslim"
    if any(token in concept for token in ("trend", "moving_average", "stage2", "52w", "momentum")):
        return "minervini_sepa"
    return "quallamaggie"


def external_strategy_to_config(payload: dict[str, Any]) -> ExternalStrategyCandidate:
    unknown = _external_unknown_rules(payload)
    entry = payload.get("entry_rules") or {}
    market = payload.get("market_regime_rules") or {}
    stock = payload.get("stock_trend_rules") or {}
    rs_rules = payload.get("relative_strength_rules") or {}
    exit_rules = payload.get("exit_rules") or {}
    concept = str(payload.get("concept_id", "")).lower()
    trend = str(payload.get("trend_profile_id", "")).lower()
    exit_profile = str(payload.get("exit_profile_id", "")).lower()

    breakout_lookback = _external_int(
        entry.get("breakout_lookback_days")
        or entry.get("close_breaks_above_high_n")
        or entry.get("nr_days_lookback")
        or entry.get("inside_days_max")
        or entry.get("tight_days")
        or 20,
        20,
        low=5,
        high=126,
    )
    base_lookback = _external_int(
        entry.get("base_length_days_min")
        or entry.get("pullback_days_min")
        or entry.get("volume_dryup_prior_days")
        or entry.get("handle_length_days_min")
        or 10,
        10,
        low=3,
        high=80,
    )
    volume_multiple = _finite_float(
        entry.get("volume_on_signal_min_adv20_mult")
        or entry.get("signal_volume_min_adv20_mult")
        or entry.get("signal_volume_min_adv50_mult")
        or entry.get("recent_gap_volume_min_adv20_mult")
        or 1.15,
        default=1.15,
    )
    max_base_range_pct = max(
        _external_pct(entry.get("range_20d_pct_max"), default=0.0),
        _external_pct(entry.get("base_depth_pct_max"), default=0.0),
        _external_pct(entry.get("handle_depth_pct_max"), default=0.0),
        _external_pct(entry.get("pullback_from_recent_high_max_pct"), default=0.0),
        _external_pct(entry.get("pullback_from_52w_high_max_pct"), default=0.0),
        0.08,
    )
    near_high_pct = 1.0 - max(
        _external_pct(entry.get("price_within_52w_high_pct_max"), default=0.0),
        _external_pct(entry.get("close_within_52w_high_pct_max"), default=0.0),
        _external_pct(stock.get("close_within_52w_high_pct_max"), default=0.0),
        0.10,
    )
    above_low_multiple = 1.0 + max(_external_pct(stock.get("close_vs_52w_low_min_pct"), default=0.0), 0.05)
    prior_runup_lookback = _external_int(
        entry.get("prior_runup_lookback_days") or entry.get("prior_return_63d_min_pct") and 63 or 63,
        63,
        low=10,
        high=126,
    )
    prior_runup_min_pct = max(
        _external_pct(entry.get("prior_runup_min_pct"), default=0.0),
        _external_pct(entry.get("prior_uptrend_min_pct"), default=0.0),
        _external_pct(entry.get("return_63d_min_pct"), default=0.0),
        _external_pct(stock.get("return_63d_min_pct"), default=0.0),
        0.03,
    )
    exit_ma_days = _ma_days(exit_rules.get("exit_on_close_below"), 20)
    market_exit = str(exit_rules.get("market_exit", ""))
    market_ma_days = _ma_days(market_exit, 100)
    if market.get("spy_close_gt_sma200") or market.get("spy_sma50_gt_sma200"):
        market_ma_days = max(market_ma_days, 200)
    elif market.get("spy_close_gt_sma100"):
        market_ma_days = max(market_ma_days, 100)
    elif market.get("spy_close_gt_sma50") or market.get("spy_ema20_gt_sma50"):
        market_ma_days = max(market_ma_days, 50)
    ma_short = 20 if ("ema" in trend or "ema" in str(entry.get("close_above", "")).lower()) else 50
    if "ema10" in str(entry.get("close_above", "")).lower():
        ma_short = 10
    ma_mid = 100 if stock.get("close_gt_sma100") or stock.get("ema50_gt_sma100") else 150
    ma_long = 200 if stock.get("close_gt_sma200") or stock.get("sma50_gt_sma200") else 150

    config = IndicatorConfig(
        family=_family_for_external_strategy(payload),
        minervini_trend=bool("stage2" in trend or "minervini" in concept or stock),
        require_rs=bool(rs_rules),
        require_base_tight=bool(
            any(key in entry for key in ("base_depth_pct_max", "range_20d_pct_max", "max_close_to_close_range_pct"))
        ),
        require_breakout=bool(
            "breakout" in concept
            or any(key in entry for key in ("entry_trigger", "close_breaks_above_high_n", "close_above_upper_band"))
        ),
        require_pocket_pivot=bool("pocket_pivot" in concept or entry.get("signal_volume_gt_max_down_volume_days")),
        require_oneil_stack=bool("ibd" in concept or "oneil" in concept),
        require_volume_dryup=bool("volume_dryup_max_adv20_mult" in entry or entry.get("prior_10d_down_volume_dryup")),
        require_prior_runup=bool(
            any(key in entry for key in ("prior_runup_min_pct", "prior_uptrend_min_pct", "return_63d_min_pct"))
        ),
        require_episodic_gap=bool("gap" in concept or "gap_open_vs_prev_close_min_pct" in entry),
        require_market_trend=bool(market),
        breakout_lookback=breakout_lookback,
        base_lookback=base_lookback,
        volume_lookback=_external_int(entry.get("volume_lookback") or entry.get("volume_dryup_prior_days") or 20, 20, low=5, high=100),
        rs_lookback=126 if "126d" in json.dumps(rs_rules) else 63 if "63d" in json.dumps(rs_rules) else 20,
        high_lookback=252 if "52w" in json.dumps(payload) else 126,
        low_lookback=252,
        ma_short=ma_short,
        ma_mid=ma_mid,
        ma_long=ma_long,
        oneil_fast_ma=10,
        oneil_mid_ma=21,
        volume_multiple=max(float(volume_multiple), 0.01),
        max_base_range_pct=float(np.clip(max_base_range_pct, 0.02, 0.50)),
        rs_near_high_pct=1.0 - max(_external_pct(rs_rules.get("rs_ratio_symbol_spy_within_high_50d_pct"), 0.04), 0.01),
        near_high_pct=float(np.clip(near_high_pct, 0.50, 0.98)),
        above_low_multiple=float(np.clip(above_low_multiple, 1.0, 2.5)),
        rsi_period=_external_int(entry.get("rsi_period"), 14, low=2, high=30),
        rsi_max=float(np.clip(_finite_float(entry.get("rsi_max_signal"), default=75.0), 35.0, 98.0)),
        prior_runup_lookback=prior_runup_lookback,
        prior_runup_min_pct=float(np.clip(prior_runup_min_pct, 0.0, 1.5)),
        volume_dryup_lookback=_external_int(entry.get("volume_dryup_prior_days"), 10, low=3, high=40),
        volume_dryup_max_ratio=float(
            np.clip(_finite_float(entry.get("volume_dryup_max_adv20_mult"), default=0.85), 0.05, 2.0)
        ),
        episodic_gap_pct=float(np.clip(_external_pct(entry.get("gap_open_vs_prev_close_min_pct"), 0.06), 0.0, 0.30)),
        min_adr_pct=0.002,
        stop_loss_pct=float(np.clip(_external_pct(exit_rules.get("stop_loss_pct"), 0.08), 0.005, 0.50)),
        trailing_stop_pct=float(np.clip(_external_pct(exit_rules.get("trailing_stop_pct"), 0.18), 0.0, 0.80)),
        take_profit_pct=float(np.clip(_external_pct(exit_rules.get("take_profit_pct"), 0.0), 0.0, 2.0)),
        max_holding_days=_external_int(exit_rules.get("max_holding_days"), 30, low=1, high=260),
        use_exit_ma=bool(exit_rules.get("exit_on_close_below")),
        use_market_exit=bool(exit_rules.get("market_exit")),
        exit_ma_days=int(np.clip(exit_ma_days, 2, 100)),
        market_ma_days=int(np.clip(market_ma_days, 10, 250)),
        market_momentum_days=20 if any(key.endswith("20d_min_pct") for key in market) else 21,
    )
    approximated: list[str] = []
    for section in ("entry_rules", "market_regime_rules", "stock_trend_rules", "relative_strength_rules", "exit_rules"):
        for key in (payload.get(section) or {}):
            if f"{section}.{key}" not in unknown:
                approximated.append(f"{section}.{key}")
    return ExternalStrategyCandidate(
        payload=payload,
        config=config,
        unsupported_rules=tuple(sorted(unknown)),
        approximated_rules=tuple(sorted(approximated)),
    )


class CandidateEvaluationTimeout(TimeoutError):
    pass


class EarlyRejectedStrategy(Exception):
    """Raised when a candidate cannot mathematically pass required filters."""

    def __init__(
        self,
        reason: str,
        *,
        split: str = "",
        year: int | None = None,
        actual: float | int | str | None = None,
        threshold: float | int | str | None = None,
        stage: str = "safe_prefilter",
        symbols_processed: int = 0,
        seconds_until_reject: float = 0.0,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.split = split
        self.year = year
        self.actual = actual
        self.threshold = threshold
        self.stage = stage
        self.symbols_processed = int(symbols_processed)
        self.seconds_until_reject = float(seconds_until_reject)
        self.diagnostic = dict(diagnostic or {})


@contextlib.contextmanager
def _candidate_evaluation_heartbeat(label: str, interval_seconds: int = 60) -> Iterable[None]:
    """Emit periodic progress so GitHub Actions does not kill long silent jobs."""
    stop_event = threading.Event()

    def _beat() -> None:
        while not stop_event.wait(interval_seconds):
            print(f"[gtbi] still evaluating {label}", flush=True)

    thread = threading.Thread(target=_beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1)


def load_external_strategy_candidates(
    pack_path: Path,
    *,
    shard_id: int | None = None,
    offset: int = 0,
    limit: int | None = None,
    strategy_format: str = "auto",
) -> list[ExternalStrategyCandidate]:
    if shard_id is not None and not (0 <= int(shard_id) <= 359):
        raise ValueError("external_strategy_shard_id must be between 0 and 359")
    strategy_offset = int(offset)
    if strategy_offset < 0:
        raise ValueError("external_strategy_offset must be greater than or equal to 0")
    candidates: list[ExternalStrategyCandidate] = []
    max_count = None if limit is None or int(limit) <= 0 else int(limit)
    matched = 0
    for path in _external_strategy_files(Path(pack_path), shard_id, strategy_format):
        for payload in _iter_external_strategy_payloads(path):
            if shard_id is not None and int(payload.get("shard_id", -1)) != int(shard_id):
                continue
            if matched < strategy_offset:
                matched += 1
                continue
            candidates.append(external_strategy_to_config(payload))
            matched += 1
            if max_count is not None and len(candidates) >= max_count:
                return candidates
    return candidates


def _balanced_external_strategy_candidates_for_job(
    pack_path: Path,
    *,
    job_index: int,
    candidate_count_per_job: int,
    strategy_format: str = "auto",
) -> tuple[list[ExternalStrategyCandidate], int]:
    all_candidates = load_external_strategy_candidates(
        pack_path,
        shard_id=None,
        offset=0,
        limit=None,
        strategy_format=strategy_format,
    )
    per_job = max(int(candidate_count_per_job), 1)
    total_jobs = int(math.ceil(len(all_candidates) / per_job)) if all_candidates else 0
    if total_jobs <= 0 or job_index < 0 or job_index >= total_jobs:
        return [], total_jobs
    ordered = sorted(
        all_candidates,
        key=lambda candidate: (
            _estimated_cost_score(candidate.payload)[0],
            str(candidate.payload.get("concept_id", "")),
            int(candidate.payload.get("shard_id", 0)),
            int(candidate.payload.get("slot_in_shard", 0)),
            str(candidate.payload.get("strategy_id", "")),
        ),
    )
    selected: list[ExternalStrategyCandidate] = []
    cursor = int(job_index)
    while cursor < len(ordered) and len(selected) < per_job:
        selected.append(ordered[cursor])
        cursor += total_jobs
    selected.sort(
        key=lambda candidate: (
            _estimated_cost_score(candidate.payload)[0],
            str(candidate.payload.get("strategy_id", "")),
        )
    )
    return selected, total_jobs


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


def _stability_quality_score(row: dict[str, Any]) -> float:
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
    avg_median_ratio = (avg / med) if med > 0.0 else 99.0
    return (
        -1_000_000.0
        - fail_count * 60_000.0
        - max(100.0 - min_trades, 0.0) * 4_000.0
        - max(150.0 - trades_per_year, 0.0) * 1_000.0
        + min(min_trades, 150.0) * 250.0
        + min(trades_per_year, 500.0) * 35.0
        + val_pos * 12_000.0
        + med_pos * 10_000.0
        + train_pos * 8_000.0
        + val_pf * 10_000.0
        + yearly_pf * 14_000.0
        + train_pf * 10_000.0
        + min(max(med, -2.0), 2.0) * 12_000.0
        + min(max(avg, -2.0), 2.0) * 2_000.0
        - max(concentration - 0.25, 0.0) * 120_000.0
        - max(avg_median_ratio - 5.0, 0.0) * 15_000.0
    )


def _sort_for_stability(leaderboard: pd.DataFrame) -> pd.DataFrame:
    if leaderboard.empty:
        return leaderboard
    out = leaderboard.copy()
    if "strict_quality_pass" not in out.columns:
        return out.sort_values(["score", "candidate_id"], ascending=[False, True])
    out["_strict_pass_sort"] = out["strict_quality_pass"].astype(str).str.lower().isin({"true", "1", "yes"}).astype(int)
    numeric_defaults = {
        "strict_quality_failure_count": 99,
        "validation_min_yearly_trades": 0,
        "validation_trades_per_year": 0,
        "validation_positive_years": 0,
        "validation_median_positive_years": 0,
        "train_2003_2010_positive_years": 0,
        "validation_profit_factor": 0,
        "validation_min_yearly_profit_factor": 0,
        "train_2003_2010_min_profit_factor": 0,
        "validation_median_trade_return_pct": -999,
        "validation_avg_trade_return_pct": -999,
        "validation_max_profit_contribution_share": 1,
        "score": -1e99,
    }
    for column, default in numeric_defaults.items():
        if column not in out.columns:
            out[column] = default
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(default)
    sorted_out = out.sort_values(
        [
            "_strict_pass_sort",
            "strict_quality_failure_count",
            "validation_min_yearly_trades",
            "validation_trades_per_year",
            "validation_positive_years",
            "validation_median_positive_years",
            "train_2003_2010_positive_years",
            "validation_profit_factor",
            "validation_min_yearly_profit_factor",
            "train_2003_2010_min_profit_factor",
            "validation_max_profit_contribution_share",
            "score",
            "candidate_id",
        ],
        ascending=[False, True, False, False, False, False, False, False, False, False, True, False, True],
    )
    return sorted_out.drop(columns=["_strict_pass_sort"])


def near_miss_seed_ids(leaderboard: pd.DataFrame, *, limit: int = 100) -> list[str]:
    if leaderboard.empty or "candidate_id" not in leaderboard.columns:
        return []
    out = leaderboard.copy()
    for column, default in (
        ("strict_quality_failure_count", 99),
        ("validation_min_yearly_trades", 0),
        ("validation_trades_per_year", 0),
        ("validation_positive_years", 0),
        ("validation_median_positive_years", 0),
        ("train_2003_2010_positive_years", 0),
        ("validation_profit_factor", 0),
        ("validation_min_yearly_profit_factor", 0),
        ("train_2003_2010_min_profit_factor", 0),
        ("validation_max_profit_contribution_share", 1),
    ):
        if column not in out.columns:
            out[column] = default
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(default)
    mask = (
        (out["validation_min_yearly_trades"] >= 50)
        & (out["validation_trades_per_year"] >= 100)
        & (out["validation_positive_years"] >= 8)
        & (out["validation_median_positive_years"] >= 7)
        & (out["train_2003_2010_positive_years"] >= 7)
        & (out["strict_quality_failure_count"] <= 5)
        & (out["validation_max_profit_contribution_share"] <= 0.35)
    )
    selected = out.loc[mask].copy()
    if selected.empty:
        selected = out.loc[
            (out["validation_min_yearly_trades"] >= 25)
            & (out["validation_positive_years"] >= 8)
            & (out["strict_quality_failure_count"] <= 6)
        ].copy()
    if selected.empty:
        return []
    selected = _sort_for_stability(selected)
    return selected["candidate_id"].astype(str).head(max(int(limit), 0)).tolist()


def recheck_batches(*, candidate_count: int, batch_size: int) -> list[dict[str, int | str]]:
    count = max(int(candidate_count), 0)
    size = max(int(batch_size), 1)
    rows: list[dict[str, int | str]] = []
    for batch, offset in enumerate(range(0, count, size)):
        limit = min(size, count - offset)
        rows.append({"offset": int(offset), "limit": int(limit), "batch": int(batch), "batch_padded": f"{batch:03d}"})
    return rows


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
        if signal.empty or not bool(signal.any()):
            continue
        prepared_frame = _prepare_ohlcv(frame)
        market_exit = ~_market_trend_ok_for_frame(prepared_frame, benchmark_prices, config) if config.use_market_exit else None
        raw_trades = simulate_trades(
            symbol,
            frame,
            signal,
            config,
            split="unassigned",
            candidate_id=candidate_id,
            exit_signal=market_exit,
        )
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
    elif scoring_profile == "stability_quality":
        score = _stability_quality_score(row)
    elif scoring_profile != "default":
        raise ValueError(f"unknown scoring_profile {scoring_profile!r}; expected one of {SCORING_PROFILES}")
    row["score"] = score
    return row, trades_df, yearly


def _external_profile_value(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return str(value)
    return ""


def _external_diagnostic_base(
    payload: dict[str, Any],
    *,
    job_id: str | None = None,
    canonical_hash: str | None = None,
) -> dict[str, Any]:
    out = {
        "strategy_id": str(payload.get("strategy_id", "")),
        "job_id": "" if job_id is None else str(job_id),
        "shard_id": payload.get("shard_id"),
        "slot_in_shard": payload.get("slot_in_shard"),
        "family": _family_for_external_strategy(payload),
        "concept": _external_profile_value(payload, "concept_id", "concept"),
        "market_overlay": _external_profile_value(payload, "market_overlay_id", "market_overlay"),
        "trend_filter": _external_profile_value(payload, "trend_profile_id", "trend_filter"),
        "relative_strength_filter": _external_profile_value(payload, "rs_profile_id", "relative_strength_filter"),
        "exit_rule": _external_profile_value(payload, "exit_profile_id", "exit_rule"),
        "aggressiveness": _external_profile_value(payload, "aggression_id", "aggressiveness"),
    }
    if canonical_hash is not None:
        out["canonical_hash"] = canonical_hash
    return out


def canonical_external_strategy_hash(candidate: ExternalStrategyCandidate) -> str:
    payload = candidate.payload
    canonical = {
        "config": candidate.config.to_dict(),
        "effective_rules": {
            "family": _family_for_external_strategy(payload),
            "concept_id": payload.get("concept_id"),
            "market_overlay_id": payload.get("market_overlay_id"),
            "trend_profile_id": payload.get("trend_profile_id"),
            "rs_profile_id": payload.get("rs_profile_id"),
            "exit_profile_id": payload.get("exit_profile_id"),
            "aggression_id": payload.get("aggression_id"),
            "entry_rules": payload.get("entry_rules", {}),
            "market_regime_rules": payload.get("market_regime_rules", {}),
            "stock_trend_rules": payload.get("stock_trend_rules", {}),
            "relative_strength_rules": payload.get("relative_strength_rules", {}),
            "exit_rules": payload.get("exit_rules", {}),
            "guardrails": {
                key: value
                for key, value in dict(payload.get("guardrails") or {}).items()
                if key
                in {
                    "data_scope",
                    "do_not_load_or_use_data_on_or_after",
                    "locked_start_exclusive",
                    "execution",
                    "positioning",
                    "min_market_cap_usd",
                    "train_end",
                    "validation_start",
                    "validation_end",
                }
            },
        },
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def signal_external_strategy_hash(candidate: ExternalStrategyCandidate) -> str:
    """Hash only the effective entry/market/stock/RS signal definition."""

    payload = candidate.payload
    canonical = {
        "family": _family_for_external_strategy(payload),
        "concept_id": payload.get("concept_id"),
        "market_overlay_id": payload.get("market_overlay_id"),
        "trend_profile_id": payload.get("trend_profile_id"),
        "rs_profile_id": payload.get("rs_profile_id"),
        "aggression_id": payload.get("aggression_id"),
        "config_signal": {
            key: value
            for key, value in candidate.config.to_dict().items()
            if key
            not in {
                "stop_loss_pct",
                "trailing_stop_pct",
                "take_profit_pct",
                "max_holding_days",
                "use_exit_ma",
                "use_market_exit",
                "exit_ma_days",
            }
        },
        "rules": {
            "entry_rules": payload.get("entry_rules", {}),
            "market_regime_rules": payload.get("market_regime_rules", {}),
            "stock_trend_rules": payload.get("stock_trend_rules", {}),
            "relative_strength_rules": payload.get("relative_strength_rules", {}),
            "guardrails": {
                key: value
                for key, value in dict(payload.get("guardrails") or {}).items()
                if key
                in {
                    "data_scope",
                    "do_not_load_or_use_data_on_or_after",
                    "locked_start_exclusive",
                    "execution",
                    "positioning",
                    "min_market_cap_usd",
                    "train_end",
                    "validation_start",
                    "validation_end",
                }
            },
        },
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


RECOVERY_FAST_CONCEPT_SCORES = {
    "q_stair_step_breakout": -8.0,
    "rsi2_pullback_rebound_trend": -8.0,
    "post_ep_pullback_reclaim_proxy": -6.0,
    "moving_average_timing_cross": -6.0,
    "time_series_momentum_reentry": -6.0,
    "macd_histogram_turnup_trend": -5.0,
    "three_weeks_tight_daily_proxy": -4.0,
    "q_stair_step_reclaim": -3.0,
}


def _estimated_cost_score(payload: dict[str, Any]) -> tuple[float, str]:
    concept = _external_profile_value(payload, "concept_id", "concept")
    family = _family_for_external_strategy(payload)
    exit_rule = _external_profile_value(payload, "exit_profile_id", "exit_rule")
    market_overlay = _external_profile_value(payload, "market_overlay_id", "market_overlay")
    aggressiveness = _external_profile_value(payload, "aggression_id", "aggressiveness")
    very_slow_concepts = {
        "atr_compression_nr_breakout",
        "ibd_cup_handle_proxy",
        "ibd_flat_base_proxy",
        "bollinger_squeeze_breakout",
        "weinstein_stage2_breakout_proxy",
        "minervini_vcp_pivot_breakout",
        "minervini_vcp_anticipation_reclaim",
        "inside_day_breakout_reclaim",
    }
    slow_concepts = {
        "keltner_pullback_reclaim",
        "ep_gap_volume_continuation_proxy",
        "academic_6_12m_momentum_reclaim",
        "failed_breakdown_reclaim",
        "pocket_pivot_reclaim",
        "ema_value_zone_pullback",
        "academic_52w_high_pullback_reclaim",
        "rs_new_high_before_price_reclaim",
        "gap_down_leader_reclaim",
        "undercut_reclaim_shakeout",
        "trend_template_pullback_rebound",
        "adx_di_pullback_reversal",
    }
    score = float(RECOVERY_FAST_CONCEPT_SCORES.get(concept, 0.0))
    if concept in very_slow_concepts:
        score += 5.0
    elif concept in slow_concepts:
        score += 3.0
    if family == "oneil_canslim":
        score += 2.0
    elif family == "quallamaggie":
        score += 1.5
    if exit_rule in {"chandelier_runner", "balanced_tp_ema20"}:
        score += 2.0
    if market_overlay in {"spy_broad_loose_bull", "spy_low_vol_uptrend"}:
        score += 1.0
    if aggressiveness == "frequency_quality":
        score += 1.0
    if score <= -4.0:
        return score, "fast"
    if score >= 8.0:
        return score, "very_slow"
    if score >= 5.0:
        return score, "slow"
    if score >= 2.0:
        return score, "normal"
    return score, "fast"


def _append_external_timeout_result(
    *,
    timeout_rows: list[dict[str, Any]],
    dedupe_rows: list[dict[str, Any]],
    timing_rows: list[dict[str, Any]],
    diagnostic_base: dict[str, Any],
    payload: dict[str, Any],
    candidate_id: str,
    canonical_hash: str,
    signal_hash: str,
    reason: str,
    seconds_total: float,
    symbols_total: int,
    symbols_processed: int,
) -> None:
    timeout_rows.append(
        {
            "strategy_id": candidate_id,
            "shard_id": payload.get("shard_id"),
            "slot_in_shard": payload.get("slot_in_shard"),
            "family": diagnostic_base.get("family", ""),
            "concept": diagnostic_base.get("concept", ""),
            "market_overlay": diagnostic_base.get("market_overlay", ""),
            "trend_filter": diagnostic_base.get("trend_filter", ""),
            "relative_strength_filter": diagnostic_base.get("relative_strength_filter", ""),
            "exit_rule": diagnostic_base.get("exit_rule", ""),
            "aggressiveness": diagnostic_base.get("aggressiveness", ""),
            "reason": reason,
            "seconds_until_timeout": float(seconds_total),
        }
    )
    dedupe_rows.append(
        {
            "strategy_id": candidate_id,
            "canonical_hash": canonical_hash,
            "canonical_strategy_id": "",
            "deduped": False,
            "signal_hash": signal_hash,
            "signal_canonical_strategy_id": "",
            "signal_deduped": False,
        }
    )
    timing_rows.append(
        {
            **diagnostic_base,
            "seconds_total": float(seconds_total),
            "seconds_feature_build": 0.0,
            "seconds_signal": float("nan"),
            "seconds_simulation": float("nan"),
            "seconds_train": 0.0,
            "seconds_validation": 0.0,
            "symbols_total": int(symbols_total),
            "symbols_processed": int(symbols_processed),
            "raw_signals_total": 0,
            "trades_total": 0,
            "train_trades": 0,
            "validation_trades": 0,
            "result_status": "timeout",
            "reject_reason": reason,
            "timeout": True,
            "early_rejected": False,
            "runtime_error": False,
        }
    )


def _signal_year_counts_for_possible_exits(
    *,
    signals_by_symbol: dict[str, pd.Series],
    symbol_frames: dict[str, pd.DataFrame],
    config: IndicatorConfig,
    years: range,
) -> dict[int, int]:
    counts = {int(year): 0 for year in years}
    lookback_days = max(int(config.max_holding_days) + 7, 14)
    for symbol, signal in signals_by_symbol.items():
        frame = _prepare_ohlcv(symbol_frames[symbol])
        if frame.empty or signal.empty:
            continue
        signal = signal.reindex(frame.index).fillna(False).astype(bool)
        signal_dates = pd.DatetimeIndex(frame.index[np.flatnonzero(signal.to_numpy(dtype=bool)[:-1])])
        if signal_dates.empty:
            continue
        for year in years:
            start = pd.Timestamp(year=int(year), month=1, day=1) - pd.Timedelta(days=lookback_days)
            end = pd.Timestamp(year=int(year), month=12, day=31)
            counts[int(year)] += int(((signal_dates >= start) & (signal_dates <= end)).sum())
    return counts


def _safe_prefilter_raw_signals(
    *,
    signals_by_symbol: dict[str, pd.Series],
    symbol_frames: dict[str, pd.DataFrame],
    config: IndicatorConfig,
    validation_start: str,
    validation_end: str,
) -> tuple[dict[str, Any] | None, int]:
    validation_years = range(_dt(validation_start).year, _dt(validation_end).year + 1)
    validation_counts = _signal_year_counts_for_possible_exits(
        signals_by_symbol=signals_by_symbol,
        symbol_frames=symbol_frames,
        config=config,
        years=validation_years,
    )
    if validation_counts:
        min_year = min(validation_counts, key=lambda year: validation_counts[year])
        min_count = int(validation_counts[min_year])
        if min_count < 100:
            return (
                {
                    "reason": "raw_signal_yearly_trades_lt_100",
                    "split": "validation",
                    "year": int(min_year),
                    "actual": int(min_count),
                    "threshold": 100,
                    "stage": "safe_prefilter",
                },
                int(sum(validation_counts.values())),
            )
        avg_count = float(sum(validation_counts.values()) / max(len(validation_counts), 1))
        if avg_count < 150.0:
            return (
                {
                    "reason": "raw_signal_trades_per_year_lt_150",
                    "split": "validation",
                    "year": "",
                    "actual": avg_count,
                    "threshold": 150.0,
                    "stage": "safe_prefilter",
                },
                int(sum(validation_counts.values())),
            )

    train_counts = _signal_year_counts_for_possible_exits(
        signals_by_symbol=signals_by_symbol,
        symbol_frames=symbol_frames,
        config=config,
        years=range(2003, 2011),
    )
    train_possible_years = int(sum(1 for value in train_counts.values() if int(value) > 0))
    if train_counts and train_possible_years < 8:
        return (
            {
                "reason": "raw_signal_train_2003_2010_years_lt_8",
                "split": "train",
                "year": "",
                "actual": int(train_possible_years),
                "threshold": 8,
                "stage": "safe_prefilter",
            },
            int(sum(validation_counts.values())),
        )
    return None, int(sum(validation_counts.values()))


def evaluate_candidate_optimized(
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
    enable_safe_prefilter: bool = True,
    enable_early_stopping: bool = True,
    deadline: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    del enable_early_stopping  # Early stops are restricted to the safe raw-signal prefilter in v1.
    total_start = time.perf_counter()
    signal_start = time.perf_counter()
    signals_by_symbol: dict[str, pd.Series] = {}
    symbols_processed = 0
    raw_signals_total = 0
    for symbol, frame in symbol_frames.items():
        if deadline is not None and time.perf_counter() >= deadline:
            raise CandidateEvaluationTimeout("candidate evaluation exceeded cooperative deadline while building signals")
        symbols_processed += 1
        signal = entry_signal(frame, benchmark_prices, config)
        if symbols_processed % 250 == 0:
            print(
                f"[gtbi] candidate={candidate_id} signal_progress={symbols_processed}/{len(symbol_frames)}",
                flush=True,
            )
        if signal.empty or not bool(signal.any()):
            if deadline is not None and time.perf_counter() >= deadline and symbols_processed < len(symbol_frames):
                raise CandidateEvaluationTimeout("candidate evaluation exceeded cooperative deadline while building signals")
            continue
        signals_by_symbol[symbol] = signal
        raw_signals_total += int(signal.sum())
        if deadline is not None and time.perf_counter() >= deadline and symbols_processed < len(symbol_frames):
            raise CandidateEvaluationTimeout("candidate evaluation exceeded cooperative deadline while building signals")
    seconds_signal = float(time.perf_counter() - signal_start)

    if enable_safe_prefilter:
        reject, validation_signal_total = _safe_prefilter_raw_signals(
            signals_by_symbol=signals_by_symbol,
            symbol_frames=symbol_frames,
            config=config,
            validation_start=validation_start,
            validation_end=validation_end,
        )
        if reject is not None:
            seconds_total = float(time.perf_counter() - total_start)
            diagnostic = {
                "seconds_total": seconds_total,
                "seconds_feature_build": 0.0,
                "seconds_signal": seconds_signal,
                "seconds_simulation": 0.0,
                "seconds_train": 0.0,
                "seconds_validation": 0.0,
                "symbols_total": int(len(symbol_frames)),
                "symbols_processed": int(symbols_processed),
                "raw_signals_total": int(raw_signals_total),
                "trades_total": 0,
                "train_trades": 0,
                "validation_trades": 0,
            }
            raise EarlyRejectedStrategy(
                str(reject["reason"]),
                split=str(reject.get("split", "")),
                year=int(reject["year"]) if str(reject.get("year", "")).isdigit() else None,
                actual=reject.get("actual", validation_signal_total),
                threshold=reject.get("threshold", ""),
                stage=str(reject.get("stage", "safe_prefilter")),
                symbols_processed=symbols_processed,
                seconds_until_reject=seconds_total,
                diagnostic=diagnostic,
            )

    simulation_start = time.perf_counter()
    all_trades: list[pd.DataFrame] = []
    simulated_symbols = 0
    for symbol, signal in signals_by_symbol.items():
        if deadline is not None and time.perf_counter() >= deadline:
            raise CandidateEvaluationTimeout("candidate evaluation exceeded cooperative deadline while simulating trades")
        simulated_symbols += 1
        frame = symbol_frames[symbol]
        prepared_frame = _prepare_ohlcv(frame)
        market_exit = ~_market_trend_ok_for_frame(prepared_frame, benchmark_prices, config) if config.use_market_exit else None
        raw_trades = simulate_trades(
            symbol,
            frame,
            signal,
            config,
            split="unassigned",
            candidate_id=candidate_id,
            exit_signal=market_exit,
        )
        trades = split_trade_frame(
            raw_trades,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
        )
        if not trades.empty:
            all_trades.append(trades)
        if simulated_symbols % 250 == 0:
            print(
                f"[gtbi] candidate={candidate_id} simulation_progress={simulated_symbols}/{len(signals_by_symbol)}",
                flush=True,
            )
        if deadline is not None and time.perf_counter() >= deadline:
            raise CandidateEvaluationTimeout("candidate evaluation exceeded cooperative deadline while simulating trades")
    seconds_simulation = float(time.perf_counter() - simulation_start)
    trades_df = pd.concat(all_trades, ignore_index=True, sort=False) if all_trades else pd.DataFrame(columns=TRADE_COLUMNS)

    train_years = max((_dt(train_end) - pd.Timestamp("1900-01-01")).days / 365.25, 1.0)
    if not trades_df.empty:
        first_train = pd.to_datetime(trades_df.loc[trades_df["split"] == "train", "exit_date"], errors="coerce").min()
        if pd.notna(first_train):
            train_years = max((_dt(train_end) - first_train).days / 365.25, 1.0)
    validation_years = max((_dt(validation_end) - _dt(validation_start)).days / 365.25, 1.0)

    train_start = time.perf_counter()
    train = summarize_trades(trades_df[trades_df["split"] == "train"], years=train_years)
    seconds_train = float(time.perf_counter() - train_start)
    validation_start_timer = time.perf_counter()
    validation = summarize_trades(trades_df[trades_df["split"] == "validation"], years=validation_years)
    yearly = yearly_trade_performance(trades_df, benchmark_prices)
    seconds_validation = float(time.perf_counter() - validation_start_timer)

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
    elif scoring_profile == "stability_quality":
        score = _stability_quality_score(row)
    elif scoring_profile != "default":
        raise ValueError(f"unknown scoring_profile {scoring_profile!r}; expected one of {SCORING_PROFILES}")
    row["score"] = score
    diagnostic = {
        "seconds_total": float(time.perf_counter() - total_start),
        "seconds_feature_build": 0.0,
        "seconds_signal": seconds_signal,
        "seconds_simulation": seconds_simulation,
        "seconds_train": seconds_train,
        "seconds_validation": seconds_validation,
        "symbols_total": int(len(symbol_frames)),
        "symbols_processed": int(symbols_processed),
        "raw_signals_total": int(raw_signals_total),
        "trades_total": int(len(trades_df)),
        "train_trades": int(row.get("train_trades", 0)),
        "validation_trades": int(row.get("validation_trades", 0)),
    }
    return row, trades_df, yearly, diagnostic


def _evaluate_external_candidate_core(
    *,
    config: IndicatorConfig,
    candidate_id: str,
    stage: int,
    symbol_frames: dict[str, pd.DataFrame],
    benchmark_prices: pd.DataFrame,
    train_end: str,
    validation_start: str,
    validation_end: str,
    optimized_evaluation_mode: str,
    enable_safe_prefilter: bool,
    enable_early_stopping: bool,
    deadline: float | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if optimized_evaluation_mode in {"optimized_evaluation_v1", "optimized_evaluation_v2"}:
        return evaluate_candidate_optimized(
            config=config,
            candidate_id=candidate_id,
            stage=stage,
            symbol_frames=symbol_frames,
            benchmark_prices=benchmark_prices,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            search_method=EXTERNAL_SEARCH_METHOD,
            selection_split="validation",
            min_selection_trades_per_year=100,
            scoring_profile="strict_quality",
            enable_safe_prefilter=enable_safe_prefilter,
            enable_early_stopping=enable_early_stopping,
            deadline=deadline,
        )

    start = time.perf_counter()
    row, trades, yearly = evaluate_candidate(
        config=config,
        candidate_id=candidate_id,
        stage=stage,
        symbol_frames=symbol_frames,
        benchmark_prices=benchmark_prices,
        train_end=train_end,
        validation_start=validation_start,
        validation_end=validation_end,
        search_method=EXTERNAL_SEARCH_METHOD,
        selection_split="validation",
        min_selection_trades_per_year=100,
        scoring_profile="strict_quality",
    )
    diagnostic = {
        "seconds_total": float(time.perf_counter() - start),
        "seconds_feature_build": 0.0,
        "seconds_signal": float("nan"),
        "seconds_simulation": float("nan"),
        "seconds_train": float("nan"),
        "seconds_validation": float("nan"),
        "symbols_total": int(len(symbol_frames)),
        "symbols_processed": int(len(symbol_frames)),
        "raw_signals_total": 0,
        "trades_total": int(len(trades)),
        "train_trades": int(row.get("train_trades", 0)),
        "validation_trades": int(row.get("validation_trades", 0)),
    }
    return row, trades, yearly, diagnostic


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
    "market_ma_days": (50, 250, True),
    "market_momentum_days": (5, 126, True),
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
        "require_market_trend": bool(rng.random() < 0.55),
        "use_market_exit": bool(rng.random() < 0.35),
        "strict_market_filter": bool(rng.random() < 0.20),
        "market_ma_days": int(rng.choice([50, 100, 150, 200])),
        "market_momentum_days": int(rng.choice([10, 21, 42, 63, 126])),
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
    elif family in STABILITY_FAMILIES:
        params.update(
            minervini_trend=False,
            require_rs=bool(rng.random() < 0.35),
            require_base_tight=False,
            require_breakout=False,
            require_market_trend=bool(rng.random() < 0.90),
            strict_market_filter=bool(rng.random() < 0.85),
            use_market_exit=bool(rng.random() < 0.90),
            use_exit_ma=bool(rng.random() < 0.45),
            ma_short=int(rng.choice([20, 30, 50])),
            ma_mid=int(rng.choice([80, 100, 150])),
            ma_long=int(rng.choice([120, 150, 200])),
            rsi_period=int(rng.choice([7, 10, 14, 21])),
            rsi_max=float(rng.uniform(38.0, 68.0)),
            near_high_pct=float(rng.uniform(0.45, 0.85)),
            above_low_multiple=float(rng.uniform(1.00, 1.25)),
            stop_loss_pct=float(rng.uniform(0.025, 0.09)),
            trailing_stop_pct=float(rng.uniform(0.035, 0.14)),
            take_profit_pct=float(rng.choice([0.0, rng.uniform(0.025, 0.18), rng.uniform(0.08, 0.30)])),
            max_holding_days=int(rng.choice([2, 3, 4, 5, 8, 10, 15, 20])),
            exit_ma_days=int(rng.choice([5, 8, 10, 15, 20])),
            market_ma_days=int(rng.choice([50, 100, 150, 200])),
            market_momentum_days=int(rng.choice([5, 10, 21, 42, 63])),
        )
        if family == "stability_rs_momentum_pullback":
            params.update(
                require_rs=True,
                require_market_trend=True,
                strict_market_filter=bool(rng.random() < 0.75),
                use_market_exit=bool(rng.random() < 0.85),
                ma_short=int(rng.choice([20, 30, 50])),
                ma_mid=int(rng.choice([80, 100, 150])),
                ma_long=int(rng.choice([150, 200])),
                rs_lookback=int(rng.choice([42, 63, 126])),
                rs_near_high_pct=float(rng.uniform(0.88, 0.99)),
                prior_runup_lookback=int(rng.choice([42, 63, 90, 126])),
                prior_runup_min_pct=float(rng.uniform(0.08, 0.45)),
                near_high_pct=float(rng.uniform(0.70, 0.92)),
                rsi_period=int(rng.choice([7, 10, 14])),
                rsi_max=float(rng.uniform(42.0, 65.0)),
                stop_loss_pct=float(rng.uniform(0.025, 0.07)),
                trailing_stop_pct=float(rng.uniform(0.04, 0.12)),
                take_profit_pct=float(rng.choice([rng.uniform(0.025, 0.12), rng.uniform(0.05, 0.20)])),
                max_holding_days=int(rng.choice([3, 4, 5, 8, 10, 15])),
            )
        elif family == "stability_rs_reclaim_frequent":
            params.update(
                require_rs=True,
                require_market_trend=True,
                strict_market_filter=bool(rng.random() < 0.60),
                use_market_exit=True,
                use_exit_ma=bool(rng.random() < 0.35),
                ma_short=int(rng.choice([10, 20, 30])),
                ma_mid=int(rng.choice([50, 80, 100])),
                ma_long=int(rng.choice([120, 150, 200])),
                rs_lookback=int(rng.choice([21, 42, 63])),
                rs_near_high_pct=float(rng.uniform(0.78, 0.92)),
                prior_runup_lookback=int(rng.choice([21, 42, 63, 90])),
                prior_runup_min_pct=float(rng.uniform(0.03, 0.18)),
                near_high_pct=float(rng.uniform(0.50, 0.78)),
                rsi_period=int(rng.choice([7, 10, 14])),
                rsi_max=float(rng.uniform(50.0, 70.0)),
                stop_loss_pct=float(rng.uniform(0.025, 0.065)),
                trailing_stop_pct=float(rng.uniform(0.035, 0.10)),
                take_profit_pct=float(rng.choice([rng.uniform(0.025, 0.08), rng.uniform(0.05, 0.14)])),
                max_holding_days=int(rng.choice([2, 3, 4, 5, 8, 10])),
                exit_ma_days=int(rng.choice([5, 8, 10])),
            )
        elif family == "stability_rs_pullback_breakout":
            params.update(
                require_rs=True,
                require_market_trend=True,
                strict_market_filter=bool(rng.random() < 0.70),
                use_market_exit=True,
                use_exit_ma=bool(rng.random() < 0.45),
                ma_short=int(rng.choice([10, 20, 30])),
                ma_mid=int(rng.choice([50, 80, 100])),
                ma_long=int(rng.choice([120, 150, 200])),
                breakout_lookback=int(rng.choice([10, 15, 20, 30])),
                base_lookback=int(rng.choice([5, 8, 10, 15, 20])),
                volume_lookback=int(rng.choice([10, 20, 30, 50])),
                volume_multiple=float(rng.uniform(0.85, 1.35)),
                max_base_range_pct=float(rng.uniform(0.06, 0.20)),
                rs_lookback=int(rng.choice([21, 42, 63, 84])),
                rs_near_high_pct=float(rng.uniform(0.78, 0.94)),
                prior_runup_lookback=int(rng.choice([21, 42, 63, 90])),
                prior_runup_min_pct=float(rng.uniform(0.03, 0.22)),
                near_high_pct=float(rng.uniform(0.55, 0.82)),
                rsi_period=int(rng.choice([7, 10, 14])),
                rsi_max=float(rng.uniform(52.0, 72.0)),
                stop_loss_pct=float(rng.uniform(0.025, 0.065)),
                trailing_stop_pct=float(rng.uniform(0.035, 0.10)),
                take_profit_pct=float(rng.choice([rng.uniform(0.025, 0.08), rng.uniform(0.05, 0.14)])),
                max_holding_days=int(rng.choice([2, 3, 4, 5, 8, 10, 15])),
                exit_ma_days=int(rng.choice([5, 8, 10, 15])),
            )
    return IndicatorConfig(**params)


def _mutate_config(rng: np.random.Generator, base: IndicatorConfig, family_set: str = "default") -> IndicatorConfig:
    data = base.to_dict()
    allowed_families = _families_for_set(family_set)
    if data["family"] not in allowed_families:
        data["family"] = str(rng.choice(allowed_families))
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
        data["family"] = str(rng.choice(allowed_families))
    return IndicatorConfig(**data)


def _neighbourhood_configs(
    rng: np.random.Generator,
    seeds: list[IndicatorConfig],
    count: int,
    *,
    family_set: str = "default",
) -> list[IndicatorConfig]:
    if count <= 0 or not seeds:
        return []
    configs: list[IndicatorConfig] = []
    for _ in range(count):
        seed = seeds[int(rng.integers(0, len(seeds)))]
        mutated = _mutate_config(rng, seed, family_set=family_set)
        data = mutated.to_dict()
        if data["family"] in STABILITY_FAMILIES:
            data["require_market_trend"] = True
            data["use_market_exit"] = True
            data["max_holding_days"] = int(np.clip(data["max_holding_days"], 2, 20))
            data["stop_loss_pct"] = float(np.clip(data["stop_loss_pct"], 0.02, 0.09))
            data["trailing_stop_pct"] = float(np.clip(data["trailing_stop_pct"], 0.03, 0.16))
            if float(data["take_profit_pct"]) <= 0.0 or rng.random() < 0.60:
                data["take_profit_pct"] = float(rng.uniform(0.025, 0.16))
        configs.append(IndicatorConfig(**data))
    return configs


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
        "require_market_trend": bool(rng.random() < 0.45),
        "use_market_exit": bool(rng.random() < 0.30),
        "strict_market_filter": bool(rng.random() < 0.15),
        "market_ma_days": int(rng.choice([50, 100, 150, 200])),
        "market_momentum_days": int(rng.choice([10, 21, 42, 63, 126])),
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
    elif family in STABILITY_FAMILIES:
        return _sample_dehb_real_config(rng, family_set=family_set)
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
        str(symbol): _prepare_ohlcv(group.reset_index(drop=True))
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
    seed_rules_path: Path | None = None,
    seed_mutation_share: float = 0.65,
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
    benchmark = _prepare_ohlcv(pd.read_parquet(pack_dir / "benchmark.parquet"))
    rng = np.random.default_rng(int(seed) + int(stage) * 1009)
    seed_configs = _load_seed_configs(seed_rules_path, max_seeds=200)
    seed_share = float(np.clip(seed_mutation_share, 0.0, 0.95)) if seed_configs else 0.0
    start = time.monotonic()
    deadline = start + max(float(time_budget_minutes), 0.01) * 60.0
    initial = min(int(configs_per_stage), max(24, int(configs_per_stage * 0.35)))
    remaining = max(int(configs_per_stage) - initial, 0)
    seed_initial = int(round(initial * seed_share))
    configs = _neighbourhood_configs(rng, seed_configs, seed_initial, family_set=family_set)
    configs.extend(
        sample_config(rng, search_method=search_method, family_set=family_set)
        for _ in range(max(initial - len(configs), 0))
    )
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
            if seed_configs and seed_share > 0.0:
                seed_extra = int(round(remaining * seed_share))
                seeded = _neighbourhood_configs(rng, seed_configs, seed_extra, family_set=family_set)
                extra = seeded + extra[: max(remaining - len(seeded), 0)]
            configs.extend(extra)
    leaderboard = pd.DataFrame(rows, columns=LEADERBOARD_COLUMNS)
    if not leaderboard.empty:
        leaderboard = _sort_for_stability(leaderboard).head(top_per_stage)
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
        "seed_rules_path": None if seed_rules_path is None else str(seed_rules_path),
        "seed_configs": int(len(seed_configs)),
        "seed_mutation_share": float(seed_share),
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
    effective_group_count = max(int(group_count), 1)
    grouped: dict[int, list[str]] = {group: [] for group in range(effective_group_count)}
    for idx, symbol in enumerate(symbols):
        grouped[idx % effective_group_count].append(symbol)

    def build_group_prices(group_index: int) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for symbol in grouped[group_index]:
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
        if frames:
            return pd.concat(frames, ignore_index=True, sort=False)
        return pd.DataFrame(columns=PRICE_COLUMNS)

    stage_rows: list[dict[str, Any]] = []
    group_stats: dict[int, dict[str, int]] = {}
    if group_count > 1:
        for group_index in range(effective_group_count):
            group_dir = output_dir / f"group-{group_index:03d}"
            group_dir.mkdir(parents=True, exist_ok=True)
            prices = build_group_prices(group_index)
            prices.to_parquet(group_dir / "prices.parquet", index=False)
            benchmark.to_parquet(group_dir / "benchmark.parquet", index=False)
            group_stats[group_index] = {
                "symbols": int(prices["symbol"].nunique()) if not prices.empty else 0,
                "rows": int(len(prices)),
            }
        for stage in range(stage_count):
            group_index = stage % effective_group_count
            stats = group_stats[group_index]
            stage_rows.append(
                {
                    "stage": stage,
                    "group": group_index,
                    "symbols": stats["symbols"],
                    "rows": stats["rows"],
                }
            )
    else:
        for stage in range(stage_count):
            stage_dir = output_dir / f"stage-{stage:03d}"
            stage_dir.mkdir(parents=True, exist_ok=True)
            prices = build_group_prices(0)
            prices.to_parquet(stage_dir / "prices.parquet", index=False)
            benchmark.to_parquet(stage_dir / "benchmark.parquet", index=False)
            stage_rows.append(
                {
                    "stage": stage,
                    "group": 0,
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
        leaderboard = _sort_for_stability(leaderboard).head(top_n)
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


def _config_from_payload(payload: dict[str, Any]) -> IndicatorConfig:
    defaults = IndicatorConfig().to_dict()
    values = {field.name: payload.get(field.name, defaults[field.name]) for field in fields(IndicatorConfig)}
    return IndicatorConfig(**values)


def _load_rule_configs(rules_path: Path) -> dict[str, IndicatorConfig]:
    configs: dict[str, IndicatorConfig] = {}
    if not rules_path.exists():
        return configs
    for line in rules_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        candidate_id = str(payload.get("candidate_id", ""))
        config_payload = payload.get("config")
        if candidate_id and isinstance(config_payload, dict):
            configs[candidate_id] = _config_from_payload(config_payload)
    return configs


def _load_seed_configs(rules_path: Path | None, *, max_seeds: int = 100) -> list[IndicatorConfig]:
    if rules_path is None:
        return []
    configs = _load_rule_configs(Path(rules_path))
    if not configs:
        return []
    return list(configs.values())[: max(int(max_seeds), 0)]


def reevaluate_global_candidates(
    *,
    merged_dir: Path,
    data_lake_root: Path,
    output_dir: Path,
    candidate_limit: int = 200,
    candidate_offset: int = 0,
    min_market_cap: float = 0.0,
    locked_start: str = DEFAULT_LOCKED_START,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
    scoring_profile: str = "strict_quality",
) -> dict[str, Any]:
    merged_dir = Path(merged_dir)
    data_lake_root = Path(data_lake_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_leaderboard_path = merged_dir / "leaderboard.csv"
    if not shard_leaderboard_path.exists():
        raise FileNotFoundError(f"{shard_leaderboard_path} not found")
    shard_leaderboard = pd.read_csv(shard_leaderboard_path)
    rule_configs = _load_rule_configs(merged_dir / "top_indicator_rules.jsonl")
    if shard_leaderboard.empty or not rule_configs:
        summary = {
            "campaign_id": CAMPAIGN_ID,
            "artifact_name": ARTIFACT_NAME,
            "global_recheck_candidates": 0,
            "filtered_candidates": 0,
            "locked_opened": False,
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        return summary

    if output_dir.resolve() == merged_dir.resolve():
        for name in (
            "leaderboard.csv",
            "filtered_leaderboard.csv",
            "yearly_trade_performance.csv",
            "top_trades_sample.csv",
            "top_indicator_rules.jsonl",
            "family_summary.csv",
            "summary.json",
        ):
            src = output_dir / name
            dst = output_dir / f"shard_{name}"
            if src.exists() and not dst.exists():
                src.replace(dst)

    pack_root = output_dir / "_global_recheck_pack"
    build_stage_packs(
        data_lake_root,
        pack_root,
        stage_count=1,
        group_count=1,
        locked_start=locked_start,
        min_rows=260,
        min_market_cap=min_market_cap,
    )
    pack_dir = pack_root / "stage-000"
    symbol_frames = _load_symbol_frames(pack_dir / "prices.parquet")
    benchmark = _prepare_ohlcv(pd.read_parquet(pack_dir / "benchmark.parquet"))

    ordered_ids = [
        str(value)
        for value in shard_leaderboard["candidate_id"]
        .iloc[int(candidate_offset) : int(candidate_offset) + int(candidate_limit)]
        .tolist()
    ]
    rows: list[dict[str, Any]] = []
    yearly_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    rules_out: list[dict[str, Any]] = []
    for idx, candidate_id in enumerate(ordered_ids):
        config = rule_configs.get(candidate_id)
        if config is None:
            continue
        row, trades, yearly = evaluate_candidate(
            config=config,
            candidate_id=candidate_id,
            stage=int(idx),
            symbol_frames=symbol_frames,
            benchmark_prices=benchmark,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            search_method="global_recheck",
            selection_split="validation",
            min_selection_trades_per_year=100,
            scoring_profile=scoring_profile,
        )
        rows.append(row)
        if not yearly.empty:
            yearly_frames.append(yearly)
        if not trades.empty:
            trade_frames.append(trades)
        rules_out.append(
            {
                "candidate_id": candidate_id,
                "stage": int(idx),
                "search_method": "global_recheck",
                "selection_split": "validation",
                "scoring_profile": scoring_profile,
                "config": config.to_dict(),
                "score": row["score"],
            }
        )

    leaderboard = pd.DataFrame(rows, columns=LEADERBOARD_COLUMNS)
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values(["score", "candidate_id"], ascending=[False, True]).reset_index(drop=True)
    filtered = pd.DataFrame(columns=leaderboard.columns)
    if not leaderboard.empty:
        mask = leaderboard["strict_quality_pass"].astype(bool)
        filtered = leaderboard.loc[mask].sort_values(
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
    yearly = pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else pd.DataFrame(columns=YEARLY_COLUMNS)
    trades = pd.concat(trade_frames, ignore_index=True, sort=False) if trade_frames else pd.DataFrame(columns=TRADE_COLUMNS)
    top_ids = set(leaderboard.head(250)["candidate_id"].astype(str)) if not leaderboard.empty else set()
    if top_ids:
        yearly = yearly[yearly["candidate_id"].astype(str).isin(top_ids)].copy()
        trades = trades[trades["candidate_id"].astype(str).isin(top_ids)].copy()
        rules_out = [row for row in rules_out if str(row["candidate_id"]) in top_ids]

    leaderboard.to_csv(output_dir / "leaderboard.csv", index=False)
    filtered.to_csv(output_dir / "filtered_leaderboard.csv", index=False)
    yearly.to_csv(output_dir / "yearly_trade_performance.csv", index=False)
    trades.head(10000).to_csv(output_dir / "top_trades_sample.csv", index=False)
    with (output_dir / "top_indicator_rules.jsonl").open("w", encoding="utf-8") as handle:
        for row in rules_out:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    if not leaderboard.empty:
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
        "global_recheck": True,
        "global_recheck_candidates": int(len(leaderboard)),
        "candidate_offset": int(candidate_offset),
        "candidate_limit": int(candidate_limit),
        "symbols": int(len(symbol_frames)),
        "min_market_cap": float(min_market_cap),
        "locked_opened": False,
        "scoring_profile": str(scoring_profile),
        "filtered_candidates": int(len(filtered)),
        "best_candidate_id": None if leaderboard.empty else str(leaderboard.iloc[0]["candidate_id"]),
        "best_score": None if leaderboard.empty else float(leaderboard.iloc[0]["score"]),
        "best_filtered_candidate_id": None if filtered.empty else str(filtered.iloc[0]["candidate_id"]),
        "best_filtered_adjusted_return_time_risk": None if filtered.empty else float(filtered.iloc[0]["adjusted_return_time_risk"]),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def _external_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_id": str(payload.get("strategy_id", "")),
        "shard_id": int(payload.get("shard_id", -1)),
        "slot_in_shard": int(payload.get("slot_in_shard", -1)),
        "concept_id": str(payload.get("concept_id", "")),
        "market_overlay_id": str(payload.get("market_overlay_id", "")),
        "trend_profile_id": str(payload.get("trend_profile_id", "")),
        "rs_profile_id": str(payload.get("rs_profile_id", "")),
        "exit_profile_id": str(payload.get("exit_profile_id", "")),
        "aggression_id": str(payload.get("aggression_id", "")),
        "source_quality_score": _finite_float(payload.get("source_quality_score"), default=float("nan")),
        "external_strategy_pack": True,
    }


def run_external_strategy_pack_shard(
    *,
    data_lake_root: Path,
    external_strategy_pack_path: Path = DEFAULT_EXTERNAL_STRATEGY_PACK_PATH,
    output_dir: Path,
    prebuilt_pack_dir: Path | None = None,
    external_strategy_shard_id: int,
    external_strategy_offset: int = 0,
    external_strategy_limit: int = 200,
    external_strategy_format: str = "auto",
    external_strategy_fail_on_unsupported: bool = False,
    candidate_timeout_seconds: int = DEFAULT_EXTERNAL_CANDIDATE_TIMEOUT_SECONDS,
    min_market_cap: float = 2_000_000_000,
    locked_start: str = DEFAULT_LOCKED_START,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
    optimized_evaluation_mode: str = "optimized_evaluation_v2",
    enable_feature_cache: bool = True,
    enable_dedupe: bool = True,
    enable_safe_prefilter: bool = True,
    enable_early_stopping: bool = True,
    enable_cost_scheduling: bool = True,
    job_wall_clock_seconds: int = 300,
) -> dict[str, Any]:
    job_start = time.perf_counter()
    job_deadline = (
        job_start + float(job_wall_clock_seconds)
        if job_wall_clock_seconds and float(job_wall_clock_seconds) > 0
        else None
    )
    shard = int(external_strategy_shard_id)
    shard_padded = f"{shard:03d}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = output_dir.name
    output_prefix = "job" if output_name.startswith("job-") else "shard"
    output_padded = output_name.split("-", 1)[1] if output_prefix == "job" and "-" in output_name else shard_padded
    file_suffix = f"{output_prefix}_{output_padded}"
    job_index_for_balancing: int | None = None
    if output_prefix == "job" and str(output_padded).isdigit():
        job_index_for_balancing = int(output_padded)
    use_v2_global_schedule = (
        str(optimized_evaluation_mode) == "optimized_evaluation_v2"
        and bool(enable_cost_scheduling)
        and job_index_for_balancing is not None
    )
    if use_v2_global_schedule:
        candidates, balanced_total_jobs = _balanced_external_strategy_candidates_for_job(
            external_strategy_pack_path,
            job_index=int(job_index_for_balancing),
            candidate_count_per_job=external_strategy_limit,
            strategy_format=external_strategy_format,
        )
        print(
            "[gtbi] job "
            f"{output_padded} using optimized_evaluation_v2 balanced schedule "
            f"total_jobs={balanced_total_jobs} candidates={len(candidates)}",
            flush=True,
        )
    else:
        candidates = load_external_strategy_candidates(
            external_strategy_pack_path,
            shard_id=shard,
            offset=external_strategy_offset,
            limit=external_strategy_limit,
            strategy_format=external_strategy_format,
        )
    unsupported_rows: list[dict[str, Any]] = []
    if any(candidate.unsupported_rules for candidate in candidates):
        for candidate in candidates:
            if candidate.unsupported_rules:
                payload = candidate.payload
                unsupported_rows.append(
                    {
                        "strategy_id": payload.get("strategy_id"),
                        "shard_id": payload.get("shard_id"),
                        "slot_in_shard": payload.get("slot_in_shard"),
                        "unsupported_rules": ";".join(candidate.unsupported_rules),
                        "reason": "unsupported_or_missing_external_rule",
                    }
                )
        if external_strategy_fail_on_unsupported:
            pd.DataFrame(unsupported_rows).to_csv(output_dir / f"unsupported_strategies_{file_suffix}.csv", index=False)
            raise ValueError(f"{len(unsupported_rows)} unsupported external strategies in shard {shard_padded}")

    evaluable = [candidate for candidate in candidates if not candidate.unsupported_rules]
    if enable_cost_scheduling and not use_v2_global_schedule:
        evaluable = sorted(evaluable, key=lambda item: _estimated_cost_score(item.payload)[0])
    if prebuilt_pack_dir is None:
        pack_root = output_dir / "_external_pack_data"
        build_stage_packs(
            data_lake_root,
            pack_root,
            stage_count=1,
            group_count=1,
            locked_start=locked_start,
            min_rows=260,
            min_market_cap=min_market_cap,
        )
        pack_dir = pack_root / "stage-000"
    else:
        pack_dir = Path(prebuilt_pack_dir)
        missing = [name for name in ("prices.parquet", "benchmark.parquet") if not (pack_dir / name).exists()]
        if missing:
            raise FileNotFoundError(f"prebuilt external pack is missing: {', '.join(missing)}")
    symbol_frames = _load_symbol_frames(pack_dir / "prices.parquet")
    benchmark = _prepare_ohlcv(pd.read_parquet(pack_dir / "benchmark.parquet"))
    feature_store = build_feature_store(
        symbol_frames,
        benchmark,
        enabled=enable_feature_cache,
        prewarm=str(optimized_evaluation_mode) != "optimized_evaluation_v2",
    )
    print(
        "[gtbi] job "
        f"{output_padded} loaded {len(candidates)} candidates "
        f"({len(evaluable)} evaluable), symbols={len(symbol_frames)}, "
        f"feature_cache={bool(feature_store.enabled)}",
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    yearly_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    rules: list[dict[str, Any]] = []
    timeout_rows: list[dict[str, Any]] = []
    early_reject_rows: list[dict[str, Any]] = []
    runtime_error_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []
    dedupe_rows: list[dict[str, Any]] = []
    job_manifest_rows: list[dict[str, Any]] = []
    evaluation_cache: dict[str, tuple[str, dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any]]] = {}
    for candidate in candidates:
        if not candidate.unsupported_rules:
            continue
        payload = candidate.payload
        diagnostic = _external_diagnostic_base(payload, job_id=output_padded)
        timing_rows.append(
            {
                **diagnostic,
                "seconds_total": 0.0,
                "seconds_feature_build": 0.0,
                "seconds_signal": 0.0,
                "seconds_simulation": 0.0,
                "seconds_train": 0.0,
                "seconds_validation": 0.0,
                "symbols_total": int(len(symbol_frames)),
                "symbols_processed": 0,
                "raw_signals_total": 0,
                "trades_total": 0,
                "train_trades": 0,
                "validation_trades": 0,
                "result_status": "unsupported",
                "reject_reason": "unsupported_or_missing_external_rule",
                "timeout": False,
                "early_rejected": False,
                "runtime_error": False,
            }
        )

    for candidate in evaluable:
        payload = candidate.payload
        candidate_id = str(payload.get("strategy_id"))
        canonical_hash = canonical_external_strategy_hash(candidate)
        signal_hash = signal_external_strategy_hash(candidate)
        diagnostic_base = _external_diagnostic_base(payload, job_id=output_padded, canonical_hash=canonical_hash)
        cost_score, cost_bucket = _estimated_cost_score(payload)
        job_manifest_rows.append(
            {
                "job_id": output_padded,
                "strategy_id": candidate_id,
                "shard_id": payload.get("shard_id"),
                "slot_in_shard": payload.get("slot_in_shard"),
                "canonical_hash": canonical_hash,
                "signal_hash": signal_hash,
                "cost_score": float(cost_score),
                "estimated_cost_bucket": cost_bucket,
            }
        )
        candidate_start = time.perf_counter()
        if job_deadline is not None:
            remaining_job_seconds = float(job_deadline - candidate_start)
            if remaining_job_seconds <= JOB_WALL_CLOCK_SHUTDOWN_MARGIN_SECONDS:
                reason = "CandidateEvaluationTimeout('job wall clock budget exhausted before candidate start')"
                _append_external_timeout_result(
                    timeout_rows=timeout_rows,
                    dedupe_rows=dedupe_rows,
                    timing_rows=timing_rows,
                    diagnostic_base=diagnostic_base,
                    payload=payload,
                    candidate_id=candidate_id,
                    canonical_hash=canonical_hash,
                    signal_hash=signal_hash,
                    reason=reason,
                    seconds_total=max(0.0, float(time.perf_counter() - candidate_start)),
                    symbols_total=len(symbol_frames),
                    symbols_processed=0,
                )
                print(
                    "[gtbi] job "
                    f"{output_padded} deferred_timeout candidate={candidate_id} "
                    f"reason=job_wall_clock_budget_exhausted "
                    f"remaining_job_seconds={remaining_job_seconds:.2f}",
                    flush=True,
                )
                continue
        print(
            "[gtbi] job "
            f"{output_padded} start candidate={candidate_id} "
            f"concept={diagnostic_base.get('concept', '')} "
            f"exit={diagnostic_base.get('exit_rule', '')} "
            f"cost_bucket={cost_bucket}",
            flush=True,
        )
        try:
            cached = evaluation_cache.get(canonical_hash) if enable_dedupe else None
            deduped = cached is not None
            if not deduped:
                heartbeat_label = f"job={output_padded} candidate={candidate_id}"
                eval_kwargs = {
                    "config": candidate.config,
                    "candidate_id": candidate_id,
                    "stage": shard,
                    "symbol_frames": symbol_frames,
                    "benchmark_prices": benchmark,
                    "train_end": train_end,
                    "validation_start": validation_start,
                    "validation_end": validation_end,
                    "optimized_evaluation_mode": optimized_evaluation_mode,
                    "enable_safe_prefilter": enable_safe_prefilter,
                    "enable_early_stopping": enable_early_stopping,
                }
                candidate_deadlines: list[float] = []
                if candidate_timeout_seconds and float(candidate_timeout_seconds) > 0:
                    candidate_deadlines.append(time.perf_counter() + float(candidate_timeout_seconds))
                if job_deadline is not None:
                    job_safe_deadline = job_deadline - JOB_WALL_CLOCK_SHUTDOWN_MARGIN_SECONDS
                    if job_safe_deadline > time.perf_counter():
                        candidate_deadlines.append(job_safe_deadline)
                    else:
                        candidate_deadlines.append(time.perf_counter())
                eval_kwargs["deadline"] = min(candidate_deadlines) if candidate_deadlines else None
                with _candidate_evaluation_heartbeat(heartbeat_label):
                    row, trades, yearly, diagnostic = _evaluate_external_candidate_core(**eval_kwargs)
                evaluation_cache[canonical_hash] = (candidate_id, row.copy(), trades.copy(), yearly.copy(), dict(diagnostic))
                canonical_strategy_id = candidate_id
            else:
                canonical_strategy_id, row, trades, yearly, diagnostic = cached
                row = row.copy()
                trades = trades.copy()
                yearly = yearly.copy()
                diagnostic = dict(diagnostic)
                row["candidate_id"] = candidate_id
                if not trades.empty:
                    trades["candidate_id"] = candidate_id
                if not yearly.empty:
                    yearly["candidate_id"] = candidate_id
                diagnostic["seconds_total"] = float(time.perf_counter() - candidate_start)
                canonical_strategy_id = str(canonical_strategy_id)
            dedupe_rows.append(
                {
                    "strategy_id": candidate_id,
                    "canonical_hash": canonical_hash,
                    "canonical_strategy_id": canonical_strategy_id,
                    "deduped": bool(deduped),
                    "signal_hash": signal_hash,
                    "signal_canonical_strategy_id": canonical_strategy_id,
                    "signal_deduped": bool(deduped),
                }
            )
            print(
                "[gtbi] job "
                f"{output_padded} done candidate={candidate_id} "
                f"status={'deduped' if deduped else 'evaluated'} "
                f"seconds={time.perf_counter() - candidate_start:.2f}",
                flush=True,
            )
        except EarlyRejectedStrategy as exc:
            diagnostic = dict(exc.diagnostic)
            diagnostic.setdefault("seconds_total", float(time.perf_counter() - candidate_start))
            diagnostic.setdefault("seconds_feature_build", 0.0)
            diagnostic.setdefault("seconds_signal", float("nan"))
            diagnostic.setdefault("seconds_simulation", 0.0)
            diagnostic.setdefault("seconds_train", 0.0)
            diagnostic.setdefault("seconds_validation", 0.0)
            diagnostic.setdefault("symbols_total", int(len(symbol_frames)))
            diagnostic.setdefault("symbols_processed", int(exc.symbols_processed))
            diagnostic.setdefault("raw_signals_total", 0)
            diagnostic.setdefault("trades_total", 0)
            diagnostic.setdefault("train_trades", 0)
            diagnostic.setdefault("validation_trades", 0)
            early_reject_rows.append(
                {
                    "strategy_id": candidate_id,
                    "reason": exc.reason,
                    "split": exc.split,
                    "year": "" if exc.year is None else int(exc.year),
                    "actual": exc.actual,
                    "threshold": exc.threshold,
                    "stage": exc.stage,
                    "seconds_until_reject": exc.seconds_until_reject,
                    "symbols_processed": exc.symbols_processed,
                }
            )
            dedupe_rows.append(
                {
                    "strategy_id": candidate_id,
                    "canonical_hash": canonical_hash,
                    "canonical_strategy_id": "",
                    "deduped": False,
                    "signal_hash": signal_hash,
                    "signal_canonical_strategy_id": "",
                    "signal_deduped": False,
                }
            )
            timing_rows.append(
                {
                    **diagnostic_base,
                    **diagnostic,
                    "result_status": "early_rejected",
                    "reject_reason": exc.reason,
                    "timeout": False,
                    "early_rejected": True,
                    "runtime_error": False,
                }
            )
            print(
                "[gtbi] job "
                f"{output_padded} early_rejected candidate={candidate_id} "
                f"reason={exc.reason} seconds={time.perf_counter() - candidate_start:.2f}",
                flush=True,
            )
            continue
        except CandidateEvaluationTimeout as exc:
            seconds_total = float(time.perf_counter() - candidate_start)
            _append_external_timeout_result(
                timeout_rows=timeout_rows,
                dedupe_rows=dedupe_rows,
                timing_rows=timing_rows,
                diagnostic_base=diagnostic_base,
                payload=payload,
                candidate_id=candidate_id,
                canonical_hash=canonical_hash,
                signal_hash=signal_hash,
                reason=repr(exc),
                seconds_total=seconds_total,
                symbols_total=len(symbol_frames),
                symbols_processed=len(symbol_frames),
            )
            print(
                "[gtbi] job "
                f"{output_padded} timeout candidate={candidate_id} "
                f"seconds={seconds_total:.2f}",
                flush=True,
            )
            continue
        except Exception as exc:
            runtime_error_rows.append(
                {
                    "strategy_id": candidate_id,
                    "shard_id": payload.get("shard_id"),
                    "slot_in_shard": payload.get("slot_in_shard"),
                    "family": diagnostic_base.get("family", ""),
                    "concept": diagnostic_base.get("concept", ""),
                    "market_overlay": diagnostic_base.get("market_overlay", ""),
                    "trend_filter": diagnostic_base.get("trend_filter", ""),
                    "relative_strength_filter": diagnostic_base.get("relative_strength_filter", ""),
                    "exit_rule": diagnostic_base.get("exit_rule", ""),
                    "aggressiveness": diagnostic_base.get("aggressiveness", ""),
                    "reason": repr(exc),
                }
            )
            dedupe_rows.append(
                {
                    "strategy_id": candidate_id,
                    "canonical_hash": canonical_hash,
                    "canonical_strategy_id": "",
                    "deduped": False,
                    "signal_hash": signal_hash,
                    "signal_canonical_strategy_id": "",
                    "signal_deduped": False,
                }
            )
            timing_rows.append(
                {
                    **diagnostic_base,
                    "seconds_total": float(time.perf_counter() - candidate_start),
                    "seconds_feature_build": 0.0,
                    "seconds_signal": float("nan"),
                    "seconds_simulation": float("nan"),
                    "seconds_train": 0.0,
                    "seconds_validation": 0.0,
                    "symbols_total": int(len(symbol_frames)),
                    "symbols_processed": int(len(symbol_frames)),
                    "raw_signals_total": 0,
                    "trades_total": 0,
                    "train_trades": 0,
                    "validation_trades": 0,
                    "result_status": "runtime_error",
                    "reject_reason": repr(exc),
                    "timeout": False,
                    "early_rejected": False,
                    "runtime_error": True,
                }
            )
            print(
                "[gtbi] job "
                f"{output_padded} runtime_error candidate={candidate_id} "
                f"error={type(exc).__name__} seconds={time.perf_counter() - candidate_start:.2f}",
                flush=True,
            )
            continue
        row.update(_external_metadata(payload))
        rows.append(row)
        if not yearly.empty:
            yearly_frames.append(yearly)
        if not trades.empty:
            trade_frames.append(trades)
        diagnostic["seconds_feature_build"] = float(feature_store.seconds_build / max(len(evaluable), 1))
        timing_rows.append(
            {
                **diagnostic_base,
                **diagnostic,
                "result_status": "deduped" if deduped else "evaluated",
                "reject_reason": "",
                "timeout": False,
                "early_rejected": False,
                "runtime_error": False,
            }
        )
        rules.append(
            {
                "candidate_id": candidate_id,
                "strategy_id": candidate_id,
                "stage": shard,
                "search_method": EXTERNAL_SEARCH_METHOD,
                "selection_split": "validation",
                "scoring_profile": "strict_quality",
                "config": candidate.config.to_dict(),
                "external_strategy": payload,
                "approximated_rules": list(candidate.approximated_rules),
                "unsupported_rules": list(candidate.unsupported_rules),
                "score": row["score"],
            }
        )

    leaderboard = pd.DataFrame(rows)
    if leaderboard.empty:
        leaderboard = pd.DataFrame(columns=LEADERBOARD_COLUMNS)
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values(["score", "candidate_id"], ascending=[False, True]).reset_index(drop=True)
    filtered = pd.DataFrame(columns=leaderboard.columns)
    if not leaderboard.empty and "strict_quality_pass" in leaderboard.columns:
        filtered = leaderboard.loc[leaderboard["strict_quality_pass"].astype(bool)].copy()
        if not filtered.empty:
            filtered = filtered.sort_values(
                ["adjusted_return_time_risk", "validation_median_trade_return_pct", "candidate_id"],
                ascending=[False, False, True],
            )
    yearly_out = pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else pd.DataFrame(columns=YEARLY_COLUMNS)
    trades_out = pd.concat(trade_frames, ignore_index=True, sort=False) if trade_frames else pd.DataFrame(columns=TRADE_COLUMNS)
    unsupported = pd.DataFrame(unsupported_rows, columns=UNSUPPORTED_COLUMNS)
    timeouts = pd.DataFrame(timeout_rows, columns=TIMEOUT_COLUMNS)
    early_rejected = pd.DataFrame(early_reject_rows, columns=EARLY_REJECT_COLUMNS)
    runtime_errors = pd.DataFrame(runtime_error_rows, columns=RUNTIME_ERROR_COLUMNS)
    timing = pd.DataFrame(timing_rows, columns=TIMING_DIAGNOSTIC_COLUMNS)
    dedupe_map = pd.DataFrame(dedupe_rows, columns=DEDUPE_MAP_COLUMNS)
    job_manifest = pd.DataFrame(job_manifest_rows, columns=JOB_MANIFEST_COLUMNS)

    leaderboard.to_csv(output_dir / f"leaderboard_{file_suffix}.csv", index=False)
    filtered.to_csv(output_dir / f"filtered_leaderboard_{file_suffix}.csv", index=False)
    yearly_out.to_csv(output_dir / f"yearly_trade_performance_{file_suffix}.csv", index=False)
    trades_out.head(5000).to_csv(output_dir / f"top_trades_sample_{file_suffix}.csv", index=False)
    unsupported.to_csv(output_dir / f"unsupported_strategies_{file_suffix}.csv", index=False)
    timeouts.to_csv(output_dir / f"timeout_strategies_{file_suffix}.csv", index=False)
    early_rejected.to_csv(output_dir / f"early_rejected_strategies_{file_suffix}.csv", index=False)
    runtime_errors.to_csv(output_dir / f"runtime_errors_{file_suffix}.csv", index=False)
    timing.to_csv(output_dir / f"timing_diagnostics_{file_suffix}.csv", index=False)
    dedupe_map.to_csv(output_dir / f"dedupe_map_{file_suffix}.csv", index=False)
    job_manifest.to_csv(output_dir / f"job_manifest_{file_suffix}.csv", index=False)
    with (output_dir / f"top_indicator_rules_{file_suffix}.jsonl").open("w", encoding="utf-8") as handle:
        for rule in rules:
            handle.write(json.dumps(rule, sort_keys=True) + "\n")
    deduped_count = int(dedupe_map["deduped"].astype(str).str.lower().isin({"true", "1", "yes"}).sum()) if not dedupe_map.empty else 0
    summary = {
        "shard_id": shard,
        "base_shard_id": shard,
        "job_padded": output_padded if output_prefix == "job" else None,
        "chunk_index": int(external_strategy_offset) // max(int(external_strategy_limit), 1),
        "strategy_offset": int(external_strategy_offset),
        "strategy_limit": int(external_strategy_limit),
        "strategies_requested": int(external_strategy_limit),
        "strategies_loaded": int(len(candidates)),
        "strategies_evaluated": int(len(rows)),
        "strategies_early_rejected": int(len(early_rejected)),
        "strategies_unsupported": int(len(unsupported_rows)),
        "strategies_runtime_error": int(len(runtime_errors)),
        "strategies_failed": int(len(timeouts) + len(runtime_errors)),
        "strategies_timed_out": int(len(timeouts)),
        "strategies_deduped": int(deduped_count),
        "candidate_timeout_seconds": int(candidate_timeout_seconds),
        "job_wall_clock_seconds": int(job_wall_clock_seconds),
        "unique_config_evaluations": int(len(evaluation_cache)),
        "cached_config_reuses": int(deduped_count),
        "optimized_evaluation_mode": str(optimized_evaluation_mode),
        "enable_feature_cache": bool(enable_feature_cache),
        "enable_dedupe": bool(enable_dedupe),
        "enable_safe_prefilter": bool(enable_safe_prefilter),
        "enable_early_stopping": bool(enable_early_stopping),
        "enable_cost_scheduling": bool(enable_cost_scheduling),
        "seconds_feature_store_build": float(feature_store.seconds_build),
        "symbols": int(len(symbol_frames)),
        "locked_start": str(locked_start),
        "train_end": str(train_end),
        "validation_start": str(validation_start),
        "validation_end": str(validation_end),
        "github_only_run": True,
        "requires_local_machine": False,
        "locked_opened": False,
        "filtered_candidates": int(len(filtered)),
        "best_candidate_id": None if leaderboard.empty else str(leaderboard.iloc[0]["candidate_id"]),
        "best_filtered_candidate_id": None if filtered.empty else str(filtered.iloc[0]["candidate_id"]),
        "best_adjusted_return_time_risk": (
            None if leaderboard.empty else float(leaderboard.iloc[0].get("adjusted_return_time_risk", float("nan")))
        ),
    }
    (output_dir / f"summary_{file_suffix}.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def merge_external_strategy_pack_outputs(
    *,
    shards_root: Path,
    output_dir: Path,
    total_strategies_requested: int,
    total_shards_requested: int,
    total_jobs_requested: int | None = None,
    candidate_count_per_job: int | None = None,
    locked_start: str = DEFAULT_LOCKED_START,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
) -> dict[str, Any]:
    shards_root = Path(shards_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    leaderboards: list[pd.DataFrame] = []
    filtered_frames: list[pd.DataFrame] = []
    yearly_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    unsupported_frames: list[pd.DataFrame] = []
    timeout_frames: list[pd.DataFrame] = []
    early_rejected_frames: list[pd.DataFrame] = []
    runtime_error_frames: list[pd.DataFrame] = []
    timing_frames: list[pd.DataFrame] = []
    dedupe_frames: list[pd.DataFrame] = []
    job_manifest_frames: list[pd.DataFrame] = []
    rule_rows: list[dict[str, Any]] = []
    def read_csv_or_empty(path: Path) -> pd.DataFrame:
        if not path.stat().st_size:
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()

    for summary_path in sorted(
        [
            *shards_root.rglob("summary_shard_*.json"),
            *shards_root.rglob("summary_job_*.json"),
            *shards_root.rglob("summary.json"),
        ]
    ):
        summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
    for path in sorted([*shards_root.rglob("leaderboard_shard_*.csv"), *shards_root.rglob("leaderboard_job_*.csv"), *shards_root.rglob("leaderboard.csv")]):
        frame = read_csv_or_empty(path)
        if not frame.empty:
            leaderboards.append(frame)
    for path in sorted(
        [
            *shards_root.rglob("filtered_leaderboard_shard_*.csv"),
            *shards_root.rglob("filtered_leaderboard_job_*.csv"),
            *shards_root.rglob("filtered_leaderboard.csv"),
        ]
    ):
        frame = read_csv_or_empty(path)
        if not frame.empty:
            filtered_frames.append(frame)
    for path in sorted(
        [
            *shards_root.rglob("yearly_trade_performance_shard_*.csv"),
            *shards_root.rglob("yearly_trade_performance_job_*.csv"),
            *shards_root.rglob("yearly_trade_performance.csv"),
        ]
    ):
        frame = read_csv_or_empty(path)
        if not frame.empty:
            yearly_frames.append(frame)
    for path in sorted([*shards_root.rglob("top_trades_sample_shard_*.csv"), *shards_root.rglob("top_trades_sample_job_*.csv"), *shards_root.rglob("top_trades_sample.csv")]):
        frame = read_csv_or_empty(path)
        if not frame.empty:
            trade_frames.append(frame)
    for path in sorted(
        [
            *shards_root.rglob("unsupported_strategies_shard_*.csv"),
            *shards_root.rglob("unsupported_strategies_job_*.csv"),
            *shards_root.rglob("unsupported_strategies.csv"),
        ]
    ):
        frame = read_csv_or_empty(path)
        if not frame.empty:
            unsupported_frames.append(frame)
    for pattern, target in (
        ("timeout_strategies_shard_*.csv", timeout_frames),
        ("timeout_strategies_job_*.csv", timeout_frames),
        ("timeout_strategies.csv", timeout_frames),
        ("early_rejected_strategies_shard_*.csv", early_rejected_frames),
        ("early_rejected_strategies_job_*.csv", early_rejected_frames),
        ("early_rejected_strategies.csv", early_rejected_frames),
        ("runtime_errors_shard_*.csv", runtime_error_frames),
        ("runtime_errors_job_*.csv", runtime_error_frames),
        ("runtime_errors.csv", runtime_error_frames),
        ("timing_diagnostics_shard_*.csv", timing_frames),
        ("timing_diagnostics_job_*.csv", timing_frames),
        ("timing_diagnostics.csv", timing_frames),
        ("dedupe_map_shard_*.csv", dedupe_frames),
        ("dedupe_map_job_*.csv", dedupe_frames),
        ("dedupe_map.csv", dedupe_frames),
        ("job_manifest_shard_*.csv", job_manifest_frames),
        ("job_manifest_job_*.csv", job_manifest_frames),
        ("job_manifest.csv", job_manifest_frames),
    ):
        for path in sorted(shards_root.rglob(pattern)):
            frame = read_csv_or_empty(path)
            if not frame.empty:
                target.append(frame)
    for path in sorted(
        [
            *shards_root.rglob("top_indicator_rules_shard_*.jsonl"),
            *shards_root.rglob("top_indicator_rules_job_*.jsonl"),
            *shards_root.rglob("top_indicator_rules.jsonl"),
        ]
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rule_rows.append(json.loads(line))

    leaderboard = pd.concat(leaderboards, ignore_index=True, sort=False) if leaderboards else pd.DataFrame(columns=LEADERBOARD_COLUMNS)
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values(["score", "candidate_id"], ascending=[False, True]).reset_index(drop=True)
    filtered = pd.concat(filtered_frames, ignore_index=True, sort=False) if filtered_frames else pd.DataFrame(columns=leaderboard.columns)
    if not filtered.empty:
        filtered = filtered.sort_values(
            ["adjusted_return_time_risk", "validation_median_trade_return_pct", "candidate_id"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
    yearly = pd.concat(yearly_frames, ignore_index=True, sort=False) if yearly_frames else pd.DataFrame(columns=YEARLY_COLUMNS)
    trades = pd.concat(trade_frames, ignore_index=True, sort=False) if trade_frames else pd.DataFrame(columns=TRADE_COLUMNS)
    unsupported = (
        pd.concat(unsupported_frames, ignore_index=True, sort=False)
        if unsupported_frames
        else pd.DataFrame(columns=UNSUPPORTED_COLUMNS)
    )
    timeouts = pd.concat(timeout_frames, ignore_index=True, sort=False) if timeout_frames else pd.DataFrame(columns=TIMEOUT_COLUMNS)
    early_rejected = (
        pd.concat(early_rejected_frames, ignore_index=True, sort=False)
        if early_rejected_frames
        else pd.DataFrame(columns=EARLY_REJECT_COLUMNS)
    )
    runtime_errors = (
        pd.concat(runtime_error_frames, ignore_index=True, sort=False)
        if runtime_error_frames
        else pd.DataFrame(columns=RUNTIME_ERROR_COLUMNS)
    )
    timing = pd.concat(timing_frames, ignore_index=True, sort=False) if timing_frames else pd.DataFrame(columns=TIMING_DIAGNOSTIC_COLUMNS)
    dedupe_map = pd.concat(dedupe_frames, ignore_index=True, sort=False) if dedupe_frames else pd.DataFrame(columns=DEDUPE_MAP_COLUMNS)
    job_manifest = (
        pd.concat(job_manifest_frames, ignore_index=True, sort=False)
        if job_manifest_frames
        else pd.DataFrame(columns=JOB_MANIFEST_COLUMNS)
    )

    leaderboard.to_csv(output_dir / "leaderboard.csv", index=False)
    filtered.to_csv(output_dir / "filtered_leaderboard.csv", index=False)
    yearly.to_csv(output_dir / "yearly_trade_performance.csv", index=False)
    trades.to_csv(output_dir / "top_trades_sample.csv", index=False)
    unsupported.to_csv(output_dir / "unsupported_strategies.csv", index=False)
    timeouts.to_csv(output_dir / "timeout_strategies.csv", index=False)
    early_rejected.to_csv(output_dir / "early_rejected_strategies.csv", index=False)
    runtime_errors.to_csv(output_dir / "runtime_errors.csv", index=False)
    timing.to_csv(output_dir / "timing_diagnostics.csv", index=False)
    dedupe_map.to_csv(output_dir / "dedupe_map.csv", index=False)
    job_manifest.to_csv(output_dir / "job_manifest.csv", index=False)
    with (output_dir / "top_indicator_rules.jsonl").open("w", encoding="utf-8") as handle:
        for row in sorted(rule_rows, key=lambda item: str(item.get("candidate_id", ""))):
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def summary_by(column: str) -> pd.DataFrame:
        if leaderboard.empty or column not in leaderboard.columns:
            return pd.DataFrame(columns=[column, "candidates", "best_score", "avg_score", "filtered_candidates"])
        filtered_ids = set(filtered["candidate_id"].astype(str)) if not filtered.empty and "candidate_id" in filtered.columns else set()
        grouped = (
            leaderboard.assign(_filtered=leaderboard["candidate_id"].astype(str).isin(filtered_ids).astype(int))
            .groupby(column, dropna=False)
            .agg(
                candidates=("candidate_id", "count"),
                best_score=("score", "max"),
                avg_score=("score", "mean"),
                filtered_candidates=("_filtered", "sum"),
            )
            .reset_index()
            .sort_values(["best_score", column], ascending=[False, True])
        )
        return grouped

    summary_by("family").to_csv(output_dir / "family_summary.csv", index=False)
    summary_by("concept_id").to_csv(output_dir / "concept_summary.csv", index=False)
    summary_by("market_overlay_id").to_csv(output_dir / "market_overlay_summary.csv", index=False)

    best_adjusted = None
    if not leaderboard.empty and "adjusted_return_time_risk" in leaderboard.columns:
        best_adjusted = _finite_float(leaderboard.iloc[0].get("adjusted_return_time_risk"), default=float("nan"))
        best_adjusted = None if not math.isfinite(best_adjusted) else float(best_adjusted)
    jobs_requested = int(total_jobs_requested) if total_jobs_requested is not None else int(total_shards_requested)
    inferred_candidate_count = None
    if candidate_count_per_job is not None:
        inferred_candidate_count = int(candidate_count_per_job)
    elif jobs_requested > 0:
        inferred_candidate_count = int(total_strategies_requested) // jobs_requested
    def sum_summary(*keys: str) -> int:
        total = 0
        for item in summaries:
            for key in keys:
                if key in item and item.get(key) is not None:
                    total += int(item.get(key, 0))
                    break
        return int(total)

    completed_jobs = sum_summary("total_jobs_completed")
    if completed_jobs == 0:
        completed_jobs = int(len(summaries))
    completed_shards = sum_summary("total_shards_completed")
    if completed_shards == 0:
        completed_shards = int(len(summaries))
    timed_out_total = sum_summary("strategies_timed_out", "total_strategies_timed_out")
    runtime_error_total = sum_summary("strategies_runtime_error", "total_strategies_runtime_error")
    failed_total = sum_summary("strategies_failed", "total_strategies_failed")
    if failed_total == 0:
        failed_total = int(timed_out_total + runtime_error_total)
    summary = {
        "total_strategies_requested": int(total_strategies_requested),
        "total_strategies_loaded": sum_summary("strategies_loaded", "total_strategies_loaded"),
        "total_strategies_evaluated": sum_summary("strategies_evaluated", "total_strategies_evaluated"),
        "total_strategies_early_rejected": sum_summary("strategies_early_rejected", "total_strategies_early_rejected"),
        "total_strategies_unsupported": sum_summary("strategies_unsupported", "total_strategies_unsupported"),
        "total_strategies_runtime_error": int(runtime_error_total),
        "total_strategies_failed": int(failed_total),
        "total_strategies_timed_out": int(timed_out_total),
        "total_strategies_deduped": sum_summary("strategies_deduped", "total_strategies_deduped"),
        "total_shards_requested": int(total_shards_requested),
        "total_shards_completed": int(completed_shards),
        "total_jobs_requested": jobs_requested,
        "total_jobs_completed": int(completed_jobs),
        "total_jobs_failed": int(max(jobs_requested - completed_jobs, 0)),
        "candidate_count_per_job": inferred_candidate_count,
        "candidate_timeout_seconds": None if not summaries else int(next((item.get("candidate_timeout_seconds") for item in summaries if item.get("candidate_timeout_seconds") is not None), 0)),
        "optimized_evaluation_mode": next((str(item.get("optimized_evaluation_mode")) for item in summaries if item.get("optimized_evaluation_mode")), "legacy"),
        "filtered_candidates": int(len(filtered)),
        "best_candidate_id": None if leaderboard.empty else str(leaderboard.iloc[0]["candidate_id"]),
        "best_filtered_candidate_id": None if filtered.empty else str(filtered.iloc[0]["candidate_id"]),
        "best_adjusted_return_time_risk": best_adjusted,
        "locked_start": str(locked_start),
        "train_end": str(train_end),
        "validation_start": str(validation_start),
        "validation_end": str(validation_end),
        "github_only_run": True,
        "requires_local_machine": False,
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
    parser.add_argument("--seed-rules-path", type=Path, default=None)
    parser.add_argument("--seed-mutation-share", type=float, default=0.65)
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
        seed_rules_path=args.seed_rules_path,
        seed_mutation_share=args.seed_mutation_share,
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


def reevaluate_global_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-evaluate merged indicator candidates on the full filtered universe.")
    parser.add_argument("--merged-dir", type=Path, required=True)
    parser.add_argument("--data-lake-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=200)
    parser.add_argument("--candidate-offset", type=int, default=0)
    parser.add_argument("--min-market-cap", type=float, default=0.0)
    parser.add_argument("--locked-start", default=DEFAULT_LOCKED_START)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--validation-start", default=DEFAULT_VALIDATION_START)
    parser.add_argument("--validation-end", default=DEFAULT_VALIDATION_END)
    parser.add_argument("--scoring-profile", choices=SCORING_PROFILES, default="strict_quality")
    args = parser.parse_args(argv)
    summary = reevaluate_global_candidates(
        merged_dir=args.merged_dir,
        data_lake_root=args.data_lake_root,
        output_dir=args.output_dir,
        candidate_limit=args.candidate_limit,
        candidate_offset=args.candidate_offset,
        min_market_cap=args.min_market_cap,
        locked_start=args.locked_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        scoring_profile=args.scoring_profile,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def run_external_strategy_pack_shard_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one external GTBI strategy-pack shard.")
    parser.add_argument("--data-lake-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prebuilt-pack-dir", type=Path, default=None)
    parser.add_argument("--external-strategy-pack-path", type=Path, default=DEFAULT_EXTERNAL_STRATEGY_PACK_PATH)
    parser.add_argument("--external-strategy-shard-id", type=int, required=True)
    parser.add_argument("--external-strategy-offset", type=int, default=0)
    parser.add_argument("--external-strategy-limit", type=int, default=200)
    parser.add_argument("--external-strategy-format", choices=("auto", "jsonl", "csv"), default="auto")
    parser.add_argument("--external-strategy-fail-on-unsupported", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--candidate-timeout-seconds", type=int, default=DEFAULT_EXTERNAL_CANDIDATE_TIMEOUT_SECONDS)
    parser.add_argument("--job-wall-clock-seconds", type=int, default=300)
    parser.add_argument("--optimized-evaluation-mode", default="optimized_evaluation_v2")
    parser.add_argument("--enable-feature-cache", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-dedupe", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-safe-prefilter", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-early-stopping", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-cost-scheduling", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-market-cap", type=float, default=2_000_000_000)
    parser.add_argument("--locked-start", default=DEFAULT_LOCKED_START)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--validation-start", default=DEFAULT_VALIDATION_START)
    parser.add_argument("--validation-end", default=DEFAULT_VALIDATION_END)
    args = parser.parse_args(argv)
    summary = run_external_strategy_pack_shard(
        data_lake_root=args.data_lake_root,
        external_strategy_pack_path=args.external_strategy_pack_path,
        output_dir=args.output_dir,
        prebuilt_pack_dir=args.prebuilt_pack_dir,
        external_strategy_shard_id=args.external_strategy_shard_id,
        external_strategy_offset=args.external_strategy_offset,
        external_strategy_limit=args.external_strategy_limit,
        external_strategy_format=args.external_strategy_format,
        external_strategy_fail_on_unsupported=args.external_strategy_fail_on_unsupported,
        candidate_timeout_seconds=args.candidate_timeout_seconds,
        job_wall_clock_seconds=args.job_wall_clock_seconds,
        min_market_cap=args.min_market_cap,
        locked_start=args.locked_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        optimized_evaluation_mode=args.optimized_evaluation_mode,
        enable_feature_cache=args.enable_feature_cache,
        enable_dedupe=args.enable_dedupe,
        enable_safe_prefilter=args.enable_safe_prefilter,
        enable_early_stopping=args.enable_early_stopping,
        enable_cost_scheduling=args.enable_cost_scheduling,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def merge_external_strategy_pack_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge external GTBI strategy-pack shard outputs.")
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--total-strategies-requested", type=int, required=True)
    parser.add_argument("--total-shards-requested", type=int, required=True)
    parser.add_argument("--total-jobs-requested", type=int, default=None)
    parser.add_argument("--candidate-count-per-job", type=int, default=None)
    parser.add_argument("--locked-start", default=DEFAULT_LOCKED_START)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--validation-start", default=DEFAULT_VALIDATION_START)
    parser.add_argument("--validation-end", default=DEFAULT_VALIDATION_END)
    args = parser.parse_args(argv)
    summary = merge_external_strategy_pack_outputs(
        shards_root=args.shards_root,
        output_dir=args.output_dir,
        total_strategies_requested=args.total_strategies_requested,
        total_shards_requested=args.total_shards_requested,
        total_jobs_requested=args.total_jobs_requested,
        candidate_count_per_job=args.candidate_count_per_job,
        locked_start=args.locked_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0

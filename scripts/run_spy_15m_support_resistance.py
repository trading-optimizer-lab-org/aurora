from __future__ import annotations

import sys
from pathlib import Path as _AuroraPolicyPath

_AURORA_POLICY_ROOT = _AuroraPolicyPath(__file__).resolve().parents[1]
if str(_AURORA_POLICY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AURORA_POLICY_ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission

import argparse
import json
import math
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning
import yfinance as yf


CAMPAIGN_ID = "spy_15m_support_resistance_355jobs"
INTERVAL = "15m"
BARS_PER_DAY = 26
BARS_PER_YEAR = 252 * BARS_PER_DAY
DEFAULT_PERIOD = "60d"
DEFAULT_TARGET_BARS = 4
DEFAULT_TARGET_SHARPE = 1.50

warnings.simplefilter("ignore", PerformanceWarning)


def main() -> None:
    require_github_actions_or_explicit_local_permission("SPY 15m support/resistance run")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--period", default=DEFAULT_PERIOD)
    parser.add_argument("--interval", choices=[INTERVAL], default=INTERVAL)
    parser.add_argument("--target-bars", type=int, default=DEFAULT_TARGET_BARS)
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=15_000)
    parser.add_argument("--time-budget-minutes", type=float, default=12.0)
    parser.add_argument("--top-per-stage", type=int, default=100)
    parser.add_argument("--target-sharpe", type=float, default=DEFAULT_TARGET_SHARPE)
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--validation-fraction", type=float, default=0.30)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(
            output_dir,
            period=str(args.period),
            interval=str(args.interval),
            target_bars=int(args.target_bars),
        )
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            configs_per_stage=int(args.configs_per_stage),
            time_budget_minutes=float(args.time_budget_minutes),
            top_per_stage=int(args.top_per_stage),
            target_sharpe=float(args.target_sharpe),
            cost_bps=float(args.cost_bps),
            validation_fraction=float(args.validation_fraction),
        )
    else:
        run_merge(output_dir, target_sharpe=float(args.target_sharpe))


def run_data(output_dir: Path, *, period: str, interval: str, target_bars: int) -> None:
    raw = yf.download(
        "SPY",
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        prepost=False,
        threads=False,
        timeout=30,
    )
    bars = normalise_yfinance_ohlcv(raw)
    if len(bars) < 300:
        raise RuntimeError(f"Insufficient SPY {interval} bars: {len(bars)}")
    if target_bars <= 0:
        raise ValueError("target_bars must be positive")

    panel = build_feature_frame(bars, target_bars=target_bars)
    if len(panel) < 200:
        raise RuntimeError(f"Insufficient feature rows after warmup: {len(panel)}")

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bars.to_csv(data_dir / "spy_15m_ohlcv.csv", index_label="timestamp")
    panel.to_csv(data_dir / "spy_15m_sr_feature_panel.csv", index_label="timestamp")

    feature_cols = [c for c in panel.columns if c not in {"target_return", "target_direction"}]
    families = feature_families(feature_cols)
    audit = {
        "symbol": "SPY",
        "interval": interval,
        "period": period,
        "target_bars": int(target_bars),
        "target_horizon_minutes": int(target_bars * 15),
        "rows_raw": int(len(bars)),
        "rows_panel": int(len(panel)),
        "first_timestamp": str(panel.index.min()),
        "last_timestamp": str(panel.index.max()),
        "feature_count": int(len(feature_cols)),
        "feature_families": {name: int(len(cols)) for name, cols in families.items()},
        "feature_policy": "support_resistance_only_all_features_known_at_bar_close",
        "selection_policy": "train_only_threshold_selection_validation_diagnostic",
    }
    (data_dir / "feature_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")


def normalise_yfinance_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        raise RuntimeError("yfinance returned no SPY data")
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        if "SPY" in frame.columns.get_level_values(0):
            frame = frame["SPY"]
        else:
            frame.columns = frame.columns.get_level_values(-1)
    rename = {c: str(c).strip().title() for c in frame.columns}
    frame = frame.rename(columns=rename)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise RuntimeError(f"SPY OHLCV missing columns: {missing}")
    out = frame[required].copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_convert("America/New_York").tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    out = out[out["Volume"] > 0]
    return out.astype(float)


def build_feature_frame(bars: pd.DataFrame, *, target_bars: int = DEFAULT_TARGET_BARS) -> pd.DataFrame:
    bars = bars[["Open", "High", "Low", "Close", "Volume"]].copy()
    bars = bars.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    open_ = bars["Open"]
    high = bars["High"]
    low = bars["Low"]
    close = bars["Close"]
    volume = bars["Volume"]
    true_range = pd.concat(
        [(high - low), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr_14 = true_range.rolling(14, min_periods=5).mean()
    atr_52 = true_range.rolling(52, min_periods=10).mean()
    atr_pct_14 = atr_14 / close.replace(0.0, np.nan)

    data = pd.DataFrame(index=bars.index)
    add_candle_features(data, open_, high, low, close, volume, atr_14)
    add_rolling_level_features(data, high, low, close, atr_14)
    add_session_features(data, bars, atr_14)
    add_pivot_features(data, bars, atr_14)
    add_opening_range_features(data, bars, atr_14)
    add_vwap_features(data, bars, atr_14)
    add_volume_profile_features(data, bars)
    add_fibonacci_features(data, high, low, close)
    add_round_number_features(data, close, atr_14)
    add_dynamic_band_features(data, close, high, low, atr_14, atr_52)
    add_fractal_pivot_features(data, high, low, close, atr_14)
    add_gap_features(data, bars, atr_14)

    near_threshold = atr_pct_14.fillna(0.0025).clip(lower=0.001, upper=0.01)
    support_like = [c for c in data.columns if any(token in c for token in ("low", "support", "s1", "s2", "lower", "val", "floor"))]
    resistance_like = [c for c in data.columns if any(token in c for token in ("high", "resistance", "r1", "r2", "upper", "vah", "ceil"))]
    data["sr_confluence_support_count"] = confluence_count(data, support_like, near_threshold)
    data["sr_confluence_resistance_count"] = confluence_count(data, resistance_like, near_threshold)
    data["sr_confluence_balance"] = data["sr_confluence_support_count"] - data["sr_confluence_resistance_count"]

    target_return = close.shift(-target_bars) / close.replace(0.0, np.nan) - 1.0
    data["target_return"] = target_return
    data["target_direction"] = np.sign(target_return)
    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=["target_return", "target_direction"])
    return data


def add_candle_features(
    data: pd.DataFrame,
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    atr: pd.Series,
) -> None:
    candle_range = (high - low).replace(0.0, np.nan)
    body = (close - open_).abs()
    data["sr_candle_close_location"] = (close - low) / candle_range
    data["sr_candle_body_pct"] = body / candle_range
    data["sr_candle_upper_wick_pct"] = (high - pd.concat([open_, close], axis=1).max(axis=1)) / candle_range
    data["sr_candle_lower_wick_pct"] = (pd.concat([open_, close], axis=1).min(axis=1) - low) / candle_range
    data["sr_candle_range_atr"] = (high - low) / atr.replace(0.0, np.nan)
    data["sr_candle_volume_z_52"] = zscore(volume, 52)
    data["sr_candle_inside_bar"] = ((high < high.shift(1)) & (low > low.shift(1))).astype(float)
    data["sr_candle_outside_bar"] = ((high > high.shift(1)) & (low < low.shift(1))).astype(float)


def add_rolling_level_features(
    data: pd.DataFrame,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr: pd.Series,
) -> None:
    for window in [4, 8, 16, 26, 52, 78, 130, 260]:
        prior_high = high.rolling(window, min_periods=max(3, window // 3)).max().shift(1)
        prior_low = low.rolling(window, min_periods=max(3, window // 3)).min().shift(1)
        channel = (prior_high - prior_low).replace(0.0, np.nan)
        mid = (prior_high + prior_low) / 2.0
        data[f"sr_roll_dist_prior_high_{window}b"] = close / prior_high.replace(0.0, np.nan) - 1.0
        data[f"sr_roll_dist_prior_low_{window}b"] = close / prior_low.replace(0.0, np.nan) - 1.0
        data[f"sr_roll_dist_mid_{window}b"] = close / mid.replace(0.0, np.nan) - 1.0
        data[f"sr_roll_dist_high_atr_{window}b"] = (close - prior_high) / atr.replace(0.0, np.nan)
        data[f"sr_roll_dist_low_atr_{window}b"] = (close - prior_low) / atr.replace(0.0, np.nan)
        data[f"sr_roll_donchian_position_{window}b"] = (close - prior_low) / channel
        data[f"sr_roll_donchian_width_{window}b"] = channel / close.replace(0.0, np.nan)
        data[f"sr_roll_breakout_up_{window}b"] = (close > prior_high).astype(float)
        data[f"sr_roll_breakout_down_{window}b"] = (close < prior_low).astype(float)
        data[f"sr_roll_failed_breakout_{window}b"] = ((high > prior_high) & (close <= prior_high)).astype(float)
        data[f"sr_roll_failed_breakdown_{window}b"] = ((low < prior_low) & (close >= prior_low)).astype(float)
        data[f"sr_roll_resistance_touches_{window}b"] = rolling_touch_pct(high, prior_high, window)
        data[f"sr_roll_support_touches_{window}b"] = rolling_touch_pct(low, prior_low, window)
        data[f"sr_roll_bars_since_high_{window}b"] = rolling_extreme_age(high, window, use_max=True)
        data[f"sr_roll_bars_since_low_{window}b"] = rolling_extreme_age(low, window, use_max=False)


def add_session_features(data: pd.DataFrame, bars: pd.DataFrame, atr: pd.Series) -> None:
    dates = pd.Series(bars.index.normalize(), index=bars.index)
    high = bars["High"]
    low = bars["Low"]
    close = bars["Close"]
    open_ = bars["Open"]
    session_high = high.groupby(dates).cummax()
    session_low = low.groupby(dates).cummin()
    session_open = open_.groupby(dates).transform("first")
    bar_index = high.groupby(dates).cumcount()
    data["sr_session_bar_index"] = bar_index.astype(float)
    data["sr_session_dist_high"] = close / session_high.replace(0.0, np.nan) - 1.0
    data["sr_session_dist_low"] = close / session_low.replace(0.0, np.nan) - 1.0
    data["sr_session_dist_open"] = close / session_open.replace(0.0, np.nan) - 1.0
    data["sr_session_range_position"] = (close - session_low) / (session_high - session_low).replace(0.0, np.nan)
    data["sr_session_high_rejection_atr"] = (session_high - close) / atr.replace(0.0, np.nan)
    data["sr_session_low_rejection_atr"] = (close - session_low) / atr.replace(0.0, np.nan)


def add_pivot_features(data: pd.DataFrame, bars: pd.DataFrame, atr: pd.Series) -> None:
    daily = bars.groupby(bars.index.normalize()).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
    )
    prev = daily.shift(1).reindex(bars.index.normalize())
    prev.index = bars.index
    close = bars["Close"]
    pp = (prev["High"] + prev["Low"] + prev["Close"]) / 3.0
    r1 = 2.0 * pp - prev["Low"]
    s1 = 2.0 * pp - prev["High"]
    r2 = pp + (prev["High"] - prev["Low"])
    s2 = pp - (prev["High"] - prev["Low"])
    r3 = prev["High"] + 2.0 * (pp - prev["Low"])
    s3 = prev["Low"] - 2.0 * (prev["High"] - pp)
    bc = (prev["High"] + prev["Low"]) / 2.0
    tc = 2.0 * pp - bc
    levels = {
        "pivot_pp": pp,
        "pivot_r1": r1,
        "pivot_s1": s1,
        "pivot_r2": r2,
        "pivot_s2": s2,
        "pivot_r3": r3,
        "pivot_s3": s3,
        "pivot_cpr_top": pd.concat([bc, tc], axis=1).max(axis=1),
        "pivot_cpr_bottom": pd.concat([bc, tc], axis=1).min(axis=1),
    }
    for name, level in levels.items():
        data[f"sr_{name}_gap"] = close / level.replace(0.0, np.nan) - 1.0
        data[f"sr_{name}_gap_atr"] = (close - level) / atr.replace(0.0, np.nan)
    data["sr_pivot_cpr_width"] = (tc - bc).abs() / close.replace(0.0, np.nan)
    data["sr_prev_day_high_gap"] = close / prev["High"].replace(0.0, np.nan) - 1.0
    data["sr_prev_day_low_gap"] = close / prev["Low"].replace(0.0, np.nan) - 1.0
    data["sr_prev_day_close_gap"] = close / prev["Close"].replace(0.0, np.nan) - 1.0


def add_opening_range_features(data: pd.DataFrame, bars: pd.DataFrame, atr: pd.Series) -> None:
    dates = pd.Series(bars.index.normalize(), index=bars.index)
    close = bars["Close"]
    for bars_count in [2, 4, 8]:
        high_level = opening_range_level(bars["High"], dates, bars_count, use_max=True)
        low_level = opening_range_level(bars["Low"], dates, bars_count, use_max=False)
        mid = (high_level + low_level) / 2.0
        data[f"sr_opening_range_high_gap_{bars_count}b"] = close / high_level.replace(0.0, np.nan) - 1.0
        data[f"sr_opening_range_low_gap_{bars_count}b"] = close / low_level.replace(0.0, np.nan) - 1.0
        data[f"sr_opening_range_mid_gap_{bars_count}b"] = close / mid.replace(0.0, np.nan) - 1.0
        data[f"sr_opening_range_break_up_{bars_count}b"] = (close > high_level).astype(float)
        data[f"sr_opening_range_break_down_{bars_count}b"] = (close < low_level).astype(float)
        data[f"sr_opening_range_width_atr_{bars_count}b"] = (high_level - low_level) / atr.replace(0.0, np.nan)


def add_vwap_features(data: pd.DataFrame, bars: pd.DataFrame, atr: pd.Series) -> None:
    dates = pd.Series(bars.index.normalize(), index=bars.index)
    typical = (bars["High"] + bars["Low"] + bars["Close"]) / 3.0
    pv = typical * bars["Volume"]
    session_vwap = pv.groupby(dates).cumsum() / bars["Volume"].groupby(dates).cumsum().replace(0.0, np.nan)
    close = bars["Close"]
    data["sr_vwap_session_gap"] = close / session_vwap.replace(0.0, np.nan) - 1.0
    data["sr_vwap_session_gap_atr"] = (close - session_vwap) / atr.replace(0.0, np.nan)
    for window in [20, 52, 130]:
        rolling_vwap = (typical * bars["Volume"]).rolling(window, min_periods=max(5, window // 4)).sum()
        rolling_vwap = rolling_vwap / bars["Volume"].rolling(window, min_periods=max(5, window // 4)).sum().replace(0.0, np.nan)
        dev = (typical - rolling_vwap).rolling(window, min_periods=max(5, window // 4)).std()
        data[f"sr_vwap_roll_gap_{window}b"] = close / rolling_vwap.replace(0.0, np.nan) - 1.0
        data[f"sr_vwap_roll_upper_gap_{window}b"] = close / (rolling_vwap + dev).replace(0.0, np.nan) - 1.0
        data[f"sr_vwap_roll_lower_gap_{window}b"] = close / (rolling_vwap - dev).replace(0.0, np.nan) - 1.0


def add_volume_profile_features(data: pd.DataFrame, bars: pd.DataFrame) -> None:
    close = bars["Close"]
    for window in [26, 78, 130]:
        levels = rolling_volume_profile_levels(bars, window=window, bins=24)
        data[f"sr_volume_profile_poc_gap_{window}b"] = close / levels["poc"].replace(0.0, np.nan) - 1.0
        data[f"sr_volume_profile_vah_gap_{window}b"] = close / levels["vah"].replace(0.0, np.nan) - 1.0
        data[f"sr_volume_profile_val_gap_{window}b"] = close / levels["val"].replace(0.0, np.nan) - 1.0
        data[f"sr_volume_profile_value_area_pos_{window}b"] = (
            (close - levels["val"]) / (levels["vah"] - levels["val"]).replace(0.0, np.nan)
        )


def add_fibonacci_features(data: pd.DataFrame, high: pd.Series, low: pd.Series, close: pd.Series) -> None:
    for window in [26, 52, 130, 260]:
        rolling_high = high.rolling(window, min_periods=max(10, window // 3)).max().shift(1)
        rolling_low = low.rolling(window, min_periods=max(10, window // 3)).min().shift(1)
        span = rolling_high - rolling_low
        data[f"sr_fib_range_width_{window}b"] = span / close.replace(0.0, np.nan)
        for ratio in [0.236, 0.382, 0.5, 0.618, 0.786]:
            level = rolling_high - span * ratio
            label = str(ratio).replace(".", "")
            data[f"sr_fib_{label}_gap_{window}b"] = close / level.replace(0.0, np.nan) - 1.0


def add_round_number_features(data: pd.DataFrame, close: pd.Series, atr: pd.Series) -> None:
    for step in [0.5, 1.0, 5.0, 10.0]:
        nearest = (close / step).round() * step
        floor = np.floor(close / step) * step
        ceil = np.ceil(close / step) * step
        label = str(step).replace(".", "p")
        data[f"sr_round_nearest_gap_{label}"] = close / nearest.replace(0.0, np.nan) - 1.0
        data[f"sr_round_floor_gap_{label}"] = close / pd.Series(floor, index=close.index).replace(0.0, np.nan) - 1.0
        data[f"sr_round_ceil_gap_{label}"] = close / pd.Series(ceil, index=close.index).replace(0.0, np.nan) - 1.0
        data[f"sr_round_nearest_gap_atr_{label}"] = (close - nearest) / atr.replace(0.0, np.nan)


def add_dynamic_band_features(
    data: pd.DataFrame,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    atr_14: pd.Series,
    atr_52: pd.Series,
) -> None:
    for window in [20, 52, 130]:
        sma = close.rolling(window, min_periods=max(5, window // 4)).mean()
        ema = close.ewm(span=window, adjust=False, min_periods=max(5, window // 4)).mean()
        std = close.rolling(window, min_periods=max(5, window // 4)).std()
        upper = sma + 2.0 * std
        lower = sma - 2.0 * std
        k_upper = ema + 1.5 * atr_14
        k_lower = ema - 1.5 * atr_14
        data[f"sr_band_sma_gap_{window}b"] = close / sma.replace(0.0, np.nan) - 1.0
        data[f"sr_band_ema_gap_{window}b"] = close / ema.replace(0.0, np.nan) - 1.0
        data[f"sr_band_bollinger_upper_gap_{window}b"] = close / upper.replace(0.0, np.nan) - 1.0
        data[f"sr_band_bollinger_lower_gap_{window}b"] = close / lower.replace(0.0, np.nan) - 1.0
        data[f"sr_band_bollinger_width_{window}b"] = (upper - lower) / sma.replace(0.0, np.nan)
        data[f"sr_band_keltner_upper_gap_{window}b"] = close / k_upper.replace(0.0, np.nan) - 1.0
        data[f"sr_band_keltner_lower_gap_{window}b"] = close / k_lower.replace(0.0, np.nan) - 1.0
        data[f"sr_band_atr_compression_{window}b"] = atr_14 / atr_52.replace(0.0, np.nan)
        channel = rolling_regression_channel(close, window)
        data[f"sr_trendline_mid_gap_{window}b"] = close / channel["mid"].replace(0.0, np.nan) - 1.0
        data[f"sr_trendline_upper_gap_{window}b"] = close / channel["upper"].replace(0.0, np.nan) - 1.0
        data[f"sr_trendline_lower_gap_{window}b"] = close / channel["lower"].replace(0.0, np.nan) - 1.0
        data[f"sr_trendline_slope_{window}b"] = channel["slope"]


def add_fractal_pivot_features(
    data: pd.DataFrame,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr: pd.Series,
) -> None:
    for left_right in [2, 3, 5]:
        pivots = last_confirmed_pivots(high, low, left=left_right, right=left_right)
        ph = pivots["pivot_high"]
        pl = pivots["pivot_low"]
        data[f"sr_fractal_pivot_high_gap_{left_right}b"] = close / ph.replace(0.0, np.nan) - 1.0
        data[f"sr_fractal_pivot_low_gap_{left_right}b"] = close / pl.replace(0.0, np.nan) - 1.0
        data[f"sr_fractal_pivot_high_gap_atr_{left_right}b"] = (close - ph) / atr.replace(0.0, np.nan)
        data[f"sr_fractal_pivot_low_gap_atr_{left_right}b"] = (close - pl) / atr.replace(0.0, np.nan)
        data[f"sr_fractal_pivot_high_age_{left_right}b"] = pivots["pivot_high_age"]
        data[f"sr_fractal_pivot_low_age_{left_right}b"] = pivots["pivot_low_age"]


def add_gap_features(data: pd.DataFrame, bars: pd.DataFrame, atr: pd.Series) -> None:
    dates = pd.Series(bars.index.normalize(), index=bars.index)
    bar_index = bars["Close"].groupby(dates).cumcount()
    prev_close = bars["Close"].shift(1)
    session_first = bar_index == 0
    gap = (bars["Open"] / prev_close.replace(0.0, np.nan) - 1.0).where(session_first)
    gap_level_upper = pd.concat([bars["Open"], prev_close], axis=1).max(axis=1).where(session_first).groupby(dates).ffill()
    gap_level_lower = pd.concat([bars["Open"], prev_close], axis=1).min(axis=1).where(session_first).groupby(dates).ffill()
    data["sr_gap_open_vs_prev_close"] = gap.groupby(dates).ffill()
    data["sr_gap_upper_gap"] = bars["Close"] / gap_level_upper.replace(0.0, np.nan) - 1.0
    data["sr_gap_lower_gap"] = bars["Close"] / gap_level_lower.replace(0.0, np.nan) - 1.0
    data["sr_gap_size_atr"] = ((bars["Open"] - prev_close) / atr.replace(0.0, np.nan)).where(session_first).groupby(dates).ffill()
    data["sr_gap_filled"] = ((bars["Low"] <= gap_level_lower) & (bars["High"] >= gap_level_upper)).astype(float)


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
    target_sharpe: float,
    cost_bps: float,
    validation_fraction: float,
) -> None:
    panel = pd.read_csv(output_dir / "data" / "spy_15m_sr_feature_panel.csv", parse_dates=["timestamp"]).set_index("timestamp")
    audit_path = output_dir / "data" / "feature_audit.json"
    target_bars = DEFAULT_TARGET_BARS
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        target_bars = int(audit.get("target_bars", DEFAULT_TARGET_BARS))
    feature_cols = [c for c in panel.columns if c not in {"target_return", "target_direction"}]
    if not feature_cols:
        raise RuntimeError("No support/resistance features found")
    matrix, target, train_mask, validation_mask = prepare_matrix(panel, feature_cols, validation_fraction=validation_fraction)

    rng = np.random.default_rng(10_000 + int(stage))
    deadline = time.monotonic() + max(0.1, time_budget_minutes) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    while evaluated < configs_per_stage and time.monotonic() < deadline:
        params = sample_params(rng, feature_cols, stage=stage, config_index=evaluated)
        score = build_score(matrix, params)
        candidate = evaluate_candidate(
            score,
            target,
            train_mask,
            validation_mask,
            params,
            feature_cols,
            cost_bps=cost_bps,
            target_sharpe=target_sharpe,
            target_bars=target_bars,
        )
        rows.append(candidate)
        if len(rows) > top_per_stage * 8:
            rows = select_top(rows, top_per_stage * 4)
        evaluated += 1

    top = select_top(rows, top_per_stage)
    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(top).to_csv(shard_dir / "top_candidates.csv", index=False)
    summary = {
        "stage": int(stage),
        "configs_requested": int(configs_per_stage),
        "configs_evaluated": int(evaluated),
        "top_rows": int(len(top)),
        "target_sharpe": float(target_sharpe),
        "cost_bps": float(cost_bps),
        "validation_fraction": float(validation_fraction),
        "target_bars": int(target_bars),
    }
    (shard_dir / "shard_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def prepare_matrix(
    panel: pd.DataFrame,
    feature_cols: list[str],
    *,
    validation_fraction: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    work = panel.replace([np.inf, -np.inf], np.nan).copy()
    n = len(work)
    if n < 200:
        raise RuntimeError(f"Not enough rows for train/validation split: {n}")
    split = int(n * (1.0 - validation_fraction))
    split = max(80, min(n - 40, split))
    train_mask = np.zeros(n, dtype=bool)
    train_mask[:split] = True
    validation_mask = ~train_mask
    x = work[feature_cols]
    med = x.iloc[:split].median(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    filled = x.fillna(med).fillna(0.0)
    mean = filled.iloc[:split].mean()
    std = filled.iloc[:split].std().replace(0.0, np.nan).fillna(1.0)
    z = ((filled - mean) / std).clip(-8.0, 8.0).fillna(0.0)
    target = work["target_return"].fillna(0.0).to_numpy(dtype=float)
    return z.to_numpy(dtype=float), target, train_mask, validation_mask


def sample_params(
    rng: np.random.Generator,
    feature_cols: list[str],
    *,
    stage: int,
    config_index: int,
) -> dict[str, Any]:
    families = feature_families(feature_cols)
    family_names = [name for name, cols in families.items() if cols]
    focus = family_names[stage % len(family_names)] if family_names else "all"
    pool = families.get(focus, list(range(len(feature_cols))))
    if config_index % 5 == 0:
        pool = list(range(len(feature_cols)))
        focus = "all"
    max_features = min(len(pool), int(rng.integers(2, 9)))
    feature_indices = sorted(rng.choice(pool, size=max_features, replace=False).astype(int).tolist())
    rule_type = str(rng.choice(["linear", "threshold_vote", "single_feature", "pair_spread", "mean_reversion"]))
    weights = rng.normal(0.0, 1.0, len(feature_indices)).tolist()
    thresholds = rng.normal(0.0, 0.9, len(feature_indices)).tolist()
    return {
        "rule_type": rule_type,
        "focus_family": focus,
        "feature_indices": feature_indices,
        "weights": weights,
        "thresholds": thresholds,
        "config_index": int(config_index),
        "stage": int(stage),
    }


def build_score(matrix: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = [int(i) for i in params["feature_indices"]]
    x = matrix[:, idx]
    rule_type = str(params["rule_type"])
    weights = np.asarray(params["weights"], dtype=float)[: len(idx)]
    thresholds = np.asarray(params["thresholds"], dtype=float)[: len(idx)]
    if rule_type == "threshold_vote":
        return ((x > thresholds).astype(float) * np.sign(weights)).sum(axis=1)
    if rule_type == "single_feature":
        selected = int(abs(weights[0]) * 997) % len(idx)
        return x[:, selected] * float(np.sign(weights[selected]) or 1.0)
    if rule_type == "pair_spread" and len(idx) >= 2:
        return x[:, 0] * float(np.sign(weights[0]) or 1.0) - x[:, 1] * float(np.sign(weights[1]) or 1.0)
    if rule_type == "mean_reversion":
        return -(x * weights).sum(axis=1)
    norm = np.sum(np.abs(weights)) or 1.0
    return (x * weights).sum(axis=1) / norm


def evaluate_candidate(
    score: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
    validation_mask: np.ndarray,
    params: dict[str, Any],
    feature_cols: list[str],
    *,
    cost_bps: float,
    target_sharpe: float,
    target_bars: int,
) -> dict[str, Any]:
    threshold, side_policy, invert, train_metrics = choose_policy_train_only(
        score,
        target,
        train_mask,
        cost_bps=cost_bps,
        target_bars=target_bars,
    )
    oriented = -score if invert else score
    positions = positions_from_score(oriented, threshold, side_policy)
    validation_metrics = metrics(positions[validation_mask], target[validation_mask], cost_bps=cost_bps, target_bars=target_bars)
    selected_features = [feature_cols[i] for i in params["feature_indices"]]
    families = sorted({feature_family_for_name(name) for name in selected_features})
    accepted = (
        train_metrics["sharpe"] >= target_sharpe
        and validation_metrics["sharpe"] >= target_sharpe
        and train_metrics["trades"] >= 8
        and validation_metrics["trades"] >= 3
    )
    return {
        "strategy_id": f"sr15m_s{int(params['stage']):03d}_{int(params['config_index']):06d}",
        "accepted": bool(accepted),
        "score": float(validation_metrics["sharpe"] + 0.25 * train_metrics["sharpe"]),
        "train_sharpe": float(train_metrics["sharpe"]),
        "validation_sharpe": float(validation_metrics["sharpe"]),
        "train_profit_factor": float(train_metrics["profit_factor"]),
        "validation_profit_factor": float(validation_metrics["profit_factor"]),
        "train_hit_rate": float(train_metrics["hit_rate"]),
        "validation_hit_rate": float(validation_metrics["hit_rate"]),
        "train_max_drawdown": float(train_metrics["max_drawdown"]),
        "validation_max_drawdown": float(validation_metrics["max_drawdown"]),
        "train_trades": int(train_metrics["trades"]),
        "validation_trades": int(validation_metrics["trades"]),
        "train_exposure": float(train_metrics["exposure"]),
        "validation_exposure": float(validation_metrics["exposure"]),
        "threshold": float(threshold),
        "side_policy": side_policy,
        "invert": int(invert),
        "rule_type": str(params["rule_type"]),
        "focus_family": str(params["focus_family"]),
        "families": "|".join(families),
        "features": "|".join(selected_features),
        "params_json": json.dumps(params, sort_keys=True),
    }


def choose_policy_train_only(
    score: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
    *,
    cost_bps: float,
    target_bars: int,
) -> tuple[float, str, int, dict[str, float]]:
    train_score = score[train_mask]
    if len(train_score) == 0 or np.nanstd(train_score) == 0.0:
        return 0.0, "long_short", 0, metrics(
            np.ones_like(target[train_mask]),
            target[train_mask],
            cost_bps=cost_bps,
            target_bars=target_bars,
        )
    quantiles = np.unique(np.nanquantile(train_score, [0.15, 0.25, 0.35, 0.50, 0.65, 0.75, 0.85]))
    best: tuple[float, str, int, dict[str, float]] | None = None
    best_score = -float("inf")
    for invert in [0, 1]:
        oriented = -score if invert else score
        for threshold in quantiles:
            for policy in ["long_short", "long_flat", "short_flat"]:
                pos = positions_from_score(oriented, float(threshold), policy)
                out = metrics(pos[train_mask], target[train_mask], cost_bps=cost_bps, target_bars=target_bars)
                objective = out["sharpe"] + 0.15 * math.log1p(max(out["trades"], 0.0)) - 0.25 * abs(out["exposure"] - 0.65)
                if objective > best_score:
                    best_score = objective
                    best = (float(threshold), policy, invert, out)
    assert best is not None
    return best


def positions_from_score(score: np.ndarray, threshold: float, policy: str) -> np.ndarray:
    if policy == "long_flat":
        return np.where(score >= threshold, 1.0, 0.0)
    if policy == "short_flat":
        return np.where(score <= threshold, -1.0, 0.0)
    return np.where(score >= threshold, 1.0, -1.0)


def metrics(positions: np.ndarray, returns: np.ndarray, *, cost_bps: float, target_bars: int) -> dict[str, float]:
    if len(positions) == 0:
        return empty_metrics()
    positions = np.asarray(positions, dtype=float)
    returns = np.asarray(returns, dtype=float)
    turnover = np.abs(np.diff(np.r_[0.0, positions]))
    net = positions * returns - turnover * (cost_bps / 10_000.0)
    active = np.abs(positions) > 0.0
    if np.nanstd(net) > 0.0:
        sharpe = float(np.nanmean(net) / np.nanstd(net) * math.sqrt(BARS_PER_YEAR / max(1, target_bars)))
    else:
        sharpe = 0.0
    gains = net[net > 0.0].sum()
    losses = net[net < 0.0].sum()
    equity = np.cumprod(1.0 + np.nan_to_num(net, nan=0.0))
    peak = np.maximum.accumulate(equity) if len(equity) else np.asarray([1.0])
    drawdown = equity / np.where(peak == 0.0, 1.0, peak) - 1.0
    return {
        "sharpe": sharpe,
        "profit_factor": float(gains / abs(losses)) if losses < 0.0 else float("inf") if gains > 0.0 else 0.0,
        "hit_rate": float(np.mean(net[active] > 0.0)) if np.any(active) else 0.0,
        "max_drawdown": float(np.nanmin(drawdown)) if len(drawdown) else 0.0,
        "trades": float(np.sum(turnover > 0.0)),
        "exposure": float(np.mean(active)),
        "mean_return": float(np.nanmean(net)),
    }


def empty_metrics() -> dict[str, float]:
    return {
        "sharpe": 0.0,
        "profit_factor": 0.0,
        "hit_rate": 0.0,
        "max_drawdown": 0.0,
        "trades": 0.0,
        "exposure": 0.0,
        "mean_return": 0.0,
    }


def select_top(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (bool(row.get("accepted")), float(row.get("score", 0.0))), reverse=True)[:limit]


def run_merge(output_dir: Path, *, target_sharpe: float) -> None:
    files = list((output_dir / "shards").glob("**/top_candidates.csv"))
    frames = []
    for path in files:
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if not frame.empty:
            frames.append(frame)
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    if not frames:
        pd.DataFrame().to_csv(final_dir / "leaderboard.csv", index=False)
        (final_dir / "summary.json").write_text(json.dumps({"rows": 0, "target_sharpe": target_sharpe}, indent=2), encoding="utf-8")
        return
    data = pd.concat(frames, ignore_index=True)
    data = data.sort_values(["accepted", "score", "validation_sharpe", "train_sharpe"], ascending=[False, False, False, False])
    data.to_csv(final_dir / "leaderboard.csv", index=False)
    accepted = data[data["accepted"].astype(bool)].copy()
    accepted.to_csv(final_dir / "accepted.csv", index=False)
    family_rows = []
    for family in sorted({part for value in data.get("families", pd.Series(dtype=str)).fillna("") for part in str(value).split("|") if part}):
        subset = data[data["families"].fillna("").astype(str).str.contains(family, regex=False)]
        family_rows.append(
            {
                "family": family,
                "rows": int(len(subset)),
                "accepted": int(subset["accepted"].astype(bool).sum()) if "accepted" in subset else 0,
                "best_validation_sharpe": float(pd.to_numeric(subset["validation_sharpe"], errors="coerce").max()),
                "best_train_sharpe": float(pd.to_numeric(subset["train_sharpe"], errors="coerce").max()),
            }
        )
    pd.DataFrame(family_rows).to_csv(final_dir / "family_summary.csv", index=False)
    summary = {
        "rows": int(len(data)),
        "accepted": int(len(accepted)),
        "target_sharpe": float(target_sharpe),
        "best_validation_sharpe": float(pd.to_numeric(data["validation_sharpe"], errors="coerce").max()),
        "best_train_sharpe": float(pd.to_numeric(data["train_sharpe"], errors="coerce").max()),
        "best_strategy_id": str(data.iloc[0]["strategy_id"]) if len(data) else "",
    }
    (final_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def feature_families(feature_cols: list[str]) -> dict[str, list[int]]:
    families = {
        "rolling_levels": [],
        "pivots": [],
        "opening_range": [],
        "vwap": [],
        "volume_profile": [],
        "fibonacci": [],
        "round_numbers": [],
        "dynamic_bands": [],
        "fractal_pivots": [],
        "gaps": [],
        "candles": [],
        "session": [],
        "confluence": [],
    }
    for i, name in enumerate(feature_cols):
        families[feature_family_for_name(name)].append(i)
    return families


def feature_family_for_name(name: str) -> str:
    if "roll_" in name:
        return "rolling_levels"
    if "pivot_" in name and "fractal" not in name:
        return "pivots"
    if "opening_range" in name:
        return "opening_range"
    if "vwap" in name:
        return "vwap"
    if "volume_profile" in name:
        return "volume_profile"
    if "fib_" in name:
        return "fibonacci"
    if "round_" in name:
        return "round_numbers"
    if "band_" in name or "trendline_" in name:
        return "dynamic_bands"
    if "fractal_" in name:
        return "fractal_pivots"
    if "gap_" in name:
        return "gaps"
    if "candle_" in name:
        return "candles"
    if "session_" in name:
        return "session"
    if "confluence_" in name:
        return "confluence"
    return "rolling_levels"


def zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window, min_periods=max(5, window // 4)).mean()
    std = series.rolling(window, min_periods=max(5, window // 4)).std()
    return (series - mean) / std.replace(0.0, np.nan)


def rolling_touch_pct(series: pd.Series, level: pd.Series, window: int) -> pd.Series:
    tolerance = (series.rolling(window, min_periods=max(3, window // 3)).std() / series.replace(0.0, np.nan)).fillna(0.0025)
    touched = ((series / level.replace(0.0, np.nan) - 1.0).abs() <= tolerance).astype(float)
    return touched.rolling(window, min_periods=max(3, window // 3)).mean().shift(1)


def rolling_extreme_age(series: pd.Series, window: int, *, use_max: bool) -> pd.Series:
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(window - 1, len(values)):
        chunk = values[i - window + 1 : i + 1]
        if np.isnan(chunk).all():
            continue
        pos = int(np.nanargmax(chunk) if use_max else np.nanargmin(chunk))
        out[i] = len(chunk) - 1 - pos
    return pd.Series(out, index=series.index).shift(1)


def opening_range_level(series: pd.Series, dates: pd.Series, bars_count: int, *, use_max: bool) -> pd.Series:
    out = pd.Series(np.nan, index=series.index, dtype=float)
    for _, idx in dates.groupby(dates).groups.items():
        group = series.loc[idx]
        if len(group) < bars_count:
            continue
        level = group.iloc[:bars_count].max() if use_max else group.iloc[:bars_count].min()
        out.loc[group.index[bars_count - 1 :]] = float(level)
    return out


def rolling_volume_profile_levels(bars: pd.DataFrame, *, window: int, bins: int) -> pd.DataFrame:
    typical = ((bars["High"] + bars["Low"] + bars["Close"]) / 3.0).to_numpy(dtype=float)
    lows = bars["Low"].to_numpy(dtype=float)
    highs = bars["High"].to_numpy(dtype=float)
    volumes = bars["Volume"].to_numpy(dtype=float)
    poc = np.full(len(bars), np.nan)
    vah = np.full(len(bars), np.nan)
    val = np.full(len(bars), np.nan)
    for i in range(window - 1, len(bars)):
        lo = float(np.nanmin(lows[i - window + 1 : i + 1]))
        hi = float(np.nanmax(highs[i - window + 1 : i + 1]))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            continue
        edges = np.linspace(lo, hi, bins + 1)
        centers = (edges[:-1] + edges[1:]) / 2.0
        bin_idx = np.clip(np.digitize(typical[i - window + 1 : i + 1], edges) - 1, 0, bins - 1)
        hist = np.zeros(bins, dtype=float)
        np.add.at(hist, bin_idx, volumes[i - window + 1 : i + 1])
        if hist.sum() <= 0.0:
            continue
        poc_bin = int(np.argmax(hist))
        order = np.argsort(hist)[::-1]
        selected = []
        total = 0.0
        for idx in order:
            selected.append(int(idx))
            total += float(hist[idx])
            if total >= hist.sum() * 0.70:
                break
        poc[i] = centers[poc_bin]
        val[i] = centers[min(selected)]
        vah[i] = centers[max(selected)]
    return pd.DataFrame({"poc": poc, "vah": vah, "val": val}, index=bars.index)


def rolling_regression_channel(close: pd.Series, window: int) -> pd.DataFrame:
    values = close.to_numpy(dtype=float)
    mid = np.full(len(values), np.nan)
    upper = np.full(len(values), np.nan)
    lower = np.full(len(values), np.nan)
    slope = np.full(len(values), np.nan)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    denom = float(((x - x_mean) ** 2).sum())
    for i in range(window - 1, len(values)):
        y = values[i - window + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = float(y.mean())
        b = float(((x - x_mean) * (y - y_mean)).sum() / denom)
        a = y_mean - b * x_mean
        fit = a + b * x
        resid_std = float(np.std(y - fit))
        mid[i] = fit[-1]
        upper[i] = fit[-1] + 2.0 * resid_std
        lower[i] = fit[-1] - 2.0 * resid_std
        slope[i] = b / values[i] if values[i] else np.nan
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "slope": slope}, index=close.index)


def last_confirmed_pivots(high: pd.Series, low: pd.Series, *, left: int, right: int) -> pd.DataFrame:
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    pivot_high = np.full(len(h), np.nan)
    pivot_low = np.full(len(l), np.nan)
    high_age = np.full(len(h), np.nan)
    low_age = np.full(len(l), np.nan)
    last_h = np.nan
    last_l = np.nan
    last_h_idx = -1
    last_l_idx = -1
    for i in range(left + right, len(h)):
        candidate = i - right
        h_window = h[candidate - left : candidate + right + 1]
        l_window = l[candidate - left : candidate + right + 1]
        if np.isfinite(h[candidate]) and h[candidate] >= np.nanmax(h_window):
            last_h = h[candidate]
            last_h_idx = candidate
        if np.isfinite(l[candidate]) and l[candidate] <= np.nanmin(l_window):
            last_l = l[candidate]
            last_l_idx = candidate
        pivot_high[i] = last_h
        pivot_low[i] = last_l
        high_age[i] = i - last_h_idx if last_h_idx >= 0 else np.nan
        low_age[i] = i - last_l_idx if last_l_idx >= 0 else np.nan
    return pd.DataFrame(
        {
            "pivot_high": pivot_high,
            "pivot_low": pivot_low,
            "pivot_high_age": high_age,
            "pivot_low_age": low_age,
        },
        index=high.index,
    )


def confluence_count(data: pd.DataFrame, columns: list[str], threshold: pd.Series) -> pd.Series:
    gap_cols = [c for c in columns if c in data and ("gap" in c or "dist" in c)]
    if not gap_cols:
        return pd.Series(0.0, index=data.index)
    hits = [(data[c].abs() <= threshold).astype(float) for c in gap_cols[:80]]
    return pd.concat(hits, axis=1).sum(axis=1)


if __name__ == "__main__":
    main()

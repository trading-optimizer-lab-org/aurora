from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from core.execution_policy import require_github_actions_or_explicit_local_permission
except ModuleNotFoundError:

    def require_github_actions_or_explicit_local_permission(reason: str | None = None) -> None:
        import os

        if os.environ.get("GITHUB_ACTIONS") == "true":
            return
        if os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
            return
        detail = f" for {reason}" if reason else ""
        raise RuntimeError(
            "Local research runs are blocked"
            f"{detail}; run in GitHub Actions or set explicit local override."
        )


CAMPAIGN_ID = "spy_weekly_noleverage_50ideas_v2_nightly_until_0700"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
PPY = 52
ALLOWED_POSITIONS = {-1.0, 0.0, 1.0}

warnings.simplefilter("ignore", PerformanceWarning)


IDEA_SPECS: list[dict[str, Any]] = [
    {"idea_id": "weekly_return_autocorr_regime", "idea_family": "autocorr", "patterns": ["autocorr"]},
    {"idea_id": "weekly_negative_autocorr_reversal", "idea_family": "autocorr", "patterns": ["negative_autocorr", "autocorr"]},
    {"idea_id": "weekly_positive_autocorr_followthrough", "idea_family": "autocorr", "patterns": ["positive_autocorr", "autocorr"]},
    {"idea_id": "weekly_realized_skew_reversal", "idea_family": "distribution_shape", "patterns": ["realized_skew"]},
    {"idea_id": "weekly_realized_kurtosis_cash_filter", "idea_family": "distribution_shape", "patterns": ["realized_kurtosis"]},
    {"idea_id": "weekly_upside_downside_vol_balance", "idea_family": "semivariance", "patterns": ["upside_downside_vol", "upside_vol", "downside_vol"]},
    {"idea_id": "weekly_semivariance_risk_off", "idea_family": "semivariance", "patterns": ["semivariance", "downside_vol"]},
    {"idea_id": "weekly_ulcer_index_recovery", "idea_family": "path_dependence", "patterns": ["ulcer_index", "drawdown_duration"]},
    {"idea_id": "weekly_return_entropy_breakout", "idea_family": "entropy", "patterns": ["return_entropy"]},
    {"idea_id": "weekly_low_entropy_trend_follow", "idea_family": "entropy", "patterns": ["low_entropy", "return_entropy"]},
    {"idea_id": "weekly_high_entropy_cash", "idea_family": "entropy", "patterns": ["high_entropy", "return_entropy"]},
    {"idea_id": "weekly_sign_pattern_4w_motif", "idea_family": "motif", "patterns": ["sign_pattern_4w"]},
    {"idea_id": "weekly_sign_pattern_6w_motif", "idea_family": "motif", "patterns": ["sign_pattern_6w"]},
    {"idea_id": "weekly_alternating_weeks_reversal", "idea_family": "motif", "patterns": ["alternating_weeks"]},
    {"idea_id": "weekly_streak_age_exhaustion", "idea_family": "streak", "patterns": ["streak_age", "streak_exhaustion"]},
    {"idea_id": "weekly_streak_age_continuation", "idea_family": "streak", "patterns": ["streak_age", "streak_continuation"]},
    {"idea_id": "weekly_acceleration_jerk_turn", "idea_family": "derivative", "patterns": ["acceleration", "jerk"]},
    {"idea_id": "weekly_second_derivative_trend", "idea_family": "derivative", "patterns": ["second_derivative", "acceleration"]},
    {"idea_id": "weekly_vol_of_vol_regime", "idea_family": "vol_stability", "patterns": ["vol_of_vol"]},
    {"idea_id": "weekly_vol_of_vol_collapse_risk_on", "idea_family": "vol_stability", "patterns": ["vol_of_vol_collapse"]},
    {"idea_id": "weekly_realized_beta_to_qqq_shift", "idea_family": "beta_shift", "patterns": ["qqq_beta"]},
    {"idea_id": "weekly_realized_beta_to_iwm_shift", "idea_family": "beta_shift", "patterns": ["iwm_beta"]},
    {"idea_id": "weekly_tlt_beta_instability", "idea_family": "beta_shift", "patterns": ["tlt_beta"]},
    {"idea_id": "weekly_credit_beta_instability", "idea_family": "beta_shift", "patterns": ["credit_beta", "hyg_beta"]},
    {"idea_id": "weekly_vix_beta_instability", "idea_family": "beta_shift", "patterns": ["vix_beta"]},
    {"idea_id": "weekly_correlation_spy_tlt_flip", "idea_family": "correlation_flip", "patterns": ["spy_tlt_corr", "corr_flip"]},
    {"idea_id": "weekly_correlation_spy_hyg_flip", "idea_family": "correlation_flip", "patterns": ["spy_hyg_corr", "corr_flip"]},
    {"idea_id": "weekly_correlation_spy_qqq_compression", "idea_family": "correlation_flip", "patterns": ["spy_qqq_corr", "corr_compression"]},
    {"idea_id": "weekly_correlation_spy_iwm_divergence", "idea_family": "correlation_flip", "patterns": ["spy_iwm_corr", "corr_divergence"]},
    {"idea_id": "weekly_sector_dispersion_expansion", "idea_family": "dispersion", "patterns": ["sector_dispersion_expansion", "sector_dispersion"]},
    {"idea_id": "weekly_sector_dispersion_compression", "idea_family": "dispersion", "patterns": ["sector_dispersion_compression", "sector_dispersion"]},
    {"idea_id": "weekly_sector_lead_lag_rotation", "idea_family": "rotation", "patterns": ["sector_lead_lag", "sector_rotation"]},
    {"idea_id": "weekly_defensive_cyclical_spread_turn", "idea_family": "rotation", "patterns": ["defensive_cyclical_spread"]},
    {"idea_id": "weekly_growth_value_proxy_rotation", "idea_family": "rotation", "patterns": ["growth_value_proxy"]},
    {"idea_id": "weekly_large_small_proxy_rotation", "idea_family": "rotation", "patterns": ["large_small_proxy"]},
    {"idea_id": "weekly_global_us_spread_mean_revert", "idea_family": "global_spread", "patterns": ["global_us_spread"]},
    {"idea_id": "weekly_em_dm_spread_risk_filter", "idea_family": "global_spread", "patterns": ["em_dm_spread"]},
    {"idea_id": "weekly_asia_us_gap_followthrough", "idea_family": "global_spread", "patterns": ["asia_us_gap"]},
    {"idea_id": "weekly_europe_us_gap_followthrough", "idea_family": "global_spread", "patterns": ["europe_us_gap"]},
    {"idea_id": "weekly_fx_equity_correlation_stress", "idea_family": "macro_correlation", "patterns": ["fx_equity_corr"]},
    {"idea_id": "weekly_rates_equity_correlation_flip", "idea_family": "macro_correlation", "patterns": ["rates_equity_corr"]},
    {"idea_id": "weekly_credit_equity_confirmation_lag", "idea_family": "macro_correlation", "patterns": ["credit_equity_lag"]},
    {"idea_id": "weekly_multi_asset_disagreement_cash", "idea_family": "agreement", "patterns": ["multi_asset_disagreement"]},
    {"idea_id": "weekly_multi_asset_agreement_trend", "idea_family": "agreement", "patterns": ["multi_asset_agreement"]},
    {"idea_id": "weekly_drawdown_duration_recovery", "idea_family": "path_dependence", "patterns": ["drawdown_duration"]},
    {"idea_id": "weekly_drawdown_duration_failure", "idea_family": "path_dependence", "patterns": ["drawdown_duration", "drawdown_failure"]},
    {"idea_id": "weekly_time_since_high_regime", "idea_family": "path_dependence", "patterns": ["time_since_high"]},
    {"idea_id": "weekly_time_since_low_reversal", "idea_family": "path_dependence", "patterns": ["time_since_low"]},
    {"idea_id": "weekly_prior_locked_like_stress_pattern", "idea_family": "stress_pattern", "patterns": ["prior_stress_pattern", "stress_cluster"]},
    {"idea_id": "weekly_regime_transition_vote", "idea_family": "transition", "patterns": ["regime_transition", "transition_vote"]},
]


def main() -> None:
    require_github_actions_or_explicit_local_permission("SPY weekly no-leverage 50 ideas v2 nightly")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=25_000)
    parser.add_argument("--time-budget-minutes", type=float, default=24.0)
    parser.add_argument("--top-per-stage", type=int, default=150)
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--locked-retest-top-n", type=int, default=5_000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            configs_per_stage=int(args.configs_per_stage),
            time_budget_minutes=float(args.time_budget_minutes),
            top_per_stage=int(args.top_per_stage),
            cost_bps=float(args.cost_bps),
        )
    else:
        final_merge(output_dir, locked_retest_top_n=int(args.locked_retest_top_n), cost_bps=float(args.cost_bps))


def run_data(output_dir: Path) -> None:
    cache_dir = output_dir / ".yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))
    weekly = download_weekly_market_data()
    if weekly.empty or "SPY_CLOSE" not in weekly:
        raise RuntimeError("SPY weekly data unavailable")
    panel = build_weekly_panel(weekly)
    if panel.empty:
        raise RuntimeError("SPY weekly feature panel is empty")
    if panel.index.max() < LOCKED_START + pd.Timedelta(days=365):
        raise RuntimeError("Locked period is too short for final retest")

    no_locked = panel.loc[panel.index < LOCKED_START].copy()
    if no_locked.index.max() >= LOCKED_START:
        raise RuntimeError("No-locked panel leaked locked rows")

    no_locked.to_csv(output_dir / "weekly_panel_no_locked.csv", index_label="timestamp")
    panel.to_csv(output_dir / "weekly_panel_all.csv", index_label="timestamp")
    feature_cols = feature_columns(panel)
    pd.DataFrame(IDEA_SPECS).to_csv(output_dir / "idea_catalog.csv", index=False)
    (output_dir / "position_policy_audit.json").write_text(
        json.dumps(base_policy_audit() | {"feature_count": len(feature_cols), "rows_all": len(panel), "rows_no_locked": len(no_locked)}, indent=2),
        encoding="utf-8",
    )


def download_weekly_market_data() -> pd.DataFrame:
    symbols = [
        "SPY", "^VIX", "^VIX3M", "^TNX", "^IRX", "DX-Y.NYB", "TLT", "LQD", "HYG",
        "QQQ", "IWM", "DIA", "XLY", "XLP", "XLK", "XLU", "XLF", "XLE", "XLV", "XLI", "XLB",
        "EFA", "EEM", "^N225", "^HSI", "^FTSE", "^GDAXI", "^FCHI",
    ]
    raw = yf.download(
        symbols,
        start="1994-01-01",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
        timeout=45,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    close = pd.DataFrame()
    spy_ohlcv = pd.DataFrame()
    for symbol in symbols:
        try:
            frame = raw[symbol] if isinstance(raw.columns, pd.MultiIndex) else raw
        except Exception:
            continue
        if "Close" not in frame:
            continue
        close[symbol] = frame["Close"]
        if symbol == "SPY":
            spy_ohlcv = frame[["Open", "High", "Low", "Close", "Volume"]].rename(
                columns={name: f"SPY_{name.upper()}" for name in ["Open", "High", "Low", "Close", "Volume"]}
            )
    if "SPY" not in close:
        raise RuntimeError("SPY close missing")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    spy_ohlcv.index = pd.to_datetime(spy_ohlcv.index).tz_localize(None)
    weekly_ohlcv = pd.DataFrame(
        {
            "SPY_OPEN": spy_ohlcv["SPY_OPEN"].resample("W-FRI").first(),
            "SPY_HIGH": spy_ohlcv["SPY_HIGH"].resample("W-FRI").max(),
            "SPY_LOW": spy_ohlcv["SPY_LOW"].resample("W-FRI").min(),
            "SPY_CLOSE": spy_ohlcv["SPY_CLOSE"].resample("W-FRI").last(),
            "SPY_VOLUME": spy_ohlcv["SPY_VOLUME"].resample("W-FRI").sum(),
        }
    )
    weekly_close = close.resample("W-FRI").last()
    weekly = weekly_ohlcv.join(weekly_close.drop(columns=["SPY"], errors="ignore"), how="left")
    return weekly.dropna(subset=["SPY_CLOSE"]).sort_index().ffill()


def build_weekly_panel(weekly: pd.DataFrame) -> pd.DataFrame:
    close = weekly["SPY_CLOSE"].astype(float)
    open_ = weekly["SPY_OPEN"].astype(float)
    high = weekly["SPY_HIGH"].astype(float)
    low = weekly["SPY_LOW"].astype(float)
    volume = weekly["SPY_VOLUME"].astype(float)
    spy_ret = close.pct_change(fill_method=None)
    prev_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14, min_periods=4).mean()
    out = pd.DataFrame(index=weekly.index)
    out["spy_return"] = spy_ret

    for lb in [1, 2, 3, 4, 8, 13, 26, 52]:
        minp = min(lb, max(1, lb // 2))
        out[f"ret_{lb}w"] = ((1.0 + spy_ret).rolling(lb, min_periods=minp).apply(np.prod, raw=True) - 1.0).shift(1)
        out[f"volatility_{lb}w"] = spy_ret.rolling(lb, min_periods=minp).std().shift(1)
        out[f"ma_gap_{lb}w"] = (close / close.rolling(lb, min_periods=minp).mean() - 1.0).shift(1)
        out[f"ma_slope_{lb}w"] = close.rolling(lb, min_periods=minp).mean().pct_change(4).shift(1)
        out[f"drawdown_{lb}w"] = (close / close.rolling(lb, min_periods=minp).max() - 1.0).shift(1)

    candle_range = (high - low).replace(0.0, np.nan)
    body_high = pd.concat([open_, close], axis=1).max(axis=1)
    body_low = pd.concat([open_, close], axis=1).min(axis=1)
    out["close_location"] = ((close - low) / candle_range).shift(1)
    out["upper_wick"] = ((high - body_high) / candle_range).shift(1)
    out["lower_wick"] = ((body_low - low) / candle_range).shift(1)
    out["range_pct"] = (candle_range / close).shift(1)
    out["range_z"] = zscore(candle_range / close, 26).shift(1)
    out["gap"] = (open_ / prev_close - 1.0).shift(1)
    out["intraw_ret"] = (close / open_ - 1.0).shift(1)
    out["gap_failure"] = np.where(np.sign(open_ / prev_close - 1.0) != np.sign(close / open_ - 1.0), 1.0, -1.0)
    out["gap_failure"] = pd.Series(out["gap_failure"], index=weekly.index).shift(1)
    out["inside_bar"] = ((high < high.shift(1)) & (low > low.shift(1))).astype(float).shift(1)
    out["outside_bar"] = ((high > high.shift(1)) & (low < low.shift(1))).astype(float).shift(1)
    out["failed_breakout"] = ((high > high.shift(1)) & (close < high.shift(1))).astype(float).shift(1)
    out["failed_breakdown"] = ((low < low.shift(1)) & (close > low.shift(1))).astype(float).shift(1)
    out["atr_pct"] = (atr / close).shift(1)
    out["atr_channel"] = ((close - close.rolling(26, min_periods=8).mean()) / atr.replace(0.0, np.nan)).shift(1)
    out["atr_reclaim"] = (((close > close.rolling(13, min_periods=4).mean()) & (close.shift(1) < close.rolling(13, min_periods=4).mean().shift(1))).astype(float) * 2.0 - 1.0).shift(1)
    out["atr_stop_distance"] = ((close - low.rolling(13, min_periods=4).min()) / atr.replace(0.0, np.nan)).shift(1)
    out["drawdown_accel"] = out["drawdown_13w"].diff().shift(1)
    out["pullback_uptrend"] = ((out["ma_slope_26w"] > 0.0) & (out["ret_2w"] < 0.0)).astype(float)
    out["rally_downtrend"] = ((out["ma_slope_26w"] < 0.0) & (out["ret_2w"] > 0.0)).astype(float)
    out["dual_ma_distance"] = (close.rolling(8, min_periods=4).mean() / close.rolling(26, min_periods=8).mean() - 1.0).shift(1)
    out["ma_stack"] = ((close.rolling(8, min_periods=4).mean() > close.rolling(26, min_periods=8).mean()) & (close.rolling(26, min_periods=8).mean() > close.rolling(52, min_periods=16).mean())).astype(float).shift(1)
    out["rsi"] = rsi(spy_ret, 14).shift(1)
    out["rsi_failure"] = ((close > close.shift(4)) & (rsi(spy_ret, 14) < rsi(spy_ret, 14).shift(4))).astype(float).shift(1)
    macd_line = close.ewm(span=12, adjust=False, min_periods=4).mean() / close.ewm(span=26, adjust=False, min_periods=8).mean() - 1.0
    macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=3).mean()
    out["macd_line"] = macd_line.shift(1)
    out["macd_hist"] = (macd_line - macd_signal).shift(1)
    out["macd_hist_turn"] = (macd_line - macd_signal).diff().shift(1)
    out["volume_z"] = zscore(volume, 26).shift(1)
    out["volume_dryup"] = (-zscore(volume, 26)).shift(1)
    out["volatility_contraction"] = (-out["volatility_13w"].diff()).shift(1)
    out["volatility_expansion"] = out["volatility_13w"].diff().shift(1)
    out["post_loss"] = (spy_ret.shift(1) < -spy_ret.rolling(52, min_periods=12).std().shift(1)).astype(float)
    out["post_gain"] = (spy_ret.shift(1) > spy_ret.rolling(52, min_periods=12).std().shift(1)).astype(float)

    add_context_features(out, weekly, spy_ret)
    add_calendar_features(out)
    add_v2_features(out, weekly, spy_ret)
    out = out.replace([np.inf, -np.inf], np.nan).dropna(subset=["spy_return"])
    feature_cols = feature_columns(out)
    train = out.loc[(out.index >= TRAIN_START) & (out.index <= TRAIN_END), feature_cols]
    median = train.median()
    scale = (train.quantile(0.75) - train.quantile(0.25)).replace(0.0, np.nan).fillna(train.std()).replace(0.0, 1.0)
    out[feature_cols] = ((out[feature_cols] - median) / scale).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-8.0, 8.0)
    return out.dropna(subset=["spy_return"]).sort_index()


def add_context_features(out: pd.DataFrame, weekly: pd.DataFrame, spy_ret: pd.Series) -> None:
    def ret(symbol: str) -> pd.Series | None:
        if symbol not in weekly:
            return None
        return weekly[symbol].astype(float).pct_change(fill_method=None)

    for symbol, prefix in [
        ("^VIX", "vix"), ("^VIX3M", "vix3m"), ("^TNX", "tnx"), ("^IRX", "irx"), ("DX-Y.NYB", "dxy"),
        ("TLT", "tlt"), ("LQD", "lqd"), ("HYG", "hyg"), ("QQQ", "qqq"), ("IWM", "iwm"), ("DIA", "dia"),
        ("EFA", "efa"), ("EEM", "eem"), ("^N225", "n225"), ("^HSI", "hsi"), ("^FTSE", "ftse"),
        ("^GDAXI", "dax"), ("^FCHI", "fchi"),
    ]:
        series = ret(symbol)
        if series is None:
            continue
        out[f"{prefix}_ret_1w"] = series.shift(1)
        out[f"{prefix}_rel_spy"] = (series - spy_ret).shift(1)
        out[f"{prefix}_chg_4w"] = weekly[symbol].astype(float).pct_change(4).shift(1)

    if "^VIX" in weekly:
        vix = weekly["^VIX"].astype(float)
        out["vix_level"] = vix.shift(1)
        out["vix_chg"] = vix.pct_change().shift(1)
        out["vix_spike"] = zscore(vix.pct_change(fill_method=None), 26).shift(1)
        out["vix_persistent"] = zscore(vix.rolling(4, min_periods=2).mean(), 52).shift(1)
    if {"^VIX", "^VIX3M"}.issubset(weekly.columns):
        out["vix_term"] = (weekly["^VIX"].astype(float) / weekly["^VIX3M"].astype(float).replace(0.0, np.nan) - 1.0).shift(1)
    if "^TNX" in weekly and "^IRX" in weekly:
        curve = weekly["^TNX"].astype(float) - weekly["^IRX"].astype(float)
        out["yield_curve"] = curve.shift(1)
        out["curve_chg"] = curve.diff(4).shift(1)
        out["rates_shock"] = zscore(weekly["^TNX"].astype(float).diff(), 26).shift(1)
    if {"HYG", "LQD"}.issubset(weekly.columns):
        hyg = weekly["HYG"].astype(float).pct_change(fill_method=None)
        lqd = weekly["LQD"].astype(float).pct_change(fill_method=None)
        out["credit"] = (hyg - lqd).shift(1)
        out["hyg_lqd"] = (weekly["HYG"].astype(float) / weekly["LQD"].astype(float).replace(0.0, np.nan) - 1.0).shift(1)
    if "TLT" in weekly:
        out["tlt_spy"] = (weekly["SPY_CLOSE"].astype(float).pct_change(4) - weekly["TLT"].astype(float).pct_change(4)).shift(1)
        out["tlt_rel"] = (weekly["TLT"].astype(float).pct_change(4) - weekly["SPY_CLOSE"].astype(float).pct_change(4)).shift(1)

    sector_symbols = ["XLY", "XLP", "XLK", "XLU", "XLF", "XLE", "XLV", "XLI", "XLB"]
    available = [symbol for symbol in sector_symbols if symbol in weekly]
    if available:
        sector_rets = weekly[available].pct_change(fill_method=None)
        out["sector_breadth"] = (sector_rets.gt(spy_ret, axis=0).mean(axis=1)).shift(1)
        defensive = [symbol for symbol in ["XLP", "XLU", "XLV"] if symbol in weekly]
        cyclical = [symbol for symbol in ["XLY", "XLK", "XLI", "XLF"] if symbol in weekly]
        if defensive:
            out["defensive"] = (weekly[defensive].pct_change(4).mean(axis=1) - weekly["SPY_CLOSE"].pct_change(4)).shift(1)
        if cyclical:
            out["cyclical"] = (weekly[cyclical].pct_change(4).mean(axis=1) - weekly["SPY_CLOSE"].pct_change(4)).shift(1)
        if "XLI" in weekly:
            out["industrial"] = (weekly["XLI"].pct_change(4) - weekly["SPY_CLOSE"].pct_change(4)).shift(1)

    global_symbols = [symbol for symbol in ["EFA", "EEM", "^N225", "^HSI", "^FTSE", "^GDAXI", "^FCHI"] if symbol in weekly]
    if global_symbols:
        global_rets = weekly[global_symbols].pct_change(fill_method=None)
        out["global_breadth"] = (global_rets.gt(spy_ret, axis=0).mean(axis=1)).shift(1)
        asia = [symbol for symbol in ["^N225", "^HSI"] if symbol in weekly]
        europe = [symbol for symbol in ["^FTSE", "^GDAXI", "^FCHI"] if symbol in weekly]
        if asia:
            out["asia_lead"] = global_rets[asia].mean(axis=1).shift(1)
        if europe:
            out["europe_lead"] = global_rets[europe].mean(axis=1).shift(1)
    if {"^VIX"}.issubset(weekly.columns):
        out["vix_divergence"] = (weekly["^VIX"].pct_change(4) + weekly["SPY_CLOSE"].pct_change(4)).shift(1)
    if "DX-Y.NYB" in weekly:
        out["dollar_stress"] = (weekly["DX-Y.NYB"].pct_change(4) - weekly["SPY_CLOSE"].pct_change(4)).shift(1)
    if "IWM" in weekly:
        out["smallcap"] = (weekly["IWM"].pct_change(4) - weekly["SPY_CLOSE"].pct_change(4)).shift(1)
    if "QQQ" in weekly:
        out["nasdaq"] = (weekly["QQQ"].pct_change(4) - weekly["SPY_CLOSE"].pct_change(4)).shift(1)


def add_calendar_features(out: pd.DataFrame) -> None:
    idx = out.index
    week = pd.Series(idx.isocalendar().week.astype(float).to_numpy(), index=idx)
    month = pd.Series(idx.month.astype(float), index=idx)
    day = pd.Series(idx.day.astype(float), index=idx)
    out["calendar_turn_month"] = ((day <= 7.0) | (day >= 24.0)).astype(float)
    out["calendar_opex"] = ((day >= 15.0) & (day <= 21.0)).astype(float)
    out["calendar_month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
    out["calendar_month_cos"] = np.cos(2.0 * np.pi * month / 12.0)
    out["calendar_week_sin"] = np.sin(2.0 * np.pi * week / 52.0)
    out["calendar_week_cos"] = np.cos(2.0 * np.pi * week / 52.0)


def add_v2_features(out: pd.DataFrame, weekly: pd.DataFrame, spy_ret: pd.Series) -> None:
    close = weekly["SPY_CLOSE"].astype(float)
    high = weekly["SPY_HIGH"].astype(float)
    low = weekly["SPY_LOW"].astype(float)
    signs = np.sign(spy_ret.fillna(0.0))
    abs_ret = spy_ret.abs()

    for window in [4, 8, 13, 26, 52]:
        minp = max(3, window // 2)
        out[f"autocorr_{window}w"] = spy_ret.rolling(window, min_periods=minp).corr(spy_ret.shift(1)).shift(1)
        out[f"positive_autocorr_{window}w"] = out[f"autocorr_{window}w"].clip(lower=0.0)
        out[f"negative_autocorr_{window}w"] = (-out[f"autocorr_{window}w"].clip(upper=0.0))
        out[f"realized_skew_{window}w"] = spy_ret.rolling(window, min_periods=minp).skew().shift(1)
        out[f"realized_kurtosis_{window}w"] = spy_ret.rolling(window, min_periods=minp).kurt().shift(1)
        out[f"upside_vol_{window}w"] = spy_ret.where(spy_ret > 0.0, 0.0).rolling(window, min_periods=minp).std().shift(1)
        out[f"downside_vol_{window}w"] = spy_ret.where(spy_ret < 0.0, 0.0).rolling(window, min_periods=minp).std().shift(1)
        out[f"upside_downside_vol_{window}w"] = (out[f"upside_vol_{window}w"] / out[f"downside_vol_{window}w"].replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)
        out[f"semivariance_{window}w"] = (spy_ret.where(spy_ret < 0.0, 0.0).pow(2).rolling(window, min_periods=minp).mean()).shift(1)
        out[f"return_entropy_{window}w"] = signs.rolling(window, min_periods=minp).apply(sign_entropy, raw=True).shift(1)
        out[f"low_entropy_{window}w"] = -out[f"return_entropy_{window}w"]
        out[f"high_entropy_{window}w"] = out[f"return_entropy_{window}w"]
        out[f"vol_of_vol_{window}w"] = abs_ret.rolling(window, min_periods=minp).std().rolling(window, min_periods=minp).std().shift(1)
        out[f"vol_of_vol_collapse_{window}w"] = (-out[f"vol_of_vol_{window}w"].diff()).shift(1)
        out[f"ulcer_index_{window}w"] = rolling_ulcer(close, window).shift(1)
        out[f"time_since_high_{window}w"] = high.rolling(window, min_periods=minp).apply(age_since_extreme_high, raw=True).shift(1)
        out[f"time_since_low_{window}w"] = low.rolling(window, min_periods=minp).apply(age_since_extreme_low, raw=True).shift(1)

    out["sign_pattern_4w"] = signs.rolling(4, min_periods=4).apply(binary_sign_code, raw=True).shift(1)
    out["sign_pattern_6w"] = signs.rolling(6, min_periods=6).apply(binary_sign_code, raw=True).shift(1)
    out["alternating_weeks"] = signs.rolling(6, min_periods=4).apply(alternation_score, raw=True).shift(1)
    out["streak_age"] = signs.rolling(26, min_periods=2).apply(current_streak_age, raw=True).shift(1)
    out["streak_exhaustion"] = out["streak_age"] * -np.sign(spy_ret.shift(1)).fillna(0.0)
    out["streak_continuation"] = out["streak_age"] * np.sign(spy_ret.shift(1)).fillna(0.0)
    out["acceleration"] = spy_ret.diff().shift(1)
    out["second_derivative"] = spy_ret.diff().diff().shift(1)
    out["jerk"] = spy_ret.diff().diff().diff().shift(1)
    out["drawdown_duration"] = (close / close.cummax() - 1.0).rolling(104, min_periods=4).apply(current_drawdown_duration, raw=True).shift(1)
    out["drawdown_failure"] = out["drawdown_duration"] * out["drawdown_13w"]
    out["prior_stress_pattern"] = ((out["volatility_13w"] > out["volatility_26w"]) & (out["drawdown_13w"] < 0.0)).astype(float)
    out["stress_cluster"] = (out["prior_stress_pattern"].rolling(8, min_periods=2).sum()).shift(1)

    add_v2_cross_asset_features(out, weekly, spy_ret)


def add_v2_cross_asset_features(out: pd.DataFrame, weekly: pd.DataFrame, spy_ret: pd.Series) -> None:
    def returns(symbol: str) -> pd.Series | None:
        if symbol not in weekly:
            return None
        return weekly[symbol].astype(float).pct_change(fill_method=None)

    for symbol, prefix in [
        ("QQQ", "qqq"), ("IWM", "iwm"), ("TLT", "tlt"), ("HYG", "hyg"), ("^VIX", "vix"),
        ("^TNX", "tnx"), ("DX-Y.NYB", "dxy"),
    ]:
        other = returns(symbol)
        if other is None:
            continue
        for window in [13, 26, 52]:
            minp = max(5, window // 2)
            var = other.rolling(window, min_periods=minp).var().replace(0.0, np.nan)
            cov = spy_ret.rolling(window, min_periods=minp).cov(other)
            corr = spy_ret.rolling(window, min_periods=minp).corr(other)
            out[f"{prefix}_beta_{window}w"] = (cov / var).shift(1)
            out[f"spy_{prefix}_corr_{window}w"] = corr.shift(1)
            out[f"{prefix}_beta_instability_{window}w"] = (cov / var).diff(4).abs().shift(1)

    if {"TLT", "HYG", "QQQ", "IWM"}.issubset(weekly.columns):
        out["corr_flip"] = (
            out.get("spy_tlt_corr_26w", 0.0).fillna(0.0)
            - out.get("spy_hyg_corr_26w", 0.0).fillna(0.0)
        )
        out["corr_compression"] = -(
            out.get("spy_qqq_corr_26w", 0.0).fillna(0.0)
            - out.get("spy_iwm_corr_26w", 0.0).fillna(0.0)
        ).abs()
        out["corr_divergence"] = (
            out.get("spy_qqq_corr_26w", 0.0).fillna(0.0)
            - out.get("spy_iwm_corr_26w", 0.0).fillna(0.0)
        )

    sector_symbols = [symbol for symbol in ["XLY", "XLP", "XLK", "XLU", "XLF", "XLE", "XLV", "XLI", "XLB"] if symbol in weekly]
    if sector_symbols:
        sector_rets = weekly[sector_symbols].pct_change(fill_method=None)
        dispersion = sector_rets.std(axis=1)
        out["sector_dispersion_4w"] = dispersion.rolling(4, min_periods=2).mean().shift(1)
        out["sector_dispersion_13w"] = dispersion.rolling(13, min_periods=5).mean().shift(1)
        out["sector_dispersion_expansion"] = out["sector_dispersion_4w"].diff().shift(1)
        out["sector_dispersion_compression"] = (-out["sector_dispersion_4w"].diff()).shift(1)
        out["sector_lead_lag"] = (sector_rets.mean(axis=1).shift(1) - spy_ret).shift(1)
        out["sector_rotation"] = sector_rets.rank(axis=1, pct=True).std(axis=1).shift(1)

    if {"XLY", "XLP", "XLK", "XLU", "XLV", "IWM", "SPY_CLOSE"}.issubset(weekly.columns):
        defensive = weekly[["XLP", "XLU", "XLV"]].pct_change(4).mean(axis=1)
        cyclical = weekly[["XLY", "XLK"]].pct_change(4).mean(axis=1)
        out["defensive_cyclical_spread"] = (cyclical - defensive).shift(1)
        out["growth_value_proxy"] = (weekly["XLK"].pct_change(4) - weekly["XLF"].pct_change(4) if "XLF" in weekly else weekly["XLK"].pct_change(4) - weekly["XLP"].pct_change(4)).shift(1)
        out["large_small_proxy"] = (weekly["SPY_CLOSE"].pct_change(4) - weekly["IWM"].pct_change(4)).shift(1)

    if {"EFA", "EEM", "^N225", "^HSI", "^FTSE", "^GDAXI", "^FCHI"}.intersection(weekly.columns):
        global_symbols = [symbol for symbol in ["EFA", "EEM", "^N225", "^HSI", "^FTSE", "^GDAXI", "^FCHI"] if symbol in weekly]
        global_ret = weekly[global_symbols].pct_change(4).mean(axis=1)
        out["global_us_spread"] = (global_ret - weekly["SPY_CLOSE"].pct_change(4)).shift(1)
    if {"EEM", "EFA"}.issubset(weekly.columns):
        out["em_dm_spread"] = (weekly["EEM"].pct_change(4) - weekly["EFA"].pct_change(4)).shift(1)
    if {"^N225", "^HSI"}.intersection(weekly.columns):
        asia_symbols = [symbol for symbol in ["^N225", "^HSI"] if symbol in weekly]
        out["asia_us_gap"] = (weekly[asia_symbols].pct_change().mean(axis=1) - spy_ret).shift(1)
    if {"^FTSE", "^GDAXI", "^FCHI"}.intersection(weekly.columns):
        europe_symbols = [symbol for symbol in ["^FTSE", "^GDAXI", "^FCHI"] if symbol in weekly]
        out["europe_us_gap"] = (weekly[europe_symbols].pct_change().mean(axis=1) - spy_ret).shift(1)

    if "DX-Y.NYB" in weekly:
        out["fx_equity_corr"] = spy_ret.rolling(26, min_periods=8).corr(weekly["DX-Y.NYB"].pct_change(fill_method=None)).shift(1)
    if "^TNX" in weekly:
        out["rates_equity_corr"] = spy_ret.rolling(26, min_periods=8).corr(weekly["^TNX"].diff()).shift(1)
    if "HYG" in weekly:
        hyg_ret = weekly["HYG"].pct_change(fill_method=None)
        out["credit_equity_lag"] = (hyg_ret.shift(1) - spy_ret).shift(1)

    agreement_inputs = []
    for col in ["qqq_ret_1w", "iwm_ret_1w", "hyg_ret_1w", "tlt_ret_1w", "global_us_spread", "defensive_cyclical_spread"]:
        if col in out:
            agreement_inputs.append(np.sign(out[col].fillna(0.0)))
    if agreement_inputs:
        agreement = pd.concat(agreement_inputs, axis=1)
        out["multi_asset_agreement"] = agreement.mean(axis=1)
        out["multi_asset_disagreement"] = agreement.std(axis=1)
        out["regime_transition"] = out["multi_asset_agreement"].diff().abs().shift(1)
        out["transition_vote"] = (out["multi_asset_agreement"] - out["multi_asset_disagreement"]).shift(1)


def sign_entropy(values: np.ndarray) -> float:
    clean = values[np.isfinite(values)]
    if clean.size == 0:
        return 0.0
    buckets = np.array([(clean > 0.0).mean(), (clean < 0.0).mean(), (clean == 0.0).mean()], dtype=float)
    buckets = buckets[buckets > 0.0]
    return float(-(buckets * np.log2(buckets)).sum())


def binary_sign_code(values: np.ndarray) -> float:
    clean = np.where(np.asarray(values) > 0.0, 1.0, 0.0)
    weights = 2.0 ** np.arange(clean.size)
    return float(np.dot(clean, weights) / max(1.0, weights.sum()))


def alternation_score(values: np.ndarray) -> float:
    clean = np.asarray(values)
    clean = clean[np.isfinite(clean)]
    if clean.size < 2:
        return 0.0
    return float(np.mean(np.sign(clean[1:]) != np.sign(clean[:-1])))


def current_streak_age(values: np.ndarray) -> float:
    clean = np.sign(np.asarray(values))
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return 0.0
    last = clean[-1]
    age = 0
    for item in clean[::-1]:
        if item == last:
            age += 1
        else:
            break
    return float(age * last)


def current_drawdown_duration(values: np.ndarray) -> float:
    clean = np.asarray(values)
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return 0.0
    age = 0
    for item in clean[::-1]:
        if item < 0.0:
            age += 1
        else:
            break
    return float(age)


def rolling_ulcer(close: pd.Series, window: int) -> pd.Series:
    rolling_max = close.rolling(window, min_periods=max(3, window // 2)).max()
    drawdown = close / rolling_max.replace(0.0, np.nan) - 1.0
    return np.sqrt(drawdown.pow(2).rolling(window, min_periods=max(3, window // 2)).mean())


def age_since_extreme_high(values: np.ndarray) -> float:
    clean = np.asarray(values)
    if clean.size == 0 or np.all(~np.isfinite(clean)):
        return 0.0
    return float(clean.size - 1 - int(np.nanargmax(clean)))


def age_since_extreme_low(values: np.ndarray) -> float:
    clean = np.asarray(values)
    if clean.size == 0 or np.all(~np.isfinite(clean)):
        return 0.0
    return float(clean.size - 1 - int(np.nanargmin(clean)))


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
    cost_bps: float,
) -> None:
    panel = pd.read_csv(output_dir / "weekly_panel_no_locked.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if panel.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard")
    feature_cols = feature_columns(panel)
    train_mask = np.asarray((panel.index >= TRAIN_START) & (panel.index <= TRAIN_END), dtype=bool)
    validation_mask = np.asarray((panel.index >= VALIDATION_START) & (panel.index <= VALIDATION_END), dtype=bool)
    matrix = panel[feature_cols].to_numpy(dtype=float)
    spy_returns = panel["spy_return"].to_numpy(dtype=float)
    idea = IDEA_SPECS[stage % len(IDEA_SPECS)]
    rng = np.random.default_rng(20260616 + int(stage) * 1_000_003)
    deadline = time.monotonic() + max(0.01, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0

    while evaluated < int(configs_per_stage) and time.monotonic() < deadline:
        evaluated += 1
        params = sample_params(rng, feature_cols, idea, stage=stage)
        scores = build_scores(matrix, params)
        positions, train_metrics, fit = choose_discrete_positions_train_only(scores, spy_returns, train_mask)
        params.update(fit)
        policy = position_policy_audit(positions)
        if not policy["policy_pass"]:
            continue
        strategy_returns = apply_costs(positions, spy_returns, cost_bps)
        train_metrics = metrics(strategy_returns[train_mask])
        validation_metrics = metrics(strategy_returns[validation_mask])
        train_position = position_summary(positions[train_mask])
        validation_position = position_summary(positions[validation_mask])
        accepted = is_accepted(train_metrics, validation_metrics, validation_position)
        features = [feature_cols[int(i)] for i in params["feature_indices"]]
        payload = {"idea_id": idea["idea_id"], "params": params, "features": features}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"spy_weekly_noleverage_50ideas_v2_s{stage:03d}_{digest}",
                "stage": int(stage),
                "config_index": int(evaluated),
                "idea_id": idea["idea_id"],
                "idea_family": idea["idea_family"],
                "train_score": selection_score(train_metrics, train_position, params),
                "accepted": bool(accepted),
                "traded_asset": "SPY",
                "frequency": "weekly",
                "position_policy": "discrete_long_flat_short_no_leverage",
                "unique_positions": policy["unique_positions"],
                "max_abs_position": policy["max_abs_position"],
                "cash_allowed": True,
                "leverage_allowed": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "train_sharpe": train_metrics["sharpe"],
                "validation_sharpe": validation_metrics["sharpe"],
                "train_total_return": train_metrics["total_return"],
                "validation_total_return": validation_metrics["total_return"],
                "train_profit_factor": train_metrics["profit_factor"],
                "validation_profit_factor": validation_metrics["profit_factor"],
                "train_mdd": train_metrics["mdd"],
                "validation_mdd": validation_metrics["mdd"],
                "train_trades": train_metrics["trades"],
                "validation_trades": validation_metrics["trades"],
                "train_abs_exposure_mean": train_position["abs_exposure_mean"],
                "validation_abs_exposure_mean": validation_position["abs_exposure_mean"],
                "train_long_pct": train_position["long_pct"],
                "validation_long_pct": validation_position["long_pct"],
                "train_short_pct": train_position["short_pct"],
                "validation_short_pct": validation_position["short_pct"],
                "train_cash_pct": train_position["cash_pct"],
                "validation_cash_pct": validation_position["cash_pct"],
                "features": "|".join(features),
                "params_json": json.dumps(params, sort_keys=True),
            }
        )

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=leaderboard_columns())
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    accepted_frame = frame[frame.get("accepted", pd.Series(dtype=bool)).astype(bool)]
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    accepted_frame.to_csv(shard_dir / "accepted.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "idea_id": idea["idea_id"],
                "idea_family": idea["idea_family"],
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "accepted_rows": int(len(accepted_frame)),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def final_merge(output_dir: Path, *, locked_retest_top_n: int, cost_bps: float) -> None:
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    top = concat_csv(list((output_dir / "shards").glob("**/top_candidates.csv")))
    accepted = concat_csv(list((output_dir / "shards").glob("**/accepted.csv")))
    summaries = load_json_files(list((output_dir / "shards").glob("**/shard_summary.json")))
    if not top.empty:
        top = top.drop_duplicates("strategy_id").sort_values(["train_score", "train_sharpe"], ascending=[False, False])
    if not accepted.empty:
        accepted = accepted.drop_duplicates("strategy_id").sort_values(["validation_profit_factor", "validation_total_return"], ascending=[False, False])

    locked_results = locked_retest(output_dir, top.head(int(locked_retest_top_n)), cost_bps=cost_bps)
    idea_summary = summarize_by(top, "idea_id")
    family_summary = summarize_by(top, "idea_family")
    fail_reasons = build_fail_reasons(top)

    top.to_csv(final / "leaderboard.csv", index=False)
    accepted.to_csv(final / "accepted.csv", index=False)
    locked_results.to_csv(final / "locked_results.csv", index=False)
    idea_summary.to_csv(final / "idea_summary.csv", index=False)
    family_summary.to_csv(final / "family_summary.csv", index=False)
    fail_reasons.to_csv(final / "fail_reasons.csv", index=False)
    pd.DataFrame(summaries).to_csv(final / "round_summaries.csv", index=False)
    (final / "position_policy_audit.json").write_text(json.dumps(base_policy_audit() | {"locked_opened": True}, indent=2), encoding="utf-8")
    (final / "nightly_summary.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "rows_leaderboard": int(len(top)),
                "rows_accepted": int(len(accepted)),
                "rows_locked_retested": int(len(locked_results)),
                "ideas_total": len(IDEA_SPECS),
                "ideas_seen": int(top["idea_id"].nunique()) if "idea_id" in top else 0,
                "configs_evaluated": int(sum(int(item.get("configs_evaluated", 0)) for item in summaries)),
                "final_position_target": 0,
                "traded_asset": "SPY",
                "position_policy": "discrete_long_flat_short_no_leverage",
                "locked_opened": True,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def locked_retest(output_dir: Path, candidates: pd.DataFrame, *, cost_bps: float) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=leaderboard_columns() + ["locked_sharpe", "locked_total_return"])
    panel = pd.read_csv(output_dir / "weekly_panel_all.csv", parse_dates=["timestamp"]).set_index("timestamp")
    feature_cols = feature_columns(panel)
    matrix = panel[feature_cols].to_numpy(dtype=float)
    spy_returns = panel["spy_return"].to_numpy(dtype=float)
    locked_mask = np.asarray(panel.index >= LOCKED_START, dtype=bool)
    rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        try:
            params = json.loads(str(row["params_json"]))
            scores = build_scores(matrix, params)
            positions = positions_from_fit(scores, params)
            policy = position_policy_audit(positions)
            if not policy["policy_pass"]:
                continue
            locked_returns = apply_costs(positions, spy_returns, cost_bps)[locked_mask]
            locked_metrics = metrics(locked_returns)
            item = row.to_dict()
            item.update(
                {
                    "locked_opened": True,
                    "locked_rows_accessed": int(np.sum(locked_mask)),
                    "validation_used_for_selection": False,
                    "locked_sharpe": locked_metrics["sharpe"],
                    "locked_total_return": locked_metrics["total_return"],
                    "locked_profit_factor": locked_metrics["profit_factor"],
                    "locked_mdd": locked_metrics["mdd"],
                    "locked_trades": locked_metrics["trades"],
                    "locked_abs_exposure_mean": position_summary(positions[locked_mask])["abs_exposure_mean"],
                }
            )
            rows.append(item)
        except Exception:
            continue
    return pd.DataFrame(rows)


def sample_params(rng: np.random.Generator, feature_cols: list[str], idea: dict[str, Any], *, stage: int) -> dict[str, Any]:
    candidates = [
        idx
        for idx, name in enumerate(feature_cols)
        if any(str(pattern) in name for pattern in idea["patterns"])
    ]
    if len(candidates) < 2:
        candidates = list(range(len(feature_cols)))
    k = int(rng.integers(1, min(6, len(candidates)) + 1))
    idx = rng.choice(candidates, size=k, replace=False)
    rule_type = str(rng.choice(["linear", "threshold_vote", "pair_spread", "rank_vote", "single_feature"]))
    weights = rng.normal(0.0, 1.0, size=k)
    if np.sum(np.abs(weights)) == 0.0:
        weights = np.ones(k)
    weights = weights / np.sum(np.abs(weights))
    return {
        "idea_id": idea["idea_id"],
        "idea_family": idea["idea_family"],
        "stage": int(stage),
        "rule_type": rule_type,
        "feature_indices": [int(i) for i in idx],
        "weights": [float(x) for x in weights],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.15, 0.85, size=k)],
        "cash_band_scale": float(rng.choice([0.0, 0.10, 0.20, 0.35, 0.50, 0.75])),
        "min_side_pct": float(rng.choice([0.02, 0.03, 0.05, 0.08])),
    }


def build_scores(matrix: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = matrix[:, idx]
    weights = np.asarray(params.get("weights", [1.0 / max(1, len(idx))] * len(idx)), dtype=float)
    directions = np.asarray(params.get("directions", [1.0] * len(idx)), dtype=float)
    rule_type = str(params.get("rule_type", "linear"))
    if values.ndim == 1:
        values = values[:, None]
    if rule_type == "single_feature":
        return values[:, 0] * directions[0]
    if rule_type == "threshold_vote":
        thresholds = np.asarray([np.nanquantile(values[:, i], params.get("quantiles", [0.5] * len(idx))[i]) for i in range(len(idx))])
        votes = np.where(values * directions >= thresholds * directions, 1.0, -1.0)
        return votes @ weights
    if rule_type == "pair_spread" and values.shape[1] >= 2:
        return values[:, 0] * directions[0] - values[:, 1] * directions[1]
    if rule_type == "rank_vote":
        ranks = pd.DataFrame(values).rank(pct=True).to_numpy(dtype=float) - 0.5
        return (ranks * directions) @ weights
    return values @ weights


def choose_discrete_positions_train_only(
    scores: np.ndarray,
    spy_returns: np.ndarray,
    train_mask: np.ndarray,
    *,
    min_side_pct: float = 0.03,
) -> tuple[np.ndarray, dict[str, float], dict[str, Any]]:
    values = np.asarray(scores, dtype=float)
    train_scores = values[train_mask]
    thresholds = [0.0]
    for q in np.linspace(0.15, 0.85, 15):
        val = np.nanquantile(train_scores, q)
        if np.isfinite(val):
            thresholds.append(float(val))
    std = float(np.nanstd(train_scores))
    if not np.isfinite(std):
        std = 0.0
    bands = [0.0, 0.10 * std, 0.20 * std, 0.35 * std, 0.50 * std]
    best: tuple[float, np.ndarray, dict[str, float], dict[str, Any]] | None = None
    for invert in [0, 1]:
        oriented = -values if invert else values
        for threshold in thresholds:
            for band in bands:
                positions = np.where(oriented > threshold + band, 1.0, np.where(oriented < threshold - band, -1.0, 0.0))
                summary = position_summary(positions[train_mask])
                if summary["long_pct"] < min_side_pct * 100.0 or summary["short_pct"] < min_side_pct * 100.0:
                    continue
                if summary["cash_pct"] > 90.0:
                    continue
                current = metrics(positions[train_mask] * spy_returns[train_mask])
                score = float(current["sharpe"]) if np.isfinite(current["sharpe"]) else -999.0
                score += float(current["total_return"])
                if best is None or score > best[0]:
                    best = (
                        score,
                        positions.astype(float),
                        current,
                        {
                            "threshold": float(threshold),
                            "cash_band": float(band),
                            "invert": int(invert),
                            "fitted_on_train_only": True,
                        },
                    )
    if best is None:
        fallback = np.sign(values)
        fallback[np.abs(values) < np.nanmedian(np.abs(train_scores)) * 0.25] = 0.0
        fit = {"threshold": 0.0, "cash_band": float(np.nanmedian(np.abs(train_scores)) * 0.25), "invert": 0, "fitted_on_train_only": True}
        return sanitize_positions(fallback), metrics(fallback[train_mask] * spy_returns[train_mask]), fit
    return sanitize_positions(best[1]), best[2], best[3]


def positions_from_fit(scores: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    values = -np.asarray(scores, dtype=float) if int(params.get("invert", 0)) == 1 else np.asarray(scores, dtype=float)
    threshold = float(params.get("threshold", 0.0))
    band = float(params.get("cash_band", 0.0))
    return sanitize_positions(np.where(values > threshold + band, 1.0, np.where(values < threshold - band, -1.0, 0.0)))


def sanitize_positions(values: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(values, dtype=float) > 0.0, 1.0, np.where(np.asarray(values, dtype=float) < 0.0, -1.0, 0.0)).astype(float)


def apply_costs(positions: np.ndarray, returns: np.ndarray, cost_bps: float) -> np.ndarray:
    pos = sanitize_positions(positions)
    rets = np.asarray(returns, dtype=float)
    changes = np.r_[abs(pos[0]), np.abs(np.diff(pos))]
    costs = changes * float(cost_bps) / 10_000.0
    return pos * rets - costs


def metrics(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return empty_metrics()
    total_return = float(np.prod(1.0 + values) - 1.0)
    std = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / std * math.sqrt(PPY)) if std > 0.0 else np.nan
    nav = np.cumprod(1.0 + values)
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    gains = values[values > 0.0].sum()
    losses = -values[values < 0.0].sum()
    pf = float(gains / losses) if losses > 0.0 else np.inf if gains > 0.0 else 0.0
    trades = int(np.sum(np.abs(values) > 0.0))
    return {"sharpe": sharpe, "total_return": total_return, "mdd": mdd, "profit_factor": pf, "trades": trades}


def empty_metrics() -> dict[str, float]:
    return {"sharpe": np.nan, "total_return": np.nan, "mdd": np.nan, "profit_factor": np.nan, "trades": 0}


def position_summary(positions: np.ndarray) -> dict[str, float]:
    values = sanitize_positions(positions)
    if len(values) == 0:
        return {"long_pct": 0.0, "short_pct": 0.0, "cash_pct": 0.0, "abs_exposure_mean": 0.0}
    return {
        "long_pct": float(np.mean(values > 0.0) * 100.0),
        "short_pct": float(np.mean(values < 0.0) * 100.0),
        "cash_pct": float(np.mean(values == 0.0) * 100.0),
        "abs_exposure_mean": float(np.mean(np.abs(values))),
    }


def position_policy_audit(positions: np.ndarray) -> dict[str, Any]:
    values = np.asarray(positions, dtype=float)
    finite = values[np.isfinite(values)]
    unique = sorted({float(x) for x in finite})
    max_abs = float(np.max(np.abs(finite))) if len(finite) else np.nan
    unique_text = "|".join(str(int(x)) for x in unique)
    return {
        "unique_positions": unique_text,
        "max_abs_position": max_abs,
        "policy_pass": bool(len(finite) == len(values) and set(unique).issubset(ALLOWED_POSITIONS) and max_abs <= 1.0),
    }


def is_accepted(train: dict[str, float], validation: dict[str, float], validation_position: dict[str, float]) -> bool:
    return bool(
        float(train["total_return"]) > 0.0
        and float(validation["total_return"]) > 0.0
        and float(validation["profit_factor"]) >= 1.05
        and int(validation["trades"]) >= 40
        and 0.15 <= float(validation_position["abs_exposure_mean"]) <= 0.90
    )


def selection_score(train: dict[str, float], position: dict[str, float], params: dict[str, Any]) -> float:
    sharpe = float(train["sharpe"]) if np.isfinite(train["sharpe"]) else -10.0
    return float(sharpe * 1_000_000.0 + float(train["total_return"]) * 200_000.0 + float(train["profit_factor"]) * 10_000.0 - abs(position["cash_pct"] - 35.0) * 1_000.0 - len(params["feature_indices"]) * 500.0)


def feature_columns(panel: pd.DataFrame) -> list[str]:
    return [col for col in panel.columns if col != "spy_return"]


def zscore(series: pd.Series, window: int) -> pd.Series:
    return (series - series.rolling(window, min_periods=max(2, window // 3)).mean()) / series.rolling(window, min_periods=max(2, window // 3)).std().replace(0.0, np.nan)


def rsi(returns: pd.Series, window: int) -> pd.Series:
    gains = returns.clip(lower=0.0).rolling(window, min_periods=max(2, window // 3)).mean()
    losses = (-returns.clip(upper=0.0)).rolling(window, min_periods=max(2, window // 3)).mean()
    rs = gains / losses.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def concat_csv(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            try:
                frame = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                continue
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=leaderboard_columns())


def load_json_files(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def summarize_by(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if frame.empty or column not in frame:
        return pd.DataFrame(columns=[column, "rows", "accepted_rows", "best_train_sharpe", "best_validation_profit_factor"])
    return (
        frame.groupby(column)
        .agg(
            rows=("strategy_id", "count"),
            accepted_rows=("accepted", "sum"),
            best_train_sharpe=("train_sharpe", "max"),
            best_validation_profit_factor=("validation_profit_factor", "max"),
        )
        .reset_index()
        .sort_values(["accepted_rows", "best_train_sharpe"], ascending=[False, False])
    )


def build_fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in frame.iterrows():
        if bool(row.get("accepted", False)):
            reasons.append("accepted")
        elif float(row.get("validation_total_return", -999.0)) <= 0.0:
            reasons.append("validation_total_return_not_positive")
        elif float(row.get("validation_profit_factor", 0.0)) < 1.05:
            reasons.append("validation_profit_factor_below_105")
        elif float(row.get("validation_abs_exposure_mean", 0.0)) < 0.15:
            reasons.append("validation_exposure_too_low")
        elif float(row.get("validation_abs_exposure_mean", 9.0)) > 0.90:
            reasons.append("validation_exposure_too_high")
        else:
            reasons.append("other")
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


def base_policy_audit() -> dict[str, Any]:
    return {
        "campaign_id": CAMPAIGN_ID,
        "traded_asset": "SPY",
        "frequency": "weekly",
        "position_policy": "discrete_long_flat_short_no_leverage",
        "allowed_positions": [-1, 0, 1],
        "cash_allowed": True,
        "leverage_allowed": False,
        "max_abs_position": 1.0,
        "validation_used_for_selection": False,
    }


def leaderboard_columns() -> list[str]:
    return [
        "strategy_id", "stage", "config_index", "idea_id", "idea_family", "train_score", "accepted",
        "traded_asset", "frequency", "position_policy", "unique_positions", "max_abs_position",
        "cash_allowed", "leverage_allowed", "locked_opened", "locked_rows_accessed", "validation_used_for_selection",
        "train_sharpe", "validation_sharpe", "train_total_return", "validation_total_return",
        "train_profit_factor", "validation_profit_factor", "train_mdd", "validation_mdd",
        "train_trades", "validation_trades", "train_abs_exposure_mean", "validation_abs_exposure_mean",
        "train_long_pct", "validation_long_pct", "train_short_pct", "validation_short_pct",
        "train_cash_pct", "validation_cash_pct", "features", "params_json",
    ]


def synthetic_weekly_panel(*, periods: int = 1500) -> pd.DataFrame:
    idx = pd.date_range("1995-01-06", periods=periods, freq="W-FRI")
    t = np.arange(periods, dtype=float)
    seasonal = np.sin(t / 17.0) * 0.015
    trend = np.where((t.astype(int) // 90) % 2 == 0, 0.006, -0.003)
    returns = seasonal + trend + np.sin(t / 5.0) * 0.004
    price = 100.0 * np.cumprod(1.0 + returns)
    weekly = pd.DataFrame(
        {
            "SPY_OPEN": price / (1.0 + returns * 0.4),
            "SPY_HIGH": price * (1.01 + np.abs(np.sin(t / 9.0)) * 0.01),
            "SPY_LOW": price * (0.99 - np.abs(np.cos(t / 11.0)) * 0.01),
            "SPY_CLOSE": price,
            "SPY_VOLUME": 1_000_000 + (np.sin(t / 13.0) + 1.2) * 100_000,
            "^VIX": 20.0 + np.maximum(0.0, -returns * 400.0) + np.sin(t / 10.0) * 2.0,
            "^VIX3M": 22.0 + np.sin(t / 12.0),
            "^TNX": 3.0 + np.sin(t / 31.0),
            "^IRX": 1.0 + np.cos(t / 37.0) * 0.4,
            "DX-Y.NYB": 95.0 + np.sin(t / 23.0) * 3.0,
            "TLT": 100.0 * np.cumprod(1.0 - returns * 0.3 + 0.001),
            "LQD": 100.0 * np.cumprod(1.0 + returns * 0.1 + 0.001),
            "HYG": 100.0 * np.cumprod(1.0 + returns * 0.5 + 0.001),
            "QQQ": 100.0 * np.cumprod(1.0 + returns * 1.2),
            "IWM": 100.0 * np.cumprod(1.0 + returns * 0.9),
            "DIA": 100.0 * np.cumprod(1.0 + returns * 0.8),
            "XLY": 100.0 * np.cumprod(1.0 + returns * 1.1),
            "XLP": 100.0 * np.cumprod(1.0 + returns * 0.4),
            "XLK": 100.0 * np.cumprod(1.0 + returns * 1.3),
            "XLU": 100.0 * np.cumprod(1.0 - returns * 0.2),
            "XLF": 100.0 * np.cumprod(1.0 + returns * 0.9),
            "XLE": 100.0 * np.cumprod(1.0 + np.roll(returns, 2) * 0.7),
            "XLV": 100.0 * np.cumprod(1.0 + returns * 0.5),
            "XLI": 100.0 * np.cumprod(1.0 + returns * 0.8),
            "XLB": 100.0 * np.cumprod(1.0 + returns * 0.7),
            "EFA": 100.0 * np.cumprod(1.0 + np.roll(returns, 1) * 0.7),
            "EEM": 100.0 * np.cumprod(1.0 + np.roll(returns, 2) * 0.8),
            "^N225": 100.0 * np.cumprod(1.0 + np.roll(returns, 1) * 0.6),
            "^HSI": 100.0 * np.cumprod(1.0 + np.roll(returns, 1) * 0.5),
            "^FTSE": 100.0 * np.cumprod(1.0 + np.roll(returns, 1) * 0.4),
            "^GDAXI": 100.0 * np.cumprod(1.0 + np.roll(returns, 1) * 0.5),
            "^FCHI": 100.0 * np.cumprod(1.0 + np.roll(returns, 1) * 0.45),
        },
        index=idx,
    )
    return build_weekly_panel(weekly)


if __name__ == "__main__":
    main()

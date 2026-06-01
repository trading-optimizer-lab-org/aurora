"""Template backtests for distinct literature strategy signatures.

This module deliberately tests Aurora templates derived from paper signatures.
It does not claim exact paper replication.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from aurora.core.metrics import compute_metrics
from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore


TRAIN_START = "1995-01-01"
TRAIN_END = "2010-12-31"
VALIDATION_START = "2011-01-01"
VALIDATION_END = "2020-12-31"
LOCKED_START = "2021-01-01"
SIZE_GRID = (0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
PERIODS_PER_YEAR = {
    "daily": 252,
    "weekly": 52,
    "monthly": 12,
    "monthly_template": 12,
    "quarterly": 4,
    "annual": 1,
}


ASSET_BUCKET_GROUPS: dict[str, tuple[str, ...]] = {
    "equity_index": ("equity_index", "equity_international"),
    "sector": ("equity_sector",),
    "equity_single": ("equity_single_name",),
    "bonds_rates": ("rates_fixed_income",),
    "credit": ("rates_fixed_income",),
    "commodities": ("commodity",),
    "fx": ("fx_spot",),
    "crypto": ("crypto_spot",),
    "multi_asset": ("equity_index", "rates_fixed_income", "commodity", "fx_spot"),
    "macro": ("equity_index", "rates_fixed_income", "commodity"),
    "volatility": ("equity_index", "rates_fixed_income"),
}

PREFERRED_SYMBOLS: dict[str, tuple[str, ...]] = {
    "equity_index": ("SPY", "QQQ", "DIA", "IWM", "VTI", "RSP", "EFA", "EEM"),
    "sector": ("XLE", "XLF", "XLK", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"),
    "equity_single": ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "WMT"),
    "bonds_rates": ("TLT", "IEF", "SHY", "BIL", "AGG", "BND", "TIP"),
    "credit": ("HYG", "LQD", "BIL", "SHY"),
    "commodities": ("GLD", "SLV", "USO", "DBC", "DBA", "CPER"),
    "fx": ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "DXY"),
    "crypto": ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"),
    "multi_asset": ("SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "DXY", "EFA", "EEM"),
    "macro": ("SPY", "QQQ", "TLT", "IEF", "GLD", "DBC"),
    "volatility": ("SPY", "QQQ", "IWM", "TLT", "GLD"),
}

CONTEXT_SYMBOLS = (
    "DGS1",
    "DGS2",
    "DGS10",
    "DGS30",
    "T10Y2Y",
    "T10Y3M",
    "FEDFUNDS",
    "UNRATE",
    "CPIAUCSL",
    "PAYEMS",
    "VIXCLS",
    "BAMLH0A0HYM2",
)


@dataclass(frozen=True)
class LiteratureBacktestConfig:
    signatures_path: str = "config/literature_strategy_signatures_9419.csv"
    manifest_path: str = "config/diversified_seed_dataset.yaml"
    train_start: str = TRAIN_START
    train_end: str = TRAIN_END
    validation_start: str = VALIDATION_START
    validation_end: str = VALIDATION_END
    locked_start: str = LOCKED_START
    expected_signatures: int = 9419
    min_train_observations: int = 36
    min_validation_observations: int = 12


def load_signatures(path: str | Path, *, expected: int = 9419) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "signature_hash",
        "distinct_strategy_signature",
        "primary_family",
        "asset_bucket",
        "signal_bucket",
        "action_bucket",
        "frequency_bucket",
        "parameter_bucket",
        "exact_rows",
        "template_rows",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"signature manifest missing columns: {missing}")
    if frame["signature_hash"].duplicated().any():
        dupes = frame.loc[frame["signature_hash"].duplicated(), "signature_hash"].head(5).tolist()
        raise ValueError(f"duplicate signature_hash values: {dupes}")
    if len(frame) != expected:
        raise ValueError(f"expected {expected} signatures, found {len(frame)}")
    return frame.reset_index(drop=True)


def chunk_bounds(total: int, chunks: int, chunk_index: int) -> tuple[int, int]:
    if chunks <= 0:
        raise ValueError("chunks must be > 0")
    if chunk_index < 0 or chunk_index >= chunks:
        raise ValueError("chunk_index out of range")
    start = math.floor(total * chunk_index / chunks)
    end = math.floor(total * (chunk_index + 1) / chunks)
    return start, end


def load_dataset(config: LiteratureBacktestConfig) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((repo_root / config.manifest_path).read_text(encoding="utf-8"))
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    symbols_by_bucket = _symbols_by_bucket(manifest)
    prices = _load_price_panel(store, symbols_by_bucket, start=config.train_start, end=config.validation_end)
    context = _load_context_panel(store, start=config.train_start, end=config.validation_end)
    if prices.empty:
        raise ValueError("no price data available for literature backtests")
    if pd.Timestamp(config.validation_end) >= pd.Timestamp(config.locked_start):
        raise ValueError("validation_end must be before locked_start")
    daily_returns = prices.pct_change()
    return {
        "prices": prices,
        "returns": daily_returns,
        "context": context.reindex(prices.index).ffill() if not context.empty else context,
        "symbols_by_bucket": symbols_by_bucket,
        "locked_opened": False,
        "train_start": config.train_start,
        "train_end": config.train_end,
        "validation_start": config.validation_start,
        "validation_end": config.validation_end,
        "locked_start": config.locked_start,
    }


def synthetic_dataset() -> dict[str, Any]:
    idx = pd.date_range("1995-01-03", "2020-12-31", freq="B")
    wave = np.sin(np.arange(len(idx)) / 19.0) * 0.002 + 0.0002
    prices = pd.DataFrame(
        {
            "SPY": 100.0 * np.cumprod(1.0 + wave),
            "QQQ": 80.0 * np.cumprod(1.0 + wave * 1.2),
            "TLT": 90.0 * np.cumprod(1.0 - wave * 0.4 + 0.0001),
        },
        index=idx,
    )
    return {
        "prices": prices,
        "returns": prices.pct_change(),
        "context": pd.DataFrame(
            {
                "VIXCLS": 20.0 + np.cos(np.arange(len(idx)) / 13.0),
                "DGS10": 3.0 + np.sin(np.arange(len(idx)) / 250.0),
            },
            index=idx,
        ),
        "symbols_by_bucket": {
            "equity_index": ("SPY", "QQQ"),
            "rates_fixed_income": ("TLT",),
        },
        "locked_opened": False,
    }


def run_chunk(
    signatures: pd.DataFrame,
    dataset: dict[str, Any],
    config: LiteratureBacktestConfig,
    *,
    chunk_index: int,
    chunks: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    start, end = chunk_bounds(len(signatures), chunks, chunk_index)
    rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for _, row in signatures.iloc[start:end].iterrows():
        record = row.to_dict()
        manifest_rows.append(record)
        try:
            rows.append(evaluate_signature(record, dataset, config))
        except Exception as exc:  # keep chunk alive; merge reports errors
            rows.append(_base_output(record) | {
                "status": "error",
                "unsupported_reason": "",
                "error": f"{type(exc).__name__}: {exc}",
                "locked_opened": False,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
            })
    summary = {
        "chunk_index": int(chunk_index),
        "chunks": int(chunks),
        "start": int(start),
        "end": int(end),
        "rows": int(len(rows)),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    }
    return pd.DataFrame(rows), pd.DataFrame(manifest_rows), summary


def evaluate_signature(row: dict[str, Any], dataset: dict[str, Any], config: LiteratureBacktestConfig) -> dict[str, Any]:
    base = _base_output(row)
    spec, reason = signature_to_spec(row, dataset)
    if reason:
        return base | _unsupported(reason)

    frequency = spec["frequency"]
    ppy = PERIODS_PER_YEAR[frequency]
    returns = _resample_returns(dataset["returns"].loc[:, list(spec["symbols"])], frequency)
    context = _resample_context(dataset["context"], frequency, returns.index)
    signal = build_signal(returns, context, spec)
    weights = build_weights(signal, spec)
    base_returns = portfolio_returns(returns, weights)

    train_mask = _between(base_returns.index, config.train_start, config.train_end)
    valid_mask = _between(base_returns.index, config.validation_start, config.validation_end)
    train_base = base_returns.loc[train_mask]
    valid_base = base_returns.loc[valid_mask]
    train_weights = weights.loc[train_mask]
    valid_weights = weights.loc[valid_mask]

    if int(train_base.dropna().shape[0]) < config.min_train_observations:
        return base | _unsupported("unsupported_not_enough_history")
    if int(valid_base.dropna().shape[0]) < config.min_validation_observations:
        return base | _unsupported("unsupported_not_enough_validation_history")

    size, train_metrics = choose_train_size(train_base, ppy)
    train_sized = train_base * size
    valid_sized = valid_base * size
    train_1x = metrics_dict(train_base, ppy, "train_1x")
    valid_1x = metrics_dict(valid_base, ppy, "validation_1x")
    train = metrics_dict(train_sized, ppy, "train")
    validation = metrics_dict(valid_sized, ppy, "validation")
    effective_start = str(train_base.dropna().index.min().date())
    score = train_score(train_metrics, train_base, train_weights)
    return base | {
        "status": "evaluated",
        "unsupported_reason": "",
        "error": "",
        "candidate_id": candidate_id_from_signature(row),
        "spec_json": json.dumps(spec, sort_keys=True),
        "frequency_tested": frequency,
        "symbols": "|".join(spec["symbols"]),
        "size_chosen_train": float(size),
        "train_score": float(score),
        "effective_start": effective_start,
        "train_observations": int(train_base.dropna().shape[0]),
        "validation_observations": int(valid_base.dropna().shape[0]),
        "train_trades_per_month": trades_per_month(train_weights, train_base.index, ppy),
        "validation_trades_per_month": trades_per_month(valid_weights, valid_base.index, ppy),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    } | train_1x | valid_1x | train | validation


def signature_to_spec(row: dict[str, Any], dataset: dict[str, Any]) -> tuple[dict[str, Any], str]:
    asset_bucket = str(row.get("asset_bucket") or "")
    signal_bucket = str(row.get("signal_bucket") or "")
    action_bucket = str(row.get("action_bucket") or "")
    frequency_bucket = str(row.get("frequency_bucket") or "")
    if frequency_bucket == "intraday":
        return {}, "unsupported_frequency_intraday"
    frequency = "monthly_template" if frequency_bucket == "unspecified" else frequency_bucket
    if frequency not in PERIODS_PER_YEAR:
        return {}, "unsupported_frequency"
    symbols = available_symbols_for_bucket(asset_bucket, dataset)
    if not symbols:
        return {}, "unsupported_no_asset_mapping"
    if signal_bucket not in {
        "momentum_trend",
        "reversal_mean_reversion",
        "volatility_signal",
        "carry_yield",
        "liquidity",
        "macro_inflation",
        "macro_growth_unemployment",
        "geopolitical_policy_uncertainty",
        "value_quality_factor",
        "ml_forecast",
        "correlation_spillover",
        "regime_switching",
        "credit_spread_signal",
        "sentiment_news",
        "portfolio_optimization",
    }:
        return {}, "unsupported_no_signal_mapping"
    if action_bucket not in {
        "forecast_rank_template",
        "long_short_cross_section",
        "hedge_safe_haven",
        "market_timing",
        "rotation_allocation",
        "template_relationship",
    }:
        return {}, "unsupported_no_action_mapping"
    return {
        "signature_hash": str(row["signature_hash"]),
        "asset_bucket": asset_bucket,
        "signal_bucket": signal_bucket,
        "action_bucket": action_bucket,
        "frequency": frequency,
        "parameter_bucket": str(row.get("parameter_bucket") or ""),
        "symbols": tuple(symbols),
        "lookback": lookback_from_parameter(str(row.get("parameter_bucket") or ""), frequency),
    }, ""


def available_symbols_for_bucket(asset_bucket: str, dataset: dict[str, Any]) -> tuple[str, ...]:
    symbols_by_bucket: dict[str, tuple[str, ...]] = dataset["symbols_by_bucket"]
    returns: pd.DataFrame = dataset["returns"]
    preferred = PREFERRED_SYMBOLS.get(asset_bucket, tuple())
    allowed_groups = ASSET_BUCKET_GROUPS.get(asset_bucket)
    if not allowed_groups:
        return tuple()
    allowed: list[str] = []
    for group in allowed_groups:
        allowed.extend(symbols_by_bucket.get(group, tuple()))
    ordered = [s for s in preferred if s in allowed and s in returns.columns]
    ordered.extend(s for s in allowed if s not in ordered and s in returns.columns)
    return tuple(ordered[:16])


def build_signal(returns: pd.DataFrame, context: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    lookback = int(spec["lookback"])
    signal_bucket = spec["signal_bucket"]
    if signal_bucket == "momentum_trend":
        signal = (1.0 + returns).rolling(lookback, min_periods=max(2, lookback // 2)).apply(np.prod, raw=True) - 1.0
    elif signal_bucket == "reversal_mean_reversion":
        signal = -returns.rolling(lookback, min_periods=max(2, lookback // 2)).mean()
    elif signal_bucket == "volatility_signal":
        vol = returns.rolling(lookback, min_periods=max(2, lookback // 2)).std()
        signal = -vol
        if "VIXCLS" in context.columns:
            vix = -context["VIXCLS"].pct_change().rolling(max(2, lookback // 2)).mean()
            signal = signal.add(vix, axis=0)
    elif signal_bucket in {"carry_yield", "macro_inflation", "macro_growth_unemployment", "liquidity", "credit_spread_signal"}:
        macro = macro_signal(context, signal_bucket, returns.index, lookback)
        trend = returns.rolling(max(2, lookback // 2), min_periods=2).mean()
        signal = trend.add(macro, axis=0)
    elif signal_bucket in {"value_quality_factor", "portfolio_optimization"}:
        signal = returns.rolling(lookback, min_periods=max(2, lookback // 2)).mean() / returns.rolling(lookback, min_periods=max(2, lookback // 2)).std()
    elif signal_bucket in {"geopolitical_policy_uncertainty", "sentiment_news", "regime_switching", "correlation_spillover", "ml_forecast"}:
        vol = returns.rolling(lookback, min_periods=max(2, lookback // 2)).std()
        mom = returns.rolling(max(2, lookback // 2), min_periods=2).mean()
        signal = mom - vol
    else:
        signal = returns.rolling(lookback, min_periods=max(2, lookback // 2)).mean()
    return signal.replace([np.inf, -np.inf], np.nan)


def macro_signal(context: pd.DataFrame, signal_bucket: str, index: pd.Index, lookback: int) -> pd.Series:
    if context.empty:
        return pd.Series(0.0, index=index)
    ctx = context.reindex(index).ffill()
    if signal_bucket == "macro_inflation" and "CPIAUCSL" in ctx.columns:
        raw = -ctx["CPIAUCSL"].pct_change(max(1, lookback))
    elif signal_bucket == "macro_growth_unemployment" and "UNRATE" in ctx.columns:
        raw = -ctx["UNRATE"].diff(max(1, lookback))
    elif signal_bucket == "credit_spread_signal" and "BAMLH0A0HYM2" in ctx.columns:
        raw = -ctx["BAMLH0A0HYM2"].diff(max(1, lookback))
    elif signal_bucket == "carry_yield" and "DGS10" in ctx.columns:
        raw = ctx["DGS10"].rolling(max(2, lookback), min_periods=2).mean()
    elif signal_bucket == "liquidity" and "FEDFUNDS" in ctx.columns:
        raw = -ctx["FEDFUNDS"].diff(max(1, lookback))
    else:
        raw = pd.Series(0.0, index=index)
    std = raw.rolling(max(6, lookback), min_periods=2).std()
    return (raw / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def build_weights(signal: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    action = spec["action_bucket"]
    if action in {"long_short_cross_section", "forecast_rank_template"} and signal.shape[1] >= 2:
        ranks = signal.rank(axis=1, pct=True)
        if action == "long_short_cross_section":
            weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
            weights[ranks >= 0.70] = 1.0
            weights[ranks <= 0.30] = -1.0
            return normalize_weights(weights)
        weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
        weights[ranks >= 0.75] = 1.0
        return normalize_weights(weights)
    if action == "rotation_allocation" and signal.shape[1] >= 2:
        ranks = signal.rank(axis=1, pct=True)
        weights = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
        weights[ranks >= 0.80] = 1.0
        return normalize_weights(weights)
    if action == "hedge_safe_haven":
        raw = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
        stress = signal.mean(axis=1)
        raw.loc[stress > stress.rolling(24, min_periods=4).median(), :] = 1.0
        return normalize_weights(raw)
    exposure = np.sign(signal.mean(axis=1)).replace(0.0, np.nan).fillna(0.0)
    raw = pd.DataFrame(0.0, index=signal.index, columns=signal.columns)
    if signal.shape[1] == 1:
        raw.iloc[:, 0] = exposure
    else:
        raw = signal.rank(axis=1, pct=True).sub(0.5).mul(2.0).mul(exposure, axis=0)
    return normalize_weights(raw)


def normalize_weights(weights: pd.DataFrame) -> pd.DataFrame:
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    return weights.div(gross, axis=0).fillna(0.0)


def portfolio_returns(returns: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    aligned_returns = returns.reindex(weights.index).shift(-1)
    out = (weights * aligned_returns).sum(axis=1, min_count=1)
    no_exposure = weights.abs().sum(axis=1) <= 0.0
    out.loc[no_exposure] = 0.0
    return out


def choose_train_size(base_returns: pd.Series, ppy: int) -> tuple[float, dict[str, float]]:
    best_size = 0.0
    best_metrics = metrics_raw(base_returns * 0.0, ppy)
    best_score = -math.inf
    for size in SIZE_GRID:
        sized = base_returns * size
        finite = sized.dropna()
        if finite.empty:
            continue
        nav = (1.0 + finite).cumprod()
        if (nav <= 0.0).any():
            continue
        metrics = metrics_raw(sized, ppy)
        score = float(metrics.get("sharpe", 0.0)) + float(metrics.get("calmar", 0.0))
        if score > best_score:
            best_score = score
            best_size = float(size)
            best_metrics = metrics
    return best_size, best_metrics


def metrics_raw(returns: pd.Series, ppy: int) -> dict[str, float]:
    return compute_metrics(returns.to_numpy(dtype=float), ppy=ppy).to_dict()


def metrics_dict(returns: pd.Series, ppy: int, prefix: str) -> dict[str, float]:
    metrics = metrics_raw(returns, ppy)
    positive_months = positive_period_pct(returns, "ME")
    positive_years = positive_period_pct(returns, "YE")
    keep = {
        "cagr": metrics["cagr"],
        "sharpe": metrics["sharpe"],
        "calmar": metrics["calmar"],
        "mdd": metrics["mdd"],
        "profit_factor": metrics["profit_factor"],
        "win_rate": metrics["win_rate"],
        "final_nav": metrics["final_nav"],
        "n_periods": metrics["n_periods"],
    }
    out = {f"{prefix}_{key}": value for key, value in keep.items()}
    out[f"{prefix}_positive_months_pct"] = positive_months
    out[f"{prefix}_positive_years_pct"] = positive_years
    return out


def positive_period_pct(returns: pd.Series, freq: str) -> float:
    finite = returns.dropna()
    if finite.empty:
        return float("nan")
    compounded = (1.0 + finite).resample(freq).prod(min_count=1) - 1.0
    compounded = compounded.dropna()
    if compounded.empty:
        return float("nan")
    return round(float((compounded > 0.0).mean() * 100.0), 4)


def trades_per_month(weights: pd.DataFrame, index: pd.Index, ppy: int) -> float:
    if weights.empty or len(weights) < 2:
        return 0.0
    changed = weights.diff().abs().sum(axis=1).fillna(0.0) > 1e-9
    months = max(len(weights) / ppy * 12.0, 1e-9)
    return round(float(changed.sum() / months), 4)


def train_score(metrics: dict[str, float], base_returns: pd.Series, weights: pd.DataFrame) -> float:
    return (
        float(metrics.get("sharpe", 0.0))
        + float(metrics.get("calmar", 0.0))
        + 0.01 * float(metrics.get("cagr", 0.0))
        - 0.001 * trades_per_month(weights, base_returns.index, 252)
    )


def candidate_id_from_signature(row: dict[str, Any]) -> str:
    payload = {
        "signature_hash": str(row["signature_hash"]),
        "distinct_strategy_signature": str(row.get("distinct_strategy_signature", "")),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"lit_{digest}"


def lookback_from_parameter(parameter_bucket: str, frequency: str) -> int:
    numbers = [int(x) for x in __import__("re").findall(r"\d+", parameter_bucket or "")]
    if numbers:
        return max(2, min(max(numbers), 260))
    defaults = {
        "daily": 126,
        "weekly": 26,
        "monthly": 12,
        "monthly_template": 12,
        "quarterly": 4,
        "annual": 3,
    }
    return defaults.get(frequency, 12)


def _symbols_by_bucket(manifest: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {}
    for section in manifest.get("sections", {}).values():
        group = str(section.get("asset_group") or "")
        for symbol in section.get("symbols", []) or []:
            out.setdefault(group, []).append(str(symbol))
    return {key: tuple(dict.fromkeys(values)) for key, values in out.items()}


def _load_price_panel(
    store: TimeSeriesStore,
    symbols_by_bucket: dict[str, tuple[str, ...]],
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    for group in ("equity_index", "equity_sector", "equity_single_name", "rates_fixed_income", "commodity", "fx_spot", "crypto_spot"):
        library = "fx_daily" if group == "fx_spot" else "crypto_daily" if group == "crypto_spot" else "prices_daily"
        for symbol in symbols_by_bucket.get(group, tuple()):
            try:
                frame = store.read(library, symbol, start=start, end=end)
            except Exception:
                continue
            column = "adj_close" if "adj_close" in frame.columns else "close" if "close" in frame.columns else "value" if "value" in frame.columns else ""
            if column:
                series[symbol] = pd.to_numeric(frame[column], errors="coerce")
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index().ffill()


def _load_context_panel(store: TimeSeriesStore, *, start: str, end: str) -> pd.DataFrame:
    series: dict[str, pd.Series] = {}
    for symbol in CONTEXT_SYMBOLS:
        try:
            frame = store.read("macro_daily", symbol, start=start, end=end)
        except Exception:
            continue
        column = "value" if "value" in frame.columns else "close" if "close" in frame.columns else ""
        if column:
            series[symbol] = pd.to_numeric(frame[column], errors="coerce")
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index().ffill()


def _resample_returns(returns: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if frequency == "daily":
        return returns
    freq = {
        "weekly": "W-FRI",
        "monthly": "ME",
        "monthly_template": "ME",
        "quarterly": "QE",
        "annual": "YE",
    }[frequency]
    return (1.0 + returns).resample(freq).prod(min_count=1) - 1.0


def _resample_context(context: pd.DataFrame, frequency: str, index: pd.Index) -> pd.DataFrame:
    if context.empty:
        return context
    if frequency == "daily":
        return context.reindex(index).ffill()
    return context.resample({
        "weekly": "W-FRI",
        "monthly": "ME",
        "monthly_template": "ME",
        "quarterly": "QE",
        "annual": "YE",
    }[frequency]).last().reindex(index).ffill()


def _between(index: pd.Index, start: str, end: str) -> np.ndarray:
    idx = pd.to_datetime(index)
    return (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))


def _base_output(row: dict[str, Any]) -> dict[str, Any]:
    exact_rows = int(float(row.get("exact_rows", 0) or 0))
    template_rows = int(float(row.get("template_rows", 0) or 0))
    return {
        "signature_hash": str(row.get("signature_hash", "")),
        "candidate_id": candidate_id_from_signature(row) if row.get("signature_hash") else "",
        "distinct_strategy_signature": str(row.get("distinct_strategy_signature", "")),
        "primary_family": str(row.get("primary_family", "")),
        "asset_bucket": str(row.get("asset_bucket", "")),
        "signal_bucket": str(row.get("signal_bucket", "")),
        "action_bucket": str(row.get("action_bucket", "")),
        "frequency_bucket": str(row.get("frequency_bucket", "")),
        "parameter_bucket": str(row.get("parameter_bucket", "")),
        "exact_rows": exact_rows,
        "template_rows": template_rows,
        "source_exactness": "exact_source" if exact_rows > 0 else "template_only",
        "paper_exact_replication_claimed": False,
    }


def _unsupported(reason: str) -> dict[str, Any]:
    return {
        "status": "unsupported",
        "unsupported_reason": reason,
        "error": "",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    }

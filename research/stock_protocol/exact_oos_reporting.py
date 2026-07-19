"""Reporting and statistical tests for one frozen exact OOS strategy."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .locked_access import LockedDataAuthorization
from .metrics import compute_portfolio_metrics
from .robustness import block_bootstrap_records, deflated_sharpe_ratio


TRADING_DAYS = 252.0


def curve_returns(curve: pd.DataFrame) -> pd.Series:
    values = curve.sort_values("date").copy()
    returns = pd.to_numeric(values["equity"], errors="raise").pct_change(
        fill_method=None
    ).dropna()
    if len(returns) < 30 or not np.isfinite(returns).all():
        raise ValueError("OOS curve has insufficient finite daily returns")
    return returns.reset_index(drop=True)


def spy_benchmark(
    strategy_curve: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    authorization: LockedDataAuthorization | None,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Build dividend-adjusted SPY buy-and-hold on identical curve dates."""

    dates = pd.to_datetime(strategy_curve["date"], errors="raise").dt.normalize()
    spy = panel.loc[panel["symbol"].astype(str).eq("SPY"), ["date", "adj_close"]].copy()
    spy["date"] = pd.to_datetime(spy["date"], errors="raise").dt.normalize()
    spy["adj_close"] = pd.to_numeric(spy["adj_close"], errors="coerce")
    spy = spy.dropna().drop_duplicates("date", keep="last").sort_values("date")
    if spy.empty or spy["date"].max() < dates.max():
        raise ValueError("SPY total-return benchmark does not reach locked end")
    spy_series = spy.set_index("date")["adj_close"]
    indexed = (
        spy_series.reindex(spy_series.index.union(pd.DatetimeIndex(dates)))
        .sort_index()
        .ffill()
        .reindex(dates)
    )
    if indexed.isna().any() or indexed.le(0).any():
        raise ValueError("SPY benchmark cannot align to exact strategy dates")
    equity = 100_000.0 * indexed.to_numpy(dtype=float) / float(indexed.iloc[0])
    curve = pd.DataFrame(
        {
            "date": dates.to_numpy(),
            "equity": equity,
            "cash": np.zeros(len(dates), dtype=float),
            "market_value": equity,
            "gross_exposure": np.ones(len(dates), dtype=float),
            "turnover": np.zeros(len(dates), dtype=float),
            "costs": np.zeros(len(dates), dtype=float),
        }
    )
    metrics = compute_portfolio_metrics(
        curve,
        pd.DataFrame(),
        locked_authorization=authorization,
    )
    return curve, metrics


def relative_metrics(
    strategy_curve: pd.DataFrame,
    spy_curve: pd.DataFrame,
) -> dict[str, float]:
    merged = strategy_curve[["date", "equity"]].merge(
        spy_curve[["date", "equity"]],
        on="date",
        suffixes=("_strategy", "_spy"),
        validate="one_to_one",
    )
    strategy_returns = merged["equity_strategy"].pct_change(fill_method=None)
    spy_returns = merged["equity_spy"].pct_change(fill_method=None)
    paired = pd.DataFrame(
        {"strategy": strategy_returns, "spy": spy_returns}
    ).dropna()
    if len(paired) < 30:
        raise ValueError("insufficient paired SPY observations")
    variance = float(paired["spy"].var(ddof=1))
    beta = (
        float(paired["strategy"].cov(paired["spy"]) / variance)
        if variance > 0
        else 0.0
    )
    alpha = float((paired["strategy"].mean() - beta * paired["spy"].mean()) * TRADING_DAYS)
    monthly = (
        merged.set_index("date")[["equity_strategy", "equity_spy"]]
        .resample("ME")
        .last()
        .pct_change(fill_method=None)
        .dropna()
    )
    yearly = (
        merged.set_index("date")[["equity_strategy", "equity_spy"]]
        .resample("YE")
        .last()
        .pct_change(fill_method=None)
        .dropna()
    )
    result = {
        "daily_correlation": float(paired["strategy"].corr(paired["spy"])),
        "beta": beta,
        "alpha_annualized": alpha,
        "months_outperform_pct": float((monthly["equity_strategy"] > monthly["equity_spy"]).mean()),
        "years_outperform_pct": float((yearly["equity_strategy"] > yearly["equity_spy"]).mean()) if len(yearly) else 0.0,
    }
    if not np.isfinite(list(result.values())).all():
        raise ValueError("relative SPY metrics are non-finite")
    return result


def yearly_comparison(
    strategy_curve: pd.DataFrame,
    spy_curve: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    period: str,
) -> pd.DataFrame:
    strategy = strategy_curve.copy()
    spy = spy_curve.copy()
    strategy["date"] = pd.to_datetime(strategy["date"], errors="raise").dt.normalize()
    spy["date"] = pd.to_datetime(spy["date"], errors="raise").dt.normalize()
    rows: list[dict[str, Any]] = []
    closed = trades.copy()
    if not closed.empty:
        if "status" in closed.columns:
            closed = closed.loc[closed["status"].astype(str).eq("closed")].copy()
        closed["exit_date"] = pd.to_datetime(closed["exit_date"], errors="raise").dt.normalize()
    for year, year_curve in strategy.groupby(strategy["date"].dt.year, sort=True):
        spy_year = spy.loc[spy["date"].dt.year.eq(year)]
        if spy_year.empty:
            continue
        strategy_return = float(year_curve["equity"].iloc[-1] / year_curve["equity"].iloc[0] - 1.0)
        spy_return = float(spy_year["equity"].iloc[-1] / spy_year["equity"].iloc[0] - 1.0)
        drawdown = pd.to_numeric(year_curve["equity"], errors="raise").div(
            pd.to_numeric(year_curve["equity"], errors="raise").cummax()
        ).sub(1.0)
        year_trades = (
            closed.loc[closed["exit_date"].dt.year.eq(year)].copy()
            if not closed.empty
            else closed
        )
        returns = pd.to_numeric(
            year_trades.get("net_return", year_trades.get("gross_return", pd.Series(dtype=float))),
            errors="coerce",
        ).dropna()
        reasons = year_trades.get("exit_reason", pd.Series(dtype=str)).astype(str)
        rows.append(
            {
                "period": period,
                "year": int(year),
                "strategy_return": strategy_return,
                "spy_return": spy_return,
                "difference": strategy_return - spy_return,
                "strategy_max_drawdown": float(drawdown.min()),
                "average_exposure": float(pd.to_numeric(year_curve.get("gross_exposure", 0.0), errors="coerce").mean()),
                "operations": int(len(year_trades)),
                "win_rate": float((returns > 0).mean()) if len(returns) else 0.0,
                "take_profits": int(reasons.isin(["take_profit", "gap_through_target"]).sum()),
                "time_exits": int(reasons.eq("time_exit").sum()),
            }
        )
    return pd.DataFrame(rows)


def _probabilistic_sharpe(returns: pd.Series, target_annual_sharpe: float) -> float:
    values = pd.to_numeric(returns, errors="raise").to_numpy(dtype=float)
    deviation = float(values.std(ddof=1))
    if len(values) < 30 or deviation <= 0:
        raise ValueError("probabilistic Sharpe requires variable returns")
    daily_sharpe = float(values.mean() / deviation)
    target = float(target_annual_sharpe) / math.sqrt(TRADING_DAYS)
    skewness = float(stats.skew(values, bias=False))
    kurtosis = float(stats.kurtosis(values, fisher=False, bias=False))
    denominator = math.sqrt(
        max(1.0 - skewness * daily_sharpe + ((kurtosis - 1.0) / 4.0) * daily_sharpe**2, 1e-15)
    )
    z_value = (daily_sharpe - target) * math.sqrt(len(values) - 1.0) / denominator
    return float(NormalDist().cdf(z_value))


def statistical_validation(
    strategy_curve: pd.DataFrame,
    spy_curve: pd.DataFrame,
    *,
    bootstrap_samples: int = 5000,
    seed: int = 20210719,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run one-strategy paired and block-bootstrap inference."""

    merged = strategy_curve[["date", "equity"]].merge(
        spy_curve[["date", "equity"]],
        on="date",
        suffixes=("_strategy", "_spy"),
        validate="one_to_one",
    )
    strategy_returns = merged["equity_strategy"].pct_change(fill_method=None).dropna().reset_index(drop=True)
    spy_returns = merged["equity_spy"].pct_change(fill_method=None).dropna().reset_index(drop=True)
    if len(strategy_returns) != len(spy_returns):
        raise ValueError("strategy and SPY returns are not paired")
    bootstrap = block_bootstrap_records(
        strategy_returns,
        n_samples=bootstrap_samples,
        block_size=min(20, len(strategy_returns)),
        seed=seed,
        variant="single_frozen_true_oos",
    )
    rng = np.random.default_rng(seed + 1)
    strategy_values = strategy_returns.to_numpy(dtype=float)
    spy_values = spy_returns.to_numpy(dtype=float)
    count = len(strategy_values)
    block_size = min(20, count)
    blocks_needed = int(math.ceil(count / block_size))
    cagr_samples: list[float] = []
    mean_samples: list[float] = []
    difference_samples: list[float] = []
    for _ in range(bootstrap_samples):
        starts = rng.integers(0, count, size=blocks_needed)
        indices = np.concatenate(
            [(int(start) + np.arange(block_size)) % count for start in starts]
        )[:count]
        strategy_sample = strategy_values[indices]
        spy_sample = spy_values[indices]
        cagr_samples.append(float(np.prod(1.0 + strategy_sample) ** (TRADING_DAYS / count) - 1.0))
        mean_samples.append(float(strategy_sample.mean()))
        strategy_std = float(strategy_sample.std(ddof=1))
        spy_std = float(spy_sample.std(ddof=1))
        strategy_sharpe = float(strategy_sample.mean() / strategy_std * math.sqrt(TRADING_DAYS)) if strategy_std > 0 else 0.0
        spy_sharpe = float(spy_sample.mean() / spy_std * math.sqrt(TRADING_DAYS)) if spy_std > 0 else 0.0
        difference_samples.append(strategy_sharpe - spy_sharpe)
    spy_std = float(spy_returns.std(ddof=1))
    spy_sharpe = float(spy_returns.mean() / spy_std * math.sqrt(TRADING_DAYS)) if spy_std > 0 else 0.0
    paired = stats.ttest_rel(strategy_returns, spy_returns, nan_policy="raise")
    regression = stats.linregress(spy_returns, strategy_returns)
    dsr = deflated_sharpe_ratio(strategy_returns, n_trials=290)
    rows = [
        {
            "test": "block_bootstrap_sharpe",
            "estimate": float(bootstrap["sharpe"].median()),
            "lower_95": float(bootstrap["sharpe"].quantile(0.025)),
            "upper_95": float(bootstrap["sharpe"].quantile(0.975)),
            "p_value": float((bootstrap["sharpe"] <= 0).mean()),
            "applicable": True,
        },
        {
            "test": "bootstrap_cagr",
            "estimate": float(np.median(cagr_samples)),
            "lower_95": float(np.quantile(cagr_samples, 0.025)),
            "upper_95": float(np.quantile(cagr_samples, 0.975)),
            "p_value": float(np.mean(np.asarray(cagr_samples) <= 0)),
            "applicable": True,
        },
        {
            "test": "bootstrap_mean_daily_return",
            "estimate": float(np.median(mean_samples)),
            "lower_95": float(np.quantile(mean_samples, 0.025)),
            "upper_95": float(np.quantile(mean_samples, 0.975)),
            "p_value": float(np.mean(np.asarray(mean_samples) <= 0)),
            "applicable": True,
        },
        {
            "test": "probabilistic_sharpe_vs_zero",
            "estimate": _probabilistic_sharpe(strategy_returns, 0.0),
            "lower_95": np.nan,
            "upper_95": np.nan,
            "p_value": np.nan,
            "applicable": True,
        },
        {
            "test": "probabilistic_sharpe_vs_spy",
            "estimate": _probabilistic_sharpe(strategy_returns, spy_sharpe),
            "lower_95": np.nan,
            "upper_95": np.nan,
            "p_value": np.nan,
            "applicable": True,
        },
        {
            "test": "bootstrap_sharpe_difference_vs_spy",
            "estimate": float(np.median(difference_samples)),
            "lower_95": float(np.quantile(difference_samples, 0.025)),
            "upper_95": float(np.quantile(difference_samples, 0.975)),
            "p_value": float(np.mean(np.asarray(difference_samples) <= 0)),
            "applicable": True,
        },
        {
            "test": "paired_daily_return_ttest",
            "estimate": float((strategy_returns - spy_returns).mean()),
            "lower_95": np.nan,
            "upper_95": np.nan,
            "p_value": float(paired.pvalue),
            "applicable": True,
        },
        {
            "test": "regression_alpha_annualized",
            "estimate": float(regression.intercept * TRADING_DAYS),
            "lower_95": np.nan,
            "upper_95": np.nan,
            "p_value": float(regression.pvalue),
            "beta": float(regression.slope),
            "applicable": True,
        },
        {
            "test": "deflated_sharpe_290_trials",
            "estimate": float(dsr["probability"]),
            "lower_95": np.nan,
            "upper_95": np.nan,
            "p_value": np.nan,
            "expected_max_sharpe": float(dsr["expected_max_sharpe"]),
            "applicable": True,
        },
    ]
    for name in ("white_reality_check", "spa", "cscv_pbo"):
        rows.append(
            {
                "test": name,
                "estimate": np.nan,
                "lower_95": np.nan,
                "upper_95": np.nan,
                "p_value": np.nan,
                "applicable": False,
                "reason": "one_previously_frozen_strategy_no_oos_variant_selection",
            }
        )
    return pd.DataFrame(rows), bootstrap


def classify_verdict(
    strategy_metrics: dict[str, float],
    spy_metrics: dict[str, float],
    statistics: pd.DataFrame,
) -> str:
    indexed = statistics.set_index("test")
    bootstrap_lower = float(indexed.loc["block_bootstrap_sharpe", "lower_95"])
    paired_p = float(indexed.loc["paired_daily_return_ttest", "p_value"])
    paired_excess = float(indexed.loc["paired_daily_return_ttest", "estimate"])
    strict = (
        strategy_metrics["total_return"] > 0
        and strategy_metrics["cagr"] > spy_metrics["cagr"]
        and strategy_metrics["sharpe"] > spy_metrics["sharpe"]
        and bootstrap_lower > 0
        and paired_excess > 0
        and paired_p <= 0.05
    )
    if strict:
        return "validated_out_of_sample"
    if strategy_metrics["total_return"] > 0 and strategy_metrics["sharpe"] > 0:
        return "promising_but_inconclusive"
    return "failed_out_of_sample"

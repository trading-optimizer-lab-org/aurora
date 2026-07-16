from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WithdrawalSimulation:
    start_date: str
    months_tested: int
    survived: bool
    failure_date: str | None
    final_capital: float
    min_capital: float
    max_drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SafeWithdrawalResult:
    initial_capital: float
    target_monthly_withdrawal: float
    target_swr_annual_pct: float
    max_safe_monthly_withdrawal: float
    swr_annual_pct: float
    target_monthly_pass: bool
    eligible_start_count: int
    failed_start_count_at_target: int
    min_horizon_months: int
    worst_start_date: str | None
    worst_start_final_capital: float
    worst_start_min_capital: float
    worst_start_max_drawdown: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compound_returns_to_monthly(
    returns: pd.Series | pd.DataFrame,
    *,
    return_column: str = "strategy_return",
    timestamp_column: str = "timestamp",
) -> pd.Series:
    """Compound daily/weekly/periodic returns into calendar monthly returns.

    Input returns are decimals: 0.01 means +1%.
    """

    series = _as_return_series(returns, return_column=return_column, timestamp_column=timestamp_column)
    if series.empty:
        return pd.Series(dtype=float, name="monthly_return")
    monthly = (1.0 + series).groupby(series.index.to_period("M")).prod() - 1.0
    monthly.index = monthly.index.to_timestamp(how="end")
    monthly.name = "monthly_return"
    return monthly.astype(float)


def simulate_monthly_withdrawal(
    monthly_returns: pd.Series,
    *,
    initial_capital: float = 100_000.0,
    monthly_withdrawal: float = 1_000.0,
    start_index: int = 0,
    withdraw_at_start: bool = True,
) -> WithdrawalSimulation:
    """Simulate one retirement path from one monthly start date.

    Withdrawal is nominal and fixed. If NAV is <= 0 after withdrawal or after
    applying the monthly return, the path is considered failed.
    """

    monthly = _clean_monthly_returns(monthly_returns)
    if start_index < 0 or start_index >= len(monthly):
        raise IndexError("start_index outside monthly return series")

    path = monthly.iloc[start_index:]
    capital = float(initial_capital)
    nav_values = [capital]
    failure_date: str | None = None

    for timestamp, period_return in path.items():
        if withdraw_at_start:
            capital -= float(monthly_withdrawal)
            if capital <= 0:
                failure_date = pd.Timestamp(timestamp).date().isoformat()
                nav_values.append(capital)
                break

        capital *= 1.0 + float(period_return)
        if not np.isfinite(capital) or capital <= 0:
            failure_date = pd.Timestamp(timestamp).date().isoformat()
            nav_values.append(capital)
            break

        if not withdraw_at_start:
            capital -= float(monthly_withdrawal)
            if capital <= 0:
                failure_date = pd.Timestamp(timestamp).date().isoformat()
                nav_values.append(capital)
                break

        nav_values.append(capital)

    nav = np.asarray(nav_values, dtype=float)
    max_drawdown = _max_drawdown(nav)
    start_date = pd.Timestamp(path.index[0]).date().isoformat()
    months_tested = int(len(nav_values) - 1)
    return WithdrawalSimulation(
        start_date=start_date,
        months_tested=months_tested,
        survived=failure_date is None,
        failure_date=failure_date,
        final_capital=round(float(nav[-1]), 6),
        min_capital=round(float(np.nanmin(nav)), 6),
        max_drawdown=round(float(max_drawdown), 6),
    )


def safe_withdrawal_rate(
    returns: pd.Series | pd.DataFrame,
    *,
    return_column: str = "strategy_return",
    timestamp_column: str = "timestamp",
    initial_capital: float = 100_000.0,
    target_monthly_withdrawal: float = 1_000.0,
    min_horizon_months: int = 1,
    withdraw_at_start: bool = True,
    precision: float = 1.0,
    max_monthly_search: float | None = None,
) -> tuple[SafeWithdrawalResult, pd.DataFrame]:
    """Calculate the maximum fixed monthly withdrawal that survives all starts.

    The function tests every eligible start month. ``min_horizon_months`` avoids
    cheating with tiny near-end windows when scoring a strategy.
    """

    monthly = compound_returns_to_monthly(
        returns,
        return_column=return_column,
        timestamp_column=timestamp_column,
    )
    monthly = _clean_monthly_returns(monthly)
    min_horizon = max(1, int(min_horizon_months))
    start_indices = [idx for idx in range(len(monthly)) if len(monthly) - idx >= min_horizon]
    target_swr = float(target_monthly_withdrawal) * 12.0 / float(initial_capital)

    if not start_indices:
        result = SafeWithdrawalResult(
            initial_capital=float(initial_capital),
            target_monthly_withdrawal=float(target_monthly_withdrawal),
            target_swr_annual_pct=round(target_swr * 100.0, 6),
            max_safe_monthly_withdrawal=0.0,
            swr_annual_pct=0.0,
            target_monthly_pass=False,
            eligible_start_count=0,
            failed_start_count_at_target=0,
            min_horizon_months=min_horizon,
            worst_start_date=None,
            worst_start_final_capital=float("nan"),
            worst_start_min_capital=float("nan"),
            worst_start_max_drawdown=float("nan"),
        )
        return result, pd.DataFrame()

    target_paths = _simulate_all(
        monthly,
        start_indices,
        initial_capital=initial_capital,
        monthly_withdrawal=target_monthly_withdrawal,
        withdraw_at_start=withdraw_at_start,
    )
    failed_at_target = int((~target_paths["survived"]).sum())
    worst = _worst_path(target_paths)

    high = float(max_monthly_search) if max_monthly_search is not None else float(initial_capital)
    low = 0.0
    if _all_starts_survive(
        monthly,
        start_indices,
        initial_capital=initial_capital,
        monthly_withdrawal=high,
        withdraw_at_start=withdraw_at_start,
    ):
        max_safe = high
    else:
        while high - low > float(precision):
            mid = (low + high) / 2.0
            if _all_starts_survive(
                monthly,
                start_indices,
                initial_capital=initial_capital,
                monthly_withdrawal=mid,
                withdraw_at_start=withdraw_at_start,
            ):
                low = mid
            else:
                high = mid
        max_safe = low

    result = SafeWithdrawalResult(
        initial_capital=float(initial_capital),
        target_monthly_withdrawal=float(target_monthly_withdrawal),
        target_swr_annual_pct=round(target_swr * 100.0, 6),
        max_safe_monthly_withdrawal=round(float(max_safe), 6),
        swr_annual_pct=round((float(max_safe) * 12.0 / float(initial_capital)) * 100.0, 6),
        target_monthly_pass=failed_at_target == 0,
        eligible_start_count=int(len(start_indices)),
        failed_start_count_at_target=failed_at_target,
        min_horizon_months=min_horizon,
        worst_start_date=str(worst.get("start_date")) if worst else None,
        worst_start_final_capital=float(worst.get("final_capital", np.nan)) if worst else float("nan"),
        worst_start_min_capital=float(worst.get("min_capital", np.nan)) if worst else float("nan"),
        worst_start_max_drawdown=float(worst.get("max_drawdown", np.nan)) if worst else float("nan"),
    )
    return result, target_paths


def _as_return_series(
    returns: pd.Series | pd.DataFrame,
    *,
    return_column: str,
    timestamp_column: str,
) -> pd.Series:
    if isinstance(returns, pd.Series):
        series = returns.copy()
        if series.empty:
            return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError("returns Series must use a DatetimeIndex")
    else:
        frame = returns.copy()
        if timestamp_column not in frame.columns:
            raise ValueError(f"missing timestamp column: {timestamp_column}")
        if return_column not in frame.columns:
            raise ValueError(f"missing return column: {return_column}")
        index = pd.to_datetime(frame[timestamp_column], errors="coerce")
        series = pd.Series(pd.to_numeric(frame[return_column], errors="coerce").to_numpy(), index=index)

    series = series.dropna()
    series = series[np.isfinite(series.astype(float))]
    series = series.sort_index()
    return series.astype(float)


def _clean_monthly_returns(monthly_returns: pd.Series) -> pd.Series:
    series = monthly_returns.copy()
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index, errors="coerce")
    series = series.dropna()
    series = series[np.isfinite(series.astype(float))]
    series = series.sort_index()
    return series.astype(float)


def _simulate_all(
    monthly: pd.Series,
    start_indices: list[int],
    *,
    initial_capital: float,
    monthly_withdrawal: float,
    withdraw_at_start: bool,
) -> pd.DataFrame:
    rows = [
        simulate_monthly_withdrawal(
            monthly,
            initial_capital=initial_capital,
            monthly_withdrawal=monthly_withdrawal,
            start_index=idx,
            withdraw_at_start=withdraw_at_start,
        ).to_dict()
        for idx in start_indices
    ]
    return pd.DataFrame(rows)


def _all_starts_survive(
    monthly: pd.Series,
    start_indices: list[int],
    *,
    initial_capital: float,
    monthly_withdrawal: float,
    withdraw_at_start: bool,
) -> bool:
    for idx in start_indices:
        if not simulate_monthly_withdrawal(
            monthly,
            initial_capital=initial_capital,
            monthly_withdrawal=monthly_withdrawal,
            start_index=idx,
            withdraw_at_start=withdraw_at_start,
        ).survived:
            return False
    return True


def _worst_path(paths: pd.DataFrame) -> dict[str, Any]:
    if paths.empty:
        return {}
    failed = paths[~paths["survived"].astype(bool)].copy()
    if not failed.empty:
        failed = failed.sort_values(["months_tested", "min_capital", "final_capital"], ascending=[True, True, True])
        return failed.iloc[0].to_dict()
    survived = paths.sort_values(["final_capital", "min_capital", "max_drawdown"], ascending=[True, True, True])
    return survived.iloc[0].to_dict()


def _max_drawdown(nav: np.ndarray) -> float:
    finite = nav[np.isfinite(nav)]
    if len(finite) == 0:
        return float("nan")
    running_max = np.maximum.accumulate(finite)
    running_max[running_max == 0] = np.nan
    drawdown = (finite - running_max) / running_max
    return float(np.nanmin(drawdown))

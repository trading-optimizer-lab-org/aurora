"""Time-based aggregations: monthly / yearly returns."""
from __future__ import annotations
import pandas as pd

from aurora.analytics.metrics_full._helpers import (
    _has_real_dt,
    _resample_returns,
)


def monthly_returns(returns) -> pd.DataFrame:
    """Year x month matrix of compounded monthly returns.

    Returns an empty DataFrame when no DatetimeIndex is present, since the
    year/month axis labels would otherwise be fabricated.
    """
    if not _has_real_dt(returns):
        return pd.DataFrame()
    monthly = _resample_returns(returns, "ME")
    if len(monthly) == 0:
        return pd.DataFrame()
    df = pd.DataFrame({"year": monthly.index.year, "month": monthly.index.month, "ret": monthly.values})
    return df.pivot(index="year", columns="month", values="ret")


def yearly_returns(returns) -> pd.Series:
    """Compounded yearly returns. Empty Series if no DatetimeIndex."""
    if not _has_real_dt(returns):
        return pd.Series(dtype=float)
    return _resample_returns(returns, "YE")


def best_month(returns) -> tuple:
    if not _has_real_dt(returns):
        return ("", 0.0)
    monthly = _resample_returns(returns, "ME")
    if len(monthly) == 0:
        return ("", 0.0)
    idx = monthly.idxmax()
    return (str(idx.strftime("%Y-%m")), float(monthly.max()))


def worst_month(returns) -> tuple:
    if not _has_real_dt(returns):
        return ("", 0.0)
    monthly = _resample_returns(returns, "ME")
    if len(monthly) == 0:
        return ("", 0.0)
    idx = monthly.idxmin()
    return (str(idx.strftime("%Y-%m")), float(monthly.min()))


def best_year(returns) -> tuple:
    if not _has_real_dt(returns):
        return (0, 0.0)
    yearly = yearly_returns(returns)
    if len(yearly) == 0:
        return (0, 0.0)
    return (int(yearly.idxmax().year), float(yearly.max()))


def worst_year(returns) -> tuple:
    if not _has_real_dt(returns):
        return (0, 0.0)
    yearly = yearly_returns(returns)
    if len(yearly) == 0:
        return (0, 0.0)
    return (int(yearly.idxmin().year), float(yearly.min()))


def positive_months(returns) -> int:
    monthly = _resample_returns(returns, "ME")
    return int((monthly > 0).sum())


def negative_months(returns) -> int:
    monthly = _resample_returns(returns, "ME")
    return int((monthly < 0).sum())

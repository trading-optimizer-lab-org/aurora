from __future__ import annotations

import pandas as pd

from aurora.validation.safe_withdrawal import (
    compound_returns_to_monthly,
    safe_withdrawal_rate,
    simulate_monthly_withdrawal,
)


def test_withdrawal_happens_at_start_of_month() -> None:
    monthly = pd.Series([0.0, 0.0, 0.0], index=pd.date_range("2020-01-31", periods=3, freq="ME"))

    result = simulate_monthly_withdrawal(
        monthly,
        initial_capital=10_000,
        monthly_withdrawal=1_000,
        start_index=0,
    )

    assert result.survived is True
    assert result.final_capital == 7_000


def test_nav_zero_or_below_is_failure() -> None:
    monthly = pd.Series([0.0], index=pd.date_range("2020-01-31", periods=1, freq="ME"))

    result = simulate_monthly_withdrawal(
        monthly,
        initial_capital=1_000,
        monthly_withdrawal=1_000,
    )

    assert result.survived is False
    assert result.failure_date == "2020-01-31"


def test_safe_withdrawal_tests_all_eligible_starts() -> None:
    monthly = pd.Series([0.0] * 6, index=pd.date_range("2020-01-31", periods=6, freq="ME"))

    result, paths = safe_withdrawal_rate(
        monthly,
        initial_capital=100_000,
        target_monthly_withdrawal=1_000,
        min_horizon_months=3,
    )

    assert result.eligible_start_count == 4
    assert len(paths) == 4
    assert result.target_monthly_pass is True


def test_target_1000_on_100k_is_12pct_annual_nominal() -> None:
    monthly = pd.Series([0.0] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME"))

    result, _ = safe_withdrawal_rate(
        monthly,
        initial_capital=100_000,
        target_monthly_withdrawal=1_000,
        min_horizon_months=12,
    )

    assert result.target_swr_annual_pct == 12.0


def test_weekly_returns_are_compounded_to_calendar_months() -> None:
    weekly = pd.Series(
        [0.10, -0.10, 0.05],
        index=pd.to_datetime(["2020-01-03", "2020-01-10", "2020-02-07"]),
    )

    monthly = compound_returns_to_monthly(weekly)

    assert round(float(monthly.iloc[0]), 6) == -0.01
    assert round(float(monthly.iloc[1]), 6) == 0.05


def test_max_safe_monthly_withdrawal_uses_worst_start() -> None:
    monthly = pd.Series([0.0] * 12, index=pd.date_range("2020-01-31", periods=12, freq="ME"))

    result, _ = safe_withdrawal_rate(
        monthly,
        initial_capital=120_000,
        target_monthly_withdrawal=10_000,
        min_horizon_months=12,
        precision=0.01,
    )

    assert result.target_monthly_pass is False
    assert 9_999 < result.max_safe_monthly_withdrawal < 10_000

"""Tests for deployment filters: R94, R95, R96, R119, R120."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import numpy as np
import pytest

from quantforge.deployment.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
)
from quantforge.deployment.news_filter import BlackoutWindow, NewsFilter
from quantforge.deployment.session_times import (
    SessionWindow,
    StrategySessionPolicy,
)
from quantforge.deployment.spread_filter import SpreadFilter, SpreadFilterConfig
from quantforge.deployment.vol_filter import VolFilter, VolFilterConfig


# --------------------------------------------------------------------------
# R120 circuit breaker
# --------------------------------------------------------------------------


def test_circuit_breaker_ok_then_warn_then_trip():
    cb = CircuitBreaker(CircuitBreakerConfig(starting_nav=100_000.0,
                                              daily_max_dd_fraction=0.02,
                                              warn_at_fraction=0.80))
    now = datetime(2026, 5, 8, 10, 0, 0)
    cb.record_pnl(-500, when=now)
    assert cb.state is CircuitBreakerState.OK
    cb.record_pnl(-1300, when=now + timedelta(hours=1))
    assert cb.state is CircuitBreakerState.WARN
    cb.record_pnl(-500, when=now + timedelta(hours=2))
    assert cb.state is CircuitBreakerState.TRIPPED
    assert cb.is_tripped is True


def test_circuit_breaker_reset_clears_state():
    cb = CircuitBreaker(CircuitBreakerConfig(starting_nav=100_000.0))
    cb.record_pnl(-2_500)
    assert cb.is_tripped
    cb.reset()
    assert cb.state is CircuitBreakerState.OK


# --------------------------------------------------------------------------
# R119 spread filter
# --------------------------------------------------------------------------


def test_spread_filter_warmup_period_does_not_block():
    sf = SpreadFilter(SpreadFilterConfig(min_observations=10))
    for _ in range(5):
        sf.observe("SPY", 100.0, 100.10)
    # During warmup, the filter must not block.
    assert sf.is_blocked("SPY", current_spread=10.0) is False


def test_spread_filter_blocks_outlier_after_warmup():
    sf = SpreadFilter(
        SpreadFilterConfig(max_multiple_over_avg=2.0, min_observations=10)
    )
    # Tight historical spread.
    for _ in range(20):
        sf.observe("SPY", 100.0, 100.01)
    avg = sf.average("SPY")
    assert avg is not None
    # Outlier 10x above average -> blocked.
    assert sf.is_blocked("SPY", current_spread=avg * 10) is True
    # In-band spread -> not blocked.
    assert sf.is_blocked("SPY", current_spread=avg * 1.5) is False


# --------------------------------------------------------------------------
# R94 news filter
# --------------------------------------------------------------------------


def test_news_filter_active_window_blocks():
    nf = NewsFilter()
    nf.add(BlackoutWindow(
        start_utc=datetime(2026, 5, 8, 12, 0),
        end_utc=datetime(2026, 5, 8, 14, 0),
        label="Fed",
    ))
    assert nf.is_blocked(datetime(2026, 5, 8, 13, 0)) is True
    assert nf.is_blocked(datetime(2026, 5, 8, 11, 0)) is False


def test_news_filter_upcoming_lists_only_within_horizon():
    nf = NewsFilter()
    nf.add(BlackoutWindow(
        start_utc=datetime(2026, 5, 8, 14, 0),
        end_utc=datetime(2026, 5, 8, 14, 30),
        label="CPI",
    ))
    upcoming = nf.upcoming(when=datetime(2026, 5, 8, 12, 0),
                           within=timedelta(hours=4))
    assert len(upcoming) == 1
    upcoming_far = nf.upcoming(when=datetime(2026, 5, 8, 12, 0),
                               within=timedelta(minutes=30))
    assert upcoming_far == []


def test_blackout_window_validates_order():
    with pytest.raises(ValueError):
        BlackoutWindow(
            start_utc=datetime(2026, 5, 8, 14, 0),
            end_utc=datetime(2026, 5, 8, 13, 0),
            label="bad",
        )


# --------------------------------------------------------------------------
# R95 vol filter
# --------------------------------------------------------------------------


def test_vol_filter_max_gate():
    vf = VolFilter(VolFilterConfig(max_realised_vol_annual=0.20))
    high_vol_rets = np.random.default_rng(0).normal(0, 0.05, 100)
    blocked, reason = vf.is_blocked(high_vol_rets)
    assert blocked is True
    assert "realised_vol" in reason


def test_vol_filter_external_metric():
    vf = VolFilter(VolFilterConfig(
        external_metric=lambda: ("VIX", 50.0),
        external_max=30.0,
    ))
    blocked, reason = vf.is_blocked(np.zeros(50))
    assert blocked is True
    assert "VIX" in reason


def test_vol_filter_passes_when_in_band():
    vf = VolFilter(VolFilterConfig(
        max_realised_vol_annual=0.50,
        min_realised_vol_annual=0.01,
    ))
    rets = np.random.default_rng(0).normal(0, 0.01, 100)
    blocked, reason = vf.is_blocked(rets)
    assert blocked is False


# --------------------------------------------------------------------------
# R96 session times
# --------------------------------------------------------------------------


def test_session_window_within_hours():
    win = SessionWindow(start=time(9, 30), end=time(16, 0), exchange="NYSE")
    # 14:00 UTC = 10:00 NY (during EDT). Inside window.
    assert win.contains(datetime(2026, 5, 8, 14, 0)) is True
    # 03:00 UTC = 23:00 prev-day NY. Outside.
    assert win.contains(datetime(2026, 5, 8, 3, 0)) is False


def test_session_window_weekend_excluded():
    win = SessionWindow(start=time(9, 30), end=time(16, 0), exchange="NYSE")
    # Saturday 2026-05-09 14:00 UTC.
    assert win.contains(datetime(2026, 5, 9, 14, 0)) is False


def test_strategy_policy_empty_windows_means_always_open():
    pol = StrategySessionPolicy(strategy_id="alpha")
    assert pol.is_open(datetime(2026, 5, 8, 3, 0)) is True


def test_strategy_policy_with_windows():
    pol = StrategySessionPolicy(
        strategy_id="alpha",
        windows=[
            SessionWindow(start=time(9, 30), end=time(16, 0),
                          exchange="NYSE"),
        ],
    )
    assert pol.is_open(datetime(2026, 5, 8, 14, 0)) is True
    assert pol.is_open(datetime(2026, 5, 8, 3, 0)) is False

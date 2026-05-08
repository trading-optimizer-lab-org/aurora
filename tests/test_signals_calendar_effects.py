"""Tests for CalendarEffectsSignal."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.signals import CalendarEffectsSignal, CalendarEffectsConfig


def test_default_signals_shape():
    idx = pd.bdate_range("2024-01-01", "2024-03-31")
    sig = CalendarEffectsSignal()
    out = sig.signals(idx)
    assert isinstance(out, pd.Series)
    assert len(out) == len(idx)
    assert set(np.unique(out.values)).issubset({-1, 0, 1})


def test_monday_blues_negative_or_offset():
    # Pick a Monday past the turn-of-month window (TOM = first 4 BDays + last BDay)
    idx = pd.DatetimeIndex([pd.Timestamp("2024-03-18")])  # Monday, mid-month
    sig = CalendarEffectsSignal()
    out = sig.signals(idx)
    # Default rule sums monday(-1) + friday(0) + tom(0) -> -1
    assert out.iloc[0] == -1


def test_friday_lift_positive():
    idx = pd.DatetimeIndex([pd.Timestamp("2024-03-08")])  # Friday mid-month
    sig = CalendarEffectsSignal()
    out = sig.signals(idx)
    assert out.iloc[0] == 1


def test_custom_rules():
    sig = CalendarEffectsSignal(CalendarEffectsConfig(
        rules=[lambda ts: 1 if ts.weekday() == 2 else 0]
    ))
    # Wednesday
    idx = pd.DatetimeIndex([pd.Timestamp("2024-03-06")])
    assert sig.signals(idx).iloc[0] == 1


def test_empty_rules_raises():
    with pytest.raises(ValueError):
        CalendarEffectsSignal(CalendarEffectsConfig(rules=[]))


def test_bad_dates_input():
    sig = CalendarEffectsSignal()
    with pytest.raises(TypeError):
        sig.signals(12345)


def test_signal_clipping():
    # 3 rules each emit +1: must clip to +1
    sig = CalendarEffectsSignal(CalendarEffectsConfig(
        rules=[lambda ts: 1, lambda ts: 1, lambda ts: 1]
    ))
    idx = pd.bdate_range("2024-03-01", periods=5)
    out = sig.signals(idx)
    assert (out == 1).all()

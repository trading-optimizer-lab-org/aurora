"""Tests for EventDrivenSignal."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.signals import EventDrivenSignal, EventDrivenConfig


@pytest.fixture
def panel_with_events():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    prices = pd.DataFrame({
        "AAA": 100.0 + np.arange(60),
        "BBB": 100.0 + np.arange(60) * 0.5,
    }, index=idx)
    events = pd.DataFrame([
        {"date": idx[20], "ticker": "AAA", "event_type": "earnings"},
        {"date": idx[40], "ticker": "BBB", "event_type": "ma"},
    ])
    return prices, events


def test_signals_shape(panel_with_events):
    prices, events = panel_with_events
    sig = EventDrivenSignal()
    out = sig.signals(prices, events)
    assert out.shape == prices.shape


def test_pre_event_long(panel_with_events):
    prices, events = panel_with_events
    sig = EventDrivenSignal(EventDrivenConfig(pre_window=3, post_window=2))
    out = sig.signals(prices, events)
    # Bars 17,18,19 for AAA should be +1
    assert (out["AAA"].iloc[17:20] == 1).all()


def test_post_event_short(panel_with_events):
    prices, events = panel_with_events
    sig = EventDrivenSignal(EventDrivenConfig(pre_window=3, post_window=2))
    out = sig.signals(prices, events)
    # Bars 21,22 for AAA should be -1
    assert (out["AAA"].iloc[21:23] == -1).all()


def test_event_at_event_day_is_zero(panel_with_events):
    prices, events = panel_with_events
    sig = EventDrivenSignal(EventDrivenConfig(pre_window=3, post_window=2))
    out = sig.signals(prices, events)
    assert out["AAA"].iloc[20] == 0


def test_unrecognized_event_type_skipped(panel_with_events):
    prices, _ = panel_with_events
    idx = prices.index
    events = pd.DataFrame([
        {"date": idx[10], "ticker": "AAA", "event_type": "something_random"},
    ])
    sig = EventDrivenSignal()
    out = sig.signals(prices, events)
    assert (out == 0).all().all()


def test_unknown_ticker_ignored(panel_with_events):
    prices, _ = panel_with_events
    idx = prices.index
    events = pd.DataFrame([
        {"date": idx[10], "ticker": "ZZZ", "event_type": "earnings"},
    ])
    sig = EventDrivenSignal()
    out = sig.signals(prices, events)
    assert (out == 0).all().all()


def test_missing_event_cols_raises(panel_with_events):
    prices, _ = panel_with_events
    bad = pd.DataFrame({"foo": [1]})
    sig = EventDrivenSignal()
    with pytest.raises(ValueError):
        sig.signals(prices, bad)

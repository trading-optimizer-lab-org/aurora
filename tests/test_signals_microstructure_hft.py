"""Tests for MicrostructureSignal."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.signals import MicrostructureSignal, MicrostructureConfig


def test_mock_book_shape():
    book = MicrostructureSignal.mock_l2_book(n=200)
    assert isinstance(book, pd.DataFrame)
    assert {"bid_qty", "ask_qty"}.issubset(book.columns)
    assert len(book) == 200


def test_signals_basic():
    book = MicrostructureSignal.mock_l2_book(n=500)
    sig = MicrostructureSignal()
    out = sig.signals(book)
    assert isinstance(out, pd.Series)
    assert set(np.unique(out.values)).issubset({-1, 0, 1})


def test_strong_buying_pressure():
    idx = pd.date_range("2024-01-01", periods=10, freq="s")
    book = pd.DataFrame({"bid_qty": [100] * 10, "ask_qty": [10] * 10}, index=idx)
    sig = MicrostructureSignal(MicrostructureConfig(threshold=0.2, smoothing=1))
    out = sig.signals(book)
    assert (out == 1).all()


def test_strong_selling_pressure():
    idx = pd.date_range("2024-01-01", periods=10, freq="s")
    book = pd.DataFrame({"bid_qty": [10] * 10, "ask_qty": [100] * 10}, index=idx)
    sig = MicrostructureSignal(MicrostructureConfig(threshold=0.2, smoothing=1))
    out = sig.signals(book)
    assert (out == -1).all()


def test_balanced_book_zero():
    idx = pd.date_range("2024-01-01", periods=10, freq="s")
    book = pd.DataFrame({"bid_qty": [50] * 10, "ask_qty": [50] * 10}, index=idx)
    sig = MicrostructureSignal(MicrostructureConfig(threshold=0.2, smoothing=1))
    out = sig.signals(book)
    assert (out == 0).all()


def test_alias_columns_recognized():
    idx = pd.date_range("2024-01-01", periods=10, freq="s")
    book = pd.DataFrame({"bid_size": [50] * 10, "ask_size": [50] * 10}, index=idx)
    sig = MicrostructureSignal()
    out = sig.signals(book)
    assert len(out) == 10


def test_invalid_inputs():
    sig = MicrostructureSignal()
    with pytest.raises(TypeError):
        sig.signals(np.zeros((10, 2)))
    bad = pd.DataFrame({"foo": [1, 2, 3]})
    with pytest.raises(ValueError):
        sig.signals(bad)


def test_invalid_config():
    with pytest.raises(ValueError):
        MicrostructureSignal(MicrostructureConfig(threshold=0))
    with pytest.raises(ValueError):
        MicrostructureSignal(MicrostructureConfig(smoothing=0))

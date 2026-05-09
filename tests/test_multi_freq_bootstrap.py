"""Tests for MultiFrequencyBootstrap."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.core.seed import set_global_seed
from aurora.validation.multi_freq_bootstrap import MultiFrequencyBootstrap


@pytest.fixture
def fake_returns():
    set_global_seed(42)
    rng = np.random.default_rng(0)
    return rng.normal(0.0005, 0.01, 500)


def test_basic(fake_returns):
    set_global_seed(42)
    mfb = MultiFrequencyBootstrap(block_sizes=(5, 20), n_paths=20)
    out = mfb.run(fake_returns)
    assert out is mfb
    assert 5 in mfb.results
    assert 20 in mfb.results
    assert mfb.results[5]["calmars"].shape == (20,)
    assert mfb.results[20]["sharpes"].shape == (20,)


def test_percentile_method(fake_returns):
    set_global_seed(42)
    mfb = MultiFrequencyBootstrap(block_sizes=(10,), n_paths=30).run(fake_returns)
    p50 = mfb.percentile(10, "calmars", 50)
    assert isinstance(p50, float)
    with pytest.raises(KeyError):
        mfb.percentile(99, "calmars", 50)
    with pytest.raises(ValueError):
        mfb.percentile(10, "bad", 50)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        MultiFrequencyBootstrap(block_sizes=()).run(np.zeros(100))
    with pytest.raises(ValueError):
        MultiFrequencyBootstrap(block_sizes=(0,)).run(np.zeros(100))
    with pytest.raises(ValueError):
        MultiFrequencyBootstrap().run(np.zeros(5))

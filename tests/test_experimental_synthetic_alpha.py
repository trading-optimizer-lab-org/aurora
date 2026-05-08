"""Tests for SyntheticAlphaGenerator."""
from __future__ import annotations

import numpy as np
import pytest

from quantforge.experimental.synthetic_alpha import SyntheticAlphaGenerator


def test_generate_without_common():
    g = SyntheticAlphaGenerator(seed=0, n_periods=100)
    res = g.generate()
    assert res["factor"].shape == (100,)
    assert res["max_corr_with_common"] == 0.0


def test_orthogonal_to_common_factors():
    g = SyntheticAlphaGenerator(seed=1, n_periods=200)
    common = np.random.default_rng(7).standard_normal((200, 2))
    res = g.generate(common)
    # After residualization, corr with each common factor should be near zero.
    assert res["max_corr_with_common"] < 1e-8


def test_factor_is_standardized():
    g = SyntheticAlphaGenerator(seed=3, n_periods=300)
    res = g.generate()
    f = res["factor"]
    assert abs(float(f.mean())) < 1e-9
    assert abs(float(f.std(ddof=1)) - 1.0) < 1e-9


def test_invalid_periods_raise():
    with pytest.raises(ValueError):
        SyntheticAlphaGenerator(n_periods=0)


def test_mismatched_common_raises():
    g = SyntheticAlphaGenerator(seed=0, n_periods=50)
    bad = np.zeros((49, 1))
    with pytest.raises(ValueError):
        g.generate(bad)


def test_seed_reproducibility():
    a = SyntheticAlphaGenerator(seed=99, n_periods=64).generate()
    b = SyntheticAlphaGenerator(seed=99, n_periods=64).generate()
    np.testing.assert_allclose(a["factor"], b["factor"])

"""Tests for quantforge.execution.market_impact."""
from __future__ import annotations

import numpy as np
import pytest

from aurora.execution.market_impact import (
    MarketImpactConfig,
    MarketImpactModel,
)


def test_mi_config_defaults():
    cfg = MarketImpactConfig()
    assert cfg.a >= 0
    assert cfg.b >= 0
    assert cfg.sigma_default > 0


def test_mi_config_invalid_negatives():
    with pytest.raises(ValueError):
        MarketImpactConfig(a=-1)
    with pytest.raises(ValueError):
        MarketImpactConfig(b=-0.5)
    with pytest.raises(ValueError):
        MarketImpactConfig(sigma_default=0)
    with pytest.raises(ValueError):
        MarketImpactConfig(adv_default=0)


def test_mi_predict_zero_qty_returns_intercept():
    m = MarketImpactModel(MarketImpactConfig(a=0.5, b=0.5, c=0.1))
    out = m.predict(qty=0, adv=1e6, sigma=0.02)
    assert out == pytest.approx(0.1)


def test_mi_predict_monotone_in_qty():
    m = MarketImpactModel(MarketImpactConfig(a=1.0, b=1.0, c=0.0))
    p1 = m.predict(qty=10, adv=1e6, sigma=0.02)
    p2 = m.predict(qty=10_000, adv=1e6, sigma=0.02)
    assert p2 > p1


def test_mi_predict_invalid_qty():
    m = MarketImpactModel()
    with pytest.raises(ValueError):
        m.predict(-1)


def test_mi_predict_invalid_adv_sigma():
    m = MarketImpactModel()
    with pytest.raises(ValueError):
        m.predict(100, adv=0, sigma=0.02)
    with pytest.raises(ValueError):
        m.predict(100, adv=1e6, sigma=0)


def test_mi_calibrate_no_intercept():
    rng = np.random.default_rng(1)
    adv = 1e6
    sigma = 0.02
    sizes = rng.uniform(1e3, 1e5, 50)
    a_true, b_true = 0.3, 0.7
    ratio = sizes / adv
    costs_clean = a_true * ratio + b_true * np.sqrt(ratio) * sigma
    costs = costs_clean + rng.normal(0, 1e-6, 50)
    m = MarketImpactModel()
    res = m.calibrate(sizes, costs)
    assert abs(m.a - a_true) < 0.05
    assert abs(m.b - b_true) < 0.05
    assert res.n_obs == 50
    assert res.rmse >= 0


def test_mi_calibrate_with_intercept():
    rng = np.random.default_rng(2)
    sizes = rng.uniform(1e3, 1e5, 30)
    costs = 0.1 + 0.5 * (sizes / 1e6) + 0.4 * np.sqrt(sizes / 1e6) * 0.02
    m = MarketImpactModel(MarketImpactConfig(fit_intercept=True))
    res = m.calibrate(sizes, costs)
    assert res.c == pytest.approx(0.1, abs=0.05)


def test_mi_calibrate_shape_mismatch():
    m = MarketImpactModel()
    with pytest.raises(ValueError):
        m.calibrate([1, 2, 3], [1.0, 2.0])


def test_mi_calibrate_too_few_obs():
    m = MarketImpactModel()
    with pytest.raises(ValueError):
        m.calibrate([1.0], [0.1])


def test_mi_calibrate_negative_size_rejected():
    m = MarketImpactModel()
    with pytest.raises(ValueError):
        m.calibrate([1, -1], [0.1, 0.2])


def test_mi_calibrate_invalid_adv_sigma():
    m = MarketImpactModel()
    with pytest.raises(ValueError):
        m.calibrate([1, 2], [0.1, 0.2], adv=[0, 1])

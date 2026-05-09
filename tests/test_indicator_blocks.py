"""Tests for strategies.blocks.indicators (R86)."""
from __future__ import annotations

import numpy as np

from aurora.strategies.blocks import (
    STANDARD_REGISTRY,
    IndicatorBlock,
    IndicatorRegistry,
    ParameterRange,
)
from aurora.strategies.blocks.indicators import require_anti_lookahead


def _gbm_prices(n: int = 600, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.01, n)
    return 100.0 * np.cumprod(1.0 + rets)


def test_standard_registry_has_seventeen_blocks():
    # Sanity floor: the canonical set ships at least the documented
    # indicator family.
    assert len(STANDARD_REGISTRY) >= 17


def test_every_block_is_callable_and_returns_aligned_length():
    prices = _gbm_prices()
    for name in STANDARD_REGISTRY.names():
        block = STANDARD_REGISTRY.get(name)
        params = {n: r.low for n, r in block.params.items()}
        result = block.compute(prices, **params)
        assert len(result) == len(prices), (
            f"{name} length mismatch: {len(result)} vs {len(prices)}"
        )


def test_sample_params_obeys_ranges():
    rng = np.random.default_rng(42)
    for name in STANDARD_REGISTRY.names():
        block = STANDARD_REGISTRY.get(name)
        sampled = block.sample_params(rng)
        for pname, pval in sampled.items():
            pr = block.params[pname]
            assert pr.low <= pval <= pr.high


def test_warmup_returns_int():
    rng = np.random.default_rng(1)
    for name in STANDARD_REGISTRY.names():
        block = STANDARD_REGISTRY.get(name)
        params = block.sample_params(rng)
        w = block.warmup(params)
        assert isinstance(w, int)
        assert w >= 0


def test_anti_lookahead_for_simple_indicators():
    prices = _gbm_prices()
    # Spot-check several deterministic indicators.
    for name in ("SMA", "EMA", "RSI", "DonchianUpper", "DonchianLower"):
        block = STANDARD_REGISTRY.get(name)
        params = {n: r.low for n, r in block.params.items()}
        assert require_anti_lookahead(block, prices, params)


def test_registry_register_and_lookup():
    reg = IndicatorRegistry()
    block = IndicatorBlock(
        name="DemoMul",
        compute=lambda p, k=2: np.asarray(p) * k,
        params={"k": ParameterRange("k", 1, 5, is_integer=True)},
    )
    reg.register(block)
    assert "DemoMul" in reg
    assert reg.get("DemoMul") is block

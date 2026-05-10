"""Minimal local Strategy extension for AURORA (R186 example).

Used by ``tests/test_extension_loader.py``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.strategies.base import Strategy, StrategySpec


class ExampleStrategy(Strategy):
    """Constant long-only weight strategy. For extension-loader tests."""

    interface_version: str = "1.0.0"
    weight: float = 0.5

    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.full(len(prices), float(self.weight))

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="ExampleStrategy",
            params={"weight": 0.5},
            param_ranges={"weight": (0.0, 1.0)},
        )


__aurora_extension__ = {
    "name": "example_ext_strategy",
    "kind": "Strategy",
    "interface_version": "1.0.0",
    "factory": lambda: ExampleStrategy,
    "capabilities": {},
}

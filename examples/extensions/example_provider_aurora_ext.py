"""Minimal local DataProvider extension for AURORA (R186 example).

Run only when the parent dir is in ``$AU_EXTENSION_DIRS``.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from aurora.core.data_providers import BaseDataProvider


class ExampleProvider(BaseDataProvider):
    """Tiny synthetic provider used by the extension loader tests."""

    name: str = "example_ext_provider"
    version: str = "example:0.1"
    point_in_time: bool = True
    tier_permission: str = "IS_TRAIN"
    interface_version: str = "1.0.0"

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.Series:
        idx = pd.date_range("2020-01-01", periods=10, freq="B")
        rng = np.random.default_rng(42)
        return pd.Series(
            100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(idx)))),
            index=idx, name=symbol,
        )


__aurora_extension__ = {
    "name": "example_ext_provider",
    "kind": "DataProvider",
    "interface_version": "1.0.0",
    "factory": ExampleProvider,
    "capabilities": {"point_in_time": True},
}

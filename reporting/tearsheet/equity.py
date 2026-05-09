"""Equity curve plot (cumulative NAV with optional benchmark overlay)."""
from __future__ import annotations

from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .header import _fig_to_base64


def _plot_equity(nav: np.ndarray, idx: pd.DatetimeIndex,
                 benchmark_nav: Optional[np.ndarray] = None,
                 bench_idx: Optional[pd.DatetimeIndex] = None) -> str:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(idx, nav, label="Strategy", color="#1f77b4", linewidth=1.4)
    if benchmark_nav is not None and bench_idx is not None:
        ax.plot(bench_idx, benchmark_nav, label="Benchmark",
                color="#999999", linewidth=1.0, linestyle="--")
    ax.set_title("Equity Curve")
    ax.set_ylabel("NAV (start = 1.0)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left")
    return _fig_to_base64(fig)

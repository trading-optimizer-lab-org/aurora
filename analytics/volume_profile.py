"""Volume profile analysis (R101).

Compute volume-by-price profile (Point of Control, value area,
high/low volume nodes). Useful as a support / resistance signal and
for post-trade analysis.

Pairs with R86 indicator block library so a strategy can use a
``volume_profile_poc`` node as one of its building blocks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass(frozen=True)
class VolumeProfile:
    """Volume-by-price profile."""

    bin_edges: np.ndarray
    bin_volumes: np.ndarray
    poc_price: float
    value_area_low: float
    value_area_high: float
    high_volume_nodes: List[float]
    low_volume_nodes: List[float]


def compute_volume_profile(
    prices: np.ndarray,
    volumes: np.ndarray,
    *,
    n_bins: int = 30,
    value_area_pct: float = 0.70,
    high_volume_node_z: float = 1.0,
) -> VolumeProfile:
    """Build a volume profile over the supplied price / volume series.

    Args:
        prices: per-bar price (typical price = (h+l+c)/3 is a good
            choice; the caller decides).
        volumes: per-bar traded volume.
        n_bins: number of price bins.
        value_area_pct: fraction of total volume that defines the
            value area around the POC. Default 0.70 (70%).
        high_volume_node_z: bins whose volume z-score >= this are HVN;
            <= -this are LVN.

    Returns:
        :class:`VolumeProfile`.
    """
    prices = np.asarray(prices, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    if len(prices) != len(volumes):
        raise ValueError("prices and volumes must have the same length")
    if len(prices) < n_bins:
        raise ValueError(
            f"need at least {n_bins} bars for {n_bins} bins; got {len(prices)}"
        )

    bin_edges = np.linspace(prices.min(), prices.max(), n_bins + 1)
    bin_idx = np.clip(
        np.digitize(prices, bin_edges) - 1, 0, n_bins - 1,
    )
    bin_volumes: np.ndarray = np.zeros(n_bins, dtype=float)
    np.add.at(bin_volumes, bin_idx, volumes)

    poc_bin = int(np.argmax(bin_volumes))
    poc_price = float((bin_edges[poc_bin] + bin_edges[poc_bin + 1]) / 2)

    total = bin_volumes.sum()
    if total <= 0:
        va_low = va_high = poc_price
    else:
        target = total * value_area_pct
        included = {poc_bin}
        running = bin_volumes[poc_bin]
        lo = hi = poc_bin
        while running < target and (lo > 0 or hi < n_bins - 1):
            below = bin_volumes[lo - 1] if lo > 0 else -1.0
            above = bin_volumes[hi + 1] if hi < n_bins - 1 else -1.0
            if above >= below and hi < n_bins - 1:
                hi += 1
                included.add(hi)
                running += bin_volumes[hi]
            elif lo > 0:
                lo -= 1
                included.add(lo)
                running += bin_volumes[lo]
            else:
                break
        va_low = float(bin_edges[lo])
        va_high = float(bin_edges[hi + 1])

    mean = bin_volumes.mean()
    std = bin_volumes.std() or 1.0
    z = (bin_volumes - mean) / std
    hvn = [
        float((bin_edges[i] + bin_edges[i + 1]) / 2)
        for i, zi in enumerate(z) if zi >= high_volume_node_z
    ]
    lvn = [
        float((bin_edges[i] + bin_edges[i + 1]) / 2)
        for i, zi in enumerate(z) if zi <= -high_volume_node_z
    ]

    return VolumeProfile(
        bin_edges=bin_edges,
        bin_volumes=bin_volumes,
        poc_price=poc_price,
        value_area_low=va_low,
        value_area_high=va_high,
        high_volume_nodes=hvn,
        low_volume_nodes=lvn,
    )


__all__ = [
    "VolumeProfile",
    "compute_volume_profile",
]

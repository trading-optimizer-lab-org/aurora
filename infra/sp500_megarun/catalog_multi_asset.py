"""Calendar-safe independent multi-asset panel used by the catalog engine."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AssetPanelV1:
    asset_ids: tuple[str, ...]
    sessions: tuple[Hashable, ...]
    values: np.ndarray
    valid_mask: np.ndarray
    validation_opened: bool = False
    locked_opened: bool = False


def build_asset_panel(
    assets: Mapping[str, Mapping[Hashable, float]],
) -> AssetPanelV1:
    if not assets:
        raise ValueError("MULTI_ASSET_EMPTY")
    asset_ids = tuple(sorted(str(asset_id) for asset_id in assets))
    if len(asset_ids) != len(assets):
        raise ValueError("MULTI_ASSET_ID_COLLISION")
    sessions = tuple(sorted({session for values in assets.values() for session in values}))
    if not sessions:
        raise ValueError("MULTI_ASSET_SESSIONS_EMPTY")
    session_index = {session: index for index, session in enumerate(sessions)}
    values = np.full((len(asset_ids), len(sessions)), np.nan, dtype=np.float64)
    for row_index, asset_id in enumerate(asset_ids):
        for session, value in assets[asset_id].items():
            values[row_index, session_index[session]] = float(value)
    return AssetPanelV1(
        asset_ids=asset_ids,
        sessions=sessions,
        values=values,
        valid_mask=np.isfinite(values),
    )


__all__ = ["AssetPanelV1", "build_asset_panel"]

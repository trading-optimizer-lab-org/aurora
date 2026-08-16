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


@dataclass(frozen=True)
class MultiAssetEvaluationV1:
    independent_signals: np.ndarray
    cross_asset_signals: np.ndarray
    asset_count: int
    session_count: int
    valid_observation_count: int
    shared_calendar_builds: int
    asset_specific_work_units: int
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


def evaluate_multi_asset_panel(
    panel: AssetPanelV1,
    *,
    lookback: int,
) -> MultiAssetEvaluationV1:
    """Build causal independent and cross-asset signals on one shared calendar."""

    values = np.asarray(panel.values, dtype=np.float64)
    valid = np.asarray(panel.valid_mask, dtype=bool)
    expected_shape = (len(panel.asset_ids), len(panel.sessions))
    if (
        lookback < 1
        or values.shape != expected_shape
        or valid.shape != expected_shape
        or not np.array_equal(valid, np.isfinite(values))
        or panel.validation_opened
        or panel.locked_opened
    ):
        raise ValueError("MULTI_ASSET_PANEL_INVALID")

    independent = np.zeros(expected_shape, dtype=np.int8)
    for asset_index in range(values.shape[0]):
        observed: list[float] = []
        for session_index in range(values.shape[1]):
            if not valid[asset_index, session_index]:
                continue
            current = float(values[asset_index, session_index])
            if len(observed) >= lookback:
                reference = float(np.mean(observed[-lookback:]))
                independent[asset_index, session_index] = (
                    1 if current > reference else -1 if current < reference else 0
                )
            observed.append(current)

    cross_asset = np.zeros(expected_shape, dtype=np.int8)
    for session_index in range(values.shape[1]):
        active = valid[:, session_index]
        if not bool(active.any()):
            continue
        current = values[active, session_index]
        reference = float(np.mean(current))
        cross_asset[active, session_index] = np.where(
            current > reference,
            1,
            np.where(current < reference, -1, 0),
        ).astype(np.int8)

    return MultiAssetEvaluationV1(
        independent_signals=independent,
        cross_asset_signals=cross_asset,
        asset_count=values.shape[0],
        session_count=values.shape[1],
        valid_observation_count=int(valid.sum()),
        shared_calendar_builds=1,
        asset_specific_work_units=values.shape[0],
    )


__all__ = [
    "AssetPanelV1",
    "MultiAssetEvaluationV1",
    "build_asset_panel",
    "evaluate_multi_asset_panel",
]

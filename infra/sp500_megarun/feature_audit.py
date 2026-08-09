"""Coverage, causality and duplicate audit for SP500 feature outputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping, Sequence

import pandas as pd


class FeatureAuditError(ValueError):
    """Raised when a feature output crosses a frozen scientific boundary."""


@dataclass(frozen=True)
class LaneCoverage:
    lane_id: str
    row_count: int
    first_date: str | None
    last_date: str | None
    yearly_non_null_fraction: Mapping[int, float]


@dataclass(frozen=True)
class FeatureAuditReport:
    ready: bool
    empty_lanes: tuple[str, ...]
    exact_duplicate_groups: tuple[tuple[str, ...], ...]
    near_duplicate_pairs: tuple[tuple[str, str], ...]
    coverage: tuple[LaneCoverage, ...]


def _normalized_output(frame: pd.DataFrame, *, lane_id: str) -> pd.DataFrame:
    required = {"date", "available_at", "value"}
    missing = sorted(required - set(frame.columns))
    if missing and not frame.empty:
        raise FeatureAuditError(f"MISSING_FEATURE_COLUMNS:{lane_id}:{','.join(missing)}")
    if frame.empty:
        return pd.DataFrame(
            {
                "date": pd.Series(dtype="datetime64[ns]"),
                "available_at": pd.Series(dtype="datetime64[ns]"),
                "value": pd.Series(dtype=float),
            }
        )
    normalized = frame.loc[:, ["date", "available_at", "value"]].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    normalized["available_at"] = pd.to_datetime(
        normalized["available_at"], errors="coerce"
    ).dt.normalize()
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    if normalized[["date", "available_at"]].isna().any().any():
        raise FeatureAuditError(f"INVALID_FEATURE_TIMESTAMPS:{lane_id}")
    if normalized["available_at"].gt(normalized["date"]).any():
        raise FeatureAuditError(f"FEATURE_LOOKAHEAD:{lane_id}")
    if normalized["date"].duplicated().any():
        raise FeatureAuditError(f"DUPLICATE_FEATURE_DATE:{lane_id}")
    return normalized.sort_values("date", kind="mergesort").reset_index(drop=True)


def _value_hash(frame: pd.DataFrame) -> str:
    canonical = frame.loc[frame["value"].notna(), ["date", "value"]].copy()
    canonical["value"] = canonical["value"].round(12)
    payload = canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _yearly_fraction(
    frame: pd.DataFrame,
    *,
    search_start: pd.Timestamp,
    search_end: pd.Timestamp,
) -> Mapping[int, float]:
    scored = frame.loc[frame["date"].between(search_start, search_end)].copy()
    result: dict[int, float] = {}
    for year in range(search_start.year, search_end.year + 1):
        rows = scored.loc[scored["date"].dt.year == year, "value"]
        result[year] = float(rows.notna().mean()) if len(rows) else 0.0
    return result


def audit_feature_outputs(
    outputs: Mapping[str, pd.DataFrame],
    *,
    expected_lane_ids: Sequence[str],
    search_start: pd.Timestamp,
    search_end: pd.Timestamp,
    near_duplicate_threshold: float = 0.995,
) -> FeatureAuditReport:
    """Audit bounded feature frames without consulting validation or locked data."""

    expected = tuple(expected_lane_ids)
    extras = sorted(set(outputs) - set(expected))
    if extras:
        raise FeatureAuditError(f"UNEXPECTED_FEATURE_LANES:{','.join(extras)}")
    normalized: dict[str, pd.DataFrame] = {}
    coverage: list[LaneCoverage] = []
    empty: list[str] = []
    for lane_id in expected:
        frame = _normalized_output(outputs.get(lane_id, pd.DataFrame()), lane_id=lane_id)
        if not frame.empty and frame["date"].gt(search_end).any():
            raise FeatureAuditError(f"NON_TRAIN_FEATURE_ROW:{lane_id}")
        normalized[lane_id] = frame
        valid = frame.loc[frame.get("value", pd.Series(dtype=float)).notna()]
        if valid.empty:
            empty.append(lane_id)
        coverage.append(
            LaneCoverage(
                lane_id=lane_id,
                row_count=len(valid),
                first_date=(valid["date"].min().date().isoformat() if not valid.empty else None),
                last_date=(valid["date"].max().date().isoformat() if not valid.empty else None),
                yearly_non_null_fraction=_yearly_fraction(
                    frame,
                    search_start=pd.Timestamp(search_start),
                    search_end=pd.Timestamp(search_end),
                ),
            )
        )

    hash_groups: dict[str, list[str]] = {}
    for lane_id, frame in normalized.items():
        if frame.empty or frame["value"].notna().sum() == 0:
            continue
        hash_groups.setdefault(_value_hash(frame), []).append(lane_id)
    exact_groups = tuple(
        tuple(group)
        for group in sorted(hash_groups.values(), key=lambda values: tuple(values))
        if len(group) > 1
    )
    exact_pairs = {
        frozenset((left, right))
        for group in exact_groups
        for position, left in enumerate(group)
        for right in group[position + 1 :]
    }

    near_pairs: list[tuple[str, str]] = []
    populated = [lane_id for lane_id in expected if lane_id not in empty]
    for position, left in enumerate(populated):
        for right in populated[position + 1 :]:
            if frozenset((left, right)) in exact_pairs:
                continue
            joined = normalized[left].merge(
                normalized[right],
                on="date",
                suffixes=("_left", "_right"),
            ).dropna(subset=["value_left", "value_right"])
            if len(joined) < 3:
                continue
            correlation = joined["value_left"].corr(joined["value_right"], method="spearman")
            if pd.notna(correlation) and abs(float(correlation)) >= near_duplicate_threshold:
                near_pairs.append((left, right))

    return FeatureAuditReport(
        ready=not empty,
        empty_lanes=tuple(empty),
        exact_duplicate_groups=exact_groups,
        near_duplicate_pairs=tuple(near_pairs),
        coverage=tuple(coverage),
    )

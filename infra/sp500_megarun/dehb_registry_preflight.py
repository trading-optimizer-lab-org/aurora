"""Physical train-only preflight for every F001-F240 DEHB lane route."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.dehb_worker import (
    FeatureEvaluator,
    feature_frame_to_decisions,
)


class RegistryPreflightError(ValueError):
    """Raised when one physical lane route is incomplete or non-causal."""


def audit_lane_registry(
    *,
    evaluator: FeatureEvaluator,
    default_configurations: Mapping[str, Mapping[str, Any]],
    expected_lane_ids: Sequence[str],
    allowed_end: str,
) -> Mapping[str, Any]:
    """Exercise every lane once without calculating or selecting performance."""

    expected = tuple(expected_lane_ids)
    if tuple(sorted(default_configurations)) != expected:
        raise RegistryPreflightError("DEFAULT_CONFIGURATION_LANES_MISMATCH")
    rows: list[dict[str, Any]] = []
    for lane_id in expected:
        feature = evaluator(lane_id, default_configurations[lane_id])
        decisions = feature_frame_to_decisions(feature, allowed_end=allowed_end)
        non_null = decisions.dropna()
        if non_null.empty:
            raise RegistryPreflightError(f"LANE_HAS_NO_DECISION:{lane_id}")
        values = non_null.to_numpy(dtype=float)
        if not np.isin(values, (-1.0, 1.0)).all():
            raise RegistryPreflightError(f"LANE_DECISION_DOMAIN_INVALID:{lane_id}")
        dates = pd.DatetimeIndex(non_null.index).normalize()
        payload = np.column_stack(
            (
                dates.asi8.astype("<i8", copy=False),
                values.astype("<f8", copy=False).view("<i8"),
            )
        ).astype("<i8", copy=False).tobytes()
        rows.append(
            {
                "lane_id": lane_id,
                "feature_rows": int(len(feature)),
                "decision_count": int(len(non_null)),
                "first_decision": dates.min().date().isoformat(),
                "last_decision": dates.max().date().isoformat(),
                "decision_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    aggregate = hashlib.sha256(
        "\n".join(
            f"{row['lane_id']}:{row['decision_sha256']}" for row in rows
        ).encode("ascii")
    ).hexdigest()
    return {
        "schema_version": 1,
        "ready": len(rows) == len(expected),
        "lane_count": len(rows),
        "aggregate_decision_sha256": aggregate,
        "lanes": rows,
        "performance_scored": False,
        "search_executed": False,
        "validation_opened": False,
        "locked_opened": False,
    }


__all__ = ["RegistryPreflightError", "audit_lane_registry"]

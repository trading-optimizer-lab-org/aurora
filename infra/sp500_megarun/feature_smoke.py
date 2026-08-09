"""Train-only technical smoke for the executable SP500 price families."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import apply_available_at_policy
from aurora.infra.sp500_megarun.feature_engine import (
    FeatureEngineError,
    evaluate_price_family_batch,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame


_PRICE_LANE_IDS = tuple(f"F{number:03d}" for number in range(1, 21))
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_price_feature_smoke(
    spy_frame: pd.DataFrame,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Build and audit F001-F020 using only the supplied 1993-2010 SPY rows."""

    if "date" not in spy_frame:
        raise FeatureEngineError("MISSING_SPY_COLUMNS:date")
    dates = pd.to_datetime(spy_frame["date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise FeatureEngineError("INVALID_SPY_TIMESTAMPS")
    if dates.gt(_TRAIN_END).any():
        raise FeatureEngineError("NON_TRAIN_PRICE_ROW")

    sessions = pd.DatetimeIndex(dates).unique().sort_values()
    available_spy = apply_available_at_policy(
        spy_frame,
        policy="same_session",
        sessions=sessions,
    )
    outputs = evaluate_price_family_batch(available_spy)
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_PRICE_LANE_IDS,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )

    root = Path(output_dir)
    feature_dir = root / "features"
    feature_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for lane_id in _PRICE_LANE_IDS:
        target = feature_dir / f"{lane_id}.parquet"
        parquet_safe_frame(outputs[lane_id]).to_parquet(target, index=False)
        artifacts[lane_id] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": int(len(outputs[lane_id])),
            "non_null_values": int(outputs[lane_id]["value"].notna().sum()),
        }

    maximum_feature_date = max(
        pd.to_datetime(frame["date"], errors="raise").max()
        for frame in outputs.values()
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(audit.ready and len(outputs) == len(_PRICE_LANE_IDS)),
        "scope": "technical_feature_smoke_train_only",
        "executable_lanes": list(_PRICE_LANE_IDS),
        "executable_lane_count": len(_PRICE_LANE_IDS),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "availability_policy": "same_session",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
    }
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "feature_smoke_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["FeatureEngineError", "build_price_feature_smoke"]

"""Train-only GitHub smoke for executable SP500 lanes F131-F140."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_calendar_state_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.nonlinear_feature_engine import (
    evaluate_nonlinear_family_batch,
)


class NonlinearFeatureSmokeError(ValueError):
    """Raised when the smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(131, 141))
_DATASETS = ("D_SPY", "D_CALENDAR")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_nonlinear_feature_smoke(
    train_snapshot: str | Path, *, output_dir: str | Path
) -> dict[str, Any]:
    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise NonlinearFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    data: dict[str, pd.DataFrame] = {}
    for dataset in _DATASETS:
        path = snapshot / f"{dataset}.parquet"
        if not path.is_file():
            raise NonlinearFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        data[dataset] = pd.read_parquet(path)
    if "date" not in data["D_CALENDAR"] or data["D_CALENDAR"].empty:
        raise NonlinearFeatureSmokeError("EMPTY_PHYSICAL_CALENDAR")
    sessions = (
        pd.DatetimeIndex(pd.to_datetime(data["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    panels = {
        "spy": normalize_spy_decision_panel(data["D_SPY"], sessions=sessions),
        "calendar": normalize_calendar_state_panel(sessions=sessions),
    }
    outputs = dict(evaluate_nonlinear_family_batch(panels))
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_LANES,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )
    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum = pd.Timestamp.min
    for lane, output in outputs.items():
        target = root / "features" / f"{lane}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum = max(maximum, pd.to_datetime(output["date"]).max())
        artifacts[lane] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": len(output),
            "non_null_values": int(output["value"].notna().sum()),
        }
    report = {
        "schema_version": 1,
        "ready": bool(audit.ready and len(outputs) == 10),
        "scope": "nonlinear_path_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "search_start": "1998-01-01",
        "train_end": "2010-12-31",
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [
            list(group) for group in audit.exact_duplicate_groups
        ],
        "near_duplicate_pairs": [
            list(pair) for pair in audit.near_duplicate_pairs
        ],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "nonlinear_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


__all__ = ["NonlinearFeatureSmokeError", "build_nonlinear_feature_smoke"]

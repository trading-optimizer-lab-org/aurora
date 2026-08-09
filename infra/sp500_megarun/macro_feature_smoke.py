"""Train-only GitHub smoke for executable SP500 macro lane F032."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_credit_spread_panel,
)
from aurora.infra.sp500_megarun.macro_feature_engine import evaluate_macro_lane
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame


class MacroFeatureSmokeError(ValueError):
    """Raised when the smoke target is not the physical train snapshot."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_macro_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Normalize, execute and audit F032 without mounting validation."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise MacroFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    rates_path = snapshot / "D_RATES.parquet"
    if not rates_path.is_file():
        raise MacroFeatureSmokeError("TRAIN_DATASET_MISSING:D_RATES")
    rates = pd.read_parquet(rates_path)
    sessions = pd.bdate_range(
        pd.to_datetime(rates["date"], errors="raise").min(),
        _TRAIN_END,
    )
    credit = normalize_credit_spread_panel(rates, sessions=sessions)
    output = evaluate_macro_lane(
        "F032",
        {"credit": credit},
        {"window": 252, "change_lag": 5},
    )
    audit = audit_feature_outputs(
        {"F032": output},
        expected_lane_ids=("F032",),
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )

    root = Path(output_dir)
    target = root / "features" / "F032.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    parquet_safe_frame(output).to_parquet(target, index=False)
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(audit.ready),
        "scope": "technical_macro_feature_smoke_train_only",
        "executable_lanes": ["F032"],
        "executable_lane_count": 1,
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": output["date"].max().date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": {
            "F032": {
                "path": target.relative_to(root).as_posix(),
                "sha256": _sha256(target),
                "rows": int(len(output)),
                "non_null_values": int(output["value"].notna().sum()),
            }
        },
    }
    (root / "macro_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["MacroFeatureSmokeError", "build_macro_feature_smoke"]

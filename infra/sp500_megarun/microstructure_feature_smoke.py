"""Train-only GitHub smoke for executable SP500 lanes F071-F080."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.microstructure_feature_engine import (
    evaluate_microstructure_family_batch,
    evaluate_microstructure_lane,
)
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class MicrostructureFeatureSmokeError(ValueError):
    """Raised when the smoke is not bound to the physical train partition."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_EXECUTABLE_LANES = tuple(f"F{index:03d}" for index in range(71, 81))
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_microstructure_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F074" and parameter == "tolerance":
        configuration["statistic"] = "touch_imbalance"
    if lane_id == "F079" and parameter == "zero_tolerance_bps":
        configuration["statistic"] = "zero_return_rate"
    if lane_id == "F080" and parameter == "stress_quantile":
        configuration["liquidity"] = "volume_drought"
    return configuration


def build_microstructure_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute and audit F071-F080 without mounting validation or locked data."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise MicrostructureFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    spy_path = snapshot / "D_SPY.parquet"
    calendar_path = snapshot / "D_CALENDAR.parquet"
    if not spy_path.is_file():
        raise MicrostructureFeatureSmokeError("TRAIN_DATASET_MISSING:D_SPY")
    if not calendar_path.is_file():
        raise MicrostructureFeatureSmokeError("TRAIN_DATASET_MISSING:D_CALENDAR")
    calendar = pd.read_parquet(calendar_path)
    if "date" not in calendar:
        raise MicrostructureFeatureSmokeError("CALENDAR_DATE_MISSING")
    sessions = pd.DatetimeIndex(
        pd.to_datetime(calendar["date"], errors="raise")
    ).normalize().unique().sort_values()
    sessions = sessions[sessions <= _TRAIN_END]
    spy = normalize_spy_decision_panel(
        pd.read_parquet(spy_path),
        sessions=sessions,
    )
    spy = spy.loc[spy["date"].le(_TRAIN_END)].reset_index(drop=True)
    outputs = dict(evaluate_microstructure_family_batch(spy))
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_EXECUTABLE_LANES,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
    )
    data_contract = load_and_validate_contract(
        _REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
    )
    feature_contract = load_and_validate_feature_contract(
        _REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json",
        data_contract,
    )
    expected_years = sorted(
        set(
            pd.to_datetime(spy["date"], errors="raise")
            .loc[lambda values: values.ge(_SEARCH_START)]
            .dt.year
        )
    )
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_EXECUTABLE_LANES,
        evaluator=lambda lane_id, configuration: evaluate_microstructure_lane(
            lane_id,
            spy,
            configuration,
        ),
        expected_years=expected_years,
        repair=_repair_microstructure_configuration,
    )

    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum_feature_date = pd.Timestamp.min
    for lane_id, output in outputs.items():
        target = root / "features" / f"{lane_id}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum_feature_date = max(
            maximum_feature_date,
            pd.to_datetime(output["date"], errors="raise").max(),
        )
        artifacts[lane_id] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": int(len(output)),
            "non_null_values": int(output["value"].notna().sum()),
        }

    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(
            audit.ready
            and parameter_audit["ready"]
            and len(outputs) == len(_EXECUTABLE_LANES)
        ),
        "scope": "technical_microstructure_feature_smoke_train_only",
        "executable_lanes": list(_EXECUTABLE_LANES),
        "executable_lane_count": len(_EXECUTABLE_LANES),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "availability_policy": "next_session",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "microstructure_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F071_F080.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "MicrostructureFeatureSmokeError",
    "build_microstructure_feature_smoke",
]

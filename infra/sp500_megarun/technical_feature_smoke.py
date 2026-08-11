"""Train-only GitHub smoke for executable SP500 lanes F121-F130."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.technical_feature_engine import (
    evaluate_technical_family_batch,
    evaluate_technical_lane,
)


class TechnicalFeatureSmokeError(ValueError):
    """Raised when the smoke is not bound to the physical train partition."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(121, 131))
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_technical_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F121" and parameter in {"buffer_fraction", "confirmation"}:
        configuration["statistic"] = "confirmed_breakout"
    if lane_id == "F124":
        if parameter == "base_window":
            configuration["span_b_window"] = 126
        if parameter == "span_b_window":
            configuration["statistic"] = "cloud_width"
    if lane_id == "F125":
        if parameter == "window":
            configuration["statistic"] = "chandelier"
        if parameter == "atr_multiplier":
            configuration["statistic"] = "supertrend"
        if parameter in {"acceleration_step", "acceleration_max"}:
            configuration["statistic"] = "parabolic_sar"
    if lane_id == "F127":
        if parameter == "statistic":
            configuration["reversal_boxes"] = 3
        if parameter in {"window", "box_atr"}:
            configuration["statistic"] = "renko"
        if parameter == "reversal_boxes":
            configuration["statistic"] = "point_figure"
    if lane_id == "F128":
        if parameter in {"tolerance", "breakout_buffer"}:
            configuration["statistic"] = "double_extreme"
        if parameter == "breakout_buffer":
            configuration["tolerance"] = 0.08
        if parameter == "head_margin":
            configuration["statistic"] = "shoulders"
    if lane_id == "F130" and parameter.startswith("klinger_"):
        configuration["statistic"] = "klinger_oscillator"
    return configuration


def build_technical_feature_smoke(
    train_snapshot: str | Path, *, output_dir: str | Path
) -> dict[str, Any]:
    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise TechnicalFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    spy_path = snapshot / "D_SPY.parquet"
    if not spy_path.is_file():
        raise TechnicalFeatureSmokeError("TRAIN_DATASET_MISSING:D_SPY")
    raw_spy = pd.read_parquet(spy_path)
    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw_spy["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    spy = normalize_spy_decision_panel(raw_spy, sessions=sessions)
    outputs = dict(evaluate_technical_family_batch(spy))
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_LANES,
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
        set(pd.DatetimeIndex(sessions[sessions >= _SEARCH_START]).year)
    )
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANES,
        evaluator=lambda lane_id, configuration: evaluate_technical_lane(
            lane_id,
            spy,
            configuration,
        ),
        expected_years=expected_years,
        repair=_repair_technical_configuration,
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
        "ready": bool(
            audit.ready and parameter_audit["ready"] and len(outputs) == 10
        ),
        "scope": "technical_indicator_feature_smoke_train_only",
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
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "technical_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "parameter_choice_audit_F121_F130.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["TechnicalFeatureSmokeError", "build_technical_feature_smoke"]

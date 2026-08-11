"""Train-only GitHub smoke for executable SP500 lanes F131-F140."""

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
    normalize_calendar_state_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.nonlinear_feature_engine import (
    evaluate_nonlinear_family_batch,
    evaluate_nonlinear_lane,
)
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class NonlinearFeatureSmokeError(ValueError):
    """Raised when the smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(131, 141))
_DATASETS = ("D_SPY", "D_CALENDAR")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_HISTORY = {
    "F131": 721,
    "F132": 252,
    "F133": 504,
    "F134": 1261,
    "F135": 504,
    "F136": 252,
    "F137": 504,
    "F138": 505,
    "F139": 504,
    "F140": 510,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repair_nonlinear_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F131" and parameter == "statistic":
        configuration["scales"] = 4
    if lane_id == "F132":
        if parameter in {"ensembles", "noise_scale"}:
            configuration["kind"] = "eemd"
        if parameter == "components":
            configuration["statistic"] = "residual"
            configuration["kind"] = "eemd"
            configuration["noise_scale"] = 0.1
    if lane_id == "F133":
        if parameter == "embedding":
            configuration["window"] = 126
        if parameter == "components":
            configuration["statistic"] = "residual"
        if parameter == "statistic":
            configuration["components"] = 3
    if lane_id == "F134" and parameter == "min_occurrences":
        configuration["statistic"] = "combined"
    if lane_id == "F135":
        if parameter == "neighbors":
            configuration["statistic"] = "motif_follow_through"
        if parameter == "radius":
            configuration["statistic"] = "motif_density"
        if parameter == "statistic":
            configuration["neighbors"] = 3
    if lane_id == "F136" and parameter == "minimum_line":
        configuration["statistic"] = "determinism"
    if lane_id == "F137" and parameter in {"q_low", "q_high"}:
        configuration["statistic"] = "multifractal_width"
    if lane_id == "F139":
        if parameter == "asymmetry":
            configuration["kind"] = "asymmetric_ewma"
            configuration["statistic"] = "variance_gap"
        if parameter == "kind" and configuration.get("kind") == "asymmetric_ewma":
            configuration["asymmetry"] = 1.0
        if parameter == "window":
            configuration["statistic"] = "variance_gap"
    if lane_id == "F140" and parameter == "transition_speed":
        configuration["kind"] = "star"
        configuration["statistic"] = "forecast"
    return configuration


def _parameter_audit_panels(
    panels: dict[str, pd.DataFrame], lane_id: str
) -> dict[str, pd.DataFrame]:
    if lane_id not in _PARAMETER_AUDIT_HISTORY:
        raise NonlinearFeatureSmokeError(f"UNKNOWN_PARAMETER_AUDIT_LANE:{lane_id}")
    spy_dates = pd.DatetimeIndex(
        pd.to_datetime(panels["spy"]["date"], errors="raise")
    )
    first_witness = int(spy_dates.searchsorted(pd.Timestamp("2010-01-01")))
    if first_witness >= len(spy_dates):
        raise NonlinearFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    start = max(0, first_witness - _PARAMETER_AUDIT_HISTORY[lane_id])
    start_date = spy_dates[start]
    result: dict[str, pd.DataFrame] = {}
    for name, panel in panels.items():
        panel_dates = pd.DatetimeIndex(
            pd.to_datetime(panel["date"], errors="raise")
        )
        bounded = panel_dates.to_series(index=panel.index).between(
            start_date,
            _TRAIN_END,
        )
        result[name] = panel.loc[bounded].reset_index(drop=True)
    result_dates = pd.DatetimeIndex(result["spy"]["date"])
    if any(
        not result_dates.isin(pd.DatetimeIndex(panel["date"])).all()
        for panel in result.values()
    ):
        raise NonlinearFeatureSmokeError("PARAMETER_AUDIT_PANELS_NOT_ALIGNED")
    return result


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
    data_contract = load_and_validate_contract(
        _REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
    )
    feature_contract = load_and_validate_feature_contract(
        _REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json",
        data_contract,
    )
    audit_panels = {
        lane_id: _parameter_audit_panels(panels, lane_id) for lane_id in _LANES
    }
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANES,
        evaluator=lambda lane_id, configuration: evaluate_nonlinear_lane(
            lane_id,
            audit_panels[lane_id],
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_nonlinear_configuration,
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
        "parameter_choice_audit_scope": (
            "lane_specific_physical_causal_tail_ending_2010"
        ),
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "nonlinear_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "parameter_choice_audit_F131_F140.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["NonlinearFeatureSmokeError", "build_nonlinear_feature_smoke"]

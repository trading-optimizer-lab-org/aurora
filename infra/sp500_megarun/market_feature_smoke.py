"""Train-only GitHub smoke for executable SP500 market families F021-F031."""

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
    normalize_cboe_vol_panel,
    normalize_cftc_sp500_panel,
    normalize_spy_decision_panel,
    normalize_treasury_curve_panel,
)
from aurora.infra.sp500_megarun.market_feature_engine import (
    evaluate_market_family_batch,
    evaluate_market_lane,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class MarketFeatureSmokeError(ValueError):
    """Raised when the smoke target is not the physical train snapshot."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_LANE_IDS = tuple(f"F{number:03d}" for number in range(21, 32))
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_REQUIRED_DATASETS = ("D_SPY", "D_VIX", "D_VXO", "D_CFTC", "D_RATES")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_inputs(snapshot: Path) -> dict[str, pd.DataFrame]:
    inputs: dict[str, pd.DataFrame] = {}
    for dataset_id in _REQUIRED_DATASETS:
        target = snapshot / f"{dataset_id}.parquet"
        if not target.is_file():
            raise MarketFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset_id}")
        inputs[dataset_id] = pd.read_parquet(target)
    return inputs


def _repair_market_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if (
        "normalization" in configuration
        and configuration.get("normalization") != "none"
        and int(configuration.get("window", 20)) < 5
    ):
        configuration["window"] = 20
    if lane_id == "F022" and parameter == "tail":
        configuration["window"] = 504
    if parameter == "form" and configuration.get("form") in {
        "correlation",
        "divergence",
    }:
        configuration["window"] = max(int(configuration.get("window", 20)), 20)
    if parameter == "statistic" and configuration.get("statistic") == "divergence":
        configuration["window"] = max(int(configuration.get("window", 20)), 20)
    if parameter == "normalization" and lane_id == "F024":
        configuration["statistic"] = "divergence"
    return configuration


def build_market_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Normalize, execute and audit F021-F031 without mounting validation."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise MarketFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw = _read_inputs(snapshot)
    sessions = pd.DatetimeIndex(
        pd.to_datetime(raw["D_SPY"]["date"], errors="raise")
    ).normalize().unique().sort_values()
    panels = {
        "spy": normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "cboe": normalize_cboe_vol_panel(
            raw["D_VIX"], raw["D_VXO"], sessions=sessions
        ),
        "cftc": normalize_cftc_sp500_panel(raw["D_CFTC"], sessions=sessions),
        "rates": normalize_treasury_curve_panel(raw["D_RATES"], sessions=sessions),
    }
    outputs = evaluate_market_family_batch(panels)
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_LANE_IDS,
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
            pd.to_datetime(panels["spy"]["date"], errors="raise")
            .loc[lambda values: values.ge(_SEARCH_START)]
            .dt.year
        )
    )
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANE_IDS,
        evaluator=lambda lane_id, parameters: evaluate_market_lane(
            lane_id, panels, parameters
        ),
        expected_years=expected_years,
        repair=_repair_market_configuration,
    )

    root = Path(output_dir)
    feature_dir = root / "features"
    feature_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for lane_id in _LANE_IDS:
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
        "ready": bool(
            audit.ready
            and parameter_audit["ready"]
            and len(outputs) == len(_LANE_IDS)
        ),
        "scope": "technical_market_feature_smoke_train_only",
        "executable_lanes": list(_LANE_IDS),
        "executable_lane_count": len(_LANE_IDS),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "cftc_minimum_observation_date": panels["cftc"]["observed_at"]
        .min()
        .date()
        .isoformat(),
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F021_F031.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["MarketFeatureSmokeError", "build_market_feature_smoke"]

"""Train-only GitHub smoke for executable SP500 lanes F051-F060."""

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
from aurora.infra.sp500_megarun.model_feature_engine import evaluate_model_lane
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class ModelFeatureSmokeError(ValueError):
    """Raised when the model smoke is not bound to physical train inputs."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_EXECUTABLE_LANES = tuple(f"F{index:03d}" for index in range(51, 61))
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_simple_features(
    *,
    price_feature_dir: Path,
    market_feature_dir: Path,
    macro_feature_dir: Path,
) -> dict[str, pd.DataFrame]:
    roots = {
        **{f"F{index:03d}": price_feature_dir for index in range(1, 21)},
        **{f"F{index:03d}": market_feature_dir for index in range(21, 32)},
        **{f"F{index:03d}": macro_feature_dir for index in range(32, 51)},
    }
    panels: dict[str, pd.DataFrame] = {}
    for lane_id, root in roots.items():
        target = root / "features" / f"{lane_id}.parquet"
        if not target.is_file():
            raise ModelFeatureSmokeError(f"SIMPLE_FEATURE_MISSING:{lane_id}")
        panels[lane_id] = pd.read_parquet(target)
    return panels


def _repair_model_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F051" and parameter == "normalization_window":
        configuration["aggregation"] = "weighted_vote"
    if lane_id == "F052":
        if parameter == "base":
            configuration["logic"] = "switch"
        if parameter == "confirmation":
            configuration["gate"] = "vix"
            configuration["logic"] = "override"
        if parameter == "logic":
            configuration["base"] = "reversal"
            configuration["gate"] = "vix"
    if lane_id == "F055" and parameter == "reset":
        configuration["kind"] = "cusum"
    if lane_id == "F057":
        if parameter == "components":
            configuration["model"] = "pls"
        if parameter in {"knots", "ridge"}:
            configuration["model"] = "gam"
    if lane_id == "F058":
        if parameter == "depth":
            configuration["model"] = "tree"
        if parameter in {"estimators", "learning_rate"}:
            configuration["model"] = "boosted_stumps"
    if lane_id == "F059":
        if parameter == "depth":
            configuration["logic"] = "or"
        if parameter == "logic" and configuration["logic"] == "majority":
            configuration["depth"] = 3
    if lane_id == "F060":
        if parameter == "hold":
            configuration["rule"] = "rev2"
        if parameter == "seed":
            configuration["rule"] = "block_placebo"
    return configuration


def build_model_feature_smoke(
    train_snapshot: str | Path,
    *,
    price_feature_dir: str | Path,
    market_feature_dir: str | Path,
    macro_feature_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute and audit F051-F060 without mounting validation or locked data."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise ModelFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    spy_path = snapshot / "D_SPY.parquet"
    calendar_path = snapshot / "D_CALENDAR.parquet"
    if not spy_path.is_file():
        raise ModelFeatureSmokeError("TRAIN_DATASET_MISSING:D_SPY")
    if not calendar_path.is_file():
        raise ModelFeatureSmokeError("TRAIN_DATASET_MISSING:D_CALENDAR")
    calendar = pd.read_parquet(calendar_path)
    if "date" not in calendar:
        raise ModelFeatureSmokeError("CALENDAR_DATE_MISSING")
    sessions = pd.DatetimeIndex(
        pd.to_datetime(calendar["date"], errors="raise")
    ).normalize().unique().sort_values()
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(
        pd.read_parquet(spy_path), sessions=sessions
    )
    market = market.loc[market["date"].le(_TRAIN_END)].reset_index(drop=True)
    feature_panels = _load_simple_features(
        price_feature_dir=Path(price_feature_dir),
        market_feature_dir=Path(market_feature_dir),
        macro_feature_dir=Path(macro_feature_dir),
    )
    parameters: dict[str, dict[str, Any]] = {
        "F051": {
            "component_set": "diversified",
            "components": 5,
            "aggregation": "weighted_vote",
            "normalization_window": 63,
        },
        "F052": {
            "base": "trend",
            "gate": "credit",
            "logic": "switch",
            "confirmation": 2,
        },
        "F053": {
            "feature_set": "diversified_3",
            "clusters": 3,
            "window": 252,
            "refit": "quarterly",
        },
        "F054": {
            "states": 2,
            "ar_order": 1,
            "window": 252,
            "refit": "quarterly",
            "probability": 0.5,
        },
        "F055": {
            "kind": "page_hinkley",
            "window": 63,
            "penalty": 1.0,
            "reset": True,
        },
        "F056": {
            "model": "logit",
            "feature_set": "diversified_3",
            "window": 252,
            "refit": "quarterly",
            "threshold": 0.525,
            "ridge": 1.0,
        },
        "F057": {
            "model": "pls",
            "feature_set": "diversified_5",
            "window": 252,
            "refit": "quarterly",
            "threshold": 0.525,
            "components": 2,
            "knots": 3,
            "ridge": 1.0,
        },
        "F058": {
            "model": "boosted_stumps",
            "feature_set": "market_5",
            "window": 252,
            "refit": "quarterly",
            "threshold": 0.525,
            "depth": 1,
            "estimators": 25,
            "learning_rate": 0.5,
        },
        "F059": {
            "feature_set": "diversified_5",
            "window": 252,
            "refit": "quarterly",
            "depth": 3,
            "logic": "majority",
            "threshold_quantile": 0.5,
        },
        "F060": {"rule": "block_placebo", "hold": 10, "seed": 17},
    }
    outputs: dict[str, pd.DataFrame] = {}
    for lane_id in _EXECUTABLE_LANES:
        output = evaluate_model_lane(
            lane_id,
            market,
            {**feature_panels, **outputs},
            parameters[lane_id],
        )
        outputs[lane_id] = output
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
            pd.to_datetime(market["date"], errors="raise")
            .loc[lambda values: values.ge(_SEARCH_START)]
            .dt.year
        )
    )
    evaluation_panels = {**feature_panels, **outputs}
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_EXECUTABLE_LANES,
        evaluator=lambda lane_id, configuration: evaluate_model_lane(
            lane_id,
            market,
            evaluation_panels,
            configuration,
        ),
        expected_years=expected_years,
        repair=_repair_model_configuration,
    )

    root = Path(output_dir)
    artifacts: dict[str, dict[str, object]] = {}
    maximum_feature_date = pd.Timestamp.min
    for lane_id, output in outputs.items():
        target = root / "features" / f"{lane_id}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        parquet_safe_frame(output).to_parquet(target, index=False)
        maximum_feature_date = max(maximum_feature_date, output["date"].max())
        artifacts[lane_id] = {
            "path": target.relative_to(root).as_posix(),
            "sha256": _sha256(target),
            "rows": int(len(output)),
            "non_null_values": int(output["value"].notna().sum()),
        }
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": bool(audit.ready and parameter_audit["ready"]),
        "scope": "technical_model_feature_smoke_train_only",
        "executable_lanes": list(_EXECUTABLE_LANES),
        "executable_lane_count": len(_EXECUTABLE_LANES),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum_feature_date.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "target_definition": "next_session_spy_return_known_one_session_later",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "model_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F051_F060.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["ModelFeatureSmokeError", "build_model_feature_smoke"]

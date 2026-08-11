"""Train-only GitHub smoke for executable SP500 lanes F141-F150."""

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
    normalize_cboe_vol_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.predictive_feature_engine import (
    evaluate_predictive_family_batch,
    evaluate_predictive_lane,
)
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class PredictiveFeatureSmokeError(ValueError):
    """Raised when the predictive smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(141, 151))
_DATASETS = ("D_SPY", "D_CALENDAR", "D_VIX", "D_VXO")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_HISTORY = {
    "F141": 1275,
    "F142": 1275,
    "F143": 1265,
    "F144": 1285,
    "F145": 1265,
    "F146": 1265,
    "F147": 1265,
    "F148": 1330,
    "F149": 1330,
    "F150": 1330,
}
_APPROVED_FEATURE_ROOTS = {
    "F003": "price",
    "F015": "price",
    "F021": "market",
    "F032": "macro",
    "F039": "macro",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_features(
    *,
    price_feature_dir: Path,
    market_feature_dir: Path,
    macro_feature_dir: Path,
) -> dict[str, pd.DataFrame]:
    roots = {
        "price": price_feature_dir,
        "market": market_feature_dir,
        "macro": macro_feature_dir,
    }
    features: dict[str, pd.DataFrame] = {}
    for lane, root_name in _APPROVED_FEATURE_ROOTS.items():
        target = roots[root_name] / "features" / f"{lane}.parquet"
        if not target.is_file():
            raise PredictiveFeatureSmokeError(f"CAUSAL_FEATURE_MISSING:{lane}")
        features[lane] = pd.read_parquet(target)
    return features


def _repair_predictive_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if parameter != "refit":
        configuration["refit"] = "annual"
    if lane_id == "F141":
        if parameter == "statistic" and configuration.get("statistic") == "innovation":
            configuration["kind"] = "arma"
            configuration["ma_order"] = 1
        if parameter == "ma_order":
            configuration["kind"] = (
                "arma" if int(configuration.get("ma_order", 0)) > 0 else "ar"
            )
        if parameter == "volume_lags":
            configuration["kind"] = "distributed_regression"
        if parameter == "kind" and configuration.get("kind") == "arma":
            configuration["ma_order"] = 1
    if (
        lane_id == "F142"
        and parameter == "statistic"
        and configuration.get("statistic") == "error_correction"
    ):
        configuration["kind"] = "vecm"
    if lane_id == "F143" and parameter == "sign_rule":
        configuration["statistic"] = "factor_score"
        configuration["components"] = 3
    if lane_id == "F144":
        if parameter == "forecast_quantile":
            configuration["statistic"] = "quantile_forecast"
        if parameter == "tail_quantile":
            configuration["statistic"] = "median_skew"
    if lane_id == "F145":
        if parameter == "gamma":
            configuration["kind"] = "rbf"
        if parameter == "degree":
            configuration["kind"] = "polynomial"
        if parameter == "support_vectors":
            configuration["window"] = 252
    if lane_id == "F150":
        if parameter == "temperature":
            configuration["kind"] = "attention"
            configuration["statistic"] = "attention_entropy"
        if parameter in {"experts", "gate"}:
            configuration["kind"] = "moe"
            configuration["statistic"] = "expert_disagreement"
        if parameter == "gate":
            configuration["lookback"] = 10
        if parameter == "statistic":
            if configuration.get("statistic") == "attention_entropy":
                configuration["kind"] = "attention"
            if configuration.get("statistic") == "expert_disagreement":
                configuration["kind"] = "moe"
    return configuration


def _parameter_audit_inputs(
    panels: dict[str, pd.DataFrame],
    feature_panels: dict[str, pd.DataFrame],
    lane_id: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    if lane_id not in _PARAMETER_AUDIT_HISTORY:
        raise PredictiveFeatureSmokeError(f"UNKNOWN_PARAMETER_AUDIT_LANE:{lane_id}")
    spy_dates = pd.DatetimeIndex(
        pd.to_datetime(panels["spy"]["date"], errors="raise")
    )
    first_witness = int(spy_dates.searchsorted(pd.Timestamp("2010-01-01")))
    if first_witness >= len(spy_dates):
        raise PredictiveFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    start = max(0, first_witness - _PARAMETER_AUDIT_HISTORY[lane_id])
    start_date = spy_dates[start]

    def bounded(frame: pd.DataFrame) -> pd.DataFrame:
        dates = pd.to_datetime(frame["date"], errors="raise")
        return frame.loc[dates.between(start_date, _TRAIN_END)].reset_index(drop=True)

    audit_panels = {name: bounded(panel) for name, panel in panels.items()}
    audit_features = {
        name: bounded(panel) for name, panel in feature_panels.items()
    }
    result_dates = pd.DatetimeIndex(audit_panels["spy"]["date"])
    if any(
        not result_dates.isin(pd.DatetimeIndex(panel["date"])).all()
        for panel in audit_panels.values()
    ):
        raise PredictiveFeatureSmokeError("PARAMETER_AUDIT_PANELS_NOT_ALIGNED")
    if any(panel.empty for panel in audit_features.values()):
        raise PredictiveFeatureSmokeError("PARAMETER_AUDIT_FEATURES_EMPTY")
    return audit_panels, audit_features


def build_predictive_feature_smoke(
    train_snapshot: str | Path,
    *,
    price_feature_dir: str | Path,
    market_feature_dir: str | Path,
    macro_feature_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F141-F150 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise PredictiveFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw: dict[str, pd.DataFrame] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise PredictiveFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        raw[dataset] = pd.read_parquet(target)
    if "date" not in raw["D_CALENDAR"] or raw["D_CALENDAR"].empty:
        raise PredictiveFeatureSmokeError("EMPTY_PHYSICAL_CALENDAR")
    feature_panels = _load_features(
        price_feature_dir=Path(price_feature_dir),
        market_feature_dir=Path(market_feature_dir),
        macro_feature_dir=Path(macro_feature_dir),
    )
    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    panels = {
        "spy": normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions),
        "cboe": normalize_cboe_vol_panel(
            raw["D_VIX"], raw["D_VXO"], sessions=sessions
        ),
    }
    outputs = dict(evaluate_predictive_family_batch(panels, feature_panels))
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
    audit_inputs = {
        lane_id: _parameter_audit_inputs(panels, feature_panels, lane_id)
        for lane_id in _LANES
    }
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANES,
        evaluator=lambda lane_id, configuration: evaluate_predictive_lane(
            lane_id,
            audit_inputs[lane_id][0],
            audit_inputs[lane_id][1],
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_predictive_configuration,
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
        "scope": "predictive_model_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "approved_causal_inputs": list(_APPROVED_FEATURE_ROOTS),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "target_definition": "next_session_spy_log_return_known_at_next_decision",
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [
            list(group) for group in audit.exact_duplicate_groups
        ],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": (
            "lane_specific_physical_causal_tail_ending_2010"
        ),
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "predictive_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "parameter_choice_audit_F141_F150.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["PredictiveFeatureSmokeError", "build_predictive_feature_smoke"]

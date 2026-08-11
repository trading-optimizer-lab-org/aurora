"""Train-only GitHub smoke for executable SP500 lanes F151-F160."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.characteristic_feature_engine import (
    evaluate_characteristic_family_batch,
    evaluate_characteristic_lane,
)
from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_french_characteristic_panels,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class CharacteristicFeatureSmokeError(ValueError):
    """Raised when the characteristic smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(151, 161))
_DATASETS = ("D_SPY", "D_CALENDAR", "D_FRENCH_US")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("2004-01-01")
_APPROVED_RESOURCES = (
    "size_daily",
    "book_to_market_daily",
    "profitability_daily",
    "investment_daily",
    "momentum_10_daily",
    "short_reversal_10_daily",
    "long_reversal_10_daily",
    "accruals_monthly",
    "beta_monthly",
    "net_share_issues_monthly",
    "variance_monthly",
    "residual_variance_monthly",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parameter_audit_inputs(
    market: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    market_dates = pd.to_datetime(market["date"], errors="raise")
    audit_market = market.loc[
        market_dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
    ].reset_index(drop=True)
    if not pd.DatetimeIndex(audit_market["date"]).year.astype(int).tolist().count(2010):
        raise CharacteristicFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise CharacteristicFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_characteristic_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F151-F160 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise CharacteristicFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw: dict[str, pd.DataFrame] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise CharacteristicFeatureSmokeError(
                f"TRAIN_DATASET_MISSING:{dataset}"
            )
        raw[dataset] = pd.read_parquet(target)
    if "date" not in raw["D_CALENDAR"] or raw["D_CALENDAR"].empty:
        raise CharacteristicFeatureSmokeError("EMPTY_PHYSICAL_CALENDAR")
    if "resource_id" not in raw["D_FRENCH_US"]:
        raise CharacteristicFeatureSmokeError("FRENCH_RESOURCE_ID_MISSING")
    resource_counts = {
        str(resource_id): int(count)
        for resource_id, count in raw["D_FRENCH_US"]["resource_id"]
        .astype(str)
        .value_counts()
        .items()
    }
    for resource_id in _APPROVED_RESOURCES:
        if resource_counts.get(resource_id, 0) < 1:
            raise CharacteristicFeatureSmokeError(
                f"FRENCH_RESOURCE_MISSING:{resource_id}"
            )

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = normalize_french_characteristic_panels(
        raw["D_FRENCH_US"], sessions=sessions
    )
    missing_panels = [resource for resource in _APPROVED_RESOURCES if resource not in panels]
    if missing_panels:
        raise CharacteristicFeatureSmokeError(
            f"NORMALIZED_FRENCH_PANEL_MISSING:{','.join(missing_panels)}"
        )
    outputs = dict(evaluate_characteristic_family_batch(market, panels))
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
    audit_market, audit_panels = _parameter_audit_inputs(market, panels)
    parameter_audit = audit_frozen_parameter_choices(
        feature_contract,
        lane_ids=_LANES,
        evaluator=lambda lane_id, configuration: evaluate_characteristic_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
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
        "scope": "characteristic_portfolio_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "approved_free_resources": list(_APPROVED_RESOURCES),
        "physical_resource_rows": {
            resource: resource_counts[resource] for resource in _APPROVED_RESOURCES
        },
        "daily_release_policy": "next_spy_session",
        "monthly_release_policy": "month_end_then_second_month_tenth_spy_session",
        "row_release_causality_valid": True,
        "historical_revision_pit_exact": False,
        "source_vintage_status": "current_download_not_historical_vintage",
        "source_vintage_warning": (
            "Kenneth French may revise full history; treat these as broad-US "
            "current-vintage proxy lanes and require exclusion robustness."
        ),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [
            list(group) for group in audit.exact_duplicate_groups
        ],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": (
            "physical_causal_tail_2004_2010"
        ),
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "characteristic_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "parameter_choice_audit_F151_F160.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["CharacteristicFeatureSmokeError", "build_characteristic_feature_smoke"]

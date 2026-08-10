"""Train-only GitHub smoke for executable SP500 lanes F171-F180."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.cross_asset_feature_engine import (
    evaluate_cross_asset_family_batch,
    evaluate_cross_asset_lane,
)
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_fx_cross_asset_panel,
    normalize_spy_decision_panel,
    normalize_treasury_curve_panel,
    normalize_usd_funding_panel,
    normalize_world_bank_commodity_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


class CrossAssetFeatureSmokeError(ValueError):
    """Raised when the F171-F180 smoke is not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(171, 181))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("2003-01-01")
_DATASETS = (
    "D_SPY",
    "D_CALENDAR",
    "D_FED_H15_H10",
    "D_WORLD_BANK_COMMODITIES",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _merge_rate_panels(
    curve: pd.DataFrame,
    funding: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["date", "observed_at", "available_at"]
    merged = curve.merge(
        funding,
        on=keys,
        how="inner",
        validate="one_to_one",
    )
    if merged.empty:
        raise CrossAssetFeatureSmokeError("EMPTY_MERGED_RATE_PANEL")
    for column in merged.columns:
        if column in {"date", "observed_at", "available_at"}:
            continue
        values = pd.to_numeric(merged[column], errors="coerce")
        if values.lt(-5.0).any() or values.gt(50.0).any():
            raise CrossAssetFeatureSmokeError(
                f"NORMALIZED_RATE_OUT_OF_RANGE:{column}"
            )
    return merged.sort_values("date", kind="mergesort").reset_index(drop=True)


def _repair_cross_asset_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if lane_id == "F171" and parameter == "threshold":
        configuration["statistic"] = "breadth"
    if lane_id == "F172" and parameter == "window":
        configuration["statistic"] = "fx_adjusted_pressure"
    if lane_id == "F173" and parameter == "aggregation":
        configuration["selection_fraction"] = 0.25
    if lane_id in {"F174", "F176"} and parameter == "window":
        configuration["statistic"] = "momentum"
    if lane_id in {"F174", "F176"} and parameter == "threshold":
        configuration["statistic"] = "breadth"
    if lane_id == "F177" and parameter == "threshold":
        configuration["statistic"] = "breadth"
    if lane_id == "F178" and parameter == "normalization_window":
        configuration["statistic"] = "volatility_scaled_mean"
    if lane_id == "F179" and parameter == "z_window":
        configuration["normalization"] = "rolling_zscore"
    if lane_id == "F180" and parameter == "long_window":
        configuration["statistic"] = "decoupling"
    return configuration


def _parameter_audit_inputs(
    market: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    market_dates = pd.to_datetime(market["date"], errors="raise")
    audit_market = market.loc[
        market_dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
    ].reset_index(drop=True)
    if not (pd.DatetimeIndex(audit_market["date"]).year == 2010).any():
        raise CrossAssetFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise CrossAssetFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_cross_asset_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F171-F180 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise CrossAssetFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise CrossAssetFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        raw[dataset] = pd.read_parquet(target)
        source_hashes[dataset] = _sha256(target)
        if "date" not in raw[dataset] or raw[dataset].empty:
            raise CrossAssetFeatureSmokeError(f"EMPTY_PHYSICAL_DATASET:{dataset}")
        dates = pd.to_datetime(raw[dataset]["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise CrossAssetFeatureSmokeError(f"NON_TRAIN_SOURCE_ROW:{dataset}")

    fed = raw["D_FED_H15_H10"]
    if "source_dataset" not in fed:
        raise CrossAssetFeatureSmokeError("FED_SOURCE_DATASET_MISSING")
    fed_sources = set(fed["source_dataset"].astype(str))
    for source in ("D_RATES", "D_FX"):
        if source not in fed_sources:
            raise CrossAssetFeatureSmokeError(f"FED_SOURCE_MISSING:{source}")

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    curve = normalize_treasury_curve_panel(fed, sessions=sessions)
    funding = normalize_usd_funding_panel(fed, sessions=sessions)
    panels = {
        "fx": normalize_fx_cross_asset_panel(fed, sessions=sessions),
        "rates": _merge_rate_panels(curve, funding),
        "commodities": normalize_world_bank_commodity_panel(
            raw["D_WORLD_BANK_COMMODITIES"], sessions=sessions
        ),
    }

    outputs = dict(evaluate_cross_asset_family_batch(market, panels))
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
        evaluator=lambda lane_id, configuration: evaluate_cross_asset_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_cross_asset_configuration,
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

    source_rows = {
        dataset: int(len(frame)) for dataset, frame in raw.items()
    }
    report = {
        "schema_version": 1,
        "ready": bool(
            audit.ready and parameter_audit["ready"] and len(outputs) == 10
        ),
        "scope": "fx_commodity_rates_cross_asset_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "physical_source_rows": source_rows,
        "source_sha256": source_hashes,
        "h10_release_policy": "following_week_release_plus_next_spy_session",
        "h15_release_policy": "daily_1615_et_plus_next_spy_session",
        "world_bank_release_policy": "third_spy_session_of_following_month",
        "row_release_causality_valid": True,
        "historical_revision_pit_exact": False,
        "source_vintage_status": "current_download_not_historical_vintage",
        "source_vintage_warning": (
            "Federal Reserve DDP and World Bank downloads may revise history; "
            "require candidate robustness both with and without F171-F180."
        ),
        "f172_fidelity": "usd_funding_pressure_proxy_not_fx_carry",
        "f172_warning": (
            "Uses U.S. Treasury 3m, Eurodollar 3m and the H.10 dollar trend; "
            "it is not a foreign-rate differential or tradable FX forward."
        ),
        "f179_fidelity": "constant_maturity_curve_proxy_not_tradable_roll",
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
        "parameter_choice_audit_scope": "physical_causal_tail_2003_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "cross_asset_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F171_F180.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "CrossAssetFeatureSmokeError",
    "build_cross_asset_feature_smoke",
]

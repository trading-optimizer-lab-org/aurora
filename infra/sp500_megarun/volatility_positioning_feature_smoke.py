"""Train-only GitHub smoke for executable SP500 lanes F211-F220."""

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
    normalize_cboe_vol_bundle_panel,
    normalize_cftc_cross_market_fallback_panel,
    normalize_cftc_sp500_panel,
    normalize_spy_decision_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.volatility_positioning_feature_engine import (
    evaluate_volatility_positioning_family_batch,
    evaluate_volatility_positioning_lane,
)


class VolatilityPositioningFeatureSmokeError(ValueError):
    """Raised when F211-F220 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(211, 221))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("2003-01-01")
_DATASETS = (
    "D_SPY",
    "D_CALENDAR",
    "D_CBOE_VOL",
    "D_CBOE_PCR",
    "D_CFTC_LEGACY",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_available(panel: pd.DataFrame, column: str) -> str | None:
    values = pd.to_numeric(panel[column], errors="coerce")
    valid = values.notna()
    if not valid.any():
        return None
    return pd.to_datetime(panel.loc[valid, "available_at"]).min().date().isoformat()


def _verify_pcr_fallback(frame: pd.DataFrame) -> None:
    if "source_dataset" not in frame:
        raise VolatilityPositioningFeatureSmokeError(
            "PCR_FALLBACK_PROVENANCE_MISSING:source_dataset"
        )
    sources = set(frame["source_dataset"].dropna().astype(str))
    if sources != {"D_CFTC"}:
        raise VolatilityPositioningFeatureSmokeError(
            "PCR_FALLBACK_PROVENANCE_MISSING:D_CFTC"
        )
    if "resource_id" not in frame or not frame["resource_id"].astype(str).str.contains(
        "legacy_futures_only", case=False
    ).any():
        raise VolatilityPositioningFeatureSmokeError(
            "PCR_FALLBACK_FUTURES_ONLY_MISSING"
        )


def _repair_volatility_positioning_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    if parameter == "change_lag":
        configuration["normalization"] = "change"
    window_statistics = {
        "F211": "vix_zscore",
        "F213": "spread_zscore",
        "F214": "shock_duration",
        "F215": "breadth_zscore",
        "F216": "disagreement_zscore",
        "F217": "commercial_zscore",
        "F220": "crowding_composite",
    }
    if lane_id in window_statistics and parameter == "window":
        configuration["statistic"] = window_statistics[lane_id]
    if lane_id in {"F218", "F219"} and parameter == "window":
        configuration["normalization"] = "rolling_zscore"
    lag_statistics = {
        "F211": "vix_trend",
        "F214": "normalization_speed",
        "F215": "breadth_trend",
        "F216": "disagreement_change",
        "F217": "commercial_change",
        "F218": "noncommercial_change",
    }
    if lane_id in lag_statistics and parameter == "lag":
        configuration["statistic"] = lag_statistics[lane_id]
    if lane_id == "F213" and parameter == "realized_window":
        configuration["statistic"] = "variance_spread"
    if lane_id == "F214" and parameter == "tail":
        configuration["statistic"] = "shock_duration"
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
        raise VolatilityPositioningFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise VolatilityPositioningFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_volatility_positioning_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute and audit F211-F220 without mounting later partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise VolatilityPositioningFeatureSmokeError("TRAIN_PARTITION_REQUIRED")

    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise VolatilityPositioningFeatureSmokeError(
                f"TRAIN_DATASET_MISSING:{dataset}"
            )
        raw[dataset] = pd.read_parquet(target)
        source_hashes[dataset] = _sha256(target)
        if "date" not in raw[dataset] or raw[dataset].empty:
            raise VolatilityPositioningFeatureSmokeError(
                f"EMPTY_PHYSICAL_DATASET:{dataset}"
            )
        dates = pd.to_datetime(raw[dataset]["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise VolatilityPositioningFeatureSmokeError(
                f"NON_TRAIN_SOURCE_ROW:{dataset}"
            )

    _verify_pcr_fallback(raw["D_CBOE_PCR"])
    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "vol": normalize_cboe_vol_bundle_panel(
            raw["D_CBOE_VOL"], sessions=sessions
        ),
        "fallback": normalize_cftc_cross_market_fallback_panel(
            raw["D_CBOE_PCR"], sessions=sessions
        ),
        "cftc": normalize_cftc_sp500_panel(
            raw["D_CFTC_LEGACY"], sessions=sessions
        ),
    }
    outputs = dict(evaluate_volatility_positioning_family_batch(market, panels))
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
        evaluator=lambda lane_id, configuration: evaluate_volatility_positioning_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_volatility_positioning_configuration,
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

    exact_duplicates = [list(group) for group in audit.exact_duplicate_groups]
    near_duplicates = [list(pair) for pair in audit.near_duplicate_pairs]
    ready = bool(
        audit.ready
        and parameter_audit["ready"]
        and len(outputs) == len(_LANES)
        and not exact_duplicates
        and not near_duplicates
    )
    report = {
        "schema_version": 1,
        "ready": ready,
        "scope": "volatility_positioning_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": len(outputs),
        "physical_source_rows": {
            dataset: int(len(frame)) for dataset, frame in raw.items()
        },
        "source_sha256": source_hashes,
        "row_release_causality_valid": True,
        "vix_bridge_policy": "VXO_before_2003_09_22_then_modern_VIX",
        "cftc_release_policy": "tuesday_observation_after_friday_release",
        "put_call_source": "preregistered_cftc_cross_market_fallback",
        "put_call_ratio_claimed": False,
        "f211_vix_first_available_at": _first_available(
            panels["vol"], "vix_close"
        ),
        "f215_fallback_first_available_at": _first_available(
            panels["fallback"], "commercial_breadth"
        ),
        "source_warning": (
            "D_CBOE_PCR is physically the preregistered CFTC fallback in this frozen "
            "snapshot. F215-F216 must never be described as put-call ratios."
        ),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": exact_duplicates,
        "near_duplicate_pairs": near_duplicates,
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": "physical_causal_tail_2003_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "volatility_positioning_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F211_F220.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "VolatilityPositioningFeatureSmokeError",
    "build_volatility_positioning_feature_smoke",
]

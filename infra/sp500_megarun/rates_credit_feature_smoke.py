"""Train-only GitHub smoke for executable SP500 lanes F181-F190."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_bank_credit_panel,
    normalize_cboe_vol_bundle_panel,
    normalize_commercial_paper_panel,
    normalize_consumer_credit_panel,
    normalize_credit_spread_panel,
    normalize_money_reserves_panel,
    normalize_spf_real_rate_panel,
    normalize_spy_decision_panel,
    normalize_treasury_curve_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.rates_credit_feature_engine import (
    evaluate_rates_credit_family_batch,
    evaluate_rates_credit_lane,
)


class RatesCreditFeatureSmokeError(ValueError):
    """Raised when F181-F190 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_FED_MISSING_SENTINEL = -9999.0
_LANES = tuple(f"F{index:03d}" for index in range(181, 191))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("2003-01-01")
_DATASETS = (
    "D_SPY",
    "D_CALENDAR",
    "D_FED_H15_H10",
    "D_FED_H3_H6_H8_G19_CP",
    "D_SPF",
    "D_CBOE_VOL",
)
_REQUIRED_MACRO_SOURCES = (
    "federal_reserve_cp_all",
    "federal_reserve_g19_all",
    "federal_reserve_h3_all",
    "federal_reserve_h6_all",
    "federal_reserve_h8_all",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_no_fed_sentinel(panels: Mapping[str, pd.DataFrame]) -> None:
    for name, panel in panels.items():
        values = panel.drop(
            columns=list({*panel.columns} & {"date", "observed_at", "available_at"})
        ).apply(pd.to_numeric, errors="coerce")
        if values.eq(_FED_MISSING_SENTINEL).any().any():
            raise RatesCreditFeatureSmokeError(f"FED_SENTINEL_SURVIVED:{name}")


def _first_available(panel: pd.DataFrame, column: str) -> str | None:
    values = pd.to_numeric(panel[column], errors="coerce")
    valid = values.notna()
    if not valid.any():
        return None
    return pd.to_datetime(panel.loc[valid, "available_at"]).min().date().isoformat()


def _repair_rates_credit_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    normalized_lanes = {"F181", "F182", "F184", "F185", "F186", "F187", "F188"}
    if lane_id in normalized_lanes and parameter == "window":
        configuration["normalization"] = "rolling_zscore"
    if lane_id in normalized_lanes and parameter == "change_lag":
        configuration["normalization"] = "change"
    if lane_id == "F182" and parameter == "shock_lag":
        configuration["statistic"] = "slope_shock"
    if lane_id == "F183" and parameter == "window":
        configuration["statistic"] = "change"
    if lane_id == "F185" and parameter == "lag":
        configuration["statistic"] = "outstanding_contraction"
    if lane_id == "F186" and parameter == "lag":
        configuration["statistic"] = "bank_credit_growth"
    if lane_id == "F187" and parameter == "lag":
        configuration["statistic"] = "money_growth"
    if lane_id == "F188" and parameter == "lag":
        configuration["statistic"] = "total_growth"
    if lane_id == "F190" and parameter == "threshold":
        configuration["statistic"] = "shock_breadth"
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
        raise RatesCreditFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise RatesCreditFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_rates_credit_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute F181-F190 without mounting validation or locked partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise RatesCreditFeatureSmokeError("TRAIN_PARTITION_REQUIRED")
    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise RatesCreditFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        raw[dataset] = pd.read_parquet(target)
        source_hashes[dataset] = _sha256(target)
        if "date" not in raw[dataset] or raw[dataset].empty:
            raise RatesCreditFeatureSmokeError(f"EMPTY_PHYSICAL_DATASET:{dataset}")
        dates = pd.to_datetime(raw[dataset]["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise RatesCreditFeatureSmokeError(f"NON_TRAIN_SOURCE_ROW:{dataset}")

    fed = raw["D_FED_H15_H10"]
    if "source_dataset" not in fed:
        raise RatesCreditFeatureSmokeError("FED_SOURCE_DATASET_MISSING")
    if "D_RATES" not in set(fed["source_dataset"].astype(str)):
        raise RatesCreditFeatureSmokeError("FED_SOURCE_MISSING:D_RATES")

    macro = raw["D_FED_H3_H6_H8_G19_CP"]
    if "resource_id" not in macro:
        raise RatesCreditFeatureSmokeError("FED_MACRO_RESOURCE_ID_MISSING")
    macro_sources = set(macro["resource_id"].astype(str))
    for source in _REQUIRED_MACRO_SOURCES:
        if source not in macro_sources:
            raise RatesCreditFeatureSmokeError(f"FED_MACRO_SOURCE_MISSING:{source}")

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    panels = {
        "rates": normalize_treasury_curve_panel(fed, sessions=sessions),
        "credit": normalize_credit_spread_panel(fed, sessions=sessions),
        "spf_real_rate": normalize_spf_real_rate_panel(raw["D_SPF"], sessions=sessions),
        "cp": normalize_commercial_paper_panel(macro, sessions=sessions),
        "bank": normalize_bank_credit_panel(macro, sessions=sessions),
        "money": normalize_money_reserves_panel(macro, sessions=sessions),
        "consumer": normalize_consumer_credit_panel(macro, sessions=sessions),
        "vol": normalize_cboe_vol_bundle_panel(raw["D_CBOE_VOL"], sessions=sessions),
    }
    _assert_no_fed_sentinel(panels)

    outputs = dict(evaluate_rates_credit_family_batch(market, panels))
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
        evaluator=lambda lane_id, configuration: evaluate_rates_credit_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_rates_credit_configuration,
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
        "scope": "rates_credit_money_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": 10,
        "physical_source_rows": {dataset: int(len(frame)) for dataset, frame in raw.items()},
        "source_sha256": source_hashes,
        "fed_missing_sentinel": _FED_MISSING_SENTINEL,
        "fed_missing_sentinel_removed": True,
        "h3_h6_h8_release_policy": "official_lag_plus_next_spy_session",
        "g19_release_policy": "second_month_conservative_day_plus_next_spy_session",
        "commercial_paper_release_policy": "official_lag_plus_next_spy_session",
        "spf_release_policy": "quarter_end_plus_next_spy_session",
        "row_release_causality_valid": True,
        "historical_revision_pit_exact": False,
        "source_vintage_status": "current_download_not_historical_vintage",
        "source_vintage_warning": (
            "Federal Reserve downloadable histories may revise past values; "
            "final robustness must pass both with and without F181-F190."
        ),
        "f182_fidelity": "constant_maturity_algebra_proxy_not_tradable_forward",
        "f183_fidelity": "official_spf_expected_real_rate_proxy",
        "f185_component_first_available_at": {
            column: _first_available(panels["cp"], column)
            for column in (
                "cp_outstanding",
                "aa_nonfinancial_90d",
                "a2p2_nonfinancial_90d",
                "aa_financial_90d",
                "issuance_amount",
            )
        },
        "f185_default": "outstanding_contraction_full_history",
        "f187_fidelity": "money_and_credit_ratio_proxy_not_income_velocity",
        "f188_fidelity": "consumer_credit_composition_proxy_not_delinquency",
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": [list(group) for group in audit.exact_duplicate_groups],
        "near_duplicate_pairs": [list(pair) for pair in audit.near_duplicate_pairs],
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": "physical_causal_tail_2003_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "rates_credit_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F181_F190.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "RatesCreditFeatureSmokeError",
    "build_rates_credit_feature_smoke",
]

"""Train-only GitHub smoke for executable SP500 lanes F221-F230."""

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
    normalize_federal_debt_panel,
    normalize_fomc_decision_panel,
    normalize_fomc_publication_panels,
    normalize_monetary_liquidity_panel,
    normalize_policy_rate_panel,
    normalize_spy_decision_panel,
    normalize_tic_foreign_flow_panel,
    normalize_treasury_auction_results_panel,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame
from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)
from aurora.infra.sp500_megarun.policy_treasury_feature_engine import (
    evaluate_policy_treasury_family_batch,
    evaluate_policy_treasury_lane,
)


class PolicyTreasuryFeatureSmokeError(ValueError):
    """Raised when F221-F230 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(221, 231))
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PARAMETER_AUDIT_START = pd.Timestamp("1998-01-01")
_DATASETS = (
    "D_SPY",
    "D_CALENDAR",
    "D_FOMC_PUBLIC",
    "D_FED_H15_H10",
    "D_TREASURY_AUCTIONS",
    "D_TREASURY_FISCAL",
    "D_TIC",
    "D_FED_H3_H6_H8_G19_CP",
)
_FOMC_KINDS = ("meeting", "statement", "minutes_release")
_TIC_RESOURCES = ("tic_treasury_sector", "tic_equity_sector")
_MONETARY_SERIES = ("RESMO14A_N.WW", "RESTR14A_N.WW", "M2.WM")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_values(
    frame: pd.DataFrame,
    *,
    dataset_id: str,
    column: str,
    required: tuple[str, ...],
) -> None:
    if column not in frame:
        raise PolicyTreasuryFeatureSmokeError(
            f"PHYSICAL_SOURCE_COLUMN_MISSING:{dataset_id}:{column}"
        )
    present = set(frame[column].dropna().astype(str))
    missing = [value for value in required if value not in present]
    if missing:
        raise PolicyTreasuryFeatureSmokeError(
            f"PHYSICAL_SOURCE_VALUE_MISSING:{dataset_id}:{column}:{','.join(missing)}"
        )


def _reject_unfrozen_fomc_derivatives(frame: pd.DataFrame) -> None:
    forbidden = [
        column
        for column in frame.columns
        if any(
            token in str(column).lower()
            for token in ("tone", "sentiment", "text_score")
        )
    ]
    if forbidden:
        raise PolicyTreasuryFeatureSmokeError(
            f"UNFROZEN_FOMC_TEXT_DERIVATIVE:{','.join(sorted(forbidden))}"
        )


def _first_available(panel: pd.DataFrame, column: str) -> str | None:
    values = pd.to_numeric(panel[column], errors="coerce")
    valid = values.notna()
    if not valid.any():
        return None
    return pd.to_datetime(panel.loc[valid, "available_at"]).min().date().isoformat()


def _repair_policy_treasury_configuration(
    lane_id: str,
    parameter: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    window_statistics = {
        "F222": "statement_gap_zscore",
        "F223": "publication_lag_zscore",
        "F224": "joint_irregularity",
        "F226": "demand_yield_balance",
        "F227": "refinancing_pressure",
        "F228": "debt_growth_zscore",
    }
    if lane_id in window_statistics and parameter == "window":
        configuration["statistic"] = window_statistics[lane_id]
        configuration["normalization"] = "raw"
    elif parameter == "window" and lane_id == "F230":
        configuration["normalization"] = "raw"
    elif parameter == "window":
        configuration["normalization"] = "rolling_zscore"
    lag_statistics = {
        "F221": "decision_rate_change",
        "F222": "statement_gap_change",
        "F223": "publication_lag_change",
        "F225": "offer_growth",
        "F226": "yield_change",
        "F228": "debt_growth",
    }
    if lane_id in lag_statistics and parameter == "change_lag":
        configuration["statistic"] = lag_statistics[lane_id]
        configuration["normalization"] = "raw"
    elif parameter == "change_lag" and lane_id == "F230":
        configuration["normalization"] = "raw"
    elif parameter == "change_lag":
        configuration["normalization"] = "change"
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
        raise PolicyTreasuryFeatureSmokeError("PARAMETER_AUDIT_2010_MISSING")
    audit_panels: dict[str, pd.DataFrame] = {}
    for resource, panel in panels.items():
        dates = pd.to_datetime(panel["date"], errors="raise")
        bounded = panel.loc[
            dates.between(_PARAMETER_AUDIT_START, _TRAIN_END)
        ].reset_index(drop=True)
        if bounded.empty:
            raise PolicyTreasuryFeatureSmokeError(
                f"PARAMETER_AUDIT_PANEL_EMPTY:{resource}"
            )
        audit_panels[resource] = bounded
    return audit_market, audit_panels


def build_policy_treasury_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute and audit F221-F230 without mounting later partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise PolicyTreasuryFeatureSmokeError("TRAIN_PARTITION_REQUIRED")

    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise PolicyTreasuryFeatureSmokeError(
                f"TRAIN_DATASET_MISSING:{dataset}"
            )
        raw[dataset] = pd.read_parquet(target)
        source_hashes[dataset] = _sha256(target)
        if "date" not in raw[dataset] or raw[dataset].empty:
            raise PolicyTreasuryFeatureSmokeError(
                f"EMPTY_PHYSICAL_DATASET:{dataset}"
            )
        dates = pd.to_datetime(raw[dataset]["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise PolicyTreasuryFeatureSmokeError(
                f"NON_TRAIN_SOURCE_ROW:{dataset}"
            )

    _reject_unfrozen_fomc_derivatives(raw["D_FOMC_PUBLIC"])
    _require_values(
        raw["D_FOMC_PUBLIC"],
        dataset_id="D_FOMC_PUBLIC",
        column="document_kind",
        required=_FOMC_KINDS,
    )
    _require_values(
        raw["D_FED_H15_H10"],
        dataset_id="D_FED_H15_H10",
        column="series_id",
        required=("RIFSPFF_N.B",),
    )
    _require_values(
        raw["D_TIC"],
        dataset_id="D_TIC",
        column="resource_id",
        required=_TIC_RESOURCES,
    )
    _require_values(
        raw["D_FED_H3_H6_H8_G19_CP"],
        dataset_id="D_FED_H3_H6_H8_G19_CP",
        column="series_id",
        required=_MONETARY_SERIES,
    )

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    publications = normalize_fomc_publication_panels(
        raw["D_FOMC_PUBLIC"], sessions=sessions
    )
    panels = {
        "decisions": normalize_fomc_decision_panel(
            raw["D_FOMC_PUBLIC"], sessions=sessions
        ),
        "policy_rate": normalize_policy_rate_panel(
            raw["D_FED_H15_H10"], sessions=sessions
        ),
        "statements": publications["statements"],
        "minutes": publications["minutes"],
        "auctions": normalize_treasury_auction_results_panel(
            raw["D_TREASURY_AUCTIONS"], sessions=sessions
        ),
        "debt": normalize_federal_debt_panel(
            raw["D_TREASURY_FISCAL"], sessions=sessions
        ),
        "tic": normalize_tic_foreign_flow_panel(raw["D_TIC"], sessions=sessions),
        "monetary": normalize_monetary_liquidity_panel(
            raw["D_FED_H3_H6_H8_G19_CP"], sessions=sessions
        ),
    }
    outputs = dict(evaluate_policy_treasury_family_batch(market, panels))
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
        evaluator=lambda lane_id, configuration: evaluate_policy_treasury_lane(
            lane_id,
            audit_market,
            audit_panels,
            configuration,
        ),
        expected_years=(2010,),
        repair=_repair_policy_treasury_configuration,
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
    full_yearly_coverage = all(
        item.yearly_non_null_fraction
        and min(item.yearly_non_null_fraction.values()) == 1.0
        for item in audit.coverage
    )
    ready = bool(
        audit.ready
        and parameter_audit["ready"]
        and len(outputs) == len(_LANES)
        and not exact_duplicates
        and not near_duplicates
        and full_yearly_coverage
    )
    report = {
        "schema_version": 1,
        "ready": ready,
        "scope": "policy_treasury_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": len(outputs),
        "physical_source_rows": {
            dataset: int(len(frame)) for dataset, frame in raw.items()
        },
        "source_sha256": source_hashes,
        "row_release_causality_valid": True,
        "fomc_publication_policy": "public_document_date_plus_next_spy_session",
        "fomc_text_available": False,
        "fomc_tone_claimed": False,
        "treasury_auction_policy": "record_issue_date_plus_next_spy_session",
        "treasury_net_cash_claimed": False,
        "federal_debt_policy": "record_date_plus_next_spy_session",
        "tic_release_policy": "second_following_month_tenth_spy_session",
        "tic_historical_revision_pit_exact": False,
        "f221_policy_rate_first_available_at": _first_available(
            panels["policy_rate"], "effective_fed_funds"
        ),
        "f225_auction_first_available_at": _first_available(
            panels["auctions"], "offering_amount"
        ),
        "source_warning": (
            "D_FOMC_PUBLIC contains metadata rather than document text, so F222-F224 "
            "measure publication timing only. Treasury net cash is not claimed. Current "
            "downloadable TIC histories do not recreate historical vintages."
        ),
        "search_start": _SEARCH_START.date().isoformat(),
        "train_end": _TRAIN_END.date().isoformat(),
        "maximum_feature_date": maximum.date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "empty_lanes": list(audit.empty_lanes),
        "exact_duplicate_groups": exact_duplicates,
        "near_duplicate_pairs": near_duplicates,
        "full_yearly_coverage": full_yearly_coverage,
        "coverage": [asdict(item) for item in audit.coverage],
        "artifacts": artifacts,
        "parameter_choice_audit_scope": "physical_causal_tail_1998_2010",
        "parameter_choice_audit": parameter_audit,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "policy_treasury_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "parameter_choice_audit_F221_F230.json").write_text(
        json.dumps(parameter_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "PolicyTreasuryFeatureSmokeError",
    "build_policy_treasury_feature_smoke",
]

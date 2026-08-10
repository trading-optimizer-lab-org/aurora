"""Train-only GitHub smoke for executable SP500 lanes F201-F210."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from aurora.infra.sp500_megarun.feature_audit import audit_feature_outputs
from aurora.infra.sp500_megarun.feature_input_normalizers import (
    normalize_revised_z1_financial_accounts_panel,
    normalize_spy_decision_panel,
    normalize_tic_foreign_flow_panel,
)
from aurora.infra.sp500_megarun.financial_accounts_feature_engine import (
    evaluate_financial_accounts_family_batch,
)
from aurora.infra.sp500_megarun.materializer import parquet_safe_frame


class FinancialAccountsFeatureSmokeError(ValueError):
    """Raised when F201-F210 are not bound to physical train data."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_SEARCH_START = pd.Timestamp("1998-01-01")
_TRAIN_END = pd.Timestamp("2010-12-31")
_LANES = tuple(f"F{index:03d}" for index in range(201, 211))
_DATASETS = ("D_SPY", "D_CALENDAR", "D_Z1", "D_TIC")
_REQUIRED_Z1_SERIES: Mapping[str, tuple[str, ...]] = {
    "household_equity": ("LM153064105.Q", "FL153064105.Q"),
    "household_financial_assets": ("FL154090005.Q",),
    "household_liabilities": ("FL154190005.Q",),
    "household_checkable": ("FL153020005.Q",),
    "household_time_deposits": ("FL153030005.Q",),
    "household_mmf": ("FL153034005.Q",),
    "corporate_financial_assets": ("FL104090005.Q",),
    "corporate_liabilities": ("FL104190005.Q",),
    "corporate_checkable": ("FL103020000.Q",),
    "corporate_time_deposits": ("FL103030003.Q",),
    "corporate_mmf": ("FL103034000.Q",),
    "corporate_debt": ("FL104122005.Q",),
    "corporate_net_issuance": ("FA103164105.Q",),
    "mutual_fund_total_assets": ("LM654090000.Q", "FL654090000.Q"),
    "mutual_fund_equity": ("LM653064100.Q", "FL653064100.Q"),
    "mutual_fund_flow": ("FA654090000.Q", "FU654090000.Q"),
    "etf_total_assets": ("LM564090005.Q", "FL564090005.Q"),
    "etf_equity": ("LM563064100.Q", "FL563064100.Q"),
    "etf_flow": ("FA564090005.Q", "FU564090005.Q"),
    "mmf_total_assets": ("FL634090005.Q",),
    "mmf_flow": ("FA634090005.Q", "FU634090005.Q"),
    "mmf_treasury": ("FL633061105.Q",),
    "mmf_commercial_paper": ("FL633069175.Q",),
    "broker_total_assets": ("FL664090005.Q",),
    "broker_liabilities": ("FL664190005.Q",),
    "broker_repo_assets": ("FL662051003.Q",),
    "broker_repo_liabilities": ("FL662151003.Q",),
    "foreign_treasury_purchases": ("FA263061105.Q",),
    "foreign_bond_purchases": ("FA263063005.Q",),
    "foreign_equity_purchases": ("FA263064105.Q",),
    "foreign_mutual_fund_purchases": ("FA263064203.Q",),
}
_REQUIRED_TIC_RESOURCES = ("tic_treasury_sector", "tic_equity_sector")


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
        raise FinancialAccountsFeatureSmokeError(
            f"PHYSICAL_SOURCE_COLUMN_MISSING:{dataset_id}:{column}"
        )
    present = set(frame[column].dropna().astype(str))
    missing = [value for value in required if value not in present]
    if missing:
        raise FinancialAccountsFeatureSmokeError(
            f"PHYSICAL_SOURCE_VALUE_MISSING:{dataset_id}:{column}:{','.join(missing)}"
        )


def _resolve_z1_series(frame: pd.DataFrame) -> dict[str, str]:
    if "series_id" not in frame:
        raise FinancialAccountsFeatureSmokeError(
            "PHYSICAL_SOURCE_COLUMN_MISSING:D_Z1:series_id"
        )
    present = set(frame["series_id"].dropna().astype(str))
    selected = {
        name: next((series_id for series_id in candidates if series_id in present), "")
        for name, candidates in _REQUIRED_Z1_SERIES.items()
    }
    missing = [name for name, series_id in selected.items() if not series_id]
    if missing:
        raise FinancialAccountsFeatureSmokeError(
            f"PHYSICAL_Z1_SIGNAL_MISSING:{','.join(missing)}"
        )
    return selected


def _first_available(panel: pd.DataFrame, column: str) -> str | None:
    values = pd.to_numeric(panel[column], errors="coerce")
    valid = values.notna()
    if not valid.any():
        return None
    return pd.to_datetime(panel.loc[valid, "available_at"]).min().date().isoformat()


def build_financial_accounts_feature_smoke(
    train_snapshot: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Execute and audit F201-F210 without mounting later partitions."""

    snapshot = Path(train_snapshot)
    if snapshot.name != _TRAIN_PARTITION:
        raise FinancialAccountsFeatureSmokeError("TRAIN_PARTITION_REQUIRED")

    raw: dict[str, pd.DataFrame] = {}
    source_hashes: dict[str, str] = {}
    for dataset in _DATASETS:
        target = snapshot / f"{dataset}.parquet"
        if not target.is_file():
            raise FinancialAccountsFeatureSmokeError(f"TRAIN_DATASET_MISSING:{dataset}")
        raw[dataset] = pd.read_parquet(target)
        source_hashes[dataset] = _sha256(target)
        if "date" not in raw[dataset] or raw[dataset].empty:
            raise FinancialAccountsFeatureSmokeError(f"EMPTY_PHYSICAL_DATASET:{dataset}")
        dates = pd.to_datetime(raw[dataset]["date"], errors="coerce")
        if dates.isna().any() or dates.gt(_TRAIN_END).any():
            raise FinancialAccountsFeatureSmokeError(f"NON_TRAIN_SOURCE_ROW:{dataset}")

    selected_z1_series = _resolve_z1_series(raw["D_Z1"])
    _require_values(
        raw["D_TIC"],
        dataset_id="D_TIC",
        column="resource_id",
        required=_REQUIRED_TIC_RESOURCES,
    )

    sessions = (
        pd.DatetimeIndex(pd.to_datetime(raw["D_SPY"]["date"], errors="raise"))
        .normalize()
        .unique()
        .sort_values()
    )
    sessions = sessions[sessions <= _TRAIN_END]
    market = normalize_spy_decision_panel(raw["D_SPY"], sessions=sessions)
    financial = normalize_revised_z1_financial_accounts_panel(
        raw["D_Z1"], sessions=sessions
    )
    tic = normalize_tic_foreign_flow_panel(raw["D_TIC"], sessions=sessions)
    outputs = dict(
        evaluate_financial_accounts_family_batch(
            market,
            {"financial_accounts": financial, "tic": tic},
        )
    )
    audit = audit_feature_outputs(
        outputs,
        expected_lane_ids=_LANES,
        search_start=_SEARCH_START,
        search_end=_TRAIN_END,
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
        and len(outputs) == len(_LANES)
        and not exact_duplicates
        and not near_duplicates
    )
    report = {
        "schema_version": 1,
        "ready": ready,
        "scope": "financial_accounts_feature_smoke_train_only",
        "executable_lanes": list(_LANES),
        "executable_lane_count": len(outputs),
        "physical_source_rows": {
            dataset: int(len(frame)) for dataset, frame in raw.items()
        },
        "source_sha256": source_hashes,
        "z1_selected_series": selected_z1_series,
        "row_release_causality_valid": True,
        "z1_release_policy": "observation_plus_13_month_revision_guard",
        "z1_historical_revision_pit_exact": False,
        "tic_release_policy": "second_following_month_tenth_spy_session",
        "tic_historical_revision_pit_exact": False,
        "f206_etf_first_available_at": _first_available(financial, "etf_total_assets"),
        "source_vintage_warning": (
            "The current downloadable Z.1 and TIC histories can include later revisions. "
            "The frozen release guards prevent future rows but do not recreate old vintages."
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
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "financial_accounts_feature_smoke_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "FinancialAccountsFeatureSmokeError",
    "build_financial_accounts_feature_smoke",
]

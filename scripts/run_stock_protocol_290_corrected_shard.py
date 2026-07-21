"""Run one corrected independent-opportunity shard for the original 10 x 29 grid."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.stock_protocol import independent_opportunity_executor
from aurora.research.stock_protocol.campaign import _candidates_for_spec
from aurora.research.stock_protocol.entries import apply_entry_rule
from aurora.research.stock_protocol.event_study_290_manifest import (
    COMBINATION_MANIFEST_NAME,
    EXPECTED_COMBINATION_COUNT,
    EXPECTED_ENTRY_SPEC_COUNT,
    EXPECTED_EXIT_SPEC_COUNT,
)
from aurora.research.stock_protocol.locked_access import activate_locked_data_access
from aurora.research.stock_protocol.opportunity_audit import symbol_metadata_frame
from scripts.run_stock_protocol_exact_oos import (
    _locked_shards,
    _manifest_authorization,
    _period_frames,
)


PERIODS: dict[str, dict[str, object]] = {
    "A": {
        "entry_start": "2008-01-01",
        "entry_end": "2015-12-31",
        "load_start": "2006-01-01",
        "load_end": "2020-12-31",
        "include_locked": False,
    },
    "B": {
        "entry_start": "2016-01-01",
        "entry_end": "2020-12-31",
        "load_start": "2014-01-01",
        "load_end": "2026-07-17",
        "include_locked": True,
    },
    "C": {
        "entry_start": "2021-01-01",
        "entry_end": "2026-07-17",
        "load_start": "2019-01-01",
        "load_end": "2026-07-17",
        "include_locked": True,
    },
}

OPPORTUNITIES_STEM = "corrected_290_opportunities"
COVERAGE_STEM = "corrected_290_entry_coverage"
RECONCILIATION_STEM = "corrected_290_reconciliation"
AUDIT_NAME = "corrected_290_shard_audit.json"
DEFAULT_FROZEN_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "frozen_stock_protocol_exact_oos"
    / "frozen_oos_strategy_manifest.json"
)
LEDGER_STATUSES = {"completed", "right_censored", "failed_due_to_data"}
DATASET_CUTOFF = independent_opportunity_executor.DATASET_CUTOFF
MAX_HOLDING_SESSIONS = independent_opportunity_executor.MAX_HOLDING_SESSIONS
HASH_COLUMNS = ("dataset_hash", "policy_hash", "source_snapshot_sha256")
FX_COLUMNS = (
    "fx_entry_date",
    "fx_entry_rate_usd_per_local",
    "fx_exit_date",
    "fx_exit_rate_usd_per_local",
    "fx_dividend_dates_used",
    "dividend_value_usd_per_share",
    "entry_value_usd_per_share",
    "exit_value_usd_per_share",
    "return_usd",
    "fx_return_contribution",
)
COST_LEVELS_BPS_PER_SIDE = (0, 5, 10, 25, 50, 100, 200)
ENTRY_FEATURE_SCHEMA = (
    "date",
    "symbol",
    "adj_close",
    "adj_high",
    "adj_low",
    "mom_12_1",
    "mom_6_1",
    "vol_12_1",
    "h52",
    "information_discreteness",
    "price_score",
    "rvol50",
    "atr20",
    *(f"breakout_{window}" for window in (20, 50, 100, 150, 200, 252)),
    *(f"breakout_level_{window}" for window in (20, 50, 100, 150, 200, 252)),
    *(f"consolidation_{window}" for window in (20, 40, 60)),
    *(f"sma_{window}" for window in (150, 200, 250)),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _write_frame_pair(root: Path, stem: str, frame: pd.DataFrame) -> dict[str, str]:
    parquet = root / f"{stem}.parquet"
    csv_gzip = root / f"{stem}.csv.gz"
    frame.to_parquet(parquet, index=False)
    frame.to_csv(csv_gzip, index=False, compression="gzip")
    return {
        "parquet": str(parquet),
        "parquet_sha256": _sha256(parquet),
        "csv_gzip": str(csv_gzip),
        "csv_gzip_sha256": _sha256(csv_gzip),
    }


def _resolve_pack_root(root: Path) -> Path:
    candidates = [Path(root), Path(root) / "pre2021_full_daily_pack"]
    candidates.extend(path.parent for path in Path(root).rglob("shard-000.parquet"))
    for candidate in candidates:
        if (
            (candidate / "shard-000.parquet").is_file()
            and (candidate / "shard-031.parquet").is_file()
        ):
            return candidate
    raise FileNotFoundError("could not resolve the immutable 32-shard price pack")


def _frozen_binding(
    path: Path | None,
    manifest_sha256: str | None,
    implementation_commit: str | None,
) -> tuple[Path, str, str]:
    resolved = DEFAULT_FROZEN_MANIFEST if path is None else Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    actual_sha256 = _sha256(resolved)
    if manifest_sha256 is not None and manifest_sha256.lower() != actual_sha256:
        raise ValueError("frozen manifest sha256 argument does not match its bytes")
    actual_commit = str(payload.get("implementation_commit", ""))
    if not actual_commit:
        raise ValueError("frozen manifest has no implementation_commit")
    if implementation_commit is not None and implementation_commit != actual_commit:
        raise ValueError("implementation commit argument differs from frozen manifest")
    return resolved, actual_sha256, actual_commit


def _validate_manifest_contract(manifest: pd.DataFrame) -> None:
    if len(manifest) != EXPECTED_COMBINATION_COUNT:
        raise ValueError("290 manifest does not contain exactly 290 combinations")
    combination_ids = manifest["combination_id"].astype(str).str.strip()
    if combination_ids.eq("").any() or combination_ids.nunique() != EXPECTED_COMBINATION_COUNT:
        raise ValueError("290 manifest must contain exactly 290 unique combination IDs")
    for column in HASH_COLUMNS:
        values = manifest[column].astype(str).str.strip().str.lower()
        valid = values.str.fullmatch(r"[0-9a-f]{64}")
        if not valid.all() or values.nunique() != 1:
            raise ValueError(f"290 manifest {column} must be one uniform sha256")


def load_corrected_entry_rows(
    manifest_root: Path,
    entry_index: int,
) -> tuple[Path, pd.DataFrame, dict[str, Any]]:
    """Load one artifact-derived entry and its exact 29 exit mappings."""

    if entry_index not in range(EXPECTED_ENTRY_SPEC_COUNT):
        raise ValueError("entry_index must be between 0 and 9")
    path = Path(manifest_root) / COMBINATION_MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {
        "combination_id",
        "entry_spec_id",
        "exit_spec_id",
        "entry_spec_json",
        "exit_spec_json",
        "corrected_track_applicability",
        "corrected_track_reason",
        "dataset_hash",
        "policy_hash",
        "source_snapshot_sha256",
    }
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"290 manifest is missing columns: {sorted(missing)}")
    _validate_manifest_contract(manifest)
    entry_ids = manifest["entry_spec_id"].drop_duplicates().tolist()
    if len(entry_ids) != EXPECTED_ENTRY_SPEC_COUNT:
        raise ValueError("290 manifest does not contain exactly 10 entry specs")
    rows = manifest.loc[manifest["entry_spec_id"].eq(entry_ids[entry_index])].copy()
    if (
        len(rows) != EXPECTED_EXIT_SPEC_COUNT
        or rows["exit_spec_id"].nunique() != EXPECTED_EXIT_SPEC_COUNT
    ):
        raise ValueError("corrected entry shard must contain 29 distinct exits")
    entry_json = rows["entry_spec_json"].drop_duplicates().tolist()
    if len(entry_json) != 1:
        raise ValueError("entry shard contains multiple entry specifications")
    entry_spec = json.loads(entry_json[0])
    if not isinstance(entry_spec, dict):
        raise ValueError("entry_spec_json must contain an object")
    return path, rows.reset_index(drop=True), entry_spec


def _normalise_dates(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_datetime(frame[column], errors="raise")
    if values.dt.tz is not None:
        values = values.dt.tz_convert(None)
    return values.dt.normalize()


def complete_entry_feature_schema(
    panel,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Restore every causal entry feature discarded by the OOS loader."""

    result = features.copy()
    required_base = {
        "date",
        "symbol",
        "adj_close",
        "adj_high",
        "adj_low",
        "mom_12_1",
        "mom_6_1",
        "vol_12_1",
        "h52",
        "information_discreteness",
        "price_score",
        "rvol50",
        "atr20",
    }
    missing_base = required_base - set(result.columns)
    if missing_base:
        raise ValueError(
            f"period feature frame lacks required base schema: {sorted(missing_base)}"
        )
    result["date"] = _normalise_dates(result, "date")
    result = result.sort_values(["symbol", "date"], kind="stable").reset_index(
        drop=True
    )
    if result.duplicated(["date", "symbol"]).any():
        raise ValueError("period feature frame contains duplicate symbol-dates")
    grouped = result.groupby("symbol", group_keys=False, sort=False)
    high_grouped = result.groupby("symbol", sort=False)["adj_high"]
    for window in (20, 50, 100, 150, 200, 252):
        level_column = f"breakout_level_{window}"
        breakout_column = f"breakout_{window}"
        if level_column not in result:
            result[level_column] = high_grouped.transform(
                lambda values, w=window: values.shift(1).rolling(
                    w, min_periods=max(10, w // 2)
                ).max()
            )
        if breakout_column not in result:
            result[breakout_column] = result["adj_close"].gt(result[level_column])
    for window in (20, 40, 60):
        column = f"consolidation_{window}"
        if column in result:
            continue
        prior_high = grouped["adj_high"].transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=w).max()
        )
        prior_low = grouped["adj_low"].transform(
            lambda values, w=window: values.shift(1).rolling(w, min_periods=w).min()
        )
        prior_close = grouped["adj_close"].shift(1)
        result[column] = prior_high.sub(prior_low).div(
            prior_close.replace(0.0, np.nan)
        )
    for window in (150, 200, 250):
        column = f"sma_{window}"
        if column not in result:
            result[column] = grouped["adj_close"].transform(
                lambda values, w=window: values.shift(1).rolling(
                    w, min_periods=max(20, w // 2)
                ).mean()
            )
    missing = set(ENTRY_FEATURE_SCHEMA) - set(result.columns)
    if missing:
        raise ValueError(f"entry feature schema is incomplete: {sorted(missing)}")
    return result


def _attach_signal_features(
    events: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    if events.empty:
        return events
    component_columns = [
        "adj_close",
        "mom_12_1",
        "mom_6_1",
        "h52",
        "rvol50",
        "atr20",
        "vol_12_1",
        *(f"breakout_{window}" for window in (20, 50, 100, 150, 200, 252)),
        *(f"breakout_level_{window}" for window in (20, 50, 100, 150, 200, 252)),
        *(f"consolidation_{window}" for window in (20, 40, 60)),
        *(f"sma_{window}" for window in (150, 200, 250)),
    ]
    missing = [column for column in component_columns if column not in events]
    if missing:
        lookup = features.reindex(columns=["date", "symbol", *missing]).rename(
            columns={"date": "signal_date"}
        )
        events = events.merge(
            lookup,
            on=["signal_date", "symbol"],
            how="left",
            validate="many_to_one",
        )
    events["signal_score"] = pd.to_numeric(events.get("score"), errors="coerce")
    events["momentum_12_1"] = pd.to_numeric(events["mom_12_1"], errors="coerce")
    events["momentum_6_1"] = pd.to_numeric(events["mom_6_1"], errors="coerce")
    events["high_52"] = pd.to_numeric(events["h52"], errors="coerce")
    return events


def _next_open_dates(events: pd.DataFrame, panel: pd.DataFrame) -> pd.Series:
    """Resolve entry dates without running any exit or portfolio logic."""

    prices = panel[["date", "symbol"]].copy()
    prices["date"] = _normalise_dates(prices, "date")
    groups = {
        str(symbol): pd.DatetimeIndex(group["date"].drop_duplicates().sort_values())
        for symbol, group in prices.groupby("symbol", sort=False)
    }
    resolved: list[pd.Timestamp | None] = []
    for row in events.itertuples(index=False):
        signal_date = pd.Timestamp(getattr(row, "signal_date")).normalize()
        dates = groups.get(str(getattr(row, "symbol")))
        if dates is None:
            resolved.append(None)
            continue
        location = int(dates.searchsorted(signal_date, side="right"))
        resolved.append(dates[location] if location < len(dates) else pd.NaT)
    return pd.Series(resolved, index=events.index, dtype="datetime64[ns]")


def _wait_sessions(
    symbol: str,
    selection_date: pd.Timestamp,
    signal_date: pd.Timestamp | None,
    feature_dates: dict[str, pd.DatetimeIndex],
    max_wait: int,
) -> int:
    if signal_date is None or pd.isna(signal_date):
        return max_wait
    dates = feature_dates.get(symbol, pd.DatetimeIndex([]))
    return max(0, int(dates.to_series().between(selection_date, signal_date).sum()) - 1)


def build_entry_cohort(
    panel,
    features: pd.DataFrame,
    entry_spec: Mapping[str, Any],
    *,
    period: str,
    authorization,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate selection and entry events once, retaining non-entry coverage."""

    config = PERIODS[period]
    entry_start = pd.Timestamp(str(config["entry_start"]))
    entry_end = pd.Timestamp(str(config["entry_end"]))
    candidates = _candidates_for_spec(panel, entry_spec, features).copy()
    if candidates.empty:
        events = pd.DataFrame(
            columns=[
                "symbol",
                "selection_date",
                "signal_date",
                "available_at",
                "entry_rule",
                "entry_date_resolved",
            ]
        )
        coverage = pd.DataFrame(
            columns=[
                "symbol",
                "selection_date",
                "entry_signal_date",
                "entry_date_resolved",
                "selected",
                "triggered",
                "wait_sessions",
                "waited",
                "waits",
                "entry_in_period",
                "coverage_status",
                "period_assignment_basis",
                "period",
                "entry_spec_id",
            ]
        )
        return candidates, events, coverage
    candidates["signal_date"] = _normalise_dates(candidates, "signal_date")
    candidates = candidates.loc[candidates["signal_date"].le(entry_end)].copy()
    rule = dict(entry_spec["entry"])
    if authorization is None:
        events = apply_entry_rule(candidates, features, rule)
    else:
        events = apply_entry_rule(
            candidates,
            features,
            rule,
            locked_authorization=authorization,
        )
    if events.empty:
        events = pd.DataFrame(
            columns=[
                *candidates.columns,
                "selection_date",
                "entry_rule",
                "entry_date_resolved",
            ]
        )
    if not events.empty:
        events["selection_date"] = _normalise_dates(events, "selection_date")
        events["signal_date"] = _normalise_dates(events, "signal_date")
        events = _attach_signal_features(events, features)
        events["entry_date_resolved"] = _next_open_dates(events, panel.frame)
        entry_events = events.loc[
            events["entry_date_resolved"].between(entry_start, entry_end)
        ].copy()
    else:
        entry_events = events.copy()
        entry_events["entry_date_resolved"] = pd.Series(dtype="datetime64[ns]")

    keys = ["symbol", "selection_date"]
    selected = candidates.rename(columns={"signal_date": "selection_date"}).copy()
    selected["selection_date"] = _normalise_dates(selected, "selection_date")
    selected = selected.drop_duplicates(keys, keep="first")
    event_columns = [
        "symbol",
        "selection_date",
        "signal_date",
        "entry_date_resolved",
        "entry_rule",
    ]
    available_event_columns = [column for column in event_columns if column in events]
    event_lookup = events[available_event_columns].drop_duplicates(keys, keep="first")
    coverage = selected.merge(event_lookup, on=keys, how="left", validate="one_to_one")
    relevant = coverage["selection_date"].between(entry_start, entry_end)
    if "entry_date_resolved" in coverage:
        relevant |= coverage["entry_date_resolved"].between(entry_start, entry_end)
    coverage = coverage.loc[relevant].copy()
    coverage["selected"] = True
    coverage["triggered"] = coverage.get(
        "signal_date_y", coverage.get("signal_date", pd.Series(pd.NaT, index=coverage.index))
    ).notna()
    if "signal_date_y" in coverage:
        coverage["entry_signal_date"] = coverage.pop("signal_date_y")
    else:
        coverage["entry_signal_date"] = coverage.get("signal_date")
    coverage.drop(columns=["signal_date_x"], errors="ignore", inplace=True)
    feature_source = features[["date", "symbol"]].copy()
    feature_source["date"] = _normalise_dates(feature_source, "date")
    feature_dates = {
        str(symbol): pd.DatetimeIndex(group["date"].drop_duplicates().sort_values())
        for symbol, group in feature_source.groupby("symbol", sort=False)
    }
    max_wait = int(rule.get("max_wait_sessions", 21))
    if not entry_events.empty:
        entry_events["wait_sessions"] = [
            _wait_sessions(
                str(row.symbol),
                pd.Timestamp(row.selection_date),
                pd.Timestamp(row.signal_date),
                feature_dates,
                max_wait,
            )
            for row in entry_events.itertuples(index=False)
        ]
        entry_events["waited"] = entry_events["wait_sessions"].gt(0)
        entry_events["waits"] = entry_events["wait_sessions"]
    coverage["wait_sessions"] = [
        _wait_sessions(
            str(row.symbol),
            pd.Timestamp(row.selection_date),
            None if pd.isna(row.entry_signal_date) else pd.Timestamp(row.entry_signal_date),
            feature_dates,
            max_wait,
        )
        for row in coverage.itertuples(index=False)
    ]
    coverage["waited"] = coverage["wait_sessions"].gt(0)
    coverage["waits"] = coverage["wait_sessions"]
    coverage["entry_in_period"] = coverage["entry_date_resolved"].between(
        entry_start, entry_end
    )
    coverage["coverage_status"] = np.where(
        coverage["triggered"], "entry_triggered", "entry_not_triggered"
    )
    coverage["period_assignment_basis"] = np.where(
        coverage["entry_in_period"], "entry_date", "selection_date_no_period_entry"
    )
    coverage["period"] = period
    coverage["entry_spec_id"] = str(entry_spec.get("candidate_id", ""))
    return candidates, entry_events.reset_index(drop=True), coverage.reset_index(drop=True)


def _ranking_keep_frame(
    panel,
    features: pd.DataFrame,
    entry_spec: Mapping[str, Any],
    exit_rule: Mapping[str, Any],
) -> pd.DataFrame | None:
    if exit_rule.get("kind") != "ranking_hysteresis":
        return None
    keep_spec = dict(entry_spec)
    keep_spec["selection"] = {
        "kind": "top_percent",
        "value": float(exit_rule["keep_percentile"]),
    }
    keep = _candidates_for_spec(panel, keep_spec, features).copy()
    if not keep.empty:
        keep["available_at"] = keep["signal_date"]
    return keep


def _economic_path_values(
    row: Mapping[str, Any],
    prepared_group: tuple[pd.DataFrame, pd.DatetimeIndex] | None,
) -> dict[str, object]:
    """Value one share through splits and dividends on the local price basis."""

    entry_date = pd.to_datetime(row.get("entry_date"), errors="coerce")
    entry_price = pd.to_numeric(pd.Series([row.get("entry_price")]), errors="coerce").iloc[0]
    exit_date = pd.to_datetime(row.get("exit_date"), errors="coerce")
    has_exit = not pd.isna(exit_date)
    valuation_date = exit_date if has_exit else pd.to_datetime(
        row.get("mtm_date"), errors="coerce"
    )
    valuation_price = pd.to_numeric(
        pd.Series([row.get("exit_price") if has_exit else row.get("mtm_price")]),
        errors="coerce",
    ).iloc[0]
    empty = {
        "entry_value_local_per_initial_share": np.nan,
        "exit_value_local_per_initial_share": np.nan,
        "price_return_local": np.nan,
        "total_return_local": np.nan,
        "dividends_local": np.nan,
        "dividend_payments_local_json": "[]",
        "dividend_event_count": 0,
        "split_event_count": 0,
        "cumulative_split_factor": np.nan,
        "entry_day_volume": np.nan,
        "entry_day_dollar_volume_local": np.nan,
        "entry_adv20_local": np.nan,
    }
    if (
        prepared_group is None
        or pd.isna(entry_date)
        or pd.isna(valuation_date)
        or pd.isna(entry_price)
    ):
        return empty
    group, dates = prepared_group
    entry_date = pd.Timestamp(entry_date).normalize()
    valuation_date = min(pd.Timestamp(valuation_date).normalize(), DATASET_CUTOFF)
    entry_index = int(dates.searchsorted(entry_date, side="left"))
    path_end = int(dates.searchsorted(valuation_date, side="right"))
    if (
        entry_index >= len(group)
        or dates[entry_index] != entry_date
        or path_end <= entry_index
    ):
        return empty
    path = group.iloc[entry_index:path_end]
    valuation_bar = path.iloc[-1]
    if pd.Timestamp(valuation_bar["date"]).normalize() != valuation_date:
        return empty
    prior = group.iloc[max(0, entry_index - 20) : entry_index]
    prior_notional = pd.to_numeric(prior["close"], errors="coerce") * pd.to_numeric(
        prior["volume"], errors="coerce"
    )
    shares = 1.0
    dividends = 0.0
    split_events = 0
    dividend_payments: list[dict[str, object]] = []
    for bar in path.itertuples(index=False):
        bar_date = pd.Timestamp(bar.date).normalize()
        split = pd.to_numeric(
            pd.Series([getattr(bar, "stock_splits", 0.0)]), errors="coerce"
        ).iloc[0]
        if bar_date > entry_date and split > 0 and not np.isclose(split, 1.0):
            shares *= float(split)
            split_events += 1
        dividend = pd.to_numeric(
            pd.Series([getattr(bar, "dividends", 0.0)]), errors="coerce"
        ).iloc[0]
        if (
            bar_date > entry_date
            and np.isfinite(dividend)
            and not np.isclose(dividend, 0.0)
        ):
            cash_local = shares * float(dividend)
            dividends += cash_local
            dividend_payments.append(
                {
                    "date": bar_date.date().isoformat(),
                    "declared_local_per_share": float(dividend),
                    "shares_held": shares,
                    "cash_local_per_initial_share": cash_local,
                }
            )
    entry_bar = group.iloc[entry_index]
    raw_entry_price = pd.to_numeric(
        pd.Series([entry_bar["open"]]), errors="coerce"
    ).iloc[0]
    raw_valuation_close = pd.to_numeric(
        pd.Series([valuation_bar["close"]]), errors="coerce"
    ).iloc[0]
    adjusted_valuation_close = pd.to_numeric(
        pd.Series([valuation_bar.get("adj_close", raw_valuation_close)]),
        errors="coerce",
    ).iloc[0]
    if not np.isfinite(raw_valuation_close) or raw_valuation_close <= 0:
        return empty
    adjustment_factor = adjusted_valuation_close / raw_valuation_close
    if (
        not np.isfinite(raw_entry_price)
        or raw_entry_price <= 0
        or not np.isfinite(adjustment_factor)
        or adjustment_factor <= 0
    ):
        return empty
    raw_valuation_price = float(valuation_price) / float(adjustment_factor)
    economic_exit = raw_valuation_price * shares
    price_return = economic_exit / float(raw_entry_price) - 1.0
    total_return = (economic_exit + dividends) / float(raw_entry_price) - 1.0
    volume = float(pd.to_numeric(pd.Series([entry_bar["volume"]]), errors="coerce").iloc[0])
    return {
        "entry_value_local_per_initial_share": float(raw_entry_price),
        "exit_value_local_per_initial_share": economic_exit,
        "price_return_local": price_return,
        "total_return_local": total_return,
        "dividends_local": dividends,
        "dividend_payments_local_json": json.dumps(
            dividend_payments, ensure_ascii=True, separators=(",", ":")
        ),
        "dividend_event_count": len(dividend_payments),
        "split_event_count": split_events,
        "cumulative_split_factor": shares,
        "entry_day_volume": volume,
        "entry_day_dollar_volume_local": volume * float(raw_entry_price),
        "entry_adv20_local": (
            float(prior_notional.mean()) if prior_notional.notna().any() else np.nan
        ),
    }


def enrich_opportunities(
    opportunities: pd.DataFrame,
    panel_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Attach market, corporate-action, path and liquidity fields without FX guesses."""

    if opportunities.empty:
        result = opportunities.copy()
        empty_columns = {
            "entry_value_local_per_initial_share": "float64",
            "exit_value_local_per_initial_share": "float64",
            "price_return_local": "float64",
            "total_return_local": "float64",
            "dividends_local": "float64",
            "dividend_payments_local_json": "object",
            "dividend_event_count": "int64",
            "split_event_count": "int64",
            "cumulative_split_factor": "float64",
            "entry_day_volume": "float64",
            "entry_day_dollar_volume_local": "float64",
            "entry_adv20_local": "float64",
            "executor_gross_return": "float64",
            "gross_return_basis": "object",
            "country": "object",
            "market": "object",
            "exchange": "object",
            "currency": "object",
            "price_scale_to_currency_unit": "float64",
            "metadata_source": "object",
            "currency_unknown": "bool",
        }
        for column, dtype in empty_columns.items():
            if column not in result:
                result[column] = pd.Series(dtype=dtype)
        for column in FX_COLUMNS:
            result[column] = pd.Series(dtype="float64")
        for column in (
            "fx_merge_status",
            "capital_rejection_reason",
        ):
            result[column] = pd.Series(dtype="object")
        for column in (
            "fx_values_invented",
            "capital_rejected",
            "portfolio_simulated",
            "sizing_applied",
            "overlap_discarded",
            "new_oos_claimed",
            "optimization_performed_on_opened_data",
        ):
            result[column] = pd.Series(dtype="bool")
        return result
    source = panel_frame.copy()
    source["date"] = _normalise_dates(source, "date")
    source = source.sort_values(["symbol", "date"], kind="stable")
    groups: dict[str, tuple[pd.DataFrame, pd.DatetimeIndex]] = {}
    for symbol, group in source.groupby("symbol", sort=False):
        prepared = group.reset_index(drop=True)
        groups[str(symbol)] = (prepared, pd.DatetimeIndex(prepared["date"]))
    path_cache: dict[tuple[object, ...], dict[str, object]] = {}
    path_rows: list[dict[str, object]] = []
    for row in opportunities.to_dict(orient="records"):
        has_exit = not pd.isna(pd.to_datetime(row.get("exit_date"), errors="coerce"))
        cache_key = (
            str(row.get("symbol", "")),
            row.get("entry_date"),
            row.get("entry_price"),
            row.get("exit_date") if has_exit else row.get("mtm_date"),
            row.get("exit_price") if has_exit else row.get("mtm_price"),
        )
        if cache_key not in path_cache:
            path_cache[cache_key] = _economic_path_values(
                row, groups.get(str(row.get("symbol", "")))
            )
        path_rows.append(path_cache[cache_key])
    result = opportunities.copy().reset_index(drop=True)
    economic = pd.DataFrame(path_rows)
    for column in economic:
        result[column] = economic[column]
    result["executor_gross_return"] = pd.to_numeric(result["gross_return"], errors="coerce")
    completed = result["status"].eq("completed")
    local_total_return = pd.to_numeric(result["total_return_local"], errors="coerce")
    result.loc[completed, "gross_return"] = local_total_return.loc[completed]
    metadata = symbol_metadata_frame(result["symbol"])
    result = result.merge(metadata, on="symbol", how="left", validate="many_to_one")
    for column in FX_COLUMNS:
        if column not in result:
            result[column] = np.nan
    usd_return = pd.to_numeric(result["return_usd"], errors="coerce")
    completed_usd = completed & usd_return.notna()
    if (completed & local_total_return.isna() & usd_return.isna()).any():
        raise ValueError("completed opportunities require a total return valuation")
    result.loc[completed_usd, "gross_return"] = usd_return.loc[completed_usd]
    result["gross_return_basis"] = "not_realized"
    result.loc[completed, "gross_return_basis"] = "total_return_local"
    result.loc[completed_usd, "gross_return_basis"] = "total_return_usd"
    if "fx_merge_status" not in result:
        result["fx_merge_status"] = np.where(
            usd_return.notna(),
            "already_enriched",
            "not_available_in_entry_period_shard",
        )
    result["fx_values_invented"] = False
    result["capital_rejected"] = False
    result["capital_rejection_reason"] = ""
    result["portfolio_simulated"] = False
    result["sizing_applied"] = False
    result["overlap_discarded"] = False
    result["new_oos_claimed"] = False
    result["optimization_performed_on_opened_data"] = False
    return result


def complete_ledger_contract(opportunities: pd.DataFrame) -> pd.DataFrame:
    """Materialize mandatory audit, cost, liquidity and FX ledger fields."""

    result = opportunities.copy().reset_index(drop=True)
    mandatory_numeric = (
        "entry_gap",
        "signal_score",
        "mom_12_1",
        "mom_6_1",
        "momentum_12_1",
        "momentum_6_1",
        "h52",
        "high_52",
        "rvol50",
        "atr20",
        "wait_sessions",
        "waits",
        "remaining_sessions_estimate",
        "trajectory_volatility",
        "volatility",
        *(f"breakout_{window}" for window in (20, 50, 100, 150, 200, 252)),
        *(f"breakout_level_{window}" for window in (20, 50, 100, 150, 200, 252)),
    )
    for column in mandatory_numeric:
        if column not in result:
            result[column] = np.nan
    for column in (
        "entry_rule",
        "entry_rule_kind",
        "entry_rule_json",
        "exit_rule",
        "exit_rule_json",
        "component_signals_json",
        "signal_weights_json",
    ):
        if column not in result:
            result[column] = ""
    if "waited" not in result:
        result["waited"] = False
    completed = result.get("status", pd.Series(dtype=str)).eq("completed")
    gross = pd.to_numeric(result.get("gross_return"), errors="coerce")
    result["primary_event_return"] = gross.where(completed)
    result["primary_event_return_basis"] = result.get(
        "gross_return_basis", pd.Series("not_realized", index=result.index)
    )
    result.loc[~completed, "primary_event_return_basis"] = "not_realized"
    result["cost_levels_bps_per_side_json"] = json.dumps(
        list(COST_LEVELS_BPS_PER_SIDE), separators=(",", ":")
    )
    net_payloads: list[str] = []
    for index in result.index:
        row_values: dict[str, float | None] = {}
        for cost in COST_LEVELS_BPS_PER_SIDE:
            value = (
                float(gross.loc[index]) - 2.0 * cost / 10_000.0
                if bool(completed.loc[index]) and np.isfinite(gross.loc[index])
                else None
            )
            row_values[str(cost)] = value
        net_payloads.append(json.dumps(row_values, separators=(",", ":")))
    result["net_returns_by_cost_bps_json"] = net_payloads
    for cost in COST_LEVELS_BPS_PER_SIDE:
        round_trip = 2.0 * cost / 10_000.0
        result[f"round_trip_cost_{cost}bps"] = round_trip
        values = gross.sub(round_trip).where(completed)
        result[f"net_return_{cost}bps"] = values
        result[f"net_return_cost_{cost}_bps_per_side"] = values

    if "financed_in_old_portfolio" not in result:
        result["financed_in_old_portfolio"] = pd.array(
            [pd.NA] * len(result), dtype="boolean"
        )
        result["financed_in_old_portfolio_source"] = (
            "not_available_in_independent_opportunity_protocol"
        )
    else:
        result["financed_in_old_portfolio_source"] = "source_entry_ledger"
    result["liquidity_entry_volume"] = pd.to_numeric(
        result.get("entry_day_volume"), errors="coerce"
    )
    result["liquidity_entry_notional_local"] = pd.to_numeric(
        result.get("entry_day_dollar_volume_local"), errors="coerce"
    )
    result["liquidity_adv20_local"] = pd.to_numeric(
        result.get("entry_adv20_local"), errors="coerce"
    )
    result["liquidity_currency"] = result.get("currency", "unknown")
    result["liquidity_status"] = np.where(
        result["liquidity_adv20_local"].notna(),
        "observed_local_notional",
        "not_available",
    )
    currency = result.get("currency", pd.Series("unknown", index=result.index)).astype(
        str
    )
    result["fx_required"] = ~currency.str.upper().isin({"USD", "UNKNOWN"})
    result["fx_available"] = pd.to_numeric(
        result.get("return_usd"), errors="coerce"
    ).notna()
    result["net_return_basis"] = result["primary_event_return_basis"]
    return result


def reconciliation_by_combination(
    opportunities: pd.DataFrame,
    manifest_rows: pd.DataFrame | None = None,
    *,
    period: str | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    groups = {
        str(combination_id): group
        for combination_id, group in opportunities.groupby("combination_id", sort=False)
    }
    if manifest_rows is None:
        combinations = [
            {
                "combination_id": combination_id,
                "entry_spec_id": str(group.iloc[0]["entry_spec_id"]),
                "exit_spec_id": str(group.iloc[0]["exit_spec_id"]),
                "semantic_applicability": str(
                    group.iloc[0]["semantic_applicability"]
                ),
            }
            for combination_id, group in groups.items()
        ]
    else:
        combinations = [
            {
                "combination_id": str(row["combination_id"]),
                "entry_spec_id": str(row["entry_spec_id"]),
                "exit_spec_id": str(row["exit_spec_id"]),
                "semantic_applicability": str(
                    row["corrected_track_applicability"]
                ),
            }
            for row in manifest_rows.to_dict(orient="records")
        ]
    for combination in combinations:
        combination_id = combination["combination_id"]
        group = groups.get(combination_id, opportunities.iloc[0:0])
        statuses = group["status"].astype(str)
        unsupported = sorted(set(statuses) - LEDGER_STATUSES)
        completed = int(statuses.eq("completed").sum())
        censored = int(statuses.eq("right_censored").sum())
        failed = int(statuses.eq("failed_due_to_data").sum())
        opportunities_count = int(len(group))
        reconciled = not unsupported and opportunities_count == completed + censored + failed
        rows.append(
            {
                "combination_id": combination_id,
                "entry_spec_id": combination["entry_spec_id"],
                "exit_spec_id": combination["exit_spec_id"],
                "period": period if period is not None else str(group.iloc[0]["period"]),
                "semantic_applicability": combination["semantic_applicability"],
                "opportunities": opportunities_count,
                "completed": completed,
                "censored": censored,
                "failed_due_to_data": failed,
                "unsupported_statuses_json": json.dumps(unsupported),
                "reconciled": reconciled,
            }
        )
    result = pd.DataFrame(rows)
    if len(result) and not result["reconciled"].all():
        raise ValueError("corrected opportunity reconciliation failed")
    if manifest_rows is not None and len(result) != len(manifest_rows):
        raise ValueError(
            "corrected shard reconciliation does not contain every requested combination"
        )
    return result


def run_corrected_shard(
    *,
    manifest_root: Path,
    pack_root: Path,
    entry_index: int,
    period: str,
    output_root: Path,
    locked_shards_root: Path | None = None,
    frozen_manifest_path: Path | None = None,
    frozen_manifest_sha256: str | None = None,
    implementation_commit: str | None = None,
    exit_start: int = 0,
    exit_end: int = EXPECTED_EXIT_SPEC_COUNT,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission(
        "stock protocol 290 corrected independent-opportunity shard"
    )
    if period not in PERIODS:
        raise ValueError("period must be A, B or C")
    manifest_path, full_manifest_rows, entry_spec = load_corrected_entry_rows(
        manifest_root, entry_index
    )
    if not 0 <= exit_start < exit_end <= EXPECTED_EXIT_SPEC_COUNT:
        raise ValueError("exit slice must satisfy 0 <= start < end <= 29")
    manifest_rows = full_manifest_rows.iloc[exit_start:exit_end].copy()
    requested_exit_count = len(manifest_rows)
    config = PERIODS[period]
    include_locked = bool(config["include_locked"])
    authorization = None
    locked: dict[int, tuple[Path, dict[str, object]]] = {}
    if include_locked:
        if locked_shards_root is None:
            raise ValueError("period B/C requires locked shards")
        (
            frozen_manifest_path,
            frozen_manifest_sha256,
            implementation_commit,
        ) = _frozen_binding(
            frozen_manifest_path,
            frozen_manifest_sha256,
            implementation_commit,
        )
        authorization = _manifest_authorization(
            frozen_manifest_path,
            frozen_manifest_sha256,
            implementation_commit,
        )
        activate_locked_data_access(
            authorization, end=pd.Timestamp(str(config["load_end"]))
        )
        locked = _locked_shards(
            locked_shards_root,
            manifest_sha256=frozen_manifest_sha256,
            implementation_commit=implementation_commit,
        )
    panel, features = _period_frames(
        pack_root=_resolve_pack_root(Path(pack_root)),
        locked=locked,
        start=str(config["load_start"]),
        end=str(config["load_end"]),
        include_locked=include_locked,
        authorization=authorization,
    )
    features = complete_entry_feature_schema(panel, features)
    panel_dates = pd.to_datetime(panel.frame["date"], errors="raise").dt.normalize()
    if panel_dates.max() > DATASET_CUTOFF:
        raise ValueError("panel exceeds hard cutoff 2026-07-17")
    _, entry_events, coverage = build_entry_cohort(
        panel,
        features,
        entry_spec,
        period=period,
        authorization=authorization,
    )
    entry_spec_id = str(manifest_rows.iloc[0]["entry_spec_id"])
    coverage.insert(0, "entry_index", entry_index)
    coverage["entry_spec_id"] = entry_spec_id
    if not entry_events.empty and not entry_events["entry_date_resolved"].between(
        pd.Timestamp(str(config["entry_start"])),
        pd.Timestamp(str(config["entry_end"])),
    ).all():
        raise ValueError("corrected shard contains an entry outside its period")
    ledgers: list[pd.DataFrame] = []
    prepared_context = (
        independent_opportunity_executor.prepare_opportunity_execution_context(
            panel=panel,
            cutoff=DATASET_CUTOFF,
            locked_authorization=authorization,
        )
    )
    ranking_keep_cache: dict[float, pd.DataFrame | None] = {}
    for manifest_row in manifest_rows.to_dict(orient="records"):
        projection = json.loads(str(manifest_row["exit_spec_json"]))
        exit_rule = dict(projection["exit"])
        ranking_keep = None
        if exit_rule.get("kind") == "ranking_hysteresis":
            keep_percentile = float(exit_rule["keep_percentile"])
            if keep_percentile not in ranking_keep_cache:
                ranking_keep_cache[keep_percentile] = _ranking_keep_frame(
                    panel, features, entry_spec, exit_rule
                )
            ranking_keep = ranking_keep_cache[keep_percentile]
        event_input = entry_events.copy()
        event_input["combination_id"] = str(manifest_row["combination_id"])
        executed = independent_opportunity_executor.execute_independent_opportunities(
            event_input,
            panel,
            exit_rule,
            combination_id=str(manifest_row["combination_id"]),
            ranking_keep=ranking_keep,
            cutoff=DATASET_CUTOFF,
            track="corrected_track",
            locked_authorization=authorization,
            prepared_context=prepared_context,
        )
        if "entry_not_triggered" in set(executed.get("status", pd.Series(dtype=str))):
            raise ValueError("entry_not_triggered belongs in coverage, not opportunity ledger")
        executed["entry_spec_id"] = entry_spec_id
        executed["exit_spec_id"] = str(manifest_row["exit_spec_id"])
        executed["period"] = period
        executed["semantic_applicability"] = str(
            manifest_row["corrected_track_applicability"]
        )
        executed["semantic_not_applicable_reason"] = str(
            manifest_row["corrected_track_reason"]
        )
        executed["ranking_eligible"] = executed["semantic_applicability"].ne(
            "not_applicable"
        )
        executed["component_signals_json"] = json.dumps(
            entry_spec.get("component_signals", []),
            sort_keys=True,
            separators=(",", ":"),
        )
        executed["signal_weights_json"] = json.dumps(
            entry_spec.get("signal_weights", {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        executed["entry_rule_json"] = json.dumps(
            entry_spec.get("entry", {}), sort_keys=True, separators=(",", ":")
        )
        executed["entry_rule_kind"] = str(
            dict(entry_spec.get("entry", {})).get("kind", "")
        )
        executed["exit_rule_json"] = json.dumps(
            exit_rule, sort_keys=True, separators=(",", ":")
        )
        executed["exit_rule"] = str(exit_rule.get("kind", ""))
        for identifier in (
            "signal_test_id",
            "signal_variant_index",
            "entry_test_id",
            "entry_variant_index",
        ):
            executed[identifier] = entry_spec.get(identifier)
        executed["exit_test_id"] = projection.get("exit_test_id")
        executed["exit_variant_index"] = projection.get("exit_variant_index")
        ledgers.append(executed)
    opportunities = (
        pd.concat(ledgers, ignore_index=True)
        if ledgers
        else pd.DataFrame(columns=["combination_id", "status"])
    )
    opportunities = enrich_opportunities(opportunities, panel.frame)
    opportunities = complete_ledger_contract(opportunities)
    opportunities.insert(0, "entry_index", entry_index)
    opportunities["dataset_cutoff"] = DATASET_CUTOFF.date().isoformat()
    for date_column in ("entry_date", "exit_date", "mtm_date"):
        if date_column in opportunities:
            dates = pd.to_datetime(opportunities[date_column], errors="coerce")
            if dates.notna().any() and dates.max() > DATASET_CUTOFF:
                raise ValueError(f"{date_column} exceeds hard cutoff 2026-07-17")
    reconciliation = reconciliation_by_combination(
        opportunities, manifest_rows, period=period
    )
    reconciliation.insert(0, "entry_index", entry_index)
    if len(entry_events) and len(opportunities) != len(entry_events) * requested_exit_count:
        raise ValueError("the requested exits were not applied to the same entry cohort")

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "opportunities": _write_frame_pair(output_root, OPPORTUNITIES_STEM, opportunities),
        "coverage": _write_frame_pair(output_root, COVERAGE_STEM, coverage),
        "reconciliation": _write_frame_pair(
            output_root, RECONCILIATION_STEM, reconciliation
        ),
    }
    audit: dict[str, object] = {
        "schema_version": 1,
        "entry_index": entry_index,
        "entry_spec_id": entry_spec_id,
        "period": period,
        "entry_start": config["entry_start"],
        "entry_end": config["entry_end"],
        "load_start": config["load_start"],
        "load_end": config["load_end"],
        "warmup_loaded": True,
        "maximum_follow_up_sessions": MAX_HOLDING_SESSIONS,
        "combination_count": requested_exit_count,
        "full_combination_count": EXPECTED_EXIT_SPEC_COUNT,
        "exit_start": exit_start,
        "exit_end": exit_end,
        "entry_count": len(entry_events),
        "opportunity_count": len(opportunities),
        "coverage_selected": int(coverage.get("selected", pd.Series(dtype=bool)).sum()),
        "coverage_triggered": int(coverage.get("triggered", pd.Series(dtype=bool)).sum()),
        "coverage_waited": int(coverage.get("waited", pd.Series(dtype=bool)).sum()),
        "coverage_wait_sessions_total": int(
            pd.to_numeric(
                coverage.get("wait_sessions", pd.Series(dtype=float)), errors="coerce"
            ).fillna(0).sum()
        ),
        "coverage_not_triggered": int(
            coverage.get("coverage_status", pd.Series(dtype=str))
            .eq("entry_not_triggered")
            .sum()
        ),
        "reconciled": bool(reconciliation["reconciled"].all()) if len(reconciliation) else True,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "source_snapshot_sha256": str(manifest_rows.iloc[0]["source_snapshot_sha256"]),
        "dataset_hash": str(manifest_rows.iloc[0]["dataset_hash"]),
        "policy_hash": str(manifest_rows.iloc[0]["policy_hash"]),
        "cutoff": DATASET_CUTOFF.date().isoformat(),
        "locked_opened": include_locked,
        "locked_manifest_path": (
            str(frozen_manifest_path) if include_locked else None
        ),
        "locked_manifest_sha256": frozen_manifest_sha256 if include_locked else None,
        "locked_implementation_commit": implementation_commit if include_locked else None,
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
        "capital_rejection_applied": False,
        "portfolio_or_sizing_applied": False,
        "overlaps_discarded": False,
        "fx_merge_performed": False,
        "executor_prepared_context_reused": True,
        "outputs": outputs,
    }
    _write_json(output_root / AUDIT_NAME, audit)
    print(json.dumps(audit, sort_keys=True))
    return audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest-root", "--contract-root", dest="manifest_root", type=Path, required=True
    )
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--locked-shards-root", type=Path)
    parser.add_argument("--frozen-manifest", dest="frozen_manifest_path", type=Path)
    parser.add_argument("--frozen-manifest-sha256")
    parser.add_argument("--implementation-commit")
    parser.add_argument("--entry-index", type=int, choices=range(10), required=True)
    parser.add_argument("--period", choices=tuple(PERIODS), required=True)
    parser.add_argument("--exit-start", type=int, default=0)
    parser.add_argument("--exit-end", type=int, default=EXPECTED_EXIT_SPEC_COUNT)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    run_corrected_shard(**vars(_parser().parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

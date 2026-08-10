from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from typing import Any

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.artifact_recovery import (
    validate_materialized_market_security_master_recovery,
)
from aurora.research.openap_181.twelve_data_market_batch import (
    API_KEY_ENV,
    MAX_CREDITS_PER_DAY,
    MAX_CREDITS_PER_MINUTE,
    SOURCE_ADJUSTMENTS_URL,
    SOURCE_HISTORICAL_URL,
    SOURCE_PRICING_URL,
    SOURCE_QUICKSTART_URL,
    SOURCE_TERMS_URL,
    SOURCE_US_EQUITIES_URL,
    TWELVE_DATA_MARKET_SIGNALS,
    TwelveDataClient,
    TwelveDataIdentityError,
    TwelveDataSourceError,
    build_twelve_data_request_plan,
    completed_request_ids,
    estimate_twelve_data_quota,
    prepare_twelve_data_universe,
    redact_twelve_data_secret,
)
from aurora.research.openap_181.twelve_data_market_signals import (
    TWELVE_DATA_DIRECT_FORMULA_SHA256,
    TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
    TWELVE_DATA_SIGNAL_BAR_COLUMNS,
    calculate_twelve_data_direct_signals,
)
from aurora.research.openap_181.twelve_data_factor_signals import (
    KENNETH_FRENCH_DAILY_URL,
    KENNETH_FRENCH_MONTHLY_URL,
    TWELVE_DATA_FACTOR_FORMULA_SHA256,
    TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    calculate_twelve_data_factor_signals,
)
from aurora.research.openap_93.external import parse_french_zip


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def _append_checkpoint(path: Path, event: dict[str, Any], api_key: str) -> None:
    encoded = json.dumps(event, sort_keys=True)
    if api_key and api_key in encoded:
        raise RuntimeError("refusing to persist a Twelve Data credential")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _checkpoint_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid checkpoint JSON at line {line_number}") from exc
        if not isinstance(event, dict):
            raise RuntimeError(f"invalid checkpoint event at line {line_number}")
        events.append(event)
    return events


def _validate_resume(
    checkpoint: Path,
    restricted_root: Path,
    request_ids: set[str],
    prior_manifest: Path,
    resume_contract: dict[str, Any],
    resume_contract_sha256: str,
) -> set[str]:
    if not checkpoint.exists():
        if prior_manifest.exists() or restricted_root.exists():
            raise RuntimeError(
                "stale Twelve Data resume payload exists without its checkpoint"
            )
        return set()
    try:
        previous = json.loads(prior_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("prior Twelve Data acquisition manifest is invalid") from exc
    if (
        not isinstance(previous, dict)
        or previous.get("resume_contract") != resume_contract
        or previous.get("resume_contract_sha256") != resume_contract_sha256
    ):
        raise RuntimeError(
            "prior Twelve Data checkpoint is not bound to this exact plan"
        )
    completed = completed_request_ids(checkpoint)
    if not completed.issubset(request_ids):
        raise RuntimeError("checkpoint contains requests outside the current frozen plan")
    for event in _checkpoint_events(checkpoint):
        event_request_id = str(event.get("request_id") or "")
        event_status = str(event.get("status") or "")
        if (
            event_request_id not in request_ids
            or event_status
            not in {"success", "terminal_error", "retryable_error"}
        ):
            raise RuntimeError(
                "checkpoint event is outside the frozen request/status contract"
            )
        if event.get("resume_contract_sha256") != resume_contract_sha256:
            raise RuntimeError(
                "checkpoint event is not bound to this exact acquisition plan"
            )
        if event.get("status") != "success":
            continue
        relative = str(event.get("restricted_relative_path") or "")
        expected_hash = str(event.get("normalized_sha256") or "")
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise RuntimeError("checkpoint contains an unsafe restricted data path")
        path = restricted_root.parent / relative
        if (
            not path.is_file()
            or len(expected_hash) != 64
            or _sha256(path) != expected_hash
        ):
            raise RuntimeError(
                f"completed checkpoint payload is missing or corrupt: {event.get('request_id')}"
            )
    return completed


def _latest_status_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    latest: dict[str, str] = {}
    for event in events:
        request_id = str(event.get("request_id") or "")
        status = str(event.get("status") or "")
        if request_id and status:
            latest[request_id] = status
    return dict(sorted(Counter(latest.values()).items()))


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _validate_source_recovery(
    manifest_path: Path,
    security_master_path: Path,
    source_manifest_path: Path,
) -> dict[str, Any]:
    try:
        return validate_materialized_market_security_master_recovery(
            manifest_path,
            security_master_path,
            source_manifest_path,
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _calculate_complete_direct_signals(
    *,
    plan: pd.DataFrame,
    events: list[dict[str, Any]],
    output: Path,
    restricted_root: Path,
    formation_at: str,
    ff3_daily: pd.DataFrame,
    ff3_monthly: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    latest_events: dict[str, dict[str, Any]] = {}
    for event in events:
        request_id = str(event.get("request_id") or "")
        if request_id:
            latest_events[request_id] = event
    if len(latest_events) != len(plan) or any(
        str(event.get("status") or "") != "success"
        for event in latest_events.values()
    ):
        return pd.DataFrame(), pd.DataFrame()

    bar_parts: list[pd.DataFrame] = []
    retrieved_values: list[pd.Timestamp] = []
    for _security_id, requests in plan.groupby("security_id", sort=True):
        if set(requests["adjust"].astype(str)) != {"all", "none"}:
            raise RuntimeError("complete market plan lacks both adjustment modes")
        for request in requests.itertuples(index=False):
            event = latest_events[str(request.request_id)]
            relative = Path(str(event["restricted_relative_path"]))
            path = restricted_root.parent / relative
            if not path.is_file() or _sha256(path) != str(event["normalized_sha256"]):
                raise RuntimeError("complete market payload is missing or corrupt")
            bar_parts.append(
                pd.read_parquet(
                    path,
                    columns=list(TWELVE_DATA_SIGNAL_BAR_COLUMNS),
                )
            )
            retrieved_at = pd.to_datetime(
                event.get("retrieved_at"), errors="coerce", utc=True
            )
            if pd.isna(retrieved_at):
                raise RuntimeError("complete market payload has invalid retrieval time")
            retrieved_values.append(pd.Timestamp(retrieved_at))
    if not bar_parts or not retrieved_values:
        return pd.DataFrame(), pd.DataFrame()
    all_bars = pd.concat(bar_parts, ignore_index=True)
    retrieved_at = max(retrieved_values).isoformat()
    values = calculate_twelve_data_direct_signals(
        all_bars,
        formation_at=formation_at,
        retrieved_at=retrieved_at,
    )
    expected_rows = int(plan["security_id"].nunique()) * len(
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS
    )
    if len(values) != expected_rows or set(values["signal"]) != set(
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS
    ):
        raise RuntimeError("direct market signal output violates the frozen contract")
    csv_path = output / "twelve_data_direct_signal_observations.csv"
    parquet_path = output / "twelve_data_direct_signal_observations.parquet"
    values.to_csv(csv_path, index=False)
    values.to_parquet(parquet_path, index=False, compression="zstd")
    factor_values = calculate_twelve_data_factor_signals(
        all_bars,
        ff3_daily,
        ff3_monthly,
        formation_at=formation_at,
        retrieved_at=retrieved_at,
    )
    expected_factor_rows = int(plan["security_id"].nunique()) * len(
        TWELVE_DATA_FACTOR_SIGNAL_TARGETS
    )
    if len(factor_values) != expected_factor_rows or set(
        factor_values["signal"]
    ) != set(TWELVE_DATA_FACTOR_SIGNAL_TARGETS):
        raise RuntimeError("factor market signal output violates the frozen contract")
    factor_csv = output / "twelve_data_factor_signal_observations.csv"
    factor_parquet = output / "twelve_data_factor_signal_observations.parquet"
    factor_values.to_csv(factor_csv, index=False)
    factor_values.to_parquet(factor_parquet, index=False, compression="zstd")
    return values, factor_values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--security-master", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-recovery-manifest", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--ff3-daily-zip", type=Path, required=True)
    parser.add_argument("--ff3-monthly-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--daily-credit-budget",
        type=int,
        default=MAX_CREDITS_PER_DAY,
    )
    parser.add_argument(
        "--minimum-request-spacing-seconds",
        type=float,
        default=60.0 / MAX_CREDITS_PER_MINUTE + 0.1,
    )
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 Twelve Data market acquisition"
    )

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} is required")
    if not 1 <= args.daily_credit_budget <= MAX_CREDITS_PER_DAY:
        raise ValueError(
            f"daily credit budget must be between 1 and {MAX_CREDITS_PER_DAY}"
        )
    minimum_spacing = 60.0 / MAX_CREDITS_PER_MINUTE
    if args.minimum_request_spacing_seconds < minimum_spacing:
        raise ValueError(
            f"request spacing cannot be below {minimum_spacing:.3f} seconds"
        )
    implementation_sha = str(args.implementation_sha).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", implementation_sha) is None:
        raise ValueError("implementation SHA must contain 40 hexadecimal characters")
    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    if not args.ff3_daily_zip.is_file() or not args.ff3_monthly_zip.is_file():
        raise RuntimeError("frozen Kenneth French factor inputs are missing")
    ff3_daily_sha256 = _sha256(args.ff3_daily_zip)
    ff3_monthly_sha256 = _sha256(args.ff3_monthly_zip)
    ff3_daily = parse_french_zip(args.ff3_daily_zip, daily=True)
    ff3_monthly = parse_french_zip(args.ff3_monthly_zip, daily=False)
    restricted_root = output / "restricted_internal_raw"
    checkpoint = output / "twelve_data_checkpoint.jsonl"

    source_recovery = _validate_source_recovery(
        args.source_recovery_manifest,
        args.security_master,
        args.source_manifest,
    )
    security_master = pd.read_parquet(args.security_master)
    accepted, rejected = prepare_twelve_data_universe(security_master)
    if accepted.empty:
        raise RuntimeError("no unambiguous ranked primary securities remain")
    plan = build_twelve_data_request_plan(
        accepted,
        formation_at=args.formation_at,
    )
    request_ids = set(plan["request_id"].astype(str))
    accepted.to_csv(output / "twelve_data_universe_accepted.csv", index=False)
    rejected.to_csv(output / "twelve_data_universe_rejected.csv", index=False)
    plan_path = output / "twelve_data_request_plan_safe.csv"
    plan.to_csv(plan_path, index=False)
    security_master_sha256 = _sha256(args.security_master)
    source_manifest_sha256 = _sha256(args.source_manifest)
    request_plan_sha256 = _sha256(plan_path)
    resume_contract = {
        "contract_version": 4,
        "implementation_sha": implementation_sha,
        "source_run_id": int(source_recovery["source_run_id"]),
        "source_head_sha": str(source_recovery["source_head_sha"]),
        "source_artifact_id": int(source_recovery["source_artifact_id"]),
        "security_master_sha256": security_master_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "identity_source_sha256": str(
            source_recovery["identity_source_sha256"]
        ),
        "formation_at": pd.Timestamp(args.formation_at).isoformat(),
        "request_plan_sha256": request_plan_sha256,
        "market_signals": sorted(TWELVE_DATA_MARKET_SIGNALS),
        "direct_signal_targets": list(TWELVE_DATA_DIRECT_SIGNAL_TARGETS),
        "direct_formula_sha256": dict(TWELVE_DATA_DIRECT_FORMULA_SHA256),
        "factor_signal_targets": list(TWELVE_DATA_FACTOR_SIGNAL_TARGETS),
        "factor_formula_sha256": dict(TWELVE_DATA_FACTOR_FORMULA_SHA256),
        "ff3_daily_sha256": ff3_daily_sha256,
        "ff3_monthly_sha256": ff3_monthly_sha256,
        "available_at_contract": (
            "next_observed_session_midnight_et_else_retrieval_timestamp"
        ),
    }
    resume_contract_sha256 = _canonical_json_sha256(resume_contract)
    manifest_path = output / "twelve_data_market_acquisition_manifest.json"
    completed = _validate_resume(
        checkpoint,
        restricted_root,
        request_ids,
        manifest_path,
        resume_contract,
        resume_contract_sha256,
    )
    pending = plan.loc[~plan["request_id"].isin(completed)].copy()

    client = TwelveDataClient(api_key=api_key)
    attempted = 0
    stopped_on_retryable_error = False
    last_request_started: float | None = None
    for request_row in pending.itertuples(index=False):
        if attempted >= args.daily_credit_budget:
            break
        if last_request_started is not None:
            elapsed = time.monotonic() - last_request_started
            wait = args.minimum_request_spacing_seconds - elapsed
            if wait > 0:
                time.sleep(wait)
        last_request_started = time.monotonic()
        attempted += 1
        row = pd.Series(request_row._asdict())
        base_event = {
            "request_id": str(row["request_id"]),
            "security_id": str(row["security_id"]),
            "ticker": str(row["ticker"]),
            "cik": str(row["cik"]),
            "exchange_family": str(row["exchange_family"]),
            "adjust": str(row["adjust"]),
            "safe_url": str(row["safe_url"]),
            "credits_consumed": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "resume_contract_sha256": resume_contract_sha256,
        }
        try:
            response = client.fetch(row)
            relative = Path("restricted_internal_raw") / f"{row['request_id']}.parquet"
            target = output / relative
            _write_parquet_atomic(target, response.bars)
            event = {
                **base_event,
                "status": "success",
                "retrieved_at": response.retrieved_at,
                "raw_response_sha256": response.raw_sha256,
                "normalized_sha256": _sha256(target),
                "restricted_relative_path": relative.as_posix(),
                "bar_rows": int(len(response.bars)),
                "first_date": str(response.bars["date"].min()),
                "last_date": str(response.bars["date"].max()),
                "provider_exchange": str(response.meta.get("exchange") or ""),
                "provider_mic": str(response.meta.get("mic_code") or ""),
                "provider_type": str(response.meta.get("type") or ""),
                "historical_ticker_interval_verified": False,
                "strict_score_eligible": False,
            }
        except TwelveDataIdentityError as exc:
            event = {
                **base_event,
                "status": "terminal_error",
                "blocker": "blocked_identity",
                "error": redact_twelve_data_secret(exc, api_key),
                "strict_score_eligible": False,
            }
        except TwelveDataSourceError as exc:
            event = {
                **base_event,
                "status": "retryable_error" if exc.retryable else "terminal_error",
                "blocker": "blocked_source_failure",
                "http_status": exc.status_code,
                "error": redact_twelve_data_secret(exc, api_key),
                "strict_score_eligible": False,
            }
            if exc.retryable:
                stopped_on_retryable_error = True
        _append_checkpoint(checkpoint, event, api_key)
        if stopped_on_retryable_error:
            break

    events = _checkpoint_events(checkpoint)
    completed_after = completed_request_ids(checkpoint)
    quota = estimate_twelve_data_quota(plan)
    status_counts = _latest_status_counts(events)
    direct_values, factor_values = _calculate_complete_direct_signals(
        plan=plan,
        events=events,
        output=output,
        restricted_root=restricted_root,
        formation_at=args.formation_at,
        ff3_daily=ff3_daily,
        ff3_monthly=ff3_monthly,
    )
    direct_current = (
        direct_values.loc[direct_values["current_usable"].eq(True)].copy()  # noqa: E712
        if not direct_values.empty
        else direct_values.copy()
    )
    direct_csv = output / "twelve_data_direct_signal_observations.csv"
    direct_parquet = output / "twelve_data_direct_signal_observations.parquet"
    factor_current = (
        factor_values.loc[factor_values["current_usable"].eq(True)].copy()  # noqa: E712
        if not factor_values.empty
        else factor_values.copy()
    )
    factor_csv = output / "twelve_data_factor_signal_observations.csv"
    factor_parquet = output / "twelve_data_factor_signal_observations.parquet"
    manifest = {
        "source_id": "twelve_data_basic",
        "implementation_sha": implementation_sha,
        "source_run_id": str(source_recovery["source_run_id"]),
        "source_head_sha": str(source_recovery["source_head_sha"]),
        "source_artifact_id": int(source_recovery["source_artifact_id"]),
        "source_artifact_name": str(source_recovery["source_artifact_name"]),
        "source_recovery_manifest_sha256": _sha256(
            args.source_recovery_manifest
        ),
        "formation_at": pd.Timestamp(args.formation_at).isoformat(),
        "market_signal_count": len(TWELVE_DATA_MARKET_SIGNALS),
        "market_signals": sorted(TWELVE_DATA_MARKET_SIGNALS),
        "security_master_sha256": security_master_sha256,
        "source_manifest_sha256": source_manifest_sha256,
        "identity_source_url": str(source_recovery["identity_source_url"]),
        "identity_source_mode": str(source_recovery["identity_source_mode"]),
        "identity_source_sha256": str(
            source_recovery["identity_source_sha256"]
        ),
        "security_master_rows": int(len(security_master)),
        "accepted_security_rows": int(len(accepted)),
        "rejected_security_rows": int(len(rejected)),
        "request_plan": quota,
        "request_plan_sha256": request_plan_sha256,
        "resume_contract": resume_contract,
        "resume_contract_sha256": resume_contract_sha256,
        "daily_credit_budget": int(args.daily_credit_budget),
        "minimum_request_spacing_seconds": float(
            args.minimum_request_spacing_seconds
        ),
        "attempted_this_invocation": attempted,
        "resume_skippable_request_count": len(completed_after),
        "successful_request_count": int(status_counts.get("success", 0)),
        "terminal_error_request_count": int(
            status_counts.get("terminal_error", 0)
        ),
        "pending_request_count": int(len(plan) - len(completed_after)),
        "checkpoint_status_counts": status_counts,
        "stopped_on_retryable_error": stopped_on_retryable_error,
        "credential_env_var": API_KEY_ENV,
        "credential_persisted": False,
        "raw_market_data_location": "restricted_internal_raw",
        "raw_market_data_internal_use_only": True,
        "raw_market_data_redistribution_allowed": False,
        "derived_data_only_for_final_publishable_artifacts": True,
        "source_pricing_url": SOURCE_PRICING_URL,
        "source_quickstart_url": SOURCE_QUICKSTART_URL,
        "source_historical_url": SOURCE_HISTORICAL_URL,
        "source_adjustments_url": SOURCE_ADJUSTMENTS_URL,
        "source_terms_url": SOURCE_TERMS_URL,
        "source_us_equities_url": SOURCE_US_EQUITIES_URL,
        "identity_contract": (
            "current SEC CIK+ticker+listed exchange+primary common-stock identity "
            "corroborated by Twelve Data symbol+exchange+MIC+type; ambiguity omitted"
        ),
        "historical_ticker_interval_verified": False,
        "direct_signal_targets": list(TWELVE_DATA_DIRECT_SIGNAL_TARGETS),
        "direct_signal_target_count": len(TWELVE_DATA_DIRECT_SIGNAL_TARGETS),
        "direct_formula_sha256": dict(TWELVE_DATA_DIRECT_FORMULA_SHA256),
        "direct_observation_rows": int(len(direct_values)),
        "direct_current_value_rows": int(len(direct_current)),
        "direct_current_signal_count": int(
            direct_current["signal"].nunique() if not direct_current.empty else 0
        ),
        "direct_csv_sha256": _sha256(direct_csv) if direct_csv.is_file() else "",
        "direct_parquet_sha256": (
            _sha256(direct_parquet) if direct_parquet.is_file() else ""
        ),
        "factor_source_urls": [
            KENNETH_FRENCH_DAILY_URL,
            KENNETH_FRENCH_MONTHLY_URL,
        ],
        "ff3_daily_sha256": ff3_daily_sha256,
        "ff3_monthly_sha256": ff3_monthly_sha256,
        "factor_signal_targets": list(TWELVE_DATA_FACTOR_SIGNAL_TARGETS),
        "factor_signal_target_count": len(TWELVE_DATA_FACTOR_SIGNAL_TARGETS),
        "factor_formula_sha256": dict(TWELVE_DATA_FACTOR_FORMULA_SHA256),
        "factor_observation_rows": int(len(factor_values)),
        "factor_current_value_rows": int(len(factor_current)),
        "factor_current_signal_count": int(
            factor_current["signal"].nunique() if not factor_current.empty else 0
        ),
        "factor_csv_sha256": _sha256(factor_csv) if factor_csv.is_file() else "",
        "factor_parquet_sha256": (
            _sha256(factor_parquet) if factor_parquet.is_file() else ""
        ),
        "current_signal_computed": bool(
            not direct_values.empty and not factor_values.empty
        ),
        "strict_score_eligible": False,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
    }
    _write_json_atomic(
        manifest_path,
        manifest,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

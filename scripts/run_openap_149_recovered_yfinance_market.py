from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.artifact_recovery import (
    normalise_recovered_security_master,
)
from aurora.research.openap_181.recovered_yfinance_market import (
    RECOVERED_YFINANCE_SOURCE_RUN_ID,
    build_recovered_yfinance_bars,
    validate_recovered_yfinance_price_shard,
    validate_yfinance_source_manifest,
)
from aurora.research.openap_181.recovered_yfinance_extended_signals import (
    PASTOR_STAMBAUGH_URL,
    RECOVERED_YFINANCE_EXTENDED_FORMULA_SHA256,
    RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS,
    calculate_recovered_yfinance_extended_signals,
    parse_pastor_stambaugh_liquidity,
)
from aurora.research.openap_181.twelve_data_factor_signals import (
    KENNETH_FRENCH_DAILY_URL,
    KENNETH_FRENCH_MONTHLY_URL,
    TWELVE_DATA_FACTOR_FORMULA_SHA256,
    TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    calculate_twelve_data_factor_signals,
)
from aurora.research.openap_181.twelve_data_market_batch import (
    prepare_twelve_data_universe,
)
from aurora.research.openap_181.twelve_data_market_signals import (
    TWELVE_DATA_DIRECT_FORMULA_SHA256,
    TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
    calculate_twelve_data_direct_signals,
)
from aurora.research.openap_93.external import parse_french_zip


SOURCE_LABEL = "recovered yfinance artifact"
SOURCE_URL = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
    f"{RECOVERED_YFINANCE_SOURCE_RUN_ID}"
)
SOURCE_ID = f"recovered_yfinance_artifacts_{RECOVERED_YFINANCE_SOURCE_RUN_ID}"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid JSON input: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON input must be an object: {path.name}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _validate_recovery(
    recovery_root: Path,
    manifest: dict[str, Any],
    *,
    formation_at: str,
) -> tuple[list[pd.DataFrame], pd.DataFrame]:
    if (
        manifest.get("contract_version") != 1
        or int(manifest.get("source_run_id", 0))
        != RECOVERED_YFINANCE_SOURCE_RUN_ID
        or int(manifest.get("recovered_price_shard_count", 0)) != 48
        or manifest.get("full_artifacts_downloaded") is not False
        or manifest.get("fresh_provider_request_made") is not False
        or manifest.get("strict_score_eligible") is not False
        or manifest.get("locked_opened") is not False
        or manifest.get("validation_used_for_selection") is not False
    ):
        raise RuntimeError("recovered price manifest violates the frozen contract")
    security_master_path = recovery_root / "security_master.parquet"
    source_manifest_path = recovery_root / "source_manifest.csv"
    yfinance_manifest_path = recovery_root / "yfinance_source_manifest.csv"
    if (
        not security_master_path.is_file()
        or not source_manifest_path.is_file()
        or not yfinance_manifest_path.is_file()
        or _sha256_file(security_master_path) != manifest.get("security_master_sha256")
        or _sha256_file(source_manifest_path) != manifest.get("source_manifest_sha256")
        or _sha256_file(yfinance_manifest_path)
        != manifest.get("yfinance_source_manifest_sha256")
    ):
        raise RuntimeError("recovered market identity or source manifest is corrupt")
    yfinance_manifest = validate_yfinance_source_manifest(
        yfinance_manifest_path.read_bytes()
    )
    evidence_rows = manifest.get("recovered_price_shards")
    if not isinstance(evidence_rows, list) or len(evidence_rows) != 48:
        raise RuntimeError("recovered price evidence must contain exactly 48 rows")
    by_chunk = {int(row.get("chunk_index", -1)): row for row in evidence_rows}
    if sorted(by_chunk) != list(range(48)):
        raise RuntimeError("recovered price evidence has an invalid chunk set")
    formation = pd.to_datetime(formation_at, errors="coerce", utc=True)
    if pd.isna(formation):
        raise RuntimeError("recovered market formation_at is invalid")
    history_start = formation.tz_convert(None) - pd.DateOffset(years=16)
    shards: list[pd.DataFrame] = []
    for chunk_index in range(48):
        evidence = by_chunk[chunk_index]
        relative = Path(str(evidence.get("restricted_relative_path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("recovered price evidence contains an unsafe path")
        path = recovery_root / relative
        if (
            not path.is_file()
            or _sha256_file(path) != evidence.get("materialized_sha256")
        ):
            raise RuntimeError(f"recovered price shard {chunk_index} is corrupt")
        artifact = {
            "id": evidence.get("artifact_id"),
            "name": evidence.get("artifact_name"),
            "size_in_bytes": evidence.get("artifact_size_in_bytes"),
            "expired": False,
        }
        frame, revalidated = validate_recovered_yfinance_price_shard(
            artifact,
            path.read_bytes(),
            yfinance_manifest.iloc[chunk_index],
        )
        if revalidated["prices_sha256"] != evidence.get("prices_sha256"):
            raise RuntimeError("recovered price shard hash evidence changed")
        shards.append(frame.loc[frame["date"].ge(history_start)].copy())
    security_master = pd.read_parquet(security_master_path)
    official_identity_path = recovery_root / str(
        manifest.get("official_identity_universe_relative_path", "")
    )
    expected_official_hash = str(
        manifest.get("official_identity_universe_sha256", "")
    )
    if (
        not official_identity_path.is_file()
        or not re.fullmatch(r"[0-9a-f]{64}", expected_official_hash)
        or _sha256_file(official_identity_path) != expected_official_hash
    ):
        raise RuntimeError("recovered official SEC identity universe is corrupt")
    official_identity_universe = pd.read_csv(
        official_identity_path,
        keep_default_na=False,
    )
    security_master, _identity_normalisation = normalise_recovered_security_master(
        security_master,
        official_identity_universe=official_identity_universe,
    )
    return shards, security_master


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--ff3-daily-zip", type=Path, required=True)
    parser.add_argument("--ff3-monthly-zip", type=Path, required=True)
    parser.add_argument("--pastor-stambaugh-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP calculation from recovered existing YFinance price artifacts"
    )
    implementation_sha = str(args.implementation_sha).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", implementation_sha) is None:
        raise ValueError("implementation SHA must contain 40 hexadecimal characters")
    if (
        not args.ff3_daily_zip.is_file()
        or not args.ff3_monthly_zip.is_file()
        or not args.pastor_stambaugh_file.is_file()
    ):
        raise RuntimeError("frozen public factor inputs are missing")
    recovery_root = args.recovery_root.resolve()
    recovery_manifest_path = recovery_root / "recovered_yfinance_price_manifest.json"
    recovery_manifest = _read_json(recovery_manifest_path)
    shards, security_master = _validate_recovery(
        recovery_root,
        recovery_manifest,
        formation_at=args.formation_at,
    )
    accepted, rejected_identity = prepare_twelve_data_universe(security_master)
    if accepted.empty:
        raise RuntimeError("no unambiguous ranked primary securities remain")
    bars, rejected_prices = build_recovered_yfinance_bars(
        shards,
        accepted,
        formation_at=args.formation_at,
    )
    covered_security_ids = set(bars["security_id"].astype(str))
    if not covered_security_ids:
        raise RuntimeError("recovered bars cover no accepted SEC identity")
    retrieved_at = pd.to_datetime(
        bars["retrieved_at"], errors="coerce", utc=True
    ).max()
    if pd.isna(retrieved_at):
        raise RuntimeError("recovered bars have no valid retrieval time")
    ff3_daily = parse_french_zip(args.ff3_daily_zip, daily=True)
    ff3_monthly = parse_french_zip(args.ff3_monthly_zip, daily=False)
    pastor_stambaugh = parse_pastor_stambaugh_liquidity(
        args.pastor_stambaugh_file.read_bytes(),
        formation_at=args.formation_at,
    )
    direct = calculate_twelve_data_direct_signals(
        bars,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
        source_label=SOURCE_LABEL,
    )
    factors = calculate_twelve_data_factor_signals(
        bars,
        ff3_daily,
        ff3_monthly,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
        source_label=SOURCE_LABEL,
    )
    security_context = security_master.merge(
        accepted[["security_id", "ticker", "cik"]],
        on="security_id",
        how="inner",
        validate="one_to_one",
        suffixes=("_master", ""),
    )
    security_context = security_context.loc[
        security_context["security_id"].astype(str).isin(covered_security_ids)
    ].copy()
    if len(security_context) != len(covered_security_ids):
        raise RuntimeError("recovered bars and SEC identity context do not match")
    extended = calculate_recovered_yfinance_extended_signals(
        bars,
        security_context,
        ff3_monthly,
        pastor_stambaugh,
        formation_at=args.formation_at,
        retrieved_at=retrieved_at,
        source_id=SOURCE_ID,
        source_url=SOURCE_URL,
    )
    covered_security_rows = len(covered_security_ids)
    expected_direct_rows = covered_security_rows * len(
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS
    )
    expected_factor_rows = covered_security_rows * len(
        TWELVE_DATA_FACTOR_SIGNAL_TARGETS
    )
    expected_extended_rows = covered_security_rows * len(
        RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS
    )
    if (
        len(direct) != expected_direct_rows
        or set(direct["signal"]) != set(TWELVE_DATA_DIRECT_SIGNAL_TARGETS)
        or len(factors) != expected_factor_rows
        or set(factors["signal"]) != set(TWELVE_DATA_FACTOR_SIGNAL_TARGETS)
        or len(extended) != expected_extended_rows
        or set(extended["signal"])
        != set(RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS)
        or direct["strict_score_eligible"].ne(False).any()  # noqa: E712
        or factors["strict_score_eligible"].ne(False).any()  # noqa: E712
        or extended["strict_score_eligible"].ne(False).any()  # noqa: E712
    ):
        raise RuntimeError("recovered market signal output violates the frozen contract")
    observations = pd.concat(
        [direct, factors, extended], ignore_index=True
    ).sort_values(["security_id", "signal"])
    current = observations.loc[observations["current_usable"].eq(True)].copy()  # noqa: E712

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    observations_csv = output / "recovered_yfinance_market_observations.csv"
    observations_parquet = output / "recovered_yfinance_market_observations.parquet"
    current_csv = output / "recovered_yfinance_market_current.csv"
    observations.to_csv(observations_csv, index=False)
    observations.to_parquet(observations_parquet, index=False, compression="zstd")
    current.to_csv(current_csv, index=False)
    accepted.to_csv(output / "recovered_yfinance_universe_accepted.csv", index=False)
    rejected_identity.to_csv(
        output / "recovered_yfinance_universe_rejected.csv", index=False
    )
    rejected_prices.to_csv(
        output / "recovered_yfinance_price_symbols_rejected.csv", index=False
    )
    manifest = {
        "contract_version": 1,
        "implementation_sha": implementation_sha,
        "formation_at": pd.Timestamp(args.formation_at).isoformat(),
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "source_label": SOURCE_LABEL,
        "source_run_id": RECOVERED_YFINANCE_SOURCE_RUN_ID,
        "source_recovery_manifest_sha256": _sha256_file(recovery_manifest_path),
        "recovered_history_contract": (
            "sixteen_year_window_covers_frozen_maximum_15_year_formula_lookback"
        ),
        "security_master_sha256": recovery_manifest["security_master_sha256"],
        "yfinance_source_manifest_sha256": recovery_manifest[
            "yfinance_source_manifest_sha256"
        ],
        "ff3_daily_source_url": KENNETH_FRENCH_DAILY_URL,
        "ff3_monthly_source_url": KENNETH_FRENCH_MONTHLY_URL,
        "ff3_daily_sha256": _sha256_file(args.ff3_daily_zip),
        "ff3_monthly_sha256": _sha256_file(args.ff3_monthly_zip),
        "pastor_stambaugh_source_url": PASTOR_STAMBAUGH_URL,
        "pastor_stambaugh_sha256": _sha256_file(args.pastor_stambaugh_file),
        "pastor_stambaugh_latest_month": str(pastor_stambaugh["month"].max()),
        "accepted_security_rows": int(len(accepted)),
        "covered_security_rows": covered_security_rows,
        "rejected_identity_rows": int(len(rejected_identity)),
        "rejected_price_symbol_rows": int(len(rejected_prices)),
        "direct_signal_targets": list(TWELVE_DATA_DIRECT_SIGNAL_TARGETS),
        "direct_formula_sha256": dict(TWELVE_DATA_DIRECT_FORMULA_SHA256),
        "factor_signal_targets": list(TWELVE_DATA_FACTOR_SIGNAL_TARGETS),
        "factor_formula_sha256": dict(TWELVE_DATA_FACTOR_FORMULA_SHA256),
        "extended_signal_targets": list(
            RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS
        ),
        "extended_formula_sha256": dict(
            RECOVERED_YFINANCE_EXTENDED_FORMULA_SHA256
        ),
        "signal_target_count": len(TWELVE_DATA_DIRECT_SIGNAL_TARGETS)
        + len(TWELVE_DATA_FACTOR_SIGNAL_TARGETS)
        + len(RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS),
        "observation_rows": int(len(observations)),
        "current_value_rows": int(len(current)),
        "current_signal_count": int(current["signal"].nunique()),
        "observations_csv_sha256": _sha256_file(observations_csv),
        "observations_parquet_sha256": _sha256_file(observations_parquet),
        "current_csv_sha256": _sha256_file(current_csv),
        "historical_ticker_interval_verified": False,
        "raw_market_data_internal_use_only": True,
        "raw_market_data_redistribution_allowed": False,
        "fresh_provider_request_made": False,
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
    }
    _write_json_atomic(output / "recovered_yfinance_market_manifest.json", manifest)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

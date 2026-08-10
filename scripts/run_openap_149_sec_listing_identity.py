from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.sec_listing_identity import (
    EXCH_SWITCH_FORMULA_SHA256,
    MAX_CORROBORATED_GAP_DAYS,
    build_current_sec_universe,
    build_sec_listing_intervals,
    calculate_sec_exch_switch_current,
    extract_sec_listing_observations,
)
from aurora.research.openap_181.sec_notes_listing_inputs import (
    load_sec_notes_listing_history,
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_csv_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _write_parquet_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _formula_contract(root: Path) -> Path:
    matches = sorted(root.rglob("openap_181_formula_inventory.csv"))
    if len(matches) != 1:
        raise RuntimeError("Expected one pinned OpenAP formula inventory")
    inventory = pd.read_csv(matches[0], keep_default_na=False)
    hash_column = "formula_sha256" if "formula_sha256" in inventory else "sha256"
    selected = inventory.loc[inventory["signal"].eq("ExchSwitch")]
    expected_url = (
        "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
        "8db892442c2c3a3779b0f1eac4370d3655be15a1/"
        "Signals/pyCode/Predictors/ExchSwitch.py"
    )
    if (
        len(selected) != 1
        or str(selected.iloc[0][hash_column]) != EXCH_SWITCH_FORMULA_SHA256
        or str(selected.iloc[0].get("source_url", "")) != expected_url
    ):
        raise RuntimeError("Pinned ExchSwitch formula evidence does not match")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes-archive-dir", type=Path, required=True)
    parser.add_argument("--notes-source-manifest", type=Path, required=True)
    parser.add_argument("--current-sec-identity-json", type=Path, required=True)
    parser.add_argument("--current-sec-identity-source-url", required=True)
    parser.add_argument("--identity-retrieved-at", required=True)
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument("--formula-source-run-id", required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument(
        "--maximum-gap-days",
        type=int,
        default=MAX_CORROBORATED_GAP_DAYS,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 SEC Notes listing-identity preparation"
    )

    implementation_sha = str(args.implementation_sha).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", implementation_sha) is None:
        raise ValueError(
            "implementation SHA must contain 40 hexadecimal characters"
        )
    formation = pd.to_datetime(args.formation_at, errors="coerce", utc=True)
    if pd.isna(formation):
        raise ValueError("formation_at is not a valid timestamp")
    if args.maximum_gap_days <= 0:
        raise ValueError("maximum-gap-days must be positive")
    if re.fullmatch(r"[1-9][0-9]*", str(args.formula_source_run_id)) is None:
        raise ValueError("formula source run id must be a positive integer")

    try:
        identity_payload = json.loads(
            args.current_sec_identity_json.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("official SEC current identity JSON is invalid") from exc
    current_universe, current_rejections = build_current_sec_universe(
        identity_payload,
        retrieved_at=args.identity_retrieved_at,
        source_url=args.current_sec_identity_source_url,
    )
    if current_universe.empty:
        raise RuntimeError("no unambiguous official SEC current securities remain")
    formula_inventory = _formula_contract(args.formula_root)

    notes_manifest = pd.read_csv(
        args.notes_source_manifest,
        keep_default_na=False,
    )
    notes_retrieved_at = pd.to_datetime(
        notes_manifest["retrieved_at"], errors="coerce", utc=True
    ).max()
    if pd.isna(notes_retrieved_at):
        raise RuntimeError("SEC Notes manifest has no valid retrieval timestamp")
    facts, archive_summaries = load_sec_notes_listing_history(
        args.notes_archive_dir,
        notes_manifest,
        allowed_ciks=frozenset(current_universe["cik"].astype(str)),
    )
    observations, observation_rejections = extract_sec_listing_observations(
        facts,
        formation_at=formation,
    )
    intervals, interval_rejections = build_sec_listing_intervals(
        observations,
        current_universe,
        formation_at=formation,
        maximum_gap_days=args.maximum_gap_days,
    )
    exchange_switch = calculate_sec_exch_switch_current(
        observations,
        intervals,
        current_universe,
        formation_at=formation,
        retrieved_at=notes_retrieved_at,
    )

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, pd.DataFrame] = {
        "current_universe_accepted.csv": current_universe,
        "current_universe_rejected.csv": current_rejections,
        "sec_notes_archive_summaries.csv": archive_summaries,
        "sec_listing_observation_rejections.csv": observation_rejections,
        "sec_listing_interval_rejections.csv": interval_rejections,
        "openap_149_sec_exch_switch_current.csv": exchange_switch,
    }
    for name, frame in artifacts.items():
        _write_csv_atomic(output / name, frame)
    parquet_artifacts: dict[str, pd.DataFrame] = {
        "sec_listing_facts.parquet": facts,
        "sec_listing_observations.parquet": observations,
        "sec_listing_intervals.parquet": intervals,
        "openap_149_sec_exch_switch_current.parquet": exchange_switch,
    }
    for name, frame in parquet_artifacts.items():
        _write_parquet_atomic(output / name, frame)

    output_names = tuple(artifacts) + tuple(parquet_artifacts)
    manifest = {
        "implementation_sha": implementation_sha,
        "formation_at": pd.Timestamp(formation).isoformat(),
        "maximum_gap_days": args.maximum_gap_days,
        "identity_source_url": str(args.current_sec_identity_source_url),
        "identity_source_mode": "sec_official_live_direct",
        "identity_source_sha256": _sha256(args.current_sec_identity_json),
        "identity_retrieved_at": pd.Timestamp(
            pd.to_datetime(args.identity_retrieved_at, utc=True)
        ).isoformat(),
        "formula_source_run_id": str(args.formula_source_run_id),
        "formula_inventory_sha256": _sha256(formula_inventory),
        "notes_source_manifest_sha256": _sha256(args.notes_source_manifest),
        "notes_periods": sorted(
            archive_summaries["source_period"].astype(str).tolist()
        ),
        "notes_archives": len(archive_summaries),
        "notes_archive_size_bytes": int(
            archive_summaries["archive_size_bytes"].sum()
        ),
        "notes_txt_rows_scanned": int(
            archive_summaries["txt_rows_scanned"].sum()
        ),
        "current_universe_rows": len(current_universe),
        "current_universe_rejected_rows": len(current_rejections),
        "listing_fact_rows": len(facts),
        "listing_observation_rows": len(observations),
        "listing_observation_rejected_rows": len(observation_rejections),
        "listing_interval_rows": len(intervals),
        "listing_interval_rejected_rows": len(interval_rejections),
        "exchange_switch_rows": len(exchange_switch),
        "exchange_switch_current_value_rows": int(
            exchange_switch["current_usable"].eq(True).sum()  # noqa: E712
        ),
        "signal": "ExchSwitch",
        "formula_sha256": str(exchange_switch["formula_sha256"].iloc[0])
        if not exchange_switch.empty
        else "",
        "identity_quality": "sec_filing_endpoints_corroborated_non_permno",
        "historical_ticker_interval_verified": False,
        "market_bars_acquired": False,
        "current_signal_computed": bool(
            exchange_switch["current_usable"].eq(True).any()  # noqa: E712
        ),
        "strict_score_eligible": False,
        "locked_opened": False,
        "forward_opened": False,
        "output_sha256": {
            name: _sha256(output / name) for name in sorted(output_names)
        },
    }
    _write_json_atomic(output / "sec_listing_identity_manifest.json", manifest)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
from aurora.research.openap_181.recovered_current_features import (
    RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS,
    RECOVERED_CURRENT_FEATURE_FORMULA_SHA256,
    RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID,
    RECOVERED_CURRENT_FEATURE_TARGETS,
    build_recovered_current_feature_observations,
    validate_recovered_current_feature_members,
)


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


def _safe_recovered_path(root: Path, relative_value: Any) -> Path:
    relative = Path(str(relative_value or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("current feature recovery contains an unsafe path")
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError("current feature recovery path escapes its root") from exc
    return path


def _load_recovered_bundle(
    recovery_root: Path,
    recovery: dict[str, Any],
):
    if (
        recovery.get("contract_version") != 1
        or int(recovery.get("audited_market_run_id", 0))
        != RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID
        or recovery.get("recovered_current_feature_contract_version") != 1
        or int(recovery.get("recovered_current_feature_member_count", 0))
        != len(RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS)
        or int(recovery.get("recovered_current_feature_target_count", 0))
        != len(RECOVERED_CURRENT_FEATURE_TARGETS)
        or recovery.get("full_artifacts_downloaded") is not False
        or recovery.get("fresh_provider_request_made") is not False
        or recovery.get("strict_score_eligible") is not False
        or recovery.get("locked_opened") is not False
        or recovery.get("validation_used_for_selection") is not False
    ):
        raise RuntimeError("current feature recovery violates the frozen contract")

    materialized = recovery.get("recovered_current_feature_members")
    if not isinstance(materialized, list) or len(materialized) != len(
        RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS
    ):
        raise RuntimeError("current feature recovery member evidence is invalid")
    by_name: dict[str, Path] = {}
    for row in materialized:
        if not isinstance(row, dict):
            raise RuntimeError("current feature recovery member evidence is invalid")
        name = str(row.get("member_name", ""))
        if name in by_name or name not in RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS:
            raise RuntimeError("current feature recovery member set is invalid")
        path = _safe_recovered_path(
            recovery_root,
            row.get("restricted_relative_path"),
        )
        if (
            not path.is_file()
            or path.stat().st_size != int(row.get("materialized_bytes", -1))
            or _sha256_file(path) != row.get("materialized_sha256")
        ):
            raise RuntimeError(f"recovered current feature member is corrupt: {name}")
        by_name[name] = path
    if set(by_name) != set(RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS):
        raise RuntimeError("current feature recovery member set is incomplete")

    security_master_path = recovery_root / "security_master.parquet"
    source_summary_path = recovery_root / "source_execution_summary.json"
    source_output_manifest_path = recovery_root / "source_output_manifest.csv"
    if (
        not security_master_path.is_file()
        or not source_summary_path.is_file()
        or not source_output_manifest_path.is_file()
        or _sha256_file(security_master_path)
        != recovery.get("security_master_sha256")
        or _sha256_file(source_output_manifest_path)
        != recovery.get("source_output_manifest_sha256")
    ):
        raise RuntimeError("recovered current feature metadata is corrupt")
    members = {
        "security_master.parquet": security_master_path.read_bytes(),
        "execution_summary.json": source_summary_path.read_bytes(),
        "output_manifest.csv": source_output_manifest_path.read_bytes(),
        **{name: path.read_bytes() for name, path in by_name.items()},
    }
    bundle = validate_recovered_current_feature_members(members)
    expected_evidence = recovery.get("recovered_current_feature_evidence")
    if not isinstance(expected_evidence, dict):
        raise RuntimeError("current feature recovery lacks validated evidence")
    for field in (
        "source_run_id",
        "source_as_of",
        "input_predictors",
        "eligible_symbols",
        "features_rows",
        "coverage_rows",
        "sec_concept_input_rows",
        "target_signal_count",
        "target_signals",
        "official_formula_sha256",
        "member_sha256",
        "strict_score_eligible",
        "strict_score_increment",
        "locked_opened",
        "validation_used_for_selection",
    ):
        if bundle.evidence.get(field) != expected_evidence.get(field):
            raise RuntimeError(
                f"recovered current feature evidence changed after recovery: {field}"
            )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery-root", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP calculation evidence from recovered current feature artifacts"
    )
    implementation_sha = str(args.implementation_sha).strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", implementation_sha) is None:
        raise ValueError("implementation SHA must contain 40 hexadecimal characters")
    recovery_root = args.recovery_root.resolve()
    recovery_manifest_path = recovery_root / "recovered_yfinance_price_manifest.json"
    recovery = _read_json(recovery_manifest_path)
    bundle = _load_recovered_bundle(recovery_root, recovery)
    observations = build_recovered_current_feature_observations(bundle)
    current = observations.loc[
        observations["current_usable"].eq(True)  # noqa: E712
    ].copy()
    rejected = observations.loc[
        observations["current_usable"].eq(False)  # noqa: E712
    ].copy()
    if (
        len(observations)
        != int(bundle.evidence["eligible_symbols"])
        * len(RECOVERED_CURRENT_FEATURE_TARGETS)
        or set(observations["signal"]) != set(RECOVERED_CURRENT_FEATURE_TARGETS)
        or observations["strict_score_eligible"].ne(False).any()  # noqa: E712
        or observations["formation_at"].nunique() != 1
        or observations["formation_at"].iloc[0]
        != pd.Timestamp(bundle.evidence["source_as_of"])
    ):
        raise RuntimeError("recovered current feature output violates the contract")

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    observations_csv = output / "recovered_current_features_observations.csv"
    observations_parquet = output / "recovered_current_features_observations.parquet"
    current_csv = output / "recovered_current_features_current.csv"
    rejected_csv = output / "recovered_current_features_rejected.csv"
    coverage_csv = output / "recovered_current_features_source_coverage.csv"
    observations.to_csv(observations_csv, index=False)
    observations.to_parquet(
        observations_parquet,
        index=False,
        compression="zstd",
    )
    current.to_csv(current_csv, index=False)
    rejected.to_csv(rejected_csv, index=False)
    bundle.coverage.loc[
        bundle.coverage["signalname"].isin(RECOVERED_CURRENT_FEATURE_TARGETS)
    ].to_csv(coverage_csv, index=False)

    signal_counts = (
        current.groupby("signal")["security_id"].nunique().astype(int).to_dict()
        if not current.empty
        else {}
    )
    manifest = {
        "contract_version": 1,
        "implementation_sha": implementation_sha,
        "source_run_id": RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID,
        "source_run_url": bundle.evidence["source_run_url"],
        "source_artifact": bundle.evidence["source_artifact"],
        "source_as_of": bundle.evidence["source_as_of"],
        "source_recovery_manifest_sha256": _sha256_file(
            recovery_manifest_path
        ),
        "source_output_manifest_sha256": recovery[
            "source_output_manifest_sha256"
        ],
        "target_signals": list(RECOVERED_CURRENT_FEATURE_TARGETS),
        "target_signal_count": len(RECOVERED_CURRENT_FEATURE_TARGETS),
        "official_formula_sha256": dict(
            RECOVERED_CURRENT_FEATURE_FORMULA_SHA256
        ),
        "source_feature_rows": int(bundle.evidence["features_rows"]),
        "source_coverage_rows": int(bundle.evidence["coverage_rows"]),
        "source_concept_input_rows": int(
            bundle.evidence["sec_concept_input_rows"]
        ),
        "eligible_security_rows": int(bundle.evidence["eligible_symbols"]),
        "observation_rows": int(len(observations)),
        "current_value_rows": int(len(current)),
        "current_signal_count": int(current["signal"].nunique()),
        "current_value_count_by_signal": signal_counts,
        "rejected_rows": int(len(rejected)),
        "rejection_reasons": (
            rejected["reason_if_missing"].value_counts().astype(int).to_dict()
            if not rejected.empty
            else {}
        ),
        "observations_csv_sha256": _sha256_file(observations_csv),
        "observations_parquet_sha256": _sha256_file(observations_parquet),
        "current_csv_sha256": _sha256_file(current_csv),
        "rejected_csv_sha256": _sha256_file(rejected_csv),
        "coverage_csv_sha256": _sha256_file(coverage_csv),
        "formula_recomputed_during_recovery": False,
        "source_values_revalidated": True,
        "source_age_laundered": False,
        "fresh_provider_request_made": False,
        "historical_ticker_interval_verified": False,
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
    }
    _write_json_atomic(
        output / "recovered_current_features_manifest.json",
        manifest,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

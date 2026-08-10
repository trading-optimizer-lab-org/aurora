from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.acquisition_149 import (
    build_acquisition_matrix,
    load_target_routes,
    overlay_preferred_current_evidence,
    replace_current_signal_batches,
    write_acquisition_outputs,
)
from aurora.research.openap_181.recovered_current_features import (
    RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION,
    RECOVERED_CURRENT_FEATURE_TARGETS,
)
from aurora.research.openap_181.recovered_yfinance_extended_signals import (
    RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS,
)
from aurora.research.openap_181.twelve_data_factor_signals import (
    TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
)
from aurora.research.openap_181.twelve_data_market_signals import (
    TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
)
from aurora.research.openap_93.registry import load_signal_registry


def _find_one(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {filename} under {root}, found {len(matches)}")
    return matches[0]


def _sha256_many(paths: list[Path]) -> str:
    digest = sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid recovered manifest: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Recovered manifest must be an object: {path.name}")
    return payload


def _manifest_string_tuple(
    manifest: dict[str, object],
    key: str,
) -> tuple[str, ...]:
    value = manifest.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise RuntimeError(f"Recovered manifest has invalid {key}")
    return tuple(value)


def _validate_recovered_csv(
    csv_path: Path,
    manifest: dict[str, object],
    *,
    expected_signals: set[str],
) -> pd.DataFrame:
    if _sha256_file(csv_path) != manifest.get("current_csv_sha256"):
        raise RuntimeError(f"Recovered CSV SHA-256 mismatch: {csv_path.name}")
    frame = pd.read_csv(csv_path, low_memory=False)
    required_columns = {
        "security_id",
        "signal",
        "formation_at",
        "current_usable",
        "strict_score_eligible",
    }
    if not required_columns.issubset(frame.columns):
        raise RuntimeError("Recovered current values lack required gates")
    signals = set(frame["signal"].dropna().astype(str))
    strict = frame["strict_score_eligible"].astype(str).str.lower()
    usable = frame["current_usable"].astype(str).str.lower()
    duplicate_keys = frame.duplicated(
        subset=["security_id", "signal", "formation_at"], keep=False
    )
    if (
        not signals.issubset(expected_signals)
        or int(manifest.get("current_value_rows", -1)) != len(frame)
        or int(manifest.get("current_signal_count", -1)) != len(signals)
        or not usable.eq("true").all()
        or not strict.eq("false").all()
        or duplicate_keys.any()
    ):
        raise RuntimeError("Recovered current values violate their manifest")
    return frame


def _load_recovered_market_batch(
    root: Path,
    *,
    expected_implementation_sha: str,
) -> tuple[pd.DataFrame, list[Path]]:
    csv_path = _find_one(root, "recovered_yfinance_market_current.csv")
    manifest_path = _find_one(root, "recovered_yfinance_market_manifest.json")
    manifest = _read_manifest(manifest_path)
    direct = _manifest_string_tuple(manifest, "direct_signal_targets")
    factor = _manifest_string_tuple(manifest, "factor_signal_targets")
    extended = _manifest_string_tuple(manifest, "extended_signal_targets")
    expected_signals = set(
        TWELVE_DATA_DIRECT_SIGNAL_TARGETS
        + TWELVE_DATA_FACTOR_SIGNAL_TARGETS
        + RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS
    )
    if manifest.get("implementation_sha") != expected_implementation_sha:
        raise RuntimeError("Recovered market implementation SHA does not match")
    if (
        manifest.get("contract_version") != 1
        or direct != TWELVE_DATA_DIRECT_SIGNAL_TARGETS
        or factor != TWELVE_DATA_FACTOR_SIGNAL_TARGETS
        or extended != RECOVERED_YFINANCE_EXTENDED_SIGNAL_TARGETS
        or int(manifest.get("signal_target_count", -1)) != len(expected_signals)
        or manifest.get("historical_ticker_interval_verified") is not False
        or manifest.get("raw_market_data_internal_use_only") is not True
        or manifest.get("raw_market_data_redistribution_allowed") is not False
        or manifest.get("fresh_provider_request_made") is not False
        or manifest.get("strict_score_eligible") is not False
        or int(manifest.get("strict_score_increment", -1)) != 0
        or manifest.get("locked_opened") is not False
        or manifest.get("forward_opened") is not False
        or manifest.get("validation_used_for_selection") is not False
    ):
        raise RuntimeError("Recovered market manifest violates its contract")
    frame = _validate_recovered_csv(
        csv_path,
        manifest,
        expected_signals=expected_signals,
    )
    return frame, [csv_path, manifest_path]


def _load_recovered_current_feature_batch(
    root: Path,
    *,
    expected_implementation_sha: str,
) -> tuple[pd.DataFrame, list[Path]]:
    csv_path = _find_one(root, "recovered_current_features_current.csv")
    manifest_path = _find_one(root, "recovered_current_features_manifest.json")
    manifest = _read_manifest(manifest_path)
    targets = _manifest_string_tuple(manifest, "target_signals")
    if manifest.get("implementation_sha") != expected_implementation_sha:
        raise RuntimeError("Recovered feature implementation SHA does not match")
    if (
        manifest.get("contract_version")
        != RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION
        or targets != RECOVERED_CURRENT_FEATURE_TARGETS
        or int(manifest.get("target_signal_count", -1))
        != len(RECOVERED_CURRENT_FEATURE_TARGETS)
        or manifest.get("formula_recomputed_during_recovery") is not False
        or manifest.get("source_values_revalidated") is not True
        or manifest.get("source_age_laundered") is not False
        or manifest.get("fresh_provider_request_made") is not False
        or manifest.get("historical_ticker_interval_verified") is not False
        or manifest.get("strict_score_eligible") is not False
        or int(manifest.get("strict_score_increment", -1)) != 0
        or manifest.get("locked_opened") is not False
        or manifest.get("forward_opened") is not False
        or manifest.get("validation_used_for_selection") is not False
    ):
        raise RuntimeError("Recovered feature manifest violates its contract")
    frame = _validate_recovered_csv(
        csv_path,
        manifest,
        expected_signals=set(RECOVERED_CURRENT_FEATURE_TARGETS),
    )
    return frame, [csv_path, manifest_path]


def _signal_contracts(path: Path) -> dict[str, dict[str, object]]:
    return {
        signal: {
            "required_inputs": spec.required_inputs,
            "minimum_history": (
                f"formula-specific {spec.natural_frequency} lookback; "
                "see pinned OpenAP source"
            ),
        }
        for signal, spec in load_signal_registry(path).items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-matrix", type=Path, required=True)
    parser.add_argument("--current-93-root", type=Path, required=True)
    parser.add_argument("--sec-current-root", type=Path, required=True)
    parser.add_argument("--finra-current-root", type=Path, required=True)
    parser.add_argument("--realestate-current-root", type=Path, required=True)
    parser.add_argument("--exchange-switch-current-root", type=Path, required=True)
    parser.add_argument("--field-ritter-current-root", type=Path, required=True)
    parser.add_argument("--spinoff-current-root", type=Path, required=True)
    parser.add_argument("--recovered-market-root", type=Path, required=True)
    parser.add_argument(
        "--recovered-current-features-root", type=Path, required=True
    )
    parser.add_argument("--formula-root", type=Path, required=True)
    parser.add_argument(
        "--signals-93", type=Path, default=Path("config/openap_93/signals_93.yaml")
    )
    parser.add_argument("--current-93-run-url", required=True)
    parser.add_argument("--sec-current-run-url", required=True)
    parser.add_argument("--finra-current-run-url", required=True)
    parser.add_argument("--realestate-current-run-url", required=True)
    parser.add_argument("--exchange-switch-current-run-url", required=True)
    parser.add_argument("--field-ritter-current-run-url", required=True)
    parser.add_argument("--spinoff-current-run-url", required=True)
    parser.add_argument("--recovered-current-run-url", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--evidence-run-url", required=True)
    parser.add_argument("--evidence-artifact", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 current evidence consolidation"
    )
    expected_source_sha = args.expected_source_sha.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) is None:
        raise RuntimeError("Expected source SHA must be a full Git revision")

    current_93_path = _find_one(args.current_93_root, "signals_93_current.csv")
    sec_path = _find_one(
        args.sec_current_root, "openap_149_sec_companyfacts_current.csv"
    )
    finra_path = _find_one(
        args.finra_current_root, "openap_149_finra_short_interest_current.csv"
    )
    realestate_path = _find_one(
        args.realestate_current_root, "openap_149_realestate_current.csv"
    )
    exchange_switch_path = _find_one(
        args.exchange_switch_current_root,
        "openap_149_sec_exch_switch_current.csv",
    )
    field_ritter_path = _find_one(
        args.field_ritter_current_root,
        "openap_149_field_ritter_ipo_current.csv",
    )
    spinoff_path = _find_one(
        args.spinoff_current_root,
        "openap_149_sec_spinoff_current.csv",
    )
    recovered_market_current, recovered_market_paths = (
        _load_recovered_market_batch(
            args.recovered_market_root,
            expected_implementation_sha=expected_source_sha,
        )
    )
    recovered_feature_current, recovered_feature_paths = (
        _load_recovered_current_feature_batch(
            args.recovered_current_features_root,
            expected_implementation_sha=expected_source_sha,
        )
    )
    formula_path = _find_one(args.formula_root, "openap_181_formula_inventory.csv")
    current_93 = pd.read_csv(current_93_path, low_memory=False)
    current_93["evidence_run"] = args.current_93_run_url
    sec_current = pd.read_csv(sec_path, low_memory=False)
    sec_current["evidence_run"] = args.sec_current_run_url
    finra_current = pd.read_csv(finra_path, low_memory=False)
    finra_current["evidence_run"] = args.finra_current_run_url
    realestate_current = pd.read_csv(realestate_path, low_memory=False)
    realestate_current["evidence_run"] = args.realestate_current_run_url
    exchange_switch_current = pd.read_csv(exchange_switch_path, low_memory=False)
    exchange_switch_current["evidence_run"] = args.exchange_switch_current_run_url
    field_ritter_current = pd.read_csv(field_ritter_path, low_memory=False)
    field_ritter_current["evidence_run"] = args.field_ritter_current_run_url
    spinoff_current = pd.read_csv(spinoff_path, low_memory=False)
    spinoff_current["evidence_run"] = args.spinoff_current_run_url
    recovered_market_current["evidence_run"] = args.recovered_current_run_url
    recovered_feature_current["evidence_run"] = args.recovered_current_run_url
    current = overlay_preferred_current_evidence(current_93, sec_current)
    current = replace_current_signal_batches(current, finra_current)
    current = replace_current_signal_batches(current, realestate_current)
    current = replace_current_signal_batches(current, exchange_switch_current)
    current = replace_current_signal_batches(current, field_ritter_current)
    current = replace_current_signal_batches(current, spinoff_current)
    current = replace_current_signal_batches(current, recovered_market_current)
    current = replace_current_signal_batches(current, recovered_feature_current)

    routes = load_target_routes(args.route_matrix)
    formulas = pd.read_csv(formula_path, keep_default_na=False)
    matrix, values = build_acquisition_matrix(
        routes,
        current,
        formula_inventory=formulas,
        signal_contracts=_signal_contracts(args.signals_93),
        evidence_run_url=args.evidence_run_url,
        evidence_artifact=args.evidence_artifact,
        tests_executed=(
            "tests/test_openap_149_acquisition.py|"
            "tests/test_openap_149_sec_companyfacts.py|"
            "tests/test_openap_181_short_interest_batch.py|"
            "tests/test_openap_149_realestate_rendered_batch.py|"
            "tests/test_openap_181_sec_listing_identity.py|"
            "tests/test_openap_181_field_ritter_ipo.py|"
            "tests/test_openap_181_sec_spinoff.py|"
            "tests/test_openap_149_recovered_yfinance_market.py|"
            "tests/test_openap_149_recovered_current_features.py"
        ),
    )
    source_runs = (
        current.groupby("signal")["evidence_run"]
        .agg(lambda values: "|".join(sorted(set(values.astype(str)))))
        .to_dict()
    )
    matrix["source_evidence_run"] = matrix["signal"].map(source_runs).fillna("")

    output = args.output_dir if args.output_dir.is_absolute() else base_data_dir() / args.output_dir
    summary = write_acquisition_outputs(
        matrix,
        values,
        output,
        source_values_sha256=_sha256_many(
            [
                current_93_path,
                sec_path,
                finra_path,
                realestate_path,
                exchange_switch_path,
                field_ritter_path,
                spinoff_path,
                *recovered_market_paths,
                *recovered_feature_paths,
            ]
        ),
        formula_inventory_sha256=_sha256_many([formula_path]),
    )
    manifest = {
        "current_93_run_url": args.current_93_run_url,
        "sec_current_run_url": args.sec_current_run_url,
        "finra_current_run_url": args.finra_current_run_url,
        "realestate_current_run_url": args.realestate_current_run_url,
        "exchange_switch_current_run_url": args.exchange_switch_current_run_url,
        "field_ritter_current_run_url": args.field_ritter_current_run_url,
        "spinoff_current_run_url": args.spinoff_current_run_url,
        "recovered_current_run_url": args.recovered_current_run_url,
        "expected_source_sha": expected_source_sha,
        "evidence_run_url": args.evidence_run_url,
        "evidence_artifact": args.evidence_artifact,
        "source_files": [
            current_93_path.name,
            sec_path.name,
            finra_path.name,
            realestate_path.name,
            exchange_switch_path.name,
            field_ritter_path.name,
            spinoff_path.name,
            *(path.name for path in recovered_market_paths),
            *(path.name for path in recovered_feature_paths),
        ],
        "merged_rows": int(len(current)),
        "approved_rows": int(len(values)),
        **summary,
    }
    (output / "openap_149_consolidation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

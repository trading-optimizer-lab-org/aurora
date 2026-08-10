from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

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
    parser.add_argument("--evidence-run-url", required=True)
    parser.add_argument("--evidence-artifact", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 current evidence consolidation"
    )

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
    current = overlay_preferred_current_evidence(current_93, sec_current)
    current = replace_current_signal_batches(current, finra_current)
    current = replace_current_signal_batches(current, realestate_current)
    current = replace_current_signal_batches(current, exchange_switch_current)
    current = replace_current_signal_batches(current, field_ritter_current)
    current = replace_current_signal_batches(current, spinoff_current)

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
            "tests/test_openap_181_sec_spinoff.py"
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

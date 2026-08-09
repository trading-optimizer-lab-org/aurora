from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.acquisition_149 import (
    build_acquisition_matrix,
    load_target_routes,
    write_acquisition_outputs,
)
from aurora.research.openap_93.registry import load_signal_registry


def _find_one(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {filename} under {root}, found {len(matches)}")
    return matches[0]


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signal_contracts(path: Path) -> dict[str, dict[str, object]]:
    registry = load_signal_registry(path)
    return {
        signal: {
            "required_inputs": spec.required_inputs,
            "minimum_history": (
                f"formula-specific {spec.natural_frequency} lookback; "
                "see pinned OpenAP source"
            ),
        }
        for signal, spec in registry.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route-matrix", type=Path, required=True)
    parser.add_argument("--current-values-root", type=Path, required=True)
    parser.add_argument("--formula-evidence-root", type=Path, required=True)
    parser.add_argument("--signals-93", type=Path, default=Path("config/openap_93/signals_93.yaml"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence-run-url", required=True)
    parser.add_argument("--source-evidence-run-url", required=True)
    parser.add_argument("--evidence-artifact", required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission("OpenAP 149 acquisition extract")

    current_path = _find_one(args.current_values_root, "signals_93_current.csv")
    formula_path = _find_one(args.formula_evidence_root, "openap_181_formula_inventory.csv")
    routes = load_target_routes(args.route_matrix)
    current = pd.read_csv(current_path, low_memory=False)
    formulas = pd.read_csv(formula_path, keep_default_na=False)
    matrix, values = build_acquisition_matrix(
        routes,
        current,
        formula_inventory=formulas,
        signal_contracts=_signal_contracts(args.signals_93),
        evidence_run_url=args.evidence_run_url,
        source_evidence_run_url=args.source_evidence_run_url,
        evidence_artifact=args.evidence_artifact,
    )
    output = args.output_dir if args.output_dir.is_absolute() else base_data_dir() / args.output_dir
    write_acquisition_outputs(
        matrix,
        values,
        output,
        source_values_sha256=_sha256(current_path),
        formula_inventory_sha256=_sha256(formula_path),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

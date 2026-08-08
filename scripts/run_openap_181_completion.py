from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.completion import (
    attach_runtime_evidence,
    build_completion_manifest,
    write_completion_outputs,
)
from aurora.research.openap_93.registry import load_signal_registry


def _read_frame(path: Path | None) -> pd.DataFrame | None:
    if path is None:
        return None
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-doc", type=Path, required=True)
    parser.add_argument(
        "--signals-93", type=Path, default=Path("config/openap_93/signals_93.yaml")
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reproduction-summary", type=Path)
    parser.add_argument("--current-features", type=Path)
    parser.add_argument("--coverage-93", type=Path)
    parser.add_argument("--formula-inventory", type=Path)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission("OpenAP 181 completion audit")
    signal_doc = pd.read_csv(args.signal_doc)
    registry = load_signal_registry(args.signals_93)
    manifest = build_completion_manifest(signal_doc, registry_93=registry)
    manifest = attach_runtime_evidence(
        manifest,
        reproduction_summary=_read_frame(args.reproduction_summary),
        current_features=_read_frame(args.current_features),
        coverage_93=_read_frame(args.coverage_93),
        formula_inventory=_read_frame(args.formula_inventory),
    )
    write_completion_outputs(manifest, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

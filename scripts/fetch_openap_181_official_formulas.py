from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.completion import build_completion_manifest
from aurora.research.openap_181.official_formulas import (
    build_formula_inventory,
    fetch_predictor_sources,
    write_formula_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-doc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 official-formula inventory"
    )
    manifest = build_completion_manifest(pd.read_csv(args.signal_doc))
    sources = fetch_predictor_sources()
    inventory = build_formula_inventory(manifest["signal"], sources)
    write_formula_bundle(inventory, sources, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

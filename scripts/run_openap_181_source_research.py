from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.source_research import write_source_research_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--formula-inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 source research outputs"
    )
    write_source_research_outputs(
        pd.read_csv(args.manifest),
        pd.read_csv(args.formula_inventory),
        args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

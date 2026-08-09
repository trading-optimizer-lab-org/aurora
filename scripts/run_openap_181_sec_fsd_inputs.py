from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.sec_fsd_inputs import prepare_sec_fsd_batch_inputs


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 SEC FSD preparation"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-quarter", required=True)
    parser.add_argument("--end-quarter", required=True)
    parser.add_argument("--formation-start", required=True)
    parser.add_argument("--formation-end", required=True)
    args = parser.parse_args()
    prepare_sec_fsd_batch_inputs(
        args.zip_dir,
        pd.read_csv(args.source_manifest, low_memory=False),
        args.output_dir,
        start_quarter=args.start_quarter,
        end_quarter=args.end_quarter,
        formation_start=args.formation_start,
        formation_end=args.formation_end,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

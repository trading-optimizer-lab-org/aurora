from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.implementation_status import (
    write_implementation_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 implementation status"
    )
    evidence = pd.read_csv(args.evidence) if args.evidence is not None else None
    write_implementation_outputs(
        pd.read_csv(args.manifest),
        pd.read_csv(args.resolution),
        args.output_dir,
        evidence,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

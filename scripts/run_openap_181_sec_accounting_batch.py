from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.openap_181.sec_accounting_batch import (
    write_sec_accounting_batch_outputs,
)


def _read_table(path: Path) -> pd.DataFrame:
    separator = "\t" if path.suffix.lower() in {".txt", ".tsv"} else ","
    return pd.read_csv(path, sep=separator, low_memory=False)


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 181 SEC accounting batch"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--sub", type=Path, required=True)
    parser.add_argument("--tag", type=Path, required=True)
    parser.add_argument("--num", type=Path, required=True)
    parser.add_argument("--pre", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--formation-months", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence-run-url", required=True)
    parser.add_argument(
        "--evidence-artifact",
        default="openap-181-sec-accounting-batch",
    )
    parser.add_argument("--implementation-commit", required=True)
    args = parser.parse_args()
    formation = pd.read_csv(args.formation_months)
    if "formation_at" not in formation.columns or formation.empty:
        raise ValueError("Formation-month input requires a non-empty formation_at column")
    write_sec_accounting_batch_outputs(
        _read_table(args.sub),
        _read_table(args.tag),
        _read_table(args.num),
        _read_table(args.pre),
        _read_table(args.identity),
        formation["formation_at"],
        args.output_dir,
        evidence_run_url=args.evidence_run_url,
        evidence_artifact=args.evidence_artifact,
        implementation_commit=args.implementation_commit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

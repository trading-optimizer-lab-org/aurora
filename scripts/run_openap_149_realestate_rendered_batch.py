from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.realestate_rendered_batch import (
    run_rendered_realestate_sector_batch,
)


def _read_many(
    paths: list[Path],
    reader: Callable[[Path], pd.DataFrame],
) -> pd.DataFrame:
    return pd.concat([reader(path) for path in paths], ignore_index=True)


def _latest_retrieved_at(paths: list[Path]) -> str:
    timestamps = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        timestamps.append(pd.Timestamp(payload["retrieved_at"]))
    return max(timestamps).isoformat()


def _load_sec_lake(
    root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, dict[str, int]]:
    fact_paths = sorted(root.rglob("sec_companyfacts_*.parquet"))
    submission_paths = sorted(root.rglob("sec_submissions_*.parquet"))
    status_paths = sorted(root.rglob("sec_status_*.csv"))
    summary_paths = sorted(root.rglob("sec_summary_*.json"))
    counts = {
        "companyfacts": len(fact_paths),
        "submissions": len(submission_paths),
        "status": len(status_paths),
        "summary": len(summary_paths),
    }
    if set(counts.values()) != {48}:
        raise RuntimeError(f"Expected 48 complete SEC shards, found {counts}")
    return (
        _read_many(fact_paths, pd.read_parquet),
        _read_many(submission_paths, pd.read_parquet),
        _read_many(status_paths, pd.read_csv),
        _latest_retrieved_at(summary_paths),
        counts,
    )


def main() -> int:
    require_github_actions_or_explicit_local_permission(
        "OpenAP 149 rendered realestate sector batch"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-root", type=Path, required=True)
    parser.add_argument("--formation-at", required=True)
    parser.add_argument("--target-sic2", required=True)
    parser.add_argument("--anchor-cik", required=True)
    parser.add_argument("--minimum-issuers", type=int, default=5)
    parser.add_argument("--maximum-issuers", type=int, default=12)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    companyfacts, submissions, status, retrieved_at, counts = _load_sec_lake(
        args.sec_root
    )
    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    result = run_rendered_realestate_sector_batch(
        companyfacts,
        submissions,
        status,
        formation_at=args.formation_at,
        target_sic2=args.target_sic2,
        anchor_cik=args.anchor_cik,
        source_run_id=args.source_run_id,
        output_dir=output,
        minimum_issuers=args.minimum_issuers,
        maximum_issuers=args.maximum_issuers,
        retrieved_at=retrieved_at,
    )
    result["source_file_counts"] = counts
    result["source_layout"] = "48_verified_sec_official_api_shards"
    (output / "openap_149_realestate_summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

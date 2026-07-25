"""Collect safe, read-only GitHub Actions timing evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from aurora.infra.github_performance.github_api import (
    build_jobs_timeline,
    build_parallelism_timeline,
    build_runtime_breakdown,
    fetch_run_jobs,
    scope_jobs_to_current_invocation,
    summarize_timeline,
)
from aurora.infra.github_performance.preflight import load_github_yaml


def _atomic_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _write_parallelism_csv(table, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=table.schema.names)
        writer.writeheader()
        for row in table.to_pylist():
            writer.writerow(
                {
                    key: (
                        value.isoformat()
                        if hasattr(value, "isoformat")
                        else value
                    )
                    for key, value in row.items()
                }
            )
    temporary.replace(path)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(
    *,
    api_url: str,
    repository: str,
    run_id: int,
    token: str,
    spec_path: Path,
    output_dir: Path,
) -> tuple[Path, ...]:
    spec = load_github_yaml(spec_path)
    requested = int(spec["execution"]["requested_parallelism"])
    jobs = scope_jobs_to_current_invocation(
        fetch_run_jobs(
            api_url,
            repository,
            run_id,
            token,
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    job_table = build_jobs_timeline(jobs)
    parallelism = build_parallelism_timeline(jobs)
    runtime = build_runtime_breakdown(jobs)
    jobs_path = output_dir / "github_jobs_timeline.parquet"
    runtime_path = output_dir / "runtime_breakdown.parquet"
    parallelism_path = output_dir / "parallelism_timeline.csv"
    pq.write_table(job_table, jobs_path, compression="zstd", version="2.6")
    pq.write_table(runtime, runtime_path, compression="zstd", version="2.6")
    _write_parallelism_csv(parallelism, parallelism_path)
    summary_path = _atomic_json(
        output_dir / "timeline_summary.json",
        summarize_timeline(jobs, requested),
    )
    status_path = _atomic_json(
        output_dir / "performance_telemetry_status.json",
        {
            "schema_version": "1",
            "complete": True,
            "run_id": run_id,
            "repository": repository,
            "token_serialized": False,
        },
    )
    evidence = (
        jobs_path,
        runtime_path,
        parallelism_path,
        summary_path,
        status_path,
    )
    manifest_path = _atomic_json(
        output_dir / "performance_telemetry_manifest.json",
        {
            "schema_version": "1",
            "files": [
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in evidence
            ],
        },
    )
    return (
        *evidence,
        manifest_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL"))
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY"),
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=os.environ.get("GITHUB_RUN_ID"),
    )
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = args.output_dir.resolve()
    try:
        collect(
            api_url=str(args.api_url),
            repository=str(args.repository),
            run_id=int(args.run_id),
            token=str(args.token),
            spec_path=args.spec,
            output_dir=output_dir,
        )
    except Exception as error:
        _atomic_json(
            output_dir / "performance_telemetry_status.json",
            {
                "schema_version": "1",
                "complete": False,
                "error_type": type(error).__name__,
                "token_serialized": False,
            },
        )
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

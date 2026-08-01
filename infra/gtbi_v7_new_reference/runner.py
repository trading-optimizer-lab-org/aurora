"""Run and compare GTBI V7 logical workers on GitHub-hosted runners."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.run_gtbi_fast_strict_worker import run_worker

from .campaign import CAMPAIGN_ID, verify_v7_campaign_plan

try:
    import resource
except ImportError:  # pragma: no cover - Windows test hosts
    resource = None  # type: ignore[assignment]

NON_SCIENTIFIC_COLUMNS = {
    "seconds_total",
    "seconds_feature_build",
    "seconds_signal",
    "seconds_simulation",
    "seconds_train",
    "seconds_validation",
    "seconds_until_reject",
    "seconds_wall_candidate",
    "job_id",
}
SCIENTIFIC_KINDS = {
    "leaderboard",
    "filtered_leaderboard",
    "early_rejected_strategies",
    "timeout_strategies",
    "slow_deferred_strategies",
    "unsupported_strategies",
    "runtime_errors",
    "yearly_trade_performance",
    "symbol_entry_counts_by_year",
    "ticker_trade_summary",
    "dedupe_map",
    "top_indicator_rules",
    "top_trades_sample",
}
REQUIRED_SCIENTIFIC_KINDS = {
    "leaderboard",
    "filtered_leaderboard",
    "early_rejected_strategies",
    "timeout_strategies",
    "slow_deferred_strategies",
    "unsupported_strategies",
    "runtime_errors",
    "yearly_trade_performance",
    "dedupe_map",
    "top_indicator_rules",
    "top_trades_sample",
}
DETERMINISTIC_SYMBOL_WORKERS_PER_PROCESS = 1


class V7RunnerError(RuntimeError):
    """Raised when runner capacity or scientific equivalence fails."""


def effective_cpu_count() -> int:
    """Return effective Linux cgroup CPU capacity, bounded by os.cpu_count."""
    counts = [max(int(os.cpu_count() or 1), 1)]
    cpu_max = Path("/sys/fs/cgroup/cpu.max")
    if cpu_max.is_file():
        quota, period = cpu_max.read_text(encoding="utf-8").strip().split()[:2]
        if quota != "max" and int(period) > 0:
            counts.append(max(1, int(int(quota) / int(period))))
    cpuset = Path("/sys/fs/cgroup/cpuset.cpus.effective")
    if cpuset.is_file():
        ranges = cpuset.read_text(encoding="utf-8").strip()
        total = 0
        for part in filter(None, ranges.split(",")):
            if "-" in part:
                start, end = (int(value) for value in part.split("-", 1))
                total += end - start + 1
            else:
                total += 1
        if total:
            counts.append(total)
    return max(1, min(counts))


def _scientific_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".csv":
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            return []
        frame = frame.drop(columns=[column for column in NON_SCIENTIFIC_COLUMNS if column in frame.columns])
        return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise V7RunnerError(f"scientific JSONL row is not an object: {path}")
                records.append(dict(value))
    return records


def scientific_output_payload(output_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Return canonical scientific records, excluding runtime diagnostics."""
    output = Path(output_dir)
    payload: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.suffix not in {".csv", ".jsonl"}:
            continue
        kind = path.stem.rsplit("_job_", 1)[0].rsplit("_shard_", 1)[0]
        if kind not in SCIENTIFIC_KINDS:
            continue
        records = _scientific_records(path)
        records.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
        payload[kind] = records
    missing = sorted(REQUIRED_SCIENTIFIC_KINDS - set(payload))
    if missing:
        raise V7RunnerError(f"scientific output is incomplete: {', '.join(missing)}")
    return payload


def scientific_output_digest(output_dir: Path) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(scientific_output_payload(output_dir))).hexdigest()


def assert_scientific_outputs_equal(outputs: list[Path]) -> str:
    if len(outputs) < 2:
        raise V7RunnerError("at least two outputs are required for equivalence")
    payloads = [scientific_output_payload(Path(path)) for path in outputs]
    if any(payload != payloads[0] for payload in payloads[1:]):
        raise V7RunnerError("reference and V7 scientific outputs differ")
    return "sha256:" + hashlib.sha256(canonical_bytes(payloads[0])).hexdigest()


def run_v7_worker(
    *,
    campaign_manifest_path: Path,
    data_manifest_path: Path,
    plan_root: Path,
    data_pack_root: Path,
    authorization_path: Path,
    worker_id: int,
    output_dir: Path,
    symbol_workers: int,
) -> dict[str, Any]:
    """Run one logical V7 worker and add capacity/runtime evidence."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise V7RunnerError("GTBI V7 scientific workers are GitHub Actions only")
    cpu_count = effective_cpu_count()
    requested = int(symbol_workers)
    if requested not in {1, 2, 4}:
        raise V7RunnerError("symbol_workers must be one of 1, 2 or 4")
    if requested > cpu_count:
        raise V7RunnerError(f"requested {requested} workers but runner exposes {cpu_count} CPUs")
    verify_v7_campaign_plan(
        plan_root=Path(plan_root),
        authorization_path=Path(authorization_path),
        data_manifest_path=Path(data_manifest_path),
    )
    previous = os.environ.get("GTBI_SYMBOL_WORKERS")
    os.environ["GTBI_SYMBOL_WORKERS"] = str(requested)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    start_wall = time.perf_counter()
    start_times = os.times()
    try:
        summary = run_worker(
            campaign_manifest_path=Path(campaign_manifest_path),
            data_manifest_path=Path(data_manifest_path),
            plan_root=Path(plan_root),
            data_pack_root=Path(data_pack_root),
            worker_id=int(worker_id),
            output_dir=Path(output_dir),
        )
    finally:
        if previous is None:
            os.environ.pop("GTBI_SYMBOL_WORKERS", None)
        else:
            os.environ["GTBI_SYMBOL_WORKERS"] = previous
    end_times = os.times()
    wall = float(time.perf_counter() - start_wall)
    cpu_seconds = float((end_times.user + end_times.system) - (start_times.user + start_times.system))
    receipt = {
        "schema_version": "gtbi_v7_new_reference_worker_receipt_v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_fingerprint": summary["campaign_fingerprint"],
        "worker_id": int(worker_id),
        "symbol_workers": requested,
        "effective_cpu_count": cpu_count,
        "blas_threads_per_process": 1,
        "wall_seconds": wall,
        "cpu_seconds": cpu_seconds,
        "cpu_capacity_utilization": 0.0 if wall <= 0 else cpu_seconds / (wall * cpu_count),
        "peak_rss_kib": (
            int(getattr(resource, "getrusage")(getattr(resource, "RUSAGE_SELF")).ru_maxrss)
            if resource is not None
            else None
        ),
        "scientific_output_digest": scientific_output_digest(Path(output_dir)),
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_actions_only": True,
    }
    receipt["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    (Path(output_dir) / "v7_worker_receipt.json").write_bytes(canonical_bytes(receipt) + b"\n")
    return {**summary, "v7_worker_receipt": receipt}


def _run_v7_worker_process(kwargs: dict[str, Any]) -> dict[str, Any]:
    return run_v7_worker(**kwargs)


def run_v7_batch(
    *,
    campaign_manifest_path: Path,
    data_manifest_path: Path,
    plan_root: Path,
    data_pack_root: Path,
    authorization_path: Path,
    worker_ids: list[int],
    output_root: Path,
    processes_per_runner: int,
) -> dict[str, Any]:
    """Run up to four independent logical workers on one downloaded data pack."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise V7RunnerError("GTBI V7 scientific batches are GitHub Actions only")
    ids = [int(value) for value in worker_ids]
    if not ids or len(ids) > 4 or len(set(ids)) != len(ids):
        raise V7RunnerError("worker_ids must contain one to four unique values")
    processes = int(processes_per_runner)
    if processes not in {1, 2, 4}:
        raise V7RunnerError("processes_per_runner must be one of 1, 2 or 4")
    cpu_count = effective_cpu_count()
    if processes > cpu_count:
        raise V7RunnerError(f"requested {processes} processes but runner exposes {cpu_count} CPUs")
    # Parallelize independent logical workers with processes. Nested symbol
    # threads can change the final floating-point reduction by a few ulps,
    # while four independent processes already consume all runner CPUs.
    symbol_workers = DETERMINISTIC_SYMBOL_WORKERS_PER_PROCESS
    output = Path(output_root)
    if output.exists():
        raise V7RunnerError(f"batch output already exists: {output}")
    output.mkdir(parents=True)
    kwargs_by_id = {
        worker_id: {
            "campaign_manifest_path": Path(campaign_manifest_path),
            "data_manifest_path": Path(data_manifest_path),
            "plan_root": Path(plan_root),
            "data_pack_root": Path(data_pack_root),
            "authorization_path": Path(authorization_path),
            "worker_id": worker_id,
            "output_dir": output / f"worker-{worker_id:03d}",
            "symbol_workers": symbol_workers,
        }
        for worker_id in ids
    }
    start = time.perf_counter()
    results: dict[int, dict[str, Any]] = {}
    if processes == 1:
        for worker_id in ids:
            results[worker_id] = _run_v7_worker_process(kwargs_by_id[worker_id])
    else:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=processes, mp_context=context) as executor:
            futures = {
                executor.submit(_run_v7_worker_process, kwargs_by_id[worker_id]): worker_id
                for worker_id in ids
            }
            for future in as_completed(futures):
                worker_id = futures[future]
                results[worker_id] = future.result()
    wall = float(time.perf_counter() - start)
    if set(results) != set(ids):
        raise V7RunnerError("batch did not return every requested worker")
    receipts = [dict(results[worker_id]["v7_worker_receipt"]) for worker_id in ids]
    batch = {
        "schema_version": "gtbi_v7_new_reference_batch_receipt_v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_fingerprint": receipts[0]["campaign_fingerprint"],
        "worker_ids": ids,
        "processes_per_runner": processes,
        "symbol_workers_per_process": symbol_workers,
        "effective_cpu_count": cpu_count,
        "wall_seconds": wall,
        "aggregate_worker_cpu_seconds": sum(float(row["cpu_seconds"]) for row in receipts),
        "aggregate_peak_rss_kib": sum(int(row.get("peak_rss_kib") or 0) for row in receipts),
        "worker_scientific_digests": {
            str(row["worker_id"]): row["scientific_output_digest"] for row in receipts
        },
        "locked_authorized": False,
        "locked_data_accessed": False,
        "github_actions_only": True,
    }
    if any(row["campaign_fingerprint"] != batch["campaign_fingerprint"] for row in receipts):
        raise V7RunnerError("batch workers used different campaign fingerprints")
    batch["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(batch)).hexdigest()
    (output / "v7_batch_receipt.json").write_bytes(canonical_bytes(batch) + b"\n")
    return batch


def assert_batch_outputs_equal(batch_roots: list[Path]) -> dict[str, Any]:
    """Prove each logical worker is identical across 1/2/4 process modes."""
    if len(batch_roots) < 2:
        raise V7RunnerError("at least two batch roots are required")
    memberships = []
    for root in batch_roots:
        memberships.append(
            {path.name: path for path in Path(root).glob("worker-*") if path.is_dir()}
        )
    expected = set(memberships[0])
    if not expected or any(set(membership) != expected for membership in memberships[1:]):
        raise V7RunnerError("benchmark batch worker membership differs")
    digests: dict[str, str] = {}
    for worker_name in sorted(expected):
        digests[worker_name] = assert_scientific_outputs_equal(
            [membership[worker_name] for membership in memberships]
        )
    return {"equivalent": True, "worker_scientific_digests": digests}


__all__ = [
    "V7RunnerError",
    "assert_scientific_outputs_equal",
    "assert_batch_outputs_equal",
    "effective_cpu_count",
    "run_v7_batch",
    "run_v7_worker",
    "scientific_output_digest",
    "scientific_output_payload",
]

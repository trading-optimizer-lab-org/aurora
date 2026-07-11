"""Run one provenance-bound GTBI V6 worker in a single persistent process."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import global_technical_buy_indicator as gtbi


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def create_data_pack_manifest(
    *,
    data_pack_root: Path,
    output_path: Path,
    source_data_run_id: str,
    source_artifact_name: str,
    universe_identity: str,
    train_end: str,
    validation_start: str,
    validation_end: str,
    locked_start: str,
) -> dict[str, Any]:
    root = Path(data_pack_root)
    if not root.is_dir():
        raise FileNotFoundError(f"data pack directory not found: {root}")
    files = [_file_record(path, root) for path in sorted(root.rglob("*")) if path.is_file()]
    if not files:
        raise ValueError("data pack contains no files")
    identity_payload = {
        "source_data_run_id": str(source_data_run_id),
        "source_artifact_name": str(source_artifact_name),
        "universe_identity": str(universe_identity),
        "train_end": str(train_end),
        "validation_start": str(validation_start),
        "validation_end": str(validation_end),
        "locked_start": str(locked_start),
        "files": files,
    }
    manifest = {
        **identity_payload,
        "data_pack_identity": hashlib.sha256(_canonical_json(identity_payload)).hexdigest(),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _verify_records(root: Path, records: list[dict[str, Any]]) -> None:
    for record in records:
        relative = Path(str(record.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"invalid manifest path: {relative}")
        path = root / relative
        if not path.is_file():
            raise ValueError(f"manifest file is missing: {relative.as_posix()}")
        actual = _file_record(path, root)
        if (
            actual["sha256"] != str(record.get("sha256") or "")
            or actual["size_bytes"] != int(record.get("size_bytes", -1))
        ):
            raise ValueError(f"digest mismatch for {relative.as_posix()}")


def _worker_group_count(worker_manifest_path: Path, worker_id: int) -> int:
    with Path(worker_manifest_path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return sum(int(row.get("worker_id", -1)) == int(worker_id) for row in rows)


def _summary_count(summary: dict[str, Any], key: str) -> int:
    alternatives = {
        "evaluated": ("total_strategies_evaluated", "strategies_evaluated"),
        "early": ("total_strategies_early_rejected", "strategies_early_rejected"),
        "timeout": ("total_strategies_timed_out", "strategies_timed_out"),
        "runtime": ("total_strategies_runtime_error", "strategies_runtime_error"),
        "unsupported": ("total_strategies_unsupported", "strategies_unsupported"),
        "deferred": ("total_strategies_slow_deferred", "strategies_slow_deferred"),
    }
    return int(next((summary.get(name, 0) for name in alternatives[key] if name in summary), 0) or 0)


def run_worker(
    *,
    campaign_manifest_path: Path,
    data_manifest_path: Path,
    plan_root: Path,
    data_pack_root: Path,
    worker_id: int,
    output_dir: Path,
) -> dict[str, Any]:
    plan = Path(plan_root)
    data_root = Path(data_pack_root)
    output = Path(output_dir)
    if output.is_file() or (output.exists() and any(path.is_file() for path in output.rglob("*"))):
        raise ValueError(f"output directory already contains files: {output}")
    campaign = _load_json(Path(campaign_manifest_path))
    fingerprint = str(campaign.get("campaign_fingerprint") or "")
    if not fingerprint:
        raise ValueError("campaign manifest has no fingerprint")
    data_manifest = _load_json(Path(data_manifest_path))
    expected_data_identity = str(campaign.get("inputs", {}).get("data_run_identity") or "")
    if str(data_manifest.get("data_pack_identity") or "") != expected_data_identity:
        raise ValueError("data pack identity does not match campaign")
    _verify_records(data_root, list(data_manifest.get("files") or []))

    shard_relative = Path("canonical_pack") / f"strategies_shard_{int(worker_id):03d}.jsonl"
    artifact_records = {
        str(record.get("path")): record for record in list(campaign.get("artifacts") or [])
    }
    shard_record = artifact_records.get(shard_relative.as_posix())
    if shard_record is None:
        raise ValueError(f"campaign has no canonical shard record for worker {worker_id}")
    _verify_records(plan, [shard_record])
    canonical_count = _worker_group_count(plan / "worker_manifest.csv", int(worker_id))
    if canonical_count <= 0:
        raise ValueError(f"worker {worker_id} has no canonical groups")

    inputs = dict(campaign.get("inputs") or {})
    output.mkdir(parents=True, exist_ok=True)
    summary = gtbi.run_external_strategy_pack_shard(
        data_lake_root=data_root,
        external_strategy_pack_path=plan / shard_relative,
        output_dir=output,
        prebuilt_pack_dir=data_root,
        external_strategy_shard_id=int(worker_id),
        external_strategy_offset=0,
        external_strategy_limit=canonical_count,
        external_strategy_format="jsonl",
        external_strategy_fail_on_unsupported=True,
        candidate_timeout_seconds=0,
        min_market_cap=float(inputs["min_market_cap"]),
        locked_start=str(inputs["locked_start"]),
        train_end=str(inputs["train_end"]),
        validation_start=str(inputs["validation_start"]),
        validation_end=str(inputs["validation_end"]),
        optimized_evaluation_mode=str(inputs["execution_mode"]),
        enable_feature_cache=True,
        enable_dedupe=True,
        enable_safe_prefilter=False,
        enable_early_stopping=False,
        enable_cost_scheduling=False,
        job_wall_clock_seconds=0,
        schedule_active_jobs=360,
        signal_first_phase="combined",
    )
    failures = {
        "timeout": _summary_count(summary, "timeout"),
        "runtime": _summary_count(summary, "runtime"),
        "unsupported": _summary_count(summary, "unsupported"),
        "deferred": _summary_count(summary, "deferred"),
    }
    if any(failures.values()):
        raise ValueError(f"worker {worker_id} has nonzero failure counts: {failures}")
    terminal = _summary_count(summary, "evaluated") + _summary_count(summary, "early")
    if terminal != canonical_count:
        raise ValueError(
            f"worker {worker_id} terminal count {terminal} differs from canonical count {canonical_count}"
        )
    summary.update(
        {
            "campaign_fingerprint": fingerprint,
            "worker_id": int(worker_id),
            "canonical_group_count": int(canonical_count),
            "signal_first_phase": "combined",
            "enable_safe_prefilter": False,
            "enable_early_stopping": False,
            "candidate_timeout_seconds": 0,
        }
    )
    (output / "worker_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "campaign_manifest.json").write_text(
        Path(campaign_manifest_path).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--data-pack-root", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--source-data-run-id", required=True)
    manifest.add_argument("--source-artifact-name", required=True)
    manifest.add_argument("--universe-identity", required=True)
    manifest.add_argument("--train-end", default="2010-12-31")
    manifest.add_argument("--validation-start", default="2011-01-01")
    manifest.add_argument("--validation-end", default="2020-12-31")
    manifest.add_argument("--locked-start", default="2021-01-01")
    run = subparsers.add_parser("run")
    run.add_argument("--campaign-manifest", type=Path, required=True)
    run.add_argument("--data-manifest", type=Path, required=True)
    run.add_argument("--plan-root", type=Path, required=True)
    run.add_argument("--data-pack-root", type=Path, required=True)
    run.add_argument("--worker-id", type=int, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "manifest":
        payload = create_data_pack_manifest(
            data_pack_root=args.data_pack_root,
            output_path=args.output,
            source_data_run_id=args.source_data_run_id,
            source_artifact_name=args.source_artifact_name,
            universe_identity=args.universe_identity,
            train_end=args.train_end,
            validation_start=args.validation_start,
            validation_end=args.validation_end,
            locked_start=args.locked_start,
        )
    else:
        payload = run_worker(
            campaign_manifest_path=args.campaign_manifest,
            data_manifest_path=args.data_manifest,
            plan_root=args.plan_root,
            data_pack_root=args.data_pack_root,
            worker_id=args.worker_id,
            output_dir=args.output_dir,
        )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

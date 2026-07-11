"""Run one provenance-bound GTBI V6 worker in a single persistent process."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from scripts import global_technical_buy_indicator as gtbi
from scripts import gtbi_fast_strict as strict


_DATA_IDENTITY_FIELDS = (
    "source_data_run_id",
    "source_artifact_name",
    "universe_identity",
    "train_end",
    "validation_start",
    "validation_end",
    "locked_start",
    "min_market_cap",
)
_REQUIRED_CAMPAIGN_INPUTS = (
    "code_sha",
    "strategy_pack_digest",
    "data_run_identity",
    "train_end",
    "validation_start",
    "validation_end",
    "locked_start",
    "min_market_cap",
    "execution_mode",
    "universe_identity",
    "dependency_lock_identity",
)
_STRICT_DATES = {
    "train_end": strict.DEFAULT_TRAIN_END,
    "validation_start": strict.DEFAULT_VALIDATION_START,
    "validation_end": strict.DEFAULT_VALIDATION_END,
    "locked_start": strict.DEFAULT_LOCKED_START,
}


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
    min_market_cap: int | float = strict.DEFAULT_MIN_MARKET_CAP,
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
        "min_market_cap": min_market_cap,
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
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return dict(value)


def _relative_manifest_path(record: dict[str, Any]) -> Path:
    relative = Path(str(record.get("path") or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid manifest path: {relative}")
    return relative


def _verify_records(root: Path, records: list[dict[str, Any]]) -> None:
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("manifest record must be an object")
        relative = _relative_manifest_path(record)
        path = root / relative
        if not path.is_file():
            raise ValueError(f"manifest file is missing: {relative.as_posix()}")
        actual = _file_record(path, root)
        try:
            expected_size = int(record.get("size_bytes", -1))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid manifest size for {relative.as_posix()}") from error
        if (
            actual["sha256"] != str(record.get("sha256") or "")
            or actual["size_bytes"] != expected_size
        ):
            raise ValueError(f"digest mismatch for {relative.as_posix()}")


def _data_identity_payload(data_manifest: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in _DATA_IDENTITY_FIELDS if field not in data_manifest]
    if missing:
        raise ValueError(f"data manifest is missing identity fields: {', '.join(missing)}")
    files = data_manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("data manifest has no files")
    if any(not isinstance(record, dict) for record in files):
        raise ValueError("data manifest records must be objects")
    return {field: data_manifest[field] for field in _DATA_IDENTITY_FIELDS} | {"files": files}


def _verify_data_manifest(data_manifest: dict[str, Any], data_root: Path) -> str:
    identity_payload = _data_identity_payload(data_manifest)
    expected_identity = hashlib.sha256(_canonical_json(identity_payload)).hexdigest()
    if str(data_manifest.get("data_pack_identity") or "") != expected_identity:
        raise ValueError("data pack identity does not match manifest content")
    _verify_records(data_root, list(identity_payload["files"]))
    return expected_identity


def _verify_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    inputs = campaign.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("campaign manifest has no inputs")
    missing = [field for field in _REQUIRED_CAMPAIGN_INPUTS if field not in inputs]
    if missing:
        raise ValueError(f"campaign manifest is missing inputs: {', '.join(missing)}")
    fingerprint = str(campaign.get("campaign_fingerprint") or "")
    if not fingerprint:
        raise ValueError("campaign manifest has no fingerprint")
    artifact_inventory = campaign.get("artifacts")
    if not isinstance(artifact_inventory, list):
        raise ValueError("campaign manifest has no artifact inventory")
    plan_content = campaign.get("plan_content")
    if not isinstance(plan_content, dict):
        raise ValueError("campaign manifest has no plan content")
    fingerprint_inputs = {field: inputs[field] for field in _REQUIRED_CAMPAIGN_INPUTS}
    if (
        strict.campaign_fingerprint(
            **fingerprint_inputs,
            artifact_inventory=artifact_inventory,
            plan_content=plan_content,
        )
        != fingerprint
    ):
        raise ValueError("campaign fingerprint does not match campaign inputs")
    for field, expected in _STRICT_DATES.items():
        if str(inputs[field]) != expected:
            raise ValueError(f"{field} must remain {expected}")
    if str(inputs["validation_end"]) >= str(inputs["locked_start"]):
        raise ValueError("validation_end must be before locked_start")
    return fingerprint_inputs


def _verify_data_campaign_binding(data_manifest: dict[str, Any], inputs: dict[str, Any]) -> None:
    for field in ("universe_identity", "train_end", "validation_start", "validation_end", "locked_start"):
        if str(data_manifest[field]) != str(inputs[field]):
            raise ValueError(f"data manifest {field} does not match campaign")
    try:
        data_min_market_cap = float(data_manifest["min_market_cap"])
        campaign_min_market_cap = float(inputs["min_market_cap"])
    except (TypeError, ValueError) as error:
        raise ValueError("min_market_cap must be numeric") from error
    if data_min_market_cap != campaign_min_market_cap:
        raise ValueError("data manifest min_market_cap does not match campaign")


def _date_columns(path: Path) -> list[str]:
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq

        columns = pq.ParquetFile(path).schema.names
    elif path.suffix.lower() == ".csv":
        columns = list(pd.read_csv(path, nrows=0).columns)
    else:
        return []
    return [column for column in columns if str(column).strip().lower() in {"date", "datetime", "timestamp"}]


def _verify_prepared_data_bounds(data_root: Path, locked_start: str) -> None:
    boundary = pd.Timestamp(locked_start, tz="UTC")
    for path in sorted(data_root.rglob("*")):
        if not path.is_file():
            continue
        columns = _date_columns(path)
        if not columns:
            continue
        try:
            if path.suffix.lower() == ".parquet":
                frame = pd.read_parquet(path, columns=columns)
            else:
                frame = pd.read_csv(path, usecols=columns)
        except Exception as error:
            raise ValueError(f"cannot inspect prepared data bounds in {path.name}") from error
        for column in columns:
            dates = pd.to_datetime(frame[column], errors="coerce", utc=True)
            if bool((dates >= boundary).fillna(False).any()):
                raise ValueError(f"prepared data {path.name} exposes a row at or after locked_start")


def _artifact_records(campaign: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = campaign.get("artifacts")
    if not isinstance(records, list):
        raise ValueError("campaign manifest has no artifact records")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("campaign artifact record must be an object")
        key = _relative_manifest_path(record).as_posix()
        if key in result:
            raise ValueError(f"duplicate campaign artifact record: {key}")
        result[key] = record
    return result


def _read_csv_rows(path: Path, required_columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        actual_columns = set(reader.fieldnames or ())
        missing = [column for column in required_columns if column not in actual_columns]
        if missing:
            raise ValueError(f"{path.name} is missing columns: {', '.join(missing)}")
        return list(reader)


def _verify_plan_coherence(
    *,
    plan: Path,
    worker_id: int,
    shard_relative: Path,
    artifact_records: dict[str, dict[str, Any]],
) -> tuple[int, list[str]]:
    required_paths = ("worker_manifest.csv", "alias_map.csv", shard_relative.as_posix())
    for relative in required_paths:
        record = artifact_records.get(relative)
        if record is None:
            raise ValueError(f"campaign has no artifact record for {relative}")
        _verify_records(plan, [record])

    worker_rows = _read_csv_rows(
        plan / "worker_manifest.csv",
        ("evaluation_hash", "canonical_strategy_id", "worker_id"),
    )
    selected_rows = [row for row in worker_rows if str(row.get("worker_id")) == str(worker_id)]
    if not selected_rows:
        raise ValueError(f"worker {worker_id} has no canonical groups")
    canonical_ids = [str(row["canonical_strategy_id"]) for row in selected_rows]
    if any(not strategy_id.strip() for strategy_id in canonical_ids) or len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError("worker manifest has invalid canonical strategy identities")
    canonical_hashes = {str(row["canonical_strategy_id"]): str(row["evaluation_hash"]) for row in selected_rows}

    shard_ids: list[str] = []
    with (plan / shard_relative).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"canonical shard has a blank row at {line_number}")
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"canonical shard has invalid JSON at row {line_number}") from error
            if not isinstance(payload, dict) or int(payload.get("shard_id", -1)) != worker_id:
                raise ValueError(f"canonical shard row {line_number} is not bound to worker {worker_id}")
            strategy_id = str(payload.get("strategy_id") or "")
            if not strategy_id:
                raise ValueError(f"canonical shard row {line_number} has no strategy_id")
            shard_ids.append(strategy_id)
    if len(shard_ids) != len(canonical_ids) or set(shard_ids) != set(canonical_ids):
        raise ValueError("canonical shard does not match worker manifest")

    aliases = _read_csv_rows(
        plan / "alias_map.csv",
        ("strategy_id", "evaluation_hash", "canonical_strategy_id", "worker_id"),
    )
    worker_aliases = [row for row in aliases if str(row.get("worker_id")) == str(worker_id)]
    if not worker_aliases:
        raise ValueError(f"alias map has no records for worker {worker_id}")
    alias_ids = [str(row["strategy_id"]) for row in worker_aliases]
    if any(not strategy_id.strip() for strategy_id in alias_ids) or len(set(alias_ids)) != len(alias_ids):
        raise ValueError("alias map has invalid strategy identities")
    for row in worker_aliases:
        canonical_id = str(row["canonical_strategy_id"])
        if canonical_hashes.get(canonical_id) != str(row["evaluation_hash"]):
            raise ValueError("alias map does not match worker manifest")
    if set(str(row["canonical_strategy_id"]) for row in worker_aliases) != set(canonical_ids):
        raise ValueError("alias map does not cover every canonical strategy")
    return len(canonical_ids), canonical_ids


def _worker_output_records(output_dir: Path) -> list[dict[str, Any]]:
    return [
        _file_record(path, output_dir)
        for path in sorted(output_dir.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name != "worker_manifest.json"
    ]


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
    value = next((summary[name] for name in alternatives[key] if name in summary), None)
    if value is None:
        raise ValueError(f"missing strict count: {key}")
    if isinstance(value, bool):
        raise ValueError(f"invalid strict count: {key}")
    try:
        count = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid strict count: {key}") from error
    if count < 0 or count != value:
        raise ValueError(f"invalid strict count: {key}")
    return count


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
    inputs = _verify_campaign(campaign)
    fingerprint = str(campaign["campaign_fingerprint"])
    data_manifest = _load_json(Path(data_manifest_path))
    data_pack_identity = _verify_data_manifest(data_manifest, data_root)
    if data_pack_identity != str(inputs["data_run_identity"]):
        raise ValueError("data pack identity does not match campaign")
    _verify_data_campaign_binding(data_manifest, inputs)
    _verify_prepared_data_bounds(data_root, str(inputs["locked_start"]))

    shard_relative = Path("canonical_pack") / f"strategies_shard_{int(worker_id):03d}.jsonl"
    artifact_records = _artifact_records(campaign)
    canonical_count, canonical_ids = _verify_plan_coherence(
        plan=plan,
        worker_id=int(worker_id),
        shard_relative=shard_relative,
        artifact_records=artifact_records,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.rmdir()
    temporary_output = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        summary = gtbi.run_external_strategy_pack_shard(
            data_lake_root=data_root,
            external_strategy_pack_path=plan / shard_relative,
            output_dir=temporary_output,
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
        if not isinstance(summary, dict):
            raise ValueError("worker evaluator returned a non-object summary")
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
                "job_wall_clock_seconds": 0,
            }
        )
        (temporary_output / "worker_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary_output / "campaign_manifest.json").write_text(
            Path(campaign_manifest_path).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (temporary_output / "worker_manifest.json").write_text(
            json.dumps(
                {
                    "worker_id": int(worker_id),
                    "campaign_fingerprint": fingerprint,
                    "canonical_ids": canonical_ids,
                    "files": _worker_output_records(temporary_output),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_output.replace(output)
        return summary
    except Exception:
        shutil.rmtree(temporary_output, ignore_errors=True)
        raise


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
    manifest.add_argument("--min-market-cap", type=float, default=strict.DEFAULT_MIN_MARKET_CAP)
    run = subparsers.add_parser("run")
    run.add_argument("--campaign-manifest", type=Path, required=True)
    run.add_argument("--data-manifest", type=Path, required=True)
    run.add_argument("--plan-root", type=Path, required=True)
    run.add_argument("--data-pack-root", type=Path, required=True)
    run.add_argument("--worker-id", type=int, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    return parser


def require_github_actions_or_explicit_local_permission() -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return
    if os.environ.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == "USER_REQUESTED_LOCAL_RUN_THIS_TURN":
        return
    raise SystemExit(
        "GTBI fast strict worker runs are GitHub-only. "
        "Set AURORA_ALLOW_LOCAL_RUNS_EXPLICIT=USER_REQUESTED_LOCAL_RUN_THIS_TURN "
        "only for tiny local smoke tests explicitly requested in the current turn."
    )


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
            min_market_cap=args.min_market_cap,
        )
    else:
        require_github_actions_or_explicit_local_permission()
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

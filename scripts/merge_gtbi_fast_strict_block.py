"""Strictly merge one fixed GTBI worker block with provenance validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from scripts.gtbi_fast_strict import campaign_fingerprint


WORKER_FILE_RE = re.compile(
    r"^(?P<kind>.+)_(?:job|shard)_\d+\.(?P<extension>csv|jsonl|json|parquet)$"
)
FAILURE_KINDS = {
    "timeout_strategies",
    "slow_deferred_strategies",
    "unsupported_strategies",
    "runtime_errors",
}
TERMINAL_ID_COLUMNS = {
    "leaderboard": "candidate_id",
    "early_rejected_strategies": "strategy_id",
}
PARQUET_INTERMEDIATE_ROWS = 100_000
POST_MANIFEST_AUDIT_FILES = {"v7_worker_receipt.json"}


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return dict(value)


def _stream_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _stream_digest(path),
        "size_bytes": path.stat().st_size,
    }


def _summary_count(summary: dict[str, Any], name: str) -> int:
    alternatives = {
        "evaluated": ("total_strategies_evaluated", "strategies_evaluated"),
        "early": ("total_strategies_early_rejected", "strategies_early_rejected"),
        "timeout": ("total_strategies_timed_out", "strategies_timed_out"),
        "runtime": ("total_strategies_runtime_error", "strategies_runtime_error"),
        "unsupported": ("total_strategies_unsupported", "strategies_unsupported"),
        "deferred": ("total_strategies_slow_deferred", "strategies_slow_deferred"),
    }
    return int(next((summary.get(key, 0) for key in alternatives[name] if key in summary), 0) or 0)


def _read_csv(path: Path) -> pd.DataFrame:
    if path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _json_records(value: Any, path: Path) -> list[dict[str, Any]]:
    records = value if isinstance(value, list) else [value]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"JSON records must be objects: {path}")
    return [dict(record) for record in records]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSONL in {path}:{line_number}") from error
            if not isinstance(value, dict):
                raise ValueError(f"JSONL record must be an object: {path}:{line_number}")
            records.append(dict(value))
    return records


def _validated_relative_path(value: Any) -> Path:
    relative = Path(str(value or ""))
    if not str(value or "") or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid manifest path: {value}")
    return relative


def _verify_optional_v7_worker_receipt(
    *,
    worker_root: Path,
    worker_id: int,
    fingerprint: str,
) -> None:
    """Verify the V7 audit receipt written after the scientific manifest."""
    path = worker_root / "v7_worker_receipt.json"
    if not path.is_file():
        return
    receipt = _json(path)
    supplied_digest = str(receipt.pop("receipt_digest", ""))
    expected_digest = "sha256:" + hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    if supplied_digest != expected_digest:
        raise ValueError(f"worker {worker_id} V7 receipt digest mismatch")
    if (
        receipt.get("schema_version") != "gtbi_v7_new_reference_worker_receipt_v1"
        or int(receipt.get("worker_id", -1)) != worker_id
        or str(receipt.get("campaign_fingerprint") or "") != fingerprint
        or receipt.get("python_hash_seed") != "0"
        or receipt.get("locked_authorized") is not False
        or receipt.get("locked_data_accessed") is not False
        or receipt.get("github_actions_only") is not True
    ):
        raise ValueError(f"worker {worker_id} V7 receipt contract mismatch")


def _verify_worker_manifest(
    *,
    worker_root: Path,
    worker_id: int,
    fingerprint: str,
    canonical_count: int,
) -> tuple[dict[str, Any], list[str]]:
    manifest_path = worker_root / "worker_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"worker {worker_id} has no worker manifest")
    manifest = _json(manifest_path)
    if int(manifest.get("worker_id", -1)) != worker_id:
        raise ValueError(f"worker manifest ID mismatch for worker {worker_id}")
    if str(manifest.get("campaign_fingerprint") or "") != fingerprint:
        raise ValueError(f"worker manifest campaign fingerprint mismatch for worker {worker_id}")
    raw_ids = manifest.get("canonical_ids")
    if not isinstance(raw_ids, list):
        raise ValueError(f"worker {worker_id} manifest has no canonical IDs")
    canonical_ids = [str(value) for value in raw_ids]
    if any(not value.strip() for value in canonical_ids) or len(set(canonical_ids)) != len(canonical_ids):
        raise ValueError(f"worker {worker_id} manifest has duplicate or empty canonical IDs")
    if len(canonical_ids) != canonical_count:
        raise ValueError(f"worker {worker_id} manifest canonical IDs differ from summary count")

    _verify_optional_v7_worker_receipt(
        worker_root=worker_root,
        worker_id=worker_id,
        fingerprint=fingerprint,
    )

    raw_records = manifest.get("files")
    if not isinstance(raw_records, list):
        raise ValueError(f"worker {worker_id} manifest has no file records")
    records: dict[Path, dict[str, Any]] = {}
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            raise ValueError(f"invalid file record in worker {worker_id} manifest")
        relative = _validated_relative_path(raw_record.get("path"))
        if relative in records:
            raise ValueError(f"duplicate file record for {relative.as_posix()}")
        records[relative] = raw_record
    expected_paths = {
        path.relative_to(worker_root)
        for path in worker_root.iterdir()
        if path.is_file()
        and path.name != "worker_manifest.json"
        and path.name not in POST_MANIFEST_AUDIT_FILES
    }
    if set(records) != expected_paths:
        raise ValueError(f"worker {worker_id} manifest file membership mismatch")
    for relative, record in records.items():
        path = worker_root / relative
        if not path.is_file():
            raise ValueError(f"manifest file is missing: {relative.as_posix()}")
        if (
            _stream_digest(path) != str(record.get("sha256") or "")
            or path.stat().st_size != int(record.get("size_bytes", -1))
        ):
            raise ValueError(f"digest mismatch for {relative.as_posix()}")
    return manifest, canonical_ids


def _validated_campaign(campaign_path: Path) -> tuple[dict[str, Any], str]:
    campaign = _json(campaign_path)
    fingerprint = str(campaign.get("campaign_fingerprint") or "")
    inputs = campaign.get("inputs")
    if not fingerprint or not isinstance(inputs, dict):
        raise ValueError(f"campaign manifest is incomplete: {campaign_path}")
    artifacts = campaign.get("artifacts")
    plan_content = campaign.get("plan_content")
    if artifacts is not None and not isinstance(artifacts, list):
        raise ValueError(f"campaign manifest artifact inventory is invalid: {campaign_path}")
    if plan_content is not None and not isinstance(plan_content, dict):
        raise ValueError(f"campaign manifest plan content is invalid: {campaign_path}")
    try:
        recomputed = campaign_fingerprint(
            **inputs,
            artifact_inventory=artifacts,
            plan_content=plan_content,
        )
    except TypeError as error:
        raise ValueError(f"campaign manifest inputs are invalid: {campaign_path}") from error
    if fingerprint != recomputed:
        raise ValueError(f"campaign fingerprint does not match inputs: {campaign_path}")
    return campaign, fingerprint


def _terminal_ids(kind: str, frame: pd.DataFrame, worker_id: int) -> list[str]:
    column = TERMINAL_ID_COLUMNS.get(kind)
    if column is None or frame.empty:
        return []
    if column not in frame.columns:
        raise ValueError(f"worker {worker_id} {kind} has no {column} column")
    ids = frame[column].dropna().astype(str).tolist()
    if len(ids) != len(frame) or any(not value.strip() for value in ids):
        raise ValueError(f"worker {worker_id} {kind} has an empty terminal ID")
    return ids


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_streaming(source: Path, destination: Path) -> None:
    with source.open("rb") as input_handle, destination.open("wb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)


def merge_block(
    *,
    input_root: Path,
    output_dir: Path,
    block_id: int,
    expected_worker_ids: list[int],
) -> dict[str, Any]:
    """Validate and atomically merge an exact, provenance-bound worker block."""
    source = Path(input_root)
    output = Path(output_dir)
    if not source.is_dir():
        raise FileNotFoundError(f"input directory not found: {source}")
    if output.exists():
        raise ValueError(f"output path already exists: {output}")
    expected = sorted(int(worker_id) for worker_id in expected_worker_ids)
    if not expected or len(set(expected)) != len(expected):
        raise ValueError("expected worker IDs must be a non-empty unique set")

    workers: dict[int, tuple[Path, dict[str, Any], dict[str, Any], list[str], str]] = {}
    fingerprints: set[str] = set()
    for summary_path in sorted(source.rglob("worker_summary.json")):
        summary = _json(summary_path)
        worker_id = int(summary.get("worker_id", -1))
        if worker_id in workers:
            raise ValueError(f"duplicate worker summary for worker {worker_id}")
        worker_root = summary_path.parent
        campaign_path = worker_root / "campaign_manifest.json"
        if not campaign_path.is_file():
            raise ValueError(f"worker {worker_id} has no campaign manifest")
        _, fingerprint = _validated_campaign(campaign_path)
        if str(summary.get("campaign_fingerprint") or "") != fingerprint:
            raise ValueError(f"campaign fingerprint mismatch inside worker {worker_id}")
        canonical_count = int(summary.get("canonical_group_count", 0) or 0)
        terminal_count = _summary_count(summary, "evaluated") + _summary_count(summary, "early")
        if canonical_count <= 0 or terminal_count != canonical_count:
            raise ValueError(
                f"worker {worker_id} terminal count {terminal_count} differs from canonical count {canonical_count}"
            )
        worker_manifest, canonical_ids = _verify_worker_manifest(
            worker_root=worker_root,
            worker_id=worker_id,
            fingerprint=fingerprint,
            canonical_count=canonical_count,
        )
        workers[worker_id] = (worker_root, summary, worker_manifest, canonical_ids, fingerprint)
        fingerprints.add(fingerprint)

    actual = sorted(workers)
    if actual != expected:
        raise ValueError(f"worker membership mismatch: expected={expected} actual={actual}")
    if len(fingerprints) != 1:
        raise ValueError(f"campaign fingerprint mismatch across block: {sorted(fingerprints)}")
    fingerprint = next(iter(fingerprints))

    tables: dict[str, list[pd.DataFrame]] = {}
    json_values: dict[str, list[Any]] = {}
    jsonl_records: dict[str, list[dict[str, Any]]] = {}
    all_canonical_ids: set[str] = set()
    canonical_total = 0
    evaluated_count = 0
    early_count = 0
    for worker_id in expected:
        worker_root, summary, _, canonical_ids, _ = workers[worker_id]
        failures = {
            key: _summary_count(summary, key)
            for key in ("timeout", "runtime", "unsupported", "deferred")
        }
        if any(failures.values()):
            raise ValueError(f"worker {worker_id} has failure counts: {failures}")
        duplicate_ids = all_canonical_ids.intersection(canonical_ids)
        if duplicate_ids:
            raise ValueError(f"duplicate canonical strategy ID: {sorted(duplicate_ids)[0]}")
        all_canonical_ids.update(canonical_ids)
        canonical_total += len(canonical_ids)

        worker_terminal_ids: list[str] = []
        for path in sorted(worker_root.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            match = WORKER_FILE_RE.match(path.name)
            if match is None:
                continue
            kind = str(match.group("kind"))
            extension = str(match.group("extension"))
            if extension == "csv":
                frame = _read_csv(path)
                tables.setdefault(kind, []).append(frame)
            elif extension == "parquet":
                frame = pd.read_parquet(path)
                tables.setdefault(kind, []).append(frame)
            elif extension == "json":
                value = json.loads(path.read_text(encoding="utf-8"))
                frame = pd.DataFrame(_json_records(value, path))
                json_values.setdefault(kind, []).append(value)
            else:
                records = _read_jsonl(path)
                frame = pd.DataFrame(records)
                jsonl_records.setdefault(kind, []).extend(records)
            if kind in FAILURE_KINDS and not frame.empty:
                raise ValueError(f"worker {worker_id} contains failure rows in {kind}")
            ids = _terminal_ids(kind, frame, worker_id)
            worker_terminal_ids.extend(ids)
            if kind == "leaderboard":
                evaluated_count += len(ids)
            elif kind == "early_rejected_strategies":
                early_count += len(ids)
        if len(set(worker_terminal_ids)) != len(worker_terminal_ids):
            raise ValueError(f"duplicate canonical strategy ID in worker {worker_id}")
        if set(worker_terminal_ids) != set(canonical_ids):
            raise ValueError(f"worker {worker_id} terminal canonical IDs differ from manifest")

    if evaluated_count + early_count != canonical_total:
        raise ValueError("block terminal row count differs from canonical total")

    block_padded = f"{int(block_id):02d}"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.merge-", dir=output.parent))
    try:
        written: list[Path] = []
        row_counts: dict[str, int] = {}
        intermediate = temporary / ".intermediate"
        for kind in sorted(tables):
            frames = tables[kind]
            columns = next((list(frame.columns) for frame in frames if len(frame.columns)), [])
            combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(columns=columns)
            path = temporary / f"{kind}_job_block_{block_padded}.csv"
            if len(combined) >= PARQUET_INTERMEDIATE_ROWS:
                intermediate.mkdir(exist_ok=True)
                parquet_path = intermediate / f"{kind}.parquet"
                combined.to_parquet(parquet_path, index=False)
                pd.read_parquet(parquet_path).to_csv(path, index=False)
            else:
                combined.to_csv(path, index=False)
            written.append(path)
            row_counts[path.name] = int(len(combined))
        shutil.rmtree(intermediate, ignore_errors=True)
        for kind in sorted(json_values):
            values = json_values[kind]
            path = temporary / f"{kind}_job_block_{block_padded}.json"
            _write_json(path, values[0] if len(values) == 1 else values)
            written.append(path)
            row_counts[path.name] = len(values)
        for kind in sorted(jsonl_records):
            records = jsonl_records[kind]
            path = temporary / f"{kind}_job_block_{block_padded}.jsonl"
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            written.append(path)
            row_counts[path.name] = len(records)

        summary = {
            "campaign_fingerprint": fingerprint,
            "block_id": int(block_id),
            "worker_ids": expected,
            "total_jobs_requested": len(expected),
            "total_jobs_completed": len(expected),
            "total_strategies_loaded": canonical_total,
            "total_strategies_evaluated": evaluated_count,
            "total_strategies_early_rejected": early_count,
            "total_strategies_timed_out": 0,
            "total_strategies_runtime_error": 0,
            "total_strategies_unsupported": 0,
            "total_strategies_slow_deferred": 0,
        }
        summary_path = temporary / f"summary_job_block_{block_padded}.json"
        _write_json(summary_path, summary)
        written.append(summary_path)
        campaign_output = temporary / "campaign_manifest.json"
        _copy_streaming(workers[expected[0]][0] / "campaign_manifest.json", campaign_output)
        written.append(campaign_output)
        manifest = {
            "campaign_fingerprint": fingerprint,
            "block_id": int(block_id),
            "worker_ids": expected,
            "canonical_group_count": canonical_total,
            "row_counts": row_counts,
            "worker_manifests": [
                {
                    "worker_id": worker_id,
                    "canonical_ids": workers[worker_id][3],
                    "sha256": _stream_digest(workers[worker_id][0] / "worker_manifest.json"),
                }
                for worker_id in expected
            ],
            "files": [_digest_record(path, temporary) for path in sorted(written)],
        }
        _write_json(temporary / "block_manifest.json", manifest)
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--block-id", type=int, required=True)
    parser.add_argument("--worker-ids", required=True, help="Comma-separated worker IDs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workers = [int(value) for value in str(args.worker_ids).split(",") if value.strip()]
    summary = merge_block(
        input_root=args.input_root,
        output_dir=args.output_dir,
        block_id=args.block_id,
        expected_worker_ids=workers,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

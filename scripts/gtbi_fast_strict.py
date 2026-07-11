"""Build a deterministic, provenance-bound GTBI evaluation campaign plan."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from scripts import global_technical_buy_indicator as gtbi


DEFAULT_WORKER_COUNT = 360
DEFAULT_EXPECTED_STRATEGY_COUNT = 72_000
DEFAULT_EXPECTED_UNIQUE_GROUP_COUNT = 3_600
DEFAULT_TRAIN_END = "2010-12-31"
DEFAULT_VALIDATION_START = "2011-01-01"
DEFAULT_VALIDATION_END = "2020-12-31"
DEFAULT_LOCKED_START = "2021-01-01"
DEFAULT_MIN_MARKET_CAP = 2_000_000_000
DEFAULT_EXECUTION_MODE = "optimized_evaluation_v5_event_first"


@dataclass(frozen=True)
class _CandidateRecord:
    candidate: gtbi.ExternalStrategyCandidate
    strategy_id: str
    source_shard_id: int
    source_slot_in_shard: int
    global_slot: int
    evaluation_hash: str


@dataclass(frozen=True)
class _EconomicGroup:
    evaluation_hash: str
    representative: _CandidateRecord
    records: tuple[_CandidateRecord, ...]
    raw_cost_score: float
    scheduling_cost: float


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def economic_evaluation_hash(candidate: gtbi.ExternalStrategyCandidate) -> str:
    """Return the hash of only the effective evaluator configuration."""
    return hashlib.sha256(_canonical_json(candidate.config.to_dict())).hexdigest()


def strategy_pack_digest(pack_path: Path) -> str:
    """Digest every pack file, ordered by its relative path and raw bytes."""
    root = Path(pack_path)
    if not root.exists():
        raise FileNotFoundError(f"strategy pack path not found: {root}")
    files: Iterable[Path]
    if root.is_file():
        files = (root,)
        relative_root = root.parent
    else:
        files = sorted(path for path in root.rglob("*") if path.is_file())
        relative_root = root
    digest = hashlib.sha256()
    for path in files:
        relative_path = path.relative_to(relative_root).as_posix().encode("utf-8")
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def campaign_fingerprint(
    *,
    code_sha: str,
    strategy_pack_digest: str,
    data_run_identity: str,
    train_end: str,
    validation_start: str,
    validation_end: str,
    locked_start: str,
    min_market_cap: int | float,
    execution_mode: str,
    universe_identity: str,
    dependency_lock_identity: str,
) -> str:
    """Hash the immutable execution and data context for one campaign."""
    inputs = {
        "code_sha": str(code_sha),
        "strategy_pack_digest": str(strategy_pack_digest),
        "data_run_identity": str(data_run_identity),
        "train_end": str(train_end),
        "validation_start": str(validation_start),
        "validation_end": str(validation_end),
        "locked_start": str(locked_start),
        "min_market_cap": min_market_cap,
        "execution_mode": str(execution_mode),
        "universe_identity": str(universe_identity),
        "dependency_lock_identity": str(dependency_lock_identity),
    }
    return hashlib.sha256(_canonical_json(inputs)).hexdigest()


def _candidate_records(candidates: list[gtbi.ExternalStrategyCandidate]) -> list[_CandidateRecord]:
    records: list[_CandidateRecord] = []
    strategy_ids: set[str] = set()
    global_slots: set[int] = set()
    for candidate in candidates:
        payload = candidate.payload
        raw_strategy_id = payload.get("strategy_id")
        strategy_id = "" if raw_strategy_id is None else str(raw_strategy_id)
        if not strategy_id.strip():
            raise ValueError("strategy_id must not be empty")
        if candidate.unsupported_rules:
            rules = ", ".join(candidate.unsupported_rules)
            raise ValueError(f"candidate {strategy_id!r} has unsupported rules: {rules}")
        if strategy_id in strategy_ids:
            raise ValueError(f"duplicate strategy_id: {strategy_id}")
        try:
            source_shard_id = int(payload["shard_id"])
            source_slot_in_shard = int(payload["slot_in_shard"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"candidate {strategy_id!r} has invalid source identity") from error
        if not 0 <= source_shard_id <= 359:
            raise ValueError(f"source_shard_id must be between 0 and 359: {source_shard_id}")
        if not 0 <= source_slot_in_shard <= 199:
            raise ValueError(f"source_slot_in_shard must be between 0 and 199: {source_slot_in_shard}")
        global_slot = source_shard_id * 200 + source_slot_in_shard
        if not 0 <= global_slot <= 71_999:
            raise ValueError(f"global_slot must be between 0 and 71999: {global_slot}")
        if global_slot in global_slots:
            raise ValueError(f"duplicate global_slot: {global_slot}")
        strategy_ids.add(strategy_id)
        global_slots.add(global_slot)
        records.append(
            _CandidateRecord(
                candidate=candidate,
                strategy_id=strategy_id,
                source_shard_id=source_shard_id,
                source_slot_in_shard=source_slot_in_shard,
                global_slot=global_slot,
                evaluation_hash=economic_evaluation_hash(candidate),
            )
        )
    return records


def _economic_groups(records: list[_CandidateRecord], execution_mode: str) -> list[_EconomicGroup]:
    grouped: dict[str, list[_CandidateRecord]] = {}
    for record in records:
        grouped.setdefault(record.evaluation_hash, []).append(record)
    groups: list[_EconomicGroup] = []
    for evaluation_hash, members in grouped.items():
        ordered_members = tuple(sorted(members, key=lambda item: (item.global_slot, item.strategy_id)))
        representative = ordered_members[0]
        raw_cost_score = float(
            gtbi._estimated_cost_score(
                representative.candidate.payload,
                optimized_evaluation_mode=execution_mode,
            )[0]
        )
        groups.append(
            _EconomicGroup(
                evaluation_hash=evaluation_hash,
                representative=representative,
                records=ordered_members,
                raw_cost_score=raw_cost_score,
                scheduling_cost=max(1.0, raw_cost_score),
            )
        )
    return groups


def _lpt_assign(groups: list[_EconomicGroup], worker_count: int) -> tuple[dict[str, int], list[list[_EconomicGroup]], list[float]]:
    worker_groups: list[list[_EconomicGroup]] = [[] for _ in range(worker_count)]
    worker_costs = [0.0] * worker_count
    assignments: dict[str, int] = {}
    for group in sorted(groups, key=lambda item: (-item.scheduling_cost, item.evaluation_hash)):
        worker_id = min(
            range(worker_count),
            key=lambda index: (worker_costs[index], len(worker_groups[index]), index),
        )
        worker_groups[worker_id].append(group)
        worker_costs[worker_id] += group.scheduling_cost
        assignments[group.evaluation_hash] = worker_id
    return assignments, worker_groups, worker_costs


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _artifact_metadata(output_dir: Path, relative_paths: Iterable[Path]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for relative_path in sorted(relative_paths, key=lambda path: path.as_posix()):
        path = output_dir / relative_path
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        artifacts.append(
            {
                "path": relative_path.as_posix(),
                "sha256": digest.hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    return artifacts


def _matrix_workers(worker_ids: Iterable[int], worker_groups: list[list[_EconomicGroup]], worker_costs: list[float]) -> list[dict[str, Any]]:
    return [
        {
            "worker_id": worker_id,
            "group_count": len(worker_groups[worker_id]),
            "scheduling_cost": worker_costs[worker_id],
        }
        for worker_id in worker_ids
    ]


def create_campaign_plan(
    pack_path: Path,
    output_dir: Path,
    *,
    worker_count: int = DEFAULT_WORKER_COUNT,
    expected_strategy_count: int = DEFAULT_EXPECTED_STRATEGY_COUNT,
    expected_unique_group_count: int | None = DEFAULT_EXPECTED_UNIQUE_GROUP_COUNT,
    code_sha: str,
    data_run_identity: str,
    train_end: str = DEFAULT_TRAIN_END,
    validation_start: str = DEFAULT_VALIDATION_START,
    validation_end: str = DEFAULT_VALIDATION_END,
    locked_start: str = DEFAULT_LOCKED_START,
    min_market_cap: int | float = DEFAULT_MIN_MARKET_CAP,
    execution_mode: str = DEFAULT_EXECUTION_MODE,
    universe_identity: str,
    dependency_lock_identity: str,
    strategy_format: str = "auto",
) -> dict[str, Any]:
    """Create a deterministic worker plan and all campaign artifacts."""
    if worker_count <= 0:
        raise ValueError("worker_count must be greater than zero")
    output = Path(output_dir)
    if output.is_file() or (output.exists() and any(path.is_file() for path in output.rglob("*"))):
        raise ValueError(f"output directory already contains files: {output}")
    candidates = gtbi.load_external_strategy_candidates(
        Path(pack_path),
        shard_id=None,
        offset=0,
        limit=None,
        strategy_format=strategy_format,
    )
    if len(candidates) != expected_strategy_count:
        raise ValueError(f"candidate count {len(candidates)} differs from expected count {expected_strategy_count}")
    records = _candidate_records(candidates)
    groups = _economic_groups(records, execution_mode)
    if expected_unique_group_count is not None and len(groups) != expected_unique_group_count:
        raise ValueError(
            f"unique economic group count {len(groups)} differs from expected count "
            f"{expected_unique_group_count}"
        )
    assignments, worker_groups, worker_costs = _lpt_assign(groups, worker_count)
    if any(not worker for worker in worker_groups):
        raise ValueError("at least one worker is empty after economic grouping")

    canonical_pack = output / "canonical_pack"
    canonical_pack.mkdir(parents=True, exist_ok=True)
    pack_digest = strategy_pack_digest(Path(pack_path))
    inputs = {
        "code_sha": str(code_sha),
        "strategy_pack_digest": pack_digest,
        "data_run_identity": str(data_run_identity),
        "train_end": str(train_end),
        "validation_start": str(validation_start),
        "validation_end": str(validation_end),
        "locked_start": str(locked_start),
        "min_market_cap": min_market_cap,
        "execution_mode": str(execution_mode),
        "universe_identity": str(universe_identity),
        "dependency_lock_identity": str(dependency_lock_identity),
    }
    fingerprint = campaign_fingerprint(**inputs)

    alias_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    for worker_id, assigned_groups in enumerate(worker_groups):
        canonical_path = canonical_pack / f"strategies_shard_{worker_id:03d}.jsonl"
        with canonical_path.open("w", encoding="utf-8") as handle:
            for slot_in_shard, group in enumerate(assigned_groups):
                representative = group.representative
                payload = dict(representative.candidate.payload)
                payload["source_shard_id"] = representative.source_shard_id
                payload["source_slot_in_shard"] = representative.source_slot_in_shard
                payload["shard_id"] = worker_id
                payload["slot_in_shard"] = slot_in_shard
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")
                manifest_rows.append(
                    {
                        "evaluation_hash": group.evaluation_hash,
                        "canonical_strategy_id": representative.strategy_id,
                        "source_shard_id": representative.source_shard_id,
                        "source_slot_in_shard": representative.source_slot_in_shard,
                        "global_slot": representative.global_slot,
                        "worker_id": worker_id,
                        "raw_cost_score": group.raw_cost_score,
                        "scheduling_cost": group.scheduling_cost,
                    }
                )
                for record in group.records:
                    alias_rows.append(
                        {
                            "strategy_id": record.strategy_id,
                            "evaluation_hash": group.evaluation_hash,
                            "canonical_strategy_id": representative.strategy_id,
                            "source_shard_id": record.source_shard_id,
                            "source_slot_in_shard": record.source_slot_in_shard,
                            "global_slot": record.global_slot,
                            "worker_id": worker_id,
                        }
                    )

    alias_rows.sort(key=lambda row: (int(row["global_slot"]), str(row["strategy_id"])))
    manifest_rows.sort(key=lambda row: (int(row["worker_id"]), int(row["global_slot"]), str(row["canonical_strategy_id"])))
    _write_csv(
        output / "alias_map.csv",
        [
            "strategy_id",
            "evaluation_hash",
            "canonical_strategy_id",
            "source_shard_id",
            "source_slot_in_shard",
            "global_slot",
            "worker_id",
        ],
        alias_rows,
    )
    _write_csv(
        output / "worker_manifest.csv",
        [
            "evaluation_hash",
            "canonical_strategy_id",
            "source_shard_id",
            "source_slot_in_shard",
            "global_slot",
            "worker_id",
            "raw_cost_score",
            "scheduling_cost",
        ],
        manifest_rows,
    )
    matrix_split = min(180, worker_count)
    _write_json(
        output / "matrix_a.json",
        {"include": _matrix_workers(range(matrix_split), worker_groups, worker_costs)},
    )
    _write_json(
        output / "matrix_b.json",
        {"include": _matrix_workers(range(matrix_split, worker_count), worker_groups, worker_costs)},
    )
    _write_json(
        output / "block_matrix.json",
        {
            "include": [
                {"block_id": block_id, "worker_ids": list(range(start, min(start + 18, worker_count)))}
                for block_id, start in enumerate(range(0, worker_count, 18))
            ]
        },
    )
    artifact_paths = [
        Path("canonical_pack") / f"strategies_shard_{worker_id:03d}.jsonl"
        for worker_id in range(worker_count)
    ]
    artifact_paths.extend(
        Path(name)
        for name in (
            "alias_map.csv",
            "worker_manifest.csv",
            "matrix_a.json",
            "matrix_b.json",
            "block_matrix.json",
        )
    )
    manifest = {
        "campaign_fingerprint": fingerprint,
        "inputs": inputs,
        "counts": {
            "candidate_count": len(records),
            "unique_economic_groups": len(groups),
            "expected_unique_group_count": expected_unique_group_count,
            "worker_count": worker_count,
        },
        "assignments": assignments,
        "artifacts": _artifact_metadata(output, artifact_paths),
    }
    _write_json(output / "campaign_manifest.json", manifest)
    return manifest


def _current_code_sha() -> str:
    github_sha = os.environ.get("GITHUB_SHA")
    if github_sha:
        return github_sha
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKER_COUNT)
    parser.add_argument("--expected-strategy-count", type=int, default=DEFAULT_EXPECTED_STRATEGY_COUNT)
    parser.add_argument(
        "--expected-unique-group-count",
        type=int,
        default=DEFAULT_EXPECTED_UNIQUE_GROUP_COUNT,
    )
    parser.add_argument("--code-sha", default=None)
    parser.add_argument("--data-run-identity", required=True)
    parser.add_argument("--train-end", default=DEFAULT_TRAIN_END)
    parser.add_argument("--validation-start", default=DEFAULT_VALIDATION_START)
    parser.add_argument("--validation-end", default=DEFAULT_VALIDATION_END)
    parser.add_argument("--locked-start", default=DEFAULT_LOCKED_START)
    parser.add_argument("--min-market-cap", type=int, default=DEFAULT_MIN_MARKET_CAP)
    parser.add_argument("--execution-mode", default=DEFAULT_EXECUTION_MODE)
    parser.add_argument("--universe-identity", required=True)
    parser.add_argument("--dependency-lock-identity", required=True)
    parser.add_argument("--strategy-format", choices=("auto", "jsonl", "csv"), default="auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = create_campaign_plan(
        args.pack_path,
        args.output_dir,
        worker_count=args.workers,
        expected_strategy_count=args.expected_strategy_count,
        expected_unique_group_count=args.expected_unique_group_count,
        code_sha=args.code_sha or _current_code_sha(),
        data_run_identity=args.data_run_identity,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        locked_start=args.locked_start,
        min_market_cap=args.min_market_cap,
        execution_mode=args.execution_mode,
        universe_identity=args.universe_identity,
        dependency_lock_identity=args.dependency_lock_identity,
        strategy_format=args.strategy_format,
    )
    print(manifest["campaign_fingerprint"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Strictly reduce GTBI V6 blocks and expand only lightweight alias results."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from scripts import global_technical_buy_indicator as gtbi
from scripts import gtbi_fast_strict as planner
from scripts import gtbi_fast_strict_results as results


BLOCK_ARTIFACT_RE = re.compile(r"^(?P<kind>.+)_job_block_\d+\.(?P<extension>csv|jsonl)$")
LIGHTWEIGHT_KINDS = {
    "leaderboard": ("leaderboard.csv", gtbi.LEADERBOARD_COLUMNS),
    "early_rejected_strategies": ("early_rejected_strategies.csv", gtbi.EARLY_REJECT_COLUMNS),
    "yearly_trade_performance": ("yearly_trade_performance.csv", gtbi.YEARLY_COLUMNS),
    "timing_diagnostics": ("timing_diagnostics.csv", gtbi.TIMING_DIAGNOSTIC_COLUMNS),
}
FAILURE_KINDS = {
    "timeout_strategies",
    "runtime_errors",
    "unsupported_strategies",
    "slow_deferred_strategies",
}


def _json(path: Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_record(root: Path, record: dict[str, Any]) -> Path:
    relative = Path(str(record.get("path") or ""))
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid manifest path: {relative}")
    path = root / relative
    if not path.is_file():
        raise ValueError(f"manifest file is missing: {relative.as_posix()}")
    if _file_digest(path) != str(record.get("sha256") or ""):
        raise ValueError(f"digest mismatch for {relative.as_posix()}")
    if path.stat().st_size != int(record.get("size_bytes", -1)):
        raise ValueError(f"size mismatch for {relative.as_posix()}")
    return path


def _artifact_records(campaign: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = list(campaign.get("artifacts") or [])
    indexed = {str(record.get("path") or ""): dict(record) for record in records}
    if len(indexed) != len(records):
        raise ValueError("campaign manifest contains duplicate artifact paths")
    return indexed


def _load_plan(
    plan_root: Path,
    original_pack_path: Path,
    *,
    expected_alias_count: int,
    expected_worker_count: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    planner.verify_campaign_artifacts(Path(plan_root))
    campaign_path = Path(plan_root) / "campaign_manifest.json"
    campaign = _json(campaign_path)
    fingerprint = str(campaign.get("campaign_fingerprint") or "")
    if not fingerprint:
        raise ValueError("campaign manifest has no fingerprint")
    inputs = results._campaign_inputs(campaign_path)
    expected_digest = str(inputs.get("strategy_pack_digest") or "")
    if not expected_digest or planner.strategy_pack_digest(Path(original_pack_path)) != expected_digest:
        raise ValueError("original pack digest does not match campaign manifest")

    records = _artifact_records(campaign)
    for name in ("alias_map.csv", "worker_manifest.csv"):
        record = records.get(name)
        if record is None:
            raise ValueError(f"campaign manifest has no record for {name}")
        _verify_record(Path(plan_root), record)

    alias_map = results._read_csv(Path(plan_root) / "alias_map.csv", results.ALIAS_COLUMNS)
    results._validate_alias_map(alias_map, expected_alias_count)
    worker_manifest = results._read_csv(Path(plan_root) / "worker_manifest.csv")
    required_worker_columns = {
        "evaluation_hash",
        "signal_hash",
        "exit_hash",
        "canonical_strategy_id",
        "source_shard_id",
        "source_slot_in_shard",
        "global_slot",
        "worker_id",
    }
    missing = sorted(required_worker_columns - set(worker_manifest.columns))
    if missing:
        raise ValueError(f"worker manifest is missing columns: {', '.join(missing)}")
    if worker_manifest.empty:
        raise ValueError("worker manifest is empty")
    results.gtbi._assert_consistent_duplicate_rows(
        worker_manifest,
        ["canonical_strategy_id"],
        label="worker manifest",
    )
    if worker_manifest["canonical_strategy_id"].astype(str).duplicated().any():
        raise ValueError("worker manifest contains duplicate canonical_strategy_id values")
    if worker_manifest["evaluation_hash"].astype(str).duplicated().any():
        raise ValueError("worker manifest contains duplicate economic groups")
    worker_ids = pd.to_numeric(worker_manifest["worker_id"], errors="raise").astype(int)
    expected_workers = set(range(int(expected_worker_count)))
    if set(worker_ids) != expected_workers:
        raise ValueError("worker manifest membership does not match expected workers")

    canonical_manifest = worker_manifest.set_index("canonical_strategy_id", drop=False)
    aliases_by_canonical = alias_map.groupby("canonical_strategy_id", sort=False)
    if set(aliases_by_canonical.groups) != set(canonical_manifest.index.astype(str)):
        raise ValueError("alias map canonical membership does not match worker manifest")
    for canonical_id, aliases in aliases_by_canonical:
        manifest_row = canonical_manifest.loc[str(canonical_id)]
        for hash_name in ("evaluation_hash", "signal_hash", "exit_hash"):
            if aliases[hash_name].astype(str).nunique() != 1:
                raise ValueError(f"aliases disagree on {hash_name} for {canonical_id}")
            if str(aliases[hash_name].iloc[0]) != str(manifest_row[hash_name]):
                raise ValueError(f"alias map {hash_name} does not match worker manifest for {canonical_id}")
        if pd.to_numeric(aliases["worker_id"], errors="raise").astype(int).nunique() != 1:
            raise ValueError(f"aliases disagree on worker for {canonical_id}")
        if int(aliases["worker_id"].iloc[0]) != int(manifest_row["worker_id"]):
            raise ValueError(f"alias map worker does not match worker manifest for {canonical_id}")

    counts = dict(campaign.get("counts") or {})
    if int(counts.get("candidate_count", -1)) != int(expected_alias_count):
        raise ValueError("campaign candidate count does not match expected aliases")
    if int(counts.get("unique_economic_groups", -1)) != len(worker_manifest):
        raise ValueError("campaign economic group count does not match worker manifest")
    if int(counts.get("worker_count", -1)) != int(expected_worker_count):
        raise ValueError("campaign worker count does not match expected workers")
    return campaign, alias_map, worker_manifest


def _expected_blocks(plan_root: Path, expected_block_count: int) -> dict[int, list[int]]:
    matrix_path = Path(plan_root) / "block_matrix.json"
    if not matrix_path.is_file():
        raise ValueError("campaign plan is missing block_matrix.json")
    rows = list(_json(matrix_path).get("include") or [])
    membership = {int(row["block_id"]): [int(worker) for worker in row["worker_ids"]] for row in rows}
    if len(membership) != len(rows) or set(membership) != set(range(int(expected_block_count))):
        raise ValueError("block matrix membership does not match expected blocks")
    if any(not workers for workers in membership.values()):
        raise ValueError("block matrix contains an empty worker block")
    return membership


def _verified_blocks(
    blocks_root: Path,
    *,
    fingerprint: str,
    expected_blocks: dict[int, list[int]],
) -> list[tuple[dict[str, Any], Path, list[Path]]]:
    manifests = sorted(Path(blocks_root).rglob("block_manifest.json"))
    if len(manifests) != len(expected_blocks):
        raise ValueError("block manifest count does not match expected blocks")
    blocks: dict[int, tuple[dict[str, Any], Path, list[Path]]] = {}
    for manifest_path in manifests:
        block_root = manifest_path.parent
        manifest = _json(manifest_path)
        block_id = int(manifest.get("block_id", -1))
        if block_id in blocks:
            raise ValueError(f"duplicate block manifest for block {block_id}")
        if str(manifest.get("campaign_fingerprint") or "") != fingerprint:
            raise ValueError(f"campaign fingerprint mismatch in block {block_id}")
        if manifest.get("worker_ids") != expected_blocks.get(block_id):
            raise ValueError(f"worker membership mismatch in block {block_id}")
        records = list(manifest.get("files") or [])
        if not records:
            raise ValueError(f"block {block_id} has no file records")
        files = [_verify_record(block_root, dict(record)) for record in records]
        if not any(path.name.startswith("summary_job_block_") for path in files):
            raise ValueError(f"block {block_id} has no summary record")
        blocks[block_id] = (manifest, block_root, files)
    if set(blocks) != set(expected_blocks):
        raise ValueError("block manifest IDs do not match expected blocks")
    return [blocks[block_id] for block_id in sorted(blocks)]


def _csv_has_data_rows(path: Path) -> bool:
    with Path(path).open("rb") as handle:
        handle.readline()
        return any(line.strip() for line in handle)


def _stream_csv_files(paths: list[Path], destination: Path) -> None:
    header: bytes | None = None
    with Path(destination).open("wb") as output:
        for path in paths:
            with Path(path).open("rb") as source:
                current = source.readline().rstrip(b"\r\n")
                if header is None:
                    header = current
                    output.write(header + b"\n")
                elif current != header:
                    raise ValueError(f"CSV header mismatch while streaming {path.name}")
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _stream_jsonl_files(paths: list[Path], destination: Path) -> None:
    with Path(destination).open("wb") as output:
        for path in paths:
            with Path(path).open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _combine_canonical_results(
    blocks: list[tuple[dict[str, Any], Path, list[Path]]],
    output: Path,
) -> tuple[Path, pd.DataFrame]:
    canonical_root = output / "canonical_results"
    canonical_root.mkdir(parents=True, exist_ok=False)
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in LIGHTWEIGHT_KINDS}
    canonical_paths: dict[str, list[Path]] = {}
    canonical_jsonl_paths: dict[str, list[Path]] = {}
    for _, _, files in blocks:
        for path in files:
            match = BLOCK_ARTIFACT_RE.match(path.name)
            if match is None:
                continue
            kind = str(match.group("kind"))
            extension = str(match.group("extension"))
            if extension == "jsonl":
                canonical_jsonl_paths.setdefault(kind, []).append(path)
                continue
            if kind in FAILURE_KINDS:
                if _csv_has_data_rows(path):
                    raise ValueError(f"block contains failure rows in {kind}")
                continue
            if kind not in frames:
                canonical_paths.setdefault(kind, []).append(path)
                continue
            frame = results._read_csv(path)
            frames[kind].append(frame)

    combined: dict[str, pd.DataFrame] = {}
    for kind, (filename, columns) in LIGHTWEIGHT_KINDS.items():
        source = frames[kind]
        frame = pd.concat(source, ignore_index=True, sort=False) if source else pd.DataFrame(columns=columns)
        combined[kind] = frame
    gtbi._assert_consistent_duplicate_rows(combined["leaderboard"], ["candidate_id"], label="final leaderboard")
    gtbi._assert_consistent_duplicate_rows(combined["early_rejected_strategies"], ["strategy_id"], label="final early_rejected")
    gtbi._assert_consistent_duplicate_rows(combined["yearly_trade_performance"], ["candidate_id", "split", "year"], label="final yearly")
    gtbi._assert_consistent_duplicate_rows(combined["timing_diagnostics"], ["strategy_id"], label="final timing")
    for kind, (filename, columns) in LIGHTWEIGHT_KINDS.items():
        frame = combined[kind].drop_duplicates(keep="first")
        results._write_csv(canonical_root / filename, frame, columns)
        combined[kind] = frame

    for kind, paths in sorted(canonical_paths.items()):
        _stream_csv_files(paths, canonical_root / f"{kind}.csv")
    for kind, paths in sorted(canonical_jsonl_paths.items()):
        _stream_jsonl_files(paths, canonical_root / f"{kind}.jsonl")
    return canonical_root, combined["leaderboard"]


def _validate_canonical_terminals(
    worker_manifest: pd.DataFrame,
    canonical_root: Path,
    *,
    expected_alias_count: int,
) -> None:
    leaderboard = results._read_csv(canonical_root / "leaderboard.csv", gtbi.LEADERBOARD_COLUMNS)
    rejected = results._read_csv(canonical_root / "early_rejected_strategies.csv", gtbi.EARLY_REJECT_COLUMNS)
    leaderboard_ids = set(leaderboard.get("candidate_id", pd.Series(dtype=str)).dropna().astype(str))
    rejected_ids = set(rejected.get("strategy_id", pd.Series(dtype=str)).dropna().astype(str))
    if leaderboard_ids & rejected_ids:
        raise ValueError("canonical terminal outcomes overlap")
    expected = set(worker_manifest["canonical_strategy_id"].astype(str))
    actual = leaderboard_ids | rejected_ids
    if actual != expected:
        raise ValueError("canonical terminal membership does not match worker manifest")
    if int(expected_alias_count) <= 0:
        raise ValueError("expected alias count must be positive")


def _publish_canonical_summaries(canonical_root: Path, output: Path) -> None:
    for path in sorted(canonical_root.iterdir()):
        if not path.is_file():
            continue
        stem = path.stem
        if stem.startswith("top_") or stem.startswith(("family_", "concept_", "market_")):
            shutil.copyfile(path, output / path.name)


def _merge_final_results_into(
    *,
    plan_root: Path,
    blocks_root: Path,
    original_pack_path: Path,
    output_dir: Path,
    expected_alias_count: int = 72_000,
    expected_block_count: int = 20,
    expected_worker_count: int = 360,
) -> dict[str, Any]:
    """Verify a V6 campaign, reduce canonical blocks, then expand aliases exactly once."""
    output = Path(output_dir)

    campaign, _alias_map, worker_manifest = _load_plan(
        Path(plan_root),
        Path(original_pack_path),
        expected_alias_count=expected_alias_count,
        expected_worker_count=expected_worker_count,
    )
    fingerprint = str(campaign["campaign_fingerprint"])
    expected_blocks = _expected_blocks(Path(plan_root), expected_block_count)
    matrix_workers = [worker for workers in expected_blocks.values() for worker in workers]
    if sorted(matrix_workers) != list(range(expected_worker_count)):
        raise ValueError("block matrix must cover every worker exactly once")
    blocks = _verified_blocks(Path(blocks_root), fingerprint=fingerprint, expected_blocks=expected_blocks)
    canonical_root, _leaderboard = _combine_canonical_results(blocks, output)
    (canonical_root / "campaign_manifest.json").write_text(
        json.dumps(campaign, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _validate_canonical_terminals(
        worker_manifest,
        canonical_root,
        expected_alias_count=expected_alias_count,
    )

    aliases_root = output / "aliases"
    expansion = results.expand_canonical_results(
        canonical_results_root=canonical_root,
        alias_map_path=Path(plan_root) / "alias_map.csv",
        original_pack_path=Path(original_pack_path),
        campaign_manifest_path=Path(plan_root) / "campaign_manifest.json",
        output_dir=aliases_root,
        expected_alias_count=expected_alias_count,
    )
    terminal_count = int(expansion["leaderboard_rows"]) + int(expansion["early_rejected_rows"])
    if terminal_count != int(expected_alias_count):
        raise ValueError("alias terminal count does not match expected aliases")
    failure_counts = (
        expansion["timeout_rows"],
        expansion["runtime_error_rows"],
        expansion["unsupported_rows"],
        expansion["slow_deferred_rows"],
        expansion["synthetic_missing_timeout_rows"],
    )
    if any(int(value) for value in failure_counts) or bool(expansion["fill_missing_timeouts_enabled"]):
        raise ValueError("final expansion contains failure or synthetic rows")
    dedupe = results._read_csv(aliases_root / "dedupe_map_job_aliases.csv")
    if len(dedupe) != int(expected_alias_count) or any(column not in dedupe for column in results.HASH_COLUMNS):
        raise ValueError("alias hash mapping is incomplete")
    results._write_csv(
        output / "canonical_trade_detail_alias_map.csv",
        dedupe[["strategy_id", "canonical_strategy_id", *results.HASH_COLUMNS]],
    )
    published_leaderboard = results._read_csv(aliases_root / "leaderboard_job_aliases.csv")
    if published_leaderboard.empty:
        best_candidate_id = None
        best_adjusted_return_time_risk = None
    else:
        best_row = published_leaderboard.iloc[0]
        best_candidate_id = str(best_row["candidate_id"])
        best_value = best_row.get("adjusted_return_time_risk")
        best_adjusted_return_time_risk = None if pd.isna(best_value) else float(best_value)
    summary = {
        **expansion,
        "campaign_fingerprint": fingerprint,
        "canonical_group_count": int(len(worker_manifest)),
        "total_terminal_identities": terminal_count,
        "best_candidate_id": best_candidate_id,
        "best_adjusted_return_time_risk": best_adjusted_return_time_risk,
        "total_strategies_requested": int(expected_alias_count),
        "total_strategies_loaded": int(expected_alias_count),
        "total_strategies_failed": 0,
        "total_jobs_requested": int(expected_worker_count),
        "total_jobs_completed": int(expected_worker_count),
        "total_jobs_failed": 0,
        "candidate_count_per_job": (
            int(len(worker_manifest) // expected_worker_count)
            if len(worker_manifest) % expected_worker_count == 0
            else None
        ),
        "candidate_timeout_seconds": 0,
        "optimized_evaluation_mode": "optimized_evaluation_v6_fast_strict",
        "github_only_run": True,
        "requires_local_machine": False,
        "strict_final_pass": True,
    }
    publication_files = {
        "leaderboard_job_aliases.csv": "leaderboard.csv",
        "early_rejected_strategies_job_aliases.csv": "early_rejected_strategies.csv",
        "dedupe_map_job_aliases.csv": "dedupe_map.csv",
        "job_manifest_job_aliases.csv": "job_manifest.csv",
        "yearly_trade_performance_job_aliases.csv": "yearly_trade_performance.csv",
        "filtered_leaderboard_job_aliases.csv": "filtered_leaderboard.csv",
        "timing_diagnostics_job_aliases.csv": "timing_diagnostics.csv",
        "timeout_strategies_job_aliases.csv": "timeout_strategies.csv",
        "runtime_errors_job_aliases.csv": "runtime_errors.csv",
        "unsupported_strategies_job_aliases.csv": "unsupported_strategies.csv",
        "slow_deferred_strategies_job_aliases.csv": "slow_deferred_strategies.csv",
    }
    for source_name, destination_name in publication_files.items():
        source = aliases_root / source_name
        if not source.is_file():
            raise ValueError(f"alias expansion did not produce {source_name}")
        shutil.copyfile(source, output / destination_name)
    shutil.rmtree(aliases_root)
    _publish_canonical_summaries(canonical_root, output)
    (output / "campaign_manifest.json").write_text(
        json.dumps(campaign, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "final_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "_SUCCESS").write_text(f"{fingerprint}\n", encoding="utf-8")
    return summary


def merge_final_results(
    *,
    plan_root: Path,
    blocks_root: Path,
    original_pack_path: Path,
    output_dir: Path,
    expected_alias_count: int = 72_000,
    expected_block_count: int = 20,
    expected_worker_count: int = 360,
) -> dict[str, Any]:
    """Publish a fully verified final artifact atomically from a sibling directory."""
    output = Path(output_dir)
    if output.exists():
        raise ValueError(f"output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        summary = _merge_final_results_into(
            plan_root=plan_root,
            blocks_root=blocks_root,
            original_pack_path=original_pack_path,
            output_dir=temporary,
            expected_alias_count=expected_alias_count,
            expected_block_count=expected_block_count,
            expected_worker_count=expected_worker_count,
        )
        temporary.replace(output)
        return summary
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--blocks-root", type=Path, required=True)
    parser.add_argument("--original-pack", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-alias-count", type=int, default=72_000)
    parser.add_argument("--expected-block-count", type=int, default=20)
    parser.add_argument("--expected-worker-count", type=int, default=360)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    summary = merge_final_results(
        plan_root=args.plan_root,
        blocks_root=args.blocks_root,
        original_pack_path=args.original_pack,
        output_dir=args.output_dir,
        expected_alias_count=args.expected_alias_count,
        expected_block_count=args.expected_block_count,
        expected_worker_count=args.expected_worker_count,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

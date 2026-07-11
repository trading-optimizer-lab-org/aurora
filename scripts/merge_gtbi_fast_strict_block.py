"""Merge a fixed GTBI worker block without dropping or reconciling rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


WORKER_FILE_RE = re.compile(r"^(?P<kind>.+)_(?:job|shard)_\d+\.(?P<extension>csv|jsonl)$")
FAILURE_KINDS = {
    "timeout_strategies",
    "slow_deferred_strategies",
    "unsupported_strategies",
    "runtime_errors",
}


def _json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _digest_record(path: Path, root: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": digest,
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


def merge_block(
    *,
    input_root: Path,
    output_dir: Path,
    block_id: int,
    expected_worker_ids: list[int],
) -> dict[str, Any]:
    source = Path(input_root)
    output = Path(output_dir)
    if output.is_file() or (output.exists() and any(path.is_file() for path in output.rglob("*"))):
        raise ValueError(f"output directory already contains files: {output}")
    summaries_by_worker: dict[int, tuple[Path, dict[str, Any]]] = {}
    fingerprints: set[str] = set()
    for summary_path in sorted(source.rglob("worker_summary.json")):
        summary = _json(summary_path)
        worker_id = int(summary.get("worker_id", -1))
        if worker_id in summaries_by_worker:
            raise ValueError(f"duplicate worker summary for worker {worker_id}")
        fingerprint = str(summary.get("campaign_fingerprint") or "")
        campaign_path = summary_path.parent / "campaign_manifest.json"
        if not campaign_path.is_file():
            raise ValueError(f"worker {worker_id} has no campaign manifest")
        if str(_json(campaign_path).get("campaign_fingerprint") or "") != fingerprint:
            raise ValueError(f"campaign fingerprint mismatch inside worker {worker_id}")
        summaries_by_worker[worker_id] = (summary_path.parent, summary)
        fingerprints.add(fingerprint)
    expected = sorted(int(worker_id) for worker_id in expected_worker_ids)
    actual = sorted(summaries_by_worker)
    if actual != expected:
        raise ValueError(f"worker membership mismatch: expected={expected} actual={actual}")
    if len(fingerprints) != 1 or "" in fingerprints:
        raise ValueError(f"campaign fingerprint mismatch across block: {sorted(fingerprints)}")

    csv_frames: dict[str, list[pd.DataFrame]] = {}
    jsonl_lines: dict[str, list[str]] = {}
    leaderboard_ids: list[str] = []
    early_ids: list[str] = []
    canonical_total = 0
    for worker_id in expected:
        worker_root, summary = summaries_by_worker[worker_id]
        failures = {
            key: _summary_count(summary, key)
            for key in ("timeout", "runtime", "unsupported", "deferred")
        }
        if any(failures.values()):
            raise ValueError(f"worker {worker_id} has failure counts: {failures}")
        canonical_count = int(summary.get("canonical_group_count", 0) or 0)
        terminal_count = _summary_count(summary, "evaluated") + _summary_count(summary, "early")
        if canonical_count <= 0 or terminal_count != canonical_count:
            raise ValueError(
                f"worker {worker_id} terminal count {terminal_count} differs from canonical count {canonical_count}"
            )
        canonical_total += canonical_count
        worker_terminal = 0
        for path in sorted(worker_root.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            match = WORKER_FILE_RE.match(path.name)
            if match is None:
                continue
            kind = str(match.group("kind"))
            extension = str(match.group("extension"))
            if extension == "jsonl":
                jsonl_lines.setdefault(kind, []).extend(
                    line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
                )
                continue
            frame = _csv(path)
            csv_frames.setdefault(kind, []).append(frame)
            if kind in FAILURE_KINDS and not frame.empty:
                raise ValueError(f"worker {worker_id} contains failure rows in {kind}")
            if kind == "leaderboard" and not frame.empty:
                ids = frame["candidate_id"].dropna().astype(str).tolist()
                leaderboard_ids.extend(ids)
                worker_terminal += len(ids)
            elif kind == "early_rejected_strategies" and not frame.empty:
                ids = frame["strategy_id"].dropna().astype(str).tolist()
                early_ids.extend(ids)
                worker_terminal += len(ids)
        if worker_terminal != canonical_count:
            raise ValueError(
                f"worker {worker_id} artifact terminal rows {worker_terminal} differ from canonical count {canonical_count}"
            )

    terminal_ids = leaderboard_ids + early_ids
    if len(set(terminal_ids)) != len(terminal_ids):
        raise ValueError("duplicate canonical strategy ID across workers")
    if len(terminal_ids) != canonical_total:
        raise ValueError("block terminal row count differs from canonical total")

    output.mkdir(parents=True, exist_ok=True)
    block_padded = f"{int(block_id):02d}"
    written: list[Path] = []
    row_counts: dict[str, int] = {}
    for kind in sorted(csv_frames):
        frames = csv_frames[kind]
        nonempty_columns = next((list(frame.columns) for frame in frames if len(frame.columns)), [])
        combined = (
            pd.concat(frames, ignore_index=True, sort=False)
            if frames
            else pd.DataFrame(columns=nonempty_columns)
        )
        path = output / f"{kind}_job_block_{block_padded}.csv"
        combined.to_csv(path, index=False)
        written.append(path)
        row_counts[path.name] = int(len(combined))
    for kind in sorted(jsonl_lines):
        path = output / f"{kind}_job_block_{block_padded}.jsonl"
        content = "\n".join(jsonl_lines[kind])
        path.write_text(content + ("\n" if content else ""), encoding="utf-8")
        written.append(path)
        row_counts[path.name] = int(len(jsonl_lines[kind]))

    fingerprint = next(iter(fingerprints))
    summary = {
        "campaign_fingerprint": fingerprint,
        "block_id": int(block_id),
        "worker_ids": expected,
        "total_jobs_requested": len(expected),
        "total_jobs_completed": len(expected),
        "total_strategies_loaded": canonical_total,
        "total_strategies_evaluated": len(leaderboard_ids),
        "total_strategies_early_rejected": len(early_ids),
        "total_strategies_timed_out": 0,
        "total_strategies_runtime_error": 0,
        "total_strategies_unsupported": 0,
        "total_strategies_slow_deferred": 0,
    }
    summary_path = output / f"summary_job_block_{block_padded}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(summary_path)
    first_campaign = summaries_by_worker[expected[0]][0] / "campaign_manifest.json"
    campaign_output = output / "campaign_manifest.json"
    campaign_output.write_text(first_campaign.read_text(encoding="utf-8"), encoding="utf-8")
    written.append(campaign_output)
    manifest = {
        "campaign_fingerprint": fingerprint,
        "block_id": int(block_id),
        "worker_ids": expected,
        "canonical_group_count": canonical_total,
        "row_counts": row_counts,
        "files": [_digest_record(path, output) for path in sorted(written)],
    }
    (output / "block_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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

"""Inventory strict GTBI worker artifacts and plan exact retry matrices."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable


FAILURE_KEYS = (
    "total_strategies_timed_out",
    "total_strategies_runtime_error",
    "total_strategies_unsupported",
    "total_strategies_slow_deferred",
)


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _count(summary: dict[str, Any], *names: str) -> int:
    return int(next((summary.get(name, 0) for name in names if name in summary), 0) or 0)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _worker_count(campaign: dict[str, Any]) -> int:
    value = dict(campaign.get("counts") or {}).get("worker_count", campaign.get("worker_count"))
    count = int(value or 0)
    if count <= 0:
        raise ValueError("campaign manifest has no positive worker_count")
    return count


def _validate_candidate(
    summary_path: Path,
    *,
    campaign_fingerprint: str,
    worker_count: int,
) -> tuple[int, dict[str, Any], str | None]:
    summary = _read_json(summary_path)
    worker_id = int(summary.get("worker_id", -1))
    if not 0 <= worker_id < worker_count:
        raise ValueError(f"worker {worker_id} is outside expected range 0..{worker_count - 1}")
    fingerprint = str(summary.get("campaign_fingerprint") or "")
    local_campaign_path = summary_path.parent / "campaign_manifest.json"
    if not local_campaign_path.is_file():
        return worker_id, summary, "missing_campaign_manifest"
    local_fingerprint = str(_read_json(local_campaign_path).get("campaign_fingerprint") or "")
    if fingerprint != campaign_fingerprint or local_fingerprint != campaign_fingerprint:
        raise ValueError(f"campaign fingerprint mismatch for worker {worker_id}")
    canonical = int(summary.get("canonical_group_count", 0) or 0)
    evaluated = _count(summary, "total_strategies_evaluated", "strategies_evaluated")
    early = _count(summary, "total_strategies_early_rejected", "strategies_early_rejected")
    if canonical <= 0 or evaluated + early != canonical:
        return worker_id, summary, "terminal_count_mismatch"
    if any(_count(summary, key) for key in FAILURE_KEYS):
        return worker_id, summary, "nonzero_failure_counts"
    return worker_id, summary, None


def inventory_workers(
    *,
    campaign_manifest_path: Path,
    input_roots: Iterable[Path],
    output_dir: Path,
    expected_worker_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Validate available workers and emit only the exact missing retry matrices."""

    campaign = _read_json(Path(campaign_manifest_path))
    fingerprint = str(campaign.get("campaign_fingerprint") or "")
    if not fingerprint:
        raise ValueError("campaign manifest has no campaign_fingerprint")
    worker_count = _worker_count(campaign)
    if expected_worker_ids is None:
        expected = set(range(worker_count))
    else:
        expected_values = [int(value) for value in expected_worker_ids]
        expected = set(expected_values)
        if not expected or len(expected) != len(expected_values):
            raise ValueError("expected_worker_ids must be non-empty and unique")
        outside = sorted(value for value in expected if not 0 <= value < worker_count)
        if outside:
            raise ValueError(f"expected workers outside campaign range: {outside}")
    output = Path(output_dir)
    if output.exists():
        raise ValueError(f"output path already exists: {output}")

    valid: dict[int, Path] = {}
    invalid: list[dict[str, Any]] = []
    for root in (Path(value) for value in input_roots):
        if not root.exists():
            continue
        for summary_path in sorted(root.rglob("worker_summary.json")):
            worker_id, _, reason = _validate_candidate(
                summary_path,
                campaign_fingerprint=fingerprint,
                worker_count=worker_count,
            )
            if worker_id not in expected:
                raise ValueError(
                    f"worker {worker_id} is outside explicitly expected worker set"
                )
            if reason is not None:
                invalid.append(
                    {
                        "worker_id": worker_id,
                        "summary_path": str(summary_path.resolve()),
                        "reason": reason,
                    }
                )
                continue
            if worker_id in valid:
                raise ValueError(f"duplicate valid artifacts for worker {worker_id}")
            valid[worker_id] = summary_path.parent.resolve()

    missing = sorted(expected - set(valid))
    payload = {
        "campaign_fingerprint": fingerprint,
        "worker_count": worker_count,
        "campaign_worker_count": worker_count,
        "expected_worker_count": len(expected),
        "expected_worker_ids": sorted(expected),
        "valid_worker_count": len(valid),
        "invalid_worker_count": len(invalid),
        "missing_worker_count": len(missing),
        "missing_worker_ids": missing,
        "invalid_workers": sorted(invalid, key=lambda row: (int(row["worker_id"]), str(row["summary_path"]))),
        "complete": not missing,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        _write_json(temporary / "matrix_a.json", {"include": [{"worker_id": value} for value in missing if value < 180]})
        _write_json(temporary / "matrix_b.json", {"include": [{"worker_id": value} for value in missing if value >= 180]})
        _write_json(temporary / "inventory_summary.json", payload)
        with (temporary / "selected_workers.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["worker_id", "artifact_root"])
            writer.writeheader()
            for worker_id in sorted(valid):
                writer.writerow({"worker_id": worker_id, "artifact_root": str(valid[worker_id])})
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--input-root", action="append", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--expected-worker-ids",
        help="Optional comma-separated exact worker subset for a strict smoke inventory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    expected_worker_ids = None
    if args.expected_worker_ids is not None:
        expected_worker_ids = [
            int(value.strip())
            for value in str(args.expected_worker_ids).split(",")
            if value.strip()
        ]
    result = inventory_workers(
        campaign_manifest_path=args.campaign_manifest,
        input_roots=args.input_root,
        output_dir=args.output_dir,
        expected_worker_ids=expected_worker_ids,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

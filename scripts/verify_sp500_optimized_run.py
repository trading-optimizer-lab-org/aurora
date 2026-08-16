"""Scientific equivalence gate between optimized and frozen catalog results."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


_ALLOWED_ADDITIVE_INFO_FIELDS = frozenset(
    {
        "positive_weeks",
        "winning_or_positive_weeks",
        "weekly_winning_or_positive_rate",
    }
)


def _load_results(root: Path) -> dict[str, dict[str, Any]]:
    parquet_path = root if root.suffix == ".parquet" else root / "results.parquet"
    if parquet_path.is_file():
        rows = pq.read_table(parquet_path).to_pylist()
        return {
            str(row["strategy_id"]): json.loads(str(row["result_json"]))
            for row in rows
        }
    jsonl_path = root if root.suffix == ".jsonl" else root / "results.jsonl"
    rows = [
        json.loads(line)
        for line in jsonl_path.read_text("utf-8").splitlines()
        if line
    ]
    return {str(row["strategy_id"]): dict(row["result"]) for row in rows}


def _compare(
    expected: Any,
    observed: Any,
    *,
    path: str,
    differences: list[str],
) -> None:
    if path.endswith(".objective_runtime_seconds"):
        return
    if isinstance(expected, dict) and isinstance(observed, dict):
        expected_keys = set(expected)
        observed_keys = set(observed)
        missing = expected_keys - observed_keys
        extra = observed_keys - expected_keys
        allowed_extra = (
            _ALLOWED_ADDITIVE_INFO_FIELDS if path.endswith(".info") else frozenset()
        )
        if missing:
            differences.append(f"{path}:missing:{','.join(sorted(missing))}")
            return
        unexpected = extra - allowed_extra
        if unexpected:
            differences.append(f"{path}:extra:{','.join(sorted(unexpected))}")
            return
        for key in sorted(expected):
            _compare(
                expected[key],
                observed[key],
                path=f"{path}.{key}",
                differences=differences,
            )
        return
    if isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            differences.append(f"{path}:length")
            return
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            _compare(
                left,
                right,
                path=f"{path}[{index}]",
                differences=differences,
            )
        return
    if isinstance(expected, float) or isinstance(observed, float):
        try:
            equal = math.isclose(
                float(expected),
                float(observed),
                rel_tol=1e-10,
                abs_tol=1e-12,
            )
        except (TypeError, ValueError):
            equal = False
        if not equal:
            differences.append(path)
        return
    if expected != observed:
        differences.append(path)


def verify_equivalence(
    optimized: Path,
    reference: Path,
) -> dict[str, object]:
    expected = _load_results(reference)
    observed = _load_results(optimized)
    differences: list[str] = []
    affected_strategy_ids: set[str] = set()
    difference_count = 0
    if set(expected) != set(observed):
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        identity_differences = [
            *(f"missing:{item}" for item in missing),
            *(f"extra:{item}" for item in extra),
        ]
        difference_count += len(identity_differences)
        differences.extend(identity_differences[:100])
        affected_strategy_ids.update(missing)
        affected_strategy_ids.update(extra)
    for strategy_id in sorted(set(expected).intersection(observed)):
        local_differences: list[str] = []
        _compare(
            expected[strategy_id],
            observed[strategy_id],
            path=strategy_id,
            differences=local_differences,
        )
        if local_differences:
            affected_strategy_ids.add(strategy_id)
            difference_count += len(local_differences)
            remaining = max(0, 100 - len(differences))
            differences.extend(local_differences[:remaining])
    return {
        "schema_version": 1,
        "equivalent": difference_count == 0,
        "expected_count": len(expected),
        "observed_count": len(observed),
        "difference_count": difference_count,
        "affected_strategy_count": len(affected_strategy_ids),
        "affected_strategy_ids": sorted(affected_strategy_ids),
        "first_differences": differences[:100],
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-10,
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--optimized", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify_equivalence(args.optimized, args.reference)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(report, sort_keys=True))
    if not report["equivalent"]:
        raise SystemExit("OPTIMIZED_REFERENCE_EQUIVALENCE_FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

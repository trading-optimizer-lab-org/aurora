"""Classify targeted catalog differences without opening protected periods."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.verify_sp500_optimized_run import _compare, _load_results


def classify_result(
    *,
    historical: dict[str, Any],
    optimized: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, object]:
    historical_reference: list[str] = []
    historical_optimized: list[str] = []
    _compare(
        reference,
        historical,
        path="result",
        differences=historical_reference,
    )
    _compare(
        optimized,
        historical,
        path="result",
        differences=historical_optimized,
    )
    return {
        "matches_reference": not historical_reference,
        "matches_optimized": not historical_optimized,
        "reference_difference_count": len(historical_reference),
        "optimized_difference_count": len(historical_optimized),
        "first_reference_differences": historical_reference[:20],
        "first_optimized_differences": historical_optimized[:20],
    }


def _load_historical(root: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("results.jsonl")):
        for line in path.read_text("utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            strategy_id = str(row["strategy_id"])
            result = dict(row["result"])
            previous = results.get(strategy_id)
            if previous is not None and previous != result:
                raise ValueError("DIAGNOSTIC_HISTORICAL_CONFLICT")
            results[strategy_id] = result
    return results


def diagnose(
    *,
    historical_root: Path,
    optimized_root: Path,
    reference_root: Path,
    diagnostic_config: Path,
    catalog_path: Path,
) -> dict[str, object]:
    config = json.loads(diagnostic_config.read_text("utf-8"))
    if (
        config.get("train_end") != "2010-12-31"
        or config.get("validation_opened") is not False
        or config.get("locked_opened") is not False
    ):
        raise ValueError("DIAGNOSTIC_PROTECTED_PERIOD_OPEN")
    strategy_ids = tuple(str(value) for value in config["strategy_ids"])
    historical = _load_historical(historical_root)
    optimized = _load_results(optimized_root)
    reference = _load_results(reference_root)
    catalog = {
        str(row["strategy_id"]): row
        for row in (
            json.loads(line)
            for line in catalog_path.read_text("utf-8").splitlines()
            if line
        )
    }
    missing = [
        strategy_id
        for strategy_id in strategy_ids
        if strategy_id not in historical
        or strategy_id not in optimized
        or strategy_id not in reference
        or strategy_id not in catalog
    ]
    if missing:
        raise ValueError(f"DIAGNOSTIC_RESULT_MISSING:{','.join(missing)}")
    rows = []
    for strategy_id in strategy_ids:
        component = catalog[strategy_id]["components"][0]
        rows.append(
            {
                "strategy_id": strategy_id,
                "lane_id": component["lane_id"],
                "configuration_sha256": component["configuration_sha256"],
                **classify_result(
                    historical=historical[strategy_id],
                    optimized=optimized[strategy_id],
                    reference=reference[strategy_id],
                ),
            }
        )
    return {
        "schema_version": 1,
        "strategy_count": len(rows),
        "rows": rows,
        "reference_match_count": sum(bool(row["matches_reference"]) for row in rows),
        "optimized_match_count": sum(bool(row["matches_optimized"]) for row in rows),
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-root", type=Path, required=True)
    parser.add_argument("--optimized-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--diagnostic-config", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(
        historical_root=args.historical_root,
        optimized_root=args.optimized_root,
        reference_root=args.reference_root,
        diagnostic_config=args.diagnostic_config,
        catalog_path=args.catalog,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

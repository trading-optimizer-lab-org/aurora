"""Aggregate isolated component repeats and expose cross-runner conflicts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


def summarize_receipts(receipts: Iterable[Mapping[str, Any]]) -> dict[str, object]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    checked = list(receipts)
    for row in checked:
        if row.get("validation_opened") is not False or row.get("locked_opened") is not False:
            raise ValueError("COMPONENT_DETERMINISM_BOUNDARY_OPEN")
        grouped[str(row["configuration_sha256"])].append(row)
    components = []
    for component_id, rows in sorted(grouped.items()):
        signal_hashes = sorted({str(row["signal_sha256"]) for row in rows})
        feature_hashes = sorted({str(row["feature_sha256"]) for row in rows})
        components.append(
            {
                "configuration_sha256": component_id,
                "lane_id": str(rows[0]["lane_id"]),
                "repeat_count": len(rows),
                "unique_signal_hash_count": len(signal_hashes),
                "unique_feature_hash_count": len(feature_hashes),
                "signal_hashes": signal_hashes,
                "feature_hashes": feature_hashes,
                "cpu_models": sorted({str(row.get("cpu_model", "")) for row in rows}),
                "runs": [dict(row) for row in rows],
            }
        )
    conflicts = [row for row in components if row["unique_signal_hash_count"] != 1]
    return {
        "schema_version": 1,
        "deterministic": not conflicts,
        "component_count": len(components),
        "repeat_count": len(checked),
        "conflicting_component_count": len(conflicts),
        "conflicting_component_ids": [
            row["configuration_sha256"] for row in conflicts
        ],
        "components": components,
        "validation_opened": False,
        "locked_opened": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--expected-components", type=int, required=True)
    parser.add_argument("--expected-repeats", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipts = [
        json.loads(path.read_text("utf-8"))
        for path in sorted(args.input_root.rglob("receipt.json"))
    ]
    report = summarize_receipts(receipts)
    if (
        report["component_count"] != args.expected_components
        or report["repeat_count"] != args.expected_components * args.expected_repeats
        or any(
            row["repeat_count"] != args.expected_repeats
            for row in report["components"]
        )
    ):
        raise SystemExit("COMPONENT_DETERMINISM_RECEIPTS_INCOMPLETE")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

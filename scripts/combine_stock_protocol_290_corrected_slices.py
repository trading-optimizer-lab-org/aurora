"""Reassemble one corrected 29-exit shard from bounded exit slices."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from scripts.run_stock_protocol_290_corrected_shard import (
    AUDIT_NAME,
    COVERAGE_STEM,
    EXPECTED_EXIT_SPEC_COUNT,
    OPPORTUNITIES_STEM,
    RECONCILIATION_STEM,
    _write_frame_pair,
    _write_json,
    load_corrected_entry_rows,
    reconciliation_by_combination,
)


def _single(root: Path, name: str) -> Path:
    matches = sorted(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected one {name} below {root}, found {len(matches)}")
    return matches[0]


def combine_corrected_slices(
    *,
    slices_root: Path,
    manifest_root: Path,
    entry_index: int,
    period: str,
    output_root: Path,
) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission(
        "stock protocol 290 corrected slice assembly"
    )
    manifest_path, manifest_rows, _ = load_corrected_entry_rows(
        manifest_root, entry_index
    )
    slice_roots = sorted(path.parent for path in slices_root.rglob(AUDIT_NAME))
    if not slice_roots:
        raise FileNotFoundError("no corrected slice audits found")

    audits: list[dict[str, object]] = []
    opportunities: list[pd.DataFrame] = []
    coverages: list[pd.DataFrame] = []
    for root in slice_roots:
        audit = json.loads((root / AUDIT_NAME).read_text(encoding="utf-8"))
        if int(audit["entry_index"]) != entry_index or str(audit["period"]) != period:
            raise ValueError("corrected slice identity mismatch")
        if any(
            bool(audit.get(field))
            for field in (
                "capital_rejection_applied",
                "portfolio_or_sizing_applied",
                "overlaps_discarded",
            )
        ):
            raise ValueError("corrected slice applied a prohibited capital rule")
        audits.append(audit)
        opportunities.append(
            pd.read_parquet(_single(root, f"{OPPORTUNITIES_STEM}.parquet"))
        )
        coverages.append(pd.read_parquet(_single(root, f"{COVERAGE_STEM}.parquet")))

    ranges = sorted((int(audit["exit_start"]), int(audit["exit_end"])) for audit in audits)
    cursor = 0
    for start, end in ranges:
        if start != cursor or end <= start:
            raise ValueError("corrected exit slices overlap or leave a gap")
        cursor = end
    if cursor != EXPECTED_EXIT_SPEC_COUNT:
        raise ValueError("corrected exit slices do not cover all 29 exits")

    coverage = coverages[0].sort_index(axis=1).reset_index(drop=True)
    for candidate in coverages[1:]:
        comparable = candidate.sort_index(axis=1).reset_index(drop=True)
        if not comparable.equals(coverage):
            raise ValueError("corrected exit slices did not reuse the same entry cohort")

    ledger = pd.concat(opportunities, ignore_index=True)
    if ledger["opportunity_id"].duplicated().any():
        raise ValueError("corrected exit slices contain duplicate opportunities")
    if ledger["combination_id"].nunique() != EXPECTED_EXIT_SPEC_COUNT:
        raise ValueError("corrected exit slices do not contain 29 combinations")
    reconciliation = reconciliation_by_combination(
        ledger, manifest_rows, period=period
    )
    reconciliation.insert(0, "entry_index", entry_index)

    output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "opportunities": _write_frame_pair(output_root, OPPORTUNITIES_STEM, ledger),
        "coverage": _write_frame_pair(output_root, COVERAGE_STEM, coverages[0]),
        "reconciliation": _write_frame_pair(
            output_root, RECONCILIATION_STEM, reconciliation
        ),
    }
    base = dict(audits[0])
    base.update(
        {
            "schema_version": 1,
            "entry_index": entry_index,
            "period": period,
            "combination_count": EXPECTED_EXIT_SPEC_COUNT,
            "full_combination_count": EXPECTED_EXIT_SPEC_COUNT,
            "exit_start": 0,
            "exit_end": EXPECTED_EXIT_SPEC_COUNT,
            "entry_count": int(coverages[0]["entry_in_period"].sum()),
            "opportunity_count": len(ledger),
            "reconciled": bool(reconciliation["reconciled"].all()),
            "manifest_path": str(manifest_path),
            "capital_rejection_applied": False,
            "portfolio_or_sizing_applied": False,
            "overlaps_discarded": False,
            "assembled_from_exit_slices": True,
            "slice_count": len(audits),
            "outputs": outputs,
        }
    )
    _write_json(output_root / AUDIT_NAME, base)
    print(json.dumps(base, sort_keys=True))
    return base


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slices-root", type=Path, required=True)
    parser.add_argument("--manifest-root", type=Path, required=True)
    parser.add_argument("--entry-index", type=int, choices=range(10), required=True)
    parser.add_argument("--period", choices=("A", "B", "C"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    combine_corrected_slices(**vars(_parser().parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

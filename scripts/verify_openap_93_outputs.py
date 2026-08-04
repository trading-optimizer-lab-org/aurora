"""Fail-closed verifier for the complete OpenAP 93 current artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aurora.core.execution_policy import require_github_execution
from aurora.research.openap_93.current_pipeline import CURRENT_USABLE_CLASSES
from aurora.research.openap_93.registry import FidelityClass


MANDATORY_FILES = (
    "signals_93_current.parquet",
    "signals_93_current.csv",
    "score_185_current.parquet",
    "score_185_current.csv",
    "coverage_93.csv",
    "source_coverage_matrix.csv",
    "source_ablation.csv",
    "validation_per_signal.csv",
    "validation_per_month.parquet",
    "validation_summary.md",
    "selected_sources.json",
    "sources.lock.json",
    "run_manifest.json",
    "data_lineage.json",
    "failures.json",
    "openap_reference_metadata.json",
    "institutional_input_audit.csv",
    "FINAL_REPORT.md",
)

COVERAGE_COLUMNS = {
    "signal",
    "status",
    "fidelity_class",
    "current_usable",
    "exact_formula",
    "primary_source",
    "fallback_source",
    "source_domains",
    "latest_period_end",
    "latest_available_at",
    "natural_frequency",
    "universe_count",
    "non_null_count",
    "coverage_pct",
    "validation_start",
    "validation_end",
    "paired_observations",
    "spearman",
    "extreme_decile_agreement",
    "license",
    "terms_status",
    "scraping_required",
    "reason_if_missing",
    "openap_script",
    "implementation_file",
}

SCORE_COLUMNS = {
    "score_strict_current",
    "score_max_current",
    "score_research_all",
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_output(root: str | Path) -> dict[str, Any]:
    output = Path(root)
    missing = [name for name in MANDATORY_FILES if not (output / name).is_file()]
    empty = [
        name
        for name in MANDATORY_FILES
        if (output / name).is_file() and (output / name).stat().st_size == 0
    ]
    _require(not missing, f"Missing mandatory files: {missing}")
    _require(not empty, f"Empty mandatory files: {empty}")

    manifest = _load_json(output / "run_manifest.json")
    lineage = _load_json(output / "data_lineage.json")
    failures = _load_json(output / "failures.json")
    selected = _load_json(output / "selected_sources.json")
    reference = _load_json(output / "openap_reference_metadata.json")

    signals = pd.read_parquet(output / "signals_93_current.parquet")
    signals_csv = pd.read_csv(output / "signals_93_current.csv")
    scores = pd.read_parquet(output / "score_185_current.parquet")
    scores_csv = pd.read_csv(output / "score_185_current.csv")
    coverage = pd.read_csv(output / "coverage_93.csv")
    validation = pd.read_csv(output / "validation_per_signal.csv")
    source_matrix = pd.read_csv(output / "source_coverage_matrix.csv")
    source_ablation = pd.read_csv(output / "source_ablation.csv")

    _require(len(coverage) == 93, "coverage_93.csv must contain exactly 93 rows")
    _require(coverage["signal"].nunique() == 93, "coverage signals must be unique")
    _require(COVERAGE_COLUMNS <= set(coverage.columns), "coverage contract is incomplete")
    _require(coverage["status"].notna().all(), "Every signal requires a final status")
    allowed_fidelity = {item.value for item in FidelityClass}
    _require(
        set(coverage["fidelity_class"].dropna()) <= allowed_fidelity,
        "Unknown fidelity class in coverage",
    )

    _require(signals["signal"].nunique() == 93, "Signal table does not contain all 93")
    _require(len(signals) == len(signals_csv), "CSV and Parquet signal row counts differ")
    _require(signals["security_id"].notna().all(), "Null security_id in signal table")
    _require(signals["ticker"].notna().all(), "Null ticker in signal table")
    _require(
        not signals.duplicated(["security_id", "signal"]).any(),
        "Duplicate security/signal observations",
    )
    universe_count = int(signals["security_id"].nunique())
    _require(
        len(signals) == universe_count * 93,
        "Signal table is not a complete universe-by-signal panel",
    )
    formation = pd.Timestamp(manifest["formation_at"]).tz_localize(None)
    available = pd.to_datetime(signals["available_at"], errors="coerce").dt.tz_localize(None)
    _require(available.dropna().le(formation).all(), "available_at exceeds formation_at")
    expected_usable = signals["fidelity_class"].isin(CURRENT_USABLE_CLASSES) & signals[
        "value"
    ].notna()
    _require(
        not (signals["current_usable"].astype(bool) & ~expected_usable).any(),
        "An unevidenced class or null value was marked current_usable",
    )

    _require(len(scores) == len(scores_csv), "CSV and Parquet score row counts differ")
    _require(len(scores) == universe_count, "Score table does not cover the full universe")
    _require(not scores["security_id"].duplicated().any(), "Duplicate score security_id")
    _require(SCORE_COLUMNS <= set(scores.columns), "Required score variants are missing")

    _require(len(validation) == 93, "Validation table must contain all 93 signals")
    _require(validation["signal"].nunique() == 93, "Validation signals must be unique")
    _require(not source_matrix.empty, "Source coverage matrix is empty")
    _require(source_matrix["signal"].nunique() == 93, "Source matrix misses signals")
    _require(not source_ablation.empty, "Source ablation is empty")
    _require(bool(selected.get("selected_source_ids")), "No source combination selected")

    _require(manifest.get("input_signals") == 93, "Manifest input_signals is not 93")
    _require(manifest.get("universe_count") == universe_count, "Manifest universe mismatch")
    _require(manifest.get("rows") == len(signals), "Manifest signal row mismatch")
    _require(manifest.get("locked_opened") is False, "Locked data was opened")
    _require(
        manifest.get("validation_used_for_selection") is False,
        "Validation was used for selection",
    )
    _require(manifest.get("cost_eur") == 0, "Pipeline is not zero-cost")
    _require(manifest.get("api_keys_required") is False, "Pipeline requires an API key")
    _require(
        manifest.get("manual_actions_required") is False,
        "Pipeline requires manual intervention",
    )
    fidelity_counts = manifest.get("fidelity_counts", {})
    _require(sum(fidelity_counts.values()) == 93, "Manifest fidelity counts do not sum to 93")
    _require(
        manifest.get("current_usable_signal_count")
        == int(coverage["current_usable"].astype(bool).sum()),
        "Manifest current-usable count mismatch",
    )

    _require(reference.get("reference_only") is True, "OpenAP release is not reference-only")
    _require(reference.get("current_signal_source") is False, "Stale OpenAP values became current")
    _require(
        reference.get("identifier_columns") == ["permno", "yyyymm"],
        "Unexpected official-reference identifiers",
    )
    _require("signal_formulas" in lineage, "Formula lineage is missing")
    _require(len(lineage["signal_formulas"]) == 93, "Formula lineage must cover 93 signals")

    failed_signals = {row["signal"] for row in failures.get("signals", [])}
    expected_failed = set(coverage.loc[~coverage["current_usable"].astype(bool), "signal"])
    _require(failed_signals == expected_failed, "Failure ledger does not match coverage")

    hashes = manifest.get("output_hashes", {})
    _require(bool(hashes), "Manifest output hashes are missing")
    for relative, expected in hashes.items():
        path = output / relative
        _require(path.is_file(), f"Hashed output is missing: {relative}")
        _require(_sha256(path) == expected, f"Hash mismatch: {relative}")
    actual_bytes = sum((output / relative).stat().st_size for relative in hashes)
    _require(
        actual_bytes == manifest.get("output_total_bytes_excluding_manifest"),
        "Manifest output byte count mismatch",
    )

    report = (output / "FINAL_REPORT.md").read_text(encoding="utf-8")
    _require(report.startswith("RESULTADO:"), "FINAL_REPORT.md lacks numeric opening")
    _require("93" in report, "FINAL_REPORT.md does not state the 93-signal result")

    return {
        "verified": True,
        "signals": 93,
        "universe_count": universe_count,
        "rows": len(signals),
        "current_usable_signal_count": manifest["current_usable_signal_count"],
        "selected_source_count": len(selected["selected_source_ids"]),
        "hashed_outputs_verified": len(hashes),
    }


def main() -> int:
    require_github_execution("OpenAP 93 output verification")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(verify_output(args.output_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Create an honest train-only multiple-testing diagnostic."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
import json
from pathlib import Path


def _row_annual_rows(row: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = row.get("annual_rows", [])
    if isinstance(value, str):
        value = json.loads(value)
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def build_multiple_testing_report(
    rows: Iterable[Mapping[str, object]],
    *,
    raw_universe: int,
    canonical_universe: int,
    campaign_recipe_count: int,
    pareto_count: int,
    reserve_count: int,
    robust_count: int,
    adaptive_generations: int,
) -> dict[str, object]:
    total = 0
    cells: Counter[tuple[int, int, int]] = Counter()
    strata: Counter[str] = Counter()
    best_by_year: dict[int, float] = {}
    for row in rows:
        total += 1
        cells[
            (
                int(row.get("positive_weeks", 0)),
                int(row.get("positive_months", 0)),
                int(row.get("joint_positive_above_spy_years", 0)),
            )
        ] += 1
        composition = row.get("composition", {})
        if isinstance(composition, str):
            composition = json.loads(composition)
        if not isinstance(composition, Mapping):
            composition = {}
        key = f"{row.get('strategy_kind', 'unknown')}|{composition.get('kind', 'unknown')}|{composition.get('direction', 'unknown')}"
        strata[key] += 1
        for annual in _row_annual_rows(row):
            year = int(annual["year"])
            value = float(annual["strategy_return"])
            best_by_year[year] = max(value, best_by_year.get(year, float("-inf")))
    return {
        "schema_version": 1,
        "status": "diagnostic_not_validation",
        "raw_universe": raw_universe,
        "canonical_universe": canonical_universe,
        "campaign_recipe_count": campaign_recipe_count,
        "observed_result_count": total,
        "canonical_coverage_fraction": campaign_recipe_count / canonical_universe,
        "formal_duplicate_count": raw_universe - canonical_universe,
        "strata_count": len(strata),
        "strata_sizes": dict(sorted(strata.items())),
        "strata_sampled": dict(sorted(strata.items())),
        "pareto_count": pareto_count,
        "reserve_count": reserve_count,
        "robust_count": robust_count,
        "objective_cell_count": len(cells),
        "objective_cell_distribution": [
            {"positive_weeks": w, "positive_months": m, "joint_positive_above_spy_years": y, "count": count}
            for (w, m, y), count in sorted(cells.items(), reverse=True)
        ],
        "best_observed_strategy_return_by_year": {str(year): value for year, value in sorted(best_by_year.items())},
        "adaptive_generations_on_train": adaptive_generations,
        "null_diagnostic": {
            "status": "not_run",
            "reason": "Final Atlas rows retain position hashes, not decision vectors; no null result is presented as evidence.",
        },
        "limitations": [
            "Millions of hypotheses increase the chance of an extreme result by luck.",
            "This report describes TRAIN selection only and is not out-of-sample validation.",
            "Validation 2011-2020 and locked 2021+ were not read.",
        ],
        "validation_opened": False,
        "locked_opened": False,
    }


def _read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("ATLAS_MULTIPLE_TESTING_ROW_OBJECT_REQUIRED")
                yield row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--catalog-manifest", type=Path, required=True)
    parser.add_argument("--reduction-receipt", type=Path, required=True)
    parser.add_argument("--robustness-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--adaptive-generations", type=int, default=0)
    args = parser.parse_args()
    catalog = json.loads(args.catalog_manifest.read_text("utf-8"))
    reduction = json.loads(args.reduction_receipt.read_text("utf-8"))
    robustness = json.loads(args.robustness_receipt.read_text("utf-8"))
    report = build_multiple_testing_report(
        _read_jsonl(args.results),
        raw_universe=int(catalog["counts"]["raw_requested_recipe_count"]),
        canonical_universe=int(catalog["counts"]["canonical_recipe_count"]),
        campaign_recipe_count=int(reduction["requested_recipe_count"]),
        pareto_count=int(reduction["pareto_recipe_count"]),
        reserve_count=int(reduction.get("reserve_recipe_count", 0)),
        robust_count=int(robustness.get("green_count", 0)),
        adaptive_generations=args.adaptive_generations,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "multiple_testing_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "multiple_testing_report.md").write_text(
        "# Atlas 1: diagnóstico de multiple testing\n\n"
        "Este documento describe resultados de TRAIN hasta 2010-12-31. No es validación fuera de muestra.\n\n"
        f"- Recetas de campaña: {report['campaign_recipe_count']}\n"
        f"- Universo canónico: {report['canonical_universe']}\n"
        f"- Cobertura canónica: {report['canonical_coverage_fraction']:.12f}\n"
        f"- Pareto: {report['pareto_count']}\n"
        f"- Robustas en TRAIN: {report['robust_count']}\n\n"
        "## Limitaciones\n\n"
        "- Buscar millones de hipótesis eleva el máximo fortuito.\n"
        "- Validation 2011-2020 y locked 2021+ permanecen cerrados.\n"
        "- Ninguna candidata está validada fuera de muestra.\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Assemble the final evidence-backed, train-only Atlas audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def create_audit(*, preflight: Path, final_results: Path, robustness: Path, multiple_testing: Path, output: Path, run_id: str, commit_sha: str) -> None:
    plan = json.loads((preflight / "plan" / "atlas_run_plan.json").read_text("utf-8"))
    catalog = json.loads((preflight / "atlas" / "manifest.json").read_text("utf-8"))
    reduction = json.loads((final_results / "reduction_receipt.json").read_text("utf-8"))
    robust = json.loads((robustness / "robustness_receipt.json").read_text("utf-8"))
    multiple = json.loads((multiple_testing / "multiple_testing_report.json").read_text("utf-8"))
    text = f"""# SP500 Atlas 1 — auditoría final de ejecución

Estado: **TRAIN_ONLY_COMPLETE** para la campaña finita ejecutada. Esto no es validación fuera de muestra.

## Identidad

- Run principal: `{run_id}`
- Commit de workflow: `{commit_sha}`
- Commit científico: `{plan['implementation_commit_sha']}`
- Plan: `{plan['plan_sha256']}`
- Catálogo: `{plan['catalog_manifest_sha256']}`
- Selección estratificada: `{plan['selection_sha256']}`
- Reducción: `{reduction['results_sha256']}`
- Robustez: `{robust['robustness_sha256']}`

## Datos y límites

- Entrenamiento: hasta `{plan['train_end']}` inclusive.
- Universo canónico: `{catalog['counts']['canonical_recipe_count']}` recetas.
- Universo bruto declarado: `{catalog['counts']['raw_requested_recipe_count']}`.
- Campaña evaluada: `{reduction['verified_recipe_count']}` recetas de `{reduction['requested_recipe_count']}`.
- Cobertura canónica: `{reduction['requested_recipe_count'] / catalog['counts']['canonical_recipe_count']:.12f}`.
- `validation_opened=false`.
- `locked_opened=false`.

## Integridad

- Fragmentos verificados: `{reduction['verified_shard_count']}`.
- Pareto: `{reduction['pareto_recipe_count']}` recetas en `{reduction['pareto_cell_count']}` celdas.
- Reserva: `{reduction.get('reserve_recipe_count', 0)}`.
- Robustas TRAIN: `{robust['green_count']}`.
- Frágiles TRAIN: `{robust['amber_count']}`.
- Rojas: `{robust['red_count']}`.
- Inválidas: `{robust['invalid_count']}`.
- Resultados completos preservados y hash verificado por el reductor.

## Multiple testing

- Recetas de campaña: `{multiple['campaign_recipe_count']}`.
- Estratos: `{multiple['strata_count']}`.
- Generaciones adaptativas sobre TRAIN: `{multiple['adaptive_generations_on_train']}`.
- El máximo observado puede contener selección fortuita por búsqueda masiva.
- El diagnóstico no afirma p-values ni validación futura; el null bootstrap no se ejecutó porque los resultados publicados conservan hashes de posiciones, no vectores completos.

## Siguiente paso

Validation 2011–2020 y locked 2021+ siguen cerrados. Ninguna estrategia es válida fuera de muestra. Hace falta una decisión explícita posterior para abrir validation; no se crea Atlas 2 automáticamente.
"""
    Path(output).write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--final-results", type=Path, required=True)
    parser.add_argument("--robustness", type=Path, required=True)
    parser.add_argument("--multiple-testing", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    args = parser.parse_args()
    create_audit(
        preflight=args.preflight,
        final_results=args.final_results,
        robustness=args.robustness,
        multiple_testing=args.multiple_testing,
        output=args.output,
        run_id=args.run_id,
        commit_sha=args.commit_sha,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate and assemble the complete scientific stock-protocol artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from aurora.research.stock_protocol.governance import (
    implementation_matrix,
    unsupported_data_requirements,
)
from aurora.research.stock_protocol.manifest import load_protocol_manifest
from aurora.research.stock_protocol.pareto import pareto_frontier, pareto_frontiers_by


PHASE_OUTPUTS = {
    "signal_results.csv": "signal_layer_results.csv",
    "weight_results.csv": "weight_layer_results.csv",
    "entry_results.csv": "entry_layer_results.csv",
    "exit_results.csv": "exit_layer_results.csv",
    "portfolio_results.csv": "portfolio_layer_results.csv",
    "cost_results.csv": "cost_scenarios.csv",
    "walk_forward_results.csv": "walk_forward_results.csv",
    "robustness_results.csv": "robustness_results.csv",
}
PASS_THROUGH_FILES = (
    "yearly_results.csv",
    "parameter_stability.csv",
    "statistical_tests.csv",
    "holdout_2016_2020.csv",
)
LEDGER_DIRECTORIES = (
    "daily_equity_curves",
    "trade_ledgers",
    "position_ledgers",
)
MAXIMIZE = ("cagr", "sortino", "calmar", "return_per_capital_day")
MINIMIZE = (
    "drawdown_abs",
    "expected_shortfall_abs",
    "turnover",
    "average_days_invested",
    "total_costs",
)


def _require_inputs(input_root: Path) -> None:
    required_files = [*PHASE_OUTPUTS, *PASS_THROUGH_FILES, "data_audit.json"]
    missing = [name for name in required_files if not (input_root / name).is_file()]
    for directory in LEDGER_DIRECTORIES:
        path = input_root / directory
        if not path.is_dir() or not any(child.is_file() for child in path.rglob("*")):
            missing.append(directory)
    if missing:
        raise ValueError(f"missing required input(s): {sorted(missing)}")


def _strict_bool_false(series: pd.Series, label: str) -> None:
    normalized = series.astype(str).str.strip().str.lower()
    if normalized.isin({"true", "1", "yes"}).any():
        raise ValueError(f"locked data detected in {label}")


def _validate_phase(frame: pd.DataFrame, label: str, data_end: str) -> pd.DataFrame:
    if frame.empty:
        raise ValueError(f"phase {label} is empty")
    if "locked_opened" not in frame or "data_end" not in frame:
        raise ValueError(f"phase {label} lacks locked audit columns")
    _strict_bool_false(frame["locked_opened"], label)
    phase_ends = pd.to_datetime(frame["data_end"], errors="raise").dt.normalize()
    maximum_end = pd.Timestamp(data_end).normalize()
    if phase_ends.gt(maximum_end).any() or phase_ends.ge(pd.Timestamp("2021-01-01")).any():
        raise ValueError(f"phase {label} crosses data boundary")
    numeric = [column for column in (*MAXIMIZE, "max_drawdown", "expected_shortfall_5", "turnover", "average_days_invested", "total_costs") if column in frame]
    if numeric:
        values = frame[numeric].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(f"phase {label} contains non-finite metrics")
    return frame


def _pareto_source(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "candidate_id",
        *MAXIMIZE,
        "max_drawdown",
        "expected_shortfall_5",
        "turnover",
        "average_days_invested",
        "total_costs",
        "horizon_sessions",
        "cost_bps",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"portfolio results lack Pareto fields: {sorted(missing)}")
    source = frame.copy()
    source["drawdown_abs"] = pd.to_numeric(source["max_drawdown"], errors="coerce").abs()
    source["expected_shortfall_abs"] = pd.to_numeric(
        source["expected_shortfall_5"], errors="coerce"
    ).abs()
    return source


def _copy_directory(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _write_recommendation(
    output_root: Path,
    matrix: pd.DataFrame,
    unsupported: pd.DataFrame,
    frontier: pd.DataFrame,
) -> None:
    if frontier.empty:
        top = "No configuration survived the finite-metric Pareto screen."
    else:
        names = ", ".join(frontier["candidate_id"].astype(str).drop_duplicates().head(10))
        top = f"Non-dominated research candidates: {names}."
    fully = int(matrix["implementation_status"].eq("fully_implemented").sum())
    limited = int(
        matrix["implementation_status"].eq(
            "implemented_with_documented_limitation"
        ).sum()
    )
    text = f"""# Recomendacion final

## Resultado

{top}

El resultado es investigacion preliminar, no una estimacion definitiva de
rentabilidad. El universo es un backfill del universo actual y tiene
survivorship bias. Ninguna candidata puede promoverse a estrategia definitiva
sin universo historico point-in-time y retornos de exclusiones de cotizacion.

## Implementacion

- Pruebas totalmente implementadas: {fully}
- Pruebas con limitaciones documentadas: {limited}
- Pruebas no soportadas por datos ausentes: {len(unsupported)}
- Locked desde 2021-01-01: cerrado
- Holdout 2016-2020: evaluado una sola vez despues de congelar decisiones

## Errores del run anterior

El run anterior trataba scores finitos como compras, desacoplaba capas,
componia operaciones como si fueran una cartera y presentaba variantes
nominales que no cambiaban la simulacion. Su Pareto era un ranking disfrazado.

## Correcciones aplicadas

Se implementaron rankings transversales reales, señales binarias estrictas,
entrada causal en la siguiente apertura, cartera diaria con efectivo y
posiciones solapadas, pesos efectivos, costes netos, frozen layers con hashes,
walk-forward purgado, robustez distribuida y Pareto no dominada real.

## Valor marginal, entradas y salidas

Los CSV por capa permiten medir el valor marginal de cada familia. Las entradas
comparan compra inmediata, breakout, consolidacion, RVOL y filtros SMA. Las
salidas comparan histeresis, fallo de breakout, minimos, SMA50, ATR, tiempo y
take profit. Una mejora solo cuenta si sobrevive neta, fuera de muestra y sin
empeorar de forma material riesgo, duracion o capacidad.

## Sizing y costes

El sizing se aplica a la cartera, incluyendo igual ponderacion, volatilidad
inversa y limites soportados. La Pareto final se construye desde escenarios de
costes netos de 5, 10, 25 y 50 bps por lado, no desde resultados brutos.

## Walk-forward, robustez y holdout

La seleccion usa exclusivamente datos anteriores a 2016 mediante walk-forward
expansivo 10/3/1 con purga. La robustez incluye bootstrap por bloques, Sharpe
deflactado, CSCV/PBO, FDR y exclusiones de grupos disponibles. El holdout
2016-2020 se mira una sola vez y no se usa para reajustar parametros.

## Pareto

La frontera maximiza CAGR neto, Sortino, Calmar y retorno por capital-dia, y
minimiza drawdown, expected shortfall, turnover, duracion y costes. No se elige
una estrategia por Sharpe aislado.

## Datos pendientes

Faltan fundamentales y estimaciones point-in-time, delistings, clasificacion
sectorial historica y un universo completamente libre de survivorship bias.
Hasta tenerlos, no puede afirmarse rentabilidad definitiva ni abrirse locked.

## Regla de decision

Si robustez u holdout no sobreviven, la conclusion correcta es que no se ha
encontrado una estrategia valida. La arquitectura recomendada solo se acepta si
la evidencia sostiene las tres capas: seleccion, entrada y salida/riesgo.
"""
    (output_root / "final_recommendation.md").write_text(text, encoding="utf-8")


def finalize_scientific_artifact(
    input_root: Path,
    output_root: Path,
    manifest_path: Path,
) -> Path:
    """Build a complete artifact or fail; partial success is not permitted."""

    manifest = load_protocol_manifest(manifest_path)
    _require_inputs(input_root)
    data_audit = json.loads((input_root / "data_audit.json").read_text(encoding="utf-8"))
    if data_audit.get("locked_opened") is not False or int(data_audit.get("locked_rows", 0)) != 0:
        raise ValueError("locked data detected in data audit")
    if str(data_audit.get("data_end")) != manifest.data_end:
        raise ValueError("data audit crosses data boundary")
    if data_audit.get("survivorship_limited") is not True:
        raise ValueError("current run must acknowledge survivorship limitation")

    phase_frames: dict[str, pd.DataFrame] = {}
    for source_name in PHASE_OUTPUTS:
        phase_frames[source_name] = _validate_phase(
            pd.read_csv(input_root / source_name), source_name, manifest.data_end
        )

    holdout = pd.read_csv(input_root / "holdout_2016_2020.csv")
    if holdout.empty or holdout["evaluation_count"].ne(1).any():
        raise ValueError("final holdout must be evaluated exactly once")
    if holdout["selection_used"].astype(str).str.lower().isin({"true", "1"}).any():
        raise ValueError("final holdout cannot be used for selection")
    _strict_bool_false(holdout["locked_opened"], "holdout")

    output_root.mkdir(parents=True, exist_ok=True)
    for source_name, output_name in PHASE_OUTPUTS.items():
        phase_frames[source_name].to_csv(output_root / output_name, index=False)
    for name in PASS_THROUGH_FILES:
        shutil.copy2(input_root / name, output_root / name)
    for directory in LEDGER_DIRECTORIES:
        _copy_directory(input_root / directory, output_root / directory)

    matrix = implementation_matrix(manifest)
    unsupported = unsupported_data_requirements(manifest)
    matrix.to_csv(output_root / "implementation_matrix.csv", index=False)
    unsupported.to_csv(output_root / "unsupported_missing_data.csv", index=False)
    (output_root / "protocol_manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    (output_root / "data_audit.json").write_text(
        json.dumps(data_audit, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    source = _pareto_source(phase_frames["cost_results.csv"])
    frontier = pareto_frontier(source, maximize=MAXIMIZE, minimize=MINIMIZE)
    by_cost = pareto_frontiers_by(
        source,
        group_columns=["cost_bps"],
        maximize=MAXIMIZE,
        minimize=MINIMIZE,
    )
    by_horizon = pareto_frontiers_by(
        source,
        group_columns=["horizon_sessions"],
        maximize=MAXIMIZE,
        minimize=MINIMIZE,
    )
    frontier.to_csv(output_root / "pareto_frontier.csv", index=False)
    by_cost.to_csv(output_root / "pareto_by_cost.csv", index=False)
    by_horizon.to_csv(output_root / "pareto_by_horizon.csv", index=False)

    summary = {
        "tests_total": int(len(matrix)),
        "tests_fully_implemented": int(
            matrix["implementation_status"].eq("fully_implemented").sum()
        ),
        "tests_implemented_with_documented_limitation": int(
            matrix["implementation_status"].eq(
                "implemented_with_documented_limitation"
            ).sum()
        ),
        "tests_unsupported_missing_data": int(len(unsupported)),
        "pareto_candidates": int(frontier["candidate_id"].nunique()),
        "locked_opened": False,
        "data_end": manifest.data_end,
        "survivorship_limited": True,
        "counts_derived_from_files": True,
        "partial": False,
    }
    (output_root / "final_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "run_audit.md").write_text(
        "# Scientific Stock Protocol Run Audit\n\n"
        "- All required source files were present.\n"
        "- All phase metrics were finite.\n"
        "- `locked_opened=false`; no row from 2021-01-01 onward was used.\n"
        "- Holdout 2016-2020 was evaluated exactly once after freezing.\n"
        "- `survivorship_limited=true`; current-universe backfill is preliminary.\n"
        "- Pareto outputs are non-dominated fronts, not Sharpe rankings.\n",
        encoding="utf-8",
    )
    _write_recommendation(output_root, matrix, unsupported, frontier)
    return output_root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--manifest", dest="manifest_path", type=Path, required=True)
    args = parser.parse_args()
    print(finalize_scientific_artifact(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

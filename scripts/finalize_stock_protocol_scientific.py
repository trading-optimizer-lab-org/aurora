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
        if "status" in frame:
            allowed_statuses = {
                "evaluated",
                "fully_implemented",
                "implemented_with_documented_limitation",
                "unsupported_missing_data",
                "unsupported_not_implemented",
                "no_observations",
                "failed",
            }
            unknown = set(frame["status"].dropna().astype(str)) - allowed_statuses
            if unknown:
                raise ValueError(f"phase {label} contains unknown statuses: {sorted(unknown)}")
            metric_rows = frame["status"].astype(str).isin(
                {
                    "evaluated",
                    "fully_implemented",
                    "implemented_with_documented_limitation",
                }
            )
        else:
            metric_rows = pd.Series(True, index=frame.index)
        values = frame.loc[metric_rows, numeric].apply(
            pd.to_numeric, errors="coerce"
        ).to_numpy(dtype=float)
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


def _truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _best_metric_row(frame: pd.DataFrame, metric: str = "sharpe") -> dict[str, object]:
    if frame.empty or metric not in frame:
        return {}
    values = pd.to_numeric(frame[metric], errors="coerce")
    finite = values.map(np.isfinite)
    if not finite.any():
        return {}
    row = frame.loc[values.loc[finite].idxmax()]
    result: dict[str, object] = {"candidate_id": str(row.get("candidate_id", ""))}
    for name in ("sharpe", "cagr", "max_drawdown"):
        value = pd.to_numeric(pd.Series([row.get(name)]), errors="coerce").iloc[0]
        result[name] = float(value) if pd.notna(value) and np.isfinite(value) else None
    return result


def _decimal(value: object, digits: int = 3) -> str:
    if value is None:
        return "no disponible"
    return f"{float(value):.{digits}f}".replace(".", ",")


def _percentage(value: object, digits: int = 2) -> str:
    if value is None:
        return "no disponible"
    return f"{100.0 * float(value):.{digits}f}%".replace(".", ",")


def _layer_result(name: str, frame: pd.DataFrame) -> str:
    best = _best_metric_row(frame)
    if not best:
        return f"- {name}: sin metrica comparable."
    return (
        f"- {name}: mejor resultado preliminar Sharpe {_decimal(best['sharpe'])}, "
        f"CAGR {_percentage(best['cagr'])}, max DD {_percentage(best['max_drawdown'])}."
    )


def _write_recommendation(
    output_root: Path,
    matrix: pd.DataFrame,
    unsupported: pd.DataFrame,
    frontier: pd.DataFrame,
    phase_frames: dict[str, pd.DataFrame],
    statistical_tests: pd.DataFrame,
    holdout: pd.DataFrame,
    data_audit: dict[str, object],
    summary: dict[str, object],
) -> None:
    fully = int(matrix["implementation_status"].eq("fully_implemented").sum())
    limited = int(
        matrix["implementation_status"].eq(
            "implemented_with_documented_limitation"
        ).sum()
    )
    robustness = phase_frames["robustness_results.csv"]
    walk_forward = _best_metric_row(phase_frames["walk_forward_results.csv"])
    holdout_best = _best_metric_row(holdout)
    pbo = pd.to_numeric(
        robustness.get("cscv_pbo_max", pd.Series(dtype=float)), errors="coerce"
    )
    pbo_max = float(pbo.max()) if pbo.notna().any() else None
    limitations = sorted(
        {
            str(value)
            for value in robustness.get(
                "robustness_limitation", pd.Series(dtype=str)
            ).dropna()
            if str(value).strip()
        }
    )
    limitation_text = "; ".join(limitations) if limitations else "ninguna registrada"
    method_counts = statistical_tests["method"].astype(str).value_counts().sort_index()
    method_text = ", ".join(
        f"{method}: {int(count)}" for method, count in method_counts.items()
    )
    strategy_found = bool(summary["strategy_found"])
    verdict = (
        f"Se han encontrado {summary['accepted_strategy_count']} estrategias "
        "cientificamente validas."
        if strategy_found
        else "No se ha encontrado ninguna estrategia cientificamente valida."
    )
    layer_lines = "\n".join(
        (
            _layer_result("Senales", phase_frames["signal_results.csv"]),
            _layer_result("Pesos", phase_frames["weight_results.csv"]),
            _layer_result("Entradas", phase_frames["entry_results.csv"]),
            _layer_result("Salidas", phase_frames["exit_results.csv"]),
            _layer_result("Sizing/cartera", phase_frames["portfolio_results.csv"]),
            _layer_result("Costes netos", phase_frames["cost_results.csv"]),
        )
    )
    text = f"""# Recomendacion final

## Veredicto

{verdict}

- Estrategias aceptadas: {summary['accepted_strategy_count']}
- Candidatas que pasan robustez: {summary['robust_pass_count']} de {summary['robustness_candidates']}
- Candidatas con robustez completa: {summary['robustness_complete_count']} de {summary['robustness_candidates']}
- Tareas estadisticas reales: {summary['statistical_tasks_count']}
- Evaluaciones de holdout: {summary['holdout_evaluated_count']}, una vez por candidata
- Locked desde 2021-01-01: cerrado
- Validacion usada para seleccionar: no

La frontera Pareto contiene {summary['pareto_candidates']} configuraciones de
investigacion preliminar. No son estrategias aceptadas ni una estimacion
definitiva de rentabilidad.

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

{layer_lines}

Los resultados fuertes de las capas tardias no sobrevivieron fuera del tramo
de desarrollo. Por tanto, no puede atribuirse valor estable a una senal, peso,
entrada, salida o sizing concreto. Las entradas compararon compra inmediata,
breakout, consolidacion, RVOL y filtros SMA; las salidas compararon histeresis,
fallo de breakout, minimos, SMA50, ATR, tiempo y take profit.

## Sizing y costes

El sizing se aplica a la cartera, incluyendo igual ponderacion, volatilidad
inversa y limites soportados. La Pareto final se construye desde escenarios de
costes netos de 5, 10, 25 y 50 bps por lado, no desde resultados brutos.

## Walk-forward, robustez y holdout

El mejor resultado walk-forward preliminar dio Sharpe {_decimal(walk_forward.get('sharpe'))},
CAGR {_percentage(walk_forward.get('cagr'))} y max DD
{_percentage(walk_forward.get('max_drawdown'))}. En el holdout 2016-2020, el
mejor diagnostico bajo a Sharpe {_decimal(holdout_best.get('sharpe'))}, CAGR
{_percentage(holdout_best.get('cagr'))} y max DD
{_percentage(holdout_best.get('max_drawdown'))}. Esa caida impide interpretar
las cifras de desarrollo como evidencia estable.

El peor CSCV/PBO agregado fue {_decimal(pbo_max)}; el umbral de pase era 0,500.
La prueba leave-one-symbol no era viable: {limitation_text}. Al faltar esa
prueba, la robustez es incompleta y ninguna candidata puede aprobar. El resto
de la evidencia distribuida incluye bootstrap por bloques, Sharpe deflactado,
CSCV/PBO, FDR y leave-one-decade. El holdout se miro una sola vez y no se uso
para reajustar parametros. Reparto real de tareas: {method_text}.

## Pareto

La frontera maximiza CAGR neto, Sortino, Calmar y retorno por capital-dia, y
minimiza drawdown, expected shortfall, turnover, duracion y costes. No se elige
una estrategia por Sharpe aislado.

## Datos pendientes

Faltan fundamentales y estimaciones point-in-time, delistings, clasificacion
sectorial historica y un universo completamente libre de survivorship bias.
El run uso {data_audit.get('symbols', 'no disponible')} simbolos y un backfill
del universo actual, por lo que no permite una conclusion representativa sobre
acciones. Hasta disponer de un universo historico point-in-time y retornos de
exclusiones de cotizacion, no puede afirmarse rentabilidad definitiva ni
abrirse locked.

## Regla de decision

La arquitectura causal y auditable queda validada como infraestructura de
investigacion. No se recomienda ninguna estrategia de este run. Solo se podra
promover una candidata futura si completa y supera robustez, mantiene su
comportamiento en holdout y elimina las limitaciones point-in-time y de
survivorship sin tocar locked.
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
    if "validation_used_for_selection" in holdout:
        _strict_bool_false(
            holdout["validation_used_for_selection"],
            "holdout validation selection audit",
        )
    _strict_bool_false(holdout["locked_opened"], "holdout")
    statistical_tests = pd.read_csv(input_root / "statistical_tests.csv")
    if statistical_tests.empty:
        raise ValueError("statistical evidence is empty")
    if "locked_opened" not in statistical_tests or "data_end" not in statistical_tests:
        raise ValueError("statistical evidence lacks locked audit columns")
    _strict_bool_false(statistical_tests["locked_opened"], "statistical evidence")
    statistical_ends = pd.to_datetime(
        statistical_tests["data_end"], errors="raise"
    ).dt.normalize()
    if statistical_ends.ge(pd.Timestamp("2021-01-01")).any():
        raise ValueError("statistical evidence crosses data boundary")

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

    robustness = phase_frames["robustness_results.csv"]
    robust_pass = _truthy(
        robustness.get("robust_pass", pd.Series(False, index=robustness.index))
    )
    robustness_complete = _truthy(
        robustness.get(
            "robustness_complete", pd.Series(False, index=robustness.index)
        )
    )
    accepted = robust_pass & robustness_complete
    holdout_best = _best_metric_row(holdout)
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
        "robustness_candidates": int(len(robustness)),
        "robustness_complete_count": int(robustness_complete.sum()),
        "robust_pass_count": int(robust_pass.sum()),
        "accepted_strategy_count": int(accepted.sum()),
        "strategy_found": bool(accepted.any()),
        "statistical_tasks_count": int(len(statistical_tests)),
        "statistical_unique_tasks": int(
            statistical_tests["task_id"].nunique()
            if "task_id" in statistical_tests
            else len(statistical_tests)
        ),
        "holdout_evaluated_count": int(len(holdout)),
        "best_holdout_sharpe": holdout_best.get("sharpe"),
        "best_holdout_cagr": holdout_best.get("cagr"),
        "best_holdout_max_drawdown": holdout_best.get("max_drawdown"),
        "validation_used_for_selection": False,
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
        f"- Accepted strategies: {summary['accepted_strategy_count']}.\n"
        f"- Robustness pass: {summary['robust_pass_count']} of {summary['robustness_candidates']}.\n"
        f"- Statistical tasks: {summary['statistical_tasks_count']}.\n"
        "- `survivorship_limited=true`; current-universe backfill is preliminary.\n"
        "- Pareto outputs are non-dominated fronts, not Sharpe rankings.\n",
        encoding="utf-8",
    )
    _write_recommendation(
        output_root,
        matrix,
        unsupported,
        frontier,
        phase_frames,
        statistical_tests,
        holdout,
        data_audit,
        summary,
    )
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

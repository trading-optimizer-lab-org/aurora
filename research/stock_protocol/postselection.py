"""Distributed pre-holdout robustness work for frozen stock portfolios."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .robustness import (
    benjamini_hochberg,
    block_bootstrap_records,
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
)


DEVELOPMENT_END = pd.Timestamp("2015-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
MAX_MATRIX_JOBS = 180
REQUIRED_METHODS = (
    "circular_block_bootstrap",
    "deflated_sharpe",
    "cscv_pbo",
    "leave_one_decade_out",
    "leave_one_symbol_out",
)
MIN_CANDIDATE_OBSERVATIONS = 252
MIN_CSCV_OBSERVATIONS = 30
ROBUSTNESS_TRADE_COLUMNS = (
    "candidate_id",
    "symbol",
    "entry_date",
    "net_return",
)


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return path


def _normalise_inputs(
    returns: pd.DataFrame,
    trades: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "date" not in returns:
        raise ValueError("robustness returns require date")
    clean_returns = returns.copy()
    clean_returns["date"] = pd.to_datetime(
        clean_returns["date"], errors="raise"
    ).dt.normalize()
    if clean_returns["date"].max() >= LOCKED_START:
        raise ValueError("robustness input contains locked dates")
    if clean_returns["date"].max() > DEVELOPMENT_END:
        raise ValueError("robustness input contains final holdout dates")
    if not clean_returns["date"].is_unique:
        raise ValueError("robustness return dates must be unique")
    clean_returns = clean_returns.sort_values("date").reset_index(drop=True)
    candidate_columns = [column for column in clean_returns if column != "date"]
    if len(candidate_columns) < 2:
        raise ValueError("robustness requires at least two frozen candidates")
    raw_numeric = clean_returns[candidate_columns]
    numeric = raw_numeric.apply(pd.to_numeric, errors="coerce")
    invalid = raw_numeric.notna() & numeric.isna()
    if invalid.any().any():
        raise ValueError("robustness returns contain non-numeric observations")
    finite_or_missing = np.isfinite(numeric.fillna(0.0).to_numpy(dtype=float)).all()
    if not finite_or_missing:
        raise ValueError("robustness returns contain non-finite observations")
    observation_counts = numeric.notna().sum()
    too_short = observation_counts.loc[
        observation_counts.lt(MIN_CANDIDATE_OBSERVATIONS)
    ]
    if not too_short.empty:
        raise ValueError(
            "robustness candidates lack 252 real observations: "
            + ", ".join(f"{name}={int(count)}" for name, count in too_short.items())
        )
    if numeric.le(-1.0).any().any():
        raise ValueError("robustness returns cannot be <= -100%")
    clean_returns[candidate_columns] = numeric

    required_trade_columns = {"candidate_id", "symbol", "entry_date", "net_return"}
    if not required_trade_columns <= set(trades.columns):
        raise ValueError("robustness trades lack required columns")
    clean_trades = trades.copy()
    clean_trades["entry_date"] = pd.to_datetime(
        clean_trades["entry_date"], errors="raise"
    ).dt.normalize()
    if len(clean_trades) and clean_trades["entry_date"].max() > DEVELOPMENT_END:
        raise ValueError("robustness trades contain final holdout dates")
    clean_trades["candidate_id"] = clean_trades["candidate_id"].astype(str)
    clean_trades["symbol"] = clean_trades["symbol"].astype(str)
    clean_trades["net_return"] = pd.to_numeric(
        clean_trades["net_return"], errors="coerce"
    )
    if clean_trades["net_return"].isna().any() or not np.isfinite(
        clean_trades["net_return"].to_numpy(dtype=float)
    ).all():
        raise ValueError("robustness trade returns must be finite")
    unknown = set(clean_trades["candidate_id"]) - set(candidate_columns)
    if unknown:
        raise ValueError(f"robustness trades contain unknown candidates: {sorted(unknown)}")
    clean_trades = clean_trades.sort_values(
        ["candidate_id", "entry_date", "symbol"]
    ).reset_index(drop=True)
    return clean_returns, clean_trades


def _cscv_subset(numeric: pd.DataFrame) -> tuple[list[str], int]:
    """Choose the largest causally observed candidate set with enough overlap."""

    columns = list(numeric.columns)
    best_columns: list[str] = []
    best_count = 0
    for left, right in itertools.combinations(columns, 2):
        count = int(numeric[[left, right]].notna().all(axis=1).sum())
        if count > best_count:
            best_columns = [left, right]
            best_count = count
    if best_count < MIN_CSCV_OBSERVATIONS:
        raise ValueError("no candidate pair has enough common observations for CSCV")
    remaining = [column for column in columns if column not in best_columns]
    while remaining:
        choices = []
        for column in remaining:
            proposed = [*best_columns, column]
            count = int(numeric[proposed].notna().all(axis=1).sum())
            choices.append((count, column))
        count, column = max(choices, key=lambda item: (item[0], item[1]))
        if count < MIN_CSCV_OBSERVATIONS:
            break
        best_columns.append(column)
        best_count = count
        remaining.remove(column)
    return best_columns, best_count


def _input_hash(returns: pd.DataFrame, trades: pd.DataFrame) -> str:
    canonical_returns = returns.copy()
    canonical_trades = trades.loc[:, ROBUSTNESS_TRADE_COLUMNS].copy()
    for column in canonical_returns.columns:
        if column != "date":
            canonical_returns[column] = pd.to_numeric(
                canonical_returns[column], errors="raise"
            ).round(12)
    canonical_trades["net_return"] = pd.to_numeric(
        canonical_trades["net_return"], errors="raise"
    ).round(12)
    digest = hashlib.sha256()
    digest.update(
        canonical_returns.to_csv(
            index=False, date_format="%Y-%m-%d", float_format="%.12g"
        ).encode("utf-8")
    )
    digest.update(b"\n--TRADES--\n")
    digest.update(
        canonical_trades.to_csv(
            index=False, date_format="%Y-%m-%d", float_format="%.12g"
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _task(method: str, parameters: dict[str, Any], input_hash: str) -> dict[str, Any]:
    raw = json.dumps(
        {"method": method, "parameters": parameters},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "task_id": hashlib.sha256(raw).hexdigest()[:20],
        "method": method,
        "parameters": parameters,
        "input_hash": input_hash,
    }


def build_robustness_plan(
    returns: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    task_count: int = 360,
    seed_base: int = 2_026_071_600,
) -> dict[str, Any]:
    """Create exactly ``task_count`` distinct, genuine statistical work units."""

    if task_count < len(REQUIRED_METHODS) or task_count > 360:
        raise ValueError("robustness task_count must be between 5 and 360")
    clean_returns, clean_trades = _normalise_inputs(returns, trades)
    input_hash = _input_hash(clean_returns, clean_trades)
    candidates = [column for column in clean_returns if column != "date"]
    numeric_returns = clean_returns[candidates]
    observation_counts = {
        candidate: int(numeric_returns[candidate].notna().sum())
        for candidate in candidates
    }
    cscv_candidates, cscv_observations = _cscv_subset(numeric_returns)
    decades_by_candidate = {
        candidate: sorted(
            (
                clean_returns.loc[numeric_returns[candidate].notna(), "date"].dt.year
                // 10
                * 10
            ).unique().tolist()
        )
        for candidate in candidates
    }
    symbols_by_candidate = {
        candidate: sorted(
            clean_trades.loc[
                clean_trades["candidate_id"].eq(candidate), "symbol"
            ].unique().tolist()
        )
        for candidate in candidates
    }
    viable_symbols_by_candidate = {
        candidate: [
            symbol
            for symbol in symbols
            if int(
                clean_trades.loc[
                    clean_trades["candidate_id"].eq(candidate)
                    & clean_trades["symbol"].ne(symbol)
                ].shape[0]
            )
            >= 2
        ]
        for candidate, symbols in symbols_by_candidate.items()
    }
    if not all(decades_by_candidate.values()) or not any(
        symbols_by_candidate.values()
    ):
        raise ValueError("robustness leave-out tasks require decades and traded symbols")

    required_methods = set(REQUIRED_METHODS)
    unavailable_methods: dict[str, str] = {}
    if not any(viable_symbols_by_candidate.values()):
        required_methods.remove("leave_one_symbol_out")
        unavailable_methods["leave_one_symbol_out"] = (
            "requires at least one frozen candidate with two traded symbols and "
            "two remaining trades after exclusion"
        )

    viable_partitions = [
        value
        for value in (4, 6, 8, 10, 12, 14, 16)
        if cscv_observations >= value * 2
    ]
    tasks: list[dict[str, Any]] = []
    task_ids: set[str] = set()

    def append_task(method: str, parameters: dict[str, Any]) -> None:
        candidate_task = _task(method, parameters, input_hash)
        if candidate_task["task_id"] not in task_ids:
            task_ids.add(candidate_task["task_id"])
            tasks.append(candidate_task)

    # Reserve complete core evidence for every candidate before spending the
    # remaining budget. This prevents a large first portfolio from consuming
    # the whole matrix with leave-one-symbol tasks.
    append_task(
        "cscv_pbo",
        {"partitions": viable_partitions[0], "candidate_ids": cscv_candidates},
    )
    for candidate_index, candidate in enumerate(candidates):
        append_task(
            "circular_block_bootstrap",
            {
                "candidate_id": candidate,
                "seed": int(seed_base + candidate_index),
                "block_size": 5,
                "n_samples": 100,
            },
        )
        append_task(
            "deflated_sharpe",
            {"candidate_id": candidate, "n_trials": len(candidates)},
        )
        for decade in decades_by_candidate[candidate]:
            append_task(
                "leave_one_decade_out",
                {"candidate_id": candidate, "decade": int(decade)},
            )
        viable_symbols = viable_symbols_by_candidate[candidate]
        if viable_symbols:
            append_task(
                "leave_one_symbol_out",
                {"candidate_id": candidate, "symbol": viable_symbols[0]},
            )

    minimum_complete_task_count = len(tasks)
    if minimum_complete_task_count > task_count:
        raise ValueError(
            "robustness task_count cannot cover complete candidate evidence: "
            f"requires at least {minimum_complete_task_count}, got {task_count}"
        )

    # Use each viable CSCV partition once, then distribute symbol exclusions
    # round-robin so no candidate monopolises the finite task budget.
    for partitions in viable_partitions[1:]:
        if len(tasks) >= task_count:
            break
        append_task(
            "cscv_pbo",
            {"partitions": partitions, "candidate_ids": cscv_candidates},
        )
    maximum_symbols = max(
        (len(symbols) for symbols in viable_symbols_by_candidate.values()),
        default=0,
    )
    for symbol_index in range(maximum_symbols):
        for candidate in candidates:
            if len(tasks) >= task_count:
                break
            symbols = viable_symbols_by_candidate[candidate]
            if symbol_index < len(symbols):
                append_task(
                    "leave_one_symbol_out",
                    {"candidate_id": candidate, "symbol": symbols[symbol_index]},
                )
        if len(tasks) >= task_count:
            break

    block_sizes = (5, 10, 21, 42, 63)
    sequence = 0
    while len(tasks) < task_count:
        candidate = candidates[sequence % len(candidates)]
        block_size = min(
            block_sizes[(sequence // len(candidates)) % len(block_sizes)],
            observation_counts[candidate],
        )
        parameters = {
            "candidate_id": candidate,
            "seed": int(seed_base + sequence + 1),
            "block_size": int(block_size),
            "n_samples": 100,
        }
        append_task("circular_block_bootstrap", parameters)
        sequence += 1
    planned = tasks
    if len(planned) != task_count or len(
        {task["task_id"] for task in planned}
    ) != task_count:
        raise ValueError("failed to create exact unique robustness task coverage")
    if required_methods - {task["method"] for task in planned}:
        raise ValueError("robustness plan lost a required method")
    split = min(MAX_MATRIX_JOBS, (task_count + 1) // 2)
    return {
        "schema_version": 1,
        "task_count": task_count,
        "matrix_a": list(range(split)),
        "matrix_b": list(range(split, task_count)),
        "tasks": planned,
        "input_hash": input_hash,
        "candidate_ids": candidates,
        "observation_counts": observation_counts,
        "required_methods": sorted(required_methods),
        "unavailable_methods": unavailable_methods,
        "minimum_complete_task_count": minimum_complete_task_count,
        "task_distribution_policy": "candidate_core_then_round_robin",
        "viable_leave_one_symbol_candidates": sorted(
            candidate
            for candidate, symbols in viable_symbols_by_candidate.items()
            if symbols
        ),
        "cscv_candidate_ids": cscv_candidates,
        "cscv_complete_observations": cscv_observations,
        "data_end": DEVELOPMENT_END.date().isoformat(),
        "locked_opened": False,
        "partial": False,
    }


def _load_inputs(
    plan_path: Path,
    returns_path: Path,
    trades_path: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    returns, trades = _normalise_inputs(
        pd.read_csv(returns_path), pd.read_csv(trades_path)
    )
    if plan.get("locked_opened") is not False:
        raise ValueError("robustness plan opened locked data")
    if _input_hash(returns, trades) != plan.get("input_hash"):
        raise ValueError("robustness input hash mismatch")
    return plan, returns, trades


def _sharpe(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="raise").astype(float)
    deviation = float(numeric.std(ddof=1))
    return float(numeric.mean() / deviation * math.sqrt(252.0)) if deviation > 0 else 0.0


def execute_robustness_task(
    *,
    plan_path: Path,
    returns_path: Path,
    trades_path: Path,
    task_index: int,
    output_root: Path,
) -> Path:
    """Execute one planned statistical method and persist its real samples."""

    plan, returns, trades = _load_inputs(plan_path, returns_path, trades_path)
    if task_index < 0 or task_index >= int(plan["task_count"]):
        raise ValueError("robustness task_index outside plan")
    task = dict(plan["tasks"][task_index])
    parameters = dict(task["parameters"])
    method = str(task["method"])
    candidate_id = str(parameters.get("candidate_id", "__all__"))
    result: dict[str, Any] = {
        "task_index": int(task_index),
        "task_id": task["task_id"],
        "method": method,
        "variant": json.dumps(parameters, sort_keys=True, separators=(",", ":")),
        "candidate_id": candidate_id,
        "seed": parameters.get("seed"),
        "n_observations": int(len(returns)),
        "input_hash": plan["input_hash"],
        "locked_opened": False,
        "data_end": DEVELOPMENT_END.date().isoformat(),
        "status": "evaluated",
        "pvalue": None,
    }
    samples = pd.DataFrame()
    candidate_returns = (
        returns[candidate_id].dropna()
        if candidate_id != "__all__"
        else pd.Series(dtype=float)
    )
    if candidate_id != "__all__":
        result["n_observations"] = int(len(candidate_returns))
    if method == "circular_block_bootstrap":
        samples = block_bootstrap_records(
            candidate_returns,
            n_samples=int(parameters["n_samples"]),
            block_size=int(parameters["block_size"]),
            seed=int(parameters["seed"]),
            variant=candidate_id,
        )
        result.update(
            {
                "sample_count": int(len(samples)),
                "sample_digest": hashlib.sha256(
                    "".join(samples["sample_hash"].astype(str)).encode("utf-8")
                ).hexdigest(),
                "estimate": float(samples["sharpe"].mean()),
                "ci_05": float(samples["sharpe"].quantile(0.05)),
                "ci_95": float(samples["sharpe"].quantile(0.95)),
                "pvalue": float((samples["sharpe"] <= 0.0).mean()),
            }
        )
    elif method == "deflated_sharpe":
        dsr = deflated_sharpe_ratio(
            candidate_returns, n_trials=int(parameters["n_trials"])
        )
        result.update(
            {
                "estimate": float(dsr["observed_sharpe"]),
                "expected_max_sharpe": float(dsr["expected_max_sharpe"]),
                "probability": float(dsr["probability"]),
                "pvalue": float(1.0 - dsr["probability"]),
            }
        )
    elif method == "cscv_pbo":
        cscv_candidates = [str(value) for value in parameters["candidate_ids"]]
        cscv_returns = returns[cscv_candidates].dropna()
        result["n_observations"] = int(len(cscv_returns))
        cscv = cscv_probability_of_backtest_overfitting(
            cscv_returns, partitions=int(parameters["partitions"])
        )
        result.update(
            {
                "estimate": float(cscv["pbo"]),
                "pbo": float(cscv["pbo"]),
                "combinations_evaluated": int(cscv["combinations_evaluated"]),
                "median_logit": float(cscv["median_logit"]),
            }
        )
    elif method == "leave_one_decade_out":
        decade = int(parameters["decade"])
        remaining = returns.loc[
            returns["date"].dt.year.floordiv(10).mul(10).ne(decade), candidate_id
        ].dropna()
        if len(remaining) < 2:
            raise ValueError("leave-one-decade task has insufficient observations")
        result.update(
            {
                "left_out_group": decade,
                "n_observations": int(len(remaining)),
                "estimate": _sharpe(remaining),
                "mean_return": float(remaining.mean()),
            }
        )
    elif method == "leave_one_symbol_out":
        symbol = str(parameters["symbol"])
        candidate_trades = trades.loc[trades["candidate_id"].eq(candidate_id)]
        remaining = candidate_trades.loc[
            candidate_trades["symbol"].ne(symbol), "net_return"
        ]
        if len(remaining) < 2:
            raise ValueError("leave-one-symbol task has insufficient observations")
        losses = float(-remaining.loc[remaining.lt(0)].sum())
        gains = float(remaining.loc[remaining.gt(0)].sum())
        result.update(
            {
                "left_out_group": symbol,
                "n_observations": int(len(remaining)),
                "estimate": float(remaining.mean()),
                "mean_return": float(remaining.mean()),
                "profit_factor": gains / losses if losses > 0 else None,
            }
        )
    else:
        raise ValueError(f"unknown robustness method: {method}")
    task_root = output_root / f"task={task_index:04d}"
    task_root.mkdir(parents=True, exist_ok=True)
    samples.to_csv(task_root / "samples.csv", index=False)
    return _write_json(task_root / "result.json", result)


def _task_results(tasks_root: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in tasks_root.rglob("result.json"):
        task_part = next(
            (part for part in reversed(path.parts) if part.startswith("task=")), None
        )
        if task_part is None:
            continue
        index = int(task_part.split("=", 1)[1])
        if index in found:
            raise ValueError(f"duplicate robustness task {index}")
        found[index] = path
    return found


def merge_robustness_tasks(
    *,
    plan_path: Path,
    tasks_root: Path,
    output_root: Path,
) -> dict[str, Path]:
    """Require exact coverage, apply FDR and derive candidate diagnostics."""

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    expected = set(range(int(plan["task_count"])))
    found = _task_results(tasks_root)
    missing = sorted(expected - set(found))
    if missing:
        raise ValueError(f"missing robustness task results: {missing}")
    extra = sorted(set(found) - expected)
    if extra:
        raise ValueError(f"unexpected robustness task results: {extra}")
    rows = []
    for index in sorted(expected):
        row = json.loads(found[index].read_text(encoding="utf-8"))
        planned = plan["tasks"][index]
        if row.get("task_id") != planned.get("task_id"):
            raise ValueError(f"robustness task identity mismatch at {index}")
        if row.get("input_hash") != plan.get("input_hash"):
            raise ValueError(f"robustness input hash mismatch at {index}")
        if row.get("locked_opened") is not False:
            raise ValueError(f"robustness task {index} opened locked data")
        rows.append(row)
    tests = pd.DataFrame(rows)
    tests["pvalue"] = pd.to_numeric(tests["pvalue"], errors="coerce")
    tests["fdr_pvalue"] = np.nan
    pvalue_rows = tests["pvalue"].notna()
    if pvalue_rows.any():
        tests.loc[pvalue_rows, "fdr_pvalue"] = benjamini_hochberg(
            tests.loc[pvalue_rows, "pvalue"]
        )
    global_pbo = pd.to_numeric(
        tests.loc[tests["method"].eq("cscv_pbo"), "pbo"], errors="coerce"
    )
    viable_symbol_candidates = set(
        plan.get("viable_leave_one_symbol_candidates", plan["candidate_ids"])
    )
    candidate_rows = []
    for candidate_id in plan["candidate_ids"]:
        candidate = tests.loc[tests["candidate_id"].eq(candidate_id)]
        bootstrap = candidate.loc[candidate["method"].eq("circular_block_bootstrap")]
        dsr = candidate.loc[candidate["method"].eq("deflated_sharpe")]
        decades = candidate.loc[candidate["method"].eq("leave_one_decade_out")]
        symbols = candidate.loc[candidate["method"].eq("leave_one_symbol_out")]
        symbol_viable = candidate_id in viable_symbol_candidates
        symbol_tested = not symbols.empty
        symbol_available = symbol_viable and symbol_tested
        symbol_minimum = pd.to_numeric(
            symbols.get("mean_return"), errors="coerce"
        ).min()
        metric_values = {
            "bootstrap_sharpe_p05": pd.to_numeric(
                bootstrap.get("ci_05"), errors="coerce"
            ).min(),
            "bootstrap_fdr_pvalue_max": pd.to_numeric(
                bootstrap.get("fdr_pvalue"), errors="coerce"
            ).max(),
            "deflated_sharpe_probability": pd.to_numeric(
                dsr.get("probability"), errors="coerce"
            ).max(),
            "cscv_pbo_max": global_pbo.max(),
            "leave_one_decade_min_sharpe": pd.to_numeric(
                decades.get("estimate"), errors="coerce"
            ).min(),
        }
        missing_metrics = [
            name
            for name, value in metric_values.items()
            if pd.isna(value) or not np.isfinite(float(value))
        ]
        if symbol_viable and (
            not symbol_tested
            or pd.isna(symbol_minimum)
            or not np.isfinite(float(symbol_minimum))
        ):
            missing_metrics.append("leave_one_symbol_min_mean_return")
        robustness_complete = bool(symbol_available and not missing_metrics)
        if not symbol_viable:
            limitation = plan["unavailable_methods"].get(
                "leave_one_symbol_out",
                "leave_one_symbol_out unavailable for candidate",
            )
        elif missing_metrics:
            limitation = "missing executed robustness metrics: " + ", ".join(
                missing_metrics
            )
        else:
            limitation = ""
        row = {
            "candidate_id": candidate_id,
            **metric_values,
            "leave_one_symbol_available": symbol_available,
            "leave_one_symbol_min_mean_return": (
                float(symbol_minimum)
                if symbol_available
                else ("not_executed" if symbol_viable else "not_applicable")
            ),
            "robustness_complete": robustness_complete,
            "robustness_limitation": limitation,
            "locked_opened": False,
            "data_end": DEVELOPMENT_END.date().isoformat(),
        }
        required = [
            row["bootstrap_sharpe_p05"],
            row["bootstrap_fdr_pvalue_max"],
            row["deflated_sharpe_probability"],
            row["cscv_pbo_max"],
            row["leave_one_decade_min_sharpe"],
        ]
        if symbol_available:
            required.append(symbol_minimum)
        row["robust_pass"] = bool(
            row["robustness_complete"]
            and all(pd.notna(value) for value in required)
            and row["bootstrap_sharpe_p05"] > 0
            and row["bootstrap_fdr_pvalue_max"] <= 0.05
            and row["deflated_sharpe_probability"] >= 0.95
            and row["cscv_pbo_max"] <= 0.50
            and row["leave_one_decade_min_sharpe"] > 0
            and symbol_minimum > 0
        )
        candidate_rows.append(row)
    robustness = pd.DataFrame(candidate_rows)
    stability = robustness[
        [
            "candidate_id",
            "leave_one_decade_min_sharpe",
            "leave_one_symbol_min_mean_return",
            "leave_one_symbol_available",
            "robustness_complete",
            "robustness_limitation",
            "bootstrap_sharpe_p05",
            "robust_pass",
        ]
    ].copy()
    output_root.mkdir(parents=True, exist_ok=True)
    tests_path = output_root / "statistical_tests.csv"
    robustness_path = output_root / "robustness_results.csv"
    stability_path = output_root / "parameter_stability.csv"
    tests.to_csv(tests_path, index=False)
    robustness.to_csv(robustness_path, index=False)
    stability.to_csv(stability_path, index=False)
    summary_path = _write_json(
        output_root / "robustness_summary.json",
        {
            "tasks_expected": len(expected),
            "tasks_found": len(found),
            "candidate_count": len(candidate_rows),
            "robustness_complete_count": int(
                robustness["robustness_complete"].sum()
            ),
            "robust_pass_count": int(robustness["robust_pass"].sum()),
            "required_methods": plan.get("required_methods", []),
            "unavailable_methods": plan.get("unavailable_methods", {}),
            "input_hash": plan["input_hash"],
            "locked_opened": False,
            "data_end": DEVELOPMENT_END.date().isoformat(),
            "partial": False,
        },
    )
    return {
        "statistical_tests": tests_path,
        "robustness_results": robustness_path,
        "parameter_stability": stability_path,
        "summary": summary_path,
    }

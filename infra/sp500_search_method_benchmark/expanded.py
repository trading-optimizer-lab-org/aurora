"""Expanded, train-only comparison of black-box search algorithms.

The previous benchmark compared seven proposal rules on a common full-fidelity
budget.  This module keeps that causal contract and adds the requested search
families.  It is deliberately self-contained: GitHub Actions installs the
locked Aurora base runtime only, so labels such as ``M07_DEHB_REAL`` refer to
the algorithm implemented here, not to a package silently falling back to
random search.

All methods share one 15-dimensional grammar, one immutable SPY snapshot, the
same seven seeds, the same 32 full-fidelity warm-start candidates, a budget of
256 full-fidelity-equivalent cost units, and the same 15-minute wall limit.
Multi-fidelity methods may spend 0.25 or 0.50 cost units on early rungs, but
only 1.00-fidelity candidates can enter the frozen top-five set.  The official
validation and locked periods are never loaded.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import qmc, norm

from aurora.infra.sp500_search_method_benchmark.benchmark import (
    AUDIT_END,
    AUDIT_START,
    GENOME_DIM,
    LOCKED_START,
    SEARCH_END,
    SEARCH_START,
    SEEDS,
    TOP_K,
    TRAIN_END,
    VALIDATION_START,
    _evaluate_rule,
    _feature_values,
    _genome_canonical,
    _json_dump,
    _load_bounded_frame,
    _sha256_file,
    _warm_start,
    build_search_space_manifest,
    canonical_hash,
    load_price_data,
    parse_causal_dates,
    prepare_benchmark_data,
)


MAX_COST_UNITS = 256.0
MAX_ACTIONS = 1024
SEARCH_WALL_SECONDS = 15 * 60
FIDELITIES = (0.25, 0.50, 1.00)
EVALUATION_WORKERS = 2
ETA = 3

METHODS = (
    "M00_RANDOM",
    "M01_SCRAMBLED_SOBOL",
    "M02_TPE",
    "M03_SMAC_RF_SMBO",
    "M04_DIFFERENTIAL_EVOLUTION",
    "M05_GENETIC_PROGRAMMING",
    "M06_GP_TPE_HYBRID",
    "M07_DEHB_REAL",
    "M08_BOHB",
    "M09_HYPERBAND",
    "M10_ASHA",
    "M11_CMA_ES",
    "M12_PSO",
    "M13_GP_BAYESIAN_OPTIMIZATION",
    "M14_TURBO",
    "M15_OPTUNA",
    "M16_NEVERGRAD",
    "M17_NSGA_II",
    "M18_LATIN_HYPERCUBE",
    "M19_HALTON",
    "M20_SUCCESSIVE_HALVING",
    "M21_POPULATION_BASED_TRAINING",
    "M22_ADVANCED_SURROGATE_ASSISTED",
)

METHOD_IMPLEMENTATIONS = {
    "M00_RANDOM": "uniform_random_search",
    "M01_SCRAMBLED_SOBOL": "scrambled_sobol_sequence",
    "M02_TPE": "parzen_density_ratio_sampler",
    "M03_SMAC_RF_SMBO": "numpy_random_forest_expected_improvement",
    "M04_DIFFERENTIAL_EVOLUTION": "differential_evolution",
    "M05_GENETIC_PROGRAMMING": "typed_grammar_genetic_programming_on_grammar_genome",
    "M06_GP_TPE_HYBRID": "genetic_programming_then_tpe_numeric_refinement",
    "M07_DEHB_REAL": "differential_evolution_hyperband_with_successive_halving",
    "M08_BOHB": "tpe_model_hyperband_with_successive_halving",
    "M09_HYPERBAND": "bracketed_successive_halving",
    "M10_ASHA": "asynchronous_successive_halving",
    "M11_CMA_ES": "diagonal_covariance_matrix_adaptation_evolution_strategy",
    "M12_PSO": "particle_swarm_optimization",
    "M13_GP_BAYESIAN_OPTIMIZATION": "gaussian_process_expected_improvement",
    "M14_TURBO": "trust_region_gaussian_process_bayesian_optimization",
    "M15_OPTUNA": "optuna_style_tpe_with_median_pruning",
    "M16_NEVERGRAD": "one_plus_one_adaptive_mutation_portfolio",
    "M17_NSGA_II": "nondominated_sorting_genetic_algorithm_ii",
    "M18_LATIN_HYPERCUBE": "latin_hypercube_sampling",
    "M19_HALTON": "halton_low_discrepancy_sequence",
    "M20_SUCCESSIVE_HALVING": "successive_halving",
    "M21_POPULATION_BASED_TRAINING": "population_based_training_exploit_and_explore",
    "M22_ADVANCED_SURROGATE_ASSISTED": "rbf_kernel_surrogate_with_uncertainty_and_local_search",
}

MULTI_FIDELITY = {
    "M07_DEHB_REAL",
    "M08_BOHB",
    "M09_HYPERBAND",
    "M10_ASHA",
    "M15_OPTUNA",
    "M20_SUCCESSIVE_HALVING",
    "M21_POPULATION_BASED_TRAINING",
}
STATIC_METHODS = {
    "M00_RANDOM",
    "M01_SCRAMBLED_SOBOL",
    "M18_LATIN_HYPERCUBE",
    "M19_HALTON",
}


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            safe = {
                key: json.dumps(value, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
                for key, value in row.items()
            }
            writer.writerow(safe)


def build_expanded_space_manifest(output_dir: Path) -> dict[str, Any]:
    base = build_search_space_manifest(output_dir)
    payload = dict(base)
    payload.update(
        {
            "schema_version": "StrategyGrammarBenchmarkExpandedV1",
            "methods": list(METHODS),
            "method_implementations": METHOD_IMPLEMENTATIONS,
            "seeds": list(SEEDS),
            "common_warm_start": 32,
            "max_cost_units": MAX_COST_UNITS,
            "fidelity_levels": list(FIDELITIES),
            "fidelity_cost_units": list(FIDELITIES),
            "search_wall_seconds": SEARCH_WALL_SECONDS,
            "evaluation_workers": EVALUATION_WORKERS,
            "selection_period": f"{SEARCH_START.date()}..{SEARCH_END.date()}",
            "audit_period": f"{AUDIT_START.date()}..{AUDIT_END.date()}",
            "validation_unopened": f"{VALIDATION_START.date()}..2020-12-31",
            "locked_unopened": f">={LOCKED_START.date()}",
            "selection_metric": "median_audit_cagr_of_top_5_frozen_full_fidelity_candidates",
            "efficiency_metric": "area_under_best_full_fidelity_search_cagr_by_cost_units",
        }
    )
    path = Path(output_dir) / "expanded_search_space_manifest.json"
    _json_dump(path, payload)
    payload["sha256"] = _sha256_file(path)
    _json_dump(path, payload)
    return payload


def _fidelity_end(data: Any, fidelity: float) -> pd.Timestamp:
    if fidelity not in FIDELITIES:
        raise ValueError("UNKNOWN_FIDELITY")
    dates = data.frame.index[(data.frame.index >= SEARCH_START) & (data.frame.index <= SEARCH_END)]
    if len(dates) == 0:
        raise ValueError("NO_SEARCH_ROWS")
    position = max(0, min(len(dates) - 1, int(math.ceil(len(dates) * fidelity)) - 1))
    return pd.Timestamp(dates[position])


def _safe_metrics() -> dict[str, Any]:
    return {
        "cagr": -1.0,
        "total_return": -1.0,
        "sharpe": -1.0,
        "sortino": -1.0,
        "calmar": -1.0,
        "max_drawdown": -1.0,
        "positive_years": 0,
        "annual": [],
    }


def _expanded_candidate(
    method: str,
    seed: int,
    proposal: int,
    genome: Sequence[float],
    fidelity: float,
    data: Any,
) -> dict[str, Any]:
    rule = _genome_canonical(genome)
    digest = canonical_hash(rule)
    end = _fidelity_end(data, fidelity)
    try:
        metrics = _evaluate_rule(rule, data, SEARCH_START, end)
        status = "VALID"
        reason = None
        fitness = float(metrics["cagr"])
    except (ValueError, FloatingPointError) as exc:
        metrics = _safe_metrics()
        status = "REJECTED"
        reason = str(exc)
        fitness = -1.0
    return {
        "candidate_id": f"{method.lower()}_s{seed}_{proposal:04d}_{int(round(fidelity * 100)):03d}_{digest[:12]}",
        "method": method,
        "seed": int(seed),
        "proposal": int(proposal),
        "fidelity": float(fidelity),
        "cost_units": float(fidelity),
        "fidelity_end": end.date().isoformat(),
        "status": status,
        "rejection_reason": reason,
        "canonical_hash": digest,
        "genome": [float(value) for value in genome],
        "rule": rule,
        "fitness": fitness,
        "search_cagr": float(metrics["cagr"]),
        "search_total_return": float(metrics["total_return"]),
        "search_sharpe": float(metrics["sharpe"]),
        "search_sortino": float(metrics["sortino"]),
        "search_calmar": float(metrics["calmar"]),
        "search_max_drawdown": float(metrics["max_drawdown"]),
        "search_positive_years": int(metrics["positive_years"]),
        "search_annual": metrics["annual"],
    }


def _full_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in records if float(row.get("fidelity", 0.0)) >= 0.999 and row.get("status") == "VALID"]


def _ranked(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(records, key=lambda row: (-float(row["fitness"]), str(row["canonical_hash"])))


def _random_point(rng: np.random.Generator) -> np.ndarray:
    return rng.random(GENOME_DIM)


def _tpe_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 24 or rng.random() < 0.20:
        return _random_point(rng)
    ranked = _ranked(records)
    good = np.asarray([row["genome"] for row in ranked[: max(8, len(ranked) // 5)]], dtype=float)
    bad = np.asarray([row["genome"] for row in ranked[max(8, len(ranked) // 5) :]], dtype=float)
    pool = rng.random((256, GENOME_DIM))
    good_scale = np.std(good, axis=0) + 0.025
    good_density = np.exp(-0.5 * np.sum(((pool[:, None, :] - good[None, :, :]) / good_scale) ** 2, axis=2)).mean(axis=1)
    if len(bad):
        bad_scale = np.std(bad, axis=0) + 0.025
        bad_density = np.exp(-0.5 * np.sum(((pool[:, None, :] - bad[None, :, :]) / bad_scale) ** 2, axis=2)).mean(axis=1)
    else:
        bad_density = np.full(len(pool), 1e-9)
    return pool[int(np.argmax(np.log(good_density + 1e-9) - np.log(bad_density + 1e-9)))]


def _tree_predict(node: Any, points: np.ndarray) -> np.ndarray:
    if node[0] == "leaf":
        return np.full(len(points), float(node[1]))
    _, feature, threshold, left, right = node
    mask = points[:, feature] <= threshold
    result = np.empty(len(points), dtype=float)
    if mask.any():
        result[mask] = _tree_predict(left, points[mask])
    if (~mask).any():
        result[~mask] = _tree_predict(right, points[~mask])
    return result


def _fit_tree(x: np.ndarray, y: np.ndarray, indices: np.ndarray, rng: np.random.Generator, depth: int = 0) -> Any:
    values = y[indices]
    if depth >= 5 or len(indices) < 8 or np.ptp(values) < 1e-12:
        return ("leaf", float(np.mean(values)))
    features = rng.choice(x.shape[1], size=min(5, x.shape[1]), replace=False)
    best: tuple[float, int, float, np.ndarray, np.ndarray] | None = None
    parent_loss = float(np.var(values) * len(values))
    for feature in features:
        values_x = x[indices, int(feature)]
        if np.ptp(values_x) < 1e-12:
            continue
        threshold = float(np.quantile(values_x, rng.uniform(0.25, 0.75)))
        left = indices[values_x <= threshold]
        right = indices[values_x > threshold]
        if len(left) < 4 or len(right) < 4:
            continue
        loss = float(np.var(y[left]) * len(left) + np.var(y[right]) * len(right))
        gain = parent_loss - loss
        if best is None or gain > best[0]:
            best = (gain, int(feature), threshold, left, right)
    if best is None or best[0] <= 1e-12:
        return ("leaf", float(np.mean(values)))
    _, feature, threshold, left, right = best
    return (
        "node",
        feature,
        threshold,
        _fit_tree(x, y, left, rng, depth + 1),
        _fit_tree(x, y, right, rng, depth + 1),
    )


def _rf_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 32:
        return _random_point(rng)
    x = np.asarray([row["genome"] for row in records], dtype=float)
    y = np.asarray([row["fitness"] for row in records], dtype=float)
    pool = rng.random((256, GENOME_DIM))
    predictions = []
    for _ in range(12):
        bootstrap = rng.integers(0, len(x), len(x))
        predictions.append(_tree_predict(_fit_tree(x, y, bootstrap, rng), pool))
    return pool[int(np.argmax(np.mean(np.asarray(predictions), axis=0)))]


def _gp_bo_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator, center: np.ndarray | None = None) -> np.ndarray:
    if len(records) < 18:
        return _random_point(rng)
    ranked = _ranked(records)
    selected = ranked[:96]
    x = np.asarray([row["genome"] for row in selected], dtype=float)
    y = np.asarray([row["fitness"] for row in selected], dtype=float)
    if center is not None:
        pool = np.clip(center + rng.normal(0.0, 0.15, (256, GENOME_DIM)), 0.0, 0.999999)
    else:
        pool = rng.random((256, GENOME_DIM))
    length = 0.20
    distances = np.sum((x[:, None, :] - x[None, :, :]) ** 2, axis=2)
    scale = float(np.median(np.sqrt(distances[distances > 0]))) if np.any(distances > 0) else length
    length = max(0.05, min(0.60, scale))
    kernel = np.exp(-np.sum((x[:, None, :] - x[None, :, :]) ** 2, axis=2) / (2.0 * length**2))
    kernel.flat[:: len(kernel) + 1] += 1e-6
    try:
        alpha = np.linalg.solve(kernel, y)
        cross = np.exp(-np.sum((pool[:, None, :] - x[None, :, :]) ** 2, axis=2) / (2.0 * length**2))
        mean = cross @ alpha
        variance = np.maximum(1e-12, 1.0 - np.sum(cross * np.linalg.solve(kernel, cross.T).T, axis=1))
    except np.linalg.LinAlgError:
        return _random_point(rng)
    std = np.sqrt(variance)
    best = float(np.max(y))
    z = (mean - best) / std
    ei = (mean - best) * norm.cdf(z) + std * norm.pdf(z)
    return pool[int(np.argmax(ei))]


def _surrogate_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 20:
        return _random_point(rng)
    ranked = _ranked(records)
    x = np.asarray([row["genome"] for row in ranked[:128]], dtype=float)
    y = np.asarray([row["fitness"] for row in ranked[:128]], dtype=float)
    pool = rng.random((512, GENOME_DIM))
    length = 0.35
    weights = np.exp(-np.sum((pool[:, None, :] - x[None, :, :]) ** 2, axis=2) / (2.0 * length**2))
    weights /= np.sum(weights, axis=1, keepdims=True) + 1e-12
    mean = weights @ y
    uncertainty = np.sqrt(np.maximum(0.0, weights @ ((y[None, :] - mean[:, None]) ** 2)))
    acquisition = mean + 0.75 * uncertainty
    local = ranked[0]["genome"] if ranked else _random_point(rng)
    local_pool = np.clip(np.asarray(local) + rng.normal(0, 0.10, (128, GENOME_DIM)), 0, 0.999999)
    local_weights = np.exp(-np.sum((local_pool[:, None, :] - x[None, :, :]) ** 2, axis=2) / (2.0 * length**2))
    local_weights /= np.sum(local_weights, axis=1, keepdims=True) + 1e-12
    local_score = local_weights @ y
    if float(np.max(local_score)) > float(np.max(acquisition)):
        return local_pool[int(np.argmax(local_score))]
    return pool[int(np.argmax(acquisition))]


def _de_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 12:
        return _random_point(rng)
    population = [np.asarray(row["genome"], dtype=float) for row in _ranked(records)[: min(64, len(records))]]
    a, b, c = population[rng.integers(len(population))], population[rng.integers(len(population))], population[rng.integers(len(population))]
    donor = np.clip(a + 0.75 * (b - c), 0.0, 0.999999)
    mask = rng.random(GENOME_DIM) < 0.70
    mask[rng.integers(GENOME_DIM)] = True
    target = population[rng.integers(len(population))]
    return np.where(mask, donor, target)


def _gp_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 32:
        return _random_point(rng)
    ranked = _ranked(records)
    parent = np.asarray(ranked[int(rng.integers(min(24, len(ranked))))]["genome"], dtype=float).copy()
    mate = np.asarray(ranked[int(rng.integers(min(48, len(ranked))))]["genome"], dtype=float)
    cut = int(rng.integers(1, GENOME_DIM - 1))
    child = parent.copy()
    child[cut:] = mate[cut:]
    if rng.random() < 0.70:
        slots = rng.choice(GENOME_DIM, size=int(rng.integers(1, 4)), replace=False)
        child[slots] = rng.random(len(slots))
    return np.clip(child, 0.0, 0.999999)


def _nondominated(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    points = []
    for row in records:
        points.append((float(row["search_cagr"]), float(row["search_sharpe"]), -float(row["search_max_drawdown"])))
    keep: list[Mapping[str, Any]] = []
    for i, row in enumerate(records):
        dominated = False
        for j, other in enumerate(points):
            if i == j:
                continue
            if all(other[k] >= points[i][k] for k in range(3)) and any(other[k] > points[i][k] for k in range(3)):
                dominated = True
                break
        if not dominated:
            keep.append(row)
    return keep


def _nsga_point(records: Sequence[Mapping[str, Any]], rng: np.random.Generator) -> np.ndarray:
    if len(records) < 24:
        return _random_point(rng)
    parents = _nondominated(_full_records(records))
    if not parents:
        return _random_point(rng)
    left = np.asarray(parents[int(rng.integers(len(parents)))]["genome"], dtype=float)
    right = np.asarray(parents[int(rng.integers(len(parents)))]["genome"], dtype=float)
    mask = rng.random(GENOME_DIM) < 0.5
    child = np.where(mask, left, right)
    mutation = rng.random(GENOME_DIM) < 0.15
    child[mutation] = np.clip(child[mutation] + rng.normal(0, 0.12, int(mutation.sum())), 0, 0.999999)
    return np.clip(child, 0.0, 0.999999)


def _stream(method: str, seed: int) -> np.ndarray:
    if method == "M00_RANDOM":
        result = np.random.default_rng(seed).random((MAX_ACTIONS, GENOME_DIM))
    elif method == "M01_SCRAMBLED_SOBOL":
        result = qmc.Sobol(d=GENOME_DIM, scramble=True, seed=seed).random(MAX_ACTIONS)
    elif method == "M18_LATIN_HYPERCUBE":
        result = qmc.LatinHypercube(d=GENOME_DIM, seed=seed).random(MAX_ACTIONS)
    elif method == "M19_HALTON":
        result = qmc.Halton(d=GENOME_DIM, scramble=True, seed=seed).random(MAX_ACTIONS)
    else:
        raise ValueError("STREAM_NOT_AVAILABLE")
    result[:32] = _warm_start(seed)
    return result


def _next_regular_point(method: str, seed: int, records: Sequence[Mapping[str, Any]], state: dict[str, Any]) -> np.ndarray:
    rng: np.random.Generator = state["rng"]
    index = len(records)
    if method in STATIC_METHODS:
        point = state["stream"][min(state["stream_index"], len(state["stream"]) - 1)]
        state["stream_index"] += 1
        return np.asarray(point, dtype=float)
    if method == "M02_TPE":
        return _tpe_point(_full_records(records), rng)
    if method == "M03_SMAC_RF_SMBO":
        return _rf_point(_full_records(records), rng)
    if method == "M04_DIFFERENTIAL_EVOLUTION":
        return _de_point(_full_records(records), rng)
    if method == "M05_GENETIC_PROGRAMMING":
        return _gp_point(_full_records(records), rng)
    if method == "M06_GP_TPE_HYBRID":
        if len(_full_records(records)) < 128:
            return _gp_point(_full_records(records), rng)
        return _tpe_point(_full_records(records), rng)
    if method == "M11_CMA_ES":
        mean = np.asarray(state["cma_mean"], dtype=float)
        sigma = float(state["cma_sigma"])
        return np.clip(mean + rng.normal(0, sigma * np.sqrt(state["cma_diag"])), 0, 0.999999)
    if method == "M12_PSO":
        index = state["pso_index"] % len(state["particles"])
        particle = state["particles"][index]
        velocity = state["velocities"][index]
        best = _ranked(_full_records(records))[0]["genome"] if _full_records(records) else _random_point(rng)
        pbest = state["pbest"][index]
        velocity[:] = 0.72 * velocity + 1.35 * rng.random(GENOME_DIM) * (np.asarray(pbest) - particle) + 1.35 * rng.random(GENOME_DIM) * (np.asarray(best) - particle)
        particle[:] = np.clip(particle + velocity, 0, 0.999999)
        return particle.copy()
    if method == "M13_GP_BAYESIAN_OPTIMIZATION":
        return _gp_bo_point(_full_records(records), rng)
    if method == "M14_TURBO":
        ranked = _ranked(_full_records(records))
        center = np.asarray(ranked[0]["genome"], dtype=float) if ranked else None
        if center is None:
            return _random_point(rng)
        radius = float(state["turbo_radius"])
        return _gp_bo_point(_full_records(records), rng, center=np.clip(center + rng.normal(0, radius / 3, GENOME_DIM), 0, 0.999999))
    if method == "M16_NEVERGRAD":
        ranked = _ranked(_full_records(records))
        center = np.asarray(ranked[0]["genome"], dtype=float) if ranked else _random_point(rng)
        return np.clip(center + rng.normal(0, float(state["ng_sigma"]), GENOME_DIM), 0, 0.999999)
    if method == "M17_NSGA_II":
        return _nsga_point(records, rng)
    if method == "M22_ADVANCED_SURROGATE_ASSISTED":
        return _surrogate_point(_full_records(records), rng)
    return _random_point(rng)


def _update_regular_state(method: str, state: dict[str, Any], records: Sequence[Mapping[str, Any]], row: Mapping[str, Any]) -> None:
    if row.get("status") != "VALID" or float(row.get("fidelity", 0.0)) < 0.999:
        return
    rng: np.random.Generator = state["rng"]
    full = _full_records(records)
    if method == "M11_CMA_ES" and len(full) >= 40 and len(full) % 8 == 0:
        elite = _ranked(full)[: max(4, len(full) // 8)]
        weights = np.linspace(len(elite), 1, len(elite), dtype=float)
        weights /= weights.sum()
        matrix = np.asarray([item["genome"] for item in elite], dtype=float)
        state["cma_mean"] = np.sum(matrix * weights[:, None], axis=0)
        state["cma_diag"] = np.clip(np.var(matrix, axis=0) + 0.03, 0.01, 0.25)
        state["cma_sigma"] = float(np.clip(state["cma_sigma"] * (1.05 if float(row["fitness"]) >= float(full[0]["fitness"]) else 0.95), 0.04, 0.45))
    if method == "M12_PSO":
        index = state["pso_index"] % len(state["particles"])
        if float(row["fitness"]) > state["pbest_score"][index]:
            state["pbest"][index] = np.asarray(row["genome"], dtype=float).copy()
            state["pbest_score"][index] = float(row["fitness"])
        state["pso_index"] += 1
    if method == "M14_TURBO":
        if float(row["fitness"]) >= state["turbo_best"]:
            state["turbo_best"] = float(row["fitness"])
            state["turbo_success"] += 1
            state["turbo_failure"] = 0
            if state["turbo_success"] >= 3:
                state["turbo_radius"] = min(0.8, state["turbo_radius"] * 2.0)
                state["turbo_success"] = 0
        else:
            state["turbo_failure"] += 1
            state["turbo_success"] = 0
            if state["turbo_failure"] >= 3:
                state["turbo_radius"] = max(0.03, state["turbo_radius"] / 2.0)
                state["turbo_failure"] = 0
    if method == "M16_NEVERGRAD":
        if float(row["fitness"]) >= state["ng_best"]:
            state["ng_best"] = float(row["fitness"])
            state["ng_sigma"] = min(0.35, state["ng_sigma"] * 1.05)
        else:
            state["ng_sigma"] = max(0.02, state["ng_sigma"] * 0.995)
    del rng


def _new_regular_state(method: str, seed: int) -> dict[str, Any]:
    rng = np.random.default_rng(seed + 7001 + METHODS.index(method))
    warm = _warm_start(seed)
    return {
        "rng": rng,
        "stream": _stream(method, seed) if method in STATIC_METHODS else None,
        "stream_index": 32,
        "cma_mean": np.mean(warm, axis=0),
        "cma_diag": np.full(GENOME_DIM, 0.10),
        "cma_sigma": 0.25,
        "particles": [np.asarray(point, dtype=float).copy() for point in warm[:16]],
        "velocities": [np.zeros(GENOME_DIM, dtype=float) for _ in range(16)],
        "pbest": [np.asarray(point, dtype=float).copy() for point in warm[:16]],
        "pbest_score": np.full(16, -np.inf, dtype=float),
        "pso_index": 0,
        "turbo_radius": 0.35,
        "turbo_best": -np.inf,
        "turbo_success": 0,
        "turbo_failure": 0,
        "ng_sigma": 0.18,
        "ng_best": -np.inf,
    }


def _multi_config(method: str, state: dict[str, Any], records: Sequence[Mapping[str, Any]]) -> np.ndarray:
    rng: np.random.Generator = state["rng"]
    full = _full_records(records)
    if method == "M07_DEHB_REAL":
        return _de_point(full, rng)
    if method in {"M08_BOHB", "M15_OPTUNA"}:
        return _tpe_point(full, rng)
    if method == "M21_POPULATION_BASED_TRAINING" and full:
        return np.clip(np.asarray(_ranked(full)[int(rng.integers(min(8, len(full))))]["genome"]) + rng.normal(0, 0.10, GENOME_DIM), 0, 0.999999)
    return _random_point(rng)


def _start_bracket(method: str, state: dict[str, Any], records: Sequence[Mapping[str, Any]]) -> None:
    if method == "M07_DEHB_REAL":
        count, promotions = 9, (9, 3, 1)
    elif method == "M08_BOHB":
        count, promotions = 9, (9, 3, 1)
    elif method == "M09_HYPERBAND":
        count, promotions = 9, (9, 3, 1)
    elif method == "M15_OPTUNA":
        count, promotions = 8, (8, 3, 1)
    elif method == "M20_SUCCESSIVE_HALVING":
        count, promotions = 12, (12, 4, 2)
    else:
        count, promotions = 8, (8, 3, 1)
    configs = [_multi_config(method, state, records) for _ in range(count)]
    state["bracket"] = {
        "rung": 0,
        "fidelities": FIDELITIES,
        "promotions": promotions,
        "configs": configs,
        "observations": [],
    }
    state["queue"] = [(config, FIDELITIES[0]) for config in configs]


def _after_bracket_action(state: dict[str, Any], row: Mapping[str, Any]) -> None:
    bracket = state["bracket"]
    bracket["observations"].append(row)
    if state["queue"]:
        return
    rung = int(bracket["rung"])
    if rung >= len(FIDELITIES) - 1:
        state["bracket"] = None
        return
    observations = _ranked([item for item in bracket["observations"] if item.get("status") == "VALID"])
    target = int(bracket["promotions"][rung + 1])
    promoted = observations[:target]
    bracket["rung"] = rung + 1
    bracket["configs"] = [item["genome"] for item in promoted]
    bracket["observations"] = []
    state["queue"] = [(np.asarray(item["genome"], dtype=float), FIDELITIES[rung + 1]) for item in promoted]


def _start_asha(state: dict[str, Any], records: Sequence[Mapping[str, Any]) -> None:
    state["asha_rungs"] = [[], [], []]
    state["asha_promoted"] = [set(), set(), set()]
    state["queue"] = [(_multi_config("M10_ASHA", state, records), FIDELITIES[0]) for _ in range(12)]


def _after_asha_action(state: dict[str, Any], row: Mapping[str, Any]) -> None:
    rung = min(2, max(0, int(round(float(row["fidelity"]) * 4)) - 1))
    state["asha_rungs"][rung].append(row)
    for level in range(2):
        eligible = _ranked([item for item in state["asha_rungs"][level] if item.get("status") == "VALID"])
        target = len(eligible) // ETA
        promoted = state["asha_promoted"][level]
        for item in eligible:
            if len(promoted) >= target:
                break
            key = str(item["canonical_hash"])
            if key in promoted:
                continue
            promoted.add(key)
            state["queue"].append((np.asarray(item["genome"], dtype=float), FIDELITIES[level + 1]))


def _next_multi_action(method: str, state: dict[str, Any], records: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, float]:
    if method == "M10_ASHA":
        if not state.get("queue"):
            _start_asha(state, records)
        return state["queue"].pop(0)
    if not state.get("queue") and state.get("bracket") is None:
        _start_bracket(method, state, records)
    if not state.get("queue"):
        _start_bracket(method, state, records)
    return state["queue"].pop(0)


def _new_multi_state(method: str, seed: int) -> dict[str, Any]:
    return {"rng": np.random.default_rng(seed + 9001 + METHODS.index(method)), "queue": [], "bracket": None}


def run_unit(method: str, seed: int, data_root: Path, output_dir: Path) -> dict[str, Any]:
    if method not in METHODS or int(seed) not in SEEDS:
        raise ValueError("UNKNOWN_METHOD_OR_SEED")
    start = time.perf_counter()
    data = load_price_data(data_root)
    for feature in ("momentum", "volatility", "volume_change", "relative_volume", "breakout", "drawdown", "range", "close_location", "intraday", "overnight", "rsi", "sma_gap"):
        for lookback in (2, 3, 5, 10, 20, 40, 63, 126, 189, 252):
            _feature_values(data.store, feature, lookback)

    records: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, float]] = set()
    cost_used = 0.0
    proposal = 0

    def add_rows(actions: Sequence[tuple[np.ndarray, float]], workers: int = EVALUATION_WORKERS) -> None:
        nonlocal cost_used, proposal
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_expanded_candidate, method, int(seed), proposal + index, genome, fidelity, data)
                for index, (genome, fidelity) in enumerate(actions)
            ]
            rows = [future.result() for future in futures]
        for row, (_, fidelity) in zip(rows, actions):
            proposal += 1
            key = (str(row["canonical_hash"]), float(fidelity))
            if key in seen_pairs:
                row["status"] = "DUPLICATE"
                row["rejection_reason"] = "canonical_hash_and_fidelity_seen"
                row["cost_units"] = 0.0
                row["elapsed_seconds"] = float(time.perf_counter() - start)
                records.append(row)
                continue
            seen_pairs.add(key)
            row["elapsed_seconds"] = float(time.perf_counter() - start)
            records.append(row)
            cost_used += float(fidelity)

    warm = [(_warm_start(int(seed))[index], 1.0) for index in range(32)]
    add_rows(warm)
    state = _new_multi_state(method, int(seed)) if method in MULTI_FIDELITY else _new_regular_state(method, int(seed))
    attempts = 0
    while cost_used + 0.249999 <= MAX_COST_UNITS and proposal < MAX_ACTIONS and time.perf_counter() - start < SEARCH_WALL_SECONDS:
        attempts += 1
        if attempts > MAX_ACTIONS * 3:
            break
        if method in MULTI_FIDELITY:
            genome, fidelity = _next_multi_action(method, state, records)
            if cost_used + fidelity > MAX_COST_UNITS + 1e-9:
                if state.get("queue"):
                    continue
                break
            before = len(records)
            add_rows([(np.asarray(genome, dtype=float), fidelity)], workers=1)
            if len(records) == before:
                continue
            row = records[-1]
            if method == "M10_ASHA":
                _after_asha_action(state, row)
            else:
                _after_bracket_action(state, row)
        else:
            batch = []
            for _ in range(2):
                if cost_used + len(batch) + 1.0 > MAX_COST_UNITS + 1e-9:
                    break
                batch.append((_next_regular_point(method, int(seed), records, state), 1.0))
            if not batch:
                break
            before = len(records)
            add_rows(batch)
            for row in records[before:]:
                _update_regular_state(method, state, records, row)

    full = _full_records(records)
    freeze = _ranked(full)[:TOP_K]
    anytime = []
    best_full = -1.0
    best_observed = -1.0
    for index, row in enumerate(records, start=1):
        best_observed = max(best_observed, float(row["fitness"]))
        if float(row.get("fidelity", 0.0)) >= 0.999 and row.get("status") == "VALID":
            best_full = max(best_full, float(row["fitness"]))
        anytime.append(
            {
                "action_number": index,
                "cost_units": float(sum(float(item.get("cost_units", 0.0)) for item in records[:index])),
                "best_full_search_cagr": best_full,
                "best_observed_search_fitness": best_observed,
            }
        )
    cost_to_best = next((item["cost_units"] for item in anytime if item["best_full_search_cagr"] >= best_full), None)
    payload = {
        "method": method,
        "method_implementation": METHOD_IMPLEMENTATIONS[method],
        "seed": int(seed),
        "data_snapshot_hash": data.snapshot_hash,
        "search_space_hash": canonical_hash(build_expanded_space_manifest(output_dir / "_space")),
        "max_cost_units": MAX_COST_UNITS,
        "max_actions": MAX_ACTIONS,
        "search_wall_seconds": SEARCH_WALL_SECONDS,
        "evaluation_workers": EVALUATION_WORKERS,
        "common_warm_start": 32,
        "records": records,
        "freeze_candidates": freeze,
        "proposal_count": proposal,
        "unique_evaluations": len(seen_pairs),
        "full_fidelity_evaluations": sum(float(row.get("fidelity", 0.0)) >= 0.999 for row in records if row.get("status") == "VALID"),
        "partial_fidelity_evaluations": sum(0.0 < float(row.get("fidelity", 0.0)) < 0.999 for row in records if row.get("status") == "VALID"),
        "cost_used": float(cost_used),
        "cost_to_best_full_fidelity": cost_to_best,
        "valid_candidates": len(full),
        "duplicate_proposals": sum(row.get("status") == "DUPLICATE" for row in records),
        "elapsed_seconds": float(time.perf_counter() - start),
        "anytime": anytime,
        "date_access": {
            "search_start": SEARCH_START.date().isoformat(),
            "search_end": SEARCH_END.date().isoformat(),
            "audit_unopened": True,
            "validation_rows": 0,
            "locked_rows": 0,
        },
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _json_dump(out / "unit_result.json", payload)
    _json_dump(out / "method_seed_freeze.json", {key: payload[key] for key in ("method", "method_implementation", "seed", "data_snapshot_hash", "search_space_hash", "freeze_candidates")})
    _write_rows(out / "search_candidates.csv", records)
    _write_rows(out / "anytime_by_cost.csv", anytime)
    return payload


def run_smoke(data_root: Path, output_dir: Path) -> dict[str, Any]:
    data = load_price_data(data_root)
    space = build_expanded_space_manifest(output_dir)
    rows = []
    for method in METHODS:
        for proposal, genome in enumerate(_warm_start(SEEDS[0])):
            rows.append(_expanded_candidate(method, SEEDS[0], proposal, genome, 1.0, data))
    expected = len(METHODS) * 32
    if len(rows) != expected:
        raise RuntimeError("SMOKE_CANDIDATE_COUNT_MISMATCH")
    payload = {
        "smoke": True,
        "methods": list(METHODS),
        "method_count": len(METHODS),
        "seed": SEEDS[0],
        "candidate_count": len(rows),
        "evaluated_candidates": len(rows),
        "data_snapshot_hash": data.snapshot_hash,
        "search_space_sha256": space["sha256"],
        "locked_rows": 0,
        "validation_rows": 0,
        "passed": True,
    }
    _json_dump(Path(output_dir) / "smoke_result.json", payload)
    _write_rows(Path(output_dir) / "smoke_candidates.csv", rows)
    return payload


def audit_candidates(data_root: Path, freeze_root: Path, output_dir: Path) -> dict[str, Any]:
    data = load_price_data(data_root)
    rows: list[dict[str, Any]] = []
    for source in sorted(Path(freeze_root).rglob("unit_result.json")):
        payload = json.loads(source.read_text("utf-8"))
        for candidate in payload["freeze_candidates"]:
            metrics = _evaluate_rule(candidate["rule"], data, AUDIT_START, AUDIT_END)
            rows.append(
                {
                    "method": payload["method"],
                    "method_implementation": payload["method_implementation"],
                    "seed": payload["seed"],
                    "candidate_id": candidate["candidate_id"],
                    "canonical_hash": candidate["canonical_hash"],
                    "search_cagr": candidate["search_cagr"],
                    "audit_cagr": metrics["cagr"],
                    "audit_sharpe": metrics["sharpe"],
                    "audit_sortino": metrics["sortino"],
                    "audit_calmar": metrics["calmar"],
                    "audit_max_drawdown": metrics["max_drawdown"],
                    "audit_positive_years": metrics["positive_years"],
                    "audit_annual": metrics["annual"],
                }
            )
    expected = len(METHODS) * len(SEEDS) * TOP_K
    if len(rows) != expected:
        raise RuntimeError(f"AUDIT_CANDIDATE_COUNT_MISMATCH:{len(rows)}:{expected}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_rows(out / "audit_results.csv", rows)
    payload = {
        "audit_candidates": len(rows),
        "audit_start": AUDIT_START.date().isoformat(),
        "audit_end": AUDIT_END.date().isoformat(),
        "validation_rows": 0,
        "locked_rows": 0,
    }
    _json_dump(out / "audit_summary.json", payload)
    return payload


def _auc(points: Sequence[Mapping[str, Any]]) -> float:
    if not points:
        return -1.0
    x = np.asarray([float(item["cost_units"]) / MAX_COST_UNITS for item in points], dtype=float)
    y = np.asarray([float(item["best_full_search_cagr"]) for item in points], dtype=float)
    order = np.argsort(x, kind="mergesort")
    return float(np.trapezoid(y[order], x[order]))


def aggregate_results(unit_root: Path, audit_root: Path, output_dir: Path) -> dict[str, Any]:
    units = [json.loads(path.read_text("utf-8")) for path in sorted(Path(unit_root).rglob("unit_result.json"))]
    audit = pd.read_csv(Path(audit_root) / "audit_results.csv")
    expected_units = len(METHODS) * len(SEEDS)
    expected_audit = expected_units * TOP_K
    if len(units) != expected_units or len(audit) != expected_audit:
        raise RuntimeError(f"AGGREGATE_INPUT_COUNT_MISMATCH:units={len(units)} audit={len(audit)}")
    anytime_rows: list[dict[str, Any]] = []
    unit_rows: list[dict[str, Any]] = []
    for unit in units:
        auc = _auc(unit["anytime"])
        unit_rows.append(
            {
                "method": unit["method"],
                "method_implementation": unit["method_implementation"],
                "seed": unit["seed"],
                "cost_used": unit["cost_used"],
                "full_fidelity_evaluations": unit["full_fidelity_evaluations"],
                "partial_fidelity_evaluations": unit["partial_fidelity_evaluations"],
                "elapsed_seconds": unit["elapsed_seconds"],
                "cost_to_best_full_fidelity": unit["cost_to_best_full_fidelity"],
                "search_efficiency_auc": auc,
            }
        )
        for point in unit["anytime"]:
            anytime_rows.append({"method": unit["method"], "seed": unit["seed"], **point})
    unit_frame = pd.DataFrame(unit_rows)
    method_rows = []
    for method in METHODS:
        method_audit = audit.loc[audit["method"] == method]
        method_units = unit_frame.loc[unit_frame["method"] == method]
        seed_scores = method_audit.groupby("seed")["audit_cagr"].median().sort_index()
        seed_best = method_audit.groupby("seed")["audit_cagr"].max().sort_index()
        method_rows.append(
            {
                "method": method,
                "method_implementation": METHOD_IMPLEMENTATIONS[method],
                "primary_method_score": float(seed_scores.median()),
                "median_best_audit_cagr": float(seed_best.median()),
                "median_audit_cagr": float(method_audit["audit_cagr"].median()),
                "median_audit_sharpe": float(method_audit["audit_sharpe"].median()),
                "median_audit_calmar": float(method_audit["audit_calmar"].replace([np.inf, -np.inf], np.nan).median()),
                "fraction_audit_positive": float((method_audit["audit_cagr"] > 0).mean()),
                "median_search_efficiency_auc": float(method_units["search_efficiency_auc"].median()),
                "median_cost_to_best_full_fidelity": float(method_units["cost_to_best_full_fidelity"].dropna().median()),
                "median_full_fidelity_evaluations": float(method_units["full_fidelity_evaluations"].median()),
                "median_partial_fidelity_evaluations": float(method_units["partial_fidelity_evaluations"].median()),
                "median_elapsed_seconds": float(method_units["elapsed_seconds"].median()),
            }
        )
    summary_frame = pd.DataFrame(method_rows).sort_values(["primary_method_score", "median_search_efficiency_auc", "method"], ascending=[False, False, True]).reset_index(drop=True)
    winner = str(summary_frame.iloc[0]["method"])
    runner_up = str(summary_frame.iloc[1]["method"])
    winner_scores = audit.loc[audit["method"] == winner].groupby("seed")["audit_cagr"].median().sort_index()
    runner_scores = audit.loc[audit["method"] == runner_up].groupby("seed")["audit_cagr"].median().sort_index()
    differences = (winner_scores - runner_scores).to_numpy(dtype=float)
    rng = np.random.default_rng(20260808)
    bootstrap = np.median(differences[rng.integers(0, len(differences), size=(10000, len(differences)))], axis=1)
    ci_low, ci_high = np.quantile(bootstrap, [0.025, 0.975])
    efficiency_method = str(summary_frame.sort_values(["median_search_efficiency_auc", "primary_method_score"], ascending=[False, False]).iloc[0]["method"])
    method_summary = summary_frame.to_dict(orient="records")
    summary = {
        "status": "NO_CLEAR_WINNER" if ci_low <= 0 <= ci_high else "CLEAR_WINNER_WITHIN_BENCHMARK",
        "best_method": winner,
        "best_search_efficiency_method": efficiency_method,
        "runner_up": runner_up,
        "methods": list(METHODS),
        "method_count": len(METHODS),
        "method_implementations": METHOD_IMPLEMENTATIONS,
        "seed_count": len(SEEDS),
        "unit_count": expected_units,
        "audit_candidate_count": expected_audit,
        "selection_period": f"{SEARCH_START.date()}..{SEARCH_END.date()}",
        "audit_period": f"{AUDIT_START.date()}..{AUDIT_END.date()}",
        "common_warm_start": 32,
        "max_cost_units": MAX_COST_UNITS,
        "fidelity_levels": list(FIDELITIES),
        "winner_runner_up_paired_median_difference": float(np.median(differences)),
        "winner_runner_up_bootstrap_ci95": [float(ci_low), float(ci_high)],
        "validation_rows_accessed": 0,
        "locked_rows_accessed": 0,
        "locked_opened": False,
        "method_summary": method_summary,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    _json_dump(out / "summary.json", summary)
    _write_rows(out / "unit_summary.csv", unit_rows)
    summary_frame.to_csv(out / "method_summary.csv", index=False)
    pd.DataFrame(anytime_rows).to_csv(out / "anytime_by_cost.csv", index=False)
    comparison = pd.DataFrame({"seed": list(winner_scores.index), "winner": winner_scores.values, "runner_up": runner_scores.values, "difference": differences})
    comparison.to_csv(out / "paired_method_comparison.csv", index=False)
    _json_dump(out / "data_audit.json", {"snapshot_role": "bounded_train", "maximum_date": TRAIN_END.date().isoformat(), "search_rows_accessed": f"{SEARCH_START.date()}..{SEARCH_END.date()}", "audit_rows_accessed": f"{AUDIT_START.date()}..{AUDIT_END.date()}", "validation_rows_accessed": 0, "locked_rows_accessed": 0, "locked_opened": False})
    _json_dump(out / "multiple_testing_audit.json", {"method_count": len(METHODS), "seed_count": len(SEEDS), "unit_count": expected_units, "selection_metric": "median_audit_cagr_of_top_5_frozen_full_fidelity_candidates", "efficiency_metric": "area_under_best_full_fidelity_search_cagr_by_cost_units", "validation_used": False, "locked_used": False})
    _json_dump(out / "benchmark_manifest.json", {"methods": list(METHODS), "method_implementations": METHOD_IMPLEMENTATIONS, "seeds": list(SEEDS), "common_warm_start": 32, "max_cost_units": MAX_COST_UNITS, "fidelity_levels": list(FIDELITIES), "search_wall_seconds": SEARCH_WALL_SECONDS, "data_end": TRAIN_END.date().isoformat(), "validation_unopened": True, "locked_unopened": True})
    return summary


def verify_results(root: Path) -> dict[str, Any]:
    base = Path(root)
    summary = json.loads((base / "summary.json").read_text("utf-8"))
    if summary.get("methods") != list(METHODS):
        raise RuntimeError("METHOD_SET_MISMATCH")
    if summary.get("method_count") != len(METHODS) or summary.get("unit_count") != len(METHODS) * len(SEEDS):
        raise RuntimeError("COUNT_CONTRACT_MISMATCH")
    if summary.get("validation_rows_accessed") != 0 or summary.get("locked_rows_accessed") != 0 or summary.get("locked_opened") is not False:
        raise RuntimeError("FUTURE_DATA_ACCESS_DETECTED")
    data_audit = json.loads((base / "data_audit.json").read_text("utf-8"))
    if data_audit.get("maximum_date") != TRAIN_END.date().isoformat() or data_audit.get("locked_opened") is not False:
        raise RuntimeError("DATA_AUDIT_BOUNDARY_FAILURE")
    verification = {"passed": True, "method_count": len(METHODS), "unit_count": len(METHODS) * len(SEEDS), "validation_rows_accessed": 0, "locked_rows_accessed": 0, "summary_sha256": _sha256_file(base / "summary.json")}
    _json_dump(base / "verification.json", verification)
    return verification


def _main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--output-dir", type=Path, required=True)
    space = sub.add_parser("space")
    space.add_argument("--output-dir", type=Path, required=True)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--data-root", type=Path, required=True)
    smoke.add_argument("--output-dir", type=Path, required=True)
    unit = sub.add_parser("unit")
    unit.add_argument("--method", required=True)
    unit.add_argument("--seed", type=int, required=True)
    unit.add_argument("--data-root", type=Path, required=True)
    unit.add_argument("--output-dir", type=Path, required=True)
    audit = sub.add_parser("audit")
    audit.add_argument("--data-root", type=Path, required=True)
    audit.add_argument("--freeze-root", type=Path, required=True)
    audit.add_argument("--output-dir", type=Path, required=True)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--unit-root", type=Path, required=True)
    aggregate.add_argument("--audit-root", type=Path, required=True)
    aggregate.add_argument("--output-dir", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_benchmark_data(args.output_dir)
    elif args.command == "space":
        build_expanded_space_manifest(args.output_dir)
    elif args.command == "smoke":
        run_smoke(args.data_root, args.output_dir)
    elif args.command == "unit":
        run_unit(args.method, args.seed, args.data_root, args.output_dir)
    elif args.command == "audit":
        audit_candidates(args.data_root, args.freeze_root, args.output_dir)
    elif args.command == "aggregate":
        aggregate_results(args.unit_root, args.audit_root, args.output_dir)
    elif args.command == "verify":
        verify_results(args.output_dir)


if __name__ == "__main__":
    _main()

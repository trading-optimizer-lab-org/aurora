"""Deterministic candidate and provenance registries for autonomous batches."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from aurora.infra.sp500_long_short_daily.contracts import CampaignPackage
from aurora.infra.sp500_long_short_daily.signals import IMPLEMENTED_FAMILIES

from .contracts import (
    LOCKED_START,
    PREVIOUS_TRIAL_COUNT,
    TRAIN_END,
    VALIDATION_END,
    VALIDATION_START,
    assert_contract,
    canonical_rule_hash,
)
from .historical_evidence import (
    HISTORICAL_DIR,
    load_historical_trial_ledger,
    load_prior_autonomous_status,
)


def repo_root() -> Path:
    for candidate in (Path.cwd(), Path(__file__).resolve().parents[2]):
        if (candidate / "campaigns" / "sp500_long_short_daily" / "research_input").is_dir():
            return candidate.resolve()
    raise RuntimeError("AURORA_REPO_ROOT_NOT_FOUND")


def base_package() -> CampaignPackage:
    root = repo_root() / "campaigns" / "sp500_long_short_daily"
    return CampaignPackage.load(
        root / "research_input",
        root / "input_package" / "SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip",
    )


def _seed(batch_id: int) -> int:
    digest = hashlib.sha256(f"sp500-autonomous:{batch_id}".encode()).hexdigest()
    return int(digest[:16], 16)


def get_previous_trial_count() -> int:
    value = os.environ.get("AURORA_AUTONOMOUS_PREVIOUS_TRIAL_COUNT", str(PREVIOUS_TRIAL_COUNT))
    if not value.isdigit() or int(value) < PREVIOUS_TRIAL_COUNT:
        raise ValueError("INVALID_PREVIOUS_TRIAL_COUNT")
    return int(value)


def _numeric_mutation(value: Any, rng: random.Random) -> Any:
    if isinstance(value, list) and value and all(
        isinstance(item, (int, float)) and not isinstance(item, bool)
        for item in value
    ):
        scale = rng.choice((0.75, 0.9, 1.0, 1.1, 1.25))
        mutated = [
            max(1, int(round(item * scale)))
            if isinstance(item, int)
            else round(float(item) * scale, 8)
            for item in value
        ]
        return mutated
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if isinstance(value, int):
        scale = rng.choice((0.75, 0.9, 1.0, 1.1, 1.25))
        return max(1, int(round(value * scale)))
    scale = rng.choice((0.75, 0.9, 1.0, 1.1, 1.25))
    return round(float(value) * scale, 8)


def _mutate(template: Mapping[str, Any], batch_id: int, index: int, rng: random.Random) -> dict[str, Any]:
    candidate = json.loads(json.dumps(template))
    candidate.update(
        {
            "instrument": "SPY",
            "cash_allowed": False,
            "partial_exposure_allowed": False,
            "leverage_allowed": False,
            "volatility_scaling_allowed": False,
            "pyramiding_allowed": False,
            "multiple_assets_in_portfolio": False,
        }
    )
    candidate["strategy_id"] = f"AUTO-B{batch_id:04d}-{index:04d}"
    candidate["variant_label"] = f"autonomous_batch_{batch_id}_{index}"
    candidate["evidence_track"] = "pre_2011_evidence"
    candidate["selection_role"] = "autonomous_pre_registered_candidate"
    parameters = dict(candidate.get("parameters", {}))
    for key in sorted(parameters):
        if rng.random() < 0.85:
            parameters[key] = _numeric_mutation(parameters[key], rng)
    candidate["parameters"] = parameters
    candidate["priority_score"] = max(1, 100 - index)
    candidate["canonical_hash"] = canonical_rule_hash(candidate)
    assert_contract(candidate)
    return candidate


def _targeted_reversal_candidates(
    package: CampaignPackage,
    batch_id: int,
    count: int,
) -> tuple[dict[str, Any], ...]:
    """Build a deterministic train-only grid after the broad search plateaued."""

    usable = [
        row
        for row in package.candidates
        if str(row.get("family")) in IMPLEMENTED_FAMILIES
        and set(row.get("required_datasets", ())).issubset({"DS001", "DS002"})
    ]
    if not usable:
        raise RuntimeError("NO_USABLE_CAUSAL_TEMPLATES")
    base = next(
        (row for row in usable if str(row.get("family")) == "short_horizon_reversal"),
        usable[0],
    )
    cycle = max(0, batch_id - 3)
    threshold_shift = 0.1 * cycle
    definitions: list[tuple[str, dict[str, Any], str, str, str]] = []

    for rsi_window, lower, upper, trend_window in (
        (2, 10, 90, 20), (2, 10, 90, 50), (2, 10, 90, 100), (2, 10, 90, 200),
        (2, 20, 80, 20), (2, 20, 80, 50), (2, 20, 80, 100), (2, 20, 80, 200),
        (3, 20, 80, 20), (3, 20, 80, 50), (3, 20, 80, 100), (3, 20, 80, 200),
    ):
        definitions.append((
            "rsi_trend_blend",
            {
                "rsi_window": rsi_window,
                "lower": lower,
                "upper": upper,
                "trend_window": trend_window,
            },
            "use RSI reversal at extremes; otherwise use causal price trend",
            "score_t > 0",
            "score_t < 0",
        ))
    for window, lower, upper in (
        (2, 5, 95), (2, 10, 90), (2, 15, 85), (2, 20, 80),
        (3, 10, 90), (3, 15, 85), (3, 20, 80), (3, 25, 75),
        (5, 15, 85), (5, 20, 80), (5, 25, 75), (5, 30, 70),
    ):
        definitions.append((
            "rsi_reversal",
            {"window": window, "lower": lower, "upper": upper},
            f"Wilder_RSI_{window} through close t",
            f"RSI_t <= {lower}",
            f"RSI_t >= {upper}",
        ))
    for lower, upper in (
        (0.05, 0.95), (0.10, 0.90), (0.15, 0.85), (0.20, 0.80),
        (0.25, 0.75), (0.30, 0.70), (0.35, 0.65), (0.40, 0.60),
        (0.10, 0.80), (0.20, 0.90), (0.15, 0.75), (0.25, 0.85),
    ):
        definitions.append((
            "internal_bar_strength_reversal",
            {"lower": lower, "upper": upper},
            "IBS_t = (TR_CLOSE_t - LOW_t) / (HIGH_t - LOW_t)",
            f"IBS_t <= {lower}",
            f"IBS_t >= {upper}",
        ))
    for lookback, threshold in (
        (1, 0.25), (1, 0.50), (1, 0.75), (1, 1.00),
        (2, 0.50), (2, 1.00), (2, 1.50), (2, 2.00),
        (3, 0.75), (3, 1.50), (5, 1.00), (5, 2.00),
    ):
        adjusted = round(threshold + threshold_shift, 4)
        definitions.append((
            "return_threshold_reversal",
            {"lookback": lookback, "threshold_pct": adjusted},
            f"lag_return_t = TR_CLOSE_t / TR_CLOSE[t-{lookback}] - 1",
            f"lag_return_t <= -{adjusted}%",
            f"lag_return_t >= {adjusted}%",
        ))
    for streak in range(2, 14):
        definitions.append((
            "streak_reversal",
            {"streak": streak},
            "streak_t = signed count of consecutive close-to-close moves through t",
            f"streak_t <= -{streak}",
            f"streak_t >= {streak}",
        ))
    for reversal_window, trend_window, threshold in (
        (1, 20, 0.5), (1, 50, 0.5), (1, 100, 0.5), (1, 200, 0.5),
        (2, 20, 1.0), (2, 50, 1.0), (2, 100, 1.0), (2, 200, 1.0),
        (3, 20, 1.5), (3, 50, 1.5), (3, 100, 1.5), (3, 200, 1.5),
    ):
        adjusted = round(threshold + threshold_shift, 4)
        definitions.append((
            "reversal_trend_blend",
            {
                "reversal_window": reversal_window,
                "trend_window": trend_window,
                "reversal_threshold_pct": adjusted,
            },
            "use short-return reversal after an extreme move; otherwise use causal trend",
            "effective score_t > 0",
            "effective score_t < 0",
        ))
    for horizons in (
        [1, 2], [1, 3], [1, 5], [2, 3], [2, 5], [3, 5],
        [1, 2, 3], [1, 2, 5], [1, 3, 5], [2, 3, 5], [1, 2, 3, 5], [2, 3, 5, 10],
    ):
        definitions.append((
            "multi_horizon_reversal",
            {"horizons": horizons},
            f"score_t = -mean(return_h through t for h in {horizons})",
            "score_t > 0",
            "score_t < 0",
        ))
    for threshold in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5, 2.0):
        adjusted = round(threshold + threshold_shift, 4)
        definitions.append((
            "intraday_return_reversal",
            {"threshold_pct": adjusted},
            "intraday_return_t = TR_CLOSE_t / TR_OPEN_t - 1",
            f"intraday_return_t <= -{adjusted}%",
            f"intraday_return_t >= {adjusted}%",
        ))

    candidates: list[dict[str, Any]] = []
    hashes: set[str] = set()
    for index, (family, parameters, formula, long_rule, short_rule) in enumerate(definitions):
        if len(candidates) >= count:
            break
        candidate = json.loads(json.dumps(base))
        candidate.update(
            {
                "instrument": "SPY",
                "cash_allowed": False,
                "partial_exposure_allowed": False,
                "leverage_allowed": False,
                "volatility_scaling_allowed": False,
                "pyramiding_allowed": False,
                "multiple_assets_in_portfolio": False,
                "strategy_id": f"AUTO-B{batch_id:04d}-{index:04d}",
                "variant_label": f"autonomous_targeted_batch_{batch_id}_{index}",
                "family": family,
                "family_name": family.replace("_", " ").title(),
                "parameters": parameters,
                "required_datasets": ["DS001", "DS002"],
                "feature_formulas": [formula],
                "long_rule": long_rule,
                "short_rule": short_rule,
                "features": [f"AUTO_TARGETED_{family.upper()}"],
                "warmup_rule": "No signal before every causal input required by the rule is defined.",
                "known_failure_modes": "Train-only hypothesis; must pass every frozen robustness gate.",
                "economic_sign_rationale": "Tests whether documented short-horizon price pressure mean-reverts at the next open.",
                "priority_score": max(1, 100 - index),
                "evidence_track": "pre_2011_evidence",
                "selection_role": "autonomous_pre_registered_candidate",
            }
        )
        candidate["canonical_hash"] = canonical_rule_hash(candidate)
        if candidate["canonical_hash"] in hashes:
            continue
        assert_contract(candidate)
        hashes.add(str(candidate["canonical_hash"]))
        candidates.append(candidate)
    if len(candidates) != count:
        raise RuntimeError(f"TARGETED_CANDIDATE_COUNT_MISMATCH:{len(candidates)}:{count}")
    return tuple(candidates)


def _neighborhood_reversal_candidates(
    package: CampaignPackage,
    batch_id: int,
    count: int,
) -> tuple[dict[str, Any], ...]:
    """Search the two strongest batch-3 families without repeating its grid."""

    usable = [
        row
        for row in package.candidates
        if str(row.get("family")) in IMPLEMENTED_FAMILIES
        and set(row.get("required_datasets", ())).issubset({"DS001", "DS002"})
    ]
    if not usable:
        raise RuntimeError("NO_USABLE_CAUSAL_TEMPLATES")
    base = next(
        (row for row in usable if str(row.get("family")) == "short_horizon_reversal"),
        usable[0],
    )
    prior_reversal = {
        (1, 20, 0.5), (1, 50, 0.5), (1, 100, 0.5), (1, 200, 0.5),
        (2, 20, 1.0), (2, 50, 1.0), (2, 100, 1.0), (2, 200, 1.0),
        (3, 20, 1.5), (3, 50, 1.5), (3, 100, 1.5), (3, 200, 1.5),
    }
    prior_rsi = {
        (2, 10, 90, 20), (2, 10, 90, 50), (2, 10, 90, 100), (2, 10, 90, 200),
        (2, 20, 80, 20), (2, 20, 80, 50), (2, 20, 80, 100), (2, 20, 80, 200),
        (3, 20, 80, 20), (3, 20, 80, 50), (3, 20, 80, 100), (3, 20, 80, 200),
    }
    generation = batch_id - 4
    trend_windows = [30, 40, 60, 80, 100, 126, 150, 180, 200, 225]
    reversal_thresholds = [
        round(value + generation * 0.05, 4)
        for value in (0.35, 0.5, 0.65, 0.75, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6)
    ]
    reversal_grid = [
        (reversal_window, trend_window, threshold)
        for trend_window in trend_windows
        for threshold in reversal_thresholds
        for reversal_window in (1, 2, 3, 4, 5)
        if (reversal_window, trend_window, threshold) not in prior_reversal
    ]
    rsi_grid = [
        (window, lower, 100 - lower, trend_window)
        for trend_window in trend_windows
        for lower in (5, 10, 15, 20, 25, 30)
        for window in (2, 3, 4, 5, 7)
        if (window, lower, 100 - lower, trend_window) not in prior_rsi
    ]

    # Interleave the whole parameter space so the first 48 are not clustered
    # around one lookback or one trend horizon.
    def spread(rows: list[tuple[Any, ...]], wanted: int) -> list[tuple[Any, ...]]:
        return [rows[(index * len(rows)) // wanted] for index in range(wanted)]

    definitions: list[tuple[str, dict[str, Any], str, str, str]] = []
    for reversal_window, trend_window, threshold in spread(reversal_grid, count // 2):
        definitions.append((
            "reversal_trend_blend",
            {
                "reversal_window": reversal_window,
                "trend_window": trend_window,
                "reversal_threshold_pct": threshold,
            },
            "use short-return reversal after an extreme move; otherwise use causal trend",
            "effective score_t > 0",
            "effective score_t < 0",
        ))
    for window, lower, upper, trend_window in spread(rsi_grid, count - len(definitions)):
        definitions.append((
            "rsi_trend_blend",
            {
                "rsi_window": window,
                "lower": lower,
                "upper": upper,
                "trend_window": trend_window,
            },
            "use RSI reversal at extremes; otherwise use causal price trend",
            "score_t > 0",
            "score_t < 0",
        ))

    candidates: list[dict[str, Any]] = []
    for index, (family, parameters, formula, long_rule, short_rule) in enumerate(definitions):
        candidate = json.loads(json.dumps(base))
        candidate.update(
            {
                "instrument": "SPY",
                "cash_allowed": False,
                "partial_exposure_allowed": False,
                "leverage_allowed": False,
                "volatility_scaling_allowed": False,
                "pyramiding_allowed": False,
                "multiple_assets_in_portfolio": False,
                "strategy_id": f"AUTO-B{batch_id:04d}-{index:04d}",
                "variant_label": f"autonomous_neighborhood_batch_{batch_id}_{index}",
                "family": family,
                "family_name": family.replace("_", " ").title(),
                "parameters": parameters,
                "required_datasets": ["DS001", "DS002"],
                "feature_formulas": [formula],
                "long_rule": long_rule,
                "short_rule": short_rule,
                "features": [f"AUTO_NEIGHBORHOOD_{family.upper()}"],
                "warmup_rule": "No signal before every causal input required by the rule is defined.",
                "known_failure_modes": "Train-only neighborhood hypothesis; must pass every frozen robustness gate.",
                "economic_sign_rationale": "Refines the strongest pre-2011 reversal and trend interactions without validation access.",
                "priority_score": max(1, 100 - index),
                "evidence_track": "pre_2011_evidence",
                "selection_role": "autonomous_pre_registered_candidate",
            }
        )
        candidate["canonical_hash"] = canonical_rule_hash(candidate)
        assert_contract(candidate)
        candidates.append(candidate)
    if len(candidates) != count or len({row["canonical_hash"] for row in candidates}) != count:
        raise RuntimeError("NEIGHBORHOOD_CANDIDATE_COUNT_OR_HASH_MISMATCH")
    return tuple(candidates)


def _combined_reversal_candidates(
    package: CampaignPackage,
    batch_id: int,
    count: int,
) -> tuple[dict[str, Any], ...]:
    """Combine the two strongest train rules and refine the stable RSI region."""

    usable = [
        row
        for row in package.candidates
        if str(row.get("family")) in IMPLEMENTED_FAMILIES
        and set(row.get("required_datasets", ())).issubset({"DS001", "DS002"})
    ]
    if not usable:
        raise RuntimeError("NO_USABLE_CAUSAL_TEMPLATES")
    base = next(
        (row for row in usable if str(row.get("family")) == "short_horizon_reversal"),
        usable[0],
    )
    generation = batch_id - 5
    definitions: list[tuple[str, dict[str, Any], str, str, str]] = []
    vote_grid = [
        {
            "rsi_window": rsi_window,
            "lower": lower,
            "upper": 100 - lower,
            "rsi_trend_window": rsi_trend,
            "reversal_window": reversal_window,
            "reversal_threshold_pct": round(threshold + generation * 0.05, 4),
            "reversal_trend_window": reversal_trend,
            "rsi_weight": rsi_weight,
            "reversal_weight": reversal_weight,
        }
        for rsi_window in (4, 5, 6, 7)
        for lower in (20, 22, 25, 28, 30)
        for rsi_trend in (180, 200, 225, 252)
        for reversal_window in (3, 4, 5, 6)
        for threshold in (0.8, 1.0, 1.1, 1.25, 1.4)
        for reversal_trend in (40, 50, 60, 75, 100)
        for rsi_weight, reversal_weight in ((1, 1), (2, 1), (1, 2))
    ]
    fine_rsi_grid = [
        {
            "rsi_window": window,
            "lower": lower,
            "upper": 100 - lower,
            "trend_window": trend_window,
        }
        for trend_window in (205, 210, 215, 220, 230, 235, 240, 245, 250, 252, 260, 270)
        for lower in (18, 20, 22, 24, 25, 26, 28, 30, 32)
        for window in (3, 4, 5, 6, 7, 8)
    ]

    def spread(rows: list[dict[str, Any]], wanted: int) -> list[dict[str, Any]]:
        return [rows[(index * len(rows)) // wanted] for index in range(wanted)]

    vote_count = count if generation >= 1 else count // 2
    for parameters in spread(vote_grid, vote_count):
        definitions.append((
            "dual_reversal_trend_vote",
            parameters,
            "weighted vote of causal RSI-trend and return-reversal-trend components",
            "weighted score_t > 0",
            "weighted score_t < 0",
        ))
    for parameters in spread(fine_rsi_grid, count - len(definitions)):
        definitions.append((
            "rsi_trend_blend",
            parameters,
            "use RSI reversal at extremes; otherwise use causal price trend",
            "score_t > 0",
            "score_t < 0",
        ))

    candidates: list[dict[str, Any]] = []
    for index, (family, parameters, formula, long_rule, short_rule) in enumerate(definitions):
        candidate = json.loads(json.dumps(base))
        candidate.update(
            {
                "instrument": "SPY",
                "cash_allowed": False,
                "partial_exposure_allowed": False,
                "leverage_allowed": False,
                "volatility_scaling_allowed": False,
                "pyramiding_allowed": False,
                "multiple_assets_in_portfolio": False,
                "strategy_id": f"AUTO-B{batch_id:04d}-{index:04d}",
                "variant_label": f"autonomous_combined_batch_{batch_id}_{index}",
                "family": family,
                "family_name": family.replace("_", " ").title(),
                "parameters": parameters,
                "required_datasets": ["DS001", "DS002"],
                "feature_formulas": [formula],
                "long_rule": long_rule,
                "short_rule": short_rule,
                "features": [f"AUTO_COMBINED_{family.upper()}"],
                "warmup_rule": "No signal before every causal input required by the rule is defined.",
                "known_failure_modes": "Train-only combined hypothesis; must pass every frozen robustness gate.",
                "economic_sign_rationale": "Combines independently pre-registered reversal and trend interactions without validation access.",
                "priority_score": max(1, 100 - index),
                "evidence_track": "pre_2011_evidence",
                "selection_role": "autonomous_pre_registered_candidate",
            }
        )
        candidate["canonical_hash"] = canonical_rule_hash(candidate)
        assert_contract(candidate)
        candidates.append(candidate)
    if len(candidates) != count or len({row["canonical_hash"] for row in candidates}) != count:
        raise RuntimeError("COMBINED_CANDIDATE_COUNT_OR_HASH_MISMATCH")
    return tuple(candidates)


def generate_candidates(batch_id: int, *, count: int = 96) -> tuple[dict[str, Any], ...]:
    """Generate a reproducible, pre-registered batch from causal templates."""

    if batch_id < 0 or count < 1:
        raise ValueError("INVALID_BATCH_ARGUMENT")
    package = base_package()
    if batch_id >= 5:
        return _combined_reversal_candidates(package, batch_id, count)
    if batch_id >= 4:
        return _neighborhood_reversal_candidates(package, batch_id, count)
    if batch_id >= 3:
        return _targeted_reversal_candidates(package, batch_id, count)
    templates = [
        row for row in package.candidates
        if str(row.get("family")) in IMPLEMENTED_FAMILIES
        and set(row.get("required_datasets", ())).issubset({"DS001", "DS002"})
    ]
    if not templates:
        raise RuntimeError("NO_USABLE_CAUSAL_TEMPLATES")
    rng = random.Random(_seed(batch_id))
    candidates: list[dict[str, Any]] = []
    hashes: set[str] = set()
    for index in range(count):
        template_offset = index + batch_id * 7
        for attempt in range(max(100, len(templates) * 20)):
            template = templates[(template_offset + attempt) % len(templates)]
            candidate = _mutate(template, batch_id, index + attempt * count, rng)
            digest = str(candidate["canonical_hash"])
            if digest not in hashes:
                candidate["strategy_id"] = f"AUTO-B{batch_id:04d}-{index:04d}"
                candidate["canonical_hash"] = canonical_rule_hash(candidate)
                assert_contract(candidate)
                candidates.append(candidate)
                hashes.add(digest)
                break
        else:
            raise RuntimeError("CANDIDATE_HASH_COLLISION_LIMIT")
    return tuple(candidates)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_batch_registry(
    root: Path,
    *,
    batch_id: int,
    candidates: tuple[Mapping[str, Any], ...],
    previous_trial_count: int | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_jsonl(root / "candidate_registry.jsonl", candidates)
    package = base_package()
    research_rows = list(package.research)
    feature_rows = list(package.features)
    dataset_rows = list(package.datasets)
    with (root / "research_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in research_rows for key in row}))
        writer.writeheader()
        writer.writerows(research_rows)
    with (root / "feature_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in feature_rows for key in row}))
        writer.writeheader()
        writer.writerows(feature_rows)
    with (root / "dataset_registry.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted({key for row in dataset_rows for key in row}))
        writer.writeheader()
        writer.writerows(dataset_rows)
    previous_trial_count = previous_trial_count if previous_trial_count is not None else get_previous_trial_count()
    new_ledger_rows = [
        {
            "batch_id": batch_id,
            "canonical_hash": str(candidate["canonical_hash"]),
            "global_trial_index": previous_trial_count + index + 1,
            "pre_registered_before_performance": True,
            "status": "registered",
            "strategy_id": str(candidate["strategy_id"]),
        }
        for index, candidate in enumerate(candidates)
    ]
    prior_ledger_value = os.environ.get("AURORA_PRIOR_TRIAL_LEDGER_PATH", "").strip()
    prior_ledger_path = Path(prior_ledger_value) if prior_ledger_value else None
    prior_ledger_rows = (
        read_jsonl(prior_ledger_path)
        if prior_ledger_path is not None and prior_ledger_path.is_file()
        else []
    )
    historical_path = Path(root) / HISTORICAL_DIR / "historical_trial_ledger.jsonl"
    historical_rows = (
        load_historical_trial_ledger(root) if historical_path.is_file() else []
    )
    combined_prior: dict[int, dict[str, Any]] = {}
    for row in (*historical_rows, *prior_ledger_rows):
        index = int(row.get("global_trial_index", 0))
        if index < 1 or index > previous_trial_count:
            continue
        existing = combined_prior.get(index)
        if existing is not None and str(existing.get("strategy_id")) != str(
            row.get("strategy_id")
        ):
            raise ValueError(f"PRIOR_TRIAL_LEDGER_INDEX_COLLISION:{index}")
        combined_prior[index] = dict(row)
    status_lookup = load_prior_autonomous_status(root)
    for row in combined_prior.values():
        status = status_lookup.get(str(row.get("strategy_id")))
        if status is not None:
            row["status"] = str(status["status"])
            row["rejection_reason"] = str(status.get("rejection_reason") or "")
    complete_prior = [combined_prior[index] for index in sorted(combined_prior)]
    if previous_trial_count > PREVIOUS_TRIAL_COUNT and not prior_ledger_rows:
        raise ValueError("PRIOR_TRIAL_LEDGER_REQUIRED")
    if historical_rows and [int(row["global_trial_index"]) for row in complete_prior] != list(
        range(1, previous_trial_count + 1)
    ):
        raise ValueError("PRIOR_TRIAL_LEDGER_COUNT_MISMATCH")
    if not historical_rows and prior_ledger_rows:
        last_index = int(prior_ledger_rows[-1].get("global_trial_index", 0))
        if last_index != previous_trial_count:
            raise ValueError("PRIOR_TRIAL_LEDGER_COUNT_MISMATCH")
        complete_prior = list(prior_ledger_rows)
    ledger_rows = [*complete_prior, *new_ledger_rows]
    for row in ledger_rows:
        row["batch_id"] = str(row.get("batch_id", ""))
    ledger_payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ledger_rows
    )
    (root / "trial_ledger.jsonl").write_text(ledger_payload, encoding="utf-8")
    pd.DataFrame(ledger_rows).to_parquet(root / "autonomous_trial_ledger.parquet", index=False)
    manifest = {
        "schema_version": "1",
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "previous_trial_count": previous_trial_count,
        "global_trial_count_after_batch": previous_trial_count + len(candidates),
        "pre_registered_before_performance": True,
        "canonical_hashes_unique": len({row["canonical_hash"] for row in candidates}) == len(candidates),
        "train_end": TRAIN_END,
        "validation_start": VALIDATION_START,
        "validation_end": VALIDATION_END,
        "locked_start": LOCKED_START,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "trial_ledger_file": "trial_ledger.jsonl",
        "trial_ledger_rows": len(ledger_rows),
        "new_trial_ledger_rows": len(new_ledger_rows),
        "prior_trial_ledger_rows": len(complete_prior),
        "historical_trial_ledger_rows": len(historical_rows),
        "trial_ledger_sha256": hashlib.sha256(ledger_payload.encode("utf-8")).hexdigest(),
        "trial_indices": [row["global_trial_index"] for row in new_ledger_rows],
    }
    (root / "candidate_registry_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_batch_registry(root: Path) -> tuple[dict[str, Any], ...]:
    rows = tuple(read_jsonl(Path(root) / "candidate_registry.jsonl"))
    if not rows:
        raise RuntimeError("EMPTY_CANDIDATE_REGISTRY")
    for row in rows:
        assert_contract(row)
    if len({row["strategy_id"] for row in rows}) != len(rows):
        raise RuntimeError("DUPLICATE_CANDIDATE_IDS")
    if len({row["canonical_hash"] for row in rows}) != len(rows):
        raise RuntimeError("DUPLICATE_CANDIDATE_HASHES")
    return rows

"""Deterministic cost-aware assignment for candidate work units."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def cost_score(
    *,
    concept_timeout_rate: float = 0.0,
    family_timeout_rate: float = 0.0,
    exit_rule_timeout_rate: float = 0.0,
    market_overlay_timeout_rate: float = 0.0,
    aggressiveness_timeout_rate: float = 0.0,
) -> float:
    return (
        concept_timeout_rate * 5.0
        + family_timeout_rate * 2.0
        + exit_rule_timeout_rate * 2.0
        + market_overlay_timeout_rate
        + aggressiveness_timeout_rate
    )


def assign_by_cost(candidates: Sequence[Mapping[str, Any]], job_count: int) -> list[dict[str, Any]]:
    if job_count < 1:
        raise ValueError("JOB_COUNT_MUST_BE_POSITIVE")
    ordered = sorted(candidates, key=lambda row: (-float(row.get("cost_score", 0.0)), str(row["strategy_id"])))
    loads = [0.0] * job_count
    output: list[dict[str, Any]] = []
    for row in ordered:
        job_id = min(range(job_count), key=lambda index: (loads[index], index))
        score = float(row.get("cost_score", 0.0))
        loads[job_id] += max(score, 1.0)
        output.append(
            {
                "job_id": job_id,
                "strategy_id": str(row["strategy_id"]),
                "canonical_hash": str(row.get("canonical_hash", "")),
                "cost_score": score,
                "estimated_cost_bucket": (
                    "very_slow" if score >= 6 else "slow" if score >= 3 else "normal" if score >= 1 else "fast"
                ),
            }
        )
    return sorted(output, key=lambda row: (row["job_id"], row["strategy_id"]))

"""Efficient staged robustness scheduling for continuous DEHB snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


class ContinuousRobustnessError(RuntimeError):
    """Raised when staged robustness evidence is incomplete or unsafe."""


@dataclass(frozen=True)
class CandidateLocalReviewRequestV1:
    island_id: str
    lane_id: str
    replicate: int
    robustness_seed: int
    strategy_fingerprint: str
    position_fingerprint: str
    configuration: Mapping[str, Any]
    candidate: Mapping[str, Any]
    schema_version: int = 1


def _champions(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_island: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        if row.get("validation_opened") is not False or row.get("locked_opened") is not False:
            raise ContinuousRobustnessError("CONTINUOUS_ROBUSTNESS_BOUNDARY_OPEN")
        if row.get("full_fidelity") is not True or row.get("train_feasible") is not True:
            continue
        island_id = str(row.get("island_id", ""))
        archive = tuple(float(value) for value in row.get("archive_key", ()))
        if not island_id or not archive:
            raise ContinuousRobustnessError("CONTINUOUS_ROBUSTNESS_CANDIDATE_INVALID")
        current = by_island.get(island_id)
        if current is None or archive < tuple(float(value) for value in current["archive_key"]):
            by_island[island_id] = row
    return [by_island[key] for key in sorted(by_island)]


def plan_candidate_local_reviews(
    rows: Sequence[Mapping[str, Any]],
    *,
    required_replicates: int = 2,
) -> tuple[CandidateLocalReviewRequestV1, ...]:
    """Schedule expensive checks only after behavior appears in independent seeds."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in _champions(rows):
        lane_id = str(row.get("lane_id", ""))
        position = str(row.get("position_fingerprint", ""))
        if not lane_id or len(position) != 64:
            raise ContinuousRobustnessError("CONTINUOUS_ROBUSTNESS_FINGERPRINT_INVALID")
        grouped.setdefault((lane_id, position), []).append(row)
    requests: list[CandidateLocalReviewRequestV1] = []
    for key in sorted(grouped):
        candidates = grouped[key]
        if len({int(row["replicate"]) for row in candidates}) < int(required_replicates):
            continue
        for row in sorted(candidates, key=lambda item: str(item["island_id"])):
            configuration = row.get("config", row.get("configuration"))
            if not isinstance(configuration, Mapping):
                raise ContinuousRobustnessError("CONTINUOUS_ROBUSTNESS_CONFIG_MISSING")
            strategy = str(row.get("strategy_fingerprint", ""))
            if len(strategy) != 64:
                raise ContinuousRobustnessError("CONTINUOUS_ROBUSTNESS_FINGERPRINT_INVALID")
            requests.append(
                CandidateLocalReviewRequestV1(
                    island_id=str(row["island_id"]),
                    lane_id=str(row["lane_id"]),
                    replicate=int(row["replicate"]),
                    robustness_seed=int(row.get("restart_seed", row["replicate"])),
                    strategy_fingerprint=strategy,
                    position_fingerprint=str(row["position_fingerprint"]),
                    configuration=dict(configuration),
                    candidate=row,
                )
            )
    return tuple(requests)


def execute_candidate_local_reviews(
    rows: Sequence[Mapping[str, Any]],
    *,
    store: object,
    reviewer: Callable[[CandidateLocalReviewRequestV1], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Run or reuse each exact candidate-seed review and return enriched champions."""

    enriched: list[dict[str, Any]] = []
    for request in plan_candidate_local_reviews(rows):
        evidence = store.get_robustness_evidence(
            stage="candidate_local",
            strategy_fingerprint=request.strategy_fingerprint,
            robustness_seed=request.robustness_seed,
        )
        if evidence is None:
            evidence = dict(reviewer(request))
            evidence = store.put_robustness_evidence(
                stage="candidate_local",
                strategy_fingerprint=request.strategy_fingerprint,
                position_fingerprint=request.position_fingerprint,
                robustness_seed=request.robustness_seed,
                evidence=evidence,
            )
        if evidence.get("validation_opened") is not False or evidence.get(
            "locked_opened"
        ) is not False:
            raise ContinuousRobustnessError("CONTINUOUS_ROBUSTNESS_BOUNDARY_OPEN")
        enriched.append(
            {
                **dict(request.candidate),
                "restart_seed": request.robustness_seed,
                "robustness_seed": request.robustness_seed,
                "candidate_local_robustness_passed": (
                    evidence.get("candidate_local_passed") is True
                ),
                "robustness": dict(evidence),
            }
        )
    return enriched


__all__ = [
    "CandidateLocalReviewRequestV1",
    "ContinuousRobustnessError",
    "execute_candidate_local_reviews",
    "plan_candidate_local_reviews",
]

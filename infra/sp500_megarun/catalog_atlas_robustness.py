"""Small, deterministic train-only robustness classifier for Atlas results."""

from __future__ import annotations

from typing import Literal, Mapping, Sequence

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel


class AtlasRobustnessResult(FrozenModel):
    status: Literal["green", "amber", "red", "invalid"]
    zero_tolerance_failures: tuple[str, ...]
    red_tests: tuple[str, ...]
    test_rows: tuple[Mapping[str, object], ...]


def classify_atlas_robustness(
    base: Mapping[str, object],
    perturbations: Sequence[Mapping[str, object]],
) -> AtlasRobustnessResult:
    """Classify precomputed perturbations without reopening protected data.

    The perturbation runner is deliberately separate: this classifier only
    consumes train-only receipts and cannot accidentally fetch validation data.
    """

    failures: list[str] = []
    if base.get("validation_opened") is not False:
        failures.append("BASE_VALIDATION_BOUNDARY_OPEN")
    if base.get("locked_opened") is not False:
        failures.append("BASE_LOCKED_BOUNDARY_OPEN")
    if base.get("train_end") != "2010-12-31":
        failures.append("BASE_TRAIN_END_INVALID")
    rows: list[Mapping[str, object]] = []
    red: list[str] = []
    base_week = float(base.get("positive_week_fraction", 0.0))
    base_month = float(base.get("positive_month_fraction", 0.0))
    base_year = float(base.get("joint_positive_above_spy_fraction", 0.0))
    for row in perturbations:
        name = str(row.get("name", "unnamed"))
        if row.get("validation_opened") is not False or row.get("locked_opened") is not False:
            failures.append(f"{name}:PROTECTED_BOUNDARY_OPEN")
        if row.get("train_end") != "2010-12-31":
            failures.append(f"{name}:TRAIN_END_INVALID")
        values = (
            float(row.get("positive_week_fraction", 0.0)),
            float(row.get("positive_month_fraction", 0.0)),
            float(row.get("joint_positive_above_spy_fraction", 0.0)),
        )
        losses = (
            base_week - values[0],
            base_month - values[1],
            base_year - values[2],
        )
        is_red = any(loss > 0.05 for loss in losses)
        if is_red:
            red.append(name)
        rows.append(
            {
                **dict(row),
                "max_objective_loss": max(losses, default=0.0),
                "status": "red" if is_red else "green",
            }
        )
    if failures:
        status: Literal["green", "amber", "red", "invalid"] = "invalid"
    elif len(red) >= 2:
        status = "red"
    elif len(red) == 1:
        status = "amber"
    else:
        status = "green"
    return AtlasRobustnessResult(
        status=status,
        zero_tolerance_failures=tuple(failures),
        red_tests=tuple(red),
        test_rows=tuple(rows),
    )


__all__ = ["AtlasRobustnessResult", "classify_atlas_robustness"]

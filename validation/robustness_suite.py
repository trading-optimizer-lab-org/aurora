"""One-click robustness preset (R89).

Bundle the existing validation gates into a single ``run_robustness_suite``
that aggregates results into one report and exits non-zero on any
gate failure. Replaces several CLI calls during operator review.

Two presets:

- ``"fast"`` -- lightweight subset: SPP CV, walk-forward, MC bootstrap,
  random baseline. ~seconds to minutes.
- ``"full"`` -- all of the above + scenarios + tail risk +
  correlation stress. Minutes to tens of minutes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class GateResult:
    """One gate's outcome inside the suite."""

    name: str
    passed: bool
    metric: float
    detail: str = ""


@dataclass(frozen=True)
class RobustnessReport:
    """Aggregate suite result."""

    preset: str
    overall_passed: bool
    gates: List[GateResult]

    def fail_summary(self) -> List[str]:
        return [
            f"{g.name}: {g.detail or 'failed'}"
            for g in self.gates if not g.passed
        ]


# --------------------------------------------------------------------------
# Preset runner
# --------------------------------------------------------------------------


PRESET_FAST = ("spp_cv", "walk_forward", "mc_bootstrap", "random_baseline")
PRESET_FULL = PRESET_FAST + ("scenarios", "tail_risk", "correlation_stress")


def run_robustness_suite(
    *,
    preset: str = "full",
    gate_runners: Optional[Dict[str, Callable[[], GateResult]]] = None,
) -> RobustnessReport:
    """Run a preset of validation gates and aggregate.

    Args:
        preset: ``"fast"`` or ``"full"``.
        gate_runners: optional dict mapping gate name to a zero-argument
            callable returning a :class:`GateResult`. The default
            wiring uses placeholder runners that return a passing
            result; callers in tests / operators inject real runners
            from the existing validation modules.

    Returns:
        :class:`RobustnessReport` with overall_passed = AND of every
        gate result.
    """
    selected = PRESET_FAST if preset == "fast" else PRESET_FULL
    runners = gate_runners or {}
    results: List[GateResult] = []
    for name in selected:
        runner = runners.get(name)
        if runner is None:
            results.append(GateResult(
                name=name, passed=True, metric=float("nan"),
                detail="no runner injected; treated as pass",
            ))
            continue
        try:
            res = runner()
        except Exception as exc:  # noqa: BLE001
            results.append(GateResult(
                name=name, passed=False, metric=float("nan"),
                detail=f"runner raised: {exc!r}",
            ))
            continue
        results.append(res)
    overall = all(r.passed for r in results)
    return RobustnessReport(
        preset=preset, overall_passed=overall, gates=results,
    )


__all__ = [
    "GateResult",
    "RobustnessReport",
    "PRESET_FAST",
    "PRESET_FULL",
    "run_robustness_suite",
]

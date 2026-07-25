"""Cold and warm setup comparison for equivalent Aurora environments."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EnvironmentSetupSample:
    """One clean-environment installation observation."""

    mode: str
    temperature: str
    repetition: int
    seconds: float
    environment_sha256: str
    installed_packages_sha256: str


@dataclass(frozen=True)
class EnvironmentSetupBenchmark:
    """Decision evidence for the immutable wheelhouse fast path."""

    schema_version: str
    status: str
    dependency_environment_reproducible: bool
    fast_path_selected: bool
    baseline_mode: str
    optimized_mode: str
    baseline_cold_seconds: tuple[float, ...]
    optimized_cold_seconds: tuple[float, ...]
    baseline_warm_seconds: tuple[float, ...]
    optimized_warm_seconds: tuple[float, ...]
    baseline_cold_median_seconds: float
    optimized_cold_median_seconds: float
    baseline_warm_median_seconds: float
    optimized_warm_median_seconds: float
    baseline_warm_p95_seconds: float
    optimized_warm_p95_seconds: float
    cold_speedup: float
    warm_speedup: float
    samples: tuple[EnvironmentSetupSample, ...]
    failure_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible immutable report."""

        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "dependency_environment_reproducible": (
                self.dependency_environment_reproducible
            ),
            "fast_path_selected": self.fast_path_selected,
            "baseline_mode": self.baseline_mode,
            "optimized_mode": self.optimized_mode,
            "baseline_cold_seconds": list(self.baseline_cold_seconds),
            "optimized_cold_seconds": list(self.optimized_cold_seconds),
            "baseline_warm_seconds": list(self.baseline_warm_seconds),
            "optimized_warm_seconds": list(self.optimized_warm_seconds),
            "baseline_cold_median_seconds": (
                self.baseline_cold_median_seconds
            ),
            "optimized_cold_median_seconds": (
                self.optimized_cold_median_seconds
            ),
            "baseline_warm_median_seconds": (
                self.baseline_warm_median_seconds
            ),
            "optimized_warm_median_seconds": (
                self.optimized_warm_median_seconds
            ),
            "baseline_warm_p95_seconds": (
                self.baseline_warm_p95_seconds
            ),
            "optimized_warm_p95_seconds": (
                self.optimized_warm_p95_seconds
            ),
            "cold_speedup": self.cold_speedup,
            "warm_speedup": self.warm_speedup,
            "samples": [
                {
                    "mode": sample.mode,
                    "temperature": sample.temperature,
                    "repetition": sample.repetition,
                    "seconds": sample.seconds,
                    "environment_sha256": sample.environment_sha256,
                    "installed_packages_sha256": (
                        sample.installed_packages_sha256
                    ),
                }
                for sample in self.samples
            ],
            "failure_codes": list(self.failure_codes),
        }


def _finite_seconds(
    samples: Iterable[EnvironmentSetupSample],
    temperature: str,
) -> tuple[float, ...]:
    values = tuple(
        float(sample.seconds)
        for sample in samples
        if sample.temperature == temperature
    )
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("setup samples must contain finite positive seconds")
    return values


def _median(values: tuple[float, ...]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _p95(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = 0.95 * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return float(
        ordered[lower] * (1.0 - fraction)
        + ordered[upper] * fraction
    )


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    value = numerator / denominator
    return float(value) if math.isfinite(value) else 0.0


def evaluate_environment_setup_samples(
    baseline_samples: Iterable[EnvironmentSetupSample],
    optimized_samples: Iterable[EnvironmentSetupSample],
) -> EnvironmentSetupBenchmark:
    """Select the wheelhouse only when equivalent and no slower."""

    baseline = tuple(baseline_samples)
    optimized = tuple(optimized_samples)
    if not baseline or not optimized:
        raise ValueError("both setup alternatives require samples")
    baseline_modes = {sample.mode for sample in baseline}
    optimized_modes = {sample.mode for sample in optimized}
    if len(baseline_modes) != 1 or len(optimized_modes) != 1:
        raise ValueError("each alternative must use exactly one setup mode")

    baseline_cold = _finite_seconds(baseline, "cold")
    optimized_cold = _finite_seconds(optimized, "cold")
    baseline_warm = _finite_seconds(baseline, "warm")
    optimized_warm = _finite_seconds(optimized, "warm")
    failures: list[str] = []
    if not baseline_cold or not optimized_cold:
        failures.append("MISSING_COLD_SAMPLE")
    if not baseline_warm or not optimized_warm:
        failures.append("MISSING_WARM_SAMPLE")

    environment_hashes = {
        sample.environment_sha256 for sample in baseline + optimized
    }
    package_hashes = {
        sample.installed_packages_sha256
        for sample in baseline + optimized
    }
    if len(environment_hashes) != 1:
        failures.append("ENVIRONMENT_HASH_MISMATCH")
    if len(package_hashes) != 1:
        failures.append("INSTALLED_PACKAGES_HASH_MISMATCH")

    baseline_cold_median = _median(baseline_cold)
    optimized_cold_median = _median(optimized_cold)
    baseline_warm_median = _median(baseline_warm)
    optimized_warm_median = _median(optimized_warm)
    if (
        baseline_cold
        and optimized_cold
        and optimized_cold_median > baseline_cold_median
    ):
        failures.append("COLD_SETUP_SLOWER")
    if (
        baseline_warm
        and optimized_warm
        and optimized_warm_median > baseline_warm_median
    ):
        failures.append("WARM_SETUP_SLOWER")

    reproducible = not {
        "ENVIRONMENT_HASH_MISMATCH",
        "INSTALLED_PACKAGES_HASH_MISMATCH",
    }.intersection(failures)
    fast_path_selected = not failures
    return EnvironmentSetupBenchmark(
        schema_version="1",
        status="success" if fast_path_selected else "failed",
        dependency_environment_reproducible=reproducible,
        fast_path_selected=fast_path_selected,
        baseline_mode=next(iter(baseline_modes)),
        optimized_mode=next(iter(optimized_modes)),
        baseline_cold_seconds=baseline_cold,
        optimized_cold_seconds=optimized_cold,
        baseline_warm_seconds=baseline_warm,
        optimized_warm_seconds=optimized_warm,
        baseline_cold_median_seconds=baseline_cold_median,
        optimized_cold_median_seconds=optimized_cold_median,
        baseline_warm_median_seconds=baseline_warm_median,
        optimized_warm_median_seconds=optimized_warm_median,
        baseline_warm_p95_seconds=_p95(baseline_warm),
        optimized_warm_p95_seconds=_p95(optimized_warm),
        cold_speedup=_ratio(
            baseline_cold_median,
            optimized_cold_median,
        ),
        warm_speedup=_ratio(
            baseline_warm_median,
            optimized_warm_median,
        ),
        samples=baseline + optimized,
        failure_codes=tuple(sorted(failures)),
    )

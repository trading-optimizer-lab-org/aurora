"""Representative scientific workloads for GitHub performance validation."""

from aurora.infra.github_performance.workloads.candidate_sweep import (
    WORKLOAD as CANDIDATE_SWEEP_WORKLOAD,
)
from aurora.infra.github_performance.workloads.event_study import (
    WORKLOAD as EVENT_STUDY_WORKLOAD,
)
from aurora.infra.github_performance.workloads.robustness import (
    WORKLOAD as ROBUSTNESS_WORKLOAD,
)

__all__ = (
    "CANDIDATE_SWEEP_WORKLOAD",
    "EVENT_STUDY_WORKLOAD",
    "ROBUSTNESS_WORKLOAD",
)

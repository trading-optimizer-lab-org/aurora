"""ResearchPipelineConfig dataclass for the factory."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ResearchPipelineConfig:
    """Knobs controlling the factory's gating behaviour.

    Defaults match ``aurora/config/research_factory.yaml``. Subclassing
    the dataclass is fine for tests; the factory only relies on attribute
    access.
    """

    is_sharpe_min: float = 0.5
    is_max_drawdown: float = -0.30
    wf_degradation_max: float = 0.50
    wf_instability_max: float = 0.40
    oos_dev_sharpe_min: float = 0.3
    skip_oos_dev_if_wf_fails: bool = True
    archive_path: Path = field(
        default_factory=lambda: __import__(
            "aurora.core.runtime_paths", fromlist=["research_archive_path"]
        ).research_archive_path()
    )
    review_queue_path: Path = field(
        default_factory=lambda: __import__(
            "aurora.core.runtime_paths", fromlist=["review_queue_path"]
        ).review_queue_path()
    )
    parallel_workers: int = 1

    @classmethod
    def from_yaml(cls, path: str) -> "ResearchPipelineConfig":
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Accept Path-typed fields from YAML strings.
        if "archive_path" in data:
            data["archive_path"] = Path(data["archive_path"])
        if "review_queue_path" in data:
            data["review_queue_path"] = Path(data["review_queue_path"])
        return cls(**data)

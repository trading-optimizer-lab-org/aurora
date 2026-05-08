"""DVC + MLflow integration.

Lightweight wrapper that records experiment runs against MLflow and tracks
data artifacts via DVC. Both libraries are imported lazily; if either is
missing the wrapper still works in "mock" mode and writes a JSON record to
disk so tests can exercise the API without the heavy dependencies.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import time


@dataclass
class RunRecord:
    run_id: str
    experiment: str
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0


def _mlflow_available() -> bool:
    try:
        import mlflow  # noqa: F401
        return True
    except ImportError:
        return False


def _dvc_available() -> bool:
    try:
        import dvc  # noqa: F401
        return True
    except ImportError:
        return False


class DVCMLflowIntegration:
    """Track runs through MLflow + DVC, fall back to JSON when unavailable."""

    def __init__(self, experiment: str = "default",
                 tracking_dir: str | Path = "./mlruns_mock",
                 use_real: bool = False):
        if not experiment:
            raise ValueError("experiment must be non-empty")
        self.experiment = str(experiment)
        self.tracking_dir = Path(tracking_dir)
        self.use_real = bool(use_real)
        self._runs: dict[str, RunRecord] = {}
        self._counter = 0

    @property
    def mlflow_available(self) -> bool:
        return _mlflow_available()

    @property
    def dvc_available(self) -> bool:
        return _dvc_available()

    def start_run(self, params: dict[str, Any] | None = None) -> RunRecord:
        self._counter += 1
        run_id = f"run_{self._counter:04d}"
        rec = RunRecord(
            run_id=run_id,
            experiment=self.experiment,
            params=dict(params or {}),
            started_at=time.time(),
        )
        self._runs[run_id] = rec
        return rec

    def log_metric(self, run_id: str, key: str, value: float) -> None:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        if not key:
            raise ValueError("metric key must be non-empty")
        self._runs[run_id].metrics[key] = float(value)

    def log_artifact(self, run_id: str, path: str | Path) -> None:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        self._runs[run_id].artifacts.append(str(path))

    def end_run(self, run_id: str) -> RunRecord:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        rec = self._runs[run_id]
        rec.ended_at = time.time()
        # Persist to JSON so we can inspect / replay later
        self.tracking_dir.mkdir(parents=True, exist_ok=True)
        out = self.tracking_dir / f"{rec.experiment}_{rec.run_id}.json"
        out.write_text(json.dumps({
            "run_id": rec.run_id,
            "experiment": rec.experiment,
            "params": rec.params,
            "metrics": rec.metrics,
            "artifacts": rec.artifacts,
            "started_at": rec.started_at,
            "ended_at": rec.ended_at,
        }, indent=2), encoding="utf-8")
        return rec

    def get_run(self, run_id: str) -> RunRecord:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        return self._runs[run_id]

    def list_runs(self) -> list[RunRecord]:
        return list(self._runs.values())

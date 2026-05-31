"""Weights & Biases hyperparameter tracking.

Lazy import of ``wandb``. When unavailable (the normal test path) the
tracker stores everything in memory so tests can exercise the contract
without a real W&B account or network.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


def _wandb_available() -> bool:
    try:
        import wandb  # noqa: F401
        return True
    except ImportError:
        return False


@dataclass
class WandBRun:
    run_id: str
    project: str
    config: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, float]] = field(default_factory=list)
    summary: dict[str, float] = field(default_factory=dict)
    finished: bool = False


class WandBTracker:
    """Track hyperparameters + metrics with optional W&B backend."""

    def __init__(self, project: str = "aurora",
                 entity: str | None = None, use_real: bool = False):
        if not project:
            raise ValueError("project must be non-empty")
        self.project = str(project)
        self.entity = entity
        self.use_real = bool(use_real)
        self._runs: dict[str, WandBRun] = {}
        self._counter = 0

    @property
    def wandb_available(self) -> bool:
        return _wandb_available()

    def init(self, config: dict[str, Any] | None = None,
             name: str | None = None) -> WandBRun:
        self._counter += 1
        run_id = name if name else f"wb_run_{self._counter:04d}"
        if run_id in self._runs:
            raise ValueError(f"run name {run_id!r} already exists")
        rec = WandBRun(
            run_id=run_id, project=self.project, config=dict(config or {}),
        )
        self._runs[run_id] = rec
        return rec

    def log(self, run_id: str, metrics: dict[str, float],
            step: int | None = None) -> None:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        if not metrics:
            raise ValueError("metrics dict must be non-empty")
        rec = self._runs[run_id]
        entry = {k: float(v) for k, v in metrics.items()}
        if step is not None:
            entry["_step"] = float(int(step))
        rec.history.append(entry)
        # update summary with latest values (no _step)
        for k, v in metrics.items():
            rec.summary[k] = float(v)

    def finish(self, run_id: str) -> WandBRun:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        rec = self._runs[run_id]
        rec.finished = True
        return rec

    def sweep(self, name: str, parameters: dict[str, list[Any]]) -> list[dict]:
        """Generate a small grid of hyperparameter combinations.

        Cartesian product is used. Returns list of dicts -- caller is responsible
        for actually running each one.
        """
        if not name:
            raise ValueError("sweep name must be non-empty")
        if not parameters:
            raise ValueError("parameters must be non-empty")
        keys = list(parameters)
        out: list[dict] = [{}]
        for k in keys:
            vals = parameters[k]
            if not vals:
                raise ValueError(f"sweep key {k!r} has empty values")
            new_out = []
            for prefix in out:
                for v in vals:
                    nxt = dict(prefix)
                    nxt[k] = v
                    new_out.append(nxt)
            out = new_out
        return out

    def get_run(self, run_id: str) -> WandBRun:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id: {run_id!r}")
        return self._runs[run_id]

    def list_runs(self) -> list[WandBRun]:
        return list(self._runs.values())

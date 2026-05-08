"""Experiment tracker for GA + optimization runs.

MLflow-style tracker. Stores experiments as JSON files in a directory:

    <root>/<experiment_id>/
        meta.json           # ExperimentMeta
        generations.jsonl   # one GenerationLog per line (GA only)
        pareto.json         # list[(params, fitness)]
        notes.md            # optional free-form notes

JSON-only encoding (stdlib). Pandas used only for compare_experiments.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

from quantforge.registry.versioning import _exclusive_file_lock


def _default_root() -> str:
    """Resolve the experiments root via runtime_paths (R75).

    Honours $QF_DATA_DIR / $QF_CACHE_DIR; falls back to platformdirs.
    Never lands inside the in-repo `quantforge/data_cache_qf/` ghost
    directory.
    """
    from quantforge.core.runtime_paths import cache_dir
    return str(cache_dir() / "experiments")


_DEFAULT_ROOT = _default_root()


# ---------- dataclasses ----------

@dataclass
class ExperimentMeta:
    experiment_id: str          # short UUID (16-char hex prefix)
    name: str
    optimizer: str              # 'ga' | 'bayes' | 'grid'
    strategy_class: str
    asset: str
    period_start: str
    period_end: str
    config: dict                # GAConfig / BayesConfig as dict
    started_at: str
    finished_at: Optional[str]
    status: str                 # 'running' | 'completed' | 'failed'
    seed: int


@dataclass
class GenerationLog:
    generation: int
    best_fitness: tuple
    median_fitness: tuple
    n_evaluated: int
    pareto_size: int
    timestamp: str


@dataclass
class ExperimentResult:
    meta: ExperimentMeta
    generations: list = field(default_factory=list)        # list[GenerationLog]
    pareto_front: list = field(default_factory=list)       # list[(params, fitness)]
    best_params: Optional[dict] = None
    best_score: Optional[float] = None
    notes: str = ""


# ---------- helpers ----------

def _now_iso() -> str:
    """UTC ISO-8601 timestamp (timezone-aware, second resolution)."""
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


def _new_experiment_id() -> str:
    """``<utc_timestamp>_<8-hex>`` — high-resolution monotonic prefix plus uuid.

    The leading timestamp gives wall-clock-ordered ids and adds entropy
    beyond the uuid prefix alone, so two concurrent calls happening within
    the same microsecond on different machines still differ.
    """
    ts = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"{ts}_{uuid.uuid4().hex[:8]}"


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj: Any) -> None:
    """Atomic JSON write: tmp + fsync + ``os.replace``.

    A direct ``open(path, "w")`` would leave ``path`` zero-length if the
    process is killed between ``open`` and the ``json.dump`` finishing,
    so subsequent ``_read_json`` calls would crash on an empty file. The
    tmp + fsync + replace pattern keeps ``path`` either at its prior
    state or fully written, never partial.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, default=str, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _meta_from_dict(d: dict) -> ExperimentMeta:
    return ExperimentMeta(
        experiment_id=d["experiment_id"],
        name=d["name"],
        optimizer=d["optimizer"],
        strategy_class=d["strategy_class"],
        asset=d["asset"],
        period_start=d["period_start"],
        period_end=d["period_end"],
        config=d.get("config") or {},
        started_at=d["started_at"],
        finished_at=d.get("finished_at"),
        status=d["status"],
        seed=int(d.get("seed", 42)),
    )


def _genlog_from_dict(d: dict) -> GenerationLog:
    return GenerationLog(
        generation=int(d["generation"]),
        best_fitness=tuple(d.get("best_fitness") or ()),
        median_fitness=tuple(d.get("median_fitness") or ()),
        n_evaluated=int(d["n_evaluated"]),
        pareto_size=int(d["pareto_size"]),
        timestamp=d["timestamp"],
    )


# ---------- tracker ----------

class ExperimentTracker:
    """MLflow-style tracker for optimization runs.

    Files per experiment:
        <root>/<experiment_id>/meta.json
        <root>/<experiment_id>/generations.jsonl
        <root>/<experiment_id>/pareto.json
        <root>/<experiment_id>/notes.md  (optional)
    """

    META_FILE = "meta.json"
    GEN_FILE = "generations.jsonl"
    PARETO_FILE = "pareto.json"
    NOTES_FILE = "notes.md"

    def __init__(self, root: str = _DEFAULT_ROOT):
        self.root = os.path.normpath(root)
        os.makedirs(self.root, exist_ok=True)

    # --- paths ---

    def _exp_dir(self, experiment_id: str) -> str:
        return os.path.join(self.root, experiment_id)

    def _meta_path(self, experiment_id: str) -> str:
        return os.path.join(self._exp_dir(experiment_id), self.META_FILE)

    def _gen_path(self, experiment_id: str) -> str:
        return os.path.join(self._exp_dir(experiment_id), self.GEN_FILE)

    def _pareto_path(self, experiment_id: str) -> str:
        return os.path.join(self._exp_dir(experiment_id), self.PARETO_FILE)

    def _notes_path(self, experiment_id: str) -> str:
        return os.path.join(self._exp_dir(experiment_id), self.NOTES_FILE)

    # --- writes ---

    def start_experiment(self, name: str, optimizer: str,
                         strategy_class: str, asset: str,
                         period_start: str, period_end: str,
                         config: dict, seed: int = 42) -> str:
        """Create a new experiment dir + meta.json. Returns experiment_id.

        The directory is created with ``exist_ok=False`` inside a retry loop:
        ``os.path.isdir`` followed by ``os.makedirs(exist_ok=True)`` was a
        TOCTOU race — two parallel callers could both observe "no such dir"
        and then race to create it, with the loser silently overwriting the
        winner's meta.json. ``exist_ok=False`` makes the create itself the
        atomic check, and ``FileExistsError`` triggers a fresh id.
        """
        for _ in range(64):
            experiment_id = _new_experiment_id()
            try:
                os.makedirs(self._exp_dir(experiment_id), exist_ok=False)
                break
            except FileExistsError:
                continue
        else:  # pragma: no cover - defensive: 64 collisions is astronomical
            raise RuntimeError(
                "could not allocate unique experiment_id after 64 attempts"
            )

        meta = ExperimentMeta(
            experiment_id=experiment_id,
            name=name,
            optimizer=optimizer,
            strategy_class=strategy_class,
            asset=asset,
            period_start=period_start,
            period_end=period_end,
            config=dict(config or {}),
            started_at=_now_iso(),
            finished_at=None,
            status="running",
            seed=int(seed),
        )
        _write_json(self._meta_path(experiment_id), asdict(meta))
        return experiment_id

    def log_generation(self, experiment_id: str, gen: int,
                       best_fit: tuple, median_fit: tuple,
                       n_evaluated: int, pareto_size: int) -> None:
        """Append one GenerationLog line to generations.jsonl."""
        # NOTE: the explicit isdir() check below cannot be replaced by
        # "let open() raise FileNotFoundError" -- ``_exclusive_file_lock``
        # below calls ``os.makedirs`` against the parent of ``gen_path`` to
        # place its sibling lock file, which would silently re-create the
        # experiment directory for an unknown id and turn a missing-experiment
        # bug into a phantom log file.
        if not os.path.isdir(self._exp_dir(experiment_id)):
            raise FileNotFoundError(
                f"experiment {experiment_id!r} not found at {self.root}"
            )

        log = GenerationLog(
            generation=int(gen),
            best_fitness=tuple(best_fit) if best_fit is not None else (),
            median_fitness=tuple(median_fit) if median_fit is not None else (),
            n_evaluated=int(n_evaluated),
            pareto_size=int(pareto_size),
            timestamp=_now_iso(),
        )
        line = json.dumps(asdict(log), default=str)
        gen_path = self._gen_path(experiment_id)
        # Serialize concurrent appends: without a lock two writers can
        # interleave bytes mid-line and corrupt the JSON-lines stream.
        with _exclusive_file_lock(gen_path):
            with open(gen_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def finish_experiment(self, experiment_id: str,
                          pareto_front: Optional[list] = None,
                          best_params: Optional[dict] = None,
                          best_score: Optional[float] = None,
                          notes: str = "",
                          status: str = "completed") -> None:
        """Update meta.json status + write pareto/best_params/notes.

        Wrapped in :func:`_exclusive_file_lock` against ``meta.json`` so
        that two callers racing to finish the same experiment cannot
        interleave their read-modify-write cycles and lose one writer's
        ``best_params`` / ``best_score`` updates.
        """
        if not os.path.isdir(self._exp_dir(experiment_id)):
            raise FileNotFoundError(f"experiment {experiment_id!r} not found at {self.root}")

        meta_path = self._meta_path(experiment_id)
        with _exclusive_file_lock(meta_path):
            meta_d = _read_json(meta_path)
            meta_d["finished_at"] = _now_iso()
            meta_d["status"] = status
            if best_params is not None:
                meta_d["best_params"] = dict(best_params)
            if best_score is not None:
                meta_d["best_score"] = float(best_score)
            _write_json(meta_path, meta_d)

            # Pareto: list of (params, fitness) tuples → JSON-friendly
            pf_payload: list = []
            if pareto_front:
                for item in pareto_front:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        params, fitness = item
                        pf_payload.append({
                            "params": dict(params) if isinstance(params, dict) else params,
                            "fitness": list(fitness) if isinstance(fitness, (list, tuple)) else fitness,
                        })
                    else:
                        pf_payload.append(item)
            _write_json(self._pareto_path(experiment_id), pf_payload)

            if notes:
                with open(self._notes_path(experiment_id), "w", encoding="utf-8") as f:
                    f.write(notes)

    # --- reads ---

    def load_experiment(self, experiment_id: str) -> ExperimentResult:
        if not os.path.isdir(self._exp_dir(experiment_id)):
            raise FileNotFoundError(f"experiment {experiment_id!r} not found at {self.root}")

        meta_d = _read_json(self._meta_path(experiment_id))
        # Strip extra keys not in dataclass before constructing
        best_params = meta_d.get("best_params")
        best_score = meta_d.get("best_score")
        meta = _meta_from_dict(meta_d)

        # Generations
        gens: list = []
        gen_path = self._gen_path(experiment_id)
        if os.path.isfile(gen_path):
            with open(gen_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Skip corrupt JSONL lines (truncated writes, partial
                    # appends from a killed process, manual edits) instead
                    # of crashing the entire experiment load. Both
                    # ``json.JSONDecodeError`` (malformed JSON) and
                    # ``KeyError`` (missing required ``_genlog_from_dict``
                    # field) recover by dropping just the bad line.
                    try:
                        gens.append(_genlog_from_dict(json.loads(line)))
                    except (json.JSONDecodeError, KeyError):
                        continue

        # Pareto
        pareto: list = []
        pareto_path = self._pareto_path(experiment_id)
        if os.path.isfile(pareto_path):
            raw = _read_json(pareto_path) or []
            for entry in raw:
                if isinstance(entry, dict) and "params" in entry and "fitness" in entry:
                    fit = entry["fitness"]
                    fit_t = tuple(fit) if isinstance(fit, list) else fit
                    pareto.append((entry["params"], fit_t))
                else:
                    pareto.append(entry)

        # Notes
        notes = ""
        notes_path = self._notes_path(experiment_id)
        if os.path.isfile(notes_path):
            with open(notes_path, "r", encoding="utf-8") as f:
                notes = f.read()

        return ExperimentResult(
            meta=meta,
            generations=gens,
            pareto_front=pareto,
            best_params=best_params,
            best_score=float(best_score) if best_score is not None else None,
            notes=notes,
        )

    def list_experiments(self, optimizer: Optional[str] = None,
                         strategy_class: Optional[str] = None,
                         status: Optional[str] = None) -> list:
        """Return list of ExperimentMeta filtered by criteria, newest first."""
        out: list = []
        if not os.path.isdir(self.root):
            return out
        for entry in os.listdir(self.root):
            d = os.path.join(self.root, entry)
            if not os.path.isdir(d):
                continue
            mp = os.path.join(d, self.META_FILE)
            if not os.path.isfile(mp):
                continue
            try:
                meta = _meta_from_dict(_read_json(mp))
            except Exception:
                continue
            if optimizer is not None and meta.optimizer != optimizer:
                continue
            if strategy_class is not None and meta.strategy_class != strategy_class:
                continue
            if status is not None and meta.status != status:
                continue
            out.append(meta)
        out.sort(key=lambda m: m.started_at, reverse=True)
        return out

    def compare_experiments(self, ids: list) -> pd.DataFrame:
        """Side-by-side comparison: one row per experiment."""
        records: list[dict] = []
        for eid in ids:
            try:
                r = self.load_experiment(eid)
            except FileNotFoundError:
                continue
            m = r.meta
            runtime = None
            if m.finished_at:
                try:
                    t0 = _dt.datetime.fromisoformat(m.started_at)
                    t1 = _dt.datetime.fromisoformat(m.finished_at)
                    runtime = (t1 - t0).total_seconds()
                except Exception:
                    runtime = None
            best_fit_last = None
            if r.generations:
                best_fit_last = r.generations[-1].best_fitness
            records.append({
                "experiment_id": m.experiment_id,
                "name": m.name,
                "optimizer": m.optimizer,
                "strategy_class": m.strategy_class,
                "asset": m.asset,
                "status": m.status,
                "seed": m.seed,
                "started_at": m.started_at,
                "finished_at": m.finished_at,
                "runtime_s": runtime,
                "best_score": r.best_score,
                "best_fitness_last_gen": best_fit_last,
                "pareto_size": len(r.pareto_front),
                "n_generations": len(r.generations),
                "config": m.config,
            })
        return pd.DataFrame.from_records(records)

    def best_experiment(self, optimizer: Optional[str] = None,
                        strategy_class: Optional[str] = None,
                        metric: str = "best_score") -> Optional[ExperimentResult]:
        """Return ExperimentResult with the highest value of `metric`.

        Supported metrics:
            - "best_score": meta.best_score
            - "pareto_size": len(pareto_front)
            - "n_generations": number of GenerationLog lines
        """
        metas = self.list_experiments(optimizer=optimizer, strategy_class=strategy_class,
                                      status="completed")
        if not metas:
            return None

        best_val = None
        best_id = None
        for m in metas:
            r = self.load_experiment(m.experiment_id)
            if metric == "best_score":
                v = r.best_score
            elif metric == "pareto_size":
                v = len(r.pareto_front)
            elif metric == "n_generations":
                v = len(r.generations)
            else:
                raise ValueError(f"unsupported metric: {metric!r}")
            if v is None:
                continue
            if best_val is None or v > best_val:
                best_val = v
                best_id = m.experiment_id

        if best_id is None:
            return None
        return self.load_experiment(best_id)

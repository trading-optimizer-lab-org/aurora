"""Reproducibility witness object (R146).

Every run (backtest, validation, GA, factory submit) emits a Witness
that captures the full reproducibility envelope: seed, git_hash,
policy_hash, snapshot_ids referenced, input_hash, output_hash,
compute_seconds, dependency_versions. Replaying a witness with the
same code repository rebuilds byte-identical output (R148 guards the
contract).

The witness is intentionally narrower than the existing
`DataSnapshot` provenance: a snapshot describes data, a witness
describes a *run*. A single run can reference many snapshots; a
single snapshot can be referenced by many witnesses.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Witness:
    """Frozen reproducibility envelope for a single run."""

    run_id: str
    kind: str  # "backtest" | "validation" | "ga" | "factory_submit" | ...
    started_at: str
    finished_at: str
    compute_seconds: float
    seed: Optional[int]
    git_hash: Optional[str]
    forge_version: Optional[str]
    policy_hash: Optional[str]
    snapshot_ids: List[str]
    input_hash: Optional[str]
    output_hash: Optional[str]
    python_version: str
    platform: str
    dependency_versions: Dict[str, str] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def witness_hash(self) -> str:
        """Stable SHA-256 over the canonical JSON form."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------


def _git_hash() -> Optional[str]:
    try:
        from aurora.core.data_layer import _get_git_hash
        return _get_git_hash()
    except Exception:
        return None


def _forge_version() -> Optional[str]:
    try:
        import importlib.metadata as md
        return md.version("aurora")
    except Exception:
        try:
            import aurora as qf
            return getattr(qf, "__version__", None)
        except Exception:
            return None


def _hash_obj(obj: Any) -> str:
    """SHA-256 over canonical-JSON of an arbitrary object."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _capture_dependency_versions(
    packages: Optional[List[str]] = None,
) -> Dict[str, str]:
    import importlib.metadata as md
    out: Dict[str, str] = {}
    targets = packages or [
        "numpy",
        "pandas",
        "scipy",
        "matplotlib",
        "pyarrow",
        "pydantic",
        "platformdirs",
        "numba",
    ]
    for pkg in targets:
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            continue
    return out


class WitnessRecorder:
    """Context manager that captures a Witness around a run.

    Usage::

        with WitnessRecorder(kind="backtest", seed=42,
                             input_obj={"asset": "SPY"}) as rec:
            result = run_backtest(...)
            rec.set_output(result.metrics.to_dict())

        witness = rec.witness   # frozen Witness instance
        witness.witness_hash()  # stable digest
    """

    def __init__(
        self,
        *,
        kind: str,
        seed: Optional[int] = None,
        policy_hash: Optional[str] = None,
        snapshot_ids: Optional[List[str]] = None,
        input_obj: Any = None,
        run_id: Optional[str] = None,
        extras: Optional[Dict[str, Any]] = None,
    ) -> None:
        import uuid
        self._kind = kind
        self._seed = seed
        self._policy_hash = policy_hash
        self._snapshot_ids = list(snapshot_ids or [])
        self._input_hash = _hash_obj(input_obj) if input_obj is not None else None
        self._output_hash: Optional[str] = None
        self._extras = dict(extras or {})
        self._run_id = run_id or uuid.uuid4().hex
        self._t0: Optional[float] = None
        self._started_at: Optional[str] = None
        self._finished_at: Optional[str] = None
        self.witness: Optional[Witness] = None

    def __enter__(self) -> "WitnessRecorder":
        self._t0 = time.monotonic()
        self._started_at = datetime.utcnow().isoformat()
        return self

    def set_output(self, output_obj: Any) -> None:
        """Record the run's output for hashing."""
        self._output_hash = _hash_obj(output_obj)

    def __exit__(self, *exc) -> None:
        self._finished_at = datetime.utcnow().isoformat()
        elapsed = (time.monotonic() - (self._t0 or time.monotonic()))
        self.witness = Witness(
            run_id=self._run_id,
            kind=self._kind,
            started_at=self._started_at or "",
            finished_at=self._finished_at,
            compute_seconds=round(elapsed, 6),
            seed=self._seed,
            git_hash=_git_hash(),
            forge_version=_forge_version(),
            policy_hash=self._policy_hash,
            snapshot_ids=list(self._snapshot_ids),
            input_hash=self._input_hash,
            output_hash=self._output_hash,
            python_version=sys.version.split()[0],
            platform=platform.platform(),
            dependency_versions=_capture_dependency_versions(),
            extras=self._extras,
        )


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def write_witness(witness: Witness, path: Path | str) -> None:
    """Append a witness to a JSONL file. Used by audit trails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(witness.to_json() + "\n")


def read_witnesses(path: Path | str) -> List[Witness]:
    path = Path(path)
    if not path.exists():
        return []
    out: List[Witness] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                out.append(Witness(**d))
            except TypeError:
                # Ignore rows from older / newer schema versions.
                continue
    return out


__all__ = [
    "Witness",
    "WitnessRecorder",
    "write_witness",
    "read_witnesses",
]

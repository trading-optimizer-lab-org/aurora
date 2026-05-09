"""Append-only research ledger (Phase 2 / Candidate B).

Records every user-visible research choice during a run -- universe,
features, parameters, filters, cost model, validation windows, seed,
data contract, strategy hash, rejection reasons and manual overrides.

The ledger is JSONL-backed under
``runtime_paths.base_data_dir() / "research_ledger.jsonl"`` and is
strictly append-only. Two writes for the same ``run_id`` produce two
records: retrying or replaying a run never overwrites prior history.

Design notes:

* ``ResearchChoice`` is a frozen dataclass so existing entries are
  immutable in-process.
* ``record()`` opens the file in append mode for every write so a
  crash mid-batch leaves a partial line at most -- never a truncated
  history.
* ``read()`` is tolerant: it skips blank lines and lines that fail to
  parse, which keeps replay safe even if the file is concurrently
  being appended to.
* Manual overrides MUST carry both ``author`` and ``reason``. The
  ledger raises ``ValueError`` rather than silently accepting an
  anonymous override.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_KINDS = frozenset({
    "universe",
    "features",
    "parameters",
    "filters",
    "cost_model",
    "validation_window",
    "seed",
    "data_contract",
    "strategy_hash",
    "rejection_reason",
    "manual_override",
})


@dataclass(frozen=True)
class ResearchChoice:
    """One user-visible research decision recorded against a run."""

    run_id: str
    timestamp_iso: str
    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)
    author: Optional[str] = None
    reason: Optional[str] = None


def _default_ledger_path() -> Path:
    # Imported lazily so tests that monkeypatch QF_DATA_DIR pick up the
    # override even after this module has been imported.
    from quantforge.core.runtime_paths import base_data_dir

    return base_data_dir() / "research_ledger.jsonl"


class ResearchLedger:
    """Append-only JSONL-backed research ledger.

    Parameters
    ----------
    path:
        Optional explicit ledger path. When omitted, defaults to
        ``runtime_paths.base_data_dir() / "research_ledger.jsonl"``.
        Tests should pass an explicit ``tmp_path`` to avoid touching
        the real runtime data directory.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path: Path = Path(path) if path is not None else _default_ledger_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def record(self, choice: ResearchChoice) -> None:
        """Append a single ``ResearchChoice`` to the ledger.

        Validates the kind and -- for manual overrides -- requires
        both ``author`` and ``reason``. Raises ``ValueError`` on any
        violation; never partially writes.
        """
        if choice.kind not in VALID_KINDS:
            raise ValueError(
                f"Unknown research-choice kind: {choice.kind!r}. "
                f"Valid kinds: {sorted(VALID_KINDS)}"
            )
        if choice.kind == "manual_override":
            if not choice.author or not choice.reason:
                raise ValueError(
                    "manual_override requires both author and reason"
                )
        if not choice.run_id:
            raise ValueError("ResearchChoice.run_id must be non-empty")
        if not choice.timestamp_iso:
            raise ValueError("ResearchChoice.timestamp_iso must be non-empty")

        row = asdict(choice)
        line = json.dumps(row, sort_keys=True, default=str) + "\n"
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def read(self, run_id: Optional[str] = None) -> List[ResearchChoice]:
        """Return all recorded choices, optionally filtered by run.

        Tolerant of partial / concurrent writes: blank lines and
        unparseable rows are skipped rather than raising.
        """
        if not self._path.exists():
            return []
        out: List[ResearchChoice] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if run_id is not None and row.get("run_id") != run_id:
                    continue
                out.append(
                    ResearchChoice(
                        run_id=str(row.get("run_id", "")),
                        timestamp_iso=str(row.get("timestamp_iso", "")),
                        kind=str(row.get("kind", "")),
                        payload=dict(row.get("payload") or {}),
                        author=row.get("author"),
                        reason=row.get("reason"),
                    )
                )
        return out


__all__ = [
    "ResearchChoice",
    "ResearchLedger",
    "VALID_KINDS",
]

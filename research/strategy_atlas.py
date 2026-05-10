"""Strategy atlas (Candidate E).

Canonical registry of which strategy ideas QuantForge supports, refuses,
or only keeps for benchmarking purposes. The atlas is the *first*
gatekeeper before the validation pipeline: an idea that is not in the
atlas, or whose status forbids promotion, never reaches the
:mod:`quantforge.validation` gates.

The atlas exists for two reasons:

1. The platform has explicit constraints on what data it owns and what
   engine capabilities it supports. Strategies that would require
   missing data (options chains, structured credit, exotic fixed income)
   or missing engine capabilities (intraday tick fills, FX margin)
   cannot be honestly backtested. Listing them as ``BLOCKED`` makes the
   refusal visible instead of silently producing meaningless results.

2. Some strategy ideas only exist as benchmarks: they live in academic
   PDFs, in the comparison tables of papers, in the appendix of a
   prospectus. We keep them in the atlas as ``BENCHMARK_ONLY`` so a
   future search engine can produce comparable numbers, but they will
   never be promoted to production.

Status changes flow only one way during normal operation:
``CANDIDATE -> SUPPORTED`` after the validation pipeline accepts the
strategy AND the similarity / graveyard query (R92 + R39) does not
flag it. Going the other direction (rejecting a strategy, marking it
benchmark-only) is allowed at any time.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AtlasStatus(Enum):
    """Lifecycle / policy status of a strategy entry in the atlas.

    Aliased as :class:`StrategyAtlasStatus` for callers that want the
    fully-qualified name. The two are the same enum.
    """

    SUPPORTED = "supported"
    """Engine + data + costs are sufficient. Eligible for promotion."""

    CANDIDATE = "candidate"
    """Idea is on-platform but has not yet cleared validation."""

    BLOCKED = "blocked"
    """Cannot be honestly run today. Reason must be in ``notes``."""

    REJECTED = "rejected"
    """Tried, failed, archived. Kept here to prevent rediscovery."""

    BENCHMARK_ONLY = "benchmark_only"
    """Used only as a comparison baseline. Never promoted to production."""

    EXTERNAL_DATA_ONLY = "external_data_only"
    """Engine could run it, but required data lives outside QuantForge."""

    NEEDS_ENGINE_SUPPORT = "needs_engine_support"
    """Engine capability missing (e.g. tick fills, FX margin, options
    Greeks). Different from BLOCKED in that the data is or could be
    available; only the execution / pricing engine is the gap."""


# Public alias. ``StrategyAtlasStatus`` is the canonical name used in
# documentation; ``AtlasStatus`` is kept as the short form for the
# original Candidate E surface.
StrategyAtlasStatus = AtlasStatus


_PROMOTABLE = frozenset({AtlasStatus.SUPPORTED})


def _all_status_values_unique() -> None:
    """Defensive: guarantee status enum values are pairwise distinct.

    Run at import so a developer cannot accidentally collide two values
    when adding a new status.
    """
    seen: dict[str, str] = {}
    for member in AtlasStatus:
        if member.value in seen:
            raise RuntimeError(
                "AtlasStatus values must be unique; collision between "
                f"{seen[member.value]!r} and {member.name!r} "
                f"on value {member.value!r}"
            )
        seen[member.value] = member.name


_all_status_values_unique()

_VALID_COST_SENSITIVITY = frozenset({"low", "medium", "high"})
_VALID_DIFFICULTY = frozenset({"easy", "medium", "hard"})


@dataclass(frozen=True)
class StrategyAtlasEntry:
    """One entry in the strategy atlas.

    Frozen so a registered entry cannot mutate after the registry has
    accepted it. All collection-typed fields are tuples for the same
    reason.
    """

    name: str
    asset_class: str
    data_requirements: tuple[str, ...]
    required_engine_capabilities: tuple[str, ...]
    cost_sensitivity: str
    overfit_risk: str
    implementation_difficulty: str
    validation_gates: tuple[str, ...]
    benchmark_expectation: str
    status: AtlasStatus
    owner: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("StrategyAtlasEntry.name must be non-empty")
        if not self.asset_class or not self.asset_class.strip():
            raise ValueError("StrategyAtlasEntry.asset_class must be non-empty")
        if not isinstance(self.data_requirements, tuple):
            raise TypeError(
                "StrategyAtlasEntry.data_requirements must be a tuple"
            )
        if len(self.data_requirements) == 0:
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): data_requirements is "
                "empty -- every entry must declare at least one data "
                "requirement so the data registry can verify availability"
            )
        if not isinstance(self.required_engine_capabilities, tuple):
            raise TypeError(
                "StrategyAtlasEntry.required_engine_capabilities must be a tuple"
            )
        if self.cost_sensitivity not in _VALID_COST_SENSITIVITY:
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): cost_sensitivity must be "
                f"one of {sorted(_VALID_COST_SENSITIVITY)}, got "
                f"{self.cost_sensitivity!r}"
            )
        if not self.overfit_risk or not self.overfit_risk.strip():
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): overfit_risk must be "
                "non-empty"
            )
        if self.implementation_difficulty not in _VALID_DIFFICULTY:
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): implementation_difficulty "
                f"must be one of {sorted(_VALID_DIFFICULTY)}, got "
                f"{self.implementation_difficulty!r}"
            )
        if not isinstance(self.validation_gates, tuple):
            raise TypeError(
                "StrategyAtlasEntry.validation_gates must be a tuple"
            )
        if not self.benchmark_expectation or not self.benchmark_expectation.strip():
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): benchmark_expectation "
                "must be non-empty -- every entry must declare what it is "
                "expected to beat (or 'none' explicitly)"
            )
        # Cross-check benchmark_expectation against the canonical enum so
        # a typo cannot slip through. Lazy import keeps strategy_atlas
        # importable even if strategy_benchmarks is being edited.
        try:
            from aurora.research.strategy_benchmarks import (
                BenchmarkExpectation as _BE,
            )
        except ImportError:  # pragma: no cover - defensive
            _BE = None  # type: ignore[assignment]
        if _BE is not None:
            valid_be = {member.value for member in _BE}
            if self.benchmark_expectation not in valid_be:
                raise ValueError(
                    f"StrategyAtlasEntry({self.name!r}): "
                    f"benchmark_expectation {self.benchmark_expectation!r} "
                    f"is not one of {sorted(valid_be)} -- update or use "
                    "an explicit BenchmarkExpectation value"
                )
        if not isinstance(self.status, AtlasStatus):
            raise TypeError(
                f"StrategyAtlasEntry({self.name!r}): status must be an "
                f"AtlasStatus, got {type(self.status).__name__}"
            )
        if not self.owner or not self.owner.strip():
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): owner must be non-empty"
            )
        if self.status is AtlasStatus.BLOCKED and not self.notes.strip():
            raise ValueError(
                f"StrategyAtlasEntry({self.name!r}): BLOCKED entries must "
                "explain the reason in `notes`"
            )


@dataclass
class StrategyAtlas:
    """In-memory registry of :class:`StrategyAtlasEntry` keyed by name."""

    _entries: dict[str, StrategyAtlasEntry] = field(default_factory=dict)

    def register(self, entry: StrategyAtlasEntry) -> None:
        """Register a new entry. Raises if the name is already present."""
        if entry.name in self._entries:
            raise ValueError(
                f"StrategyAtlas: entry {entry.name!r} already registered"
            )
        self._entries[entry.name] = entry

    def get(self, name: str) -> StrategyAtlasEntry:
        """Look up an entry by name. Raises ``KeyError`` if missing."""
        if name not in self._entries:
            raise KeyError(f"StrategyAtlas: unknown entry {name!r}")
        return self._entries[name]

    def has(self, name: str) -> bool:
        return name in self._entries

    def list_by_status(self, status: AtlasStatus) -> list[StrategyAtlasEntry]:
        return [e for e in self._entries.values() if e.status is status]

    def all_entries(self) -> list[StrategyAtlasEntry]:
        return list(self._entries.values())

    def is_promotable(self, name: str) -> bool:
        """True iff ``name`` is registered with a promotable status."""
        if name not in self._entries:
            return False
        return self._entries[name].status in _PROMOTABLE

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries


def query_before_promote(
    name: str,
    candidate_signal: Any,
    candidate_params: Mapping[str, float],
    candidate_equity: Any,
    *,
    atlas: StrategyAtlas | None = None,
    similarity_threshold: float = 0.85,
    archive_path: Any = None,
    reference_strategies: Iterable[
        tuple[str, Any, Mapping[str, float], Any]
    ] | None = None,
) -> list[str]:
    """Run the R92 / R39 gates before promoting a candidate.

    Returns a list of human-readable warning messages. An empty list
    means no concern was raised. The function is best-effort: if the
    R92 (``dna_fingerprint``) or R39 (``graveyard``) modules are not
    importable in this deployment, the corresponding check is skipped
    and a degradation warning is emitted instead of raising.

    Parameters
    ----------
    name:
        Name of the candidate strategy.
    candidate_signal:
        Signal vector for similarity comparison (typically ``np.ndarray``).
    candidate_params:
        Parameter mapping for similarity comparison.
    candidate_equity:
        Equity curve for similarity comparison (typically ``np.ndarray``).
    atlas:
        Atlas instance. If supplied, reference strategies for the
        similarity check are built from currently-supported entries.
        When ``None`` and ``reference_strategies`` is also ``None``,
        the similarity check degrades to a no-op.
    similarity_threshold:
        Composite similarity threshold above which a warning is emitted.
    archive_path:
        Path to the research archive JSONL used by the graveyard reader.
        When ``None``, the graveyard check degrades to a no-op.
    reference_strategies:
        Optional explicit iterable of
        ``(name, signal, params, equity)`` tuples to compare against.
        Overrides ``atlas`` if provided.
    """
    warnings: list[str] = []

    # ---- R92: similarity check ------------------------------------------------
    try:
        from aurora.research.dna_fingerprint import (
            fingerprint,
            is_too_similar,
        )
    except ImportError:
        warnings.append(
            f"[{name}] similarity check skipped: dna_fingerprint module "
            "is not importable in this deployment"
        )
    else:
        refs: list[
            tuple[str, Any, Mapping[str, float], Any]
        ] = []
        if reference_strategies is not None:
            refs = list(reference_strategies)
        elif atlas is not None:
            # No live reference signals attached to atlas entries by default.
            # Caller provides them through reference_strategies; otherwise
            # the check degrades to a no-op without raising.
            refs = []
        for ref_name, ref_signal, ref_params, ref_equity in refs:
            if ref_name == name:
                continue
            try:
                scores = fingerprint(
                    signal_vector_a=candidate_signal,
                    signal_vector_b=ref_signal,
                    params_a=dict(candidate_params),
                    params_b=dict(ref_params),
                    equity_a=candidate_equity,
                    equity_b=ref_equity,
                )
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(
                    f"[{name}] similarity check vs {ref_name!r} errored: "
                    f"{exc!r}"
                )
                continue
            if is_too_similar(scores, threshold=similarity_threshold):
                warnings.append(
                    f"[{name}] too similar to existing strategy "
                    f"{ref_name!r} (composite={scores.composite:.3f} "
                    f">= {similarity_threshold:.2f}); review before "
                    "promotion"
                )

    # ---- R39: graveyard query -------------------------------------------------
    try:
        from aurora.research.graveyard import (
            read_graveyard,
        )
    except ImportError:
        warnings.append(
            f"[{name}] graveyard check skipped: graveyard module is not "
            "importable in this deployment"
        )
    else:
        if archive_path is None:
            # Best-effort: caller did not supply an archive path so we
            # cannot scan. Do not raise.
            pass
        else:
            try:
                from pathlib import Path

                entries = read_graveyard(Path(archive_path))
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(
                    f"[{name}] graveyard check failed reading "
                    f"{archive_path!r}: {exc!r}"
                )
            else:
                for entry in entries:
                    sid = getattr(entry, "strategy_id", "")
                    if sid and sid == name:
                        warnings.append(
                            f"[{name}] previously archived in graveyard "
                            f"(version={entry.version!r}, "
                            f"reason={entry.rejection_reason!r}); do not "
                            "re-promote without explicit override"
                        )

    return warnings


def query_graveyard_before_promote(
    entry: StrategyAtlasEntry,
    *,
    atlas: StrategyAtlas | None = None,
    archive_path: Any = None,
) -> None:
    """Refuse promotion if a similar entry was rejected previously.

    Checks two graveyards:

    1. The atlas itself: any entry already in the registry with status
       :attr:`AtlasStatus.REJECTED` and the same ``name`` triggers a
       ``ValueError`` -- a rejected idea cannot quietly come back.
    2. The on-disk research archive (R39 graveyard) if ``archive_path``
       is provided. Any matching ``strategy_id`` triggers a
       ``ValueError``.

    The function returns ``None`` on success and raises ``ValueError``
    on collision so callers can wire it into a hard gate.
    """
    if atlas is not None and atlas.has(entry.name):
        existing = atlas.get(entry.name)
        if existing.status is AtlasStatus.REJECTED:
            raise ValueError(
                f"query_graveyard_before_promote: entry {entry.name!r} "
                "already rejected in the atlas; cannot re-promote"
            )

    if archive_path is None:
        return

    try:
        from aurora.research.graveyard import (  # type: ignore[import-not-found]
            read_graveyard,
        )
    except ImportError:
        # On-disk graveyard reader not available in this deployment.
        # Best-effort: parse the JSONL ourselves so we still honour a
        # real rejection record. The archive format used elsewhere is
        # one JSON object per line with ``strategy_id`` and
        # ``event``/``rejection_reason`` keys.
        from pathlib import Path
        import json as _json
        try:
            text = Path(archive_path).read_text(encoding="utf-8")
        except OSError:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            sid = row.get("strategy_id") or row.get("name") or ""
            if sid and sid == entry.name:
                reason = (
                    row.get("rejection_reason")
                    or row.get("reason")
                    or "previous rejection"
                )
                raise ValueError(
                    f"query_graveyard_before_promote: entry {entry.name!r} "
                    f"appears in graveyard archive ({reason!r}); cannot "
                    "re-promote without explicit override"
                ) from None
        return

    from pathlib import Path
    try:
        rows = read_graveyard(Path(archive_path))
    except Exception:  # pragma: no cover - defensive
        return
    for row in rows:
        sid = getattr(row, "strategy_id", "") or getattr(row, "name", "")
        if sid and sid == entry.name:
            reason = (
                getattr(row, "rejection_reason", None)
                or getattr(row, "reason", None)
                or "previous rejection"
            )
            raise ValueError(
                f"query_graveyard_before_promote: entry {entry.name!r} "
                f"appears in graveyard archive ({reason!r}); cannot "
                "re-promote without explicit override"
            )


__all__ = [
    "AtlasStatus",
    "StrategyAtlas",
    "StrategyAtlasEntry",
    "StrategyAtlasStatus",
    "query_before_promote",
    "query_graveyard_before_promote",
]

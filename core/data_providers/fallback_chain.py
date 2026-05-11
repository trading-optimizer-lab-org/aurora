"""Fallback chain orchestration for the R155 free bulk programme.

Aurora never silently merges OHLCV from two different providers. When a
primary provider fails (auth gate, contract violation, empty payload),
the fallback chain picks the next configured provider and records the
substitution explicitly in a :class:`FallbackReport`. The caller decides
whether to accept the substitution based on the report's ``warnings``
and ``rejected_sources`` lists.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from ._free_bulk_common import FreeBulkContractViolation, FreeBulkLineage

_log = logging.getLogger(__name__)


__all__ = [
    "FallbackAttempt",
    "FallbackReport",
    "execute_fallback_chain",
    "ProviderMismatch",
]


# ---------------------------------------------------------------------------
# Records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FallbackAttempt:
    """One attempt against a provider in the chain.

    Attributes:
        provider_name: which provider was tried.
        outcome: ``"success"`` / ``"empty"`` / ``"contract_violation"`` /
            ``"auth_required"`` / ``"error"`` / ``"mismatch"``.
        message: free-form detail (error text or short note).
        rows: number of rows returned (0 on failure).
    """

    provider_name: str
    outcome: str
    message: str
    rows: int = 0


@dataclass(frozen=True)
class FallbackReport:
    """Audit record produced by :func:`execute_fallback_chain`.

    Records the selected source, every rejected source, missing symbols
    (when running multi-symbol sweeps), substitutions, and warnings. The
    caller MUST inspect this object before treating the result as
    authoritative.
    """

    selected_source: Optional[str]
    selected_lineage: Optional[FreeBulkLineage]
    selected_df: Optional[pd.DataFrame]
    attempts: Tuple[FallbackAttempt, ...]
    rejected_sources: Tuple[str, ...]
    missing_symbols: Tuple[str, ...] = field(default_factory=tuple)
    substitutions: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)


class ProviderMismatch(ValueError):
    """Raised when two providers disagree on a symbol's OHLCV.

    Carries both candidate frames so the caller can inspect / record
    the disagreement. The fallback chain produces this when running in
    *strict* mode and observing different content hashes for the same
    timestamp window.
    """

    def __init__(self, symbol: str, candidates: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(
            f"providers disagree on {symbol!r}: "
            f"{[c['provider_name'] for c in candidates]}"
        )
        self.symbol = symbol
        self.candidates = list(candidates)


# ---------------------------------------------------------------------------
# Chain executor.
# ---------------------------------------------------------------------------


# Fetcher signature: takes the symbol, returns ``(df, lineage)``.
Fetcher = Callable[[str], Tuple[pd.DataFrame, FreeBulkLineage]]


def execute_fallback_chain(
    symbol: str,
    chain: Sequence[Tuple[str, Fetcher]],
    *,
    strict_compare: bool = False,
) -> FallbackReport:
    """Run ``chain`` until a fetcher returns a usable result.

    Each chain entry is ``(provider_name, fetcher)`` where ``fetcher`` is
    a zero-arg callable bound to the symbol. Failures are recorded as
    :class:`FallbackAttempt` rows and the next provider is tried. The
    function never silently merges results: only the first successful
    fetcher produces ``selected_df``, and every other provider that
    produced data is recorded in ``rejected_sources`` with a substitution
    note.

    Args:
        symbol: the symbol being fetched (recorded into ``missing_symbols``
            when no provider succeeds).
        chain: ordered chain of ``(provider_name, fetcher)`` tuples. The
            first entry is the primary; subsequent entries are
            fallbacks.
        strict_compare: when True, run *all* providers in the chain,
            compare their content hashes, and raise
            :class:`ProviderMismatch` if any two providers return
            different content. Off by default because it doubles the
            fetch cost.
    """
    attempts: list[FallbackAttempt] = []
    rejected: list[str] = []
    selected_name: Optional[str] = None
    selected_df: Optional[pd.DataFrame] = None
    selected_lineage: Optional[FreeBulkLineage] = None
    substitutions: list[Mapping[str, Any]] = []
    warnings: list[str] = []

    successes: list[Mapping[str, Any]] = []

    for provider_name, fetcher in chain:
        outcome, message, df, lineage = _try_provider(provider_name, fetcher)
        rows = int(len(df)) if df is not None else 0
        attempts.append(
            FallbackAttempt(
                provider_name=provider_name,
                outcome=outcome,
                message=message,
                rows=rows,
            )
        )
        if outcome == "success" and df is not None and lineage is not None:
            successes.append(
                {
                    "provider_name": provider_name,
                    "df": df,
                    "lineage": lineage,
                    "snapshot_hash": lineage.lineage.snapshot_hash,
                }
            )
            if selected_name is None:
                selected_name = provider_name
                selected_df = df
                selected_lineage = lineage
            else:
                rejected.append(provider_name)
                substitutions.append(
                    {
                        "from": selected_name,
                        "to": provider_name,
                        "reason": "later_provider_in_chain_after_success",
                    }
                )
                warnings.append(
                    f"provider {provider_name!r} also returned data; "
                    f"selected_source remains {selected_name!r} -- not merged."
                )
            if not strict_compare:
                break
        else:
            rejected.append(provider_name)
            warnings.append(
                f"provider {provider_name!r} failed: {outcome}: {message}"
            )

    if strict_compare and len(successes) >= 2:
        # Detect content disagreement.
        primary_hash = successes[0]["snapshot_hash"]
        mismatched = [s for s in successes if s["snapshot_hash"] != primary_hash]
        if mismatched:
            raise ProviderMismatch(symbol, successes)

    missing_symbols: tuple[str, ...] = tuple()
    if selected_df is None:
        missing_symbols = (symbol,)

    return FallbackReport(
        selected_source=selected_name,
        selected_lineage=selected_lineage,
        selected_df=selected_df,
        attempts=tuple(attempts),
        rejected_sources=tuple(rejected),
        missing_symbols=missing_symbols,
        substitutions=tuple(substitutions),
        warnings=tuple(warnings),
    )


def _try_provider(
    name: str, fetcher: Fetcher
) -> Tuple[str, str, Optional[pd.DataFrame], Optional[FreeBulkLineage]]:
    """Run ``fetcher`` and classify the outcome.

    Returns ``(outcome, message, df, lineage)``. The first three fields
    drive the audit table; ``lineage`` is None on failure.
    """
    try:
        result = fetcher()
    except FreeBulkContractViolation as exc:
        return "contract_violation", str(exc), None, None
    except Exception as exc:  # noqa: BLE001 -- fallback chain catches all
        # Provider modules raise vendor-specific subclasses
        # (StooqAuthRequired, ProviderError, etc); classify by class name
        # so the report stays informative without coupling to each module.
        cls_name = type(exc).__name__
        if "Auth" in cls_name:
            return "auth_required", f"{cls_name}: {exc}", None, None
        return "error", f"{cls_name}: {exc}", None, None

    if not isinstance(result, tuple) or len(result) != 2:
        return "error", "fetcher returned non-tuple", None, None
    df, lineage = result
    if df is None or len(df) == 0:
        return "empty", "no rows returned", df, lineage
    return "success", "ok", df, lineage


# ---------------------------------------------------------------------------
# Coverage helper.
# ---------------------------------------------------------------------------


def coverage_summary(
    requested: Sequence[str], reports: Sequence[FallbackReport]
) -> dict[str, Any]:
    """Build a coverage summary for ``aurora data coverage-report``.

    Returns the count breakdown:
        requested -> total symbols asked for.
        found     -> total symbols where any provider returned data.
        usable    -> total symbols where the selected provider's frame
                     passed its contract (i.e. the report has a
                     ``selected_df``).
        missing   -> the symbols that no provider could serve.
    """
    requested_set = list(requested)
    found = 0
    usable = 0
    missing: list[str] = []
    for sym, rep in zip(requested_set, reports):
        if rep.selected_df is not None:
            found += 1
            usable += 1
        else:
            missing.append(sym)
            # Also count any attempt that returned rows but failed contract
            # ("found but unusable"); this keeps the report honest.
            for attempt in rep.attempts:
                if attempt.rows > 0 and attempt.outcome != "success":
                    found += 1
                    break
    return {
        "requested": len(requested_set),
        "found": found,
        "usable": usable,
        "missing": missing,
        "missing_count": len(missing),
    }


__all__.append("coverage_summary")

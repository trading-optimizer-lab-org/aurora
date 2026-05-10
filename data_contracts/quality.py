"""R161 - Data quality score, quarantine and coverage decisions.

Wraps the structural :func:`aurora.data_contracts.validator.validate_dataframe`
output with a numeric score, a plain-language decision and a small
JSONL-backed quarantine ledger so downstream pipelines can ask "is this
symbol approved, warned, quarantined or rejected?" without re-deriving
the answer from validator internals.

Scoring is intentionally simple. The goal is for the operator to see
which symbols are usable and why; sophisticated probabilistic scoring is
not required for honest gating.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd

from aurora.data_contracts.contract import (
    DataContract,
    DataValidationResult,
)
from aurora.data_contracts.validator import validate_dataframe


QualityDecision = Literal["approved", "warning", "quarantined", "rejected"]


@dataclass(frozen=True)
class DataQualityReport:
    """Score + decision for a single (provider, symbol, version) tuple."""

    provider: str
    symbol: str
    version: str
    decision: QualityDecision
    score: float
    row_count: int
    date_min: Optional[str]
    date_max: Optional[str]
    missing_sessions: int
    duplicate_dates: int
    non_monotonic: int
    impossible_ohlc: int
    nonpositive_prices: int
    extreme_returns: int
    reasons: Tuple[str, ...]
    warnings: Tuple[str, ...]
    contract_hash: Optional[str] = None
    snapshot_hash: Optional[str] = None
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_blocking(self) -> bool:
        return self.decision in ("quarantined", "rejected")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


# Each issue contributes a fixed deduction from a base score of 1.0. Hard
# failures (impossible OHLC, duplicate dates, non-monotonic dates) move the
# decision to "rejected" regardless of score.
_HARD_FAIL_THRESHOLD = 0
_QUARANTINE_THRESHOLD = 0.5
_WARNING_THRESHOLD = 0.85


def _detect_impossible_ohlc(df: pd.DataFrame) -> int:
    cols = {c.lower(): c for c in df.columns}
    needed = {"open", "high", "low", "close"}
    if not needed.issubset(cols):
        return 0
    o = df[cols["open"]].to_numpy(dtype=float)
    h = df[cols["high"]].to_numpy(dtype=float)
    low = df[cols["low"]].to_numpy(dtype=float)
    c = df[cols["close"]].to_numpy(dtype=float)
    bad = (h < low) | (h < o) | (h < c) | (low > o) | (low > c)
    return int(np.count_nonzero(bad))


def _detect_nonpositive(df: pd.DataFrame, contract: DataContract) -> int:
    candidate_cols = [
        col for col in contract.required_columns if col.lower() in {
            "open", "high", "low", "close", "adj_close", "price",
        }
    ]
    bad = 0
    for col in candidate_cols:
        if col not in df.columns:
            continue
        arr = df[col].to_numpy(dtype=float)
        bad += int(np.count_nonzero(arr <= 0))
    return bad


def _detect_extreme_returns(
    df: pd.DataFrame, contract: DataContract, *, threshold: float = 0.5,
) -> int:
    """Count daily returns whose magnitude exceeds ``threshold`` (50%)."""
    price_col = None
    for candidate in ("close", "adj_close", "price"):
        for col in df.columns:
            if col.lower() == candidate:
                price_col = col
                break
        if price_col is not None:
            break
    if price_col is None:
        return 0
    prices = df[price_col].to_numpy(dtype=float)
    if len(prices) < 2:
        return 0
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.diff(prices) / prices[:-1]
    rets = rets[np.isfinite(rets)]
    return int(np.count_nonzero(np.abs(rets) > threshold))


def _detect_duplicate_dates(ts_series: pd.Series) -> int:
    return int(ts_series.duplicated().sum())


def _detect_non_monotonic(ts_series: pd.Series) -> int:
    if len(ts_series) < 2:
        return 0
    diffs = ts_series.values[1:] - ts_series.values[:-1]
    return int(np.count_nonzero(diffs <= np.timedelta64(0, "ns")))


def _detect_missing_sessions(
    ts_series: pd.Series, contract: DataContract,
) -> int:
    """Count expected business-day sessions missing between min and max.

    AURORA's :class:`DataContract` does not currently declare a calendar;
    the operator opts into the missing-sessions check via the
    ``CALENDAR_NYSE`` exchange marker in the contract metadata. Crypto /
    FX contracts yield zero so we never falsely flag weekend gaps.
    """
    if len(ts_series) < 2:
        return 0
    exchange = (contract.exchange or "").upper()
    is_equity_calendar = (
        exchange.startswith(("NYSE", "NASDAQ", "ARCA", "BATS", "EQUITY"))
    )
    if not is_equity_calendar:
        return 0
    expected = pd.bdate_range(ts_series.min(), ts_series.max())
    present = set(pd.to_datetime(ts_series).dt.normalize())
    missing = sum(1 for d in expected if d not in present)
    return int(missing)


def _extract_ts(df: pd.DataFrame, contract: DataContract) -> Optional[pd.Series]:
    if contract.timestamp_col in df.columns:
        s = df[contract.timestamp_col]
    elif df.index.name == contract.timestamp_col:
        s = df.index.to_series()
    else:
        return None
    try:
        s = pd.to_datetime(s, errors="coerce")
    except Exception:
        return None
    return s.dropna()


def score_dataframe(
    df: pd.DataFrame,
    contract: DataContract,
    *,
    provider: str,
    symbol: str,
    version: str = "v1",
    snapshot_hash: Optional[str] = None,
    extreme_return_threshold: float = 0.5,
    quarantined: bool = False,
) -> DataQualityReport:
    """Score ``df`` and produce a :class:`DataQualityReport`.

    The decision honours an existing quarantine flag (``quarantined=True``)
    so a previously-quarantined dataset stays quarantined even after a
    re-run that finds no new issues.
    """
    structural: DataValidationResult = validate_dataframe(
        df, contract, snapshot_hash=snapshot_hash,
    )
    ts = _extract_ts(df, contract)
    duplicate_dates = _detect_duplicate_dates(ts) if ts is not None else 0
    non_monotonic = _detect_non_monotonic(ts) if ts is not None else 0
    impossible_ohlc = _detect_impossible_ohlc(df)
    nonpositive_prices = _detect_nonpositive(df, contract)
    extreme_returns = _detect_extreme_returns(
        df, contract, threshold=extreme_return_threshold
    )
    missing_sessions = _detect_missing_sessions(ts, contract) if ts is not None else 0

    reasons: List[str] = []
    score = 1.0
    hard_fail = False
    if not structural.passed:
        reasons.extend(f"structural: {e}" for e in structural.errors)
        hard_fail = True
        score -= 0.5
    if duplicate_dates:
        reasons.append(f"{duplicate_dates} duplicate dates")
        hard_fail = True
        score -= 0.4
    if non_monotonic:
        reasons.append(f"{non_monotonic} non-monotonic dates")
        hard_fail = True
        score -= 0.4
    if impossible_ohlc:
        reasons.append(f"{impossible_ohlc} bars with impossible OHLC")
        hard_fail = True
        score -= 0.4
    if nonpositive_prices:
        reasons.append(f"{nonpositive_prices} non-positive prices")
        score -= 0.2
    if extreme_returns:
        reasons.append(f"{extreme_returns} extreme returns (>50%)")
        score -= 0.05 * min(extreme_returns, 5)
    if missing_sessions:
        reasons.append(f"{missing_sessions} missing equity sessions")
        score -= 0.01 * min(missing_sessions, 30)
    score = max(0.0, score)

    if quarantined:
        decision: QualityDecision = "quarantined"
    elif hard_fail or score <= _HARD_FAIL_THRESHOLD:
        decision = "rejected"
    elif score < _QUARANTINE_THRESHOLD:
        decision = "quarantined"
    elif score < _WARNING_THRESHOLD:
        decision = "warning"
    else:
        decision = "approved"

    return DataQualityReport(
        provider=provider,
        symbol=symbol,
        version=version,
        decision=decision,
        score=round(score, 4),
        row_count=len(df),
        date_min=(ts.min().isoformat() if ts is not None and len(ts) else None),
        date_max=(ts.max().isoformat() if ts is not None and len(ts) else None),
        missing_sessions=missing_sessions,
        duplicate_dates=duplicate_dates,
        non_monotonic=non_monotonic,
        impossible_ohlc=impossible_ohlc,
        nonpositive_prices=nonpositive_prices,
        extreme_returns=extreme_returns,
        reasons=tuple(reasons),
        warnings=tuple(structural.warnings),
        contract_hash=structural.contract_hash,
        snapshot_hash=structural.snapshot_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Quarantine ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuarantineEntry:
    """One quarantine action recorded by the operator."""

    provider: str
    library: str
    symbol: str
    version: str
    reason: str
    actor: str
    decision: QualityDecision
    recorded_at: str

    def key(self) -> Tuple[str, str, str, str]:
        return (self.provider, self.library, self.symbol, self.version)


class QuarantineLedger:
    """Append-only JSONL ledger of quarantine / approve actions.

    The latest record per ``(provider, library, symbol, version)`` wins.
    The ledger is intentionally a flat JSONL file so it can be inspected
    with `cat` / `jq` and committed to git when the operator wants a
    versioned record.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _ensure_parent(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: QuarantineEntry) -> None:
        if entry.decision not in ("quarantined", "approved"):
            raise ValueError(
                f"ledger only records quarantined/approved, got {entry.decision!r}"
            )
        with self._lock:
            self._ensure_parent()
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(entry), sort_keys=True) + "\n")

    def quarantine(
        self,
        *,
        provider: str,
        library: str,
        symbol: str,
        version: str,
        reason: str,
        actor: str,
    ) -> QuarantineEntry:
        entry = QuarantineEntry(
            provider=provider,
            library=library,
            symbol=symbol,
            version=version,
            reason=reason,
            actor=actor,
            decision="quarantined",
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.append(entry)
        return entry

    def approve(
        self,
        *,
        provider: str,
        library: str,
        symbol: str,
        version: str,
        reason: str,
        actor: str,
    ) -> QuarantineEntry:
        entry = QuarantineEntry(
            provider=provider,
            library=library,
            symbol=symbol,
            version=version,
            reason=reason,
            actor=actor,
            decision="approved",
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.append(entry)
        return entry

    def entries(self) -> List[QuarantineEntry]:
        if not self._path.exists():
            return []
        out: List[QuarantineEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                out.append(QuarantineEntry(**payload))
        return out

    def latest_state(self) -> Dict[Tuple[str, str, str, str], QuarantineEntry]:
        """Return ``{key: latest_entry}`` keyed by (provider, library, symbol, version)."""
        latest: Dict[Tuple[str, str, str, str], QuarantineEntry] = {}
        for e in self.entries():
            latest[e.key()] = e
        return latest

    def is_quarantined(
        self,
        *,
        provider: str,
        library: str,
        symbol: str,
        version: str,
    ) -> bool:
        state = self.latest_state().get((provider, library, symbol, version))
        return bool(state and state.decision == "quarantined")


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    """Aggregated breakdown of dataset state for an operator overview."""

    requested: Tuple[str, ...]
    approved: Tuple[str, ...]
    warning: Tuple[str, ...]
    quarantined: Tuple[str, ...]
    rejected: Tuple[str, ...]
    missing: Tuple[str, ...]

    @property
    def counts(self) -> Dict[str, int]:
        return {
            "requested": len(self.requested),
            "approved": len(self.approved),
            "warning": len(self.warning),
            "quarantined": len(self.quarantined),
            "rejected": len(self.rejected),
            "missing": len(self.missing),
        }

    def to_dict(self) -> dict:
        return {
            "requested": list(self.requested),
            "approved": list(self.approved),
            "warning": list(self.warning),
            "quarantined": list(self.quarantined),
            "rejected": list(self.rejected),
            "missing": list(self.missing),
            "counts": self.counts,
        }


def build_coverage(
    requested: List[str],
    reports: List[DataQualityReport],
) -> CoverageReport:
    by_symbol = {r.symbol: r for r in reports}
    approved = sorted(
        s for s in requested
        if (r := by_symbol.get(s)) is not None and r.decision == "approved"
    )
    warning = sorted(
        s for s in requested
        if (r := by_symbol.get(s)) is not None and r.decision == "warning"
    )
    quarantined = sorted(
        s for s in requested
        if (r := by_symbol.get(s)) is not None and r.decision == "quarantined"
    )
    rejected = sorted(
        s for s in requested
        if (r := by_symbol.get(s)) is not None and r.decision == "rejected"
    )
    missing = sorted(s for s in requested if s not in by_symbol)
    return CoverageReport(
        requested=tuple(requested),
        approved=tuple(approved),
        warning=tuple(warning),
        quarantined=tuple(quarantined),
        rejected=tuple(rejected),
        missing=tuple(missing),
    )


__all__ = [
    "CoverageReport",
    "DataQualityReport",
    "QualityDecision",
    "QuarantineEntry",
    "QuarantineLedger",
    "build_coverage",
    "score_dataframe",
]

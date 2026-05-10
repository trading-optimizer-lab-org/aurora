"""Corporate-action records and adjustment verifiers.

A :class:`CorporateActionRecord` describes a single action affecting an
instrument: split / reverse split, cash dividend, special dividend,
merger, spin-off, symbol change, etc. The verifiers in this module check
whether prices around the action have been adjusted in a way that is
*consistent* with the action -- they do NOT recompute the adjustment.

They return a small descriptor with a boolean ``passed`` flag plus a
human-readable reason so the caller (validator, factory, audit pipeline)
can record the decision. Tolerances are configurable so the verifiers
work both for clean vendor data and for slightly messier broker fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date_type
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple


# Action types we know how to reason about. Other values are accepted
# (round-tripping through the validator may still record them) but the
# verifiers below only treat these explicitly. ``ticker_change`` is the
# canonical R160 alias for ``symbol_change``; both are accepted so the
# rename is non-breaking.
KNOWN_ACTION_TYPES = (
    "split",
    "reverse_split",
    "cash_dividend",
    "special_dividend",
    "merger",
    "spin_off",
    "symbol_change",
    "ticker_change",
    "delisting",
    "suspension",
    "adr_ratio_change",
)


class AdjustmentStatus(str, Enum):
    """Adjustment posture recorded on a price provenance record.

    A snapshot manifest must carry one of these values so downstream
    consumers know whether the prices they are reading were already
    rolled forward through corporate actions or not. ``UNKNOWN`` is the
    explicit "we don't know" marker; production-grade consumers (the
    snapshot approval gate, factory submit, paper / live promotion)
    should refuse ``UNKNOWN`` for equities and ETFs.
    """

    RAW = "RAW"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    DIVIDEND_ADJUSTED = "DIVIDEND_ADJUSTED"
    TOTAL_RETURN = "TOTAL_RETURN"
    UNKNOWN = "UNKNOWN"


# Action types where adjustment is structurally required for honest
# backtests. If the provenance status is UNKNOWN and any of these
# actions exist for the instrument, the snapshot must not be approved.
_ADJUSTMENT_REQUIRED_ACTIONS = frozenset({
    "split",
    "reverse_split",
    "cash_dividend",
    "special_dividend",
    "spin_off",
})


@dataclass(frozen=True)
class CorporateActionRecord:
    """One corporate action affecting one instrument.

    Attributes:
        symbol: internal symbol from the Security Master.
        action_type: one of :data:`KNOWN_ACTION_TYPES` (other values are
            tolerated but verifiers treat them as no-ops).
        effective_date: action effective date.
        factor: split factor (e.g. ``2.0`` for a 2-for-1 split,
            ``0.5`` for a 1-for-2 reverse split). ``None`` for
            non-split actions.
        cash_amount: cash distributed per share (e.g. dividend). ``None``
            for non-cash actions.
    """

    symbol: str
    action_type: str
    effective_date: _date_type
    factor: Optional[float] = None
    cash_amount: Optional[float] = None


@dataclass(frozen=True)
class AdjustmentCheck:
    """Result of running a verifier against a price window."""

    passed: bool
    reason: str = ""


def verify_split_adjustment(
    prices_before: Sequence[float],
    prices_after: Sequence[float],
    action: CorporateActionRecord,
    *,
    tolerance: float = 0.01,
) -> AdjustmentCheck:
    """Verify a split was applied consistently.

    A split with factor ``f`` divides per-share prices by ``f`` going
    forward (e.g. a 2-for-1 split halves prices). If the data is
    *unadjusted*, the bar-to-bar move on the effective date will look
    like a dramatic jump. If the data is *adjusted*, the historical
    prices were already pre-divided so the level should line up.

    The check compares the last pre-action price against the first
    post-action price. ``passed=True`` means the ratio is consistent
    with the recorded factor within ``tolerance`` (relative).
    """
    if action.action_type not in {"split", "reverse_split"}:
        return AdjustmentCheck(False, f"action_type {action.action_type!r} is not a split")
    if action.factor is None or action.factor <= 0:
        return AdjustmentCheck(False, "split factor must be a positive float")
    if not prices_before or not prices_after:
        return AdjustmentCheck(False, "need at least one price on each side")

    last_before = float(prices_before[-1])
    first_after = float(prices_after[0])
    if last_before <= 0 or first_after <= 0:
        return AdjustmentCheck(False, "non-positive prices around action")

    expected_after = last_before / action.factor
    rel_err = abs(first_after - expected_after) / max(expected_after, 1e-12)
    if rel_err <= tolerance:
        return AdjustmentCheck(
            True,
            f"split adjustment consistent: ratio {first_after / last_before:.6f} "
            f"matches 1/factor={1.0 / action.factor:.6f} (rel_err={rel_err:.4f})",
        )
    return AdjustmentCheck(
        False,
        f"split adjustment inconsistent: first_after={first_after:.6f} vs "
        f"expected={expected_after:.6f} (rel_err={rel_err:.4f})",
    )


def verify_dividend_adjustment(
    prices_before: Sequence[float],
    prices_after: Sequence[float],
    action: CorporateActionRecord,
    *,
    tolerance: float = 0.05,
) -> AdjustmentCheck:
    """Verify a cash-dividend adjustment is consistent.

    Cash dividends drop the price by approximately the cash amount on
    the ex-date. The check compares ``last_before - first_after`` to
    the recorded ``cash_amount`` within ``tolerance`` (relative to the
    pre-action price level).
    """
    if action.action_type not in {"cash_dividend", "special_dividend"}:
        return AdjustmentCheck(
            False, f"action_type {action.action_type!r} is not a dividend"
        )
    if action.cash_amount is None or action.cash_amount <= 0:
        return AdjustmentCheck(False, "cash_amount must be a positive float")
    if not prices_before or not prices_after:
        return AdjustmentCheck(False, "need at least one price on each side")

    last_before = float(prices_before[-1])
    first_after = float(prices_after[0])
    if last_before <= 0 or first_after <= 0:
        return AdjustmentCheck(False, "non-positive prices around action")

    drop = last_before - first_after
    expected_drop = float(action.cash_amount)
    rel_err = abs(drop - expected_drop) / max(last_before, 1e-12)
    if rel_err <= tolerance:
        return AdjustmentCheck(
            True,
            f"dividend adjustment consistent: drop={drop:.6f} vs "
            f"cash_amount={expected_drop:.6f} (rel_err={rel_err:.4f})",
        )
    return AdjustmentCheck(
        False,
        f"dividend adjustment inconsistent: drop={drop:.6f} vs "
        f"cash_amount={expected_drop:.6f} (rel_err={rel_err:.4f})",
    )


def _coerce_date(value: Any) -> _date_type:
    """Best-effort coercion of ``value`` to a stdlib ``datetime.date``."""
    from datetime import datetime as _dt

    # datetime.datetime subclasses datetime.date so check it first.
    if isinstance(value, _dt):
        return value.date()
    if isinstance(value, _date_type):
        return value
    # pandas.Timestamp has .date() returning datetime.date
    if hasattr(value, "date") and callable(value.date):
        return value.date()
    if isinstance(value, str):
        return _dt.fromisoformat(value).date()
    raise TypeError(f"cannot interpret {value!r} as a date")


def _split_prices_around(
    prices: Sequence[Any],
    dates: Sequence[Any],
    effective_date: _date_type,
    *,
    window: int = 1,
) -> Tuple[List[float], List[float]]:
    """Pick ``window`` prices on either side of ``effective_date``.

    ``dates`` and ``prices`` must align by index. Returns
    ``(prices_before, prices_after)``. Either side may be empty if the
    fixture does not span the action.
    """
    before: List[Tuple[_date_type, float]] = []
    after: List[Tuple[_date_type, float]] = []
    for d, p in zip(dates, prices):
        try:
            d_norm = _coerce_date(d)
        except TypeError:
            continue
        try:
            p_val = float(p)
        except (TypeError, ValueError):
            continue
        if d_norm < effective_date:
            before.append((d_norm, p_val))
        elif d_norm >= effective_date:
            after.append((d_norm, p_val))
    before.sort(key=lambda x: x[0])
    after.sort(key=lambda x: x[0])
    return (
        [p for _, p in before[-window:]],
        [p for _, p in after[:window]],
    )


def report_corporate_actions(
    records: Sequence[CorporateActionRecord],
    prices: Optional[Any] = None,
) -> Dict[str, Any]:
    """Produce a small, deterministic summary of corporate actions.

    Parameters
    ----------
    records:
        Sequence of :class:`CorporateActionRecord`.
    prices:
        Optional price series. May be a pandas DataFrame or a mapping
        with at least ``date`` (or ``timestamp``) and ``close`` columns.
        Used to run :func:`verify_split_adjustment` /
        :func:`verify_dividend_adjustment` for each compatible action.
        When ``None`` the report still summarises the records but skips
        adjustment checks.

    Returns
    -------
    dict
        With keys:

        * ``summary``: one-line text overview (deterministic).
        * ``counts``: ``{action_type: count}``.
        * ``actions``: per-action descriptors with optional ``check``.
        * ``unknown_action_types``: action types not in :data:`KNOWN_ACTION_TYPES`.
        * ``text``: multi-line plain-English report.
    """
    counts: Dict[str, int] = {}
    unknown: List[str] = []
    actions_out: List[Dict[str, Any]] = []

    # Pull out (dates, closes) once if a frame-like was supplied.
    dates_arr: Optional[Sequence[Any]] = None
    close_arr: Optional[Sequence[Any]] = None
    if prices is not None:
        dates_arr, close_arr = _extract_dates_and_close(prices)

    sorted_records = sorted(
        records,
        key=lambda r: (r.effective_date, r.symbol, r.action_type),
    )
    for rec in sorted_records:
        counts[rec.action_type] = counts.get(rec.action_type, 0) + 1
        if rec.action_type not in KNOWN_ACTION_TYPES:
            unknown.append(rec.action_type)

        descriptor: Dict[str, Any] = {
            "symbol": rec.symbol,
            "action_type": rec.action_type,
            "effective_date": rec.effective_date.isoformat(),
            "factor": rec.factor,
            "cash_amount": rec.cash_amount,
            "check": None,
        }

        if dates_arr is not None and close_arr is not None:
            before, after = _split_prices_around(
                close_arr, dates_arr, rec.effective_date,
            )
            check: Optional[AdjustmentCheck] = None
            if rec.action_type in {"split", "reverse_split"}:
                check = verify_split_adjustment(before, after, rec)
            elif rec.action_type in {"cash_dividend", "special_dividend"}:
                check = verify_dividend_adjustment(before, after, rec)
            if check is not None:
                descriptor["check"] = {
                    "passed": bool(check.passed),
                    "reason": check.reason,
                }
        actions_out.append(descriptor)

    # Plausibility flag: True iff every check we ran passed; None if no
    # checks were applicable (e.g. only ticker changes / delistings).
    passed_checks = [a["check"] for a in actions_out if a["check"] is not None]
    if not passed_checks:
        plausibility: Optional[bool] = None
    else:
        plausibility = all(c["passed"] for c in passed_checks)

    summary = f"{len(actions_out)} corporate actions across {len(set(r.symbol for r in records))} symbols"
    text_lines = [summary]
    for a in actions_out:
        line = (
            f"  {a['effective_date']} {a['symbol']:<8} {a['action_type']:<18}"
            f" factor={a['factor']!s} cash={a['cash_amount']!s}"
        )
        if a["check"] is not None:
            line += f"  [{'PASS' if a['check']['passed'] else 'FAIL'}: {a['check']['reason']}]"
        text_lines.append(line)
    if unknown:
        text_lines.append(f"  unknown action types: {sorted(set(unknown))}")
    if plausibility is not None:
        text_lines.append(
            f"  price-series plausibility: {'consistent' if plausibility else 'inconsistent'}"
        )

    return {
        "summary": summary,
        "counts": counts,
        "actions": actions_out,
        "unknown_action_types": sorted(set(unknown)),
        "plausibility": plausibility,
        "text": "\n".join(text_lines),
    }


def _extract_dates_and_close(prices: Any) -> Tuple[Optional[Sequence[Any]], Optional[Sequence[Any]]]:
    """Best-effort extraction of (dates, close prices) from a frame-like.

    Supports pandas DataFrames with a ``date``/``timestamp`` column plus a
    ``close`` (or ``adj_close``) column; mappings with the same keys; and
    a 2-tuple ``(dates, closes)``.
    """
    # mapping / dict
    if isinstance(prices, dict):
        date_key = next(
            (k for k in ("date", "timestamp", "Date", "Timestamp") if k in prices), None
        )
        price_key = next(
            (k for k in ("close", "adj_close", "Close") if k in prices), None
        )
        if date_key is None or price_key is None:
            return None, None
        return list(prices[date_key]), list(prices[price_key])
    # 2-tuple of sequences
    if isinstance(prices, tuple) and len(prices) == 2:
        return list(prices[0]), list(prices[1])
    # pandas DataFrame
    columns = getattr(prices, "columns", None)
    if columns is not None:
        cols = {str(c).lower(): c for c in columns}
        date_col = cols.get("date") or cols.get("timestamp")
        price_col = cols.get("close") or cols.get("adj_close")
        if date_col is not None and price_col is not None:
            return list(prices[date_col]), list(prices[price_col])
    return None, None


__all__ = [
    "AdjustmentCheck",
    "AdjustmentStatus",
    "CorporateActionRecord",
    "KNOWN_ACTION_TYPES",
    "report_corporate_actions",
    "verify_dividend_adjustment",
    "verify_split_adjustment",
]

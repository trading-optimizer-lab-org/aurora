"""Multi-tier data splits per RESEARCH_PROTOCOL.md.

Tiers:
- IS_TRAIN: 1995-01-01 to 2010-12-31 - model fitting
- IS_VALID: 2011-01-01 to 2012-12-31 - inner WF holdout
- OOS_DEV:  2013-01-01 to 2020-12-31 - post-GA validation, can re-touch
- OOS_LOCKED: 2021-01-01 to 2024-12-31 - frozen, single-look ceremony
- FORWARD:  2025-01-01 onwards - paper/live
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional, Union, TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from aurora.core.snapshots import DataSnapshot

# P0.A: tier boundaries are now sourced from ``ProtocolPolicy``. The
# module-level constants below remain for backwards compatibility but
# are seeded from ``ProtocolPolicy.load()`` at import time. Tests that
# need a custom policy can call ``set_active_policy`` and then
# ``reload_tier_constants_from_policy`` to re-seed.
def _resolve_tier_constants() -> dict:
    """Read the canonical tier date table from the active ``ProtocolPolicy``."""
    # Late import to avoid a circular dependency at package import time.
    from aurora.core.protocol_policy import get_active_policy
    pol = get_active_policy()
    tiers = pol.tiers
    out = {
        "IS_TRAIN_END": pd.Timestamp(tiers["IS_TRAIN"].end),
        "IS_VALID_START": pd.Timestamp(tiers["IS_VALID"].start),
        "IS_VALID_END": pd.Timestamp(tiers["IS_VALID"].end),
        "OOS_DEV_START": pd.Timestamp(tiers["OOS_DEV"].start),
        "OOS_DEV_END": pd.Timestamp(tiers["OOS_DEV"].end),
        "OOS_LOCKED_START": pd.Timestamp(tiers["OOS_LOCKED"].start),
        "OOS_LOCKED_END": pd.Timestamp(tiers["OOS_LOCKED"].end),
        "FORWARD_START": pd.Timestamp(tiers["FORWARD"].start),
    }
    return out


_constants = _resolve_tier_constants()
IS_TRAIN_END = _constants["IS_TRAIN_END"]
IS_VALID_START = _constants["IS_VALID_START"]
IS_VALID_END = _constants["IS_VALID_END"]
OOS_DEV_START = _constants["OOS_DEV_START"]
OOS_DEV_END = _constants["OOS_DEV_END"]
OOS_LOCKED_START = _constants["OOS_LOCKED_START"]
OOS_LOCKED_END = _constants["OOS_LOCKED_END"]
FORWARD_START = _constants["FORWARD_START"]


def reload_tier_constants_from_policy() -> None:
    """Re-seed the module-level tier constants from the active policy.

    Useful for tests that swap in a custom :class:`ProtocolPolicy` via
    :func:`aurora.core.protocol_policy.set_active_policy`.
    """
    global IS_TRAIN_END, IS_VALID_START, IS_VALID_END
    global OOS_DEV_START, OOS_DEV_END
    global OOS_LOCKED_START, OOS_LOCKED_END, FORWARD_START
    global _TIER_END_DATES
    c = _resolve_tier_constants()
    IS_TRAIN_END = c["IS_TRAIN_END"]
    IS_VALID_START = c["IS_VALID_START"]
    IS_VALID_END = c["IS_VALID_END"]
    OOS_DEV_START = c["OOS_DEV_START"]
    OOS_DEV_END = c["OOS_DEV_END"]
    OOS_LOCKED_START = c["OOS_LOCKED_START"]
    OOS_LOCKED_END = c["OOS_LOCKED_END"]
    FORWARD_START = c["FORWARD_START"]
    # Rebuild the tier-end-date lookup so ``load_up_to_tier`` sees the
    # refreshed constants.
    _TIER_END_DATES = {
        "IS_TRAIN": IS_TRAIN_END,
        "IS_VALID": IS_VALID_END,
        "OOS_DEV": OOS_DEV_END,
        "OOS_LOCKED": OOS_LOCKED_END,
        "FORWARD": pd.Timestamp.max,
    }

Tier = Literal["IS_TRAIN", "IS_VALID", "OOS_DEV", "OOS_LOCKED", "FORWARD"]


@dataclass(frozen=True)
class TierSplit:
    """Five-tier split of a price series.

    Attributes:
        is_train:  prices with index <= IS_TRAIN_END (1995-01-01..2010-12-31).
        is_valid:  prices with IS_VALID_START..IS_VALID_END (2011-2012).
        oos_dev:   prices with OOS_DEV_START..OOS_DEV_END  (2013-2020).
        oos_locked: prices with OOS_LOCKED_START..OOS_LOCKED_END (2021-2024).
        forward:   prices with index >= FORWARD_START (>= 2025-01-01).
    """

    is_train: pd.Series
    is_valid: pd.Series
    oos_dev: pd.Series
    oos_locked: pd.Series
    forward: pd.Series

    @property
    def is_all(self) -> pd.Series:
        """IS_TRAIN + IS_VALID combined (for legacy callers)."""
        return pd.concat([self.is_train, self.is_valid])


def split_by_tier(prices: pd.Series) -> TierSplit:
    """Split prices into 5 tiers per protocol.

    Round-4 audit fix (P1.2)
    ------------------------
    All tier boundary timestamps are at midnight (00:00:00). For an
    intraday DatetimeIndex (e.g. a 09:30 bar on 2010-12-31), the bare
    ``idx <= IS_TRAIN_END`` test fails because ``09:30 > 00:00`` --
    that bar would simultaneously fail the IS_TRAIN bound AND fail
    ``idx >= IS_VALID_START`` (2011-01-01 00:00), so it would land in
    no tier at all.

    The fix is to compare the *date component* of the index to the
    boundary dates: ``idx.normalize()`` snaps each timestamp to its
    midnight, so an intraday 2010-12-31 09:30 bar is treated as
    2010-12-31 and lands in IS_TRAIN. This preserves the date-precision
    contract of the tier definitions (1995-01-01..2010-12-31, etc.)
    regardless of whether the input series is daily or intraday.

    Args:
        prices: price series with a DatetimeIndex.

    Returns:
        TierSplit with the five disjoint tier slices.
    """
    idx = pd.to_datetime(prices.index)
    # P1.2: normalize to date-precision so intraday bars on a boundary
    # date sort into the correct tier.
    idx_dates = idx.normalize()
    return TierSplit(
        is_train=prices[idx_dates <= IS_TRAIN_END],
        is_valid=prices[(idx_dates >= IS_VALID_START)
                         & (idx_dates <= IS_VALID_END)],
        oos_dev=prices[(idx_dates >= OOS_DEV_START)
                        & (idx_dates <= OOS_DEV_END)],
        oos_locked=prices[(idx_dates >= OOS_LOCKED_START)
                           & (idx_dates <= OOS_LOCKED_END)],
        forward=prices[idx_dates >= FORWARD_START],
    )


def get_tier(prices: pd.Series, tier: Tier) -> pd.Series:
    """Return a single tier slice from `prices`.

    Args:
        prices: price series with a DatetimeIndex.
        tier: one of "IS_TRAIN", "IS_VALID", "OOS_DEV", "OOS_LOCKED", "FORWARD".

    Returns:
        The requested tier slice.
    """
    s = split_by_tier(prices)
    return getattr(s, tier.lower())


# ---------------------------------------------------------------------------
# Tier-bounded loaders (round-3 fix)
# ---------------------------------------------------------------------------
#
# ``load_asset(include_oos=True)`` is the legacy "give me everything"
# loader. Several CLI commands and ``cmd_search`` only need data up to
# OOS_DEV but were calling the unbounded loader, so OOS_LOCKED and
# FORWARD bars were leaking into the cached DataFrame even though the
# downstream code never *used* them. Round-3 of the audit asks for a
# tier-cap loader so the protocol boundary is enforced at read time, not
# at slice time.
#
# Tier ordinals -- used by ``load_up_to_tier`` to compute the upper
# date bound. Mirrors the order of the dataclass fields above.
_TIER_END_DATES: dict[str, pd.Timestamp] = {
    "IS_TRAIN": IS_TRAIN_END,
    "IS_VALID": IS_VALID_END,
    "OOS_DEV": OOS_DEV_END,
    "OOS_LOCKED": OOS_LOCKED_END,
    # FORWARD has no fixed upper bound -- callers that ask for FORWARD
    # accept "everything from 2025-01-01 onwards".
    "FORWARD": pd.Timestamp.max,
}

# Which ceremony phase each tier requires when read directly. ``IS_TRAIN``
# / ``IS_VALID`` / ``OOS_DEV`` are routine; ``OOS_LOCKED`` / ``FORWARD``
# require an explicit unlock ceremony to keep formal validation honest.
_TIER_REQUIRED_CEREMONY: dict[str, Optional[str]] = {
    "IS_TRAIN": None,
    "IS_VALID": None,
    "OOS_DEV": None,
    "OOS_LOCKED": "explicit_unlock_oos_locked",
    "FORWARD": "explicit_unlock_forward",
}


def _normalize_tier(tier: str) -> str:
    """Upper-case + validate a tier label."""
    if not isinstance(tier, str):
        raise TypeError(f"tier must be str, got {type(tier).__name__}")
    norm = tier.upper()
    if norm not in _TIER_END_DATES:
        raise ValueError(
            f"tier={tier!r} not in "
            f"{sorted(_TIER_END_DATES)}"
        )
    return norm


def load_up_to_tier(
    symbol: str,
    max_tier: str = "OOS_DEV",
    *,
    source: str = "yfinance",
    require_snapshot: bool = False,
    freeze: bool = False,
    provenance: Optional[str] = None,
    oos_purpose: Optional[str] = None,
) -> Union[pd.Series, tuple[pd.Series, "DataSnapshot"]]:
    """Load a price series capped at the end of ``max_tier``.

    Round-3 audit fix: ``cmd_search`` / ``cmd_validate`` only need bars
    up to ``OOS_DEV_END`` (2020-12-31) but the legacy
    ``load_asset(include_oos=True)`` returned every cached bar
    including OOS_LOCKED (2021-2024) and FORWARD (>=2025). Cached
    parquet files written by older runs may already contain those
    later bars, so simply reading the cache leaks the lockbox into
    the formal-validation address space.

    This helper takes the *upper bound* approach: it resolves the
    series via ``load_asset`` and then trims to ``<= end_of(max_tier)``.
    Callers requesting OOS-bearing tiers (anything from OOS_DEV up)
    pass ``include_oos=True`` to ``load_asset``, which will record the
    read on the active OOSGuard.

    Args:
        symbol: e.g. "SPY", "^GSPC".
        max_tier: one of ``"IS_TRAIN"``, ``"IS_VALID"``, ``"OOS_DEV"``
            (default), ``"OOS_LOCKED"``, ``"FORWARD"``. The returned
            series ends at the inclusive end-date of that tier
            (FORWARD = unbounded).
        source: ``load_asset`` source argument.
        require_snapshot: passed through to ``load_asset``. When True,
            the formal-validation snapshot lookup applies.
        freeze: when True, returns ``(prices, snapshot)``.
        provenance: provenance label for the frozen snapshot.
        oos_purpose: passed through; only used when ``max_tier`` is
            an OOS tier.

    Returns:
        Series (default) or ``(Series, DataSnapshot)`` when
        ``freeze=True``.

    Raises:
        ValueError: if ``max_tier`` is not a known tier label.
        RuntimeError: if ``max_tier`` is OOS_LOCKED / FORWARD and no
            matching ``OOSGuard("explicit_unlock_*")`` is active.
    """
    norm = _normalize_tier(max_tier)
    end_ts = _TIER_END_DATES[norm]
    # Anything from OOS_DEV up needs include_oos=True so the read is
    # authorized and recorded on the active guard.
    needs_oos = norm in ("OOS_DEV", "OOS_LOCKED", "FORWARD")

    # Locked tiers require a matching ceremony BEFORE the read happens
    # so the lockbox cannot be tripped by ordinary CLI flags.
    required = _TIER_REQUIRED_CEREMONY[norm]
    if required is not None:
        # Late import: data_layer imports data_tiers (split_by_tier),
        # so we must defer to break the cycle.
        from aurora.core.data_layer import OOSGuard
        active = OOSGuard.active()
        if active is None or active.phase != required:
            raise RuntimeError(
                f"load_up_to_tier({symbol!r}, max_tier={max_tier!r}) "
                f"requires an active OOSGuard({required!r}); "
                "locked tiers are gated by a single-look ceremony."
            )

    # Late import to avoid a cycle (data_layer -> snapshots -> ... -> data_tiers).
    from aurora.core.data_layer import load_asset
    result = load_asset(
        symbol,
        source=source,
        include_oos=needs_oos,
        freeze=freeze,
        provenance=provenance,
        oos_purpose=oos_purpose,
        require_snapshot=require_snapshot,
    )
    if freeze:
        prices, snap = result
    else:
        prices = result
    # Cap at the tier upper bound. ``end_ts`` is ``Timestamp.max`` for
    # FORWARD, which is effectively a no-op cap. P1.2: compare against
    # the date component so intraday bars on the boundary date are
    # included.
    if end_ts != pd.Timestamp.max:
        prices = prices[pd.to_datetime(prices.index).normalize() <= end_ts]
    if freeze:
        return prices, snap
    return prices


def load_tier(
    symbol: str,
    tier: str,
    *,
    source: str = "yfinance",
    require_snapshot: bool = False,
    freeze: bool = False,
    provenance: Optional[str] = None,
    oos_purpose: Optional[str] = None,
) -> Union[pd.Series, tuple[pd.Series, "DataSnapshot"]]:
    """Load only the bars belonging to ``tier``.

    Round-3 audit fix: gives every CLI subcommand a single, explicit
    way to ask for "just the IS_VALID slice" or "just the OOS_DEV
    slice" without ever materializing a series that contains OOS_LOCKED
    or FORWARD bars.

    Args:
        symbol: e.g. "SPY".
        tier: one of ``"IS_TRAIN"``, ``"IS_VALID"``, ``"OOS_DEV"``,
            ``"OOS_LOCKED"``, ``"FORWARD"``.
        source: ``load_asset`` source argument.
        require_snapshot: passed through to ``load_asset``.
        freeze: when True, returns ``(slice, snapshot)``. The snapshot
            covers the FULL series read (whatever ``load_asset`` saw),
            not the carved tier slice -- the snapshot's hash is
            content-addressed off the underlying data, not the carve.
        provenance: provenance label for the frozen snapshot.
        oos_purpose: passed through.

    Returns:
        Series (default) or ``(Series, DataSnapshot)`` when
        ``freeze=True``. Returns an empty Series with a DatetimeIndex
        when the tier window contains no bars in the loaded series.

    Raises:
        ValueError: if ``tier`` is not a known tier label.
        RuntimeError: if ``tier`` is OOS_LOCKED / FORWARD and no
            matching ``OOSGuard("explicit_unlock_*")`` is active.
    """
    norm = _normalize_tier(tier)
    # Reuse load_up_to_tier so the ceremony / OOS-guard gating lives in
    # exactly one place, then trim the lower bound for the requested
    # tier.
    result = load_up_to_tier(
        symbol,
        max_tier=norm,
        source=source,
        require_snapshot=require_snapshot,
        freeze=freeze,
        provenance=provenance,
        oos_purpose=oos_purpose,
    )
    if freeze:
        prices, snap = result
    else:
        prices = result
    tiers = split_by_tier(prices)
    sliced: pd.Series = getattr(tiers, norm.lower())
    if freeze:
        return sliced, snap
    return sliced

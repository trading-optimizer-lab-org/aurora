"""Timezone handling helpers (R45).

Backtest pricing is UTC by default. Live exchanges have local sessions
(NY = America/New_York, London = Europe/London, Tokyo = Asia/Tokyo,
crypto = 24h UTC). The helpers below surface clear errors when a
caller mixes a tz-naive index with a tz-aware one and provide the
canonical exchange -> tz mapping.

R45 closure note: the audit recommended in the roadmap (walk every
date / time boundary) is a multi-week project. This module is the
foundation: every new module must import these helpers when it
crosses a session boundary, and the audit follow-up will sweep
existing modules to enforce the same.
"""
from __future__ import annotations

from typing import Optional, Union

import pandas as pd


# --------------------------------------------------------------------------
# Canonical exchange -> tz mapping
# --------------------------------------------------------------------------
#
# Trading-hour-aware modules should resolve symbols to exchanges via the
# DataProviderRegistry (or per-symbol metadata) and then look up the tz
# here. Adding a new exchange requires updating this map AND a test
# case asserting the right tz is returned.
EXCHANGE_TIMEZONES: dict[str, str] = {
    # US equities + ETFs
    "NYSE": "America/New_York",
    "NASDAQ": "America/New_York",
    "AMEX": "America/New_York",
    "ARCA": "America/New_York",
    "BATS": "America/New_York",
    "CBOE": "America/Chicago",
    # US futures
    "CME": "America/Chicago",
    "CBOT": "America/Chicago",
    "NYMEX": "America/New_York",
    "COMEX": "America/New_York",
    # UK / EU
    "LSE": "Europe/London",
    "EURONEXT": "Europe/Paris",
    "XETRA": "Europe/Berlin",
    "SIX": "Europe/Zurich",
    # Asia
    "TSE": "Asia/Tokyo",
    "JPX": "Asia/Tokyo",
    "HKEX": "Asia/Hong_Kong",
    "SSE": "Asia/Shanghai",
    "SZSE": "Asia/Shanghai",
    "ASX": "Australia/Sydney",
    # Crypto: 24/7 UTC convention
    "CRYPTO": "UTC",
}


def tz_for_exchange(exchange: str) -> str:
    """Return the canonical IANA tz string for ``exchange``.

    Raises:
        KeyError: when the exchange is not in :data:`EXCHANGE_TIMEZONES`.
            Callers must update the map before adding strategies on a
            new exchange.
    """
    key = exchange.upper()
    if key not in EXCHANGE_TIMEZONES:
        raise KeyError(
            f"unknown exchange {exchange!r}; add to "
            "core.timezone.EXCHANGE_TIMEZONES"
        )
    return EXCHANGE_TIMEZONES[key]


# --------------------------------------------------------------------------
# Tz validation helpers
# --------------------------------------------------------------------------


class TimezoneMismatch(ValueError):
    """Two indices were combined with incompatible tz posture."""


def is_tz_aware(idx: Union[pd.DatetimeIndex, pd.Series, pd.Timestamp]) -> bool:
    """True iff the input has timezone information attached."""
    if isinstance(idx, pd.Series):
        idx = idx.index
    if isinstance(idx, pd.Timestamp):
        return idx.tz is not None
    if isinstance(idx, pd.DatetimeIndex):
        return idx.tz is not None
    raise TypeError(
        f"is_tz_aware expects pd.Timestamp / DatetimeIndex / Series, "
        f"got {type(idx).__name__}"
    )


def assert_compatible(
    a: Union[pd.DatetimeIndex, pd.Series, pd.Timestamp],
    b: Union[pd.DatetimeIndex, pd.Series, pd.Timestamp],
) -> None:
    """Raise :class:`TimezoneMismatch` if mixing tz-aware with tz-naive.

    Two tz-aware indices are accepted regardless of zone (pandas can
    convert between zones safely). Two tz-naive indices are accepted.
    Mixed posture raises.
    """
    aware_a = is_tz_aware(a)
    aware_b = is_tz_aware(b)
    if aware_a != aware_b:
        raise TimezoneMismatch(
            "cannot combine tz-aware with tz-naive datetime; "
            f"left aware={aware_a}, right aware={aware_b}. "
            "Localise the tz-naive side or strip the tz-aware side "
            "before combining."
        )


def localise_to_exchange(
    idx: pd.DatetimeIndex,
    exchange: str,
) -> pd.DatetimeIndex:
    """Localise a tz-naive index to the exchange's canonical tz.

    Raises:
        ValueError: when ``idx`` is already tz-aware.
        KeyError: when ``exchange`` is unknown.
    """
    if is_tz_aware(idx):
        raise ValueError(
            "localise_to_exchange expects a tz-naive index; "
            "use convert_to_exchange to switch zones."
        )
    return idx.tz_localize(tz_for_exchange(exchange))


def convert_to_exchange(
    idx: pd.DatetimeIndex,
    exchange: str,
) -> pd.DatetimeIndex:
    """Convert a tz-aware index to the exchange's canonical tz.

    Raises:
        ValueError: when ``idx`` is tz-naive.
        KeyError: when ``exchange`` is unknown.
    """
    if not is_tz_aware(idx):
        raise ValueError(
            "convert_to_exchange expects a tz-aware index; "
            "use localise_to_exchange to attach a zone."
        )
    return idx.tz_convert(tz_for_exchange(exchange))


def to_utc(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return ``idx`` in UTC. Localises tz-naive input to UTC first."""
    if is_tz_aware(idx):
        return idx.tz_convert("UTC")
    return idx.tz_localize("UTC")


__all__ = [
    "EXCHANGE_TIMEZONES",
    "TimezoneMismatch",
    "tz_for_exchange",
    "is_tz_aware",
    "assert_compatible",
    "localise_to_exchange",
    "convert_to_exchange",
    "to_utc",
]

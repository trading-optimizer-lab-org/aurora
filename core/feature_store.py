"""R181 - Point-in-time feature store and signal cache.

Stores per-symbol per-feature time series with explicit availability
times so a backtest cannot read a feature value computed after the
decision time. Cache keys hash the input signature so recomputing the
same feature from the same inputs yields the same content hash.

The store is in-memory; persistence is left to the caller (typical
deployments back it with parquet or arctic). The PIT discipline is what
matters here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureDefinition:
    """Schema record for one feature."""

    name: str
    version: str
    inputs: Tuple[str, ...]
    lookback: int
    owner: str = ""
    frequency: str = "daily"
    null_policy: str = "drop"  # "drop" | "ffill" | "raise"
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name must be non-empty")
        if not self.version:
            raise ValueError("version must be non-empty")
        if self.null_policy not in ("drop", "ffill", "raise"):
            raise ValueError(f"null_policy={self.null_policy!r} invalid")

    def code_hash(self) -> str:
        payload = {
            "name": self.name,
            "version": self.version,
            "inputs": list(self.inputs),
            "lookback": self.lookback,
            "frequency": self.frequency,
            "null_policy": self.null_policy,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class FeatureValue:
    """One feature value with explicit ``available_time``."""

    feature_name: str
    feature_version: str
    symbol: str
    decision_time: pd.Timestamp
    available_time: pd.Timestamp
    value: float
    inputs_hash: str

    def to_dict(self) -> dict:
        return {
            "feature_name": self.feature_name,
            "feature_version": self.feature_version,
            "symbol": self.symbol,
            "decision_time": self.decision_time.isoformat(),
            "available_time": self.available_time.isoformat(),
            "value": float(self.value),
            "inputs_hash": self.inputs_hash,
        }


class FeatureUnavailable(LookupError):
    """Raised when no feature value is available at the requested time."""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


@dataclass
class FeatureStore:
    """In-memory PIT-aware feature store."""

    _definitions: Dict[Tuple[str, str], FeatureDefinition] = field(
        default_factory=dict
    )
    # (feature_name, feature_version, symbol) -> List[FeatureValue]
    _values: Dict[Tuple[str, str, str], List[FeatureValue]] = field(
        default_factory=dict
    )

    # -- registration -------------------------------------------------------

    def register(
        self, definition: FeatureDefinition, *, replace: bool = False,
    ) -> None:
        key = (definition.name, definition.version)
        if not replace and key in self._definitions:
            raise ValueError(
                f"feature {definition.name}:{definition.version} "
                "already registered"
            )
        self._definitions[key] = definition

    def definition(self, name: str, version: str) -> FeatureDefinition:
        try:
            return self._definitions[(name, version)]
        except KeyError as exc:
            raise KeyError(
                f"no feature definition for {name}:{version}"
            ) from exc

    def list_features(self) -> List[Tuple[str, str]]:
        return sorted(self._definitions.keys())

    # -- writes -------------------------------------------------------------

    def put(self, value: FeatureValue) -> None:
        if value.available_time < value.decision_time:
            raise ValueError(
                "available_time cannot be earlier than decision_time"
            )
        if (value.feature_name, value.feature_version) not in self._definitions:
            raise KeyError(
                f"feature {value.feature_name}:{value.feature_version} "
                "is not registered"
            )
        key = (value.feature_name, value.feature_version, value.symbol)
        self._values.setdefault(key, []).append(value)
        self._values[key].sort(key=lambda v: (v.decision_time, v.available_time))

    def put_series(
        self,
        *,
        feature_name: str,
        feature_version: str,
        symbol: str,
        decision_times: Iterable[pd.Timestamp],
        available_times: Iterable[pd.Timestamp],
        values: Iterable[float],
        inputs_hash: str,
    ) -> None:
        decision_list = [pd.Timestamp(t) for t in decision_times]
        available_list = [pd.Timestamp(t) for t in available_times]
        values_list = list(values)
        if not (len(decision_list) == len(available_list) == len(values_list)):
            raise ValueError(
                "decision_times, available_times and values must align"
            )
        for dt, at, v in zip(decision_list, available_list, values_list):
            self.put(FeatureValue(
                feature_name=feature_name,
                feature_version=feature_version,
                symbol=symbol,
                decision_time=dt,
                available_time=at,
                value=float(v),
                inputs_hash=inputs_hash,
            ))

    # -- reads --------------------------------------------------------------

    def feature_at(
        self,
        *,
        feature_name: str,
        feature_version: str,
        symbol: str,
        decision_time: pd.Timestamp,
    ) -> FeatureValue:
        """Return the latest available value at ``decision_time``.

        Raises :class:`FeatureUnavailable` when no value is available
        because the lookup time precedes the earliest available_time.
        """
        decision_time = pd.Timestamp(decision_time)
        key = (feature_name, feature_version, symbol)
        series = self._values.get(key, [])
        # Filter by available_time <= decision_time AND decision_time of the
        # row <= the requested decision_time. We use the row's
        # available_time as the strict gate; a row that became visible
        # after the decision time leaks future information.
        candidates = [
            v for v in series if v.available_time <= decision_time
        ]
        if not candidates:
            raise FeatureUnavailable(
                f"no value for {feature_name}:{feature_version} "
                f"on {symbol} at {decision_time.isoformat()}"
            )
        # Pick the latest decision_time still at or before the requested
        # decision_time; fall back to the latest available row.
        eligible = [v for v in candidates if v.decision_time <= decision_time]
        return (eligible or candidates)[-1]

    def history(
        self, *, feature_name: str, feature_version: str, symbol: str,
    ) -> List[FeatureValue]:
        key = (feature_name, feature_version, symbol)
        return list(self._values.get(key, []))

    # -- diagnostics --------------------------------------------------------

    def missingness(
        self, *, feature_name: str, feature_version: str, symbol: str,
    ) -> int:
        """Count NaN values stored for the (feature, version, symbol)."""
        return sum(
            1 for v in self.history(
                feature_name=feature_name,
                feature_version=feature_version,
                symbol=symbol,
            )
            if not np.isfinite(v.value)
        )

    def content_hash(
        self, *, feature_name: str, feature_version: str, symbol: str,
    ) -> str:
        history = self.history(
            feature_name=feature_name,
            feature_version=feature_version,
            symbol=symbol,
        )
        payload = [v.to_dict() for v in history]
        blob = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------


def cache_key(
    feature: FeatureDefinition,
    inputs: Iterable[Tuple[str, str]],
    policy_hash: str,
) -> str:
    """Deterministic hash over feature definition + inputs + policy hash."""
    payload = {
        "feature": feature.code_hash(),
        "inputs": sorted(tuple(t) for t in inputs),
        "policy_hash": policy_hash,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = [
    "FeatureDefinition",
    "FeatureStore",
    "FeatureUnavailable",
    "FeatureValue",
    "cache_key",
]

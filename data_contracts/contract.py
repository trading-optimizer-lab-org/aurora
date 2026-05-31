"""Versioned data contract dataclasses.

A :class:`DataContract` is a frozen description of what a dataset must look
like before any backtest, GA run, validation gate or factory submit is
allowed to consume it. Contracts are content-hashed (``sha256`` over a
canonical JSON dump) so that downstream provenance can record exactly which
contract version was active at decision time.

Design notes
------------

* All dataclasses are ``frozen=True`` -- callers must use
  :func:`dataclasses.replace` (or build a fresh contract) to derive a new
  variant. Mutation raises ``FrozenInstanceError``.
* Tuples (not lists) for sequence fields keep equality / hashing
  deterministic across the test suite.
* ``contract_hash`` is a stable digest of the canonical JSON dump; it is
  what propagates through :class:`DataValidationResult`, the lineage
  record and any downstream snapshot manifest.
* The contract intentionally does NOT depend on pandas. The validator
  consumes the contract, but the contract itself is pure stdlib so it can
  be built, hashed and serialised in tests that have no DataFrame.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


CONTRACT_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# Field-level description
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractField:
    """One column declared in a :class:`DataContract`.

    Attributes:
        name: column name as it appears on the DataFrame.
        dtype_kind: high-level dtype family. One of ``"numeric"``,
            ``"integer"``, ``"datetime"``, ``"string"``, ``"bool"``.
        nullable: whether nulls are allowed for this column.
        positive_only: if ``True``, the validator rejects zero or negative
            values (e.g. price columns).
        is_price: marks the column as a price series for split-jump
            detection.
        description: free-form human description.
    """

    name: str
    dtype_kind: str = "numeric"
    nullable: bool = False
    positive_only: bool = False
    is_price: bool = False
    description: str = ""


# --------------------------------------------------------------------------
# Availability / point-in-time policy
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AvailabilityPolicy:
    """Point-in-time / bitemporal columns the dataset is expected to expose.

    A dataset is *bitemporal* when each row tracks both ``event_time``
    (when the world-event happened) and ``available_time`` (when our
    pipeline could have known about the row). Strategies and the factory
    must never read a row whose ``available_time`` is greater than the
    decision time -- doing so leaks future information.

    Attributes:
        event_time_col: column that records when the underlying event
            happened. Optional.
        available_time_col: column that records when the row became
            visible to the pipeline. The validator uses this column to
            enforce point-in-time access in
            :func:`aurora.data_contracts.validator.validate_dataframe`.
        ingested_time_col: column that records when the row hit our
            storage. Optional, used for lineage only.
        revision_time_col: column that records the latest revision time.
            Optional.
        require_pit_columns: when ``True`` the validator fails if any of
            the named columns is missing.
    """

    event_time_col: Optional[str] = None
    available_time_col: Optional[str] = None
    ingested_time_col: Optional[str] = None
    revision_time_col: Optional[str] = None
    require_pit_columns: bool = False


# --------------------------------------------------------------------------
# Corporate-action policy
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CorporateActionPolicy:
    """How the validator treats suspicious split-like jumps.

    ``severity`` controls how
    :func:`aurora.data_contracts.validator.validate_dataframe` reacts
    when a single bar-to-bar move on a price column exceeds
    ``split_jump_threshold``:

    * ``"warn"``: row is reported in
      :attr:`DataValidationResult.warnings`.
    * ``"fail"``: row is reported in :attr:`DataValidationResult.errors`
      and the result is marked as failed.
    * ``"ignore"``: detection is disabled. Use only when the dataset is
      pre-validated upstream.

    Attributes:
        split_jump_threshold: absolute log-return magnitude that flags a
            suspicious split-like jump (default ``0.5`` => ~65% move).
        severity: ``"warn"`` / ``"fail"`` / ``"ignore"``.
        impossible_return_threshold: absolute log-return that is
            considered always impossible (default ``2.3`` => ~10x move).
            Always escalates to a hard error regardless of ``severity``.
    """

    split_jump_threshold: float = 0.5
    severity: str = "warn"
    impossible_return_threshold: float = 2.3


# --------------------------------------------------------------------------
# DataContract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DataContract:
    """Frozen description of an acceptable dataset shape.

    The validator uses the contract to gate every input dataset before
    backtest / GA / validation / factory consumption. The contract is
    deterministically hashed via :attr:`contract_hash`.

    Attributes:
        name: short symbolic name (e.g. ``"sp500_daily_v1"``).
        version: semver-style version string.
        description: free-form human description.
        fields: tuple of declared :class:`ContractField` records.
        timestamp_col: name of the column / index that is the temporal
            anchor. The validator enforces monotonicity and uniqueness
            on this axis.
        timezone: ``"UTC"`` or any pandas-compatible tz name. Use ``None``
            to allow naive timestamps; mixed-timezone input still fails.
        allow_naive_timestamps: if ``True``, naive timestamps are
            accepted as long as they are consistent.
        max_staleness_days: maximum allowed gap between the dataset's
            last timestamp and the snapshot decision time. ``None``
            disables the check.
        availability: point-in-time policy. See
            :class:`AvailabilityPolicy`.
        corporate_actions: split-jump policy. See
            :class:`CorporateActionPolicy`.
        currency: declared currency for price fields, for cross-checks.
        exchange: declared primary exchange.
    """

    name: str
    version: str = CONTRACT_VERSION
    description: str = ""
    fields: Tuple[ContractField, ...] = field(default_factory=tuple)
    timestamp_col: str = "timestamp"
    timezone: Optional[str] = "UTC"
    allow_naive_timestamps: bool = False
    max_staleness_days: Optional[int] = None
    availability: AvailabilityPolicy = field(default_factory=AvailabilityPolicy)
    corporate_actions: CorporateActionPolicy = field(default_factory=CorporateActionPolicy)
    currency: Optional[str] = None
    exchange: Optional[str] = None

    @property
    def contract_hash(self) -> str:
        """Deterministic ``sha256`` over a canonical JSON dump."""
        return _hash_dict(asdict(self))

    @property
    def required_columns(self) -> Tuple[str, ...]:
        """Tuple of required column names declared on the contract."""
        return tuple(f.name for f in self.fields if not f.nullable)

    @property
    def price_columns(self) -> Tuple[str, ...]:
        """Tuple of column names that the contract marks as price series."""
        return tuple(f.name for f in self.fields if f.is_price)

    def field_by_name(self, name: str) -> Optional[ContractField]:
        """Return the :class:`ContractField` for ``name`` or ``None``."""
        for f in self.fields:
            if f.name == name:
                return f
        return None


# --------------------------------------------------------------------------
# Validation result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DataValidationResult:
    """Outcome of running the validator against a DataFrame.

    Attributes:
        passed: ``True`` if no errors were emitted.
        errors: list of human-readable hard-failure messages.
        warnings: list of human-readable advisory messages.
        snapshot_hash: optional hash of the validated dataset snapshot
            (echoed by the caller so provenance has a single source of
            truth).
        contract_hash: hash of the :class:`DataContract` used for
            validation. Always populated when validation runs.
        validator_version: version string for the validator that
            produced the result. See
            :data:`aurora.data_contracts.validator.VALIDATOR_VERSION`.
        decision_outcome: free-form summary string written into the
            lineage record. Empty when not yet decided.
    """

    passed: bool
    errors: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    snapshot_hash: Optional[str] = None
    contract_hash: Optional[str] = None
    validator_version: str = ""
    decision_outcome: str = ""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _hash_dict(d: Dict[str, Any]) -> str:
    """Stable sha256 over ``json.dumps(d, sort_keys=True, default=str)``."""
    payload = json.dumps(d, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "CONTRACT_VERSION",
    "AvailabilityPolicy",
    "ContractField",
    "CorporateActionPolicy",
    "DataContract",
    "DataValidationResult",
]

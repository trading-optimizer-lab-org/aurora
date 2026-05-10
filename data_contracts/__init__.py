"""aurora.data_contracts -- versioned dataset contracts and validators.

Phase 1 of the data integrity programme (Candidate C). Provides:

* :class:`DataContract`, :class:`ContractField`, :class:`AvailabilityPolicy`,
  :class:`CorporateActionPolicy`, :class:`DataValidationResult` -- the
  frozen data shape for an acceptable dataset.
* :func:`validate_dataframe` -- the gate that backtest, GA, validation and
  factory submit call before consuming a DataFrame.
* :class:`SecurityMaster` / :class:`SecurityMasterRecord` -- registry of
  instrument identity (vendor, broker, exchange, listing window).
* :class:`CorporateActionRecord`, :func:`verify_split_adjustment`,
  :func:`verify_dividend_adjustment` -- corporate-action records plus
  consistency checkers.
* :class:`DataLineage` -- per-decision lineage record.
"""
from __future__ import annotations

from aurora.data_contracts.contract import (
    CONTRACT_VERSION,
    AvailabilityPolicy,
    ContractField,
    CorporateActionPolicy,
    DataContract,
    DataValidationResult,
)
from aurora.data_contracts.calendars import (
    CalendarRecord,
    CalendarRegistry,
    MarketCalendarKind,
    expected_sessions,
    validate_series,
)
from aurora.data_contracts.corporate_actions import (
    KNOWN_ACTION_TYPES,
    AdjustmentCheck,
    AdjustmentStatus,
    CorporateActionRecord,
    report_corporate_actions,
    verify_dividend_adjustment,
    verify_split_adjustment,
)
from aurora.data_contracts.instrument_master import (
    AmbiguousIdentityError,
    IdentityResolver,
    InstrumentProvenance,
    InstrumentRecord,
    expand_provider_aliases,
    normalise_symbol,
    seed_resolver,
)
from aurora.data_contracts.lineage import LINEAGE_VERSION, DataLineage
from aurora.data_contracts.liquidity import (
    LiquidityRecord,
    LiquidityValidationGate,
    compute_liquidity_features,
    flag_thin_symbols,
)
from aurora.data_contracts.provider_terms import (
    ProviderTerms,
    ProviderTermsBlocked,
    ProviderTermsRegistry,
    UsageLabel,
    default_registry as default_provider_terms_registry,
)
from aurora.data_contracts.quality import (
    CoverageReport,
    DataQualityReport,
    QualityDecision,
    QuarantineEntry,
    QuarantineLedger,
    build_coverage,
    score_dataframe,
)
from aurora.data_contracts.security_master import (
    SecurityMaster,
    SecurityMasterRecord,
)
from aurora.data_contracts.validator import (
    UTC,
    VALIDATOR_VERSION,
    hash_dataframe,
    validate_dataframe,
)

__all__ = [
    "CONTRACT_VERSION",
    "LINEAGE_VERSION",
    "VALIDATOR_VERSION",
    "AdjustmentCheck",
    "AdjustmentStatus",
    "AmbiguousIdentityError",
    "AvailabilityPolicy",
    "CalendarRecord",
    "CalendarRegistry",
    "ContractField",
    "CorporateActionPolicy",
    "CorporateActionRecord",
    "CoverageReport",
    "DataContract",
    "DataLineage",
    "DataQualityReport",
    "DataValidationResult",
    "IdentityResolver",
    "InstrumentProvenance",
    "InstrumentRecord",
    "KNOWN_ACTION_TYPES",
    "LiquidityRecord",
    "LiquidityValidationGate",
    "MarketCalendarKind",
    "ProviderTerms",
    "ProviderTermsBlocked",
    "ProviderTermsRegistry",
    "QualityDecision",
    "QuarantineEntry",
    "QuarantineLedger",
    "SecurityMaster",
    "SecurityMasterRecord",
    "UsageLabel",
    "UTC",
    "build_coverage",
    "compute_liquidity_features",
    "default_provider_terms_registry",
    "expand_provider_aliases",
    "expected_sessions",
    "flag_thin_symbols",
    "normalise_symbol",
    "report_corporate_actions",
    "score_dataframe",
    "seed_resolver",
    "hash_dataframe",
    "validate_dataframe",
    "validate_series",
    "verify_dividend_adjustment",
    "verify_split_adjustment",
]

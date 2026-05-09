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
from aurora.data_contracts.corporate_actions import (
    KNOWN_ACTION_TYPES,
    AdjustmentCheck,
    CorporateActionRecord,
    verify_dividend_adjustment,
    verify_split_adjustment,
)
from aurora.data_contracts.lineage import LINEAGE_VERSION, DataLineage
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
    "AvailabilityPolicy",
    "ContractField",
    "CorporateActionPolicy",
    "CorporateActionRecord",
    "DataContract",
    "DataLineage",
    "DataValidationResult",
    "KNOWN_ACTION_TYPES",
    "SecurityMaster",
    "SecurityMasterRecord",
    "UTC",
    "hash_dataframe",
    "validate_dataframe",
    "verify_dividend_adjustment",
    "verify_split_adjustment",
]

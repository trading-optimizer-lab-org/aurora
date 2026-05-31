"""Data-contract lineage record.

A :class:`DataLineage` record is the small per-decision provenance object
that travels alongside every dataset entering a backtest, GA run,
validation gate or factory submission. It is intentionally self-contained
and JSON-friendly so it can be appended to an audit chain or written to
the run report without coupling to any storage backend.

This module deliberately does NOT touch
:mod:`aurora.dataeng.data_lineage`, which is a different scope
(graph-based dataset transformations). That module remains the home for
"how did this dataset get built across many transformations".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple


LINEAGE_VERSION = "1.0.0"


@dataclass(frozen=True)
class DataLineage:
    """Per-decision lineage record bound to a data-contract validation.

    Attributes:
        input_dataset_hash: caller-provided sha256 of the upstream dataset
            (e.g. the parquet snapshot).
        transformation_chain: ordered tuple of transformation tags, oldest
            first. Free-form strings (e.g. ``"adjust_splits"``,
            ``"resample_daily"``).
        code_version: version string of the consuming code (commit sha or
            semver).
        contract_version: version of the contract used at validation
            time.
        snapshot_hash: hash of the validated DataFrame snapshot, i.e. the
            output of ``hash_dataframe``.
        validator_version: validator version that produced the
            corresponding :class:`DataValidationResult`.
        decision_outcome: human-readable summary of what was decided
            (e.g. ``"accepted"``, ``"rejected: stale snapshot"``).
        contract_hash: hash of the :class:`DataContract`. Optional so the
            record can also be used in contexts where the validator is
            run with a contract-less mode.
        policy_hash: optional propagated ``ProtocolPolicy.policy_hash``.
    """

    input_dataset_hash: str
    transformation_chain: Tuple[str, ...]
    code_version: str
    contract_version: str
    snapshot_hash: str
    validator_version: str
    decision_outcome: str
    contract_hash: Optional[str] = None
    policy_hash: Optional[str] = None
    lineage_version: str = field(default=LINEAGE_VERSION)

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain ``dict`` round-trippable with :meth:`from_dict`.

        ``transformation_chain`` is dumped as a list (JSON has no tuple).
        """
        d = asdict(self)
        d["transformation_chain"] = list(self.transformation_chain)
        return d

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DataLineage":
        """Round-trip from :meth:`to_dict` output.

        Unknown keys are ignored; missing keys raise ``KeyError`` for the
        required fields and ``None`` for the optional ones. Lists are
        coerced back into tuples.
        """
        chain = payload.get("transformation_chain", ())
        return cls(
            input_dataset_hash=payload["input_dataset_hash"],
            transformation_chain=tuple(chain),
            code_version=payload["code_version"],
            contract_version=payload["contract_version"],
            snapshot_hash=payload["snapshot_hash"],
            validator_version=payload["validator_version"],
            decision_outcome=payload["decision_outcome"],
            contract_hash=payload.get("contract_hash"),
            policy_hash=payload.get("policy_hash"),
            lineage_version=payload.get("lineage_version", LINEAGE_VERSION),
        )


__all__ = ["DataLineage", "LINEAGE_VERSION"]

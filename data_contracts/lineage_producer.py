"""End-to-end :class:`DataLineage` producer.

A *lineage producer* records each stage of a data pipeline (raw fetch ->
adjustment -> snapshot -> strategy consumption) by appending a
transformation tag to the chain. It returns a fresh
:class:`DataLineage` (frozen) — the previous record is left untouched.

The :class:`SnapshotStoreLineageWrapper` is a thin adapter around
:class:`aurora.core.snapshots.SnapshotStore` that auto-records lineage
entries for ``freeze`` and ``load`` calls without changing the store's
public API. Existing call sites work unmodified; lineage-aware callers
go through the wrapper to get the chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from aurora.data_contracts.lineage import DataLineage, LINEAGE_VERSION


if TYPE_CHECKING:  # pragma: no cover -- type-only
    import pandas as pd

    from aurora.core.snapshots import DataSnapshot, SnapshotStore


def record_pipeline_step(
    prior_lineage: Optional[DataLineage],
    transform_name: str,
    *,
    output_hash: str,
    contract_hash: Optional[str] = None,
    contract_version: Optional[str] = None,
    code_version: Optional[str] = None,
    validator_version: Optional[str] = None,
    decision_outcome: Optional[str] = None,
    policy_hash: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> DataLineage:
    """Append ``transform_name`` to a lineage chain.

    Args:
        prior_lineage: previous :class:`DataLineage` in the chain, or
            ``None`` to start a fresh chain.
        transform_name: short tag for the transform (e.g.
            ``"adjust_splits"``, ``"snapshot_freeze"``,
            ``"strategy_consume"``).
        output_hash: sha256 of the dataset *after* the transform.
        contract_hash: optional contract hash to propagate.
        contract_version: contract version string. Defaults to the prior
            value or empty.
        code_version: code-version tag for the transform. Defaults to
            the prior value or empty.
        validator_version: validator version. Defaults to the prior
            value or empty.
        decision_outcome: free-form decision string. Defaults to
            ``"pipeline_step:<transform_name>"``.
        policy_hash: ProtocolPolicy hash to propagate. Defaults to the
            prior value.
        params: params attached to the transform. Stored as an extra
            transformation tag of the form
            ``"<transform_name>(<sorted-key=value>...)"`` so the chain
            stays a flat tuple of strings (matching the dataclass shape)
            but parameters survive the appendage.

    Returns:
        New :class:`DataLineage` with the chain extended.
    """
    if prior_lineage is None:
        chain: Tuple[str, ...] = ()
        prior_input = output_hash
        prior_contract_version = ""
        prior_code = ""
        prior_validator = ""
        prior_policy: Optional[str] = None
        prior_contract_hash = None
    else:
        chain = prior_lineage.transformation_chain
        prior_input = prior_lineage.input_dataset_hash
        prior_contract_version = prior_lineage.contract_version
        prior_code = prior_lineage.code_version
        prior_validator = prior_lineage.validator_version
        prior_policy = prior_lineage.policy_hash
        prior_contract_hash = prior_lineage.contract_hash

    tag = transform_name
    if params:
        kvs = ",".join(f"{k}={params[k]!r}" for k in sorted(params))
        tag = f"{transform_name}({kvs})"

    return DataLineage(
        input_dataset_hash=prior_input,
        transformation_chain=chain + (tag,),
        code_version=code_version if code_version is not None else prior_code,
        contract_version=(
            contract_version
            if contract_version is not None
            else prior_contract_version
        ),
        snapshot_hash=output_hash,
        validator_version=(
            validator_version
            if validator_version is not None
            else prior_validator
        ),
        decision_outcome=(
            decision_outcome
            if decision_outcome is not None
            else f"pipeline_step:{transform_name}"
        ),
        contract_hash=(
            contract_hash if contract_hash is not None else prior_contract_hash
        ),
        policy_hash=policy_hash if policy_hash is not None else prior_policy,
    )


# --------------------------------------------------------------------------
# SnapshotStore adapter
# --------------------------------------------------------------------------


@dataclass
class SnapshotStoreLineageWrapper:
    """Thin adapter that records a :class:`DataLineage` per snapshot op.

    The wrapper does not change ``SnapshotStore``'s public API — it
    forwards ``freeze`` / ``load`` to the wrapped store and additionally
    builds a lineage entry recording the operation. The most recent
    lineage is exposed via :attr:`last_lineage`. The full chain is in
    :attr:`chain` (oldest first).
    """

    store: "SnapshotStore"
    code_version: str = ""
    contract_hash: Optional[str] = None
    contract_version: str = ""
    validator_version: str = ""
    chain: list = field(default_factory=list)

    @property
    def last_lineage(self) -> Optional[DataLineage]:
        return self.chain[-1] if self.chain else None

    def freeze(
        self,
        prices: "pd.Series",
        symbol: str,
        provenance: str,
        *,
        locked: bool = False,
        config_hash: Optional[str] = None,
        prior_lineage: Optional[DataLineage] = None,
    ) -> "DataSnapshot":
        """Freeze ``prices`` and append a lineage entry."""
        snap = self.store.freeze(
            prices, symbol, provenance, locked=locked, config_hash=config_hash
        )
        prior = prior_lineage if prior_lineage is not None else self.last_lineage
        lineage = record_pipeline_step(
            prior,
            "snapshot_freeze",
            output_hash=snap.sha256,
            contract_hash=self.contract_hash,
            contract_version=self.contract_version,
            code_version=self.code_version,
            validator_version=self.validator_version,
            decision_outcome=f"snapshot_freeze:{symbol}",
            policy_hash=snap.policy_hash,
            params={"symbol": symbol, "provenance": provenance, "locked": locked},
        )
        self.chain.append(lineage)
        return snap

    def load(self, sha256: str) -> Tuple["pd.Series", "DataSnapshot"]:
        """Load ``sha256`` from the wrapped store and append a lineage entry."""
        prices, snap = self.store.load(sha256)
        lineage = record_pipeline_step(
            self.last_lineage,
            "snapshot_load",
            output_hash=snap.sha256,
            contract_hash=self.contract_hash,
            contract_version=self.contract_version,
            code_version=self.code_version,
            validator_version=self.validator_version,
            decision_outcome=f"snapshot_load:{snap.symbol}",
            policy_hash=snap.policy_hash,
            params={"sha256": sha256},
        )
        self.chain.append(lineage)
        return prices, snap


def producer_for_snapshot_store(
    snapshot_store: "SnapshotStore",
    *,
    code_version: str = "",
    contract_hash: Optional[str] = None,
    contract_version: str = "",
    validator_version: str = "",
) -> SnapshotStoreLineageWrapper:
    """Build a :class:`SnapshotStoreLineageWrapper` around ``snapshot_store``.

    The wrapped store's API is unchanged. Use the wrapper instead of the
    raw store wherever you want lineage recorded; both end up writing
    the same parquet+sqlite content.
    """
    return SnapshotStoreLineageWrapper(
        store=snapshot_store,
        code_version=code_version,
        contract_hash=contract_hash,
        contract_version=contract_version,
        validator_version=validator_version,
    )


__all__ = [
    "LINEAGE_VERSION",
    "SnapshotStoreLineageWrapper",
    "producer_for_snapshot_store",
    "record_pipeline_step",
]

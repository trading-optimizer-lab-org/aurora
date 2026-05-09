"""Evidence pack and access guards for the research-agent layer (Phase 7 / Candidate G).

An :class:`EvidencePack` carries only protocol-approved inputs:

- snapshot, policy, validation, strategy and data-contract hashes
- audit references and source report paths

Agents may read evidence packs and produce comments. They MUST NOT
fetch arbitrary data, read locked OOS / FORWARD partitions, submit
broker actions, read secrets, or modify code. Hash mismatches or
forbidden access attempts fail closed via the exception classes below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MissingEvidenceError(Exception):
    """Raised when an agent tries to act without the required evidence."""


class HashMismatchError(Exception):
    """Raised when an evidence-pack hash does not match the recomputed value."""


class ForbiddenAccessError(Exception):
    """Raised when an agent attempts to access OOS_LOCKED / FORWARD data or a
    forbidden tool. Fail-closed by design.
    """


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------


_LOCKED_PARTITION_TOKENS: Tuple[str, ...] = (
    "OOS_LOCKED",
    "FORWARD",
)


@dataclass(frozen=True)
class EvidencePack:
    """Immutable bundle of protocol-approved evidence handed to agents.

    Every field is optional at construction so the pack can express partial
    evidence, but :meth:`verify_hashes` fails closed if any hash field is
    ``None`` when a real value is expected. Agents MUST cite the snapshot
    hash, policy hash and validation hash on every material claim; the pack
    is the single source of truth for what they may quote.
    """

    snapshot_hash: Optional[str] = None
    policy_hash: Optional[str] = None
    validation_hash: Optional[str] = None
    strategy_hash: Optional[str] = None
    data_contract_hash: Optional[str] = None
    audit_references: Tuple[str, ...] = ()
    source_report_paths: Tuple[str, ...] = ()
    created_at_iso: str = ""

    # ---------------------------------------------------------------
    # Hash verification
    # ---------------------------------------------------------------
    def verify_hashes(self, actual_hashes: Mapping[str, Optional[str]]) -> bool:
        """Compare each non-None hash field to ``actual_hashes[<field>]``.

        Returns ``False`` (fail-closed) if any of the following holds:

        - a field on the pack is ``None`` (missing evidence)
        - the field is not present in ``actual_hashes``
        - the value in ``actual_hashes`` is ``None``
        - the values do not match (case-sensitive equality)

        Returns ``True`` only when every hash field on the pack is present
        and matches the recomputed actual value. Empty packs (no hash
        fields populated) return ``False``: missing evidence is not a pass.
        """
        hash_fields = (
            "snapshot_hash",
            "policy_hash",
            "validation_hash",
            "strategy_hash",
            "data_contract_hash",
        )

        any_set = False
        for field_name in hash_fields:
            pack_value = getattr(self, field_name)
            if pack_value is None:
                # Missing evidence is not a pass.
                return False
            any_set = True
            actual_value = actual_hashes.get(field_name)
            if actual_value is None:
                return False
            if pack_value != actual_value:
                return False
        return any_set


def assert_no_oos_access(pack: EvidencePack) -> None:
    """Raise :class:`ForbiddenAccessError` if ``pack`` references locked data.

    The check is a string match against ``OOS_LOCKED`` and ``FORWARD`` in
    every audit reference and source report path. Agents must use the
    same OOSGuard ceremony as any other caller; the evidence-pack layer
    refuses to even hand them references to locked partitions.
    """
    haystack: Tuple[str, ...] = pack.audit_references + pack.source_report_paths
    for entry in haystack:
        if not isinstance(entry, str):
            continue
        upper = entry.upper()
        for token in _LOCKED_PARTITION_TOKENS:
            if token in upper:
                raise ForbiddenAccessError(
                    f"evidence pack references locked partition {token!r}: {entry!r}"
                )


__all__ = [
    "EvidencePack",
    "MissingEvidenceError",
    "HashMismatchError",
    "ForbiddenAccessError",
    "assert_no_oos_access",
]

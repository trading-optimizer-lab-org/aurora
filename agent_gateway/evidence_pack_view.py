"""R176 -- Read-only role-restricted view over an :class:`EvidencePack`.

A view is constructed from a pack plus an explicit set of allowed
section names (typically supplied by an
:class:`aurora.agent_gateway.agent_roles.AgentCapability`). Reading
anything else raises :class:`EvidenceAccessDenied`. The view also
re-checks the pack's stored ``pack_hash`` on every read; if the pack
content was tampered with after the view was constructed, every
subsequent read raises :class:`EvidenceHashMismatch`.

The view is read-only:

* No ``__setattr__`` after construction.
* :meth:`get_section` returns deep copies for sequence/dict fields so a
  caller mutating its return value cannot punch through to the
  underlying pack object.
* There are no submit / cancel / approve / promote methods.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any, FrozenSet, Iterable

from aurora.reporting.evidence_pack import EvidencePack, compute_pack_hash


class EvidenceAccessDenied(Exception):
    """Raised when a role asks for a section it is not allowed to read."""


class EvidenceHashMismatch(Exception):
    """Raised when the underlying pack's content no longer hashes to ``pack_hash``."""


class EvidencePackView:
    """Read-only role-restricted facade over an :class:`EvidencePack`.

    Args:
        pack: the underlying evidence pack. The view captures the pack
            and its stored ``pack_hash`` at construction time and
            re-verifies the hash on every read.
        allowed_sections: iterable of section names this role may read.
            Anything else raises :class:`EvidenceAccessDenied`.

    The view never exposes broker-action methods. There is no
    ``submit_order`` / ``cancel_order`` / ``approve`` / ``promote``
    surface anywhere on this class or its parents.
    """

    __slots__ = ("_pack", "_allowed", "_pack_hash_at_bind")

    def __init__(
        self, pack: EvidencePack, allowed_sections: Iterable[str],
    ) -> None:
        if not isinstance(pack, EvidencePack):
            raise TypeError(
                "EvidencePackView requires an EvidencePack instance, "
                f"got {type(pack).__name__}"
            )
        # Verify the pack hashes correctly to its stored value at bind
        # time. A mismatch at construction means the caller handed us a
        # tampered pack -- fail closed before we ever read a field.
        stored = pack.pack_hash or ""
        recomputed = compute_pack_hash(pack)
        if stored and stored != recomputed:
            raise EvidenceHashMismatch(
                f"pack_hash mismatch at bind: stored={stored[:12]} "
                f"computed={recomputed[:12]}"
            )
        # Use object.__setattr__ to populate slots; further sets are
        # blocked by ``__setattr__`` below.
        object.__setattr__(self, "_pack", pack)
        object.__setattr__(self, "_allowed",
                           frozenset(str(s) for s in allowed_sections))
        # Pin the hash we expect every subsequent read to recompute to.
        # If the pack was constructed without one (some test fixtures
        # do this), fall back to the computed hash for the bind moment.
        object.__setattr__(self, "_pack_hash_at_bind",
                           stored or recomputed)

    # ------------------------------------------------------------------
    # Read-only contract
    # ------------------------------------------------------------------
    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(
            f"EvidencePackView is read-only; cannot set attribute {name!r}"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"EvidencePackView is read-only; cannot delete attribute {name!r}"
        )

    # ------------------------------------------------------------------
    # Pack-hash binding
    # ------------------------------------------------------------------
    @property
    def pack_hash(self) -> str:
        """The pack hash captured when the view was bound to a pack."""
        return self._pack_hash_at_bind

    @property
    def allowed_sections(self) -> FrozenSet[str]:
        """The frozen set of section names this view is permitted to read."""
        return self._allowed

    def _verify_hash(self) -> None:
        """Re-hash the underlying pack and compare to the bound hash."""
        recomputed = compute_pack_hash(self._pack)
        if recomputed != self._pack_hash_at_bind:
            raise EvidenceHashMismatch(
                f"pack content changed since view was bound: "
                f"bound={self._pack_hash_at_bind[:12]} "
                f"now={recomputed[:12]}"
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get_section(self, name: str) -> Any:
        """Return a deep copy of section ``name`` if the role may read it.

        Raises:
            :class:`EvidenceAccessDenied` if the section is not in
                ``allowed_sections``.
            :class:`EvidenceHashMismatch` if the pack's content hash no
                longer matches the value bound at construction.
        """
        if name not in self._allowed:
            raise EvidenceAccessDenied(
                f"section {name!r} is not in this role's allowlist"
            )
        self._verify_hash()
        if not hasattr(self._pack, name):
            raise EvidenceAccessDenied(
                f"section {name!r} does not exist on the pack"
            )
        # Deep copy so any caller mutation cannot reach the underlying
        # pack object even if ``EvidencePack`` were not frozen.
        return copy.deepcopy(getattr(self._pack, name))

    def has_section(self, name: str) -> bool:
        """True iff ``name`` is allowed AND present on the pack."""
        return name in self._allowed and hasattr(self._pack, name)

    def evidence_ids(self) -> dict:
        """Return the citation envelope a reviewer must echo back.

        These ids are the citation surface a reviewer's output is
        validated against. Provenance fields ride in every role's
        allowlist by construction.
        """
        self._verify_hash()
        return {
            "pack_id": self._pack.pack_id,
            "pack_hash": self._pack.pack_hash or self._pack_hash_at_bind,
            "policy_hash": self._pack.policy_hash,
            "snapshot_hash": self._pack.snapshot_hash,
            "subject_id": self._pack.subject_id,
        }

    def snapshot(self) -> dict:
        """Return a dict of all allowed sections (deep-copied).

        Useful for handing the role-restricted view to a stub LLM
        callable in tests.
        """
        self._verify_hash()
        out: dict = {}
        for section in self._allowed:
            if hasattr(self._pack, section):
                out[section] = copy.deepcopy(getattr(self._pack, section))
        return out


__all__ = [
    "EvidencePackView",
    "EvidenceAccessDenied",
    "EvidenceHashMismatch",
]

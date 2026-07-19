"""Manifest-bound, single-use authorization for an irreversible locked evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets

import pandas as pd


LOCKED_START = pd.Timestamp("2021-01-01")
_ISSUER_SECRET = secrets.token_hex(32)


@dataclass
class LockedDataAuthorization:
    """Capability issued only after a frozen manifest has been verified."""

    candidate_id: str
    manifest_sha256: str
    implementation_commit: str
    locked_end: pd.Timestamp
    _issuer_secret: str = field(repr=False)
    _consumed: bool = field(default=False, init=False, repr=False)

    @property
    def consumed(self) -> bool:
        return self._consumed


def issue_locked_data_authorization(
    *,
    candidate_id: str,
    manifest_sha256: str,
    implementation_commit: str,
    locked_end: str,
) -> LockedDataAuthorization:
    end = pd.Timestamp(locked_end).normalize()
    if end < LOCKED_START:
        raise ValueError("locked end precedes locked boundary")
    return LockedDataAuthorization(
        candidate_id=str(candidate_id),
        manifest_sha256=str(manifest_sha256),
        implementation_commit=str(implementation_commit),
        locked_end=end,
        _issuer_secret=_ISSUER_SECRET,
    )


def _validate_capability(
    authorization: LockedDataAuthorization | None,
) -> LockedDataAuthorization:
    if (
        authorization is None
        or not isinstance(authorization, LockedDataAuthorization)
        or authorization._issuer_secret != _ISSUER_SECRET
    ):
        raise ValueError("locked data requires a verified frozen authorization")
    return authorization


def consume_locked_evaluation(
    authorization: LockedDataAuthorization | None,
    *,
    candidate_id: str,
    end: pd.Timestamp,
) -> LockedDataAuthorization:
    capability = _validate_capability(authorization)
    if capability._consumed:
        raise ValueError("locked authorization was already consumed")
    if str(candidate_id) != capability.candidate_id:
        raise ValueError("locked authorization candidate mismatch")
    normalized_end = pd.Timestamp(end).normalize()
    if normalized_end < LOCKED_START or normalized_end > capability.locked_end:
        raise ValueError("locked evaluation end is outside frozen manifest")
    capability._consumed = True
    return capability


def assert_locked_access(
    authorization: LockedDataAuthorization | None,
    *,
    latest_date: pd.Timestamp,
) -> None:
    capability = _validate_capability(authorization)
    if not capability._consumed:
        raise ValueError("locked authorization has not been consumed")
    if pd.Timestamp(latest_date).normalize() > capability.locked_end:
        raise ValueError("locked data exceeds frozen manifest end")

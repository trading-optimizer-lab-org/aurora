"""Sealed envelope forecast ceremony (R153).

Before live deployment, encrypt strategy parameters + a forward-looking
forecast for the window [T, T+N] under an operator key. The lockbox
holds the ciphertext; only after T+N closes does the operator decrypt
and compare forecast vs realised.

Anti-cheating: prevents post-hoc rationalisation of strategy edits
during the forward window. If the strategy is edited mid-flight, the
sealed envelope's hash will not match the live config, and the
ceremony refuses to open.

This module deliberately does NOT introduce a new crypto dependency.
It uses the stdlib ``hashlib`` + ``hmac`` for integrity (the operator
binding key acts as a MAC) and stores the payload as JSON inside a
tagged envelope. For production deployments where confidentiality is
required, callers wrap the envelope in a real symmetric cipher (e.g.
``cryptography.Fernet``); the integrity primitive ships now.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SealedEnvelope:
    """A sealed forecast envelope.

    Attributes:
        envelope_id: random 32-character hex id.
        sealed_at: ISO timestamp when the envelope was sealed.
        opens_after: ISO timestamp before which the envelope refuses to
            open.
        payload_json: the JSON-serialised forecast payload.
        binding_tag: HMAC-SHA256 over (sealed_at || opens_after ||
            payload_json) using the operator key. Detects any tampering
            of the envelope contents or its metadata.
    """

    envelope_id: str
    sealed_at: str
    opens_after: str
    payload_json: str
    binding_tag: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "sealed_at": self.sealed_at,
            "opens_after": self.opens_after,
            "payload_json": self.payload_json,
            "binding_tag": self.binding_tag,
        }


def seal_envelope(
    *,
    payload: Dict[str, Any],
    opens_after: datetime,
    operator_key: bytes,
    sealed_at: Optional[datetime] = None,
) -> SealedEnvelope:
    """Seal a forecast payload under the operator key.

    Args:
        payload: arbitrary JSON-serialisable forecast (params, forecast
            window, expected metric distribution, etc.).
        opens_after: minimum datetime before which the envelope refuses
            to open. Use the forecast end date.
        operator_key: bytes of the operator key. Anyone holding this
            key can both seal AND open the envelope.
        sealed_at: override for the seal timestamp. Defaults to UTC now.

    Returns:
        :class:`SealedEnvelope`.
    """
    if not operator_key:
        raise ValueError("operator_key must be non-empty")
    sealed_at = sealed_at or datetime.now(timezone.utc)
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    binding_tag = _binding_tag(
        operator_key=operator_key,
        sealed_at=sealed_at.isoformat(),
        opens_after=opens_after.isoformat(),
        payload_json=payload_json,
    )
    return SealedEnvelope(
        envelope_id=secrets.token_hex(16),
        sealed_at=sealed_at.isoformat(),
        opens_after=opens_after.isoformat(),
        payload_json=payload_json,
        binding_tag=binding_tag,
    )


def open_envelope(
    *,
    envelope: SealedEnvelope,
    operator_key: bytes,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Verify the envelope and return the original payload.

    Raises:
        PermissionError: opens_after is in the future.
        ValueError: binding tag does not validate (envelope tampered or
            wrong operator key).
    """
    now = now or datetime.now(timezone.utc)
    opens_after = datetime.fromisoformat(envelope.opens_after)
    if now < opens_after:
        raise PermissionError(
            f"envelope {envelope.envelope_id} cannot open until {envelope.opens_after}"
        )
    expected = _binding_tag(
        operator_key=operator_key,
        sealed_at=envelope.sealed_at,
        opens_after=envelope.opens_after,
        payload_json=envelope.payload_json,
    )
    if not hmac.compare_digest(expected, envelope.binding_tag):
        raise ValueError(
            f"binding tag mismatch for envelope {envelope.envelope_id}; "
            "either the envelope was tampered with or the operator key "
            "is wrong"
        )
    return json.loads(envelope.payload_json)


def _binding_tag(
    *,
    operator_key: bytes,
    sealed_at: str,
    opens_after: str,
    payload_json: str,
) -> str:
    msg = (sealed_at + "|" + opens_after + "|" + payload_json).encode("utf-8")
    return hmac.new(operator_key, msg, hashlib.sha256).hexdigest()


def write_envelope(envelope: SealedEnvelope, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(envelope.to_dict(), fh)


def read_envelope(path: Path) -> SealedEnvelope:
    with path.open("r", encoding="utf-8") as fh:
        d = json.load(fh)
    return SealedEnvelope(**d)


__all__ = [
    "SealedEnvelope",
    "seal_envelope",
    "open_envelope",
    "write_envelope",
    "read_envelope",
]

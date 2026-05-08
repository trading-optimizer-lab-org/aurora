"""Strategy spec verification chain (R44).

Today the factory accepts a `StrategySpec` from any caller. There is
no signature chain proving that a spec came from a trusted developer.
This module ships an opt-in signing primitive:

- developer signs the spec_hash with an HMAC operator key,
- the factory verifies the signature against a registered key set,
- the gateway audit chain records the signing identity.

Same crypto pattern as :mod:`agent_gateway.sealed_envelope` (R153):
HMAC-SHA256 over a canonical JSON projection of the spec. Stdlib only.
For deployments that need asymmetric signing, swap the verifier for an
ed25519 implementation; the surface is the same.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional


@dataclass(frozen=True)
class SpecSignature:
    """A signed spec_hash + the identity that signed it."""

    signer_id: str
    spec_hash: str
    signature: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signer_id": self.signer_id,
            "spec_hash": self.spec_hash,
            "signature": self.signature,
        }


def canonical_spec_hash(spec_payload: Mapping[str, Any]) -> str:
    """Stable SHA256 over canonical JSON of the spec payload.

    The same spec payload always hashes to the same value -- the
    canonicaliser sorts keys and uses tight separators.
    """
    canonical = json.dumps(spec_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_spec(
    *,
    signer_id: str,
    spec_payload: Mapping[str, Any],
    operator_key: bytes,
) -> SpecSignature:
    """Mint a SpecSignature over the canonical spec hash."""
    if not signer_id:
        raise ValueError("signer_id must be non-empty")
    if not operator_key:
        raise ValueError("operator_key must be non-empty")
    spec_hash = canonical_spec_hash(spec_payload)
    msg = (signer_id + "|" + spec_hash).encode("utf-8")
    signature = hmac.new(operator_key, msg, hashlib.sha256).hexdigest()
    return SpecSignature(
        signer_id=signer_id,
        spec_hash=spec_hash,
        signature=signature,
    )


def verify_spec(
    *,
    signature: SpecSignature,
    spec_payload: Mapping[str, Any],
    key_registry: Mapping[str, bytes],
) -> None:
    """Raise if the signature is invalid; return otherwise.

    Args:
        signature: the SpecSignature attached to the spec.
        spec_payload: the canonical spec dict the signature claims to
            cover. Re-hashed and compared against ``signature.spec_hash``.
        key_registry: known signer_id -> operator key. Look up the
            signer's key here.

    Raises:
        KeyError: signer_id is not registered.
        ValueError: spec_payload no longer matches the signed hash.
        ValueError: signature does not validate under the signer's key.
    """
    if signature.signer_id not in key_registry:
        raise KeyError(
            f"signer '{signature.signer_id}' is not in the key registry"
        )
    expected_hash = canonical_spec_hash(spec_payload)
    if expected_hash != signature.spec_hash:
        raise ValueError(
            f"spec hash mismatch: expected {expected_hash}, "
            f"signature claims {signature.spec_hash}"
        )
    key = key_registry[signature.signer_id]
    msg = (signature.signer_id + "|" + signature.spec_hash).encode("utf-8")
    expected_sig = hmac.new(key, msg, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, signature.signature):
        raise ValueError(
            f"signature for spec_hash {signature.spec_hash} does not "
            f"validate under signer '{signature.signer_id}' key"
        )


__all__ = [
    "SpecSignature",
    "canonical_spec_hash",
    "sign_spec",
    "verify_spec",
]

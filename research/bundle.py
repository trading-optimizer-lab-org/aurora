"""Strategy publish / import bundle (R91).

Package a strategy plus its `policy_hash`, `spec_hash`, audit-report
hash, and a README into a single signed bundle. Operators on a
different machine import the bundle, verify the hash chain, and
reproduce the validation locally.

Format: a deterministic JSON envelope that bundles:

- the canonical spec payload,
- the validation report digest,
- the policy hash bound to the spec at promotion time,
- the witness hash from R146,
- a SpecSignature (R44) so consumers can verify the publisher,
- a manifest of any auxiliary file hashes (per-fold weights, GA
  population dump, etc).

A full marketplace is explicitly out of scope. This module ships the
PUBLISH and IMPORT primitives only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class StrategyBundle:
    """Self-contained transport package for a promoted strategy."""

    bundle_version: str
    forge_version: str
    spec_payload: Dict[str, Any]
    spec_hash: str
    policy_hash: str
    witness_hash: Optional[str]
    validation_report_hash: str
    aux_files: Dict[str, str] = field(default_factory=dict)
    spec_signature: Optional[Dict[str, str]] = None

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_version": self.bundle_version,
            "forge_version": self.forge_version,
            "spec_payload": self.spec_payload,
            "spec_hash": self.spec_hash,
            "policy_hash": self.policy_hash,
            "witness_hash": self.witness_hash,
            "validation_report_hash": self.validation_report_hash,
            "aux_files": dict(self.aux_files),
            "spec_signature": (
                dict(self.spec_signature) if self.spec_signature else None
            ),
        }


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def publish_bundle(
    *,
    spec_payload: Mapping[str, Any],
    policy_hash: str,
    witness_hash: Optional[str],
    validation_report_hash: str,
    aux_files: Mapping[str, str] | None = None,
    spec_signature: Mapping[str, str] | None = None,
    forge_version: str = "1.4.0",
    bundle_version: str = "1",
) -> StrategyBundle:
    """Mint a :class:`StrategyBundle` ready to write to disk."""
    spec_hash = _canonical_hash(spec_payload)
    return StrategyBundle(
        bundle_version=bundle_version,
        forge_version=forge_version,
        spec_payload=dict(spec_payload),
        spec_hash=spec_hash,
        policy_hash=policy_hash,
        witness_hash=witness_hash,
        validation_report_hash=validation_report_hash,
        aux_files=dict(aux_files or {}),
        spec_signature=dict(spec_signature) if spec_signature else None,
    )


def write_bundle(bundle: StrategyBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(bundle.to_json())


def read_bundle(path: Path) -> StrategyBundle:
    with path.open("r", encoding="utf-8") as fh:
        d = json.load(fh)
    return StrategyBundle(**d)


def verify_bundle(bundle: StrategyBundle) -> List[str]:
    """Return a list of integrity errors (empty list = bundle is valid).

    Checks:

    1. Recomputed spec hash matches the recorded ``spec_hash``.
    2. Recorded ``spec_signature`` (if any) covers the recorded
       spec_hash. We do NOT verify the signature against a key
       registry here -- the caller does that with R44 ``verify_spec``;
       this primitive only reports structural mismatches.
    3. Bundle version is recognised.
    """
    errors: List[str] = []
    if bundle.bundle_version not in {"1"}:
        errors.append(f"unrecognised bundle_version: {bundle.bundle_version}")
    expected = _canonical_hash(bundle.spec_payload)
    if expected != bundle.spec_hash:
        errors.append(
            f"spec_hash mismatch: recomputed {expected}, "
            f"recorded {bundle.spec_hash}"
        )
    if bundle.spec_signature is not None:
        sig_hash = bundle.spec_signature.get("spec_hash")
        if sig_hash != bundle.spec_hash:
            errors.append(
                f"spec_signature covers spec_hash {sig_hash} but bundle "
                f"records {bundle.spec_hash}"
            )
    return errors


__all__ = [
    "StrategyBundle",
    "publish_bundle",
    "write_bundle",
    "read_bundle",
    "verify_bundle",
]

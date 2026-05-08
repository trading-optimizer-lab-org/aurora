"""Zero-knowledge proof of strategy returns (skeleton).

Lets a prover claim "my strategy achieved Sharpe >= S over period P" without
disclosing the trade log. The implementation here is a mock: the proof is a
salted hash of the private statistics plus a hash commitment to the trade
series. A real implementation would use a SNARK/STARK system (e.g. Risc0,
arkworks, libsnark). The interface is intentionally close to the shape such
a system would expose so callers can swap backends later.

Threat model & intent
---------------------
- Auditor wants to verify a performance claim without seeing positions.
- Prover commits up front to the trade series (so they cannot retroactively
  edit it once challenged).
- A real ZK backend would let the auditor verify the claim relative to that
  commitment; the mock here only checks that the proof was generated from
  the same data.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


def _hash_bytes(*chunks: bytes) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


@dataclass
class ZKPerformanceProof:
    """Mock ZK proof generator/verifier for strategy performance.

    A "proof" here is ``sha256(salt || claim || commitment)``. The verifier
    re-hashes the public claim and commitment with the disclosed salt and
    checks for a match. This is **not** zero-knowledge in the cryptographic
    sense; it is a stand-in so the rest of the codebase can wire up the
    interface today.
    """

    claim_metric: str = "sharpe_ratio"
    salt: bytes = field(default_factory=lambda: secrets.token_bytes(16))

    def commit(self, returns: np.ndarray) -> str:
        """Commit to the trade-return series. Returns a hex digest."""
        arr = np.asarray(returns, dtype=float)
        return _hash_bytes(arr.tobytes())

    def generate_proof(
        self,
        returns: np.ndarray,
        claimed_value: float,
    ) -> dict:
        """Generate a mock proof of the claimed metric value.

        Returns a JSON-serializable dict with ``commitment``, ``claim``,
        ``proof``. The salt stays private to the prover.
        """
        commitment = self.commit(returns)
        claim_blob = json.dumps(
            {"metric": self.claim_metric, "value": float(claimed_value)},
            sort_keys=True,
        ).encode()
        proof = _hash_bytes(self.salt, claim_blob, commitment.encode())
        return {
            "commitment": commitment,
            "claim": {"metric": self.claim_metric, "value": float(claimed_value)},
            "proof": proof,
        }

    def verify(self, bundle: dict, salt: Optional[bytes] = None) -> bool:
        """Verify a proof bundle. The salt must be provided by the prover.

        In a real ZK system the salt would not be revealed; the SNARK
        circuit would prove knowledge of it without disclosure.
        """
        s = salt if salt is not None else self.salt
        claim_blob = json.dumps(bundle["claim"], sort_keys=True).encode()
        expected = _hash_bytes(s, claim_blob, bundle["commitment"].encode())
        return expected == bundle["proof"]

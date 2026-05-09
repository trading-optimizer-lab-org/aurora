"""GDPR-compliant PII masking and encryption at rest.

Provides deterministic masking for fields that are commonly PII (names,
emails, account numbers, IBAN, SSN-like patterns) and a symmetric
encryption helper for at-rest persistence. The cryptography library is
imported lazily; if missing, encryption raises a clear error.

The masking strategy uses HMAC-SHA256 truncation so masked values are
stable per-key (enabling joins on masked fields) but not reversible.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


_DEFAULT_PII_FIELDS: frozenset[str] = frozenset({
    "name", "full_name", "first_name", "last_name",
    "email", "phone", "phone_number",
    "address", "street", "postcode", "zip",
    "ssn", "tax_id", "iban", "account_number",
    "passport", "national_id", "dob", "date_of_birth",
})


@dataclass
class PIIConfig:
    """Static config for the PII handler.

    Attributes:
        hmac_key_env: env var holding the HMAC pepper for deterministic masking.
        encryption_key_env: env var holding a 32-byte urlsafe base64 Fernet key.
        mask_fields: explicit field names to mask. Defaults to common PII set.
        mask_token_length: characters of HMAC hash kept in the masked value.
    """
    hmac_key_env: str = "QF_PII_HMAC_KEY"
    encryption_key_env: str = "QF_PII_FERNET_KEY"
    mask_fields: frozenset[str] = field(default_factory=lambda: _DEFAULT_PII_FIELDS)
    mask_token_length: int = 16


class PIIHandler:
    """Mask and encrypt PII fields per GDPR Articles 5(1)(f) and 32."""

    _EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def __init__(self, config: Optional[PIIConfig] = None) -> None:
        self.config = config or PIIConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def mask_record(self, record: dict) -> dict:
        """Return a copy of ``record`` with PII fields HMAC-masked.

        Non-PII fields pass through unchanged.
        """
        out: dict = {}
        for k, v in record.items():
            if k in self.config.mask_fields and v is not None:
                out[k] = self.mask_value(str(v))
            else:
                out[k] = v
        return out

    def mask_value(self, value: str) -> str:
        """Return deterministic HMAC-truncated mask of ``value``."""
        key = self._hmac_key().encode("utf-8")
        digest = hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"PII_{digest[: self.config.mask_token_length]}"

    def mask_dataframe_like(self, rows: Iterable[dict]) -> list[dict]:
        """Apply ``mask_record`` to each row in ``rows``."""
        return [self.mask_record(r) for r in rows]

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        """Encrypt ``plaintext`` using a Fernet key from env. Lazy import."""
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:  # pragma: no cover - optional dep
            raise ImportError(
                "cryptography>=41 required for PIIHandler.encrypt_bytes"
            ) from e
        import os
        key = os.environ.get(self.config.encryption_key_env, "")
        if not key:
            raise RuntimeError(
                f"missing env var {self.config.encryption_key_env}"
            )
        return Fernet(key.encode("utf-8")).encrypt(plaintext)

    def decrypt_bytes(self, ciphertext: bytes) -> bytes:
        """Decrypt ``ciphertext`` using a Fernet key from env. Lazy import."""
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:  # pragma: no cover - optional dep
            raise ImportError(
                "cryptography>=41 required for PIIHandler.decrypt_bytes"
            ) from e
        import os
        key = os.environ.get(self.config.encryption_key_env, "")
        if not key:
            raise RuntimeError(
                f"missing env var {self.config.encryption_key_env}"
            )
        return Fernet(key.encode("utf-8")).decrypt(ciphertext)

    @classmethod
    def looks_like_email(cls, value: str) -> bool:
        """Quick heuristic: True if value looks like an email."""
        return bool(cls._EMAIL_RE.match(value or ""))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _hmac_key(self) -> str:
        import os
        key = os.environ.get(self.config.hmac_key_env, "")
        # When unset, fall back to a stable per-process default so masking is
        # still deterministic within tests, but the operator MUST set this in
        # production. We deliberately do NOT log the fallback to avoid pretending
        # this is secure.
        return key or "qf-default-hmac-pepper-not-for-production"

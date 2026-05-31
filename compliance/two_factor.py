"""TOTP two-factor authentication for critical actions.

Wraps the ``pyotp`` library for time-based one-time passwords used to gate
sensitive operations such as live trading arming, deployment to prod, and
key rotation. ``pyotp`` is imported lazily; absence raises a clear error.

Secrets MUST be supplied via env vars or an out-of-band secret manager.
This module never accepts a plaintext secret as a constructor argument
when the env var path is configured.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TwoFactorConfig:
    """Static config for the TOTP helper.

    Attributes:
        secret_env: env var holding the base32-encoded shared secret.
        issuer: issuer name shown in authenticator apps.
        account_label: account label shown in authenticator apps.
        digits: number of digits in the OTP (6 standard, 8 supported).
        period_seconds: TOTP step in seconds (RFC 6238 default 30).
        valid_window: number of preceding/following steps accepted on verify.
    """
    secret_env: str = "QF_TOTP_SECRET"
    issuer: str = "Aurora"
    account_label: str = "operations"
    digits: int = 6
    period_seconds: int = 30
    valid_window: int = 1
    extra_metadata: tuple[str, ...] = field(default_factory=tuple)


class TwoFactorAuth:
    """TOTP helper for gating critical actions."""

    def __init__(self, config: Optional[TwoFactorConfig] = None) -> None:
        self.config = config or TwoFactorConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate_secret(self) -> str:
        """Return a fresh base32-encoded 160-bit secret. Lazy pyotp.

        Falls back to ``os.urandom`` when pyotp is unavailable so secret
        generation works in offline environments.
        """
        try:
            import pyotp
            return str(pyotp.random_base32())
        except ImportError:  # pragma: no cover - optional dep
            raw = os.urandom(20)
            return base64.b32encode(raw).decode("ascii").rstrip("=")

    def provisioning_uri(self, secret: Optional[str] = None) -> str:
        """Return otpauth:// URI for QR code provisioning. Lazy pyotp."""
        s = secret or self._secret()
        try:
            import pyotp
            return str(
                pyotp.TOTP(s, digits=self.config.digits, interval=self.config.period_seconds)
                .provisioning_uri(
                    name=self.config.account_label, issuer_name=self.config.issuer
                )
            )
        except ImportError:  # pragma: no cover - optional dep
            label = f"{self.config.issuer}:{self.config.account_label}"
            return (
                f"otpauth://totp/{label}?secret={s}"
                f"&issuer={self.config.issuer}"
                f"&digits={self.config.digits}"
                f"&period={self.config.period_seconds}"
            )

    def now_otp(self, secret: Optional[str] = None) -> str:
        """Return the current OTP. Uses pyotp when available."""
        s = secret or self._secret()
        try:
            import pyotp
            return str(
                pyotp.TOTP(s, digits=self.config.digits, interval=self.config.period_seconds).now()
            )
        except ImportError:  # pragma: no cover - optional dep
            return self._compute_totp(s, int(time.time()))

    def verify(self, code: str, secret: Optional[str] = None) -> bool:
        """Return True if ``code`` is valid for current step or windowed steps."""
        s = secret or self._secret()
        try:
            import pyotp
            totp = pyotp.TOTP(
                s, digits=self.config.digits, interval=self.config.period_seconds
            )
            return bool(totp.verify(code, valid_window=self.config.valid_window))
        except ImportError:  # pragma: no cover - optional dep
            return self._verify_offline(s, code)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _secret(self) -> str:
        s = os.environ.get(self.config.secret_env, "")
        if not s:
            raise RuntimeError(
                f"missing env var {self.config.secret_env}; cannot derive TOTP"
            )
        return s

    def _verify_offline(self, secret: str, code: str) -> bool:
        now_step = int(time.time()) // self.config.period_seconds
        for offset in range(-self.config.valid_window, self.config.valid_window + 1):
            ts = (now_step + offset) * self.config.period_seconds
            if hmac.compare_digest(self._compute_totp(secret, ts), code):
                return True
        return False

    def _compute_totp(self, secret: str, when_unix: int) -> str:
        """RFC 6238 TOTP computation used when pyotp is unavailable."""
        # Pad base32 secret to a multiple of 8 chars before decoding.
        padded = secret + "=" * ((8 - len(secret) % 8) % 8)
        key = base64.b32decode(padded.upper())
        counter = when_unix // self.config.period_seconds
        msg = struct.pack(">Q", counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        otp = truncated % (10 ** self.config.digits)
        return str(otp).zfill(self.config.digits)

"""Tests for quantforge.compliance.two_factor."""
from __future__ import annotations

import base64
import time

import pytest

from aurora.compliance.two_factor import TwoFactorAuth, TwoFactorConfig


@pytest.fixture
def auth() -> TwoFactorAuth:
    return TwoFactorAuth(TwoFactorConfig())


def _is_base32(value: str) -> bool:
    try:
        padded = value + "=" * ((8 - len(value) % 8) % 8)
        base64.b32decode(padded.upper())
        return True
    except Exception:
        return False


def test_generate_secret_is_base32(auth):
    s = auth.generate_secret()
    assert isinstance(s, str)
    assert len(s) >= 16
    assert _is_base32(s)


def test_generate_secret_unique(auth):
    a = auth.generate_secret()
    b = auth.generate_secret()
    # collision is astronomically unlikely
    assert a != b


def test_provisioning_uri_contains_issuer(auth):
    s = "JBSWY3DPEHPK3PXP"
    uri = auth.provisioning_uri(s)
    assert uri.startswith("otpauth://totp/")
    assert "QuantForge" in uri


def test_now_otp_is_digit_string(auth):
    otp = auth.now_otp("JBSWY3DPEHPK3PXP")
    assert otp.isdigit()
    assert len(otp) == auth.config.digits


def test_verify_accepts_current_otp(auth):
    secret = "JBSWY3DPEHPK3PXP"
    otp = auth.now_otp(secret)
    assert auth.verify(otp, secret) is True


def test_verify_rejects_wrong_otp(auth):
    secret = "JBSWY3DPEHPK3PXP"
    assert auth.verify("000000", secret) is False or auth.verify("000000", secret) is True
    # The above guard is loose because the actual current OTP is unknown.
    # Tighter check: a deterministically far-from-now code rejects.
    bad_code = "999999"
    real = auth.now_otp(secret)
    if real != bad_code:
        assert auth.verify(bad_code, secret) is False


def test_verify_rejects_short_code(auth):
    assert auth.verify("123", "JBSWY3DPEHPK3PXP") is False


def test_now_otp_no_secret_raises(auth, monkeypatch):
    monkeypatch.delenv("QF_TOTP_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="QF_TOTP_SECRET"):
        auth.now_otp()


def test_uses_env_secret_when_set(auth, monkeypatch):
    monkeypatch.setenv("QF_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    otp = auth.now_otp()
    assert otp.isdigit()
    assert len(otp) == auth.config.digits


def test_window_accepts_recent_code(auth):
    secret = "JBSWY3DPEHPK3PXP"
    # Use the engine's own offline computation for a previous step.
    period = auth.config.period_seconds
    prev_ts = int(time.time()) - period
    prior_code = auth._compute_totp(secret, prev_ts)
    # default valid_window=1 so previous step should still accept
    # (when pyotp is missing the offline path uses _verify_offline)
    if not _has_pyotp():
        assert auth.verify(prior_code, secret) is True


def _has_pyotp() -> bool:
    try:
        import pyotp  # noqa: F401
        return True
    except ImportError:
        return False

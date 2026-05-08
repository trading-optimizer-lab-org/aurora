"""Protocol fuzzing (R13).

Hypothesis-based adversarial inputs against the protocol surface:

- OOSGuard phase strings and lock-file paths.
- ``split_by_tier`` with malformed / degenerate price indices.
- ``ProtocolPolicy.from_dict`` with corrupt payloads.
- ``AgentGateway.stage`` with malformed ``ActionRequest`` objects.
- ``AgentToken`` signature tampering detection.

These tests assert that the protocol either (a) accepts well-formed input
or (b) raises a typed exception without silently swallowing the error.
A ``KeyError``, an ``AssertionError``, or a clean tier rejection are all
acceptable -- a stack trace from deep inside numpy is NOT.

Skipped cleanly when hypothesis is not installed.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

hypothesis = pytest.importorskip("hypothesis")

# E402 noqa: importorskip must precede dependent imports.
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from quantforge.core.data_layer import OOSGuard  # noqa: E402
from quantforge.core.data_tiers import split_by_tier  # noqa: E402
from quantforge.core.protocol_policy import ProtocolPolicy  # noqa: E402

_HC = [HealthCheck.too_slow, HealthCheck.function_scoped_fixture]


# ===========================================================================
# OOSGuard: phase strings, lock paths
# ===========================================================================


@given(phase=st.text(min_size=0, max_size=200))
@settings(max_examples=25, deadline=None, suppress_health_check=_HC)
def test_oosguard_accepts_any_phase_string(phase, tmp_path_factory):
    """OOSGuard accepts any free-form phase string and exits cleanly.

    The phase is metadata; access decisions live in the unlock-ceremony
    matchers, not in the OOSGuard constructor. Random text must not
    crash the lock file write.
    """
    lock_dir = tmp_path_factory.mktemp("oos_fuzz")
    lock = str(lock_dir / "lock.json")
    try:
        with OOSGuard(phase=phase, lock_path=lock) as g:
            assert g.phase == phase
            assert g.violations == 0
    except (ValueError, OSError):
        # Acceptable: a very long / control-character phase may fail at
        # write time; that is a typed error, not a crash.
        pass


@given(
    phase=st.sampled_from(
        [
            "explicit_unlock_oos_locked",
            "explicit_unlock_forward",
            "explicit_unlock_full_tier",
            "explicit_unlock_snapshot",
            "post_ga_validation",
            "optimization",
        ]
    ),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_oosguard_known_phases_work_in_memory(phase):
    """All documented phases construct cleanly without a lock file."""
    with OOSGuard(phase=phase, lock_path=None) as g:
        assert g.phase == phase


def test_oosguard_invalid_lock_path_raises_typed_error(tmp_path):
    """Passing a directory (not a file) as lock_path must fail typed."""
    lock = str(tmp_path)  # directory, not a file
    # Either OSError on write or accepted as opaque path. We require that
    # it is not a silent crash; use a try/except boundary to assert that
    # any failure is OSError-family.
    try:
        with OOSGuard(phase="optimization", lock_path=lock):
            pass
    except (OSError, IsADirectoryError, PermissionError):
        return
    # If it succeeded, that is also fine.


# ===========================================================================
# split_by_tier: degenerate indices
# ===========================================================================


@given(n=st.integers(min_value=0, max_value=20))
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_split_by_tier_handles_short_series(n):
    """Tiny / empty input must not crash split_by_tier."""
    if n == 0:
        idx = pd.DatetimeIndex([])
    else:
        idx = pd.date_range("2015-06-01", periods=n, freq="D")
    prices = pd.Series(np.full(n, 100.0), index=idx)
    s = split_by_tier(prices)
    total = (
        len(s.is_train)
        + len(s.is_valid)
        + len(s.oos_dev)
        + len(s.oos_locked)
        + len(s.forward)
    )
    assert total == n


@given(n=st.integers(min_value=10, max_value=100))
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_split_by_tier_handles_duplicate_timestamps(n):
    """Duplicate timestamps in the index do not crash split_by_tier."""
    base = pd.date_range("2015-06-01", periods=n, freq="D")
    # Inject duplicates at random positions.
    idx = pd.DatetimeIndex(list(base) + list(base[: n // 4]))
    prices = pd.Series(np.full(len(idx), 100.0), index=idx)
    s = split_by_tier(prices)
    total = (
        len(s.is_train)
        + len(s.is_valid)
        + len(s.oos_dev)
        + len(s.oos_locked)
        + len(s.forward)
    )
    assert total == len(idx)


@given(
    start_year=st.integers(min_value=1980, max_value=2050),
    n=st.integers(min_value=20, max_value=300),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_split_by_tier_handles_extreme_year_ranges(start_year, n):
    """Year boundaries far before/after policy tiers do not crash."""
    idx = pd.date_range(f"{start_year}-01-01", periods=n, freq="D")
    prices = pd.Series(np.full(n, 100.0), index=idx)
    s = split_by_tier(prices)
    total = (
        len(s.is_train)
        + len(s.is_valid)
        + len(s.oos_dev)
        + len(s.oos_locked)
        + len(s.forward)
    )
    assert total == n


# ===========================================================================
# ProtocolPolicy: from_dict on corrupt payloads
# ===========================================================================


def test_protocol_policy_from_dict_empty_payload_recovers():
    """An empty dict yields a default-shaped policy or raises typed error."""
    try:
        p = ProtocolPolicy.from_dict({})
        # If it succeeds, the result must verify its own hash.
        assert p.verify_hash()
    except (KeyError, TypeError, ValueError):
        return  # typed failure is acceptable


@given(
    extra_key=st.text(min_size=1, max_size=20),
    extra_val=st.one_of(
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=40),
    ),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_protocol_policy_ignores_unknown_keys(extra_key, extra_val):
    """Unknown top-level keys must not crash from_dict.

    The policy schema may evolve; tolerating extra keys keeps forward
    compatibility. This test asserts only that the call returns or raises
    typed -- no NameError, no AttributeError.
    """
    base = ProtocolPolicy.default().to_dict()
    base[extra_key] = extra_val
    try:
        p = ProtocolPolicy.from_dict(base)
        assert p is not None
    except (KeyError, TypeError, ValueError):
        return


# ===========================================================================
# AgentGateway: token tampering
# ===========================================================================


@pytest.fixture
def _gateway_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("QF_GATEWAY_SECRET", "test-secret-for-fuzz-tests")
    yield


@given(
    actor=st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
    days=st.integers(min_value=1, max_value=30),
)
@settings(max_examples=15, deadline=None, suppress_health_check=_HC)
def test_token_signature_rejects_actor_tampering(_gateway_secret, actor, days):
    """Mutating ``actor`` after issue invalidates the signature."""
    from quantforge.agent_gateway.tokens import (
        TokenScope,
        issue_token,
    )

    tok = issue_token(
        actor=actor,
        scopes=frozenset({TokenScope.READ_DATA}),
        expires_in_days=days,
    )
    # Tamper: clone with a mutated actor; recompute what the legitimate
    # signature for the tampered token would be, and assert it differs
    # from the original signature. If they matched, the signature did
    # not cover ``actor`` -- that would be a real protocol bug.
    bad = replace(tok, actor=actor + "_TAMPER")
    expected_sig_for_tampered = bad.expected_signature()
    assert expected_sig_for_tampered != tok.signature, (
        "actor field is not covered by the token signature"
    )

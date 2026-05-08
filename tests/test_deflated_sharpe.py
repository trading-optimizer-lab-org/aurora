"""Tests for validation.deflated_sharpe polish: warn on n_trials=1."""
from __future__ import annotations
import warnings
import pytest

from quantforge.validation.deflated_sharpe import deflated_sharpe_check, DSRReport


def test_dsr_warns_n_trials_one():
    """n_trials=1 must raise a UserWarning explaining multiplicity is inactive."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rep = deflated_sharpe_check(
            observed_sharpe=1.5, n_trials=1, n_periods=252,
        )
    assert isinstance(rep, DSRReport)
    assert rep.n_trials == 1
    # Look for at least one UserWarning mentioning multiplicity.
    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert user_warnings, "expected UserWarning for n_trials=1"
    assert any("multiplicity" in str(w.message) for w in user_warnings)


def test_dsr_n_trials_one_returns_psr():
    """When n_trials=1, DSR collapses to PSR-vs-zero (probability in [0, 1])."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        rep = deflated_sharpe_check(
            observed_sharpe=2.0, n_trials=1, n_periods=252,
        )
    assert 0.0 <= rep.dsr <= 1.0
    assert rep.dsr == rep.psr_vs_zero


def test_dsr_n_trials_gt_one_no_warning():
    """n_trials > 1 must NOT emit the multiplicity warning."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rep = deflated_sharpe_check(
            observed_sharpe=1.5, n_trials=10, n_periods=252,
        )
    user_warnings = [
        w for w in caught
        if issubclass(w.category, UserWarning)
        and "multiplicity" in str(w.message)
    ]
    assert not user_warnings
    assert rep.n_trials == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

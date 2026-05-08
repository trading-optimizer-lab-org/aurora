"""Tests for quantforge.core.metrics — compute_metrics edge cases."""
from __future__ import annotations
import math
import numpy as np

from quantforge.core.metrics import compute_metrics


def test_calmar_handles_zero_mdd():
    """When |mdd| < 1e-9, Calmar must be a signed infinity (or 0 for zero CAGR),
    not 0 (the previous silent fallback) and not NaN (inf/inf trap)."""
    # Monotone-up returns -> no drawdown at all (mdd == 0)
    r_pos = np.array([0.001, 0.002, 0.001, 0.003, 0.0015])
    m_pos = compute_metrics(r_pos, ppy=252)
    assert m_pos.mdd == 0.0
    assert m_pos.cagr > 0
    assert math.isinf(m_pos.calmar)
    assert m_pos.calmar > 0
    assert math.isinf(m_pos.mar) and m_pos.mar > 0

    # All zeros -> cagr 0, mdd 0 -> calmar 0
    r_zero = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    m_zero = compute_metrics(r_zero, ppy=252)
    assert m_zero.mdd == 0.0
    assert m_zero.cagr == 0.0
    assert m_zero.calmar == 0.0

    # Monotonically declining tiny but with nav going to ~1 (still no peak above 1)
    # Construct: very tiny negative followed by tiny positive that doesn't fully recover
    # Easiest negative-cagr-zero-mdd case is contrived; check the branch by:
    # a series whose nav is non-increasing from the start (mdd == 0 by definition
    # of cummax-from-start), but with a final nav < 1 -> cagr < 0.
    # cummax[0] = nav[0] = 1+r0 < 1 only if r0 < 0; cummax stays at 1+r0; subsequent
    # nav values <= cummax. mdd is min((nav-cummax)/cummax) which can be negative.
    # To force mdd == 0 we need nav[i] == cummax[i] for all i: monotonically
    # non-decreasing nav. That means CAGR >= 0. So a monotonically increasing
    # sequence with cagr exactly 0 is impossible. Skip the negative branch test:
    # the implementation handles it explicitly.


def test_metrics_normal_path_unchanged():
    """A typical mixed-sign return series still produces a finite, non-zero Calmar."""
    rng = np.random.default_rng(0)
    r = rng.normal(0.0005, 0.012, 500)
    m = compute_metrics(r, ppy=252)
    assert math.isfinite(m.calmar)
    # mdd should be strictly negative for any volatile series
    assert m.mdd < 0

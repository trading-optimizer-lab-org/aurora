"""Verify analytics.metrics_full re-exports core.metrics symbols (no duplication)."""
from __future__ import annotations

from quantforge.analytics import metrics_full as mf
from quantforge.core import metrics as core_m


def test_compute_metrics_is_same_object():
    assert mf.compute_metrics is core_m.compute_metrics


def test_deflated_sharpe_is_same_object():
    assert mf.deflated_sharpe is core_m.deflated_sharpe


def test_probabilistic_sharpe_is_same_object():
    assert mf.probabilistic_sharpe is core_m.probabilistic_sharpe


def test_both_modules_importable():
    """Both module paths should work for shared symbols."""
    from quantforge.analytics.metrics_full import compute_metrics as mf_cm
    from quantforge.core.metrics import compute_metrics as core_cm
    assert mf_cm is core_cm

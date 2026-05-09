"""Tests for quantforge.research.concept_drift_monitor."""
from __future__ import annotations
import numpy as np
import pytest

from aurora.research.concept_drift_monitor import (
    ConceptDriftMonitor,
    DriftSignal,
)


def test_basic_construction():
    m = ConceptDriftMonitor()
    assert "ddm" in m._detectors
    assert "eddm" in m._detectors
    assert "kswin" in m._detectors


def test_no_detectors_rejected():
    with pytest.raises(ValueError):
        ConceptDriftMonitor(ddm=False, eddm=False, kswin=False)


def test_stable_stream_no_drift():
    m = ConceptDriftMonitor(ddm=False, eddm=False, kswin=True,
                            kswin_window=40)
    rng = np.random.default_rng(0)
    last = {}
    for _ in range(200):
        v = float(rng.normal(0.0, 1.0))
        last = m.update(v)
    assert all(isinstance(s, DriftSignal) for s in last.values())
    # in a stationary stream the kswin detector should be stable at the end
    assert last["kswin"].level == "stable"


def test_kswin_detects_distribution_shift():
    m = ConceptDriftMonitor(ddm=False, eddm=False, kswin=True,
                            kswin_window=40)
    rng = np.random.default_rng(1)
    for _ in range(100):
        m.update(float(rng.normal(0.0, 1.0)))
    for _ in range(40):
        m.update(float(rng.normal(5.0, 1.0)))
    levels = {s.level for s in m.history()}
    assert "drift" in levels or "warning" in levels


def test_history_grows():
    m = ConceptDriftMonitor()
    for i in range(10):
        m.update(float(i))
    h = m.history()
    assert len(h) == 10 * len(m._detectors)


def test_any_drift_flag():
    m = ConceptDriftMonitor(ddm=False, eddm=False, kswin=True,
                            kswin_window=40)
    rng = np.random.default_rng(2)
    for _ in range(100):
        m.update(float(rng.normal(0.0, 1.0)))
    for _ in range(40):
        m.update(float(rng.normal(5.0, 1.0)))
    assert m.any_drift() is True

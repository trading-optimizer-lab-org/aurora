"""Tests for aurora.monitoring.drift (Batch O.5).

Run: uv run pytest aurora/tests/test_drift.py -v
"""
from __future__ import annotations

import numpy as np
import pytest

from aurora.monitoring.drift import (
    ADWINDetector,
    AutoRetrainController,
    KSDriftDetector,
    PageHinkleyDetector,
)


# ---------------------------------------------------------------------------
# Page-Hinkley
# ---------------------------------------------------------------------------


def test_ph_no_drift():
    """Stationary stream should not raise an alarm."""
    rng = np.random.default_rng(42)
    det = PageHinkleyDetector(delta=0.005, threshold=50.0, alpha=0.9999)
    fired = False
    for _ in range(1000):
        if det.update(rng.normal(0.0, 1.0)):
            fired = True
            break
    assert not fired, "PH fired on stationary normal stream"


def test_ph_detect_shift():
    """Mean shift from 0 to 1 should fire reasonably soon."""
    rng = np.random.default_rng(7)
    det = PageHinkleyDetector(delta=0.005, threshold=20.0, alpha=0.9999)
    # Stationary phase.
    for _ in range(500):
        det.update(rng.normal(0.0, 0.5))
    # Shifted phase.
    fired_at = None
    for i in range(500):
        if det.update(rng.normal(1.0, 0.5)):
            fired_at = i
            break
    assert fired_at is not None, "PH did not fire after mean shift"
    assert fired_at < 400, f"PH fired too late: {fired_at}"


def test_ph_no_false_alarm_warmup():
    """Warm-start (mean = first sample) must prevent a false alarm on a
    constant residual stream regardless of its non-zero offset.
    """
    det = PageHinkleyDetector(delta=0.0, threshold=1.0, alpha=0.9999)
    fired = False
    for _ in range(500):
        if det.update(10.0):  # constant offset; would fire without warm-start
            fired = True
            break
    assert not fired, (
        "PageHinkley fired on a constant residual stream after warm-start"
    )


def test_ph_reset():
    """Reset should restore initial state."""
    det = PageHinkleyDetector(delta=0.0, threshold=1.0)
    for _ in range(50):
        det.update(10.0)
    assert det.statistic >= 0.0
    det.reset()
    assert det.statistic == 0.0
    # After reset the detector must be usable again on stationary data.
    rng = np.random.default_rng(1)
    fired = any(det.update(rng.normal(0.0, 0.1)) for _ in range(200))
    assert not fired


# ---------------------------------------------------------------------------
# ADWIN
# ---------------------------------------------------------------------------


def test_adwin_no_drift():
    """Stationary stream should not raise an alarm.

    The per-cut Hoeffding bound is now applied at every interior cut, so the
    confidence parameter (``delta``) needs to be tightened compared to the
    single-cut formulation. Use a small ``delta`` so the per-cut false
    positive rate stays low even with multiple comparisons.
    """
    rng = np.random.default_rng(99)
    det = ADWINDetector(delta=1e-6, max_buckets=5)
    fired = False
    for _ in range(1500):
        if det.update(rng.normal(0.0, 1.0)):
            fired = True
            break
    assert not fired, "ADWIN fired on stationary stream"


def test_adwin_iterates_all_cuts():
    """ADWIN must consider every interior cut, not just the median split.

    Construct a window where the drift is concentrated near the head: the
    older 1/4 of buckets has a very different mean from the rest. The split
    test at the median (cut=k/2) sees a small gap, but the cut at k/4 (which
    isolates the older buckets) sees a large gap and must trigger.
    """
    det = ADWINDetector(delta=1e-3, max_buckets=4)
    # Fill 1 bucket of "old" regime then 3 buckets of "new" regime so the
    # median cut is between bucket 2 and 3 — both halves contain mostly new
    # samples and the median-only test would miss the drift. The cut at
    # index 1, however, isolates the old bucket and must catch it.
    for _ in range(32):
        det.update(0.0)
    fired = False
    for _ in range(96):
        if det.update(5.0):
            fired = True
            break
    assert fired, "ADWIN failed to detect drift visible at a non-median cut"


def test_adwin_detect_shift():
    """Distribution shift should fire ADWIN."""
    rng = np.random.default_rng(123)
    det = ADWINDetector(delta=0.05, max_buckets=4)
    for _ in range(400):
        det.update(rng.normal(0.0, 0.3))
    fired = False
    for _ in range(800):
        if det.update(rng.normal(2.0, 0.3)):
            fired = True
            break
    assert fired, "ADWIN did not fire after distribution shift"


# ---------------------------------------------------------------------------
# KS detector
# ---------------------------------------------------------------------------


def test_ks_no_drift():
    """Same-distribution buffer should not reject the null."""
    rng = np.random.default_rng(11)
    ref = rng.normal(0.0, 1.0, 500)
    det = KSDriftDetector(window=200, p_threshold=0.01)
    det.fit_reference(ref)
    fired = False
    rng2 = np.random.default_rng(22)
    for _ in range(800):
        if det.update(rng2.normal(0.0, 1.0)):
            fired = True
            break
    assert not fired, "KS fired on identical distribution"


def test_ks_detect_shift():
    """Post-shift buffer should reject the null."""
    rng = np.random.default_rng(33)
    ref = rng.normal(0.0, 1.0, 500)
    det = KSDriftDetector(window=200, p_threshold=0.01)
    det.fit_reference(ref)
    rng2 = np.random.default_rng(44)
    fired = False
    for _ in range(600):
        if det.update(rng2.normal(2.0, 1.0)):
            fired = True
            break
    assert fired, "KS did not fire after large shift"


def test_ks_non_overlapping_windows():
    """The KS detector must run on disjoint, non-overlapping windows and
    clear its buffer regardless of whether drift fires.
    """
    rng = np.random.default_rng(0)
    ref = rng.normal(0.0, 1.0, 1000)
    det = KSDriftDetector(window=50, p_threshold=0.01)
    det.fit_reference(ref)

    # Feed 49 samples — buffer not yet full, no test runs.
    for _ in range(49):
        assert det.update(rng.normal(0.0, 1.0)) is False

    # 50th sample fills the window. KS may or may not fire on noise, but the
    # buffer must clear unconditionally afterwards.
    det.update(rng.normal(0.0, 1.0))
    assert len(det._buffer) == 0, (
        "KS buffer did not clear after running the test"
    )

    # Feed another 49: buffer fills again with strictly *new* samples — the
    # window does not include any of the previous 50.
    for i in range(49):
        out = det.update(rng.normal(0.0, 1.0))
        assert out is False, f"unexpected fire at intra-window step {i}"
    assert len(det._buffer) == 49


def test_ks_reference_required():
    """Calling update without a reference must raise a clear error."""
    det = KSDriftDetector(window=50)
    with pytest.raises(RuntimeError, match="fit_reference"):
        det.update(0.0)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


def test_controller_callback_invoked():
    """Synthetic shift triggers callback exactly once over the burst."""
    calls = {"n": 0}

    def cb():
        calls["n"] += 1

    det = PageHinkleyDetector(delta=0.005, threshold=15.0, alpha=0.9999)
    ctrl = AutoRetrainController(
        detectors=[det], retrain_callback=cb, cooldown_steps=10_000
    )
    rng = np.random.default_rng(5)
    # Stationary residuals.
    for _ in range(300):
        ctrl.step(prediction=0.0, realized=rng.normal(0.0, 0.1))
    # Shift: predictions diverge from realized.
    for _ in range(300):
        ctrl.step(prediction=1.0, realized=rng.normal(0.0, 0.1))
    assert calls["n"] == 1, f"expected exactly 1 callback, got {calls['n']}"


def test_controller_cooldown():
    """Cooldown enforces a no-fire window after a retrain.

    Page-Hinkley now warm-starts the running mean to the first observed
    sample, so a constant residual is correctly treated as zero drift. To
    trigger drift bursts, alternate between two regimes (zero residuals and
    a step-up residual). Each burst should produce exactly one retrain
    while the cooldown is honoured.
    """
    calls = {"n": 0}

    def cb():
        calls["n"] += 1

    det = PageHinkleyDetector(delta=0.0, threshold=1.0, alpha=0.9999)
    ctrl = AutoRetrainController(
        detectors=[det], retrain_callback=cb, cooldown_steps=200
    )
    # Burn-in: feed zeros so PH warms up at zero. No drift, no callback.
    for _ in range(50):
        ctrl.step(prediction=0.0, realized=0.0)
    assert calls["n"] == 0
    # Burst of strong residuals; PH triggers within a few steps.
    for _ in range(150):
        ctrl.step(prediction=10.0, realized=0.0)
    assert calls["n"] == 1
    # Stationary stretch — within cooldown observed-drift window, still 1.
    for _ in range(100):
        ctrl.step(prediction=0.0, realized=0.0)
    assert calls["n"] == 1
    # After cooldown elapsed, another burst fires once more.
    for _ in range(150):
        ctrl.step(prediction=10.0, realized=0.0)
    assert calls["n"] == 2


def test_autoretrain_cooldown_no_immediate_refire():
    """A second drift signal observed immediately after a retrain must NOT
    re-fire while the cooldown window is still active.
    """
    calls = {"n": 0}

    def cb():
        calls["n"] += 1

    # A "stub" detector that always reports drift. Lets us probe the
    # controller's cooldown semantics independent of any real detector.
    class _AlwaysFiring:
        def update(self, x: float) -> bool:
            return True

        def reset(self) -> None:
            return None

    ctrl = AutoRetrainController(
        detectors=[_AlwaysFiring()], retrain_callback=cb, cooldown_steps=10
    )
    # First step fires the retrain.
    assert ctrl.step(0.0, 0.0) is True
    assert calls["n"] == 1
    # Next 9 steps are inside the cooldown — must NOT refire.
    for i in range(9):
        assert ctrl.step(0.0, 0.0) is False, (
            f"controller refired at step {i + 2} inside cooldown"
        )
    assert calls["n"] == 1
    # 10th step after the trigger crosses the strict-< boundary and may fire.
    assert ctrl.step(0.0, 0.0) is True
    assert calls["n"] == 2


def test_controller_get_state():
    """get_state returns the documented keys."""
    ctrl = AutoRetrainController(
        detectors=[PageHinkleyDetector()],
        retrain_callback=lambda: None,
        cooldown_steps=50,
    )
    ctrl.step(prediction=0.0, realized=0.0)
    state = ctrl.get_state()
    for key in (
        "steps",
        "retrains",
        "last_trigger_step",
        "cooldown_steps",
        "n_detectors",
    ):
        assert key in state, f"missing key in get_state(): {key}"
    assert state["steps"] == 1
    assert state["n_detectors"] == 1
    assert state["cooldown_steps"] == 50

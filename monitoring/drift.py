"""Concept drift detection and auto-retrain triggers (Batch O.5).

Implements three classic streaming drift detectors plus a controller that
binds them to a retrain callback:

- Page-Hinkley test (Page 1954): cumulative deviation from running mean
  with forgetting factor.
- ADWIN-lite (Bifet & Gavalda 2007): adaptive sliding window using the
  Hoeffding bound to compare the older half mean to the newer half mean.
- Kolmogorov-Smirnov drift detector: two-sample KS p-value of a rolling
  buffer against a fixed reference distribution.

The :class:`AutoRetrainController` feeds residuals (prediction - realized)
into a list of detectors and invokes a user-supplied retrain callback
when any detector signals drift, with a cooldown to prevent thrashing.

References
----------
- Page, E. S. (1954). Continuous inspection schemes. Biometrika 41(1).
- Bifet, A. & Gavalda, R. (2007). Learning from time-changing data with
  adaptive windowing. SDM 2007.
- Massey, F. J. (1951). The Kolmogorov-Smirnov test for goodness of fit.
  JASA 46(253).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import math
import numpy as np
from scipy.stats import ks_2samp


__all__ = [
    "PageHinkleyDetector",
    "ADWINDetector",
    "KSDriftDetector",
    "AutoRetrainController",
]


# ---------------------------------------------------------------------------
# Page-Hinkley
# ---------------------------------------------------------------------------


@dataclass
class PageHinkleyDetector:
    """Page-Hinkley streaming drift test.

    Maintains a running mean and the cumulative deviation
    ``PH_t = max(0, PH_{t-1} + (x_t - mean_t - delta))``. An alarm is
    raised when ``PH_t > threshold``.

    Parameters
    ----------
    delta : float
        Tolerance / minimum drift magnitude to ignore. Increase to make
        the test more conservative.
    threshold : float
        Alarm threshold lambda. Larger values delay detection but reduce
        false alarms.
    alpha : float
        Forgetting factor in (0, 1] for the running mean. ``1.0`` keeps
        a true mean. Values just below 1 (e.g. 0.9999) make the mean
        adapt slowly to recent data.

    Notes
    -----
    The running mean is warm-started to the *first* observed sample. Without
    this, the EWMA mean starts at 0 and large early samples can push the PH
    statistic above ``threshold`` immediately, producing a spurious alarm
    before the detector has seen enough data to estimate a baseline.
    """

    delta: float = 0.005
    threshold: float = 50.0
    alpha: float = 0.9999

    _n: int = field(default=0, init=False, repr=False)
    _mean: float = field(default=0.0, init=False, repr=False)
    _ph: float = field(default=0.0, init=False, repr=False)
    _initialized: bool = field(default=False, init=False, repr=False)

    def update(self, x: float) -> bool:
        """Update with a new sample and return True if drift detected."""
        x = float(x)
        self._n += 1
        if not self._initialized:
            # Warm-start the mean with the first sample so the PH statistic
            # does not bias against zero in the warm-up regime.
            self._mean = x
            self._initialized = True
            return False
        if self.alpha >= 1.0:
            # Plain running mean.
            self._mean += (x - self._mean) / self._n
        else:
            # Exponentially-weighted running mean.
            self._mean = self.alpha * self._mean + (1.0 - self.alpha) * x
        self._ph = max(0.0, self._ph + (x - self._mean - self.delta))
        return self._ph > self.threshold

    def reset(self) -> None:
        """Clear all internal state."""
        self._n = 0
        self._mean = 0.0
        self._ph = 0.0
        self._initialized = False

    @property
    def statistic(self) -> float:
        """Current PH statistic (read-only)."""
        return self._ph


# ---------------------------------------------------------------------------
# ADWIN-lite
# ---------------------------------------------------------------------------


@dataclass
class ADWINDetector:
    """Adaptive windowing drift detector (simplified).

    Stores recent samples in ``max_buckets`` equally-sized buckets.
    Whenever a new bucket is sealed, the window is split into older
    and newer halves and drift is flagged when
    ``|mean_old - mean_new| > epsilon`` with the **per-cut Hoeffding
    bound**::

        epsilon = sqrt(ln(2 / delta) / (2 m))

    where ``m`` is the harmonic-style window size of the two halves
    (``m = 1 / (1/n0 + 1/n1)``).

    Note on Type-I error
    --------------------
    Using ``ln(2/delta)`` ties the false-positive rate to ``delta`` for
    a *single* comparison. Because :meth:`update` evaluates every
    interior bucket cut on each seal, the per-window Type-I error
    scales with the number of cuts ``k - 1`` and exceeds ``delta``.
    Callers who need a strict per-window guarantee at level ``delta``
    should pre-divide by the maximum cut count (Bonferroni) before
    constructing the detector, or replace ``ln(2/delta)`` with
    ``ln(4 n / delta)`` in :meth:`update` for the Bifet-Gavalda
    correction. We deliberately use the simpler per-cut bound here for
    higher detection sensitivity in the streaming setting.

    Parameters
    ----------
    delta : float
        Confidence parameter in (0, 1). Lower delta = stricter test.
    max_buckets : int
        Number of buckets retained. Larger windows give more statistical
        power but slower detection.
    """

    delta: float = 0.002
    max_buckets: int = 5

    _buckets: list = field(default_factory=list, init=False, repr=False)
    _bucket_size: int = field(default=32, init=False, repr=False)
    _current: list = field(default_factory=list, init=False, repr=False)
    _new_bucket: bool = field(default=False, init=False, repr=False)

    def update(self, x: float) -> bool:
        """Append sample and check for drift across every bucket cut.

        Iterates over all interior cut points (1..k-1) of the bucket
        window. For each cut, applies the per-cut Hoeffding bound::

            epsilon = sqrt(ln(2 / delta) / (2 m))

        where ``m`` is the harmonic-style window size of the two halves.
        Drift is signalled at the first cut where the mean gap exceeds
        ``epsilon``; the older buckets up to and including that cut are
        dropped so the window adapts.

        Implementation note: prefix sums and prefix counts of bucket
        contents are computed once per seal, so each candidate cut is
        evaluated in O(1) and the whole per-seal scan is O(k) instead of
        the previous O(k^2) ``np.concatenate`` loop.
        """
        x = float(x)
        self._current.append(x)
        self._new_bucket = False
        if len(self._current) >= self._bucket_size:
            self._buckets.append(np.array(self._current, dtype=float))
            self._current = []
            self._new_bucket = True
            if len(self._buckets) > self.max_buckets:
                self._buckets.pop(0)

        # Only evaluate the split test when a bucket has just been sealed.
        if not self._new_bucket or len(self._buckets) < 2:
            return False

        k = len(self._buckets)
        # Prefix sums and counts of bucket contents. ``prefix_sum[i]`` is
        # the running sum of the first ``i`` buckets concatenated, and
        # ``prefix_count[i]`` is their total sample count. With these,
        # the mean of any prefix or suffix is O(1).
        bucket_sums = np.array([float(b.sum()) for b in self._buckets], dtype=float)
        bucket_counts = np.array([b.size for b in self._buckets], dtype=np.int64)
        prefix_sum = np.concatenate(([0.0], np.cumsum(bucket_sums)))
        prefix_count = np.concatenate(([0], np.cumsum(bucket_counts)))
        total_sum = prefix_sum[-1]
        total_count = int(prefix_count[-1])

        ln_2_over_delta = math.log(2.0 / self.delta)
        for cut in range(1, k):
            n0 = int(prefix_count[cut])
            n1 = total_count - n0
            if n0 == 0 or n1 == 0:
                continue
            mean_old = prefix_sum[cut] / n0
            mean_new = (total_sum - prefix_sum[cut]) / n1
            m = 1.0 / (1.0 / n0 + 1.0 / n1)
            # Per-cut Hoeffding bound; using ln(2/delta) ties the
            # per-comparison false-positive rate to ``delta``.
            epsilon = math.sqrt(ln_2_over_delta / (2.0 * m))
            if abs(mean_old - mean_new) > epsilon:
                self._buckets = self._buckets[cut:]
                return True
        return False

    def reset(self) -> None:
        """Discard all stored samples."""
        self._buckets = []
        self._current = []
        self._new_bucket = False


# ---------------------------------------------------------------------------
# KS drift detector
# ---------------------------------------------------------------------------


@dataclass
class KSDriftDetector:
    """Two-sample Kolmogorov-Smirnov drift detector.

    Maintains a rolling buffer of the last ``window`` samples. To avoid
    the multiple-comparisons problem that would arise from running a
    KS test after every single new sample, the test is only evaluated
    once every ``window`` newly observed samples (i.e. on full,
    non-overlapping windows). Drift is flagged when ``p < p_threshold``
    and the buffer is then cleared.

    Parameters
    ----------
    window : int
        Rolling window size.
    p_threshold : float
        KS p-value below which the null (same distribution) is rejected.
    reference : np.ndarray, optional
        Reference sample. Required before calling :meth:`update`. Set
        directly or via :meth:`fit_reference`.
    """

    window: int = 200
    p_threshold: float = 0.01
    reference: Optional[np.ndarray] = None

    _buffer: list = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._buffer = []
        if self.reference is not None:
            self.reference = np.asarray(self.reference, dtype=float).ravel()

    def fit_reference(self, data: np.ndarray) -> None:
        """Set the reference sample used for the KS comparison."""
        arr = np.asarray(data, dtype=float).ravel()
        if arr.size < 2:
            raise ValueError("KSDriftDetector reference needs >= 2 samples.")
        self.reference = arr

    def update(self, x: float) -> bool:
        """Append a sample and run KS once per disjoint window.

        The buffer is a plain list that fills up to ``window`` samples. When
        full, the KS test is run against the reference and the buffer is
        cleared *unconditionally* — drift or no drift — so consecutive tests
        operate on strictly non-overlapping windows. This avoids the
        multiple-comparison inflation of running KS on every shifted window.
        """
        if self.reference is None:
            raise RuntimeError(
                "KSDriftDetector.update called before fit_reference; "
                "provide a reference sample first."
            )
        self._buffer.append(float(x))
        if len(self._buffer) < self.window:
            return False
        try:
            result = ks_2samp(np.asarray(self._buffer, dtype=float), self.reference)
            pvalue = float(result.pvalue)
            return pvalue < self.p_threshold
        finally:
            # Always clear so the next window does not overlap with this one.
            self._buffer.clear()

    def reset(self) -> None:
        """Clear the rolling buffer (does not drop the reference)."""
        self._buffer.clear()


# ---------------------------------------------------------------------------
# Auto-retrain controller
# ---------------------------------------------------------------------------


class AutoRetrainController:
    """Coordinator that triggers retraining when drift is detected.

    Parameters
    ----------
    detectors : list
        Detectors implementing ``update(x: float) -> bool`` and
        ``reset()`` (e.g. instances of the classes in this module).
    retrain_callback : Callable
        Callback invoked with no arguments when drift fires. Use it to
        kick off a retrain job, log an alert, etc.
    cooldown_steps : int
        Minimum number of :meth:`step` calls between consecutive
        retrain invocations. Prevents thrashing when drift is sustained.
    """

    def __init__(
        self,
        detectors: list,
        retrain_callback: Callable[[], None],
        cooldown_steps: int = 100,
    ) -> None:
        if not detectors:
            raise ValueError("AutoRetrainController requires at least one detector.")
        if cooldown_steps < 0:
            raise ValueError("cooldown_steps must be >= 0.")
        self.detectors = list(detectors)
        self.retrain_callback = retrain_callback
        self.cooldown_steps = int(cooldown_steps)
        self._steps: int = 0
        self._retrains: int = 0
        self._last_trigger_step: int = -10**9  # last successful retrain step
        self._last_drift_observed_step: int = -10**9  # last observed drift sample

    def step(self, prediction: float, realized: float) -> bool:
        """Feed a (prediction, realized) pair and maybe trigger retrain.

        Cooldown is measured from the most recent *successful retrain*
        (``_last_trigger_step``). A fresh drift signal observed inside the
        cooldown window is suppressed and the detectors are reset so that
        the accumulated drift does not immediately refire once the window
        elapses. Outside the cooldown window, an observed drift fires the
        retrain callback and resets the cooldown anchor.

        ``_last_drift_observed_step`` is bookkeeping only - it is updated
        on every observed drift event (suppressed or not) and exposed via
        :meth:`get_state` so callers can inspect detector activity that
        was filtered by the cooldown.

        The cooldown comparison uses a strict ``<`` to avoid the off-by-one
        that previously released one step early.

        Returns
        -------
        bool
            True if a retrain was triggered on this step.
        """
        self._steps += 1
        residual = float(prediction) - float(realized)
        any_drift = False
        for det in self.detectors:
            if det.update(residual):
                any_drift = True
        if not any_drift:
            return False

        # Always refresh the observed-drift timestamp.
        self._last_drift_observed_step = self._steps

        # Strict ``<`` (was ``<=``) — fixes off-by-one that released the
        # cooldown one step early.
        in_cooldown = (self._steps - self._last_trigger_step) < self.cooldown_steps
        if in_cooldown:
            # Suppress the alarm and clear detector state so the same
            # accumulated drift does not immediately re-fire once the
            # cooldown elapses.
            for det in self.detectors:
                det.reset()
            return False
        self._last_trigger_step = self._steps
        self._retrains += 1
        self.retrain_callback()
        # Reset detectors so the post-retrain stream starts fresh.
        for det in self.detectors:
            det.reset()
        return True

    def get_state(self) -> dict:
        """Return a snapshot of controller counters."""
        return {
            "steps": self._steps,
            "retrains": self._retrains,
            "last_trigger_step": self._last_trigger_step,
            "last_drift_observed_step": self._last_drift_observed_step,
            "cooldown_steps": self.cooldown_steps,
            "n_detectors": len(self.detectors),
        }

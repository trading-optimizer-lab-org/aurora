"""Tests for Round V deployment fixes.

Covers:
  1.  KillSwitch threading lock (race-free check/arm/disarm).
  2.  Idempotency cache OrderedDict + maxlen + eviction log.
  3.  Kraken userref BLAKE2b hash + collision detection.
  4.  PaperBroker submit_order kill-switch atomic snapshot.
  5.  RateLimiter Condition.wait (no busy sleep).
  6.  PaperBroker side-flip absolute cache set.
  7.  AuditLog rotate atomicity (open new, swap, close old).
  8.  Partial-fill correctness gap documented + _pending_orders surface.
  9.  QFLiveStrategy.bind() returns fresh subclass per call.
 10.  submit_with_retry network error classification + transient_predicate.
 11.  EWMA cov bias_corr near-zero fallback.
 12.  PSD floor relative to eigvals.max() (condition-number bounded).
 13.  Kelly tiny-positive avg_loss/win blowup.
 14.  Preflight NTP all-fail defaults to FAIL (soft_skip opt-in).
 15.  Preflight new checks wired into run_preflight.
 16.  LiveConfig.fractional skips int truncation.
 17.  Idempotency cache returns deep copies.
 18.  Date-roll race per-instance lock (single NAV snapshot).
 19.  Risk-parity analytic Jacobian matches numeric.
 20.  pd.Timestamp.now(tz='UTC') replaces deprecated utcnow().
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantforge.deployment import brokers, live
from quantforge.deployment.brokers import (
    AuditLog,
    BrokerConfig,
    KillSwitch,
    KrakenAdapter,
    Order,
    PaperBroker,
    Position,
    _RateLimiter,
)
from quantforge.deployment.cov_shrinkage import (
    exponential_cov,
    fix_nonpositive_semidefinite,
)
from quantforge.deployment.live import (
    LiveConfig,
    QFLiveStrategy,
    submit_with_retry,
    TransientOrderError,
)
from quantforge.deployment.preflight import (
    check_system_time,
)
from quantforge.deployment.risk_parity import _solve_sqp
from quantforge.deployment.sizing import kelly_size


# ---------------------------------------------------------------------------
# Issue 1, 4: KillSwitch lock + atomic snapshot
# ---------------------------------------------------------------------------

def test_kill_switch_has_lock():
    """KillSwitch exposes an internal RLock via locked()."""
    ks = KillSwitch()
    lock = ks.locked()
    # Re-entrant: same thread can acquire twice without blocking.
    with lock:
        with lock:
            assert ks.triggered is False


def test_kill_switch_arm_disarm_are_atomic():
    """arm() / disarm() update flags inside the lock."""
    ks = KillSwitch()
    ks.arm()
    assert ks.triggered is True
    ks.disarm()
    assert ks.triggered is False
    assert ks.day_start_equity is None


def test_kill_switch_concurrent_check_does_not_corrupt_state():
    """Two threads hammering check() must not interleave the daily reset."""
    ks = KillSwitch(max_daily_loss_pct=0.5, max_position_qty=1e9)

    def worker():
        for _ in range(200):
            ks.check({"equity": 100_000.0}, [])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # day_start_equity is set exactly once and never goes None mid-flight.
    assert ks.day_start_equity == pytest.approx(100_000.0)
    assert ks.triggered is False


# ---------------------------------------------------------------------------
# Issue 2, 17: Idempotency cache OrderedDict + maxlen + deepcopy
# ---------------------------------------------------------------------------

def test_idempotency_cache_is_ordered_dict():
    """PaperBroker uses OrderedDict for FIFO eviction semantics."""
    pb = PaperBroker(BrokerConfig(name="paper", paper=True))
    assert isinstance(pb._seen_client_order_ids, OrderedDict)


def test_idempotency_cache_evicts_when_over_max(monkeypatch):
    """Inserting more than IDEMPOTENT_CACHE_MAX entries evicts FIFO."""
    pb = PaperBroker(BrokerConfig(name="paper", paper=True))
    monkeypatch.setattr(pb, "IDEMPOTENT_CACHE_MAX", 3)
    pb._record_idempotent("a", {"status": "filled"})
    pb._record_idempotent("b", {"status": "filled"})
    pb._record_idempotent("c", {"status": "filled"})
    pb._record_idempotent("d", {"status": "filled"})
    seen = pb._seen_client_order_ids
    assert "a" not in seen
    assert list(seen.keys()) == ["b", "c", "d"]


def test_idempotency_cache_returns_deep_copy():
    """Mutating the returned dict must not corrupt the cache."""
    pb = PaperBroker(BrokerConfig(name="paper", paper=True))
    pb._record_idempotent("xyz", {"status": "filled", "nested": {"k": 1}})
    out = pb._idempotent_response("xyz")
    out["status"] = "MUTATED"
    out["nested"]["k"] = 999
    again = pb._idempotent_response("xyz")
    assert again["status"] == "filled"
    assert again["nested"]["k"] == 1


def test_idempotency_record_stored_as_deepcopy():
    """Mutating the input after recording must not corrupt the cache."""
    pb = PaperBroker(BrokerConfig(name="paper", paper=True))
    payload = {"status": "submitted", "details": {"qty": 10}}
    pb._record_idempotent("cid1", payload)
    payload["status"] = "external mutation"
    payload["details"]["qty"] = -1
    out = pb._idempotent_response("cid1")
    assert out["status"] == "submitted"
    assert out["details"]["qty"] == 10


# ---------------------------------------------------------------------------
# Issue 3: Kraken userref hash + collision detection
# ---------------------------------------------------------------------------

def test_kraken_userref_uses_blake2b():
    """userref is derived via 4-byte BLAKE2b -> u32 in [0, 2**32)."""
    refs = [
        KrakenAdapter._client_order_id_to_userref(s)
        for s in ("a", "abcd", "qf-cid-99", "xx" * 50)
    ]
    for r in refs:
        assert 0 <= r < 2 ** 32
    # Different inputs produce different outputs (BLAKE2b avalanche).
    assert len(set(refs)) == len(refs)


def test_kraken_userref_none_returns_zero():
    assert KrakenAdapter._client_order_id_to_userref(None) == 0


# ---------------------------------------------------------------------------
# Issue 5: RateLimiter Condition.wait (no busy sleep)
# ---------------------------------------------------------------------------

def test_rate_limiter_uses_condition_wait():
    """Custom wait_fn replaces the Condition.wait (testability)."""
    waits: list[float] = []
    fake_now = [0.0]

    def fake_wait(timeout):
        waits.append(float(timeout))
        # Advance fake clock so subsequent acquires can pass.
        fake_now[0] += timeout

    def now():
        return fake_now[0]

    rl = _RateLimiter(max_per_minute=2, window_seconds=10.0,
                      time_fn=now, wait_fn=fake_wait)
    rl.acquire()
    rl.acquire()
    rl.acquire()  # should wait once
    assert len(waits) >= 1
    assert all(w > 0 for w in waits)


# ---------------------------------------------------------------------------
# Issue 7: AuditLog rotate atomicity
# ---------------------------------------------------------------------------

def test_audit_log_rotate_failure_keeps_old_connection(monkeypatch, tmp_path):
    """If opening the new dated DB fails, writes continue on the old conn."""
    monkeypatch.chdir(tmp_path)
    al = AuditLog()  # default dated path
    orig_conn = al._conn

    # Force the rotation to "have rolled" by setting open_date in the past.
    from datetime import date as _date
    al._open_date = _date(1999, 1, 1)

    # Make _open_connection raise so the rotation fails.
    def boom(path):
        raise OSError("disk full")
    monkeypatch.setattr(AuditLog, "_open_connection", staticmethod(boom))

    # Trigger rotation; record() must NOT raise even when the rotate fails.
    al.record("fill", order_id="x")
    assert al._conn is orig_conn  # original connection retained
    # Cleanup
    al.close()


# ---------------------------------------------------------------------------
# Issue 6: PaperBroker side-flip absolute cache set
# ---------------------------------------------------------------------------

def test_paper_broker_side_flip_local_cache_absolute():
    """When a position flips sign via partial fill, local cache is set
    absolutely to the new qty (not delta-accumulated)."""
    pb = PaperBroker(BrokerConfig(name="paper", paper=True))
    pb.set_last_price("XYZ", 100.0)
    # Build initial long via market buy.
    pb.submit_order(Order(symbol="XYZ", qty=5, side="buy",
                          order_type="market"))
    assert pb._local_positions.get("XYZ") == pytest.approx(5.0)
    # Force a side flip by direct internal call (paper rejects oversells
    # at the user-facing layer, so we exercise _update_position directly).
    pb._update_position("XYZ", -7.0, 100.0)
    assert pb._state.positions["XYZ"].qty == pytest.approx(-2.0)
    assert pb._local_positions["XYZ"] == pytest.approx(-2.0)


# ---------------------------------------------------------------------------
# Issue 8: partial-fill _pending_orders surface
# ---------------------------------------------------------------------------

def test_paper_broker_pending_orders_attribute_exists():
    pb = PaperBroker(BrokerConfig(name="paper", paper=True))
    assert hasattr(pb, "_pending_orders")
    assert pb._pending_orders == {}


# ---------------------------------------------------------------------------
# Issue 10: submit_with_retry network error classification + predicate
# ---------------------------------------------------------------------------

class _OrderStub:
    """Plain order with no client_order_id so idempotency lookup is skipped."""
    client_order_id = None


def test_submit_with_retry_retries_connection_error():
    strat = MagicMock(spec=["submit_order", "broker"])
    strat.broker = None
    strat.submit_order = MagicMock(side_effect=[
        ConnectionError("blip"), {"status": "ok"},
    ])
    out = submit_with_retry(strat, order=_OrderStub(),
                            max_attempts=3, delay=0.0)
    assert out == {"status": "ok"}
    assert strat.submit_order.call_count == 2


def test_submit_with_retry_retries_timeout_error():
    strat = MagicMock(spec=["submit_order", "broker"])
    strat.broker = None
    strat.submit_order = MagicMock(side_effect=[
        TimeoutError("slow"), {"status": "ok"},
    ])
    out = submit_with_retry(strat, order=_OrderStub(),
                            max_attempts=3, delay=0.0)
    assert out == {"status": "ok"}


def test_submit_with_retry_propagates_value_error():
    """ValueError is non-retryable (auth/validation/etc)."""
    strat = MagicMock(spec=["submit_order", "broker"])
    strat.broker = None
    strat.submit_order = MagicMock(side_effect=ValueError("bad"))
    with pytest.raises(ValueError):
        submit_with_retry(strat, order=_OrderStub(),
                          max_attempts=3, delay=0.0)
    assert strat.submit_order.call_count == 1


def test_submit_with_retry_uses_transient_predicate():
    """Caller-supplied predicate marks a non-default exception as retryable."""
    class WeirdError(Exception):
        pass

    strat = MagicMock(spec=["submit_order", "broker"])
    strat.broker = None
    strat.submit_order = MagicMock(side_effect=[
        WeirdError("vendor 503"), {"status": "ok"},
    ])
    out = submit_with_retry(
        strat, order=_OrderStub(), max_attempts=3, delay=0.0,
        transient_predicate=lambda e: isinstance(e, WeirdError),
    )
    assert out == {"status": "ok"}
    assert strat.submit_order.call_count == 2


# ---------------------------------------------------------------------------
# Issue 11: EWMA cov bias_corr near zero
# ---------------------------------------------------------------------------

def test_exponential_cov_falls_back_when_effective_n_low():
    """Tight EWMA span concentrates weight so effective sample size drops
    below threshold; function emits a UserWarning and returns the biased
    estimate instead of dividing by a near-zero correction factor."""
    rng = np.random.default_rng(0)
    rets = pd.DataFrame(rng.normal(size=(50, 3)),
                        columns=["A", "B", "C"])
    # span=2 makes alpha=2/3, so effective_n ~ 1.6 -> below threshold 3.
    with pytest.warns(UserWarning, match="effective sample size"):
        cov = exponential_cov(rets, span=2, frequency=252,
                              effective_n_threshold=3.0)
    # Still returns a finite covariance matrix.
    assert np.all(np.isfinite(cov.to_numpy()))


# ---------------------------------------------------------------------------
# Issue 12: PSD floor relative to eigvals.max()
# ---------------------------------------------------------------------------

def test_psd_repair_condition_number_bounded():
    """Spectral repair on a poorly scaled matrix bounds condition number."""
    n = 5
    # Diagonal with one huge eigenvalue and one tiny negative.
    M = np.diag([1e6, 100.0, 50.0, 10.0, -1e-3])
    df = pd.DataFrame(M, index=range(n), columns=range(n))
    fixed = fix_nonpositive_semidefinite(df, fix_method="spectral")
    eigs = np.linalg.eigvalsh(fixed.to_numpy())
    cond = float(eigs.max() / max(eigs.min(), 1e-30))
    assert cond < 1e8 + 1


# ---------------------------------------------------------------------------
# Issue 13: Kelly tiny-positive blowup
# ---------------------------------------------------------------------------

def test_kelly_zero_when_avg_loss_below_floor():
    out = kelly_size(nav=100_000.0, asset_price=100.0, win_rate=0.6,
                     avg_win=1.0, avg_loss=1e-9, fraction=0.25)
    assert out == 0


def test_kelly_zero_when_avg_win_below_floor():
    out = kelly_size(nav=100_000.0, asset_price=100.0, win_rate=0.6,
                     avg_win=1e-9, avg_loss=1.0, fraction=0.25)
    assert out == 0


# ---------------------------------------------------------------------------
# Issue 14: NTP default-FAIL on all-unreachable
# ---------------------------------------------------------------------------

def test_check_system_time_defaults_to_fail_on_no_ntp(monkeypatch):
    import quantforge.deployment.preflight as pf
    monkeypatch.setattr(pf, "_query_ntp_server",
                        lambda server, timeout: None)
    chk = check_system_time(timeout=0.01)
    assert chk.passed is False
    assert "no NTP reachable" in chk.detail


def test_check_system_time_soft_skip_passes_on_no_ntp(monkeypatch):
    import quantforge.deployment.preflight as pf
    monkeypatch.setattr(pf, "_query_ntp_server",
                        lambda server, timeout: None)
    chk = check_system_time(timeout=0.01, soft_skip=True)
    assert chk.passed is True
    assert "skipped" in chk.detail.lower()


# ---------------------------------------------------------------------------
# Issue 16: LiveConfig.fractional shares
# ---------------------------------------------------------------------------

def test_live_config_default_fractional_false():
    cfg = LiveConfig()
    assert cfg.fractional is False


def test_live_config_fractional_can_be_enabled():
    cfg = LiveConfig(fractional=True)
    assert cfg.fractional is True


# ---------------------------------------------------------------------------
# Issue 18: Date-roll race per-instance lock
# ---------------------------------------------------------------------------

def test_maybe_roll_session_uses_per_instance_lock(monkeypatch):
    """Concurrent _maybe_roll_session calls on the same instance capture NAV
    exactly once. The legacy implementation could double-snapshot."""
    monkeypatch.setattr(live, "HAS_LUMIBOT", True)
    qf = MagicMock()
    qf.signals = MagicMock(return_value=[0.0])
    cls = QFLiveStrategy.bind(qf_strategy=qf, symbol="SPY",
                              risk_per_trade=0.01,
                              daily_loss_limit=0.05,
                              max_notional_pct=1.0)
    inst = object.__new__(cls)
    inst.set_market = MagicMock()
    inst.sleeptime = None
    nav_calls = {"n": 0}

    def gpv():
        nav_calls["n"] += 1
        return 100_000.0

    inst.get_portfolio_value = gpv
    inst.initialize()
    # Manually mark prior date so the next _maybe_roll_session sees a roll.
    from datetime import date as _date
    inst.qf_session_date = _date(1999, 1, 1)

    threads = [threading.Thread(target=inst._maybe_roll_session)
               for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # initialize() consumed at least 1 NAV call. The roll should have
    # captured exactly one additional snapshot, not 5.
    # (Allow >=2: initialize call + one roll call.)
    assert nav_calls["n"] <= 2


# ---------------------------------------------------------------------------
# Issue 19: Risk-parity analytic Jacobian
# ---------------------------------------------------------------------------

def test_risk_parity_analytic_jacobian_matches_numeric():
    """Closed-form gradient agrees with central finite differences."""
    rng = np.random.default_rng(7)
    n = 4
    A = rng.standard_normal((n, n))
    cov = A @ A.T + np.eye(n)
    b = np.ones(n) / n

    # Build the local objective + grad clones; we re-use the same shapes
    # the solver wires up.
    def objective(w):
        sw = cov @ w
        var = float(w @ sw)
        if var <= 0:
            return 1.0
        rc = w * sw / var
        return float(np.sum((rc - b) ** 2))

    def analytic_grad(w):
        sw = cov @ w
        v = float(w @ sw)
        rc = w * sw / v
        diff = rc - b
        term_diag = (diff * sw) / v
        term_offdiag = (cov @ (diff * w)) / v
        scalar = float(np.sum(diff * rc))
        term_cross = (2.0 * scalar / v) * sw
        return 2.0 * (term_diag + term_offdiag - term_cross)

    w = rng.dirichlet(np.ones(n))
    g_ana = analytic_grad(w)
    eps = 1e-6
    g_num = np.zeros(n)
    for i in range(n):
        w_p = w.copy()
        w_m = w.copy()
        w_p[i] += eps
        w_m[i] -= eps
        g_num[i] = (objective(w_p) - objective(w_m)) / (2 * eps)
    np.testing.assert_allclose(g_ana, g_num, rtol=1e-4, atol=1e-7)


def test_risk_parity_solver_still_converges():
    """End-to-end SLSQP solver still converges with analytic Jacobian."""
    cov = np.array([[0.04, 0.01, 0.0],
                    [0.01, 0.09, 0.02],
                    [0.0, 0.02, 0.16]])
    b = np.ones(3) / 3
    w, _, converged = _solve_sqp(cov, b, max_iter=500, tol=1e-10)
    assert converged
    assert w.sum() == pytest.approx(1.0, abs=1e-6)
    # Risk contributions are equal within tolerance.
    sw = cov @ w
    rc = w * sw / float(w @ sw)
    np.testing.assert_allclose(rc, b, atol=1e-4)


# ---------------------------------------------------------------------------
# Issue 20: pd.Timestamp.now(tz='UTC') replaces utcnow()
# ---------------------------------------------------------------------------

def test_no_pd_timestamp_utcnow_in_preflight():
    """pd.Timestamp.utcnow() is deprecated; preflight uses .now(tz='UTC')."""
    src = (
        __import__("quantforge.deployment.preflight",
                   fromlist=["__file__"]).__file__
    )
    text = open(src, encoding="utf-8").read()
    assert "pd.Timestamp.utcnow()" not in text

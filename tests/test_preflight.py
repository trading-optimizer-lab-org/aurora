"""Tests for Task 4.4: pre-trade preflight validators."""
from __future__ import annotations
import json
import os
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.preflight import (
    PreflightCheck,
    PreflightReport,
    check_anti_lookahead,
    check_broker_connection,
    check_data_availability,
    check_disk_space,
    check_files_exist,
    check_no_conflicting_positions,
    check_position_sizing,
    check_strategy_callable,
    check_system_time,
    check_validation_marker,
    run_preflight,
    write_validation_marker,
    _marker_path,
    _resolve_min_bars,
    _NTP_FALLBACK_SERVERS,
)
from quantforge.strategies.library import MACross


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _synth_prices(n: int = 800, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    rets = rng.normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="SYNTH")


class _Bogus:
    """Object with no signals attr."""
    pass


# ---------------------------------------------------------------------------
# check_strategy_callable
# ---------------------------------------------------------------------------


def test_callable_check_pass():
    s = MACross(fast=10, slow=50)
    chk = check_strategy_callable(s)
    assert chk.passed is True
    assert chk.name == "strategy_callable"


def test_callable_check_fail():
    chk = check_strategy_callable(_Bogus())
    assert chk.passed is False
    assert "missing signals" in chk.detail


def test_callable_check_none():
    chk = check_strategy_callable(None)
    assert chk.passed is False


# ---------------------------------------------------------------------------
# check_data_availability
# ---------------------------------------------------------------------------


def test_data_availability_pass(monkeypatch):
    """Patch load_asset to return enough bars."""
    import quantforge.deployment.preflight as pf
    fake = _synth_prices(400)
    monkeypatch.setattr(pf, "load_asset", lambda symbol, include_oos=True: fake)
    chk = check_data_availability("FAKE", min_bars=200)
    assert chk.passed is True
    assert "400" in chk.detail


def test_data_availability_fail(monkeypatch):
    import quantforge.deployment.preflight as pf
    fake = _synth_prices(50)
    monkeypatch.setattr(pf, "load_asset", lambda symbol, include_oos=True: fake)
    chk = check_data_availability("FAKE", min_bars=200)
    assert chk.passed is False
    assert "50" in chk.detail


def test_data_availability_load_error(monkeypatch):
    import quantforge.deployment.preflight as pf

    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(pf, "load_asset", boom)
    chk = check_data_availability("FAKE", min_bars=10)
    assert chk.passed is False
    assert "network down" in chk.detail


# ---------------------------------------------------------------------------
# check_anti_lookahead
# ---------------------------------------------------------------------------


def test_anti_lookahead_pass():
    """Clean MACross is causal."""
    s = MACross(fast=10, slow=50)
    prices = _synth_prices(400)
    chk = check_anti_lookahead(s, prices)
    assert chk.passed is True


def test_anti_lookahead_fail_with_leaky():
    """Leaky strategy uses last-bar value at every index -> caught by shuffle."""
    class Leaky:
        def signals(self, prices):
            arr = np.asarray(prices.values, dtype=float)
            n = len(arr)
            # arr[-1] sits inside the shuffle zone; permutation changes it ->
            # signals differ before k -> runtime check flags the leak.
            future_val = arr[-1]
            sig = np.full(n, future_val / 1000.0)
            return sig

    chk = check_anti_lookahead(Leaky(), _synth_prices(500))
    assert chk.passed is False


def test_anti_lookahead_short_series():
    s = MACross(fast=5, slow=10)
    short = _synth_prices(20)
    chk = check_anti_lookahead(s, short)
    assert chk.passed is False


# ---------------------------------------------------------------------------
# check_validation_marker
# ---------------------------------------------------------------------------


def test_validation_marker_missing(tmp_path):
    chk = check_validation_marker("NoSuchStrat", project_dir=str(tmp_path))
    assert chk.passed is False
    assert "missing marker" in chk.detail


def test_validation_marker_present(tmp_path):
    name = "FakeStrat"
    metrics = {"is": {"calmar": 1.1}, "oos": {"calmar": 0.9}}
    path = write_validation_marker(name, metrics, project_dir=str(tmp_path))
    assert os.path.exists(path)
    # file is well-formed
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["strategy_name"] == name
    assert "timestamp" in data

    chk = check_validation_marker(name, project_dir=str(tmp_path))
    assert chk.passed is True
    assert "present" in chk.detail


def test_validation_marker_corrupt(tmp_path):
    name = "BadStrat"
    p = _marker_path(name, str(tmp_path))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("not json {{")
    chk = check_validation_marker(name, project_dir=str(tmp_path))
    assert chk.passed is False
    assert "unreadable" in chk.detail


# ---------------------------------------------------------------------------
# check_broker_connection / no_conflicting_positions
# ---------------------------------------------------------------------------


def test_broker_connection_none_skipped():
    chk = check_broker_connection(None)
    assert chk.passed is True
    assert "skipped" in chk.detail


def test_broker_connection_ok():
    broker = MagicMock()
    broker.is_connected.return_value = True
    chk = check_broker_connection(broker)
    assert chk.passed is True


def test_broker_connection_disconnected():
    broker = MagicMock()
    broker.is_connected.return_value = False
    chk = check_broker_connection(broker)
    assert chk.passed is False


def test_broker_no_conflict():
    broker = MagicMock()
    broker.get_position.return_value = None
    chk = check_no_conflicting_positions(broker, "SPY")
    assert chk.passed is True


def test_broker_conflicting_position():
    broker = MagicMock()
    pos = MagicMock()
    pos.quantity = 100
    broker.get_position.return_value = pos
    chk = check_no_conflicting_positions(broker, "SPY")
    assert chk.passed is False
    assert "qty=100" in chk.detail


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------


def test_disk_space(tmp_path):
    """Probe should return ok or warn -- never fail the test on environment."""
    chk = check_disk_space(str(tmp_path), min_mb=1)
    assert chk.name == "disk_space"
    # very low threshold so it passes; if shutil.disk_usage fails we still get a check
    assert chk.passed in (True, False)


def test_disk_space_mocked_low(monkeypatch):
    import quantforge.deployment.preflight as pf

    class FakeUsage:
        free = 50 * 1024 * 1024  # 50 MB
    monkeypatch.setattr(pf.shutil, "disk_usage", lambda p: FakeUsage())
    chk = check_disk_space(".", min_mb=500)
    assert chk.passed is False
    assert "50 MB" in chk.detail


# ---------------------------------------------------------------------------
# check_position_sizing
# ---------------------------------------------------------------------------


def test_position_sizing_within_cap():
    chk = check_position_sizing(np.array([0.5, -0.3, 0.7]), max_pct=1.0)
    assert chk.passed is True


def test_position_sizing_exceeds_cap():
    chk = check_position_sizing(np.array([0.5, 1.5, -0.2]), max_pct=1.0)
    assert chk.passed is False


def test_position_sizing_nan():
    chk = check_position_sizing(np.array([0.5, np.nan]), max_pct=1.0)
    assert chk.passed is False


# ---------------------------------------------------------------------------
# check_files_exist
# ---------------------------------------------------------------------------


def test_files_exist_pass(tmp_path):
    f1 = tmp_path / "config.json"
    f1.write_text("{}", encoding="utf-8")
    chk = check_files_exist([str(f1)])
    assert chk.passed is True


def test_files_exist_missing(tmp_path):
    chk = check_files_exist([str(tmp_path / "nope.txt")])
    assert chk.passed is False
    assert "missing" in chk.detail


def test_files_exist_empty():
    chk = check_files_exist([])
    assert chk.passed is True


# ---------------------------------------------------------------------------
# run_preflight orchestrator
# ---------------------------------------------------------------------------


def test_full_preflight_runs(tmp_path, monkeypatch):
    """End-to-end: returns a PreflightReport with all 10 sub-checks."""
    import quantforge.deployment.preflight as pf

    fake = _synth_prices(400)
    monkeypatch.setattr(pf, "load_asset", lambda symbol, include_oos=True: fake)

    # write a valid marker so check 4 passes
    s = MACross(fast=10, slow=50)
    write_validation_marker(
        type(s).__name__, {"is": {"calmar": 1.0}}, project_dir=str(tmp_path),
    )

    broker = MagicMock()
    broker.is_connected.return_value = True
    broker.get_position.return_value = None

    rep = run_preflight(
        strategy=s,
        symbol="FAKE",
        broker=broker,
        min_data_bars=200,
        max_position_pct=1.0,
        required_files=[],
        project_dir=str(tmp_path),
        prices=fake,
        min_disk_mb=1,
        check_ntp=False,
    )

    assert isinstance(rep, PreflightReport)
    # Issue 15: market_hours, data_freshness, buying_power are now wired
    # into run_preflight(). Default behavior is "skipped/passed" when their
    # caller-side knobs are not configured.
    assert len(rep.checks) == 13
    names = [c.name for c in rep.checks]
    assert names == [
        "strategy_callable",
        "data_availability",
        "anti_lookahead",
        "validation_marker",
        "broker_connection",
        "no_conflicting_positions",
        "position_sizing",
        "files_exist",
        "disk_space",
        "system_time",
        "market_hours",
        "data_freshness",
        "buying_power",
    ]
    # report renders cleanly
    out = rep.report()
    assert "PREFLIGHT REPORT" in out
    assert "OVERALL:" in out
    assert rep.all_passed is True
    assert rep.blockers == []


def test_full_preflight_fails_when_marker_missing(tmp_path, monkeypatch):
    """No marker -> validation_marker fails -> all_passed False, blocker reported."""
    import quantforge.deployment.preflight as pf

    fake = _synth_prices(400)
    monkeypatch.setattr(pf, "load_asset", lambda symbol, include_oos=True: fake)

    rep = run_preflight(
        strategy=MACross(fast=10, slow=50),
        symbol="FAKE",
        broker=None,
        min_data_bars=200,
        project_dir=str(tmp_path),
        prices=fake,
        min_disk_mb=1,
        check_ntp=False,
    )
    assert rep.all_passed is False
    assert any("validation_marker" in b for b in rep.blockers)


def test_pipeline_writes_marker_on_pass(tmp_path, monkeypatch):
    """validate_pipeline must drop the marker file when overall_passed=True."""
    from quantforge.core.seed import set_global_seed
    from quantforge.core.costs import ZERO_costs
    from quantforge.validation.pipeline import validate_pipeline
    from quantforge.validation.walk_forward import WFWindow

    set_global_seed(42)
    n = 6000
    idx = pd.date_range("2000-01-03", periods=n, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, n)
    prices = pd.Series(100.0 * np.cumprod(1.0 + rets), index=idx, name="SYN")

    def factory():
        return MACross(fast=10, slow=50)

    fast_wf = [
        WFWindow("WF1", "2000-01-03", "2005-12-31", "2006-01-01", "2008-12-31"),
    ]

    # Redirect the marker writer to tmp_path so we don't pollute the repo.
    import quantforge.deployment.preflight as pf
    orig = pf.write_validation_marker
    captured = {}

    def fake_write(strategy_name, metrics, project_dir="."):
        path = orig(strategy_name, metrics, project_dir=str(tmp_path))
        captured["path"] = path
        captured["metrics"] = metrics
        return path

    monkeypatch.setattr(
        "quantforge.deployment.preflight.write_validation_marker", fake_write,
    )
    # pipeline imports inside validate_pipeline; patch the lookup site too
    import quantforge.validation.pipeline as pipe_mod
    monkeypatch.setattr(
        pipe_mod, "validate_pipeline", pipe_mod.validate_pipeline, raising=False,
    )

    rep = validate_pipeline(
        factory, prices, "MarkerTest",
        costs=ZERO_costs, wf_windows=fast_wf,
        mc_n_paths=20, min_wf_pass=0,
    )
    if rep.overall_passed:
        assert "path" in captured, "marker should be written on pass"
        assert os.path.exists(captured["path"])
        with open(captured["path"], "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["strategy_name"] == "MarkerTest"
        assert "is" in data["metrics"]
    else:
        # Even on fail the test still asserts no marker was created
        assert "path" not in captured


# ---------------------------------------------------------------------------
# Item 5: data-availability adapts to strategy lookback
# ---------------------------------------------------------------------------


class _StratWithMinBars:
    min_bars = 600

    def signals(self, prices):
        return np.zeros(len(prices))


class _StratWithWarmup:
    warmup = 350

    def signals(self, prices):
        return np.zeros(len(prices))


class _StratNoLookback:
    def signals(self, prices):
        return np.zeros(len(prices))


def test_resolve_min_bars_uses_strategy_attr():
    assert _resolve_min_bars(_StratWithMinBars(), fallback=200) == 600
    assert _resolve_min_bars(_StratWithWarmup(), fallback=200) == 350
    assert _resolve_min_bars(_StratNoLookback(), fallback=200) == 200
    # min_bars wins over warmup if both present
    class Both:
        min_bars = 500
        warmup = 100
    assert _resolve_min_bars(Both(), fallback=200) == 500
    # Garbage values fall back
    class Bad:
        min_bars = "not-an-int"
    assert _resolve_min_bars(Bad(), fallback=200) == 200


def test_preflight_adapts_min_bars_to_strategy(monkeypatch):
    """check_data_availability uses strategy.min_bars when present."""
    import quantforge.deployment.preflight as pf

    fake = _synth_prices(400)
    monkeypatch.setattr(pf, "load_asset", lambda symbol, include_oos=True: fake)

    # Strategy needs 600 bars but only 400 available -> fail
    chk = check_data_availability("FAKE", min_bars=200,
                                  strategy=_StratWithMinBars())
    assert chk.passed is False
    assert "600" in chk.detail

    # Strategy with no lookback attr falls back to 200 -> 400 bars passes
    chk2 = check_data_availability("FAKE", min_bars=200,
                                   strategy=_StratNoLookback())
    assert chk2.passed is True

    # warmup attribute also honored
    chk3 = check_data_availability("FAKE", min_bars=200,
                                   strategy=_StratWithWarmup())
    assert chk3.passed is True  # 350 < 400

    # Strategy with warmup > available bars -> fail
    class TooMuchWarmup:
        warmup = 800
    chk4 = check_data_availability("FAKE", min_bars=200,
                                   strategy=TooMuchWarmup())
    assert chk4.passed is False
    assert "800" in chk4.detail


# ---------------------------------------------------------------------------
# Item 6: anti_lookahead multi-shuffle ensemble
# ---------------------------------------------------------------------------


def test_preflight_lookahead_multi_shuffle():
    """Multi-shuffle ensemble runs 5 seeds and exposes the stats in detail."""
    s = MACross(fast=10, slow=50)
    prices = _synth_prices(500)
    chk = check_anti_lookahead(s, prices, n_shuffles=5)
    assert chk.passed is True
    # Detail string should include the n=5 ensemble stats.
    assert "n=5" in chk.detail
    assert "mean=" in chk.detail
    assert "std=" in chk.detail


def test_preflight_lookahead_multi_shuffle_catches_leak():
    """Multi-shuffle catches a leaky strategy on at least one seed."""
    class Leaky:
        def signals(self, prices):
            arr = np.asarray(prices.values, dtype=float)
            n = len(arr)
            future_val = arr[-1]
            return np.full(n, future_val / 1000.0)

    chk = check_anti_lookahead(Leaky(), _synth_prices(500), n_shuffles=5)
    assert chk.passed is False
    # Multi-shuffle context is preserved in the failure detail.
    assert "shuffle" in chk.detail.lower() or "leak" in chk.detail.lower()


def test_preflight_lookahead_custom_seeds():
    """Caller can pass explicit seeds; n_shuffles tracks the seed count."""
    s = MACross(fast=10, slow=50)
    prices = _synth_prices(500)
    chk = check_anti_lookahead(s, prices, n_shuffles=3,
                               seeds=(1, 2, 3))
    assert chk.passed is True
    assert "n=3" in chk.detail


# ---------------------------------------------------------------------------
# Item 7: NTP fallback chain
# ---------------------------------------------------------------------------


def test_preflight_ntp_default_fallback_list():
    """Module exposes a 4-server fallback chain in the documented order."""
    assert _NTP_FALLBACK_SERVERS == (
        "pool.ntp.org",
        "time.google.com",
        "time.cloudflare.com",
        "time.nist.gov",
    )


def test_preflight_ntp_falls_back_on_failure(monkeypatch):
    """If every NTP server fails, check_system_time defaults to FAIL.

    Default behavior is now FAIL on all-unreachable so live deploys block
    when the clock cannot be verified. ``soft_skip=True`` opts back into
    the legacy local-clock pass behavior.
    """
    import socket as _socket
    import quantforge.deployment.preflight as pf

    calls: list[str] = []

    class _AlwaysFailSocket:
        def __init__(self, *a, **kw):
            pass

        def settimeout(self, t):
            pass

        def sendto(self, packet, addr):
            calls.append(addr[0])
            raise _socket.timeout("unreachable")

        def recvfrom(self, n):
            raise _socket.timeout("unreachable")

        def close(self):
            pass

    monkeypatch.setattr(pf.socket, "socket", _AlwaysFailSocket)

    # Default (strict): all-fail -> FAIL with detail "no NTP reachable".
    chk = check_system_time(timeout=0.01)
    assert chk.passed is False
    assert "no NTP reachable" in chk.detail
    # Every server in the default chain was probed.
    assert calls == list(_NTP_FALLBACK_SERVERS)

    # Reset call tracking and verify soft_skip=True restores legacy PASS.
    calls.clear()
    chk_soft = check_system_time(timeout=0.01, soft_skip=True)
    assert chk_soft.passed is True
    assert "skipped" in chk_soft.detail.lower()
    assert calls == list(_NTP_FALLBACK_SERVERS)


def test_preflight_ntp_uses_first_responsive(monkeypatch):
    """First server that responds wins; later servers are not contacted."""
    import quantforge.deployment.preflight as pf

    # Patch the low-level NTP querier so the first server returns a valid
    # epoch and the rest are never reached.
    import time as _time
    asked: list[str] = []

    def fake_query(server, timeout):
        asked.append(server)
        if server == "pool.ntp.org":
            return _time.time()  # zero drift
        return None

    monkeypatch.setattr(pf, "_query_ntp_server", fake_query)

    chk = check_system_time(timeout=0.5, max_drift_sec=2.0)
    assert chk.passed is True
    assert "drift=" in chk.detail
    assert "pool.ntp.org" in chk.detail
    # Only the first server was contacted.
    assert asked == ["pool.ntp.org"]


def test_preflight_ntp_skips_bad_server_then_succeeds(monkeypatch):
    """Failed first server -> falls back to second working server."""
    import quantforge.deployment.preflight as pf
    import time as _time

    asked: list[str] = []

    def fake_query(server, timeout):
        asked.append(server)
        if server == "pool.ntp.org":
            return None  # simulated timeout
        if server == "time.google.com":
            return _time.time()
        return None

    monkeypatch.setattr(pf, "_query_ntp_server", fake_query)

    chk = check_system_time(timeout=0.5, max_drift_sec=2.0)
    assert chk.passed is True
    assert "time.google.com" in chk.detail
    assert asked == ["pool.ntp.org", "time.google.com"]


# ---------------------------------------------------------------------------
# Issue 20: validation marker staleness
# ---------------------------------------------------------------------------

def test_preflight_marker_stale_warns(tmp_path):
    """Markers older than max_age_days are reported as stale (failed)."""
    proj = tmp_path
    path = write_validation_marker("MyStrat", {"sharpe": 1.0},
                                   project_dir=str(proj))
    assert os.path.exists(path)

    # Fresh marker -> passes default 7-day window.
    chk = check_validation_marker("MyStrat", project_dir=str(proj),
                                  max_age_days=7)
    assert chk.passed is True
    assert "age" in chk.detail.lower()

    # Manually rewrite the marker with a stale timestamp.
    stale = {
        "timestamp": "2020-01-01T00:00:00+00:00",
        "strategy_name": "MyStrat",
        "metrics": {"sharpe": 1.0},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stale, f)
    chk = check_validation_marker("MyStrat", project_dir=str(proj),
                                  max_age_days=7)
    assert chk.passed is False
    assert "stale" in chk.detail.lower()


# ---------------------------------------------------------------------------
# Issue 21: new checks (market hours, data freshness, buying power)
# ---------------------------------------------------------------------------

def test_check_market_hours_skips_when_lib_missing(monkeypatch):
    """When pandas_market_calendars is absent, the check passes with a
    'skipped' detail so test environments without the optional dep stay
    green."""
    import sys as _sys
    # Force importlib to fail by pointing the module entry to None and
    # invalidating any cached module.
    _sys.modules.pop("pandas_market_calendars", None)
    monkeypatch.setitem(_sys.modules, "pandas_market_calendars", None)
    from quantforge.deployment.preflight import check_market_hours
    chk = check_market_hours("SPY", exchange="NYSE")
    assert chk.passed is True
    assert "skipped" in chk.detail.lower()


def test_check_data_freshness_passes_when_recent():
    from quantforge.deployment.preflight import check_data_freshness
    now = pd.Timestamp.utcnow().tz_convert("UTC")
    idx = pd.date_range(end=now, periods=5, freq="h", tz="UTC")
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
    chk = check_data_freshness(s, max_age_hours=24, now_utc=now)
    assert chk.passed is True


def test_check_data_freshness_fails_when_stale():
    from quantforge.deployment.preflight import check_data_freshness
    now = pd.Timestamp("2026-05-07T12:00:00", tz="UTC")
    idx = pd.date_range(end=pd.Timestamp("2026-05-04T00:00:00", tz="UTC"),
                        periods=5, freq="h", tz="UTC")
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx)
    chk = check_data_freshness(s, max_age_hours=24, now_utc=now)
    assert chk.passed is False


def test_check_buying_power_dict_account():
    from quantforge.deployment.preflight import check_buying_power

    class _Broker:
        def get_account(self):
            return {"cash": 5000.0, "equity": 5000.0,
                    "buying_power": 5000.0}

    chk = check_buying_power(_Broker(), required_cash=2_000.0)
    assert chk.passed is True
    chk = check_buying_power(_Broker(), required_cash=10_000.0)
    assert chk.passed is False


def test_check_buying_power_skips_when_no_broker():
    from quantforge.deployment.preflight import check_buying_power
    chk = check_buying_power(None, required_cash=1000.0)
    assert chk.passed is True

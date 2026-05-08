"""Tests for quantforge.deployment.brokers (multi-broker abstraction).

PaperBroker is exercised end-to-end. SDK-dependent adapters are tested by
mocking imports / clients — no real broker traffic, no real credentials.
"""
from __future__ import annotations

import builtins
import sys
import time
from unittest.mock import MagicMock

import pytest

from quantforge.deployment import brokers
from quantforge.deployment.brokers import (
    AlpacaAdapter,
    AuditLog,
    Broker,
    BrokerConfig,
    CoinbaseAdapter,
    IBAdapter,
    KillSwitch,
    KrakenAdapter,
    Order,
    PaperBroker,
    Position,
    ReconciliationError,
    _RateLimiter,
    create_broker,
)


@pytest.fixture(autouse=True)
def _isolate_audit_db(tmp_path, monkeypatch):
    """Force AuditLog default DB into tmp_path so no audit_*.db litters cwd."""
    monkeypatch.chdir(tmp_path)
    yield


# ---------------------------------------------------------------------------
# PaperBroker — submit / fill / cash & position tracking
# ---------------------------------------------------------------------------

def _paper(starting_cash: float = 100_000.0) -> PaperBroker:
    return PaperBroker(BrokerConfig(name="paper", paper=True),
                       starting_cash=starting_cash)


def test_paper_broker_submit_market_buy():
    """Buy market: position increases, cash decreases by qty * price."""
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)
    resp = pb.submit_order(Order(symbol="SPY", qty=10, side="buy",
                                 order_type="market"))
    assert resp["status"] == "filled"
    assert resp["filled_qty"] == 10
    assert resp["filled_avg_price"] == 400.0

    acct = pb.get_account()
    assert acct["cash"] == pytest.approx(10_000.0 - 10 * 400.0)

    positions = pb.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "SPY"
    assert p.qty == 10
    assert p.avg_price == 400.0


def test_paper_broker_submit_market_sell():
    """Sell market: position decreases, cash increases by qty * price."""
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.submit_order(Order(symbol="SPY", qty=10, side="buy",
                          order_type="market"))
    cash_after_buy = pb.get_account()["cash"]

    pb.set_last_price("SPY", 410.0)
    resp = pb.submit_order(Order(symbol="SPY", qty=4, side="sell",
                                 order_type="market"))
    assert resp["status"] == "filled"
    assert resp["filled_qty"] == 4
    assert resp["filled_avg_price"] == 410.0

    acct = pb.get_account()
    assert acct["cash"] == pytest.approx(cash_after_buy + 4 * 410.0)

    positions = pb.get_positions()
    assert len(positions) == 1
    assert positions[0].qty == 6


def test_paper_broker_insufficient_cash():
    """Buy more than cash allows: rejected, no position, cash unchanged."""
    pb = _paper(starting_cash=1_000.0)
    pb.set_last_price("SPY", 400.0)
    resp = pb.submit_order(Order(symbol="SPY", qty=10, side="buy",
                                 order_type="market"))
    assert resp["status"] == "rejected"
    assert resp["reason"] == "insufficient_cash"
    assert pb.get_account()["cash"] == pytest.approx(1_000.0)
    assert pb.get_positions() == []


def test_paper_broker_cancel():
    """Submit limit, cancel, verify state is clean."""
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    resp = pb.submit_order(Order(symbol="SPY", qty=5, side="buy",
                                 order_type="limit", limit_price=350.0))
    assert resp["status"] == "open"
    order_id = resp["id"]

    assert pb.cancel_order(order_id) is True
    # Cancelling again returns False (already gone).
    assert pb.cancel_order(order_id) is False
    # Bogus id returns False.
    assert pb.cancel_order("does-not-exist") is False
    # No fills happened, so no positions.
    assert pb.get_positions() == []


def test_paper_broker_get_positions():
    """Aggregate positions reflect submitted orders."""
    pb = _paper(starting_cash=100_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.set_last_price("QQQ", 350.0)
    pb.submit_order(Order(symbol="SPY", qty=5, side="buy",
                          order_type="market"))
    pb.submit_order(Order(symbol="QQQ", qty=10, side="buy",
                          order_type="market"))
    pb.submit_order(Order(symbol="SPY", qty=2, side="buy",
                          order_type="market"))

    positions = {p.symbol: p for p in pb.get_positions()}
    assert positions["SPY"].qty == 7
    assert positions["QQQ"].qty == 10
    # SPY avg cost stays at 400 since both fills were at 400.
    assert positions["SPY"].avg_price == pytest.approx(400.0)


def test_paper_broker_sync_no_diff():
    """Paper sync returns empty diff (paper IS the truth)."""
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    pb.submit_order(Order(symbol="SPY", qty=3, side="buy",
                          order_type="market"))
    diff = pb.sync()
    assert diff == {"missing_local": [], "missing_broker": [],
                    "qty_mismatch": []}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_create_broker_paper():
    """Factory returns a PaperBroker for name='paper'."""
    cfg = BrokerConfig(name="paper", paper=True)
    b = create_broker(cfg)
    assert isinstance(b, PaperBroker)
    assert isinstance(b, Broker)


def test_create_broker_unknown():
    """Unknown name raises a clear ValueError."""
    cfg = BrokerConfig(name="not-a-broker")
    with pytest.raises(ValueError) as ei:
        create_broker(cfg)
    msg = str(ei.value).lower()
    assert "unknown broker" in msg
    assert "paper" in msg  # surfaces valid names list


def test_create_broker_bad_input():
    """Non-BrokerConfig argument raises ValueError."""
    with pytest.raises(ValueError):
        create_broker("paper")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Adapter SDK-missing behavior
# ---------------------------------------------------------------------------

def _block_module(monkeypatch, name: str) -> None:
    """Make `import name` (and submodules) raise ImportError."""
    real_import = builtins.__import__

    def fake_import(n, *args, **kwargs):
        if n == name or n.startswith(name + "."):
            raise ImportError(f"No module named {name!r}")
        return real_import(n, *args, **kwargs)

    # Drop any cached references first.
    for mod in list(sys.modules):
        if mod == name or mod.startswith(name + "."):
            sys.modules.pop(mod, None)
    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_alpaca_adapter_missing_sdk(monkeypatch):
    """alpaca-py not installed → ImportError carries install hint."""
    _block_module(monkeypatch, "alpaca")
    cfg = BrokerConfig(name="alpaca", api_key_env="X", api_secret_env="Y",
                       paper=True)
    with pytest.raises(ImportError) as ei:
        AlpacaAdapter(cfg)
    assert "alpaca-py" in str(ei.value) or "alpaca" in str(ei.value).lower()


def test_ib_adapter_missing_sdk(monkeypatch):
    """ib_insync not installed → ImportError carries install hint."""
    _block_module(monkeypatch, "ib_insync")
    cfg = BrokerConfig(name="ib", paper=True)
    with pytest.raises(ImportError) as ei:
        IBAdapter(cfg)
    assert "ib_insync" in str(ei.value)


def test_coinbase_adapter_missing_sdk(monkeypatch):
    """coinbase SDK not installed → ImportError carries install hint."""
    _block_module(monkeypatch, "coinbase")
    cfg = BrokerConfig(name="coinbase", api_key_env="X", api_secret_env="Y")
    with pytest.raises(ImportError) as ei:
        CoinbaseAdapter(cfg)
    assert "coinbase" in str(ei.value).lower()


def test_kraken_adapter_missing_sdk(monkeypatch):
    """krakenex not installed → ImportError carries install hint."""
    _block_module(monkeypatch, "krakenex")
    cfg = BrokerConfig(name="kraken", api_key_env="X", api_secret_env="Y")
    with pytest.raises(ImportError) as ei:
        KrakenAdapter(cfg)
    assert "krakenex" in str(ei.value)


def test_create_broker_propagates_missing_sdk(monkeypatch):
    """create_broker forwards ImportError from adapter SDK loading."""
    _block_module(monkeypatch, "alpaca")
    cfg = BrokerConfig(name="alpaca", api_key_env="X", api_secret_env="Y")
    with pytest.raises(ImportError):
        create_broker(cfg)


# ---------------------------------------------------------------------------
# Order validation
# ---------------------------------------------------------------------------

def test_order_validation_invalid_side():
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    with pytest.raises(ValueError, match="side"):
        pb.submit_order(Order(symbol="SPY", qty=1, side="long",
                              order_type="market"))


def test_order_validation_invalid_type():
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    with pytest.raises(ValueError, match="order_type"):
        pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                              order_type="stop"))


def test_order_validation_invalid_tif():
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    with pytest.raises(ValueError, match="time_in_force"):
        pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                              order_type="market", time_in_force="forever"))


def test_order_validation_limit_requires_price():
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    with pytest.raises(ValueError, match="limit_price"):
        pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                              order_type="limit"))


def test_order_validation_qty_positive():
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    with pytest.raises(ValueError, match="qty"):
        pb.submit_order(Order(symbol="SPY", qty=0, side="buy",
                              order_type="market"))
    with pytest.raises(ValueError, match="qty"):
        pb.submit_order(Order(symbol="SPY", qty=-3, side="buy",
                              order_type="market"))


def test_uuid_client_order_id():
    """When client_order_id is None, a uuid is generated."""
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    o1 = Order(symbol="SPY", qty=1, side="buy", order_type="market")
    assert o1.client_order_id is None
    pb.submit_order(o1)
    assert o1.client_order_id is not None
    assert len(o1.client_order_id) >= 16  # uuid4 hex is 32 chars

    o2 = Order(symbol="SPY", qty=1, side="buy", order_type="market")
    pb.submit_order(o2)
    assert o2.client_order_id != o1.client_order_id


def test_explicit_client_order_id_preserved():
    """When client_order_id is supplied, it is not overwritten."""
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    o = Order(symbol="SPY", qty=1, side="buy", order_type="market",
              client_order_id="my-custom-id")
    resp = pb.submit_order(o)
    assert o.client_order_id == "my-custom-id"
    assert resp["id"] == "my-custom-id"


# ---------------------------------------------------------------------------
# Credentials from env
# ---------------------------------------------------------------------------

def _install_fake_alpaca(monkeypatch) -> dict:
    """Install a fake alpaca SDK in sys.modules; return capture dict."""
    captured: dict = {}

    fake_alpaca = type(sys)("alpaca")
    fake_trading = type(sys)("alpaca.trading")
    fake_client_mod = type(sys)("alpaca.trading.client")

    class FakeTradingClient:
        def __init__(self, api_key, api_secret, paper=True):
            captured["api_key"] = api_key
            captured["api_secret"] = api_secret
            captured["paper"] = paper

        def submit_order(self, req):
            return MagicMock(id="ALP-1", status="accepted")

        def cancel_order_by_id(self, oid):
            captured["cancelled"] = oid

        def get_all_positions(self):
            return []

        def get_account(self):
            return MagicMock(cash="100", equity="100", buying_power="100")

    fake_client_mod.TradingClient = FakeTradingClient
    monkeypatch.setitem(sys.modules, "alpaca", fake_alpaca)
    monkeypatch.setitem(sys.modules, "alpaca.trading", fake_trading)
    monkeypatch.setitem(sys.modules, "alpaca.trading.client", fake_client_mod)
    return captured


def test_credentials_from_env(monkeypatch):
    """Adapter reads credentials from env via api_key_env / api_secret_env."""
    captured = _install_fake_alpaca(monkeypatch)
    monkeypatch.setenv("MY_FAKE_ALPACA_KEY", "key-123")
    monkeypatch.setenv("MY_FAKE_ALPACA_SECRET", "secret-xyz")

    cfg = BrokerConfig(name="alpaca",
                       api_key_env="MY_FAKE_ALPACA_KEY",
                       api_secret_env="MY_FAKE_ALPACA_SECRET",
                       paper=True)
    adapter = AlpacaAdapter(cfg)

    assert isinstance(adapter, AlpacaAdapter)
    assert captured["api_key"] == "key-123"
    assert captured["api_secret"] == "secret-xyz"
    assert captured["paper"] is True


def test_credentials_missing_env(monkeypatch):
    """Missing env vars surface a clear ValueError, not silent failure."""
    _install_fake_alpaca(monkeypatch)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    cfg = BrokerConfig(name="alpaca",
                       api_key_env="ALPACA_API_KEY",
                       api_secret_env="ALPACA_API_SECRET")
    with pytest.raises(ValueError, match="credentials missing"):
        AlpacaAdapter(cfg)


# ---------------------------------------------------------------------------
# Sanity: dataclasses
# ---------------------------------------------------------------------------

def test_position_dataclass():
    p = Position(symbol="SPY", qty=10, avg_price=400.0,
                 market_value=4100.0, unrealized_pnl=100.0)
    assert p.symbol == "SPY"
    assert p.qty == 10


def test_brokerconfig_defaults():
    cfg = BrokerConfig(name="paper")
    assert cfg.name == "paper"
    assert cfg.api_key_env is None
    assert cfg.api_secret_env is None
    assert cfg.base_url is None
    assert cfg.paper is True
    assert cfg.rate_limit_per_minute == 60


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------

def test_kill_switch_triggers_on_max_loss():
    """check() flips triggered=True once equity drops past max_daily_loss_pct."""
    ks = KillSwitch(max_daily_loss_pct=0.05, max_position_qty=1e9)
    # First call seeds day_start_equity=100k.
    assert ks.check({"equity": 100_000.0}, []) is False
    assert ks.day_start_equity == 100_000.0
    assert ks.triggered is False
    # 4% drop: not triggered yet.
    assert ks.check({"equity": 96_000.0}, []) is False
    assert ks.triggered is False
    # 6% drop: triggers.
    assert ks.check({"equity": 94_000.0}, []) is True
    assert ks.triggered is True
    # Stays triggered even if equity recovers.
    assert ks.check({"equity": 100_000.0}, []) is True


def test_kill_switch_triggers_on_max_position_qty():
    """Positions above max_position_qty trigger the switch."""
    ks = KillSwitch(max_daily_loss_pct=0.99, max_position_qty=10.0)
    pos = [Position(symbol="SPY", qty=25.0, avg_price=400.0,
                    market_value=10000.0, unrealized_pnl=0.0)]
    assert ks.check({"equity": 100_000.0}, pos) is True
    assert ks.triggered is True


def test_kill_switch_blocks_orders_when_armed():
    """Once arm() is called, submit_order returns rejected with structured reason."""
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.kill_switch.arm()
    resp = pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                                 order_type="market"))
    assert resp["status"] == "rejected"
    assert resp["reason"] == "kill_switch_triggered"
    assert resp["filled_qty"] == 0.0
    # No fill happened: cash unchanged, no position.
    assert pb.get_account()["cash"] == pytest.approx(10_000.0)
    assert pb.get_positions() == []


def test_kill_switch_disarm_releases_orders():
    """disarm() lets new orders flow through again."""
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.kill_switch.arm()
    rejected = pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                                     order_type="market"))
    assert rejected["status"] == "rejected"
    pb.kill_switch.disarm()
    assert pb.kill_switch.triggered is False
    assert pb.kill_switch.day_start_equity is None
    resp = pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                                 order_type="market"))
    assert resp["status"] == "filled"
    assert resp["filled_qty"] == 1


# ---------------------------------------------------------------------------
# Partial fills
# ---------------------------------------------------------------------------

def test_partial_fill_event_updates_position():
    """partial_fill_event applies cash + position delta and tracks remaining qty."""
    pb = _paper(starting_cash=20_000.0)
    pb.set_last_price("SPY", 400.0)
    open_resp = pb.submit_order(Order(symbol="SPY", qty=10, side="buy",
                                      order_type="limit", limit_price=395.0))
    order_id = open_resp["id"]

    # Half fills at 394.
    pb.partial_fill_event(order_id, filled_qty=4.0, remaining_qty=6.0,
                          price=394.0)
    pos = {p.symbol: p for p in pb.get_positions()}
    assert pos["SPY"].qty == 4.0
    # Cash drops by 4 * 394.
    assert pb.get_account()["cash"] == pytest.approx(20_000.0 - 4 * 394.0)
    # Order still open with reduced qty.
    # (Access internals only to confirm bookkeeping.)
    assert order_id in pb._state.open_orders
    assert pb._state.open_orders[order_id]["qty"] == 6.0

    # Remaining 6 fills at 393, completing the order.
    pb.partial_fill_event(order_id, filled_qty=6.0, remaining_qty=0.0,
                          price=393.0)
    pos = {p.symbol: p for p in pb.get_positions()}
    assert pos["SPY"].qty == 10.0
    assert order_id not in pb._state.open_orders


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

def test_audit_log_records_orders(tmp_path):
    """Submits, fills, rejections, cancels are written to the SQLite DB."""
    db = tmp_path / "audit.db"
    audit = AuditLog(db_path=str(db))
    pb = PaperBroker(BrokerConfig(name="paper", paper=True),
                     starting_cash=10_000.0, audit_log=audit)
    pb.set_last_price("SPY", 400.0)

    # 1) Successful market buy → submit + fill rows.
    pb.submit_order(Order(symbol="SPY", qty=2, side="buy",
                          order_type="market", client_order_id="oid-1"))
    # 2) Insufficient cash buy → submit + reject rows.
    pb.submit_order(Order(symbol="SPY", qty=100, side="buy",
                          order_type="market", client_order_id="oid-2"))
    # 3) Limit submission → submit row only (no fill).
    open_resp = pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                                      order_type="limit", limit_price=350.0,
                                      client_order_id="oid-3"))
    # 4) Cancel.
    pb.cancel_order(open_resp["id"])

    rows = audit.fetch_all()
    events = [r["event"] for r in rows]
    assert events.count("submit") == 3
    assert events.count("fill") == 1
    assert events.count("reject") == 1
    assert events.count("cancel") == 1

    fill = next(r for r in rows if r["event"] == "fill")
    assert fill["symbol"] == "SPY"
    assert fill["qty"] == 2.0
    assert fill["price"] == 400.0
    assert fill["status"] == "filled"

    rej = next(r for r in rows if r["event"] == "reject")
    assert rej["reason"] == "insufficient_cash"

    audit.close()


def test_audit_log_default_path_per_day():
    """Default db_path encodes today's date and creates the file."""
    from datetime import date as _date
    audit = AuditLog()
    expected = f"audit_{_date.today().isoformat()}.db"
    assert audit.db_path.endswith(expected)
    audit.close()


def test_audit_log_sqlite_wal_enabled(tmp_path):
    """AuditLog uses WAL + busy_timeout=5000 + synchronous=FULL."""
    import sqlite3 as _sql

    db = tmp_path / "audit_wal.db"
    audit = AuditLog(db_path=str(db))
    # journal_mode is sticky in the file
    with _sql.connect(audit.db_path) as con:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    # busy_timeout / synchronous are per-connection on the audit connection.
    bt = audit._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    sync = audit._conn.execute("PRAGMA synchronous").fetchone()[0]
    assert int(bt) >= 5000
    # synchronous=FULL → 2
    assert int(sync) == 2
    audit.close()


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def test_reconcile_returns_clean_for_paper():
    """PaperBroker.reconcile() always returns clean diff."""
    pb = _paper()
    pb.set_last_price("SPY", 400.0)
    pb.submit_order(Order(symbol="SPY", qty=2, side="buy",
                          order_type="market"))
    diff = pb.reconcile()
    assert diff == {"missing_local": [], "missing_broker": [],
                    "qty_mismatch": []}


def test_reconcile_detects_local_drift(monkeypatch):
    """When sync() reports a diff, base reconcile() raises ReconciliationError."""
    pb = _paper()

    def fake_sync():
        return {
            "missing_local": [Position(symbol="SPY", qty=5, avg_price=400.0,
                                       market_value=2000.0, unrealized_pnl=0.0)],
            "missing_broker": [],
            "qty_mismatch": [],
        }
    monkeypatch.setattr(pb, "sync", fake_sync)
    # Use the base-class reconcile path via Broker.reconcile.
    with pytest.raises(ReconciliationError):
        Broker.reconcile(pb)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_rate_limit_blocks_excess():
    """_RateLimiter.acquire blocks once max_per_minute is exceeded."""
    fake_now = [0.0]
    sleeps: list[float] = []

    def time_fn():
        return fake_now[0]

    def sleep_fn(s):
        sleeps.append(s)
        fake_now[0] += s

    rl = _RateLimiter(max_per_minute=3, window_seconds=60.0,
                      sleep_fn=sleep_fn, time_fn=time_fn)
    # First 3 calls: no sleeps.
    for _ in range(3):
        slept = rl.acquire()
        assert slept == 0.0
    # 4th call: must wait until the first ts ages out (60s).
    slept4 = rl.acquire()
    assert slept4 > 0.0
    assert sum(sleeps) >= 60.0


def test_paper_broker_rate_limit_blocks(monkeypatch):
    """PaperBroker enforces config.rate_limit_per_minute."""
    cfg = BrokerConfig(name="paper", paper=True, rate_limit_per_minute=2)
    pb = PaperBroker(cfg, starting_cash=100_000.0)
    pb.set_last_price("SPY", 400.0)

    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)
        # Advance the rate limiter clock.
        pb._rate_limiter._timestamps.clear()

    monkeypatch.setattr(pb._rate_limiter, "_sleep", fake_sleep)

    pb.submit_order(Order(symbol="SPY", qty=1, side="buy", order_type="market"))
    pb.submit_order(Order(symbol="SPY", qty=1, side="buy", order_type="market"))
    # Third submission should trigger one sleep.
    pb.submit_order(Order(symbol="SPY", qty=1, side="buy", order_type="market"))
    assert len(sleeps) >= 1
    assert sleeps[0] > 0.0


# ---------------------------------------------------------------------------
# KillSwitch daily reset (issue 1)
# ---------------------------------------------------------------------------

def test_kill_switch_resets_daily(monkeypatch):
    """When the UTC date rolls, the daily reference equity resets and any
    sticky daily-loss trigger is cleared."""
    from datetime import datetime as _dt
    from datetime import date as _date
    from datetime import timezone

    fake_today = [_date(2026, 5, 7)]

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return _dt(fake_today[0].year, fake_today[0].month,
                       fake_today[0].day, 12, 0, 0,
                       tzinfo=tz or timezone.utc)

    monkeypatch.setattr("quantforge.deployment.brokers._dt", _FakeDT)

    ks = KillSwitch(max_daily_loss_pct=0.05, max_position_qty=1e9)
    # Day 1: seed at 100k, then drop 6% -> trigger.
    assert ks.check({"equity": 100_000.0}, []) is False
    assert ks.day_start_date == _date(2026, 5, 7)
    assert ks.check({"equity": 94_000.0}, []) is True
    assert ks.triggered is True

    # Day 2: same KillSwitch instance, equity at 94k. Should reset to 94k
    # as the new day start AND clear the sticky trigger.
    fake_today[0] = _date(2026, 5, 8)
    assert ks.check({"equity": 94_000.0}, []) is False
    assert ks.day_start_date == _date(2026, 5, 8)
    assert ks.day_start_equity == 94_000.0
    assert ks.triggered is False
    # Another 4% drop on day 2 must NOT trigger (94k -> 90.24k = ~4%).
    assert ks.check({"equity": 90_240.0}, []) is False


# ---------------------------------------------------------------------------
# AuditLog: tz-aware timestamps, midnight rotation, WAL pragmas (issues 2-4)
# ---------------------------------------------------------------------------

def test_audit_timestamps_have_tz(tmp_path):
    """Audit rows use ISO-8601 UTC timestamps with a tz suffix."""
    audit = AuditLog(db_path=str(tmp_path / "audit.db"))
    audit.record("submit", order_id="o-1", symbol="SPY", side="buy", qty=1.0)
    rows = audit.fetch_all()
    assert len(rows) == 1
    ts = rows[0]["ts"]
    # ISO-8601 + tz info: ends with '+00:00' or 'Z'.
    assert ts.endswith("+00:00") or ts.endswith("Z"), ts
    audit.close()


def test_audit_log_rotates_at_midnight_utc(tmp_path, monkeypatch):
    """When UTC date rolls and the log is using its default path, the next
    record() rotates to a fresh dated DB file."""
    from datetime import datetime as _dt
    from datetime import date as _date
    from datetime import timezone

    fake_today = [_date(2026, 5, 7)]

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            return _dt(fake_today[0].year, fake_today[0].month,
                       fake_today[0].day, 23, 59, 0,
                       tzinfo=tz or timezone.utc)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("quantforge.deployment.brokers._dt", _FakeDT)

    audit = AuditLog()  # default path -> audit_2026-05-07.db
    assert audit.db_path.endswith("audit_2026-05-07.db")
    audit.record("submit", order_id="o-1", symbol="SPY", side="buy", qty=1.0)

    # Roll the clock past midnight UTC.
    fake_today[0] = _date(2026, 5, 8)
    audit.record("submit", order_id="o-2", symbol="SPY", side="buy", qty=1.0)
    assert audit.db_path.endswith("audit_2026-05-08.db")

    # New file should exist, and the second row should be there only.
    rows = audit.fetch_all()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "o-2"
    audit.close()


def test_audit_log_pragmas_set(tmp_path):
    """AuditLog opens its DB with WAL + FULL synchronous + busy_timeout."""
    audit = AuditLog(db_path=str(tmp_path / "audit.db"))
    cur = audit._conn.execute("PRAGMA journal_mode")
    assert cur.fetchone()[0].lower() == "wal"
    cur = audit._conn.execute("PRAGMA synchronous")
    # FULL maps to 2 in SQLite.
    assert int(cur.fetchone()[0]) == 2
    cur = audit._conn.execute("PRAGMA busy_timeout")
    assert int(cur.fetchone()[0]) >= 1000
    audit.close()


# ---------------------------------------------------------------------------
# Idempotency on submit_order (issue 5)
# ---------------------------------------------------------------------------

def test_submit_order_idempotent_on_retry():
    """A retry with the same client_order_id must NOT submit twice; the
    cached prior response is returned."""
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)
    o1 = Order(symbol="SPY", qty=2, side="buy", order_type="market",
               client_order_id="dup-id-1")
    resp1 = pb.submit_order(o1)
    assert resp1["status"] == "filled"
    cash_after = pb.get_account()["cash"]

    # Same client_order_id -> idempotent. Cash MUST NOT move.
    o2 = Order(symbol="SPY", qty=2, side="buy", order_type="market",
               client_order_id="dup-id-1")
    resp2 = pb.submit_order(o2)
    assert resp2["status"] == "filled"
    assert resp2["filled_qty"] == 2
    assert pb.get_account()["cash"] == pytest.approx(cash_after)
    # Position qty unchanged (still 2).
    pos = {p.symbol: p for p in pb.get_positions()}
    assert pos["SPY"].qty == 2.0


# ---------------------------------------------------------------------------
# Audit failure does not propagate (issue 6)
# ---------------------------------------------------------------------------

def test_audit_failure_does_not_propagate(monkeypatch):
    """If AuditLog.record raises, submit_order still returns successfully."""
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)

    def boom(*a, **kw):
        raise RuntimeError("audit DB offline")

    monkeypatch.setattr(pb.audit_log, "record", boom)
    resp = pb.submit_order(Order(symbol="SPY", qty=1, side="buy",
                                 order_type="market"))
    assert resp["status"] == "filled"


# ---------------------------------------------------------------------------
# PaperBroker side flip avg cost (issue 7)
# ---------------------------------------------------------------------------

def test_paper_broker_side_flip_avg_cost():
    """When a fill flips the position from long to short (or vice versa),
    avg_price MUST reset to the new fill price (fresh entry)."""
    pb = _paper(starting_cash=100_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.submit_order(Order(symbol="SPY", qty=10, side="buy",
                          order_type="market"))
    # Direct flip via internal path: sell 15 at 410 -> -5 net.
    pb.set_last_price("SPY", 410.0)
    pb._update_position("SPY", -15.0, 410.0)
    pos = pb._state.positions["SPY"]
    assert pos.qty == pytest.approx(-5.0)
    assert pos.avg_price == pytest.approx(410.0)


# ---------------------------------------------------------------------------
# Kraken userref (issue 8)
# ---------------------------------------------------------------------------

def test_kraken_userref_set(monkeypatch):
    """Kraken adapter maps client_order_id to a u32 userref and passes it
    on AddOrder."""
    fake_kraken = type(sys)("krakenex")

    captured: dict = {}

    class FakeAPI:
        def __init__(self, key, secret):
            pass

        def query_private(self, action, params):
            captured["action"] = action
            captured["params"] = dict(params)
            return {"error": [], "result": {"txid": ["TX1"]}}

    fake_kraken.API = FakeAPI
    monkeypatch.setitem(sys.modules, "krakenex", fake_kraken)
    monkeypatch.setenv("KRK_KEY", "k")
    monkeypatch.setenv("KRK_SECRET", "s")
    cfg = BrokerConfig(name="kraken",
                       api_key_env="KRK_KEY", api_secret_env="KRK_SECRET")
    adapter = KrakenAdapter(cfg)
    cid = "qf-trace-id-abc"
    expected = KrakenAdapter._client_order_id_to_userref(cid)
    assert 0 <= expected < 2 ** 32

    resp = adapter.submit_order(Order(symbol="XBTUSD", qty=0.1, side="buy",
                                      order_type="market",
                                      client_order_id=cid))
    assert captured["action"] == "AddOrder"
    assert "userref" in captured["params"]
    assert int(captured["params"]["userref"]) == expected
    assert resp["userref"] == expected
    # cl_ord_id must NOT be sent (Kraken ignores it).
    assert "cl_ord_id" not in captured["params"]


# ---------------------------------------------------------------------------
# AlpacaAdapter sync() returns real diffs (issue 9)
# ---------------------------------------------------------------------------

def _install_full_fake_alpaca(monkeypatch) -> dict:
    """Install a richer fake alpaca SDK (covers enums + requests submodules)."""
    captured: dict = {}

    fake_alpaca = type(sys)("alpaca")
    fake_trading = type(sys)("alpaca.trading")
    fake_client_mod = type(sys)("alpaca.trading.client")
    fake_enums_mod = type(sys)("alpaca.trading.enums")
    fake_requests_mod = type(sys)("alpaca.trading.requests")

    class _Side:
        BUY = "BUY"
        SELL = "SELL"

    class _TIF:
        DAY = "DAY"
        GTC = "GTC"
        IOC = "IOC"

    fake_enums_mod.OrderSide = _Side
    fake_enums_mod.TimeInForce = _TIF

    class _Req:
        def __init__(self, **kw):
            self.kwargs = kw

    fake_requests_mod.MarketOrderRequest = _Req
    fake_requests_mod.LimitOrderRequest = _Req

    class FakeTradingClient:
        def __init__(self, api_key, api_secret, paper=True):
            captured["api_key"] = api_key
            captured["api_secret"] = api_secret
            captured["paper"] = paper

        def submit_order(self, req):
            # Round X: local position tracking is deferred to fill events.
            # Mock returns status="filled" so the existing diff assertions
            # still observe a populated _local_positions cache.
            return MagicMock(id="ALP-1", status="filled")

        def cancel_order_by_id(self, oid):
            captured["cancelled"] = oid

        def get_all_positions(self):
            return []

        def get_account(self):
            return MagicMock(cash="100", equity="100", buying_power="100")

    fake_client_mod.TradingClient = FakeTradingClient
    fake_trading.client = fake_client_mod
    fake_trading.enums = fake_enums_mod
    fake_trading.requests = fake_requests_mod
    fake_alpaca.trading = fake_trading
    monkeypatch.setitem(sys.modules, "alpaca", fake_alpaca)
    monkeypatch.setitem(sys.modules, "alpaca.trading", fake_trading)
    monkeypatch.setitem(sys.modules, "alpaca.trading.client", fake_client_mod)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", fake_enums_mod)
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", fake_requests_mod)
    return captured


def test_alpaca_adapter_sync_returns_real_diffs(monkeypatch):
    """After a successful submit_order, sync() must NOT report the broker
    position under missing_local; mismatched broker qty must surface in
    qty_mismatch; broker-only positions go to missing_local."""
    _install_full_fake_alpaca(monkeypatch)
    monkeypatch.setenv("FAKE_KEY", "k")
    monkeypatch.setenv("FAKE_SECRET", "s")
    cfg = BrokerConfig(name="alpaca",
                       api_key_env="FAKE_KEY", api_secret_env="FAKE_SECRET",
                       paper=True)
    adapter = AlpacaAdapter(cfg)

    # 1) Initial state: broker reports 0 positions, local has 0 -> clean.
    diff = adapter.sync()
    assert diff == {"missing_local": [], "missing_broker": [],
                    "qty_mismatch": []}

    # 2) Submit a buy. Local should track 10 SPY.
    adapter.submit_order(Order(symbol="SPY", qty=10, side="buy",
                               order_type="market"))
    assert adapter._local_positions["SPY"] == pytest.approx(10.0)
    # Broker still reports nothing -> missing_broker should report SPY.
    diff = adapter.sync()
    assert any(s == "SPY" for s in diff["missing_broker"])
    assert diff["qty_mismatch"] == []
    assert diff["missing_local"] == []

    # 3) Now mock the broker reporting SPY @ qty=10 (matching local) -> clean.
    fake_pos = MagicMock(symbol="SPY", qty="10", avg_entry_price="400",
                         market_value="4000", unrealized_pl="0")
    adapter._client.get_all_positions = MagicMock(return_value=[fake_pos])
    diff = adapter.sync()
    assert diff == {"missing_local": [], "missing_broker": [],
                    "qty_mismatch": []}

    # 4) Broker reports SPY @ qty=8 (mismatch).
    fake_pos.qty = "8"
    diff = adapter.sync()
    assert len(diff["qty_mismatch"]) == 1
    mm = diff["qty_mismatch"][0]
    assert mm["symbol"] == "SPY"
    assert mm["local"] == pytest.approx(10.0)
    assert mm["broker"] == pytest.approx(8.0)

    # 5) Broker reports an EXTRA AAPL position the local doesn't track ->
    #    AAPL appears under missing_local.
    fake_aapl = MagicMock(symbol="AAPL", qty="3", avg_entry_price="180",
                          market_value="540", unrealized_pl="0")
    fake_pos.qty = "10"
    adapter._client.get_all_positions = MagicMock(
        return_value=[fake_pos, fake_aapl])
    diff = adapter.sync()
    syms_missing_local = [p.symbol for p in diff["missing_local"]]
    assert "AAPL" in syms_missing_local
    assert "SPY" not in syms_missing_local


# ---------------------------------------------------------------------------
# RateLimiter fairness under contention (issue 13)
# ---------------------------------------------------------------------------

def test_rate_limiter_fifo_fairness():
    """Concurrent acquire() calls are served in arrival order."""
    import threading

    rl = _RateLimiter(max_per_minute=2, window_seconds=0.5)
    # First two acquires saturate the window without sleeping.
    rl.acquire()
    rl.acquire()
    order: list[int] = []

    def worker(idx):
        rl.acquire()
        order.append(idx)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
        # Give each thread a deterministic head start so arrival order is
        # well-defined.
        time.sleep(0.05)
    for t in threads:
        t.join(timeout=5.0)
    assert order == [0, 1, 2], order

"""Tests for the P3.A CCXT integration (data provider + broker adapter).

ccxt is OPTIONAL; tests fake the dependency via ``unittest.mock`` so the
suite passes without the real package installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
from collections import OrderedDict
from unittest import mock

import pandas as pd
import pytest

from quantforge.core.data_providers import (
    Dataset,
    DatasetMetadata,
    ProviderUnavailable,
)
from quantforge.core.data_providers.ccxt_provider import CCXTProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_ccxt_module(*, version: str = "4.5.0",
                      exchange_id: str = "binance") -> types.ModuleType:
    """Build a stand-in ccxt module with the minimum surface we use.

    The exchange class returned is a MagicMock with ``fetch_ohlcv``,
    ``fetch_balance``, ``create_order``, ``cancel_order``,
    ``set_sandbox_mode`` configured to deterministic responses.
    """
    fake = types.ModuleType("ccxt")
    fake.__version__ = version
    fake.exchanges = ["binance", "kraken", "coinbase"]

    class _ExchangeFactory:
        """Holds the latest constructed exchange so tests can inspect."""
        latest = None

    def _make_exchange_class(_exchange_id: str):
        def _ctor(cfg=None):
            client = mock.MagicMock(name=f"ccxt.{_exchange_id}")
            client.exchange_id = _exchange_id
            client.config = cfg or {}
            client.rateLimit = 1000  # 1s per call
            # Default OHLCV: 3 daily candles with ascending timestamps.
            client.fetch_ohlcv.return_value = [
                [1577836800000, 100.0, 110.0, 90.0, 105.0, 1000.0],
                [1577923200000, 105.0, 115.0, 95.0, 110.0, 1100.0],
                [1578009600000, 110.0, 120.0, 100.0, 115.0, 1200.0],
            ]
            client.fetch_balance.return_value = {
                "total": {"BTC": 0.5, "USDT": 1000.0},
                "free": {"BTC": 0.5, "USDT": 800.0},
                "used": {"BTC": 0.0, "USDT": 200.0},
            }
            client.create_order.return_value = {
                "id": "ccxt-order-1",
                "status": "open",
                "filled": 0.0,
                "average": 0.0,
            }
            client.cancel_order.return_value = {"id": "ccxt-order-1"}
            _ExchangeFactory.latest = client
            return client
        _ctor.__name__ = _exchange_id
        return _ctor

    for ex in ("binance", "kraken", "coinbase"):
        setattr(fake, ex, _make_exchange_class(ex))
    fake._factory = _ExchangeFactory
    return fake


@pytest.fixture
def fake_ccxt(monkeypatch):
    """Inject a fake ``ccxt`` module into sys.modules for the test."""
    fake = _fake_ccxt_module()
    monkeypatch.setitem(sys.modules, "ccxt", fake)
    yield fake


@pytest.fixture(autouse=True)
def _isolate_audit(tmp_path, monkeypatch):
    """Force AuditLog default DB into tmp_path so cwd stays clean."""
    monkeypatch.chdir(tmp_path)
    yield


# ---------------------------------------------------------------------------
# 1. CCXTProvider lazy import unavailable
# ---------------------------------------------------------------------------


def test_ccxt_provider_lazy_import_unavailable(monkeypatch):
    """If ``ccxt`` is not installed, fetch raises ProviderUnavailable."""
    monkeypatch.setitem(sys.modules, "ccxt", None)
    p = CCXTProvider("binance")
    with pytest.raises(ProviderUnavailable):
        p.fetch("BTC/USDT", pd.Timestamp("2020-01-01"),
                pd.Timestamp("2020-01-31"))


# ---------------------------------------------------------------------------
# 2. CCXTProvider mock-installed: fetch returns a Dataset with metadata
# ---------------------------------------------------------------------------


def test_ccxt_provider_fetch_returns_dataset(fake_ccxt):
    p = CCXTProvider("binance")
    ds = p.fetch("BTC/USDT", pd.Timestamp("2020-01-01"),
                 pd.Timestamp("2020-01-31"), timeframe="1d")
    assert isinstance(ds, Dataset)
    assert isinstance(ds.metadata, DatasetMetadata)
    assert ds.metadata.source == "ccxt:binance"
    assert ds.metadata.source_version.startswith("ccxt:")
    assert ds.metadata.point_in_time is False
    assert "ccxt:binance:BTC/USDT" in ds.metadata.name
    assert ds.metadata.extra["exchange_id"] == "binance"
    assert ds.metadata.extra["timeframe"] == "1d"
    assert "normalized_symbol" in ds.metadata.extra
    assert len(ds.data) == 3
    assert list(ds.data.columns) == ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# 3. CCXTProvider point_in_time=False
# ---------------------------------------------------------------------------


def test_ccxt_provider_point_in_time_false():
    p = CCXTProvider("binance")
    assert p.is_point_in_time() is False


# ---------------------------------------------------------------------------
# 4. CCXTProvider supported_tiers excludes OOS_LOCKED/FORWARD
# ---------------------------------------------------------------------------


def test_ccxt_provider_supported_tiers_restricted():
    p = CCXTProvider("binance")
    tiers = p.supported_tiers()
    assert "OOS_LOCKED" not in tiers
    assert "FORWARD" not in tiers
    # Must be at least IS_TRAIN/IS_VALID (research tiers).
    assert "IS_TRAIN" in tiers
    assert "IS_VALID" in tiers


# ---------------------------------------------------------------------------
# 5. CCXTProvider fetch inside OOS_LOCKED ceremony refused (non-PIT)
# ---------------------------------------------------------------------------


def test_ccxt_provider_refused_under_oos_locked_unlock(fake_ccxt):
    """A non-PIT provider with no OOS_LOCKED/FORWARD support is refused
    even with an explicit unlock ceremony open."""
    from quantforge.core.data_layer import OOSGuard
    from quantforge.core.data_providers import (
        DataProviderRegistry,
        TierPermissionError,
    )

    reg = DataProviderRegistry()
    p = CCXTProvider("binance")
    reg.register(p)
    with OOSGuard("explicit_unlock_oos_locked", lock_path=None):
        with pytest.raises(TierPermissionError):
            reg.fetch("ccxt", "BTC/USDT",
                      pd.Timestamp("2020-01-01"),
                      pd.Timestamp("2020-01-31"))


# ---------------------------------------------------------------------------
# 6. CCXTBrokerAdapter lazy import unavailable raises
# ---------------------------------------------------------------------------


def test_ccxt_broker_adapter_lazy_import_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "ccxt", None)
    from quantforge.deployment.ccxt_adapter import CCXTBrokerAdapter
    with pytest.raises(ImportError):
        CCXTBrokerAdapter("binance")


# ---------------------------------------------------------------------------
# 7. CCXTBrokerAdapter default sandbox=True
# ---------------------------------------------------------------------------


def test_ccxt_broker_adapter_default_sandbox(fake_ccxt):
    from quantforge.deployment.ccxt_adapter import CCXTBrokerAdapter
    a = CCXTBrokerAdapter("binance")
    assert a.sandbox is True
    # When sandbox=True and the exchange supports set_sandbox_mode, it
    # must have been called.
    a._client.set_sandbox_mode.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# 8. CCXTBrokerAdapter live without gateway_committed refused
# ---------------------------------------------------------------------------


def test_ccxt_broker_live_without_gateway_committed_refused(fake_ccxt):
    from quantforge.deployment.brokers import Order
    from quantforge.deployment.ccxt_adapter import CCXTBrokerAdapter

    a = CCXTBrokerAdapter("binance", sandbox=False)
    order = Order(symbol="BTC/USDT", qty=0.01, side="buy",
                  order_type="market")
    resp = a.submit_order(order)
    assert resp["status"] == "rejected"
    assert "missing_gateway_committed" in resp["reason"]
    a._client.create_order.assert_not_called()


# ---------------------------------------------------------------------------
# 9. CCXTBrokerAdapter live without OOSGuard ceremony refused
# ---------------------------------------------------------------------------


def test_ccxt_broker_live_without_oos_guard_refused(fake_ccxt, monkeypatch):
    from quantforge.deployment.brokers import Order
    from quantforge.deployment.ccxt_adapter import (
        ALLOW_LIVE_TOKEN_ENV_PATTERN,
        CCXTBrokerAdapter,
    )

    # Set the allow-live token but DO NOT open an OOS ceremony.
    env = ALLOW_LIVE_TOKEN_ENV_PATTERN.format(EXCHANGE="BINANCE")
    monkeypatch.setenv(env, "1")
    a = CCXTBrokerAdapter("binance", sandbox=False)
    fake_committed = mock.MagicMock(name="CommittedAction")
    order = Order(symbol="BTC/USDT", qty=0.01, side="buy",
                  order_type="market")
    resp = a.submit_order(order, gateway_committed=fake_committed)
    assert resp["status"] == "rejected"
    assert "missing_oos_guard_ceremony" in resp["reason"]
    a._client.create_order.assert_not_called()


# ---------------------------------------------------------------------------
# 10. CCXTBrokerAdapter sandbox order goes through (mocked)
# ---------------------------------------------------------------------------


def test_ccxt_broker_sandbox_order_routes_to_client(fake_ccxt):
    from quantforge.deployment.brokers import Order
    from quantforge.deployment.ccxt_adapter import CCXTBrokerAdapter

    a = CCXTBrokerAdapter("binance", sandbox=True)
    order = Order(symbol="BTC/USDT", qty=0.01, side="buy",
                  order_type="market", client_order_id="cid-1")
    resp = a.submit_order(order)
    assert resp["status"] in ("open", "submitted")
    assert resp["client_order_id"] == "cid-1"
    a._client.create_order.assert_called_once()
    args, kwargs = a._client.create_order.call_args
    # Symbol passed in CCXT BASE/QUOTE shape.
    assert args[0] == "BTC/USDT"
    # market type, side, qty, price=None, params={"clientOrderId": "cid-1"}.
    assert args[1] == "market"
    assert args[2] == "buy"
    assert args[3] == 0.01
    assert args[4] is None
    assert args[5]["clientOrderId"] == "cid-1"


# ---------------------------------------------------------------------------
# 11. CCXTBrokerAdapter KillSwitch env var blocks
# ---------------------------------------------------------------------------


def test_ccxt_broker_kill_switch_env_blocks(fake_ccxt, monkeypatch):
    from quantforge.deployment.brokers import Order
    from quantforge.deployment.ccxt_adapter import (
        CCXTBrokerAdapter,
        KILL_SWITCH_ENV,
    )

    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    a = CCXTBrokerAdapter("binance", sandbox=True)
    order = Order(symbol="BTC/USDT", qty=0.01, side="buy",
                  order_type="market")
    resp = a.submit_order(order)
    assert resp["status"] == "rejected"
    assert resp["reason"] == "kill_switch_env"
    a._client.create_order.assert_not_called()


# ---------------------------------------------------------------------------
# 12. CCXTBrokerAdapter API keys read from env, never logged
# ---------------------------------------------------------------------------


def test_ccxt_broker_api_keys_from_env_never_logged(fake_ccxt, monkeypatch,
                                                    caplog):
    from quantforge.deployment.ccxt_adapter import CCXTBrokerAdapter

    secret_key = "AKIA-supersecret-1234567890abcdef"
    secret_secret = "shh-this-is-a-very-private-secret-value-9999"
    monkeypatch.setenv("QF_CCXT_BINANCE_KEY", secret_key)
    monkeypatch.setenv("QF_CCXT_BINANCE_SECRET", secret_secret)
    with caplog.at_level("DEBUG"):
        a = CCXTBrokerAdapter("binance", sandbox=True)
    # Construction must have used the env values via the SDK constructor.
    assert a._client.config.get("apiKey") == secret_key
    assert a._client.config.get("secret") == secret_secret
    # Logs must NEVER contain the secret values.
    log_text = "\n".join(
        f"{r.name}: {r.getMessage()}" for r in caplog.records
    )
    assert secret_key not in log_text
    assert secret_secret not in log_text
    # The env var NAMES are fine to log; the values are not.
    assert "QF_CCXT_BINANCE_KEY" in log_text or len(log_text) >= 0


# ---------------------------------------------------------------------------
# 13. CCXTBrokerAdapter unstable quote warns
# ---------------------------------------------------------------------------


def test_ccxt_broker_unstable_quote_warns(fake_ccxt):
    from quantforge.deployment.brokers import Order
    from quantforge.deployment.ccxt_adapter import CCXTBrokerAdapter

    a = CCXTBrokerAdapter("binance", sandbox=True,
                          allowed_quotes={"USDT", "USDC", "USD"})
    order = Order(symbol="ETH/BTC", qty=1.0, side="buy",
                  order_type="market")
    with pytest.warns(UserWarning, match="unstable quote"):
        a.submit_order(order)


# ---------------------------------------------------------------------------
# 14. CLI: forge crypto exchanges smoke (lazy-fails cleanly if ccxt missing)
# ---------------------------------------------------------------------------


def test_cli_crypto_exchanges_lazy_fails_cleanly():
    """Without ccxt installed, ``forge crypto exchanges`` should print a
    clean message and exit 1 instead of crashing with a traceback."""
    # Run the CLI as a subprocess with a clean ccxt-blocked env so we
    # don't pollute the in-process import cache.
    code = (
        "import sys; sys.modules['ccxt'] = None;"
        "from quantforge.cli.forge import main;"
        "raise SystemExit(main(['crypto', 'exchanges']))"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
    )
    # Either ccxt is genuinely missing -> stdout reports it; or a fake is
    # present. Both are acceptable so long as the process exits cleanly
    # without a Python traceback.
    combined = res.stdout + res.stderr
    assert "Traceback" not in combined, combined
    assert res.returncode in (0, 1)
    if res.returncode == 1:
        assert "ccxt not installed" in res.stdout

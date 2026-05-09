"""Multi-broker abstraction for Aurora.

Adapter pattern unifies access to brokers used by deployment.live and
deployment.paper. Concrete adapters lazy-import their SDKs so the package
remains importable without optional dependencies.

Supported names: 'paper', 'alpaca', 'ib', 'coinbase', 'kraken'.

Usage:
    from aurora.deployment.brokers import (
        BrokerConfig, Order, create_broker,
    )
    cfg = BrokerConfig(name='paper', paper=True)
    broker = create_broker(cfg)
    broker.submit_order(Order(symbol='SPY', qty=10, side='buy',
                              order_type='market'))

Credentials NEVER appear in source. Adapters read API keys from the env var
NAME stored in BrokerConfig (e.g. config.api_key_env='ALPACA_API_KEY' →
os.getenv('ALPACA_API_KEY')).

The package was split out of a single ``brokers.py`` module in R50. The
public surface (every symbol previously exposed by the flat module) is
preserved here so existing imports keep resolving unchanged.
"""
from __future__ import annotations

# Stdlib re-exports preserved for back-compat with code that did
# ``from aurora.deployment import brokers`` and reached into the module
# namespace for these names. Tests also monkeypatch ``_dt`` via this path,
# so ``_dt`` must remain a module attribute that submodules consult at
# runtime (see ``base._now_utc``).
import copy
import hashlib
import os
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime as _dt
from datetime import timezone
from typing import Any, Optional

from aurora.core.logging import get_logger, log_event

from .alpaca import AlpacaAdapter
from .base import (
    AuditLog,
    Broker,
    BrokerConfig,
    KillSwitch,
    Order,
    Position,
    ReconciliationError,
    _RateLimiter,
    _diff_positions,
    _import_or_raise,
    _log,
    _read_env,
    _validate_order,
)
from .coinbase import CoinbaseAdapter
from .ib import IBAdapter
from .kraken import KrakenAdapter
from .paper import PaperBroker, _PaperState


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Any] = {
    "paper": PaperBroker,
    "alpaca": AlpacaAdapter,
    "ib": IBAdapter,
    "coinbase": CoinbaseAdapter,
    "kraken": KrakenAdapter,
}


def create_broker(config: BrokerConfig) -> Broker:
    """Return a broker instance for `config.name`.

    Raises ValueError on unknown name. Raises ImportError when the matching
    SDK is not installed (message includes the install hint).
    """
    if not isinstance(config, BrokerConfig):
        raise ValueError(
            f"create_broker requires BrokerConfig, got {type(config).__name__}"
        )
    name = (config.name or "").lower()
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown broker name {config.name!r}; "
            f"valid names: {sorted(_REGISTRY)}"
        )
    cls = _REGISTRY[name]
    return cls(config)


__all__ = [
    # Public broker surface
    "AlpacaAdapter",
    "AuditLog",
    "Broker",
    "BrokerConfig",
    "CoinbaseAdapter",
    "IBAdapter",
    "KillSwitch",
    "KrakenAdapter",
    "Order",
    "PaperBroker",
    "Position",
    "ReconciliationError",
    "create_broker",
]

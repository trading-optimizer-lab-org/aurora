"""``forge crypto`` subcommand group (R49 split).

P3.A: optional CCXT-backed crypto data + execution.
"""
from __future__ import annotations

from ._shared import _runtime_error


# ---------------------------------------------------------------------------
# Crypto / CCXT subcommands (P3.A)
# ---------------------------------------------------------------------------


def _ccxt_load_config():
    """Best-effort load of ``config/ccxt.yaml``. Returns dict or {}."""
    import os
    try:
        import yaml
    except Exception:
        return {}
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "config", "ccxt.yaml"),
        "quantforge/config/ccxt.yaml",
        "config/ccxt.yaml",
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
    return {}


def cmd_crypto_exchanges(args):
    """List the ccxt-supported exchanges. Lazy-fails cleanly if missing."""
    try:
        import ccxt
    except Exception:
        print("ccxt not installed. Install with: pip install ccxt")
        return 1
    exchanges = sorted(getattr(ccxt, "exchanges", []))
    print(f"ccxt {getattr(ccxt, '__version__', '?')}: "
          f"{len(exchanges)} exchanges")
    for ex in exchanges:
        print(f"  {ex}")
    return 0


def cmd_crypto_fetch(args):
    """Fetch crypto OHLCV via the CCXTProvider into a parquet."""
    import json
    import os
    try:
        from aurora.core.data_providers.ccxt_provider import CCXTProvider
    except Exception as exc:
        return _runtime_error(f"crypto fetch: {exc}")
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    provider = CCXTProvider(exchange_id=exchange)
    try:
        ds = provider.fetch(
            args.symbol,
            start=args.start, end=args.end,
            timeframe=args.timeframe,
        )
    except Exception as exc:
        return _runtime_error(f"crypto fetch: {exc}")
    out = args.output
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    try:
        ds.data.to_parquet(out)
    except Exception as exc:
        return _runtime_error(f"crypto fetch: parquet write failed: {exc}")
    sidecar_path = out + ".meta.json"
    payload = {
        "name": ds.metadata.name,
        "source": ds.metadata.source,
        "source_version": ds.metadata.source_version,
        "asof_date": ds.metadata.asof_date.isoformat(),
        "point_in_time": ds.metadata.point_in_time,
        "content_hash": ds.metadata.content_hash,
        "tier_permission": ds.metadata.tier_permission,
        "schema_version": ds.metadata.schema_version,
        "extra": ds.metadata.extra,
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"Wrote {out} ({len(ds.data)} rows)")
    print(f"Sidecar metadata: {sidecar_path}")
    return 0


def cmd_crypto_submit_order(args):
    """Submit a crypto order through the CCXT broker adapter."""
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    sandbox = not getattr(args, "allow_live", False)
    try:
        from aurora.deployment.ccxt_adapter import CCXTBrokerAdapter
        from aurora.deployment.brokers import Order
    except Exception as exc:
        return _runtime_error(f"crypto submit-order: {exc}")
    try:
        adapter = CCXTBrokerAdapter(
            exchange_id=exchange,
            sandbox=sandbox,
        )
    except ImportError as exc:
        return _runtime_error(f"crypto submit-order: {exc}")
    order = Order(
        symbol=args.symbol,
        qty=float(args.qty),
        side=args.side,
        order_type=args.type,
        limit_price=float(args.limit_price) if args.limit_price else None,
    )
    try:
        resp = adapter.submit_order(order)
    except Exception as exc:
        return _runtime_error(f"crypto submit-order: {exc}")
    print(resp)
    if str(resp.get("status", "")).lower() == "rejected":
        return 1
    return 0


def cmd_crypto_positions(args):
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    try:
        from aurora.deployment.ccxt_adapter import CCXTBrokerAdapter
    except Exception as exc:
        return _runtime_error(f"crypto positions: {exc}")
    try:
        adapter = CCXTBrokerAdapter(exchange_id=exchange, sandbox=True)
        positions = adapter.get_positions()
    except Exception as exc:
        return _runtime_error(f"crypto positions: {exc}")
    if not positions:
        print("(no positions)")
        return 0
    for p in positions:
        print(f"{p.symbol:<14}  qty={p.qty}")
    return 0


def cmd_crypto_balance(args):
    cfg = _ccxt_load_config()
    exchange = args.exchange or cfg.get("default_exchange", "binance")
    try:
        from aurora.deployment.ccxt_adapter import CCXTBrokerAdapter
    except Exception as exc:
        return _runtime_error(f"crypto balance: {exc}")
    try:
        adapter = CCXTBrokerAdapter(exchange_id=exchange, sandbox=True)
        bal = adapter.get_balance()
    except Exception as exc:
        return _runtime_error(f"crypto balance: {exc}")
    if not bal:
        print("(empty balance)")
        return 0
    free = bal.get("free", {}) if isinstance(bal, dict) else {}
    total = bal.get("total", {}) if isinstance(bal, dict) else {}
    print(f"{'currency':<10}  {'free':>16}  {'total':>16}")
    for ccy in sorted(set(list(free) + list(total))):
        print(f"{ccy:<10}  {free.get(ccy, 0)!s:>16}  {total.get(ccy, 0)!s:>16}")
    return 0


def cmd_crypto_allow_live(args):
    """Write a one-time allow-live consent token for an exchange."""
    cfg = _ccxt_load_config()
    token_dir = (
        args.token_dir
        or cfg.get("allow_live_token_dir")
        or "~/.quantforge/ccxt_tokens"
    )
    try:
        from aurora.deployment.ccxt_adapter import (
            ALLOW_LIVE_TOKEN_ENV_PATTERN,
            LIVE_CEREMONY_PHASE,
            write_allow_live_token,
        )
    except Exception as exc:
        return _runtime_error(f"crypto allow-live: {exc}")
    path = write_allow_live_token(args.exchange, token_dir)
    env_var = ALLOW_LIVE_TOKEN_ENV_PATTERN.format(EXCHANGE=args.exchange.upper())
    print(f"Wrote consent token: {path}")
    print()
    print("To go live, export:")
    print(f"  {env_var}=1")
    print(f"  (and open an OOSGuard with phase={LIVE_CEREMONY_PHASE!r})")
    print()
    print("This token alone does NOT authorize live trading. Live submit "
          "still requires gateway_committed + OOSGuard ceremony.")
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``crypto`` subcommand group on the top-level subparsers."""
    p_crypto = subparsers.add_parser(
        "crypto",
        help="Crypto data + execution via CCXT (optional dep)",
        description=(
            "Crypto integration via the optional ``ccxt`` package. "
            "Sandbox by default; live trading requires a triple-gate: "
            "gateway_committed + OOSGuard ceremony + allow-live token."
        ),
    )
    crypto_sub = p_crypto.add_subparsers(dest="crypto_cmd", required=True)

    p_cx_ex = crypto_sub.add_parser(
        "exchanges", help="List ccxt-supported exchanges (lazy import)",
    )
    p_cx_ex.set_defaults(func=cmd_crypto_exchanges)

    p_cx_fetch = crypto_sub.add_parser(
        "fetch", help="Fetch OHLCV crypto data via CCXTProvider",
    )
    p_cx_fetch.add_argument("symbol", help="Symbol e.g. BTC/USDT")
    p_cx_fetch.add_argument("--exchange", default=None,
                            help="ccxt exchange id (default from config)")
    p_cx_fetch.add_argument("--timeframe", default="1d",
                            help="Candle timeframe (1m/5m/1h/1d/...)")
    p_cx_fetch.add_argument("--start", default=None, help="ISO start date")
    p_cx_fetch.add_argument("--end", default=None, help="ISO end date")
    p_cx_fetch.add_argument("--output", required=True,
                            help="Parquet output path")
    p_cx_fetch.set_defaults(func=cmd_crypto_fetch)

    p_cx_submit = crypto_sub.add_parser(
        "submit-order", help="Submit a crypto order via CCXTBrokerAdapter",
    )
    p_cx_submit.add_argument("--exchange", default=None)
    p_cx_submit.add_argument("--symbol", required=True)
    p_cx_submit.add_argument("--side", choices=["buy", "sell"], required=True)
    p_cx_submit.add_argument("--qty", required=True)
    p_cx_submit.add_argument("--type", choices=["market", "limit"],
                             default="market")
    p_cx_submit.add_argument("--limit-price", default=None,
                             dest="limit_price")
    p_cx_submit.add_argument("--sandbox", action="store_true",
                             help="Force sandbox mode (default)")
    p_cx_submit.add_argument("--allow-live", action="store_true",
                             dest="allow_live",
                             help="Disable sandbox; requires triple-gate")
    p_cx_submit.set_defaults(func=cmd_crypto_submit_order)

    p_cx_pos = crypto_sub.add_parser(
        "positions", help="Show CCXT positions",
    )
    p_cx_pos.add_argument("--exchange", default=None)
    p_cx_pos.set_defaults(func=cmd_crypto_positions)

    p_cx_bal = crypto_sub.add_parser(
        "balance", help="Show CCXT balance",
    )
    p_cx_bal.add_argument("--exchange", default=None)
    p_cx_bal.set_defaults(func=cmd_crypto_balance)

    p_cx_allow = crypto_sub.add_parser(
        "allow-live", help="Write one-time allow-live consent token",
    )
    p_cx_allow.add_argument("exchange",
                            help="Exchange id, e.g. binance")
    p_cx_allow.add_argument("--token-dir", default=None, dest="token_dir",
                            help="Override token storage directory")
    p_cx_allow.set_defaults(func=cmd_crypto_allow_live)

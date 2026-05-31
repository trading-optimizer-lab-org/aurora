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
        "aurora/config/ccxt.yaml",
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


def cmd_crypto_capability(args):
    """Print the capability matrix entry for an exchange (R185)."""
    try:
        from aurora.markets.exchange_capability import default_registry
    except Exception as exc:  # noqa: BLE001  -- defensive import
        return _runtime_error(f"crypto capability: {exc}")
    reg = default_registry()
    cap = reg.get(args.exchange)
    if cap is None:
        print(
            f"unknown exchange {args.exchange!r}; "
            f"known: {list(reg.names())}"
        )
        return 1
    print(f"exchange:                   {cap.name}")
    print(f"  spot_supported:           {cap.spot_supported}")
    print(f"  futures_supported:        {cap.futures_supported}")
    print(f"  perpetual_supported:      {cap.perpetual_supported}")
    print(f"  margin_supported:         {cap.margin_supported}")
    print(
        f"  order_types:              "
        f"{', '.join(sorted(cap.supported_order_types))}"
    )
    print(
        f"  time_in_force:            "
        f"{', '.join(sorted(cap.supported_time_in_force))}"
    )
    print(f"  min_size_per_kind:        {dict(cap.min_size_per_kind)}")
    print(f"  tick_size_per_kind:       {dict(cap.tick_size_per_kind)}")
    print(f"  rate_limit_calls/min:     {cap.rate_limit_calls_per_minute}")
    print(f"  sandbox_supported:        {cap.sandbox_supported}")
    return 0


def cmd_crypto_funding_history(args):
    """Print a stub funding-rate history for a perpetual (R185).

    Pure offline command -- it does NOT make a network call. It prints
    the FundingRateRecord schema and a small synthetic example so an
    operator can confirm the contract before piping live data into the
    engine.
    """
    try:
        from aurora.markets.crypto_derivatives import FundingRateRecord
    except Exception as exc:  # noqa: BLE001
        return _runtime_error(f"crypto funding-history: {exc}")
    import pandas as pd  # noqa: WPS433  -- localised import

    print(f"symbol: {args.symbol}")
    print(
        "schema: instrument_symbol, exchange, ts, rate, "
        "interval_seconds, source"
    )
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    examples = []
    for i in range(3):
        rec = FundingRateRecord(
            instrument_symbol=args.symbol,
            exchange=args.exchange or "binance_perpetual",
            ts=base + pd.Timedelta(hours=8 * i),
            rate=0.0001 * (1 if i % 2 == 0 else -1),
            interval_seconds=28800,
            source="cli_stub",
        )
        examples.append(rec)
        print(
            f"  ts={rec.ts.isoformat()}  rate={rec.rate:+.6f}  "
            f"annualised={rec.annualised():+.4%}"
        )
    return 0


def cmd_crypto_preflight(args):
    """Run the R185 capability + downtime preflight for one order spec."""
    try:
        from aurora.markets.crypto_derivatives import CryptoInstrumentKind
        from aurora.markets.exchange_capability import (
            UnsupportedCapability,
            assert_exchange_supports,
        )
    except Exception as exc:  # noqa: BLE001
        return _runtime_error(f"crypto preflight: {exc}")
    kind = args.kind or "spot"
    order_type = args.order_type or "market"
    try:
        parsed_kind = CryptoInstrumentKind.parse(kind)
    except ValueError as exc:
        return _runtime_error(f"crypto preflight: {exc}")
    try:
        assert_exchange_supports(args.exchange, parsed_kind, order_type)
    except UnsupportedCapability as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(
        f"OK: exchange={args.exchange} symbol={args.symbol} "
        f"kind={parsed_kind.value} order_type={order_type}"
    )
    return 0


def cmd_crypto_allow_live(args):
    """Write a one-time allow-live consent token for an exchange."""
    cfg = _ccxt_load_config()
    token_dir = (
        args.token_dir
        or cfg.get("allow_live_token_dir")
        or "~/.aurora/ccxt_tokens"
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

    # ----- R185 capability / funding-history / preflight -----
    p_cx_cap = crypto_sub.add_parser(
        "capability",
        help="Show the hand-curated capability matrix entry for EXCHANGE",
    )
    p_cx_cap.add_argument(
        "exchange",
        help="Capability registry key, e.g. binance_perpetual",
    )
    p_cx_cap.set_defaults(func=cmd_crypto_capability)

    p_cx_fund = crypto_sub.add_parser(
        "funding-history",
        help="Print stub FundingRateRecord schema/examples for SYMBOL",
    )
    p_cx_fund.add_argument("symbol", help="Perpetual symbol e.g. BTC-PERP")
    p_cx_fund.add_argument(
        "--exchange", default=None,
        help="Capability registry key (default: binance_perpetual)",
    )
    p_cx_fund.set_defaults(func=cmd_crypto_funding_history)

    p_cx_pre = crypto_sub.add_parser(
        "preflight",
        help="Refusal-gate preflight for an EXCHANGE / SYMBOL / kind / type",
    )
    p_cx_pre.add_argument("exchange", help="Capability registry key")
    p_cx_pre.add_argument("symbol", help="Instrument symbol")
    p_cx_pre.add_argument(
        "--kind",
        choices=["spot", "future", "dated_future", "perpetual"],
        default="spot",
        help="Instrument kind (default: spot)",
    )
    p_cx_pre.add_argument(
        "--order-type",
        dest="order_type",
        choices=["market", "limit", "stop", "stop_limit",
                 "post_only", "ioc", "fok"],
        default="market",
        help="Order type (default: market)",
    )
    p_cx_pre.set_defaults(func=cmd_crypto_preflight)

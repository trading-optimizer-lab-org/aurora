"""Broker connection / position / buying-power preflight checks."""
from __future__ import annotations

from aurora.deployment.preflight._models import PreflightCheck


def check_broker_connection(broker) -> PreflightCheck:
    """Probe broker. Accepts duck-typed object with is_connected() or connected attr.

    Skipped (passes) when broker exposes neither ``is_connected`` nor
    ``connected``, matching the duck-typed skip policy used by
    ``check_no_conflicting_positions`` for ``get_position``.
    """
    if broker is None:
        return PreflightCheck("broker_connection", True, "no broker (skipped)")
    if not (hasattr(broker, "is_connected") or hasattr(broker, "connected")):
        return PreflightCheck(
            "broker_connection", True,
            "broker has no is_connected/connected interface (skipped)",
        )
    try:
        if hasattr(broker, "is_connected"):
            ok = bool(broker.is_connected())
        else:
            ok = bool(broker.connected)
    except Exception as e:
        return PreflightCheck("broker_connection", False, f"probe error: {e}")
    if not ok:
        return PreflightCheck("broker_connection", False, "broker not connected")
    return PreflightCheck("broker_connection", True, "broker connected")


def check_no_conflicting_positions(broker, symbol: str) -> PreflightCheck:
    """Verify broker has no open position for symbol that would conflict."""
    if broker is None:
        return PreflightCheck("no_conflicting_positions", True, "no broker (skipped)")
    try:
        getp = getattr(broker, "get_position", None)
        if getp is None:
            return PreflightCheck(
                "no_conflicting_positions", True,
                "broker has no get_position (skipped)",
            )
        pos = getp(symbol)
    except Exception as e:
        return PreflightCheck("no_conflicting_positions", False, f"probe error: {e}")
    if pos is None:
        return PreflightCheck("no_conflicting_positions", True, f"no open {symbol}")
    qty = getattr(pos, "quantity", 0)
    if qty == 0:
        return PreflightCheck("no_conflicting_positions", True, f"flat {symbol}")
    return PreflightCheck(
        "no_conflicting_positions", False,
        f"existing {symbol} position qty={qty}",
    )


def check_buying_power(broker, required_cash: float) -> PreflightCheck:
    """Verify the broker reports >= ``required_cash`` buying power.

    Skipped when ``broker`` is None. ``required_cash`` must be > 0.
    """
    if broker is None:
        return PreflightCheck(
            "buying_power", True, "no broker (skipped)",
        )
    if required_cash <= 0:
        return PreflightCheck(
            "buying_power", False,
            f"required_cash must be > 0, got {required_cash}",
        )
    try:
        if hasattr(broker, "get_account"):
            acct = broker.get_account()
            if isinstance(acct, dict):
                bp = float(acct.get("buying_power", acct.get("cash", 0.0)) or 0.0)
            else:
                bp = float(getattr(acct, "buying_power",
                                   getattr(acct, "cash", 0.0)))
        elif hasattr(broker, "get_buying_power"):
            bp = float(broker.get_buying_power())
        else:
            return PreflightCheck(
                "buying_power", False,
                "broker has no get_account / get_buying_power",
            )
    except Exception as e:
        return PreflightCheck("buying_power", False, f"probe error: {e}")
    if bp < float(required_cash):
        return PreflightCheck(
            "buying_power", False,
            f"buying_power {bp:.2f} < required {float(required_cash):.2f}",
        )
    return PreflightCheck(
        "buying_power", True,
        f"buying_power {bp:.2f} >= required {float(required_cash):.2f}",
    )

"""Market-hours preflight check."""
from __future__ import annotations

from typing import Optional

import pandas as pd

from aurora.deployment.preflight._models import PreflightCheck


def check_market_hours(symbol: str, exchange: str = "NYSE",
                       now_utc: Optional[pd.Timestamp] = None
                       ) -> PreflightCheck:
    """Verify the market is open RIGHT NOW for ``symbol`` on ``exchange``.

    Skipped (passes) when ``pandas_market_calendars`` is not installed so
    paper deployments without that optional dep keep working.
    """
    try:
        import pandas_market_calendars as mcal
    except Exception:
        return PreflightCheck(
            "market_hours", True,
            "skipped (pandas_market_calendars not installed)",
        )
    try:
        cal = mcal.get_calendar(exchange)
    except Exception as e:
        return PreflightCheck(
            "market_hours", False,
            f"unknown exchange calendar {exchange!r}: {e}",
        )
    now = pd.Timestamp.now(tz="UTC") if now_utc is None else now_utc
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    today = now.normalize().date()
    try:
        sched = cal.schedule(start_date=today.isoformat(),
                             end_date=today.isoformat())
    except Exception as e:
        return PreflightCheck(
            "market_hours", False,
            f"calendar query failed for {exchange}: {e}",
        )
    if sched.empty:
        return PreflightCheck(
            "market_hours", False,
            f"{exchange} closed on {today}",
        )
    open_ts = pd.Timestamp(sched.iloc[0]["market_open"]).tz_convert("UTC")
    close_ts = pd.Timestamp(sched.iloc[0]["market_close"]).tz_convert("UTC")
    if open_ts <= now <= close_ts:
        return PreflightCheck(
            "market_hours", True,
            f"{exchange} open ({open_ts.isoformat()} -> {close_ts.isoformat()})",
        )
    return PreflightCheck(
        "market_hours", False,
        f"{exchange} session window {open_ts.isoformat()} -> "
        f"{close_ts.isoformat()} does not include now={now.isoformat()}",
    )

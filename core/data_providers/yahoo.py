"""Yahoo Finance provider (yfinance wrapper).

Wraps the existing ``data_layer._download`` path. Marked
``point_in_time=False`` because yfinance retroactively adjusts close
prices for splits/dividends, so historical reads can change between
calls. Default tier permission is ``IS_TRAIN`` -- callers that want to
serve OOS_LOCKED / FORWARD with yfinance must wrap the read in an
explicit unlock ceremony AND override the tier permission via
``YahooProvider(tier_permission="OOS_LOCKED")``.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from . import BaseDataProvider


class YahooProvider(BaseDataProvider):
    """yfinance-backed provider.

    Fetch kwargs:
        auto_adjust: bool. Defaults to True (matches yfinance.download
            and the existing ``data_layer._download`` contract).
        progress: bool. Defaults to False.
        column: str. Which OHLCV column to extract. Defaults to "Close".
    """

    name: str = "yahoo"
    version: str = "yahoo:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"

    def __init__(self, *, tier_permission: Optional[str] = None) -> None:
        if tier_permission is not None:
            # Allow runtime override -- tests / explicit unlock ceremonies
            # can construct YahooProvider(tier_permission="OOS_LOCKED").
            object.__setattr__(self, "tier_permission", tier_permission)

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.Series:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - yfinance is a dep
            from . import ProviderUnavailable
            raise ProviderUnavailable(
                "yahoo provider requires the optional ``yfinance`` package; "
                "install with ``pip install yfinance``"
            ) from exc

        s_arg = start.strftime("%Y-%m-%d") if start is not None else "1990-01-01"
        e_arg = end.strftime("%Y-%m-%d") if end is not None else \
            pd.Timestamp.today().strftime("%Y-%m-%d")
        auto_adjust = bool(kwargs.get("auto_adjust", True))
        progress = bool(kwargs.get("progress", False))
        column = kwargs.get("column", "Close")

        df = yf.download(
            symbol, start=s_arg, end=e_arg,
            auto_adjust=auto_adjust, progress=progress,
        )
        if df is None or len(df) == 0:
            return pd.Series([], index=pd.DatetimeIndex([]),
                             name=symbol, dtype="float64")
        if column in df.columns:
            s = df[column].squeeze()
        else:
            s = df.iloc[:, 0]
        s = s.dropna()
        # Normalize tz-aware index to naive UTC (matches data_layer +
        # snapshots contract).
        idx = pd.to_datetime(s.index)
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        s.index = idx
        s.name = symbol
        return s

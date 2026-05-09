"""CCXT crypto data provider (P3.A).

Lazy-imports the optional ``ccxt`` package. If the package is not installed,
construction succeeds (so the registry can list it) but ``fetch`` raises
:exc:`ProviderUnavailable` with a clean install hint.

CCXT exchanges retroactively adjust history (delistings, exchange policy
changes, listing date corrections) so the provider is conservatively marked
``point_in_time=False`` with ``tier_permission="IS_TRAIN"`` and
``supported_tiers={"IS_TRAIN", "IS_VALID"}``. Fetching inside an
``OOSGuard`` ``OOS_LOCKED`` ceremony is refused unless the unlock matches
AND the provider declares OOS_LOCKED/FORWARD support (which it does NOT
by default).

Symbol normalization: CCXT exchanges expect symbols in ``BASE/QUOTE``
form (e.g. ``"BTC/USDT"``). Anything passed in ``base-quote`` or
``BASE_QUOTE`` is normalized.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from . import BaseDataProvider, ProviderError, ProviderUnavailable

_log = logging.getLogger(__name__)


def _normalize_symbol(symbol: str) -> str:
    """Convert various symbol forms to CCXT's ``BASE/QUOTE`` shape.

    Accepts ``BTC/USDT``, ``BTC-USDT``, ``BTC_USDT``, ``BTCUSDT``
    (best-effort) and returns ``BTC/USDT``.
    """
    if not isinstance(symbol, str) or not symbol:
        raise ValueError(f"symbol must be non-empty str, got {symbol!r}")
    s = symbol.strip().upper()
    if "/" in s:
        return s
    for sep in ("-", "_"):
        if sep in s:
            base, quote = s.split(sep, 1)
            return f"{base}/{quote}"
    # No separator: try to split common quote currencies off the end.
    for q in ("USDT", "USDC", "USD", "BTC", "ETH", "EUR"):
        if s.endswith(q) and len(s) > len(q):
            return f"{s[: -len(q)]}/{q}"
    raise ValueError(
        f"cannot normalize symbol {symbol!r}: expected BASE/QUOTE shape"
    )


class CCXTProvider(BaseDataProvider):
    """CCXT exchange OHLCV adapter (lazy-import).

    Construction kwargs:
        exchange_id: ccxt exchange id, e.g. ``"binance"``, ``"kraken"``,
            ``"coinbase"``. Default ``"binance"``.
        config: optional dict forwarded to the ccxt exchange constructor
            (e.g. ``{"timeout": 30000}``). API keys are NOT taken here --
            data fetching is keyless.
        point_in_time: opt-in PIT flag (default False).
        tier_permission: per-instance override (default ``"IS_TRAIN"``).
    """

    name: str = "ccxt"
    version: str = "ccxt:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"

    # CCXT-specific defaults: how many candles per page, max retries.
    _PAGE_LIMIT = 500
    _MAX_PAGES = 200  # hard cap so a runaway loop cannot DoS the exchange

    def __init__(
        self,
        exchange_id: str = "binance",
        config: Optional[dict] = None,
        *,
        point_in_time: Optional[bool] = None,
        tier_permission: Optional[str] = None,
    ) -> None:
        self.exchange_id = str(exchange_id).lower()
        self.config = dict(config or {})
        if point_in_time is not None:
            object.__setattr__(self, "point_in_time", bool(point_in_time))
        if tier_permission is not None:
            object.__setattr__(self, "tier_permission", tier_permission)
        # Exchange object is constructed lazily inside fetch() so that
        # importing ccxt is deferred until the first call.
        self._exchange: Any = None

    def supported_tiers(self) -> set[str]:
        # Crypto exchange history is non-PIT: hard restrict to research
        # tiers. Override only via explicit ceremony / explicit flag.
        if self.tier_permission == "ANY":
            return super().supported_tiers()
        return {"IS_TRAIN", "IS_VALID"}

    def _import_ccxt(self) -> Any:
        try:
            import ccxt
        except Exception as exc:  # pragma: no cover - ccxt is optional
            raise ProviderUnavailable(
                "ccxt provider requires the optional ``ccxt`` package; "
                "install with ``pip install ccxt``"
            ) from exc
        return ccxt

    def _build_exchange(self) -> Any:
        if self._exchange is not None:
            return self._exchange
        ccxt = self._import_ccxt()
        if not hasattr(ccxt, self.exchange_id):
            raise ProviderError(
                f"ccxt provider: unknown exchange_id {self.exchange_id!r}; "
                f"see ccxt.exchanges for the supported list"
            )
        cls = getattr(ccxt, self.exchange_id)
        cfg = dict(self.config)
        # Force keyless mode for data fetches: exchanges that accept api
        # keys still serve public OHLCV without auth, and we want zero
        # credential dependency for data.
        cfg.setdefault("enableRateLimit", True)
        self._exchange = cls(cfg)
        return self._exchange

    def _ccxt_version(self) -> str:
        try:
            ccxt = self._import_ccxt()
            return f"ccxt:{getattr(ccxt, '__version__', '?')}"
        except ProviderUnavailable:
            return "ccxt:?"

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.DataFrame:
        timeframe = kwargs.pop("timeframe", "1d")
        norm_symbol = _normalize_symbol(symbol)
        ex = self._build_exchange()
        # Convert start/end to ms-since-epoch UTC.
        if start is not None:
            since = int(pd.Timestamp(start).tz_localize(None).value // 10**6)
        else:
            since = None
        if end is not None:
            end_ms = int(pd.Timestamp(end).tz_localize(None).value // 10**6)
        else:
            end_ms = None
        # Pagination loop: ccxt fetch_ohlcv returns at most exchange-specific
        # limit per call. We page forward until end is reached or the
        # exchange returns no more rows.
        all_rows: list[list] = []
        cursor = since
        for _ in range(self._MAX_PAGES):
            page = ex.fetch_ohlcv(
                norm_symbol, timeframe=timeframe,
                since=cursor, limit=self._PAGE_LIMIT,
            )
            if not page:
                break
            all_rows.extend(page)
            last_ts = page[-1][0]
            if end_ms is not None and last_ts >= end_ms:
                break
            if len(page) < self._PAGE_LIMIT:
                break
            cursor = last_ts + 1
        if not all_rows:
            # Empty frame: return shape consistent with downstream expectations.
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=pd.DatetimeIndex([], name="timestamp"),
            )
        df = pd.DataFrame(
            all_rows,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        # Convert ms epoch to tz-naive UTC datetime index. We build the
        # DatetimeIndex explicitly (not via column reassignment) so the
        # index inherits tz handling rather than the column dtype.
        idx = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        # Drop tz so downstream content_hash sees an order-stable naive
        # int64 view.
        idx = idx.dt.tz_convert("UTC").dt.tz_localize(None)
        df = df.drop(columns=["timestamp"])
        df.index = pd.DatetimeIndex(idx, name="timestamp")
        # Filter end-bound (CCXT returns inclusive of `since` but no end
        # parameter; downstream consumer expects [start, end] window).
        if end is not None:
            df = df[df.index <= pd.Timestamp(end).tz_localize(None)]
        return df.sort_index()

    def fetch(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> Any:
        # Override fetch so the metadata's source/source_version reflect
        # the ccxt version at runtime and ``name`` includes exchange+tf.
        from . import Dataset, DatasetMetadata, compute_content_hash
        timeframe = kwargs.get("timeframe", "1d")
        norm_symbol = _normalize_symbol(symbol)
        data = self._fetch_raw(symbol, start, end, **kwargs)
        if isinstance(data, (pd.Series, pd.DataFrame)) and len(data) > 0 \
                and isinstance(data.index, pd.DatetimeIndex):
            asof = pd.Timestamp(data.index.max())
        else:
            asof = pd.Timestamp.utcnow().tz_localize(None)
        meta = DatasetMetadata(
            name=f"ccxt:{self.exchange_id}:{norm_symbol}:{timeframe}",
            source=f"ccxt:{self.exchange_id}",
            source_version=self._ccxt_version(),
            asof_date=asof,
            point_in_time=self.is_point_in_time(),
            content_hash=compute_content_hash(data),
            tier_permission=self.tier_permission,
            schema_version=self.schema_version,
            extra={
                "exchange_id": self.exchange_id,
                "timeframe": timeframe,
                "ccxt_version": self._ccxt_version(),
                "normalized_symbol": norm_symbol,
            },
        )
        return Dataset(metadata=meta, data=data)

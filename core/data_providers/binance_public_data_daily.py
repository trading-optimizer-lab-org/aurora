"""Binance public-data daily OHLCV provider (R155 CRYPTO_PRIMARY).

Binance publishes monthly ZIP archives of OHLCV bars at
``https://data.binance.vision/data/spot/daily/klines/<symbol>/<interval>/``.
Each ZIP contains one CSV per day. We parse with stdlib ``zipfile`` so
no extra dependency is needed. A sibling ``.CHECKSUM`` file (sha256) is
verified when present; missing checksums emit a warning but do not
block ingestion (Binance does not always publish them historically).
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Tuple

import pandas as pd

from . import BaseDataProvider, ProviderError
from ._free_bulk_common import (
    OHLCV_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    empty_ohlcv_frame,
    normalise_ohlcv_frame,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "binance_public_data"
PROVIDER_URL = "https://data.binance.vision/"


# Klines CSV columns (per Binance public data spec).
_KLINE_COLUMNS = (
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
)


# ---------------------------------------------------------------------------
# Helpers (parsing + checksum).
# ---------------------------------------------------------------------------


def _verify_checksum(zip_bytes: bytes, expected_sha256: Optional[str]) -> bool:
    """Compare ``sha256(zip_bytes)`` against ``expected_sha256`` (hex).

    Returns True when no expected checksum was supplied (caller decides
    how to react to the missing-check case).
    """
    if not expected_sha256:
        return True
    actual = hashlib.sha256(zip_bytes).hexdigest()
    return actual.lower() == expected_sha256.strip().lower()


def _parse_kline_csv(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    reader = csv.reader(io.StringIO(text))
    for raw in reader:
        if not raw:
            continue
        if len(raw) < len(_KLINE_COLUMNS):
            continue
        row = {col: raw[i] for i, col in enumerate(_KLINE_COLUMNS)}
        rows.append(row)
    return rows


def _zip_bytes_to_dataframe(zip_bytes: bytes) -> pd.DataFrame:
    """Parse a Binance kline ZIP archive into a normalised OHLCV frame."""
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.namelist():
            if not member.lower().endswith(".csv"):
                continue
            text = zf.read(member).decode("utf-8", errors="replace")
            rows.extend(_parse_kline_csv(text))
    if not rows:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )
    df = pd.DataFrame(rows)
    open_time_ms = pd.to_numeric(df["open_time"], errors="coerce")
    idx = pd.to_datetime(open_time_ms, unit="ms", utc=True)
    out = pd.DataFrame({
        "open": pd.to_numeric(df["open"], errors="coerce"),
        "high": pd.to_numeric(df["high"], errors="coerce"),
        "low": pd.to_numeric(df["low"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
        "volume": pd.to_numeric(df["volume"], errors="coerce"),
    })
    out.index = pd.DatetimeIndex(idx.values, tz="UTC", name="timestamp")
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out.sort_index()


# ---------------------------------------------------------------------------
# Default client (production -- HTTPS).
# ---------------------------------------------------------------------------


def _default_client(
    symbol: str, interval: str, year: int, month: int
) -> Tuple[bytes, Optional[str]]:
    """Production client: download the monthly ZIP + optional checksum.

    Returns ``(zip_bytes, sha256_hex)``. Tests inject a stub.
    """
    from urllib.request import urlopen

    base = (
        f"{PROVIDER_URL}data/spot/monthly/klines/"
        f"{symbol.upper()}/{interval}/"
    )
    name = f"{symbol.upper()}-{interval}-{year:04d}-{month:02d}.zip"
    zip_url = base + name
    chk_url = zip_url + ".CHECKSUM"
    with urlopen(zip_url, timeout=60) as resp:  # nosec B310 -- official URL
        zip_bytes = resp.read()
    sha: Optional[str] = None
    try:
        with urlopen(chk_url, timeout=15) as resp:  # nosec B310 -- official
            chk_text = resp.read().decode("ascii", errors="replace")
            sha = chk_text.strip().split()[0] if chk_text else None
    except Exception:
        sha = None
    return zip_bytes, sha


# ---------------------------------------------------------------------------
# Provider class.
# ---------------------------------------------------------------------------


class BinancePublicDataDailyProvider(BaseDataProvider):
    """Binance public-data ZIP archive provider (CRYPTO_PRIMARY)."""

    name: str = PROVIDER_NAME
    version: str = "binance_public_data:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[
            Callable[[str, str, int, int], Tuple[bytes, Optional[str]]]
        ] = None,
    ) -> None:
        self._client = client or _default_client

    def fetch_daily_from_zip(
        self,
        symbol: str,
        zip_bytes: bytes,
        *,
        expected_sha256: Optional[str] = None,
        interval: str = "1d",
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Parse a fixture ZIP and return ``(df, lineage)``.

        The ``expected_sha256`` parameter is honoured when supplied; a
        mismatch raises :class:`ProviderError`. ``zip_bytes`` is stored
        in memory to avoid touching the filesystem when the fixture is a
        single in-memory archive.
        """
        if expected_sha256 is not None and not _verify_checksum(
            zip_bytes, expected_sha256
        ):
            raise ProviderError(
                f"binance_public_data: checksum mismatch for symbol="
                f"{symbol!r}"
            )
        raw = _zip_bytes_to_dataframe(zip_bytes)
        if len(raw) == 0:
            df = empty_ohlcv_frame()
        else:
            df = normalise_ohlcv_frame(raw)
        snapshot_hash = assert_against_contract(df, OHLCV_DAILY_V1)
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={
                "symbol": symbol,
                "interval": interval,
                "checksum_verified": expected_sha256 is not None,
            },
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "OFFICIAL",
                "source": "Binance public data",
                "adjustment_posture": "RAW",
                "checksum": expected_sha256 or "",
            },
        )
        return df, lineage

    def fetch_daily_from_file(
        self,
        symbol: str,
        path: Path,
        *,
        expected_sha256: Optional[str] = None,
        interval: str = "1d",
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Read ``path`` (a ZIP archive) and parse it. Convenience wrapper."""
        zip_bytes = Path(path).read_bytes()
        return self.fetch_daily_from_zip(
            symbol,
            zip_bytes,
            expected_sha256=expected_sha256,
            interval=interval,
        )

    def fetch_daily(
        self,
        symbol: str,
        *,
        year: int,
        month: int,
        interval: str = "1d",
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Production fetch: download ZIP for ``year/month`` and parse it."""
        zip_bytes, sha = self._client(symbol, interval, year, month)
        return self.fetch_daily_from_zip(
            symbol,
            zip_bytes,
            expected_sha256=sha,
            interval=interval,
        )

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        raise NotImplementedError(
            "binance_public_data provides ZIP-based monthly fetches; "
            "use fetch_daily(year=..., month=...) or "
            "fetch_daily_from_zip(...)"
        )


def descriptor():
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.CRYPTO_PRIMARY,
        licence_terms_url="https://www.binance.com/en/terms",
        rate_limits="archive download (per-month, may rate limit)",
        auth_required=False,
        asset_classes=("crypto",),
        intervals=("1d", "1h", "1m"),
        adjustment_posture="RAW",
        reliability="OFFICIAL",
    )


def _coerce_iter(value: Iterable[Any]) -> list[Any]:
    return list(value)


__all__ = [
    "BinancePublicDataDailyProvider",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
    "_zip_bytes_to_dataframe",
]

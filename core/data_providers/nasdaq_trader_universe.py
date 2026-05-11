"""Nasdaq Trader symbol-directory universe downloader (R155).

Parses the official Nasdaq Trader pipe-delimited symbol files
(``nasdaqlisted.txt`` + ``otherlisted.txt``). The provider takes an
injectable ``client`` callable that returns the raw text for a named
file; tests mock the client. The default production client fetches over
HTTPS from ``https://www.nasdaqtrader.com/dynamic/SymDir/`` -- this is
exercised end-to-end only in network-enabled integration runs, never in
the fast suite.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Mapping, Optional, Tuple

import pandas as pd

from . import BaseDataProvider, ProviderUnavailable
from ._free_bulk_common import (
    UNIVERSE_V1,
    FreeBulkLineage,
    assert_universe_frame,
    build_lineage,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "nasdaq_trader"
PROVIDER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/"
NASDAQ_LISTED_FILE = "nasdaqlisted.txt"
OTHER_LISTED_FILE = "otherlisted.txt"


# ---------------------------------------------------------------------------
# Default loader (production path, network).
# ---------------------------------------------------------------------------


def _default_client(filename: str) -> str:
    """Production client that downloads the named symbol file.

    Lazy-imports ``urllib`` so a pure-test path does not pay the import
    cost. Callers in tests must inject a stub client.
    """
    try:
        from urllib.request import urlopen
    except Exception as exc:  # pragma: no cover - stdlib always present
        raise ProviderUnavailable(
            "nasdaq_trader provider requires urllib.request from stdlib"
        ) from exc
    url = PROVIDER_URL.rstrip("/") + "/" + filename
    with urlopen(url, timeout=30) as resp:  # nosec B310 -- official URL
        return resp.read().decode("ascii", errors="replace")


# ---------------------------------------------------------------------------
# File parsing.
# ---------------------------------------------------------------------------


def _parse_nasdaq_pipe_file(text: str) -> List[dict[str, Any]]:
    """Parse a Nasdaq Trader pipe-delimited file into a list of dicts.

    The file ends with a "File Creation Time" trailer line; we strip it.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    if lines[0].lower().startswith("file creation"):
        return []
    header = [c.strip() for c in lines[0].split("|")]
    rows: list[dict[str, Any]] = []
    for raw in lines[1:]:
        if raw.lower().startswith("file creation"):
            continue
        cells = raw.split("|")
        if len(cells) != len(header):
            continue
        rows.append({header[i]: cells[i].strip() for i in range(len(header))})
    return rows


# ---------------------------------------------------------------------------
# Provider class.
# ---------------------------------------------------------------------------


class NasdaqTraderUniverseProvider(BaseDataProvider):
    """Universe-only provider for the Nasdaq Trader symbol directory."""

    name: str = PROVIDER_NAME
    version: str = "nasdaq_trader:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._client = client or _default_client

    # -- universe API -------------------------------------------------------

    def fetch_universe(
        self,
        *,
        active_only: bool = True,
        files: Optional[Tuple[str, ...]] = None,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Fetch + normalise ``nasdaqlisted.txt`` and ``otherlisted.txt``.

        Returns ``(df, lineage)`` matching :data:`UNIVERSE_V1`.
        """
        if files is None:
            files = (NASDAQ_LISTED_FILE, OTHER_LISTED_FILE)
        rows: list[Mapping[str, Any]] = []
        used_files: list[str] = []
        for fname in files:
            text = self._client(fname)
            parsed = _parse_nasdaq_pipe_file(text)
            for r in parsed:
                rows.append({**r, "_source_file": fname})
            used_files.append(fname)
        df = self._normalise(rows)
        if active_only:
            df = df[df["active"]].reset_index(drop=True)
        snapshot_hash = assert_universe_frame(df)
        lineage = build_lineage(
            df=df,
            contract=UNIVERSE_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={"active_only": active_only, "files": used_files},
            snapshot_hash=snapshot_hash,
            symbol_count=int(df["canonical_symbol"].nunique()),
            extra={"reliability": "OFFICIAL", "source": "Nasdaq Trader"},
        )
        return df, lineage

    @staticmethod
    def _normalise(rows: List[Mapping[str, Any]]) -> pd.DataFrame:
        ts = pd.Timestamp(utcnow_iso().replace("Z", "+00:00"))
        out: list[dict[str, Any]] = []
        for r in rows:
            symbol = (
                r.get("Symbol")
                or r.get("ACT Symbol")
                or r.get("CQS Symbol")
                or ""
            )
            symbol = str(symbol).strip()
            if not symbol:
                continue
            test_issue = str(r.get("Test Issue", "N")).strip().upper() == "Y"
            if test_issue:
                continue
            exchange = r.get("Exchange") or r.get("Listing Exchange") or ""
            etf_flag = str(r.get("ETF", "")).strip().upper() == "Y"
            asset_class = "etf" if etf_flag else "equities"
            out.append({
                "provider_symbol": symbol,
                "canonical_symbol": symbol.replace(".", "-"),
                "exchange": str(exchange).strip() or None,
                "asset_class": asset_class,
                "currency": "USD",
                "active": True,
                "source_timestamp": ts,
            })
        if not out:
            return pd.DataFrame(
                columns=(
                    "provider_symbol",
                    "canonical_symbol",
                    "exchange",
                    "asset_class",
                    "currency",
                    "active",
                    "source_timestamp",
                )
            )
        return pd.DataFrame(out)

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        raise NotImplementedError(
            "nasdaq_trader is a universe provider; use fetch_universe()"
        )


def descriptor():
    """Return the registry-friendly :class:`ProviderDescriptor`."""
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.UNIVERSE,
        licence_terms_url="https://www.nasdaqtrader.com/Trader.aspx?id=Symbology",
        rate_limits="none (static daily files)",
        auth_required=False,
        asset_classes=("equities", "etf"),
        intervals=(),
        adjustment_posture="MIXED",
        reliability="OFFICIAL",
    )


__all__ = [
    "NasdaqTraderUniverseProvider",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "_parse_nasdaq_pipe_file",
    "descriptor",
]

"""R157 / R158 per-asset-class provider adapters.

Each section's providers expose a different fetch signature (Stooq
wants a CSV client, Binance wants ZIP bytes, OpenFIGI wants an
``http_post``, etc). The ``http_clients`` mapping injects a callable
per provider name so tests stay deterministic; production wires real
transports. When a provider has no entry, the adapter raises a
friendly error rather than calling out to a default network client.

R158 extension: the FX section dispatches to the same OHLCV providers
as equities, but threads symbols through ``_symbol_map`` so a canonical
``EURUSD`` becomes ``EURUSD=X`` for yfinance / ``EURUSD.FX`` for Stooq.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Tuple

import pandas as pd

from .._free_bulk_common import FreeBulkLineage
from ._symbol_map import apply_normalisation


__all__ = [
    "HttpClients",
    "fetch_for_section",
]


HttpClients = Mapping[str, Callable[..., Any]]


def _resolve_client(
    http_clients: Optional[HttpClients], provider: str
) -> Optional[Callable[..., Any]]:
    if not http_clients:
        return None
    return http_clients.get(provider)


def _augment_lineage_with_normalisation(
    lineage: FreeBulkLineage, canonical: str, normalised: str,
) -> FreeBulkLineage:
    """Return a new lineage carrying the canonical -> normalised mapping.

    No-op when the spelling did not change.
    """
    if canonical == normalised:
        return lineage
    extra = dict(lineage.extra)
    extra["symbol_canonical"] = canonical
    extra["symbol_normalised_from"] = canonical
    extra["symbol_normalised_to"] = normalised
    # Frozen dataclass: rebuild with the augmented extras.
    return FreeBulkLineage(
        lineage=lineage.lineage,
        provider_name=lineage.provider_name,
        provider_url=lineage.provider_url,
        retrieved_at_iso=lineage.retrieved_at_iso,
        auth_mode=lineage.auth_mode,
        query_params=lineage.query_params,
        row_count=lineage.row_count,
        date_range=lineage.date_range,
        symbol_count=lineage.symbol_count,
        extra=extra,
        warnings=tuple(
            list(lineage.warnings)
            + [f"symbol normalised: {canonical} -> {normalised}"]
        ),
    )


def _fetch_equity(
    provider: str,
    symbol: str,
    start: str,
    end: str,
    http_clients: Optional[HttpClients],
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Run an equity / ETF provider for ``symbol``."""
    client = _resolve_client(http_clients, provider)
    provider_symbol, _rec = apply_normalisation(symbol, provider)
    if provider == "stooq":
        from ..stooq_daily import StooqDailyProvider

        if client is None:
            raise RuntimeError(
                "first-dataset: stooq requires an injected client; "
                "pass http_clients={'stooq': fn} or skip stooq in the chain"
            )
        p = StooqDailyProvider(client=client)
        df, lineage = p.fetch_daily(
            provider_symbol, start=start or None, end=end or None,
        )
    elif provider == "yfinance_daily":
        from ..yfinance_daily import YFinanceDailyProvider

        if client is None:
            raise RuntimeError(
                "first-dataset: yfinance_daily requires an injected client"
            )
        p = YFinanceDailyProvider(client=client)
        df, lineage = p.fetch_daily(
            provider_symbol, start=start or None, end=end or None,
        )
    elif provider == "yahooquery_daily":
        from ..yahooquery_daily import YahooQueryDailyProvider

        if client is None:
            raise RuntimeError(
                "first-dataset: yahooquery_daily requires an injected client"
            )
        p = YahooQueryDailyProvider(client=client)
        df, lineage = p.fetch_daily(
            provider_symbol, start=start or None, end=end or None,
        )
    else:
        raise RuntimeError(
            f"first-dataset: unknown equity provider {provider!r}"
        )
    return df, _augment_lineage_with_normalisation(
        lineage, symbol, provider_symbol,
    )


def _fetch_fx(
    provider: str,
    symbol: str,
    start: str,
    end: str,
    http_clients: Optional[HttpClients],
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Run an FX provider for ``symbol``.

    FX providers share the OHLCV daily contract with equities, so we
    delegate to ``_fetch_equity`` after symbol normalisation. The
    library that lands in the timeseries store is selected per section
    in the manifest (``fx_daily``).
    """
    return _fetch_equity(provider, symbol, start, end, http_clients)


def _fetch_crypto(
    provider: str,
    symbol: str,
    start: str,
    end: str,
    http_clients: Optional[HttpClients],
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Run a crypto provider for ``symbol``."""
    if provider == "binance_public_data":
        from ..binance_public_data_daily import (
            BinancePublicDataDailyProvider,
        )

        client = _resolve_client(http_clients, provider)
        if client is None:
            raise RuntimeError(
                "first-dataset: binance_public_data requires an "
                "injected client returning (zip_bytes, sha256)"
            )
        p = BinancePublicDataDailyProvider(client=client)
        # Use the manifest's start year/month -- a single ZIP per call.
        # The manifest currently covers 2023; tests exercise the fixture
        # path via fetch_daily_from_zip directly. This branch keeps the
        # production code path operator-callable without requiring a
        # live network.
        ts = pd.Timestamp(start) if start else pd.Timestamp("2023-01-01")
        return p.fetch_daily(
            symbol, year=int(ts.year), month=int(ts.month),
        )
    raise RuntimeError(
        f"first-dataset: unknown crypto provider {provider!r}"
    )


def _fetch_macro(
    provider: str,
    series_id: str,
    start: str,
    end: str,
    http_clients: Optional[HttpClients],
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Run a macro provider for ``series_id``."""
    if provider == "fred_macro":
        from ..fred_daily import FREDDailyProvider

        client = _resolve_client(http_clients, provider)
        if client is None:
            raise RuntimeError(
                "first-dataset: fred_macro requires an injected client"
            )
        p = FREDDailyProvider(client=client)
        return p.fetch_series(series_id)
    if provider == "dbnomics_macro":
        # DBnomics is not a single-id macro source; in the manifest we
        # only fall back to it when FRED fails. Without a series-key
        # map, we surface a friendly error here so the bootstrap report
        # records the gap explicitly rather than silently skipping.
        raise RuntimeError(
            "first-dataset: dbnomics fallback requires a "
            "series-key map (FRED id -> 'provider/dataset/series'); "
            "skip in the chain unless configured"
        )
    if provider == "ecb_data_portal":
        raise RuntimeError(
            "first-dataset: ecb_data_portal fallback requires a "
            "series-key map (FRED id -> 'dataflow/key'); skip in the "
            "chain unless configured"
        )
    raise RuntimeError(
        f"first-dataset: unknown macro provider {provider!r}"
    )


def _fetch_identity(
    provider: str,
    symbol: str,
    http_clients: Optional[HttpClients],
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Run an identity-mapping provider for ``symbol``.

    Returns a one-row DataFrame so the timeseries store can persist it
    under the ``identity`` library. The lineage carrier is the OpenFIGI
    query's provenance.
    """
    if provider == "openfigi_mapper":
        from ..openfigi_mapper import OpenFIGIClient

        http_post = _resolve_client(http_clients, provider)
        if http_post is None:
            raise RuntimeError(
                "first-dataset: openfigi_mapper requires an injected "
                "http_post callable"
            )
        c = OpenFIGIClient(http_post=http_post)
        result = c.map_symbol(ticker=symbol, id_type="TICKER")
        if not result.mappings:
            # Treat as a clean "no match" -- lineage still carries the
            # warning so the operator sees it in coverage-report.
            df = pd.DataFrame(
                columns=[
                    "symbol", "figi", "ticker", "exchange_code",
                    "market_sector", "security_type", "is_ambiguous",
                ]
            )
            return df, result.provenance
        rows = [
            {
                "symbol": symbol,
                "figi": m.figi or "",
                "ticker": m.ticker or "",
                "exchange_code": m.exchange_code or "",
                "market_sector": m.market_sector or "",
                "security_type": m.security_type or "",
                "is_ambiguous": result.is_ambiguous,
            }
            for m in result.mappings
        ]
        df = pd.DataFrame(rows)
        return df, result.provenance
    raise RuntimeError(
        f"first-dataset: unknown identity provider {provider!r}"
    )


def _fetch_fundamentals(
    provider: str,
    ticker: str,
    http_clients: Optional[HttpClients],
    *,
    cik_map: Optional[Mapping[str, int]] = None,
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Run a fundamentals provider for ``ticker``.

    Builds a long-form DataFrame keyed on (tag, period_end_iso) so the
    timeseries store can persist it under the ``fundamentals`` library.
    The lineage is the EDGAR companyfacts provenance.
    """
    if provider == "sec_edgar_companyfacts":
        from ..sec_edgar_companyfacts import SECEdgarClient

        http_get = _resolve_client(http_clients, provider)
        if http_get is None:
            raise RuntimeError(
                "first-dataset: sec_edgar_companyfacts requires an "
                "injected http_get callable"
            )
        client = SECEdgarClient(http_get=http_get, user_agent="aurora-r157")
        if cik_map and ticker.upper() in cik_map:
            cik = int(cik_map[ticker.upper()])
        else:
            mapping = client.fetch_ticker_cik_map()
            match = next(
                (m for m in mapping if m.ticker == ticker.upper()), None
            )
            if match is None:
                raise RuntimeError(
                    f"first-dataset: sec_edgar: no CIK for ticker "
                    f"{ticker!r}"
                )
            cik = int(match.cik)
        bundle = client.fetch_companyfacts(cik)
        rows = [
            {
                "ticker": ticker.upper(),
                "cik": cik,
                "tag": f.tag,
                "unit": f.unit,
                "value": f.value,
                "period_end_iso": f.period_end_iso,
                "accepted_iso": f.accepted_iso,
                "form": f.form,
            }
            for f in bundle.facts
        ]
        df = pd.DataFrame(rows)
        return df, bundle.provenance
    raise RuntimeError(
        f"first-dataset: unknown fundamentals provider {provider!r}"
    )


_EQUITY_LIKE_SECTIONS: frozenset[str] = frozenset(
    {
        "equities",
        "broad_us_etfs",
        "us_sector_etfs",
        "us_large_caps",
        "international_etfs",
        "bonds_rates_etfs",
        "commodities",
    }
)


def fetch_for_section(
    section_name: str,
    provider: str,
    symbol: str,
    *,
    start: str,
    end: str,
    http_clients: Optional[HttpClients],
    cik_map: Optional[Mapping[str, int]] = None,
) -> Tuple[pd.DataFrame, FreeBulkLineage]:
    """Dispatch to the right per-asset-class fetcher."""
    sn = section_name.lower()
    if sn in _EQUITY_LIKE_SECTIONS:
        return _fetch_equity(provider, symbol, start, end, http_clients)
    if sn == "fx":
        return _fetch_fx(provider, symbol, start, end, http_clients)
    if sn == "crypto":
        return _fetch_crypto(provider, symbol, start, end, http_clients)
    if sn == "macro":
        return _fetch_macro(provider, symbol, start, end, http_clients)
    if sn == "identity":
        return _fetch_identity(provider, symbol, http_clients)
    if sn == "fundamentals":
        return _fetch_fundamentals(
            provider, symbol, http_clients, cik_map=cik_map,
        )
    raise RuntimeError(
        f"first-dataset: unknown section {section_name!r}"
    )

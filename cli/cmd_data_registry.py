"""R155 free-bulk provider registry builder for the data CLI.

Encapsulates the long try/except chain that constructs a role-aware
``DataProviderRegistry`` from the available R155+R156 modules. Modules
that fail to import (e.g. AKShare without env opt-in, optional clients
without their backing transport) are recorded in the returned
``errors`` list rather than raised so the CLI continues to list the
providers that ARE available.
"""
from __future__ import annotations

import os


def _build_r155_registry():
    """Build a role-aware registry of the R155 free-bulk providers.

    Returns ``(registry, errors)``. Module imports that fail (e.g.
    AKShare without env opt-in) are recorded in ``errors`` rather than
    raised so the CLI continues to list the providers that ARE
    available.
    """
    from aurora.core.data_providers import DataProviderRegistry

    registry = DataProviderRegistry()
    errors: list[str] = []

    try:
        from aurora.core.data_providers.finance_database_universe import (
            FinanceDatabaseUniverseProvider,
            descriptor as fd_descriptor,
        )
        registry.register(
            FinanceDatabaseUniverseProvider(client=lambda _ac: []),
            descriptor=fd_descriptor(),
        )
    except Exception as exc:
        errors.append(f"finance_database: {exc}")
    try:
        from aurora.core.data_providers.nasdaq_trader_universe import (
            NasdaqTraderUniverseProvider,
            descriptor as nt_descriptor,
        )
        registry.register(
            NasdaqTraderUniverseProvider(client=lambda _f: ""),
            descriptor=nt_descriptor(),
        )
    except Exception as exc:
        errors.append(f"nasdaq_trader: {exc}")
    try:
        from aurora.core.data_providers.stooq_daily import (
            StooqDailyProvider,
            descriptor as st_descriptor,
        )
        registry.register(
            StooqDailyProvider(client=lambda _s, _a, _b: ""),
            descriptor=st_descriptor(),
        )
    except Exception as exc:
        errors.append(f"stooq: {exc}")
    try:
        import pandas as _pd
        from aurora.core.data_providers.yfinance_daily import (
            YFinanceDailyProvider,
            descriptor as yf_descriptor,
        )
        registry.register(
            YFinanceDailyProvider(
                client=lambda _s, _a, _b, _k: _pd.DataFrame()
            ),
            descriptor=yf_descriptor(),
        )
    except Exception as exc:
        errors.append(f"yfinance_daily: {exc}")
    try:
        import pandas as _pd
        from aurora.core.data_providers.yahooquery_daily import (
            YahooQueryDailyProvider,
            descriptor as yq_descriptor,
        )
        registry.register(
            YahooQueryDailyProvider(
                client=lambda _s, _a, _b, _k: _pd.DataFrame()
            ),
            descriptor=yq_descriptor(),
        )
    except Exception as exc:
        errors.append(f"yahooquery_daily: {exc}")
    try:
        from aurora.core.data_providers.binance_public_data_daily import (
            BinancePublicDataDailyProvider,
            descriptor as bn_descriptor,
        )
        registry.register(
            BinancePublicDataDailyProvider(
                client=lambda _s, _i, _y, _m: (b"", None)
            ),
            descriptor=bn_descriptor(),
        )
    except Exception as exc:
        errors.append(f"binance_public_data: {exc}")
    try:
        from aurora.core.data_providers.coingecko_daily import (
            CoinGeckoDailyProvider,
            descriptor as cg_descriptor,
        )
        registry.register(
            CoinGeckoDailyProvider(client=lambda _c, _v, _d: {}),
            descriptor=cg_descriptor(),
        )
    except Exception as exc:
        errors.append(f"coingecko: {exc}")
    try:
        from aurora.core.data_providers.ccxt_daily import (
            CCXTDailyProvider,
            descriptor as cc_descriptor,
            is_ccxt_available,
        )
        if is_ccxt_available():
            registry.register(CCXTDailyProvider(), descriptor=cc_descriptor())
    except Exception as exc:
        errors.append(f"ccxt_daily: {exc}")
    try:
        import pandas as _pd
        from aurora.core.data_providers.fred_daily import (
            FREDDailyProvider,
            descriptor as fd_macro_descriptor,
        )
        registry.register(
            FREDDailyProvider(
                client=lambda _s, _k: _pd.Series(dtype="float64")
            ),
            descriptor=fd_macro_descriptor(),
        )
    except Exception as exc:
        errors.append(f"fred_macro: {exc}")
    if os.environ.get("AU_ENABLE_AKSHARE") == "1":
        try:
            import pandas as _pd
            from aurora.core.data_providers.akshare_experimental_daily import (
                AKShareExperimentalDailyProvider,
                descriptor as ak_descriptor,
            )
            registry.register(
                AKShareExperimentalDailyProvider(
                    client=lambda _s, _a, _b: _pd.DataFrame()
                ),
                descriptor=ak_descriptor(),
            )
        except Exception as exc:
            errors.append(f"akshare_experimental: {exc}")
    # R156 priority 1: OpenFIGI identifier-mapping. Registered with a
    # stub http_post so listing the registry does not require live
    # credentials. Real callers construct OpenFIGIClient(http_post=...)
    # directly when they need to issue lookups.
    try:
        from aurora.core.data_providers.openfigi_mapper import (
            OpenFIGIClient,
            descriptor as openfigi_descriptor,
        )
        registry.register(
            OpenFIGIClient(http_post=lambda _u, _p, _h: []),
            descriptor=openfigi_descriptor(),
        )
    except Exception as exc:
        errors.append(f"openfigi_mapper: {exc}")
    # R156 priority 3: DBnomics multi-source macro. Registered with a
    # stub http_get so listing the registry never calls out. Real
    # callers construct DBnomicsClient(http_get=...) directly.
    try:
        from aurora.core.data_providers.dbnomics_macro import (
            DBnomicsClient,
            descriptor as dbnomics_descriptor,
        )
        registry.register(
            DBnomicsClient(http_get=lambda _u, _p=None: ""),
            descriptor=dbnomics_descriptor(),
        )
    except Exception as exc:
        errors.append(f"dbnomics_macro: {exc}")
    # R156 priority 4: Coin Metrics community (CRYPTO_METRICS).
    try:
        from aurora.core.data_providers.coinmetrics_community import (
            CoinMetricsCommunityProvider,
            descriptor as cm_descriptor,
        )
        registry.register(
            CoinMetricsCommunityProvider(),
            descriptor=cm_descriptor(),
        )
    except Exception as exc:
        errors.append(f"coinmetrics_community: {exc}")
    # R156 priority 5: ECB Data Portal (FX reference rates + euro-area
    # macro series via SDMX-JSON). Registered with a stub http_get for
    # the same reason; real callers inject a live transport.
    try:
        from aurora.core.data_providers.ecb_data_portal import (
            ECBClient,
            descriptor as ecb_descriptor,
        )
        registry.register(
            ECBClient(http_get=lambda _u, _p=None, _h=None: ""),
            descriptor=ecb_descriptor(),
        )
    except Exception as exc:
        errors.append(f"ecb_data_portal: {exc}")
    # R156 priority 6: Tiingo daily (OPTIONAL_PRICE_FALLBACK, env-gated).
    if os.environ.get("AU_TIINGO_API_TOKEN"):
        try:
            from aurora.core.data_providers.tiingo_daily import (
                TiingoDailyProvider,
                descriptor as tg_descriptor,
            )
            registry.register(
                TiingoDailyProvider(),
                descriptor=tg_descriptor(),
            )
        except Exception as exc:
            errors.append(f"tiingo_daily: {exc}")
    return registry, errors

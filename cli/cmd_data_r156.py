"""R156 complementary provider command implementations.

identity (OpenFIGI), fundamentals (SEC EDGAR), macro search/fetch
(DBnomics, ECB), crypto-metrics (Coin Metrics community).
"""
from __future__ import annotations

import os
import sys

from ._shared import _runtime_error
from .cmd_data_shared import (
    _emit_json_or_table,
    _gate_error,
    _resolve_http_get_for,
    _resolve_http_post_for_openfigi,
)


def cmd_data_identity_map(args):
    """Map a ticker / ISIN / CUSIP / SEDOL to FIGI candidates via OpenFIGI."""
    try:
        from aurora.core.data_providers.openfigi_mapper import OpenFIGIClient
    except Exception as exc:
        return _runtime_error(f"identity map: import failed: {exc}")
    try:
        http_post = _resolve_http_post_for_openfigi()
    except Exception as exc:
        return _runtime_error(f"identity map: {exc}")
    client = OpenFIGIClient(http_post=http_post)
    try:
        result = client.map_symbol(
            ticker=args.symbol,
            exchange=args.exchange,
            id_type=(args.id_type or "TICKER"),
            id_value=args.id_value,
        )
    except RuntimeError as exc:
        return _gate_error(f"identity map: {exc}")
    except Exception as exc:
        return _runtime_error(f"identity map: {exc}")

    if not result.mappings:
        warning = result.warning or "no FIGI match"
        print(f"warning: {warning}", file=sys.stderr)
        # Still emit an empty payload in the requested format so callers
        # can rely on a structured response.
        _emit_json_or_table(
            args, [],
            headers=[
                "figi", "ticker", "name", "exchange_code",
                "market_sector", "security_type",
            ],
        )
        return 0
    rows = [
        {
            "figi": m.figi or "",
            "ticker": m.ticker or "",
            "name": m.name or "",
            "exchange_code": m.exchange_code or "",
            "market_sector": m.market_sector or "",
            "security_type": m.security_type or "",
        }
        for m in result.mappings
    ]
    if result.is_ambiguous:
        print(
            f"note: {len(rows)} candidates returned (ambiguous; refine "
            "with --exchange / --id-type ISIN/CUSIP/SEDOL)",
            file=sys.stderr,
        )
    _emit_json_or_table(
        args, rows,
        headers=[
            "figi", "ticker", "name", "exchange_code",
            "market_sector", "security_type",
        ],
    )
    return 0


def cmd_data_fundamentals_fetch(args):
    """Fetch SEC EDGAR XBRL company facts (PIT-filtered when requested)."""
    try:
        from aurora.core.data_providers.sec_edgar_companyfacts import (
            SECEdgarClient,
            filter_pit_safe,
        )
    except Exception as exc:
        return _runtime_error(f"fundamentals fetch: import failed: {exc}")

    try:
        http_get = _resolve_http_get_for("AU_SEC_EDGAR_HTTP_GET_FACTORY")
    except Exception as exc:
        return _runtime_error(f"fundamentals fetch: {exc}")

    try:
        client = SECEdgarClient(http_get=http_get)
    except RuntimeError as exc:
        return _gate_error(f"fundamentals fetch: {exc}")

    cik_int = args.cik
    if cik_int is None:
        # Resolve CIK from ticker via the public ticker/CIK table.
        try:
            mapping = client.fetch_ticker_cik_map()
        except RuntimeError as exc:
            return _gate_error(f"fundamentals fetch: {exc}")
        except Exception as exc:
            return _runtime_error(
                f"fundamentals fetch: ticker/CIK lookup failed: {exc}"
            )
        ticker = (args.ticker or "").upper()
        match = next((m for m in mapping if m.ticker == ticker), None)
        if match is None:
            return _runtime_error(
                f"fundamentals fetch: no CIK for ticker {ticker!r}; "
                "pass --cik to disambiguate"
            )
        cik_int = match.cik

    try:
        bundle = client.fetch_companyfacts(int(cik_int))
    except RuntimeError as exc:
        return _gate_error(f"fundamentals fetch: {exc}")
    except Exception as exc:
        return _runtime_error(f"fundamentals fetch: {exc}")

    facts = bundle.facts
    if args.decision_date:
        facts = filter_pit_safe(facts, args.decision_date)

    rows = [
        {
            "tag": f.tag,
            "unit": f.unit,
            "value": f.value,
            "period_end_iso": f.period_end_iso,
            "accepted_iso": f.accepted_iso,
            "form": f.form,
        }
        for f in facts
    ]
    if args.decision_date:
        print(
            f"PIT filter: kept {len(rows)} of {len(bundle.facts)} facts "
            f"with accepted_iso <= {args.decision_date}",
            file=sys.stderr,
        )
    _emit_json_or_table(
        args, rows,
        headers=["tag", "unit", "value", "period_end_iso", "accepted_iso", "form"],
    )
    return 0


def cmd_data_macro_search(args):
    """Search the DBnomics catalogue for a query string."""
    if (args.source or "dbnomics").lower() != "dbnomics":
        return _runtime_error(
            f"macro search: unsupported source {args.source!r} (only "
            "'dbnomics' supports search)"
        )
    try:
        from aurora.core.data_providers import ProviderUnavailable
        from aurora.core.data_providers.dbnomics_macro import DBnomicsClient
    except Exception as exc:
        return _runtime_error(f"macro search: import failed: {exc}")
    try:
        http_get = _resolve_http_get_for("AU_DBNOMICS_HTTP_GET_FACTORY")
    except Exception as exc:
        return _runtime_error(f"macro search: {exc}")
    client = DBnomicsClient(http_get=http_get) if http_get else DBnomicsClient()
    try:
        results = client.search(args.query, max_results=args.max_results)
    except ProviderUnavailable as exc:
        return _gate_error(f"macro search: {exc}")
    except RuntimeError as exc:
        return _gate_error(f"macro search: {exc}")
    except Exception as exc:
        return _runtime_error(f"macro search: {exc}")
    rows = [
        {
            "provider_code": p,
            "dataset_code": d,
            "series_code": s,
            "name": n,
        }
        for (p, d, s, n) in results
    ]
    _emit_json_or_table(
        args, rows,
        headers=["provider_code", "dataset_code", "series_code", "name"],
    )
    return 0


def cmd_data_macro_fetch(args):
    """Fetch a macro series from DBnomics or ECB."""
    source = (args.source or "").lower()
    if source not in ("dbnomics", "ecb"):
        return _runtime_error(
            f"macro fetch: unknown source {source!r} (use dbnomics or ecb)"
        )
    try:
        from aurora.core.data_providers import ProviderUnavailable
    except Exception as exc:
        return _runtime_error(f"macro fetch: import failed: {exc}")

    if source == "dbnomics":
        try:
            from aurora.core.data_providers.dbnomics_macro import (
                DBnomicsClient,
                DBnomicsSeriesId,
            )
        except Exception as exc:
            return _runtime_error(f"macro fetch: import failed: {exc}")
        try:
            http_get = _resolve_http_get_for("AU_DBNOMICS_HTTP_GET_FACTORY")
        except Exception as exc:
            return _runtime_error(f"macro fetch: {exc}")
        client = DBnomicsClient(http_get=http_get) if http_get else DBnomicsClient()
        # DBnomics keys are "provider/dataset/series".
        parts = (args.series or "").split("/")
        if len(parts) != 3:
            return _runtime_error(
                f"macro fetch: --series must be 'provider/dataset/series' "
                f"for dbnomics (got {args.series!r})"
            )
        try:
            series_id = DBnomicsSeriesId(*parts)
            series = client.fetch_series(series_id)
        except ProviderUnavailable as exc:
            return _gate_error(f"macro fetch: {exc}")
        except RuntimeError as exc:
            return _gate_error(f"macro fetch: {exc}")
        except Exception as exc:
            return _runtime_error(f"macro fetch: {exc}")
        observations = series.observations
    else:
        try:
            from aurora.core.data_providers.ecb_data_portal import (
                ECBClient,
                ECBSeriesKey,
            )
        except Exception as exc:
            return _runtime_error(f"macro fetch: import failed: {exc}")
        try:
            http_get = _resolve_http_get_for("AU_ECB_HTTP_GET_FACTORY")
        except Exception as exc:
            return _runtime_error(f"macro fetch: {exc}")
        client = ECBClient(http_get=http_get) if http_get else ECBClient()
        # ECB series spec: "dataflow/key", e.g. "EXR/D.USD.EUR.SP00.A".
        parts = (args.series or "").split("/", 1)
        if len(parts) != 2:
            return _runtime_error(
                f"macro fetch: --series must be 'dataflow/key' for ecb "
                f"(got {args.series!r})"
            )
        try:
            series_key = ECBSeriesKey(dataflow=parts[0], key=parts[1])
            series = client.fetch_series(
                series_key, start=args.start, end=args.end,
            )
        except ProviderUnavailable as exc:
            return _gate_error(f"macro fetch: {exc}")
        except RuntimeError as exc:
            return _gate_error(f"macro fetch: {exc}")
        except Exception as exc:
            return _runtime_error(f"macro fetch: {exc}")
        observations = series.observations

    rows = []
    for o in observations:
        # ECB observations carry an obs_status; DBnomics observations
        # carry an attributes mapping. Render both fields when present
        # so the JSON envelope is round-trippable.
        row = {"period_iso": o.period_iso, "value": o.value}
        if hasattr(o, "obs_status"):
            row["obs_status"] = o.obs_status
        rows.append(row)
    headers = ["period_iso", "value"]
    if rows and "obs_status" in rows[0]:
        headers.append("obs_status")
    _emit_json_or_table(args, rows, headers=headers)
    return 0


def cmd_data_crypto_metrics_fetch(args):
    """Fetch a Coin Metrics community asset metric series."""
    if (args.source or "coinmetrics").lower() != "coinmetrics":
        return _runtime_error(
            f"crypto-metrics fetch: unsupported source {args.source!r} "
            "(only 'coinmetrics' is supported)"
        )
    try:
        from aurora.core.data_providers.coinmetrics_community import (
            CoinMetricsClient,
            LICENCE_WARNING,
            OPERATOR_OVERRIDE_ENV,
        )
    except Exception as exc:
        return _runtime_error(f"crypto-metrics fetch: import failed: {exc}")

    try:
        http_get = _resolve_http_get_for("AU_COINMETRICS_HTTP_GET_FACTORY")
    except Exception as exc:
        return _runtime_error(f"crypto-metrics fetch: {exc}")
    try:
        client = CoinMetricsClient(http_get=http_get) if http_get else CoinMetricsClient(
            http_get=None,
        )
    except RuntimeError as exc:
        return _gate_error(f"crypto-metrics fetch: {exc}")

    try:
        observations = client.fetch_metric(
            args.asset, args.metric, start=args.start, end=args.end,
        )
    except RuntimeError as exc:
        return _gate_error(f"crypto-metrics fetch: {exc}")
    except Exception as exc:
        return _runtime_error(f"crypto-metrics fetch: {exc}")

    # Surface the licence warning to stderr unless the operator set
    # the override env. We never silently drop the non-commercial
    # licence flag (R156 spec line 3194-3196).
    if os.environ.get(OPERATOR_OVERRIDE_ENV, "") != "1":
        print(
            f"warning: {LICENCE_WARNING} "
            "(set AU_COINMETRICS_LICENCE_OVERRIDE=1 to acknowledge)",
            file=sys.stderr,
        )
    rows = [
        {
            "time_iso": o.time_iso,
            "asset": o.asset,
            "metric_name": o.metric_name,
            "value": o.value,
        }
        for o in observations
    ]
    _emit_json_or_table(
        args, rows,
        headers=["time_iso", "asset", "metric_name", "value"],
    )
    return 0

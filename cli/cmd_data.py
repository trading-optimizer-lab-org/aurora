"""``forge data`` subcommand group (R49 split).

DataProviderRegistry CLI surface (P0.B): list-providers, fetch, verify.
R155 free bulk daily-data programme: universe, backfill,
provider-status, coverage-report.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ._shared import _runtime_error


# ---------------------------------------------------------------------------
# data subcommands (P0.B DataProviderRegistry)
# ---------------------------------------------------------------------------


def cmd_data_list_providers(args):
    """Print the registered data providers + their PIT/tier posture."""
    from aurora.core.data_providers import get_default_registry
    registry = get_default_registry()
    rows = registry.describe()
    if not rows:
        print("(no providers registered)")
        return 0
    name_w = max(len(r["name"]) for r in rows)
    ver_w = max(len(str(r["version"])) for r in rows)
    print(
        f"{'NAME':<{name_w}}  "
        f"{'VERSION':<{ver_w}}  "
        f"{'PIT':<5}  TIER_PERMISSION  SUPPORTED_TIERS"
    )
    for r in rows:
        pit = "yes" if r["point_in_time"] else "no"
        print(
            f"{r['name']:<{name_w}}  "
            f"{str(r['version']):<{ver_w}}  "
            f"{pit:<5}  {r['tier_permission']:<15}  "
            f"{','.join(r['supported_tiers'])}"
        )
    return 0


def cmd_data_fetch(args):
    """Fetch a Dataset from a provider and write parquet + sidecar."""
    import json
    import os
    from aurora.core.data_providers import get_default_registry
    registry = get_default_registry()
    try:
        ds = registry.fetch(
            args.provider, args.symbol, start=args.start, end=args.end,
        )
    except Exception as exc:
        return _runtime_error(f"data fetch: {exc}")
    out = args.output
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    raw = ds.data
    try:
        import pandas as pd
        if isinstance(raw, pd.Series):
            raw.to_frame(raw.name or "value").to_parquet(out)
        else:
            raw.to_parquet(out)
    except Exception as exc:
        return _runtime_error(f"data fetch: parquet write failed: {exc}")
    sidecar_path = out + ".meta.json"
    meta_payload = {
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
        json.dump(meta_payload, f, indent=2, default=str)
    print(f"Wrote {out} ({len(raw)} rows)")
    print(f"Sidecar metadata: {sidecar_path}")
    print(f"  content_hash: {ds.metadata.content_hash}")
    print(f"  asof_date:    {ds.metadata.asof_date.isoformat()}")
    print(f"  point_in_time:{ds.metadata.point_in_time}")
    print(f"  tier_permission:{ds.metadata.tier_permission}")
    return 0


def cmd_data_verify(args):
    """Recompute content_hash and check tier permission of a fetched parquet."""
    import json
    import os
    parquet = args.parquet
    sidecar = parquet + ".meta.json"
    if not os.path.exists(parquet):
        return _runtime_error(f"data verify: file not found: {parquet}")
    if not os.path.exists(sidecar):
        return _runtime_error(f"data verify: sidecar not found: {sidecar}")
    try:
        with open(sidecar, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as exc:
        return _runtime_error(f"data verify: sidecar read failed: {exc}")

    import pandas as pd
    df = pd.read_parquet(parquet)
    from aurora.core.data_providers import compute_content_hash
    if df.shape[1] == 1:
        recomputed = compute_content_hash(df.iloc[:, 0])
    else:
        recomputed = compute_content_hash(df)
    expected = meta.get("content_hash")
    print(f"file:           {parquet}")
    print(f"expected hash:  {expected}")
    print(f"recomputed hash:{recomputed}")
    if recomputed != expected:
        print("VERIFY: FAIL (content_hash mismatch -- file tampered)")
        return 1
    print("VERIFY: PASS (content_hash matches)")
    print(f"tier_permission: {meta.get('tier_permission')}")
    print(f"point_in_time:   {meta.get('point_in_time')}")
    return 0


# ---------------------------------------------------------------------------
# R155 free-bulk daily-data programme
# ---------------------------------------------------------------------------


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
    try:
        from aurora.core.data_providers.cftc_cot_weekly import (
            CFTCCOTWeeklyProvider,
            descriptor as cftc_descriptor,
            sample_cot_csv,
        )
        registry.register(
            CFTCCOTWeeklyProvider(client=lambda _p: sample_cot_csv()),
            descriptor=cftc_descriptor(),
        )
    except Exception as exc:
        errors.append(f"cftc_cot: {exc}")
    try:
        from aurora.core.data_providers.kenneth_french_factors import (
            KennethFrenchFactorsProvider,
            descriptor as french_descriptor,
            sample_french_factor_csv,
        )
        registry.register(
            KennethFrenchFactorsProvider(
                client=lambda _p: sample_french_factor_csv()
            ),
            descriptor=french_descriptor(),
        )
    except Exception as exc:
        errors.append(f"kenneth_french: {exc}")
    try:
        from aurora.core.data_providers.federal_reserve_h15 import (
            FederalReserveH15Provider,
            descriptor as h15_descriptor,
            sample_h15_csv,
        )
        registry.register(
            FederalReserveH15Provider(client=lambda _p: sample_h15_csv()),
            descriptor=h15_descriptor(),
        )
    except Exception as exc:
        errors.append(f"federal_reserve_h15: {exc}")
    try:
        from aurora.core.data_providers.bls_public_api import (
            BLSPublicAPIProvider,
            descriptor as bls_descriptor,
            sample_bls_json,
        )
        registry.register(
            BLSPublicAPIProvider(client=lambda _p: sample_bls_json()),
            descriptor=bls_descriptor(),
        )
    except Exception as exc:
        errors.append(f"bls_public_api: {exc}")
    try:
        from aurora.core.data_providers.yale_shiller import (
            YaleShillerProvider,
            descriptor as shiller_descriptor,
            sample_shiller_csv,
        )
        registry.register(
            YaleShillerProvider(client=lambda _p: sample_shiller_csv()),
            descriptor=shiller_descriptor(),
        )
    except Exception as exc:
        errors.append(f"yale_shiller: {exc}")
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


def cmd_data_universe_fetch(args):
    """Fetch a universe snapshot from a registered universe provider."""
    source = (args.source or "finance_database").lower()
    if source == "finance_database":
        from aurora.core.data_providers.finance_database_universe import (
            FinanceDatabaseUniverseProvider,
        )
        provider = FinanceDatabaseUniverseProvider()
        try:
            df, lineage = provider.fetch_universe(asset_class=args.asset_class)
        except Exception as exc:
            return _runtime_error(f"universe fetch: {exc}")
    elif source == "nasdaq_trader":
        from aurora.core.data_providers.nasdaq_trader_universe import (
            NasdaqTraderUniverseProvider,
        )
        provider = NasdaqTraderUniverseProvider()
        try:
            df, lineage = provider.fetch_universe()
        except Exception as exc:
            return _runtime_error(f"universe fetch: {exc}")
    else:
        return _runtime_error(
            f"universe fetch: unknown source {source!r} "
            "(use finance_database or nasdaq_trader)"
        )

    if args.output:
        try:
            df.to_parquet(args.output)
        except Exception as exc:
            return _runtime_error(
                f"universe fetch: parquet write failed: {exc}"
            )
        sidecar = args.output + ".meta.json"
        with open(sidecar, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "provider_name": lineage.provider_name,
                    "provider_url": lineage.provider_url,
                    "retrieved_at_iso": lineage.retrieved_at_iso,
                    "row_count": lineage.row_count,
                    "symbol_count": lineage.symbol_count,
                    "snapshot_hash": lineage.lineage.snapshot_hash,
                    "contract_hash": lineage.lineage.contract_hash,
                    "extra": dict(lineage.extra),
                },
                f,
                indent=2,
                default=str,
            )
        print(
            f"Wrote {args.output} ({len(df)} rows, "
            f"{lineage.symbol_count} symbols)"
        )
        print(f"Sidecar: {sidecar}")
    else:
        print(f"shape: {df.shape}")
        print(f"symbols: {lineage.symbol_count}")
        print(f"provider: {lineage.provider_name}")
        print(f"snapshot_hash: {lineage.lineage.snapshot_hash}")
        print(df.head(10).to_string())
    return 0


def cmd_data_universe_diff(args):
    """Diff two universe snapshots (added / removed canonical symbols)."""
    import pandas as pd
    if not os.path.exists(args.prev):
        return _runtime_error(f"universe diff: file not found: {args.prev}")
    if not os.path.exists(args.new):
        return _runtime_error(f"universe diff: file not found: {args.new}")
    try:
        prev = pd.read_parquet(args.prev)
        new = pd.read_parquet(args.new)
    except Exception as exc:
        return _runtime_error(f"universe diff: parquet read failed: {exc}")
    prev_syms = set(
        prev.get("canonical_symbol", pd.Series(dtype="object")).astype(str)
    )
    new_syms = set(
        new.get("canonical_symbol", pd.Series(dtype="object")).astype(str)
    )
    added = sorted(new_syms - prev_syms)
    removed = sorted(prev_syms - new_syms)
    print(f"prev rows: {len(prev)}    new rows: {len(new)}")
    print(f"added: {len(added)}")
    for s in added[:50]:
        print(f"  + {s}")
    if len(added) > 50:
        print(f"  (+{len(added) - 50} more)")
    print(f"removed: {len(removed)}")
    for s in removed[:50]:
        print(f"  - {s}")
    if len(removed) > 50:
        print(f"  (-{len(removed) - 50} more)")
    return 0


def cmd_data_backfill(args):
    """Run a backfill against a named provider for a given asset class."""
    asset_class = args.asset_class.lower()
    if asset_class not in ("equities", "crypto", "macro"):
        return _runtime_error(
            f"backfill: unknown asset_class {asset_class!r} "
            "(equities|crypto|macro)"
        )
    print(
        f"backfill: asset_class={asset_class} provider={args.provider} "
        f"symbols={args.symbols} start={args.start} end={args.end}"
    )
    print("(no-op without explicit ingestion runner; see provider-status)")
    return 0


def cmd_data_provider_terms(args):
    """Print provider terms registry (R178)."""
    from aurora.data_contracts.provider_terms import (
        UsageLabel,
        default_registry,
        render_provider_detail,
        render_table,
    )

    registry = default_registry()
    if getattr(args, "json", False):
        payload = {
            name: registry.require(name).to_dict()
            for name in registry.providers()
        }
        if getattr(args, "provider", None):
            payload = {args.provider: payload[args.provider]}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if getattr(args, "provider", None):
        print(render_provider_detail(registry, args.provider))
        return 0
    if getattr(args, "check_usage", None):
        try:
            usage = UsageLabel(args.check_usage)
        except ValueError:
            return _runtime_error(
                f"unknown usage {args.check_usage!r}; valid: "
                f"{','.join(u.value for u in UsageLabel)}"
            )
        for name in registry.providers():
            terms = registry.require(name)
            verdict = "ALLOW" if terms.permits(usage) else "BLOCK"
            print(f"{verdict}  {name:<18}  {terms.explain(usage)}")
        return 0
    print(render_table(registry))
    return 0


def cmd_data_provider_status(args):
    """Print the registered providers + their last successful fetch + role.

    By default lists only R155 baseline roles (UNIVERSE, PRICE_*,
    CRYPTO_*, MACRO, EXPERIMENTAL) for back-compat with the original
    R155 operator UX. Pass ``--include-complementary`` to also list
    the R156 complementary providers (IDENTITY_MAPPING, FUNDAMENTALS,
    MACRO_MULTI_SOURCE, CRYPTO_METRICS, FX_REFERENCE,
    OPTIONAL_PRICE_FALLBACK).
    """
    from aurora.cli.cmd_data_shared import (
        _R155_ROLE_VALUES,
        _R156_ROLE_VALUES,
    )

    registry, errors = _build_r155_registry()
    rows = registry.role_status()
    include_complementary = bool(getattr(args, "include_complementary", False))
    allowed = set(_R155_ROLE_VALUES)
    if include_complementary:
        allowed = allowed | set(_R156_ROLE_VALUES)
    rows = [r for r in rows if r.get("role") in allowed]
    if not rows:
        print("(no providers registered)")
        return 0
    print(
        f"{'NAME':<26}  {'ROLE':<22}  {'RELIABILITY':<13}  "
        f"{'AUTH':<5}  {'POSTURE':<10}  LAST_SUCCESS"
    )
    for r in rows:
        auth = "yes" if r["auth_required"] else "no"
        last = r.get("last_success") or "(never)"
        print(
            f"{r['name']:<26}  {r['role']:<22}  {r['reliability']:<13}  "
            f"{auth:<5}  {r['adjustment_posture']:<10}  {last}"
        )
    if errors:
        print("\nbootstrap errors (provider not registered):")
        for e in errors:
            print(f"  - {e}")
    return 0


def cmd_data_coverage_report(args):
    """Print a coverage report -- requested vs found vs usable.

    Modes:
        * ``--symbols A,B,C``: legacy stub. Prints "missing" for every
          requested symbol -- placeholder pending a real per-symbol
          inventory walk.
        * ``--dataset first``: read the JSON report saved by the last
          ``aurora data bootstrap-first-dataset`` run and surface the
          per-section coverage in plain language.
        * ``--dataset diversified_seed``: same JSON path; the R158
          manifest also writes its bootstrap report to ``cache_dir() /
          first_dataset_report.json`` since both use the same store.
        * ``--requested-vs-persisted``: print a compact roll-up of
          requested vs persisted counts per section + grand totals.
    """
    dataset = (getattr(args, "dataset", None) or "").strip().lower()
    requested_vs_persisted = bool(
        getattr(args, "requested_vs_persisted", False)
    )
    if dataset in ("first", "diversified_seed"):
        from aurora.core.data_providers.first_dataset import (
            default_report_path,
            load_report,
        )
        try:
            report = load_report()
        except FileNotFoundError as exc:
            if requested_vs_persisted:
                rc = _print_store_coverage_fallback(dataset)
                if rc == 0:
                    return 0
            return _runtime_error(f"coverage-report: {exc}")
        path = default_report_path()
        print(f"first-dataset coverage report (read from {path}):")
        print(f"manifest_name: {report.get('manifest_name')}")
        print(f"dry_run:       {report.get('dry_run')}")
        sections = report.get("sections", []) or []
        if requested_vs_persisted:
            total_req = 0
            total_persisted = 0
            total_failed = 0
            total_fallback = 0
            print("\nrequested-vs-persisted summary:")
            print(
                f"  {'section':<22} {'lib':<14} {'req':>5} {'attempt':>8} "
                f"{'persisted':>10} {'failed':>7} {'fallback':>9}"
            )
            for s in sections:
                req = len(list(s.get("requested", [])))
                results = list(s.get("results", []))
                attempted = sum(
                    1 for r in results if r.get("selected_provider")
                )
                persisted = sum(1 for r in results if r.get("persisted"))
                failed = sum(1 for r in results if not r.get("persisted"))
                fallback = sum(1 for r in results if r.get("fallback_used"))
                print(
                    f"  {s.get('name',''):<22} {s.get('library',''):<14} "
                    f"{req:>5} {attempted:>8} {persisted:>10} {failed:>7} "
                    f"{fallback:>9}"
                )
                total_req += req
                total_persisted += persisted
                total_failed += failed
                total_fallback += fallback
            print(
                f"  {'TOTAL':<22} {'-':<14} {total_req:>5} {'-':>8} "
                f"{total_persisted:>10} {total_failed:>7} {total_fallback:>9}"
            )
            return 0
        for s in sections:
            requested = list(s.get("requested", []))
            fetched = list(s.get("fetched", []))
            failed = list(s.get("failed", []))
            print(
                f"\nsection {s.get('name')!r} (library={s.get('library')!r}): "
                f"requested={len(requested)} fetched={len(fetched)} "
                f"failed={len(failed)}"
            )
            for r in s.get("results", []):
                sym = r.get("symbol")
                if r.get("persisted"):
                    src = r.get("selected_provider") or "?"
                    rows = r.get("rows", 0)
                    fb = " (fallback)" if r.get("fallback_used") else ""
                    print(
                        f"  + {sym}: ok via {src}{fb}, {rows} rows, "
                        f"version={r.get('version','')}"
                    )
                else:
                    err = r.get("error") or "unknown error"
                    contract = list(r.get("contract_errors") or [])
                    if contract:
                        print(
                            f"  - {sym}: rejected (contract violation: "
                            f"{'; '.join(contract)})"
                        )
                    else:
                        print(f"  - {sym}: failed -- {err}")
                    rejected = list(r.get("rejected_providers") or [])
                    if rejected:
                        print(
                            f"      tried providers: {', '.join(rejected)}"
                        )
        return 0

    requested = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if getattr(args, "symbols", None)
        else []
    )
    if not requested:
        print("requested: 0    found: 0    usable: 0")
        print(
            "(supply --symbols A,B,C, or --dataset first to read the "
            "first-dataset bootstrap report)"
        )
        return 0
    print(f"requested: {len(requested)}    found: 0    usable: 0")
    for s in requested:
        print(f"  - {s}: missing (run backfill to populate)")
    return 0


def _print_store_coverage_fallback(dataset: str) -> int:
    """Summarise a seeded dataset from the local TimeSeriesStore.

    The bootstrap JSON report is useful after a fresh download, but local
    operators often have the parquet/sqlite store without that cache file.
    This fallback keeps ``coverage-report --requested-vs-persisted`` useful
    offline by comparing the checked-in manifest with persisted store rows.
    """
    import sqlite3

    from aurora.core import runtime_paths as rp
    from aurora.core.data_providers.first_dataset import load_manifest
    from aurora.data_contracts.timeseries_store import TimeSeriesStore

    manifest_path = {
        "first": Path("config/first_dataset.yaml"),
        "diversified_seed": Path("config/diversified_seed_dataset.yaml"),
    }.get(dataset)
    if manifest_path is None or not manifest_path.exists():
        return 1

    store = TimeSeriesStore(rp.base_data_dir() / "timeseries")
    if not store.index_path.exists():
        return 1

    manifest = load_manifest(manifest_path)
    con = sqlite3.connect(str(store.index_path))
    try:
        rows = con.execute(
            "SELECT library, symbol, COUNT(*) FROM timeseries "
            "GROUP BY library, symbol"
        ).fetchall()
    finally:
        con.close()
    persisted = {(str(library), str(symbol)) for library, symbol, _ in rows}

    print(
        "coverage-report: bootstrap JSON not found; "
        "using local TimeSeriesStore fallback"
    )
    print(f"manifest_name: {manifest.name}")
    print("\nrequested-vs-persisted summary:")
    print(
        f"  {'section':<22} {'lib':<14} {'req':>5} {'attempt':>8} "
        f"{'persisted':>10} {'failed':>7} {'fallback':>9}"
    )
    total_req = 0
    total_persisted = 0
    total_failed = 0
    for section in manifest.sections:
        req = len(section.symbols)
        found = sum(
            1 for symbol in section.symbols
            if (section.library, symbol) in persisted
        )
        failed = req - found
        print(
            f"  {section.name:<22} {section.library:<14} "
            f"{req:>5} {found:>8} {found:>10} {failed:>7} {0:>9}"
        )
        total_req += req
        total_persisted += found
        total_failed += failed
    print(
        f"  {'TOTAL':<22} {'-':<14} {total_req:>5} {'-':>8} "
        f"{total_persisted:>10} {total_failed:>7} {0:>9}"
    )
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``data`` subcommand group on the top-level subparsers."""
    p_data = subparsers.add_parser(
        "data",
        help="Data provider registry (list-providers, fetch, verify)",
        description=(
            "Manage the DataProviderRegistry: list registered providers, "
            "fetch a dataset to parquet (with sidecar metadata), or "
            "verify the content_hash of a previously-fetched file."
        ),
    )
    data_sub = p_data.add_subparsers(dest="data_cmd", required=True)

    p_data_ls = data_sub.add_parser(
        "list-providers",
        help="List registered providers and their PIT/tier posture",
    )
    p_data_ls.set_defaults(func=cmd_data_list_providers)

    p_data_fetch = data_sub.add_parser(
        "fetch", help="Fetch a Dataset and write parquet + sidecar metadata",
    )
    p_data_fetch.add_argument("provider", help="Registered provider name")
    p_data_fetch.add_argument("symbol", help="Ticker symbol")
    p_data_fetch.add_argument("--start", default=None, help="ISO start date")
    p_data_fetch.add_argument("--end", default=None, help="ISO end date")
    p_data_fetch.add_argument(
        "--output", required=True,
        help="Path to write the parquet file (sidecar gets .meta.json suffix)",
    )
    p_data_fetch.set_defaults(func=cmd_data_fetch)

    p_data_verify = data_sub.add_parser(
        "verify", help="Recompute content_hash and check tier permission",
    )
    p_data_verify.add_argument("parquet", help="Path to a parquet emitted by ``data fetch``")
    p_data_verify.set_defaults(func=cmd_data_verify)

    # R155 free-bulk daily-data programme
    p_universe = data_sub.add_parser(
        "universe",
        help="Universe sources (fetch / diff)",
    )
    universe_sub = p_universe.add_subparsers(dest="universe_cmd", required=True)
    p_universe_fetch = universe_sub.add_parser(
        "fetch",
        help="Fetch a universe snapshot from a registered universe provider",
    )
    p_universe_fetch.add_argument(
        "--source",
        default="finance_database",
        choices=["finance_database", "nasdaq_trader"],
        help="Universe provider (default: finance_database)",
    )
    p_universe_fetch.add_argument(
        "--asset-class",
        dest="asset_class",
        default="equities",
        help="Asset class (only used by finance_database)",
    )
    p_universe_fetch.add_argument(
        "--output",
        default=None,
        help="Optional parquet path to write the universe snapshot",
    )
    p_universe_fetch.set_defaults(func=cmd_data_universe_fetch)

    p_universe_diff = universe_sub.add_parser(
        "diff",
        help="Diff two universe snapshots (added / removed canonical symbols)",
    )
    p_universe_diff.add_argument("prev", help="Previous universe snapshot parquet")
    p_universe_diff.add_argument("new", help="New universe snapshot parquet")
    p_universe_diff.set_defaults(func=cmd_data_universe_diff)

    p_backfill = data_sub.add_parser(
        "backfill",
        help="Backfill daily history for a provider + asset class",
    )
    backfill_sub = p_backfill.add_subparsers(dest="backfill_cmd", required=True)
    p_backfill_daily = backfill_sub.add_parser(
        "daily",
        help="Daily backfill (equities / crypto / macro)",
    )
    p_backfill_daily.add_argument(
        "--asset-class",
        dest="asset_class",
        required=True,
        choices=["equities", "crypto", "macro"],
        help="Asset class to backfill",
    )
    p_backfill_daily.add_argument(
        "--provider",
        required=True,
        help="Provider name (matching aurora data provider-status)",
    )
    p_backfill_daily.add_argument(
        "--symbols", default="",
        help="Comma-separated list of symbols",
    )
    p_backfill_daily.add_argument("--start", default=None, help="ISO start date")
    p_backfill_daily.add_argument("--end", default=None, help="ISO end date")
    p_backfill_daily.set_defaults(func=cmd_data_backfill)

    p_provider_status = data_sub.add_parser(
        "provider-status",
        help="List R155 providers + roles + last successful fetch",
    )
    p_provider_status.add_argument(
        "--include-complementary", dest="include_complementary",
        action="store_true",
        help=(
            "Also list R156 complementary providers (IDENTITY_MAPPING, "
            "FUNDAMENTALS, MACRO_MULTI_SOURCE, CRYPTO_METRICS, etc)."
        ),
    )
    p_provider_status.set_defaults(func=cmd_data_provider_status)

    p_coverage = data_sub.add_parser(
        "coverage-report",
        help="Symbols requested vs found vs usable",
    )
    p_coverage.add_argument(
        "--symbols", default="",
        help="Comma-separated list of symbols requested",
    )
    p_coverage.add_argument(
        "--dataset", default=None,
        help=(
            "Named dataset whose bootstrap report should be summarised "
            "(first | diversified_seed). Mutually-useful with "
            "--requested-vs-persisted."
        ),
    )
    p_coverage.add_argument(
        "--requested-vs-persisted", dest="requested_vs_persisted",
        action="store_true",
        help=(
            "Roll-up: requested / attempted / persisted / failed / "
            "fallback counts per section + grand totals."
        ),
    )
    p_coverage.set_defaults(func=cmd_data_coverage_report)

    # R178 provider terms registry
    p_terms = data_sub.add_parser(
        "provider-terms",
        help="Show licence and allowed-usage posture for each provider",
        description=(
            "Print the licence summary, cost tier and allowed-usage labels "
            "for each registered provider. Use --provider to drill in or "
            "--check-usage to test a specific usage label."
        ),
    )
    p_terms.add_argument(
        "--provider", default=None,
        help="Show detail for a single provider",
    )
    p_terms.add_argument(
        "--check-usage", dest="check_usage", default=None,
        help=(
            "Print ALLOW/BLOCK for each provider against this usage label. "
            "Valid labels: smoke_test, personal_research, internal_research, "
            "redistribution, paper_trading, live_trading, report_export"
        ),
    )
    p_terms.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of a table",
    )
    p_terms.set_defaults(func=cmd_data_provider_terms)

    # ------------------------------------------------------------------
    # R156: identity / fundamentals / macro / crypto-metrics
    # ------------------------------------------------------------------
    from aurora.cli.cmd_data_r156 import (
        cmd_data_crypto_metrics_fetch,
        cmd_data_fundamentals_fetch,
        cmd_data_identity_map,
        cmd_data_macro_fetch,
        cmd_data_macro_search,
    )

    p_identity = data_sub.add_parser(
        "identity",
        help="Identifier mapping (OpenFIGI: TICKER/ISIN/CUSIP/SEDOL -> FIGI)",
    )
    identity_sub = p_identity.add_subparsers(dest="identity_cmd", required=True)
    p_identity_map = identity_sub.add_parser(
        "map",
        help="Map a ticker/ISIN/CUSIP/SEDOL to FIGI candidates",
    )
    p_identity_map.add_argument("--source", default="openfigi", choices=["openfigi"])
    p_identity_map.add_argument("--symbol", default=None)
    p_identity_map.add_argument("--exchange", default=None)
    p_identity_map.add_argument("--id-type", dest="id_type", default="TICKER",
        choices=["TICKER", "ISIN", "CUSIP", "SEDOL", "FIGI"])
    p_identity_map.add_argument("--id-value", dest="id_value", default=None)
    p_identity_map.add_argument("--output", default="table", choices=["json", "table"])
    p_identity_map.set_defaults(func=cmd_data_identity_map)

    p_fundamentals = data_sub.add_parser(
        "fundamentals",
        help="Fundamentals (SEC EDGAR XBRL company facts, PIT-aware)",
    )
    fundamentals_sub = p_fundamentals.add_subparsers(dest="fundamentals_cmd", required=True)
    p_fundamentals_fetch = fundamentals_sub.add_parser("fetch")
    p_fundamentals_fetch.add_argument("--source", default="sec-edgar", choices=["sec-edgar"])
    p_fundamentals_fetch.add_argument("--ticker", default=None)
    p_fundamentals_fetch.add_argument("--cik", default=None, type=int)
    p_fundamentals_fetch.add_argument("--decision-date", dest="decision_date", default=None)
    p_fundamentals_fetch.add_argument("--output", default="table", choices=["json", "table"])
    p_fundamentals_fetch.set_defaults(func=cmd_data_fundamentals_fetch)

    p_macro = data_sub.add_parser(
        "macro",
        help="Macro multi-source (DBnomics search/fetch, ECB FX/macro fetch)",
    )
    macro_sub = p_macro.add_subparsers(dest="macro_cmd", required=True)
    p_macro_search = macro_sub.add_parser("search")
    p_macro_search.add_argument("--source", default="dbnomics", choices=["dbnomics"])
    p_macro_search.add_argument("--query", required=True)
    p_macro_search.add_argument("--max-results", dest="max_results", default=20, type=int)
    p_macro_search.add_argument("--output", default="table", choices=["json", "table"])
    p_macro_search.set_defaults(func=cmd_data_macro_search)

    p_macro_fetch = macro_sub.add_parser("fetch")
    p_macro_fetch.add_argument("--source", required=True, choices=["dbnomics", "ecb"])
    p_macro_fetch.add_argument("--series", required=True)
    p_macro_fetch.add_argument("--start", default=None)
    p_macro_fetch.add_argument("--end", default=None)
    p_macro_fetch.add_argument("--output", default="table", choices=["json", "table"])
    p_macro_fetch.set_defaults(func=cmd_data_macro_fetch)

    p_crypto_metrics = data_sub.add_parser(
        "crypto-metrics",
        help="Crypto on-chain metrics (Coin Metrics community API)",
    )
    crypto_metrics_sub = p_crypto_metrics.add_subparsers(dest="crypto_metrics_cmd", required=True)
    p_crypto_metrics_fetch = crypto_metrics_sub.add_parser("fetch")
    p_crypto_metrics_fetch.add_argument("--source", default="coinmetrics", choices=["coinmetrics"])
    p_crypto_metrics_fetch.add_argument("--asset", required=True)
    p_crypto_metrics_fetch.add_argument("--metric", required=True)
    p_crypto_metrics_fetch.add_argument("--start", default=None)
    p_crypto_metrics_fetch.add_argument("--end", default=None)
    p_crypto_metrics_fetch.add_argument("--output", default="table", choices=["json", "table"])
    p_crypto_metrics_fetch.set_defaults(func=cmd_data_crypto_metrics_fetch)

    # ------------------------------------------------------------------
    # Optional local data lakes
    # ------------------------------------------------------------------
    try:
        from aurora.cli.cmd_data_eodhd import register_eodhd
    except ModuleNotFoundError:
        register_eodhd = None
    from aurora.cli.cmd_data_free_us_daily import register_free_us_daily

    if register_eodhd is not None:
        register_eodhd(data_sub)
    register_free_us_daily(data_sub)

    # ------------------------------------------------------------------
    # R157 + R158: bootstrap / manifest-summary / freeze
    # ------------------------------------------------------------------
    from aurora.cli.cmd_data_r157_r158 import (
        cmd_data_bootstrap_first_dataset,
        cmd_data_freeze,
        cmd_data_manifest_summary,
    )

    def _add_bootstrap(name, help_text):
        p = data_sub.add_parser(name, help=help_text)
        p.add_argument("--manifest", required=True)
        p.add_argument("--dry-run", dest="dry_run", action="store_true")
        p.add_argument("--output", default="table", choices=["json", "table"])
        p.set_defaults(func=cmd_data_bootstrap_first_dataset)
        return p

    _add_bootstrap(
        "bootstrap-first-dataset",
        "Walk a first-dataset manifest, fetch + validate via registered "
        "providers, persist to the timeseries store",
    )
    _add_bootstrap(
        "bootstrap-manifest",
        "Alias for bootstrap-first-dataset (R158 diversified_seed manifest)",
    )

    p_manifest_summary = data_sub.add_parser(
        "manifest-summary",
        help="Print requested symbols/sections/totals for a manifest WITHOUT fetching",
    )
    p_manifest_summary.add_argument("--manifest", required=True)
    p_manifest_summary.add_argument("--output", default="table", choices=["json", "table"])
    p_manifest_summary.set_defaults(func=cmd_data_manifest_summary)

    p_freeze = data_sub.add_parser(
        "freeze",
        help="Freeze a SnapshotStore entry from locally-persisted first-dataset rows",
    )
    p_freeze.add_argument("--dataset", default="first")
    p_freeze.add_argument("--symbol", default=None)
    p_freeze.add_argument("--symbols", default=None)
    p_freeze.add_argument("--section", default=None)
    p_freeze.add_argument("--library", default="prices_daily")
    p_freeze.add_argument("--version", default=None)
    p_freeze.add_argument("--provenance", default=None)
    p_freeze.set_defaults(func=cmd_data_freeze)


"""CLI for the free US daily active-stock price lake."""
from __future__ import annotations

import json
from pathlib import Path

from ._shared import _runtime_error


def _root_from_args(args):
    raw = getattr(args, "root", None)
    return Path(raw) if raw else None


def cmd_free_us_daily_build_universe(args) -> int:
    from aurora.core.free_us_daily import (
        build_yahoo_us_stock_universe,
        persist_company_metadata_frame,
        persist_universe,
    )

    try:
        df, metadata, report = build_yahoo_us_stock_universe()
        path = persist_universe(df, root=_root_from_args(args))
        persist_company_metadata_frame(metadata, root=_root_from_args(args))
    except Exception as exc:
        return _runtime_error(f"free-us-daily build-universe: {exc}")
    print(f"Wrote {path}")
    print(f"stock_like_symbols: {len(df)}")
    if getattr(args, "output", "table") == "json":
        print(
            json.dumps(
                {
                    "path": str(path),
                    "stock_like_symbols": int(len(df)),
                    "report": report,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


def cmd_free_us_daily_build_foreign_universe(args) -> int:
    from aurora.core.free_us_daily import (
        build_yahoo_foreign_stock_universe,
        persist_foreign_universe_merge,
    )

    try:
        universe, metadata, report = build_yahoo_foreign_stock_universe(
            priorities=getattr(args, "priorities", "alta,media,baja").split(","),
            min_market_cap_usd=getattr(args, "min_market_cap_usd"),
            min_price_usd=getattr(args, "min_price_usd"),
            min_avg_dollar_volume_3m=getattr(args, "min_avg_dollar_volume_3m"),
            max_quote_age_days=getattr(args, "max_quote_age_days"),
        )
        path = persist_foreign_universe_merge(
            universe,
            metadata,
            report,
            root=_root_from_args(args),
            merge_existing=not getattr(args, "replace_existing", False),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily build-foreign-universe: {exc}")
    payload = {
        "path": str(path),
        "foreign_symbols": int(len(universe)),
        "metadata_rows": int(len(metadata)),
        "report": report,
    }
    if getattr(args, "output", "table") == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"Wrote {path}")
    print(f"foreign_symbols: {len(universe)}")
    print(f"metadata_rows:   {len(metadata)}")
    return 0


def cmd_free_us_daily_download_prices(args) -> int:
    from aurora.core.free_us_daily import download_prices, load_universe

    symbols = [
        s.strip().upper()
        for s in (getattr(args, "symbols", "") or "").split(",")
        if s.strip()
    ]
    start = getattr(args, "start", None)
    if start == "max":
        start = None
    try:
        universe = load_universe(root=_root_from_args(args))
        results = download_prices(
            universe,
            root=_root_from_args(args),
            symbols=symbols or None,
            start=start,
            end=getattr(args, "end", None),
            workers=getattr(args, "workers", 4),
            batch_size=getattr(args, "batch_size", 75),
            retries=getattr(args, "retries", 3),
            retry_wait_seconds=getattr(args, "retry_wait_seconds", 1.0),
            sleep_between_batches=getattr(args, "sleep_between_batches", 2.0),
            max_symbols=getattr(args, "max_symbols", None),
            offset=getattr(args, "offset", 0),
            shard_count=getattr(args, "shard_count", 1),
            shard_index=getattr(args, "shard_index", 0),
            skip_existing=getattr(args, "skip_existing", False),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily download-prices: {exc}")
    ok = sum(1 for r in results if r.status == "ok")
    no_data = sum(1 for r in results if r.status == "no_data")
    invalid = sum(1 for r in results if r.status == "invalid")
    errors = sum(1 for r in results if r.status == "error")
    print(
        "download-prices: "
        f"requested={len(results)} ok={ok} no_data={no_data} "
        f"invalid={invalid} error={errors}"
    )
    return 0


def cmd_free_us_daily_validate(args) -> int:
    from aurora.core.free_us_daily import validate_persisted_prices

    try:
        results = validate_persisted_prices(
            root=_root_from_args(args),
            min_rows=getattr(args, "min_rows", 30),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily validate: {exc}")
    ok = sum(1 for r in results if r.status == "ok")
    bad = len(results) - ok
    print(f"validate: files={len(results)} ok={ok} bad={bad}")
    return 0 if bad == 0 else 1


def cmd_free_us_daily_coverage_report(args) -> int:
    from aurora.core.free_us_daily import build_coverage_report, write_coverage_report

    try:
        path = write_coverage_report(root=_root_from_args(args))
        payload = build_coverage_report(root=_root_from_args(args))
    except Exception as exc:
        return _runtime_error(f"free-us-daily coverage-report: {exc}")
    if getattr(args, "output", "table") == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"coverage report: {path}")
    print(f"universe_symbols:     {payload['universe_symbols']}")
    print(f"downloaded_ok:        {payload['downloaded_ok']}")
    print(f"no_data:              {payload['no_data']}")
    print(f"invalid:              {payload['invalid']}")
    print(f"errors:               {payload['errors']}")
    print(f"coverage_mean_years:  {payload['coverage_mean_years']}")
    print("\ntop 20 most history:")
    for row in payload["top_20_most_history"]:
        print(
            f"  {row['symbol']:<10} rows={row['rows']:<6} "
            f"{row['first_date']}..{row['last_date']} years={row['years']}"
        )
    print("\ntop 20 least history:")
    for row in payload["top_20_least_history"]:
        print(
            f"  {row['symbol']:<10} rows={row['rows']:<6} "
            f"{row['first_date']}..{row['last_date']} years={row['years']}"
        )
    return 0


def cmd_free_us_daily_export_duckdb(args) -> int:
    from aurora.core.free_us_daily import export_duckdb

    try:
        path = export_duckdb(root=_root_from_args(args))
    except Exception as exc:
        return _runtime_error(f"free-us-daily export-duckdb: {exc}")
    print(f"Wrote {path}")
    return 0


def cmd_free_us_daily_export_parquet(args) -> int:
    from aurora.core.free_us_daily import export_all_prices_parquet

    try:
        path = export_all_prices_parquet(root=_root_from_args(args))
    except Exception as exc:
        return _runtime_error(f"free-us-daily export-parquet: {exc}")
    print(f"Wrote {path}")
    return 0


def cmd_free_us_daily_update_daily(args) -> int:
    from aurora.core.free_us_daily import update_daily_prices

    symbols = [
        s.strip().upper()
        for s in (getattr(args, "symbols", "") or "").split(",")
        if s.strip()
    ]
    try:
        results = update_daily_prices(
            root=_root_from_args(args),
            symbols=symbols or None,
            workers=getattr(args, "workers", 2),
            batch_size=getattr(args, "batch_size", 20),
            retries=getattr(args, "retries", 3),
            retry_wait_seconds=getattr(args, "retry_wait_seconds", 1.0),
            sleep_between_batches=getattr(args, "sleep_between_batches", 2.0),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily update-daily: {exc}")
    ok = sum(1 for r in results if r.status == "ok")
    no_data = sum(1 for r in results if r.status == "no_data")
    invalid = sum(1 for r in results if r.status == "invalid")
    errors = sum(1 for r in results if r.status == "error")
    print(
        "update-daily: "
        f"requested={len(results)} ok={ok} no_data={no_data} "
        f"invalid={invalid} error={errors}"
    )
    return 0 if errors == 0 else 1


def cmd_free_us_daily_quality_report(args) -> int:
    from aurora.core.free_us_daily import build_quality_report, write_quality_report

    try:
        path = write_quality_report(root=_root_from_args(args))
        report = build_quality_report(root=_root_from_args(args))
    except Exception as exc:
        return _runtime_error(f"free-us-daily quality-report: {exc}")
    if getattr(args, "output", "table") == "json":
        payload = {
            "path": str(path),
            "rows": int(len(report)),
            "by_status": report["status"].value_counts().to_dict(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"quality report: {path}")
    print(f"rows: {len(report)}")
    print(report["status"].value_counts().to_string())
    return 0


def cmd_free_us_daily_prune_valid_prices(args) -> int:
    from aurora.core.free_us_daily import prune_universe_to_valid_prices

    try:
        payload = prune_universe_to_valid_prices(
            root=_root_from_args(args),
            min_last_close=getattr(args, "min_last_close", 1.0),
            min_median_dollar_volume_90d=getattr(
                args,
                "min_median_dollar_volume_90d",
                100_000,
            ),
            max_last_date_age_days=getattr(args, "max_last_date_age_days", 10),
            max_calendar_gap_days=getattr(args, "max_calendar_gap_days", 31),
            reference_date=getattr(args, "reference_date", None),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily prune-valid-prices: {exc}")
    if getattr(args, "output", "table") == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"universe_before: {payload['universe_before']}")
    print(f"removed_total:   {payload['removed_total']}")
    print(f"universe_after:  {payload['universe_after']}")
    return 0


def cmd_free_us_daily_enrich_metadata(args) -> int:
    from aurora.core.free_us_daily import (
        build_metadata_coverage,
        enrich_company_metadata,
        load_universe,
        write_metadata_failure_report,
    )

    symbols = [
        s.strip().upper()
        for s in (getattr(args, "symbols", "") or "").split(",")
        if s.strip()
    ]
    try:
        universe = load_universe(root=_root_from_args(args))
        results = enrich_company_metadata(
            universe,
            root=_root_from_args(args),
            symbols=symbols or None,
            workers=getattr(args, "workers", 2),
            batch_size=getattr(args, "batch_size", 25),
            retries=getattr(args, "retries", 3),
            retry_wait_seconds=getattr(args, "retry_wait_seconds", 1.0),
            sleep_between_batches=getattr(args, "sleep_between_batches", 2.0),
            max_symbols=getattr(args, "max_symbols", None),
            offset=getattr(args, "offset", 0),
            skip_existing=not getattr(args, "refresh_existing", False),
        )
        write_metadata_failure_report(root=_root_from_args(args))
        payload = build_metadata_coverage(root=_root_from_args(args))
    except Exception as exc:
        return _runtime_error(f"free-us-daily enrich-metadata: {exc}")
    ok = sum(1 for r in results if r.status == "ok")
    no_data = sum(1 for r in results if r.status == "no_data")
    errors = sum(1 for r in results if r.status == "error")
    if getattr(args, "output", "table") == "json":
        print(
            json.dumps(
                {
                    "requested": len(results),
                    "ok": ok,
                    "no_data": no_data,
                    "errors": errors,
                    "coverage": payload,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if errors == 0 else 1
    print(
        "enrich-metadata: "
        f"requested={len(results)} ok={ok} no_data={no_data} error={errors}"
    )
    print(f"metadata_rows:       {payload['metadata_rows']}")
    print(f"sector_populated:    {payload['sector_populated']}")
    print(f"industry_populated:  {payload['industry_populated']}")
    print(f"market_cap_populated: {payload['market_cap_populated']}")
    return 0 if errors == 0 else 1


def cmd_free_us_daily_filter_market_cap(args) -> int:
    from aurora.core.free_us_daily import filter_universe_by_market_cap

    try:
        payload = filter_universe_by_market_cap(
            root=_root_from_args(args),
            min_market_cap=getattr(args, "min_market_cap"),
            drop_missing_market_cap=getattr(args, "drop_missing_market_cap"),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily filter-market-cap: {exc}")
    if getattr(args, "output", "table") == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"universe_before:              {payload['universe_before']}")
    print(f"removed_below_min_market_cap: {payload['removed_below_min_market_cap']}")
    print(f"removed_missing_market_cap:   {payload['removed_missing_market_cap']}")
    print(f"kept_missing_market_cap:      {payload['kept_missing_market_cap']}")
    print(f"universe_after:               {payload['universe_after']}")
    return 0


def cmd_free_us_daily_build_benchmarks(args) -> int:
    from aurora.core.free_us_daily import build_benchmarks

    symbols = [
        s.strip()
        for s in (getattr(args, "symbols", "") or "").split(",")
        if s.strip()
    ]
    try:
        payload = build_benchmarks(
            root=_root_from_args(args),
            symbols=symbols or ("SPY", "^GSPC"),
            end=getattr(args, "end", None),
        )
    except Exception as exc:
        return _runtime_error(f"free-us-daily build-benchmarks: {exc}")
    if getattr(args, "output", "table") == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    for row in payload["benchmarks"]:
        print(
            f"{row['symbol']:<8} {row['status']:<8} rows={row['rows']} "
            f"{row['first_date']}..{row['last_date']}"
        )
    return 0


def register_free_us_daily(data_sub) -> None:
    p = data_sub.add_parser(
        "free-us-daily",
        help="Free active-stock daily price lake",
        description=(
            "Build a zero-cost active-stock daily history lake from "
            "Yahoo screener universes and yfinance daily prices. Active "
            "listings only; not survivorship-bias free."
        ),
    )
    sub = p.add_subparsers(dest="free_us_daily_cmd", required=True)

    def add_root(parser):
        parser.add_argument(
            "--root",
            default=None,
            help=(
                "Optional AU_DATA_DIR-like base for tests/operators. "
                "Default uses aurora.core.runtime_paths.base_data_dir()."
            ),
        )

    p_uni = sub.add_parser(
        "build-universe",
        help="Build filtered US common-stock universe from Yahoo screener",
    )
    add_root(p_uni)
    p_uni.add_argument("--output", default="table", choices=["table", "json"])
    p_uni.set_defaults(func=cmd_free_us_daily_build_universe)

    p_foreign = sub.add_parser(
        "build-foreign-universe",
        help="Add filtered Yahoo foreign common-stock symbols to the universe",
    )
    add_root(p_foreign)
    p_foreign.add_argument(
        "--priorities",
        default="alta,media,baja",
        help="Comma-separated market priority groups: alta,media,baja",
    )
    p_foreign.add_argument(
        "--min-market-cap-usd",
        dest="min_market_cap_usd",
        default=50_000_000,
        type=float,
    )
    p_foreign.add_argument(
        "--min-price-usd",
        dest="min_price_usd",
        default=1.0,
        type=float,
    )
    p_foreign.add_argument(
        "--min-avg-dollar-volume-3m",
        dest="min_avg_dollar_volume_3m",
        default=100_000,
        type=float,
    )
    p_foreign.add_argument(
        "--max-quote-age-days",
        dest="max_quote_age_days",
        default=10,
        type=int,
    )
    p_foreign.add_argument(
        "--replace-existing",
        dest="replace_existing",
        action="store_true",
        help="Replace the current universe instead of merging into it",
    )
    p_foreign.add_argument("--output", default="table", choices=["table", "json"])
    p_foreign.set_defaults(func=cmd_free_us_daily_build_foreign_universe)

    p_dl = sub.add_parser(
        "download-prices",
        help="Download yfinance max daily history for persisted universe",
    )
    add_root(p_dl)
    p_dl.add_argument("--start", default="max", help="ISO start date or max")
    p_dl.add_argument("--end", default=None, help="Optional ISO end date")
    p_dl.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated canonical symbols, e.g. AAPL,MSFT",
    )
    p_dl.add_argument("--workers", default=4, type=int)
    p_dl.add_argument("--batch-size", dest="batch_size", default=75, type=int)
    p_dl.add_argument("--retries", default=3, type=int)
    p_dl.add_argument(
        "--retry-wait-seconds",
        dest="retry_wait_seconds",
        default=1.0,
        type=float,
    )
    p_dl.add_argument(
        "--sleep-between-batches",
        dest="sleep_between_batches",
        default=2.0,
        type=float,
    )
    p_dl.add_argument(
        "--max-symbols",
        dest="max_symbols",
        default=None,
        type=int,
        help="Safety limiter for smoke runs",
    )
    p_dl.add_argument(
        "--offset",
        default=0,
        type=int,
        help="Skip this many symbols after filters/skip-existing are applied",
    )
    p_dl.add_argument(
        "--skip-existing",
        dest="skip_existing",
        action="store_true",
        help="Skip symbols already catalogued as ok, invalid, or no_data",
    )
    p_dl.add_argument(
        "--shard-count",
        dest="shard_count",
        default=1,
        type=int,
        help="Total number of deterministic download shards",
    )
    p_dl.add_argument(
        "--shard-index",
        dest="shard_index",
        default=0,
        type=int,
        help="Zero-based shard index for this worker",
    )
    p_dl.set_defaults(func=cmd_free_us_daily_download_prices)

    p_val = sub.add_parser(
        "validate",
        help="Validate all persisted normalised symbol parquet files",
    )
    add_root(p_val)
    p_val.add_argument("--min-rows", dest="min_rows", default=30, type=int)
    p_val.set_defaults(func=cmd_free_us_daily_validate)

    p_cov = sub.add_parser(
        "coverage-report",
        help="Write and print coverage summary",
    )
    add_root(p_cov)
    p_cov.add_argument("--output", default="table", choices=["table", "json"])
    p_cov.set_defaults(func=cmd_free_us_daily_coverage_report)

    p_duck = sub.add_parser(
        "export-duckdb",
        help="Export valid prices to exports/free_us_daily.duckdb",
    )
    add_root(p_duck)
    p_duck.set_defaults(func=cmd_free_us_daily_export_duckdb)

    p_parquet = sub.add_parser(
        "export-parquet",
        help="Export valid prices to exports/all_prices.parquet",
    )
    add_root(p_parquet)
    p_parquet.set_defaults(func=cmd_free_us_daily_export_parquet)

    p_update = sub.add_parser(
        "update-daily",
        help="Refresh symbols from the latest saved date",
    )
    add_root(p_update)
    p_update.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated canonical symbols, e.g. AAPL,MSFT",
    )
    p_update.add_argument("--workers", default=2, type=int)
    p_update.add_argument("--batch-size", dest="batch_size", default=20, type=int)
    p_update.add_argument("--retries", default=3, type=int)
    p_update.add_argument(
        "--retry-wait-seconds",
        dest="retry_wait_seconds",
        default=1.0,
        type=float,
    )
    p_update.add_argument(
        "--sleep-between-batches",
        dest="sleep_between_batches",
        default=2.0,
        type=float,
    )
    p_update.set_defaults(func=cmd_free_us_daily_update_daily)

    p_quality = sub.add_parser(
        "quality-report",
        help="Write and print per-symbol quality report",
    )
    add_root(p_quality)
    p_quality.add_argument("--output", default="table", choices=["table", "json"])
    p_quality.set_defaults(func=cmd_free_us_daily_quality_report)

    p_prune = sub.add_parser(
        "prune-valid-prices",
        help="Keep only symbols with validated ok price histories",
    )
    add_root(p_prune)
    p_prune.add_argument("--min-last-close", dest="min_last_close", default=1.0, type=float)
    p_prune.add_argument(
        "--min-median-dollar-volume-90d",
        dest="min_median_dollar_volume_90d",
        default=100_000,
        type=float,
    )
    p_prune.add_argument(
        "--max-last-date-age-days",
        dest="max_last_date_age_days",
        default=10,
        type=int,
    )
    p_prune.add_argument(
        "--max-calendar-gap-days",
        dest="max_calendar_gap_days",
        default=31,
        type=int,
    )
    p_prune.add_argument("--reference-date", dest="reference_date", default=None)
    p_prune.add_argument("--output", default="table", choices=["table", "json"])
    p_prune.set_defaults(func=cmd_free_us_daily_prune_valid_prices)

    p_meta = sub.add_parser(
        "enrich-metadata",
        help="Fetch current company metadata, sectors, industries and market caps",
    )
    add_root(p_meta)
    p_meta.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated canonical symbols, e.g. AAPL,MSFT",
    )
    p_meta.add_argument("--workers", default=2, type=int)
    p_meta.add_argument("--batch-size", dest="batch_size", default=25, type=int)
    p_meta.add_argument("--retries", default=3, type=int)
    p_meta.add_argument(
        "--retry-wait-seconds",
        dest="retry_wait_seconds",
        default=1.0,
        type=float,
    )
    p_meta.add_argument(
        "--sleep-between-batches",
        dest="sleep_between_batches",
        default=2.0,
        type=float,
    )
    p_meta.add_argument(
        "--max-symbols",
        dest="max_symbols",
        default=None,
        type=int,
        help="Safety limiter for smoke runs",
    )
    p_meta.add_argument(
        "--offset",
        default=0,
        type=int,
        help="Skip this many symbols after filters/skip-existing are applied",
    )
    p_meta.add_argument(
        "--refresh-existing",
        dest="refresh_existing",
        action="store_true",
        help="Refetch symbols already present in company_metadata.parquet",
    )
    p_meta.add_argument("--output", default="table", choices=["table", "json"])
    p_meta.set_defaults(func=cmd_free_us_daily_enrich_metadata)

    p_filter_mc = sub.add_parser(
        "filter-market-cap",
        help="Prune universe and metadata by current market cap",
    )
    add_root(p_filter_mc)
    p_filter_mc.add_argument(
        "--min-market-cap",
        dest="min_market_cap",
        required=True,
        type=float,
        help="Minimum current market cap to keep, e.g. 50000000",
    )
    p_filter_mc.add_argument(
        "--drop-missing-market-cap",
        dest="drop_missing_market_cap",
        action="store_true",
        help="Also remove symbols with missing/non-positive market cap",
    )
    p_filter_mc.add_argument("--output", default="table", choices=["table", "json"])
    p_filter_mc.set_defaults(func=cmd_free_us_daily_filter_market_cap)

    p_bench = sub.add_parser(
        "build-benchmarks",
        help="Download SPY/S&P 500 benchmark histories separately",
    )
    add_root(p_bench)
    p_bench.add_argument(
        "--symbols",
        default="SPY,^GSPC",
        help="Comma-separated yfinance benchmark symbols",
    )
    p_bench.add_argument(
        "--end",
        default=None,
        help="Exclusive YYYY-MM-DD boundary; no benchmark row may reach it",
    )
    p_bench.add_argument("--output", default="table", choices=["table", "json"])
    p_bench.set_defaults(func=cmd_free_us_daily_build_benchmarks)


__all__ = [
    "cmd_free_us_daily_build_universe",
    "cmd_free_us_daily_build_foreign_universe",
    "cmd_free_us_daily_download_prices",
    "cmd_free_us_daily_validate",
    "cmd_free_us_daily_coverage_report",
    "cmd_free_us_daily_export_duckdb",
    "cmd_free_us_daily_export_parquet",
    "cmd_free_us_daily_update_daily",
    "cmd_free_us_daily_quality_report",
    "cmd_free_us_daily_enrich_metadata",
    "cmd_free_us_daily_filter_market_cap",
    "cmd_free_us_daily_prune_valid_prices",
    "cmd_free_us_daily_build_benchmarks",
    "register_free_us_daily",
]

"""GitHub-only entry point for the maximum-free OpenAP 93 extension."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aurora.core.execution_policy import require_github_execution
from aurora.research.openap_93.current_pipeline import run_current_pipeline
from aurora.research.openap_93.external import download_public_inputs, normalize_public_inputs
from aurora.research.openap_93.registry import load_signal_registry
from aurora.research.openap_93.sources import (
    PUBLIC_SOURCES,
    TEST_SYMBOLS,
    select_sources_lexicographically,
    source_coverage_matrix,
    write_source_evidence,
)


NORMALIZED_PUBLIC_DATASETS = (
    "ff3_daily",
    "ff3_monthly",
    "ff48_sic_codes",
    "liquidity_monthly",
    "vix_daily",
    "gnp_deflator",
    "signal_doc",
    "openap_reference_sample",
    "sec_13f_filings",
    "sec_13f_holdings",
    "sec_13f_exclusions",
    "openfigi_cusip_map",
)


def required_cached_inputs(source_probe: Path, public_inputs: Path) -> tuple[Path, ...]:
    """Return every file required for a deterministic offline execution."""

    normalized = public_inputs / "normalized"
    return (
        source_probe / "source_probe_results.csv",
        source_probe / "source_symbol_probe_results.csv",
        source_probe / "source_coverage_matrix.csv",
        source_probe / "source_ablation.csv",
        source_probe / "selected_sources.json",
        source_probe / "sources.lock.json",
        public_inputs / "public_inputs_manifest.json",
        normalized / "normalized_summary.json",
        normalized / "openap_reference_metadata.json",
        *(normalized / f"{dataset}.parquet" for dataset in NORMALIZED_PUBLIC_DATASETS),
    )


def probe_sources(args: argparse.Namespace) -> None:
    registry = load_signal_registry(args.signals_config)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    probes, symbol_probes = write_source_evidence(output)
    matrix = source_coverage_matrix(registry, probes)
    selected, ablation = select_sources_lexicographically(matrix)
    matrix.to_csv(output / "source_coverage_matrix.csv", index=False)
    ablation.to_csv(output / "source_ablation.csv", index=False)
    (output / "selected_sources.json").write_text(
        json.dumps(selected, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    lock = {
        "sources": [source.__dict__ for source in PUBLIC_SOURCES],
        "probe_results": probes.to_dict(orient="records"),
        "symbol_probe_rows": len(symbol_probes),
    }
    (output / "sources.lock.json").write_text(
        json.dumps(lock, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    if (
        len(registry) != 93
        or len(probes) != len(PUBLIC_SOURCES)
        or len(symbol_probes) != len(PUBLIC_SOURCES) * len(TEST_SYMBOLS)
    ):
        raise RuntimeError("Source probe contract incomplete")


def fetch_public_inputs(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    download_public_inputs(output)
    normalize_public_inputs(output / "raw", output / "normalized")


def _formation_date(value: str) -> str:
    if value.strip().lower() == "today":
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).date().isoformat()
    return value


def _read_universe(path: str) -> set[str] | None:
    if not path:
        return None
    universe = Path(path)
    if not universe.exists():
        raise RuntimeError(f"Universe file does not exist: {universe}")
    values = {
        item.strip().upper()
        for line in universe.read_text(encoding="utf-8-sig").splitlines()
        for item in line.split(",")
        if item.strip() and item.strip().lower() not in {"ticker", "symbol"}
    }
    if not values:
        raise RuntimeError("Universe file contains no symbols")
    return values


def build_current(args: argparse.Namespace) -> None:
    registry = load_signal_registry(args.signals_config)
    selected = (
        {item.strip() for item in args.signals.split(",") if item.strip()}
        if args.signals
        else None
    )
    run_current_pipeline(
        base_database=args.base_db,
        normalized_public_inputs=args.public_inputs_dir,
        source_probe_dir=args.source_probe_dir,
        output_dir=args.output_dir,
        registry=registry,
        formation_at=_formation_date(args.formation_date),
        universe_symbols=_read_universe(args.universe_file),
        selected_signals=selected,
        forward_proxy_certificates=(
            args.forward_proxy_certificates or None
        ),
        forward_proxy_source_manifest=(
            args.forward_proxy_source_manifest or None
        ),
        forward_proxy_mode=getattr(args, "forward_proxy_mode", "strict"),
    )


def run_all(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    source_probe = output / "source_probe"
    public_inputs = output / "public_inputs"
    if args.refresh and args.offline:
        raise RuntimeError("--refresh and --offline cannot be used together")
    required_offline = required_cached_inputs(source_probe, public_inputs)
    cache_complete = all(path.exists() for path in required_offline)
    if not args.offline and (args.refresh or not cache_complete):
        probe_sources(
            argparse.Namespace(
                signals_config=args.signals_config,
                output_dir=str(source_probe),
            )
        )
        fetch_public_inputs(argparse.Namespace(output_dir=str(public_inputs)))
    missing = [str(path) for path in required_offline if not path.exists()]
    if missing:
        raise RuntimeError("Offline cache is incomplete: " + ", ".join(missing))
    build_current(
        argparse.Namespace(
            signals_config=args.signals_config,
            base_db=args.base_db,
            public_inputs_dir=str(public_inputs / "normalized"),
            source_probe_dir=str(source_probe),
            output_dir=str(output),
            formation_date=args.formation_date,
            universe_file=args.universe_file,
            signals=args.signals,
            forward_proxy_certificates=args.forward_proxy_certificates,
            forward_proxy_source_manifest=args.forward_proxy_source_manifest,
            forward_proxy_mode=getattr(args, "forward_proxy_mode", "strict"),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals-config", default="config/openap_93/signals_93.yaml")
    sub = parser.add_subparsers(dest="mode", required=True)
    probe = sub.add_parser("probe-sources")
    probe.add_argument("--output-dir", required=True)
    fetch = sub.add_parser("fetch-public-inputs")
    fetch.add_argument("--output-dir", required=True)
    build = sub.add_parser("build-current")
    build.add_argument(
        "--base-db",
        default=os.environ.get("OPENAP_BASE_DB", "inputs/openap_current.duckdb"),
    )
    build.add_argument("--public-inputs-dir", required=True)
    build.add_argument("--source-probe-dir", required=True)
    build.add_argument("--output-dir", default="outputs/openap_93_current")
    build.add_argument("--formation-date", "--as-of", default="today")
    build.add_argument("--universe-file", default="")
    build.add_argument("--signals", default="")
    build.add_argument("--forward-proxy-certificates", default="")
    build.add_argument("--forward-proxy-source-manifest", default="")
    build.add_argument(
        "--forward-proxy-mode",
        choices=("strict", "advisory"),
        default="strict",
        help="strict uses certified proxies only; advisory exposes failed proxies with a confidence weight",
    )
    run = sub.add_parser("run")
    run.add_argument(
        "--base-db",
        default=os.environ.get("OPENAP_BASE_DB", "inputs/openap_current.duckdb"),
    )
    run.add_argument("--output-dir", default="outputs/openap_93_current")
    run.add_argument("--formation-date", "--as-of", default="today")
    run.add_argument("--universe-file", default="")
    run.add_argument("--signals", default="")
    run.add_argument("--offline", action="store_true")
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--forward-proxy-certificates", default="")
    run.add_argument("--forward-proxy-source-manifest", default="")
    run.add_argument(
        "--forward-proxy-mode",
        choices=("strict", "advisory"),
        default="strict",
        help="strict uses certified proxies only; advisory exposes failed proxies with a confidence weight",
    )
    return parser


def main() -> int:
    require_github_execution("OpenAP 93 maximum-free pipeline")
    args = build_parser().parse_args()
    if args.mode == "probe-sources":
        probe_sources(args)
    elif args.mode == "fetch-public-inputs":
        fetch_public_inputs(args)
    elif args.mode == "build-current":
        build_current(args)
    elif args.mode == "run":
        run_all(args)
    else:
        raise RuntimeError(f"Unsupported mode: {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

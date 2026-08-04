"""GitHub-only entry point for the maximum-free OpenAP 93 extension."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aurora.core.execution_policy import require_github_execution
from aurora.research.openap_93.external import download_public_inputs, normalize_public_inputs
from aurora.research.openap_93.registry import load_signal_registry
from aurora.research.openap_93.sources import (
    PUBLIC_SOURCES,
    select_sources_lexicographically,
    source_coverage_matrix,
    write_source_evidence,
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
    if len(registry) != 93 or len(probes) != len(PUBLIC_SOURCES):
        raise RuntimeError("Source probe contract incomplete")


def fetch_public_inputs(args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    download_public_inputs(output)
    normalize_public_inputs(output / "raw", output / "normalized")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals-config", default="config/openap_93/signals_93.yaml")
    sub = parser.add_subparsers(dest="mode", required=True)
    probe = sub.add_parser("probe-sources")
    probe.add_argument("--output-dir", required=True)
    fetch = sub.add_parser("fetch-public-inputs")
    fetch.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    require_github_execution("OpenAP 93 maximum-free pipeline")
    args = build_parser().parse_args()
    if args.mode == "probe-sources":
        probe_sources(args)
    elif args.mode == "fetch-public-inputs":
        fetch_public_inputs(args)
    else:
        raise RuntimeError(f"Unsupported mode: {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""R157 / R158 first-real-ingestion command implementations.

bootstrap-first-dataset (and the R158 alias bootstrap-manifest), the
freeze command (single-symbol R157 + multi-symbol/section R158), and
the inspection-only manifest-summary view.
"""
from __future__ import annotations

import json
import os
import sys

from ._shared import _runtime_error
from .cmd_data_shared import _resolve_first_dataset_http_clients_factory


def cmd_data_bootstrap_first_dataset(args):
    """Bootstrap the R157 first dataset from a manifest.

    Steps: parse manifest -> fetch each section via its provider chain
    -> validate via the contract gate -> persist to TimeSeriesStore (or
    skip if --dry-run). Saves a JSON report under
    ``runtime_paths.cache_dir() / 'first_dataset_report.json'`` so
    ``aurora data coverage-report --dataset first`` can read it.
    """
    try:
        from aurora.core.data_providers.first_dataset import (
            bootstrap_first_dataset,
            load_manifest,
            report_to_dict,
            save_report,
        )
    except Exception as exc:
        return _runtime_error(f"bootstrap-first-dataset: import failed: {exc}")

    manifest_path = args.manifest
    if not os.path.exists(manifest_path):
        return _runtime_error(
            f"bootstrap-first-dataset: manifest not found: {manifest_path}"
        )
    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        return _runtime_error(
            f"bootstrap-first-dataset: manifest parse failed: {exc}"
        )

    try:
        http_clients = _resolve_first_dataset_http_clients_factory()
    except Exception as exc:
        return _runtime_error(
            f"bootstrap-first-dataset: factory resolution failed: {exc}"
        )

    try:
        report = bootstrap_first_dataset(
            manifest,
            dry_run=bool(args.dry_run),
            http_clients=http_clients,
        )
    except Exception as exc:
        return _runtime_error(f"bootstrap-first-dataset: {exc}")

    if not args.dry_run:
        try:
            save_report(report)
        except Exception as exc:
            print(
                f"warning: failed to save bootstrap report: {exc}",
                file=sys.stderr,
            )

    payload = report_to_dict(report)
    fmt = (getattr(args, "output", None) or "table").lower()
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(
        f"first-dataset bootstrap: manifest={manifest.name!r} "
        f"dry_run={report.dry_run}"
    )
    for section in report.sections:
        n_ok = sum(1 for r in section.results if r.ok or args.dry_run)
        n_fail = sum(
            1 for r in section.results
            if not (r.ok or (args.dry_run and r.error is None))
        )
        print(
            f"  section {section.name!r} (library={section.library!r}): "
            f"requested={len(section.requested)} ok={n_ok} fail={n_fail}"
        )
        for r in section.results:
            tag = "ok" if r.ok else ("dry" if args.dry_run and r.error is None else "FAIL")
            src = r.selected_provider or "-"
            extra = ""
            if r.fallback_used:
                extra = " (fallback)"
            if r.error:
                extra += f" [error: {r.error}]"
            print(
                f"    {tag:<4} {r.symbol:<8} via {src:<22} "
                f"rows={r.rows} {r.date_range[0]}..{r.date_range[1]}{extra}"
            )
    return 0


def cmd_data_manifest_summary(args):
    """Inspection-only summary of a first-dataset manifest.

    Parses the YAML manifest and prints requested symbols by section
    plus totals. Does NOT fetch, validate, or persist anything; useful
    for distinguishing "what the manifest would request" from "what
    has actually been persisted via bootstrap".
    """
    try:
        from aurora.core.data_providers.first_dataset import load_manifest
    except Exception as exc:
        return _runtime_error(f"manifest-summary: import failed: {exc}")

    manifest_path = args.manifest
    if not os.path.exists(manifest_path):
        return _runtime_error(
            f"manifest-summary: manifest not found: {manifest_path}"
        )
    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        return _runtime_error(
            f"manifest-summary: parse failed: {exc}"
        )

    fmt = (getattr(args, "output", None) or "table").lower()
    payload = {
        "name": manifest.name,
        "start": manifest.start,
        "end": manifest.end,
        "frequency": manifest.frequency,
        "section_count": len(manifest.sections),
        "total_symbols": sum(len(s.symbols) for s in manifest.sections),
        "sections": [
            {
                "name": s.name,
                "library": s.library,
                "trust_level": s.trust_level,
                "asset_group": s.asset_group,
                "providers": list(s.providers),
                "symbol_count": len(s.symbols),
                "symbols": list(s.symbols),
                "expected_fields": list(s.expected_fields),
                "allow_fallback": s.allow_fallback,
                "notes": s.notes,
            }
            for s in manifest.sections
        ],
    }
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
        return 0

    print(
        f"manifest {manifest.name!r} "
        f"(start={manifest.start!r} end={manifest.end!r} "
        f"frequency={manifest.frequency!r})"
    )
    print(
        f"sections: {len(manifest.sections)}    "
        f"total symbols: {payload['total_symbols']}"
    )
    for s in manifest.sections:
        print(
            f"\n  section {s.name!r} (library={s.library!r}, "
            f"trust={s.trust_level!r}, group={s.asset_group!r}): "
            f"{len(s.symbols)} symbols"
        )
        if s.providers:
            print(f"    providers: {', '.join(s.providers)}")
        if s.expected_fields:
            print(f"    expected_fields: {', '.join(s.expected_fields)}")
        if s.notes:
            note = " ".join(str(s.notes).split())
            if len(note) > 110:
                note = note[:107] + "..."
            print(f"    notes: {note}")
        # Print up to the first 12 symbols inline; truncate long lists.
        if len(s.symbols) <= 12:
            print(f"    symbols: {', '.join(s.symbols)}")
        else:
            head = ", ".join(s.symbols[:12])
            print(f"    symbols (first 12 of {len(s.symbols)}): {head}, ...")
    return 0


def cmd_data_freeze(args):
    """Freeze a SnapshotStore entry from local persisted first-dataset data.

    R157 single-symbol path: ``--symbol SPY``.
    R158 multi-symbol paths:
        ``--symbols SPY,TLT,GLD``
        ``--section equities`` (read symbols from the bootstrap report)

    Refuses to freeze if a symbol is missing from the timeseries store,
    or if the stored frame's index is non-monotonic / has duplicate
    timestamps. Per-symbol failures are surfaced in the final report;
    the freeze loop continues across the rest.
    """
    dataset = (args.dataset or "first").lower()
    if dataset not in ("first", "diversified_seed"):
        return _runtime_error(
            f"freeze: dataset {dataset!r} not supported "
            "(only 'first' / 'diversified_seed' for now)"
        )
    try:
        from aurora.core.data_providers.first_dataset import (
            freeze_from_first_dataset,
            freeze_many_from_first_dataset,
            load_report,
        )
    except Exception as exc:
        return _runtime_error(f"freeze: import failed: {exc}")

    multi_symbols = (getattr(args, "symbols", None) or "").strip()
    section_filter = (getattr(args, "section", None) or "").strip()

    if multi_symbols or section_filter:
        targets: list[str] = []
        library_overrides: dict[str, str] = {}
        if multi_symbols:
            targets = [s.strip() for s in multi_symbols.split(",") if s.strip()]
        else:
            try:
                report = load_report()
            except FileNotFoundError as exc:
                return _runtime_error(
                    f"freeze: {exc}; run bootstrap-first-dataset first."
                )
            for s in report.get("sections", []) or []:
                if s.get("name") != section_filter:
                    continue
                lib = s.get("library", args.library)
                for r in s.get("results", []) or []:
                    if r.get("persisted"):
                        sym = r.get("symbol")
                        if sym:
                            targets.append(sym)
                            library_overrides[sym] = lib
            if not targets:
                return _runtime_error(
                    f"freeze: no persisted symbols in section "
                    f"{section_filter!r}."
                )
        snaps, errors = freeze_many_from_first_dataset(
            targets,
            library=args.library,
            library_overrides=library_overrides or None,
            provenance=args.provenance,
        )
        print(
            f"freeze multi: ok={len(snaps)} fail={len(errors)} "
            f"(targets={len(targets)})"
        )
        for snap in snaps:
            print(
                f"  + {snap.symbol}: sha256={snap.sha256[:12]} "
                f"bars={snap.n_bars}"
            )
        for sym, reason in errors.items():
            print(f"  - {sym}: {reason}")
        if errors and not snaps:
            return 1
        return 0

    if not getattr(args, "symbol", None):
        return _runtime_error(
            "freeze: pass --symbol, --symbols, or --section."
        )

    try:
        snap = freeze_from_first_dataset(
            args.symbol,
            library=args.library,
            version=args.version,
            provenance=args.provenance or f"first_dataset:{args.library}",
        )
    except (KeyError, FileNotFoundError) as exc:
        return _runtime_error(
            f"freeze: {args.symbol} not in store ({exc}); run "
            "bootstrap-first-dataset first."
        )
    except Exception as exc:
        return _runtime_error(f"freeze: {exc}")

    print(f"frozen snapshot {snap.sha256[:12]} for symbol={snap.symbol!r}")
    print(
        f"  bars={snap.n_bars} window={snap.start.isoformat()}..{snap.end.isoformat()}"
    )
    print(f"  data_path={snap.data_path}")
    print(f"  provenance={snap.provenance}")
    return 0

"""R157 orchestrator -- walks a manifest and persists every winning frame.

Pure orchestration: provider fallback chain per symbol, contract gate
trust (the providers already gate internally), persistence to the
:class:`TimeSeriesStore`, and a :class:`BootstrapReport` containing
per-symbol detail.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

import pandas as pd

from aurora.data_contracts.timeseries_store import (
    TimeSeriesStore,
    default_store,
)

from .._free_bulk_common import FreeBulkContractViolation, FreeBulkLineage
from ._adapters import HttpClients, fetch_for_section
from ._manifest import FirstDatasetManifest, FirstDatasetSection
from ._persist import PersistenceContractViolation, persist
from ._results import BootstrapReport, SectionReport, SymbolResult


__all__ = ["bootstrap_first_dataset"]


def bootstrap_first_dataset(
    manifest: FirstDatasetManifest,
    *,
    registry: Optional[Any] = None,
    store: Optional[TimeSeriesStore] = None,
    dry_run: bool = False,
    http_clients: Optional[HttpClients] = None,
    cik_map: Optional[Mapping[str, int]] = None,
) -> BootstrapReport:
    """Walk ``manifest`` and persist every fetched + validated frame.

    Args:
        manifest: parsed :class:`FirstDatasetManifest`.
        registry: unused today; kept in the signature for forward
            compatibility with the role-aware DataProviderRegistry. The
            section dispatch already routes by name without a registry
            lookup.
        store: TimeSeriesStore instance. Defaults to
            :func:`aurora.data_contracts.timeseries_store.default_store`.
        dry_run: when True, runs every fetcher and validator but never
            calls ``store.put``. Useful for checking provider auth /
            response shape before committing.
        http_clients: mapping from provider name to an injectable
            transport callable. The orchestrator never builds default
            production clients on its own -- callers must opt in.
        cik_map: optional ticker -> CIK override for SEC EDGAR. Skips
            the public ticker/CIK lookup when present.

    Returns:
        :class:`BootstrapReport` with per-section, per-symbol details.
    """
    del registry  # Not used yet; kept for forward compatibility.
    target_store = store if store is not None else default_store()
    section_reports: list[SectionReport] = []
    for section in manifest.sections:
        results: list[SymbolResult] = []
        for symbol in section.symbols:
            res = _bootstrap_symbol(
                section,
                symbol,
                manifest=manifest,
                store=target_store,
                dry_run=dry_run,
                http_clients=http_clients,
                cik_map=cik_map,
            )
            results.append(res)
        section_reports.append(
            SectionReport(
                name=section.name,
                library=section.library,
                requested=section.symbols,
                results=tuple(results),
            )
        )
    return BootstrapReport(
        manifest_name=manifest.name,
        dry_run=dry_run,
        sections=tuple(section_reports),
    )


def _bootstrap_symbol(
    section: FirstDatasetSection,
    symbol: str,
    *,
    manifest: FirstDatasetManifest,
    store: TimeSeriesStore,
    dry_run: bool,
    http_clients: Optional[HttpClients],
    cik_map: Optional[Mapping[str, int]],
) -> SymbolResult:
    """Run the fallback chain for one symbol and persist the winning frame."""
    rejected: list[str] = []
    warnings: list[str] = []
    selected: Optional[Tuple[str, pd.DataFrame, FreeBulkLineage]] = None
    last_error: Optional[str] = None
    contract_errors: Tuple[str, ...] = ()

    for idx, provider in enumerate(section.providers):
        if idx > 0 and not section.allow_fallback:
            warnings.append(
                f"section {section.name!r}: allow_fallback=False; "
                f"skipping provider {provider!r} after primary failure."
            )
            rejected.append(provider)
            continue
        try:
            df, lineage = fetch_for_section(
                section.name,
                provider,
                symbol,
                start=manifest.start,
                end=manifest.end,
                http_clients=http_clients,
                cik_map=cik_map,
            )
        except FreeBulkContractViolation as exc:
            rejected.append(provider)
            warnings.append(
                f"provider {provider!r} produced a contract violation: {exc}"
            )
            last_error = str(exc)
            contract_errors = exc.errors
            continue
        except Exception as exc:
            rejected.append(provider)
            cls = type(exc).__name__
            warnings.append(
                f"provider {provider!r} failed ({cls}): {exc}"
            )
            last_error = f"{cls}: {exc}"
            continue
        # Empty frame is treated as soft failure so the next provider in
        # the chain gets a chance.
        if df is None or len(df) == 0:
            rejected.append(provider)
            warnings.append(
                f"provider {provider!r} returned no rows for {symbol!r}."
            )
            last_error = "empty"
            continue
        selected = (provider, df, lineage)
        break

    if selected is None:
        return SymbolResult(
            symbol=symbol,
            selected_provider=None,
            rows=0,
            date_range=("", ""),
            fallback_used=False,
            rejected_providers=tuple(rejected),
            warnings=tuple(warnings),
            error=last_error or "no_provider_succeeded",
            contract_errors=contract_errors,
            persisted=False,
            library=section.library,
        )

    provider_name, df, lineage = selected
    fallback_used = bool(rejected)

    # The provider modules already gate on the contract internally -- a
    # successful return means the frame passed validation. Persist
    # unless dry_run.
    if dry_run:
        return SymbolResult(
            symbol=symbol,
            selected_provider=provider_name,
            rows=int(len(df)),
            date_range=lineage.date_range,
            fallback_used=fallback_used,
            rejected_providers=tuple(rejected),
            warnings=tuple(warnings + list(lineage.warnings)),
            error=None,
            contract_errors=(),
            persisted=False,
            library=section.library,
            version="",
            content_hash=lineage.lineage.snapshot_hash,
        )

    try:
        version, content_hash = persist(
            store, section.library, symbol, df, lineage,
            section_name=section.name,
            expected_fields=section.expected_fields,
            frequency=manifest.frequency,
        )
    except PersistenceContractViolation as exc:
        return SymbolResult(
            symbol=symbol,
            selected_provider=provider_name,
            rows=int(len(df)),
            date_range=lineage.date_range,
            fallback_used=fallback_used,
            rejected_providers=tuple(rejected),
            warnings=tuple(
                warnings + list(lineage.warnings)
                + [f"persistence rejected: {exc}"]
            ),
            error=str(exc),
            contract_errors=exc.errors,
            persisted=False,
            library=section.library,
        )
    except Exception as exc:
        cls = type(exc).__name__
        return SymbolResult(
            symbol=symbol,
            selected_provider=provider_name,
            rows=int(len(df)),
            date_range=lineage.date_range,
            fallback_used=fallback_used,
            rejected_providers=tuple(rejected),
            warnings=tuple(
                warnings + list(lineage.warnings)
                + [f"persistence failed: {cls}: {exc}"]
            ),
            error=f"{cls}: {exc}",
            persisted=False,
            library=section.library,
        )

    return SymbolResult(
        symbol=symbol,
        selected_provider=provider_name,
        rows=int(len(df)),
        date_range=lineage.date_range,
        fallback_used=fallback_used,
        rejected_providers=tuple(rejected),
        warnings=tuple(warnings + list(lineage.warnings)),
        error=None,
        persisted=True,
        library=section.library,
        version=version,
        content_hash=content_hash,
    )

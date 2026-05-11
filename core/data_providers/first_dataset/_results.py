"""R157 first-dataset report dataclasses + JSON (de)serialisation.

Holds the per-symbol / per-section / top-level result frozen
dataclasses, plus the helpers used by ``aurora data
coverage-report`` to read a previous run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

from aurora.core.runtime_paths import cache_dir


__all__ = [
    "SymbolResult",
    "SectionReport",
    "BootstrapReport",
    "default_report_path",
    "report_to_dict",
    "save_report",
    "load_report",
]


@dataclass(frozen=True)
class SymbolResult:
    """Outcome for one symbol within one section."""

    symbol: str
    selected_provider: Optional[str]
    rows: int
    date_range: Tuple[str, str]
    fallback_used: bool
    rejected_providers: Tuple[str, ...]
    warnings: Tuple[str, ...]
    error: Optional[str] = None
    contract_errors: Tuple[str, ...] = ()
    persisted: bool = False
    library: str = ""
    version: str = ""
    content_hash: str = ""

    @property
    def ok(self) -> bool:
        """True iff the symbol persisted to the store."""
        return self.persisted and self.error is None


@dataclass(frozen=True)
class SectionReport:
    """Per-section roll-up: requested / fetched / failed / rows."""

    name: str
    library: str
    requested: Tuple[str, ...]
    results: Tuple[SymbolResult, ...]

    @property
    def fetched(self) -> Tuple[str, ...]:
        return tuple(r.symbol for r in self.results if r.ok)

    @property
    def failed(self) -> Tuple[str, ...]:
        return tuple(r.symbol for r in self.results if not r.ok)


@dataclass(frozen=True)
class BootstrapReport:
    """Top-level outcome of :func:`bootstrap_first_dataset`."""

    manifest_name: str
    dry_run: bool
    sections: Tuple[SectionReport, ...]

    def section(self, name: str) -> Optional[SectionReport]:
        for s in self.sections:
            if s.name == name:
                return s
        return None

    def all_results(self) -> Tuple[SymbolResult, ...]:
        out: list[SymbolResult] = []
        for s in self.sections:
            out.extend(s.results)
        return tuple(out)

    def requested_vs_persisted_summary(self) -> dict[str, Any]:
        """Return a R158 requested-vs-persisted breakdown.

        Surfaces the gap between what the manifest asked for and what
        actually landed in the store. Per-section counts are returned
        in declaration order so the CLI table prints stably.
        """
        per_section: list[dict[str, Any]] = []
        total_requested = 0
        total_attempted = 0
        total_persisted = 0
        total_failed = 0
        total_fallback = 0
        for s in self.sections:
            requested = len(s.requested)
            attempted = sum(
                1 for r in s.results if r.selected_provider is not None
            )
            persisted = sum(1 for r in s.results if r.persisted)
            failed = sum(1 for r in s.results if not r.persisted)
            fallback = sum(1 for r in s.results if r.fallback_used)
            per_section.append(
                {
                    "name": s.name,
                    "library": s.library,
                    "requested": requested,
                    "attempted": attempted,
                    "persisted": persisted,
                    "failed": failed,
                    "fallback": fallback,
                }
            )
            total_requested += requested
            total_attempted += attempted
            total_persisted += persisted
            total_failed += failed
            total_fallback += fallback
        return {
            "manifest_name": self.manifest_name,
            "dry_run": self.dry_run,
            "requested_count": total_requested,
            "attempted_count": total_attempted,
            "persisted_count": total_persisted,
            "failed_count": total_failed,
            "fallback_count": total_fallback,
            "sections": per_section,
        }


# ---------------------------------------------------------------------------
# Report (de)serialisation -- used by coverage-report to read a previous run.
# ---------------------------------------------------------------------------


def default_report_path() -> Path:
    """Return the canonical bootstrap-report JSON location."""
    return cache_dir() / "first_dataset_report.json"


def report_to_dict(report: BootstrapReport) -> dict[str, Any]:
    """Serialize a :class:`BootstrapReport` for JSON / table output."""
    return {
        "manifest_name": report.manifest_name,
        "dry_run": report.dry_run,
        "sections": [
            {
                "name": s.name,
                "library": s.library,
                "requested": list(s.requested),
                "fetched": list(s.fetched),
                "failed": list(s.failed),
                "results": [
                    {
                        "symbol": r.symbol,
                        "selected_provider": r.selected_provider,
                        "rows": r.rows,
                        "date_range": list(r.date_range),
                        "fallback_used": r.fallback_used,
                        "rejected_providers": list(r.rejected_providers),
                        "warnings": list(r.warnings),
                        "error": r.error,
                        "contract_errors": list(r.contract_errors),
                        "persisted": r.persisted,
                        "library": r.library,
                        "version": r.version,
                        "content_hash": r.content_hash,
                    }
                    for r in s.results
                ],
            }
            for s in report.sections
        ],
    }


def save_report(report: BootstrapReport, path: Optional[Path] = None) -> Path:
    """Persist a bootstrap report as JSON. Returns the written path."""
    target = Path(path) if path is not None else default_report_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report_to_dict(report), indent=2, default=str),
        encoding="utf-8",
    )
    return target


def load_report(path: Optional[Path] = None) -> dict[str, Any]:
    """Read a previously-saved bootstrap report. Returns the raw dict."""
    target = Path(path) if path is not None else default_report_path()
    if not target.exists():
        raise FileNotFoundError(
            f"first-dataset report not found at {target}; "
            "run `aurora data bootstrap-first-dataset` first."
        )
    return json.loads(target.read_text(encoding="utf-8"))

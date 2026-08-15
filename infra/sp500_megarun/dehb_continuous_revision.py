"""Fail-closed boundary between frozen science and operational runtime changes."""

from __future__ import annotations

from collections.abc import Iterable


_OPERATIONAL_PREFIXES = (".github/", "tests/")
_OPERATIONAL_PATHS = frozenset(
    {
        "infra/sp500_megarun/dehb_continuous_coordinator.py",
        "infra/sp500_megarun/dehb_continuous_archive.py",
        "infra/sp500_megarun/dehb_continuous_migration.py",
        "infra/sp500_megarun/dehb_continuous_revision.py",
        "infra/sp500_megarun/dehb_continuous_schema.py",
        "infra/sp500_megarun/dehb_continuous_store.py",
        "infra/sp500_megarun/dehb_continuous_worker.py",
        "scripts/assert_sp500_dehb_database_quiescent.py",
        "scripts/build_sp500_dehb_historical_archive.py",
        "scripts/close_sp500_dehb_database_run_sessions.py",
        "scripts/compact_sp500_dehb_database_clone.py",
        "scripts/reduce_sp500_dehb_continuous_snapshot.py",
        "scripts/run_sp500_dehb_continuous_worker.py",
        "scripts/segment_sp500_dehb_continuous_state.py",
        "scripts/verify_sp500_dehb_database_clone.py",
        "scripts/verify_sp500_dehb_scientific_revision.py",
    }
)


def unexpected_scientific_changes(paths: Iterable[str]) -> tuple[str, ...]:
    unexpected = {
        str(path).replace("\\", "/")
        for path in paths
        if not str(path).replace("\\", "/").startswith(_OPERATIONAL_PREFIXES)
        and str(path).replace("\\", "/") not in _OPERATIONAL_PATHS
    }
    return tuple(sorted(unexpected))


__all__ = ["unexpected_scientific_changes"]

"""R157/R158 date-sanity smoke test.

A timestamp-scale bug in a prior session shipped a corrupt BTCUSDT
parquet whose trailing rows carried year=58296. The bug was fixed in
the provider but the corrupt v1 still sits on disk under the operator's
``$AU_DATA_DIR/timeseries/`` tree. This test guards against the bug
class returning: any persisted daily series whose ``read()`` resolves
through the default (latest) version must not contain dates beyond
``MAX_SANE_YEAR``.

The test is a smoke check, not a sweep -- it only inspects libraries
that are present locally. CI hosts without local data run the test as
a no-op + a printed skip reason rather than failing on missing fixtures.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest


MAX_SANE_YEAR = 2035
SANITY_LIBRARIES = ("crypto_daily", "prices_daily", "fx_daily", "macro_daily")


def _resolve_store_root() -> Path | None:
    """Return the on-disk timeseries root, or None if it does not exist.

    Resolves through ``aurora.core.runtime_paths`` so the test honours
    ``AU_DATA_DIR`` env var overrides without touching production state.
    """
    from aurora.core import runtime_paths as rp

    root = rp.base_data_dir() / "timeseries"
    if not root.exists():
        return None
    return root


def _list_symbols(library_root: Path) -> list[str]:
    """Return the symbols (sub-directories) under one library."""
    if not library_root.exists() or not library_root.is_dir():
        return []
    return sorted(p.name for p in library_root.iterdir() if p.is_dir())


def test_default_read_returns_dates_within_sane_year_window():
    """For every persisted symbol, the default ``read()`` must stay <= 2035."""
    root = _resolve_store_root()
    if root is None:
        pytest.skip("no local timeseries store; nothing to sanity-check")

    from aurora.data_contracts.timeseries_store import TimeSeriesStore

    store = TimeSeriesStore(root)
    cutoff = pd.Timestamp(f"{MAX_SANE_YEAR}-01-01")
    bad: list[tuple[str, str, int, pd.Timestamp]] = []

    for library in SANITY_LIBRARIES:
        for symbol in _list_symbols(root / library):
            try:
                df = store.read(library=library, symbol=symbol)
            except Exception:
                # Default read failures are not in scope for this test;
                # the goal is to assert that when a read SUCCEEDS the
                # returned frame is not corrupt.
                continue
            if df is None or len(df) == 0:
                continue
            idx = pd.to_datetime(df.index, errors="coerce")
            n_bad = int((idx > cutoff).sum())
            if n_bad > 0:
                bad.append((library, symbol, n_bad, idx.max()))

    if bad:
        lines = [
            f"  {lib}/{sym}: {n} rows beyond {MAX_SANE_YEAR}; max_ts={ts}"
            for lib, sym, n, ts in bad
        ]
        pytest.fail(
            "Daily timeseries series have absurd dates -- timestamp-scale "
            "bug regression suspected. Inspect the offending versions and "
            "quarantine via aurora.data_contracts.QuarantineLedger. "
            "Affected:\n" + "\n".join(lines)
        )


def test_btcusdt_corrupt_version_remains_quarantined_when_present():
    """If the historical 20260510T172618 BTCUSDT version is still on disk,
    confirm the QuarantineLedger has it marked.

    This protects against the operator (or a script) accidentally
    re-approving the parquet with year=58296 rows.
    """
    root = _resolve_store_root()
    if root is None:
        pytest.skip("no local timeseries store; nothing to check")
    btc_dir = root / "crypto_daily" / "BTCUSDT"
    if not btc_dir.exists():
        pytest.skip("BTCUSDT not present locally")

    from aurora.data_contracts.timeseries_store import TimeSeriesStore
    from aurora.data_contracts.quality import QuarantineLedger
    from aurora.core import runtime_paths as rp

    store = TimeSeriesStore(root)
    versions = store.list_versions(library="crypto_daily", symbol="BTCUSDT")
    if "20260510T172618" not in versions:
        pytest.skip("corrupt version no longer indexed; nothing to assert")

    ledger = QuarantineLedger(rp.base_data_dir() / "quarantine_ledger.jsonl")
    if not ledger.path.exists():
        pytest.fail(
            "BTCUSDT 20260510T172618 is still indexed but no quarantine "
            "ledger is present. Run: \n"
            "  from aurora.data_contracts.quality import QuarantineLedger\n"
            "  from aurora.core import runtime_paths as rp\n"
            "  ledger = QuarantineLedger(rp.base_data_dir() / 'quarantine_ledger.jsonl')\n"
            "  ledger.quarantine(provider='binance_public_data',\n"
            "                    library='crypto_daily', symbol='BTCUSDT',\n"
            "                    version='20260510T172618',\n"
            "                    reason='timestamp scale parsing bug',\n"
            "                    actor='<operator>')"
        )
    assert ledger.is_quarantined(
        provider="binance_public_data",
        library="crypto_daily",
        symbol="BTCUSDT",
        version="20260510T172618",
    ), (
        "BTCUSDT 20260510T172618 is on disk but not in quarantine ledger. "
        "Add an entry via QuarantineLedger.quarantine()."
    )

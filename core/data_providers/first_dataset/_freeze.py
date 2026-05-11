"""R157 / R158 step 5 -- read persisted frames and freeze them.

Reads back from the TimeSeriesStore and bridges into the SnapshotStore
so a strategy can run from local persisted data without hitting the
network.

R158 extension: a multi-symbol helper
:func:`freeze_many_from_first_dataset` walks a list of canonical
symbols, freezes each one, and returns a list of resulting snapshots
plus a dict of failures keyed by symbol. The single-symbol helper
:func:`freeze_from_first_dataset` is unchanged for back-compat.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Tuple

import pandas as pd

from aurora.data_contracts.timeseries_store import (
    TimeSeriesStore,
    default_store,
)


__all__ = [
    "freeze_from_first_dataset",
    "freeze_many_from_first_dataset",
    "load_from_first_dataset",
]


def load_from_first_dataset(
    symbol: str,
    *,
    library: str = "prices_daily",
    version: Optional[str] = None,
    store: Optional[TimeSeriesStore] = None,
) -> pd.DataFrame:
    """Read a previously-persisted first-dataset frame.

    Returns the stored DataFrame as-is (with the contract's timestamp
    column intact). Used by the smoke backtest helper to prove a
    strategy can run from local persisted data without hitting the
    network.

    Raises:
        KeyError: nothing in the store under ``library/symbol``.
    """
    target_store = store if store is not None else default_store()
    return target_store.read(library, symbol, version=version)


def freeze_from_first_dataset(
    symbol: str,
    *,
    library: str = "prices_daily",
    version: Optional[str] = None,
    store: Optional[TimeSeriesStore] = None,
    snapshot_root: Optional[Path] = None,
    provenance: Optional[str] = None,
    locked: bool = False,
) -> Any:
    """Freeze a SnapshotStore entry from the local first-dataset store.

    Reads the requested ``library/symbol/version`` from the timeseries
    store, extracts the ``close`` column (OHLCV) or the single-value
    column (macro), and calls :meth:`SnapshotStore.freeze`. Returns the
    resulting :class:`DataSnapshot`.

    Refuses to freeze if the stored frame's timestamp column is missing
    or non-monotonic -- the contract gate at ingestion already blocks
    this, but the freeze path checks again so a manually-tampered store
    does not produce an approved snapshot.
    """
    df = load_from_first_dataset(
        symbol, library=library, version=version, store=store,
    )
    series = _frame_to_close_series(df, library, symbol)
    if not series.index.is_monotonic_increasing:
        raise ValueError(
            f"freeze_from_first_dataset: index for {library}/{symbol} is not "
            "monotonically increasing; refusing to freeze."
        )
    if series.index.duplicated().any():
        raise ValueError(
            f"freeze_from_first_dataset: duplicate timestamps in "
            f"{library}/{symbol}; refusing to freeze."
        )
    if len(series) == 0:
        raise ValueError(
            f"freeze_from_first_dataset: no rows in {library}/{symbol}."
        )

    from aurora.core.runtime_paths import snapshot_root as _default_snapshot_root
    from aurora.core.snapshots import SnapshotStore

    root = snapshot_root if snapshot_root is not None else _default_snapshot_root()
    snap_store = SnapshotStore(str(root))
    return snap_store.freeze(
        series,
        symbol=symbol,
        provenance=provenance or f"first_dataset:{library}",
        locked=locked,
    )


def freeze_many_from_first_dataset(
    symbols: Iterable[str],
    *,
    library: str = "prices_daily",
    library_overrides: Optional[Mapping[str, str]] = None,
    store: Optional[TimeSeriesStore] = None,
    snapshot_root: Optional[Path] = None,
    provenance: Optional[str] = None,
    locked: bool = False,
) -> Tuple[List[Any], dict[str, str]]:
    """Freeze a list of canonical symbols.

    ``library_overrides`` lets the caller route per-symbol libraries
    (e.g. ``{"BTCUSDT": "crypto_daily", "DGS10": "macro_daily"}``).
    Symbols not present in the override map fall back to the default
    ``library`` argument.

    Returns ``(snapshots, errors)`` where ``errors`` maps the failing
    symbol to a human-readable reason. The walker keeps going on
    individual failures so an operator can freeze the survivors.
    """
    overrides = dict(library_overrides or {})
    snaps: list[Any] = []
    errors: dict[str, str] = {}
    for sym in symbols:
        sym_library = overrides.get(sym, library)
        try:
            snap = freeze_from_first_dataset(
                sym,
                library=sym_library,
                store=store,
                snapshot_root=snapshot_root,
                provenance=provenance or f"first_dataset:{sym_library}",
                locked=locked,
            )
        except (KeyError, FileNotFoundError) as exc:
            errors[sym] = f"not in store: {exc}"
            continue
        except Exception as exc:
            errors[sym] = f"{type(exc).__name__}: {exc}"
            continue
        snaps.append(snap)
    return snaps, errors


_OHLCV_LIBRARIES: frozenset[str] = frozenset(
    {"prices_daily", "crypto_daily", "fx_daily"}
)


def _frame_to_close_series(
    df: pd.DataFrame, library: str, symbol: str,
) -> pd.Series:
    """Coerce a stored frame into a price ``pd.Series`` for SnapshotStore.

    OHLCV / FX libraries pull the ``close`` column. Macro libraries
    pull ``value``. Identity / fundamentals are not freezable as price
    series and raise an explicit error.
    """
    if "timestamp" not in df.columns:
        raise ValueError(
            f"freeze_from_first_dataset: {library}/{symbol} has no "
            "'timestamp' column; not a freezable price series."
        )
    idx = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    idx = pd.DatetimeIndex(idx)
    # SnapshotStore expects naive UTC.
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    if library in _OHLCV_LIBRARIES:
        col = "close"
    elif library == "macro_daily":
        col = "value"
    else:
        raise ValueError(
            f"freeze_from_first_dataset: library {library!r} is not a "
            "price/value series; only prices_daily / crypto_daily / "
            "fx_daily / macro_daily are freezable."
        )
    if col not in df.columns:
        raise ValueError(
            f"freeze_from_first_dataset: {library}/{symbol} missing "
            f"column {col!r}."
        )
    series = pd.Series(
        pd.to_numeric(df[col], errors="coerce").values,
        index=idx,
        name=symbol,
    ).dropna()
    return series.sort_index()

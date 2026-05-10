"""R167 - Incremental data refresh, versioning and diff.

Compares two snapshots of the same logical dataset / symbol and reports:

* new rows (the date axis was extended)
* removed rows (a row went away unexpectedly)
* changed historical rows (a value at a previously-loaded date moved)
* changed metadata (provider, adjustment posture, content hash)

Designed to operate on small to medium frames in memory; large datasets
should pre-aggregate (per-symbol diffs) before calling.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RowDiff:
    """One historical row that changed value between two versions."""

    timestamp: str
    column: str
    old_value: float
    new_value: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SymbolDiff:
    """Diff between two snapshots of one symbol."""

    symbol: str
    old_version: str
    new_version: str
    new_rows: int
    removed_rows: int
    changed_rows: List[RowDiff] = field(default_factory=list)
    metadata_changes: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)
    content_hash_changed: bool = False
    old_content_hash: str = ""
    new_content_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "new_rows": self.new_rows,
            "removed_rows": self.removed_rows,
            "changed_rows": [r.to_dict() for r in self.changed_rows],
            "metadata_changes": {
                k: list(v) for k, v in self.metadata_changes.items()
            },
            "content_hash_changed": self.content_hash_changed,
            "old_content_hash": self.old_content_hash,
            "new_content_hash": self.new_content_hash,
        }

    @property
    def is_changed(self) -> bool:
        return (
            self.new_rows > 0
            or self.removed_rows > 0
            or bool(self.changed_rows)
            or self.content_hash_changed
            or bool(self.metadata_changes)
        )


@dataclass(frozen=True)
class DatasetDiffSummary:
    """Aggregate diff across multiple symbols."""

    symbols_added: List[str] = field(default_factory=list)
    symbols_removed: List[str] = field(default_factory=list)
    symbols_changed: List[str] = field(default_factory=list)
    symbols_unchanged: List[str] = field(default_factory=list)
    per_symbol: Dict[str, SymbolDiff] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbols_added": list(self.symbols_added),
            "symbols_removed": list(self.symbols_removed),
            "symbols_changed": list(self.symbols_changed),
            "symbols_unchanged": list(self.symbols_unchanged),
            "per_symbol": {k: v.to_dict() for k, v in self.per_symbol.items()},
        }


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def content_hash(df: pd.DataFrame) -> str:
    """Stable sha256 over the DataFrame's canonical bytes."""
    h = hashlib.sha256()
    for col in df.columns:
        h.update(str(col).encode("utf-8"))
        h.update(b"\x00")
    h.update(b"\xff")
    for col in df.columns:
        arr = np.ascontiguousarray(df[col].to_numpy(dtype=float), dtype="<f8")
        h.update(arr.tobytes())
        h.update(b"\x00")
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        idx_ns = np.ascontiguousarray(
            idx.values.astype("datetime64[ns]").view("int64"),
            dtype="<i8",
        )
        h.update(idx_ns.tobytes())
    else:
        h.update(repr(list(df.index)).encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Symbol diff
# ---------------------------------------------------------------------------


def diff_symbol(
    *,
    symbol: str,
    old: pd.DataFrame,
    new: pd.DataFrame,
    old_version: str = "old",
    new_version: str = "new",
    old_metadata: Optional[Mapping[str, Any]] = None,
    new_metadata: Optional[Mapping[str, Any]] = None,
    rtol: float = 1e-6,
    atol: float = 1e-9,
) -> SymbolDiff:
    """Diff two frames sharing a date index."""
    old_idx = pd.to_datetime(old.index)
    new_idx = pd.to_datetime(new.index)
    new_rows_idx = new_idx.difference(old_idx)
    removed_rows_idx = old_idx.difference(new_idx)
    common_idx = old_idx.intersection(new_idx)

    changed: List[RowDiff] = []
    if len(common_idx) > 0:
        old_common = old.loc[common_idx]
        new_common = new.loc[common_idx]
        shared_cols = [c for c in new_common.columns if c in old_common.columns]
        for col in shared_cols:
            o = old_common[col].to_numpy(dtype=float)
            n = new_common[col].to_numpy(dtype=float)
            mask = ~np.isclose(o, n, rtol=rtol, atol=atol, equal_nan=True)
            for ts, ov, nv in zip(common_idx[mask], o[mask], n[mask]):
                changed.append(RowDiff(
                    timestamp=pd.Timestamp(ts).isoformat(),
                    column=col,
                    old_value=float(ov),
                    new_value=float(nv),
                ))

    old_meta = dict(old_metadata or {})
    new_meta = dict(new_metadata or {})
    metadata_changes: Dict[str, Tuple[Any, Any]] = {}
    for key in sorted(set(old_meta) | set(new_meta)):
        if old_meta.get(key) != new_meta.get(key):
            metadata_changes[key] = (old_meta.get(key), new_meta.get(key))

    old_hash = content_hash(old) if not old.empty else ""
    new_hash = content_hash(new) if not new.empty else ""
    return SymbolDiff(
        symbol=symbol,
        old_version=old_version,
        new_version=new_version,
        new_rows=int(len(new_rows_idx)),
        removed_rows=int(len(removed_rows_idx)),
        changed_rows=changed,
        metadata_changes=metadata_changes,
        content_hash_changed=old_hash != new_hash,
        old_content_hash=old_hash,
        new_content_hash=new_hash,
    )


# ---------------------------------------------------------------------------
# Dataset diff
# ---------------------------------------------------------------------------


def diff_dataset(
    *,
    old_frames: Mapping[str, pd.DataFrame],
    new_frames: Mapping[str, pd.DataFrame],
    old_version: str = "old",
    new_version: str = "new",
    metadata_old: Optional[Mapping[str, Mapping[str, Any]]] = None,
    metadata_new: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> DatasetDiffSummary:
    """Compare two ``{symbol: frame}`` mappings."""
    old_syms = set(old_frames)
    new_syms = set(new_frames)
    added = sorted(new_syms - old_syms)
    removed = sorted(old_syms - new_syms)
    common = sorted(old_syms & new_syms)

    per_symbol: Dict[str, SymbolDiff] = {}
    changed: List[str] = []
    unchanged: List[str] = []
    for sym in common:
        old_meta = (metadata_old or {}).get(sym)
        new_meta = (metadata_new or {}).get(sym)
        d = diff_symbol(
            symbol=sym,
            old=old_frames[sym],
            new=new_frames[sym],
            old_version=old_version,
            new_version=new_version,
            old_metadata=old_meta,
            new_metadata=new_meta,
        )
        per_symbol[sym] = d
        if d.is_changed:
            changed.append(sym)
        else:
            unchanged.append(sym)

    return DatasetDiffSummary(
        symbols_added=added,
        symbols_removed=removed,
        symbols_changed=sorted(changed),
        symbols_unchanged=sorted(unchanged),
        per_symbol=per_symbol,
    )


# ---------------------------------------------------------------------------
# Stale-report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StaleArtefact:
    """One downstream artefact that depends on a changed symbol."""

    artefact_id: str
    artefact_kind: str
    affected_symbols: Tuple[str, ...]


def stale_artefact_report(
    diff: DatasetDiffSummary,
    artefact_dependencies: Mapping[str, Mapping[str, List[str]]],
) -> List[StaleArtefact]:
    """Return the artefacts whose inputs changed.

    ``artefact_dependencies`` maps ``artefact_kind -> {artefact_id: [symbols]}``.
    """
    changed_set = set(diff.symbols_changed) | set(diff.symbols_added) | set(
        diff.symbols_removed
    )
    out: List[StaleArtefact] = []
    for kind, mapping in artefact_dependencies.items():
        for artefact_id, symbols in mapping.items():
            affected = sorted(set(symbols) & changed_set)
            if affected:
                out.append(StaleArtefact(
                    artefact_id=artefact_id,
                    artefact_kind=kind,
                    affected_symbols=tuple(affected),
                ))
    out.sort(key=lambda s: (s.artefact_kind, s.artefact_id))
    return out


__all__ = [
    "DatasetDiffSummary",
    "RowDiff",
    "StaleArtefact",
    "SymbolDiff",
    "content_hash",
    "diff_dataset",
    "diff_symbol",
    "stale_artefact_report",
]

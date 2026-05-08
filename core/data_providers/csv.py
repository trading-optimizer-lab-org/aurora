"""CSV provider.

Loads a price series from a local CSV. The asof_date defaults to the
file's mtime. If a sidecar ``<file>.meta.json`` exists, its ``asof_date``
field is used instead -- this lets a researcher pin a specific PIT date
to a CSV that was published on a different day.

The provider's ``point_in_time`` flag is **opt-in** via the construction
kwarg ``point_in_time`` (default False, same conservative posture as
yfinance). Callers who curate CSVs from a PIT-correct source can flip
the flag to True at construction time.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Any, Optional

import pandas as pd

from . import BaseDataProvider, ProviderError


class CSVProvider(BaseDataProvider):
    """Local CSV provider with optional sidecar metadata.

    Construction kwargs:
        root_dir: Directory the provider searches when given a bare
            symbol. Defaults to the cwd.
        point_in_time: opt-in PIT flag (see module docstring).
        tier_permission: per-instance override of the default
            ``IS_TRAIN`` permission.

    Fetch kwargs:
        path: explicit path to the CSV. Takes precedence over ``symbol``.
        date_column: column name for the index. Defaults to "date".
        value_column: column name for the value. Defaults to "close".
    """

    name: str = "csv"
    version: str = "csv:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"

    def __init__(
        self,
        root_dir: Optional[str] = None,
        *,
        point_in_time: Optional[bool] = None,
        tier_permission: Optional[str] = None,
    ) -> None:
        self.root_dir = root_dir or os.getcwd()
        if point_in_time is not None:
            object.__setattr__(self, "point_in_time", bool(point_in_time))
        if tier_permission is not None:
            object.__setattr__(self, "tier_permission", tier_permission)

    def _resolve_path(self, symbol: str, kwargs: dict) -> str:
        path = kwargs.get("path")
        if path is not None:
            return str(path)
        # Try ``<root>/<symbol>.csv`` then ``<root>/<symbol>.parquet``-
        # adjacent .csv variants.
        candidate = os.path.join(self.root_dir, f"{symbol}.csv")
        if os.path.exists(candidate):
            return candidate
        raise ProviderError(
            f"csv provider: no file for {symbol!r} found at {candidate!r} "
            "and no explicit ``path`` kwarg given"
        )

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.Series:
        path = self._resolve_path(symbol, kwargs)
        date_col = kwargs.get("date_column", "date")
        value_col = kwargs.get("value_column", "close")
        df = pd.read_csv(path)
        # Case-insensitive fallback for the columns -- CSVs in the wild
        # often capitalize.
        cols_lower = {c.lower(): c for c in df.columns}
        if date_col not in df.columns:
            if date_col.lower() in cols_lower:
                date_col = cols_lower[date_col.lower()]
        if value_col not in df.columns:
            if value_col.lower() in cols_lower:
                value_col = cols_lower[value_col.lower()]
        if date_col not in df.columns or value_col not in df.columns:
            raise ProviderError(
                f"csv provider: missing columns {date_col!r} / {value_col!r} "
                f"in {path!r} (have {list(df.columns)})"
            )
        idx = pd.to_datetime(df[date_col])
        if idx.dt.tz is not None:
            idx = idx.dt.tz_convert("UTC").dt.tz_localize(None)
        s = pd.Series(df[value_col].astype(float).values, index=idx, name=symbol)
        s = s.dropna().sort_index()
        if start is not None:
            s = s[s.index >= start]
        if end is not None:
            s = s[s.index <= end]
        return s

    def fetch(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ):
        ds = super().fetch(symbol, start, end, **kwargs)
        # Override asof_date from sidecar metadata if present, so the
        # caller can pin a PIT date independent of the file's mtime.
        path = self._resolve_path(symbol, kwargs)
        sidecar = path + ".meta.json"
        if os.path.exists(sidecar):
            try:
                with open(sidecar, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if isinstance(meta, dict) and "asof_date" in meta:
                    asof = pd.Timestamp(meta["asof_date"])
                    new_meta = type(ds.metadata)(
                        name=ds.metadata.name,
                        source=ds.metadata.source,
                        source_version=ds.metadata.source_version,
                        asof_date=asof,
                        point_in_time=ds.metadata.point_in_time,
                        content_hash=ds.metadata.content_hash,
                        tier_permission=ds.metadata.tier_permission,
                        schema_version=ds.metadata.schema_version,
                        extra={**ds.metadata.extra, "csv_path": path,
                               "sidecar": sidecar},
                    )
                    return type(ds)(metadata=new_meta, data=ds.data)
            except Exception:
                # Sidecar read failure is non-fatal; we keep the file mtime
                # asof we stamped in BaseDataProvider.fetch.
                pass
        # No sidecar -> stamp file mtime as asof so callers see a real
        # PIT date instead of "now".
        try:
            mtime = os.path.getmtime(path)
            asof = pd.Timestamp(_dt.datetime.fromtimestamp(mtime, tz=_dt.timezone.utc).replace(tzinfo=None))
            new_meta = type(ds.metadata)(
                name=ds.metadata.name,
                source=ds.metadata.source,
                source_version=ds.metadata.source_version,
                asof_date=asof,
                point_in_time=ds.metadata.point_in_time,
                content_hash=ds.metadata.content_hash,
                tier_permission=ds.metadata.tier_permission,
                schema_version=ds.metadata.schema_version,
                extra={**ds.metadata.extra, "csv_path": path},
            )
            return type(ds)(metadata=new_meta, data=ds.data)
        except OSError:
            return ds

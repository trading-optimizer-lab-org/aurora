"""Year/symbol-partitioned parquet store.

Lazy ``pyarrow``. Falls back to a plain pandas-per-partition layout when
``pyarrow.dataset`` is unavailable so unit tests can run on a stripped
install. Layout on disk::

    root/
        year=2023/symbol=SPY/part-0000.parquet
        year=2024/symbol=SPY/part-0001.parquet
        year=2024/symbol=AAPL/part-0001.parquet
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class ParquetPartitionConfig:
    """Static config for :class:`PartitionedParquetStore`.

    Attributes:
        root: filesystem root directory.
        partition_cols: column names used as Hive-style partitions.
        timestamp_col: timestamp column used to derive ``year`` if missing.
    """
    root: str = "data_cache_qf/parquet_store"
    partition_cols: tuple[str, ...] = ("year", "symbol")
    timestamp_col: str = "timestamp"


class PartitionedParquetStore:
    """Write / read parquet partitioned by year + symbol."""

    def __init__(self, config: Optional[ParquetPartitionConfig] = None) -> None:
        self.config = config or ParquetPartitionConfig()
        os.makedirs(self.config.root, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def write(self, df: pd.DataFrame) -> int:
        """Append ``df`` partitioned by configured columns. Returns row count."""
        if df is None or df.empty:
            return 0
        df = self._ensure_year(df)
        missing = [c for c in self.config.partition_cols if c not in df.columns]
        if missing:
            raise ValueError(f"missing partition columns: {missing}")
        try:
            return self._write_pyarrow(df)
        except ImportError:
            return self._write_fallback(df)

    def read(
        self,
        symbol: Optional[str] = None,
        year: Optional[int] = None,
    ) -> pd.DataFrame:
        """Read a slice. ``symbol`` / ``year`` filters narrow the scan."""
        try:
            return self._read_pyarrow(symbol=symbol, year=year)
        except ImportError:
            return self._read_fallback(symbol=symbol, year=year)

    def list_partitions(self) -> list[dict]:
        """Enumerate all on-disk Hive-style partitions as dicts."""
        out: list[dict] = []
        root = self.config.root
        if not os.path.isdir(root):
            return out
        for dp, _, files in os.walk(root):
            if not any(f.endswith(".parquet") for f in files):
                continue
            rel = os.path.relpath(dp, root).replace(os.sep, "/")
            if rel == ".":
                continue
            parts = {}
            for seg in rel.split("/"):
                if "=" in seg:
                    k, v = seg.split("=", 1)
                    parts[k] = v
            if parts:
                out.append(parts)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _ensure_year(self, df: pd.DataFrame) -> pd.DataFrame:
        if "year" in df.columns:
            return df
        if self.config.timestamp_col not in df.columns:
            raise ValueError(
                f"need either 'year' column or '{self.config.timestamp_col}' "
                "to derive year"
            )
        df = df.copy()
        df["year"] = pd.to_datetime(df[self.config.timestamp_col]).dt.year.astype(int)
        return df

    def _write_pyarrow(self, df: pd.DataFrame) -> int:
        import pyarrow as pa
        import pyarrow.dataset as ds

        table = pa.Table.from_pandas(df, preserve_index=False)
        ds.write_dataset(
            table,
            base_dir=self.config.root,
            format="parquet",
            partitioning=list(self.config.partition_cols),
            partitioning_flavor="hive",
            existing_data_behavior="overwrite_or_ignore",
        )
        return int(len(df))

    def _read_pyarrow(self, symbol: Optional[str], year: Optional[int]) -> pd.DataFrame:
        import pyarrow.dataset as ds

        if not os.path.isdir(self.config.root) or not os.listdir(self.config.root):
            return pd.DataFrame()
        dataset = ds.dataset(
            self.config.root, format="parquet",
            partitioning="hive",
        )
        flt = None
        if symbol is not None:
            flt = ds.field("symbol") == symbol
        if year is not None:
            term = ds.field("year") == int(year)
            flt = term if flt is None else (flt & term)
        table = dataset.to_table(filter=flt)
        return table.to_pandas()

    def _write_fallback(self, df: pd.DataFrame) -> int:
        # Manual partitioned writes: one parquet per (year,symbol) group.
        n_total = 0
        group_cols = list(self.config.partition_cols)
        for keys, sub in df.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            parts = [f"{c}={v}" for c, v in zip(group_cols, keys)]
            target_dir = os.path.join(self.config.root, *parts)
            os.makedirs(target_dir, exist_ok=True)
            existing = [f for f in os.listdir(target_dir) if f.endswith(".parquet")]
            idx = len(existing)
            target = os.path.join(target_dir, f"part-{idx:04d}.parquet")
            sub.drop(columns=group_cols, errors="ignore").to_parquet(target, index=False)
            n_total += len(sub)
        return int(n_total)

    def _read_fallback(self, symbol: Optional[str], year: Optional[int]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        if not os.path.isdir(self.config.root):
            return pd.DataFrame()
        for dp, _, files in os.walk(self.config.root):
            parquet_files = [f for f in files if f.endswith(".parquet")]
            if not parquet_files:
                continue
            rel = os.path.relpath(dp, self.config.root).replace(os.sep, "/")
            parts: dict[str, str] = {}
            for seg in rel.split("/"):
                if "=" in seg:
                    k, v = seg.split("=", 1)
                    parts[k] = v
            if symbol is not None and parts.get("symbol") != symbol:
                continue
            if year is not None and str(parts.get("year")) != str(int(year)):
                continue
            for f in parquet_files:
                frame = pd.read_parquet(os.path.join(dp, f))
                for k, v in parts.items():
                    if k not in frame.columns:
                        # restore partition column with its original dtype.
                        if k == "year":
                            frame[k] = int(v)
                        else:
                            frame[k] = v
                frames.append(frame)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

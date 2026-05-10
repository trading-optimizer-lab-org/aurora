"""TimescaleDB hypertable adapter for tick / bar ingestion.

Lazy ``psycopg2``. The default ``mock=True`` mode keeps an in-memory
DataFrame so tests run offline. Real ingestion happens only when a DSN
is provided and ``mock=False``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class TimescaleConfig:
    """Static config for :class:`TimescaleAdapter`.

    Attributes:
        dsn: connection string. Falls back to env var.
        dsn_env: env var name to read DSN from.
        schema: target schema name.
        ticks_table: table holding raw tick rows.
        bars_table: table holding aggregated bar rows.
        chunk_time_interval: hypertable chunk size (e.g. ``"1 day"``).
    """
    dsn: str = ""
    dsn_env: str = "QUANTFORGE_TIMESCALE_DSN"
    schema: str = "public"
    ticks_table: str = "ticks"
    bars_table: str = "bars"
    chunk_time_interval: str = "1 day"


_TICK_COLS = ("timestamp", "symbol", "price", "size")
_BAR_COLS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")


class TimescaleAdapter:
    """Hypertable manager + tick / bar inserter."""

    DDL_TICKS = (
        "CREATE TABLE IF NOT EXISTS {schema}.{table} ("
        " timestamp TIMESTAMPTZ NOT NULL,"
        " symbol TEXT NOT NULL,"
        " price DOUBLE PRECISION NOT NULL,"
        " size DOUBLE PRECISION NOT NULL"
        ")"
    )
    DDL_BARS = (
        "CREATE TABLE IF NOT EXISTS {schema}.{table} ("
        " timestamp TIMESTAMPTZ NOT NULL,"
        " symbol TEXT NOT NULL,"
        " open DOUBLE PRECISION NOT NULL,"
        " high DOUBLE PRECISION NOT NULL,"
        " low DOUBLE PRECISION NOT NULL,"
        " close DOUBLE PRECISION NOT NULL,"
        " volume DOUBLE PRECISION NOT NULL"
        ")"
    )

    def __init__(self, config: Optional[TimescaleConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or TimescaleConfig()
        self.mock = bool(mock)
        # In-memory ticks / bars frames for mock mode.
        self._ticks = pd.DataFrame(columns=list(_TICK_COLS))
        self._bars = pd.DataFrame(columns=list(_BAR_COLS))
        if not self.mock:  # pragma: no cover - real DB path
            self._init_hypertables()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest_ticks(self, df: pd.DataFrame) -> int:
        """Append ticks. Returns row count inserted."""
        if df is None or df.empty:
            return 0
        missing = [c for c in _TICK_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"missing tick columns: {missing}")
        df = df[list(_TICK_COLS)].copy()
        if self.mock:
            self._ticks = pd.concat([self._ticks, df], ignore_index=True)
            return int(len(df))
        return self._db_copy(self.config.ticks_table, df)  # pragma: no cover

    def ingest_bars(self, df: pd.DataFrame) -> int:
        """Append OHLCV bars. Returns row count inserted."""
        if df is None or df.empty:
            return 0
        missing = [c for c in _BAR_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"missing bar columns: {missing}")
        df = df[list(_BAR_COLS)].copy()
        if self.mock:
            self._bars = pd.concat([self._bars, df], ignore_index=True)
            return int(len(df))
        return self._db_copy(self.config.bars_table, df)  # pragma: no cover

    def query_ticks(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return ticks for ``symbol`` in ``[start, end)``."""
        if self.mock:
            df = self._ticks
            mask = df["symbol"] == symbol
            if start is not None:
                mask &= pd.to_datetime(df["timestamp"]) >= pd.to_datetime(start)
            if end is not None:
                mask &= pd.to_datetime(df["timestamp"]) < pd.to_datetime(end)
            return df.loc[mask].sort_values("timestamp").reset_index(drop=True)
        return self._db_query(self.config.ticks_table, symbol, start, end)  # pragma: no cover

    def query_bars(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return bars for ``symbol`` in ``[start, end)``."""
        if self.mock:
            df = self._bars
            mask = df["symbol"] == symbol
            if start is not None:
                mask &= pd.to_datetime(df["timestamp"]) >= pd.to_datetime(start)
            if end is not None:
                mask &= pd.to_datetime(df["timestamp"]) < pd.to_datetime(end)
            return df.loc[mask].sort_values("timestamp").reset_index(drop=True)
        return self._db_query(self.config.bars_table, symbol, start, end)  # pragma: no cover

    def aggregate_to_bars(
        self,
        symbol: str,
        freq: str = "1min",
    ) -> pd.DataFrame:
        """Aggregate ticks to OHLCV bars of ``freq`` (mock-only helper)."""
        ticks = self.query_ticks(symbol)
        if ticks.empty:
            return pd.DataFrame(columns=list(_BAR_COLS))
        ticks = ticks.copy()
        ticks["timestamp"] = pd.to_datetime(ticks["timestamp"])
        # Mock storage may upcast numeric columns to object after pd.concat
        # with empty seed frames; coerce back to float so resample.ohlc()
        # can aggregate.
        ticks["price"] = pd.to_numeric(ticks["price"], errors="coerce")
        ticks["size"] = pd.to_numeric(ticks["size"], errors="coerce")
        ticks = ticks.set_index("timestamp")
        agg = ticks["price"].resample(freq).ohlc()
        vol = ticks["size"].resample(freq).sum().rename("volume")
        out = agg.join(vol).dropna(subset=["open"]).reset_index()
        out["symbol"] = symbol
        return out[list(_BAR_COLS)]

    # ------------------------------------------------------------------
    # Internals (real DB paths excluded from coverage)
    # ------------------------------------------------------------------
    def _resolve_dsn(self) -> str:
        return self.config.dsn or os.environ.get(self.config.dsn_env, "")

    def _connect(self):  # pragma: no cover - real DB path
        try:
            import psycopg2
        except ImportError as e:
            raise ImportError("psycopg2 required for TimescaleAdapter mock=False") from e
        dsn = self._resolve_dsn()
        if not dsn:
            raise RuntimeError(
                f"missing DSN; set config.dsn or env {self.config.dsn_env}"
            )
        return psycopg2.connect(dsn)

    def _init_hypertables(self) -> None:  # pragma: no cover - real DB path
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(self.DDL_TICKS.format(
                    schema=self.config.schema, table=self.config.ticks_table,
                ))
                cur.execute(self.DDL_BARS.format(
                    schema=self.config.schema, table=self.config.bars_table,
                ))
                # idempotent: create_hypertable with if_not_exists.
                for tbl in (self.config.ticks_table, self.config.bars_table):
                    cur.execute(
                        "SELECT create_hypertable(%s, 'timestamp',"
                        " if_not_exists => TRUE,"
                        " chunk_time_interval => INTERVAL %s)",
                        (f"{self.config.schema}.{tbl}",
                         self.config.chunk_time_interval),
                    )

    def _db_copy(self, table: str, df: pd.DataFrame) -> int:  # pragma: no cover
        cols = list(df.columns)
        placeholders = ", ".join(["%s"] * len(cols))
        col_list = ", ".join(cols)
        sql = (f"INSERT INTO {self.config.schema}.{table} ({col_list}) "
               f"VALUES ({placeholders})")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, [tuple(r) for r in df.itertuples(index=False)])
                return int(cur.rowcount)

    def _db_query(self, table: str, symbol: str,
                  start: Optional[str], end: Optional[str]) -> pd.DataFrame:  # pragma: no cover
        clauses = ["symbol = %s"]
        params: list = [symbol]
        if start is not None:
            clauses.append("timestamp >= %s")
            params.append(start)
        if end is not None:
            clauses.append("timestamp < %s")
            params.append(end)
        where = " AND ".join(clauses)
        sql = (f"SELECT * FROM {self.config.schema}.{table} "
               f"WHERE {where} ORDER BY timestamp ASC")
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=tuple(params))

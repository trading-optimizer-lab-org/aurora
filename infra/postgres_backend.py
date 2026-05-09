"""Postgres-backed registry / journal drop-in.

Mirrors the SQLite-based :class:`quantforge.registry.registry.BacktestRegistry`
API but persists to Postgres via lazy ``psycopg2``. The same dataclass
:class:`~quantforge.registry.registry.RegistryEntry` is reused, so callers
swap implementations without touching downstream code.

Two modes:

- ``mock=True`` (default): keep state in an in-memory list. Used by tests
  and offline development; no real database needed.
- ``mock=False``: connect to Postgres via ``dsn`` and execute SQL. Lazy
  import of ``psycopg2`` happens only on the first DB call.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from aurora.registry.registry import RegistryEntry


@dataclass
class PostgresConfig:
    """Static config for :class:`PostgresRegistry`.

    Attributes:
        dsn: connection string (``postgresql://user:pw@host:5432/db``).
            Read from env if empty.
        dsn_env: env var to pull DSN from when ``dsn`` is empty.
        schema: schema name (defaults to ``public``).
        table: registry table name.
    """
    dsn: str = ""
    dsn_env: str = "QUANTFORGE_PG_DSN"
    schema: str = "public"
    table: str = "backtests"


def _canonical_params(params: dict) -> str:
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)


def _hash_config(strategy_class: str, params: dict, asset: str,
                 period_start: str, period_end: str) -> str:
    payload = "|".join([
        str(strategy_class),
        _canonical_params(params),
        str(asset),
        str(period_start),
        str(period_end),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PostgresRegistry:
    """Postgres registry with the same surface as ``BacktestRegistry``."""

    SCHEMA_DDL = (
        "CREATE TABLE IF NOT EXISTS {schema}.{table} ("
        " id BIGSERIAL PRIMARY KEY,"
        " strategy_class TEXT NOT NULL,"
        " strategy_params JSONB NOT NULL,"
        " asset TEXT NOT NULL,"
        " period_start TEXT NOT NULL,"
        " period_end TEXT NOT NULL,"
        " metrics JSONB NOT NULL,"
        " timestamp TIMESTAMPTZ NOT NULL,"
        " git_hash TEXT,"
        " config_hash TEXT NOT NULL UNIQUE,"
        " tags JSONB NOT NULL DEFAULT '[]'::jsonb"
        ")"
    )

    def __init__(self, config: Optional[PostgresConfig] = None,
                 mock: bool = True) -> None:
        self.config = config or PostgresConfig()
        self.mock = bool(mock)
        # Mock mode: in-memory rows keyed by config_hash for dedup.
        self._rows: dict[str, dict] = {}
        self._next_id: int = 1
        if not self.mock:  # pragma: no cover - real DB path
            self._init_schema()

    # ------------------------------------------------------------------
    # Public API (mirrors BacktestRegistry)
    # ------------------------------------------------------------------
    def store(self, strategy_class: str, strategy_params: dict, asset: str,
              period_start: str, period_end: str, metrics: dict,
              tags: Optional[list] = None) -> int:
        cfg_hash = _hash_config(strategy_class, strategy_params, asset,
                                period_start, period_end)
        ts = _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")
        tags = list(tags or [])
        if self.mock:
            existing = self._rows.get(cfg_hash)
            if existing is not None:
                return int(existing["id"])
            row = {
                "id": self._next_id,
                "strategy_class": strategy_class,
                "strategy_params": dict(strategy_params or {}),
                "asset": asset,
                "period_start": period_start,
                "period_end": period_end,
                "metrics": dict(metrics or {}),
                "timestamp": ts,
                "git_hash": None,
                "config_hash": cfg_hash,
                "tags": list(tags),
            }
            self._rows[cfg_hash] = row
            self._next_id += 1
            return int(row["id"])
        return self._db_store(strategy_class, strategy_params, asset,
                              period_start, period_end, metrics, tags,
                              cfg_hash, ts)

    def get(self, entry_id: int) -> Optional[RegistryEntry]:
        if self.mock:
            for row in self._rows.values():
                if int(row["id"]) == int(entry_id):
                    return self._row_to_entry(row)
            return None
        return self._db_get(entry_id)  # pragma: no cover - real DB path

    def query(self, strategy_class: Optional[str] = None,
              asset: Optional[str] = None,
              tags: Optional[list] = None,
              limit: int = 100) -> list[RegistryEntry]:
        if self.mock:
            out = []
            for row in self._rows.values():
                if strategy_class is not None and row["strategy_class"] != strategy_class:
                    continue
                if asset is not None and row["asset"] != asset:
                    continue
                if tags:
                    have = set(row.get("tags") or [])
                    if not all(t in have for t in tags):
                        continue
                out.append(row)
            out.sort(key=lambda r: r["timestamp"], reverse=True)
            return [self._row_to_entry(r) for r in out[:int(limit)]]
        return self._db_query(strategy_class, asset, tags, limit)  # pragma: no cover

    def count(self) -> int:
        if self.mock:
            return len(self._rows)
        return self._db_count()  # pragma: no cover - real DB path

    def delete(self, entry_id: int) -> bool:
        if self.mock:
            for cfg, row in list(self._rows.items()):
                if int(row["id"]) == int(entry_id):
                    del self._rows[cfg]
                    return True
            return False
        return self._db_delete(entry_id)  # pragma: no cover - real DB path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _row_to_entry(self, row: dict) -> RegistryEntry:
        return RegistryEntry(
            id=int(row["id"]),
            strategy_class=str(row["strategy_class"]),
            strategy_params=dict(row.get("strategy_params") or {}),
            asset=str(row["asset"]),
            period_start=str(row["period_start"]),
            period_end=str(row["period_end"]),
            metrics=dict(row.get("metrics") or {}),
            timestamp=str(row["timestamp"]),
            git_hash=row.get("git_hash"),
            config_hash=str(row["config_hash"]),
            tags=list(row.get("tags") or []),
        )

    def _resolve_dsn(self) -> str:
        if self.config.dsn:
            return self.config.dsn
        return os.environ.get(self.config.dsn_env, "")

    # --- real DB I/O paths (no test coverage by design) ---

    def _connect(self):  # pragma: no cover - real DB path
        try:
            import psycopg2  # type: ignore
        except ImportError as e:
            raise ImportError("psycopg2 required for PostgresRegistry mock=False") from e
        dsn = self._resolve_dsn()
        if not dsn:
            raise RuntimeError(
                f"missing DSN; set config.dsn or env {self.config.dsn_env}"
            )
        return psycopg2.connect(dsn)

    def _init_schema(self) -> None:  # pragma: no cover - real DB path
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(self.SCHEMA_DDL.format(
                    schema=self.config.schema, table=self.config.table,
                ))

    def _db_store(self, strategy_class: str, strategy_params: dict, asset: str,
                  period_start: str, period_end: str, metrics: dict,
                  tags: list, cfg_hash: str, ts: str) -> int:  # pragma: no cover
        sql = (
            f"INSERT INTO {self.config.schema}.{self.config.table} "
            "(strategy_class, strategy_params, asset, period_start, period_end,"
            " metrics, timestamp, config_hash, tags) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (config_hash) DO UPDATE SET config_hash=EXCLUDED.config_hash "
            "RETURNING id"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    strategy_class, json.dumps(strategy_params or {}),
                    asset, period_start, period_end,
                    json.dumps(metrics or {}), ts, cfg_hash,
                    json.dumps(tags),
                ))
                row = cur.fetchone()
                return int(row[0])

    def _db_get(self, entry_id: int) -> Optional[RegistryEntry]:  # pragma: no cover
        sql = f"SELECT * FROM {self.config.schema}.{self.config.table} WHERE id = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (entry_id,))
                row = cur.fetchone()
                return self._row_to_entry(self._tuple_to_row(cur, row)) if row else None

    def _db_query(self, strategy_class: Optional[str], asset: Optional[str],
                  tags: Optional[list], limit: int) -> list[RegistryEntry]:  # pragma: no cover
        clauses, params = [], []
        if strategy_class is not None:
            clauses.append("strategy_class = %s")
            params.append(strategy_class)
        if asset is not None:
            clauses.append("asset = %s")
            params.append(asset)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (f"SELECT * FROM {self.config.schema}.{self.config.table} {where} "
               "ORDER BY timestamp DESC LIMIT %s")
        params.append(int(limit))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                return [self._row_to_entry(self._tuple_to_row(cur, r)) for r in rows]

    def _db_count(self) -> int:  # pragma: no cover
        sql = f"SELECT COUNT(*) FROM {self.config.schema}.{self.config.table}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return int(cur.fetchone()[0])

    def _db_delete(self, entry_id: int) -> bool:  # pragma: no cover
        sql = f"DELETE FROM {self.config.schema}.{self.config.table} WHERE id = %s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (entry_id,))
                return cur.rowcount > 0

    @staticmethod
    def _tuple_to_row(cursor, tup) -> dict:  # pragma: no cover - real DB path
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, tup))

"""SQLite registry for backtest results.

Stdlib sqlite3 only. JSON-encoded dicts/lists. Dedup via UNIQUE config_hash.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import pandas as pd

from aurora.core.sqlite_utils import _setup_sqlite


_DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data_cache_qf", "registry.db")
)

# Whitelist of metric names allowed in BacktestRegistry.best_by(metric=...)
# (interpolated into a json_extract path, so a strict whitelist closes the
# door on string-injection-flavored mischief while keeping the signature
# friendly).
_ALLOWED_BEST_BY_METRICS: frozenset[str] = frozenset(
    {"calmar", "sharpe", "mdd", "cagr", "sortino"}
)


@dataclass
class RegistryEntry:
    id: int
    strategy_class: str
    strategy_params: dict
    asset: str
    period_start: str
    period_end: str
    metrics: dict
    timestamp: str
    git_hash: Optional[str]
    config_hash: str
    tags: list = field(default_factory=list)


# ---------- helpers ----------

def _canonical_params(params: dict) -> str:
    """Canonical JSON of params: keys sorted, no whitespace, deterministic."""
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)


def hash_config(strategy_class: str, params: dict, asset: str,
                period_start: str, period_end: str) -> str:
    """SHA256 hex digest of canonical (class | params | asset | period)."""
    payload = "|".join([
        str(strategy_class),
        _canonical_params(params),
        str(asset),
        str(period_start),
        str(period_end),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _capture_git_hash() -> Optional[str]:
    """Best-effort HEAD hash. None on any failure.

    Uses :func:`aurora.registry.versioning._run_git_proc` (Popen +
    explicit terminate/kill) instead of ``subprocess.run`` so a hung
    ``git.exe`` on Windows does not orphan a zombie process — the
    standard library's ``run(..., timeout=...)`` raises ``TimeoutExpired``
    but does not always reap the child cleanly on Windows.
    """
    try:
        from aurora.registry.versioning import _run_git_proc
        rc, out = _run_git_proc(["rev-parse", "HEAD"], timeout=2.0)
    except Exception:
        return None
    if rc is None or rc != 0:
        return None
    h = out.strip()
    return h or None


def _row_to_entry(row: sqlite3.Row) -> RegistryEntry:
    return RegistryEntry(
        id=row["id"],
        strategy_class=row["strategy_class"],
        strategy_params=json.loads(row["strategy_params"] or "{}"),
        asset=row["asset"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        metrics=json.loads(row["metrics"] or "{}"),
        timestamp=row["timestamp"],
        git_hash=row["git_hash"],
        config_hash=row["config_hash"],
        tags=json.loads(row["tags"] or "[]"),
    )


# ---------- registry ----------

class BacktestRegistry:
    """SQLite-backed registry for storing + querying backtest results.

    Schema:
        id INTEGER PRIMARY KEY
        strategy_class TEXT
        strategy_params TEXT (JSON)
        asset TEXT
        period_start TEXT
        period_end TEXT
        metrics TEXT (JSON)
        timestamp TEXT (ISO)
        git_hash TEXT
        config_hash TEXT (UNIQUE - dedup)
        tags TEXT (JSON list)
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS backtests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_class TEXT NOT NULL,
            strategy_params TEXT NOT NULL,
            asset TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            metrics TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            git_hash TEXT,
            config_hash TEXT NOT NULL UNIQUE,
            tags TEXT NOT NULL DEFAULT '[]'
        )
    """

    INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_strategy_class ON backtests(strategy_class)",
        "CREATE INDEX IF NOT EXISTS idx_asset ON backtests(asset)",
        "CREATE INDEX IF NOT EXISTS idx_timestamp ON backtests(timestamp DESC)",
    ]

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    # --- connection ---

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Open a connection in autocommit mode.

        Autocommit (``isolation_level=None``) disables Python's implicit
        transaction wrapping, so callers can issue ``BEGIN IMMEDIATE``
        explicitly without sqlite3's auto-begin layering a second
        ``BEGIN`` on top and raising ``OperationalError: cannot start a
        transaction within a transaction``. ``store()`` controls its own
        transaction with explicit ``BEGIN IMMEDIATE`` / ``COMMIT`` /
        ``ROLLBACK``; read-only callers fall back to autocommit reads
        which is fine for SELECT-only paths.
        """
        conn = sqlite3.connect(self.db_path)
        conn.isolation_level = None
        _setup_sqlite(conn, mode="normal")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.execute(self.SCHEMA)
            for stmt in self.INDEXES:
                c.execute(stmt)

    # --- write ---

    def store(self, strategy_class: str, strategy_params: dict, asset: str,
              period_start: str, period_end: str, metrics: dict,
              tags: Optional[list] = None) -> int:
        """Store result. Returns ID of stored or existing row.

        Dedup: if a row with same config_hash already exists, returns its ID
        without inserting (INSERT OR IGNORE).
        """
        cfg_hash = hash_config(strategy_class, strategy_params, asset,
                               period_start, period_end)
        ts = _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")
        git_hash = _capture_git_hash()
        tags = list(tags or [])

        with self._conn() as c:
            # BEGIN IMMEDIATE acquires a RESERVED lock immediately, so the
            # INSERT OR IGNORE + follow-up SELECT below run as a single
            # writer-serialized critical section. Without this, two writers
            # racing the same config_hash can both observe ``rowcount == 0``
            # and then both read inconsistent ids during the SELECT.
            #
            # The connection runs in autocommit mode (isolation_level=None)
            # so ``BEGIN IMMEDIATE`` is the explicit transaction start and
            # the matching ``COMMIT`` / ``ROLLBACK`` ends it.
            c.execute("BEGIN IMMEDIATE")
            try:
                cur = c.execute(
                    """
                    INSERT OR IGNORE INTO backtests
                        (strategy_class, strategy_params, asset, period_start,
                         period_end, metrics, timestamp, git_hash, config_hash, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        strategy_class,
                        _canonical_params(strategy_params),
                        asset,
                        period_start,
                        period_end,
                        json.dumps(metrics or {}, default=str),
                        ts,
                        git_hash,
                        cfg_hash,
                        json.dumps(tags),
                    ),
                )
                # If rowcount == 0 the row was a duplicate and lastrowid is
                # stale (sqlite returns the previous insert's rowid). Always
                # look up by config_hash on duplicates, only trust lastrowid
                # on fresh inserts.
                if cur.rowcount == 0:
                    row = c.execute(
                        "SELECT id FROM backtests WHERE config_hash = ?",
                        (cfg_hash,),
                    ).fetchone()
                    if row is None:  # pragma: no cover - defensive
                        raise RuntimeError(
                            f"INSERT OR IGNORE skipped row but no existing row "
                            f"matches config_hash={cfg_hash!r}"
                        )
                    result_id = int(row["id"])
                else:
                    last_id = cur.lastrowid
                    if last_id is None:  # pragma: no cover - defensive
                        raise RuntimeError(
                            "sqlite cursor.lastrowid is None after fresh INSERT"
                        )
                    result_id = int(last_id)
            except Exception:
                c.execute("ROLLBACK")
                raise
            c.execute("COMMIT")
            return result_id

    # --- read ---

    def get(self, entry_id: int) -> Optional[RegistryEntry]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM backtests WHERE id = ?", (entry_id,)
            ).fetchone()
            return _row_to_entry(row) if row else None

    def query(self, strategy_class: Optional[str] = None,
              asset: Optional[str] = None,
              min_calmar: Optional[float] = None,
              min_sharpe: Optional[float] = None,
              max_mdd: Optional[float] = None,
              tags: Optional[list] = None,
              limit: int = 100) -> list:
        """Filter by criteria. Returns matches sorted by timestamp desc.

        Notes:
        - min_calmar / min_sharpe / max_mdd compare against JSON-extracted
          metric fields. max_mdd is treated as 'mdd >= max_mdd' since mdd is
          stored as a non-positive number (closer to 0 is better).
        - tags filter requires ALL given tags to be present in row.tags.
        """
        clauses: list = []
        params: list[Any] = []

        if strategy_class is not None:
            clauses.append("strategy_class = ?")
            params.append(strategy_class)
        if asset is not None:
            clauses.append("asset = ?")
            params.append(asset)
        # json_extract returns NULL for missing keys; non-numeric (string)
        # values cast to 0.0 under SQLite's CAST AS REAL. Both cases would
        # silently match the comparison. Filter out NULL values explicitly
        # and require json_type to be a number to keep the result correct.
        if min_calmar is not None:
            clauses.append(
                "json_extract(metrics, '$.calmar') IS NOT NULL "
                "AND json_type(metrics, '$.calmar') IN ('integer', 'real') "
                "AND CAST(json_extract(metrics, '$.calmar') AS REAL) >= ?"
            )
            params.append(float(min_calmar))
        if min_sharpe is not None:
            clauses.append(
                "json_extract(metrics, '$.sharpe') IS NOT NULL "
                "AND json_type(metrics, '$.sharpe') IN ('integer', 'real') "
                "AND CAST(json_extract(metrics, '$.sharpe') AS REAL) >= ?"
            )
            params.append(float(min_sharpe))
        if max_mdd is not None:
            # mdd values are non-positive; max_mdd is the floor (i.e., not worse than this).
            clauses.append(
                "json_extract(metrics, '$.mdd') IS NOT NULL "
                "AND json_type(metrics, '$.mdd') IN ('integer', 'real') "
                "AND CAST(json_extract(metrics, '$.mdd') AS REAL) >= ?"
            )
            params.append(float(max_mdd))

        # Push the tag filter into SQL via ``json_each`` so it composes
        # with LIMIT correctly. Previously ``tags`` was applied in Python
        # AFTER the SQL ``LIMIT`` had already truncated the result set,
        # which silently returned fewer rows than ``limit`` (or zero) when
        # the LIMIT cut excluded all tag-matching rows. AND semantics
        # across the requested tags is enforced by counting distinct
        # matches and requiring the count to equal ``len(tags)``.
        if tags:
            req = list(dict.fromkeys(str(t) for t in tags))  # dedup, keep order
            placeholders = ",".join("?" for _ in req)
            clauses.append(
                f"(SELECT COUNT(DISTINCT je.value) "
                f"FROM json_each(backtests.tags) je "
                f"WHERE je.value IN ({placeholders})) = ?"
            )
            params.extend(req)
            params.append(len(req))

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM backtests {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(int(limit))

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()

        return [_row_to_entry(r) for r in rows]

    def best_by(self, metric: str = "calmar", n: int = 10,
                strategy_class: Optional[str] = None,
                asset: Optional[str] = None) -> list:
        """Top N by given metric (descending)."""
        clauses: list = []
        params: list[Any] = []
        if strategy_class is not None:
            clauses.append("strategy_class = ?")
            params.append(strategy_class)
        if asset is not None:
            clauses.append("asset = ?")
            params.append(asset)

        # safe: 'metric' is interpolated into the json_extract path. Restrict
        # to a known whitelist instead of the looser alphanumeric check; if a
        # caller wants a new metric name they should add it here explicitly.
        if metric not in _ALLOWED_BEST_BY_METRICS:
            raise ValueError(
                f"invalid metric name: {metric!r}; "
                f"allowed: {sorted(_ALLOWED_BEST_BY_METRICS)}"
            )

        # Filter out rows where the metric is null or non-numeric so they
        # don't sort to the top (NULL sorts last DESC, but we still want
        # to drop string/non-numeric values).
        type_clause = (
            f"json_extract(metrics, '$.{metric}') IS NOT NULL "
            f"AND json_type(metrics, '$.{metric}') IN ('integer', 'real')"
        )
        clauses.append(type_clause)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order_expr = f"CAST(json_extract(metrics, '$.{metric}') AS REAL)"
        sql = (
            f"SELECT * FROM backtests {where} "
            f"ORDER BY {order_expr} DESC LIMIT ?"
        )
        params.append(int(n))

        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_entry(r) for r in rows]

    def delete(self, entry_id: int) -> bool:
        # Autocommit mode: each statement commits immediately, so no
        # explicit BEGIN/COMMIT pair needed for a single DELETE.
        with self._conn() as c:
            cur = c.execute("DELETE FROM backtests WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    def count(self) -> int:
        with self._conn() as c:
            row = c.execute("SELECT COUNT(*) AS n FROM backtests").fetchone()
            return int(row["n"]) if row else 0

    def to_dataframe(self) -> pd.DataFrame:
        """All entries as DataFrame. JSON columns are decoded to Python objects."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM backtests ORDER BY timestamp DESC"
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=[
                "id", "strategy_class", "strategy_params", "asset",
                "period_start", "period_end", "metrics", "timestamp",
                "git_hash", "config_hash", "tags",
            ])
        records = []
        for r in rows:
            e = _row_to_entry(r)
            records.append({
                "id": e.id,
                "strategy_class": e.strategy_class,
                "strategy_params": e.strategy_params,
                "asset": e.asset,
                "period_start": e.period_start,
                "period_end": e.period_end,
                "metrics": e.metrics,
                "timestamp": e.timestamp,
                "git_hash": e.git_hash,
                "config_hash": e.config_hash,
                "tags": e.tags,
            })
        return pd.DataFrame.from_records(records)


# ---------- convenience ----------

def store_backtest_result(result: Any, strategy_class: str,
                          strategy_params: dict, asset: str,
                          registry_path: Optional[str] = None,
                          tags: Optional[list] = None) -> int:
    """Store from a BacktestResult. Pulls metrics + period from result.

    Args:
        result: BacktestResult-like with .metrics.to_dict() and .timestamps
        strategy_class: name of strategy class
        strategy_params: dict of params (JSON-encoded for storage)
        asset: e.g. "SPY"
        registry_path: optional path override (defaults to project default)
        tags: optional list of tags

    Returns:
        ID of stored row.
    """
    metrics_obj = result.metrics
    metrics = metrics_obj.to_dict() if hasattr(metrics_obj, "to_dict") else dict(metrics_obj)

    ts = result.timestamps
    if len(ts) == 0:
        period_start = period_end = ""
    else:
        period_start = pd.Timestamp(ts[0]).strftime("%Y-%m-%d")
        period_end = pd.Timestamp(ts[-1]).strftime("%Y-%m-%d")

    reg = BacktestRegistry(db_path=registry_path) if registry_path else BacktestRegistry()
    return reg.store(
        strategy_class=strategy_class,
        strategy_params=strategy_params,
        asset=asset,
        period_start=period_start,
        period_end=period_end,
        metrics=metrics,
        tags=tags,
    )

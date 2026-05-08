"""Strategy Marketplace skeleton.

Stores strategy specs in a SQLite-backed registry so multiple users can
publish, discover, and retrieve strategies. The marketplace stores only
*specifications* (a name + JSON-serializable params + JSON metadata),
not executable code -- that responsibility lives with the user, who must
already have the named Strategy class on their PYTHONPATH.

Schema:

    CREATE TABLE strategies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author TEXT NOT NULL,
        name TEXT NOT NULL,
        family TEXT NOT NULL DEFAULT 'misc',
        description TEXT NOT NULL DEFAULT '',
        params_json TEXT NOT NULL DEFAULT '{}',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        published_at TEXT NOT NULL,
        UNIQUE(author, name)
    );

Operations:
    register(author, name, family, description, params, metadata)
    discover(family=None, author=None, name_contains=None) -> list
    get(author, name) -> MarketplaceStrategy
    delete(author, name) -- requires explicit author for ownership safety

This is a skeleton. Trust, signatures, payment etc are out of scope.
"""
from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author TEXT NOT NULL,
    name TEXT NOT NULL,
    family TEXT NOT NULL DEFAULT 'misc',
    description TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    published_at TEXT NOT NULL,
    UNIQUE(author, name)
);
"""


@dataclass
class MarketplaceStrategy:
    author: str
    name: str
    family: str
    description: str
    params: dict[str, Any]
    metadata: dict[str, Any]
    published_at: str


class StrategyMarketplace:
    """SQLite-backed registry for shareable strategy specs."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- mutation -----------------------------------------------------------

    def register(self, author: str, name: str, family: str = "misc",
                 description: str = "",
                 params: dict[str, Any] | None = None,
                 metadata: dict[str, Any] | None = None
                 ) -> MarketplaceStrategy:
        if not author or not name:
            raise ValueError("author and name must be non-empty")
        params = params or {}
        metadata = metadata or {}
        try:
            params_json = json.dumps(params, sort_keys=True)
            metadata_json = json.dumps(metadata, sort_keys=True)
        except TypeError as e:
            raise ValueError(f"params/metadata must be JSON serializable: {e}") from e
        ts = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "INSERT INTO strategies (author, name, family, description, "
                "params_json, metadata_json, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (author, name, family, description, params_json, metadata_json, ts),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(
                f"strategy {name!r} by {author!r} already registered"
            ) from e
        return MarketplaceStrategy(
            author=author, name=name, family=family, description=description,
            params=params, metadata=metadata, published_at=ts,
        )

    def delete(self, author: str, name: str) -> bool:
        """Remove a strategy. Returns True if deleted, False if not found."""
        cur = self._conn.execute(
            "DELETE FROM strategies WHERE author = ? AND name = ?",
            (author, name),
        )
        self._conn.commit()
        return cur.rowcount > 0

    # -- queries ------------------------------------------------------------

    def get(self, author: str, name: str) -> MarketplaceStrategy | None:
        cur = self._conn.execute(
            "SELECT * FROM strategies WHERE author = ? AND name = ?",
            (author, name),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_strategy(row)

    def discover(self, family: str | None = None, author: str | None = None,
                 name_contains: str | None = None
                 ) -> list[MarketplaceStrategy]:
        """Return matching strategies. All filters are optional and AND-combined."""
        clauses = []
        params: list[Any] = []
        if family is not None:
            clauses.append("family = ?")
            params.append(family)
        if author is not None:
            clauses.append("author = ?")
            params.append(author)
        if name_contains is not None:
            clauses.append("name LIKE ?")
            params.append(f"%{name_contains}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM strategies{where} ORDER BY published_at DESC"
        cur = self._conn.execute(sql, tuple(params))
        return [self._row_to_strategy(r) for r in cur.fetchall()]

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM strategies")
        return int(cur.fetchone()["c"])

    def authors(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT author FROM strategies ORDER BY author"
        )
        return [r["author"] for r in cur.fetchall()]

    def families(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT DISTINCT family FROM strategies ORDER BY family"
        )
        return [r["family"] for r in cur.fetchall()]

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _row_to_strategy(row: sqlite3.Row) -> MarketplaceStrategy:
        return MarketplaceStrategy(
            author=row["author"], name=row["name"], family=row["family"],
            description=row["description"] or "",
            params=json.loads(row["params_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            published_at=row["published_at"],
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StrategyMarketplace":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

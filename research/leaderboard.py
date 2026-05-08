"""Strategy Leaderboard.

SQLite-backed ranking of strategies by Calmar / Sharpe across users (or
users=1 for solo). Versioned -- each submission is appended with a version
number, and queries return either the latest entry per (user, strategy) or
the full history.

Schema:

    CREATE TABLE leaderboard (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        version INTEGER NOT NULL,
        calmar REAL NOT NULL,
        sharpe REAL NOT NULL,
        cagr REAL NOT NULL,
        mdd REAL NOT NULL,
        notes TEXT DEFAULT '',
        submitted_at TEXT NOT NULL,
        UNIQUE(user_id, strategy_name, version)
    );

The DB is opened on construction. Multiple instances may safely target the
same file path (SQLite handles per-connection locking).
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS leaderboard (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    calmar REAL NOT NULL,
    sharpe REAL NOT NULL,
    cagr REAL NOT NULL,
    mdd REAL NOT NULL,
    notes TEXT DEFAULT '',
    submitted_at TEXT NOT NULL,
    UNIQUE(user_id, strategy_name, version)
);
"""


@dataclass
class LeaderboardEntry:
    user_id: str
    strategy_name: str
    version: int
    calmar: float
    sharpe: float
    cagr: float
    mdd: float
    notes: str
    submitted_at: str


class StrategyLeaderboard:
    """SQLite ranking over strategies."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- mutation -----------------------------------------------------------

    def submit(self, user_id: str, strategy_name: str, calmar: float,
               sharpe: float, cagr: float, mdd: float, notes: str = ""
               ) -> LeaderboardEntry:
        """Append a new versioned entry. Version auto-increments per (user, strategy)."""
        if not user_id or not strategy_name:
            raise ValueError("user_id and strategy_name must be non-empty")
        cur = self._conn.execute(
            "SELECT MAX(version) AS v FROM leaderboard "
            "WHERE user_id = ? AND strategy_name = ?",
            (user_id, strategy_name),
        )
        row = cur.fetchone()
        version = (row["v"] or 0) + 1
        ts = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO leaderboard (user_id, strategy_name, version, "
            "calmar, sharpe, cagr, mdd, notes, submitted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, strategy_name, version, float(calmar), float(sharpe),
             float(cagr), float(mdd), notes, ts),
        )
        self._conn.commit()
        return LeaderboardEntry(
            user_id=user_id, strategy_name=strategy_name, version=version,
            calmar=float(calmar), sharpe=float(sharpe), cagr=float(cagr),
            mdd=float(mdd), notes=notes, submitted_at=ts,
        )

    # -- queries ------------------------------------------------------------

    def latest(self, user_id: str, strategy_name: str
               ) -> LeaderboardEntry | None:
        cur = self._conn.execute(
            "SELECT * FROM leaderboard WHERE user_id = ? AND strategy_name = ? "
            "ORDER BY version DESC LIMIT 1",
            (user_id, strategy_name),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def history(self, user_id: str, strategy_name: str
                ) -> list[LeaderboardEntry]:
        cur = self._conn.execute(
            "SELECT * FROM leaderboard WHERE user_id = ? AND strategy_name = ? "
            "ORDER BY version ASC",
            (user_id, strategy_name),
        )
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def top(self, metric: str = "calmar", n: int = 10
            ) -> list[LeaderboardEntry]:
        if metric not in ("calmar", "sharpe", "cagr", "mdd"):
            raise ValueError(f"unsupported metric: {metric!r}")
        if n < 1:
            raise ValueError("n must be >= 1")
        # For mdd lower is better, but typically mdd is stored as a negative
        # number. We sort descending for the metrics where higher is better
        # and ascending for mdd.
        order = "ASC" if metric == "mdd" else "DESC"
        # Latest version per (user, strategy) only
        cur = self._conn.execute(
            f"""
            SELECT lb.* FROM leaderboard lb
            INNER JOIN (
                SELECT user_id, strategy_name, MAX(version) AS v
                FROM leaderboard GROUP BY user_id, strategy_name
            ) latest
              ON lb.user_id = latest.user_id
             AND lb.strategy_name = latest.strategy_name
             AND lb.version = latest.v
            ORDER BY lb.{metric} {order}
            LIMIT ?
            """,
            (int(n),),
        )
        return [self._row_to_entry(r) for r in cur.fetchall()]

    def all_users(self) -> list[str]:
        cur = self._conn.execute("SELECT DISTINCT user_id FROM leaderboard ORDER BY user_id")
        return [r["user_id"] for r in cur.fetchall()]

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM leaderboard")
        return int(cur.fetchone()["c"])

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> LeaderboardEntry:
        return LeaderboardEntry(
            user_id=row["user_id"],
            strategy_name=row["strategy_name"],
            version=int(row["version"]),
            calmar=float(row["calmar"]),
            sharpe=float(row["sharpe"]),
            cagr=float(row["cagr"]),
            mdd=float(row["mdd"]),
            notes=row["notes"] or "",
            submitted_at=row["submitted_at"],
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StrategyLeaderboard":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

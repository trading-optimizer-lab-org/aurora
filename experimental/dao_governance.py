"""Mock DAO governance — SQLite-backed proposal + vote tracker.

Lets a small team (or a future on-chain DAO) record proposals about project
decisions ("flip the live trading kill switch", "promote strategy X to
production", ...) and tally weighted votes against a configurable quorum
and approval threshold. No blockchain wiring; the persistence layer is a
plain SQLite file so the audit trail survives process restarts.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DAOGovernance:
    """Minimal governance ledger.

    Parameters
    ----------
    db_path : Path
        SQLite file. Created on first call.
    quorum : float
        Minimum participation as a fraction of total voting weight in (0, 1].
    approval_threshold : float
        Minimum yes-share among cast votes in (0, 1] for a proposal to pass.
    """

    db_path: Path
    quorum: float = 0.5
    approval_threshold: float = 0.5
    _conn: sqlite3.Connection = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 < self.quorum <= 1.0):
            raise ValueError("quorum must be in (0, 1]")
        if not (0.0 < self.approval_threshold <= 1.0):
            raise ValueError("approval_threshold must be in (0, 1]")
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS proposals ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "title TEXT NOT NULL, "
            "body TEXT, "
            "created_at REAL NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'open')"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS votes ("
            "proposal_id INTEGER NOT NULL, "
            "voter TEXT NOT NULL, "
            "weight REAL NOT NULL, "
            "yes INTEGER NOT NULL, "
            "PRIMARY KEY (proposal_id, voter))"
        )
        self._conn.commit()

    def create_proposal(self, title: str, body: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO proposals (title, body, created_at) VALUES (?, ?, ?)",
            (title, body, time.time()),
        )
        self._conn.commit()
        if cur.lastrowid is None:
            raise RuntimeError("sqlite did not return a lastrowid for the proposal")
        return int(cur.lastrowid)

    def vote(self, proposal_id: int, voter: str, weight: float, approve: bool) -> None:
        if weight <= 0:
            raise ValueError("weight must be > 0")
        self._conn.execute(
            "INSERT OR REPLACE INTO votes (proposal_id, voter, weight, yes) "
            "VALUES (?, ?, ?, ?)",
            (proposal_id, voter, float(weight), 1 if approve else 0),
        )
        self._conn.commit()

    def tally(self, proposal_id: int, total_weight: float) -> dict:
        """Return participation, yes-share, and pass/fail flag.

        ``total_weight`` is the universe of eligible voting weight (used for
        the quorum check). For an equal-weight DAO of N members, pass N.
        """
        if total_weight <= 0:
            raise ValueError("total_weight must be > 0")
        rows = self._conn.execute(
            "SELECT weight, yes FROM votes WHERE proposal_id = ?", (proposal_id,)
        ).fetchall()
        cast = sum(w for w, _ in rows)
        yes = sum(w for w, y in rows if y == 1)
        participation = cast / total_weight
        yes_share = (yes / cast) if cast > 0 else 0.0
        passed = (participation >= self.quorum) and (yes_share >= self.approval_threshold)
        return {
            "proposal_id": proposal_id,
            "participation": participation,
            "yes_share": yes_share,
            "passed": passed,
            "n_votes": len(rows),
        }

    def list_proposals(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, title, body, created_at, status FROM proposals ORDER BY id"
        ).fetchall()
        return [
            {"id": r[0], "title": r[1], "body": r[2], "created_at": r[3], "status": r[4]}
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()

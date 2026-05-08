"""Shared SQLite connection setup helpers.

Centralized PRAGMA setup so every SQLite connection in the project enables
WAL journaling, sets a busy timeout, and chooses an appropriate
synchronous level. Used by:

- registry.registry.BacktestRegistry
- registry.journal.TradeJournal
- core.snapshots.SnapshotStore
- deployment.brokers.AuditLog

WAL increases concurrency: readers do not block the writer and vice-versa.
``busy_timeout`` makes ``SELECT/INSERT`` retry briefly when the writer is
holding a lock, instead of immediately failing with ``database is locked``.
``synchronous=NORMAL`` is the WAL recommendation; ``synchronous=FULL`` is
used by the audit log for crash safety.
"""
from __future__ import annotations

import sqlite3


def _setup_sqlite(conn: sqlite3.Connection, mode: str = "normal") -> None:
    """Apply standard PRAGMAs to ``conn``.

    Args:
        conn: an open SQLite connection.
        mode: 'normal' for WAL+synchronous=NORMAL (registry/journal/snapshots);
              'full' for WAL+synchronous=FULL (audit log, crash-safe writes).

    Notes
    -----
    - PRAGMA ``journal_mode`` is sticky per database file. Repeated calls on
      additional connections to the same file are cheap (returns 'wal').
    - ``busy_timeout=30000`` (30 s) avoids spurious ``OperationalError:
      database is locked`` under contention. The previous 5 s ceiling was
      too aggressive for production hosts where a backup or VACUUM can
      hold the writer lock for tens of seconds.
    - ``wal_autocheckpoint=1000`` keeps the WAL file from growing
      unbounded — every 1000 frames (~1 MB) the checkpoint is folded back
      into the main DB. Without this the WAL grows for the lifetime of
      the longest open reader.
    - ``synchronous=NORMAL`` is durable across application crashes (only
      power-loss can lose the most recent transaction). ``synchronous=FULL``
      additionally protects against power-loss at the cost of fsync per
      commit.
    """
    if mode not in {"normal", "full"}:
        raise ValueError(f"mode must be 'normal' or 'full', got {mode!r}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    if mode == "full":
        conn.execute("PRAGMA synchronous=FULL")
    else:
        conn.execute("PRAGMA synchronous=NORMAL")

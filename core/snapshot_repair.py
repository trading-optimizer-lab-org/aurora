"""SnapshotStore repair helper (R36).

CLI helper: ``python -m quantforge.core.snapshot_repair --root <dir>``.

Walks the blob directory, recomputes sha256 over every parquet
content, and reports which blobs are intact vs corrupted. Optionally
rebuilds the SQLite index from the surviving blobs (each row carries
the minimum metadata needed for ``SnapshotStore.lookup`` to round-trip:
sha256, n_bars, and a synthesised symbol field tagged
"<recovered>" so an operator can see at a glance which rows came from
this rebuild rather than the original freeze).

Design notes
------------

* ``--check-only`` returns a mismatch report and exits non-zero on any
  corruption found.
* The default mode also rebuilds the index, but only after backing up
  the existing index to ``<index>.broken-<timestamp>``.
* Provenance fields the original freeze captured (policy_hash, git_hash,
  forge_version) cannot be reconstructed from the blob alone. Recovered
  rows leave those fields blank; the operator must accept that
  recovered snapshots are NOT promotable to OOS_LOCKED until they are
  re-validated under a known policy.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import time
from pathlib import Path

from quantforge.core.sqlite_utils import _setup_sqlite

_log = logging.getLogger("quantforge.core.snapshot_repair")


def _hash_blob(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def walk_blobs(root: Path) -> tuple[list[Path], list[tuple[Path, str, str]]]:
    """Walk ``<root>/blobs/`` and return (intact, mismatched).

    intact = blobs whose sha256 matches the filename stem.
    mismatched = list of (path, declared_hash, actual_hash).
    """
    blobs_dir = root / "blobs"
    if not blobs_dir.exists():
        # Older SnapshotStore layouts wrote parquets directly under root.
        blobs_dir = root
    intact: list[Path] = []
    mismatched: list[tuple[Path, str, str]] = []
    for p in sorted(blobs_dir.glob("*.parquet")):
        declared = p.stem
        actual = _hash_blob(p)
        if declared == actual:
            intact.append(p)
        else:
            mismatched.append((p, declared, actual))
    return intact, mismatched


_SCHEMA = """
    CREATE TABLE IF NOT EXISTS snapshots (
        sha256       TEXT PRIMARY KEY,
        symbol       TEXT NOT NULL,
        start_iso    TEXT NOT NULL,
        end_iso      TEXT NOT NULL,
        n_bars       INTEGER NOT NULL,
        provenance   TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        data_path    TEXT NOT NULL,
        locked       INTEGER NOT NULL DEFAULT 0,
        git_hash     TEXT,
        forge_version TEXT,
        seed         INTEGER,
        config_hash  TEXT,
        policy_hash  TEXT,
        audit_report_hash TEXT
    )
"""


def rebuild_index(root: Path, intact: list[Path]) -> Path:
    """Rebuild the SQLite index from the intact blob list."""
    index_path = root / "snapshots_index.sqlite"
    if index_path.exists():
        backup = index_path.with_name(
            f"{index_path.stem}.broken-{int(time.time())}{index_path.suffix}"
        )
        index_path.rename(backup)
        _log.warning("backed up existing index to %s", backup)

    con = sqlite3.connect(str(index_path))
    try:
        _setup_sqlite(con, mode="normal")
        con.execute(_SCHEMA)
        for p in intact:
            sha = p.stem
            try:
                import pandas as pd
                df = pd.read_parquet(p)
                n = len(df)
            except Exception:
                n = 0
            con.execute(
                """
                INSERT OR REPLACE INTO snapshots
                (sha256, symbol, start_iso, end_iso, n_bars, provenance,
                 created_at, data_path, locked,
                 git_hash, forge_version, seed, config_hash, policy_hash,
                 audit_report_hash)
                VALUES (?, '<recovered>', '', '', ?, 'recovered',
                        ?, ?, 0,
                        NULL, NULL, NULL, NULL, NULL,
                        NULL)
                """,
                (sha, n, time.strftime("%Y-%m-%dT%H:%M:%S"), str(p)),
            )
        con.commit()
    finally:
        con.close()
    return index_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path,
                        help="Snapshot store root (parent of blobs/).")
    parser.add_argument("--check-only", action="store_true",
                        help="Report mismatches without rebuilding the index.")
    args = parser.parse_args(argv)

    intact, mismatched = walk_blobs(args.root)
    print(f"intact: {len(intact)} blobs")
    print(f"mismatched: {len(mismatched)} blobs")
    for p, declared, actual in mismatched:
        print(f"  {p.name}: declared={declared[:12]}... actual={actual[:12]}...")

    if args.check_only:
        return 1 if mismatched else 0

    index = rebuild_index(args.root, intact)
    print(f"index rebuilt: {index} ({len(intact)} rows)")
    return 1 if mismatched else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())

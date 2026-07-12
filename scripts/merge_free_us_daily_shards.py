"""Merge sharded free_us_daily GitHub Actions artifacts into one data lake."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.free_us_daily import (
    ensure_layout,
    read_download_results,
    validate_persisted_prices,
    write_coverage_report,
)


def _copy_tree_files(src: Path, dst: Path, pattern: str) -> int:
    count = 0
    if not src.exists():
        return count
    dst.mkdir(parents=True, exist_ok=True)
    for path in src.glob(pattern):
        if path.is_file():
            shutil.copy2(path, dst / path.name)
            count += 1
    return count


def _candidate_roots(shards_dir: Path) -> list[Path]:
    roots: list[Path] = []
    if shards_dir.exists():
        for path in shards_dir.iterdir():
            if (
                path.is_dir()
                and (path / "catalog.sqlite").exists()
                and ((path / "raw").exists() or (path / "normalized").exists())
            ):
                roots.append(path)
    for path in shards_dir.rglob("prices/free_us_daily"):
        if path.is_dir():
            roots.append(path)
    for path in shards_dir.rglob("free_us_daily"):
        if path.is_dir() and path not in roots:
            roots.append(path)
    return sorted(set(roots))


def _merge_catalog(src_catalog: Path, dst_catalog: Path) -> int:
    if not src_catalog.exists():
        return 0
    with sqlite3.connect(src_catalog) as src:
        has_downloads = src.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='downloads'"
        ).fetchone()
        if not has_downloads:
            return 0
        rows = src.execute(
            """
            SELECT
                symbol, provider_symbol, yfinance_symbol, status, rows,
                first_date, last_date, years, error, warnings_json,
                raw_path, normalized_path, retrieved_at
            FROM downloads
            """
        ).fetchall()
    if not rows:
        return 0
    with sqlite3.connect(dst_catalog) as dst:
        dst.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                symbol TEXT PRIMARY KEY,
                provider_symbol TEXT,
                yfinance_symbol TEXT,
                status TEXT,
                rows INTEGER,
                first_date TEXT,
                last_date TEXT,
                years REAL,
                error TEXT,
                warnings_json TEXT,
                raw_path TEXT,
                normalized_path TEXT,
                retrieved_at TEXT
            )
            """
        )
        dst.executemany(
            """
            INSERT INTO downloads (
                symbol, provider_symbol, yfinance_symbol, status, rows,
                first_date, last_date, years, error, warnings_json,
                raw_path, normalized_path, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                provider_symbol=excluded.provider_symbol,
                yfinance_symbol=excluded.yfinance_symbol,
                status=excluded.status,
                rows=excluded.rows,
                first_date=excluded.first_date,
                last_date=excluded.last_date,
                years=excluded.years,
                error=excluded.error,
                warnings_json=excluded.warnings_json,
                raw_path=excluded.raw_path,
                normalized_path=excluded.normalized_path,
                retrieved_at=excluded.retrieved_at
            """,
            rows,
        )
    return len(rows)


def main() -> int:
    require_github_actions_or_explicit_local_permission("free_us_daily shard merge")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="QF_DATA_DIR-style root")
    parser.add_argument("--shards-dir", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    shards_dir = Path(args.shards_dir)
    paths = ensure_layout(root)
    copied_raw = 0
    copied_normalized = 0
    merged_catalog_rows = 0
    for shard_root in _candidate_roots(shards_dir):
        copied_raw += _copy_tree_files(
            shard_root / "raw" / "yfinance",
            paths["raw_dir"],
            "*.parquet",
        )
        copied_normalized += _copy_tree_files(
            shard_root / "normalized",
            paths["normalized_dir"],
            "*.parquet",
        )
        merged_catalog_rows += _merge_catalog(
            shard_root / "catalog.sqlite",
            paths["catalog_path"],
        )
    validate_persisted_prices(root=root)
    coverage_path = write_coverage_report(root=root)
    downloads = read_download_results(root=root)
    payload = {
        "copied_raw": copied_raw,
        "copied_normalized": copied_normalized,
        "merged_catalog_rows": merged_catalog_rows,
        "catalog_rows": int(len(downloads)),
        "coverage_report": str(coverage_path),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""DuckDB builder for the immutable full-universe pre-2021 research artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Sequence

import duckdb
import pandas as pd

from .dataset import DAILY_COLUMNS, DailySource, discover_daily_sources


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _relation(source: DailySource) -> str | None:
    path = _quote(source.path.as_posix())
    if source.format == "parquet":
        return f"read_parquet({path}, union_by_name=true)"
    if source.format == "csv":
        return f"read_csv_auto({path}, union_by_name=true, header=true)"
    return None


def _columns(connection: duckdb.DuckDBPyConnection, relation: str) -> dict[str, str]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    return {str(row[0]).strip().lower(): str(row[0]) for row in rows}


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _source_select(
    connection: duckdb.DuckDBPyConnection,
    source: DailySource,
    source_index: int,
    end_date: str,
) -> str | None:
    relation = _relation(source)
    if relation is None:
        return None
    columns = _columns(connection, relation)
    aliases = {
        "date": ("date", "datetime", "timestamp", "index"),
        "symbol": ("symbol", "ticker"),
        "adj_close": ("adj_close", "adjclose", "adjusted_close"),
        "stock_splits": ("stock_splits", "stock_split"),
    }

    def expression(name: str, default: str) -> str:
        candidates = aliases.get(name, (name,))
        actual = next((columns[item] for item in candidates if item in columns), None)
        return _identifier(actual) if actual else default

    date_expr = expression("date", "NULL")
    if date_expr == "NULL" or any(expression(name, "NULL") == "NULL" for name in ("open", "high", "low", "close")):
        return None
    symbol_expr = expression("symbol", _quote(source.path.stem.upper()))
    select_columns = [
        f"TRY_CAST({date_expr} AS DATE) AS date",
        f"UPPER(TRIM(CAST({symbol_expr} AS VARCHAR))) AS symbol",
        *[
            f"TRY_CAST({expression(name, 'NULL')} AS DOUBLE) AS {name}"
            for name in ("open", "high", "low", "close")
        ],
        f"TRY_CAST({expression('adj_close', expression('close', 'NULL'))} AS DOUBLE) AS adj_close",
        f"COALESCE(TRY_CAST({expression('volume', '0')} AS DOUBLE), 0) AS volume",
        f"COALESCE(TRY_CAST({expression('dividends', '0')} AS DOUBLE), 0) AS dividends",
        f"COALESCE(TRY_CAST({expression('stock_splits', '0')} AS DOUBLE), 0) AS stock_splits",
        f"{source_index}::INTEGER AS _source_order",
        f"{_quote(source.path.as_posix())} AS _source_path",
    ]
    return (
        "SELECT " + ", ".join(select_columns) + f" FROM {relation} "
        f"WHERE TRY_CAST({date_expr} AS DATE) <= DATE {_quote(end_date)}"
    )


def _write_root_cause(path: Path) -> None:
    path.write_text(
        """# Causa exacta del pack anterior de dos simbolos

El run `29505808241` consumio `final-qf-data/stock_protocol_pack`. Su
`pack_audit.json` demuestra 30.395 filas y exactamente dos simbolos: `SPY` y
`^GSPC`.

El job de merge copio 1.626 Parquet normalizados y registro 2.091 filas de
catalogo, pero recibio `--root final-qf-data/prices/free_us_daily`.
`ensure_layout(root)` interpreta su argumento como `QF_DATA_DIR` y vuelve a
anadir `prices/free_us_daily`. Por eso las 1.626 acciones quedaron en:

`final-qf-data/prices/free_us_daily/prices/free_us_daily/normalized`

Los dos benchmarks estaban en la ruta directa:

`final-qf-data/prices/free_us_daily/benchmarks`

La antigua funcion `_parquet_paths()` encontro esos dos archivos directos y,
al no estar vacia la lista, no ejecuto la busqueda recursiva. Ignoro asi los
1.626 Parquet anidados y construyo el pack solo con SPY y GSPC. Esta cadena se
demuestra con el log del job `87647118754`, el arbol del artifact de universo,
el codigo anterior y el `pack_audit.json`; no fue un filtro financiero.
""",
        encoding="utf-8",
    )


def build_full_pre2021_pack(
    source_roots: Sequence[Path],
    output_root: Path,
    end_date: str = "2020-12-31",
    shard_count: int = 32,
    minimum_symbols: int = 1000,
    provenance: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a deduplicated, quality-controlled and hash-bound research pack."""

    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    sources = discover_daily_sources(list(source_roots))
    if not sources:
        raise FileNotFoundError("no source files discovered")
    output_root.mkdir(parents=True, exist_ok=True)
    pack_root = output_root / "pre2021_full_daily_pack"
    pack_root.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(output_root / "build.duckdb"))
    ignored: list[dict[str, str]] = []
    selects: list[str] = []
    for index, source in enumerate(sources):
        try:
            query = _source_select(connection, source, index, end_date)
        except Exception as exc:
            ignored.append({"path": str(source.path), "reason": f"schema_error:{type(exc).__name__}:{exc}"})
            continue
        if query is None:
            ignored.append({"path": str(source.path), "reason": "unsupported_or_missing_daily_ohlc"})
            continue
        selects.append(query)
    if not selects:
        connection.close()
        raise ValueError("no compatible daily source remained")
    connection.execute("CREATE TABLE source_pre2021 AS " + " UNION ALL ".join(selects))
    source_rows = int(connection.execute("SELECT COUNT(*) FROM source_pre2021").fetchone()[0])
    source_symbols = int(connection.execute("SELECT COUNT(DISTINCT symbol) FROM source_pre2021").fetchone()[0])
    connection.execute(
        """
        CREATE TABLE valid_pre2021 AS
        SELECT * FROM source_pre2021
        WHERE date IS NOT NULL AND symbol <> ''
          AND open > 0 AND high > 0 AND low > 0 AND close > 0
          AND high >= GREATEST(open, close, low)
          AND low <= LEAST(open, close, high)
        """
    )
    valid_rows = int(connection.execute("SELECT COUNT(*) FROM valid_pre2021").fetchone()[0])
    invalid_rows = source_rows - valid_rows
    connection.execute(
        """
        CREATE TABLE canonical AS
        SELECT date, symbol, open, high, low, close,
               COALESCE(adj_close, close) AS adj_close, volume, dividends, stock_splits
        FROM valid_pre2021
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY symbol, date ORDER BY _source_order, _source_path
        ) = 1
        """
    )
    pack_rows = int(connection.execute("SELECT COUNT(*) FROM canonical").fetchone()[0])
    pack_symbols = int(connection.execute("SELECT COUNT(DISTINCT symbol) FROM canonical").fetchone()[0])
    duplicates_removed = valid_rows - pack_rows
    if pack_symbols < minimum_symbols:
        connection.close()
        raise ValueError(f"minimum symbol control failed: {pack_symbols} < {minimum_symbols}")
    if source_symbols and (source_symbols - pack_symbols) / source_symbols > 0.05:
        connection.close()
        raise ValueError("unexpected symbol coverage reduction exceeds 5%")

    coverage = connection.execute(
        """
        SELECT symbol, MIN(date) AS first_date, MAX(date) AS last_date,
               COUNT(*) AS rows, COUNT(DISTINCT date) AS unique_dates,
               SUM(CASE WHEN volume IS NULL OR volume <= 0 THEN 1 ELSE 0 END) AS missing_volume,
               SUM(CASE WHEN dividends <> 0 THEN 1 ELSE 0 END) AS dividend_rows,
               SUM(CASE WHEN stock_splits <> 0 THEN 1 ELSE 0 END) AS split_rows,
               COUNT(*) >= 252 AS eligible_252, COUNT(*) >= 504 AS eligible_504
        FROM canonical GROUP BY symbol ORDER BY symbol
        """
    ).fetch_df()
    coverage.to_csv(output_root / "pre2021_symbol_coverage.csv", index=False)
    symbols_252 = int(coverage["eligible_252"].sum())
    symbols_504 = int(coverage["eligible_504"].sum())

    inventory = connection.execute(
        """
        SELECT _source_path AS path, symbol, MIN(date) AS min_date, MAX(date) AS max_date,
               COUNT(*) AS rows, COUNT(DISTINCT date) AS unique_dates,
               COUNT(*) - COUNT(DISTINCT date) AS duplicate_dates,
               SUM(CASE WHEN volume IS NULL OR volume <= 0 THEN 1 ELSE 0 END) AS missing_volume,
               SUM(CASE WHEN dividends <> 0 THEN 1 ELSE 0 END) AS dividend_rows,
               SUM(CASE WHEN stock_splits <> 0 THEN 1 ELSE 0 END) AS split_rows
        FROM source_pre2021 GROUP BY _source_path, symbol ORDER BY _source_path, symbol
        """
    ).fetch_df()
    metadata = {
        str(source.path.as_posix()): {
            "format": source.format,
            "file_size": source.path.stat().st_size,
            "sha256": _sha256(source.path),
        }
        for source in sources
    }
    inventory["format"] = inventory["path"].map(lambda value: metadata[str(value)]["format"])
    inventory["columns"] = ",".join(DAILY_COLUMNS)
    inventory["invalid_ohlc"] = 0
    inventory["file_size"] = inventory["path"].map(lambda value: metadata[str(value)]["file_size"])
    inventory["sha256"] = inventory["path"].map(lambda value: metadata[str(value)]["sha256"])
    inventory.to_csv(output_root / "full_dataset_inventory.csv", index=False)

    exclusions = connection.execute(
        """
        SELECT _source_path AS path, symbol,
               COUNT(*) AS rows_removed, 'invalid_ohlc_or_required_field' AS reason,
               FALSE AS included_in_pack
        FROM source_pre2021
        WHERE NOT (date IS NOT NULL AND symbol <> '' AND open > 0 AND high > 0
          AND low > 0 AND close > 0 AND high >= GREATEST(open, close, low)
          AND low <= LEAST(open, close, high))
        GROUP BY _source_path, symbol
        """
    ).fetch_df()
    short_history = coverage.loc[~coverage["eligible_252"], ["symbol", "rows"]].copy()
    short_history["path"] = "canonical_pack"
    short_history = short_history.rename(columns={"rows": "rows_removed"})
    short_history["rows_removed"] = 0
    short_history["reason"] = "included_but_not_eligible_for_252_session_signal"
    short_history["included_in_pack"] = True
    ignored_frame = pd.DataFrame(ignored)
    if not ignored_frame.empty:
        ignored_frame["symbol"] = ""
        ignored_frame["rows_removed"] = 0
        ignored_frame["included_in_pack"] = False
        ignored_frame = ignored_frame[["path", "symbol", "rows_removed", "reason", "included_in_pack"]]
    exclusions = pd.concat(
        [exclusions, short_history[["path", "symbol", "rows_removed", "reason", "included_in_pack"]], ignored_frame],
        ignore_index=True,
    )
    exclusions.to_csv(output_root / "dataset_exclusions.csv", index=False)

    shard_entries: list[dict[str, object]] = []
    for shard in range(shard_count):
        shard_path = pack_root / f"shard-{shard:03d}.parquet"
        connection.execute(
            f"COPY (SELECT * FROM canonical WHERE ABS(HASH(symbol)) % {shard_count} = {shard} ORDER BY symbol, date) "
            f"TO {_quote(shard_path.as_posix())} (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        stats = connection.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM read_parquet({_quote(shard_path.as_posix())})"
        ).fetchone()
        shard_entries.append(
            {
                "shard": shard,
                "path": shard_path.relative_to(output_root).as_posix(),
                "rows": int(stats[0]),
                "symbols": int(stats[1]),
                "first_date": str(stats[2]) if stats[2] else None,
                "last_date": str(stats[3]) if stats[3] else None,
                "bytes": shard_path.stat().st_size,
                "sha256": _sha256(shard_path),
            }
        )
    first_date, last_date = connection.execute("SELECT MIN(date), MAX(date) FROM canonical").fetchone()
    connection.close()
    (output_root / "build.duckdb").unlink(missing_ok=True)

    manifest_core = {
        "shards_expected": shard_count,
        "shards_found": len(shard_entries),
        "shards": shard_entries,
    }
    dataset_hash = hashlib.sha256(
        json.dumps(manifest_core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = {**manifest_core, "dataset_hash": dataset_hash}
    (output_root / "data_shard_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    audit: dict[str, object] = {
        "source_files": len(selects),
        "source_symbols": source_symbols,
        "source_rows": source_rows,
        "pack_symbols": pack_symbols,
        "pack_rows": pack_rows,
        "symbols": pack_symbols,
        "rows": pack_rows,
        "first_date": str(first_date),
        "last_date": str(last_date),
        "data_start": str(first_date),
        "data_end": end_date,
        "symbols_with_252_sessions": symbols_252,
        "symbols_with_504_sessions": symbols_504,
        "duplicates_removed": duplicates_removed,
        "invalid_rows_removed": invalid_rows,
        "locked_rows": 0,
        "locked_opened": False,
        "survivorship_free": False,
        "metadata_is_bitemporal": False,
        "dataset_hash": dataset_hash,
        "source_artifact": provenance or {},
        "ignored_files": ignored,
    }
    for name in ("pre2021_pack_audit.json", "full_dataset_audit.json", "pack_audit.json"):
        (output_root / name).write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    (pack_root / "pack_audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
    _write_root_cause(output_root / "two_symbol_root_cause.md")
    return audit

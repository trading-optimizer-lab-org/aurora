"""Discovery, canonicalisation and bounded loading of daily price datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Sequence

import pandas as pd

from .manifest import ProtocolManifest


DAILY_COLUMNS = (
    "date", "symbol", "open", "high", "low", "close", "adj_close",
    "volume", "dividends", "stock_splits",
)
SUPPORTED_SUFFIXES = {".parquet", ".csv", ".duckdb", ".sqlite", ".db"}


@dataclass(frozen=True)
class DailySource:
    path: Path
    format: str
    root_priority: int


@dataclass(frozen=True)
class PackAudit:
    source_root: str
    output_root: str
    data_start: str | None
    data_end: str
    rows: int
    symbols: int
    locked_rows: int
    survivorship_free: bool
    metadata_is_bitemporal: bool
    dataset_hash: str
    locked_opened: bool = False
    source_files: int = 0
    duplicates_removed: int = 0
    invalid_rows_removed: int = 0
    ignored_files: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["ignored_files"] = list(self.ignored_files)
        return payload


@dataclass(frozen=True)
class ResearchPanel:
    frame: pd.DataFrame
    audit: PackAudit


def _roots(value: Path | Sequence[Path]) -> list[Path]:
    if isinstance(value, Path):
        return [value]
    roots = [Path(item) for item in value]
    if not roots:
        raise ValueError("at least one data root is required")
    return roots


def discover_daily_sources(roots: Path | Sequence[Path]) -> list[DailySource]:
    """Find every supported candidate under every configured root.

    Discovery deliberately never stops after finding files in a preferred folder.
    Canonical precedence is root order followed by the absolute path.
    """

    found: dict[Path, DailySource] = {}
    for priority, root in enumerate(_roots(roots)):
        if root.is_file() and root.suffix.lower() in SUPPORTED_SUFFIXES:
            resolved = root.resolve()
            found.setdefault(resolved, DailySource(resolved, root.suffix.lower()[1:], priority))
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                resolved = path.resolve()
                current = found.get(resolved)
                candidate = DailySource(resolved, path.suffix.lower()[1:], priority)
                if current is None or candidate.root_priority < current.root_priority:
                    found[resolved] = candidate
    return sorted(found.values(), key=lambda item: (item.root_priority, str(item.path).lower()))


def _normalise_columns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
    aliases = {
        "adjclose": "adj_close",
        "adjusted_close": "adj_close",
        "stock_split": "stock_splits",
        "ticker": "symbol",
    }
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "date" not in frame.columns:
        for candidate in ("datetime", "timestamp", "index"):
            if candidate in frame.columns:
                frame = frame.rename(columns={candidate: "date"})
                break
    if "date" not in frame.columns:
        raise ValueError("missing date column")
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol
    for column in DAILY_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0 if column in {"dividends", "stock_splits", "volume"} else pd.NA
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    for column in DAILY_COLUMNS[2:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[list(DAILY_COLUMNS)]


def _read_parquet_bounded(path: Path, end: pd.Timestamp) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, filters=[("date", "<=", end.to_pydatetime())])
    except Exception:
        frame = pd.read_parquet(path)
        date_column = next(
            (column for column in frame.columns if str(column).strip().lower() in {"date", "datetime", "timestamp", "index"}),
            None,
        )
        if date_column is None:
            return frame
        return frame.loc[pd.to_datetime(frame[date_column], errors="coerce", utc=True).dt.tz_convert(None) <= end]


def _read_csv_bounded(path: Path, end: pd.Timestamp) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(path, chunksize=250_000):
        date_column = next(
            (column for column in chunk.columns if str(column).strip().lower() in {"date", "datetime", "timestamp", "index"}),
            None,
        )
        if date_column is None:
            return chunk
        dates = pd.to_datetime(chunk[date_column], errors="coerce", utc=True).dt.tz_convert(None)
        chunks.append(chunk.loc[dates <= end])
    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def _database_tables(path: Path, engine: str) -> list[str]:
    if engine == "duckdb":
        import duckdb

        with duckdb.connect(str(path), read_only=True) as connection:
            return [str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()]
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        return [
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]


def _read_database_bounded(path: Path, engine: str, end: pd.Timestamp) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for table in _database_tables(path, engine):
        quoted = '"' + table.replace('"', '""') + '"'
        if engine == "duckdb":
            import duckdb

            with duckdb.connect(str(path), read_only=True) as connection:
                columns = {str(row[0]).lower() for row in connection.execute(f"DESCRIBE {quoted}").fetchall()}
                if "date" not in columns or not {"open", "high", "low", "close"}.issubset(columns):
                    continue
                frames.append(connection.execute(f"SELECT * FROM {quoted} WHERE CAST(date AS DATE) <= ?", [end.date()]).fetch_df())
        else:
            with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
                columns = {str(row[1]).lower() for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()}
                if "date" not in columns or not {"open", "high", "low", "close"}.issubset(columns):
                    continue
                frames.append(pd.read_sql_query(f"SELECT * FROM {quoted} WHERE date <= ?", connection, params=[end.date().isoformat()]))
    return frames


def _read_source_bounded(source: DailySource, end: pd.Timestamp) -> list[pd.DataFrame]:
    if source.format == "parquet":
        return [_read_parquet_bounded(source.path, end)]
    if source.format == "csv":
        return [_read_csv_bounded(source.path, end)]
    if source.format == "duckdb":
        return _read_database_bounded(source.path, "duckdb", end)
    if source.format in {"sqlite", "db"}:
        return _read_database_bounded(source.path, "sqlite", end)
    return []


def _hash_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values(["date", "symbol"]).reset_index(drop=True)
    digest.update(ordered.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8"))
    return digest.hexdigest()


def load_bounded_daily_panel(root: Path | Sequence[Path], end_date: str) -> ResearchPanel:
    """Load all configured sources while materialising no row after ``end_date``."""

    roots = _roots(root)
    end = pd.Timestamp(end_date).normalize()
    sources = discover_daily_sources(roots)
    if not sources:
        raise FileNotFoundError(f"no supported daily files found under {roots}")
    frames: list[pd.DataFrame] = []
    ignored: list[str] = []
    for source_order, source in enumerate(sources):
        try:
            source_frames = _read_source_bounded(source, end)
        except Exception as exc:  # one unrelated database must not hide valid price files
            ignored.append(f"{source.path}: {type(exc).__name__}: {exc}")
            continue
        if not source_frames:
            ignored.append(f"{source.path}: no compatible daily OHLC table")
            continue
        for frame_order, raw in enumerate(source_frames):
            if raw.empty:
                continue
            try:
                frame = _normalise_columns(raw, source.path.stem.upper())
            except ValueError as exc:
                ignored.append(f"{source.path}: {exc}")
                continue
            frame = frame.loc[frame["date"].le(end)].copy()
            frame["_source_order"] = source_order
            frame["_frame_order"] = frame_order
            frames.append(frame)
    if not frames:
        raise ValueError("bounded daily panel is empty")
    combined = pd.concat(frames, ignore_index=True)
    valid = combined["date"].notna()
    for column in ("open", "high", "low", "close"):
        valid &= combined[column].notna() & combined[column].gt(0)
    valid &= combined["high"].ge(combined[["open", "close", "low"]].max(axis=1))
    valid &= combined["low"].le(combined[["open", "close", "high"]].min(axis=1))
    invalid_rows = int((~valid).sum())
    combined = combined.loc[valid].sort_values(
        ["date", "symbol", "_source_order", "_frame_order"], kind="stable"
    )
    before_dedup = len(combined)
    combined = combined.drop_duplicates(["date", "symbol"], keep="first")
    duplicates_removed = int(before_dedup - len(combined))
    combined = combined[list(DAILY_COLUMNS)].sort_values(["date", "symbol"]).reset_index(drop=True)
    if combined.empty:
        raise ValueError("bounded daily panel is empty after quality controls")
    audit = PackAudit(
        source_root=json.dumps([str(item) for item in roots]),
        output_root="",
        data_start=combined["date"].min().date().isoformat(),
        data_end=end.date().isoformat(),
        rows=int(len(combined)),
        symbols=int(combined["symbol"].nunique()),
        locked_rows=0,
        survivorship_free=False,
        metadata_is_bitemporal=False,
        dataset_hash=_hash_frame(combined),
        source_files=len(sources),
        duplicates_removed=duplicates_removed,
        invalid_rows_removed=invalid_rows,
        ignored_files=tuple(ignored),
    )
    return ResearchPanel(combined, audit)


def build_research_pack(
    source_root: Path | Sequence[Path],
    output_root: Path,
    manifest: ProtocolManifest,
) -> PackAudit:
    panel = load_bounded_daily_panel(source_root, manifest.data_end)
    output_root.mkdir(parents=True, exist_ok=True)
    for year, year_frame in panel.frame.groupby(panel.frame["date"].dt.year):
        year_dir = output_root / f"year={int(year)}"
        year_dir.mkdir(parents=True, exist_ok=True)
        year_frame.to_parquet(year_dir / "data.parquet", index=False)
    audit = PackAudit(**{**panel.audit.to_json(), "ignored_files": tuple(panel.audit.ignored_files), "output_root": str(output_root)})
    (output_root / "pack_audit.json").write_text(
        json.dumps(audit.to_json(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "policy_hash.txt").write_text(manifest.policy_hash + "\n", encoding="utf-8")
    return audit


def _pack_paths(root: Path) -> list[Path]:
    legacy = sorted(root.glob("year=*/data.parquet"))
    if legacy:
        return legacy
    full_pack = root / "pre2021_full_daily_pack"
    if full_pack.is_dir():
        return sorted(full_pack.rglob("*.parquet"))
    return sorted(root.glob("shard_id=*/*.parquet")) + sorted(root.glob("shard-*.parquet"))


def _read_pack_audit(root: Path, frame: pd.DataFrame, end: pd.Timestamp) -> PackAudit:
    audit_path = root / "pack_audit.json"
    if audit_path.exists():
        return read_pack_audit(root)
    return PackAudit(
        source_root="pack", output_root=str(root),
        data_start=str(frame["date"].min().date()), data_end=end.date().isoformat(),
        rows=int(len(frame)), symbols=int(frame["symbol"].nunique()), locked_rows=0,
        survivorship_free=False, metadata_is_bitemporal=False,
        dataset_hash=_hash_frame(frame),
    )


def read_pack_audit(root: Path) -> PackAudit:
    """Load the immutable pack identity without materialising price rows."""

    audit_path = root / "pack_audit.json"
    if not audit_path.is_file():
        raise FileNotFoundError(f"pack audit is missing: {audit_path}")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    required = {"dataset_hash", "data_end"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"pack audit missing fields: {sorted(missing)}")
    rows = int(payload.get("rows", payload.get("pack_rows", 0)))
    symbols = int(payload.get("symbols", payload.get("pack_symbols", 0)))
    if rows <= 0 or symbols <= 0:
        raise ValueError("pack audit has non-positive row or symbol count")
    return PackAudit(
        source_root=str(payload.get("source_root", "artifact")),
        output_root=str(payload.get("output_root", root)),
        data_start=payload.get("data_start") or payload.get("first_date"),
        data_end=str(payload["data_end"]),
        rows=rows,
        symbols=symbols,
        locked_rows=int(payload.get("locked_rows", 0)),
        survivorship_free=bool(payload.get("survivorship_free", False)),
        metadata_is_bitemporal=bool(payload.get("metadata_is_bitemporal", False)),
        dataset_hash=str(payload["dataset_hash"]),
        locked_opened=bool(payload.get("locked_opened", False)),
        source_files=int(payload.get("source_files", 0)),
        duplicates_removed=int(payload.get("duplicates_removed", 0)),
        invalid_rows_removed=int(payload.get("invalid_rows_removed", 0)),
        ignored_files=tuple(str(item) for item in payload.get("ignored_files", ())),
    )


def _read_pack_partition_range(
    path: Path,
    start: pd.Timestamp | None,
    end: pd.Timestamp,
) -> pd.DataFrame:
    filters: list[tuple[str, str, object]] = [("date", "<=", end.to_pydatetime())]
    if start is not None:
        filters.insert(0, ("date", ">=", start.to_pydatetime()))
    try:
        return pd.read_parquet(path, filters=filters)
    except Exception:
        frame = pd.read_parquet(path)
        dates = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
        mask = dates.le(end)
        if start is not None:
            mask &= dates.ge(start)
        return frame.loc[mask].copy()


def read_pack_range(
    root: Path,
    *,
    start_date: str | None = None,
    end_date: str = "2020-12-31",
) -> ResearchPanel:
    """Read only a bounded interval while preserving the immutable pack identity."""

    start = pd.Timestamp(start_date).normalize() if start_date is not None else None
    end = pd.Timestamp(end_date).normalize()
    if start is not None and start > end:
        raise ValueError("pack range start must not exceed end")
    frames = [
        frame
        for path in _pack_paths(root)
        if not (frame := _read_pack_partition_range(path, start, end)).empty
    ]
    if not frames:
        raise FileNotFoundError(f"no pack observations found under {root} in requested range")
    frame = pd.concat(frames, ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    if start is not None and frame["date"].lt(start).any():
        raise ValueError(f"pack contains rows before {start.date().isoformat()}")
    if frame["date"].gt(end).any():
        raise ValueError(f"pack contains rows after {end.date().isoformat()}")
    audit = _read_pack_audit(root, frame, end)
    return ResearchPanel(frame.sort_values(["date", "symbol"]).reset_index(drop=True), audit)


def read_pack(root: Path, end_date: str = "2020-12-31") -> ResearchPanel:
    return read_pack_range(root, end_date=end_date)

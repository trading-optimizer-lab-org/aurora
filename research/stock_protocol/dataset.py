"""Date-bounded daily panel and compact research-pack builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from .manifest import ProtocolManifest


DAILY_COLUMNS = (
    "date", "symbol", "open", "high", "low", "close", "adj_close",
    "volume", "dividends", "stock_splits",
)


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

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchPanel:
    frame: pd.DataFrame
    audit: PackAudit


def _normalise_columns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(col).strip().lower().replace(" ", "_") for col in frame.columns]
    aliases = {"adjclose": "adj_close", "stock_split": "stock_splits"}
    frame = frame.rename(columns={key: value for key, value in aliases.items() if key in frame.columns})
    if "date" not in frame.columns:
        for candidate in ("datetime", "timestamp", "index"):
            if candidate in frame.columns:
                frame = frame.rename(columns={candidate: "date"})
                break
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol
    for column in DAILY_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0 if column in {"dividends", "stock_splits", "volume"} else pd.NA
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    for column in DAILY_COLUMNS[2:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame[list(DAILY_COLUMNS)]


def _parquet_paths(root: Path) -> list[Path]:
    candidates = []
    for base in (root / "normalized", root / "benchmarks"):
        if base.exists():
            candidates.extend(base.rglob("*.parquet"))
    if not candidates:
        candidates.extend(root.rglob("*.parquet"))
    return sorted({path for path in candidates if path.is_file()})


def _hash_frame(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    ordered = frame.sort_values(["date", "symbol"]).reset_index(drop=True)
    digest.update(ordered.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8"))
    return digest.hexdigest()


def load_bounded_daily_panel(root: Path, end_date: str) -> ResearchPanel:
    """Load daily OHLCV and fail if source data crosses the requested boundary."""

    end = pd.Timestamp(end_date).normalize()
    paths = _parquet_paths(root)
    if not paths:
        raise FileNotFoundError(f"no daily parquet files found under {root}")
    frames: list[pd.DataFrame] = []
    locked_rows = 0
    for path in paths:
        symbol = path.stem.upper()
        frame = pd.read_parquet(path)
        frame = _normalise_columns(frame, symbol)
        invalid = int((frame["date"] > end).sum())
        locked_rows += invalid
        if invalid:
            raise ValueError(
                f"source contains {invalid} rows after {end.date().isoformat()} in {path}"
            )
        frames.append(frame.dropna(subset=["date", "open", "high", "low", "close"]))
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(["date", "symbol"], keep="last")
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    if combined.empty:
        raise ValueError("bounded daily panel is empty")
    audit = PackAudit(
        source_root=str(root),
        output_root="",
        data_start=combined["date"].min().date().isoformat(),
        data_end=end.date().isoformat(),
        rows=int(len(combined)),
        symbols=int(combined["symbol"].nunique()),
        locked_rows=locked_rows,
        survivorship_free=False,
        metadata_is_bitemporal=False,
        dataset_hash=_hash_frame(combined),
    )
    return ResearchPanel(combined, audit)


def build_research_pack(
    source_root: Path,
    output_root: Path,
    manifest: ProtocolManifest,
) -> PackAudit:
    panel = load_bounded_daily_panel(source_root, manifest.data_end)
    output_root.mkdir(parents=True, exist_ok=True)
    for year, year_frame in panel.frame.groupby(panel.frame["date"].dt.year):
        year_dir = output_root / f"year={int(year)}"
        year_dir.mkdir(parents=True, exist_ok=True)
        year_frame.to_parquet(year_dir / "data.parquet", index=False)
    audit = PackAudit(
        **{**panel.audit.to_json(), "output_root": str(output_root)}
    )
    (output_root / "pack_audit.json").write_text(
        json.dumps(audit.to_json(), indent=2, sort_keys=True), encoding="utf-8"
    )
    (output_root / "policy_hash.txt").write_text(manifest.policy_hash + "\n", encoding="utf-8")
    return audit


def read_pack(root: Path, end_date: str = "2020-12-31") -> ResearchPanel:
    frames = []
    for path in sorted(root.glob("year=*/data.parquet")):
        frames.append(pd.read_parquet(path))
    if not frames:
        raise FileNotFoundError(f"no pack partitions found under {root}")
    frame = pd.concat(frames, ignore_index=True)
    end = pd.Timestamp(end_date).normalize()
    if (pd.to_datetime(frame["date"]) > end).any():
        raise ValueError(f"pack contains rows after {end.date().isoformat()}")
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    audit_path = root / "pack_audit.json"
    if audit_path.exists():
        audit = PackAudit(**json.loads(audit_path.read_text(encoding="utf-8")))
    else:
        audit = PackAudit(
            source_root="pack", output_root=str(root),
            data_start=str(frame["date"].min().date()), data_end=end.date().isoformat(),
            rows=int(len(frame)), symbols=int(frame["symbol"].nunique()), locked_rows=0,
            survivorship_free=False, metadata_is_bitemporal=False,
            dataset_hash=_hash_frame(frame),
        )
    return ResearchPanel(frame.sort_values(["date", "symbol"]).reset_index(drop=True), audit)

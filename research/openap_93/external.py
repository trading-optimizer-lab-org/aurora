"""Immutable downloads and parsers for no-key public OpenAP inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json

import pandas as pd
import requests


@dataclass(frozen=True)
class DownloadSpec:
    source_id: str
    dataset_id: str
    url: str
    filename: str
    parser: str


PUBLIC_INPUTS: tuple[DownloadSpec, ...] = (
    DownloadSpec(
        "kenneth_french", "ff3_daily",
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip",
        "ff3_daily.zip", "french_zip",
    ),
    DownloadSpec(
        "kenneth_french", "ff3_monthly",
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
        "ff3_monthly.zip", "french_zip",
    ),
    DownloadSpec(
        "pastor_stambaugh", "liquidity_monthly",
        "https://faculty.chicagobooth.edu/-/media/faculty/lubos-pastor/data/liq_data_1962_2024.txt",
        "pastor_stambaugh_liquidity.txt", "pastor_stambaugh",
    ),
    DownloadSpec(
        "cboe_public", "vix_daily",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        "vix_history.csv", "cboe_vix",
    ),
    DownloadSpec(
        "fred_public_csv", "gnp_deflator",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GNPDEF",
        "gnpdef.csv", "fred_csv",
    ),
    DownloadSpec(
        "openap_reference", "signal_doc",
        "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/8db892442c2c3a3779b0f1eac4370d3655be15a1/SignalDoc.csv",
        "SignalDoc.csv", "csv",
    ),
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def download_public_inputs(output_dir: str | Path, *, timeout: int = 120) -> list[dict[str, object]]:
    """Download all immutable public inputs and return a hash manifest."""

    output = Path(output_dir)
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    headers = {
        "User-Agent": "Aurora-OpenAP-Research/1.0 https://github.com/trading-optimizer-lab-org/aurora",
        "Accept": "text/csv,text/plain,application/zip,application/octet-stream,*/*",
    }
    with requests.Session() as session:
        for spec in PUBLIC_INPUTS:
            target = raw / spec.filename
            response = session.get(spec.url, headers=headers, timeout=timeout)
            response.raise_for_status()
            content = response.content
            if not content:
                raise RuntimeError(f"{spec.dataset_id}: empty public download")
            target.write_bytes(content)
            rows.append({
                **asdict(spec),
                "path": str(target),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_type": response.headers.get("Content-Type", ""),
                "retrieved_at": utcnow(),
                "status_code": response.status_code,
            })
    (output / "public_inputs_manifest.json").write_text(
        json.dumps({"downloads": rows}, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return rows


def parse_french_zip(path: str | Path, *, daily: bool) -> pd.DataFrame:
    """Parse Kenneth French FF3 daily or monthly ZIP into decimal returns."""

    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected one French CSV, found {names}")
        text = archive.read(names[0]).decode("utf-8", errors="replace")
    lines = text.splitlines()
    width = 8 if daily else 6
    data_lines = [
        line for line in lines
        if line.strip() and line.split(",", 1)[0].strip().isdigit()
        and len(line.split(",", 1)[0].strip()) == width
    ]
    if not data_lines:
        raise ValueError("No dated rows in Kenneth French archive")
    frame = pd.read_csv(
        StringIO("date,Mkt-RF,SMB,HML,RF\n" + "\n".join(data_lines)),
        dtype={"date": str},
    )
    frame.columns = [column.strip().lower().replace("-", "") for column in frame.columns]
    frame["date"] = pd.to_datetime(
        frame["date"], format="%Y%m%d" if daily else "%Y%m", errors="raise"
    )
    for column in ("mktrf", "smb", "hml", "rf"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce") / 100.0
    return frame.dropna(subset=["date", "mktrf", "smb", "hml", "rf"]).sort_values("date")


def parse_pastor_stambaugh(path: str | Path) -> pd.DataFrame:
    """Parse official monthly aggregate liquidity innovations."""

    rows: list[tuple[str, float, float, float]] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        parts = stripped.split()
        if len(parts) != 4 or len(parts[0]) != 6 or not parts[0].isdigit():
            continue
        rows.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3])))
    if not rows:
        raise ValueError("No Pastor-Stambaugh observations parsed")
    frame = pd.DataFrame(rows, columns=["yyyymm", "aggregate_liquidity", "ps_innovation", "traded_liquidity"])
    frame["date"] = pd.to_datetime(frame["yyyymm"], format="%Y%m")
    return frame.drop(columns="yyyymm").sort_values("date")


def parse_cboe_vix(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    normalized = {column: column.strip().lower() for column in frame.columns}
    frame = frame.rename(columns=normalized)
    date_column = next((column for column in frame.columns if column in {"date", "trade date"}), None)
    close_column = next((column for column in frame.columns if column in {"close", "vix close"}), None)
    if date_column is None or close_column is None:
        raise ValueError(f"Unexpected Cboe VIX schema: {list(frame.columns)}")
    result = pd.DataFrame({
        "date": pd.to_datetime(frame[date_column], errors="coerce"),
        "vix_close": pd.to_numeric(frame[close_column], errors="coerce"),
    }).dropna()
    result["vix_change"] = result["vix_close"].diff()
    return result.sort_values("date")


def parse_fred_csv(path: str | Path, *, value_column: str) -> pd.DataFrame:
    """Parse a public FRED graph CSV without assuming its date header spelling."""

    frame = pd.read_csv(path)
    normalized = {column: column.strip().lower() for column in frame.columns}
    frame = frame.rename(columns=normalized)
    date_column = next(
        (column for column in frame.columns if column in {"date", "observation_date"}),
        None,
    )
    normalized_value = value_column.lower()
    if date_column is None or normalized_value not in frame.columns:
        raise ValueError(f"Unexpected FRED schema: {list(frame.columns)}")
    result = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[date_column], errors="coerce"),
            normalized_value: pd.to_numeric(frame[normalized_value], errors="coerce"),
        }
    ).dropna()
    return result.sort_values("date")


def normalize_public_inputs(raw_dir: str | Path, output_dir: str | Path) -> dict[str, int]:
    """Normalize public inputs to Parquet and return row counts."""

    raw = Path(raw_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "ff3_daily": parse_french_zip(raw / "ff3_daily.zip", daily=True),
        "ff3_monthly": parse_french_zip(raw / "ff3_monthly.zip", daily=False),
        "liquidity_monthly": parse_pastor_stambaugh(raw / "pastor_stambaugh_liquidity.txt"),
        "vix_daily": parse_cboe_vix(raw / "vix_history.csv"),
        "gnp_deflator": parse_fred_csv(raw / "gnpdef.csv", value_column="GNPDEF"),
        "signal_doc": pd.read_csv(raw / "SignalDoc.csv"),
    }
    counts: dict[str, int] = {}
    for dataset_id, frame in frames.items():
        if frame.empty:
            raise RuntimeError(f"{dataset_id}: normalized dataset is empty")
        frame.to_parquet(output / f"{dataset_id}.parquet", index=False, compression="zstd")
        counts[dataset_id] = len(frame)
    (output / "normalized_summary.json").write_text(
        json.dumps({"rows": counts, "created_at": utcnow()}, indent=2), encoding="utf-8"
    )
    return counts

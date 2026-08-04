"""Immutable downloads and parsers for no-key public OpenAP inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import StringIO
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import re
import time

import pandas as pd
import requests

from .http import public_headers
from .institutional_pipeline import map_cusips_openfigi, parse_13f_archives


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
        "kenneth_french", "ff48_sic_codes",
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/Siccodes48.zip",
        "siccodes48.zip", "french_sic_zip",
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
    DownloadSpec(
        "openap_reference", "firm_characteristics_latest",
        "https://drive.usercontent.google.com/download?id=1avFIMjz_7LoF3p3nO26eqLW5KdRTOdhW&export=download&confirm=t",
        "signed_predictors_dl_wide.zip", "openap_reference_zip",
    ),
    DownloadSpec(
        "sec_13f", "sec_13f_2026_march_may",
        "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip",
        "sec_13f_2026_march_may.zip", "sec_13f_zip",
    ),
    DownloadSpec(
        "sec_13f", "sec_13f_2025_december_2026_february",
        "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01dec2025-28feb2026_form13f.zip",
        "sec_13f_2025_december_2026_february.zip", "sec_13f_zip",
    ),
    DownloadSpec(
        "sec_13f", "sec_13f_2025_september_november",
        "https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01sep2025-30nov2025_form13f.zip",
        "sec_13f_2025_september_november.zip", "sec_13f_zip",
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
    with requests.Session() as session:
        for spec in PUBLIC_INPUTS:
            headers = public_headers(sec=spec.source_id == "sec_13f")
            target = raw / spec.filename
            temporary = target.with_suffix(target.suffix + ".partial")
            last_error: Exception | None = None
            digest = hashlib.sha256()
            byte_count = 0
            content_type = ""
            status_code = 0
            for attempt in range(4):
                temporary.unlink(missing_ok=True)
                digest = hashlib.sha256()
                byte_count = 0
                try:
                    with session.get(
                        spec.url,
                        headers=headers,
                        timeout=(30, timeout),
                        stream=True,
                    ) as response:
                        response.raise_for_status()
                        content_type = response.headers.get("Content-Type", "")
                        status_code = response.status_code
                        with temporary.open("wb") as handle:
                            for block in response.iter_content(chunk_size=8 * 1024 * 1024):
                                if not block:
                                    continue
                                handle.write(block)
                                digest.update(block)
                                byte_count += len(block)
                    if byte_count == 0:
                        raise RuntimeError(f"{spec.dataset_id}: empty public download")
                    temporary.replace(target)
                    last_error = None
                    break
                except (requests.RequestException, OSError, RuntimeError) as exc:
                    temporary.unlink(missing_ok=True)
                    last_error = exc
                    if attempt < 3:
                        time.sleep(2.0**attempt)
            if last_error is not None:
                raise RuntimeError(
                    f"{spec.dataset_id}: public download failed after four attempts"
                ) from last_error
            rows.append({
                **asdict(spec),
                "path": str(target),
                "bytes": byte_count,
                "sha256": digest.hexdigest(),
                "content_type": content_type,
                "retrieved_at": utcnow(),
                "status_code": status_code,
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


def parse_ff48_sic_zip(path: str | Path) -> pd.DataFrame:
    """Parse Kenneth French's official FF48 SIC interval definitions."""

    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if len(names) != 1:
            raise ValueError(f"Expected one FF48 text file, found {names}")
        text = archive.read(names[0]).decode("cp1252", errors="replace")

    industry_pattern = re.compile(r"^\s*(\d{1,2})\s+([A-Za-z0-9]+)\s+(.+?)\s*$")
    range_pattern = re.compile(r"^\s*(\d{4})-(\d{4})\s*(.*?)\s*$")
    current: tuple[int, str, str] | None = None
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        industry_match = industry_pattern.match(line)
        if industry_match:
            current = (
                int(industry_match.group(1)),
                industry_match.group(2),
                industry_match.group(3).strip(),
            )
            continue
        range_match = range_pattern.match(line)
        if range_match and current is not None:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                raise ValueError(f"Invalid FF48 SIC range: {start}-{end}")
            rows.append(
                {
                    "ff48": current[0],
                    "industry_abbrev": current[1],
                    "industry_name": current[2],
                    "sic_start": start,
                    "sic_end": end,
                    "range_description": range_match.group(3).strip(),
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty or set(frame["ff48"].unique()) != set(range(1, 49)):
        raise ValueError("Official FF48 archive did not yield all 48 industries")
    expanded = pd.Series(
        [
            sic
            for row in frame.itertuples(index=False)
            for sic in range(int(row.sic_start), int(row.sic_end) + 1)
        ],
        dtype="int64",
    )
    if expanded.duplicated().any():
        raise ValueError("Official FF48 SIC intervals overlap")
    return frame.sort_values(["ff48", "sic_start", "sic_end"]).reset_index(drop=True)


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


def parse_openap_reference_zip(
    path: str | Path,
    *,
    sample_rows: int = 2_000,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Read a bounded schema sample from the latest official firm-level archive.

    The official file identifies companies only by CRSP ``permno``.  The sample
    is retained as stale validation evidence, never as current signal data.
    """

    with ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected one OpenAP reference CSV, found {names}")
        info = archive.getinfo(names[0])
        with archive.open(info) as raw_handle:
            with TextIOWrapper(raw_handle, encoding="utf-8-sig", errors="replace") as handle:
                frame = pd.read_csv(handle, nrows=sample_rows, low_memory=False)
    required = {"permno", "yyyymm"}
    if frame.empty or not required <= set(frame.columns):
        raise ValueError(
            "OpenAP firm-level reference must contain permno and yyyymm"
        )
    signal_columns = [column for column in frame.columns if column not in required]
    if not signal_columns:
        raise ValueError("OpenAP firm-level reference has no signal columns")
    frame["permno"] = pd.to_numeric(frame["permno"], errors="coerce").astype("Int64")
    frame["yyyymm"] = pd.to_numeric(frame["yyyymm"], errors="coerce").astype("Int64")
    metadata: dict[str, object] = {
        "archive_entry": info.filename,
        "archive_entry_uncompressed_bytes": info.file_size,
        "archive_entry_compressed_bytes": info.compress_size,
        "sample_rows": len(frame),
        "column_count": len(frame.columns),
        "signal_column_count": len(signal_columns),
        "identifier_columns": ["permno", "yyyymm"],
        "declared_latest_period": "2024-12",
        "reference_only": True,
        "current_signal_source": False,
        "identity_crosswalk_required": "CRSP permno to current CIK/ticker",
    }
    return frame, metadata


def normalize_public_inputs(
    raw_dir: str | Path,
    output_dir: str | Path,
    *,
    openfigi_http_post=None,
    openfigi_sleep=None,
) -> dict[str, int]:
    """Normalize public inputs to Parquet and return row counts."""

    raw = Path(raw_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    openap_sample, openap_metadata = parse_openap_reference_zip(
        raw / "signed_predictors_dl_wide.zip"
    )
    institutional_filings, institutional_holdings, institutional_exclusions = (
        parse_13f_archives(
            [
                raw / "sec_13f_2026_march_may.zip",
                raw / "sec_13f_2025_december_2026_february.zip",
                raw / "sec_13f_2025_september_november.zip",
            ]
        )
    )
    mapping_checkpoint = output / "openfigi_cusip_map.partial.jsonl"
    mapping_inputs = institutional_holdings["cusip"].dropna().astype(str)
    if openfigi_sleep is None:
        openfigi_cusip_map = map_cusips_openfigi(
            mapping_inputs,
            output_checkpoint=mapping_checkpoint,
            http_post=openfigi_http_post,
        )
    else:
        openfigi_cusip_map = map_cusips_openfigi(
            mapping_inputs,
            output_checkpoint=mapping_checkpoint,
            http_post=openfigi_http_post,
            sleep=openfigi_sleep,
        )
    frames = {
        "ff3_daily": parse_french_zip(raw / "ff3_daily.zip", daily=True),
        "ff3_monthly": parse_french_zip(raw / "ff3_monthly.zip", daily=False),
        "ff48_sic_codes": parse_ff48_sic_zip(raw / "siccodes48.zip"),
        "liquidity_monthly": parse_pastor_stambaugh(raw / "pastor_stambaugh_liquidity.txt"),
        "vix_daily": parse_cboe_vix(raw / "vix_history.csv"),
        "gnp_deflator": parse_fred_csv(raw / "gnpdef.csv", value_column="GNPDEF"),
        "signal_doc": pd.read_csv(raw / "SignalDoc.csv"),
        "openap_reference_sample": openap_sample,
        "sec_13f_filings": institutional_filings,
        "sec_13f_holdings": institutional_holdings,
        "sec_13f_exclusions": institutional_exclusions,
        "openfigi_cusip_map": openfigi_cusip_map,
    }
    counts: dict[str, int] = {}
    for dataset_id, frame in frames.items():
        if frame.empty and dataset_id != "sec_13f_exclusions":
            raise RuntimeError(f"{dataset_id}: normalized dataset is empty")
        frame.to_parquet(output / f"{dataset_id}.parquet", index=False, compression="zstd")
        counts[dataset_id] = len(frame)
    if not openfigi_cusip_map["mapping_status"].eq("request_failed").any():
        mapping_checkpoint.unlink(missing_ok=True)
    (output / "normalized_summary.json").write_text(
        json.dumps(
            {
                "rows": counts,
                "created_at": utcnow(),
                "openfigi_mapping_complete": bool(
                    not openfigi_cusip_map["mapping_status"]
                    .eq("request_failed")
                    .any()
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "openap_reference_metadata.json").write_text(
        json.dumps(openap_metadata, indent=2, ensure_ascii=True), encoding="utf-8"
    )
    return counts

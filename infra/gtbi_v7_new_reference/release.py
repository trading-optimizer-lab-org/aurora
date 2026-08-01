"""Verify the frozen release and create the locked-free V7 execution pack.

The release contains rows after the historical boundary.  This module never
exposes those rows to an evaluator: it extracts only the four required source
files, verifies every byte in the complete TAR stream, and writes a new pack
whose maximum date is 2020-12-31.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.frozen_data_lake import (
    COPY_CHUNK_SIZE,
    MANIFEST_DOMAIN,
    MANIFEST_FILENAME,
    MANIFEST_MEMBER,
    RECEIPT_DOMAIN,
    RECEIPT_FILENAME,
)
from scripts.run_gtbi_fast_strict_worker import create_data_pack_manifest

RELEASE_REPOSITORY = "trading-optimizer-lab-org/aurora-v7-assets"
RELEASE_ID = 362286563
RELEASE_TAG = "gtbi-v7-frozen-data-lake-v1"
ARCHIVE_SHA256 = "sha256:5a77dc20ffcc8769e0dabe38811d50664f6f3ab6d8ac262c17d39dc7b86070b5"
ARCHIVE_SIZE_BYTES = 3_252_295_680
LOCKED_START = "2021-01-01"
SCIENTIFIC_CUTOFF = "2020-12-31"
MIN_MARKET_CAP_USD = 2_000_000_000

REQUIRED_SOURCE_PATHS = (
    "benchmarks/SPY.parquet",
    "exports/all_prices.parquet",
    "metadata/company_metadata.parquet",
    "universe/us_stock_like_universe.parquet",
)


class FrozenReleaseError(RuntimeError):
    """Raised when release or historical-view validation fails closed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK_SIZE):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(str(value))
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in str(value)
        or "\x00" in str(value)
    ):
        raise FrozenReleaseError(f"unsafe release path: {value}")
    return Path(*pure.parts)


def _load_canonical(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FrozenReleaseError(f"JSON object expected: {path}")
    if Path(path).read_bytes() != canonical_bytes(value) + b"\n":
        raise FrozenReleaseError(f"release metadata is not canonical JSON: {path.name}")
    return dict(value)


def _validate_metadata(manifest: dict[str, Any], receipt: dict[str, Any]) -> None:
    expected_manifest = domain_digest(
        MANIFEST_DOMAIN,
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    expected_receipt = domain_digest(
        RECEIPT_DOMAIN,
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    if manifest.get("manifest_digest") != expected_manifest:
        raise FrozenReleaseError("frozen manifest digest mismatch")
    if receipt.get("receipt_digest") != expected_receipt:
        raise FrozenReleaseError("frozen receipt digest mismatch")
    required = {
        "release_tag": RELEASE_TAG,
        "archive_sha256": ARCHIVE_SHA256,
        "archive_size_bytes": ARCHIVE_SIZE_BYTES,
        "locked_start": LOCKED_START,
        "scientific_cutoff": SCIENTIFIC_CUTOFF,
        "provider_download_performed": False,
    }
    for field, expected in required.items():
        if receipt.get(field) != expected:
            raise FrozenReleaseError(f"release receipt {field} mismatch")
    if manifest.get("locked_start") != LOCKED_START or manifest.get("scientific_cutoff") != SCIENTIFIC_CUTOFF:
        raise FrozenReleaseError("frozen manifest historical boundary mismatch")
    if receipt.get("manifest_digest") != manifest.get("manifest_digest"):
        raise FrozenReleaseError("release receipt and manifest disagree")
    rows = list(manifest.get("files") or [])
    paths = [str(row.get("path") or "") for row in rows]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise FrozenReleaseError("release manifest paths are not unique and sorted")
    if int(manifest.get("source_file_count", -1)) != len(rows):
        raise FrozenReleaseError("release manifest file count mismatch")
    if not set(REQUIRED_SOURCE_PATHS).issubset(paths):
        raise FrozenReleaseError("release does not contain every V7 execution source")


class _VerifiedPartsReader(io.RawIOBase):
    """Concatenate and verify split assets while TAR consumes them once."""

    def __init__(self, root: Path, receipt: dict[str, Any]) -> None:
        self._root = Path(root)
        self._expected = list(receipt.get("parts") or [])
        if int(receipt.get("part_count", -1)) != len(self._expected) or not self._expected:
            raise FrozenReleaseError("release part count mismatch")
        self._index = 0
        self._current: BinaryIO | None = None
        self._current_digest = hashlib.sha256()
        self._current_size = 0
        self._archive_digest = hashlib.sha256()
        self._archive_size = 0
        self._expected_archive_digest = str(receipt["archive_sha256"])
        self._expected_archive_size = int(receipt["archive_size_bytes"])
        self._verified = False

    def readable(self) -> bool:
        return True

    def _open_next(self) -> bool:
        if self._index >= len(self._expected):
            self._finish_archive()
            return False
        row = self._expected[self._index]
        if int(row.get("index", -1)) != self._index + 1:
            raise FrozenReleaseError("release part indices are not contiguous")
        path = self._root / str(row.get("name") or "")
        if not path.is_file():
            raise FrozenReleaseError(f"release part missing: {path.name}")
        self._current = path.open("rb")
        self._current_digest = hashlib.sha256()
        self._current_size = 0
        return True

    def _finish_part(self) -> None:
        row = self._expected[self._index]
        assert self._current is not None
        self._current.close()
        self._current = None
        if self._current_size != int(row.get("size_bytes", -1)):
            raise FrozenReleaseError(f"release part size mismatch: {row.get('name')}")
        if "sha256:" + self._current_digest.hexdigest() != str(row.get("sha256") or ""):
            raise FrozenReleaseError(f"release part digest mismatch: {row.get('name')}")
        self._index += 1

    def _finish_archive(self) -> None:
        if self._verified:
            return
        if self._archive_size != self._expected_archive_size:
            raise FrozenReleaseError("release archive size mismatch")
        if "sha256:" + self._archive_digest.hexdigest() != self._expected_archive_digest:
            raise FrozenReleaseError("release archive digest mismatch")
        self._verified = True

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer)
        while True:
            if self._current is None and not self._open_next():
                return 0
            assert self._current is not None
            data = self._current.read(len(view))
            if not data:
                self._finish_part()
                continue
            self._current_digest.update(data)
            self._archive_digest.update(data)
            self._current_size += len(data)
            self._archive_size += len(data)
            view[: len(data)] = data
            return len(data)

    def drain_and_verify(self) -> None:
        buffer = bytearray(COPY_CHUNK_SIZE)
        while self.readinto(buffer):
            pass
        self._finish_archive()

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
            self._current = None
        super().close()


def verify_and_extract_required_release_files(
    *,
    release_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Verify all release bytes and atomically extract only required files."""
    root = Path(release_root)
    output = Path(output_dir)
    if output.exists():
        raise FrozenReleaseError(f"output already exists: {output}")
    manifest_path = root / MANIFEST_FILENAME
    receipt_path = root / RECEIPT_FILENAME
    manifest = _load_canonical(manifest_path)
    receipt = _load_canonical(receipt_path)
    _validate_metadata(manifest, receipt)
    expected = {str(row["path"]): dict(row) for row in manifest["files"]}
    observed: set[str] = set()
    embedded_manifest: dict[str, Any] | None = None
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    selected_records: list[dict[str, Any]] = []
    reader = _VerifiedPartsReader(root, receipt)
    try:
        with tarfile.open(fileobj=reader, mode="r|", bufsize=COPY_CHUNK_SIZE) as archive:
            for member in archive:
                if not member.isfile():
                    raise FrozenReleaseError(f"non-file TAR member: {member.name}")
                if member.name == MANIFEST_MEMBER:
                    source = archive.extractfile(member)
                    if source is None:
                        raise FrozenReleaseError("embedded manifest is unreadable")
                    embedded_manifest = json.load(source)
                    continue
                row = expected.get(member.name)
                if row is None:
                    raise FrozenReleaseError(f"unexpected TAR member: {member.name}")
                relative = _safe_relative(member.name)
                source = archive.extractfile(member)
                if source is None:
                    raise FrozenReleaseError(f"unreadable TAR member: {member.name}")
                destination = temporary / relative if member.name in REQUIRED_SOURCE_PATHS else None
                if destination is not None:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    sink: BinaryIO | None = destination.open("xb")
                else:
                    sink = None
                digest = hashlib.sha256()
                size = 0
                try:
                    while chunk := source.read(COPY_CHUNK_SIZE):
                        digest.update(chunk)
                        size += len(chunk)
                        if sink is not None:
                            sink.write(chunk)
                finally:
                    if sink is not None:
                        sink.close()
                actual_digest = "sha256:" + digest.hexdigest()
                if size != int(row["size_bytes"]) or actual_digest != str(row["sha256"]):
                    raise FrozenReleaseError(f"TAR member digest mismatch: {member.name}")
                observed.add(member.name)
                if destination is not None:
                    selected_records.append(
                        {"path": member.name, "size_bytes": size, "sha256": actual_digest}
                    )
        reader.drain_and_verify()
        if observed != set(expected):
            raise FrozenReleaseError("TAR member coverage mismatch")
        if embedded_manifest != manifest:
            raise FrozenReleaseError("embedded manifest mismatch")
        if {row["path"] for row in selected_records} != set(REQUIRED_SOURCE_PATHS):
            raise FrozenReleaseError("required source extraction is incomplete")
        verification = {
            "schema_version": "gtbi_v7_new_reference_release_extraction_v1",
            "repository": RELEASE_REPOSITORY,
            "release_id": RELEASE_ID,
            "release_tag": RELEASE_TAG,
            "archive_sha256": ARCHIVE_SHA256,
            "archive_size_bytes": ARCHIVE_SIZE_BYTES,
            "manifest_digest": manifest["manifest_digest"],
            "source_file_count_verified": len(observed),
            "selected_files": sorted(selected_records, key=lambda row: row["path"]),
            "locked_rows_present_in_source": True,
            "locked_data_accessed_by_evaluator": False,
            "locked_start": LOCKED_START,
            "scientific_cutoff": SCIENTIFIC_CUTOFF,
            "verified": True,
        }
        verification["verification_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(verification)).hexdigest()
        (temporary / "release_verification.json").write_bytes(canonical_bytes(verification) + b"\n")
        temporary.replace(output)
        return verification
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        reader.close()


def _symbol_column(frame: pd.DataFrame) -> str:
    for column in ("symbol", "canonical_symbol", "yfinance_symbol"):
        if column in frame.columns:
            return column
    raise FrozenReleaseError("metadata has no symbol column")


def _eligible_symbols(metadata_path: Path, universe_path: Path, min_market_cap: float) -> list[str]:
    metadata = pd.read_parquet(metadata_path)
    universe = pd.read_parquet(universe_path)
    if "market_cap" not in metadata.columns:
        raise FrozenReleaseError("metadata has no market_cap")
    metadata_symbol = _symbol_column(metadata)
    universe_symbol = _symbol_column(universe)
    cap = pd.to_numeric(metadata["market_cap"], errors="coerce")
    cap_symbols = set(metadata.loc[cap >= float(min_market_cap), metadata_symbol].dropna().astype(str))
    universe_symbols = set(universe[universe_symbol].dropna().astype(str))
    return sorted((cap_symbols & universe_symbols) - {"SPY"})


def _write_filtered_prices(source: Path, destination: Path, symbols: list[str]) -> tuple[int, list[str]]:
    if not symbols:
        raise FrozenReleaseError("historical price view is empty")
    dataset = ds.dataset(source, format="parquet")
    schema_names = set(dataset.schema.names)
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    if not required.issubset(schema_names):
        raise FrozenReleaseError(f"price export missing columns: {sorted(required - schema_names)}")
    cutoff = pa.scalar(pd.Timestamp(LOCKED_START).date(), type=pa.date32())
    expression = (ds.field("date") < cutoff) & ds.field("symbol").isin(symbols)
    table = dataset.to_table(filter=expression)
    if table.num_rows == 0:
        raise FrozenReleaseError("historical price view is empty")
    counts = table.group_by("symbol").aggregate([("date", "count")])
    count_frame = counts.to_pandas()
    retained = sorted(
        count_frame.loc[count_frame["date_count"] >= 260, "symbol"].dropna().astype(str).tolist()
    )
    if not retained:
        raise FrozenReleaseError("no symbol has the minimum historical rows")
    table = table.filter(pc.is_in(table["symbol"], value_set=pa.array(retained)))
    table = table.sort_by([("symbol", "ascending"), ("date", "ascending")])
    maximum = pc.max(table["date"]).as_py()
    if maximum is None or str(maximum) > SCIENTIFIC_CUTOFF:
        raise FrozenReleaseError("historical prices expose locked rows")
    pq.write_table(table, destination, compression="zstd", use_dictionary=True)
    return int(table.num_rows), retained


def _write_filtered_benchmark(source: Path, destination: Path) -> int:
    table = pq.read_table(source)
    if "date" not in table.column_names:
        raise FrozenReleaseError("benchmark has no date column")
    date_type = table.schema.field("date").type
    if pa.types.is_timestamp(date_type):
        cutoff = pa.scalar(pd.Timestamp(LOCKED_START), type=date_type)
    elif pa.types.is_date(date_type):
        cutoff = pa.scalar(pd.Timestamp(LOCKED_START).date(), type=date_type)
    else:
        dates = pc.strptime(table["date"], format="%Y-%m-%d", unit="ns", error_is_null=True)
        table = table.set_column(table.schema.get_field_index("date"), "date", dates)
        cutoff = pa.scalar(pd.Timestamp(LOCKED_START), type=dates.type)
    table = table.filter(pc.less(table["date"], cutoff)).sort_by([("date", "ascending")])
    if table.num_rows == 0:
        raise FrozenReleaseError("historical benchmark is empty")
    maximum = pc.max(table["date"]).as_py()
    if pd.Timestamp(maximum).date().isoformat() > SCIENTIFIC_CUTOFF:
        raise FrozenReleaseError("historical benchmark exposes locked rows")
    pq.write_table(table, destination, compression="zstd", use_dictionary=True)
    return int(table.num_rows)


def build_historical_execution_pack(
    *,
    extracted_root: Path,
    output_root: Path,
    min_market_cap: float = MIN_MARKET_CAP_USD,
) -> dict[str, Any]:
    """Create an immutable pre-2021 execution pack from verified release files."""
    source = Path(extracted_root)
    output = Path(output_root)
    if output.exists():
        raise FrozenReleaseError(f"output already exists: {output}")
    release_verification = _load_canonical(source / "release_verification.json")
    if release_verification.get("verified") is not True:
        raise FrozenReleaseError("release extraction is not verified")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    pack = temporary / "data-pack"
    pack.mkdir()
    try:
        symbols = _eligible_symbols(
            source / "metadata/company_metadata.parquet",
            source / "universe/us_stock_like_universe.parquet",
            float(min_market_cap),
        )
        price_rows, retained_symbols = _write_filtered_prices(
            source / "exports/all_prices.parquet",
            pack / "prices.parquet",
            symbols,
        )
        benchmark_rows = _write_filtered_benchmark(
            source / "benchmarks/SPY.parquet",
            pack / "benchmark.parquet",
        )
        symbol_digest = "sha256:" + hashlib.sha256(
            ("\n".join(retained_symbols) + "\n").encode("utf-8")
        ).hexdigest()
        universe_identity = f"gtbi-v7-static-post-period-cap-{int(min_market_cap)}-{symbol_digest[7:23]}"
        manifest = create_data_pack_manifest(
            data_pack_root=pack,
            output_path=temporary / "data_manifest.json",
            source_data_run_id=f"{RELEASE_REPOSITORY}:release:{RELEASE_ID}",
            source_artifact_name=RELEASE_TAG,
            universe_identity=universe_identity,
            train_end="2010-12-31",
            validation_start="2011-01-01",
            validation_end=SCIENTIFIC_CUTOFF,
            locked_start=LOCKED_START,
            min_market_cap=float(min_market_cap),
        )
        contract = {
            "schema_version": "gtbi_v7_new_reference_data_contract_v1",
            "campaign_id": "gtbi_v7_new_reference_v1",
            "data_pack_identity": manifest["data_pack_identity"],
            "release_verification_digest": release_verification["verification_digest"],
            "release_archive_sha256": ARCHIVE_SHA256,
            "release_manifest_digest": release_verification["manifest_digest"],
            "universe_identity": universe_identity,
            "eligible_symbol_count_before_min_rows": len(symbols),
            "retained_symbol_count": len(retained_symbols),
            "retained_symbol_digest": symbol_digest,
            "price_rows": price_rows,
            "benchmark_rows": benchmark_rows,
            "survivorship_biased": True,
            "point_in_time_universe": False,
            "retrospectively_adjusted_reference": True,
            "locked_start": LOCKED_START,
            "scientific_cutoff": SCIENTIFIC_CUTOFF,
            "locked_rows_in_execution_pack": False,
            "locked_data_accessed_by_evaluator": False,
            "provider_download_performed": False,
        }
        contract["contract_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(contract)).hexdigest()
        manifest["v7_data_contract"] = contract
        (temporary / "data_manifest.json").write_bytes(canonical_bytes(manifest) + b"\n")
        (temporary / "data_contract.json").write_bytes(canonical_bytes(contract) + b"\n")
        output_identity = {
            "data_pack_identity": manifest["data_pack_identity"],
            "universe_identity": universe_identity,
            "data_contract_digest": contract["contract_digest"],
            "price_rows": price_rows,
            "benchmark_rows": benchmark_rows,
            "retained_symbol_count": len(retained_symbols),
        }
        temporary.replace(output)
        return output_identity
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


__all__ = [
    "ARCHIVE_SHA256",
    "ARCHIVE_SIZE_BYTES",
    "FrozenReleaseError",
    "LOCKED_START",
    "MIN_MARKET_CAP_USD",
    "RELEASE_ID",
    "RELEASE_REPOSITORY",
    "RELEASE_TAG",
    "SCIENTIFIC_CUTOFF",
    "build_historical_execution_pack",
    "verify_and_extract_required_release_files",
]

"""Selective recovery helpers for large GitHub Actions ZIP artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from hashlib import sha256
from io import BytesIO, RawIOBase
from pathlib import Path
from typing import Any
import json
import re
from zipfile import ZipFile

import pandas as pd


INSTITUTIONAL_RECOVERY_MEMBERS = (
    "public_inputs/normalized/sec_13f_filings.parquet",
    "public_inputs/normalized/sec_13f_holdings.parquet",
    "public_inputs/normalized/openfigi_cusip_map.parquet",
    "run_manifest.json",
)
MARKET_SECURITY_MASTER_RECOVERY_MEMBERS = (
    "security_master.parquet",
    "execution_summary.json",
    "source_manifest.csv",
)
SEC_TICKER_EXCHANGE_URL = (
    "https://www.sec.gov/files/company_tickers_exchange.json"
)
_MARKET_SECURITY_MASTER_REQUIRED_COLUMNS = {
    "security_id",
    "symbol",
    "cik",
    "exchange_sec",
    "eligible_common_stock",
    "issuer_primary_security",
    "issuer_share_class_count",
    "ranking_eligible",
    "source_sec",
    "retrieved_at_sec",
}


class HttpRangeReader(RawIOBase):
    """Expose an exact byte-range callback as a seekable binary reader."""

    def __init__(
        self,
        size: int,
        fetch_range: Callable[[int, int], bytes],
    ) -> None:
        super().__init__()
        if size < 0:
            raise ValueError("range reader size cannot be negative")
        self._size = int(size)
        self._fetch_range = fetch_range
        self._position = 0
        self.range_requests = 0
        self.bytes_fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            position = offset
        elif whence == 1:
            position = self._position + offset
        elif whence == 2:
            position = self._size + offset
        else:
            raise ValueError(f"unsupported seek mode: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self._position = int(position)
        return self._position

    def read(self, size: int = -1) -> bytes:
        if self._position >= self._size or size == 0:
            return b""
        start = self._position
        end = self._size - 1 if size is None or size < 0 else min(
            self._size - 1, start + size - 1
        )
        payload = self._fetch_range(start, end)
        self.range_requests += 1
        self.bytes_fetched += len(payload)
        expected = end - start + 1
        if len(payload) != expected:
            raise OSError(
                f"range response length mismatch: expected={expected}:actual={len(payload)}"
            )
        self._position += len(payload)
        return payload


def read_zip_members(
    reader: HttpRangeReader,
    member_names: Iterable[str],
) -> dict[str, bytes]:
    """Read exact ZIP members and reject missing or duplicate archive names."""

    requested = tuple(member_names)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("requested ZIP members must be unique and non-empty")
    with ZipFile(reader) as archive:
        names = archive.namelist()
        for member_name in requested:
            if names.count(member_name) != 1:
                raise ValueError(
                    f"expected one ZIP member {member_name}, found {names.count(member_name)}"
                )
        return {member_name: archive.read(member_name) for member_name in requested}


def inspect_zip_members(
    reader: HttpRangeReader,
    member_names: Iterable[str],
) -> dict[str, dict[str, int]]:
    """Inspect exact ZIP members before fetching their compressed payloads."""

    requested = tuple(member_names)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("requested ZIP members must be unique and non-empty")
    with ZipFile(reader) as archive:
        names = archive.namelist()
        inspected: dict[str, dict[str, int]] = {}
        for member_name in requested:
            if names.count(member_name) != 1:
                raise ValueError(
                    f"expected one ZIP member {member_name}, found {names.count(member_name)}"
                )
            info = archive.getinfo(member_name)
            inspected[member_name] = {
                "file_size": int(info.file_size),
                "compress_size": int(info.compress_size),
                "crc": int(info.CRC),
            }
        return inspected


def _validate_failed_openap_93_source_run(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> tuple[int, str, int, str]:
    run_id = int(run.get("id", 0))
    head_sha = str(run.get("head_sha", ""))
    if (
        run_id <= 0
        or run.get("status") != "completed"
        or run.get("conclusion") != "failure"
        or re.fullmatch(r"[0-9a-fA-F]{40}", head_sha) is None
    ):
        raise ValueError("source run is not a completed failed run with a pinned SHA")

    pipeline_jobs = [job for job in jobs if job.get("name") == "full_pipeline"]
    if len(pipeline_jobs) != 1:
        raise ValueError("expected one full_pipeline source job")
    steps = {
        str(step.get("name", "")): str(step.get("conclusion", ""))
        for step in pipeline_jobs[0].get("steps", [])
    }
    required_successes = {
        "Verify mandatory deliverables and contracts",
        "Independently reopen and verify the complete artifact",
    }
    if any(steps.get(name) != "success" for name in required_successes):
        raise ValueError("source run lacks successful verified output steps")
    audit_step = "Build the canonical fail-closed 181-signal completion audit"
    if steps.get(audit_step) != "failure":
        raise ValueError("source run did not fail only at the later completion audit")

    artifact_id = int(artifact.get("id", 0))
    expected_name = f"openap-93-max-free-failed-output-{run_id}"
    if (
        artifact_id <= 0
        or artifact.get("name") != expected_name
        or artifact.get("expired") is not False
        or int(artifact.get("size_in_bytes", 0)) <= 0
    ):
        raise ValueError("source diagnostic artifact identity is invalid")
    return run_id, head_sha.lower(), artifact_id, expected_name


def validate_recovered_openap_93(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
    members: Mapping[str, bytes],
) -> dict[str, Any]:
    """Validate that a failed run contains previously verified OpenAP 93 outputs."""

    run_id, head_sha, artifact_id, expected_name = (
        _validate_failed_openap_93_source_run(run, jobs, artifact)
    )

    required_members = {
        "coverage_93.csv",
        "signals_93_current.csv",
        "run_manifest.json",
    }
    missing = required_members.difference(members)
    if missing:
        raise ValueError(f"recovered artifact members missing: {sorted(missing)}")
    try:
        manifest = json.loads(members["run_manifest.json"])
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recovered run manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("recovered run manifest must be a JSON object")
    output_hashes = manifest.get("output_hashes", {})
    if not isinstance(output_hashes, dict):
        raise ValueError("recovered run manifest output hashes are invalid")
    for member_name in ("coverage_93.csv", "signals_93_current.csv"):
        actual = sha256(members[member_name]).hexdigest()
        if output_hashes.get(member_name) != actual:
            raise ValueError(f"recovered member hash mismatch: {member_name}")
    if (
        manifest.get("input_signals") != 93
        or manifest.get("locked_opened") is not False
        or manifest.get("validation_used_for_selection") is not False
        or manifest.get("cost_eur") != 0
    ):
        raise ValueError("recovered OpenAP 93 safety contract is invalid")

    return {
        "source_run_id": run_id,
        "source_head_sha": head_sha.lower(),
        "source_artifact_id": artifact_id,
        "source_artifact_name": expected_name,
        "source_artifact_size_bytes": int(artifact["size_in_bytes"]),
        "input_signals": 93,
        "current_usable_signal_count": int(
            manifest.get("current_usable_signal_count", 0)
        ),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
        "recovered_hashes": {
            name: sha256(members[name]).hexdigest()
            for name in sorted(required_members)
        },
    }


def validate_recovered_openap_93_institutional_inputs(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
    members: Mapping[str, bytes],
) -> dict[str, Any]:
    """Validate selectively recovered SEC 13F and OpenFIGI normalized inputs."""

    run_id, head_sha, artifact_id, expected_name = (
        _validate_failed_openap_93_source_run(run, jobs, artifact)
    )
    missing = set(INSTITUTIONAL_RECOVERY_MEMBERS).difference(members)
    if missing:
        raise ValueError(f"recovered institutional members missing: {sorted(missing)}")
    try:
        manifest = json.loads(members["run_manifest.json"])
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recovered run manifest is invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("recovered run manifest must be a JSON object")
    if (
        manifest.get("input_signals") != 93
        or manifest.get("locked_opened") is not False
        or manifest.get("validation_used_for_selection") is not False
        or manifest.get("cost_eur") != 0
    ):
        raise ValueError("recovered OpenAP 93 safety contract is invalid")

    output_hashes = manifest.get("output_hashes", {})
    if not isinstance(output_hashes, dict):
        raise ValueError("recovered run manifest output hashes are invalid")
    data_members = INSTITUTIONAL_RECOVERY_MEMBERS[:-1]
    for member_name in data_members:
        actual = sha256(members[member_name]).hexdigest()
        if output_hashes.get(member_name) != actual:
            raise ValueError(f"recovered member hash mismatch: {member_name}")

    row_counts = manifest.get("public_input_row_counts", {})
    institutional = manifest.get("institutional_inputs", {})
    if not isinstance(row_counts, dict) or not isinstance(institutional, dict):
        raise ValueError("recovered institutional input metadata is invalid")
    filings = int(row_counts.get("sec_13f_filings", 0))
    holdings = int(row_counts.get("sec_13f_holdings", 0))
    mappings = int(row_counts.get("openfigi_cusip_map", 0))
    mapped_holdings = int(institutional.get("mapped_holding_rows", 0))
    latest_period = str(institutional.get("latest_report_period", ""))
    latest_filing = str(institutional.get("latest_filing_date", ""))
    if (
        min(filings, holdings, mappings, mapped_holdings) <= 0
        or mapped_holdings > holdings
        or not latest_period
        or not latest_filing
    ):
        raise ValueError("recovered institutional coverage metadata is invalid")

    return {
        "source_run_id": run_id,
        "source_head_sha": head_sha,
        "source_artifact_id": artifact_id,
        "source_artifact_name": expected_name,
        "source_artifact_size_bytes": int(artifact["size_in_bytes"]),
        "sec_13f_filing_rows": filings,
        "sec_13f_holding_rows": holdings,
        "openfigi_mapping_rows": mappings,
        "mapped_holding_rows": mapped_holdings,
        "latest_report_period": latest_period,
        "latest_filing_date": latest_filing,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
        "recovered_hashes": {
            name: sha256(members[name]).hexdigest() for name in sorted(data_members)
        },
    }


def validate_recovered_market_security_master(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
    members: Mapping[str, bytes],
) -> dict[str, Any]:
    """Validate the narrow identity input recovered from a successful base run."""

    run_id = int(run.get("id", 0))
    head_sha = str(run.get("head_sha", ""))
    if (
        run_id <= 0
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or re.fullmatch(r"[0-9a-fA-F]{40}", head_sha) is None
    ):
        raise ValueError("market source run is not completed successfully at a pinned SHA")

    merge_jobs = [job for job in jobs if job.get("name") == "merge"]
    if len(merge_jobs) != 1 or merge_jobs[0].get("conclusion") != "success":
        raise ValueError("expected one successful market source merge job")
    steps = {
        str(step.get("name", "")): str(step.get("conclusion", ""))
        for step in merge_jobs[0].get("steps", [])
    }
    required_steps = {
        "Merge lake and calculate current scores",
        "Validate final acceptance contract",
    }
    if any(steps.get(name) != "success" for name in required_steps):
        raise ValueError("market source run lacks successful acceptance steps")

    artifact_id = int(artifact.get("id", 0))
    expected_name = "openap-yfinance-sec-current-score-results"
    if (
        artifact_id <= 0
        or artifact.get("name") != expected_name
        or artifact.get("expired") is not False
        or int(artifact.get("size_in_bytes", 0)) <= 0
    ):
        raise ValueError("market source artifact identity is invalid")

    missing = set(MARKET_SECURITY_MASTER_RECOVERY_MEMBERS).difference(members)
    if missing:
        raise ValueError(f"recovered market identity members missing: {sorted(missing)}")
    try:
        summary = json.loads(members["execution_summary.json"])
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recovered market execution summary is invalid JSON") from exc
    if not isinstance(summary, dict):
        raise ValueError("recovered market execution summary must be a JSON object")
    if (
        int(summary.get("eligible_symbols", 0)) <= 1000
        or int(summary.get("security_master_rows", 0)) <= 0
        or summary.get("locked_opened") is not False
        or summary.get("backtest_enabled") is not False
        or summary.get("validation_used_for_selection") is not False
        or summary.get("partial") is not False
        or int(summary.get("database_contract_violations", -1)) != 0
    ):
        raise ValueError("recovered market execution safety contract is invalid")

    try:
        source_manifest = pd.read_csv(BytesIO(members["source_manifest.csv"]))
    except Exception as exc:
        raise ValueError("recovered market source manifest is not readable CSV") from exc
    required_source_columns = {
        "source",
        "source_url",
        "source_mode",
        "sha256",
        "role",
    }
    missing_source_columns = required_source_columns.difference(
        source_manifest.columns
    )
    if missing_source_columns:
        raise ValueError(
            "recovered market source manifest lacks columns: "
            f"{sorted(missing_source_columns)}"
        )
    identity_sources = source_manifest.loc[
        source_manifest["role"].astype(str).eq("ticker_cik_universe")
    ]
    if (
        len(identity_sources) != 1
        or str(identity_sources.iloc[0]["source"])
        != "company_tickers_exchange.json"
        or str(identity_sources.iloc[0]["source_url"])
        != SEC_TICKER_EXCHANGE_URL
        or str(identity_sources.iloc[0]["source_mode"]) != "sec_official_live"
        or re.fullmatch(
            r"[0-9a-fA-F]{64}", str(identity_sources.iloc[0]["sha256"])
        )
        is None
    ):
        raise ValueError(
            "recovered market source manifest lacks one official SEC ticker source"
        )

    try:
        security_master = pd.read_parquet(
            BytesIO(members["security_master.parquet"])
        )
    except Exception as exc:
        raise ValueError("recovered security master is not readable Parquet") from exc
    missing_columns = _MARKET_SECURITY_MASTER_REQUIRED_COLUMNS.difference(
        security_master.columns
    )
    if missing_columns:
        raise ValueError(
            f"recovered security master lacks columns: {sorted(missing_columns)}"
        )
    identity_retrieved_at = pd.to_datetime(
        security_master["retrieved_at_sec"], errors="coerce", utc=True
    )
    share_class_count = pd.to_numeric(
        security_master["issuer_share_class_count"], errors="coerce"
    )
    if (
        len(security_master) != int(summary["security_master_rows"])
        or security_master.empty
        or security_master["security_id"].isna().any()
        or security_master["security_id"].astype(str).str.strip().eq("").any()
        or security_master["security_id"].duplicated(keep=False).any()
        or not security_master["source_sec"].fillna("").astype(str).eq(
            "sec_company_tickers_exchange"
        ).all()
        or identity_retrieved_at.isna().any()
        or share_class_count.isna().any()
        or share_class_count.lt(1).any()
        or share_class_count.mod(1).ne(0).any()
    ):
        raise ValueError(
            "recovered security master row or SEC identity provenance contract is invalid"
        )

    return {
        "source_run_id": run_id,
        "source_head_sha": head_sha.lower(),
        "source_artifact_id": artifact_id,
        "source_artifact_name": expected_name,
        "source_artifact_size_bytes": int(artifact["size_in_bytes"]),
        "eligible_symbols": int(summary["eligible_symbols"]),
        "security_master_rows": int(summary["security_master_rows"]),
        "identity_source_url": SEC_TICKER_EXCHANGE_URL,
        "identity_source_mode": "sec_official_live",
        "identity_source_sha256": str(identity_sources.iloc[0]["sha256"]).lower(),
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": False,
        "database_contract_violations": 0,
        "recovered_hashes": {
            name: sha256(members[name]).hexdigest()
            for name in MARKET_SECURITY_MASTER_RECOVERY_MEMBERS
        },
    }


def _sha256_path(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_integer(value: Any) -> int | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric) or not float(numeric).is_integer():
        return None
    return int(numeric)


def validate_materialized_market_security_master_recovery(
    recovery_manifest_path: Path | str,
    security_master_path: Path | str,
    source_manifest_path: Path | str,
) -> dict[str, Any]:
    """Revalidate materialized market-identity files against recovery evidence."""

    recovery_path = Path(recovery_manifest_path)
    security_path = Path(security_master_path)
    source_path = Path(source_manifest_path)
    try:
        recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "market security-master recovery manifest is invalid"
        ) from exc
    if not isinstance(recovery, dict):
        raise ValueError(
            "market security-master recovery manifest must be an object"
        )
    recovered_hashes = recovery.get("recovered_hashes", {})
    if not isinstance(recovered_hashes, dict):
        raise ValueError("market security-master recovery hashes are invalid")
    source_run_id = _strict_integer(recovery.get("source_run_id"))
    source_artifact_id = _strict_integer(recovery.get("source_artifact_id"))
    database_contract_violations = _strict_integer(
        recovery.get("database_contract_violations")
    )
    eligible_symbols = _strict_integer(recovery.get("eligible_symbols"))
    security_master_rows = _strict_integer(recovery.get("security_master_rows"))
    source_head_sha = str(recovery.get("source_head_sha") or "")
    identity_hash = str(recovery.get("identity_source_sha256") or "")
    if (
        source_run_id is None
        or source_run_id <= 0
        or source_artifact_id is None
        or source_artifact_id <= 0
        or re.fullmatch(r"[0-9a-f]{40}", source_head_sha) is None
        or re.fullmatch(r"[0-9a-f]{64}", identity_hash) is None
        or recovery.get("source_artifact_name")
        != "openap-yfinance-sec-current-score-results"
        or recovery.get("full_artifact_downloaded") is not False
        or recovery.get("identity_input_only") is not True
        or recovery.get("identity_source_url") != SEC_TICKER_EXCHANGE_URL
        or recovery.get("identity_source_mode") != "sec_official_live"
        or recovery.get("locked_opened") is not False
        or recovery.get("backtest_enabled") is not False
        or recovery.get("validation_used_for_selection") is not False
        or recovery.get("partial") is not False
        or database_contract_violations != 0
        or eligible_symbols is None
        or eligible_symbols <= 1000
        or security_master_rows is None
        or security_master_rows <= 0
        or not security_path.is_file()
        or not source_path.is_file()
        or recovered_hashes.get("security_master.parquet")
        != _sha256_path(security_path)
        or recovered_hashes.get("source_manifest.csv")
        != _sha256_path(source_path)
    ):
        raise ValueError("market security-master recovery contract is invalid")
    return recovery


__all__ = [
    "HttpRangeReader",
    "INSTITUTIONAL_RECOVERY_MEMBERS",
    "MARKET_SECURITY_MASTER_RECOVERY_MEMBERS",
    "inspect_zip_members",
    "read_zip_members",
    "validate_recovered_openap_93",
    "validate_recovered_openap_93_institutional_inputs",
    "validate_recovered_market_security_master",
    "validate_materialized_market_security_master_recovery",
]

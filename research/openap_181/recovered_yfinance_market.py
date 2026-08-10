"""Fail-closed recovery of already acquired YFinance price artifacts.

This module never calls Yahoo.  It accepts only the 48 price shards produced by
the pinned private GitHub Actions run and binds each shard to the SHA-256 values
recorded by the independently audited merged artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from io import BytesIO
from typing import Any
import re

import numpy as np
import pandas as pd


RECOVERED_YFINANCE_SOURCE_RUN_ID = 31_256_096_194
RECOVERED_YFINANCE_SOURCE_HEAD_SHA = (
    "af8c622fc8f0c3789bda539dd14e0b3a52f37187"
)
RECOVERED_YFINANCE_SOURCE_WORKFLOW = (
    ".github/workflows/openap-yfinance-sec-current-score.yml"
)
RECOVERED_YFINANCE_PRICE_COLUMNS = (
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
    "source",
    "retrieved_at",
)
_SOURCE_MANIFEST_COLUMNS = frozenset(
    {
        "chunk_index",
        "total_chunks",
        "symbols_expected",
        "symbols_with_prices",
        "price_rows",
        "metadata_rows",
        "analyst_snapshots",
        "option_rows",
        "retrieved_at",
        "prices_sha256",
        "metadata_sha256",
        "options_sha256",
        "analyst_sha256",
        "status_sha256",
        "summary_sha256",
    }
)
_HASH_COLUMNS = tuple(
    sorted(column for column in _SOURCE_MANIFEST_COLUMNS if column.endswith("_sha256"))
)


def _successful_step(job: Mapping[str, Any], name: str) -> bool:
    return any(
        str(step.get("name", "")) == name
        and str(step.get("conclusion", "")) == "success"
        for step in job.get("steps", [])
        if isinstance(step, Mapping)
    )


def _successful_upload_step(job: Mapping[str, Any]) -> bool:
    return any(
        "actions/upload-artifact@" in str(step.get("name", ""))
        and str(step.get("conclusion", "")) == "success"
        for step in job.get("steps", [])
        if isinstance(step, Mapping)
    )


def validate_recovered_yfinance_source(
    run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Require exact evidence that all 48 price-producing jobs succeeded."""

    run_id = int(run.get("id", 0))
    head_sha = str(run.get("head_sha", "")).lower()
    if (
        run_id != RECOVERED_YFINANCE_SOURCE_RUN_ID
        or run.get("status") != "completed"
        or run.get("conclusion") != "failure"
        or head_sha != RECOVERED_YFINANCE_SOURCE_HEAD_SHA
        or run.get("path") != RECOVERED_YFINANCE_SOURCE_WORKFLOW
    ):
        raise ValueError("source run identity does not match the pinned failed run")

    prepare = [job for job in jobs if job.get("name") == "prepare"]
    if (
        len(prepare) != 1
        or prepare[0].get("conclusion") != "success"
        or not _successful_step(prepare[0], "Validate prepare outputs")
    ):
        raise ValueError("source prepare job lacks successful validation evidence")

    expected_job_names = {f"yfinance ({chunk})" for chunk in range(48)}
    yfinance_jobs = [
        job for job in jobs if str(job.get("name", "")) in expected_job_names
    ]
    actual_job_names = {str(job.get("name")) for job in yfinance_jobs}
    if len(yfinance_jobs) != 48 or actual_job_names != expected_job_names:
        raise ValueError("source run does not contain exactly 48 yfinance jobs")
    if any(
        job.get("conclusion") != "success"
        or not _successful_step(
            job,
            "Download YFinance history and current snapshots",
        )
        or not _successful_upload_step(job)
        for job in yfinance_jobs
    ):
        raise ValueError("source run lacks 48 successful yfinance jobs and uploads")

    expected_artifact_names = {f"openap-yfinance-{chunk}" for chunk in range(48)}
    selected = [
        artifact
        for artifact in artifacts
        if str(artifact.get("name", "")) in expected_artifact_names
    ]
    actual_artifact_names = {str(row.get("name")) for row in selected}
    if len(selected) != 48 or actual_artifact_names != expected_artifact_names:
        raise ValueError("source run does not contain exactly 48 active price artifacts")
    normalised_artifacts: list[dict[str, Any]] = []
    for artifact in selected:
        name = str(artifact.get("name", ""))
        match = re.fullmatch(r"openap-yfinance-(\d+)", name)
        if (
            match is None
            or artifact.get("expired") is not False
            or int(artifact.get("id", 0)) <= 0
            or int(artifact.get("size_in_bytes", 0)) <= 0
        ):
            raise ValueError("source price artifact identity is invalid")
        normalised_artifacts.append(
            {
                **dict(artifact),
                "chunk_index": int(match.group(1)),
            }
        )
    normalised_artifacts.sort(key=lambda row: int(row["chunk_index"]))
    return {
        "source_run_id": run_id,
        "source_head_sha": head_sha,
        "source_workflow": RECOVERED_YFINANCE_SOURCE_WORKFLOW,
        "source_run_conclusion": "failure_after_48_successful_yfinance_jobs",
        "artifact_count": len(normalised_artifacts),
        "artifacts": normalised_artifacts,
        "fresh_provider_request_made": False,
        "strict_score_eligible": False,
    }


def validate_yfinance_source_manifest(payload: bytes) -> pd.DataFrame:
    """Validate the 48-row hash manifest from the audited merged artifact."""

    try:
        frame = pd.read_csv(BytesIO(payload))
    except Exception as exc:
        raise ValueError("audited yfinance source manifest is unreadable") from exc
    missing = sorted(_SOURCE_MANIFEST_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(f"audited yfinance source manifest is missing columns: {missing}")
    if len(frame) != 48:
        raise ValueError("audited yfinance source manifest must contain exactly 48 rows")
    numeric_columns = (
        "chunk_index",
        "total_chunks",
        "symbols_expected",
        "symbols_with_prices",
        "price_rows",
        "metadata_rows",
        "analyst_snapshots",
        "option_rows",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any() or not np.equal(
            frame[column], frame[column].astype("int64")
        ).all():
            raise ValueError(
                f"audited yfinance source manifest has invalid integer {column}"
            )
    expected_chunks = list(range(48))
    chunks = frame["chunk_index"].dropna().astype(int).tolist()
    if sorted(chunks) != expected_chunks or frame["chunk_index"].duplicated().any():
        raise ValueError("audited yfinance source manifest has an invalid chunk set")
    if not frame["total_chunks"].eq(48).all():
        raise ValueError("audited yfinance source manifest total_chunks must be 48")
    if (
        frame["symbols_expected"].le(0).any()
        or frame["symbols_with_prices"].le(0).any()
        or frame["price_rows"].le(0).any()
        or frame["symbols_with_prices"].gt(frame["symbols_expected"]).any()
    ):
        raise ValueError("audited yfinance source manifest has invalid row counts")
    retrieved = pd.to_datetime(frame["retrieved_at"], errors="coerce", utc=True)
    if retrieved.isna().any():
        raise ValueError("audited yfinance source manifest has invalid retrieval times")
    for column in _HASH_COLUMNS:
        if not frame[column].fillna("").astype(str).str.fullmatch(r"[0-9a-fA-F]{64}").all():
            raise ValueError(f"audited yfinance source manifest has invalid {column}")
        frame[column] = frame[column].astype(str).str.lower()
    frame["retrieved_at"] = retrieved
    return frame.sort_values("chunk_index").reset_index(drop=True)


def validate_recovered_yfinance_price_shard(
    artifact: Mapping[str, Any],
    payload: bytes,
    manifest_row: Mapping[str, Any] | pd.Series,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Bind one selectively recovered parquet member to its audited hash row."""

    name = str(artifact.get("name", ""))
    match = re.fullmatch(r"openap-yfinance-(\d+)", name)
    if (
        match is None
        or artifact.get("expired") is not False
        or int(artifact.get("id", 0)) <= 0
        or int(artifact.get("size_in_bytes", 0)) <= 0
    ):
        raise ValueError("recovered yfinance artifact identity is invalid")
    chunk_index = int(match.group(1))
    if int(manifest_row.get("chunk_index", -1)) != chunk_index:
        raise ValueError("recovered yfinance artifact and manifest chunk do not match")
    digest = sha256(payload).hexdigest()
    if digest != str(manifest_row.get("prices_sha256", "")).lower():
        raise ValueError("recovered price shard SHA-256 does not match audited evidence")
    try:
        frame = pd.read_parquet(BytesIO(payload))
    except Exception as exc:
        raise ValueError("recovered price shard is not readable parquet") from exc
    if tuple(frame.columns) != RECOVERED_YFINANCE_PRICE_COLUMNS:
        raise ValueError("recovered price shard violates the exact column contract")
    if len(frame) != int(manifest_row.get("price_rows", -1)):
        raise ValueError("recovered price shard row count does not match audited evidence")
    if frame.empty:
        raise ValueError("recovered price shard is empty")

    parsed = frame.copy()
    parsed["symbol"] = parsed["symbol"].fillna("").astype(str).str.strip().str.upper()
    parsed["date"] = pd.to_datetime(parsed["date"], errors="coerce")
    if parsed["date"].dt.tz is not None:
        parsed["date"] = parsed["date"].dt.tz_convert(None)
    parsed["retrieved_at"] = pd.to_datetime(
        parsed["retrieved_at"], errors="coerce", utc=True
    )
    numeric_columns = (
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "dividends",
        "stock_splits",
    )
    for column in numeric_columns:
        parsed[column] = pd.to_numeric(parsed[column], errors="coerce")
    structural_invalid = (
        parsed["symbol"].eq("")
        | parsed["date"].isna()
        | parsed["retrieved_at"].isna()
        | ~parsed["source"].fillna("").astype(str).eq("yfinance")
    )
    if structural_invalid.any():
        raise ValueError("recovered price shard contains invalid structural rows")
    if parsed.duplicated(["symbol", "date"]).any():
        raise ValueError("recovered price shard contains duplicate symbol/date rows")
    retrievals = parsed["retrieved_at"].drop_duplicates()
    expected_retrieved = pd.to_datetime(
        manifest_row.get("retrieved_at"), errors="coerce", utc=True
    )
    if (
        len(retrievals) != 1
        or pd.isna(expected_retrieved)
        or retrievals.iloc[0] != expected_retrieved
    ):
        raise ValueError("recovered price shard retrieval time does not match manifest")
    if parsed["date"].dt.date.gt(expected_retrieved.date()).any():
        raise ValueError("recovered price shard contains rows after retrieval")
    symbol_count = int(parsed["symbol"].nunique())
    if symbol_count != int(manifest_row.get("symbols_with_prices", -1)):
        raise ValueError("recovered price shard symbol count does not match evidence")
    invalid_price = (
        ~np.isfinite(parsed[list(numeric_columns)]).all(axis=1)
        | parsed[["open", "high", "low", "close", "adj_close"]].le(0).any(axis=1)
        | parsed["volume"].lt(0)
        | parsed["high"].lt(parsed["low"])
    )
    accepted = parsed.loc[~invalid_price].copy()
    if accepted.empty:
        raise ValueError("recovered price shard contains no valid price rows")
    evidence = {
        "chunk_index": chunk_index,
        "artifact_id": int(artifact["id"]),
        "artifact_name": name,
        "artifact_size_in_bytes": int(artifact["size_in_bytes"]),
        "price_rows": int(len(parsed)),
        "accepted_price_rows": int(len(accepted)),
        "quarantined_price_rows": int(invalid_price.sum()),
        "symbols_with_prices": symbol_count,
        "retrieved_at": expected_retrieved.isoformat(),
        "prices_sha256": digest,
        "fresh_provider_request_made": False,
        "strict_score_eligible": False,
    }
    return accepted, evidence


def _midnight_new_york(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value).normalize()
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp.tz_localize("America/New_York").tz_convert("UTC")


def build_recovered_yfinance_bars(
    shards: Sequence[pd.DataFrame],
    accepted_universe: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    source_run_id: int = RECOVERED_YFINANCE_SOURCE_RUN_ID,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build adjusted and nominal bars without promoting historical identity."""

    if source_run_id != RECOVERED_YFINANCE_SOURCE_RUN_ID:
        raise ValueError("recovered price bars require the pinned source run")
    required_universe = {"security_id", "ticker", "cik"}
    missing = sorted(required_universe.difference(accepted_universe.columns))
    if missing:
        raise ValueError(f"accepted universe is missing columns: {missing}")
    formation = pd.to_datetime(formation_at, errors="coerce", utc=True)
    if pd.isna(formation):
        raise ValueError("recovered price formation_at is invalid")
    if not shards:
        raise ValueError("no recovered price shards were supplied")

    universe = accepted_universe.loc[:, ["security_id", "ticker", "cik"]].copy()
    universe["security_id"] = universe["security_id"].fillna("").astype(str).str.strip()
    universe["ticker"] = universe["ticker"].fillna("").astype(str).str.strip().str.upper()
    universe["cik"] = universe["cik"].fillna("").astype(str).str.strip().str.zfill(10)
    invalid_universe = (
        universe["security_id"].eq("")
        | universe["ticker"].eq("")
        | ~universe["cik"].str.fullmatch(r"\d{10}")
        | universe["security_id"].duplicated(keep=False)
        | universe["ticker"].duplicated(keep=False)
    )
    if invalid_universe.any():
        raise ValueError("accepted universe contains ambiguous current identities")

    prices = pd.concat([frame.copy() for frame in shards], ignore_index=True)
    if tuple(prices.columns) != RECOVERED_YFINANCE_PRICE_COLUMNS:
        raise ValueError("recovered price shards violate the exact column contract")
    prices["symbol"] = prices["symbol"].fillna("").astype(str).str.strip().str.upper()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    if prices["date"].dt.tz is not None:
        prices["date"] = prices["date"].dt.tz_convert(None)
    prices["retrieved_at"] = pd.to_datetime(
        prices["retrieved_at"], errors="coerce", utc=True
    )
    for column in ("open", "high", "low", "close", "adj_close", "volume"):
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    if prices.duplicated(["symbol", "date"]).any():
        raise ValueError("recovered price shards overlap on symbol/date")
    invalid_prices = (
        prices["symbol"].eq("")
        | prices["date"].isna()
        | prices["retrieved_at"].isna()
        | ~np.isfinite(
            prices[["open", "high", "low", "close", "adj_close", "volume"]]
        ).all(axis=1)
        | prices[["open", "high", "low", "close", "adj_close"]].le(0).any(axis=1)
        | prices["volume"].lt(0)
        | prices["high"].lt(prices["low"])
        | ~prices["source"].fillna("").astype(str).eq("yfinance")
    )
    if invalid_prices.any():
        raise ValueError("recovered price shards contain invalid rows")
    formation_naive = formation.tz_convert(None)
    prices = prices.loc[prices["date"].le(formation_naive)].copy()
    if prices.empty:
        raise ValueError("recovered price shards contain no causal rows")

    price_symbols = set(prices["symbol"])
    universe_symbols = set(universe["ticker"])
    rejected_rows = [
        {
            "symbol": symbol,
            "reason": "not_in_current_sec_primary_universe",
            "strict_score_eligible": False,
        }
        for symbol in sorted(price_symbols.difference(universe_symbols))
    ]
    rejected_rows.extend(
        {
            "symbol": symbol,
            "reason": "no_recovered_price_history",
            "strict_score_eligible": False,
        }
        for symbol in sorted(universe_symbols.difference(price_symbols))
    )
    rejected = pd.DataFrame(
        rejected_rows,
        columns=("symbol", "reason", "strict_score_eligible"),
    )
    prices = prices.loc[prices["symbol"].isin(universe["ticker"])].copy()
    if prices.empty:
        raise ValueError("no recovered prices match the current SEC universe")
    prices = prices.merge(
        universe,
        left_on="symbol",
        right_on="ticker",
        how="inner",
        validate="many_to_one",
    ).sort_values(["security_id", "date"])

    prices["next_observed_date"] = prices.groupby("security_id", sort=False)[
        "date"
    ].shift(-1)
    prices["available_at"] = [
        _midnight_new_york(next_date)
        if not pd.isna(next_date)
        else retrieved_at
        for next_date, retrieved_at in zip(
            prices["next_observed_date"],
            prices["retrieved_at"],
            strict=True,
        )
    ]
    prices["available_at"] = pd.to_datetime(
        prices["available_at"], errors="coerce", utc=True
    )
    prices = prices.loc[prices["available_at"].le(formation)].copy()
    if prices.empty:
        raise ValueError("no recovered prices were available by formation_at")

    base_columns = [
        "security_id",
        "ticker",
        "cik",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "available_at",
        "retrieved_at",
    ]
    nominal = prices.loc[:, base_columns].copy()
    nominal.insert(3, "adjust", "none")
    ratio = prices["adj_close"] / prices["close"]
    if (~np.isfinite(ratio) | ratio.le(0)).any():
        raise ValueError("recovered adjusted-close ratios are invalid")
    adjusted = prices.loc[:, base_columns].copy()
    adjusted.insert(3, "adjust", "all")
    for column in ("open", "high", "low", "close"):
        adjusted[column] = prices[column].to_numpy(dtype=float) * ratio.to_numpy(dtype=float)
    adjusted["close"] = prices["adj_close"].to_numpy(dtype=float)

    bars = pd.concat([adjusted, nominal], ignore_index=True)
    bars["source_id"] = f"recovered_yfinance_artifacts_{source_run_id}"
    bars["source_url"] = (
        "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
        f"{source_run_id}"
    )
    bars["historical_ticker_interval_verified"] = False
    bars["strict_score_eligible"] = False
    bars = bars.sort_values(["security_id", "adjust", "date"]).reset_index(drop=True)
    return bars, rejected


__all__ = [
    "RECOVERED_YFINANCE_PRICE_COLUMNS",
    "RECOVERED_YFINANCE_SOURCE_HEAD_SHA",
    "RECOVERED_YFINANCE_SOURCE_RUN_ID",
    "RECOVERED_YFINANCE_SOURCE_WORKFLOW",
    "build_recovered_yfinance_bars",
    "validate_recovered_yfinance_price_shard",
    "validate_recovered_yfinance_source",
    "validate_yfinance_source_manifest",
]

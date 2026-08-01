"""GitHub-only OpenAP current data and score pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping
import zipfile

import numpy as np
import pandas as pd
import yaml

from aurora.core.execution_policy import (
    require_github_actions_or_explicit_local_permission,
)
from aurora.research.openap_current_score import (
    EXPECTED_PREDICTORS,
    FeatureValue,
    OpenAPDataError,
    assemble_feature_table,
    build_redundancy_groups,
    calculate_accounting_features,
    calculate_price_features,
    calculate_scores,
    coverage_report,
    latest_sec_concepts,
    select_strict_predictors,
    sha256_file,
    write_summary,
)


EXCLUDE_SECURITY_RE = re.compile(
    r"\b(?:ETF|ETN|FUND|DEPOSITARY|ADR|ADS|WARRANT|RIGHT|UNIT|PREFERRED|PREF|SPAC|ACQUISITION CORP)\b",
    re.IGNORECASE,
)
ALLOWED_EXCHANGE_RE = re.compile(r"NASDAQ|NYSE|NEW YORK STOCK EXCHANGE|CBOE", re.IGNORECASE)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_config(path: str | Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if config.get("execution", {}).get("execution_location") != "github_actions":
        raise OpenAPDataError("OpenAP current pipeline must declare GitHub Actions execution")
    if config.get("execution", {}).get("local_runs_allowed") is not False:
        raise OpenAPDataError("OpenAP current pipeline cannot allow local runs")
    if int(config.get("openap", {}).get("expected_predictors", 0)) != EXPECTED_PREDICTORS:
        raise OpenAPDataError("Config must require exactly 185 strict predictors")
    return config


def _download(url: str, destination: Path, *, headers: Mapping[str, str] | None = None, retries: int = 4) -> None:
    import requests

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(retries):
        try:
            with requests.get(url, headers=dict(headers or {}), stream=True, timeout=(30, 300)) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for block in response.iter_content(chunk_size=1024 * 1024):
                        if block:
                            handle.write(block)
            if temporary.stat().st_size == 0:
                raise OpenAPDataError(f"Downloaded empty file: {url}")
            temporary.replace(destination)
            return
        except Exception:
            if attempt + 1 >= retries:
                raise
            time.sleep(2 ** attempt)


def _parse_dates(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    compact = text.str.fullmatch(r"\d{6}")
    result = pd.to_datetime(text, errors="coerce")
    result.loc[compact] = pd.to_datetime(text.loc[compact] + "01", format="%Y%m%d", errors="coerce")
    return result


def _read_predictor_returns(path: Path, names: list[str]) -> pd.DataFrame:
    raw = pd.read_csv(path, low_memory=False)
    date_col = str(raw.columns[0])
    raw[date_col] = _parse_dates(raw[date_col])
    available = {re.sub(r"[^a-z0-9]", "", str(col).lower()): str(col) for col in raw.columns}
    rename: dict[str, str] = {}
    missing = []
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key not in available:
            missing.append(name)
        else:
            rename[available[key]] = name
    if missing:
        raise OpenAPDataError(f"Official returns missing {len(missing)} selected predictors")
    return raw.set_index(date_col)[list(rename)].rename(columns=rename).apply(pd.to_numeric, errors="coerce")


def _sec_exchange_rows(payload: Mapping[str, Any]) -> pd.DataFrame:
    fields = [str(item) for item in payload.get("fields", [])]
    data = payload.get("data", [])
    if not fields or not isinstance(data, list):
        raise OpenAPDataError("Unexpected SEC ticker exchange payload")
    frame = pd.DataFrame(data, columns=fields)
    columns = {str(col).lower(): str(col) for col in frame.columns}
    cik_col = columns.get("cik")
    name_col = columns.get("name")
    tickers_col = columns.get("tickers")
    exchanges_col = columns.get("exchanges")
    if not all((cik_col, name_col, tickers_col, exchanges_col)):
        raise OpenAPDataError(f"SEC exchange payload missing fields: {fields}")
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        tickers = record.get(tickers_col) or []
        exchanges = record.get(exchanges_col) or []
        if isinstance(tickers, str):
            tickers = [tickers]
        if isinstance(exchanges, str):
            exchanges = [exchanges]
        for index, ticker in enumerate(tickers):
            exchange = exchanges[index] if index < len(exchanges) else ""
            symbol = str(ticker).strip().upper().replace(".", "-")
            name = str(record.get(name_col) or "").strip()
            if not symbol or not ALLOWED_EXCHANGE_RE.search(str(exchange)):
                continue
            if EXCLUDE_SECURITY_RE.search(name) or "$" in symbol or "^" in symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "sec_ticker": str(ticker).strip().upper(),
                    "cik": int(record[cik_col]),
                    "company_name_sec": name,
                    "exchange_sec": str(exchange),
                    "asset_type": "COMMON_STOCK_CANDIDATE",
                    "country": "United States",
                    "source": "sec_company_tickers_exchange",
                    "retrieved_at": _utcnow(),
                }
            )
    result = pd.DataFrame(rows).drop_duplicates(["symbol", "cik"]).sort_values(["symbol", "cik"])
    if result.empty:
        raise OpenAPDataError("SEC universe is empty after common-stock filters")
    return result.reset_index(drop=True)


def prepare(config: dict[str, Any], args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    metadata = pd.read_excel(args.predictor_summary, sheet_name="short")
    selected = select_strict_predictors(metadata)
    selected.to_csv(output / "selected_185_predictors.csv", index=False)
    selected.to_parquet(output / "selected_185_predictors.parquet", index=False)

    returns = _read_predictor_returns(Path(args.predictor_returns), selected["signalname"].astype(str).tolist())
    groups = build_redundancy_groups(
        selected,
        returns,
        threshold=float(config["openap"]["correlation_threshold"]),
        minimum_overlap=int(config["openap"]["minimum_overlap_months"]),
    )
    groups.to_csv(output / "redundancy_groups.csv", index=False)

    sec_payload_path = output / "company_tickers_exchange.json"
    _download(config["sec"]["ticker_exchange_url"], sec_payload_path, headers={"User-Agent": args.sec_user_agent})
    sec_payload = json.loads(sec_payload_path.read_text(encoding="utf-8"))
    universe = _sec_exchange_rows(sec_payload)
    universe.to_csv(output / "security_master_seed.csv", index=False)
    universe.to_parquet(output / "security_master_seed.parquet", index=False)

    source_rows = [
        {"source": "PredictorSummary.xlsx", "sha256": sha256_file(args.predictor_summary), "role": "selection_and_evidence"},
        {"source": "PredictorLSretWide.csv", "sha256": sha256_file(args.predictor_returns), "role": "redundancy_groups"},
        {"source": "company_tickers_exchange.json", "sha256": sha256_file(sec_payload_path), "role": "ticker_cik_universe"},
    ]
    pd.DataFrame(source_rows).to_csv(output / "source_manifest.csv", index=False)
    write_summary(
        output / "prepare_summary.json",
        {
            "dataset_id": config["dataset_id"],
            "prepared_at": _utcnow(),
            "selected_predictors": len(selected),
            "universe_rows": len(universe),
            "unique_symbols": int(universe["symbol"].nunique()),
            "unique_ciks": int(universe["cik"].nunique()),
            "redundancy_groups": int(groups["redundancy_group"].nunique()),
            "openap_commit": config["openap"]["commit"],
            "locked_opened": False,
            "backtest_enabled": False,
        },
    )


def _normalise_price_frame(frame: pd.DataFrame, symbol: str, retrieved_at: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    if isinstance(out.index, pd.MultiIndex):
        out = out.reset_index()
    else:
        out = out.reset_index()
    rename = {
        "Date": "date",
        "Datetime": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
        "Dividends": "dividends",
        "Stock Splits": "stock_splits",
    }
    out = out.rename(columns=rename)
    if "date" not in out and out.columns.size:
        out = out.rename(columns={out.columns[0]: "date"})
    if "adj_close" not in out and "close" in out:
        out["adj_close"] = out["close"]
    for column in ("open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"):
        if column not in out:
            out[column] = np.nan if column not in {"dividends", "stock_splits"} else 0.0
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True).dt.tz_localize(None)
    out = out.dropna(subset=["date", "adj_close"]).sort_values("date").drop_duplicates("date", keep="last")
    out["symbol"] = symbol
    out["source"] = "yfinance"
    out["retrieved_at"] = retrieved_at
    return out[["date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits", "source", "retrieved_at"]]


def _extract_batch_symbol(raw: pd.DataFrame, symbol: str, single: bool) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if not isinstance(raw.columns, pd.MultiIndex):
        return raw if single else pd.DataFrame()
    level0 = set(map(str, raw.columns.get_level_values(0)))
    level1 = set(map(str, raw.columns.get_level_values(1)))
    if symbol in level0:
        return raw[symbol]
    if symbol in level1:
        return raw.xs(symbol, axis=1, level=1)
    return pd.DataFrame()


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value if not isinstance(value, float) or math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    return str(value)


def _dataframe_payload(frame: Any) -> list[dict[str, Any]]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    reset = frame.reset_index()
    return [_json_safe(row) for row in reset.to_dict(orient="records")]


def _ticker_snapshots(ticker: Any, symbol: str, config: Mapping[str, Any], retrieved_at: str) -> tuple[dict[str, Any], list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]]:
    metadata: dict[str, Any] = {"symbol": symbol, "retrieved_at": retrieved_at, "source": "yfinance", "status": "ok"}
    analyst_rows: list[dict[str, Any]] = []
    options_frames: list[pd.DataFrame] = []
    status_rows: list[dict[str, Any]] = []
    try:
        info = ticker.get_info() or {}
        wanted = (
            "longName", "shortName", "quoteType", "exchange", "marketCap", "sharesOutstanding",
            "floatShares", "sector", "industry", "country", "currency", "currentPrice",
            "regularMarketPrice", "averageDailyVolume3Month", "averageVolume10days", "firstTradeDateEpochUtc",
        )
        metadata.update({key: _json_safe(info.get(key)) for key in wanted})
    except Exception as exc:
        metadata["status"] = "metadata_error"
        metadata["error"] = str(exc)[:500]

    datasets = (
        "recommendations", "upgrades_downgrades", "earnings_estimate", "revenue_estimate",
        "earnings_history", "eps_trend", "eps_revisions", "growth_estimates", "institutional_holders",
        "mutualfund_holders", "insider_transactions",
    )
    for dataset in datasets:
        try:
            value = getattr(ticker, dataset, None)
            if callable(value):
                value = value()
            payload = _dataframe_payload(value)
            analyst_rows.append({"symbol": symbol, "dataset": dataset, "retrieved_at": retrieved_at, "payload_json": json.dumps(payload, ensure_ascii=True)})
        except Exception as exc:
            status_rows.append({"symbol": symbol, "surface": dataset, "status": "error", "error": str(exc)[:500]})

    if bool(config["yfinance"].get("current_options_snapshot", True)):
        try:
            expirations = list(ticker.options or [])
            if expirations:
                target = pd.Timestamp.utcnow().tz_localize(None) + pd.Timedelta(days=int(config["yfinance"].get("target_option_days", 30)))
                expiration = min(expirations, key=lambda item: abs((pd.Timestamp(item) - target).days))
                chain = ticker.option_chain(expiration)
                for option_type, frame in (("call", chain.calls), ("put", chain.puts)):
                    if frame is None or frame.empty:
                        continue
                    current = frame.copy()
                    current["symbol"] = symbol
                    current["option_type"] = option_type
                    current["expiration"] = expiration
                    current["retrieved_at"] = retrieved_at
                    options_frames.append(current)
        except Exception as exc:
            status_rows.append({"symbol": symbol, "surface": "options", "status": "error", "error": str(exc)[:500]})
    options = pd.concat(options_frames, ignore_index=True) if options_frames else pd.DataFrame()
    return metadata, analyst_rows, options, status_rows


def yfinance_chunk(config: dict[str, Any], args: argparse.Namespace) -> None:
    import yfinance as yf

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    universe = pd.read_parquet(args.security_master)
    chunks = np.array_split(universe.reset_index(drop=True), int(args.total_chunks))
    chunk_index = int(args.chunk_index)
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise OpenAPDataError(f"Invalid chunk {chunk_index} for {len(chunks)} chunks")
    selected = chunks[chunk_index].copy()
    symbols = selected["symbol"].astype(str).tolist()
    retrieved_at = _utcnow()
    prices: list[pd.DataFrame] = []
    metadata_rows: list[dict[str, Any]] = []
    analyst_rows: list[dict[str, Any]] = []
    option_frames: list[pd.DataFrame] = []
    status_rows: list[dict[str, Any]] = []

    batch_size = int(config["yfinance"].get("batch_size", 25))
    for start in range(0, len(symbols), batch_size):
        batch = symbols[start : start + batch_size]
        raw = pd.DataFrame()
        error = ""
        for attempt in range(3):
            try:
                raw = yf.download(
                    tickers=batch,
                    period=str(config["yfinance"].get("history_period", "max")),
                    auto_adjust=False,
                    actions=True,
                    group_by="ticker",
                    threads=True,
                    progress=False,
                    timeout=60,
                )
                if raw is not None and not raw.empty:
                    break
            except Exception as exc:
                error = str(exc)
                time.sleep(2 ** attempt)
        for symbol in batch:
            frame = _extract_batch_symbol(raw, symbol, len(batch) == 1)
            normalised = _normalise_price_frame(frame, symbol, retrieved_at)
            if not normalised.empty:
                prices.append(normalised)
                status_rows.append({"symbol": symbol, "surface": "prices", "status": "ok", "rows": len(normalised), "error": ""})
            else:
                status_rows.append({"symbol": symbol, "surface": "prices", "status": "no_data", "rows": 0, "error": error[:500]})

    for index, symbol in enumerate(symbols):
        ticker = yf.Ticker(symbol)
        metadata, analysts, options, extra_status = _ticker_snapshots(ticker, symbol, config, retrieved_at)
        metadata_rows.append(metadata)
        analyst_rows.extend(analysts)
        if not options.empty:
            option_frames.append(options)
        status_rows.extend(extra_status)
        if index and index % 20 == 0:
            time.sleep(1.0)

    price_frame = pd.concat(prices, ignore_index=True) if prices else pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits", "source", "retrieved_at"])
    price_frame.to_parquet(output / f"prices_{chunk_index:03d}.parquet", index=False, compression="zstd")
    pd.DataFrame(metadata_rows).to_parquet(output / f"metadata_{chunk_index:03d}.parquet", index=False, compression="zstd")
    options_frame = pd.concat(option_frames, ignore_index=True) if option_frames else pd.DataFrame(columns=["symbol", "option_type", "expiration", "retrieved_at"])
    options_frame.to_parquet(output / f"options_{chunk_index:03d}.parquet", index=False, compression="zstd")
    with (output / f"analyst_{chunk_index:03d}.jsonl").open("w", encoding="utf-8") as handle:
        for row in analyst_rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")
    pd.DataFrame(status_rows).to_csv(output / f"status_{chunk_index:03d}.csv", index=False)
    write_summary(
        output / f"summary_{chunk_index:03d}.json",
        {
            "chunk_index": chunk_index,
            "total_chunks": int(args.total_chunks),
            "symbols_expected": len(symbols),
            "symbols_with_prices": int(price_frame["symbol"].nunique()) if not price_frame.empty else 0,
            "price_rows": len(price_frame),
            "metadata_rows": len(metadata_rows),
            "analyst_snapshots": len(analyst_rows),
            "option_rows": len(options_frame),
            "retrieved_at": retrieved_at,
        },
    )


def _submission_rows(payload: Mapping[str, Any], cik: int) -> list[dict[str, Any]]:
    filings = payload.get("filings", {}) if isinstance(payload, Mapping) else {}
    recent = filings.get("recent", {}) if isinstance(filings, Mapping) else {}
    if not isinstance(recent, Mapping):
        return []
    arrays = {key: value if isinstance(value, list) else [] for key, value in recent.items()}
    n = max((len(value) for value in arrays.values()), default=0)
    rows = []
    for index in range(n):
        def item(name: str) -> Any:
            values = arrays.get(name, [])
            return values[index] if index < len(values) else None
        rows.append(
            {
                "cik": cik,
                "accession_number": item("accessionNumber"),
                "filing_date": item("filingDate"),
                "accepted_at": item("acceptanceDateTime"),
                "report_date": item("reportDate") or item("periodOfReport"),
                "form": item("form"),
                "primary_document": item("primaryDocument"),
                "is_xbrl": item("isXBRL"),
                "source": "sec_submissions_bulk",
            }
        )
    return rows


def _cik_from_member(member: str) -> int | None:
    match = re.search(r"CIK0*(\d+)", member, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _write_parquet_batches(path: Path, batches: Iterable[pd.DataFrame]) -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    writer = None
    rows = 0
    try:
        for frame in batches:
            if frame.empty:
                continue
            table = pa.Table.from_pandas(frame, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(path, table.schema, compression="zstd")
            writer.write_table(table)
            rows += len(frame)
    finally:
        if writer is not None:
            writer.close()
    if writer is None:
        pd.DataFrame().to_parquet(path, index=False)
    return rows


def sec_bulk(config: dict[str, Any], args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    raw_dir = output / "raw"
    lake_dir = output / "lake"
    raw_dir.mkdir(parents=True, exist_ok=True)
    lake_dir.mkdir(parents=True, exist_ok=True)
    universe = pd.read_parquet(args.security_master)
    ciks = set(pd.to_numeric(universe["cik"], errors="coerce").dropna().astype(int).tolist())
    headers = {"User-Agent": args.sec_user_agent}
    companyfacts_zip = raw_dir / "companyfacts.zip"
    submissions_zip = raw_dir / "submissions.zip"
    _download(config["sec"]["companyfacts_bulk_url"], companyfacts_zip, headers=headers)
    _download(config["sec"]["submissions_bulk_url"], submissions_zip, headers=headers)

    submission_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(submissions_zip) as archive:
        for member in archive.namelist():
            cik = _cik_from_member(member)
            if cik not in ciks or not member.lower().endswith(".json"):
                continue
            try:
                payload = json.loads(archive.read(member).decode("utf-8", errors="replace"))
            except Exception:
                continue
            submission_rows.extend(_submission_rows(payload, cik))
    submissions = pd.DataFrame(submission_rows)
    if submissions.empty:
        raise OpenAPDataError("SEC submissions bulk produced no selected rows")
    submissions["accepted_at"] = pd.to_datetime(submissions["accepted_at"], errors="coerce", utc=True)
    submissions.to_parquet(lake_dir / "sec_submissions.parquet", index=False, compression="zstd")
    accepted_map = {
        (int(row.cik), str(row.accession_number)): row.accepted_at
        for row in submissions.itertuples()
        if pd.notna(row.accession_number) and pd.notna(row.accepted_at)
    }

    def fact_batches() -> Iterable[pd.DataFrame]:
        buffer: list[dict[str, Any]] = []
        with zipfile.ZipFile(companyfacts_zip) as archive:
            for member in archive.namelist():
                cik = _cik_from_member(member)
                if cik not in ciks or not member.lower().endswith(".json"):
                    continue
                try:
                    payload = json.loads(archive.read(member).decode("utf-8", errors="replace"))
                except Exception:
                    continue
                entity_name = str(payload.get("entityName") or "")
                facts = payload.get("facts", {})
                if not isinstance(facts, Mapping):
                    continue
                for taxonomy, concepts in facts.items():
                    if not isinstance(concepts, Mapping):
                        continue
                    for tag, definition in concepts.items():
                        units = definition.get("units", {}) if isinstance(definition, Mapping) else {}
                        if not isinstance(units, Mapping):
                            continue
                        for unit, observations in units.items():
                            if not isinstance(observations, list):
                                continue
                            for observation in observations:
                                if not isinstance(observation, Mapping):
                                    continue
                                accession = str(observation.get("accn") or "")
                                filed = str(observation.get("filed") or "")
                                accepted = accepted_map.get((cik, accession))
                                quality = "sec_acceptance_timestamp"
                                if pd.isna(accepted) or accepted is None:
                                    accepted = pd.to_datetime(filed, errors="coerce", utc=True) + pd.Timedelta(days=1)
                                    quality = "conservative_filing_date_plus_one_day"
                                buffer.append(
                                    {
                                        "cik": cik,
                                        "entity_name": entity_name,
                                        "taxonomy": taxonomy,
                                        "tag": tag,
                                        "unit": unit,
                                        "value": observation.get("val"),
                                        "period_start": observation.get("start"),
                                        "period_end": observation.get("end"),
                                        "fy": observation.get("fy"),
                                        "fp": observation.get("fp"),
                                        "form": observation.get("form"),
                                        "filed": filed,
                                        "accession_number": accession,
                                        "frame": observation.get("frame"),
                                        "available_at": accepted,
                                        "available_at_quality": quality,
                                        "source": f"zip://companyfacts.zip#{member}",
                                    }
                                )
                                if len(buffer) >= 100_000:
                                    yield _normalise_fact_batch(pd.DataFrame(buffer))
                                    buffer = []
        if buffer:
            yield _normalise_fact_batch(pd.DataFrame(buffer))

    fact_count = _write_parquet_batches(lake_dir / "sec_companyfacts.parquet", fact_batches())
    manifest = {
        "retrieved_at": _utcnow(),
        "universe_ciks": len(ciks),
        "submissions_rows": len(submissions),
        "companyfacts_rows": fact_count,
        "companyfacts_zip_bytes": companyfacts_zip.stat().st_size,
        "companyfacts_zip_sha256": sha256_file(companyfacts_zip),
        "submissions_zip_bytes": submissions_zip.stat().st_size,
        "submissions_zip_sha256": sha256_file(submissions_zip),
        "all_facts_have_available_at": True,
        "locked_opened": False,
    }
    write_summary(output / "sec_bulk_summary.json", manifest)


def _read_jsonl_files(paths: Iterable[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return pd.DataFrame(rows)


def _options_features(frame: pd.DataFrame, stock_volume: float | None, realized_vol: float | None) -> dict[str, FeatureValue]:
    if frame.empty:
        return {}
    data = frame.copy()
    for column in ("impliedVolatility", "volume", "openInterest", "strike"):
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    calls = data.loc[data["option_type"].eq("call")]
    puts = data.loc[data["option_type"].eq("put")]
    call_iv = calls["impliedVolatility"].median() if "impliedVolatility" in calls else np.nan
    put_iv = puts["impliedVolatility"].median() if "impliedVolatility" in puts else np.nan
    total_volume = data["volume"].sum(min_count=1) if "volume" in data else np.nan
    total_oi = data["openInterest"].sum(min_count=1) if "openInterest" in data else np.nan
    values: dict[str, FeatureValue] = {
        "CPVolSpread": FeatureValue("CPVolSpread", float(call_iv - put_iv) if pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "median_call_iv_minus_put_iv", "Current chain replaces OptionMetrics filters"),
        "OptionVolume1": FeatureValue("OptionVolume1", _safe_numeric_ratio(total_volume, stock_volume), "proxy", "yfinance_current_option_chain", "option_volume_over_stock_volume", "Current nearest-expiry chain only"),
        "OptionVolume2": FeatureValue("OptionVolume2", _safe_numeric_ratio(total_oi, stock_volume), "proxy", "yfinance_current_option_chain", "option_oi_over_stock_volume", "Open interest proxy for total option activity"),
        "SmileSlope": FeatureValue("SmileSlope", float(put_iv - call_iv) if pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "put_iv_minus_call_iv", "Median IV spread replaces matched-delta smile slope"),
        "skew1": FeatureValue("skew1", float(put_iv - call_iv) if pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "put_iv_minus_call_iv", "Current-chain smirk proxy"),
        "RIVolSpread": FeatureValue("RIVolSpread", float(realized_vol - (call_iv + put_iv) / 2) if realized_vol is not None and pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "realized_minus_median_implied_vol", "Current-chain proxy"),
    }
    return values


def _normalise_fact_batch(frame: pd.DataFrame) -> pd.DataFrame:
    """Force a stable Arrow schema across all SEC fact batches."""

    out = frame.copy()
    out["cik"] = pd.to_numeric(out["cik"], errors="coerce").astype("Int64")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["fy"] = pd.to_numeric(out["fy"], errors="coerce").astype("Int64")
    for column in (
        "entity_name", "taxonomy", "tag", "unit", "period_start", "period_end",
        "fp", "form", "filed", "accession_number", "frame", "available_at_quality",
        "source",
    ):
        out[column] = out[column].astype("string")
    out["available_at"] = pd.to_datetime(out["available_at"], errors="coerce", utc=True)
    return out[
        [
            "cik", "entity_name", "taxonomy", "tag", "unit", "value", "period_start",
            "period_end", "fy", "fp", "form", "filed", "accession_number", "frame",
            "available_at", "available_at_quality", "source",
        ]
    ]


def _safe_numeric_ratio(left: Any, right: Any) -> float | None:
    try:
        left_value, right_value = float(left), float(right)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(left_value) or not np.isfinite(right_value) or right_value == 0:
        return None
    return left_value / right_value


def _analyst_features(rows: pd.DataFrame) -> dict[str, FeatureValue]:
    if rows.empty:
        return {}
    payloads: dict[str, list[dict[str, Any]]] = {}
    for row in rows.itertuples():
        try:
            payloads[str(row.dataset)] = json.loads(row.payload_json)
        except Exception:
            payloads[str(row.dataset)] = []
    result: dict[str, FeatureValue] = {}
    revisions = payloads.get("eps_revisions", [])
    if revisions:
        latest = revisions[0]
        up = sum(float(latest.get(key) or 0) for key in latest if "up" in str(key).lower())
        down = sum(float(latest.get(key) or 0) for key in latest if "down" in str(key).lower())
        net = up - down
        result["AnalystRevision"] = FeatureValue("AnalystRevision", net, "proxy", "yfinance_analyst_snapshot", "current_up_minus_down_eps_revisions", "Current Yahoo snapshot, not PIT IBES")
        result["UpRecomm"] = FeatureValue("UpRecomm", up, "proxy", "yfinance_analyst_snapshot", "current_upward_eps_revisions", "Current Yahoo snapshot")
        result["DownRecomm"] = FeatureValue("DownRecomm", down, "proxy", "yfinance_analyst_snapshot", "current_downward_eps_revisions", "Current Yahoo snapshot")
        result["REV6"] = FeatureValue("REV6", net, "proxy", "yfinance_analyst_snapshot", "current_revision_balance_proxy", "No six-month PIT IBES history")
    trend = payloads.get("eps_trend", [])
    if trend:
        latest = trend[0]
        current = next((float(value) for key, value in latest.items() if "current" in str(key).lower() and _is_number(value)), None)
        old = next((float(value) for key, value in latest.items() if any(token in str(key).lower() for token in ("90", "60", "30")) and _is_number(value)), None)
        change = current - old if current is not None and old is not None else None
        result["ChForecastAccrual"] = FeatureValue("ChForecastAccrual", change, "proxy", "yfinance_analyst_snapshot", "eps_trend_current_minus_prior", "Yahoo field availability varies")
        result["sfe"] = FeatureValue("sfe", current, "proxy", "yfinance_analyst_snapshot", "current_eps_forecast", "Current Yahoo snapshot")
    recommendations = payloads.get("recommendations", [])
    if recommendations:
        numeric = []
        for item in recommendations:
            for key, value in item.items():
                if "mean" in str(key).lower() and _is_number(value):
                    numeric.append(float(value))
        if numeric:
            result["ChangeInRecommendation"] = FeatureValue("ChangeInRecommendation", numeric[-1] - numeric[-2] if len(numeric) > 1 else None, "proxy", "yfinance_analyst_snapshot", "recommendation_mean_change", "Yahoo snapshot, not PIT IBES")
            result["ConsRecomm"] = FeatureValue("ConsRecomm", numeric[-1], "proxy", "yfinance_analyst_snapshot", "recommendation_mean", "Yahoo scale and coverage differ from IBES")
    return result


def _is_number(value: Any) -> bool:
    try:
        return np.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def merge(config: dict[str, Any], args: argparse.Namespace) -> None:
    import duckdb

    input_root = Path(args.input_root)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    prepare_dir = Path(args.prepare_dir)
    sec_dir = Path(args.sec_dir)
    metadata = pd.read_parquet(prepare_dir / "selected_185_predictors.parquet")
    groups = pd.read_csv(prepare_dir / "redundancy_groups.csv")
    seed = pd.read_parquet(prepare_dir / "security_master_seed.parquet")

    price_paths = sorted(input_root.rglob("prices_*.parquet"))
    metadata_paths = sorted(input_root.rglob("metadata_*.parquet"))
    option_paths = sorted(input_root.rglob("options_*.parquet"))
    analyst_paths = sorted(input_root.rglob("analyst_*.jsonl"))
    summary_paths = sorted(input_root.rglob("summary_*.json"))
    expected_chunks = int(config["execution"]["yfinance_chunks"])
    if len(price_paths) != expected_chunks:
        raise OpenAPDataError(f"Expected {expected_chunks} YFinance price chunks, found {len(price_paths)}")

    db_path = output / "openap_current.duckdb"
    connection = duckdb.connect(str(db_path))
    quoted_prices = ",".join(repr(str(path)) for path in price_paths)
    quoted_metadata = ",".join(repr(str(path)) for path in metadata_paths)
    connection.execute(f"CREATE OR REPLACE TABLE prices_daily AS SELECT * FROM read_parquet([{quoted_prices}], union_by_name=true)")
    connection.execute(f"CREATE OR REPLACE TABLE yahoo_current_snapshots AS SELECT * FROM read_parquet([{quoted_metadata}], union_by_name=true)")
    valid_options = [path for path in option_paths if path.stat().st_size > 0]
    if valid_options:
        quoted_options = ",".join(repr(str(path)) for path in valid_options)
        connection.execute(f"CREATE OR REPLACE TABLE yahoo_options_current AS SELECT * FROM read_parquet([{quoted_options}], union_by_name=true)")
    else:
        connection.execute("CREATE OR REPLACE TABLE yahoo_options_current(symbol VARCHAR, option_type VARCHAR, expiration VARCHAR, retrieved_at VARCHAR)")
    connection.execute(f"CREATE OR REPLACE TABLE sec_companyfacts AS SELECT * FROM read_parquet({repr(str(sec_dir / 'lake' / 'sec_companyfacts.parquet'))}, union_by_name=true)")
    connection.execute(f"CREATE OR REPLACE TABLE sec_submissions AS SELECT * FROM read_parquet({repr(str(sec_dir / 'lake' / 'sec_submissions.parquet'))}, union_by_name=true)")

    yahoo_meta = connection.execute("SELECT * FROM yahoo_current_snapshots").df()
    if not yahoo_meta.empty:
        yahoo_meta = yahoo_meta.sort_values("retrieved_at").drop_duplicates("symbol", keep="last")
    security_master = seed.merge(yahoo_meta, on="symbol", how="left", suffixes=("_sec", "_yahoo"))
    quote_type = security_master.get("quoteType", pd.Series(index=security_master.index, dtype=object)).astype(str).str.upper()
    security_master["eligible_common_stock"] = quote_type.isin(["EQUITY", "NONE", "NAN", ""])
    security_master.to_parquet(output / "security_master.parquet", index=False, compression="zstd")

    analysts = _read_jsonl_files(analyst_paths)
    as_of = pd.Timestamp.utcnow().tz_localize(None)
    values_by_symbol: dict[str, dict[str, FeatureValue]] = {}
    quality_rows: list[dict[str, Any]] = []
    eligible = security_master.loc[security_master["eligible_common_stock"]].copy()
    for row in eligible.itertuples():
        symbol = str(row.symbol)
        cik = int(row.cik)
        prices = connection.execute("SELECT * FROM prices_daily WHERE symbol = ? ORDER BY date", [symbol]).df()
        values = calculate_price_features(prices)
        market_cap = getattr(row, "marketCap", None)
        if not _is_number(market_cap):
            market_cap = None
        facts = connection.execute("SELECT * FROM sec_companyfacts WHERE cik = ?", [cik]).df()
        concepts = latest_sec_concepts(facts, as_of)
        if market_cap is None and not prices.empty:
            shares = concepts.get("shares", [None])[0] if concepts.get("shares") else None
            if _is_number(shares):
                market_cap = float(prices["adj_close"].iloc[-1]) * float(shares)
        values.update(calculate_accounting_features(concepts, market_cap=market_cap))
        if market_cap is not None:
            values["Size"] = FeatureValue("Size", float(market_cap), "exact", "yfinance_sec", "current_market_cap")
        shares = concepts.get("shares", [None])[0] if concepts.get("shares") else None
        if _is_number(shares) and "ShareVol" in values and values["ShareVol"].raw_value is not None:
            values["ShareVol"] = FeatureValue("ShareVol", _safe_numeric_ratio(values["ShareVol"].raw_value, shares), "exact", "yfinance_sec", "mean_share_volume_over_sec_shares")
        if _is_number(shares) and "std_turn" in values and values["std_turn"].raw_value is not None:
            values["std_turn"] = FeatureValue("std_turn", _safe_numeric_ratio(values["std_turn"].raw_value, shares), "proxy", "yfinance_sec", "volume_std_over_sec_shares", "Uses current shares for the full window")
        symbol_options = connection.execute("SELECT * FROM yahoo_options_current WHERE symbol = ?", [symbol]).df()
        stock_volume = float(prices["volume"].tail(21).mean()) if not prices.empty else None
        realized = values.get("RealizedVol").raw_value if values.get("RealizedVol") else None
        values.update(_options_features(symbol_options, stock_volume, realized))
        symbol_analysts = analysts.loc[analysts["symbol"].eq(symbol)] if not analysts.empty else pd.DataFrame()
        values.update(_analyst_features(symbol_analysts))
        values_by_symbol[symbol] = values
        quality_rows.append(
            {
                "symbol": symbol,
                "cik": cik,
                "price_rows": len(prices),
                "first_price_date": prices["date"].min() if not prices.empty else None,
                "last_price_date": prices["date"].max() if not prices.empty else None,
                "sec_fact_rows": len(facts),
                "computed_features": sum(item.raw_value is not None for item in values.values()),
                "exact_features": sum(item.status == "exact" and item.raw_value is not None for item in values.values()),
                "proxy_features": sum(item.status == "proxy" and item.raw_value is not None for item in values.values()),
            }
        )

    feature_frame = assemble_feature_table(
        metadata,
        values_by_symbol,
        as_of=as_of.date().isoformat(),
        redundancy_groups=groups,
    )
    scores = calculate_scores(feature_frame, minimum_metrics=int(config["score"]["minimum_metrics_per_score"]))
    coverage = coverage_report(feature_frame, metadata)
    quality = pd.DataFrame(quality_rows)
    feature_frame.to_parquet(output / "openap_features_current.parquet", index=False, compression="zstd")
    scores.to_parquet(output / "openap_scores_current.parquet", index=False, compression="zstd")
    coverage.to_csv(output / "coverage_185.csv", index=False)
    quality.to_csv(output / "data_quality.csv", index=False)
    coverage.loc[coverage["coverage_status"].eq("proxy")].to_csv(output / "proxy_audit.csv", index=False)
    coverage.loc[coverage["coverage_status"].eq("unavailable")].to_csv(output / "unavailable_predictors.csv", index=False)
    metadata.to_csv(output / "selected_185_predictors.csv", index=False)
    groups.to_csv(output / "redundancy_groups.csv", index=False)

    connection.execute("CREATE OR REPLACE TABLE security_master AS SELECT * FROM read_parquet(?)", [str(output / "security_master.parquet")])
    connection.execute("CREATE OR REPLACE TABLE openap_features_current AS SELECT * FROM read_parquet(?)", [str(output / "openap_features_current.parquet")])
    connection.execute("CREATE OR REPLACE TABLE openap_scores_current AS SELECT * FROM read_parquet(?)", [str(output / "openap_scores_current.parquet")])
    duplicate_prices = int(
        connection.execute(
            "SELECT COALESCE(SUM(row_count - 1), 0) FROM "
            "(SELECT symbol, date, COUNT(*) AS row_count FROM prices_daily "
            "GROUP BY symbol, date HAVING COUNT(*) > 1)"
        ).fetchone()[0]
    )
    future_price_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM prices_daily WHERE CAST(date AS DATE) > CURRENT_DATE"
        ).fetchone()[0]
    )
    facts_without_available_at = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_companyfacts WHERE available_at IS NULL"
        ).fetchone()[0]
    )
    connection.close()

    exact_predictors = int((coverage["coverage_status"] == "exact").sum())
    proxy_predictors = int((coverage["coverage_status"] == "proxy").sum())
    unavailable_predictors = int((coverage["coverage_status"] == "unavailable").sum())
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in summary_paths]
    sec_summary = json.loads((sec_dir / "sec_bulk_summary.json").read_text(encoding="utf-8"))
    summary = {
        "dataset_id": config["dataset_id"],
        "completed_at": _utcnow(),
        "as_of": as_of.isoformat(),
        "input_predictors": len(metadata),
        "eligible_symbols": len(values_by_symbol),
        "price_rows": int(sum(int(item.get("price_rows", 0)) for item in summaries)),
        "sec_companyfacts_rows": int(sec_summary["companyfacts_rows"]),
        "sec_submissions_rows": int(sec_summary["submissions_rows"]),
        "exact_predictors_with_any_value": exact_predictors,
        "proxy_predictors_with_any_value": proxy_predictors,
        "unavailable_predictors": unavailable_predictors,
        "coverage_rows": len(coverage),
        "scores_rows": len(scores),
        "features_rows": len(feature_frame),
        "all_facts_have_available_at": bool(sec_summary["all_facts_have_available_at"]),
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": False,
        "raw_sec_archives_preserved_in_run": True,
        "duplicate_price_rows": duplicate_prices,
        "future_price_rows": future_price_rows,
        "facts_without_available_at": facts_without_available_at,
    }
    if duplicate_prices or future_price_rows or facts_without_available_at:
        raise OpenAPDataError(
            "Data-quality gate failed: "
            f"duplicate_prices={duplicate_prices}, future_prices={future_price_rows}, "
            f"facts_without_available_at={facts_without_available_at}"
        )
    if len(coverage) != EXPECTED_PREDICTORS or len(feature_frame) != len(values_by_symbol) * EXPECTED_PREDICTORS:
        raise OpenAPDataError("Final feature or coverage row counts do not reconcile")
    write_summary(output / "execution_summary.json", summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--predictor-summary", required=True)
    prepare_parser.add_argument("--predictor-returns", required=True)
    prepare_parser.add_argument("--sec-user-agent", required=True)
    prepare_parser.add_argument("--output-dir", required=True)
    yahoo_parser = subparsers.add_parser("yfinance-chunk")
    yahoo_parser.add_argument("--security-master", required=True)
    yahoo_parser.add_argument("--chunk-index", type=int, required=True)
    yahoo_parser.add_argument("--total-chunks", type=int, required=True)
    yahoo_parser.add_argument("--output-dir", required=True)
    sec_parser = subparsers.add_parser("sec-bulk")
    sec_parser.add_argument("--security-master", required=True)
    sec_parser.add_argument("--sec-user-agent", required=True)
    sec_parser.add_argument("--output-dir", required=True)
    merge_parser = subparsers.add_parser("merge")
    merge_parser.add_argument("--input-root", required=True)
    merge_parser.add_argument("--prepare-dir", required=True)
    merge_parser.add_argument("--sec-dir", required=True)
    merge_parser.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    require_github_actions_or_explicit_local_permission("OpenAP YFinance SEC current data pipeline")
    args = build_parser().parse_args()
    config = _read_config(args.config)
    if args.mode == "prepare":
        prepare(config, args)
    elif args.mode == "yfinance-chunk":
        yfinance_chunk(config, args)
    elif args.mode == "sec-bulk":
        sec_bulk(config, args)
    elif args.mode == "merge":
        merge(config, args)
    else:
        raise OpenAPDataError(f"Unsupported mode: {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

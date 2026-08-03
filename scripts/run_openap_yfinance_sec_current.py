"""GitHub-only OpenAP current data and score pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
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
    ACCOUNTING_PROXY_LIMITS,
    EXPECTED_PREDICTORS,
    FeatureValue,
    OpenAPDataError,
    SEC_CONCEPT_ALIASES,
    apply_accounting_input_freshness,
    assemble_feature_table,
    build_redundancy_groups,
    calculate_accounting_features,
    calculate_aggregate_scores,
    calculate_price_features,
    calculate_scores,
    clean_price_history,
    coverage_report,
    latest_sec_concept_inputs,
    redundancy_correlation_audit,
    refine_current_redundancy_groups,
    sec_concepts_from_inputs,
    select_strict_predictors,
    sha256_file,
    write_summary,
)


EXCLUDE_SECURITY_RE = re.compile(
    r"\b(?:ETF|ETN|EXCHANGE[- ]TRADED|MUTUAL FUND|CLOSED[- ]END FUND|INVESTMENT TRUST|"
    r"DEPOSITARY|ADR|ADS|WARRANTS?|RIGHTS?|UNITS|PREFERRED|PREF|SPAC|BLANK CHECK|"
    r"ACQUISITION (?:CORP|CO|COMPANY)|ACQUISITION LTD)\b",
    re.IGNORECASE,
)
PREFERRED_SYMBOL_RE = re.compile(r"-P[A-Z]$", re.IGNORECASE)
UNIT_SYMBOL_RE = re.compile(r"-(?:UN|U)$", re.IGNORECASE)
WARRANT_SYMBOL_RE = re.compile(r"-(?:WT|WS)$", re.IGNORECASE)
FOREIGN_SEC_FORMS = frozenset({"20-F", "40-F", "6-K", "F-1", "F-3", "F-4"})
INVESTMENT_COMPANY_FORMS = frozenset({"N-1A", "N-2", "N-CSR", "N-CSRS", "NPORT-P", "NPORT-NP"})
ALLOWED_EXCHANGE_RE = re.compile(r"NASDAQ|NYSE|NEW YORK STOCK EXCHANGE|CBOE", re.IGNORECASE)
_SEC_DIRECT_API_BLOCKED = False


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


def _sec_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Encoding": "gzip, deflate",
    }


def _select_chunk_rows(
    frame: pd.DataFrame,
    chunk_index: int,
    total_chunks: int,
) -> pd.DataFrame:
    """Return one stable round-robin DataFrame shard."""

    if total_chunks <= 0:
        raise OpenAPDataError("total_chunks must be positive")
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise OpenAPDataError(
            f"Invalid chunk {chunk_index} for {total_chunks} chunks"
        )
    return frame.reset_index(drop=True).iloc[chunk_index::total_chunks].copy()


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


def _sec_exchange_csv_rows(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str).fillna("")
    columns = {str(column).lower(): str(column) for column in frame.columns}
    required = {"cik", "ticker", "name", "exchange"}
    if not required.issubset(columns):
        raise OpenAPDataError(
            "SEC CIK mapper fallback is missing required columns"
        )
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        raw_ticker = str(record[columns["ticker"]]).strip().upper()
        symbol = raw_ticker.replace(".", "-")
        name = str(record[columns["name"]]).strip()
        exchange = str(record[columns["exchange"]]).strip()
        if not symbol or not ALLOWED_EXCHANGE_RE.search(exchange):
            continue
        if EXCLUDE_SECURITY_RE.search(name) or "$" in symbol or "^" in symbol:
            continue
        try:
            cik = int(str(record[columns["cik"]]).strip())
        except ValueError:
            continue
        rows.append(
            {
                "symbol": symbol,
                "sec_ticker": raw_ticker,
                "cik": cik,
                "company_name_sec": name,
                "exchange_sec": exchange,
                "asset_type": "COMMON_STOCK_CANDIDATE",
                "country": "United States",
                "source": "sec_cik_mapper_pinned_sec_derived",
                "retrieved_at": _utcnow(),
            }
        )
    result = (
        pd.DataFrame(rows)
        .drop_duplicates(["symbol", "cik"])
        .sort_values(["symbol", "cik"])
    )
    if result.empty:
        raise OpenAPDataError("SEC fallback universe is empty after filters")
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
    redundancy_correlation_audit(
        selected,
        returns,
        groups,
        threshold=float(config["openap"]["correlation_threshold"]),
        minimum_overlap=int(config["openap"]["minimum_overlap_months"]),
    ).to_csv(output / "redundancy_correlation_audit.csv", index=False)

    sec_payload_path = output / "company_tickers_exchange.json"
    sec_source_url = str(config["sec"]["ticker_exchange_url"])
    sec_source_mode = "sec_official_live"
    fallback_reason = ""
    try:
        _download(
            sec_source_url,
            sec_payload_path,
            headers=_sec_headers(args.sec_user_agent),
        )
        sec_payload = json.loads(sec_payload_path.read_text(encoding="utf-8"))
        universe = _sec_exchange_rows(sec_payload)
    except Exception as exc:
        fallback_reason = f"{type(exc).__name__}: {exc}"
        sec_payload_path = output / "sec_cik_mapper_mappings.csv"
        sec_source_url = str(config["sec"]["ticker_exchange_fallback_url"])
        sec_source_mode = "pinned_sec_derived_fallback"
        _download(sec_source_url, sec_payload_path)
        universe = _sec_exchange_csv_rows(sec_payload_path)
    universe.to_csv(output / "security_master_seed.csv", index=False)
    universe.to_parquet(output / "security_master_seed.parquet", index=False)
    cik_universe = (
        universe.sort_values(["cik", "symbol"])
        .drop_duplicates("cik", keep="first")[["cik", "symbol"]]
        .reset_index(drop=True)
    )
    cik_universe.to_parquet(output / "sec_cik_universe.parquet", index=False)

    source_rows = [
        {"source": "PredictorSummary.xlsx", "source_url": f"https://drive.google.com/uc?id={config['openap']['predictor_summary_gdrive_id']}", "source_mode": "openap_official_gdrive", "sha256": sha256_file(args.predictor_summary), "role": "selection_and_evidence"},
        {"source": "PredictorLSretWide.csv", "source_url": f"https://drive.google.com/uc?id={config['openap']['predictor_returns_gdrive_id']}", "source_mode": "openap_official_gdrive", "sha256": sha256_file(args.predictor_returns), "role": "redundancy_groups"},
        {
            "source": sec_payload_path.name,
            "source_url": sec_source_url,
            "source_mode": sec_source_mode,
            "sha256": sha256_file(sec_payload_path),
            "role": "ticker_cik_universe",
        },
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
            "sec_cik_rows": len(cik_universe),
            "redundancy_groups": int(groups["redundancy_group"].nunique()),
            "openap_commit": config["openap"]["commit"],
            "ticker_universe_source_mode": sec_source_mode,
            "ticker_universe_fallback_reason": fallback_reason,
            "ticker_universe_fallback_commit": config["sec"].get(
                "ticker_exchange_fallback_commit", ""
            ),
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
                target = pd.Timestamp.now(tz="UTC").tz_localize(None) + pd.Timedelta(days=int(config["yfinance"].get("target_option_days", 30)))
                candidates = sorted(
                    expirations,
                    key=lambda item: abs((pd.Timestamp(item) - target).days),
                )[: int(config["yfinance"].get("maximum_option_expiries", 3))]
                for expiration in candidates:
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
    chunk_index = int(args.chunk_index)
    selected = _select_chunk_rows(universe, chunk_index, int(args.total_chunks))
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
        def item(name: str, position: int = index) -> Any:
            values = arrays.get(name, [])
            return values[position] if position < len(values) else None

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
                "entity_type": payload.get("entityType"),
                "sic": payload.get("sic"),
                "sic_description": payload.get("sicDescription"),
                "fiscal_year_end": payload.get("fiscalYearEnd"),
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


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_from_jina_text(text: str) -> Mapping[str, Any]:
    marker = "Markdown Content:"
    if marker not in text:
        raise OpenAPDataError("Jina SEC fallback response lacks JSON marker")
    candidate = text.split(marker, 1)[1].strip()
    if candidate.startswith("```json"):
        candidate = candidate[7:]
    if candidate.startswith("```"):
        candidate = candidate[3:]
    if candidate.endswith("```"):
        candidate = candidate[:-3]
    # Jina can preserve raw control characters present in SEC company names.
    # Non-strict mode accepts those characters while retaining JSON structure
    # validation and the existing object-type check below.
    payload = json.loads(candidate.strip(), strict=False)
    if not isinstance(payload, Mapping):
        raise OpenAPDataError("Jina SEC fallback did not return a JSON object")
    return payload


def _request_sec_json(
    direct_url: str,
    fallback_url: str,
    *,
    headers: Mapping[str, str],
    retries: int = 3,
) -> tuple[Mapping[str, Any], str, str]:
    """Fetch SEC JSON directly, then through a public read-through fallback."""

    import requests

    global _SEC_DIRECT_API_BLOCKED
    errors: list[str] = []
    for source_mode, url in (("sec_official_api", direct_url), ("sec_via_jina_readthrough", fallback_url)):
        if source_mode == "sec_official_api" and _SEC_DIRECT_API_BLOCKED:
            errors.append("sec_official_api:skipped_after_earlier_401_or_403")
            continue
        for attempt in range(retries):
            try:
                response = requests.get(
                    url,
                    headers=dict(headers) if source_mode == "sec_official_api" else {"Accept": "text/plain"},
                    timeout=(20, 120),
                )
                if source_mode == "sec_official_api" and response.status_code in {401, 403}:
                    _SEC_DIRECT_API_BLOCKED = True
                response.raise_for_status()
                if source_mode == "sec_official_api":
                    payload = response.json()
                    if not isinstance(payload, Mapping):
                        raise OpenAPDataError("SEC API did not return a JSON object")
                else:
                    payload = _json_from_jina_text(response.text)
                return payload, source_mode, url
            except Exception as exc:
                errors.append(f"{source_mode}:{type(exc).__name__}:{exc}")
                if source_mode == "sec_official_api" and _SEC_DIRECT_API_BLOCKED:
                    break
                if attempt + 1 < retries:
                    time.sleep(2 ** attempt)
        if source_mode == "sec_official_api":
            continue
    raise OpenAPDataError("SEC JSON unavailable: " + " | ".join(errors[-4:]))


def _companyfacts_rows(
    payload: Mapping[str, Any],
    cik: int,
    *,
    source_url: str,
    source_mode: str,
    accepted_at_by_accession: Mapping[str, Any] | None = None,
    observations_per_tag: int = 24,
) -> list[dict[str, Any]]:
    wanted_tags = {
        alias
        for aliases in SEC_CONCEPT_ALIASES.values()
        for alias in aliases
    }
    entity_name = str(payload.get("entityName") or "")
    facts = payload.get("facts", {})
    if not isinstance(facts, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, Mapping):
            continue
        for tag, definition in concepts.items():
            if str(tag) not in wanted_tags or not isinstance(definition, Mapping):
                continue
            units = definition.get("units", {})
            if not isinstance(units, Mapping):
                continue
            for unit, observations in units.items():
                if not isinstance(observations, list):
                    continue
                usable = [item for item in observations if isinstance(item, Mapping) and item.get("end")]
                usable.sort(key=lambda item: (str(item.get("end") or ""), str(item.get("filed") or "")))
                by_period: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
                for observation in usable:
                    key = (
                        str(observation.get("end") or ""),
                        str(observation.get("start") or ""),
                        str(observation.get("form") or ""),
                        str(observation.get("fp") or ""),
                    )
                    by_period[key] = observation
                for observation in list(by_period.values())[-observations_per_tag:]:
                    filed = pd.to_datetime(observation.get("filed"), errors="coerce", utc=True)
                    if pd.isna(filed):
                        continue
                    accession = str(observation.get("accn") or "")
                    accepted = pd.to_datetime(
                        (accepted_at_by_accession or {}).get(accession),
                        errors="coerce",
                        utc=True,
                    )
                    if pd.isna(accepted):
                        accepted = filed + pd.Timedelta(days=1)
                        available_quality = "conservative_filing_date_plus_one_day"
                    elif accepted.normalize() < filed.normalize():
                        accepted = filed + pd.Timedelta(days=1)
                        available_quality = "sec_acceptance_before_filing_clamped_plus_one_day"
                    else:
                        available_quality = "sec_acceptance_timestamp"
                    rows.append(
                        {
                            "cik": cik,
                            "entity_name": entity_name,
                            "taxonomy": str(taxonomy),
                            "tag": str(tag),
                            "unit": str(unit),
                            "value": observation.get("val"),
                            "period_start": observation.get("start"),
                            "period_end": observation.get("end"),
                            "fy": observation.get("fy"),
                            "fp": observation.get("fp"),
                            "form": observation.get("form"),
                            "filed": observation.get("filed"),
                            "accession_number": accession,
                            "frame": observation.get("frame"),
                            "available_at": accepted,
                            "available_at_quality": available_quality,
                            "source": source_url,
                            "source_mode": source_mode,
                        }
                    )
    return rows


def sec_chunk(config: dict[str, Any], args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    raw_dir = output / "raw"
    lake_dir = output / "lake"
    raw_dir.mkdir(parents=True, exist_ok=True)
    lake_dir.mkdir(parents=True, exist_ok=True)
    universe = pd.read_parquet(args.security_master)
    chunk_index = int(args.chunk_index)
    total_chunks = int(args.total_chunks)
    selected = _select_chunk_rows(universe, chunk_index, total_chunks)
    selected = selected.drop_duplicates("cik")
    headers = _sec_headers(args.sec_user_agent)
    interval = float(config["sec"].get("request_interval_seconds", 1.0))
    fact_rows: list[dict[str, Any]] = []
    submission_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    raw_zip_path = raw_dir / f"sec_raw_{chunk_index:03d}.zip"

    with zipfile.ZipFile(raw_zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for row in selected.itertuples():
            cik = int(row.cik)
            cik_text = f"{cik:010d}"
            companyfacts_direct = str(config["sec"]["companyfacts_api_template"]).format(cik=cik_text)
            companyfacts_fallback = str(config["sec"]["companyfacts_fallback_template"]).format(cik=cik_text)
            submissions_direct = str(config["sec"]["submissions_api_template"]).format(cik=cik_text)
            submissions_fallback = str(config["sec"]["submissions_fallback_template"]).format(cik=cik_text)
            companyfacts_payload: Mapping[str, Any] | None = None
            accepted_at_by_accession: dict[str, Any] = {}
            try:
                submissions_payload, source_mode, source_url = _request_sec_json(
                    submissions_direct,
                    submissions_fallback,
                    headers=headers,
                )
                raw_bytes = _canonical_json_bytes(submissions_payload)
                archive.writestr(f"submissions/CIK{cik_text}.json", raw_bytes)
                rows = _submission_rows(submissions_payload, cik)
                for item in rows:
                    item["source"] = source_url
                    item["source_mode"] = source_mode
                    accession = str(item.get("accession_number") or "")
                    accepted = item.get("accepted_at")
                    if accession and accepted:
                        accepted_at_by_accession[accession] = accepted
                submission_rows.extend(rows)
                source_counts[source_mode] = source_counts.get(source_mode, 0) + 1
                status_rows.append(
                    {
                        "cik": cik,
                        "symbol": str(row.symbol),
                        "surface": "submissions",
                        "status": "ok",
                        "rows": len(rows),
                        "source_mode": source_mode,
                        "source_url": source_url,
                        "canonical_json_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                        "error": "",
                    }
                )
            except Exception as exc:
                status_rows.append(
                    {
                        "cik": cik,
                        "symbol": str(row.symbol),
                        "surface": "submissions",
                        "status": "error",
                        "rows": 0,
                        "source_mode": "unavailable",
                        "source_url": submissions_direct,
                        "canonical_json_sha256": "",
                        "error": str(exc)[:1000],
                    }
                )
            try:
                companyfacts_payload, source_mode, source_url = _request_sec_json(
                    companyfacts_direct,
                    companyfacts_fallback,
                    headers=headers,
                )
                raw_bytes = _canonical_json_bytes(companyfacts_payload)
                archive.writestr(f"companyfacts/CIK{cik_text}.json", raw_bytes)
                rows = _companyfacts_rows(
                    companyfacts_payload,
                    cik,
                    source_url=source_url,
                    source_mode=source_mode,
                    accepted_at_by_accession=accepted_at_by_accession,
                )
                fact_rows.extend(rows)
                source_counts[source_mode] = source_counts.get(source_mode, 0) + 1
                status_rows.append(
                    {
                        "cik": cik,
                        "symbol": str(row.symbol),
                        "surface": "companyfacts",
                        "status": "ok",
                        "rows": len(rows),
                        "source_mode": source_mode,
                        "source_url": source_url,
                        "canonical_json_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                        "error": "",
                    }
                )
            except Exception as exc:
                status_rows.append(
                    {
                        "cik": cik,
                        "symbol": str(row.symbol),
                        "surface": "companyfacts",
                        "status": "error",
                        "rows": 0,
                        "source_mode": "unavailable",
                        "source_url": companyfacts_direct,
                        "canonical_json_sha256": "",
                        "error": str(exc)[:1000],
                    }
                )

            time.sleep(interval)

    facts = _normalise_fact_batch(pd.DataFrame(fact_rows)) if fact_rows else pd.DataFrame(
        columns=["cik", "entity_name", "taxonomy", "tag", "unit", "value", "period_start", "period_end", "fy", "fp", "form", "filed", "accession_number", "frame", "available_at", "available_at_quality", "source", "source_mode"]
    )
    submissions = pd.DataFrame(submission_rows)
    if submissions.empty:
        submissions = pd.DataFrame(columns=[
            "cik", "accession_number", "filing_date", "accepted_at", "report_date",
            "form", "primary_document", "is_xbrl", "entity_type", "sic",
            "sic_description", "fiscal_year_end", "source", "source_mode",
        ])
    else:
        submissions["accepted_at"] = pd.to_datetime(submissions["accepted_at"], errors="coerce", utc=True)
    facts_path = lake_dir / f"sec_companyfacts_{chunk_index:03d}.parquet"
    submissions_path = lake_dir / f"sec_submissions_{chunk_index:03d}.parquet"
    facts.to_parquet(facts_path, index=False, compression="zstd")
    submissions.to_parquet(submissions_path, index=False, compression="zstd")
    status = pd.DataFrame(status_rows)
    status.to_csv(output / f"sec_status_{chunk_index:03d}.csv", index=False)
    summary = {
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "ciks_expected": int(selected["cik"].nunique()),
            "companyfacts_ciks_ok": int(status.loc[(status["surface"] == "companyfacts") & (status["status"] == "ok"), "cik"].nunique()),
            "submissions_ciks_ok": int(status.loc[(status["surface"] == "submissions") & (status["status"] == "ok"), "cik"].nunique()),
            "companyfacts_rows": len(facts),
            "submissions_rows": len(submissions),
            "source_counts": source_counts,
            "raw_zip_bytes": raw_zip_path.stat().st_size,
            "raw_zip_sha256": sha256_file(raw_zip_path),
            "all_facts_have_available_at": bool(not facts.empty and facts["available_at"].notna().all()),
            "locked_opened": False,
            "retrieved_at": _utcnow(),
        }
    write_summary(output / f"sec_summary_{chunk_index:03d}.json", summary)
    if selected.empty or facts.empty or submissions.empty:
        raise OpenAPDataError(
            "SEC shard is empty: "
            f"chunk={chunk_index}, selected={len(selected)}, facts={len(facts)}, "
            f"submissions={len(submissions)}"
        )


def sec_bulk(config: dict[str, Any], args: argparse.Namespace) -> None:
    output = Path(args.output_dir)
    raw_dir = output / "raw"
    lake_dir = output / "lake"
    raw_dir.mkdir(parents=True, exist_ok=True)
    lake_dir.mkdir(parents=True, exist_ok=True)
    universe = pd.read_parquet(args.security_master)
    ciks = set(pd.to_numeric(universe["cik"], errors="coerce").dropna().astype(int).tolist())
    headers = _sec_headers(args.sec_user_agent)
    companyfacts_zip = raw_dir / "companyfacts.zip"
    submissions_zip = raw_dir / "submissions.zip"
    _download(config["sec"]["companyfacts_bulk_url"], companyfacts_zip, headers=headers)
    _download(config["sec"]["submissions_bulk_url"], submissions_zip, headers=headers)

    submission_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(submissions_zip) as archive:
        for member in archive.namelist():
            cik = _cik_from_member(member)
            if cik is None or cik not in ciks or not member.lower().endswith(".json"):
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
    submissions_path = lake_dir / "sec_submissions_000.parquet"
    submissions.to_parquet(submissions_path, index=False, compression="zstd")
    accepted_map: dict[int, dict[str, Any]] = {}
    for row in submissions.itertuples():
        if pd.isna(row.accession_number) or pd.isna(row.accepted_at):
            continue
        accepted_map.setdefault(int(row.cik), {})[
            str(row.accession_number)
        ] = row.accepted_at

    def fact_batches() -> Iterable[pd.DataFrame]:
        buffer: list[dict[str, Any]] = []
        with zipfile.ZipFile(companyfacts_zip) as archive:
            for member in archive.namelist():
                cik = _cik_from_member(member)
                if cik is None or cik not in ciks or not member.lower().endswith(".json"):
                    continue
                try:
                    payload = json.loads(archive.read(member).decode("utf-8", errors="replace"))
                except Exception:
                    continue
                buffer.extend(
                    _companyfacts_rows(
                        payload,
                        cik,
                        source_url=f"zip://companyfacts.zip#{member}",
                        source_mode="sec_official_bulk_archive",
                        accepted_at_by_accession=accepted_map.get(cik, {}),
                    )
                )
                if len(buffer) >= 100_000:
                    yield _normalise_fact_batch(pd.DataFrame(buffer))
                    buffer = []
        if buffer:
            yield _normalise_fact_batch(pd.DataFrame(buffer))

    companyfacts_path = lake_dir / "sec_companyfacts_000.parquet"
    fact_count = _write_parquet_batches(companyfacts_path, fact_batches())
    fact_index = pd.read_parquet(
        companyfacts_path, columns=["cik", "available_at"]
    )
    fact_ciks = set(
        fact_index["cik"].dropna().astype(int).unique().tolist()
    )
    all_facts_have_available_at = bool(
        not fact_index.empty and fact_index["available_at"].notna().all()
    )
    submission_ciks = set(
        pd.to_numeric(submissions["cik"], errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    status_rows = []
    for cik in sorted(ciks):
        for surface, available in (
            ("companyfacts", cik in fact_ciks),
            ("submissions", cik in submission_ciks),
        ):
            status_rows.append(
                {
                    "chunk_index": 0,
                    "cik": cik,
                    "surface": surface,
                    "status": "ok" if available else "missing",
                    "source_mode": "sec_official_bulk_archive",
                    "error": "" if available else "CIK absent from official bulk archive",
                }
            )
    pd.DataFrame(status_rows).to_csv(output / "sec_status_000.csv", index=False)
    manifest = {
        "chunk_index": 0,
        "total_chunks": 1,
        "source_layout": "official_bulk_archive",
        "retrieved_at": _utcnow(),
        "universe_ciks": len(ciks),
        "ciks_expected": len(ciks),
        "companyfacts_ciks_ok": len(fact_ciks),
        "submissions_ciks_ok": len(submission_ciks),
        "submissions_rows": len(submissions),
        "companyfacts_rows": fact_count,
        "companyfacts_zip_bytes": companyfacts_zip.stat().st_size,
        "companyfacts_zip_sha256": sha256_file(companyfacts_zip),
        "submissions_zip_bytes": submissions_zip.stat().st_size,
        "submissions_zip_sha256": sha256_file(submissions_zip),
        "all_facts_have_available_at": all_facts_have_available_at,
        "locked_opened": False,
    }
    write_summary(output / "sec_summary_000.json", manifest)


def _read_jsonl_files(paths: Iterable[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return pd.DataFrame(rows)


def _options_features(
    frame: pd.DataFrame,
    stock_volume: float | None,
    realized_vol: float | None,
    *,
    stock_price: float | None = None,
    as_of: pd.Timestamp | None = None,
    config: Mapping[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, FeatureValue]:
    if frame.empty:
        if audit is not None:
            audit.update({"option_contracts_raw": 0, "option_contracts_usable": 0})
        return {}
    data = frame.copy()
    raw_contracts = len(data)
    settings = (config or {}).get("yfinance", config or {})
    for column in ("impliedVolatility", "volume", "openInterest", "strike", "bid", "ask"):
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    now = pd.Timestamp(as_of or pd.Timestamp.now(tz="UTC")).tz_localize(None)
    expiration_source = data.get("expiration", pd.Series(pd.NaT, index=data.index))
    trade_source = data.get("lastTradeDate", pd.Series(pd.NaT, index=data.index))
    data["expiration"] = pd.to_datetime(expiration_source, errors="coerce").dt.tz_localize(None)
    data["lastTradeDate"] = pd.to_datetime(trade_source, errors="coerce", utc=True).dt.tz_localize(None)
    data["days_to_expiry"] = (data["expiration"] - now.normalize()).dt.days
    valid = (
        data["days_to_expiry"].between(
            int(settings.get("minimum_option_days", 14)),
            int(settings.get("maximum_option_days", 60)),
        )
        & data["impliedVolatility"].between(
            float(settings.get("minimum_implied_volatility", 0.01)),
            float(settings.get("maximum_implied_volatility", 5.0)),
        )
        & data["lastTradeDate"].ge(
            now - pd.Timedelta(days=int(settings.get("maximum_option_staleness_days", 14)))
        )
    )
    if {"bid", "ask"}.issubset(data.columns):
        valid &= data["bid"].fillna(0).ge(0) & data["ask"].fillna(0).ge(data["bid"].fillna(0))
    if stock_price is not None and _is_number(stock_price):
        moneyness = data["strike"] / float(stock_price)
        valid &= moneyness.between(
            float(settings.get("minimum_option_moneyness", 0.80)),
            float(settings.get("maximum_option_moneyness", 1.20)),
        )
    data = data.loc[valid].copy()
    if data.empty:
        if audit is not None:
            audit.update({"option_contracts_raw": raw_contracts, "option_contracts_usable": 0})
        return {}
    target_days = int(settings.get("target_option_days", 30))
    minimum_per_side = int(settings.get("minimum_option_contracts_per_side", 1))
    minimum_total = int(settings.get("minimum_option_contracts_total", 2))
    expiry_depth = (
        data.assign(
            is_call=data["option_type"].eq("call").astype(int),
            is_put=data["option_type"].eq("put").astype(int),
        )
        .groupby("expiration", as_index=False)
        .agg(
            days_to_expiry=("days_to_expiry", "first"),
            contracts=("option_type", "size"),
            calls=("is_call", "sum"),
            puts=("is_put", "sum"),
        )
    )
    expiry_depth["distance"] = (expiry_depth["days_to_expiry"] - target_days).abs()
    qualifying_expiries = expiry_depth.loc[
        expiry_depth["calls"].ge(minimum_per_side)
        & expiry_depth["puts"].ge(minimum_per_side)
        & expiry_depth["contracts"].ge(minimum_total)
    ].sort_values(["distance", "expiration"])
    if qualifying_expiries.empty:
        if audit is not None:
            audit.update(
                {
                    "option_contracts_raw": raw_contracts,
                    "option_contracts_usable": len(data),
                    "option_calls_usable": int(data["option_type"].eq("call").sum()),
                    "option_puts_usable": int(data["option_type"].eq("put").sum()),
                    "option_depth_pass": False,
                    "option_rejection_reason": "insufficient_contract_depth",
                }
            )
        return {}
    nearest_expiry = qualifying_expiries.iloc[0]["expiration"]
    data = data.loc[data["expiration"].eq(nearest_expiry)]
    if audit is not None:
        audit.update(
            {
                "option_contracts_raw": raw_contracts,
                "option_contracts_usable": len(data),
                "option_expiry_used": pd.Timestamp(nearest_expiry).date().isoformat(),
            }
        )
    calls = data.loc[data["option_type"].eq("call")]
    puts = data.loc[data["option_type"].eq("put")]
    if (
        len(calls) < minimum_per_side
        or len(puts) < minimum_per_side
        or len(data) < minimum_total
    ):
        if audit is not None:
            audit.update(
                {
                    "option_contracts_raw": raw_contracts,
                    "option_contracts_usable": len(data),
                    "option_calls_usable": len(calls),
                    "option_puts_usable": len(puts),
                    "option_depth_pass": False,
                    "option_rejection_reason": "insufficient_contract_depth",
                }
            )
        return {}
    if audit is not None:
        audit.update(
            {
                "option_calls_usable": len(calls),
                "option_puts_usable": len(puts),
                "option_depth_pass": True,
                "option_rejection_reason": "",
            }
        )
    call_iv = calls["impliedVolatility"].median() if "impliedVolatility" in calls else np.nan
    put_iv = puts["impliedVolatility"].median() if "impliedVolatility" in puts else np.nan
    total_volume = data["volume"].sum(min_count=1) if "volume" in data else np.nan
    total_oi = data["openInterest"].sum(min_count=1) if "openInterest" in data else np.nan
    values: dict[str, FeatureValue] = {
        "CPVolSpread": FeatureValue("CPVolSpread", float(call_iv - put_iv) if pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "median_call_iv_minus_put_iv", "Current chain replaces OptionMetrics filters"),
        "OptionVolume1": FeatureValue("OptionVolume1", _safe_numeric_ratio(total_volume, stock_volume), "proxy", "yfinance_current_option_chain", "option_volume_over_stock_volume", "Current nearest-expiry chain only"),
        "OptionVolume2": FeatureValue(
            "OptionVolume2",
            _safe_numeric_ratio(total_oi, stock_volume)
            if pd.notna(total_oi) and float(total_oi) > 0
            else None,
            "proxy",
            "yfinance_current_option_chain",
            "option_oi_over_stock_volume",
            "Open interest proxy for total option activity",
        ),
        "SmileSlope": FeatureValue("SmileSlope", float(put_iv - call_iv) if pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "put_iv_minus_call_iv", "Median IV spread replaces matched-delta smile slope"),
        "skew1": FeatureValue("skew1", float(put_iv - call_iv) if pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "put_iv_minus_call_iv", "Current-chain smirk proxy"),
        "RIVolSpread": FeatureValue("RIVolSpread", float(realized_vol * math.sqrt(252.0) - (call_iv + put_iv) / 2) if realized_vol is not None and pd.notna(call_iv) and pd.notna(put_iv) else None, "proxy", "yfinance_current_option_chain", "annualized_realized_minus_median_implied_vol", "Current-chain proxy with compatible annualized units"),
    }
    return values


def _normalise_fact_batch(frame: pd.DataFrame) -> pd.DataFrame:
    """Force a stable Arrow schema across all SEC fact batches."""

    out = frame.copy()
    if "source_mode" not in out:
        out["source_mode"] = "sec_bulk_archive"
    out["cik"] = pd.to_numeric(out["cik"], errors="coerce").astype("Int64")
    out["value"] = pd.to_numeric(out["value"], errors="coerce")
    out["fy"] = pd.to_numeric(out["fy"], errors="coerce").astype("Int64")
    for column in (
        "entity_name", "taxonomy", "tag", "unit", "period_start", "period_end",
        "fp", "form", "filed", "accession_number", "frame", "available_at_quality",
        "source", "source_mode",
    ):
        out[column] = out[column].astype("string")
    out["available_at"] = pd.to_datetime(out["available_at"], errors="coerce", utc=True)
    return out[
        [
            "cik", "entity_name", "taxonomy", "tag", "unit", "value", "period_start",
            "period_end", "fy", "fp", "form", "filed", "accession_number", "frame",
            "available_at", "available_at_quality", "source", "source_mode",
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


def _resolve_current_shares_outstanding(
    sec_shares: Any,
    yahoo_shares: Any,
    *,
    maximum_ratio: float = 2.0,
) -> FeatureValue:
    """Resolve current shares without trusting an implausible SEC class/unit value."""

    sec_value = float(sec_shares) if _is_number(sec_shares) and float(sec_shares) > 0 else None
    yahoo_value = (
        float(yahoo_shares)
        if _is_number(yahoo_shares) and float(yahoo_shares) > 0
        else None
    )
    if sec_value is not None and yahoo_value is not None:
        ratio = max(sec_value, yahoo_value) / min(sec_value, yahoo_value)
        if ratio <= float(maximum_ratio):
            return FeatureValue(
                "shares_outstanding",
                sec_value,
                "exact",
                "sec_edgar_cross_validated",
                "latest_instant_shares",
                f"SEC/Yahoo ratio={ratio:.4f}",
            )
        return FeatureValue(
            "shares_outstanding",
            yahoo_value,
            "proxy",
            "yfinance_current_shares",
            "yfinance_shares_after_sec_mismatch",
            f"SEC/Yahoo mismatch ratio={ratio:.4f}; rejected SEC value {sec_value:g}",
        )
    if yahoo_value is not None:
        return FeatureValue(
            "shares_outstanding",
            yahoo_value,
            "proxy",
            "yfinance_current_shares",
            "yfinance_current_shares",
            "SEC shares unavailable; Yahoo snapshot used",
        )
    if sec_value is not None:
        return FeatureValue(
            "shares_outstanding",
            sec_value,
            "proxy",
            "sec_edgar_unvalidated_shares",
            "latest_instant_shares_unvalidated",
            "Yahoo shares unavailable; SEC value could not be cross-validated",
        )
    return FeatureValue(
        "shares_outstanding",
        None,
        "unavailable",
        "missing_shares_outstanding",
        "",
        "Neither SEC nor Yahoo supplied a positive current share count",
    )


def _share_turnover_features(
    prices: pd.DataFrame,
    resolved_shares: FeatureValue | None,
) -> dict[str, FeatureValue]:
    """Calculate OpenAP-style turnover features only in dimensionless units."""

    missing = {
        "ShareVol": FeatureValue(
            "ShareVol", None, "unavailable", "missing_shares_outstanding", "", "Share count required"
        ),
        "std_turn": FeatureValue(
            "std_turn", None, "unavailable", "missing_shares_outstanding", "", "Share count required"
        ),
    }
    if (
        prices.empty
        or resolved_shares is None
        or not _is_number(resolved_shares.raw_value)
        or float(resolved_shares.raw_value) <= 0
    ):
        return missing
    data = prices.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["volume"] = pd.to_numeric(data["volume"], errors="coerce")
    monthly_volume = (
        data.dropna(subset=["date", "volume"])
        .set_index("date")["volume"]
        .resample("ME")
        .sum(min_count=1)
        .dropna()
    )
    if monthly_volume.empty:
        return missing
    shares = float(resolved_shares.raw_value)
    monthly_turnover = monthly_volume / shares
    three_month_turnover = (
        float(monthly_volume.iloc[-3:].sum()) / (3.0 * shares)
        if len(monthly_volume) >= 3
        else None
    )
    sharevol = None
    if three_month_turnover is not None:
        if three_month_turnover > 0.10:
            sharevol = 1.0
        elif three_month_turnover < 0.05:
            sharevol = 0.0
    status = "exact" if resolved_shares.status == "exact" else "proxy"
    note = resolved_shares.note
    std_turn = (
        float(monthly_turnover.iloc[-36:].std(ddof=1))
        if len(monthly_turnover) >= 36
        else None
    )
    return {
        "ShareVol": FeatureValue(
            "ShareVol",
            sharevol,
            status,
            resolved_shares.source,
            "openap_sharevol_binary_3m_turnover",
            note,
        ),
        "std_turn": FeatureValue(
            "std_turn",
            std_turn,
            "proxy" if std_turn is not None else "unavailable",
            resolved_shares.source,
            "monthly_turnover_std_36m" if std_turn is not None else "",
            "Current shares applied to historical monthly volume; " + note,
        ),
    }


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
        up_values = [
            float(value)
            for key, value in latest.items()
            if "up" in str(key).lower() and _is_number(value)
        ]
        down_values = [
            float(value)
            for key, value in latest.items()
            if "down" in str(key).lower() and _is_number(value)
        ]
        up = float(sum(up_values)) if up_values else None
        down = float(sum(down_values)) if down_values else None
        net = up - down if up is not None and down is not None else None
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


def _hashes_by_chunk(paths: Iterable[Path]) -> dict[int, str]:
    result: dict[int, str] = {}
    for path in paths:
        match = re.search(r"_(\d{3})(?:\.[^.]+)$", path.name)
        if match:
            result[int(match.group(1))] = sha256_file(path)
    return result


DATABASE_UNIQUE_KEYS: dict[str, tuple[str, ...]] = {
    "prices_daily_raw": ("symbol", "date"),
    "prices_daily_clean": ("symbol", "date"),
    "security_master": ("symbol",),
    "sec_companyfacts": ("fact_identity",),
    "sec_submissions": ("cik", "accession_number", "form", "filing_date"),
    "sec_concept_inputs_current": ("symbol", "concept", "concept_lag"),
    "openap_features_current": ("as_of", "symbol", "signalname"),
    "openap_scores_current": ("as_of", "symbol", "horizon_months"),
    "openap_overall_scores_current": ("as_of", "symbol", "horizon_months"),
    "openap_scores_aggregate_current": ("as_of", "symbol"),
    "openap_score_contributions_current": (
        "as_of", "symbol", "horizon_months", "signalname"
    ),
    "openap_current_leaderboard": ("as_of", "symbol"),
    "openap_current_deployable_leaderboard": ("as_of", "symbol"),
    "selected_predictors": ("signalname",),
    "redundancy_groups": ("signalname",),
    "current_redundancy_groups": ("signalname",),
    "overall_redundancy_groups": ("signalname",),
    "coverage_185": ("signalname",),
    "price_quality_current": ("symbol",),
    "data_quality_current": ("symbol",),
    "yahoo_options_raw": ("contractSymbol",),
    "yahoo_options_usable": ("contractSymbol",),
    "source_manifest": ("source",),
    "yfinance_source_manifest": ("chunk_index",),
    "sec_source_manifest": ("chunk_index",),
}

DATABASE_REQUIRED_NON_NULL: dict[str, tuple[str, ...]] = {
    "prices_daily_raw": ("symbol", "date", "adj_close"),
    "prices_daily_clean": ("symbol", "date", "adj_close"),
    "security_master": (
        "symbol", "cik", "eligible_common_stock", "ranking_eligible",
        "sec_companyfacts_available", "sec_submissions_available",
    ),
    "sec_companyfacts": (
        "fact_identity", "cik", "taxonomy", "tag", "unit", "value",
        "period_end", "filed", "accession_number", "available_at",
    ),
    "sec_submissions": ("cik", "accession_number", "form", "filing_date"),
    "sec_concept_inputs_current": ("symbol", "concept", "concept_lag", "available_at"),
    "openap_features_current": (
        "as_of", "symbol", "signalname", "status", "value_status",
        "official_filter_status",
    ),
    "openap_scores_current": (
        "as_of", "symbol", "horizon_months", "metrics_expected", "groups_expected",
    ),
    "openap_overall_scores_current": (
        "as_of", "symbol", "horizon_months", "metrics_expected", "groups_expected",
    ),
    "openap_scores_aggregate_current": (
        "as_of", "symbol", "score_validation_status", "required_horizons",
    ),
    "openap_score_contributions_current": (
        "as_of", "symbol", "horizon_months", "signalname",
        "redundancy_group", "score_weight", "raw_score_contribution",
        "directional_contribution_vs_neutral",
    ),
    "openap_current_leaderboard": (
        "as_of", "symbol", "aggregate_score", "aggregate_confidence",
        "ranking_eligible", "clean_price_staleness_days",
    ),
    "openap_current_deployable_leaderboard": (
        "as_of", "symbol", "aggregate_score", "aggregate_confidence",
        "ranking_eligible", "deployment_eligible",
    ),
    "selected_predictors": ("signalname", "tstat", "Sign"),
    "redundancy_groups": ("signalname",),
    "current_redundancy_groups": ("signalname",),
    "overall_redundancy_groups": ("signalname",),
    "coverage_185": ("signalname",),
    "price_quality_current": ("symbol",),
    "data_quality_current": ("symbol",),
    "yahoo_options_raw": ("contractSymbol",),
    "yahoo_options_usable": ("contractSymbol",),
    "source_manifest": ("source",),
    "yfinance_source_manifest": ("chunk_index",),
    "sec_source_manifest": ("chunk_index",),
}


def _database_layer(table_name: str) -> str:
    if table_name.endswith("_raw"):
        return "raw"
    if table_name.endswith("_clean") or table_name.endswith("_usable"):
        return "clean"
    if "manifest" in table_name or "status" in table_name:
        return "provenance"
    if "audit" in table_name or "quality" in table_name or "coverage" in table_name:
        return "audit"
    return "derived"


def finalize_database_contract(
    connection: Any,
    output: Path,
    *,
    required_tables: set[str] | None = None,
) -> tuple[int, int, int]:
    """Create physical indexes and a complete contract for every DB object."""

    objects = connection.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    object_names = {str(row[0]) for row in objects}
    object_types = {str(row[0]): str(row[1]) for row in objects}
    contract_check_rows: list[dict[str, Any]] = []
    contract_tables = (
        set(required_tables)
        if required_tables is not None
        else set(DATABASE_UNIQUE_KEYS) | set(DATABASE_REQUIRED_NON_NULL)
    )
    for table_name in sorted(contract_tables):
        if table_name not in object_names:
            contract_check_rows.append(
                {
                    "table_name": table_name,
                    "check_type": "required_table",
                    "columns": "",
                    "issue_count": 1,
                    "passed": False,
                }
            )
            continue
        actual_columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        }
        required = DATABASE_REQUIRED_NON_NULL.get(table_name, ())
        missing_required = sorted(set(required).difference(actual_columns))
        if missing_required:
            contract_check_rows.append(
                {
                    "table_name": table_name,
                    "check_type": "required_columns",
                    "columns": ",".join(missing_required),
                    "issue_count": len(missing_required),
                    "passed": False,
                }
            )
        elif required:
            predicate = " OR ".join(f'"{column}" IS NULL' for column in required)
            null_count = int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table_name}" WHERE {predicate}'
                ).fetchone()[0]
            )
            contract_check_rows.append(
                {
                    "table_name": table_name,
                    "check_type": "required_non_null",
                    "columns": ",".join(required),
                    "issue_count": null_count,
                    "passed": null_count == 0,
                }
            )
        unique_columns = DATABASE_UNIQUE_KEYS.get(table_name, ())
        missing_unique = sorted(set(unique_columns).difference(actual_columns))
        if missing_unique:
            contract_check_rows.append(
                {
                    "table_name": table_name,
                    "check_type": "unique_key_columns",
                    "columns": ",".join(missing_unique),
                    "issue_count": len(missing_unique),
                    "passed": False,
                }
            )
        elif unique_columns:
            quoted = ", ".join(f'"{column}"' for column in unique_columns)
            duplicate_count = int(
                connection.execute(
                    f'SELECT COALESCE(SUM(n - 1), 0) FROM ('
                    f'SELECT {quoted}, COUNT(*) AS n FROM "{table_name}" '
                    f'GROUP BY {quoted} HAVING COUNT(*) > 1)'
                ).fetchone()[0]
            )
            contract_check_rows.append(
                {
                    "table_name": table_name,
                    "check_type": "unique_key",
                    "columns": ",".join(unique_columns),
                    "issue_count": duplicate_count,
                    "passed": duplicate_count == 0,
                }
            )
    for table_name, columns in sorted(DATABASE_REQUIRED_NON_NULL.items()):
        if table_name not in object_names:
            continue
        if object_types.get(table_name) != "BASE TABLE":
            contract_check_rows.append(
                {
                    "table_name": table_name,
                    "check_type": "physical_not_null_constraint",
                    "columns": ",".join(columns),
                    "issue_count": 1,
                    "passed": False,
                }
            )
            continue
        existing_failures = [
            row
            for row in contract_check_rows
            if row["table_name"] == table_name
            and row["check_type"] in {"required_columns", "required_non_null"}
            and not row["passed"]
        ]
        if existing_failures:
            continue
        failed_columns: list[str] = []
        for column in columns:
            try:
                connection.execute(
                    f'ALTER TABLE "{table_name}" ALTER COLUMN "{column}" SET NOT NULL'
                )
            except Exception:
                failed_columns.append(column)
        table_info = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        physically_required = {
            str(row[1]) for row in table_info if bool(row[3])
        }
        missing_constraints = sorted(set(columns).difference(physically_required))
        failed_columns = sorted(set(failed_columns) | set(missing_constraints))
        contract_check_rows.append(
            {
                "table_name": table_name,
                "check_type": "physical_not_null_constraint",
                "columns": ",".join(columns),
                "issue_count": len(failed_columns),
                "passed": not failed_columns,
            }
        )

    contract_checks = pd.DataFrame(contract_check_rows)
    contract_checks.to_csv(output / "database_contract_checks.csv", index=False)
    connection.register("database_contract_checks_frame", contract_checks)
    connection.execute(
        "CREATE OR REPLACE TABLE database_contract_checks AS "
        "SELECT * FROM database_contract_checks_frame"
    )
    connection.unregister("database_contract_checks_frame")

    index_rows: list[dict[str, Any]] = []
    for table_name, columns in DATABASE_UNIQUE_KEYS.items():
        if table_name not in object_names:
            continue
        failed_unique_check = any(
            row["table_name"] == table_name
            and row["check_type"] in {"unique_key_columns", "unique_key"}
            and not row["passed"]
            for row in contract_check_rows
        )
        if failed_unique_check:
            continue
        index_name = "ux_" + re.sub(r"[^a-zA-Z0-9_]", "_", table_name)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        connection.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" '
            f'ON "{table_name}" ({quoted_columns})'
        )
        index_rows.append(
            {
                "index_name": index_name,
                "table_name": table_name,
                "columns": ",".join(columns),
                "unique": True,
            }
        )
    index_contract = pd.DataFrame(index_rows)
    index_contract.to_csv(output / "index_contract.csv", index=False)
    connection.execute(
        "CREATE OR REPLACE TABLE index_contract AS SELECT * FROM read_csv_auto(?)",
        [str(output / "index_contract.csv")],
    )

    objects = connection.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    if "schema_contract" not in {str(row[0]) for row in objects}:
        objects.append(("schema_contract", "BASE TABLE"))
    schema_rows = []
    for table_name, table_type in objects:
        name = str(table_name)
        table_info = (
            connection.execute(f"PRAGMA table_info('{name}')").fetchall()
            if str(table_type) == "BASE TABLE" and name != "schema_contract"
            else []
        )
        physical_not_null = sorted(str(row[1]) for row in table_info if bool(row[3]))
        schema_rows.append(
            {
                "table_name": name,
                "table_type": str(table_type),
                "data_layer": _database_layer(name),
                "consumer_safe": bool(
                    not name.endswith("_raw")
                    and name not in {"sec_companyfacts", "yahoo_current_snapshots"}
                ),
                "unique_key": ",".join(DATABASE_UNIQUE_KEYS.get(name, ())),
                "required_non_null": ",".join(DATABASE_REQUIRED_NON_NULL.get(name, ())),
                "physical_not_null": ",".join(physical_not_null),
            }
        )
    schema_contract = pd.DataFrame(schema_rows)
    schema_contract.to_csv(output / "schema_contract.csv", index=False)
    connection.execute(
        "CREATE OR REPLACE TABLE schema_contract AS SELECT * FROM read_csv_auto(?)",
        [str(output / "schema_contract.csv")],
    )
    contract_violations = int(
        contract_checks.loc[~contract_checks["passed"], "issue_count"].sum()
    )
    return len(schema_contract), len(index_contract), contract_violations


def repair_failed_companyfacts_from_bulk(
    connection: Any,
    config: Mapping[str, Any],
    output: Path,
) -> dict[str, Any]:
    """Repair API/Jina failures from the official SEC bulk archive once."""

    audit_columns = ["cik", "status", "rows", "error"]

    def persist_audit(rows: list[dict[str, Any]]) -> pd.DataFrame:
        audit_frame = pd.DataFrame(rows, columns=audit_columns)
        audit_frame.to_csv(output / "sec_bulk_repair_audit.csv", index=False)
        connection.register("sec_bulk_repair_audit_frame", audit_frame)
        connection.execute(
            "CREATE OR REPLACE TABLE sec_bulk_repair_audit AS "
            "SELECT * FROM sec_bulk_repair_audit_frame"
        )
        connection.unregister("sec_bulk_repair_audit_frame")
        return audit_frame

    failed = connection.execute(
        "SELECT DISTINCT cik FROM sec_download_status "
        "WHERE surface = 'companyfacts' AND status <> 'ok' ORDER BY cik"
    ).df()
    if failed.empty or not bool(config["sec"].get("repair_failed_from_bulk", True)):
        persist_audit([])
        return {
            "requested": int(len(failed)),
            "repaired": 0,
            "still_missing": int(len(failed)),
            "bulk_sha256": "",
        }
    bulk_path = output / ".companyfacts_repair.zip"
    try:
        _download(
            str(config["sec"]["companyfacts_bulk_url"]),
            bulk_path,
            headers=_sec_headers(str(config["sec"]["default_user_agent"])),
            retries=4,
        )
    except Exception as exc:
        persist_audit(
            [
                {
                    "cik": int(cik),
                    "status": "bulk_download_failed",
                    "rows": 0,
                    "error": f"{type(exc).__name__}:{exc}",
                }
                for cik in failed["cik"].astype(int)
            ]
        )
        bulk_path.unlink(missing_ok=True)
        return {
            "requested": int(len(failed)),
            "repaired": 0,
            "still_missing": int(len(failed)),
            "bulk_sha256": "",
        }
    bulk_hash = sha256_file(bulk_path)
    repair_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(bulk_path) as archive:
        member_map = {Path(name).name: name for name in archive.namelist()}
        for cik_value in failed["cik"].astype(int):
            member = member_map.get(f"CIK{cik_value:010d}.json")
            if not member:
                audit_rows.append(
                    {
                        "cik": cik_value,
                        "status": "not_present_in_official_bulk",
                        "rows": 0,
                        "error": "",
                    }
                )
                continue
            payload = json.loads(archive.read(member))
            submissions = connection.execute(
                "SELECT accession_number, accepted_at FROM sec_submissions WHERE cik = ?",
                [cik_value],
            ).df()
            accepted = {
                str(row.accession_number): row.accepted_at
                for row in submissions.itertuples()
                if str(row.accession_number or "") and pd.notna(row.accepted_at)
            }
            rows = _companyfacts_rows(
                payload,
                cik_value,
                source_url=str(config["sec"]["companyfacts_bulk_url"]),
                source_mode="sec_official_bulk_repair",
                accepted_at_by_accession=accepted,
            )
            repair_rows.extend(rows)
            audit_rows.append(
                {
                    "cik": cik_value,
                    "status": "repaired" if rows else "bulk_file_without_required_facts",
                    "rows": len(rows),
                    "error": "",
                }
            )
    if repair_rows:
        repair_frame = pd.DataFrame(repair_rows)
        connection.register("sec_bulk_repair_rows", repair_frame)
        connection.execute(
            "INSERT INTO sec_companyfacts BY NAME SELECT * FROM sec_bulk_repair_rows"
        )
        connection.unregister("sec_bulk_repair_rows")
        connection.execute(
            "CREATE OR REPLACE TABLE sec_companyfacts AS SELECT DISTINCT * FROM sec_companyfacts"
        )
    audit = persist_audit(audit_rows)
    repaired_ciks = audit.loc[audit["status"].eq("repaired"), "cik"].astype(int).tolist()
    if repaired_ciks:
        connection.execute(
            "UPDATE sec_download_status SET status = 'repaired_bulk', "
            "source_mode = 'sec_official_bulk_repair', error = '' "
            "WHERE surface = 'companyfacts' AND cik IN (SELECT * FROM unnest(?))",
            [repaired_ciks],
        )
    bulk_path.unlink(missing_ok=True)
    repaired = len(repaired_ciks)
    return {
        "requested": int(len(failed)),
        "repaired": repaired,
        "still_missing": int(len(failed) - repaired),
        "bulk_sha256": bulk_hash,
    }


def _sec_issuer_flags(submissions: pd.DataFrame) -> pd.DataFrame:
    """Summarise SEC filing evidence used to exclude foreign/fund issuers."""

    columns = ["cik", "sec_foreign_filer", "sec_investment_company", "sec_forms_seen"]
    if submissions.empty:
        return pd.DataFrame(columns=columns)
    frame = submissions.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce").astype("Int64")
    frame["form"] = frame.get("form", "").astype("string").fillna("").str.upper()
    rows = []
    for cik, group in frame.dropna(subset=["cik"]).groupby("cik"):
        forms = sorted(set(group["form"].dropna().astype(str)) - {""})
        rows.append(
            {
                "cik": int(cik),
                "sec_foreign_filer": bool(set(forms) & FOREIGN_SEC_FORMS),
                "sec_investment_company": bool(set(forms) & INVESTMENT_COMPANY_FORMS),
                "sec_forms_seen": "|".join(forms),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _sec_surface_availability(status: pd.DataFrame) -> pd.DataFrame:
    """Return one fail-closed SEC availability row per issuer."""

    columns = ["cik", "sec_companyfacts_available", "sec_submissions_available"]
    if status.empty:
        return pd.DataFrame(columns=columns)
    frame = status.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce").astype("Int64")
    frame["surface"] = frame["surface"].astype("string").fillna("").str.lower()
    frame["available"] = frame["status"].isin(["ok", "repaired_bulk"])
    frame = frame.dropna(subset=["cik"])
    rows: list[dict[str, Any]] = []
    for cik, group in frame.groupby("cik"):
        by_surface = group.groupby("surface")["available"].any().to_dict()
        rows.append(
            {
                "cik": int(cik),
                "sec_companyfacts_available": bool(
                    by_surface.get("companyfacts", False)
                ),
                "sec_submissions_available": bool(by_surface.get("submissions", False)),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _classify_security_eligibility(
    frame: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    maximum_price_age_days: int = 14,
) -> pd.DataFrame:
    """Classify a strict US common-stock universe with an auditable reason."""

    out = frame.copy()
    quote_type = out.get(
        "quoteType", pd.Series(index=out.index, dtype="string")
    ).astype("string").fillna("").str.upper().str.strip()
    country = out.get(
        "country_yahoo", pd.Series(index=out.index, dtype="string")
    ).astype("string").fillna("").str.strip()
    yahoo_name = out.get(
        "longName", pd.Series(index=out.index, dtype="string")
    ).astype("string")
    sec_name = out.get(
        "company_name_sec", pd.Series(index=out.index, dtype="string")
    ).astype("string")
    name = yahoo_name.fillna(sec_name).fillna("")
    symbol = out["symbol"].astype("string").fillna("").str.upper()
    price_rows = pd.to_numeric(
        out.get("price_rows", pd.Series(index=out.index, dtype="float64")),
        errors="coerce",
    ).fillna(0)
    last_price = pd.to_datetime(
        out.get("last_price_date", pd.Series(index=out.index, dtype="datetime64[ns]")),
        errors="coerce",
    )
    cutoff = pd.Timestamp(as_of).tz_localize(None).normalize() - pd.Timedelta(
        days=int(maximum_price_age_days)
    )
    excluded_name = name.str.contains(EXCLUDE_SECURITY_RE, regex=True, na=False)
    excluded_symbol = (
        symbol.str.contains(PREFERRED_SYMBOL_RE, regex=True, na=False)
        | symbol.str.contains(UNIT_SYMBOL_RE, regex=True, na=False)
        | symbol.str.contains(WARRANT_SYMBOL_RE, regex=True, na=False)
    )
    foreign_filer = out.get(
        "sec_foreign_filer", pd.Series(False, index=out.index)
    ).fillna(False).astype(bool)
    investment_company = out.get(
        "sec_investment_company", pd.Series(False, index=out.index)
    ).fillna(False).astype(bool)
    reasons = np.select(
        [
            excluded_name | excluded_symbol,
            foreign_filer,
            investment_company,
            quote_type.ne("EQUITY"),
            country.eq(""),
            country.ne("United States"),
            price_rows.le(0),
            last_price.isna(),
            last_price.lt(cutoff),
        ],
        [
            "excluded_name_or_instrument",
            "excluded_foreign_sec_filer",
            "excluded_investment_company",
            "yahoo_quote_type_not_equity",
            "yahoo_country_unavailable",
            "yahoo_country_not_united_states",
            "price_history_unavailable",
            "latest_price_date_unavailable",
            "latest_price_is_stale",
        ],
        default="eligible_us_common_stock",
    )
    out["eligibility_reason"] = reasons
    out["eligible_common_stock"] = out["eligibility_reason"].eq(
        "eligible_us_common_stock"
    )
    out["issuer_share_class_count"] = 1
    out["issuer_primary_security"] = True
    if "cik" in out:
        candidates = out.loc[out["eligible_common_stock"]].copy()
        candidates["_cap"] = pd.to_numeric(
            candidates.get("marketCap", pd.Series(np.nan, index=candidates.index)),
            errors="coerce",
        ).fillna(-1)
        candidates["_plain_symbol"] = ~candidates["symbol"].astype(str).str.contains(
            "-", regex=False
        )
        class_counts = candidates.groupby("cik")["symbol"].transform("nunique")
        out.loc[candidates.index, "issuer_share_class_count"] = class_counts.astype(int)
        primary = (
            candidates.sort_values(
                ["cik", "_plain_symbol", "_cap", "symbol"],
                ascending=[True, False, False, True],
            )
            .drop_duplicates("cik", keep="first")
            .index
        )
        out.loc[candidates.index, "issuer_primary_security"] = False
        out.loc[primary, "issuer_primary_security"] = True
    return out


def merge(config: dict[str, Any], args: argparse.Namespace) -> None:
    import duckdb

    input_root = Path(args.input_root)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    prepare_dir = Path(args.prepare_dir)
    sec_dir = Path(args.sec_dir)
    metadata = pd.read_parquet(prepare_dir / "selected_185_predictors.parquet")
    groups = pd.read_csv(prepare_dir / "redundancy_groups.csv")
    redundancy_audit_path = prepare_dir / "redundancy_correlation_audit.csv"
    if redundancy_audit_path.exists():
        redundancy_audit = pd.read_csv(redundancy_audit_path)
        redundancy_audit_source_status = "source_artifact"
    else:
        redundancy_audit = groups[["signalname", "redundancy_group"]].copy()
        redundancy_audit["correlation"] = np.nan
        redundancy_audit["audit_status"] = "missing_from_legacy_source_artifact"
        redundancy_audit_source_status = "reconstructed_manifest_only"
    seed = pd.read_parquet(prepare_dir / "security_master_seed.parquet")
    source_manifest = pd.read_csv(prepare_dir / "source_manifest.csv")

    price_paths = sorted(input_root.rglob("prices_*.parquet"))
    metadata_paths = sorted(input_root.rglob("metadata_*.parquet"))
    option_paths = sorted(input_root.rglob("options_*.parquet"))
    analyst_paths = sorted(input_root.rglob("analyst_*.jsonl"))
    yahoo_status_paths = sorted(input_root.rglob("status_*.csv"))
    summary_paths = sorted(input_root.rglob("summary_*.json"))
    expected_chunks = int(config["execution"]["yfinance_chunks"])
    yahoo_surface_counts = {
        "prices": len(price_paths),
        "metadata": len(metadata_paths),
        "options": len(option_paths),
        "analyst": len(analyst_paths),
        "status": len(yahoo_status_paths),
        "summary": len(summary_paths),
    }
    incomplete_yahoo = {
        name: count for name, count in yahoo_surface_counts.items()
        if count != expected_chunks
    }
    if incomplete_yahoo:
        raise OpenAPDataError(
            f"Expected {expected_chunks} YFinance chunks per surface, found {incomplete_yahoo}"
        )

    db_path = output / "openap_current.duckdb"
    connection = duckdb.connect(str(db_path))
    quoted_prices = ",".join(repr(str(path)) for path in price_paths)
    quoted_metadata = ",".join(repr(str(path)) for path in metadata_paths)
    connection.execute(f"CREATE OR REPLACE TABLE prices_daily_raw AS SELECT * FROM read_parquet([{quoted_prices}], union_by_name=true)")
    connection.execute("CREATE OR REPLACE VIEW prices_daily AS SELECT * FROM prices_daily_raw")
    connection.execute(f"CREATE OR REPLACE TABLE yahoo_current_snapshots AS SELECT * FROM read_parquet([{quoted_metadata}], union_by_name=true)")
    valid_options = [path for path in option_paths if path.stat().st_size > 0]
    if valid_options:
        quoted_options = ",".join(repr(str(path)) for path in valid_options)
        connection.execute(f"CREATE OR REPLACE TABLE yahoo_options_raw AS SELECT * FROM read_parquet([{quoted_options}], union_by_name=true)")
    else:
        connection.execute(
            "CREATE OR REPLACE TABLE yahoo_options_raw("
            "contractSymbol VARCHAR, lastTradeDate TIMESTAMPTZ, strike DOUBLE, "
            "lastPrice DOUBLE, bid DOUBLE, ask DOUBLE, change DOUBLE, percentChange DOUBLE, "
            "volume DOUBLE, openInterest DOUBLE, impliedVolatility DOUBLE, inTheMoney BOOLEAN, "
            "contractSize VARCHAR, currency VARCHAR, symbol VARCHAR, option_type VARCHAR, "
            "expiration VARCHAR, retrieved_at VARCHAR)"
        )
    connection.execute("CREATE OR REPLACE VIEW yahoo_options_current AS SELECT * FROM yahoo_options_raw")
    sec_fact_paths = sorted(sec_dir.rglob("sec_companyfacts_*.parquet"))
    sec_submission_paths = sorted(sec_dir.rglob("sec_submissions_*.parquet"))
    sec_status_paths = sorted(sec_dir.rglob("sec_status_*.csv"))
    sec_summary_paths = sorted(sec_dir.rglob("sec_summary_*.json"))
    sec_layout = "sharded_api"
    if len(sec_summary_paths) == 1:
        first_sec_summary = json.loads(
            sec_summary_paths[0].read_text(encoding="utf-8")
        )
        sec_layout = str(first_sec_summary.get("source_layout", sec_layout))
    expected_sec_chunks = (
        1
        if sec_layout == "official_bulk_archive"
        else int(config["execution"].get("sec_chunks", expected_chunks))
    )
    sec_surface_counts = {
        "companyfacts": len(sec_fact_paths),
        "submissions": len(sec_submission_paths),
        "status": len(sec_status_paths),
        "summary": len(sec_summary_paths),
    }
    incomplete_sec = {
        name: count for name, count in sec_surface_counts.items()
        if count != expected_sec_chunks
    }
    if incomplete_sec:
        raise OpenAPDataError(
            f"Expected {expected_sec_chunks} SEC chunks per surface, found {incomplete_sec}"
        )
    quoted_sec_facts = ",".join(repr(str(path)) for path in sec_fact_paths)
    quoted_sec_submissions = ",".join(repr(str(path)) for path in sec_submission_paths)
    connection.execute(
        f"CREATE OR REPLACE TABLE sec_companyfacts AS "
        f"SELECT DISTINCT * FROM read_parquet([{quoted_sec_facts}], union_by_name=true)"
    )
    connection.execute(
        f"CREATE OR REPLACE TABLE sec_submissions AS "
        f"SELECT DISTINCT * FROM read_parquet([{quoted_sec_submissions}], union_by_name=true)"
    )
    quoted_yahoo_status = ",".join(repr(str(path)) for path in yahoo_status_paths)
    quoted_sec_status = ",".join(repr(str(path)) for path in sec_status_paths)
    connection.execute(
        f"CREATE OR REPLACE TABLE yfinance_download_status AS "
        f"SELECT * FROM read_csv_auto([{quoted_yahoo_status}], union_by_name=true, filename=true)"
    )
    connection.execute(
        f"CREATE OR REPLACE TABLE sec_download_status AS "
        f"SELECT * FROM read_csv_auto([{quoted_sec_status}], union_by_name=true, filename=true)"
    )
    sec_bulk_repair = repair_failed_companyfacts_from_bulk(
        connection, config, output
    )
    connection.execute("ALTER TABLE sec_companyfacts ADD COLUMN fact_identity VARCHAR")
    connection.execute(
        "UPDATE sec_companyfacts SET fact_identity = md5(concat_ws('|', "
        "CAST(cik AS VARCHAR), taxonomy, tag, unit, COALESCE(period_start, ''), "
        "period_end, accession_number))"
    )

    yahoo_meta = connection.execute("SELECT * FROM yahoo_current_snapshots").df()
    if not yahoo_meta.empty:
        yahoo_meta = yahoo_meta.sort_values("retrieved_at").drop_duplicates("symbol", keep="last")
    price_coverage = connection.execute(
        "SELECT symbol, COUNT(*) AS price_rows, MIN(date) AS first_price_date, "
        "MAX(date) AS last_price_date FROM prices_daily GROUP BY symbol"
    ).df()
    security_master = seed.merge(yahoo_meta, on="symbol", how="left", suffixes=("_sec", "_yahoo"))
    security_master = security_master.merge(price_coverage, on="symbol", how="left")
    sec_issuer_flags = _sec_issuer_flags(connection.execute("SELECT * FROM sec_submissions").df())
    security_master = security_master.merge(sec_issuer_flags, on="cik", how="left")
    sec_availability = _sec_surface_availability(
        connection.execute("SELECT cik, surface, status FROM sec_download_status").df()
    )
    security_master = security_master.merge(sec_availability, on="cik", how="left")
    for column in ("sec_companyfacts_available", "sec_submissions_available"):
        security_master[column] = security_master[column].fillna(False).astype(bool)
    as_of = pd.Timestamp.now(tz="UTC").tz_localize(None)
    security_master = _classify_security_eligibility(
        security_master,
        as_of=as_of,
        maximum_price_age_days=int(config["universe"]["maximum_price_age_days"]),
    )
    analysts = _read_jsonl_files(analyst_paths)
    if analysts.empty:
        analysts = pd.DataFrame(columns=["symbol", "dataset", "retrieved_at", "payload_json"])
    analysts.to_parquet(
        output / "yahoo_analyst_current.parquet",
        index=False,
        compression="zstd",
    )
    values_by_symbol: dict[str, dict[str, FeatureValue]] = {}
    quality_rows: list[dict[str, Any]] = []
    sec_concept_input_frames: list[pd.DataFrame] = []
    for row in security_master.loc[security_master["eligible_common_stock"]].itertuples():
        symbol = str(row.symbol)
        prices = connection.execute(
            "SELECT * FROM prices_daily WHERE symbol = ? ORDER BY date", [symbol]
        ).df()
        clean_prices, price_quality = clean_price_history(prices)
        current_price = (
            float(clean_prices["adj_close"].iloc[-1]) if not clean_prices.empty else np.nan
        )
        recent = clean_prices.tail(21)
        average_volume = pd.to_numeric(recent.get("volume"), errors="coerce").mean()
        average_dollar_volume = (
            pd.to_numeric(recent.get("volume"), errors="coerce")
            * pd.to_numeric(recent.get("adj_close"), errors="coerce")
        ).mean()
        quality_rows.append(
            {
                "symbol": symbol,
                **price_quality,
                "current_price": current_price,
                "average_volume_21d": average_volume,
                "average_dollar_volume_21d": average_dollar_volume,
            }
        )
    price_quality_frame = pd.DataFrame(quality_rows)
    security_master = security_master.merge(price_quality_frame, on="symbol", how="left")
    last_clean_price_dates = pd.to_datetime(
        security_master.get("last_clean_price_date"), errors="coerce"
    ).dt.normalize()
    as_of_date = pd.Timestamp(as_of).tz_localize(None).normalize()
    security_master["clean_price_staleness_days"] = (
        as_of_date - last_clean_price_dates
    ).dt.days
    market_cap = pd.to_numeric(security_master.get("marketCap"), errors="coerce")
    rank_conditions = [
        market_cap.lt(float(config["universe"]["minimum_market_cap_usd"])) | market_cap.isna(),
        pd.to_numeric(security_master.get("current_price"), errors="coerce").lt(float(config["universe"]["minimum_price_usd"])),
        pd.to_numeric(security_master.get("average_volume_21d"), errors="coerce").lt(float(config["universe"]["minimum_average_volume_21d"])) | pd.to_numeric(security_master.get("average_volume_21d"), errors="coerce").isna(),
        pd.to_numeric(security_master.get("average_dollar_volume_21d"), errors="coerce").lt(float(config["universe"]["minimum_average_dollar_volume_21d"])) | pd.to_numeric(security_master.get("average_dollar_volume_21d"), errors="coerce").isna(),
        pd.to_numeric(security_master.get("clean_price_rows"), errors="coerce").lt(float(config["universe"]["minimum_clean_price_rows"])),
        pd.to_numeric(security_master.get("clean_price_staleness_days"), errors="coerce").gt(
            int(config["universe"]["maximum_price_age_days"])
        ) | pd.to_numeric(security_master.get("clean_price_staleness_days"), errors="coerce").isna(),
        ~security_master.get("price_quality_pass", pd.Series(False, index=security_master.index)).fillna(False).astype(bool),
        ~security_master["sec_submissions_available"],
        ~security_master["sec_companyfacts_available"],
    ]
    security_master["ranking_rejection_reason"] = np.select(
        rank_conditions,
        [
            "market_cap_below_minimum_or_missing",
            "price_below_minimum",
            "average_volume_below_minimum",
            "average_dollar_volume_below_minimum",
            "insufficient_clean_price_history",
            "stale_or_missing_latest_price",
            "price_quality_failed",
            "sec_submissions_unavailable",
            "sec_companyfacts_unavailable",
        ],
        default="",
    )
    security_master["ranking_eligible"] = (
        security_master["eligible_common_stock"]
        & security_master["ranking_rejection_reason"].eq("")
    )
    security_master.to_parquet(output / "security_master.parquet", index=False, compression="zstd")
    security_master.loc[~security_master["ranking_eligible"]].to_csv(
        output / "security_universe_exclusions.csv",
        index=False,
    )
    eligible = security_master.loc[security_master["ranking_eligible"]].copy()
    quality_rows = []
    for row in eligible.itertuples():
        symbol = str(row.symbol)
        cik = int(row.cik)
        prices = connection.execute("SELECT * FROM prices_daily WHERE symbol = ? ORDER BY date", [symbol]).df()
        prices, price_quality = clean_price_history(prices)
        values = calculate_price_features(prices)
        market_cap = getattr(row, "marketCap", None)
        market_cap_source = "yfinance_current_market_cap"
        if not _is_number(market_cap):
            market_cap = None
        facts = connection.execute("SELECT * FROM sec_companyfacts WHERE cik = ?", [cik]).df()
        concept_inputs = latest_sec_concept_inputs(facts, as_of)
        accounting_inputs = concept_inputs.loc[
            concept_inputs["concept_lag"].eq(0)
            & ~concept_inputs["concept"].isin(["shares", "employees"])
        ] if not concept_inputs.empty else concept_inputs
        if not concept_inputs.empty:
            concept_inputs.insert(0, "cik", cik)
            concept_inputs.insert(0, "symbol", symbol)
            sec_concept_input_frames.append(concept_inputs)
        concepts = sec_concepts_from_inputs(concept_inputs)
        sec_shares = concepts.get("shares", [None])[0] if concepts.get("shares") else None
        resolved_shares = _resolve_current_shares_outstanding(
            sec_shares,
            getattr(row, "sharesOutstanding", None),
        )
        if market_cap is None and not prices.empty:
            if _is_number(resolved_shares.raw_value):
                market_cap = float(prices["adj_close"].iloc[-1]) * float(resolved_shares.raw_value)
                market_cap_source = resolved_shares.source
        accounting_values = calculate_accounting_features(
            concepts, market_cap=market_cap
        )
        accounting_values = apply_accounting_input_freshness(
            accounting_values,
            concept_inputs,
            as_of=as_of,
            maximum_age_days=int(
                config["score"]["maximum_accounting_input_age_days_for_ranking"]
            ),
        )
        values.update(accounting_values)
        if market_cap is not None:
            values["Size"] = FeatureValue(
                "Size",
                float(market_cap),
                "proxy",
                market_cap_source,
                "current_market_cap",
                "Current snapshot; not the official lagged portfolio-formation market cap",
            )
        values.update(_share_turnover_features(prices, resolved_shares))
        symbol_options = connection.execute("SELECT * FROM yahoo_options_current WHERE symbol = ?", [symbol]).df()
        stock_volume = float(prices["volume"].tail(21).mean()) if not prices.empty else None
        realized = values.get("RealizedVol").raw_value if values.get("RealizedVol") else None
        stock_price = float(prices["adj_close"].iloc[-1]) if not prices.empty else None
        option_audit: dict[str, Any] = {}
        values.update(
            _options_features(
                symbol_options,
                stock_volume,
                realized,
                stock_price=stock_price,
                as_of=as_of,
                config=config,
                audit=option_audit,
            )
        )
        symbol_analysts = analysts.loc[analysts["symbol"].eq(symbol)] if not analysts.empty else pd.DataFrame()
        values.update(_analyst_features(symbol_analysts))
        values_by_symbol[symbol] = values
        quality_rows.append(
            {
                "symbol": symbol,
                "cik": cik,
                **price_quality,
                "price_rows": len(prices),
                "first_price_date": prices["date"].min() if not prices.empty else None,
                "last_price_date": prices["date"].max() if not prices.empty else None,
                "last_sec_available_at": facts["available_at"].max() if not facts.empty else None,
                "last_sec_input_available_at": (
                    concept_inputs["available_at"].max()
                    if not concept_inputs.empty
                    else None
                ),
                "last_accounting_input_available_at": (
                    accounting_inputs["available_at"].max()
                    if not accounting_inputs.empty
                    else None
                ),
                "resolved_shares": resolved_shares.raw_value,
                "resolved_shares_status": resolved_shares.status,
                "resolved_shares_source": resolved_shares.source,
                "resolved_shares_note": resolved_shares.note,
                "sec_fact_rows": len(facts),
                "computed_features": sum(item.raw_value is not None for item in values.values()),
                "exact_features": sum(item.status == "exact" and item.raw_value is not None for item in values.values()),
                "proxy_features": sum(item.status == "proxy" and item.raw_value is not None for item in values.values()),
                **option_audit,
            }
        )

    industry_by_symbol = eligible.set_index("symbol").get("industry", pd.Series(dtype=object)).astype(str)
    industry_momentum: dict[str, list[float]] = {}
    for symbol, values in values_by_symbol.items():
        momentum = values.get("Mom6m")
        industry = industry_by_symbol.get(symbol, "")
        if industry and industry not in {"nan", "None"} and momentum and _is_number(momentum.raw_value):
            industry_momentum.setdefault(industry, []).append(float(momentum.raw_value))
    industry_means = {name: float(np.mean(values)) for name, values in industry_momentum.items() if values}
    for symbol, values in values_by_symbol.items():
        industry = industry_by_symbol.get(symbol, "")
        values["IndMom"] = FeatureValue(
            "IndMom",
            industry_means.get(industry),
            "proxy",
            "yfinance_current_industry",
            "current_industry_mean_mom6m",
            "Current Yahoo industry replaces historical SIC membership",
        )
        realized = values.get("RealizedVol")
        values["IdioVolAHT"] = FeatureValue(
            "IdioVolAHT",
            float(realized.raw_value) if realized and _is_number(realized.raw_value) else None,
            "proxy",
            "yfinance_price_history",
            "realized_volatility_proxy_for_idiosyncratic_volatility",
            "Factor-residual volatility is unavailable; total realized volatility is disclosed as a proxy",
        )

    feature_frame = assemble_feature_table(
        metadata,
        values_by_symbol,
        as_of=as_of.date().isoformat(),
        redundancy_groups=groups,
        security_context=eligible,
        exact_source_multiplier=float(config["score"]["exact_source_multiplier"]),
        proxy_source_multiplier=float(config["score"]["proxy_source_multiplier"]),
        minimum_nonmodal_fraction=float(
            config["score"]["minimum_cross_sectional_nonmodal_fraction"]
        ),
    )
    feature_frame, current_redundancy_audit = refine_current_redundancy_groups(
        feature_frame,
        threshold=float(config["openap"].get("current_redundancy_threshold", 0.995)),
        minimum_overlap=int(config["openap"].get("current_redundancy_minimum_overlap", 100)),
    )
    scores = calculate_scores(
        feature_frame,
        minimum_metrics=int(config["score"]["minimum_metrics_per_score"]),
        maximum_metric_weight_multiple=float(config["score"]["maximum_metric_weight_multiple"]),
        maximum_family_weight=float(config["score"]["maximum_family_weight"]),
    )
    horizon_score_contributions = scores.attrs.get(
        "score_contributions", pd.DataFrame()
    )
    overall_features = feature_frame.copy()
    overall_features["horizon_months"] = 0
    overall_features, overall_redundancy_audit = refine_current_redundancy_groups(
        overall_features,
        threshold=float(config["openap"].get("current_redundancy_threshold", 0.995)),
        minimum_overlap=int(config["openap"].get("current_redundancy_minimum_overlap", 100)),
    )
    overall_scores = calculate_scores(
        overall_features,
        minimum_metrics=int(config["score"]["minimum_metrics_per_score"]),
        maximum_metric_weight_multiple=float(config["score"]["maximum_metric_weight_multiple"]),
        maximum_family_weight=float(config["score"]["maximum_family_weight"]),
    )
    overall_score_contributions = overall_scores.attrs.get(
        "score_contributions", pd.DataFrame()
    )
    overall_scores = overall_scores.loc[overall_scores["horizon_months"].eq(0)].copy()
    score_contributions = pd.concat(
        [horizon_score_contributions, overall_score_contributions],
        ignore_index=True,
    )
    aggregate_scores = calculate_aggregate_scores(
        overall_scores,
        minimum_horizons=int(config["score"]["minimum_horizons_for_ranking"]),
        required_horizons=config["score"]["required_ranking_horizons"],
        minimum_confidence=float(config["score"]["minimum_aggregate_confidence"]),
    )
    coverage = coverage_report(feature_frame, metadata)
    quality = pd.DataFrame(quality_rows)
    for column, default in (
        ("option_contracts_raw", 0),
        ("option_contracts_usable", 0),
        ("option_calls_usable", 0),
        ("option_puts_usable", 0),
        ("option_depth_pass", False),
        ("option_rejection_reason", "no_usable_option_snapshot"),
    ):
        if column not in quality:
            quality[column] = default
        else:
            quality[column] = quality[column].fillna(default)
    score_context = quality[
        [
            "symbol",
            "last_price_date",
            "last_sec_available_at",
            "last_sec_input_available_at",
            "last_accounting_input_available_at",
            "price_rows",
            "computed_features",
            "exact_features",
            "proxy_features",
        ]
    ].copy()
    score_context["missing_features"] = EXPECTED_PREDICTORS - score_context["computed_features"]
    score_context["sec_input_age_days"] = (
        pd.Timestamp(as_of).tz_localize(None).normalize()
        - pd.to_datetime(score_context["last_sec_input_available_at"], errors="coerce", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
    ).dt.days
    score_context["accounting_input_age_days"] = (
        pd.Timestamp(as_of).tz_localize(None).normalize()
        - pd.to_datetime(
            score_context["last_accounting_input_available_at"],
            errors="coerce",
            utc=True,
        )
        .dt.tz_localize(None)
        .dt.normalize()
    ).dt.days
    scores = scores.merge(score_context, on="symbol", how="left")
    overall_scores = overall_scores.merge(score_context, on="symbol", how="left")
    aggregate_scores = aggregate_scores.merge(score_context, on="symbol", how="left")
    aggregate_scores = aggregate_scores.merge(
        security_master[[
            "symbol",
            "marketCap",
            "current_price",
            "average_volume_21d",
            "average_dollar_volume_21d",
            "clean_price_staleness_days",
            "ranking_eligible",
        ]],
        on="symbol",
        how="left",
        suffixes=("", "_universe"),
    )
    aggregate_scores["ranking_eligible"] = (
        aggregate_scores["ranking_eligible"].fillna(False)
        & aggregate_scores["ranking_eligible_universe"].fillna(False)
    )
    aggregate_scores = aggregate_scores.drop(columns=["ranking_eligible_universe"])
    minimum_features = int(config["score"]["minimum_computed_features_for_ranking"])
    maximum_missing = int(config["score"]["maximum_missing_features_for_ranking"])
    maximum_sec_age = int(config["score"]["maximum_sec_age_days_for_ranking"])
    maximum_accounting_age = int(
        config["score"]["maximum_accounting_input_age_days_for_ranking"]
    )
    semantic_rejections = [
        pd.to_numeric(aggregate_scores["computed_features"], errors="coerce").lt(minimum_features),
        pd.to_numeric(aggregate_scores["missing_features"], errors="coerce").gt(maximum_missing),
        pd.to_numeric(aggregate_scores["sec_input_age_days"], errors="coerce").gt(maximum_sec_age)
        | pd.to_numeric(aggregate_scores["sec_input_age_days"], errors="coerce").isna(),
        pd.to_numeric(
            aggregate_scores["accounting_input_age_days"], errors="coerce"
        ).gt(maximum_accounting_age)
        | pd.to_numeric(
            aggregate_scores["accounting_input_age_days"], errors="coerce"
        ).isna(),
    ]
    semantic_reasons = [
        "insufficient_computed_features",
        "too_many_missing_features",
        "stale_or_missing_sec_inputs",
        "stale_or_missing_accounting_inputs",
    ]
    prior_reason = aggregate_scores["ranking_rejection_reason"].fillna("").astype(str)
    semantic_reason = pd.Series(
        np.select(semantic_rejections, semantic_reasons, default=""),
        index=aggregate_scores.index,
    )
    aggregate_scores["ranking_rejection_reason"] = prior_reason.where(
        prior_reason.ne(""), semantic_reason
    )
    aggregate_scores["ranking_eligible"] &= semantic_reason.eq("")
    aggregate_scores["research_universe_score"] = aggregate_scores["aggregate_score"]
    aggregate_scores["aggregate_score"] = np.nan
    qualified_index = aggregate_scores.index[aggregate_scores["ranking_eligible"]]
    qualified_raw = pd.to_numeric(
        aggregate_scores.loc[qualified_index, "aggregate_raw_score"], errors="coerce"
    )
    qualified_count = int(qualified_raw.notna().sum())
    if qualified_count == 1:
        aggregate_scores.loc[qualified_index, "aggregate_score"] = 50.0
    elif qualified_count > 1:
        aggregate_scores.loc[qualified_index, "aggregate_score"] = (
            100.0
            * (qualified_raw.rank(method="average", na_option="keep") - 1.0)
            / (qualified_count - 1)
        )
    aggregate_scores["score_is_probability"] = False
    aggregate_scores["score_scale"] = "cross_sectional_percentile_0_100"

    deployment = config["deployment"]
    deployment_conditions = [
        pd.to_numeric(aggregate_scores["marketCap"], errors="coerce").lt(
            float(deployment["minimum_market_cap_usd"])
        ),
        pd.to_numeric(
            aggregate_scores["average_dollar_volume_21d"], errors="coerce"
        ).lt(float(deployment["minimum_average_dollar_volume_21d"])),
        pd.to_numeric(aggregate_scores["price_rows"], errors="coerce").lt(
            int(deployment["minimum_clean_price_rows"])
        ),
    ]
    aggregate_scores["deployment_rejection_reason"] = np.select(
        deployment_conditions,
        [
            "deployment_market_cap_below_minimum",
            "deployment_liquidity_below_minimum",
            "deployment_price_history_too_short",
        ],
        default="",
    )
    aggregate_scores["deployment_eligible"] = (
        aggregate_scores["ranking_eligible"]
        & aggregate_scores["deployment_rejection_reason"].eq("")
    )
    leaderboard = aggregate_scores.loc[aggregate_scores["ranking_eligible"]].sort_values(
        ["aggregate_score", "aggregate_confidence"], ascending=[False, False]
    )
    deployable_leaderboard = leaderboard.loc[
        leaderboard["deployment_eligible"]
    ].copy()
    sec_concept_inputs = (
        pd.concat(sec_concept_input_frames, ignore_index=True)
        if sec_concept_input_frames
        else latest_sec_concept_inputs(pd.DataFrame(), as_of).assign(
            symbol=pd.Series(dtype="string"),
            cik=pd.Series(dtype="Int64"),
        )
    )
    feature_frame.to_parquet(output / "openap_features_current.parquet", index=False, compression="zstd")
    scores.to_parquet(output / "openap_scores_current.parquet", index=False, compression="zstd")
    overall_scores.to_parquet(
        output / "openap_overall_scores_current.parquet",
        index=False,
        compression="zstd",
    )
    aggregate_scores.to_parquet(
        output / "openap_scores_aggregate_current.parquet",
        index=False,
        compression="zstd",
    )
    score_contributions.to_parquet(
        output / "openap_score_contributions_current.parquet",
        index=False,
        compression="zstd",
    )
    leaderboard.to_csv(output / "openap_current_leaderboard.csv", index=False)
    deployable_leaderboard.to_csv(
        output / "openap_current_deployable_leaderboard.csv", index=False
    )
    sec_concept_inputs.to_parquet(
        output / "sec_concept_inputs_current.parquet",
        index=False,
        compression="zstd",
    )
    coverage.to_csv(output / "coverage_185.csv", index=False)
    quality.to_csv(output / "data_quality.csv", index=False)
    price_quality_frame.to_csv(output / "price_quality_current.csv", index=False)
    coverage.loc[coverage["coverage_status"].isin(["proxy", "mixed"])].to_csv(output / "proxy_audit.csv", index=False)
    coverage.loc[coverage["coverage_status"].eq("mixed")].to_csv(output / "mixed_fidelity_audit.csv", index=False)
    coverage.loc[coverage["coverage_status"].eq("unavailable")].to_csv(output / "unavailable_predictors.csv", index=False)
    metadata.to_csv(output / "selected_185_predictors.csv", index=False)
    groups.to_csv(output / "redundancy_groups.csv", index=False)
    redundancy_audit.to_csv(output / "redundancy_correlation_audit.csv", index=False)
    current_redundancy_audit.to_csv(
        output / "current_redundancy_groups.csv", index=False
    )
    overall_redundancy_audit.to_csv(
        output / "overall_redundancy_groups.csv", index=False
    )

    connection.execute("CREATE OR REPLACE TABLE security_master AS SELECT * FROM read_parquet(?)", [str(output / "security_master.parquet")])
    connection.execute("CREATE OR REPLACE TABLE openap_features_current AS SELECT * FROM read_parquet(?)", [str(output / "openap_features_current.parquet")])
    connection.execute("CREATE OR REPLACE TABLE openap_scores_current AS SELECT * FROM read_parquet(?)", [str(output / "openap_scores_current.parquet")])
    connection.execute(
        "CREATE OR REPLACE TABLE openap_overall_scores_current AS SELECT * FROM read_parquet(?)",
        [str(output / "openap_overall_scores_current.parquet")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE openap_scores_aggregate_current AS SELECT * FROM read_parquet(?)",
        [str(output / "openap_scores_aggregate_current.parquet")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE openap_score_contributions_current AS SELECT * FROM read_parquet(?)",
        [str(output / "openap_score_contributions_current.parquet")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE sec_concept_inputs_current AS SELECT * FROM read_parquet(?)",
        [str(output / "sec_concept_inputs_current.parquet")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE yahoo_analyst_current AS SELECT * FROM read_parquet(?)",
        [str(output / "yahoo_analyst_current.parquet")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE price_quality_current AS SELECT * FROM read_csv_auto(?)",
        [str(output / "price_quality_current.csv")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE data_quality_current AS SELECT * FROM read_csv_auto(?)",
        [str(output / "data_quality.csv")],
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE prices_daily_clean AS
        SELECT p.*
        FROM prices_daily_raw p
        INNER JOIN price_quality_current q USING (symbol)
        WHERE q.price_quality_pass
          AND p.adj_close > 0
          AND (p.open IS NULL OR p.open > 0)
          AND (p.high IS NULL OR p.high > 0)
          AND (p.low IS NULL OR p.low > 0)
          AND (p.close IS NULL OR p.close > 0)
          AND (
            p.open IS NULL OR p.high IS NULL OR p.low IS NULL OR p.close IS NULL
            OR (
              p.high >= greatest(p.open, p.close, p.low)
              AND p.low <= least(p.open, p.close, p.high)
            )
          )
          AND (q.history_reset_after IS NULL OR p.date > q.history_reset_after)
        """
    )
    connection.execute("CREATE OR REPLACE VIEW prices_daily AS SELECT * FROM prices_daily_clean")

    option_columns = {
        row[1] for row in connection.execute("PRAGMA table_info('yahoo_options_raw')").fetchall()
    }
    required_option_columns = {
        "symbol", "expiration", "lastTradeDate", "strike", "bid", "ask",
        "impliedVolatility",
    }
    if required_option_columns.issubset(option_columns):
        connection.execute(
            """
            CREATE OR REPLACE TABLE yahoo_options_quality AS
            SELECT o.*,
              CASE
                WHEN try_cast(o.expiration AS DATE) IS NULL THEN 'invalid_expiration'
                WHEN date_diff('day', CAST(? AS DATE), try_cast(o.expiration AS DATE)) NOT BETWEEN ? AND ? THEN 'dte_outside_policy'
                WHEN o.bid < 0 OR o.ask < o.bid THEN 'crossed_or_negative_quote'
                WHEN o.impliedVolatility NOT BETWEEN ? AND ? THEN 'invalid_implied_volatility'
                WHEN try_cast(o.lastTradeDate AS TIMESTAMPTZ) < CAST(? AS TIMESTAMPTZ) - (? * INTERVAL '1 day') THEN 'stale_trade'
                WHEN s.current_price IS NULL OR s.current_price <= 0 THEN 'missing_stock_price'
                WHEN o.strike / s.current_price NOT BETWEEN ? AND ? THEN 'moneyness_outside_policy'
                ELSE 'usable_candidate'
              END AS quality_status
            FROM yahoo_options_raw o
            LEFT JOIN security_master s USING (symbol)
            """,
            [
                as_of.date().isoformat(),
                int(config["yfinance"]["minimum_option_days"]),
                int(config["yfinance"]["maximum_option_days"]),
                float(config["yfinance"]["minimum_implied_volatility"]),
                float(config["yfinance"]["maximum_implied_volatility"]),
                as_of.isoformat(),
                int(config["yfinance"]["maximum_option_staleness_days"]),
                float(config["yfinance"]["minimum_option_moneyness"]),
                float(config["yfinance"]["maximum_option_moneyness"]),
            ],
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE yahoo_options_usable AS
            SELECT * EXCLUDE (quality_status)
            FROM yahoo_options_quality
            WHERE quality_status = 'usable_candidate'
            QUALIFY try_cast(expiration AS DATE) = min(try_cast(expiration AS DATE)) OVER (PARTITION BY symbol)
            """
        )
    else:
        connection.execute(
            "CREATE OR REPLACE TABLE yahoo_options_quality AS SELECT *, 'missing_required_columns' AS quality_status FROM yahoo_options_raw"
        )
        connection.execute(
            "CREATE OR REPLACE TABLE yahoo_options_usable AS SELECT * EXCLUDE (quality_status) FROM yahoo_options_quality WHERE false"
        )
    connection.execute("CREATE OR REPLACE VIEW yahoo_options_current AS SELECT * FROM yahoo_options_usable")
    option_quality_summary = connection.execute(
        "SELECT quality_status, COUNT(*) AS rows FROM yahoo_options_quality GROUP BY quality_status ORDER BY quality_status"
    ).df()
    option_quality_summary.to_csv(output / "options_quality_summary.csv", index=False)
    connection.execute(
        "CREATE OR REPLACE TABLE options_quality_summary AS SELECT * FROM read_csv_auto(?)",
        [str(output / "options_quality_summary.csv")],
    )
    connection.execute("SELECT * FROM yfinance_download_status").df().to_csv(
        output / "yfinance_download_status.csv", index=False
    )
    connection.execute("SELECT * FROM sec_download_status").df().to_csv(
        output / "sec_download_status.csv", index=False
    )
    connection.execute(
        "CREATE OR REPLACE TABLE openap_current_leaderboard AS SELECT * FROM read_csv_auto(?)",
        [str(output / "openap_current_leaderboard.csv")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE openap_current_deployable_leaderboard AS SELECT * FROM read_csv_auto(?)",
        [str(output / "openap_current_deployable_leaderboard.csv")],
    )
    for table_name, file_name in (
        ("selected_predictors", "selected_185_predictors.csv"),
        ("redundancy_groups", "redundancy_groups.csv"),
        ("redundancy_correlation_audit", "redundancy_correlation_audit.csv"),
        ("current_redundancy_groups", "current_redundancy_groups.csv"),
        ("overall_redundancy_groups", "overall_redundancy_groups.csv"),
        ("coverage_185", "coverage_185.csv"),
        ("data_quality_current", "data_quality.csv"),
        ("proxy_audit", "proxy_audit.csv"),
        ("mixed_fidelity_audit", "mixed_fidelity_audit.csv"),
        ("unavailable_predictors", "unavailable_predictors.csv"),
        ("security_universe_exclusions", "security_universe_exclusions.csv"),
    ):
        connection.execute(
            f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_csv_auto(?)",
            [str(output / file_name)],
        )
    duplicate_prices = int(
        connection.execute(
            "SELECT COALESCE(SUM(row_count - 1), 0) FROM "
            "(SELECT symbol, date, COUNT(*) AS row_count FROM prices_daily "
            "GROUP BY symbol, date HAVING COUNT(*) > 1)"
        ).fetchone()[0]
    )
    raw_price_rows_db = int(
        connection.execute("SELECT COUNT(*) FROM prices_daily_raw").fetchone()[0]
    )
    sec_companyfacts_rows_db = int(
        connection.execute("SELECT COUNT(*) FROM sec_companyfacts").fetchone()[0]
    )
    clean_price_rows_db = int(
        connection.execute("SELECT COUNT(*) FROM prices_daily_clean").fetchone()[0]
    )
    raw_nonpositive_price_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM prices_daily_raw WHERE adj_close <= 0"
        ).fetchone()[0]
    )
    options_raw_rows = int(
        connection.execute("SELECT COUNT(*) FROM yahoo_options_raw").fetchone()[0]
    )
    options_usable_rows = int(
        connection.execute("SELECT COUNT(*) FROM yahoo_options_usable").fetchone()[0]
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
    concept_inputs_without_available_at = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_concept_inputs_current WHERE available_at IS NULL"
        ).fetchone()[0]
    )
    future_concept_inputs = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_concept_inputs_current "
            "WHERE CAST(period_end AS DATE) > CAST(? AS DATE)",
            [as_of.date().isoformat()],
        ).fetchone()[0]
    )
    concept_inputs_before_period_end = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_concept_inputs_current "
            "WHERE CAST(available_at AS TIMESTAMP) < CAST(period_end AS TIMESTAMP)"
        ).fetchone()[0]
    )
    concept_inputs_before_filed = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_concept_inputs_current "
            "WHERE filed IS NOT NULL AND CAST(available_at AS TIMESTAMP) < CAST(filed AS TIMESTAMP)"
        ).fetchone()[0]
    )
    invalid_concept_units = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_concept_inputs_current WHERE "
            "(concept = 'shares' AND lower(unit) <> 'shares') OR "
            "(concept = 'employees' AND lower(unit) NOT IN ('employee','employees','person','persons')) OR "
            "(concept NOT IN ('shares','employees') AND upper(unit) <> 'USD')"
        ).fetchone()[0]
    )
    duplicate_companyfacts = int(
        connection.execute(
            "SELECT COALESCE(SUM(n - 1), 0) FROM ("
            "SELECT cik, taxonomy, tag, unit, period_start, period_end, accession_number, COUNT(*) n "
            "FROM sec_companyfacts GROUP BY ALL HAVING COUNT(*) > 1)"
        ).fetchone()[0]
    )
    duplicate_submissions = int(
        connection.execute(
            "SELECT COALESCE(SUM(n - 1), 0) FROM ("
            "SELECT cik, accession_number, form, filing_date, COUNT(*) n "
            "FROM sec_submissions GROUP BY ALL HAVING COUNT(*) > 1)"
        ).fetchone()[0]
    )
    blank_required_identifiers = int(
        connection.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM security_master WHERE trim(symbol) = '') + "
            "(SELECT COUNT(*) FROM sec_companyfacts WHERE "
            "trim(taxonomy) = '' OR trim(tag) = '' OR trim(unit) = '' "
            "OR trim(accession_number) = '') + "
            "(SELECT COUNT(*) FROM sec_submissions WHERE "
            "trim(accession_number) = '' OR trim(form) = '') + "
            "(SELECT COUNT(*) FROM openap_features_current WHERE "
            "trim(symbol) = '' OR trim(signalname) = '')"
        ).fetchone()[0]
    )
    inconsistent_feature_status = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current "
            "WHERE raw_value IS NULL AND status IN ('exact','proxy')"
        ).fetchone()[0]
    )
    ineligible_leaderboard_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_current_leaderboard WHERE NOT ranking_eligible"
        ).fetchone()[0]
    )
    stale_leaderboard_prices = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_current_leaderboard "
            "WHERE clean_price_staleness_days IS NULL OR clean_price_staleness_days > ?",
            [int(config["universe"]["maximum_price_age_days"])],
        ).fetchone()[0]
    )
    unsupported_official_filters = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current "
            "WHERE official_filter_status LIKE 'unsupported:%'"
        ).fetchone()[0]
    )
    weak_bucket_scores = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_overall_scores_current "
            "WHERE metrics_used < minimum_metrics_required AND score IS NOT NULL"
        ).fetchone()[0]
    )
    family_weight_cap_violations = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_overall_scores_current "
            "WHERE horizon_evidence_sufficient "
            "AND maximum_family_weight_actual > ? + 1e-12",
            [float(config["score"]["maximum_family_weight"])],
        ).fetchone()[0]
    )
    required_horizons = [int(value) for value in config["score"]["required_ranking_horizons"]]
    required_horizon_denominator_variants = int(
        connection.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT horizon_months FROM openap_overall_scores_current "
            f"WHERE horizon_months IN ({','.join(map(str, required_horizons))}) "
            "GROUP BY horizon_months HAVING COUNT(DISTINCT (metrics_expected, groups_expected)) <> 1)"
        ).fetchone()[0]
    )
    ranking_sec_download_failures = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_download_status d "
            "INNER JOIN security_master s ON d.cik = s.cik "
            "WHERE s.ranking_eligible "
            "AND d.status NOT IN ('ok','repaired_bulk')"
        ).fetchone()[0]
    )
    sec_download_errors = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_download_status "
            "WHERE status NOT IN ('ok','repaired_bulk')"
        ).fetchone()[0]
    )
    sec_direct_downloads = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_download_status "
            "WHERE status = 'ok' AND source_mode = 'sec_official_api'"
        ).fetchone()[0]
    )
    sec_jina_fallback_downloads = int(
        connection.execute(
            "SELECT COUNT(*) FROM sec_download_status "
            "WHERE status = 'ok' AND source_mode = 'sec_via_jina_readthrough'"
        ).fetchone()[0]
    )
    uninformative_weighted_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current "
            "WHERE value_status = 'uninformative_cross_section' "
            "AND (status <> 'unavailable' OR evidence_weight <> 0)"
        ).fetchone()[0]
    )
    weighted_constant_predictors = int(
        connection.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT signalname FROM openap_features_current "
            "WHERE status IN ('exact','proxy') AND evidence_weight > 0 AND raw_value IS NOT NULL "
            "GROUP BY signalname HAVING COUNT(*) >= 3 AND COUNT(DISTINCT raw_value) <= 1)"
        ).fetchone()[0]
    )
    stale_sec_leaderboard_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_current_leaderboard "
            "WHERE sec_input_age_days IS NULL OR sec_input_age_days > ?",
            [int(config["score"]["maximum_sec_age_days_for_ranking"])],
        ).fetchone()[0]
    )
    stale_accounting_leaderboard_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_current_leaderboard "
            "WHERE accounting_input_age_days IS NULL OR accounting_input_age_days > ?",
            [
                int(
                    config["score"][
                        "maximum_accounting_input_age_days_for_ranking"
                    ]
                )
            ],
        ).fetchone()[0]
    )
    stale_weighted_feature_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current "
            "WHERE source_input_age_days > ? AND evidence_weight > 0",
            [
                int(
                    config["score"][
                        "maximum_accounting_input_age_days_for_ranking"
                    ]
                )
            ],
        ).fetchone()[0]
    )
    undercovered_leaderboard_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_current_leaderboard "
            "WHERE computed_features < ? OR missing_features > ? OR aggregate_confidence < ?",
            [
                int(config["score"]["minimum_computed_features_for_ranking"]),
                int(config["score"]["maximum_missing_features_for_ranking"]),
                float(config["score"]["minimum_aggregate_confidence"]),
            ],
        ).fetchone()[0]
    )
    forbidden_exact_signals = tuple(sorted(ACCOUNTING_PROXY_LIMITS)) + ("Size",)
    placeholders = ",".join("?" for _ in forbidden_exact_signals)
    exact_formula_policy_violations = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current "
            f"WHERE status = 'exact' AND signalname IN ({placeholders})",
            list(forbidden_exact_signals),
        ).fetchone()[0]
    )
    mixed_unit_turnover_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current WHERE formula_id IN "
            "('mean_volume_21d','volume_std_proxy_252d','mean_share_volume_over_sec_shares',"
            "'volume_std_over_sec_shares')"
        ).fetchone()[0]
    )
    shallow_option_feature_rows = int(
        connection.execute(
            "SELECT COUNT(*) FROM openap_features_current f "
            "LEFT JOIN data_quality_current q USING (symbol) "
            "WHERE f.source = 'yfinance_current_option_chain' "
            "AND f.raw_value IS NOT NULL AND NOT COALESCE(q.option_depth_pass, FALSE)"
        ).fetchone()[0]
    )
    overall_score_scale_violations = int(
        connection.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT as_of, MIN(aggregate_score) lo, MAX(aggregate_score) hi, "
            "COUNT(aggregate_score) n FROM openap_current_leaderboard GROUP BY as_of) "
            "WHERE n > 1 AND (ABS(lo) > 1e-9 OR ABS(hi - 100.0) > 1e-9)"
        ).fetchone()[0]
    )
    score_contribution_mismatches = int(
        connection.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT s.as_of, s.symbol, s.horizon_months, s.raw_score, "
            "SUM(c.raw_score_contribution) contribution_sum "
            "FROM openap_overall_scores_current s "
            "JOIN openap_score_contributions_current c USING (as_of, symbol, horizon_months) "
            "WHERE s.horizon_months = 0 AND s.raw_score IS NOT NULL "
            "GROUP BY s.as_of, s.symbol, s.horizon_months, s.raw_score) "
            "WHERE ABS(raw_score - contribution_sum) > 1e-8"
        ).fetchone()[0]
    )
    issue_counts = {
        "duplicate_price_rows": duplicate_prices,
        "future_price_rows": future_price_rows,
        "facts_without_available_at": facts_without_available_at,
        "concept_inputs_without_available_at": concept_inputs_without_available_at,
        "future_concept_inputs": future_concept_inputs,
        "concept_inputs_before_period_end": concept_inputs_before_period_end,
        "concept_inputs_before_filed": concept_inputs_before_filed,
        "invalid_concept_units": invalid_concept_units,
        "duplicate_companyfacts": duplicate_companyfacts,
        "duplicate_submissions": duplicate_submissions,
        "blank_required_identifiers": blank_required_identifiers,
        "inconsistent_feature_status": inconsistent_feature_status,
        "ineligible_leaderboard_rows": ineligible_leaderboard_rows,
        "stale_leaderboard_prices": stale_leaderboard_prices,
        "unsupported_official_filters": unsupported_official_filters,
        "weak_bucket_scores": weak_bucket_scores,
        "family_weight_cap_violations": family_weight_cap_violations,
        "required_horizon_denominator_variants": required_horizon_denominator_variants,
        "ranking_sec_download_failures": ranking_sec_download_failures,
        "uninformative_weighted_rows": uninformative_weighted_rows,
        "weighted_constant_predictors": weighted_constant_predictors,
        "stale_sec_leaderboard_rows": stale_sec_leaderboard_rows,
        "stale_accounting_leaderboard_rows": stale_accounting_leaderboard_rows,
        "stale_weighted_feature_rows": stale_weighted_feature_rows,
        "undercovered_leaderboard_rows": undercovered_leaderboard_rows,
        "exact_formula_policy_violations": exact_formula_policy_violations,
        "mixed_unit_turnover_rows": mixed_unit_turnover_rows,
        "shallow_option_feature_rows": shallow_option_feature_rows,
        "overall_score_scale_violations": overall_score_scale_violations,
        "score_contribution_mismatches": score_contribution_mismatches,
    }
    warning_counts = {
        "nonranking_sec_download_errors": max(
            sec_download_errors - ranking_sec_download_failures, 0
        ),
        "sec_jina_fallback_downloads": sec_jina_fallback_downloads,
        "raw_nonpositive_price_rows_quarantined": raw_nonpositive_price_rows,
        "stale_sec_inputs_over_warning_age": int(
            connection.execute(
                "SELECT COUNT(*) FROM openap_scores_aggregate_current "
                "WHERE sec_input_age_days > ?",
                [int(config["score"]["sec_freshness_warning_days"])],
            ).fetchone()[0]
        ),
        "stale_accounting_inputs_over_warning_age": int(
            connection.execute(
                "SELECT COUNT(*) FROM openap_scores_aggregate_current "
                "WHERE accounting_input_age_days > ?",
                [int(config["score"]["accounting_freshness_warning_days"])],
            ).fetchone()[0]
        ),
        "nondeployable_research_leaderboard_rows": int(
            connection.execute(
                "SELECT COUNT(*) FROM openap_current_leaderboard "
                "WHERE NOT deployment_eligible"
            ).fetchone()[0]
        ),
        "legacy_redundancy_audit_missing": int(
            redundancy_audit_source_status != "source_artifact"
        ),
        "secondary_common_share_classes_retained": int(
            (
                security_master["eligible_common_stock"]
                & ~security_master["issuer_primary_security"]
            ).sum()
        ),
    }
    issues = pd.DataFrame(
        [
            {"check_name": name, "severity": "error", "issue_count": count, "passed": count == 0}
            for name, count in issue_counts.items()
        ]
        + [
            {"check_name": name, "severity": "warning", "issue_count": count, "passed": count == 0}
            for name, count in warning_counts.items()
        ]
    )
    issues.to_csv(output / "data_quality_issues.csv", index=False)
    connection.execute(
        "CREATE OR REPLACE TABLE data_quality_issues AS SELECT * FROM read_csv_auto(?)",
        [str(output / "data_quality_issues.csv")],
    )
    connection.close()

    exact_predictors = int((coverage["coverage_status"] == "exact").sum())
    proxy_predictors = int((coverage["coverage_status"] == "proxy").sum())
    mixed_predictors = int((coverage["coverage_status"] == "mixed").sum())
    unavailable_predictors = int((coverage["coverage_status"] == "unavailable").sum())
    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in summary_paths]
    if len(sec_summary_paths) != expected_sec_chunks:
        raise OpenAPDataError(
            f"Expected {expected_sec_chunks} SEC summaries, found {len(sec_summary_paths)}"
        )
    sec_summaries = [json.loads(path.read_text(encoding="utf-8")) for path in sec_summary_paths]
    yahoo_source_manifest = pd.DataFrame(summaries).sort_values("chunk_index")
    sec_source_manifest = pd.DataFrame(sec_summaries).sort_values("chunk_index")
    yahoo_hash_sources = {
        "prices_sha256": price_paths,
        "metadata_sha256": metadata_paths,
        "options_sha256": option_paths,
        "analyst_sha256": analyst_paths,
        "status_sha256": yahoo_status_paths,
        "summary_sha256": summary_paths,
    }
    for column, paths in yahoo_hash_sources.items():
        hashes = _hashes_by_chunk(paths)
        yahoo_source_manifest[column] = yahoo_source_manifest["chunk_index"].map(hashes)
    sec_hash_sources = {
        "companyfacts_parquet_sha256": sec_fact_paths,
        "submissions_parquet_sha256": sec_submission_paths,
        "status_sha256": sec_status_paths,
        "summary_sha256": sec_summary_paths,
    }
    for column, paths in sec_hash_sources.items():
        hashes = _hashes_by_chunk(paths)
        sec_source_manifest[column] = sec_source_manifest["chunk_index"].map(hashes)
    source_manifest.to_csv(output / "source_manifest.csv", index=False)
    yahoo_source_manifest.to_csv(output / "yfinance_source_manifest.csv", index=False)
    sec_source_manifest.to_csv(output / "sec_source_manifest.csv", index=False)
    connection = duckdb.connect(str(db_path))
    connection.execute(
        "CREATE OR REPLACE TABLE source_manifest AS SELECT * FROM read_csv_auto(?)",
        [str(output / "source_manifest.csv")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE yfinance_source_manifest AS SELECT * FROM read_csv_auto(?)",
        [str(output / "yfinance_source_manifest.csv")],
    )
    connection.execute(
        "CREATE OR REPLACE TABLE sec_source_manifest AS SELECT * FROM read_csv_auto(?)",
        [str(output / "sec_source_manifest.csv")],
    )
    (
        schema_contract_rows,
        database_index_rows,
        database_contract_violations,
    ) = finalize_database_contract(
        connection, output
    )
    issues = pd.concat(
        [
            issues,
            pd.DataFrame(
                [
                    {
                        "check_name": "database_contract_violations",
                        "severity": "error",
                        "issue_count": database_contract_violations,
                        "passed": database_contract_violations == 0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    issues.to_csv(output / "data_quality_issues.csv", index=False)
    connection.register("data_quality_issues_frame", issues)
    connection.execute(
        "CREATE OR REPLACE TABLE data_quality_issues AS "
        "SELECT * FROM data_quality_issues_frame"
    )
    connection.unregister("data_quality_issues_frame")
    connection.close()
    sec_companyfacts_rows = sum(int(item.get("companyfacts_rows", 0)) for item in sec_summaries)
    sec_submissions_rows = sum(int(item.get("submissions_rows", 0)) for item in sec_summaries)
    all_facts_have_available_at = facts_without_available_at == 0
    summary = {
        "dataset_id": config["dataset_id"],
        "completed_at": _utcnow(),
        "as_of": as_of.isoformat(),
        "input_predictors": len(metadata),
        "eligible_symbols": len(values_by_symbol),
        "security_master_rows": len(security_master),
        "security_exclusion_rows": int((~security_master["eligible_common_stock"]).sum()),
        "common_stock_exclusion_rows": int((~security_master["eligible_common_stock"]).sum()),
        "multi_share_class_issuer_count": int(
            security_master.loc[
                security_master["eligible_common_stock"]
                & security_master["issuer_share_class_count"].gt(1),
                "cik",
            ].nunique()
        ),
        "secondary_common_share_classes_retained": int(
            (
                security_master["eligible_common_stock"]
                & ~security_master["issuer_primary_security"]
            ).sum()
        ),
        "ranking_exclusion_rows": int((~security_master["ranking_eligible"]).sum()),
        "price_rows": int(sum(int(item.get("price_rows", 0)) for item in summaries)),
        "raw_price_rows_in_database": raw_price_rows_db,
        "clean_price_rows_in_database": clean_price_rows_db,
        "options_raw_rows": options_raw_rows,
        "options_usable_rows": options_usable_rows,
        "sec_companyfacts_rows": sec_companyfacts_rows_db,
        "sec_companyfacts_rows_before_bulk_repair": sec_companyfacts_rows,
        "sec_bulk_repair_requested": sec_bulk_repair["requested"],
        "sec_bulk_repair_completed": sec_bulk_repair["repaired"],
        "sec_bulk_repair_still_missing": sec_bulk_repair["still_missing"],
        "sec_bulk_repair_sha256": sec_bulk_repair["bulk_sha256"],
        "sec_submissions_rows": sec_submissions_rows,
        "exact_predictors_with_any_value": exact_predictors,
        "proxy_predictors_with_any_value": proxy_predictors,
        "mixed_predictors_with_exact_and_proxy_rows": mixed_predictors,
        "unavailable_predictors": unavailable_predictors,
        "coverage_rows": len(coverage),
        "scores_rows": len(scores),
        "overall_scores_rows": len(overall_scores),
        "aggregate_scores_rows": len(aggregate_scores),
        "leaderboard_rows": len(leaderboard),
        "deployable_leaderboard_rows": len(deployable_leaderboard),
        "score_contribution_rows": len(score_contributions),
        "score_horizons": sorted(scores["horizon_months"].dropna().astype(int).unique().tolist()),
        "ranking_score_mode": str(config["score"]["ranking_score_mode"]),
        "redundancy_audit_source_status": redundancy_audit_source_status,
        "features_rows": len(feature_frame),
        "all_facts_have_available_at": all_facts_have_available_at,
        "locked_opened": False,
        "backtest_enabled": False,
        "validation_used_for_selection": False,
        "partial": False,
        "raw_sec_archives_preserved_in_run": True,
        "raw_sec_archives_in_final_artifact": False,
        "raw_sec_archive_retention_days": int(config["execution"]["artifact_retention_days"]),
        "sec_chunks_found": len(sec_summary_paths),
        "sec_source_layout": sec_layout,
        "duplicate_price_rows": duplicate_prices,
        "future_price_rows": future_price_rows,
        "facts_without_available_at": facts_without_available_at,
        "sec_concept_input_rows": len(sec_concept_inputs),
        "concept_inputs_without_available_at": concept_inputs_without_available_at,
        "future_concept_inputs": future_concept_inputs,
        "concept_inputs_before_period_end": concept_inputs_before_period_end,
        "concept_inputs_before_filed": concept_inputs_before_filed,
        "invalid_concept_units": invalid_concept_units,
        "duplicate_companyfacts": duplicate_companyfacts,
        "duplicate_submissions": duplicate_submissions,
        "blank_required_identifiers": blank_required_identifiers,
        "inconsistent_feature_status": inconsistent_feature_status,
        "ineligible_leaderboard_rows": ineligible_leaderboard_rows,
        "stale_leaderboard_prices": stale_leaderboard_prices,
        "unsupported_official_filters": unsupported_official_filters,
        "weak_bucket_scores": weak_bucket_scores,
        "family_weight_cap_violations": family_weight_cap_violations,
        "required_horizon_denominator_variants": required_horizon_denominator_variants,
        "ranking_sec_download_failures": ranking_sec_download_failures,
        "uninformative_weighted_rows": uninformative_weighted_rows,
        "weighted_constant_predictors": weighted_constant_predictors,
        "stale_sec_leaderboard_rows": stale_sec_leaderboard_rows,
        "stale_accounting_leaderboard_rows": stale_accounting_leaderboard_rows,
        "stale_weighted_feature_rows": stale_weighted_feature_rows,
        "undercovered_leaderboard_rows": undercovered_leaderboard_rows,
        "exact_formula_policy_violations": exact_formula_policy_violations,
        "mixed_unit_turnover_rows": mixed_unit_turnover_rows,
        "shallow_option_feature_rows": shallow_option_feature_rows,
        "overall_score_scale_violations": overall_score_scale_violations,
        "score_contribution_mismatches": score_contribution_mismatches,
        "sec_download_errors": sec_download_errors,
        "sec_direct_downloads": sec_direct_downloads,
        "sec_jina_fallback_downloads": sec_jina_fallback_downloads,
        "score_validation_status": str(config["score"]["validation_status"]),
        "prediction_probability_claimed": False,
        "source_manifest_rows": len(source_manifest),
        "yfinance_source_manifest_rows": len(yahoo_source_manifest),
        "sec_source_manifest_rows": len(sec_source_manifest),
        "schema_contract_rows": schema_contract_rows,
        "database_index_rows": database_index_rows,
        "database_contract_violations": database_contract_violations,
        "pipeline_git_sha": os.environ.get("GITHUB_SHA", ""),
        "config_sha256": sha256_file(args.config),
    }
    if any(issue_counts.values()) or database_contract_violations:
        raise OpenAPDataError(
            "Data-quality gate failed: "
            + ", ".join(
                [f"{name}={count}" for name, count in issue_counts.items() if count]
                + ([f"database_contract_violations={database_contract_violations}"] if database_contract_violations else [])
            )
        )
    if len(coverage) != EXPECTED_PREDICTORS or len(feature_frame) != len(values_by_symbol) * EXPECTED_PREDICTORS:
        raise OpenAPDataError("Final feature or coverage row counts do not reconcile")
    write_summary(output / "execution_summary.json", summary)
    output_rows = []
    for path in sorted(output.iterdir()):
        if not path.is_file() or path.name == "output_manifest.csv":
            continue
        output_rows.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    pd.DataFrame(output_rows).to_csv(output / "output_manifest.csv", index=False)


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
    sec_parser = subparsers.add_parser("sec-chunk")
    sec_parser.add_argument("--security-master", required=True)
    sec_parser.add_argument("--sec-user-agent", required=True)
    sec_parser.add_argument("--chunk-index", type=int, required=True)
    sec_parser.add_argument("--total-chunks", type=int, required=True)
    sec_parser.add_argument("--output-dir", required=True)
    sec_bulk_parser = subparsers.add_parser("sec-bulk")
    sec_bulk_parser.add_argument("--security-master", required=True)
    sec_bulk_parser.add_argument("--sec-user-agent", required=True)
    sec_bulk_parser.add_argument("--output-dir", required=True)
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
    elif args.mode == "sec-chunk":
        sec_chunk(config, args)
    elif args.mode == "sec-bulk":
        sec_bulk(config, args)
    elif args.mode == "merge":
        merge(config, args)
    else:
        raise OpenAPDataError(f"Unsupported mode: {args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

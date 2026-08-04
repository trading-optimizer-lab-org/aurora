"""Bounded, fail-closed data acquisition for the SPY daily campaign."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from aurora.core.execution_policy import require_github_only_execution
from aurora.infra.sp500_long_short_daily.contracts import (
    LOCKED_START,
    TRAIN_END,
    VALIDATION_END,
    CampaignPackage,
    LockedBoundaryError,
    assert_frame_before_locked,
    canonical_json_hash,
)
from aurora.infra.sp500_long_short_daily.ledger import build_total_return_ledger


YAHOO_CHART_ENDPOINTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
)
STOOQ_HISTORY_PAGE = "https://stooq.com/q/d/"
STOOQ_VERIFY = "https://stooq.com/__verify"
FRED_DOWNLOAD = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
SPY_RETURN_TOLERANCE = 5e-4
SPY_REQUIRED_TOLERANCE_FRACTION = 0.995
SPONSOR_EVENT_AMOUNT_TOLERANCE = 5.001e-4
STOOQ_MAX_BOUNDED_PAGES = 100
STOOQ_PUBLIC_HISTORY_ROW_CAP = 1000
STOOQ_PAGE_DELAY_SECONDS = 1.25


class DataGateError(RuntimeError):
    """Raised when a required source cannot satisfy the frozen contract."""


@dataclass(frozen=True)
class DownloadReceipt:
    dataset_id: str
    url_template: str
    sha256: str
    byte_count: int
    minimum_date: str | None
    maximum_date: str | None
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class PreparedMarketData:
    ledger: pd.DataFrame
    series: Mapping[str, pd.Series]
    available_dataset_ids: frozenset[str]
    rejected_datasets: Mapping[str, str]
    receipts: tuple[DownloadReceipt, ...]
    split: str


def _repo_campaign_root() -> Path:
    candidates: list[Path] = []
    github_workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if github_workspace:
        candidates.append(Path(github_workspace))
    candidates.extend((Path.cwd(), Path(__file__).resolve().parents[2]))
    for root in candidates:
        campaign = root / "campaigns" / "sp500_long_short_daily"
        if (campaign / "official_inputs").is_dir():
            return campaign.resolve()
    raise DataGateError("SP500_CAMPAIGN_OFFICIAL_INPUTS_NOT_FOUND")


def _epoch_seconds(value: pd.Timestamp) -> int:
    timestamp = pd.Timestamp(value, tz="UTC")
    return int(timestamp.timestamp())


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _store_raw(raw_dir: Path | None, filename: str, payload: bytes) -> None:
    if raw_dir is None:
        return
    root = Path(raw_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    target.write_bytes(payload)
    if _sha256(target.read_bytes()) != _sha256(payload):
        raise DataGateError(f"RAW_SNAPSHOT_HASH_MISMATCH:{filename}")


def _bounded_dates(start: Any, end: Any, *, split: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start_date = pd.Timestamp(start).normalize()
    end_date = pd.Timestamp(end).normalize()
    if end_date >= LOCKED_START:
        raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:data_request")
    if split == "train" and end_date > TRAIN_END:
        raise DataGateError("TRAIN_REQUEST_CROSSES_SELECTION_BOUNDARY")
    if split == "validation" and (
        start_date < TRAIN_END + pd.Timedelta(days=1) or end_date > VALIDATION_END
    ):
        raise DataGateError("VALIDATION_REQUEST_OUTSIDE_FROZEN_BOUNDARY")
    return start_date, end_date


def _request_bytes(
    session: requests.Session,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    attempts: int = 4,
    timeout: int = 60,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.content
            if not payload:
                raise DataGateError("EMPTY_HTTP_RESPONSE")
            return payload
        except (requests.RequestException, DataGateError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise DataGateError(f"DOWNLOAD_FAILED:{type(last_error).__name__}")


def _solve_stooq_browser_verification(session: requests.Session, payload: bytes) -> bool:
    """Complete Stooq's deterministic JavaScript proof-of-work using HTTP only."""

    if b"/__verify" not in payload or b"crypto.subtle.digest" not in payload:
        return False
    match = re.search(rb'const c="([^"]+)",d=(\d+)', payload)
    if match is None:
        raise DataGateError("STOOQ_VERIFICATION_SCHEMA_MISMATCH")
    challenge = match.group(1).decode("ascii")
    difficulty = int(match.group(2))
    if difficulty < 1 or difficulty > 6:
        raise DataGateError("STOOQ_VERIFICATION_DIFFICULTY_OUT_OF_RANGE")
    prefix = "0" * difficulty
    nonce: int | None = None
    for candidate in range(10_000_000):
        digest = hashlib.sha256(f"{challenge}{candidate}".encode()).hexdigest()
        if digest.startswith(prefix):
            nonce = candidate
            break
    if nonce is None:
        raise DataGateError("STOOQ_VERIFICATION_NONCE_NOT_FOUND")
    try:
        response = session.post(
            STOOQ_VERIFY,
            data={"c": challenge, "n": str(nonce)},
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DataGateError("STOOQ_VERIFICATION_POST_FAILED") from exc
    return True


def _parse_csv(payload: bytes) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(payload))
    except Exception as exc:
        raise DataGateError("INVALID_CSV_RESPONSE") from exc


class _StooqHistoryHTMLParser(HTMLParser):
    """Collect Stooq history rows and pagination links from public HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.hrefs: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


_STOOQ_MONTHS = {
    "jan": 1,
    "sty": 1,
    "feb": 2,
    "lut": 2,
    "mar": 3,
    "apr": 4,
    "kwi": 4,
    "may": 5,
    "maj": 5,
    "jun": 6,
    "cze": 6,
    "jul": 7,
    "lip": 7,
    "aug": 8,
    "sie": 8,
    "sep": 9,
    "wrz": 9,
    "oct": 10,
    "paz": 10,
    "paź": 10,
    "nov": 11,
    "lis": 11,
    "dec": 12,
    "gru": 12,
}


def _parse_stooq_display_date(value: str) -> pd.Timestamp:
    parts = value.replace("\xa0", " ").strip().split()
    if len(parts) != 3:
        raise DataGateError("STOOQ_HTML_DATE_SCHEMA_MISMATCH")
    month = _STOOQ_MONTHS.get(parts[1].casefold())
    if month is None:
        raise DataGateError("STOOQ_HTML_MONTH_SCHEMA_MISMATCH")
    try:
        return pd.Timestamp(year=int(parts[2]), month=month, day=int(parts[0]))
    except ValueError as exc:
        raise DataGateError("STOOQ_HTML_INVALID_DATE") from exc


def _parse_stooq_html_history(payload: bytes) -> tuple[pd.DataFrame, int]:
    """Parse bounded Stooq OHLCV rows without retaining page-level current quotes."""

    parser = _StooqHistoryHTMLParser()
    parser.feed(payload.decode("utf-8", errors="ignore"))
    parsed: list[dict[str, Any]] = []
    for cells in parser.rows:
        if len(cells) < 7 or not cells[0].replace(",", "").isdigit():
            continue
        try:
            parsed.append(
                {
                    "Date": _parse_stooq_display_date(cells[1]),
                    "Open": float(cells[2].replace(",", "")),
                    "High": float(cells[3].replace(",", "")),
                    "Low": float(cells[4].replace(",", "")),
                    "Close": float(cells[5].replace(",", "")),
                    "Volume": int(float(cells[-1].replace(",", ""))),
                }
            )
        except (ValueError, DataGateError) as exc:
            raise DataGateError("STOOQ_HTML_ROW_SCHEMA_MISMATCH") from exc
    if not parsed:
        raise DataGateError("STOOQ_HTML_HISTORY_ROWS_NOT_FOUND")
    page_numbers = [
        int(match.group(1))
        for href in parser.hrefs
        if "q/d/?" in href
        and (match := re.search(r"(?:[?&])l=(\d+)(?:&|$)", href)) is not None
    ]
    page_count = max(page_numbers, default=1)
    frame = pd.DataFrame(parsed).drop_duplicates(subset=["Date"], keep="last")
    return frame, page_count


def _request_stooq_history_page(
    client: requests.Session,
    params: Mapping[str, Any],
    *,
    browser_profile: Path | None,
) -> bytes:
    if browser_profile is None:
        return _request_bytes(
            client,
            STOOQ_HISTORY_PAGE,
            params=params,
            attempts=2,
            timeout=15,
        )
    browser = next(
        (
            path
            for executable in (
                "google-chrome",
                "google-chrome-stable",
                "chromium",
                "chromium-browser",
            )
            if (path := shutil.which(executable)) is not None
        ),
        None,
    )
    if browser is None:
        raise DataGateError("STOOQ_HEADLESS_BROWSER_NOT_AVAILABLE")
    prepared = requests.Request("GET", STOOQ_HISTORY_PAGE, params=params).prepare()
    if prepared.url is None:
        raise DataGateError("STOOQ_HEADLESS_URL_BUILD_FAILED")
    command = [
        browser,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--virtual-time-budget=15000",
        f"--user-data-dir={browser_profile}",
        "--dump-dom",
        prepared.url,
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DataGateError("STOOQ_HEADLESS_BROWSER_FAILED") from exc
    payload = bytes(completed.stdout)
    if completed.returncode != 0 or not payload:
        raise DataGateError(
            f"STOOQ_HEADLESS_BROWSER_FAILED:returncode={completed.returncode}"
        )
    return payload


def _load_stooq_history_page(
    client: requests.Session,
    params: Mapping[str, Any],
    *,
    browser_profile: Path | None,
    attempts: int = 3,
) -> tuple[bytes, pd.DataFrame, int]:
    """Fetch and validate one page, retrying transient verification screens."""

    last_error: DataGateError | None = None
    for attempt in range(1, attempts + 1):
        payload = _request_stooq_history_page(
            client,
            params,
            browser_profile=browser_profile,
        )
        if browser_profile is None and _solve_stooq_browser_verification(client, payload):
            payload = _request_stooq_history_page(
                client,
                params,
                browser_profile=None,
            )
        try:
            frame, page_count = _parse_stooq_html_history(payload)
            return payload, frame, page_count
        except DataGateError as exc:
            if str(exc) != "STOOQ_HTML_HISTORY_ROWS_NOT_FOUND" or attempt == attempts:
                raise
            last_error = exc
            time.sleep(float(attempt))
    raise DataGateError("STOOQ_HTML_HISTORY_ROWS_NOT_FOUND") from last_error


def _download_stooq_html_history(
    client: requests.Session,
    symbol: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> tuple[pd.DataFrame, bytes, str, int]:
    """Read Stooq's public bounded historical-data pages."""

    browser_profile: Path | None = None
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        temp_root = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
        browser_profile = temp_root / "aurora-stooq-browser-profile"
        browser_profile.mkdir(parents=True, exist_ok=True)
    print("[sp500-data] stooq first page start", flush=True)
    first_params: Mapping[str, Any] = {
        "s": symbol.lower(),
        "d1": start_date.strftime("%Y%m%d"),
        "d2": end_date.strftime("%Y%m%d"),
        "i": "d",
    }
    first_payload, first_frame, page_count = _load_stooq_history_page(
        client,
        first_params,
        browser_profile=browser_profile,
    )
    print(
        f"[sp500-data] stooq first page complete rows={len(first_frame)} pages={page_count}",
        flush=True,
    )
    if page_count > STOOQ_MAX_BOUNDED_PAGES:
        raise DataGateError(f"STOOQ_HTML_PAGE_COUNT_OUT_OF_RANGE:{page_count}")
    frames = [first_frame]
    payload_hashes = [_sha256(first_payload)]

    def fetch_page(page: int) -> tuple[int, bytes, pd.DataFrame, int]:
        print(f"[sp500-data] stooq page={page} start", flush=True)
        page_client = client
        owned_client: requests.Session | None = None
        if isinstance(client, requests.Session):
            owned_client = requests.Session()
            owned_client.headers.update(client.headers)
            owned_client.headers["Referer"] = STOOQ_HISTORY_PAGE
            owned_client.cookies.update(client.cookies)
            page_client = owned_client
        try:
            payload, page_frame, reported_page_count = _load_stooq_history_page(
                page_client,
                {
                    "s": symbol.lower(),
                    "i": "d",
                    "f": start_date.strftime("%Y%m%d"),
                    "t": end_date.strftime("%Y%m%d"),
                    "l": page,
                },
                browser_profile=browser_profile,
            )
            print(f"[sp500-data] stooq page={page} complete", flush=True)
            return page, payload, page_frame, reported_page_count
        finally:
            if owned_client is not None:
                owned_client.close()

    for page in range(2, page_count + 1):
        if isinstance(client, requests.Session):
            time.sleep(STOOQ_PAGE_DELAY_SECONDS)
        try:
            _, page_payload, page_frame, reported_page_count = fetch_page(page)
        except DataGateError as exc:
            accumulated_rows = sum(len(frame) for frame in frames)
            terminal_public_cap = (
                str(exc) == "STOOQ_HTML_HISTORY_ROWS_NOT_FOUND"
                and page == page_count
                and accumulated_rows >= STOOQ_PUBLIC_HISTORY_ROW_CAP
            )
            if not terminal_public_cap:
                raise
            print(
                "[sp500-data] stooq terminal empty page accepted "
                f"after public row cap={accumulated_rows}",
                flush=True,
            )
            break
        if reported_page_count > page_count:
            raise DataGateError("STOOQ_HTML_PAGINATION_CHANGED_DURING_DOWNLOAD")
        frames.append(page_frame)
        payload_hashes.append(_sha256(page_payload))
    frame = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["Date"], keep="last")
        .sort_values("Date", kind="mergesort")
        .reset_index(drop=True)
    )
    canonical_payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    response_chain_hash = _sha256("\n".join(payload_hashes).encode("ascii"))
    return frame, canonical_payload, response_chain_hash, page_count


def _assert_response_date_bound(
    frame: pd.DataFrame,
    *,
    date_column: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    label: str,
) -> pd.DataFrame:
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    if dates.isna().any():
        raise DataGateError(f"INVALID_DATES:{label}")
    normalized = dates.dt.normalize()
    if len(normalized) and (normalized.min() < start or normalized.max() > end):
        raise DataGateError(f"UNBOUNDED_SOURCE_RESPONSE:{label}")
    result = frame.copy()
    result[date_column] = normalized
    assert_frame_before_locked(result, label=label)
    return result


def _parse_yahoo_chart(
    payload: bytes,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, bytes]:
    """Parse only bounded daily observations and discard Yahoo quote metadata."""

    try:
        document = json.loads(payload)
        chart = document["chart"]
        if chart.get("error") is not None:
            raise DataGateError("YAHOO_CHART_ERROR")
        results = chart.get("result") or []
        if len(results) != 1:
            raise DataGateError("YAHOO_CHART_RESULT_COUNT")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [])[0]
        adjusted_groups = result.get("indicators", {}).get("adjclose") or []
        adjusted = adjusted_groups[0].get("adjclose", []) if adjusted_groups else []
    except DataGateError:
        raise
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise DataGateError("YAHOO_CHART_SCHEMA_MISMATCH") from exc

    columns = {
        "open": quote.get("open", []),
        "high": quote.get("high", []),
        "low": quote.get("low", []),
        "close": quote.get("close", []),
        "volume": quote.get("volume", []),
    }
    lengths = {len(timestamps), len(adjusted), *(len(values) for values in columns.values())}
    if len(lengths) != 1:
        raise DataGateError("YAHOO_CHART_ARRAY_LENGTH_MISMATCH")

    dates = pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None).normalize()
    prices = pd.DataFrame(
        {
            "date": dates,
            **columns,
            "adj_close": adjusted,
        }
    )[["date", "open", "high", "low", "close", "adj_close", "volume"]]
    prices = _assert_response_date_bound(
        prices,
        date_column="date",
        start=start,
        end=end,
        label="yahoo_history",
    )

    events = result.get("events") or {}

    def event_frame(name: str, value_name: str) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for event in (events.get(name) or {}).values():
            event_timestamp = event.get("date")
            if event_timestamp is None:
                raise DataGateError(f"YAHOO_EVENT_DATE_MISSING:{name}")
            if name == "splits":
                numerator = event.get("numerator")
                denominator = event.get("denominator")
                if numerator is None or denominator in (None, 0):
                    raise DataGateError("YAHOO_SPLIT_RATIO_MISSING")
                value = float(numerator) / float(denominator)
            else:
                value = event.get("amount")
            rows.append(
                {
                    "date": pd.to_datetime(event_timestamp, unit="s", utc=True)
                    .tz_localize(None)
                    .normalize(),
                    value_name: value,
                }
            )
        frame = pd.DataFrame(rows, columns=["date", value_name])
        if len(frame):
            frame[value_name] = pd.to_numeric(frame[value_name], errors="raise")
            frame = frame.sort_values("date", kind="mergesort").reset_index(drop=True)
        return _assert_response_date_bound(
            frame,
            date_column="date",
            start=start,
            end=end,
            label=f"yahoo_{name}",
        )

    dividends = event_frame("dividends", "distribution")
    splits = event_frame("splits", "split_ratio")
    bounded_prices = prices.assign(date=prices["date"].dt.strftime("%Y-%m-%d"))
    bounded_prices = bounded_prices.astype(object).where(pd.notna(bounded_prices), None)
    bounded_snapshot = json.dumps(
        {
            "prices": bounded_prices.to_dict(orient="records"),
            "dividends": dividends.assign(date=dividends["date"].dt.strftime("%Y-%m-%d")).to_dict(
                orient="records"
            ),
            "splits": splits.assign(date=splits["date"].dt.strftime("%Y-%m-%d")).to_dict(
                orient="records"
            ),
        },
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return prices, dividends, splits, bounded_snapshot


def download_yahoo_history(
    symbol: str,
    start: Any,
    end: Any,
    *,
    split: str,
    session: requests.Session | None = None,
    raw_dir: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[DownloadReceipt, ...]]:
    """Download bounded raw OHLC, dividends and splits from Yahoo chart JSON."""

    start_date, end_date = _bounded_dates(start, end, split=split)
    client = session or requests.Session()
    client.headers.update({"User-Agent": "Mozilla/5.0 AuroraResearch bounded-chart-json"})
    params = {
        "period1": _epoch_seconds(start_date),
        "period2": _epoch_seconds(end_date + pd.Timedelta(days=1)),
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
        "includePrePost": "false",
    }
    payload: bytes | None = None
    selected_url: str | None = None
    errors: list[str] = []
    for endpoint in YAHOO_CHART_ENDPOINTS:
        selected_url = endpoint.format(symbol=symbol)
        try:
            payload = _request_bytes(client, selected_url, params=params, attempts=3)
            break
        except DataGateError as exc:
            errors.append(str(exc))
    if payload is None or selected_url is None:
        raise DataGateError(f"YAHOO_CHART_ENDPOINTS_FAILED:{'|'.join(errors)}")

    prices, dividends, splits, bounded_payload = _parse_yahoo_chart(
        payload,
        start=start_date,
        end=end_date,
    )
    _store_raw(raw_dir, f"yahoo_{symbol.lower()}_bounded_chart.json", bounded_payload)
    dates = prices["date"]
    receipts = (
        DownloadReceipt(
            dataset_id="YAHOO_SPY_BOUNDED_CHART",
            url_template=selected_url,
            sha256=_sha256(bounded_payload),
            byte_count=len(bounded_payload),
            minimum_date=dates.min().date().isoformat() if len(dates) else None,
            maximum_date=dates.max().date().isoformat() if len(dates) else None,
            status="downloaded_bounded_chart_json_current_metadata_discarded",
        ),
    )
    return prices, dividends, splits, receipts


def download_stooq_history(
    symbol: str,
    start: Any,
    end: Any,
    *,
    split: str,
    session: requests.Session | None = None,
    raw_dir: Path | None = None,
) -> tuple[pd.DataFrame, DownloadReceipt]:
    start_date, end_date = _bounded_dates(start, end, split=split)
    client = session or requests.Session()
    client.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    frame, payload, html_chain_hash, page_count = _download_stooq_html_history(
        client,
        symbol,
        start_date,
        end_date,
    )
    frame = _assert_response_date_bound(
        frame,
        date_column="Date",
        start=start_date,
        end=end_date,
        label=f"stooq_{symbol}",
    ).rename(columns=str.lower)
    _store_raw(raw_dir, f"stooq_{symbol.replace('.', '_').lower()}_history.csv", payload)
    dates = frame["date"]
    receipt = DownloadReceipt(
        dataset_id="DS002",
        url_template=STOOQ_HISTORY_PAGE,
        sha256=_sha256(payload),
        byte_count=len(payload),
        minimum_date=dates.min().date().isoformat() if len(dates) else None,
        maximum_date=dates.max().date().isoformat() if len(dates) else None,
        status="downloaded_bounded_html_public_history",
        reason=(
            f"page_count={page_count};raw_response_chain_sha256={html_chain_hash};"
            "transport="
            + (
                "headless_chrome"
                if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true"
                else "https"
            )
        ),
    )
    return frame[["date", "open", "high", "low", "close", "volume"]], receipt


def download_fred_series(
    series_id: str,
    dataset_id: str,
    start: Any,
    end: Any,
    *,
    split: str,
    session: requests.Session | None = None,
    raw_dir: Path | None = None,
) -> tuple[pd.Series, DownloadReceipt]:
    start_date, end_date = _bounded_dates(start, end, split=split)
    payload = _request_bytes(
        session or requests.Session(),
        FRED_DOWNLOAD,
        params={
            "id": series_id,
            "cosd": start_date.date().isoformat(),
            "coed": end_date.date().isoformat(),
        },
    )
    frame = _parse_csv(payload)
    if "DATE" not in frame.columns or series_id not in frame.columns:
        raise DataGateError(f"FRED_SCHEMA_MISMATCH:{series_id}")
    frame = _assert_response_date_bound(
        frame,
        date_column="DATE",
        start=start_date,
        end=end_date,
        label=f"fred_{series_id}",
    )
    _store_raw(raw_dir, f"fred_{dataset_id}_{series_id}.csv", payload)
    values = pd.to_numeric(frame[series_id].replace(".", pd.NA), errors="coerce")
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(frame["DATE"]), name=series_id)
    series = series.dropna().sort_index(kind="mergesort")
    receipt = DownloadReceipt(
        dataset_id=dataset_id,
        url_template=FRED_DOWNLOAD,
        sha256=_sha256(payload),
        byte_count=len(payload),
        minimum_date=series.index.min().date().isoformat() if len(series) else None,
        maximum_date=series.index.max().date().isoformat() if len(series) else None,
        status="downloaded",
    )
    return series, receipt


def download_alfred_initial_series(
    series_id: str,
    dataset_id: str,
    start: Any,
    end: Any,
    *,
    split: str,
    session: requests.Session | None = None,
    api_key: str | None = None,
    raw_dir: Path | None = None,
) -> tuple[pd.DataFrame, DownloadReceipt]:
    """Download initial releases only and retain their actual release dates."""

    start_date, end_date = _bounded_dates(start, end, split=split)
    key = api_key or os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise DataGateError("FRED_API_KEY_REQUIRED_FOR_INITIAL_RELEASE_VINTAGES")
    payload = _request_bytes(
        session or requests.Session(),
        FRED_API_OBSERVATIONS,
        params={
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "output_type": 4,
            "observation_start": start_date.date().isoformat(),
            "observation_end": end_date.date().isoformat(),
            "realtime_start": "1776-07-04",
            "realtime_end": end_date.date().isoformat(),
            "limit": 100000,
            "sort_order": "asc",
        },
    )
    try:
        decoded = json.loads(payload)
        observations = decoded["observations"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DataGateError(f"ALFRED_SCHEMA_MISMATCH:{series_id}") from exc
    rows = []
    for observation in observations:
        value = pd.to_numeric(observation.get("value"), errors="coerce")
        if pd.isna(value):
            continue
        observation_date = pd.Timestamp(observation["date"]).normalize()
        release_date = pd.Timestamp(observation["realtime_start"]).normalize()
        if observation_date < start_date or observation_date > end_date:
            raise DataGateError(f"UNBOUNDED_SOURCE_RESPONSE:alfred_{series_id}")
        if release_date > end_date:
            raise DataGateError(f"POST_PHASE_RELEASE_IN_RESPONSE:alfred_{series_id}")
        if release_date >= LOCKED_START:
            raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:alfred_release")
        rows.append(
            {
                "observation_date": observation_date,
                "release_date": release_date,
                "value": float(value),
            }
        )
    frame = pd.DataFrame(rows, columns=["observation_date", "release_date", "value"])
    if not frame.empty:
        frame = frame.sort_values(
            ["release_date", "observation_date"], kind="mergesort"
        ).drop_duplicates("release_date", keep="last")
    _store_raw(raw_dir, f"alfred_{dataset_id}_{series_id}.json", payload)
    receipt = DownloadReceipt(
        dataset_id=dataset_id,
        url_template=FRED_API_OBSERVATIONS,
        sha256=_sha256(payload),
        byte_count=len(payload),
        minimum_date=(frame["observation_date"].min().date().isoformat() if len(frame) else None),
        maximum_date=(frame["observation_date"].max().date().isoformat() if len(frame) else None),
        status="downloaded_initial_releases_only",
    )
    return frame, receipt


def load_state_street_distributions(
    path: Path,
    start: Any,
    end: Any,
    *,
    split: str,
) -> tuple[pd.DataFrame, DownloadReceipt]:
    """Load a pre-frozen official sponsor export without touching current data."""

    start_date, end_date = _bounded_dates(start, end, split=split)
    source = Path(path).resolve()
    if not source.is_file():
        raise DataGateError("STATE_STREET_DISTRIBUTION_SNAPSHOT_REQUIRED")
    payload = source.read_bytes()
    frame = _parse_csv(payload)
    required = {"ex_date", "distribution"}
    if not required.issubset(frame.columns):
        raise DataGateError("STATE_STREET_DISTRIBUTION_SCHEMA_MISMATCH")
    dates = pd.to_datetime(frame["ex_date"], errors="coerce").dt.normalize()
    values = pd.to_numeric(frame["distribution"], errors="coerce")
    if dates.isna().any() or values.isna().any() or (values < 0).any():
        raise DataGateError("STATE_STREET_DISTRIBUTION_INVALID_VALUES")
    phase_limit = TRAIN_END if split == "train" else VALIDATION_END
    if len(dates) and dates.max() > phase_limit:
        raise DataGateError("STATE_STREET_SNAPSHOT_EXCEEDS_PHASE_BOUNDARY")
    if len(dates) and dates.max() >= LOCKED_START:
        raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:sponsor_snapshot")
    bounded = pd.DataFrame({"date": dates, "distribution": values})
    bounded = bounded.loc[(bounded["date"] >= start_date) & (bounded["date"] <= end_date)]
    bounded = bounded.sort_values("date", kind="mergesort").reset_index(drop=True)
    if bounded["date"].duplicated().any():
        raise DataGateError("STATE_STREET_DISTRIBUTION_DUPLICATE_EX_DATE")
    receipt = DownloadReceipt(
        dataset_id="DS001",
        url_template="PINNED_STATE_STREET_SPY_DISTRIBUTION_EXPORT",
        sha256=_sha256(payload),
        byte_count=len(payload),
        minimum_date=bounded["date"].min().date().isoformat() if len(bounded) else None,
        maximum_date=bounded["date"].max().date().isoformat() if len(bounded) else None,
        status="loaded_official_frozen_snapshot",
    )
    return bounded, receipt


def load_sec_distribution_totals(
    path: Path,
    start: Any,
    end: Any,
    *,
    split: str,
) -> tuple[pd.DataFrame, DownloadReceipt]:
    """Load audited SPY distribution totals for explicitly bounded fiscal periods."""

    start_date, end_date = _bounded_dates(start, end, split=split)
    source = Path(path).resolve()
    if not source.is_file():
        raise DataGateError("SEC_DISTRIBUTION_TOTALS_SNAPSHOT_REQUIRED")
    payload = source.read_bytes()
    frame = _parse_csv(payload)
    required = {"period_start", "period_end", "distribution_total"}
    if not required.issubset(frame.columns):
        raise DataGateError("SEC_DISTRIBUTION_TOTALS_SCHEMA_MISMATCH")
    starts = pd.to_datetime(frame["period_start"], errors="coerce").dt.normalize()
    ends = pd.to_datetime(frame["period_end"], errors="coerce").dt.normalize()
    totals = pd.to_numeric(frame["distribution_total"], errors="coerce")
    if (
        starts.isna().any()
        or ends.isna().any()
        or totals.isna().any()
        or (starts > ends).any()
        or (totals < 0).any()
    ):
        raise DataGateError("SEC_DISTRIBUTION_TOTALS_INVALID_VALUES")
    phase_limit = TRAIN_END if split == "train" else VALIDATION_END
    if len(ends) and ends.max() > phase_limit:
        raise DataGateError("SEC_DISTRIBUTION_TOTALS_EXCEED_PHASE_BOUNDARY")
    if len(ends) and ends.max() >= LOCKED_START:
        raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:sec_distribution_totals")
    bounded = frame.copy()
    bounded["period_start"] = starts
    bounded["period_end"] = ends
    bounded["distribution_total"] = totals
    bounded = (
        bounded.loc[(bounded["period_end"] >= start_date) & (bounded["period_start"] <= end_date)]
        .sort_values("period_start", kind="mergesort")
        .reset_index(drop=True)
    )
    if bounded["period_start"].duplicated().any() or bounded["period_end"].duplicated().any():
        raise DataGateError("SEC_DISTRIBUTION_TOTALS_DUPLICATE_PERIOD")
    previous_end: pd.Timestamp | None = None
    for row in bounded.itertuples(index=False):
        if previous_end is not None and pd.Timestamp(row.period_start) <= previous_end:
            raise DataGateError("SEC_DISTRIBUTION_TOTALS_OVERLAPPING_PERIODS")
        previous_end = pd.Timestamp(row.period_end)
    receipt = DownloadReceipt(
        dataset_id="DS001_SEC_AUDITED_TOTALS",
        url_template="PINNED_SEC_AUDITED_SPY_DISTRIBUTION_TOTALS",
        sha256=_sha256(payload),
        byte_count=len(payload),
        minimum_date=(bounded["period_start"].min().date().isoformat() if len(bounded) else None),
        maximum_date=(bounded["period_end"].max().date().isoformat() if len(bounded) else None),
        status="loaded_official_frozen_audited_totals",
    )
    return bounded, receipt


def reconcile_sponsor_distributions(
    sponsor: pd.DataFrame,
    yahoo: pd.DataFrame,
    *,
    absolute_tolerance: float = SPONSOR_EVENT_AMOUNT_TOLERANCE,
) -> Mapping[str, Any]:
    left = sponsor.set_index("date")["distribution"].sort_index()
    right = yahoo.set_index("date")["distribution"].sort_index()
    if not left.index.equals(right.index):
        missing_sponsor = right.index.difference(left.index)
        missing_yahoo = left.index.difference(right.index)
        raise DataGateError(
            "SPONSOR_DISTRIBUTION_DATE_MISMATCH:"
            f"missing_sponsor={len(missing_sponsor)}:missing_yahoo={len(missing_yahoo)}"
        )
    differences = (left - right).abs()
    if len(differences) and bool((differences > absolute_tolerance).any()):
        raise DataGateError("SPONSOR_DISTRIBUTION_AMOUNT_MISMATCH")
    return {
        "event_count": int(len(left)),
        "maximum_absolute_amount_difference": (
            float(differences.max()) if len(differences) else 0.0
        ),
        "absolute_tolerance": absolute_tolerance,
    }


def reconcile_official_distribution_audit(
    exact_events: pd.DataFrame,
    fiscal_totals: pd.DataFrame,
    yahoo: pd.DataFrame,
    *,
    exact_tolerance: float = SPONSOR_EVENT_AMOUNT_TOLERANCE,
    rounded_total_tolerance: float = 0.005001,
) -> Mapping[str, Any]:
    """Verify operational Yahoo events against official event and audited totals."""

    operational = yahoo.loc[:, ["date", "distribution"]].copy()
    operational["date"] = pd.to_datetime(operational["date"]).dt.normalize()
    operational["distribution"] = pd.to_numeric(operational["distribution"], errors="coerce")
    operational = operational.sort_values("date", kind="mergesort").reset_index(drop=True)
    if (
        operational["date"].isna().any()
        or operational["distribution"].isna().any()
        or operational["date"].duplicated().any()
    ):
        raise DataGateError("OPERATIONAL_DISTRIBUTION_EVENTS_INVALID")
    if operational.empty:
        raise DataGateError("OPERATIONAL_DISTRIBUTION_EVENTS_EMPTY")

    exact_audit: Mapping[str, Any]
    if exact_events.empty:
        exact_audit = {
            "event_count": 0,
            "maximum_absolute_amount_difference": 0.0,
            "absolute_tolerance": exact_tolerance,
        }
    else:
        exact_start = pd.Timestamp(exact_events["date"].min()).normalize()
        exact_end = pd.Timestamp(exact_events["date"].max()).normalize()
        operational_exact_window = operational.loc[
            operational["date"].between(exact_start, exact_end)
        ]
        exact_audit = reconcile_sponsor_distributions(
            exact_events,
            operational_exact_window,
            absolute_tolerance=exact_tolerance,
        )

    period_rows: list[dict[str, Any]] = []
    covered_dates: set[pd.Timestamp] = set(exact_events["date"])
    for row in fiscal_totals.itertuples(index=False):
        period_start = pd.Timestamp(row.period_start).normalize()
        period_end = pd.Timestamp(row.period_end).normalize()
        in_period = operational.loc[operational["date"].between(period_start, period_end)]
        observed = float(in_period["distribution"].sum())
        expected = float(row.distribution_total)
        difference = abs(observed - expected)
        if difference > rounded_total_tolerance:
            raise DataGateError(
                "SEC_DISTRIBUTION_FISCAL_TOTAL_MISMATCH:"
                f"{period_start.date()}:{period_end.date()}:"
                f"observed={observed:.8f}:expected={expected:.8f}"
            )
        covered_dates.update(pd.Timestamp(value) for value in in_period["date"])
        period_rows.append(
            {
                "period_start": period_start.date().isoformat(),
                "period_end": period_end.date().isoformat(),
                "event_count": int(len(in_period)),
                "observed_total": observed,
                "audited_total": expected,
                "absolute_difference": difference,
            }
        )

    uncovered = [
        date.date().isoformat()
        for date in operational["date"]
        if pd.Timestamp(date) not in covered_dates
    ]
    if uncovered:
        raise DataGateError(
            "OPERATIONAL_DISTRIBUTION_EVENT_WITHOUT_OFFICIAL_COVERAGE:" + ",".join(uncovered[:10])
        )
    return {
        "operational_source": "Yahoo Finance bounded event endpoint",
        "official_verification_sources": [
            "State Street exact distribution events",
            "SEC audited fiscal distribution totals",
        ],
        "operational_event_count": int(len(operational)),
        "exact_event_audit": exact_audit,
        "fiscal_period_audit": period_rows,
        "uncovered_event_count": 0,
        "exact_tolerance": exact_tolerance,
        "rounded_total_tolerance": rounded_total_tolerance,
    }


FRED_DATASETS: Mapping[str, tuple[str, str]] = {
    "DS004": ("VIXCLS", "VIX"),
    "DS016": ("DGS10", "DGS10"),
    "DS017": ("DGS2", "DGS2"),
    "DS018": ("DGS3MO", "DGS3MO"),
    "DS019": ("T10Y2Y", "T10Y2Y"),
    "DS020": ("T10Y3M", "T10Y3M"),
    "DS021": ("DFF", "DFF"),
    "DS022": ("BAA10YM", "BAA10Y"),
    "DS023": ("BAMLC0A0CM", "IG_OAS"),
    "DS024": ("BAMLH0A0HYM2", "HY_OAS"),
    "DS025": ("NFCI", "NFCI"),
    "DS026": ("ANFCI", "ANFCI"),
    "DS027": ("STLFSI4", "STLFSI"),
    "DS028": ("OFRFSI", "OFR_FSI"),
    "DS033": ("CPIAUCSL", "CPI"),
    "DS034": ("PCEPI", "PCE"),
    "DS038": ("WALCL", "WALCL"),
    "DS039": ("M2SL", "M2"),
    "DS040": ("T10YIE", "T10YIE"),
    "DS045": ("USEPUINDXD", "EPU"),
    "DS050": ("DTWEXBGS", "USD"),
    "DS051": ("DCOILWTICO", "WTI"),
    "DS052": ("GOLDAMGBD228NLBM", "GOLD"),
}


def _align_causal(
    series: pd.Series, sessions: pd.DatetimeIndex, *, lag_sessions: int = 1
) -> pd.Series:
    values = series.copy().sort_index(kind="mergesort")
    values.index = pd.DatetimeIndex(values.index).normalize()
    aligned = values.reindex(sessions, method="ffill")
    if lag_sessions:
        aligned = aligned.shift(lag_sessions)
    return aligned


def _align_initial_releases(
    releases: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    *,
    first_dissemination: pd.Timestamp | None = None,
) -> pd.Series:
    if releases.empty:
        return pd.Series(np.nan, index=sessions, dtype=float)
    values = releases.set_index("release_date")["value"].sort_index(kind="mergesort")
    aligned = values.reindex(sessions, method="ffill").shift(1)
    if first_dissemination is not None:
        aligned.loc[aligned.index < first_dissemination] = np.nan
    return aligned


def _reconcile_spy_sources(
    yahoo_prices: pd.DataFrame,
    stooq: pd.DataFrame,
    distributions: pd.DataFrame,
    splits: pd.DataFrame,
    *,
    minimum_overlap: int = 1000,
) -> Mapping[str, Any]:
    yahoo_prices = yahoo_prices.set_index("date").sort_index(kind="mergesort")
    comparison = stooq.set_index("date").sort_index(kind="mergesort")
    common = yahoo_prices.index.intersection(comparison.index)
    if len(common) < minimum_overlap:
        raise DataGateError("SPY_RECONCILIATION_TOO_SHORT")
    yahoo = yahoo_prices.loc[common, "close"].pct_change()
    stooq_returns = comparison.loc[common, "close"].pct_change()
    valid = yahoo.notna() & stooq_returns.notna()
    yahoo = yahoo.loc[valid]
    stooq_returns = stooq_returns.loc[valid]
    differences = (yahoo - stooq_returns).abs()
    within = differences <= SPY_RETURN_TOLERANCE
    within_fraction = float(within.mean()) if len(within) else 0.0
    event_dates = set(pd.to_datetime(distributions.get("date", pd.Series(dtype="datetime64[ns]"))))
    event_dates.update(pd.to_datetime(splits.get("date", pd.Series(dtype="datetime64[ns]"))))
    outlier_dates = differences.index[~within]
    unreconciled = [date for date in outlier_dates if date not in event_dates]
    correlation = float(yahoo.corr(stooq_returns))
    median_abs_difference = float((yahoo - stooq_returns).abs().median())
    if within_fraction < SPY_REQUIRED_TOLERANCE_FRACTION:
        raise DataGateError("SPY_RECONCILIATION_99_5_PERCENT_GATE_FAILED")
    if unreconciled:
        raise DataGateError(f"SPY_UNRECONCILED_RETURN_OUTLIERS:{len(unreconciled)}")
    if correlation < 0.999:
        raise DataGateError("SPY_RECONCILIATION_FAILED")
    return {
        "overlap_rows": len(common),
        "daily_return_correlation": correlation,
        "median_abs_return_difference": median_abs_difference,
        "within_5_bps_fraction": within_fraction,
        "outlier_count": int(len(outlier_dates)),
        "unreconciled_outlier_count": 0,
        "return_tolerance": SPY_RETURN_TOLERANCE,
        "required_tolerance_fraction": SPY_REQUIRED_TOLERANCE_FRACTION,
    }


def prepare_market_snapshot(
    root: Path,
    package: CampaignPackage,
    *,
    start: str,
    end: str,
    split: str,
) -> Mapping[str, Any]:
    """Acquire one immutable bounded snapshot on GitHub Actions."""

    require_github_only_execution("SP500_LONG_SHORT_DAILY_PREPARE")
    start_date, end_date = _bounded_dates(start, end, split=split)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    raw_root = root / "raw"
    raw_root.mkdir(exist_ok=True)
    client = requests.Session()
    print(f"[sp500-data] yahoo start={start_date.date()} end={end_date.date()}", flush=True)
    prices, yahoo_dividends, splits, yahoo_receipts = download_yahoo_history(
        "SPY",
        start_date,
        end_date,
        split=split,
        session=client,
        raw_dir=raw_root,
    )
    if not splits.empty:
        raise DataGateError("SPY_SPLIT_REQUIRES_EXPLICIT_RAW_PRICE_REPAIR")
    print(f"[sp500-data] yahoo complete rows={len(prices)}", flush=True)
    if split == "train":
        exact_path = Path(
            os.environ.get("SP500_STATE_STREET_DISTRIBUTIONS_CSV", "").strip()
            or _repo_campaign_root()
            / "official_inputs"
            / "state_street_spy_distribution_events_2006_2010.csv"
        )
        totals_path = Path(
            os.environ.get("SP500_SEC_DISTRIBUTION_TOTALS_CSV", "").strip()
            or _repo_campaign_root()
            / "official_inputs"
            / "sec_spy_distribution_fiscal_totals_1993_2009.csv"
        )
        exact_events, sponsor_receipt = load_state_street_distributions(
            exact_path, start_date, end_date, split=split
        )
        fiscal_totals, totals_receipt = load_sec_distribution_totals(
            totals_path, start_date, end_date, split=split
        )
        sponsor_reconciliation = reconcile_official_distribution_audit(
            exact_events, fiscal_totals, yahoo_dividends
        )
        print("[sp500-data] official distribution audit complete", flush=True)
        dividends = yahoo_dividends.copy()
        _store_raw(raw_root, exact_path.name, exact_path.read_bytes())
        _store_raw(raw_root, totals_path.name, totals_path.read_bytes())
        distribution_receipts = [sponsor_receipt, totals_receipt]
    else:
        sponsor_path = Path(
            os.environ.get("SP500_STATE_STREET_DISTRIBUTIONS_CSV", "").strip()
            or _repo_campaign_root()
            / "official_inputs"
            / "state_street_spy_distributions_2011_2020.csv"
        )
        dividends, sponsor_receipt = load_state_street_distributions(
            sponsor_path, start_date, end_date, split=split
        )
        sponsor_reconciliation = reconcile_sponsor_distributions(dividends, yahoo_dividends)
        _store_raw(
            raw_root,
            f"state_street_spy_distributions_{split}.csv",
            sponsor_path.read_bytes(),
        )
        distribution_receipts = [sponsor_receipt]
    ledger, audit = build_total_return_ledger(prices, dividends, splits)
    print("[sp500-data] stooq history start", flush=True)
    stooq, stooq_receipt = download_stooq_history(
        "spy.us",
        start_date,
        end_date,
        split=split,
        session=client,
        raw_dir=raw_root,
    )
    print(f"[sp500-data] stooq history complete rows={len(stooq)}", flush=True)
    reconciliation = _reconcile_spy_sources(
        prices,
        stooq,
        dividends,
        splits,
        minimum_overlap=min(1000, max(200, len(ledger) - 1)),
    )

    receipts: list[DownloadReceipt] = [
        *yahoo_receipts,
        *distribution_receipts,
        stooq_receipt,
    ]
    series: dict[str, pd.Series] = {}
    available = {"DS001", "DS002"}
    rejected: dict[str, str] = {}
    required = set(package.required_dataset_ids())
    static_rejections = {
        "DS009": "FIRST_DISSEMINATION_AFTER_TRAIN_END:VIX3M_2013_09_30",
        "DS011": "NO_BOUNDED_CAUSAL_VIX_FUTURES_ADAPTER",
        "DS071": "PROXY_ONLY_NOT_EXECUTION_GRADE",
    }
    for dataset_id, reason in static_rejections.items():
        if dataset_id in required:
            rejected[dataset_id] = reason
    for dataset_id, (fred_id, logical_name) in FRED_DATASETS.items():
        if dataset_id not in required:
            continue
        try:
            print(f"[sp500-data] alfred {dataset_id} start", flush=True)
            downloaded, receipt = download_alfred_initial_series(
                fred_id,
                dataset_id,
                start_date,
                end_date,
                split=split,
                session=client,
                raw_dir=raw_root,
            )
            first_dissemination = pd.Timestamp("2003-09-22") if dataset_id == "DS004" else None
            aligned = _align_initial_releases(
                downloaded,
                ledger.index,
                first_dissemination=first_dissemination,
            )
            if not aligned.notna().any():
                raise DataGateError(f"NO_CAUSAL_VALUES_IN_PHASE:{dataset_id}")
            series[logical_name] = aligned
            receipts.append(receipt)
            available.add(dataset_id)
            print(f"[sp500-data] alfred {dataset_id} complete", flush=True)
        except DataGateError as exc:
            rejected[dataset_id] = str(exc)
            print(f"[sp500-data] alfred {dataset_id} rejected={exc}", flush=True)

    for dataset_id in sorted(required - available - set(rejected)):
        rejected[dataset_id] = "NO_BOUNDED_CAUSAL_ADAPTER"

    prices_path = root / "spy_ledger.parquet"
    pq.write_table(
        pa.Table.from_pandas(ledger.reset_index(names="date"), preserve_index=False), prices_path
    )
    series_rows = []
    for name, values in sorted(series.items()):
        for date, value in values.items():
            series_rows.append({"date": date, "series": name, "value": value})
    series_path = root / "causal_series.parquet"
    pq.write_table(pa.Table.from_pylist(series_rows), series_path)
    receipt_payload = [receipt.__dict__ for receipt in receipts]
    (root / "raw_manifest.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in receipt_payload
        ),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1",
        "split": split,
        "minimum_date": ledger.index.min().date().isoformat(),
        "maximum_date": ledger.index.max().date().isoformat(),
        "locked_opened": False,
        "available_dataset_ids": sorted(available),
        "rejected_datasets": dict(sorted(rejected.items())),
        "receipts": receipt_payload,
        "ledger_audit": audit.__dict__,
        "spy_reconciliation": reconciliation,
        "sponsor_distribution_reconciliation": sponsor_reconciliation,
        "candidate_pack_sha256": canonical_json_hash(list(package.candidates)),
    }
    manifest["snapshot_sha256"] = canonical_json_hash(manifest)
    (root / "market_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def load_market_snapshot(root: Path) -> PreparedMarketData:
    root = Path(root).resolve()
    manifest = json.loads((root / "market_data_manifest.json").read_text("utf-8"))
    if manifest.get("locked_opened") is not False:
        raise LockedBoundaryError("TECHNICAL_FAILURE_LOCKED_BREACH:snapshot_manifest")
    ledger = pq.read_table(root / "spy_ledger.parquet").to_pandas()
    ledger["date"] = pd.to_datetime(ledger["date"])
    ledger = ledger.set_index("date").sort_index(kind="mergesort")
    assert_frame_before_locked(ledger, label="loaded_spy_ledger")
    series_table = pq.read_table(root / "causal_series.parquet").to_pandas()
    series: dict[str, pd.Series] = {}
    if len(series_table):
        series_table["date"] = pd.to_datetime(series_table["date"])
        assert_frame_before_locked(series_table, label="loaded_causal_series")
        for name, group in series_table.groupby("series", sort=True):
            series[str(name)] = pd.Series(
                group["value"].to_numpy(dtype=float),
                index=pd.DatetimeIndex(group["date"]),
                name=str(name),
            ).sort_index(kind="mergesort")
    return PreparedMarketData(
        ledger=ledger,
        series=series,
        available_dataset_ids=frozenset(manifest["available_dataset_ids"]),
        rejected_datasets=manifest["rejected_datasets"],
        receipts=tuple(DownloadReceipt(**row) for row in manifest["receipts"]),
        split=str(manifest["split"]),
    )


def write_fixture_snapshot(
    root: Path,
    ledger: pd.DataFrame,
    *,
    split: str = "train",
    series: Mapping[str, pd.Series] | None = None,
    available_dataset_ids: Iterable[str] = ("DS001", "DS002"),
) -> None:
    """Write a deterministic test fixture without invoking acquisition."""

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    assert_frame_before_locked(ledger, label="fixture_ledger")
    pq.write_table(
        pa.Table.from_pandas(ledger.reset_index(names="date"), preserve_index=False),
        root / "spy_ledger.parquet",
    )
    rows = []
    for name, values in sorted((series or {}).items()):
        for date, value in values.items():
            rows.append({"date": date, "series": name, "value": float(value)})
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    pa.field("date", pa.timestamp("ns")),
                    pa.field("series", pa.string()),
                    pa.field("value", pa.float64()),
                ]
            ),
        ),
        root / "causal_series.parquet",
    )
    manifest = {
        "schema_version": "1",
        "split": split,
        "minimum_date": ledger.index.min().date().isoformat(),
        "maximum_date": ledger.index.max().date().isoformat(),
        "locked_opened": False,
        "available_dataset_ids": sorted(set(available_dataset_ids)),
        "rejected_datasets": {},
        "receipts": [],
        "snapshot_sha256": canonical_json_hash({"fixture": True, "rows": len(ledger)}),
    }
    (root / "market_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "raw_manifest.jsonl").write_text("", encoding="utf-8")

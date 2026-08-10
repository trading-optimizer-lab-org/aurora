"""Fail-closed Twelve Data EOD acquisition for the frozen OpenAP market routes.

This module acquires inputs only.  It does not calculate or promote any signal.
The Basic-plan credential is sent exclusively in the HTTP Authorization header,
and every persisted request URL is safe to publish because it never contains the
credential.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

from .implementation_status import TWELVE_DATA_MARKET_SIGNALS
from .sec_listing_identity import normalize_exchange_family


API_ROOT = "https://api.twelvedata.com"
TIME_SERIES_ENDPOINT = f"{API_ROOT}/time_series"
API_KEY_ENV = "TWELVE_DATA_API_KEY"
SEC_TICKER_EXCHANGE_URL = (
    "https://www.sec.gov/files/company_tickers_exchange.json"
)
ADJUSTMENT_MODES = ("all", "none")
MAX_CREDITS_PER_MINUTE = 8
MAX_CREDITS_PER_DAY = 800
MINIMUM_HISTORY_MONTHS = 182
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
SOURCE_TERMS_URL = "https://twelvedata.com/terms"
SOURCE_PRICING_URL = "https://twelvedata.com/pricing"
SOURCE_US_EQUITIES_URL = (
    "https://support.twelvedata.com/en/articles/9935903-us-equities-market-data"
)
SOURCE_HISTORICAL_URL = (
    "https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices"
)
SOURCE_ADJUSTMENTS_URL = (
    "https://support.twelvedata.com/en/articles/5179064-are-the-prices-adjusted"
)
SOURCE_QUICKSTART_URL = "https://twelvedata.com/docs/introduction/quickstart"

_REQUIRED_MASTER_COLUMNS = {
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
_ACCEPTED_UNIVERSE_COLUMNS = (
    "security_id",
    "ticker",
    "provider_symbol",
    "cik",
    "exchange_sec",
    "exchange_query",
    "exchange_family",
    "issuer_share_class_count",
    "identity_available_at",
    "identity_source_url",
)
_REJECTED_UNIVERSE_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "exchange_sec",
    "reason_if_rejected",
)
_US_EASTERN = ZoneInfo("America/New_York")


class TwelveDataError(RuntimeError):
    """Base error for the bounded Twelve Data acquisition surface."""


class TwelveDataIdentityError(TwelveDataError):
    """The provider response does not corroborate the requested security."""


class TwelveDataSourceError(TwelveDataError):
    """The provider returned an invalid, unavailable, or rate-limited response."""

    def __init__(self, message: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.retryable = bool(retryable)


@dataclass(frozen=True)
class TwelveDataResponse:
    """One validated time-series response and its non-secret provenance."""

    bars: pd.DataFrame
    meta: Mapping[str, Any]
    raw_sha256: str
    safe_url: str
    retrieved_at: str


HttpGet = Callable[
    [str, Mapping[str, str], float],
    tuple[int, Mapping[str, str], bytes],
]


def _utc_timestamp(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    try:
        timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(timestamp):
        return pd.NaT
    return pd.Timestamp(timestamp)


def _exchange_query(family: str) -> str:
    return {
        "NASDAQ": "NASDAQ",
        "NYSE": "NYSE",
        "NYSE_AMERICAN": "NYSE AMERICAN",
        "NYSE_ARCA": "NYSE ARCA",
        "CBOE_BZX": "CBOE BZX",
    }.get(family, "")


def _provider_symbol(ticker: str) -> str:
    return ticker.replace("-", ".")


def prepare_twelve_data_universe(
    security_master: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep one primary ranked CIK/ticker/exchange identity and reject ambiguity."""

    missing = _REQUIRED_MASTER_COLUMNS.difference(security_master.columns)
    if missing:
        raise ValueError(f"security master is missing columns: {sorted(missing)}")
    frame = security_master.copy()
    frame["security_id"] = frame["security_id"].fillna("").astype(str).str.strip()
    frame["ticker"] = frame["symbol"].fillna("").astype(str).str.strip().str.upper()
    frame["cik_number"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["exchange_sec"] = (
        frame["exchange_sec"].fillna("").astype(str).str.strip()
    )
    frame["exchange_family"] = frame["exchange_sec"].map(
        normalize_exchange_family
    )
    frame["exchange_query"] = frame["exchange_family"].map(_exchange_query)
    frame["provider_symbol"] = frame["ticker"].map(_provider_symbol)
    frame["issuer_share_class_count"] = pd.to_numeric(
        frame["issuer_share_class_count"], errors="coerce"
    )
    identity_available = pd.to_datetime(
        frame["retrieved_at_sec"], errors="coerce", utc=True
    )
    frame["identity_available_at"] = identity_available.map(
        lambda value: value.isoformat() if pd.notna(value) else ""
    )
    official_identity = frame["source_sec"].fillna("").astype(str).eq(
        "sec_company_tickers_exchange"
    )
    frame["identity_source_url"] = ""
    frame.loc[official_identity, "identity_source_url"] = SEC_TICKER_EXCHANGE_URL
    frame["reason_if_rejected"] = ""

    eligible = (
        frame["eligible_common_stock"].eq(True)  # noqa: E712 - strict contract
        & frame["issuer_primary_security"].eq(True)  # noqa: E712
        & frame["ranking_eligible"].eq(True)  # noqa: E712
    )
    frame.loc[~eligible, "reason_if_rejected"] = "outside_ranked_primary_common_stock"
    missing_identity = (
        frame["security_id"].eq("")
        | frame["ticker"].eq("")
        | frame["cik_number"].isna()
        | ~frame["provider_symbol"].str.fullmatch(r"[A-Z0-9.]+")
    )
    frame.loc[
        frame["reason_if_rejected"].eq("") & missing_identity,
        "reason_if_rejected",
    ] = "missing_or_invalid_current_identity"
    unsupported_exchange = frame["exchange_family"].eq("")
    frame.loc[
        frame["reason_if_rejected"].eq("") & unsupported_exchange,
        "reason_if_rejected",
    ] = "unsupported_or_nonlisted_us_exchange"
    invalid_class_count = (
        frame["issuer_share_class_count"].isna()
        | frame["issuer_share_class_count"].lt(1)
        | frame["issuer_share_class_count"].mod(1).ne(0)
    )
    frame.loc[
        frame["reason_if_rejected"].eq("") & invalid_class_count,
        "reason_if_rejected",
    ] = "invalid_issuer_share_class_count"
    frame.loc[
        frame["reason_if_rejected"].eq("")
        & frame["identity_available_at"].eq(""),
        "reason_if_rejected",
    ] = "missing_current_identity_available_at"
    frame.loc[
        frame["reason_if_rejected"].eq("") & ~official_identity,
        "reason_if_rejected",
    ] = "current_identity_not_from_official_sec_live"

    candidates = frame["reason_if_rejected"].eq("")
    duplicate_security = frame.loc[candidates, "security_id"].duplicated(keep=False)
    duplicate_security_ids = set(
        frame.loc[candidates].loc[duplicate_security, "security_id"]
    )
    frame.loc[
        frame["reason_if_rejected"].eq("")
        & frame["security_id"].isin(duplicate_security_ids),
        "reason_if_rejected",
    ] = "duplicate_security_id"

    candidates = frame["reason_if_rejected"].eq("")
    duplicate_tickers = set(
        frame.loc[candidates & frame["ticker"].duplicated(keep=False), "ticker"]
    )
    frame.loc[
        frame["reason_if_rejected"].eq("")
        & frame["ticker"].isin(duplicate_tickers),
        "reason_if_rejected",
    ] = "duplicate_current_ticker"

    candidates = frame["reason_if_rejected"].eq("")
    duplicate_ciks = set(
        frame.loc[
            candidates & frame["cik_number"].duplicated(keep=False), "cik_number"
        ]
    )
    frame.loc[
        frame["reason_if_rejected"].eq("")
        & frame["cik_number"].isin(duplicate_ciks),
        "reason_if_rejected",
    ] = "duplicate_primary_cik"

    frame["cik"] = frame["cik_number"].map(
        lambda value: f"{int(value):010d}" if pd.notna(value) else ""
    )
    frame["issuer_share_class_count"] = frame[
        "issuer_share_class_count"
    ].astype("Int64")
    expected_security_id = (
        "US-SEC-" + frame["cik"] + "-" + frame["ticker"]
    )
    frame.loc[
        frame["reason_if_rejected"].eq("")
        & frame["security_id"].ne(expected_security_id),
        "reason_if_rejected",
    ] = "security_id_cik_ticker_mismatch"

    accepted = frame.loc[frame["reason_if_rejected"].eq("")].copy()
    accepted = accepted[list(_ACCEPTED_UNIVERSE_COLUMNS)].sort_values(
        "security_id"
    ).reset_index(drop=True)
    rejected = frame.loc[frame["reason_if_rejected"].ne("")].copy()
    rejected = rejected[list(_REJECTED_UNIVERSE_COLUMNS)].sort_values(
        ["reason_if_rejected", "security_id"]
    ).reset_index(drop=True)
    return accepted, rejected


def build_twelve_data_request_plan(
    universe: pd.DataFrame,
    *,
    formation_at: str | datetime | pd.Timestamp,
) -> pd.DataFrame:
    """Build two one-credit, secret-free requests per accepted security."""

    required = set(_ACCEPTED_UNIVERSE_COLUMNS)
    missing = required.difference(universe.columns)
    if missing:
        raise ValueError(f"accepted universe is missing columns: {sorted(missing)}")
    formation = _utc_timestamp(formation_at)
    if pd.isna(formation):
        raise ValueError("formation_at is not a valid timestamp")
    start = formation - pd.DateOffset(months=MINIMUM_HISTORY_MONTHS)
    start_date = start.date().isoformat()
    end_date = formation.date().isoformat()
    rows: list[dict[str, Any]] = []
    for security in universe.sort_values("security_id").itertuples(index=False):
        identity_available_at = _utc_timestamp(security.identity_available_at)
        if pd.isna(identity_available_at):
            raise ValueError(
                "accepted universe contains an invalid current SEC identity timestamp"
            )
        if identity_available_at > formation:
            raise ValueError(
                "accepted universe contains current SEC identity after formation"
            )
        if str(security.identity_source_url) != SEC_TICKER_EXCHANGE_URL:
            raise ValueError(
                "accepted universe contains a non-official SEC identity source"
            )
        for adjust in ADJUSTMENT_MODES:
            params = {
                "symbol": str(security.provider_symbol),
                "interval": "1day",
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
                "order": "asc",
                "format": "JSON",
                "timezone": "Exchange",
                "country": "United States",
                "type": "Common Stock",
                "exchange": str(security.exchange_query),
            }
            safe_url = f"{TIME_SERIES_ENDPOINT}?{urlencode(params)}"
            request_basis = "|".join(
                [
                    str(security.security_id),
                    str(security.provider_symbol),
                    str(security.cik),
                    str(security.exchange_family),
                    str(security.issuer_share_class_count),
                    identity_available_at.isoformat(),
                    str(security.identity_source_url),
                    adjust,
                    start_date,
                    end_date,
                    TIME_SERIES_ENDPOINT,
                ]
            )
            rows.append(
                {
                    "request_id": sha256(request_basis.encode("utf-8")).hexdigest(),
                    "security_id": str(security.security_id),
                    "ticker": str(security.ticker),
                    "provider_symbol": str(security.provider_symbol),
                    "cik": str(security.cik),
                    "exchange_sec": str(security.exchange_sec),
                    "exchange_query": str(security.exchange_query),
                    "exchange_family": str(security.exchange_family),
                    "issuer_share_class_count": int(
                        security.issuer_share_class_count
                    ),
                    "identity_available_at": identity_available_at.isoformat(),
                    "identity_source_url": str(security.identity_source_url),
                    "adjust": adjust,
                    "start_date": start_date,
                    "end_date": end_date,
                    "interval": "1day",
                    "endpoint": TIME_SERIES_ENDPOINT,
                    "safe_url": safe_url,
                    "credits": 1,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["security_id", "adjust"]
    ).reset_index(drop=True)


def estimate_twelve_data_quota(plan: pd.DataFrame) -> dict[str, int]:
    """Return a lower bound that excludes retries and credential probes."""

    if "credits" not in plan:
        raise ValueError("request plan lacks credits")
    credits = int(pd.to_numeric(plan["credits"], errors="raise").sum())
    return {
        "requests": int(len(plan)),
        "credits": credits,
        "minimum_quota_days": math.ceil(credits / MAX_CREDITS_PER_DAY),
        "minimum_rate_limited_minutes": math.ceil(
            credits / MAX_CREDITS_PER_MINUTE
        ),
    }


def redact_twelve_data_secret(value: Any, api_key: str | None = None) -> str:
    """Remove explicit and conventional Twelve Data credential forms."""

    text = str(value)
    if api_key:
        text = text.replace(str(api_key), "[REDACTED]")
    text = re.sub(
        r"(?i)(authorization\s*:\s*apikey\s+)[^\s&]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)(apikey=)[^&\s]+", r"\1[REDACTED]", text)
    return text


def _default_http_get(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> tuple[int, Mapping[str, str], bytes]:  # pragma: no cover - network seam
    request = Request(url, headers=dict(headers))
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 official URL
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            return int(response.status), dict(response.headers.items()), payload
    except HTTPError as exc:
        payload = exc.read(MAX_RESPONSE_BYTES + 1)
        return int(exc.code), dict(exc.headers.items()), payload
    except (URLError, TimeoutError, OSError) as exc:
        raise TwelveDataSourceError(
            f"Twelve Data transport failure: {exc.__class__.__name__}",
            status_code=0,
            retryable=True,
        ) from exc


def _parse_json_response(
    payload: bytes,
    *,
    status_code: int,
    api_key: str,
) -> Mapping[str, Any]:
    if len(payload) > MAX_RESPONSE_BYTES:
        raise TwelveDataSourceError(
            "Twelve Data response exceeded the bounded payload size",
            status_code=status_code,
            retryable=False,
        )
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TwelveDataSourceError(
            "Twelve Data response is not valid UTF-8 JSON",
            status_code=status_code,
            retryable=status_code in {401, 403, 429} or status_code >= 500,
        ) from exc
    if not isinstance(decoded, Mapping):
        raise TwelveDataSourceError(
            "Twelve Data response is not a JSON object",
            status_code=status_code,
            retryable=False,
        )
    if status_code != 200 or str(decoded.get("status", "")).lower() == "error":
        message = redact_twelve_data_secret(decoded.get("message", "source error"), api_key)
        raise TwelveDataSourceError(
            f"Twelve Data HTTP {status_code}: {message}",
            status_code=status_code,
            retryable=status_code in {401, 403, 429} or status_code >= 500,
        )
    return decoded


def _validate_response_identity(
    meta: Mapping[str, Any],
    request_row: Mapping[str, Any],
) -> None:
    expected_symbol = str(request_row["provider_symbol"]).strip().upper()
    actual_symbol = str(meta.get("symbol") or "").strip().upper().replace("-", ".")
    interval = str(meta.get("interval") or "").strip().lower()
    currency = str(meta.get("currency") or "").strip().upper()
    instrument_type = str(meta.get("type") or "").strip().upper()
    exchange_timezone = str(meta.get("exchange_timezone") or "").strip()
    exchange_family = normalize_exchange_family(meta.get("exchange"))
    mic_family = normalize_exchange_family(meta.get("mic_code"))
    response_families = {item for item in (exchange_family, mic_family) if item}
    expected_family = str(request_row["exchange_family"])
    if (
        actual_symbol != expected_symbol
        or interval != "1day"
        or currency != "USD"
        or instrument_type != "COMMON STOCK"
        or exchange_timezone != "America/New_York"
        or response_families != {expected_family}
    ):
        raise TwelveDataIdentityError(
            "Twelve Data metadata does not corroborate current "
            "SEC ticker, US exchange, MIC and common-stock identity"
        )


def _validated_bars(
    values: Any,
    *,
    request_row: Mapping[str, Any],
    retrieved_at: pd.Timestamp,
    raw_sha256: str,
    safe_url: str,
) -> pd.DataFrame:
    if not isinstance(values, list) or not values:
        raise TwelveDataSourceError(
            "Twelve Data response contains no daily values",
            status_code=200,
            retryable=False,
        )
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise TwelveDataSourceError(
                "Twelve Data daily value is not an object",
                status_code=200,
                retryable=False,
            )
        date = pd.to_datetime(value.get("datetime"), errors="coerce")
        numbers = {
            field: pd.to_numeric(value.get(field), errors="coerce")
            for field in ("open", "high", "low", "close", "volume")
        }
        if (
            pd.isna(date)
            or any(pd.isna(number) or not math.isfinite(float(number)) for number in numbers.values())
            or min(float(numbers[field]) for field in ("open", "high", "low", "close")) <= 0
            or float(numbers["volume"]) < 0
            or float(numbers["high"]) < max(float(numbers["open"]), float(numbers["close"]))
            or float(numbers["low"]) > min(float(numbers["open"]), float(numbers["close"]))
        ):
            raise TwelveDataSourceError(
                "Twelve Data daily value violates the finite OHLCV contract",
                status_code=200,
                retryable=False,
            )
        rows.append(
            {
                "date": pd.Timestamp(date).date(),
                "open": float(numbers["open"]),
                "high": float(numbers["high"]),
                "low": float(numbers["low"]),
                "close": float(numbers["close"]),
                "volume": float(numbers["volume"]),
            }
        )
    bars = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    if bars["date"].duplicated(keep=False).any():
        raise TwelveDataSourceError(
            "Twelve Data response contains duplicate daily dates",
            status_code=200,
            retryable=False,
        )
    start_date = pd.Timestamp(str(request_row["start_date"])).date()
    end_date = pd.Timestamp(str(request_row["end_date"])).date()
    if bars["date"].min() < start_date or bars["date"].max() > end_date:
        raise TwelveDataSourceError(
            "Twelve Data response falls outside the bounded request dates",
            status_code=200,
            retryable=False,
        )

    available_at: list[str] = []
    available_quality: list[str] = []
    for index, _row in bars.iterrows():
        if index + 1 < len(bars):
            next_session = datetime.combine(
                bars.loc[index + 1, "date"],
                datetime.min.time(),
                tzinfo=_US_EASTERN,
            )
            available_at.append(next_session.astimezone(UTC).isoformat())
            available_quality.append("next_observed_session_midnight_et")
        else:
            available_at.append(retrieved_at.isoformat())
            available_quality.append("retrieval_timestamp_conservative")
    bars.insert(0, "request_id", str(request_row["request_id"]))
    bars.insert(1, "security_id", str(request_row["security_id"]))
    bars.insert(2, "ticker", str(request_row["ticker"]))
    bars.insert(3, "provider_symbol", str(request_row["provider_symbol"]))
    bars.insert(4, "cik", str(request_row["cik"]))
    bars.insert(5, "exchange_sec", str(request_row["exchange_sec"]))
    bars.insert(6, "exchange_family", str(request_row["exchange_family"]))
    bars.insert(
        7,
        "issuer_share_class_count",
        int(request_row["issuer_share_class_count"]),
    )
    bars.insert(
        8,
        "current_identity_available_at",
        str(request_row["identity_available_at"]),
    )
    bars.insert(
        9,
        "current_identity_source_url",
        str(request_row["identity_source_url"]),
    )
    bars.insert(10, "adjust", str(request_row["adjust"]))
    bars["available_at"] = available_at
    bars["available_at_quality"] = available_quality
    bars["retrieved_at"] = retrieved_at.isoformat()
    bars["source_id"] = "twelve_data_basic"
    bars["source_url"] = TIME_SERIES_ENDPOINT
    bars["safe_request_url"] = safe_url
    bars["raw_response_sha256"] = raw_sha256
    bars["identity_quality"] = (
        "current_sec_cik_ticker_exchange_plus_twelve_data_symbol_mic_type"
    )
    bars["historical_ticker_interval_verified"] = False
    bars["strict_score_eligible"] = False
    return bars


class TwelveDataClient:
    """One-request client with an injectable network seam and no implicit retries."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_get: HttpGet | None = None,
        timeout: float = 90.0,
    ) -> None:
        key = str(api_key or os.environ.get(API_KEY_ENV, "")).strip()
        if not key and http_get is None:
            raise RuntimeError(
                f"{API_KEY_ENV} is required for Twelve Data Basic acquisition"
            )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._api_key = key
        self._http_get = http_get or _default_http_get
        self._timeout = float(timeout)

    def fetch(
        self,
        request_row: Mapping[str, Any] | pd.Series,
        *,
        retrieved_at: str | datetime | pd.Timestamp | None = None,
    ) -> TwelveDataResponse:
        """Fetch and validate one planned symbol/adjustment request."""

        row = request_row.to_dict() if isinstance(request_row, pd.Series) else dict(request_row)
        required = {
            "request_id",
            "security_id",
            "ticker",
            "provider_symbol",
            "cik",
            "exchange_sec",
            "exchange_family",
            "issuer_share_class_count",
            "identity_available_at",
            "identity_source_url",
            "adjust",
            "start_date",
            "end_date",
            "safe_url",
        }
        missing = required.difference(row)
        if missing:
            raise ValueError(f"planned request is missing fields: {sorted(missing)}")
        safe_url = str(row["safe_url"])
        if "apikey" in safe_url.lower() or (
            self._api_key and self._api_key in safe_url
        ):
            raise ValueError("planned request URL contains credential material")
        headers = {
            "Accept": "application/json",
            "Authorization": f"apikey {self._api_key}",
            "User-Agent": "Aurora-OpenAP-149-TwelveData/1.0",
        }
        timestamp = _utc_timestamp(retrieved_at or datetime.now(UTC))
        if pd.isna(timestamp):
            raise ValueError("retrieved_at is not a valid timestamp")
        status_code, _response_headers, payload = self._http_get(
            safe_url,
            headers,
            self._timeout,
        )
        decoded = _parse_json_response(
            payload,
            status_code=int(status_code),
            api_key=self._api_key,
        )
        meta = decoded.get("meta")
        if not isinstance(meta, Mapping):
            raise TwelveDataSourceError(
                "Twelve Data response lacks metadata",
                status_code=int(status_code),
                retryable=False,
            )
        _validate_response_identity(meta, row)
        raw_sha256 = sha256(payload).hexdigest()
        bars = _validated_bars(
            decoded.get("values"),
            request_row=row,
            retrieved_at=timestamp,
            raw_sha256=raw_sha256,
            safe_url=safe_url,
        )
        return TwelveDataResponse(
            bars=bars,
            meta=dict(meta),
            raw_sha256=raw_sha256,
            safe_url=safe_url,
            retrieved_at=timestamp.isoformat(),
        )


def completed_request_ids(checkpoint_path: str | Path) -> set[str]:
    """Load successful and terminal per-security checkpoint decisions."""

    path = Path(checkpoint_path)
    if not path.exists():
        return set()
    completed: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid Twelve Data checkpoint JSON at line {line_number}"
            ) from exc
        if not isinstance(event, Mapping):
            raise ValueError(
                f"invalid Twelve Data checkpoint event at line {line_number}"
            )
        request_id = str(event.get("request_id") or "")
        status = str(event.get("status") or "")
        if not re.fullmatch(r"[0-9a-f]{64}|[A-Za-z0-9_-]+", request_id):
            raise ValueError(
                f"invalid Twelve Data checkpoint request id at line {line_number}"
            )
        if status in {"success", "terminal_error"}:
            completed.add(request_id)
    return completed


__all__ = [
    "ADJUSTMENT_MODES",
    "API_KEY_ENV",
    "API_ROOT",
    "MAX_CREDITS_PER_DAY",
    "MAX_CREDITS_PER_MINUTE",
    "MINIMUM_HISTORY_MONTHS",
    "SOURCE_PRICING_URL",
    "SOURCE_ADJUSTMENTS_URL",
    "SOURCE_HISTORICAL_URL",
    "SOURCE_QUICKSTART_URL",
    "SOURCE_TERMS_URL",
    "SOURCE_US_EQUITIES_URL",
    "TIME_SERIES_ENDPOINT",
    "TWELVE_DATA_MARKET_SIGNALS",
    "TwelveDataClient",
    "TwelveDataError",
    "TwelveDataIdentityError",
    "TwelveDataResponse",
    "TwelveDataSourceError",
    "build_twelve_data_request_plan",
    "completed_request_ids",
    "estimate_twelve_data_quota",
    "prepare_twelve_data_universe",
    "redact_twelve_data_secret",
]

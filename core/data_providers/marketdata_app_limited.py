"""MarketData.app limited provider (R156 deferred, OPTIONS_LIMITED).

MarketData.app exposes a free credit-limited tier for delayed equity
quotes and options chains. This provider is a minimal scaffold gated
behind ``AU_ENABLE_MARKETDATA_APP=1`` so it never runs as part of a
default ingestion job.

The provider records each call's credit cost in provenance so operators
can budget against the free 100-credit / day tier. Quotes and options
chains carry an ``is_delayed`` flag because the free tier serves data
with a typical 15-minute delay.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Tuple

from . import ProviderDescriptor, ProviderRole
from ._free_bulk_common import FreeBulkLineage, utcnow_iso
from aurora.data_contracts.lineage import DataLineage

_log = logging.getLogger(__name__)


PROVIDER_NAME = "marketdata_app_limited"
PROVIDER_URL = "https://api.marketdata.app/v1/"
ENABLE_ENV_VAR = "AU_ENABLE_MARKETDATA_APP"
TOKEN_ENV_VAR = "AU_MARKETDATA_APP_TOKEN"

OptionType = Literal["call", "put"]


MARKETDATA_APP_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.OPTIONS_LIMITED,
    licence_terms_url="https://www.marketdata.app/docs/api/",
    rate_limits="100 daily credits free",
    auth_required=True,
    asset_classes=("equity", "options"),
    intervals=("daily", "intraday_15min", "options_chain"),
    adjustment_posture="ADJUSTED",
    reliability="COMMUNITY",
)


def _check_gate() -> None:
    """Refuse to construct unless ``AU_ENABLE_MARKETDATA_APP=1``."""
    if os.environ.get(ENABLE_ENV_VAR, "") != "1":
        raise RuntimeError(
            "MarketData.app provider is gated; set "
            f"{ENABLE_ENV_VAR}=1 to opt in. The free tier is limited to "
            "100 daily credits and is intended for options experiments / "
            "smoke tests, not for mass ingestion."
        )


@dataclass(frozen=True)
class MDOptionsChainEntry:
    """A single options-chain row from MarketData.app."""

    symbol: str
    expiration_iso: str
    strike: float
    option_type: OptionType
    bid: float
    ask: float
    last: float
    volume: int
    open_interest: int
    implied_volatility: float
    delayed_minutes: int


@dataclass(frozen=True)
class MDStockQuote:
    """A single delayed stock quote from MarketData.app."""

    symbol: str
    time_iso: str
    last: float
    bid: float
    ask: float
    volume: int
    delayed_minutes: int


HttpGet = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def _default_http_get(
    url: str, params: Mapping[str, Any]
) -> Mapping[str, Any]:  # pragma: no cover - production path
    raise RuntimeError(
        "MarketDataAppClient requires an injected http_get callable. "
        "The default production HTTP path is not wired in this deferred "
        "scaffold."
    )


class MarketDataAppClient:
    """Minimal MarketData.app client with an injectable HTTP callable.

    Args:
        http_get: callable accepting ``(url, params)`` and returning the
            decoded JSON body. Tests inject a deterministic fixture.
        api_token: API token. Falls back to the env var
            ``AU_MARKETDATA_APP_TOKEN``. Raises if no token is supplied
            and the env var is unset, because authentication is
            mandatory for this provider.
    """

    DEFAULT_DELAY_MINUTES: int = 15
    OPTIONS_CHAIN_CREDIT_COST: int = 1
    STOCK_QUOTE_CREDIT_COST: int = 1

    def __init__(
        self,
        http_get: Optional[HttpGet] = None,
        api_token: Optional[str] = None,
    ) -> None:
        _check_gate()
        token = api_token or os.environ.get(TOKEN_ENV_VAR, "")
        if not token:
            raise RuntimeError(
                "MarketDataAppClient requires an api_token argument or "
                f"the {TOKEN_ENV_VAR} env var to be set."
            )
        self._token = token
        self._http_get = http_get or _default_http_get

    def fetch_options_chain(
        self,
        symbol: str,
        *,
        expiration: Optional[str] = None,
    ) -> Tuple[Tuple[MDOptionsChainEntry, ...], FreeBulkLineage]:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        params: dict[str, Any] = {"symbol": symbol, "token": self._token}
        if expiration is not None:
            params["expiration"] = expiration
        url = f"{PROVIDER_URL}options/chain/{symbol}/"
        body = self._http_get(url, params)
        rows = body.get("options", ())
        entries = tuple(
            MDOptionsChainEntry(
                symbol=str(r.get("symbol", symbol)),
                expiration_iso=str(r["expiration"]),
                strike=float(r["strike"]),
                option_type=_validate_option_type(r["option_type"]),
                bid=float(r["bid"]),
                ask=float(r["ask"]),
                last=float(r.get("last", 0.0)),
                volume=int(r.get("volume", 0)),
                open_interest=int(r.get("open_interest", 0)),
                implied_volatility=float(r.get("implied_volatility", 0.0)),
                delayed_minutes=int(
                    r.get("delayed_minutes", self.DEFAULT_DELAY_MINUTES)
                ),
            )
            for r in rows
        )
        provenance = self._build_provenance(
            symbol=symbol,
            params={k: v for k, v in params.items() if k != "token"},
            row_count=len(entries),
            credit_cost=self.OPTIONS_CHAIN_CREDIT_COST,
            endpoint="options_chain",
        )
        return entries, provenance

    def fetch_stock_quote(
        self, symbol: str
    ) -> Tuple[MDStockQuote, FreeBulkLineage]:
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol must be a non-empty string")
        params: dict[str, Any] = {"symbol": symbol, "token": self._token}
        url = f"{PROVIDER_URL}stocks/quotes/{symbol}/"
        body = self._http_get(url, params)
        quote = MDStockQuote(
            symbol=str(body.get("symbol", symbol)),
            time_iso=str(body["time_iso"]),
            last=float(body["last"]),
            bid=float(body["bid"]),
            ask=float(body["ask"]),
            volume=int(body.get("volume", 0)),
            delayed_minutes=int(
                body.get("delayed_minutes", self.DEFAULT_DELAY_MINUTES)
            ),
        )
        provenance = self._build_provenance(
            symbol=symbol,
            params={k: v for k, v in params.items() if k != "token"},
            row_count=1,
            credit_cost=self.STOCK_QUOTE_CREDIT_COST,
            endpoint="stocks_quote",
        )
        return quote, provenance

    @staticmethod
    def _build_provenance(
        *,
        symbol: str,
        params: Mapping[str, Any],
        row_count: int,
        credit_cost: int,
        endpoint: str,
    ) -> FreeBulkLineage:
        retrieved = utcnow_iso()
        lineage = DataLineage(
            input_dataset_hash=retrieved,
            transformation_chain=(f"marketdata_app_{endpoint}",),
            code_version="aurora-r156",
            contract_version="marketdata_app_v0",
            snapshot_hash="",
            validator_version="0.0",
            decision_outcome="accepted",
            contract_hash="",
        )
        return FreeBulkLineage(
            lineage=lineage,
            provider_name=PROVIDER_NAME,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=retrieved,
            auth_mode="token",
            query_params=dict(params),
            row_count=int(row_count),
            date_range=("", ""),
            symbol_count=1,
            extra={
                "asset_class": "options" if endpoint == "options_chain" else "equity",
                "reliability": "COMMUNITY",
                "adjustment_posture": "ADJUSTED",
                "is_delayed": True,
                "credit_cost": int(credit_cost),
                "endpoint": endpoint,
                "deferred_scaffold": True,
                "warning": (
                    "MarketData.app is a deferred R156 scaffold; only the "
                    "100-credit / day free tier is exercised."
                ),
            },
        )


def _validate_option_type(value: Any) -> OptionType:
    s = str(value).lower()
    if s not in ("call", "put"):
        raise ValueError(f"option_type={value!r} must be 'call' or 'put'")
    return s  # type: ignore[return-value]


def descriptor() -> ProviderDescriptor:
    """Return the static :class:`ProviderDescriptor` for the registry."""
    return MARKETDATA_APP_DESCRIPTOR


__all__ = [
    "ENABLE_ENV_VAR",
    "MARKETDATA_APP_DESCRIPTOR",
    "MDOptionsChainEntry",
    "MDStockQuote",
    "MarketDataAppClient",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "TOKEN_ENV_VAR",
    "descriptor",
]

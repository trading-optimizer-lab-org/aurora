"""Tests for the R156 tiingo_daily provider.

All tests use injected ``http_get`` callables backed by in-memory
fixtures; no test touches the network. Coverage spans descriptor
metadata, the missing-token failure mode, the happy-path EOD parser,
the optional-fallback provenance flag, and split / dividend
preservation.
"""
from __future__ import annotations

from typing import Any, List, Mapping

import pytest

from aurora.core.data_providers import ProviderRole
from aurora.core.data_providers.tiingo_daily import (
    PROVIDER_NAME,
    TIINGO_DESCRIPTOR,
    TOKEN_ENV_VAR,
    TiingoClient,
    TiingoEODBar,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def _eod_payload() -> List[Mapping[str, Any]]:
    """Two-bar EOD fixture matching Tiingo's ``/tiingo/daily/.../prices``."""
    return [
        {
            "date": "2024-01-02T00:00:00.000Z",
            "open": 187.15,
            "high": 188.44,
            "low": 183.89,
            "close": 185.64,
            "adjClose": 185.64,
            "volume": 82488700,
            "divCash": 0.0,
            "splitFactor": 1.0,
        },
        {
            "date": "2024-01-03T00:00:00.000Z",
            "open": 184.22,
            "high": 185.88,
            "low": 183.43,
            "close": 184.25,
            "adjClose": 184.25,
            "volume": 58414500,
            "divCash": 0.24,
            "splitFactor": 2.0,
        },
    ]


def _make_http_get(payload: Any):
    captured: dict[str, Any] = {}

    def http_get(url: str, headers: Mapping[str, str]) -> Any:
        captured["url"] = url
        captured["headers"] = dict(headers)
        return payload

    return http_get, captured


# ---------------------------------------------------------------------------
# 1. Descriptor.
# ---------------------------------------------------------------------------


def test_descriptor_role_and_reliability() -> None:
    assert TIINGO_DESCRIPTOR.name == PROVIDER_NAME
    assert TIINGO_DESCRIPTOR.role is ProviderRole.OPTIONAL_PRICE_FALLBACK
    assert TIINGO_DESCRIPTOR.reliability == "COMMUNITY"
    assert TIINGO_DESCRIPTOR.auth_required is True
    assert "equity" in TIINGO_DESCRIPTOR.asset_classes


def test_adjusted_posture_recorded() -> None:
    assert TIINGO_DESCRIPTOR.adjustment_posture == "ADJUSTED"


# ---------------------------------------------------------------------------
# 2. Missing-token failure mode.
# ---------------------------------------------------------------------------


def test_missing_token_raises_with_operator_message(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        TiingoClient()
    msg = str(excinfo.value)
    assert TOKEN_ENV_VAR in msg
    assert "tiingo" in msg.lower()


# ---------------------------------------------------------------------------
# 3. Happy path with injected http_get.
# ---------------------------------------------------------------------------


def test_with_injected_token_fetches_eod_fixture(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    http_get, captured = _make_http_get(_eod_payload())
    client = TiingoClient(http_get=http_get, api_token="test-token-123")

    bars = client.fetch_daily("AAPL", start="2024-01-02", end="2024-01-03")
    assert len(bars) == 2
    assert all(isinstance(b, TiingoEODBar) for b in bars)
    assert bars[0].date_iso.startswith("2024-01-02")
    assert bars[0].close == pytest.approx(185.64)
    assert bars[1].adj_close == pytest.approx(184.25)

    # Authorization header must reflect the supplied token.
    auth = captured["headers"].get("Authorization", "")
    assert auth == "Token test-token-123"
    assert "tiingo" in captured["url"].lower()
    assert "AAPL" in captured["url"]


def test_with_injected_http_no_token_works(monkeypatch) -> None:
    """When http_get is injected, no token is required (test seam)."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    http_get, _ = _make_http_get(_eod_payload())
    # No api_token, no env var, but http_get is injected -> no raise.
    client = TiingoClient(http_get=http_get)
    bars = client.fetch_daily("AAPL")
    assert len(bars) == 2


# ---------------------------------------------------------------------------
# 4. Provenance carries optional-fallback flag.
# ---------------------------------------------------------------------------


def test_provenance_carries_optional_fallback_flag(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    http_get, _ = _make_http_get(_eod_payload())
    client = TiingoClient(http_get=http_get, api_token="t")
    bars = client.fetch_daily("AAPL")
    prov = bars[0].provenance
    assert prov.provider_name == PROVIDER_NAME
    assert prov.auth_mode == "api_token"
    assert prov.extra.get("is_optional_fallback") is True
    assert prov.extra.get("is_fallback") is True


# ---------------------------------------------------------------------------
# 5. Split + dividend preserved per-bar.
# ---------------------------------------------------------------------------


def test_split_and_dividend_preserved_in_bar(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    http_get, _ = _make_http_get(_eod_payload())
    client = TiingoClient(http_get=http_get, api_token="t")
    bars = client.fetch_daily("AAPL")
    # First bar has no split / dividend.
    assert bars[0].dividend == pytest.approx(0.0)
    assert bars[0].split_factor == pytest.approx(1.0)
    # Second bar has a $0.24 dividend and a 2:1 split.
    assert bars[1].dividend == pytest.approx(0.24)
    assert bars[1].split_factor == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 6. Token discovery via env var.
# ---------------------------------------------------------------------------


def test_token_picked_up_from_env(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "env-token-xyz")
    http_get, captured = _make_http_get(_eod_payload())
    client = TiingoClient(http_get=http_get)
    client.fetch_daily("AAPL")
    auth = captured["headers"].get("Authorization", "")
    assert auth == "Token env-token-xyz"


def test_fetch_daily_rejects_empty_ticker(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    http_get, _ = _make_http_get([])
    client = TiingoClient(http_get=http_get, api_token="t")
    with pytest.raises(ValueError):
        client.fetch_daily("")

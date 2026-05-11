"""Tests for the R155 free-bulk daily-data programme.

All tests use local fixtures + injected client callables; no test
touches the network. Coverage spans the role-aware registry, the new
provider modules (universe / OHLCV / crypto / macro / experimental),
the fallback chain, and the CLI subcommands.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd
import pytest

from aurora.core.data_providers import (
    DataProviderRegistry,
    ProviderDescriptor,
    ProviderRole,
)
from aurora.core.data_providers._free_bulk_common import (
    FreeBulkContractViolation,
    OHLCV_DAILY_V1,
    UNIVERSE_V1,
    assert_against_contract,
    build_lineage,
    normalise_ohlcv_frame,
)
from aurora.core.data_providers.binance_public_data_daily import (
    BinancePublicDataDailyProvider,
    descriptor as binance_descriptor,
)
from aurora.core.data_providers.coingecko_daily import CoinGeckoDailyProvider
from aurora.core.data_providers.fallback_chain import (
    FallbackReport,
    ProviderMismatch,
    coverage_summary,
    execute_fallback_chain,
)
from aurora.core.data_providers.finance_database_universe import (
    FinanceDatabaseUniverseProvider,
)
from aurora.core.data_providers.fred_daily import FREDDailyProvider
from aurora.core.data_providers.nasdaq_trader_universe import (
    NasdaqTraderUniverseProvider,
    _parse_nasdaq_pipe_file,
)
from aurora.core.data_providers.stooq_daily import (
    StooqAuthRequired,
    StooqDailyProvider,
)
from aurora.core.data_providers.yfinance_daily import YFinanceDailyProvider


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _ohlcv_csv_text(n: int = 5) -> str:
    """Build a plausible Stooq CSV with monotonic timestamps."""
    out = ["Date,Open,High,Low,Close,Volume"]
    base = pd.Timestamp("2024-01-01", tz="UTC")
    for i in range(n):
        d = base + pd.Timedelta(days=i)
        o = 100.0 + i
        h = o + 1.0
        low = o - 1.0
        c = o + 0.5
        v = 1000 + i
        out.append(
            f"{d.date().isoformat()},{o:.2f},{h:.2f},{low:.2f},{c:.2f},{v}"
        )
    return "\n".join(out) + "\n"


def _make_ohlcv_df(n: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame(
        {
            "open": np.arange(n) + 100.0,
            "high": np.arange(n) + 101.0,
            "low": np.arange(n) + 99.0,
            "close": np.arange(n) + 100.5,
            "volume": np.arange(n) + 1000,
        },
        index=pd.DatetimeIndex(idx, name="timestamp"),
    )
    return df


# ---------------------------------------------------------------------------
# 1. Provider role registry.
# ---------------------------------------------------------------------------


def test_provider_descriptor_roundtrip():
    d = ProviderDescriptor(
        name="x",
        role=ProviderRole.PRICE_PRIMARY,
        licence_terms_url="http://example.com/terms",
        rate_limits="none",
        auth_required=False,
        asset_classes=("equities",),
        intervals=("1d",),
        adjustment_posture="ADJUSTED",
        reliability="OFFICIAL",
    )
    assert d.role is ProviderRole.PRICE_PRIMARY
    assert d.adjustment_posture == "ADJUSTED"


def test_provider_descriptor_invalid_role_raises():
    with pytest.raises(TypeError):
        ProviderDescriptor(
            name="x",
            role="PRICE_PRIMARY",  # type: ignore[arg-type]
            licence_terms_url="x",
            rate_limits="x",
            auth_required=False,
            asset_classes=(),
            intervals=(),
            adjustment_posture="RAW",
            reliability="OFFICIAL",
        )


def test_registry_role_lookup():
    reg = DataProviderRegistry()
    p = StooqDailyProvider(client=lambda *_: _ohlcv_csv_text())
    reg.register(
        p,
        descriptor=ProviderDescriptor(
            name="stooq",
            role=ProviderRole.PRICE_PRIMARY,
            licence_terms_url="https://stooq.com/conditions/",
            rate_limits="aggressive",
            auth_required=False,
            asset_classes=("equities",),
            intervals=("1d",),
            adjustment_posture="MIXED",
            reliability="OFFICIAL",
        ),
    )
    assert reg.list_by_role(ProviderRole.PRICE_PRIMARY) == ["stooq"]
    assert reg.list_by_role(ProviderRole.MACRO) == []
    rs = reg.role_status()
    assert len(rs) == 1
    assert rs[0]["role"] == "PRICE_PRIMARY"
    assert rs[0]["reliability"] == "OFFICIAL"


# ---------------------------------------------------------------------------
# 2. Stooq -- auth detection.
# ---------------------------------------------------------------------------


def test_stooq_auth_required_html_response():
    def client(symbol, start, end):
        return "<html><body>captcha</body></html>"
    p = StooqDailyProvider(client=client)
    with pytest.raises(StooqAuthRequired) as excinfo:
        p.fetch_daily("aapl.us")
    assert "operator action" in str(excinfo.value).lower()


def test_stooq_auth_required_rate_limit_text():
    def client(symbol, start, end):
        return "Exceeded daily limit; api key required."
    p = StooqDailyProvider(client=client)
    with pytest.raises(StooqAuthRequired):
        p.fetch_daily("aapl.us")


def test_stooq_happy_path_passes_contract():
    def client(symbol, start, end):
        return _ohlcv_csv_text()
    p = StooqDailyProvider(client=client)
    df, lineage = p.fetch_daily("AAPL")
    assert len(df) == 5
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert lineage.provider_name == "stooq"
    assert lineage.lineage.contract_hash == OHLCV_DAILY_V1.contract_hash


# ---------------------------------------------------------------------------
# 3. Nasdaq Trader -- pipe parsing.
# ---------------------------------------------------------------------------


def test_nasdaq_trader_parses_pipe_file():
    text = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
        "SPY|SPDR S&P 500 ETF Trust|P|N|N|100|Y|N\n"
        "ZZ_TEST|Test Issue|Q|Y|N|100|N|N\n"
        "File Creation Time: 2024-01-01\n"
    )
    rows = _parse_nasdaq_pipe_file(text)
    syms = sorted(r["Symbol"] for r in rows)
    assert "AAPL" in syms
    assert "SPY" in syms
    # The trailer must NOT survive parsing.
    assert "File Creation Time" not in syms


def test_nasdaq_trader_universe_normalises():
    pipe = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc.|Q|N|N|100|N|N\n"
        "SPY|SPDR S&P 500|P|N|N|100|Y|N\n"
        "ZZ|Test|Q|Y|N|100|N|N\n"
    )
    other = (
        "ACT Symbol|CQS Symbol|Security Name|Listing Exchange|Test Issue|ETF\n"
        "BRK.B|BRKB|Berkshire Hathaway|N|N|N\n"
    )

    def client(name):
        return pipe if name == "nasdaqlisted.txt" else other

    p = NasdaqTraderUniverseProvider(client=client)
    df, lineage = p.fetch_universe()
    syms = sorted(df["canonical_symbol"].tolist())
    assert "AAPL" in syms
    assert "SPY" in syms
    assert "BRK-B" in syms  # canonical replaces "." with "-"
    # Test issue must be filtered out.
    assert "ZZ" not in syms
    assert lineage.symbol_count == len(syms)


# ---------------------------------------------------------------------------
# 4. yfinance fallback emits unofficial_source.
# ---------------------------------------------------------------------------


def test_yfinance_fallback_emits_unofficial_warning():
    def client(symbol, start, end, kwargs):
        return _make_ohlcv_df()

    p = YFinanceDailyProvider(client=client)
    df, lineage = p.fetch_daily("AAPL")
    extras = dict(lineage.extra)
    assert extras.get("unofficial_source") is True
    assert extras.get("reliability") == "COMMUNITY"
    assert "warning" in extras
    assert "yfinance" in extras["warning"]


# ---------------------------------------------------------------------------
# 5. Binance ZIP parsing.
# ---------------------------------------------------------------------------


def _build_binance_zip_fixture() -> bytes:
    """Build an in-memory Binance kline ZIP archive."""
    # 3 daily klines (Jan 1-3, 2024).
    rows = []
    for i in range(3):
        open_time_ms = int(pd.Timestamp(f"2024-01-{i+1}", tz="UTC").value // 10**6)
        close_time_ms = open_time_ms + 86_400_000 - 1
        rows.append(
            f"{open_time_ms},100.{i},101.{i},99.{i},100.{i+5},10.5,"
            f"{close_time_ms},1050.0,5,5.0,500.0,0"
        )
    csv_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BTCUSDT-1d-2024-01.csv", csv_bytes)
    return buf.getvalue()


def test_binance_zip_recovers_ohlcv():
    zip_bytes = _build_binance_zip_fixture()
    p = BinancePublicDataDailyProvider(client=lambda *_: (zip_bytes, None))
    df, lineage = p.fetch_daily_from_zip("BTCUSDT", zip_bytes)
    assert len(df) == 3
    assert df["close"].iloc[0] > 0
    assert lineage.provider_name == "binance_public_data"
    assert lineage.extra["adjustment_posture"] == "RAW"


def test_binance_descriptor_is_crypto_primary():
    d = binance_descriptor()
    assert d.role is ProviderRole.CRYPTO_PRIMARY
    assert d.reliability == "OFFICIAL"


# ---------------------------------------------------------------------------
# 6. FRED macro library + lineage.
# ---------------------------------------------------------------------------


def test_fred_macro_under_macro_daily_library():
    def client(series_id, kwargs):
        idx = pd.date_range("2024-01-01", periods=5, freq="D")
        return pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx, name=series_id)

    p = FREDDailyProvider(client=client)
    df, lineage = p.fetch_series("DFF")
    assert list(df.columns) == ["timestamp", "value"]
    assert lineage.extra["asset_class"] == "MACRO"
    assert lineage.extra["library"] == "macro_daily"


# ---------------------------------------------------------------------------
# 7. Contract violations -- duplicates + impossible prices.
# ---------------------------------------------------------------------------


def test_duplicate_dates_raise_contract_violation():
    df = _make_ohlcv_df()
    # Inject a duplicate timestamp.
    duped = pd.concat([df.iloc[[0]], df]).reset_index(drop=True)
    duped["timestamp"] = pd.to_datetime(
        ["2024-01-01"] + list(df.index.strftime("%Y-%m-%d")),
        utc=True,
    )
    duped = duped[["timestamp", "open", "high", "low", "close", "volume"]]
    with pytest.raises(FreeBulkContractViolation) as excinfo:
        assert_against_contract(duped, OHLCV_DAILY_V1)
    assert "duplicate" in str(excinfo.value).lower()


def test_impossible_negative_close_raises_contract_violation():
    df = _make_ohlcv_df()
    df = df.reset_index()
    df.loc[2, "close"] = -1.0
    with pytest.raises(FreeBulkContractViolation):
        assert_against_contract(df, OHLCV_DAILY_V1)


def test_impossible_jump_raises_contract_violation():
    df = _make_ohlcv_df(n=4).reset_index()
    df.loc[2, "close"] = 1e9  # massive jump triggers impossible_return_threshold
    with pytest.raises(FreeBulkContractViolation):
        assert_against_contract(df, OHLCV_DAILY_V1)


# ---------------------------------------------------------------------------
# 8. Coverage report -- requested vs found vs usable.
# ---------------------------------------------------------------------------


def test_coverage_report_counts_requested_found_usable():
    requested = ["A", "B", "C"]

    def good():
        df = _make_ohlcv_df().reset_index()[
            ["timestamp", "open", "high", "low", "close", "volume"]
        ]
        from aurora.core.data_providers._free_bulk_common import build_lineage
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name="primary",
            provider_url="http://example.com/",
        )
        return df, lineage

    def empty():
        from aurora.core.data_providers._free_bulk_common import build_lineage
        df = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name="empty",
            provider_url="http://example.com/",
        )
        return df, lineage

    reports = [
        execute_fallback_chain("A", [("primary", good)]),
        execute_fallback_chain("B", [("primary", empty)]),
        execute_fallback_chain("C", [("primary", good)]),
    ]
    summary = coverage_summary(requested, reports)
    assert summary["requested"] == 3
    assert summary["usable"] == 2
    assert summary["missing_count"] == 1
    assert summary["missing"] == ["B"]


# ---------------------------------------------------------------------------
# 9. Provider mismatch on the same symbol.
# ---------------------------------------------------------------------------


def test_provider_mismatch_strict_records_both_candidates():
    df_a = _make_ohlcv_df(n=4).reset_index()
    df_b = df_a.copy()
    df_b["close"] = df_b["close"] + 5.0  # different content -> different hash

    def fetcher_a():
        from aurora.core.data_providers._free_bulk_common import build_lineage
        return df_a, build_lineage(
            df=df_a, contract=OHLCV_DAILY_V1,
            provider_name="A", provider_url="http://example.com/",
        )

    def fetcher_b():
        from aurora.core.data_providers._free_bulk_common import build_lineage
        return df_b, build_lineage(
            df=df_b, contract=OHLCV_DAILY_V1,
            provider_name="B", provider_url="http://example.com/",
        )

    with pytest.raises(ProviderMismatch) as excinfo:
        execute_fallback_chain(
            "AAPL", [("A", fetcher_a), ("B", fetcher_b)],
            strict_compare=True,
        )
    candidates = excinfo.value.candidates
    assert sorted(c["provider_name"] for c in candidates) == ["A", "B"]


def test_fallback_chain_records_substitution_and_warning():
    """Two providers succeed; chain must select first, not merge silently."""
    df_a = _make_ohlcv_df(n=4).reset_index()
    df_b = df_a.copy()

    def fetcher_a():
        from aurora.core.data_providers._free_bulk_common import build_lineage
        return df_a, build_lineage(
            df=df_a, contract=OHLCV_DAILY_V1,
            provider_name="A", provider_url="http://example.com/",
        )

    def fetcher_b():
        from aurora.core.data_providers._free_bulk_common import build_lineage
        return df_b, build_lineage(
            df=df_b, contract=OHLCV_DAILY_V1,
            provider_name="B", provider_url="http://example.com/",
        )

    rep = execute_fallback_chain(
        "AAPL", [("A", fetcher_a), ("B", fetcher_b)], strict_compare=True,
    )
    assert rep.selected_source == "A"
    assert "B" in rep.rejected_sources
    assert any("not merged" in w for w in rep.warnings)


def test_fallback_falls_through_to_secondary_on_auth():
    def primary():
        raise StooqAuthRequired("upstream gated")

    def secondary():
        from aurora.core.data_providers._free_bulk_common import build_lineage
        df = _make_ohlcv_df().reset_index()
        return df, build_lineage(
            df=df, contract=OHLCV_DAILY_V1,
            provider_name="yfinance_daily", provider_url="http://example.com/",
        )

    rep = execute_fallback_chain(
        "AAPL", [("stooq", primary), ("yfinance_daily", secondary)]
    )
    assert rep.selected_source == "yfinance_daily"
    auth_attempt = next(a for a in rep.attempts if a.provider_name == "stooq")
    assert auth_attempt.outcome == "auth_required"


def test_fallback_records_missing_when_all_fail():
    def fail_a():
        raise StooqAuthRequired("auth")

    def fail_b():
        raise RuntimeError("network down")

    rep = execute_fallback_chain(
        "AAPL", [("a", fail_a), ("b", fail_b)]
    )
    assert rep.selected_source is None
    assert rep.missing_symbols == ("AAPL",)
    assert {a.outcome for a in rep.attempts} == {"auth_required", "error"}


# ---------------------------------------------------------------------------
# 10. AKShare opt-in gate.
# ---------------------------------------------------------------------------


def test_akshare_module_refuses_load_without_env_var(monkeypatch):
    monkeypatch.delenv("AU_ENABLE_AKSHARE", raising=False)
    # Force re-import even if it was previously cached.
    sys.modules.pop(
        "aurora.core.data_providers.akshare_experimental_daily", None,
    )
    with pytest.raises(RuntimeError, match="AU_ENABLE_AKSHARE"):
        import aurora.core.data_providers.akshare_experimental_daily  # noqa: F401


def test_akshare_module_loads_with_env_var(monkeypatch):
    monkeypatch.setenv("AU_ENABLE_AKSHARE", "1")
    sys.modules.pop(
        "aurora.core.data_providers.akshare_experimental_daily", None,
    )
    mod = __import__(
        "aurora.core.data_providers.akshare_experimental_daily",
        fromlist=["AKShareExperimentalDailyProvider"],
    )
    provider_cls = mod.AKShareExperimentalDailyProvider
    p = provider_cls(client=lambda _s, _a, _b: pd.DataFrame())
    df, lineage = p.fetch_daily("000001")
    assert lineage.extra["reliability"] == "EXPERIMENTAL"


# ---------------------------------------------------------------------------
# 11. Universe -- finance_database via injected client.
# ---------------------------------------------------------------------------


def test_finance_database_universe_fetches_via_injected_client():
    def client(asset_class):
        return [
            {"symbol": "AAPL", "exchange": "NMS", "currency": "USD"},
            {"symbol": "MSFT", "exchange": "NMS", "currency": "USD"},
        ]

    p = FinanceDatabaseUniverseProvider(client=client)
    df, lineage = p.fetch_universe(asset_class="equities")
    assert sorted(df["canonical_symbol"]) == ["AAPL", "MSFT"]
    assert lineage.symbol_count == 2


# ---------------------------------------------------------------------------
# 12. CoinGecko market_chart -> OHLCV synthesis.
# ---------------------------------------------------------------------------


def test_coingecko_synthesises_ohlcv_from_market_chart():
    def client(coin_id, vs, days):
        base_ms = int(pd.Timestamp("2024-01-01", tz="UTC").value // 10**6)
        return {
            "prices": [
                [base_ms + i * 86_400_000, 1000.0 + i] for i in range(3)
            ],
            "total_volumes": [
                [base_ms + i * 86_400_000, 50.0 + i] for i in range(3)
            ],
        }

    p = CoinGeckoDailyProvider(client=client)
    df, lineage = p.fetch_daily("bitcoin", days=3)
    assert len(df) == 3
    extras = dict(lineage.extra)
    assert extras.get("rate_limit_aware") is True


# ---------------------------------------------------------------------------
# 13. CLI smoke -- provider-status + coverage-report --help.
# ---------------------------------------------------------------------------


def test_cli_provider_status_smoke():
    res = subprocess.run(
        [sys.executable, "-m", "aurora.cli.forge", "data", "provider-status"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "ROLE" in out
    # At least one of the canonical providers should show up.
    assert any(
        token in out
        for token in ("stooq", "fred_macro", "binance_public_data")
    )


def test_cli_coverage_report_help_smoke():
    res = subprocess.run(
        [
            sys.executable, "-m", "aurora.cli.forge", "data",
            "coverage-report", "--help",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0
    assert "--symbols" in res.stdout
    assert "symbols requested" in res.stdout.lower()


def test_cli_universe_fetch_smoke(tmp_path, monkeypatch):
    """Exercise the CLI universe fetch path against a fixture cache."""
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path))
    cache_root = tmp_path / "cache" / "finance_database"
    cache_root.mkdir(parents=True, exist_ok=True)
    fixture = cache_root / "equities.json"
    fixture.write_text(
        json.dumps(
            [{"symbol": "AAPL", "exchange": "NMS", "currency": "USD"}]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "uni.parquet"
    res = subprocess.run(
        [
            sys.executable, "-m", "aurora.cli.forge", "data",
            "universe", "fetch",
            "--source", "finance_database",
            "--asset-class", "equities",
            "--output", str(out),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "AU_DATA_DIR": str(tmp_path)},
    )
    assert res.returncode == 0, res.stderr
    assert out.exists()

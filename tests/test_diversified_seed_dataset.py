"""R158 diversified seed dataset tests.

All tests are unit tests with injected provider clients. None of them
opens a socket. Coverage:

* manifest YAML loads all 10 sections (broad_us_etfs, us_sector_etfs,
  us_large_caps, international_etfs, bonds_rates_etfs, commodities,
  fx, crypto, macro, fundamentals)
* manifest-summary CLI prints per-section counts
* symbol normalisation table (BRK-B / EURUSD / unknown)
* extreme return spike rejection
* calendar gap warning
* bootstrap persists at least one row per section (mocked)
* requested vs persisted summary counts match
* multi-symbol freeze creates the expected snapshots
* fx section uses fx_daily library
* sentinel: no live network in bootstrap
* fundamentals PIT gate filters out future facts
"""
from __future__ import annotations

import io
import json
import socket
import sys
import types
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.cli.forge import main as forge_main
from aurora.core.data_providers.first_dataset import (
    FirstDatasetManifest,
    FirstDatasetSection,
    apply_normalisation,
    bootstrap_first_dataset,
    freeze_many_from_first_dataset,
    load_manifest,
    lookup_normalisation,
    normalise_symbol,
)
from aurora.data_contracts.timeseries_store import TimeSeriesStore


REPO_ROOT = Path(__file__).resolve().parent.parent
DIVERSIFIED_PATH = REPO_ROOT / "config" / "diversified_seed_dataset.yaml"


# ---------------------------------------------------------------------------
# Fixtures + helpers.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path) -> TimeSeriesStore:
    return TimeSeriesStore(root_dir=tmp_path / "ts_store")


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AU_CACHE_DIR", str(tmp_path / "data" / "cache"))
    monkeypatch.setenv(
        "AU_SNAPSHOT_ROOT", str(tmp_path / "data" / "snapshots")
    )
    return tmp_path


def _ohlcv_csv(rows: int = 5, start: str = "2023-01-02", base_price: float = 100.0) -> str:
    out = ["Date,Open,High,Low,Close,Volume"]
    base = pd.Timestamp(start, tz="UTC")
    for i in range(rows):
        d = base + pd.Timedelta(days=i)
        o = base_price + i
        h = o + 1.0
        low = o - 1.0
        c = o + 0.5
        v = 1000 + i
        out.append(
            f"{d.date().isoformat()},{o:.2f},{h:.2f},{low:.2f},{c:.2f},{v}"
        )
    return "\n".join(out) + "\n"


def _ohlcv_csv_with_spike(start: str = "2023-01-02") -> str:
    """OHLCV CSV with one absurd 200% one-day move on day 3 -> reject."""
    out = ["Date,Open,High,Low,Close,Volume"]
    base = pd.Timestamp(start, tz="UTC")
    closes = [100.0, 101.0, 320.0, 321.0]  # day 2 -> day 3 == 220% move
    for i, c in enumerate(closes):
        d = base + pd.Timedelta(days=i)
        # build OHLC consistent with close
        o = c - 0.5
        h = c + 0.5
        low = c - 1.0 if c - 1.0 > 0 else 0.5
        out.append(
            f"{d.date().isoformat()},{o:.2f},{h:.2f},{low:.2f},{c:.2f},1000"
        )
    return "\n".join(out) + "\n"


def _ohlcv_csv_with_calendar_gap(start: str = "2023-01-02") -> str:
    """OHLCV CSV with one large calendar gap (10d) inside a daily series."""
    out = ["Date,Open,High,Low,Close,Volume"]
    base = pd.Timestamp(start, tz="UTC")
    days_offsets = [0, 1, 2, 12, 13]  # 10-day gap between day 2 and day 12
    for i, off in enumerate(days_offsets):
        d = base + pd.Timedelta(days=off)
        o = 100.0 + i
        h = o + 1.0
        low = o - 1.0
        c = o + 0.5
        out.append(
            f"{d.date().isoformat()},{o:.2f},{h:.2f},{low:.2f},{c:.2f},1000"
        )
    return "\n".join(out) + "\n"


def _binance_zip(symbol: str = "BTCUSDT", n_days: int = 3) -> bytes:
    rows = []
    base = pd.Timestamp("2023-01-01", tz="UTC")
    for i in range(n_days):
        open_time_ms = int((base + pd.Timedelta(days=i)).value // 10**6)
        close_time_ms = open_time_ms + 86_400_000 - 1
        rows.append(
            f"{open_time_ms},100.{i},101.{i},99.{i},100.{i+5},10.5,"
            f"{close_time_ms},1050.0,5,5.0,500.0,0"
        )
    csv_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{symbol}-1d-2023-01.csv", csv_bytes)
    return buf.getvalue()


def _yfinance_df(rows: int = 5, start: str = "2023-01-02") -> pd.DataFrame:
    idx = pd.date_range(start, periods=rows, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": np.arange(rows) + 100.0,
            "High": np.arange(rows) + 101.0,
            "Low": np.arange(rows) + 99.0,
            "Close": np.arange(rows) + 100.5,
            "Volume": np.arange(rows) + 1000,
        },
        index=idx,
    )


def _section(
    name: str, **kw
) -> FirstDatasetSection:
    defaults = {
        "symbols": ("SPY",),
        "providers": ("stooq",),
        "library": "prices_daily",
        "allow_fallback": False,
        "trust_level": "research_seed",
        "asset_group": "equity_index",
        "expected_fields": ("open", "high", "low", "close", "volume"),
        "notes": None,
    }
    defaults.update(kw)
    return FirstDatasetSection(name=name, **defaults)


def _manifest(*sections: FirstDatasetSection, name: str = "diversified_seed", frequency: str = "1d") -> FirstDatasetManifest:
    return FirstDatasetManifest(
        name=name,
        start="2023-01-01",
        end="2023-12-31",
        sections=tuple(sections),
        frequency=frequency,
    )


def _install_factory(monkeypatch, module_name: str, attr: str, factory):
    mod = types.ModuleType(module_name)
    setattr(mod, attr, factory)
    monkeypatch.setitem(sys.modules, module_name, mod)


# ---------------------------------------------------------------------------
# 1. Manifest with 10 sections.
# ---------------------------------------------------------------------------


def test_manifest_loads_all_10_sections():
    """The shipped diversified manifest must parse to 10 sections."""
    if not DIVERSIFIED_PATH.exists():  # pragma: no cover
        pytest.skip("config/diversified_seed_dataset.yaml not present")
    manifest = load_manifest(DIVERSIFIED_PATH)
    assert manifest.name == "diversified_seed"
    assert manifest.frequency == "1d"
    section_names = {s.name for s in manifest.sections}
    expected = {
        "broad_us_etfs",
        "us_sector_etfs",
        "us_large_caps",
        "international_etfs",
        "bonds_rates_etfs",
        "commodities",
        "fx",
        "crypto",
        "macro",
        "fundamentals",
    }
    assert section_names == expected
    fx = next(s for s in manifest.sections if s.name == "fx")
    assert fx.library == "fx_daily"
    assert fx.trust_level == "reference_seed"
    assert "EURUSD" in fx.symbols
    fundamentals = next(s for s in manifest.sections if s.name == "fundamentals")
    assert fundamentals.trust_level == "official_pit"
    macro = next(s for s in manifest.sections if s.name == "macro")
    assert macro.trust_level == "context_seed"
    # Expected fields must propagate.
    assert "value" in macro.expected_fields


# ---------------------------------------------------------------------------
# 2. CLI manifest-summary.
# ---------------------------------------------------------------------------


def test_manifest_summary_cli_prints_section_counts(capsys):
    if not DIVERSIFIED_PATH.exists():  # pragma: no cover
        pytest.skip("config/diversified_seed_dataset.yaml not present")
    rc = forge_main([
        "data", "manifest-summary",
        "--manifest", str(DIVERSIFIED_PATH),
    ])
    assert (rc or 0) == 0
    out = capsys.readouterr().out
    assert "diversified_seed" in out
    assert "sections: 10" in out
    assert "broad_us_etfs" in out
    assert "fx" in out
    assert "fundamentals" in out


def test_manifest_summary_cli_json_mode_emits_valid_json(capsys):
    if not DIVERSIFIED_PATH.exists():  # pragma: no cover
        pytest.skip("config/diversified_seed_dataset.yaml not present")
    rc = forge_main([
        "data", "manifest-summary",
        "--manifest", str(DIVERSIFIED_PATH),
        "--output", "json",
    ])
    assert (rc or 0) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["name"] == "diversified_seed"
    assert payload["section_count"] == 10
    assert payload["total_symbols"] >= 100


# ---------------------------------------------------------------------------
# 3. Symbol normalisation.
# ---------------------------------------------------------------------------


def test_symbol_normalisation_brkb_stooq():
    assert normalise_symbol("BRK-B", "stooq") == "BRK-B.US"
    rec = lookup_normalisation("BRK-B", "stooq")
    assert rec is not None
    assert rec.provider_symbol == "BRK-B.US"


def test_symbol_normalisation_eurusd_yfinance():
    assert normalise_symbol("EURUSD", "yfinance_daily") == "EURUSD=X"
    assert normalise_symbol("EURUSD", "stooq") == "EURUSD.FX"
    assert normalise_symbol("EURUSD", "dukascopy_fx_history") == "EUR/USD"


def test_symbol_normalisation_unknown_returns_canonical():
    # No mapping for SPY -> stooq, fallback returns canonical unchanged.
    assert normalise_symbol("SPY", "stooq") == "SPY"
    # Apply also returns a None record in the unknown path.
    sym, rec = apply_normalisation("SPY", "stooq")
    assert sym == "SPY"
    assert rec is None


def test_symbol_normalisation_dxy_yahoo():
    assert normalise_symbol("DXY", "yfinance_daily") == "DX-Y.NYB"
    assert normalise_symbol("DXY", "stooq") == "^DXY"


# ---------------------------------------------------------------------------
# 4. Strict contract gates (extreme returns + calendar gap).
# ---------------------------------------------------------------------------


def test_extreme_return_spike_rejects_persistence(tmp_store):
    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY",),
            providers=("stooq",),
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={"stooq": lambda *_: _ohlcv_csv_with_spike()},
    )
    res = report.section("broad_us_etfs").results[0]
    assert res.persisted is False
    assert res.error is not None
    assert any(
        "extreme return spike" in e.lower() or "return" in e.lower()
        for e in res.contract_errors
    )
    # Nothing in the store either.
    assert tmp_store.list_versions("prices_daily", "SPY") == ()


def test_calendar_gap_warning_recorded(tmp_store):
    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY",),
            providers=("stooq",),
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={
            "stooq": lambda *_: _ohlcv_csv_with_calendar_gap(),
        },
    )
    res = report.section("broad_us_etfs").results[0]
    # Persisted, but warning surfaced via the persistence contract gate.
    versions = tmp_store.list_versions("prices_daily", "SPY")
    assert len(versions) == 1
    records = tmp_store.list_records("prices_daily", "SPY")
    assert len(records) == 1
    metadata_warnings = list(
        (records[0].metadata or {}).get("warnings", [])
    )
    assert any(
        "calendar gap" in w.lower() for w in metadata_warnings
    ), metadata_warnings
    assert res.persisted is True


# ---------------------------------------------------------------------------
# 5. Bootstrap persists at least one symbol per section across 10 sections.
# ---------------------------------------------------------------------------


def test_bootstrap_persists_at_least_one_per_section(
    tmp_store, monkeypatch,
):
    """Mocked providers across all 10 sections, each persists >=1 symbol."""
    # FRED test client returning a small daily series.
    def fred_client(series_id, kwargs):
        idx = pd.date_range("2023-01-02", periods=4, freq="D")
        return pd.Series([1.0, 1.1, 1.2, 1.3], index=idx, name=series_id)

    # SEC EDGAR client (handles ticker map + companyfacts + submissions).
    def sec_get(url, headers):
        if url.endswith("company_tickers.json"):
            payload = {
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
            }
        elif "submissions/CIK" in url:
            payload = {
                "cik": "320193",
                "name": "Apple Inc.",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-23-000106"],
                        "filingDate": ["2023-11-03"],
                        "acceptanceDateTime": ["2023-11-03T18:08:42.000Z"],
                        "form": ["10-K"],
                        "primaryDocument": ["aapl-20230930.htm"],
                        "periodOfReport": ["2023-09-30"],
                        "isXBRL": [1],
                    }
                },
            }
        elif "companyfacts/CIK" in url:
            payload = {
                "cik": 320193,
                "entityName": "Apple Inc.",
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "label": "Revenues",
                            "description": "Net revenues",
                            "units": {
                                "USD": [
                                    {
                                        "start": "2022-09-25",
                                        "end": "2023-09-30",
                                        "val": 383285000000,
                                        "accn": "0000320193-23-000106",
                                        "fy": 2023,
                                        "fp": "FY",
                                        "form": "10-K",
                                        "filed": "2023-11-03",
                                        "accepted": "2023-11-03T18:08:42.000Z",
                                        "frame": "CY2023",
                                    }
                                ]
                            },
                        },
                    }
                },
            }
        else:
            payload = {}
        return json.dumps(payload).encode("utf-8")

    monkeypatch.setenv(
        "AU_SEC_EDGAR_USER_AGENT", "aurora-test ops@example.com",
    )

    # 10 sections with 1 symbol each (representative), driven by mocks.
    sections = (
        _section(
            "broad_us_etfs",
            symbols=("SPY",),
            providers=("stooq",),
            asset_group="equity_index",
        ),
        _section(
            "us_sector_etfs",
            symbols=("XLK",),
            providers=("stooq",),
            asset_group="equity_sector",
        ),
        _section(
            "us_large_caps",
            symbols=("AAPL",),
            providers=("stooq",),
            asset_group="equity_single_name",
        ),
        _section(
            "international_etfs",
            symbols=("EFA",),
            providers=("stooq",),
            asset_group="equity_international",
        ),
        _section(
            "bonds_rates_etfs",
            symbols=("TLT",),
            providers=("stooq",),
            asset_group="rates_fixed_income",
        ),
        _section(
            "commodities",
            symbols=("GLD",),
            providers=("stooq",),
            asset_group="commodity",
        ),
        _section(
            "fx",
            symbols=("EURUSD",),
            providers=("yfinance_daily",),
            library="fx_daily",
            asset_group="fx_spot",
            expected_fields=("open", "high", "low", "close"),
        ),
        _section(
            "crypto",
            symbols=("BTCUSDT",),
            providers=("binance_public_data",),
            library="crypto_daily",
            asset_group="crypto_spot",
        ),
        _section(
            "macro",
            symbols=("DGS10",),
            providers=("fred_macro",),
            library="macro_daily",
            asset_group="macro_indicator",
            expected_fields=("value",),
        ),
        _section(
            "fundamentals",
            symbols=("AAPL",),
            providers=("sec_edgar_companyfacts",),
            library="fundamentals",
            asset_group="company_fundamentals",
            expected_fields=(
                "tag", "value", "period_end_iso", "accepted_iso",
            ),
        ),
    )
    manifest = _manifest(*sections)

    http_clients = {
        "stooq": lambda *_: _ohlcv_csv(),
        "yfinance_daily": lambda *args, **kw: _yfinance_df(),
        "binance_public_data": lambda *args, **kw: (_binance_zip(), None),
        "fred_macro": fred_client,
        "sec_edgar_companyfacts": sec_get,
    }
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients=http_clients,
    )
    for section in report.sections:
        ok = [r for r in section.results if r.persisted]
        assert len(ok) >= 1, (
            f"section {section.name!r} persisted nothing; "
            f"errors: {[r.error for r in section.results]}"
        )


# ---------------------------------------------------------------------------
# 6. requested vs persisted summary.
# ---------------------------------------------------------------------------


def test_requested_vs_persisted_summary_counts_match(tmp_store):
    """Requested 5 symbols, mock persists 3, summary should show 5/3."""
    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY", "QQQ", "DIA", "BAD1", "BAD2"),
            providers=("stooq",),
            allow_fallback=False,
        ),
    )

    def stooq_client(symbol, start, end):
        if symbol in ("BAD1", "BAD2"):
            raise RuntimeError(f"forced fail {symbol}")
        return _ohlcv_csv()

    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={"stooq": stooq_client},
    )
    summary = report.requested_vs_persisted_summary()
    assert summary["requested_count"] == 5
    assert summary["persisted_count"] == 3
    assert summary["failed_count"] == 2
    sec = summary["sections"][0]
    assert sec["name"] == "broad_us_etfs"
    assert sec["requested"] == 5
    assert sec["persisted"] == 3


# ---------------------------------------------------------------------------
# 7. Multi-symbol freeze.
# ---------------------------------------------------------------------------


def test_freeze_multi_symbol_creates_three_snapshots(
    tmp_store, isolated_runtime,
):
    """Freeze SPY (equity) + BTCUSDT (crypto) + DGS10 (macro) -> 3 snapshots."""
    def fred_client(series_id, kwargs):
        idx = pd.date_range("2023-01-02", periods=6, freq="D")
        return pd.Series(
            [4.0, 4.1, 4.2, 4.1, 4.05, 4.1], index=idx, name=series_id,
        )

    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY",),
            providers=("stooq",),
        ),
        _section(
            "crypto",
            symbols=("BTCUSDT",),
            providers=("binance_public_data",),
            library="crypto_daily",
        ),
        _section(
            "macro",
            symbols=("DGS10",),
            providers=("fred_macro",),
            library="macro_daily",
            expected_fields=("value",),
        ),
    )
    bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={
            "stooq": lambda *_: _ohlcv_csv(8),
            "binance_public_data": lambda *args, **kw: (
                _binance_zip(n_days=6), None,
            ),
            "fred_macro": fred_client,
        },
    )
    snaps, errors = freeze_many_from_first_dataset(
        ["SPY", "BTCUSDT", "DGS10"],
        store=tmp_store,
        snapshot_root=isolated_runtime / "data" / "snapshots",
        library_overrides={
            "BTCUSDT": "crypto_daily",
            "DGS10": "macro_daily",
        },
    )
    assert errors == {}
    assert len(snaps) == 3
    symbols = {s.symbol for s in snaps}
    assert symbols == {"SPY", "BTCUSDT", "DGS10"}

    from aurora.core.snapshots import SnapshotStore

    snap_store = SnapshotStore(
        str(isolated_runtime / "data" / "snapshots")
    )
    rows = snap_store.list_snapshots()
    assert len(rows) >= 3


# ---------------------------------------------------------------------------
# 8. fx section uses fx_daily library.
# ---------------------------------------------------------------------------


def test_fx_section_uses_fx_daily_library(tmp_store):
    manifest = _manifest(
        _section(
            "fx",
            symbols=("EURUSD",),
            providers=("yfinance_daily",),
            library="fx_daily",
            expected_fields=("open", "high", "low", "close"),
            asset_group="fx_spot",
            trust_level="reference_seed",
        ),
    )
    captured: list[str] = []

    def yf_client(symbol, start, end, kwargs):
        captured.append(symbol)
        return _yfinance_df()

    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={"yfinance_daily": yf_client},
    )
    res = report.section("fx").results[0]
    assert res.persisted, res.error
    assert res.library == "fx_daily"
    # Symbol normalised before going to yfinance.
    assert captured == ["EURUSD=X"]
    versions = tmp_store.list_versions("fx_daily", "EURUSD")
    assert len(versions) == 1
    # Lineage warnings record the canonical -> normalised mapping.
    assert any(
        "EURUSD" in w and "EURUSD=X" in w for w in res.warnings
    ), res.warnings


# ---------------------------------------------------------------------------
# 9. No live network sentinel.
# ---------------------------------------------------------------------------


def test_no_live_network_in_diversified_bootstrap(monkeypatch, tmp_store):
    """Bootstrapping the diversified seed must not open any sockets."""
    accesses: list[str] = []

    def block_socket(*args, **kwargs):
        accesses.append(repr((args, kwargs)))
        raise RuntimeError("network access not allowed in unit tests")

    monkeypatch.setattr(socket.socket, "connect", block_socket)
    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY", "QQQ"),
            providers=("stooq",),
        ),
        _section(
            "fx",
            symbols=("EURUSD",),
            providers=("yfinance_daily",),
            library="fx_daily",
            expected_fields=("open", "high", "low", "close"),
        ),
    )
    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={
            "stooq": lambda *_: _ohlcv_csv(),
            "yfinance_daily": lambda *args, **kw: _yfinance_df(),
        },
    )
    for section in report.sections:
        for r in section.results:
            assert r.persisted, f"{r.symbol}: {r.error}"
    assert accesses == [], (
        f"orchestrator opened {len(accesses)} sockets: {accesses[:3]}"
    )


# ---------------------------------------------------------------------------
# 10. Fundamentals PIT gate filters out future facts.
# ---------------------------------------------------------------------------


def test_fundamentals_pit_gate_blocks_future_fact(tmp_store, monkeypatch):
    """A fact accepted 2024-06 with decision_date 2024-01 must NOT survive."""
    monkeypatch.setenv(
        "AU_SEC_EDGAR_USER_AGENT", "aurora-test ops@example.com",
    )

    def http_get(url, headers):
        if url.endswith("company_tickers.json"):
            payload = {
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
            }
        elif "submissions/CIK" in url:
            payload = {
                "cik": "320193",
                "name": "Apple Inc.",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0000320193-24-999999"],
                        "filingDate": ["2024-06-15"],
                        "acceptanceDateTime": [
                            "2024-06-15T18:08:42.000Z"
                        ],
                        "form": ["10-Q"],
                        "primaryDocument": ["aapl-20240331.htm"],
                        "periodOfReport": ["2024-03-31"],
                        "isXBRL": [1],
                    }
                },
            }
        elif "companyfacts/CIK" in url:
            payload = {
                "cik": 320193,
                "entityName": "Apple Inc.",
                "facts": {
                    "us-gaap": {
                        "Revenues": {
                            "label": "Revenues",
                            "description": "Net revenues",
                            "units": {
                                "USD": [
                                    {
                                        "start": "2024-01-01",
                                        "end": "2024-03-31",
                                        "val": 90000000000,
                                        "accn": "0000320193-24-999999",
                                        "fy": 2024,
                                        "fp": "Q2",
                                        "form": "10-Q",
                                        "filed": "2024-06-15",
                                        "accepted": "2024-06-15T18:08:42.000Z",
                                        "frame": "CY2024Q1",
                                    }
                                ]
                            },
                        },
                    }
                },
            }
        else:
            payload = {}
        return json.dumps(payload).encode("utf-8")

    manifest = _manifest(
        _section(
            "fundamentals",
            symbols=("AAPL",),
            providers=("sec_edgar_companyfacts",),
            library="fundamentals",
            expected_fields=(
                "tag", "value", "period_end_iso", "accepted_iso",
            ),
            asset_group="company_fundamentals",
            trust_level="official_pit",
        ),
    )
    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={"sec_edgar_companyfacts": http_get},
    )
    res = report.section("fundamentals").results[0]
    assert res.persisted, res.error

    # The persisted frame contains the fact at its true accepted_iso.
    df = tmp_store.read("fundamentals", "AAPL")
    assert (df["accepted_iso"] == "2024-06-15T18:08:42.000Z").all()
    # PIT filter at decision_date=2024-01-01 must produce no rows.
    from aurora.core.data_providers.sec_edgar_companyfacts import (
        XBRLFact, filter_pit_safe,
    )
    facts = [
        XBRLFact(
            cik=int(row["cik"]),
            taxonomy="us-gaap",
            tag=str(row["tag"]),
            unit=str(row["unit"]),
            value=float(row["value"]),
            period_start_iso="",
            period_end_iso=str(row["period_end_iso"]),
            frame="",
            accession_number="",
            filing_date_iso="",
            accepted_iso=str(row["accepted_iso"]),
            form=str(row["form"]),
            source_url="",
        )
        for _, row in df.iterrows()
    ]
    filtered = filter_pit_safe(facts, decision_date="2024-01-01")
    assert filtered == ()


# ---------------------------------------------------------------------------
# 11. CLI requested-vs-persisted on the saved report.
# ---------------------------------------------------------------------------


def test_coverage_report_requested_vs_persisted_cli(
    tmp_store, isolated_runtime, capsys,
):
    """--requested-vs-persisted prints the compact per-section summary."""
    from aurora.core.data_providers.first_dataset import save_report

    manifest = _manifest(
        _section(
            "broad_us_etfs",
            symbols=("SPY", "BAD"),
            providers=("stooq",),
            allow_fallback=False,
        ),
    )

    def stooq_client(symbol, start, end):
        if symbol == "BAD":
            raise RuntimeError("forced fail")
        return _ohlcv_csv()

    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": stooq_client},
    )
    save_report(report)
    rc = forge_main([
        "data", "coverage-report",
        "--dataset", "diversified_seed",
        "--requested-vs-persisted",
    ])
    assert (rc or 0) == 0
    out = capsys.readouterr().out
    assert "requested-vs-persisted summary" in out
    assert "broad_us_etfs" in out
    assert "TOTAL" in out

"""R157 first real ingestion tests.

All tests use fixtures + injected provider clients. No test touches the
network. Coverage:

* manifest YAML round-trips into the FirstDatasetManifest dataclass
* dry_run leaves the timeseries store empty
* equity / crypto / macro / identity / fundamentals each persist a
  deterministic row
* fallback chain switches to a backup provider and records the swap
* contract violation blocks persistence + surfaces the rejection
* coverage-report explains failures in plain language
* freeze produces an approved snapshot
* freeze refuses unvalidated data
* a smoke backtest runs from a snapshot without network access
* a sentinel test asserts the orchestrator opens no sockets at import
  / fixture setup time
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
    bootstrap_first_dataset,
    freeze_from_first_dataset,
    load_manifest,
    save_report,
)
from aurora.data_contracts.timeseries_store import TimeSeriesStore


# ---------------------------------------------------------------------------
# Helpers / fixtures.
# ---------------------------------------------------------------------------


def _ohlcv_csv_text(n: int = 5, start: str = "2023-01-02") -> str:
    """Build a Stooq-shaped CSV with monotonic timestamps."""
    out = ["Date,Open,High,Low,Close,Volume"]
    base = pd.Timestamp(start, tz="UTC")
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


def _yfinance_ohlcv_df(n: int = 5, start: str = "2023-01-02") -> pd.DataFrame:
    """Return a frame mimicking yfinance.download output."""
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "Open": np.arange(n) + 100.0,
            "High": np.arange(n) + 101.0,
            "Low": np.arange(n) + 99.0,
            "Close": np.arange(n) + 100.5,
            "Volume": np.arange(n) + 1000,
        },
        index=idx,
    )


def _binance_zip_fixture(symbol: str = "BTCUSDT", n_days: int = 3) -> bytes:
    """Build an in-memory Binance kline ZIP archive."""
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


def _make_section(
    name: str,
    *,
    symbols=("SPY",),
    providers=("stooq",),
    library="prices_daily",
    allow_fallback=True,
) -> FirstDatasetSection:
    return FirstDatasetSection(
        name=name,
        symbols=tuple(symbols),
        providers=tuple(providers),
        library=library,
        allow_fallback=allow_fallback,
    )


def _make_manifest(*sections: FirstDatasetSection, name: str = "first") -> FirstDatasetManifest:
    return FirstDatasetManifest(
        name=name,
        start="2023-01-01",
        end="2023-12-31",
        sections=tuple(sections),
    )


@pytest.fixture
def tmp_store(tmp_path) -> TimeSeriesStore:
    """A TimeSeriesStore rooted under tmp_path so tests stay isolated."""
    return TimeSeriesStore(root_dir=tmp_path / "ts_store")


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    """Force runtime_paths to point under tmp_path so save_report / freeze
    do not stomp on the user's real cache.
    """
    monkeypatch.setenv("AU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AU_CACHE_DIR", str(tmp_path / "data" / "cache"))
    monkeypatch.setenv("AU_SNAPSHOT_ROOT", str(tmp_path / "data" / "snapshots"))
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Manifest YAML.
# ---------------------------------------------------------------------------


def test_manifest_loads_from_yaml(tmp_path):
    """Round-trip a YAML manifest into FirstDatasetManifest."""
    manifest_text = (
        "name: first\n"
        "start: '2023-01-01'\n"
        "end: '2023-12-31'\n"
        "sections:\n"
        "  equities:\n"
        "    symbols: [SPY, AAPL]\n"
        "    providers: [stooq, yfinance_daily]\n"
        "    library: prices_daily\n"
        "    allow_fallback: true\n"
        "  crypto:\n"
        "    symbols: [BTCUSDT]\n"
        "    providers: [binance_public_data]\n"
        "    library: crypto_daily\n"
        "    allow_fallback: false\n"
    )
    path = tmp_path / "manifest.yaml"
    path.write_text(manifest_text, encoding="utf-8")
    manifest = load_manifest(path)
    assert manifest.name == "first"
    assert manifest.start == "2023-01-01"
    assert manifest.end == "2023-12-31"
    assert len(manifest.sections) == 2
    eq, cr = manifest.sections
    assert eq.name == "equities"
    assert eq.symbols == ("SPY", "AAPL")
    assert eq.providers == ("stooq", "yfinance_daily")
    assert eq.library == "prices_daily"
    assert eq.allow_fallback is True
    assert cr.allow_fallback is False


def test_manifest_round_trips_canonical_yaml():
    """The shipped config/first_dataset.yaml must parse cleanly."""
    repo_root = Path(__file__).resolve().parent.parent
    canonical = repo_root / "config" / "first_dataset.yaml"
    if not canonical.exists():  # pragma: no cover - shipped file
        pytest.skip("config/first_dataset.yaml not present in checkout")
    manifest = load_manifest(canonical)
    assert manifest.name == "first"
    section_names = {s.name for s in manifest.sections}
    assert {"equities", "crypto", "macro", "identity", "fundamentals"}.issubset(
        section_names
    )


# ---------------------------------------------------------------------------
# 2. Dry run -- no persistence.
# ---------------------------------------------------------------------------


def test_dry_run_writes_no_data(tmp_store):
    """Bootstrap with dry_run=True must not write any rows to the store."""
    manifest = _make_manifest(
        _make_section("equities", symbols=("SPY",), providers=("stooq",)),
    )
    http_clients = {"stooq": lambda *_: _ohlcv_csv_text()}
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, dry_run=True, http_clients=http_clients,
    )
    assert report.dry_run is True
    eq = report.section("equities")
    assert eq is not None
    res = eq.results[0]
    # Dry-run ran the fetcher but did not call store.put.
    assert res.error is None
    assert res.rows == 5
    assert res.persisted is False
    assert tmp_store.list_versions("prices_daily", "SPY") == ()


# ---------------------------------------------------------------------------
# 3. Per-section persistence.
# ---------------------------------------------------------------------------


def test_bootstrap_persists_one_etf_series(tmp_store):
    """Mocked Stooq returns 5 rows for SPY; store registers one version."""
    manifest = _make_manifest(
        _make_section("equities", symbols=("SPY",), providers=("stooq",)),
    )
    http_clients = {"stooq": lambda *_: _ohlcv_csv_text()}
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients=http_clients,
    )
    eq = report.section("equities")
    res = eq.results[0]
    assert res.persisted is True
    assert res.selected_provider == "stooq"
    assert res.rows == 5
    versions = tmp_store.list_versions("prices_daily", "SPY")
    assert len(versions) == 1
    df = tmp_store.read("prices_daily", "SPY")
    assert "close" in df.columns
    assert len(df) == 5


def test_bootstrap_uses_fallback_when_primary_fails(tmp_store):
    """Stooq raises StooqAuthRequired -> yfinance fallback wins."""
    def stooq_client(symbol, start, end):
        return "<html>captcha</html>"

    def yfinance_client(symbol, start, end, kwargs):
        return _yfinance_ohlcv_df()

    manifest = _make_manifest(
        _make_section(
            "equities",
            symbols=("SPY",),
            providers=("stooq", "yfinance_daily"),
            allow_fallback=True,
        ),
    )
    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={
            "stooq": stooq_client,
            "yfinance_daily": yfinance_client,
        },
    )
    res = report.section("equities").results[0]
    assert res.persisted is True
    assert res.selected_provider == "yfinance_daily"
    assert res.fallback_used is True
    assert "stooq" in res.rejected_providers
    assert any("StooqAuthRequired" in w for w in res.warnings)


def test_bootstrap_persists_one_crypto_series(tmp_store):
    """Mocked Binance ZIP archive lands one row per day under crypto_daily."""
    zip_bytes = _binance_zip_fixture("BTCUSDT", n_days=3)
    manifest = _make_manifest(
        _make_section(
            "crypto",
            symbols=("BTCUSDT",),
            providers=("binance_public_data",),
            library="crypto_daily",
            allow_fallback=False,
        ),
    )
    http_clients = {
        "binance_public_data": lambda *args, **kw: (zip_bytes, None),
    }
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients=http_clients,
    )
    res = report.section("crypto").results[0]
    assert res.persisted, res.error
    assert res.rows == 3
    df = tmp_store.read("crypto_daily", "BTCUSDT")
    assert len(df) == 3
    assert "close" in df.columns


def test_bootstrap_persists_one_macro_series(tmp_store):
    """Mocked FRED returns DGS10; the store registers under macro_daily."""
    def fred_client(series_id, kwargs):
        idx = pd.date_range("2023-01-02", periods=4, freq="D")
        return pd.Series(
            [3.91, 3.79, 3.74, 3.71], index=idx, name=series_id,
        )

    manifest = _make_manifest(
        _make_section(
            "macro",
            symbols=("DGS10",),
            providers=("fred_macro",),
            library="macro_daily",
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"fred_macro": fred_client},
    )
    res = report.section("macro").results[0]
    assert res.persisted
    df = tmp_store.read("macro_daily", "DGS10")
    assert "value" in df.columns
    assert len(df) == 4


def test_bootstrap_persists_one_identity_mapping(tmp_store):
    """Mocked OpenFIGI returns one mapping; persisted under identity."""
    def http_post(url, payload, headers):
        return [
            {
                "data": [
                    {
                        "figi": "BBG000B9XRY4",
                        "name": "APPLE INC",
                        "ticker": "AAPL",
                        "exchCode": "US",
                        "marketSector": "Equity",
                        "securityType": "Common Stock",
                    }
                ]
            }
        ]

    manifest = _make_manifest(
        _make_section(
            "identity",
            symbols=("AAPL",),
            providers=("openfigi_mapper",),
            library="identity",
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"openfigi_mapper": http_post},
    )
    res = report.section("identity").results[0]
    assert res.persisted, res.error
    df = tmp_store.read("identity", "AAPL")
    assert "figi" in df.columns
    assert df["figi"].iloc[0] == "BBG000B9XRY4"


def test_bootstrap_persists_one_fundamentals_record(tmp_store, monkeypatch):
    """Mocked SEC EDGAR returns one fact bundle; persisted under fundamentals."""
    monkeypatch.setenv("AU_SEC_EDGAR_USER_AGENT", "aurora-test ops@example.com")

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

    manifest = _make_manifest(
        _make_section(
            "fundamentals",
            symbols=("AAPL",),
            providers=("sec_edgar_companyfacts",),
            library="fundamentals",
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest,
        store=tmp_store,
        http_clients={"sec_edgar_companyfacts": http_get},
    )
    res = report.section("fundamentals").results[0]
    assert res.persisted, res.error
    df = tmp_store.read("fundamentals", "AAPL")
    assert "tag" in df.columns
    assert "value" in df.columns
    assert df["tag"].str.contains("Revenues").any()


# ---------------------------------------------------------------------------
# 4. Contract violation -> rejection.
# ---------------------------------------------------------------------------


def test_contract_violation_blocks_persistence(tmp_store):
    """A duplicate-date payload from Stooq must NOT land in the store."""
    csv_bad = (
        "Date,Open,High,Low,Close,Volume\n"
        "2023-01-02,100,101,99,100.5,1000\n"
        "2023-01-02,101,102,100,101.5,1100\n"  # duplicate date
        "2023-01-04,102,103,101,102.5,1200\n"
    )
    manifest = _make_manifest(
        _make_section(
            "equities",
            symbols=("SPY",),
            providers=("stooq",),
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": lambda *_: csv_bad},
    )
    res = report.section("equities").results[0]
    assert res.persisted is False
    assert res.error is not None
    # The contract validator surfaces the duplicate timestamp as one of
    # the errors tuple.
    assert any(
        "duplicate" in e.lower() or "monoton" in e.lower()
        for e in res.contract_errors
    )
    # No version registered in the store.
    assert tmp_store.list_versions("prices_daily", "SPY") == ()


def test_coverage_report_explains_failures_in_plain_language(
    tmp_store, isolated_runtime, capsys,
):
    """coverage-report --dataset first should surface explicit reasons."""
    csv_bad = (
        "Date,Open,High,Low,Close,Volume\n"
        "2023-01-02,100,101,99,100.5,1000\n"
        "2023-01-02,101,102,100,101.5,1100\n"
    )
    manifest = _make_manifest(
        _make_section(
            "equities",
            symbols=("SPY",),
            providers=("stooq",),
            allow_fallback=False,
        ),
    )
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": lambda *_: csv_bad},
    )
    save_report(report)
    rc = forge_main(["data", "coverage-report", "--dataset", "first"])
    assert (rc or 0) == 0
    out = capsys.readouterr().out
    assert "first-dataset coverage report" in out
    assert "SPY" in out
    assert "rejected" in out.lower() or "contract violation" in out.lower()


# ---------------------------------------------------------------------------
# 5. Snapshot freeze + smoke backtest.
# ---------------------------------------------------------------------------


def test_freeze_creates_approved_snapshot(tmp_store, isolated_runtime):
    """A bootstrap + freeze produces at least one snapshot row."""
    manifest = _make_manifest(
        _make_section("equities", symbols=("SPY",), providers=("stooq",)),
    )
    bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": lambda *_: _ohlcv_csv_text(8)},
    )
    snap = freeze_from_first_dataset(
        "SPY",
        library="prices_daily",
        store=tmp_store,
        snapshot_root=isolated_runtime / "data" / "snapshots",
    )
    assert snap.symbol == "SPY"
    assert snap.n_bars == 8
    assert snap.sha256

    from aurora.core.snapshots import SnapshotStore

    snap_store = SnapshotStore(str(isolated_runtime / "data" / "snapshots"))
    rows = snap_store.list_snapshots()
    assert len(rows) >= 1


def test_freeze_refuses_unvalidated_data(tmp_store, isolated_runtime):
    """If the symbol is missing from the store, freeze raises with a hint."""
    with pytest.raises(KeyError):
        freeze_from_first_dataset(
            "DOES_NOT_EXIST",
            library="prices_daily",
            store=tmp_store,
            snapshot_root=isolated_runtime / "data" / "snapshots",
        )


def test_smoke_backtest_runs_from_snapshot(tmp_store, isolated_runtime):
    """Load SPY from snapshot, run a 2-bar moving-average baseline."""
    manifest = _make_manifest(
        _make_section("equities", symbols=("SPY",), providers=("stooq",)),
    )
    bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": lambda *_: _ohlcv_csv_text(10)},
    )
    snap = freeze_from_first_dataset(
        "SPY",
        library="prices_daily",
        store=tmp_store,
        snapshot_root=isolated_runtime / "data" / "snapshots",
    )

    from aurora.core.snapshots import SnapshotStore

    snap_store = SnapshotStore(str(isolated_runtime / "data" / "snapshots"))
    prices, _ = snap_store.load(snap.sha256)
    assert len(prices) == 10
    # Toy 2-bar MA strategy: long when MA crosses up, exit on cross down.
    rets = prices.pct_change().fillna(0.0)
    ma_short = prices.rolling(2, min_periods=1).mean()
    ma_long = prices.rolling(4, min_periods=1).mean()
    signal = (ma_short > ma_long).astype(int).shift(1).fillna(0)
    pnl = float((signal * rets).sum())
    assert np.isfinite(pnl)


# ---------------------------------------------------------------------------
# 6. Sentinel: no live network access.
# ---------------------------------------------------------------------------


def test_no_live_network_in_unit_tests(monkeypatch, tmp_store):
    """Importing + running a fixture bootstrap must NOT touch the network."""
    accesses: list[str] = []

    def block_socket(*args, **kwargs):
        accesses.append(repr((args, kwargs)))
        raise RuntimeError("network access not allowed in unit tests")

    monkeypatch.setattr(socket.socket, "connect", block_socket)
    manifest = _make_manifest(
        _make_section("equities", symbols=("SPY",), providers=("stooq",)),
    )
    report = bootstrap_first_dataset(
        manifest, store=tmp_store, http_clients={"stooq": lambda *_: _ohlcv_csv_text()},
    )
    assert report.section("equities").results[0].persisted
    assert accesses == [], (
        f"orchestrator opened {len(accesses)} sockets in a unit test: "
        f"{accesses[:3]}"
    )


# ---------------------------------------------------------------------------
# 7. CLI smoke -- bootstrap-first-dataset --dry-run.
# ---------------------------------------------------------------------------


def _install_factory(monkeypatch, module_name: str, attr: str, factory):
    mod = types.ModuleType(module_name)
    setattr(mod, attr, factory)
    monkeypatch.setitem(sys.modules, module_name, mod)


def test_cli_bootstrap_first_dataset_dry_run(
    tmp_path, monkeypatch, capsys, isolated_runtime,
):
    """`aurora data bootstrap-first-dataset --dry-run` runs in-process."""
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "name: first\n"
        "start: '2023-01-01'\n"
        "end: '2023-12-31'\n"
        "sections:\n"
        "  equities:\n"
        "    symbols: [SPY]\n"
        "    providers: [stooq]\n"
        "    library: prices_daily\n"
        "    allow_fallback: false\n",
        encoding="utf-8",
    )

    def factory():
        return {"stooq": lambda *_: _ohlcv_csv_text()}

    _install_factory(
        monkeypatch, "_aurora_test_first_dataset_factory", "make", factory,
    )
    monkeypatch.setenv(
        "AU_FIRST_DATASET_HTTP_CLIENTS_FACTORY",
        "_aurora_test_first_dataset_factory:make",
    )

    rc = forge_main([
        "data", "bootstrap-first-dataset",
        "--manifest", str(manifest_path),
        "--dry-run",
        "--output", "json",
    ])
    assert (rc or 0) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["dry_run"] is True
    assert payload["sections"][0]["name"] == "equities"
    # No persisted rows in dry run.
    assert payload["sections"][0]["fetched"] == []


def test_cli_freeze_from_first_dataset(
    tmp_path, monkeypatch, capsys, isolated_runtime,
):
    """`aurora data freeze --dataset first` freezes a stored series."""
    # Pre-populate the timeseries store under the AU_DATA_DIR root.
    from aurora.data_contracts.timeseries_store import (
        _reset_default_store_for_tests,
    )
    _reset_default_store_for_tests()

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "name: first\n"
        "start: '2023-01-01'\n"
        "end: '2023-12-31'\n"
        "sections:\n"
        "  equities:\n"
        "    symbols: [SPY]\n"
        "    providers: [stooq]\n"
        "    library: prices_daily\n"
        "    allow_fallback: false\n",
        encoding="utf-8",
    )

    def factory():
        return {"stooq": lambda *_: _ohlcv_csv_text(7)}

    _install_factory(
        monkeypatch, "_aurora_test_first_dataset_factory_2", "make", factory,
    )
    monkeypatch.setenv(
        "AU_FIRST_DATASET_HTTP_CLIENTS_FACTORY",
        "_aurora_test_first_dataset_factory_2:make",
    )

    rc1 = forge_main([
        "data", "bootstrap-first-dataset",
        "--manifest", str(manifest_path),
    ])
    assert (rc1 or 0) == 0

    rc2 = forge_main([
        "data", "freeze",
        "--dataset", "first",
        "--symbol", "SPY",
        "--library", "prices_daily",
    ])
    assert (rc2 or 0) == 0
    out = capsys.readouterr().out
    assert "frozen snapshot" in out
    assert "SPY" in out

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pandas as pd

from aurora.core.free_us_daily import (
    build_benchmarks,
    build_coverage_report,
    build_metadata_coverage,
    build_quality_report,
    build_us_stock_like_universe,
    build_yahoo_us_stock_universe,
    build_yahoo_foreign_stock_universe,
    download_one_symbol,
    download_prices,
    enrich_company_metadata,
    export_all_prices_parquet,
    export_duckdb,
    filter_universe_by_market_cap,
    load_company_metadata,
    load_universe,
    normalise_symbol_for_yfinance,
    normalise_yfinance_history,
    persist_company_metadata_frame,
    persist_universe,
    prune_universe_to_valid_prices,
    update_daily_prices,
    validate_price_frame,
    write_metadata_coverage,
    write_quality_report,
)


def _nasdaq_fixture(name: str) -> str:
    if name == "nasdaqlisted.txt":
        return (
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
            "Round Lot Size|ETF|NextShares\n"
            "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
            "QQQ|Invesco QQQ Trust ETF|Q|N|N|100|Y|N\n"
            "WXYZW|Example Corp Warrant|Q|N|N|100|N|N\n"
            "WXYZS|Example Corp Warrants|Q|N|N|100|N|N\n"
            "ZZTEST|Test Corp - Common Stock|Q|Y|N|100|N|N\n"
            "File Creation Time: 2026-06-21\n"
        )
    return (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol\n"
        "BRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK.B\n"
        "BF.B|Brown Forman Inc. Class B Common Stock|N|BF.B|N|100|N|BF.B\n"
        "NVO|Novo Nordisk A/S American Depositary Shares|N|NVO|N|100|N|NVO\n"
        "SAP|SAP SE ADS|N|SAP|N|100|N|SAP\n"
        "AACI|Armada Acquisition Corp. III - Class A Ordinary Share|N|AACI|N|100|N|AACI\n"
        "ABR|Arbor Realty Trust Common Stock|N|ABR|N|100|N|ABR\n"
        "ALL$B|Allstate Corporation Depositary Shares|N|ALLpB|N|100|N|ALL-B\n"
        "DPSD|Example Corp Depositary Shares|N|DPSD|N|100|N|DPSD\n"
        "UABC|Example Acquisition Corp. Units|N|UABC|N|100|N|UABC\n"
        "RABC|Example Acquisition Corp. Rights|N|RABC|N|100|N|RABC\n"
        "PREF.P|Example Preferred Stock|N|PREF.P|N|100|N|PREF.P\n"
    )


def _yf_frame(rows: int = 40) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=rows, freq="B")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(rows)],
            "High": [101.0 + i for i in range(rows)],
            "Low": [99.0 + i for i in range(rows)],
            "Close": [100.5 + i for i in range(rows)],
            "Adj Close": [100.4 + i for i in range(rows)],
            "Volume": [1000 + i for i in range(rows)],
            "Dividends": [0.0 for _ in range(rows)],
            "Stock Splits": [0.0 for _ in range(rows)],
        },
        index=pd.DatetimeIndex(idx, name="Date"),
    )


def _metadata_fixture(symbol: str) -> dict:
    payload = {
        "AAPL": {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "exchange": "NMS",
            "quoteType": "EQUITY",
            "marketCap": 3_000_000_000_000,
            "sharesOutstanding": 15_000_000_000,
            "country": "United States",
            "website": "https://www.apple.com",
        },
        "BRK-B": {
            "longName": "Berkshire Hathaway Inc.",
            "sector": "Financial Services",
            "industry": "Insurance - Diversified",
            "exchange": "NYQ",
            "quoteType": "EQUITY",
            "marketCap": 900_000_000_000,
            "sharesOutstanding": 1_300_000_000,
            "country": "United States",
            "website": "https://www.berkshirehathaway.com",
        },
    }
    return payload.get(symbol, {})


def test_stock_like_universe_filters_noise_and_normalises_symbols():
    df = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )

    assert df["canonical_symbol"].tolist() == ["AAPL", "BF-B", "BRK-B"]
    assert df.set_index("canonical_symbol").loc["BRK-B", "yfinance_symbol"] == "BRK-B"
    assert df.set_index("canonical_symbol").loc["AAPL", "asset_type"] == "COMMON_STOCK"
    assert "QQQ" not in set(df["canonical_symbol"])
    assert "NVO" not in set(df["canonical_symbol"])
    assert "SAP" not in set(df["canonical_symbol"])
    assert "AACI" not in set(df["canonical_symbol"])
    assert "ABR" not in set(df["canonical_symbol"])
    assert "WXYZW" not in set(df["canonical_symbol"])
    assert "WXYZS" not in set(df["canonical_symbol"])
    assert "UABC" not in set(df["canonical_symbol"])
    assert "RABC" not in set(df["canonical_symbol"])
    assert "ALL$B" not in set(df["canonical_symbol"])
    assert "DPSD" not in set(df["canonical_symbol"])
    assert "PREF-P" not in set(df["canonical_symbol"])


def test_yahoo_us_stock_universe_applies_cleaning_filters():
    now = pd.Timestamp("2026-06-21T12:00:00Z")

    def screen_client(region, *, size, offset):
        assert region == "us"
        quotes = [
            {
                "symbol": "AAPL",
                "quoteType": "EQUITY",
                "marketCap": 3_000_000_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 200,
                "currency": "USD",
                "averageDailyVolume3Month": 50_000_000,
                "regularMarketTime": now.timestamp(),
                "longName": "Apple Inc. Common Stock",
                "exchange": "NMS",
            },
            {
                "symbol": "PENNY",
                "quoteType": "EQUITY",
                "marketCap": 100_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 0.5,
                "currency": "USD",
                "averageDailyVolume3Month": 1_000_000,
                "regularMarketTime": now.timestamp(),
                "longName": "Penny Corp Common Stock",
            },
            {
                "symbol": "MICRO",
                "quoteType": "EQUITY",
                "marketCap": 10_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 10,
                "currency": "USD",
                "averageDailyVolume3Month": 1_000_000,
                "regularMarketTime": now.timestamp(),
                "longName": "Micro Corp Common Stock",
            },
            {
                "symbol": "ILLIQ",
                "quoteType": "EQUITY",
                "marketCap": 100_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 10,
                "currency": "USD",
                "averageDailyVolume3Month": 1,
                "regularMarketTime": now.timestamp(),
                "longName": "Illiquid Corp Common Stock",
            },
            {
                "symbol": "OLD",
                "quoteType": "EQUITY",
                "marketCap": 100_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 10,
                "currency": "USD",
                "averageDailyVolume3Month": 1_000_000,
                "regularMarketTime": (now - pd.Timedelta(days=30)).timestamp(),
                "longName": "Old Quote Corp Common Stock",
            },
            {
                "symbol": "SPAC",
                "quoteType": "EQUITY",
                "marketCap": 100_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 10,
                "currency": "USD",
                "averageDailyVolume3Month": 1_000_000,
                "regularMarketTime": now.timestamp(),
                "longName": "Example Acquisition Corp. Class A Ordinary Shares",
            },
            {
                "symbol": "ADR",
                "quoteType": "EQUITY",
                "marketCap": 100_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 10,
                "currency": "USD",
                "averageDailyVolume3Month": 1_000_000,
                "regularMarketTime": now.timestamp(),
                "longName": "Example SA American Depositary Shares",
            },
            {
                "symbol": "ETF",
                "quoteType": "ETF",
                "marketCap": 100_000_000,
                "financialCurrency": "USD",
                "regularMarketPrice": 10,
                "currency": "USD",
                "averageDailyVolume3Month": 1_000_000,
                "regularMarketTime": now.timestamp(),
                "longName": "Example ETF",
            },
        ]
        return {"total": len(quotes), "quotes": quotes[offset:offset + size]}

    universe, metadata, report = build_yahoo_us_stock_universe(
        reference_time=now,
        screen_client=screen_client,
        page_size=50,
    )

    assert universe["canonical_symbol"].tolist() == ["AAPL"]
    assert metadata["symbol"].tolist() == ["AAPL"]
    assert report["us_symbols"] == 1
    assert report["rejected"]["not_equity"] == 1
    assert report["rejected"]["market_cap"] == 1
    assert report["rejected"]["price"] == 1
    assert report["rejected"]["liquidity"] == 1
    assert report["rejected"]["stale"] == 1
    assert report["rejected"]["name"] == 2


def test_symbol_normalisation_for_yfinance_special_classes():
    assert normalise_symbol_for_yfinance("BRK.B") == "BRK-B"
    assert normalise_symbol_for_yfinance("bf.b") == "BF-B"
    assert normalise_symbol_for_yfinance("AAPL") == "AAPL"


def test_normalise_yfinance_history_schema():
    out = normalise_yfinance_history(
        _yf_frame(35),
        symbol="AAPL",
        retrieved_at="2026-06-21T00:00:00Z",
    )

    assert list(out.columns) == [
        "date",
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
        "symbol",
    ]
    assert out["symbol"].unique().tolist() == ["AAPL"]
    assert validate_price_frame(out).ok is True


def test_validate_price_frame_rejects_duplicate_and_negative_values():
    good = normalise_yfinance_history(_yf_frame(35), symbol="AAPL")
    duped = pd.concat([good.iloc[[0]], good], ignore_index=True)
    bad_dup = validate_price_frame(duped)
    assert bad_dup.ok is False
    assert any("duplicate" in e for e in bad_dup.errors)

    negative = good.copy()
    negative.loc[2, "close"] = -1.0
    bad_negative = validate_price_frame(negative)
    assert bad_negative.ok is False
    assert any("close contains non-positive" in e for e in bad_negative.errors)


def test_download_one_symbol_persists_catalog_and_reports(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    loaded = load_universe(root=tmp_path)

    result = download_one_symbol(
        loaded.iloc[0],
        root=tmp_path,
        client=lambda *args, **kwargs: _yf_frame(40),
        retry_wait_seconds=0,
    )

    assert result.status == "ok"
    assert result.rows == 40
    assert result.raw_path is not None
    assert result.normalized_path is not None
    report = build_coverage_report(root=tmp_path)
    assert report["universe_symbols"] == 3
    assert report["downloaded_ok"] == 1


def test_download_one_symbol_tolerates_mixed_object_raw_columns(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    loaded = load_universe(root=tmp_path)
    raw = _yf_frame(40)
    raw["Adj Close"] = raw["Adj Close"].astype("object")
    raw.iloc[0, raw.columns.get_loc("Adj Close")] = b"100.4"
    raw.columns = pd.MultiIndex.from_product([raw.columns, ["AAPL"]])

    result = download_one_symbol(
        loaded.iloc[0],
        root=tmp_path,
        client=lambda *args, **kwargs: raw,
        retry_wait_seconds=0,
    )

    assert result.status == "ok"
    assert result.raw_path is not None
    assert result.normalized_path is not None


def test_rebuilding_universe_prunes_out_of_scope_download_catalog(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    loaded = load_universe(root=tmp_path)
    download_one_symbol(
        loaded.iloc[0],
        root=tmp_path,
        client=lambda *args, **kwargs: _yf_frame(40),
        retry_wait_seconds=0,
    )

    reduced = universe[universe["canonical_symbol"] != loaded.iloc[0]["canonical_symbol"]]
    persist_universe(reduced, root=tmp_path)

    catalog = tmp_path / "prices" / "free_us_daily" / "catalog.sqlite"
    with sqlite3.connect(catalog) as con:
        count = con.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    assert count == 0


def test_prune_universe_to_valid_prices_removes_bad_symbols_and_files(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    persist_company_metadata_frame(
        pd.DataFrame(
            {
                "symbol": ["AAPL", "BF-B", "BRK-B"],
                "provider_symbol": ["AAPL", "BF.B", "BRK.B"],
                "yfinance_symbol": ["AAPL", "BF-B", "BRK-B"],
                "company_name": ["Apple", "Brown Forman", "Berkshire"],
                "status": ["ok", "ok", "ok"],
            }
        ),
        root=tmp_path,
    )
    paths = tmp_path / "prices" / "free_us_daily"
    normalized = paths / "normalized"
    raw = paths / "raw" / "yfinance"
    normalized.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    for symbol in ("AAPL", "BF-B", "BRK-B"):
        normalise_yfinance_history(_yf_frame(40), symbol=symbol).to_parquet(
            normalized / f"{symbol}.parquet",
            index=False,
        )
        _yf_frame(40).to_parquet(raw / f"{symbol}.parquet", index=False)
    with sqlite3.connect(paths / "catalog.sqlite") as con:
        con.executemany(
            """
            INSERT INTO downloads (
                symbol, provider_symbol, yfinance_symbol, status, rows,
                first_date, last_date, years, error, warnings_json,
                raw_path, normalized_path, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("AAPL", "AAPL", "AAPL", "ok", 40, "2020-01-01", "2020-02-25", 0.15, None, "[]", str(raw / "AAPL.parquet"), str(normalized / "AAPL.parquet"), "now"),
                ("BF-B", "BF.B", "BF-B", "invalid", 10, "2020-01-01", "2020-01-15", 0.04, "row count below minimum 30", "[]", str(raw / "BF-B.parquet"), str(normalized / "BF-B.parquet"), "now"),
                ("BRK-B", "BRK.B", "BRK-B", "no_data", 0, None, None, None, None, "[]", str(raw / "BRK-B.parquet"), str(normalized / "BRK-B.parquet"), "now"),
            ],
        )

    report = prune_universe_to_valid_prices(root=tmp_path, reference_date="2020-02-26")

    assert report["removed_total"] == 2
    assert load_universe(root=tmp_path)["canonical_symbol"].tolist() == ["AAPL"]
    assert load_company_metadata(root=tmp_path)["symbol"].tolist() == ["AAPL"]
    assert (normalized / "AAPL.parquet").exists()
    assert not (normalized / "BF-B.parquet").exists()
    assert not (normalized / "BRK-B.parquet").exists()


def test_prune_universe_to_valid_prices_applies_price_quality_filters(tmp_path):
    universe = pd.DataFrame(
        {
            "provider_symbol": ["GOOD", "PENNY", "STALE", "ILLIQ", "GAPPY"],
            "canonical_symbol": ["GOOD", "PENNY", "STALE", "ILLIQ", "GAPPY"],
            "yfinance_symbol": ["GOOD", "PENNY", "STALE", "ILLIQ", "GAPPY"],
            "security_name": ["Good", "Penny", "Stale", "Illiquid", "Gappy"],
            "asset_type": ["COMMON_STOCK"] * 5,
            "exchange": ["NMS"] * 5,
            "source_file": ["test"] * 5,
            "source": ["test"] * 5,
            "retrieved_at": ["now"] * 5,
        }
    )
    persist_universe(universe, root=tmp_path)
    persist_company_metadata_frame(
        pd.DataFrame({"symbol": ["GOOD", "PENNY", "STALE", "ILLIQ", "GAPPY"], "status": ["ok"] * 5}),
        root=tmp_path,
    )
    paths = tmp_path / "prices" / "free_us_daily"
    normalized = paths / "normalized"
    raw = paths / "raw" / "yfinance"
    normalized.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)

    def write_price(symbol, close, volume, end_date, *, long_gap=False):
        frame = normalise_yfinance_history(_yf_frame(40), symbol=symbol)
        frame["date"] = pd.date_range(end=pd.Timestamp(end_date), periods=40, freq="B").date
        if long_gap:
            dates = list(pd.date_range(end=pd.Timestamp(end_date), periods=39, freq="B").date)
            dates.insert(20, pd.Timestamp("2026-01-01").date())
            frame["date"] = dates
        frame["close"] = close
        frame["adj_close"] = close
        frame["volume"] = volume
        frame.to_parquet(normalized / f"{symbol}.parquet", index=False)
        _yf_frame(40).to_parquet(raw / f"{symbol}.parquet", index=False)
        return frame

    frames = {
        "GOOD": write_price("GOOD", 10.0, 20_000, "2026-06-19"),
        "PENNY": write_price("PENNY", 0.5, 1_000_000, "2026-06-19"),
        "STALE": write_price("STALE", 10.0, 20_000, "2026-05-01"),
        "ILLIQ": write_price("ILLIQ", 10.0, 10, "2026-06-19"),
        "GAPPY": write_price("GAPPY", 10.0, 20_000, "2026-06-19", long_gap=True),
    }
    with sqlite3.connect(paths / "catalog.sqlite") as con:
        rows = []
        for symbol, frame in frames.items():
            rows.append(
                (
                    symbol,
                    symbol,
                    symbol,
                    "ok",
                    len(frame),
                    str(frame["date"].min()),
                    str(frame["date"].max()),
                    0.15,
                    None,
                    "[]",
                    str(raw / f"{symbol}.parquet"),
                    str(normalized / f"{symbol}.parquet"),
                    "now",
                )
            )
        con.executemany(
            """
            INSERT INTO downloads (
                symbol, provider_symbol, yfinance_symbol, status, rows,
                first_date, last_date, years, error, warnings_json,
                raw_path, normalized_path, retrieved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    report = prune_universe_to_valid_prices(
        root=tmp_path,
        min_last_close=1.0,
        min_median_dollar_volume_90d=100_000,
        max_last_date_age_days=10,
        max_calendar_gap_days=31,
        reference_date="2026-06-22",
    )

    assert report["removed_total"] == 4
    assert report["removed_by_reason"] == {
        "calendar_gap_above_max": 1,
        "last_close_below_min": 1,
        "last_date_too_old": 1,
        "median_dollar_volume_below_min": 1,
    }
    assert load_universe(root=tmp_path)["canonical_symbol"].tolist() == ["GOOD"]


def test_download_prices_handles_no_data_separately(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )

    def client(symbol, **kwargs):
        if symbol == "BF-B":
            return pd.DataFrame()
        return _yf_frame(40)

    results = download_prices(
        universe,
        root=tmp_path,
        symbols=["AAPL", "BF-B"],
        workers=1,
        batch_size=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=client,
    )

    by_symbol = {r.symbol: r.status for r in results}
    assert by_symbol == {"AAPL": "ok", "BF-B": "no_data"}
    report = build_coverage_report(root=tmp_path)
    assert report["downloaded_ok"] == 1
    assert report["no_data"] == 1


def test_download_prices_skip_existing_resumes_without_redownloading(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )

    calls: list[str] = []

    def client(symbol, **kwargs):
        calls.append(symbol)
        return _yf_frame(40)

    first = download_prices(
        universe,
        root=tmp_path,
        symbols=["AAPL"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=client,
    )
    second = download_prices(
        universe,
        root=tmp_path,
        symbols=["AAPL", "BRK-B"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        skip_existing=True,
        client=client,
    )

    assert [r.symbol for r in first] == ["AAPL"]
    assert [r.symbol for r in second] == ["BRK-B"]
    assert calls == ["AAPL", "BRK-B"]


def test_download_prices_supports_deterministic_shards(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    calls: list[str] = []

    def client(symbol, **kwargs):
        calls.append(symbol)
        return _yf_frame(40)

    first = download_prices(
        universe,
        root=tmp_path,
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        shard_count=2,
        shard_index=0,
        client=client,
    )
    second = download_prices(
        universe,
        root=tmp_path,
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        shard_count=2,
        shard_index=1,
        client=client,
    )

    downloaded = {r.symbol for r in first + second}
    assert downloaded == set(universe["canonical_symbol"])
    assert len(downloaded) == len(first) + len(second)


def test_build_yahoo_foreign_stock_universe_filters_noise():
    now = pd.Timestamp("2026-06-21T00:00:00Z")

    def screen_client(region, *, size, offset):
        if region != "jp":
            return {"total": 0, "quotes": []}
        if offset:
            return {"total": 6, "quotes": []}
        return {
            "total": 6,
            "quotes": [
                {
                    "symbol": "7203.T",
                    "quoteType": "EQUITY",
                    "shortName": "Toyota Motor Corporation",
                    "exchange": "JPX",
                    "marketCap": 50_000_000_000_000,
                    "financialCurrency": "JPY",
                    "currency": "JPY",
                    "regularMarketPrice": 3000,
                    "averageDailyVolume3Month": 10_000_000,
                    "regularMarketTime": int(now.timestamp()),
                    "sharesOutstanding": 10_000_000_000,
                },
                {
                    "symbol": "LOWPRICE.T",
                    "quoteType": "EQUITY",
                    "shortName": "Low Price",
                    "exchange": "JPX",
                    "marketCap": 50_000_000_000,
                    "financialCurrency": "JPY",
                    "currency": "JPY",
                    "regularMarketPrice": 100,
                    "averageDailyVolume3Month": 10_000_000,
                    "regularMarketTime": int(now.timestamp()),
                },
                {
                    "symbol": "ETF.T",
                    "quoteType": "ETF",
                    "shortName": "Index ETF",
                    "marketCap": 50_000_000_000_000,
                    "currency": "JPY",
                },
                {
                    "symbol": "UNIT.T",
                    "quoteType": "EQUITY",
                    "shortName": "Example Units",
                    "marketCap": 50_000_000_000_000,
                    "financialCurrency": "JPY",
                    "currency": "JPY",
                    "regularMarketPrice": 3000,
                    "averageDailyVolume3Month": 10_000_000,
                    "regularMarketTime": int(now.timestamp()),
                },
                {
                    "symbol": "STALE.T",
                    "quoteType": "EQUITY",
                    "shortName": "Stale Co",
                    "marketCap": 50_000_000_000_000,
                    "financialCurrency": "JPY",
                    "currency": "JPY",
                    "regularMarketPrice": 3000,
                    "averageDailyVolume3Month": 10_000_000,
                    "regularMarketTime": int(
                        pd.Timestamp("2026-05-01T00:00:00Z").timestamp()
                    ),
                },
                {
                    "symbol": "OTHER.X",
                    "quoteType": "EQUITY",
                    "shortName": "Wrong Suffix",
                    "marketCap": 50_000_000_000_000,
                    "financialCurrency": "JPY",
                    "currency": "JPY",
                    "regularMarketPrice": 3000,
                    "averageDailyVolume3Month": 10_000_000,
                    "regularMarketTime": int(now.timestamp()),
                },
            ],
        }

    universe, metadata, report = build_yahoo_foreign_stock_universe(
        priorities=("alta",),
        min_market_cap_usd=50_000_000,
        min_price_usd=1,
        min_avg_dollar_volume_3m=100_000,
        reference_time=now,
        retrieved_at="2026-06-21T00:00:00Z",
        fx_rates={"JPY": 0.00691},
        screen_client=screen_client,
    )

    assert universe["canonical_symbol"].tolist() == ["7203-T"]
    assert universe.iloc[0]["yfinance_symbol"] == "7203.T"
    assert metadata["symbol"].tolist() == ["7203-T"]
    assert metadata.iloc[0]["country"] == "Japan"
    assert report["foreign_symbols"] == 1
    assert report["rejected"]["not_equity"] == 1
    assert report["rejected"]["name"] == 1
    assert report["rejected"]["stale"] == 1


def test_enrich_company_metadata_persists_snapshot_and_coverage(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)

    results = enrich_company_metadata(
        universe,
        root=tmp_path,
        symbols=["AAPL", "BRK-B"],
        workers=1,
        batch_size=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=_metadata_fixture,
    )
    metadata = load_company_metadata(root=tmp_path)
    coverage_path = write_metadata_coverage(root=tmp_path)
    coverage = build_metadata_coverage(root=tmp_path)

    assert coverage_path.exists()
    assert {r.status for r in results} == {"ok"}
    assert set(metadata["symbol"]) == {"AAPL", "BRK-B"}
    by_symbol = metadata.set_index("symbol")
    assert by_symbol.loc["AAPL", "sector"] == "Technology"
    assert by_symbol.loc["BRK-B", "industry"] == "Insurance - Diversified"
    assert coverage["metadata_rows"] == 2
    assert coverage["sector_populated"] == 2
    assert coverage["market_cap_populated"] == 2


def test_enrich_company_metadata_skip_existing_resumes(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    calls: list[str] = []

    def client(symbol):
        calls.append(symbol)
        return _metadata_fixture(symbol)

    enrich_company_metadata(
        universe,
        root=tmp_path,
        symbols=["AAPL"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=client,
    )
    enrich_company_metadata(
        universe,
        root=tmp_path,
        symbols=["AAPL", "BRK-B"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        skip_existing=True,
        client=client,
    )

    assert calls == ["AAPL", "BRK-B"]


def test_filter_universe_by_market_cap_prunes_low_caps_and_metadata(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    metadata = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "provider_symbol": "AAPL",
                "yfinance_symbol": "AAPL",
                "company_name": "Apple Inc.",
                "security_name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "exchange": "NMS",
                "quote_type": "EQUITY",
                "market_cap": 3_000_000_000_000,
                "shares_outstanding": 15_000_000_000,
                "country": "United States",
                "website": "https://www.apple.com",
                "status": "ok",
                "source": "test",
                "retrieved_at": "2026-06-21T00:00:00Z",
                "error": None,
            },
            {
                "symbol": "BRK-B",
                "provider_symbol": "BRK.B",
                "yfinance_symbol": "BRK-B",
                "company_name": "Berkshire Hathaway Inc.",
                "security_name": "Berkshire Hathaway Inc.",
                "sector": "Financial Services",
                "industry": "Insurance - Diversified",
                "exchange": "NYQ",
                "quote_type": "EQUITY",
                "market_cap": 49_999_999,
                "shares_outstanding": 1_300_000_000,
                "country": "United States",
                "website": "https://www.berkshirehathaway.com",
                "status": "ok",
                "source": "test",
                "retrieved_at": "2026-06-21T00:00:00Z",
                "error": None,
            },
            {
                "symbol": "BF-B",
                "provider_symbol": "BF.B",
                "yfinance_symbol": "BF-B",
                "company_name": "Brown Forman Inc.",
                "security_name": "Brown Forman Inc.",
                "sector": "Consumer Defensive",
                "industry": "Beverages",
                "exchange": "NYQ",
                "quote_type": "EQUITY",
                "market_cap": pd.NA,
                "shares_outstanding": pd.NA,
                "country": "United States",
                "website": None,
                "status": "ok",
                "source": "test",
                "retrieved_at": "2026-06-21T00:00:00Z",
                "error": None,
            },
        ]
    )
    from aurora.core.free_us_daily import ensure_layout

    paths = ensure_layout(tmp_path)
    metadata.to_parquet(paths["company_metadata_path"], index=False)

    report = filter_universe_by_market_cap(
        root=tmp_path,
        min_market_cap=50_000_000,
    )

    filtered = load_universe(root=tmp_path)
    filtered_metadata = load_company_metadata(root=tmp_path)
    assert report["removed_below_min_market_cap"] == 1
    assert "BRK-B" not in set(filtered["canonical_symbol"])
    assert "BRK-B" not in set(filtered_metadata["symbol"])
    assert "AAPL" in set(filtered["canonical_symbol"])
    assert "BF-B" in set(filtered["canonical_symbol"])
    assert report["kept_missing_market_cap"] == 1


def test_export_duckdb_and_combined_parquet(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    download_prices(
        universe,
        root=tmp_path,
        symbols=["AAPL", "BRK-B"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=lambda *args, **kwargs: _yf_frame(40),
    )

    duck_path = export_duckdb(root=tmp_path)
    parquet_path = export_all_prices_parquet(root=tmp_path)

    assert duck_path.exists()
    assert parquet_path.exists()
    import duckdb

    con = duckdb.connect(str(duck_path))
    try:
        rows = con.execute("select count(*) from prices_daily").fetchone()[0]
        symbols = {
            r[0]
            for r in con.execute(
                "select distinct symbol from prices_daily"
            ).fetchall()
        }
    finally:
        con.close()
    assert rows == 80
    assert symbols == {"AAPL", "BRK-B"}


def test_update_daily_uses_next_day_for_existing_symbol(tmp_path):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    download_prices(
        universe,
        root=tmp_path,
        symbols=["AAPL"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=lambda *args, **kwargs: _yf_frame(40),
    )
    starts: list[str | None] = []

    def client(symbol, **kwargs):
        starts.append(kwargs.get("start"))
        return _yf_frame(40)

    update_daily_prices(
        root=tmp_path,
        symbols=["AAPL"],
        workers=1,
        batch_size=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=client,
    )

    assert starts == ["2020-02-26"]


def test_quality_report_and_benchmarks(tmp_path, monkeypatch):
    universe = build_us_stock_like_universe(
        client=_nasdaq_fixture,
        retrieved_at="2026-06-21T00:00:00Z",
    )
    persist_universe(universe, root=tmp_path)
    download_prices(
        universe,
        root=tmp_path,
        symbols=["AAPL"],
        workers=1,
        sleep_between_batches=0,
        retry_wait_seconds=0,
        client=lambda *args, **kwargs: _yf_frame(40),
    )
    quality_path = write_quality_report(root=tmp_path)
    quality = build_quality_report(root=tmp_path)
    assert quality_path.exists()
    assert set(quality["status"]) == {"ok", "missing"}

    import aurora.core.free_us_daily as mod

    monkeypatch.setattr(
        mod,
        "fetch_yfinance_raw",
        lambda symbol, start=None, end=None, client=None: _yf_frame(40),
    )
    payload = build_benchmarks(root=tmp_path, symbols=("SPY", "^GSPC"))
    assert [b["symbol"] for b in payload["benchmarks"]] == ["SPY", "^GSPC"]
    assert all(b["status"] == "ok" for b in payload["benchmarks"])


def test_cli_free_us_daily_help_smoke():
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "aurora.cli.forge",
            "data",
            "free-us-daily",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert res.returncode == 0, res.stderr
    assert "build-universe" in res.stdout
    assert "download-prices" in res.stdout
    assert "enrich-metadata" in res.stdout


def test_cli_coverage_report_json_empty_dataset(tmp_path):
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "aurora.cli.forge",
            "data",
            "free-us-daily",
            "coverage-report",
            "--root",
            str(tmp_path),
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert res.returncode == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["dataset"] == "free_us_daily"
    assert payload["downloaded_ok"] == 0

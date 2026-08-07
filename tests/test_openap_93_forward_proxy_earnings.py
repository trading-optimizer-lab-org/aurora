from __future__ import annotations

import json

import pandas as pd
import pytest

from aurora.research.openap_93.earnings_events import (
    announcement_return,
    attach_prior_closes,
    build_earnings_events,
    choose_earnings_event,
    earnings_streak_value,
    normalize_periodic_filing_events,
    normalize_sec_item_202_events,
    normalize_yahoo_earnings_events,
)


def test_prior_closes_are_attached_by_symbol_without_cross_symbol_leakage() -> None:
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "AAA"],
            "event_at": pd.to_datetime(
                ["2020-01-03T13:00:00Z", "2020-01-03T13:00:00Z", "2020-01-06T13:00:00Z"],
                utc=True,
            ),
            "prior_close": [None, None, 777.0],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "date": pd.to_datetime(
                ["2020-01-02", "2020-01-03", "2020-01-02", "2020-01-03"]
            ),
            "adj_close": [10.0, 11.0, 20.0, 21.0],
        }
    )

    result = attach_prior_closes(events, prices)

    assert result.loc[0, "prior_close"] == pytest.approx(10.0)
    assert result.loc[1, "prior_close"] == pytest.approx(20.0)
    assert result.loc[2, "prior_close"] == pytest.approx(777.0)


def test_build_events_only_attaches_prices_to_yahoo_eps_events() -> None:
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})
    submissions = pd.DataFrame(
        {
            "cik": [1],
            "accession_number": ["a"],
            "form": ["8-K"],
            "items": ["2.02"],
            "accepted_at": ["2020-01-03T13:00:00Z"],
            "report_date": ["2019-12-31"],
        }
    )
    analyst = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "dataset": ["earnings_dates"],
            "retrieved_at": ["2020-01-04T00:00:00Z"],
            "payload_json": [
                json.dumps(
                    [{
                        "Earnings Date": "2020-01-03T13:00:00Z",
                        "EPS Estimate": 1.0,
                        "Reported EPS": 1.1,
                    }]
                )
            ],
        }
    )
    prices = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "date": pd.to_datetime(["2020-01-02"]),
            "adj_close": [10.0],
        }
    )

    result = build_earnings_events(master, submissions, analyst, prices)

    by_source = result.set_index("source_id")
    assert pd.isna(by_source.loc["sec_8k_item_202", "prior_close"])
    assert by_source.loc["yahoo_earnings_actual", "prior_close"] == pytest.approx(10.0)


def test_item_202_precedes_yahoo_and_periodic_filing_for_same_period() -> None:
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA"],
            "period_end": ["2025-12-31"] * 3,
            "event_at": ["2026-02-01", "2026-01-29", "2026-02-05"],
            "source_id": [
                "yahoo_earnings_actual",
                "sec_8k_item_202",
                "periodic_filing_date",
            ],
            "reported_eps": [2.1, None, None],
            "consensus_eps": [2.0, None, None],
        }
    )

    chosen = choose_earnings_event(events)

    assert chosen["source_id"] == "sec_8k_item_202"
    assert pd.Timestamp(chosen["event_at"]) == pd.Timestamp("2026-01-29", tz="UTC")


def test_announcement_return_uses_exact_four_trading_sessions_minus1_plus2() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
            ),
            "stock_return": [0.01, 0.01, 0.01, 0.01, 0.50],
        }
    )
    factors = pd.DataFrame(
        {
            "date": prices["date"],
            "mktrf": [0.0] * 5,
            "rf": [0.0] * 5,
        }
    )

    result = announcement_return(prices, factors, event_at="2020-01-06")

    assert result.value == pytest.approx(0.53)
    assert result.sessions == 4
    assert result.window_start == pd.Timestamp("2020-01-03")
    assert result.window_end == pd.Timestamp("2020-01-08")


def test_earnings_streak_requires_two_same_sign_price_scaled_surprises() -> None:
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "event_at": ["2025-10-20", "2026-01-20"],
            "reported_eps": [2.0, 3.0],
            "consensus_eps": [1.0, 2.0],
            "prior_close": [100.0, 100.0],
            "source_id": ["yahoo_earnings_actual"] * 2,
        }
    )
    opposite = events.copy()
    opposite.loc[1, "reported_eps"] = 1.0

    assert earnings_streak_value(events, formation_at="2026-02-01") == pytest.approx(0.01)
    assert earnings_streak_value(opposite, formation_at="2026-02-01") is None
    assert earnings_streak_value(events, formation_at="2026-08-01") is None


def test_sec_item_202_and_yahoo_events_normalize_to_common_schema() -> None:
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})
    submissions = pd.DataFrame(
        {
            "cik": [1, 1],
            "accession_number": ["a", "b"],
            "form": ["8-K", "10-Q"],
            "items": ["2.02,9.01", ""],
            "accepted_at": ["2026-01-20T21:05:00Z", "2026-02-05T12:00:00Z"],
            "report_date": ["2025-12-31", "2025-12-31"],
        }
    )
    analyst = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "dataset": ["earnings_dates"],
            "retrieved_at": ["2026-02-01T00:00:00Z"],
            "payload_json": [
                json.dumps(
                    [
                        {
                            "Earnings Date": "2026-01-20T21:00:00Z",
                            "EPS Estimate": 2.0,
                            "Reported EPS": 2.1,
                            "Surprise(%)": 5.0,
                        }
                    ]
                )
            ],
        }
    )

    sec = normalize_sec_item_202_events(submissions, master)
    yahoo = normalize_yahoo_earnings_events(analyst)

    assert sec.iloc[0]["source_id"] == "sec_8k_item_202"
    assert sec.iloc[0]["period_end"] == pd.Timestamp("2025-12-31")
    assert yahoo.iloc[0]["reported_eps"] == pytest.approx(2.1)
    assert yahoo.iloc[0]["consensus_eps"] == pytest.approx(2.0)
    assert set(sec.columns) == set(yahoo.columns)


def test_sec_item_202_accepts_nullable_numeric_items_column() -> None:
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})
    submissions = pd.DataFrame(
        {
            "cik": pd.Series([1], dtype="Int64"),
            "accession_number": ["a"],
            "form": ["10-Q"],
            "items": pd.Series([pd.NA], dtype="Int32"),
            "accepted_at": ["2026-02-05T12:00:00Z"],
            "report_date": ["2025-12-31"],
        }
    )

    result = normalize_sec_item_202_events(submissions, master)

    assert result.empty


def test_periodic_events_accept_submissions_with_existing_symbol_column() -> None:
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})
    submissions = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "cik": [1],
            "accession_number": ["a"],
            "form": ["10-Q"],
            "items": [""],
            "accepted_at": ["2026-02-05T12:00:00Z"],
            "report_date": ["2025-12-31"],
        }
    )

    result = normalize_periodic_filing_events(submissions, master)

    assert result.iloc[0]["symbol"] == "AAA"

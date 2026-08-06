from __future__ import annotations

import json

import pandas as pd
import pytest

from aurora.research.openap_93.earnings_events import (
    announcement_return,
    choose_earnings_event,
    earnings_streak_value,
    normalize_sec_item_202_events,
    normalize_yahoo_earnings_events,
)


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
    assert pd.Timestamp(chosen["event_at"]) == pd.Timestamp("2026-01-29")


def test_announcement_return_uses_exact_four_trading_sessions_minus2_plus1() -> None:
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

    assert result.value == pytest.approx(0.04)
    assert result.sessions == 4
    assert result.window_start == pd.Timestamp("2020-01-02")
    assert result.window_end == pd.Timestamp("2020-01-07")


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

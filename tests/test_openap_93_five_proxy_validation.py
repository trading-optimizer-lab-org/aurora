from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.openap_93.historical_proxy_validation import (
    FIVE_PROXY_SIGNALS,
    _attach_formation_month_returns,
    _build_announcement_return,
    _build_earnings_streak,
    _build_earnings_streak_from_events,
    _rank_buckets,
    compare_to_reference,
    reconstruct_monthly_proxies,
)


def test_rank_buckets_are_cross_sectional_and_bounded() -> None:
    buckets = _rank_buckets(pd.Series([10.0, 20.0, 30.0, 40.0, 50.0]))
    assert buckets.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_reconstruction_rejects_unknown_signal_before_opening_database() -> None:
    with pytest.raises(ValueError, match="Unknown OpenAP proxy signals"):
        reconstruct_monthly_proxies("does-not-exist.duckdb", signals=["Unknown"])


def test_realized_return_is_aligned_to_formation_month_not_completed_month() -> None:
    proxies = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "completed_month": pd.to_datetime(["2020-01-31"]),
            "formation_month": pd.to_datetime(["2020-02-01"]),
            "signal": ["DivSeason"],
            "proxy_value": [1.0],
        }
    )
    monthly = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "completed_month": pd.to_datetime(["2020-01-31", "2020-02-29"]),
            "month_return": [-0.25, 0.40],
            "month_end_raw_close": [4.50, 9.00],
        }
    )

    result = _attach_formation_month_returns(proxies, monthly)

    assert result.iloc[0]["realized_month_return"] == pytest.approx(0.40)
    assert result.iloc[0]["screen_price"] == pytest.approx(4.50)


def test_missing_crosswalk_fails_closed_for_all_five() -> None:
    reference = pd.DataFrame(
        {
            "permno": [1],
            "yyyymm": [202001],
            "formation_month": [pd.Timestamp("2020-01-01")],
            **{signal: [1.0] for signal in FIVE_PROXY_SIGNALS},
        }
    )
    monthly, summary = compare_to_reference(reference, pd.DataFrame(), None)
    assert monthly.empty
    assert set(summary["validation_status"]) == {"blocked_missing_permno_crosswalk"}
    assert summary["paired_observations"].sum() == 0


def test_paired_reference_and_proxy_calculate_similarity() -> None:
    months = pd.date_range("2020-01-01", periods=2, freq="MS")
    reference = pd.DataFrame(
        {
            "permno": [1, 2, 3, 4, 1, 2, 3, 4],
            "yyyymm": [202001] * 4 + [202002] * 4,
            "formation_month": list(months[:1]) * 4 + list(months[1:]) * 4,
            **{signal: [1.0, 2.0, 3.0, 4.0] * 2 for signal in FIVE_PROXY_SIGNALS},
        }
    )
    crosswalk = pd.DataFrame(
        {
            "permno": [1, 2, 3, 4],
            "symbol": ["A", "B", "C", "D"],
            "effective_start": [pd.NaT] * 4,
            "effective_end": [pd.NaT] * 4,
        }
    )
    proxy = pd.DataFrame(
        [
            {
                "signal": signal,
                "symbol": symbol,
                "formation_month": month,
                "proxy_value": float(index + 1),
            }
            for signal in FIVE_PROXY_SIGNALS
            for month in months
            for index, symbol in enumerate(["A", "B", "C", "D"])
        ]
    )
    monthly, summary = compare_to_reference(reference, proxy, crosswalk, min_pairs=4)
    assert not monthly.empty
    assert set(summary["validation_status"]) == {"ok"}
    assert (summary["mean_monthly_spearman"] == 1.0).all()
    assert (summary["mean_quintile_agreement"] == 1.0).all()


def test_earnings_streak_uses_conservative_availability_lag() -> None:
    monthly = pd.DataFrame({
        "symbol": ["AAA", "AAA"],
        "completed_month": pd.to_datetime(["2016-09-30", "2016-10-31"]),
        "formation_month": pd.to_datetime(["2016-10-01", "2016-11-01"]),
    })
    history = pd.DataFrame({
        "act_symbol": ["AAA", "AAA"],
        "period_end_date": pd.to_datetime(["2016-03-31", "2016-06-30"]),
        "reported": [1.0, 1.2],
        "estimate": [0.8, 1.0],
    })
    result = _build_earnings_streak(monthly, history)
    assert result.loc[result["completed_month"].eq(pd.Timestamp("2016-09-30")), "proxy_value"].notna().all()
    assert result["reconstruction_status"].eq("reconstructed").all()
    assert result["caveat"].str.contains("90-day").all()


def test_announcement_return_uses_official_minus1_plus2_window() -> None:
    dates = pd.date_range("2020-01-06", periods=6, freq="B")
    prices = pd.DataFrame({
        "symbol": ["AAA"] * len(dates),
        "date": dates,
        "adj_close": [99.0, 100.0, 101.0, 103.0, 106.0, 110.0],
    })
    submissions = pd.DataFrame({
        "cik": [1],
        "form": ["8-K"],
        "items": ["2.02"],
        "accepted_at": [pd.Timestamp(dates[3]).tz_localize("UTC")],
        "report_date": [pd.Timestamp("2019-12-31")],
        "accession_number": ["0000000001-20-000001"],
    })
    monthly = pd.DataFrame({
        "symbol": ["AAA"],
        "completed_month": [pd.Timestamp("2020-01-31")],
        "formation_month": [pd.Timestamp("2020-02-01")],
    })
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})
    result = _build_announcement_return(monthly, submissions, prices, None, master)
    # The official window is dates[2:6]: prior session, event session, and
    # the following two sessions.
    expected = (101 / 100 - 1) + (103 / 101 - 1) + (106 / 103 - 1) + (110 / 106 - 1)
    assert result.iloc[0]["proxy_value"] == pytest.approx(expected)
    assert (
        result.iloc[0]["proxy_formula_id"]
        == "openap_announcement_return_trading_sessions_minus1_plus2"
    )
    assert result.iloc[0]["variant_id"] == "sec_8k_item_202"


def test_announcement_return_rejects_periodic_filing_date() -> None:
    dates = pd.date_range("2020-01-06", periods=6, freq="B")
    prices = pd.DataFrame(
        {"symbol": ["AAA"] * 6, "date": dates, "adj_close": range(100, 106)}
    )
    submissions = pd.DataFrame(
        {
            "cik": [1],
            "form": ["10-Q"],
            "items": [""],
            "accepted_at": [pd.Timestamp(dates[3]).tz_localize("UTC")],
            "report_date": [pd.Timestamp("2019-12-31")],
            "accession_number": ["periodic"],
        }
    )
    monthly = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "completed_month": [pd.Timestamp("2020-01-31")],
            "formation_month": [pd.Timestamp("2020-02-01")],
        }
    )
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})

    result = _build_announcement_return(monthly, submissions, prices, None, master)

    assert result.empty


def test_announcement_return_expires_after_six_months() -> None:
    dates = pd.date_range("2020-01-02", "2020-08-31", freq="B")
    prices = pd.DataFrame(
        {
            "symbol": ["AAA"] * len(dates),
            "date": dates,
            "adj_close": 100.0 + pd.Series(range(len(dates))) * 0.1,
        }
    )
    event_date = pd.Timestamp("2020-01-09", tz="UTC")
    submissions = pd.DataFrame(
        {
            "cik": [1],
            "form": ["8-K"],
            "items": ["2.02"],
            "accepted_at": [event_date],
            "report_date": [pd.Timestamp("2019-12-31")],
            "accession_number": ["event"],
        }
    )
    monthly = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "completed_month": pd.to_datetime(["2020-01-31", "2020-08-31"]),
            "formation_month": pd.to_datetime(["2020-02-01", "2020-09-01"]),
        }
    )
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})

    result = _build_announcement_return(monthly, submissions, prices, None, master)

    assert result["formation_month"].tolist() == [pd.Timestamp("2020-02-01")]


def test_earnings_streak_expires_after_six_months() -> None:
    monthly = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "completed_month": pd.to_datetime(["2020-03-31", "2020-10-31"]),
            "formation_month": pd.to_datetime(["2020-04-01", "2020-11-01"]),
        }
    )
    history = pd.DataFrame(
        {
            "act_symbol": ["AAA", "AAA"],
            "period_end_date": pd.to_datetime(["2019-09-30", "2019-12-31"]),
            "reported": [1.0, 1.2],
            "estimate": [0.8, 1.0],
        }
    )

    result = _build_earnings_streak(monthly, history)
    by_month = result.set_index("formation_month")["proxy_value"]

    assert pd.notna(by_month.loc[pd.Timestamp("2020-04-01")])
    assert pd.isna(by_month.loc[pd.Timestamp("2020-11-01")])


def test_yahoo_event_history_builds_same_prospective_earnings_streak_variant() -> None:
    monthly = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "completed_month": pd.to_datetime(["2020-04-30", "2020-11-30"]),
            "formation_month": pd.to_datetime(["2020-05-01", "2020-12-01"]),
        }
    )
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "event_at": pd.to_datetime(
                ["2020-01-10T13:00:00Z", "2020-04-10T13:00:00Z"], utc=True
            ),
            "reported_eps": [1.10, 1.30],
            "consensus_eps": [1.00, 1.10],
            "prior_close": [10.0, 10.0],
            "source_id": ["yahoo_earnings_actual", "yahoo_earnings_actual"],
        }
    )

    result = _build_earnings_streak_from_events(monthly, events)
    by_month = result.set_index("formation_month")

    assert by_month.loc[pd.Timestamp("2020-05-01"), "proxy_value"] == pytest.approx(0.02)
    assert by_month.loc[pd.Timestamp("2020-05-01"), "variant_id"] == (
        "yahoo_earnings_actual_price_scaled_v1"
    )
    assert pd.isna(by_month.loc[pd.Timestamp("2020-12-01"), "proxy_value"])


def test_announcement_return_keeps_yahoo_and_sec_variants_separate() -> None:
    dates = pd.date_range("2020-01-06", periods=6, freq="B")
    prices = pd.DataFrame(
        {"symbol": ["AAA"] * 6, "date": dates, "adj_close": range(100, 106)}
    )
    events = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "event_at": pd.to_datetime(
                ["2020-01-09T13:00:00Z", "2020-01-09T13:00:00Z"], utc=True
            ),
            "source_id": ["sec_8k_item_202", "yahoo_earnings_actual"],
        }
    )
    monthly = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "completed_month": [pd.Timestamp("2020-01-31")],
            "formation_month": [pd.Timestamp("2020-02-01")],
        }
    )
    master = pd.DataFrame({"symbol": ["AAA"], "cik": [1]})

    result = _build_announcement_return(monthly, events, prices, None, master)

    assert set(result["variant_id"]) == {"sec_8k_item_202", "yahoo_earnings_actual"}

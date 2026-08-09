from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _normalizer_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.feature_input_normalizers"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"feature input normalizers are missing: {exc}")


def _sessions() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        pd.to_datetime(
            [
                "2010-01-04",
                "2010-01-05",
                "2010-01-06",
                "2010-01-07",
                "2010-01-08",
                "2010-01-11",
            ]
        )
    )


def test_spy_panel_moves_close_to_the_next_decision_session() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-04", "2010-01-05"]),
            "open": [99.0, 100.0],
            "high": [101.0, 102.0],
            "low": [98.0, 99.0],
            "close": [100.0, 101.0],
            "volume": [1_000.0, 1_100.0],
        }
    )

    result = api.normalize_spy_decision_panel(frame, sessions=_sessions())

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-05",
        "2010-01-06",
    ]
    assert result["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-04",
        "2010-01-05",
    ]
    assert result["close"].tolist() == [100.0, 101.0]


def test_cboe_panel_combines_vix_and_vxo_at_next_session() -> None:
    api = _normalizer_api()
    vix = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-04", "2010-01-05"]),
            "CLOSE": ["20.0", "21.0"],
            "resource_id": ["vix_from_2003", "vix_from_2003"],
        }
    )
    vxo = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-04", "2010-01-05"]),
            "4": ["19.0", None],
            "Unnamed: 4": [None, "20.0"],
            "resource_id": ["vxo_1986_2003", "vxo_2004_2010"],
        }
    )

    result = api.normalize_cboe_vol_panel(vix, vxo, sessions=_sessions())

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-05",
        "2010-01-06",
    ]
    assert result["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-04",
        "2010-01-05",
    ]
    assert result["vix_close"].tolist() == [20.0, 21.0]
    assert result["vxo_close"].tolist() == [19.0, 20.0]
    assert result["date"].equals(result["available_at"])


def test_cboe_panel_keeps_latest_observation_when_dates_share_next_session() -> None:
    api = _normalizer_api()
    observations = pd.to_datetime(["2010-01-08", "2010-01-09"])
    vix = pd.DataFrame(
        {
            "date": observations,
            "CLOSE": [20.0, 21.0],
            "resource_id": "vix_from_2003",
        }
    )
    vxo = pd.DataFrame(
        {
            "date": observations,
            "4": [19.0, 20.0],
            "Unnamed: 4": None,
            "resource_id": "vxo_1986_2003",
        }
    )

    result = api.normalize_cboe_vol_panel(vix, vxo, sessions=_sessions())

    assert len(result) == 1
    assert result.loc[0, "date"] == pd.Timestamp("2010-01-11")
    assert result.loc[0, "observed_at"] == pd.Timestamp("2010-01-09")
    assert result.loc[0, "vix_close"] == pytest.approx(21.0)
    assert result.loc[0, "vxo_close"] == pytest.approx(20.0)


def test_cboe_panel_causally_carries_short_isolated_source_gaps() -> None:
    api = _normalizer_api()
    observations = pd.to_datetime(["2010-01-04", "2010-01-05", "2010-01-06"])
    vix = pd.DataFrame(
        {
            "date": observations,
            "CLOSE": [20.0, np.nan, 22.0],
            "resource_id": "vix_from_2003",
        }
    )
    vxo = pd.DataFrame(
        {
            "date": observations,
            "4": [19.0, 20.0, np.nan],
            "Unnamed: 4": np.nan,
            "resource_id": "vxo_1986_2003",
        }
    )

    result = api.normalize_cboe_vol_panel(vix, vxo, sessions=_sessions())

    january_six = result.loc[result["date"].eq(pd.Timestamp("2010-01-06"))].iloc[0]
    january_seven = result.loc[result["date"].eq(pd.Timestamp("2010-01-07"))].iloc[0]
    assert january_six["vix_close"] == pytest.approx(20.0)
    assert january_six["vxo_close"] == pytest.approx(20.0)
    assert january_seven["vix_close"] == pytest.approx(22.0)
    assert january_seven["vxo_close"] == pytest.approx(20.0)


def test_cboe_panel_rejects_recalculated_vix_before_public_methodology() -> None:
    api = _normalizer_api()
    observations = pd.to_datetime(["1998-01-05", "2003-09-22"])
    sessions = pd.bdate_range("1998-01-05", "2003-09-23")
    vix = pd.DataFrame(
        {
            "date": observations,
            "CLOSE": [30.0, 21.0],
            "resource_id": "vix_from_2003",
        }
    )
    vxo = pd.DataFrame(
        {
            "date": observations,
            "4": [18.0, 20.0],
            "Unnamed: 4": np.nan,
            "resource_id": "vxo_1986_2003",
        }
    )

    result = api.normalize_cboe_vol_panel(vix, vxo, sessions=sessions)

    pre_methodology = result.loc[
        result["date"].eq(pd.Timestamp("1998-01-06"))
    ].iloc[0]
    introduction = result.loc[
        result["date"].eq(pd.Timestamp("2003-09-23"))
    ].iloc[0]
    assert pre_methodology["vix_close"] == pytest.approx(18.0)
    assert pre_methodology["vxo_close"] == pytest.approx(18.0)
    assert introduction["vix_close"] == pytest.approx(21.0)
    assert introduction["vxo_close"] == pytest.approx(20.0)


def test_cboe_panel_does_not_carry_a_close_beyond_five_source_rows() -> None:
    api = _normalizer_api()
    observations = pd.bdate_range("2010-01-04", periods=8)
    sessions = pd.bdate_range("2010-01-04", periods=9)
    vix = pd.DataFrame(
        {
            "date": observations,
            "CLOSE": [20.0, *([np.nan] * 6), 22.0],
            "resource_id": "vix_from_2003",
        }
    )
    vxo = pd.DataFrame(
        {
            "date": observations,
            "4": np.linspace(19.0, 20.0, len(observations)),
            "Unnamed: 4": np.nan,
            "resource_id": "vxo_1986_2003",
        }
    )

    result = api.normalize_cboe_vol_panel(vix, vxo, sessions=sessions)

    sixth_gap_decision = observations[6] + pd.offsets.BDay(1)
    sixth_gap = result.loc[result["date"].eq(sixth_gap_decision)].iloc[0]
    assert pd.isna(sixth_gap["vix_close"])


def test_policy_rate_panel_uses_only_the_official_effective_funds_series() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2010-01-04", "2010-01-04", "2010-01-05"]
            ),
            "series_id": ["RIFSPFF_N.B", "OTHER_RATE", "RIFSPFF_N.B"],
            "value": [0.12, 99.0, 0.13],
        }
    )

    result = api.normalize_policy_rate_panel(frame, sessions=_sessions())

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-05",
        "2010-01-06",
    ]
    assert result["effective_fed_funds"].tolist() == [0.12, 0.13]
    assert result["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-04",
        "2010-01-05",
    ]


def test_monetary_liquidity_panel_applies_h3_and_h6_release_delays() -> None:
    api = _normalizer_api()
    sessions = pd.bdate_range("2009-12-28", "2010-01-29")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2010-01-06", "2010-01-06", "2010-01-04"]
            ),
            "series_id": ["RESMO14A_N.WW", "RESTR14A_N.WW", "M2.WM"],
            "resource_id": [
                "federal_reserve_h3_all",
                "federal_reserve_h3_all",
                "federal_reserve_h6_all",
            ],
            "value": [2_000.0, 1_000.0, 8_000.0],
        }
    )

    result = api.normalize_monetary_liquidity_panel(frame, sessions=sessions)

    h3_release = result.loc[result["date"].eq(pd.Timestamp("2010-01-14"))].iloc[0]
    h6_release = result.loc[result["date"].eq(pd.Timestamp("2010-01-14"))].iloc[0]
    assert h3_release["monetary_base"] == pytest.approx(2_000.0)
    assert h3_release["total_reserves"] == pytest.approx(1_000.0)
    assert h6_release["m2"] == pytest.approx(8_000.0)
    assert h3_release["observed_at"] == pd.Timestamp("2010-01-06")
    assert h3_release["available_at"] == pd.Timestamp("2010-01-14")


def test_credit_money_panel_bridges_old_monthly_and_new_weekly_cp_causally() -> None:
    api = _normalizer_api()
    sessions = pd.bdate_range("2000-12-20", "2001-03-15")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2000-12-31",
                    "2001-01-03",
                    "2001-01-03",
                    "2001-01-01",
                    "2001-01-03",
                ]
            ),
            "series_id": [
                "H1.DTBSPCK.M",
                "DTBSPCK_N.WW",
                "B1001NCBA",
                "M2.WM",
                "B1020NCBA",
            ],
            "resource_id": [
                "federal_reserve_cp_all",
                "federal_reserve_cp_all",
                "federal_reserve_h8_all",
                "federal_reserve_h6_all",
                "federal_reserve_h8_all",
            ],
            "value": [1_500.0, 1_600.0, 4_000.0, 8_000.0, 3_000.0],
        }
    )

    result = api.normalize_credit_money_panel(frame, sessions=sessions)
    old_only = api.normalize_credit_money_panel(
        frame.loc[frame["series_id"].ne("DTBSPCK_N.WW")],
        sessions=sessions,
    )

    weekly_release = result.loc[
        result["date"].eq(pd.Timestamp("2001-01-12"))
    ].iloc[0]
    old_monthly_release = old_only.loc[
        old_only["date"].eq(pd.Timestamp("2001-02-01"))
    ].iloc[0]
    assert weekly_release["bank_credit"] == pytest.approx(4_000.0)
    assert weekly_release["loans_and_leases"] == pytest.approx(3_000.0)
    assert weekly_release["m2"] == pytest.approx(8_000.0)
    assert weekly_release["commercial_paper"] == pytest.approx(1_600.0)
    assert old_monthly_release["commercial_paper"] == pytest.approx(1_500.0)
    assert old_monthly_release["observed_at"] == pd.Timestamp("2001-01-03")


def test_fomc_decision_panel_uses_last_day_and_next_session() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["1998-02-03", "1998-02-03", "1998-04-02"]
            ),
            "document_kind": ["meeting", "minutes", "minutes_release"],
            "document_reference": [
                "February 3-4 Meeting - 1998",
                "/fomc/minutes/19980203.htm",
                "Released April 2, 1998",
            ],
        }
    )
    sessions = pd.bdate_range("1998-02-02", "1998-04-06")

    result = api.normalize_fomc_decision_panel(frame, sessions=sessions)

    assert len(result) == 1
    assert result.loc[0, "observed_at"] == pd.Timestamp("1998-02-04")
    assert result.loc[0, "date"] == pd.Timestamp("1998-02-05")
    assert result.loc[0, "meeting_count"] == 1
    assert result.loc[0, "conference_call"] == 0


def test_calendar_marks_holiday_adjusted_standard_expiry() -> None:
    api = _normalizer_api()
    sessions = pd.bdate_range("2008-03-17", "2008-04-18").drop(
        pd.Timestamp("2008-03-21")
    )

    result = api.normalize_calendar_state_panel(sessions=sessions)

    expiry = result.loc[result["date"].eq(pd.Timestamp("2008-03-20"))].iloc[0]
    prior = result.loc[result["date"].eq(pd.Timestamp("2008-03-19"))].iloc[0]
    after = result.loc[result["date"].eq(pd.Timestamp("2008-03-24"))].iloc[0]
    assert expiry["is_standard_expiry"] == 1
    assert expiry["is_quarterly_expiry"] == 1
    assert expiry["sessions_until_standard_expiry"] == 0
    assert prior["sessions_until_standard_expiry"] == 1
    assert after["sessions_until_standard_expiry"] > 0


def test_cftc_panel_filters_sp500_and_waits_until_friday() -> None:
    api = _normalizer_api()
    base = {
        "As of Date in Form YYYY-MM-DD": "2010-01-05",
        "Open Interest (All)": "1000",
        "Noncommercial Positions-Long (All)": "400",
        "Noncommercial Positions-Short (All)": "300",
        "Commercial Positions-Long (All)": "200",
        "Commercial Positions-Short (All)": "350",
        "Concentration-Net LT =4 TDR-Long (All)": "25",
        "Concentration-Net LT =4 TDR-Short (All)": "30",
        "Concentration-Net LT =8 TDR-Long (All)": "40",
        "Concentration-Net LT =8 TDR-Short (All)": "50",
        " Total Reportable Positions-Long (All)": "700",
        "Total Reportable Positions-Short (All)": "650",
        "resource_id": "legacy_futures_only:2010",
    }
    frame = pd.DataFrame(
        [
            {
                **base,
                "Market and Exchange Names": (
                    "  E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE  "
                ),
            },
            {**base, "Market and Exchange Names": "CRUDE OIL - NEW YORK"},
        ]
    )
    frame["date"] = pd.to_datetime(frame["As of Date in Form YYYY-MM-DD"])

    result = api.normalize_cftc_sp500_panel(frame, sessions=_sessions())

    assert len(result) == 1
    assert result.loc[0, "observed_at"] == pd.Timestamp("2010-01-05")
    assert result.loc[0, "available_at"] == pd.Timestamp("2010-01-08")
    assert result.loc[0, "noncommercial_net_pct_oi"] == pytest.approx(0.1)
    assert result.loc[0, "commercial_net_pct_oi"] == pytest.approx(-0.15)
    assert result.loc[0, "noncommercial_short_pct_oi"] == pytest.approx(0.3)
    assert result.loc[0, "reportable_short_pct_oi"] == pytest.approx(0.65)
    assert result.loc[0, "top4_net_concentration"] == pytest.approx(-0.05)
    assert result.loc[0, "top8_net_concentration"] == pytest.approx(-0.1)


def test_rate_curve_uses_only_official_business_frequency_maturities() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-05"] * 4),
            "series_id": [
                "RIFLGFCM03_N.B",
                "RIFLGFCY02_N.B",
                "RIFLGFCY10_N.B",
                "RIFLGFCY10_N.M",
            ],
            "value": [0.1, 1.0, 3.0, 99.0],
        }
    )

    result = api.normalize_treasury_curve_panel(frame, sessions=_sessions())

    assert len(result) == 1
    assert result.loc[0, "available_at"] == pd.Timestamp("2010-01-06")
    assert result.loc[0, "yield_3m"] == pytest.approx(0.1)
    assert result.loc[0, "yield_2y"] == pytest.approx(1.0)
    assert result.loc[0, "yield_10y"] == pytest.approx(3.0)


def test_credit_panel_uses_daily_moodys_aaa_and_baa() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-05"] * 3),
            "series_id": [
                "RIMLPAAAR_N.B",
                "RIMLPBAAR_N.B",
                "RIMLPBAAR_N.M",
            ],
            "value": [5.25, 6.75, 99.0],
        }
    )

    result = api.normalize_credit_spread_panel(frame, sessions=_sessions())

    assert len(result) == 1
    assert result.loc[0, "observed_at"] == pd.Timestamp("2010-01-05")
    assert result.loc[0, "available_at"] == pd.Timestamp("2010-01-06")
    assert result.loc[0, "aaa_yield"] == pytest.approx(5.25)
    assert result.loc[0, "baa_yield"] == pytest.approx(6.75)
    assert result.loc[0, "baa_aaa_spread"] == pytest.approx(1.5)


def test_normalizers_reject_2011_rows() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2011-01-03"]),
            "series_id": ["RIFLGFCY10_N.B"],
            "value": [3.0],
        }
    )

    with pytest.raises(api.FeatureInputNormalizerError, match="NON_TRAIN_ROW:D_RATES"):
        api.normalize_treasury_curve_panel(frame, sessions=_sessions())


def test_financial_conditions_wait_until_next_session() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-04", "2010-01-05"]),
            "financial_conditions_score": [0.2, 0.4],
            "rate_level": [2.0, 2.1],
            "volatility_level": [20.0, 21.0],
        }
    )

    result = api.normalize_financial_conditions_panel(frame, sessions=_sessions())

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-05",
        "2010-01-06",
    ]
    assert result["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-04",
        "2010-01-05",
    ]


def test_philadelphia_realtime_growth_uses_only_values_in_each_vintage() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2009-02-15", "2009-02-15", "2009-05-15", "2009-05-15"]
            ),
            "observation_date": pd.to_datetime(
                ["2008-07-01", "2008-10-01", "2008-10-01", "2009-01-01"]
            ),
            "value": [100.0, 101.0, 102.0, 104.0],
            "resource_id": ["real_output_monthly_vintages"] * 4,
        }
    )
    sessions = pd.bdate_range("2009-02-13", "2009-05-20")

    result = api.normalize_philadelphia_realtime_growth_panel(
        frame, sessions=sessions
    )

    assert result["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2008-10-01",
        "2009-01-01",
    ]
    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2009-02-16",
        "2009-05-18",
    ]
    assert result.loc[0, "realtime_output_growth"] == pytest.approx(
        ((101.0 / 100.0) ** 4 - 1.0) * 100.0
    )
    assert result.loc[1, "realtime_output_growth"] == pytest.approx(
        ((104.0 / 102.0) ** 4 - 1.0) * 100.0
    )


def test_macro_release_panel_assigns_first_and_second_release_dates() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2009-01-01", "2009-01-01"]),
            "resource_id": [
                "philly_payroll_first_releases",
                "philly_real_output_first_releases",
            ],
            "1": [100.0, 2.0],
            "2": [120.0, 2.5],
        }
    )
    sessions = pd.bdate_range("2009-01-02", "2009-07-31")

    result = api.normalize_macro_release_panel(frame, sessions=sessions)

    march_release = result.loc[result["date"].eq(pd.Timestamp("2009-02-16"))]
    assert march_release.iloc[0]["payroll_first"] == pytest.approx(100.0)
    april_revision = result.loc[result["date"].eq(pd.Timestamp("2009-03-16"))]
    assert april_revision.iloc[0]["payroll_revision"] == pytest.approx(20.0)
    may_output = result.loc[result["date"].eq(pd.Timestamp("2009-05-15"))]
    assert may_output.iloc[0]["output_first"] == pytest.approx(2.0)


def test_fomc_events_are_only_usable_next_session() -> None:
    api = _normalizer_api()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2010-01-04", "2010-01-04", "2010-01-05"]),
            "document_kind": ["meeting", "statement", "minutes_release"],
        }
    )

    result = api.normalize_fomc_event_panel(frame, sessions=_sessions())

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-05",
        "2010-01-06",
    ]
    assert result["fomc_event_count"].tolist() == [2, 1]


def test_revised_valuation_inputs_wait_a_full_year_before_use() -> None:
    api = _normalizer_api()
    goyal = pd.DataFrame(
        {
            "date": pd.to_datetime(["2008-01-01", "2008-01-01", "2008-02-01"]),
            "resource_id": [
                "predictor_data_original_2005",
                "predictor_data_updated",
                "predictor_data_updated",
            ],
            "Index": [100.0, 100.0, 110.0],
            "D12": [4.0, 5.0, 5.5],
            "E12": [8.0, 10.0, 11.0],
            "b/m": [0.4, 0.5, 0.6],
            "ntis": [0.03, 0.02, 0.01],
        }
    )
    shiller = pd.DataFrame(
        {
            "date": pd.to_datetime(["2008-01-01", "2008-02-01"]),
            "12": [20.0, 22.0],
            "resource_id": "shiller_ie_data",
        }
    )
    sessions = pd.bdate_range("2008-01-02", "2009-04-30")

    result = api.normalize_lagged_valuation_panel(
        goyal,
        shiller,
        sessions=sessions,
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2009-02-16",
        "2009-03-16",
    ]
    assert result["observed_at"].dt.strftime("%Y-%m-%d").tolist() == [
        "2008-01-01",
        "2008-02-01",
    ]
    assert result.loc[0, "dividend_yield"] == pytest.approx(0.05)
    assert result.loc[0, "earnings_yield"] == pytest.approx(0.10)
    assert result.loc[0, "book_to_market"] == pytest.approx(0.5)
    assert result.loc[0, "inverse_cape"] == pytest.approx(0.05)
    assert result.loc[0, "net_equity_issuance"] == pytest.approx(0.02)
    assert result.loc[0, "payout_ratio"] == pytest.approx(0.5)


def test_fx_panel_uses_frozen_daily_series_only_after_next_session() -> None:
    api = _normalizer_api()
    observed = pd.to_datetime(["2010-01-04", "2010-01-05"])
    rows: list[dict[str, object]] = []
    series = {
        "V0.JRXWTFB_N.B": [100.0, 101.0],
        "RXI_N.B.CA": [1.05, 1.06],
        "RXI_N.B.JA": [92.0, 91.0],
        "RXI_N.B.SZ": [1.02, 1.01],
        "RXI$US_N.B.UK": [1.60, 1.61],
    }
    for series_id, values in series.items():
        rows.extend(
            {"date": date, "series_id": series_id, "value": value}
            for date, value in zip(observed, values, strict=True)
        )

    result = api.normalize_fx_cross_asset_panel(
        pd.DataFrame(rows), sessions=_sessions()
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2010-01-05",
        "2010-01-06",
    ]
    assert result.loc[0, "broad_dollar"] == pytest.approx(100.0)
    assert {"fx_cad", "fx_jpy", "fx_chf", "fx_gbp"} <= set(result.columns)


def test_fx_panel_causally_carries_prior_local_holiday_quotes() -> None:
    api = _normalizer_api()
    observed = pd.to_datetime(["2010-01-04", "2010-01-05"])
    rows: list[dict[str, object]] = []
    for series_id in [
        "V0.JRXWTFB_N.B",
        "RXI_N.B.CA",
        "RXI_N.B.JA",
        "RXI_N.B.SZ",
        "RXI$US_N.B.UK",
    ]:
        rows.append({"date": observed[0], "series_id": series_id, "value": 100.0})
        rows.append(
            {
                "date": observed[1],
                "series_id": series_id,
                "value": -9999.0 if series_id == "RXI_N.B.JA" else 101.0,
            }
        )

    result = api.normalize_fx_cross_asset_panel(
        pd.DataFrame(rows), sessions=_sessions()
    )

    assert result.loc[1, "fx_jpy"] == pytest.approx(100.0)
    assert result.loc[1, "observed_at"] == pd.Timestamp("2010-01-05")


def test_world_bank_assets_wait_until_third_session_of_next_month() -> None:
    api = _normalizer_api()
    gold = pd.DataFrame({"date": pd.to_datetime(["2009-12-01"]), "value": [1100.0]})
    oil = pd.DataFrame({"date": pd.to_datetime(["2009-12-01"]), "value": [75.0]})
    sessions = pd.bdate_range("2009-12-01", "2010-01-15")

    result = api.normalize_world_bank_cross_asset_panel(
        gold, oil, sessions=sessions
    )

    assert result.loc[0, "observed_at"] == pd.Timestamp("2009-12-01")
    assert result.loc[0, "available_at"] == pd.Timestamp("2010-01-05")
    assert result.loc[0, "gold"] == pytest.approx(1100.0)
    assert result.loc[0, "oil"] == pytest.approx(75.0)


def test_french_panels_use_ff3_and_48_industries_at_next_session() -> None:
    api = _normalizer_api()
    dates = pd.to_datetime(["2010-01-04", "2010-01-05"])
    factors = pd.DataFrame(
        {
            "date": dates,
            "resource_id": "ff3_daily",
            "Mkt-RF": [0.1, 0.2],
            "SMB": [0.3, 0.4],
            "HML": [-0.1, -0.2],
            "RF": [0.01, 0.01],
        }
    )
    industries = pd.DataFrame(
        {
            "date": dates,
            "resource_id": "industry_48_daily",
            "Autos": [1.0, -1.0],
            "Food": [-0.5, 0.5],
            "Util": [0.2, 0.1],
        }
    )

    factor_panel, industry_panel = api.normalize_french_us_panels(
        factors, industries, sessions=_sessions()
    )

    assert factor_panel.loc[0, "date"] == pd.Timestamp("2010-01-05")
    assert factor_panel.loc[0, "smb"] == pytest.approx(0.003)
    assert industry_panel.loc[0, "Autos"] == pytest.approx(0.01)
    assert industry_panel.loc[0, "Food"] == pytest.approx(-0.005)
    standalone = api.normalize_french_industry_panel(
        industries, sessions=_sessions()
    )
    pd.testing.assert_frame_equal(standalone, industry_panel)


def test_revised_z1_proxy_waits_full_year_and_margin_waits_two_months() -> None:
    api = _normalizer_api()
    z1_rows: list[dict[str, object]] = []
    values = {
        "FL153064105.Q": 400.0,
        "FL154090005.Q": 1000.0,
        "FL653064100.Q": 300.0,
        "FL654090000.Q": 600.0,
    }
    for series_id, value in values.items():
        z1_rows.append(
            {"date": pd.Timestamp("2008-03-31"), "series_id": series_id, "value": value}
        )
    sessions = pd.bdate_range("2008-03-31", "2009-06-30")

    z1 = api.normalize_revised_z1_equity_panel(
        pd.DataFrame(z1_rows), sessions=sessions
    )
    margin = api.normalize_finra_margin_panel(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2009-01-01"]),
                "Debit Balances in Customers' Securities Margin Accounts": [200.0],
                "Free Credit Balances in Customers' Cash Accounts": [100.0],
                "Free Credit Balances in Customers' Securities Margin Accounts": [50.0],
            }
        ),
        sessions=sessions,
    )

    assert z1.loc[0, "date"] == pd.Timestamp("2009-04-15")
    assert z1.loc[0, "household_equity_share"] == pytest.approx(0.4)
    assert z1.loc[0, "mutual_fund_equity_share"] == pytest.approx(0.5)
    assert margin.loc[0, "date"] == pd.Timestamp("2009-03-13")
    assert margin.loc[0, "margin_debit_to_credit"] == pytest.approx(200.0 / 150.0)


def test_calendar_panel_is_known_on_each_session() -> None:
    api = _normalizer_api()
    sessions = pd.bdate_range("2010-01-25", "2010-02-05")

    result = api.normalize_calendar_state_panel(sessions=sessions)

    january_end = result.loc[result["date"].eq(pd.Timestamp("2010-01-29"))].iloc[0]
    february_start = result.loc[result["date"].eq(pd.Timestamp("2010-02-01"))].iloc[0]
    assert january_end["sessions_remaining_month"] == 0
    assert february_start["session_of_month"] == 1
    assert result["date"].equals(result["observed_at"])
    assert result["date"].equals(result["available_at"])

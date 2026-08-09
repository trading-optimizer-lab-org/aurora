from __future__ import annotations

import importlib

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
    assert result.loc[0, "top4_net_concentration"] == pytest.approx(-0.05)


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

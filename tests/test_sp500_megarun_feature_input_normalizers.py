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

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_181.twelve_data_market_signals import (
    TWELVE_DATA_DIRECT_SIGNAL_TARGETS,
    TWELVE_DATA_TIME_SERIES_SIGNAL_TARGETS,
    calculate_twelve_data_direct_signals,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-10T10:00:00Z"


def _bars() -> pd.DataFrame:
    dates = pd.bdate_range("2011-06-01", "2026-07-31")
    base_close = 25.0 * np.exp(np.linspace(0.0, 1.0, len(dates)))
    volume = 1_000_000.0 + np.arange(len(dates), dtype=float) * 125.0
    volume[-10::3] = 0.0
    rows: list[dict[str, object]] = []
    for adjust, scale in (("all", 1.0), ("none", 1.01)):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "request_id": f"request-{adjust}",
                    "security_id": "SEC-0000000001-AAA",
                    "ticker": "AAA",
                    "provider_symbol": "AAA",
                    "cik": "0000000001",
                    "exchange_sec": "Nasdaq",
                    "exchange_family": "NASDAQ",
                    "issuer_share_class_count": 1,
                    "current_identity_available_at": "2026-08-01T00:00:00Z",
                    "current_identity_source_url": (
                        "https://www.sec.gov/files/company_tickers_exchange.json"
                    ),
                    "adjust": adjust,
                    "date": date.date().isoformat(),
                    "open": base_close[index] * scale,
                    "high": base_close[index] * scale * 1.01,
                    "low": base_close[index] * scale * 0.99,
                    "close": base_close[index] * scale,
                    "volume": volume[index],
                    "available_at": (
                        date.tz_localize("UTC") + pd.Timedelta(days=1)
                    ).isoformat(),
                    "available_at_quality": "next_observed_session_midnight_et",
                    "retrieved_at": RETRIEVED_AT,
                    "source_id": "twelve_data_basic",
                    "source_url": "https://api.twelvedata.com/time_series",
                    "safe_request_url": "https://api.twelvedata.com/time_series?symbol=AAA",
                    "raw_response_sha256": "a" * 64,
                    "identity_quality": (
                        "current_sec_cik_ticker_exchange_plus_twelve_data_symbol_mic_type"
                    ),
                    "historical_ticker_interval_verified": False,
                    "strict_score_eligible": False,
                }
            )
    return pd.DataFrame(rows)


def test_twelve_data_direct_market_signals_calculate_time_series_targets() -> None:
    result = calculate_twelve_data_direct_signals(
        _bars(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("signal")

    assert set(result.index) == set(TWELVE_DATA_DIRECT_SIGNAL_TARGETS)
    assert len(result) == 12
    time_series = result.loc[list(TWELVE_DATA_TIME_SERIES_SIGNAL_TARGETS)]
    assert time_series["current_usable"].all()
    assert time_series["value"].notna().all()
    assert time_series["fidelity_class"].eq("reconstructed").all()
    assert not result.loc[["BetaTailRisk", "MomRev", "MomVol"], "current_usable"].any()
    assert result["source_id"].eq("twelve_data_basic").all()
    assert result["strict_score_eligible"].eq(False).all()  # noqa: E712
    assert result["formula_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert result.loc["High52", "value"] == pytest.approx(1.0)


def test_twelve_data_direct_market_signals_fail_closed_without_both_adjustments() -> None:
    bars = _bars().loc[lambda frame: frame["adjust"].eq("all")].copy()
    result = calculate_twelve_data_direct_signals(
        bars,
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )

    assert len(result) == 12
    assert result["value"].isna().all()
    assert not result["current_usable"].any()


def test_twelve_data_direct_market_signals_reject_strict_or_historical_claims() -> None:
    bars = _bars()
    bars.loc[bars.index[0], "strict_score_eligible"] = True

    with pytest.raises(ValueError, match="non-strict source contract"):
        calculate_twelve_data_direct_signals(
            bars,
            formation_at=FORMATION_AT,
            retrieved_at=RETRIEVED_AT,
        )


def test_identity_conflict_cannot_hide_in_an_invalid_bar() -> None:
    bars = _bars()
    conflicting = bars.iloc[[0]].copy()
    conflicting["ticker"] = "BBB"
    conflicting["close"] = np.nan

    with pytest.raises(ValueError, match="conflicting current identities"):
        calculate_twelve_data_direct_signals(
            pd.concat([bars, conflicting], ignore_index=True),
            formation_at=FORMATION_AT,
            retrieved_at=RETRIEVED_AT,
        )


def _cross_section_bars() -> pd.DataFrame:
    dates = pd.date_range("2023-06-30", "2026-07-31", freq="BME")
    formation_period = pd.Period("2026-08", freq="M")
    rows: list[dict[str, object]] = []
    for security_number in range(1, 11):
        close = 100.0
        closes: list[float] = []
        for date in dates:
            lag = int(formation_period.ordinal - date.to_period("M").ordinal)
            if 1 <= lag <= 5:
                monthly_return = security_number * 0.005
            elif 13 <= lag <= 36:
                monthly_return = (11 - security_number) * 0.001
            else:
                monthly_return = 0.001
            close *= 1.0 + monthly_return
            closes.append(close)
        for adjust, scale in (("all", 1.0), ("none", 1.01)):
            for date, value in zip(dates, closes, strict=True):
                rows.append(
                    {
                        "security_id": f"SEC-{security_number:010d}-S{security_number:02d}",
                        "ticker": f"S{security_number:02d}",
                        "cik": f"{security_number:010d}",
                        "adjust": adjust,
                        "date": date.date().isoformat(),
                        "close": value * scale,
                        "high": value * scale * 1.01,
                        "low": value * scale * 0.99,
                        "volume": float(security_number * 100_000),
                        "available_at": (
                            date.tz_localize("UTC") + pd.Timedelta(days=1)
                        ).isoformat(),
                        "retrieved_at": RETRIEVED_AT,
                        "source_id": "twelve_data_basic",
                        "historical_ticker_interval_verified": False,
                        "strict_score_eligible": False,
                    }
                )
    return pd.DataFrame(rows)


def _beta_tail_bars() -> pd.DataFrame:
    dates = pd.date_range("2019-08-30", "2026-07-31", freq="BME")
    rows: list[dict[str, object]] = []
    for security_number in range(1, 41):
        close = 100.0
        closes: list[float] = []
        exposure = security_number / 40.0
        for month_number, _date in enumerate(dates):
            tail_state = 0.008 + 0.004 * (
                1.0 + np.sin(month_number * np.pi / 9.0)
            )
            close *= 1.0 - 0.002 - exposure * tail_state
            closes.append(close)
        for adjust, scale in (("all", 1.0), ("none", 1.01)):
            for date, value in zip(dates, closes, strict=True):
                rows.append(
                    {
                        "security_id": f"SEC-{security_number:010d}-T{security_number:02d}",
                        "ticker": f"T{security_number:02d}",
                        "cik": f"{security_number:010d}",
                        "adjust": adjust,
                        "date": date.date().isoformat(),
                        "close": value * scale,
                        "high": value * scale * 1.01,
                        "low": value * scale * 0.99,
                        "volume": float(500_000 + security_number * 1_000),
                        "available_at": (
                            date.tz_localize("UTC") + pd.Timedelta(days=1)
                        ).isoformat(),
                        "retrieved_at": RETRIEVED_AT,
                        "source_id": "twelve_data_basic",
                        "historical_ticker_interval_verified": False,
                        "strict_score_eligible": False,
                    }
                )
    return pd.DataFrame(rows)


def test_cross_sectional_momentum_and_volume_sorts_are_prepared() -> None:
    result = calculate_twelve_data_direct_signals(
        _cross_section_bars(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )
    cross = result.loc[result["signal"].isin({"MomRev", "MomVol"})]
    momrev = cross.loc[cross["signal"].eq("MomRev")].set_index("ticker")
    momvol = cross.loc[cross["signal"].eq("MomVol")]

    assert momrev.loc["S01", "value"] == pytest.approx(0.0)
    assert momrev.loc["S10", "value"] == pytest.approx(1.0)
    assert momvol["current_usable"].any()
    assert momvol.loc[momvol["current_usable"], "value"].between(1, 10).all()
    assert not cross["strict_score_eligible"].any()


def test_cross_sectional_tail_beta_is_prepared_without_external_factors() -> None:
    result = calculate_twelve_data_direct_signals(
        _beta_tail_bars(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )
    beta_tail = result.loc[result["signal"].eq("BetaTailRisk")]

    assert len(beta_tail) == 40
    assert beta_tail["current_usable"].all()
    assert beta_tail["value"].notna().all()
    assert beta_tail["observation_count"].ge(72).all()
    assert not beta_tail["strict_score_eligible"].any()

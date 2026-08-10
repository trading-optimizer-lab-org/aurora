from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.research.openap_181.twelve_data_factor_signals import (
    TWELVE_DATA_FACTOR_SIGNAL_TARGETS,
    calculate_twelve_data_factor_signals,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-10T10:00:00Z"


def _factor_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-02", "2026-07-31")
    index = np.arange(len(dates), dtype=float)
    market = 0.0002 + 0.006 * np.sin(index / 13.0) + 0.002 * np.cos(index / 5.0)
    daily_factors = pd.DataFrame(
        {
            "date": dates,
            "mktrf": market,
            "smb": 0.002 * np.sin(index / 17.0),
            "hml": 0.002 * np.cos(index / 19.0),
            "rf": np.full(len(dates), 0.00001),
        }
    )
    monthly_factors = (
        daily_factors.assign(month=dates.to_period("M"))
        .groupby("month", as_index=False)
        .agg(
            date=("date", "min"),
            mktrf=("mktrf", "sum"),
            smb=("smb", "sum"),
            hml=("hml", "sum"),
            rf=("rf", "sum"),
        )
        .drop(columns="month")
    )
    rows: list[dict[str, object]] = []
    lagged_market = np.r_[0.0, market[:-1]]
    for security_number in range(1, 7):
        exposure = 0.55 + security_number * 0.12
        returns = (
            0.0001
            + exposure * market
            + 0.08 * lagged_market
            + 0.0005 * np.sin(index / (3.0 + security_number))
        )
        adjusted_close = 40.0 * np.cumprod(1.0 + returns)
        for adjust, scale in (("all", 1.0), ("none", 1.01)):
            for date, close in zip(dates, adjusted_close, strict=True):
                rows.append(
                    {
                        "security_id": (
                            f"SEC-{security_number:010d}-F{security_number:02d}"
                        ),
                        "ticker": f"F{security_number:02d}",
                        "cik": f"{security_number:010d}",
                        "adjust": adjust,
                        "date": date.date().isoformat(),
                        "close": float(close * scale),
                        "high": float(close * scale * 1.01),
                        "low": float(close * scale * 0.99),
                        "volume": float(500_000 + security_number * 10_000),
                        "available_at": (
                            date.tz_localize("UTC") + pd.Timedelta(days=1)
                        ).isoformat(),
                        "retrieved_at": RETRIEVED_AT,
                        "source_id": "twelve_data_basic",
                        "historical_ticker_interval_verified": False,
                        "strict_score_eligible": False,
                    }
                )
    return pd.DataFrame(rows), daily_factors, monthly_factors


def test_twelve_data_and_free_french_factors_prepare_eleven_signals() -> None:
    bars, daily, monthly = _factor_inputs()

    result = calculate_twelve_data_factor_signals(
        bars,
        daily,
        monthly,
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    )

    assert len(result) == 6 * len(TWELVE_DATA_FACTOR_SIGNAL_TARGETS)
    assert set(result["signal"]) == set(TWELVE_DATA_FACTOR_SIGNAL_TARGETS)
    assert result["current_usable"].all()
    assert result["value"].notna().all()
    assert result["fidelity_class"].eq("reconstructed").all()
    assert result["source_id"].eq(
        "twelve_data_basic|kenneth_french"
    ).all()
    assert result["strict_score_eligible"].eq(False).all()  # noqa: E712
    assert result["formula_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()


def test_free_factor_inputs_reject_duplicate_dates() -> None:
    bars, daily, monthly = _factor_inputs()
    duplicate = pd.concat([daily, daily.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate dates"):
        calculate_twelve_data_factor_signals(
            bars,
            duplicate,
            monthly,
            formation_at=FORMATION_AT,
            retrieved_at=RETRIEVED_AT,
        )

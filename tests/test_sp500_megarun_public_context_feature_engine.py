from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.public_context_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"public-context feature engine is missing: {exc}")


def _timed(
    dates: pd.DatetimeIndex,
    values: Mapping[str, object],
    *,
    same_session: bool = False,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates if same_session else dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("1997-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    market = _timed(
        dates,
        {"close": 100.0 * np.exp(np.cumsum(0.0002 + 0.004 * np.sin(phase / 31.0)))},
    )
    publication_dates = dates[20::21]
    p = np.arange(len(publication_dates), dtype=float)
    philly = _timed(
        publication_dates,
        {
            "vintage_count": 1.0 + (p % 4),
            "resource_breadth": 1.0 + (p % 6),
            "monthly_breadth": 1.0 + (p % 2),
            "quarterly_breadth": 1.0 + (p % 4),
            "publication_point_count": 100.0 + 3.0 * p,
            "latest_observation_age_days": 35.0 + 8.0 * np.sin(p / 7.0),
            "oldest_latest_observation_age_days": 80.0 + 15.0 * np.cos(p / 9.0),
        },
    )
    announcement_dates = dates[10::10]
    a = np.arange(len(announcement_dates), dtype=float)
    announcements = _timed(
        announcement_dates,
        {
            "announcement_count": 1.0 + (a % 4),
            "announced_offering": 20e9 + 4e9 * np.sin(a / 9.0) + 20e6 * a,
            "weighted_maturity_years": 3.0 + 2.0 * np.sin(a / 13.0),
            "announcement_to_auction_days": 4.0 + (a % 4),
            "maturity_hhi": 0.45 + 0.05 * np.sin(a / 14.0),
            "bill_share": 0.45 + 0.1 * np.cos(a / 12.0),
            "note_bond_share": 0.55 - 0.1 * np.cos(a / 12.0),
        },
    )
    fomc_dates = dates[15::31]
    f = np.arange(len(fomc_dates), dtype=float)
    meeting_count = (f % 3 == 0).astype(float)
    statement_count = (f % 3 == 1).astype(float)
    minutes_count = (f % 3 == 2).astype(float)
    fomc_documents = _timed(
        fomc_dates,
        {
            "meeting_count": meeting_count,
            "statement_count": statement_count,
            "minutes_release_count": minutes_count,
            "document_count": meeting_count + statement_count + minutes_count,
            "meeting_share": meeting_count,
            "statement_share": statement_count,
            "minutes_release_share": minutes_count,
            "document_mix_entropy": 0.2 + 0.1 * np.sin(f / 5.0),
            "publication_gap_days": 30.0 + 5.0 * np.sin(f / 7.0),
        },
    )
    tic_dates = pd.DatetimeIndex(
        dates.to_series().groupby(dates.to_period("M")).first().iloc[2:]
    )
    t = np.arange(len(tic_dates), dtype=float)
    tic = _timed(
        tic_dates,
        {
            "tic_treasury_net_purchases": 25_000.0 + 15_000.0 * np.sin(t / 7.0),
            "tic_treasury_official": 8_000.0 + 4_000.0 * np.cos(t / 9.0),
            "tic_equity_net_purchases": 10_000.0 + 12_000.0 * np.cos(t / 8.0),
            "tic_equity_official": 2_000.0 + 2_500.0 * np.sin(t / 10.0),
        },
    )
    weather = _timed(
        dates,
        {
            "temperature": 55.0 + 22.0 * np.sin(2.0 * np.pi * phase / 252.0),
            "dewpoint": 42.0 + 18.0 * np.sin(2.0 * np.pi * (phase - 8.0) / 252.0),
            "sea_level_pressure": 1013.0 + 8.0 * np.cos(phase / 19.0),
            "visibility": 9.0 + 1.5 * np.sin(phase / 13.0),
            "wind_speed": 7.0 + 3.0 * np.cos(phase / 17.0),
            "maximum_wind_speed": 13.0 + 4.0 * np.cos(phase / 17.0),
            "gust": 18.0 + 6.0 * np.cos(phase / 17.0),
            "maximum_temperature": 64.0 + 22.0 * np.sin(2.0 * np.pi * phase / 252.0),
            "minimum_temperature": 46.0 + 20.0 * np.sin(2.0 * np.pi * phase / 252.0),
            "precipitation": np.maximum(0.0, 0.3 * np.sin(phase / 11.0)),
            "snow_depth": np.maximum(0.0, 3.0 * np.cos(2.0 * np.pi * phase / 252.0)),
            "fog": (np.sin(phase / 23.0) > 0.8).astype(float),
            "rain": (np.sin(phase / 11.0) > 0.4).astype(float),
            "snow_ice": (np.cos(2.0 * np.pi * phase / 252.0) > 0.8).astype(float),
            "hail": np.zeros(len(dates)),
            "thunder": (np.sin(phase / 29.0) > 0.9).astype(float),
            "tornado": np.zeros(len(dates)),
        },
    )
    month_groups = pd.Series(np.arange(len(dates)), index=dates).groupby(dates.to_period("M"))
    session_of_month = month_groups.cumcount() + 1
    remaining = month_groups.cumcount(ascending=False)
    calendar = _timed(
        dates,
        {
            "weekday": dates.weekday,
            "month": dates.month,
            "quarter": dates.quarter,
            "session_of_month": session_of_month.to_numpy(),
            "sessions_remaining_month": remaining.to_numpy(),
            "is_standard_expiry": ((dates.weekday == 4) & (dates.day >= 15) & (dates.day <= 21)).astype(int),
            "is_quarterly_expiry": ((dates.weekday == 4) & (dates.day >= 15) & (dates.day <= 21) & np.isin(dates.month, [3, 6, 9, 12])).astype(int),
            "sessions_until_standard_expiry": np.mod(phase, 21),
        },
        same_session=True,
    )
    return market, {
        "philly": philly,
        "announcements": announcements,
        "fomc_documents": fomc_documents,
        "tic": tic,
        "weather": weather,
        "calendar": calendar,
    }


_VARIANTS = {
    "F231": ("resource_breadth", "release_gap", "release_frequency", "breadth_change", "freshness", "clustering_breadth"),
    "F232": ("announcement_count", "announced_offering", "announcement_gap", "announcement_density", "weighted_maturity", "maturity_hhi", "lead_days", "cluster_pressure"),
    "F233": ("document_count", "publication_gap", "publication_density", "meeting_share", "statement_share", "minutes_share", "mix_entropy", "mix_change"),
    "F234": ("treasury_equity_divergence", "official_divergence", "divergence_change", "divergence_zscore", "direction_disagreement", "flow_ratio", "rolling_correlation"),
    "F235": ("precipitation", "precipitation_event", "precipitation_anomaly", "visibility", "fog", "snow_depth", "wet_low_visibility"),
    "F236": ("temperature", "temperature_anomaly", "temperature_range", "dewpoint_spread", "pressure_anomaly", "wind_speed", "gust", "temperature_extreme", "storm_composite"),
    "F237": ("daylight_minutes", "daylight_change", "is_dst", "dst_transition_window", "days_to_dst_transition", "clock_change_direction"),
    "F238": ("turn_of_month", "turn_of_quarter", "turn_of_year", "pre_holiday", "post_holiday", "standard_expiry", "quarterly_expiry", "sessions_until_expiry"),
    "F239": ("presidential_cycle_year", "election_year", "midterm_year", "days_to_general_election", "absolute_election_distance", "pre_election_window", "post_election_window", "cycle_sine", "cycle_cosine"),
    "F240": ("total_event_count", "rolling_event_density", "type_weighted_density", "event_breadth", "event_concentration", "macro_policy_overlap", "public_arrival_pressure"),
}


def _parameters(lane: str) -> dict[str, object]:
    return {
        "statistic": _VARIANTS[lane][0],
        "window": 20,
        "change_lag": 1,
        "normalization": "raw",
        "direction": "continuation",
    }


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(231, 241)])
def test_f231_f240_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_public_context_lane(lane, market, panels, _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(231, 241)])
def test_f231_f240_do_not_change_when_future_train_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[2200, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {name: panel.loc[panel["date"].le(cutoff)].copy() for name, panel in panels.items()}

    before = api.evaluate_public_context_lane(lane, before_market, before_panels, _parameters(lane))
    after = api.evaluate_public_context_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(("lane", "variants"), list(_VARIANTS.items()))
def test_f231_f240_frozen_statistics_are_executable(lane: str, variants: tuple[str, ...]) -> None:
    market, panels = _inputs()
    for statistic in variants:
        result = _api().evaluate_public_context_lane(
            lane, market, panels, {**_parameters(lane), "statistic": statistic}
        )
        assert result["value"].notna().any(), f"{lane}:{statistic}"


def test_public_context_engine_fails_closed() -> None:
    api = _api()
    market, panels = _inputs()
    with pytest.raises(api.PublicContextFeatureEngineError, match="UNKNOWN_LANE"):
        api.evaluate_public_context_lane("F241", market, panels, {})
    with pytest.raises(api.PublicContextFeatureEngineError, match="UNKNOWN_PARAMETER"):
        api.evaluate_public_context_lane(
            "F235", market, panels, {**_parameters("F235"), "statistic": "sunshine"}
        )
    future = market.copy()
    future.loc[len(future)] = future.iloc[-1]
    future.loc[len(future) - 1, ["date", "observed_at", "available_at"]] = pd.Timestamp("2011-01-03")
    with pytest.raises(api.PublicContextFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_public_context_lane("F231", future, panels, _parameters("F231"))


@pytest.mark.parametrize(
    ("lane", "statistic"),
    [("F235", "visibility"), ("F236", "temperature_anomaly")],
)
def test_family_batch_uses_continuous_weather_representatives(
    lane: str, statistic: str
) -> None:
    api = _api()
    market, panels = _inputs()

    batch = api.evaluate_public_context_family_batch(market, panels)[lane]
    explicit = api.evaluate_public_context_lane(
        lane,
        market,
        panels,
        {
            "statistic": statistic,
            "window": 20,
            "change_lag": 1,
            "normalization": "raw",
            "direction": "continuation",
        },
    )

    pd.testing.assert_frame_equal(batch, explicit)

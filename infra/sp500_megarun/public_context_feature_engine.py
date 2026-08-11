"""Causal train-only public-context kernels for SP500 lanes F231-F240."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


class PublicContextFeatureEngineError(ValueError):
    """Raised when F231-F240 violate their frozen causal contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F231": ("philly",),
    "F232": ("announcements",),
    "F233": ("fomc_documents",),
    "F234": ("tic",),
    "F235": ("weather",),
    "F236": ("weather",),
    "F237": ("calendar",),
    "F238": ("calendar",),
    "F239": ("calendar",),
    "F240": ("philly", "announcements", "fomc_documents", "calendar"),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise PublicContextFeatureEngineError(
            f"TIMESTAMP_COLUMNS_MISSING:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = (
            pd.to_datetime(result[column], errors="coerce")
            .astype("datetime64[ns]")
            .dt.normalize()
        )
    if result.loc[:, list(_TIMESTAMPS)].isna().any().any():
        raise PublicContextFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(_TRAIN_END).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise PublicContextFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise PublicContextFeatureEngineError(
            f"OBSERVED_AFTER_AVAILABILITY:{label}"
        )
    if result["available_at"].gt(result["date"]).any():
        raise PublicContextFeatureEngineError(
            f"AVAILABLE_AFTER_PANEL_DATE:{label}"
        )
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise PublicContextFeatureEngineError(
            f"DATES_NOT_STRICTLY_ORDERED:{label}"
        )
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise PublicContextFeatureEngineError(
            f"INVALID_POSITIVE_PARAMETER:{name}:{value}"
        )
    return value


def _choice(
    parameters: Mapping[str, Any],
    name: str,
    choices: Sequence[str],
    default: str,
) -> str:
    value = str(parameters.get(name, default))
    if value not in choices:
        raise PublicContextFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _numeric(frame: pd.DataFrame, columns: Sequence[str], *, label: str) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise PublicContextFeatureEngineError(
            f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}"
        )
    return (
        frame.loc[:, list(columns)]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0.0, np.nan)


def _rolling_zscore(value: pd.Series, window: int) -> pd.Series:
    mean = value.rolling(window, min_periods=window).mean()
    scale = value.rolling(window, min_periods=window).std(ddof=0)
    return (value - mean) / scale.replace(0.0, np.nan)


def _normalize(
    value: pd.Series,
    parameters: Mapping[str, Any],
    *,
    window: int,
) -> pd.Series:
    mode = _choice(
        parameters,
        "normalization",
        ("raw", "change", "rolling_zscore"),
        "raw",
    )
    if mode == "change":
        return value.diff(_positive(parameters, "change_lag", 1))
    if mode == "rolling_zscore":
        return _rolling_zscore(value, window)
    return value


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(
        parameters,
        "direction",
        ("continuation", "reversal"),
        "continuation",
    )
    return value if direction == "continuation" else -value


def _align_panel(market: pd.DataFrame, panel: pd.DataFrame, *, label: str) -> pd.DataFrame:
    values = [column for column in panel if column not in _TIMESTAMPS]
    rename = {
        "date": f"{label}_source_date",
        "observed_at": f"{label}_source_observed_at",
        "available_at": f"{label}_source_available_at",
        **{column: f"{label}_{column}" for column in values},
    }
    right = panel.rename(columns=rename)
    aligned = pd.merge_asof(
        market.loc[:, ["date"]],
        right.sort_values(f"{label}_source_date", kind="mergesort"),
        left_on="date",
        right_on=f"{label}_source_date",
        direction="backward",
        allow_exact_matches=True,
    )
    if aligned[f"{label}_source_available_at"].gt(aligned["date"]).fillna(False).any():
        raise PublicContextFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{label}")
    return aligned


def _output(
    market: pd.DataFrame,
    alignments: Sequence[tuple[str, pd.DataFrame]],
    value: pd.Series,
) -> pd.DataFrame:
    observed = pd.concat(
        [aligned[f"{label}_source_observed_at"] for label, aligned in alignments],
        axis=1,
    ).max(axis=1)
    available = pd.concat(
        [aligned[f"{label}_source_available_at"] for label, aligned in alignments],
        axis=1,
    ).max(axis=1)
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": observed.fillna(market["observed_at"]),
            "available_at": available.fillna(market["available_at"]),
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _daily_choice(
    market: pd.DataFrame,
    alignments: Sequence[tuple[str, pd.DataFrame]],
    choices: Mapping[str, pd.Series],
    parameters: Mapping[str, Any],
    *,
    default: str,
) -> pd.DataFrame:
    window = _positive(parameters, "window", 20)
    statistic = _choice(parameters, "statistic", tuple(choices), default)
    value = _direction(
        _normalize(choices[statistic], parameters, window=window), parameters
    )
    return _output(market, alignments, value)


def _event_choice(
    market: pd.DataFrame,
    source: pd.DataFrame,
    choices: Mapping[str, pd.Series],
    parameters: Mapping[str, Any],
    *,
    default: str,
    label: str,
) -> pd.DataFrame:
    window = _positive(parameters, "window", 13)
    statistic = _choice(parameters, "statistic", tuple(choices), default)
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["feature"] = _direction(
        _normalize(choices[statistic], parameters, window=window), parameters
    )
    aligned = _align_panel(market, derived, label=label)
    return _output(market, [(label, aligned)], aligned[f"{label}_feature"])


def _f231(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["philly"]
    values = _numeric(
        source,
        (
            "resource_breadth",
            "monthly_breadth",
            "quarterly_breadth",
            "latest_observation_age_days",
        ),
        label="philly",
    )
    gap = source["date"].diff().dt.days.astype(float)
    choices = {
        "resource_breadth": values["resource_breadth"],
        "release_gap": gap,
        "release_frequency": 365.25 / gap.replace(0.0, np.nan),
        "breadth_change": values["resource_breadth"].diff(
            _positive(parameters, "change_lag", 1)
        ),
        "freshness": -values["latest_observation_age_days"],
        "clustering_breadth": _safe_ratio(values["resource_breadth"], gap),
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="clustering_breadth",
        label="philly_f231",
    )


def _f232(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["announcements"]
    values = _numeric(
        source,
        (
            "announcement_count",
            "announced_offering",
            "weighted_maturity_years",
            "announcement_to_auction_days",
            "maturity_hhi",
        ),
        label="announcements",
    )
    window = _positive(parameters, "window", 13)
    gap = source["date"].diff().dt.days.astype(float)
    choices = {
        "announcement_count": values["announcement_count"],
        "announced_offering": values["announced_offering"],
        "announcement_gap": gap,
        "announcement_density": values["announcement_count"].rolling(
            window, min_periods=window
        ).sum(),
        "weighted_maturity": values["weighted_maturity_years"],
        "maturity_hhi": values["maturity_hhi"],
        "lead_days": values["announcement_to_auction_days"],
        "cluster_pressure": (
            _rolling_zscore(values["announced_offering"], window)
            * values["announcement_count"]
            / gap.replace(0.0, np.nan)
        ),
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="cluster_pressure",
        label="announcement_f232",
    )


def _f233(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["fomc_documents"]
    values = _numeric(
        source,
        (
            "document_count",
            "publication_gap_days",
            "meeting_share",
            "statement_share",
            "minutes_release_share",
            "document_mix_entropy",
        ),
        label="fomc_documents",
    )
    window = _positive(parameters, "window", 13)
    choices = {
        "document_count": values["document_count"],
        "publication_gap": values["publication_gap_days"],
        "publication_density": values["document_count"].rolling(
            window, min_periods=window
        ).sum(),
        "meeting_share": values["meeting_share"],
        "statement_share": values["statement_share"],
        "minutes_share": values["minutes_release_share"],
        "mix_entropy": values["document_mix_entropy"],
        "mix_change": values["document_mix_entropy"].diff(
            _positive(parameters, "change_lag", 1)
        ),
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="mix_entropy",
        label="fomc_f233",
    )


def _f234(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["tic"]
    values = _numeric(
        source,
        (
            "tic_treasury_net_purchases",
            "tic_treasury_official",
            "tic_equity_net_purchases",
            "tic_equity_official",
        ),
        label="tic",
    )
    treasury = values["tic_treasury_net_purchases"]
    equity = values["tic_equity_net_purchases"]
    divergence = treasury - equity
    window = _positive(parameters, "window", 13)
    choices = {
        "treasury_equity_divergence": divergence,
        "official_divergence": (
            values["tic_treasury_official"] - values["tic_equity_official"]
        ),
        "divergence_change": divergence.diff(_positive(parameters, "change_lag", 1)),
        "divergence_zscore": _rolling_zscore(divergence, window),
        "direction_disagreement": (np.sign(treasury) != np.sign(equity)).astype(float),
        "flow_ratio": _safe_ratio(treasury, equity.abs()),
        "rolling_correlation": treasury.rolling(window, min_periods=window).corr(equity),
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="divergence_zscore",
        label="tic_f234",
    )


def _weather_values(source: pd.DataFrame) -> pd.DataFrame:
    return _numeric(
        source,
        (
            "temperature",
            "dewpoint",
            "sea_level_pressure",
            "visibility",
            "wind_speed",
            "maximum_wind_speed",
            "gust",
            "maximum_temperature",
            "minimum_temperature",
            "precipitation",
            "snow_depth",
            "fog",
            "rain",
            "snow_ice",
            "hail",
            "thunder",
            "tornado",
        ),
        label="weather",
    )


def _f235(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["weather"]
    values = _weather_values(source)
    window = _positive(parameters, "window", 20)
    precip_z = _rolling_zscore(values["precipitation"], window)
    visibility_z = _rolling_zscore(values["visibility"], window)
    choices = {
        "precipitation": values["precipitation"],
        "precipitation_event": (
            values["precipitation"].gt(0.0) | values["rain"].gt(0.0)
        ).astype(float),
        "precipitation_anomaly": precip_z,
        "visibility": values["visibility"],
        "fog": values["fog"],
        "snow_depth": values["snow_depth"],
        "wet_low_visibility": precip_z - visibility_z + values["fog"],
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="wet_low_visibility",
        label="weather_f235",
    )


def _f236(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["weather"]
    values = _weather_values(source)
    window = _positive(parameters, "window", 63)
    temp_z = _rolling_zscore(values["temperature"], window)
    pressure_z = _rolling_zscore(values["sea_level_pressure"], window)
    wind_z = _rolling_zscore(values["wind_speed"], window)
    gust_z = _rolling_zscore(values["gust"], window)
    choices = {
        "temperature": values["temperature"],
        "temperature_anomaly": temp_z,
        "temperature_range": (
            values["maximum_temperature"] - values["minimum_temperature"]
        ),
        "dewpoint_spread": values["temperature"] - values["dewpoint"],
        "pressure_anomaly": pressure_z,
        "wind_speed": values["wind_speed"],
        "gust": values["gust"],
        "temperature_extreme": temp_z.abs(),
        "storm_composite": wind_z + 0.5 * gust_z - pressure_z,
    }
    return _event_choice(
        market,
        source,
        choices,
        parameters,
        default="storm_composite",
        label="weather_f236",
    )


def _first_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> pd.Timestamp:
    start = pd.Timestamp(year=year, month=month, day=1)
    offset = (weekday - start.weekday()) % 7 + 7 * (occurrence - 1)
    return start + pd.Timedelta(days=offset)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> pd.Timestamp:
    end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    return end - pd.Timedelta(days=(end.weekday() - weekday) % 7)


def _dst_boundaries(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    if year >= 2007:
        return (
            _first_weekday_of_month(year, 3, 6, 2),
            _first_weekday_of_month(year, 11, 6, 1),
        )
    return (
        _first_weekday_of_month(year, 4, 6, 1),
        _last_weekday_of_month(year, 10, 6),
    )


def _calendar_alignment(
    market: pd.DataFrame, source: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    values = _numeric(
        source,
        (
            "weekday",
            "month",
            "quarter",
            "session_of_month",
            "sessions_remaining_month",
            "is_standard_expiry",
            "is_quarterly_expiry",
            "sessions_until_standard_expiry",
        ),
        label="calendar",
    )
    aligned = _align_panel(market, source, label="calendar")
    return aligned, values


def _f237(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["calendar"]
    aligned, _ = _calendar_alignment(market, source)
    dates = market["date"]
    day_of_year = dates.dt.dayofyear.astype(float)
    latitude = np.deg2rad(40.7769)
    declination = np.deg2rad(
        23.44 * np.sin(2.0 * np.pi * (284.0 + day_of_year) / 365.25)
    )
    hour_angle = np.arccos(
        np.clip(-np.tan(latitude) * np.tan(declination), -1.0, 1.0)
    )
    daylight = pd.Series(8.0 * np.rad2deg(hour_angle), index=market.index)
    starts: list[pd.Timestamp] = []
    ends: list[pd.Timestamp] = []
    for year in sorted(dates.dt.year.unique()):
        start, end = _dst_boundaries(int(year))
        starts.append(start)
        ends.append(end)
    transition_dates = pd.DatetimeIndex(sorted([*starts, *ends]))
    is_dst: list[float] = []
    distance: list[float] = []
    direction: list[float] = []
    for date in dates:
        start, end = _dst_boundaries(int(date.year))
        is_dst.append(float(start <= date < end))
        deltas = (transition_dates - date).days
        nearest_position = int(np.argmin(np.abs(deltas)))
        distance.append(float(deltas[nearest_position]))
        nearest = transition_dates[nearest_position]
        direction.append(1.0 if nearest.month in (3, 4) else -1.0)
    distance_series = pd.Series(distance, index=market.index)
    choices = {
        "daylight_minutes": daylight,
        "daylight_change": daylight.diff(),
        "is_dst": pd.Series(is_dst, index=market.index),
        "dst_transition_window": distance_series.abs().le(5.0).astype(float),
        "days_to_dst_transition": distance_series,
        "clock_change_direction": (
            pd.Series(direction, index=market.index)
            * distance_series.abs().le(5.0).astype(float)
        ),
    }
    return _daily_choice(
        market,
        [("calendar", aligned)],
        choices,
        parameters,
        default="daylight_change",
    )


def _f238(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["calendar"]
    aligned, values = _calendar_alignment(market, source)
    dates = source["date"]
    first_month = values["session_of_month"].le(3)
    last_month = values["sessions_remaining_month"].le(3)
    turn_month = (first_month | last_month).astype(float)
    turn_quarter = (
        (first_month & dates.dt.month.isin([1, 4, 7, 10]))
        | (last_month & dates.dt.month.isin([3, 6, 9, 12]))
    ).astype(float)
    turn_year = (
        (first_month & dates.dt.month.eq(1))
        | (last_month & dates.dt.month.eq(12))
    ).astype(float)
    previous_gap = dates.diff().dt.days.astype(float)
    next_gap = dates.shift(-1).sub(dates).dt.days.astype(float)
    pre_holiday = next_gap.gt(3.0).astype(float)
    post_holiday = previous_gap.gt(3.0).astype(float)
    choices = {
        "turn_of_month": turn_month,
        "turn_of_quarter": turn_quarter,
        "turn_of_year": turn_year,
        "pre_holiday": pre_holiday,
        "post_holiday": post_holiday,
        "standard_expiry": values["is_standard_expiry"],
        "quarterly_expiry": values["is_quarterly_expiry"],
        "sessions_until_expiry": values["sessions_until_standard_expiry"],
    }
    daily_choices = {
        name: aligned["date"].map(pd.Series(value.to_numpy(), index=dates))
        for name, value in choices.items()
    }
    return _daily_choice(
        market,
        [("calendar", aligned)],
        daily_choices,
        parameters,
        default="turn_of_month",
    )


def _general_election(year: int) -> pd.Timestamp:
    november = pd.Timestamp(year=year, month=11, day=1)
    first_monday = november + pd.Timedelta(days=(0 - november.weekday()) % 7)
    return first_monday + pd.Timedelta(days=1)


def _f239(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["calendar"]
    aligned, _ = _calendar_alignment(market, source)
    dates = market["date"]
    cycle_year = dates.dt.year.mod(4).astype(float)
    election_dates = pd.Series(
        [_general_election(int(year)) for year in dates.dt.year], index=market.index
    )
    distance = (election_dates - dates).dt.days.astype(float)
    angle = 2.0 * np.pi * cycle_year / 4.0
    choices = {
        "presidential_cycle_year": cycle_year,
        "election_year": cycle_year.eq(0.0).astype(float),
        "midterm_year": cycle_year.eq(2.0).astype(float),
        "days_to_general_election": distance,
        "absolute_election_distance": distance.abs(),
        "pre_election_window": distance.between(0.0, 90.0).astype(float),
        "post_election_window": distance.between(-90.0, -1.0).astype(float),
        "cycle_sine": np.sin(angle),
        "cycle_cosine": np.cos(angle),
    }
    return _daily_choice(
        market,
        [("calendar", aligned)],
        choices,
        parameters,
        default="days_to_general_election",
    )


def _event_pulse(
    market: pd.DataFrame,
    source: pd.DataFrame,
    value: pd.Series,
) -> pd.Series:
    grouped = pd.Series(value.to_numpy(), index=source["date"]).groupby(level=0).sum()
    return market["date"].map(grouped).fillna(0.0).astype(float)


def _f240(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    window = _positive(parameters, "window", 20)
    philly = panels["philly"]
    announcements = panels["announcements"]
    fomc = panels["fomc_documents"]
    calendar = panels["calendar"]
    philly_values = _numeric(philly, ("vintage_count",), label="philly")
    auction_values = _numeric(
        announcements, ("announcement_count",), label="announcements"
    )
    fomc_values = _numeric(fomc, ("document_count",), label="fomc_documents")
    calendar_values = _numeric(
        calendar,
        (
            "session_of_month",
            "sessions_remaining_month",
            "is_standard_expiry",
            "is_quarterly_expiry",
        ),
        label="calendar",
    )
    macro_pulse = _event_pulse(market, philly, philly_values["vintage_count"])
    auction_pulse = _event_pulse(
        market, announcements, auction_values["announcement_count"]
    )
    policy_pulse = _event_pulse(market, fomc, fomc_values["document_count"])
    calendar_event = (
        calendar_values["session_of_month"].le(1)
        | calendar_values["sessions_remaining_month"].le(1)
        | calendar_values["is_standard_expiry"].gt(0.0)
        | calendar_values["is_quarterly_expiry"].gt(0.0)
    ).astype(float)
    calendar_pulse = _event_pulse(market, calendar, calendar_event)
    pulses = pd.DataFrame(
        {
            "macro": macro_pulse,
            "policy": policy_pulse,
            "auction": auction_pulse,
            "calendar": calendar_pulse,
        }
    )
    rolling = pulses.rolling(window, min_periods=window).sum()
    total = rolling.sum(axis=1)
    shares = rolling.div(total.replace(0.0, np.nan), axis=0)
    breadth = rolling.gt(0.0).sum(axis=1).astype(float)
    concentration = shares.pow(2).sum(axis=1)
    weighted = (
        2.0 * rolling["macro"]
        + 3.0 * rolling["policy"]
        + rolling["auction"]
        + 0.5 * rolling["calendar"]
    )
    choices = {
        "total_event_count": pulses.sum(axis=1),
        "rolling_event_density": total,
        "type_weighted_density": weighted,
        "event_breadth": breadth,
        "event_concentration": concentration,
        "macro_policy_overlap": (
            rolling["macro"] * rolling["policy"] / float(window * window)
        ),
        "public_arrival_pressure": weighted * concentration,
    }
    alignments = [
        ("philly", _align_panel(market, philly, label="philly")),
        (
            "announcements",
            _align_panel(market, announcements, label="announcements"),
        ),
        ("fomc_documents", _align_panel(market, fomc, label="fomc_documents")),
        ("calendar", _align_panel(market, calendar, label="calendar")),
    ]
    return _daily_choice(
        market,
        alignments,
        choices,
        parameters,
        default="public_arrival_pressure",
    )


_LANE_KERNELS: Mapping[
    str,
    Callable[[pd.DataFrame, Mapping[str, pd.DataFrame], Mapping[str, Any]], pd.DataFrame],
] = {
    "F231": _f231,
    "F232": _f232,
    "F233": _f233,
    "F234": _f234,
    "F235": _f235,
    "F236": _f236,
    "F237": _f237,
    "F238": _f238,
    "F239": _f239,
    "F240": _f240,
}


def evaluate_public_context_lane(
    lane_id: str,
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F231-F240 lane using only train-safe inputs."""

    if lane_id not in _LANE_KERNELS:
        raise PublicContextFeatureEngineError(f"UNKNOWN_LANE:{lane_id}")
    validated_market = _validated(market, label="market")
    required = _LANE_SOURCES[lane_id]
    missing = sorted(set(required) - set(panels))
    if missing:
        raise PublicContextFeatureEngineError(
            f"SOURCE_PANEL_MISSING:{lane_id}:{','.join(missing)}"
        )
    validated_panels = {
        name: _validated(panels[name], label=name) for name in required
    }
    return _LANE_KERNELS[lane_id](validated_market, validated_panels, parameters)


def evaluate_public_context_family_batch(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate one representative preregistered configuration per lane."""

    defaults: Mapping[str, str] = {
        "F231": "clustering_breadth",
        "F232": "cluster_pressure",
        "F233": "mix_entropy",
        "F234": "divergence_zscore",
        "F235": "visibility",
        "F236": "temperature_anomaly",
        "F237": "daylight_change",
        "F238": "turn_of_month",
        "F239": "days_to_general_election",
        "F240": "public_arrival_pressure",
    }
    return {
        lane: evaluate_public_context_lane(
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
        for lane, statistic in defaults.items()
    }


__all__ = [
    "PublicContextFeatureEngineError",
    "evaluate_public_context_family_batch",
    "evaluate_public_context_lane",
]

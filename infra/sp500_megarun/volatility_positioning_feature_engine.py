"""Causal train-only volatility and positioning kernels for F211-F220."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


class VolatilityPositioningFeatureEngineError(ValueError):
    """Raised when F211-F220 violate the frozen train contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F211": ("vol",),
    "F212": ("vol",),
    "F213": ("vol",),
    "F214": ("vol",),
    "F215": ("fallback",),
    "F216": ("fallback",),
    "F217": ("cftc",),
    "F218": ("cftc",),
    "F219": ("cftc",),
    "F220": ("cftc",),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise VolatilityPositioningFeatureEngineError(
            f"TIMESTAMP_COLUMNS_MISSING:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result.loc[:, list(_TIMESTAMPS)].isna().any().any():
        raise VolatilityPositioningFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(_TRAIN_END).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise VolatilityPositioningFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise VolatilityPositioningFeatureEngineError(
            f"OBSERVED_AFTER_AVAILABILITY:{label}"
        )
    if result["available_at"].gt(result["date"]).any():
        raise VolatilityPositioningFeatureEngineError(
            f"AVAILABLE_AFTER_PANEL_DATE:{label}"
        )
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise VolatilityPositioningFeatureEngineError(
            f"DATES_NOT_STRICTLY_ORDERED:{label}"
        )
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise VolatilityPositioningFeatureEngineError(
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
        raise VolatilityPositioningFeatureEngineError(
            f"UNKNOWN_PARAMETER:{name}:{value}"
        )
    return value


def _numeric(frame: pd.DataFrame, columns: Sequence[str], *, label: str) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise VolatilityPositioningFeatureEngineError(
            f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}"
        )
    return (
        frame.loc[:, list(columns)]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )


def _rolling_zscore(value: pd.Series, window: int) -> pd.Series:
    mean = value.rolling(window, min_periods=window).mean()
    scale = value.rolling(window, min_periods=window).std(ddof=0)
    return (value - mean) / scale.replace(0.0, np.nan)


def _rolling_percentile(value: pd.Series, window: int) -> pd.Series:
    return value.rolling(window, min_periods=window).apply(
        lambda sample: float((sample <= sample[-1]).mean()),
        raw=True,
    )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0.0, np.nan)


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
    right = panel.rename(
        columns={
            "date": "source_date",
            "observed_at": "source_observed_at",
            "available_at": "source_available_at",
        }
    )
    aligned = pd.merge_asof(
        market.loc[:, ["date"]],
        right.loc[
            :,
            ["source_date", "source_observed_at", "source_available_at", *values],
        ].sort_values("source_date", kind="mergesort"),
        left_on="date",
        right_on="source_date",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="source_date")
    if aligned["source_available_at"].gt(aligned["date"]).fillna(False).any():
        raise VolatilityPositioningFeatureEngineError(
            f"FORWARD_FILLED_FUTURE_INPUT:{label}"
        )
    return aligned


def _market_output(
    market: pd.DataFrame,
    aligned: pd.DataFrame,
    value: pd.Series,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": aligned["source_observed_at"].fillna(market["observed_at"]),
            "available_at": aligned["source_available_at"].fillna(
                market["available_at"]
            ),
            "value": pd.to_numeric(value, errors="coerce").replace(
                [np.inf, -np.inf], np.nan
            ),
        }
    )


def _event_output(
    market: pd.DataFrame,
    source: pd.DataFrame,
    value: pd.Series,
    *,
    label: str,
) -> pd.DataFrame:
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["value"] = pd.to_numeric(value, errors="coerce")
    aligned = _align_panel(market, derived, label=label)
    return _market_output(market, aligned, aligned["value"])


def _event_lane(
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
    value = _direction(
        _normalize(choices[statistic], parameters, window=window), parameters
    )
    return _event_output(market, source, value, label=label)


def _vol_state(
    market: pd.DataFrame, panel: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    aligned = _align_panel(market, panel, label="vol")
    values = _numeric(aligned, ("vix_close", "vxo_close"), label="vol")
    values = values.where(values.gt(0.0)).ffill(limit=5)
    return aligned, values


def _daily_lane(
    market: pd.DataFrame,
    aligned: pd.DataFrame,
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
    return _market_output(market, aligned, value)


def _f211(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned, values = _vol_state(market, panels["vol"])
    vix = values["vix_close"]
    window = _positive(parameters, "window", 20)
    lag = _positive(parameters, "lag", 5)
    choices = {
        "vix_level": vix,
        "vix_log_level": np.log(vix),
        "vix_trend": np.log(vix).diff(lag),
        "vix_zscore": _rolling_zscore(vix, window),
        "vix_percentile": _rolling_percentile(vix, window),
        "vix_vxo_spread": vix - values["vxo_close"],
    }
    return _daily_lane(
        market, aligned, choices, parameters, default="vix_percentile"
    )


def _f212(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned, values = _vol_state(market, panels["vol"])
    change = np.log(values["vix_close"]).diff()
    window = _positive(parameters, "window", 20)
    vol_of_vol = change.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(252.0)
    positive = change.clip(lower=0.0)
    negative = change.clip(upper=0.0)
    choices = {
        "vol_of_vol": vol_of_vol,
        "mean_abs_change": change.abs().rolling(window, min_periods=window).mean(),
        "positive_shock_vol": np.sqrt(
            252.0 * positive.pow(2).rolling(window, min_periods=window).mean()
        ),
        "negative_shock_vol": np.sqrt(
            252.0 * negative.pow(2).rolling(window, min_periods=window).mean()
        ),
        "vol_of_vol_zscore": _rolling_zscore(vol_of_vol, window),
    }
    return _daily_lane(market, aligned, choices, parameters, default="vol_of_vol")


def _f213(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned, values = _vol_state(market, panels["vol"])
    close = _numeric(market, ("close",), label="market")["close"].where(
        lambda value: value.gt(0.0)
    )
    realized_window = _positive(parameters, "realized_window", 20)
    window = _positive(parameters, "window", 63)
    returns = np.log(close).diff()
    realized = 252.0 * returns.pow(2).rolling(
        realized_window, min_periods=realized_window
    ).mean()
    implied = (values["vix_close"] / 100.0).pow(2)
    spread = implied - realized
    ratio = _safe_ratio(implied, realized)
    choices = {
        "implied_variance": implied,
        "realized_variance": realized,
        "variance_spread": spread,
        "variance_ratio": ratio,
        "log_variance_ratio": np.log(ratio.where(ratio.gt(0.0))),
        "spread_zscore": _rolling_zscore(spread, window),
    }
    return _daily_lane(
        market, aligned, choices, parameters, default="variance_spread"
    )


def _f214(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned, values = _vol_state(market, panels["vol"])
    vix = values["vix_close"]
    log_vix = np.log(vix)
    change = log_vix.diff()
    window = _positive(parameters, "window", 63)
    lag = _positive(parameters, "lag", 5)
    tail = float(parameters.get("tail", 0.9))
    if not 0.5 < tail < 1.0:
        raise VolatilityPositioningFeatureEngineError(f"INVALID_TAIL:{tail}")
    threshold = vix.rolling(window, min_periods=window).quantile(tail).shift(1)
    shock = vix.gt(threshold) & threshold.notna()
    groups = (~shock).cumsum()
    duration = shock.astype(float).groupby(groups).cumsum()
    peak = vix.rolling(window, min_periods=window).max()
    choices = {
        "shock_magnitude": change.clip(lower=0.0),
        "shock_indicator": shock.astype(float).where(threshold.notna()),
        "shock_duration": duration.where(threshold.notna()),
        "distance_from_peak": _safe_ratio(vix, peak) - 1.0,
        "normalization_speed": -log_vix.diff(lag) / float(lag),
        "tail_percentile": _rolling_percentile(vix, window),
    }
    return _daily_lane(
        market, aligned, choices, parameters, default="shock_duration"
    )


def _f215(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["fallback"]
    values = _numeric(
        source,
        ("commercial_breadth", "noncommercial_breadth", "breadth_gap"),
        label="fallback",
    )
    window = _positive(parameters, "window", 26)
    lag = _positive(parameters, "lag", 1)
    choices = {
        "commercial_breadth": values["commercial_breadth"],
        "noncommercial_breadth": values["noncommercial_breadth"],
        "breadth_gap": values["breadth_gap"],
        "breadth_trend": values["commercial_breadth"].diff(lag),
        "breadth_zscore": _rolling_zscore(values["commercial_breadth"], window),
    }
    return _event_lane(
        market, source, choices, parameters, default="commercial_breadth", label="f215"
    )


def _f216(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["fallback"]
    values = _numeric(
        source,
        ("positioning_disagreement", "commercial_dispersion", "breadth_gap"),
        label="fallback",
    )
    window = _positive(parameters, "window", 26)
    lag = _positive(parameters, "lag", 1)
    disagreement_z = _rolling_zscore(values["positioning_disagreement"], window)
    dispersion_z = _rolling_zscore(values["commercial_dispersion"], window)
    choices = {
        "positioning_disagreement": values["positioning_disagreement"],
        "disagreement_change": values["positioning_disagreement"].diff(lag),
        "disagreement_zscore": disagreement_z,
        "commercial_dispersion": values["commercial_dispersion"],
        "dispersion_zscore": dispersion_z,
        "reversal_pressure": disagreement_z
        - _rolling_zscore(values["breadth_gap"], window),
    }
    return _event_lane(
        market, source, choices, parameters, default="disagreement_zscore", label="f216"
    )


def _cftc_values(source: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    return _numeric(source, columns, label="cftc").ffill()


def _f217(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["cftc"]
    values = _cftc_values(source, ("commercial_net_pct_oi", "open_interest"))
    commercial = values["commercial_net_pct_oi"]
    window = _positive(parameters, "window", 26)
    lag = _positive(parameters, "lag", 1)
    oi_z = _rolling_zscore(np.log(values["open_interest"].where(lambda x: x.gt(0.0))), window)
    choices = {
        "commercial_net": commercial,
        "commercial_change": commercial.diff(lag),
        "commercial_zscore": _rolling_zscore(commercial, window),
        "commercial_percentile": _rolling_percentile(commercial, window),
        "commercial_open_interest_interaction": commercial * oi_z,
    }
    return _event_lane(
        market, source, choices, parameters, default="commercial_net", label="f217"
    )


def _f218(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["cftc"]
    values = _cftc_values(
        source,
        (
            "noncommercial_net_pct_oi",
            "noncommercial_short_pct_oi",
            "noncommercial_spreading_pct_oi",
        ),
    )
    noncommercial = values["noncommercial_net_pct_oi"]
    spreading = values["noncommercial_spreading_pct_oi"]
    choices = {
        "noncommercial_net": noncommercial,
        "noncommercial_short": values["noncommercial_short_pct_oi"],
        "spreading_share": spreading,
        "noncommercial_change": noncommercial.diff(_positive(parameters, "lag", 1)),
        "speculative_pressure": noncommercial - spreading,
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="speculative_pressure",
        label="f218",
    )


def _f219(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["cftc"]
    values = _cftc_values(
        source,
        (
            "commercial_net_pct_oi",
            "commercial_net_pct_oi_combined",
            "noncommercial_net_pct_oi",
            "noncommercial_net_pct_oi_combined",
            "open_interest",
            "open_interest_combined",
            "noncommercial_spreading_pct_oi",
            "noncommercial_spreading_pct_oi_combined",
            "top4_net_concentration",
            "top4_net_concentration_combined",
        ),
    )
    choices = {
        "commercial_mode_difference": values["commercial_net_pct_oi"]
        - values["commercial_net_pct_oi_combined"],
        "noncommercial_mode_difference": values["noncommercial_net_pct_oi"]
        - values["noncommercial_net_pct_oi_combined"],
        "option_open_interest_share": (
            values["open_interest_combined"] - values["open_interest"]
        )
        / values["open_interest_combined"].replace(0.0, np.nan),
        "spreading_mode_difference": values["noncommercial_spreading_pct_oi_combined"]
        - values["noncommercial_spreading_pct_oi"],
        "concentration_mode_difference": values["top4_net_concentration_combined"]
        - values["top4_net_concentration"],
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="commercial_mode_difference",
        label="f219",
    )


def _f220(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["cftc"]
    values = _cftc_values(
        source,
        (
            "open_interest",
            "trader_count",
            "top4_net_concentration",
            "top8_net_concentration",
        ),
    )
    open_interest = values["open_interest"]
    trader_count = values["trader_count"]
    top4 = values["top4_net_concentration"]
    top8 = values["top8_net_concentration"]
    window = _positive(parameters, "window", 26)
    crowding = pd.concat(
        (
            _rolling_zscore(open_interest.pct_change(fill_method=None), window),
            _rolling_zscore(top4.abs(), window),
            _rolling_zscore(top8.abs(), window),
        ),
        axis=1,
    ).mean(axis=1)
    choices = {
        "open_interest": open_interest,
        "open_interest_growth": open_interest.pct_change(fill_method=None),
        "trader_count": trader_count,
        "trader_count_growth": trader_count.pct_change(fill_method=None),
        "top4_net_concentration": top4,
        "top8_net_concentration": top8,
        "concentration_gap": top8 - top4,
        "crowding_composite": crowding,
    }
    return _event_lane(
        market,
        source,
        choices,
        parameters,
        default="crowding_composite",
        label="f220",
    )


_LANE_KERNELS: Mapping[
    str,
    Callable[[pd.DataFrame, Mapping[str, pd.DataFrame], Mapping[str, Any]], pd.DataFrame],
] = {
    "F211": _f211,
    "F212": _f212,
    "F213": _f213,
    "F214": _f214,
    "F215": _f215,
    "F216": _f216,
    "F217": _f217,
    "F218": _f218,
    "F219": _f219,
    "F220": _f220,
}


def evaluate_volatility_positioning_lane(
    lane_id: str,
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one F211-F220 lane using only released train rows."""

    if lane_id not in _LANE_KERNELS:
        raise VolatilityPositioningFeatureEngineError(f"UNKNOWN_LANE:{lane_id}")
    validated_market = _validated(market, label="market")
    required = _LANE_SOURCES[lane_id]
    missing = sorted(set(required) - set(panels))
    if missing:
        raise VolatilityPositioningFeatureEngineError(
            f"SOURCE_PANEL_MISSING:{lane_id}:{','.join(missing)}"
        )
    validated_panels = {
        name: _validated(panels[name], label=name) for name in required
    }
    return _LANE_KERNELS[lane_id](validated_market, validated_panels, parameters)


def evaluate_volatility_positioning_family_batch(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate one representative preregistered configuration per lane."""

    defaults: Mapping[str, str] = {
        "F211": "vix_percentile",
        "F212": "vol_of_vol",
        "F213": "variance_spread",
        "F214": "shock_duration",
        "F215": "commercial_breadth",
        "F216": "disagreement_zscore",
        "F217": "commercial_net",
        "F218": "speculative_pressure",
        "F219": "commercial_mode_difference",
        "F220": "crowding_composite",
    }
    return {
        lane: evaluate_volatility_positioning_lane(
            lane,
            market,
            panels,
            {
                "statistic": statistic,
                "window": 63 if lane <= "F214" else 26,
                "realized_window": 20,
                "lag": 5 if lane <= "F214" else 1,
                "tail": 0.9,
                "change_lag": 1,
                "normalization": "raw",
                "direction": "continuation",
            },
        )
        for lane, statistic in defaults.items()
    }


__all__ = [
    "VolatilityPositioningFeatureEngineError",
    "evaluate_volatility_positioning_family_batch",
    "evaluate_volatility_positioning_lane",
]

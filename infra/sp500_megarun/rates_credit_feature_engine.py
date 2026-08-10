"""Causal rates, credit and monetary kernels for SP500 lanes F181-F190."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


class RatesCreditFeatureEngineError(ValueError):
    """Raised when a rates/credit input or parameter breaks the frozen contract."""


_TRAIN_END = pd.Timestamp("2010-12-31")
_TIMESTAMPS = ("date", "observed_at", "available_at")
_LANE_SOURCES: Mapping[str, tuple[str, ...]] = {
    "F181": ("rates",),
    "F182": ("rates",),
    "F183": ("spf_real_rate",),
    "F184": ("rates", "credit"),
    "F185": ("cp",),
    "F186": ("bank",),
    "F187": ("money",),
    "F188": ("consumer",),
    "F189": ("rates", "credit", "cp", "bank", "money", "vol"),
    "F190": ("credit", "cp", "bank", "money", "vol"),
}


def _validated(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = sorted(set(_TIMESTAMPS) - set(frame.columns))
    if missing:
        raise RatesCreditFeatureEngineError(
            f"MISSING_TIMESTAMP_COLUMNS:{label}:{','.join(missing)}"
        )
    result = frame.copy()
    for column in _TIMESTAMPS:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    if result[list(_TIMESTAMPS)].isna().any().any():
        raise RatesCreditFeatureEngineError(f"INVALID_TIMESTAMPS:{label}")
    if result["date"].gt(_TRAIN_END).any() or result["available_at"].gt(_TRAIN_END).any():
        kind = "MARKET_ROW" if label == "market" else f"PANEL_ROW:{label}"
        raise RatesCreditFeatureEngineError(f"NON_TRAIN_{kind}")
    if result["observed_at"].gt(result["available_at"]).any():
        raise RatesCreditFeatureEngineError(f"OBSERVED_AFTER_AVAILABILITY:{label}")
    if result["available_at"].gt(result["date"]).any():
        raise RatesCreditFeatureEngineError(f"AVAILABLE_AFTER_PANEL_DATE:{label}")
    if result["date"].duplicated().any() or not result["date"].is_monotonic_increasing:
        raise RatesCreditFeatureEngineError(f"DATES_NOT_STRICTLY_ORDERED:{label}")
    return result.reset_index(drop=True)


def _positive(parameters: Mapping[str, Any], name: str, default: int) -> int:
    value = int(parameters.get(name, default))
    if value < 1:
        raise RatesCreditFeatureEngineError(f"INVALID_POSITIVE_PARAMETER:{name}:{value}")
    return value


def _choice(
    parameters: Mapping[str, Any],
    name: str,
    choices: Sequence[str],
    default: str,
) -> str:
    value = str(parameters.get(name, default))
    if value not in choices:
        raise RatesCreditFeatureEngineError(f"UNKNOWN_PARAMETER:{name}:{value}")
    return value


def _direction(value: pd.Series, parameters: Mapping[str, Any]) -> pd.Series:
    direction = _choice(parameters, "direction", ("continuation", "reversal"), "continuation")
    return value if direction == "continuation" else -value


def _numeric_matrix(
    frame: pd.DataFrame,
    *,
    columns: Sequence[str],
    label: str,
) -> pd.DataFrame:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise RatesCreditFeatureEngineError(f"PANEL_VALUE_MISSING:{label}:{','.join(missing)}")
    return (
        frame.loc[:, list(columns)]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )


def _align_panel(
    market: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    label: str,
) -> pd.DataFrame:
    value_columns = [column for column in panel if column not in _TIMESTAMPS]
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
            [
                "source_date",
                "source_observed_at",
                "source_available_at",
                *value_columns,
            ],
        ].sort_values("source_date", kind="mergesort"),
        left_on="date",
        right_on="source_date",
        direction="backward",
        allow_exact_matches=True,
    ).drop(columns="source_date")
    if aligned["source_available_at"].gt(aligned["date"]).fillna(False).any():
        raise RatesCreditFeatureEngineError(f"FORWARD_FILLED_FUTURE_INPUT:{label}")
    return aligned


def _output(
    market: pd.DataFrame,
    value: pd.Series,
    aligned: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    observed = pd.concat([panel["source_observed_at"] for panel in aligned], axis=1).max(axis=1)
    available = pd.concat([panel["source_available_at"] for panel in aligned], axis=1).max(axis=1)
    return pd.DataFrame(
        {
            "date": market["date"],
            "observed_at": observed.fillna(market["observed_at"]),
            "available_at": available.fillna(market["available_at"]),
            "value": pd.to_numeric(value, errors="coerce").replace([np.inf, -np.inf], np.nan),
        }
    )


def _align_derived(
    market: pd.DataFrame,
    source: pd.DataFrame,
    value: pd.Series,
    *,
    label: str,
) -> pd.DataFrame:
    derived = source.loc[:, list(_TIMESTAMPS)].copy()
    derived["value"] = pd.to_numeric(value, errors="coerce")
    aligned = _align_panel(market, derived, label=label)
    return _output(market, aligned["value"], (aligned,))


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
    normalization = _choice(
        parameters,
        "normalization",
        ("raw", "change", "rolling_zscore"),
        "raw",
    )
    if normalization == "change":
        return value.diff(_positive(parameters, "change_lag", 20))
    if normalization == "rolling_zscore":
        return _rolling_zscore(value, window)
    return value


def _log_change(value: pd.Series, lag: int) -> pd.Series:
    return np.log(value.where(value.gt(0.0))).diff(lag)


def _f181(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    rates = _align_panel(market, panels["rates"], label="rates")
    curve = _numeric_matrix(
        rates,
        columns=("yield_3m", "yield_2y", "yield_5y", "yield_10y", "yield_20y"),
        label="rates",
    )
    statistic = _choice(
        parameters,
        "statistic",
        ("level", "slope_10y_3m", "curvature_2_5_10", "long_curvature_5_10_20"),
        "slope_10y_3m",
    )
    choices = {
        "level": curve["yield_10y"],
        "slope_10y_3m": curve["yield_10y"] - curve["yield_3m"],
        "curvature_2_5_10": 2.0 * curve["yield_5y"] - curve["yield_2y"] - curve["yield_10y"],
        "long_curvature_5_10_20": 2.0 * curve["yield_10y"] - curve["yield_5y"] - curve["yield_20y"],
    }
    value = _normalize(
        choices[statistic],
        parameters,
        window=_positive(parameters, "window", 126),
    )
    return _output(market, _direction(value, parameters), (rates,))


def _f182(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    rates = _align_panel(market, panels["rates"], label="rates")
    curve = _numeric_matrix(
        rates,
        columns=("yield_2y", "yield_5y", "yield_10y"),
        label="rates",
    )
    forward_2y5y = (5.0 * curve["yield_5y"] - 2.0 * curve["yield_2y"]) / 3.0
    forward_5y10y = (10.0 * curve["yield_10y"] - 5.0 * curve["yield_5y"]) / 5.0
    slope = curve["yield_10y"] - curve["yield_2y"]
    statistic = _choice(
        parameters,
        "statistic",
        ("forward_2y5y", "forward_5y10y", "forward_slope", "butterfly", "slope_shock"),
        "forward_slope",
    )
    choices = {
        "forward_2y5y": forward_2y5y,
        "forward_5y10y": forward_5y10y,
        "forward_slope": forward_5y10y - forward_2y5y,
        "butterfly": 2.0 * curve["yield_5y"] - curve["yield_2y"] - curve["yield_10y"],
        "slope_shock": slope.diff(_positive(parameters, "shock_lag", 20)),
    }
    value = _normalize(
        choices[statistic],
        parameters,
        window=_positive(parameters, "window", 126),
    )
    return _output(market, _direction(value, parameters), (rates,))


def _f183(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    source = panels["spf_real_rate"]
    values = _numeric_matrix(
        source,
        columns=("real_rate_cpi", "real_rate_pce", "real_rate_pgdp"),
        label="spf_real_rate",
    )
    basis = _choice(parameters, "inflation_basis", ("cpi", "pce", "pgdp", "median"), "median")
    bases = {
        "cpi": values["real_rate_cpi"],
        "pce": values["real_rate_pce"],
        "pgdp": values["real_rate_pgdp"],
        "median": values.median(axis=1, skipna=True),
    }
    base = bases[basis]
    window = _positive(parameters, "window", 8)
    statistic = _choice(
        parameters,
        "statistic",
        ("level", "change", "dispersion", "tightness"),
        "level",
    )
    choices = {
        "level": base,
        "change": base.diff(window),
        "dispersion": values.std(axis=1, ddof=0),
        "tightness": _rolling_zscore(base, window),
    }
    value = _direction(choices[statistic], parameters)
    return _align_derived(market, source, value, label="spf_real_rate")


def _f184(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    rates = _align_panel(market, panels["rates"], label="rates")
    credit = _align_panel(market, panels["credit"], label="credit")
    yields = _numeric_matrix(
        credit,
        columns=("aaa_yield", "baa_yield", "baa_aaa_spread"),
        label="credit",
    )
    treasury = _numeric_matrix(rates, columns=("yield_10y",), label="rates")["yield_10y"]
    baa_aaa = yields["baa_aaa_spread"]
    aaa_treasury = yields["aaa_yield"] - treasury
    baa_treasury = yields["baa_yield"] - treasury
    statistic = _choice(
        parameters,
        "statistic",
        ("baa_aaa", "aaa_treasury", "baa_treasury", "credit_stress_composite"),
        "baa_aaa",
    )
    window = _positive(parameters, "window", 126)
    choices = {
        "baa_aaa": baa_aaa,
        "aaa_treasury": aaa_treasury,
        "baa_treasury": baa_treasury,
        "credit_stress_composite": pd.concat(
            [
                _rolling_zscore(baa_aaa, window),
                _rolling_zscore(aaa_treasury, window),
                _rolling_zscore(baa_treasury, window),
            ],
            axis=1,
        ).mean(axis=1),
    }
    value = _normalize(choices[statistic], parameters, window=window)
    return _output(market, _direction(value, parameters), (rates, credit))


def _f185(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    cp = _align_panel(market, panels["cp"], label="cp")
    values = _numeric_matrix(
        cp,
        columns=(
            "aa_nonfinancial_90d",
            "a2p2_nonfinancial_90d",
            "aa_financial_90d",
            "cp_outstanding",
            "issuance_amount",
        ),
        label="cp",
    )
    lag = _positive(parameters, "lag", 20)
    window = _positive(parameters, "window", 126)
    quality = values["a2p2_nonfinancial_90d"] - values["aa_nonfinancial_90d"]
    financial = values["aa_financial_90d"] - values["aa_nonfinancial_90d"]
    contraction = -_log_change(values["cp_outstanding"], lag)
    issuance = values["issuance_amount"] / values["cp_outstanding"].replace(0.0, np.nan)
    components = pd.concat(
        [
            _rolling_zscore(quality, window),
            _rolling_zscore(financial, window),
            _rolling_zscore(contraction, window),
            _rolling_zscore(issuance, window),
        ],
        axis=1,
    )
    statistic = _choice(
        parameters,
        "statistic",
        (
            "quality_spread",
            "financial_spread",
            "outstanding_contraction",
            "issuance_intensity",
            "spread_volume_composite",
        ),
        "quality_spread",
    )
    choices = {
        "quality_spread": quality,
        "financial_spread": financial,
        "outstanding_contraction": contraction,
        "issuance_intensity": issuance,
        "spread_volume_composite": components.mean(axis=1, skipna=True),
    }
    value = _normalize(choices[statistic], parameters, window=window)
    return _output(market, _direction(value, parameters), (cp,))


def _f186(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    bank = _align_panel(market, panels["bank"], label="bank")
    values = _numeric_matrix(
        bank,
        columns=(
            "bank_credit",
            "securities",
            "loans",
            "ci_loans",
            "real_estate_loans",
            "consumer_loans",
        ),
        label="bank",
    )
    lag = _positive(parameters, "lag", 63)
    changes = values.apply(lambda series: _log_change(series, lag))
    statistic = _choice(
        parameters,
        "statistic",
        (
            "bank_credit_growth",
            "loan_growth",
            "loan_share",
            "credit_breadth",
            "composition_dispersion",
        ),
        "credit_breadth",
    )
    choices = {
        "bank_credit_growth": changes["bank_credit"],
        "loan_growth": changes["loans"],
        "loan_share": values["loans"] / values["bank_credit"].replace(0.0, np.nan),
        "credit_breadth": changes.gt(0.0).where(changes.notna()).mean(axis=1) - 0.5,
        "composition_dispersion": changes.loc[
            :, ["securities", "ci_loans", "real_estate_loans", "consumer_loans"]
        ].std(axis=1, ddof=0),
    }
    value = _normalize(
        choices[statistic],
        parameters,
        window=_positive(parameters, "window", 126),
    )
    return _output(market, _direction(value, parameters), (bank,))


def _f187(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    money = _align_panel(market, panels["money"], label="money")
    values = _numeric_matrix(
        money,
        columns=("m1", "m2", "monetary_base", "total_reserves", "fed_borrowings", "bank_credit"),
        label="money",
    )
    lag = _positive(parameters, "lag", 63)
    statistic = _choice(
        parameters,
        "statistic",
        (
            "money_growth",
            "liquid_share",
            "reserve_growth",
            "borrowing_pressure",
            "credit_money_ratio",
        ),
        "money_growth",
    )
    choices = {
        "money_growth": _log_change(values["m2"], lag),
        "liquid_share": values["m1"] / values["m2"].replace(0.0, np.nan),
        "reserve_growth": _log_change(values["total_reserves"], lag),
        "borrowing_pressure": np.log1p(values["fed_borrowings"].clip(lower=0.0))
        - np.log(values["total_reserves"].where(values["total_reserves"].gt(0.0))),
        "credit_money_ratio": values["bank_credit"] / values["m2"].replace(0.0, np.nan),
    }
    value = _normalize(
        choices[statistic],
        parameters,
        window=_positive(parameters, "window", 126),
    )
    return _output(market, _direction(value, parameters), (money,))


def _f188(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    consumer = _align_panel(market, panels["consumer"], label="consumer")
    values = _numeric_matrix(
        consumer,
        columns=("consumer_total", "consumer_revolving", "consumer_nonrevolving"),
        label="consumer",
    )
    lag = _positive(parameters, "lag", 63)
    window = _positive(parameters, "window", 126)
    total_growth = _log_change(values["consumer_total"], lag)
    revolving_growth = _log_change(values["consumer_revolving"], lag)
    nonrevolving_growth = _log_change(values["consumer_nonrevolving"], lag)
    revolving_share = values["consumer_revolving"] / values["consumer_total"].replace(0.0, np.nan)
    relative = revolving_growth - nonrevolving_growth
    stress = pd.concat(
        [
            _rolling_zscore(revolving_share, window),
            _rolling_zscore(relative, window),
            -_rolling_zscore(total_growth, window),
        ],
        axis=1,
    ).mean(axis=1)
    statistic = _choice(
        parameters,
        "statistic",
        (
            "total_growth",
            "revolving_growth",
            "revolving_share",
            "revolving_relative_growth",
            "consumer_credit_stress",
        ),
        "revolving_share",
    )
    choices = {
        "total_growth": total_growth,
        "revolving_growth": revolving_growth,
        "revolving_share": revolving_share,
        "revolving_relative_growth": relative,
        "consumer_credit_stress": stress,
    }
    value = _normalize(choices[statistic], parameters, window=window)
    return _output(market, _direction(value, parameters), (consumer,))


def _stress_components(
    aligned: Mapping[str, pd.DataFrame],
    *,
    window: int,
    change_lag: int,
) -> pd.DataFrame:
    rates = _numeric_matrix(aligned["rates"], columns=("yield_3m", "yield_10y"), label="rates")
    credit = _numeric_matrix(aligned["credit"], columns=("baa_aaa_spread",), label="credit")
    cp = _numeric_matrix(
        aligned["cp"],
        columns=("aa_nonfinancial_90d", "a2p2_nonfinancial_90d"),
        label="cp",
    )
    bank = _numeric_matrix(aligned["bank"], columns=("bank_credit",), label="bank")
    money = _numeric_matrix(
        aligned["money"], columns=("fed_borrowings", "total_reserves"), label="money"
    )
    vol = _numeric_matrix(aligned["vol"], columns=("vix_close", "vxo_close"), label="vol")
    vix = vol["vix_close"].combine_first(vol["vxo_close"])
    raw = {
        "curve": -(rates["yield_10y"] - rates["yield_3m"]),
        "credit": credit["baa_aaa_spread"],
        "cp": cp["a2p2_nonfinancial_90d"] - cp["aa_nonfinancial_90d"],
        "bank": -_log_change(bank["bank_credit"], change_lag),
        "money": np.log1p(money["fed_borrowings"].clip(lower=0.0))
        - np.log(money["total_reserves"].where(money["total_reserves"].gt(0.0))),
        "vol": vix,
    }
    return pd.DataFrame({name: _rolling_zscore(value, window) for name, value in raw.items()})


def _f189(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = {name: _align_panel(market, panel, label=name) for name, panel in panels.items()}
    stress = _stress_components(
        aligned,
        window=_positive(parameters, "window", 126),
        change_lag=_positive(parameters, "change_lag", 20),
    )
    statistic = _choice(
        parameters,
        "statistic",
        ("composite", "breadth", "max_stress", "dispersion"),
        "composite",
    )
    choices = {
        "composite": stress.mean(axis=1),
        "breadth": stress.gt(0.0).where(stress.notna()).mean(axis=1) - 0.5,
        "max_stress": stress.max(axis=1),
        "dispersion": stress.std(axis=1, ddof=0),
    }
    return _output(
        market,
        _direction(choices[statistic], parameters),
        tuple(aligned.values()),
    )


def _shock_components(
    aligned: Mapping[str, pd.DataFrame],
    *,
    window: int,
    shock_lag: int,
) -> pd.DataFrame:
    credit = _numeric_matrix(aligned["credit"], columns=("baa_aaa_spread",), label="credit")[
        "baa_aaa_spread"
    ]
    cp = _numeric_matrix(
        aligned["cp"],
        columns=("aa_nonfinancial_90d", "a2p2_nonfinancial_90d"),
        label="cp",
    )
    bank = _numeric_matrix(aligned["bank"], columns=("bank_credit",), label="bank")["bank_credit"]
    money = _numeric_matrix(aligned["money"], columns=("total_reserves",), label="money")[
        "total_reserves"
    ]
    vol = _numeric_matrix(aligned["vol"], columns=("vix_close", "vxo_close"), label="vol")
    vix = vol["vix_close"].combine_first(vol["vxo_close"])
    raw = {
        "vol": vix.diff(shock_lag),
        "credit": credit.diff(shock_lag),
        "cp": (cp["a2p2_nonfinancial_90d"] - cp["aa_nonfinancial_90d"]).diff(shock_lag),
        "bank": -_log_change(bank, shock_lag),
        "reserves": -_log_change(money, shock_lag),
    }
    return pd.DataFrame({name: _rolling_zscore(value, window) for name, value in raw.items()})


def _f190(
    market: pd.DataFrame,
    panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    aligned = {name: _align_panel(market, panel, label=name) for name, panel in panels.items()}
    window = _positive(parameters, "window", 63)
    shocks = _shock_components(
        aligned,
        window=window,
        shock_lag=_positive(parameters, "shock_lag", 5),
    )
    threshold = float(parameters.get("threshold", 1.0))
    if threshold < 0.0:
        raise RatesCreditFeatureEngineError(f"INVALID_THRESHOLD:{threshold}")
    exceedance = shocks.gt(threshold).where(shocks.notna()).mean(axis=1)
    statistic = _choice(
        parameters,
        "statistic",
        ("joint_mean", "joint_max", "shock_breadth", "triple_interaction", "persistence"),
        "joint_mean",
    )
    choices = {
        "joint_mean": shocks.mean(axis=1),
        "joint_max": shocks.max(axis=1),
        "shock_breadth": exceedance,
        "triple_interaction": shocks["vol"] * shocks["credit"] * shocks["bank"],
        "persistence": exceedance.rolling(window, min_periods=window).mean(),
    }
    return _output(
        market,
        _direction(choices[statistic], parameters),
        tuple(aligned.values()),
    )


_EVALUATORS = {
    "F181": _f181,
    "F182": _f182,
    "F183": _f183,
    "F184": _f184,
    "F185": _f185,
    "F186": _f186,
    "F187": _f187,
    "F188": _f188,
    "F189": _f189,
    "F190": _f190,
}
_DEFAULT_PARAMETERS: Mapping[str, Mapping[str, Any]] = {
    "F181": {
        "statistic": "slope_10y_3m",
        "window": 126,
        "normalization": "rolling_zscore",
        "direction": "continuation",
    },
    "F182": {
        "statistic": "forward_slope",
        "window": 126,
        "shock_lag": 20,
        "normalization": "rolling_zscore",
        "direction": "continuation",
    },
    "F183": {
        "statistic": "level",
        "inflation_basis": "median",
        "window": 8,
        "direction": "continuation",
    },
    "F184": {
        "statistic": "baa_aaa",
        "window": 126,
        "normalization": "rolling_zscore",
        "direction": "continuation",
    },
    "F185": {
        "statistic": "quality_spread",
        "window": 126,
        "lag": 20,
        "normalization": "rolling_zscore",
        "direction": "continuation",
    },
    "F186": {
        "statistic": "credit_breadth",
        "window": 126,
        "lag": 63,
        "normalization": "raw",
        "direction": "continuation",
    },
    "F187": {
        "statistic": "money_growth",
        "window": 126,
        "lag": 63,
        "normalization": "raw",
        "direction": "continuation",
    },
    "F188": {
        "statistic": "revolving_share",
        "window": 126,
        "lag": 63,
        "normalization": "rolling_zscore",
        "direction": "continuation",
    },
    "F189": {
        "statistic": "composite",
        "window": 126,
        "change_lag": 20,
        "direction": "continuation",
    },
    "F190": {
        "statistic": "joint_mean",
        "window": 63,
        "shock_lag": 5,
        "threshold": 1.0,
        "direction": "continuation",
    },
}


def evaluate_rates_credit_lane(
    lane_id: str,
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
    parameters: Mapping[str, Any],
) -> pd.DataFrame:
    """Evaluate one frozen F181-F190 lane using released train rows only."""

    if lane_id not in _EVALUATORS:
        raise RatesCreditFeatureEngineError(f"UNKNOWN_RATES_CREDIT_LANE:{lane_id}")
    market = _validated(market_frame, label="market")
    missing = [source for source in _LANE_SOURCES[lane_id] if source not in raw_panels]
    if missing:
        raise RatesCreditFeatureEngineError(
            f"MISSING_RATES_CREDIT_PANEL:{lane_id}:{','.join(missing)}"
        )
    panels = {
        source: _validated(raw_panels[source], label=source) for source in _LANE_SOURCES[lane_id]
    }
    return _EVALUATORS[lane_id](market, panels, parameters)


def evaluate_rates_credit_family_batch(
    market_frame: pd.DataFrame,
    raw_panels: Mapping[str, pd.DataFrame],
) -> Mapping[str, pd.DataFrame]:
    """Evaluate the ten frozen defaults in stable F181-F190 order."""

    return {
        lane: evaluate_rates_credit_lane(lane, market_frame, raw_panels, parameters)
        for lane, parameters in _DEFAULT_PARAMETERS.items()
    }


__all__ = [
    "RatesCreditFeatureEngineError",
    "evaluate_rates_credit_family_batch",
    "evaluate_rates_credit_lane",
]

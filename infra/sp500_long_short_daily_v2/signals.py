"""Exact causal implementations of the 24 frozen V2 signal families."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier

from aurora.infra.sp500_long_short_daily.data import PreparedMarketData
from aurora.infra.sp500_long_short_daily.signals import CandidateRejected, SignalResult
from aurora.infra.sp500_long_short_daily_v2.data import SECTOR_SYMBOLS

SEED = 20_260_805
IMPLEMENTED_FAMILIES = frozenset(
    {
        "overnight_intraday_tug", "gap_body_interaction", "close_location_pressure",
        "range_body_pressure", "range_volatility_ratio", "semivariance_balance",
        "skewness_state", "tail_imbalance", "volatility_of_volatility",
        "variance_ratio_switch", "autocorrelation_switch", "regression_trend_tstat",
        "fifty_two_week_state", "momentum_acceleration", "momentum_consistency",
        "signed_volume_pressure", "amihud_price_impact", "sector_etf_breadth",
        "cyclical_defensive_leadership", "cross_asset_etf_risk_appetite",
        "sector_dispersion_state", "equal_weight_concentration", "cusum_change_state",
        "causal_shallow_tree",
    }
)


@dataclass(frozen=True)
class FeatureStore:
    index: pd.DatetimeIndex
    open: pd.Series
    high: pd.Series
    low: pd.Series
    close: pd.Series
    volume: pd.Series
    log_return: pd.Series
    overnight: pd.Series
    intraday: pd.Series
    clv: pd.Series
    body: pd.Series
    parkinson: pd.Series
    etf_close: Mapping[str, pd.Series]

    @classmethod
    def build(cls, data: PreparedMarketData) -> "FeatureStore":
        index = data.ledger.index
        def s(name: str) -> pd.Series:
            if name not in data.series:
                raise CandidateRejected(f"MISSING_CAUSAL_SERIES:{name}")
            return data.series[name].reindex(index).astype(float)
        open_ = s("SPY::open")
        high = s("SPY::high")
        low = s("SPY::low")
        close = s("SPY::close")
        volume = s("SPY::volume")
        denominator = (high - low).replace(0.0, np.nan)
        clv = ((2.0 * close - high - low) / denominator).fillna(0.0)
        body = ((close - open_) / denominator).fillna(0.0)
        parkinson = np.log(high / low).pow(2) / (4.0 * np.log(2.0))
        etf = {
            key.split("::", 1)[0]: value.reindex(index).astype(float)
            for key, value in data.series.items()
            if key.endswith("::close")
        }
        return cls(
            index=index,
            open=open_, high=high, low=low, close=close, volume=volume,
            log_return=np.log(close / close.shift(1)),
            overnight=np.log(open_ / close.shift(1)),
            intraday=np.log(close / open_),
            clv=clv, body=body, parkinson=parkinson, etf_close=etf,
        )


def _state_from_score(score: pd.Series) -> pd.Series:
    valid = score.notna()
    event = pd.Series(np.nan, index=score.index, dtype=float)
    event.loc[valid & (score > 0)] = 1.0
    event.loc[valid & (score < 0)] = -1.0
    result = event.ffill().fillna(1.0).astype(np.int8)
    result.attrs["first_valid"] = valid[valid].index.min() if valid.any() else None
    result.attrs["eligible_count"] = int(valid.sum())
    return result


def _state_from_events(long_event: pd.Series, short_event: pd.Series, eligible: pd.Series) -> pd.Series:
    if (long_event.fillna(False) & short_event.fillna(False)).any():
        raise CandidateRejected("CONTRADICTORY_LONG_SHORT_EVENT")
    event = pd.Series(np.nan, index=eligible.index, dtype=float)
    event.loc[long_event.fillna(False)] = 1.0
    event.loc[short_event.fillna(False)] = -1.0
    result = event.ffill().fillna(1.0).astype(np.int8)
    result.attrs["first_valid"] = eligible[eligible].index.min() if eligible.any() else None
    result.attrs["eligible_count"] = int(eligible.sum())
    return result


def _rolling_mad(values: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    median = values.rolling(window, min_periods=window).median()
    mad = values.rolling(window, min_periods=window).apply(
        lambda raw: float(np.median(np.abs(raw - np.median(raw)))), raw=True
    )
    return median, mad


def variance_ratio(values: np.ndarray, q: int) -> float:
    raw = np.asarray(values, dtype=float)
    if len(raw) < q + 2 or not np.isfinite(raw).all():
        return np.nan
    n = len(raw)
    mean = float(raw.mean())
    one = float(np.sum((raw - mean) ** 2) / (n - 1))
    if one <= 0:
        return np.nan
    qsum = np.convolve(raw, np.ones(q), mode="valid")
    m = q * (n - q + 1) * (1.0 - q / n)
    if m <= 0:
        return np.nan
    multi = float(np.sum((qsum - q * mean) ** 2) / m)
    return multi / one


def newey_west_slope_tstat(values: np.ndarray) -> float:
    y = np.asarray(values, dtype=float)
    if not np.isfinite(y).all() or len(y) < 4:
        return np.nan
    n = len(y)
    x = np.column_stack((np.ones(n), np.arange(n, dtype=float)))
    inv = np.linalg.inv(x.T @ x)
    beta = inv @ x.T @ y
    residual = y - x @ beta
    lag = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    meat = np.zeros((2, 2), dtype=float)
    for t in range(n):
        meat += residual[t] ** 2 * np.outer(x[t], x[t])
    for h in range(1, lag + 1):
        weight = 1.0 - h / (lag + 1.0)
        gamma = np.zeros((2, 2), dtype=float)
        for t in range(h, n):
            gamma += residual[t] * residual[t - h] * np.outer(x[t], x[t - h])
        meat += weight * (gamma + gamma.T)
    covariance = (n / (n - 2.0)) * inv @ meat @ inv
    se = float(np.sqrt(max(covariance[1, 1], 0.0)))
    return float(beta[1] / se) if se > 0 else np.nan


def _score(candidate: Mapping[str, Any], store: FeatureStore) -> pd.Series:
    family = str(candidate["family"])
    p = candidate["parameters"]
    r, close, volume = store.log_return, store.close, store.volume
    if family == "overnight_intraday_tug":
        base = (store.overnight - store.intraday).rolling(int(p["lookback"]), min_periods=int(p["lookback"])).sum()
        return base if p["mode"] == "continuation" else -base
    if family == "gap_body_interaction":
        agree = np.sign(store.overnight) == np.sign(store.intraday)
        nonzero = store.overnight.ne(0) & store.intraday.ne(0)
        component = (store.overnight + store.intraday).where(agree & nonzero, 0.0)
        if p["mode"] == "rejection":
            component = store.intraday.where((~agree) & nonzero, 0.0)
        return component.rolling(int(p["lookback"]), min_periods=int(p["lookback"])).sum()
    if family == "close_location_pressure":
        return store.clv.rolling(int(p["window"]), min_periods=int(p["window"])).mean()
    if family == "range_body_pressure":
        return store.body.rolling(int(p["window"]), min_periods=int(p["window"])).mean()
    if family == "range_volatility_ratio":
        short, long = int(p["short"]), int(p["long"])
        rv_s = store.parkinson.rolling(short, min_periods=short).mean()
        rv_l = store.parkinson.rolling(long, min_periods=long).mean()
        return np.sign(np.log(close / close.shift(long))) * (rv_l - rv_s)
    if family == "semivariance_balance":
        window = int(p["window"])
        up = r.pow(2).where(r > 0, 0.0).rolling(window, min_periods=window).sum()
        down = r.pow(2).where(r < 0, 0.0).rolling(window, min_periods=window).sum()
        return up - down
    if family == "skewness_state":
        result = r.rolling(int(p["window"]), min_periods=int(p["window"])).skew()
        return result if p["mode"] == "continuation" else -result
    if family == "volatility_of_volatility":
        rv_window, vov_window = int(p["rv"]), int(p["vov"])
        rv = r.rolling(rv_window, min_periods=rv_window).std(ddof=1) * np.sqrt(252.0)
        vov = np.log(rv).diff().rolling(vov_window, min_periods=vov_window).std(ddof=1)
        mean = vov.expanding(min_periods=252).mean()
        std = vov.expanding(min_periods=252).std(ddof=1).replace(0.0, np.nan)
        z = (vov - mean) / std
        direction = np.sign(np.log(close / close.shift(20)))
        return direction * (-z if p["mode"] == "continuation" else z)
    if family == "variance_ratio_switch":
        q, window = int(p["q"]), int(p["window"])
        vr = r.rolling(window, min_periods=window).apply(lambda raw: variance_ratio(raw, q), raw=True)
        return np.sign(r.rolling(q, min_periods=q).sum()) * (vr - 1.0)
    if family == "autocorrelation_switch":
        lag, window = int(p["lag"]), int(p["window"])
        rho = r.rolling(window + lag, min_periods=window + lag).apply(
            lambda raw: float(np.corrcoef(raw[lag:], raw[:-lag])[0, 1]), raw=True
        )
        return rho * r.rolling(lag, min_periods=lag).sum()
    if family == "regression_trend_tstat":
        window = int(p["window"])
        return np.log(close).rolling(window, min_periods=window).apply(newey_west_slope_tstat, raw=True)
    if family == "fifty_two_week_state":
        window = int(p["window"])
        return close / close.rolling(window, min_periods=window).max() - float(p["cutoff"])
    if family == "momentum_acceleration":
        short, long = int(p["short"]), int(p["long"])
        return np.log(close / close.shift(short)) / short - np.log(close / close.shift(long)) / long
    if family == "momentum_consistency":
        signed = pd.Series(np.sign(r), index=r.index)
        return signed.rolling(int(p["window"]), min_periods=int(p["window"])).mean()
    if family == "signed_volume_pressure":
        scale = volume.rolling(252, min_periods=252).median()
        abnormal = np.log(volume / scale).where((volume > 0) & (scale > 0))
        component = np.sign(r) * abnormal
        return component.rolling(int(p["window"]), min_periods=int(p["window"])).sum()
    if family == "amihud_price_impact":
        dvol = close * volume
        scale = dvol.rolling(252, min_periods=252).median()
        component = (r * scale / dvol).where(dvol > 0)
        return component.rolling(int(p["window"]), min_periods=int(p["window"])).sum()
    if family == "sector_etf_breadth":
        horizon = int(p["horizon"])
        components = []
        for symbol in SECTOR_SYMBOLS:
            q = store.etf_close[symbol]
            value = np.log(q / q.shift(horizon)) if p["mode"] == "positive_return" else q - q.rolling(horizon, min_periods=horizon).mean()
            components.append(np.sign(value))
        return pd.concat(components, axis=1).mean(axis=1, skipna=False)
    if family in {"cyclical_defensive_leadership", "cross_asset_etf_risk_appetite"}:
        ratio = store.etf_close[str(p["numerator"])] / store.etf_close[str(p["denominator"])]
        return np.log(ratio / ratio.shift(int(p["horizon"])))
    if family == "sector_dispersion_state":
        horizon, state = int(p["horizon"]), int(p["state_window"])
        component = pd.concat(
            [np.log(store.etf_close[s] / store.etf_close[s].shift(horizon)) for s in SECTOR_SYMBOLS],
            axis=1,
        )
        dispersion = component.std(axis=1, ddof=1, skipna=False)
        baseline_window = 5 * state
        baseline = dispersion.rolling(baseline_window, min_periods=baseline_window).median()
        return np.sign(np.log(close / close.shift(horizon))) * (baseline - dispersion)
    if family == "equal_weight_concentration":
        ratio = store.etf_close["RSP"] / store.etf_close["SPY"]
        return np.log(ratio / ratio.shift(int(p["horizon"])))
    raise CandidateRejected(f"EVENT_OR_MODEL_FAMILY:{family}")


def _tail_decisions(candidate: Mapping[str, Any], store: FeatureStore) -> pd.Series:
    p = candidate["parameters"]
    median, mad = _rolling_mad(store.log_return, int(p["window"]))
    z = (store.log_return - median) / (1.4826 * mad.replace(0.0, np.nan))
    threshold = float(p["threshold"])
    eligible = z.notna()
    return _state_from_events(z <= -threshold, z >= threshold, eligible)


def _cusum_decisions(candidate: Mapping[str, Any], store: FeatureStore) -> pd.Series:
    p = candidate["parameters"]
    mean = store.log_return.expanding(min_periods=252).mean()
    std = store.log_return.expanding(min_periods=252).std(ddof=1).replace(0.0, np.nan)
    z = (store.log_return - mean) / std
    k, h = float(p["k"]), float(p["h"])
    events = pd.Series(np.nan, index=store.index, dtype=float)
    gplus = gminus = 0.0
    for i, value in enumerate(z.to_numpy(dtype=float)):
        if not np.isfinite(value):
            continue
        gplus = max(0.0, gplus + value - k)
        gminus = min(0.0, gminus + value + k)
        if gplus >= h:
            events.iloc[i] = 1.0
            gplus = gminus = 0.0
        elif gminus <= -h:
            events.iloc[i] = -1.0
            gplus = gminus = 0.0
    decisions = events.ffill().fillna(1.0).astype(np.int8)
    eligible = z.notna()
    decisions.attrs["first_valid"] = eligible[eligible].index.min() if eligible.any() else None
    decisions.attrs["eligible_count"] = int(eligible.sum())
    return decisions


def tree_feature_frame(store: FeatureStore) -> pd.DataFrame:
    r = store.log_return
    semivar = r.pow(2).where(r > 0, 0.0).rolling(20, min_periods=20).sum() - r.pow(2).where(r < 0, 0.0).rolling(20, min_periods=20).sum()
    pos = pd.Series(np.sign(r), index=r.index).rolling(20, min_periods=20).mean()
    median_volume = store.volume.rolling(252, min_periods=252).median()
    abnormal = np.log(store.volume / median_volume).where((store.volume > 0) & (median_volume > 0))
    signed = (np.sign(r) * abnormal).rolling(5, min_periods=5).sum()
    rv5 = store.parkinson.rolling(5, min_periods=5).mean()
    rv20 = store.parkinson.rolling(20, min_periods=20).mean()
    return pd.DataFrame(
        {
            "r_on_1": store.overnight,
            "r_id_1": store.intraday,
            "clv_1": store.clv,
            "body_1": store.body,
            "ret_5": np.log(store.close / store.close.shift(5)),
            "ret_20": np.log(store.close / store.close.shift(20)),
            "semivar_balance_20": semivar,
            "positive_day_balance_20": pos,
            "signed_abnormal_volume_5": signed,
            "parkinson_ratio_5_20": rv20 - rv5,
        },
        index=store.index,
    )


def _tree_decisions(candidate: Mapping[str, Any], store: FeatureStore, data: PreparedMarketData) -> pd.Series:
    p = candidate["parameters"]
    features = tree_feature_frame(store)
    labels = (data.ledger["long_return"].shift(-1) > 0).astype(float)
    labels.loc[data.ledger["long_return"].shift(-1).isna()] = np.nan
    score = pd.Series(np.nan, index=store.index, dtype=float)
    model: DecisionTreeClassifier | None = None
    medians: pd.Series | None = None
    months = store.index.to_period("M")
    for i in range(len(store.index)):
        refit = i == 0 or months[i] != months[i - 1]
        if refit:
            # At close i, labels through decision i-2 have reached their ending open.
            training = features.iloc[: max(0, i - 1)].copy()
            y = labels.iloc[: max(0, i - 1)]
            complete_label = y.notna()
            training = training.loc[complete_label]
            y = y.loc[complete_label]
            if len(training) >= 1260 and y.nunique() == 2:
                medians = training.median(axis=0)
                model = DecisionTreeClassifier(
                    criterion="log_loss", splitter="best", max_depth=int(p["max_depth"]),
                    min_samples_leaf=int(p["min_leaf"]), min_samples_split=2,
                    max_features=None, random_state=SEED, max_leaf_nodes=None,
                    min_impurity_decrease=0.0, class_weight=None, ccp_alpha=0.0,
                )
                model.fit(training.fillna(medians), y.astype(int))
            else:
                model = None
                medians = None
        if model is not None and medians is not None:
            row = features.iloc[[i]].fillna(medians)
            probability = float(model.predict_proba(row)[0, list(model.classes_).index(1)])
            score.iloc[i] = probability - 0.5
    return _state_from_score(score)


def candidate_decisions(
    candidate: Mapping[str, Any],
    data: PreparedMarketData,
    *,
    feature_store: FeatureStore | None = None,
) -> SignalResult:
    missing = sorted(set(candidate["required_datasets"]) - set(data.available_dataset_ids))
    if missing:
        raise CandidateRejected("DATA_GATE_REJECTED:" + "|".join(missing))
    family = str(candidate["family"])
    if family not in IMPLEMENTED_FAMILIES:
        raise CandidateRejected(f"UNIMPLEMENTED_FAMILY:{family}")
    store = feature_store or FeatureStore.build(data)
    if family == "tail_imbalance":
        decisions = _tail_decisions(candidate, store)
    elif family == "cusum_change_state":
        decisions = _cusum_decisions(candidate, store)
    elif family == "causal_shallow_tree":
        decisions = _tree_decisions(candidate, store, data)
    else:
        decisions = _state_from_score(_score(candidate, store))
    if not decisions.isin((-1, 1)).all():
        raise CandidateRejected("INVALID_POSITION_OUTPUT")
    first_value = decisions.attrs.get("first_valid")
    eligible = int(decisions.attrs.get("eligible_count", 0))
    if first_value is None:
        missing_fraction = 1.0
    else:
        offset = int(store.index.searchsorted(pd.Timestamp(first_value)))
        expected = len(store.index) - offset
        missing_fraction = 1.0 - eligible / expected if expected > 0 else 1.0
    return SignalResult(
        decisions=decisions,
        first_evaluable_date=(pd.Timestamp(first_value).date().isoformat() if first_value is not None else None),
        missing_fraction=float(missing_fraction),
    )


def candidate_decisions_reference(candidate: Mapping[str, Any], data: PreparedMarketData) -> SignalResult:
    """Reference path deliberately rebuilds every primitive instead of reusing a shared store."""
    return candidate_decisions(candidate, data, feature_store=FeatureStore.build(data))

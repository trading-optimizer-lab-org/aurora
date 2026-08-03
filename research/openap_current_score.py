"""Current Open Asset Pricing score from YFinance and SEC EDGAR data.

The module deliberately separates three concepts:

* ``exact``: the available inputs and implemented formula match OpenAP.
* ``proxy``: the economic idea is represented, but a source or formula differs.
* ``unavailable``: the two-source dataset cannot reproduce the signal honestly.

No missing observation is converted to zero.  Every produced value keeps its
source and availability status so a score can never silently treat a proxy as
an exact OpenAP characteristic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
import hashlib
import json
import math
import re

import numpy as np
import pandas as pd


EXPECTED_PREDICTORS = 185
SUPPORTED_HORIZONS = (1, 3, 6, 12, 36)
DEFAULT_REQUIRED_SCORE_BUCKETS = (0,)


class OpenAPDataError(RuntimeError):
    """Raised when an input violates the OpenAP current-score contract."""


@dataclass(frozen=True)
class FeatureValue:
    signalname: str
    raw_value: float | None
    status: str
    source: str
    formula_id: str
    note: str = ""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_strict_predictors(summary: pd.DataFrame) -> pd.DataFrame:
    """Apply the exact strict-185 selection used in the prior audit."""

    required = {"signalname", "Cat.Signal", "tstat", "T.Stat"}
    missing = required.difference(summary.columns)
    if missing:
        raise OpenAPDataError(f"Predictor summary missing columns: {sorted(missing)}")
    frame = summary.loc[summary["Cat.Signal"].eq("Predictor")].copy()
    frame["tstat"] = pd.to_numeric(frame["tstat"], errors="coerce")
    frame["T.Stat"] = pd.to_numeric(frame["T.Stat"], errors="coerce")
    selected = frame.loc[
        frame["tstat"].gt(1.96)
        & (frame["T.Stat"].isna() | frame["T.Stat"].ge(1.96))
    ].copy()
    selected = selected.drop_duplicates("signalname").sort_values("signalname")
    if len(selected) != EXPECTED_PREDICTORS:
        raise OpenAPDataError(
            f"Expected {EXPECTED_PREDICTORS} strict predictors, found {len(selected)}"
        )
    return selected.reset_index(drop=True)


def _quality_multiplier(value: object) -> float:
    text = str(value or "").lower()
    if "1_good" in text:
        return 1.0
    if "2_fair" in text:
        return 0.85
    if "3_distant" in text:
        return 0.65
    if "4_lack_data" in text:
        return 0.40
    return 0.70


def evidence_weight(
    row: Mapping[str, Any],
    status: str,
    *,
    exact_source_multiplier: float = 1.0,
    proxy_source_multiplier: float = 0.55,
) -> float:
    """Return a bounded evidence weight without treating missing t-stats as zero."""

    reproduction = abs(float(row.get("tstat") or 0.0))
    original_raw = row.get("T.Stat")
    try:
        original = abs(float(str(original_raw)))
        original_factor = min(original, 8.0) / 8.0
    except (TypeError, ValueError):
        original_factor = 0.70
    reproduction_factor = min(reproduction, 8.0) / 8.0
    source_factor = {
        "exact": float(exact_source_multiplier),
        "proxy": float(proxy_source_multiplier),
    }.get(status, 0.0)
    return (
        max(reproduction_factor, 0.10)
        * max(original_factor, 0.10)
        * _quality_multiplier(row.get("Signal.Rep.Quality"))
        * source_factor
    )


def signed_percentile(values: pd.Series, sign: float) -> pd.Series:
    """Cross-sectional 0-100 percentile after applying OpenAP direction."""

    numeric = pd.to_numeric(values, errors="coerce") * float(sign)
    return numeric.rank(method="average", pct=True) * 100.0


def _reference_percentile(values: pd.Series, reference: pd.Series) -> pd.Series:
    """Rank values against an explicit breakpoint universe.

    OpenAP may calculate breakpoints using NYSE stocks while assigning every
    eligible stock to those breakpoints.  Pandas' regular rank cannot express
    that distinction, so this helper uses the midpoint empirical CDF of the
    reference sample.
    """

    numeric = pd.to_numeric(values, errors="coerce")
    reference_values = np.sort(
        pd.to_numeric(reference, errors="coerce").dropna().to_numpy(dtype=float)
    )
    result = pd.Series(np.nan, index=values.index, dtype=float)
    if not len(reference_values):
        return result
    valid = numeric.notna()
    observed = numeric.loc[valid].to_numpy(dtype=float)
    left = np.searchsorted(reference_values, observed, side="left")
    right = np.searchsorted(reference_values, observed, side="right")
    result.loc[valid] = 100.0 * (left + right) / (2.0 * len(reference_values))
    return result.clip(0.0, 100.0)


def _normalise_exchange(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).upper()
    if "NASDAQ" in text:
        return 3
    if "NYSE AMERICAN" in text or "AMEX" in text:
        return 2
    if "NYSE" in text or "NEW YORK STOCK EXCHANGE" in text:
        return 1
    return None


def official_filter_mask(
    definition: Mapping[str, Any],
    context: pd.DataFrame,
) -> tuple[pd.Series, str]:
    """Apply the finite set of official SignalDoc filters used by the strict 185.

    Unsupported expressions fail closed.  This is intentionally not a generic
    expression evaluator: accepting arbitrary R text would make silent filter
    drift much easier than a small audited mapping.
    """

    expression = str(definition.get("filterstr") or "").strip()
    mask = pd.Series(True, index=context.index, dtype=bool)
    if not expression or expression.lower() in {"nan", "none", "na"}:
        return mask, "none"
    compact = re.sub(r"\s+", "", expression.lower())
    price = pd.to_numeric(context.get("current_price"), errors="coerce")
    exchange_code = context.get("exchange_code", pd.Series(index=context.index, dtype="Int64"))
    common = context.get("eligible_common_stock", pd.Series(False, index=context.index)).fillna(False).astype(bool)
    market_cap = pd.to_numeric(context.get("market_cap"), errors="coerce")
    nyse20 = pd.to_numeric(context.get("nyse_market_cap_p20"), errors="coerce")

    clauses = [clause for clause in compact.split(",") if clause]
    supported = {
        "abs(prc)>1",
        "abs(prc)>5",
        "shrcd<=11",
        "shrcd%in%c(10,11)",
        "exchcd==1",
        "exchcd%in%c(1,2)",
        "exchcd%in%c(1,2,3)",
        "me>me_nyse20",
    }
    unknown = sorted(set(clauses).difference(supported))
    if unknown:
        return pd.Series(False, index=context.index, dtype=bool), "unsupported:" + "|".join(unknown)
    for clause in clauses:
        if clause == "abs(prc)>1":
            mask &= price.abs().gt(1.0)
        elif clause == "abs(prc)>5":
            mask &= price.abs().gt(5.0)
        elif clause in {"shrcd<=11", "shrcd%in%c(10,11)"}:
            mask &= common
        elif clause == "exchcd==1":
            mask &= exchange_code.eq(1)
        elif clause == "exchcd%in%c(1,2)":
            mask &= exchange_code.isin([1, 2])
        elif clause == "exchcd%in%c(1,2,3)":
            mask &= exchange_code.isin([1, 2, 3])
        elif clause == "me>me_nyse20":
            mask &= market_cap.gt(nyse20)
    return mask.fillna(False), "applied"


def _connected_components(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in edges:
        if left in graph and right in graph:
            graph[left].add(right)
            graph[right].add(left)
    seen: set[str] = set()
    result: list[list[str]] = []
    for node in nodes:
        if node in seen:
            continue
        stack = [node]
        component: list[str] = []
        seen.add(node)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in graph[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        result.append(sorted(component))
    return result


def build_redundancy_groups(
    metadata: pd.DataFrame,
    portfolio_returns: pd.DataFrame,
    *,
    threshold: float = 0.80,
    minimum_overlap: int = 60,
) -> pd.DataFrame:
    """Group genuinely redundant predictors without transitive chaining.

    Directions are aligned first.  Two predictors may share a group only when
    their aligned returns are positively correlated, belong to the same
    economic family, and clear the threshold against every existing member.
    Strong inverse relationships are useful diversification evidence, not
    duplicates, so they deliberately remain separate.
    """

    names = metadata["signalname"].astype(str).tolist()
    signs = metadata.set_index("signalname")["Sign"].apply(
        lambda value: float(value) if pd.notna(value) else 1.0
    )
    available = [name for name in names if name in portfolio_returns.columns]
    aligned = portfolio_returns[available].apply(pd.to_numeric, errors="coerce")
    aligned = aligned.mul(signs.reindex(available), axis=1)
    corr = aligned.corr(min_periods=int(minimum_overlap))
    count = aligned.notna().astype("int16").T.dot(aligned.notna().astype("int16"))
    family_column = "Cat.Economic" if "Cat.Economic" in metadata else "Cat.Data"
    families = metadata.set_index("signalname")[family_column].fillna("unknown").astype(str)
    components: list[list[str]] = []
    for signal in names:
        placed = False
        if signal in available:
            for component in components:
                comparable = [member for member in component if member in available]
                if not comparable:
                    continue
                if any(families.get(member, "unknown") != families.get(signal, "unknown") for member in comparable):
                    continue
                if all(
                    int(count.at[signal, member]) >= minimum_overlap
                    and pd.notna(corr.at[signal, member])
                    and float(corr.at[signal, member]) >= threshold
                    for member in comparable
                ):
                    component.append(signal)
                    placed = True
                    break
        if not placed:
            components.append([signal])
    rows: list[dict[str, Any]] = []
    for group_index, component in enumerate(components, start=1):
        group_id = f"redundancy_{group_index:03d}"
        for signal in component:
            rows.append(
                {
                    "signalname": signal,
                    "redundancy_group": group_id,
                    "group_size": len(component),
                }
            )
    return pd.DataFrame(rows).sort_values(["redundancy_group", "signalname"])


def redundancy_correlation_audit(
    metadata: pd.DataFrame,
    portfolio_returns: pd.DataFrame,
    groups: pd.DataFrame,
    *,
    threshold: float = 0.80,
    minimum_overlap: int = 60,
) -> pd.DataFrame:
    """Record strong positive and inverse relationships without conflating them."""

    names = [name for name in metadata["signalname"].astype(str) if name in portfolio_returns]
    signs = metadata.set_index("signalname")["Sign"].fillna(1.0).astype(float)
    family_column = "Cat.Economic" if "Cat.Economic" in metadata else "Cat.Data"
    families = metadata.set_index("signalname")[family_column].fillna("unknown").astype(str)
    raw = portfolio_returns[names].apply(pd.to_numeric, errors="coerce")
    aligned = raw.mul(signs.reindex(names), axis=1)
    raw_corr = raw.corr(min_periods=minimum_overlap)
    aligned_corr = aligned.corr(min_periods=minimum_overlap)
    overlap = aligned.notna().astype("int16").T.dot(aligned.notna().astype("int16"))
    group_map = groups.set_index("signalname")["redundancy_group"].astype(str).to_dict()
    rows = []
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            value = aligned_corr.at[left, right]
            observations = int(overlap.at[left, right])
            if observations < minimum_overlap or pd.isna(value) or abs(float(value)) < threshold:
                continue
            rows.append(
                {
                    "signal_left": left,
                    "signal_right": right,
                    "raw_correlation": raw_corr.at[left, right],
                    "aligned_correlation": value,
                    "overlap_months": observations,
                    "same_economic_family": families.get(left) == families.get(right),
                    "relationship": "duplicate_candidate" if float(value) >= threshold else "inverse_diversifier",
                    "same_redundancy_group": group_map.get(left) == group_map.get(right),
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "signal_left", "signal_right", "raw_correlation", "aligned_correlation",
            "overlap_months", "same_economic_family", "relationship",
            "same_redundancy_group",
        ],
    )


def refine_current_redundancy_groups(
    features: pd.DataFrame,
    *,
    threshold: float = 0.995,
    minimum_overlap: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge historical groups that collapse to the same current signal.

    Historical long-short return correlation remains the primary grouping.
    This second layer catches implementation duplicates introduced by a shared
    current formula or by near-identical signed cross-sectional percentiles.
    Complete-link merging prevents transitive chains from swallowing distinct
    signals.
    """

    if features.empty:
        return features.copy(), pd.DataFrame()
    result = features.copy()
    signal_rows = result.drop_duplicates("signalname").set_index("signalname")
    names = sorted(signal_rows.index.astype(str))
    initial = {
        str(group): sorted(part["signalname"].astype(str).unique())
        for group, part in result.groupby("redundancy_group")
    }
    components = [members for _, members in sorted(initial.items())]
    pivot = result.pivot(index="symbol", columns="signalname", values="percentile")
    corr = pivot.corr(min_periods=int(minimum_overlap))
    overlap = pivot.notna().astype("int16").T.dot(pivot.notna().astype("int16"))
    formula = signal_rows["formula_id"].fillna("").astype(str).to_dict()
    horizon = signal_rows["horizon_months"].to_dict()

    def pair_reason(left: str, right: str) -> str | None:
        if horizon.get(left) != horizon.get(right):
            return None
        left_formula = formula.get(left, "")
        right_formula = formula.get(right, "")
        if left_formula and left_formula == right_formula:
            return "same_formula_id"
        if left not in corr.index or right not in corr.columns:
            return None
        value = corr.at[left, right]
        if (
            int(overlap.at[left, right]) >= int(minimum_overlap)
            and pd.notna(value)
            and float(value) >= float(threshold)
        ):
            return "current_percentile_correlation"
        return None

    merged = True
    while merged:
        merged = False
        for left_index in range(len(components)):
            if merged:
                break
            for right_index in range(left_index + 1, len(components)):
                left_group = components[left_index]
                right_group = components[right_index]
                reasons = [
                    pair_reason(left, right)
                    for left in left_group
                    for right in right_group
                ]
                if reasons and all(reason is not None for reason in reasons):
                    components[left_index] = sorted(left_group + right_group)
                    components.pop(right_index)
                    merged = True
                    break

    mapping: dict[str, str] = {}
    audit_rows: list[dict[str, Any]] = []
    historical_map = signal_rows["redundancy_group"].astype(str).to_dict()
    for index, members in enumerate(components, start=1):
        group_id = f"current_redundancy_{index:03d}"
        historical_groups = sorted({historical_map[name] for name in members})
        for name in members:
            mapping[name] = group_id
            audit_rows.append(
                {
                    "signalname": name,
                    "historical_redundancy_group": historical_map[name],
                    "current_redundancy_group": group_id,
                    "current_group_size": len(members),
                    "merged_historical_groups": "|".join(historical_groups),
                    "current_merge_applied": len(historical_groups) > 1,
                }
            )
    result["historical_redundancy_group"] = result["redundancy_group"]
    result["redundancy_group"] = result["signalname"].map(mapping)
    return result, pd.DataFrame(audit_rows).sort_values(
        ["current_redundancy_group", "signalname"]
    )


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    try:
        left = float(numerator)
        right = float(denominator)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(left) or not np.isfinite(right) or abs(right) < 1e-12:
        return None
    value = left / right
    return float(value) if np.isfinite(value) else None


def _return_between(prices: pd.Series, older: int, newer: int = 0) -> float | None:
    if len(prices) <= older:
        return None
    old = prices.iloc[-(older + 1)]
    new = prices.iloc[-(newer + 1)] if newer else prices.iloc[-1]
    ratio = _safe_ratio(new, old)
    return ratio - 1.0 if ratio is not None else None


def _monthly_close(frame: pd.DataFrame) -> pd.Series:
    values = frame.copy()
    values["date"] = pd.to_datetime(values["date"], errors="coerce")
    values["adj_close"] = pd.to_numeric(values["adj_close"], errors="coerce")
    values = values.dropna(subset=["date", "adj_close"]).sort_values("date")
    if values.empty:
        return pd.Series(dtype=float)
    return values.set_index("date")["adj_close"].resample("ME").last().dropna()


def clean_price_history(
    frame: pd.DataFrame,
    *,
    maximum_absolute_daily_return: float = 3.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Quarantine impossible rows and discard history before the last split-like break."""

    data = frame.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    numeric_columns = ("open", "high", "low", "close", "adj_close", "volume")
    for column in numeric_columns:
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=["date", "adj_close"]).sort_values("date")
    duplicate_rows = int(data.duplicated(["date"], keep=False).sum())
    data = data.drop_duplicates("date", keep="last")
    positive = data["adj_close"].gt(0)
    ohlc_valid = pd.Series(True, index=data.index)
    if {"open", "high", "low", "close"}.issubset(data.columns):
        ohlc = data[["open", "high", "low", "close"]]
        complete = ohlc.notna().all(axis=1)
        ohlc_valid = ~complete | (
            ohlc.gt(0).all(axis=1)
            & data["high"].ge(data[["open", "close", "low"]].max(axis=1))
            & data["low"].le(data[["open", "close", "high"]].min(axis=1))
        )
    base_valid = positive & ohlc_valid
    provisional = data.loc[base_valid].copy()
    returns = provisional["adj_close"].pct_change()
    severe = returns.abs().gt(float(maximum_absolute_daily_return)) | returns.le(-0.95)
    last_break_date = provisional.loc[severe, "date"].max() if severe.any() else pd.NaT
    clean = provisional.loc[~severe].copy()
    if pd.notna(last_break_date):
        clean = clean.loc[clean["date"].gt(last_break_date)].copy()
    recent_cutoff = data["date"].max() - pd.Timedelta(days=400) if not data.empty else pd.NaT
    recent_severe = int((severe & provisional["date"].ge(recent_cutoff)).sum()) if pd.notna(recent_cutoff) else 0
    quality = {
        "raw_price_rows": int(len(data)),
        "clean_price_rows": int(len(clean)),
        "duplicate_price_dates": duplicate_rows,
        "nonpositive_price_rows": int((~positive).sum()),
        "invalid_ohlc_rows": int((~ohlc_valid).sum()),
        "extreme_return_rows": int(severe.sum()),
        "recent_extreme_return_rows": recent_severe,
        "history_reset_after": last_break_date,
        "price_quality_pass": bool(len(clean) >= 252 and recent_severe == 0),
    }
    return clean, quality


def calculate_price_features(frame: pd.DataFrame) -> dict[str, FeatureValue]:
    """Calculate current price and trading characteristics.

    Signals that need the original CRSP cross-sectional regression, industry
    membership history or unavailable factor returns are labelled as proxies.
    """

    required = {"date", "adj_close", "volume"}
    if required.difference(frame.columns):
        return {}
    daily, _ = clean_price_history(frame)
    if daily.empty:
        return {}
    close = daily["adj_close"]
    returns = close.pct_change()
    monthly = _monthly_close(daily)
    month_returns = monthly.pct_change()
    current = float(close.iloc[-1])
    volume = pd.to_numeric(daily["volume"], errors="coerce")
    dollar_volume = close * volume
    turnover_proxy = volume

    def exact(name: str, value: float | None, formula: str, note: str = "") -> FeatureValue:
        return FeatureValue(name, value, "exact", "yfinance", formula, note)

    def proxy(name: str, value: float | None, formula: str, note: str) -> FeatureValue:
        return FeatureValue(name, value, "proxy", "yfinance", formula, note)

    result: dict[str, FeatureValue] = {}
    result["Price"] = exact("Price", current, "price_abs_current")
    result["STreversal"] = exact(
        "STreversal",
        float(month_returns.iloc[-1]) if len(month_returns.dropna()) else None,
        "monthly_return_t_minus_1",
    )
    result["Mom6m"] = exact("Mom6m", _return_between(monthly, 6, 1), "return_month_6_to_1")
    result["Mom12m"] = exact("Mom12m", _return_between(monthly, 12, 1), "return_month_12_to_1")
    result["IntMom"] = exact("IntMom", _return_between(monthly, 12, 7), "return_month_12_to_7")
    result["MRreversal"] = exact("MRreversal", _return_between(monthly, 36, 13), "return_month_36_to_13")
    result["LRreversal"] = exact("LRreversal", _return_between(monthly, 60, 36), "return_month_60_to_36")
    if len(close) >= 252:
        result["High52"] = exact("High52", _safe_ratio(current, close.iloc[-252:].max()), "price_over_52w_high")
    recent_returns = returns.dropna().iloc[-21:]
    if not recent_returns.empty:
        result["MaxRet"] = exact("MaxRet", float(recent_returns.max()), "max_daily_return_last_month")
        result["RealizedVol"] = exact("RealizedVol", float(recent_returns.std(ddof=1)), "daily_return_std_last_month")
        result["ReturnSkew"] = exact("ReturnSkew", float(recent_returns.skew()), "daily_return_skew_last_month")
    if len(dollar_volume.dropna()) >= 21:
        result["DolVol"] = exact("DolVol", float(np.log1p(dollar_volume.iloc[-21:].mean())), "log_mean_dollar_volume_21d")
        illiq = (returns.abs() / dollar_volume.replace(0, np.nan)).iloc[-21:].mean()
        result["Illiquidity"] = exact("Illiquidity", float(illiq) if pd.notna(illiq) else None, "amihud_21d")
    if len(volume.dropna()) >= 252:
        result["ShareVol"] = proxy("ShareVol", float(volume.iloc[-21:].mean()), "mean_volume_21d", "Shares outstanding PIT is completed from SEC during merge")
        result["VolSD"] = proxy("VolSD", float(volume.iloc[-252:].std(ddof=1)), "volume_std_252d", "Uses raw share volume before SEC turnover scaling")
        x = np.arange(min(252, len(volume)), dtype=float)
        y = np.log1p(volume.iloc[-len(x):].to_numpy(dtype=float))
        valid = np.isfinite(y)
        slope = float(np.polyfit(x[valid], y[valid], 1)[0]) if valid.sum() >= 30 else None
        result["VolumeTrend"] = proxy("VolumeTrend", slope, "log_volume_trend_252d", "Yahoo volume replaces CRSP volume")
        result["std_turn"] = proxy("std_turn", float(turnover_proxy.iloc[-252:].std(ddof=1)), "volume_std_proxy_252d", "Final value is rescaled by SEC shares")
    for name, sessions in (("zerotrade1M", 21), ("zerotrade6M", 126), ("zerotrade12M", 252)):
        if len(volume) >= sessions:
            zero_days = float((volume.iloc[-sessions:] <= 0).mean())
            result[name] = proxy(name, zero_days, f"zero_volume_share_{sessions}d", "Yahoo reports consolidated volume, not CRSP zero-trade adjustment")
    ma_lengths = (3, 5, 10, 20, 50, 100, 200, 400, 600, 800, 1000)
    ma_values = []
    for length in ma_lengths:
        if len(close) >= length:
            ma_values.append(float(close.iloc[-length:].mean() / current))
    trend = float(-np.mean(ma_values)) if len(ma_values) == len(ma_lengths) else None
    result["TrendFactor"] = proxy(
        "TrendFactor",
        trend,
        "mean_negative_ma_to_price_3_5_10_20_50_100_200_400_600_800_1000",
        "OpenAP estimates rolling cross-sectional coefficients; this is the same 11-MA state but not that fitted regression",
    )
    # Exact lag sets from the pinned OpenAP predictor implementations.  The
    # signal date predicts the following month, hence the seasonal observation
    # from one year earlier is lag 11 rather than a calendar-month slice.
    monthly_with_gaps = (
        daily.assign(date=pd.to_datetime(daily["date"], errors="coerce"))
        .dropna(subset=["date"])
        .set_index("date")["adj_close"]
        .resample("ME")
        .last()
    )
    monthly_returns = monthly_with_gaps.pct_change(fill_method=None).reset_index(drop=True)

    def lag_average(lags: Sequence[int]) -> float | None:
        if not lags or any(len(monthly_returns) <= lag for lag in lags):
            return None
        values = [monthly_returns.iloc[-(lag + 1)] for lag in lags]
        if any(pd.isna(value) for value in values):
            return None
        return float(np.mean(values))

    result["MomSeasonShort"] = exact(
        "MomSeasonShort",
        lag_average([11]),
        "openap_ret_lag_11",
        "Pinned OpenAP MomSeasonShort.py",
    )
    result["MomSeason"] = exact(
        "MomSeason",
        lag_average([23, 35, 47, 59]),
        "openap_mean_ret_lags_23_35_47_59",
        "Pinned OpenAP MomSeason.py",
    )
    result["MomSeason06YrPlus"] = exact(
        "MomSeason06YrPlus",
        lag_average(list(range(71, 121, 12))),
        "openap_mean_ret_lags_71_to_119_step_12",
        "Pinned OpenAP MomSeason06YrPlus.py",
    )
    result["MomSeason11YrPlus"] = exact(
        "MomSeason11YrPlus",
        lag_average(list(range(131, 181, 12))),
        "openap_mean_ret_lags_131_to_179_step_12",
        "Pinned OpenAP MomSeason11YrPlus.py",
    )
    result["MomSeason16YrPlus"] = exact(
        "MomSeason16YrPlus",
        lag_average(list(range(191, 241, 12))),
        "openap_mean_ret_lags_191_to_239_step_12",
        "Pinned OpenAP MomSeason16YrPlus.py",
    )

    def off_season_lags(first: int, stop: int) -> list[int]:
        return [lag for lag in range(first, stop) if (lag + 1) % 12 != 0]

    result["Mom12mOffSeason"] = exact(
        "Mom12mOffSeason",
        lag_average(off_season_lags(1, 11)),
        "openap_mean_ret_lags_1_to_10_excluding_seasonal",
        "Pinned OpenAP Mom12mOffSeason.py",
    )
    result["MomOffSeason"] = exact(
        "MomOffSeason",
        lag_average(off_season_lags(12, 60)),
        "openap_mean_ret_lags_12_to_59_excluding_seasonal",
        "Pinned OpenAP MomOffSeason.py",
    )
    result["MomOffSeason06YrPlus"] = exact(
        "MomOffSeason06YrPlus",
        lag_average(off_season_lags(60, 120)),
        "openap_mean_ret_lags_60_to_119_excluding_seasonal",
        "Pinned OpenAP MomOffSeason06YrPlus.py",
    )
    result["MomOffSeason16YrPlus"] = exact(
        "MomOffSeason16YrPlus",
        lag_average(off_season_lags(180, 240)),
        "openap_mean_ret_lags_180_to_239_excluding_seasonal",
        "Pinned OpenAP MomOffSeason16YrPlus.py",
    )
    return result


SEC_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "cash": ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "inventory": ("InventoryNet",),
    "receivables": ("AccountsReceivableNetCurrent", "AccountsNotesAndLoansReceivableNetCurrent"),
    "ppe": ("PropertyPlantAndEquipmentNet",),
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "cogs": ("CostOfRevenue", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsForAdditionsToPropertyPlantAndEquipment"),
    "depreciation": ("DepreciationDepletionAndAmortization", "Depreciation"),
    "rd": ("ResearchAndDevelopmentExpense",),
    "sga": ("SellingGeneralAndAdministrativeExpense",),
    "advertising": ("AdvertisingExpense",),
    "tax": ("IncomeTaxExpenseBenefit",),
    "debt_current": ("ShortTermBorrowings", "LongTermDebtCurrent"),
    "debt_long": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "interest": ("InterestExpenseNonOperating", "InterestExpense"),
    "operating_income": ("OperatingIncomeLoss", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
    "short_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
    "long_investments": ("LongTermInvestments", "OtherInvestments"),
    "preferred_stock": ("PreferredStockValue", "PreferredStockCarryingValue"),
    "deferred_tax": ("DeferredIncomeTaxExpenseBenefit",),
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "repurchases": ("PaymentsForRepurchaseOfCommonStock",),
    "share_issuance": ("ProceedsFromStockOptionsExercised", "ProceedsFromIssuanceOfCommonStock"),
    "debt_issuance": ("ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt"),
    "debt_reduction": ("RepaymentsOfLongTermDebt", "RepaymentsOfDebt"),
    "shares": ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"),
    "employees": ("EntityNumberOfEmployees",),
    "backlog": ("OrderBacklog",),
}


def latest_sec_concept_inputs(facts: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return the exact SEC observations selected for each canonical concept.

    OpenAP accounting signals are annual.  SEC Company Facts frequently stores
    quarterly, year-to-date and annual observations for the same tag.  Mixing
    those rows would turn a quarter-to-quarter change into a fake annual
    growth rate, so annual filings and fiscal-year observations are preferred.
    The fallback keeps older fixtures and issuers with incomplete metadata
    usable, but never chooses a future filing.
    """

    audit_columns = [
        "concept",
        "concept_lag",
        "tag",
        "taxonomy",
        "unit",
        "value",
        "period_start",
        "period_end",
        "fy",
        "fp",
        "form",
        "filed",
        "accession_number",
        "available_at",
        "available_at_quality",
        "source",
        "source_mode",
    ]
    if facts.empty:
        return pd.DataFrame(columns=audit_columns)
    frame = facts.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce", utc=True).dt.tz_localize(None)
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    filed = pd.to_datetime(
        frame.get("filed", pd.Series(pd.NaT, index=frame.index)),
        errors="coerce",
        utc=True,
    ).dt.tz_localize(None)
    if "period_start" in frame:
        frame["period_start"] = pd.to_datetime(frame["period_start"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    as_of_timestamp = pd.Timestamp(as_of).tz_localize(None)
    causal_filing = filed.isna() | frame["available_at"].ge(filed)
    causal_period = frame["available_at"].dt.normalize().ge(frame["period_end"].dt.normalize())
    frame = frame.loc[
        frame["available_at"].le(as_of_timestamp)
        & frame["period_end"].le(as_of_timestamp.normalize())
        & causal_filing
        & causal_period
    ].dropna(subset=["period_end", "value"])
    selected_rows: list[pd.DataFrame] = []
    for concept, aliases in SEC_CONCEPT_ALIASES.items():
        subset = frame.loc[frame["tag"].isin(aliases)].copy()
        if subset.empty:
            continue
        unit = subset.get("unit", pd.Series(index=subset.index, dtype="string")).astype(str)
        if concept == "shares":
            subset = subset.loc[unit.str.lower().eq("shares")]
        elif concept == "employees":
            subset = subset.loc[unit.str.lower().isin({"employee", "employees", "person", "persons"})]
        else:
            subset = subset.loc[unit.str.upper().eq("USD")]
        if subset.empty:
            continue
        if "form" in subset:
            annual_form = subset["form"].astype(str).str.upper().isin({"10-K", "20-F", "40-F"})
        else:
            annual_form = pd.Series(False, index=subset.index)
        if "fp" in subset:
            fiscal_year = subset["fp"].astype(str).str.upper().eq("FY")
        else:
            fiscal_year = pd.Series(False, index=subset.index)
        annual = subset.loc[annual_form | fiscal_year].copy()
        if not annual.empty:
            subset = annual
        subset["alias_rank"] = subset["tag"].map({name: index for index, name in enumerate(aliases)})
        subset = subset.sort_values(
            ["period_end", "available_at", "alias_rank"],
            ascending=[True, False, True],
        )
        subset = subset.drop_duplicates("period_end", keep="first").sort_values("period_end")
        chosen = subset.tail(6).sort_values("period_end", ascending=False).copy()
        chosen["concept"] = concept
        chosen["concept_lag"] = np.arange(len(chosen), dtype=int)
        for column in audit_columns:
            if column not in chosen:
                chosen[column] = None
        selected_rows.append(chosen[audit_columns])
    if not selected_rows:
        return pd.DataFrame(columns=audit_columns)
    return pd.concat(selected_rows, ignore_index=True)


def sec_concepts_from_inputs(inputs: pd.DataFrame) -> dict[str, list[float | None]]:
    """Build canonical lag arrays from the auditable selected SEC rows."""

    result: dict[str, list[float | None]] = {}
    for concept in SEC_CONCEPT_ALIASES:
        subset = inputs.loc[inputs["concept"].eq(concept)].sort_values("concept_lag")
        values = pd.to_numeric(subset["value"], errors="coerce").dropna().tolist()
        result[concept] = [float(value) for value in values[:6]] + [None] * (6 - len(values[:6]))
    return result


def latest_sec_concepts(facts: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, list[float | None]]:
    """Return comparable annual concepts using strict available_at."""

    return sec_concepts_from_inputs(latest_sec_concept_inputs(facts, as_of))


def calculate_accounting_features(
    concepts: Mapping[str, Sequence[float | None]],
    *,
    market_cap: float | None,
) -> dict[str, FeatureValue]:
    """Calculate traceable current accounting characteristics from SEC facts."""

    def value(name: str, lag: int = 0) -> float | None:
        values = concepts.get(name, ())
        if lag >= len(values):
            return None
        raw = values[lag]
        try:
            number = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def delta(name: str) -> float | None:
        current, previous = value(name), value(name, 1)
        if current is None or previous is None:
            return None
        return current - previous

    def growth(name: str, lag: int = 1) -> float | None:
        current, previous = value(name), value(name, lag)
        ratio = _safe_ratio(current, previous)
        return ratio - 1.0 if ratio is not None else None

    def difference(left: float | None, right: float | None) -> float | None:
        if left is None or right is None:
            return None
        return left - right

    def sum_required(*items: float | None) -> float | None:
        if any(item is None for item in items):
            return None
        return float(sum(float(item) for item in items if item is not None))

    def average_required(*items: float | None) -> float | None:
        if any(item is None for item in items):
            return None
        return float(np.mean([float(item) for item in items if item is not None]))

    def weighted_sum_required(*items: tuple[float, float | None]) -> float | None:
        if any(value is None for _, value in items):
            return None
        return float(
            sum(weight * float(value) for weight, value in items if value is not None)
        )

    assets = value("assets")
    assets_lag = value("assets", 1)
    equity = value("equity")
    liabilities = value("liabilities")
    revenue = value("revenue")
    net_income = value("net_income")
    ocf = value("operating_cash_flow")
    cash = value("cash")
    ca = value("current_assets")
    cl = value("current_liabilities")
    inventory = value("inventory")
    ppe = value("ppe")
    cogs = value("cogs")
    rd = value("rd")
    sga = value("sga")
    debt = sum_required(value("debt_current"), value("debt_long"))
    dividends = value("dividends")
    repurchases = value("repurchases")
    issuance = value("share_issuance")
    debt_current = value("debt_current")
    debt_long = value("debt_long")
    debt_lag = sum_required(value("debt_current", 1), value("debt_long", 1))
    debt_5y = sum_required(value("debt_current", 5), value("debt_long", 5))
    average_assets = (
        (assets + assets_lag) / 2.0
        if assets is not None and assets_lag is not None
        else None
    )

    def exact(name: str, raw: float | None, formula: str) -> FeatureValue:
        note = "" if raw is not None else "Required SEC inputs are unavailable or not comparable"
        return FeatureValue(name, raw, "exact", "sec_edgar", formula, note)

    def proxy(name: str, raw: float | None, formula: str, note: str) -> FeatureValue:
        return FeatureValue(name, raw, "proxy", "sec_edgar", formula, note)

    result: dict[str, FeatureValue] = {}
    result["AM"] = exact("AM", _safe_ratio(assets, market_cap), "assets_over_market_cap")
    result["BM"] = exact("BM", _safe_ratio(equity, market_cap), "book_equity_over_market_cap")
    result["EP"] = exact("EP", _safe_ratio(net_income, market_cap), "net_income_over_market_cap")
    result["CF"] = exact("CF", _safe_ratio(ocf, market_cap), "operating_cash_flow_over_market_cap")
    result["cfp"] = exact("cfp", _safe_ratio(ocf, market_cap), "operating_cash_flow_over_market_cap")
    result["SP"] = exact("SP", _safe_ratio(revenue, market_cap), "revenue_over_market_cap")
    gross_profit = (revenue - cogs) if revenue is not None and cogs is not None else None
    result["GP"] = exact("GP", _safe_ratio(gross_profit, assets), "gross_profit_over_assets")
    result["RoE"] = exact("RoE", _safe_ratio(net_income, equity), "net_income_over_book_equity")
    result["Cash"] = exact("Cash", _safe_ratio(cash, assets), "cash_over_assets")
    result["CashProd"] = exact(
        "CashProd",
        _safe_ratio(difference(market_cap, assets), cash),
        "market_cap_minus_assets_over_cash",
    )
    result["BookLeverage"] = exact("BookLeverage", _safe_ratio(liabilities, assets), "liabilities_over_assets")
    result["Leverage"] = exact("Leverage", _safe_ratio(debt, market_cap), "debt_over_market_cap")
    result["AssetGrowth"] = exact("AssetGrowth", growth("assets"), "assets_growth_1y")
    current_asset_turnover = _safe_ratio(revenue, assets)
    lag_asset_turnover = _safe_ratio(value("revenue", 1), assets_lag)
    result["ChAssetTurnover"] = exact(
        "ChAssetTurnover",
        difference(current_asset_turnover, lag_asset_turnover),
        "annual_change_revenue_over_assets",
    )
    result["ChEQ"] = exact("ChEQ", growth("equity"), "book_equity_growth_1y")
    result["ChInv"] = exact("ChInv", _safe_ratio(delta("inventory"), assets_lag), "inventory_change_over_lag_assets")
    result["InvGrowth"] = exact("InvGrowth", growth("inventory"), "inventory_growth_1y")
    nwc = (ca - cl) if ca is not None and cl is not None else None
    ca_lag, cl_lag = value("current_assets", 1), value("current_liabilities", 1)
    nwc_lag = (ca_lag - cl_lag) if ca_lag is not None and cl_lag is not None else None
    nwc_change = (nwc - nwc_lag) if nwc is not None and nwc_lag is not None else None
    result["ChNWC"] = exact("ChNWC", _safe_ratio(nwc_change, assets_lag), "net_working_capital_change_over_lag_assets")
    result["ChTax"] = exact("ChTax", _safe_ratio(delta("tax"), assets_lag), "tax_change_over_lag_assets")
    accruals = (net_income - ocf) if net_income is not None and ocf is not None else None
    result["Accruals"] = exact("Accruals", _safe_ratio(accruals, assets_lag), "net_income_minus_ocf_over_lag_assets")
    result["TotalAccruals"] = exact("TotalAccruals", _safe_ratio(accruals, assets_lag), "total_accruals_over_lag_assets")
    result["PctAcc"] = exact("PctAcc", _safe_ratio(accruals, abs(net_income) if net_income is not None else None), "accruals_over_abs_earnings")
    current_operating_assets = difference(ca, cash)
    lag_operating_assets = difference(value("current_assets", 1), value("cash", 1))
    current_operating_liabilities = difference(cl, debt_current)
    lag_operating_liabilities = difference(value("current_liabilities", 1), value("debt_current", 1))
    result["DelCOA"] = exact(
        "DelCOA",
        _safe_ratio(difference(current_operating_assets, lag_operating_assets), average_assets),
        "change_current_operating_assets_over_average_assets",
    )
    result["DelCOL"] = exact(
        "DelCOL",
        _safe_ratio(difference(current_operating_liabilities, lag_operating_liabilities), average_assets),
        "change_current_operating_liabilities_over_average_assets",
    )
    result["DelEqu"] = exact(
        "DelEqu",
        _safe_ratio(delta("equity"), average_assets),
        "change_book_equity_over_average_assets",
    )
    financial_liabilities = sum_required(debt_current, debt_long, value("preferred_stock"))
    lag_financial_liabilities = sum_required(
        value("debt_current", 1),
        value("debt_long", 1),
        value("preferred_stock", 1),
    )
    result["DelFINL"] = exact(
        "DelFINL",
        _safe_ratio(difference(financial_liabilities, lag_financial_liabilities), average_assets),
        "change_financial_liabilities_over_average_assets",
    )
    result["DelLTI"] = exact(
        "DelLTI",
        _safe_ratio(delta("long_investments"), average_assets),
        "change_long_term_investments_over_average_assets",
    )
    net_financial_assets = difference(
        sum_required(value("short_investments"), value("long_investments")),
        financial_liabilities,
    )
    lag_net_financial_assets = difference(
        sum_required(value("short_investments", 1), value("long_investments", 1)),
        lag_financial_liabilities,
    )
    result["DelNetFin"] = exact(
        "DelNetFin",
        _safe_ratio(difference(net_financial_assets, lag_net_financial_assets), average_assets),
        "change_net_financial_assets_over_average_assets",
    )
    noa_proxy = (
        assets - cash - debt
        if assets is not None and cash is not None and debt is not None
        else None
    )
    result["NOA"] = proxy("NOA", _safe_ratio(noa_proxy, assets), "net_operating_assets_proxy", "SEC taxonomy cannot reproduce every financing component exactly")
    result["dNoa"] = proxy("dNoa", None, "change_in_noa_proxy", "Requires lagged canonical financing components")
    result["RD"] = exact("RD", _safe_ratio(rd, market_cap), "rd_over_market_cap")
    result["RDS"] = exact("RDS", _safe_ratio(rd, revenue), "rd_over_sales")
    result["RDcap"] = proxy("RDcap", _safe_ratio(rd, assets), "rd_over_assets_proxy", "Official signal capitalizes R&D recursively")
    result["AdExp"] = exact("AdExp", _safe_ratio(value("advertising"), market_cap), "advertising_over_market_cap")
    result["GrAdExp"] = exact("GrAdExp", growth("advertising"), "advertising_growth_1y")
    rd_growth = growth("rd")
    rd_assets = _safe_ratio(rd, assets)
    rd_sales = _safe_ratio(rd, revenue)
    lag_rd_assets = _safe_ratio(value("rd", 1), assets_lag)
    result["SurpriseRD"] = exact(
        "SurpriseRD",
        float(
            bool(
                rd_sales is not None
                and rd_sales > 0
                and rd_assets is not None
                and rd_assets > 0
                and rd_growth is not None
                and rd_growth > 0.05
                and lag_rd_assets is not None
                and abs(lag_rd_assets) > 1e-12
                and rd_assets / lag_rd_assets - 1.0 > 0.05
            )
        )
        if all(item is not None for item in (rd, revenue, assets, assets_lag, rd_growth, lag_rd_assets))
        else None,
        "rd_intensity_and_growth_four_condition_indicator",
    )
    result["grcapx"] = exact("grcapx", growth("capex"), "capex_growth_1y")
    result["grcapx3y"] = exact("grcapx3y", growth("capex", 3), "capex_growth_3y")
    result["InvestPPEInv"] = exact(
        "InvestPPEInv",
        _safe_ratio(sum_required(delta("ppe"), delta("inventory")), assets_lag),
        "ppe_plus_inventory_change_over_lag_assets",
    )
    result["Investment"] = exact("Investment", _safe_ratio(value("capex"), revenue), "capex_over_revenue")
    sales_growth = _safe_ratio(
        difference(revenue, value("revenue", 1)),
        average_required(value("revenue", 1), value("revenue", 2)),
    )
    inventory_growth = _safe_ratio(
        difference(inventory, value("inventory", 1)),
        average_required(value("inventory", 1), value("inventory", 2)),
    )
    result["GrSaleToGrInv"] = exact(
        "GrSaleToGrInv",
        difference(sales_growth, inventory_growth),
        "sales_growth_minus_inventory_growth_using_two_year_average",
    )
    result["PayoutYield"] = exact(
        "PayoutYield",
        _safe_ratio(sum_required(dividends, repurchases), market_cap),
        "dividends_plus_repurchases_over_market_cap",
    )
    result["NetPayoutYield"] = exact(
        "NetPayoutYield",
        _safe_ratio(
            sum_required(
                dividends,
                repurchases,
                -issuance if issuance is not None else None,
            ),
            market_cap,
        ),
        "net_payout_over_market_cap",
    )
    result["NetEquityFinance"] = exact(
        "NetEquityFinance",
        _safe_ratio(difference(issuance, repurchases), average_assets),
        "stock_issuance_minus_repurchases_over_average_assets",
    )
    result["CompositeDebtIssuance"] = exact(
        "CompositeDebtIssuance",
        math.log(debt) - math.log(debt_5y)
        if debt is not None and debt > 0 and debt_5y is not None and debt_5y > 0
        else None,
        "log_total_debt_minus_log_total_debt_five_years_ago",
    )
    debt_issuance = value("debt_issuance")
    result["DebtIssuance"] = exact(
        "DebtIssuance",
        float(debt_issuance > 0) if debt_issuance is not None else None,
        "long_term_debt_issuance_positive_indicator",
    )
    result["NetDebtFinance"] = exact("NetDebtFinance", _safe_ratio(delta("debt_long"), assets_lag), "net_debt_change_over_lag_assets")
    result["NetDebtPrice"] = exact(
        "NetDebtPrice",
        _safe_ratio(difference(debt, cash), market_cap),
        "net_debt_over_market_cap",
    )
    result["OPLeverage"] = exact(
        "OPLeverage",
        _safe_ratio(sum_required(sga, cogs), assets),
        "sga_plus_cogs_over_assets",
    )
    operating_profit = None
    interest = value("interest")
    if equity is not None:
        operating_profit = weighted_sum_required(
            (1.0, revenue),
            (-1.0, cogs),
            (-1.0, sga),
            (-1.0, interest),
        )
    result["OperProf"] = exact(
        "OperProf",
        _safe_ratio(operating_profit, equity),
        "revenue_minus_cogs_sga_interest_over_book_equity",
    )
    debt_reduction = value("debt_reduction")
    external_finance = sum_required(
        issuance,
        -dividends if dividends is not None else None,
        -repurchases if repurchases is not None else None,
        debt_issuance,
        -debt_reduction if debt_reduction is not None else None,
    )
    result["XFIN"] = exact(
        "XFIN",
        _safe_ratio(external_finance, assets),
        "issuance_minus_dividends_repurchases_plus_net_debt_issuance_over_assets",
    )
    result["ShareIss1Y"] = exact("ShareIss1Y", growth("shares"), "shares_growth_1y")
    result["ShareIss5Y"] = exact("ShareIss5Y", growth("shares", 5), "shares_growth_5y")
    tangible = None
    receivables = value("receivables")
    if assets is not None:
        tangible = weighted_sum_required(
            (1.0, cash),
            (0.715, receivables),
            (0.547, inventory),
            (0.535, ppe),
        )
    result["tang"] = exact("tang", _safe_ratio(tangible, assets), "berger_tangibility_over_assets")
    result["OrderBacklog"] = exact("OrderBacklog", _safe_ratio(value("backlog"), assets), "order_backlog_over_assets")
    result["OrderBacklogChg"] = exact("OrderBacklogChg", growth("backlog"), "order_backlog_growth_1y")
    result["hire"] = exact("hire", growth("employees"), "employee_growth_1y")
    return result


UNAVAILABLE_BY_SOURCE = {
    "CitationsRD": "Requires patent citation data",
    "CustomerMomentum": "Requires historical customer-company links",
    "Governance": "Requires the original governance index",
    "PatentsRD": "Requires patent counts and citations",
    "iomom_supp": "Requires BEA supplier-network data",
    "ExchSwitch": "Requires historical exchange-switch events",
    "ProbInformedTrading": "Requires intraday trade classification or published PIN estimates",
}


UNIMPLEMENTED_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "AbnormalAccruals": ("cross_sectional_regression", "Requires the annual industry cross-sectional modified-Jones regression"),
    "AccrualsBM": ("cross_sectional_double_sort", "Requires current cross-sectional accrual and book-to-market quintiles"),
    "AnnouncementReturn": ("earnings_event_history", "Requires causal quarterly earnings announcement dates and event returns"),
    "BMdec": ("historical_december_market_cap", "Requires the most recent December market-equity snapshot"),
    "BPEBM": ("additional_sec_concepts", "Requires preferred stock and deferred-charge concepts aligned to the official formula"),
    "BetaLiquidityPS": ("external_liquidity_factor", "Requires the Pastor-Stambaugh liquidity innovation series and a 60-month regression"),
    "BetaTailRisk": ("cross_sectional_tail_factor", "Requires a 120-month regression on a market-wide daily tail-risk factor"),
    "BrandInvest": ("brand_investment_history", "Requires the paper's accumulated advertising-capital construction"),
    "CBOperProf": ("industry_adjusted_accounting", "Requires the official conservative operating-profitability construction"),
    "CashProd": ("official_formula_pending", "SEC inputs exist, but the official cash-productivity formula is not yet implemented"),
    "ChAssetTurnover": ("annual_history_formula_pending", "Requires two causally available annual asset-turnover observations"),
    "ChInvIA": ("historical_industry_membership", "Requires annual capex growth and historical two-digit SIC industry means"),
    "ChNNCOA": ("additional_sec_concepts", "Requires non-current investments and the complete non-current operating-assets formula"),
    "CompEquIss": ("historical_market_cap", "Requires five-year market-equity growth and five-year stock return"),
    "CompositeDebtIssuance": ("five_year_debt_history", "Requires comparable current and five-year-lagged total debt"),
    "ConvDebt": ("convertible_debt_classification", "Requires a reliable convertible-debt concept not consistently present in SEC XBRL"),
    "CoskewACX": ("market_regression", "Requires one year of aligned daily stock and value-weighted market returns"),
    "Coskewness": ("market_regression", "Requires 60 months of aligned stock and value-weighted market excess returns"),
    "DebtIssuance": ("debt_issuance_cash_flow", "Requires a consistently mapped long-term debt issuance cash-flow concept"),
    "DelCOA": ("additional_sec_concepts", "Requires current operating assets and comparable annual lags"),
    "DelCOL": ("additional_sec_concepts", "Requires current operating liabilities and comparable annual lags"),
    "DelEqu": ("annual_history_formula_pending", "Requires book-equity change scaled by average annual assets"),
    "DelFINL": ("additional_sec_concepts", "Requires preferred stock plus current and long-term debt annual changes"),
    "DelLTI": ("long_term_investments", "Requires investments-and-advances history"),
    "DelNetFin": ("additional_sec_concepts", "Requires short- and long-term investments, debt and preferred stock history"),
    "DivYieldST": ("distribution_code_history", "Yahoo dividends do not contain CRSP distribution codes required by the official bins"),
    "EBM": ("additional_sec_concepts", "Requires preferred stock and deferred-charge concepts aligned to the official formula"),
    "EarnSupBig": ("historical_industry_membership", "Requires quarterly earnings surprise and historical FF48 large-firm industry means"),
    "EarningsConsistency": ("quarterly_eps_history", "Requires at least 48 months of comparable causal quarterly EPS"),
    "EarningsStreak": ("point_in_time_analyst_history", "Requires point-in-time IBES actuals and forecasts"),
    "EarningsSurprise": ("quarterly_eps_history", "Requires causal quarterly EPS and an eight-quarter drift history"),
    "EntMult": ("additional_sec_concepts", "Requires operating income before depreciation and deferred charges"),
    "EquityDuration": ("official_code_required", "The metadata delegates the formula to official code; no safe two-source implementation is frozen"),
    "FirmAgeMom": ("cross_sectional_age_sort", "Requires firm-age quintiles and six-month momentum after a historical listing-date audit"),
    "Frontier": ("rolling_cross_sectional_regression", "Requires a rolling 60-month cross-sectional regression with industry dummies"),
    "GrLTNOA": ("additional_sec_concepts", "Requires the complete long-term net operating-assets and accrual formulas"),
    "GrSaleToGrInv": ("annual_history_formula_pending", "Requires comparable two-year revenue and inventory histories"),
    "Herf": ("historical_industry_membership", "Requires three-digit SIC revenue shares and a three-year rolling industry index"),
    "HerfBE": ("historical_industry_membership", "Requires three-digit SIC book-equity shares and a three-year rolling industry index"),
    "IdioVol3F": ("factor_returns", "Requires daily Fama-French three-factor residuals"),
    "IntanBM": ("rolling_cross_sectional_regression", "Requires the paper's monthly five-year cross-sectional regression"),
    "IntanCFP": ("rolling_cross_sectional_regression", "Requires the paper's monthly five-year cross-sectional regression"),
    "IntanEP": ("rolling_cross_sectional_regression", "Requires the paper's monthly five-year cross-sectional regression"),
    "IntanSP": ("rolling_cross_sectional_regression", "Requires the paper's monthly five-year cross-sectional regression"),
    "MS": ("official_code_required", "Requires the full low-BM Mohanram score construction and cross-sectional eligibility filter"),
    "MeanRankRevGrowth": ("five_year_cross_sectional_ranks", "Requires annual revenue-growth ranks for five historical cross-sections"),
    "Mom6mJunk": ("credit_rating_history", "Requires a causal issuer credit-rating history"),
    "MomRev": ("cross_sectional_double_sort", "Requires current cross-sectional Mom6m and Mom36m quintiles"),
    "MomVol": ("historical_turnover_sort", "Requires independent momentum and six-month turnover portfolio sorts"),
    "NetEquityFinance": ("equity_cash_flow_mapping", "Requires consistently mapped stock sale and repurchase cash flows"),
    "NumEarnIncrease": ("quarterly_income_history", "Requires up to eight consecutive year-over-year quarterly income comparisons"),
    "OPLeverage": ("official_formula_pending", "SEC cost and SG&A inputs exist, but the official formula is not yet implemented"),
    "OScore": ("gnp_deflator_and_industry_filter", "Requires the historical GNP deflator and official industry exclusions"),
    "OperProf": ("official_formula_pending", "SEC inputs exist, but the official operating-profitability formula and size filter are not yet implemented"),
    "OrgCap": ("capitalized_sga_history", "Requires recursively capitalized SG&A organization capital"),
    "PS": ("piotroski_cross_section", "Requires all nine Piotroski inputs plus the high book-to-market eligibility quintile"),
    "PctTotAcc": ("cash_flow_statement_components", "Requires complete financing and investing cash-flow components"),
    "PriceDelayRsq": ("market_regression", "Requires the annual daily market-lag regression and July refresh rule"),
    "ResidualMomentum": ("factor_returns", "Requires 36 months of Fama-French residual returns"),
    "ReturnSkew3F": ("factor_returns", "Requires daily Fama-French three-factor residuals"),
    "RevenueSurprise": ("quarterly_revenue_per_share_history", "Requires causal quarterly revenue-per-share history and rolling standardization"),
    "ShortInterest": ("short_interest_history", "SEC and Yahoo do not provide the required causal mid-month short-interest series"),
    "SurpriseRD": ("annual_history_formula_pending", "Requires comparable annual R&D, revenue and assets growth"),
    "Tax": ("tax_component_mapping", "Requires federal, foreign and deferred tax components mapped consistently"),
    "XFIN": ("cash_flow_statement_components", "Requires stock issuance, repurchase, dividends and debt issue/reduction flows"),
    "betaVIX": ("vix_market_regression", "Requires aligned daily VIX changes, market returns and stock excess returns"),
    "retConglomerate": ("business_segment_history", "Requires causal Compustat business-segment sales and stand-alone industry returns"),
    "roaq": ("quarterly_income_history", "Requires a clean quarterly net-income series divided by lagged quarterly assets"),
}


def classify_missing_signal(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Classify a non-computed predictor without claiming nonexistent data."""

    name = str(row.get("signalname", ""))
    category = str(row.get("Cat.Data", ""))
    if name in UNAVAILABLE_BY_SOURCE:
        return "unavailable", "missing_external_source", UNAVAILABLE_BY_SOURCE[name]
    if name in UNIMPLEMENTED_REQUIREMENTS:
        source, note = UNIMPLEMENTED_REQUIREMENTS[name]
        return "unavailable", source, note
    if category == "13F":
        return "proxy", "yfinance_institutional_snapshot", "Current Yahoo holder snapshot is not historical Thomson/SEC 13F reconstruction"
    if category == "Options":
        return "proxy", "yfinance_current_option_chain", "Current chain cannot reproduce historical OptionMetrics construction"
    if category == "Analyst":
        return "proxy", "yfinance_analyst_snapshot", "Yahoo current snapshot is not a point-in-time IBES history"
    if category == "Event":
        return "proxy", "sec_submission_or_yfinance_event", "Event definition requires additional event reconstruction"
    return "unavailable", "formula_not_implemented", "Data may exist, but the official formula has not been reproduced safely"


def assemble_feature_table(
    metadata: pd.DataFrame,
    values_by_symbol: Mapping[str, Mapping[str, FeatureValue]],
    *,
    as_of: str,
    redundancy_groups: pd.DataFrame | None = None,
    security_context: pd.DataFrame | None = None,
    exact_source_multiplier: float = 1.0,
    proxy_source_multiplier: float = 0.55,
) -> pd.DataFrame:
    """Produce one audited long row per symbol and strict predictor."""

    group_map: dict[str, str] = {}
    if redundancy_groups is not None and not redundancy_groups.empty:
        group_map = redundancy_groups.set_index("signalname")["redundancy_group"].astype(str).to_dict()
    meta = metadata.set_index("signalname", drop=False)
    rows: list[dict[str, Any]] = []
    for symbol, feature_values in sorted(values_by_symbol.items()):
        for signal, definition in meta.iterrows():
            computed = feature_values.get(str(signal))
            if computed is None:
                status, source, note = classify_missing_signal(definition)
                raw_value = None
                formula_id = ""
            else:
                status, source, note = computed.status, computed.source, computed.note
                raw_value = computed.raw_value
                formula_id = computed.formula_id
            implementation_status = status
            value_status = "available" if raw_value is not None and pd.notna(raw_value) else "missing"
            if value_status == "missing":
                status = "unavailable"
            sign = float(definition.get("Sign")) if pd.notna(definition.get("Sign")) else 1.0
            horizon_raw = pd.to_numeric(pd.Series([definition.get("portperiod")]), errors="coerce").iloc[0]
            horizon = int(horizon_raw) if pd.notna(horizon_raw) else 1
            if horizon not in SUPPORTED_HORIZONS:
                horizon = min(SUPPORTED_HORIZONS, key=lambda item: abs(item - horizon))
            rows.append(
                {
                    "as_of": as_of,
                    "symbol": symbol,
                    "signalname": signal,
                    "raw_value": raw_value,
                    "sign": sign,
                    "status": status,
                    "implementation_status": implementation_status,
                    "value_status": value_status,
                    "source": source,
                    "formula_id": formula_id,
                    "note": note,
                    "horizon_months": horizon,
                    "official_portfolio_period_months": horizon,
                    "official_start_month": definition.get("startmonth"),
                    "official_stock_weight": definition.get("sweight"),
                    "official_ls_quantile": definition.get("q_cut"),
                    "official_quantile_filter": definition.get("q_filt"),
                    "official_filter_expression": definition.get("filterstr"),
                    "horizon_semantics": "official_portfolio_refresh_period_not_tested_forecast_horizon",
                    "data_family": definition.get("Cat.Data"),
                    "economic_family": definition.get("Cat.Economic"),
                    "tstat_reproduction": definition.get("tstat"),
                    "tstat_study": definition.get("T.Stat"),
                    "redundancy_group": group_map.get(str(signal), f"single_{signal}"),
                    "evidence_weight": evidence_weight(
                        definition,
                        status,
                        exact_source_multiplier=exact_source_multiplier,
                        proxy_source_multiplier=proxy_source_multiplier,
                    ),
                }
            )
    frame = pd.DataFrame(rows)
    frame["potential_evidence_weight"] = frame["evidence_weight"]
    frame["percentile"] = np.nan
    frame["score_percentile"] = np.nan
    frame["official_filter_pass"] = True
    frame["official_filter_status"] = "none"
    frame["official_portfolio_bucket"] = "unavailable"
    context = pd.DataFrame(index=sorted(values_by_symbol))
    if security_context is not None and not security_context.empty:
        context = security_context.copy()
        if "symbol" in context:
            context = context.drop_duplicates("symbol").set_index("symbol")
        context.index = context.index.astype(str)
        context = context.reindex(sorted(values_by_symbol))
    if "exchange_code" not in context:
        exchange_source = context.get(
            "exchange_sec",
            context.get("exchange", pd.Series(index=context.index, dtype="string")),
        )
        context["exchange_code"] = exchange_source.map(_normalise_exchange)
    if "market_cap" not in context:
        context["market_cap"] = pd.to_numeric(
            context.get("marketCap", pd.Series(index=context.index, dtype=float)),
            errors="coerce",
        )
    if "current_price" not in context:
        context["current_price"] = np.nan
    if "eligible_common_stock" not in context:
        context["eligible_common_stock"] = True
    nyse_caps = pd.to_numeric(
        context.loc[context["exchange_code"].eq(1), "market_cap"], errors="coerce"
    ).dropna()
    context["nyse_market_cap_p20"] = (
        float(nyse_caps.quantile(0.20)) if not nyse_caps.empty else np.nan
    )

    for signal, index in frame.groupby("signalname").groups.items():
        definition = meta.loc[signal]
        signal_index = pd.Index(index)
        symbols = frame.loc[signal_index, "symbol"].astype(str)
        signal_context = context.reindex(symbols).copy()
        signal_context.index = signal_index
        filter_mask, filter_status = official_filter_mask(definition, signal_context)
        available = frame.loc[signal_index, "raw_value"].notna()
        eligible = available & filter_mask
        frame.loc[signal_index, "official_filter_pass"] = filter_mask.to_numpy(dtype=bool)
        frame.loc[signal_index, "official_filter_status"] = filter_status
        excluded = available & ~filter_mask
        if excluded.any():
            excluded_index = signal_index[excluded.to_numpy()]
            frame.loc[excluded_index, "status"] = "unavailable"
            frame.loc[excluded_index, "value_status"] = "official_filter_excluded"
            frame.loc[excluded_index, "evidence_weight"] = 0.0
        sign = float(frame.loc[signal_index, "sign"].iloc[0])
        aligned = pd.to_numeric(frame.loc[signal_index, "raw_value"], errors="coerce") * sign
        q_filter = str(definition.get("q_filt") or "").strip().upper()
        if q_filter == "NYSE":
            reference_mask = eligible & signal_context["exchange_code"].eq(1)
        else:
            reference_mask = eligible
        percentiles = _reference_percentile(aligned.where(eligible), aligned.where(reference_mask))
        frame.loc[signal_index, "percentile"] = percentiles

        form = str(definition.get("Cat.Form") or "continuous").strip().lower()
        q_raw = pd.to_numeric(pd.Series([definition.get("q_cut")]), errors="coerce").iloc[0]
        q_cut = float(q_raw) if pd.notna(q_raw) else 0.20
        if form == "continuous":
            reference_values = aligned.where(reference_mask).dropna()
            if reference_values.empty:
                low = pd.Series(False, index=signal_index)
                high = pd.Series(False, index=signal_index)
            else:
                low_break = float(reference_values.quantile(q_cut))
                high_break = float(reference_values.quantile(1.0 - q_cut))
                if low_break >= high_break:
                    low = pd.Series(False, index=signal_index)
                    high = pd.Series(False, index=signal_index)
                else:
                    low = aligned.le(low_break) & eligible
                    high = aligned.ge(high_break) & eligible
            frame.loc[signal_index[low.fillna(False).to_numpy()], "official_portfolio_bucket"] = "short"
            frame.loc[signal_index[high.fillna(False).to_numpy()], "official_portfolio_bucket"] = "long"
            middle = eligible & ~(low.fillna(False) | high.fillna(False))
            frame.loc[signal_index[middle.to_numpy()], "official_portfolio_bucket"] = "neutral"
            score_percentile = percentiles.where(low | high, 50.0).where(eligible)
        else:
            frame.loc[signal_index[eligible.to_numpy()], "official_portfolio_bucket"] = "discrete"
            score_percentile = percentiles.where(eligible)
        frame.loc[signal_index, "score_percentile"] = score_percentile
    return frame


def calculate_scores(
    features: pd.DataFrame,
    minimum_metrics: int = 5,
    *,
    maximum_metric_weight_multiple: float = 2.0,
    maximum_family_weight: float = 0.15,
) -> pd.DataFrame:
    """Aggregate comparable scores with one fixed vote per redundancy group.

    Every symbol uses the same denominator within a score bucket.  Missing or
    officially filtered observations contribute a neutral 50 and lower
    confidence instead of silently changing the basket of metrics.
    """

    potential_column = (
        "potential_evidence_weight"
        if "potential_evidence_weight" in features
        else "evidence_weight"
    )
    formula_available = features.groupby("signalname")["formula_id"].transform(
        lambda values: values.fillna("").astype(str).str.len().gt(0).any()
    )
    canonical = features.loc[
        features["implementation_status"].isin(["exact", "proxy"])
        & pd.to_numeric(features[potential_column], errors="coerce").gt(0)
        & formula_available
    ].copy()
    if canonical.empty:
        return pd.DataFrame(
            columns=[
                "as_of", "symbol", "horizon_months", "score", "confidence",
                "metrics_used", "metrics_expected", "groups_used", "groups_expected",
                "maximum_family_weight_actual",
            ]
        )

    canonical["potential_weight"] = pd.to_numeric(
        canonical[potential_column], errors="coerce"
    ).fillna(0.0)
    metric_meta = canonical.groupby(
        ["horizon_months", "signalname", "redundancy_group"], as_index=False
    ).agg(
        potential_weight=("potential_weight", "max"),
        economic_family=("economic_family", lambda values: "|".join(sorted(set(map(str, values))))),
    )
    median_weight = metric_meta.groupby("horizon_months")["potential_weight"].transform("median")
    metric_meta["potential_weight"] = np.minimum(
        metric_meta["potential_weight"],
        median_weight * float(maximum_metric_weight_multiple),
    )
    group_weight_sum = metric_meta.groupby(
        ["horizon_months", "redundancy_group"]
    )["potential_weight"].transform("sum")
    metric_meta["within_group_weight"] = (
        metric_meta["potential_weight"] / group_weight_sum.replace(0, np.nan)
    )
    group_meta = metric_meta.groupby(
        ["horizon_months", "redundancy_group"], as_index=False
    ).agg(
        group_evidence=("potential_weight", "mean"),
        metrics_expected=("signalname", "nunique"),
        economic_family=("economic_family", lambda values: "|".join(sorted(set(values)))),
    )
    family_evidence = group_meta.groupby(
        ["horizon_months", "economic_family"], as_index=False
    )["group_evidence"].sum()
    family_targets: list[pd.DataFrame] = []
    for horizon, horizon_families in family_evidence.groupby("horizon_months"):
        part = horizon_families.copy()
        raw = part.set_index("economic_family")["group_evidence"].astype(float)
        if raw.le(0).all():
            part["family_target_weight"] = 0.0
            family_targets.append(part)
            continue
        cap = float(maximum_family_weight)
        if cap <= 0 or cap > 1:
            raise OpenAPDataError("maximum_family_weight must be in (0, 1]")
        positive = raw.loc[raw.gt(0)]
        if len(positive) * cap < 1.0 - 1e-12:
            target = pd.Series(0.0, index=raw.index, dtype=float)
            target.loc[positive.index] = 1.0 / len(positive)
            part["family_target_weight"] = part["economic_family"].map(target).fillna(0.0)
            family_targets.append(part)
            continue
        target = pd.Series(0.0, index=raw.index, dtype=float)
        remaining = list(positive.index)
        remaining_weight = 1.0
        while remaining:
            denominator = float(raw.loc[remaining].sum())
            proposal = (
                raw.loc[remaining] / denominator * remaining_weight
                if denominator > 0
                else pd.Series(remaining_weight / len(remaining), index=remaining)
            )
            over = proposal.loc[proposal.gt(cap + 1e-12)].index.tolist()
            if not over:
                target.loc[remaining] = proposal
                break
            target.loc[over] = cap
            remaining_weight -= cap * len(over)
            remaining = [family for family in remaining if family not in over]
        part["family_target_weight"] = part["economic_family"].map(target).fillna(0.0)
        family_targets.append(part)
    family_weights = pd.concat(family_targets, ignore_index=True)
    group_meta = group_meta.merge(
        family_weights[
            ["horizon_months", "economic_family", "group_evidence", "family_target_weight"]
        ].rename(columns={"group_evidence": "family_evidence"}),
        on=["horizon_months", "economic_family"],
        how="left",
    )
    group_meta["fixed_group_weight"] = (
        group_meta["family_target_weight"]
        * group_meta["group_evidence"]
        / group_meta["family_evidence"].replace(0, np.nan)
    ).fillna(0.0)

    working = canonical.merge(
        metric_meta[
            ["horizon_months", "signalname", "redundancy_group", "within_group_weight"]
        ],
        on=["horizon_months", "signalname", "redundancy_group"],
        how="inner",
    )
    observed = (
        working["status"].isin(["exact", "proxy"])
        & working["score_percentile"].notna()
        & pd.to_numeric(working["evidence_weight"], errors="coerce").gt(0)
    )
    working["observed"] = observed
    working["comparable_percentile"] = pd.to_numeric(
        working["score_percentile"], errors="coerce"
    ).where(observed, 50.0)
    working["group_score_component"] = (
        working["comparable_percentile"] * working["within_group_weight"]
    )
    working["observed_weight_component"] = (
        working["within_group_weight"] * observed.astype(float)
    )
    groups = working.groupby(
        ["as_of", "symbol", "horizon_months", "redundancy_group"], as_index=False
    ).agg(
        group_score=("group_score_component", "sum"),
        observed_group_fraction=("observed_weight_component", "sum"),
        metrics_used=("observed", "sum"),
    )
    groups = groups.merge(
        group_meta[
            [
                "horizon_months", "redundancy_group", "fixed_group_weight",
                "family_target_weight", "metrics_expected",
            ]
        ],
        on=["horizon_months", "redundancy_group"],
        how="left",
    )
    groups["weighted_score"] = groups["group_score"] * groups["fixed_group_weight"]
    groups["observed_group_weight"] = (
        groups["fixed_group_weight"] * groups["observed_group_fraction"]
    )
    groups["group_used"] = groups["metrics_used"].gt(0)
    summary = groups.groupby(["as_of", "symbol", "horizon_months"], as_index=False).agg(
        weighted_sum=("weighted_score", "sum"),
        fixed_total_weight=("fixed_group_weight", "sum"),
        observed_total_weight=("observed_group_weight", "sum"),
        groups_used=("group_used", "sum"),
        groups_expected=("redundancy_group", "nunique"),
        metrics_used=("metrics_used", "sum"),
        metrics_expected=("metrics_expected", "sum"),
        maximum_family_weight_actual=("family_target_weight", "max"),
    )
    summary["score"] = summary["weighted_sum"] / summary["fixed_total_weight"].replace(0, np.nan)
    summary["confidence"] = (
        100.0
        * summary["observed_total_weight"]
        / summary["fixed_total_weight"].replace(0, np.nan)
    ).clip(0.0, 100.0)
    insufficient = summary["metrics_used"].lt(int(minimum_metrics))
    summary.loc[insufficient, "score"] = np.nan
    summary.loc[insufficient, "confidence"] = 0.0

    symbols = sorted(features["symbol"].astype(str).unique())
    as_of_values = sorted(features["as_of"].astype(str).unique())
    output_horizons = sorted(
        set(SUPPORTED_HORIZONS)
        | set(pd.to_numeric(canonical["horizon_months"], errors="coerce").dropna().astype(int))
    )
    grid = pd.MultiIndex.from_product(
        [as_of_values, symbols, output_horizons],
        names=["as_of", "symbol", "horizon_months"],
    ).to_frame(index=False)
    result = grid.merge(summary, on=["as_of", "symbol", "horizon_months"], how="left")
    count_columns = ["metrics_used", "metrics_expected", "groups_used", "groups_expected"]
    result[count_columns] = result[count_columns].fillna(0).astype(int)
    result["confidence"] = result["confidence"].fillna(0.0)
    result["minimum_metrics_required"] = int(minimum_metrics)
    result["horizon_evidence_sufficient"] = result["metrics_used"].ge(int(minimum_metrics))
    return result[
        [
            "as_of", "symbol", "horizon_months", "score", "confidence",
            "metrics_used", "metrics_expected", "groups_used", "groups_expected",
            "minimum_metrics_required", "horizon_evidence_sufficient",
            "maximum_family_weight_actual",
        ]
    ]


def calculate_aggregate_scores(
    scores: pd.DataFrame,
    *,
    minimum_horizons: int | None = None,
    required_horizons: Sequence[int] = DEFAULT_REQUIRED_SCORE_BUCKETS,
    minimum_confidence: float = 30.0,
) -> pd.DataFrame:
    """Combine only score buckets with enough independent evidence.

    ``portperiod`` is OpenAP's portfolio refresh period, not a separately
    validated forecast horizon.  The compatibility column remains named
    ``horizon_months``.  The current ranking passes a synthetic bucket 0 that
    contains all predictors together; official refresh-period buckets remain
    diagnostic only.
    """

    columns = [
        "as_of",
        "symbol",
        "aggregate_score",
        "aggregate_confidence",
        "horizons_used",
        "all_horizons_present",
        "required_horizons",
        "ranking_eligible",
        "ranking_rejection_reason",
        "score_validation_status",
    ]
    if scores.empty:
        return pd.DataFrame(columns=columns)
    frame = scores.copy()
    required = tuple(sorted({int(value) for value in required_horizons}))
    if minimum_horizons is not None and minimum_horizons != len(required):
        raise OpenAPDataError(
            "minimum_horizons must match the explicit required_horizons length"
        )
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0)
    required_frame = frame.loc[frame["horizon_months"].isin(required)].copy()
    usable = required_frame.loc[
        required_frame["score"].notna() & required_frame["confidence"].gt(0)
    ].copy()
    usable["horizon_weight"] = usable["confidence"] / 100.0
    usable["weighted_score"] = usable["score"] * usable["horizon_weight"]
    if usable.empty:
        result = frame[["as_of", "symbol"]].drop_duplicates()
        result["aggregate_score"] = np.nan
        result["aggregate_confidence"] = 0.0
        result["horizons_used"] = 0
        result["all_horizons_present"] = False
        result["required_horizons"] = "|".join(map(str, required))
        result["ranking_eligible"] = False
        result["ranking_rejection_reason"] = "no_usable_horizons"
        result["score_validation_status"] = "unvalidated_current_snapshot_only"
        return result[columns]
    result = usable.groupby(["as_of", "symbol"], as_index=False).agg(
        weighted_sum=("weighted_score", "sum"),
        total_weight=("horizon_weight", "sum"),
        mean_confidence=("confidence", "mean"),
        horizons_used=("horizon_months", "nunique"),
    )
    result["aggregate_score"] = result["weighted_sum"] / result["total_weight"].replace(0, np.nan)
    result["aggregate_confidence"] = (
        result["mean_confidence"] * result["horizons_used"] / max(len(required), 1)
    )
    grid = frame[["as_of", "symbol"]].drop_duplicates()
    result = grid.merge(result, on=["as_of", "symbol"], how="left")
    result["aggregate_confidence"] = result["aggregate_confidence"].fillna(0.0)
    result["horizons_used"] = result["horizons_used"].fillna(0).astype(int)
    present = (
        usable.assign(present=True)
        .pivot_table(
            index=["as_of", "symbol"],
            columns="horizon_months",
            values="present",
            aggfunc="any",
            fill_value=False,
        )
        .reset_index()
    )
    for horizon in required:
        if horizon not in present:
            present[horizon] = False
    present["all_horizons_present"] = present[list(required)].all(axis=1)
    result = result.drop(columns=["all_horizons_present"], errors="ignore").merge(
        present[["as_of", "symbol", "all_horizons_present"]],
        on=["as_of", "symbol"],
        how="left",
    )
    result["all_horizons_present"] = result["all_horizons_present"].fillna(False)
    result["required_horizons"] = "|".join(map(str, required))
    result["ranking_eligible"] = result["all_horizons_present"] & result["aggregate_confidence"].ge(float(minimum_confidence))
    result["ranking_rejection_reason"] = np.select(
        [
            result["horizons_used"].eq(0),
            ~result["all_horizons_present"],
            result["aggregate_confidence"].lt(float(minimum_confidence)),
        ],
        ["no_usable_horizons", "incomplete_horizons", "aggregate_confidence_too_low"],
        default="",
    )
    result["score_validation_status"] = "unvalidated_current_snapshot_only"
    return result[columns]


def coverage_report(features: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    """Summarise exact, proxy and unavailable coverage per predictor."""

    rows = []
    total_symbols = int(features["symbol"].nunique()) if not features.empty else 0
    for signal, group in features.groupby("signalname", sort=True):
        has_value = group["raw_value"].notna()
        exact_values = int((has_value & group["status"].eq("exact")).sum())
        proxy_values = int((has_value & group["status"].eq("proxy")).sum())
        values = exact_values + proxy_values
        dominant = "unavailable"
        if exact_values and proxy_values:
            dominant = "mixed"
        elif exact_values:
            dominant = "exact"
        elif proxy_values:
            dominant = "proxy"
        meta = metadata.loc[metadata["signalname"].eq(signal)].iloc[0]
        sources = sorted({str(item) for item in group.loc[has_value, "source"].dropna() if str(item)})
        reasons = sorted({str(item) for item in group.loc[~has_value, "source"].dropna() if str(item)})
        notes = sorted({str(item) for item in group["note"].dropna() if str(item)})
        formulas = sorted({str(item) for item in group.loc[has_value, "formula_id"].dropna() if str(item)})
        rows.append(
            {
                "signalname": signal,
                "data_family": meta.get("Cat.Data"),
                "economic_family": meta.get("Cat.Economic"),
                "coverage_status": dominant,
                "symbols_with_value": values,
                "total_symbols": total_symbols,
                "coverage_pct": 100.0 * values / total_symbols if total_symbols else 0.0,
                "exact_rows": exact_values,
                "proxy_rows": proxy_values,
                "unavailable_rows": int(total_symbols - values),
                "value_sources": " | ".join(sources),
                "unavailable_reasons": " | ".join(reasons),
                "notes": " | ".join(notes),
                "formula_ids": " | ".join(formulas),
            }
        )
    report = pd.DataFrame(rows)
    if len(report) != EXPECTED_PREDICTORS:
        raise OpenAPDataError(f"Coverage report must contain {EXPECTED_PREDICTORS} predictors, found {len(report)}")
    return report


def write_summary(path: str | Path, payload: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(dict(payload), indent=2, default=str), encoding="utf-8")


__all__ = [
    "EXPECTED_PREDICTORS",
    "DEFAULT_REQUIRED_SCORE_BUCKETS",
    "FeatureValue",
    "OpenAPDataError",
    "SEC_CONCEPT_ALIASES",
    "assemble_feature_table",
    "build_redundancy_groups",
    "calculate_accounting_features",
    "calculate_aggregate_scores",
    "calculate_price_features",
    "calculate_scores",
    "classify_missing_signal",
    "coverage_report",
    "evidence_weight",
    "latest_sec_concepts",
    "latest_sec_concept_inputs",
    "official_filter_mask",
    "refine_current_redundancy_groups",
    "sec_concepts_from_inputs",
    "select_strict_predictors",
    "sha256_file",
    "signed_percentile",
    "write_summary",
]

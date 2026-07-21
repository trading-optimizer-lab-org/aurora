"""Post-lock diagnostic audit for the frozen stock protocol strategy.

This module never searches for a strategy.  It treats the immutable opportunity
ledgers as event-study observations and provides deterministic portfolio,
currency, calendar, benchmark and concentration diagnostics.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats


AUDIT_ROLE = "diagnostic_reanalysis_of_opened_locked_period"
CUTOFF = pd.Timestamp("2026-07-17")
PERIODS = {
    "walk_forward_is": (pd.Timestamp("2008-01-01"), pd.Timestamp("2015-12-31")),
    "diagnostic_reused_holdout": (
        pd.Timestamp("2016-01-01"),
        pd.Timestamp("2020-12-31"),
    ),
    "opened_locked_diagnostic": (
        pd.Timestamp("2021-03-11"),
        CUTOFF,
    ),
}


def label_analysis_role(frame: pd.DataFrame) -> pd.DataFrame:
    """Label every period row without presenting opened locked data as fresh OOS."""

    if "period" not in frame.columns:
        raise ValueError("analysis-role labelling requires a period column")
    labelled = frame.copy()
    labelled["analysis_role"] = np.where(
        labelled["period"].astype(str).eq("opened_locked_diagnostic"),
        AUDIT_ROLE,
        labelled["period"].astype(str),
    )
    return labelled


@dataclass(frozen=True)
class MarketMetadata:
    country: str
    market: str
    exchange: str
    currency: str
    price_scale: float = 1.0


# Yahoo suffixes retained by the immutable dataset as ``SYMBOL-SUFFIX``.
SUFFIX_METADATA: dict[str, MarketMetadata] = {
    "TO": MarketMetadata("Canada", "Canada", "TSX", "CAD"),
    "V": MarketMetadata("Canada", "Canada", "TSXV", "CAD"),
    "L": MarketMetadata("United Kingdom", "United Kingdom", "LSE", "GBP", 0.01),
    "PA": MarketMetadata("France", "Eurozone", "Euronext Paris", "EUR"),
    "AS": MarketMetadata("Netherlands", "Eurozone", "Euronext Amsterdam", "EUR"),
    "BR": MarketMetadata("Belgium", "Eurozone", "Euronext Brussels", "EUR"),
    "LS": MarketMetadata("Portugal", "Eurozone", "Euronext Lisbon", "EUR"),
    "DE": MarketMetadata("Germany", "Eurozone", "Xetra", "EUR"),
    "F": MarketMetadata("Germany", "Eurozone", "Frankfurt", "EUR"),
    "MI": MarketMetadata("Italy", "Eurozone", "Borsa Italiana", "EUR"),
    "MC": MarketMetadata("Spain", "Eurozone", "BME", "EUR"),
    "VI": MarketMetadata("Austria", "Eurozone", "Vienna", "EUR"),
    "AT": MarketMetadata("Greece", "Eurozone", "Athens", "EUR"),
    "IR": MarketMetadata("Ireland", "Eurozone", "Euronext Dublin", "EUR"),
    "HE": MarketMetadata("Finland", "Nordics", "Nasdaq Helsinki", "EUR"),
    "ST": MarketMetadata("Sweden", "Nordics", "Nasdaq Stockholm", "SEK"),
    "CO": MarketMetadata("Denmark", "Nordics", "Nasdaq Copenhagen", "DKK"),
    "OL": MarketMetadata("Norway", "Nordics", "Oslo", "NOK"),
    "SW": MarketMetadata("Switzerland", "Switzerland", "SIX", "CHF"),
    "WA": MarketMetadata("Poland", "Central Europe", "Warsaw", "PLN"),
    "PR": MarketMetadata("Czech Republic", "Central Europe", "Prague", "CZK"),
    "BD": MarketMetadata("Hungary", "Central Europe", "Budapest", "HUF"),
    "RO": MarketMetadata("Romania", "Central Europe", "Bucharest", "RON"),
    "IS": MarketMetadata("Turkey", "Turkey", "Istanbul", "TRY"),
    "T": MarketMetadata("Japan", "Japan", "Tokyo", "JPY"),
    "KS": MarketMetadata("South Korea", "South Korea", "Korea Exchange", "KRW"),
    "KQ": MarketMetadata("South Korea", "South Korea", "KOSDAQ", "KRW"),
    "SS": MarketMetadata("China", "China", "Shanghai", "CNY"),
    "SZ": MarketMetadata("China", "China", "Shenzhen", "CNY"),
    "HK": MarketMetadata("Hong Kong", "Hong Kong", "Hong Kong", "HKD"),
    "TW": MarketMetadata("Taiwan", "Taiwan", "Taiwan", "TWD"),
    "TWO": MarketMetadata("Taiwan", "Taiwan", "Taipei Exchange", "TWD"),
    "AX": MarketMetadata("Australia", "Australia", "ASX", "AUD"),
    "NZ": MarketMetadata("New Zealand", "New Zealand", "NZX", "NZD"),
    "SI": MarketMetadata("Singapore", "Singapore", "SGX", "SGD"),
    "KL": MarketMetadata("Malaysia", "Malaysia", "Bursa Malaysia", "MYR"),
    "JK": MarketMetadata("Indonesia", "Indonesia", "IDX", "IDR"),
    "BK": MarketMetadata("Thailand", "Thailand", "SET", "THB"),
    "NS": MarketMetadata("India", "India", "NSE", "INR"),
    "BO": MarketMetadata("India", "India", "BSE", "INR"),
    "TA": MarketMetadata("Israel", "Israel", "Tel Aviv", "ILS"),
    "QA": MarketMetadata("Qatar", "Gulf", "Qatar", "QAR"),
    "SR": MarketMetadata("Saudi Arabia", "Gulf", "Saudi Exchange", "SAR"),
    "AE": MarketMetadata("United Arab Emirates", "Gulf", "Abu Dhabi", "AED"),
    "JO": MarketMetadata("South Africa", "South Africa", "JSE", "ZAR", 0.01),
    "SA": MarketMetadata("Brazil", "Brazil", "B3", "BRL"),
    "MX": MarketMetadata("Mexico", "Mexico", "BMV", "MXN"),
    "BA": MarketMetadata("Argentina", "Argentina", "Buenos Aires", "ARS"),
    "SN": MarketMetadata("Chile", "Chile", "Santiago", "CLP"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def market_metadata(symbol: str) -> tuple[MarketMetadata, str, bool]:
    """Resolve market metadata from the dataset's explicit Yahoo suffix."""

    value = str(symbol).strip().upper()
    suffix = value.rsplit("-", 1)[-1] if "-" in value else ""
    if suffix in SUFFIX_METADATA:
        return SUFFIX_METADATA[suffix], "dataset_yahoo_suffix", False
    # Hyphens such as BRK-A and BF-A are US share classes, not Yahoo markets.
    if suffix in {"A", "B", "C", "P", "R", "U", "W"} or "-" not in value:
        return (
            MarketMetadata("United States", "United States", "US consolidated", "USD"),
            "dataset_unsuffixed_us_convention",
            False,
        )
    return MarketMetadata("unknown", "unknown", "unknown", "unknown"), "unresolved", True


def symbol_metadata_frame(symbols: Iterable[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol in sorted({str(item) for item in symbols}):
        metadata, source, unknown = market_metadata(symbol)
        rows.append(
            {
                "symbol": symbol,
                "country": metadata.country,
                "market": metadata.market,
                "exchange": metadata.exchange,
                "currency": metadata.currency,
                "price_scale_to_currency_unit": metadata.price_scale,
                "metadata_source": source,
                "currency_unknown": unknown,
            }
        )
    return pd.DataFrame(rows)


def _normalised_selection(selection: Mapping[str, Any]) -> tuple[str, float]:
    kind = str(selection.get("kind"))
    value = float(selection.get("value", 0.0))
    if kind == "decile" and int(value) == 1:
        return "top_percent", 10.0
    if kind == "quintile" and int(value) == 1:
        return "top_percent", 20.0
    return kind, value


def functional_component_signature(component: Mapping[str, Any]) -> str:
    """Hash only fields that can change a component's selected observations."""

    variant = dict(component.get("signal_variant", {}))
    # ``portfolio`` was upstream reporting metadata for signal 8 and did not
    # enter its H52 score formula.
    if int(component.get("signal_test_id", -1)) == 8:
        variant.pop("portfolio", None)
    payload = {
        "signal_test_id": int(component["signal_test_id"]),
        "signal_variant": variant,
        "selection": _normalised_selection(dict(component["selection"])),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def component_audit_frames(
    strategy_spec: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    components = [dict(item) for item in strategy_spec.get("component_signals", [])]
    if len(components) != 10:
        raise ValueError(f"frozen ensemble must contain ten components, found {len(components)}")
    rows: list[dict[str, object]] = []
    for index, component in enumerate(components, start=1):
        signature = functional_component_signature(component)
        rows.append(
            {
                "component_index": index,
                "component_id": hashlib.sha256(
                    json.dumps(component, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()[:20],
                "functional_signature": signature,
                "signal_test_id": int(component["signal_test_id"]),
                "signal_variant_json": json.dumps(component["signal_variant"], sort_keys=True),
                "selection_json": json.dumps(component["selection"], sort_keys=True),
                "declared_weight": 0.1,
            }
        )
    full = pd.DataFrame(rows)
    reduced = (
        full.groupby("functional_signature", as_index=False, sort=False)
        .agg(
            component_indices=("component_index", lambda values: ",".join(map(str, values))),
            duplicate_count=("component_index", "size"),
            signal_test_id=("signal_test_id", "first"),
            signal_variant_json=("signal_variant_json", "first"),
            selection_json=("selection_json", "first"),
            effective_weight=("declared_weight", "sum"),
        )
    )
    if not math.isclose(float(reduced["effective_weight"].sum()), 1.0, abs_tol=1e-12):
        raise ValueError("effective component weights do not sum to one")
    full["functionally_duplicated"] = full["functional_signature"].duplicated(False)
    return full, reduced


def _profit_factor(values: pd.Series) -> float:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    gains = float(returns.loc[returns > 0].sum())
    losses = float(-returns.loc[returns < 0].sum())
    return gains / losses if losses > 0 else (math.inf if gains > 0 else 0.0)


def _drawdown(values: pd.Series) -> float:
    series = pd.to_numeric(values, errors="raise")
    return float(series.div(series.cummax()).sub(1.0).min())


def portfolio_metrics(
    curve: pd.DataFrame,
    ledger: pd.DataFrame,
    *,
    observations_per_year: float = 252.0,
) -> dict[str, float]:
    if curve.empty:
        raise ValueError("portfolio curve is empty")
    ordered = curve.sort_values("date").copy()
    equity = pd.to_numeric(ordered["equity"], errors="raise")
    returns = equity.pct_change(fill_method=None).dropna()
    years = max(
        (pd.Timestamp(ordered["date"].iloc[-1]) - pd.Timestamp(ordered["date"].iloc[0])).days
        / 365.2425,
        1.0 / 365.2425,
    )
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)
    volatility = float(returns.std(ddof=1) * math.sqrt(observations_per_year))
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(observations_per_year))
        if returns.std(ddof=1) > 0
        else 0.0
    )
    downside = returns.loc[returns < 0]
    sortino = (
        float(returns.mean() * observations_per_year / (downside.pow(2).mean() ** 0.5 * math.sqrt(observations_per_year)))
        if len(downside) and downside.pow(2).mean() > 0
        else 0.0
    )
    max_drawdown = _drawdown(equity)
    statuses = (
        ledger["status"].astype(str)
        if "status" in ledger
        else pd.Series("closed", index=ledger.index, dtype=str)
    )
    closed = ledger.loc[statuses.eq("closed")].copy()
    net = pd.to_numeric(closed.get("net_return", pd.Series(dtype=float)), errors="coerce")
    monthly = ordered.set_index(pd.to_datetime(ordered["date"]))["equity"].resample("ME").last().pct_change(fill_method=None).dropna()
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "annualized_volatility": volatility,
        "max_drawdown": max_drawdown,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0,
        "average_exposure": float(pd.to_numeric(ordered.get("gross_exposure", 0.0), errors="coerce").mean()),
        "trades": float(len(closed)),
        "win_rate": float((net > 0).mean()) if len(net) else 0.0,
        "profit_factor": _profit_factor(net),
        "worst_day": float(returns.min()) if len(returns) else 0.0,
        "worst_month": float(monthly.min()) if len(monthly) else 0.0,
        "turnover": float(pd.to_numeric(ordered.get("turnover", 0.0), errors="coerce").sum()),
        "average_positions": float(pd.to_numeric(ordered.get("positions", 0.0), errors="coerce").mean()),
        "max_positions": float(pd.to_numeric(ordered.get("positions", 0.0), errors="coerce").max()),
        "average_cash_pct": float(
            pd.to_numeric(ordered.get("cash", 0.0), errors="coerce")
            .div(equity.replace(0, np.nan))
            .mean()
        ),
    }


def enrich_opportunity_paths(
    opportunities: pd.DataFrame,
    panel: pd.DataFrame,
) -> pd.DataFrame:
    """Add independent-trade path diagnostics without applying cash limits."""

    result = opportunities.copy().reset_index(drop=True)
    for column in ("selection_date", "signal_date", "entry_date", "exit_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    source = panel.copy()
    source["date"] = pd.to_datetime(source["date"], errors="raise").dt.normalize()
    source = source.sort_values(["symbol", "date"])
    groups = {symbol: group.reset_index(drop=True) for symbol, group in source.groupby("symbol", sort=False)}
    path_rows: list[dict[str, object]] = []
    for row in result.itertuples(index=False):
        values = row._asdict()
        symbol = str(values["symbol"])
        group = groups.get(symbol)
        entry = pd.Timestamp(values["entry_date"])
        exit_date = pd.Timestamp(values["exit_date"])
        path = group.loc[group["date"].between(entry, exit_date)].copy() if group is not None else pd.DataFrame()
        if path.empty:
            path_rows.append(
                {
                    "holding_sessions": 0,
                    "calendar_days_invested": int((exit_date - entry).days),
                    "maximum_favourable_excursion": np.nan,
                    "maximum_adverse_excursion": np.nan,
                    "trade_path_max_drawdown": np.nan,
                    "dividends_local": np.nan,
                    "entry_adv20_local": np.nan,
                }
            )
            continue
        close = pd.to_numeric(path["close"], errors="coerce")
        adj_close = pd.to_numeric(path["adj_close"], errors="coerce")
        factor = adj_close.div(close.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).ffill().bfill().fillna(1.0)
        adjusted_high = pd.to_numeric(path["high"], errors="coerce").mul(factor)
        adjusted_low = pd.to_numeric(path["low"], errors="coerce").mul(factor)
        entry_adjusted = float(values["entry_price"]) * float(factor.iloc[0])
        adjusted_path = adj_close.dropna()
        adv_source = group.loc[group["date"].lt(entry)].tail(20)
        adv = pd.to_numeric(adv_source["volume"], errors="coerce").mul(
            pd.to_numeric(adv_source["close"], errors="coerce")
        ).mean()
        path_rows.append(
            {
                "holding_sessions": int(len(path)),
                "calendar_days_invested": int((exit_date - entry).days),
                "maximum_favourable_excursion": float(adjusted_high.max() / entry_adjusted - 1.0),
                "maximum_adverse_excursion": float(adjusted_low.min() / entry_adjusted - 1.0),
                "trade_path_max_drawdown": _drawdown(adjusted_path) if len(adjusted_path) else np.nan,
                "dividends_local": float(pd.to_numeric(path["dividends"], errors="coerce").fillna(0).sum()),
                "entry_adv20_local": float(adv) if pd.notna(adv) else np.nan,
            }
        )
    return pd.concat([result, pd.DataFrame(path_rows)], axis=1)


def event_study_statistics(
    opportunities: pd.DataFrame,
    *,
    seed: int = 20260717,
    bootstrap_samples: int = 5000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return summary and inference without computing a portfolio CAGR."""

    values = pd.to_numeric(opportunities["gross_return"], errors="coerce").dropna()
    if len(values) != len(opportunities):
        raise ValueError("every opportunity must have a finite gross return")
    rng = np.random.default_rng(seed)
    array = values.to_numpy(dtype=float)
    ordinary_means = np.empty(bootstrap_samples)
    ordinary_medians = np.empty(bootstrap_samples)
    for index in range(bootstrap_samples):
        sample = rng.choice(array, size=len(array), replace=True)
        ordinary_means[index] = sample.mean()
        ordinary_medians[index] = np.median(sample)
    dated = opportunities.copy()
    dated["entry_date"] = pd.to_datetime(dated["entry_date"], errors="raise")
    dated["entry_year"] = dated["entry_date"].dt.year
    dated["entry_month"] = dated["entry_date"].dt.to_period("M").astype(str)

    def clustered_bootstrap(group_column: str, samples: int = 2000) -> np.ndarray:
        groups = [part["gross_return"].to_numpy(dtype=float) for _, part in dated.groupby(group_column)]
        estimates = np.empty(samples)
        for sample_index in range(samples):
            chosen = rng.integers(0, len(groups), size=len(groups))
            sample = np.concatenate([groups[item] for item in chosen])
            estimates[sample_index] = sample.mean()
        return estimates

    symbol_cluster = clustered_bootstrap("symbol")
    year_cluster = clustered_bootstrap("entry_year")
    month_blocks = clustered_bootstrap("entry_month")
    sem = float(values.std(ddof=1) / math.sqrt(len(values)))
    t_stat = float(values.mean() / sem) if sem > 0 else 0.0
    wilcoxon = stats.wilcoxon(array, alternative="greater", zero_method="wilcox")
    mae = pd.to_numeric(
        opportunities["maximum_adverse_excursion"], errors="coerce"
    ).dropna()
    mfe = pd.to_numeric(
        opportunities["maximum_favourable_excursion"], errors="coerce"
    ).dropna()
    summary = pd.DataFrame(
        [
            {
                "opportunities": len(values),
                "mean_return": float(values.mean()),
                "median_return": float(values.median()),
                "geometric_mean_return": float(np.exp(np.log1p(array).mean()) - 1.0),
                "mean_log_return": float(np.log1p(array).mean()),
                "win_rate": float((values > 0).mean()),
                "profit_factor": _profit_factor(values),
                "target_50_pct": float(opportunities["reached_50pct"].astype(bool).mean()),
                "time_exit_pct": float(opportunities["time_exit"].astype(bool).mean()),
                "duration_mean_sessions": float(pd.to_numeric(opportunities["holding_sessions"]).mean()),
                "duration_median_sessions": float(pd.to_numeric(opportunities["holding_sessions"]).median()),
                **{f"return_p{percentile:02d}": float(np.percentile(array, percentile)) for percentile in (5, 10, 25, 50, 75, 90, 95)},
                "mae_median": float(pd.to_numeric(opportunities["maximum_adverse_excursion"], errors="coerce").median()),
                "mfe_median": float(pd.to_numeric(opportunities["maximum_favourable_excursion"], errors="coerce").median()),
                **{
                    f"mae_p{percentile:02d}": (
                        float(np.percentile(mae, percentile)) if len(mae) else np.nan
                    )
                    for percentile in (5, 10, 25, 50, 75, 90, 95)
                },
                **{
                    f"mfe_p{percentile:02d}": (
                        float(np.percentile(mfe, percentile)) if len(mfe) else np.nan
                    )
                    for percentile in (5, 10, 25, 50, 75, 90, 95)
                },
                "mean_bootstrap_low95": float(np.quantile(ordinary_means, 0.025)),
                "mean_bootstrap_high95": float(np.quantile(ordinary_means, 0.975)),
                "median_bootstrap_low95": float(np.quantile(ordinary_medians, 0.025)),
                "median_bootstrap_high95": float(np.quantile(ordinary_medians, 0.975)),
                "t_statistic": t_stat,
                "t_pvalue_one_sided": float(stats.t.sf(t_stat, len(values) - 1)),
                "wilcoxon_statistic": float(wilcoxon.statistic),
                "wilcoxon_pvalue_one_sided": float(wilcoxon.pvalue),
                "temporal_block_mean_low95": float(np.quantile(month_blocks, 0.025)),
                "temporal_block_mean_high95": float(np.quantile(month_blocks, 0.975)),
                "symbol_cluster_mean_low95": float(np.quantile(symbol_cluster, 0.025)),
                "symbol_cluster_mean_high95": float(np.quantile(symbol_cluster, 0.975)),
                "year_cluster_mean_low95": float(np.quantile(year_cluster, 0.025)),
                "year_cluster_mean_high95": float(np.quantile(year_cluster, 0.975)),
            }
        ]
    )
    # Deliberately no CAGR: independent opportunities are not a capital curve.
    records = pd.DataFrame(
        {
            "sample": np.arange(bootstrap_samples),
            "mean_return": ordinary_means,
            "median_return": ordinary_medians,
        }
    )
    return summary, records


def yearly_opportunity_results(opportunities: pd.DataFrame) -> pd.DataFrame:
    frame = opportunities.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise")
    frame["year"] = frame["entry_date"].dt.year
    rows: list[dict[str, object]] = []
    for year, group in frame.groupby("year", sort=True):
        returns = pd.to_numeric(group["gross_return"], errors="raise")
        rng = np.random.default_rng(20260717 + int(year))
        means = np.asarray(
            [rng.choice(returns, size=len(returns), replace=True).mean() for _ in range(2000)]
        )
        positive = float(np.quantile(means, 0.025)) > 0
        funded = group["originally_financed"].astype(bool)
        rows.append(
            {
                "year": int(year),
                "opportunities": int(len(group)),
                "unique_symbols": int(group["symbol"].nunique()),
                "theoretical_trades": int(len(group)),
                "originally_financed_trades": int(funded.sum()),
                "closed_trades": int(group["originally_closed"].astype(bool).sum()),
                "funded_pct": float(funded.mean()),
                "mean_return": float(returns.mean()),
                "median_return": float(returns.median()),
                "win_rate": float((returns > 0).mean()),
                "profit_factor": _profit_factor(returns),
                "target_50_count": int(group["reached_50pct"].astype(bool).sum()),
                "time_exit_count": int(group["time_exit"].astype(bool).sum()),
                "median_mae": float(pd.to_numeric(group["maximum_adverse_excursion"], errors="coerce").median()),
                "median_mfe": float(pd.to_numeric(group["maximum_favourable_excursion"], errors="coerce").median()),
                "median_duration_sessions": float(pd.to_numeric(group["holding_sessions"], errors="coerce").median()),
                "bootstrap_mean_low95": float(np.quantile(means, 0.025)),
                "bootstrap_mean_high95": float(np.quantile(means, 0.975)),
                "statistically_positive": positive,
            }
        )
    return pd.DataFrame(rows)


def causal_fx_merge(
    rows: pd.DataFrame,
    fx: pd.DataFrame,
    *,
    date_column: str,
) -> pd.DataFrame:
    """Attach last known USD-per-local FX without looking into the future."""

    source = rows.copy()
    source[date_column] = (
        pd.to_datetime(source[date_column], errors="raise")
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    rates = fx.copy()
    rates["date"] = (
        pd.to_datetime(rates["date"], errors="raise")
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    if (rates["date"] > CUTOFF).any():
        raise ValueError("FX source contains a date after the frozen cutoff")
    parts: list[pd.DataFrame] = []
    for currency, group in source.groupby("currency", dropna=False, sort=False):
        key = str(currency)
        if key == "USD":
            part = group.copy()
            part["fx_date"] = part[date_column]
            part["fx_usd_per_local"] = 1.0
            parts.append(part)
            continue
        available = rates.loc[rates["currency"].eq(key), ["date", "usd_per_local"]].dropna().sort_values("date")
        if available.empty:
            part = group.copy()
            part["fx_date"] = pd.NaT
            part["fx_usd_per_local"] = np.nan
            parts.append(part)
            continue
        left = group.sort_values(date_column)
        part = pd.merge_asof(
            left,
            available.rename(columns={"date": "fx_date"}),
            left_on=date_column,
            right_on="fx_date",
            direction="backward",
            allow_exact_matches=True,
        ).rename(columns={"usd_per_local": "fx_usd_per_local"})
        if (part["fx_date"] > part[date_column]).fillna(False).any():
            raise ValueError("future FX rate used")
        parts.append(part)
    return pd.concat(parts, ignore_index=True).sort_index()


def fx_adjust_opportunities(
    opportunities: pd.DataFrame,
    fx: pd.DataFrame,
    *,
    price_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    base = opportunities.copy().reset_index(drop=True)
    base["_row_id"] = np.arange(len(base))
    entry = causal_fx_merge(base, fx, date_column="entry_date").rename(
        columns={"fx_date": "fx_entry_date", "fx_usd_per_local": "fx_entry"}
    )
    # Keep both provenance dates.  The exit merge only adds a second causal
    # rate and must not erase which rate was available at entry.
    exit_input = entry.copy()
    adjusted = causal_fx_merge(exit_input, fx, date_column="exit_date").rename(
        columns={"fx_date": "fx_exit_date", "fx_usd_per_local": "fx_exit"}
    )
    scale = pd.to_numeric(adjusted["price_scale_to_currency_unit"], errors="coerce")
    entry_usd = pd.to_numeric(adjusted["entry_price"], errors="coerce") * scale * adjusted["fx_entry"]
    exit_usd = pd.to_numeric(adjusted["exit_price"], errors="coerce") * scale * adjusted["fx_exit"]
    local_dividends = pd.to_numeric(adjusted["dividends_local"], errors="coerce").fillna(0)
    if price_panel is None and local_dividends.abs().gt(1e-12).any():
        raise ValueError("price_panel is required to convert dividends with causal FX")
    dividend_usd = pd.Series(0.0, index=adjusted.index, dtype=float)
    dividend_dates = pd.Series("", index=adjusted.index, dtype=str)
    dividend_fx_missing = pd.Series(False, index=adjusted.index, dtype=bool)
    if price_panel is not None:
        required = {"date", "symbol", "dividends"}
        if required - set(price_panel.columns):
            raise ValueError("price panel lacks date, symbol, or dividends for FX conversion")
        payments = price_panel[["date", "symbol", "dividends"]].copy()
        payments["date"] = pd.to_datetime(payments["date"], errors="raise").dt.normalize()
        payments["dividends"] = pd.to_numeric(payments["dividends"], errors="coerce").fillna(0)
        payments = payments.loc[payments["dividends"].abs().gt(1e-12)]
        if not payments.empty:
            symbol_meta = adjusted[
                ["symbol", "currency", "price_scale_to_currency_unit"]
            ].drop_duplicates()
            if symbol_meta["symbol"].duplicated().any():
                raise ValueError("inconsistent currency metadata for a dividend symbol")
            payments = payments.merge(symbol_meta, on="symbol", how="left", validate="many_to_one")
            payments = causal_fx_merge(payments, fx, date_column="date")
            payments["dividend_usd"] = (
                payments["dividends"]
                * pd.to_numeric(payments["price_scale_to_currency_unit"], errors="coerce")
                * pd.to_numeric(payments["fx_usd_per_local"], errors="coerce")
            )
            links = adjusted[["_row_id", "symbol", "entry_date", "exit_date"]].merge(
                payments[["symbol", "date", "dividend_usd", "fx_usd_per_local"]],
                on="symbol",
                how="left",
            )
            in_trade = links["date"].notna() & links["date"].between(
                links["entry_date"], links["exit_date"]
            )
            links = links.loc[in_trade]
            if not links.empty:
                grouped = links.groupby("_row_id", sort=False)
                values = grouped["dividend_usd"].sum(min_count=1)
                dates = grouped["date"].agg(
                    lambda items: ",".join(
                        timestamp.date().isoformat()
                        for timestamp in sorted(pd.to_datetime(items).drop_duplicates())
                    )
                )
                missing = grouped["fx_usd_per_local"].apply(lambda values: values.isna().any())
                dividend_usd = adjusted["_row_id"].map(values).fillna(0.0)
                dividend_dates = adjusted["_row_id"].map(dates).fillna("")
                dividend_fx_missing = adjusted["_row_id"].map(missing).fillna(False).astype(bool)
    adjusted["entry_value_usd_per_share"] = entry_usd
    adjusted["exit_value_usd_per_share"] = exit_usd
    adjusted["dividend_value_usd_per_share"] = dividend_usd
    adjusted["fx_dividend_dates_used"] = dividend_dates
    adjusted["return_usd"] = (exit_usd + dividend_usd).div(entry_usd).sub(1.0)
    adjusted["local_total_return_with_dividends"] = (
        pd.to_numeric(adjusted["exit_price"], errors="coerce")
        .add(pd.to_numeric(adjusted["dividends_local"], errors="coerce").fillna(0))
        .div(pd.to_numeric(adjusted["entry_price"], errors="coerce"))
        .sub(1.0)
    )
    adjusted["fx_return_contribution"] = adjusted["return_usd"] - adjusted["local_total_return_with_dividends"]
    adjusted["currency_unknown"] = (
        adjusted["currency_unknown"].astype(bool)
        | adjusted["fx_entry"].isna()
        | adjusted["fx_exit"].isna()
        | dividend_fx_missing
    )
    return adjusted.sort_values("_row_id").drop(columns=["_row_id"]).reset_index(drop=True)


def resampled_returns(curve: pd.DataFrame, frequency: str) -> pd.Series:
    frame = curve.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    equity = frame.sort_values("date").set_index("date")["equity"]
    rules = {"daily": None, "weekly": "W-FRI", "monthly": "ME", "quarterly": "QE"}
    if frequency not in rules:
        raise ValueError(f"unsupported frequency: {frequency}")
    if rules[frequency] is not None:
        # Keep the final *observed* date in each bucket.  Pandas otherwise
        # labels incomplete weeks/months/quarters with a future period end,
        # which would make a frozen-cutoff audit appear to use future data.
        sampled = equity.rename("equity").to_frame()
        sampled["observed_date"] = sampled.index
        sampled = sampled.resample(rules[frequency]).agg(
            {"equity": "last", "observed_date": "last"}
        ).dropna(subset=["equity", "observed_date"])
        equity = pd.Series(
            sampled["equity"].to_numpy(),
            index=pd.DatetimeIndex(sampled["observed_date"]),
            name="equity",
        )
    return pd.to_numeric(equity, errors="raise").pct_change(fill_method=None).dropna()


def frequency_metric_rows(
    curve: pd.DataFrame,
    *,
    period: str,
    variant: str,
) -> pd.DataFrame:
    frame = curve.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    rows: list[dict[str, object]] = []
    years = max((frame["date"].max() - frame["date"].min()).days / 365.2425, 1e-9)
    real_observations = float(len(frame) / years)
    for calendar_mode, bounded in (
        ("artifact_calendar", frame),
        ("monday_to_friday", frame.loc[frame["date"].dt.dayofweek.lt(5)].copy()),
    ):
        for frequency, annualization in (
            ("daily", 252.0 if calendar_mode == "monday_to_friday" else real_observations),
            ("weekly", 52.0),
            ("monthly", 12.0),
            ("quarterly", 4.0),
        ):
            returns = resampled_returns(bounded, frequency)
            deviation = float(returns.std(ddof=1))
            rows.append(
                {
                    "period": period,
                    "variant": variant,
                    "calendar_mode": calendar_mode,
                    "frequency": frequency,
                    "observations": int(len(returns)),
                    "observations_per_year_used": annualization,
                    "total_return": float(np.prod(1 + returns) - 1.0),
                    "annualized_return": float((1 + returns.mean()) ** annualization - 1.0),
                    "annualized_volatility": deviation * math.sqrt(annualization),
                    "sharpe": float(returns.mean() / deviation * math.sqrt(annualization)) if deviation > 0 else 0.0,
                    "daily_asynchrony_warning": frequency == "daily",
                }
            )
    return pd.DataFrame(rows)


def benchmark_comparison(
    strategy_curve: pd.DataFrame,
    benchmark_prices: pd.DataFrame,
    *,
    benchmark: str,
    period: str,
    variant: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    strategy = strategy_curve[["date", "equity"]].copy()
    strategy["date"] = pd.to_datetime(strategy["date"], errors="raise").dt.normalize()
    benchmark_frame = benchmark_prices.loc[
        benchmark_prices["symbol"].eq(benchmark), ["date", "adj_close"]
    ].copy()
    benchmark_frame["date"] = pd.to_datetime(benchmark_frame["date"], errors="raise").dt.normalize()
    benchmark_frame = benchmark_frame.sort_values("date").drop_duplicates("date", keep="last")
    if benchmark_frame.empty:
        unavailable = pd.DataFrame(
            [{"period": period, "variant": variant, "benchmark": benchmark, "status": "unavailable"}]
        )
        return unavailable, unavailable.copy()
    dates = pd.DatetimeIndex(strategy["date"])
    values = (
        benchmark_frame.set_index("date")["adj_close"]
        .reindex(pd.DatetimeIndex(benchmark_frame["date"]).union(dates))
        .sort_index()
        .ffill()
        .reindex(dates)
    )
    valid = values.notna() & values.gt(0)
    strategy = strategy.loc[valid.to_numpy()].copy()
    values = values.loc[valid]
    if len(strategy) < 30:
        unavailable = pd.DataFrame(
            [{"period": period, "variant": variant, "benchmark": benchmark, "status": "insufficient_history"}]
        )
        return unavailable, unavailable.copy()
    benchmark_curve = pd.DataFrame(
        {"date": strategy["date"].to_numpy(), "equity": 100_000 * values.to_numpy() / float(values.iloc[0])}
    )
    rows: list[dict[str, object]] = []
    regressions: list[dict[str, object]] = []
    annualization = {"daily": 252.0, "weekly": 52.0, "monthly": 12.0, "quarterly": 4.0}
    for frequency, factor in annualization.items():
        s = resampled_returns(strategy, frequency)
        b = resampled_returns(benchmark_curve, frequency)
        paired = pd.concat([s.rename("strategy"), b.rename("benchmark")], axis=1).dropna()
        if len(paired) < 4:
            continue
        excess = paired["strategy"] - paired["benchmark"]
        variance = float(paired["benchmark"].var(ddof=1))
        beta = float(paired["strategy"].cov(paired["benchmark"]) / variance) if variance > 0 else 0.0
        alpha = float((paired["strategy"].mean() - beta * paired["benchmark"].mean()) * factor)
        tracking = float(excess.std(ddof=1) * math.sqrt(factor))
        information = float(excess.mean() / excess.std(ddof=1) * math.sqrt(factor)) if excess.std(ddof=1) > 0 else 0.0
        s_std = float(paired["strategy"].std(ddof=1))
        b_std = float(paired["benchmark"].std(ddof=1))
        s_sharpe = float(paired["strategy"].mean() / s_std * math.sqrt(factor)) if s_std > 0 else 0.0
        b_sharpe = float(paired["benchmark"].mean() / b_std * math.sqrt(factor)) if b_std > 0 else 0.0
        s_down = paired.loc[paired["strategy"] < 0, "strategy"]
        b_down = paired.loc[paired["benchmark"] < 0, "benchmark"]
        s_sortino = float(paired["strategy"].mean() * factor / (s_down.pow(2).mean() ** 0.5 * math.sqrt(factor))) if len(s_down) else 0.0
        b_sortino = float(paired["benchmark"].mean() * factor / (b_down.pow(2).mean() ** 0.5 * math.sqrt(factor))) if len(b_down) else 0.0
        s_equity = (1 + paired["strategy"]).cumprod()
        b_equity = (1 + paired["benchmark"]).cumprod()
        strategy_total = float(np.prod(1.0 + paired["strategy"]))
        benchmark_total = float(np.prod(1.0 + paired["benchmark"]))
        elapsed_years = max(
            (pd.Timestamp(paired.index.max()) - pd.Timestamp(paired.index.min())).days
            / 365.2425,
            1.0 / 365.2425,
        )
        strategy_cagr = strategy_total ** (1.0 / elapsed_years) - 1.0
        benchmark_cagr = benchmark_total ** (1.0 / elapsed_years) - 1.0
        monthly_paired = (1.0 + paired).resample("ME").prod().sub(1.0)
        yearly_paired = (1.0 + paired).resample("YE").prod().sub(1.0)
        rows.append(
            {
                "period": period,
                "variant": variant,
                "benchmark": benchmark,
                "frequency": frequency,
                "status": "evaluated",
                "comparison_start": paired.index.min(),
                "comparison_end": paired.index.max(),
                "observations": len(paired),
                "strategy_cagr": strategy_cagr,
                "benchmark_cagr": benchmark_cagr,
                "cagr_difference": strategy_cagr - benchmark_cagr,
                "strategy_sharpe": s_sharpe,
                "benchmark_sharpe": b_sharpe,
                "sharpe_difference": s_sharpe - b_sharpe,
                "strategy_sortino": s_sortino,
                "benchmark_sortino": b_sortino,
                "sortino_difference": s_sortino - b_sortino,
                "strategy_max_drawdown": _drawdown(s_equity),
                "benchmark_max_drawdown": _drawdown(b_equity),
                "drawdown_difference": _drawdown(s_equity) - _drawdown(b_equity),
                "correlation": float(paired["strategy"].corr(paired["benchmark"])),
                "beta": beta,
                "alpha_annualized": alpha,
                "tracking_error": tracking,
                "information_ratio": information,
                "periods_outperformed_pct": float((excess > 0).mean()),
                "months_outperformed_pct": float(
                    (monthly_paired["strategy"] > monthly_paired["benchmark"]).mean()
                ),
                "years_outperformed_pct": float(
                    (yearly_paired["strategy"] > yearly_paired["benchmark"]).mean()
                ),
            }
        )
        # HAC/Newey-West regression is added lazily to keep statsmodels optional
        # for unit tests that exercise pure data transformations.
        try:
            import statsmodels.api as sm

            lags = {"daily": 5, "weekly": 4, "monthly": 3, "quarterly": 1}[frequency]
            model = sm.OLS(paired["strategy"], sm.add_constant(paired["benchmark"])).fit(
                cov_type="HAC", cov_kwds={"maxlags": lags}
            )
            regressions.append(
                {
                    "period": period,
                    "variant": variant,
                    "benchmark": benchmark,
                    "frequency": frequency,
                    "alpha_annualized": float(model.params["const"] * factor),
                    "alpha_pvalue_newey_west": float(model.pvalues["const"]),
                    "beta": float(model.params["benchmark"]),
                    "beta_pvalue_newey_west": float(model.pvalues["benchmark"]),
                    "newey_west_lags": lags,
                }
            )
        except ImportError:
            regressions.append(
                {
                    "period": period,
                    "variant": variant,
                    "benchmark": benchmark,
                    "frequency": frequency,
                    "alpha_annualized": alpha,
                    "alpha_pvalue_newey_west": np.nan,
                    "beta": beta,
                    "beta_pvalue_newey_west": np.nan,
                    "newey_west_lags": np.nan,
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(regressions)


def fx_adjust_price_panel(
    panel: pd.DataFrame,
    metadata: pd.DataFrame,
    fx: pd.DataFrame,
) -> pd.DataFrame:
    """Convert an OHLCV panel to USD using same-day or prior causal FX."""

    source = panel.merge(
        metadata[["symbol", "currency", "price_scale_to_currency_unit"]],
        on="symbol",
        how="left",
        validate="many_to_one",
    )
    adjusted = causal_fx_merge(source, fx, date_column="date")
    multiplier = (
        pd.to_numeric(adjusted["price_scale_to_currency_unit"], errors="coerce")
        * pd.to_numeric(adjusted["fx_usd_per_local"], errors="coerce")
    )
    for column in ("open", "high", "low", "close", "adj_close", "dividends"):
        adjusted[column] = pd.to_numeric(adjusted[column], errors="coerce") * multiplier
    return adjusted.dropna(subset=["open", "high", "low", "close", "fx_usd_per_local"])


def attach_entry_adv_notional(
    opportunities: pd.DataFrame,
    price_panel: pd.DataFrame,
    *,
    output_column: str = "entry_adv20_notional",
) -> pd.DataFrame:
    """Attach causal trailing 20-session average dollar volume at entry."""

    required = {"date", "symbol", "close", "volume"}
    if required - set(price_panel.columns):
        raise ValueError("price panel lacks fields required for ADV")
    panel = price_panel[["date", "symbol", "close", "volume"]].copy()
    panel["date"] = pd.to_datetime(panel["date"], errors="raise").dt.normalize()
    panel = panel.sort_values(["symbol", "date"])
    panel["dollar_volume"] = (
        pd.to_numeric(panel["close"], errors="coerce")
        * pd.to_numeric(panel["volume"], errors="coerce")
    )
    panel[output_column] = panel.groupby("symbol", sort=False)["dollar_volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=1).mean()
    )
    lookup = panel[["date", "symbol", output_column]].drop_duplicates(
        ["date", "symbol"], keep="last"
    )
    result = opportunities.copy()
    result["entry_date"] = pd.to_datetime(result["entry_date"], errors="raise").dt.normalize()
    result = result.merge(
        lookup,
        left_on=["entry_date", "symbol"],
        right_on=["date", "symbol"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["date"])
    return result


def prepare_fx_portfolio_opportunities(
    adjusted_opportunities: pd.DataFrame,
    usd_price_panel: pd.DataFrame,
) -> pd.DataFrame:
    """Prepare USD trades without embedding dividends into exit prices."""

    known = adjusted_opportunities.loc[
        adjusted_opportunities["return_usd"].notna()
        & ~adjusted_opportunities["currency_unknown"].astype(bool)
    ].copy()
    known["entry_price"] = pd.to_numeric(
        known["entry_value_usd_per_share"], errors="raise"
    )
    known["exit_price"] = pd.to_numeric(
        known["exit_value_usd_per_share"], errors="raise"
    )
    known = attach_entry_adv_notional(known, usd_price_panel)
    known["capacity_currency"] = "USD"
    return known


def _price_lookup(
    panel: pd.DataFrame,
    symbols: set[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.DatetimeIndex, dict[tuple[pd.Timestamp, str], tuple[float, float, float, float, float]]]:
    source = panel.loc[
        panel["symbol"].astype(str).isin(symbols)
        & pd.to_datetime(panel["date"], errors="raise").between(start, end),
        ["date", "symbol", "open", "close", "volume", "dividends", "stock_splits"],
    ].copy()
    source["date"] = pd.to_datetime(source["date"], errors="raise").dt.normalize()
    source = source.sort_values(["date", "symbol"]).drop_duplicates(["date", "symbol"], keep="last")
    calendar = pd.DatetimeIndex(source["date"].drop_duplicates().sort_values())
    lookup = {
        (pd.Timestamp(date), str(symbol)): (
            float(open_price),
            float(close),
            float(volume or 0.0),
            float(dividends or 0.0),
            float(stock_splits or 0.0),
        )
        for date, symbol, open_price, close, volume, dividends, stock_splits in source.itertuples(index=False, name=None)
    }
    return calendar, lookup


def simulate_opportunity_portfolio(
    opportunities: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    max_positions: int | None,
    max_initial_weight: float | None,
    order_mode: str,
    cost_bps_per_side: float = 0.0,
    initial_capital: float = 100_000.0,
    max_volume_participation: float = 0.10,
    seed: int = 20260717,
    _price_context: tuple[
        pd.DatetimeIndex,
        dict[tuple[pd.Timestamp, str], tuple[float, float, float, float, float]],
    ]
    | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate predeclared portfolio construction over immutable opportunities."""

    if order_mode not in {"original", "score", "permuted"}:
        raise ValueError(f"unsupported order mode: {order_mode}")
    if max_positions is not None and max_positions < 1:
        raise ValueError("max_positions must be positive")
    if max_initial_weight is not None and not 0 < max_initial_weight <= 1:
        raise ValueError("max_initial_weight must be in (0, 1]")
    if cost_bps_per_side < 0:
        raise ValueError("cost cannot be negative")
    ledger = opportunities.copy().reset_index(drop=True)
    required = {"symbol", "entry_date", "entry_price", "exit_date", "exit_price", "score", "weight"}
    missing = required - set(ledger)
    if missing:
        raise ValueError(f"opportunity ledger missing {sorted(missing)}")
    for column in ("entry_date", "exit_date"):
        ledger[column] = pd.to_datetime(ledger[column], errors="raise").dt.normalize()
    if (ledger["exit_date"] < ledger["entry_date"]).any():
        raise ValueError("exit before entry")
    ledger["simulation_trade_id"] = np.arange(len(ledger), dtype=int)
    ledger["simulation_status"] = "pending"
    ledger["simulation_rejection_reason"] = ""
    ledger["simulation_entry_notional"] = 0.0
    ledger["simulation_exit_notional"] = 0.0
    ledger["simulation_entry_cost"] = 0.0
    ledger["simulation_exit_cost"] = 0.0
    ledger["simulation_shares"] = 0.0
    ledger["simulation_capacity_reduced"] = False
    ledger["simulation_adv_notional"] = np.nan
    ledger["simulation_capacity_notional"] = np.nan
    ledger["simulation_desired_notional"] = 0.0
    ledger["simulation_capacity_reduction_notional"] = 0.0
    ledger["simulation_volume_participation_pct"] = np.nan
    ledger["simulation_capacity_basis"] = ""
    ledger["simulation_max_weight"] = max_initial_weight if max_initial_weight is not None else np.nan
    ledger["simulation_order_mode"] = order_mode
    rng = np.random.default_rng(seed)
    ledger["_random_order"] = rng.random(len(ledger))
    symbols = set(ledger["symbol"].astype(str))
    if _price_context is None:
        calendar, lookup = _price_lookup(
            panel,
            symbols,
            ledger["entry_date"].min(),
            ledger["exit_date"].max(),
        )
    else:
        calendar, lookup = _price_context
    if len(calendar) == 0:
        raise ValueError("no price calendar for portfolio")
    entry_groups = {date: group.index.to_list() for date, group in ledger.groupby("entry_date", sort=False)}
    exit_groups = {date: group.index.to_list() for date, group in ledger.groupby("exit_date", sort=False)}
    cash = float(initial_capital)
    positions: dict[str, dict[str, float | int]] = {}
    prior_equity = float(initial_capital)
    cost_rate = float(cost_bps_per_side) / 10_000.0
    curve_rows: list[dict[str, object]] = []

    for date in calendar:
        timestamp = pd.Timestamp(date)
        day_costs = 0.0
        day_traded = 0.0
        for symbol, position in list(positions.items()):
            quote = lookup.get((timestamp, symbol))
            if quote is None:
                continue
            split = quote[4]
            if split > 0 and not math.isclose(split, 1.0):
                position["shares"] = float(position["shares"]) * split

        for index in exit_groups.get(timestamp, []):
            if ledger.at[index, "simulation_status"] != "open":
                continue
            symbol = str(ledger.at[index, "symbol"])
            position = positions.pop(symbol, None)
            if position is None:
                continue
            exit_notional = float(position["shares"]) * float(ledger.at[index, "exit_price"])
            exit_cost = exit_notional * cost_rate
            cash += exit_notional - exit_cost
            day_costs += exit_cost
            day_traded += exit_notional
            ledger.at[index, "simulation_exit_notional"] = exit_notional
            ledger.at[index, "simulation_exit_cost"] = exit_cost
            ledger.at[index, "simulation_status"] = "closed"

        open_value = cash
        for symbol, position in positions.items():
            quote = lookup.get((timestamp, symbol))
            mark = quote[0] if quote is not None else float(position["last_close"])
            open_value += float(position["shares"]) * mark

        entrants = ledger.loc[entry_groups.get(timestamp, [])].copy()
        if order_mode == "original":
            # The immutable ledger already records the engine's deterministic
            # arrival order.  Preserve it exactly; do not substitute a new
            # weight-based priority rule.
            columns = [column for column in ("trade_id", "symbol") if column in entrants]
            entrants = entrants.sort_values(columns, kind="stable")
        elif order_mode == "score":
            entrants = entrants.sort_values(["score", "symbol"], ascending=[False, True], kind="stable")
        else:
            entrants = entrants.sort_values(["_random_order", "symbol"], ascending=[True, True], kind="stable")
        for index, trade in entrants.iterrows():
            symbol = str(trade["symbol"])
            if symbol in positions:
                ledger.at[index, "simulation_status"] = "rejected"
                ledger.at[index, "simulation_rejection_reason"] = "duplicate_symbol"
                continue
            if max_positions is not None and len(positions) >= max_positions:
                ledger.at[index, "simulation_status"] = "rejected"
                ledger.at[index, "simulation_rejection_reason"] = "position_limit"
                continue
            quote = lookup.get((timestamp, symbol))
            if quote is None:
                ledger.at[index, "simulation_status"] = "rejected"
                ledger.at[index, "simulation_rejection_reason"] = "missing_price"
                continue
            weight = float(trade["weight"]) if max_initial_weight is None else float(max_initial_weight)
            if max_initial_weight is not None and weight > max_initial_weight + 1e-12:
                raise ValueError("opportunity weight exceeds predeclared maximum")
            desired = max(0.0, weight) * open_value
            adv_column = next(
                (
                    column
                    for column in ("entry_adv20_notional", "entry_adv20_usd", "entry_adv20_local")
                    if column in trade.index and pd.notna(trade[column]) and float(trade[column]) > 0
                ),
                None,
            )
            if adv_column is None:
                adv_notional = quote[2] * float(trade["entry_price"])
                capacity_basis = "entry_day_dollar_volume_fallback"
            else:
                adv_notional = float(trade[adv_column])
                capacity_basis = adv_column
            volume_capacity = adv_notional * max_volume_participation
            affordable = cash / (1.0 + cost_rate)
            notional = min(desired, volume_capacity, affordable)
            ledger.at[index, "simulation_adv_notional"] = adv_notional
            ledger.at[index, "simulation_capacity_notional"] = volume_capacity
            ledger.at[index, "simulation_desired_notional"] = desired
            ledger.at[index, "simulation_capacity_reduction_notional"] = max(
                0.0, desired - notional
            )
            ledger.at[index, "simulation_volume_participation_pct"] = (
                notional / adv_notional if adv_notional > 0 else np.nan
            )
            ledger.at[index, "simulation_capacity_basis"] = capacity_basis
            if notional <= 0:
                ledger.at[index, "simulation_status"] = "rejected"
                ledger.at[index, "simulation_rejection_reason"] = "insufficient_capital"
                continue
            shares = notional / float(trade["entry_price"])
            entry_cost = notional * cost_rate
            cash -= notional + entry_cost
            positions[symbol] = {
                "shares": shares,
                "trade_id": int(index),
                "last_close": float(trade["entry_price"]),
            }
            ledger.at[index, "simulation_shares"] = shares
            ledger.at[index, "simulation_entry_notional"] = notional
            ledger.at[index, "simulation_entry_cost"] = entry_cost
            ledger.at[index, "simulation_capacity_reduced"] = notional + 1e-9 < desired
            ledger.at[index, "simulation_status"] = "open"
            day_costs += entry_cost
            day_traded += notional

        for index in exit_groups.get(timestamp, []):
            if ledger.at[index, "simulation_status"] != "open" or ledger.at[index, "entry_date"] != timestamp:
                continue
            symbol = str(ledger.at[index, "symbol"])
            position = positions.pop(symbol)
            exit_notional = float(position["shares"]) * float(ledger.at[index, "exit_price"])
            exit_cost = exit_notional * cost_rate
            cash += exit_notional - exit_cost
            ledger.at[index, "simulation_exit_notional"] = exit_notional
            ledger.at[index, "simulation_exit_cost"] = exit_cost
            ledger.at[index, "simulation_status"] = "closed"
            day_costs += exit_cost
            day_traded += exit_notional

        market_value = 0.0
        for symbol, position in positions.items():
            quote = lookup.get((timestamp, symbol))
            if quote is not None:
                cash += float(position["shares"]) * quote[3]
                position["last_close"] = quote[1]
            market_value += float(position["shares"]) * float(position["last_close"])
        equity = cash + market_value
        if not np.isfinite(equity) or equity <= 0:
            raise ValueError("portfolio equity became non-positive or non-finite")
        curve_rows.append(
            {
                "date": timestamp,
                "cash": cash,
                "market_value": market_value,
                "equity": equity,
                "gross_exposure": market_value / equity,
                "turnover": day_traded / prior_equity if prior_equity > 0 else 0.0,
                "costs": day_costs,
                "positions": len(positions),
            }
        )
        prior_equity = equity

    ledger["simulation_net_return"] = np.where(
        ledger["simulation_status"].eq("closed") & ledger["simulation_entry_notional"].gt(0),
        (ledger["simulation_exit_notional"] - ledger["simulation_exit_cost"])
        / (ledger["simulation_entry_notional"] + ledger["simulation_entry_cost"])
        - 1.0,
        np.nan,
    )
    ledger["status"] = ledger["simulation_status"]
    ledger["net_return"] = ledger["simulation_net_return"]
    ledger = ledger.drop(columns=["_random_order"])
    curve = pd.DataFrame(curve_rows)
    if max_positions is not None and int(curve["positions"].max()) > max_positions:
        raise ValueError("position limit violated")
    if (curve["cash"] < -1e-7).any() or (curve["gross_exposure"] > 1.0000001).any():
        raise ValueError("capital or leverage constraint violated")
    return curve, ledger


def portfolio_yearly_rows(
    curve: pd.DataFrame,
    ledger: pd.DataFrame,
    *,
    period: str,
    variant: str,
    cost_bps: float,
) -> pd.DataFrame:
    frame = curve.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    trades = ledger.loc[ledger["status"].astype(str).eq("closed")].copy()
    trades["exit_date"] = pd.to_datetime(trades["exit_date"], errors="raise").dt.normalize()
    rows: list[dict[str, object]] = []
    for year, part in frame.groupby(frame["date"].dt.year, sort=True):
        year_trades = trades.loc[trades["exit_date"].dt.year.eq(year)]
        returns = pd.to_numeric(year_trades["net_return"], errors="coerce").dropna()
        rows.append(
            {
                "period": period,
                "variant": variant,
                "cost_bps_per_side": cost_bps,
                "year": int(year),
                "return": float(part["equity"].iloc[-1] / part["equity"].iloc[0] - 1.0),
                "max_drawdown": _drawdown(part["equity"]),
                "average_exposure": float(part["gross_exposure"].mean()),
                "average_positions": float(part["positions"].mean()),
                "max_positions": int(part["positions"].max()),
                "trades": int(len(year_trades)),
                "win_rate": float((returns > 0).mean()) if len(returns) else 0.0,
                "profit_factor": _profit_factor(returns),
            }
        )
    return pd.DataFrame(rows)


_SEQUENCE_WORKER_OPPORTUNITIES: pd.DataFrame | None = None
_SEQUENCE_WORKER_PANEL: pd.DataFrame | None = None
_SEQUENCE_WORKER_PRICE_CONTEXT: tuple[
    pd.DatetimeIndex,
    dict[tuple[pd.Timestamp, str], tuple[float, float, float, float, float]],
] | None = None


def _build_sequence_price_context(
    opportunities: pd.DataFrame,
    panel: pd.DataFrame,
) -> tuple[
    pd.DatetimeIndex,
    dict[tuple[pd.Timestamp, str], tuple[float, float, float, float, float]],
]:
    entry_dates = pd.to_datetime(opportunities["entry_date"], errors="raise").dt.normalize()
    exit_dates = pd.to_datetime(opportunities["exit_date"], errors="raise").dt.normalize()
    return _price_lookup(
        panel,
        set(opportunities["symbol"].astype(str)),
        entry_dates.min(),
        exit_dates.max(),
    )


def _sequence_rows_for_range(
    opportunities: pd.DataFrame,
    panel: pd.DataFrame,
    price_context: tuple[
        pd.DatetimeIndex,
        dict[tuple[pd.Timestamp, str], tuple[float, float, float, float, float]],
    ],
    *,
    start: int,
    stop: int,
    seed: int,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for simulation in range(start, stop):
        curve, ledger = simulate_opportunity_portfolio(
            opportunities,
            panel,
            max_positions=None,
            max_initial_weight=None,
            order_mode="permuted",
            seed=seed + simulation + 1,
            _price_context=price_context,
        )
        metrics = portfolio_metrics(curve, ledger)
        funded = int(ledger["status"].eq("closed").sum())
        rows.append(
            {
                "simulation": simulation,
                **metrics,
                "funded_opportunities": funded,
                "funded_pct": funded / len(ledger),
            }
        )
    return rows


def _initialize_sequence_worker(
    opportunities: pd.DataFrame,
    panel: pd.DataFrame,
) -> None:
    global _SEQUENCE_WORKER_OPPORTUNITIES
    global _SEQUENCE_WORKER_PANEL
    global _SEQUENCE_WORKER_PRICE_CONTEXT
    _SEQUENCE_WORKER_OPPORTUNITIES = opportunities
    _SEQUENCE_WORKER_PANEL = panel
    _SEQUENCE_WORKER_PRICE_CONTEXT = _build_sequence_price_context(opportunities, panel)


def _sequence_worker_range(start: int, stop: int, seed: int) -> list[dict[str, object]]:
    if (
        _SEQUENCE_WORKER_OPPORTUNITIES is None
        or _SEQUENCE_WORKER_PANEL is None
        or _SEQUENCE_WORKER_PRICE_CONTEXT is None
    ):
        raise RuntimeError("sequence worker was not initialized")
    return _sequence_rows_for_range(
        _SEQUENCE_WORKER_OPPORTUNITIES,
        _SEQUENCE_WORKER_PANEL,
        _SEQUENCE_WORKER_PRICE_CONTEXT,
        start=start,
        stop=stop,
        seed=seed,
    )


def sequence_dependence(
    opportunities: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    simulations: int = 1000,
    seed: int = 20260717,
    workers: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if simulations < 1000:
        raise ValueError("at least 1000 sequence permutations are required")
    if workers < 1:
        raise ValueError("workers must be positive")
    workers = min(int(workers), simulations)
    price_context = _build_sequence_price_context(opportunities, panel)
    deterministic: list[dict[str, object]] = []
    curves: dict[str, pd.DataFrame] = {}
    ledgers: dict[str, pd.DataFrame] = {}
    for mode in ("original", "score"):
        curve, ledger = simulate_opportunity_portfolio(
            opportunities,
            panel,
            max_positions=None,
            max_initial_weight=None,
            order_mode=mode,
            seed=seed,
            _price_context=price_context,
        )
        metrics = portfolio_metrics(curve, ledger)
        funded = int(ledger["status"].eq("closed").sum())
        deterministic.append(
            {
                "order": mode,
                **metrics,
                "funded_opportunities": funded,
                "funded_pct": funded / len(ledger),
            }
        )
        curves[mode] = curve
        ledgers[mode] = ledger
    if workers == 1:
        random_rows = _sequence_rows_for_range(
            opportunities,
            panel,
            price_context,
            start=0,
            stop=simulations,
            seed=seed,
        )
    else:
        bounds = np.linspace(0, simulations, workers + 1, dtype=int)
        start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
        context = multiprocessing.get_context(start_method)
        random_rows = []
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_initialize_sequence_worker,
            initargs=(opportunities, panel),
        ) as executor:
            futures = [
                executor.submit(
                    _sequence_worker_range,
                    int(bounds[index]),
                    int(bounds[index + 1]),
                    seed,
                )
                for index in range(workers)
            ]
            for future in futures:
                random_rows.extend(future.result())
    distribution = pd.DataFrame(random_rows).sort_values("simulation").reset_index(drop=True)
    result = pd.DataFrame(deterministic)
    original = result.loc[result["order"].eq("original")].iloc[0]
    for metric in ("cagr", "sharpe", "max_drawdown", "total_return", "trades", "funded_pct"):
        result.loc[result["order"].eq("original"), f"original_percentile_{metric}"] = float(
            (distribution[metric] <= float(original[metric])).mean()
        )
    return result, distribution


def write_artifact_manifest(
    output_root: Path,
    *,
    input_artifacts: Mapping[str, str],
    commit: str,
) -> dict[str, object]:
    files = sorted(path for path in output_root.rglob("*") if path.is_file() and path.name != "final_artifact_manifest.json")
    payload = {
        "artifact_name": "stock-protocol-all-opportunities-and-realistic-portfolio-audit",
        "role": AUDIT_ROLE,
        "commit": commit,
        "cutoff": CUTOFF.date().isoformat(),
        "new_oos_claimed": False,
        "optimization_performed": False,
        "survivorship_limited": True,
        "input_artifacts": dict(input_artifacts),
        "files": {
            path.relative_to(output_root).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        },
    }
    (output_root / "final_artifact_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload

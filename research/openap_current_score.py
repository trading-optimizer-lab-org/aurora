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


def evidence_weight(row: Mapping[str, Any], status: str) -> float:
    """Return a bounded evidence weight without treating missing t-stats as zero."""

    reproduction = abs(float(row.get("tstat") or 0.0))
    original_raw = row.get("T.Stat")
    try:
        original = abs(float(str(original_raw)))
        original_factor = min(original, 8.0) / 8.0
    except (TypeError, ValueError):
        original_factor = 0.70
    reproduction_factor = min(reproduction, 8.0) / 8.0
    source_factor = {"exact": 1.0, "proxy": 0.55}.get(status, 0.0)
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
    """Group near-identical and mirror predictors after direction alignment."""

    names = metadata["signalname"].astype(str).tolist()
    signs = metadata.set_index("signalname")["Sign"].apply(
        lambda value: float(value) if pd.notna(value) else 1.0
    )
    available = [name for name in names if name in portfolio_returns.columns]
    aligned = portfolio_returns[available].apply(pd.to_numeric, errors="coerce")
    aligned = aligned.mul(signs.reindex(available), axis=1)
    corr = aligned.corr(min_periods=int(minimum_overlap))
    count = aligned.notna().astype("int16").T.dot(aligned.notna().astype("int16"))
    edges: list[tuple[str, str]] = []
    for index, left in enumerate(available):
        for right in available[index + 1 :]:
            value = corr.at[left, right]
            overlap = int(count.at[left, right])
            if overlap >= minimum_overlap and pd.notna(value) and abs(float(value)) >= threshold:
                edges.append((left, right))
    components = _connected_components(names, edges)
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


def calculate_price_features(frame: pd.DataFrame) -> dict[str, FeatureValue]:
    """Calculate current price and trading characteristics.

    Signals that need the original CRSP cross-sectional regression, industry
    membership history or unavailable factor returns are labelled as proxies.
    """

    required = {"date", "adj_close", "volume"}
    if required.difference(frame.columns):
        return {}
    daily = frame.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    for column in ("adj_close", "volume", "high", "low", "close"):
        if column in daily:
            daily[column] = pd.to_numeric(daily[column], errors="coerce")
    daily = daily.dropna(subset=["date", "adj_close"]).sort_values("date")
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
    if len(monthly) >= 193:
        current_month = monthly.index[-1].month
        same_month = month_returns.loc[month_returns.index.month == current_month].dropna()
        result["MomSeason"] = exact("MomSeason", float(same_month.iloc[-5:].mean()) if len(same_month) >= 5 else None, "same_calendar_month_return_history")
        result["MomSeason06YrPlus"] = exact("MomSeason06YrPlus", float(same_month.iloc[:-5].mean()) if len(same_month) > 5 else None, "same_month_history_excluding_recent_5y")
        result["MomSeason11YrPlus"] = exact("MomSeason11YrPlus", float(same_month.iloc[:-10].mean()) if len(same_month) > 10 else None, "same_month_history_excluding_recent_10y")
        result["MomSeason16YrPlus"] = exact("MomSeason16YrPlus", float(same_month.iloc[:-15].mean()) if len(same_month) > 15 else None, "same_month_history_excluding_recent_15y")
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
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "repurchases": ("PaymentsForRepurchaseOfCommonStock",),
    "share_issuance": ("ProceedsFromStockOptionsExercised", "ProceedsFromIssuanceOfCommonStock"),
    "shares": ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"),
    "employees": ("EntityNumberOfEmployees",),
    "backlog": ("OrderBacklog",),
}


def latest_sec_concepts(facts: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, list[float | None]]:
    """Return current and lagged canonical concepts using strict available_at."""

    if facts.empty:
        return {}
    frame = facts.copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="coerce", utc=True).dt.tz_localize(None)
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.loc[frame["available_at"].le(pd.Timestamp(as_of))].dropna(subset=["period_end", "value"])
    result: dict[str, list[float | None]] = {}
    for concept, aliases in SEC_CONCEPT_ALIASES.items():
        subset = frame.loc[frame["tag"].isin(aliases)].copy()
        if subset.empty:
            result[concept] = [None, None, None, None, None, None]
            continue
        subset["alias_rank"] = subset["tag"].map({name: index for index, name in enumerate(aliases)})
        subset = subset.sort_values(["period_end", "available_at", "alias_rank"])
        subset = subset.drop_duplicates("period_end", keep="last").sort_values("period_end")
        values = subset["value"].tail(6).tolist()[::-1]
        result[concept] = [float(value) for value in values] + [None] * (6 - len(values))
    return result


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
    debt = sum(item or 0.0 for item in (value("debt_current"), value("debt_long")))
    dividends = value("dividends")
    repurchases = value("repurchases")
    issuance = value("share_issuance")

    def exact(name: str, raw: float | None, formula: str) -> FeatureValue:
        return FeatureValue(name, raw, "exact", "sec_edgar", formula)

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
    result["BookLeverage"] = exact("BookLeverage", _safe_ratio(liabilities, assets), "liabilities_over_assets")
    result["Leverage"] = exact("Leverage", _safe_ratio(debt, market_cap), "debt_over_market_cap")
    result["AssetGrowth"] = exact("AssetGrowth", growth("assets"), "assets_growth_1y")
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
    result["NOA"] = proxy("NOA", _safe_ratio((assets or 0) - (cash or 0) - debt, assets), "net_operating_assets_proxy", "SEC taxonomy cannot reproduce every financing component exactly")
    result["dNoa"] = proxy("dNoa", None, "change_in_noa_proxy", "Requires lagged canonical financing components")
    result["RD"] = exact("RD", _safe_ratio(rd, market_cap), "rd_over_market_cap")
    result["RDS"] = exact("RDS", _safe_ratio(rd, revenue), "rd_over_sales")
    result["RDcap"] = proxy("RDcap", _safe_ratio(rd, assets), "rd_over_assets_proxy", "Official signal capitalizes R&D recursively")
    result["AdExp"] = exact("AdExp", _safe_ratio(value("advertising"), market_cap), "advertising_over_market_cap")
    result["GrAdExp"] = exact("GrAdExp", growth("advertising"), "advertising_growth_1y")
    result["grcapx"] = exact("grcapx", growth("capex"), "capex_growth_1y")
    result["grcapx3y"] = exact("grcapx3y", growth("capex", 3), "capex_growth_3y")
    result["InvestPPEInv"] = exact("InvestPPEInv", _safe_ratio((delta("ppe") or 0.0) + (delta("inventory") or 0.0), assets_lag), "ppe_plus_inventory_change_over_lag_assets")
    result["Investment"] = exact("Investment", _safe_ratio(value("capex"), revenue), "capex_over_revenue")
    result["PayoutYield"] = exact("PayoutYield", _safe_ratio((dividends or 0.0) + (repurchases or 0.0), market_cap), "dividends_plus_repurchases_over_market_cap")
    result["NetPayoutYield"] = exact("NetPayoutYield", _safe_ratio((dividends or 0.0) + (repurchases or 0.0) - (issuance or 0.0), market_cap), "net_payout_over_market_cap")
    result["NetDebtFinance"] = exact("NetDebtFinance", _safe_ratio(delta("debt_long"), assets_lag), "net_debt_change_over_lag_assets")
    result["NetDebtPrice"] = exact("NetDebtPrice", _safe_ratio(debt - (cash or 0.0), market_cap), "net_debt_over_market_cap")
    result["ShareIss1Y"] = exact("ShareIss1Y", growth("shares"), "shares_growth_1y")
    result["ShareIss5Y"] = exact("ShareIss5Y", growth("shares", 5), "shares_growth_5y")
    tangible = None
    if assets is not None:
        tangible = (cash or 0.0) + 0.715 * (value("receivables") or 0.0) + 0.547 * (inventory or 0.0) + 0.535 * (ppe or 0.0)
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


def classify_missing_signal(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Classify a non-computed predictor without claiming nonexistent data."""

    name = str(row.get("signalname", ""))
    category = str(row.get("Cat.Data", ""))
    if name in UNAVAILABLE_BY_SOURCE:
        return "unavailable", "missing_external_source", UNAVAILABLE_BY_SOURCE[name]
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
                    "source": source,
                    "formula_id": formula_id,
                    "note": note,
                    "horizon_months": horizon,
                    "data_family": definition.get("Cat.Data"),
                    "economic_family": definition.get("Cat.Economic"),
                    "tstat_reproduction": definition.get("tstat"),
                    "tstat_study": definition.get("T.Stat"),
                    "redundancy_group": group_map.get(str(signal), f"single_{signal}"),
                    "evidence_weight": evidence_weight(definition, status),
                }
            )
    frame = pd.DataFrame(rows)
    frame["percentile"] = np.nan
    for signal, index in frame.groupby("signalname").groups.items():
        sign = float(frame.loc[index, "sign"].iloc[0])
        frame.loc[index, "percentile"] = signed_percentile(frame.loc[index, "raw_value"], sign)
    return frame


def calculate_scores(features: pd.DataFrame, minimum_metrics: int = 5) -> pd.DataFrame:
    """Aggregate metric percentiles with one bounded vote per redundancy group."""

    usable = features.loc[
        features["status"].isin(["exact", "proxy"])
        & features["percentile"].notna()
        & features["evidence_weight"].gt(0)
    ].copy()
    if usable.empty:
        return pd.DataFrame(
            columns=["as_of", "symbol", "horizon_months", "score", "confidence", "metrics_used", "groups_used"]
        )
    usable["metric_weight"] = pd.to_numeric(usable["evidence_weight"], errors="coerce").fillna(0.0)
    group_weight_sum = usable.groupby(["symbol", "horizon_months", "redundancy_group"])["metric_weight"].transform("sum")
    usable["within_group_weight"] = usable["metric_weight"] / group_weight_sum.replace(0, np.nan)
    usable["group_score_component"] = usable["percentile"] * usable["within_group_weight"]
    groups = usable.groupby(["as_of", "symbol", "horizon_months", "redundancy_group"], as_index=False).agg(
        group_score=("group_score_component", "sum"),
        group_evidence=("metric_weight", "mean"),
        metrics_in_group=("signalname", "nunique"),
    )
    groups["weighted_score"] = groups["group_score"] * groups["group_evidence"]
    summary = groups.groupby(["as_of", "symbol", "horizon_months"], as_index=False).agg(
        weighted_sum=("weighted_score", "sum"),
        total_weight=("group_evidence", "sum"),
        groups_used=("redundancy_group", "nunique"),
        metrics_used=("metrics_in_group", "sum"),
    )
    summary["score"] = summary["weighted_sum"] / summary["total_weight"].replace(0, np.nan)
    summary["confidence"] = np.minimum(100.0, 100.0 * summary["groups_used"] / 25.0)
    available_by_horizon = (
        usable.groupby("horizon_months")["signalname"].nunique().clip(upper=int(minimum_metrics)).astype(int)
    )
    required = summary["horizon_months"].map(available_by_horizon).fillna(int(minimum_metrics)).astype(int)
    summary.loc[summary["metrics_used"].lt(required), ["score", "confidence"]] = np.nan

    symbols = sorted(features["symbol"].astype(str).unique())
    as_of_values = sorted(features["as_of"].astype(str).unique())
    grid = pd.MultiIndex.from_product(
        [as_of_values, symbols, SUPPORTED_HORIZONS],
        names=["as_of", "symbol", "horizon_months"],
    ).to_frame(index=False)
    result = grid.merge(summary, on=["as_of", "symbol", "horizon_months"], how="left")
    result[["metrics_used", "groups_used"]] = result[["metrics_used", "groups_used"]].fillna(0).astype(int)
    result["confidence"] = result["confidence"].fillna(0.0)
    return result[["as_of", "symbol", "horizon_months", "score", "confidence", "metrics_used", "groups_used"]]


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
        if exact_values:
            dominant = "exact"
        elif proxy_values:
            dominant = "proxy"
        meta = metadata.loc[metadata["signalname"].eq(signal)].iloc[0]
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
    "FeatureValue",
    "OpenAPDataError",
    "SEC_CONCEPT_ALIASES",
    "assemble_feature_table",
    "build_redundancy_groups",
    "calculate_accounting_features",
    "calculate_price_features",
    "calculate_scores",
    "classify_missing_signal",
    "coverage_report",
    "evidence_weight",
    "latest_sec_concepts",
    "select_strict_predictors",
    "sha256_file",
    "signed_percentile",
    "write_summary",
]

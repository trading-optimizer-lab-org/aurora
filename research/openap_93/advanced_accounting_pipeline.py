"""Current point-in-time reconstructions that need multi-year SEC history.

These formulas mirror the pinned OpenSourceAP implementations while replacing
Compustat/CRSP identifiers with audited SEC facts and the primary Yahoo price
series already stored by Aurora.  Material substitutions remain research-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .registry import FidelityClass


ADVANCED_ACCOUNTING_IMPLEMENTED_SIGNALS = frozenset(
    {
        "BrandInvest",
        "CompEquIss",
        "EarningsConsistency",
        "Herf",
        "HerfBE",
        "IntanBM",
        "IntanCFP",
        "IntanEP",
        "IntanSP",
        "MeanRankRevGrowth",
        "OrgCap",
        "RDIPO",
    }
)


ANNUAL_ALIASES: dict[str, tuple[str, ...]] = {
    "advertising": ("AdvertisingExpense",),
    "assets": ("Assets",),
    "depreciation": ("DepreciationDepletionAndAmortization", "Depreciation"),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "preferred_stock": ("PreferredStockValue", "PreferredStockCarryingValue"),
    "rd": ("ResearchAndDevelopmentExpense",),
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "sga": ("SellingGeneralAndAdministrativeExpense",),
    "shares": ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"),
}

FLOW_CONCEPTS = {
    "advertising",
    "depreciation",
    "net_income",
    "rd",
    "revenue",
    "sga",
}


@dataclass(frozen=True)
class AdvancedValue:
    symbol: str
    signal: str
    value: float | None
    fidelity: FidelityClass
    formula_id: str
    source_ids: tuple[str, ...]
    available_at: pd.Timestamp | None
    period_end: pd.Timestamp | None
    observation_count: int
    reason_if_missing: str = ""
    caveat: str = ""

    def record(self, formation_at: pd.Timestamp) -> dict[str, Any]:
        finite = self.value is not None and np.isfinite(float(self.value))
        fidelity = self.fidelity if finite else FidelityClass.UNAVAILABLE
        available = pd.to_datetime(self.available_at, errors="coerce")
        period = pd.to_datetime(self.period_end, errors="coerce")
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "value": float(self.value) if finite else None,
            "fidelity_class": fidelity.value,
            "current_usable": bool(
                finite
                and fidelity
                in {
                    FidelityClass.EXACT,
                    FidelityClass.RECONSTRUCTED,
                    FidelityClass.VALIDATED_PROXY,
                }
            ),
            "formula_id": self.formula_id,
            "source_ids": "|".join(self.source_ids),
            "available_at": available,
            "period_end": period,
            "observation_count": int(self.observation_count),
            "reason_if_missing": "" if finite else self.reason_if_missing,
            "caveat": self.caveat,
            "formation_at": formation_at,
            "staleness_days": (
                int((formation_at.normalize() - available.normalize()).days)
                if pd.notna(available)
                else np.nan
            ),
        }


def _naive_datetime(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_localize(None)


def _finite(value: Any) -> float | None:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(number) if pd.notna(number) and np.isfinite(number) else None


def _prepare_annual_facts(
    companyfacts: pd.DataFrame,
    formation_at: pd.Timestamp,
) -> pd.DataFrame:
    facts = companyfacts.copy()
    facts["available_at"] = _naive_datetime(facts["available_at"])
    facts["period_end"] = pd.to_datetime(facts["period_end"], errors="coerce")
    facts["period_start"] = pd.to_datetime(facts["period_start"], errors="coerce")
    facts["value"] = pd.to_numeric(facts["value"], errors="coerce")
    facts = facts.loc[
        facts["available_at"].le(formation_at)
        & facts["form"].isin({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})
        & facts["period_end"].notna()
        & facts["value"].notna()
    ].copy()
    inverse = {
        tag: (concept, priority)
        for concept, aliases in ANNUAL_ALIASES.items()
        for priority, tag in enumerate(aliases)
    }
    facts = facts.loc[facts["tag"].isin(inverse)].copy()
    facts["concept"] = facts["tag"].map(lambda tag: inverse[str(tag)][0])
    facts["tag_priority"] = facts["tag"].map(lambda tag: inverse[str(tag)][1])
    duration = (facts["period_end"] - facts["period_start"]).dt.days
    flow = facts["concept"].isin(FLOW_CONCEPTS)
    facts = facts.loc[~flow | duration.between(250, 450)].copy()
    facts = facts.sort_values(
        ["symbol", "period_end", "concept", "tag_priority", "available_at"]
    ).drop_duplicates(["symbol", "period_end", "concept"], keep="last")
    values = facts.pivot(index=["symbol", "period_end"], columns="concept", values="value")
    for concept in ANNUAL_ALIASES:
        if concept not in values.columns:
            values[concept] = np.nan
    dates = facts.groupby(["symbol", "period_end"])["available_at"].max()
    rows = values.join(dates.rename("available_at")).reset_index()
    return rows.sort_values(["symbol", "available_at", "period_end"])


def _attach_sic(
    annual: pd.DataFrame,
    master: pd.DataFrame,
    submissions: pd.DataFrame,
    formation_at: pd.Timestamp,
) -> pd.DataFrame:
    result = annual.copy()
    sub = submissions.copy()
    if not sub.empty:
        sub["accepted_at"] = _naive_datetime(sub["accepted_at"])
        sub["sic"] = pd.to_numeric(sub["sic"], errors="coerce")
        sub = sub.loc[sub["accepted_at"].le(formation_at) & sub["sic"].notna()]
        latest = (
            sub.sort_values(["cik", "accepted_at"])
            .drop_duplicates("cik", keep="last")[["cik", "sic"]]
        )
    else:
        latest = pd.DataFrame(columns=["cik", "sic"])
    identity = master[["symbol", "cik"]].drop_duplicates("symbol").merge(
        latest, on="cik", how="left"
    )
    return result.merge(identity, on="symbol", how="left", validate="many_to_one")


def _monthly_prices(prices: pd.DataFrame, formation_at: pd.Timestamp) -> pd.DataFrame:
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.loc[frame["date"].le(formation_at)].dropna(
        subset=["symbol", "date", "close", "adj_close"]
    )
    frame = frame.sort_values(["symbol", "date"])
    frame["month"] = frame["date"].dt.to_period("M").dt.to_timestamp("M")
    monthly = (
        frame.groupby(["symbol", "month"], as_index=False)
        .agg(close=("close", "last"), adj_close=("adj_close", "last"), price_date=("date", "last"))
        .sort_values(["symbol", "month"])
    )
    monthly["ret"] = monthly.groupby("symbol")["adj_close"].pct_change(fill_method=None)
    return monthly


def _monthly_asof(
    annual: pd.DataFrame,
    monthly_prices: pd.DataFrame,
    formation_at: pd.Timestamp,
    months: int = 84,
) -> pd.DataFrame:
    current_month = monthly_prices["month"].max()
    first_month = current_month - pd.DateOffset(months=months)
    prices = monthly_prices.loc[monthly_prices["month"].between(first_month, current_month)].copy()
    output: list[pd.DataFrame] = []
    annual_groups = {symbol: part for symbol, part in annual.groupby("symbol")}
    for symbol, left in prices.groupby("symbol", sort=False):
        right = annual_groups.get(symbol)
        left = left.sort_values("month")
        if right is None or right.empty:
            output.append(left)
            continue
        right = right.sort_values("available_at").drop_duplicates("available_at", keep="last")
        output.append(
            pd.merge_asof(
                left,
                right.drop(columns="symbol"),
                left_on="month",
                right_on="available_at",
                direction="backward",
                allow_exact_matches=True,
            )
        )
        output[-1]["symbol"] = symbol
    if not output:
        return pd.DataFrame()
    panel = pd.concat(output, ignore_index=True)
    panel = panel.sort_values(["symbol", "month"]).reset_index(drop=True)
    return panel


def _latest_sic(master: pd.DataFrame, submissions: pd.DataFrame, formation: pd.Timestamp) -> pd.DataFrame:
    identity = master[["symbol", "cik"]].drop_duplicates("symbol")
    if submissions.empty:
        identity["sic"] = np.nan
        return identity
    sub = submissions.copy()
    sub["accepted_at"] = _naive_datetime(sub["accepted_at"])
    sub["sic"] = pd.to_numeric(sub["sic"], errors="coerce")
    sub = sub.loc[sub["accepted_at"].le(formation) & sub["sic"].notna()]
    latest = sub.sort_values(["cik", "accepted_at"]).drop_duplicates("cik", keep="last")
    return identity.merge(latest[["cik", "sic"]], on="cik", how="left")


def _brand_invest(annual: pd.DataFrame) -> dict[str, tuple[float, pd.Timestamp, pd.Timestamp, int]]:
    output: dict[str, tuple[float, pd.Timestamp, pd.Timestamp, int]] = {}
    for symbol, group in annual.groupby("symbol"):
        rows = group.sort_values("period_end")
        capital: float | None = None
        prior_scaled: float | None = None
        latest: tuple[float, pd.Timestamp, pd.Timestamp, int] | None = None
        used = 0
        for row in rows.itertuples():
            sic = _finite(getattr(row, "sic", np.nan))
            if sic is not None and (4900 <= sic <= 4999 or 6000 <= sic <= 6999):
                continue
            advertising = _finite(getattr(row, "advertising", np.nan))
            assets = _finite(getattr(row, "assets", np.nan))
            if capital is None:
                if advertising is None:
                    continue
                capital = advertising / 0.6
            else:
                capital = 0.5 * capital + (advertising or 0.0)
            current_scaled = capital / assets if assets and assets > 0 and advertising is not None else None
            if prior_scaled not in (None, 0.0):
                value = (advertising or 0.0) / prior_scaled
                if np.isfinite(value):
                    used += 1
                    latest = (float(value), row.available_at, row.period_end, used)
            prior_scaled = current_scaled
        if latest is not None:
            output[str(symbol)] = latest
    return output


def _org_cap(
    annual: pd.DataFrame,
    gnp_deflator: pd.DataFrame,
) -> dict[str, tuple[float, pd.Timestamp, pd.Timestamp, int]]:
    deflator = gnp_deflator.copy()
    deflator["date"] = pd.to_datetime(deflator["date"], errors="coerce")
    deflator = deflator.dropna(subset=["date", "gnpdef"]).sort_values("date")
    raw_rows: list[dict[str, Any]] = []
    for symbol, group in annual.groupby("symbol"):
        capital: float | None = None
        count = 0
        for row in group.sort_values("period_end").itertuples():
            sga = _finite(getattr(row, "sga", np.nan)) or 0.0
            assets = _finite(getattr(row, "assets", np.nan))
            eligible = deflator.loc[deflator["date"].le(pd.Timestamp(row.period_end))]
            if eligible.empty or assets in (None, 0.0):
                continue
            real_sga = sga / float(eligible.iloc[-1]["gnpdef"])
            capital = 4.0 * real_sga if capital is None else 0.85 * capital + real_sga
            if capital == 0:
                continue
            count += 1
            raw_rows.append(
                {
                    "symbol": symbol,
                    "period_end": row.period_end,
                    "available_at": row.available_at,
                    "sic": _finite(getattr(row, "sic", np.nan)),
                    "raw": capital / assets,
                    "count": count,
                }
            )
    if not raw_rows:
        return {}
    latest = pd.DataFrame(raw_rows).sort_values(["symbol", "available_at"]).drop_duplicates(
        "symbol", keep="last"
    )
    lower, upper = latest["raw"].quantile([0.01, 0.99])
    latest["trimmed"] = latest["raw"].clip(lower, upper)
    latest["industry"] = (pd.to_numeric(latest["sic"], errors="coerce") // 100).astype("Int64")
    stats = latest.groupby("industry")["trimmed"].agg(["mean", "std"])
    latest = latest.join(stats, on="industry")
    latest["value"] = (latest["trimmed"] - latest["mean"]) / latest["std"]
    return {
        str(row.symbol): (float(row.value), row.available_at, row.period_end, int(row.count))
        for row in latest.dropna(subset=["value"]).itertuples()
        if not (6000 <= float(row.sic) < 7000)
    }


def _latest_from_panel(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.sort_values(["symbol", "month"]).drop_duplicates("symbol", keep="last")


def _comp_equity_issuance(panel: pd.DataFrame) -> pd.Series:
    data = panel.copy()
    data["mve"] = data["close"] * data["shares"]
    data["cumret"] = data.groupby("symbol")["ret"].transform(
        lambda values: (1.0 + values.fillna(0.0)).cumprod()
    )
    for column in ("mve", "cumret"):
        data[f"{column}_lag60"] = data.groupby("symbol")[column].shift(60)
    data["buy_hold_60"] = data["cumret"] / data["cumret_lag60"] - 1.0
    valid = (data["mve"] > 0) & (data["mve_lag60"] > 0)
    data["value"] = np.nan
    data.loc[valid, "value"] = (
        np.log(data.loc[valid, "mve"] / data.loc[valid, "mve_lag60"])
        - data.loc[valid, "buy_hold_60"]
    )
    return _latest_from_panel(data).set_index("symbol")["value"]


def _mean_rank_revenue_growth(panel: pd.DataFrame) -> pd.Series:
    data = panel.copy()
    data["revenue_lag12"] = data.groupby("symbol")["revenue"].shift(12)
    valid = (data["revenue"] > 0) & (data["revenue_lag12"] > 0)
    data["growth"] = np.nan
    data.loc[valid, "growth"] = np.log(data.loc[valid, "revenue"]) - np.log(
        data.loc[valid, "revenue_lag12"]
    )
    data["rank"] = data.groupby("month")["growth"].rank(ascending=False, method="first")
    lags = []
    for lag in (12, 24, 36, 48, 60):
        column = f"rank_lag{lag}"
        data[column] = data.groupby("symbol")["rank"].shift(lag)
        lags.append(column)
    data["value"] = (
        5 * data[lags[0]]
        + 4 * data[lags[1]]
        + 3 * data[lags[2]]
        + 2 * data[lags[3]]
        + data[lags[4]]
    ) / 15.0
    return _latest_from_panel(data).set_index("symbol")["value"]


def _earnings_consistency(panel: pd.DataFrame) -> pd.Series:
    data = panel.copy()
    data["eps"] = data["net_income"] / data["shares"].replace(0, np.nan)
    data["eps_lag12"] = data.groupby("symbol")["eps"].shift(12)
    data["eps_lag24"] = data.groupby("symbol")["eps"].shift(24)
    denominator = 0.5 * (data["eps_lag12"].abs() + data["eps_lag24"].abs())
    data["growth"] = (data["eps"] - data["eps_lag12"]) / denominator.replace(0, np.nan)
    growth_columns = ["growth"]
    for lag in (12, 24, 36, 48):
        column = f"growth_lag{lag}"
        data[column] = data.groupby("symbol")["growth"].shift(lag)
        growth_columns.append(column)
    data["value"] = data[growth_columns].mean(axis=1, skipna=True)
    prior_growth = data["growth_lag12"]
    exception = (
        data["eps"].isna()
        | data["eps_lag12"].isna()
        | (data["eps"].abs() / data["eps_lag12"].abs().replace(0, np.nan) > 6)
        | ((data["growth"] > 0) & (prior_growth < 0))
        | ((data["growth"] < 0) & ((prior_growth > 0) | prior_growth.isna()))
    )
    data.loc[exception, "value"] = np.nan
    return _latest_from_panel(data).set_index("symbol")["value"]


def _intangible_residuals(panel: pd.DataFrame) -> dict[str, pd.Series]:
    data = panel.copy()
    data["mve"] = data["close"] * data["shares"]
    data["cumret"] = data.groupby("symbol")["ret"].transform(
        lambda values: (1.0 + values.fillna(0.0)).cumprod()
    )
    data["cumret_lag60"] = data.groupby("symbol")["cumret"].shift(60)
    data["ret60"] = data["cumret"] / data["cumret_lag60"] - 1.0
    current_month = data["month"].max()
    current_mask = data["month"].eq(current_month)
    current = data.loc[current_mask].copy()
    if current.empty:
        return {}
    lower, upper = current["ret60"].quantile([0.01, 0.99])
    data.loc[current_mask & ~data["ret60"].between(lower, upper), "ret60"] = np.nan
    definitions = {
        "IntanBM": np.log((data["equity"] / data["mve"]).where((data["equity"] / data["mve"]) > 0)),
        "IntanSP": data["revenue"] / data["mve"],
        "IntanCFP": (data["net_income"] + data["depreciation"]) / data["mve"],
        "IntanEP": data["net_income"] / data["mve"],
    }
    output: dict[str, pd.Series] = {}
    for signal, measure in definitions.items():
        data["measure"] = measure
        data["measure_lag60"] = data.groupby("symbol")["measure"].shift(60)
        data["measure_ret"] = data["measure"] - data["measure_lag60"] + data["ret60"]
        sample = data.loc[data["month"].eq(current_month), [
            "symbol", "ret60", "measure_lag60", "measure_ret"
        ]].dropna()
        if len(sample) < 20:
            output[signal] = pd.Series(dtype=float)
            continue
        x = np.column_stack(
            [np.ones(len(sample)), sample["measure_lag60"], sample["measure_ret"]]
        )
        coefficients, *_ = np.linalg.lstsq(x, sample["ret60"].to_numpy(), rcond=None)
        residual = sample["ret60"].to_numpy() - x @ coefficients
        output[signal] = pd.Series(residual, index=sample["symbol"].astype(str))
    return output


def _append_value(
    rows: list[AdvancedValue],
    *,
    symbol: str,
    signal: str,
    value: Any,
    fidelity: FidelityClass,
    formula_id: str,
    source_ids: tuple[str, ...],
    available_at: Any,
    period_end: Any,
    observation_count: int,
    caveat: str = "",
) -> None:
    number = _finite(value)
    rows.append(
        AdvancedValue(
            symbol=symbol,
            signal=signal,
            value=number,
            fidelity=fidelity,
            formula_id=formula_id,
            source_ids=source_ids,
            available_at=pd.to_datetime(available_at, errors="coerce"),
            period_end=pd.to_datetime(period_end, errors="coerce"),
            observation_count=observation_count,
            reason_if_missing="missing_causal_multiyear_inputs",
            caveat=caveat,
        )
    )


def calculate_advanced_accounting_signals(
    security_master: pd.DataFrame,
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    prices_daily: pd.DataFrame,
    gnp_deflator: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate current multi-year formulas without using future observations."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    master = security_master.copy().drop_duplicates("symbol")
    annual = _prepare_annual_facts(companyfacts, formation)
    annual = _attach_sic(annual, master, submissions, formation)
    monthly_prices = _monthly_prices(prices_daily, formation)
    panel = _monthly_asof(annual, monthly_prices, formation)
    latest = _latest_from_panel(panel).set_index("symbol") if not panel.empty else pd.DataFrame()
    symbols = sorted(master["symbol"].astype(str).unique())
    rows: list[AdvancedValue] = []

    brand = _brand_invest(annual.loc[annual["period_end"].dt.month.eq(12)])
    org = _org_cap(annual.loc[annual["period_end"].dt.month.eq(12)], gnp_deflator)
    comp_equity = _comp_equity_issuance(panel) if not panel.empty else pd.Series(dtype=float)
    revenue_rank = _mean_rank_revenue_growth(panel) if not panel.empty else pd.Series(dtype=float)
    consistency = _earnings_consistency(panel) if not panel.empty else pd.Series(dtype=float)
    intangibles = _intangible_residuals(panel) if not panel.empty else {}

    sic = _latest_sic(master, submissions, formation).set_index("symbol")["sic"]
    if not panel.empty:
        concentration = panel.copy()
        concentration["sic"] = concentration["symbol"].map(sic)
        concentration["industry"] = pd.to_numeric(concentration["sic"], errors="coerce").astype("Int64")
        concentration["book_equity_proxy"] = concentration["equity"] - concentration["preferred_stock"].fillna(0.0)
        for base_column, output_column in (("revenue", "herf"), ("book_equity_proxy", "herf_be")):
            total = concentration.groupby(["month", "industry"])[base_column].transform("sum")
            share_sq = (concentration[base_column] / total.replace(0, np.nan)) ** 2
            concentration[output_column] = share_sq.groupby(
                [concentration["month"], concentration["industry"]]
            ).transform("sum")
            concentration[output_column] = concentration.groupby("symbol")[output_column].transform(
                lambda values: values.rolling(36, min_periods=12).mean()
            )
        concentration_latest = _latest_from_panel(concentration).set_index("symbol")
        regulated = pd.to_numeric(concentration_latest["sic"], errors="coerce").between(
            4900, 4999
        )
        concentration_latest.loc[regulated, ["herf", "herf_be"]] = np.nan
    else:
        concentration_latest = pd.DataFrame()

    for symbol in symbols:
        latest_row = latest.loc[symbol] if symbol in latest.index else pd.Series(dtype=object)
        price_date = latest_row.get("price_date", pd.NaT)
        accounting_date = latest_row.get("available_at", pd.NaT)
        current_available = max(
            [date for date in (price_date, accounting_date) if pd.notna(date)],
            default=pd.NaT,
        )
        period_end = latest_row.get("period_end", pd.NaT)
        monthly_count = int((panel["symbol"] == symbol).sum()) if not panel.empty else 0

        brand_value = brand.get(symbol)
        _append_value(
            rows,
            symbol=symbol,
            signal="BrandInvest",
            value=brand_value[0] if brand_value else None,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_brandinvest_sec_recursive_capital",
            source_ids=("sec_edgar",),
            available_at=brand_value[1] if brand_value else pd.NaT,
            period_end=brand_value[2] if brand_value else pd.NaT,
            observation_count=brand_value[3] if brand_value else 0,
            caveat="SEC AdvertisingExpense replaces Compustat xad; December fiscal year ends only",
        )
        org_value = org.get(symbol)
        _append_value(
            rows,
            symbol=symbol,
            signal="OrgCap",
            value=org_value[0] if org_value else None,
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            formula_id="openap_orgcap_sec_sga_sic2_proxy",
            source_ids=("sec_edgar", "fred_public_csv"),
            available_at=org_value[1] if org_value else pd.NaT,
            period_end=org_value[2] if org_value else pd.NaT,
            observation_count=org_value[3] if org_value else 0,
            caveat="Uses SEC two-digit SIC groups instead of the official CRSP SIC FF17 map",
        )
        _append_value(
            rows,
            symbol=symbol,
            signal="CompEquIss",
            value=comp_equity.get(symbol),
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_compequiss_60m_sec_shares_yahoo_return",
            source_ids=("sec_edgar", "yahoo_public"),
            available_at=current_available,
            period_end=period_end,
            observation_count=monthly_count,
            caveat="Primary-share price times SEC issuer shares replaces CRSP company market equity",
        )
        _append_value(
            rows,
            symbol=symbol,
            signal="MeanRankRevGrowth",
            value=revenue_rank.get(symbol),
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_weighted_revenue_growth_ranks_12_60m_sec",
            source_ids=("sec_edgar",),
            available_at=accounting_date,
            period_end=period_end,
            observation_count=monthly_count,
        )
        _append_value(
            rows,
            symbol=symbol,
            signal="EarningsConsistency",
            value=consistency.get(symbol),
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            formula_id="openap_earnings_consistency_net_income_per_sec_share_proxy",
            source_ids=("sec_edgar",),
            available_at=accounting_date,
            period_end=period_end,
            observation_count=monthly_count,
            caveat="Derives EPS from SEC net income and shares instead of Compustat epspx",
        )

        for signal in ("IntanBM", "IntanSP", "IntanCFP", "IntanEP"):
            values = intangibles.get(signal, pd.Series(dtype=float))
            fidelity = (
                FidelityClass.UNVALIDATED_PROXY
                if signal == "IntanCFP"
                else FidelityClass.RECONSTRUCTED
            )
            caveat = (
                "Uses net income plus depreciation instead of Compustat income before extraordinary items"
                if signal == "IntanCFP"
                else "SEC annual inputs carried causally and primary-share market equity replace Compustat/CRSP"
            )
            _append_value(
                rows,
                symbol=symbol,
                signal=signal,
                value=values.get(symbol),
                fidelity=fidelity,
                formula_id=f"openap_{signal.lower()}_60m_cross_sectional_residual_sec_yahoo",
                source_ids=("sec_edgar", "yahoo_public"),
                available_at=current_available,
                period_end=period_end,
                observation_count=monthly_count,
                caveat=caveat,
            )

        if symbol in concentration_latest.index:
            concentration_row = concentration_latest.loc[symbol]
            herf = concentration_row.get("herf")
            herf_be = concentration_row.get("herf_be")
        else:
            herf = herf_be = None
        _append_value(
            rows,
            symbol=symbol,
            signal="Herf",
            value=herf,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_herf_36m_sec_revenue_sic4",
            source_ids=("sec_edgar",),
            available_at=accounting_date,
            period_end=period_end,
            observation_count=min(monthly_count, 36),
            caveat="SEC filing SIC replaces CRSP historical SIC",
        )
        _append_value(
            rows,
            symbol=symbol,
            signal="HerfBE",
            value=herf_be,
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            formula_id="openap_herfbe_36m_sec_equity_proxy",
            source_ids=("sec_edgar",),
            available_at=accounting_date,
            period_end=period_end,
            observation_count=min(monthly_count, 36),
            caveat="Deferred-tax balance is unavailable; uses equity less preferred stock",
        )

        first_trade = pd.to_datetime(
            master.loc[master["symbol"].eq(symbol), "first_price_date"].iloc[0],
            errors="coerce",
        )
        rd = _finite(latest_row.get("rd"))
        months_since_ipo = (
            (formation.year - first_trade.year) * 12 + formation.month - first_trade.month
            if pd.notna(first_trade)
            else None
        )
        rdipo = (
            1.0
            if months_since_ipo is not None and 6 < months_since_ipo <= 36 and rd == 0.0
            else 0.0 if months_since_ipo is not None and rd is not None else None
        )
        _append_value(
            rows,
            symbol=symbol,
            signal="RDIPO",
            value=rdipo,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_rdipo_sec_rd_yahoo_first_trade",
            source_ids=("sec_edgar", "yahoo_public"),
            available_at=current_available,
            period_end=period_end,
            observation_count=1 if rdipo is not None else 0,
            caveat="Yahoo first clean price date substitutes for CRSP IPO date",
        )

    return pd.DataFrame([row.record(formation) for row in rows])


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    source_map: dict[str, tuple[str, ...]] = {
        "BrandInvest": ("sec_edgar",),
        "CompEquIss": ("sec_edgar", "yahoo_public"),
        "EarningsConsistency": ("sec_edgar",),
        "Herf": ("sec_edgar",),
        "HerfBE": ("sec_edgar",),
        "IntanBM": ("sec_edgar", "yahoo_public"),
        "IntanCFP": ("sec_edgar", "yahoo_public"),
        "IntanEP": ("sec_edgar", "yahoo_public"),
        "IntanSP": ("sec_edgar", "yahoo_public"),
        "MeanRankRevGrowth": ("sec_edgar",),
        "OrgCap": ("sec_edgar", "fred_public_csv"),
        "RDIPO": ("sec_edgar", "yahoo_public"),
    }
    return frozenset(
        (signal, source) for signal, sources in source_map.items() for source in sources
    )

"""Current SEC reconstructions for the accounting members of the OpenAP 93.

The input is the audited, point-in-time ``sec_concept_inputs_current`` table
created by Aurora's SEC pipeline.  Values are never forward-filled and every
output carries the newest publication date among its required inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .registry import FidelityClass


ACCOUNTING_IMPLEMENTED_SIGNALS = frozenset(
    {
        "AccrualsBM",
        "BMdec",
        "CBOperProf",
        "ChInvIA",
        "DelNetFin",
        "EntMult",
        "OScore",
        "OrderBacklog",
        "OrderBacklogChg",
        "PctTotAcc",
        "PS",
        "Tax",
        "dNoa",
        "hire",
    }
)


@dataclass(frozen=True)
class AccountingSignalValue:
    symbol: str
    signal: str
    value: float | None
    fidelity: FidelityClass
    formula_id: str
    source_ids: tuple[str, ...]
    available_at: pd.Timestamp | None
    period_end: pd.Timestamp | None
    observation_count: int
    missing_reason: str = ""
    caveat: str = ""

    def to_record(self, formation_at: pd.Timestamp) -> dict[str, Any]:
        value = self.value
        finite = value is not None and np.isfinite(float(value))
        fidelity = self.fidelity if finite else FidelityClass.UNAVAILABLE
        available = pd.to_datetime(self.available_at, errors="coerce")
        period_end = pd.to_datetime(self.period_end, errors="coerce")
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "value": float(value) if finite else None,
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
            "period_end": period_end,
            "observation_count": int(self.observation_count),
            "reason_if_missing": "" if finite else self.missing_reason,
            "caveat": self.caveat,
            "formation_at": formation_at,
            "staleness_days": (
                int((formation_at.normalize() - available.normalize()).days)
                if pd.notna(available)
                else np.nan
            ),
        }


def _number(value: Any) -> float | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) and np.isfinite(numeric) else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-12:
        return None
    result = numerator / denominator
    return float(result) if np.isfinite(result) else None


def _growth(current: float | None, lagged: float | None) -> float | None:
    if current is None or lagged is None or lagged <= 0 or current <= 0:
        return None
    return float(np.log(current) - np.log(lagged))


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    result = left - right
    return float(result) if np.isfinite(result) else None


def _quantile(values: pd.Series, bins: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = numeric.notna()
    if int(valid.sum()) >= bins:
        result.loc[valid] = (
            pd.qcut(
                numeric.loc[valid].rank(method="first"),
                q=bins,
                labels=False,
                duplicates="drop",
            ).astype(float)
            + 1.0
        )
    return result


def _prepare_inputs(
    concept_inputs: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = concept_inputs.copy()
    frame["available_at"] = pd.to_datetime(
        frame["available_at"], errors="coerce", utc=True
    ).dt.tz_localize(None)
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["concept_lag"] = pd.to_numeric(frame["concept_lag"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "concept", "concept_lag"])
    frame = frame.sort_values(["symbol", "concept", "concept_lag", "available_at"])
    frame = frame.drop_duplicates(["symbol", "concept", "concept_lag"], keep="last")
    index = ["symbol"]
    columns = ["concept", "concept_lag"]
    values = frame.pivot(index=index, columns=columns, values="value")
    available = frame.pivot(index=index, columns=columns, values="available_at")
    periods = frame.pivot(index=index, columns=columns, values="period_end")
    counts = frame.groupby("symbol").size().to_frame("input_count")
    return values, available, periods, counts


def _lookup(frame: pd.DataFrame, symbol: str, concept: str, lag: int = 0) -> float | None:
    key = (concept, lag)
    if symbol not in frame.index or key not in frame.columns:
        return None
    return _number(frame.loc[symbol, key])


def _latest_date(
    frame: pd.DataFrame,
    symbol: str,
    dependencies: tuple[tuple[str, int], ...],
) -> pd.Timestamp | None:
    dates: list[pd.Timestamp] = []
    for dependency in dependencies:
        if symbol not in frame.index or dependency not in frame.columns:
            return None
        date = pd.to_datetime(frame.loc[symbol, dependency], errors="coerce")
        if pd.isna(date):
            return None
        dates.append(date)
    return max(dates) if dates else None


def _append(
    rows: list[AccountingSignalValue],
    *,
    symbol: str,
    signal: str,
    value: float | None,
    fidelity: FidelityClass,
    formula_id: str,
    dependencies: tuple[tuple[str, int], ...],
    available: pd.DataFrame,
    periods: pd.DataFrame,
    source_ids: tuple[str, ...] = ("sec_edgar",),
    caveat: str = "",
) -> None:
    available_at = _latest_date(available, symbol, dependencies)
    period_end = _latest_date(periods, symbol, dependencies)
    finite = value is not None and np.isfinite(float(value))
    rows.append(
        AccountingSignalValue(
            symbol=symbol,
            signal=signal,
            value=float(value) if finite else None,
            fidelity=fidelity,
            formula_id=formula_id,
            source_ids=source_ids,
            available_at=available_at,
            period_end=period_end,
            observation_count=sum(
                1
                for dependency in dependencies
                if symbol in available.index
                and dependency in available.columns
                and pd.notna(available.loc[symbol, dependency])
            ),
            missing_reason="missing_point_in_time_sec_inputs",
            caveat=caveat,
        )
    )


def _market_cap(master: pd.DataFrame, symbol: str) -> float | None:
    if symbol not in master.index:
        return None
    for column in ("issuer_market_cap", "marketCap", "market_cap"):
        if column in master.columns:
            value = _number(master.loc[symbol, column])
            if value is not None and value > 0:
                return value
    return None


def calculate_accounting_signals(
    security_master: pd.DataFrame,
    concept_inputs: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    gnp_deflator: float | None = None,
) -> pd.DataFrame:
    """Calculate the SEC-supported accounting subset and fail closed elsewhere."""

    formation = pd.Timestamp(formation_at).tz_localize(None)
    master = security_master.copy().drop_duplicates("symbol").set_index("symbol")
    values, available, periods, counts = _prepare_inputs(concept_inputs)
    symbols = sorted(set(master.index.astype(str)) & set(values.index.astype(str)))
    rows: list[AccountingSignalValue] = []
    cross: list[dict[str, Any]] = []

    for symbol in symbols:
        def get(
            concept: str,
            lag: int = 0,
            bound_symbol: str = symbol,
        ) -> float | None:
            return _lookup(values, bound_symbol, concept, lag)

        assets = get("assets")
        assets_lag = get("assets", 1)
        cash = get("cash")
        cash_lag = get("cash", 1)
        liabilities = get("liabilities")
        liabilities_lag = get("liabilities", 1)
        equity = get("equity")
        equity_lag = get("equity", 1)
        current_assets = get("current_assets")
        current_assets_lag = get("current_assets", 1)
        current_liabilities = get("current_liabilities")
        current_liabilities_lag = get("current_liabilities", 1)
        debt_current_input = get("debt_current")
        debt_current = debt_current_input or 0.0
        debt_current_lag = get("debt_current", 1) or 0.0
        debt_long_input = get("debt_long")
        debt_long = debt_long_input or 0.0
        debt_long_lag = get("debt_long", 1) or 0.0
        preferred = get("preferred_stock") or 0.0
        preferred_lag = get("preferred_stock", 1) or 0.0
        revenue = get("revenue")
        cogs = get("cogs")
        sga = get("sga")
        rd = get("rd") or 0.0
        receivables = get("receivables") or 0.0
        receivables_lag = get("receivables", 1) or 0.0
        inventory = get("inventory") or 0.0
        inventory_lag = get("inventory", 1) or 0.0
        net_income = get("net_income")
        net_income_lag = get("net_income", 1)
        ocf = get("operating_cash_flow")
        ocf_lag = get("operating_cash_flow", 1)
        market_cap = _market_cap(master, symbol)

        noa = (
            assets
            - cash
            - (assets - debt_long - debt_current - preferred - equity)
            if None not in (assets, cash, equity)
            else None
        )
        noa_lag = (
            assets_lag
            - cash_lag
            - (
                assets_lag
                - debt_long_lag
                - debt_current_lag
                - preferred_lag
                - equity_lag
            )
            if None not in (assets_lag, cash_lag, equity_lag)
            else None
        )
        d_noa = _ratio(
            noa - noa_lag if noa is not None and noa_lag is not None else None,
            assets_lag,
        )
        _append(
            rows,
            symbol=symbol,
            signal="dNoa",
            value=d_noa,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_dnoa_sec_components_lag12",
            dependencies=(
                ("assets", 0),
                ("assets", 1),
                ("cash", 0),
                ("cash", 1),
                ("equity", 0),
                ("equity", 1),
            ),
            available=available,
            periods=periods,
            caveat="Minority interest is zero-filled exactly as the OpenAP implementation permits",
        )

        ebitda = (
            get("operating_income") + get("depreciation")
            if get("operating_income") is not None and get("depreciation") is not None
            else None
        )
        enterprise_value = (
            market_cap + debt_current + debt_long - cash
            if market_cap is not None and cash is not None
            else None
        )
        _append(
            rows,
            symbol=symbol,
            signal="EntMult",
            value=_ratio(enterprise_value, ebitda),
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_enterprise_value_over_oibdp_sec",
            dependencies=(("operating_income", 0), ("depreciation", 0), ("cash", 0)),
            available=available,
            periods=periods,
            source_ids=("sec_edgar", "yahoo_public"),
        )

        backlog = get("backlog")
        backlog_lag = get("backlog", 1)
        _append(
            rows,
            symbol=symbol,
            signal="OrderBacklog",
            value=_ratio(
                backlog,
                0.5 * (assets + assets_lag)
                if assets is not None and assets_lag is not None
                else None,
            ),
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_order_backlog_over_assets_sec",
            dependencies=(("backlog", 0), ("assets", 0), ("assets", 1)),
            available=available,
            periods=periods,
        )
        _append(
            rows,
            symbol=symbol,
            signal="OrderBacklogChg",
            value=_difference(
                _ratio(backlog, 0.5 * (assets + assets_lag))
                if assets is not None and assets_lag is not None
                else None,
                _ratio(
                    backlog_lag,
                    0.5 * (assets_lag + get("assets", 2)),
                )
                if None not in (backlog_lag, assets_lag, get("assets", 2))
                else None
            ),
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_change_normalized_order_backlog_sec",
            dependencies=(
                ("backlog", 0),
                ("backlog", 1),
                ("assets", 0),
                ("assets", 1),
                ("assets", 2),
            ),
            available=available,
            periods=periods,
        )

        employees = get("employees")
        employees_lag = get("employees", 1)
        _append(
            rows,
            symbol=symbol,
            signal="hire",
            value=_ratio(
                employees - employees_lag
                if employees is not None and employees_lag is not None
                else None,
                0.5 * (employees + employees_lag)
                if employees is not None and employees_lag is not None
                else None,
            ),
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_employee_growth_sec",
            dependencies=(("employees", 0), ("employees", 1)),
            available=available,
            periods=periods,
        )

        debt = debt_current + debt_long + preferred
        debt_lag = debt_current_lag + debt_long_lag + preferred_lag
        short_inv = get("short_investments") or 0.0
        short_inv_lag = get("short_investments", 1) or 0.0
        long_inv = get("long_investments") or 0.0
        long_inv_lag = get("long_investments", 1) or 0.0
        net_fin = short_inv + long_inv - debt
        net_fin_lag = short_inv_lag + long_inv_lag - debt_lag
        _append(
            rows,
            symbol=symbol,
            signal="DelNetFin",
            value=_ratio(
                net_fin - net_fin_lag,
                np.mean([assets, assets_lag])
                if assets is not None and assets_lag is not None
                else None,
            ),
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            formula_id="openap_delnetfin_sec_partial_components",
            dependencies=(("assets", 0), ("assets", 1)),
            available=available,
            periods=periods,
            caveat="SEC taxonomies do not expose every Compustat financing component consistently",
        )

        accrual = _ratio(
            net_income - ocf if net_income is not None and ocf is not None else None,
            assets_lag,
        )
        bm = _ratio(equity, market_cap)
        capex_growth = _growth(get("capex"), get("capex", 1))
        cross.append(
            {
                "symbol": symbol,
                "accrual": accrual,
                "bm": bm if bm is not None and bm > 0 else np.nan,
                "capex_growth": capex_growth,
                "industry": str(master.loc[symbol].get("industry") or ""),
                "assets": assets,
                "assets_lag": assets_lag,
                "liabilities": liabilities,
                "current_assets": current_assets,
                "current_assets_lag": current_assets_lag,
                "current_liabilities": current_liabilities,
                "current_liabilities_lag": current_liabilities_lag,
                "net_income": net_income,
                "net_income_lag": net_income_lag,
                "ocf": ocf,
                "ocf_lag": ocf_lag,
                "revenue": revenue,
                "revenue_lag": get("revenue", 1),
                "cogs": cogs,
                "cogs_lag": get("cogs", 1),
                "tax": get("tax"),
                "interest": get("interest"),
                "debt_long": debt_long_input,
                "debt_long_lag": get("debt_long", 1),
                "shares": get("shares"),
                "shares_lag": get("shares", 1),
                "market_cap": market_cap,
                "sic": _number(
                    master.loc[symbol].get("sic_sec")
                    if "sic_sec" in master.columns
                    else master.loc[symbol].get("sic")
                ),
            }
        )

        cb_oper = None
        if None not in (revenue, cogs, sga, assets):
            cb_oper = _ratio(
                revenue
                - cogs
                - (sga - rd)
                - (receivables - receivables_lag)
                - (inventory - inventory_lag),
                assets,
            )
        _append(
            rows,
            symbol=symbol,
            signal="CBOperProf",
            value=cb_oper,
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            formula_id="openap_cboperprof_sec_partial_working_capital",
            dependencies=(("revenue", 0), ("cogs", 0), ("sga", 0), ("assets", 0)),
            available=available,
            periods=periods,
            caveat=(
                "Deferred revenue, accounts payable and accrued-expense "
                "components are incomplete"
            ),
        )

        tax = get("tax")
        deferred_tax = get("deferred_tax")
        taxable = (
            (tax - (deferred_tax or 0.0)) / 0.35
            if tax is not None
            else None
        )
        _append(
            rows,
            symbol=symbol,
            signal="Tax",
            value=_ratio(taxable, net_income),
            fidelity=FidelityClass.UNVALIDATED_PROXY,
            formula_id="openap_tax_total_less_deferred_sec_proxy",
            dependencies=(("tax", 0), ("net_income", 0)),
            available=available,
            periods=periods,
            caveat="SEC total tax replaces separate federal and foreign tax components",
        )

        pct_total_accrual_inputs = (
            net_income,
            get("repurchases"),
            get("share_issuance"),
            get("dividends"),
            ocf,
            get("financing_cash_flow"),
            get("investing_cash_flow"),
        )
        pct_total_accrual = None
        if all(value is not None for value in pct_total_accrual_inputs):
            (
                pct_net_income,
                repurchases,
                share_issuance,
                dividends,
                operating_cash_flow,
                financing_cash_flow,
                investing_cash_flow,
            ) = pct_total_accrual_inputs
            if abs(float(pct_net_income)) >= 1e-12:
                pct_total_accrual = (
                    float(pct_net_income)
                    - (
                        float(repurchases)
                        - float(share_issuance)
                        + float(dividends)
                        + float(operating_cash_flow)
                        + float(financing_cash_flow)
                        + float(investing_cash_flow)
                    )
                ) / abs(float(pct_net_income))
        _append(
            rows,
            symbol=symbol,
            signal="PctTotAcc",
            value=pct_total_accrual,
            fidelity=FidelityClass.RECONSTRUCTED,
            formula_id="openap_pcttotacc_sec_cashflow_components",
            dependencies=(
                ("net_income", 0),
                ("repurchases", 0),
                ("share_issuance", 0),
                ("dividends", 0),
                ("operating_cash_flow", 0),
                ("financing_cash_flow", 0),
                ("investing_cash_flow", 0),
            ),
            available=available,
            periods=periods,
            caveat=(
                "OpenAP formula reproduced with economically equivalent "
                "US-GAAP cash-flow tags; issuer-specific extensions fail closed"
            ),
        )

    cross_frame = pd.DataFrame(cross).set_index("symbol") if cross else pd.DataFrame()
    if not cross_frame.empty:
        numeric_columns = [
            column for column in cross_frame.columns if column != "industry"
        ]
        cross_frame[numeric_columns] = cross_frame[numeric_columns].apply(
            pd.to_numeric,
            errors="coerce",
        )
        accrual_q = _quantile(cross_frame["accrual"], 5)
        bm_q = _quantile(cross_frame["bm"], 5)
        accrual_bm = pd.Series(np.nan, index=cross_frame.index)
        accrual_bm.loc[bm_q.eq(5) & accrual_q.eq(1)] = 1.0
        accrual_bm.loc[bm_q.eq(1) & accrual_q.eq(5)] = 0.0

        industry_capex = cross_frame.groupby("industry")["capex_growth"].transform("mean")
        adjusted_capex = cross_frame["capex_growth"] - industry_capex

        def positive(value: pd.Series) -> pd.Series:
            return value.gt(0).astype(float)

        roa = cross_frame["net_income"] / cross_frame["assets"]
        roa_lag = cross_frame["net_income_lag"] / cross_frame["assets_lag"]
        cfo = cross_frame["ocf"] / cross_frame["assets"]
        leverage_change = (
            cross_frame["debt_long"] / cross_frame["assets"]
            - cross_frame["debt_long_lag"] / cross_frame["assets"]
        )
        current_ratio = cross_frame["current_assets"] / cross_frame["current_liabilities"]
        current_ratio_lag = (
            cross_frame["current_assets_lag"]
            / cross_frame["current_liabilities_lag"]
        )
        ebit = (
            cross_frame["net_income"]
            + cross_frame["tax"]
            + cross_frame["interest"]
        )
        margin = ebit / cross_frame["revenue"]
        margin_lag = ebit / cross_frame["revenue_lag"]
        turnover = cross_frame["revenue"] / cross_frame["assets"]
        turnover_lag = cross_frame["revenue_lag"] / cross_frame["assets_lag"]
        ps = (
            positive(roa)
            + positive(cfo)
            + positive(roa - roa_lag)
            + positive(cfo - roa)
            + positive(-leverage_change)
            + positive(current_ratio - current_ratio_lag)
            + positive(margin - margin_lag)
            + positive(turnover - turnover_lag)
            + cross_frame["shares"].le(cross_frame["shares_lag"]).astype(float)
        ).where(bm_q.eq(5))
        ps = ps.where(
            cross_frame[
                [
                    "net_income",
                    "ocf",
                    "assets",
                    "assets_lag",
                    "debt_long",
                    "current_assets",
                    "current_liabilities",
                    "tax",
                    "interest",
                    "revenue",
                    "shares",
                    "shares_lag",
                ]
            ].notna().all(axis=1)
        )

        gnp = float(gnp_deflator) if gnp_deflator and gnp_deflator > 0 else np.nan
        lag_income = cross_frame["net_income_lag"]
        oscore_raw = (
            -1.32
            - 0.407 * np.log(cross_frame["assets"] / gnp)
            + 6.03 * cross_frame["liabilities"] / cross_frame["assets"]
            - 1.43
            * (cross_frame["current_assets"] - cross_frame["current_liabilities"])
            / cross_frame["assets"]
            + 0.076
            * cross_frame["current_liabilities"]
            / cross_frame["current_assets"]
            - 1.72
            * cross_frame["liabilities"].gt(cross_frame["assets"]).astype(float)
            - 2.37 * cross_frame["net_income"] / cross_frame["assets"]
            - 1.83 * cross_frame["ocf"] / cross_frame["liabilities"]
            + 0.285 * (cross_frame["net_income"] + lag_income).lt(0).astype(float)
            - 0.521
            * (cross_frame["net_income"] - lag_income)
            / (cross_frame["net_income"].abs() + lag_income.abs())
        )
        oscore_raw = oscore_raw.where(
            ~(
                cross_frame["sic"].between(4000, 4999)
                | cross_frame["sic"].gt(5999)
            )
        )
        oscore_q = _quantile(oscore_raw, 10)
        oscore = pd.Series(np.nan, index=cross_frame.index)
        oscore.loc[oscore_q.eq(10)] = 1.0
        oscore.loc[oscore_q.between(1, 7)] = 0.0

        for symbol in cross_frame.index:
            for signal, value, fidelity, formula, deps, caveat in (
                (
                    "AccrualsBM",
                    accrual_bm.loc[symbol],
                    FidelityClass.UNVALIDATED_PROXY,
                    "openap_accrualsbm_sec_ocf_double_sort_proxy",
                    (
                        ("net_income", 0),
                        ("operating_cash_flow", 0),
                        ("assets", 1),
                        ("equity", 0),
                    ),
                    "Cash-flow accruals replace the official balance-sheet accrual construction",
                ),
                (
                    "BMdec",
                    cross_frame.loc[symbol, "bm"],
                    FidelityClass.UNVALIDATED_PROXY,
                    "openap_bm_current_market_cap_proxy",
                    (("equity", 0),),
                    "Current market cap replaces the required lagged December market equity",
                ),
                (
                    "ChInvIA",
                    adjusted_capex.loc[symbol],
                    FidelityClass.UNVALIDATED_PROXY,
                    "openap_chinvia_current_industry_proxy",
                    (("capex", 0), ("capex", 1)),
                    "Current Yahoo industry replaces historical two-digit SIC membership",
                ),
                (
                    "PS",
                    ps.loc[symbol],
                    FidelityClass.RECONSTRUCTED,
                    "openap_piotroski_nine_inputs_high_bm_sec",
                    (("assets", 0), ("net_income", 0), ("operating_cash_flow", 0), ("revenue", 0)),
                    "SEC taxonomies are normalized to the OpenAP Piotroski inputs",
                ),
                (
                    "OScore",
                    oscore.loc[symbol],
                    FidelityClass.RECONSTRUCTED,
                    "openap_ohlson_oscore_decile_sec_gnpdefl",
                    (
                        ("assets", 0),
                        ("liabilities", 0),
                        ("net_income", 0),
                        ("net_income", 1),
                    ),
                    (
                        "Operating cash flow is the documented OpenAP fallback "
                        "for funds from operations"
                    ),
                ),
            ):
                source_ids = ("sec_edgar",)
                if signal in {"AccrualsBM", "BMdec", "ChInvIA", "PS"}:
                    source_ids = ("sec_edgar", "yahoo_public")
                elif signal == "OScore":
                    source_ids = ("sec_edgar", "fred_public_csv")
                _append(
                    rows,
                    symbol=symbol,
                    signal=signal,
                    value=_number(value),
                    fidelity=fidelity,
                    formula_id=formula,
                    dependencies=deps,
                    available=available,
                    periods=periods,
                    source_ids=source_ids,
                    caveat=caveat,
                )

    return pd.DataFrame([row.to_record(formation) for row in rows])


def implemented_source_pairs() -> frozenset[tuple[str, str]]:
    source_map: dict[str, tuple[str, ...]] = {
        signal: ("sec_edgar",) for signal in ACCOUNTING_IMPLEMENTED_SIGNALS
    }
    for signal in ("AccrualsBM", "BMdec", "ChInvIA", "EntMult", "PS"):
        source_map[signal] = ("sec_edgar", "yahoo_public")
    source_map["OScore"] = ("sec_edgar", "fred_public_csv")
    return frozenset(
        (signal, source) for signal, sources in source_map.items() for source in sources
    )

"""As-filed SEC FSD reconstruction for the frozen Cash/GP/Investment batch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd


OPENAP_FORMULA_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"
SEC_ACCOUNTING_BATCH = ("Cash", "GP", "Investment")

FORMULA_METADATA = {
    "Cash": {
        "formula_id": "openap_cash_cheq_atq_sec_fsd",
        "path": "Signals/pyCode/Predictors/Cash.py",
        "sha256": "7e9f046dd3ebe3581b57ede655a9f1ba68340dcbf53167ed6fe0030e746ecab2",
    },
    "GP": {
        "formula_id": "openap_gp_revt_cogs_at_sec_fsd",
        "path": "Signals/pyCode/Predictors/GP.py",
        "sha256": "6a05de4a5b6ddb47a320e1d95d6392e625bfca3b50091e698be9fd866a6c8576",
    },
    "Investment": {
        "formula_id": "openap_investment_capx_revt_36m_sec_fsd",
        "path": "Signals/pyCode/Predictors/Investment.py",
        "sha256": "9b5b843157e7a57f67f6d8de610f165c27a69a5bf7cff8e671fef0e52a472e17",
    },
}


@dataclass(frozen=True)
class ConceptSpec:
    aliases: tuple[str, ...]
    statement: str


CONCEPT_SPECS = {
    "assets": ConceptSpec(("Assets",), "BS"),
    "cash_combined": ConceptSpec(("CashAndShortTermInvestments",), "BS"),
    "cash_base": ConceptSpec(
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        "BS",
    ),
    "short_investments": ConceptSpec(
        ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
        "BS",
    ),
    "revenue": ConceptSpec(
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        "IS",
    ),
    "cogs": ConceptSpec(
        ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
        "IS",
    ),
    "capex": ConceptSpec(("PaymentsToAcquirePropertyPlantAndEquipment",), "CF"),
}

_ALIAS_LOOKUP = {
    alias: (concept, priority, spec.statement)
    for concept, spec in CONCEPT_SPECS.items()
    for priority, alias in enumerate(spec.aliases)
}
_ALLOWED_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A"})
_ANNUAL_FORMS = frozenset({"10-K", "10-K/A"})
_IDENTITY_COLUMNS = frozenset(
    {
        "security_id",
        "cik",
        "valid_from",
        "valid_to",
        "is_primary",
        "security_type",
        "mapping_source",
    }
)
_OUTPUT_COLUMNS = [
    "security_id",
    "cik",
    "signal",
    "formation_at",
    "period_end",
    "available_at",
    "accession_number",
    "value",
    "observation_count",
    "reason_if_missing",
    "formula_id",
    "formula_commit",
    "formula_path",
    "formula_sha256",
    "source_id",
    "identity_source",
]


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _sec_date(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(8)
    return pd.to_datetime(text, format="%Y%m%d", errors="coerce")


def _sec_timestamp(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(14)
    return pd.to_datetime(text, format="%Y%m%d%H%M%S", errors="coerce")


def normalize_sec_fsd_tables(
    sub: pd.DataFrame,
    tag: pd.DataFrame,
    num: pd.DataFrame,
    pre: pd.DataFrame,
) -> pd.DataFrame:
    """Join official FSD tables while retaining accession-level causal provenance."""

    _require_columns(
        sub,
        {"adsh", "cik", "sic", "form", "period", "filed", "accepted"},
        "SUB",
    )
    _require_columns(tag, {"tag", "version", "custom", "abstract"}, "TAG")
    _require_columns(
        num,
        {"adsh", "tag", "version", "coreg", "ddate", "qtrs", "uom", "value"},
        "NUM",
    )
    _require_columns(pre, {"adsh", "line", "stmt", "tag", "version"}, "PRE")

    submissions = sub.copy()
    submissions["adsh"] = submissions["adsh"].astype(str).str.strip()
    submissions["cik"] = pd.to_numeric(submissions["cik"], errors="coerce")
    submissions["sic"] = pd.to_numeric(submissions["sic"], errors="coerce")
    submissions["report_period"] = _sec_date(submissions["period"])
    submissions["filed_at"] = _sec_date(submissions["filed"])
    submissions["accepted_at"] = _sec_timestamp(submissions["accepted"])
    submissions = submissions.loc[
        submissions["adsh"].ne("")
        & submissions["adsh"].notna()
        & submissions["cik"].notna()
        & submissions["form"].isin(_ALLOWED_FORMS)
        & submissions["report_period"].notna()
        & submissions["filed_at"].notna()
        & submissions["accepted_at"].notna()
        & submissions["accepted_at"].dt.normalize().ge(submissions["filed_at"])
        & submissions["accepted_at"].ge(submissions["report_period"])
    ].copy()
    submissions = submissions.drop_duplicates("adsh", keep="last")

    taxonomy = tag.copy()
    taxonomy["custom"] = pd.to_numeric(taxonomy["custom"], errors="coerce")
    taxonomy["abstract"] = pd.to_numeric(taxonomy["abstract"], errors="coerce")
    taxonomy = taxonomy.loc[
        taxonomy["tag"].isin(_ALIAS_LOOKUP)
        & taxonomy["custom"].eq(0)
        & taxonomy["abstract"].eq(0)
    ][["tag", "version"]].drop_duplicates()

    presentation = pre.copy()
    presentation["line"] = pd.to_numeric(presentation["line"], errors="coerce")
    presentation = (
        presentation.loc[presentation["tag"].isin(_ALIAS_LOOKUP)]
        .sort_values(["adsh", "tag", "version", "line"])
        .drop_duplicates(["adsh", "tag", "version"], keep="first")
        [["adsh", "tag", "version", "stmt", "line"]]
    )

    facts = num.copy()
    facts["adsh"] = facts["adsh"].astype(str).str.strip()
    facts["coreg"] = facts["coreg"].fillna("").astype(str).str.strip()
    facts["qtrs"] = pd.to_numeric(facts["qtrs"], errors="coerce")
    facts["value"] = pd.to_numeric(facts["value"], errors="coerce")
    facts["period_end"] = _sec_date(facts["ddate"])
    facts = facts.loc[
        facts["tag"].isin(_ALIAS_LOOKUP)
        & facts["coreg"].eq("")
        & facts["uom"].eq("USD")
        & facts["value"].notna()
        & facts["period_end"].notna()
    ].copy()
    facts = facts.merge(taxonomy, on=["tag", "version"], how="inner")
    facts = facts.merge(
        presentation,
        on=["adsh", "tag", "version"],
        how="inner",
        validate="many_to_one",
    )
    facts = facts.merge(
        submissions[
            [
                "adsh",
                "cik",
                "sic",
                "form",
                "report_period",
                "filed_at",
                "accepted_at",
            ]
        ],
        on="adsh",
        how="inner",
        validate="many_to_one",
    )
    facts["concept"] = facts["tag"].map(lambda value: _ALIAS_LOOKUP[str(value)][0])
    facts["alias_priority"] = facts["tag"].map(
        lambda value: _ALIAS_LOOKUP[str(value)][1]
    )
    facts["required_stmt"] = facts["tag"].map(
        lambda value: _ALIAS_LOOKUP[str(value)][2]
    )
    facts = facts.loc[
        facts["stmt"].eq(facts["required_stmt"])
        & facts["period_end"].le(facts["report_period"])
    ].copy()

    group = ["adsh", "concept", "period_end", "qtrs"]
    best_priority = facts.groupby(group)["alias_priority"].transform("min")
    facts = facts.loc[facts["alias_priority"].eq(best_priority)].copy()
    distinct_values = facts.groupby(group)["value"].transform("nunique")
    facts["fact_ambiguous"] = distinct_values.gt(1)
    facts = facts.sort_values(group + ["line", "tag"]).drop_duplicates(group, keep="first")
    return facts[
        [
            "adsh",
            "cik",
            "sic",
            "form",
            "report_period",
            "filed_at",
            "accepted_at",
            "tag",
            "version",
            "concept",
            "alias_priority",
            "period_end",
            "qtrs",
            "uom",
            "value",
            "stmt",
            "line",
            "fact_ambiguous",
        ]
    ].sort_values(["cik", "accepted_at", "adsh", "concept"]).reset_index(drop=True)


def _active_identities(identity: pd.DataFrame, formation_at: pd.Timestamp) -> pd.DataFrame:
    _require_columns(identity, _IDENTITY_COLUMNS, "identity")
    frame = identity.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["valid_from"] = pd.to_datetime(frame["valid_from"], errors="coerce")
    frame["valid_to"] = pd.to_datetime(frame["valid_to"], errors="coerce")
    frame = frame.loc[
        frame["cik"].notna()
        & frame["security_id"].fillna("").astype(str).str.strip().ne("")
        & frame["valid_from"].le(formation_at)
        & (frame["valid_to"].isna() | frame["valid_to"].ge(formation_at))
        & frame["is_primary"].eq(True)
        & frame["security_type"].eq("common_stock")
    ].copy()
    duplicate_ciks = frame.loc[frame["cik"].duplicated(keep=False), "cik"].unique()
    return frame.loc[~frame["cik"].isin(duplicate_ciks)].drop_duplicates("security_id")


def _pick_concept(
    filing: pd.DataFrame,
    concept: str,
    *,
    qtrs: int,
) -> pd.Series | None:
    rows = filing.loc[
        filing["concept"].eq(concept)
        & filing["qtrs"].eq(qtrs)
        & filing["period_end"].eq(filing["report_period"])
        & ~filing["fact_ambiguous"]
    ]
    if rows.empty:
        return None
    return rows.sort_values(["alias_priority", "line", "tag"]).iloc[0]


def _filings_as_of(
    facts: pd.DataFrame,
    cik: int,
    formation_at: pd.Timestamp,
    *,
    forms: frozenset[str],
) -> list[pd.DataFrame]:
    eligible = facts.loc[
        facts["cik"].eq(cik)
        & facts["accepted_at"].le(formation_at)
        & facts["form"].isin(forms)
    ].copy()
    filings = [part for _, part in eligible.groupby("adsh", sort=False)]
    return sorted(
        filings,
        key=lambda part: (part["accepted_at"].iloc[0], part["adsh"].iloc[0]),
        reverse=True,
    )


def _cash_value(
    facts: pd.DataFrame,
    cik: int,
    formation_at: pd.Timestamp,
) -> dict[str, Any]:
    for filing in _filings_as_of(
        facts,
        cik,
        formation_at,
        forms=_ALLOWED_FORMS,
    ):
        accepted = pd.Timestamp(filing["accepted_at"].iloc[0])
        month_age = (
            formation_at.to_period("M") - accepted.to_period("M")
        ).n
        if month_age < 0 or month_age > 2:
            continue
        assets = _pick_concept(filing, "assets", qtrs=0)
        combined = _pick_concept(filing, "cash_combined", qtrs=0)
        cash = _pick_concept(filing, "cash_base", qtrs=0)
        short = _pick_concept(filing, "short_investments", qtrs=0)
        if assets is None or (combined is None and (cash is None or short is None)):
            continue
        denominator = float(assets["value"])
        if denominator <= 0:
            return _value_result(filing, None, 0, "nonpositive_assets")
        numerator = (
            float(combined["value"])
            if combined is not None
            else float(cash["value"]) + float(short["value"])
        )
        return _value_result(filing, numerator / denominator, 3, "")
    return _missing_result("missing_complete_quarterly_filing")


def _gp_value(
    facts: pd.DataFrame,
    cik: int,
    formation_at: pd.Timestamp,
) -> dict[str, Any]:
    for filing in _filings_as_of(facts, cik, formation_at, forms=_ANNUAL_FORMS):
        revenue = _pick_concept(filing, "revenue", qtrs=4)
        cogs = _pick_concept(filing, "cogs", qtrs=4)
        assets = _pick_concept(filing, "assets", qtrs=0)
        if revenue is None or cogs is None or assets is None:
            continue
        sic = pd.to_numeric(filing["sic"], errors="coerce").iloc[0]
        if pd.notna(sic) and 6000 <= float(sic) < 7000:
            return _value_result(filing, None, 3, "financial_sic_excluded")
        denominator = float(assets["value"])
        if denominator <= 0:
            return _value_result(filing, None, 3, "nonpositive_assets")
        value = (float(revenue["value"]) - float(cogs["value"])) / denominator
        return _value_result(filing, value, 3, "")
    return _missing_result("missing_complete_annual_filing")


def _annual_investment_ratios(
    facts: pd.DataFrame,
    cik: int,
    formation_at: pd.Timestamp,
) -> pd.DataFrame:
    rows = []
    for filing in _filings_as_of(facts, cik, formation_at, forms=_ANNUAL_FORMS):
        capex = _pick_concept(filing, "capex", qtrs=4)
        revenue = _pick_concept(filing, "revenue", qtrs=4)
        if capex is None or revenue is None or float(revenue["value"]) <= 0:
            continue
        rows.append(
            {
                "adsh": filing["adsh"].iloc[0],
                "accepted_at": filing["accepted_at"].iloc[0],
                "period_end": filing["report_period"].iloc[0],
                "revenue": float(revenue["value"]),
                "ratio": float(capex["value"]) / float(revenue["value"]),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["adsh", "accepted_at", "period_end", "revenue", "ratio"])
    return (
        pd.DataFrame(rows)
        .sort_values(["period_end", "accepted_at"])
        .drop_duplicates("period_end", keep="last")
    )


def _investment_value(
    facts: pd.DataFrame,
    cik: int,
    formation_at: pd.Timestamp,
) -> dict[str, Any]:
    last_month = formation_at + pd.offsets.MonthEnd(0)
    month_ends = [last_month - pd.offsets.MonthEnd(offset) for offset in range(35, -1, -1)]
    ratios = []
    current = pd.DataFrame()
    for month_end in month_ends:
        as_of = _annual_investment_ratios(facts, cik, month_end)
        if as_of.empty:
            continue
        current = as_of.sort_values(["accepted_at", "period_end"]).tail(1)
        ratios.append(float(current.iloc[0]["ratio"]))
    if current.empty:
        return _missing_result("missing_complete_annual_filing")
    row = current.iloc[0]
    filing = facts.loc[facts["adsh"].eq(row["adsh"])]
    if float(row["revenue"]) < 10_000_000.0:
        return _value_result(filing, None, len(ratios), "revenue_below_10m_usd")
    if len(ratios) < 24:
        return _value_result(filing, None, len(ratios), "fewer_than_24_monthly_observations")
    rolling = float(np.mean(ratios[-36:]))
    if not np.isfinite(rolling) or rolling == 0:
        return _value_result(filing, None, len(ratios), "invalid_36_month_mean")
    return _value_result(filing, float(row["ratio"]) / rolling, len(ratios), "")


def _missing_result(reason: str) -> dict[str, Any]:
    return {
        "period_end": pd.NaT,
        "available_at": pd.NaT,
        "accession_number": "",
        "value": np.nan,
        "observation_count": 0,
        "reason_if_missing": reason,
    }


def _value_result(
    filing: pd.DataFrame,
    value: float | None,
    observation_count: int,
    reason: str,
) -> dict[str, Any]:
    number = float(value) if value is not None and np.isfinite(value) else np.nan
    return {
        "period_end": pd.Timestamp(filing["report_period"].iloc[0]),
        "available_at": pd.Timestamp(filing["accepted_at"].iloc[0]),
        "accession_number": str(filing["adsh"].iloc[0]),
        "value": number,
        "observation_count": int(observation_count),
        "reason_if_missing": "" if np.isfinite(number) else reason,
    }


def calculate_sec_accounting_batch(
    normalized_facts: pd.DataFrame,
    identity: pd.DataFrame,
    formation_months: Iterable[pd.Timestamp | str],
) -> pd.DataFrame:
    """Calculate the frozen batch causally at each supplied formation timestamp."""

    rows = []
    for raw_formation in sorted(pd.Timestamp(value) for value in formation_months):
        formation = raw_formation.tz_localize(None) if raw_formation.tzinfo else raw_formation
        active = _active_identities(identity, formation)
        for identity_row in active.sort_values("security_id").itertuples(index=False):
            cik = int(identity_row.cik)
            values = {
                "Cash": _cash_value(normalized_facts, cik, formation),
                "GP": _gp_value(normalized_facts, cik, formation),
                "Investment": _investment_value(normalized_facts, cik, formation),
            }
            for signal in SEC_ACCOUNTING_BATCH:
                metadata = FORMULA_METADATA[signal]
                rows.append(
                    {
                        "security_id": str(identity_row.security_id),
                        "cik": cik,
                        "signal": signal,
                        "formation_at": formation,
                        **values[signal],
                        "formula_id": metadata["formula_id"],
                        "formula_commit": OPENAP_FORMULA_COMMIT,
                        "formula_path": metadata["path"],
                        "formula_sha256": metadata["sha256"],
                        "source_id": "sec_financial_statement_datasets",
                        "identity_source": str(identity_row.mapping_source),
                    }
                )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)


def build_sec_accounting_batch_evidence(
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Emit implemented gates while leaving every empirical gate closed."""

    return pd.DataFrame(
        [
            {
                "signal": signal,
                "formula_implemented": True,
                "data_pipeline_implemented": True,
                "point_in_time_verified": False,
                "identity_verified": False,
                "coverage_measured": False,
                "fidelity_measured": False,
                "coverage_result": "not_measured",
                "fidelity_result": "not_measured",
                "strict_gate_result": "blocked",
                "blocking_reason": (
                    "point_in_time_identity_coverage_fidelity_not_measured"
                ),
                "evidence_run_url": evidence_run_url,
                "evidence_artifact": evidence_artifact,
                "implementation_commit": implementation_commit,
            }
            for signal in SEC_ACCOUNTING_BATCH
        ]
    )


__all__ = [
    "FORMULA_METADATA",
    "OPENAP_FORMULA_COMMIT",
    "SEC_ACCOUNTING_BATCH",
    "build_sec_accounting_batch_evidence",
    "calculate_sec_accounting_batch",
    "normalize_sec_fsd_tables",
]

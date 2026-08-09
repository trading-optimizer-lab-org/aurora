"""As-filed SEC FSD reconstruction for the frozen Cash/GP/Investment batch."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class SecAccountingValidationThresholds:
    minimum_paired_rows: int = 60
    minimum_paired_months: int = 12
    minimum_cross_sectional_coverage: float = 0.80
    minimum_spearman: float = 0.95
    minimum_sign_agreement: float = 0.95
    minimum_extreme_decile_agreement: float = 0.80


FROZEN_VALIDATION_THRESHOLDS = SecAccountingValidationThresholds()


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
_MEASUREMENT_SECURITY_TYPES = frozenset(
    {"common_stock", "issuer_internal_unverified"}
)
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
        & frame["security_type"].isin(_MEASUREMENT_SECURITY_TYPES)
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


def write_sec_accounting_batch_outputs(
    sub: pd.DataFrame,
    tag: pd.DataFrame,
    num: pd.DataFrame,
    pre: pd.DataFrame,
    identity: pd.DataFrame,
    formation_months: Iterable[pd.Timestamp | str],
    output_dir: Path | str,
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, int]:
    """Persist deterministic batch inputs, observations, evidence, and counts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    normalized = normalize_sec_fsd_tables(sub, tag, num, pre)
    observations = calculate_sec_accounting_batch(
        normalized,
        identity,
        formation_months,
    )
    evidence = build_sec_accounting_batch_evidence(
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    summary = {
        "normalized_facts": int(len(normalized)),
        "observations": int(len(observations)),
        "finite_values": int(observations["value"].notna().sum()),
        "signals": int(evidence["signal"].nunique()),
        "strict_approved": int(evidence["strict_gate_result"].eq("approved").sum()),
    }
    normalized.to_csv(output / "sec_accounting_batch_normalized_facts.csv", index=False)
    observations.to_csv(output / "sec_accounting_batch_observations.csv", index=False)
    evidence.to_csv(output / "sec_accounting_batch_evidence.csv", index=False)
    (output / "sec_accounting_batch_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _month_end(values: pd.Series) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    return dates + pd.offsets.MonthEnd(0)


def _jaccard(left: set[object], right: set[object]) -> float:
    union = left | right
    return float(len(left & right) / len(union)) if union else np.nan


def _extreme_decile_agreement(pair: pd.DataFrame) -> float:
    monthly = []
    for _, group in pair.groupby("formation_at", sort=True):
        if len(group) < 2:
            continue
        count = max(1, int(np.ceil(len(group) * 0.10)))
        observed = group["value"].sort_values()
        reference = group["reference_value"].sort_values()
        low = _jaccard(set(observed.index[:count]), set(reference.index[:count]))
        high = _jaccard(set(observed.index[-count:]), set(reference.index[-count:]))
        monthly.append(float(np.nanmean([low, high])))
    return float(np.mean(monthly)) if monthly else np.nan


def _coverage_breakdown(
    expected: pd.DataFrame,
    found_keys: set[tuple[str, pd.Timestamp]],
    column: str,
) -> str:
    if column not in expected.columns:
        return "{}"
    records: dict[str, dict[str, float | int]] = {}
    for value, group in expected.groupby(column, dropna=False):
        keys = set(zip(group["security_id"], group["formation_at"], strict=False))
        found = len(keys & found_keys)
        records[str(value)] = {
            "expected": len(keys),
            "found": found,
            "coverage": found / len(keys) if keys else 0.0,
        }
    return json.dumps(records, sort_keys=True)


def _coverage_metrics(
    observations: pd.DataFrame,
    expected_universe: pd.DataFrame,
    thresholds: SecAccountingValidationThresholds,
) -> pd.DataFrame:
    _require_columns(
        expected_universe,
        {"security_id", "formation_at"},
        "expected universe",
    )
    expected = expected_universe.copy()
    expected["security_id"] = expected["security_id"].astype(str).str.strip()
    expected["formation_at"] = _month_end(expected["formation_at"])
    expected = expected.dropna(subset=["security_id", "formation_at"]).drop_duplicates(
        ["security_id", "formation_at"]
    )
    expected_keys = set(zip(expected["security_id"], expected["formation_at"], strict=False))
    rows = []
    for signal in SEC_ACCOUNTING_BATCH:
        found = observations.loc[
            observations["signal"].eq(signal) & observations["value"].notna(),
            ["security_id", "formation_at"],
        ].drop_duplicates()
        found_keys = set(zip(found["security_id"], found["formation_at"], strict=False))
        matched = expected_keys & found_keys
        matched_frame = pd.DataFrame(list(matched), columns=["security_id", "formation_at"])
        expected_companies = int(expected["security_id"].nunique())
        found_companies = int(matched_frame["security_id"].nunique()) if matched else 0
        expected_months = int(expected["formation_at"].nunique())
        valid_months = int(matched_frame["formation_at"].nunique()) if matched else 0
        ratio = len(matched) / len(expected_keys) if expected_keys else 0.0
        delisted_expected = (
            int(expected["delisted"].fillna(False).map(bool).sum())
            if "delisted" in expected
            else 0
        )
        delisted_found = 0
        if "delisted" in expected and matched:
            delisted_found = int(
                expected.loc[
                    expected.apply(
                        lambda row, matched_keys=matched: (
                            row["security_id"],
                            row["formation_at"],
                        )
                        in matched_keys,
                        axis=1,
                    ),
                    "delisted",
                ]
                .fillna(False)
                .map(bool)
                .sum()
            )
        rows.append(
            {
                "signal": signal,
                "expected_rows": int(len(expected_keys)),
                "found_rows": int(len(matched)),
                "coverage_ratio": float(ratio),
                "expected_companies": expected_companies,
                "found_companies": found_companies,
                "expected_months": expected_months,
                "valid_months": valid_months,
                "first_expected_period": expected["formation_at"].min(),
                "last_expected_period": expected["formation_at"].max(),
                "first_valid_period": (
                    matched_frame["formation_at"].min() if matched else pd.NaT
                ),
                "last_valid_period": (
                    matched_frame["formation_at"].max() if matched else pd.NaT
                ),
                "expected_delisted_rows": delisted_expected,
                "found_delisted_rows": delisted_found,
                "coverage_by_exchange": _coverage_breakdown(
                    expected, matched, "exchange"
                ),
                "coverage_by_security_type": _coverage_breakdown(
                    expected, matched, "security_type"
                ),
                "minimum_cross_sectional_coverage": (
                    thresholds.minimum_cross_sectional_coverage
                ),
                "coverage_pass": bool(
                    expected_keys
                    and ratio >= thresholds.minimum_cross_sectional_coverage
                ),
            }
        )
    return pd.DataFrame(rows)


def _empty_fidelity_row(
    signal: str,
    thresholds: SecAccountingValidationThresholds,
    status: str,
) -> dict[str, Any]:
    return {
        "signal": signal,
        "measurement_status": status,
        "paired_rows": 0,
        "paired_months": 0,
        "paired_companies": 0,
        "pearson": np.nan,
        "spearman": np.nan,
        "sign_agreement": np.nan,
        "extreme_decile_agreement": np.nan,
        "mean_absolute_error": np.nan,
        "mean_relative_error": np.nan,
        "monthly_spearman_std": np.nan,
        "minimum_paired_rows": thresholds.minimum_paired_rows,
        "minimum_paired_months": thresholds.minimum_paired_months,
        "minimum_spearman": thresholds.minimum_spearman,
        "minimum_sign_agreement": thresholds.minimum_sign_agreement,
        "minimum_extreme_decile_agreement": (
            thresholds.minimum_extreme_decile_agreement
        ),
        "fidelity_pass": False,
    }


def _fidelity_metrics(
    observations: pd.DataFrame,
    reference: pd.DataFrame,
    thresholds: SecAccountingValidationThresholds,
    *,
    identity_verified: bool,
) -> pd.DataFrame:
    if not identity_verified:
        return pd.DataFrame(
            [
                _empty_fidelity_row(
                    signal,
                    thresholds,
                    "blocked_identity_not_verified",
                )
                for signal in SEC_ACCOUNTING_BATCH
            ]
        )
    _require_columns(
        reference,
        {"security_id", "formation_at", "signal", "reference_value"},
        "OpenAP reference",
    )
    official = reference.copy()
    official["security_id"] = official["security_id"].astype(str).str.strip()
    official["formation_at"] = _month_end(official["formation_at"])
    official["reference_value"] = pd.to_numeric(
        official["reference_value"], errors="coerce"
    )
    official = official.dropna(
        subset=["security_id", "formation_at", "signal", "reference_value"]
    ).drop_duplicates(["security_id", "formation_at", "signal"])
    rows = []
    for signal in SEC_ACCOUNTING_BATCH:
        measured = observations.loc[
            observations["signal"].eq(signal),
            ["security_id", "formation_at", "value"],
        ]
        target = official.loc[
            official["signal"].eq(signal),
            ["security_id", "formation_at", "reference_value"],
        ]
        pair = measured.merge(
            target,
            on=["security_id", "formation_at"],
            how="inner",
            validate="one_to_one",
        ).dropna(subset=["value", "reference_value"])
        if pair.empty:
            rows.append(
                _empty_fidelity_row(signal, thresholds, "no_aligned_reference_rows")
            )
            continue
        pearson = pair["value"].corr(pair["reference_value"], method="pearson")
        spearman = pair["value"].corr(pair["reference_value"], method="spearman")
        signs = pair.loc[pair["value"].ne(0) & pair["reference_value"].ne(0)]
        sign_agreement = (
            float((np.sign(signs["value"]) == np.sign(signs["reference_value"])).mean())
            if not signs.empty
            else np.nan
        )
        extreme = _extreme_decile_agreement(pair)
        absolute_error = (pair["value"] - pair["reference_value"]).abs()
        relative = absolute_error.loc[pair["reference_value"].ne(0)] / pair.loc[
            pair["reference_value"].ne(0), "reference_value"
        ].abs()
        monthly_spearman = pd.Series(
            [
                group["value"].corr(group["reference_value"], method="spearman")
                for _, group in pair.groupby("formation_at", sort=True)
            ],
            dtype=float,
        )
        paired_months = int(pair["formation_at"].nunique())
        passed = bool(
            len(pair) >= thresholds.minimum_paired_rows
            and paired_months >= thresholds.minimum_paired_months
            and pd.notna(spearman)
            and float(spearman) >= thresholds.minimum_spearman
            and pd.notna(sign_agreement)
            and sign_agreement >= thresholds.minimum_sign_agreement
            and pd.notna(extreme)
            and extreme >= thresholds.minimum_extreme_decile_agreement
        )
        rows.append(
            {
                "signal": signal,
                "measurement_status": "measured",
                "paired_rows": int(len(pair)),
                "paired_months": paired_months,
                "paired_companies": int(pair["security_id"].nunique()),
                "pearson": float(pearson) if pd.notna(pearson) else np.nan,
                "spearman": float(spearman) if pd.notna(spearman) else np.nan,
                "sign_agreement": sign_agreement,
                "extreme_decile_agreement": extreme,
                "mean_absolute_error": float(absolute_error.mean()),
                "mean_relative_error": (
                    float(relative.mean()) if not relative.empty else np.nan
                ),
                "monthly_spearman_std": float(monthly_spearman.std(ddof=0)),
                "minimum_paired_rows": thresholds.minimum_paired_rows,
                "minimum_paired_months": thresholds.minimum_paired_months,
                "minimum_spearman": thresholds.minimum_spearman,
                "minimum_sign_agreement": thresholds.minimum_sign_agreement,
                "minimum_extreme_decile_agreement": (
                    thresholds.minimum_extreme_decile_agreement
                ),
                "fidelity_pass": passed,
            }
        )
    return pd.DataFrame(rows)


def evaluate_sec_accounting_validation(
    observations: pd.DataFrame,
    reference: pd.DataFrame,
    expected_universe: pd.DataFrame,
    *,
    point_in_time_verified: bool,
    identity_verified: bool,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
    thresholds: SecAccountingValidationThresholds = FROZEN_VALIDATION_THRESHOLDS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Measure the frozen gates without using results to alter mappings or thresholds."""

    _require_columns(
        observations,
        {"security_id", "formation_at", "signal", "value"},
        "SEC observations",
    )
    measured = observations.copy()
    measured["security_id"] = measured["security_id"].astype(str).str.strip()
    measured["formation_at"] = _month_end(measured["formation_at"])
    measured["value"] = pd.to_numeric(measured["value"], errors="coerce")
    measured = measured.loc[measured["signal"].isin(SEC_ACCOUNTING_BATCH)].drop_duplicates(
        ["security_id", "formation_at", "signal"]
    )
    coverage = _coverage_metrics(measured, expected_universe, thresholds)
    fidelity = _fidelity_metrics(
        measured,
        reference,
        thresholds,
        identity_verified=identity_verified,
    )
    coverage_index = coverage.set_index("signal")
    fidelity_index = fidelity.set_index("signal")
    rows = []
    for signal in SEC_ACCOUNTING_BATCH:
        coverage_pass = bool(coverage_index.loc[signal, "coverage_pass"])
        fidelity_measured = bool(
            identity_verified
            and fidelity_index.loc[signal, "measurement_status"] == "measured"
        )
        fidelity_pass = bool(fidelity_index.loc[signal, "fidelity_pass"])
        approved = bool(
            point_in_time_verified
            and identity_verified
            and coverage_pass
            and fidelity_measured
            and fidelity_pass
        )
        if not point_in_time_verified:
            blocker = "point_in_time_not_verified"
        elif not identity_verified:
            blocker = "identity_not_verified"
        elif not coverage_pass:
            blocker = "coverage_below_frozen_threshold"
        elif not fidelity_measured:
            blocker = "fidelity_not_measured"
        elif not fidelity_pass:
            blocker = "fidelity_below_frozen_threshold"
        else:
            blocker = "none"
        rows.append(
            {
                "signal": signal,
                "formula_implemented": True,
                "data_pipeline_implemented": True,
                "point_in_time_verified": bool(point_in_time_verified),
                "identity_verified": bool(identity_verified),
                "coverage_measured": True,
                "fidelity_measured": fidelity_measured,
                "coverage_result": "pass" if coverage_pass else "fail",
                "fidelity_result": (
                    "pass"
                    if fidelity_pass
                    else "fail"
                    if fidelity_measured
                    else "not_measured"
                ),
                "strict_gate_result": "approved" if approved else "blocked",
                "blocking_reason": blocker,
                "evidence_run_url": evidence_run_url,
                "evidence_artifact": evidence_artifact,
                "implementation_commit": implementation_commit,
            }
        )
    return pd.DataFrame(rows), coverage, fidelity


_SOURCE_MANIFEST_COLUMNS = [
    "source_id",
    "source_url",
    "period",
    "sha256",
    "size_bytes",
    "retrieved_at",
    "status",
    "failure_reason",
]


def _validate_sec_source_manifest(source_manifest: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        source_manifest,
        set(_SOURCE_MANIFEST_COLUMNS),
        "SEC source manifest",
    )
    clean = source_manifest[_SOURCE_MANIFEST_COLUMNS].copy()
    for column in (
        "source_id",
        "source_url",
        "period",
        "sha256",
        "retrieved_at",
        "status",
        "failure_reason",
    ):
        clean[column] = clean[column].fillna("").astype(str).str.strip()
    if clean.empty:
        raise ValueError("SEC source manifest cannot be empty")
    if clean["source_id"].eq("").any() or clean["source_id"].duplicated().any():
        raise ValueError("SEC source manifest requires unique non-empty source IDs")
    if not clean["source_url"].str.startswith("https://").all():
        raise ValueError("SEC source manifest requires HTTPS source URLs")
    if clean["period"].eq("").any() or clean["retrieved_at"].eq("").any():
        raise ValueError("SEC source manifest requires periods and retrieval timestamps")
    if not set(clean["status"]).issubset({"downloaded", "failed"}):
        raise ValueError("SEC source manifest has an unsupported status")
    clean["size_bytes"] = pd.to_numeric(clean["size_bytes"], errors="coerce")
    downloaded = clean["status"].eq("downloaded")
    valid_hashes = clean["sha256"].str.fullmatch(r"[0-9a-fA-F]{64}")
    valid_sizes = clean["size_bytes"].notna() & clean["size_bytes"].gt(0)
    if not (valid_hashes.loc[downloaded] & valid_sizes.loc[downloaded]).all():
        raise ValueError("Downloaded SEC sources require SHA-256 and positive size")
    if clean.loc[~downloaded, "failure_reason"].eq("").any():
        raise ValueError("Failed SEC sources require a concrete failure reason")
    clean["size_bytes"] = clean["size_bytes"].fillna(0).astype("int64")
    return clean.sort_values(["period", "source_id"], kind="stable").reset_index(
        drop=True
    )


def write_sec_accounting_validation_outputs(
    observations: pd.DataFrame,
    reference: pd.DataFrame,
    expected_universe: pd.DataFrame,
    source_manifest: pd.DataFrame,
    output_dir: Path | str,
    *,
    point_in_time_verified: bool,
    identity_verified: bool,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
    thresholds: SecAccountingValidationThresholds = FROZEN_VALIDATION_THRESHOLDS,
) -> dict[str, int]:
    """Persist frozen validation metrics and auditable source provenance."""

    clean_sources = _validate_sec_source_manifest(source_manifest)
    evidence, coverage, fidelity = evaluate_sec_accounting_validation(
        observations,
        reference,
        expected_universe,
        point_in_time_verified=point_in_time_verified,
        identity_verified=identity_verified,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
        thresholds=thresholds,
    )
    summary = {
        "coverage_passed": int(coverage["coverage_pass"].map(bool).sum()),
        "fidelity_measured": int(evidence["fidelity_measured"].map(bool).sum()),
        "fidelity_passed": int(fidelity["fidelity_pass"].map(bool).sum()),
        "signals": int(evidence["signal"].nunique()),
        "strict_approved": int(evidence["strict_gate_result"].eq("approved").sum()),
    }
    threshold_record = {
        "formula_commit": OPENAP_FORMULA_COMMIT,
        **asdict(thresholds),
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "sec_accounting_batch_coverage.csv", index=False)
    fidelity.to_csv(output / "sec_accounting_batch_fidelity.csv", index=False)
    evidence.to_csv(output / "sec_accounting_batch_evidence.csv", index=False)
    clean_sources.to_csv(
        output / "sec_accounting_batch_source_manifest.csv",
        index=False,
    )
    (output / "sec_accounting_batch_thresholds.json").write_text(
        json.dumps(threshold_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "sec_accounting_batch_validation_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


__all__ = [
    "FORMULA_METADATA",
    "FROZEN_VALIDATION_THRESHOLDS",
    "OPENAP_FORMULA_COMMIT",
    "SEC_ACCOUNTING_BATCH",
    "build_sec_accounting_batch_evidence",
    "calculate_sec_accounting_batch",
    "evaluate_sec_accounting_validation",
    "normalize_sec_fsd_tables",
    "write_sec_accounting_batch_outputs",
    "write_sec_accounting_validation_outputs",
]

"""Current Cash, GP and Investment reconstructions from SEC CompanyFacts.

The formulas are the pinned OpenAP formulas already frozen in
``sec_accounting_batch``.  This adapter changes only the free SEC surface:
audited CompanyFacts shards replace the Financial Statement Data Set tables.
Every accepted fact remains bounded by its SEC availability timestamp.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..openap_current_score import (
    ACCOUNTING_FEATURE_DEPENDENCIES,
    SEC_CONCEPT_ALIASES,
    apply_accounting_input_freshness,
    calculate_accounting_features,
    latest_sec_concept_inputs,
    sec_concepts_from_inputs,
)
from .sec_accounting_batch import (
    CONCEPT_SPECS,
    FORMULA_METADATA,
    SEC_ACCOUNTING_BATCH,
    calculate_sec_accounting_batch,
)


_FACT_COLUMNS = {
    "cik",
    "tag",
    "unit",
    "value",
    "period_start",
    "period_end",
    "form",
    "filed",
    "accession_number",
    "available_at",
}
_SUBMISSION_COLUMNS = {"cik", "accession_number", "accepted_at", "sic"}
_STATUS_COLUMNS = {"cik", "symbol", "surface", "status"}
_ALIAS_LOOKUP = {
    alias: (concept, priority)
    for concept, spec in CONCEPT_SPECS.items()
    for priority, alias in enumerate(spec.aliases)
}
_RDABILITY_ALIAS_LOOKUP = {
    alias: (concept, priority)
    for concept in ("revenue", "rd")
    for priority, alias in enumerate(SEC_CONCEPT_ALIASES[concept])
}
_REALESTATE_ALIAS_LOOKUP = {
    "Assets": ("assets", 0),
    "BuildingsAndImprovementsGross": ("buildings_gross", 0),
    "BuildingsAndImprovementsNet": ("buildings_net", 0),
    "LandAndLandImprovements": ("land", 0),
    "PropertyPlantAndEquipmentGross": ("ppe_gross", 0),
    "PropertyPlantAndEquipmentNet": ("ppe_net", 0),
    (
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfter"
        "AccumulatedDepreciationAndAmortization"
    ): ("ppe_net", 1),
}
_TAX_ALIAS_LOOKUP = {
    "IncomeLossFromContinuingOperations": ("income", 0),
    "NetIncomeLoss": ("income", 1),
    "ProfitLoss": ("income", 2),
    "CurrentFederalTaxExpenseBenefit": ("federal_tax", 0),
    "CurrentForeignTaxExpenseBenefit": ("foreign_tax", 0),
    "IncomeTaxExpenseBenefit": ("total_tax", 0),
    "DeferredIncomeTaxExpenseBenefit": ("deferred_tax", 0),
}
_ROAQ_ALIAS_LOOKUP = {
    "Assets": ("assets", 0),
    "IncomeLossFromContinuingOperations": ("income", 0),
    "NetIncomeLoss": ("income", 1),
    "ProfitLoss": ("income", 2),
}
_BACKLOG_ALIAS_LOOKUP = {
    "Assets": ("assets", 0),
    "OrderBacklog": ("backlog", 0),
}
_OUTPUT_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "signal",
    "formation_at",
    "period_end",
    "filed_at",
    "available_at",
    "retrieved_at",
    "value",
    "fidelity_class",
    "current_usable",
    "source_id",
    "source_url",
    "formula_id",
    "formula_sha256",
    "observation_count",
    "reason_if_missing",
    "caveat",
)


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _utc(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True)


def normalize_companyfacts_for_accounting(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize audited CompanyFacts into the frozen accounting calculator."""

    _require_columns(companyfacts, _FACT_COLUMNS, "SEC CompanyFacts")
    _require_columns(submissions, _SUBMISSION_COLUMNS, "SEC submissions")
    facts = companyfacts.copy()
    facts["cik"] = pd.to_numeric(facts["cik"], errors="coerce")
    facts["value"] = pd.to_numeric(facts["value"], errors="coerce")
    facts["period_start"] = _utc(facts["period_start"]).dt.tz_localize(None)
    facts["period_end"] = _utc(facts["period_end"]).dt.tz_localize(None)
    facts["filed_at"] = _utc(facts["filed"])
    facts["fact_available_at"] = _utc(facts["available_at"])
    facts["adsh"] = facts["accession_number"].fillna("").astype(str).str.strip()
    facts = facts.loc[
        facts["cik"].notna()
        & facts["adsh"].ne("")
        & facts["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & facts["tag"].isin(_ALIAS_LOOKUP)
        & facts["unit"].eq("USD")
        & facts["value"].notna()
        & np.isfinite(facts["value"])
        & facts["period_end"].notna()
        & facts["fact_available_at"].notna()
        & facts["form"].isin({"10-K", "10-K/A", "10-Q", "10-Q/A"})
    ].copy()

    filing = submissions.copy()
    filing["cik"] = pd.to_numeric(filing["cik"], errors="coerce")
    filing["adsh"] = filing["accession_number"].fillna("").astype(str).str.strip()
    filing["submission_accepted_at"] = _utc(filing["accepted_at"])
    filing["sic"] = pd.to_numeric(filing["sic"], errors="coerce")
    filing = (
        filing.sort_values(["cik", "adsh", "submission_accepted_at"])
        .drop_duplicates(["cik", "adsh"], keep="last")
        [["cik", "adsh", "submission_accepted_at", "sic"]]
    )
    facts = facts.merge(filing, on=["cik", "adsh"], how="left", validate="many_to_one")
    facts["accepted_at"] = facts[["fact_available_at", "submission_accepted_at"]].max(
        axis=1
    )
    facts["report_period"] = facts["period_end"]
    facts["concept"] = facts["tag"].map(lambda tag: _ALIAS_LOOKUP[str(tag)][0])
    facts["alias_priority"] = facts["tag"].map(
        lambda tag: _ALIAS_LOOKUP[str(tag)][1]
    )
    duration = (facts["period_end"] - facts["period_start"]).dt.days
    facts["qtrs"] = np.where(facts["period_start"].isna(), 0, np.where(duration.between(250, 450), 4, 1))
    facts["line"] = 0
    group = ["adsh", "concept", "period_end", "qtrs"]
    best_priority = facts.groupby(group)["alias_priority"].transform("min")
    facts = facts.loc[facts["alias_priority"].eq(best_priority)].copy()
    facts["fact_ambiguous"] = facts.groupby(group)["value"].transform("nunique").gt(1)
    facts = facts.sort_values(group + ["accepted_at", "tag"]).drop_duplicates(
        group, keep="last"
    )
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
            "concept",
            "alias_priority",
            "period_end",
            "qtrs",
            "unit",
            "value",
            "line",
            "fact_ambiguous",
        ]
    ].sort_values(["cik", "accepted_at", "adsh", "concept"])


def build_companyfacts_identity(status: pd.DataFrame) -> pd.DataFrame:
    """Build one fail-closed active ticker identity per successful SEC CIK."""

    _require_columns(status, _STATUS_COLUMNS, "SEC status")
    frame = status.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["symbol"] = frame["symbol"].fillna("").astype(str).str.strip().str.upper()
    frame = frame.loc[
        frame["cik"].notna()
        & frame["symbol"].ne("")
        & frame["surface"].isin({"companyfacts", "submissions"})
        & frame["status"].eq("ok")
    ].copy()
    surface_count = frame.groupby(["cik", "symbol"])["surface"].nunique()
    complete = surface_count.loc[surface_count.eq(2)].reset_index()[["cik", "symbol"]]
    ambiguous = complete.loc[complete["cik"].duplicated(keep=False), "cik"].unique()
    complete = complete.loc[~complete["cik"].isin(ambiguous)].copy()
    complete["security_id"] = complete.apply(
        lambda row: f"US-SEC-{int(row['cik']):010d}-{row['symbol']}", axis=1
    )
    complete["valid_from"] = pd.Timestamp("1900-01-01")
    complete["valid_to"] = pd.NaT
    complete["is_primary"] = True
    complete["security_type"] = "common_stock"
    complete["mapping_source"] = "audited_sec_shard_status"
    return complete[
        [
            "security_id",
            "symbol",
            "cik",
            "valid_from",
            "valid_to",
            "is_primary",
            "security_type",
            "mapping_source",
        ]
    ].sort_values("security_id")


def calculate_sec_submission_current(
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate a causal SEC-first-filing proxy for OpenAP FirmAge."""

    _require_columns(submissions, _SUBMISSION_COLUMNS, "SEC submissions")
    identity = build_companyfacts_identity(status)
    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")

    filings = submissions.copy()
    filings["cik"] = pd.to_numeric(filings["cik"], errors="coerce")
    filings["accepted_at"] = _utc(filings["accepted_at"])
    filings = filings.loc[
        filings["cik"].notna()
        & filings["accepted_at"].notna()
        & filings["accepted_at"].le(formation)
    ].copy()
    if filings.empty or identity.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    first_filings = (
        filings.groupby("cik", as_index=False)
        .agg(
            first_accepted_at=("accepted_at", "min"),
            observation_count=("accepted_at", "size"),
        )
        .merge(identity, on="cik", how="inner", validate="one_to_one")
    )
    rows: list[dict[str, Any]] = []
    for row in first_filings.itertuples(index=False):
        first = pd.Timestamp(row.first_accepted_at)
        age_months = (
            (formation.year - first.year) * 12
            + formation.month
            - first.month
            + 1
        )
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": str(row.symbol),
                "cik": f"{int(row.cik):010d}",
                "signal": "FirmAge",
                "formation_at": formation.isoformat(),
                "period_end": formation.isoformat(),
                "filed_at": first.isoformat(),
                "available_at": first.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": float(age_months),
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/submissions/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": "openap_firmage_sec_first_filing_months_proxy",
                "formula_sha256": "",
                "observation_count": int(row.observation_count),
                "reason_if_missing": "",
                "caveat": (
                    "SEC first-filing proxy; OpenAP uses months since first "
                    "CRSP coverage and excludes original CRSP firms"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        "security_id"
    ).reset_index(drop=True)


def calculate_companyfacts_149_current(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate the three pinned formulas from current official SEC evidence."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is not None:
        formation = formation.tz_localize(None)
    normalized = normalize_companyfacts_for_accounting(companyfacts, submissions)
    normalized = normalized.loc[
        normalized["accepted_at"].dt.tz_localize(None).le(formation)
    ].copy()
    normalized["accepted_at"] = normalized["accepted_at"].dt.tz_localize(None)
    normalized["filed_at"] = normalized["filed_at"].dt.tz_localize(None)
    identity = build_companyfacts_identity(status)
    observation_parts = []
    facts_by_cik = {
        int(cik): part for cik, part in normalized.groupby("cik", sort=False)
    }
    for identity_row in identity.itertuples(index=False):
        cik = int(identity_row.cik)
        issuer_facts = facts_by_cik.get(cik)
        if issuer_facts is None:
            continue
        issuer_identity = identity.loc[identity["cik"].eq(cik)].copy()
        observation_parts.append(
            calculate_sec_accounting_batch(
                issuer_facts,
                issuer_identity,
                [formation],
            )
        )
    observations = (
        pd.concat(observation_parts, ignore_index=True)
        if observation_parts
        else pd.DataFrame()
    )
    tickers = identity.set_index("security_id")["symbol"].to_dict()
    rows: list[dict[str, Any]] = []
    for row in observations.itertuples(index=False):
        metadata = FORMULA_METADATA[str(row.signal)]
        ticker = tickers[str(row.security_id)]
        finite = pd.notna(row.value) and np.isfinite(row.value)
        available = pd.to_datetime(row.available_at, errors="coerce", utc=True)
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": ticker,
                "cik": f"{int(row.cik):010d}",
                "signal": str(row.signal),
                "formation_at": pd.Timestamp(formation, tz="UTC").isoformat(),
                "period_end": (
                    pd.Timestamp(row.period_end, tz="UTC").isoformat()
                    if pd.notna(row.period_end)
                    else ""
                ),
                "filed_at": available.isoformat() if pd.notna(available) else "",
                "available_at": available.isoformat() if pd.notna(available) else "",
                "retrieved_at": pd.Timestamp(retrieved_at).isoformat(),
                "value": float(row.value) if finite else np.nan,
                "fidelity_class": "reconstructed" if finite else "unavailable",
                "current_usable": bool(finite),
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": str(metadata["formula_id"]).replace(
                    "_sec_fsd", "_sec_companyfacts"
                ),
                "formula_sha256": str(metadata["sha256"]),
                "observation_count": int(row.observation_count),
                "reason_if_missing": str(row.reason_if_missing),
                "caveat": (
                    "SEC CompanyFacts reconstruction; not validated as "
                    "Compustat-equivalent"
                ),
            }
        )
    result = pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)
    if not result.empty:
        result["signal"] = pd.Categorical(
            result["signal"], categories=list(SEC_ACCOUNTING_BATCH), ordered=True
        )
        result = result.sort_values(["security_id", "signal"]).reset_index(drop=True)
        result["signal"] = result["signal"].astype("string")
    return result


def _dependency_dates(
    inputs: pd.DataFrame,
    signal: str,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp] | None:
    dependencies = ACCOUNTING_FEATURE_DEPENDENCIES.get(signal)
    if not dependencies:
        return None
    lookup = {
        (str(row.concept), int(row.concept_lag)): row
        for row in inputs.dropna(subset=["concept", "concept_lag"]).itertuples()
    }
    rows = [lookup.get(dependency) for dependency in dependencies]
    if any(row is None for row in rows):
        return None
    period_ends = pd.to_datetime(
        pd.Series([row.period_end for row in rows]), errors="coerce", utc=True
    ).dropna()
    available = pd.to_datetime(
        pd.Series([row.available_at for row in rows]), errors="coerce", utc=True
    ).dropna()
    filed = pd.to_datetime(
        pd.Series([row.filed for row in rows]), errors="coerce", utc=True
    ).dropna()
    if period_ends.empty or available.empty:
        return None
    available_at = available.max()
    filed_at = filed.max() if not filed.empty else available_at
    if filed_at > available_at:
        return None
    return period_ends.max(), filed_at, available_at


def calculate_companyfacts_accounting_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
    target_signals: Iterable[str],
    maximum_input_age_days: int = 550,
) -> pd.DataFrame:
    """Calculate every finite pure-SEC accounting formula already implemented."""

    _require_columns(companyfacts, _FACT_COLUMNS, "SEC CompanyFacts")
    targets = {str(signal) for signal in target_signals}
    unsupported = targets.difference(ACCOUNTING_FEATURE_DEPENDENCIES)
    if unsupported:
        raise ValueError(f"Unsupported SEC accounting targets: {sorted(unsupported)}")
    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is not None:
        formation = formation.tz_localize(None)
    identity = build_companyfacts_identity(status)
    facts = companyfacts.copy()
    facts["cik"] = pd.to_numeric(facts["cik"], errors="coerce")
    facts_by_cik = {
        int(cik): part.copy() for cik, part in facts.groupby("cik", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for identity_row in identity.itertuples(index=False):
        cik = int(identity_row.cik)
        issuer_facts = facts_by_cik.get(cik)
        if issuer_facts is None:
            continue
        issuer_facts["symbol"] = str(identity_row.symbol)
        inputs = latest_sec_concept_inputs(issuer_facts, formation)
        concepts = sec_concepts_from_inputs(inputs)
        calculated = calculate_accounting_features(concepts, market_cap=None)
        calculated = apply_accounting_input_freshness(
            calculated,
            inputs,
            as_of=formation,
            maximum_age_days=maximum_input_age_days,
        )
        for signal in sorted(targets):
            value = calculated.get(signal)
            if value is None or value.raw_value is None:
                continue
            number = pd.to_numeric(pd.Series([value.raw_value]), errors="coerce").iloc[0]
            if pd.isna(number) or not np.isfinite(number):
                continue
            dates = _dependency_dates(inputs, signal)
            if dates is None:
                continue
            period_end, filed_at, available_at = dates
            if available_at.tz_localize(None) > formation:
                continue
            fidelity = (
                "reconstructed" if value.status == "exact" else "unvalidated_proxy"
            )
            rows.append(
                {
                    "security_id": str(identity_row.security_id),
                    "ticker": str(identity_row.symbol),
                    "cik": f"{cik:010d}",
                    "signal": signal,
                    "formation_at": pd.Timestamp(formation, tz="UTC").isoformat(),
                    "period_end": period_end.isoformat(),
                    "filed_at": filed_at.isoformat(),
                    "available_at": available_at.isoformat(),
                    "retrieved_at": pd.Timestamp(retrieved_at).isoformat(),
                    "value": float(number),
                    "fidelity_class": fidelity,
                    "current_usable": True,
                    "source_id": "sec_edgar",
                    "source_url": (
                        "https://data.sec.gov/api/xbrl/companyfacts/"
                        f"CIK{cik:010d}.json"
                    ),
                    "formula_id": str(value.formula_id),
                    "formula_sha256": "",
                    "observation_count": len(
                        ACCOUNTING_FEATURE_DEPENDENCIES[signal]
                    ),
                    "reason_if_missing": "",
                    "caveat": str(value.note),
                }
            )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


def _rdability_annual_facts(
    companyfacts: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    required = _FACT_COLUMNS | {"taxonomy", "fy", "fp"}
    _require_columns(companyfacts, required, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["fiscal_year"] = pd.to_numeric(frame["fy"], errors="coerce")
    frame["period_start"] = _utc(frame["period_start"])
    frame["period_end"] = _utc(frame["period_end"])
    frame["filed_at"] = _utc(frame["filed"])
    frame["available_at"] = _utc(frame["available_at"])
    duration = (frame["period_end"] - frame["period_start"]).dt.days
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["fiscal_year"].notna()
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(_RDABILITY_ALIAS_LOOKUP)
        & frame["unit"].eq("USD")
        & frame["form"].isin({"10-K", "10-K/A"})
        & frame["fp"].fillna("").astype(str).eq("FY")
        & duration.between(250, 450)
        & frame["period_end"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(formation)
    ].copy()
    if frame.empty:
        return frame
    frame["concept"] = frame["tag"].map(
        lambda tag: _RDABILITY_ALIAS_LOOKUP[str(tag)][0]
    )
    frame["alias_priority"] = frame["tag"].map(
        lambda tag: _RDABILITY_ALIAS_LOOKUP[str(tag)][1]
    )
    group = ["cik", "fiscal_year", "concept"]
    best_priority = frame.groupby(group)["alias_priority"].transform("min")
    frame = frame.loc[frame["alias_priority"].eq(best_priority)].copy()
    latest_available = frame.groupby(group)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest_available)].copy()
    conflicts = frame.groupby(group)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return frame.sort_values(group + ["filed_at", "accession_number"]).drop_duplicates(
        group, keep="last"
    )


def _rdability_candidate(issuer_facts: pd.DataFrame) -> dict[str, Any] | None:
    values = issuer_facts.pivot(
        index="fiscal_year", columns="concept", values="value"
    ).sort_index()
    if not {"revenue", "rd"}.issubset(values.columns):
        return None
    years = values.index.to_numpy(dtype=int)
    gap_positions = np.flatnonzero(np.diff(years) > 1) + 1
    current_segment_start = int(gap_positions[-1]) if len(gap_positions) else 0
    sales = pd.to_numeric(values["revenue"], errors="coerce")
    rd = pd.to_numeric(values["rd"], errors="coerce")
    sales = sales.where(sales.gt(0))
    rd = rd.where(rd.ge(0))
    sales_growth = np.log(sales / sales.shift(1))
    rd_intensity_log = np.log1p(rd / sales)
    slopes: list[float] = []
    for lag in range(1, 6):
        window = pd.DataFrame(
            {
                "y": sales_growth,
                "x": rd_intensity_log.shift(lag),
            }
        ).tail(8)
        valid = window.dropna()
        if len(valid) < 6:
            continue
        frequency_window = rd_intensity_log.shift(lag).iloc[
            current_segment_start:
        ].tail(8)
        if len(frequency_window) >= 6:
            positive_frequency = float(frequency_window.gt(0).mean())
            if positive_frequency < 0.5:
                continue
        x = valid["x"].to_numpy(dtype=float)
        y = valid["y"].to_numpy(dtype=float)
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            continue
        if float(np.ptp(x)) <= 1e-12:
            continue
        design = np.column_stack([np.ones(len(x), dtype=float), x])
        coefficient = np.linalg.lstsq(design, y, rcond=None)[0][1]
        if np.isfinite(coefficient):
            slopes.append(float(coefficient))
    latest_rd = rd.iloc[-1]
    latest_sales = sales.iloc[-1]
    current_intensity = (
        float(latest_rd / latest_sales)
        if pd.notna(latest_rd)
        and pd.notna(latest_sales)
        and float(latest_sales) != 0.0
        else None
    )
    if not slopes or current_intensity is None or current_intensity <= 0:
        return None
    used_years = set(values.index.astype(float))
    used = issuer_facts.loc[issuer_facts["fiscal_year"].isin(used_years)]
    return {
        "cik": int(issuer_facts["cik"].iloc[0]),
        "value": float(np.mean(slopes)),
        "rd_intensity": float(current_intensity),
        "period_end": used["period_end"].max(),
        "filed_at": used["filed_at"].max(),
        "available_at": used["available_at"].max(),
        "observation_count": int(len(values)),
    }


def calculate_companyfacts_rdability_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Reconstruct current OpenAP RDAbility from causal annual SEC facts."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")
    identity = build_companyfacts_identity(status)
    facts = _rdability_annual_facts(companyfacts, formation)
    candidates = [
        candidate
        for _, issuer_facts in facts.groupby("cik", sort=False)
        if (candidate := _rdability_candidate(issuer_facts)) is not None
    ]
    candidate_frame = pd.DataFrame(candidates)
    if len(candidate_frame) < 3 or candidate_frame["rd_intensity"].nunique() < 3:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    candidate_frame["rd_tercile"] = pd.qcut(
        candidate_frame["rd_intensity"], q=3, labels=False, duplicates="drop"
    )
    observed_terciles = set(candidate_frame["rd_tercile"].dropna().astype(int))
    if observed_terciles != {0, 1, 2}:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    selected = candidate_frame.loc[candidate_frame["rd_tercile"].eq(2)].merge(
        identity, on="cik", how="inner", validate="one_to_one"
    )
    rows = []
    for row in selected.itertuples(index=False):
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": str(row.symbol),
                "cik": f"{int(row.cik):010d}",
                "signal": "RDAbility",
                "formation_at": formation.isoformat(),
                "period_end": pd.Timestamp(row.period_end).isoformat(),
                "filed_at": pd.Timestamp(row.filed_at).isoformat(),
                "available_at": pd.Timestamp(row.available_at).isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": float(row.value),
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": "openap_rdability_sec_companyfacts_current_proxy",
                "formula_sha256": "",
                "observation_count": int(row.observation_count),
                "reason_if_missing": "",
                "caveat": (
                    "SEC CompanyFacts and current CIK-universe reconstruction; "
                    "not validated as Compustat/GVKEY/PERMNO-equivalent"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        "security_id"
    ).reset_index(drop=True)


def _realestate_annual_facts(
    companyfacts: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    required = _FACT_COLUMNS | {"taxonomy", "fy", "fp"}
    _require_columns(companyfacts, required, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["fiscal_year"] = pd.to_numeric(frame["fy"], errors="coerce")
    frame["period_end"] = _utc(frame["period_end"])
    frame["filed_at"] = _utc(frame["filed"])
    frame["available_at"] = _utc(frame["available_at"])
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["fiscal_year"].notna()
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(_REALESTATE_ALIAS_LOOKUP)
        & frame["unit"].eq("USD")
        & frame["form"].isin({"10-K", "10-K/A"})
        & frame["fp"].fillna("").astype(str).eq("FY")
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(formation)
    ].copy()
    if frame.empty:
        return frame
    frame["concept"] = frame["tag"].map(
        lambda tag: _REALESTATE_ALIAS_LOOKUP[str(tag)][0]
    )
    frame["alias_priority"] = frame["tag"].map(
        lambda tag: _REALESTATE_ALIAS_LOOKUP[str(tag)][1]
    )
    group = ["cik", "period_end", "concept"]
    best_priority = frame.groupby(group)["alias_priority"].transform("min")
    frame = frame.loc[frame["alias_priority"].eq(best_priority)].copy()
    latest_available = frame.groupby(group)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest_available)].copy()
    conflicts = frame.groupby(group)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return frame.sort_values(group + ["filed_at", "accession_number"]).drop_duplicates(
        group, keep="last"
    )


def _realestate_candidate(issuer_facts: pd.DataFrame) -> dict[str, Any] | None:
    for period_end in sorted(issuer_facts["period_end"].unique(), reverse=True):
        period = issuer_facts.loc[issuer_facts["period_end"].eq(period_end)].copy()
        lookup = period.set_index("concept")
        if "assets" not in lookup.index:
            continue
        assets = float(lookup.loc["assets", "value"])
        if not np.isfinite(assets):
            continue

        new_concepts = ("buildings_gross", "land", "ppe_gross")
        old_concepts = ("buildings_net", "land", "ppe_net")
        used_concepts: tuple[str, ...] | None = None
        variant = ""
        ratio: float | None = None
        for candidate_concepts, candidate_variant in (
            (new_concepts, "gross"),
            (old_concepts, "net"),
        ):
            if not set(candidate_concepts).issubset(lookup.index):
                continue
            buildings, land, ppe = (
                float(lookup.loc[concept, "value"])
                for concept in candidate_concepts
            )
            if not all(np.isfinite(value) for value in (buildings, land, ppe)):
                continue
            if ppe <= 0:
                continue
            candidate_ratio = (buildings + land) / ppe
            if not np.isfinite(candidate_ratio):
                continue
            ratio = float(candidate_ratio)
            used_concepts = ("assets", *candidate_concepts)
            variant = candidate_variant
            break
        if ratio is None or used_concepts is None:
            continue

        used = period.loc[period["concept"].isin(used_concepts)]
        return {
            "cik": int(issuer_facts["cik"].iloc[0]),
            "ratio": ratio,
            "variant": variant,
            "period_end": used["period_end"].max(),
            "filed_at": used["filed_at"].max(),
            "available_at": used["available_at"].max(),
            "observation_count": int(len(used)),
        }
    return None


def _latest_submission_sic(
    submissions: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    _require_columns(submissions, _SUBMISSION_COLUMNS, "SEC submissions")
    filings = submissions.copy()
    filings["cik"] = pd.to_numeric(filings["cik"], errors="coerce")
    filings["sic"] = pd.to_numeric(filings["sic"], errors="coerce")
    filings["accepted_at"] = _utc(filings["accepted_at"])
    filings["accession_number"] = (
        filings["accession_number"].fillna("").astype(str).str.strip()
    )
    filings = filings.loc[
        filings["cik"].notna()
        & filings["accepted_at"].notna()
        & filings["accepted_at"].le(formation)
    ].copy()
    if filings.empty:
        return pd.DataFrame(columns=["cik", "sic", "sic_available_at"])
    filings = filings.sort_values(
        ["cik", "accepted_at", "accession_number"]
    ).drop_duplicates(["cik", "accepted_at", "accession_number"], keep="last")
    latest_accepted = filings.groupby("cik")["accepted_at"].transform("max")
    latest = filings.loc[filings["accepted_at"].eq(latest_accepted)].copy()
    conflicts = latest.groupby("cik")["sic"].transform("nunique").gt(1)
    latest = latest.loc[~conflicts & latest["sic"].notna()].copy()
    latest = latest.sort_values(["cik", "accession_number"]).drop_duplicates(
        "cik", keep="last"
    )
    latest["sic"] = latest["sic"].astype(int)
    latest = latest.loc[latest["sic"].between(1, 9999)].copy()
    latest["sic2"] = latest["sic"].map(lambda sic: f"{sic:04d}"[:2])
    latest["sic4"] = latest["sic"].map(lambda sic: f"{sic:04d}")
    return latest.rename(columns={"accepted_at": "sic_available_at"})[
        ["cik", "sic", "sic2", "sic4", "sic_available_at"]
    ]


def calculate_companyfacts_realestate_current(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build a causal SEC proxy for OpenAP's industry-adjusted real estate."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")

    identity = build_companyfacts_identity(status)
    facts = _realestate_annual_facts(companyfacts, formation)
    candidates = [
        candidate
        for _, issuer_facts in facts.groupby("cik", sort=False)
        if (candidate := _realestate_candidate(issuer_facts)) is not None
    ]
    candidate_frame = pd.DataFrame(candidates)
    if candidate_frame.empty or identity.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    sic = _latest_submission_sic(submissions, formation)
    candidate_frame = (
        candidate_frame.merge(sic, on="cik", how="inner", validate="one_to_one")
        .merge(identity, on="cik", how="inner", validate="one_to_one")
    )
    if candidate_frame.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    candidate_frame["industry_count"] = candidate_frame.groupby("sic2")[
        "ratio"
    ].transform("count")
    candidate_frame = candidate_frame.loc[
        candidate_frame["industry_count"].ge(5)
    ].copy()
    if candidate_frame.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    candidate_frame["industry_mean"] = candidate_frame.groupby("sic2")[
        "ratio"
    ].transform("mean")
    candidate_frame["value"] = (
        candidate_frame["ratio"] - candidate_frame["industry_mean"]
    )

    rows: list[dict[str, Any]] = []
    for row in candidate_frame.itertuples(index=False):
        available_at = max(
            pd.Timestamp(row.available_at), pd.Timestamp(row.sic_available_at)
        )
        if (
            available_at > formation
            or available_at > retrieved
            or not np.isfinite(row.value)
        ):
            continue
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": str(row.symbol),
                "cik": f"{int(row.cik):010d}",
                "signal": "realestate",
                "formation_at": formation.isoformat(),
                "period_end": pd.Timestamp(row.period_end).isoformat(),
                "filed_at": pd.Timestamp(row.filed_at).isoformat(),
                "available_at": available_at.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": float(row.value),
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": "openap_realestate_sec_companyfacts_current_proxy",
                "formula_sha256": "",
                "observation_count": int(row.observation_count),
                "reason_if_missing": "",
                "caveat": (
                    f"SEC CompanyFacts {row.variant} PP&E and current SEC SIC2 "
                    "proxy; not validated as Compustat/CRSP-equivalent"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        "security_id"
    ).reset_index(drop=True)


def calculate_companyfacts_herfasset_current(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build a causal SEC proxy for OpenAP's asset concentration signal."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")

    identity = build_companyfacts_identity(status)
    annual = _realestate_annual_facts(companyfacts, formation)
    annual = annual.loc[
        annual.get("concept", pd.Series(index=annual.index, dtype="string")).eq(
            "assets"
        )
        & annual["value"].gt(0)
    ].copy()
    sic = _latest_submission_sic(submissions, formation)
    if annual.empty or identity.empty or sic.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    annual = annual.merge(
        sic[["cik", "sic4", "sic_available_at"]],
        on="cik",
        how="inner",
        validate="many_to_one",
    )
    annual = annual.loc[~annual["sic4"].str.startswith("49")].copy()
    if annual.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    latest_period = annual.groupby(["cik", "fiscal_year"])[
        "period_end"
    ].transform("max")
    annual = annual.loc[annual["period_end"].eq(latest_period)].copy()
    annual = annual.sort_values(
        ["cik", "fiscal_year", "available_at", "accession_number"]
    ).drop_duplicates(["cik", "fiscal_year"], keep="last")

    industry_key = ["fiscal_year", "sic4"]
    annual["industry_assets"] = annual.groupby(industry_key)["value"].transform(
        "sum"
    )
    annual = annual.loc[annual["industry_assets"].gt(0)].copy()
    annual["squared_asset_share"] = (
        annual["value"] / annual["industry_assets"]
    ) ** 2
    annual["industry_hhi"] = annual.groupby(industry_key)[
        "squared_asset_share"
    ].transform("sum")
    industry = (
        annual.groupby(industry_key, as_index=False)
        .agg(
            industry_hhi=("industry_hhi", "first"),
            period_end=("period_end", "max"),
            filed_at=("filed_at", "max"),
            available_at=("available_at", "max"),
            observation_count=("cik", "size"),
        )
        .sort_values(industry_key)
    )
    current = (
        annual.sort_values(["cik", "fiscal_year", "period_end"])
        .drop_duplicates("cik", keep="last")
        .merge(identity, on="cik", how="inner", validate="one_to_one")
    )

    rows: list[dict[str, Any]] = []
    for issuer in current.itertuples(index=False):
        history = industry.loc[
            industry["sic4"].eq(str(issuer.sic4))
            & industry["fiscal_year"].le(issuer.fiscal_year)
        ].tail(3)
        if history.empty:
            continue
        value = float(history["industry_hhi"].mean())
        available_at = max(
            history["available_at"].max(), pd.Timestamp(issuer.sic_available_at)
        )
        if (
            available_at > formation
            or available_at > retrieved
            or not np.isfinite(value)
        ):
            continue
        rows.append(
            {
                "security_id": str(issuer.security_id),
                "ticker": str(issuer.symbol),
                "cik": f"{int(issuer.cik):010d}",
                "signal": "HerfAsset",
                "formation_at": formation.isoformat(),
                "period_end": pd.Timestamp(history["period_end"].max()).isoformat(),
                "filed_at": pd.Timestamp(history["filed_at"].max()).isoformat(),
                "available_at": available_at.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": value,
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(issuer.cik):010d}.json"
                ),
                "formula_id": (
                    "openap_herfasset_sec_companyfacts_current_proxy"
                ),
                "formula_sha256": "",
                "observation_count": int(history["observation_count"].sum()),
                "reason_if_missing": "",
                "caveat": (
                    "SEC CompanyFacts three-annual-period SIC4 approximation "
                    "to OpenAP's 36-month asset HHI; current SEC SIC and no "
                    "CRSP share-code filter"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        "security_id"
    ).reset_index(drop=True)


def calculate_companyfacts_herf_current(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build a causal SEC sales-concentration proxy for OpenAP Herf."""

    _require_columns(
        companyfacts,
        _FACT_COLUMNS | {"taxonomy", "fy", "fp"},
        "SEC CompanyFacts",
    )
    aliases = SEC_CONCEPT_ALIASES["revenue"]
    facts = companyfacts.loc[companyfacts["tag"].isin(aliases)].copy()
    if facts.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    alias_rank = {alias: rank for rank, alias in enumerate(aliases)}
    facts["_alias_rank"] = facts["tag"].map(alias_rank)
    best_alias = facts.groupby(["cik", "period_end"])["_alias_rank"].transform(
        "min"
    )
    facts = facts.loc[facts["_alias_rank"].eq(best_alias)].copy()
    facts["tag"] = "Assets"

    result = calculate_companyfacts_herfasset_current(
        facts,
        submissions,
        status,
        formation_at=formation_at,
        retrieved_at=retrieved_at,
    )
    if result.empty:
        return result
    result["signal"] = "Herf"
    result["formula_id"] = "openap_herf_sec_companyfacts_current_proxy"
    result["caveat"] = (
        "SEC CompanyFacts three-annual-period SIC4 approximation to OpenAP's "
        "36-month sales HHI; current SEC SIC and no CRSP share-code filter"
    )
    return result


def calculate_companyfacts_herfbe_current(
    companyfacts: pd.DataFrame,
    submissions: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build a causal SEC book-equity concentration proxy for OpenAP HerfBE."""

    _require_columns(
        companyfacts,
        _FACT_COLUMNS | {"taxonomy", "fy", "fp"},
        "SEC CompanyFacts",
    )
    aliases = SEC_CONCEPT_ALIASES["equity"]
    facts = companyfacts.loc[companyfacts["tag"].isin(aliases)].copy()
    if facts.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    alias_rank = {alias: rank for rank, alias in enumerate(aliases)}
    facts["_alias_rank"] = facts["tag"].map(alias_rank)
    best_alias = facts.groupby(["cik", "period_end"])["_alias_rank"].transform(
        "min"
    )
    facts = facts.loc[facts["_alias_rank"].eq(best_alias)].copy()
    facts["tag"] = "Assets"

    result = calculate_companyfacts_herfasset_current(
        facts,
        submissions,
        status,
        formation_at=formation_at,
        retrieved_at=retrieved_at,
    )
    if result.empty:
        return result
    result["signal"] = "HerfBE"
    result["formula_id"] = "openap_herfbe_sec_companyfacts_current_proxy"
    result["caveat"] = (
        "SEC StockholdersEquity three-annual-period SIC4 approximation to "
        "OpenAP's 36-month adjusted book-equity HHI; current SEC SIC, no "
        "Compustat book-equity adjustments and no CRSP share-code filter"
    )
    return result


def _tax_annual_facts(
    companyfacts: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    required = _FACT_COLUMNS | {"taxonomy", "fy", "fp"}
    _require_columns(companyfacts, required, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["fiscal_year"] = pd.to_numeric(frame["fy"], errors="coerce")
    frame["period_start"] = _utc(frame["period_start"])
    frame["period_end"] = _utc(frame["period_end"])
    frame["filed_at"] = _utc(frame["filed"])
    frame["available_at"] = _utc(frame["available_at"])
    duration = (frame["period_end"] - frame["period_start"]).dt.days
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["fiscal_year"].notna()
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(_TAX_ALIAS_LOOKUP)
        & frame["unit"].eq("USD")
        & frame["form"].isin({"10-K", "10-K/A"})
        & frame["fp"].fillna("").astype(str).eq("FY")
        & duration.between(250, 450)
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(formation)
    ].copy()
    if frame.empty:
        return frame
    frame["concept"] = frame["tag"].map(
        lambda tag: _TAX_ALIAS_LOOKUP[str(tag)][0]
    )
    frame["alias_priority"] = frame["tag"].map(
        lambda tag: _TAX_ALIAS_LOOKUP[str(tag)][1]
    )
    group = ["cik", "period_end", "concept"]
    best_priority = frame.groupby(group)["alias_priority"].transform("min")
    frame = frame.loc[frame["alias_priority"].eq(best_priority)].copy()
    latest_available = frame.groupby(group)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest_available)].copy()
    conflicts = frame.groupby(group)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return frame.sort_values(group + ["filed_at", "accession_number"]).drop_duplicates(
        group, keep="last"
    )


def _tax_candidate(issuer_facts: pd.DataFrame) -> dict[str, Any] | None:
    for period_end in sorted(issuer_facts["period_end"].unique(), reverse=True):
        period = issuer_facts.loc[issuer_facts["period_end"].eq(period_end)].copy()
        lookup = period.set_index("concept")
        if "income" not in lookup.index:
            continue
        income = float(lookup.loc["income", "value"])
        if not np.isfinite(income):
            continue

        direct = {"federal_tax", "foreign_tax"}
        alternative = {"total_tax", "deferred_tax"}
        if direct.issubset(lookup.index):
            numerator = float(lookup.loc["federal_tax", "value"]) + float(
                lookup.loc["foreign_tax", "value"]
            )
            used_concepts = ("income", "federal_tax", "foreign_tax")
            variant = "current_federal_plus_foreign"
        elif alternative.issubset(lookup.index):
            numerator = float(lookup.loc["total_tax", "value"]) - float(
                lookup.loc["deferred_tax", "value"]
            )
            used_concepts = ("income", "total_tax", "deferred_tax")
            variant = "total_less_deferred"
        else:
            continue
        if not np.isfinite(numerator):
            continue
        if income <= 0 and numerator > 0:
            value = 1.0
        elif income == 0:
            continue
        else:
            value = (numerator / 0.35) / income
        if not np.isfinite(value):
            continue
        used = period.loc[period["concept"].isin(used_concepts)]
        return {
            "cik": int(issuer_facts["cik"].iloc[0]),
            "value": float(value),
            "variant": variant,
            "period_end": used["period_end"].max(),
            "filed_at": used["filed_at"].max(),
            "available_at": used["available_at"].max(),
            "observation_count": int(len(used)),
        }
    return None


def calculate_companyfacts_tax_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build a causal SEC proxy for OpenAP taxable-income-to-income."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")
    identity = build_companyfacts_identity(status)
    facts = _tax_annual_facts(companyfacts, formation)
    candidates = [
        candidate
        for _, issuer_facts in facts.groupby("cik", sort=False)
        if (candidate := _tax_candidate(issuer_facts)) is not None
    ]
    candidate_frame = pd.DataFrame(candidates)
    if candidate_frame.empty or identity.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    selected = candidate_frame.merge(
        identity, on="cik", how="inner", validate="one_to_one"
    )
    rows: list[dict[str, Any]] = []
    for row in selected.itertuples(index=False):
        available_at = pd.Timestamp(row.available_at)
        if (
            available_at > formation
            or available_at > retrieved
            or not np.isfinite(row.value)
        ):
            continue
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": str(row.symbol),
                "cik": f"{int(row.cik):010d}",
                "signal": "Tax",
                "formation_at": formation.isoformat(),
                "period_end": pd.Timestamp(row.period_end).isoformat(),
                "filed_at": pd.Timestamp(row.filed_at).isoformat(),
                "available_at": available_at.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": float(row.value),
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": "openap_tax_sec_companyfacts_current_proxy",
                "formula_sha256": "",
                "observation_count": int(row.observation_count),
                "reason_if_missing": "",
                "caveat": (
                    f"SEC CompanyFacts {row.variant} tax proxy; OpenAP uses "
                    "Compustat tax and income semantics"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        "security_id"
    ).reset_index(drop=True)


def _roaq_quarterly_facts(
    companyfacts: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    required = _FACT_COLUMNS | {"taxonomy", "fy", "fp"}
    _require_columns(companyfacts, required, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["period_start"] = _utc(frame["period_start"])
    frame["period_end"] = _utc(frame["period_end"])
    frame["filed_at"] = _utc(frame["filed"])
    frame["available_at"] = _utc(frame["available_at"])
    frame["concept"] = frame["tag"].map(
        lambda tag: _ROAQ_ALIAS_LOOKUP.get(str(tag), (None, None))[0]
    )
    frame["alias_priority"] = frame["tag"].map(
        lambda tag: _ROAQ_ALIAS_LOOKUP.get(str(tag), (None, None))[1]
    )
    duration = (frame["period_end"] - frame["period_start"]).dt.days
    valid_assets = frame["concept"].eq("assets") & frame["form"].isin(
        {"10-K", "10-K/A", "10-Q", "10-Q/A"}
    )
    valid_income = (
        frame["concept"].eq("income")
        & frame["form"].isin({"10-Q", "10-Q/A"})
        & duration.between(70, 110)
    )
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(_ROAQ_ALIAS_LOOKUP)
        & frame["unit"].eq("USD")
        & (valid_assets | valid_income)
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(formation)
    ].copy()
    if frame.empty:
        return frame
    group = ["cik", "period_end", "concept"]
    best_priority = frame.groupby(group)["alias_priority"].transform("min")
    frame = frame.loc[frame["alias_priority"].eq(best_priority)].copy()
    latest_available = frame.groupby(group)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest_available)].copy()
    conflicts = frame.groupby(group)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return frame.sort_values(group + ["filed_at", "accession_number"]).drop_duplicates(
        group, keep="last"
    )


def _roaq_candidate(issuer_facts: pd.DataFrame) -> dict[str, Any] | None:
    income_facts = issuer_facts.loc[issuer_facts["concept"].eq("income")].sort_values(
        "period_end", ascending=False
    )
    assets = issuer_facts.loc[issuer_facts["concept"].eq("assets")].sort_values(
        "period_end"
    )
    for income_row in income_facts.itertuples(index=False):
        prior_assets = assets.loc[assets["period_end"].lt(income_row.period_end)].copy()
        if prior_assets.empty:
            continue
        prior = prior_assets.iloc[-1]
        gap_days = (pd.Timestamp(income_row.period_end) - prior["period_end"]).days
        if not 60 <= gap_days <= 125:
            continue
        denominator = float(prior["value"])
        income = float(income_row.value)
        if denominator <= 0 or not np.isfinite(denominator) or not np.isfinite(income):
            continue
        value = income / denominator
        if not np.isfinite(value):
            continue
        return {
            "cik": int(issuer_facts["cik"].iloc[0]),
            "value": float(value),
            "period_end": income_row.period_end,
            "filed_at": max(
                pd.Timestamp(income_row.filed_at), pd.Timestamp(prior["filed_at"])
            ),
            "available_at": max(
                pd.Timestamp(income_row.available_at),
                pd.Timestamp(prior["available_at"]),
            ),
            "observation_count": 2,
        }
    return None


def calculate_companyfacts_roaq_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build a causal quarterly SEC proxy for OpenAP roaq."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")
    identity = build_companyfacts_identity(status)
    facts = _roaq_quarterly_facts(companyfacts, formation)
    candidates = [
        candidate
        for _, issuer_facts in facts.groupby("cik", sort=False)
        if (candidate := _roaq_candidate(issuer_facts)) is not None
    ]
    candidate_frame = pd.DataFrame(candidates)
    if candidate_frame.empty or identity.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    selected = candidate_frame.merge(
        identity, on="cik", how="inner", validate="one_to_one"
    )
    rows: list[dict[str, Any]] = []
    for row in selected.itertuples(index=False):
        available_at = pd.Timestamp(row.available_at)
        if available_at > formation or available_at > retrieved:
            continue
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": str(row.symbol),
                "cik": f"{int(row.cik):010d}",
                "signal": "roaq",
                "formation_at": formation.isoformat(),
                "period_end": pd.Timestamp(row.period_end).isoformat(),
                "filed_at": pd.Timestamp(row.filed_at).isoformat(),
                "available_at": available_at.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": float(row.value),
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": "openap_roaq_sec_companyfacts_current_proxy",
                "formula_sha256": "",
                "observation_count": int(row.observation_count),
                "reason_if_missing": "",
                "caveat": (
                    "SEC CompanyFacts discrete-quarter income over prior fiscal-"
                    "quarter assets; not validated as Compustat/GVKEY-equivalent"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        "security_id"
    ).reset_index(drop=True)


def _backlog_annual_facts(
    companyfacts: pd.DataFrame,
    formation: pd.Timestamp,
) -> pd.DataFrame:
    required = _FACT_COLUMNS | {"taxonomy", "fy", "fp"}
    _require_columns(companyfacts, required, "SEC CompanyFacts")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["fiscal_year"] = pd.to_numeric(frame["fy"], errors="coerce")
    frame["period_end"] = _utc(frame["period_end"])
    frame["filed_at"] = _utc(frame["filed"])
    frame["available_at"] = _utc(frame["available_at"])
    frame = frame.loc[
        frame["cik"].notna()
        & frame["value"].notna()
        & np.isfinite(frame["value"])
        & frame["fiscal_year"].notna()
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].isin(_BACKLOG_ALIAS_LOOKUP)
        & frame["unit"].eq("USD")
        & frame["form"].isin({"10-K", "10-K/A"})
        & frame["fp"].fillna("").astype(str).eq("FY")
        & frame["period_end"].notna()
        & frame["filed_at"].notna()
        & frame["available_at"].notna()
        & frame["available_at"].le(formation)
    ].copy()
    if frame.empty:
        return frame
    frame["concept"] = frame["tag"].map(
        lambda tag: _BACKLOG_ALIAS_LOOKUP[str(tag)][0]
    )
    frame["alias_priority"] = frame["tag"].map(
        lambda tag: _BACKLOG_ALIAS_LOOKUP[str(tag)][1]
    )
    group = ["cik", "period_end", "concept"]
    best_priority = frame.groupby(group)["alias_priority"].transform("min")
    frame = frame.loc[frame["alias_priority"].eq(best_priority)].copy()
    latest_available = frame.groupby(group)["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest_available)].copy()
    conflicts = frame.groupby(group)["value"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].copy()
    return frame.sort_values(group + ["filed_at", "accession_number"]).drop_duplicates(
        group, keep="last"
    )


def _backlog_candidates(issuer_facts: pd.DataFrame) -> list[dict[str, Any]]:
    periods = sorted(issuer_facts["period_end"].unique())
    ratios: list[dict[str, Any]] = []
    for index in range(1, len(periods)):
        current_end = periods[index]
        prior_end = periods[index - 1]
        gap_days = (pd.Timestamp(current_end) - pd.Timestamp(prior_end)).days
        if not 300 <= gap_days <= 430:
            continue
        current = issuer_facts.loc[issuer_facts["period_end"].eq(current_end)]
        prior = issuer_facts.loc[issuer_facts["period_end"].eq(prior_end)]
        current_lookup = current.set_index("concept")
        prior_lookup = prior.set_index("concept")
        if not {"assets", "backlog"}.issubset(current_lookup.index):
            continue
        if "assets" not in prior_lookup.index:
            continue
        assets = float(current_lookup.loc["assets", "value"])
        assets_lag = float(prior_lookup.loc["assets", "value"])
        backlog = float(current_lookup.loc["backlog", "value"])
        denominator = 0.5 * (assets + assets_lag)
        if (
            backlog == 0
            or denominator <= 0
            or not all(np.isfinite(value) for value in (assets, assets_lag, backlog))
        ):
            continue
        used = pd.concat(
            [
                current.loc[current["concept"].isin({"assets", "backlog"})],
                prior.loc[prior["concept"].eq("assets")],
            ],
            ignore_index=True,
        )
        ratios.append(
            {
                "period_end": pd.Timestamp(current_end),
                "ratio": float(backlog / denominator),
                "filed_at": used["filed_at"].max(),
                "available_at": used["available_at"].max(),
                "observation_count": int(len(used)),
            }
        )
    if not ratios:
        return []
    latest = ratios[-1]
    output = [
        {
            **latest,
            "cik": int(issuer_facts["cik"].iloc[0]),
            "signal": "OrderBacklog",
            "value": latest["ratio"],
            "formula_id": "openap_orderbacklog_sec_companyfacts_current_proxy",
        }
    ]
    if len(ratios) >= 2:
        previous = ratios[-2]
        gap_days = (latest["period_end"] - previous["period_end"]).days
        if 300 <= gap_days <= 430:
            output.append(
                {
                    **latest,
                    "cik": int(issuer_facts["cik"].iloc[0]),
                    "signal": "OrderBacklogChg",
                    "value": latest["ratio"] - previous["ratio"],
                    "formula_id": (
                        "openap_orderbacklogchg_sec_companyfacts_current_proxy"
                    ),
                    "filed_at": max(latest["filed_at"], previous["filed_at"]),
                    "available_at": max(
                        latest["available_at"], previous["available_at"]
                    ),
                    "observation_count": int(
                        latest["observation_count"] + previous["observation_count"]
                    ),
                }
            )
    return output


def calculate_companyfacts_order_backlog_current(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Build causal SEC proxies for the two OpenAP order-backlog signals."""

    formation = pd.Timestamp(formation_at)
    if formation.tzinfo is None:
        formation = formation.tz_localize("UTC")
    else:
        formation = formation.tz_convert("UTC")
    retrieved = pd.Timestamp(retrieved_at)
    if retrieved.tzinfo is None:
        retrieved = retrieved.tz_localize("UTC")
    else:
        retrieved = retrieved.tz_convert("UTC")
    identity = build_companyfacts_identity(status)
    facts = _backlog_annual_facts(companyfacts, formation)
    candidates = [
        candidate
        for _, issuer_facts in facts.groupby("cik", sort=False)
        for candidate in _backlog_candidates(issuer_facts)
    ]
    candidate_frame = pd.DataFrame(candidates)
    if candidate_frame.empty or identity.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)
    selected = candidate_frame.merge(
        identity, on="cik", how="inner", validate="many_to_one"
    )
    rows: list[dict[str, Any]] = []
    for row in selected.itertuples(index=False):
        available_at = pd.Timestamp(row.available_at)
        if (
            available_at > formation
            or available_at > retrieved
            or not np.isfinite(row.value)
        ):
            continue
        rows.append(
            {
                "security_id": str(row.security_id),
                "ticker": str(row.symbol),
                "cik": f"{int(row.cik):010d}",
                "signal": str(row.signal),
                "formation_at": formation.isoformat(),
                "period_end": pd.Timestamp(row.period_end).isoformat(),
                "filed_at": pd.Timestamp(row.filed_at).isoformat(),
                "available_at": available_at.isoformat(),
                "retrieved_at": retrieved.isoformat(),
                "value": float(row.value),
                "fidelity_class": "unvalidated_proxy",
                "current_usable": True,
                "source_id": "sec_edgar",
                "source_url": (
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                    f"CIK{int(row.cik):010d}.json"
                ),
                "formula_id": str(row.formula_id),
                "formula_sha256": "",
                "observation_count": int(row.observation_count),
                "reason_if_missing": "",
                "caveat": (
                    "SEC CompanyFacts OrderBacklog and annual assets proxy; "
                    "not validated as Compustat/GVKEY-equivalent"
                ),
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "build_companyfacts_identity",
    "calculate_companyfacts_accounting_current",
    "calculate_companyfacts_149_current",
    "calculate_companyfacts_herfbe_current",
    "calculate_companyfacts_herf_current",
    "calculate_companyfacts_herfasset_current",
    "calculate_companyfacts_order_backlog_current",
    "calculate_companyfacts_rdability_current",
    "calculate_companyfacts_realestate_current",
    "calculate_companyfacts_roaq_current",
    "calculate_companyfacts_tax_current",
    "calculate_sec_submission_current",
    "normalize_companyfacts_for_accounting",
]

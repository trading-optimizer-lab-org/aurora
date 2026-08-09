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
    years = values.index.to_series().astype(int)
    breaks = years.diff().fillna(1).ne(1)
    if breaks.any():
        values = values.loc[years.index[breaks].max() :]
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
        positive_frequency = float(window["x"].gt(0).mean())
        if len(valid) < 6 or positive_frequency < 0.5:
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


__all__ = [
    "build_companyfacts_identity",
    "calculate_companyfacts_accounting_current",
    "calculate_companyfacts_149_current",
    "calculate_companyfacts_rdability_current",
    "calculate_sec_submission_current",
    "normalize_companyfacts_for_accounting",
]

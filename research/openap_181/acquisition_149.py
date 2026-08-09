"""Fail-closed acquisition ledger for the 149 documented free routes.

The ledger deliberately separates source evidence, a finite current signal,
and strict-score approval.  Existing current artifacts are accepted only when
all recorded sources belong to the signal-specific route allow-list.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
import json
import re

import numpy as np
import pandas as pd


TARGET_FEASIBILITY = "free_route_documented"
TARGET_SIGNAL_COUNT = 149

ROUTE_REQUIRED_COLUMNS = {
    "signal",
    "category",
    "current_free_data_feasibility",
    "current_route_quality",
    "primary_free_sources",
    "current_remaining_blocker",
    "strict_score_eligible",
    "official_formula_url",
    "source_checked_at",
}

CURRENT_VALUE_REQUIRED_COLUMNS = {
    "security_id",
    "ticker",
    "signal",
    "formation_at",
    "period_end",
    "available_at",
    "value",
    "fidelity_class",
    "source_id",
    "source_url",
    "formula_id",
}

MATRIX_COLUMNS = (
    "signal",
    "category",
    "official_formula_url",
    "official_formula_sha256",
    "required_inputs",
    "source_used",
    "source_url",
    "license_terms",
    "minimum_history",
    "data_acquired",
    "current_value_calculated",
    "current_value_count",
    "effective_date",
    "available_at",
    "coverage",
    "fidelity",
    "tests_executed",
    "github_run",
    "source_evidence_run",
    "artifact",
    "status",
    "remaining_blocker",
    "strict_score_eligible",
)

VALUE_COLUMNS = (
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
    "source_id",
    "source_url",
    "formula_id",
    "observation_count",
    "caveat",
)

SOURCE_ALIASES = {
    "sec_edgar": "sec_edgar",
    "sec_companyfacts": "sec_edgar",
    "sec_edgar_companyfacts": "sec_edgar",
    "sec_fsd": "sec_financial_statement_datasets",
    "sec_financial_statement_datasets": "sec_financial_statement_datasets",
    "sec_financial_statement_notes": "sec_financial_statement_notes",
    "sec_13f": "sec_13f",
    "openfigi": "openfigi",
    "openfigi_public": "openfigi",
    "kenneth_french": "kenneth_french_factors",
    "kenneth_french_factors": "kenneth_french_factors",
    "fred_public_csv": "fred",
    "fred": "fred",
    "cboe_public": "cboe_vix",
    "cboe_vix": "cboe_vix",
    "bea_public": "bea",
    "bea": "bea",
    "field_ritter_ipo": "field_ritter_ipo",
    "patentsview_public": "uspto_patentsview",
    "uspto_patentsview": "uspto_patentsview",
    "finra_equity_short_interest": "finra_equity_short_interest",
    "twelve_data_basic": "twelve_data_basic",
}

SOURCE_TERMS = {
    "sec_edgar": "SEC public data; automated access subject to SEC fair-access policy",
    "sec_financial_statement_datasets": "SEC public bulk data; SEC fair-access policy",
    "sec_financial_statement_notes": "SEC public bulk data; SEC fair-access policy",
    "sec_13f": "SEC public filing data; SEC fair-access policy",
    "openfigi": "OpenFIGI free API terms and rate limits",
    "kenneth_french_factors": "Kenneth French Data Library research data terms",
    "fred": "FRED public data terms; series-specific upstream rights apply",
    "cboe_vix": "Cboe public delayed/historical data terms",
    "bea": "BEA public US-government data terms",
    "field_ritter_ipo": "Jay Ritter public research-data usage terms",
    "uspto_patentsview": "USPTO PatentsView public data terms and rate limits",
    "finra_equity_short_interest": "FINRA public data terms; short interest is not short volume",
    "twelve_data_basic": "Twelve Data Basic free-plan terms and request limits",
}

FIDELITY_ORDER = {
    "exact": 0,
    "reconstructed": 1,
    "validated_proxy": 2,
    "unvalidated_proxy": 3,
    "proxy": 3,
    "stale_reference_only": 4,
    "unavailable": 5,
}


class AcquisitionContractError(RuntimeError):
    """Raised when acquisition evidence is incomplete or internally unsafe."""


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise AcquisitionContractError(f"{label} missing columns: {sorted(missing)}")


def _as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_target_routes(path: str | Path) -> pd.DataFrame:
    """Load and freeze the exact 149-row free-route target universe."""

    frame = pd.read_csv(path, dtype={"signal": "string"}, keep_default_na=False)
    _require_columns(frame, ROUTE_REQUIRED_COLUMNS, "route matrix")
    target = frame.loc[
        frame["current_free_data_feasibility"].eq(TARGET_FEASIBILITY)
    ].copy()
    if len(target) != TARGET_SIGNAL_COUNT or target["signal"].nunique() != TARGET_SIGNAL_COUNT:
        raise AcquisitionContractError(
            "route matrix must contain exactly 149 unique free_route_documented signals"
        )
    if target["signal"].str.strip().eq("").any() or target["signal"].duplicated().any():
        raise AcquisitionContractError("route matrix contains a blank or duplicate signal")
    return target.sort_values("signal").reset_index(drop=True)


def _tokens(value: Any) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ()
    return tuple(
        token.strip()
        for token in re.split(r"[|,;]", raw)
        if token.strip()
    )


def _canonical_sources(value: Any) -> tuple[str, ...]:
    return tuple(SOURCE_ALIASES.get(token, token) for token in _tokens(value))


def _source_allowed(source_value: Any, allowed_value: Any) -> bool:
    actual = set(_canonical_sources(source_value))
    allowed = set(_canonical_sources(allowed_value))
    return bool(actual) and actual.issubset(allowed)


def _formula_hashes(formula_inventory: pd.DataFrame | None) -> dict[str, str]:
    if formula_inventory is None or formula_inventory.empty:
        return {}
    if "signal" not in formula_inventory:
        raise AcquisitionContractError("formula inventory missing signal column")
    hash_column = next(
        (name for name in ("formula_sha256", "sha256") if name in formula_inventory),
        None,
    )
    if hash_column is None:
        raise AcquisitionContractError("formula inventory missing sha256 column")
    inventory = formula_inventory[["signal", hash_column]].copy()
    inventory["signal"] = inventory["signal"].astype(str)
    inventory[hash_column] = inventory[hash_column].fillna("").astype(str)
    conflicts = inventory.loc[inventory[hash_column].ne("")].groupby("signal")[
        hash_column
    ].nunique()
    if conflicts.gt(1).any():
        raise AcquisitionContractError("formula inventory contains conflicting hashes")
    return (
        inventory.loc[inventory[hash_column].str.fullmatch(r"[0-9a-fA-F]{64}")]
        .drop_duplicates("signal", keep="last")
        .set_index("signal")[hash_column]
        .str.lower()
        .to_dict()
    )


def _validate_current_rows(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CURRENT_VALUE_REQUIRED_COLUMNS, "current values")
    rows = frame.copy()
    for column in ("formation_at", "period_end", "filed_at", "available_at"):
        if column not in rows:
            rows[column] = pd.NaT
        rows[column] = pd.to_datetime(rows[column], errors="coerce", utc=True)
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    finite = rows["value"].notna() & np.isfinite(rows["value"])
    lookahead = (
        finite
        & rows["available_at"].notna()
        & rows["formation_at"].notna()
        & rows["available_at"].gt(rows["formation_at"])
    )
    if lookahead.any():
        offenders = sorted(rows.loc[lookahead, "signal"].astype(str).unique())
        raise AcquisitionContractError(f"lookahead detected for signals: {offenders}")
    pre_period = (
        finite
        & rows["available_at"].notna()
        & rows["period_end"].notna()
        & rows["available_at"].lt(rows["period_end"])
    )
    if pre_period.any():
        raise AcquisitionContractError("available_at precedes the effective period")
    pre_filing = (
        finite
        & rows["available_at"].notna()
        & rows["filed_at"].notna()
        & rows["available_at"].lt(rows["filed_at"])
    )
    if pre_filing.any():
        raise AcquisitionContractError("available_at precedes filing date")
    key = ["security_id", "signal", "formation_at"]
    duplicate = rows.duplicated(key, keep=False)
    if duplicate.any():
        grouped = rows.loc[duplicate].groupby(key, dropna=False)
        conflicts = grouped["value"].nunique(dropna=False).gt(1)
        if conflicts.any():
            raise AcquisitionContractError("conflicting duplicate current values")
        rows = rows.drop_duplicates(key, keep="last")
    return rows


def _best_fidelity(values: pd.Series) -> str:
    choices = {str(value) for value in values.dropna() if str(value)}
    if not choices:
        return "unavailable"
    return min(choices, key=lambda value: FIDELITY_ORDER.get(value, 99))


def _iso_max(values: pd.Series) -> str:
    parsed = pd.to_datetime(values, errors="coerce", utc=True).dropna()
    if parsed.empty:
        return ""
    return parsed.max().isoformat()


def _contract_fields(
    signal: str,
    signal_contracts: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[str, str]:
    contract = (signal_contracts or {}).get(signal, {})
    required = contract.get("required_inputs", ())
    if isinstance(required, str):
        required_text = required
    else:
        required_text = "|".join(str(item) for item in required)
    history = str(contract.get("minimum_history", "not_yet_frozen"))
    return required_text, history


def build_acquisition_matrix(
    routes: pd.DataFrame,
    current_rows: pd.DataFrame,
    *,
    formula_inventory: pd.DataFrame | None = None,
    signal_contracts: Mapping[str, Mapping[str, Any]] | None = None,
    evidence_run_url: str = "",
    source_evidence_run_url: str = "",
    evidence_artifact: str = "",
    tests_executed: str = "tests/test_openap_149_acquisition.py",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross approved routes with current evidence and emit a 149-row ledger."""

    _require_columns(routes, ROUTE_REQUIRED_COLUMNS, "route matrix")
    if routes["signal"].duplicated().any():
        raise AcquisitionContractError("route matrix contains duplicate signals")
    rows = _validate_current_rows(current_rows)
    route_signals = set(routes["signal"].astype(str))
    rows = rows.loc[rows["signal"].astype(str).isin(route_signals)].copy()
    universe_size = int(current_rows["security_id"].dropna().astype(str).nunique())
    hashes = _formula_hashes(formula_inventory)

    approved_parts: list[pd.DataFrame] = []
    matrix_rows: list[dict[str, Any]] = []
    for route in routes.sort_values("signal").to_dict(orient="records"):
        signal = str(route["signal"])
        part = rows.loc[rows["signal"].astype(str).eq(signal)].copy()
        allowed_sources = route["primary_free_sources"]
        source_match = pd.Series(
            [
                _source_allowed(value, allowed_sources)
                for value in part["source_id"]
            ],
            index=part.index,
            dtype=bool,
        )
        approved = part.loc[source_match].copy()
        unapproved = part.loc[~source_match & part["value"].notna()].copy()
        observation_count = pd.to_numeric(
            approved.get("observation_count", pd.Series(index=approved.index, dtype=float)),
            errors="coerce",
        ).fillna(0)
        raw_evidence = approved["source_url"].fillna("").astype(str).str.strip().ne("")
        data_acquired = bool((raw_evidence | observation_count.gt(0)).any())
        formula_hash = hashes.get(signal, "")
        finite = approved["value"].notna() & np.isfinite(approved["value"])
        formula_present = approved["formula_id"].fillna("").astype(str).str.strip().ne("")
        calculated = approved.loc[finite & formula_present & bool(formula_hash)].copy()
        current_value_calculated = not calculated.empty

        if current_value_calculated:
            status = "current_signal_computed"
            blocker = "strict_validation_and_fidelity_gates_pending"
            approved_parts.append(calculated)
        elif not unapproved.empty:
            bad_sources = sorted(
                {
                    token
                    for value in unapproved["source_id"]
                    for token in _tokens(value)
                }
            )
            status = "blocked_fidelity"
            blocker = "unapproved_current_source:" + "|".join(bad_sources)
        elif data_acquired and not formula_hash:
            status = "blocked_formula"
            blocker = "official_formula_hash_missing_or_unresolved"
        elif data_acquired:
            status = "blocked_coverage"
            reasons = sorted(
                {
                    str(value)
                    for value in approved.get(
                        "reason_if_missing", pd.Series(index=approved.index, dtype="string")
                    ).dropna()
                    if str(value)
                }
            )
            blocker = (
                "|".join(reasons)
                or "approved_inputs_do_not_produce_a_current_value"
            )
        else:
            status = "blocked_source_failure"
            blocker = (
                str(route.get("current_remaining_blocker", ""))
                or "no_approved_current_evidence"
            )

        source_used = sorted(
            {
                canonical
                for value in calculated.get(
                    "source_id", pd.Series(index=calculated.index, dtype="string")
                )
                for canonical in _canonical_sources(value)
            }
        )
        source_urls = sorted(
            {
                str(value)
                for value in calculated.get(
                    "source_url", pd.Series(index=calculated.index, dtype="string")
                ).dropna()
                if str(value)
            }
        )
        terms = " | ".join(
            SOURCE_TERMS.get(source, "terms_not_yet_verified")
            for source in source_used
        )
        required_inputs, minimum_history = _contract_fields(signal, signal_contracts)
        count = int(calculated["security_id"].astype(str).nunique())
        matrix_rows.append(
            {
                "signal": signal,
                "category": str(route["category"]),
                "official_formula_url": str(route["official_formula_url"]),
                "official_formula_sha256": formula_hash,
                "required_inputs": required_inputs,
                "source_used": "|".join(source_used),
                "source_url": "|".join(source_urls),
                "license_terms": terms,
                "minimum_history": minimum_history,
                "data_acquired": data_acquired,
                "current_value_calculated": current_value_calculated,
                "current_value_count": count,
                "effective_date": _iso_max(
                    calculated.get("period_end", pd.Series(dtype="datetime64[ns]"))
                ),
                "available_at": _iso_max(
                    calculated.get("available_at", pd.Series(dtype="datetime64[ns]"))
                ),
                "coverage": float(count / universe_size) if universe_size else 0.0,
                "fidelity": _best_fidelity(
                    calculated.get("fidelity_class", pd.Series(dtype="string"))
                ),
                "tests_executed": tests_executed,
                "github_run": evidence_run_url,
                "source_evidence_run": source_evidence_run_url,
                "artifact": evidence_artifact,
                "status": status,
                "remaining_blocker": blocker,
                "strict_score_eligible": False,
            }
        )

    matrix = pd.DataFrame(matrix_rows, columns=MATRIX_COLUMNS).sort_values("signal")
    if len(matrix) != len(routes) or matrix["signal"].nunique() != len(routes):
        raise AcquisitionContractError("acquisition ledger lost or duplicated a target signal")
    if matrix["strict_score_eligible"].map(_as_bool).any():
        raise AcquisitionContractError("strict score cannot be promoted by acquisition evidence")

    if approved_parts:
        values = pd.concat(approved_parts, ignore_index=True)
    else:
        values = pd.DataFrame(columns=VALUE_COLUMNS)
    for column in VALUE_COLUMNS:
        if column not in values:
            values[column] = pd.NA
    values = values[list(VALUE_COLUMNS)].sort_values(["signal", "security_id"])
    for column in ("formation_at", "period_end", "filed_at", "available_at"):
        values[column] = pd.to_datetime(values[column], errors="coerce", utc=True).map(
            lambda value: value.isoformat() if pd.notna(value) else ""
        )
    return matrix.reset_index(drop=True), values.reset_index(drop=True)


def write_acquisition_outputs(
    matrix: pd.DataFrame,
    values: pd.DataFrame,
    output_dir: str | Path,
    *,
    source_values_sha256: str,
    formula_inventory_sha256: str,
) -> dict[str, Any]:
    """Write bounded human and machine-readable acquisition evidence."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(output / "OPENAP_149_ACQUISITION_MATRIX.csv", index=False)
    values.to_csv(output / "openap_149_current_values.csv", index=False)
    if not values.empty:
        values.to_parquet(output / "openap_149_current_values.parquet", index=False)

    data_count = int(matrix["data_acquired"].map(_as_bool).sum())
    calculated_count = int(matrix["current_value_calculated"].map(_as_bool).sum())
    strict_count = int(matrix["strict_score_eligible"].map(_as_bool).sum())
    reconstructed_count = int(
        (
            matrix["current_value_calculated"].map(_as_bool)
            & matrix["fidelity"].eq("reconstructed")
        ).sum()
    )
    blocked_count = int((~matrix["current_value_calculated"].map(_as_bool)).sum())
    summary = {
        "target_signals": int(len(matrix)),
        "data_acquired": data_count,
        "current_values_calculated": calculated_count,
        "strict_score_eligible": strict_count,
        "reconstructed_not_strict": reconstructed_count,
        "blocked": blocked_count,
        "pending": blocked_count,
        "value_rows": int(len(values)),
        "source_values_sha256": source_values_sha256,
        "formula_inventory_sha256": formula_inventory_sha256,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "fail_closed": True,
    }
    (output / "openap_149_acquisition_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    status_counts = matrix["status"].value_counts().sort_index()
    lines = [
        "# OpenAP 149 Acquisition Status",
        "",
        "This is a fail-closed extraction of already verified current artifacts. ",
        "It does not promote any signal into the strict score.",
        "",
        f"- Target signals: {len(matrix)}",
        f"- Approved free-route data acquired: {data_count}",
        f"- Current signals calculated: {calculated_count}",
        f"- Strict-score eligible: {strict_count}",
        f"- Reconstructed but not strict: {reconstructed_count}",
        f"- Blocked or pending: {blocked_count}",
        f"- Company-signal value rows preserved: {len(values)}",
        "",
        "## Status counts",
        "",
        *[f"- `{name}`: {int(count)}" for name, count in status_counts.items()],
        "",
        "The matrix records source allow-list checks, official formula hashes, ",
        "point-in-time dates, coverage and the remaining blocker per signal.",
    ]
    (output / "OPENAP_149_ACQUISITION_STATUS.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return summary


__all__ = [
    "AcquisitionContractError",
    "MATRIX_COLUMNS",
    "TARGET_SIGNAL_COUNT",
    "build_acquisition_matrix",
    "load_target_routes",
    "write_acquisition_outputs",
]

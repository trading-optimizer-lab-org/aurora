"""Recover audited current accounting features without laundering their age.

The successful YFinance/SEC merge already calculated a broad current feature
grid.  This module accepts only the hash-bound members of that artifact,
reconciles the grid and coverage contracts, and emits a narrow set of
non-strict accounting reconstructions.  The original run timestamp remains the
formation timestamp; recovery time never makes an old observation current.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from aurora.research.openap_181.artifact_recovery import (
    OFFICIAL_SEC_IDENTITY_SOURCES,
    normalise_recovered_security_master,
)


RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID = 31_388_342_037
RECOVERED_CURRENT_FEATURE_SOURCE_URL = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
    f"{RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID}"
)
RECOVERED_CURRENT_FEATURE_SOURCE_ARTIFACT = (
    "openap-yfinance-sec-current-score-results"
)
RECOVERED_CURRENT_FEATURE_SOURCE_ID = (
    f"recovered_openap_features_{RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID}"
    "|sec_edgar|recovered_yfinance_artifacts"
)
RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION = 2

RECOVERED_CURRENT_FEATURE_TARGETS = (
    "AccrualsBM",
    "AM",
    "BM",
    "BMdec",
    "CashProd",
    "CF",
    "cfp",
    "EntMult",
    "EP",
    "Leverage",
    "NetDebtPrice",
    "NetPayoutYield",
    "PayoutYield",
    "PS",
    "RD",
    "SP",
    "AdExp",
)

RECOVERED_CURRENT_FEATURE_DEPENDENCIES: dict[
    str, tuple[tuple[str, int], ...]
] = {
    "AccrualsBM": (
        ("net_income", 0),
        ("operating_cash_flow", 0),
        ("assets", 1),
        ("equity", 0),
    ),
    "AM": (("assets", 0),),
    "BM": (("equity", 0),),
    "BMdec": (("equity", 0),),
    "CashProd": (("assets", 0), ("cash", 0)),
    "CF": (("net_income", 0), ("depreciation", 0)),
    "cfp": (("operating_cash_flow", 0),),
    "EntMult": (
        ("operating_income", 0),
        ("depreciation", 0),
        ("cash", 0),
        ("debt_current", 0),
        ("debt_long", 0),
    ),
    "EP": (("net_income", 0),),
    "Leverage": (("liabilities", 0),),
    "NetDebtPrice": (
        ("debt_current", 0),
        ("debt_long", 0),
        ("cash", 0),
    ),
    "NetPayoutYield": (
        ("dividends", 0),
        ("repurchases", 0),
        ("share_issuance", 0),
    ),
    "PayoutYield": (("dividends", 0), ("repurchases", 0)),
    "PS": (
        ("equity", 0),
        ("assets", 0),
        ("assets", 1),
        ("net_income", 0),
        ("net_income", 1),
        ("operating_cash_flow", 0),
        ("debt_long", 0),
        ("debt_long", 1),
        ("current_assets", 0),
        ("current_assets", 1),
        ("current_liabilities", 0),
        ("current_liabilities", 1),
        ("tax", 0),
        ("interest", 0),
        ("revenue", 0),
        ("revenue", 1),
        ("shares", 0),
        ("shares", 1),
    ),
    "RD": (("rd", 0),),
    "SP": (("revenue", 0),),
    "AdExp": (("advertising", 0),),
}

RECOVERED_CURRENT_FEATURE_FORMULA_SHA256 = {
    "AccrualsBM": "3d2504ee7c6da044cfb9cbe5da5abc6d2e126a917b22b65333bcd28cde08c1fa",
    "AdExp": "2e813c7e054aecddfe759d1b9c136c88ffb62755408f4ecc3697e870033aa82e",
    "AM": "5c66c0e4e0cfcf3ecb68ca6a28d707600500462a8065694d161ab0be380ad750",
    "BM": "b852ede9b0b5cb9da89e752ca4c5348ed96380a923357fa9e7dd5274a9a5d946",
    "BMdec": "111bb8df1db87d92fb55ec4c070dc157281655afe80d9f54796ee4572f533d06",
    "CashProd": "2541484ba36d9869221987b2a5ec015f3dd9aa5ce4406f8a0ffea56173ce1983",
    "CF": "09532e1ce762f64f4b225c5f4bd00b48ae40de55003da0295b1ae617585f1296",
    "cfp": "71b6f3fc630ec686409d5cc9c49d60cda5381402886bf7ea7a3f119093fe41ed",
    "EntMult": "3959786d1f35735633a840c626f3241384cc913f5d026435a02c85c0b44161d9",
    "EP": "7879a38168363a50056907b7819023be609e29a4514bfc7b9bc547a3bd590a96",
    "Leverage": "c63e0c634038e25511493d98fa9ee58099613f5d022df7bc74a33619d034e70b",
    "NetDebtPrice": "cb76e8dc208659a85cddaf38004c8bf4ba7e23349c2afde6b0f7904e72176442",
    "NetPayoutYield": "4a30a7eeee64e52bcc4c609ce5134ac873bc1cff7b7e25ace9282f7887a79afe",
    "PayoutYield": "d9cd4c9f27364929ac0889ed48149f6d7b509c9a6f1d0dc1cde272f2bd8229db",
    "PS": "2c47a2cefe19e28b8cae289b2f57fa14dd3baf9cd960ba74f75321b99d30ac56",
    "RD": "c9b58cea6980a3570096ab08c9e1cd224bb89e5dc0cfbadc80777bbbb263edf3",
    "SP": "4645a61c5b36a42900442c05cf287b44cbe8434f7b4447945ee54c0dc1501e1b",
}

RECOVERED_CURRENT_FEATURE_FIDELITY_CLASS = {
    signal: (
        "unvalidated_proxy"
        if signal in {"AccrualsBM", "BMdec"}
        else "reconstructed"
    )
    for signal in RECOVERED_CURRENT_FEATURE_TARGETS
}

RECOVERED_CURRENT_FEATURE_SIGNAL_CAVEATS = {
    "AccrualsBM": (
        "The source feature uses cash-flow accruals rather than the official "
        "balance-sheet accrual construction."
    ),
    "BMdec": (
        "Current issuer market capitalisation replaces the official historical "
        "December market equity."
    ),
    "EntMult": (
        "Current issuer market capitalisation and normalized SEC debt and "
        "operating-income tags do not prove Compustat equivalence."
    ),
    "PS": (
        "Normalized SEC inputs and current issuer market capitalisation do not "
        "reproduce the historical CRSP/Compustat high-BM portfolio identity."
    ),
}

RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS = (
    "openap_features_current.parquet",
    "coverage_185.csv",
    "sec_concept_inputs_current.parquet",
)
RECOVERED_CURRENT_FEATURE_VALIDATION_MEMBERS = (
    "security_master.parquet",
    "execution_summary.json",
    "output_manifest.csv",
    *RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS,
)
OUTPUT_MANIFEST_BOUND_MEMBERS = tuple(
    name
    for name in RECOVERED_CURRENT_FEATURE_VALIDATION_MEMBERS
    if name != "output_manifest.csv"
)

_SECURITY_REQUIRED_COLUMNS = {
    "security_id",
    "symbol",
    "cik",
    "eligible_common_stock",
    "ranking_eligible",
    "source_sec",
    "retrieved_at_sec",
    "marketCap",
    "issuer_market_cap",
    "issuer_market_cap_source",
    "retrieved_at_yahoo",
}
_FEATURE_REQUIRED_COLUMNS = {
    "as_of",
    "symbol",
    "signalname",
    "raw_value",
    "status",
    "implementation_status",
    "value_status",
    "source",
    "formula_id",
    "note",
    "source_available_at",
    "official_filter_pass",
    "official_filter_status",
}
_COVERAGE_REQUIRED_COLUMNS = {
    "signalname",
    "coverage_status",
    "symbols_with_value",
    "total_symbols",
    "coverage_pct",
    "exact_rows",
    "proxy_rows",
    "unavailable_rows",
}
_CONCEPT_REQUIRED_COLUMNS = {
    "symbol",
    "cik",
    "concept",
    "concept_lag",
    "value",
    "period_end",
    "filed",
    "available_at",
}
_SUMMARY_ZERO_GATES = (
    "concept_inputs_without_available_at",
    "future_concept_inputs",
    "concept_inputs_before_period_end",
    "concept_inputs_before_filed",
    "invalid_concept_units",
    "inconsistent_feature_status",
    "unsupported_official_filters",
    "database_contract_violations",
)
_CAVEAT = (
    "Hash-bound recovery of a current SEC reconstruction combined with a "
    "YFinance issuer-market-cap snapshot. It does not reproduce Compustat/CRSP "
    "semantics, historical GVKEY/PERMNO intervals, or the official lagged "
    "portfolio-formation identity and remains outside the strict score."
)


@dataclass(frozen=True)
class RecoveredCurrentFeatureBundle:
    security_master: pd.DataFrame
    features: pd.DataFrame
    coverage: pd.DataFrame
    concept_inputs: pd.DataFrame
    output_manifest: pd.DataFrame
    summary: Mapping[str, Any]
    evidence: Mapping[str, Any]


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    label: str,
) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{label} lacks columns: {sorted(missing)}")


def _read_parquet(payload: bytes, label: str) -> pd.DataFrame:
    try:
        return pd.read_parquet(BytesIO(payload))
    except Exception as exc:
        raise ValueError(f"{label} is not readable Parquet") from exc


def _read_csv(payload: bytes, label: str) -> pd.DataFrame:
    try:
        return pd.read_csv(BytesIO(payload))
    except Exception as exc:
        raise ValueError(f"{label} is not readable CSV") from exc


def _strict_integer(value: Any, label: str) -> int:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric) or not float(numeric).is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(numeric)


def _utc_timestamp(value: Any) -> pd.Timestamp | pd.NaT:
    return pd.to_datetime(value, errors="coerce", utc=True)


def _normalise_cik(value: Any) -> str:
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.0)?", text) is None:
        return ""
    return str(int(float(text))).zfill(10)


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value)


def validate_recovered_output_manifest(
    members: Mapping[str, bytes],
) -> pd.DataFrame:
    """Bind every required recovered member to the source output manifest."""

    missing = set(RECOVERED_CURRENT_FEATURE_VALIDATION_MEMBERS).difference(members)
    if missing:
        raise ValueError(f"recovered current feature members missing: {sorted(missing)}")
    manifest = _read_csv(members["output_manifest.csv"], "output manifest")
    required_columns = {"file", "bytes", "sha256"}
    _require_columns(manifest, required_columns, "output manifest")
    if manifest.empty or manifest["file"].isna().any():
        raise ValueError("output manifest is empty or contains a blank file")
    names = manifest["file"].astype(str)
    if (
        names.str.strip().eq("").any()
        or names.duplicated(keep=False).any()
        or names.str.contains(r"[/\\]", regex=True).any()
    ):
        raise ValueError("output manifest file identities are invalid")
    manifest["file"] = names
    by_name = manifest.set_index("file", drop=False)
    for member_name in OUTPUT_MANIFEST_BOUND_MEMBERS:
        if member_name not in by_name.index:
            raise ValueError(
                f"output manifest lacks required member {member_name}"
            )
        row = by_name.loc[member_name]
        expected_bytes = _strict_integer(
            row["bytes"], f"output manifest bytes for {member_name}"
        )
        if expected_bytes < 0 or expected_bytes != len(members[member_name]):
            raise ValueError(
                f"output manifest byte count mismatch for {member_name}"
            )
        expected_hash = str(row["sha256"]).strip().lower()
        actual_hash = sha256(members[member_name]).hexdigest()
        if (
            re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
            or actual_hash != expected_hash
        ):
            raise ValueError(
                f"output manifest SHA-256 mismatch for {member_name}"
            )
    return manifest.reset_index(drop=True)


def _validate_summary(payload: bytes) -> tuple[dict[str, Any], pd.Timestamp]:
    try:
        summary = json.loads(payload)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("recovered execution summary is invalid JSON") from exc
    if not isinstance(summary, dict):
        raise ValueError("recovered execution summary must be an object")
    integers = {
        name: _strict_integer(summary.get(name), f"execution summary {name}")
        for name in (
            "input_predictors",
            "eligible_symbols",
            "security_master_rows",
            "coverage_rows",
            "features_rows",
            "sec_concept_input_rows",
        )
    }
    if (
        integers["input_predictors"] != 185
        or integers["eligible_symbols"] <= 0
        or integers["security_master_rows"] <= 0
        or integers["coverage_rows"] != 185
        or integers["features_rows"]
        != integers["input_predictors"] * integers["eligible_symbols"]
        or integers["sec_concept_input_rows"] < 0
        or summary.get("all_facts_have_available_at") is not True
        or summary.get("locked_opened") is not False
        or summary.get("backtest_enabled") is not False
        or summary.get("validation_used_for_selection") is not False
        or summary.get("partial") is not False
        or any(
            _strict_integer(summary.get(name), f"execution summary {name}") != 0
            for name in _SUMMARY_ZERO_GATES
        )
    ):
        raise ValueError("recovered execution summary violates the safety contract")
    source_as_of = _utc_timestamp(summary.get("as_of"))
    if pd.isna(source_as_of):
        raise ValueError("recovered execution summary has an invalid as_of")
    summary.update(integers)
    return summary, source_as_of


def _validate_security_master(
    frame: pd.DataFrame,
    *,
    summary: Mapping[str, Any],
    source_as_of: pd.Timestamp,
    official_identity_universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    security, _identity_normalisation = normalise_recovered_security_master(
        frame,
        official_identity_universe=official_identity_universe,
    )
    _require_columns(security, _SECURITY_REQUIRED_COLUMNS, "security master")
    identity_available_at = pd.to_datetime(
        security["retrieved_at_sec"], errors="coerce", utc=True
    )
    official_scope = pd.Series(True, index=security.index)
    if official_identity_universe is not None:
        official_scope = security["ranking_eligible"].eq(True)  # noqa: E712
    if (
        len(security) != int(summary["security_master_rows"])
        or security.empty
        or security["security_id"].isna().any()
        or security["symbol"].isna().any()
        or security["security_id"].astype(str).str.strip().eq("").any()
        or security["symbol"].astype(str).str.strip().eq("").any()
        or security["security_id"].duplicated(keep=False).any()
        or security["symbol"].duplicated(keep=False).any()
        or not (
            ~official_scope
            | security["source_sec"].fillna("").astype(str).isin(
                OFFICIAL_SEC_IDENTITY_SOURCES
            )
        ).all()
        or identity_available_at.isna().any()
        or identity_available_at.gt(source_as_of).any()
    ):
        raise ValueError("security master identity contract is invalid")
    security["_normalised_cik"] = security["cik"].map(_normalise_cik)
    if security["_normalised_cik"].eq("").any():
        raise ValueError("security master contains an invalid CIK")
    security["_identity_available_at"] = identity_available_at
    return security


def _validate_features(
    frame: pd.DataFrame,
    *,
    summary: Mapping[str, Any],
    source_as_of: pd.Timestamp,
    ranked_symbols: set[str],
) -> pd.DataFrame:
    _require_columns(frame, _FEATURE_REQUIRED_COLUMNS, "current feature grid")
    features = frame.copy()
    features["symbol"] = features["symbol"].astype(str)
    features["signalname"] = features["signalname"].astype(str)
    key = ["as_of", "symbol", "signalname"]
    raw_numeric = pd.to_numeric(features["raw_value"], errors="coerce")
    invalid_raw = features["raw_value"].notna() & (
        raw_numeric.isna() | ~np.isfinite(raw_numeric)
    )
    feature_dates = pd.to_datetime(features["as_of"], errors="coerce", utc=True)
    signal_counts = features.groupby("symbol")["signalname"].nunique()
    if (
        len(features) != int(summary["features_rows"])
        or features[key].isna().any().any()
        or features.duplicated(key, keep=False).any()
        or features["signalname"].nunique() != int(summary["input_predictors"])
        or features["symbol"].nunique() != int(summary["eligible_symbols"])
        or not signal_counts.eq(int(summary["input_predictors"])).all()
        or set(features["symbol"]) != ranked_symbols
        or feature_dates.isna().any()
        or not feature_dates.dt.date.eq(source_as_of.date()).all()
        or invalid_raw.any()
        or not set(RECOVERED_CURRENT_FEATURE_TARGETS).issubset(
            set(features["signalname"])
        )
        or features[
            [
                "status",
                "implementation_status",
                "value_status",
                "official_filter_status",
            ]
        ].isna().any().any()
    ):
        raise ValueError("recovered current feature grid is invalid")
    features["raw_value"] = raw_numeric
    features["source_available_at"] = pd.to_datetime(
        features["source_available_at"], errors="coerce", utc=True
    )
    available = features["value_status"].astype(str).eq("available")
    live_status = features["status"].astype(str).isin({"exact", "proxy"})
    filter_pass = features["official_filter_pass"].eq(True)  # noqa: E712
    if (
        (available & (~features["raw_value"].notna() | ~live_status)).any()
        or (live_status & features["raw_value"].notna() & ~available).any()
        or (available & ~filter_pass).any()
    ):
        raise ValueError("recovered current feature value status is inconsistent")
    return features


def _validate_concept_inputs(
    frame: pd.DataFrame,
    *,
    summary: Mapping[str, Any],
    source_as_of: pd.Timestamp,
    features: pd.DataFrame,
    security: pd.DataFrame,
) -> pd.DataFrame:
    _require_columns(frame, _CONCEPT_REQUIRED_COLUMNS, "SEC concept inputs")
    concepts = frame.copy()
    if len(concepts) != int(summary["sec_concept_input_rows"]):
        raise ValueError("SEC concept input row count does not reconcile")
    concepts["symbol"] = concepts["symbol"].astype(str)
    concepts["concept"] = concepts["concept"].astype(str)
    concepts["concept_lag"] = pd.to_numeric(
        concepts["concept_lag"], errors="coerce"
    )
    integer_lag = concepts["concept_lag"].notna() & concepts[
        "concept_lag"
    ].mod(1).eq(0)
    concepts["period_end"] = pd.to_datetime(
        concepts["period_end"], errors="coerce", utc=True
    )
    concepts["filed"] = pd.to_datetime(
        concepts["filed"], errors="coerce", utc=True
    )
    concepts["available_at"] = pd.to_datetime(
        concepts["available_at"], errors="coerce", utc=True
    )
    concepts["_normalised_cik"] = concepts["cik"].map(_normalise_cik)
    key = ["symbol", "concept", "concept_lag"]
    if (
        concepts[key].isna().any().any()
        or concepts.duplicated(key, keep=False).any()
        or not integer_lag.all()
        or concepts["concept_lag"].lt(0).any()
        or concepts["period_end"].isna().any()
        or concepts["filed"].isna().any()
        or concepts["available_at"].isna().any()
        or concepts["_normalised_cik"].eq("").any()
        or concepts["available_at"].gt(source_as_of).any()
        or concepts["available_at"].lt(concepts["period_end"]).any()
        or concepts["available_at"].lt(concepts["filed"]).any()
        or not set(concepts["symbol"]).issubset(set(features["symbol"]))
    ):
        raise ValueError("SEC concept input causal contract is invalid")
    security_cik = security.set_index("symbol")["_normalised_cik"].to_dict()
    mismatched_cik = concepts["_normalised_cik"].ne(
        concepts["symbol"].map(security_cik)
    )
    if mismatched_cik.any():
        raise ValueError("SEC concept input identity does not match security master")
    concepts["concept_lag"] = concepts["concept_lag"].astype(int)
    lookup = concepts.set_index(key, drop=False)
    target_features = features.loc[
        features["signalname"].isin(RECOVERED_CURRENT_FEATURE_TARGETS)
        & features["raw_value"].notna()
        & features["status"].eq("proxy")
        & features["value_status"].eq("available")
        & features["official_filter_pass"].eq(True)  # noqa: E712
    ]
    for row in target_features.itertuples(index=False):
        dependency_rows = []
        for concept, lag in RECOVERED_CURRENT_FEATURE_DEPENDENCIES[row.signalname]:
            dependency_key = (str(row.symbol), concept, lag)
            if dependency_key not in lookup.index:
                raise ValueError(
                    "recovered feature lacks a required SEC dependency: "
                    f"{row.symbol}:{row.signalname}:{concept}:{lag}"
                )
            dependency_rows.append(lookup.loc[dependency_key])
        expected_available_at = max(
            pd.Timestamp(item["available_at"]) for item in dependency_rows
        )
        if (
            pd.isna(row.source_available_at)
            or pd.Timestamp(row.source_available_at) != expected_available_at
        ):
            raise ValueError(
                "recovered feature SEC dependency timestamp does not reconcile: "
                f"{row.symbol}:{row.signalname}"
            )
        if not _text(row.formula_id).strip():
            raise ValueError(
                f"recovered feature formula id is missing: {row.symbol}:{row.signalname}"
            )
    return concepts


def _validate_coverage(
    frame: pd.DataFrame,
    *,
    summary: Mapping[str, Any],
    features: pd.DataFrame,
) -> pd.DataFrame:
    _require_columns(frame, _COVERAGE_REQUIRED_COLUMNS, "coverage report")
    coverage = frame.copy()
    coverage["signalname"] = coverage["signalname"].astype(str)
    if (
        len(coverage) != int(summary["coverage_rows"])
        or coverage["signalname"].str.strip().eq("").any()
        or coverage["signalname"].duplicated(keep=False).any()
        or set(coverage["signalname"]) != set(features["signalname"])
    ):
        raise ValueError("recovered coverage signal contract is invalid")
    integer_columns = (
        "symbols_with_value",
        "total_symbols",
        "exact_rows",
        "proxy_rows",
        "unavailable_rows",
    )
    for column in integer_columns:
        numeric = pd.to_numeric(coverage[column], errors="coerce")
        if numeric.isna().any() or numeric.mod(1).ne(0).any() or numeric.lt(0).any():
            raise ValueError(f"recovered coverage {column} is invalid")
        coverage[column] = numeric.astype(int)
    coverage_pct = pd.to_numeric(coverage["coverage_pct"], errors="coerce")
    expected_total = int(summary["eligible_symbols"])
    expected_pct = 100.0 * coverage["symbols_with_value"] / expected_total
    if (
        coverage_pct.isna().any()
        or not coverage["total_symbols"].eq(expected_total).all()
        or not coverage["symbols_with_value"].eq(
            coverage["exact_rows"] + coverage["proxy_rows"]
        ).all()
        or not coverage["unavailable_rows"].eq(
            expected_total - coverage["symbols_with_value"]
        ).all()
        or not np.allclose(coverage_pct, expected_pct, rtol=0.0, atol=1e-9)
    ):
        raise ValueError("recovered coverage counts do not reconcile")
    raw_available = features["raw_value"].notna()
    observed = (
        features.assign(
            _exact=(raw_available & features["status"].eq("exact")).astype(int),
            _proxy=(raw_available & features["status"].eq("proxy")).astype(int),
        )
        .groupby("signalname", as_index=False)[["_exact", "_proxy"]]
        .sum()
        .rename(columns={"_exact": "observed_exact", "_proxy": "observed_proxy"})
    )
    reconciled = coverage.merge(
        observed, on="signalname", how="left", validate="one_to_one"
    )
    if (
        reconciled["exact_rows"].ne(reconciled["observed_exact"]).any()
        or reconciled["proxy_rows"].ne(reconciled["observed_proxy"]).any()
    ):
        raise ValueError("recovered coverage does not match the feature grid")
    coverage["coverage_pct"] = coverage_pct
    return coverage


def validate_recovered_current_feature_members(
    members: Mapping[str, bytes],
    *,
    official_identity_universe: pd.DataFrame | None = None,
) -> RecoveredCurrentFeatureBundle:
    """Validate the exact successful-run members needed for 17 reconstructions."""

    manifest = validate_recovered_output_manifest(members)
    summary, source_as_of = _validate_summary(members["execution_summary.json"])
    security = _validate_security_master(
        _read_parquet(members["security_master.parquet"], "security master"),
        summary=summary,
        source_as_of=source_as_of,
        official_identity_universe=official_identity_universe,
    )
    ranked_symbols = set(
        security.loc[security["ranking_eligible"].eq(True), "symbol"].astype(str)  # noqa: E712
    )
    if len(ranked_symbols) != int(summary["eligible_symbols"]):
        raise ValueError("ranked security universe does not match eligible_symbols")
    features = _validate_features(
        _read_parquet(
            members["openap_features_current.parquet"],
            "current feature grid",
        ),
        summary=summary,
        source_as_of=source_as_of,
        ranked_symbols=ranked_symbols,
    )
    concepts = _validate_concept_inputs(
        _read_parquet(
            members["sec_concept_inputs_current.parquet"],
            "SEC concept inputs",
        ),
        summary=summary,
        source_as_of=source_as_of,
        features=features,
        security=security,
    )
    coverage = _validate_coverage(
        _read_csv(members["coverage_185.csv"], "coverage report"),
        summary=summary,
        features=features,
    )
    evidence = {
        "source_run_id": RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID,
        "source_run_url": RECOVERED_CURRENT_FEATURE_SOURCE_URL,
        "source_artifact": RECOVERED_CURRENT_FEATURE_SOURCE_ARTIFACT,
        "source_as_of": source_as_of.isoformat(),
        "input_predictors": int(summary["input_predictors"]),
        "eligible_symbols": int(summary["eligible_symbols"]),
        "features_rows": int(summary["features_rows"]),
        "coverage_rows": int(summary["coverage_rows"]),
        "sec_concept_input_rows": int(summary["sec_concept_input_rows"]),
        "target_signal_count": len(RECOVERED_CURRENT_FEATURE_TARGETS),
        "target_signals": list(RECOVERED_CURRENT_FEATURE_TARGETS),
        "official_formula_sha256": dict(
            RECOVERED_CURRENT_FEATURE_FORMULA_SHA256
        ),
        "member_sha256": {
            name: sha256(members[name]).hexdigest()
            for name in RECOVERED_CURRENT_FEATURE_VALIDATION_MEMBERS
        },
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "historical_ticker_interval_verified": False,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    return RecoveredCurrentFeatureBundle(
        security_master=security,
        features=features,
        coverage=coverage,
        concept_inputs=concepts,
        output_manifest=manifest,
        summary=summary,
        evidence=evidence,
    )


def _issuer_market_availability(
    security: pd.DataFrame,
    *,
    source_as_of: pd.Timestamp,
) -> dict[str, tuple[pd.Timestamp | pd.NaT, str, int]]:
    output: dict[str, tuple[pd.Timestamp | pd.NaT, str, int]] = {}
    common = security.loc[security["eligible_common_stock"].eq(True)].copy()  # noqa: E712
    for cik, group in common.groupby("_normalised_cik", sort=False):
        issuer_caps = pd.to_numeric(group["issuer_market_cap"], errors="coerce")
        sources = group["issuer_market_cap_source"].fillna("").astype(str)
        if issuer_caps.isna().all() or not issuer_caps.dropna().gt(0).all():
            output[cik] = (pd.NaT, "market_cap_evidence_missing", 0)
            continue
        if not sources.str.startswith("yfinance_").all():
            output[cik] = (pd.NaT, "market_cap_provenance_unverified", 0)
            continue
        component_caps = pd.to_numeric(group["marketCap"], errors="coerce")
        contributors = group.loc[component_caps.gt(0)].copy()
        if contributors.empty:
            output[cik] = (pd.NaT, "market_cap_evidence_missing", 0)
            continue
        retrieved = pd.to_datetime(
            contributors["retrieved_at_yahoo"], errors="coerce", utc=True
        )
        if retrieved.isna().any():
            output[cik] = (
                pd.NaT,
                "market_cap_available_at_missing",
                int(len(contributors)),
            )
            continue
        market_available_at = retrieved.max()
        reason = (
            "market_cap_lookahead"
            if market_available_at > source_as_of
            else ""
        )
        output[cik] = (market_available_at, reason, int(len(contributors)))
    return output


def _dependency_periods_match_lags(
    dependency_rows: list[pd.Series],
) -> bool:
    periods_by_lag: dict[int, set[pd.Timestamp]] = {}
    for item in dependency_rows:
        period = pd.to_datetime(item["period_end"], errors="coerce", utc=True)
        if pd.isna(period):
            return False
        lag = int(item["concept_lag"])
        periods_by_lag.setdefault(lag, set()).add(period.normalize())
    if not periods_by_lag or any(
        len(periods) != 1 for periods in periods_by_lag.values()
    ):
        return False
    lags = sorted(periods_by_lag)
    if lags != list(range(lags[0], lags[-1] + 1)):
        return False
    period_for_lag = {
        lag: next(iter(periods)) for lag, periods in periods_by_lag.items()
    }
    for current_lag, prior_lag in zip(lags, lags[1:]):
        day_gap = (
            period_for_lag[current_lag] - period_for_lag[prior_lag]
        ).days
        if not 330 <= day_gap <= 400:
            return False
    return True


def build_recovered_current_feature_observations(
    bundle: RecoveredCurrentFeatureBundle,
) -> pd.DataFrame:
    """Convert the validated 17-signal slice into fail-closed current rows."""

    source_as_of = _utc_timestamp(bundle.summary.get("as_of"))
    if pd.isna(source_as_of):
        raise ValueError("validated feature bundle lost its source as_of")
    security = bundle.security_master.copy()
    security_by_symbol = security.set_index("symbol", drop=False)
    market_evidence = _issuer_market_availability(
        security,
        source_as_of=source_as_of,
    )
    concept_lookup = bundle.concept_inputs.set_index(
        ["symbol", "concept", "concept_lag"], drop=False
    )
    target_features = bundle.features.loc[
        bundle.features["signalname"].isin(RECOVERED_CURRENT_FEATURE_TARGETS)
    ].sort_values(["symbol", "signalname"])
    expected_rows = int(bundle.summary["eligible_symbols"]) * len(
        RECOVERED_CURRENT_FEATURE_TARGETS
    )
    if len(target_features) != expected_rows:
        raise ValueError("validated feature bundle lost target rows")

    rows: list[dict[str, Any]] = []
    for feature in target_features.itertuples(index=False):
        symbol = str(feature.symbol)
        signal = str(feature.signalname)
        identity = security_by_symbol.loc[symbol]
        cik = str(identity["_normalised_cik"])
        dependency_rows: list[pd.Series] = []
        for concept, lag in RECOVERED_CURRENT_FEATURE_DEPENDENCIES[signal]:
            key = (symbol, concept, lag)
            if key in concept_lookup.index:
                dependency_rows.append(concept_lookup.loc[key])
        period_end = (
            max(pd.Timestamp(item["period_end"]) for item in dependency_rows)
            if dependency_rows
            else pd.NaT
        )
        filed_at = (
            max(pd.Timestamp(item["filed"]) for item in dependency_rows)
            if dependency_rows
            else pd.NaT
        )
        dependency_periods_match = _dependency_periods_match_lags(
            dependency_rows
        )
        sec_available_at = _utc_timestamp(feature.source_available_at)
        market_available_at, market_reason, market_observations = market_evidence.get(
            cik,
            (pd.NaT, "market_cap_evidence_missing", 0),
        )
        available_candidates = [
            value
            for value in (
                sec_available_at,
                market_available_at,
                identity["_identity_available_at"],
            )
            if pd.notna(value)
        ]
        available_at = max(available_candidates) if available_candidates else pd.NaT
        raw_value = pd.to_numeric(feature.raw_value, errors="coerce")
        reason = ""
        if str(feature.value_status) == "official_filter_excluded":
            reason = "official_filter_excluded"
        elif str(feature.value_status) != "available" or pd.isna(raw_value):
            reason = str(feature.value_status) or "source_feature_missing"
        elif str(feature.status) != "proxy":
            reason = "source_feature_not_reconstructed_proxy"
        elif (
            feature.official_filter_pass is not True
            and feature.official_filter_pass != True  # noqa: E712
        ):
            reason = "official_filter_excluded"
        elif len(dependency_rows) != len(
            RECOVERED_CURRENT_FEATURE_DEPENDENCIES[signal]
        ):
            reason = "sec_dependency_missing"
        elif not dependency_periods_match:
            reason = "sec_dependency_period_mismatch"
        elif pd.isna(sec_available_at):
            reason = "sec_available_at_missing"
        elif sec_available_at > source_as_of:
            reason = "sec_lookahead"
        elif pd.isna(period_end):
            reason = "effective_period_missing"
        elif pd.isna(filed_at):
            reason = "filing_date_missing"
        elif market_reason:
            reason = market_reason
        elif pd.isna(market_available_at):
            reason = "market_cap_available_at_missing"
        elif pd.isna(available_at) or available_at > source_as_of:
            reason = "combined_source_lookahead"
        elif not math.isfinite(float(raw_value)):
            reason = "non_finite_value"

        usable = reason == ""
        value = float(raw_value) if usable else np.nan
        rows.append(
            {
                "security_id": str(identity["security_id"]),
                "ticker": symbol,
                "cik": cik,
                "signal": signal,
                "formation_at": source_as_of,
                "period_end": period_end,
                "filed_at": filed_at,
                "available_at": available_at,
                "retrieved_at": market_available_at,
                "value": value,
                "current_usable": usable,
                "reason_if_missing": reason,
                "fidelity_class": RECOVERED_CURRENT_FEATURE_FIDELITY_CLASS[
                    signal
                ],
                "source_id": RECOVERED_CURRENT_FEATURE_SOURCE_ID,
                "source_url": RECOVERED_CURRENT_FEATURE_SOURCE_URL,
                "source_run_id": RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID,
                "source_artifact": RECOVERED_CURRENT_FEATURE_SOURCE_ARTIFACT,
                "formula_id": _text(feature.formula_id),
                "official_formula_sha256": (
                    RECOVERED_CURRENT_FEATURE_FORMULA_SHA256[signal]
                ),
                "observation_count": len(dependency_rows) + market_observations,
                "caveat": " ".join(
                    part
                    for part in (
                        _CAVEAT,
                        RECOVERED_CURRENT_FEATURE_SIGNAL_CAVEATS.get(signal, ""),
                    )
                    if part
                ),
                "source_feature_status": str(feature.status),
                "source_feature_note": _text(feature.note),
                "official_filter_status": str(feature.official_filter_status),
                "historical_ticker_interval_verified": False,
                "strict_score_eligible": False,
            }
        )
    observations = pd.DataFrame(rows)
    key = ["security_id", "signal", "formation_at"]
    if (
        len(observations) != expected_rows
        or observations.duplicated(key, keep=False).any()
        or observations["strict_score_eligible"].ne(False).any()  # noqa: E712
        or observations["historical_ticker_interval_verified"].ne(False).any()  # noqa: E712
        or observations.loc[
            observations["current_usable"].eq(False), "value"  # noqa: E712
        ].notna().any()
    ):
        raise ValueError("recovered current feature observations violate the contract")
    return observations.sort_values(["security_id", "signal"]).reset_index(drop=True)


__all__ = [
    "OUTPUT_MANIFEST_BOUND_MEMBERS",
    "RECOVERED_CURRENT_FEATURE_CONTRACT_VERSION",
    "RECOVERED_CURRENT_FEATURE_DEPENDENCIES",
    "RECOVERED_CURRENT_FEATURE_DERIVED_MEMBERS",
    "RECOVERED_CURRENT_FEATURE_FIDELITY_CLASS",
    "RECOVERED_CURRENT_FEATURE_FORMULA_SHA256",
    "RECOVERED_CURRENT_FEATURE_SOURCE_ARTIFACT",
    "RECOVERED_CURRENT_FEATURE_SOURCE_ID",
    "RECOVERED_CURRENT_FEATURE_SOURCE_RUN_ID",
    "RECOVERED_CURRENT_FEATURE_SOURCE_URL",
    "RECOVERED_CURRENT_FEATURE_SIGNAL_CAVEATS",
    "RECOVERED_CURRENT_FEATURE_TARGETS",
    "RECOVERED_CURRENT_FEATURE_VALIDATION_MEMBERS",
    "RecoveredCurrentFeatureBundle",
    "build_recovered_current_feature_observations",
    "validate_recovered_current_feature_members",
    "validate_recovered_output_manifest",
]

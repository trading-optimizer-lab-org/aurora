"""Narrow validation of non-strict proxies in the recovered OpenAP 93 artifact."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OPENAP93_RECOVERY_RUN_ID = 31341580689
OPENAP93_RECOVERY_RUN_URL = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
    f"{OPENAP93_RECOVERY_RUN_ID}"
)
OPENAP93_SOURCE_RUN_ID = 31333714423
OPENAP93_SOURCE_HEAD_SHA = "34464d5327598282aa2af1523422105dfd5dd184"
OPENAP93_SOURCE_ARTIFACT_ID = 9045608652
OPENAP93_SOURCE_ARTIFACT_SIZE_BYTES = 2741147673
OPENAP93_SOURCE_ARTIFACT_NAME = (
    "openap-93-max-free-failed-output-31333714423"
)
OPENAP93_SOURCE_RUN_URL = (
    "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
    f"{OPENAP93_SOURCE_RUN_ID}"
)
OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"

COMPEQUISS_SIGNAL = "CompEquIss"
COMPEQUISS_FORMULA_ID = "openap_compequiss_60m_sec_shares_yahoo_return"
COMPEQUISS_OPENAP_SCRIPT = "Signals/pyCode/Predictors/CompEquIss.py"
COMPEQUISS_IMPLEMENTATION_FILE = (
    "research/openap_93/advanced_accounting_pipeline.py"
)
COMPEQUISS_ORIGINAL_SOURCE = "sec_edgar|yahoo_public"
COMPEQUISS_RECOVERY_SOURCE = "recovered_openap93_compequiss"
COMPEQUISS_CAVEAT = (
    "Primary-share price times SEC issuer shares replaces CRSP company market "
    "equity"
)

_REQUIRED_FILENAMES = (
    "signals_93_current.csv",
    "coverage_93.csv",
    "source_run_manifest.json",
    "openap_93_artifact_recovery_manifest.json",
)
_VALUE_COLUMNS = {
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
    "openap_script",
    "natural_frequency",
    "is_current_for_natural_frequency",
    "observation_count",
    "caveat",
}
_COVERAGE_COLUMNS = {
    "signal",
    "status",
    "fidelity_class",
    "current_usable",
    "exact_formula",
    "primary_source",
    "fallback_source",
    "natural_frequency",
    "universe_count",
    "applicable_count",
    "non_null_count",
    "current_usable_count",
    "not_applicable_count",
    "missing_count",
    "coverage_pct",
    "scraping_required",
    "openap_script",
    "implementation_file",
}


def _find_one(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {filename} under {root}, found {len(matches)}"
        )
    return matches[0]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON evidence: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON evidence must be an object: {path.name}")
    return payload


def _as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes"}


def _strict_int(value: Any, label: str) -> int:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number) or not float(number).is_integer():
        raise ValueError(f"{label} must be an integer")
    return int(number)


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def _validate_manifest_chain(
    paths: dict[str, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    recovery = _read_object(paths["openap_93_artifact_recovery_manifest.json"])
    source = _read_object(paths["source_run_manifest.json"])
    if (
        recovery.get("source_run_id") != OPENAP93_SOURCE_RUN_ID
        or recovery.get("source_head_sha") != OPENAP93_SOURCE_HEAD_SHA
        or recovery.get("source_artifact_id") != OPENAP93_SOURCE_ARTIFACT_ID
        or recovery.get("source_artifact_name") != OPENAP93_SOURCE_ARTIFACT_NAME
        or _strict_int(
            recovery.get("source_artifact_size_bytes"),
            "source artifact size",
        )
        != OPENAP93_SOURCE_ARTIFACT_SIZE_BYTES
        or recovery.get("source_run_url") != OPENAP93_SOURCE_RUN_URL
        or _strict_int(recovery.get("range_requests"), "range requests") <= 0
        or _strict_int(recovery.get("bytes_fetched"), "bytes fetched") <= 0
        or _strict_int(recovery.get("bytes_fetched"), "bytes fetched")
        >= OPENAP93_SOURCE_ARTIFACT_SIZE_BYTES // 100
        or recovery.get("input_signals") != 93
        or recovery.get("full_artifact_downloaded") is not False
        or recovery.get("strict_score_eligible") is not False
        or recovery.get("locked_opened") is not False
        or recovery.get("validation_used_for_selection") is not False
        or recovery.get("cost_eur") != 0
    ):
        raise ValueError("OpenAP 93 recovery manifest violates its pinned contract")

    recovered_hashes = recovery.get("recovered_hashes")
    if not isinstance(recovered_hashes, dict):
        raise ValueError("OpenAP 93 recovery hashes are invalid")
    recovered_names = {
        "signals_93_current.csv": "signals_93_current.csv",
        "coverage_93.csv": "coverage_93.csv",
        "run_manifest.json": "source_run_manifest.json",
    }
    for manifest_name, materialized_name in recovered_names.items():
        if recovered_hashes.get(manifest_name) != _sha256_file(
            paths[materialized_name]
        ):
            raise ValueError(f"OpenAP 93 recovered hash mismatch: {manifest_name}")

    if (
        source.get("input_signals") != 93
        or source.get("openap_commit") != OPENAP_COMMIT
        or source.get("locked_opened") is not False
        or source.get("validation_used_for_selection") is not False
        or source.get("cost_eur") != 0
        or source.get("api_keys_required") is not False
        or source.get("manual_actions_required") is not False
    ):
        raise ValueError("OpenAP 93 source manifest violates its safety contract")
    output_hashes = source.get("output_hashes")
    if not isinstance(output_hashes, dict):
        raise ValueError("OpenAP 93 source output hashes are invalid")
    for filename in ("signals_93_current.csv", "coverage_93.csv"):
        if output_hashes.get(filename) != _sha256_file(paths[filename]):
            raise ValueError(f"OpenAP 93 source hash mismatch: {filename}")
    if source.get("current_usable_signal_count") != recovery.get(
        "current_usable_signal_count"
    ):
        raise ValueError("OpenAP 93 usable-signal counts disagree")
    return recovery, source


def _validate_global_tables(
    values: pd.DataFrame,
    coverage: pd.DataFrame,
    recovery: dict[str, Any],
    source: dict[str, Any],
) -> tuple[list[str], int]:
    _require_columns(values, _VALUE_COLUMNS, "OpenAP 93 values")
    _require_columns(coverage, _COVERAGE_COLUMNS, "OpenAP 93 coverage")
    selected = source.get("selected_signals")
    if (
        not isinstance(selected, list)
        or len(selected) != 93
        or not all(isinstance(signal, str) and signal for signal in selected)
        or len(set(selected)) != 93
        or COMPEQUISS_SIGNAL not in selected
    ):
        raise ValueError("OpenAP 93 selected-signal contract is invalid")
    selected_set = set(selected)
    if (
        set(values["signal"].dropna().astype(str)) != selected_set
        or len(values) != _strict_int(source.get("rows"), "source rows")
        or len(coverage) != 93
        or coverage["signal"].astype(str).duplicated().any()
        or set(coverage["signal"].astype(str)) != selected_set
    ):
        raise ValueError("OpenAP 93 materialized tables do not match the manifest")
    usable_signal_count = int(coverage["current_usable"].map(_as_bool).sum())
    if usable_signal_count != _strict_int(
        recovery.get("current_usable_signal_count"),
        "current usable signal count",
    ):
        raise ValueError("OpenAP 93 coverage usable-signal count is inconsistent")
    universe_count = _strict_int(source.get("universe_count"), "universe count")
    if universe_count <= 0:
        raise ValueError("OpenAP 93 universe must be non-empty")
    return selected, universe_count


def _validate_comp_equ_iss_coverage(
    coverage: pd.DataFrame,
    *,
    universe_count: int,
    usable_count: int,
) -> None:
    rows = coverage.loc[coverage["signal"].astype(str).eq(COMPEQUISS_SIGNAL)]
    if len(rows) != 1:
        raise ValueError("expected exactly one CompEquIss coverage row")
    row = rows.iloc[0]
    count_fields = {
        "universe_count": universe_count,
        "applicable_count": universe_count,
        "non_null_count": usable_count,
        "current_usable_count": usable_count,
        "not_applicable_count": 0,
        "missing_count": universe_count - usable_count,
    }
    if any(_strict_int(row[name], name) != expected for name, expected in count_fields.items()):
        raise ValueError("CompEquIss coverage counts do not reconcile")
    coverage_pct = pd.to_numeric(row["coverage_pct"], errors="coerce")
    expected_pct = usable_count * 100.0 / universe_count
    if pd.isna(coverage_pct) or not np.isclose(float(coverage_pct), expected_pct):
        raise ValueError("CompEquIss coverage percentage does not reconcile")
    if (
        str(row["status"]) != "current_usable"
        or str(row["fidelity_class"]) != "reconstructed"
        or not _as_bool(row["current_usable"])
        or not _as_bool(row["exact_formula"])
        or str(row["primary_source"]) != "sec_edgar"
        or str(row["fallback_source"]) != "yahoo_public"
        or str(row["natural_frequency"]) != "annual"
        or _as_bool(row["scraping_required"])
        or str(row["openap_script"]) != COMPEQUISS_OPENAP_SCRIPT
        or str(row["implementation_file"]) != COMPEQUISS_IMPLEMENTATION_FILE
    ):
        raise ValueError("CompEquIss coverage metadata violates its contract")


def _validate_comp_equ_iss_rows(
    values: pd.DataFrame,
    source: dict[str, Any],
    *,
    universe_count: int,
) -> pd.DataFrame:
    rows = values.loc[values["signal"].astype(str).eq(COMPEQUISS_SIGNAL)].copy()
    if len(rows) != universe_count:
        raise ValueError("CompEquIss does not cover the declared source universe")
    key = ["security_id", "signal", "formation_at"]
    if rows[key].isna().any().any() or rows.duplicated(key, keep=False).any():
        raise ValueError("CompEquIss contains blank or duplicate identity keys")

    ciks = pd.to_numeric(rows["cik"], errors="coerce")
    tickers = rows["ticker"].fillna("").astype(str).str.strip()
    if (
        ciks.isna().any()
        or ciks.le(0).any()
        or ciks.mod(1).ne(0).any()
        or tickers.eq("").any()
    ):
        raise ValueError("CompEquIss contains invalid SEC identity fields")
    expected_ids = pd.Series(
        [
            f"US-SEC-{int(cik):010d}-{ticker}"
            for cik, ticker in zip(ciks, tickers, strict=True)
        ],
        index=rows.index,
    )
    if not rows["security_id"].astype(str).eq(expected_ids).all():
        raise ValueError("CompEquIss security_id does not bind CIK and ticker")

    formation = pd.to_datetime(rows["formation_at"], errors="coerce", utc=True)
    period_end = pd.to_datetime(rows["period_end"], errors="coerce", utc=True)
    filed_at = pd.to_datetime(rows["filed_at"], errors="coerce", utc=True)
    available_at = pd.to_datetime(rows["available_at"], errors="coerce", utc=True)
    retrieved_at = pd.to_datetime(rows["retrieved_at"], errors="coerce", utc=True)
    expected_formation = pd.to_datetime(source.get("formation_at"), errors="coerce", utc=True)
    expected_retrieved = pd.to_datetime(source.get("retrieved_at"), errors="coerce", utc=True)
    if (
        formation.isna().any()
        or period_end.isna().any()
        or available_at.isna().any()
        or retrieved_at.isna().any()
        or pd.isna(expected_formation)
        or pd.isna(expected_retrieved)
        or not formation.eq(expected_formation).all()
        or not retrieved_at.eq(expected_retrieved).all()
        or available_at.gt(formation).any()
        or available_at.lt(period_end).any()
        or (filed_at.notna() & available_at.lt(filed_at)).any()
    ):
        raise ValueError("CompEquIss temporal contract or lookahead check failed")

    numeric_values = pd.to_numeric(rows["value"], errors="coerce")
    usable = rows["current_usable"].map(_as_bool)
    natural_current = rows["is_current_for_natural_frequency"].map(_as_bool)
    observations = pd.to_numeric(rows["observation_count"], errors="coerce")
    if (
        not rows["source_id"].astype(str).eq(COMPEQUISS_ORIGINAL_SOURCE).all()
        or not rows["formula_id"].astype(str).eq(COMPEQUISS_FORMULA_ID).all()
        or not rows["openap_script"].astype(str).eq(COMPEQUISS_OPENAP_SCRIPT).all()
        or not rows["natural_frequency"].astype(str).eq("annual").all()
        or not rows["caveat"].astype(str).eq(COMPEQUISS_CAVEAT).all()
        or not natural_current.eq(usable).all()
        or observations.isna().any()
        or (usable & observations.lt(60)).any()
        or (usable & ~np.isfinite(numeric_values)).any()
        or (~usable & numeric_values.notna()).any()
        or not rows.loc[usable, "fidelity_class"].astype(str).eq("reconstructed").all()
    ):
        raise ValueError("CompEquIss row-level formula or fidelity contract failed")
    return rows.loc[usable].copy()


def load_verified_openap93_comp_equ_iss(
    root: Path | str,
    *,
    evidence_run_url: str,
) -> tuple[pd.DataFrame, list[Path], dict[str, Any]]:
    """Return only verified current CompEquIss rows from the pinned recovery."""

    if evidence_run_url.rstrip("/") != OPENAP93_RECOVERY_RUN_URL:
        raise ValueError("CompEquIss recovery must come from the pinned recovery run")
    artifact_root = Path(root)
    paths = {name: _find_one(artifact_root, name) for name in _REQUIRED_FILENAMES}
    recovery, source = _validate_manifest_chain(paths)
    values = pd.read_csv(paths["signals_93_current.csv"], low_memory=False)
    coverage = pd.read_csv(paths["coverage_93.csv"], low_memory=False)
    _, universe_count = _validate_global_tables(values, coverage, recovery, source)
    current = _validate_comp_equ_iss_rows(
        values,
        source,
        universe_count=universe_count,
    )
    _validate_comp_equ_iss_coverage(
        coverage,
        universe_count=universe_count,
        usable_count=len(current),
    )

    current["source_id"] = COMPEQUISS_RECOVERY_SOURCE
    current["source_url"] = (
        evidence_run_url.rstrip("/") + "|" + current["source_url"].astype(str)
    )
    current["caveat"] = (
        current["caveat"].astype(str)
        + "; recovered from hash-bound OpenAP93 evidence; historical CRSP identity not verified"
    )
    current["strict_score_eligible"] = False
    current["current_usable"] = True
    evidence = {
        "contract_version": 1,
        "recovery_run_id": OPENAP93_RECOVERY_RUN_ID,
        "source_run_id": OPENAP93_SOURCE_RUN_ID,
        "source_head_sha": OPENAP93_SOURCE_HEAD_SHA,
        "openap_commit": OPENAP_COMMIT,
        "signal": COMPEQUISS_SIGNAL,
        "formula_id": COMPEQUISS_FORMULA_ID,
        "universe_count": universe_count,
        "current_value_rows": int(len(current)),
        "source_values_sha256": _sha256_file(paths["signals_93_current.csv"]),
        "strict_score_eligible": False,
        "strict_score_increment": 0,
        "historical_crsp_identity_verified": False,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
    }
    return current.reset_index(drop=True), list(paths.values()), evidence


__all__ = [
    "COMPEQUISS_FORMULA_ID",
    "COMPEQUISS_RECOVERY_SOURCE",
    "OPENAP93_RECOVERY_RUN_URL",
    "load_verified_openap93_comp_equ_iss",
]

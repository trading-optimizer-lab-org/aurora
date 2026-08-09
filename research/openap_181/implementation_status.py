"""Fail-closed implementation gates for the 181 unfinished OpenAP signals."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .completion import CURRENT_EXACT_31


IMPLEMENTATION_STATUS_COLUMNS = [
    "signal",
    "formula_implemented",
    "data_pipeline_implemented",
    "point_in_time_verified",
    "identity_verified",
    "coverage_measured",
    "fidelity_measured",
    "coverage_result",
    "fidelity_result",
    "strict_gate_result",
    "score_eligible",
    "blocking_reason",
    "evidence_run_url",
    "evidence_artifact",
    "implementation_commit",
]

STRICT_INVENTORY_COLUMNS = [
    "signal",
    "eligibility_basis",
    "implementation_commit",
    "evidence_run_url",
    "evidence_artifact",
]

_BOOLEAN_GATES = (
    "formula_implemented",
    "data_pipeline_implemented",
    "point_in_time_verified",
    "identity_verified",
    "coverage_measured",
    "fidelity_measured",
)
_EVIDENCE_COLUMNS = [
    "signal",
    *_BOOLEAN_GATES,
    "coverage_result",
    "fidelity_result",
    "strict_gate_result",
    "blocking_reason",
    "evidence_run_url",
    "evidence_artifact",
    "implementation_commit",
]
_ALLOWED_MEASUREMENT_RESULTS = frozenset({"pass", "fail", "not_measured"})
_ALLOWED_STRICT_RESULTS = frozenset({"approved", "blocked", "not_attempted"})
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _clean_signal_column(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    if "signal" not in frame.columns:
        raise ValueError(f"{label} is missing the signal column")
    result = frame.copy()
    result["signal"] = result["signal"].astype(str).str.strip()
    if result["signal"].eq("").any():
        raise ValueError(f"{label} contains a blank signal")
    if result["signal"].duplicated().any():
        raise ValueError(f"{label} contains duplicate signals")
    return result


def _validate_source_frames(
    manifest: pd.DataFrame,
    resolution: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    clean_manifest = _clean_signal_column(manifest, label="manifest")
    clean_resolution = _clean_signal_column(resolution, label="resolution")
    if len(clean_manifest) != 181 or len(clean_resolution) != 181:
        raise ValueError("Implementation status requires exactly 181 signals")
    if set(clean_manifest["signal"]) != set(clean_resolution["signal"]):
        raise ValueError("Manifest and resolution signal universes do not match")
    if "remaining_blocker" not in clean_resolution.columns:
        raise ValueError("Resolution is missing remaining_blocker")
    blockers = clean_resolution["remaining_blocker"].fillna("").astype(str).str.strip()
    if blockers.eq("").any():
        raise ValueError("Resolution contains a blank remaining blocker")
    clean_resolution["remaining_blocker"] = blockers
    return clean_manifest, clean_resolution


def _require_evidence_schema(evidence: pd.DataFrame) -> pd.DataFrame:
    clean = _clean_signal_column(evidence, label="evidence")
    missing = [column for column in _EVIDENCE_COLUMNS if column not in clean.columns]
    if missing:
        raise ValueError(f"Evidence is missing required columns: {missing}")
    for gate in _BOOLEAN_GATES:
        invalid = ~clean[gate].map(lambda value: isinstance(value, bool))
        if invalid.any():
            raise ValueError(f"Evidence gate {gate} must contain booleans")
    for column in ("coverage_result", "fidelity_result"):
        values = clean[column].fillna("").astype(str).str.strip()
        if not set(values).issubset(_ALLOWED_MEASUREMENT_RESULTS):
            raise ValueError(f"Evidence contains an unsupported {column}")
        clean[column] = values
    strict_results = clean["strict_gate_result"].fillna("").astype(str).str.strip()
    if not set(strict_results).issubset(_ALLOWED_STRICT_RESULTS):
        raise ValueError("Evidence contains an unsupported strict_gate_result")
    clean["strict_gate_result"] = strict_results
    for column in (
        "blocking_reason",
        "evidence_run_url",
        "evidence_artifact",
        "implementation_commit",
    ):
        clean[column] = clean[column].fillna("").astype(str).str.strip()
    if not clean["evidence_run_url"].str.startswith("https://").all():
        raise ValueError("Every evidence row requires an HTTPS run URL")
    if clean["evidence_artifact"].eq("").any():
        raise ValueError("Every evidence row requires a non-empty artifact")
    if not clean["implementation_commit"].map(
        lambda value: bool(_COMMIT_RE.fullmatch(value))
    ).all():
        raise ValueError("Every evidence row requires a 40-character commit SHA")
    return clean[_EVIDENCE_COLUMNS]


def _row_is_eligible(row: pd.Series | dict[str, Any]) -> bool:
    return (
        all(bool(row[gate]) for gate in _BOOLEAN_GATES)
        and row["coverage_result"] == "pass"
        and row["fidelity_result"] == "pass"
        and row["strict_gate_result"] == "approved"
        and str(row["evidence_run_url"]).startswith("https://")
        and bool(str(row["evidence_artifact"]).strip())
        and bool(_COMMIT_RE.fullmatch(str(row["implementation_commit"])))
    )


def build_signal_implementation_status(
    manifest: pd.DataFrame,
    resolution: pd.DataFrame,
    evidence: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one fail-closed implementation row for every unfinished signal."""

    clean_manifest, clean_resolution = _validate_source_frames(manifest, resolution)
    blockers = clean_resolution.set_index("signal")["remaining_blocker"]
    rows = []
    for signal in sorted(clean_manifest["signal"]):
        rows.append(
            {
                "signal": signal,
                **{gate: False for gate in _BOOLEAN_GATES},
                "coverage_result": "not_measured",
                "fidelity_result": "not_measured",
                "strict_gate_result": "not_attempted",
                "score_eligible": False,
                "blocking_reason": blockers.loc[signal],
                "evidence_run_url": "",
                "evidence_artifact": "",
                "implementation_commit": "",
            }
        )
    status = pd.DataFrame(rows, columns=IMPLEMENTATION_STATUS_COLUMNS).set_index("signal")

    if evidence is not None and not evidence.empty:
        clean_evidence = _require_evidence_schema(evidence)
        unknown = set(clean_evidence["signal"]) - set(status.index)
        if unknown:
            raise ValueError(f"Evidence contains unknown signals: {sorted(unknown)}")
        for record in clean_evidence.to_dict(orient="records"):
            signal = record.pop("signal")
            eligible = _row_is_eligible(record)
            record["score_eligible"] = eligible
            if not eligible and record["strict_gate_result"] == "approved":
                record["strict_gate_result"] = "blocked"
            blocker = str(record["blocking_reason"]).strip()
            if eligible:
                record["blocking_reason"] = "none"
            elif not blocker or blocker == "none":
                raise ValueError("Ineligible evidence requires a concrete blocking reason")
            for column, value in record.items():
                status.loc[signal, column] = value

    result = status.reset_index()[IMPLEMENTATION_STATUS_COLUMNS]
    result["score_eligible"] = result.apply(_row_is_eligible, axis=1)
    return result


def build_strict_score_inventory(status: pd.DataFrame) -> pd.DataFrame:
    """Return the code-owned 31 exact signals plus fully gated additions."""

    clean = _clean_signal_column(status, label="implementation status")
    missing = [column for column in IMPLEMENTATION_STATUS_COLUMNS if column not in clean]
    if missing:
        raise ValueError(f"Implementation status is missing required columns: {missing}")
    if len(clean) != 181:
        raise ValueError("Strict inventory requires exactly 181 implementation rows")

    rows = [
        {
            "signal": signal,
            "eligibility_basis": "preexisting_exact_31",
            "implementation_commit": "",
            "evidence_run_url": "",
            "evidence_artifact": "",
        }
        for signal in sorted(CURRENT_EXACT_31)
    ]
    for record in clean.sort_values("signal").to_dict(orient="records"):
        recomputed = _row_is_eligible(record)
        if bool(record["score_eligible"]) != recomputed:
            raise ValueError(f"Inconsistent eligibility for {record['signal']}")
        if not recomputed:
            continue
        rows.append(
            {
                "signal": record["signal"],
                "eligibility_basis": "openap_181_complete_strict_gates",
                "implementation_commit": record["implementation_commit"],
                "evidence_run_url": record["evidence_run_url"],
                "evidence_artifact": record["evidence_artifact"],
            }
        )
    result = pd.DataFrame(rows, columns=STRICT_INVENTORY_COLUMNS)
    if result["signal"].duplicated().any():
        raise ValueError("Strict inventory contains duplicate signals")
    return result.sort_values("signal").reset_index(drop=True)


__all__ = [
    "IMPLEMENTATION_STATUS_COLUMNS",
    "STRICT_INVENTORY_COLUMNS",
    "build_signal_implementation_status",
    "build_strict_score_inventory",
]

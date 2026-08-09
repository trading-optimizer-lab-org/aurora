"""Fail-closed implementation gates for the 181 unfinished OpenAP signals."""

from __future__ import annotations

import re
from pathlib import Path
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
DOCUMENTARY_BLOCKING_CLASSIFICATIONS = frozenset(
    {
        "formula_ambiguous",
        "historical_point_in_time_missing",
        "identifier_bridge_missing",
        "no_free_authorized_source",
        "proxy_only",
        "source_access_unverified",
    }
)


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


def build_documentary_blocker_evidence(
    resolution: pd.DataFrame,
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Attach auditable fail-closed evidence only to closed research classes."""

    clean = _clean_signal_column(resolution, label="resolution")
    required = {
        "final_research_classification",
        "remaining_blocker",
    }
    missing = sorted(required - set(clean.columns))
    if missing:
        raise ValueError(f"Resolution is missing documentary fields: {missing}")
    if not str(evidence_run_url).startswith("https://"):
        raise ValueError("Documentary evidence requires an HTTPS run URL")
    if not str(evidence_artifact).strip():
        raise ValueError("Documentary evidence requires a non-empty artifact")
    if not _COMMIT_RE.fullmatch(str(implementation_commit)):
        raise ValueError("Documentary evidence requires a 40-character commit SHA")
    for column in (
        "final_research_classification",
        "remaining_blocker",
    ):
        clean[column] = clean[column].fillna("").astype(str).str.strip()
    selected = clean.loc[
        clean["final_research_classification"].isin(
            DOCUMENTARY_BLOCKING_CLASSIFICATIONS
        )
    ].copy()
    if selected["remaining_blocker"].eq("").any():
        raise ValueError("Documentary blocker evidence requires concrete blockers")
    rows = []
    for row in selected.sort_values("signal").itertuples(index=False):
        classification = row.final_research_classification
        rows.append(
            {
                "signal": row.signal,
                "formula_implemented": False,
                "data_pipeline_implemented": False,
                "point_in_time_verified": False,
                "identity_verified": False,
                "coverage_measured": False,
                "fidelity_measured": False,
                "coverage_result": "not_measured",
                "fidelity_result": "not_measured",
                "strict_gate_result": "blocked",
                "blocking_reason": f"{classification}:{row.remaining_blocker}",
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
        )
    return pd.DataFrame(rows, columns=_EVIDENCE_COLUMNS)


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


def _markdown_values(values: list[str]) -> str:
    if not values:
        return "None."
    return ", ".join(f"`{value}`" for value in values)


def render_implementation_validation_report(
    status: pd.DataFrame,
    strict_inventory: pd.DataFrame,
) -> str:
    """Render the implementation decisions without converting absence into evidence."""

    clean_status = _clean_signal_column(status, label="implementation status")
    missing_status = [
        column for column in IMPLEMENTATION_STATUS_COLUMNS if column not in clean_status
    ]
    if missing_status or len(clean_status) != 181:
        raise ValueError("Implementation report requires the complete 181-row status")
    clean_inventory = _clean_signal_column(strict_inventory, label="strict inventory")
    missing_inventory = [
        column for column in STRICT_INVENTORY_COLUMNS if column not in clean_inventory
    ]
    if missing_inventory:
        raise ValueError("Implementation report received an invalid strict inventory")

    attempted = clean_status.loc[
        clean_status["strict_gate_result"].ne("not_attempted"), "signal"
    ].sort_values().tolist()
    approved = clean_status.loc[
        clean_status["score_eligible"].map(bool), "signal"
    ].sort_values().tolist()
    rejected = clean_status.loc[
        clean_status["strict_gate_result"].eq("blocked"), "signal"
    ].sort_values().tolist()
    prior = clean_inventory.loc[
        clean_inventory["eligibility_basis"].eq("preexisting_exact_31"), "signal"
    ].sort_values().tolist()
    promoted = clean_inventory.loc[
        clean_inventory["eligibility_basis"].eq(
            "openap_181_complete_strict_gates"
        ),
        "signal",
    ].sort_values().tolist()
    evidence = clean_status.loc[
        clean_status["evidence_run_url"].astype(str).str.startswith("https://"),
        ["evidence_run_url", "evidence_artifact", "implementation_commit"],
    ].drop_duplicates()
    documentary = clean_status.loc[
        clean_status["blocking_reason"].astype(str).str.contains(
            r"formula|legal|licen[cs]e|permission|commercial|document|source",
            case=False,
            regex=True,
        ),
        "signal",
    ].sort_values().tolist()
    coverage_counts = clean_status["coverage_result"].value_counts().sort_index()
    fidelity_counts = clean_status["fidelity_result"].value_counts().sort_index()

    lines = [
        "# OpenAP 181 Implementation Validation Report",
        "",
        "## Decision summary",
        "",
        f"- Signals in implementation registry: {len(clean_status)}",
        f"- Signals attempted: {len(attempted)}",
        f"- Signals approved: {len(approved)}",
        f"- Signals blocked with evidence: {len(rejected)}",
        f"- Signals not attempted: {len(clean_status) - len(attempted)}",
        f"- Strict score signals: {len(clean_inventory)}",
        "",
        "No signal is promoted merely because it produces a value. Promotion requires "
        "formula, data pipeline, point-in-time, identity, measured coverage, measured "
        "fidelity, and complete run evidence to pass together.",
        "",
        "## Attempted, approved, and rejected signals",
        "",
        f"- Attempted: {_markdown_values(attempted)}",
        f"- Approved: {_markdown_values(approved)}",
        f"- Rejected: {_markdown_values(rejected)}",
        "",
        "## Coverage and fidelity",
        "",
        "Coverage results: "
        + ", ".join(f"`{key}`={int(value)}" for key, value in coverage_counts.items()),
        "Fidelity results: "
        + ", ".join(f"`{key}`={int(value)}" for key, value in fidelity_counts.items()),
        "No unmeasured coverage or fidelity value is presented as a successful result.",
        "",
        "## Legal, source, formula, and documentary blockers",
        "",
        _markdown_values(documentary),
        "",
        "The row-level registry remains authoritative for the concrete blocker of every "
        "unfinished signal.",
        "",
        "## Independent OpenAP comparison",
        "",
    ]
    if clean_status["fidelity_measured"].map(bool).any():
        lines.append(
            "Measured fidelity decisions and differences are recorded per signal in the "
            "registry and in the linked evidence artifacts. No formula or threshold was "
            "selected from these results."
        )
    else:
        lines.append(
            "Fidelity has not been measured for this baseline. No agreement or difference "
            "with historical OpenAP values is claimed."
        )
    lines.extend(["", "## Evidence runs and artifacts", ""])
    if evidence.empty:
        lines.append("No implementation evidence run is attached to this baseline.")
    else:
        for row in evidence.sort_values("evidence_run_url").itertuples(index=False):
            lines.append(
                f"- {row.evidence_run_url} — `{row.evidence_artifact}` — "
                f"`{row.implementation_commit}`"
            )
    lines.extend(
        [
            "",
            "## Real strict-score changes",
            "",
            f"- Pre-existing exact signals retained: {len(prior)}",
            f"- Newly promoted signals: {len(promoted)}",
            f"- Newly promoted list: {_markdown_values(promoted)}",
            "",
            "## Exact final usable signal list",
            "",
            _markdown_values(sorted(clean_inventory["signal"].tolist())),
            "",
            "## Per-signal implementation decision",
            "",
            "| Signal | Strict gate | Score eligible | Coverage | Fidelity | Blocker | Evidence |",
            "|---|---|---:|---|---|---|---|",
        ]
    )
    for row in clean_status.sort_values("signal").itertuples(index=False):
        blocker = str(row.blocking_reason).replace("|", "/").replace("\n", " ")
        evidence_url = str(row.evidence_run_url).strip() or "none"
        lines.append(
            f"| `{row.signal}` | `{row.strict_gate_result}` | "
            f"`{str(bool(row.score_eligible)).lower()}` | `{row.coverage_result}` | "
            f"`{row.fidelity_result}` | {blocker} | {evidence_url} |"
        )
    return "\n".join(lines) + "\n"


def write_implementation_outputs(
    manifest: pd.DataFrame,
    resolution: pd.DataFrame,
    output_dir: Path | str,
    evidence: pd.DataFrame | None = None,
) -> dict[str, int]:
    """Write the mandatory implementation registry, strict inventory, and report."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    status = build_signal_implementation_status(manifest, resolution, evidence)
    inventory = build_strict_score_inventory(status)
    report = render_implementation_validation_report(status, inventory)
    status.to_csv(output / "signal_implementation_status_181.csv", index=False)
    inventory.to_csv(output / "strict_score_signal_inventory.csv", index=False)
    (output / "IMPLEMENTATION_VALIDATION_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )
    attempted = int(status["strict_gate_result"].ne("not_attempted").sum())
    approved = int(status["score_eligible"].sum())
    blocked = int(status["strict_gate_result"].eq("blocked").sum())
    not_attempted = int(status["strict_gate_result"].eq("not_attempted").sum())
    return {
        "signals": int(len(status)),
        "unique_signals": int(status["signal"].nunique()),
        "attempted": attempted,
        "approved": approved,
        "blocked": blocked,
        "not_attempted": not_attempted,
        "strict_inventory_signals": int(len(inventory)),
    }


__all__ = [
    "DOCUMENTARY_BLOCKING_CLASSIFICATIONS",
    "IMPLEMENTATION_STATUS_COLUMNS",
    "STRICT_INVENTORY_COLUMNS",
    "build_documentary_blocker_evidence",
    "build_signal_implementation_status",
    "build_strict_score_inventory",
    "render_implementation_validation_report",
    "write_implementation_outputs",
]

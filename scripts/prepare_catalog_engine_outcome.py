#!/usr/bin/env python3
"""Select and expose one explicit reusable catalog-engine outcome."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from aurora.infra.sp500_megarun.catalog_engine_outcome import (
    CatalogEngineOutcomeV1,
    select_catalog_engine_outcome,
)
from aurora.infra.sp500_megarun.catalog_request_contract import canonical_model_bytes


_INPUT_KEYS = frozenset(
    {
        "request_sha256",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "protected_commit_sha",
        "engine_run_id",
        "engine_run_attempt",
        "stage_results",
        "recovery_statuses",
        "final_evidence_artifact",
        "runtime_audit_artifact",
        "science_evidence_artifact",
        "recovery_evidence_artifact",
        "failure_fingerprint",
        "failure_occurrence_count",
        "failure_reason_code",
        "retry_not_before",
        "terminal_failure_code",
        "created_at",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare one closed catalog engine outcome receipt."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _strict_input(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("input is not one regular file")
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant: {value}")
        ),
    )
    if not isinstance(payload, dict) or set(payload) != _INPUT_KEYS:
        raise ValueError("input shape is not closed")
    return payload


def _safe_output_value(value: object | None) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        rendered = value.isoformat().replace("+00:00", "Z")
    elif hasattr(value, "value"):
        rendered = str(value.value)
    else:
        rendered = str(value)
    if "\n" in rendered or "\r" in rendered or len(rendered) > 200:
        raise ValueError("CATALOG_ENGINE_GITHUB_OUTPUT_INVALID")
    return rendered


def _write_github_outputs(
    path: Path | None,
    outcome: CatalogEngineOutcomeV1,
) -> None:
    if path is None:
        return
    if path.is_symlink():
        raise ValueError("CATALOG_ENGINE_GITHUB_OUTPUT_INVALID")
    values = {
        "campaign_state": outcome.state.value,
        "outcome_evidence_sha256": outcome.evidence_sha256,
        "final_evidence_artifact": outcome.final_evidence_artifact,
        "runtime_audit_artifact": outcome.runtime_audit_artifact,
        "science_evidence_artifact": outcome.science_evidence_artifact,
        "recovery_evidence_artifact": outcome.recovery_evidence_artifact,
        "failure_fingerprint": outcome.failure_fingerprint,
        "failure_occurrence_count": outcome.failure_occurrence_count,
        "failure_reason_code": outcome.reason_code,
        "retry_not_before": outcome.retry_not_before,
        "terminal_failure_code": outcome.terminal_failure_code,
    }
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            stream.write(f"{key}={_safe_output_value(value)}\n")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("output already exists")
        payload = _strict_input(args.input)
        outcome = select_catalog_engine_outcome(**payload)
        args.output.write_bytes(canonical_model_bytes(outcome) + b"\n")
        _write_github_outputs(args.github_output, outcome)
        return 0
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"CATALOG_ENGINE_OUTCOME_INPUT_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Select and expose one explicit reusable catalog-engine outcome."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
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
_REDUCTION_RECOVERY_KEYS = frozenset({"reduction_only", "recovery_verified"})
_REDUCTION_RECOVERY_OMITTED_STAGES = frozenset(
    {
        "publish_sealed_payload_artifacts",
        "build_components_a",
        "build_components_b",
        "materialize_cached_components_a",
        "materialize_cached_components_b",
        "verify_component_store",
        "evaluate_a",
        "evaluate_b",
        "evaluate_c",
        "reconcile_wave_0",
        "recovery_wave_1",
        "recovery_wave_2",
        "recovery_wave_3",
        "ready_to_merge",
        "reduce_groups",
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
    if not isinstance(payload, dict) or set(payload) not in {
        _INPUT_KEYS,
        _INPUT_KEYS | _REDUCTION_RECOVERY_KEYS,
    }:
        raise ValueError("input shape is not closed")
    for key in _REDUCTION_RECOVERY_KEYS:
        if key in payload and type(payload[key]) is not bool:
            raise ValueError("reduction recovery flags must be boolean")
    return payload


def _reduction_recovery_mode(payload: Mapping[str, object]) -> tuple[bool, bool]:
    reduction_only = payload.get("reduction_only", False)
    recovery_verified = payload.get("recovery_verified", False)
    if type(reduction_only) is not bool or type(recovery_verified) is not bool:
        raise ValueError("reduction recovery flags must be boolean")
    if recovery_verified != reduction_only:
        raise ValueError("reduction recovery flags are inconsistent")
    if not reduction_only:
        return False, False

    stages = payload.get("stage_results")
    if not isinstance(stages, Mapping):
        raise ValueError("reduction recovery stage results are invalid")
    if stages.get("engine_verify_sealed_plan") != "success":
        raise ValueError("reduction recovery engine verification is invalid")
    if any(stages.get(stage) != "skipped" for stage in _REDUCTION_RECOVERY_OMITTED_STAGES):
        raise ValueError("reduction recovery producer omission is invalid")
    if payload.get("recovery_statuses") != []:
        raise ValueError("reduction recovery cannot contain recovery waves")
    return True, True


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
    *,
    reduction_only: bool,
    recovery_verified: bool,
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
        "reduction_only": str(reduction_only).lower(),
        "recovery_verified": str(recovery_verified).lower(),
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
        reduction_only, recovery_verified = _reduction_recovery_mode(payload)
        outcome_payload = {
            key: value for key, value in payload.items() if key in _INPUT_KEYS
        }
        outcome = select_catalog_engine_outcome(**outcome_payload)
        args.output.write_bytes(canonical_model_bytes(outcome) + b"\n")
        _write_github_outputs(
            args.github_output,
            outcome,
            reduction_only=reduction_only,
            recovery_verified=recovery_verified,
        )
        return 0
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"CATALOG_ENGINE_OUTCOME_INPUT_INVALID:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

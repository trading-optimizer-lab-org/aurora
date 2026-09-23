#!/usr/bin/env python3
"""Emit the one fail-closed terminal receipt for an Atlas-1 fast run.

This command is deliberately compatible with the catalog-fast controller's
terminal interface: it writes a ``CatalogTerminalReceiptV2`` JSON document, a
``{"body": ...}`` comment payload, and the usual ``GITHUB_OUTPUT`` keys.

``--run`` / ``--jobs``
    Fresh GitHub API snapshots for the parent controller run and its jobs.
``--preflight-root`` / ``--final-root``
    Extracted contents of the real ``sp500-atlas-preflight`` and
    ``sp500-atlas-final-results`` artifacts.  The reducer receipt verifies all
    360 shards and 209906 rows; this finalizer does not download shards.

``--plan-sha256`` and ``--final-results-artifact`` optionally bind the
workflow outputs exposed by the reusable call.  The parent run may still be
``in_progress`` with ``conclusion=null``; required job conclusions and the
reducer proof are the terminal evidence.

Missing or inconsistent evidence produces a ``BLOCKED`` receipt.  The command
does not launch, retry, repair, or publish anything and never reads protected
``validation``/``locked`` data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.sp500_megarun.catalog_atlas_terminal_adapter import (  # noqa: E402
    AtlasTerminalEvidenceError,
    AtlasTerminalVerification,
    CAMPAIGN_KEY,
    build_terminal_receipt,
    read_json,
    verify_atlas_terminal_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one fail-closed terminal receipt for an Atlas-1 parent run."
    )
    parser.add_argument("--repo-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--request-context", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--preflight-root", required=True, type=Path)
    parser.add_argument("--final-root", required=True, type=Path)
    parser.add_argument("--plan-sha256", default=None)
    parser.add_argument("--final-results-artifact", default="sp500-atlas-final-results")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--comment-output", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    parser.add_argument(
        "--gate-result",
        choices=("success", "failure", "cancelled", "skipped"),
        default=None,
    )
    return parser


def _write_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_OUTPUT_EXISTS")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _duration(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.3f}s"


def _comment(
    receipt: Mapping[str, Any],
    verification: AtlasTerminalVerification,
) -> dict[str, str]:
    timing = verification.timing
    diagnostics = ", ".join(verification.diagnostics) if verification.diagnostics else "none"
    body = (
        "## AURORA catalog fast path\n\n"
        f"- State: `{receipt['state']}`\n"
        f"- Reason: `{receipt['reason_code']}`\n"
        f"- Progress: `{receipt['observed_recipe_count']}/{receipt['expected_recipe_count']}`\n"
        f"- Workflow: `{verification.run_id if verification.run_id is not None else 'unknown'}`\n"
        f"- Atlas artifacts: `sp500-atlas-preflight`, `sp500-atlas-final-results` "
        f"({verification.artifact_count} artifacts)\n"
        f"- Plan: `{verification.plan_sha256 or 'unavailable'}`\n"
        f"- Boundaries: `validation_opened=False`, `locked_opened=False`\n"
        f"- Timing diagnostics: {diagnostics}\n"
        f"- Initial queue: {_duration(timing.get('initial_queue_seconds'))}\n"
        f"- Preflight jobs window: {_duration(timing.get('preparation_jobs_window_seconds'))}\n"
        f"- Evaluation jobs window: {_duration(timing.get('evaluation_jobs_window_seconds'))}\n"
        f"- Worker evaluation aggregate: {_duration(timing.get('worker_evaluation_seconds'))}\n"
        f"- Reduction jobs window: {_duration(timing.get('reduction_jobs_window_seconds'))}\n"
        f"- Receipt: `{receipt['receipt_sha256']}`"
    )
    return {"body": body}


def _load_boundaries(
    context_path: Path,
    decision_path: Path,
) -> tuple[Any, Any]:
    """Load only the authority-bound inputs for fail-closed fallback receipts."""

    from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
    from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
    from aurora.infra.github_performance.contracts import canonical_sha256

    context = read_json(context_path, "ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID")
    if not isinstance(context, Mapping):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID")
    identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if context.get("content_sha256") != canonical_sha256(identity):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_REQUEST_CONTEXT_INVALID")
    try:
        request = CatalogRunRequestV1.model_validate(context.get("request"))
        decision = CatalogFastLaunchDecisionV1.model_validate(
            read_json(decision_path, "ATLAS_TERMINAL_DECISION_INVALID")
        )
    except Exception as exc:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_AUTHORITY_BINDING_INVALID") from exc
    context_identity = context.get("identity")
    if (
        not isinstance(context_identity, Mapping)
        or context_identity.get("engine_id") != "atlas_static_v1"
        or context_identity.get("campaign_key") != CAMPAIGN_KEY
        or context.get("logical_recipe_count") != 209_906
        or request.campaign_key != context_identity.get("campaign_key")
        or decision.request_sha256 != request.request_sha256
        or decision.submission_key_sha256 != request.submission_key_sha256
        or decision.campaign_key != request.campaign_key
    ):
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_AUTHORITY_BINDING_INVALID")
    return request, decision


def finalize_atlas_run(
    *,
    repo_root: Path,
    request_context_path: Path,
    decision_path: Path,
    run_path: Path,
    jobs_path: Path,
    preflight_root: Path,
    final_root: Path,
    output_path: Path,
    comment_output_path: Path,
    github_output: Path,
    gate_result: str | None = None,
    expected_plan_sha256: str | None = None,
    final_results_artifact: str = "sp500-atlas-final-results",
):
    if gate_result not in {None, "success", "failure", "cancelled", "skipped"}:
        raise AtlasTerminalEvidenceError("ATLAS_TERMINAL_GATE_RESULT_INVALID")
    request, decision = _load_boundaries(request_context_path, decision_path)
    try:
        _, verified_request, verified_decision, verification = verify_atlas_terminal_evidence(
            repo_root=Path(repo_root),
            context_path=request_context_path,
            decision_path=decision_path,
            run_path=run_path,
            jobs_path=jobs_path,
            preflight_root=preflight_root,
            final_root=final_root,
            gate_result=gate_result,
            expected_plan_sha256=expected_plan_sha256,
            final_results_artifact=final_results_artifact,
        )
        request, decision = verified_request, verified_decision
    except AtlasTerminalEvidenceError as exc:
        # Request and decision are already authenticated and hash-bound.  A
        # malformed/missing parent-run evidence is therefore safe to terminalize
        # as BLOCKED, while a malformed authority input still raises above.
        verification = AtlasTerminalVerification(
            state="BLOCKED",
            reason_code=exc.code,
            expected_recipe_count=209_906,
            observed_recipe_count=0,
            run_id=None,
            run_url=None,
            plan_sha256=None,
            result_science_sha256=None,
            artifact_count=0,
            timing={
                "initial_queue_seconds": None,
                "preparation_jobs_window_seconds": None,
                "evaluation_jobs_window_seconds": None,
                "recovery_jobs_window_seconds": None,
                "reduction_jobs_window_seconds": None,
                "worker_evaluation_seconds": None,
            },
            diagnostics=(exc.code,),
        )
    receipt = build_terminal_receipt(
        request=request,
        decision=decision,
        verification=verification,
        created_at=datetime.now(timezone.utc),
    )
    receipt_payload = receipt.model_dump(mode="json")
    comment_payload = _comment(receipt_payload, verification)
    _write_json(output_path, receipt_payload)
    _write_json(comment_output_path, comment_payload)
    github_output.parent.mkdir(parents=True, exist_ok=True)
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"terminal_state={receipt.state}\n")
        stream.write(f"terminal_reason_code={receipt.reason_code}\n")
        stream.write(f"terminal_receipt_sha256={receipt.receipt_sha256}\n")
        stream.write(f"atlas_final_results_artifact={final_results_artifact}\n")
        stream.write(f"atlas_plan_sha256={verification.plan_sha256 or ''}\n")
        stream.write(f"atlas_workflow_run_id={verification.run_id or ''}\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        finalize_atlas_run(
            repo_root=args.repo_root,
            request_context_path=args.request_context,
            decision_path=args.decision,
            run_path=args.run,
            jobs_path=args.jobs,
            preflight_root=args.preflight_root,
            final_root=args.final_root,
            output_path=args.output,
            comment_output_path=args.comment_output,
            github_output=args.github_output,
            gate_result=args.gate_result,
            expected_plan_sha256=args.plan_sha256,
            final_results_artifact=args.final_results_artifact,
        )
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

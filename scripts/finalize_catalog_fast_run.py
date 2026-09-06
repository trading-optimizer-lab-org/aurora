#!/usr/bin/env python3
"""Create the one terminal receipt for a fast catalog request."""

from __future__ import annotations

from aurora.infra.sp500_megarun.catalog_recovery_blocks import aggregate_recovery_metrics

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_engine_outcome import (
    CatalogEngineOutcomeState,
    CatalogEngineOutcomeV1,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1,
    CatalogTerminalReceiptV2,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize one fast catalog request.")
    parser.add_argument("--request-context", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--jobs", required=True, type=Path)
    parser.add_argument("--engine-outcome", type=Path)
    parser.add_argument("--science-index", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--comment-output", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    parser.add_argument("--gate-result", choices=("success", "failure", "cancelled", "skipped"))
    return parser


def _strict_json(path: Path) -> object:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("CATALOG_FAST_TERMINAL_DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_FAST_TERMINAL_INPUT_INVALID")
    return json.loads(
        path.read_text("utf-8"),
        object_pairs_hook=reject,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_FAST_TERMINAL_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("CATALOG_FAST_TERMINAL_TIME_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CATALOG_FAST_TERMINAL_TIME_INVALID")
    return parsed.astimezone(timezone.utc)


def _job_rows(value: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        raw = value.get("jobs")
        pages: Sequence[object] = (value,)
    elif isinstance(value, list):
        pages = value
        raw = None
    else:
        raise ValueError("CATALOG_FAST_TERMINAL_JOBS_INVALID")
    rows: list[Mapping[str, Any]] = []
    for page in pages:
        page_map = _mapping(page, "CATALOG_FAST_TERMINAL_JOBS_INVALID")
        page_rows = page_map.get("jobs")
        if not isinstance(page_rows, list):
            raise ValueError("CATALOG_FAST_TERMINAL_JOBS_INVALID")
        rows.extend(
            _mapping(item, "CATALOG_FAST_TERMINAL_JOBS_INVALID")
            for item in page_rows
        )
    if raw is not None and not isinstance(raw, list):
        raise ValueError("CATALOG_FAST_TERMINAL_JOBS_INVALID")
    return tuple(rows)


def _span_seconds(
    jobs: tuple[Mapping[str, Any], ...],
    markers: tuple[str, ...],
) -> float | None:
    intervals: list[tuple[datetime, datetime]] = []
    for job in jobs:
        name = str(job.get("name", "")).casefold()
        if not any(marker in name for marker in markers):
            continue
        started = job.get("started_at")
        completed = job.get("completed_at")
        if started is None or completed is None:
            if job.get("conclusion") == "skipped":
                continue
            return None
        try:
            begin = _utc(started)
            end = _utc(completed)
        except ValueError:
            return None
        if end >= begin:
            intervals.append((begin, end))
        else:
            return None
    if not intervals:
        return None
    return max(0.0, (max(end for _, end in intervals) - min(begin for begin, _ in intervals)).total_seconds())


def _timing_diagnostics(run: Mapping[str, Any], jobs: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    codes: set[str] = set()
    try:
        created = _utc(run.get("created_at"))
    except ValueError:
        created = None
        codes.add("TIMING_METADATA_INVALID" if run.get("created_at") else "TIMING_METADATA_MISSING")
    for job in jobs:
        if job.get("conclusion") == "skipped":
            continue
        if not job.get("started_at") or not job.get("completed_at"):
            codes.add("TIMING_METADATA_MISSING")
            continue
        try:
            start, end = _utc(job["started_at"]), _utc(job["completed_at"])
        except ValueError:
            codes.add("TIMING_METADATA_INVALID")
            continue
        if end < start or (created is not None and start < created):
            codes.add("CLOCK_SKEW")
    return tuple(sorted(codes))


def _failure_class(reason_code: str) -> str:
    request_reasons = {
        "CATALOG_REQUEST_ALREADY_TERMINAL",
        "CATALOG_REQUEST_EXPIRED",
        "CATALOG_REQUEST_TIME_INVALID",
        "CATALOG_CAMPAIGN_NOT_REGISTERED",
    }
    if reason_code in request_reasons:
        return "request"
    if "SCIENT" in reason_code:
        return "scientific"
    return "infrastructure"


def finalize_fast_run(
    *,
    request_context_path: Path,
    decision_path: Path,
    run_path: Path,
    jobs_path: Path,
    engine_outcome_path: Path | None,
    science_index_path: Path | None,
    output_path: Path,
    comment_output_path: Path,
    github_output: Path,
    gate_result: str | None = None,
) -> CatalogTerminalReceiptV2:
    if gate_result not in {None, "success", "failure", "cancelled", "skipped"}:
        raise ValueError("CATALOG_FAST_TERMINAL_GATE_RESULT_INVALID")
    context = _mapping(
        _strict_json(request_context_path),
        "CATALOG_FAST_REQUEST_CONTEXT_INVALID",
    )
    context_identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if context.get("content_sha256") != canonical_sha256(context_identity):
        raise ValueError("CATALOG_FAST_REQUEST_CONTEXT_INVALID")
    request = CatalogRunRequestV1.model_validate(context.get("request"))
    decision = CatalogFastLaunchDecisionV1.model_validate(_strict_json(decision_path))
    if (
        decision.request_sha256 != request.request_sha256
        or decision.submission_key_sha256 != request.submission_key_sha256
        or decision.campaign_key != request.campaign_key
    ):
        raise ValueError("CATALOG_FAST_TERMINAL_BINDING_INVALID")
    if decision.existing_run_id is not None:
        # Adoption only reads the original owner's result. A replay must never
        # produce another terminal receipt or close the owner's request.
        raise ValueError("CATALOG_FAST_TERMINAL_NOT_RUN_OWNER")
    expected_count = context.get("logical_recipe_count")
    if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 1:
        raise ValueError("CATALOG_FAST_TERMINAL_COUNT_INVALID")
    run = _mapping(_strict_json(run_path), "CATALOG_FAST_TERMINAL_RUN_INVALID")
    run_id = run.get("id")
    run_url = run.get("html_url")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
        raise ValueError("CATALOG_FAST_TERMINAL_RUN_INVALID")
    if not isinstance(run_url, str) or not run_url.startswith("https://"):
        raise ValueError("CATALOG_FAST_TERMINAL_RUN_INVALID")
    jobs = _job_rows(_strict_json(jobs_path))
    timing_diagnostics = _timing_diagnostics(run, jobs)
    try:
        created_at = _utc(run.get("created_at"))
        starts = [_utc(row["started_at"]) for row in jobs if row.get("started_at")]
        queue_seconds = (min(starts) - created_at).total_seconds() if starts else None
    except ValueError:
        queue_seconds = None
    if queue_seconds is not None and queue_seconds < 0:
        queue_seconds = None

    outcome = None
    if engine_outcome_path is not None and engine_outcome_path.is_file():
        outcome = CatalogEngineOutcomeV1.model_validate(_strict_json(engine_outcome_path))
        if outcome.request_sha256 != request.request_sha256 or outcome.engine_run_id != run_id:
            raise ValueError("CATALOG_FAST_TERMINAL_ENGINE_BINDING_INVALID")

    observed_count = 0
    result_science_sha256 = None
    science_verified = False
    science_error = None
    worker_evaluation_seconds = None
    recovered_block_ids = None
    if (outcome is not None and outcome.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE
            and science_index_path is not None and science_index_path.is_file()):
        try:
            science = _mapping(
                _strict_json(science_index_path),
                "CATALOG_FAST_TERMINAL_SCIENCE_INVALID",
            )
            science_identity = {key: value for key, value in science.items() if key != "index_sha256"}
            if (
                science.get("index_sha256") != canonical_sha256(science_identity)
                or science.get("request_sha256") != request.request_sha256
                or science.get("science_sha256") != outcome.science_sha256
            ):
                raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
            files = science.get("files")
            if not isinstance(files, list):
                raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
            seen: set[str] = set()
            for raw in files:
                row = _mapping(raw, "CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
                relative = row.get("path")
                if (
                    not isinstance(relative, str)
                    or relative in seen
                    or Path(relative).is_absolute()
                    or ".." in Path(relative).parts
                ):
                    raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
                target = science_index_path.parent / relative
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or target.stat().st_size != row.get("size_bytes")
                    or hashlib.sha256(target.read_bytes()).hexdigest()
                    != row.get("sha256")
                ):
                    raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
                seen.add(relative)
            audit_path = science_index_path.parent / "catalog_scientific_audit_receipt_v1.json"
            if audit_path.name not in seen:
                raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
            audit = _mapping(
                _strict_json(audit_path),
                "CATALOG_FAST_TERMINAL_SCIENCE_INVALID",
            )
            audit_identity = {key: value for key, value in audit.items() if key != "receipt_sha256"}
            if audit.get("receipt_sha256") != canonical_sha256(audit_identity):
                raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
            metrics = audit.get("execution_metrics")
            if audit_path.name in seen:
                recovery = aggregate_recovery_metrics([audit])
                if recovery is not None:
                    recovered_block_ids = tuple(recovery["recovered_block_ids"])
            if isinstance(metrics, Mapping):
                measured = metrics.get("worker_evaluation_seconds")
                if (audit_path.name in seen and metrics.get("schema_version") == "1"
                        and metrics.get("basis") == "sum_of_verified_worker_evaluation_durations"
                        and isinstance(measured, (int, float)) and not isinstance(measured, bool)
                        and math.isfinite(measured) and measured >= 0):
                    worker_evaluation_seconds = float(measured)
            observed_count = int(audit.get("strategy_count", 0))
            result_science_sha256 = str(audit.get("scientific_results_sha256", ""))
            science_verified = True
        except (ValueError, TypeError, OSError) as exc:
            # Only science decoding/validation is contained here. Request and
            # owner validation above must still fail without issuing a receipt.
            code = str(exc)
            science_error = code if code.startswith("CATALOG_FAST_TERMINAL_") else "CATALOG_FAST_TERMINAL_SCIENCE_INVALID"
            observed_count = 0
            result_science_sha256 = None
            worker_evaluation_seconds = None
            recovered_block_ids = None

    if decision.state == "BLOCKED":
        state = "BLOCKED"
        reason_code = decision.reason_code
        failure_class = _failure_class(reason_code)
    elif gate_result in {"failure", "cancelled", "skipped"}:
        state = "BLOCKED"
        reason_code = "CATALOG_GATE_CANCELLED" if gate_result == "cancelled" else "CATALOG_GATE_PUBLICATION_FAILED"
        failure_class = "infrastructure"
    elif outcome is None:
        state = "BLOCKED"
        reason_code = "CATALOG_ENGINE_OUTCOME_MISSING"
        failure_class = "infrastructure"
    elif science_error is not None:
        state = "BLOCKED"
        reason_code = science_error
        failure_class = "scientific"
    elif outcome.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE and not science_verified:
        state = "BLOCKED"
        reason_code = "CATALOG_FAST_TERMINAL_SCIENCE_MISSING"
        failure_class = "infrastructure"
    elif outcome.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE:
        state = "SUCCESS"
        reason_code = "CATALOG_RUN_SUCCESS"
        failure_class = None
    else:
        state = "BLOCKED"
        reason_code = outcome.reason_code
        failure_class = _failure_class(reason_code)

    receipt = CatalogTerminalReceiptV2.create(
        state=state,
        reason_code=reason_code,
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256=decision.prepared_receipt_sha256,
        engine_run_id=run_id if decision.launch_required else None,
        run_url=run_url if decision.launch_required else None,
        expected_recipe_count=expected_count,
        observed_recipe_count=observed_count,
        timing=dict(
        initial_queue_seconds=queue_seconds,
        preparation_jobs_window_seconds=_span_seconds(
            jobs,
            ("engine_verify_sealed_plan", "prepare_runtime_and_inputs", "verify_component_store"),
        ),
        evaluation_jobs_window_seconds=_span_seconds(jobs, ("evaluate_a", "evaluate_b", "evaluate_c")),
        recovery_jobs_window_seconds=_span_seconds(jobs, ("reconcile_wave_0", "recovery_wave_")),
        reduction_jobs_window_seconds=_span_seconds(
            jobs,
            ("ready_to_merge", "reduce_groups", " / reduce / ", "verify_terminal_science"),
        ),
        worker_evaluation_seconds=worker_evaluation_seconds,
        ),
        recovered_block_ids=recovered_block_ids,
        failure_class=failure_class,
        result_science_sha256=result_science_sha256,
        created_at=datetime.now(timezone.utc),
    )
    comment = {
        "body": (
            "## AURORA catalog fast path\n\n"
            f"- State: `{receipt.state}`\n"
            f"- Reason: `{receipt.reason_code}`\n"
            f"- Progress: `{receipt.observed_recipe_count}/{receipt.expected_recipe_count}`\n"
            f"- Timing diagnostics: {', '.join(timing_diagnostics) if timing_diagnostics else 'none'}\n"
            f"- Initial queue: {_duration_text(receipt.timing.initial_queue_seconds)}\n"
            f"- Setup jobs window: {_duration_text(receipt.timing.preparation_jobs_window_seconds)}\n"
            f"- Evaluation jobs window: {_duration_text(receipt.timing.evaluation_jobs_window_seconds)}\n"
            "- Worker evaluation (aggregate): "
            + (f"`{worker_evaluation_seconds:.3f}s`\n" if worker_evaluation_seconds is not None else "unavailable\n")
            +
            f"- Recovery jobs window: {_duration_text(receipt.timing.recovery_jobs_window_seconds)}\n"
            f"- Reduction jobs window: {_duration_text(receipt.timing.reduction_jobs_window_seconds)}\n"
            f"- Recovered blocks: {receipt.recovered_block_count if receipt.recovered_block_count is not None else 'unavailable'}\n"
            f"- Receipt: `{receipt.receipt_sha256}`"
        )
    }
    try:
        output_path.write_text(
            json.dumps(receipt.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        comment_output_path.write_text(
            json.dumps(comment, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with github_output.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"terminal_state={receipt.state}\n")
            stream.write(f"terminal_reason_code={receipt.reason_code}\n")
            stream.write(f"terminal_receipt_sha256={receipt.receipt_sha256}\n")
    except OSError as exc:
        # A failed publication is not a new scientific outcome or permission
        # to release the reservation. Let existing reconciliation read evidence.
        print(json.dumps({
            "reason_code": "CATALOG_FAST_TERMINAL_PUBLICATION_FAILED",
            "primary_reason_code": receipt.reason_code,
            "request_sha256": receipt.request_sha256,
            "receipt_sha256": receipt.receipt_sha256,
            "reservation_release_allowed": False,
            "os_error_number": exc.errno,
        }, sort_keys=True), file=sys.stderr)
        raise ValueError("CATALOG_FAST_TERMINAL_PUBLICATION_FAILED") from exc
    return receipt


def _duration_text(value: float | None) -> str:
    return "unavailable" if value is None else f"`{value:.3f}s`"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        finalize_fast_run(
            request_context_path=args.request_context,
            decision_path=args.decision,
            run_path=args.run,
            jobs_path=args.jobs,
            engine_outcome_path=args.engine_outcome,
            science_index_path=args.science_index,
            output_path=args.output,
            comment_output_path=args.comment_output,
            github_output=args.github_output,
            gate_result=args.gate_result,
        )
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

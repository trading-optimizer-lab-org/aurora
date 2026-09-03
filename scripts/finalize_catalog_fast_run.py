#!/usr/bin/env python3
"""Create the one terminal receipt for a fast catalog request."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
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
    CatalogTerminalReceiptV1,
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
) -> float:
    intervals: list[tuple[datetime, datetime]] = []
    for job in jobs:
        name = str(job.get("name", "")).casefold()
        if not any(marker in name for marker in markers):
            continue
        started = job.get("started_at")
        completed = job.get("completed_at")
        if started is None or completed is None:
            continue
        begin = _utc(started)
        end = _utc(completed)
        if end >= begin:
            intervals.append((begin, end))
    if not intervals:
        return 0.0
    return max(0.0, (max(end for _, end in intervals) - min(begin for begin, _ in intervals)).total_seconds())


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
) -> CatalogTerminalReceiptV1:
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
    created_at = _utc(run.get("created_at"))
    starts = [_utc(row["started_at"]) for row in jobs if row.get("started_at")]
    queue_seconds = max(0.0, (min(starts) - created_at).total_seconds()) if starts else 0.0

    outcome = None
    if engine_outcome_path is not None and engine_outcome_path.is_file():
        outcome = CatalogEngineOutcomeV1.model_validate(_strict_json(engine_outcome_path))
        if outcome.request_sha256 != request.request_sha256 or outcome.engine_run_id != run_id:
            raise ValueError("CATALOG_FAST_TERMINAL_ENGINE_BINDING_INVALID")

    observed_count = 0
    result_science_sha256 = None
    if outcome is not None and outcome.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE:
        if science_index_path is None:
            raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_MISSING")
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
        audit = _mapping(
            _strict_json(audit_path),
            "CATALOG_FAST_TERMINAL_SCIENCE_INVALID",
        )
        audit_identity = {key: value for key, value in audit.items() if key != "receipt_sha256"}
        if audit.get("receipt_sha256") != canonical_sha256(audit_identity):
            raise ValueError("CATALOG_FAST_TERMINAL_SCIENCE_INVALID")
        observed_count = int(audit.get("strategy_count", 0))
        result_science_sha256 = str(audit.get("scientific_results_sha256", ""))

    if decision.state == "BLOCKED":
        state = "BLOCKED"
        reason_code = decision.reason_code
        failure_class = _failure_class(reason_code)
    elif outcome is None:
        state = "BLOCKED"
        reason_code = "CATALOG_ENGINE_OUTCOME_MISSING"
        failure_class = "infrastructure"
    elif outcome.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE:
        state = "SUCCESS"
        reason_code = "CATALOG_RUN_SUCCESS"
        failure_class = None
    else:
        state = "BLOCKED"
        reason_code = outcome.reason_code
        failure_class = _failure_class(reason_code)

    receipt = CatalogTerminalReceiptV1.create(
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
        queue_seconds=queue_seconds,
        preparation_seconds=_span_seconds(
            jobs,
            ("engine_verify_sealed_plan", "prepare_runtime_and_inputs", "verify_component_store"),
        ),
        computation_seconds=_span_seconds(jobs, ("evaluate_a", "evaluate_b", "evaluate_c")),
        recovery_seconds=_span_seconds(jobs, ("reconcile_wave_0", "recovery_wave_")),
        reduction_seconds=_span_seconds(
            jobs,
            ("ready_to_merge", "reduce_groups", " / reduce / ", "verify_terminal_science"),
        ),
        recovered_block_count=(
            sum(item in {"retry", "replan"} for item in outcome.recovery_statuses)
            if outcome is not None
            else 0
        ),
        failure_class=failure_class,
        result_science_sha256=result_science_sha256,
        created_at=datetime.now(timezone.utc),
    )
    output_path.write_text(
        json.dumps(receipt.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    comment = {
        "body": (
            "## AURORA catalog fast path\n\n"
            f"- State: `{receipt.state}`\n"
            f"- Reason: `{receipt.reason_code}`\n"
            f"- Progress: `{receipt.observed_recipe_count}/{receipt.expected_recipe_count}`\n"
            f"- Queue: `{receipt.queue_seconds:.3f}s`\n"
            f"- Setup verification: `{receipt.preparation_seconds:.3f}s`\n"
            f"- Compute: `{receipt.computation_seconds:.3f}s`\n"
            f"- Recovery: `{receipt.recovery_seconds:.3f}s`\n"
            f"- Reduction: `{receipt.reduction_seconds:.3f}s`\n"
            f"- Receipt: `{receipt.receipt_sha256}`"
        )
    }
    comment_output_path.write_text(
        json.dumps(comment, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(f"terminal_state={receipt.state}\n")
        stream.write(f"terminal_reason_code={receipt.reason_code}\n")
        stream.write(f"terminal_receipt_sha256={receipt.receipt_sha256}\n")
    return receipt


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
        )
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

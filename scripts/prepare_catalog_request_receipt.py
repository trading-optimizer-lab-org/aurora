#!/usr/bin/env python3
"""Prepare one provenance-bound, mirror-first catalog request receipt."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_authority_ledger import (  # noqa: E402
    AuthorityState,
    CatalogAuthorityRecordV1,
)
from aurora.infra.sp500_megarun.catalog_authority_writer import (  # noqa: E402
    CatalogAuthorityTransitionCandidateV1,
    catalog_authority_writer_context_from_github,
)
from aurora.infra.sp500_megarun.catalog_engine_outcome import (  # noqa: E402
    CatalogEngineOutcomeV1,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (  # noqa: E402
    CatalogGitHubReadOnlyClient,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (  # noqa: E402
    canonical_model_bytes,
)
from aurora.infra.sp500_megarun.catalog_request_receipt import (  # noqa: E402
    REQUEST_RECEIPT_MARKER,
    CatalogRequestReceiptV1,
    build_nonexecuting_request_receipt,
    build_waiting_retry_request_receipt,
    next_request_receipt_sequence,
    parse_request_receipt_comment,
)
from aurora.infra.sp500_megarun.catalog_routing import (  # noqa: E402
    CatalogRoutingCommandV1,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_SAFE_OUTPUT = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_ACTIVE = frozenset(
    {
        AuthorityState.RESERVED,
        AuthorityState.RUNNING,
        AuthorityState.RECOVERING,
        AuthorityState.WAITING_RETRY,
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a request receipt without writing to GitHub."
    )
    parser.add_argument(
        "--mode", choices=("nonexecuting", "waiting-retry"), required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--decision-outcome")
    parser.add_argument("--reason-code")
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--request-sha256")
    parser.add_argument("--campaign-id")
    parser.add_argument("--authority-id")
    parser.add_argument("--retry-not-before")
    parser.add_argument("--routing-command", type=Path)
    parser.add_argument("--request-receipts", type=Path)
    parser.add_argument("--authority-candidate", type=Path)
    parser.add_argument("--engine-outcome", type=Path)
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_REQUEST_RECEIPT_JSON_DUPLICATE")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_REQUEST_RECEIPT_JSON_NONFINITE:{value}")


def _read_json(path: Path, *, runner_temp: Path) -> object:
    if path.is_symlink():
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(runner_temp):
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
    return json.loads(
        resolved.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


def _positive_env(name: str) -> int:
    value = os.environ.get(name, "")
    if not value.isdigit() or int(value) < 1:
        raise ValueError("CATALOG_REQUEST_RECEIPT_ENVIRONMENT_INVALID")
    return int(value)


def _current_writer(*, expected_job: str, expected_commit: str):
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if (
        repository != _REPOSITORY
        or not token
        or os.environ.get("GITHUB_JOB") != expected_job
        or os.environ.get("GITHUB_SHA") != expected_commit
        or not _COMMIT.fullmatch(expected_commit)
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_ENVIRONMENT_INVALID")
    run_id = _positive_env("GITHUB_RUN_ID")
    run_attempt = _positive_env("GITHUB_RUN_ATTEMPT")
    client = CatalogGitHubReadOnlyClient(repository, token)
    run, _ = client.get_json(f"/repos/{repository}/actions/runs/{run_id}")
    jobs = client.stable_paginated(
        f"/repos/{repository}/actions/runs/{run_id}/jobs",
        root="jobs",
    )
    if not isinstance(run, dict) or client.observed_at is None:
        raise ValueError("CATALOG_REQUEST_RECEIPT_WRITER_INVALID")
    return catalog_authority_writer_context_from_github(
        run=run,
        jobs=jobs.collection.rows,
        expected_run_id=run_id,
        expected_run_attempt=run_attempt,
        expected_job_id=expected_job,
        expected_protected_commit_sha=expected_commit,
        observed_at=client.observed_at,
    )


def _latest_authority(
    command: CatalogRoutingCommandV1,
    authority_id: str | None,
) -> CatalogAuthorityRecordV1 | None:
    if not authority_id:
        return None
    try:
        expected = UUID(authority_id)
    except ValueError:
        raise ValueError("CATALOG_REQUEST_RECEIPT_AUTHORITY_INVALID") from None
    matches = [row for row in command.ledger.records if row.authority_id == expected]
    if not matches:
        raise ValueError("CATALOG_REQUEST_RECEIPT_AUTHORITY_INVALID")
    return matches[-1]


def _sequence_from_document(
    path: Path,
    *,
    runner_temp: Path,
    issue_number: int,
    request_sha256: str,
) -> int:
    document = _read_json(path, runner_temp=runner_temp)
    if not isinstance(document, dict) or any(
        document.get(flag) is not True
        for flag in ("complete", "stable", "sequence_valid")
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    rows = document.get("receipts")
    trusted_hashes = document.get("trusted_receipt_sha256s")
    if not isinstance(rows, list) or not isinstance(trusted_hashes, list):
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    trusted = set(trusted_hashes)
    receipts: list[CatalogRequestReceiptV1] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("receipt") is None:
            continue
        receipt = CatalogRequestReceiptV1.model_validate(row["receipt"])
        if receipt.receipt_sha256 in trusted:
            receipts.append(receipt)
    sequence = next_request_receipt_sequence(
        receipts,
        issue_number=issue_number,
        request_sha256=request_sha256,
    )
    if document.get("next_delivery_sequence") != sequence:
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    return sequence


def _live_sequence(*, issue_number: int, request_sha256: str) -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    if repository != _REPOSITORY or not token:
        raise ValueError("CATALOG_REQUEST_RECEIPT_ENVIRONMENT_INVALID")
    client = CatalogGitHubReadOnlyClient(repository, token)
    snapshot = client.stable_paginated(
        f"/repos/{repository}/issues/{issue_number}/comments",
        root="list",
    )
    receipts: list[CatalogRequestReceiptV1] = []
    for comment in snapshot.collection.rows:
        body = comment.get("body")
        user = comment.get("user")
        author = user.get("login") if isinstance(user, dict) else None
        if (
            isinstance(body, str)
            and REQUEST_RECEIPT_MARKER in body
            and author == "github-actions[bot]"
        ):
            receipt = parse_request_receipt_comment(
                comment,
                expected_author="github-actions[bot]",
            )
            if receipt is None:
                raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
            receipts.append(receipt)
    return next_request_receipt_sequence(
        receipts,
        issue_number=issue_number,
        request_sha256=request_sha256,
    )


def _delivery_sequence(
    args: argparse.Namespace,
    *,
    runner_temp: Path,
    issue_number: int,
    request_sha256: str,
) -> int:
    if args.request_receipts is not None:
        return _sequence_from_document(
            args.request_receipts,
            runner_temp=runner_temp,
            issue_number=issue_number,
            request_sha256=request_sha256,
        )
    return _live_sequence(
        issue_number=issue_number,
        request_sha256=request_sha256,
    )


def _nonexecuting_summary(*, state: str, reason_code: str) -> str:
    if state == "DEFERRED":
        return (
            "La solicitud queda en espera sin iniciar trabajo nuevo.\n\n"
            f"Motivo: `{reason_code}`.\n"
            "GitHub volverá a revisarla automáticamente."
        )
    if state == "SUCCESS":
        return (
            "La solicitud queda enlazada a un resultado existente ya verificado.\n\n"
            f"Motivo: `{reason_code}`."
        )
    if state == "FAILED":
        return (
            "La solicitud queda enlazada a un resultado fallido ya verificado.\n\n"
            f"Motivo: `{reason_code}`."
        )
    return (
        "La solicitud ha quedado bloqueada antes de iniciar trabajo nuevo.\n\n"
        f"Motivo: `{reason_code}`.\n"
        "No se ha lanzado ningún run de catálogo."
    )


def _prepare_nonexecuting(
    args: argparse.Namespace,
    *,
    runner_temp: Path,
) -> tuple[CatalogRequestReceiptV1, str, bool]:
    outcome = str(args.decision_outcome or "blocked").casefold()
    reason = str(args.reason_code or "CATALOG_REQUEST_BLOCKED")
    campaign_id = args.campaign_id or None
    if (
        args.issue_number is None
        or args.issue_number < 1
        or not _SHA256.fullmatch(str(args.request_sha256 or ""))
        or not _REASON.fullmatch(reason)
        or (campaign_id and not _SHA256.fullmatch(campaign_id))
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
    command = None
    if args.routing_command is not None:
        command = CatalogRoutingCommandV1.model_validate(
            _read_json(args.routing_command, runner_temp=runner_temp)
        )
        if (
            command.request_issue_number != args.issue_number
            or command.request_sha256 != args.request_sha256
            or (campaign_id and command.campaign_id != campaign_id)
        ):
            raise ValueError("CATALOG_REQUEST_RECEIPT_ROUTING_BINDING_INVALID")
    record = None if command is None else _latest_authority(command, args.authority_id)
    if outcome == "adopted":
        if record is None:
            raise ValueError("CATALOG_REQUEST_RECEIPT_AUTHORITY_INVALID")
        if record.state in _ACTIVE:
            state = "DEFERRED"
            reason = "CATALOG_ADOPTED_WAITING_FOR_EXISTING"
        else:
            state = record.state.value.upper()
            reason = record.reason_code or reason
    elif outcome == "deferred":
        state = "DEFERRED"
        record = None
    elif outcome == "blocked":
        state = "BLOCKED"
        record = None
    elif outcome in {"eligible", "admitted"}:
        state = "BLOCKED"
        reason = "CATALOG_ADMISSION_NOT_COMPLETED"
        record = None
    else:
        raise ValueError("CATALOG_REQUEST_RECEIPT_OUTCOME_INVALID")
    commit = os.environ.get("GITHUB_SHA", "")
    writer = _current_writer(
        expected_job="report_nonexecuting_decision",
        expected_commit=commit,
    )
    retry_not_before = None
    if state == "DEFERRED" and reason != "CATALOG_ADOPTED_WAITING_FOR_EXISTING":
        if args.retry_not_before:
            try:
                retry_not_before = datetime.fromisoformat(
                    str(args.retry_not_before).replace("Z", "+00:00")
                )
            except ValueError:
                raise ValueError("CATALOG_REQUEST_RECEIPT_RETRY_INVALID") from None
            if (
                retry_not_before.tzinfo is None
                or retry_not_before.utcoffset() is None
            ):
                raise ValueError("CATALOG_REQUEST_RECEIPT_RETRY_INVALID")
            retry_not_before = retry_not_before.astimezone(UTC)
        else:
            retry_not_before = writer.observed_at + timedelta(minutes=15)
    summary = _nonexecuting_summary(state=state, reason_code=reason)
    delivery_sequence = _delivery_sequence(
        args,
        runner_temp=runner_temp,
        issue_number=args.issue_number,
        request_sha256=args.request_sha256,
    )
    receipt = build_nonexecuting_request_receipt(
        state=state,
        reason_code=reason,
        issue_number=args.issue_number,
        request_sha256=args.request_sha256,
        campaign_id=(record.campaign_id if record is not None else campaign_id),
        authority_record=record,
        writer=writer,
        retry_not_before=retry_not_before,
        summary=summary,
        delivery_sequence=delivery_sequence,
    )
    return receipt, summary, state in {"SUCCESS", "FAILED", "BLOCKED"}


def _prepare_waiting(
    args: argparse.Namespace,
    *,
    runner_temp: Path,
) -> tuple[CatalogRequestReceiptV1, str, bool]:
    if args.authority_candidate is None or args.engine_outcome is None:
        raise ValueError("CATALOG_REQUEST_RECEIPT_INPUT_INVALID")
    candidate = CatalogAuthorityTransitionCandidateV1.model_validate(
        _read_json(args.authority_candidate, runner_temp=runner_temp)
    )
    outcome = CatalogEngineOutcomeV1.model_validate(
        _read_json(args.engine_outcome, runner_temp=runner_temp)
    )
    writer = _current_writer(
        expected_job="record_nonterminal_wait",
        expected_commit=candidate.record.protected_commit_sha,
    )
    if (
        writer.run_id != candidate.record.run_id
        or writer.run_attempt != candidate.record.run_attempt
        or writer.writer_job_database_id != candidate.record.writer_job_database_id
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_WRITER_INVALID")
    retry_at = outcome.retry_not_before
    if retry_at is None:
        raise ValueError("CATALOG_REQUEST_RECEIPT_WAITING_BINDING_INVALID")
    summary = (
        "El run queda en espera sin perder el trabajo válido ya realizado.\n\n"
        f"Motivo: `{outcome.reason_code}`.\n"
        "Reanudación automática no antes de: "
        f"`{retry_at.isoformat().replace('+00:00', 'Z')}`."
    )
    return (
        build_waiting_retry_request_receipt(
            authority_candidate=candidate,
            engine_outcome=outcome,
            summary=summary,
            delivery_sequence=_delivery_sequence(
                args,
                runner_temp=runner_temp,
                issue_number=candidate.record.request_issue_number,
                request_sha256=candidate.record.request_sha256,
            ),
        ),
        summary,
        False,
    )


def _append_outputs(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    if path.is_symlink() or any(
        not _SAFE_OUTPUT.fullmatch(value) for value in values.values()
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_GITHUB_OUTPUT_INVALID")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def prepare(args: argparse.Namespace) -> dict[str, str]:
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    if not runner_temp_raw:
        raise ValueError("CATALOG_REQUEST_RECEIPT_ENVIRONMENT_INVALID")
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    output = args.output_dir.resolve(strict=False)
    if (
        args.output_dir.exists()
        or args.output_dir.is_symlink()
        or not output.is_relative_to(runner_temp)
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_OUTPUT_INVALID")
    if args.mode == "nonexecuting":
        receipt, summary, close_request = _prepare_nonexecuting(
            args, runner_temp=runner_temp
        )
    else:
        receipt, summary, close_request = _prepare_waiting(
            args, runner_temp=runner_temp
        )
    args.output_dir.mkdir(parents=False, exist_ok=False)
    (args.output_dir / "request-receipt.json").write_bytes(
        canonical_model_bytes(receipt) + b"\n"
    )
    (args.output_dir / "comment.md").write_text(
        receipt.comment_body(summary), encoding="utf-8", newline="\n"
    )
    if close_request:
        (args.output_dir / "terminal-issue-patch.json").write_text(
            json.dumps(
                {
                    "labels": ["catalog-run-terminal-v1"],
                    "state": "closed",
                    "state_reason": "completed",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    values = {
        "artifact_name": receipt.artifact_name,
        "receipt_sha256": receipt.receipt_sha256,
        "issue_number": str(receipt.issue_number),
        "receipt_state": receipt.state,
        "close_request": str(close_request).lower(),
    }
    _append_outputs(args.github_output, values)
    return values


def main(argv: list[str] | None = None) -> int:
    try:
        values = prepare(_parser().parse_args(argv))
        print(json.dumps(values, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

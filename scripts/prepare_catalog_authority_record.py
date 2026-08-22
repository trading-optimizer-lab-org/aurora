#!/usr/bin/env python3
"""Prepare one catalog authority record from fresh GET-only GitHub evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.sp500_megarun.catalog_authority_writer import (  # noqa: E402
    catalog_authority_writer_context_from_github,
    prepare_catalog_authority_transition,
    prepare_catalog_terminal_transition,
)
from aurora.infra.sp500_megarun.catalog_controller import (  # noqa: E402
    CatalogControllerDecisionV1,
)
from aurora.infra.sp500_megarun.catalog_controller_reporting import (  # noqa: E402
    CatalogTerminalDecisionV1,
)
from aurora.infra.sp500_megarun.catalog_github_controls import (  # noqa: E402
    AuditorCatalogGithubControlsReceiptV1,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (  # noqa: E402
    CatalogGitHubReadOnlyClient,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (  # noqa: E402
    canonical_model_bytes,
)
from aurora.infra.sp500_megarun.catalog_routing import (  # noqa: E402
    CatalogRoutingCommandV1,
)


_SAFE_OUTPUT = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_MODE_TO_JOB = {
    "reserve": "reserve",
    "running": "record_running",
    "waiting_retry": "record_nonterminal_wait",
    "terminal": "finalize",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare one mirror-first authority record. This command performs "
            "GET requests only and never writes to GitHub."
        )
    )
    parser.add_argument("--mode", choices=tuple(_MODE_TO_JOB), required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--routing-command", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--evidence-sha256")
    parser.add_argument("--failure-fingerprint")
    parser.add_argument("--failure-occurrence-count", type=int)
    parser.add_argument("--reason-code")
    parser.add_argument("--terminal-decision", type=Path)
    parser.add_argument("--terminal-controls", type=Path)
    parser.add_argument("--audit-context-sha256")
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_AUTHORITY_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_AUTHORITY_JSON_NONFINITE:{value}")


def _read_json(path: Path, *, runner_temp: Path) -> object:
    if path.is_symlink():
        raise ValueError("CATALOG_AUTHORITY_INPUT_INVALID")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(runner_temp):
        raise ValueError("CATALOG_AUTHORITY_INPUT_INVALID")
    return json.loads(
        resolved.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


def _positive_int(name: str) -> int:
    value = os.environ.get(name, "")
    if not value.isdigit() or int(value) < 1:
        raise ValueError("CATALOG_AUTHORITY_WRITER_ENVIRONMENT_INVALID")
    return int(value)


def _append_outputs(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    if path.is_symlink() or any(not _SAFE_OUTPUT.fullmatch(value) for value in values.values()):
        raise ValueError("CATALOG_AUTHORITY_GITHUB_OUTPUT_INVALID")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def prepare(args: argparse.Namespace) -> dict[str, str]:
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    current_job = os.environ.get("GITHUB_JOB", "")
    if not runner_temp_raw or repository != "trading-optimizer-lab-org/aurora" or not token:
        raise ValueError("CATALOG_AUTHORITY_WRITER_ENVIRONMENT_INVALID")
    expected_job = _MODE_TO_JOB[args.mode]
    if current_job != expected_job:
        raise ValueError("CATALOG_AUTHORITY_WRITER_JOB_INVALID")
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    output = args.output_dir.resolve(strict=False)
    if (
        args.output_dir.exists()
        or args.output_dir.is_symlink()
        or not output.is_relative_to(runner_temp)
    ):
        raise ValueError("CATALOG_AUTHORITY_OUTPUT_INVALID")
    decision = CatalogControllerDecisionV1.model_validate(
        _read_json(args.decision, runner_temp=runner_temp)
    )
    command = CatalogRoutingCommandV1.model_validate(
        _read_json(args.routing_command, runner_temp=runner_temp)
    )
    if decision.sealed_inputs is None:
        raise ValueError("CATALOG_AUTHORITY_DECISION_BINDING_INVALID")
    run_id = _positive_int("GITHUB_RUN_ID")
    run_attempt = _positive_int("GITHUB_RUN_ATTEMPT")
    client = CatalogGitHubReadOnlyClient(repository, token)
    run, _ = client.get_json(f"/repos/{repository}/actions/runs/{run_id}")
    jobs = client.stable_paginated(
        f"/repos/{repository}/actions/runs/{run_id}/jobs",
        root="jobs",
    )
    if not isinstance(run, dict) or client.observed_at is None:
        raise ValueError("CATALOG_AUTHORITY_WRITER_PROVENANCE_INVALID")
    writer = catalog_authority_writer_context_from_github(
        run=run,
        jobs=jobs.collection.rows,
        expected_run_id=run_id,
        expected_run_attempt=run_attempt,
        expected_job_id=expected_job,
        expected_protected_commit_sha=decision.sealed_inputs.protected_commit_sha,
        observed_at=client.observed_at,
    )
    if args.mode == "terminal":
        if (
            args.terminal_decision is None
            or args.terminal_controls is None
            or args.audit_context_sha256 is None
        ):
            raise ValueError("CATALOG_TERMINAL_WRITER_INPUT_MISSING")
        terminal_decision = CatalogTerminalDecisionV1.model_validate(
            _read_json(args.terminal_decision, runner_temp=runner_temp)
        )
        terminal_controls = AuditorCatalogGithubControlsReceiptV1.model_validate(
            _read_json(args.terminal_controls, runner_temp=runner_temp)
        )
        candidate = prepare_catalog_terminal_transition(
            decision=decision,
            terminal_decision=terminal_decision,
            fresh_command=command,
            writer=writer,
            terminal_controls=terminal_controls,
            expected_audit_context_sha256=args.audit_context_sha256,
        )
    else:
        if any(
            value is not None
            for value in (
                args.terminal_decision,
                args.terminal_controls,
                args.audit_context_sha256,
            )
        ):
            raise ValueError("CATALOG_TERMINAL_WRITER_INPUT_UNEXPECTED")
        candidate = prepare_catalog_authority_transition(
            mode=args.mode,
            decision=decision,
            fresh_command=command,
            writer=writer,
            evidence_sha256=args.evidence_sha256,
            failure_fingerprint=args.failure_fingerprint,
            failure_occurrence_count=args.failure_occurrence_count,
            reason_code=args.reason_code,
        )
    args.output_dir.mkdir(parents=False, exist_ok=False)
    (args.output_dir / "candidate.json").write_bytes(
        canonical_model_bytes(candidate) + b"\n"
    )
    (args.output_dir / "record.json").write_bytes(
        canonical_model_bytes(candidate.record) + b"\n"
    )
    (args.output_dir / "comment.md").write_text(
        candidate.comment_body,
        encoding="utf-8",
        newline="\n",
    )
    values = {
        "append_required": str(candidate.append_required).lower(),
        "commit_allowed": str(candidate.commit_allowed_for_current_writer).lower(),
        "authority_committed": "false",
        "artifact_name": candidate.artifact_name,
        "record_sha256": candidate.record.record_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "authority_state": candidate.expected_state.value,
    }
    _append_outputs(args.github_output, values)
    return values


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        values = prepare(args)
        print(json.dumps(values, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

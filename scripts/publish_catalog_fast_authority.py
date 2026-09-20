#!/usr/bin/env python3
"""Stage one protected reservation publication; workflow uploads then verifies it."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_authority import load_lineage_transition
from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority, write_current_fast_authority
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1, REQUEST_MAX_AGE, parse_catalog_terminal_receipt
from aurora.infra.sp500_megarun.catalog_fast_reservation import load_fast_gate_owner
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient, CatalogGitHubSnapshotError
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.admit_catalog_fast_request import _download_owner_archive, _historical_owner_commit_approved, _strict_json, _reserve_new_fast_request
from scripts.verify_catalog_fast_authority import read_live_edit
from aurora.infra.sp500_megarun.catalog_gate_budget import gate_timeout


def _publisher_job(client: CatalogGitHubReadOnlyClient, run_id: int, attempt: int, commit: str, phase: str, issue_number: int | None = None) -> int:
    from aurora.infra.sp500_megarun.catalog_fast_authority_github import authority_publisher_job_name
    if phase not in {"bootstrap", "gate", "finalize", "reconcile",
                     "intake-signed", "intake-uncertain", "intake-published"}:
        raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_PHASE_INVALID")
    prefix = f"/repos/{client.repository}/actions/runs/{run_id}"
    run, _ = client.get_json(prefix)
    if (not isinstance(run, dict) or run.get("id") != run_id or run.get("run_attempt") != attempt
        or run.get("head_sha") != commit or run.get("head_branch") != "main"
        or run.get("repository", {}).get("full_name") != client.repository):
        raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_RUN_INVALID")
    expected_job = authority_publisher_job_name(run, commit=commit, phase=phase, issue_number=issue_number)
    # Only locate this job in this attempt; never enumerate historical runs.
    for page in range(1, 11):
        payload, _ = client.get_json(prefix + f"/attempts/{attempt}/jobs?per_page=100&page={page}")
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_JOB_INVALID")
        matches = [job for job in payload["jobs"] if job.get("name") == expected_job]
        if matches:
            if len(matches) != 1:
                raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_JOB_INVALID")
            job = matches[0]
            if (type(job.get("id")) is not int or job["id"] < 1 or job.get("run_id") != run_id
                or job.get("run_attempt") != attempt or job.get("head_sha") != commit or job.get("status") != "in_progress"):
                raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_JOB_INVALID")
            return job["id"]
        if len(payload["jobs"]) < 100:
            break
    raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_JOB_UNAVAILABLE")


def _require_unlaunched_terminal(*, client, repository, token, commit, number,
                                request, issue, context, decision, receipt, run_id, receipt_artifact_id):
    """A terminal without an engine can only close an expired, never-owned request."""
    try:
        created = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
        if (created.utcoffset() is None or issue["created_at"] != context.get("issue_created_at")
                or issue.get("state") != "open"
                or any(row.get("name") in {"catalog-run-active-v1", "catalog-run-terminal-v1"}
                       for row in issue.get("labels", ()))
                or decision.state != "BLOCKED" or decision.launch_required
                or decision.existing_run_id is not None or decision.selected_workers != 0
                or decision.reason_code == "CATALOG_FAST_EXISTING_RUN"
                or decision.reason_code.startswith("CATALOG_REQUEST_ALREADY_")
                or decision.expires_at != created + REQUEST_MAX_AGE
                or decision.decided_at <= created + REQUEST_MAX_AGE
                or receipt.created_at < decision.decided_at
                or receipt.state != "BLOCKED" or receipt.reason_code != decision.reason_code
                or receipt.engine_run_id is not None or receipt.run_url is not None
                or receipt.observed_recipe_count != 0 or receipt.result_science_sha256 is not None):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("CATALOG_FAST_AUTHORITY_UNLAUNCHED_TERMINAL_INVALID") from exc
    owner = load_fast_gate_owner(client=client, issue_number=number, request=request,
        approved_commits=frozenset({commit}),
        approve_historical_commit=lambda candidate: _historical_owner_commit_approved(client, candidate, commit),
        download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id))
    if owner is not None:
        raise ValueError("CATALOG_FAST_AUTHORITY_UNLAUNCHED_OWNER_EXISTS")
    inventory = client.stable_paginated(
        f"/repos/{repository}/actions/artifacts?name=catalog-terminal-receipt-{request.request_sha256}",
        root="artifacts")
    if (type(receipt_artifact_id) is not int or receipt_artifact_id < 1
            or inventory.stable is not True or inventory.collection.complete is not True
            or len(inventory.collection.rows) != 1
            or any(row.get("workflow_run", {}).get("id") != run_id
                   or row.get("workflow_run", {}).get("head_sha") != commit
                   or row.get("id") != receipt_artifact_id or row.get("expired") is not False
                   for row in inventory.collection.rows)):
        raise ValueError("CATALOG_FAST_AUTHORITY_UNLAUNCHED_TERMINAL_CONFLICT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--phase", choices=("gate", "finalize"), required=True)
    parser.add_argument("--request-context", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
        if (repository != "trading-optimizer-lab-org/aurora" or not token
            or not re.fullmatch(r"[0-9a-f]{40}", commit) or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_JOB") != args.phase):
            raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_ENVIRONMENT_INVALID")
        run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
        root = args.repo_root.resolve(strict=True)
        temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        paths: tuple[Path, ...] = (args.output, args.request_context, args.decision)
        if args.terminal_receipt is not None:
            paths += (args.terminal_receipt,)
        if args.github_output is not None:
            paths += (args.github_output,)
        if (args.phase == "finalize") != (args.terminal_receipt is not None):
            raise ValueError("CATALOG_FAST_AUTHORITY_TERMINAL_INPUT_INVALID")
        if (args.repo_root.is_symlink() or args.output.exists()
            or any(path.is_symlink() or not path.resolve(strict=False).is_relative_to(temp)
                   for path in paths)
            or not args.output.parent.is_dir()):
            raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_PATH_INVALID")
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
            text=True, timeout=10, check=False)
        if head.returncode != 0 or head.stdout.strip() != commit:
            raise ValueError("CATALOG_FAST_AUTHORITY_CHECKOUT_INVALID")
        anchor = _strict_json(root / "config/catalog_authority_anchor_v1.json")
        actors = _strict_json(root / "config/catalog_controller_actors_v1.json")
        context = _strict_json(args.request_context)
        if not isinstance(anchor, dict) or not isinstance(actors, dict) or not isinstance(context, dict):
            raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_INPUT_INVALID")
        if (context.get("protected_commit_sha") != commit
            or context.get("content_sha256") != canonical_sha256({k: v for k, v in context.items() if k != "content_sha256"})):
            raise ValueError("CATALOG_FAST_AUTHORITY_CONTEXT_INVALID")
        request = CatalogRunRequestV1.model_validate(context["request"])
        number = context["issue_number"]
        if type(number) is not int or number < 1:
            raise ValueError("CATALOG_FAST_AUTHORITY_REQUEST_INVALID")
        public_path = (root / actors["requester_public_key_path"]).resolve(strict=True)
        if not public_path.is_relative_to(root):
            raise ValueError("CATALOG_FAST_AUTHORITY_KEY_INVALID")
        client = CatalogGitHubReadOnlyClient(repository, token)
        issue, _ = client.get_json(f"/repos/{repository}/issues/{number}")
        if (not isinstance(issue, dict) or issue.get("number") != number
            or issue.get("user", {}).get("login") != context.get("actor")
            or context.get("actor") not in actors.get("request_actors", ())
            or not isinstance(issue.get("title"), str) or not isinstance(issue.get("body"), str)
            or parse_catalog_run_request(issue["title"], issue["body"], public_path.read_bytes()) != request):
            raise ValueError("CATALOG_FAST_AUTHORITY_REQUEST_INVALID")
        decision = CatalogFastLaunchDecisionV1.model_validate(_strict_json(args.decision))
        unlaunched_terminal = args.phase == "finalize" and not decision.launch_required
        if ((not decision.launch_required and not unlaunched_terminal) or decision.existing_run_id is not None
            or decision.request_sha256 != request.request_sha256
            or decision.submission_key_sha256 != request.submission_key_sha256
            or decision.campaign_key != request.campaign_key):
            raise ValueError("CATALOG_FAST_AUTHORITY_DECISION_INVALID")
        receipt = None
        if args.terminal_receipt is not None:
            receipt = parse_catalog_terminal_receipt(_strict_json(args.terminal_receipt))
            if (receipt.request_sha256 != request.request_sha256
                or receipt.submission_key_sha256 != request.submission_key_sha256
                or receipt.campaign_key != request.campaign_key
                or receipt.prepared_receipt_sha256 != decision.prepared_receipt_sha256
                or receipt.engine_run_id != (None if unlaunched_terminal else run_id)
                or receipt.run_url != (None if unlaunched_terminal else f"https://github.com/{repository}/actions/runs/{run_id}")
                or receipt.expected_recipe_count != context.get("logical_recipe_count")):
                raise ValueError("CATALOG_FAST_AUTHORITY_TERMINAL_BINDING_INVALID")
            if unlaunched_terminal:
                _require_unlaunched_terminal(client=client, repository=repository, token=token,
                    commit=commit, number=number, request=request, issue=issue, context=context,
                    decision=decision, receipt=receipt, run_id=run_id,
                    receipt_artifact_id=int(os.environ.get("CATALOG_TERMINAL_ARTIFACT_ID", "0")))
        latest: dict[str, Any] = {}

        def read() -> dict[str, Any]:
            nonlocal latest
            latest = read_live_edit(anchor)
            return latest

        current = load_current_fast_authority(client=client, anchor=anchor, protected_commit=commit,
            read_edit=read, download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
            approve_historical_commit=lambda candidate: _historical_owner_commit_approved(client, candidate, commit))
        expected_edit_id = latest["data"]["repository"]["issue"]["userContentEdits"]["nodes"][0]["id"]
        transition = load_lineage_transition(root, request) if receipt is None or unlaunched_terminal else None
        recovery_proof = None
        if receipt is None:
            _, recovery_proof = _reserve_new_fast_request(
                root=root, authority=current, request=request, issue_number=number, run_id=run_id,
                client=client, protected_commit=commit,
                download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
            )
            candidate = (current.reserve(request=request, issue_number=number, run_id=run_id,
                                        lineage_transition=transition) if recovery_proof is None
                else current.reserve_checkpoint_successor(request=request, issue_number=number,
                    run_id=run_id, recovery_proof=recovery_proof, lineage_transition=transition))
        else:
            candidate = (current.close_unlaunched(request=request, issue_number=number, run_id=run_id,
                terminal_receipt_sha256=receipt.receipt_sha256, lineage_transition=transition) if unlaunched_terminal
                else current.terminalize(request=request, run_id=run_id, terminal_receipt_sha256=receipt.receipt_sha256))
        job_id = _publisher_job(client, run_id, attempt, commit, args.phase, number)

        def write(body: str) -> None:
            result = subprocess.run(["gh", "api", "--method", "PATCH", f"repos/{repository}/issues/{anchor['issue_number']}", "--input", "-"],
                input=json.dumps({"body": body}), capture_output=True, text=True, timeout=gate_timeout(20, reserve_seconds=10), check=False)
            if result.returncode != 0:
                raise ValueError("CATALOG_FAST_AUTHORITY_WRITE_REQUEST_FAILED")

        publication = write_current_fast_authority(current=current, candidate=candidate,
            expected_edit_id=expected_edit_id, anchor=anchor, run_id=run_id, run_attempt=attempt,
            job_id=job_id, phase=args.phase, commit=commit, read_edit=read, write_body=write,
            lineage_transition=transition, unlaunched_terminal=unlaunched_terminal, recovery_proof=recovery_proof)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(publication.model_dump_json() + "\n")
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write(f"authority_artifact_name=catalog-fast-authority-{run_id}-{attempt}-{args.phase}-{job_id}\n")
        print(json.dumps({"status": "STAGED_REQUIRES_UPLOAD_AND_VERIFICATION", "revision": candidate.revision,
            "state_sha256": candidate.state_sha256}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, CatalogGitHubSnapshotError, subprocess.SubprocessError) as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"CATALOG_[A-Z0-9_]+", reason):
            reason = "CATALOG_FAST_AUTHORITY_WRITE_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

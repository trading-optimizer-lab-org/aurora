#!/usr/bin/env python3
"""Import one fixed, verified pre-reservation closure into fast authority."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from typing import Any, Mapping, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_authority_github import (
    load_current_fast_authority,
    write_current_fast_authority,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    _verify_fast_gate_publication_metadata,
    read_fast_gate_archive,
    verify_nonreserving_fast_gate_execution,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.admit_catalog_fast_request import (
    _download_owner_archive,
    _historical_owner_commit_approved,
    _strict_json,
)
from scripts.publish_catalog_fast_authority import _publisher_job
from scripts.verify_catalog_fast_authority import read_live_edit


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARCHIVE = 2 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser


def _strict_bytes(raw: bytes) -> object:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_FAST_RECONCILIATION_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_FAST_RECONCILIATION_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _time(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(code)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError(code)
    return parsed


def _validate_config(config: object) -> Mapping[str, Any]:
    config = _mapping(config, "CATALOG_FAST_RECONCILIATION_CONFIG_INVALID")
    if set(config) != {
        "schema_version", "document_type", "operation", "current_authority",
        "request", "issue", "gate", "context", "evidence",
    } or config["schema_version"] != "1" or config["document_type"] != "catalog_fast_authority_reconciliation_v1" \
            or config["operation"] != "reconcile":
        raise ValueError("CATALOG_FAST_RECONCILIATION_CONFIG_INVALID")
    current = _mapping(config["current_authority"], "CATALOG_FAST_RECONCILIATION_CURRENT_PIN_INVALID")
    if set(current) != {"revision", "state_sha256", "campaign"}:
        raise ValueError("CATALOG_FAST_RECONCILIATION_CURRENT_PIN_INVALID")
    campaign = _mapping(current["campaign"], "CATALOG_FAST_RECONCILIATION_CURRENT_PIN_INVALID")
    if set(campaign) != {
        "campaign_key", "request_sha256", "launch_generation",
        "previous_terminal_request_sha256", "owner_issue_number", "owner_run_id",
        "terminal_receipt_sha256", "legacy_closure_evidence_sha256",
    }:
        raise ValueError("CATALOG_FAST_RECONCILIATION_CURRENT_PIN_INVALID")
    request = _mapping(config["request"], "CATALOG_FAST_RECONCILIATION_REQUEST_PIN_INVALID")
    if set(request) != {
        "issue_number", "issue_node_id", "title", "request_id", "request_sha256",
        "campaign_key", "launch_generation", "previous_terminal_request_sha256",
        "actor", "protected_commit_sha",
    }:
        raise ValueError("CATALOG_FAST_RECONCILIATION_REQUEST_PIN_INVALID")
    closure = _mapping(config["issue"], "CATALOG_FAST_RECONCILIATION_CLOSURE_PIN_INVALID")
    if set(closure) != {
        "state", "state_reason", "closed_at", "closed_by", "terminal_label",
        "created_at", "updated_at",
    }:
        raise ValueError("CATALOG_FAST_RECONCILIATION_CLOSURE_PIN_INVALID")
    gate = _mapping(config["gate"], "CATALOG_FAST_RECONCILIATION_GATE_PIN_INVALID")
    if set(gate) != {"run", "artifact"}:
        raise ValueError("CATALOG_FAST_RECONCILIATION_GATE_PIN_INVALID")
    run = _mapping(gate["run"], "CATALOG_FAST_RECONCILIATION_RUN_PIN_INVALID")
    if set(run) != {
        "run_id", "run_attempt", "path", "event", "head_branch", "head_sha",
        "status", "conclusion", "gate_job_id", "engine_job_id", "finalize_job_id",
    }:
        raise ValueError("CATALOG_FAST_RECONCILIATION_RUN_PIN_INVALID")
    artifact = _mapping(gate["artifact"], "CATALOG_FAST_RECONCILIATION_ARTIFACT_PIN_INVALID")
    if set(artifact) != {"id", "name", "size_in_bytes", "digest", "created_at", "expires_at"}:
        raise ValueError("CATALOG_FAST_RECONCILIATION_ARTIFACT_PIN_INVALID")
    context = _mapping(config["context"], "CATALOG_FAST_RECONCILIATION_CONTEXT_PIN_INVALID")
    if set(context) != {
        "schema_version", "document_type", "content_sha256", "protected_commit_sha",
        "issue_number", "logical_recipe_count", "preparation_error", "request_mode",
        "identity", "decision", "decision_sha256",
    }:
        raise ValueError("CATALOG_FAST_RECONCILIATION_CONTEXT_PIN_INVALID")
    for value in (
        current["state_sha256"], campaign["request_sha256"],
        campaign["previous_terminal_request_sha256"], campaign["legacy_closure_evidence_sha256"],
        request["request_sha256"],
        artifact["digest"][7:] if isinstance(artifact.get("digest"), str) else "",
        context["content_sha256"],
        context["decision_sha256"],
    ):
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise ValueError("CATALOG_FAST_RECONCILIATION_PIN_HASH_INVALID")
    if not isinstance(artifact.get("digest"), str) or not artifact["digest"].startswith("sha256:"):
        raise ValueError("CATALOG_FAST_RECONCILIATION_ARTIFACT_PIN_INVALID")
    if (
        type(current["revision"]) is not int or current["revision"] < 1
        or any(type(campaign[key]) is not int or campaign[key] < 1
               for key in ("launch_generation", "owner_issue_number", "owner_run_id"))
        or any(type(run[key]) is not int or run[key] < 1
               for key in ("run_id", "run_attempt", "gate_job_id", "engine_job_id", "finalize_job_id"))
        or type(artifact["id"]) is not int or artifact["id"] < 1
        or type(artifact["size_in_bytes"]) is not int or not 0 < artifact["size_in_bytes"] <= _MAX_ARCHIVE
        or type(context["issue_number"]) is not int or context["issue_number"] < 1
        or type(context["logical_recipe_count"]) is not int or context["logical_recipe_count"] < 0
    ):
        raise ValueError("CATALOG_FAST_RECONCILIATION_PIN_INVALID")
    if (
        not _COMMIT.fullmatch(request["protected_commit_sha"])
        or not _COMMIT.fullmatch(run["head_sha"])
        or not _COMMIT.fullmatch(context["protected_commit_sha"])
    ):
        raise ValueError("CATALOG_FAST_RECONCILIATION_PIN_COMMIT_INVALID")
    evidence = _mapping(config["evidence"], "CATALOG_FAST_RECONCILIATION_EVIDENCE_INVALID")
    if set(evidence) != {"schema_version", "document_type", "legacy_closure_evidence_sha256"} \
            or evidence["schema_version"] != "1" \
            or evidence["document_type"] != "catalog_fast_legacy_closure_evidence_v1":
        raise ValueError("CATALOG_FAST_RECONCILIATION_EVIDENCE_INVALID")
    if not isinstance(evidence["legacy_closure_evidence_sha256"], str) \
            or not _SHA.fullmatch(evidence["legacy_closure_evidence_sha256"]):
        raise ValueError("CATALOG_FAST_RECONCILIATION_EVIDENCE_HASH_INVALID")
    if campaign["terminal_receipt_sha256"] is not None or request["previous_terminal_request_sha256"] is not None:
        raise ValueError("CATALOG_FAST_RECONCILIATION_GENERATION_PIN_INVALID")
    if request["launch_generation"] != 1 or run["run_id"] < 1 or artifact["id"] < 1:
        raise ValueError("CATALOG_FAST_RECONCILIATION_PIN_INVALID")
    evidence_payload = {key: config[key] for key in ("request", "issue", "gate", "context")}
    if canonical_sha256(evidence_payload) != evidence["legacy_closure_evidence_sha256"]:
        raise ValueError("CATALOG_FAST_RECONCILIATION_EVIDENCE_HASH_INVALID")
    return config


def _read_gate_context(raw: bytes) -> Mapping[str, Any]:
    if not raw or len(raw) > _MAX_ARCHIVE:
        raise ValueError("CATALOG_FAST_RECONCILIATION_ARCHIVE_SIZE_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            target = [member for member in members if member.filename == "catalog-fast-request-context.json"]
            if len(members) != 2 or len(target) != 1:
                raise ValueError
            member = target[0]
            if member.is_dir() or member.flag_bits & 1 or not 0 < member.file_size <= 1024 * 1024:
                raise ValueError
            context = _strict_bytes(archive.read(member))
    except (zipfile.BadZipFile, OSError, RuntimeError, UnicodeError, ValueError) as exc:
        raise ValueError("CATALOG_FAST_RECONCILIATION_CONTEXT_INVALID") from exc
    return _mapping(context, "CATALOG_FAST_RECONCILIATION_CONTEXT_INVALID")


def _validate_issue(issue: Mapping[str, Any], pin: Mapping[str, Any]) -> None:
    closer = issue.get("closed_by")
    user = issue.get("user")
    labels = issue.get("labels")
    if (
        issue.get("number") != pin["issue_number"]
        or issue.get("node_id") != pin["issue_node_id"]
        or issue.get("title") != pin["title"]
        or issue.get("state") != "closed"
        or issue.get("state_reason") != "completed"
        or issue.get("created_at") != pin.get("created_at")
        or issue.get("updated_at") != pin.get("updated_at")
        or issue.get("closed_at") != pin.get("closed_at")
        or not isinstance(user, Mapping) or user.get("login") != pin["actor"]
        or not isinstance(closer, Mapping) or closer.get("login") != "github-actions[bot]"
        or not isinstance(labels, list) or len(labels) != 1
        or not isinstance(labels[0], Mapping) or labels[0].get("name") != "catalog-run-terminal-v1"
    ):
        raise ValueError("CATALOG_FAST_RECONCILIATION_ISSUE_CLOSURE_INVALID")
    if _time(issue["created_at"], "CATALOG_FAST_RECONCILIATION_ISSUE_TIME_INVALID") \
            > _time(issue["closed_at"], "CATALOG_FAST_RECONCILIATION_ISSUE_TIME_INVALID"):
        raise ValueError("CATALOG_FAST_RECONCILIATION_ISSUE_TIME_INVALID")


def _validate_current(state: FastAuthorityStateV1, pin: Mapping[str, Any]) -> None:
    if state.revision != pin["revision"] or state.state_sha256 != pin["state_sha256"] or len(state.campaigns) != 1:
        raise ValueError("CATALOG_FAST_RECONCILIATION_CURRENT_CHANGED")
    row = state.campaigns[0]
    expected = pin["campaign"]
    if (
        row.request.campaign_key != expected["campaign_key"]
        or row.request.request_sha256 != expected["request_sha256"]
        or row.request.launch_generation != expected["launch_generation"]
        or row.request.previous_terminal_request_sha256 != expected["previous_terminal_request_sha256"]
        or row.owner_issue_number != expected["owner_issue_number"]
        or row.owner_run_id != expected["owner_run_id"]
        or row.terminal_receipt_sha256 != expected["terminal_receipt_sha256"]
        or row.legacy_closure_evidence_sha256 != expected["legacy_closure_evidence_sha256"]
    ):
        raise ValueError("CATALOG_FAST_RECONCILIATION_CURRENT_CHANGED")


def _validate_run(run: Mapping[str, Any], pin: Mapping[str, Any]) -> None:
    expected = {
        "id": pin["run_id"],
        "run_attempt": pin["run_attempt"],
        "path": pin["path"],
        "event": pin["event"],
        "head_branch": pin["head_branch"],
        "head_sha": pin["head_sha"],
        "status": pin["status"],
        "conclusion": pin["conclusion"],
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError("CATALOG_FAST_RECONCILIATION_RUN_INVALID")


def _validate_artifact(artifact: Mapping[str, Any], pin: Mapping[str, Any]) -> None:
    if any(artifact.get(key) != value for key, value in pin.items()):
        raise ValueError("CATALOG_FAST_RECONCILIATION_ARTIFACT_INVALID")


def _write_body(repository: str, issue_number: int, body: str) -> None:
    result = subprocess.run(
        ["gh", "api", "--method", "PATCH", f"repos/{repository}/issues/{issue_number}", "--input", "-"],
        input=json.dumps({"body": body}), capture_output=True, text=True, timeout=20, check=False,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_FAST_RECONCILIATION_WRITE_FAILED")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
        if (
            repository != _REPOSITORY or not token or not _COMMIT.fullmatch(commit)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_JOB") != "bootstrap"
            or os.environ.get("CATALOG_AUTHORITY_MAINTENANCE_OPERATION") != "reconcile"
        ):
            raise ValueError("CATALOG_FAST_RECONCILIATION_ENVIRONMENT_INVALID")
        run_id = int(os.environ["GITHUB_RUN_ID"])
        attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
        root = args.repo_root.resolve(strict=True)
        runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        output = args.output.resolve(strict=False)
        github_output = args.github_output.resolve(strict=False)
        if (
            args.repo_root.is_symlink() or not root.is_dir() or args.output.exists() or args.output.is_symlink()
            or not output.is_relative_to(runner_temp) or not output.parent.is_dir()
            or args.github_output.is_symlink() or not github_output.is_relative_to(runner_temp)
        ):
            raise ValueError("CATALOG_FAST_RECONCILIATION_PATH_INVALID")
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
            text=True, timeout=10, check=False,
        )
        if head.returncode != 0 or head.stdout.strip() != commit:
            raise ValueError("CATALOG_FAST_RECONCILIATION_CHECKOUT_INVALID")
        config = _validate_config(_strict_json(root / "config/catalog_fast_authority_reconciliation_v1.json"))
        anchor = _mapping(_strict_json(root / "config/catalog_authority_anchor_v1.json"),
                          "CATALOG_FAST_RECONCILIATION_ANCHOR_INVALID")
        actors = _mapping(_strict_json(root / "config/catalog_controller_actors_v1.json"),
                          "CATALOG_FAST_RECONCILIATION_ACTORS_INVALID")
        request_pin = config["request"]
        key_path = (root / actors["requester_public_key_path"]).resolve(strict=True)
        if not key_path.is_relative_to(root):
            raise ValueError("CATALOG_FAST_RECONCILIATION_KEY_INVALID")
        client = CatalogGitHubReadOnlyClient(repository, token)

        issue, _ = client.get_json(f"/repos/{repository}/issues/{request_pin['issue_number']}")
        issue = _mapping(issue, "CATALOG_FAST_RECONCILIATION_ISSUE_INVALID")
        _validate_issue(issue, {**request_pin, **config["issue"]})
        request = parse_catalog_run_request(issue["title"], issue["body"], key_path.read_bytes())
        if (
            request.request_id != request_pin["request_id"]
            or request.request_sha256 != request_pin["request_sha256"]
            or request.campaign_key != request_pin["campaign_key"]
            or request.launch_generation != request_pin["launch_generation"]
            or request.previous_terminal_request_sha256 != request_pin["previous_terminal_request_sha256"]
            or issue["user"]["login"] != request_pin["actor"]
            or issue["user"]["login"] not in actors["request_actors"]
        ):
            raise ValueError("CATALOG_FAST_RECONCILIATION_REQUEST_INVALID")

        run_pin = config["gate"]["run"]
        run, _ = client.get_json(f"/repos/{repository}/actions/runs/{run_pin['run_id']}")
        run = _mapping(run, "CATALOG_FAST_RECONCILIATION_RUN_INVALID")
        _validate_run(run, run_pin)
        if not _historical_owner_commit_approved(client, run_pin["head_sha"], commit):
            raise ValueError("CATALOG_FAST_RECONCILIATION_SOURCE_UNAPPROVED")

        artifact_pin = config["gate"]["artifact"]
        artifact, _ = client.get_json(f"/repos/{repository}/actions/artifacts/{artifact_pin['id']}")
        artifact = _mapping(artifact, "CATALOG_FAST_RECONCILIATION_ARTIFACT_INVALID")
        _validate_artifact(artifact, artifact_pin)
        inventory, _ = client.get_json(
            f"/repos/{repository}/actions/runs/{run_pin['run_id']}/artifacts?per_page=100"
        )
        inventory = _mapping(inventory, "CATALOG_FAST_RECONCILIATION_ARTIFACT_INVENTORY_INVALID")
        rows = inventory.get("artifacts")
        if inventory.get("total_count") != 1 or not isinstance(rows, list) or len(rows) != 1:
            raise ValueError("CATALOG_FAST_RECONCILIATION_ARTIFACT_INVENTORY_INVALID")
        if rows[0].get("id") != artifact_pin["id"] or rows[0].get("name") != artifact_pin["name"]:
            raise ValueError("CATALOG_FAST_RECONCILIATION_ARTIFACT_INVALID")
        if any(str(row.get("name", "")).startswith("catalog-terminal-receipt-") for row in rows):
            raise ValueError("CATALOG_FAST_RECONCILIATION_TERMINAL_ARTIFACT_PRESENT")

        jobs_snapshot = client.stable_paginated(
            f"/repos/{repository}/actions/runs/{run_pin['run_id']}/attempts/{run_pin['run_attempt']}/jobs",
            root="jobs",
        )
        if jobs_snapshot.stable is not True or jobs_snapshot.collection.complete is not True:
            raise ValueError("CATALOG_FAST_RECONCILIATION_JOBS_INCOMPLETE")
        jobs = jobs_snapshot.collection.rows
        _verify_fast_gate_publication_metadata(
            artifact=artifact, run=run, jobs=jobs, expected_issue_number=request_pin["issue_number"],
            expected_commit=run_pin["head_sha"], requires_reservation=False,
        )
        verify_nonreserving_fast_gate_execution(
            jobs=jobs, run=run, expected_gate_job_id=run_pin["gate_job_id"],
            expected_engine_job_id=run_pin["engine_job_id"], expected_finalize_job_id=run_pin["finalize_job_id"],
        )
        raw = _download_owner_archive(repository, token, artifact_pin["id"])
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != artifact_pin["size_in_bytes"] or digest != artifact_pin["digest"][7:]:
            raise ValueError("CATALOG_FAST_RECONCILIATION_ARCHIVE_DIGEST_INVALID")
        decision = read_fast_gate_archive(
            raw, expected_sha256=artifact_pin["digest"][7:], expected_request=request,
            expected_issue_number=request_pin["issue_number"],
        )
        context = _read_gate_context(raw)
        context_pin = config["context"]
        context_fields = {
            "schema_version": context_pin["schema_version"],
            "document_type": context_pin["document_type"],
            "content_sha256": context_pin["content_sha256"],
            "protected_commit_sha": context_pin["protected_commit_sha"],
            "issue_number": context_pin["issue_number"],
            "logical_recipe_count": context_pin["logical_recipe_count"],
            "preparation_error": context_pin["preparation_error"],
            "request_mode": context_pin["request_mode"],
            "actor": request_pin["actor"],
            "issue_created_at": config["issue"]["created_at"],
            "issue_updated_at": config["issue"]["created_at"],
            "issue_labels": [],
        }
        if (
            any(context.get(key) != value for key, value in context_fields.items())
            or context.get("identity") != context_pin["identity"]
            or decision.model_dump(mode="json") != context_pin["decision"]
            or decision.decision_sha256 != context_pin["decision_sha256"]
        ):
            raise ValueError("CATALOG_FAST_RECONCILIATION_CONTEXT_BINDING_INVALID")

        latest: dict[str, Any] = {}

        def read() -> dict[str, Any]:
            nonlocal latest
            latest = read_live_edit(cast(dict[str, Any], anchor))
            return latest

        current = load_current_fast_authority(
            client=client, anchor=anchor, protected_commit=commit, read_edit=read,
            download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
            approve_historical_commit=lambda candidate: _historical_owner_commit_approved(client, candidate, commit),
        )
        _validate_current(current, config["current_authority"])
        candidate = current.reconcile_legacy_closure(
            request=request, issue_number=request_pin["issue_number"], historical_run_id=run_pin["run_id"],
            legacy_closure_evidence_sha256=config["evidence"]["legacy_closure_evidence_sha256"],
        )
        if candidate == current:
            with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write("authority_already_applied=true\n")
            print(json.dumps({"status": "RECONCILIATION_ALREADY_APPLIED", "revision": current.revision,
                              "state_sha256": current.state_sha256}))
            return 0
        expected_edit_id = latest["data"]["repository"]["issue"]["userContentEdits"]["nodes"][0]["id"]
        job_id = _publisher_job(client, run_id, attempt, commit, "reconcile")
        publication = write_current_fast_authority(
            current=current, candidate=candidate, expected_edit_id=expected_edit_id, anchor=anchor,
            run_id=run_id, run_attempt=attempt, job_id=job_id, phase="reconcile", commit=commit,
            read_edit=read, write_body=lambda body: _write_body(repository, anchor["issue_number"], body),
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(publication.model_dump_json() + "\n")
        with args.github_output.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"authority_artifact_name=catalog-fast-authority-{run_id}-{attempt}-reconcile-{job_id}\n")
            stream.write("authority_already_applied=false\n")
        print(json.dumps({"status": "RECONCILIATION_STAGED_REQUIRES_UPLOAD_AND_VERIFICATION",
                          "revision": candidate.revision, "state_sha256": candidate.state_sha256}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, CatalogGitHubSnapshotError, subprocess.SubprocessError) as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"CATALOG_[A-Z0-9_]+", reason):
            reason = "CATALOG_FAST_RECONCILIATION_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

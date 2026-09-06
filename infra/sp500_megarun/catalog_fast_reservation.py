"""Read existing gate evidence; never treat archive integrity as writer authority."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastLaunchDecisionV1, CatalogTerminalReceipt, ExistingCatalogLaunchV1, parse_catalog_terminal_receipt,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogStableInventory


_MEMBERS = frozenset({"catalog-fast-request-context.json", "catalog-fast-decision-v1.json"})
_MAX_MEMBER_BYTES = 1024 * 1024


class _OwnerReader(Protocol):
    repository: str

    def stable_paginated(self, path: str, *, root: str) -> CatalogStableInventory: ...

    def get_json(self, path: str) -> tuple[object, object]: ...


@dataclass(frozen=True)
class FastGateOwnerEvidence:
    run_id: int
    run: Mapping[str, Any]
    decision: CatalogFastLaunchDecisionV1
    jobs: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class FastGateAliasEvidence:
    """Authenticated routing hint, never a reservation or launch permission."""

    target_run_id: int


def bind_owner_terminal_receipt(
    *, owner: FastGateOwnerEvidence, receipt: CatalogTerminalReceipt,
) -> ExistingCatalogLaunchV1:
    """Bind a separately authenticated terminal publication to its reservation.

    Hash-valid JSON alone is not sufficient: the caller must verify the exact
    owner-run artifact and terminal publisher before calling this function.
    """
    decision = owner.decision
    if (
        not decision.launch_required or decision.existing_run_id is not None
        or receipt.engine_run_id != owner.run_id
        or receipt.run_url != f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{owner.run_id}"
        or receipt.request_sha256 != decision.request_sha256
        or receipt.submission_key_sha256 != decision.submission_key_sha256
        or receipt.campaign_key != decision.campaign_key
        or receipt.prepared_receipt_sha256 != decision.prepared_receipt_sha256
    ):
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_BINDING_INVALID")
    return ExistingCatalogLaunchV1(
        submission_key_sha256=receipt.submission_key_sha256,
        campaign_key=receipt.campaign_key, state=receipt.state, run_id=owner.run_id,
    )


def load_owner_terminal_receipt(
    *, client: _OwnerReader, owner: FastGateOwnerEvidence, issue_number: int,
    download_archive: Callable[[int], bytes],
) -> CatalogTerminalReceipt | None:
    """Read the existing terminal publication, reusing verified owner/job data.

    Does not rerun science or publish a replacement. A failed finalizer after
    successful receipt upload does not invalidate the already committed result.
    """
    name = f"catalog-terminal-receipt-{owner.decision.request_sha256}"
    inventory = client.stable_paginated(
        f"/repos/{client.repository}/actions/runs/{owner.run_id}/artifacts?name={name}", root="artifacts",
    )
    if inventory.stable is not True or inventory.collection.complete is not True:
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_INVENTORY_INCOMPLETE")
    rows = inventory.collection.rows
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_AMBIGUOUS")
    artifact = rows[0]
    try:
        source = artifact["workflow_run"]
        run = owner.run
        if (
            client.repository != "trading-optimizer-lab-org/aurora"
            or run["status"] != "completed" or run["id"] != owner.run_id
            or artifact["name"] != name or artifact["expired"] is not False
            or type(artifact["id"]) is not int or artifact["id"] < 1
            or source["id"] != owner.run_id or source["head_sha"] != run["head_sha"]
            or source["head_branch"] != "main"
            or source["repository_id"] != run["repository"]["id"]
            or source["head_repository_id"] != run["repository"]["id"]
            or type(artifact["size_in_bytes"]) is not int
            or not 0 < artifact["size_in_bytes"] <= 2 * _MAX_MEMBER_BYTES
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])
        ):
            raise ValueError
        finalizer_name = (
            "finalize" if run["path"] == ".github/workflows/catalog-fast-controller.yml"
            else f"catalog-request-{issue_number} / finalize"
        )
        finalizers = [job for job in owner.jobs if job.get("name") == finalizer_name]
        if len(finalizers) != 1:
            raise ValueError
        finalizer = finalizers[0]
        if (
            finalizer["run_id"] != owner.run_id or finalizer["run_attempt"] != run["run_attempt"]
            or finalizer["head_sha"] != run["head_sha"] or finalizer["status"] != "completed"
        ):
            raise ValueError
        create, publish = [
            [step for step in finalizer["steps"] if step.get("name") == label]
            for label in ("Create exactly one terminal receipt", "Publish the terminal receipt before changing the issue")
        ]
        if len(create) != 1 or len(publish) != 1:
            raise ValueError
        create_step, publish_step = create[0], publish[0]
        if any(step["status"] != "completed" or step["conclusion"] != "success" for step in (create_step, publish_step)):
            raise ValueError
        times = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (
            create_step["started_at"], create_step["completed_at"], publish_step["started_at"],
            artifact["created_at"], publish_step["completed_at"],
        )]
        if any(value.utcoffset() is None for value in times) or times != sorted(times):
            raise ValueError
        if create_step["number"] >= publish_step["number"]:
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_PROVENANCE_INVALID") from exc
    raw = download_archive(artifact["id"])
    if not raw or len(raw) > 2 * _MAX_MEMBER_BYTES or hashlib.sha256(raw).hexdigest() != artifact["digest"][7:]:
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_DIGEST_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise ValueError
            member = members[0]
            if (
                member.filename != "catalog-terminal-receipt-v1.json" or member.is_dir()
                or ((member.external_attr >> 16) & 0o170000) not in {0, 0o100000}
                or member.flag_bits & 1 or not 0 < member.file_size <= _MAX_MEMBER_BYTES
            ):
                raise ValueError
            receipt = parse_catalog_terminal_receipt(json.loads(
                archive.read(member), object_pairs_hook=_object, parse_constant=_nonfinite,
            ))
    except (zipfile.BadZipFile, ValueError, OSError, RuntimeError) as exc:
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_ARCHIVE_INVALID") from exc
    if not times[0] <= receipt.created_at <= times[1]:
        raise ValueError("CATALOG_FAST_OWNER_TERMINAL_TIME_INVALID")
    bind_owner_terminal_receipt(owner=owner, receipt=receipt)
    return receipt


def load_fast_gate_owner(
    *, client: _OwnerReader, issue_number: int, request: CatalogRunRequestV1,
    approved_commits: frozenset[str], download_archive: Callable[[int], bytes],
    approve_historical_commit: Callable[[str], bool] | None = None,
) -> FastGateOwnerEvidence | FastGateAliasEvidence | None:
    """Look up existing publication, not all historical runs or terminal issues.

    None means no gate artifacts were found, NOT authorization to launch: the
    caller must also inspect durable request state for expired/deleted evidence.
    More than sixteen publications requires offline reconciliation, not a long
    discovery loop in admission. Terminal run conclusion is not science proof.
    """
    if (
        client.repository != "trading-optimizer-lab-org/aurora"
        or type(issue_number) is not int or issue_number < 1
        or not approved_commits
        or any(not re.fullmatch(r"[0-9a-f]{40}", commit) for commit in approved_commits)
    ):
        raise ValueError("CATALOG_FAST_OWNER_LOOKUP_INVALID")
    prefix = f"/repos/{client.repository}"
    inventory = client.stable_paginated(
        f"{prefix}/actions/artifacts?name=catalog-fast-gate-{issue_number}", root="artifacts",
    )
    if inventory.stable is not True or inventory.collection.complete is not True:
        raise ValueError("CATALOG_FAST_OWNER_INVENTORY_INCOMPLETE")
    rows = inventory.collection.rows
    if len(rows) > 16:
        raise ValueError("CATALOG_FAST_OWNER_RECONCILIATION_REQUIRED")
    owners: list[FastGateOwnerEvidence] = []
    alias_targets: set[int] = set()
    for artifact in rows:
        source = artifact.get("workflow_run")
        commit = source.get("head_sha") if isinstance(source, Mapping) else None
        if (
            not isinstance(source, Mapping)
            or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or (commit not in approved_commits and (
                approve_historical_commit is None or not approve_historical_commit(commit)
            ))
        ):
            raise ValueError("CATALOG_FAST_OWNER_SOURCE_UNAPPROVED")
        run_id, artifact_id = source.get("id"), artifact.get("id")
        if type(run_id) is not int or run_id < 1 or type(artifact_id) is not int or artifact_id < 1:
            raise ValueError("CATALOG_FAST_OWNER_ID_INVALID")
        if artifact.get("name") != f"catalog-fast-gate-{issue_number}" or artifact.get("expired") is not False:
            raise ValueError("CATALOG_FAST_OWNER_ARTIFACT_UNAVAILABLE")
        digest = artifact.get("digest")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_DIGEST_INVALID")
        decision = read_fast_gate_archive(
            download_archive(artifact_id), expected_sha256=digest[7:],
            expected_request=request, expected_issue_number=issue_number,
        )
        if not decision.launch_required and decision.existing_run_id is None:
            continue
        run, _ = client.get_json(f"{prefix}/actions/runs/{run_id}")
        if not isinstance(run, Mapping) or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1:
            raise ValueError("CATALOG_FAST_OWNER_RUN_INVALID")
        jobs = client.stable_paginated(
            f"{prefix}/actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", root="jobs",
        )
        if jobs.stable is not True or jobs.collection.complete is not True:
            raise ValueError("CATALOG_FAST_OWNER_INVENTORY_INCOMPLETE")
        publisher_id = _verify_fast_gate_publication_metadata(
            artifact=artifact, run=run, jobs=jobs.collection.rows,
            expected_issue_number=issue_number, expected_commit=source["head_sha"],
            requires_reservation=decision.launch_required,
        )
        if decision.launch_required:
            owners.append(FastGateOwnerEvidence(publisher_id, dict(run), decision, tuple(jobs.collection.rows)))
        else:
            if decision.existing_run_id == publisher_id or type(decision.existing_run_id) is not int:
                raise ValueError("CATALOG_FAST_ALIAS_TARGET_INVALID")
            alias_targets.add(decision.existing_run_id)
    if len(owners) > 1:
        raise ValueError("CATALOG_FAST_OWNER_AMBIGUOUS")
    if len(alias_targets) > 1 or (owners and alias_targets and alias_targets != {owners[0].run_id}):
        raise ValueError("CATALOG_FAST_ALIAS_TARGET_CONFLICT")
    if not owners and alias_targets:
        return FastGateAliasEvidence(next(iter(alias_targets)))
    if rows and not owners:
        raise ValueError("CATALOG_FAST_OWNER_ORIGINAL_EVIDENCE_MISSING")
    return owners[0] if owners else None


def verify_fast_gate_owner_metadata(
    *, artifact: Mapping[str, Any], run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]], expected_issue_number: int, expected_commit: str,
) -> int:
    """Check authenticated, complete GitHub observations; return owner ID only.

    Caller supplies protected-source approval and complete job pagination.
    A failed run can own a reservation; terminal science is a separate check.
    Reconciler callers require the exact protected reusable-workflow binding
    and the explicit per-issue job name published by the reconciler.
    """
    return _verify_fast_gate_publication_metadata(
        artifact=artifact, run=run, jobs=jobs, expected_issue_number=expected_issue_number,
        expected_commit=expected_commit, requires_reservation=True,
    )


def _verify_fast_gate_publication_metadata(
    *, artifact: Mapping[str, Any], run: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]], expected_issue_number: int, expected_commit: str,
    requires_reservation: bool,
) -> int:
    """Validate an owner publication or a non-reserving alias publication."""
    try:
        run_id = run["id"]
        attempt = run["run_attempt"]
        repository = run["repository"]
        source = artifact["workflow_run"]
        if run["path"] == ".github/workflows/catalog-fast-controller.yml" and run["event"] == "issues":
            gate_name = "gate"
        elif (
            run["path"] == ".github/workflows/catalog-request-reconciler.yml"
            and run["event"] in {"schedule", "workflow_dispatch"}
        ):
            references = run.get("referenced_workflows")
            if not isinstance(references, list):
                raise ValueError
            expected_path = (
                "trading-optimizer-lab-org/aurora/.github/workflows/"
                f"catalog-fast-controller.yml@{expected_commit}"
            )
            matches = [item for item in references if isinstance(item, Mapping)
                       and item.get("path") == expected_path]
            if (
                len(matches) != 1 or matches[0].get("sha") != expected_commit
                or matches[0].get("ref") != "refs/heads/main"
            ):
                raise ValueError
            gate_name = f"catalog-request-{expected_issue_number} / gate"
        else:
            raise ValueError
        if (
            type(run_id) is not int or run_id < 1
            or type(attempt) is not int or attempt < 1
            or not re.fullmatch(r"[0-9a-f]{40}", expected_commit)
            or repository["full_name"] != "trading-optimizer-lab-org/aurora"
            or run["head_branch"] != "main"
            or run["head_sha"] != expected_commit
            or source["id"] != run_id or source["head_sha"] != expected_commit
            or source["head_branch"] != "main"
            or source["repository_id"] != repository["id"]
            or source["head_repository_id"] != repository["id"]
            or artifact["name"] != f"catalog-fast-gate-{expected_issue_number}"
            or artifact["expired"] is not False
            or type(artifact["size_in_bytes"]) is not int
            or not 0 < artifact["size_in_bytes"] <= 2 * _MAX_MEMBER_BYTES
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])
        ):
            raise ValueError
        gates = [job for job in jobs if job.get("name") == gate_name]
        if len(gates) != 1:
            raise ValueError
        gate = gates[0]
        if (
            gate["run_id"] != run_id or gate["run_attempt"] != attempt
            or gate["head_sha"] != expected_commit
            or gate["status"] != "completed" or gate["conclusion"] not in {"success", "failure", "cancelled"}
        ):
            raise ValueError
        publication, reservation = [
            [step for step in gate["steps"] if step.get("name") == name]
            for name in ("Publish the one gate decision", "Reserve the campaign atomically and expose QUEUED")
        ]
        if len(publication) != 1 or len(reservation) != 1:
            raise ValueError
        publish, reserve = publication[0], reservation[0]
        if publish["status"] != "completed" or publish["conclusion"] != "success":
            raise ValueError
        reservation_steps = [reserve]
        verified_name = "Verify the uploaded reservation before exposing QUEUED"
        durable_steps = [step for step in gate["steps"] if step.get("name") == verified_name]
        if requires_reservation and durable_steps:
            # Approved protected source: a later label failure does not undo
            # the already uploaded and independently verified reservation.
            reservation_steps = []
            for name in ("Write current authority edition", "Publish current authority edition", verified_name):
                matches = [step for step in gate["steps"] if step.get("name") == name]
                conclusions = {"success", "failure"} if name == "Publish current authority edition" else {"success"}
                if len(matches) != 1 or matches[0]["status"] != "completed" or matches[0]["conclusion"] not in conclusions:
                    raise ValueError
                reservation_steps.append(matches[0])
        elif (gate["conclusion"] != "success" or reserve["status"] != "completed"
                or reserve["conclusion"] != ("success" if requires_reservation else "skipped")):
            raise ValueError
        times = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (
            publish["started_at"], artifact["created_at"], publish["completed_at"],
        )]
        if requires_reservation:
            for step in reservation_steps:
                times.extend(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (
                    step["started_at"], step["completed_at"],
                ))
        if any(value.utcoffset() is None for value in times) or times != sorted(times):
            raise ValueError
        numbers = [publish["number"], *(step["number"] for step in reservation_steps)]
        if any(left >= right for left, right in zip(numbers, numbers[1:])):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("CATALOG_FAST_OWNER_PROVENANCE_INVALID") from exc
    return run_id


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_FAST_OWNER_DUPLICATE_KEY")
        result[key] = value
    return result


def _nonfinite(value: str) -> object:
    raise ValueError("CATALOG_FAST_OWNER_NONFINITE_JSON")


def read_fast_gate_archive(
    raw: bytes,
    *,
    expected_sha256: str,
    expected_request: CatalogRunRequestV1,
    expected_issue_number: int,
) -> CatalogFastLaunchDecisionV1:
    """Verify byte/identity binding of the existing two-file gate artifact.

    Caller must separately authenticate GitHub artifact metadata, producer run,
    protected workflow/commit and successful reservation step. This function
    does not establish a run owner, infer terminal success or create a record.
    """
    if not raw or len(raw) > 2 * _MAX_MEMBER_BYTES:
        raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_SIZE_INVALID")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_DIGEST_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 2 or {item.filename for item in members} != _MEMBERS:
                raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_SHAPE_INVALID")
            documents: dict[str, object] = {}
            for member in members:
                file_type = (member.external_attr >> 16) & 0o170000
                if (
                    member.is_dir() or file_type not in {0, 0o100000}
                    or member.flag_bits & 1
                    or not 0 < member.file_size <= _MAX_MEMBER_BYTES
                ):
                    raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_MEMBER_INVALID")
                documents[member.filename] = json.loads(
                    archive.read(member), object_pairs_hook=_object, parse_constant=_nonfinite,
                )
    except (zipfile.BadZipFile, OSError, UnicodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_INVALID") from exc
    context = documents["catalog-fast-request-context.json"]
    if not isinstance(context, dict):
        raise ValueError("CATALOG_FAST_OWNER_CONTEXT_INVALID")
    identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if (
        type(context.get("issue_number")) is not int
        or context.get("issue_number") != expected_issue_number
        or context.get("content_sha256") != canonical_sha256(identity)
    ):
        raise ValueError("CATALOG_FAST_OWNER_CONTEXT_BINDING_INVALID")
    try:
        archived_request = CatalogRunRequestV1.model_validate(context.get("request"))
        decision = CatalogFastLaunchDecisionV1.model_validate(documents["catalog-fast-decision-v1.json"])
    except ValueError as exc:
        raise ValueError("CATALOG_FAST_OWNER_DOCUMENT_INVALID") from exc
    if (
        archived_request != expected_request
        or decision.request_sha256 != expected_request.request_sha256
        or decision.submission_key_sha256 != expected_request.submission_key_sha256
        or decision.campaign_key != expected_request.campaign_key
    ):
        raise ValueError("CATALOG_FAST_OWNER_REQUEST_BINDING_INVALID")
    return decision

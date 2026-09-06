"""Read one current publication by exact locator; never infer an empty ledger.

The caller supplies authenticated transports and the checked-out protected anchor.
The issue is mutable and untrusted until its exact edit is bound to an artifact
from an approved producer. No historical issue enumeration or remote writes.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import zipfile
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from .catalog_fast_authority import FastAuthorityStateV1, FastAuthorityEditBindingV1, bind_authority_edit, verify_authority_edit


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_LOCATOR = re.compile(r"\n<!-- AURORA_FAST_PUBLICATION:([1-9][0-9]*):([1-9][0-9]*):(bootstrap|gate|finalize):([0-9a-f]{40}):([1-9][0-9]*) -->\Z")
_MAX_ARCHIVE = 2 * 1024 * 1024


def authority_publisher_job_name(run: Mapping[str, Any], *, commit: str, phase: str,
                               issue_number: int | None = None) -> str:
    """Accept only the direct writer or its exact protected reusable caller."""
    if phase == "bootstrap":
        if run.get("path") == ".github/workflows/catalog-fast-authority-maintenance.yml" and run.get("event") == "workflow_dispatch":
            return phase
    elif phase in {"gate", "finalize"}:
        if run.get("path") == ".github/workflows/catalog-fast-controller.yml" and run.get("event") == "issues":
            return phase
        if (run.get("path") == ".github/workflows/catalog-request-reconciler.yml"
                and run.get("event") in {"schedule", "workflow_dispatch"}
                and type(issue_number) is int and issue_number > 0):
            references = run.get("referenced_workflows")
            expected = f"{_REPOSITORY}/.github/workflows/catalog-fast-controller.yml@{commit}"
            matches = [row for row in references if isinstance(row, Mapping) and row.get("path") == expected] if isinstance(references, list) else []
            if len(matches) == 1 and matches[0].get("sha") == commit and matches[0].get("ref") == "refs/heads/main":
                return f"catalog-request-{issue_number} / {phase}"
    raise ValueError("CATALOG_FAST_AUTHORITY_PRODUCER_INVALID")


class _Reader(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_FAST_AUTHORITY_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("CATALOG_FAST_AUTHORITY_TIME_INVALID")
    return parsed


def _anchor_issue(payload: Mapping[str, Any], anchor: Mapping[str, Any]) -> Mapping[str, Any]:
    repository = payload["data"]["repository"]
    issue = repository["issue"]
    if (
        payload.get("errors") or anchor["production_enabled"] is not True
        or anchor["repository"] != _REPOSITORY
        or repository["id"] != anchor["repository_node_id"]
        or repository["nameWithOwner"] != _REPOSITORY
        or issue["id"] != anchor["issue_node_id"] or issue["number"] != anchor["issue_number"]
        or issue["title"] != anchor["exact_title"] or issue["state"] != "OPEN"
        or issue["locked"] is not False or issue["author"]["login"] != anchor["creator_login"]
        or issue["createdAt"] != anchor["created_at"]
    ):
        raise ValueError("CATALOG_FAST_AUTHORITY_ANCHOR_INVALID")
    return issue


def _edition(payload: Mapping[str, Any], anchor: Mapping[str, Any]) -> tuple[str, str, str]:
    issue = _anchor_issue(payload, anchor)
    nodes = issue["userContentEdits"]["nodes"]
    if len(nodes) != 1:
        raise ValueError("CATALOG_FAST_AUTHORITY_EDIT_INVALID")
    edit = nodes[0]
    if (
        not isinstance(edit["id"], str) or not edit["id"] or edit["deletedAt"] is not None
        or edit["editedAt"] != issue["lastEditedAt"] or edit["editor"] != issue["editor"]
        or edit["editor"]["login"] not in {"github-actions", "github-actions[bot]"}
        or not isinstance(issue["body"], str) or len(issue["body"].encode("utf-8")) > 256 * 1024
    ):
        raise ValueError("CATALOG_FAST_AUTHORITY_EDIT_INVALID")
    return issue["body"], edit["id"], edit["editedAt"]


def load_current_fast_authority(*, client: _Reader, anchor: Mapping[str, Any], protected_commit: str,
    read_edit: Callable[[], Mapping[str, Any]], download_archive: Callable[[int], bytes],
    approve_historical_commit: Callable[[str], bool] | None = None,
) -> FastAuthorityStateV1:
    """Authenticate current state or fail closed, including partially written state.

    Job completion is not required: a writer can verify its own completed upload
    before exiting. Both mutation and publication steps must already have passed.
    Full bootstrap and mutation authorization remain the producer's responsibility.
    """
    try:
        if client.repository != _REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", protected_commit):
            raise ValueError("CATALOG_FAST_AUTHORITY_INPUT_INVALID")
        edition = _edition(read_edit(), anchor)
        body, edit_id, edited_at = edition
        locator = _LOCATOR.search(body)
        if locator is None:
            raise ValueError("CATALOG_FAST_AUTHORITY_PUBLICATION_REQUIRED")
        run_id, attempt = int(locator[1]), int(locator[2])
        phase, commit = locator[3], locator[4]
        job_id = int(locator[5])
        if commit != protected_commit and (approve_historical_commit is None or not approve_historical_commit(commit)):
            raise ValueError("CATALOG_FAST_AUTHORITY_SOURCE_UNAPPROVED")
        prefix = f"/repos/{_REPOSITORY}/actions/runs/{run_id}"
        run, _ = client.get_json(prefix)
        name = f"catalog-fast-authority-{run_id}-{attempt}-{phase}-{job_id}"
        artifacts, _ = client.get_json(prefix + f"/artifacts?name={name}&per_page=100")
        writer, _ = client.get_json(f"/repos/{_REPOSITORY}/actions/jobs/{job_id}")
        if not isinstance(run, Mapping) or not isinstance(artifacts, Mapping) or not isinstance(writer, Mapping):
            raise ValueError("CATALOG_FAST_AUTHORITY_METADATA_INVALID")
        # These are bounded complete run-specific collections, not a repository scan.
        if artifacts["total_count"] != len(artifacts["artifacts"]) or artifacts["total_count"] > 100:
            raise ValueError("CATALOG_FAST_AUTHORITY_INVENTORY_INCOMPLETE")
        reusable_match = re.fullmatch(r"catalog-request-([1-9][0-9]*) / (gate|finalize)", str(writer.get("name", "")))
        owner_issue = int(reusable_match[1]) if reusable_match else None
        expected_job = authority_publisher_job_name(run, commit=commit, phase=phase, issue_number=owner_issue)
        if (
            run["id"] != run_id or run["run_attempt"] != attempt or run["head_sha"] != commit
            or run["head_branch"] != "main"
            or run["repository"]["full_name"] != _REPOSITORY
            or run["repository"]["node_id"] != anchor["repository_node_id"]
        ):
            raise ValueError("CATALOG_FAST_AUTHORITY_PRODUCER_INVALID")
        matches = [row for row in artifacts["artifacts"] if row.get("name") == name]
        if artifacts["total_count"] == 0:
            raise ValueError("CATALOG_FAST_AUTHORITY_ARTIFACT_MISSING")
        if len(matches) != 1 or writer["id"] != job_id or writer["name"] != expected_job:
            raise ValueError("CATALOG_FAST_AUTHORITY_PUBLICATION_AMBIGUOUS")
        artifact = matches[0]
        source = artifact["workflow_run"]
        if (
            artifact["expired"] is not False or type(artifact["id"]) is not int or artifact["id"] < 1
            or type(artifact["size_in_bytes"]) is not int or not 0 < artifact["size_in_bytes"] <= _MAX_ARCHIVE
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])
            or source["id"] != run_id or source["head_sha"] != commit or source["head_branch"] != "main"
            or source["repository_id"] != run["repository"]["id"] or source["head_repository_id"] != run["repository"]["id"]
            or writer["run_id"] != run_id or writer["run_attempt"] != attempt or writer["head_sha"] != commit
        ):
            raise ValueError("CATALOG_FAST_AUTHORITY_PRODUCER_INVALID")
        stages = []
        for label in ("Write current authority edition", "Publish current authority edition"):
            steps = [step for step in writer["steps"] if step.get("name") == label]
            conclusions = {"success", "failure"} if label == "Publish current authority edition" else {"success"}
            # Lost upload acknowledgement is not absence: the exact stored
            # archive, digest, producer window and current edit below decide.
            if len(steps) != 1 or steps[0]["status"] != "completed" or steps[0]["conclusion"] not in conclusions:
                raise ValueError("CATALOG_FAST_AUTHORITY_PUBLICATION_INCOMPLETE")
            stages.append(steps[0])
        write, upload = stages
        recovered = [step for step in writer["steps"] if step.get("name") == "Recover missing authority publication"]
        if len(recovered) > 1:
            raise ValueError("CATALOG_FAST_AUTHORITY_PUBLICATION_AMBIGUOUS")
        if not _time(upload["started_at"]) <= _time(artifact["created_at"]) <= _time(upload["completed_at"]):
            if (len(recovered) != 1 or recovered[0].get("status") != "completed"
                    or recovered[0].get("conclusion") not in {"success", "failure"}
                    or recovered[0]["number"] <= upload["number"]
                    or _time(recovered[0]["started_at"]) < _time(upload["completed_at"])):
                raise ValueError("CATALOG_FAST_AUTHORITY_PUBLICATION_TIME_INVALID")
            upload = recovered[0]
        times = [_time(value) for value in (write["started_at"], edited_at, write["completed_at"],
            upload["started_at"], artifact["created_at"], upload["completed_at"])]
        if times != sorted(times) or write["number"] >= upload["number"]:
            raise ValueError("CATALOG_FAST_AUTHORITY_PUBLICATION_TIME_INVALID")
        raw = download_archive(artifact["id"])
        if len(raw) != artifact["size_in_bytes"] or hashlib.sha256(raw).hexdigest() != artifact["digest"][7:]:
            raise ValueError("CATALOG_FAST_AUTHORITY_DIGEST_INVALID")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 1:
                raise ValueError("CATALOG_FAST_AUTHORITY_ARCHIVE_INVALID")
            member = members[0]
            if (member.filename != "catalog-fast-authority-publication-v1.json" or member.is_dir()
                or not 0 < member.file_size <= 512 * 1024 or member.flag_bits & 1
                or ((member.external_attr >> 16) & 0o170000) not in {0, 0o100000}):
                raise ValueError("CATALOG_FAST_AUTHORITY_ARCHIVE_INVALID")
            payload = json.loads(archive.read(member), object_pairs_hook=_object)
        state = verify_authority_edit(body=body[:locator.start()], publication_json=json.dumps(payload, allow_nan=False),
            issue_node_id=anchor["issue_node_id"], latest_edit_node_id=edit_id)
        if owner_issue is not None and not any(row.owner_issue_number == owner_issue and row.owner_run_id == run_id for row in state.campaigns):
            raise ValueError("CATALOG_FAST_AUTHORITY_OWNER_MISMATCH")
        if _edition(read_edit(), anchor) != edition:
            raise ValueError("CATALOG_FAST_AUTHORITY_CHANGED_DURING_READ")
        return state
    except (KeyError, TypeError, AttributeError, zipfile.BadZipFile, UnicodeError) as exc:
        raise ValueError("CATALOG_FAST_AUTHORITY_METADATA_INVALID") from exc


def write_current_fast_authority(*, current: FastAuthorityStateV1, candidate: FastAuthorityStateV1,
    expected_edit_id: str, anchor: Mapping[str, Any], run_id: int, run_attempt: int, job_id: int,
    phase: str, commit: str, read_edit: Callable[[], Mapping[str, Any]],
    write_body: Callable[[str], None],
) -> FastAuthorityEditBindingV1:
    """Mutate under the workflow's shared writer lock, then bind the observed edit.

    Caller must obtain current and expected_edit_id from the same verified read.
    Returns staging content, not publication success: upload and a full protected
    read-back are still required before evaluation or freeing a campaign.
    """
    if (phase not in {"gate", "finalize"} or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or any(type(value) is not int or value < 1 for value in (run_id, run_attempt, job_id))):
        raise ValueError("CATALOG_FAST_AUTHORITY_WRITER_INVALID")
    old_rows = {row.request.campaign_key: row for row in current.campaigns}
    changed = [row for row in candidate.campaigns if old_rows.get(row.request.campaign_key) != row]
    if len(changed) != 1 or changed[0].owner_run_id != run_id:
        raise ValueError("CATALOG_FAST_AUTHORITY_TRANSITION_INVALID")
    row = changed[0]
    if phase == "gate":
        expected = current.reserve(request=row.request, issue_number=row.owner_issue_number, run_id=run_id)
    else:
        if row.terminal_receipt_sha256 is None:
            raise ValueError("CATALOG_FAST_AUTHORITY_TERMINAL_REQUIRED")
        expected = current.terminalize(request=row.request, run_id=run_id,
            terminal_receipt_sha256=row.terminal_receipt_sha256)
    if expected != candidate:
        raise ValueError("CATALOG_FAST_AUTHORITY_TRANSITION_INVALID")
    before = _edition(read_edit(), anchor)
    locator = _LOCATOR.search(before[0])
    if (locator is None or before[1] != expected_edit_id
        or before[0][:locator.start()] != current.to_body()):
        raise ValueError("CATALOG_FAST_AUTHORITY_WRITE_CONFLICT")
    body = candidate.to_body() + f"\n<!-- AURORA_FAST_PUBLICATION:{run_id}:{run_attempt}:{phase}:{commit}:{job_id} -->"
    # GitHub issue body capacity is finite; never discover overflow after mutation.
    if len(body.encode("utf-8")) > 60 * 1024:
        raise ValueError("CATALOG_FAST_AUTHORITY_BODY_CAPACITY_EXCEEDED")
    write_error = None
    try:
        write_body(body)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        write_error = exc
    after = _edition(read_edit(), anchor)
    if (after[0] != body or after[1] == before[1]
        or _time(after[2]) < _time(before[2])):
        raise ValueError("CATALOG_FAST_AUTHORITY_WRITE_NOT_CONFIRMED") from write_error
    return bind_authority_edit(state=candidate, issue_node_id=anchor["issue_node_id"], edit_node_id=after[1])


def require_pristine_fast_authority(payload: Mapping[str, Any], anchor: Mapping[str, Any]) -> None:
    """Maintenance-only original-anchor guard, not evidence that history is empty."""
    issue = _anchor_issue(payload, anchor)
    if (issue["body"] != "AURORA CATALOG AUTHORITY LEDGER V1\n" or issue["lastEditedAt"] is not None
        or issue["editor"] is not None or issue["userContentEdits"]["nodes"] != []):
        raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_ANCHOR_NOT_PRISTINE")


def write_bootstrap_fast_authority(*, candidate: FastAuthorityStateV1, expected_state_sha256: str,
    anchor: Mapping[str, Any], run_id: int, run_attempt: int, job_id: int, commit: str,
    read_edit: Callable[[], Mapping[str, Any]], write_body: Callable[[str], None],
) -> FastAuthorityEditBindingV1:
    """Publish independently verified imported history, never automatically reset."""
    if (candidate.state_sha256 != expected_state_sha256 or candidate.revision != 1
        or candidate.previous_state_sha256 is not None or not candidate.campaigns
        or any(row.legacy_closure_evidence_sha256 is None or row.terminal_receipt_sha256 is not None
               for row in candidate.campaigns)
        or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or any(type(value) is not int or value < 1 for value in (run_id, run_attempt, job_id))):
        raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_CANDIDATE_INVALID")
    require_pristine_fast_authority(read_edit(), anchor)
    body = candidate.to_body() + f"\n<!-- AURORA_FAST_PUBLICATION:{run_id}:{run_attempt}:bootstrap:{commit}:{job_id} -->"
    if len(body.encode("utf-8")) > 60 * 1024:
        raise ValueError("CATALOG_FAST_AUTHORITY_BODY_CAPACITY_EXCEEDED")
    write_error = None
    try:
        write_body(body)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        write_error = exc
    after = _edition(read_edit(), anchor)
    if after[0] != body or _time(after[2]) < _time(anchor["created_at"]):
        raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_WRITE_NOT_CONFIRMED") from write_error
    return bind_authority_edit(state=candidate, issue_node_id=anchor["issue_node_id"], edit_node_id=after[1])

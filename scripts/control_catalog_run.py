"""Produce one fail-closed catalog controller decision from sealed snapshots."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

import jsonschema

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AUTHORITY_COMMENT_END,
    AUTHORITY_COMMENT_START,
    AuthorityState,
    CatalogAuthorityAnchorV1,
    CatalogAuthorityCheckpointV1,
    CatalogAuthorityRecordV1,
    CatalogControllerActorsV1,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
    parse_authority_comments,
    reconcile_authority_issue_tamper,
    reconcile_authority_mirrors,
    verify_authority_issue_anchor,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_builder import (
    verify_catalog_campaign_definition,
)
from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import (
    parse_catalog_campaign_definition_bytes,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogAuthorityAnchorEvidenceV1,
    CatalogCampaignDefinitionEvidenceV1,
    CatalogCapacityAdmissionEvidenceV1,
    CatalogControllerDecisionV1,
    CatalogGithubControlsEvidenceV1,
    CatalogPromptPolicyEvidenceV1,
    CatalogProtectedHeadEvidenceV1,
    CatalogRequestQueueEvidenceV1,
    CatalogScienceAdmissionEvidenceV1,
    CatalogSourceArtifactsEvidenceV1,
    ControllerOutcome,
    _blocked_decision,
    decide_catalog_run,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    canonical_model_bytes,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_SAFE_OUTPUT_VALUE = re.compile(
    r"^(?:true|false|[0-9]+|[0-9a-f]{40}|[0-9a-f]{64}|"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"
    r"[a-z0-9]+(?:[_-][a-z0-9]+)*)$"
)


class _BlockedInput(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate one catalog request without dispatching a workflow."
    )
    for name in (
        "event",
        "authority-issue",
        "authority-comments",
        "request-queue",
        "protected-head",
        "github-controls",
        "capacity",
        "admission-evidence",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--authority-anchor", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--actors", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    return parser


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _strict_json_file(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _BlockedInput(code)
    return value


def _repository_file(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    if candidate.is_symlink():
        raise _BlockedInput("CATALOG_CONTROLLER_SYMLINK_FORBIDDEN")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        raise _BlockedInput("CATALOG_CONTROLLER_REPOSITORY_INPUT_INVALID") from None
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise _BlockedInput("CATALOG_CONTROLLER_REPOSITORY_INPUT_INVALID")
    return resolved


def _snapshot_file(runner_temp: Path, path: Path) -> Path:
    if path.is_symlink():
        raise _BlockedInput("CATALOG_CONTROLLER_SYMLINK_FORBIDDEN")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise _BlockedInput("CATALOG_CONTROLLER_SNAPSHOT_INVALID") from None
    if not resolved.is_file() or not resolved.is_relative_to(runner_temp):
        raise _BlockedInput("CATALOG_CONTROLLER_SNAPSHOT_INVALID")
    return resolved


def _parse_event(payload: object) -> tuple[int, str, str, str]:
    event = _mapping(payload, "CATALOG_REQUEST_INVALID")
    if set(event) != {"repository", "issue"}:
        raise _BlockedInput("CATALOG_REQUEST_INVALID")
    repository = _mapping(event["repository"], "CATALOG_REQUEST_INVALID")
    issue = _mapping(event["issue"], "CATALOG_REQUEST_INVALID")
    user = _mapping(issue.get("user"), "CATALOG_REQUEST_INVALID")
    if repository.get("full_name") != _REPOSITORY:
        raise _BlockedInput("CATALOG_REQUEST_INVALID")
    number = issue.get("number")
    title = issue.get("title")
    body = issue.get("body")
    author = user.get("login")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or not isinstance(title, str)
        or not isinstance(body, str)
        or not isinstance(author, str)
    ):
        raise _BlockedInput("CATALOG_REQUEST_INVALID")
    return number, title, body, author


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise _BlockedInput("CATALOG_CONTROLLER_TIME_INVALID")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise _BlockedInput("CATALOG_CONTROLLER_TIME_INVALID") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _BlockedInput("CATALOG_CONTROLLER_TIME_INVALID")
    return parsed.astimezone(UTC)


def _blocked_from_event(event_bytes: bytes, reason: str) -> CatalogControllerDecisionV1:
    return _blocked_decision(
        failures=(reason,),
        request_sha256=hashlib.sha256(event_bytes).hexdigest(),
        campaign_id=None,
        science_sha256=None,
        execution_plan_sha256=None,
        execution_protocol_sha256=None,
        authority_id=None,
    )


def _prompt_evidence(
    *,
    root: Path,
    policy_path: Path,
    applicable_commit_sha: str,
    observed_at: datetime,
) -> CatalogPromptPolicyEvidenceV1:
    policy = _mapping(_strict_json_file(policy_path), "CATALOG_PROMPT_POLICY_INVALID")
    schema_path = _repository_file(
        root,
        Path("schemas/catalog_run_prompt_policy_v1.schema.json"),
    )
    schema = _strict_json_file(schema_path)
    prompt_path = _repository_file(
        root,
        Path("docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"),
    )
    migration_value = policy.get("migration_path")
    if not isinstance(migration_value, str):
        raise _BlockedInput("CATALOG_PROMPT_POLICY_INVALID")
    migration_path = _repository_file(root, Path(migration_value))
    try:
        jsonschema.validate(policy, schema)
    except jsonschema.ValidationError:
        raise _BlockedInput("CATALOG_PROMPT_POLICY_INVALID") from None
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    migration_hash = hashlib.sha256(migration_path.read_bytes()).hexdigest()
    rule_ids = tuple(
        str(_mapping(row, "CATALOG_PROMPT_POLICY_INVALID").get("rule_id"))
        for row in policy.get("rules", ())
    )
    expected_rule_ids = tuple(f"CAT-{index:03d}" for index in range(1, 26))
    if (
        prompt_hash != policy.get("active_prompt_sha256")
        or migration_hash != policy.get("migration_sha256")
        or rule_ids != expected_rule_ids
    ):
        raise _BlockedInput("CATALOG_PROMPT_POLICY_INVALID")
    policy_hash = _sha256(policy)
    receipt = {
        "applicable_commit_sha": applicable_commit_sha,
        "prompt_sha256": prompt_hash,
        "prompt_policy_sha256": policy_hash,
        "rule_ids": rule_ids,
    }
    return CatalogPromptPolicyEvidenceV1(
        status="ready",
        observed_at=observed_at,
        source_sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        content_sha256=_sha256(receipt),
        receipt_sha256=_sha256({"receipt": receipt}),
        applicable_commit_sha=applicable_commit_sha,
        prompt_sha256=prompt_hash,
        prompt_policy_sha256=policy_hash,
        prompt_bytes_verified=True,
        prompt_policy_schema_valid=True,
        enforced_policy_rule_ids=rule_ids,
    )


def _definition_evidence(
    *,
    root: Path,
    registry_path: Path,
    registry: object,
    entry: object,
    applicable_commit_sha: str,
    observed_at: datetime,
) -> CatalogCampaignDefinitionEvidenceV1:
    manifest_path = _repository_file(root, Path(entry.definition_manifest_path))
    manifest_bytes = manifest_path.read_bytes()
    manifest = parse_catalog_campaign_definition_bytes(manifest_bytes)
    schema = _strict_json_file(
        _repository_file(
            root,
            Path("schemas/catalog_campaign_definition_manifest_v1.schema.json"),
        )
    )
    try:
        jsonschema.validate(manifest.model_dump(mode="json"), schema)
    except jsonschema.ValidationError:
        raise _BlockedInput("CATALOG_CAMPAIGN_DEFINITION_MISMATCH") from None
    verified = verify_catalog_campaign_definition(
        repo_root=root,
        registry_entry=entry,
        manifest=manifest,
    )
    registry_hash = canonical_sha256(registry)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    receipt = {
        "applicable_commit_sha": applicable_commit_sha,
        "campaign_key": entry.campaign_key,
        "campaign_registry_sha256": registry_hash,
        "campaign_definition_manifest_sha256": manifest_hash,
        "campaign_definition_sha256": verified.campaign_definition_sha256,
    }
    return CatalogCampaignDefinitionEvidenceV1(
        status="ready",
        observed_at=observed_at,
        source_sha256=hashlib.sha256(registry_path.read_bytes()).hexdigest(),
        content_sha256=_sha256(receipt),
        receipt_sha256=_sha256({"repository_rehash": receipt}),
        applicable_commit_sha=applicable_commit_sha,
        campaign_key=entry.campaign_key,
        registry_entry_resolved=True,
        safe_paths_verified=True,
        manifest_schema_valid=True,
        repository_rehash_complete=True,
        campaign_registry_sha256=registry_hash,
        campaign_definition_manifest_sha256=manifest_hash,
        campaign_definition_sha256=verified.campaign_definition_sha256,
        campaign_definition_rehash_receipt_sha256=_sha256(
            {"complete_repository_rehash": receipt}
        ),
    )


def _authority_state(
    *,
    anchor_path: Path,
    issue_payload: object,
    comments_payload: object,
    observed_at: datetime,
) -> tuple[CatalogAuthorityAnchorEvidenceV1, VerifiedAuthorityLedgerV1, Mapping[str, Any]]:
    issue = _mapping(issue_payload, "CATALOG_AUTHORITY_ANCHOR_INVALID")
    comments = _mapping(comments_payload, "CATALOG_LEDGER_INVALID")
    anchor = CatalogAuthorityAnchorV1.model_validate(_strict_json_file(anchor_path))
    verification = verify_authority_issue_anchor(
        anchor=anchor,
        repository_variable_number=issue.get("repository_variable_number"),
        repository_snapshot=issue.get("repository_snapshot"),
        issue_snapshot=issue.get("issue_snapshot"),
    )
    ledger = parse_authority_comments(
        comments.get("comments", ()),
        expected_author="github-actions[bot]",
        writer_run_snapshots=comments.get("writer_run_snapshots", ()),
    )
    mirror = reconcile_authority_mirrors(
        comment_records=ledger.records,
        artifact_records=tuple(
            CatalogAuthorityRecordV1.model_validate(item)
            for item in comments.get("artifact_records", ())
        ),
        checkpoints=tuple(
            CatalogAuthorityCheckpointV1.model_validate(item)
            for item in comments.get("checkpoints", ())
        ),
        tamper_incidents=comments.get("tamper_incidents", ()),
        now=observed_at,
    )
    lifecycle = reconcile_authority_issue_tamper(
        ledger=ledger,
        incident=comments.get("authority_tamper_incident"),
        complete_timeline=comments.get("complete_timeline"),
    )
    if not mirror.safe_to_schedule_compute or lifecycle.all_catalog_authorities_blocked:
        raise _BlockedInput("CATALOG_LEDGER_INVALID")
    receipt = {
        "anchor": verification.model_dump(mode="json"),
        "ledger_sha256": ledger.ledger_sha256,
        "mirror_status": mirror.status,
        "lifecycle": lifecycle.model_dump(mode="json"),
    }
    evidence = CatalogAuthorityAnchorEvidenceV1(
        status="ready",
        observed_at=observed_at,
        source_sha256=hashlib.sha256(anchor_path.read_bytes()).hexdigest(),
        content_sha256=_sha256(receipt),
        receipt_sha256=_sha256({"authority_anchor": receipt}),
        identity_verified=True,
        live_variable_matches=True,
        ledger_integrity_verified=True,
        ledger_sha256=ledger.ledger_sha256,
        authority_anchor_evidence_sha256=_sha256(receipt),
    )
    writer_context = _mapping(
        comments.get("current_writer_context", {}),
        "CATALOG_LEDGER_WRITER_PROVENANCE_INVALID",
    )
    return evidence, ledger, writer_context


def _render_authority_comment(record: object) -> str:
    payload = canonical_model_bytes(record).decode("utf-8")
    return f"{AUTHORITY_COMMENT_START}\n{payload}\n{AUTHORITY_COMMENT_END}\n"


def _authority_append(
    *,
    decision: CatalogControllerDecisionV1,
    ledger: VerifiedAuthorityLedgerV1,
    request_issue_number: int,
    writer_context: Mapping[str, Any],
    observed_at: datetime,
) -> str | None:
    if decision.outcome is ControllerOutcome.ADMITTED:
        if decision.sealed_inputs is None or decision.authority_id is None:
            raise _BlockedInput("CATALOG_AUTHORITY_APPEND_INVALID")
        record = append_authority_record(
            previous=None,
            authority_id=decision.authority_id,
            request_issue_number=request_issue_number,
            campaign_id=decision.sealed_inputs.campaign_id,
            request_sha256=decision.request_sha256,
            science_sha256=decision.sealed_inputs.science_sha256,
            execution_plan_sha256=decision.sealed_inputs.execution_plan_sha256,
            execution_protocol_sha256=(decision.sealed_inputs.execution_protocol_sha256),
            state=AuthorityState.RESERVED,
            run_id=writer_context.get("run_id"),
            run_attempt=writer_context.get("run_attempt"),
            writer_job_id="reserve",
            writer_job_database_id=writer_context.get("writer_job_database_id"),
            protected_commit_sha=decision.sealed_inputs.protected_commit_sha,
            created_at=observed_at,
        )
        return _render_authority_comment(record)
    if (
        decision.outcome is ControllerOutcome.ADOPTED
        and decision.should_resume_existing
    ):
        previous = ledger.latest
        if previous is None or decision.sealed_inputs is None:
            raise _BlockedInput("CATALOG_AUTHORITY_APPEND_INVALID")
        record = append_authority_record(
            previous=previous,
            state=AuthorityState.RECOVERING,
            run_id=writer_context.get("run_id"),
            run_attempt=writer_context.get("run_attempt"),
            writer_job_id="reserve",
            writer_job_database_id=writer_context.get("writer_job_database_id"),
            execution_plan_sha256=decision.sealed_inputs.execution_plan_sha256,
            evidence_sha256=decision.decision_sha256,
            safe_operational_replan=True,
            created_at=observed_at,
        )
        return _render_authority_comment(record)
    return None


def _request_comment(decision: CatalogControllerDecisionV1) -> str:
    labels = {
        "blocked": "BLOCKED",
        "deferred": "DEFERRED",
        "admitted": "ADMITTED",
        "adopted": "ADOPTED",
    }
    return (
        "## Decisión automática del run de catálogo\n\n"
        f"- Estado: {labels[decision.outcome.value]}\n"
        f"- Motivo: `{decision.reason_code}`\n"
        f"- Solicitud: `{decision.request_sha256}`\n"
        f"- Decisión: `{decision.decision_sha256}`\n"
    )


def _github_output_values(
    decision: CatalogControllerDecisionV1,
    request_issue_number: int,
) -> dict[str, str]:
    values = {
        "call_engine": str(decision.outcome is ControllerOutcome.ADMITTED).lower(),
        "resume_existing": str(
            decision.outcome is ControllerOutcome.ADOPTED
            and decision.should_resume_existing
        ).lower(),
        "create_authority": str(decision.should_create_authority).lower(),
        "decision_sha256": decision.decision_sha256,
        "request_issue_number": str(request_issue_number),
    }
    if decision.authority_id is not None:
        values["authority_id"] = str(decision.authority_id)
    if decision.sealed_inputs is not None:
        for key, value in decision.sealed_inputs.model_dump(mode="json").items():
            values[f"sealed_{key}"] = str(value)
    if any(not _SAFE_OUTPUT_VALUE.fullmatch(value) for value in values.values()):
        raise ValueError("CATALOG_GITHUB_OUTPUT_VALUE_INVALID")
    return values


def _emit(
    *,
    output_dir: Path,
    github_output: Path | None,
    runner_temp: Path,
    decision: CatalogControllerDecisionV1,
    request_issue_number: int,
    authority_comment: str | None,
) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("CATALOG_CONTROLLER_OUTPUT_DIRECTORY_EXISTS")
    resolved_output = output_dir.resolve(strict=False)
    if not resolved_output.is_relative_to(runner_temp):
        raise ValueError("CATALOG_CONTROLLER_OUTPUT_DIRECTORY_INVALID")
    output_dir.mkdir(parents=True)
    (output_dir / "decision.json").write_bytes(canonical_model_bytes(decision) + b"\n")
    (output_dir / "request_comment.md").write_text(
        _request_comment(decision),
        encoding="utf-8",
        newline="\n",
    )
    if authority_comment is not None:
        (output_dir / "authority_comment.md").write_text(
            authority_comment,
            encoding="utf-8",
            newline="\n",
        )
    if github_output is not None:
        if github_output.is_symlink():
            raise ValueError("CATALOG_CONTROLLER_GITHUB_OUTPUT_INVALID")
        resolved_github_output = github_output.resolve(strict=False)
        if not resolved_github_output.is_relative_to(runner_temp):
            raise ValueError("CATALOG_CONTROLLER_GITHUB_OUTPUT_INVALID")
        values = _github_output_values(decision, request_issue_number)
        with github_output.open("a", encoding="utf-8", newline="\n") as handle:
            for key, value in sorted(values.items()):
                handle.write(f"{key}={value}\n")


def _enabled_decision(
    *,
    args: argparse.Namespace,
    root: Path,
    files: Mapping[str, Path],
    event_payload: object,
    actors: CatalogControllerActorsV1,
) -> tuple[CatalogControllerDecisionV1, int, str | None]:
    issue_number, title, body, author = _parse_event(event_payload)
    if author not in actors.request_actors or actors.requester_public_key_path is None:
        raise _BlockedInput("CATALOG_REQUEST_ACTOR_INVALID")
    public_key_path = _repository_file(root, Path(actors.requester_public_key_path))
    public_key = public_key_path.read_bytes()
    request = parse_catalog_run_request(title, body, public_key)
    if request.requester_public_key_sha256 != actors.requester_public_key_sha256:
        raise _BlockedInput("CATALOG_REQUESTER_PUBLIC_KEY_FINGERPRINT_MISMATCH")

    protected_head = CatalogProtectedHeadEvidenceV1.model_validate(
        _strict_json_file(files["protected_head"])
    )
    admission = _mapping(
        _strict_json_file(files["admission_evidence"]),
        "CATALOG_ADMISSION_EVIDENCE_INVALID",
    )
    observed_at = _parse_time(admission.get("verified_github_now"))
    policy_path = _repository_file(root, args.policy)
    prompt_evidence = _prompt_evidence(
        root=root,
        policy_path=policy_path,
        applicable_commit_sha=protected_head.applicable_commit_sha,
        observed_at=observed_at,
    )

    registry_path = _repository_file(root, args.registry)
    registry = load_catalog_campaign_registry(registry_path)
    try:
        entry = resolve_catalog_campaign(registry, request.campaign_key, root)
    except ValueError:
        raise _BlockedInput("CATALOG_CAMPAIGN_NOT_REGISTERED") from None
    definition_evidence = _definition_evidence(
        root=root,
        registry_path=registry_path,
        registry=registry,
        entry=entry,
        applicable_commit_sha=protected_head.applicable_commit_sha,
        observed_at=observed_at,
    )

    authority_evidence, ledger, writer_context = _authority_state(
        anchor_path=_repository_file(root, args.authority_anchor),
        issue_payload=_strict_json_file(files["authority_issue"]),
        comments_payload=_strict_json_file(files["authority_comments"]),
        observed_at=observed_at,
    )
    request_queue = CatalogRequestQueueEvidenceV1.model_validate(
        _strict_json_file(files["request_queue"])
    )
    github_controls = CatalogGithubControlsEvidenceV1.model_validate(
        _strict_json_file(files["github_controls"])
    )
    capacity = CatalogCapacityAdmissionEvidenceV1.model_validate(
        _strict_json_file(files["capacity"])
    )
    science = CatalogScienceAdmissionEvidenceV1.model_validate(
        admission.get("science_evidence")
    )
    source_artifacts = CatalogSourceArtifactsEvidenceV1.model_validate(
        admission.get("source_artifacts_evidence")
    )
    operational_plan = _mapping(
        admission.get("operational_plan"),
        "CATALOG_EXECUTION_PLAN_INVALID",
    )
    protocol = admission.get("execution_protocol_sha256")
    active_owner_run = admission.get("active_owner_run")
    if not isinstance(protocol, str) or not isinstance(active_owner_run, bool):
        raise _BlockedInput("CATALOG_ADMISSION_EVIDENCE_INVALID")

    decision = decide_catalog_run(
        request=request,
        request_issue_number=issue_number,
        request_issue_author=author,
        allowed_request_actors=actors.request_actors,
        observed_request_sha256=request.request_sha256,
        registry_entry=entry,
        prompt_evidence=prompt_evidence,
        campaign_definition_evidence=definition_evidence,
        authority_anchor_evidence=authority_evidence,
        protected_head_evidence=protected_head,
        github_controls_evidence=github_controls,
        science_evidence=science,
        source_artifacts_evidence=source_artifacts,
        capacity_evidence=capacity,
        request_queue_evidence=request_queue,
        ledger=ledger,
        operational_plan=operational_plan,
        execution_protocol_sha256=protocol,
        verified_github_now=observed_at,
        active_owner_run=active_owner_run,
    )
    authority_comment = _authority_append(
        decision=decision,
        ledger=ledger,
        request_issue_number=issue_number,
        writer_context=writer_context,
        observed_at=observed_at,
    )
    return decision, issue_number, authority_comment


def main() -> int:
    args = _parser().parse_args()
    root = args.repo_root.resolve(strict=True)
    if args.repo_root.is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_CONTROLLER_REPOSITORY_ROOT_INVALID")
    runner_temp_value = os.environ.get("RUNNER_TEMP")
    if not runner_temp_value:
        raise ValueError("CATALOG_CONTROLLER_RUNNER_TEMP_REQUIRED")
    runner_temp = Path(runner_temp_value).resolve(strict=True)
    snapshot_arguments = {
        "event": args.event,
        "authority_issue": args.authority_issue,
        "authority_comments": args.authority_comments,
        "request_queue": args.request_queue,
        "protected_head": args.protected_head,
        "github_controls": args.github_controls,
        "capacity": args.capacity,
        "admission_evidence": args.admission_evidence,
    }
    files = {
        name: _snapshot_file(runner_temp, path)
        for name, path in snapshot_arguments.items()
    }
    event_bytes = files["event"].read_bytes()
    issue_number = 1
    authority_comment: str | None = None
    try:
        event_payload = _strict_json_file(files["event"])
        issue_number, _, _, _ = _parse_event(event_payload)
        actors_path = _repository_file(root, args.actors)
        actors = CatalogControllerActorsV1.model_validate(
            _strict_json_file(actors_path)
        )
        if not actors.production_enabled:
            raise _BlockedInput("CATALOG_REQUEST_ACTOR_NOT_BOOTSTRAPPED")
        decision, issue_number, authority_comment = _enabled_decision(
            args=args,
            root=root,
            files=files,
            event_payload=event_payload,
            actors=actors,
        )
    except _BlockedInput as exc:
        decision = _blocked_from_event(event_bytes, str(exc))
    except (ValueError, TypeError, OSError):
        decision = _blocked_from_event(event_bytes, "CATALOG_CONTROLLER_INPUT_INVALID")
    _emit(
        output_dir=args.output_dir,
        github_output=args.github_output,
        runner_temp=runner_temp,
        decision=decision,
        request_issue_number=issue_number,
        authority_comment=authority_comment,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

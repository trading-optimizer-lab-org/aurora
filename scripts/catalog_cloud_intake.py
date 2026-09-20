#!/usr/bin/env python3
"""Protected, phased cloud intake; only the App client may POST a run request."""

from datetime import timedelta
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.infra.sp500_megarun.catalog_campaign_definition_contract import parse_catalog_campaign_definition_bytes, registry_entry_sha256
from aurora.infra.sp500_megarun.catalog_campaign_registry import load_catalog_campaign_registry, resolve_catalog_campaign
from aurora.infra.sp500_megarun.catalog_cloud_cutover import imported_cloud_ticket, load_cloud_retirement
from aurora.infra.sp500_megarun.catalog_cloud_emission import CatalogCloudEmissionV1, CloudOriginEvidenceV1
from aurora.infra.sp500_megarun.catalog_cloud_ticket import select_cloud_launch_ticket
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH, load_checkpoint_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_cloud_transport import _processing_record
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient
from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition
from aurora.infra.sp500_megarun.catalog_requester import build_catalog_intent_draft
from aurora.infra.sp500_megarun.catalog_requester_broker import (
    sign_catalog_request, submit_catalog_request_to_github, reconcile_catalog_request_to_github,
    _verify_issue, _parse_github_time,
)
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.publish_catalog_cloud_authority import publish_cloud_candidate
from scripts.validate_catalog_cloud_intent import load_validated_cloud_context, _strict_json_file


def _write_once(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def _workdir(path):
    temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if path.is_symlink() or not path.resolve().is_relative_to(temp):
        raise ValueError("CATALOG_CLOUD_WORKDIR_INVALID")
    path.mkdir(exist_ok=True)
    if not path.is_dir():
        raise ValueError("CATALOG_CLOUD_WORKDIR_INVALID")
    return path.resolve(strict=True)


def _session(root):
    from aurora.infra.sp500_megarun.catalog_cloud_app import cloud_app_session
    key = os.environ.get("CATALOG_REQUESTER_PRIVATE_KEY", "")
    if not key:
        raise ValueError("CATALOG_CLOUD_REQUESTER_KEY_REQUIRED")
    return cloud_app_session(root, key.encode("utf-8"))


def _require_checkpoint_definition(root, manifest, proof):
    """The signed definition must bind the exact protected recovery profile."""
    profile = load_checkpoint_recovery_profile(root, proof.campaign_key, proof.target_generation)
    path = root / CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH
    if (profile is None or profile.profile_sha256 != proof.profile_sha256
            or manifest.campaign_key != proof.campaign_key or path.is_symlink()
            or not path.resolve(strict=True).is_relative_to(root.resolve(strict=True))):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_DEFINITION_INVALID")
    rows = [row for row in manifest.entries if row.path == CHECKPOINT_RECOVERY_CONFIG_RELATIVE_PATH]
    raw = path.read_bytes()
    if (len(rows) != 1 or rows[0].sha256 != hashlib.sha256(raw).hexdigest()
            or rows[0].size_bytes != len(raw)):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_DEFINITION_INVALID")


def _new_emission(root, context, run_id, commit, *, recovery_proof=None):
    registry = load_catalog_campaign_registry(root / "config/catalog_campaign_registry_v1.json")
    entry = resolve_catalog_campaign(registry, context.intent.campaign_key, root)
    manifest_path = root / entry.definition_manifest_path
    if manifest_path.is_symlink() or not manifest_path.resolve().is_relative_to(root):
        raise ValueError("CATALOG_CLOUD_MANIFEST_PATH_INVALID")
    manifest = parse_catalog_campaign_definition_bytes(manifest_path.read_bytes())
    if manifest.registry_entry_sha256 != registry_entry_sha256(entry):
        raise ValueError("CATALOG_CLOUD_MANIFEST_REGISTRY_MISMATCH")
    if recovery_proof is not None:
        _require_checkpoint_definition(root, manifest, recovery_proof)
    prompt = (root / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md").read_bytes()
    prompt_sha = hashlib.sha256(prompt).hexdigest()
    imported = imported_cloud_ticket(
        root=root, authority=context.authority, campaign_key=entry.campaign_key,
        campaign_definition_sha256=manifest.campaign_definition_sha256, prompt_sha256=prompt_sha,
    )
    transition = load_lineage_transition(root, imported) if imported is not None else None
    ticket = select_cloud_launch_ticket(
        authority=context.authority, intent=context.intent,
        campaign_definition_sha256=manifest.campaign_definition_sha256,
        prompt_sha256=prompt_sha, imported_ticket=imported, lineage_transition=transition,
        lineage_resolver=lambda candidate: load_lineage_transition(root, candidate),
        recovery_proof=recovery_proof,
    )
    draft = build_catalog_intent_draft(ticket=ticket, registry_entry=entry,
                                      campaign_manifest=manifest, prompt_bytes=prompt)
    with _session(root) as (app, _token, public_key):
        signed = sign_catalog_request(draft=draft,
            private_key_pem=os.environ["CATALOG_REQUESTER_PRIVATE_KEY"].encode("utf-8"))
        if parse_catalog_run_request(signed.title, signed.body, public_key) != signed.request:
            raise ValueError("CATALOG_CLOUD_REQUEST_INVALID")
        origin = CloudOriginEvidenceV1(
            app_id=app.app_id, installation_id=app.installation_id,
            requester_actor=app.expected_actor, requester_public_key_sha256=app.requester_public_key_sha256,
            environment="catalog-cloud-intake", permissions=tuple(sorted(app.config.required_installation_permissions.items())),
            retirement_receipt_sha256=load_cloud_retirement(root).receipt_sha256,
            launch_ticket_sha256=ticket.launch_ticket_sha256,
        )
    return CatalogCloudEmissionV1(
        intent_id=context.intent.intent_id, intent_issue_number=context.intent.issue_number,
        repository_id=context.intent.repository_id, actor_id=context.intent.author_id,
        intent_sha256=context.intent.intent_sha256, request=signed.request, origin=origin,
        producer_run_id=run_id, producer_commit=commit, state="SIGNED",
    )


def _post_bounds(client, item):
    run, _ = client.get_json(f"/repos/{client.repository}/actions/runs/{item.post_run_id}/attempts/{item.post_run_attempt}")
    if (not isinstance(run, dict) or run.get("id") != item.post_run_id
            or run.get("run_attempt") != item.post_run_attempt
            or run.get("head_branch") != "main"
            or run.get("repository", {}).get("full_name") != client.repository
            or run.get("path") != ".github/workflows/catalog-cloud-intake.yml"):
        raise ValueError("CATALOG_CLOUD_POST_RUN_INVALID")
    jobs = []
    for page in range(1, 11):
        payload, _ = client.get_json(
            f"/repos/{client.repository}/actions/runs/{item.post_run_id}/attempts/{item.post_run_attempt}/jobs?per_page=100&page={page}"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("CATALOG_CLOUD_POST_JOB_INVALID")
        jobs.extend(row for row in payload["jobs"] if row.get("name") == "intake")
        if len(payload["jobs"]) < 100:
            break
    else:
        raise ValueError("CATALOG_CLOUD_POST_JOB_INVALID")
    if (len(jobs) != 1 or jobs[0].get("run_id") != item.post_run_id
            or jobs[0].get("run_attempt") != item.post_run_attempt
            or jobs[0].get("head_sha") != run.get("head_sha")):
        raise ValueError("CATALOG_CLOUD_POST_JOB_INVALID")
    lower = _parse_github_time(jobs[0].get("started_at"))
    # The producer job has a fixed 15-minute timeout. This window is the same
    # on resume; the resume clock must never authorize a later duplicate issue.
    return lower, lower + timedelta(minutes=15)


def _report_locator(context, client):
    """An idempotent public locator, never evidence of scientific success."""
    item = context.replay
    if context.status not in {"PUBLICADO", "COMPLETED"} or item is None or item.issue_number is None:
        raise ValueError("CATALOG_CLOUD_PUBLICATION_PENDING")
    request_sha = item.request.request_sha256 if isinstance(item, CatalogCloudEmissionV1) else item.request_sha256
    body = (f"<!-- AURORA_CLOUD_INTENT:{item.intent_id} -->\n"
            f"Solicitud científica: https://github.com/{client.repository}/issues/{item.issue_number}\n"
            f"request_sha256: `{request_sha}`\n\n"
            "Este enlace no acredita éxito científico; consulta el recibo terminal del controlador.\n")
    endpoint = f"/repos/{client.repository}/issues/{context.intent.issue_number}/comments"

    def found():
        count = 0
        for page in range(1, 11):
            comments, _ = client.get_json(endpoint + f"?per_page=100&page={page}")
            if not isinstance(comments, list):
                raise ValueError("CATALOG_CLOUD_REPORT_INVENTORY_INVALID")
            count += sum(row.get("body") == body and row.get("user", {}).get("login") == "github-actions[bot]"
                         for row in comments if isinstance(row, dict))
            if len(comments) < 100:
                if count > 1:
                    raise ValueError("CATALOG_CLOUD_REPORT_AMBIGUOUS")
                return count == 1
        raise ValueError("CATALOG_CLOUD_REPORT_INVENTORY_INCOMPLETE")
    if not found():
        try:
            subprocess.run(["gh", "api", "--method", "POST", endpoint.lstrip("/"), "--input", "-"],
                input=json.dumps({"body": body}), capture_output=True, text=True, timeout=30, check=False)
        except subprocess.SubprocessError:
            pass
        if not found():
            raise ValueError("CATALOG_CLOUD_REPORT_UNCONFIRMED")
    return {"changed": "false", "status": context.status,
            "scientific_issue_url": f"https://github.com/{client.repository}/issues/{item.issue_number}"}


def execute_phase(*, root, work, phase, context, client, run_id, attempt, commit):
    if phase == "report":
        return _report_locator(context, client)
    item = context.replay
    if context.status == "COMPLETED" or context.status == "PUBLICADO":
        return {"changed": "false", "status": context.status}
    current = context.authority
    if phase == "signed":
        if item is not None:
            return {"changed": "false", "status": context.status}
        owner = next((row for row in current.campaigns
                      if row.request.campaign_key == context.intent.campaign_key), None)
        profile = load_checkpoint_recovery_profile(
            root, context.intent.campaign_key, owner.generation + 1 if owner else 1,
        )
        proof = None
        if profile is not None:
            from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import authenticate_checkpoint_recovery_owner
            from scripts.admit_catalog_fast_request import _download_owner_archive
            authenticated = authenticate_checkpoint_recovery_owner(
                repo_root=root, repository=client.repository, protected_commit_sha=commit,
                profile=profile, fetch_json=client,
                download_artifact=lambda artifact_id: _download_owner_archive(
                    client.repository, os.environ["GH_TOKEN"], artifact_id),
            )
            proof = authenticated.proof
        item = _new_emission(root, context, run_id, commit, recovery_proof=proof)
        transition = load_lineage_transition(root, item.request)
        if proof is None:
            candidate = current.stage_emission(item, lineage_transition=transition)
        else:
            candidate = current.stage_checkpoint_emission(item, recovery_proof=proof,
                                                          lineage_transition=transition)
    elif phase == "uncertain":
        if item is None:
            raise ValueError("CATALOG_CLOUD_SIGNED_EMISSION_REQUIRED")
        if item.state != "SIGNED":
            return {"changed": "false", "status": item.state}
        candidate = current.advance_emission(intent_id=item.intent_id,
            state="PUBLICACION_INCIERTA", post_run_id=run_id, post_run_attempt=attempt)
    elif phase == "post":
        if item is None or item.state != "PUBLICACION_INCIERTA":
            raise ValueError("CATALOG_CLOUD_UNCERTAIN_EMISSION_REQUIRED")
        lower, upper = _post_bounds(client, item)
        permit_path = work / "first-post-permit.json"
        fresh = False
        if permit_path.exists():
            permit = _strict_json_file(permit_path, max_bytes=4096)
            fresh = permit == {"intent_id": item.intent_id, "state_sha256": current.state_sha256,
                               "run_id": run_id, "run_attempt": attempt}
            if not fresh or (item.post_run_id, item.post_run_attempt) != (run_id, attempt):
                raise ValueError("CATALOG_CLOUD_POST_PERMIT_INVALID")
        with _session(root) as (app, token, public_key):
            if (item.origin.app_id != app.app_id or item.origin.installation_id != app.installation_id
                    or item.origin.requester_actor != app.expected_actor
                    or item.origin.retirement_receipt_sha256 != load_cloud_retirement(root).receipt_sha256):
                raise ValueError("CATALOG_CLOUD_ORIGIN_CHANGED")
            if parse_catalog_run_request(item.title, item.body, public_key) != item.request:
                raise ValueError("CATALOG_CLOUD_REQUEST_INVALID")
            signed = _processing_record(item, lower)
            if fresh and not (work / "first-post-consumed.json").exists():
                # O_EXCL is an ephemeral invocation guard, not another durable
                # ledger. Authority remains uncertain if any following step fails.
                _write_once(work / "first-post-consumed.json", {"intent_id": item.intent_id})
                receipt = submit_catalog_request_to_github(signed=signed, client=app,
                    installation_token=token, post_lower_bound=lower, post_upper_bound=upper)
            else:
                receipt = reconcile_catalog_request_to_github(signed=signed, client=app,
                    installation_token=token, post_lower_bound=lower, post_upper_bound=upper)
        _write_once(work / "post-result.json", {"intent_id": item.intent_id, "issue_number": receipt.issue_number})
        return {"changed": "false", "status": "POST_READBACK_VERIFIED"}
    else:
        if item is None or item.state != "PUBLICACION_INCIERTA":
            raise ValueError("CATALOG_CLOUD_UNCERTAIN_EMISSION_REQUIRED")
        result = _strict_json_file(work / "post-result.json", max_bytes=4096)
        if set(result) != {"intent_id", "issue_number"} or result["intent_id"] != item.intent_id:
            raise ValueError("CATALOG_CLOUD_POST_RESULT_INVALID")
        number = result["issue_number"]
        if type(number) is not int or number < 1:
            raise ValueError("CATALOG_CLOUD_POST_RESULT_INVALID")
        issue, _ = client.get_json(f"/repos/{client.repository}/issues/{number}")
        lower, upper = _post_bounds(client, item)
        actors = _strict_json_file(root / "config/catalog_controller_actors_v1.json")
        if len(actors["request_actors"]) != 1:
            raise ValueError("CATALOG_CLOUD_REQUESTER_ACTOR_INVALID")
        verified = _verify_issue(issue, signed=_processing_record(item, lower),
            expected_actor=actors["request_actors"][0], repository=client.repository,
            post_lower_bound=lower, post_upper_bound=upper)
        if verified != number:
            raise ValueError("CATALOG_CLOUD_POST_RESULT_INVALID")
        candidate = current.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=number)
    publication_phase = "intake-" + phase
    directory = work / publication_phase
    directory.mkdir(exist_ok=False)
    artifact = publish_cloud_candidate(root=root, current=current, candidate=candidate,
        expected_edit_id=context.latest_edit_id, client=client, phase=publication_phase,
        output=directory / "catalog-fast-authority-publication-v1.json")
    if phase == "uncertain":
        _write_once(work / "first-post-permit.json", {"intent_id": item.intent_id,
            "state_sha256": candidate.state_sha256, "run_id": run_id, "run_attempt": attempt})
    return {"changed": "true", "authority_artifact_name": artifact, "status": publication_phase}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=("signed", "uncertain", "post", "published", "report"), required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if os.environ.get("GITHUB_JOB") != "intake":
            raise ValueError("CATALOG_CLOUD_JOB_INVALID")
        if args.github_output is not None and (
                str(args.github_output) != os.environ.get("GITHUB_OUTPUT") or args.github_output.is_symlink()):
            raise ValueError("CATALOG_CLOUD_OUTPUT_INVALID")
        context = load_validated_cloud_context(args.repo_root)
        root, work = args.repo_root.resolve(strict=True), _workdir(args.work_dir)
        retirement = load_cloud_retirement(root)
        if retirement.observed_at > context.intent.observed_at:
            raise ValueError("CATALOG_CLOUD_RETIREMENT_TIME_INVALID")
        client = CatalogGitHubReadOnlyClient(context.intent.repository, os.environ["GH_TOKEN"])
        result = execute_phase(root=root, work=work, phase=args.phase, context=context, client=client,
            run_id=int(os.environ["GITHUB_RUN_ID"]), attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
            commit=os.environ["GITHUB_SHA"])
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as stream:
                for key, value in result.items():
                    stream.write(f"{key}={value}\n")
        print(json.dumps(result))
        return 0
    except Exception as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"(?:CATALOG_|REQUESTER_|CLOUD_)[A-Z0-9_]+", reason):
            reason = "CATALOG_CLOUD_INTAKE_FAILED"
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

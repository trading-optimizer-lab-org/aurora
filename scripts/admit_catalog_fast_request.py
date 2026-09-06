#!/usr/bin/env python3
"""Run the single live gate and materialize one already-prepared plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_gate_budget import gate_timeout
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastGateSnapshotV1,
    CatalogFastLaunchDecisionV1,
    CatalogPreparationIdentityV1,
    CatalogTerminalReceipt,
    decide_fast_catalog_launch,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    materialize_prepared_catalog_plan,
    verify_prepared_catalog_bundle,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    FastGateAliasEvidence, load_fast_gate_owner, load_owner_terminal_receipt,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Admit one already-prepared catalog run.")
    parser.add_argument("--request-context", required=True, type=Path)
    parser.add_argument("--prepared-bundle", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    return parser


def _strict_json(path: Path) -> object:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("CATALOG_FAST_GATE_DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_FAST_GATE_INPUT_INVALID")
    return json.loads(
        path.read_text("utf-8"),
        object_pairs_hook=reject,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_FAST_GATE_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("CATALOG_REQUEST_TIME_INVALID")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CATALOG_REQUEST_TIME_INVALID")
    return parsed.astimezone(timezone.utc)


def _bool_env(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"CATALOG_FAST_GATE_VARIABLE_INVALID:{name}")
    return value == "true"


def _blocked(
    *,
    request: CatalogRunRequestV1,
    prepared_receipt_sha256: str | None,
    now: datetime,
    expires_at: datetime,
    reason_code: str,
) -> CatalogFastLaunchDecisionV1:
    return CatalogFastLaunchDecisionV1.create(
        state="BLOCKED",
        reason_code=reason_code,
        request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256,
        campaign_key=request.campaign_key,
        prepared_receipt_sha256=prepared_receipt_sha256,
        selected_workers=0,
        launch_required=False,
        existing_run_id=None,
        decided_at=now,
        expires_at=expires_at,
    )


def _download_owner_archive(repository: str, token: str, artifact_id: int) -> bytes:
    """Read a metadata-bounded archive via gh without exposing the bearer token."""
    if repository != _REPOSITORY or type(artifact_id) is not int or artifact_id < 1:
        raise ValueError("CATALOG_FAST_OWNER_DOWNLOAD_INVALID")
    with tempfile.TemporaryFile() as stream:
        result = subprocess.run(
            ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"],
            stdout=stream, stderr=subprocess.PIPE, env={**os.environ, "GH_TOKEN": token},
            timeout=gate_timeout(20), check=False,
        )
        if result.returncode != 0:
            raise ValueError("CATALOG_FAST_OWNER_DOWNLOAD_FAILED")
        stream.seek(0)
        raw = stream.read(2 * 1024 * 1024 + 1)
    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError("CATALOG_FAST_OWNER_ARCHIVE_SIZE_INVALID")
    return raw


def _historical_owner_commit_approved(client: CatalogGitHubReadOnlyClient, candidate: str, protected: str) -> bool:
    # Authenticate ancestry to the independently bound protected checkout. The
    # artifact's own head_sha is only a query, never its approval evidence.
    comparison, _ = client.get_json(f"/repos/{_REPOSITORY}/compare/{candidate}...{protected}")
    return (
        isinstance(comparison, Mapping)
        and comparison.get("status") in {"ahead", "identical"}
        and comparison.get("base_commit", {}).get("sha") == candidate
        and comparison.get("merge_base_commit", {}).get("sha") == candidate
    )


def _write_replay_decision(
    decision: CatalogFastLaunchDecisionV1, *, output_dir: Path, github_output: Path,
    terminal_receipt: CatalogTerminalReceipt | None = None,
) -> None:
    output_dir.mkdir(parents=False, exist_ok=False)
    (output_dir / "catalog-fast-decision-v1.json").write_text(decision.model_dump_json() + "\n", encoding="utf-8")
    outputs = {
        "preserve_issue": "true", "launch_required": "false", "selected_workers": "0",
        "existing_run_id": str(decision.existing_run_id) if decision.existing_run_id else "",
        "campaign_state": decision.state, "reason_code": decision.reason_code,
        "request_sha256": decision.request_sha256, "submission_key_sha256": decision.submission_key_sha256,
        "prepared_receipt_sha256": decision.prepared_receipt_sha256 or "",
        "decision_sha256": decision.decision_sha256,
        "terminal_receipt_sha256": terminal_receipt.receipt_sha256 if terminal_receipt else "",
        "existing_run_url": terminal_receipt.run_url if terminal_receipt else "",
    }
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={value}\n")


def admit_request(
    *,
    request_context_path: Path,
    prepared_bundle: Path,
    repo_root: Path,
    output_dir: Path,
    github_output: Path,
) -> CatalogFastLaunchDecisionV1:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    if (
        repository != _REPOSITORY
        or not token
        or not _COMMIT.fullmatch(expected_commit)
        or not runner_temp_raw
    ):
        raise ValueError("CATALOG_FAST_GATE_INVOCATION_INVALID")
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    root = repo_root.resolve(strict=True)
    context_path = request_context_path.resolve(strict=True)
    bundle = prepared_bundle.resolve(strict=False)
    target = output_dir.resolve(strict=False)
    gh_output = github_output.resolve(strict=False)
    if (
        repo_root.is_symlink()
        or not root.is_dir()
        or not context_path.is_relative_to(runner_temp)
        or not bundle.is_relative_to(runner_temp)
        or output_dir.exists()
        or output_dir.is_symlink()
        or not target.is_relative_to(runner_temp)
        or github_output.is_symlink()
        or not gh_output.is_relative_to(runner_temp)
    ):
        raise ValueError("CATALOG_FAST_GATE_PATH_INVALID")
    context = _mapping(_strict_json(context_path), "CATALOG_FAST_REQUEST_CONTEXT_INVALID")
    context_identity = {key: value for key, value in context.items() if key != "content_sha256"}
    if (
        context.get("schema_version") != "1"
        or context.get("document_type") != "catalog_fast_request_context_v1"
        or context.get("protected_commit_sha") != expected_commit
        or context.get("content_sha256") != canonical_sha256(context_identity)
        or context.get("request_mode") not in {None, "admit_new", "lookup_existing"}
    ):
        raise ValueError("CATALOG_FAST_REQUEST_CONTEXT_INVALID")
    request = CatalogRunRequestV1.model_validate(context.get("request"))
    client = CatalogGitHubReadOnlyClient(repository, token)
    actors = _mapping(
        _strict_json(root / "config/catalog_controller_actors_v1.json"),
        "CATALOG_FAST_REQUEST_ACTOR_INVALID",
    )
    public_key_path = actors.get("requester_public_key_path")
    if not isinstance(public_key_path, str):
        raise ValueError("CATALOG_REQUESTER_KEY_UNAVAILABLE")
    public_key = (root / public_key_path).read_bytes()
    current_issue_number = context.get("issue_number")
    if type(current_issue_number) is not int or current_issue_number < 1:
        raise ValueError("CATALOG_FAST_REQUEST_CONTEXT_INVALID")
    # Until absence of ownership is established, failures must not terminalize
    # the original request through a workflow fallback.
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write("preserve_issue=true\n")
    issue_raw, _ = client.get_json(f"/repos/{repository}/issues/{current_issue_number}")
    issue = _mapping(issue_raw, "CATALOG_FAST_REQUEST_CONTEXT_INVALID")
    if (
        issue.get("number") != current_issue_number
        or issue.get("user", {}).get("login") != context.get("actor")
        or context.get("actor") not in actors.get("request_actors", ())
        or not isinstance(issue.get("title"), str) or not isinstance(issue.get("body"), str)
        or parse_catalog_run_request(issue["title"], issue["body"], public_key) != request
        or issue.get("created_at") != context.get("issue_created_at")
    ):
        raise ValueError("CATALOG_FAST_REQUEST_LIVE_BINDING_INVALID")
    labels = {row.get("name") for row in issue.get("labels", ()) if isinstance(row, Mapping)}
    if client.observed_at is None:
        raise ValueError("CATALOG_FAST_GATE_GITHUB_TIME_INVALID")
    owner = None
    lookup_error = None
    owner_issue_number = current_issue_number
    active_campaigns: set[str] = set()
    terminal_generations: list[tuple[CatalogRunRequestV1, Mapping[str, Any]]] = []
    pinned_terminal_sha256 = None
    existing_issue_state = (
        bool(labels & {"catalog-run-active-v1", "catalog-run-terminal-v1"})
        or issue.get("state") == "closed"
    )
    durable_owner = existing_issue_state or context.get("request_mode") == "lookup_existing"

    def lookup_owner(number: int, signed_request: CatalogRunRequestV1):
        return load_fast_gate_owner(
            client=client, issue_number=number, request=signed_request,
            approved_commits=frozenset({expected_commit}),
            approve_historical_commit=lambda candidate: _historical_owner_commit_approved(client, candidate, expected_commit),
            download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
        )

    try:
        evidence = lookup_owner(current_issue_number, request)
        alias_target = evidence.target_run_id if isinstance(evidence, FastGateAliasEvidence) else None
        owner = None if isinstance(evidence, FastGateAliasEvidence) else evidence
        if alias_target is not None:
            durable_owner = True
        compact_handled = False
        authority_path = runner_temp / "catalog-fast-authority-current.json"
        if owner is None and authority_path.exists():
            # Same-job output of verify_catalog_fast_authority.py, never request
            # content or a downloaded user artifact. The writer revalidates the
            # live edition under the shared lock before reserving or launching.
            try:
                if authority_path.is_symlink() or authority_path.stat().st_size > 256 * 1024:
                    raise ValueError("invalid snapshot file")
                authority = FastAuthorityStateV1.model_validate(_strict_json(authority_path))
            except (ValueError, OSError) as exc:
                raise ValueError("CATALOG_FAST_AUTHORITY_SNAPSHOT_INVALID") from exc
            current = next((row for row in authority.campaigns
                            if row.request.campaign_key == request.campaign_key), None)
            if current is not None and current.request.request_id == request.request_id:
                if current.request.intent_sha256 != request.intent_sha256:
                    raise ValueError("CATALOG_FAST_INTENT_CONFLICT")
                durable_owner = True
                owner_issue_number = current.owner_issue_number
                resolved = lookup_owner(owner_issue_number, current.request)
                if isinstance(resolved, FastGateAliasEvidence):
                    raise ValueError("CATALOG_FAST_ALIAS_CHAIN_NOT_ALLOWED")
                if resolved is not None and resolved.run_id != current.owner_run_id:
                    raise ValueError("CATALOG_FAST_AUTHORITY_OWNER_MISMATCH")
                if alias_target is not None and (resolved is None or resolved.run_id != alias_target):
                    raise ValueError("CATALOG_FAST_ALIAS_TARGET_CONFLICT")
                owner = resolved
                pinned_terminal_sha256 = current.terminal_receipt_sha256
                compact_handled = True
            # Absence from a partial maintenance baseline is NOT proof of an
            # empty campaign history. Older intents retain original evidence.
            elif current is not None and not durable_owner and request.launch_generation > current.generation:
                publisher = os.environ.get("GITHUB_RUN_ID", "")
                if not publisher.isascii() or not publisher.isdecimal() or int(publisher) < 1:
                    raise ValueError("CATALOG_FAST_GATE_INVOCATION_INVALID")
                authority.reserve(request=request, issue_number=current_issue_number, run_id=int(publisher))
                active_campaigns.update(row.request.campaign_key for row in authority.campaigns if not row.is_terminal)
                compact_handled = True
        if owner is None and not compact_handled and (not existing_issue_state or alias_target is not None):
            active_inventory = client.stable_paginated(
                f"/repos/{repository}/issues?state=open&labels=catalog-run-active-v1", root="list",
            )
            if active_inventory.stable is not True or active_inventory.collection.complete is not True:
                raise ValueError("CATALOG_ACTIVE_REQUEST_INVENTORY_INCOMPLETE")
            matches: list[tuple[int, CatalogRunRequestV1]] = []
            for row in active_inventory.collection.rows:
                number = row.get("number")
                if number == current_issue_number:
                    continue
                if (
                    type(number) is not int or number < 1
                    or row.get("user", {}).get("login") not in actors.get("request_actors", ())
                    or not isinstance(row.get("title"), str) or not isinstance(row.get("body"), str)
                ):
                    raise ValueError("CATALOG_ACTIVE_REQUEST_INVALID")
                active_request = parse_catalog_run_request(row["title"], row["body"], public_key)
                active_campaigns.add(active_request.campaign_key)
                if active_request.request_id == request.request_id:
                    if active_request.intent_sha256 != request.intent_sha256:
                        raise ValueError("CATALOG_FAST_INTENT_CONFLICT")
                    matches.append((number, active_request))
            if not matches:
                terminal_inventory = client.stable_paginated(
                    f"/repos/{repository}/issues?state=all&labels=catalog-run-terminal-v1", root="list",
                )
                if terminal_inventory.stable is not True or terminal_inventory.collection.complete is not True:
                    raise ValueError("CATALOG_TERMINAL_REQUEST_INVENTORY_INCOMPLETE")
                for row in terminal_inventory.collection.rows:
                    number = row.get("number")
                    if (
                        number == current_issue_number or type(number) is not int or number < 1
                        or row.get("user", {}).get("login") not in actors.get("request_actors", ())
                        or not isinstance(row.get("title"), str) or not isinstance(row.get("body"), str)
                    ):
                        continue
                    try:
                        terminal_request = parse_catalog_run_request(row["title"], row["body"], public_key)
                    except ValueError:
                        continue
                    if terminal_request.campaign_key == request.campaign_key:
                        terminal_generations.append((terminal_request, row))
                    if terminal_request.request_id == request.request_id:
                        if terminal_request.intent_sha256 != request.intent_sha256:
                            raise ValueError("CATALOG_FAST_INTENT_CONFLICT")
                        matches.append((number, terminal_request))
            if len(matches) > 1:
                raise ValueError("CATALOG_FAST_OWNER_AMBIGUOUS")
            if matches:
                owner_issue_number, original_request = matches[0]
                durable_owner = True
                resolved = lookup_owner(owner_issue_number, original_request)
                if isinstance(resolved, FastGateAliasEvidence):
                    raise ValueError("CATALOG_FAST_ALIAS_CHAIN_NOT_ALLOWED")
                if alias_target is not None and (resolved is None or resolved.run_id != alias_target):
                    raise ValueError("CATALOG_FAST_ALIAS_TARGET_CONFLICT")
                owner = resolved
            if not matches and not durable_owner and request.campaign_key not in active_campaigns:
                latest_generation = max((item.launch_generation for item, _ in terminal_generations), default=0)
                if request.launch_generation != latest_generation + 1:
                    raise ValueError("CATALOG_FAST_GENERATION_CONFLICT")
                previous = [pair for pair in terminal_generations if pair[0].launch_generation == latest_generation]
                if len(previous) > 1:
                    raise ValueError("CATALOG_FAST_OWNER_AMBIGUOUS")
                previous_hash = previous[0][0].request_sha256 if previous else None
                if request.previous_terminal_request_sha256 != previous_hash:
                    raise ValueError("CATALOG_FAST_PREDECESSOR_CONFLICT")
                if previous:
                    previous_request, previous_row = previous[0]
                    number = previous_row["number"]
                    previous_raw, _ = client.get_json(f"/repos/{repository}/issues/{number}")
                    previous_issue = _mapping(previous_raw, "CATALOG_FAST_PREDECESSOR_INVALID")
                    previous_closer = _mapping(previous_issue.get("closed_by"), "CATALOG_FAST_PREDECESSOR_INVALID")
                    previous_actor = _mapping(previous_issue.get("user"), "CATALOG_FAST_PREDECESSOR_INVALID")
                    if (
                        previous_issue.get("number") != number
                        or previous_issue.get("state") != "closed"
                        or previous_issue.get("state_reason") != "completed"
                        or not isinstance(actors.get("ledger_actor"), str)
                        or previous_closer.get("login") != actors["ledger_actor"]
                        or previous_actor.get("login") not in actors.get("request_actors", ())
                        or not isinstance(previous_issue.get("title"), str) or not isinstance(previous_issue.get("body"), str)
                        or parse_catalog_run_request(previous_issue["title"], previous_issue["body"], public_key) != previous_request
                        or "catalog-run-terminal-v1" not in {label.get("name") for label in previous_issue.get("labels", ()) if isinstance(label, Mapping)}
                        or not _utc(previous_issue.get("created_at")) <= _utc(previous_issue.get("closed_at")) <= _utc(issue.get("created_at")) <= client.observed_at
                    ):
                        raise ValueError("CATALOG_FAST_PREDECESSOR_INVALID")
    except (CatalogGitHubSnapshotError, ValueError, OSError, subprocess.SubprocessError) as exc:
        lookup_error = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"CATALOG_[A-Z0-9_]+", lookup_error):
            lookup_error = "CATALOG_FAST_OWNER_LOOKUP_UNAVAILABLE"
    if owner is not None or lookup_error is not None or durable_owner:
        terminal_receipt = None
        state = "BLOCKED"
        reason = lookup_error or "CATALOG_FAST_OWNER_ORIGINAL_EVIDENCE_MISSING"
        preparation_error = context.get("preparation_error")
        if owner is None and lookup_error is None and isinstance(preparation_error, str) and re.fullmatch(r"CATALOG_[A-Z0-9_]+", preparation_error):
            reason = preparation_error
        if owner is not None:
            if owner.run.get("status") in {"queued", "in_progress", "waiting", "pending", "requested"}:
                state, reason = "QUEUED", "CATALOG_FAST_EXISTING_RUN"
            else:
                reason = "CATALOG_FAST_OWNER_TERMINAL_EVIDENCE_REQUIRED"
                try:
                    terminal_receipt = load_owner_terminal_receipt(
                        client=client, owner=owner, issue_number=owner_issue_number,
                        download_archive=lambda artifact_id: _download_owner_archive(repository, token, artifact_id),
                    )
                    if terminal_receipt is not None and pinned_terminal_sha256 is not None and terminal_receipt.receipt_sha256 != pinned_terminal_sha256:
                        terminal_receipt = None
                        raise ValueError("CATALOG_FAST_AUTHORITY_TERMINAL_CONFLICT")
                except (CatalogGitHubSnapshotError, ValueError, OSError, subprocess.SubprocessError) as exc:
                    reason = str(exc).split(":", 1)[0]
                    if not re.fullmatch(r"CATALOG_[A-Z0-9_]+", reason):
                        reason = "CATALOG_FAST_OWNER_TERMINAL_LOOKUP_UNAVAILABLE"
                if terminal_receipt is not None:
                    state, reason = terminal_receipt.state, terminal_receipt.reason_code
        replay = CatalogFastLaunchDecisionV1.create(
            state=state, reason_code=reason, request_sha256=request.request_sha256,
            submission_key_sha256=request.submission_key_sha256, campaign_key=request.campaign_key,
            prepared_receipt_sha256=owner.decision.prepared_receipt_sha256 if owner else None,
            selected_workers=0, launch_required=False, existing_run_id=owner.run_id if owner else None,
            decided_at=client.observed_at, expires_at=_utc(context.get("issue_created_at")) + timedelta(minutes=30),
        )
        _write_replay_decision(replay, output_dir=output_dir, github_output=github_output, terminal_receipt=terminal_receipt)
        return replay
    identity = CatalogPreparationIdentityV1.model_validate(context.get("identity"))
    registry = load_catalog_campaign_registry(root / "config/catalog_campaign_registry_v1.json")
    entry = resolve_catalog_campaign(registry, request.campaign_key, root)
    safe_capacity_raw = os.environ.get("CATALOG_SAFE_FREE_CAPACITY", "")
    try:
        safe_capacity = int(safe_capacity_raw)
    except ValueError as exc:
        raise ValueError("CATALOG_WORKER_CEILING_INVALID") from exc
    snapshot = CatalogFastGateSnapshotV1(
        schema_version="1",
        observed_at=client.observed_at,
        protected_commit_sha=expected_commit,
        controller_enabled=_bool_env("CATALOG_CONTROLLER_ENABLED"),
        production_armed=_bool_env("CATALOG_CONTROLLER_PRODUCTION_ARMED"),
        current_safe_free_capacity=safe_capacity,
        existing_launches=(),
        active_campaign_keys=tuple(sorted(active_campaigns)),
    )
    issue_created_at = _utc(context.get("issue_created_at"))
    expires_at = issue_created_at + timedelta(minutes=30)
    prepared = None
    if request.campaign_key in active_campaigns:
        decision = _blocked(
            request=request,
            prepared_receipt_sha256=None,
            now=snapshot.observed_at,
            expires_at=expires_at,
            reason_code="CATALOG_CAMPAIGN_BUSY",
        )
    elif not bundle.is_dir() or prepared_bundle.is_symlink():
        decision = _blocked(
            request=request,
            prepared_receipt_sha256=None,
            now=snapshot.observed_at,
            expires_at=expires_at,
            reason_code="CATALOG_PREPARATION_REQUIRED",
        )
    else:
        try:
            prepared, _ = verify_prepared_catalog_bundle(
                bundle_dir=bundle,
                expected_identity=identity,
            )
            store_index = CatalogRebuildableStoreIndexV1.model_validate(
                _strict_json(
                    bundle / "evidence/catalog-rebuildable-store-index-v1.json"
                )
            )
            if store_index.index_sha256 != prepared.component_store_manifest_sha256:
                raise ValueError("CATALOG_PREPARATION_STORE_INDEX_MISMATCH")
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            decision = _blocked(
                request=request,
                prepared_receipt_sha256=None,
                now=snapshot.observed_at,
                expires_at=expires_at,
                reason_code="CATALOG_PREPARATION_INVALID",
            )
        else:
            cache_inventory = client.stable_paginated(
                f"/repos/{repository}/actions/caches?ref=refs/heads/main",
                root="actions_caches",
            )
            caches = cache_inventory.collection
            live_cache_keys = {
                str(row.get("key"))
                for row in caches.rows
                if row.get("ref") == "refs/heads/main"
            }
            indexed_cache_keys = {
                candidate.cache_key
                for candidate in store_index.candidates
                if candidate.cache_key is not None
            }
            required_cache_keys = set(prepared.required_cache_keys)
            if cache_inventory.stable is not True or caches.complete is not True:
                decision = _blocked(
                    request=request,
                    prepared_receipt_sha256=prepared.receipt_sha256,
                    now=snapshot.observed_at,
                    expires_at=expires_at,
                    reason_code="CATALOG_PREPARATION_CACHE_INVENTORY_INCOMPLETE",
                )
            elif indexed_cache_keys != required_cache_keys:
                decision = _blocked(
                    request=request,
                    prepared_receipt_sha256=prepared.receipt_sha256,
                    now=snapshot.observed_at,
                    expires_at=expires_at,
                    reason_code="CATALOG_PREPARATION_INVALID",
                )
            elif not required_cache_keys.issubset(live_cache_keys):
                decision = _blocked(
                    request=request,
                    prepared_receipt_sha256=prepared.receipt_sha256,
                    now=snapshot.observed_at,
                    expires_at=expires_at,
                    reason_code="CATALOG_PREPARATION_CACHE_MISSING",
                )
            else:
                decision = decide_fast_catalog_launch(
                    request=request,
                    registry_entry=entry,
                    prepared_receipt=prepared,
                    expected_preparation_identity=identity,
                    snapshot=snapshot,
                    issue_created_at=issue_created_at,
                )
                if decision.launch_required and (
                    decision.selected_workers != prepared.qualified_worker_ceiling
                ):
                    decision = _blocked(
                        request=request,
                        prepared_receipt_sha256=prepared.receipt_sha256,
                        now=snapshot.observed_at,
                        expires_at=expires_at,
                        reason_code="CATALOG_FAST_CONFIGURATION_UNAVAILABLE",
                    )

    output_dir.mkdir(parents=False, exist_ok=False)
    decision_path = output_dir / "catalog-fast-decision-v1.json"
    decision_path.write_text(
        json.dumps(
            decision.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    sealed_receipt: Mapping[str, Any] | None = None
    if decision.launch_required:
        sealed_receipt = materialize_prepared_catalog_plan(
            bundle_dir=bundle,
            expected_identity=identity,
            request_sha256=request.request_sha256,
            decision_sha256=decision.decision_sha256,
            output_dir=output_dir / "sealed-plan",
        )
    outputs = {
        "preserve_issue": "false",
        "launch_required": str(decision.launch_required).lower(),
        "existing_run_id": str(decision.existing_run_id) if decision.existing_run_id is not None else "",
        "campaign_state": decision.state,
        "reason_code": decision.reason_code,
        "request_sha256": request.request_sha256,
        "submission_key_sha256": request.submission_key_sha256,
        "prepared_receipt_sha256": (
            prepared.receipt_sha256 if prepared is not None else ""
        ),
        "decision_sha256": decision.decision_sha256,
        "selected_workers": str(decision.selected_workers),
        "authority_id": str(sealed_receipt.get("authority_id", "")) if sealed_receipt else "",
        "campaign_id": str(sealed_receipt.get("campaign_id", "")) if sealed_receipt else "",
        "science_sha256": str(sealed_receipt.get("science_sha256", "")) if sealed_receipt else "",
        "execution_plan_sha256": str(sealed_receipt.get("execution_plan_sha256", "")) if sealed_receipt else "",
        "execution_protocol_sha256": str(sealed_receipt.get("execution_protocol_sha256", "")) if sealed_receipt else "",
        "protected_commit_sha": expected_commit,
    }
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in outputs.items():
            if "\n" in value:
                raise ValueError("CATALOG_FAST_GATE_OUTPUT_INVALID")
            stream.write(f"{key}={value}\n")
    return decision


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runner_temp = os.environ.get("RUNNER_TEMP", "")
        authority_path = Path(runner_temp) / "catalog-fast-authority-current.json"
        if not runner_temp or authority_path.is_symlink() or not authority_path.is_file():
            raise ValueError("CATALOG_FAST_AUTHORITY_SNAPSHOT_REQUIRED")
        try:
            if authority_path.stat().st_size > 256 * 1024:
                raise ValueError("snapshot too large")
            FastAuthorityStateV1.model_validate(_strict_json(authority_path))
        except (ValueError, OSError) as exc:
            raise ValueError("CATALOG_FAST_AUTHORITY_SNAPSHOT_INVALID") from exc
        admit_request(
            request_context_path=args.request_context,
            prepared_bundle=args.prepared_bundle,
            repo_root=args.repo_root,
            output_dir=args.output_dir,
            github_output=args.github_output,
        )
        return 0
    except (CatalogGitHubSnapshotError, json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

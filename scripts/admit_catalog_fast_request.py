#!/usr/bin/env python3
"""Run the single live gate and materialize one already-prepared plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogFastGateSnapshotV1,
    CatalogFastLaunchDecisionV1,
    CatalogPreparationIdentityV1,
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
    ):
        raise ValueError("CATALOG_FAST_REQUEST_CONTEXT_INVALID")
    request = CatalogRunRequestV1.model_validate(context.get("request"))
    identity = CatalogPreparationIdentityV1.model_validate(context.get("identity"))
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, request.campaign_key, root)

    client = CatalogGitHubReadOnlyClient(repository, token)
    active_issues = client.stable_paginated(
        f"/repos/{repository}/issues?state=open&labels=catalog-run-active-v1",
        root="list",
    ).collection
    if client.observed_at is None:
        raise ValueError("CATALOG_FAST_GATE_GITHUB_TIME_INVALID")
    actors = _mapping(
        _strict_json(root / "config/catalog_controller_actors_v1.json"),
        "CATALOG_FAST_REQUEST_ACTOR_INVALID",
    )
    public_key_path = actors.get("requester_public_key_path")
    if not isinstance(public_key_path, str):
        raise ValueError("CATALOG_REQUESTER_KEY_UNAVAILABLE")
    public_key = (root / public_key_path).read_bytes()
    current_issue_number = context.get("issue_number")
    active_campaigns: set[str] = set()
    for row in active_issues.rows:
        if row.get("number") == current_issue_number:
            continue
        title = row.get("title")
        body = row.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError("CATALOG_ACTIVE_REQUEST_INVALID")
        try:
            active_request = parse_catalog_run_request(title, body, public_key)
        except ValueError as exc:
            raise ValueError("CATALOG_ACTIVE_REQUEST_INVALID") from exc
        active_campaigns.add(active_request.campaign_key)

    terminal_issues = client.stable_paginated(
        f"/repos/{repository}/issues?state=all&labels=catalog-run-terminal-v1",
        root="list",
    ).collection
    terminal_submission_keys: set[str] = set()
    for row in terminal_issues.rows:
        if row.get("number") == current_issue_number:
            continue
        title = row.get("title")
        body = row.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            continue
        try:
            terminal_request = parse_catalog_run_request(title, body, public_key)
        except ValueError:
            continue
        terminal_submission_keys.add(terminal_request.submission_key_sha256)

    labels = set(str(item) for item in context.get("issue_labels", ()))
    active_label = "catalog-run-active-v1"
    terminal_label = "catalog-run-terminal-v1"
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
    if (
        terminal_label in labels
        or request.submission_key_sha256 in terminal_submission_keys
    ):
        decision = _blocked(
            request=request,
            prepared_receipt_sha256=None,
            now=snapshot.observed_at,
            expires_at=expires_at,
            reason_code="CATALOG_REQUEST_ALREADY_TERMINAL",
        )
    elif active_label in labels:
        decision = _blocked(
            request=request,
            prepared_receipt_sha256=None,
            now=snapshot.observed_at,
            expires_at=expires_at,
            reason_code="CATALOG_REQUEST_ALREADY_ACTIVE",
        )
    elif request.campaign_key in active_campaigns:
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
            caches = client.stable_paginated(
                f"/repos/{repository}/actions/caches?ref=refs/heads/main",
                root="actions_caches",
            ).collection
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
            if indexed_cache_keys != required_cache_keys:
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
        "launch_required": str(decision.launch_required).lower(),
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

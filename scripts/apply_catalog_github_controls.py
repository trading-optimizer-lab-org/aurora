#!/usr/bin/env python3
"""Exact catalog GitHub-controls reconciler; dry-run unless explicitly armed."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[1]


def _pin_aurora_source_checkout() -> None:
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if not getattr(finder, "__module__", "").startswith(
            "__editable___aurora_"
        )
    ]
    for name in tuple(sys.modules):
        if name.startswith("aurora."):
            del sys.modules[name]
    source_init = ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "aurora",
        source_init,
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("AURORA_SOURCE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules["aurora"] = module
    spec.loader.exec_module(module)


_pin_aurora_source_checkout()

from aurora.infra.sp500_megarun.catalog_github_controls import (
    CatalogGithubControlsReceiptV1,
    audit_catalog_github_controls,
    bootstrap_controls_prepared,
    build_github_controls_mutation_plan,
    github_controls_state_sha256,
    load_catalog_github_auditor,
    load_catalog_github_controls,
)

try:
    from scripts.audit_catalog_github_controls import (
        ACCEPT,
        GhReadOnlyClient,
        collect_live_snapshot,
        load_snapshot_directory,
        write_json,
    )
except ModuleNotFoundError:  # Direct script execution puts scripts/ on sys.path.
    from audit_catalog_github_controls import (  # type: ignore[no-redef]
        ACCEPT,
        GhReadOnlyClient,
        collect_live_snapshot,
        load_snapshot_directory,
        write_json,
    )


REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CONFIRMATION = "CATALOG_GITHUB_CONTROLS_V1"
_RECEIPT_ADAPTER = TypeAdapter(CatalogGithubControlsReceiptV1)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _load_verified_zero_mutation_dry_run(
    path: Path,
    *,
    repository: str,
    expected_state_sha: str,
    desired: object,
) -> object:
    text = path.read_text("utf-8")
    value = json.loads(text)
    if text != _canonical_json(value) + "\n":
        raise ValueError("CATALOG_GITHUB_VERIFIED_DRY_RUN_INVALID")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1"
        or value.get("mode") != "dry_run"
        or value.get("repository") != repository
        or value.get("current_state_sha256") != expected_state_sha
        or value.get("mutations") != []
        or value.get("after_receipt") is not None
    ):
        raise ValueError("CATALOG_GITHUB_VERIFIED_DRY_RUN_INVALID")
    receipt = _RECEIPT_ADAPTER.validate_python(value.get("before_receipt"))
    plan = build_github_controls_mutation_plan(desired=desired, receipt=receipt)
    if (
        plan.mutations
        or value.get("current_receipt_sha256") != receipt.receipt_sha256
        or github_controls_state_sha256(receipt) != expected_state_sha
        or value.get("plan_sha256") != plan.plan_sha256
    ):
        raise ValueError("CATALOG_GITHUB_VERIFIED_DRY_RUN_INVALID")
    return receipt


class GhMutationClient:
    """Narrow argument-array adapter for mutations already sealed in a plan."""

    def __init__(self, *, api_version: str) -> None:
        self.api_version = api_version

    def mutate(
        self,
        *,
        method: str,
        endpoint: str,
        body: dict[str, object],
    ) -> object:
        if method not in {"PUT", "POST", "PATCH"}:
            raise ValueError("CATALOG_GITHUB_MUTATION_METHOD_FORBIDDEN")
        if not endpoint.startswith("/") or any(
            token in endpoint for token in ("\r", "\n", "\x00")
        ):
            raise ValueError("CATALOG_GITHUB_MUTATION_ENDPOINT_INVALID")
        completed = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                method,
                "-H",
                f"Accept: {ACCEPT}",
                "-H",
                f"X-GitHub-Api-Version: {self.api_version}",
                "--input",
                "-",
                endpoint,
            ],
            input=_canonical_json(body),
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                "CATALOG_GITHUB_MUTATION_FAILED: "
                f"{method} {endpoint}: {completed.stderr.strip()}"
            )
        if not completed.stdout.strip():
            return None
        return json.loads(completed.stdout)

    def get(self, endpoint: str) -> object:
        if not endpoint.startswith("/") or any(
            token in endpoint for token in ("\r", "\n", "\x00")
        ):
            raise ValueError("CATALOG_GITHUB_MUTATION_ENDPOINT_INVALID")
        completed = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                "-H",
                f"Accept: {ACCEPT}",
                "-H",
                f"X-GitHub-Api-Version: {self.api_version}",
                endpoint,
            ],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                "CATALOG_GITHUB_MUTATION_READ_FAILED: "
                f"GET {endpoint}: {completed.stderr.strip()}"
            )
        return json.loads(completed.stdout)


def _cache_retention_value(client: object, endpoint: str) -> int:
    payload = client.get(endpoint)  # type: ignore[attr-defined]
    value = payload.get("max_cache_retention_days") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("CATALOG_CACHE_RETENTION_UNKNOWN")
    return value


def apply_cache_retention_transaction(
    client: object,
    *,
    desired: object,
    receipt: CatalogGithubControlsReceiptV1,
    plan: object,
) -> list[object]:
    """Apply the sealed three-level retention change with verified rollback."""

    control_plane = desired.billing.budget_control_plane  # type: ignore[attr-defined]
    minimum = desired.billing.repository_cache_retention_days  # type: ignore[attr-defined]
    endpoints = (
        f"/enterprises/{control_plane.enterprise}/actions/cache/retention-limit",
        f"/organizations/{control_plane.organization_id}/actions/cache/retention-limit",
        f"/repos/{receipt.repository}/actions/cache/retention-limit",
    )
    retention_mutations = tuple(
        mutation
        for mutation in plan.mutations  # type: ignore[attr-defined]
        if "CACHE_RETENTION_POLICY_REQUIRED" in mutation.reason_codes
    )
    if not retention_mutations:
        return []
    if (
        len(retention_mutations) != 3
        or tuple(mutation.endpoint for mutation in retention_mutations) != endpoints
        or any(mutation.method != "PUT" for mutation in retention_mutations)
    ):
        raise ValueError("CATALOG_CACHE_RETENTION_PLAN_INVALID")

    originals = tuple(_cache_retention_value(client, endpoint) for endpoint in endpoints)
    sealed_originals = (
        receipt.enterprise_cache_retention_days,
        receipt.organization_cache_retention_days,
        receipt.repository_cache_retention_days,
    )
    if originals != sealed_originals:
        raise ValueError("CATALOG_CACHE_RETENTION_PLAN_STALE")

    targets: list[int] = []
    for mutation, original in zip(retention_mutations, originals, strict=True):
        target = mutation.body.get("max_cache_retention_days")
        if (
            isinstance(target, bool)
            or not isinstance(target, int)
            or target != max(original, minimum)
            or target < original
        ):
            raise ValueError("CATALOG_CACHE_RETENTION_PLAN_INVALID")
        targets.append(target)

    mutated: list[tuple[str, int]] = []
    responses: list[object] = []
    try:
        for mutation, target, original in zip(
            retention_mutations, targets, originals, strict=True
        ):
            response = client.mutate(  # type: ignore[attr-defined]
                method="PUT",
                endpoint=mutation.endpoint,
                body={"max_cache_retention_days": target},
            )
            mutated.append((mutation.endpoint, original))
            observed = _cache_retention_value(client, mutation.endpoint)
            if observed != target:
                raise ValueError("CATALOG_CACHE_RETENTION_READBACK_INVALID")
            responses.append(
                {
                    "endpoint": mutation.endpoint,
                    "response": response,
                    "readback": observed,
                }
            )
    except Exception as transaction_error:
        rollback_errors: list[str] = []
        for endpoint, original in reversed(mutated):
            try:
                client.mutate(  # type: ignore[attr-defined]
                    method="PUT",
                    endpoint=endpoint,
                    body={"max_cache_retention_days": original},
                )
                if _cache_retention_value(client, endpoint) != original:
                    raise ValueError("ROLLBACK_READBACK_INVALID")
            except Exception as rollback_error:
                rollback_errors.append(f"{endpoint}:{rollback_error}")
        if rollback_errors:
            raise ValueError(
                "CATALOG_CACHE_RETENTION_ROLLBACK_FAILED:"
                + "|".join(rollback_errors)
            ) from transaction_error
        raise ValueError("CATALOG_CACHE_RETENTION_TRANSACTION_FAILED") from transaction_error
    return responses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and plan exact catalog GitHub controls. No mutation occurs "
            "unless --apply, the current control-state hash, and the fixed confirmation "
            "are all supplied."
        )
    )
    parser.add_argument(
        "--repository",
        default="trading-optimizer-lab-org/aurora",
    )
    parser.add_argument(
        "--desired",
        type=Path,
        default=ROOT / "config/catalog_github_controls_v1.json",
    )
    parser.add_argument(
        "--auditor",
        type=Path,
        default=ROOT / "config/catalog_github_auditor_v1.json",
    )
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--bootstrap-controls-only", action="store_true")
    parser.add_argument("--verified-dry-run", type=Path)
    parser.add_argument("--expected-current-state-sha")
    parser.add_argument("--confirm")
    return parser


def _live_snapshot(args: argparse.Namespace, desired: object, auditor: object) -> dict[str, object]:
    client = GhReadOnlyClient(api_version=desired.github_api_version)
    observed_commit = client.get(
        f"/repos/{args.repository}/commits/{desired.default_branch}"
    )
    if not isinstance(observed_commit, dict) or not isinstance(
        observed_commit.get("sha"), str
    ):
        raise ValueError("CATALOG_DEFAULT_BRANCH_SHA_UNAVAILABLE")
    observed_default_sha = observed_commit["sha"]
    return collect_live_snapshot(
        client=client,
        desired=desired,
        auditor=auditor,
        repository=args.repository,
        observer_context="bootstrap_local",
        caller_workflow=".github/workflows/catalog-run-controller.yml",
        caller_job="live_controls_audit_before_reserve",
        purpose="admission",
        audit_context_sha256="0" * 64,
        protected_commit_sha=observed_default_sha,
        repo_root=args.repo_root,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not REPOSITORY_PATTERN.fullmatch(args.repository):
            raise ValueError("CATALOG_REPOSITORY_INVALID")
        desired = load_catalog_github_controls(args.desired)
        auditor = load_catalog_github_auditor(args.auditor)
        if args.repository != desired.repository_identity.full_name:
            raise ValueError("CATALOG_REPOSITORY_UNEXPECTED")
        if args.verified_dry_run is not None and (
            not args.apply or not args.bootstrap_controls_only
        ):
            raise ValueError("CATALOG_GITHUB_VERIFIED_DRY_RUN_MODE_INVALID")
        if args.apply:
            if args.confirm != CONFIRMATION:
                raise ValueError("CATALOG_GITHUB_CONTROLS_CONFIRMATION_REQUIRED")
            if not isinstance(args.expected_current_state_sha, str) or not re.fullmatch(
                r"[0-9a-f]{64}", args.expected_current_state_sha
            ):
                raise ValueError("CATALOG_GITHUB_CONTROLS_EXPECTED_SHA_REQUIRED")
        if args.verified_dry_run is not None:
            prior = _load_verified_zero_mutation_dry_run(
                args.verified_dry_run,
                repository=args.repository,
                expected_state_sha=args.expected_current_state_sha,
                desired=desired,
            )
            fresh_snapshots = _live_snapshot(args, desired, auditor)
            fresh = audit_catalog_github_controls(
                desired=desired,
                auditor=auditor,
                snapshots=fresh_snapshots,
            )
            fresh_plan = build_github_controls_mutation_plan(
                desired=desired,
                receipt=fresh,
            )
            if fresh_plan.mutations:
                raise ValueError("CATALOG_GITHUB_CONTROLS_STALE")
            prepared = bootstrap_controls_prepared(fresh)
            if fresh.status != "ready" and not prepared:
                raise ValueError("CATALOG_GITHUB_CONTROLS_RECONCILIATION_INCOMPLETE")
            result = {
                "schema_version": "1",
                "mode": "apply",
                "repository": args.repository,
                "before_receipt": prior.model_dump(mode="json"),
                "current_receipt_sha256": fresh.receipt_sha256,
                "current_state_sha256": github_controls_state_sha256(fresh),
                "plan_sha256": fresh_plan.plan_sha256,
                "mutations": [],
                "api_responses": [],
                "after_receipt": fresh.model_dump(mode="json"),
                "bootstrap_controls_prepared": prepared,
            }
            write_json(args.output, result)
            print(
                _canonical_json(
                    {
                        "mode": "bootstrap_prepared" if prepared else "apply",
                        "mutation_count": 0,
                        "receipt_sha256": fresh.receipt_sha256,
                        "output": str(args.output),
                    }
                )
            )
            return 0
        snapshots = (
            load_snapshot_directory(args.snapshot_dir)
            if args.snapshot_dir is not None
            else _live_snapshot(args, desired, auditor)
        )
        before = audit_catalog_github_controls(
            desired=desired,
            auditor=auditor,
            snapshots=snapshots,
        )
        before_state_sha = github_controls_state_sha256(before)
        plan = build_github_controls_mutation_plan(
            desired=desired,
            receipt=before,
        )
        result: dict[str, object] = {
            "schema_version": "1",
            "mode": "apply" if args.apply else "dry_run",
            "repository": args.repository,
            "before_receipt": before.model_dump(mode="json"),
            "current_receipt_sha256": before.receipt_sha256,
            "current_state_sha256": before_state_sha,
            "plan_sha256": plan.plan_sha256,
            "mutations": [
                mutation.model_dump(mode="json") for mutation in plan.mutations
            ],
            "api_responses": [],
            "after_receipt": None,
        }
        if not args.apply:
            write_json(args.output, result)
            print(
                _canonical_json(
                    {
                        "mode": "dry_run",
                        "mutation_count": len(plan.mutations),
                        "plan_sha256": plan.plan_sha256,
                        "output": str(args.output),
                    }
                )
            )
            return 0
        fresh_snapshots = (
            load_snapshot_directory(args.snapshot_dir)
            if args.snapshot_dir is not None
            else _live_snapshot(args, desired, auditor)
        )
        fresh = audit_catalog_github_controls(
            desired=desired,
            auditor=auditor,
            snapshots=fresh_snapshots,
        )
        fresh_state_sha = github_controls_state_sha256(fresh)
        if (
            fresh_state_sha != args.expected_current_state_sha
            or fresh_state_sha != before_state_sha
        ):
            raise ValueError("CATALOG_GITHUB_CONTROLS_STALE")
        if args.snapshot_dir is not None:
            raise ValueError("CATALOG_GITHUB_SNAPSHOT_APPLY_FORBIDDEN")

        mutation_client = GhMutationClient(api_version=desired.github_api_version)
        responses: list[object] = []
        retention_applied = False
        for mutation in plan.mutations:
            if "CACHE_RETENTION_POLICY_REQUIRED" in mutation.reason_codes:
                if not retention_applied:
                    responses.extend(
                        apply_cache_retention_transaction(
                            mutation_client,
                            desired=desired,
                            receipt=fresh,
                            plan=plan,
                        )
                    )
                    retention_applied = True
                continue
            responses.append(
                mutation_client.mutate(
                    method=mutation.method,
                    endpoint=mutation.endpoint,
                    body=dict(mutation.body),
                )
            )
        after_snapshots = _live_snapshot(args, desired, auditor)
        after = audit_catalog_github_controls(
            desired=desired,
            auditor=auditor,
            snapshots=after_snapshots,
        )
        prepared = args.bootstrap_controls_only and bootstrap_controls_prepared(after)
        if after.status != "ready" and not prepared:
            raise ValueError("CATALOG_GITHUB_CONTROLS_RECONCILIATION_INCOMPLETE")
        result["api_responses"] = responses
        result["after_receipt"] = after.model_dump(mode="json")
        result["bootstrap_controls_prepared"] = prepared
        write_json(args.output, result)
        print(
            _canonical_json(
                {
                    "mode": "bootstrap_prepared" if prepared else "apply",
                    "mutation_count": len(plan.mutations),
                    "receipt_sha256": after.receipt_sha256,
                    "output": str(args.output),
                }
            )
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

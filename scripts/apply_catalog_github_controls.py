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
    audit_catalog_github_controls,
    bootstrap_controls_prepared,
    build_github_controls_mutation_plan,
    load_catalog_github_auditor,
    load_catalog_github_controls,
)

from audit_catalog_github_controls import (
    ACCEPT,
    GhReadOnlyClient,
    collect_live_snapshot,
    load_snapshot_directory,
    write_json,
)


REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CONFIRMATION = "CATALOG_GITHUB_CONTROLS_V1"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and plan exact catalog GitHub controls. No mutation occurs "
            "unless --apply, the current receipt hash, and the fixed confirmation "
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
    parser.add_argument("--expected-current-sha")
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
        if args.confirm != CONFIRMATION:
            raise ValueError("CATALOG_GITHUB_CONTROLS_CONFIRMATION_REQUIRED")
        if not isinstance(args.expected_current_sha, str) or not re.fullmatch(
            r"[0-9a-f]{64}", args.expected_current_sha
        ):
            raise ValueError("CATALOG_GITHUB_CONTROLS_EXPECTED_SHA_REQUIRED")

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
        if (
            fresh.receipt_sha256 != args.expected_current_sha
            or fresh.receipt_sha256 != before.receipt_sha256
        ):
            raise ValueError("CATALOG_GITHUB_CONTROLS_STALE")
        if args.snapshot_dir is not None:
            raise ValueError("CATALOG_GITHUB_SNAPSHOT_APPLY_FORBIDDEN")

        mutation_client = GhMutationClient(api_version=desired.github_api_version)
        responses: list[object] = []
        for mutation in plan.mutations:
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

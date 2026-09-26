#!/usr/bin/env python3
"""Re-verify the fixed Atlas-1 source run without evaluating science again."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.infra.sp500_megarun.catalog_atlas_terminal_adapter import (
    build_terminal_receipt, read_json, verify_atlas_terminal_evidence,
)
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceiptV2
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient, CatalogGitHubSnapshotError
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.admit_catalog_fast_request import _historical_owner_commit_approved

REPOSITORY = "trading-optimizer-lab-org/aurora"
SOURCE_RUN_ID = 36032882147
SOURCE_COMMIT = "adf5f5839134cea3309fe48aae5fc1b3df75a017"
ISSUE_NUMBER = 378
REQUEST_SHA = "4fe5767ac61c2b8ac92adce450bd0d726801f033c5e7e3f29f8d40b59d281834"
OLD_RECEIPT_SHA = "b8918eee4510d094153756c02baa387c61d5623f91335d5f34707d9e5493ac7f"
SOURCE_ARTIFACTS = {
    "gate": (10823267210, "catalog-fast-gate-378", 3431, "sha256:c66054ad4168c3ec616d89b3a2465a7aa7d104b2e255eb8f3e0281b4287d6495"),
    "preflight": (10823467596, "sp500-atlas-preflight", 46976715, "sha256:1926344c4c018ac1c288e5004cc51c2962684183544a02b2e8b237fefba035c2"),
    "final": (10838302174, "sp500-atlas-final-results", 90319418, "sha256:405f3e408c927361d5b4e86502ce2ba2e8f5c56216010267ca9b6014126eb683"),
    "terminal": (10838522391, f"catalog-terminal-receipt-{REQUEST_SHA}", 1189, "sha256:6d924f05034503870c0d7f213f27276d80a251b4eaf835b36a6d393e921fde2a"),
}


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _require_environment(root: Path) -> tuple[CatalogGitHubReadOnlyClient, str]:
    token = os.environ.get("GH_TOKEN", "")
    commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_JOB") != "bootstrap"
        or os.environ.get("CATALOG_AUTHORITY_MAINTENANCE_OPERATION") != "atlas-terminal-correction-378"
        or not token or not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not root.is_dir() or root.is_symlink()):
        raise ValueError("ATLAS_TERMINAL_CORRECTION_ENVIRONMENT_INVALID")
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=10, check=False)
    if head.returncode != 0 or head.stdout.strip() != commit:
        raise ValueError("ATLAS_TERMINAL_CORRECTION_CHECKOUT_INVALID")
    return CatalogGitHubReadOnlyClient(REPOSITORY, token), commit


def _verify_source_metadata(client: CatalogGitHubReadOnlyClient, commit: str, root: Path) -> tuple[Mapping[str, Any], object]:
    run = _mapping(client.get_json(f"/repos/{REPOSITORY}/actions/runs/{SOURCE_RUN_ID}")[0], "ATLAS_CORRECTION_RUN_INVALID")
    if (run.get("id") != SOURCE_RUN_ID or run.get("run_attempt") != 1
        or run.get("path") != ".github/workflows/catalog-fast-controller.yml"
        or run.get("event") != "issues" or run.get("head_branch") != "main"
        or run.get("head_sha") != SOURCE_COMMIT
        or (run.get("status"), run.get("conclusion")) != ("completed", "success")
        or not _historical_owner_commit_approved(client, SOURCE_COMMIT, commit)):
        raise ValueError("ATLAS_CORRECTION_SOURCE_RUN_INVALID")
    jobs = client.stable_paginated(
        f"/repos/{REPOSITORY}/actions/runs/{SOURCE_RUN_ID}/attempts/1/jobs", root="jobs",
    )
    if jobs.stable is not True or jobs.collection.complete is not True or len(jobs.collection.rows) != 372:
        raise ValueError("ATLAS_CORRECTION_SOURCE_JOBS_INCOMPLETE")
    for artifact_id, name, size, digest in SOURCE_ARTIFACTS.values():
        artifact = _mapping(client.get_json(f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}")[0], "ATLAS_CORRECTION_ARTIFACT_INVALID")
        source = _mapping(artifact.get("workflow_run"), "ATLAS_CORRECTION_ARTIFACT_RUN_INVALID")
        if (artifact.get("id"), artifact.get("name"), artifact.get("size_in_bytes"), artifact.get("digest")) != (artifact_id, name, size, digest) or artifact.get("expired") is not False or (source.get("id"), source.get("head_sha")) != (SOURCE_RUN_ID, SOURCE_COMMIT):
            raise ValueError("ATLAS_CORRECTION_ARTIFACT_INVALID")
    issue = _mapping(client.get_json(f"/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}")[0], "ATLAS_CORRECTION_ISSUE_INVALID")
    actors = _mapping(read_json(root / "config/catalog_controller_actors_v1.json"), "ATLAS_CORRECTION_ACTORS_INVALID")
    key_path = (root / str(actors["requester_public_key_path"])).resolve(strict=True)
    if not key_path.is_relative_to(root):
        raise ValueError("ATLAS_CORRECTION_KEY_INVALID")
    request = parse_catalog_run_request(str(issue.get("title")), str(issue.get("body")), key_path.read_bytes())
    actor = _mapping(issue.get("user"), "ATLAS_CORRECTION_ISSUE_INVALID").get("login")
    if (issue.get("number") != ISSUE_NUMBER or issue.get("state") != "closed"
        or actor not in actors["request_actors"] or request.request_sha256 != REQUEST_SHA
        or request.campaign_key != "sp500-atlas-v1" or request.launch_generation != 3):
        raise ValueError("ATLAS_CORRECTION_SIGNED_REQUEST_INVALID")
    return run, jobs.collection.rows


def prepare(*, root: Path, gate: Path, preflight: Path, final: Path, old_terminal: Path,
            output: Path, proof_output: Path, client: CatalogGitHubReadOnlyClient,
            protected_commit: str) -> CatalogTerminalReceiptV2:
    run, jobs = _verify_source_metadata(client, protected_commit, root)
    old = CatalogTerminalReceiptV2.model_validate(read_json(old_terminal, "ATLAS_CORRECTION_OLD_RECEIPT_INVALID"))
    if (old.receipt_sha256 != OLD_RECEIPT_SHA or old.request_sha256 != REQUEST_SHA
        or old.engine_run_id != SOURCE_RUN_ID or old.state != "BLOCKED"
        or old.reason_code != "ATLAS_TERMINAL_CATALOG_HASH_INVALID"):
        raise ValueError("ATLAS_CORRECTION_OLD_RECEIPT_INVALID")
    context_path = gate / "catalog-fast-request-context.json"
    decision_path = gate / "catalog-fast-decision-v1.json"
    context = _mapping(read_json(context_path), "ATLAS_CORRECTION_CONTEXT_INVALID")
    if context.get("issue_number") != ISSUE_NUMBER or context.get("protected_commit_sha") != SOURCE_COMMIT:
        raise ValueError("ATLAS_CORRECTION_CONTEXT_INVALID")
    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        run_path = Path(scratch) / "run.json"
        jobs_path = Path(scratch) / "jobs.json"
        run_path.write_text(json.dumps(run), encoding="utf-8")
        jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        _, request, decision, verification = verify_atlas_terminal_evidence(
            repo_root=root, context_path=context_path, decision_path=decision_path,
            run_path=run_path, jobs_path=jobs_path, preflight_root=preflight,
            final_root=final, completed_source=True, gate_result="success",
        )
    if (verification.state != "SUCCESS" or verification.observed_recipe_count != 209906
        or verification.expected_recipe_count != 209906 or request.request_sha256 != REQUEST_SHA
        or verification.run_id != SOURCE_RUN_ID or verification.plan_sha256 != "bd79d52474fbffba864915f004d9a63114b9d48d235d7502c328c423ad7ddd82"
        or verification.result_science_sha256 != "18e614ffd8ef079fe7f6488db922d8bee33f539d07f37dc2de4bc1309c12df42"):
        raise ValueError(f"ATLAS_CORRECTION_SCIENCE_NOT_VERIFIED:{verification.reason_code}")
    receipt = build_terminal_receipt(request=request, decision=decision, verification=verification,
                                     created_at=datetime.now(timezone.utc))
    if receipt.state != "SUCCESS" or receipt.reason_code != "CATALOG_RUN_SUCCESS":
        raise ValueError("ATLAS_CORRECTION_RECEIPT_INVALID")
    proof = {
        "source_run_id": SOURCE_RUN_ID, "source_commit": SOURCE_COMMIT,
        "issue_number": ISSUE_NUMBER, "request_sha256": REQUEST_SHA,
        "old_terminal_receipt_sha256": OLD_RECEIPT_SHA,
        "corrected_terminal_receipt_sha256": receipt.receipt_sha256,
        "plan_sha256": verification.plan_sha256,
        "result_science_sha256": verification.result_science_sha256,
        "observed_recipe_count": verification.observed_recipe_count,
        "source_artifact_ids": {key: row[0] for key, row in SOURCE_ARTIFACTS.items()},
    }
    output.write_text(receipt.model_dump_json() + "\n", encoding="utf-8")
    proof_output.write_text(json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ATLAS_CORRECTION_PREPARED_NOT_PUBLISHED", **proof}, sort_keys=True))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo-root", "gate", "preflight", "final", "old-terminal", "output", "proof-output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve(strict=True)
        client, commit = _require_environment(root)
        prepare(root=root, gate=args.gate, preflight=args.preflight, final=args.final,
                old_terminal=args.old_terminal, output=args.output,
                proof_output=args.proof_output, client=client, protected_commit=commit)
        return 0
    except (OSError, ValueError, TypeError, KeyError, CatalogGitHubSnapshotError) as exc:
        print(str(exc).split(":", 1)[0], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

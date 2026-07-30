"""Validation for the immutable PR-1 merge reconciliation receipt."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    git_blob_id,
    raw_sha256,
    require_digest,
)
from infra.gtbi_v7_readiness.genesis import build_initial_records
from infra.gtbi_v7_readiness.records import (
    RECORD_SCHEMAS,
    write_csv,
    write_jsonl,
)

RECEIPT_FILENAME = "pr1_merge_reconciliation_receipt.json"
REPOSITORY = "trading-optimizer-lab-org/aurora"
REQUIRED_WORKFLOWS = frozenset(
    {
        "CodeQL",
        "GitHub Performance CI",
        "GitHub Performance Policy",
        "GTBI V7 Master Plan Quality",
        "lint",
        "security",
        "tests",
        "typecheck",
        "wheel",
    }
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PostMergeValidationError(ValueError):
    """Raised when PR-1 merge evidence is incomplete or inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_sha(value: object, label: str) -> str:
    text = str(value)
    if not _SHA_RE.fullmatch(text):
        raise PostMergeValidationError(f"{label} is not a canonical Git SHA")
    return text


def validate_pr1_merge_receipt(repository_root: Path) -> dict[str, Any]:
    """Validate the checked-in PR-1 merge and CI evidence against local bytes."""
    root = repository_root.resolve()
    readiness = root / "docs/readiness/gtbi-v7"
    path = readiness / RECEIPT_FILENAME
    if not path.is_file():
        raise PostMergeValidationError(f"missing {RECEIPT_FILENAME}")
    receipt = _read_json(path)
    if path.read_bytes() != canonical_bytes(receipt) + b"\n":
        raise PostMergeValidationError("PR-1 receipt is not canonical JSON")
    if receipt.get("schema_version") != "gtbi_v7_pr1_merge_reconciliation_v1":
        raise PostMergeValidationError("unexpected PR-1 receipt schema")
    if receipt.get("repository") != REPOSITORY:
        raise PostMergeValidationError("PR-1 receipt repository mismatch")
    if receipt.get("pull_request_number") != 21:
        raise PostMergeValidationError("PR-1 receipt pull request mismatch")

    base_sha = _require_sha(receipt.get("base_sha"), "base_sha")
    head_sha = _require_sha(receipt.get("head_sha"), "head_sha")
    merge_sha = _require_sha(receipt.get("merge_sha"), "merge_sha")
    if len({base_sha, head_sha, merge_sha}) != 3:
        raise PostMergeValidationError("base, head and merge SHAs must differ")
    if receipt.get("pull_request_state") != "MERGED":
        raise PostMergeValidationError("PR-1 was not recorded as merged")

    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    if receipt.get("master_plan_sha256") != raw_sha256(plan_path):
        raise PostMergeValidationError("master-plan SHA-256 mismatch")
    if receipt.get("master_plan_git_blob_id") != git_blob_id(
        plan_path.read_bytes()
    ):
        raise PostMergeValidationError("master-plan Git blob mismatch")

    initial_digests = receipt.get("initial_record_digests")
    if not isinstance(initial_digests, dict) or not initial_digests:
        raise PostMergeValidationError("initial record digests are missing")
    initial_records = build_initial_records(root)
    schema_by_filename = {
        schema.filename: schema for schema in RECORD_SCHEMAS
    }
    with tempfile.TemporaryDirectory(prefix="gtbi-v7-pr1-prefix-") as temp:
        temporary = Path(temp)
        for relative, expected in initial_digests.items():
            require_digest(str(expected))
            filename = Path(str(relative)).name
            if filename not in initial_records:
                raise PostMergeValidationError(
                    f"unknown initial record in receipt: {relative}"
                )
            schema = schema_by_filename[filename]
            generated = temporary / filename
            if schema.record_format == "csv":
                write_csv(
                    generated,
                    schema.fields,
                    initial_records[filename],
                )
            else:
                write_jsonl(generated, initial_records[filename])
            if raw_sha256(generated) != expected:
                raise PostMergeValidationError(
                    f"frozen initial digest mismatch: {relative}"
                )
            current = root / str(relative)
            if filename.endswith("_events.jsonl") and not (
                current.read_bytes().startswith(generated.read_bytes())
            ):
                raise PostMergeValidationError(
                    f"initial readiness prefix drift: {relative}"
                )

    runs = receipt.get("ci_runs")
    if not isinstance(runs, list) or not runs:
        raise PostMergeValidationError("CI run evidence is missing")
    run_ids: set[int] = set()
    workflows: set[str] = set()
    for run in runs:
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise PostMergeValidationError("CI evidence contains a non-success run")
        if run.get("head_sha") != head_sha:
            raise PostMergeValidationError("CI run is not bound to PR-1 head")
        run_id = int(run["run_id"])
        if run_id in run_ids:
            raise PostMergeValidationError("duplicate CI run id")
        run_ids.add(run_id)
        workflows.add(str(run["workflow"]))
    if not REQUIRED_WORKFLOWS.issubset(workflows):
        missing = sorted(REQUIRED_WORKFLOWS - workflows)
        raise PostMergeValidationError(f"missing successful workflows: {missing}")

    matrix = receipt.get("test_matrix")
    if not isinstance(matrix, list) or len(matrix) != 6:
        raise PostMergeValidationError("test matrix must contain six jobs")
    expected_matrix = {
        (version, os_name)
        for version in ("3.11", "3.12", "3.13")
        for os_name in ("ubuntu-latest", "windows-latest")
    }
    observed_matrix = {
        (str(row["python"]), str(row["os"])) for row in matrix
    }
    if observed_matrix != expected_matrix:
        raise PostMergeValidationError("test matrix coverage mismatch")
    if any(row.get("conclusion") != "success" for row in matrix):
        raise PostMergeValidationError("test matrix contains a non-success job")

    if receipt.get("maximum_incremental_net_spend_usd") != 0:
        raise PostMergeValidationError("PR-1 receipt violates the zero-cost cap")
    if receipt.get("formal_effect") != "PREV7-0000_merge_evidence_complete":
        raise PostMergeValidationError("unexpected PR-1 formal effect")
    expected_digest = domain_digest(
        "GTBI_V7_PR1_MERGE_RECONCILIATION_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    require_digest(str(receipt.get("receipt_digest")))
    if receipt["receipt_digest"] != expected_digest:
        raise PostMergeValidationError("PR-1 receipt digest mismatch")
    return receipt


__all__ = [
    "PostMergeValidationError",
    "RECEIPT_FILENAME",
    "validate_pr1_merge_receipt",
]

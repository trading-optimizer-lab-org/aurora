from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable


REPOSITORY = "trading-optimizer-lab-org/aurora"
OWNER = "github-user:271768688"
CURRENT_BRANCH = "codex/gtbi-v7-completed-clean"
CANONICAL_ARTIFACTS = {
    "gtbi-v7-new-reference-historical-results",
    "global-technical-buy-indicator-long-hold-fast-strict-v6-results",
}
REGISTRY_COLUMNS = (
    "asset_type",
    "identity",
    "owner",
    "purpose",
    "product",
    "status",
    "canonical_replacement",
    "retention_class",
    "last_verified_at",
    "decision",
    "sha_or_id",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _canonical_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _gh(endpoint: str) -> Any:
    completed = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _gh_pages(endpoint: str, *, object_key: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 1000):
        separator = "&" if "?" in endpoint else "?"
        payload = _gh(f"{endpoint}{separator}per_page=100&page={page}")
        batch = payload.get(object_key, []) if object_key else payload
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
    return rows


def _artifact_family(name: str) -> str:
    value = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "{uuid}",
        name,
    )
    value = re.sub(r"(?i)(?=[0-9a-f]{8,})(?=.*[a-f])[0-9a-f]{8,}", "{hex}", value)
    value = re.sub(r"\d+", "{n}", value)
    return value


def _product(identity: str) -> str:
    lowered = identity.lower()
    if "gtbi-v7-new-reference" in lowered or "gtbi-v{n}-new-reference" in lowered:
        return "GTBI_V7_CANONICAL_SUCCESSOR_1"
    if "gtbi" in lowered or "global-technical-buy-indicator" in lowered:
        return "GTBI_HISTORICAL_RESEARCH"
    if "github-performance" in lowered:
        return "AURORA_PERFORMANCE_FRAMEWORK"
    if "openap" in lowered or "openassetpricing" in lowered:
        return "OPEN_ASSET_PRICING"
    return "AURORA_RESEARCH"


def _decision(
    asset_type: str, identity: str, status: str, open_heads: set[str]
) -> tuple[str, str, str]:
    lowered = identity.lower()
    if asset_type == "branch":
        if identity in {"main", CURRENT_BRANCH} or identity in open_heads:
            return "keep", "active", "active_source"
        return "archive", "inactive_preserved", "historical_source"
    if "gtbi-v7-new-reference" in lowered or "gtbi-v{n}-new-reference" in lowered:
        return "keep", status, "canonical_scientific"
    if asset_type in {"workflow", "run_family"} and (
        "maintenance" in lowered
        or "ci" in lowered
        or "security" in lowered
        or "lint" in lowered
        or "property" in lowered
        or "docs" in lowered
    ):
        return "keep", status, "operational"
    if asset_type == "artifact" and identity in CANONICAL_ARTIFACTS:
        return "keep", status, "canonical_scientific"
    if asset_type == "artifact_family" and (
        "gtbi-v7-new-reference" in lowered or "gtbi-v{n}-new-reference" in lowered
    ):
        return "keep", status, "canonical_scientific"
    return "archive", status, "historical_reference"


def _registry_row(
    *,
    asset_type: str,
    identity: str,
    status: str,
    verified_at: str,
    open_heads: set[str],
    sha_or_id: str = "",
    purpose: str = "inventoried repository asset",
) -> dict[str, str]:
    decision, classified_status, retention = _decision(asset_type, identity, status, open_heads)
    product = _product(identity)
    replacement = (
        "gtbi_v7_new_reference_v1"
        if product == "GTBI_HISTORICAL_RESEARCH"
        else (identity if decision == "keep" else "none")
    )
    return {
        "asset_type": asset_type,
        "identity": identity,
        "owner": OWNER,
        "purpose": purpose,
        "product": product,
        "status": classified_status,
        "canonical_replacement": replacement,
        "retention_class": retention,
        "last_verified_at": verified_at,
        "decision": decision,
        "sha_or_id": sha_or_id,
    }


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: Iterable[str]) -> int:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def build(*, inventory_source: Path, repository_root: Path) -> dict[str, Any]:
    project_inventory = repository_root / "docs" / "project_inventory"
    successor = repository_root / "docs" / "readiness" / "gtbi-v7-successor"
    project_inventory.mkdir(parents=True, exist_ok=True)
    successor.mkdir(parents=True, exist_ok=True)

    for name in (
        "artifacts.csv",
        "releases_complete.csv",
        "packages_complete.csv",
        "inventory_reconciliation.json",
    ):
        shutil.copy2(inventory_source / name, project_inventory / name)

    inventory = json.loads(
        (project_inventory / "inventory_reconciliation.json").read_text(encoding="utf-8")
    )
    if not inventory.get("complete"):
        raise RuntimeError("complete inventory is required")
    verified_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    branches = _gh_pages(f"repos/{REPOSITORY}/branches")
    workflows = _gh_pages(f"repos/{REPOSITORY}/actions/workflows", object_key="workflows")
    pulls = _gh_pages(f"repos/{REPOSITORY}/pulls?state=open")
    open_heads = {str(row["head"]["ref"]) for row in pulls}

    registry: list[dict[str, str]] = []
    for branch in branches:
        registry.append(
            _registry_row(
                asset_type="branch",
                identity=str(branch["name"]),
                status="protected" if branch.get("protected") else "unprotected",
                verified_at=verified_at,
                open_heads=open_heads,
                sha_or_id=str(branch["commit"]["sha"]),
                purpose="source branch",
            )
        )
    for workflow in workflows:
        path = str(workflow["path"])
        registry.append(
            _registry_row(
                asset_type="workflow",
                identity=path,
                status=str(workflow["state"]),
                verified_at=verified_at,
                open_heads=open_heads,
                sha_or_id=str(workflow["id"]),
                purpose="workflow definition",
            )
        )
        registry.append(
            _registry_row(
                asset_type="run_family",
                identity=path,
                status=str(workflow["state"]),
                verified_at=verified_at,
                open_heads=open_heads,
                sha_or_id=str(workflow["id"]),
                purpose="workflow run family",
            )
        )

    family_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total_size": 0, "first": "", "last": "", "examples": []}
    )
    canonical_rows: list[dict[str, str]] = []
    with (project_inventory / "artifacts.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = str(row["name"])
            family = _artifact_family(name)
            stats = family_stats[family]
            stats["count"] += 1
            stats["total_size"] += int(row["size_in_bytes"] or 0)
            created = str(row["created_at"])
            stats["first"] = min(filter(None, (stats["first"], created)), default=created)
            stats["last"] = max(stats["last"], created)
            if len(stats["examples"]) < 3:
                stats["examples"].append(name)
            if name in CANONICAL_ARTIFACTS or name.startswith(
                "gtbi-v7-new-reference-preservation-"
            ):
                canonical_rows.append(
                    _registry_row(
                        asset_type="artifact",
                        identity=name,
                        status="expired" if row["expired"].lower() == "true" else "retained",
                        verified_at=verified_at,
                        open_heads=open_heads,
                        sha_or_id=str(row["artifact_id"]),
                        purpose=f"canonical artifact from run {row['run_id']}",
                    )
                )
    registry.extend(canonical_rows)
    family_rows: list[dict[str, Any]] = []
    for family, stats in sorted(family_stats.items()):
        row = _registry_row(
            asset_type="artifact_family",
            identity=family,
            status="inventoried",
            verified_at=verified_at,
            open_heads=open_heads,
            purpose=f"artifact naming family with {stats['count']} records",
        )
        registry.append(row)
        family_rows.append(
            {
                "artifact_family": family,
                "artifact_count": stats["count"],
                "total_size_in_bytes": stats["total_size"],
                "first_created_at": stats["first"],
                "last_created_at": stats["last"],
                "examples_json": json.dumps(stats["examples"], separators=(",", ":")),
                "decision": row["decision"],
                "retention_class": row["retention_class"],
                "canonical_replacement": row["canonical_replacement"],
            }
        )

    registry_count = _write_csv(
        project_inventory / "workflow_branch_registry.csv", registry, REGISTRY_COLUMNS
    )
    family_count = _write_csv(
        project_inventory / "artifact_family_registry.csv",
        family_rows,
        (
            "artifact_family",
            "artifact_count",
            "total_size_in_bytes",
            "first_created_at",
            "last_created_at",
            "examples_json",
            "decision",
            "retention_class",
            "canonical_replacement",
        ),
    )
    unknown = sum(row["decision"] == "unknown" for row in registry)
    if unknown:
        raise RuntimeError(f"registry contains {unknown} unknown decisions")

    local_receipt = json.loads(
        (project_inventory / "local_reorganization_receipt.json").read_text(encoding="utf-8")
    )
    g4 = {
        "schema_version": "gtbi_v7_successor_g4_completion_v1",
        "complete": True,
        "inventory_run_id": 30763993869,
        "inventory_cutoff_utc": inventory["cutoff_utc"],
        "inventory_receipt_digest": inventory["receipt_digest"],
        "artifact_rows": inventory["output_row_counts"]["artifacts.csv"],
        "release_rows": inventory["output_row_counts"]["releases_complete.csv"],
        "package_rows": inventory["output_row_counts"]["packages_complete.csv"],
        "branch_rows": len(branches),
        "workflow_rows": len(workflows),
        "artifact_family_rows": family_count,
        "registry_rows": registry_count,
        "unknown_decisions": unknown,
        "local_worktrees": local_receipt["worktree_count"],
        "dirty_worktrees": local_receipt["dirty_worktree_count"],
        "dirty_paths": local_receipt["dirty_path_count"],
        "preserved_objects": local_receipt["preserved_object_count"],
        "unresolved_secret_findings": local_receipt["unresolved_secret_finding_count"],
        "fresh_primary_clone_verified": local_receipt["restore_verification"] == "passed",
        "one_active_worktree_policy": "registered_active_branches_only; historical worktrees preserved in place",
        "destructive_action_taken": False,
        "locked_data_accessed": False,
        "github_only_scientific_execution": True,
        "files": {
            name: _sha256(project_inventory / name)
            for name in (
                "artifacts.csv",
                "releases_complete.csv",
                "packages_complete.csv",
                "inventory_reconciliation.json",
                "workflow_branch_registry.csv",
                "artifact_family_registry.csv",
                "worktrees_complete.csv",
                "dirty_paths.csv",
                "local_reorganization_receipt.json",
            )
        },
    }
    _canonical_write(successor / "g4_completion_receipt.json", g4)
    _canonical_write(
        successor / "quarantine_plan.json",
        {
            "schema_version": "gtbi_v7_successor_quarantine_plan_v1",
            "status": "no_candidates_selected",
            "approved_redundant_copy_count": 0,
            "grace_period_days": 30,
            "restore_proof": "docs/project_inventory/local_reorganization_receipt.json",
            "destructive_action_authorized": False,
            "destructive_action_taken": False,
        },
    )
    _canonical_write(
        successor / "deletion_after_grace_receipt.json",
        {
            "schema_version": "gtbi_v7_successor_deletion_v1",
            "status": "terminal_no_op",
            "reason": "no redundant copy was approved for deletion",
            "candidate_count": 0,
            "deleted_count": 0,
            "destructive_action_taken": False,
        },
    )
    return g4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-source", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = build(
        inventory_source=args.inventory_source.resolve(),
        repository_root=args.repository_root.resolve(),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

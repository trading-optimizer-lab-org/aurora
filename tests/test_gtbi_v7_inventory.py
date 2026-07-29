from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from infra.gtbi_v7_readiness.inventory import (
    CSV_SCHEMAS,
    generate_remote_inventory,
    inventory_schema,
    validate_inventory,
)

ROOT = Path(__file__).resolve().parents[1]
QUERY_MANIFEST_PATH = (
    ROOT / "config/gtbi/contracts/emergency_inventory_query_manifest_v1.json"
)


class FakeClient:
    def __init__(self, *, deny_collaborators: bool = False) -> None:
        self.deny_collaborators = deny_collaborators

    def get(
        self, path: str, params: Mapping[str, object] | None = None
    ) -> Any:
        if path == "repos/trading-optimizer-lab-org/aurora":
            return {
                "default_branch": "main",
                "visibility": "public",
                "private": False,
                "archived": False,
                "web_commit_signoff_required": False,
                "allow_forking": True,
                "delete_branch_on_merge": False,
                "security_and_analysis": {"secret_scanning": {"status": "enabled"}},
            }
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "a" * 40}}
        if path.endswith("/actions/artifacts"):
            return {"total_count": 326415}
        if path.endswith("/actions/artifacts/8251391531"):
            return _critical_artifact()
        if path.endswith("/environments"):
            return {"environments": []}
        if path.endswith("/branches/main/protection"):
            return {}
        raise AssertionError(f"unexpected GET {path} {params}")

    def paginate(
        self,
        path: str,
        *,
        item_key: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> list[Any]:
        if path.endswith("/branches"):
            return [
                {
                    "name": "main",
                    "protected": False,
                    "protection_url": "https://example/protection",
                    "commit": {"sha": "a" * 40, "url": "https://example/commit"},
                }
            ]
        if path.endswith("/actions/workflows"):
            return [
                {
                    "id": 1,
                    "name": "test",
                    "path": ".github/workflows/test.yml",
                    "state": "active",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
        if path.endswith("/actions/runs"):
            return []
        if "/actions/runs/" in path and path.endswith("/artifacts"):
            return []
        if path.endswith("/releases"):
            return []
        if path.endswith("/packages"):
            return []
        if path.endswith("/collaborators"):
            if self.deny_collaborators:
                from infra.gtbi_v7_readiness.inventory import GitHubApiError

                raise GitHubApiError(path, 403, "Resource not accessible")
            return [
                {
                    "login": "owner",
                    "id": 1,
                    "type": "User",
                    "site_admin": False,
                    "role_name": "admin",
                    "permissions": {"admin": True},
                }
            ]
        if path.endswith("/rulesets"):
            return []
        raise AssertionError(f"unexpected pagination {path} {item_key} {params}")


def _critical_artifact() -> dict[str, Any]:
    return {
        "id": 8251391531,
        "name": "global-technical-buy-indicator-long-hold-fast-strict-v6-results",
        "size_in_bytes": 1962204087,
        "digest": (
            "sha256:870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b"
        ),
        "expired": False,
        "created_at": "2026-07-11T18:17:52Z",
        "updated_at": "2026-07-11T18:17:52Z",
        "expires_at": "2026-08-10T18:16:37Z",
        "archive_download_url": "https://api.github.test/artifact.zip",
        "workflow_run": {"id": 29162930823},
    }


def _manifest() -> dict[str, Any]:
    return json.loads(QUERY_MANIFEST_PATH.read_text(encoding="utf-8"))


def test_inventory_schema_defines_every_csv() -> None:
    schema = inventory_schema()
    assert set(schema["csv_files"]) == set(CSV_SCHEMAS)
    for definition in schema["csv_files"].values():
        assert definition["primary_key"]
        assert definition["columns"]


def test_complete_remote_inventory_has_matching_v6_artifact(tmp_path: Path) -> None:
    metadata = generate_remote_inventory(
        client=FakeClient(),
        query_manifest=_manifest(),
        query_manifest_path=QUERY_MANIFEST_PATH,
        output_dir=tmp_path,
        audited_at_utc="2026-07-29T12:00:00Z",
        workflow_run_id="123",
    )
    assert metadata["complete"] is True
    assert metadata["missing_required_surfaces"] == []
    with (tmp_path / "artifacts_critical.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == "8251391531"
    assert rows[0]["metadata_match"] == "true"
    assert rows[0]["expired"] == "false"
    assert validate_inventory(tmp_path) == []


def test_permission_failure_is_explicit_and_blocks_completeness(
    tmp_path: Path,
) -> None:
    metadata = generate_remote_inventory(
        client=FakeClient(deny_collaborators=True),
        query_manifest=_manifest(),
        query_manifest_path=QUERY_MANIFEST_PATH,
        output_dir=tmp_path,
        audited_at_utc="2026-07-29T12:00:00Z",
    )
    assert metadata["complete"] is False
    assert "collaborators" in metadata["missing_required_surfaces"]
    errors = validate_inventory(tmp_path)
    assert any("remote inventory is incomplete" in error for error in errors)


def test_checked_in_inventory_workflow_is_pinned_and_read_only() -> None:
    workflow = (
        ROOT / ".github/workflows/gtbi-v7-inventory.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "contents: read" in workflow
    assert "actions: read" in workflow
    assert "contents: write" not in workflow
    assert "self-hosted" not in workflow
    assert "C:\\" not in workflow
    assert "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow


def test_inventory_script_runs_directly_from_repository() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/generate_gtbi_v7_inventory.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--mode" in completed.stdout


def test_checked_in_query_manifest_is_canonical() -> None:
    from infra.gtbi_v7_readiness.canonical import canonical_bytes

    payload = _manifest()
    assert QUERY_MANIFEST_PATH.read_bytes() == canonical_bytes(payload) + b"\n"

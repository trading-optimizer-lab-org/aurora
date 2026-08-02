from __future__ import annotations

import csv
import json
import sqlite3
import urllib.parse
from pathlib import Path

from infra.gtbi_v7_readiness.full_inventory import (
    FullInventoryError,
    PageResponse,
    run_complete_inventory,
)
import pytest


class FakePageClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def get_page(self, url: str, *, etag: str | None = None) -> PageResponse:
        self.calls.append((url, etag))
        headers = {
            "ETag": f'"{hash(url)}"',
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4999",
            "X-RateLimit-Reset": "0",
        }
        if etag:
            return PageResponse(304, None, headers)
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        page = int(query["page"][0])
        if parsed.path.endswith("/actions/artifacts"):
            items = [] if page > 1 else [_artifact(1), _artifact(2)]
            return PageResponse(200, {"total_count": 2, "artifacts": items}, headers)
        if parsed.path.endswith("/releases"):
            items = [] if page > 1 else [_release(20)]
            return PageResponse(200, items, headers)
        if parsed.path.endswith("/packages"):
            package_type = query["package_type"][0]
            items = [] if page > 1 or package_type != "container" else [_package(30)]
            return PageResponse(200, items, headers)
        if parsed.path.endswith("/versions"):
            items = [] if page > 1 else [_package_version(40)]
            return PageResponse(200, items, headers)
        raise AssertionError(url)


class FailingPageClient(FakePageClient):
    def get_page(self, url: str, *, etag: str | None = None) -> PageResponse:
        if urllib.parse.urlparse(url).path.endswith("/releases"):
            raise FullInventoryError("deliberate release failure")
        return super().get_page(url, etag=etag)


def _artifact(artifact_id: int) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": f"artifact-{artifact_id}",
        "size_in_bytes": 100,
        "digest": f"sha256:{artifact_id:064x}",
        "expired": False,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
        "expires_at": "2026-09-01T00:00:00Z",
        "archive_download_url": "https://api.github.test/artifact.zip",
        "workflow_run": {"id": 100 + artifact_id},
    }


def _release(release_id: int) -> dict[str, object]:
    return {
        "id": release_id,
        "tag_name": "v7-test",
        "target_commitish": "main",
        "name": "V7 Test",
        "draft": False,
        "prerelease": False,
        "immutable": True,
        "created_at": "2026-08-01T00:00:00Z",
        "published_at": "2026-08-01T00:00:00Z",
        "html_url": "https://github.test/releases/v7-test",
        "assets": [],
    }


def _package(package_id: int) -> dict[str, object]:
    return {
        "id": package_id,
        "name": "aurora-test",
        "package_type": "container",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }


def _package_version(version_id: int) -> dict[str, object]:
    return {
        "id": version_id,
        "name": "sha256:test",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
        "html_url": "https://github.test/packages/aurora-test/40",
        "metadata": {"container": {"tags": ["test"]}},
    }


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_complete_inventory_requires_two_identical_scans(tmp_path: Path) -> None:
    client = FakePageClient()
    checkpoint = tmp_path / "checkpoint.sqlite"
    output = tmp_path / "results"
    result = run_complete_inventory(
        client=client,
        repository="trading-optimizer-lab-org/aurora",
        organization="trading-optimizer-lab-org",
        api_url="https://api.github.test",
        cutoff_utc="2026-08-02T00:00:00Z",
        checkpoint_path=checkpoint,
        output_dir=output,
    )
    assert result["complete"] is True
    assert result["surfaces"]["artifacts"]["stable_retained_id_set"] is True
    assert result["surfaces"]["artifacts"]["scan_b_retained_count"] == 2
    assert result["surfaces"]["releases"]["scan_b_retained_count"] == 1
    assert result["surfaces"]["packages"]["scan_b_retained_count"] == 1
    assert len(_rows(output / "artifacts.csv")) == 2
    assert len(_rows(output / "releases_complete.csv")) == 1
    assert len(_rows(output / "packages_complete.csv")) == 1
    recorded = json.loads((output / "inventory_reconciliation.json").read_text())
    assert recorded == result
    assert all("Authorization" not in url for url, _ in client.calls)
    assert any(etag for _, etag in client.calls)


def test_checkpoint_records_every_page_and_is_resumable(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.sqlite"
    output = tmp_path / "results"
    first = run_complete_inventory(
        client=FakePageClient(),
        repository="trading-optimizer-lab-org/aurora",
        organization="trading-optimizer-lab-org",
        api_url="https://api.github.test",
        cutoff_utc="2026-08-02T00:00:00Z",
        checkpoint_path=checkpoint,
        output_dir=output,
    )
    with sqlite3.connect(checkpoint) as connection:
        page_count = connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        duplicate_pages = connection.execute(
            "SELECT COUNT(*) FROM (SELECT scan_id,surface,request_key,page_number,COUNT(*) n FROM pages GROUP BY 1,2,3,4 HAVING n>1)"
        ).fetchone()[0]
    second_client = FakePageClient()
    second = run_complete_inventory(
        client=second_client,
        repository="trading-optimizer-lab-org/aurora",
        organization="trading-optimizer-lab-org",
        api_url="https://api.github.test",
        cutoff_utc="2026-08-02T00:00:00Z",
        checkpoint_path=checkpoint,
        output_dir=output,
    )
    assert page_count > 0
    assert duplicate_pages == 0
    assert second == first or second["receipt_digest"] != ""
    assert second_client.calls == []


def test_incomplete_scan_writes_exact_fail_closed_reconciliation(
    tmp_path: Path,
) -> None:
    output = tmp_path / "results"
    with pytest.raises(FullInventoryError, match="deliberate release failure"):
        run_complete_inventory(
            client=FailingPageClient(),
            repository="trading-optimizer-lab-org/aurora",
            organization="trading-optimizer-lab-org",
            api_url="https://api.github.test",
            cutoff_utc="2026-08-02T00:00:00Z",
            checkpoint_path=tmp_path / "checkpoint.sqlite",
            output_dir=output,
        )
    reconciliation = json.loads(
        (output / "inventory_reconciliation.json").read_text(encoding="utf-8")
    )
    assert reconciliation["complete"] is False
    assert reconciliation["surfaces"]["releases"]["inaccessible_count"] == 1
    assert "deliberate release failure" in reconciliation["surfaces"]["releases"][
        "scan_a_incomplete_reason"
    ]


def test_full_inventory_workflow_is_github_only_and_read_only() -> None:
    text = Path(".github/workflows/aurora-maintenance-inventory.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in text
    assert "runs-on: ubuntu-24.04" in text
    assert "timeout-minutes: 360" in text
    assert "actions: read" in text
    assert "contents: read" in text
    assert "packages: read" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text
    assert "generate_gtbi_v7_full_inventory" in text
    assert "if: always()" in text

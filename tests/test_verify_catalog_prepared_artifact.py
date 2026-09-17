"""Exercise the production CLI consumer without replacing its byte verifier."""

from pathlib import Path
import subprocess
from io import BytesIO
import zipfile

import pytest

from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry, resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import build_catalog_preparation_identity
from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_prepared_bundle import write_prepared_catalog_bundle_manifest
from scripts import verify_catalog_prepared_bundle as consumer
from tests.test_catalog_fast_path import _prepared
from tests.test_catalog_prepared_artifact import _FakeGitHubClient
from aurora.infra.sp500_megarun import catalog_prepared_artifact as artifact_reader


def _current_bundle(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", commit)
    registry = load_catalog_campaign_registry(root / "config/catalog_campaign_registry_v1.json")
    entry = resolve_catalog_campaign(registry, "catalog-fast-canary-v1", root)
    identity = build_catalog_preparation_identity(
        repo_root=root, registry_entry=entry, protected_commit_sha=commit,
    )
    receipt = _prepared(identity=identity)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "prepared-receipt.json").write_text(receipt.model_dump_json(), encoding="utf-8")
    write_prepared_catalog_bundle_manifest(bundle_dir=bundle, prepared_receipt=receipt)
    return root, bundle, receipt


def test_exact_cached_bundle_never_needs_remote_artifact_lookup(tmp_path, monkeypatch):
    root, bundle, receipt = _current_bundle(tmp_path, monkeypatch)

    def unexpected_remote(*args, **kwargs):
        raise AssertionError("an exact cache hit must not contact GitHub")

    monkeypatch.setattr(consumer, "CatalogGitHubReadOnlyClient", unexpected_remote)
    result = consumer.verify_bundle(
        campaign_key="catalog-fast-canary-v1", repo_root=root, bundle=bundle,
        github_output=None, restore_artifact_on_miss=True,
    )
    assert result == receipt.receipt_sha256


def test_corrupt_cached_bundle_is_not_silently_replaced(tmp_path, monkeypatch):
    root, bundle, _ = _current_bundle(tmp_path, monkeypatch)
    receipt_path = bundle / "prepared-receipt.json"
    receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="CATALOG_PREPARED_BUNDLE_CONTENT_INVALID"):
        consumer.verify_bundle(
            campaign_key="catalog-fast-canary-v1", repo_root=root, bundle=bundle,
            github_output=None, restore_artifact_on_miss=True,
        )


def test_cache_miss_restores_verified_artifact_through_real_consumer(tmp_path, monkeypatch):
    root, source_bundle, receipt = _current_bundle(tmp_path, monkeypatch)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(source_bundle.rglob("*")):
            if path.is_file():
                archive.writestr(path.relative_to(source_bundle).as_posix(), path.read_bytes())
    raw = output.getvalue()
    client = _FakeGitHubClient(raw, identity=receipt.identity)
    destination = tmp_path / "restored"
    monkeypatch.setenv("GITHUB_REPOSITORY", client.repository)
    monkeypatch.setenv("GH_TOKEN", "test-network-boundary-token")
    monkeypatch.setattr(consumer, "CatalogGitHubReadOnlyClient", lambda *args: client)
    monkeypatch.setattr(artifact_reader, "_download_archive", lambda *args: raw)
    result = consumer.verify_bundle(
        campaign_key=receipt.identity.campaign_key, repo_root=root, bundle=destination,
        github_output=None, restore_artifact_on_miss=True,
    )
    assert result == receipt.receipt_sha256
    assert (destination / "prepared-receipt.json").read_bytes() == (source_bundle / "prepared-receipt.json").read_bytes()
    assert client._artifact_reads == 2


def test_controller_routes_only_authenticated_cache_misses_to_fallback():
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / ".github/workflows/catalog-fast-controller.yml")
    steps = workflow["jobs"]["gate"]["steps"]
    positions = {step.get("id"): index for index, step in enumerate(steps) if step.get("id")}
    assert "recover_prepared" in positions
    assert positions["authority"] < positions["restore"] < positions["recover_prepared"] < positions["admit"]
    fallback = steps[positions["recover_prepared"]]
    assert "steps.inspect.outputs.valid_request == 'true'" in fallback["if"]
    assert "steps.restore.outputs['cache-matched-key'] == ''" in fallback["if"]
    assert "steps.inspect.outputs.prepared_cache_restore_prefix != ''" in fallback["if"]
    assert "--restore-artifact-on-miss" in fallback["run"]
    assert "--require-live-caches" in fallback["run"]
    assert fallback["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_preparation_consumer_attempts_exact_artifact_before_rebuilding():
    root = Path(__file__).resolve().parents[1]
    workflow = load_github_yaml(root / ".github/workflows/catalog-prepare-one.yml")
    steps = workflow["jobs"]["preflight"]["steps"]
    verify = next(step for step in steps if step.get("id") == "verify")
    assert "if" not in verify
    assert "--restore-artifact-on-miss" in verify["run"]
    assert "--require-live-caches" in verify["run"]

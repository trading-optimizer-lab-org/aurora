from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest

from aurora.infra.sp500_megarun.catalog_fast_path import (
    CatalogPreparedReceiptV1,
    CatalogPreparationIdentityV1,
)
from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
    write_prepared_catalog_bundle_manifest,
)
from aurora.infra.sp500_megarun.catalog_prepared_artifact import (
    PreparedArtifactRestoreError,
    restore_prepared_artifact,
)
import aurora.infra.sp500_megarun.catalog_prepared_artifact as prepared_artifact_module


REPOSITORY = "trading-optimizer-lab-org/aurora"
REPOSITORY_ID = 1232647748
WORKFLOW_PATH = ".github/workflows/catalog-prepare.yml"
CAMPAIGN = "catalog-fast-canary-v1"
COMMIT = "b" * 40  # synthetic full SHA; live evidence has the same field shape
RUN_ID = 34991736509
ARTIFACT_ID = 10405719360
OBSERVED_AT = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


def _identity(*, campaign_key: str = CAMPAIGN, commit: str = COMMIT) -> CatalogPreparationIdentityV1:
    return CatalogPreparationIdentityV1(
        schema_version="1",
        campaign_key=campaign_key,
        engine_id="optimized_catalog_v1",
        protected_commit_sha=commit,
        campaign_definition_sha256="1" * 64,
        scientific_contract_sha256="2" * 64,
        dependency_lock_sha256="3" * 64,
        optimization_policy_sha256="4" * 64,
        data_contract_sha256="5" * 64,
        feature_contract_sha256="6" * 64,
        catalog_manifest_sha256="7" * 64,
        selected_config_sha256="8" * 64,
    )


def _receipt(identity: CatalogPreparationIdentityV1) -> CatalogPreparedReceiptV1:
    return CatalogPreparedReceiptV1.create(
        identity=identity,
        generated_at=datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc),
        runtime_identity_sha256="9" * 64,
        prepared_input_identity_sha256="a" * 64,
        component_store_manifest_sha256="b" * 64,
        execution_plan_template_sha256="c" * 64,
        required_cache_keys=("prepared-cache-key",),
        logical_recipe_count=24,
        unique_component_count=12,
        qualified_worker_ceiling=7,
        production_dependency_smoke_passed=True,
        recipe_worker_build_allowed=False,
    )


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _bundle_archive(tmp_path: Path, identity: CatalogPreparationIdentityV1) -> bytes:
    bundle = tmp_path / "bundle"
    (bundle / "payload").mkdir(parents=True)
    receipt = _receipt(identity)
    (bundle / "prepared-receipt.json").write_bytes(
        _canonical_json(receipt.model_dump(mode="json"))
    )
    (bundle / "payload" / "input.bin").write_bytes(b"prepared-input")
    write_prepared_catalog_bundle_manifest(bundle_dir=bundle, prepared_receipt=receipt)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.writestr(path.relative_to(bundle).as_posix(), path.read_bytes())
    return output.getvalue()


def _zip_with_members(members: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


class _FakeGitHubClient:
    repository = REPOSITORY
    observed_at = OBSERVED_AT

    def __init__(self, archive: bytes, *, identity: CatalogPreparationIdentityV1) -> None:
        self.archive = archive
        self.identity = identity
        self.run = {
            "id": RUN_ID,
            "path": WORKFLOW_PATH,
            "event": "push",
            "head_branch": "main",
            "head_sha": identity.protected_commit_sha,
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "run_number": 901,
            "repository": {"id": REPOSITORY_ID, "full_name": REPOSITORY},
        }
        self.jobs = [
            {
                "id": 1000 + index,
                "name": (
                    f"prepare ({identity.campaign_key}) / preflight"
                    if index == 1
                    else f"prepare ({identity.campaign_key}) / finalize"
                    if index == 2
                    else f"worker-{index}"
                ),
                "run_id": RUN_ID,
                "run_attempt": 1,
                "head_sha": identity.protected_commit_sha,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-09-17T10:00:00Z",
                "completed_at": "2026-09-17T11:02:00Z",
                "steps": (
                    [
                        {
                            "name": "Publish the PREPARED receipt and bundle as durable evidence",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": "2026-09-17T11:00:00Z",
                            "completed_at": "2026-09-17T11:02:00Z",
                        }
                    ]
                    if index == 2
                    else []
                ),
            }
            for index in range(1, 161)
        ]
        self.artifact = {
            "id": ARTIFACT_ID,
            "name": f"catalog-prepared-{identity.campaign_key}-{identity.preparation_key_sha256}",
            "size_in_bytes": len(archive),
            "digest": "sha256:" + sha256(archive).hexdigest(),
            "expired": False,
            "created_at": "2026-09-17T11:01:00Z",
            "expires_at": "2026-12-16T11:01:00Z",
            "workflow_run": {
                "id": RUN_ID,
                "head_branch": "main",
                "head_sha": identity.protected_commit_sha,
                "repository_id": REPOSITORY_ID,
                "head_repository_id": REPOSITORY_ID,
            },
        }
        self.artifact_rows_override: list[dict[str, object]] | None = None
        self.mutate_after_download = False
        self._artifact_reads = 0
        self._job_reads = 0
        self._workflow_runs_reads = 0

    def get_json(self, path: str):
        parsed = urlparse(path)
        query = parse_qs(parsed.query)
        body: dict[str, object]
        if parsed.path.endswith("/actions/workflows/catalog-prepare.yml/runs"):
            self._workflow_runs_reads += 1
            body = {"total_count": 1, "workflow_runs": [deepcopy(self.run)]}
        elif parsed.path.endswith("/actions/artifacts"):
            self._artifact_reads += 1
            rows = self.artifact_rows_override
            if rows is None:
                rows = [deepcopy(self.artifact)]
            artifact_rows = deepcopy(rows)
            if self.mutate_after_download and self._artifact_reads >= 2:
                artifact_rows[0]["digest"] = "sha256:" + "e" * 64
            body = {"total_count": len(rows), "artifacts": artifact_rows}
        elif parsed.path.endswith(f"/actions/runs/{RUN_ID}"):
            body = deepcopy(self.run)
        elif parsed.path.endswith(f"/actions/runs/{RUN_ID}/jobs"):
            page = int(query.get("page", ["1"])[0])
            rows = self.jobs[:100] if page == 1 else self.jobs[100:]
            body = {"total_count": 160, "jobs": deepcopy(rows)}
            self._job_reads += 1
        else:
            raise AssertionError(f"unexpected GET {path}")
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        headers = {"ETag": '"fixture-etag"'}
        if (
            parsed.path.endswith(f"/actions/runs/{RUN_ID}/jobs")
            and int(query.get("page", ["1"])[0]) == 1
        ):
            headers["Link"] = (
                f'<https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}/jobs'
                '?page=2&per_page=100>; rel="next"'
            )
        return body, SimpleNamespace(headers=headers, body=raw)


def _restore(tmp_path: Path, *, identity: CatalogPreparationIdentityV1 | None = None):
    expected = identity or _identity()
    archive = _bundle_archive(tmp_path, expected)
    client = _FakeGitHubClient(archive, identity=expected)
    destination = tmp_path / "restored"
    result = restore_prepared_artifact(
        client=client,
        expected_identity=expected,
        destination=destination,
        download_archive=lambda _artifact_id: archive,
    )
    return result, client, destination, archive


def test_absence_feature_failed_first_with_stable_public_reason():
    """The new public entry point exists and fails only with a stable code."""
    assert callable(restore_prepared_artifact)
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=object(),
            expected_identity=_identity(),
            destination=Path("missing-parent") / "bundle",
            download_archive=lambda _artifact_id: b"",
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_CLIENT_INVALID"
    assert "missing-parent" not in str(error.value)


def test_restore_happy_path_uses_160_job_pagination_and_returns_provenance(tmp_path):
    result, client, destination, archive = _restore(tmp_path)

    receipt, manifest = result
    assert receipt.identity.protected_commit_sha == COMMIT
    assert receipt.identity.campaign_key == CAMPAIGN
    assert receipt.identity.preparation_key_sha256 == _identity().preparation_key_sha256
    assert manifest.preparation_key_sha256 == receipt.identity.preparation_key_sha256
    assert result.artifact_id == ARTIFACT_ID
    assert result.run_id == RUN_ID
    assert result.digest == "sha256:" + sha256(archive).hexdigest()
    assert client._job_reads == 4
    assert client._workflow_runs_reads == 0
    assert (destination / "prepared-receipt.json").is_file()
    assert (destination / "payload" / "input.bin").read_bytes() == b"prepared-input"


def test_restore_derives_sp500_job_names_and_returns_publish_provenance(tmp_path):
    identity = _identity(campaign_key="sp500-optimized-catalog-v1")
    result, client, destination, _archive = _restore(tmp_path, identity=identity)

    assert result.campaign_key == "sp500-optimized-catalog-v1"
    assert destination.is_dir()
    assert client.jobs[0]["name"] == "prepare (sp500-optimized-catalog-v1) / preflight"
    assert client.jobs[1]["name"] == "prepare (sp500-optimized-catalog-v1) / finalize"


def test_restore_rejects_failed_or_out_of_window_publish_step(tmp_path):
    identity = _identity()
    archive = _bundle_archive(tmp_path, identity)
    client = _FakeGitHubClient(archive, identity=identity)
    client.jobs[1]["steps"][0]["conclusion"] = "failure"
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=identity,
            destination=tmp_path / "failed-step",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_INVALID"

    client = _FakeGitHubClient(archive, identity=identity)
    client.artifact["created_at"] = "2026-09-17T11:03:00Z"
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=identity,
            destination=tmp_path / "late-artifact",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_PUBLISH_STEP_TIME_INVALID"


def test_restore_rejects_forged_bundle_after_real_verifier(tmp_path):
    identity = _identity()
    source = zipfile.ZipFile(BytesIO(_bundle_archive(tmp_path, identity)))
    forged = BytesIO()
    with zipfile.ZipFile(forged, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for member in source.infolist():
            value = source.read(member)
            if member.filename == "payload/input.bin":
                value = b"forged-input"
            output.writestr(member.filename, value)
    source.close()
    archive = forged.getvalue()
    client = _FakeGitHubClient(archive, identity=identity)
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=identity,
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_BUNDLE_INVALID"


def test_restore_rejects_stale_cross_campaign_bundle(tmp_path):
    source = _identity()
    expected = _identity(campaign_key="catalog-fast-canary-v2")
    archive = _bundle_archive(tmp_path, source)
    client = _FakeGitHubClient(archive, identity=source)
    client.artifact["name"] = f"catalog-prepared-{expected.campaign_key}-{expected.preparation_key_sha256}"
    client.jobs[0]["name"] = f"prepare ({expected.campaign_key}) / preflight"
    client.jobs[1]["name"] = f"prepare ({expected.campaign_key}) / finalize"
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=expected,
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_BUNDLE_INVALID"


def test_restore_rejects_traversal_member_before_writing_destination(tmp_path):
    archive = _zip_with_members({"../escape.txt": b"nope"})
    client = _FakeGitHubClient(archive, identity=_identity())
    client.artifact.update(
        size_in_bytes=len(archive), digest="sha256:" + sha256(archive).hexdigest()
    )
    destination = tmp_path / "restored"
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=_identity(),
            destination=destination,
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_ARCHIVE_PATH_INVALID"
    assert not destination.exists()


def test_restore_rejects_ambiguous_artifact(tmp_path):
    archive = _bundle_archive(tmp_path, _identity())
    client = _FakeGitHubClient(archive, identity=_identity())
    client.artifact_rows_override = [deepcopy(client.artifact), deepcopy(client.artifact)]
    client.artifact_rows_override[1]["id"] = ARTIFACT_ID + 1
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=_identity(),
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_AMBIGUOUS_ARTIFACT"


def test_restore_rejects_cross_campaign_artifact_name(tmp_path):
    archive = _bundle_archive(tmp_path, _identity())
    client = _FakeGitHubClient(archive, identity=_identity())
    client.artifact["name"] = "catalog-prepared-other-campaign-v1-" + _identity().preparation_key_sha256
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=_identity(),
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_NAME_INVALID"


def test_restore_rejects_source_commit_mismatch(tmp_path):
    archive = _bundle_archive(tmp_path, _identity())
    client = _FakeGitHubClient(archive, identity=_identity())
    client.run["head_sha"] = "c" * 40
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=_identity(),
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_RUN_INVALID"


def test_restore_rejects_archive_digest_mismatch(tmp_path):
    archive = _bundle_archive(tmp_path, _identity())
    client = _FakeGitHubClient(archive, identity=_identity())
    client.artifact["digest"] = "sha256:" + "f" * 64
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=_identity(),
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_DIGEST_INVALID"


@pytest.mark.parametrize("mutation", ["absent", "expired", "old_expiry", "foreign_repository", "dispatch"])
def test_restore_rejects_unusable_source_before_download(tmp_path, mutation):
    identity = _identity()
    archive = _bundle_archive(tmp_path, identity)
    client = _FakeGitHubClient(archive, identity=identity)
    if mutation == "absent":
        client.artifact_rows_override = []
    elif mutation == "expired":
        client.artifact["expired"] = True
    elif mutation == "old_expiry":
        client.artifact["expires_at"] = "2026-09-16T00:00:00Z"
    elif mutation == "foreign_repository":
        client.artifact["workflow_run"]["head_repository_id"] = REPOSITORY_ID + 1
    else:
        client.run["event"] = "workflow_dispatch"

    downloads = []

    def must_not_download(_artifact_id):
        downloads.append(_artifact_id)
        raise AssertionError("invalid provenance must be rejected before download")

    with pytest.raises(PreparedArtifactRestoreError):
        restore_prepared_artifact(
            client=client, expected_identity=identity, destination=tmp_path / "restored",
            download_archive=must_not_download,
        )
    assert not (tmp_path / "restored").exists()
    assert downloads == []


def test_restore_rejects_remote_mutation_on_reread(tmp_path):
    archive = _bundle_archive(tmp_path, _identity())
    client = _FakeGitHubClient(archive, identity=_identity())
    client.mutate_after_download = True
    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client,
            expected_identity=_identity(),
            destination=tmp_path / "restored",
            download_archive=lambda _artifact_id: archive,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_REMOTE_MUTATED"


def test_download_timeout_has_sanitized_transport_code(monkeypatch):
    observed: dict[str, object] = {}

    def timeout(*_args, **kwargs):
        observed["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(cmd="gh", timeout=20)

    monkeypatch.setattr(prepared_artifact_module.subprocess, "run", timeout)
    with pytest.raises(PreparedArtifactRestoreError) as error:
        prepared_artifact_module._download_archive(
            SimpleNamespace(_token="synthetic-token"), ARTIFACT_ID
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_DOWNLOAD_TIMEOUT"
    assert observed["timeout"] == 35.0


def test_composed_recovery_prepared_metadata_fits_bounded_capacity(tmp_path):
    identity = _identity(campaign_key="sp500-optimized-catalog-v1")
    archive = _bundle_archive(tmp_path, identity)
    client = _FakeGitHubClient(archive, identity=identity)
    # Measured carrier with both preserved sources; no scientific evaluation.
    client.artifact["size_in_bytes"] = 81_730_797
    prepared_artifact_module._validate_artifact(
        client.artifact, expected_identity=identity, run_id=RUN_ID,
        run_attempt=1, observed_at=OBSERVED_AT,
    )


def test_prepared_capacity_remains_bounded_before_download(tmp_path):
    identity = _identity()
    archive = _bundle_archive(tmp_path, identity)
    client = _FakeGitHubClient(archive, identity=identity)
    client.artifact["size_in_bytes"] = prepared_artifact_module.MAX_ARCHIVE_BYTES + 1
    downloads: list[int] = []

    def must_not_download(artifact_id: int) -> bytes:
        downloads.append(artifact_id)
        raise AssertionError("oversized metadata must be rejected before download")

    with pytest.raises(PreparedArtifactRestoreError) as error:
        restore_prepared_artifact(
            client=client, expected_identity=identity, destination=tmp_path / "restored",
            download_archive=must_not_download,
        )
    assert error.value.code == "CATALOG_PREPARED_ARTIFACT_METADATA_INVALID"
    assert downloads == []
    assert not (tmp_path / "restored").exists()
    assert prepared_artifact_module.MAX_TOTAL_UNCOMPRESSED_BYTES == 256 * 1024 * 1024
    assert prepared_artifact_module.MAX_MEMBER_BYTES == 64 * 1024 * 1024
    assert prepared_artifact_module.MAX_ARCHIVE_MEMBERS == 4096
    assert prepared_artifact_module.MAX_COMPRESSION_RATIO == 100

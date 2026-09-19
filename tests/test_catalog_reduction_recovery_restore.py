from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from aurora.infra.sp500_megarun import catalog_reduction_recovery_restore as restore


ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


def _zip(members: list[tuple[str, bytes, int | None]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content, mode in members:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, content)
    return stream.getvalue()


def test_flat_group_archive_is_materialized_under_named_group_root(tmp_path: Path) -> None:
    destination = tmp_path / "groups" / "catalog-reduction-group-64ea4c3c11181f4a-g00"
    raw = _zip(
        [
            ("receipt.json", b"{}\n", None),
            ("results.parquet", b"PAR1", None),
        ]
    )

    restore._safe_extract_archive(raw, destination)

    assert (destination / "receipt.json").read_bytes() == b"{}\n"
    assert (destination / "results.parquet").read_bytes() == b"PAR1"


@pytest.mark.parametrize(
    "members",
    [
        [("../escape", b"bad", None)],
        [("nested/../../escape", b"bad", None)],
        [("link", b"bad", 0o120000)],
        [("result", b"one", None), ("RESULT", b"two", None)],
    ],
)
def test_archive_extraction_rejects_traversal_links_and_duplicates(
    tmp_path: Path, members: list[tuple[str, bytes, int | None]]
) -> None:
    destination = tmp_path / "extract"

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARCHIVE_"):
        restore._safe_extract_archive(_zip(members), destination)
    assert not (tmp_path / "escape").exists()


def test_archive_extraction_rejects_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "extract"
    destination.mkdir()

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_EXTRACTION_TARGET_INVALID"):
        restore._safe_extract_archive(_zip([("file", b"x", None)]), destination)


def test_profile_artifact_metadata_is_exact() -> None:
    artifact = SimpleNamespace(
        artifact_id=7,
        artifact_name="source-plan",
        digest="sha256:" + "a" * 64,
        size_bytes=4,
        publisher_job_name="gate",
        publish_step_name="Publish plan",
        receipt_sha256=None,
    )
    restore._profile_artifact_metadata(
        {
            "id": 7,
            "name": "source-plan",
            "digest": "sha256:" + "a" * 64,
            "size_in_bytes": 4,
        },
        artifact,
    )
    with pytest.raises(ValueError, match="CATALOG_RECOVERY_ARTIFACT_PROFILE_MISMATCH"):
        restore._profile_artifact_metadata(
            {
                "id": 7,
                "name": "source-plan",
                "digest": "sha256:" + "b" * 64,
                "size_in_bytes": 4,
            },
            artifact,
        )


def test_source_request_rejects_untrusted_issue_actor(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "catalog_controller_actors_v1.json").write_bytes(
        (ROOT / "config/catalog_controller_actors_v1.json").read_bytes()
    )
    (config / "catalog_requester_public_key_v1.pem").write_bytes(
        (ROOT / "config/catalog_requester_public_key_v1.pem").read_bytes()
    )
    issue = {
        "number": 323,
        "user": {"login": "untrusted"},
        "title": "ignored",
        "body": "ignored",
    }
    profile = SimpleNamespace(source_issue_number=323)

    class Client:
        def get_json(self, path: str) -> tuple[object, object]:
            assert path.endswith("/issues/323")
            return issue, object()

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_SOURCE_REQUESTER_INVALID"):
        restore._read_signed_request(Client(), tmp_path, profile, lambda *_: pytest.fail())


def test_restore_requires_sealed_profile_and_token_before_network_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    output = tmp_path / "output"
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", COMMIT)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_INVOCATION_INVALID"):
        restore.restore_catalog_reduction_recovery(
            repo_root=ROOT,
            sealed_plan=sealed,
            output_dir=output,
        )
    assert not output.exists()


def test_restore_requires_non_null_sealed_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sealed = tmp_path / "sealed"
    sealed.mkdir()
    output = tmp_path / "output"
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", COMMIT)
    seen: dict[str, object] = {}

    def reader(root: Path, current: Path, *, expected_bindings: dict[str, str]) -> None:
        seen.update(root=root, current=current, expected_bindings=expected_bindings)
        return None

    monkeypatch.setattr(restore, "read_sealed_reduction_recovery_profile", reader)

    with pytest.raises(ValueError, match="CATALOG_RECOVERY_PROFILE_REQUIRED"):
        restore.restore_catalog_reduction_recovery(
            repo_root=ROOT,
            sealed_plan=sealed,
            output_dir=output,
        )
    assert seen["expected_bindings"] == {"protected_commit_sha": COMMIT}
    assert not output.exists()


def test_real_sealed_profile_reader_rejects_wrong_current_commit(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.catalog_prepared_bundle import (
        materialize_prepared_catalog_plan,
    )
    from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import (
        load_reduction_recovery_profiles,
        read_sealed_reduction_recovery_profile,
    )
    from aurora.tests.test_catalog_prepared_materialization import prepared_transport_fixture

    profile = load_reduction_recovery_profiles(ROOT)[0]
    bundle, _template, _plan, identity, _prepared = prepared_transport_fixture(tmp_path)
    sealed = tmp_path / "sealed"
    materialize_prepared_catalog_plan(
        bundle_dir=bundle,
        expected_identity=identity,
        request_sha256="a" * 64,
        decision_sha256="b" * 64,
        output_dir=sealed,
        reduction_recovery=profile.model_dump(mode="json"),
    )

    with pytest.raises(ValueError, match="CATALOG_SEALED_PLAN_BINDING_INVALID"):
        read_sealed_reduction_recovery_profile(
            ROOT,
            sealed,
            expected_bindings={"protected_commit_sha": "0" * 40},
        )


def test_restore_uses_the_integrated_profile_and_source_consumers() -> None:
    from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import (
        read_sealed_reduction_recovery_profile,
    )
    from aurora.infra.sp500_megarun.catalog_reduction_recovery_source import (
        verify_reduction_recovery_source,
    )

    assert restore.read_sealed_reduction_recovery_profile is read_sealed_reduction_recovery_profile
    assert restore.verify_reduction_recovery_source is verify_reduction_recovery_source


def test_runtime_has_no_forbidden_admission_imports() -> None:
    source = (ROOT / "infra/sp500_megarun/catalog_reduction_recovery_restore.py").read_text(
        encoding="utf-8"
    )
    assert "scripts.admit_catalog_fast_request" not in source
    assert "catalog_fast_authority" not in source

from __future__ import annotations

import io
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from aurora.infra.sp500_megarun import catalog_reduction_recovery_restore as restore
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceiptV1


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


@pytest.mark.parametrize("source_generation,terminal_reason", [(7, "CATALOG_REDUCTION_FAILED"), (10, "CATALOG_ENGINE_STAGE_FAILED")])
def test_happy_restore_orchestrates_real_source_and_owner_archive_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_generation: int, terminal_reason: str
) -> None:
    """Exercise the successful boundary without faking validators or extraction.

    The signed-request, current-profile, and owner lookup are isolated here;
    their authentication failures have focused tests.  The actual terminal
    receipt reader, artifact reader, ZIP extraction, and source validator all
    consume the fixture bytes through one small HTTP-shaped client boundary.
    """
    from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import (
        load_reduction_recovery_profiles,
    )
    from aurora.tests.test_catalog_reduction_recovery_source import (
        build_historical_reduction_source_fixture,
    )

    fixture = build_historical_reduction_source_fixture(tmp_path / "source")
    source_plan = fixture["sealed_plan"]
    group_name = next(path.name for path in fixture["groups"].iterdir() if path.is_dir())

    def zip_tree(root: Path) -> bytes:
        return _zip(
            [
                (path.relative_to(root).as_posix(), path.read_bytes(), None)
                for path in sorted(root.rglob("*"))
                if path.is_file()
            ]
        )

    plan_raw = zip_tree(source_plan)
    group_raw = zip_tree(fixture["groups"] / group_name)
    request_sha = fixture["bindings"]["request_sha256"]
    decision_sha = fixture["bindings"]["decision_sha256"]
    protected_commit = fixture["bindings"]["protected_commit_sha"]
    run_id = 17
    head_sha = protected_commit
    campaign_key = "catalog-fast-canary-v1"
    run_url = f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{run_id}"
    terminal = CatalogTerminalReceiptV1.create(
        state="BLOCKED",
        reason_code=terminal_reason,
        request_sha256=request_sha,
        submission_key_sha256="b" * 64,
        campaign_key=campaign_key,
        prepared_receipt_sha256="f" * 64,
        engine_run_id=run_id,
        run_url=run_url,
        expected_recipe_count=8,
        observed_recipe_count=0,
        queue_seconds=0.0,
        preparation_seconds=0.0,
        computation_seconds=0.0,
        recovery_seconds=0.0,
        reduction_seconds=0.0,
        recovered_block_count=0,
        failure_class="scientific",
        result_science_sha256=None,
        created_at="2026-09-19T10:10:01Z",
    )

    profile_template = load_reduction_recovery_profiles(ROOT)[0]
    plan_template, group_template = profile_template.artifacts
    artifacts = (
        SimpleNamespace(
            role="plan",
            artifact_id=10582715279,
            artifact_name="source-plan",
            digest="sha256:" + hashlib.sha256(plan_raw).hexdigest(),
            size_bytes=len(plan_raw),
            publisher_job_name=plan_template.publisher_job_name,
            publish_step_name=plan_template.publish_step_name,
            receipt_sha256=None,
        ),
        SimpleNamespace(
            role="group",
            artifact_id=10582565863,
            artifact_name=group_name,
            digest="sha256:" + hashlib.sha256(group_raw).hexdigest(),
            size_bytes=len(group_raw),
            publisher_job_name=group_template.publisher_job_name,
            publish_step_name=group_template.publish_step_name,
            receipt_sha256=json.loads(
                (fixture["groups"] / group_name / "receipt.json").read_text(
                    encoding="utf-8"
                )
            )["receipt_sha256"],
        ),
    )
    profile = SimpleNamespace(
        source_generation=source_generation,
        terminal_reason_code=terminal_reason,
        profile_sha256="p" * 64,
        campaign_key=campaign_key,
        source_request_sha256=request_sha,
        source_issue_number=323,
        source_run_id=run_id,
        source_run_attempt=1,
        source_terminal_receipt_sha256=terminal.receipt_sha256,
        source_plan_bindings=fixture["bindings"],
        source_plan_receipt_sha256=fixture["plan_receipt"]["receipt_sha256"],
        science_sha256=fixture["science"],
        catalog_manifest_sha256=fixture["catalog"],
        strategy_ids=fixture["strategy_ids"],
        artifacts=artifacts,
    )
    request = SimpleNamespace(request_sha256=request_sha, campaign_key=campaign_key)
    decision = SimpleNamespace(
        request_sha256=request_sha,
        decision_sha256=decision_sha,
        campaign_key=campaign_key,
        submission_key_sha256="b" * 64,
        prepared_receipt_sha256="f" * 64,
        launch_required=True,
        existing_run_id=None,
    )
    run = {
        "id": run_id,
        "run_attempt": 1,
        "head_sha": head_sha,
        "head_branch": "main",
        "path": ".github/workflows/catalog-fast-controller.yml",
        "status": "completed",
        "conclusion": "failure",
        "repository": {
            "id": 1232647748,
            "full_name": "trading-optimizer-lab-org/aurora",
        },
    }

    def publication_job(name: str, step_name: str) -> dict[str, object]:
        return {
            "id": run_id * 100 + len(name),
            "run_id": run_id,
            "run_attempt": 1,
            "head_sha": head_sha,
            "name": name,
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {
                    "name": step_name,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-09-19T10:10:00Z",
                    "completed_at": "2026-09-19T10:10:04Z",
                }
            ],
        }

    jobs = (
        {
            "id": 1701,
            "run_id": run_id,
            "run_attempt": 1,
            "head_sha": head_sha,
            "name": "finalize",
            "status": "completed",
            "conclusion": "failure",
            "steps": [
                {
                    "name": "Create exactly one terminal receipt",
                    "number": 9,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-09-19T10:10:00Z",
                    "completed_at": "2026-09-19T10:10:01Z",
                },
                {
                    "name": "Publish the terminal receipt before changing the issue",
                    "number": 10,
                    "status": "completed",
                    "conclusion": "success",
                    "started_at": "2026-09-19T10:10:01Z",
                    "completed_at": "2026-09-19T10:10:03Z",
                },
            ],
        },
        publication_job(plan_template.publisher_job_name, plan_template.publish_step_name),
        publication_job(group_template.publisher_job_name, group_template.publish_step_name),
    )
    terminal_buffer = io.BytesIO()
    with zipfile.ZipFile(terminal_buffer, "w") as archive:
        archive.writestr("catalog-terminal-receipt-v1.json", terminal.model_dump_json())
    terminal_raw = terminal_buffer.getvalue()

    def artifact_row(artifact_id: int, name: str, raw: bytes) -> dict[str, object]:
        return {
            "id": artifact_id,
            "name": name,
            "expired": False,
            "size_in_bytes": len(raw),
            "created_at": "2026-09-19T10:10:02Z",
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "workflow_run": {
                "id": run_id,
                "head_sha": head_sha,
                "head_branch": "main",
                "repository_id": 1232647748,
                "head_repository_id": 1232647748,
            },
        }

    rows = {
        f"catalog-terminal-receipt-{request_sha}": artifact_row(
            10582500001, f"catalog-terminal-receipt-{request_sha}", terminal_raw
        ),
        "source-plan": artifact_row(artifacts[0].artifact_id, "source-plan", plan_raw),
        group_name: artifact_row(artifacts[1].artifact_id, group_name, group_raw),
    }
    downloads = {
        10582500001: terminal_raw,
        artifacts[0].artifact_id: plan_raw,
        artifacts[1].artifact_id: group_raw,
    }

    class HttpBoundaryClient:
        repository = "trading-optimizer-lab-org/aurora"

        def get_json(self, path: str) -> tuple[object, object]:
            raise AssertionError(f"unexpected HTTP read: {path}")

        def stable_paginated(self, path: str, *, root: str) -> object:
            assert root == "artifacts"
            name = path.rsplit("?name=", 1)[1]
            return SimpleNamespace(
                stable=True,
                collection=SimpleNamespace(complete=True, rows=(rows[name],)),
            )

    owner = SimpleNamespace(
        run_id=run_id,
        run=run,
        decision=decision,
        jobs=jobs,
        unlaunched_terminal=False,
    )
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("CATALOG_PROTECTED_COMMIT_SHA", protected_commit)
    monkeypatch.setattr(
        restore,
        "read_sealed_reduction_recovery_profile",
        lambda root, sealed, *, expected_bindings: (
            assert_profile_binding(expected_bindings, profile)
        ),
    )
    monkeypatch.setattr(
        restore,
        "_read_signed_request",
        lambda client, root, current_profile, parse_request: request,
    )
    monkeypatch.setattr(restore, "load_fast_gate_owner", lambda **kwargs: owner)

    def assert_profile_binding(
        expected_bindings: dict[str, str], current_profile: object
    ) -> object:
        assert expected_bindings == {"protected_commit_sha": protected_commit}
        return current_profile

    result = restore.restore_catalog_reduction_recovery(
        repo_root=ROOT,
        sealed_plan=fixture["sealed_plan"],
        output_dir=tmp_path / "restored",
        client=HttpBoundaryClient(),
        download_archive=lambda artifact_id: downloads[artifact_id],
    )

    assert result.profile_sha256 == "p" * 64
    assert result.owner_run_id == run_id
    assert result.terminal_receipt_sha256 == terminal.receipt_sha256
    assert result.source_plan_receipt_sha256 == fixture["plan_receipt"]["receipt_sha256"]
    assert result.group_receipt_sha256s == (artifacts[1].receipt_sha256,)
    assert (result.output_dir / "sealed-plan" / "reduction_plan.json").is_file()
    assert (result.output_dir / "groups" / group_name / "receipt.json").is_file()


def test_runtime_has_no_forbidden_admission_imports() -> None:
    source = (ROOT / "infra/sp500_megarun/catalog_reduction_recovery_restore.py").read_text(
        encoding="utf-8"
    )
    assert "scripts.admit_catalog_fast_request" not in source
    assert "catalog_fast_authority" not in source


def _gen11_profile():
    from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import ReductionRecoveryProfileV1

    return ReductionRecoveryProfileV1.model_validate_json(
        (ROOT / "tests/fixtures/catalog_recovery_gen10_source_profile.json").read_text("utf-8")
    )


@pytest.mark.parametrize("generation", [7, 9, 10, 11])
def test_source_request_generation_is_bound_to_gen10_not_target_minus_one(
    monkeypatch: pytest.MonkeyPatch, generation: int
) -> None:
    profile = _gen11_profile()
    request = SimpleNamespace(request_sha256=profile.source_request_sha256,
                              campaign_key=profile.campaign_key, launch_generation=generation)
    monkeypatch.setattr(restore, "_load_controller_actors", lambda _: ({"trusted"}, "public-key"))

    class Client:
        def get_json(self, path):
            assert path.endswith("/issues/333")
            return {"number": 333, "user": {"login": "trusted"}, "title": "signed", "body": "request"}, None

    if generation == 10:
        assert restore._read_signed_request(Client(), ROOT, profile, lambda *_: request) is request
    else:
        with pytest.raises(ValueError, match="CATALOG_RECOVERY_SOURCE_GENERATION_INVALID"):
            restore._read_signed_request(Client(), ROOT, profile, lambda *_: request)


@pytest.mark.parametrize("mutation", [None, "reason", "receipt", "state", "attempt", "commit", "decision", "observed", "science"])
def test_gen10_owner_terminal_requires_exact_failure_and_provenance(mutation: str | None) -> None:
    profile = _gen11_profile()
    request = SimpleNamespace(request_sha256=profile.source_request_sha256, campaign_key=profile.campaign_key)
    owner = SimpleNamespace(run_id=profile.source_run_id,
        run={"run_attempt": 1, "head_sha": profile.source_plan_bindings["protected_commit_sha"]},
        decision=SimpleNamespace(request_sha256=profile.source_request_sha256,
            decision_sha256=profile.source_plan_bindings["decision_sha256"], campaign_key=profile.campaign_key))
    terminal = SimpleNamespace(state="BLOCKED", reason_code="CATALOG_ENGINE_STAGE_FAILED",
        receipt_sha256=profile.source_terminal_receipt_sha256, request_sha256=profile.source_request_sha256,
        campaign_key=profile.campaign_key, observed_recipe_count=0, result_science_sha256=None)
    if mutation == "reason":
        terminal.reason_code = "CATALOG_REDUCTION_FAILED"
    elif mutation == "receipt":
        terminal.receipt_sha256 = "0" * 64
    elif mutation == "state":
        terminal.state = "SUCCESS"
    elif mutation == "attempt":
        owner.run["run_attempt"] = 2
    elif mutation == "commit":
        owner.run["head_sha"] = "0" * 40
    elif mutation == "decision":
        owner.decision.decision_sha256 = "0" * 64
    elif mutation == "observed":
        terminal.observed_recipe_count = 8
    elif mutation == "science":
        terminal.result_science_sha256 = "0" * 64
    if mutation is None:
        restore._require_owner_and_terminal(owner, terminal, profile, request)
    else:
        with pytest.raises(ValueError, match="CATALOG_RECOVERY_(OWNER|TERMINAL)"):
            restore._require_owner_and_terminal(owner, terminal, profile, request)

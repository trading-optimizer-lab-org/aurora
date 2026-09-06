from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
    RebuildableStoreCandidateV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
)
from aurora.infra.sp500_megarun.strategy_catalog import configuration_sha256
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from scripts.prepare_catalog_admission_candidates import (
    _PROTOCOL_COMMON_PATHS,
    _protocol_sha256,
    derive_catalog_work_requirements,
    load_verified_rebuildable_store_inventory,
    verify_fixed_source_artifact_metadata,
)
from test_sp500_catalog_optimization_contract import _task10_contract_payload


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


_CRITICAL_COMMON_PROTOCOL_PATHS = {
    ".github/workflows/catalog-run-controller.yml",
    ".github/actions/catalog-live-controls-audit/action.yml",
    ".github/workflows/catalog-request-reconciler.yml",
    ".github/workflows/catalog-ledger-guard.yml",
    ".github/workflows/catalog-run-watchdog.yml",
    "infra/sp500_megarun/catalog_admission_adapter.py",
    "infra/sp500_megarun/catalog_authority_writer.py",
    "infra/sp500_megarun/catalog_engine_outcome.py",
    "infra/sp500_megarun/catalog_github_controls.py",
    "infra/sp500_megarun/catalog_github_snapshot.py",
    "infra/sp500_megarun/catalog_request_receipt.py",
    "infra/sp500_megarun/catalog_routing_snapshot.py",
    "infra/sp500_megarun/catalog_runtime_audit.py",
    "infra/sp500_megarun/catalog_terminal_adapter.py",
    "infra/sp500_megarun/catalog_worker_failure.py",
    "scripts/audit_catalog_github_controls.py",
    "scripts/prepare_catalog_admission_decision.py",
    "scripts/prepare_catalog_authority_record.py",
    "scripts/prepare_catalog_engine_outcome.py",
    "scripts/prepare_catalog_request_receipt.py",
    "scripts/prepare_catalog_terminal_decision.py",
    "scripts/prepare_catalog_terminal_evidence.py",
    "scripts/prepare_catalog_terminal_request_receipt.py",
    "scripts/prepare_catalog_worker_failure.py",
    "scripts/run_catalog_recipe_worker_guarded.py",
    "scripts/verify_catalog_authority_record.py",
    "scripts/verify_catalog_terminal_science.py",
}


def _contract() -> RunOptimizationContractV1:
    return RunOptimizationContractV1.model_validate(_task10_contract_payload())


def _campaign_entry() -> CatalogCampaignEntryV1:
    registry = load_catalog_campaign_registry(
        ROOT / "config/catalog_campaign_registry_v1.json"
    )
    return resolve_catalog_campaign(registry, "sp500-optimized-catalog-v1", ROOT)


def _component(lane: str, configuration_sha256: str) -> dict[str, object]:
    return {
        "lane_id": lane,
        "configuration": {"window": 20, "direction": "continuation"},
        "configuration_sha256": configuration_sha256,
    }


def test_candidate_derivation_deduplicates_global_components_without_science_compute() -> None:
    first = _component("F001", "1" * 64)
    second = _component("F002", "2" * 64)
    rows = [
        {
            "strategy_id": "strategy-a",
            "scientific_recipe_sha256": "a" * 64,
            "feature_count": 2,
            "components": [first, second],
        },
        {
            "strategy_id": "strategy-b",
            "scientific_recipe_sha256": "b" * 64,
            "feature_count": 1,
            "components": [first],
        },
    ]

    components, recipes = derive_catalog_work_requirements(
        contract=_contract(),
        catalog_rows=rows,
        selected_rows=[],
        feature_contract_sha256="6" * 64,
    )

    assert len(components) == 2
    assert len({item.component_id for item in components}) == 2
    assert {item.source_configuration_sha256 for item in components} == {
        "1" * 64,
        "2" * 64,
    }
    assert all(item.component_id != item.source_configuration_sha256 for item in components)
    by_strategy = {item.strategy_id: item for item in recipes}
    assert len(by_strategy["strategy-a"].component_ids) == 2
    assert len(by_strategy["strategy-b"].component_ids) == 1
    assert set(by_strategy["strategy-b"].component_ids) < set(
        by_strategy["strategy-a"].component_ids
    )


def test_candidate_derivation_preserves_component_runtime_datasets() -> None:
    component = _component("F032", "1" * 64)

    components, _recipes = derive_catalog_work_requirements(
        contract=_contract(),
        catalog_rows=[
            {
                "strategy_id": "strategy-a",
                "feature_count": 1,
                "components": [component],
            }
        ],
        selected_rows=[],
        feature_contract_sha256="6" * 64,
    )

    assert components[0].runtime_dataset_ids == (
        "D_CALENDAR",
        "D_CFTC_LEGACY",
        "D_FINRA_MARGIN",
        "D_FIN_COND",
        "D_FOMC_PUBLIC",
        "D_FRENCH_FACTORS",
        "D_FRENCH_INDUSTRIES",
        "D_FX",
        "D_GOLD",
        "D_GOYAL",
        "D_MACRO_PIT",
        "D_PHILLY_RT",
        "D_RATES",
        "D_SHILLER",
        "D_SPY",
        "D_WTI",
        "D_Z1",
    )


def test_candidate_derivation_normalizes_selected_strategy_keys_to_component_hashes() -> None:
    selected = {
        "source_strategy_key": "3" * 64,
        "lane_id": "F150",
        "configuration": {"kind": "attention", "window": 756},
    }
    catalog_component = _component("F001", "1" * 64)

    components, _recipes = derive_catalog_work_requirements(
        contract=_contract(),
        catalog_rows=[
            {
                "strategy_id": "strategy-a",
                "feature_count": 1,
                "components": [catalog_component],
            }
        ],
        selected_rows=[selected],
        feature_contract_sha256="6" * 64,
    )

    expected = configuration_sha256(
        str(selected["lane_id"]),
        selected["configuration"],
    )
    assert {item.source_configuration_sha256 for item in components} == {
        "1" * 64,
        expected,
    }


def test_candidate_derivation_rejects_an_invalid_selected_strategy_key() -> None:
    with pytest.raises(ValueError, match="CATALOG_CANDIDATE_COMPONENT_INVALID"):
        derive_catalog_work_requirements(
            contract=_contract(),
            catalog_rows=[
                {
                    "strategy_id": "strategy-a",
                    "feature_count": 1,
                    "components": [_component("F001", "1" * 64)],
                }
            ],
            selected_rows=[
                {
                    "source_strategy_key": "not-a-sha256",
                    "lane_id": "F150",
                    "configuration": {"kind": "attention", "window": 756},
                }
            ],
            feature_contract_sha256="6" * 64,
        )


def test_registered_sp500_selected_components_use_the_canonical_component_identity() -> None:
    selected = json.loads(
        (ROOT / "config/sp500_megarun_selected_dehb_13.json").read_text("utf-8")
    )
    components, _recipes = derive_catalog_work_requirements(
        contract=_contract(),
        catalog_rows=[
            {
                "strategy_id": "strategy-a",
                "feature_count": 1,
                "components": [_component("F001", "1" * 64)],
            }
        ],
        selected_rows=selected,
        feature_contract_sha256="6" * 64,
    )

    observed = {item.source_configuration_sha256 for item in components}
    expected = {
        configuration_sha256(str(item["lane_id"]), item["configuration"])
        for item in selected
    }
    assert expected <= observed


def _source_contract() -> dict[str, object]:
    return {
        "schema_version": "1",
        "repository": "owner/repo",
        "artifacts": [
            {
                "contract_name": "runtime_input_pack_v1",
                "classification": "training_input",
                "run_id": 11,
                "artifact_id": 101,
                "artifact_name": "runtime-input",
                "artifact_size_in_bytes": 123,
                "artifact_digest": f"sha256:{'1' * 64}",
                "head_sha": "2" * 40,
                "validation_opened": False,
                "locked_opened": False,
            },
            {
                "contract_name": "reference_oracle_v1",
                "classification": "training_reference",
                "run_id": 12,
                "artifact_id": 102,
                "artifact_name": "reference",
                "artifact_size_in_bytes": 456,
                "artifact_digest": f"sha256:{'3' * 64}",
                "head_sha": "4" * 40,
                "validation_opened": False,
                "locked_opened": False,
            },
        ],
    }


def _metadata() -> dict[int, dict[str, object]]:
    return {
        101: {
            "id": 101,
            "name": "runtime-input",
            "size_in_bytes": 123,
            "digest": f"sha256:{'1' * 64}",
            "expired": False,
            "workflow_run": {"id": 11, "head_sha": "2" * 40},
        },
        102: {
            "id": 102,
            "name": "reference",
            "size_in_bytes": 456,
            "digest": f"sha256:{'3' * 64}",
            "expired": False,
            "workflow_run": {"id": 12, "head_sha": "4" * 40},
        },
    }


def test_fixed_source_metadata_is_complete_hash_bound_and_closed() -> None:
    evidence, normalized = verify_fixed_source_artifact_metadata(
        source_contract=_source_contract(),
        artifact_metadata=_metadata(),
        required_contracts=("runtime_input_pack_v1", "reference_oracle_v1"),
        observed_at=NOW,
    )

    assert evidence.status == "ready"
    assert evidence.artifacts_exist is True
    assert evidence.hashes_bound is True
    assert evidence.immutable is True
    assert [row["artifact_id"] for row in normalized] == [101, 102]


def _store_index_fixture() -> tuple[CatalogRebuildableStoreIndexV1, str]:
    identity = "7" * 64
    manifest = "8" * 64
    cache_key = f"aurora-catalog-v1-{identity}-{manifest}-main"
    candidate = RebuildableStoreCandidateV1(
        object_family="component",
        logical_id=identity,
        identity_sha256=identity,
        content_manifest_sha256=manifest,
        content_sha256="9" * 64,
        storage_kind="actions_cache",
        status="verified",
        source_branch="main",
        contained_logical_ids=("a" * 64,),
        logical_identity_bindings=(("a" * 64, "a" * 64),),
        logical_content_bindings=(("a" * 64, "c" * 64),),
        cache_key=cache_key,
        file_hashes=(("manifest.json", "b" * 64),),
        manifest_verified=True,
        content_verified=True,
        scope_verified=True,
    )
    index = CatalogRebuildableStoreIndexV1.create(
        artifact_name="catalog-rebuildable-store-index-v1",
        repository="owner/repo",
        writer_workflow=".github/workflows/catalog-optimized-run.yml",
        writer_run_id=123,
        writer_run_attempt=1,
        protected_commit_sha="c" * 40,
        source_branch="main",
        authority_id="11111111-1111-7111-8111-111111111111",
        campaign_id="d" * 64,
        science_sha256="e" * 64,
        execution_plan_sha256="f" * 64,
        execution_protocol_sha256="1" * 64,
        candidates=(candidate,),
    )
    return index, cache_key


def _store_index_zip(index: CatalogRebuildableStoreIndexV1) -> bytes:
    raw = BytesIO()
    with zipfile.ZipFile(raw, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "catalog-rebuildable-store-index-v1.json",
            json.dumps(
                index.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
        )
    return raw.getvalue()


class _StoreIndexClient:
    def get_json(self, path: str) -> tuple[object, object]:
        assert path == "/repos/owner/repo/actions/runs/123"
        return (
            {
                "id": 123,
                "run_attempt": 1,
                "path": ".github/workflows/catalog-optimized-run.yml",
                "head_branch": "main",
                "head_sha": "c" * 40,
                "status": "completed",
                "repository": {"full_name": "owner/repo"},
            },
            object(),
        )


class _ReusableStoreIndexClient:
    publication_mutation: str | None = None

    def paginated(self, path: str, *, root: str) -> SimpleNamespace:
        assert path == "/repos/owner/repo/actions/runs/123/attempts/1/jobs"
        assert root == "jobs"
        job = {
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "c" * 40,
            "name": "engine / verify_component_store",
            "status": "completed",
            "conclusion": "success",
            "steps": [{
                "name": "Publish the immutable global reuse index when cache read-back succeeded",
                "status": "completed",
                "conclusion": "success",
            }],
        }
        mutation = self.publication_mutation
        if mutation == "missing":
            return SimpleNamespace(rows=(), complete=True)
        if mutation == "run":
            job["run_id"] = 124
        elif mutation == "attempt":
            job["run_attempt"] = 2
        elif mutation == "commit":
            job["head_sha"] = "d" * 40
        elif mutation == "skipped":
            job["steps"] = []
        rows = (job, job) if mutation == "duplicate" else (job,)
        return SimpleNamespace(rows=rows, complete=True)

    def get_json(self, path: str) -> tuple[object, object]:
        assert path == "/repos/owner/repo/actions/runs/123"
        return (
            {
                "id": 123,
                "run_attempt": 1,
                "path": ".github/workflows/catalog-fast-controller.yml",
                "head_branch": "main",
                "head_sha": "c" * 40,
                "status": "completed",
                "repository": {"full_name": "owner/repo"},
                "referenced_workflows": [
                    {
                        "path": (
                            "owner/repo/.github/workflows/"
                            f"catalog-optimized-run.yml@{'c' * 40}"
                        ),
                        "ref": "refs/heads/main",
                        "sha": "c" * 40,
                    }
                ],
            },
            object(),
        )


@pytest.mark.parametrize("publication_mutation", (None, "missing", "run", "attempt", "commit", "skipped", "duplicate"))
def test_store_index_accepts_only_a_verified_reusable_workflow_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication_mutation: str | None
) -> None:
    index, cache_key = _store_index_fixture()
    archive = _store_index_zip(index)

    def fake_download(**kwargs: object) -> bytes:
        destination = Path(str(kwargs["destination"]))
        destination.write_bytes(archive)
        return archive

    monkeypatch.setattr(
        "scripts.prepare_catalog_admission_candidates._download_store_index_archive",
        fake_download,
    )
    metadata = {
        "id": 55,
        "name": "catalog-rebuildable-store-index-v1",
        "size_in_bytes": len(archive),
        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "expired": False,
        "workflow_run": {
            "id": 123,
            "head_branch": "main",
            "head_sha": "c" * 40,
        },
    }

    client = _ReusableStoreIndexClient()
    client.publication_mutation = publication_mutation
    if publication_mutation is not None:
        with pytest.raises(ValueError, match="CATALOG_STORE_INDEX_PUBLICATION_INVALID"):
            load_verified_rebuildable_store_inventory(
                expected_commit="c" * 40,
                artifacts=(metadata,),
                caches=({"id": 77, "key": cache_key, "ref": "refs/heads/main"},),
                client=client,
                repository="owner/repo",
                token="test-token",
                download_root=tmp_path / "reusable",
            )
        return
    inventory = load_verified_rebuildable_store_inventory(
        expected_commit="c" * 40,
        artifacts=(metadata,),
        caches=({"id": 77, "key": cache_key, "ref": "refs/heads/main"},),
        client=client,
        repository="owner/repo",
        token="test-token",
        download_root=tmp_path / "reusable",
    )
    assert inventory.candidates == index.candidates


@pytest.mark.parametrize(
    "mutation",
    ("repository", "sha", "ref", "missing_reference", "digest", "artifact_run"),
)
def test_reusable_store_index_rejects_unverified_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    index, cache_key = _store_index_fixture()
    archive = _store_index_zip(index)
    run, response = _ReusableStoreIndexClient().get_json(
        "/repos/owner/repo/actions/runs/123"
    )
    assert isinstance(run, dict)
    reference = run["referenced_workflows"][0]
    metadata = {
        "id": 55,
        "name": "catalog-rebuildable-store-index-v1",
        "size_in_bytes": len(archive),
        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "expired": False,
        "workflow_run": {
            "id": 123,
            "head_branch": "main",
            "head_sha": "c" * 40,
        },
    }
    expected_error = "CATALOG_STORE_INDEX_WRITER_RUN_INVALID"
    if mutation == "repository":
        reference["path"] = reference["path"].replace("owner/repo/", "other/repo/")
    elif mutation == "sha":
        reference["sha"] = "d" * 40
    elif mutation == "ref":
        reference["ref"] = "refs/heads/untrusted"
    elif mutation == "missing_reference":
        run.pop("referenced_workflows")
    elif mutation == "digest":
        metadata["digest"] = f"sha256:{'0' * 64}"
        expected_error = "CATALOG_STORE_INDEX_ARTIFACT_DIGEST_INVALID"
    elif mutation == "artifact_run":
        metadata["workflow_run"] = {
            "id": 124, "head_branch": "main", "head_sha": "c" * 40
        }

    def fake_download(**kwargs: object) -> bytes:
        Path(str(kwargs["destination"])).write_bytes(archive)
        return archive

    def get_json(self: object, path: str) -> tuple[object, object]:
        assert path == "/repos/owner/repo/actions/runs/123"
        return run, response

    monkeypatch.setattr(
        "scripts.prepare_catalog_admission_candidates._download_store_index_archive",
        fake_download,
    )
    monkeypatch.setattr(_ReusableStoreIndexClient, "get_json", get_json)
    with pytest.raises(ValueError, match=expected_error):
        load_verified_rebuildable_store_inventory(
            expected_commit="c" * 40,
            artifacts=(metadata,),
            caches=({"id": 77, "key": cache_key, "ref": "refs/heads/main"},),
            client=_ReusableStoreIndexClient(),
            repository="owner/repo",
            token="test-token",
            download_root=tmp_path / mutation,
        )


@pytest.mark.parametrize("current_commit", ("c" * 40, "d" * 40))
def test_runtime_reuse_requires_current_source_but_preserves_other_families(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, current_commit: str
) -> None:
    previous, _ = _store_index_fixture()
    component = previous.candidates[0]
    candidates = [component]
    for family, logical_id, digit in (
        ("runtime", "runtime", "2"),
        ("prepared_input", "core", "3"),
    ):
        identity = digit * 64
        candidates.append(RebuildableStoreCandidateV1.model_validate({
            **component.model_dump(mode="json"),
            "object_family": family,
            "logical_id": logical_id,
            "identity_sha256": identity,
            "cache_key": f"aurora-catalog-v1-{identity}-{component.content_manifest_sha256}-main",
        }))
    index = CatalogRebuildableStoreIndexV1.create(
        **previous.model_dump(mode="json", exclude={"index_sha256", "candidates"}),
        candidates=candidates,
    )
    archive = _store_index_zip(index)

    def fake_download(**kwargs: object) -> bytes:
        Path(str(kwargs["destination"])).write_bytes(archive)
        return archive

    monkeypatch.setattr(
        "scripts.prepare_catalog_admission_candidates._download_store_index_archive",
        fake_download,
    )
    metadata = {
        "id": 55, "name": "catalog-rebuildable-store-index-v1",
        "size_in_bytes": len(archive),
        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "expired": False,
        "workflow_run": {"id": 123, "head_branch": "main", "head_sha": "c" * 40},
    }
    inventory = load_verified_rebuildable_store_inventory(
        artifacts=(metadata,),
        caches=tuple(
            {"id": ordinal, "key": candidate.cache_key, "ref": "refs/heads/main"}
            for ordinal, candidate in enumerate(index.candidates, start=77)
        ),
        client=_StoreIndexClient(),
        repository="owner/repo", token="test-token",
        download_root=tmp_path / "verified",
        expected_commit=current_commit,
    )
    expected = tuple(
        candidate for candidate in index.candidates
        if candidate.object_family != "runtime" or current_commit == "c" * 40
    )
    assert inventory.candidates == expected
    assert {row.object_family for row in inventory.candidates} >= {"component", "prepared_input"}


def test_content_bound_store_index_promotes_only_a_still_live_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, cache_key = _store_index_fixture()
    archive = _store_index_zip(index)

    def fake_download(**kwargs: object) -> bytes:
        destination = Path(str(kwargs["destination"]))
        destination.write_bytes(archive)
        return archive

    monkeypatch.setattr(
        "scripts.prepare_catalog_admission_candidates._download_store_index_archive",
        fake_download,
    )
    metadata = {
        "id": 55,
        "name": "catalog-rebuildable-store-index-v1",
        "size_in_bytes": len(archive),
        "digest": f"sha256:{hashlib.sha256(archive).hexdigest()}",
        "expired": False,
        "workflow_run": {
            "id": 123,
            "head_branch": "main",
            "head_sha": "c" * 40,
        },
    }
    cache = {"id": 77, "key": cache_key, "ref": "refs/heads/main"}

    warm = load_verified_rebuildable_store_inventory(
        expected_commit="c" * 40,
        artifacts=(metadata,),
        caches=(cache,),
        client=_StoreIndexClient(),  # type: ignore[arg-type]
        repository="owner/repo",
        token="test-token",
        download_root=tmp_path / "warm",
    )
    assert warm.candidates == index.candidates

    cold = load_verified_rebuildable_store_inventory(
        expected_commit="c" * 40,
        artifacts=(metadata,),
        caches=({**cache, "key": "unrelated"},),
        client=_StoreIndexClient(),  # type: ignore[arg-type]
        repository="owner/repo",
        token="test-token",
        download_root=tmp_path / "cold",
    )
    assert cold.candidates == ()


def test_store_index_rejects_archive_digest_or_writer_provenance_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index, cache_key = _store_index_fixture()
    archive = _store_index_zip(index)

    def fake_download(**kwargs: object) -> bytes:
        destination = Path(str(kwargs["destination"]))
        destination.write_bytes(archive)
        return archive

    monkeypatch.setattr(
        "scripts.prepare_catalog_admission_candidates._download_store_index_archive",
        fake_download,
    )
    metadata = {
        "id": 55,
        "name": "catalog-rebuildable-store-index-v1",
        "size_in_bytes": len(archive),
        "digest": f"sha256:{'0' * 64}",
        "expired": False,
        "workflow_run": {
            "id": 123,
            "head_branch": "main",
            "head_sha": "c" * 40,
        },
    }
    with pytest.raises(ValueError, match="CATALOG_STORE_INDEX_ARTIFACT_DIGEST_INVALID"):
        load_verified_rebuildable_store_inventory(
            expected_commit="c" * 40,
            artifacts=(metadata,),
            caches=(
                {"id": 77, "key": cache_key, "ref": "refs/heads/main"},
            ),
            client=_StoreIndexClient(),  # type: ignore[arg-type]
            repository="owner/repo",
            token="test-token",
            download_root=tmp_path / "invalid",
        )


@pytest.mark.parametrize(
    "mutation",
    ("digest", "size_in_bytes", "expired", "workflow_run"),
)
def test_fixed_source_metadata_mismatch_blocks(mutation: str) -> None:
    metadata = _metadata()
    metadata[101][mutation] = (
        True if mutation == "expired" else ({"id": 99, "head_sha": "2" * 40} if mutation == "workflow_run" else "wrong")
    )

    with pytest.raises(ValueError, match="CATALOG_SOURCE_ARTIFACT_METADATA_INVALID"):
        verify_fixed_source_artifact_metadata(
            source_contract=_source_contract(),
            artifact_metadata=metadata,
            required_contracts=("runtime_input_pack_v1", "reference_oracle_v1"),
            observed_at=NOW,
        )


def test_candidate_cli_has_no_arbitrary_path_network_or_command_selection() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/prepare_catalog_admission_candidates.py"),
            "--help",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for forbidden in (
        "--repository",
        "--url",
        "--token",
        "--command",
        "--workflow",
        "--campaign",
        "--catalog-dir",
        "--policy",
    ):
        assert forbidden not in result.stdout


def test_candidate_documents_never_embed_issue_text_or_absolute_paths(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1",
        "request_sha256": "a" * 64,
        "campaign_id": "b" * 64,
        "content": {"path": "config/fixed.json"},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    target = tmp_path / "candidate.json"
    target.write_text(raw + "\n", encoding="utf-8")

    assert str(tmp_path) not in target.read_text("utf-8")
    assert "[AURORA CATALOG RUN REQUEST]" not in target.read_text("utf-8")


def test_execution_protocol_common_manifest_is_closed_and_complete() -> None:
    assert len(_PROTOCOL_COMMON_PATHS) == len(set(_PROTOCOL_COMMON_PATHS))
    assert _CRITICAL_COMMON_PROTOCOL_PATHS <= set(_PROTOCOL_COMMON_PATHS)
    assert ".github/actions/catalog-live-controls-audit/action.yml" in _PROTOCOL_COMMON_PATHS
    assert ".github/workflows/catalog-live-controls-audit.yml" not in _PROTOCOL_COMMON_PATHS
    for relative in _PROTOCOL_COMMON_PATHS:
        assert relative == Path(relative).as_posix()
        assert not Path(relative).is_absolute()
        assert ".." not in Path(relative).parts
        assert (ROOT / relative).is_file(), relative


def test_execution_protocol_hash_changes_for_any_sealed_common_file(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for relative in _PROTOCOL_COMMON_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"sealed:{relative}\n".encode())
    entry = _campaign_entry()
    original = _protocol_sha256(
        root=root,
        entry=entry,
        manifest_sha256="a" * 64,
    )

    for relative in _PROTOCOL_COMMON_PATHS:
        path = root / relative
        before = path.read_bytes()
        path.write_bytes(before + b"changed\n")
        assert (
            _protocol_sha256(
                root=root,
                entry=entry,
                manifest_sha256="a" * 64,
            )
            != original
        ), relative
        path.write_bytes(before)


def test_execution_protocol_rejects_missing_sealed_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    for relative in _PROTOCOL_COMMON_PATHS[:-1]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_EXECUTION_PROTOCOL_FILE_INVALID"):
        _protocol_sha256(
            root=root,
            entry=_campaign_entry(),
            manifest_sha256="a" * 64,
        )

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (
    RebuildableStoreCandidateV1,
    select_component_store_candidates,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (
    CatalogRebuildableStoreIndexV1,
)
from scripts import build_catalog_rebuildable_store_index as builder


AUTHORITY_ID = "11111111-1111-7111-8111-111111111111"
CAMPAIGN_ID = "1" * 64
SCIENCE_SHA = "2" * 64
PLAN_SHA = "3" * 64
PROTOCOL_SHA = "4" * 64
HEAD_SHA = "5" * 40
RUNTIME_IDENTITY = "6" * 64
PREPARED_IDENTITY = "7" * 64
BUNDLE_IDENTITY = "8" * 64
COMPONENT_ID = "9" * 64


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


class _RunClient:
    def __init__(self, repository: str, token: str) -> None:
        assert repository == "owner/repo"
        assert token == "token"

    def get_json(self, path: str) -> tuple[object, object]:
        assert path == "/repos/owner/repo/actions/runs/123"
        return (
            {
                "id": 123,
                "run_attempt": 1,
                "head_branch": "main",
                "head_sha": HEAD_SHA,
                "path": ".github/workflows/catalog-prepare.yml",
            },
            object(),
        )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, set[str]]:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "wheel.whl").write_bytes(b"wheel")
    runtime_manifest = {
        "schema_version": "1",
        "runtime_identity_sha256": RUNTIME_IDENTITY,
        "object_sha256": "a" * 64,
    }
    _write_json(runtime / "runtime_manifest.json", runtime_manifest)
    runtime_manifest_sha = hashlib.sha256(
        (runtime / "runtime_manifest.json").read_bytes()
    ).hexdigest()
    runtime_key = (
        f"aurora-catalog-v1-{RUNTIME_IDENTITY}-{runtime_manifest_sha}-main"
    )

    prepared_files = [
        {
            "path": "fragment.bin",
            "sha256": hashlib.sha256(b"fragment").hexdigest(),
            "size_bytes": len(b"fragment"),
        }
    ]
    prepared_manifest_sha = hashlib.sha256(
        json.dumps(
            prepared_files, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    prepared_key = (
        f"aurora-catalog-v1-{PREPARED_IDENTITY}-{prepared_manifest_sha}-main"
    )

    component = tmp_path / "components" / "transport"
    component.mkdir(parents=True)
    (component / "signal.bin").write_bytes(b"signal")
    wrapper_identity = {
        "schema_version": "1",
        "bundle_identity_sha256": BUNDLE_IDENTITY,
        "component_store_manifest_sha256": "b" * 64,
        "component_count": 1,
        "components": [
            {
                "component_id": COMPONENT_ID,
                "source_configuration_sha256": "c" * 64,
                "result_sha256": "d" * 64,
            }
        ],
        "validation_opened": False,
        "locked_opened": False,
    }
    wrapper = {
        **wrapper_identity,
        "manifest_sha256": canonical_sha256(wrapper_identity),
    }
    _write_json(component / "component_bundle_manifest.json", wrapper)
    component_key = (
        f"aurora-catalog-v1-{BUNDLE_IDENTITY}-"
        f"{wrapper['manifest_sha256']}-main"
    )

    seal_identity = {
        "schema_version": "1",
        "request_sha256": "e" * 64,
        "authority_id": AUTHORITY_ID,
        "campaign_id": CAMPAIGN_ID,
        "science_sha256": SCIENCE_SHA,
        "execution_plan_sha256": PLAN_SHA,
        "execution_protocol_sha256": PROTOCOL_SHA,
        "protected_commit_sha": HEAD_SHA,
        "runtime_identity_sha256": RUNTIME_IDENTITY,
        "runtime_manifest_sha256": runtime_manifest_sha,
        "prepared_input_identity_sha256": PREPARED_IDENTITY,
        "source_artifacts_sha256": "f" * 64,
        "source_fetch_receipt_sha256": None,
        "partitions": [
            {
                "logical_id": "runtime-fragment-core",
                "cache_key": prepared_key,
                "manifest_sha256": prepared_manifest_sha,
                "file_count": 1,
                "size_bytes": len(b"fragment"),
                "files": prepared_files,
                "cache_hit": False,
            }
        ],
        "validation_opened": False,
        "locked_opened": False,
    }
    seal = {**seal_identity, "seal_sha256": canonical_sha256(seal_identity)}
    seal_path = tmp_path / "runtime-prepared-seal.json"
    _write_json(seal_path, seal)

    caches = tmp_path / "caches.json"
    live_keys = {runtime_key, prepared_key, component_key}
    _write_json(
        caches,
        [
            {
                "actions_caches": [
                    {"id": index, "key": key, "ref": "refs/heads/main"}
                    for index, key in enumerate(sorted(live_keys), start=1)
                ]
            }
        ],
    )
    return seal_path, runtime, component.parent, caches, live_keys


def test_builder_emits_runtime_prepared_and_component_cache_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seal, runtime, components, caches, live_keys = _fixture(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CATALOG_AUTHORITY_ID", AUTHORITY_ID)
    monkeypatch.setenv("CATALOG_CAMPAIGN_ID", CAMPAIGN_ID)
    monkeypatch.setenv("CATALOG_SCIENCE_SHA256", SCIENCE_SHA)
    monkeypatch.setenv("CATALOG_EXECUTION_PLAN_SHA256", PLAN_SHA)
    monkeypatch.setenv("CATALOG_EXECUTION_PROTOCOL_SHA256", PROTOCOL_SHA)
    monkeypatch.setattr(builder, "CatalogGitHubReadOnlyClient", _RunClient)

    index = builder.build_index(
        runtime_prepared_seal=seal,
        runtime_root=runtime,
        component_root=components,
        cache_inventory=caches,
    )

    assert isinstance(index, CatalogRebuildableStoreIndexV1)
    assert {item.object_family for item in index.candidates} == {
        "runtime",
        "prepared_input",
        "component",
    }
    assert {item.cache_key for item in index.candidates} == live_keys
    assert index.writer_workflow == ".github/workflows/catalog-optimized-run.yml"
    assert index.index_sha256 == canonical_sha256(
        index.model_dump(mode="json", exclude={"index_sha256"})
    )


def test_builder_omits_a_cache_not_confirmed_by_the_live_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seal, runtime, components, caches, _ = _fixture(tmp_path)
    payload = json.loads(caches.read_text(encoding="utf-8"))
    payload[0]["actions_caches"] = payload[0]["actions_caches"][:1]
    _write_json(caches, payload)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CATALOG_AUTHORITY_ID", AUTHORITY_ID)
    monkeypatch.setenv("CATALOG_CAMPAIGN_ID", CAMPAIGN_ID)
    monkeypatch.setenv("CATALOG_SCIENCE_SHA256", SCIENCE_SHA)
    monkeypatch.setenv("CATALOG_EXECUTION_PLAN_SHA256", PLAN_SHA)
    monkeypatch.setenv("CATALOG_EXECUTION_PROTOCOL_SHA256", PROTOCOL_SHA)
    monkeypatch.setattr(builder, "CatalogGitHubReadOnlyClient", _RunClient)

    index = builder.build_index(
        runtime_prepared_seal=seal,
        runtime_root=runtime,
        component_root=components,
        cache_inventory=caches,
    )

    assert len(index.candidates) == 1


def _component_candidate(
    *,
    ordinal: int,
    bindings: tuple[tuple[str, str], ...],
) -> RebuildableStoreCandidateV1:
    identity = f"{ordinal:064x}"
    manifest = f"{ordinal + 100:064x}"
    logical_ids = tuple(item[0] for item in bindings)
    return RebuildableStoreCandidateV1(
        object_family="component",
        logical_id=identity,
        identity_sha256=identity,
        content_manifest_sha256=manifest,
        content_sha256=f"{ordinal + 200:064x}",
        storage_kind="actions_cache",
        status="verified",
        source_branch="main",
        contained_logical_ids=logical_ids,
        logical_identity_bindings=tuple((item, item) for item in logical_ids),
        logical_content_bindings=bindings,
        cache_key=f"aurora-catalog-v1-{identity}-{manifest}-main",
        file_hashes=(("component_bundle_manifest.json", f"{ordinal + 300:064x}"),),
        manifest_verified=True,
        content_verified=True,
        scope_verified=True,
    )


def test_overlapping_warm_bundles_choose_one_best_location_without_recompute() -> None:
    first = "a" * 64
    second = "b" * 64
    narrow = _component_candidate(ordinal=1, bindings=((first, "c" * 64),))
    broad = _component_candidate(
        ordinal=2,
        bindings=((first, "c" * 64), (second, "d" * 64)),
    )

    selected = select_component_store_candidates(
        (narrow, broad),
        required_identity_by_id={first: first, second: second},
    )

    assert selected == {first: broad, second: broad}


def test_overlapping_warm_bundles_block_conflicting_component_content() -> None:
    component = "a" * 64
    first = _component_candidate(
        ordinal=1, bindings=((component, "c" * 64),)
    )
    conflict = _component_candidate(
        ordinal=2, bindings=((component, "d" * 64),)
    )

    with pytest.raises(ValueError, match="REBUILDABLE_COMPONENT_CONTENT_CONFLICT"):
        select_component_store_candidates(
            (first, conflict),
            required_identity_by_id={component: component},
        )

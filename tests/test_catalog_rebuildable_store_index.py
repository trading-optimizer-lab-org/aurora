from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

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
                "total_count": len(live_keys),
                "actions_caches": [
                    {"id": index, "key": key, "ref": "refs/heads/main", "version": "v1", "size_in_bytes": 100}
                    for index, key in enumerate(sorted(live_keys), start=1)
                ]
            }
        ],
    )
    return seal_path, runtime, component.parent, caches, live_keys


def _workflow_steps() -> dict[str, dict]:
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/catalog-optimized-run.yml"
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8-sig"))["jobs"]
    return {step["id"]: step for step in jobs["verify_component_store"]["steps"] if "id" in step}


def _set_builder_context(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "token",
        "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
        "CATALOG_AUTHORITY_ID": AUTHORITY_ID, "CATALOG_CAMPAIGN_ID": CAMPAIGN_ID,
        "CATALOG_SCIENCE_SHA256": SCIENCE_SHA, "CATALOG_EXECUTION_PLAN_SHA256": PLAN_SHA,
        "CATALOG_EXECUTION_PROTOCOL_SHA256": PROTOCOL_SHA,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(builder, "CatalogGitHubReadOnlyClient", _RunClient)


def test_real_workflow_capture_and_index_accept_access_time_and_unrelated_cache_churn(tmp_path, monkeypatch):
    seal, runtime, components, caches, expected_keys = _fixture(tmp_path)
    first = json.loads(caches.read_text())
    second = json.loads(caches.read_text())
    first[0]["actions_caches"].append({"id": 98, "key": "removed-ci", "ref": "refs/heads/main", "version": "v1", "size_in_bytes": 100})
    first[0]["total_count"] += 1
    for row in second[0]["actions_caches"]:
        row["last_accessed_at"] = "2026-09-13T18:50:43Z"
    second[0]["actions_caches"].reverse()
    second[0]["actions_caches"].append({"id": 99, "key": "unrelated-ci", "ref": "refs/heads/main", "version": "v1", "size_in_bytes": 100})
    second[0]["total_count"] += 1
    second_rows = second[0]["actions_caches"]
    second = [
        {"total_count": len(second_rows), "actions_caches": second_rows[:2]},
        {"total_count": len(second_rows), "actions_caches": second_rows[2:]},
    ]
    _write_json(tmp_path / "inventory-1.json", first)
    _write_json(tmp_path / "inventory-2.json", second)
    steps = _workflow_steps()
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if bash is None or not Path(bash).is_file():
        pytest.skip("Bash required for the actual workflow capture script")
    _set_builder_context(monkeypatch)
    monkeypatch.setenv("RUNNER_TEMP", ".")
    capture = subprocess.run(
        [bash, "-c", 'gh() { cat "inventory-$snapshot.json"; };\n' + steps["cache_inventory"]["run"]],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert capture.returncode == 0, capture.stderr
    (tmp_path / "runtime-prepared-seal").mkdir()
    seal.rename(tmp_path / "runtime-prepared-seal/runtime-prepared-seal.json")
    runtime.rename(tmp_path / "runtime-transport")
    components.rename(tmp_path / "component-transports")
    monkeypatch.chdir(tmp_path)
    argv = shlex.split(steps["store_index"]["run"])
    monkeypatch.setattr(sys, "argv", [arg.replace("$RUNNER_TEMP", ".") for arg in argv[1:]])
    assert builder.main() == 0
    output = tmp_path / "catalog-rebuildable-store-index-v1.json"
    index = CatalogRebuildableStoreIndexV1.model_validate_json(output.read_text())
    assert {row.cache_key for row in index.candidates} == expected_keys


def test_real_workflow_cache_inventory_is_stable_when_access_time_changes_between_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seal, runtime, components, _, expected_keys = _fixture(tmp_path)
    created_origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    access_origin = datetime(2026, 9, 13, 23, 59, tzinfo=timezone.utc)
    mutated_access = (access_origin + timedelta(minutes=1)).isoformat().replace(
        "+00:00", "Z"
    )
    live_keys = sorted(expected_keys)
    rows = []
    for cache_id in range(1, 208):
        rows.append(
            {
                "id": cache_id,
                "key": (
                    live_keys[cache_id - 1]
                    if cache_id <= len(live_keys)
                    else f"unrelated-cache-{cache_id}"
                ),
                "ref": "refs/heads/main",
                "version": "v1",
                "size_in_bytes": 100,
                "created_at": (created_origin + timedelta(minutes=cache_id))
                .isoformat()
                .replace("+00:00", "Z"),
                "last_accessed_at": (access_origin - timedelta(minutes=cache_id))
                .isoformat()
                .replace("+00:00", "Z"),
            }
        )

    def pages_before_and_after(before_rows, after_rows):
        return [
            {
                "total_count": len(rows),
                "actions_caches": before_rows[:100],
            },
            {
                "total_count": len(rows),
                "actions_caches": after_rows[100:200],
            },
            {
                "total_count": len(rows),
                "actions_caches": after_rows[200:300],
            }
        ]

    mutated_rows = [dict(row) for row in rows]
    mutated_rows[200]["last_accessed_at"] = mutated_access

    # GitHub's default ordering is last_accessed_at DESC. The initial dataset
    # is rows 1..207 in that order. After page 1, row 201 moves to the front;
    # recomputing page 2 then starts at row 100 (a duplicate), while row 201 is
    # absent from the later pages. The validator must reject that inventory.
    access_before = sorted(
        rows, key=lambda row: str(row["last_accessed_at"]), reverse=True
    )
    access_after = sorted(
        mutated_rows, key=lambda row: str(row["last_accessed_at"]), reverse=True
    )
    unstable_pages = pages_before_and_after(access_before, access_after)
    assert access_before[:100][-1]["id"] == 100
    assert access_after[0]["id"] == 201
    assert access_after[100]["id"] == 100
    assert 201 not in [row["id"] for row in access_after[100:]]
    _write_json(tmp_path / "unstable-pages.json", unstable_pages)

    # Sorting by immutable creation time keeps all three page memberships
    # unchanged even though row 201's access time changes between pages.
    created_before = sorted(rows, key=lambda row: str(row["created_at"]))
    created_after = sorted(mutated_rows, key=lambda row: str(row["created_at"]))
    stable_pages = pages_before_and_after(created_before, created_after)
    assert [row["id"] for row in created_before] == [
        row["id"] for row in created_after
    ]
    _write_json(tmp_path / "stable-pages.json", stable_pages)

    steps = _workflow_steps()
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    if bash is None or not Path(bash).is_file():
        pytest.skip("Bash required for the actual workflow capture script")
    _set_builder_context(monkeypatch)
    monkeypatch.setenv("RUNNER_TEMP", ".")
    capture = subprocess.run(
        [
            bash,
            "-c",
            """gh() {
  local url="${4:-}"
  printf '%s\\n' "$url" >> gh-requests.log
  if [[ "$url" == *"sort=created_at"* && "$url" == *"direction=asc"* ]]; then
    cat stable-pages.json
  else
    cat unstable-pages.json
  fi
}
"""
            + steps["cache_inventory"]["run"],
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert capture.returncode == 0, capture.stderr
    requests = (tmp_path / "gh-requests.log").read_text(encoding="utf-8").splitlines()
    assert len(requests) == 2
    assert all(
        "actions/caches?ref=refs/heads/main&per_page=100" in request
        for request in requests
    )

    (tmp_path / "runtime-prepared-seal").mkdir()
    seal.rename(tmp_path / "runtime-prepared-seal/runtime-prepared-seal.json")
    runtime.rename(tmp_path / "runtime-transport")
    components.rename(tmp_path / "component-transports")
    monkeypatch.chdir(tmp_path)
    argv = shlex.split(steps["store_index"]["run"])
    monkeypatch.setattr(sys, "argv", [arg.replace("$RUNNER_TEMP", ".") for arg in argv[1:]])
    assert builder.main() == 0
    output = tmp_path / "catalog-rebuildable-store-index-v1.json"
    index = CatalogRebuildableStoreIndexV1.model_validate_json(output.read_text())
    assert {row.cache_key for row in index.candidates} == expected_keys


@pytest.mark.parametrize("changed", [{"id": 999}, {"version": "v2"}, {"size_in_bytes": 101}, {"ref": "refs/heads/other"}, None])
def test_changed_or_removed_cache_is_not_published_as_reusable(tmp_path, monkeypatch, changed):
    seal, runtime, components, caches, live_keys = _fixture(tmp_path)
    second = json.loads(caches.read_text())
    changed_key = second[0]["actions_caches"][0]["key"]
    if changed is None:
        second[0]["actions_caches"].pop(0)
        second[0]["total_count"] -= 1
    else:
        second[0]["actions_caches"][0].update(changed)
    confirmation = tmp_path / "confirmation.json"
    _write_json(confirmation, second)
    _set_builder_context(monkeypatch)
    index = builder.build_index(runtime_prepared_seal=seal, runtime_root=runtime, component_root=components, cache_inventory=caches, cache_inventory_confirmation=confirmation)
    assert {row.cache_key for row in index.candidates} == live_keys - {changed_key}
    from scripts.finalize_catalog_preparation import required_prepared_cache_keys
    receipt = {
        "runtime_cache_key": next(key for key in live_keys if RUNTIME_IDENTITY in key),
        "prepared_input_cache_keys": (("runtime-fragment-core", next(key for key in live_keys if PREPARED_IDENTITY in key)),),
    }
    with pytest.raises(ValueError, match="CATALOG_PREPARATION_CACHE_COVERAGE_INVALID"):
        required_prepared_cache_keys(index, receipt)


@pytest.mark.parametrize("invalid_first", [False, True])
@pytest.mark.parametrize("mutation", ["truncated", "duplicate_id", "duplicate_key", "missing_version"])
def test_index_rejects_incomplete_or_ambiguous_confirmation(tmp_path, monkeypatch, mutation, invalid_first):
    seal, runtime, components, caches, _ = _fixture(tmp_path)
    second = json.loads(caches.read_text())
    rows = second[0]["actions_caches"]
    if mutation == "truncated":
        rows.pop()
    elif mutation == "duplicate_id":
        rows[1]["id"] = rows[0]["id"]
    elif mutation == "duplicate_key":
        rows[1]["key"] = rows[0]["key"]
    else:
        rows[0].pop("version")
    confirmation = tmp_path / "confirmation.json"
    _write_json(confirmation, second)
    if invalid_first:
        caches, confirmation = confirmation, caches
    _set_builder_context(monkeypatch)
    with pytest.raises(ValueError, match="CATALOG_STORE_INDEX_CACHE"):
        builder.build_index(runtime_prepared_seal=seal, runtime_root=runtime, component_root=components, cache_inventory=caches, cache_inventory_confirmation=confirmation)


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
        cache_inventory_confirmation=caches,
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
    payload[0]["total_count"] = 1
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
        cache_inventory_confirmation=caches,
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

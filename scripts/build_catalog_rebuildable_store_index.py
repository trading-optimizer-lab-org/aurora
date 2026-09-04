#!/usr/bin/env python3
"""Build one immutable index for exact catalog caches verified in this run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256  # noqa: E402
from aurora.infra.sp500_megarun.catalog_github_snapshot import (  # noqa: E402
    CatalogGitHubReadOnlyClient,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store import (  # noqa: E402
    RebuildableStoreCandidateV1,
)
from aurora.infra.sp500_megarun.catalog_rebuildable_store_index import (  # noqa: E402
    CatalogRebuildableStoreIndexV1,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Index exact verified catalog caches from one protected run."
    )
    parser.add_argument("--runtime-prepared-seal", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--component-root", type=Path, required=True)
    parser.add_argument("--cache-inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_STORE_INDEX_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _strict_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_STORE_INDEX_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _tree_rows(root: Path) -> tuple[dict[str, object], ...]:
    resolved = root.resolve(strict=True)
    if root.is_symlink() or not resolved.is_dir():
        raise ValueError("CATALOG_STORE_INDEX_TREE_INVALID")
    rows: list[dict[str, object]] = []
    for path in sorted(
        resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix()
    ):
        if path.is_symlink():
            raise ValueError("CATALOG_STORE_INDEX_TREE_SYMLINK_FORBIDDEN")
        if not path.is_file():
            continue
        rows.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    if not rows:
        raise ValueError("CATALOG_STORE_INDEX_TREE_EMPTY")
    return tuple(rows)


def _candidate_file_hashes(
    rows: tuple[dict[str, object], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple((str(row["path"]), str(row["sha256"])) for row in rows)


def _live_main_cache_keys(payload: object) -> frozenset[str]:
    pages = payload if isinstance(payload, list) else [payload]
    rows: list[Mapping[str, Any]] = []
    for page in pages:
        if isinstance(page, Mapping):
            raw_rows = page.get("actions_caches")
        elif isinstance(page, list):
            raw_rows = page
        else:
            raw_rows = None
        if not isinstance(raw_rows, list):
            raise ValueError("CATALOG_STORE_INDEX_CACHE_INVENTORY_INVALID")
        rows.extend(
            _mapping(row, "CATALOG_STORE_INDEX_CACHE_INVENTORY_INVALID")
            for row in raw_rows
        )
    ids = tuple(row.get("id") for row in rows)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in ids):
        raise ValueError("CATALOG_STORE_INDEX_CACHE_INVENTORY_INVALID")
    if len(ids) != len(set(ids)):
        raise ValueError("CATALOG_STORE_INDEX_CACHE_INVENTORY_DUPLICATE")
    keys = tuple(
        str(row.get("key"))
        for row in rows
        if row.get("ref") == "refs/heads/main"
    )
    if any(not key or key == "None" for key in keys) or len(keys) != len(set(keys)):
        raise ValueError("CATALOG_STORE_INDEX_CACHE_KEY_INVALID")
    return frozenset(keys)


def _verify_seal(path: Path) -> Mapping[str, Any]:
    seal = _mapping(_strict_json(path), "CATALOG_STORE_INDEX_SEAL_INVALID")
    identity = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        not _SHA256.fullmatch(str(seal.get("seal_sha256", "")))
        or canonical_sha256(identity) != seal.get("seal_sha256")
        or seal.get("validation_opened") is not False
        or seal.get("locked_opened") is not False
    ):
        raise ValueError("CATALOG_STORE_INDEX_SEAL_INVALID")
    return seal


def _runtime_candidate(
    *,
    seal: Mapping[str, Any],
    runtime_root: Path,
    live_cache_keys: frozenset[str],
) -> RebuildableStoreCandidateV1 | None:
    manifest_path = runtime_root / "runtime_manifest.json"
    manifest = _mapping(
        _strict_json(manifest_path), "CATALOG_STORE_INDEX_RUNTIME_INVALID"
    )
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    identity = str(manifest.get("runtime_identity_sha256", ""))
    if (
        not _SHA256.fullmatch(identity)
        or manifest_sha != seal.get("runtime_manifest_sha256")
        or identity != seal.get("runtime_identity_sha256")
    ):
        raise ValueError("CATALOG_STORE_INDEX_RUNTIME_INVALID")
    cache_key = f"aurora-catalog-v1-{identity}-{manifest_sha}-main"
    if cache_key not in live_cache_keys:
        return None
    rows = _tree_rows(runtime_root)
    return RebuildableStoreCandidateV1(
        object_family="runtime",
        logical_id="runtime",
        identity_sha256=identity,
        content_manifest_sha256=manifest_sha,
        content_sha256=canonical_sha256(rows),
        storage_kind="actions_cache",
        status="verified",
        source_branch="main",
        cache_key=cache_key,
        file_hashes=_candidate_file_hashes(rows),
        manifest_verified=True,
        content_verified=True,
        scope_verified=True,
    )


def _prepared_candidates(
    *,
    seal: Mapping[str, Any],
    live_cache_keys: frozenset[str],
) -> tuple[RebuildableStoreCandidateV1, ...]:
    identity = str(seal.get("prepared_input_identity_sha256", ""))
    partitions = seal.get("partitions")
    if not _SHA256.fullmatch(identity) or not isinstance(partitions, list):
        raise ValueError("CATALOG_STORE_INDEX_PREPARED_INVALID")
    candidates: list[RebuildableStoreCandidateV1] = []
    logical_ids: list[str] = []
    for raw in partitions:
        row = _mapping(raw, "CATALOG_STORE_INDEX_PREPARED_INVALID")
        logical_id = str(row.get("logical_id", ""))
        cache_key = str(row.get("cache_key", ""))
        manifest_sha = str(row.get("manifest_sha256", ""))
        files = row.get("files")
        if (
            not logical_id
            or not _SHA256.fullmatch(manifest_sha)
            or cache_key != f"aurora-catalog-v1-{identity}-{manifest_sha}-main"
            or not isinstance(files, list)
            or not files
        ):
            raise ValueError("CATALOG_STORE_INDEX_PREPARED_INVALID")
        normalized = tuple(
            {
                "path": str(_mapping(item, "CATALOG_STORE_INDEX_PREPARED_INVALID").get("path", "")),
                "sha256": str(_mapping(item, "CATALOG_STORE_INDEX_PREPARED_INVALID").get("sha256", "")),
                "size_bytes": _mapping(item, "CATALOG_STORE_INDEX_PREPARED_INVALID").get("size_bytes"),
            }
            for item in files
        )
        if (
            tuple(item["path"] for item in normalized)
            != tuple(sorted(set(str(item["path"]) for item in normalized)))
            or any(
                not item["path"]
                or not _SHA256.fullmatch(str(item["sha256"]))
                or isinstance(item["size_bytes"], bool)
                or not isinstance(item["size_bytes"], int)
                or int(item["size_bytes"]) < 0
                for item in normalized
            )
            or hashlib.sha256(_canonical_bytes(normalized)).hexdigest()
            != manifest_sha
        ):
            raise ValueError("CATALOG_STORE_INDEX_PREPARED_INVALID")
        logical_ids.append(logical_id)
        if cache_key not in live_cache_keys:
            continue
        candidates.append(
            RebuildableStoreCandidateV1(
                object_family="prepared_input",
                logical_id=logical_id,
                identity_sha256=identity,
                content_manifest_sha256=manifest_sha,
                content_sha256=canonical_sha256(normalized),
                storage_kind="actions_cache",
                status="verified",
                source_branch="main",
                cache_key=cache_key,
                file_hashes=_candidate_file_hashes(normalized),
                manifest_verified=True,
                content_verified=True,
                scope_verified=True,
            )
        )
    if logical_ids != sorted(set(logical_ids)):
        raise ValueError("CATALOG_STORE_INDEX_PREPARED_INVALID")
    return tuple(candidates)


def _component_candidates(
    *,
    component_root: Path,
    live_cache_keys: frozenset[str],
) -> tuple[RebuildableStoreCandidateV1, ...]:
    root = component_root.resolve(strict=True)
    wrappers = sorted(root.rglob("component_bundle_manifest.json"))
    if not wrappers:
        raise ValueError("CATALOG_STORE_INDEX_COMPONENTS_MISSING")
    candidates: list[RebuildableStoreCandidateV1] = []
    for wrapper_path in wrappers:
        wrapper = _mapping(
            _strict_json(wrapper_path), "CATALOG_STORE_INDEX_COMPONENT_INVALID"
        )
        wrapper_identity = {
            key: value for key, value in wrapper.items() if key != "manifest_sha256"
        }
        bundle_identity = str(wrapper.get("bundle_identity_sha256", ""))
        manifest_sha = str(wrapper.get("manifest_sha256", ""))
        components = wrapper.get("components")
        if (
            not _SHA256.fullmatch(bundle_identity)
            or not _SHA256.fullmatch(manifest_sha)
            or canonical_sha256(wrapper_identity) != manifest_sha
            or not isinstance(components, list)
            or not components
        ):
            raise ValueError("CATALOG_STORE_INDEX_COMPONENT_INVALID")
        bindings = tuple(
            (
                str(_mapping(row, "CATALOG_STORE_INDEX_COMPONENT_INVALID").get("component_id", "")),
                str(_mapping(row, "CATALOG_STORE_INDEX_COMPONENT_INVALID").get("component_id", "")),
            )
            for row in components
        )
        content_bindings = tuple(
            (
                str(_mapping(row, "CATALOG_STORE_INDEX_COMPONENT_INVALID").get("component_id", "")),
                str(_mapping(row, "CATALOG_STORE_INDEX_COMPONENT_INVALID").get("result_sha256", "")),
            )
            for row in components
        )
        if (
            bindings != tuple(sorted(set(bindings)))
            or any(not _SHA256.fullmatch(item[0]) for item in bindings)
            or content_bindings != tuple(sorted(set(content_bindings)))
            or tuple(item[0] for item in content_bindings)
            != tuple(item[0] for item in bindings)
            or any(not _SHA256.fullmatch(item[1]) for item in content_bindings)
        ):
            raise ValueError("CATALOG_STORE_INDEX_COMPONENT_INVALID")
        cache_key = (
            f"aurora-catalog-v1-{bundle_identity}-{manifest_sha}-main"
        )
        if cache_key not in live_cache_keys:
            continue
        rows = _tree_rows(wrapper_path.parent)
        candidates.append(
            RebuildableStoreCandidateV1(
                object_family="component",
                logical_id=bundle_identity,
                identity_sha256=bundle_identity,
                content_manifest_sha256=manifest_sha,
                content_sha256=canonical_sha256(rows),
                storage_kind="actions_cache",
                status="verified",
                source_branch="main",
                contained_logical_ids=tuple(item[0] for item in bindings),
                logical_identity_bindings=bindings,
                logical_content_bindings=content_bindings,
                cache_key=cache_key,
                file_hashes=_candidate_file_hashes(rows),
                manifest_verified=True,
                content_verified=True,
                scope_verified=True,
            )
        )
    return tuple(candidates)


def build_index(
    *,
    runtime_prepared_seal: Path,
    runtime_root: Path,
    component_root: Path,
    cache_inventory: Path,
) -> CatalogRebuildableStoreIndexV1:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if (
        not _REPOSITORY.fullmatch(repository)
        or not run_id.isdigit()
        or not run_attempt.isdigit()
    ):
        raise ValueError("CATALOG_STORE_INDEX_INVOCATION_INVALID")
    client = CatalogGitHubReadOnlyClient(repository, token)
    run_raw, _ = client.get_json(f"/repos/{repository}/actions/runs/{run_id}")
    run = _mapping(run_raw, "CATALOG_STORE_INDEX_RUN_INVALID")
    if (
        run.get("id") != int(run_id)
        or run.get("run_attempt") != int(run_attempt)
        or run.get("head_branch") != "main"
        or not _COMMIT.fullmatch(str(run.get("head_sha", "")))
    ):
        raise ValueError("CATALOG_STORE_INDEX_RUN_INVALID")

    seal = _verify_seal(runtime_prepared_seal)
    expected_bindings = {
        "authority_id": os.environ.get("CATALOG_AUTHORITY_ID", ""),
        "campaign_id": os.environ.get("CATALOG_CAMPAIGN_ID", ""),
        "science_sha256": os.environ.get("CATALOG_SCIENCE_SHA256", ""),
        "execution_plan_sha256": os.environ.get(
            "CATALOG_EXECUTION_PLAN_SHA256", ""
        ),
        "execution_protocol_sha256": os.environ.get(
            "CATALOG_EXECUTION_PROTOCOL_SHA256", ""
        ),
        "protected_commit_sha": str(run["head_sha"]),
    }
    if any(str(seal.get(key, "")) != value for key, value in expected_bindings.items()):
        raise ValueError("CATALOG_STORE_INDEX_SEAL_BINDING_INVALID")

    live_keys = _live_main_cache_keys(_strict_json(cache_inventory))
    candidates = tuple(
        item
        for item in (
            _runtime_candidate(
                seal=seal,
                runtime_root=runtime_root,
                live_cache_keys=live_keys,
            ),
            *_prepared_candidates(seal=seal, live_cache_keys=live_keys),
            *_component_candidates(
                component_root=component_root,
                live_cache_keys=live_keys,
            ),
        )
        if item is not None
    )
    if not candidates:
        raise ValueError("CATALOG_STORE_INDEX_NO_LIVE_VERIFIED_CACHE")
    return CatalogRebuildableStoreIndexV1.create(
        artifact_name="catalog-rebuildable-store-index-v1",
        repository=repository,
        writer_workflow=".github/workflows/catalog-optimized-run.yml",
        writer_run_id=int(run_id),
        writer_run_attempt=int(run_attempt),
        protected_commit_sha=str(run["head_sha"]),
        source_branch="main",
        authority_id=expected_bindings["authority_id"],
        campaign_id=expected_bindings["campaign_id"],
        science_sha256=expected_bindings["science_sha256"],
        execution_plan_sha256=expected_bindings["execution_plan_sha256"],
        execution_protocol_sha256=expected_bindings["execution_protocol_sha256"],
        candidates=candidates,
    )


def main() -> int:
    args = _parser().parse_args()
    index = build_index(
        runtime_prepared_seal=args.runtime_prepared_seal,
        runtime_root=args.runtime_root,
        component_root=args.component_root,
        cache_inventory=args.cache_inventory,
    )
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("CATALOG_STORE_INDEX_OUTPUT_EXISTS")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        _canonical_bytes(index.model_dump(mode="json")) + b"\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Content-bound campaign bundles used by the short catalog launch path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .catalog_fast_path import (
    CatalogPreparedReceiptV1,
    CatalogPreparationIdentityV1,
)
from .catalog_request_contract import FrozenModel, Sha256


SafeRelativePath = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512),
]
MANIFEST_NAME = "prepared-bundle-manifest.json"
RECEIPT_NAME = "prepared-receipt.json"


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _strict_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("CATALOG_PREPARED_BUNDLE_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_PREPARED_BUNDLE_NONFINITE_JSON:{value}")
        ),
    )


class CatalogPreparedBundleFileV1(FrozenModel):
    path: SafeRelativePath
    sha256: Sha256
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _path_is_safe(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "." in path.parts
            or path.as_posix() != value
            or value == MANIFEST_NAME
        ):
            raise ValueError("CATALOG_PREPARED_BUNDLE_PATH_INVALID")
        return value


class CatalogPreparedBundleManifestV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    document_type: Literal["catalog_prepared_bundle_v1"] = (
        "catalog_prepared_bundle_v1"
    )
    preparation_key_sha256: Sha256
    prepared_receipt_sha256: Sha256
    files: tuple[CatalogPreparedBundleFileV1, ...]
    manifest_sha256: Sha256

    @field_validator("files")
    @classmethod
    def _files_are_complete_and_canonical(
        cls,
        value: tuple[CatalogPreparedBundleFileV1, ...],
    ) -> tuple[CatalogPreparedBundleFileV1, ...]:
        paths = tuple(item.path for item in value)
        if not value or paths != tuple(sorted(set(paths))) or RECEIPT_NAME not in paths:
            raise ValueError("CATALOG_PREPARED_BUNDLE_FILE_LIST_INVALID")
        return value

    @model_validator(mode="after")
    def _manifest_hash_is_exact(self) -> "CatalogPreparedBundleManifestV1":
        identity = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != _canonical_sha256(identity):
            raise ValueError("CATALOG_PREPARED_BUNDLE_MANIFEST_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogPreparedBundleManifestV1":
        raw_files = values.get("files")
        if not isinstance(raw_files, tuple | list):
            raise ValueError("CATALOG_PREPARED_BUNDLE_FILE_LIST_INVALID")
        files = tuple(
            sorted(
                (
                    item
                    if isinstance(item, CatalogPreparedBundleFileV1)
                    else CatalogPreparedBundleFileV1.model_validate(item)
                    for item in raw_files
                ),
                key=lambda item: item.path,
            )
        )
        identity = {
            "schema_version": "1",
            "document_type": "catalog_prepared_bundle_v1",
            **values,
            "files": [item.model_dump(mode="json") for item in files],
        }
        identity.pop("manifest_sha256", None)
        return cls.model_validate(
            {**identity, "manifest_sha256": _canonical_sha256(identity)}
        )


def _bundle_files(root: Path) -> tuple[CatalogPreparedBundleFileV1, ...]:
    files: list[CatalogPreparedBundleFileV1] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise ValueError("CATALOG_PREPARED_BUNDLE_SYMLINK_FORBIDDEN")
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        relative = path.relative_to(root).as_posix()
        files.append(
            CatalogPreparedBundleFileV1(
                path=relative,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                size_bytes=path.stat().st_size,
            )
        )
    return tuple(files)


def write_prepared_catalog_bundle_manifest(
    *,
    bundle_dir: Path,
    prepared_receipt: CatalogPreparedReceiptV1,
) -> CatalogPreparedBundleManifestV1:
    """Seal an already-built directory without changing any material file."""

    root = Path(bundle_dir).resolve(strict=True)
    if Path(bundle_dir).is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_PREPARED_BUNDLE_PATH_INVALID")
    receipt_path = root / RECEIPT_NAME
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("CATALOG_PREPARED_BUNDLE_RECEIPT_MISSING")
    parsed_receipt = CatalogPreparedReceiptV1.model_validate(_strict_json(receipt_path))
    if parsed_receipt != prepared_receipt:
        raise ValueError("CATALOG_PREPARED_BUNDLE_RECEIPT_MISMATCH")
    manifest = CatalogPreparedBundleManifestV1.create(
        preparation_key_sha256=prepared_receipt.identity.preparation_key_sha256,
        prepared_receipt_sha256=prepared_receipt.receipt_sha256,
        files=_bundle_files(root),
    )
    target = root / MANIFEST_NAME
    if target.exists() or target.is_symlink():
        raise ValueError("CATALOG_PREPARED_BUNDLE_MANIFEST_ALREADY_EXISTS")
    target.write_text(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_prepared_catalog_bundle(
    *,
    bundle_dir: Path,
    expected_identity: CatalogPreparationIdentityV1,
) -> tuple[CatalogPreparedReceiptV1, CatalogPreparedBundleManifestV1]:
    """Verify exact files and reject any stale or partially restored bundle."""

    root = Path(bundle_dir).resolve(strict=True)
    if Path(bundle_dir).is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_PREPARED_BUNDLE_PATH_INVALID")
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("CATALOG_PREPARED_BUNDLE_MANIFEST_MISSING")
    manifest = CatalogPreparedBundleManifestV1.model_validate(
        _strict_json(manifest_path)
    )
    actual_files = _bundle_files(root)
    if actual_files != manifest.files:
        raise ValueError("CATALOG_PREPARED_BUNDLE_CONTENT_INVALID")
    receipt = CatalogPreparedReceiptV1.model_validate(
        _strict_json(root / RECEIPT_NAME)
    )
    if (
        receipt.identity != expected_identity
        or manifest.preparation_key_sha256 != expected_identity.preparation_key_sha256
        or manifest.prepared_receipt_sha256 != receipt.receipt_sha256
    ):
        raise ValueError("CATALOG_PREPARED_BUNDLE_STALE")
    return receipt, manifest


def materialize_prepared_catalog_plan(
    *,
    bundle_dir: Path,
    expected_identity: CatalogPreparationIdentityV1,
    request_sha256: str,
    decision_sha256: str,
    output_dir: Path,
) -> dict[str, object]:
    """Copy one verified template and bind only its small controller envelope."""

    from .catalog_sealed_plan import (
        verify_sealed_global_reuse_execution_plan,
    )

    receipt, _manifest = verify_prepared_catalog_bundle(
        bundle_dir=bundle_dir,
        expected_identity=expected_identity,
    )
    template = (
        Path(bundle_dir).resolve(strict=True)
        / f"templates/workers-{receipt.qualified_worker_ceiling:03d}"
    )
    if not template.is_dir() or template.is_symlink():
        raise ValueError("CATALOG_PREPARED_TEMPLATE_MISSING")
    original = verify_sealed_global_reuse_execution_plan(template)
    if (
        original.get("science_sha256") != expected_identity.scientific_contract_sha256
        or original.get("protected_commit_sha") != expected_identity.protected_commit_sha
    ):
        raise ValueError("CATALOG_PREPARED_TEMPLATE_IDENTITY_MISMATCH")
    if (
        original.get("global_reuse_plan_sha256")
        != receipt.execution_plan_template_sha256
    ):
        raise ValueError("CATALOG_PREPARED_TEMPLATE_MISMATCH")
    target = Path(output_dir).resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("CATALOG_FAST_PLAN_OUTPUT_EXISTS")
    shutil.copytree(template, target)

    controller_path = target / "controller_binding.json"
    controller = _strict_json(controller_path)
    if not isinstance(controller, dict) or not isinstance(
        controller.get("binding"), dict
    ):
        raise ValueError("CATALOG_FAST_CONTROLLER_BINDING_INVALID")
    controller["binding"] = {
        **controller["binding"],
        "request_sha256": request_sha256,
        "decision_sha256": decision_sha256,
        "prepared_receipt_sha256": receipt.receipt_sha256,
    }
    controller_identity = {
        key: value for key, value in controller.items() if key != "content_sha256"
    }
    controller["content_sha256"] = _canonical_sha256(controller_identity)
    controller_raw = (
        json.dumps(controller, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    controller_path.write_bytes(controller_raw)

    plan_receipt_path = target / "execution_plan_receipt.json"
    plan_receipt = _strict_json(plan_receipt_path)
    if not isinstance(plan_receipt, dict) or not isinstance(
        plan_receipt.get("content_manifest"), list
    ):
        raise ValueError("CATALOG_FAST_PLAN_RECEIPT_INVALID")
    matching_rows = [
        row
        for row in plan_receipt["content_manifest"]
        if isinstance(row, dict) and row.get("path") == "controller_binding.json"
    ]
    if len(matching_rows) != 1:
        raise ValueError("CATALOG_FAST_PLAN_RECEIPT_INVALID")
    matching_rows[0].update(
        {
            "sha256": hashlib.sha256(controller_raw).hexdigest(),
            "size_bytes": len(controller_raw),
        }
    )
    plan_receipt.update(
        {
            "request_sha256": request_sha256,
            "decision_sha256": decision_sha256,
            "content_manifest_sha256": _canonical_sha256(
                plan_receipt["content_manifest"]
            ),
        }
    )
    plan_identity = {
        key: value for key, value in plan_receipt.items() if key != "receipt_sha256"
    }
    plan_receipt["receipt_sha256"] = _canonical_sha256(plan_identity)
    plan_receipt_path.write_text(
        json.dumps(plan_receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return verify_sealed_global_reuse_execution_plan(
        target,
        expected_bindings={
            "request_sha256": request_sha256,
            "decision_sha256": decision_sha256,
        },
    )


__all__ = [
    "CatalogPreparedBundleFileV1",
    "CatalogPreparedBundleManifestV1",
    "materialize_prepared_catalog_plan",
    "verify_prepared_catalog_bundle",
    "write_prepared_catalog_bundle_manifest",
]

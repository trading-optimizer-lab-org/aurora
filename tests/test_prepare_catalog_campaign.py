from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from scripts.prepare_catalog_campaign import (
    PREPARED_PARTITIONS,
    _canonical_bytes,
    _document,
    _payload_artifact_matrix,
)


def test_prepared_partition_ids_are_unique_and_canonically_ordered() -> None:
    assert PREPARED_PARTITIONS == tuple(sorted(set(PREPARED_PARTITIONS)))
    assert PREPARED_PARTITIONS == (
        "runtime-fragment-D_CBOE_PCR",
        "runtime-fragment-D_CFTC",
        "runtime-fragment-D_CFTC_LEGACY",
        "runtime-fragment-D_FED_H15_H10",
        "runtime-fragment-D_FED_H3_H6_H8_G19_CP",
        "runtime-fragment-D_FRENCH_US",
        "runtime-fragment-D_MACRO_PIT",
        "runtime-fragment-D_Z1",
        "runtime-fragment-core",
    )


def test_canonical_documents_serialize_nested_validated_models() -> None:
    class NestedModel(BaseModel):
        value: int

    payload = {"items": (NestedModel(value=7),)}
    document = _document("test_document_v1", payload)

    assert json.loads(_canonical_bytes(payload)) == {"items": [{"value": 7}]}
    assert document["payload"] == {"items": [{"value": 7}]}


def test_payload_artifact_matrix_names_every_materialized_bundle(
    tmp_path: Path,
) -> None:
    payload_root = tmp_path / "sealed-plan" / "payload_artifacts"
    for name in ("catalog-descriptors-bundle-b", "catalog-descriptors-bundle-a"):
        member = payload_root / name / "component" / "worker-000.json"
        member.parent.mkdir(parents=True)
        member.write_text("{}\n", encoding="utf-8")

    matrix = json.loads(_payload_artifact_matrix(tmp_path / "sealed-plan"))

    assert matrix == {
        "artifact": [
            "catalog-descriptors-bundle-a",
            "catalog-descriptors-bundle-b",
        ]
    }

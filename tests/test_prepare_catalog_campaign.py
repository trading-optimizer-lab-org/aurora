from __future__ import annotations

import json

from pydantic import BaseModel

from scripts.prepare_catalog_campaign import (
    PREPARED_PARTITIONS,
    _canonical_bytes,
    _document,
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

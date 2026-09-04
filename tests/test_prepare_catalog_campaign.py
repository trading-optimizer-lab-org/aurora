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


def test_canonical_documents_serialize_nested_validated_models() -> None:
    class NestedModel(BaseModel):
        value: int

    payload = {"items": (NestedModel(value=7),)}
    document = _document("test_document_v1", payload)

    assert json.loads(_canonical_bytes(payload)) == {"items": [{"value": 7}]}
    assert document["payload"] == {"items": [{"value": 7}]}

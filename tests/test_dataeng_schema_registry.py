"""Tests for quantforge.dataeng.schema_registry."""
from __future__ import annotations

import pytest

from aurora.dataeng.schema_registry import (
    SchemaRegistry,
    SchemaRegistryConfig,
)


@pytest.fixture
def registry() -> SchemaRegistry:
    return SchemaRegistry(SchemaRegistryConfig(db_path=":memory:",
                                               format="jsonschema"))


def test_register_assigns_version_one(registry: SchemaRegistry):
    sv = registry.register("trades", {"type": "object",
                                      "properties": {"id": {"type": "integer"}}})
    assert sv.version == 1
    assert sv.subject == "trades"
    assert sv.format == "jsonschema"


def test_register_increments_version(registry: SchemaRegistry):
    registry.register("trades", {"type": "object", "v": 1})
    sv2 = registry.register("trades", {"type": "object", "v": 2})
    assert sv2.version == 2


def test_latest_returns_highest(registry: SchemaRegistry):
    registry.register("orders", {"type": "object", "v": 1})
    registry.register("orders", {"type": "object", "v": 2})
    registry.register("orders", {"type": "object", "v": 3})
    assert registry.latest("orders").version == 3


def test_get_specific_version(registry: SchemaRegistry):
    registry.register("orders", {"v": 1})
    registry.register("orders", {"v": 2})
    sv = registry.get("orders", version=1)
    assert sv is not None and sv.schema == {"v": 1}


def test_unknown_subject_returns_none(registry: SchemaRegistry):
    assert registry.latest("missing") is None
    assert registry.get("missing", 1) is None


def test_list_subjects_and_versions(registry: SchemaRegistry):
    registry.register("a", {"v": 1})
    registry.register("a", {"v": 2})
    registry.register("b", {"v": 1})
    assert registry.list_subjects() == ["a", "b"]
    assert registry.list_versions("a") == [1, 2]


def test_empty_schema_rejected(registry: SchemaRegistry):
    with pytest.raises(ValueError):
        registry.register("x", {})

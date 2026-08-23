from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from infra.sp500_megarun.catalog_bootstrap_contract import (
    github_manifest_payload,
    load_catalog_bootstrap_manifests,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/catalog_bootstrap_app_manifests_v1.json"
SCHEMA_PATH = ROOT / "schemas/catalog_bootstrap_app_manifests_v1.schema.json"

EXPECTED_AUDITOR_REPOSITORY_PERMISSIONS = {
    "actions": "read",
    "administration": "read",
    "contents": "read",
    "environments": "read",
    "issues": "read",
    "metadata": "read",
    "packages": "read",
    "variables": "read",
}
EXPECTED_AUDITOR_MANIFEST_PERMISSIONS = {
    "actions": "read",
    "administration": "read",
    "contents": "read",
    "environments": "read",
    "issues": "read",
    "metadata": "read",
    "packages": "read",
    "actions_variables": "read",
    "organization_administration": "read",
}


def _object_nodes(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, dict):
        if value.get("type") == "object":
            found.append(value)
        for child in value.values():
            found.extend(_object_nodes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_object_nodes(child))
    return found


def test_bootstrap_manifests_are_exact() -> None:
    value = load_catalog_bootstrap_manifests(MANIFEST_PATH)
    assert value.repository == "trading-optimizer-lab-org/aurora"
    assert value.organization == "trading-optimizer-lab-org"
    assert value.requester.name == "AURORA Catalog Requester f10c7b40e1"
    assert value.auditor.name == "AURORA Catalog Controls Auditor cf479d98fb"
    assert value.requester.manifest_permissions == {
        "metadata": "read",
        "issues": "write",
    }
    assert value.auditor.manifest_permissions == EXPECTED_AUDITOR_MANIFEST_PERMISSIONS
    assert (
        value.auditor.expected_repository_permissions
        == EXPECTED_AUDITOR_REPOSITORY_PERMISSIONS
    )
    assert value.auditor.expected_organization_permissions == {
        "administration": "read"
    }
    assert value.auditor.expected_enterprise_permissions == {}
    assert value.requester.webhook_active is False
    assert value.auditor.webhook_active is False
    assert value.requester.default_events == ()
    assert value.auditor.default_events == ()


def test_github_manifest_payload_is_closed_and_callback_bound() -> None:
    value = load_catalog_bootstrap_manifests(MANIFEST_PATH)
    callback = "http://127.0.0.1:43127/github/manifest/callback"
    payload = github_manifest_payload(value.auditor, redirect_url=callback)
    assert payload == {
        "name": "AURORA Catalog Controls Auditor cf479d98fb",
        "url": "https://github.com/trading-optimizer-lab-org/aurora",
        "description": "Read-only verifier for AURORA catalog controls.",
        "redirect_url": callback,
        "public": False,
        "default_events": [],
        "default_permissions": dict(sorted(EXPECTED_AUDITOR_MANIFEST_PERMISSIONS.items())),
        "request_oauth_on_install": False,
        "setup_on_update": False,
    }


def test_schema_is_closed_and_rejects_unknown_or_write_auditor_permission() -> None:
    document = json.loads(MANIFEST_PATH.read_text("utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(document, schema)
    assert all(node.get("additionalProperties") is False for node in _object_nodes(schema))

    extra = deepcopy(document)
    extra["auditor"]["unsafe"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(extra, schema)

    write = deepcopy(document)
    write["auditor"]["manifest_permissions"]["contents"] = "write"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(write, schema)


def test_python_validation_rejects_unknown_provider_permission() -> None:
    document = json.loads(MANIFEST_PATH.read_text("utf-8"))
    document["auditor"]["manifest_permissions"]["pull_requests"] = "read"
    with pytest.raises(ValueError, match="AUDITOR_MANIFEST_PERMISSIONS_INVALID"):
        load_catalog_bootstrap_manifests(document)

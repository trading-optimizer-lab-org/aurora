from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ARCHIVE = ROOT / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT_V5_3_ARCHIVE.md"
PROMPT = ROOT / "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md"
POLICY = ROOT / "config/catalog_run_prompt_policy_v1.json"
SCHEMA = ROOT / "schemas/catalog_run_prompt_policy_v1.schema.json"
MIGRATION = ROOT / "config/catalog_prompt_migration_v5_3_to_v6_0.json"
MIGRATION_SCHEMA = ROOT / "schemas/catalog_prompt_migration_v5_3_to_v6_0.schema.json"
EXPECTED_SOURCE_SHA256 = (
    "6be6180a40c82298c7e6eef6f531344d90979aea50364a2056d2ad3dab601a6b"
)
EXPECTED_RULE_IDS = tuple(f"CAT-{number:03d}" for number in range(1, 26))
DIRECT_MECHANICS = (
    "workflow_dispatch",
    "gh workflow run",
    "/dispatches",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "scripts/submit_catalog_run_request.py",
    "aurora.infra.sp500_megarun.catalog_requester_cli",
    "catalog-requester-broker.pyz",
    "--launch-ticket",
    'COMMIT_SHA: "<<<EDITAR',
    'DISPATCH_REF: "<<<EDITAR',
)


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _inside_root(relative_path: str) -> Path:
    resolved = (ROOT / relative_path).resolve()
    resolved.relative_to(ROOT.resolve())
    return resolved


def _validate_migration(migration: dict[str, Any]) -> None:
    jsonschema.validate(migration, _json(MIGRATION_SCHEMA))
    assert migration["source_prompt_sha256"] == EXPECTED_SOURCE_SHA256
    assert migration["active_prompt_sha256"] == hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    source_lines = SOURCE_ARCHIVE.read_bytes().splitlines(keepends=True)
    expected_start = 1
    for row in migration["spans"]:
        assert row["start_line"] == expected_start
        assert row["end_line"] >= row["start_line"]
        span = b"".join(source_lines[row["start_line"] - 1 : row["end_line"]])
        assert hashlib.sha256(span).hexdigest() == row["source_span_sha256"]
        assert set(row["machine_rule_ids"]) <= set(EXPECTED_RULE_IDS)
        assert row["active_prompt_section"] or row["machine_rule_ids"]
        if row["disposition"] == "replaced_incompatible":
            assert row["machine_rule_ids"]
            assert row["replacement_reason"]
        if row["disposition"] == "preserved_for_ai":
            decoded = span.decode("utf-8")
            assert not any(mechanic in decoded for mechanic in DIRECT_MECHANICS)
        expected_start = row["end_line"] + 1
    assert expected_start == len(source_lines) + 1


def _validate_policy(policy: dict[str, Any]) -> None:
    jsonschema.validate(policy, _json(SCHEMA))
    assert policy["source_prompt_sha256"] == EXPECTED_SOURCE_SHA256
    assert policy["active_prompt_sha256"] == hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    assert policy["source_prompt_version"] == "5.3"
    assert policy["active_prompt_version"] == "7.1-CHAT-ENTRY"
    assert policy["migration_path"] == MIGRATION.relative_to(ROOT).as_posix()
    assert policy["migration_sha256"] == hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert tuple(row["rule_id"] for row in policy["rules"]) == EXPECTED_RULE_IDS
    nodeids: set[str] = set()
    for row in policy["rules"]:
        inactive_markers = (
            "pend" + "ing",
            "tempor" + "ary",
            "x" + "fail",
            "s" + "kip",
        )
        mapping_text = " ".join(
            (row["enforcer_path"], row["test_nodeid"])
        ).casefold()
        assert not any(marker in mapping_text for marker in inactive_markers)
        enforcer = _inside_root(row["enforcer_path"])
        assert enforcer.is_file()
        assert row["failure_code"] in enforcer.read_text(encoding="utf-8")
        test_file, separator, test_name = row["test_nodeid"].partition("::")
        assert separator == "::"
        test_path = _inside_root(test_file)
        assert test_path.is_file()
        source = test_path.read_text(encoding="utf-8")
        assert f"def {test_name}(" in source
        function = next(
            (
                node
                for node in ast.parse(source).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == test_name
            ),
            None,
        )
        assert function is not None
        decorators = " ".join(ast.unparse(item) for item in function.decorator_list).casefold()
        assert not any(marker in decorators for marker in inactive_markers[-2:])
        assert row["test_nodeid"] not in nodeids
        nodeids.add(row["test_nodeid"])
        assert row["evidence_contract"]
        assert row["evidence_field"]


def test_source_prompt_archive_is_the_approved_exact_version() -> None:
    assert hashlib.sha256(SOURCE_ARCHIVE.read_bytes()).hexdigest() == EXPECTED_SOURCE_SHA256


def test_active_prompt_is_controller_only_and_hash_bound() -> None:
    text = PROMPT.read_text(encoding="utf-8")
    policy = _json(POLICY)
    assert "VERSIÓN: 7.1-CHAT-ENTRY" in text
    assert "C:/Python314/python.exe -I -S" in text
    assert "C:/ProgramData/AURORA/CatalogChatSender/submit_catalog_chat_intent.py" in text
    assert "solo necesita CAMPAIGN_KEY" in text
    assert "C:/ProgramData/AURORA/CatalogChatSender/catalog_campaign_registry_v1.json" in text
    assert "BLOCKED_CAMPAIGN_SELECTION_AMBIGUOUS" in text
    assert "BLOCKED_CHAT_ENTRY_NOT_INSTALLED" in text
    assert hashlib.sha256(PROMPT.read_bytes()).hexdigest() == policy["active_prompt_sha256"]
    for forbidden in DIRECT_MECHANICS:
        assert forbidden not in text


def test_migration_covers_every_source_line_exactly_once() -> None:
    _validate_migration(_json(MIGRATION))


def test_prompt_policy_is_closed_complete_and_points_to_real_tests() -> None:
    _validate_policy(_json(POLICY))


def test_agents_requires_the_catalog_runbook() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/runbooks/CATALOG_RUN_MASTER_PROMPT.md" in agents
    assert "CATALOG_RUN_MASTER_PROMPT_V5_3_ARCHIVE.md" not in agents
    assert "CATALOG_RUN_PROTOCOL_REQUIRED" in agents


def test_policy_validator_rejects_missing_extra_and_duplicate_ids() -> None:
    policy = _json(POLICY)
    missing = deepcopy(policy)
    missing["rules"].pop()
    with pytest.raises((AssertionError, jsonschema.ValidationError)):
        _validate_policy(missing)
    extra = deepcopy(policy)
    extra["rules"].append(deepcopy(extra["rules"][-1]))
    extra["rules"][-1]["rule_id"] = "CAT-026"
    with pytest.raises((AssertionError, jsonschema.ValidationError)):
        _validate_policy(extra)
    duplicate = deepcopy(policy)
    duplicate["rules"][-1]["rule_id"] = duplicate["rules"][-2]["rule_id"]
    with pytest.raises((AssertionError, jsonschema.ValidationError)):
        _validate_policy(duplicate)


def test_policy_validator_rejects_unsafe_or_missing_paths_and_tests() -> None:
    policy = _json(POLICY)
    unsafe = deepcopy(policy)
    unsafe["rules"][0]["enforcer_path"] = "../outside.py"
    with pytest.raises((AssertionError, ValueError, jsonschema.ValidationError)):
        _validate_policy(unsafe)
    missing = deepcopy(policy)
    missing["rules"][0]["enforcer_path"] = "infra/sp500_megarun/absent.py"
    with pytest.raises(AssertionError):
        _validate_policy(missing)
    absent_test = deepcopy(policy)
    absent_test["rules"][0]["test_nodeid"] = (
        "tests/test_catalog_run_prompt_policy.py::test_absent_policy_gate"
    )
    with pytest.raises(AssertionError):
        _validate_policy(absent_test)


def test_policy_validator_rejects_inactive_or_nonpassing_mappings() -> None:
    policy = _json(POLICY)
    for field, value in (
        (
            "enforcer_path",
            "infra/sp500_megarun/catalog_policy_" + "pend" + "ing.py",
        ),
        (
            "test_nodeid",
            "tests/test_catalog_controller_qualification.py::test_cat_001_"
            + "x"
            + "fail",
        ),
        (
            "test_nodeid",
            "tests/test_catalog_controller_qualification.py::test_cat_001_"
            + "s"
            + "kip",
        ),
    ):
        mutation = deepcopy(policy)
        mutation["rules"][0][field] = value
        with pytest.raises((AssertionError, jsonschema.ValidationError)):
            _validate_policy(mutation)


def test_migration_validator_rejects_gaps_overlap_reorder_and_hash_mismatch() -> None:
    migration = _json(MIGRATION)
    gap = deepcopy(migration)
    gap["spans"][1]["start_line"] += 1
    with pytest.raises(AssertionError):
        _validate_migration(gap)
    overlap = deepcopy(migration)
    overlap["spans"][1]["start_line"] -= 1
    with pytest.raises(AssertionError):
        _validate_migration(overlap)
    reordered = deepcopy(migration)
    reordered["spans"][0], reordered["spans"][1] = reordered["spans"][1], reordered["spans"][0]
    with pytest.raises(AssertionError):
        _validate_migration(reordered)
    bad_hash = deepcopy(migration)
    bad_hash["spans"][0]["source_span_sha256"] = "0" * 64
    with pytest.raises(AssertionError):
        _validate_migration(bad_hash)


def test_migration_validator_rejects_unknown_rules_and_preserved_direct_mechanics() -> None:
    migration = _json(MIGRATION)
    unknown = deepcopy(migration)
    unknown["spans"][0]["machine_rule_ids"] = ["CAT-999"]
    with pytest.raises((AssertionError, jsonschema.ValidationError)):
        _validate_migration(unknown)
    direct_index = next(
        index
        for index, row in enumerate(migration["spans"])
        if any(
            mechanic
            in b"".join(
                SOURCE_ARCHIVE.read_bytes().splitlines(keepends=True)[
                    row["start_line"] - 1 : row["end_line"]
                ]
            ).decode("utf-8")
            for mechanic in DIRECT_MECHANICS
        )
    )
    preserved = deepcopy(migration)
    preserved["spans"][direct_index]["disposition"] = "preserved_for_ai"
    with pytest.raises(AssertionError):
        _validate_migration(preserved)

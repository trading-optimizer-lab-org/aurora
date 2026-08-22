from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType
from typing import Literal

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/catalog_controller_qualification"
CAMPAIGN_FIXTURE = FIXTURE_ROOT / "campaign_v1.json"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest_v1.json"
SIMULATOR = FIXTURE_ROOT / "simulator.py"
FINAL_RESULT_SHA256 = "4491a203c6f027845f25e1fde210bb8ccd2d017cab7e6062509ace278dcd4af2"


@dataclass(frozen=True)
class ScenarioExpectation:
    outcome: str
    reason_code: str
    authority_record_count: int
    final_state: str
    component_execution_count: int
    unit_execution_count: int
    preserved_valid_work_count: int
    evidence_kind: Literal["none", "receipt", "final"]


E = ScenarioExpectation
SCENARIOS: dict[str, ScenarioExpectation] = {
    "Q-001": E("ADMITTED", "CATALOG_ADMITTED", 1, "RESERVED", 0, 0, 0, "none"),
    "Q-002": E("BLOCKED", "CATALOG_REQUEST_MALFORMED", 0, "NONE", 0, 0, 0, "none"),
    "Q-003": E("BLOCKED", "CATALOG_REQUEST_EXTRA_FIELD", 0, "NONE", 0, 0, 0, "none"),
    "Q-004": E("BLOCKED", "CATALOG_REQUEST_UNTRUSTED_SYNTAX", 0, "NONE", 0, 0, 0, "none"),
    "Q-005": E("BLOCKED", "CATALOG_REQUEST_ACTOR_NOT_ALLOWED", 0, "NONE", 0, 0, 0, "none"),
    "Q-006": E("BLOCKED", "CATALOG_REQUEST_SHA_MISMATCH", 0, "NONE", 0, 0, 0, "none"),
    "Q-007": E("BLOCKED", "CATALOG_PROMPT_HASH_MISMATCH", 0, "NONE", 0, 0, 0, "none"),
    "Q-008": E("BLOCKED", "CATALOG_COMMIT_NOT_PROTECTED_HEAD", 0, "NONE", 0, 0, 0, "none"),
    "Q-009": E("BLOCKED", "CATALOG_VALIDATION_MUST_REMAIN_CLOSED", 0, "NONE", 0, 0, 0, "none"),
    "Q-010": E("BLOCKED", "CATALOG_FREE_CAPACITY_REQUIRED", 0, "NONE", 0, 0, 0, "none"),
    "Q-011": E("BLOCKED", "AGENT_ADMIN_CREDENTIAL_EXPOSED", 0, "NONE", 0, 0, 0, "none"),
    "Q-012": E("ADOPTED", "CATALOG_EQUIVALENT_AUTHORITY_SERIALIZED", 2, "RUNNING", 12, 24, 0, "none"),
    "Q-013": E("ADOPTED", "CATALOG_ACTIVE_AUTHORITY_ADOPTED", 2, "RUNNING", 0, 0, 24, "none"),
    "Q-014": E("ADOPTED", "CATALOG_SUCCESS_ALREADY_EXISTS", 3, "SUCCESS", 0, 0, 24, "final"),
    "Q-015": E("BLOCKED", "CATALOG_LEDGER_COMMENT_TAMPERED", 1, "BLOCKED", 0, 0, 0, "none"),
    "Q-016": E("BLOCKED", "CATALOG_LEDGER_WRITER_INVALID", 1, "BLOCKED", 0, 0, 0, "none"),
    "Q-017": E("BLOCKED", "CATALOG_LEDGER_CHAIN_INVALID", 1, "BLOCKED", 0, 0, 0, "none"),
    "Q-018": E("SUCCESS", "CATALOG_COLD_COMPONENT_STORE_COMPLETE", 3, "SUCCESS", 12, 24, 0, "final"),
    "Q-019": E("SUCCESS", "CATALOG_WARM_COMPONENT_STORE_REUSED", 3, "SUCCESS", 0, 24, 12, "final"),
    "Q-020": E("SUCCESS", "CATALOG_PARTIAL_COMPONENT_STORE_REBUILT_MISSING_ONLY", 3, "SUCCESS", 4, 24, 8, "final"),
    "Q-021": E("BLOCKED", "CATALOG_COMPONENT_SUCCESS_CONFLICT", 2, "BLOCKED", 0, 0, 12, "none"),
    "Q-022": E("RECOVERING", "CATALOG_TRANSIENT_UNIT_RETRY_1", 3, "RECOVERING", 12, 25, 23, "receipt"),
    "Q-023": E("RECOVERING", "CATALOG_TRANSIENT_UNIT_RETRY_2", 4, "RECOVERING", 12, 26, 23, "receipt"),
    "Q-024": E("BLOCKED", "CATALOG_FAILURE_LIMIT_REACHED", 5, "BLOCKED", 12, 26, 23, "receipt"),
    "Q-025": E("BLOCKED", "CATALOG_DETERMINISTIC_FAILURE", 3, "BLOCKED", 12, 1, 0, "receipt"),
    "Q-026": E("RECOVERING", "CATALOG_OPERATIONAL_REPLAN", 3, "RECOVERING", 12, 24, 23, "receipt"),
    "Q-027": E("RECOVERING", "CATALOG_CORRUPT_CHECKPOINT_IGNORED", 3, "RECOVERING", 12, 25, 23, "receipt"),
    "Q-028": E("BLOCKED", "CATALOG_CONFLICTING_UNIT_SUCCESS", 3, "BLOCKED", 12, 25, 23, "receipt"),
    "Q-029": E("BLOCKED", "CATALOG_INCOMPLETE_FINAL_COVERAGE", 3, "BLOCKED", 12, 23, 23, "receipt"),
    "Q-030": E("SUCCESS", "CATALOG_HIERARCHICAL_REDUCTION_SELECTED", 3, "SUCCESS", 12, 24, 0, "final"),
    "Q-031": E("SUCCESS", "CATALOG_REDUCTION_MODES_EQUIVALENT", 3, "SUCCESS", 12, 24, 0, "final"),
    "Q-032": E("NOOP", "CATALOG_WATCHDOG_NO_AUTHORITY", 0, "NONE", 0, 0, 0, "none"),
    "Q-033": E("NOOP", "CATALOG_WATCHDOG_OWNER_ACTIVE", 2, "RUNNING", 0, 0, 24, "none"),
    "Q-034": E("RECOVERING", "CATALOG_WATCHDOG_ADOPTED_PENDING", 3, "RECOVERING", 0, 1, 23, "receipt"),
    "Q-035": E("BLOCKED", "CATALOG_DIRECT_HEAVY_DISPATCH_IMPOSSIBLE", 0, "NONE", 0, 0, 0, "none"),
    "Q-036": E("BLOCKED", "CATALOG_GITHUB_CONTROLS_INVALID", 2, "BLOCKED", 12, 24, 24, "receipt"),
    "Q-037": E("BLOCKED", "CATALOG_SOURCE_ARTIFACT_MISSING", 0, "NONE", 0, 0, 0, "none"),
    "Q-038": E("SUCCESS", "CATALOG_SECRET_OUTPUT_REDACTED", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-039": E("SUCCESS", "CATALOG_FINALIZER_IDEMPOTENT", 3, "SUCCESS", 12, 24, 24, "final"),
    "Q-040": E("SUCCESS", "CATALOG_SYNTHETIC_CAMPAIGN_SUCCESS", 3, "SUCCESS", 12, 24, 0, "final"),
    "Q-041": E("BLOCKED", "CATALOG_CONTROLLER_DISABLED", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-042": E("BLOCKED", "CATALOG_AUTHORITY_COMMENT_TAMPERED", 2, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-043": E("RECOVERING", "CATALOG_SCHEDULED_RECONCILER_DELIVERED_ONCE", 1, "RESERVED", 0, 0, 0, "receipt"),
    "Q-044": E("DEFERRED", "CATALOG_RECONCILER_PAGINATION_COMPLETE", 1, "RESERVED", 0, 0, 0, "receipt"),
    "Q-045": E("SUCCESS", "CATALOG_KEEPER_PRESERVATION_COMPLETE", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-046": E("RECOVERING", "CATALOG_COMPONENT_CACHE_REBUILD_MISSING_ONLY", 2, "RUNNING", 1, 0, 11, "receipt"),
    "Q-047": E("BLOCKED", "CATALOG_SOURCE_ARTIFACT_MISSING", 0, "NONE", 0, 0, 0, "none"),
    "Q-048": E("ADOPTED", "CATALOG_LEDGER_ETAG_SNAPSHOT_REUSED", 248, "RUNNING", 0, 0, 24, "receipt"),
    "Q-049": E("RECOVERING", "CATALOG_COMPONENTS_PRESERVED_AFTER_RECIPE_FAILURE", 3, "RECOVERING", 12, 1, 12, "receipt"),
    "Q-050": E("RECOVERING", "CATALOG_CHECKPOINT_SLOTS_1_7_REUSED", 3, "RECOVERING", 12, 1, 23, "receipt"),
    "Q-051": E("BLOCKED", "CATALOG_ORIGINATING_REQUEST_DELETED", 2, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-052": E("DEFERRED", "CATALOG_WAITING_FOR_FREE_CAPACITY", 0, "DEFERRED", 0, 0, 0, "receipt"),
    "Q-053": E("WAITING_RETRY", "CATALOG_RETRY_NOT_DUE", 3, "WAITING_RETRY", 0, 0, 23, "receipt"),
    "Q-054": E("SUCCESS", "CATALOG_WARM_DEPENDENCIES_REUSED", 3, "SUCCESS", 0, 24, 12, "final"),
    "Q-055": E("ADOPTED", "CATALOG_PAGINATED_CACHE_INVENTORY_COMPLETE", 0, "NONE", 0, 0, 12, "receipt"),
    "Q-056": E("FAILED", "CATALOG_CLOSED_SCIENTIFIC_FAILURE", 3, "FAILED", 12, 1, 0, "receipt"),
    "Q-057": E("DEFERRED", "CATALOG_FIFO_SERIALIZATION_ENFORCED", 1, "RESERVED", 0, 0, 0, "receipt"),
    "Q-058": E("BLOCKED", "CATALOG_PRE_RECIPE_FAILURE_EVIDENCE_COMPLETE", 3, "BLOCKED", 0, 0, 0, "receipt"),
    "Q-059": E("BLOCKED", "CATALOG_AUTHORITY_LIFECYCLE_TAMPERED", 2, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-060": E("BLOCKED", "CATALOG_AUTHORITY_ANCHOR_INVALID", 0, "NONE", 0, 0, 0, "none"),
    "Q-061": E("BLOCKED", "CATALOG_EXECUTION_PROTOCOL_INCOMPATIBLE", 3, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-062": E("BLOCKED", "BLOCKED_EXTERNAL_INTERVENTION", 2, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-063": E("BLOCKED", "CATALOG_REQUEST_LIFECYCLE_TAMPERED", 2, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-064": E("NOOP", "CATALOG_UNTRUSTED_RECEIPT_IGNORED", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-065": E("ADOPTED", "CATALOG_UNCERTAIN_POST_RECONCILED", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-066": E("BLOCKED", "CATALOG_PROMPT_HASH_MISMATCH", 0, "NONE", 0, 0, 0, "none"),
    "Q-067": E("ADOPTED", "CATALOG_PREFIX_CHECKPOINT_VERIFIED", 500, "RUNNING", 0, 0, 24, "receipt"),
    "Q-068": E("BLOCKED", "CATALOG_REQUEST_RECEIPT_TAMPERED", 2, "BLOCKED", 0, 0, 24, "receipt"),
    "Q-069": E("SUCCESS", "CATALOG_AFFINITY_LAYOUT_QUALIFIED", 3, "SUCCESS", 12, 24, 0, "final"),
    "Q-070": E("SUCCESS", "CATALOG_CROSS_RUNTIME_CANONICALIZATION_EQUAL", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-071": E("DEFERRED", "DEFERRED_ADMISSION_AUDIT_EXPIRED", 0, "DEFERRED", 0, 0, 0, "receipt"),
    "Q-072": E("BLOCKED", "CATALOG_KEEPER_FORBIDDEN_CLASSIFICATION", 0, "NONE", 0, 0, 0, "none"),
    "Q-073": E("BLOCKED", "CATALOG_FREE_STORAGE_UNPROVEN", 0, "NONE", 0, 0, 0, "none"),
    "Q-074": E("BLOCKED", "CATALOG_UNMANAGED_HEAVY_RUN", 0, "NONE", 0, 0, 0, "none"),
    "Q-075": E("BLOCKED", "CATALOG_REQUESTER_CAPABILITY_GATE", 0, "NONE", 0, 0, 0, "none"),
    "Q-076": E("ADOPTED", "CATALOG_NEXT_GENERATION_IDEMPOTENT", 3, "SUCCESS", 0, 0, 24, "final"),
    "Q-077": E("ADOPTED", "CATALOG_REQUESTER_JOURNAL_RECONSTRUCTED", 0, "NONE", 0, 0, 0, "receipt"),
    "Q-078": E("BLOCKED", "CATALOG_REQUESTER_PUBLIC_INPUT_DRIFT", 0, "NONE", 0, 0, 0, "none"),
}


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_simulator() -> ModuleType:
    assert SIMULATOR.is_file(), "qualification simulator is missing"
    spec = importlib.util.spec_from_file_location(
        "catalog_controller_qualification_simulator",
        SIMULATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(scenario_id: str) -> dict[str, object]:
    module = _load_simulator()
    result = module.run_scenario(scenario_id, CAMPAIGN_FIXTURE)
    assert isinstance(result, dict)
    return result


def _assert_scenario(scenario_id: str) -> None:
    expected = SCENARIOS[scenario_id]
    result = _run(scenario_id)
    assert set(result) == {
        "scenario_id",
        "outcome",
        "reason_code",
        "authority_record_count",
        "final_state",
        "component_execution_count",
        "unit_execution_count",
        "preserved_valid_work_count",
        "final_evidence_sha256",
        "production_data_accesses",
        "validation_opened",
        "locked_opened",
        "paid_runner_minutes",
        "estimated_paid_actions_cost",
        "untrusted_shell_fragments",
        "real_enforcer_calls",
        "receipt_sha256",
    }
    identity = {key: value for key, value in result.items() if key != "receipt_sha256"}
    assert result["receipt_sha256"] == _canonical_sha256(identity)
    assert result["scenario_id"] == scenario_id
    assert result["outcome"] == expected.outcome
    assert result["reason_code"] == expected.reason_code
    assert result["authority_record_count"] == expected.authority_record_count
    assert result["final_state"] == expected.final_state
    assert result["component_execution_count"] == expected.component_execution_count
    assert result["unit_execution_count"] == expected.unit_execution_count
    assert result["preserved_valid_work_count"] == expected.preserved_valid_work_count
    if expected.evidence_kind == "none":
        assert result["final_evidence_sha256"] is None
    elif expected.evidence_kind == "final":
        assert result["final_evidence_sha256"] == FINAL_RESULT_SHA256
    else:
        assert re.fullmatch(r"[0-9a-f]{64}", str(result["final_evidence_sha256"]))
    assert result["production_data_accesses"] == []
    assert result["validation_opened"] is False
    assert result["locked_opened"] is False
    assert result["paid_runner_minutes"] == 0
    assert result["estimated_paid_actions_cost"] == 0
    assert result["untrusted_shell_fragments"] == []
    assert isinstance(result["real_enforcer_calls"], list)
    assert result["real_enforcer_calls"]


@pytest.mark.parametrize("scenario_id", tuple(SCENARIOS))
def test_closed_q001_q078_scenario_matrix(scenario_id: str) -> None:
    _assert_scenario(scenario_id)


def test_scenario_matrix_is_exactly_q001_through_q078() -> None:
    assert tuple(SCENARIOS) == tuple(f"Q-{number:03d}" for number in range(1, 79))


def test_simulator_has_no_embedded_expected_result_matrix() -> None:
    source = SIMULATOR.read_text(encoding="utf-8")
    assert "_BASE_TEXT" not in source
    assert "QUALIFICATION_RESULT_UNOBSERVED" in source
    tree = ast.parse(source)
    for statement in tree.body:
        value = None
        if isinstance(statement, ast.Assign):
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            value = statement.value
        if not isinstance(value, ast.Dict):
            continue
        scenario_keys = {
            key.value
            for key in value.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and re.fullmatch(r"Q-[0-9]{3}", key.value)
        }
        assert not scenario_keys


def test_fixture_manifest_and_science_are_exact() -> None:
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    manifest_identity = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    assert manifest["manifest_sha256"] == _canonical_sha256(manifest_identity)
    for entry in manifest["entries"]:
        path = (FIXTURE_ROOT / entry["path"]).resolve()
        path.relative_to(FIXTURE_ROOT.resolve())
        assert path.is_file()
        assert path.stat().st_size == entry["size_bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]

    fixture = json.loads(CAMPAIGN_FIXTURE.read_text(encoding="utf-8"))
    assert len(fixture["recipes"]) == 24
    assert len(fixture["components"]) == 12
    assert fixture["recipe_worker_count"] == 4
    assert fixture["component_worker_count"] == 2
    components = {row["component_key"]: row for row in fixture["components"]}
    for row in components.values():
        assert hashlib.sha256(
            json.dumps(row["values"], separators=(",", ":")).encode()
        ).hexdigest() == row["expected_sha256"]
    results = []
    for recipe in fixture["recipes"]:
        value = sum(
            sum(components[key]["values"])
            for key in recipe["component_keys"]
        ) * recipe["coefficient"]
        result = {"recipe_id": recipe["recipe_id"], "value": value}
        assert value == recipe["expected_value"]
        assert _canonical_sha256(result) == recipe["expected_result_sha256"]
        results.append(result)
    assert _canonical_sha256(results) == FINAL_RESULT_SHA256
    assert fixture["expected_final_result_sha256"] == FINAL_RESULT_SHA256
    assert fixture["expected_central_result_sha256"] == FINAL_RESULT_SHA256
    assert fixture["expected_hierarchical_result_sha256"] == FINAL_RESULT_SHA256
    assert fixture["validation_opened"] is False
    assert fixture["locked_opened"] is False
    assert fixture["external_downloads"] is False
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", CAMPAIGN_FIXTURE.read_text())


def test_q041_key_is_ephemeral_in_memory_and_never_a_fixture_or_secret() -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    message = b"controller-bootstrap-qualification-v1"
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    public_key.verify(
        signature,
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    assert not list(FIXTURE_ROOT.glob("*.pem"))
    assert "secrets:" not in SIMULATOR.read_text(encoding="utf-8") if SIMULATOR.exists() else True


def test_simulator_imports_in_the_standalone_workflow_process() -> None:
    code = (
        "import importlib.util,sys;"
        f"sys.path.insert(0,{str(ROOT / 'tests')!r});"
        f"p={str(SIMULATOR)!r};"
        "s=importlib.util.spec_from_file_location('qualification_simulator',p);"
        "assert s is not None and s.loader is not None;"
        "m=importlib.util.module_from_spec(s);"
        "sys.modules[s.name]=m;"
        "s.loader.exec_module(m);"
        "assert callable(m.run_scenario)"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT.parent)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cat_001_enforced() -> None:
    _assert_scenario("Q-002")


def test_cat_002_enforced() -> None:
    _assert_scenario("Q-078")


def test_cat_003_enforced() -> None:
    _assert_scenario("Q-008")


def test_cat_004_enforced() -> None:
    _assert_scenario("Q-007")


def test_cat_005_enforced() -> None:
    _assert_scenario("Q-061")


def test_cat_006_enforced() -> None:
    _assert_scenario("Q-009")


def test_cat_007_enforced() -> None:
    _assert_scenario("Q-047")


def test_cat_008_enforced() -> None:
    _assert_scenario("Q-019")


def test_cat_009_enforced() -> None:
    _assert_scenario("Q-029")


def test_cat_010_enforced() -> None:
    _assert_scenario("Q-069")


def test_cat_011_enforced() -> None:
    _assert_scenario("Q-010")


def test_cat_012_enforced() -> None:
    _assert_scenario("Q-073")


def test_cat_013_enforced() -> None:
    _assert_scenario("Q-004")


def test_cat_014_enforced() -> None:
    _assert_scenario("Q-054")


def test_cat_015_enforced() -> None:
    _assert_scenario("Q-050")


def test_cat_016_enforced() -> None:
    _assert_scenario("Q-022")


def test_cat_017_enforced() -> None:
    _assert_scenario("Q-024")


def test_cat_018_enforced() -> None:
    _assert_scenario("Q-062")


def test_cat_019_enforced() -> None:
    _assert_scenario("Q-030")


def test_cat_020_enforced() -> None:
    _assert_scenario("Q-012")


def test_cat_021_enforced() -> None:
    _assert_scenario("Q-035")


def test_cat_022_enforced() -> None:
    _assert_scenario("Q-074")


def test_cat_023_enforced() -> None:
    _assert_scenario("Q-029")


def test_cat_024_enforced() -> None:
    _assert_scenario("Q-040")


def test_cat_025_enforced() -> None:
    _assert_scenario("Q-039")

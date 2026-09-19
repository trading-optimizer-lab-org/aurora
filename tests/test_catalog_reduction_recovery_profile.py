from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, asdict
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import (
    ReductionRecoveryArtifactV1,
    ReductionRecoveryProfileV1,
    load_reduction_recovery_profile,
    load_reduction_recovery_profiles,
    validate_exact_profile,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogRunRequestV1


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/catalog_reduction_recovery_profiles_v1.json"

PREDECESSOR_REQUEST_SHA256 = (
    "a0749c8833b52612096d8a820f3a46f5af48ce52848f8bfc02377f3236996896"
)
GEN8_REQUEST_SHA256 = "70d15409754069379635e7ff1d9a6990d8b30dff68fce16531cee875d16e719f"
SCIENCE_SHA256 = "57a24398bba9779f2095d20dc50f15975cd04949964055ae322411a3d57906a2"
SOURCE_PLAN_BINDINGS = {
    "request_sha256": PREDECESSOR_REQUEST_SHA256,
    "decision_sha256": "c9471a1431226acc4ef70bfd815ac2a6e0cc2bc011865b61d5d045244b0ebc7c",
    "protected_commit_sha": "fc77968dceeb93b332c143cc367b99128f488093",
    "authority_id": "b7102536-d7fa-5dc8-a438-d456bd2313c5",
    "campaign_id": "cf367334c63ed4e8a087ca3730b718e94e5e914877327a23c069f4989725173e",
    "science_sha256": SCIENCE_SHA256,
    "execution_plan_sha256": "64ea4c3c11181f4aa47a545c81da55d5d3e67ee406d78b0ddf3d0867ebe03f25",
    "execution_protocol_sha256": "e4f267c15125890abf6d1cc4e8889fa8975bf407b89d80306f59ac0691245631",
}
EXPECTED_STRATEGY_IDS = (
    "SCV1-0008de8188a0dfedb69e2087fa0786d8876821d9dfaeaf970a6b3f830fc031b0",
    "SCV1-0009261998f567e326cbcff4b17ed79c26420ecd05771957455abfdb0cfdda0a",
    "SCV1-000aec232b3b9f37549bab3388af27d55b6e1c57ac2192525a985f8d437b3b7b",
    "SCV1-000c5a76a3c0dac7d7dd53a1cffe80b86b511dc5cc447830033209746bd771fa",
    "SCV1-000ca745fd2a8fe5ac48e736fdcf7ae52b8dec69e68363e1b18b903cdb414dd4",
    "SCV1-00122340e81efb755e5586b43a952a5e1801bc131060752e2ac2487d6463661c",
    "SCV1-001937e4fad670d10fd93267f0c65a5a643a59dfc1d22e2b4d92c1c08d6ddf40",
    "SCV1-002e6ef7635802db02a3ed6deca385d1f368d0d080f5389d5feb0edc54b1a7f4",
)
PLAN_ARTIFACT = ReductionRecoveryArtifactV1(
    role="plan",
    artifact_id=10582715279,
    artifact_name="catalog-sealed-execution-plan-b7102536-d7fa-5dc8-a438-d456bd2313c5",
    digest="sha256:ed2d84bf6cc297eeeed6692003670d68d9916a5f71c2485c421ed670219d7472",
    receipt_sha256=None,
    size_bytes=175878,
    publisher_job_name="gate",
    publish_step_name="Publish the already-materialized sealed plan",
)
GROUP_ARTIFACT = ReductionRecoveryArtifactV1(
    role="group",
    artifact_id=10582565863,
    artifact_name="catalog-reduction-group-64ea4c3c11181f4a-g00",
    digest="sha256:1f32af1a9468e01a21fbb2e2869b945e273ed68a74eaf1b3153bc74588706e47",
    receipt_sha256="e7e2b1b22a70cbfcdba840f25d4b6e87656a3d1a9eb6e155e08f2d4a3e03fbd7",
    size_bytes=28148,
    publisher_job_name="engine / reduce_groups (catalog-checkpoint-64ea4c3c11181f4a-g00-*, 0, catalog-reduction-group-64ea4c3c1118...",
    publish_step_name="Upload one bounded reduction group",
)


def _request(
    *,
    campaign_key: str = "catalog-fast-canary-v1",
    launch_generation: int = 8,
    previous_terminal_request_sha256: str | None = PREDECESSOR_REQUEST_SHA256,
) -> CatalogRunRequestV1:
    return CatalogRunRequestV1.model_validate(
        {
            "schema_version": "1",
            "request_id": "018f47a2-6e91-7c34-8000-000000000008",
            "campaign_key": campaign_key,
            "launch_generation": launch_generation,
            "launch_ticket_sha256": "3" * 64,
            "previous_terminal_request_sha256": previous_terminal_request_sha256,
            "campaign_definition_sha256": "4" * 64,
            "prompt_sha256": "5" * 64,
            "authorization": "USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
            "free_resources_only": True,
            "automatic_recovery": True,
            "max_same_failure_count": 3,
            "requester_public_key_sha256": "6" * 64,
            "requester_attestation_algorithm": "rsa-pss-sha256-v1",
            "requester_attestation_b64": "A" * 300,
        }
    )


def test_generation8_canary_loads_one_frozen_profile_with_derived_hashes() -> None:
    profile = load_reduction_recovery_profile(ROOT, _request())

    assert isinstance(profile, ReductionRecoveryProfileV1)
    assert profile.campaign_key == "catalog-fast-canary-v1"
    assert profile.target_generation == 8
    assert profile.source_request_sha256 == PREDECESSOR_REQUEST_SHA256
    assert profile.source_issue_number == 323
    assert profile.source_run_id == 35436320227
    assert profile.source_run_attempt == 1
    assert profile.source_terminal_receipt_sha256 == (
        "67224b935b44f2d7598e2b28d9cb686d4eee89a046d0ec3b0482db4aba9d8cc4"
    )
    assert profile.science_sha256 == SCIENCE_SHA256
    assert profile.source_plan_bindings == SOURCE_PLAN_BINDINGS
    assert profile.strategy_ids == EXPECTED_STRATEGY_IDS
    assert profile.source_plan_receipt_sha256 == (
        "d4d0734b231aa346930b8654e26a9ae52cc4cf24098b2ab97815d4a13a11af04"
    )
    assert profile.catalog_manifest_sha256 == (
        "2de5b6a09fb10b71adff0f45af450f30c7f3dbfb196bfea8f01f92d4cf3cb981"
    )
    assert profile.artifacts == (PLAN_ARTIFACT, GROUP_ARTIFACT)

    dumped = profile.model_dump(mode="json")
    canonical = json.dumps(
        dumped, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert profile.profile_sha256 == hashlib.sha256(canonical).hexdigest()
    assert dumped["science_sha256"] == SCIENCE_SHA256
    assert dumped["strategy_ids"] == list(EXPECTED_STRATEGY_IDS)
    with pytest.raises((ValidationError, TypeError)):
        profile.campaign_key = "sp500-optimized-catalog-v1"


@pytest.mark.parametrize(
    ("campaign_key", "launch_generation"),
    [
        ("catalog-fast-canary-v1", 7),
        ("catalog-fast-canary-v1", 10),
        ("sp500-optimized-catalog-v1", 8),
        ("unknown-campaign-v1", 8),
    ],
)
def test_non_target_requests_return_none(
    campaign_key: str, launch_generation: int
) -> None:
    assert load_reduction_recovery_profile(
        ROOT,
        _request(campaign_key=campaign_key, launch_generation=launch_generation),
    ) is None


def test_generation8_canary_requires_exact_predecessor() -> None:
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_PREDECESSOR_MISMATCH"):
        load_reduction_recovery_profile(
            ROOT,
            _request(previous_terminal_request_sha256="a" * 64),
        )


def test_profile_config_is_closed_and_rejects_changed_protected_binding(
    tmp_path: Path,
) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["profiles"][0]["unexpected"] = True
    config = tmp_path / "config/catalog_reduction_recovery_profiles_v1.json"
    config.parent.mkdir()
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID"):
        load_reduction_recovery_profile(tmp_path, _request())

    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["profiles"][0]["artifacts"][1]["artifact_id"] = 10582565864
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID"):
        load_reduction_recovery_profile(tmp_path, _request())


def test_profile_has_no_target_definition_or_current_token_binding() -> None:
    profile = load_reduction_recovery_profile(ROOT, _request())
    assert profile is not None
    dumped = profile.model_dump(mode="json")
    assert "target_definition_sha256" not in dumped
    assert "admission_token_sha256" not in dumped
    assert "verification_token_sha256" not in dumped


def test_engine_loader_and_exact_validation_select_each_protected_profile() -> None:
    profiles = load_reduction_recovery_profiles(ROOT)
    assert tuple(profile.target_generation for profile in profiles) == (8, 9, 11)
    assert profiles[0] == load_reduction_recovery_profile(ROOT, _request())
    assert validate_exact_profile(ROOT, profiles[1].model_dump(mode="json")) == profiles[1]
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))["profiles"][0]
    assert validate_exact_profile(ROOT, payload) == profiles[0]

    payload["source_plan_bindings"]["decision_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH"):
        validate_exact_profile(ROOT, payload)


def test_gen8_serialization_and_hash_remain_exact() -> None:
    profile = load_reduction_recovery_profile(ROOT, _request())
    assert profile is not None
    assert profile.profile_sha256 == "482a84722888ab7410a796c4542dbc0bedad1abb8a8834e89287b3b52cdc40e5"
    assert "predecessor_bindings" not in profile.model_dump(mode="json")
    assert "source_generation" not in profile.model_dump(mode="json")
    assert profile.source_generation == 7
    predecessor = profile.predecessor_bindings
    assert predecessor.generation == 7
    assert predecessor.request_sha256 == PREDECESSOR_REQUEST_SHA256
    assert predecessor.issue_number == 323
    assert predecessor.run_id == 35436320227
    assert predecessor.run_attempt == 1
    assert predecessor.protected_commit_sha == SOURCE_PLAN_BINDINGS["protected_commit_sha"]
    assert predecessor.terminal_receipt_sha256 == profile.source_terminal_receipt_sha256
    assert predecessor.decision_sha256 == SOURCE_PLAN_BINDINGS["decision_sha256"]


def test_gen9_authorizes_gen8_but_preserves_gen7_source() -> None:
    profile = load_reduction_recovery_profile(
        ROOT, _request(launch_generation=9, previous_terminal_request_sha256=GEN8_REQUEST_SHA256)
    )
    assert profile is not None
    original = load_reduction_recovery_profile(ROOT, _request())
    assert original is not None
    expected = original.model_dump(mode="json")
    expected["target_generation"] = 9
    assert profile.model_dump(mode="json") == expected
    assert profile.profile_sha256 != original.profile_sha256
    assert profile.source_generation == 7
    assert asdict(profile.predecessor_bindings) == {
        "generation": 8,
        "request_sha256": GEN8_REQUEST_SHA256,
        "issue_number": 328,
        "run_id": 35454099484,
        "run_attempt": 1,
        "protected_commit_sha": "41d904b66c33bb8d0150aa14c7ca2564afd3f154",
        "terminal_receipt_sha256": "a10a880af0c3a3bd4ebd69958f5e4761cf3c620da32abddaff080a346b8a0193",
        "decision_sha256": "91e1e0bb41a76b5014d8d705cb67ccb5b163c24c2551bd1d84cc91ab37ccf023",
    }
    with pytest.raises(FrozenInstanceError):
        profile.predecessor_bindings.run_id = 1


@pytest.mark.parametrize("generation,predecessor", [(9, PREDECESSOR_REQUEST_SHA256), (9, "0" * 64), (8, GEN8_REQUEST_SHA256)])
def test_predecessors_cannot_be_cross_selected(generation: int, predecessor: str) -> None:
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_PREDECESSOR_MISMATCH"):
        load_reduction_recovery_profile(
            ROOT, _request(launch_generation=generation, previous_terminal_request_sha256=predecessor)
        )


@pytest.mark.parametrize("generations", [(8,), (9,), (8, 8), (9, 9), (8, 9, 9), (8, 10)])
def test_config_requires_exactly_two_distinct_protected_generations(tmp_path: Path, generations: tuple[int, ...]) -> None:
    original = json.loads(CONFIG.read_text("utf-8"))["profiles"][0]
    payload = {"schema_version": "1", "profiles": [dict(original, target_generation=g) for g in generations]}
    config = tmp_path / "config/catalog_reduction_recovery_profiles_v1.json"
    config.parent.mkdir()
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID"):
        load_reduction_recovery_profiles(tmp_path)


def test_exact_selection_is_independent_of_profile_order(tmp_path: Path) -> None:
    original = json.loads(CONFIG.read_text("utf-8"))["profiles"][0]
    gen11 = json.loads((ROOT / "tests/fixtures/catalog_recovery_gen10_source_profile.json").read_text("utf-8"))
    payload = {"schema_version": "1", "profiles": [gen11, dict(original, target_generation=9), original]}
    config = tmp_path / "config/catalog_reduction_recovery_profiles_v1.json"
    config.parent.mkdir()
    config.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_exact_profile(tmp_path, original).target_generation == 8
    assert validate_exact_profile(tmp_path, payload["profiles"][1]).target_generation == 9
    assert validate_exact_profile(tmp_path, gen11).target_generation == 11


def test_gen11_uses_exact_gen10_source_and_predecessor_without_changing_old_hashes() -> None:
    payload = json.loads((ROOT / "tests/fixtures/catalog_recovery_gen10_source_profile.json").read_text("utf-8"))
    profile = load_reduction_recovery_profile(
        ROOT, _request(launch_generation=11, previous_terminal_request_sha256=payload["source_request_sha256"])
    )
    assert profile is not None
    assert profile.model_dump(mode="json") == payload
    assert validate_exact_profile(ROOT, payload) == profile
    assert profile.source_generation == 10
    assert profile.terminal_reason_code == "CATALOG_ENGINE_STAGE_FAILED"
    assert asdict(profile.predecessor_bindings) == {
        "generation": 10, "request_sha256": payload["source_request_sha256"],
        "issue_number": 333, "run_id": 35460847765, "run_attempt": 1,
        "protected_commit_sha": "26a6832e3d0b9f0c319b99afc328ea9fb4831acf",
        "decision_sha256": "4bedf1b0e05eb1d15b14aad37d08d2d42fa76f1299ccbddd501900c8869dbdc5",
        "terminal_receipt_sha256": "3a414441d7498154f1c3128f9fc4dc286075286e86fb2a3d001574b0236e9bf5",
    }
    for generation, expected_hash in (
        (8, "482a84722888ab7410a796c4542dbc0bedad1abb8a8834e89287b3b52cdc40e5"),
        (9, "ba865a461790c8e5d78a4dc9ec06d259b6a8d8cd68ec4fb730334319f070fc6b"),
    ):
        old = next(p for p in load_reduction_recovery_profiles(ROOT) if p.target_generation == generation)
        assert old.profile_sha256 == expected_hash
        assert old.source_generation == 7
        assert old.terminal_reason_code == "CATALOG_REDUCTION_FAILED"
        assert "terminal_reason_code" not in old.model_dump(mode="json")


@pytest.mark.parametrize("predecessor", [PREDECESSOR_REQUEST_SHA256, GEN8_REQUEST_SHA256, "0" * 64])
def test_gen11_rejects_wrong_predecessor(predecessor: str) -> None:
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_PREDECESSOR_MISMATCH"):
        load_reduction_recovery_profile(ROOT, _request(launch_generation=11, previous_terminal_request_sha256=predecessor))


@pytest.mark.parametrize("mutation", ["source", "bindings", "artifacts", "generation", "reason", "receipt", "publisher"])
def test_gen11_rejects_mixed_or_altered_historical_provenance(mutation: str) -> None:
    payload = json.loads((ROOT / "tests/fixtures/catalog_recovery_gen10_source_profile.json").read_text("utf-8"))
    old = json.loads(CONFIG.read_text("utf-8"))["profiles"][0]
    if mutation == "source":
        payload["source_request_sha256"] = old["source_request_sha256"]
    elif mutation == "bindings":
        payload["source_plan_bindings"] = old["source_plan_bindings"]
    elif mutation == "artifacts":
        payload["artifacts"] = old["artifacts"]
    elif mutation == "generation":
        payload["target_generation"] = 9
    elif mutation == "reason":
        payload["terminal_reason_code"] = "CATALOG_REDUCTION_FAILED"
    elif mutation == "receipt":
        payload["source_terminal_receipt_sha256"] = "0" * 64
    else:
        payload["artifacts"][1]["publisher_job_name"] = "engine / evaluate_a"
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH"):
        validate_exact_profile(ROOT, payload)


@pytest.mark.parametrize("targets", [(8, 9), (8, 9, 9), (8, 11, 11), (8, 9, 11, 11), (8, 9, 12)])
def test_config_requires_exact_closed_targets_8_9_11(tmp_path: Path, targets: tuple[int, ...]) -> None:
    old = json.loads(CONFIG.read_text("utf-8"))["profiles"][0]
    new = json.loads((ROOT / "tests/fixtures/catalog_recovery_gen10_source_profile.json").read_text("utf-8"))
    payload = {"schema_version": "1", "profiles": [dict(new if g == 11 else old, target_generation=g) for g in targets]}
    config = tmp_path / "config/catalog_reduction_recovery_profiles_v1.json"
    config.parent.mkdir()
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_CONFIG_INVALID"):
        load_reduction_recovery_profiles(tmp_path)


@pytest.mark.parametrize("generation", [8, 9])
@pytest.mark.parametrize("mutation", ["source_request", "source_binding", "artifact", "predecessor_override"])
def test_both_generations_reject_source_or_predecessor_overrides(generation: int, mutation: str) -> None:
    payload = json.loads(CONFIG.read_text("utf-8"))["profiles"][0]
    payload["target_generation"] = generation
    if mutation == "source_request":
        payload["source_request_sha256"] = GEN8_REQUEST_SHA256
    elif mutation == "source_binding":
        payload["source_plan_bindings"]["request_sha256"] = GEN8_REQUEST_SHA256
    elif mutation == "artifact":
        payload["artifacts"][1]["artifact_id"] += 1
    else:
        payload["predecessor_bindings"] = {"request_sha256": "0" * 64}
    with pytest.raises(ValueError, match="CATALOG_REDUCTION_RECOVERY_PROFILE_MISMATCH"):
        validate_exact_profile(ROOT, payload)

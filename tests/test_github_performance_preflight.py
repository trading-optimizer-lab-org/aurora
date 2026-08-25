from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import RunSpec
from aurora.infra.github_performance.preflight import (
    DuplicateYamlKey,
    PreflightError,
    classify_workflow,
    freeze_resolved_contract,
    load_github_yaml,
    load_legacy_workflow_allowlist,
    load_legacy_workflow_migrations,
    resolve_run_spec,
    validate_future_workflow,
    validate_catalog_workflow_topology,
    validate_run_spec,
    validate_workflow_policy,
    write_preflight_report,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignRegistryV1,
    load_catalog_campaign_registry,
)
from github_performance_helpers import (
    complete_runtime_evidence,
    manual_heavy_workflow,
    minimal_valid_spec,
    push_triggered_heavy_workflow,
    workflow_with_step,
    write_yaml,
)


def test_rejects_local_execution(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["execution"]["local_runs_allowed"] = True
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "LOCAL_EXECUTION_ALLOWED" in report.violation_codes


def test_rejects_larger_runner(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["performance"]["larger_runners_allowed"] = True
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "LARGER_RUNNER_FORBIDDEN" in report.violation_codes


def test_rejects_planner_ceiling_above_360(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["performance"]["planner_max_jobs"] = 361
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "CONCURRENCY_CEILING_EXCEEDED" in report.violation_codes


def test_rejects_empty_user_owned_fields(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["identity"]["campaign_id"] = ""
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "REQUIRED_VALUE_EMPTY" in report.violation_codes


def test_rejects_zero_length_or_overlapping_periods(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["policy"]["train_end"] = spec["policy"]["train_start"]
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "PERIOD_ORDER_INVALID" in report.violation_codes


def test_rejects_data_after_validation(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["data"]["max_date"] = "2021-01-01"
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "DATA_AFTER_VALIDATION" in report.violation_codes


def test_runtime_evidence_freezes_blank_derived_hashes() -> None:
    requested = RunSpec.model_validate(minimal_valid_spec())
    resolved = resolve_run_spec(requested, complete_runtime_evidence())
    assert resolved.identity["code_sha"] == "a" * 40
    assert resolved.policy["policy_hash"] == "b" * 64
    assert resolved.data["snapshot_hash"] == "c" * 64
    assert resolved.execution["environment_sha256"] == "3" * 64
    assert resolved.performance["capacity_profile_sha256"] == "f" * 64


def test_supplied_runtime_hash_must_match_observed_evidence() -> None:
    payload = minimal_valid_spec()
    payload["identity"]["code_sha"] = "0" * 40
    requested = RunSpec.model_validate(payload)
    with pytest.raises(PreflightError, match="CODE_SHA_MISMATCH"):
        resolve_run_spec(requested, complete_runtime_evidence())


def test_freeze_writes_resolved_spec_and_performance_contract(
    tmp_path: Path,
) -> None:
    requested = RunSpec.model_validate(minimal_valid_spec())
    paths = freeze_resolved_contract(
        requested,
        complete_runtime_evidence(),
        tmp_path,
    )
    assert {path.name for path in paths} == {
        "resolved_run_spec.json",
        "performance_contract.json",
    }
    contract = json.loads((tmp_path / "performance_contract.json").read_text())
    assert contract["locked_opened"] is False
    assert contract["standard_runner_only"] is True
    assert contract["capacity_profile_sha256"] == "f" * 64


def test_preflight_report_is_machine_readable(tmp_path: Path) -> None:
    path = write_yaml(tmp_path / "spec.yaml", minimal_valid_spec())
    report = validate_run_spec(path)
    output = write_preflight_report(report, tmp_path / "output")
    payload = json.loads(output.read_text())
    assert payload["valid"] is False
    assert isinstance(payload["violations"], list)


def test_rejects_missing_local_reusable_workflow(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow("./.github/workflows/missing.yml"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "LOCAL_REFERENCE_MISSING" in {item.code for item in violations}


def test_rejects_unpinned_external_action(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        workflow_with_step("actions/checkout@v6"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "ACTION_NOT_PINNED" in {item.code for item in violations}


def test_rejects_unapproved_sha_for_official_action(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        workflow_with_step(f"actions/checkout@{'0' * 40}"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "ACTION_SHA_NOT_APPROVED" in {item.code for item in violations}


def test_rejects_local_reference_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-action"
    outside.write_text("name: outside\n", encoding="utf-8")
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow("./../outside-action"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "LOCAL_REFERENCE_OUTSIDE_REPO" in {
        item.code for item in violations
    }


def test_rejects_heavy_push_trigger(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        push_triggered_heavy_workflow(),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "HEAVY_AUTOMATIC_TRIGGER" in {item.code for item in violations}


def test_accepts_manual_framework_caller(tmp_path: Path) -> None:
    reusable = tmp_path / ".github/workflows/_aurora-future-run-v3.yml"
    reusable.parent.mkdir(parents=True)
    reusable.write_text("name: reusable\n", encoding="utf-8")
    caller = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow(
            "./.github/workflows/_aurora-future-run-v3.yml"
        ),
    )
    assert validate_future_workflow(caller, tmp_path) == []


def test_github_loader_preserves_on_as_a_string(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
    assert "on" in load_github_yaml(path)


def test_github_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "workflow.yml"
    path.write_text("name: first\nname: second\n", encoding="utf-8")
    with pytest.raises(DuplicateYamlKey, match="name"):
        load_github_yaml(path)


def test_legacy_workflow_is_identified_by_path_and_hash(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github/workflows/legacy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: legacy\n", encoding="utf-8")
    allowlist = {
        ".github/workflows/legacy.yml": (
            "e94863e008af0ffe480b5078baf6681b8ac8b9944eacf5eae59ac4046623da02"
        )
    }
    assert classify_workflow(workflow, allowlist, tmp_path) == "legacy"


def test_legacy_workflow_crlf_checkout_matches_lf_digest(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github/workflows/legacy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_bytes(b"name: legacy\r\n")
    allowlist = {
        ".github/workflows/legacy.yml": (
            "e94863e008af0ffe480b5078baf6681b8ac8b9944eacf5eae59ac4046623da02"
        )
    }

    assert classify_workflow(workflow, allowlist, tmp_path) == "legacy"


def test_one_byte_legacy_change_is_modified_legacy(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github/workflows/legacy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: changed\n", encoding="utf-8")
    allowlist = {".github/workflows/legacy.yml": "0" * 64}
    assert (
        classify_workflow(workflow, allowlist, tmp_path)
        == "modified_legacy"
    )
    violations = validate_workflow_policy(workflow, tmp_path, allowlist)
    assert "LEGACY_WORKFLOW_MODIFIED" in {
        item.code for item in violations
    }


def test_receipt_bound_legacy_migration_is_accepted(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github/workflows/legacy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: repaired\n", encoding="utf-8")
    previous_digest = "0" * 64
    replacement_digest = (
        "d0cf80ff4af4795964fcd40075abf995c2d114ffbc4826ad428234c205a5b2f9"
    )
    allowlist = {".github/workflows/legacy.yml": previous_digest}
    migrations = {
        ".github/workflows/legacy.yml": {
            "previous_sha256": previous_digest,
            "replacement_sha256": replacement_digest,
            "reason": "repair",
        }
    }

    assert (
        classify_workflow(workflow, allowlist, tmp_path, migrations)
        == "migrated_legacy"
    )
    assert (
        validate_workflow_policy(
            workflow,
            tmp_path,
            allowlist,
            migrations,
        )
        == []
    )


def test_legacy_migration_does_not_accept_unregistered_bytes(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / ".github/workflows/legacy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: tampered\n", encoding="utf-8")
    allowlist = {".github/workflows/legacy.yml": "0" * 64}
    migrations = {
        ".github/workflows/legacy.yml": {
            "previous_sha256": "0" * 64,
            "replacement_sha256": "1" * 64,
            "reason": "repair",
        }
    }

    assert (
        classify_workflow(workflow, allowlist, tmp_path, migrations)
        == "modified_legacy"
    )
    violations = validate_workflow_policy(
        workflow,
        tmp_path,
        allowlist,
        migrations,
    )
    assert {item.code for item in violations} == {
        "LEGACY_WORKFLOW_MODIFIED"
    }


def test_legacy_migration_loader_verifies_authorization_receipt(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "docs/readiness/owner.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"accepted":true}\n', encoding="utf-8")
    migration = tmp_path / "config/migrations.json"
    migration.parent.mkdir(parents=True)
    migration.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "authorization_receipt": {
                    "path": "docs/readiness/owner.json",
                    "sha256": (
                        "b1b367dc6a7d077581f77f16169a6696bac3d68ffd5c93189ac6"
                        "0fac027e57a3"
                    ),
                    "actor_id": "github-user:1",
                    "scope": "workflow_repair",
                },
                "migrations": [
                    {
                        "path": ".github/workflows/legacy.yml",
                        "previous_sha256": "0" * 64,
                        "replacement_sha256": "1" * 64,
                        "reason": "repair",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_legacy_workflow_migrations(migration, tmp_path)
    assert loaded[".github/workflows/legacy.yml"][
        "authorization_actor_id"
    ] == "github-user:1"
    receipt.write_text('{"accepted":false}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="receipt digest mismatches"):
        load_legacy_workflow_migrations(migration, tmp_path)


def test_authorized_adoption_loader_binds_receipt_commit_and_rows(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "docs/readiness/workflow-adoption.json"
    receipt.parent.mkdir(parents=True)
    adopted = [
        {
            "path": ".github/workflows/adopted.yml",
            "sha256": "1" * 64,
        }
    ]
    adopted_bytes = json.dumps(
        adopted,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    adopted_sha256 = hashlib.sha256(adopted_bytes).hexdigest()
    receipt_payload = {
        "accepted": True,
        "adopted_workflow_count": 1,
        "adopted_workflows_sha256": adopted_sha256,
        "authorization_scope": ["adopt_baseline"],
        "baseline_commit_sha": "b" * 40,
        "owner_actor_id": "github-user:1",
        "preserves_future_framework_enforcement": True,
    }
    receipt.write_text(
        json.dumps(
            receipt_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    allowlist_path = tmp_path / "config/allowlist.json"
    allowlist_path.parent.mkdir(parents=True)
    allowlist_path.write_text(
        json.dumps(
            {
                "adoption_commit": "a" * 40,
                "authorized_adoptions": [
                    {
                        "adoption_commit": "b" * 40,
                        "authorization_receipt": {
                            "actor_id": "github-user:1",
                            "path": "docs/readiness/workflow-adoption.json",
                            "scope": "adopt_baseline",
                            "sha256": hashlib.sha256(
                                receipt.read_bytes()
                                .replace(b"\r\n", b"\n")
                                .replace(b"\r", b"\n")
                            ).hexdigest(),
                        },
                        "workflow_count": 1,
                        "workflows_sha256": adopted_sha256,
                    }
                ],
                "schema_version": "2",
                "workflows": [
                    {
                        "adoption_commit": "b" * 40,
                        **adopted[0],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert load_legacy_workflow_allowlist(allowlist_path, tmp_path) == {
        ".github/workflows/adopted.yml": "1" * 64
    }
    receipt.write_text('{"accepted":false}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="receipt digest mismatches"):
        load_legacy_workflow_allowlist(allowlist_path, tmp_path)


def test_new_heavy_workflow_must_call_framework(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new-backtest.yml",
        {
            "name": "new backtest",
            "on": {"workflow_dispatch": {}},
            "permissions": {"contents": "read"},
            "jobs": {
                "search": {
                    "runs-on": "ubuntu-24.04",
                    "strategy": {
                        "fail-fast": False,
                        "matrix": {"stage": [0, 1]},
                    },
                    "steps": [{"run": "python scripts/run_search.py"}],
                }
            },
        },
    )
    violations = validate_workflow_policy(workflow, tmp_path, {})
    assert "FUTURE_HEAVY_WORKFLOW_BYPASSES_FRAMEWORK" in {
        item.code for item in violations
    }


def test_new_framework_caller_passes_policy(tmp_path: Path) -> None:
    reusable = tmp_path / ".github/workflows/_aurora-future-run-v3.yml"
    reusable.parent.mkdir(parents=True)
    reusable.write_text("name: reusable\n", encoding="utf-8")
    caller = write_yaml(
        tmp_path / ".github/workflows/new-backtest.yml",
        manual_heavy_workflow(
            "./.github/workflows/_aurora-future-run-v3.yml"
        ),
    )
    assert validate_workflow_policy(caller, tmp_path, {}) == []


def test_exact_internal_framework_helper_passes_policy(tmp_path: Path) -> None:
    helper = write_yaml(
        tmp_path / ".github/workflows/_aurora-merge-level-v3.yml",
        {
            "name": "bounded internal merge",
            "on": {"workflow_call": {}},
            "permissions": {"contents": "read"},
            "jobs": {
                "merge": {
                    "runs-on": "ubuntu-24.04",
                    "strategy": {"matrix": {"partition": [0, 1]}},
                    "steps": [{"run": "python scripts/merge.py"}],
                }
            },
        },
    )

    assert validate_workflow_policy(helper, tmp_path, {}) == []


def test_exact_serial_maintenance_inventory_passes_policy(
    tmp_path: Path,
) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/aurora-maintenance-inventory.yml",
        {
            "name": "read-only complete inventory",
            "on": {"workflow_dispatch": {}},
            "permissions": {
                "actions": "read",
                "contents": "read",
                "packages": "read",
            },
            "jobs": {
                "inventory": {
                    "runs-on": "ubuntu-24.04",
                    "timeout-minutes": 360,
                    "steps": [
                        {
                            "run": (
                                "python -m scripts."
                                "generate_gtbi_v7_full_inventory"
                            )
                        }
                    ],
                }
            },
        },
    )

    assert validate_workflow_policy(workflow, tmp_path, {}) == []


def test_internal_helper_exception_is_path_scoped(tmp_path: Path) -> None:
    lookalike = write_yaml(
        tmp_path / ".github/workflows/unregistered-helper.yml",
        {
            "name": "unregistered merge helper",
            "on": {"workflow_call": {}},
            "permissions": {"contents": "read"},
            "jobs": {
                "merge": {
                    "runs-on": "ubuntu-24.04",
                    "strategy": {"matrix": {"partition": [0, 1]}},
                    "steps": [{"run": "python scripts/merge.py"}],
                }
            },
        },
    )

    assert "FUTURE_HEAVY_WORKFLOW_BYPASSES_FRAMEWORK" in {
        violation.code
        for violation in validate_workflow_policy(lookalike, tmp_path, {})
    }


def test_repository_allowlist_has_frozen_adoption_metadata() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    allowlist = load_legacy_workflow_allowlist(repo_root=repo_root)
    assert len(allowlist) == 130
    assert ".github/workflows/tests.yml" in allowlist
    assert ".github/workflows/catalog-run-controller.yml" in allowlist
    assert ".github/workflows/sp500-atlas-run.yml" in allowlist


def _topology_registry() -> CatalogCampaignRegistryV1:
    return CatalogCampaignRegistryV1.model_validate(
        {
            "schema_version": "1",
            "campaigns": [
                {
                    "campaign_key": "fixture-v1",
                    "engine_id": "optimized_catalog_v1",
                    "definition_manifest_path": "config/definition.json",
                    "optimization_policy_path": "config/policy.json",
                    "campaign_contract_path": "config/campaign.json",
                    "catalog_dir": "config/catalog",
                    "selected_config_path": "config/selected.json",
                    "admission_evidence_path": "config/evidence.json",
                    "data_contract_path": "config/data.json",
                    "feature_contract_path": "config/features.json",
                    "runtime_input_run_id": 1,
                    "reference_run_id": 2,
                    "scientific_contract_sha256": "3" * 64,
                    "max_free_workers": 4,
                    "allowed_protected_branch": "main",
                    "source_artifact_contracts": ["runtime_input_pack_v1"],
                    "component_store_family": "sp500_component_store_v1",
                    "reducer_family": "catalog_hierarchical_reducer_v1",
                    "active": True,
                }
            ],
        }
    )


def test_repository_live_audit_and_keeper_topology_is_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    receipt = validate_catalog_workflow_topology(repo_root=root, registry=registry)
    relevant = {
        item.code
        for item in receipt.violations
        if item.code.startswith("CATALOG_LIVE_AUDIT")
        or item.code == "CATALOG_KEEPER_AUDIT_CALL_INVALID"
    }
    assert relevant == set()


def test_catalog_workflow_inventory_runbook_matches_sealed_topology() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = load_catalog_campaign_registry(
        root / "config/catalog_campaign_registry_v1.json"
    )
    receipt = validate_catalog_workflow_topology(repo_root=root, registry=registry)
    runbook = (root / "docs/runbooks/CATALOG_WORKFLOW_INVENTORY.md").read_text(
        encoding="utf-8"
    )

    assert receipt.status == "ready"
    assert f"Workflows inventariados: **{len(receipt.inventory)}**." in runbook
    assert f"Hash canónico del inventario final: `{receipt.inventory_sha256}`." in runbook


def _write_topology_fixture(
    root: Path,
    *,
    trigger: str = "workflow_call",
    runner: str = "ubuntu-24.04",
    environment: str | None = "catalog-production",
    action: str = f"actions/checkout@{'a' * 40}",
    checkout_ref: str = "${{ inputs.protected_commit_sha }}",
    run: str = "python scripts/run_sp500_optimized_recipe_worker.py",
) -> Path:
    workflow = {
        "name": "fixture catalog engine",
        "on": {
            trigger: (
                {
                    "inputs": {
                        name: {"required": True, "type": "string"}
                        for name in (
                            "request_sha256",
                            "authority_id",
                            "campaign_id",
                            "science_sha256",
                            "execution_plan_sha256",
                            "execution_protocol_sha256",
                            "protected_commit_sha",
                            "decision_sha256",
                        )
                    }
                }
                if trigger == "workflow_call"
                else {}
            )
        },
        "permissions": {"actions": "read", "contents": "read"},
        "jobs": {
            "engine": {
                "runs-on": runner,
                **({"environment": environment} if environment else {}),
                "steps": [
                    {"uses": action, "with": {"ref": checkout_ref}},
                    {"run": run},
                ],
            }
        },
    }
    return write_yaml(root / ".github/workflows/catalog-optimized-run.yml", workflow)


@pytest.mark.parametrize(
    ("update", "expected_code"),
    [
        ({"trigger": "workflow_dispatch"}, "CATALOG_HEAVY_PUBLIC_TRIGGER"),
        ({"runner": "windows-latest"}, "CATALOG_PAID_OR_UNSAFE_RUNNER"),
        ({"runner": "self-hosted"}, "CATALOG_PAID_OR_UNSAFE_RUNNER"),
        ({"environment": None}, "CATALOG_ENVIRONMENT_MISSING"),
        ({"action": "actions/checkout@v4"}, "CATALOG_ACTION_NOT_PINNED"),
        (
            {"checkout_ref": "${{ github.sha }}"},
            "CATALOG_PROTECTED_COMMIT_NOT_ENFORCED",
        ),
        ({"run": "gh workflow run unsafe.yml"}, "CATALOG_NESTED_DISPATCH"),
        (
            {"run": "echo '${{ github.event.issue.body }}'"},
            "CATALOG_UNTRUSTED_ISSUE_DATAFLOW",
        ),
    ],
)
def test_catalog_topology_rejects_escape_paths(
    tmp_path: Path,
    update: dict[str, object],
    expected_code: str,
) -> None:
    _write_topology_fixture(tmp_path, **update)
    receipt = validate_catalog_workflow_topology(
        repo_root=tmp_path,
        registry=_topology_registry(),
    )
    assert expected_code in {item.code for item in receipt.violations}

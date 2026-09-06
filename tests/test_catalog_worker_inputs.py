import json
from pathlib import Path

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_admission import (
    CatalogRunPlanV1,
    _plan_token,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from scripts.plan_sp500_optimized_catalog_run import build_repository_contract
from scripts.resolve_catalog_worker_inputs import (
    main,
    resolve_worker_inputs,
)


ROOT = Path(__file__).resolve().parents[1]


def _sealed_inputs(tmp_path: Path, campaign_key: str) -> tuple[Path, Path, str]:
    registry = load_catalog_campaign_registry(
        ROOT / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, campaign_key, ROOT)
    contract = build_repository_contract(
        repo_root=ROOT,
        policy_path=ROOT / entry.optimization_policy_path,
        campaign_path=ROOT / entry.campaign_contract_path,
        catalog_dir=ROOT / entry.catalog_dir,
        selected_config_path=ROOT / entry.selected_config_path,
    )
    contract_path = tmp_path / f"{campaign_key}.contract.json"
    contract_path.write_text(
        json.dumps(contract.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )

    work_manifest_sha256 = "b" * 64
    admission_token = "a" * 64
    plan = CatalogRunPlanV1(
        contract_sha256=contract.contract_sha256,
        evidence_sha256="c" * 64,
        admission_token_sha256=_plan_token(
            admission_token,
            work_manifest_sha256,
            pending_recipe_count=1,
            cached_recipe_count=0,
        ),
        workers=1,
        active_workers=1,
        component_workers=1,
        component_processes_per_worker=1,
        processes_per_worker=1,
        block_size=1,
        matrices=((0,),),
        work_manifest_sha256=work_manifest_sha256,
        pending_recipe_count=1,
        cached_recipe_count=0,
        expected_physical_component_builds=0,
    )
    plan_path = tmp_path / f"{campaign_key}.run-plan.json"
    plan_path.write_text(
        json.dumps(plan.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    return contract_path, plan_path, plan.admission_token_sha256


@pytest.mark.parametrize(
    "campaign_key",
    ("sp500-optimized-catalog-v1", "catalog-fast-canary-v1"),
)
def test_resolves_paths_from_each_active_registered_campaign(
    tmp_path: Path, campaign_key: str
) -> None:
    contract_path, plan_path, admission_token = _sealed_inputs(tmp_path, campaign_key)

    resolved = resolve_worker_inputs(
        repo_root=ROOT,
        resolved_contract=contract_path,
        run_plan=plan_path,
        admission_token=admission_token,
    )

    registry = load_catalog_campaign_registry(
        ROOT / "config/catalog_campaign_registry_v1.json"
    )
    entry = resolve_catalog_campaign(registry, campaign_key, ROOT)
    assert resolved == {
        "campaign_contract_path": entry.campaign_contract_path,
        "catalog_dir": entry.catalog_dir,
        "selected_config_path": entry.selected_config_path,
    }
    assert all(not Path(value).is_absolute() for value in resolved.values())


def test_main_appends_all_outputs_after_validation_and_preserves_existing_content(
    tmp_path: Path
) -> None:
    contract_path, plan_path, admission_token = _sealed_inputs(
        tmp_path, "sp500-optimized-catalog-v1"
    )
    output_path = tmp_path / "github-output"
    output_path.write_text("prior=value\n", encoding="utf-8")

    assert main(
        [
            "--repo-root",
            str(ROOT),
            "--resolved-contract",
            str(contract_path),
            "--run-plan",
            str(plan_path),
            "--admission-token",
            admission_token,
            "--github-output",
            str(output_path),
        ]
    ) == 0
    assert output_path.read_text(encoding="utf-8") == (
        "prior=value\n"
        "campaign_contract_path=config/sp500_megarun_dehb_campaign_v1.json\n"
        "catalog_dir=config/sp500_megarun_strategy_catalog_v1\n"
        "selected_config_path=config/sp500_megarun_selected_dehb_13.json\n"
    )


def test_rejects_unknown_science_without_appending(tmp_path: Path) -> None:
    contract_path, plan_path, admission_token = _sealed_inputs(
        tmp_path, "sp500-optimized-catalog-v1"
    )
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    payload["science"]["data_snapshot_sha256"] = "0" * 64
    contract_path.write_text(json.dumps(payload), encoding="utf-8")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["contract_sha256"] = canonical_sha256(payload)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    output_path = tmp_path / "github-output"
    output_path.write_text("prior=value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_WORKER_CAMPAIGN_UNRESOLVED"):
        resolve_worker_inputs(
            repo_root=ROOT,
            resolved_contract=contract_path,
            run_plan=plan_path,
            admission_token=admission_token,
        )
    assert output_path.read_text(encoding="utf-8") == "prior=value\n"


def test_rejects_contract_plan_mismatch_without_appending(tmp_path: Path) -> None:
    contract_path, plan_path, admission_token = _sealed_inputs(
        tmp_path, "sp500-optimized-catalog-v1"
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["contract_sha256"] = "d" * 64
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_WORKER_CONTRACT_PLAN_MISMATCH"):
        resolve_worker_inputs(
            repo_root=ROOT,
            resolved_contract=contract_path,
            run_plan=plan_path,
            admission_token=admission_token,
        )


def test_rejects_changed_selection_from_existing_registered_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract_path, plan_path, admission_token = _sealed_inputs(
        tmp_path, "sp500-optimized-catalog-v1"
    )

    def reject_changed_selection(**_: object) -> tuple[str, ...]:
        raise ValueError("CATALOG_REDUCER_SELECTED_CONTENT_MISMATCH")

    monkeypatch.setattr(
        "scripts.resolve_catalog_worker_inputs.resolve_registered_selected_result_keys",
        reject_changed_selection,
    )
    with pytest.raises(ValueError, match="CATALOG_REDUCER_SELECTED_CONTENT_MISMATCH"):
        resolve_worker_inputs(
            repo_root=ROOT,
            resolved_contract=contract_path,
            run_plan=plan_path,
            admission_token=admission_token,
        )


def test_rejects_symlink_github_output_before_writing(tmp_path: Path) -> None:
    contract_path, plan_path, admission_token = _sealed_inputs(
        tmp_path, "sp500-optimized-catalog-v1"
    )
    target = tmp_path / "real-output"
    target.write_text("prior=value\n", encoding="utf-8")
    output_path = tmp_path / "github-output"
    try:
        output_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert main(
        [
            "--repo-root",
            str(ROOT),
            "--resolved-contract",
            str(contract_path),
            "--run-plan",
            str(plan_path),
            "--admission-token",
            admission_token,
            "--github-output",
            str(output_path),
        ]
    ) == 2
    assert target.read_text(encoding="utf-8") == "prior=value\n"


def test_plan_fixture_uses_the_contract_hash_under_test(tmp_path: Path) -> None:
    contract_path, plan_path, _ = _sealed_inputs(
        tmp_path, "catalog-fast-canary-v1"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["contract_sha256"] == canonical_sha256(contract)

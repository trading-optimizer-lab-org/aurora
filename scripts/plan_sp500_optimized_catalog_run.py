"""Validate and freeze one optimized SP500 catalog execution plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from aurora.infra.sp500_megarun.catalog_admission import (
    CatalogAdmissionEvidenceV1,
    CatalogRunPlanV1,
    build_catalog_run_plan,
)
from aurora.infra.sp500_megarun.catalog_autotune import (
    CatalogPerformanceHistoryV1,
    CatalogTuningDecisionV1,
    ThermalState,
    select_history_configuration,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_component_inventory import (
    collect_unique_components,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeWorkManifestV1,
    build_resume_work_manifest,
    load_resume_index,
)
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_source_identity import (
    catalog_infrastructure_source_sha256,
    catalog_scientific_source_sha256,
)
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    numeric_runtime_profile_sha256,
)
from aurora.infra.sp500_megarun.strategy_catalog import (
    verify_strategy_catalog_directory,
)


def _read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(Path(path).read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CATALOG_PLAN_INPUT_NOT_OBJECT")
    return payload


def _matrix_payload(shards: tuple[int, ...]) -> str:
    return json.dumps(
        {"shard": list(shards)},
        separators=(",", ":"),
        sort_keys=True,
    )


def _component_matrix_payload(worker_count: int) -> str:
    return json.dumps(
        {"component_shard": list(range(worker_count))},
        separators=(",", ":"),
        sort_keys=True,
    )


def apply_qualification_worker_override(
    contract: RunOptimizationContractV1,
    *,
    workers: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Create one measured worker-count candidate without weakening production."""

    if not qualification_only:
        raise ValueError("WORKER_OVERRIDE_REQUIRES_QUALIFICATION")
    if not 1 <= int(workers) <= 360:
        raise ValueError("WORKER_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "workers": int(workers),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_qualification_process_override(
    contract: RunOptimizationContractV1,
    *,
    processes_per_worker: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Create one measured process-count candidate without weakening production."""

    if not qualification_only:
        raise ValueError("PROCESS_OVERRIDE_REQUIRES_QUALIFICATION")
    if int(processes_per_worker) not in (1, 2, 4):
        raise ValueError("PROCESS_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "processes_per_worker": int(processes_per_worker),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_qualification_component_process_override(
    contract: RunOptimizationContractV1,
    *,
    component_processes_per_worker: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Measure component CPU topology independently from recipe topology."""

    if not qualification_only:
        raise ValueError("COMPONENT_PROCESS_OVERRIDE_REQUIRES_QUALIFICATION")
    if int(component_processes_per_worker) not in (1, 2, 4):
        raise ValueError("COMPONENT_PROCESS_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "component_processes_per_worker": int(component_processes_per_worker),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_qualification_component_worker_override(
    contract: RunOptimizationContractV1,
    *,
    component_workers: int,
    qualification_only: bool,
) -> RunOptimizationContractV1:
    """Measure component fan-out independently from recipe fan-out."""

    if not qualification_only:
        raise ValueError("COMPONENT_WORKER_OVERRIDE_REQUIRES_QUALIFICATION")
    if not 1 <= int(component_workers) <= 120:
        raise ValueError("COMPONENT_WORKER_OVERRIDE_INVALID")
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "component_workers": int(component_workers),
    }
    return RunOptimizationContractV1.model_validate(payload)


def apply_compatible_autotune_history(
    contract: RunOptimizationContractV1,
    *,
    history_path: Path | None,
    thermal_state: ThermalState,
) -> tuple[RunOptimizationContractV1, CatalogTuningDecisionV1 | None]:
    """Apply only a three-sample, science-compatible promoted configuration."""

    if history_path is None or not Path(history_path).is_file():
        return contract, None
    history = CatalogPerformanceHistoryV1.load(Path(history_path))
    try:
        decision = select_history_configuration(
            history,
            science_identity_sha256=canonical_sha256(contract.science),
            thermal_state=thermal_state,
            minimum_samples=3,
            previous_best_median_seconds=None,
            max_regression_ratio=contract.acceptance.max_performance_regression_ratio,
            max_memory_fraction=contract.limits.max_memory_fraction,
        )
    except ValueError as exc:
        if str(exc) == "CATALOG_TUNING_NO_SAFE_EQUIVALENT_CANDIDATE":
            return contract, None
        raise
    payload = contract.model_dump(mode="python")
    payload["execution"] = {
        **payload["execution"],
        "workers": decision.workers,
        "component_workers": decision.component_workers,
        "component_processes_per_worker": (
            decision.component_processes_per_worker
        ),
        "processes_per_worker": decision.processes_per_worker,
        "block_size": decision.block_size,
    }
    return RunOptimizationContractV1.model_validate(payload), decision


def build_repository_contract(
    *,
    repo_root: Path,
    policy_path: Path,
    campaign_path: Path,
    catalog_dir: Path,
    selected_config_path: Path | None = None,
) -> RunOptimizationContractV1:
    """Resolve all scientific identities and counts from authoritative files."""

    repo_root = Path(repo_root).resolve()
    policy = _read_json_object(policy_path)
    campaign = _read_json_object(campaign_path)
    boundaries = campaign.get("boundaries")
    scientific_inputs = campaign.get("scientific_inputs")
    if not isinstance(boundaries, dict) or not isinstance(scientific_inputs, dict):
        raise ValueError("CATALOG_CAMPAIGN_CONTRACT_INVALID")
    receipt = verify_strategy_catalog_directory(Path(catalog_dir))
    catalog_path = Path(catalog_dir) / "catalog.jsonl"
    catalog_rows = [
        json.loads(line)
        for line in catalog_path.read_text("utf-8").splitlines()
        if line
    ]
    selected_path = (
        Path(selected_config_path)
        if selected_config_path is not None
        else repo_root / "config/sp500_megarun_selected_dehb_13.json"
    )
    selected_payload = json.loads(selected_path.read_text("utf-8"))
    if not isinstance(selected_payload, list):
        raise ValueError("CATALOG_SELECTED_CONFIG_INVALID")
    canonical_recipes = len(
        {str(row["scientific_recipe_sha256"]) for row in catalog_rows}
    )
    unique_components = collect_unique_components(catalog_rows, selected_payload)
    estimates = policy.get("workload_estimates")
    if not isinstance(estimates, dict):
        raise ValueError("CATALOG_WORKLOAD_ESTIMATES_INVALID")
    prior_cache_hits = int(estimates["expected_prior_cache_hits"])
    if policy.get("numeric_profile") != "derived:dehb_numeric_runtime_v1":
        raise ValueError("CATALOG_NUMERIC_PROFILE_POLICY_INVALID")
    manifest_path = Path(catalog_dir) / "manifest.json"
    payload = {
        "schema_version": policy["schema_version"],
        "optimization_mode": policy["optimization_mode"],
        "allow_unoptimized_run": policy["allow_unoptimized_run"],
        "infrastructure_sha256": catalog_infrastructure_source_sha256(repo_root),
        "science": {
            "evaluator_sha256": catalog_scientific_source_sha256(repo_root),
            "data_snapshot_sha256": scientific_inputs[
                "train_snapshot_manifest_sha256"
            ],
            "catalog_manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "train_end": boundaries["search_end"],
            "validation_opened": boundaries["validation_opened"],
            "locked_opened": boundaries["locked_opened"],
            "numeric_profile": numeric_runtime_profile_sha256(),
        },
        "workload": {
            "requested_recipes": int(receipt["strategy_count"]),
            "canonical_recipes": canonical_recipes,
            "unique_components": len(unique_components),
            "expected_new_recipes": canonical_recipes - prior_cache_hits,
            "expected_prior_cache_hits": prior_cache_hits,
            "estimated_position_equivalences": estimates[
                "estimated_position_equivalences"
            ],
        },
        "execution": policy["execution"],
        "limits": policy["limits"],
        "acceptance": policy["acceptance"],
    }
    return RunOptimizationContractV1.model_validate(payload)


def write_catalog_run_plan(
    contract_path: Path,
    evidence_path: Path,
    output_dir: Path,
    *,
    github_output: Path | None = None,
    work_manifest: CatalogResumeWorkManifestV1 | None = None,
) -> CatalogRunPlanV1:
    """Write a plan only after the fail-closed admission controller accepts it."""

    contract = RunOptimizationContractV1.model_validate(
        _read_json_object(contract_path)
    )
    evidence = CatalogAdmissionEvidenceV1.model_validate(
        _read_json_object(evidence_path)
    )
    plan = build_catalog_run_plan(
        contract,
        evidence,
        work_manifest_sha256=(
            work_manifest.manifest_sha256 if work_manifest is not None else "0" * 64
        ),
        pending_recipe_count=(
            len(work_manifest.pending_strategy_ids)
            if work_manifest is not None
            else None
        ),
        cached_recipe_count=(
            len(work_manifest.cached_strategy_ids)
            if work_manifest is not None
            else 0
        ),
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "resolved_contract.json").write_text(
        contract.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    (output_dir / "admission_evidence.json").write_text(
        evidence.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    (output_dir / "run_plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n",
        "utf-8",
    )
    if work_manifest is not None:
        (output_dir / "resume_work_manifest.json").write_text(
            work_manifest.model_dump_json(indent=2) + "\n",
            "utf-8",
        )
    if github_output is not None:
        matrices = list(plan.matrices)
        matrices.extend([tuple()] * (3 - len(matrices)))
        if len(matrices) != 3:
            raise ValueError("CATALOG_PLAN_MATRIX_COUNT_INVALID")
        lines = [
            f"matrix_a={_matrix_payload(matrices[0])}",
            f"matrix_b={_matrix_payload(matrices[1])}",
            f"matrix_c={_matrix_payload(matrices[2])}",
            f"admission_token_sha256={plan.admission_token_sha256}",
            f"workers={plan.workers}",
            f"active_workers={plan.active_workers}",
            f"component_workers={plan.component_workers}",
            "component_matrix="
            f"{_component_matrix_payload(plan.component_workers)}",
            f"pending_recipe_count={plan.pending_recipe_count}",
            f"cached_recipe_count={plan.cached_recipe_count}",
            "component_processes_per_worker="
            f"{plan.component_processes_per_worker}",
            f"processes_per_worker={plan.processes_per_worker}",
            f"block_size={plan.block_size}",
        ]
        Path(github_output).write_text("\n".join(lines) + "\n", "utf-8")
    return plan


def write_repository_catalog_run_plan(
    *,
    repo_root: Path,
    policy_path: Path,
    campaign_path: Path,
    catalog_dir: Path,
    selected_config_path: Path | None = None,
    evidence_path: Path,
    output_dir: Path,
    github_output: Path | None = None,
    resume_roots: tuple[Path, ...] = (),
    benchmark_workers: int | None = None,
    benchmark_processes: int | None = None,
    benchmark_component_processes: int | None = None,
    benchmark_component_workers: int | None = None,
    autotune_history_path: Path | None = None,
    thermal_state: ThermalState = "cold",
) -> CatalogRunPlanV1:
    """Resolve the immutable contract from the checkout before admission."""

    contract = build_repository_contract(
        repo_root=repo_root,
        policy_path=policy_path,
        campaign_path=campaign_path,
        catalog_dir=catalog_dir,
        selected_config_path=selected_config_path,
    )
    contract, autotune_decision = apply_compatible_autotune_history(
        contract,
        history_path=autotune_history_path,
        thermal_state=thermal_state,
    )
    if benchmark_workers is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_worker_override(
            contract,
            workers=benchmark_workers,
            qualification_only=evidence.qualification_only,
        )
    if benchmark_processes is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_process_override(
            contract,
            processes_per_worker=benchmark_processes,
            qualification_only=evidence.qualification_only,
        )
    if benchmark_component_processes is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_component_process_override(
            contract,
            component_processes_per_worker=benchmark_component_processes,
            qualification_only=evidence.qualification_only,
        )
    if benchmark_component_workers is not None:
        evidence = CatalogAdmissionEvidenceV1.model_validate(
            _read_json_object(evidence_path)
        )
        contract = apply_qualification_component_worker_override(
            contract,
            component_workers=benchmark_component_workers,
            qualification_only=evidence.qualification_only,
        )
    resolved_path = Path(output_dir).parent / "resolved-contract-input.json"
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(contract.model_dump_json(indent=2) + "\n", "utf-8")
    catalog_rows = [
        json.loads(line)
        for line in (Path(catalog_dir) / "catalog.jsonl").read_text("utf-8").splitlines()
        if line
    ]
    science_identity_sha256 = canonical_sha256(contract.science)
    resume_index = load_resume_index(
        resume_roots,
        expected_science_identity_sha256=science_identity_sha256,
        expected_catalog_manifest_sha256=contract.science.catalog_manifest_sha256,
    )
    work_manifest = build_resume_work_manifest(
        tuple(str(row["strategy_id"]) for row in catalog_rows),
        cached_strategy_ids=resume_index.strategy_ids,
        maximum_workers=contract.execution.workers,
    )
    try:
        plan = write_catalog_run_plan(
            resolved_path,
            evidence_path,
            output_dir,
            github_output=github_output,
            work_manifest=work_manifest,
        )
        if autotune_decision is not None:
            (Path(output_dir) / "autotune_decision.json").write_text(
                autotune_decision.model_dump_json(indent=2) + "\n",
                "utf-8",
            )
        return plan
    finally:
        resolved_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--contract", type=Path)
    source.add_argument("--policy", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--catalog-dir", type=Path)
    parser.add_argument("--selected-config", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--resume-root", type=Path, action="append", default=[])
    parser.add_argument("--benchmark-workers", type=int, default=0)
    parser.add_argument("--benchmark-processes", type=int, default=0)
    parser.add_argument("--benchmark-component-processes", type=int, default=0)
    parser.add_argument("--benchmark-component-workers", type=int, default=0)
    parser.add_argument("--autotune-history", type=Path)
    parser.add_argument(
        "--thermal-state",
        choices=("cold", "component_warm", "fully_hot"),
        default="cold",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.contract is not None:
        write_catalog_run_plan(
            args.contract,
            args.evidence,
            args.output_dir,
            github_output=args.github_output,
        )
    else:
        if args.repo_root is None or args.campaign is None or args.catalog_dir is None:
            raise SystemExit(
                "--policy requires --repo-root, --campaign and --catalog-dir"
            )
        write_repository_catalog_run_plan(
            repo_root=args.repo_root,
            policy_path=args.policy,
            campaign_path=args.campaign,
            catalog_dir=args.catalog_dir,
            selected_config_path=args.selected_config,
            evidence_path=args.evidence,
            output_dir=args.output_dir,
            github_output=args.github_output,
            resume_roots=tuple(args.resume_root),
            benchmark_workers=(
                args.benchmark_workers if args.benchmark_workers else None
            ),
            benchmark_processes=(
                args.benchmark_processes if args.benchmark_processes else None
            ),
            benchmark_component_processes=(
                args.benchmark_component_processes
                if args.benchmark_component_processes
                else None
            ),
            benchmark_component_workers=(
                args.benchmark_component_workers
                if args.benchmark_component_workers
                else None
            ),
            autotune_history_path=args.autotune_history,
            thermal_state=args.thermal_state,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

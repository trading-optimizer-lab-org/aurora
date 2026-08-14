"""Build official DEHB coordinator state from the continuous database."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace
from aurora.infra.sp500_megarun.dehb_continuous_coordinator import (
    ContinuousCampaignCoordinator,
)
from aurora.infra.sp500_megarun.dehb_continuous_island import (
    ContinuousIslandState,
    pack_checkpoint_directory,
    restore_checkpoint_directory,
)
from aurora.infra.sp500_megarun.dehb_continuous_models import (
    EvaluationCacheKeyV2,
    EvaluationProposalV2,
)
from aurora.infra.sp500_megarun.dehb_evaluation_cache import (
    scientific_evaluator_binding_sha256,
)
from aurora.infra.sp500_megarun.dehb_island_runner import _resume_safe_dehb_class
from aurora.infra.sp500_megarun.dehb_numeric_runtime import (
    numeric_runtime_profile_sha256,
)


def _fidelity_recipe_sha256(contract: Any, fidelity: int) -> str:
    specification = next(item for item in contract.fidelities if int(item.budget) == fidelity)
    payload = {
        "schema_version": 1,
        "budget": int(specification.budget),
        "years": [int(year) for year in specification.years],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_continuous_coordinator(
    *,
    store: Any,
    campaign: Any,
    feature_contract: Any,
    launch: Any,
    work_root: Path,
    owner_token: str,
) -> ContinuousCampaignCoordinator:
    """Restore 720 official optimizers and replay any unresolved deterministic asks."""

    import dehb

    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    open_batches = store.load_open_batches()
    islands = []
    for record in store.load_island_records():
        native = root / record.island_id / "native_checkpoint"
        resume = record.checkpoint_bytes is not None
        if resume:
            restore_checkpoint_directory(
                record.checkpoint_bytes,
                native,
                expected_checkpoint_sha256=str(record.checkpoint_sha256),
            )
        else:
            native.mkdir(parents=True, exist_ok=True)
        lane_space = build_lane_configspace(
            feature_contract,
            record.lane_id,
            seed=record.restart_seed,
        )
        optimizer_class = _resume_safe_dehb_class(dehb.DEHB) if resume else dehb.DEHB
        optimizer = optimizer_class(
            cs=lane_space.configspace,
            f=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("CONTINUOUS_COORDINATOR_MUST_NOT_EVALUATE")
            ),
            min_fidelity=min(int(item.budget) for item in campaign.fidelities),
            max_fidelity=max(int(item.budget) for item in campaign.fidelities),
            eta=campaign.eta,
            seed=record.restart_seed,
            n_workers=1,
            output_path=native,
            save_freq="end",
            log_level="WARNING",
            resume=resume,
        )

        def serialize(value: Any, *, checkpoint_dir: Path = native) -> bytes:
            value.save()
            return pack_checkpoint_directory(checkpoint_dir)

        state = ContinuousIslandState(
            island_id=record.island_id,
            optimizer=optimizer,
            full_fidelity=max(int(item.budget) for item in campaign.fidelities),
            plateau_minimum_completed=campaign.plateau_minimum_completed,
            plateau_completed_without_improvement=(
                campaign.plateau_completed_without_improvement
            ),
            checkpoint_serializer=serialize,
            next_batch_sequence=record.next_batch_sequence,
            evaluations=int(record.runtime_state.get("evaluations", 0)),
            full_fidelity_evaluations=int(
                record.runtime_state.get("full_fidelity_evaluations", 0)
            ),
            completed_since_improvement=int(
                record.runtime_state.get("completed_since_improvement", 0)
            ),
            best_archive_key=(
                tuple(float(value) for value in record.runtime_state["best_archive_key"])
                if record.runtime_state.get("best_archive_key") is not None
                else None
            ),
            prior_checkpoint_sha256=record.checkpoint_sha256,
        )
        if record.island_id in open_batches:
            state.restore_open_batch(open_batches[record.island_id])
        islands.append(state)

    evaluator_sha256 = scientific_evaluator_binding_sha256(
        code_commit_sha=launch.code_commit_sha,
        campaign_contract_sha256=campaign.sha256,
        runtime_scientific_input_binding_sha256=(
            launch.runtime_scientific_input_binding_sha256
        ),
        numeric_runtime_profile_sha256=numeric_runtime_profile_sha256(),
    )

    def proposal_builder(island: Any, batch: Any, slot: int, job: dict) -> EvaluationProposalV2:
        fidelity = int(float(job["fidelity"]))
        key = EvaluationCacheKeyV2.build(
            evaluator_sha256=evaluator_sha256,
            numeric_profile_sha256=numeric_runtime_profile_sha256(),
            train_manifest_sha256=campaign.train_snapshot_manifest_sha256,
            train_spy_sha256=campaign.train_spy_sha256,
            campaign_contract_sha256=campaign.sha256,
            lane_id=island.island_id[:4],
            configuration=dict(job["config"]),
            fidelity=fidelity,
            fidelity_recipe_sha256=_fidelity_recipe_sha256(campaign, fidelity),
            robustness_identity="base",
        )
        return EvaluationProposalV2.build(
            campaign_id=store.campaign_id,
            island_id=island.island_id,
            batch_sequence=batch.batch_sequence,
            batch_slot=slot,
            evaluation_key=key,
            dehb_job=job,
        )

    coordinator = ContinuousCampaignCoordinator(
        store=store,
        islands=islands,
        proposal_builder=proposal_builder,
        owner_token=owner_token,
        open_batches=open_batches.values(),
    )
    return coordinator


__all__ = ["build_continuous_coordinator"]

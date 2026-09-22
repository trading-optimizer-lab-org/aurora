"""Closed failure-owner evidence, explicitly not a scientific terminal.

The caller authenticates the protected profile, signed request, gate owner and
stable terminal inventory with the existing GitHub readers before using this
boundary. This evidence alone neither reserves a successor nor admits science.
No scientific runtime dependency is imported by the controller boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

from ..github_performance.contracts import canonical_sha256
from .catalog_fast_reservation import FastGateOwnerEvidence
from .catalog_fast_path import CatalogTerminalReceiptV1, CatalogTerminalReceiptV2

if TYPE_CHECKING:
    from .catalog_checkpoint_recovery_profile import CheckpointRecoveryProfileV1


@dataclass(frozen=True)
class CheckpointRecoveryOwnerProofV1:
    profile_sha256: str
    campaign_key: str
    target_generation: int
    source_request_sha256: str
    source_issue_number: int
    source_run_id: int
    source_run_attempt: int
    source_protected_commit_sha: str
    source_decision_sha256: str
    source_finalizer_job_id: int
    evidence_kind: Literal['failed_owner_without_terminal', 'failed_owner_with_terminal'] = 'failed_owner_without_terminal'

    @property
    def source_terminal_receipt_sha256(self) -> str | None:
        if self.evidence_kind == 'failed_owner_with_terminal' and self.target_generation == 9:
            from .catalog_checkpoint_recovery_profile import CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
            return CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
        return None

    @property
    def evidence_sha256(self) -> str:
        return canonical_sha256(asdict(self))


def verify_checkpoint_failure_owner(
    *, profile: CheckpointRecoveryProfileV1, owner: FastGateOwnerEvidence,
    terminal: object | None,
) -> CheckpointRecoveryOwnerProofV1:
    """Validate the profile's exact failure state after reader authentication.

    ``terminal=None`` must be the result of ``load_owner_terminal_receipt`` on
    its stable, complete inventory, never an assumption or a caught exception.
    The terminal-bearing successor requires its exact published BLOCKED receipt.
    The original source owner is not mutated or declared terminal here.
    """
    code = 'CATALOG_CHECKPOINT_RECOVERY_OWNER_INVALID'
    try:
        terminal_recovery = profile.target_generation == 9
        if (
            not isinstance(owner, FastGateOwnerEvidence)
            or owner.unlaunched_terminal
            or (not terminal_recovery and terminal is not None)
            or owner.run_id != profile.source_run_id
            or owner.run['id'] != profile.source_run_id
            or owner.run['run_attempt'] != profile.source_run_attempt
            or owner.run['head_sha'] != profile.source_protected_commit_sha
            or owner.run['head_branch'] != 'main'
            or owner.run['status'] != 'completed'
            or owner.run['conclusion'] != 'failure'
            or owner.decision.launch_required is not True
            or owner.decision.request_sha256 != profile.source_request_sha256
            or owner.decision.campaign_key != profile.campaign_key
            or owner.decision.decision_sha256 != profile.source_plan_bindings['decision_sha256']
        ):
            raise ValueError(code)
        jobs = [job for job in owner.jobs if job.get('name') == 'finalize']
        if len(jobs) != 1:
            raise ValueError(code)
        job = jobs[0]
        if (
            type(job['id']) is not int or job['id'] <= 0
            or job['run_id'] != profile.source_run_id
            or job['run_attempt'] != profile.source_run_attempt
            or job['head_sha'] != profile.source_protected_commit_sha
            or job['status'] != 'completed'
            or job['conclusion'] != ('success' if terminal_recovery else 'failure')
        ):
            raise ValueError(code)
        expected_steps = {
            'Fetch one bounded timing snapshot': 'failure',
            'Create exactly one terminal receipt': 'skipped',
            'Publish the terminal receipt before changing the issue': 'skipped',
            'Write current authority edition': 'skipped',
            'Publish current authority edition': 'skipped',
            'Verify the terminal publication before releasing the campaign': 'skipped',
            'Publish the terminal state and release the reservation': 'skipped',
        }
        if terminal_recovery:
            from .catalog_fast_reservation import bind_owner_terminal_receipt
            from .catalog_fast_path import parse_catalog_terminal_receipt

            if not isinstance(terminal, (CatalogTerminalReceiptV1, CatalogTerminalReceiptV2)):
                raise ValueError(code)
            terminal = parse_catalog_terminal_receipt(terminal.model_dump(mode='json'))
            bind_owner_terminal_receipt(owner=owner, receipt=terminal)
            if (
                profile.source_generation != 8
                or terminal.receipt_sha256 != profile.source_terminal_receipt_sha256
                or terminal.state != 'BLOCKED'
                or terminal.reason_code != 'CATALOG_REDUCTION_FAILED'
                or terminal.observed_recipe_count != 0
                or terminal.expected_recipe_count != profile.expected_total_count
                or terminal.result_science_sha256 is not None
            ):
                raise ValueError(code)
            expected_steps = dict.fromkeys(expected_steps, 'success')
        for name, conclusion in expected_steps.items():
            matching = [step for step in job['steps'] if step.get('name') == name]
            if len(matching) != 1 or (
                matching[0]['status'] != 'completed' or matching[0]['conclusion'] != conclusion
            ):
                raise ValueError(code)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(code) from exc
    return CheckpointRecoveryOwnerProofV1(
        profile_sha256=profile.profile_sha256,
        campaign_key=profile.campaign_key,
        target_generation=profile.target_generation,
        source_request_sha256=profile.source_request_sha256,
        source_issue_number=profile.source_issue_number,
        source_run_id=profile.source_run_id,
        source_run_attempt=profile.source_run_attempt,
        source_protected_commit_sha=profile.source_protected_commit_sha,
        source_decision_sha256=owner.decision.decision_sha256,
        source_finalizer_job_id=job['id'],
        evidence_kind='failed_owner_with_terminal' if terminal_recovery else 'failed_owner_without_terminal',
    )

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aurora.infra.sp500_megarun.catalog_runtime_audit import (
    build_catalog_runtime_audit,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
BINDING = {
    "request_sha256": "1" * 64,
    "authority_id": "018f47a2-6e91-7c34-8000-000000000001",
    "campaign_id": "2" * 64,
    "science_sha256": "3" * 64,
    "execution_plan_sha256": "4" * 64,
    "execution_protocol_sha256": "5" * 64,
    "protected_commit_sha": "6" * 40,
}


def _run() -> dict[str, object]:
    return {
        "id": 100,
        "run_attempt": 2,
        "head_sha": BINDING["protected_commit_sha"],
        "path": ".github/workflows/catalog-run-controller.yml",
        "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
    }


def _pages(root: str) -> list[dict[str, object]]:
    rows = (
        [
            {
                "id": 10,
                "name": "evaluate / worker 1",
                "labels": ["ubuntu-24.04"],
                "runner_group_name": "GitHub Actions",
            },
            {
                "id": 11,
                "name": "reduce",
                "labels": ["ubuntu-24.04"],
                "runner_group_name": "GitHub Actions",
            },
        ]
        if root == "jobs"
        else [{"id": 20, "name": "final", "expired": False, "size_in_bytes": 12}]
    )
    return [{root: rows}]


def _build(**updates: object):
    values = {
        "binding": BINDING,
        "run": _run(),
        "repository": {
            "full_name": "trading-optimizer-lab-org/aurora",
            "visibility": "public",
            "private": False,
        },
        "jobs_pages": _pages("jobs"),
        "jobs_confirmation_pages": _pages("jobs"),
        "artifacts_pages": _pages("artifacts"),
        "artifacts_confirmation_pages": _pages("artifacts"),
        "run_id": 100,
        "run_attempt": 2,
        "audited_at": NOW,
        "components_reused": 7,
        "components_computed_once": 5,
        "selective_retries": 1,
    }
    values.update(updates)
    return build_catalog_runtime_audit(**values)


def test_runtime_audit_proves_exact_commit_standard_free_runner_and_zero_cost() -> None:
    receipt = _build()
    assert receipt.protected_commit_sha == BINDING["protected_commit_sha"]
    assert receipt.standard_runner_only is True
    assert receipt.repository_visibility == "public"
    assert receipt.paid_runner_minutes == 0
    assert receipt.estimated_paid_actions_cost_microusd == 0
    assert receipt.components_reused == 7
    assert receipt.components_computed_once == 5


@pytest.mark.parametrize("label", ("self-hosted", "ubuntu-24.04-16core"))
def test_runtime_audit_rejects_any_unproven_runner(label: str) -> None:
    pages = _pages("jobs")
    pages[0]["jobs"][0]["labels"] = [label]
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_NONSTANDARD_RUNNER"):
        _build(jobs_pages=pages, jobs_confirmation_pages=pages)


def test_runtime_audit_rejects_incomplete_or_changing_pagination() -> None:
    confirmation = _pages("jobs")
    confirmation[0]["jobs"] = confirmation[0]["jobs"][:-1]
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_JOB_INVENTORY_UNSTABLE"):
        _build(jobs_confirmation_pages=confirmation)


def test_runtime_audit_rejects_wrong_commit_or_nonpublic_repository() -> None:
    run = _run()
    run["head_sha"] = "f" * 40
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_RUN_IDENTITY_INVALID"):
        _build(run=run)
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_RUN_IDENTITY_INVALID"):
        _build(
            repository={
                "full_name": "trading-optimizer-lab-org/aurora",
                "visibility": "private",
                "private": True,
            }
        )


def test_runtime_audit_accepts_only_proven_optional_skipped_job() -> None:
    pages = _pages("jobs")
    jobs = pages[0]["jobs"]
    assert isinstance(jobs, list)
    jobs.append({
        "id": 12, "name": "engine / build_components_b",
        "conclusion": "skipped", "labels": [],
    })
    receipt = _build(
        jobs_pages=pages, jobs_confirmation_pages=pages,
        allowed_skipped_job_names=frozenset({"engine / build_components_b"}),
    )
    assert receipt.job_ids == (10, 11, 12)


@pytest.mark.parametrize("labels", ([], ["ubuntu-24.04"]))
def test_runtime_audit_rejects_unapproved_skips_even_with_standard_labels(labels) -> None:
    pages = [{"jobs": [{
        "id": 12, "name": "engine / evaluate_a",
        "conclusion": "skipped", "labels": labels,
    }]}]
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_UNEXPECTED_SKIPPED_JOB"):
        _build(jobs_pages=pages, jobs_confirmation_pages=pages,
               allowed_skipped_job_names=frozenset({"engine / build_components_b"}))


def test_runtime_audit_does_not_excuse_executed_optional_job_without_runner() -> None:
    name = "engine / build_components_b"
    pages = [{"jobs": [{"id": 12, "name": name, "conclusion": "success", "labels": []}]}]
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_NONSTANDARD_RUNNER"):
        _build(jobs_pages=pages, jobs_confirmation_pages=pages,
               allowed_skipped_job_names=frozenset({name}))


def test_cancelled_run_cannot_excuse_a_required_evaluation() -> None:
    run = _run()
    run["conclusion"] = "cancelled"
    pages = [{"jobs": [{"id": 12, "name": "engine / evaluate_a", "conclusion": "skipped", "labels": []}]}]
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_UNEXPECTED_SKIPPED_JOB"):
        _build(run=run, jobs_pages=pages, jobs_confirmation_pages=pages,
               allowed_skipped_job_names=frozenset({"engine / build_components_b"}))


def test_optional_skip_requires_consistent_confirmation() -> None:
    name = "engine / build_components_b"
    pages = [{"jobs": [{"id": 12, "name": name, "conclusion": "skipped", "labels": []}]}]
    confirmation = [{"jobs": [{"id": 12, "name": name, "conclusion": "success", "labels": []}]}]
    with pytest.raises(ValueError, match="CATALOG_RUNTIME_AUDIT_JOB_INVENTORY_UNSTABLE"):
        _build(jobs_pages=pages, jobs_confirmation_pages=confirmation,
               allowed_skipped_job_names=frozenset({name}))

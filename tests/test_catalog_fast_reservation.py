from copy import deepcopy

import pytest

from aurora.infra.sp500_megarun.catalog_fast_reservation import verify_fast_gate_owner_metadata


COMMIT = "44d4f5e1bfe0d2d9396b99f44b4684205e737c0e"


def _metadata():
    # Shape and identifiers from the read-only run33910681070 observation.
    artifact = {
        "id": 9951225148, "name": "catalog-fast-gate-276", "size_in_bytes": 3487,
        "digest": "sha256:fc62dc8cf2807cb531c0996f77c21bc08e3d24effe775b074094fbfe400aae88",
        "expired": False, "created_at": "2026-09-04T19:21:04Z",
        "workflow_run": {"id": 33910681070, "head_sha": COMMIT, "head_branch": "main",
                         "repository_id": 1232647748, "head_repository_id": 1232647748},
    }
    run = {"id": 33910681070, "run_attempt": 1, "head_sha": COMMIT,
           "head_branch": "main", "path": ".github/workflows/catalog-fast-controller.yml",
           "event": "issues", "repository": {"id": 1232647748, "full_name": "trading-optimizer-lab-org/aurora"},
           "status": "completed", "conclusion": "failure"}
    jobs = [{"id": 101146103606, "run_id": run["id"], "run_attempt": 1,
             "head_sha": COMMIT, "name": "gate", "status": "completed", "conclusion": "success",
             "steps": [
                 {"name": "Publish the one gate decision", "number": 13, "status": "completed", "conclusion": "success",
                  "started_at": "2026-09-04T19:21:03Z", "completed_at": "2026-09-04T19:21:04Z"},
                 {"name": "Reserve the campaign atomically and expose QUEUED", "number": 15,
                  "status": "completed", "conclusion": "success",
                  "started_at": "2026-09-04T19:21:05Z", "completed_at": "2026-09-04T19:21:07Z"},
             ]}]
    return artifact, run, jobs


@pytest.mark.parametrize("mutation", (None, "unreserved", "wrong_attempt", "old_artifact", "foreign_repo", "wrong_commit", "ambiguous_gate", "expired"))
def test_owner_metadata_requires_exact_successful_reservation(mutation):
    artifact, run, jobs = _metadata()
    if mutation == "unreserved":
        jobs[0]["steps"][1]["conclusion"] = "failure"
    elif mutation == "wrong_attempt":
        jobs[0]["run_attempt"] = 2
    elif mutation == "old_artifact":
        artifact["created_at"] = "2026-09-03T19:21:04Z"
    elif mutation == "foreign_repo":
        run["repository"]["full_name"] = "other/aurora"
    elif mutation == "wrong_commit":
        run["head_sha"] = "b" * 40
    elif mutation == "ambiguous_gate":
        jobs.append(deepcopy(jobs[0]))
    elif mutation == "expired":
        artifact["expired"] = True
    if mutation is None:
        assert verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
            expected_issue_number=276, expected_commit=COMMIT) == 33910681070
        # Ownership exists even though the scientific run failed; no SUCCESS is returned.
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_PROVENANCE_INVALID"):
            verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
                expected_issue_number=276, expected_commit=COMMIT)


@pytest.mark.parametrize("mutation", (None, "missing_reference", "wrong_sha", "wrong_ref", "wrong_job", "foreign_caller"))
def test_reconciler_owner_requires_exact_reusable_binding(mutation):
    artifact, run, jobs = _metadata()
    run["path"] = ".github/workflows/catalog-request-reconciler.yml"
    run["event"] = "schedule"
    run["referenced_workflows"] = [{
        "path": f"trading-optimizer-lab-org/aurora/.github/workflows/catalog-fast-controller.yml@{COMMIT}",
        "sha": COMMIT, "ref": "refs/heads/main",
    }]
    jobs[0]["name"] = "catalog-request-276 / gate"
    if mutation == "missing_reference":
        run["referenced_workflows"] = []
    elif mutation == "wrong_sha":
        run["referenced_workflows"][0]["sha"] = "b" * 40
    elif mutation == "wrong_ref":
        run["referenced_workflows"][0]["ref"] = "refs/heads/other"
    elif mutation == "wrong_job":
        jobs[0]["name"] = "catalog-request-277 / gate"
    elif mutation == "foreign_caller":
        run["path"] = ".github/workflows/other.yml"
    if mutation is None:
        assert verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
            expected_issue_number=276, expected_commit=COMMIT) == 33910681070
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_PROVENANCE_INVALID"):
            verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
                expected_issue_number=276, expected_commit=COMMIT)


@pytest.mark.parametrize("mutation", [None, "lost_upload_response", "failed_verification", "missing_upload", "early_verification"])
def test_failed_gate_retains_only_a_verified_durable_reservation(mutation):
    artifact, run, jobs = _metadata()
    gate = jobs[0]
    gate["conclusion"] = "failure"
    gate["steps"][1].update(number=19, conclusion="failure", started_at="2026-09-04T19:21:11Z", completed_at="2026-09-04T19:21:12Z")
    gate["steps"] += [
        {"name": name, "number": number, "status": "completed", "conclusion": "success",
         "started_at": f"2026-09-04T19:21:{start:02}Z", "completed_at": f"2026-09-04T19:21:{start + 1:02}Z"}
        for name, number, start in [("Write current authority edition", 16, 5),
            ("Publish current authority edition", 17, 7),
            ("Verify the uploaded reservation before exposing QUEUED", 18, 9)]
    ]
    if mutation == "failed_verification":
        gate["steps"][-1]["conclusion"] = "failure"
    elif mutation == "lost_upload_response":
        gate["steps"][-2]["conclusion"] = "failure"
    elif mutation == "missing_upload":
        gate["steps"].pop(-2)
    elif mutation == "early_verification":
        gate["steps"][-1]["started_at"] = "2026-09-04T19:21:02Z"
    if mutation in {None, "lost_upload_response"}:
        assert verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
            expected_issue_number=276, expected_commit=COMMIT) == 33910681070
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_OWNER_PROVENANCE_INVALID"):
            verify_fast_gate_owner_metadata(artifact=artifact, run=run, jobs=jobs,
                expected_issue_number=276, expected_commit=COMMIT)

"""Only GitHub transport is replaced; signatures and owner verifiers are real."""
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from types import SimpleNamespace
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogFastLaunchDecisionV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.bootstrap_catalog_fast_authority import build_bootstrap_candidate
from tests.test_inspect_catalog_fast_request import _signed_request
from tests.test_catalog_fast_reservation import _metadata, COMMIT


def bootstrap_transport(case="valid"):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    rows, previous = [], None
    origin = datetime(2026, 9, 4, 18, 20, tzinfo=timezone.utc)
    for generation in range(1, 7):
        title, body = _signed_request(private, request_id=f"018f47a2-6e91-7c34-8000-{generation:012d}", launch_generation=generation, previous_terminal_request_sha256=previous)
        request = parse_catalog_run_request(title, body, public)
        previous = request.request_sha256
        created = origin + timedelta(minutes=generation * 10)
        rows.append({"number":270 + generation, "node_id":f"issue-{generation}", "title":title, "body":body,
                     "user":{"login":"requester"}, "state":"closed", "state_reason":"completed",
                     "closed_by":{"login":"github-actions[bot]"}, "labels":[{"name":"catalog-run-terminal-v1"}],
                     "created_at":created.isoformat(), "closed_at":(created + timedelta(minutes=2)).isoformat()})
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    decision = CatalogFastLaunchDecisionV1.create(
        state="QUEUED", reason_code="CATALOG_FAST_PATH_ADMITTED", request_sha256=request.request_sha256,
        submission_key_sha256=request.submission_key_sha256, campaign_key=request.campaign_key,
        prepared_receipt_sha256="b" * 64, selected_workers=1, launch_required=True, existing_run_id=None,
        decided_at=created, expires_at=created + timedelta(minutes=30),
    )
    context = {"issue_number":276, "request":request.model_dump(mode="json")}
    context["content_sha256"] = canonical_sha256(context)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("catalog-fast-request-context.json", json.dumps(context))
        archive.writestr("catalog-fast-decision-v1.json", decision.model_dump_json())
    raw = stream.getvalue()
    artifact, run, jobs = _metadata()
    artifact["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    artifact["size_in_bytes"] = len(raw)
    if case == "wrong_closer":
        rows[-1]["closed_by"] = {"login":"not-authorized"}
    if case == "active":
        rows[-1]["state"] = "open"
    if case == "closure_before_reservation":
        rows[-1]["closed_at"] = "2026-09-04T19:20:30Z"

    class Reader:
        repository = "trading-optimizer-lab-org/aurora"
        observed_at = now

        def stable_paginated(self, path, *, root):
            if "actions/artifacts?name=" in path:
                found = [] if case == "missing_owner" else [artifact]
            elif path.endswith("/jobs"):
                found = jobs
            elif "/issues?" in path:
                found = rows
            else:
                raise AssertionError(path)
            return SimpleNamespace(stable=True, collection=SimpleNamespace(complete=case != "incomplete", rows=tuple(found)))

        def get_json(self, path):
            if "/actions/runs/" in path:
                return run, {}
            return next(row for row in rows if str(row["number"]) == path.rsplit("/", 1)[-1]), {}

    args = dict(client=Reader(), public_key=public, request_actors=frozenset({"requester"}),
                ledger_actor="github-actions[bot]", campaign_key=request.campaign_key,
                expected_tail_sha256="f" * 64 if case == "wrong_tail" else request.request_sha256,
                approved_commits=frozenset({COMMIT}), download_archive=lambda artifact_id: raw)
    return args


@pytest.mark.parametrize("case", ["valid", "wrong_tail", "wrong_closer", "missing_owner", "incomplete", "active", "closure_before_reservation"])
def test_bootstrap_reads_signed_chain_and_owner_without_scientific_success(case):
    args = bootstrap_transport(case)
    if case != "valid":
        with pytest.raises(ValueError, match="CATALOG_"):
            build_bootstrap_candidate(**args)
        return
    candidate = build_bootstrap_candidate(**args)
    assert candidate.campaigns[0].generation == 6
    assert candidate.campaigns[0].owner_issue_number == 276
    assert candidate.campaigns[0].owner_run_id == 33910681070
    assert candidate.campaigns[0].terminal_receipt_sha256 is None
    assert candidate.campaigns[0].legacy_closure_evidence_sha256 is not None
    assert candidate.revision == 1

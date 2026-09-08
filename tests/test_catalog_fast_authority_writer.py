"""One mutation with read-back reconciliation; never retry an ambiguous write."""

import json

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import verify_authority_edit
from tests.test_catalog_fast_authority_github import publication_transport
from tests.test_catalog_fast_path import _request


@pytest.mark.parametrize("fault", [None, "response_lost", "write_rejected", "stale_edit", "wrong_readback"])
def test_writer_commits_once_or_stops_without_resetting_state(fault):
    from aurora.infra.sp500_megarun.catalog_fast_authority_github import write_current_fast_authority

    fixture = publication_transport()
    current = fixture.state
    candidate = current.reserve(request=_request(), issue_number=280, run_id=123)
    issue = fixture.edit["data"]["repository"]["issue"]
    if fault == "stale_edit":
        issue["userContentEdits"]["nodes"][0]["id"] = "E_other"
    writes = []

    def write_body(body):
        writes.append(body)
        if fault == "write_rejected":
            raise OSError("transport refused")
        issue["body"] = body if fault != "wrong_readback" else "changed externally"
        issue["lastEditedAt"] = "2026-09-05T12:01:00Z"
        issue["userContentEdits"]["nodes"][0].update(id="E_written", editedAt=issue["lastEditedAt"])
        if fault == "response_lost":
            raise TimeoutError("response lost after commit")

    def write():
        return write_current_fast_authority(current=current, candidate=candidate,
            expected_edit_id="E_current", anchor=fixture.anchor,
            run_id=123, run_attempt=1, job_id=789, phase="gate", commit="a" * 40,
            read_edit=lambda: json.loads(json.dumps(fixture.edit)), write_body=write_body)

    if fault in {None, "response_lost"}:
        publication = write()
        reopened = verify_authority_edit(body=candidate.to_body(), publication_json=publication.model_dump_json(),
            issue_node_id="I_anchor", latest_edit_node_id="E_written")
        assert reopened.revision == 2
        assert reopened.campaigns[0].owner_run_id == 123
        assert len(writes) == 1
        assert issue["body"].startswith(candidate.to_body() + "\n<!-- AURORA_FAST_PUBLICATION:")
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_"):
            write()
        assert len(writes) == (0 if fault == "stale_edit" else 1)


@pytest.mark.parametrize("approved", [True, False])
def test_lineage_writer_rechecks_approval_and_production_reader_reopens_bytes(approved):
    from aurora.infra.sp500_megarun.catalog_fast_authority_github import (
        load_current_fast_authority, write_current_fast_authority,
    )
    from tests.test_catalog_fast_authority import _lineage_boundary

    current, request, approval = _lineage_boundary()
    candidate = current.reserve(request=request, issue_number=280, run_id=123,
                                lineage_transition=approval)
    fixture = publication_transport(state=current)
    issue = fixture.edit["data"]["repository"]["issue"]
    writes = []

    def write_body(body):
        writes.append(body)
        issue["body"] = body
        issue["userContentEdits"]["nodes"][0]["id"] = "E_written"

    def publish():
        return write_current_fast_authority(
            current=current, candidate=candidate, expected_edit_id="E_current",
            anchor=fixture.anchor, run_id=123, run_attempt=1, job_id=789,
            phase="gate", commit="a" * 40, read_edit=lambda: fixture.edit,
            write_body=write_body, lineage_transition=approval if approved else None,
        )

    if not approved:
        with pytest.raises(ValueError, match="LINEAGE_CHANGE_REQUIRES_MAINTENANCE"):
            publish()
        assert writes == []
        return
    publication = publish()
    uploaded = publication_transport(
        state=candidate, phase="gate", edit_id="E_written",
        publication_bytes=publication.model_dump_json(),
    )
    assert writes == [uploaded.edit["data"]["repository"]["issue"]["body"]]
    reopened = load_current_fast_authority(
        client=uploaded.client, anchor=uploaded.anchor, protected_commit="a" * 40,
        read_edit=lambda: uploaded.edit, download_archive=lambda _: uploaded.raw,
    )
    assert reopened == candidate
    assert reopened.previous_state_sha256 == current.state_sha256
    assert reopened.campaigns[0].generation == 7

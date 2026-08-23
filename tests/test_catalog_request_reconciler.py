from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import UUID

from aurora.infra.sp500_megarun.catalog_request_receipt import (
    CatalogRequestReceiptV1,
)
from aurora.infra.sp500_megarun.catalog_request_reconciler import (
    select_catalog_request_reconciliation_candidates,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
REPOSITORY = "trading-optimizer-lab-org/aurora"


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _issue(number: int, *, terminal: bool = False) -> dict[str, object]:
    return {
        "id": 10_000 + number,
        "number": number,
        "title": (
            "[AURORA CATALOG RUN REQUEST] "
            f"018f47a2-6e91-7c34-8000-{number:012d}"
        ),
        "state": "open",
        "labels": ([{"name": "catalog-run-terminal-v1"}] if terminal else []),
    }


def _receipt(
    issue_number: int,
    *,
    state: str,
    reason_code: str,
    retry_not_before: datetime | None,
) -> CatalogRequestReceiptV1:
    summary = f"Estado controlado de la solicitud {issue_number}."
    payload = {
        "schema_version": "1",
        "marker": "AURORA_CATALOG_REQUEST_RECEIPT_V1",
        "state": state,
        "reason_code": reason_code,
        "issue_number": issue_number,
        "delivery_sequence": 0,
        "request_sha256": f"{issue_number:064x}"[-64:],
        "authority_id": None,
        "campaign_id": "c" * 64,
        "terminal_decision_sha256": None,
        "authority_record_sha256": None,
        "writer_run_id": issue_number,
        "writer_run_attempt": 1,
        "writer_job_id": "report_nonexecuting_decision",
        "writer_job_database_id": 20_000 + issue_number,
        "protected_commit_sha": "a" * 40,
        "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "retry_not_before": (
            retry_not_before.isoformat().replace("+00:00", "Z")
            if retry_not_before is not None
            else None
        ),
    }
    payload["receipt_sha256"] = _sha256(payload)
    return CatalogRequestReceiptV1.model_validate(payload)


def _comment(receipt: CatalogRequestReceiptV1) -> dict[str, object]:
    summary = f"Estado controlado de la solicitud {receipt.issue_number}."
    return {
        "id": 30_000 + receipt.issue_number,
        "issue_url": (
            f"https://api.github.com/repos/{REPOSITORY}/issues/"
            f"{receipt.issue_number}"
        ),
        "body": receipt.comment_body(summary),
        "user": {"login": "github-actions[bot]"},
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def _select(
    issues: list[dict[str, object]],
    comments: list[dict[str, object]] | None = None,
):
    return select_catalog_request_reconciliation_candidates(
        repository=REPOSITORY,
        issues=issues,
        comments=comments or [],
        terminal_label="catalog-run-terminal-v1",
        observed_at=NOW,
        source_sha256="f" * 64,
    )


def test_reconciler_selects_fifo_and_bounds_each_wave_to_ninety() -> None:
    plan = _select([_issue(number) for number in range(101, 0, -1)])
    assert plan.issue_numbers == tuple(range(1, 91))
    assert plan.has_candidates is True
    assert plan.matrix == {
        "include": [{"issue_number": number} for number in range(1, 91)]
    }


def test_reconciler_skips_terminal_nonrequests_and_pull_requests() -> None:
    terminal = _issue(1, terminal=True)
    unrelated = _issue(2)
    unrelated["title"] = "ordinary issue"
    pull_request = _issue(3)
    pull_request["pull_request"] = {"url": "https://example.invalid/pr/3"}
    plan = _select([terminal, unrelated, pull_request, _issue(4)])
    assert plan.issue_numbers == (4,)


def test_reconciler_honours_deferred_deadline_and_replays_when_due() -> None:
    future = _receipt(
        1,
        state="DEFERRED",
        reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
        retry_not_before=NOW + timedelta(minutes=5),
    )
    due = _receipt(
        2,
        state="DEFERRED",
        reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
        retry_not_before=NOW - timedelta(seconds=1),
    )
    plan = _select([_issue(1), _issue(2)], [_comment(future), _comment(due)])
    assert plan.issue_numbers == (2,)


def test_reconciler_leaves_adopted_and_waiting_retry_work_to_watchdog() -> None:
    adopted = _receipt(
        1,
        state="DEFERRED",
        reason_code="CATALOG_ADOPTED_WAITING_FOR_EXISTING",
        retry_not_before=None,
    )
    waiting = _receipt(
        2,
        state="WAITING_RETRY",
        reason_code="PROVIDER_429",
        retry_not_before=NOW - timedelta(seconds=1),
    ).model_copy(
        update={
            "authority_id": UUID("018f47a2-6e91-7c34-8000-000000000001"),
            "authority_record_sha256": "d" * 64,
        }
    )
    # The copied object is used only to exercise scheduling semantics; its
    # canonical hash is rebuilt before rendering a trusted comment.
    payload = waiting.model_dump(mode="json", exclude={"receipt_sha256"})
    payload["receipt_sha256"] = _sha256(payload)
    waiting = CatalogRequestReceiptV1.model_validate(payload)
    plan = _select([_issue(1), _issue(2)], [_comment(adopted), _comment(waiting)])
    assert plan.issue_numbers == ()


def test_invalid_or_untrusted_receipt_never_suppresses_reconciliation() -> None:
    receipt = _receipt(
        1,
        state="DEFERRED",
        reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
        retry_not_before=NOW + timedelta(days=1),
    )
    untrusted = _comment(receipt)
    untrusted["user"] = {"login": "human"}
    malformed = _comment(receipt)
    malformed["id"] = 99_999
    malformed["body"] = str(malformed["body"]) + "tamper"
    plan = _select([_issue(1)], [untrusted, malformed])
    assert plan.issue_numbers == (1,)

"""Bounded FIFO replay selection for already-existing catalog requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .catalog_request_contract import FrozenModel, Sha256
from .catalog_request_receipt import (
    REQUEST_RECEIPT_MARKER,
    CatalogRequestReceiptV1,
    parse_request_receipt_comment,
)


_REQUEST_TITLE = re.compile(
    r"^\[AURORA CATALOG RUN REQUEST\] [0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class CatalogRequestReconciliationPlanV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    issue_numbers: tuple[int, ...]
    observed_at: datetime
    source_sha256: Sha256
    plan_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_RECONCILER_TIME_INVALID")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogRequestReconciliationPlanV1":
        if (
            len(self.issue_numbers) > 90
            or self.issue_numbers != tuple(sorted(set(self.issue_numbers)))
            or any(number < 1 for number in self.issue_numbers)
        ):
            raise ValueError("CATALOG_RECONCILER_MATRIX_INVALID")
        identity = self.model_dump(mode="json", exclude={"plan_sha256"})
        if _canonical_sha256(identity) != self.plan_sha256:
            raise ValueError("CATALOG_RECONCILER_PLAN_HASH_INVALID")
        return self

    @property
    def has_candidates(self) -> bool:
        return bool(self.issue_numbers)

    @property
    def matrix(self) -> dict[str, list[dict[str, int]]]:
        return {
            "include": [
                {"issue_number": number} for number in self.issue_numbers
            ]
        }


def _mapping(value: object, reason: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(reason)
    return value


def _issue_number_from_comment(
    comment: Mapping[str, object], *, repository: str
) -> int | None:
    issue_url = comment.get("issue_url")
    prefix = f"https://api.github.com/repos/{repository}/issues/"
    if not isinstance(issue_url, str) or not issue_url.startswith(prefix):
        return None
    suffix = issue_url.removeprefix(prefix)
    if not suffix.isdigit() or int(suffix) < 1:
        return None
    return int(suffix)


def _label_names(issue: Mapping[str, object]) -> frozenset[str]:
    labels = issue.get("labels")
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
        raise ValueError("CATALOG_RECONCILER_ISSUE_INVALID")
    names: set[str] = set()
    for raw in labels:
        if isinstance(raw, str):
            name = raw
        else:
            label = _mapping(raw, "CATALOG_RECONCILER_ISSUE_INVALID")
            name = label.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("CATALOG_RECONCILER_ISSUE_INVALID")
        names.add(name)
    return frozenset(names)


def _should_replay(
    *,
    receipt: CatalogRequestReceiptV1 | None,
    observed_at: datetime,
    receipt_history_invalid: bool,
) -> bool:
    if receipt_history_invalid or receipt is None:
        return True
    if receipt.state == "WAITING_RETRY":
        return False
    if (
        receipt.state == "DEFERRED"
        and receipt.reason_code == "CATALOG_ADOPTED_WAITING_FOR_EXISTING"
    ):
        return False
    if receipt.state == "DEFERRED":
        return receipt.retry_not_before is None or receipt.retry_not_before <= observed_at
    return True


def select_catalog_request_reconciliation_candidates(
    *,
    repository: str,
    issues: Sequence[object],
    comments: Sequence[object],
    terminal_label: str,
    observed_at: datetime,
    source_sha256: str,
) -> CatalogRequestReconciliationPlanV1:
    """Select at most 90 due open requests; never creates or validates science."""

    if (
        not _REPOSITORY.fullmatch(repository)
        or not terminal_label
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise ValueError("CATALOG_RECONCILER_INPUT_INVALID")
    observed_at = observed_at.astimezone(UTC)

    comments_by_issue: dict[int, list[CatalogRequestReceiptV1]] = {}
    invalid_receipt_issues: set[int] = set()
    seen_comment_ids: set[int] = set()
    for raw_comment in comments:
        comment = _mapping(raw_comment, "CATALOG_RECONCILER_COMMENT_INVALID")
        comment_id = comment.get("id")
        if (
            isinstance(comment_id, bool)
            or not isinstance(comment_id, int)
            or comment_id < 1
            or comment_id in seen_comment_ids
        ):
            raise ValueError("CATALOG_RECONCILER_COMMENT_INVALID")
        seen_comment_ids.add(comment_id)
        number = _issue_number_from_comment(comment, repository=repository)
        if number is None:
            continue
        body = comment.get("body")
        trusted_marker = (
            isinstance(body, str)
            and REQUEST_RECEIPT_MARKER in body
            and isinstance(comment.get("user"), Mapping)
            and comment["user"].get("login") == "github-actions[bot]"
        )
        try:
            receipt = parse_request_receipt_comment(comment)
        except ValueError:
            if trusted_marker:
                invalid_receipt_issues.add(number)
            continue
        if receipt is None:
            continue
        if receipt.issue_number != number:
            invalid_receipt_issues.add(number)
            continue
        comments_by_issue.setdefault(number, []).append(receipt)

    candidates: list[int] = []
    seen_issue_ids: set[int] = set()
    seen_issue_numbers: set[int] = set()
    for raw_issue in issues:
        issue = _mapping(raw_issue, "CATALOG_RECONCILER_ISSUE_INVALID")
        issue_id = issue.get("id")
        number = issue.get("number")
        if (
            isinstance(issue_id, bool)
            or not isinstance(issue_id, int)
            or issue_id < 1
            or issue_id in seen_issue_ids
            or isinstance(number, bool)
            or not isinstance(number, int)
            or number < 1
            or number in seen_issue_numbers
        ):
            raise ValueError("CATALOG_RECONCILER_ISSUE_INVALID")
        seen_issue_ids.add(issue_id)
        seen_issue_numbers.add(number)
        if "pull_request" in issue or issue.get("state") != "open":
            continue
        title = issue.get("title")
        if not isinstance(title, str) or not _REQUEST_TITLE.fullmatch(title):
            continue
        if terminal_label in _label_names(issue):
            continue
        history = comments_by_issue.get(number, [])
        latest = (
            max(
                history,
                key=lambda item: (
                    item.created_at,
                    item.writer_run_id,
                    item.writer_run_attempt,
                    item.receipt_sha256,
                ),
            )
            if history
            else None
        )
        if _should_replay(
            receipt=latest,
            observed_at=observed_at,
            receipt_history_invalid=number in invalid_receipt_issues,
        ):
            candidates.append(number)

    issue_numbers = tuple(sorted(candidates)[:90])
    identity = {
        "schema_version": "1",
        "issue_numbers": list(issue_numbers),
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "source_sha256": source_sha256,
    }
    return CatalogRequestReconciliationPlanV1(
        **identity,
        plan_sha256=_canonical_sha256(identity),
    )


__all__ = [
    "CatalogRequestReconciliationPlanV1",
    "select_catalog_request_reconciliation_candidates",
]

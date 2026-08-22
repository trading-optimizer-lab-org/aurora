from __future__ import annotations

from email.message import Message
import json

import pytest

from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
    GitHubGetResponse,
)


API = "https://api.github.com"


def _headers(**values: str) -> Message:
    result = Message()
    result["Date"] = "Fri, 21 Aug 2026 10:00:00 GMT"
    result["ETag"] = '"etag"'
    for key, value in values.items():
        result[key.replace("_", "-")] = value
    return result


def _response(url: str, payload: object, *, link: str = "") -> GitHubGetResponse:
    headers = _headers()
    if link:
        headers["Link"] = link
    return GitHubGetResponse(
        status=200,
        requested_url=url,
        final_url=url,
        headers=headers,
        body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    )


class _Transport:
    def __init__(self, responses: dict[str, list[GitHubGetResponse]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, headers: dict[str, str]) -> GitHubGetResponse:
        del headers
        self.calls.append(url)
        available = self.responses.get(url)
        if not available:
            raise AssertionError(f"unexpected GET: {url}")
        return available.pop(0)


def test_pagination_follows_same_origin_links_and_records_all_248_ids() -> None:
    first = f"{API}/repos/o/r/issues/7/comments?per_page=100"
    second = f"{API}/repos/o/r/issues/7/comments?page=2&per_page=100"
    third = f"{API}/repos/o/r/issues/7/comments?page=3&per_page=100"
    transport = _Transport(
        {
            first: [
                _response(
                    first,
                    [{"id": value} for value in range(1, 101)],
                    link=f'<{second}>; rel="next"',
                )
            ],
            second: [
                _response(
                    second,
                    [{"id": value} for value in range(101, 201)],
                    link=f'<{third}>; rel="next"',
                )
            ],
            third: [_response(third, [{"id": value} for value in range(201, 249)])],
        }
    )
    client = CatalogGitHubReadOnlyClient("o/r", "token", transport=transport)

    collection = client.paginated("/repos/o/r/issues/7/comments", root="list")

    assert len(collection.rows) == 248
    assert collection.ordered_ids == tuple(range(1, 249))
    assert collection.complete is True
    assert len(collection.pages) == 3


def test_pagination_rejects_duplicate_ids_and_cross_origin_next_link() -> None:
    url = f"{API}/repos/o/r/issues/7/comments?per_page=100"
    duplicate = _Transport({url: [_response(url, [{"id": 1}, {"id": 1}])]})
    with pytest.raises(CatalogGitHubSnapshotError, match="DUPLICATE_ID"):
        CatalogGitHubReadOnlyClient(
            "o/r", "token", transport=duplicate
        ).paginated("/repos/o/r/issues/7/comments", root="list")

    evil = _Transport(
        {
            url: [
                _response(
                    url,
                    [{"id": 1}],
                    link='<https://evil.example/page=2>; rel="next"',
                )
            ]
        }
    )
    with pytest.raises(CatalogGitHubSnapshotError, match="PAGINATION_ORIGIN"):
        CatalogGitHubReadOnlyClient(
            "o/r", "token", transport=evil
        ).paginated("/repos/o/r/issues/7/comments", root="list")


def test_stable_issue_collection_retries_twice_then_accepts_third_attempt() -> None:
    issue_url = f"{API}/repos/o/r/issues/7"
    comments_url = f"{API}/repos/o/r/issues/7/comments?per_page=100"
    changed = {"id": 7, "comments": 1, "updated_at": "2026-08-21T10:00:01Z"}
    original = {"id": 7, "comments": 1, "updated_at": "2026-08-21T10:00:00Z"}
    transport = _Transport(
        {
            issue_url: [
                _response(issue_url, original),
                _response(issue_url, changed),
                _response(issue_url, original),
                _response(issue_url, changed),
                _response(issue_url, original),
                _response(issue_url, original),
            ],
            comments_url: [
                _response(comments_url, [{"id": 1}]),
                _response(comments_url, [{"id": 1}]),
                _response(comments_url, [{"id": 1}]),
            ],
        }
    )
    client = CatalogGitHubReadOnlyClient("o/r", "token", transport=transport)

    stable = client.stable_issue_collection(
        issue_path="/repos/o/r/issues/7",
        collection_path="/repos/o/r/issues/7/comments",
        root="list",
        count_field="comments",
    )

    assert stable.attempt == 3
    assert stable.stable is True
    assert stable.collection.ordered_ids == (1,)


def test_stable_issue_collection_blocks_after_three_complete_unstable_reads() -> None:
    issue_url = f"{API}/repos/o/r/issues/7"
    comments_url = f"{API}/repos/o/r/issues/7/comments?per_page=100"
    responses = []
    for attempt in range(3):
        responses.extend(
            [
                _response(
                    issue_url,
                    {"id": 7, "comments": 0, "updated_at": f"2026-08-21T10:00:0{attempt}Z"},
                ),
                _response(
                    issue_url,
                    {"id": 7, "comments": 0, "updated_at": f"2026-08-21T10:00:1{attempt}Z"},
                ),
            ]
        )
    transport = _Transport(
        {
            issue_url: responses,
            comments_url: [_response(comments_url, []) for _ in range(3)],
        }
    )
    client = CatalogGitHubReadOnlyClient("o/r", "token", transport=transport)

    with pytest.raises(CatalogGitHubSnapshotError, match="SNAPSHOT_UNSTABLE"):
        client.stable_issue_collection(
            issue_path="/repos/o/r/issues/7",
            collection_path="/repos/o/r/issues/7/comments",
            root="list",
            count_field="comments",
        )


def test_stable_paginated_inventory_retries_until_two_complete_reads_match() -> None:
    url = f"{API}/repos/o/r/issues?per_page=100"
    transport = _Transport(
        {
            url: [
                _response(url, [{"id": 1}]),
                _response(url, [{"id": 2}]),
                _response(url, [{"id": 2}]),
                _response(url, [{"id": 2}]),
            ]
        }
    )
    client = CatalogGitHubReadOnlyClient("o/r", "token", transport=transport)

    stable = client.stable_paginated("/repos/o/r/issues", root="list")

    assert stable.attempt == 2
    assert stable.collection.ordered_ids == (2,)


def test_rate_limit_or_redirect_uncertainty_fails_closed() -> None:
    url = f"{API}/repos/o/r"
    limited = GitHubGetResponse(
        status=403,
        requested_url=url,
        final_url=url,
        headers=_headers(X_RateLimit_Remaining="0", Retry_After="120"),
        body=b"{}",
    )
    with pytest.raises(CatalogGitHubSnapshotError, match="RATE_LIMIT"):
        CatalogGitHubReadOnlyClient(
            "o/r", "token", transport=_Transport({url: [limited]})
        ).get_json("/repos/o/r")

    redirected = GitHubGetResponse(
        status=200,
        requested_url=url,
        final_url=f"{API}/repositories/1",
        headers=_headers(),
        body=b"{}",
    )
    with pytest.raises(CatalogGitHubSnapshotError, match="REDIRECT"):
        CatalogGitHubReadOnlyClient(
            "o/r", "token", transport=_Transport({url: [redirected]})
        ).get_json("/repos/o/r")

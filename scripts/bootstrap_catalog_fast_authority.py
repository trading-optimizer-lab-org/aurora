#!/usr/bin/env python3
"""Read-only maintenance import; never publish authority or launch a campaign."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityCampaignV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence, load_fast_gate_owner
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.admit_catalog_fast_request import _download_owner_archive, _historical_owner_commit_approved


REPOSITORY = "trading-optimizer-lab-org/aurora"


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("CATALOG_BOOTSTRAP_TIME_INVALID")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("CATALOG_BOOTSTRAP_TIME_INVALID")
    return result


def build_bootstrap_candidate(
    *, client: CatalogGitHubReadOnlyClient, public_key: bytes,
    request_actors: frozenset[str], ledger_actor: str, campaign_key: str,
    expected_tail_sha256: str, approved_commits: frozenset[str],
    download_archive: Callable[[int], bytes],
    approve_historical_commit: Callable[[str], bool] | None = None,
) -> FastAuthorityStateV1:
    if (client.repository != REPOSITORY or not request_actors or not ledger_actor
            or not re.fullmatch(r"[0-9a-f]{64}", expected_tail_sha256)):
        raise ValueError("CATALOG_BOOTSTRAP_INVOCATION_INVALID")
    inventory = client.stable_paginated(f"/repos/{REPOSITORY}/issues?state=all", root="list")
    if inventory.stable is not True or inventory.collection.complete is not True:
        raise ValueError("CATALOG_BOOTSTRAP_HISTORY_INCOMPLETE")
    records = []
    for row in inventory.collection.rows:
        actor = row.get("user")
        if not isinstance(actor, Mapping) or actor.get("login") not in request_actors:
            continue
        if not str(row.get("title", "")).startswith("[AURORA CATALOG RUN REQUEST] "):
            continue
        request = parse_catalog_run_request(row.get("title"), row.get("body"), public_key)
        if request.campaign_key != campaign_key:
            continue
        ticket = CatalogLaunchTicketV1(
            schema_version="1",
            request_id=request.request_id, campaign_key=request.campaign_key,
            launch_generation=request.launch_generation,
            campaign_definition_sha256=request.campaign_definition_sha256,
            prompt_sha256=request.prompt_sha256,
            previous_terminal_request_sha256=request.previous_terminal_request_sha256,
        )
        if ticket.launch_ticket_sha256 != request.launch_ticket_sha256:
            raise ValueError("CATALOG_BOOTSTRAP_TICKET_INVALID")
        records.append((request, row))
    records.sort(key=lambda pair: pair[0].launch_generation)
    if not records or [request.launch_generation for request, _ in records] != list(range(1, len(records) + 1)):
        raise ValueError("CATALOG_BOOTSTRAP_HISTORY_CHAIN_INVALID")
    if records[-1][0].request_sha256 != expected_tail_sha256:
        raise ValueError("CATALOG_BOOTSTRAP_TAIL_CHANGED")
    if len({request.request_id for request, _ in records}) != len(records):
        raise ValueError("CATALOG_BOOTSTRAP_HISTORY_CHAIN_INVALID")
    closures: list[Mapping[str, Any]] = []
    previous_hash = None
    previous_closed = None
    previous_number = 0
    lineage = (records[0][0].campaign_definition_sha256, records[0][0].prompt_sha256)
    for request, row in records:
        number = row.get("number")
        if (type(number) is not int or number <= previous_number
                or request.previous_terminal_request_sha256 != previous_hash
                or (request.campaign_definition_sha256, request.prompt_sha256) != lineage):
            raise ValueError("CATALOG_BOOTSTRAP_HISTORY_CHAIN_INVALID")
        issue, _ = client.get_json(f"/repos/{REPOSITORY}/issues/{number}")
        if not isinstance(issue, Mapping):
            raise ValueError("CATALOG_BOOTSTRAP_CLOSURE_INVALID")
        closer, actor = issue.get("closed_by"), issue.get("user")
        if (issue.get("number") != number or not issue.get("node_id")
                or issue.get("state") != "closed" or issue.get("state_reason") != "completed"
                or not isinstance(closer, Mapping) or closer.get("login") != ledger_actor
                or not isinstance(actor, Mapping) or actor.get("login") not in request_actors
                or "catalog-run-terminal-v1" not in {label.get("name") for label in issue.get("labels", ()) if isinstance(label, Mapping)}
                or parse_catalog_run_request(issue.get("title"), issue.get("body"), public_key) != request):
            raise ValueError("CATALOG_BOOTSTRAP_CLOSURE_INVALID")
        created, closed = _time(issue.get("created_at")), _time(issue.get("closed_at"))
        if (client.observed_at is None or not created <= closed <= client.observed_at
                or (previous_closed is not None and created < previous_closed)):
            raise ValueError("CATALOG_BOOTSTRAP_CLOSURE_INVALID")
        closures.append({"issue_node_id":issue["node_id"], "issue_number":number,
                         "request_sha256":request.request_sha256, "closed_at":closed.isoformat(), "closed_by":ledger_actor})
        previous_hash, previous_closed, previous_number = request.request_sha256, closed, number
    request, row = records[-1]
    owner = load_fast_gate_owner(
        client=client, issue_number=row["number"], request=request,
        approved_commits=approved_commits, download_archive=download_archive,
        approve_historical_commit=approve_historical_commit,
    )
    if not isinstance(owner, FastGateOwnerEvidence) or owner.run.get("status") != "completed":
        raise ValueError("CATALOG_BOOTSTRAP_OWNER_UNVERIFIED")
    gate_name = ("gate" if owner.run.get("path") == ".github/workflows/catalog-fast-controller.yml"
                 else f"catalog-request-{row['number']} / gate")
    reservations = [step for job in owner.jobs if job.get("name") == gate_name
                    for step in job.get("steps", ())
                    if step.get("name") == "Reserve the campaign atomically and expose QUEUED"]
    if len(reservations) != 1 or not created <= _time(reservations[0].get("completed_at")) <= closed:
        raise ValueError("CATALOG_BOOTSTRAP_CLOSURE_BEFORE_RESERVATION")
    evidence_hash = canonical_sha256({"closures":closures, "owner_run_id":owner.run_id,
                                      "owner_decision_sha256":owner.decision.decision_sha256})
    return FastAuthorityStateV1.bootstrap(campaigns=(FastAuthorityCampaignV1(
        request=request, owner_issue_number=row["number"], owner_run_id=owner.run_id,
        legacy_closure_evidence_sha256=evidence_hash,
    ),))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-key", required=True)
    parser.add_argument("--expected-tail-sha256", required=True)
    parser.add_argument("--protected-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT,
                                check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        if commit != args.protected_commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("CATALOG_BOOTSTRAP_SOURCE_MISMATCH")
        actors = json.loads((REPOSITORY_ROOT / "config/catalog_controller_actors_v1.json").read_text("utf-8"))
        key_path = (REPOSITORY_ROOT / actors["requester_public_key_path"]).resolve(strict=True)
        if not key_path.is_relative_to(REPOSITORY_ROOT) or args.output.exists() or args.output.is_symlink():
            raise ValueError("CATALOG_BOOTSTRAP_PATH_INVALID")
        token = os.environ.get("GH_TOKEN", "")
        client = CatalogGitHubReadOnlyClient(REPOSITORY, token)
        candidate = build_bootstrap_candidate(
            client=client, public_key=key_path.read_bytes(), request_actors=frozenset(actors["request_actors"]),
            ledger_actor=actors["ledger_actor"], campaign_key=args.campaign_key,
            expected_tail_sha256=args.expected_tail_sha256, approved_commits=frozenset({commit}),
            download_archive=lambda artifact_id: _download_owner_archive(REPOSITORY, token, artifact_id),
            approve_historical_commit=lambda old: _historical_owner_commit_approved(client, old, commit),
        )
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(candidate.model_dump_json() + "\n")
        print(json.dumps({"status":"CANDIDATE_REQUIRES_PROTECTED_PUBLICATION", "state_sha256":candidate.state_sha256}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

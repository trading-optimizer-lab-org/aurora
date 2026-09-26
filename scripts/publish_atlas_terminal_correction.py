#!/usr/bin/env python3
"""Publish the one verified Atlas-1 terminal correction under the authority lock."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile
from typing import Any, Mapping, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority, write_current_fast_authority
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogTerminalReceiptV2
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient, CatalogGitHubSnapshotError
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.admit_catalog_fast_request import _download_owner_archive, _historical_owner_commit_approved
from scripts.prepare_atlas_terminal_correction import (
    ISSUE_NUMBER, OLD_RECEIPT_SHA, REPOSITORY, REQUEST_SHA, SOURCE_COMMIT,
    SOURCE_RUN_ID, _mapping, _require_environment,
)
from scripts.publish_catalog_fast_authority import _publisher_job
from scripts.reconcile_catalog_fast_authority import _write_body
from scripts.verify_catalog_fast_authority import read_live_edit


def _verify_uploaded_receipt(*, client: CatalogGitHubReadOnlyClient, run_id: int,
                             artifact_id: int, digest: str, receipt: CatalogTerminalReceiptV2,
                             commit: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("ATLAS_CORRECTION_UPLOAD_DIGEST_INVALID")
    metadata = _mapping(client.get_json(f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}")[0], "ATLAS_CORRECTION_UPLOAD_INVALID")
    source = _mapping(metadata.get("workflow_run"), "ATLAS_CORRECTION_UPLOAD_INVALID")
    expected_name = "catalog-terminal-correction-378"
    if (metadata.get("id") != artifact_id or metadata.get("name") != expected_name
        or metadata.get("digest") != digest or metadata.get("expired") is not False
        or (source.get("id"), source.get("head_sha")) != (run_id, commit)):
        raise ValueError("ATLAS_CORRECTION_UPLOAD_INVALID")
    raw = _download_owner_archive(REPOSITORY, os.environ["GH_TOKEN"], artifact_id)
    if hashlib.sha256(raw).hexdigest() != digest[7:]:
        raise ValueError("ATLAS_CORRECTION_UPLOAD_HASH_INVALID")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) != 1 or members[0].filename != "catalog-terminal-receipt-v1.json" or members[0].file_size > 8192:
            raise ValueError("ATLAS_CORRECTION_UPLOAD_CONTENT_INVALID")
        uploaded = CatalogTerminalReceiptV2.model_validate_json(archive.read(members[0]))
    if uploaded != receipt:
        raise ValueError("ATLAS_CORRECTION_UPLOAD_CONTENT_INVALID")


def publish(*, root: Path, receipt_path: Path, proof_path: Path, output: Path,
            github_output: Path, artifact_id: int, artifact_digest: str,
            client: CatalogGitHubReadOnlyClient, commit: str) -> None:
    proof = _mapping(json.loads(proof_path.read_text(encoding="utf-8")), "ATLAS_CORRECTION_PROOF_INVALID")
    receipt = CatalogTerminalReceiptV2.model_validate_json(receipt_path.read_bytes())
    if (proof.get("source_run_id") != SOURCE_RUN_ID or proof.get("source_commit") != SOURCE_COMMIT
        or proof.get("issue_number") != ISSUE_NUMBER or proof.get("request_sha256") != REQUEST_SHA
        or proof.get("old_terminal_receipt_sha256") != OLD_RECEIPT_SHA
        or proof.get("corrected_terminal_receipt_sha256") != receipt.receipt_sha256
        or proof.get("observed_recipe_count") != 209906
        or proof.get("result_science_sha256") != receipt.result_science_sha256
        or receipt.state != "SUCCESS" or receipt.reason_code != "CATALOG_RUN_SUCCESS"
        or receipt.engine_run_id != SOURCE_RUN_ID or receipt.request_sha256 != REQUEST_SHA
        or receipt.observed_recipe_count != 209906 or receipt.expected_recipe_count != 209906):
        raise ValueError("ATLAS_CORRECTION_PROOF_INVALID")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    _verify_uploaded_receipt(client=client, run_id=run_id, artifact_id=artifact_id,
                             digest=artifact_digest, receipt=receipt, commit=commit)
    issue = _mapping(client.get_json(f"/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}")[0], "ATLAS_CORRECTION_ISSUE_INVALID")
    actors = _mapping(json.loads((root / "config/catalog_controller_actors_v1.json").read_text(encoding="utf-8")), "ATLAS_CORRECTION_ACTORS_INVALID")
    key_path = (root / str(actors["requester_public_key_path"])).resolve(strict=True)
    if not key_path.is_relative_to(root):
        raise ValueError("ATLAS_CORRECTION_KEY_INVALID")
    request = parse_catalog_run_request(str(issue.get("title")), str(issue.get("body")), key_path.read_bytes())
    if request.request_sha256 != REQUEST_SHA:
        raise ValueError("ATLAS_CORRECTION_REQUEST_INVALID")
    anchor = _mapping(json.loads((root / "config/catalog_authority_anchor_v1.json").read_text(encoding="utf-8")), "ATLAS_CORRECTION_ANCHOR_INVALID")
    latest: dict[str, Any] = {}

    def read() -> dict[str, Any]:
        nonlocal latest
        latest = read_live_edit(cast(dict[str, Any], anchor))
        return latest

    current = load_current_fast_authority(
        client=client, anchor=anchor, protected_commit=commit, read_edit=read,
        download_archive=lambda source_id: _download_owner_archive(REPOSITORY, os.environ["GH_TOKEN"], source_id),
        approve_historical_commit=lambda source: _historical_owner_commit_approved(client, source, commit),
    )
    candidate = current.correct_terminal(
        request=request, run_id=SOURCE_RUN_ID, issue_number=ISSUE_NUMBER,
        prior_terminal_sha256=OLD_RECEIPT_SHA,
        corrected_terminal_sha256=receipt.receipt_sha256,
    )
    if candidate == current:
        with github_output.open("a", encoding="utf-8") as stream:
            stream.write("authority_already_applied=true\n")
        print(json.dumps({"status": "ATLAS_CORRECTION_ALREADY_APPLIED", "revision": current.revision}))
        return
    edit_id = latest["data"]["repository"]["issue"]["userContentEdits"]["nodes"][0]["id"]
    job_id = _publisher_job(client, run_id, attempt, commit, "reconcile")
    publication = write_current_fast_authority(
        current=current, candidate=candidate, expected_edit_id=edit_id,
        anchor=anchor, run_id=run_id, run_attempt=attempt, job_id=job_id,
        phase="reconcile", commit=commit, read_edit=read,
        write_body=lambda body: _write_body(REPOSITORY, anchor["issue_number"], body),
        terminal_correction_prior_sha256=OLD_RECEIPT_SHA,
    )
    output.write_text(publication.model_dump_json() + "\n", encoding="utf-8")
    with github_output.open("a", encoding="utf-8") as stream:
        stream.write(f"authority_artifact_name=catalog-fast-authority-{run_id}-{attempt}-reconcile-{job_id}\n")
        stream.write("authority_already_applied=false\n")
    print(json.dumps({"status": "ATLAS_CORRECTION_AUTHORITY_STAGED", "revision": candidate.revision,
                      "state_sha256": candidate.state_sha256, "corrected_receipt_sha256": receipt.receipt_sha256}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo-root", "receipt", "proof", "output", "github-output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--artifact-id", required=True, type=int)
    parser.add_argument("--artifact-digest", required=True)
    args = parser.parse_args()
    try:
        root = args.repo_root.resolve(strict=True)
        client, commit = _require_environment(root)
        publish(root=root, receipt_path=args.receipt, proof_path=args.proof,
                output=args.output, github_output=args.github_output,
                artifact_id=args.artifact_id, artifact_digest=args.artifact_digest,
                client=client, commit=commit)
        return 0
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile, CatalogGitHubSnapshotError) as exc:
        print(str(exc).split(":", 1)[0], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

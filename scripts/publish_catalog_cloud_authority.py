"""Publication adapter used by the protected cloud-intake phase runner.

Returns an edit binding requiring upload and production-reader verification;
the local file is never treated as sufficient evidence of durable publication.
"""

import json
import os
from pathlib import Path
import subprocess
from typing import Any, cast

from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_authority_github import write_current_fast_authority
from aurora.infra.sp500_megarun.catalog_lineage_transition import load_lineage_transition
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from scripts.admit_catalog_fast_request import _strict_json
from scripts.publish_catalog_fast_authority import _publisher_job
from scripts.verify_catalog_fast_authority import read_live_edit


def publish_cloud_candidate(
    *, root: Path, current: FastAuthorityStateV1, candidate: FastAuthorityStateV1,
    expected_edit_id: str, client, phase: str, output: Path,
) -> str:
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_JOB") != "intake"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or phase not in {"intake-signed", "intake-uncertain", "intake-published"}):
        raise ValueError("CATALOG_CLOUD_PUBLICATION_CONTEXT_INVALID")
    root = root.resolve(strict=True)
    temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    if (output.is_symlink() or output.exists()
            or not output.resolve().is_relative_to(temp)
            or output.name != "catalog-fast-authority-publication-v1.json"
            or not output.parent.is_dir()):
        raise ValueError("CATALOG_CLOUD_PUBLICATION_PATH_INVALID")
    run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
    commit = os.environ["GITHUB_SHA"]
    if os.environ.get("CATALOG_PROTECTED_COMMIT_SHA") != commit:
        raise ValueError("CATALOG_CLOUD_PUBLICATION_CONTEXT_INVALID")
    anchor_raw = _strict_json(root / "config/catalog_authority_anchor_v1.json")
    actors_raw = _strict_json(root / "config/catalog_controller_actors_v1.json")
    if not isinstance(anchor_raw, dict) or not isinstance(actors_raw, dict):
        raise ValueError("CATALOG_CLOUD_PUBLICATION_CONFIG_INVALID")
    anchor = cast(dict[str, Any], anchor_raw)
    actors = cast(dict[str, Any], actors_raw)
    public_key_path = actors.get("requester_public_key_path")
    if type(public_key_path) is not str or not public_key_path:
        raise ValueError("CATALOG_CLOUD_PUBLIC_KEY_INVALID")
    public_path = root / public_key_path
    if public_path.is_symlink() or not public_path.resolve(strict=True).is_relative_to(root):
        raise ValueError("CATALOG_CLOUD_PUBLIC_KEY_INVALID")
    public_key = public_path.read_bytes()
    changed = [row for row in candidate.emissions if row not in current.emissions]
    if len(changed) != 1:
        raise ValueError("CATALOG_CLOUD_PUBLICATION_TRANSITION_INVALID")
    item = changed[0]
    if parse_catalog_run_request(item.title, item.body, public_key) != item.request:
        raise ValueError("CATALOG_CLOUD_REQUEST_INVALID")
    job_id = _publisher_job(client, run_id, attempt, commit, phase)
    transition = load_lineage_transition(root, item.request) if phase == "intake-signed" else None

    def patch_once(body):
        result = subprocess.run(
            ["gh", "api", "--method", "PATCH",
             f"repos/{client.repository}/issues/{anchor['issue_number']}", "--input", "-"],
            input=json.dumps({"body": body}), capture_output=True, text=True,
            timeout=30, check=False,
        )
        if result.returncode != 0:
            raise ValueError("CATALOG_CLOUD_AUTHORITY_WRITE_UNCONFIRMED")

    publication = write_current_fast_authority(
        current=current, candidate=candidate, expected_edit_id=expected_edit_id,
        anchor=anchor, run_id=run_id, run_attempt=attempt, job_id=job_id,
        phase=phase, commit=commit, read_edit=lambda: read_live_edit(anchor),
        write_body=patch_once, lineage_transition=transition,
    )
    with output.open("x", encoding="utf-8") as stream:
        stream.write(publication.model_dump_json() + "\n")
    return f"catalog-fast-authority-{run_id}-{attempt}-{phase}-{job_id}"

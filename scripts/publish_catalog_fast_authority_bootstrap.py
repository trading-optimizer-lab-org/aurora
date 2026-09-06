#!/usr/bin/env python3
"""One initial protected publication from pinned, freshly verified signed history."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from aurora.infra.sp500_megarun.catalog_fast_authority_github import require_pristine_fast_authority, write_bootstrap_fast_authority
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient, CatalogGitHubSnapshotError
from scripts.admit_catalog_fast_request import _download_owner_archive, _historical_owner_commit_approved, _strict_json
from scripts.bootstrap_catalog_fast_authority import build_bootstrap_candidate
from scripts.publish_catalog_fast_authority import _publisher_job
from scripts.verify_catalog_fast_authority import read_live_edit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GH_TOKEN", "")
        commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
        if (repository != "trading-optimizer-lab-org/aurora" or not token
            or not re.fullmatch(r"[0-9a-f]{40}", commit) or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_JOB") != "bootstrap"):
            raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_ENVIRONMENT_INVALID")
        run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
        root = args.repo_root.resolve(strict=True)
        temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        if args.github_output is not None and (args.github_output.is_symlink()
                or not args.github_output.resolve(strict=False).is_relative_to(temp)):
            raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_PATH_INVALID")
        if (args.repo_root.is_symlink() or args.output.is_symlink() or args.output.exists()
            or not args.output.resolve(strict=False).is_relative_to(temp) or not args.output.parent.is_dir()):
            raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_PATH_INVALID")
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
            text=True, timeout=10, check=False)
        if head.returncode != 0 or head.stdout.strip() != commit:
            raise ValueError("CATALOG_FAST_AUTHORITY_CHECKOUT_INVALID")
        anchor = _strict_json(root / "config/catalog_authority_anchor_v1.json")
        actors = _strict_json(root / "config/catalog_controller_actors_v1.json")
        baseline = _strict_json(root / "config/catalog_fast_authority_bootstrap_v1.json")
        if not isinstance(anchor, dict) or not isinstance(actors, dict) or not isinstance(baseline, dict):
            raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_INPUT_INVALID")
        if (set(baseline) != {"schema_version", "campaign_key", "expected_tail_sha256", "expected_state_sha256"}
            or baseline["schema_version"] != "1"
            or any(not isinstance(baseline[key], str) or not re.fullmatch(r"[0-9a-f]{64}", baseline[key])
                   for key in ("expected_tail_sha256", "expected_state_sha256"))):
            raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_PIN_INVALID")
        require_pristine_fast_authority(read_live_edit(anchor), anchor)
        key_path = (root / actors["requester_public_key_path"]).resolve(strict=True)
        if not key_path.is_relative_to(root):
            raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_KEY_INVALID")
        client = CatalogGitHubReadOnlyClient(repository, token)
        job_id = _publisher_job(client, run_id, attempt, commit, "bootstrap")
        candidate = build_bootstrap_candidate(client=client, public_key=key_path.read_bytes(),
            request_actors=frozenset(actors["request_actors"]), ledger_actor=actors["ledger_actor"],
            campaign_key=baseline["campaign_key"], expected_tail_sha256=baseline["expected_tail_sha256"],
            approved_commits=frozenset({commit}),
            download_archive=lambda artifact: _download_owner_archive(repository, token, artifact),
            approve_historical_commit=lambda old: _historical_owner_commit_approved(client, old, commit))

        def write(body: str) -> None:
            result = subprocess.run(["gh", "api", "--method", "PATCH", f"repos/{repository}/issues/{anchor['issue_number']}", "--input", "-"],
                input=json.dumps({"body": body}), capture_output=True, text=True, timeout=20, check=False)
            if result.returncode != 0:
                raise ValueError("CATALOG_FAST_AUTHORITY_BOOTSTRAP_WRITE_FAILED")

        publication = write_bootstrap_fast_authority(candidate=candidate,
            expected_state_sha256=baseline["expected_state_sha256"], anchor=anchor, run_id=run_id,
            run_attempt=attempt, job_id=job_id, commit=commit, read_edit=lambda: read_live_edit(anchor), write_body=write)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(publication.model_dump_json() + "\n")
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write(f"authority_artifact_name=catalog-fast-authority-{run_id}-{attempt}-bootstrap-{job_id}\n")
        print(json.dumps({"status": "BOOTSTRAP_STAGED_REQUIRES_UPLOAD_AND_VERIFICATION", "state_sha256": candidate.state_sha256}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, CatalogGitHubSnapshotError, subprocess.SubprocessError) as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"CATALOG_[A-Z0-9_]+", reason):
            reason = "CATALOG_FAST_AUTHORITY_BOOTSTRAP_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

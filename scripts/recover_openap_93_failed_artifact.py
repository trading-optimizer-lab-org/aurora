from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.core.runtime_paths import base_data_dir
from aurora.research.openap_181.artifact_recovery import (
    HttpRangeReader,
    read_zip_members,
    validate_recovered_openap_93,
)


API_ROOT = "https://api.github.com"
RECOVERY_MEMBERS = (
    "coverage_93.csv",
    "signals_93_current.csv",
    "run_manifest.json",
)


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Aurora-OpenAP-Artifact-Recovery/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _read_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _artifact_download_url(repository: str, artifact_id: int, token: str) -> str:
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        headers=_headers(token),
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code not in {302, 303, 307} or not exc.headers.get("Location"):
            raise
        return str(exc.headers["Location"])
    raise RuntimeError("GitHub artifact endpoint did not return a download redirect")


def _select_artifact(payload: Any, artifact_name: str) -> dict[str, Any]:
    artifacts = payload.get("artifacts", []) if isinstance(payload, dict) else []
    matches = [artifact for artifact in artifacts if artifact.get("name") == artifact_name]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one source artifact {artifact_name}, found {len(matches)}"
        )
    return dict(matches[0])


def _range_fetcher(url: str, total_size: int):
    def fetch(start: int, end: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "Aurora-OpenAP-Artifact-Recovery/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 206:
                raise RuntimeError(f"Range request returned HTTP {response.status}")
            expected_range = f"bytes {start}-{end}/{total_size}"
            if response.headers.get("Content-Range") != expected_range:
                raise RuntimeError("Range response Content-Range mismatch")
            return response.read()

    return fetch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-artifact-name", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require_github_actions_or_explicit_local_permission(
        "OpenAP 93 failed artifact selective recovery"
    )
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for artifact recovery")
    run_url = f"{API_ROOT}/repos/{args.repository}/actions/runs/{args.source_run_id}"
    run = _read_json(run_url, token)
    jobs = _read_json(f"{run_url}/jobs?per_page=100", token).get("jobs", [])
    artifacts = _read_json(f"{run_url}/artifacts?per_page=100", token)
    artifact = _select_artifact(artifacts, args.source_artifact_name)
    artifact_size = int(artifact["size_in_bytes"])
    signed_url = _artifact_download_url(args.repository, int(artifact["id"]), token)
    reader = HttpRangeReader(
        artifact_size,
        _range_fetcher(signed_url, artifact_size),
    )
    members = read_zip_members(reader, RECOVERY_MEMBERS)
    recovery = validate_recovered_openap_93(run, jobs, artifact, members)

    output = (
        args.output_dir
        if args.output_dir.is_absolute()
        else base_data_dir() / args.output_dir
    )
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in members.items():
        target_name = "source_run_manifest.json" if name == "run_manifest.json" else name
        (output / target_name).write_bytes(payload)
    recovery.update(
        {
            "source_run_url": (
                f"https://github.com/{args.repository}/actions/runs/{args.source_run_id}"
            ),
            "range_requests": reader.range_requests,
            "bytes_fetched": reader.bytes_fetched,
            "full_artifact_downloaded": False,
            "recovered_at": datetime.now(timezone.utc).isoformat(),
            "strict_score_eligible": False,
        }
    )
    (output / "openap_93_artifact_recovery_manifest.json").write_text(
        json.dumps(recovery, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(recovery, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

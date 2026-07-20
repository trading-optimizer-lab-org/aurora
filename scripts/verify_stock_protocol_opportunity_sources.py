"""Verify the immutable GitHub artifact set used by the opportunity audit."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def main() -> None:
    verified: list[dict[str, object]] = []
    checks = (
        ("FINAL_RUN_ID", "FINAL_ARTIFACT_ID", "FINAL_ARTIFACT_NAME", "FINAL_ARTIFACT_DIGEST"),
        ("IS_RUN_ID", "IS_ARTIFACT_ID", "IS_ARTIFACT_NAME", "IS_ARTIFACT_DIGEST"),
        ("LOCKED_RUN_ID", "PACK_ARTIFACT_ID", "PACK_ARTIFACT_NAME", "PACK_ARTIFACT_DIGEST"),
    )
    repository = os.environ["GITHUB_REPOSITORY"]
    for run_key, id_key, name_key, digest_key in checks:
        artifact = json.loads(
            subprocess.check_output(
                ["gh", "api", f"repos/{repository}/actions/artifacts/{os.environ[id_key]}"],
                text=True,
            )
        )
        assert str(artifact["workflow_run"]["id"]) == os.environ[run_key]
        assert str(artifact["id"]) == os.environ[id_key]
        assert artifact["name"] == os.environ[name_key]
        assert artifact["digest"].lower() == os.environ[digest_key].lower()
        assert artifact["expired"] is False
        verified.append(
            {
                "role": id_key.removesuffix("_ARTIFACT_ID").lower(),
                "run_id": int(os.environ[run_key]),
                "artifact_id": int(os.environ[id_key]),
                "artifact_name": artifact["name"],
                "digest": artifact["digest"].lower(),
                "expired": False,
            }
        )
    locked = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                f"repos/{repository}/actions/runs/{os.environ['LOCKED_RUN_ID']}/artifacts?per_page=100",
            ],
            text=True,
        )
    )["artifacts"]
    shards = [
        item for item in locked if item["name"].startswith("stock-protocol-exact-locked-data-")
    ]
    assert len(shards) == 32
    assert all(not item["expired"] and item.get("digest") for item in shards)
    verified.extend(
        {
            "role": "locked_data_shard",
            "run_id": int(os.environ["LOCKED_RUN_ID"]),
            "artifact_id": int(item["id"]),
            "artifact_name": item["name"],
            "digest": item["digest"].lower(),
            "expired": False,
        }
        for item in sorted(shards, key=lambda value: value["name"])
    )
    Path("source-artifact-audit.json").write_text(
        json.dumps({"verified_artifacts": verified}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"verified immutable artifacts: {len(verified)}")


if __name__ == "__main__":
    main()

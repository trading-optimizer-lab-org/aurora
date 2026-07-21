"""Verify every immutable GitHub artifact used by the 290-event study."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


SOURCE_LOCK_NAME = "stock-protocol-290-source-lock.json"

EXPECTED = (
    {
        "role": "original_290_definition",
        "run_id": 29658603488,
        "artifact_id": 8433666535,
        "name": "stock-protocol-scientific-full-universe-360jobs-corrected-results",
        "digest": "sha256:3936159b63e4dab5e7299fafb6996c6eb963cb4d88aea388fe6e62444a059116",
    },
    {
        "role": "prior_opportunity_audit",
        "run_id": 29804082610,
        "artifact_id": 8484878298,
        "name": "stock-protocol-all-opportunities-and-realistic-portfolio-audit",
        "digest": "sha256:3b9a48a3a068bf84f5360d559035bfb626a330e7ad90664dd4a23fbe95aed87c",
    },
    {
        "role": "frozen_exact_strategy",
        "run_id": 29688666475,
        "artifact_id": 8442888783,
        "name": "stock-protocol-exact-irrevocable-oos-results-final",
        "digest": "sha256:2e878f9cba45ac27d18939b498e54bf4c193b1ce65641231b1914363c1bf4704",
    },
    {
        "role": "prelocked_price_pack",
        "run_id": 29684671183,
        "artifact_id": 8441708061,
        "name": "stock-protocol-exact-prelocked-pack",
        "digest": "sha256:0e904662d4ea453869370300d1eb6e1ed43992e1d4db36d0949516291f9f3576",
    },
    {
        "role": "entry_layer_snapshot",
        "run_id": 29645606473,
        "artifact_id": 8429948323,
        "name": "stock-protocol-entries-merged",
        "digest": "sha256:c61dd3c1d14c2aa2146e85bfd0217a85076f1970ef9c1e98f14303e2e4806039",
    },
    {
        "role": "exit_layer_snapshot",
        "run_id": 29645606473,
        "artifact_id": 8429948441,
        "name": "stock-protocol-exits-merged",
        "digest": "sha256:43697a099297d4a9f4c648ddd8282b69203588334ef2fa3640ba17edd918320a",
    },
)


def _artifact(repository: str, artifact_id: int) -> dict[str, object]:
    return json.loads(
        subprocess.check_output(
            ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}"],
            text=True,
        )
    )


def _verify_one(repository: str, expected: dict[str, object]) -> dict[str, object]:
    actual = _artifact(repository, int(expected["artifact_id"]))
    checks = {
        "run_id": int(actual["workflow_run"]["id"]),
        "artifact_id": int(actual["id"]),
        "name": str(actual["name"]),
        "digest": str(actual["digest"]).lower(),
        "expired": bool(actual["expired"]),
    }
    if checks["run_id"] != expected["run_id"]:
        raise ValueError(f"run mismatch for {expected['role']}: {checks['run_id']}")
    if checks["artifact_id"] != expected["artifact_id"]:
        raise ValueError(f"artifact id mismatch for {expected['role']}")
    if checks["name"] != expected["name"]:
        raise ValueError(f"artifact name mismatch for {expected['role']}")
    if checks["digest"] != str(expected["digest"]).lower():
        raise ValueError(f"artifact digest mismatch for {expected['role']}")
    if checks["expired"]:
        raise ValueError(f"artifact expired for {expected['role']}")
    return {**expected, "expired": False, "size_in_bytes": int(actual["size_in_bytes"])}


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "trading-optimizer-lab-org/aurora")
    verified = [_verify_one(repository, item) for item in EXPECTED]
    locked = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "repos/trading-optimizer-lab-org/aurora/actions/runs/29684671183/artifacts?per_page=100",
            ],
            text=True,
        )
    )["artifacts"]
    shards = sorted(
        (
            item
            for item in locked
            if str(item["name"]).startswith("stock-protocol-exact-locked-data-")
        ),
        key=lambda item: str(item["name"]),
    )
    if len(shards) != 32:
        raise ValueError(f"expected 32 locked shards, found {len(shards)}")
    for item in shards:
        if item["expired"] or not str(item.get("digest", "")).startswith("sha256:"):
            raise ValueError(f"invalid locked shard artifact: {item['name']}")
        verified.append(
            {
                "role": "locked_price_shard",
                "run_id": 29684671183,
                "artifact_id": int(item["id"]),
                "name": str(item["name"]),
                "digest": str(item["digest"]).lower(),
                "expired": False,
                "size_in_bytes": int(item["size_in_bytes"]),
            }
        )
    payload = {
        "schema_version": 1,
        "repository": repository,
        "verified_artifacts": verified,
        "source_count": len(verified),
        "cutoff": "2026-07-17",
        "new_oos_claimed": False,
        "optimization_performed_on_opened_data": False,
    }
    Path(SOURCE_LOCK_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"verified": len(verified), "locked_shards": len(shards)}))


if __name__ == "__main__":
    main()

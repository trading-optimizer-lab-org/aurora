"""Apply and capture owner-controlled stage-two GitHub protection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes
from infra.gtbi_v7_readiness.g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
    REPOSITORY,
)
from infra.gtbi_v7_readiness.stage_two_protection import (
    branch_protection_api_payload,
    build_policy,
)

POLICY = ROOT / "config/gtbi/governance/stage_two_owner_controlled_protection.json"


class StageTwoProtectionError(RuntimeError):
    """A stage-two GitHub operation failed."""


def _run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    allow_not_found: bool = False,
) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        stderr = result.stderr.decode("utf-8", errors="replace")
        if allow_not_found and "HTTP 404" in stderr:
            return ""
        raise StageTwoProtectionError(stderr)
    return result.stdout.decode("utf-8")


def _gh_json(
    endpoint: str,
    *,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    allow_not_found: bool = False,
) -> Any:
    args = ["gh", "api"]
    if method != "GET":
        args.extend(["--method", method])
    args.append(endpoint)
    payload = None
    if body is not None:
        args.extend(["--input", "-"])
        payload = canonical_bytes(body)
    raw = _run(
        args,
        input_bytes=payload,
        allow_not_found=allow_not_found,
    )
    return json.loads(raw) if raw else None


def apply_branch_protection() -> None:
    _gh_json(
        f"/repos/{REPOSITORY}/branches/main/protection",
        method="PUT",
        body=branch_protection_api_payload(),
    )


def capture_environment(name: str) -> dict[str, Any]:
    encoded = quote(name, safe="")
    environment = _gh_json(f"/repos/{REPOSITORY}/environments/{encoded}")
    branch_policies = _gh_json(
        f"/repos/{REPOSITORY}/environments/{encoded}/deployment-branch-policies",
        allow_not_found=True,
    ) or {"total_count": 0}
    secrets = _gh_json(
        f"/repos/{REPOSITORY}/environments/{encoded}/secrets",
        allow_not_found=True,
    ) or {"total_count": 0}
    reviewers: list[dict[str, Any]] = []
    prevent_self_review = False
    for rule in environment.get("protection_rules", []):
        if rule.get("type") != "required_reviewers":
            continue
        prevent_self_review = bool(rule.get("prevent_self_review"))
        for entry in rule.get("reviewers", []):
            reviewer = entry.get("reviewer") or {}
            reviewers.append(
                {
                    "type": reviewer.get("type"),
                    "id": reviewer.get("id"),
                    "login": reviewer.get("login"),
                }
            )
    return {
        "name": name,
        "deployment_branch_policy": environment.get("deployment_branch_policy"),
        "reviewers": reviewers,
        "prevent_self_review": prevent_self_review,
        "custom_branch_policy_count": int(branch_policies.get("total_count", 0)),
        "secret_count": int(secrets.get("total_count", 0)),
    }


def capture_live_snapshot() -> dict[str, Any]:
    return {
        "branch_protection": _gh_json(f"/repos/{REPOSITORY}/branches/main/protection"),
        "environments": [capture_environment(name) for name in CANONICAL_SOURCE_ENVIRONMENTS],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--print-snapshot", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    POLICY.write_bytes(canonical_bytes(build_policy()) + b"\n")
    if args.apply:
        apply_branch_protection()
    if args.print_snapshot:
        print(json.dumps(capture_live_snapshot(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

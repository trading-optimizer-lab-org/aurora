#!/usr/bin/env python3
"""Authenticate one issue and derive its exact PREPARED cache prefix."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_fast_path import (
    build_catalog_preparation_identity,
)
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request


_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect one signed fast catalog request.")
    parser.add_argument("--issue", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    return parser


def _strict_json(path: Path) -> object:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("CATALOG_FAST_REQUEST_DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_FAST_REQUEST_INPUT_INVALID")
    return json.loads(
        path.read_text("utf-8"),
        object_pairs_hook=reject,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"CATALOG_FAST_REQUEST_NONFINITE_JSON:{value}")
        ),
    )


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(code)
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def inspect_request(
    *,
    issue_path: Path,
    repo_root: Path,
    output_path: Path,
    github_output: Path,
) -> dict[str, object]:
    expected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    if not _COMMIT.fullmatch(expected_commit) or not runner_temp_raw:
        raise ValueError("CATALOG_FAST_REQUEST_INVOCATION_INVALID")
    root = repo_root.resolve(strict=True)
    runner_temp = Path(runner_temp_raw).resolve(strict=True)
    issue_file = issue_path.resolve(strict=True)
    output = output_path.resolve(strict=False)
    gh_output = github_output.resolve(strict=False)
    if (
        repo_root.is_symlink()
        or not root.is_dir()
        or not issue_file.is_relative_to(runner_temp)
        or output_path.exists()
        or output_path.is_symlink()
        or not output.is_relative_to(runner_temp)
        or github_output.is_symlink()
        or not gh_output.is_relative_to(runner_temp)
    ):
        raise ValueError("CATALOG_FAST_REQUEST_PATH_INVALID")
    checked_out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if checked_out != expected_commit:
        raise ValueError("CATALOG_FAST_REQUEST_COMMIT_MISMATCH")

    issue = _mapping(_strict_json(issue_file), "CATALOG_FAST_REQUEST_INVALID")
    user = _mapping(issue.get("user"), "CATALOG_FAST_REQUEST_ACTOR_INVALID")
    actors = _mapping(
        _strict_json(root / "config/catalog_controller_actors_v1.json"),
        "CATALOG_FAST_REQUEST_ACTOR_INVALID",
    )
    actor = user.get("login")
    allowed = actors.get("request_actors")
    if not isinstance(allowed, list) or actor not in allowed:
        raise ValueError("CATALOG_FAST_REQUEST_ACTOR_INVALID")
    title = issue.get("title")
    body = issue.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("CATALOG_FAST_REQUEST_INVALID")
    public_key_path = actors.get("requester_public_key_path")
    if not isinstance(public_key_path, str):
        raise ValueError("CATALOG_REQUESTER_KEY_UNAVAILABLE")
    request = parse_catalog_run_request(
        title,
        body,
        (root / public_key_path).read_bytes(),
    )
    ticket = CatalogLaunchTicketV1(
        schema_version="1",
        request_id=request.request_id,
        campaign_key=request.campaign_key,
        launch_generation=request.launch_generation,
        campaign_definition_sha256=request.campaign_definition_sha256,
        prompt_sha256=request.prompt_sha256,
        previous_terminal_request_sha256=request.previous_terminal_request_sha256,
    )
    if request.launch_ticket_sha256 != ticket.launch_ticket_sha256:
        raise ValueError("CATALOG_LAUNCH_TICKET_INVALID")
    labels = issue.get("labels", [])
    label_names = tuple(
        sorted(
            str(row.get("name"))
            for row in labels
            if isinstance(row, Mapping) and isinstance(row.get("name"), str)
        )
    )
    # A hint may only narrow this invocation to reading an existing owner. The
    # live admission reader still authenticates ownership; these labels do not.
    lookup_existing = bool(set(label_names) & {"catalog-run-active-v1", "catalog-run-terminal-v1"}) or issue.get("state") == "closed"
    identity = None
    logical_recipe_count = None
    preparation_error = None
    if not lookup_existing:
        try:
            registry = load_catalog_campaign_registry(root / "config/catalog_campaign_registry_v1.json")
            entry = resolve_catalog_campaign(registry, request.campaign_key, root)
            identity = build_catalog_preparation_identity(
                repo_root=root, registry_entry=entry, protected_commit_sha=expected_commit,
            )
            catalog_manifest = _mapping(
                _strict_json(root / entry.catalog_dir / "manifest.json"), "CATALOG_MANIFEST_INVALID",
            )
            logical_recipe_count = catalog_manifest.get("strategy_count")
            if isinstance(logical_recipe_count, bool) or not isinstance(logical_recipe_count, int) or logical_recipe_count < 1:
                raise ValueError("CATALOG_MANIFEST_INVALID")
        except (ValueError, OSError) as exc:
            # Authentication above already succeeded. Unavailable current
            # preparation must not prevent reading a previously admitted run.
            # Restrict this context to lookup: it can never authorize fresh work.
            code = str(exc).split(":", 1)[0]
            preparation_error = code if re.fullmatch(r"CATALOG_[A-Z0-9_]+", code) else "CATALOG_PREPARATION_UNAVAILABLE"
            lookup_existing = True
            identity = None
            logical_recipe_count = None
    context_identity = {
        "schema_version": "1",
        "document_type": "catalog_fast_request_context_v1",
        "issue_number": issue.get("number"),
        "issue_created_at": issue.get("created_at"),
        "issue_updated_at": issue.get("updated_at"),
        "issue_labels": label_names,
        "actor": actor,
        "request": request.model_dump(mode="json"),
        "identity": identity.model_dump(mode="json") if identity is not None else None,
        "request_mode": "lookup_existing" if lookup_existing else "admit_new",
        "preparation_error": preparation_error,
        "logical_recipe_count": logical_recipe_count,
        "protected_commit_sha": expected_commit,
    }
    context = {
        **context_identity,
        "content_sha256": canonical_sha256(context_identity),
    }
    _write(output_path, context)
    outputs = {
        "campaign_key": request.campaign_key,
        "request_sha256": request.request_sha256,
        "submission_key_sha256": request.submission_key_sha256,
        "preparation_key_sha256": identity.preparation_key_sha256 if identity is not None else "",
        "prepared_cache_restore_prefix": (
            f"aurora-catalog-prepared-v1-{identity.preparation_key_sha256}-"
            if identity is not None else ""
        ),
    }
    with github_output.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in outputs.items():
            stream.write(f"{key}={value}\n")
    return context


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        inspect_request(
            issue_path=args.issue,
            repo_root=args.repo_root,
            output_path=args.output,
            github_output=args.github_output,
        )
        return 0
    except (json.JSONDecodeError, OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

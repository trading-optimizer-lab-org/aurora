"""Closed one-shot coordinator for AURORA catalog bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from infra.sp500_megarun.catalog_bootstrap_contract import (
    CatalogBootstrapAppManifestV1,
    CatalogBootstrapManifestSetV1,
)
from infra.sp500_megarun.catalog_bootstrap_binding import (
    build_public_binding_patch,
    create_or_verify_authority_anchor,
)
from infra.sp500_megarun.catalog_bootstrap_github import (
    CatalogAppPublicBinding,
    CatalogBootstrapGitHubClient,
    derive_public_binding,
)
from infra.sp500_megarun.catalog_bootstrap_finalizer import (
    CatalogBootstrapFinalEvidenceV1,
    CatalogBootstrapObservedProductionSealV1,
    canonical_ready_receipt_bytes,
    complete_sealed_bootstrap,
    finalize_bootstrap,
)
from infra.sp500_megarun.catalog_bootstrap_manifest import (
    ManifestLoopbackServer,
    exchange_manifest_code,
    start_manifest_session,
)
from infra.sp500_megarun.catalog_bootstrap_secrets import (
    store_requester_key_once,
    upload_auditor_key_once,
)
from infra.sp500_megarun.catalog_bootstrap_state import (
    CatalogBootstrapEventV1,
    CatalogBootstrapStateV1,
    advance_bootstrap_state,
    initial_bootstrap_state,
    load_bootstrap_state,
    persist_bootstrap_state,
)


EXPECTED_ROOT = Path("C:/ProgramData/AURORA/CatalogBootstrap")
REPOSITORY = "trading-optimizer-lab-org/aurora"
BROKER_ROOT = Path("C:/ProgramData/AURORA/CatalogRequester")
AGENT_ROOT = Path("C:/ProgramData/AURORA/CatalogAgent")
CONTROLLER_VARIABLE = "CATALOG_CONTROLLER_ENABLED"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_BOOTSTRAP_WORKFLOWS = frozenset(
    {
        "catalog-live-controls-qualification.yml",
        "catalog-controller-policy-check.yml",
        "catalog-controller-qualification.yml",
        "catalog-capacity-calibration.yml",
        "catalog-artifact-keeper.yml",
    }
)
_HEAVY_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/catalog-component-worker.yml",
        ".github/workflows/catalog-optimized-run.yml",
        ".github/workflows/catalog-optimized-worker.yml",
        ".github/workflows/catalog-recovery-wave.yml",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("CATALOG_BOOTSTRAP_CONTEXT_INVALID")
    return value


def _manifests() -> CatalogBootstrapManifestSetV1:
    with zipfile.ZipFile(Path(sys.argv[0])) as archive:
        data = archive.read("config/catalog_bootstrap_app_manifests_v1.json")
    return CatalogBootstrapManifestSetV1.model_validate_json(data)


def _state_path(root: Path) -> Path:
    return root / "state/catalog-bootstrap-state-v1.json"


def _context(root: Path) -> dict[str, object]:
    value = _read_json(root / "install-context-v1.json")
    if set(value) != {"repository", "source_commit_sha", "source_root"}:
        raise ValueError("CATALOG_BOOTSTRAP_CONTEXT_INVALID")
    if value["repository"] != REPOSITORY:
        raise ValueError("CATALOG_BOOTSTRAP_CONTEXT_INVALID")
    return value


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: int = 120,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED")
    return result.stdout.strip()


def _run_with_input(
    args: list[str],
    body: object,
    *,
    cwd: Path | None = None,
    timeout_seconds: int = 120,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        input=_canonical(body),
        check=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED")
    return result.stdout.decode("utf-8").strip()


def _write_canonical(path: Path, value: object) -> str:
    data = _canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def _set_repository_variable(name: str, value: str) -> None:
    if name not in {
        CONTROLLER_VARIABLE,
        "CATALOG_AUTHORITY_ISSUE_NUMBER",
        "AURORA_CATALOG_AUDITOR_APP_ID",
    }:
        raise ValueError("CATALOG_BOOTSTRAP_VARIABLE_FORBIDDEN")
    _run(["gh", "variable", "set", name, "--body", value, "--repo", REPOSITORY])
    observed = _run(["gh", "variable", "get", name, "--repo", REPOSITORY])
    if observed != value:
        raise ValueError("CATALOG_BOOTSTRAP_VARIABLE_READBACK_INVALID")


def _list_workflow_runs(workflow: str) -> list[dict[str, object]]:
    if workflow not in _ALLOWED_BOOTSTRAP_WORKFLOWS:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FORBIDDEN")
    raw = _run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            REPOSITORY,
            "--workflow",
            workflow,
            "--branch",
            "main",
            "--limit",
            "50",
            "--json",
            "databaseId,headSha,event,status,conclusion,createdAt,url",
        ]
    )
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_LIST_INVALID")
    return value


def _dispatch_workflow(workflow: str, protected_commit_sha: str) -> dict[str, object]:
    if workflow not in _ALLOWED_BOOTSTRAP_WORKFLOWS or not _COMMIT.fullmatch(
        protected_commit_sha
    ):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FORBIDDEN")
    before = {
        int(row["databaseId"])
        for row in _list_workflow_runs(workflow)
        if isinstance(row.get("databaseId"), int)
    }
    _run(
        [
            "gh",
            "workflow",
            "run",
            workflow,
            "--repo",
            REPOSITORY,
            "--ref",
            "main",
        ]
    )
    deadline = time.monotonic() + 300
    selected: dict[str, object] | None = None
    while time.monotonic() < deadline:
        candidates = [
            row
            for row in _list_workflow_runs(workflow)
            if isinstance(row.get("databaseId"), int)
            and int(row["databaseId"]) not in before
            and row.get("event") == "workflow_dispatch"
            and row.get("headSha") == protected_commit_sha
        ]
        if len(candidates) > 1:
            raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_RUN_AMBIGUOUS")
        if candidates:
            selected = candidates[0]
            break
        time.sleep(3)
    if selected is None:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_RUN_NOT_FOUND")
    run_id = int(selected["databaseId"])
    watched = subprocess.run(
        ["gh", "run", "watch", str(run_id), "--repo", REPOSITORY, "--exit-status"],
        check=False,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if watched.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FAILED")
    observed = json.loads(
        _run(
            [
                "gh",
                "run",
                "view",
                str(run_id),
                "--repo",
                REPOSITORY,
                "--json",
                "databaseId,headSha,event,status,conclusion,url",
            ]
        )
    )
    if (
        not isinstance(observed, dict)
        or observed.get("databaseId") != run_id
        or observed.get("headSha") != protected_commit_sha
        or observed.get("event") != "workflow_dispatch"
        or observed.get("status") != "completed"
        or observed.get("conclusion") != "success"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_READBACK_INVALID")
    return observed


def _download_live_qualification(
    root: Path,
    run: dict[str, object],
    protected_commit_sha: str,
) -> dict[str, object]:
    run_id = int(run["databaseId"])
    destination = root / f"receipts/live-controls-{run_id}"
    if not destination.exists():
        destination.mkdir(parents=True)
        _run(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--repo",
                REPOSITORY,
                "--name",
                f"catalog-live-controls-qualification-{run_id}",
                "--dir",
                str(destination),
            ],
            timeout_seconds=600,
        )
    receipt_path = destination / "catalog_live_controls_qualification_receipt_v1.json"
    data = receipt_path.read_bytes()
    receipt = _read_json(receipt_path)
    if (
        data != _canonical(receipt) + b"\n"
        or set(receipt)
        != {
            "schema_version",
            "observer_context",
            "protected_commit_sha",
            "admission_receipt_sha256",
            "terminal_receipt_sha256",
            "receipt_sha256",
        }
        or receipt.get("schema_version") != "1"
        or receipt.get("observer_context") != "live_qualification"
        or receipt.get("protected_commit_sha") != protected_commit_sha
        or any(
            not _SHA256.fullmatch(str(receipt.get(name, "")))
            for name in (
                "admission_receipt_sha256",
                "terminal_receipt_sha256",
                "receipt_sha256",
            )
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_INVALID")
    identity = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if hashlib.sha256(_canonical(identity)).hexdigest() != receipt["receipt_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_LIVE_RECEIPT_INVALID")
    return {
        "run_id": run_id,
        "run_url": run.get("url"),
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "receipt": receipt,
    }


def _run_live_qualification(root: Path, protected_commit_sha: str) -> dict[str, object]:
    run = _dispatch_workflow(
        "catalog-live-controls-qualification.yml", protected_commit_sha
    )
    return _download_live_qualification(root, run, protected_commit_sha)


def _github_activity_snapshot() -> dict[str, object]:
    issue_pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/issues?state=all&per_page=100",
            ]
        )
    )
    issues = [row for page in issue_pages for row in page]
    requests = [
        int(row["number"])
        for row in issues
        if isinstance(row, dict)
        and "pull_request" not in row
        and isinstance(row.get("number"), int)
        and str(row.get("title", "")).startswith("[AURORA CATALOG RUN REQUEST] ")
    ]
    run_pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/actions/runs?per_page=100",
            ]
        )
    )
    runs = [row for page in run_pages for row in page]
    heavy = [
        int(row["id"])
        for row in runs
        if isinstance(row, dict)
        and isinstance(row.get("id"), int)
        and row.get("path") in _HEAVY_WORKFLOW_PATHS
    ]
    return {
        "request_issue_numbers": sorted(requests),
        "heavy_run_ids": sorted(heavy),
    }


def _run_binding_review_rounds(root: Path, source: Path) -> dict[str, object]:
    staged_tree = _run(["git", "write-tree"], cwd=source)
    if not _COMMIT.fullmatch(staged_tree):
        raise ValueError("CATALOG_BOOTSTRAP_BINDING_TREE_INVALID")
    rounds: list[dict[str, object]] = []
    test_paths = (
        "tests/test_catalog_bootstrap_binding.py",
        "tests/test_catalog_authority_ledger.py",
        "tests/test_catalog_github_controls.py",
        "tests/test_catalog_controller_workflows.py",
        "tests/test_catalog_run_request.py",
        "tests/test_submit_catalog_run_request.py",
        "tests/test_catalog_requester_broker.py",
    )
    for number in range(1, 4):
        _run(
            ["C:/Python314/python.exe", "-m", "pytest", "-q", *test_paths],
            cwd=source,
            timeout_seconds=3600,
        )
        _run(
            [
                "C:/Python314/python.exe",
                "-m",
                "ruff",
                "check",
                "infra/sp500_megarun/catalog_bootstrap_binding.py",
                *test_paths,
            ],
            cwd=source,
            timeout_seconds=600,
        )
        _run(["git", "diff", "--cached", "--check"], cwd=source)
        observed_tree = _run(["git", "write-tree"], cwd=source)
        staged_diff = _run(["git", "diff", "--cached", "--binary"], cwd=source)
        if observed_tree != staged_tree or any(
            marker in staged_diff
            for marker in (
                "BEGIN PRIVATE KEY",
                "BEGIN RSA PRIVATE KEY",
                "github_pat_",
                "ghp_",
            )
        ):
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_REVIEW_FAILED")
        round_receipt = {
            "round": number,
            "staged_tree_sha": staged_tree,
            "changed_paths": list(
                sorted(
                    path
                    for path in _run(
                        ["git", "diff", "--cached", "--name-only"], cwd=source
                    ).splitlines()
                    if path
                )
            ),
            "material_problems_found": [],
        }
        round_receipt["round_sha256"] = hashlib.sha256(
            _canonical(round_receipt)
        ).hexdigest()
        rounds.append(round_receipt)
    result = {"staged_tree_sha": staged_tree, "rounds": rounds}
    _write_canonical(root / "binding-review-rounds-v1.json", result)
    return result


def _event(
    state: CatalogBootstrapStateV1,
    name: str,
    evidence: object,
) -> CatalogBootstrapEventV1:
    return CatalogBootstrapEventV1(
        schema_version="1",
        bootstrap_id=state.bootstrap_id,
        sequence=state.sequence + 1,
        name=name,  # type: ignore[arg-type]
        protected_commit_sha=state.protected_commit_sha,
        observed_at=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        evidence_sha256=hashlib.sha256(_canonical(evidence)).hexdigest(),
    )


def _advance(
    root: Path,
    state: CatalogBootstrapStateV1,
    name: str,
    evidence: object,
) -> None:
    persist_bootstrap_state(
        _state_path(root),
        advance_bootstrap_state(state, _event(state, name, evidence)),
    )


def perform_precheck(root: Path) -> None:
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    context = _context(root)
    source = Path(str(context["source_root"]))
    head = _run(["git", "rev-parse", "HEAD"], cwd=source)
    if head != context["source_commit_sha"]:
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_COMMIT_CHANGED")
    if _run(["git", "status", "--porcelain=v1", "--untracked-files=no"], cwd=source):
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_DIRTY")
    enabled = _run(
        ["gh", "variable", "get", "CATALOG_CONTROLLER_ENABLED", "--repo", REPOSITORY]
    )
    if enabled != "false":
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_NOT_DISABLED")
    baseline = _github_activity_snapshot()
    _write_canonical(root / "github-activity-baseline-v1.json", baseline)
    state = initial_bootstrap_state(
        f"bootstrap-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}",
        head,
    )
    persist_bootstrap_state(_state_path(root), state)
    _advance(
        root,
        state,
        "precheck_passed",
        {"head": head, "enabled": enabled, "activity": baseline},
    )


def _stop_hp_codex_processes() -> None:
    command = (
        "$rows=Get-CimInstance Win32_Process | Where-Object {$_.Name -in "
        "@('ChatGPT.exe','codex.exe')}; foreach($p in $rows){"
        "$o=Invoke-CimMethod -InputObject $p -MethodName GetOwner;"
        "if($o.User -eq 'HP'){Stop-Process -Id $p.ProcessId -Force}};"
        "Start-Sleep -Milliseconds 500; $left=Get-CimInstance Win32_Process | "
        "Where-Object {$_.Name -in @('ChatGPT.exe','codex.exe')};"
        "foreach($p in $left){$o=Invoke-CimMethod -InputObject $p -MethodName GetOwner;"
        "if($o.User -eq 'HP'){exit 17}}"
    )
    _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]
    )


def _create_app(root: Path, kind: str) -> None:
    state = load_bootstrap_state(_state_path(root))
    app: CatalogBootstrapAppManifestV1 = getattr(_manifests(), kind)
    session = start_manifest_session(kind, now=datetime.now(tz=UTC))  # type: ignore[arg-type]
    with ManifestLoopbackServer(session, app) as server:
        _write_canonical(
            root / "browser-action-v1.json",
            {
                "schema_version": "1",
                "action": f"create_{kind}_app",
                "url": server.start_url,
                "expires_at": session.expires_at.isoformat().replace("+00:00", "Z"),
            },
        )
        accepted = server.wait(timeout_seconds=3600)
    conversion = exchange_manifest_code(accepted.query["code"])
    try:
        binding = derive_public_binding(
            kind=kind,
            app_id=conversion.app_id,
            slug=conversion.slug,
            private_key_pem=conversion.private_key_pem,
        )
        secret_root = root / "secrets"
        secret_root.mkdir(parents=True, exist_ok=True)
        store_requester_key_once(
            secret_root / f"{kind}-pending.pem",
            conversion.private_key_pem,
        )
        public = {
            "app_id": binding.app_id,
            "app_slug": binding.app_slug,
            "kind": kind,
            "public_key_pem": binding.public_key_pem.decode("ascii"),
            "public_key_sha256": binding.public_key_sha256,
        }
        (root / f"{kind}-public-v1.json").write_bytes(_canonical(public) + b"\n")
    finally:
        conversion.clear()
        (root / "browser-action-v1.json").unlink(missing_ok=True)
    name = "requester_created" if kind == "requester" else "auditor_created"
    _advance(root, state, name, public)


def create_requester(root: Path) -> None:
    _create_app(root, "requester")


def create_auditor(root: Path) -> None:
    _create_app(root, "auditor")


def _verify_installation(root: Path, kind: str) -> None:
    state = load_bootstrap_state(_state_path(root))
    app = getattr(_manifests(), kind)
    public_path = root / f"{kind}-public-v1.json"
    public = _read_json(public_path)
    key_buffer = bytearray((root / f"secrets/{kind}-pending.pem").read_bytes())
    client = CatalogBootstrapGitHubClient(
        app_id=int(public["app_id"]),
        private_key_pem=key_buffer,
    )
    install_url = f"https://github.com/apps/{public['app_slug']}/installations/new"
    _write_canonical(
        root / "browser-action-v1.json",
        {
            "schema_version": "1",
            "action": f"install_{kind}_app",
            "url": install_url,
        },
    )
    deadline = time.monotonic() + 3600
    while True:
        try:
            access = client.find_exact_installation(app)
            break
        except ValueError as exc:
            if str(exc) != "APP_INSTALLATION_NOT_EXACT" or time.monotonic() >= deadline:
                client.close()
                raise
            time.sleep(5)
    client.close()
    (root / "browser-action-v1.json").unlink(missing_ok=True)
    public["installation_id"] = access.installation_id
    public_path.write_bytes(_canonical(public) + b"\n")
    name = "requester_installed" if kind == "requester" else "auditor_installed"
    _advance(root, state, name, public)


def verify_requester_installation(root: Path) -> None:
    _verify_installation(root, "requester")


def verify_auditor_installation(root: Path) -> None:
    _verify_installation(root, "auditor")


def _public_binding(root: Path, kind: str) -> CatalogAppPublicBinding:
    value = _read_json(root / f"{kind}-public-v1.json")
    return CatalogAppPublicBinding(
        kind=kind,
        app_id=int(value["app_id"]),
        app_slug=str(value["app_slug"]),
        public_key_pem=str(value["public_key_pem"]).encode("ascii"),
        public_key_sha256=str(value["public_key_sha256"]),
    )


def _authority_issue() -> dict[str, object]:
    raw = _run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"/repos/{REPOSITORY}/issues?state=all&per_page=100",
        ]
    )
    pages = json.loads(raw)
    rows = [item for page in pages for item in page]
    exact_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("title") == "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT"
        and "pull_request" not in row
    ]
    if not exact_rows:
        created = json.loads(
            _run_with_input(
                [
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    f"/repos/{REPOSITORY}/issues",
                    "--input",
                    "-",
                ],
                {
                    "body": "AURORA CATALOG AUTHORITY LEDGER V1\n",
                    "title": "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT",
                },
            )
        )
        exact_rows = [created]
    if len(exact_rows) != 1 or not isinstance(exact_rows[0].get("number"), int):
        raise ValueError("MULTIPLE_ANCHORS")
    comment_pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/issues/{exact_rows[0]['number']}/comments?per_page=100",
            ]
        )
    )
    comments = [row for page in comment_pages for row in page]
    if comments:
        raise ValueError("AUTHORITY_ANCHOR_NOT_EMPTY")
    candidates = [
        {
            "repository": REPOSITORY,
            "repository_node_id": json.loads(
                _run(["gh", "api", f"/repos/{REPOSITORY}"])
            )["node_id"],
            "number": row.get("number"),
            "node_id": row.get("node_id"),
            "title": row.get("title"),
            "creator_login": row.get("user", {}).get("login"),
            "created_at": row.get("created_at"),
        }
        for row in exact_rows
    ]
    return dict(create_or_verify_authority_anchor(candidates))


def apply_public_binding(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    requester = _public_binding(root, "requester")
    auditor = _public_binding(root, "auditor")
    authority = _authority_issue()
    tree = {
        path: (source / path).read_bytes()
        for path in (
            "config/catalog_controller_actors_v1.json",
            "config/catalog_github_auditor_v1.json",
        )
    }
    patch = build_public_binding_patch(requester, auditor, authority, tree)
    branch_hash = hashlib.sha256(
        f"{requester.app_id}:{auditor.app_id}".encode()
    ).hexdigest()[:12]
    branch = f"catalog/bootstrap-binding-{branch_hash}"
    _run(["git", "fetch", "origin", "main"], cwd=source)
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=source,
        check=False,
    ).returncode == 0
    if existing:
        _run(["git", "switch", branch], cwd=source)
    else:
        _run(["git", "switch", "--create", branch, "origin/main"], cwd=source)
    for relative, data in patch.documents.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _run(["git", "add", "--", *patch.changed_paths], cwd=source)
    changed = tuple(
        sorted(
            line
            for line in _run(
                ["git", "diff", "--cached", "--name-only"], cwd=source
            ).splitlines()
            if line
        )
    )
    if not changed and existing:
        committed = tuple(
            sorted(
                line
                for line in _run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                    cwd=source,
                ).splitlines()
                if line
            )
        )
        ahead = _run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=source)
        if committed != patch.changed_paths or ahead != "1":
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_REPLAY_INVALID")
        review = _read_json(root / "binding-review-rounds-v1.json")
    else:
        if changed != patch.changed_paths:
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_DIFF_INVALID")
        if _run(["git", "diff", "--cached", "--check"], cwd=source):
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_DIFF_INVALID")
        review = _run_binding_review_rounds(root, source)
        commit_result = subprocess.run(
            ["git", "commit", "-m", "chore: bind catalog controller identities"],
            cwd=source,
            check=False,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode != 0:
            raise ValueError("CATALOG_BOOTSTRAP_BINDING_COMMIT_FAILED")
    head = _run(["git", "rev-parse", "HEAD"], cwd=source)
    _run(["git", "push", "--set-upstream", "origin", branch], cwd=source)
    listed = json.loads(
        _run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                REPOSITORY,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number,headRefOid",
            ]
        )
    )
    if len(listed) > 1:
        raise ValueError("MULTIPLE_BOOTSTRAP_PRS")
    if listed:
        pr_number = int(listed[0]["number"])
    else:
        url = _run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                REPOSITORY,
                "--base",
                "main",
                "--head",
                branch,
                "--title",
                "chore: bind catalog controller identities",
                "--body",
                "Automated public-only catalog bootstrap binding.",
            ],
            cwd=source,
        )
        pr_number = int(url.rstrip("/").split("/")[-1])
    receipt = {
        "binding_commit_sha": head,
        "branch": branch,
        "pr_number": pr_number,
        "review_rounds_sha256": hashlib.sha256(_canonical(review)).hexdigest(),
    }
    (root / "public-binding-operation-v1.json").write_bytes(
        _canonical(receipt) + b"\n"
    )
    _advance(root, state, "public_binding_committed", receipt)


def merge_public_binding(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    receipt = _read_json(root / "public-binding-operation-v1.json")
    pr_number = str(receipt["pr_number"])
    checks = subprocess.run(
        ["gh", "pr", "checks", pr_number, "--repo", REPOSITORY, "--required", "--watch"],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if checks.returncode != 0:
        raise ValueError("BOOTSTRAP_PR_NOT_READY")
    _run(
        ["gh", "pr", "merge", pr_number, "--repo", REPOSITORY, "--merge"],
        cwd=source,
    )
    observed = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                REPOSITORY,
                "--json",
                "state,mergeCommit",
            ]
        )
    )
    merge_sha = observed.get("mergeCommit", {}).get("oid")
    if observed.get("state") != "MERGED" or not isinstance(merge_sha, str):
        raise ValueError("BOOTSTRAP_PR_MERGE_UNVERIFIED")
    _run(["git", "fetch", "origin", "main"], cwd=source)
    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            str(receipt["binding_commit_sha"]),
            merge_sha,
        ],
        cwd=source,
        timeout=1800,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValueError("BOOTSTRAP_PR_MERGE_UNVERIFIED")
    receipt["merge_commit_sha"] = merge_sha
    (root / "public-binding-operation-v1.json").write_bytes(
        _canonical(receipt) + b"\n"
    )
    _advance(root, state, "protected_merge_observed", receipt)


def install_local_components(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    binding = _read_json(root / "public-binding-operation-v1.json")
    merge_sha = str(binding["merge_commit_sha"])
    _run(["git", "switch", "--detach", merge_sha], cwd=source)
    staging = Path("C:/ProgramData/AURORA/BootstrapStaging")
    apps = staging / "requester-apps"
    staging.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "icacls.exe",
            str(staging),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(OI)(CI)(F)",
            "*S-1-5-32-544:(OI)(CI)(F)",
        ]
    )
    _run(
        [
            "C:/Python314/python.exe",
            str(source / "scripts/build_catalog_requester_apps.py"),
            "--source-root",
            str(source),
            "--output-dir",
            str(apps),
            "--expected-commit-sha",
            merge_sha,
        ],
        cwd=source,
        timeout_seconds=1800,
    )
    requester_key = root / "secrets/requester-pending.pem"
    staged_key = staging / "requester-private-key.pem"
    if not staged_key.exists():
        staged_key.write_bytes(requester_key.read_bytes())
    _run(
        [
            "icacls.exe",
            str(staged_key),
            "/inheritance:r",
            "/grant:r",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ]
    )
    requester = _read_json(root / "requester-public-v1.json")
    app_id = str(requester["app_id"])
    installation_id = str(requester["installation_id"])
    setup_environment = (
        f"[Environment]::SetEnvironmentVariable('AURORA_CATALOG_REQUESTER_APP_ID','{app_id}','Machine');"
        f"[Environment]::SetEnvironmentVariable('AURORA_CATALOG_REQUESTER_INSTALLATION_ID','{installation_id}','Machine')"
    )
    _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", setup_environment])
    agent_receipt = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/install_catalog_agent_sandbox.ps1"),
            "-Apply",
            "-Confirm",
            "AURORA_CATALOG_AGENT_SANDBOX_V1",
        ],
        cwd=source,
        timeout_seconds=1800,
    )
    broker_receipt = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/install_catalog_requester_broker.ps1"),
            "-Apply",
            "-Confirm",
            "AURORA_CATALOG_REQUESTER_BROKER_V1",
        ],
        cwd=source,
        timeout_seconds=1800,
    )
    _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Start-ScheduledTask -TaskName 'AURORA Catalog Requester Broker'; Start-Sleep -Seconds 2; if((Get-ScheduledTask -TaskName 'AURORA Catalog Requester Broker').State -ne 'Running'){exit 19}",
        ]
    )
    if staged_key.exists():
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STAGING_NOT_CLEARED")
    installed_key = BROKER_ROOT / "secrets/requester-private-key.pem"
    if not installed_key.is_file():
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_KEY_NOT_INSTALLED")
    requester_key.unlink()
    if requester_key.exists():
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_STAGING_NOT_CLEARED")
    receipt = {
        "agent": json.loads(agent_receipt.splitlines()[-1]),
        "broker": json.loads(broker_receipt.splitlines()[-1]),
        "merge_commit_sha": merge_sha,
    }
    (root / "local-install-receipt-v1.json").write_bytes(_canonical(receipt) + b"\n")
    _advance(root, state, "local_install_verified", receipt)


def apply_github_controls(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    binding = _read_json(root / "public-binding-operation-v1.json")
    protected_commit_sha = str(binding["merge_commit_sha"])
    authority = _read_json(source / "config/catalog_authority_anchor_v1.json")
    auditor = _read_json(root / "auditor-public-v1.json")
    if (
        not _COMMIT.fullmatch(protected_commit_sha)
        or authority.get("production_enabled") is not True
        or not isinstance(authority.get("issue_number"), int)
        or not isinstance(auditor.get("app_id"), int)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_PUBLIC_BINDING_INVALID")
    _set_repository_variable(CONTROLLER_VARIABLE, "false")
    _set_repository_variable(
        "CATALOG_AUTHORITY_ISSUE_NUMBER", str(authority["issue_number"])
    )
    dry_path = root / "receipts/github-controls-dry-run-v1.json"
    _run(
        [
            "C:/Python314/python.exe",
            str(source / "scripts/apply_catalog_github_controls.py"),
            "--repo-root",
            str(source),
            "--output",
            str(dry_path),
        ],
        cwd=source,
        timeout_seconds=900,
    )
    dry = _read_json(dry_path)
    current_sha = str(dry.get("current_receipt_sha256", ""))
    if not _SHA256.fullmatch(current_sha):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_DRY_RUN_INVALID")
    apply_path = root / "receipts/github-controls-apply-v1.json"
    _run(
        [
            "C:/Python314/python.exe",
            str(source / "scripts/apply_catalog_github_controls.py"),
            "--repo-root",
            str(source),
            "--output",
            str(apply_path),
            "--apply",
            "--bootstrap-controls-only",
            "--expected-current-sha",
            current_sha,
            "--confirm",
            "CATALOG_GITHUB_CONTROLS_V1",
        ],
        cwd=source,
        timeout_seconds=900,
    )
    applied = _read_json(apply_path)
    if applied.get("bootstrap_controls_prepared") is not True and (
        not isinstance(applied.get("after_receipt"), dict)
        or applied["after_receipt"].get("status") != "ready"  # type: ignore[index]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_NOT_PREPARED")
    _set_repository_variable("AURORA_CATALOG_AUDITOR_APP_ID", str(auditor["app_id"]))
    pending = root / "secrets/auditor-pending.pem"
    staging = root / "secrets/auditor-upload-once.pem"
    proof = upload_auditor_key_once(staging, bytearray(pending.read_bytes()))
    pending.unlink()
    if pending.exists() or staging.exists():
        raise ValueError("CATALOG_BOOTSTRAP_AUDITOR_STAGING_NOT_CLEARED")
    live = _run_live_qualification(root, protected_commit_sha)
    receipt = {
        "protected_commit_sha": protected_commit_sha,
        "apply_receipt_sha256": hashlib.sha256(apply_path.read_bytes()).hexdigest(),
        "auditor_secret_name": proof.get("name"),
        "first_live_qualification": live,
    }
    _write_canonical(root / "github-controls-operation-v1.json", receipt)
    _advance(root, state, "github_controls_verified", receipt)


def _parse_terminal_controller_receipt(issue_number: int) -> dict[str, object]:
    pages = json.loads(
        _run(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"/repos/{REPOSITORY}/issues/{issue_number}/comments?per_page=100",
            ]
        )
    )
    rows = [row for page in pages for row in page]
    marker = "<!-- AURORA_CATALOG_REQUEST_RECEIPT_V1 -->\n```json\n"
    receipts: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("body"), str):
            continue
        body = str(row["body"])
        user = row.get("user")
        if marker not in body:
            continue
        if (
            not isinstance(user, dict)
            or user.get("login") != "github-actions[bot]"
            or row.get("created_at") != row.get("updated_at")
            or body.count(marker) != 1
            or not body.endswith("\n```\n")
        ):
            raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
        encoded = body.split(marker, 1)[1][:-5]
        value = json.loads(encoded)
        if not isinstance(value, dict) or encoded.encode() != _canonical(value):
            raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
        receipts.append(value)
    exact = [
        row
        for row in receipts
        if row.get("issue_number") == issue_number
        and row.get("state") == "BLOCKED"
        and row.get("reason_code") == "CATALOG_CONTROLLER_DISABLED"
        and _SHA256.fullmatch(str(row.get("receipt_sha256", "")))
    ]
    if len(exact) != 1:
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
    identity = {key: value for key, value in exact[0].items() if key != "receipt_sha256"}
    if hashlib.sha256(_canonical(identity)).hexdigest() != exact[0]["receipt_sha256"]:
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_RECEIPT_INVALID")
    return exact[0]


def _invoke_bootstrap_request(source: Path) -> dict[str, object]:
    raw = _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/run_catalog_bootstrap_qualification_client.ps1"),
        ],
        cwd=source,
        timeout_seconds=300,
    )
    value = json.loads(raw.splitlines()[-1])
    if (
        not isinstance(value, dict)
        or value.get("campaign_key") != "controller-bootstrap-qualification-v1"
        or value.get("status") not in {"pending", "submitted"}
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_RECEIPT_INVALID")
    return value


def _seal_hash(payload: dict[str, object], field: str) -> str:
    unsigned = {**payload, field: "0" * 64}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _run_requester_qualification(root: Path, source: Path) -> dict[str, object]:
    ticket = BROKER_ROOT / "launch-tickets/controller-bootstrap-qualification-v1.ticket.json"
    deadline = time.monotonic() + 300
    while not ticket.is_file() and time.monotonic() < deadline:
        time.sleep(2)
    if not ticket.is_file():
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_TICKET_MISSING")
    first = _invoke_bootstrap_request(source)
    issue_number = first.get("issue_number")
    if not isinstance(issue_number, int) or issue_number < 1:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            time.sleep(2)
            first = _invoke_bootstrap_request(source)
            issue_number = first.get("issue_number")
            if isinstance(issue_number, int) and issue_number > 0:
                break
    if not isinstance(issue_number, int) or issue_number < 1:
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_ISSUE_MISSING")
    status_path = (
        BROKER_ROOT
        / "campaign-status/controller-bootstrap-qualification-v1.status.json"
    )
    deadline = time.monotonic() + 1200
    status: dict[str, object] = {}
    while time.monotonic() < deadline:
        if status_path.is_file():
            status = _read_json(status_path)
            if status.get("state") == "terminal":
                break
        time.sleep(5)
    if (
        status.get("state") != "terminal"
        or status.get("issue_number") != issue_number
        or not _SHA256.fullmatch(str(status.get("request_sha256", "")))
        or not _SHA256.fullmatch(str(status.get("submission_key_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_NOT_TERMINAL")
    issue = json.loads(_run(["gh", "api", f"/repos/{REPOSITORY}/issues/{issue_number}"]))
    requester = _read_json(root / "requester-public-v1.json")
    if (
        not isinstance(issue, dict)
        or issue.get("state") != "closed"
        or issue.get("state_reason") != "completed"
        or (issue.get("user") or {}).get("login") != f"{requester['app_slug']}[bot]"
        or (issue.get("closed_by") or {}).get("login") != "github-actions[bot]"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATION_ISSUE_INVALID")
    controller = _parse_terminal_controller_receipt(issue_number)
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    seal = {
        "schema_version": "1",
        "qualification_permanently_sealed": True,
        "qualification_submission_key_sha256": status["submission_key_sha256"],
        "qualification_request_sha256": status["request_sha256"],
        "qualification_issue_number": issue_number,
        "controller_receipt_sha256": controller["receipt_sha256"],
        "sealed_at": now,
        "bootstrap_seal_sha256": "0" * 64,
    }
    seal["bootstrap_seal_sha256"] = _seal_hash(seal, "bootstrap_seal_sha256")
    _write_canonical(BROKER_ROOT / "config/bootstrap-qualified-v1.seal.json", seal)
    second = _invoke_bootstrap_request(source)
    if (
        second.get("issue_number") != issue_number
        or second.get("request_sha256") != first.get("request_sha256")
    ):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_REPLAY_INVALID")
    return {
        "issue_number": issue_number,
        "submission_key_sha256": status["submission_key_sha256"],
        "request_sha256": status["request_sha256"],
        "controller_receipt_sha256": controller["receipt_sha256"],
        "bootstrap_seal_sha256": seal["bootstrap_seal_sha256"],
        "duplicate_call_proof_sha256": hashlib.sha256(
            _canonical({"first": first, "second": second})
        ).hexdigest(),
    }


def run_qualifications(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    binding = _read_json(root / "public-binding-operation-v1.json")
    protected_commit_sha = str(binding["merge_commit_sha"])
    controls = _read_json(root / "github-controls-operation-v1.json")
    live_receipts = [controls["first_live_qualification"]]
    for _ in range(2):
        live_receipts.append(_run_live_qualification(root, protected_commit_sha))
    file_hashes = [str(item["file_sha256"]) for item in live_receipts]  # type: ignore[index]
    if len(set(file_hashes)) != 3 or any(not _SHA256.fullmatch(value) for value in file_hashes):
        raise ValueError("CATALOG_BOOTSTRAP_QUALIFICATIONS_NOT_INDEPENDENT")
    for workflow in (
        "catalog-controller-policy-check.yml",
        "catalog-controller-qualification.yml",
    ):
        for _ in range(3):
            _dispatch_workflow(workflow, protected_commit_sha)
    capacity = _dispatch_workflow(
        "catalog-capacity-calibration.yml", protected_commit_sha
    )
    keeper = _dispatch_workflow("catalog-artifact-keeper.yml", protected_commit_sha)
    requester = _run_requester_qualification(root, source)
    baseline = _read_json(root / "github-activity-baseline-v1.json")
    current = _github_activity_snapshot()
    baseline_requests = set(baseline["request_issue_numbers"])  # type: ignore[arg-type]
    current_requests = set(current["request_issue_numbers"])  # type: ignore[arg-type]
    baseline_heavy = set(baseline["heavy_run_ids"])  # type: ignore[arg-type]
    current_heavy = set(current["heavy_run_ids"])  # type: ignore[arg-type]
    if current_requests - baseline_requests != {requester["issue_number"]}:
        raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_REQUEST_OBSERVED")
    if current_heavy - baseline_heavy:
        raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_RUN_OBSERVED")
    receipt = {
        "protected_commit_sha": protected_commit_sha,
        "live_qualifications": live_receipts,
        "qualification_receipt_sha256s": file_hashes,
        "capacity_run_id": capacity["databaseId"],
        "keeper_run_id": keeper["databaseId"],
        "requester_qualification": requester,
        "production_request_count": 0,
        "production_run_count": 0,
    }
    _write_canonical(root / "qualification-operation-v1.json", receipt)
    _advance(root, state, "qualification_passed", receipt)


def _codex_process_owners() -> list[dict[str, object]]:
    command = (
        "$r=@(); Get-CimInstance Win32_Process | Where-Object {$_.Name -in "
        "@('ChatGPT.exe','codex.exe')} | ForEach-Object {$o=Invoke-CimMethod "
        "-InputObject $_ -MethodName GetOwner; $r += [ordered]@{pid=$_.ProcessId;"
        "name=$_.Name;user=$o.User}}; $r | ConvertTo-Json -Compress"
    )
    raw = _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]
    )
    if not raw:
        return []
    value = json.loads(raw)
    rows = value if isinstance(value, list) else [value]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("CATALOG_BOOTSTRAP_PROCESS_AUDIT_INVALID")
    return rows


def launch_isolated_codex(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    source = Path(str(_context(root)["source_root"]))
    _stop_hp_codex_processes()
    _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/launch_catalog_codex_secure.ps1"),
        ],
        cwd=source,
        timeout_seconds=180,
    )
    deadline = time.monotonic() + 120
    owners: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        owners = _codex_process_owners()
        if owners and all(row.get("user") == "AURORAAgent" for row in owners):
            break
        time.sleep(3)
    if not owners or any(row.get("user") != "AURORAAgent" for row in owners):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_RESTART_INVALID")
    capability_raw = _run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "scripts/audit_catalog_agent_capabilities.ps1"),
        ],
        cwd=source,
        timeout_seconds=180,
    )
    capability = json.loads(capability_raw.splitlines()[-1])
    if not isinstance(capability, dict) or capability.get("identity") != "AURORAAgent":
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_CAPABILITY_INVALID")
    installed_profile = AGENT_ROOT / "profile/config.toml"
    source_profile = source / "config/catalog_agent_codex_profile_v1.toml"
    profile_bytes = installed_profile.read_bytes()
    normalized_profile = profile_bytes.replace(b"\r\n", b"\n")
    if profile_bytes != source_profile.read_bytes() or any(
        marker not in normalized_profile
        for marker in (
            b'[plugins."browser@openai-bundled"]\nenabled = false',
            b'[plugins."chrome@openai-bundled"]\nenabled = false',
            b'[plugins."computer-use@openai-bundled"]\nenabled = false',
            b'[plugins."codex-app-tools@openai-bundled"]\nenabled = false',
            b'sandbox = "unelevated"',
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_PROFILE_INVALID")
    receipt = {
        "processes": owners,
        "agent_process_owner": "AURORAAgent",
        "capability_audit": capability,
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "browser_connectors_disabled": True,
    }
    _write_canonical(root / "agent-restart-operation-v1.json", receipt)
    _advance(root, state, "agent_restart_verified", receipt)


def _application_sha256(kind: str) -> str:
    manifest = _read_json(BROKER_ROOT / f"bin/catalog-requester-{kind}.manifest.json")
    value = str(manifest.get("application_sha256", ""))
    if not _SHA256.fullmatch(value):
        raise ValueError("CATALOG_BOOTSTRAP_REQUESTER_MANIFEST_INVALID")
    return value


def _production_seal(
    protected_commit_sha: str,
    ready_receipt_bytes: bytes,
) -> CatalogBootstrapObservedProductionSealV1:
    payload: dict[str, object] = {
        "schema_version": "1",
        "production_enabled": True,
        "protected_commit_sha": protected_commit_sha,
        "bootstrap_receipt_sha256": hashlib.sha256(ready_receipt_bytes).hexdigest(),
        "requester_client_application_sha256": _application_sha256("client"),
        "requester_broker_application_sha256": _application_sha256("broker"),
        "sealed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "production_seal_sha256": "0" * 64,
    }
    payload["production_seal_sha256"] = _seal_hash(
        payload, "production_seal_sha256"
    )
    return CatalogBootstrapObservedProductionSealV1.model_validate(payload)


def perform_final_audit(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    binding = _read_json(root / "public-binding-operation-v1.json")
    protected_commit_sha = str(binding["merge_commit_sha"])
    qualification = _read_json(root / "qualification-operation-v1.json")
    applied_controls = _read_json(root / "receipts/github-controls-apply-v1.json")
    after_controls = applied_controls.get("after_receipt")
    if not isinstance(after_controls, dict):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RECEIPT_INVALID")
    zero_budgets = after_controls.get("actions_zero_spend_budgets")
    if not isinstance(zero_budgets, list) or len(zero_budgets) != 3:
        raise ValueError("CATALOG_BOOTSTRAP_ZERO_BUDGETS_INVALID")
    hashes = tuple(qualification["qualification_receipt_sha256s"])
    owners = _codex_process_owners()
    agent_operation = _read_json(root / "agent-restart-operation-v1.json")
    capability = agent_operation.get("capability_audit")
    if not isinstance(capability, dict) or any(
        capability.get(name) is not True
        for name in (
            "medium_or_lower_integrity",
            "requester_key_read_denied",
            "broker_code_read_denied",
            "processing_list_denied",
            "agent_credential_read_denied",
            "broker_write_denied",
            "elevated_helper_write_denied",
        )
    ):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_CAPABILITY_INVALID")
    if not owners or any(row.get("user") != "AURORAAgent" for row in owners):
        raise ValueError("CATALOG_BOOTSTRAP_AGENT_PROCESS_OWNER_INVALID")
    pre_enable = _run_live_qualification(root, protected_commit_sha)
    _set_repository_variable(CONTROLLER_VARIABLE, "true")
    try:
        post_enable = _run_live_qualification(root, protected_commit_sha)
        baseline = _read_json(root / "github-activity-baseline-v1.json")
        current = _github_activity_snapshot()
        requester = qualification["requester_qualification"]
        production_requests = set(current["request_issue_numbers"]) - set(  # type: ignore[arg-type]
            baseline["request_issue_numbers"]  # type: ignore[arg-type]
        ) - {requester["issue_number"]}  # type: ignore[index]
        production_runs = set(current["heavy_run_ids"]) - set(  # type: ignore[arg-type]
            baseline["heavy_run_ids"]  # type: ignore[arg-type]
        )
        evidence = CatalogBootstrapFinalEvidenceV1(
            schema_version="1",
            repository=REPOSITORY,
            protected_commit_sha=protected_commit_sha,
            public_binding_sha256=hashlib.sha256(
                (root / "public-binding-operation-v1.json").read_bytes()
            ).hexdigest(),
            merged_binding_verified=True,
            requester_installation_verified=True,
            auditor_installation_verified=True,
            requester_key_isolated=not (root / "secrets/requester-pending.pem").exists(),
            auditor_key_github_only=not (root / "secrets/auditor-pending.pem").exists(),
            local_identities_and_acls_verified=(
                (BROKER_ROOT / "config/acl-baseline-v1.json").is_file()
                and (BROKER_ROOT / "receipts/broker-self-audit-v1.receipt.json").is_file()
                and capability.get("is_admin") is False
                and capability.get("enabled_dangerous_privileges") == 0
                and capability.get("forbidden_environment_count") == 0
            ),
            agent_process_owner="AURORAAgent",
            hp_codex_process_count=sum(row.get("user") == "HP" for row in owners),
            github_controls_status="ready",
            zero_budget_count=len(zero_budgets),
            qualification_receipt_sha256s=hashes,
            qualification_equivalent=True,
            disabled_bootstrap_request_count=1,
            production_request_count=len(production_requests),
            production_run_count=len(production_runs),
            controller_enabled_readback=(
                _run(
                    [
                        "gh",
                        "variable",
                        "get",
                        CONTROLLER_VARIABLE,
                        "--repo",
                        REPOSITORY,
                    ]
                )
                == "true"
            ),
            post_enable_controls_status=(
                "ready"
                if post_enable["receipt"]["protected_commit_sha"]  # type: ignore[index]
                == protected_commit_sha
                else "blocked"
            ),
        )
        ready = finalize_bootstrap(evidence)
        ready_bytes = canonical_ready_receipt_bytes(ready)
        ready_path = BROKER_ROOT / "receipts/controller-bootstrap-v1.receipt.json"
        _write_canonical(ready_path, ready.model_dump(mode="json"))
        if ready_path.read_bytes() != ready_bytes:
            raise ValueError("CATALOG_BOOTSTRAP_READY_RECEIPT_READBACK_INVALID")
        seal = _production_seal(protected_commit_sha, ready_bytes)
        seal_path = BROKER_ROOT / "config/production-enabled-v1.seal.json"
        _write_canonical(seal_path, seal.model_dump(mode="json"))
        completion = complete_sealed_bootstrap(ready, seal)
        _write_canonical(
            root / "receipts/controller-bootstrap-completion-v1.receipt.json",
            completion.model_dump(mode="json"),
        )
        deadline = time.monotonic() + 300
        registry = _read_json(BROKER_ROOT / "config/catalog_campaign_registry_v1.json")
        active = {
            row["campaign_key"]
            for row in registry.get("campaigns", [])
            if isinstance(row, dict) and row.get("active") is True
        }
        while time.monotonic() < deadline:
            tickets = {
                path.name.removesuffix(".ticket.json")
                for path in (BROKER_ROOT / "launch-tickets").glob("*.ticket.json")
            }
            if tickets == active:
                break
            time.sleep(2)
        if tickets != active:
            raise ValueError("CATALOG_BOOTSTRAP_PRODUCTION_TICKETS_INVALID")
        self_audit_path = BROKER_ROOT / "receipts/broker-self-audit-v1.receipt.json"
        deadline = time.monotonic() + 120
        self_audit: dict[str, object] = {}
        while time.monotonic() < deadline:
            self_audit = _read_json(self_audit_path)
            if self_audit.get("status") == "production_sealed":
                break
            time.sleep(2)
        if (
            self_audit.get("status") != "production_sealed"
            or self_audit.get("production_seal_present") is not True
            or self_audit.get("broker_application_sha256")
            != seal.requester_broker_application_sha256
        ):
            raise ValueError("CATALOG_BOOTSTRAP_BROKER_FINAL_AUDIT_INVALID")
        final_activity = _github_activity_snapshot()
        final_production_requests = set(final_activity["request_issue_numbers"]) - set(  # type: ignore[arg-type]
            baseline["request_issue_numbers"]  # type: ignore[arg-type]
        ) - {requester["issue_number"]}  # type: ignore[index]
        final_production_runs = set(final_activity["heavy_run_ids"]) - set(  # type: ignore[arg-type]
            baseline["heavy_run_ids"]  # type: ignore[arg-type]
        )
        final_owners = _codex_process_owners()
        if (
            final_production_requests
            or final_production_runs
            or not final_owners
            or any(row.get("user") != "AURORAAgent" for row in final_owners)
            or _run(
                [
                    "gh",
                    "variable",
                    "get",
                    CONTROLLER_VARIABLE,
                    "--repo",
                    REPOSITORY,
                ]
            )
            != "true"
        ):
            raise ValueError("CATALOG_BOOTSTRAP_POST_ENABLE_DRIFT")
        final = {
            "ready_receipt_sha256": hashlib.sha256(ready_bytes).hexdigest(),
            "completion_receipt_sha256": completion.completion_receipt_sha256,
            "production_seal_sha256": seal.production_seal_sha256,
            "pre_enable_live_run_id": pre_enable["run_id"],
            "post_enable_live_run_id": post_enable["run_id"],
            "production_ticket_campaign_keys": sorted(tickets),
            "broker_self_audit_sha256": self_audit.get("self_audit_sha256"),
        }
        _write_canonical(root / "final-audit-operation-v1.json", final)
        _advance(root, state, "final_audit_passed", final)
    except Exception:
        _set_repository_variable(CONTROLLER_VARIABLE, "false")
        raise


PHASE_HANDLERS: dict[str, Callable[[Path], None]] = {
    "PRECHECK": perform_precheck,
    "REQUESTER_CREATE_PENDING": create_requester,
    "REQUESTER_INSTALL_PENDING": verify_requester_installation,
    "AUDITOR_CREATE_PENDING": create_auditor,
    "AUDITOR_INSTALL_PENDING": verify_auditor_installation,
    "PUBLIC_BINDING_PENDING": apply_public_binding,
    "MERGE_PENDING": merge_public_binding,
    "LOCAL_INSTALL_PENDING": install_local_components,
    "GITHUB_CONTROLS_PENDING": apply_github_controls,
    "QUALIFICATION_PENDING": run_qualifications,
    "AGENT_RESTART_PENDING": launch_isolated_codex,
    "FINAL_AUDIT_PENDING": perform_final_audit,
}


def run_phase(phase: str, installed_root: Path) -> None:
    try:
        handler = PHASE_HANDLERS[phase]
    except KeyError as exc:
        raise ValueError("CATALOG_BOOTSTRAP_PHASE_INVALID") from exc
    handler(installed_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed-root", type=Path, required=True)
    args = parser.parse_args()
    state_file = _state_path(args.installed_root)
    if not state_file.exists():
        perform_precheck(args.installed_root)
    state = load_bootstrap_state(state_file)
    while True:
        state = load_bootstrap_state(state_file)
        if state.phase in {"READY", "BLOCKED"}:
            return 0 if state.phase == "READY" else 2
        try:
            run_phase(state.phase, args.installed_root)
        except Exception as exc:
            try:
                _set_repository_variable(CONTROLLER_VARIABLE, "false")
            except Exception:
                pass
            reason = str(exc)
            if not reason or len(reason) > 160 or any(
                marker in reason.casefold()
                for marker in ("private", "secret", "token", "password", "jwt")
            ):
                reason = "CATALOG_BOOTSTRAP_PHASE_FAILED"
            blocked = {
                "schema_version": "1",
                "result": "BLOCKED",
                "phase": state.phase,
                "reason_code": reason,
                "controller_enabled_readback": False,
            }
            _write_canonical(
                args.installed_root / "receipts/controller-bootstrap-blocked-v1.json",
                blocked,
            )
            _advance(args.installed_root, state, "blocked", blocked)
            return 2


if __name__ == "__main__":
    raise SystemExit(main())

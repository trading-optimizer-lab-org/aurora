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
    clear_private_material,
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
BOOTSTRAP_STAGING_ROOT = Path("C:/ProgramData/AURORA/BootstrapStaging")
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
_PUBLIC_BINDING_PATHS = (
    "config/catalog_authority_anchor_v1.json",
    "config/catalog_controller_actors_v1.json",
    "config/catalog_github_auditor_v1.json",
    "config/catalog_requester_app_permissions_v1.json",
    "config/catalog_requester_public_key_v1.pem",
)
_LOCAL_INSTALL_REPAIR_PATHS = (
    "infra/sp500_megarun/catalog_bootstrap_state.py",
    "scripts/build_catalog_requester_apps.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/fixtures/catalog_controller_qualification/simulator.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS = (
    ".gitattributes",
    "scripts/build_catalog_requester_apps.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_COMPAT_REPAIR_PATHS = (
    "scripts/install_catalog_agent_sandbox.ps1",
    "scripts/install_catalog_requester_broker.ps1",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS = (
    "scripts/install_catalog_requester_broker.ps1",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_VERIFIER_REPAIR_PATHS = (
    "scripts/install_catalog_requester_broker.ps1",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_requester_packaging.py",
)
_LOCAL_INSTALL_ACL_REPAIR_PATHS = _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
_LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS = _LOCAL_INSTALL_ACL_REPAIR_PATHS
_LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS = (
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
)
_GITHUB_CONTROLS_REPAIR_PATHS = (
    "infra/sp500_megarun/catalog_bootstrap_state.py",
    "scripts/apply_catalog_github_controls.py",
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
    "tests/test_catalog_github_controls.py",
)
_GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS = (
    "scripts/run_catalog_bootstrap_assistant.py",
    "tests/test_catalog_bootstrap_assistant.py",
)
_BOOTSTRAP_REQUIRED_CHECK_NAMES = frozenset({"GTBI V7 stage-two required"})
_EXACT_REPOSITORY_REMOTES = frozenset(
    {
        "https://github.com/trading-optimizer-lab-org/aurora.git",
        "git@github.com:trading-optimizer-lab-org/aurora.git",
        "ssh://git@github.com/trading-optimizer-lab-org/aurora.git",
    }
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _repository_remote_is_exact(remote: str) -> bool:
    return remote in _EXACT_REPOSITORY_REMOTES


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
    env: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        env=env,
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


def _review_import_environment(root: Path, source: Path) -> dict[str, str]:
    source = source.resolve(strict=True)
    source_init = source / "__init__.py"
    if not source_init.is_file() or source_init.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    import_root = root / "review-import-v1"
    package_root = import_root / "aurora"
    package_root.mkdir(parents=True, exist_ok=True)
    shim = (
        "from pathlib import Path as _Path\n"
        f"_AURORA_SOURCE = _Path({json.dumps(str(source))})\n"
        "__path__ = [str(_AURORA_SOURCE)]\n"
        "__file__ = str(_AURORA_SOURCE / '__init__.py')\n"
        "exec(compile((_AURORA_SOURCE / '__init__.py').read_bytes(), "
        "__file__, 'exec'), globals(), globals())\n"
    ).encode("utf-8")
    shim_path = package_root / "__init__.py"
    if package_root.is_symlink() or shim_path.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    shim_path.write_bytes(shim)
    if shim_path.read_bytes() != shim:
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    sitecustomize = (
        "import importlib.util as _importlib_util\n"
        "import sys as _sys\n"
        "_sys.meta_path[:] = [\n"
        "    _finder for _finder in _sys.meta_path\n"
        "    if not getattr(_finder, '__module__', '').startswith("
        "'__editable___aurora_')\n"
        "]\n"
        f"_source = {json.dumps(str(source))}\n"
        "_spec = _importlib_util.spec_from_file_location("
        "'aurora', _source + '/__init__.py', "
        "submodule_search_locations=[_source])\n"
        "if _spec is None or _spec.loader is None:\n"
        "    raise RuntimeError('AURORA_SOURCE_IMPORT_FAILED')\n"
        "_module = _importlib_util.module_from_spec(_spec)\n"
        "_sys.modules['aurora'] = _module\n"
        "_spec.loader.exec_module(_module)\n"
    ).encode("utf-8")
    sitecustomize_path = import_root / "sitecustomize.py"
    if sitecustomize_path.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    sitecustomize_path.write_bytes(sitecustomize)
    if sitecustomize_path.read_bytes() != sitecustomize:
        raise ValueError("CATALOG_BOOTSTRAP_SOURCE_PACKAGE_INVALID")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "pythonpath"
    }
    environment["PYTHONPATH"] = str(import_root)
    return environment


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


def _list_recent_heavy_workflow_runs(
    workflow_path: str,
) -> list[dict[str, object]]:
    if workflow_path not in _HEAVY_WORKFLOW_PATHS:
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_FORBIDDEN")
    workflow_name = Path(workflow_path).name
    raw = _run(
        [
            "gh",
            "api",
            f"/repos/{REPOSITORY}/actions/workflows/{workflow_name}/runs"
            "?branch=main&per_page=100",
        ]
    )
    value = json.loads(raw)
    rows = value.get("workflow_runs") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("CATALOG_BOOTSTRAP_WORKFLOW_LIST_INVALID")
    return rows


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
    heavy = {
        int(row["id"])
        for workflow_path in _HEAVY_WORKFLOW_PATHS
        for row in _list_recent_heavy_workflow_runs(workflow_path)
        if isinstance(row.get("id"), int) and row.get("path") == workflow_path
    }
    return {
        "request_issue_numbers": sorted(requests),
        "heavy_run_ids": sorted(heavy),
    }


def _run_binding_review_rounds(root: Path, source: Path) -> dict[str, object]:
    staged_tree = _run(["git", "write-tree"], cwd=source)
    if not _COMMIT.fullmatch(staged_tree):
        raise ValueError("CATALOG_BOOTSTRAP_BINDING_TREE_INVALID")
    review_environment = _review_import_environment(root, source)
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
            env=review_environment,
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
            env=review_environment,
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


def _wait_for_required_checks(
    pr_number: str,
    source: Path,
    *,
    timeout_seconds: int = 1800,
    poll_seconds: int = 5,
) -> tuple[dict[str, str], ...]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "gh",
                "pr",
                "checks",
                pr_number,
                "--repo",
                REPOSITORY,
                "--required",
                "--json",
                "name,state,bucket",
            ],
            cwd=source,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        rows: object = None
        if result.stdout.strip():
            try:
                rows = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID") from exc
        if isinstance(rows, list) and rows:
            normalized: list[dict[str, str]] = []
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("name"), str)
                    or not isinstance(row.get("state"), str)
                    or row.get("bucket") not in {"pass", "pending", "fail", "cancel"}
                ):
                    raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
                normalized.append(
                    {
                        "bucket": str(row["bucket"]),
                        "name": str(row["name"]),
                        "state": str(row["state"]),
                    }
                )
            if len({row["name"] for row in normalized}) != len(normalized):
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
            if not _BOOTSTRAP_REQUIRED_CHECK_NAMES.issubset(
                {row["name"] for row in normalized}
            ):
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
            if any(row["bucket"] in {"fail", "cancel"} for row in normalized):
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECK_FAILED")
            if all(row["bucket"] == "pass" for row in normalized):
                return tuple(sorted(normalized, key=lambda row: row["name"]))
        elif rows is not None and rows != []:
            raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
        elif result.returncode != 0:
            message = f"{result.stdout}\n{result.stderr}".casefold()
            if "no required checks reported" not in message:
                raise ValueError("BOOTSTRAP_PR_REQUIRED_CHECKS_INVALID")
        time.sleep(poll_seconds)
    raise ValueError("BOOTSTRAP_PR_NOT_READY")


def _verify_existing_installations(root: Path) -> dict[str, int]:
    observed: dict[str, int] = {}
    manifests = _manifests()
    for kind in ("requester", "auditor"):
        public = _read_json(root / f"{kind}-public-v1.json")
        installation_id = public.get("installation_id")
        app_id = public.get("app_id")
        key_path = root / f"secrets/{kind}-pending.pem"
        if (
            not isinstance(installation_id, int)
            or not isinstance(app_id, int)
            or not key_path.is_file()
            or key_path.is_symlink()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        key_buffer = bytearray(key_path.read_bytes())
        client: CatalogBootstrapGitHubClient | None = None
        try:
            client = CatalogBootstrapGitHubClient(
                app_id=app_id,
                private_key_pem=key_buffer,
            )
            access = client.find_exact_installation(getattr(manifests, kind))
        finally:
            if client is None:
                clear_private_material(key_buffer)
            else:
                client.close()
        if access.installation_id != installation_id:
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        observed[kind] = installation_id
    return dict(sorted(observed.items()))


def _verify_post_install_installations(root: Path) -> dict[str, int]:
    observed: dict[str, int] = {}
    manifests = _manifests()
    key_paths = {
        "requester": BROKER_ROOT / "secrets/requester-private-key.pem",
        "auditor": root / "secrets/auditor-pending.pem",
    }
    for kind in ("requester", "auditor"):
        public = _read_json(root / f"{kind}-public-v1.json")
        installation_id = public.get("installation_id")
        app_id = public.get("app_id")
        key_path = key_paths[kind]
        if (
            not isinstance(installation_id, int)
            or not isinstance(app_id, int)
            or not key_path.is_file()
            or key_path.is_symlink()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        key_buffer = bytearray(key_path.read_bytes())
        client: CatalogBootstrapGitHubClient | None = None
        try:
            client = CatalogBootstrapGitHubClient(
                app_id=app_id,
                private_key_pem=key_buffer,
            )
            access = client.find_exact_installation(getattr(manifests, kind))
        finally:
            if client is None:
                clear_private_material(key_buffer)
            else:
                client.close()
        if access.installation_id != installation_id:
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_INSTALLATION_INVALID")
        observed[kind] = installation_id
    return dict(sorted(observed.items()))


def _validated_binding_review(
    root: Path,
    operation: dict[str, object],
) -> dict[str, object]:
    review_path = root / "binding-review-rounds-v1.json"
    review = _read_json(review_path)
    if (
        review_path.read_bytes() != _canonical(review) + b"\n"
        or
        hashlib.sha256(_canonical(review)).hexdigest()
        != operation.get("review_rounds_sha256")
        or not _COMMIT.fullmatch(str(review.get("staged_tree_sha", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
    rounds = review.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 3:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
    for expected_number, row in enumerate(rounds, 1):
        if not isinstance(row, dict):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
        unsigned = {key: value for key, value in row.items() if key != "round_sha256"}
        if (
            row.get("round") != expected_number
            or row.get("staged_tree_sha") != review["staged_tree_sha"]
            or tuple(row.get("changed_paths", ())) != _PUBLIC_BINDING_PATHS
            or row.get("material_problems_found") != []
            or row.get("round_sha256")
            != hashlib.sha256(_canonical(unsigned)).hexdigest()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_RETRY_REVIEW_INVALID")
    return review


def _resume_transient_merge_block(root: Path) -> bool:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "BLOCKED" or state.sequence != 7:
        return False
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked = _read_json(blocked_path)
    expected_block = {
        "controller_enabled_readback": False,
        "phase": "MERGE_PENDING",
        "reason_code": "BOOTSTRAP_PR_NOT_READY",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    if blocked != expected_block:
        return False
    if blocked_path.read_bytes() != _canonical(blocked) + b"\n":
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_BLOCK_RECEIPT_INVALID")
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    context = _context(root)
    source = Path(str(context["source_root"]))
    if source.is_symlink():
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_SOURCE_INVALID")
    source = source.resolve(strict=True)
    _run(["git", "fetch", "origin", "main"], cwd=source)
    current_commit = _run(["git", "rev-parse", "HEAD"], cwd=source)
    remote = _run(["git", "remote", "get-url", "origin"], cwd=source)
    if (
        current_commit != context["source_commit_sha"]
        or current_commit != _run(["git", "rev-parse", "origin/main"], cwd=source)
        or not _repository_remote_is_exact(remote)
        or _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=source,
        )
        or _run(["git", "branch", "--show-current"], cwd=source) != "main"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_SOURCE_INVALID")
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", state.protected_commit_sha, current_commit],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if ancestry.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_SOURCE_INVALID")
    if _run(
        ["gh", "variable", "get", CONTROLLER_VARIABLE, "--repo", REPOSITORY]
    ) != "false":
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_NOT_DISABLED")

    operation_path = root / "public-binding-operation-v1.json"
    operation = _read_json(operation_path)
    branch = operation.get("branch")
    pr_number = operation.get("pr_number")
    binding_commit = operation.get("binding_commit_sha")
    if (
        set(operation)
        != {"binding_commit_sha", "branch", "pr_number", "review_rounds_sha256"}
        or not isinstance(branch, str)
        or not re.fullmatch(r"catalog/bootstrap-binding-[0-9a-f]{12}", branch)
        or not isinstance(pr_number, int)
        or not isinstance(binding_commit, str)
        or not _COMMIT.fullmatch(binding_commit)
        or not _SHA256.fullmatch(str(operation.get("review_rounds_sha256", "")))
        or operation_path.read_bytes() != _canonical(operation) + b"\n"
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_OPERATION_INVALID")
    review = _validated_binding_review(root, operation)
    observed_pr = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefName,headRefOid",
            ],
            cwd=source,
        )
    )
    if not isinstance(observed_pr, dict):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    head_commit = observed_pr.get("headRefOid")
    if (
        observed_pr.get("state") != "OPEN"
        or observed_pr.get("baseRefName") != "main"
        or observed_pr.get("headRefName") != branch
        or not isinstance(head_commit, str)
        or not _COMMIT.fullmatch(head_commit)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    _run(["git", "fetch", "origin", branch], cwd=source)
    binding_ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", binding_commit, head_commit],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if binding_ancestry.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    changed_paths = tuple(
        sorted(
            path
            for path in _run(
                ["gh", "pr", "diff", str(pr_number), "--repo", REPOSITORY, "--name-only"],
                cwd=source,
            ).splitlines()
            if path
        )
    )
    if changed_paths != _PUBLIC_BINDING_PATHS:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_PR_INVALID")
    required_checks = _wait_for_required_checks(str(pr_number), source)
    installations = _verify_existing_installations(root)
    baseline = _read_json(root / "github-activity-baseline-v1.json")
    current_activity = _github_activity_snapshot()
    if current_activity != baseline:
        raise ValueError("CATALOG_BOOTSTRAP_RETRY_ACTIVITY_INVALID")
    recovery = {
        "binding_commit_sha": binding_commit,
        "blocked_state_sha256": hashlib.sha256(
            (root / "state/catalog-bootstrap-state-v1.json").read_bytes()
        ).hexdigest(),
        "head_commit_sha": head_commit,
        "installations": installations,
        "pr_number": pr_number,
        "required_checks": list(required_checks),
        "review_rounds_sha256": hashlib.sha256(_canonical(review)).hexdigest(),
        "source_commit_sha": current_commit,
    }
    _write_canonical(root / "receipts/controller-bootstrap-merge-retry-v1.json", recovery)
    _advance(root, state, "merge_retry_authorized", recovery)
    return True


def _local_install_repair_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_followup_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_compat_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_COMPAT_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_account_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_verifier_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_VERIFIER_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_acl_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_ACL_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_task_identity_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "--full-index",
            f"{base_commit}..{head_commit}",
            "--",
            *_LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _local_install_task_identity_followup_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
) -> str:
    result = subprocess.run(
        [
            "git", "diff", "--binary", "--full-index",
            f"{base_commit}..{head_commit}", "--",
            *_LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError(
            "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_PATCH_INVALID"
        )
    return hashlib.sha256(result.stdout).hexdigest()


def _github_controls_repair_patch_sha256(
    source: Path,
    base_commit: str,
    head_commit: str,
    changed_paths: tuple[str, ...] = _GITHUB_CONTROLS_REPAIR_PATHS,
) -> str:
    result = subprocess.run(
        [
            "git", "diff", "--binary", "--full-index",
            f"{base_commit}..{head_commit}", "--", *changed_paths,
        ],
        cwd=source,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_PATCH_INVALID")
    return hashlib.sha256(result.stdout).hexdigest()


def _verify_github_controls_repair_graph(
    source: Path,
    operation: dict[str, object],
) -> None:
    merge_commit = str(operation["merge_commit_sha"])
    if (
        _run(["git", "rev-parse", f"{merge_commit}^1"], cwd=source)
        != operation["base_commit_sha"]
        or _run(["git", "rev-parse", f"{merge_commit}^2"], cwd=source)
        != operation["head_commit_sha"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_GRAPH_INVALID")
    if (
        _github_controls_repair_patch_sha256(
            source,
            str(operation["base_commit_sha"]),
            str(operation["head_commit_sha"]),
            tuple(str(path) for path in operation["changed_paths"]),
        )
        != operation["patch_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PATCH_INVALID")


def _validated_local_install_repair(
    root: Path,
    binding: dict[str, object],
) -> dict[str, object]:
    repair_path = root / "local-install-repair-operation-v1.json"
    repair = _read_json(repair_path)
    changed_paths = repair.get("changed_paths")
    if (
        set(repair)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or repair_path.read_bytes() != _canonical(repair) + b"\n"
        or repair.get("schema_version") != "1"
        or repair.get("repository") != REPOSITORY
        or repair.get("base_commit_sha") != binding.get("merge_commit_sha")
        or not isinstance(repair.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-recovery-[0-9a-f]{12}",
            str(repair.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_REPAIR_PATHS
        or not isinstance(repair.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(repair.get("head_commit_sha")))
        or not isinstance(repair.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(repair.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(repair.get("patch_sha256", "")))
        or not isinstance(repair.get("pr_number"), int)
        or int(repair["pr_number"]) < 1
        or repair.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_INVALID")
    return repair


def _validated_local_install_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-followup-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-followup-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_REPAIR_INVALID")
    return operation


def _validated_local_install_compat_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-compat-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-compat-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_COMPAT_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_REPAIR_INVALID")
    return operation


def _validated_local_install_account_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-account-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-account-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_REPAIR_INVALID")
    return operation


def _validated_local_install_verifier_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-verifier-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha",
            "branch",
            "changed_paths",
            "head_commit_sha",
            "merge_commit_sha",
            "patch_sha256",
            "pr_number",
            "repository",
            "required_check",
            "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-verifier-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_REPAIR_INVALID")
    return operation


def _validated_local_install_acl_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-acl-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-acl-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_ACL_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_REPAIR_INVALID")
    return operation


def _validated_local_install_task_identity_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-task-identity-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-task-identity-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_INVALID")
    return operation


def _validated_local_install_task_identity_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "local-install-task-identity-followup-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-local-install-task-identity-followup-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths)
        != _LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_REPAIR_INVALID"
        )
    return operation


def _validated_github_controls_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-github-controls-recovery-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_INVALID")
    return operation


def _validated_github_controls_followup_repair(
    root: Path,
    prior_repair: dict[str, object],
) -> dict[str, object]:
    path = root / "github-controls-followup-repair-operation-v1.json"
    operation = _read_json(path)
    changed_paths = operation.get("changed_paths")
    if (
        set(operation)
        != {
            "base_commit_sha", "branch", "changed_paths", "head_commit_sha",
            "merge_commit_sha", "patch_sha256", "pr_number", "repository",
            "required_check", "schema_version",
        }
        or path.read_bytes() != _canonical(operation) + b"\n"
        or operation.get("schema_version") != "1"
        or operation.get("repository") != REPOSITORY
        or operation.get("base_commit_sha") != prior_repair.get("merge_commit_sha")
        or not isinstance(operation.get("branch"), str)
        or not re.fullmatch(
            r"codex/catalog-github-controls-followup-[0-9a-f]{12}",
            str(operation.get("branch")),
        )
        or not isinstance(changed_paths, list)
        or tuple(changed_paths) != _GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS
        or not isinstance(operation.get("head_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("head_commit_sha")))
        or not isinstance(operation.get("merge_commit_sha"), str)
        or not _COMMIT.fullmatch(str(operation.get("merge_commit_sha")))
        or not _SHA256.fullmatch(str(operation.get("patch_sha256", "")))
        or not isinstance(operation.get("pr_number"), int)
        or int(operation["pr_number"]) < 1
        or operation.get("required_check") not in _BOOTSTRAP_REQUIRED_CHECK_NAMES
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_INVALID")
    return operation


def _runtime_commit(root: Path) -> str:
    binding_path = root / "public-binding-operation-v1.json"
    binding = _read_json(binding_path)
    binding_merge = binding.get("merge_commit_sha")
    if (
        binding_path.read_bytes() != _canonical(binding) + b"\n"
        or not isinstance(binding_merge, str)
        or not _COMMIT.fullmatch(binding_merge)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_PUBLIC_BINDING_INVALID")
    retry_path = root / "receipts/controller-bootstrap-local-install-retry-v1.json"
    if not retry_path.exists():
        return binding_merge
    if retry_path.is_symlink() or retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_RECEIPT_INVALID")
    retry = _read_json(retry_path)
    repair = _validated_local_install_repair(root, binding)
    repair_merge = repair["merge_commit_sha"]
    if (
        set(retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "installations",
            "public_binding_merge_commit_sha",
            "repair_merge_commit_sha",
            "repair_operation_sha256",
            "repair_pr_number",
            "schema_version",
        }
        or retry_path.read_bytes() != _canonical(retry) + b"\n"
        or retry.get("schema_version") != "1"
        or retry.get("public_binding_merge_commit_sha") != binding_merge
        or retry.get("repair_merge_commit_sha") != repair_merge
        or retry.get("repair_pr_number") != repair.get("pr_number")
        or retry.get("repair_operation_sha256")
        != hashlib.sha256(_canonical(repair)).hexdigest()
        or not _SHA256.fullmatch(str(retry.get("activity_baseline_sha256", "")))
        or not _SHA256.fullmatch(str(retry.get("blocked_state_sha256", "")))
        or not _COMMIT.fullmatch(str(retry.get("bootstrap_source_commit_sha", "")))
        or not isinstance(retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_RECEIPT_INVALID")
    followup_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-2-v1.json"
    )
    if not followup_retry_path.exists():
        return str(repair_merge)
    if followup_retry_path.is_symlink() or followup_retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
    followup = _validated_local_install_followup_repair(root, repair)
    followup_retry = _read_json(followup_retry_path)
    followup_merge = followup["merge_commit_sha"]
    if (
        set(followup_retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "followup_merge_commit_sha",
            "followup_operation_sha256",
            "followup_pr_number",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or followup_retry_path.read_bytes() != _canonical(followup_retry) + b"\n"
        or followup_retry.get("schema_version") != "1"
        or followup_retry.get("prior_runtime_commit_sha") != repair_merge
        or followup_retry.get("followup_merge_commit_sha") != followup_merge
        or followup_retry.get("followup_pr_number") != followup.get("pr_number")
        or followup_retry.get("followup_operation_sha256")
        != hashlib.sha256(_canonical(followup)).hexdigest()
        or followup_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(followup_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(followup_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(followup_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(followup_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
    compat_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-3-v1.json"
    )
    if not compat_retry_path.exists():
        return str(followup_merge)
    if compat_retry_path.is_symlink() or compat_retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
    compat = _validated_local_install_compat_repair(root, followup)
    compat_retry = _read_json(compat_retry_path)
    compat_merge = compat["merge_commit_sha"]
    if (
        set(compat_retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "compat_merge_commit_sha",
            "compat_operation_sha256",
            "compat_pr_number",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or compat_retry_path.read_bytes() != _canonical(compat_retry) + b"\n"
        or compat_retry.get("schema_version") != "1"
        or compat_retry.get("prior_runtime_commit_sha") != followup_merge
        or compat_retry.get("compat_merge_commit_sha") != compat_merge
        or compat_retry.get("compat_pr_number") != compat.get("pr_number")
        or compat_retry.get("compat_operation_sha256")
        != hashlib.sha256(_canonical(compat)).hexdigest()
        or compat_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(followup_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(compat_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(compat_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(compat_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(compat_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
    account_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-4-v1.json"
    )
    if not account_retry_path.exists():
        return str(compat_merge)
    if account_retry_path.is_symlink() or account_retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
    account = _validated_local_install_account_repair(root, compat)
    account_retry = _read_json(account_retry_path)
    account_merge = account["merge_commit_sha"]
    if (
        set(account_retry)
        != {
            "account_merge_commit_sha",
            "account_operation_sha256",
            "account_pr_number",
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
        }
        or account_retry_path.read_bytes() != _canonical(account_retry) + b"\n"
        or account_retry.get("schema_version") != "1"
        or account_retry.get("prior_runtime_commit_sha") != compat_merge
        or account_retry.get("account_merge_commit_sha") != account_merge
        or account_retry.get("account_pr_number") != account.get("pr_number")
        or account_retry.get("account_operation_sha256")
        != hashlib.sha256(_canonical(account)).hexdigest()
        or account_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(compat_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(account_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(account_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(account_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(account_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
    verifier_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-5-v1.json"
    )
    if not verifier_retry_path.exists():
        return str(account_merge)
    if verifier_retry_path.is_symlink() or verifier_retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
    verifier = _validated_local_install_verifier_repair(root, account)
    verifier_retry = _read_json(verifier_retry_path)
    verifier_merge = verifier["merge_commit_sha"]
    if (
        set(verifier_retry)
        != {
            "activity_baseline_sha256",
            "blocked_state_sha256",
            "bootstrap_source_commit_sha",
            "installations",
            "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha",
            "schema_version",
            "verifier_merge_commit_sha",
            "verifier_operation_sha256",
            "verifier_pr_number",
        }
        or verifier_retry_path.read_bytes() != _canonical(verifier_retry) + b"\n"
        or verifier_retry.get("schema_version") != "1"
        or verifier_retry.get("prior_runtime_commit_sha") != account_merge
        or verifier_retry.get("verifier_merge_commit_sha") != verifier_merge
        or verifier_retry.get("verifier_pr_number") != verifier.get("pr_number")
        or verifier_retry.get("verifier_operation_sha256")
        != hashlib.sha256(_canonical(verifier)).hexdigest()
        or verifier_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(account_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(verifier_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(verifier_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(verifier_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(verifier_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
    acl_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-6-v1.json"
    )
    if not acl_retry_path.exists():
        return str(verifier_merge)
    if acl_retry_path.is_symlink() or acl_retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
    acl = _validated_local_install_acl_repair(root, verifier)
    acl_retry = _read_json(acl_retry_path)
    acl_merge = acl["merge_commit_sha"]
    if (
        set(acl_retry)
        != {
            "acl_merge_commit_sha", "acl_operation_sha256", "acl_pr_number",
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version",
        }
        or acl_retry_path.read_bytes() != _canonical(acl_retry) + b"\n"
        or acl_retry.get("schema_version") != "1"
        or acl_retry.get("prior_runtime_commit_sha") != verifier_merge
        or acl_retry.get("acl_merge_commit_sha") != acl_merge
        or acl_retry.get("acl_pr_number") != acl.get("pr_number")
        or acl_retry.get("acl_operation_sha256")
        != hashlib.sha256(_canonical(acl)).hexdigest()
        or acl_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(verifier_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(str(acl_retry.get("activity_baseline_sha256", "")))
        or not _SHA256.fullmatch(str(acl_retry.get("blocked_state_sha256", "")))
        or not _COMMIT.fullmatch(str(acl_retry.get("bootstrap_source_commit_sha", "")))
        or not isinstance(acl_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
    task_identity_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-7-v1.json"
    )
    task_identity_operation_path = (
        root / "local-install-task-identity-repair-operation-v1.json"
    )
    if not task_identity_operation_path.exists():
        return str(acl_merge)
    if (
        task_identity_operation_path.is_symlink()
        or task_identity_operation_path.is_junction()
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_INVALID")
    task_identity = _validated_local_install_task_identity_repair(root, acl)
    task_identity_merge = task_identity["merge_commit_sha"]
    if not task_identity_retry_path.exists():
        return str(task_identity_merge)
    if (
        task_identity_retry_path.is_symlink()
        or task_identity_retry_path.is_junction()
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_RETRY_RECEIPT_INVALID")
    task_identity_followup = (
        _validated_local_install_task_identity_followup_repair(root, task_identity)
    )
    task_identity_retry = _read_json(task_identity_retry_path)
    task_identity_followup_merge = task_identity_followup["merge_commit_sha"]
    if (
        set(task_identity_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "installations",
            "prior_retry_receipt_sha256", "prior_runtime_commit_sha",
            "schema_version", "task_identity_followup_merge_commit_sha",
            "task_identity_followup_operation_sha256",
            "task_identity_followup_pr_number",
        }
        or task_identity_retry_path.read_bytes()
        != _canonical(task_identity_retry) + b"\n"
        or task_identity_retry.get("schema_version") != "1"
        or task_identity_retry.get("prior_runtime_commit_sha")
        != task_identity_merge
        or task_identity_retry.get("task_identity_followup_merge_commit_sha")
        != task_identity_followup_merge
        or task_identity_retry.get("task_identity_followup_pr_number")
        != task_identity_followup.get("pr_number")
        or task_identity_retry.get("task_identity_followup_operation_sha256")
        != hashlib.sha256(_canonical(task_identity_followup)).hexdigest()
        or task_identity_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(acl_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(task_identity_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(task_identity_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(task_identity_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(task_identity_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_RETRY_RECEIPT_INVALID")
    github_controls_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-v1.json"
    )
    if not github_controls_retry_path.exists():
        return str(task_identity_followup_merge)
    if (
        github_controls_retry_path.is_symlink()
        or github_controls_retry_path.is_junction()
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    github_controls = _validated_github_controls_repair(
        root, task_identity_followup
    )
    github_controls_retry = _read_json(github_controls_retry_path)
    github_controls_merge = github_controls["merge_commit_sha"]
    if (
        set(github_controls_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "github_controls_merge_commit_sha",
            "github_controls_operation_sha256", "github_controls_pr_number",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or github_controls_retry_path.read_bytes()
        != _canonical(github_controls_retry) + b"\n"
        or github_controls_retry.get("schema_version") != "1"
        or github_controls_retry.get("prior_runtime_commit_sha")
        != task_identity_followup_merge
        or github_controls_retry.get("github_controls_merge_commit_sha")
        != github_controls_merge
        or github_controls_retry.get("github_controls_pr_number")
        != github_controls.get("pr_number")
        or github_controls_retry.get("github_controls_operation_sha256")
        != hashlib.sha256(_canonical(github_controls)).hexdigest()
        or github_controls_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(task_identity_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(github_controls_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(github_controls_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(github_controls_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(github_controls_retry.get("installations"), dict)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-2-v1.json"
    )
    if not followup_retry_path.exists():
        return str(github_controls_merge)
    if followup_retry_path.is_symlink() or followup_retry_path.is_junction():
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_RETRY_INVALID"
        )
    followup = _validated_github_controls_followup_repair(
        root, github_controls
    )
    followup_retry = _read_json(followup_retry_path)
    followup_merge = followup["merge_commit_sha"]
    if (
        set(followup_retry)
        != {
            "activity_baseline_sha256", "blocked_state_sha256",
            "bootstrap_source_commit_sha", "followup_merge_commit_sha",
            "followup_operation_sha256", "followup_pr_number",
            "installations", "prior_retry_receipt_sha256",
            "prior_runtime_commit_sha", "schema_version",
        }
        or followup_retry_path.read_bytes()
        != _canonical(followup_retry) + b"\n"
        or followup_retry.get("schema_version") != "1"
        or followup_retry.get("prior_runtime_commit_sha")
        != github_controls_merge
        or followup_retry.get("followup_merge_commit_sha") != followup_merge
        or followup_retry.get("followup_pr_number") != followup.get("pr_number")
        or followup_retry.get("followup_operation_sha256")
        != hashlib.sha256(_canonical(followup)).hexdigest()
        or followup_retry.get("prior_retry_receipt_sha256")
        != hashlib.sha256(github_controls_retry_path.read_bytes()).hexdigest()
        or not _SHA256.fullmatch(
            str(followup_retry.get("activity_baseline_sha256", ""))
        )
        or not _SHA256.fullmatch(
            str(followup_retry.get("blocked_state_sha256", ""))
        )
        or not _COMMIT.fullmatch(
            str(followup_retry.get("bootstrap_source_commit_sha", ""))
        )
        or not isinstance(followup_retry.get("installations"), dict)
    ):
        raise ValueError(
            "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_RETRY_INVALID"
        )
    return str(followup_merge)


def _resume_transient_local_install_block(root: Path) -> bool:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "BLOCKED" or state.sequence not in {10, 12, 14, 16, 18, 20, 22}:
        return False
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked = _read_json(blocked_path)
    expected_block = {
        "controller_enabled_readback": False,
        "phase": "LOCAL_INSTALL_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    if blocked != expected_block:
        return False
    if blocked_path.read_bytes() != _canonical(blocked) + b"\n":
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_BLOCK_RECEIPT_INVALID")
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    followup_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-2-v1.json"
    )
    if state.sequence == 12 and followup_retry_path.exists():
        evidence = _read_json(followup_retry_path)
        if _runtime_commit(root) != evidence.get("followup_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    compat_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-3-v1.json"
    )
    if state.sequence == 14 and compat_retry_path.exists():
        evidence = _read_json(compat_retry_path)
        if _runtime_commit(root) != evidence.get("compat_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    account_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-4-v1.json"
    )
    if state.sequence == 16 and account_retry_path.exists():
        evidence = _read_json(account_retry_path)
        if _runtime_commit(root) != evidence.get("account_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    verifier_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-5-v1.json"
    )
    if state.sequence == 18 and verifier_retry_path.exists():
        evidence = _read_json(verifier_retry_path)
        if _runtime_commit(root) != evidence.get("verifier_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    acl_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-6-v1.json"
    )
    if state.sequence == 20 and acl_retry_path.exists():
        evidence = _read_json(acl_retry_path)
        if _runtime_commit(root) != evidence.get("acl_merge_commit_sha"):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True
    task_identity_retry_path = (
        root / "receipts/controller-bootstrap-local-install-retry-7-v1.json"
    )
    if state.sequence == 22 and task_identity_retry_path.exists():
        evidence = _read_json(task_identity_retry_path)
        if _runtime_commit(root) != evidence.get(
            "task_identity_followup_merge_commit_sha"
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_RETRY_RECEIPT_INVALID"
            )
        _advance(root, state, "local_install_retry_authorized", evidence)
        return True

    context_path = root / "install-context-v1.json"
    context = _context(root)
    source_commit = context.get("source_commit_sha")
    if (
        context_path.read_bytes() != _canonical(context) + b"\n"
        or not isinstance(source_commit, str)
        or not _COMMIT.fullmatch(source_commit)
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_CONTEXT_INVALID")
    source = Path(str(context["source_root"]))
    if source.is_symlink() or source.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_SOURCE_INVALID")
    source = source.resolve(strict=True)

    operation_path = root / "public-binding-operation-v1.json"
    operation = _read_json(operation_path)
    binding_branch = operation.get("branch")
    binding_pr_number = operation.get("pr_number")
    binding_commit = operation.get("binding_commit_sha")
    binding_merge = operation.get("merge_commit_sha")
    if (
        set(operation)
        != {
            "binding_commit_sha",
            "branch",
            "merge_commit_sha",
            "pr_number",
            "review_rounds_sha256",
        }
        or operation_path.read_bytes() != _canonical(operation) + b"\n"
        or not isinstance(binding_branch, str)
        or not re.fullmatch(
            r"catalog/bootstrap-binding-[0-9a-f]{12}",
            binding_branch,
        )
        or not isinstance(binding_pr_number, int)
        or binding_pr_number < 1
        or not isinstance(binding_commit, str)
        or not _COMMIT.fullmatch(binding_commit)
        or not isinstance(binding_merge, str)
        or not _COMMIT.fullmatch(binding_merge)
        or not _SHA256.fullmatch(str(operation.get("review_rounds_sha256", "")))
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_OPERATION_INVALID")

    repair = _validated_local_install_repair(root, operation)
    repair_branch = str(repair["branch"])
    repair_head = str(repair["head_commit_sha"])
    repair_merge = str(repair["merge_commit_sha"])
    repair_pr_number = int(repair["pr_number"])
    followup: dict[str, object] | None = None
    compat: dict[str, object] | None = None
    account: dict[str, object] | None = None
    verifier: dict[str, object] | None = None
    acl: dict[str, object] | None = None
    task_identity: dict[str, object] | None = None
    task_identity_followup: dict[str, object] | None = None
    if state.sequence == 22:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        account = _validated_local_install_account_repair(root, compat)
        verifier = _validated_local_install_verifier_repair(root, account)
        acl = _validated_local_install_acl_repair(root, verifier)
        task_identity = _validated_local_install_task_identity_repair(root, acl)
        task_identity_merge = str(task_identity["merge_commit_sha"])
        if _runtime_commit(root) != task_identity_merge:
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_RETRY_RECEIPT_INVALID"
            )
        task_identity_followup = (
            _validated_local_install_task_identity_followup_repair(
                root, task_identity
            )
        )
        runtime_base = task_identity_merge
        runtime_head = str(task_identity_followup["head_commit_sha"])
        runtime_merge = str(task_identity_followup["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_task_identity_followup_patch_sha256
    elif state.sequence == 20:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        account = _validated_local_install_account_repair(root, compat)
        verifier = _validated_local_install_verifier_repair(root, account)
        verifier_merge = str(verifier["merge_commit_sha"])
        if _runtime_commit(root) != verifier_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_RETRY_RECEIPT_INVALID")
        acl = _validated_local_install_acl_repair(root, verifier)
        runtime_base = verifier_merge
        runtime_head = str(acl["head_commit_sha"])
        runtime_merge = str(acl["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_ACL_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_acl_patch_sha256
    elif state.sequence == 18:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        account = _validated_local_install_account_repair(root, compat)
        account_merge = str(account["merge_commit_sha"])
        if _runtime_commit(root) != account_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_RETRY_RECEIPT_INVALID")
        verifier = _validated_local_install_verifier_repair(root, account)
        runtime_base = account_merge
        runtime_head = str(verifier["head_commit_sha"])
        runtime_merge = str(verifier["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_verifier_patch_sha256
    elif state.sequence == 16:
        followup = _validated_local_install_followup_repair(root, repair)
        compat = _validated_local_install_compat_repair(root, followup)
        compat_merge = str(compat["merge_commit_sha"])
        if _runtime_commit(root) != compat_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_RETRY_RECEIPT_INVALID")
        account = _validated_local_install_account_repair(root, compat)
        runtime_base = compat_merge
        runtime_head = str(account["head_commit_sha"])
        runtime_merge = str(account["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_account_patch_sha256
    elif state.sequence == 14:
        followup = _validated_local_install_followup_repair(root, repair)
        followup_merge = str(followup["merge_commit_sha"])
        if _runtime_commit(root) != followup_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_RETRY_RECEIPT_INVALID")
        compat = _validated_local_install_compat_repair(root, followup)
        runtime_base = followup_merge
        runtime_head = str(compat["head_commit_sha"])
        runtime_merge = str(compat["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_COMPAT_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_compat_patch_sha256
    elif state.sequence == 12:
        if _runtime_commit(root) != repair_merge:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_RETRY_RECEIPT_INVALID")
        followup = _validated_local_install_followup_repair(root, repair)
        runtime_base = repair_merge
        runtime_head = str(followup["head_commit_sha"])
        runtime_merge = str(followup["merge_commit_sha"])
        runtime_paths = _LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_followup_patch_sha256
    else:
        runtime_base = binding_merge
        runtime_head = repair_head
        runtime_merge = repair_merge
        runtime_paths = _LOCAL_INSTALL_REPAIR_PATHS
        runtime_patch_sha256 = _local_install_repair_patch_sha256
    if source_commit != runtime_merge:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_CONTEXT_INVALID")

    for installed_root in (AGENT_ROOT, BROKER_ROOT):
        if (
            installed_root.exists()
            or installed_root.is_symlink()
            or installed_root.is_junction()
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PARTIAL_INSTALL")
    staging = BOOTSTRAP_STAGING_ROOT
    if staging.is_symlink() or staging.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PARTIAL_INSTALL")
    if staging.exists() and (not staging.is_dir() or any(staging.iterdir())):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PARTIAL_INSTALL")
    pending_key = root / "secrets/requester-pending.pem"
    if (
        not pending_key.is_file()
        or pending_key.is_symlink()
        or pending_key.is_junction()
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_KEY_INVALID")

    _run(["git", "fetch", "origin", "main"], cwd=source)
    current_commit = _run(["git", "rev-parse", "HEAD"], cwd=source)
    remote = _run(["git", "remote", "get-url", "origin"], cwd=source)
    if (
        current_commit != runtime_merge
        or current_commit != _run(["git", "rev-parse", "origin/main"], cwd=source)
        or not _repository_remote_is_exact(remote)
        or _run(
            ["git", "status", "--porcelain=v1", "--untracked-files=no"],
            cwd=source,
        )
        or _run(["git", "branch", "--show-current"], cwd=source) != "main"
        or _run(["git", "rev-parse", f"{runtime_merge}^1"], cwd=source)
        != runtime_base
        or _run(["git", "rev-parse", f"{runtime_merge}^2"], cwd=source)
        != runtime_head
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_SOURCE_INVALID")

    for revision in (
        f"{runtime_base}..{runtime_head}",
        f"{runtime_base}..{runtime_merge}",
    ):
        changed = tuple(
            line
            for line in _run(
                ["git", "diff", "--name-only", revision, "--"],
                cwd=source,
            ).splitlines()
            if line
        )
        if changed != runtime_paths:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATHS_INVALID")
    if (
        runtime_patch_sha256(
            source,
            runtime_base,
            runtime_head,
        )
        != (
            task_identity_followup
            or task_identity
            or acl
            or verifier
            or account
            or compat
            or followup
            or repair
        )["patch_sha256"]
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATCH_INVALID")

    ancestry = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            state.protected_commit_sha,
            binding_merge,
        ],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if ancestry.returncode != 0:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_SOURCE_INVALID")
    if _run(
        ["gh", "variable", "get", CONTROLLER_VARIABLE, "--repo", REPOSITORY]
    ) != "false":
        raise ValueError("CATALOG_BOOTSTRAP_CONTROLLER_NOT_DISABLED")

    observed_binding = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                str(binding_pr_number),
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefName,mergeCommit",
            ],
            cwd=source,
        )
    )
    observed_binding_merge = (
        observed_binding.get("mergeCommit")
        if isinstance(observed_binding, dict)
        else None
    )
    if (
        not isinstance(observed_binding, dict)
        or set(observed_binding)
        != {"baseRefName", "headRefName", "mergeCommit", "state"}
        or observed_binding.get("state") != "MERGED"
        or observed_binding.get("baseRefName") != "main"
        or observed_binding.get("headRefName") != binding_branch
        or not isinstance(observed_binding_merge, dict)
        or set(observed_binding_merge) != {"oid"}
        or observed_binding_merge.get("oid") != binding_merge
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_PR_INVALID")

    observed_repair = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                str(repair_pr_number),
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefName,headRefOid,mergeCommit",
            ],
            cwd=source,
        )
    )
    observed_repair_merge = (
        observed_repair.get("mergeCommit")
        if isinstance(observed_repair, dict)
        else None
    )
    if (
        not isinstance(observed_repair, dict)
        or set(observed_repair)
        != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
        or observed_repair.get("state") != "MERGED"
        or observed_repair.get("baseRefName") != "main"
        or observed_repair.get("headRefName") != repair_branch
        or observed_repair.get("headRefOid") != repair_head
        or not isinstance(observed_repair_merge, dict)
        or set(observed_repair_merge) != {"oid"}
        or observed_repair_merge.get("oid") != repair_merge
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PR_INVALID")
    observed_paths = tuple(
        line
        for line in _run(
            [
                "gh",
                "pr",
                "diff",
                str(repair_pr_number),
                "--repo",
                REPOSITORY,
                "--name-only",
            ],
            cwd=source,
        ).splitlines()
        if line
    )
    if observed_paths != _LOCAL_INSTALL_REPAIR_PATHS:
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_REPAIR_PATHS_INVALID")
    _wait_for_required_checks(str(repair_pr_number), source)
    if followup is not None:
        followup_pr_number = int(followup["pr_number"])
        observed_followup = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(followup_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_followup_merge = (
            observed_followup.get("mergeCommit")
            if isinstance(observed_followup, dict)
            else None
        )
        if (
            not isinstance(observed_followup, dict)
            or set(observed_followup)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_followup.get("state") != "MERGED"
            or observed_followup.get("baseRefName") != "main"
            or observed_followup.get("headRefName") != followup["branch"]
            or observed_followup.get("headRefOid") != followup["head_commit_sha"]
            or not isinstance(observed_followup_merge, dict)
            or set(observed_followup_merge) != {"oid"}
            or observed_followup_merge.get("oid") != followup["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_REPAIR_PR_INVALID")
        observed_followup_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(followup_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_followup_paths != _LOCAL_INSTALL_FOLLOWUP_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_FOLLOWUP_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(followup_pr_number), source)
    if compat is not None:
        compat_pr_number = int(compat["pr_number"])
        observed_compat = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(compat_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_compat_merge = (
            observed_compat.get("mergeCommit")
            if isinstance(observed_compat, dict)
            else None
        )
        if (
            not isinstance(observed_compat, dict)
            or set(observed_compat)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_compat.get("state") != "MERGED"
            or observed_compat.get("baseRefName") != "main"
            or observed_compat.get("headRefName") != compat["branch"]
            or observed_compat.get("headRefOid") != compat["head_commit_sha"]
            or not isinstance(observed_compat_merge, dict)
            or set(observed_compat_merge) != {"oid"}
            or observed_compat_merge.get("oid") != compat["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_REPAIR_PR_INVALID")
        observed_compat_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(compat_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_compat_paths != _LOCAL_INSTALL_COMPAT_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_COMPAT_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(compat_pr_number), source)
    if account is not None:
        account_pr_number = int(account["pr_number"])
        observed_account = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(account_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_account_merge = (
            observed_account.get("mergeCommit")
            if isinstance(observed_account, dict)
            else None
        )
        if (
            not isinstance(observed_account, dict)
            or set(observed_account)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_account.get("state") != "MERGED"
            or observed_account.get("baseRefName") != "main"
            or observed_account.get("headRefName") != account["branch"]
            or observed_account.get("headRefOid") != account["head_commit_sha"]
            or not isinstance(observed_account_merge, dict)
            or set(observed_account_merge) != {"oid"}
            or observed_account_merge.get("oid") != account["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_REPAIR_PR_INVALID")
        observed_account_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(account_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_account_paths != _LOCAL_INSTALL_ACCOUNT_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACCOUNT_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(account_pr_number), source)
    if verifier is not None:
        verifier_pr_number = int(verifier["pr_number"])
        observed_verifier = json.loads(
            _run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(verifier_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_verifier_merge = (
            observed_verifier.get("mergeCommit")
            if isinstance(observed_verifier, dict)
            else None
        )
        if (
            not isinstance(observed_verifier, dict)
            or set(observed_verifier)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_verifier.get("state") != "MERGED"
            or observed_verifier.get("baseRefName") != "main"
            or observed_verifier.get("headRefName") != verifier["branch"]
            or observed_verifier.get("headRefOid") != verifier["head_commit_sha"]
            or not isinstance(observed_verifier_merge, dict)
            or set(observed_verifier_merge) != {"oid"}
            or observed_verifier_merge.get("oid") != verifier["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_REPAIR_PR_INVALID")
        observed_verifier_paths = tuple(
            line
            for line in _run(
                [
                    "gh",
                    "pr",
                    "diff",
                    str(verifier_pr_number),
                    "--repo",
                    REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_verifier_paths != _LOCAL_INSTALL_VERIFIER_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_VERIFIER_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(verifier_pr_number), source)
    if acl is not None:
        acl_pr_number = int(acl["pr_number"])
        observed_acl = json.loads(
            _run(
                [
                    "gh", "pr", "view", str(acl_pr_number), "--repo", REPOSITORY,
                    "--json", "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_acl_merge = (
            observed_acl.get("mergeCommit") if isinstance(observed_acl, dict) else None
        )
        if (
            not isinstance(observed_acl, dict)
            or set(observed_acl)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_acl.get("state") != "MERGED"
            or observed_acl.get("baseRefName") != "main"
            or observed_acl.get("headRefName") != acl["branch"]
            or observed_acl.get("headRefOid") != acl["head_commit_sha"]
            or not isinstance(observed_acl_merge, dict)
            or set(observed_acl_merge) != {"oid"}
            or observed_acl_merge.get("oid") != acl["merge_commit_sha"]
        ):
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_REPAIR_PR_INVALID")
        observed_acl_paths = tuple(
            line
            for line in _run(
                [
                    "gh", "pr", "diff", str(acl_pr_number), "--repo", REPOSITORY,
                    "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if observed_acl_paths != _LOCAL_INSTALL_ACL_REPAIR_PATHS:
            raise ValueError("CATALOG_BOOTSTRAP_LOCAL_ACL_REPAIR_PATHS_INVALID")
        _wait_for_required_checks(str(acl_pr_number), source)
    if task_identity is not None:
        task_identity_pr_number = int(task_identity["pr_number"])
        observed_task_identity = json.loads(
            _run(
                [
                    "gh", "pr", "view", str(task_identity_pr_number),
                    "--repo", REPOSITORY, "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_task_identity_merge = (
            observed_task_identity.get("mergeCommit")
            if isinstance(observed_task_identity, dict)
            else None
        )
        if (
            not isinstance(observed_task_identity, dict)
            or set(observed_task_identity)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_task_identity.get("state") != "MERGED"
            or observed_task_identity.get("baseRefName") != "main"
            or observed_task_identity.get("headRefName") != task_identity["branch"]
            or observed_task_identity.get("headRefOid")
            != task_identity["head_commit_sha"]
            or not isinstance(observed_task_identity_merge, dict)
            or set(observed_task_identity_merge) != {"oid"}
            or observed_task_identity_merge.get("oid")
            != task_identity["merge_commit_sha"]
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_PR_INVALID"
            )
        observed_task_identity_paths = tuple(
            line
            for line in _run(
                [
                    "gh", "pr", "diff", str(task_identity_pr_number),
                    "--repo", REPOSITORY, "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if (
            observed_task_identity_paths
            != _LOCAL_INSTALL_TASK_IDENTITY_REPAIR_PATHS
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_REPAIR_PATHS_INVALID"
            )
        _wait_for_required_checks(str(task_identity_pr_number), source)
    if task_identity_followup is not None:
        task_identity_followup_pr_number = int(task_identity_followup["pr_number"])
        observed_task_identity_followup = json.loads(
            _run(
                [
                    "gh", "pr", "view", str(task_identity_followup_pr_number),
                    "--repo", REPOSITORY, "--json",
                    "state,baseRefName,headRefName,headRefOid,mergeCommit",
                ],
                cwd=source,
            )
        )
        observed_task_identity_followup_merge = (
            observed_task_identity_followup.get("mergeCommit")
            if isinstance(observed_task_identity_followup, dict)
            else None
        )
        if (
            not isinstance(observed_task_identity_followup, dict)
            or set(observed_task_identity_followup)
            != {"baseRefName", "headRefName", "headRefOid", "mergeCommit", "state"}
            or observed_task_identity_followup.get("state") != "MERGED"
            or observed_task_identity_followup.get("baseRefName") != "main"
            or observed_task_identity_followup.get("headRefName")
            != task_identity_followup["branch"]
            or observed_task_identity_followup.get("headRefOid")
            != task_identity_followup["head_commit_sha"]
            or not isinstance(observed_task_identity_followup_merge, dict)
            or set(observed_task_identity_followup_merge) != {"oid"}
            or observed_task_identity_followup_merge.get("oid")
            != task_identity_followup["merge_commit_sha"]
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_REPAIR_PR_INVALID"
            )
        observed_task_identity_followup_paths = tuple(
            line
            for line in _run(
                [
                    "gh", "pr", "diff", str(task_identity_followup_pr_number),
                    "--repo", REPOSITORY, "--name-only",
                ],
                cwd=source,
            ).splitlines()
            if line
        )
        if (
            observed_task_identity_followup_paths
            != _LOCAL_INSTALL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS
        ):
            raise ValueError(
                "CATALOG_BOOTSTRAP_LOCAL_TASK_IDENTITY_FOLLOWUP_REPAIR_PATHS_INVALID"
            )
        _wait_for_required_checks(str(task_identity_followup_pr_number), source)

    installations = _verify_existing_installations(root)
    baseline_path = root / "github-activity-baseline-v1.json"
    baseline = _read_json(baseline_path)
    if (
        baseline_path.read_bytes() != _canonical(baseline) + b"\n"
        or set(baseline) != {"heavy_run_ids", "request_issue_numbers"}
        or not isinstance(baseline["heavy_run_ids"], list)
        or not isinstance(baseline["request_issue_numbers"], list)
        or _github_activity_snapshot() != baseline
    ):
        raise ValueError("CATALOG_BOOTSTRAP_LOCAL_RETRY_ACTIVITY_INVALID")

    common_recovery = {
        "activity_baseline_sha256": hashlib.sha256(_canonical(baseline)).hexdigest(),
        "blocked_state_sha256": hashlib.sha256(
            (root / "state/catalog-bootstrap-state-v1.json").read_bytes()
        ).hexdigest(),
        "bootstrap_source_commit_sha": state.protected_commit_sha,
        "installations": installations,
        "schema_version": "1",
    }
    if task_identity_followup is not None:
        prior_retry_path = acl_retry_path
        recovery = {
            **common_recovery,
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": task_identity["merge_commit_sha"],
            "task_identity_followup_merge_commit_sha": task_identity_followup[
                "merge_commit_sha"
            ],
            "task_identity_followup_operation_sha256": hashlib.sha256(
                _canonical(task_identity_followup)
            ).hexdigest(),
            "task_identity_followup_pr_number": task_identity_followup["pr_number"],
        }
        recovery_path = task_identity_retry_path
    elif acl is not None:
        prior_retry_path = verifier_retry_path
        recovery = {
            **common_recovery,
            "acl_merge_commit_sha": acl["merge_commit_sha"],
            "acl_operation_sha256": hashlib.sha256(_canonical(acl)).hexdigest(),
            "acl_pr_number": acl["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": verifier["merge_commit_sha"],
        }
        recovery_path = acl_retry_path
    elif verifier is not None:
        prior_retry_path = account_retry_path
        recovery = {
            **common_recovery,
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": account["merge_commit_sha"],
            "verifier_merge_commit_sha": verifier["merge_commit_sha"],
            "verifier_operation_sha256": hashlib.sha256(
                _canonical(verifier)
            ).hexdigest(),
            "verifier_pr_number": verifier["pr_number"],
        }
        recovery_path = verifier_retry_path
    elif account is not None:
        prior_retry_path = compat_retry_path
        recovery = {
            **common_recovery,
            "account_merge_commit_sha": account["merge_commit_sha"],
            "account_operation_sha256": hashlib.sha256(
                _canonical(account)
            ).hexdigest(),
            "account_pr_number": account["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": compat["merge_commit_sha"],
        }
        recovery_path = account_retry_path
    elif compat is not None:
        prior_retry_path = followup_retry_path
        recovery = {
            **common_recovery,
            "compat_merge_commit_sha": compat["merge_commit_sha"],
            "compat_operation_sha256": hashlib.sha256(
                _canonical(compat)
            ).hexdigest(),
            "compat_pr_number": compat["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": followup["merge_commit_sha"],
        }
        recovery_path = compat_retry_path
    elif followup is None:
        recovery = {
            **common_recovery,
            "public_binding_merge_commit_sha": binding_merge,
            "repair_merge_commit_sha": repair_merge,
            "repair_operation_sha256": hashlib.sha256(_canonical(repair)).hexdigest(),
            "repair_pr_number": repair_pr_number,
        }
        recovery_path = (
            root / "receipts/controller-bootstrap-local-install-retry-v1.json"
        )
    else:
        prior_retry_path = (
            root / "receipts/controller-bootstrap-local-install-retry-v1.json"
        )
        recovery = {
            **common_recovery,
            "followup_merge_commit_sha": followup["merge_commit_sha"],
            "followup_operation_sha256": hashlib.sha256(
                _canonical(followup)
            ).hexdigest(),
            "followup_pr_number": followup["pr_number"],
            "prior_retry_receipt_sha256": hashlib.sha256(
                prior_retry_path.read_bytes()
            ).hexdigest(),
            "prior_runtime_commit_sha": repair_merge,
        }
        recovery_path = followup_retry_path
    _write_canonical(recovery_path, recovery)
    _advance(root, state, "local_install_retry_authorized", recovery)
    return True


def _resume_transient_github_controls_block(root: Path) -> bool:
    state = load_bootstrap_state(_state_path(root))
    if state.phase != "BLOCKED" or state.sequence != 25:
        return False
    blocked_path = root / "receipts/controller-bootstrap-blocked-v1.json"
    blocked = _read_json(blocked_path)
    expected_block = {
        "controller_enabled_readback": False,
        "phase": "GITHUB_CONTROLS_PENDING",
        "reason_code": "CATALOG_BOOTSTRAP_FIXED_COMMAND_FAILED",
        "result": "BLOCKED",
        "schema_version": "1",
    }
    if blocked != expected_block:
        return False
    if blocked_path.read_bytes() != _canonical(blocked) + b"\n":
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BLOCK_INVALID")
    if root.resolve() != EXPECTED_ROOT.resolve():
        raise ValueError("CATALOG_BOOTSTRAP_ROOT_INVALID")
    first_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-v1.json"
    )
    if not first_retry_path.exists():
        return False
    if first_retry_path.is_symlink() or first_retry_path.is_junction():
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    runtime_commit = _runtime_commit(root)
    followup_retry_path = (
        root / "receipts/controller-bootstrap-github-controls-retry-2-v1.json"
    )
    if followup_retry_path.exists():
        if followup_retry_path.is_symlink() or followup_retry_path.is_junction():
            raise ValueError(
                "CATALOG_BOOTSTRAP_GITHUB_CONTROLS_FOLLOWUP_RETRY_INVALID"
        )
        retry_path = followup_retry_path
        evidence = _read_json(retry_path)
        operation_path = root / "github-controls-followup-repair-operation-v1.json"
        merge_field = "followup_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_FOLLOWUP_REPAIR_PATHS
    else:
        retry_path = first_retry_path
        evidence = _read_json(retry_path)
        operation_path = root / "github-controls-repair-operation-v1.json"
        merge_field = "github_controls_merge_commit_sha"
        expected_paths = _GITHUB_CONTROLS_REPAIR_PATHS
    if runtime_commit != evidence.get(merge_field):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_RETRY_RECEIPT_INVALID")
    if evidence.get("blocked_state_sha256") != hashlib.sha256(
        _state_path(root).read_bytes()
    ).hexdigest():
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_BLOCK_STATE_INVALID")
    operation = _read_json(operation_path)
    context = _context(root)
    source = Path(str(context["source_root"])).resolve(strict=True)
    if context.get("source_commit_sha") != runtime_commit:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_CONTEXT_INVALID")
    if (
        _run(["git", "rev-parse", "HEAD"], cwd=source) != runtime_commit
        or _run(["git", "rev-parse", "origin/main"], cwd=source)
        != runtime_commit
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_SOURCE_INVALID")
    observed = json.loads(
        _run(
            [
                "gh", "pr", "view", str(operation["pr_number"]), "--repo",
                REPOSITORY, "--json",
                "state,baseRefName,headRefName,headRefOid,mergeCommit",
            ],
            cwd=source,
        )
    )
    observed_merge = observed.get("mergeCommit") if isinstance(observed, dict) else None
    if (
        not isinstance(observed, dict)
        or observed.get("state") != "MERGED"
        or observed.get("baseRefName") != "main"
        or observed.get("headRefName") != operation["branch"]
        or observed.get("headRefOid") != operation["head_commit_sha"]
        or not isinstance(observed_merge, dict)
        or observed_merge.get("oid") != runtime_commit
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PR_INVALID")
    _verify_github_controls_repair_graph(source, operation)
    observed_paths = tuple(
        line
        for line in _run(
            [
                "gh", "pr", "diff", str(operation["pr_number"]), "--repo",
                REPOSITORY, "--name-only",
            ],
            cwd=source,
        ).splitlines()
        if line
    )
    if observed_paths != expected_paths:
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_REPAIR_PATHS_INVALID")
    _wait_for_required_checks(str(operation["pr_number"]), source)
    if _verify_post_install_installations(root) != evidence.get("installations"):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_INSTALLATIONS_INVALID")
    baseline_path = root / "github-activity-baseline-v1.json"
    baseline = _read_json(baseline_path)
    if (
        hashlib.sha256(_canonical(baseline)).hexdigest()
        != evidence.get("activity_baseline_sha256")
        or _github_activity_snapshot() != baseline
    ):
        raise ValueError("CATALOG_BOOTSTRAP_GITHUB_CONTROLS_ACTIVITY_INVALID")
    _advance(root, state, "github_controls_retry_authorized", evidence)
    return True


def merge_public_binding(root: Path) -> None:
    state = load_bootstrap_state(_state_path(root))
    context = _context(root)
    source = Path(str(context["source_root"]))
    receipt = _read_json(root / "public-binding-operation-v1.json")
    pr_number = str(receipt["pr_number"])
    binding_commit = receipt.get("binding_commit_sha")
    if not isinstance(binding_commit, str) or not _COMMIT.fullmatch(binding_commit):
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    if state.sequence == 6:
        expected_head = binding_commit
    elif state.sequence == 8:
        retry_path = root / "receipts/controller-bootstrap-merge-retry-v1.json"
        retry = _read_json(retry_path)
        expected_retry_keys = {
            "binding_commit_sha",
            "blocked_state_sha256",
            "head_commit_sha",
            "installations",
            "pr_number",
            "required_checks",
            "review_rounds_sha256",
            "source_commit_sha",
        }
        expected_head = retry.get("head_commit_sha")
        if (
            set(retry) != expected_retry_keys
            or retry_path.read_bytes() != _canonical(retry) + b"\n"
            or retry.get("binding_commit_sha") != binding_commit
            or retry.get("pr_number") != receipt.get("pr_number")
            or retry.get("review_rounds_sha256")
            != receipt.get("review_rounds_sha256")
            or not isinstance(expected_head, str)
            or not _COMMIT.fullmatch(expected_head)
        ):
            raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    else:
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    _wait_for_required_checks(pr_number, source)
    pull_request = json.loads(
        _run(
            [
                "gh",
                "pr",
                "view",
                pr_number,
                "--repo",
                REPOSITORY,
                "--json",
                "state,baseRefName,headRefOid",
            ],
            cwd=source,
        )
    )
    if (
        not isinstance(pull_request, dict)
        or pull_request.get("state") != "OPEN"
        or pull_request.get("baseRefName") != "main"
        or pull_request.get("headRefOid") != expected_head
    ):
        raise ValueError("BOOTSTRAP_PR_HEAD_MISMATCH")
    _run(
        [
            "gh",
            "pr",
            "merge",
            pr_number,
            "--repo",
            REPOSITORY,
            "--merge",
            "--match-head-commit",
            expected_head,
        ],
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
    merge_sha = _runtime_commit(root)
    _run(["git", "switch", "--detach", merge_sha], cwd=source)
    staging = BOOTSTRAP_STAGING_ROOT
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
    protected_commit_sha = _runtime_commit(root)
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
    protected_commit_sha = _runtime_commit(root)
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
    protected_commit_sha = _runtime_commit(root)
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
        if state.phase == "READY":
            return 0
        if state.phase == "BLOCKED":
            try:
                recovered = _resume_transient_merge_block(args.installed_root)
                if not recovered:
                    recovered = _resume_transient_local_install_block(
                        args.installed_root
                    )
                if not recovered:
                    recovered = _resume_transient_github_controls_block(
                        args.installed_root
                    )
                if not recovered:
                    return 2
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
                    reason = "CATALOG_BOOTSTRAP_RECOVERY_FAILED"
                recovery_phase = "BLOCKED"
                blocked_path = (
                    args.installed_root
                    / "receipts/controller-bootstrap-blocked-v1.json"
                )
                try:
                    blocked_receipt = _read_json(blocked_path)
                    if blocked_path.read_bytes() != _canonical(blocked_receipt) + b"\n":
                        raise ValueError("CATALOG_BOOTSTRAP_RECOVERY_RECEIPT_INVALID")
                    observed_phase = blocked_receipt.get("phase")
                    if observed_phase in {"MERGE_PENDING", "LOCAL_INSTALL_PENDING"}:
                        recovery_phase = observed_phase
                except (OSError, TypeError, ValueError):
                    pass
                _write_canonical(
                    args.installed_root
                    / "receipts/controller-bootstrap-recovery-blocked-v1.json",
                    {
                        "controller_enabled_readback": False,
                        "phase": recovery_phase,
                        "reason_code": reason,
                        "result": "BLOCKED",
                        "schema_version": "1",
                    },
                )
                return 2
            continue
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

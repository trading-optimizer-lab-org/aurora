# AURORA Assisted Catalog Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-run Windows assistant that creates and installs the two exact GitHub Apps through owner-confirmed screens, keeps every private key outside Codex, completes the protected bootstrap, and reopens Codex under `AURORAAgent`.

**Architecture:** A pure Python contract/state core drives an idempotent elevated coordinator. A loopback-only GitHub App Manifest flow hands private material directly to an administrator-only store after every HP Codex process has stopped. Existing controller, requester, controls, and qualification components are reused; production enablement is the final verified transition.

**Tech Stack:** Python 3.14, Pydantic 2.13.4, requests 2.34.2, cryptography 50.0.0, PowerShell, Windows DPAPI/AppX/ACL APIs, GitHub REST and GraphQL, pytest 9.

**Spec:** `docs/superpowers/specs/2026-08-23-aurora-assisted-catalog-bootstrap-design.md`

## Global Constraints

- Exact repository: `trading-optimizer-lab-org/aurora`.
- Exact organization: `trading-optimizer-lab-org`.
- Keep `CATALOG_CONTROLLER_ENABLED=false` until the final live audit.
- Create no production request and launch no production catalog run.
- One agent; no subagents, forks, or additional worktrees.
- Preserve the dirty primary checkout and the two existing untracked user documents.
- Requester permissions: Metadata read and Issues read/write only.
- Auditor permissions: exact sealed read-only map in `config/catalog_github_auditor_v1.json`.
- Billing controls use the organization endpoint with repository scope; no
  enterprise permission or enterprise-level App installation is allowed.
- No key, token, JWT, client secret, webhook secret, password, cookie, or session value in argv, inherited environment, stdout, logs, receipts, git, Downloads, temp, or Codex.
- Stop all HP Codex processes before requesting the first manifest code.
- Callback only on `127.0.0.1` with one-use random state and one-hour expiry.
- Missing, ambiguous, stale, duplicated, broadened, or unverified evidence is `BLOCKED`.
- Use TDD and exact-path staging for every change.
- Do not modify `C:\Users\HP\Desktop\plantilla-prompt-nuevo-run-catalogo.md`.

---

### Task 1: Closed App manifest contracts

**Files:**

- Create: `config/catalog_bootstrap_app_manifests_v1.json`
- Create: `schemas/catalog_bootstrap_app_manifests_v1.schema.json`
- Create: `infra/sp500_megarun/catalog_bootstrap_contract.py`
- Create: `tests/test_catalog_bootstrap_app_manifests.py`

**Interfaces:**

- Produces: `CatalogBootstrapManifestSetV1`, `CatalogBootstrapAppManifestV1`, `CatalogBootstrapPublicAppBindingV1`, `load_catalog_bootstrap_manifests`, and `github_manifest_payload`.

- [ ] **Step 1: Write failing exact-permission and closed-schema tests**

~~~python
def test_bootstrap_manifests_are_exact() -> None:
    value = load_catalog_bootstrap_manifests(MANIFEST_PATH)
    assert value.repository == "trading-optimizer-lab-org/aurora"
    assert value.requester.manifest_permissions == {
        "metadata": "read", "issues": "write"
    }
    assert value.auditor.manifest_permissions == EXPECTED_AUDITOR_MANIFEST_PERMISSIONS
    assert value.auditor.expected_repository_permissions == EXPECTED_AUDITOR_PERMISSIONS
    assert value.requester.webhook_active is False
    assert value.auditor.webhook_active is False
    assert value.requester.default_events == ()
    assert value.auditor.default_events == ()


def test_manifest_rejects_unknown_or_write_auditor_permission() -> None:
    assert_schema_rejected(document_with_extra_field())
    assert_schema_rejected(document_with_auditor_contents_write())
~~~

- [ ] **Step 2: Run tests and require missing-module failure**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_app_manifests.py -q
~~~

- [ ] **Step 3: Implement frozen models and exact payload**

~~~python
class CatalogBootstrapAppManifestV1(FrozenModel):
    kind: Literal["requester", "auditor"]
    name: str
    description: str
    homepage_url: HttpUrl
    public: Literal[False]
    webhook_active: Literal[False]
    default_events: tuple[()]
    manifest_permissions: dict[str, Literal["read", "write"]]
    expected_repository_permissions: dict[str, Literal["read", "write"]]
    expected_organization_permissions: dict[str, Literal["read", "write"]]


def github_manifest_payload(app, *, redirect_url: str) -> dict[str, object]:
    return {
        "name": app.name,
        "url": str(app.homepage_url),
        "description": app.description,
        "redirect_url": redirect_url,
        "public": False,
        "hook_attributes": {"url": redirect_url, "active": False},
        "default_events": [],
        "default_permissions": dict(sorted(app.manifest_permissions.items())),
        "request_oauth_on_install": False,
        "setup_on_update": False,
    }
~~~

Validate both exact maps in Python and recursively close the schema. Task 6
includes these files in the assistant's closed application manifest; Task 9
binds their hashes into the final bootstrap receipt. They are governance inputs,
not scientific campaign inputs, so the campaign-definition closure stays
unchanged.

Use the deterministic names `AURORA Catalog Requester f10c7b40e1` and
`AURORA Catalog Controls Auditor cf479d98fb`. The auditor manifest uses the
provider parameter names `actions_variables` and
`organization_administration`; the post-installation verifier normalizes the
provider response to the already sealed repository key `variables` and
organization key `administration` before comparing exact maps. Tests cover both
provider forms and reject every unknown key. The auditor requests no enterprise
permission: repository-scoped zero budgets are read from the organization
billing endpoint, so one exact-repository organization installation is enough.

- [ ] **Step 4: Run tests, regenerate/check manifest, and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_app_manifests.py -q
git add -- config/catalog_bootstrap_app_manifests_v1.json schemas/catalog_bootstrap_app_manifests_v1.schema.json infra/sp500_megarun/catalog_bootstrap_contract.py tests/test_catalog_bootstrap_app_manifests.py
git diff --cached --check
git commit -m "feat: define catalog bootstrap app manifests"
~~~

### Task 2: Resumable state and receipts

**Files:**

- Create: `infra/sp500_megarun/catalog_bootstrap_state.py`
- Create: `tests/test_catalog_bootstrap_assistant.py`

**Interfaces:**

- Produces: `CatalogBootstrapStateV1`, `CatalogBootstrapEventV1`, `advance_bootstrap_state`, `load_bootstrap_state`, and `persist_bootstrap_state`.

- [ ] **Step 1: Write failing graph, replay, rollback, and secret-field tests**

~~~python
def test_only_closed_forward_transitions_are_allowed() -> None:
    state = initial_state("a" * 40)
    state = advance_bootstrap_state(state, event("precheck_passed"))
    assert state.phase == "REQUESTER_CREATE_PENDING"
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        advance_bootstrap_state(state, event("auditor_installed"))


def test_same_observation_is_idempotent() -> None:
    first = advance_bootstrap_state(REQUESTER_PENDING, REQUESTER_CREATED)
    second = advance_bootstrap_state(first, REQUESTER_CREATED)
    assert canonical_bytes(first) == canonical_bytes(second)
~~~

- [ ] **Step 2: Run failing test, then implement explicit state table**

Phases are exactly:

~~~text
PRECHECK
REQUESTER_CREATE_PENDING
REQUESTER_INSTALL_PENDING
AUDITOR_CREATE_PENDING
AUDITOR_INSTALL_PENDING
PUBLIC_BINDING_PENDING
MERGE_PENDING
LOCAL_INSTALL_PENDING
GITHUB_CONTROLS_PENDING
QUALIFICATION_PENDING
AGENT_RESTART_PENDING
FINAL_AUDIT_PENDING
READY
BLOCKED
~~~

Each event has a canonical public idempotency hash. Persistence uses create-new temporary files, flush, atomic replace, read-back SHA-256, one writer lock, and rejects links, noncanonical JSON, state rollback, changed bootstrap ID, or changed protected commit. The state schema contains no key, token, password, PEM, JWT, or secret field.

- [ ] **Step 3: Run focused tests and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_assistant.py -q
git add -- infra/sp500_megarun/catalog_bootstrap_state.py tests/test_catalog_bootstrap_assistant.py
git diff --cached --check
git commit -m "feat: add resumable catalog bootstrap state"
~~~

### Task 3: Loopback-only GitHub manifest flow

**Files:**

- Create: `infra/sp500_megarun/catalog_bootstrap_manifest.py`
- Create: `tests/test_catalog_bootstrap_manifest_flow.py`
- Create: `requirements/catalog-bootstrap.in`
- Create: `requirements/catalog-bootstrap-win-py314.lock`

**Interfaces:**

- Produces: `ManifestSession`, `GitHubManifestConversion`, `start_manifest_session`, `accept_manifest_callback`, and `exchange_manifest_code`.

- [ ] **Step 1: Write failing loopback, state, replay, expiry, and redaction tests**

~~~python
def test_callback_is_loopback_state_bound_and_one_use() -> None:
    session = start_manifest_session("requester", now=NOW)
    assert session.bind_host == "127.0.0.1"
    with pytest.raises(ValueError, match="STATE_MISMATCH"):
        accept_manifest_callback(session, {"code": "c" * 24, "state": "bad"}, NOW)
    accepted = accept_manifest_callback(
        session, {"code": "c" * 24, "state": session.state}, NOW
    )
    with pytest.raises(ValueError, match="CALLBACK_REPLAY"):
        accept_manifest_callback(accepted.session, accepted.query, NOW)


def test_conversion_repr_never_contains_key() -> None:
    value = conversion_with_key(b"PRIVATE-MARKER")
    assert "PRIVATE-MARKER" not in repr(value)
~~~

- [ ] **Step 2: Implement one-request local server and conversion**

~~~python
@dataclass(slots=True)
class GitHubManifestConversion:
    app_id: int
    slug: str
    private_key_pem: bytearray = field(repr=False)

    def __repr__(self) -> str:
        return "GitHubManifestConversion(<redacted>)"

    def clear(self) -> None:
        for index in range(len(self.private_key_pem)):
            self.private_key_pem[index] = 0
~~~

The server accepts only the exact callback path and loopback Host, caps request/header sizes, emits `Cache-Control: no-store`, never logs, and stops after success or expiry. Exchange only `POST /app-manifests/{code}/conversions` with fixed headers and timeout.

- [ ] **Step 3: Add exact dependencies and generated lock**

`requirements/catalog-bootstrap.in` contains exactly:

~~~text
cryptography==50.0.0
pydantic==2.13.4
requests==2.34.2
~~~

Generate the Windows Python 3.14 lock with `uv pip compile --generate-hashes`. Test hashes, compatible wheels, and absence of pytest, browser, GUI, VCS, editable, local, or URL dependencies.

- [ ] **Step 4: Run tests and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_manifest_flow.py tests/test_catalog_bootstrap_app_manifests.py -q
git add -- infra/sp500_megarun/catalog_bootstrap_manifest.py tests/test_catalog_bootstrap_manifest_flow.py requirements/catalog-bootstrap.in requirements/catalog-bootstrap-win-py314.lock
git diff --cached --check
git commit -m "feat: add protected GitHub App manifest flow"
~~~

### Task 4: Exact installation verification and key custody

**Files:**

- Create: `infra/sp500_megarun/catalog_bootstrap_github.py`
- Create: `infra/sp500_megarun/catalog_bootstrap_secrets.py`
- Create: `tests/test_catalog_bootstrap_secret_isolation.py`

**Interfaces:**

- Produces: `verify_exact_installation`, `derive_public_binding`, `store_requester_key_once`, `upload_auditor_key_once`, and `clear_private_material`.

- [ ] **Step 1: Write failing scope and ACL tests**

~~~python
def test_installation_rejects_extra_repository_or_permission() -> None:
    with pytest.raises(ValueError, match="INSTALL_SCOPE_INVALID"):
        verify_exact_installation(snapshot_with_two_repositories(), EXPECTED)
    with pytest.raises(ValueError, match="APP_PERMISSION_DRIFT"):
        verify_exact_installation(snapshot_with_extra_permission(), EXPECTED)


def test_requester_key_requires_preclosed_parent(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SECRET_ACL_OPEN"):
        store_requester_key_once(tmp_path, bytearray(KEY_PEM))
~~~

- [ ] **Step 2: Implement fixed create-new custody**

Requester key path is exactly `C:\ProgramData\AURORA\CatalogRequester\secrets\requester-private-key.pem`. Auditor staging is exactly `C:\ProgramData\AURORA\CatalogBootstrap\secrets\auditor-private-key.pem`. Parent ACLs are closed before content exists. Files use create-new, flush, separate-handle fingerprint verification, and reject every reparse point.

Derive only SubjectPublicKeyInfo DER and SHA-256. Upload auditor PEM to the fixed environment secret through stdin, read metadata back, zero memory, delete staging, and prove no copy remains.

- [ ] **Step 3: Run tests and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_secret_isolation.py tests/test_catalog_requester_packaging.py -q
git add -- infra/sp500_megarun/catalog_bootstrap_github.py infra/sp500_megarun/catalog_bootstrap_secrets.py tests/test_catalog_bootstrap_secret_isolation.py
git diff --cached --check
git commit -m "feat: isolate catalog bootstrap credentials"
~~~

### Task 5: Public binding, authority, PR, and merge

**Files:**

- Create: `infra/sp500_megarun/catalog_bootstrap_binding.py`
- Create: `tests/test_catalog_bootstrap_binding.py`
- Modify: existing requester, authority, controls, and qualification tests.

**Interfaces:**

- Produces: `build_public_binding_patch`, `create_or_verify_authority_anchor`, `open_or_reuse_bootstrap_pr`, and `merge_verified_bootstrap_pr`.

- [ ] **Step 1: Write failing allowlisted-diff and duplicate-anchor tests**

~~~python
def test_binding_changes_only_public_allowlisted_paths() -> None:
    result = build_public_binding_patch(REQUESTER, AUDITOR, AUTHORITY, TREE)
    assert result.changed_paths == EXPECTED_PUBLIC_BINDING_PATHS
    assert_no_private_values(result.documents)


def test_authority_anchor_is_unique_and_reused() -> None:
    assert create_or_verify_authority_anchor([EXACT_AUTHORITY]) == EXACT_AUTHORITY
    with pytest.raises(ValueError, match="MULTIPLE_ANCHORS"):
        create_or_verify_authority_anchor([EXACT_AUTHORITY, SECOND_AUTHORITY])
~~~

- [ ] **Step 2: Implement only these real binding paths**

~~~text
config/catalog_controller_actors_v1.json
config/catalog_authority_anchor_v1.json
config/catalog_requester_v1.json
config/catalog_requester_public_key_v1.pem
config/catalog_github_auditor_v1.json
~~~

Use fixed git/gh argument arrays. Require exact remote, branch, head, clean tracked tree, no index lock, no other writer, exact diff paths, one PR, green checks, satisfied protection, and a merge SHA containing the exact binding commit.

- [ ] **Step 3: Run binding acceptance and commit implementation only**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_binding.py tests/test_catalog_authority_ledger.py tests/test_catalog_github_controls.py tests/test_catalog_run_request.py tests/test_submit_catalog_run_request.py tests/test_catalog_requester_broker.py tests/test_catalog_controller_qualification.py -q
git add -- infra/sp500_megarun/catalog_bootstrap_binding.py tests/test_catalog_bootstrap_binding.py tests/test_catalog_authority_ledger.py tests/test_catalog_github_controls.py tests/test_catalog_run_request.py tests/test_submit_catalog_run_request.py tests/test_catalog_requester_broker.py tests/test_catalog_controller_qualification.py
git diff --cached --check
git commit -m "feat: automate protected catalog identity binding"
~~~

Real public binding values are applied only later by the elevated assistant.

### Task 6: Deterministic coordinator package

**Files:**

- Create: `scripts/run_catalog_bootstrap_assistant.py`
- Create: `scripts/build_catalog_bootstrap_assistant.py`
- Create: `schemas/catalog_bootstrap_application_manifest_v1.schema.json`
- Create: `tests/test_catalog_bootstrap_packaging.py`

**Interfaces:**

- Produces: `catalog-bootstrap-assistant.pyz`, closed manifest, `run_phase`, and CLI accepting only `--installed-root`.

- [ ] **Step 1: Write failing CLI, member-list, and deterministic-build tests**

~~~python
def test_cli_has_only_installed_root() -> None:
    assert parser_options(SCRIPT) == {"-h", "--help", "--installed-root"}


def test_two_builds_are_identical(tmp_path: Path) -> None:
    first = build(tmp_path / "one")
    second = build(tmp_path / "two")
    assert first.pyz.read_bytes() == second.pyz.read_bytes()
    assert first.manifest.read_bytes() == second.manifest.read_bytes()
~~~

- [ ] **Step 2: Implement closed dispatcher**

~~~python
PHASE_HANDLERS = {
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
~~~

No generic shell runner, browser automation, arbitrary URL/path/repository input, or production request function enters the package. Fix archive order, timestamps, permissions, compression, and newlines.

- [ ] **Step 3: Run package regressions and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_packaging.py tests/test_catalog_requester_packaging.py -q
git add -- scripts/run_catalog_bootstrap_assistant.py scripts/build_catalog_bootstrap_assistant.py schemas/catalog_bootstrap_application_manifest_v1.schema.json tests/test_catalog_bootstrap_packaging.py
git diff --cached --check
git commit -m "feat: package catalog bootstrap assistant"
~~~

### Task 7: Windows installer and HP Codex shutdown gate

**Files:**

- Create: `scripts/install_catalog_bootstrap_assistant.ps1`
- Create: `scripts/start_catalog_bootstrap_assistant.ps1`
- Create: `tests/test_catalog_bootstrap_windows.py`
- Modify: `tests/test_catalog_requester_packaging.py`

**Interfaces:**

- Produces: `C:\ProgramData\AURORA\CatalogBootstrap`, dry-run receipt, and shortcut `Instalar controlador AURORA.lnk`.

- [ ] **Step 1: Write failing dry-run, parameter, ACL, and ordering tests**

~~~python
def test_installer_is_nonmutating_by_default() -> None:
    receipt = run_powershell(INSTALLER)
    assert receipt["mode"] == "dry_run"
    assert receipt["mutation_performed"] is False
    assert receipt["production_enabled"] is False


def test_no_secret_or_arbitrary_parameters() -> None:
    assert powershell_parameters(INSTALLER) == {"Apply", "Confirm"}
    assert powershell_parameters(STARTER) == set()
~~~

- [ ] **Step 2: Implement exact installer/starter**

Confirmation is exactly `AURORA_CATALOG_BOOTSTRAP_ASSISTANT_V1`. Verify admin token, exact repo/head/remote, clean tracked tree, disabled controller, no other writer; create closed roots, build twice, install locked venv, and create fixed shortcut.

Starter has no parameters. It verifies all installed hashes, starts only the fixed elevated coordinator through UAC, checkpoints state, and closes the exact HP ChatGPT/Codex tree before the first manifest form.

- [ ] **Step 3: Run tests and commit**

~~~powershell
& scripts/install_catalog_bootstrap_assistant.ps1
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_windows.py tests/test_catalog_bootstrap_packaging.py tests/test_catalog_requester_packaging.py -q
git add -- scripts/install_catalog_bootstrap_assistant.ps1 scripts/start_catalog_bootstrap_assistant.ps1 tests/test_catalog_bootstrap_windows.py tests/test_catalog_requester_packaging.py
git diff --cached --check
git commit -m "feat: install one-click catalog bootstrap assistant"
~~~

### Task 8: Secure Codex launcher and isolated profile

**Files:**

- Create: `scripts/launch_catalog_codex_secure.ps1`
- Create: `config/catalog_agent_codex_profile_v1.toml`
- Create: `tests/test_catalog_agent_codex_launcher.py`
- Modify: `scripts/install_catalog_agent_sandbox.ps1`
- Modify: `docs/runbooks/CATALOG_AGENT_SANDBOX.md`

**Interfaces:**

- Consumes exact AppX family `OpenAI.Codex_2p2nqsd0c76g0`.
- Produces sealed low-privilege launch and process-tree audit.

- [ ] **Step 1: Write failing package/profile/owner tests**

~~~python
def test_profile_disables_privileged_plugins() -> None:
    profile = tomllib.loads(AGENT_PROFILE.read_text(encoding="utf-8"))
    for name in ("chrome@openai-bundled", "browser@openai-bundled",
                 "computer-use@openai-bundled"):
        assert profile["plugins"][name]["enabled"] is False
    assert "mcp_servers" not in profile
    assert profile["agents"] == {"max_threads": 1, "max_depth": 1}


def test_launcher_accepts_no_path_or_arguments() -> None:
    assert powershell_parameters(LAUNCHER) == set()
    assert "OpenAI.Codex_2p2nqsd0c76g0" in LAUNCHER.read_text()
~~~

- [ ] **Step 2: Implement exact AppX activation as AURORAAgent**

Resolve package family and verified publisher on every launch, register it for `AURORAAgent` if absent, and use a Windows-protected random low-account credential. Accept no path/arguments, never elevate, require no HP Codex process, and verify every ChatGPT/Codex descendant is owned by `AURORAAgent`.

Profile disables browser, Chrome, computer-use, external MCP, notifications, and nonessential plugins. ACLs deny HP profile, gh config, browser profiles, requester/auditor roots, and bootstrap admin state. If OpenAI requests login, controller remains disabled until login and process audit finish.

- [ ] **Step 3: Run tests and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_agent_codex_launcher.py tests/test_catalog_requester_packaging.py -q
git add -- scripts/launch_catalog_codex_secure.ps1 scripts/install_catalog_agent_sandbox.ps1 config/catalog_agent_codex_profile_v1.toml tests/test_catalog_agent_codex_launcher.py tests/test_catalog_requester_packaging.py docs/runbooks/CATALOG_AGENT_SANDBOX.md
git diff --cached --check
git commit -m "feat: launch Codex under isolated catalog agent"
~~~

### Task 9: Final live audit, qualification, and receipt

**Files:**

- Create: `infra/sp500_megarun/catalog_bootstrap_finalizer.py`
- Create: `tests/test_catalog_bootstrap_end_to_end.py`
- Create: `docs/runbooks/CATALOG_BOOTSTRAP_ASSISTANT.md`
- Modify: `scripts/apply_catalog_github_controls.py`
- Modify: `scripts/audit_catalog_github_controls.py`
- Modify: `docs/runbooks/CATALOG_CONTROLLER_BOOTSTRAP_RECEIPT.md`
- Modify live policy/qualification workflows only if a failing test proves a gap.

**Interfaces:**

- Produces: `CatalogBootstrapFinalReceiptV1`, production seal, enabled read-back, and `READY`.

- [ ] **Step 1: Write failing complete-evidence and zero-production tests**

~~~python
def test_every_required_final_fact_is_mandatory() -> None:
    complete = complete_evidence()
    for field in CatalogBootstrapFinalEvidenceV1.model_fields:
        with pytest.raises(ValueError):
            finalize_bootstrap(complete.model_copy(update={field: None}))


def test_final_ready_has_zero_production_activity() -> None:
    receipt = finalize_bootstrap(complete_evidence())
    assert receipt.result == "READY"
    assert receipt.controller_enabled_readback is True
    assert receipt.production_request_count == 0
    assert receipt.production_run_count == 0
~~~

- [ ] **Step 2: Implement finalizer in fail-closed order**

~~~python
def finalize_bootstrap(evidence):
    verify_real_app_bindings(evidence)
    verify_merged_protected_commit(evidence)
    verify_local_identities_acls_and_broker(evidence)
    verify_live_github_controls_and_budgets(evidence)
    verify_three_equivalent_qualifications(evidence)
    verify_single_disabled_bootstrap_request(evidence)
    verify_zero_production_activity(evidence)
    set_controller_enabled_and_read_back(evidence.github)
    verify_post_enable_live_controls(evidence)
    seal = create_broker_production_seal(evidence)
    return build_ready_receipt(evidence, seal)
~~~

Any exception after an enable attempt resets `CATALOG_CONTROLLER_ENABLED=false` and reads it back. Receipt contains every original-plan field, hashes itself, and contains no secrets.

- [ ] **Step 3: Run full focused acceptance and commit**

~~~powershell
& "C:/Python314/python.exe" -m pytest tests/test_catalog_bootstrap_end_to_end.py tests/test_catalog_bootstrap_assistant.py tests/test_catalog_bootstrap_manifest_flow.py tests/test_catalog_bootstrap_secret_isolation.py tests/test_catalog_bootstrap_binding.py tests/test_catalog_bootstrap_packaging.py tests/test_catalog_bootstrap_windows.py tests/test_catalog_agent_codex_launcher.py tests/test_catalog_github_controls.py tests/test_catalog_controller_workflows.py tests/test_catalog_controller_qualification.py tests/test_catalog_requester_packaging.py tests/test_catalog_requester_broker.py -q
git add -- infra/sp500_megarun/catalog_bootstrap_finalizer.py tests/test_catalog_bootstrap_end_to_end.py docs/runbooks/CATALOG_BOOTSTRAP_ASSISTANT.md scripts/apply_catalog_github_controls.py scripts/audit_catalog_github_controls.py docs/runbooks/CATALOG_CONTROLLER_BOOTSTRAP_RECEIPT.md
git diff --cached --check
git commit -m "feat: finalize assisted catalog bootstrap"
~~~

### Task 10: Adversarial acceptance, release, and user confirmation

**Files:**

- Modify only files proven defective by acceptance.
- Update: `docs/runbooks/CATALOG_CONTROLLER_BOOTSTRAP_RECEIPT.md`

- [ ] **Step 1: Run repository-wide checks**

~~~powershell
& "C:/Python314/python.exe" -m pytest -q
& "C:/Python314/python.exe" -m pre_commit run --all-files
python scripts/build_catalog_campaign_definition.py --campaign-key sp500-optimized-catalog-v1 --check
git diff --check
~~~

- [ ] **Step 2: Complete three clean adversarial rounds**

Each round proves:

1. AI cannot dispatch, cancel, retry, modify GitHub, or access privileged identities.
2. No secret reaches arguments, environment, logs, state, receipts, git, temp, Downloads, or Codex.
3. Interrupted phases resume without duplicate App, issue, PR, ticket, or request.
4. No production request or heavy run is created.
5. Enablement is last and rollback works for every later failure.
6. App, repository, permissions, authority, PR, process owner, ACL, budget, storage, or workflow drift blocks.

Any material issue resets the clean-round count to zero and is fixed with a failing test first.

- [ ] **Step 3: Push exact HEAD and require green GitHub checks**

~~~powershell
git status --short --branch
git fetch origin codex/sp500-search-method-benchmark-short
git merge-base --is-ancestor origin/codex/sp500-search-method-benchmark-short HEAD
git push origin HEAD:codex/sp500-search-method-benchmark-short
~~~

Verify only expected policy/lint workflows ran and no catalog run exists.

- [ ] **Step 4: Install nonsecret assistant shell**

~~~powershell
& scripts/install_catalog_bootstrap_assistant.ps1
& scripts/install_catalog_bootstrap_assistant.ps1 -Apply -Confirm AURORA_CATALOG_BOOTSTRAP_ASSISTANT_V1
~~~

Require dry-run first, then UAC apply. Read back hashes, ACLs, shortcut, venv, package, and controller-disabled state. No App/key exists yet.

- [ ] **Step 5: Hand control to fixed user-owned wizard**

The user opens `Instalar controlador AURORA`. It closes HP Codex, shows official requester Create/Install and auditor Create/Install confirmations, completes remaining phases, and starts Codex as `AURORAAgent`. The agent never controls the authenticated browser.

- [ ] **Step 6: Verify terminal receipt from AURORAAgent**

Read only `C:\ProgramData\AURORA\CatalogRequester\receipts\controller-bootstrap-v1.receipt.json` and require:

~~~text
result=READY
controller_enabled_readback=true
production_seal_matches_bootstrap=true
production_request_count=0
production_run_count=0
requester_app_exact_permissions=true
auditor_app_exact_read_permissions=true
agent_identity=AURORAAgent
broker_identity=AURORARequester
admin_credential_exposed=false
requester_credential_exposed=false
auditor_credential_exposed=false
~~~

Anything missing or false is `BLOCKED`, never partial success.

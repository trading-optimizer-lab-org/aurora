# GitHub Performance Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Subagents
> are unavailable in this side conversation. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Build the mandatory, reusable GitHub-only execution foundation for all
future heavy Aurora workflows.

**Architecture:** A frozen version-3 run spec is validated against a canonical
schema and capacity profile. A planner chooses the useful job count, balances
logical units, splits matrices at 256, records GitHub telemetry, preserves
attempts, performs a bounded hierarchical merge, and independently verifies the
final artifact. Existing workflows are grandfathered by immutable allowlist;
new heavy workflows must call the reusable framework.

**Tech Stack:** Python 3.12, Pydantic 2, PyYAML, PyArrow, JSON Schema, GitHub
Actions, Parquet, immutable Actions artifacts.

## Global Constraints

- Heavy execution and every test run occur in GitHub Actions.
- No local backtests, smokes, benchmarks, or pytest invocations.
- Repository: `trading-optimizer-lab-org/aurora`.
- Implementation branch: `codex/github-performance-system`.
- Standard-runner ceiling: 360 organization-specific concurrent jobs.
- Matrix ceiling: 256 jobs.
- Standard runner only; larger, GPU, and paid runners are prohibited.
- Heavy workflows use `workflow_dispatch` or `workflow_call`, never automatic
  push or pull-request fan-out.
- The planner may request fewer than 360 jobs when that is faster.
- Existing workflows remain unchanged and are grandfathered by filename and
  content hash.
- New runtime paths use `aurora.core.runtime_paths`.
- Existing `ProtocolPolicy`, `SnapshotStore`, `FeatureStore`,
  `WitnessRecorder`, `ExperimentTracker`, and `monitoring.telemetry` remain the
  scientific sources of truth.
- No locked data and no validation-driven scientific selection.
- External actions are pinned to immutable commit SHAs.
- Every task is committed separately.
- After the first task, push the branch and create one draft PR. Later tasks
  push to the same branch and wait for GitHub checks.

---

## File Map

### Canonical policy and configuration

- `docs/GITHUB_RUN_MASTER_STANDARD.md`: tracked canonical copy of the desktop
  version-3.0 run standard.
- `config/schemas/github_run_spec_v3.schema.json`: machine-readable future-run
  schema packaged with Aurora.
- `config/templates/github_run_v3.yaml`: fillable version-3 run template.
- `config/github_capacity_profile.json`: support-confirmed capacity and runner
  reference.
- `config/official_actions_lock.json`: immutable commits for official actions.
- `config/legacy_workflow_allowlist.json`: adoption-time workflow hashes.

### Python package

- `core/execution_policy.py`: centralized GitHub-only guard.
- `infra/github_performance/contracts.py`: immutable Pydantic contracts.
- `infra/github_performance/preflight.py`: spec, capacity, repository, and
  workflow validation.
- `infra/github_performance/telemetry.py`: performance spans and Parquet export
  built on `monitoring.telemetry`.
- `infra/github_performance/shard_planner.py`: job-count model, weighted LPT,
  and matrix split.
- `infra/github_performance/execution_planner.py`: immutable performance and
  execution plans assembled from pilot evidence.
- `infra/github_performance/checkpoint.py`: atomic checkpoint creation and
  bounded resume state.
- `infra/github_performance/recovery.py`: failure classification and selective
  retry plans.
- `infra/github_performance/merge_planner.py`: merge groups and reconciliation.
- `infra/github_performance/verifier.py`: artifact and closure verification.
- `infra/github_performance/workload.py`: phase-1 workload protocol and loader.
- `infra/github_performance/github_api.py`: read-only GitHub jobs timeline
  collection and pagination.
- `infra/github_performance/reference_workload.py`: deterministic real Aurora
  benchmark adapter.
- `infra/github_performance/__init__.py`: public Phase-1 API.

### CLI and wrappers

- `cli/cmd_github.py`: `aurora github` commands.
- `cli/forge.py`: register the command group.
- `scripts/aurora_github_run.py`: workload-mode entrypoint.
- `scripts/aurora_github_recover.py`: selective recovery-plan entrypoint.
- `scripts/aurora_github_merge.py`: merge entrypoint.
- `scripts/aurora_github_verify.py`: independent verifier entrypoint.
- `scripts/collect_github_run_timeline.py`: post-run GitHub timeline collector.

### GitHub Actions

- `.github/actions/aurora-runtime-setup/action.yml`: pinned, restore-only setup.
- `.github/workflows/_aurora-future-run-v3.yml`: reusable execution spine.
- `.github/workflows/github-performance-policy.yml`: lightweight PR policy.
- `.github/workflows/github-performance-ci.yml`: GitHub-only unit and smoke
  tests.
- `.github/workflows/github-performance-reference.yml`: manual end-to-end
  caller.
- `.github/workflows/github-performance-benchmark.yml`: manual baseline versus
  framework comparison.

### Tests

- `tests/test_execution_policy.py`
- `tests/test_github_performance_contracts.py`
- `tests/test_github_performance_preflight.py`
- `tests/test_github_performance_telemetry.py`
- `tests/test_github_performance_shard_planner.py`
- `tests/test_github_performance_merge.py`
- `tests/test_github_performance_verifier.py`
- `tests/test_github_performance_workload.py`
- `tests/test_github_performance_cli.py`
- `tests/test_github_performance_workflows.py`
- `tests/test_github_performance_reference.py`
- `tests/test_github_performance_recovery.py`
- `tests/github_performance_helpers.py`: shared deterministic factories for
  complete specs, units, attempts, workflows, and GitHub timeline payloads.

---

### Task 1: Canonical Standard, Schema, Capacity, and GitHub Test Lane

**Files:**
- Create: `docs/GITHUB_RUN_MASTER_STANDARD.md`
- Create: `config/schemas/github_run_spec_v3.schema.json`
- Create: `config/templates/github_run_v3.yaml`
- Create: `config/github_capacity_profile.json`
- Create: `config/official_actions_lock.json`
- Create: `.github/workflows/github-performance-ci.yml`
- Create: `tests/test_github_performance_contracts.py`
- Modify: `pyproject.toml:27-46`
- Modify: `pyproject.toml:150-152`

**Interfaces:**
- Produces: version-3 YAML accepted by
  `jsonschema.Draft202012Validator`.
- Produces: capacity fields
  `standard_concurrency_ceiling`, `matrix_job_ceiling`,
  `runner_label`, and `confirmed_on`.
- Produces: action lock mapping action name to full 40-character SHA.

- [x] **Step 1: Copy the reviewed standard into the repository**

Copy the exact UTF-8 content of
`C:\Users\HP\Desktop\PLANTILLA_MAESTRA_RUN_GITHUB_AURORA.md` to
`docs/GITHUB_RUN_MASTER_STANDARD.md`. Confirm both files have the same SHA-256
before staging.

- [x] **Step 2: Add schema and capacity tests**

```python
def load_schema() -> dict[str, Any]:
    return json.loads(
        Path("config/schemas/github_run_spec_v3.schema.json").read_text()
    )


def load_template() -> dict[str, Any]:
    return yaml.safe_load(
        Path("config/templates/github_run_v3.yaml").read_text()
    )


def template_mapping_paths(
    value: Mapping[str, Any],
    prefix: tuple = (),
) -> set[tuple]:
    paths: set[tuple] = set()
    for key, child in value.items():
        path = prefix + (key,)
        paths.add(path)
        if isinstance(child, Mapping):
            paths.update(template_mapping_paths(child, path))
    return paths


def schema_mapping_paths(
    schema: Mapping[str, Any],
    prefix: tuple = (),
) -> set[tuple]:
    paths: set[tuple] = set()
    for key, child in schema.get("properties", {}).items():
        path = prefix + (key,)
        paths.add(path)
        if child.get("type") == "object":
            paths.update(schema_mapping_paths(child, path))
    return paths


def test_master_template_validates_against_v3_schema() -> None:
    jsonschema.Draft202012Validator(load_schema()).validate(load_template())


def test_capacity_profile_matches_support_confirmation() -> None:
    profile = json.loads(
        Path("config/github_capacity_profile.json").read_text()
    )
    assert profile["standard_concurrency_ceiling"] == 360
    assert profile["matrix_job_ceiling"] == 256
    assert profile["runner_label"] == "ubuntu-24.04"
    assert profile["larger_runners_allowed"] is False


def test_schema_covers_every_master_template_key() -> None:
    assert schema_mapping_paths(load_schema()) == template_mapping_paths(
        load_template()
    )
```

- [x] **Step 3: Add the version-3 schema and template**

Require these top-level objects:

```json
{
  "required": [
    "schema_version",
    "identity",
    "objective",
    "policy",
    "data",
    "execution",
    "resources",
    "performance",
    "retries",
    "artifacts",
    "security",
    "statistics",
    "metrics",
    "reconciliation",
    "gates"
  ]
}
```

Set `additionalProperties: false` at the top level and on every fixed contract
object. Set `schema_version` to the constant `"3.0"`. Define every key present
in the embedded master template with its actual JSON type, enum, minimum,
maximum, and required status; the path-coverage test prevents silent schema
omissions. Require `execution_location: github_actions`,
`local_runs_allowed: false`, `matrix_max_jobs` no greater than 256,
`execution.max_matrix_jobs` no greater than 256, `planner_max_jobs` no greater
than 360, and `larger_runners_allowed: false`.

The fillable template may use empty strings so the template itself remains
schema-valid. Semantic preflight rejects empty user-owned values with
`REQUIRED_VALUE_EMPTY`. Runtime-derived hashes may remain blank in the requested
spec and are filled by `freeze_contract`; if supplied, they must match observed
evidence. SHA-256 fields use 64 lowercase hexadecimal characters and
`code_sha` uses 40.

- [x] **Step 4: Add immutable capacity and action locks**

Use this capacity record:

```json
{
  "schema_version": "1",
  "organization": "trading-optimizer-lab-org",
  "repository": "aurora",
  "repository_visibility": "public",
  "plan": "enterprise",
  "standard_concurrency_ceiling": 360,
  "matrix_job_ceiling": 256,
  "runner_label": "ubuntu-24.04",
  "reference_cpu": 4,
  "reference_memory_gb": 16,
  "reference_ssd_gb": 14,
  "larger_runners_allowed": false,
  "confirmed_on": "2026-06-02",
  "confirmation_source": "github_support_email"
}
```

Pin these current official action commits:

```json
{
  "actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
  "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
  "actions/cache": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
  "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
  "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
}
```

- [x] **Step 5: Declare the runtime dependency and exact package data**

Add `jsonschema>=4.23` to the main project dependencies because every future
workflow executes preflight. Extend Aurora package data exactly to:

```toml
"aurora" = [
    "py.typed",
    "config/*.yaml",
    "config/*.yml",
    "config/templates/*.yaml",
    "config/schemas/*.json",
]
```

Add a test that loads both nested files with:

```python
root = importlib.resources.files("aurora")
schema = root.joinpath("config/schemas/github_run_spec_v3.schema.json")
template = root.joinpath("config/templates/github_run_v3.yaml")
assert schema.is_file()
assert template.is_file()
```

- [x] **Step 6: Add the lightweight GitHub test workflow**

Use `pull_request` and `workflow_dispatch`; pin checkout and setup-python to the
SHAs above. Run only:

```bash
python -m pip install -e ".[dev]"
python -m pytest \
  tests/test_github_performance_contracts.py \
  --tb=short -q
```

The workflow uses `ubuntu-24.04`, `permissions: contents: read`, and a
15-minute timeout.

- [x] **Step 7: Commit, push, and open the draft PR**

```bash
git add docs/GITHUB_RUN_MASTER_STANDARD.md config/schemas \
  config/templates config/github_capacity_profile.json \
  config/official_actions_lock.json pyproject.toml \
  tests/test_github_performance_contracts.py \
  .github/workflows/github-performance-ci.yml
git commit -m "feat: add GitHub run v3 contracts"
git push -u origin codex/github-performance-system
gh pr create --draft \
  --base main \
  --head codex/github-performance-system \
  --title "Build Aurora GitHub performance system" \
  --body "Phase 1 implementation tracked in docs/superpowers/plans/2026-07-25-github-performance-phase1.md"
gh pr checks --watch
```

Expected: `github-performance-ci` passes on GitHub. Do not run pytest locally.

---

### Task 2: Central GitHub-Only Execution Guard

**Files:**
- Create: `core/execution_policy.py`
- Create: `tests/test_execution_policy.py`

**Interfaces:**
- Produces:
  `require_github_execution(operation: str, environ: Mapping[str, str] | None = None) -> None`.
- Raises: `LocalRunBlocked`.

- [x] **Step 1: Write guard tests**

```python
def test_guard_allows_github() -> None:
    require_github_execution("candidate sweep", {"GITHUB_ACTIONS": "true"})


def test_guard_blocks_local() -> None:
    with pytest.raises(LocalRunBlocked, match="Run local bloqueado"):
        require_github_execution("candidate sweep", {})


def test_guard_allows_exact_user_token() -> None:
    env = {
        "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT":
            "USER_REQUESTED_LOCAL_RUN_THIS_TURN"
    }
    require_github_execution("candidate sweep", env)
```

- [x] **Step 2: Implement the guard**

```python
EXPLICIT_LOCAL_TOKEN = "USER_REQUESTED_LOCAL_RUN_THIS_TURN"


class LocalRunBlocked(RuntimeError):
    pass


def require_github_execution(
    operation: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    env = os.environ if environ is None else environ
    if env.get("GITHUB_ACTIONS", "").lower() == "true":
        return
    if env.get("AURORA_ALLOW_LOCAL_RUNS_EXPLICIT") == EXPLICIT_LOCAL_TOKEN:
        return
    raise LocalRunBlocked(
        "Run local bloqueado por politica Aurora. "
        f"Operacion: {operation}. Lanzalo en GitHub Actions o pide "
        "explicitamente ejecucion local."
    )
```

- [x] **Step 3: Push and verify in GitHub**

```bash
git add core/execution_policy.py tests/test_execution_policy.py
git commit -m "feat: centralize GitHub-only execution guard"
git push
gh pr checks --watch
```

Expected: guard tests pass on Linux and no legacy script is changed.

---

### Task 3: Immutable Performance Contracts and Hashes

**Files:**
- Create: `infra/github_performance/__init__.py`
- Create: `infra/github_performance/contracts.py`
- Modify: `pyproject.toml:56-149`
- Create: `tests/github_performance_helpers.py`
- Create: `tests/test_github_performance_contracts.py`

**Interfaces:**
- Produces models: `RunSpec`, `CapacityProfile`, `PerformanceContract`,
  `RuntimeEvidence`,
  `ResourceSample`, `PreparedInputs`, `SmokeResult`, `PilotResult`, `WorkUnit`,
  `WorkUnitManifest`, `JobCountAlternative`, `JobCountDecision`,
  `AttemptManifest`, `UnitAttemptRecord`,
  `ShardDefinition`, `ShardPlan`, `MatrixSplit`, `ExecutionPlan`, `MergeGroup`,
  `MergePlan`, `Violation`, `PreflightReport`, `ReconciliationResult`,
  `CheckpointManifest`, `RecoveryDecision`, `RecoveryPlan`,
  `VerificationReport`, and `BenchmarkReport`.
- Produces:
  `canonical_sha256(value: BaseModel | Mapping[str, Any]) -> str`.

- [x] **Step 1: Add deterministic contract tests**

```python
def _manifest_payload(
    shard_id: str, attempt_id: str, state: str = "completed"
) -> dict[str, object]:
    return {
        "shard_id": shard_id,
        "attempt_id": attempt_id,
        "state": state,
        "spec_hash": "1" * 64,
        "policy_hash": "2" * 64,
        "snapshot_hash": "3" * 64,
        "code_sha": "4" * 40,
        "dependency_lock_sha256": "5" * 64,
        "capacity_profile_sha256": "6" * 64,
        "output_sha256": "7" * 64,
        "reason_code": None,
        "artifact_name": f"run-shard-g00-{shard_id}-{attempt_id}",
        "unit_attempts_path": "unit_attempts.parquet",
        "unit_attempts_sha256": "8" * 64,
        "checkpoint_artifact": None,
        "completed_unit_count": 1,
        "output_rows": 1,
        "output_bytes": 128,
    }


def test_contract_hash_ignores_mapping_order() -> None:
    assert canonical_sha256({"a": 1, "b": 2}) == canonical_sha256(
        {"b": 2, "a": 1}
    )


def test_run_spec_is_deeply_immutable() -> None:
    spec = RunSpec.model_validate(minimal_valid_spec())
    with pytest.raises(TypeError):
        spec.policy["locked_opened"] = True


def test_attempt_identity_is_physical_not_logical() -> None:
    a = AttemptManifest.model_validate(_manifest_payload("s1", "a1"))
    b = AttemptManifest.model_validate(_manifest_payload("s1", "a2"))
    assert a.shard_id == b.shard_id
    assert a.attempt_id != b.attempt_id


def test_terminal_state_is_closed_enum() -> None:
    with pytest.raises(ValidationError):
        AttemptManifest.model_validate(
            _manifest_payload("u", "a", state="skipped")
        )
```

- [x] **Step 2: Implement frozen Pydantic models**

Use `ConfigDict(frozen=True, extra="forbid")`. Define terminal states exactly:

```python
class TerminalState(StrEnum):
    COMPLETED = "completed"
    RIGHT_CENSORED = "right_censored"
    UNSUPPORTED = "unsupported"
    FAILED_TECHNICAL = "failed_technical"
```

Add `FrozenMapping`, `deep_freeze_json`, and `deep_thaw_json` helpers in
`contracts.py`. `FrozenMapping` implements the read-only `Mapping` protocol and
has no mutating methods. `deep_freeze_json` recursively converts mappings to
`FrozenMapping` and lists to tuples. A `RunSpec` field validator applies it to
every contract section after Pydantic validation. `canonical_sha256` and
`resolve_run_spec` use `deep_thaw_json` to obtain a plain, deterministically
ordered JSON tree. This is required because `ConfigDict(frozen=True)` alone
does not freeze nested dictionaries.

Use these exact minimum fields so later tasks share one vocabulary:

```python
class RunSpec(FrozenModel):
    schema_version: Literal["3.0"]
    identity: Mapping[str, Any]
    objective: Mapping[str, Any]
    policy: Mapping[str, Any]
    data: Mapping[str, Any]
    execution: Mapping[str, Any]
    resources: Mapping[str, Any]
    performance: Mapping[str, Any]
    retries: Mapping[str, Any]
    artifacts: Mapping[str, Any]
    security: Mapping[str, Any]
    statistics: Mapping[str, Any]
    metrics: Mapping[str, Any]
    reconciliation: Mapping[str, Any]
    gates: Mapping[str, Any]


class RuntimeEvidence(FrozenModel):
    code_sha: str
    workflow_sha256: str
    policy_hash: str
    dependency_lock_sha256: str
    capacity_profile_sha256: str
    data_manifest_sha256: str
    snapshot_hash: str
    metric_contract_sha256: str
    environment_sha256: str


class CapacityProfile(FrozenModel):
    schema_version: str
    organization: str
    repository: str
    repository_visibility: Literal["public", "private", "internal"]
    plan: str
    standard_concurrency_ceiling: int
    matrix_job_ceiling: int
    runner_label: str
    reference_cpu: int
    reference_memory_gb: int
    reference_ssd_gb: int
    larger_runners_allowed: bool
    confirmed_on: date
    confirmation_source: str


class PerformanceContract(FrozenModel):
    resolved_spec_sha256: Sha256
    code_sha: CodeSha
    workflow_sha256: Sha256
    policy_hash: Sha256
    snapshot_hash: Sha256
    data_manifest_sha256: Sha256
    metric_contract_sha256: Sha256
    dependency_lock_sha256: Sha256
    capacity_profile_sha256: Sha256
    environment_sha256: Sha256
    standard_runner_only: bool
    locked_opened: bool
    validation_used_for_selection: bool
    larger_runners_allowed: bool
    artifact_transport_mode: Literal[
        "auto",
        "actions_artifact",
        "snapshot_backend",
    ]
    planner_min_jobs: int
    planner_max_jobs: int
    planner_job_count_search: Literal["adaptive_exact"]
    planner_large_unit_threshold: int
    planner_exact_lpt_candidates_max: int
    matrix_job_ceiling: int
    standard_concurrency_ceiling: int
    runner_label: str
    max_memory_pct: int
    min_free_disk_gb: float
    merge_fan_in: int
    target_setup_fraction_max: float
    target_checkpoint_fraction_max: float


class ResourceSample(FrozenModel):
    rss_mb: float
    peak_memory_mb: float
    free_disk_mb: float
    cpu_seconds: float
    io_wait_seconds: float


class PreparedInputs(FrozenModel):
    manifest_path: str
    manifest_sha256: str
    snapshot_hash: str
    policy_hash: str
    artifact_names: Sequence[str]


class SmokeResult(FrozenModel):
    passed: bool
    output_sha256: str | None
    reason_codes: Sequence[str]


class PilotResult(FrozenModel):
    queue_seconds: float
    setup_seconds: float
    transfer_fixed_seconds: float
    transfer_per_wave_seconds: float
    checkpoint_seconds: float
    merge_fixed_seconds: float
    merge_per_shard_seconds: float
    verify_seconds: float
    unit_seconds_p50: float
    unit_seconds_p95: float
    usable_parallelism: int


class WorkUnit(FrozenModel):
    unit_key: str
    estimated_seconds: float
    payload_ref: str
    payload_sha256: str


class WorkUnitManifest(FrozenModel):
    path: str
    sha256: str
    schema_version: str
    unit_count: int
    total_estimated_seconds: float


class ShardDefinition(FrozenModel):
    shard_id: str
    assignment_artifact: str
    assignment_member: str
    assignment_sha256: str
    unit_count: int
    estimated_seconds: float
    merge_group: str


class ShardPlan(FrozenModel):
    selected_jobs: int
    work_unit_manifest_sha256: str
    assignment_artifact: str
    assignment_manifest_sha256: str
    shards: Sequence[ShardDefinition]
    plan_sha256: str


class JobCountAlternative(FrozenModel):
    jobs: int
    waves: int
    slowest_shard_seconds: float
    predicted_seconds: float
    estimate_kind: Literal["analytical", "histogram", "exact_lpt"]


class JobCountDecision(FrozenModel):
    selected_jobs: int
    predicted_seconds: float
    alternatives: Sequence[JobCountAlternative]


class MatrixSplit(FrozenModel):
    matrix_a: Sequence[ShardDefinition]
    matrix_b: Sequence[ShardDefinition]
    has_matrix_b: bool


class ExecutionPlan(FrozenModel):
    job_count: JobCountDecision
    shard_plan: ShardPlan
    matrix_split: MatrixSplit
    numeric_threads: int
    checkpoint_interval_seconds: float
    artifact_compression_level: int
    fallback_plan_sha256: str


class MergeGroup(FrozenModel):
    group_id: str
    level: int
    input_artifacts: Sequence[str]
    projected_input_bytes: int
    projected_output_bytes: int
    output_artifact: str


class MergePlan(FrozenModel):
    fan_in: int
    groups: Sequence[MergeGroup]
    plan_sha256: str


class AttemptManifest(FrozenModel):
    shard_id: str
    attempt_id: str
    state: TerminalState
    spec_hash: str
    policy_hash: str
    snapshot_hash: str
    code_sha: str
    dependency_lock_sha256: str
    capacity_profile_sha256: str
    output_sha256: str | None
    reason_code: str | None
    artifact_name: str | None
    unit_attempts_path: str | None
    unit_attempts_sha256: str | None
    checkpoint_artifact: str | None
    completed_unit_count: int
    output_rows: int
    output_bytes: int


class UnitAttemptRecord(FrozenModel):
    unit_key: str
    shard_id: str
    attempt_id: str
    state: TerminalState
    output_sha256: str | None
    reason_code: str | None


class CheckpointManifest(FrozenModel):
    shard_id: str
    attempt_id: str
    artifact_name: str
    completed_unit_count: int
    last_completed_unit_key: str | None
    payload_path: str
    payload_sha256: str
    created_at: datetime


class RecoveryDecision(FrozenModel):
    shard_id: str
    prior_attempt_id: str
    action: Literal["retry", "replan", "do_not_retry"]
    failure_class: str
    next_attempt_id: str | None
    checkpoint_artifact: str | None
    reason_code: str


class RecoveryPlan(FrozenModel):
    decisions: Sequence[RecoveryDecision]
    retry_matrix_a: Sequence[Mapping[str, Any]]
    retry_matrix_b: Sequence[Mapping[str, Any]]
    has_retry_matrix_a: bool
    has_retry_matrix_b: bool
    plan_sha256: str


class ReconciliationResult(FrozenModel):
    expected_units: int
    completed: int
    right_censored: int
    unsupported: int
    failed_technical: int
    selected_attempt_ids: Sequence[str]
    identical_duplicate_attempt_ids: Sequence[str]
    conflicting_unit_keys: Sequence[str]
    missing_unit_keys: Sequence[str]
    partial: bool


class Violation(FrozenModel):
    code: str
    path: str
    message: str
    severity: Literal["error", "warning"]


class PreflightReport(FrozenModel):
    valid: bool
    spec_hash: str | None
    violations: Sequence[Violation]

    @property
    def violation_codes(self) -> frozenset[str]:
        return frozenset(item.code for item in self.violations)


class VerificationReport(FrozenModel):
    passed: bool
    partial: bool
    requirements_passed: bool
    locked_opened: bool
    validation_used_for_selection: bool
    standard_runner_only: bool
    matrix_job_ceiling_respected: bool
    evidence_paths: Sequence[str]


class BenchmarkReport(FrozenModel):
    passed: bool
    scientific_outputs_equal: bool
    reference_wall_seconds: float
    optimized_wall_seconds: float
    speedup: float
    reference_billable_minutes: float
    optimized_billable_minutes: float
    predicted_observed_error_pct: float
```

`ShardDefinition` carries only compact artifact/member references, hashes,
unit count, projected cost, and merge group; it never embeds all unit keys.
`ExecutionPlan` carries the selected job-count decision, the full shard plan,
the matrix split, thread limits, checkpoint interval, compression, and fallback
plan. `ReconciliationResult` carries exact terminal counts, selected attempts,
identical duplicates, conflicts, missing units, and `partial`.
`VerificationReport` and `BenchmarkReport` carry explicit `passed` flags and
immutable evidence paths.

`AttemptManifest` describes one physical shard attempt and includes spec,
policy, snapshot, code, dependency, capacity-profile, and output hashes.
`UnitAttemptRecord` describes one logical unit inside that attempt. Completed
physical manifests require `output_sha256`, `unit_attempts_path`, and
`unit_attempts_sha256`; completed logical records require `output_sha256`.
Other terminal states require `reason_code`.

- [x] **Step 3: Add complete deterministic test factories**

Create these factories in `tests/github_performance_helpers.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import yaml

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    PerformanceContract,
    PilotResult,
    RuntimeEvidence,
    ShardDefinition,
    TerminalState,
    UnitAttemptRecord,
    VerificationReport,
    WorkUnit,
)


def minimal_valid_spec() -> dict[str, Any]:
    payload = yaml.safe_load(
        Path("config/templates/github_run_v3.yaml").read_text(encoding="utf-8")
    )
    payload["identity"].update(
        {
            "campaign_id": "test-campaign",
            "run_type": "reference",
            "code_ref": "refs/heads/test",
            "workflow": ".github/workflows/test.yml",
            "deadline_utc": "2099-12-31T00:00:00Z",
        }
    )
    payload["objective"].update(
        {
            "description": "Verify the GitHub performance framework",
            "success_criteria": ["partial=false"],
            "negative_result_criteria": ["no accepted result"],
            "technical_failure_criteria": ["partial=true"],
        }
    )
    payload["policy"].update(
        {
            "train_start": "1995-01-01",
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "decision_timezone": "UTC",
            "decision_timestamp_rule": "close",
            "execution_timestamp_rule": "next_open",
            "market_calendar": "XNYS",
        }
    )
    payload["execution"].update(
        {
            "shard_seed_formula": "global_seed + shard_index",
            "python_version": "3.12",
            "runner_image": "ubuntu-24.04",
        }
    )
    payload["artifacts"]["final_name"] = "test-campaign-results"
    payload["metrics"].update(
        {
            "return_type": "simple",
            "return_basis": "total_return",
            "annualization_rule": "252",
            "risk_free_source": "zero",
            "undefined_metric_policy": "null",
        }
    )
    return payload


def complete_runtime_evidence() -> RuntimeEvidence:
    return RuntimeEvidence(
        code_sha="a" * 40,
        workflow_sha256="d" * 64,
        policy_hash="b" * 64,
        dependency_lock_sha256="e" * 64,
        capacity_profile_sha256="f" * 64,
        data_manifest_sha256="1" * 64,
        snapshot_hash="c" * 64,
        metric_contract_sha256="2" * 64,
        environment_sha256="3" * 64,
    )


def write_yaml(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(dict(payload), sort_keys=False),
        encoding="utf-8",
    )
    return path


def make_unit(index: int, seconds: float = 1.0) -> WorkUnit:
    key = f"u{index:04d}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return WorkUnit(
        unit_key=key,
        estimated_seconds=seconds,
        payload_ref=f"units/{key}.json",
        payload_sha256=digest,
    )


def make_shard(index: int) -> ShardDefinition:
    return ShardDefinition(
        shard_id=f"s{index:03d}",
        assignment_artifact="run-assignment-bundle-000",
        assignment_member=f"assignments/s{index:03d}.parquet",
        assignment_sha256="8" * 64,
        unit_count=1,
        estimated_seconds=1.0,
        merge_group=f"g{index // 30:02d}",
    )


def contract() -> PerformanceContract:
    return PerformanceContract(
        resolved_spec_sha256="0" * 64,
        code_sha="a" * 40,
        workflow_sha256="b" * 64,
        policy_hash="c" * 64,
        snapshot_hash="d" * 64,
        data_manifest_sha256="e" * 64,
        metric_contract_sha256="f" * 64,
        dependency_lock_sha256="1" * 64,
        capacity_profile_sha256="2" * 64,
        environment_sha256="3" * 64,
        standard_runner_only=True,
        locked_opened=False,
        validation_used_for_selection=False,
        larger_runners_allowed=False,
        artifact_transport_mode="auto",
        planner_min_jobs=1,
        planner_max_jobs=360,
        planner_job_count_search="adaptive_exact",
        planner_large_unit_threshold=50_000,
        planner_exact_lpt_candidates_max=3,
        matrix_job_ceiling=256,
        standard_concurrency_ceiling=360,
        runner_label="ubuntu-24.04",
        max_memory_pct=80,
        min_free_disk_gb=5.0,
        merge_fan_in=30,
        target_setup_fraction_max=0.10,
        target_checkpoint_fraction_max=0.03,
    )


def pilot() -> PilotResult:
    return PilotResult(
        queue_seconds=2.0,
        setup_seconds=3.0,
        transfer_fixed_seconds=1.0,
        transfer_per_wave_seconds=0.5,
        checkpoint_seconds=0.2,
        merge_fixed_seconds=1.0,
        merge_per_shard_seconds=0.01,
        verify_seconds=0.5,
        unit_seconds_p50=1.0,
        unit_seconds_p95=2.0,
        usable_parallelism=360,
    )


def high_setup_pilot() -> PilotResult:
    return pilot().model_copy(
        update={"setup_seconds": 120.0, "transfer_per_wave_seconds": 5.0}
    )


def _shard_attempt_fields(
    shard_id: str, attempt_id: str
) -> dict[str, Any]:
    return {
        "shard_id": shard_id,
        "attempt_id": attempt_id,
        "spec_hash": "1" * 64,
        "policy_hash": "2" * 64,
        "snapshot_hash": "3" * 64,
        "code_sha": "4" * 40,
        "dependency_lock_sha256": "5" * 64,
        "capacity_profile_sha256": "6" * 64,
    }


def completed_unit(
    unit_key: str,
    attempt_id: str,
    digest: str,
    shard_id: str = "s000",
) -> UnitAttemptRecord:
    return UnitAttemptRecord(
        unit_key=unit_key,
        shard_id=shard_id,
        attempt_id=attempt_id,
        state=TerminalState.COMPLETED,
        output_sha256=digest,
        reason_code=None,
    )


def unsupported_unit(
    unit_key: str,
    reason_code: str,
    shard_id: str = "s000",
) -> UnitAttemptRecord:
    return UnitAttemptRecord(
        unit_key=unit_key,
        shard_id=shard_id,
        attempt_id=f"unsupported-{unit_key}",
        state=TerminalState.UNSUPPORTED,
        output_sha256=None,
        reason_code=reason_code,
    )


def failed_attempt(
    shard_id: str, attempt_id: str, reason_code: str
) -> AttemptManifest:
    return AttemptManifest(
        **_shard_attempt_fields(shard_id, attempt_id),
        state=TerminalState.FAILED_TECHNICAL,
        output_sha256=None,
        reason_code=reason_code,
        artifact_name=f"run-failure-{shard_id}-{attempt_id}",
        unit_attempts_path=None,
        unit_attempts_sha256=None,
        checkpoint_artifact=None,
        completed_unit_count=0,
        output_rows=0,
        output_bytes=0,
    )


def verification_report(
    partial: bool,
    requirements_passed: bool,
    locked_opened: bool,
) -> VerificationReport:
    passed = not partial and requirements_passed and not locked_opened
    return VerificationReport(
        passed=passed,
        partial=partial,
        requirements_passed=requirements_passed,
        locked_opened=locked_opened,
        validation_used_for_selection=False,
        standard_runner_only=True,
        matrix_job_ceiling_respected=True,
        evidence_paths=["final_artifact_manifest.json"],
    )


def manual_heavy_workflow(local_uses: str) -> dict[str, Any]:
    return {
        "name": "future manual run",
        "on": {"workflow_dispatch": {}},
        "permissions": {"contents": "read"},
        "jobs": {"run": {"uses": local_uses}},
    }


def workflow_with_step(uses: str) -> dict[str, Any]:
    return {
        "name": "future action test",
        "on": {"workflow_dispatch": {}},
        "permissions": {"contents": "read"},
        "jobs": {
            "run": {
                "runs-on": "ubuntu-24.04",
                "steps": [{"name": "external", "uses": uses}],
            }
        },
    }


def push_triggered_heavy_workflow() -> dict[str, Any]:
    payload = manual_heavy_workflow(
        "./.github/workflows/_aurora-future-run-v3.yml"
    )
    payload["on"] = {"push": {"branches": ["main"]}}
    return payload


def _timestamp(value: str) -> str:
    return f"2026-07-25T{value}Z"


def github_job(
    name: str,
    created: str,
    started: str,
    completed: str,
) -> dict[str, Any]:
    return {
        "id": int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:8], 16),
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "created_at": _timestamp(created),
        "started_at": _timestamp(started),
        "completed_at": _timestamp(completed),
        "steps": [
            {
                "name": "Aurora runtime setup",
                "status": "completed",
                "conclusion": "success",
                "started_at": _timestamp(started),
                "completed_at": _timestamp(completed),
                "number": 1,
            }
        ],
    }
```

Keep all additional factories in this module deterministic, with hashes at
their declared lengths, timestamps in UTC, and safe policy flags by default.

- [x] **Step 4: Register the explicit package**

Add:

```toml
"aurora.infra.github_performance",
```

and:

```toml
"aurora.infra.github_performance" = "infra/github_performance"
```

- [x] **Step 5: Push and verify in GitHub**

```bash
git add infra/github_performance pyproject.toml \
  tests/github_performance_helpers.py \
  tests/test_github_performance_contracts.py
git commit -m "feat: add immutable GitHub performance contracts"
git push
gh pr checks --watch
```

---

### Task 4: Performance Telemetry Adapter

**Files:**
- Create: `infra/github_performance/telemetry.py`
- Create: `tests/test_github_performance_telemetry.py`

**Interfaces:**
- Consumes: `aurora.monitoring.telemetry.TelemetrySink`.
- Produces:
  `PerformanceRecorder.start_phase(name: str) -> PerformanceSpan`.
- Produces:
  `PerformanceRecorder.write_parquet(path: Path) -> None`.

- [x] **Step 1: Write deterministic span tests**

Inject a fake monotonic clock and fake resource sampler:

```python
def test_span_records_phase_without_scientific_values(tmp_path: Path) -> None:
    recorder = PerformanceRecorder(
        run_id="r1",
        shard_id="s1",
        clock=iter([10.0, 13.5]).__next__,
        sample_resources=lambda: ResourceSample(
            rss_mb=100.0,
            peak_memory_mb=200.0,
            free_disk_mb=300.0,
            cpu_seconds=0.4,
            io_wait_seconds=0.1,
        ),
    )
    with recorder.start_phase("compute"):
        pass
    row = recorder.rows()[0]
    assert row.phase == "compute"
    assert row.duration_seconds == 3.5
    assert "score" not in row.model_dump()
```

- [x] **Step 2: Implement bounded phase recording**

Record:

```text
run_id, job_id, shard_id, attempt_id, phase,
started_at, completed_at, duration_seconds,
units_processed, bytes_read, bytes_written,
peak_memory_mb, peak_disk_mb, cpu_seconds, io_wait_seconds
```

Use `time.perf_counter`, `resource.getrusage` on Linux, and `shutil.disk_usage`.
No candidate metrics, validation values, or secrets may enter labels or payload.

- [x] **Step 3: Export one fixed PyArrow schema**

`write_parquet` writes one table with Zstandard compression and a stable schema.
The file metadata includes schema version, code SHA, run ID, and policy hash.

- [x] **Step 4: Push and verify in GitHub**

```bash
git add infra/github_performance/telemetry.py \
  tests/test_github_performance_telemetry.py
git commit -m "feat: record GitHub phase telemetry"
git push
gh pr checks --watch
```

---

### Task 5: Preflight and Future-Workflow Static Validator

**Files:**
- Create: `infra/github_performance/preflight.py`
- Create: `tests/test_github_performance_preflight.py`

**Interfaces:**
- Produces:
  `validate_run_spec(spec_path: Path) -> PreflightReport`.
- Produces:
  `validate_future_workflow(path: Path, repo_root: Path) -> list[Violation]`.
- Produces:
  `load_github_yaml(path: Path) -> Mapping[str, Any]`.
- Produces:
  `write_preflight_report(report, output_dir) -> Path`.
- Produces:
  `resolve_run_spec(requested: RunSpec, runtime_evidence: RuntimeEvidence) -> RunSpec`.
- Produces:
  `freeze_resolved_contract(spec, runtime_evidence, output_dir) -> Sequence[Path]`.

- [x] **Step 1: Write policy tests**

Cover:

```python
def test_rejects_local_execution(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["execution"]["local_runs_allowed"] = True
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "LOCAL_EXECUTION_ALLOWED" in report.violation_codes


def test_rejects_larger_runner(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["performance"]["larger_runners_allowed"] = True
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "LARGER_RUNNER_FORBIDDEN" in report.violation_codes


def test_rejects_planner_ceiling_above_360(tmp_path: Path) -> None:
    spec = minimal_valid_spec()
    spec["performance"]["planner_max_jobs"] = 361
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "CONCURRENCY_CEILING_EXCEEDED" in report.violation_codes


def test_rejects_empty_user_owned_fields(
    tmp_path: Path,
) -> None:
    spec = minimal_valid_spec()
    spec["identity"]["campaign_id"] = ""
    path = write_yaml(tmp_path / "spec.yaml", spec)
    report = validate_run_spec(path)
    assert "REQUIRED_VALUE_EMPTY" in report.violation_codes


def test_runtime_evidence_freezes_blank_derived_hashes() -> None:
    requested = RunSpec.model_validate(minimal_valid_spec())
    resolved = resolve_run_spec(requested, complete_runtime_evidence())
    assert resolved.identity["code_sha"] == "a" * 40
    assert resolved.policy["policy_hash"] == "b" * 64
    assert resolved.data["snapshot_hash"] == "c" * 64


def test_supplied_runtime_hash_must_match_observed_evidence() -> None:
    payload = minimal_valid_spec()
    payload["identity"]["code_sha"] = "0" * 40
    requested = RunSpec.model_validate(payload)
    with pytest.raises(PreflightError, match="CODE_SHA_MISMATCH"):
        resolve_run_spec(requested, complete_runtime_evidence())


def test_rejects_missing_local_reusable_workflow(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow("./.github/workflows/missing.yml"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "LOCAL_REFERENCE_MISSING" in {v.code for v in violations}


def test_rejects_unpinned_external_action(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        workflow_with_step("actions/checkout@v6"),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "ACTION_NOT_PINNED" in {v.code for v in violations}


def test_rejects_heavy_push_trigger(tmp_path: Path) -> None:
    workflow = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        push_triggered_heavy_workflow(),
    )
    violations = validate_future_workflow(workflow, tmp_path)
    assert "HEAVY_AUTOMATIC_TRIGGER" in {v.code for v in violations}


def test_accepts_manual_framework_caller(tmp_path: Path) -> None:
    reusable = tmp_path / ".github/workflows/_aurora-future-run-v3.yml"
    reusable.parent.mkdir(parents=True)
    reusable.write_text("name: reusable\n", encoding="utf-8")
    caller = write_yaml(
        tmp_path / ".github/workflows/new.yml",
        manual_heavy_workflow(
            "./.github/workflows/_aurora-future-run-v3.yml"
        ),
    )
    assert validate_future_workflow(caller, tmp_path) == []
```

Each test writes a complete minimal YAML fixture and asserts the exact violation
code, such as `LOCAL_REFERENCE_MISSING` or `HEAVY_AUTOMATIC_TRIGGER`.

- [x] **Step 2: Implement GitHub-safe YAML loading**

Create a SafeLoader that treats `on`, `off`, `yes`, and `no` as strings rather
than YAML-1.1 booleans. Reject duplicate mapping keys with line numbers.

- [x] **Step 3: Implement run-spec preflight**

Validate JSON Schema, load `CapacityProfile`, enforce 360/256, require
GitHub-only policy, and verify user-owned files and hashes. Write
`preflight_report.json` for the requested spec. After environment and data
preparation, resolve runtime-derived evidence and write
`resolved_run_spec.json` plus `performance_contract.json`. The latter freezes
the capacity-profile hash, runner label, standard-runner-only flag, planner
limits, memory/disk limits, artifact policy, and hard scientific invariants.

- [x] **Step 4: Implement workflow checks**

External `uses:` values must end in `@[0-9a-f]{40}`. Local `uses:` paths must
exist. Heavy callers must use `_aurora-future-run-v3.yml`, avoid push/PR
triggers, and declare standard Ubuntu only.

- [x] **Step 5: Push and verify in GitHub**

```bash
git add infra/github_performance/preflight.py \
  tests/test_github_performance_preflight.py
git commit -m "feat: validate future GitHub workflows"
git push
gh pr checks --watch
```

---

### Task 6: Optimal Job Count and Weighted Shard Planner

**Files:**
- Create: `infra/github_performance/shard_planner.py`
- Create: `infra/github_performance/execution_planner.py`
- Create: `tests/test_github_performance_shard_planner.py`

**Interfaces:**
- Produces:
  `write_work_unit_manifest(units, path) -> WorkUnitManifest`.
- Produces:
  `weighted_lpt(manifest: WorkUnitManifest, jobs: int, output_dir: Path) -> ShardPlan`.
- Produces:
  `choose_job_count(manifest, contract, pilot, *, lpt_builder=weighted_lpt) -> JobCountDecision`.
- Produces:
  `split_matrices(shards, matrix_ceiling=256) -> MatrixSplit`.
- Produces:
  `encode_matrix_outputs(split, max_bytes=262_144) -> Mapping[str, str]`.
- Produces:
  `build_execution_plan(spec, manifest, pilot, output_dir) -> ExecutionPlan`.
- Produces files: `performance_plan.json`, `execution_plan.json`, and
  `balanced_shard_plan.json`, plus `work_units.parquet` and
  `balanced_unit_assignments.parquet`.
- Produces:
  `write_pilot_result(pilot, path) -> Path` for `performance_pilot.json`.

- [x] **Step 1: Write deterministic planner tests**

```python
def test_lpt_is_balanced_and_deterministic(tmp_path: Path) -> None:
    units = [
        make_unit(index, seconds=seconds)
        for index, seconds in enumerate([9, 8, 7, 6, 5, 4])
    ]
    first_manifest = write_work_unit_manifest(
        units, tmp_path / "first" / "work_units.parquet"
    )
    second_manifest = write_work_unit_manifest(
        reversed(units), tmp_path / "second" / "work_units.parquet"
    )
    first = weighted_lpt(first_manifest, jobs=2, output_dir=tmp_path / "a")
    second = weighted_lpt(second_manifest, jobs=2, output_dir=tmp_path / "b")
    assert first.assignment_manifest_sha256 == (
        second.assignment_manifest_sha256
    )
    assert max(s.estimated_seconds for s in first.shards) == 20


def test_full_capacity_splits_256_and_104() -> None:
    shards = tuple(make_shard(i) for i in range(360))
    split = split_matrices(shards)
    assert len(split.matrix_a) == 256
    assert len(split.matrix_b) == 104


def test_matrix_output_is_compact() -> None:
    split = split_matrices(tuple(make_shard(i) for i in range(360)))
    outputs = encode_matrix_outputs(split)
    assert sum(len(value.encode("utf-8")) for value in outputs.values()) < 262_144
    assert "unit_keys" not in "".join(outputs.values())


def test_small_workload_does_not_force_360_jobs(tmp_path: Path) -> None:
    manifest = write_work_unit_manifest(
        (make_unit(i, seconds=1) for i in range(20)),
        tmp_path / "work_units.parquet",
    )
    decision = choose_job_count(manifest, contract(), high_setup_pilot())
    assert decision.jobs < 20


def test_large_path_runs_at_most_three_exact_lpt_calls(
    tmp_path: Path,
) -> None:
    manifest = write_work_unit_manifest(
        (make_unit(i, seconds=float((i % 7) + 1)) for i in range(100)),
        tmp_path / "work_units.parquet",
    )
    calls: list[int] = []

    def counted_lpt(manifest, jobs, output_dir):
        calls.append(jobs)
        return weighted_lpt(manifest, jobs, output_dir)

    large_contract = contract().model_copy(
        update={"planner_large_unit_threshold": 10}
    )
    choose_job_count(
        manifest,
        large_contract,
        pilot(),
        lpt_builder=counted_lpt,
    )
    assert 1 <= len(calls) <= 3
```

- [x] **Step 2: Implement weighted LPT**

Write `work_units.parquet` with the fixed columns `unit_key`,
`estimated_seconds`, `payload_ref`, and `payload_sha256`, sorted by
`unit_key`. For LPT, read only those columns, sort by
`(-estimated_seconds, unit_key)`, and repeatedly assign to the shard with lowest
`(estimated_seconds, shard_id)`.

Write one small assignment Parquet member per shard and one
`balanced_unit_assignments.parquet` reconciliation catalog. Package member
references into a bounded assignment artifact chosen by the transport plan.
The matrix receives only `ShardDefinition`; if projected repeated download of a
single assignment artifact exceeds the transfer budget and no external
`SnapshotBackend` is configured, preflight blocks rather than launching an
inefficient fan-out.

Phase 1 supports assignment transport through one bounded Actions artifact or
an existing immutable `SnapshotBackend`. It calculates total repeated download
bytes before fan-out and blocks with
`ASSIGNMENT_TRANSPORT_BUDGET_EXCEEDED` when one artifact is not viable and no
backend exists. Automatic publication of multiple coarse assignment artifacts
belongs to Phase 2; Phase 1 must never claim file-selective download from a
single Actions artifact.

`encode_matrix_outputs` emits only compact descriptors and raises
`MatrixOutputTooLarge` before writing `$GITHUB_OUTPUT` when the combined UTF-8
payload reaches 262,144 bytes.

- [x] **Step 3: Implement the adaptive wall-time search**

For each feasible job count `j` from 1 through
`min(unit_count, planner_max_jobs)`, first compute a cheap lower bound using
`max(max_unit_seconds, total_estimated_seconds / j)` in place of
`slowest_shard_seconds`:

```python
predicted = (
    pilot.queue_seconds
    + pilot.setup_seconds
    + slowest_shard_seconds
    + pilot.transfer_fixed_seconds
    + pilot.transfer_per_wave_seconds * math.ceil(j / usable_parallelism)
    + pilot.checkpoint_seconds
    + pilot.merge_fixed_seconds
    + pilot.merge_per_shard_seconds * j
    + pilot.verify_seconds
)
```

When `unit_count <= 50_000`, exact LPT may be evaluated for every `j`. Above
that threshold, rank every `j` with a deterministic logarithmic cost histogram,
then run exact LPT only for the best provisional `j` and feasible neighbours
`j - 1` and `j + 1`. Choose minimum `(exact_predicted, j)` from those at most
three exact candidates. Record every analytical alternative and flag the exact
candidates.

Add a lightweight threshold test with 100 units and a contract whose
`planner_large_unit_threshold` is 10; its injected LPT spy must observe at most
three exact LPT calls. Add a skewed-cost test where the exact neighbour beats
the provisional histogram winner. This checks million-unit control flow without
allocating a million Python objects in CI.

- [x] **Step 4: Assemble and serialize one immutable execution plan**

Add this test:

```python
def test_execution_plan_is_complete_and_hash_stable(tmp_path: Path) -> None:
    run_spec = RunSpec.model_validate(minimal_valid_spec())
    work_units = tuple(make_unit(index) for index in range(20))
    first_manifest = write_work_unit_manifest(
        work_units, tmp_path / "first" / "work_units.parquet"
    )
    second_manifest = write_work_unit_manifest(
        reversed(work_units), tmp_path / "second" / "work_units.parquet"
    )
    first = build_execution_plan(
        run_spec, first_manifest, pilot(), tmp_path / "first-plan"
    )
    second = build_execution_plan(
        run_spec, second_manifest, pilot(), tmp_path / "second-plan"
    )
    assert canonical_sha256(first) == canonical_sha256(second)
    assert first.matrix_split.has_matrix_b == (
        first.job_count.selected_jobs > 256
    )
    paths = write_execution_plan(first, tmp_path)
    pilot_path = write_pilot_result(
        pilot(), tmp_path / "performance_pilot.json"
    )
    assert {path.name for path in paths} == {
        "performance_plan.json",
        "execution_plan.json",
        "balanced_shard_plan.json",
    }
    assert pilot_path.name == "performance_pilot.json"
```

`performance_plan.json` contains every job-count alternative and the selected
break-even point. `execution_plan.json` contains the selected runtime settings
and immutable hashes. `balanced_shard_plan.json` contains compact shard
descriptors and the hash of `balanced_unit_assignments.parquet`; the assignment
catalog contains every logical unit key exactly once and sorted by
`(shard_id, unit_key)`.

- [x] **Step 5: Push and verify in GitHub**

```bash
git add infra/github_performance/shard_planner.py \
  infra/github_performance/execution_planner.py \
  tests/test_github_performance_shard_planner.py
git commit -m "feat: plan balanced GitHub shards"
git push
gh pr checks --watch
```

---

### Task 7: Hierarchical Merge, Reconciliation, and Independent Verification

**Files:**
- Create: `infra/github_performance/merge_planner.py`
- Create: `infra/github_performance/verifier.py`
- Create: `tests/test_github_performance_merge.py`
- Create: `tests/test_github_performance_verifier.py`

**Interfaces:**
- Produces:
  `build_merge_plan(shards, fan_in, disk_budget_bytes) -> MergePlan`.
- Produces:
  `reconcile_attempts(expected_units, attempts: Sequence[UnitAttemptRecord]) -> ReconciliationResult`.
- Produces:
  `reconcile_attempt_files(expected_manifest, attempt_paths, output_path) -> ReconciliationResult`.
- Produces:
  `verify_final_artifact(root: Path, spec: RunSpec) -> VerificationReport`.
- Produces:
  `write_reconciliation(result, path) -> Path`.
- Produces:
  `build_requirements_traceability(spec, evidence) -> pyarrow.Table`.
- Produces:
  `write_campaign_closure(report, path) -> Path`.
- Produces:
  `write_merge_plan(plan, path) -> Path`.
- Produces:
  `write_final_artifact_manifest(root, path) -> Path`.
- Produces:
  `write_verification_report(report, path) -> Path`.
- Produces: `shard_attempt_manifest.parquet` for physical job attempts and
  `unit_attempt_manifest.parquet` for logical-unit outcomes before
  reconciliation.

- [x] **Step 1: Write reconciliation failure tests**

Cover one accepted completed attempt, identical duplicate attempts, conflicting
completed digests, missing units, unsupported units, right-censored units, and
technical failures.

```python
def test_conflicting_successful_attempts_block_merge() -> None:
    attempts = [
        completed_unit("u1", "a1", digest="1" * 64),
        completed_unit("u1", "a2", digest="2" * 64),
    ]
    with pytest.raises(ReconciliationError, match="conflicting output"):
        reconcile_attempts({"u1"}, attempts)
```

- [x] **Step 2: Implement bounded merge groups**

Group sorted shard IDs into immutable groups of at most `fan_in`. Reject a group
whose projected download plus output exceeds 80 percent of the configured disk
budget. Derive group artifact names from run ID, level, group index, and plan
hash. Serialize the immutable plan to `merge_plan.json`.

- [x] **Step 3: Implement exact reconciliation**

Require:

```text
completed + right_censored + unsupported + failed_technical = expected_units
```

Select one verified completed attempt per logical unit. Identical duplicate
attempts are recorded but not double-counted. Conflicting output hashes block.

The in-memory `reconcile_attempts` function is the reference implementation for
small tests. Production uses `reconcile_attempt_files`: every shard's
unit-attempt Parquet is sorted by `(unit_key, attempt_id)`, while physical shard
attempts are concatenated separately. The expected manifest is sorted by
`unit_key`. Perform a `heapq.merge` over bounded Arrow record-batch iterators,
write `unit_reconciliation.parquet` incrementally, and retain only the current
logical unit's attempts in memory. The production merge must not materialize all
expected keys or attempts as Python sets or Pydantic objects.

- [x] **Step 4: Implement final manifest verification**

Verify every path, byte size, SHA-256, schema version, code SHA, spec hash,
snapshot hash, policy hash, and reconciliation total. `campaign_closure.json`
can say `success` only when `partial=false` and all hard invariants pass.
Write `final_artifact_manifest.json` before verification and
`final_verification_report.json` after independently reopening every listed
file.

- [x] **Step 5: Write reconciliation, traceability, and formal closure**

Add deterministic tests:

```python
def test_reconciliation_table_accounts_for_every_unit(tmp_path: Path) -> None:
    result = reconcile_attempts(
        {"u1", "u2"},
        [
            completed_unit("u1", "a1", "1" * 64),
            unsupported_unit("u2", "NO_DATA"),
        ],
    )
    path = write_reconciliation(
        result, tmp_path / "unit_reconciliation.parquet"
    )
    table = pq.read_table(path)
    assert table.num_rows == 2
    assert set(table.column("unit_key").to_pylist()) == {"u1", "u2"}


def test_closure_cannot_claim_success_with_failed_requirement(
    tmp_path: Path,
) -> None:
    report = verification_report(
        partial=False,
        requirements_passed=False,
        locked_opened=False,
    )
    path = write_campaign_closure(report, tmp_path / "campaign_closure.json")
    payload = json.loads(path.read_text())
    assert payload["status"] == "failed"
```

`requirements_traceability.csv` uses the exact columns
`requirement_id`, `requirement_text`, `expected_value`, `observed_value`,
`evidence_path`, and `status`. It must contain rows for GitHub-only execution,
standard-runner use, matrix ceiling, locked access, validation selection,
complete reconciliation, artifact hashes, and independent verification.

`campaign_closure.json` contains `status`, `partial`, exact terminal counts,
`locked_opened`, `validation_used_for_selection`, `standard_runner_only`,
`matrix_job_ceiling_respected`, `requirements_passed`, and the SHA-256 of the
final manifest, traceability CSV, reconciliation Parquet, and verification
report.

- [x] **Step 6: Push and verify in GitHub**

```bash
git add infra/github_performance/merge_planner.py \
  infra/github_performance/verifier.py \
  tests/test_github_performance_merge.py \
  tests/test_github_performance_verifier.py
git commit -m "feat: reconcile and verify GitHub outputs"
git push
gh pr checks --watch
```

---

### Task 8: Workload Protocol, CLI, and Script Entrypoints

**Files:**
- Create: `infra/github_performance/workload.py`
- Create: `cli/cmd_github.py`
- Modify: `cli/forge.py:20-40`
- Modify: `cli/forge.py:120-170`
- Create: `scripts/aurora_github_run.py`
- Create: `scripts/aurora_github_merge.py`
- Create: `scripts/aurora_github_verify.py`
- Create: `tests/test_github_performance_workload.py`
- Create: `tests/test_github_performance_cli.py`

**Interfaces:**
- Produces:
  `load_workload("package.module:OBJECT") -> GithubWorkload`.
- Produces CLI:
  `aurora github validate|plan|run-shard|recover-plan|merge-plan|verify`.
- Consumes canonical Aurora services:
  `ProtocolPolicy`, `SnapshotStore`, `FeatureStore`, `WitnessRecorder`,
  `ExperimentTracker`, and `runtime_paths`.

- [x] **Step 1: Define and test the workload protocol**

```python
class GithubWorkload(Protocol):
    def prepare(self, spec: RunSpec, output_dir: Path) -> PreparedInputs:
        raise NotImplementedError

    def smoke(self, spec: RunSpec, prepared: PreparedInputs) -> SmokeResult:
        raise NotImplementedError

    def pilot(self, spec: RunSpec, prepared: PreparedInputs) -> PilotResult:
        raise NotImplementedError

    def enumerate_units(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        output_path: Path,
    ) -> WorkUnitManifest:
        raise NotImplementedError

    def run_shard(
        self,
        spec: RunSpec,
        shard: ShardDefinition,
        output_dir: Path,
        checkpoint: CheckpointManifest | None,
    ) -> AttemptManifest:
        raise NotImplementedError

    def merge_group(
        self, inputs: Sequence[Path], output_dir: Path
    ) -> Path:
        raise NotImplementedError
```

Reject module references outside `aurora.*` and objects that do not satisfy all
runtime-checkable protocol methods.

- [x] **Step 2: Add CLI parser tests**

Assert `build_parser().parse_args(["github", "validate", "--spec", "x.yaml"])`
binds `cmd_github_validate`, and every run or merge command calls
`require_github_execution`.

- [x] **Step 3: Implement commands and wrappers**

Wrappers import command functions; they do not duplicate contract logic.
Failures emit machine-readable JSON to stderr and non-zero exit status.

`prepare` resolves runtime directories only through `runtime_paths`, freezes or
opens inputs through `SnapshotStore`, and reuses feature identities from
`FeatureStore`. Campaign and attempt lineage is recorded through
`ExperimentTracker`; hard-gate evidence is appended through `WitnessRecorder`.
The wrappers verify
`spec.policy_hash == snapshot.policy_hash == attempt.policy_hash` before shard
execution. They must not create a second snapshot index, feature cache,
experiment registry, witness format, or OOS lock implementation.

Add integration-contract tests with fakes for those six services that assert
each canonical service is called once and that a policy-hash mismatch blocks
before the workload method runs.

- [x] **Step 4: Push and verify in GitHub**

```bash
git add infra/github_performance/workload.py cli/cmd_github.py cli/forge.py \
  scripts/aurora_github_run.py scripts/aurora_github_merge.py \
  scripts/aurora_github_verify.py \
  tests/test_github_performance_workload.py \
  tests/test_github_performance_cli.py
git commit -m "feat: expose GitHub performance CLI"
git push
gh pr checks --watch
```

---

### Task 9: Atomic Checkpoints and Selective Recovery

**Files:**
- Create: `infra/github_performance/checkpoint.py`
- Create: `infra/github_performance/recovery.py`
- Create: `scripts/aurora_github_recover.py`
- Modify: `cli/cmd_github.py`
- Create: `tests/test_github_performance_recovery.py`

**Interfaces:**
- Produces:
  `CheckpointManager.commit(shard_id, attempt_id, completed_unit_count, last_completed_unit_key, payload_path) -> CheckpointManifest`.
- Produces:
  `load_checkpoint(path: Path) -> CheckpointManifest`.
- Produces:
  `sha256_file(path: Path) -> str`.
- Produces:
  `classify_failure(payload: Mapping[str, Any]) -> FailureClass`.
- Produces:
  `build_recovery_plan(shards, attempts, checkpoints, retry_policy) -> RecoveryPlan`.
- Produces:
  `write_recovery_plan(plan, output_dir) -> Sequence[Path]`.
- Produces: `recovery_plan.json` and `checkpoint_audit.parquet`, including
  valid zero-retry outputs when no recovery is needed.

- [x] **Step 1: Write checkpoint and recovery tests**

```python
def test_checkpoint_manifest_is_published_after_payload(
    tmp_path: Path,
) -> None:
    payload = tmp_path / "rows.parquet"
    payload.write_bytes(b"valid")
    manager = CheckpointManager(tmp_path / "checkpoint")
    manifest = manager.commit("s001", "a001", 12, "u0012", payload)
    loaded = load_checkpoint(
        tmp_path / "checkpoint" / "checkpoint_manifest.json"
    )
    assert loaded == manifest
    assert sha256_file(Path(loaded.payload_path)) == loaded.payload_sha256


def test_transient_failure_retries_with_new_attempt_id() -> None:
    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", "a001", "GITHUB_5XX")],
        [],
        {"github_5xx": 3},
    )
    decision = plan.decisions[0]
    assert decision.action == "retry"
    assert decision.next_attempt_id != decision.prior_attempt_id


@pytest.mark.parametrize(
    ("reason", "expected_action"),
    [
        ("SCHEMA_MISMATCH", "do_not_retry"),
        ("POLICY_VIOLATION", "do_not_retry"),
        ("DETERMINISTIC_CODE_ERROR", "do_not_retry"),
        ("OUT_OF_MEMORY", "replan"),
        ("DISK_EXHAUSTED", "replan"),
    ],
)
def test_non_transient_failures_are_not_retried_identically(
    reason: str,
    expected_action: str,
) -> None:
    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", "a001", reason)],
        [],
        {"runner_lost": 2},
    )
    assert plan.decisions[0].action == expected_action


def test_retry_budget_exhaustion_stops_retry() -> None:
    attempts = [
        failed_attempt("s001", "a001", "GITHUB_5XX"),
        failed_attempt("s001", "a002", "GITHUB_5XX"),
    ]
    plan = build_recovery_plan(
        [make_shard(1)], attempts, [], {"github_5xx": 1}
    )
    assert plan.decisions[0].action == "do_not_retry"
    assert plan.decisions[0].reason_code == "RETRY_BUDGET_EXHAUSTED"


def test_corrupt_checkpoint_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "rows.parquet"
    payload.write_bytes(b"valid")
    manager = CheckpointManager(tmp_path / "checkpoint")
    manager.commit("s001", "a001", 12, "u0012", payload)
    payload.write_bytes(b"tampered")
    with pytest.raises(CheckpointIntegrityError, match="sha256"):
        load_checkpoint(tmp_path / "checkpoint" / "checkpoint_manifest.json")


def test_recovery_matrices_respect_github_limits() -> None:
    shards = [make_shard(index) for index in range(360)]
    attempts = [
        failed_attempt(shard.shard_id, f"a{index:03d}", "RUNNER_LOST")
        for index, shard in enumerate(shards)
    ]
    plan = build_recovery_plan(shards, attempts, [], {"runner_lost": 2})
    assert len(plan.retry_matrix_a) == 256
    assert len(plan.retry_matrix_b) == 104
    assert plan.has_retry_matrix_a is True
    assert plan.has_retry_matrix_b is True


def test_verified_checkpoint_is_selected_for_resume() -> None:
    checkpoint = CheckpointManifest(
        shard_id="s001",
        attempt_id="a001",
        artifact_name="run-checkpoint-s001-a001",
        completed_unit_count=12,
        last_completed_unit_key="u0012",
        payload_path="rows.parquet",
        payload_sha256="9" * 64,
        created_at=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )
    plan = build_recovery_plan(
        [make_shard(1)],
        [failed_attempt("s001", "a001", "RUNNER_LOST")],
        [checkpoint],
        {"runner_lost": 2},
    )
    assert plan.decisions[0].checkpoint_artifact == (
        "run-checkpoint-s001-a001"
    )
```

- [x] **Step 2: Implement atomic checkpoint publication**

Write payload and manifest to temporary sibling paths, flush and `fsync` each
file, atomically `Path.replace` the payload first, and publish
`checkpoint_manifest.json` last. `load_checkpoint` verifies file existence,
SHA-256, shard identity, attempt identity, and monotonic completed-unit count.
A corrupt or regressing checkpoint is ignored and recorded as technical
evidence; it is never used to skip work.

- [x] **Step 3: Implement failure classification and retry budgets**

Define:

```python
class FailureClass(StrEnum):
    TRANSIENT_NETWORK = "transient_network"
    GITHUB_5XX = "github_5xx"
    PROVIDER_429 = "provider_429"
    ARTIFACT_UPLOAD = "artifact_upload"
    RUNNER_LOST = "runner_lost"
    DETERMINISTIC_INPUT = "deterministic_input"
    SCHEMA = "schema"
    POLICY = "policy"
    CODE = "code"
    OUT_OF_MEMORY = "out_of_memory"
    DISK_EXHAUSTED = "disk_exhausted"
```

Only the first five classes may retry. Apply the exact per-class limits from
the run spec. OOM and disk exhaustion emit `replan`; deterministic classes emit
`do_not_retry`. A retry preserves `shard_id` and logical unit keys, receives a
new UUIDv4 `attempt_id`, and resumes only from a verified checkpoint.

- [x] **Step 4: Write compact recovery outputs**

Write `recovery_plan.json`, `retry_matrix_a.json`, `retry_matrix_b.json`, and
`checkpoint_audit.parquet`. Empty matrices are represented by
`has_retry_matrix_* = false` and are never submitted. Matrix descriptors
contain only shard, attempt, checkpoint-artifact, and assignment references.
Reject combined GitHub outputs at 262,144 bytes.

- [x] **Step 5: Expose recovery through the CLI**

`aurora github recover-plan` and `scripts/aurora_github_recover.py` load
attempt/checkpoint manifests, apply the spec retry budget, write machine-readable
outputs, and call `require_github_execution` before any recovery operation.

- [x] **Step 6: Push and verify in GitHub**

```bash
git add infra/github_performance/checkpoint.py \
  infra/github_performance/recovery.py \
  scripts/aurora_github_recover.py cli/cmd_github.py \
  tests/test_github_performance_recovery.py
git commit -m "feat: preserve and recover GitHub shards"
git push
gh pr checks --watch
```

---

### Task 10: Pinned Runtime Setup Composite Action

**Files:**
- Create: `.github/actions/aurora-runtime-setup/action.yml`
- Create: `tests/test_github_performance_workflows.py`

**Interfaces:**
- Inputs: `python-version`, `extras`, `cache-key`, `cache-mode`.
- Outputs: `cpu-count`, `memory-mb`, `free-disk-mb`, `image-os`,
  `image-version`, `cache-hit`, and `environment-sha256`.
- Produces: `environment_manifest.json` with runner, Python, dependency,
  cache-key, installed-wheel, and thread-limit hashes.

- [ ] **Step 1: Write static action tests**

Load the action YAML and assert:

- composite action;
- setup-python SHA equals the lock file;
- restore-only is default;
- numerical thread variables equal detected CPU count;
- `persist-credentials` is not enabled;
- no larger-runner label appears.

- [ ] **Step 2: Implement restore-only setup**

The action:

1. records runner metadata;
2. calls pinned setup-python;
3. restores one dependency cache key;
4. installs the exact requested Aurora extra;
5. exports bounded thread variables;
6. hashes the dependency and runtime manifest;
7. writes runtime outputs.

`cache-mode` accepts only `restore-only` or `writer`, and defaults to
`restore-only`. Only the dedicated `prepare_environment` job uses `writer`;
every other job uses `restore-only`. The cache key contains the dependency-lock
hash, Python version, runner OS, architecture, and Aurora build-input hash.

- [ ] **Step 3: Push and verify in GitHub**

```bash
git add .github/actions/aurora-runtime-setup/action.yml \
  tests/test_github_performance_workflows.py
git commit -m "feat: add pinned Aurora runtime action"
git push
gh pr checks --watch
```

---

### Task 11: Reusable Future-Run Workflow

**Files:**
- Create: `.github/workflows/_aurora-future-run-v3.yml`
- Modify: `tests/test_github_performance_workflows.py`

**Interfaces:**
- `workflow_call` inputs:
  `spec_path`, `workload`, `run_label`, `retention_days`.
- Produces artifact:
  `<run_label>-results`.

- [ ] **Step 1: Add structural workflow tests**

Assert the workflow contains:

```text
validate → prepare_environment
validate → prepare_data
prepare_environment + prepare_data → freeze_contract
freeze_contract → smoke → pilot → plan
plan → fanout_a
plan → fanout_b
fanout_a + fanout_b → recovery_plan
recovery_plan → retry_a
recovery_plan → retry_b
fanout_a + fanout_b + retry_a + retry_b → merge_partials
merge_partials → final_merge → verify → publish
```

Assert both matrices use `fail-fast: false`; A is at most 256, B is at most 104;
all salvage and merge jobs use `if: always()`; all runners are
`ubuntu-24.04`.

- [ ] **Step 2: Implement compact dynamic matrices**

`plan` writes only compact shard descriptors to `$GITHUB_OUTPUT`:

```json
{"include":[{"shard_id":"s000","attempt_id":"a000","merge_group":"g00","assignment_artifact":"run-assignment-bundle-000","assignment_member":"assignments/s000.parquet","assignment_sha256":"8888888888888888888888888888888888888888888888888888888888888888"}]}
```

The complete plan is uploaded as an immutable artifact. `fanout_b` has a job
condition based on `has_matrix_b` so no empty matrix is evaluated.

`prepare_environment` and `prepare_data` start together after `validate`.
`prepare_environment` is the sole cache writer and uploads an immutable
`environment_manifest.json`. `freeze_contract` downloads the environment and
data manifests, resolves every runtime-derived hash, writes
`resolved_run_spec.json` and `performance_contract.json`, and uploads both as
one immutable contract artifact. `smoke`, `pilot`, planning, fan-out, recovery,
merge, and verification download that artifact, verify its SHA-256, and never
reload the requested YAML as their scientific contract. They use restore-only
setup and verify the environment hash before executing.

Every checkout uses the pinned checkout action, `persist-credentials: false`,
and the exact `identity.code_sha` from the validated spec. `validate` compares
that SHA with the triggering commit and blocks `CODE_SHA_MISMATCH` before any
preparation job.

- [ ] **Step 3: Implement unique shard artifacts**

Name artifacts:

```text
<run_label>-shard-<merge_group>-<shard_id>-<attempt_id>
```

Use pinned upload-artifact, `compression-level: 0` for Parquet, and
`if-no-files-found: error`.

- [ ] **Step 4: Integrate salvage and selective retry**

Every fan-out job runs an `if: always()` salvage step that uploads its valid
checkpoint, attempt manifest, and technical diagnostics under a unique
attempt-specific artifact name. `recovery_plan` always runs after both initial
matrices, downloads only manifests, classifies failures, and emits retry
matrices through `aurora github recover-plan`.

`retry_a` and `retry_b` use `fail-fast: false`, run only when their corresponding
boolean output is true, verify any checkpoint hash before resuming, and preserve
the original shard and unit identities. Merge waits for initial and retry jobs
with `if: always()`.

- [ ] **Step 5: Implement one bounded partial-merge level**

Each partial merge downloads only artifacts matching its merge-group prefix.
The final merge downloads partial artifacts, not every original shard. The
verifier always runs and publishes diagnostics even on partial failure.

- [ ] **Step 6: Push and verify in GitHub**

```bash
git add .github/workflows/_aurora-future-run-v3.yml \
  tests/test_github_performance_workflows.py
git commit -m "feat: add reusable future-run workflow"
git push
gh pr checks --watch
```

---

### Task 12: Legacy Allowlist and Mandatory Future-Workflow Guard

**Files:**
- Create: `config/legacy_workflow_allowlist.json`
- Create: `.github/workflows/github-performance-policy.yml`
- Modify: `infra/github_performance/preflight.py`
- Modify: `tests/test_github_performance_preflight.py`
- Modify: `tests/test_github_performance_workflows.py`

**Interfaces:**
- Produces:
  `classify_workflow(path, allowlist) -> "legacy" | "future" | "modified_legacy"`.

- [ ] **Step 1: Freeze adoption-time workflow hashes**

Generate one entry per tracked `.github/workflows/*.yml` at parent commit
`0ca928bd1`, containing repository-relative path and SHA-256. Exclude files
introduced by this branch.

- [ ] **Step 2: Test grandfathering**

Assert unchanged legacy files pass, a one-byte change becomes
`modified_legacy`, and a new heavy workflow must call the framework.

- [ ] **Step 3: Add lightweight policy workflow**

On pull requests touching `.github/**`, `scripts/**`, `research/**`, or
`infra/github_performance/**`, run only the static validator. It does not launch
research jobs.

- [ ] **Step 4: Push and verify in GitHub**

```bash
git add config/legacy_workflow_allowlist.json \
  .github/workflows/github-performance-policy.yml \
  infra/github_performance/preflight.py \
  tests/test_github_performance_preflight.py \
  tests/test_github_performance_workflows.py
git commit -m "feat: enforce framework for future workflows"
git push
gh pr checks --watch
```

---

### Task 13: Deterministic Real Aurora Reference Workload

**Files:**
- Create: `infra/github_performance/reference_workload.py`
- Create: `config/github_performance_reference.yaml`
- Create: `.github/workflows/github-performance-reference.yml`
- Create: `tests/test_github_performance_reference.py`

**Interfaces:**
- Produces: `WORKLOAD: GithubWorkload`.
- Uses: `aurora.core.engine`, `aurora.core.metrics`, and deterministic generated
  non-locked return series. This exercises the real Aurora engine and metrics
  path; only the compact input fixture is generated to remove vendor drift.

- [ ] **Step 1: Write deterministic reference tests**

Generate returns with NumPy `default_rng(20260725)`, 4,032 train observations,
2,520 validation observations, and no dates after `2020-12-31`. Assert the same
unit key always produces the same output hash.

- [ ] **Step 2: Implement the reference workload**

Create 1,024 logical parameter units over moving-average windows, causal lag one,
and fixed costs. Train determines the unit parameters; validation is report-only.
The workload emits no accepted-strategy claim, never reads locked data, and
does not replace the engine or metrics with test doubles.

- [ ] **Step 3: Add a four-shard PR smoke**

Extend `github-performance-ci.yml` with a GitHub-only four-shard smoke that uses
the same workload protocol without invoking the 360-job workflow. Verify exact
reconciliation and `locked_opened=false`.

- [ ] **Step 4: Add the manual full caller**

`github-performance-reference.yml` contains only `workflow_dispatch`, least
permissions (`contents: read`, `actions: read`), and one call to
`_aurora-future-run-v3.yml`.

- [ ] **Step 5: Push and verify in GitHub**

```bash
git add infra/github_performance/reference_workload.py \
  config/github_performance_reference.yaml \
  .github/workflows/github-performance-reference.yml \
  .github/workflows/github-performance-ci.yml \
  tests/test_github_performance_reference.py
git commit -m "feat: add GitHub performance reference workload"
git push
gh pr checks --watch
```

---

### Task 14: Equivalent Baseline, Benchmark, and Phase-1 Closure

**Files:**
- Create: `.github/workflows/github-performance-benchmark.yml`
- Create: `infra/github_performance/github_api.py`
- Create: `scripts/collect_github_run_timeline.py`
- Create: `scripts/compare_github_performance_runs.py`
- Create: `tests/test_github_performance_github_api.py`
- Create: `tests/test_github_performance_benchmark.py`
- Modify: `.github/workflows/_aurora-future-run-v3.yml`
- Modify: `tests/test_github_performance_workflows.py`
- Modify: `docs/GITHUB_RUN_MASTER_STANDARD.md`
- Modify: `README.md`

**Interfaces:**
- Produces:
  `compare_runs(reference_dir: Path, optimized_dir: Path) -> BenchmarkReport`.
- Produces:
  `fetch_run_jobs(api_url, repository, run_id, token, opener) -> Sequence[Mapping[str, Any]]`.
- Produces:
  `build_parallelism_timeline(jobs) -> pyarrow.Table`.
- Produces:
  `github_performance_phase1_closure.json`.
- Produces:
  `build_bottleneck_report(reference, optimized, timeline) -> Mapping[str, Any]`.
- Produces:
  `write_performance_final(report, path) -> Path`.

- [ ] **Step 1: Write paginated GitHub timeline tests**

Mock two GitHub API pages. The first returns 100 jobs and a `Link` header with
`rel="next"`; the second returns 3 jobs. Assert all 103 jobs are preserved,
the authorization header is sent but never serialized, and UTC timestamps
produce deterministic concurrency intervals.

```python
def test_timeline_uses_real_job_intervals() -> None:
    jobs = [
        github_job("a", created="00:00:00", started="00:00:10",
                   completed="00:00:40"),
        github_job("b", created="00:00:05", started="00:00:20",
                   completed="00:00:30"),
    ]
    table = build_parallelism_timeline(jobs)
    assert table.column("observed_parallelism").to_pylist() == [1, 2, 1]
    assert table.column("queue_seconds").to_pylist()[0] == 10.0
```

The collector reports `queue_seconds` from `started_at - created_at` and
`runner_bootstrap_proxy_seconds` from the first Aurora step minus job start.
It must not label the proxy as measured GitHub provisioning.

- [ ] **Step 2: Implement read-only timeline collection**

Use `urllib.request` with `GITHUB_API_URL`, `GITHUB_REPOSITORY`,
`GITHUB_RUN_ID`, and `GITHUB_TOKEN`. Paginate until there is no `next` link.
Write `parallelism_timeline.csv` and `github_jobs_timeline.parquet`. Never write
the token, response headers, actor email, or arbitrary step logs.

Add an `if: always()` `collect_timeline` job after verification in the reusable
workflow. Give only that job `actions: read` and `contents: read`; all other
jobs retain `contents: read`. Timeline failure marks performance telemetry
incomplete but cannot rewrite scientific outputs.

Change the final dependency chain to
`verify -> collect_timeline -> publish`. Exclude the still-running collector
and not-yet-started publisher from concurrency calculations. Publish includes
the timeline files alongside verification and scientific artifacts.

- [ ] **Step 3: Write equivalence and benchmark tests**

Require identical unit keys and scientific output hashes before comparing
performance. Report cold/warm setup, queue, wall time, billable minutes,
straggler ratio, and predicted-versus-observed error. Write
`bottleneck_report.json` with the measured critical-path component and
`performance_final.json` with requested/observed/peak parallelism, useful
compute fraction, setup fraction, transfer fraction, retry waste, merge path,
and total wall and billable time.

- [ ] **Step 4: Add equivalent baseline mode**

The baseline uses equal-count shards, repeated standard setup, flat merge, and
the same job-count ceiling selected for the optimized run. It uses the exact same
code SHA, spec, input hash, units, seeds, runner label, and scientific output
contract.

- [ ] **Step 5: Add the manual benchmark workflow**

Run baseline and optimized modes, compare only after output equivalence, and
declare `contents: read` plus `actions: read`, then upload:

```text
preflight_report.json
performance_contract.json
performance_pilot.json
performance_plan.json
environment_manifest.json
resolved_run_spec.json
execution_plan.json
balanced_shard_plan.json
work_units.parquet
balanced_unit_assignments.parquet
runtime_breakdown.parquet
parallelism_timeline.csv
github_jobs_timeline.parquet
bottleneck_report.json
recovery_plan.json
checkpoint_audit.parquet
shard_attempt_manifest.parquet
unit_attempt_manifest.parquet
merge_plan.json
performance_final.json
unit_reconciliation.parquet
final_artifact_manifest.json
final_verification_report.json
requirements_traceability.csv
campaign_closure.json
github_performance_phase1_closure.json
```

- [ ] **Step 6: Push and wait for all PR checks**

```bash
git add .github/workflows/github-performance-benchmark.yml \
  .github/workflows/_aurora-future-run-v3.yml \
  infra/github_performance/github_api.py \
  scripts/collect_github_run_timeline.py \
  scripts/compare_github_performance_runs.py \
  tests/test_github_performance_github_api.py \
  tests/test_github_performance_benchmark.py \
  tests/test_github_performance_workflows.py \
  docs/GITHUB_RUN_MASTER_STANDARD.md README.md
git commit -m "feat: close GitHub performance phase one"
git push
gh pr checks --watch
```

- [ ] **Step 7: Mark the PR ready for review**

```bash
gh pr ready
gh pr view --json url,headRefName,baseRefName,statusCheckRollup
```

Do not merge while checks are pending.

- [ ] **Step 8: Run the manual benchmark after the framework exists on `main`**

After the reviewed PR is merged:

```bash
gh workflow run github-performance-benchmark.yml \
  --repo trading-optimizer-lab-org/aurora \
  --ref main
```

Inspect the final artifact and require:

```text
locked_opened=false
validation_used_for_selection=false
partial=false
scientific_outputs_equal=true
matrix_job_ceiling_respected=true
larger_runner_used=false
```

Phase 1 is complete only after the closure artifact records those values and the
measured bottleneck report is available for the Phase-2 planner design.

# SP500 Continuous DEHB Worker Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents and worktree forks are prohibited for this project.

**Goal:** Replace rigid DEHB waves with a PostgreSQL-backed continuous pool of 360 four-vCPU GitHub runners that globally deduplicates physical SP500 evaluations while preserving each island's official-DEHB trajectory.

**Architecture:** A single leased coordinator owns 720 independent DEHB state machines and publishes deterministic four-slot batches into a durable PostgreSQL queue. Three workflow shards keep 360 GitHub jobs alive; every job runs four single-threaded executor processes that claim unique leases, while a snapshot reducer and supervisor operate without stopping search.

**Tech Stack:** Python 3.11, DEHB 0.1.2, ConfigSpace 1.2.2, PostgreSQL 16, psycopg 3, pytest, GitHub Actions.

## Global Constraints

- Authoritative worktree: `C:\Users\HP\AURORA_sp500_search_method_benchmark_short`.
- Branch: `codex/sp500-search-method-benchmark-short`.
- Use no subagents and create no worktree forks.
- Search, backtests, optimisation, campaign work, mass import and scientific smokes run only in GitHub Actions.
- Training data ends in 2010; validation 2011-2020 and locked 2021+ must never be mounted, opened or read.
- Preserve `config/sp500_megarun_dehb_campaign_v1.json`, official DEHB, 240 lanes, three replicas, seeds, fidelities, objectives, robustness gates and stopping rules.
- Run exactly 360 GitHub worker sessions with four single-threaded scientific executor slots each; database permits cap execution at 1,440 slots.
- A proposal/configuration/fidelity/seed identity can have one accepted result and at most one active physical lease.
- A cache conflict, scientific identity change, partial input or boundary violation halts fail-closed.
- The cancelled v1 runs are historical evidence only; they must never auto-continue.

---

## File map

- `infra/sp500_megarun/dehb_continuous_models.py`: immutable v2 identities, proposals, leases, results and hash rules.
- `infra/sp500_megarun/dehb_continuous_schema.py`: PostgreSQL schema and migration receipt.
- `infra/sp500_megarun/dehb_continuous_store.py`: store protocol plus psycopg implementation and transactions.
- `infra/sp500_megarun/dehb_continuous_island.py`: serializable official-DEHB island adapter and canonical batch order.
- `infra/sp500_megarun/dehb_continuous_coordinator.py`: leader loop, fair scheduling, checkpointing and result fan-out.
- `infra/sp500_megarun/dehb_continuous_worker.py`: four-slot worker runtime, heartbeats, spooling and position-key dedupe.
- `infra/sp500_megarun/dehb_continuous_importer.py`: verified v1 artifact import.
- `infra/sp500_megarun/dehb_continuous_reducer.py`: immutable sequence-cutoff snapshots using existing reconciliation.
- `infra/sp500_megarun/dehb_continuous_supervisor.py`: health audit and idempotent pool-generation decisions.
- `scripts/*sp500_dehb_continuous*.py`: GitHub-only command entry points.
- `.github/workflows/sp500-dehb-continuous-*-v2.yml`: bootstrap, coordinator, workers, reducer and supervisor.
- `tests/test_sp500_megarun_dehb_continuous_*.py`: unit, transaction, conformance, failure and workflow tests.

### Task 1: Immutable v2 scientific identities

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_models.py`
- Test: `tests/test_sp500_megarun_dehb_continuous_models.py`

**Interfaces:**
- Consumes: `_canonical_bytes`, `_json_value`, `scientific_result_sha256` from `dehb_evaluation_cache.py`.
- Produces: `EvaluationCacheKeyV2.build`, `StrategyEvaluationKeyV1.build`, `EvaluationProposalV2`, `EvaluationLeaseV1`, `EvaluationResultV2`.

- [x] **Step 1: Add failing key and boundary tests**

```python
def test_v2_key_is_stable_and_seed_sensitive():
    first = build_key(configuration={"b": np.int64(2), "a": 1}, robustness_identity="seed:7")
    same = build_key(configuration={"a": 1, "b": 2}, robustness_identity="seed:7")
    other_seed = build_key(configuration={"a": 1, "b": 2}, robustness_identity="seed:8")
    assert first.sha256 == same.sha256
    assert first.sha256 != other_seed.sha256

def test_result_rejects_opened_partitions():
    with pytest.raises(ContinuousModelError, match="CONTINUOUS_RESULT_OPENED_VALIDATION"):
        EvaluationResultV2.build(key=build_key(), result=result(validation_opened=True))
```

- [x] **Step 2: Run the tests and confirm the missing module failure**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_models.py -q`

- [x] **Step 3: Implement frozen dataclasses and domain-separated hashes**

```python
@dataclass(frozen=True)
class EvaluationCacheKeyV2:
    sha256: str
    payload: Mapping[str, Any]

    @classmethod
    def build(cls, *, evaluator_sha256: str, numeric_profile_sha256: str,
              train_manifest_sha256: str, train_spy_sha256: str,
              campaign_contract_sha256: str, lane_id: str,
              configuration: Mapping[str, Any], fidelity: int,
              fidelity_recipe_sha256: str, robustness_identity: str,
              execution_contract_version: int = 2,
              return_interval_contract_version: int = 1) -> "EvaluationCacheKeyV2":
        payload = canonical_v2_payload(
            evaluator_sha256=evaluator_sha256,
            numeric_profile_sha256=numeric_profile_sha256,
            train_manifest_sha256=train_manifest_sha256,
            train_spy_sha256=train_spy_sha256,
            campaign_contract_sha256=campaign_contract_sha256,
            lane_id=lane_id,
            configuration=configuration,
            fidelity=fidelity,
            fidelity_recipe_sha256=fidelity_recipe_sha256,
            robustness_identity=robustness_identity,
            execution_contract_version=execution_contract_version,
            return_interval_contract_version=return_interval_contract_version,
        )
        digest = hashlib.sha256(b"SP500-DEHB-EVALUATION-V2\0" + _canonical_bytes(payload)).hexdigest()
        return cls(sha256=digest, payload=payload)
```

The implementation validates every SHA-256, lane `F001`-`F240`, positive integral fidelity, non-empty robustness identity and exact `validation_opened=False`/`locked_opened=False` result flags.

- [x] **Step 4: Run focused tests and existing cache tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_models.py tests/test_sp500_megarun_dehb_evaluation_cache.py -q`

- [x] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_models.py tests/test_sp500_megarun_dehb_continuous_models.py
git commit -m "feat: define continuous DEHB identities"
```

### Task 2: PostgreSQL schema and least-privilege contract

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_schema.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_schema.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: model schema versions from Task 1.
- Produces: `SCHEMA_VERSION = 1`, `schema_statements() -> Sequence[str]`, `apply_schema(connection) -> SchemaReceiptV1`.

- [x] **Step 1: Add failing schema-shape tests**

```python
def test_schema_has_unique_scientific_work_and_slot_caps():
    sql = "\n".join(schema_statements())
    assert "UNIQUE (campaign_id, cache_key_sha256)" in sql
    assert "UNIQUE (campaign_id, strategy_key_sha256)" in sql
    assert "worker_slot_leases" in sql
    assert "validation_opened boolean NOT NULL CHECK (validation_opened = false)" in sql
```

- [x] **Step 2: Confirm failure, then add psycopg dependency**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_schema.py -q`

Add `"psycopg[binary,pool]>=3.2,<4"` to project dependencies so GitHub workers share one tested driver and connection pool.

- [x] **Step 3: Implement idempotent DDL**

Create all tables listed in the design, append-only `audit_events`, `BIGINT` sequences, foreign keys, result immutability triggers, 360 session permits, 1,440 slot permits, lease expiries, partial unique indexes for active leases, and database roles `sp500_dehb_coordinator`, `sp500_dehb_worker`, `sp500_dehb_reducer`.

- [x] **Step 4: Run schema tests and package metadata tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_schema.py tests/test_audit_fixes.py tests/test_lint_config.py -q`

- [x] **Step 5: Commit**

```powershell
git add pyproject.toml infra/sp500_megarun/dehb_continuous_schema.py tests/test_sp500_megarun_dehb_continuous_schema.py
git commit -m "feat: add continuous DEHB PostgreSQL schema"
```

### Task 3: Transactional store and global deduplication

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_store.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_store.py`
- Create: `tests/integration/test_sp500_megarun_dehb_continuous_postgres.py`

**Interfaces:**
- Produces: `ContinuousCampaignStore` protocol and `PostgresContinuousCampaignStore` with `register_proposal`, `claim_worker_session`, `claim_evaluation`, `heartbeat`, `publish_position_key`, `complete_evaluation`, `release_lease`, `fetch_completed_batches`, `append_checkpoint`, and `snapshot_cutoff`.

- [x] **Step 1: Add an in-memory contract harness and collision tests**

```python
def test_500_concurrent_proposals_create_one_physical_work_item(store):
    rows = run_concurrently(500, lambda: store.register_proposal(proposal()))
    assert len({row.evaluation_id for row in rows}) == 1
    assert store.count_ready_work_items() == 1

def test_conflicting_completion_halts_campaign(store):
    lease = store.claim_evaluation(slot())
    store.complete_evaluation(lease, result(hash_value="a" * 64))
    with pytest.raises(ResultConflictError):
        store.complete_evaluation(lease, result(hash_value="b" * 64))
    assert store.campaign_state() == "halted_conflict"
```

- [x] **Step 2: Confirm contract tests fail**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_store.py -q`

- [x] **Step 3: Implement serializable transactions**

Use PostgreSQL `INSERT ON CONFLICT` and `SELECT FOR UPDATE SKIP LOCKED`, opaque random lease tokens, database timestamps, advisory coordinator lock, atomic audit sequence allocation and idempotent same-hash completion. Never interpolate identifiers or payload values into SQL.

- [ ] **Step 4: Run PostgreSQL 16 concurrency tests in GitHub-compatible Docker when available**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_store.py tests/integration/test_sp500_megarun_dehb_continuous_postgres.py -q`

- [x] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_store.py tests/test_sp500_megarun_dehb_continuous_store.py tests/integration/test_sp500_megarun_dehb_continuous_postgres.py
git commit -m "feat: add atomic continuous DEHB store"
```

### Task 4: Official-DEHB state-machine adapter

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_island.py`
- Modify: `infra/sp500_megarun/dehb_island_runner.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_island.py`

**Interfaces:**
- Produces: `ContinuousIslandState.restore`, `ask_batch() -> IslandBatchV1`, `tell_batch(batch, results) -> IslandAdvanceV1`, `checkpoint_bytes()`.
- Reuses: `_ask_valid_batch`, `_validated_result`, `_resume_safe_dehb_class` without changing v1 results.

- [x] **Step 1: Freeze v1 trajectory fixtures**

```python
def test_out_of_order_arrival_keeps_v1_trajectory(frozen_optimizer):
    baseline = run_v1_three_batches(frozen_optimizer.copy(), deterministic_results())
    state = ContinuousIslandState.from_optimizer(frozen_optimizer.copy())
    for batch in range(3):
        asked = state.ask_batch()
        state.tell_batch(asked, reversed_results_for(asked))
    assert state.trajectory_receipt() == baseline.trajectory_receipt()
```

- [x] **Step 2: Run and confirm the adapter is absent**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_island.py -q`

- [x] **Step 3: Extract reusable four-job ask/tell primitives and implement the adapter**

The adapter asks four valid jobs, assigns stable slots 0-3, buffers arbitrary arrival order, calls official DEHB `tell` in slot order, stores consumed result hashes and creates a hash-chain checkpoint only at a complete four-job boundary.

- [x] **Step 4: Run conformance plus all existing island tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_island.py tests/test_sp500_megarun_dehb_island_runner.py tests/test_sp500_megarun_dehb_plan_resume.py -q`

- [x] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_island.py infra/sp500_megarun/dehb_island_runner.py tests/test_sp500_megarun_dehb_continuous_island.py
git commit -m "feat: preserve DEHB islands in continuous batches"
```

### Task 5: Leader coordinator and fair queue replenishment

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_coordinator.py`
- Create: `scripts/run_sp500_dehb_continuous_coordinator.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_coordinator.py`

**Interfaces:**
- Produces: `ContinuousCampaignCoordinator.run_once() -> CoordinatorCycleV1`, `run_forever(stop_event)`, weighted-deficit scheduler and leader handoff.

- [ ] **Step 1: Add failing fairness, restart and cache fan-out tests**

```python
def test_240_lanes_all_advance_without_global_barrier(coordinator):
    coordinator.run_until(lambda state: state.completed_batches >= 480)
    assert set(coordinator.advanced_lanes()) == {f"F{i:03d}" for i in range(1, 241)}
    assert coordinator.global_barrier_count == 0

def test_second_leader_cannot_mutate(coordinator_pair):
    first, second = coordinator_pair
    assert first.acquire_leadership()
    assert not second.acquire_leadership()
```

- [ ] **Step 2: Confirm failures**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_coordinator.py -q`

- [ ] **Step 3: Implement one-cycle idempotency and queue watermarks**

Restore runnable islands, deliver cache hits before creating work, register at most one unresolved batch per island, replenish toward 2,880 ready unique evaluations, checkpoint after each complete batch and stop proposal creation only in `freezing`, `frozen` or fail-closed states.

- [ ] **Step 4: Run coordinator, store and conformance tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_coordinator.py tests/test_sp500_megarun_dehb_continuous_store.py tests/test_sp500_megarun_dehb_continuous_island.py -q`

- [ ] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_coordinator.py scripts/run_sp500_dehb_continuous_coordinator.py tests/test_sp500_megarun_dehb_continuous_coordinator.py
git commit -m "feat: coordinate continuous DEHB islands"
```

### Task 6: Four-vCPU worker and two-stage strategy dedupe

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_worker.py`
- Modify: `infra/sp500_megarun/dehb_worker.py`
- Create: `scripts/run_sp500_dehb_continuous_worker.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_worker.py`

**Interfaces:**
- Produces: `ContinuousWorkerRuntime.run()`, `run_executor_slot(slot_index)`, `build_strategy_key`, `EmergencySpoolV1`.
- Reuses: `candidate_fingerprints`, `feature_frame_to_decisions`, `evaluate_lane_candidate`.

- [ ] **Step 1: Add failing batch, position collision and lease-loss tests**

```python
def test_four_slots_never_receive_same_key(worker_store):
    runtime = ContinuousWorkerRuntime(store=worker_store, executor_slots=4)
    runtime.run_until_completed(8)
    assert worker_store.maximum_concurrent_lease_count_per_key() == 1

def test_same_positions_backtest_once(worker_store, evaluator_spy):
    worker_store.enqueue(two_configs_with_same_positions())
    ContinuousWorkerRuntime(worker_store, executor_slots=4).run_until_completed(2)
    assert evaluator_spy.expensive_backtest_calls == 1
    assert worker_store.completed_subscriber_count() == 2
```

- [ ] **Step 2: Confirm failures**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_worker.py -q`

- [ ] **Step 3: Split position generation from expensive evaluation and implement runtime**

Each spawned process claims independently, verifies the numeric environment and train hashes, generates positions, atomically publishes `StrategyEvaluationKeyV1`, waits on an existing owner or evaluates as owner, heartbeats during long work, and submits only hash-bound train-only results.

- [ ] **Step 4: Run worker, numeric-runtime and objective tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_worker.py tests/test_sp500_megarun_dehb_worker.py tests/test_sp500_megarun_dehb_numeric_runtime.py tests/test_sp500_megarun_dehb_objective.py -q`

- [ ] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_worker.py infra/sp500_megarun/dehb_worker.py scripts/run_sp500_dehb_continuous_worker.py tests/test_sp500_megarun_dehb_continuous_worker.py
git commit -m "feat: run four-slot deduplicated DEHB workers"
```

### Task 7: Verified rigid-wave importer

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_importer.py`
- Create: `scripts/import_sp500_dehb_rigid_wave_artifacts.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_importer.py`

**Interfaces:**
- Produces: `RigidWaveArtifactImporterV1.verify_bundle(path)`, `import_bundle(path, source_run_id) -> ImportReceiptV1`.

- [ ] **Step 1: Add failing import, conflict and boundary tests**

```python
def test_import_is_idempotent_and_preserves_provenance(importer, clean_bundle):
    first = importer.import_bundle(clean_bundle, source_run_id=31799845515)
    second = importer.import_bundle(clean_bundle, source_run_id=31799845515)
    assert first.inserted_evaluations > 0
    assert second.inserted_evaluations == 0
    assert second.existing_same_hash == first.inserted_evaluations

def test_import_rejects_any_opened_partition(importer, bundle_with_validation_flag):
    with pytest.raises(ImportContractError, match="IMPORT_OPENED_VALIDATION"):
        importer.verify_bundle(bundle_with_validation_flag)
```

- [ ] **Step 2: Confirm failures, then implement manifest and ledger verification**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_importer.py -q`

- [ ] **Step 3: Import through the same unique-key transactions as live work**

Accept only runs `31799845515` and completed worker bundles from `31811823543` when launch, evaluator, numeric, train and campaign hashes match. Treat `31817248374` as denied by default. Emit a signed-content import receipt with inserted, reused, rejected and conflict counts.

- [ ] **Step 4: Run importer and existing bundle verification tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_importer.py tests/test_sp500_megarun_dehb_evaluation_cache.py tests/test_sp500_megarun_dehb_global_merge.py -q`

- [ ] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_importer.py scripts/import_sp500_dehb_rigid_wave_artifacts.py tests/test_sp500_megarun_dehb_continuous_importer.py
git commit -m "feat: import verified rigid-wave evaluations"
```

### Task 8: Continuous reducer and freeze transition

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_reducer.py`
- Create: `scripts/reduce_sp500_dehb_continuous_snapshot.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_reducer.py`

**Interfaces:**
- Produces: `ContinuousReducer.build_snapshot(cutoff_sequence)`, `attempt_train_freeze(snapshot_id)` and `ContinuousReducerSnapshotV1`.

- [ ] **Step 1: Add failing sequence-cutoff and v1-equivalence tests**

```python
def test_snapshot_ignores_results_after_cutoff(reducer, seeded_store):
    cutoff = seeded_store.audit_sequence()
    expected = reducer.build_snapshot(cutoff)
    seeded_store.add_result(candidate_after_cutoff())
    assert reducer.build_snapshot(cutoff).sha256 == expected.sha256

def test_no_finalist_keeps_searching(reducer):
    snapshot = reducer.build_snapshot(reducer.store.audit_sequence())
    assert reducer.attempt_train_freeze(snapshot.id).state == "searching"
```

- [ ] **Step 2: Confirm failures, then adapt the existing global merge to row streams**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_reducer.py -q`

- [ ] **Step 3: Implement immutable snapshots and atomic freeze cutoff**

Trigger at 10,000 new physical evaluations or five minutes with new data, reuse existing multiplicity/60-gate/consensus logic, seal a winner only from train-only rows and keep both later partitions false in snapshot and campaign state.

- [ ] **Step 4: Run continuous and existing reducer suites**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_reducer.py tests/test_sp500_megarun_dehb_global_reconciliation.py tests/test_sp500_megarun_dehb_global_merge.py tests/test_sp500_megarun_dehb_finalist_robustness.py -q`

- [ ] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_reducer.py scripts/reduce_sp500_dehb_continuous_snapshot.py tests/test_sp500_megarun_dehb_continuous_reducer.py
git commit -m "feat: reduce continuous DEHB snapshots"
```

### Task 9: Bootstrap, audit and supervisor commands

**Files:**
- Create: `infra/sp500_megarun/dehb_continuous_supervisor.py`
- Create: `scripts/init_sp500_dehb_continuous_campaign.py`
- Create: `scripts/audit_sp500_dehb_continuous_campaign.py`
- Create: `tests/test_sp500_megarun_dehb_continuous_supervisor.py`

**Interfaces:**
- Produces: `bootstrap_campaign`, `audit_campaign`, `PoolSupervisor.decide -> PoolDecisionV1`.

- [ ] **Step 1: Add failing preflight and generation-idempotency tests**

```python
def test_bootstrap_requires_tls_and_pool_capacity(preflight):
    with pytest.raises(BootstrapError, match="DATABASE_TLS_REQUIRED"):
        preflight("postgresql://plain")

def test_same_generation_dispatches_once(supervisor):
    first = supervisor.reserve_generation("pool-0007")
    second = supervisor.reserve_generation("pool-0007")
    assert first.dispatch is True
    assert second.dispatch is False
```

- [ ] **Step 2: Confirm failures, then implement fail-closed operational checks**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_supervisor.py -q`

- [ ] **Step 3: Implement exact bootstrap receipt and health decision**

Verify TLS, schema, roles, advisory lock, 400 pooler clients, 360 session permits, 1,440 slot permits, queue depth, leases, audit chain, scientific hashes and closed partitions. Supervisor decisions are `healthy`, `dispatch_next_generation`, `recover_coordinator`, `halt_conflict` or `halt_boundary`.

- [ ] **Step 4: Run supervisor tests and ruff on new modules**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_continuous_supervisor.py -q`

Run: `C:/Python314/python.exe -m ruff check infra/sp500_megarun/dehb_continuous_*.py scripts/*sp500_dehb_continuous*.py`

- [ ] **Step 5: Commit**

```powershell
git add infra/sp500_megarun/dehb_continuous_supervisor.py scripts/init_sp500_dehb_continuous_campaign.py scripts/audit_sp500_dehb_continuous_campaign.py tests/test_sp500_megarun_dehb_continuous_supervisor.py
git commit -m "feat: supervise continuous DEHB campaign"
```

### Task 10: GitHub workflows and policy tests

**Files:**
- Create: `.github/actions/sp500-dehb-continuous-worker/action.yml`
- Create: `.github/workflows/sp500-dehb-continuous-bootstrap-v2.yml`
- Create: `.github/workflows/sp500-dehb-continuous-coordinator-v2.yml`
- Create: `.github/workflows/sp500-dehb-continuous-worker-pool-v2.yml`
- Create: `.github/workflows/sp500-dehb-continuous-reducer-v2.yml`
- Create: `.github/workflows/sp500-dehb-continuous-supervisor-v2.yml`
- Modify: `tests/test_sp500_megarun_dehb_workflows.py`

**Interfaces:**
- Inputs shared by every workflow: `commit_sha`, `campaign_id`, `runtime_input_run_id`, `technical_evidence_run_id`, `launch_contract_sha256`.
- Secret: `SP500_DEHB_COORDINATOR_DATABASE_URL`.

- [ ] **Step 1: Add failing workflow policy assertions**

```python
def test_continuous_pool_is_360_four_vcpu_jobs_without_v1_continue():
    workflow = load_workflow("sp500-dehb-continuous-worker-pool-v2.yml")
    assert shard_max_parallel(workflow) == [120, 120, 120]
    assert total_matrix_entries(workflow) == 720
    assert "run_sp500_dehb_continuous_worker.py" in workflow_text(workflow)
    assert "sp500-dehb-mega-controller-v1.yml" not in workflow_text(workflow)
```

- [ ] **Step 2: Confirm failures**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_workflows.py -q`

- [ ] **Step 3: Implement pinned, least-privilege workflows**

All checkouts use the frozen commit; dependencies and action SHAs are pinned; workers receive only the worker DSN, train artifact and launch receipt; coordinator/reducer use separate database roles; concurrency groups and pool generation keys prevent duplicate campaigns.

- [ ] **Step 4: Run workflow policy and YAML parsing tests**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_workflows.py tests/test_github_performance_workflows.py -q`

- [ ] **Step 5: Commit**

```powershell
git add .github/actions/sp500-dehb-continuous-worker .github/workflows/sp500-dehb-continuous-*-v2.yml tests/test_sp500_megarun_dehb_workflows.py
git commit -m "ci: add continuous DEHB worker pool"
```

### Task 11: Full verification and GitHub synthetic smoke

**Files:**
- Create: `.github/workflows/sp500-dehb-continuous-smoke-v2.yml`
- Create: `scripts/smoke_sp500_dehb_continuous.py`
- Modify: `docs/superpowers/specs/2026-08-14-sp500-continuous-dehb-worker-pool-design.md`

- [ ] **Step 1: Add a PostgreSQL service-container smoke**

The smoke creates 720 synthetic islands, 50,000 proposals with forced exact and position collisions, 360 logical worker sessions, 1,440 executor slots, coordinator restart, worker death, lease expiry, out-of-order completion, reducer cutoff and partition-denial probes.

- [ ] **Step 2: Run the complete focused local suite**

Run: `C:/Python314/python.exe -m pytest tests/test_sp500_megarun_dehb_* tests/integration/test_sp500_megarun_dehb_continuous_postgres.py -q`

- [ ] **Step 3: Run lint and diff validation**

Run: `C:/Python314/python.exe -m ruff check infra/sp500_megarun/dehb_continuous_*.py scripts/*sp500_dehb_continuous*.py tests/test_sp500_megarun_dehb_continuous_*.py`

Run: `git diff --check`

- [ ] **Step 4: Push the frozen revision and dispatch the synthetic smoke**

```powershell
git push origin codex/sp500-search-method-benchmark-short
gh workflow run sp500-dehb-continuous-smoke-v2.yml --ref codex/sp500-search-method-benchmark-short -f commit_sha=$(git rev-parse HEAD)
```

- [ ] **Step 5: Inspect every failed job and record exact evidence**

Run: `$smokeRunId = gh run list --workflow sp500-dehb-continuous-smoke-v2.yml --branch codex/sp500-search-method-benchmark-short --limit 1 --json databaseId | ConvertFrom-Json | Select-Object -ExpandProperty databaseId; gh run view $smokeRunId --json status,conclusion,jobs,headSha,url`

Acceptance: all tests pass, zero conflicts, one physical execution per scientific key, 360 sessions admitted, 1,440 slots admitted, trajectory receipt identical, validation and locked unopened.

- [ ] **Step 6: Commit verification receipts**

```powershell
git add docs/superpowers/specs/2026-08-14-sp500-continuous-dehb-worker-pool-design.md
git commit -m "docs: record continuous DEHB verification"
```

### Task 12: Production bootstrap, import and launch

**Files:**
- No code change unless a verified smoke exposes a defect.

- [ ] **Step 1: Verify required repository secret without printing it**

Run: `gh secret list | Select-String -Pattern '^SP500_DEHB_COORDINATOR_DATABASE_URL\s'`

- [ ] **Step 2: Dispatch bootstrap at the exact accepted commit**

Run: `$launch = Get-Content -Raw outputs/launch/launch_contract.json | ConvertFrom-Json; gh workflow run sp500-dehb-continuous-bootstrap-v2.yml --ref codex/sp500-search-method-benchmark-short -f commit_sha=$(git rev-parse HEAD) -f runtime_input_run_id=$launch.runtime_input_run_id -f technical_evidence_run_id=$launch.technical_evidence_run_id`

- [ ] **Step 3: Import only verified train-only artifacts**

Dispatch importer inputs `31799845515,31811823543`; assert the import receipt denies `31817248374`, reports no result conflicts and leaves validation/locked flags false.

- [ ] **Step 4: Start coordinator, reducer, supervisor and the first worker generation**

Use the campaign ID and launch hash emitted by bootstrap. Verify all workflow `headSha` values equal the accepted commit before workers can claim scientific work.

- [ ] **Step 5: Verify live acceptance before leaving the campaign unattended**

Require coordinator leader acquired, queue populated, 355-360 active GitHub jobs after provisioning, four executor slots per admitted job, no duplicate active leases, no hash conflicts, reducer snapshots advancing and both later-data flags false.

- [ ] **Step 6: Replace the obsolete heartbeat with a v2-only monitor**

The monitor follows the campaign ID and exact commit, reports only changes/failures/decisions, rejects partial GitHub pagination, never dispatches v1 and never reads validation or locked data.

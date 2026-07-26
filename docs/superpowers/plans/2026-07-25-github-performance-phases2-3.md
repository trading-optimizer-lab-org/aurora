# GitHub Performance Phases 2 and 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Aurora's universal GitHub performance planner, durable recovery, independent verification, reproducible runtime, representative benchmarks, and profile-gated native acceleration without changing scientific results.

**Architecture:** Extend the phase-1 immutable contracts with runtime evidence, a content-addressed DAG, historical performance profiles, durable campaign state, iterative recovery, arbitrary merge levels, and a frozen wheelhouse. Keep workload science behind a stable adapter, keep operational adaptation blind to scientific outputs, and reject every optimization that is not equivalent and faster in an end-to-end GitHub benchmark.

**Tech Stack:** Python 3.12, Pydantic 2, PyArrow, NumPy, NetworkX, GitHub Actions on `ubuntu-24.04`, pinned GitHub actions, JSON Schema, Parquet, pytest.

## Global Constraints

- All tests, smokes, benchmarks, and research execution run in GitHub Actions.
- Only standard `ubuntu-24.04` runners are allowed.
- No matrix may exceed 256 jobs; combined standard concurrency may not exceed 360 jobs.
- Locked data remains closed and `locked_rows_accessed` must equal `0`.
- Validation is report-only and must never influence selection.
- Operational adaptation cannot inspect candidates, metrics, validation results, or locked data.
- Scientific unit keys, seeds, inputs, outputs, and metric contracts remain unchanged.
- A slower or non-equivalent optimization automatically falls back to reference execution.
- No native kernel is kept without at least 10% measured runner-time share and 5% projected whole-workflow benefit.

---

### Task 1: Runtime Policy Evidence and Mandatory Audits

**Files:**
- Create: `infra/github_performance/audits.py`
- Modify: `infra/github_performance/contracts.py`
- Modify: `infra/github_performance/workload.py`
- Modify: `infra/github_performance/merge_runtime.py`
- Modify: `infra/github_performance/verifier.py`
- Test: `tests/test_github_performance_audits.py`
- Test: `tests/test_github_performance_verifier.py`

**Interfaces:**
- Produces: `RuntimeAccessLedger`, `DataAudit`, `PolicyAudit`, `RuntimeAudit`, and `ProvenanceRecord`.
- Produces: `write_required_audits(root, spec, access_records, environment) -> tuple[Path, ...]`.
- Consumes: runtime access records emitted by every workload shard.

- [x] **Step 1: Write failing audit tests**

Assert that every access record includes source, partition, minimum date, maximum date, row count, split, purpose (`selection` or `report`), and locked flag. Assert that any locked row, any selection read from validation, or any date after the declared split fails closed.

- [x] **Step 2: Run the focused GitHub test job and record RED**

Dispatch `github-performance-ci.yml` with the audit test selector. Require failure because `RuntimeAccessLedger` and the four mandatory audit files do not exist.

- [x] **Step 3: Implement runtime-ledger and audit writers**

Use immutable Pydantic models. Aggregate rows without trusting requested policy values. Write:

```text
data_audit.json
policy_audit.json
runtime_audit.json
provenance.json
```

The data audit derives `locked_rows_accessed`, maximum accessed dates, and split/purpose counts from records emitted during execution.

- [x] **Step 4: Enforce audits in final verification**

Require all four files in the final manifest. Verification reads their contents, checks hashes, and fails on missing runtime evidence even when the requested spec declares safe values.

- [x] **Step 5: Run GitHub tests and commit**

Require audit and verifier tests to pass, then commit:

```text
feat: verify runtime policy evidence
```

---

### Task 2: Independent Metric Recalculation

**Files:**
- Create: `infra/github_performance/metric_verifier.py`
- Modify: `infra/github_performance/verifier.py`
- Modify: `config/github_performance_reference_metrics.json`
- Test: `tests/test_github_performance_metric_verifier.py`

**Interfaces:**
- Produces: `recompute_metrics(returns, trades, contract) -> Mapping[str, float | int | None]`.
- Produces: `verify_metric_table(source, recomputed, tolerances) -> MetricEquivalenceReport`.
- Produces final artifact: `independent_metric_verification.json`.

- [x] **Step 1: Write failing differential tests**

Cover CAGR, annualized return, volatility, Sharpe, Sortino, maximum drawdown, Calmar, profit factor, win rate, trade count, average return, and total return. Include empty inputs, one return, NaN policy, signed zero, and a deliberate mismatch.

- [x] **Step 2: Record RED in GitHub**

Run only metric-verifier tests and require failure because the independent implementation is absent.

- [x] **Step 3: Implement independent formulas**

Use arrays read from final canonical return/trade outputs, never metric values produced by the workload. Apply explicit annualization, risk-free rate, NaN, infinity, and tolerance rules from the metric contract.

- [x] **Step 4: Add verifier gate**

Set `independent_metrics_equal=true` only when every required metric matches. Include per-field expected, observed, absolute error, relative error, and tolerance in the report.

- [x] **Step 5: Run GitHub tests and commit**

Commit:

```text
feat: independently verify scientific metrics
```

Evidence: RED run `30167836306`; GREEN run `30168194017`;
implementation commits `851cd7e80` and `72565f1b3`. Full reusable-workflow
closure run `30168253488` completed successfully: `1024/1024` units,
`2048` metric-input records, `30720` independently recomputed fields,
zero mismatches, `partial=false`, `locked_opened=false`, and
`validation_used_for_selection=false`.

---

### Task 3: Reproducible Wheelhouse and Environment Manifest

**Files:**
- Create: `requirements/github-performance.in`
- Create: `requirements/github-performance.lock`
- Create: `infra/github_performance/environment.py`
- Create: `scripts/build_github_performance_wheelhouse.py`
- Modify: `.github/actions/aurora-runtime-setup/action.yml`
- Modify: `.github/workflows/_aurora-future-run-v3.yml`
- Test: `tests/test_github_performance_environment.py`
- Test: `tests/test_github_performance_workflows.py`

**Interfaces:**
- Produces: `dependency_lock_manifest.json`, `wheelhouse_manifest.json`, and one Aurora wheel.
- Consumes: exact transitive pins from `requirements/github-performance.lock`.
- Fan-out setup accepts `wheelhouse-path` and installs with `--no-index --require-hashes`.

- [x] **Step 1: Write failing environment tests**

Require exact transitive pins, hashes for every requirement, wheel hashes, Python/OS/architecture compatibility, and rejection of missing or extra wheels.

- [x] **Step 2: Generate the lock in GitHub**

Run a dedicated lock job on `ubuntu-24.04`, Python 3.12, using pinned `pip-tools`. Download the artifact, review it, and commit the generated lock.

- [x] **Step 3: Build one immutable wheelhouse**

`prepare_environment` downloads every locked wheel once, builds Aurora once, hashes all files, uploads one immutable wheelhouse artifact, and records build provenance.

- [x] **Step 4: Add the fan-out fast path**

Fan-out jobs restore the exact wheelhouse, verify its manifest, and install without dependency resolution or wheel building. Remove per-job pip upgrade and network resolution.

- [x] **Step 5: Benchmark setup cold and warm**

Publish setup distributions and reject the fast path if environment hashes differ or wall time is slower.

- [x] **Step 6: Run GitHub tests and commit**

Commit:

```text
feat: freeze and reuse GitHub wheelhouse
```

Evidence: environment RED run `30168711668`; lock-generation run
`30168825373`; setup-benchmark RED run `30169832258`; GREEN contract and
four-shard smoke run `30170050477`. Full reusable-workflow closure run
`30169599148` completed `1024/1024` units with zero metric mismatches and one
immutable `225233720`-byte wheelhouse. Equivalent cold/warm benchmark run
`30170101585` installed the same package and environment hashes in all eight
samples. The wheelhouse reduced cold setup from `20.0185s` to `12.7623s`
(`1.5686x`) and warm median setup from `15.5765s` to `12.4928s` (`1.2468x`);
`dependency_environment_reproducible=true`, `fast_path_selected=true`, and
all failure-code lists were empty.

---

### Task 4: Stable Workload Adapter and Content-Addressed DAG

**Files:**
- Create: `infra/github_performance/dag.py`
- Create: `infra/github_performance/adapter.py`
- Modify: `infra/github_performance/contracts.py`
- Modify: `infra/github_performance/workload.py`
- Test: `tests/test_github_performance_dag.py`
- Test: `tests/test_github_performance_adapter.py`

**Interfaces:**
- Workload methods: `describe_contract`, `prepare_shared_inputs`, `enumerate_units`, `estimate_unit_cost`, `execute_unit`, `verify_unit`, `merge_outputs`.
- Produces: `ComputationNode`, `ComputationGraph`, `SharedIntermediateManifest`.
- Stable node identity: SHA-256 of operation, implementation version, exact inputs, parameters, policy hash, and snapshot hash.

- [x] **Step 1: Write failing graph tests**

Build the chain `data -> features -> signals -> positions -> returns -> metrics -> robustness`. Assert topological order, cycle rejection, stable hashes, exact deduplication, preservation of original candidate identities, and no approximate candidate elimination.

- [x] **Step 2: Record RED in GitHub**

Require failure because adapter and DAG contracts do not exist.

- [x] **Step 3: Implement adapter compatibility**

Support phase-1 workloads through a compatibility adapter while exposing the phase-2 interface to new workloads.

- [x] **Step 4: Implement content-addressed shared nodes**

Write intermediates atomically under their content hash and verify schema, size, and hash before reuse. Reuse only exact matches.

- [x] **Step 5: Run GitHub tests and commit**

Commit:

```text
feat: plan content-addressed workload DAGs
```

Evidence: RED run `30170818898` failed on the intentionally absent adapter
and DAG modules. GREEN run `30171198090` used commit `809875ded` and completed
successfully on `ubuntu-24.04`: the dependency lock reproduced exactly, all
`166` GitHub-performance contract tests passed, and all `4` real-engine shard
smokes passed. The stable adapter preserves original candidate identities and
supports phase-1 workloads; the DAG uses exact content hashes, rejects cycles
and missing dependencies, and verifies schema identity, byte size, and SHA-256
before reusing an atomically published shared intermediate.

---

### Task 5: Performance Profiles and Engine Selection

**Files:**
- Create: `infra/github_performance/profiles.py`
- Create: `infra/github_performance/engines.py`
- Modify: `infra/github_performance/execution_planner.py`
- Modify: `infra/github_performance/contracts.py`
- Test: `tests/test_github_performance_profiles.py`
- Test: `tests/test_github_performance_engines.py`

**Interfaces:**
- Produces: `PerformanceProfileKey` over code SHA, workflow hash, spec hash, snapshot hash, dependency lock hash, and runner contract.
- Produces: `select_fastest_equivalent_engine(trials) -> EngineDecision`.
- Produces: `performance_profile.json` and `engine_trials.json`.

- [x] **Step 1: Write failing profile tests**

Require exact key matching, expiry outside confidence bands, cold/warm samples, measurement uncertainty, and mandatory pilot on mismatch.

- [x] **Step 2: Write failing engine tests**

Compare Python reference, NumPy, Numba, Arrow, DuckDB when installed, processes, and threads. Reject non-equivalent or slower trials; include compilation and warm-up in end-to-end time.

- [x] **Step 3: Implement profile persistence**

Profiles are immutable artifacts and never selected by candidate quality.

- [x] **Step 4: Implement engine decision and fallback**

Choose only an equivalent faster engine. Missing optional engines become capability outcomes. Preserve reference fallback.

- [x] **Step 5: Run GitHub tests and commit**

Commit:

```text
feat: select engines from equivalent profiles
```

Evidence: RED run `30171377698` failed only because the profile, engine, and
planner-resolution contracts were intentionally absent. GREEN run
`30171537001` used commit `06d86abb2` and completed successfully on
`ubuntu-24.04`: the dependency lock reproduced exactly, all `185` contract
tests passed, and all `4` real-engine shard smokes passed. Profiles require an
exact six-field compatibility key, preserve separate cold/warm samples with
measurement uncertainty, expire on out-of-band observations, and require a
fresh pilot on mismatch. Engine selection preserves Python as fallback and
rejects unavailable, scientifically different, slower, or uncertainty-overlap
alternatives; compilation and warm-up are mandatory end-to-end evidence.

---

### Task 6: Deadlines, Budgets, Resource Monitor, and Safe Stops

**Files:**
- Create: `infra/github_performance/guardrails.py`
- Modify: `infra/github_performance/telemetry.py`
- Modify: `infra/github_performance/execution_planner.py`
- Modify: `cli/cmd_github.py`
- Test: `tests/test_github_performance_guardrails.py`
- Test: `tests/test_github_performance_telemetry.py`

**Interfaces:**
- Produces: `ResourceMonitor` with periodic child-aware samples.
- Produces: `BudgetLedger`, `DeadlineDecision`, and `SafeStopReason`.
- Produces artifacts: `resource_samples.parquet`, `budget_audit.json`, and `deadline_audit.json`.

- [x] **Step 1: Write failing guardrail tests**

Cover child CPU/RSS aggregation, disk and I/O samples, budget projection, deadline projection, graceful checkpoint request, and fail-closed behavior when evidence is missing.

- [x] **Step 2: Record RED in GitHub**

Require failure because periodic monitoring and enforced budgets are absent.

- [x] **Step 3: Implement periodic monitor**

Sample the process tree at a bounded interval, publish maximum and p95 resources, and request a checkpoint before memory, disk, deadline, or budget exhaustion.

- [x] **Step 4: Enforce planner and runtime decisions**

Planner refuses a route projected beyond hard budget/deadline. Runtime stops only at durable unit boundaries and records the exact reason.

- [x] **Step 5: Run GitHub tests and commit**

Commit:

```text
feat: enforce GitHub runtime guardrails
```

**Evidence:** RED run `30171721269` used commit `893c2be30` and failed
only on the deliberately absent guardrail CLI, module, and process-tree
telemetry contracts. The first GREEN run `30172204050` proved the exact
dependency lock and all four real-engine shards, while exposing one strict
floating-point audit mismatch (`40.400000000000006` versus `40.4`). Commit
`998344847` replaced binary monetary multiplication with decimal arithmetic.
Final GREEN run `30172263777` completed successfully with the reproducible
dependency lock, `199` contract tests, and all four real-engine shards.
`ResourceMonitor` now records child-aware RSS, peak memory, CPU, disk, read and
write bytes, I/O wait, load, maximums, and p95. Planner routes fail closed on
deadline, billable-minute, or cost evidence violations. Runtime pressure is
latched and can request a stop only at a declared durable unit boundary.

---

### Task 7: Durable Campaign State, Iterative Recovery, Replan, and Merge-Only

**Files:**
- Create: `infra/github_performance/campaign.py`
- Modify: `infra/github_performance/recovery.py`
- Modify: `cli/cmd_github.py`
- Modify: `.github/workflows/_aurora-future-run-v3.yml`
- Test: `tests/test_github_performance_campaign.py`
- Test: `tests/test_github_performance_recovery.py`

**Interfaces:**
- Produces immutable `campaign_state_vNNNNNN.json` and verified `campaign_state_latest.json`.
- Produces CLI commands: `campaign-update`, `recovery-loop`, `replan`, and `merge-only`.
- Replan may change only operational partitioning and preserves logical unit keys.

- [x] **Step 1: Write failing state-machine tests**

Cover version monotonicity, pointer hash verification, resume after interruption, repeated transient retries, OOM/disk replan, no identical deterministic retry, and merge-only reuse.

- [x] **Step 2: Record RED in GitHub**

Require failure because only one recovery pass exists.

- [x] **Step 3: Implement durable campaign state**

Every wave, recovery, replan, merge, and verification transition writes a new immutable state version.

- [x] **Step 4: Implement bounded iterative recovery**

Loop until all units are terminal, a hard policy failure occurs, or retry budgets are exhausted. Reuse verified checkpoints and source artifacts.

- [x] **Step 5: Implement replan and merge-only paths**

Replan preserves completed units and changes only operational fields. Merge-only reads verified state and repeats no shard computation.

- [x] **Step 6: Run GitHub failure simulations and commit**

Commit:

```text
feat: make GitHub campaigns durably recoverable
```

**Evidence:** RED run `30192834219` required immutable state preservation,
terminal unit evidence, and universal replan/merge-only workflows. GREEN runs
`30193486553`, `30194068395`, and `30194974558` passed the reproducible
dependency lock, `225` focused contracts, and all four real-engine smoke
shards. The complete reference run `30193528008` produced `1024/1024`
scientific units with zero metric mismatches. Merge-only run `30193838870`
scheduled no compute, reused only its verified source artifact, and reproduced
the exact scientific output SHA-256
`da6714280f5b1ec1925e5bc454d24ca6257d4647964b3af469fe6750453a415c`.

Failure-fixture run `30194113698` preserved `512` completed units and bound the
remaining `512` to real `OUT_OF_MEMORY` and `DISK_EXHAUSTED` terminal
evidence. The first reusable calls, `30194398332` and `30194526692`, correctly
failed before compute because GitHub passed the dispatch number as a string;
their workflow annotations reported `Unexpected value '4'`. Commit
`d313e11e4` added explicit numeric conversion and restored the source
wheelhouse by its own verified scientific SHA instead of coupling recovery to
the newer orchestration SHA.

Final replan run `30195022749` completed in `31` seconds. Its source run,
contract, and wheelhouse all verified SHA
`68605d726f37bb8c03425d1a5f355e2f411dbb03`, while the orchestration fix ran
at `d313e11e4ceaecc3c98fbba997a5ab0327034554`. It changed only
`requested_parallelism` from two to four, preserved the scientific contract,
logical-unit manifest, and completed-unit evidence hashes, and produced four
new shards of `128` units. Independent inspection proved that the `512`
replanned keys equal the `512` pending keys exactly, overlap the `512`
completed keys by zero, contain no duplicates, and omit no pending unit.
Therefore `campaign_state_recoverable=true`,
`selective_recovery_verified=true`, `replan_verified=true`, and
`merge_only_verified=true` have direct GitHub evidence.

---

### Task 8: Arbitrary Multi-Level Merge and Partitioned Transport

**Files:**
- Modify: `infra/github_performance/contracts.py`
- Modify: `infra/github_performance/merge_planner.py`
- Modify: `infra/github_performance/merge_runtime.py`
- Modify: `.github/workflows/_aurora-future-run-v3.yml`
- Test: `tests/test_github_performance_merge.py`
- Test: `tests/test_github_performance_workflows.py`

**Interfaces:**
- Produces one matrix descriptor per merge level and group.
- Produces partitioned artifacts under configured byte/file bounds.
- Final merge downloads only direct children from the preceding level.

- [x] **Step 1: Write failing merge-tree tests**

Generate 7200 fake shard descriptors and require enough levels to respect fan-in, disk, artifact count, and matrix limits. Assert no source row is lost or duplicated.

- [x] **Step 2: Record RED in GitHub**

Require failure because the workflow executes only one bounded partial level.

- [x] **Step 3: Implement arbitrary merge levels**

Build and execute each level from the immutable merge plan. Verify every child hash before reduction.

- [x] **Step 4: Implement partitioned large transport**

Split oversized outputs deterministically by logical key and byte target; record all parts in the manifest.

- [x] **Step 5: Run GitHub tests and commit**

Commit:

```text
feat: execute bounded multi-level merges
```

Evidence:

- RED `30195541316` required a bounded 7,200-shard hierarchy,
  deterministic partition transport, and direct-child workflow reduction.
- Runtime RED `30196850821` reached the real root and exposed both an invalid
  Arrow projection argument and an unnecessarily expensive binary-search
  partition writer.
- GREEN CI `30197132684` verifies the real engine through two merge levels,
  verifies every child and transport hash, and proves that a corrupted child
  blocks its parent. The optimized strict partition writer reduced that smoke
  from 4m32s to 1m16s including runner setup.
- Workflow GREEN `30197253702` executed 60 source shards, two level-zero
  reductions, one level-one root, a root-only final download, and independent
  verification. It completed 1,024 of 1,024 units with zero technical
  failures, `merge_root_level=1`, `merge_levels_executed=2`,
  `multi_level_merge_verified=true`, `locked_rows_accessed=0`, and maximum
  accessed date `2020-12-31`.
- The 1,024 canonical per-unit scientific hashes and every scientific column
  are identical to the prior full reference run. The physical Parquet hash
  differs only because `source_attempt_id` is operational provenance; Task 9
  must expose a separate canonical scientific-content hash so a physical
  artifact hash is never mistaken for scientific equivalence.

---

### Task 9: Mandatory Outputs and Complete Traceability

**Files:**
- Modify: `infra/github_performance/verifier.py`
- Modify: `infra/github_performance/merge_runtime.py`
- Modify: `infra/github_performance/benchmark.py`
- Modify: `.github/workflows/_aurora-future-run-v3.yml`
- Test: `tests/test_github_performance_verifier.py`
- Test: `tests/test_github_performance_workflows.py`

**Interfaces:**
- Final artifact includes every phase-1, phase-2, and applicable phase-3 output.
- Produces a requirement row for every explicit acceptance criterion.

- [ ] **Step 1: Write failing completeness tests**

Delete each mandatory output one at a time and require verification failure. Require telemetry to be sealed before final manifest creation.

- [ ] **Step 2: Expand traceability**

Add evidence for deadlines, budget, runtime locked rows, validation separation, independent metrics, dependency environment, recovery, replan, merge-only, multi-level merge, standard runners, matrix limits, equivalence, and required output completeness.

- [ ] **Step 3: Move telemetry before artifact seal**

The final manifest is created only after runtime and GitHub timeline telemetry are present. Missing telemetry keeps scientific outputs but fails campaign completion.

- [ ] **Step 4: Run GitHub tests and commit**

Commit:

```text
feat: require complete GitHub campaign evidence
```

---

### Task 10: Three Representative Workload Families

**Files:**
- Create: `infra/github_performance/workloads/candidate_sweep.py`
- Create: `infra/github_performance/workloads/event_study.py`
- Create: `infra/github_performance/workloads/robustness.py`
- Create: `infra/github_performance/workloads/__init__.py`
- Create: `config/github_performance_candidate_sweep.yaml`
- Create: `config/github_performance_event_study.yaml`
- Create: `config/github_performance_robustness.yaml`
- Create: `.github/workflows/github-performance-validation.yml`
- Test: `tests/test_github_performance_workload_families.py`

**Interfaces:**
- Candidate sweep exercises CPU-parallel parameter evaluation.
- Event study exercises partitioned I/O and aggregation.
- Robustness exercises bootstrap/permutation compute and expensive reduction.

- [ ] **Step 1: Write deterministic workload tests**

Require stable unit keys and hashes, no dates after `2020-12-31`, runtime access evidence, and independent metric inputs.

- [ ] **Step 2: Implement frozen compact workloads**

Use real Aurora engine/metrics paths where applicable and deterministic frozen inputs. Do not use mocks for scientific output.

- [ ] **Step 3: Add validation workflow**

Run cold/warm, baseline/optimized, matrix A/A+B, transient failure, checkpoint, replan, merge-only, multi-level merge, and high-capacity scenarios.

- [ ] **Step 4: Run GitHub tests and commit**

Commit:

```text
feat: add representative performance workloads
```

---

### Task 11: Profile-Guided Native Qualification and Fallback

**Files:**
- Create: `infra/github_performance/native.py`
- Create: `scripts/profile_github_hot_paths.py`
- Modify: `infra/github_performance/engines.py`
- Test: `tests/test_github_performance_native.py`

**Interfaces:**
- Produces: `hot_path_profile.json`, `native_candidate_report.json`, `native_equivalence_report.json`, `native_benchmark.json`, `native_wheel_manifest.json`, and `native_fallback_audit.json`.
- Produces `NativeQualificationDecision` with measured runner share and projected whole-workflow benefit.

- [ ] **Step 1: Write failing qualification tests**

Reject paths below 10% runner-time share, below 5% projected end-to-end gain, impure paths, mutable external state, or missing Python reference.

- [ ] **Step 2: Implement qualification and ordered optimization evidence**

Record algorithm, shared-computation, vectorization, NumPy/Arrow/DuckDB, Numba, then Rust evidence. Rust remains unavailable unless all earlier stages fail to meet the measured opportunity.

- [ ] **Step 3: Implement capability and fallback audit**

A missing or failing native capability selects the Python reference and records why. Scientific output hashes remain identical.

- [ ] **Step 4: Run differential GitHub tests and commit**

Commit:

```text
feat: gate native acceleration on GitHub profiles
```

---

### Task 12: End-to-End GitHub Validation and Closure

**Files:**
- Modify: `.github/workflows/github-performance-benchmark.yml`
- Modify: `.github/workflows/github-performance-validation.yml`
- Modify: `docs/GITHUB_RUN_MASTER_STANDARD.md`
- Modify: `C:\Users\HP\Desktop\PLANTILLA_MAESTRA_RUN_GITHUB_AURORA.md`
- Create: `docs/superpowers/specs/2026-07-25-github-performance-phase2-3-closure.md`

**Interfaces:**
- Produces one closure artifact per workload plus a combined closure.
- Produces uncertainty intervals, critical path, cost, speedup, and fallback decisions.

- [ ] **Step 1: Run all static and focused tests in GitHub**

Require all performance-system tests to pass on Python 3.12 and standard `ubuntu-24.04`.

- [ ] **Step 2: Run three small end-to-end smokes**

Verify contracts, runtime audits, independent metrics, checkpoint, recovery, merge, and required outputs before scale.

- [ ] **Step 3: Run representative baseline and optimized campaigns**

For each workload run cold and warm sizes, fixed full capacity, and adaptive plan. Publish real GitHub timelines and billable minutes.

- [ ] **Step 4: Inject and recover failures**

Demonstrate selective retry, OOM/disk operational replan, merge-only, and multi-level merge without repeating completed logical units.

- [ ] **Step 5: Verify full acceptance matrix**

Require:

```text
locked_opened=false
locked_rows_accessed=0
validation_used_for_selection=false
partial=false
required_outputs_complete=true
independent_metrics_equal=true
dependency_environment_reproducible=true
deadline_respected=true
budget_respected=true
campaign_state_recoverable=true
selective_recovery_verified=true
replan_verified=true
merge_only_verified=true
multi_level_merge_verified=true
scientific_outputs_equal=true
matrix_job_ceiling_respected=true
standard_runner_only=true
larger_runner_used=false
```

- [ ] **Step 6: Require material speedup**

At least one representative optimized workload must be materially faster than its equivalent baseline after uncertainty. Any slower optimization is rejected and the reference route remains selected.

- [ ] **Step 7: Synchronize documentation and close**

Update the canonical standard, copy it to the Desktop master template, write the closure evidence, open a PR, wait for required checks, merge only after review, and rerun the closure workflow from `main`.

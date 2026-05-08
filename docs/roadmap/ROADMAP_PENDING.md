# QuantForge Roadmap

Status: living roadmap
Last updated: 2026-05-08 (post-execution-pass)
Source: migrated from Desktop and normalised after v1.4 review
Scope: post-v1.4 backlog for QA, docs, AI, data, execution, performance and production hardening

Rule: this is a backlog, not an execution order. Work should move from
confidence to automation to production, not from the most spectacular item to
the most expensive incident.

---

## Session 2026-05-08 summary

Phase 1 (trust), Phase 2 (research memory), and the in-repo slices of
Phase 3 (data/production foundations) shipped this session. Phase 3
items that need real credentials, legal review or external infra are
documented as blockers in [`BLOCKERS.md`](BLOCKERS.md). Phase 4 stays
gated behind benchmarking / profiling.

Items closed this session (R1, R7, R8, R9, R10, R11, R12, R13, R14,
R15, R22) total 80 new tests across 8 commits plus a follow-up
honesty cleanup commit and a `data_cache_qf` ghost-dir retirement.
Items still open: R2, R3, R4, R5, R6, R16, R17, R18, R19, R20, R21.

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

- `tests/test_spine_e2e.py`: 15 passed.
- Property suites: `tests/test_property.py` (15) + `tests/test_property_v2.py` (17).
- New session suites: `test_protocol_fuzz.py` (9), `test_llm_augmenter.py` (5),
  `test_rag.py` (10), `test_auto_loop.py` (7), `test_snapshots_distributed.py` (8),
  `test_lean_live.py` (9). Aggregate: 95 passed in 31.50s.
- Full fast-suite pass not re-verified at the end of this session;
  the 95-test aggregate covers the new and adjacent surface only.

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

### R15. API reference auto-generated (with warnings pending)

Status: landed, build succeeds; warnings still present
Evidence: `docs/conf.py`, `docs/index.rst`, `docs/api/index.rst`,
`Makefile` (`make docs`), `pyproject.toml` `[docs]` extra

Sphinx + autodoc + autosummary + napoleon + myst-parser + furo theme.
Optional-extras modules (`torch`, `hmmlearn`, `ccxt`, ...) are mocked
via `autodoc_mock_imports` so the build does not require the heavy
dependency tree. Build output goes to `docs/_build/html/` (gitignored).
Operator markdown guides surface alongside the auto-generated module
pages.

Caveat: a clean rebuild emits docstring-formatting warnings (RST
substitution errors in `strategies/library/atr_breakout.py`,
`strategies/library/online_learner.py`, `strategies/library/pair_trade.py`,
`validation/purged_cv.py`, `validation/spp.py`, plus duplicate-object
descriptions in `triage/`) and a couple of toctree warnings. The
build still produces a usable HTML tree. Cleaning the warnings is
tracked as R20 below.

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
suites. Remaining work tracked as R20 below if the runner proves too
narrow in practice.

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

## Recommended Execution Order

This section is now historical. The original sequence was:

1. Phase 1 (trust): R15, R14, R12, R13. **Done this session.**
2. Phase 2 (research memory): R9, R10, R8. **Done this session.**
3. Phase 3 (data + production): R7, R2, R1, R3, R4. **R7 + R1 in-repo
   slice done this session; R2 / R3 / R4 blocked on external deps,
   see `BLOCKERS.md`.**
4. Phase 4 (optimisation): R5, R6. **Still gated behind benchmarking /
   profiling. Do not start without measurement.**

Open items below.

---

## Active Backlog

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

Status: pending, design call
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

Status: pending or accept-as-wontfix
Priority: low
Effort: half a day to 2 days depending on choice
Area: regime/ML
Suggested path: `regime/markov_switching.py`,
`tests/test_markov_switching.py`

9 pre-existing failures in `tests/test_markov_switching.py` come from
statsmodels API drift. Unrelated to QuantForge logic but make the
baseline test command noisy.

Decision options:

- Pin `statsmodels` to a version that exposes the old API.
- Update `regime/markov_switching.py` to the current statsmodels API
  and re-green the tests.
- Skip the test module with `@pytest.mark.skip(reason="statsmodels API drift")`
  and document as wontfix in `CLAUDE.md`.

Definition of done:

- One option chosen and applied.
- Baseline test command no longer reports markov failures (skipped or
  fixed).
- Decision recorded in `CHANGELOG.md`.

### R18. Lint cleanup + CI hardening

Status: scope expanded after lint audit
Priority: medium
Effort: 1 to 2 weeks (incremental)
Area: tests / CI / lint
Suggested paths: legacy modules under `core/`, `validation/`, `ga/`,
`compliance/`, `agents/`, `analytics/`, etc; `.github/workflows/lint.yml`,
`tests/test_lint_config.py`

Two findings reframe the original "cosmetic false positive" item:

1. `ruff check .` reports ~6500 errors across the repo on baseline.
   Most are auto-fixable (`UP`, `I`, `B`, `E`) but the legacy surface
   has not been swept.
2. `.github/workflows/lint.yml` ran ruff with
   `continue-on-error: true`, so even the new code's lint regressions
   would not have blocked CI.

The follow-up landed:

- `pyproject.toml` `[tool.ruff.lint]` ignore list adds `N999` (the
  repo top-level dir is `QuantForge`; renaming it is out of scope and
  the package itself is `quantforge` via `package-dir` remapping).
- `.github/workflows/lint.yml` now runs two jobs: `ruff-full`
  (permissive sweep over the whole repo, `continue-on-error: true`)
  and `ruff-strict` (curated post-v1.4 surface, hard-fails on any
  finding).

Definition of done:

- New code added in this session is ruff-clean under the strict job.
  (Done as of this update.)
- Each curated module from the legacy sweep is migrated into the
  strict job after a focused cleanup pass. Track per-module migration
  in CHANGELOG entries.
- The `test_lint_config::test_no_unmarked_live_data_loads` scanner
  false positive is either fixed or skipped with a documented reason.

Risk: incremental migration is easy to drop. Keep one cleanup PR at
a time; do not bundle behavior changes with lint-only sweeps.

### R19. Wire `SnapshotStore` to the new backend interface

Status: follow-up to R7, pending
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

Status: pending
Priority: low
Effort: 1 to 2 days
Area: docs
Suggested paths: `validation/spp.py`, `validation/purged_cv.py`,
`strategies/library/atr_breakout.py`,
`strategies/library/online_learner.py`,
`strategies/library/pair_trade.py`, `triage/`, `docs/SPINE.md`

R15 left the Sphinx build emitting RST docstring warnings (substitution
references `|close[i]-close[i-1]|`, `|return|`, `|z|`; "inline strong
start-string without end-string" in spp / pipeline; "unexpected
indentation" in purged_cv) plus a few duplicate-object descriptions in
`triage/` and a couple of cross-reference warnings in `SPINE.md`.

Definition of done:

- `make docs` produces zero warnings on a clean rebuild.
- `make docs-strict` (or equivalent) treats warnings as errors and is
  wired into CI as a non-blocking job (then promoted to blocking once
  the count is zero).
- Cross-reference targets from `SPINE.md` either resolve or are
  rewritten as plain text.

### R21. Mutmut runner sanity

Status: optional follow-up to R12
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

## Suggested Next Task

Recommended next item: **R19** wire `SnapshotStore` to the new
`SnapshotBackend` interface.

Why:

- Closes the gap left by R7 (interface exists; the store does not yet
  use it).
- Pure refactor with the new tests as a safety net.
- No external blockers.
- Unblocks future remote backend drivers.

Second choice: **R20** clean up the Sphinx warning count so `make
docs` runs warning-free, then promote `ruff-strict` to cover the
docstrings affected.

Third choice: **R16** decide the Calmar / MAR zero-MDD contract.
Half-day effort, removes a property-test caveat.

Fourth choice: **R17** resolve the markov switching API drift, if the
priority is shrinking the known-issues list.

Phase 3 production items (R2, R3, R4) only after operator confirms
external dependencies (credentials, legal review, broker accounts) are
available.

---

## Commit Plan

Recommended separation per future task: one commit per Rxx item, scoped
narrowly. The session 2026-05-08 pass landed eight item-scoped commits
(`064c535`, `2a506eb`, `bd90417`, `105046b`, `8a644df`, `9593e86`,
`e06761b`, `56160f9`) plus the earlier R11 commit (`1b600a7`).

Avoid bundling unrelated agent-local files (`.claude/`, `AGENTS.md`)
unless they are intentionally part of project policy.

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
R15, R22) total 80 new tests across 8 commits plus follow-up honesty
cleanup commits.

Items added to the roadmap during the post-session review (R23 to R46)
capture every loose thread that surfaced in this chat: the project
rename to **AURORA**, repo / docs / CI housekeeping, operational
runbooks (audit rotation, HMAC keys, disaster recovery, daily ops
delivery), strategy lifecycle (curation policy + graveyard), benchmark
scaffold (the gate for R5 / R6), full mutmut sweep, multi-user RBAC,
spec signing, timezone audit and the `ZERO_costs` runtime warning.

Project name decision: **AURORA**. Rename execution tracked as R23.
Until R23 lands, the project name on disk and in code remains
`quantforge` -- doing the rename in isolation is the safer migration.

Items still open: R2, R3, R4, R5, R6, R16, R17, R18, R19, R20, R21,
R23 through R46.

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

Risk: the rename touches everything. Do it AFTER the open R19, R16,
R17 follow-ups so a rename rollback is not entangled with semantic
fixes.

### R24. Decide policy on `AGENTS.md` and `.claude/`

Status: pending decision
Priority: low
Effort: 1 hour
Area: repo hygiene

These files have stayed untracked across the whole session. The
decision is: commit them, gitignore them, or leave them as
intentionally untracked. Pick one and document it in `CLAUDE.md` so
future sessions stop suggesting committing them.

### R25. Refresh `CLAUDE.md` test count and known-issues block

Status: pending
Priority: low
Effort: 30 minutes
Area: docs / project memory

`CLAUDE.md` still claims a baseline of 2780 tests. The session added
80 new tests (R11 + R13 fuzz + R8/R9/R10/R7/R1 suites). After R17 and
R18 land, the known-issues block should also shrink. Bring the file
up to date.

### R26. Refresh `docs/ZERO_TO_LIVE.md` test command

Status: pending
Priority: low
Effort: 15 minutes
Area: docs

Section 2 still includes `--ignore=tests/test_config.py` even though
that test was repaired in R22. Drop the stale flag so the recipe
matches the live CI command.

### R27. Update `CHANGELOG.md` for the v1.4.x follow-ups

Status: pending
Priority: medium
Effort: 1 to 2 hours
Area: docs

The session shipped 14+ commits (R1, R7, R8, R9, R10, R11, R12, R13,
R14, R15, R22 plus three cleanup commits) that are not yet reflected
in `CHANGELOG.md`. Roll them into a single 1.4.1 entry (or a
sequence of 1.4.x patches if you prefer to map one entry per item).
Cite each commit hash for traceability.

### R28. Set the canonical repository URL

Status: pending
Priority: low
Effort: 5 minutes once decided
Area: docs / packaging

`docs/index.rst` no longer carries the `anthropics/quantforge`
placeholder, but no canonical URL exists yet. Decide where the repo
lives (private fork, organisation account, ...), set
`project_urls` in `pyproject.toml`, and link from the README plus
`docs/index.rst`.

### R29. Add Python 3.14 to the CI matrix

Status: pending
Priority: low
Effort: 1 hour
Area: CI

`tests.yml` runs against 3.11 / 3.12 / 3.13. The local developer
machine is on 3.14 and there are no known incompatibilities. Add 3.14
to the matrix once GitHub-hosted runners ship a stable 3.14 image.

### R30. Pre-commit hooks

Status: pending
Priority: medium
Effort: half a day
Area: repo hygiene / lint
Suggested paths: `.pre-commit-config.yaml`, `Makefile`

Configure `pre-commit` to run ruff + ruff-format on changed files
before each commit. Pair with a small `make precommit-install` target.
Pre-commit hooks shrink R18 (the legacy ruff debt) over time without
needing a flag-day cleanup.

### R31. Sphinx docs hosting

Status: pending decision
Priority: low
Effort: half a day for hosting; up to 2 days if also adding a
publish workflow
Area: docs / CI

Right now `make docs` builds locally to `docs/_build/html/`. Decide
on hosting: GitHub Pages, Read the Docs, internal mirror, or no
hosting (operator runs `make docs` locally). If hosting, add a
publish workflow and document the URL in README.

### R32. Legacy ruff cleanup batch plan

Status: pending
Priority: medium
Effort: 2 to 3 weeks (split into ~8 batches)
Area: lint / refactor
Suggested paths: legacy modules grouped by directory

R18 says "clean up legacy ruff debt"; 6500+ findings is too big for
a single sweep. Break it into batches and pick an explicit order:

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

Status: pending
Priority: medium
Effort: 1 hour (mostly waiting)
Area: QA

The session validated subsets (95 tests, 163 tests, 80 tests) but
did not re-run the full fast suite end-to-end after the cleanup
commits. Run the canonical baseline command once and record the new
pass count + list of any new failures in `CLAUDE.md`.

### R34. Audit log rotation policy

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
Priority: low
Effort: 2 to 3 hours
Area: ops / docs
Suggested path: `docs/DAILY_OPS_RECIPE.md`

`forge ops alerts --slack-webhook ...` exists in code; there is no
operator-facing recipe for: setting up the Slack/email side, picking
the right cron cadence, or rate-limiting alerts to avoid notification
fatigue. Document it.

### R38. Strategy version curation policy

Status: pending
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

Status: pending
Priority: low
Effort: 2 days
Area: research / observability
Suggested paths: `cli/forge.py` (`forge research graveyard`), or a
new dashboard page under `monitoring/`

Surface every archived candidate with its rejection reason and
timestamp so an operator can see "what we tried and why it failed".
Pair with R9 (RAG) so the graveyard is searchable.

### R40. Performance benchmark scaffold

Status: pending; gate for R5 / R6
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

Status: pending
Priority: low
Effort: half a day
Area: QA / CI

`thorough` (max_examples=200) currently runs only when an operator
runs `make property-thorough`. Add a nightly CI job that runs it
under the same env. Surface failures via the same channel as the
fast CI suite.

### R43. Multi-user / RBAC for the agent gateway

Status: pending design
Priority: medium-low
Effort: 2 to 3 weeks (with security review)
Area: agent gateway / security
Suggested paths: `agent_gateway/`, `compliance/rbac.py`

The current gateway treats every actor symmetrically. A team of
operators needs per-role caps (junior ops = paper-only, senior ops =
live, admin = revoke / rotate). Build on top of the existing
`compliance/rbac.py` skeleton.

### R44. Strategy spec verification chain

Status: pending design
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

Status: pending
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

Status: pending
Priority: low
Effort: 1 hour
Area: safety / engine

`ZERO_costs` is the default cost model only because it is convenient
in tests. Easy to forget on the way to live. Emit a one-shot warning
the first time `run_backtest` runs with `ZERO_costs` in a process,
unless an explicit `acknowledge_zero_costs=True` flag is passed.

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

Three short-effort items can land before any of the bigger plays
(R23 rename, R32 ruff legacy cleanup, R40 benchmark scaffold):

1. **R25 + R26 + R27** -- bring `CLAUDE.md`, `ZERO_TO_LIVE.md` and
   `CHANGELOG.md` up to the post-session reality. Total ~3 hours.
   Removes the cosmetic discrepancies surfaced in the post-session
   review.
2. **R33** -- run the full fast suite once and record the new pass
   count. Mostly waiting; gives R25 something accurate to copy in.
3. **R30** -- add pre-commit hooks so future PRs do not regrow
   ruff debt while R32 is still in progress.

After that, the big plays in priority order:

- **R23** Rename to AURORA. Touches everything; do it in isolation.
- **R19** Wire `SnapshotStore` to the new `SnapshotBackend`.
  Pure refactor; safety net is the R7 tests.
- **R40** Performance benchmark scaffold. Unlocks the R5 / R6 gates.
- **R32** Legacy ruff cleanup, batch by batch.
- **R34** Audit log rotation (becomes urgent once long-running ops
  start writing real audit chains).
- **R20** Sphinx docstring cleanup.
- **R16** Calmar / MAR zero-MDD contract.
- **R17** Markov switching API drift.

Phase 3 production items (R2, R3, R4) and Phase 4 perf items
(R5, R6) only after their gates are met (operator-side credentials
or in-repo benchmark / profile evidence).

---

## Commit Plan

Recommended separation per future task: one commit per Rxx item, scoped
narrowly. The session 2026-05-08 pass landed eight item-scoped commits
(`064c535`, `2a506eb`, `bd90417`, `105046b`, `8a644df`, `9593e86`,
`e06761b`, `56160f9`) plus the earlier R11 commit (`1b600a7`).

Avoid bundling unrelated agent-local files (`.claude/`, `AGENTS.md`)
unless they are intentionally part of project policy.

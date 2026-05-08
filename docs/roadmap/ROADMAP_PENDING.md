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

A second deep audit pass added R47 to R76 covering the items that only
turn up when you grep the actual code: production-status of the 75+
cross-asset / data / infra modules, triage of `experimental/`,
oversized-file splits (cli/forge.py 3577 lines, deployment/brokers.py
1861 lines, ...), 65 `raise NotImplementedError` sites, 24 TODO /
FIXME markers, 243 broad `except Exception:` blocks, 16 undocumented
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

Project name decision: **AURORA**. Rename execution tracked as R23.
Until R23 lands, the project name on disk and in code remains
`quantforge` -- doing the rename in isolation is the safer migration.

Items still open: R2, R3, R4, R5, R6, R16, R17, R18, R19, R20, R21,
R23 through R124.

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

### R47. Production-status audit for cross-asset / data / infra modules

Status: pending
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

Status: pending
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

### R49. Split `cli/forge.py` (3577 lines)

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

### R50. Split `deployment/brokers.py` (1861 lines)

Status: pending
Priority: medium
Effort: 2 to 3 days
Area: refactor
Suggested path: `deployment/brokers/`

Convert to a package: one file per broker (`paper.py`, `alpaca.py`,
`ib.py`, `coinbase.py`, `kraken.py`) plus a base `__init__.py` that
re-exports the public surface. Tests already partition by broker.

### R51. Split `reporting/tearsheet.py` (1312 lines)

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
- `core/data_layer.py` (923).
- `research/factory/factory.py` (882).
- `deployment/preflight.py` (821).

One commit per split. Keep behaviour identical. No bundling with
semantic changes.

### R53. Classify the 65 `raise NotImplementedError` sites

Status: pending
Priority: medium-high
Effort: 2 to 3 days
Area: project hygiene

`grep -rn "raise NotImplementedError"` returns 65 hits in production
modules. Each is one of:

- a deliberate base-class abstract (`@abstractmethod`-style),
- a deliberate "remote backend reserved" stub (R7-style fail-loud),
- an unfinished implementation that someone gave up on.

Tag each occurrence with one of three categories in a comment, then
file follow-up tasks for the genuinely unfinished ones.

### R54. Resolve the 24 TODO / FIXME markers

Status: pending
Priority: low
Effort: 2 days
Area: project hygiene

A grep across production code finds 24 TODO / FIXME / XXX / HACK
markers. Some are scaffold notes in the Lean exporter; others are
real "come back to this" reminders. Triage: convert to a tracked
roadmap item, fix in place, or drop with a one-line rationale.

### R55. Audit `except Exception:` blocks

Status: pending
Priority: medium
Effort: 1 week
Area: safety / error handling

243 `except Exception:` blocks across the repo. Some are intentional
(audit-trail writers must not crash the caller). Many are likely too
broad and silently mask real failures. Walk every site and decide:

- Keep with explicit comment naming the swallowed cases.
- Tighten to a specific exception class.
- Re-raise after logging.

### R56. Replace `print()` calls with structured logging

Status: pending
Priority: low
Effort: half a day
Area: observability
Suggested paths: `ga/runner.py`, `ga/multi_asset_runner.py`,
`compliance/trade_reconstruction.py`

Production code emits status via `print()` in a handful of places.
Convert to module-level loggers so output is filterable and CI-friendly.

### R57. Document the 16 missing environment variables

Status: pending
Priority: high (security-sensitive subset)
Effort: half a day
Area: docs / ops
Suggested paths: `CLAUDE.md`, `README.md`, `docs/ZERO_TO_LIVE.md`

Code references env vars not documented anywhere:

Security:

- `QF_GATEWAY_SECRET` (HMAC server secret for token signing).
- `QF_OPERATOR_KEY` (HMAC operator countersign secret).
- `QF_PII_FERNET_KEY` (encryption-at-rest for PII).
- `QF_TOTP_SECRET` (two-factor auth seed).
- `QF_SQLCIPHER_KEY` (audit DB encryption).

Ops:

- `QF_AUTO_LOOP_LOG`, `QF_CCXT_DEFAULT_EXCHANGE`,
  `QF_CCXT_BINANCE_KEY`, `QF_CCXT_BINANCE_SECRET`,
  `QF_CCXT_KILL_SWITCH`, `QF_CONFIG_DIR`, `QF_JOURNAL`,
  `QF_LEAN_LIVE_AUTH`, `QF_REFRESH`, `QF_ALLOW_FULL_TIER`,
  `QF_CACHE` (legacy alias of `QF_CACHE_DIR`).

Definition of done:

- Every env var the code reads is documented in one place with
  purpose, default, and security caveat.
- Security-sensitive env vars are flagged "must come from a secrets
  manager, never .env file in repo".

### R58. Resolve `QF_ALLOW_FULL_TIER` vs `QF_ALLOW_OOS_LOCKED`

Status: pending
Priority: low
Effort: 1 hour
Area: protocol / docs

The CLI uses `QF_ALLOW_FULL_TIER`; `CLAUDE.md` mentions
`QF_ALLOW_OOS_LOCKED`. Verify both are intended (separate ceremonies)
or consolidate to one. Update docs to match the actual code.

### R59. Wire the existing pre-commit configuration

Status: pending
Priority: medium (replaces R30 wording)
Effort: 1 hour
Area: dev tooling
Suggested path: `.pre-commit-config.yaml`, `Makefile`,
`docs/CONTRIBUTING.md`

`.pre-commit-config.yaml` already exists with ruff + standard hooks
(R30 incorrectly described it as "configure pre-commit"). What is
missing:

- A `make precommit-install` target that runs
  `pre-commit install --hook-type pre-commit --hook-type pre-push`.
- A doc paragraph in `CONTRIBUTING.md` telling new contributors to
  run that target on first clone.
- A CI job that runs `pre-commit run --all-files` so PRs that bypass
  the hook locally are still caught.

### R60. Cross-platform `wheel.yml` CI

Status: pending
Priority: low
Effort: 1 hour
Area: CI
Suggested path: `.github/workflows/wheel.yml`

`wheel.yml` creates a temp venv at `/tmp/test_venv` -- Linux-only.
Once Windows is added to the wheel job (or if anyone moves the
runner), it breaks. Switch to `runner.temp` or a tmp directory via
`mktemp` / `Get-Item -LiteralPath $env:RUNNER_TEMP`.

### R61. Security scanning in CI

Status: pending
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

Status: pending
Priority: low
Effort: 2 hours
Area: CI / supply chain

Produce a software bill of materials per release. `cyclonedx-bom` or
`syft` both work. Attach the SBOM artefact to the wheel build run so
operators can audit transitive deps.

### R63. mypy in CI

Status: pending
Priority: medium
Effort: 1 day initial; ongoing maintenance
Area: CI / type checking
Suggested paths: `.github/workflows/typecheck.yml`,
`pyproject.toml` (`[tool.mypy]`)

`mypy` is in `[dev]` but not run by any CI workflow. Add a
`typecheck` job that runs `python -m mypy quantforge/`. Start with
`continue-on-error: true` (the legacy code is partially typed) and
ratchet up over time.

### R64. Coverage gate enforced in CI

Status: pending
Priority: medium
Effort: 1 hour
Area: CI / QA

`.coveragerc` declares a fail-under threshold of 80 percent, but
`pytest --cov` is not in the test workflow. Add `--cov` to the test
command in `tests.yml` and let the .coveragerc threshold actually
gate the job.

### R65. Coverage artefact / dashboard

Status: pending
Priority: low
Effort: half a day
Area: observability

Upload the coverage XML from CI either to Codecov / Coveralls or as
a workflow artefact, so operators can see uncovered lines without
re-running locally.

### R66. Archive historical version completion reports

Status: pending
Priority: low
Effort: 30 minutes
Area: docs hygiene

`docs/v1_COMPLETION_REPORT.md`, `v1_1_*`, `v1_2_*`, `v1_3_*` (four
files), `v2_0_*`, `v3_0_*` -- nine historical reports clutter the
docs index. Move into `docs/archive/version_reports/` and update
references. Keep `v4_0_SPINE_REPORT.md` in place since it documents
the current spine.

### R67. Archive historical development plans

Status: pending
Priority: low
Effort: 15 minutes
Area: docs hygiene

`docs/DEVELOPMENT_PLAN.md`, `DEVELOPMENT_PLAN_v1_1.md`,
`DEVELOPMENT_PLAN_v1_2.md`, `DEVELOPMENT_PLAN_v1_3.md` -- move to
`docs/archive/dev_plans/`. New plans live in the roadmap.

### R68. Decision on `docs/GITHUB_RESEARCH_v1.1.md`

Status: pending
Priority: very low
Effort: 15 minutes
Area: docs hygiene

Sphinx warns this file is not in any toctree. Either include it in
the operator-guides toctree or move to `docs/archive/`.

### R69. SECURITY.md vulnerability disclosure policy

Status: pending
Priority: medium
Effort: 2 hours
Area: docs / security
Suggested path: `SECURITY.md`

GitHub's standard `SECURITY.md` describes how to report a
vulnerability privately, what response window to expect, and which
versions are supported. Required before any public release.

### R70. README references CONTRIBUTING.md

Status: pending
Priority: very low
Effort: 5 minutes
Area: docs

`CONTRIBUTING.md` exists but `README.md` does not link to it. One-
line fix.

### R71. Concurrent strategy run isolation

Status: pending
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

Status: pending; follow-up to R12 / R41
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

Status: pending
Priority: low
Effort: 1 hour
Area: refactor / API hygiene

`cli/__init__.py` is empty. Pair with R49 (CLI split): once the
subcommand modules exist, declare the public symbols in
`__init__.py` so external callers have a stable surface to import
from rather than reaching into `cli.forge`.

### R74. Cosmetic Windows-incompatible path in docstring

Status: pending
Priority: very low
Effort: 5 minutes
Area: docs

`core/data_layer.py:164` has a docstring example using
`/tmp/.oos_lock.json`. On Windows that path resolves under the C:
drive root, which is usually not writable for non-admin users. Fix
the example to use `tmp_path / ".oos_lock.json"` or
`Path(tempfile.gettempdir()) / ".oos_lock.json"`.

### R75. Audit hardcoded paths beyond `data_cache_qf`

Status: pending; follow-up to R22
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

Status: pending; sub-task of R23
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

Status: pending
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

Status: pending
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

Status: pending
Priority: medium
Effort: 2 weeks
Area: strategies
Suggested path: `strategies/patterns/`

Detect chart patterns (head and shoulders, double top / bottom,
triangles, flags, breakouts on candle formations) and emit standard
`signals()` arrays. Pair with R77 so generated strategies can use
"pattern detected" as a precondition block.

### R80. Multi-platform code export beyond Lean

Status: pending
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

Status: pending
Priority: medium
Effort: 3 to 4 days
Area: validation / reporting
Suggested paths: `validation/walk_forward.py`, `reporting/tearsheet.py`

Render the per-window OOS performance as a 2D heatmap (window index
x metric). Surfaces "this strategy passed walk-forward overall but
fell apart in window 4" at a glance.

### R82. Optimization heatmaps

Status: pending
Priority: medium
Effort: 3 to 4 days
Area: GA / reporting
Suggested paths: `ga/runner.py`, `reporting/tearsheet.py`

For 2-parameter optimizations, render a heatmap of the fitness
landscape (param X x param Y -> Calmar). For higher-D, render
pairwise slices. Surfaces "knife-edge" optima where one nudge in
parameter space tanks performance.

### R83. Equity curve similarity scoring

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
Priority: low
Effort: 1 week
Area: strategies / docs
Suggested paths: `strategies/templates/`, `docs/STRATEGY_TEMPLATES.md`

Curate a gallery of starter strategies grouped by family (trend
following, mean reversion, breakout, pairs, vol-targeting overlay,
regime-switching). Each template ships with a one-page description,
a parameter cheat-sheet, and a smoke backtest expected output.

### R88. Money management library

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
Priority: medium
Effort: 3 to 4 days
Area: deployment / safety
Suggested path: `deployment/vol_filter.py`

Pause trading when a configured volatility metric (VIX, realized
vol, regime detector) breaches a band. Filter integrates with the
existing `LiveConfig` so operators do not need new wrappers.

### R96. Custom session times per strategy

Status: pending
Priority: low
Effort: 3 to 4 days
Area: deployment

Today strategies inherit the engine session calendar (RTH / 24h /
ETH). Allow per-strategy session windows so an Asia-only signal does
not fire during US hours. Honour exchange-local timezones (R45).

### R97. Cross-validation matrices

Status: pending
Priority: medium-low
Effort: 1 week
Area: validation / reporting
Suggested paths: `validation/cscv_pbo.py`, `reporting/tearsheet.py`

Visualise the CSCV / PBO output as a matrix of train / test fold
performance, plus a delta heatmap. Surfaces "the strategy looks fine
on average but has a fold where it loses 30%".

### R98. Consolidated stability index

Status: pending
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

Status: pending
Priority: medium-low
Effort: 3 to 4 weeks
Area: research / regime
Suggested paths: `research/regime_adaptive.py`, `regime/`

Strategies that re-tune their parameters when a regime detector
(R40 Hurst, HMM, Bayesian) flags a regime shift. Pair with R71 so
adaptive re-tuning never lifts an OOSGuard.

### R100. Trade simulator with realistic frictions

Status: pending
Priority: medium
Effort: 1 to 2 weeks
Area: execution / paper

Today PaperBroker is functional but does not model partial fills,
queue priority, varying spread, latency, or rejected orders. Build a
trade simulator that wraps PaperBroker with these knobs (cf. R4
first-slice "paper execution simulator").

### R101. Volume profile analysis

Status: pending
Priority: low
Effort: 1 week
Area: analytics / microstructure
Suggested path: `analytics/volume_profile.py`

Compute volume-by-price profiles (POC, value area, HVN/LVN). Useful
input for support / resistance signals and post-trade analysis.
Pair with R86 so a volume-profile node is available as a strategy
block.

### R102. Build-level goal-seeking optimisation

Status: pending
Priority: low
Effort: 1 to 2 weeks
Area: GA / research

"Find me a strategy with Sharpe >= 1.2 and MDD <= 15% in under 2
hours of compute" -- the build runs until the goal is met or the
budget expires. Today GA runs for a fixed number of generations.
Add a goal-seeking driver on top of `ga/runner.py` that watches the
Pareto front and stops early on success.

### R103. Random-baseline statistical significance test

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
Priority: medium-high
Effort: 1 week
Area: strategies / ensemble
Source: BuildAlpha
Suggested path: `strategies/library/ensemble_vote.py`

Combine M sub-signals; emit `+1` only when at least X% agree on
long, `-1` when at least X% agree on short, `0` otherwise. Pair with
R105 for contribution analysis and R98 for stability scoring.

### R110. Bar-by-bar backtest replay debugger

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
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

Status: pending
Priority: medium
Effort: 1 week
Area: strategies / portfolio
Source: Composer.trade
Suggested path: `strategies/symphony/`

Operators want "apply rule X to my equity bucket, rule Y to my
fixed-income bucket". Symphony language extension: groups of assets
plus rules per group. Pair with R113.

### R116. Explicit cash-state within strategy

Status: pending
Priority: low
Effort: 3 days
Area: strategies / engine
Source: Composer.trade

Today a flat strategy returns weight 0. There is no first-class
"cash holds out for X bars while in cash" position. Add an explicit
cash state in the engine so cooldown / regime-off / stop-out periods
are visible distinct from "no signal yet".

### R117. What-if scenario replay

Status: pending
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

Status: pending
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

Status: pending
Priority: medium
Effort: 3 days
Area: deployment / safety
Source: Molanis
Suggested path: `deployment/spread_filter.py`

Pause trading when the live bid-ask spread exceeds a configured
multiple of the average spread for the symbol. Cheap defence
against thin-market lockups.

### R120. Account-level circuit breaker

Status: pending
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

Status: pending; design-call required
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

Status: pending
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

Status: pending
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

Status: pending
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

Quick-win batch (run before any of the bigger plays). Total ~6 hours:

1. **R25 + R26 + R27** -- bring `CLAUDE.md`, `ZERO_TO_LIVE.md` and
   `CHANGELOG.md` up to the post-session reality.
2. **R33** -- run the full fast suite once and record the new pass
   count.
3. **R57** -- document the 16 missing env vars (security-sensitive
   subset is high priority).
4. **R59** -- wire the existing pre-commit config (install target +
   contributing doc + CI verify job).
5. **R70** -- README link to CONTRIBUTING.md.
6. **R74** -- one-line docstring path fix.

Medium plays (1 to 5 days each) before R23 rename:

- **R69** SECURITY.md vulnerability disclosure.
- **R66 + R67** archive historical reports and dev plans.
- **R56** replace `print()` with logging.
- **R47** production-status audit of the 75+ cross-asset modules
  (this one is a genuine surprise: the project ships modules whose
  production state nobody has written down).
- **R48** triage `experimental/`.
- **R30 / R59** pre-commit + R63 mypy + R64 coverage gate as a CI
  hardening batch.

Big plays (priority order):

- **R23** Rename to AURORA. Touches everything; do it in isolation
  AFTER R76 (env var migration plan) is finalised.
- **R49 + R50 + R51 + R52** oversized-file splits.
- **R19** Wire `SnapshotStore` to the new `SnapshotBackend`.
- **R40** Performance benchmark scaffold. Unlocks R5 / R6 gates.
- **R32** Legacy ruff cleanup, batch by batch.
- **R34** Audit log rotation.
- **R71** Concurrent strategy isolation.
- **R55** `except Exception:` audit (243 sites).
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

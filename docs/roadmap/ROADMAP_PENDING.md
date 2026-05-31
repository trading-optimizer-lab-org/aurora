# Aurora Roadmap (formerly Aurora)

Status: living roadmap
Last updated: 2026-05-10 (solo-operator posture applied to R158-R190)
Source: migrated from Desktop and normalised after v1.4 review
Scope: post-v1.4 backlog for QA, docs, AI, data, execution, performance and production hardening

Rule: this is a backlog, not an execution order. Work should move from
confidence to automation to production, not from the most spectacular item to
the most expensive incident.

Roadmap hygiene rules:

- New R155+ items are allowed when they are concrete, sourced and
  implementable. Avoid vague wish-list entries, but do not block useful
  roadmap expansion merely because the number is high.
- Keep external blockers in `BLOCKERS.md`; keep in-repo actionable work
  here.
- A roadmap item should stay only if it has a clear next action,
  acceptance evidence, or an explicit design decision to make.
- If two items describe the same work, keep the more precise one and
  mark the older entry as superseded instead of tracking both.
- Verification beats memory. If tests / lint / docs / build contradict
  an old note, update the roadmap immediately.

Solo-operator posture:

- AURORA is assumed to be used by one operator unless a future note
  explicitly changes that. Design for disciplined solo research, not
  institutional bureaucracy.
- Keep the strong parts: data contracts, point-in-time safety,
  reproducibility, audit hashes, evidence packs, realistic costs,
  preflight checks, local diagnostics and clear failure messages.
- Keep approvals local and lightweight: one operator may approve,
  override or retire a strategy, but the reason, timestamp, hashes and
  affected artefacts must be recorded.
- Prefer local-first tools: JSONL logs, local reports, local dashboard,
  CLI checks and files under runtime paths. External observability,
  multi-user workflow, public plugin systems and signed public releases
  are optional expansions, not default requirements.
- Do not build committee workflow unless real multi-user operation
  appears. A single human with a good evidence trail beats five fake
  approval roles. Glamour saved, complexity murdered.

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

Project name decision: **AURORA**. R23 has executed: package metadata,
CLI entry point and primary imports use `aurora`. The legacy
`aurora` namespace remains only as the planned compatibility shim.

Current strict open items, external blockers and recently reconciled
state notes:

- **R2, R3, R4** -- in-repo prep complete; remaining work is
  permanently external (credentials, legal review, broker
  reconciliation). The roadmap entries above and `BLOCKERS.md` carry
  the canonical state.
- **R5, R6** -- gate primitive landed (R40 benchmark scaffold).
  Remaining work waits for a benchmark / profile signal that Python
  + numba is the real bottleneck.
- **R34** -- closed 2026-05-10. 7 writers wired to rotation policy.
- **R39** -- closed 2026-05-10. CLI subcommands + opt-in dashboard tile.
- **R41** -- procedure documented; the actual sweep runs on a
  Linux/macOS/WSL host because mutmut native-Windows is upstream-
  unsupported.
- **R45** -- closed 2026-05-10. 43 tz idioms migrated across 17 files.
- **R48** -- closed 2026-05-10. 8 keep / 9 archive (.py.txt) / 3 delete.
- **R49** -- closed 2026-05-10. `cli/cmd_run.py` split into shim + 4
  siblings; all `cli/cmd_*.py` modules ≤800 lines.
- **R52** -- closed 2026-05-10. `reporting/daily_ops/builder.py` and
  `core/data_layer.py` split into sub-packages; all production files
  ≤800 lines.
- **R65** -- closed 2026-05-10. Self-hosted HTML coverage artefact
  in CI workflow; external service dependency rejected.
- **R90** -- distributed generation scaffold exists; real distributed
  runtime remains deferred until factory contracts and validation gates
  are stronger.
- **R140** -- closed 2026-05-10. Auto-loop runs SLA evaluator at
  cycle step 0; default archive, opt-in revalidate.
- **R155** -- closed 2026-05-10. 12 provider connectors + ProviderRole
  registry + 5 CLI subcommands + 27 tests; live ops still operator follow-up.
- **R156** -- closed 2026-05-10. 8 providers shipped (openfigi, sec_edgar,
  dbnomics, ecb, coinmetrics, tiingo, dukascopy, marketdata_app) + 8 new
  ProviderRole entries + 5 CLI subcommands + 91 tests. PIT-safe SEC facts.
- **R157** -- closed 2026-05-10. Manifest-driven first-dataset
  orchestrator (`config/first_dataset.yaml` +
  `core/data_providers/first_dataset/` package, 7 modules max 285 lines);
  3 new CLI subcommands
  (`bootstrap-first-dataset`, `freeze`, `coverage-report --dataset
  first`); 17 unit tests with no live network; at least one approved
  SnapshotStore freeze from local persisted data.
- **R158** -- completed 2026-05-10. Diversified seed manifest at
  `config/diversified_seed_dataset.yaml` covers 10 sections (133
  symbols), with trust levels, FX section + library, symbol
  normalisation table (BRK-B / FX majors / DXY), strict persistence
  contract gates (extreme-return spike, calendar-gap, OHLC bands),
  multi-symbol freeze, requested-vs-persisted summary, plus 16 unit
  tests + 4 smoke research tests with no live network.
- **R159-R167** -- open. Post-R158 data trust layer: instrument
  identity, corporate actions / calendars, quality quarantine,
  point-in-time fundamentals, liquidity / costs / capacity, mandatory
  benchmarks, research ledger enforcement, reproducible evidence packs
  and incremental data refresh / diff.
- **R168-R177** -- open. Execution integrity, portfolio construction,
  strategy atlas, literature ingestion, solo-operator risk approval and
  agentic explanation layer. These items should start only after the
  data trust layer has a usable first slice.
- **R178-R190** -- open. Local-first platform-hardening layer: data
  licence registry, local telemetry, lightweight incident notes,
  feature store, model registry, futures, options, crypto derivatives,
  optional extension API, `aurora doctor`, solo cockpit and performance
  / memory budget. Public release signing and external observability
  are optional, not default.

R23 (Aurora rename) and R76 (env var migration) closed 2026-05-09 in
commit `cf41bc2`. Package now installs as `aurora-1.5.0`; both
`import aurora` and the deprecation-warned `import aurora` shim
work; `aurora --version` returns `aurora 1.5.0`.

Every other roadmap item has either landed code, a scaffold, a
written decision, or an explicit descope. R30 superseded by R59. R32
descoped 2026-05-08.
R30 is superseded by R59. R32 descoped 2026-05-08 (default ruff
gate is clean; broader rule families are not planned).

Closed-but-kept-for-history entries: R1, R7, R8, R9, R10, R11, R12,
R13, R14, R15, R17, R20, R22, R30, R33.

Newly closed / scaffolded / plan-locked in the 2026-05-08 "execute
the whole roadmap" batch, reconciled with the 2026-05-09 truth pass:
**R2 (in-repo prep), R3 (in-repo prep), R4 (in-repo prep), R5
(gate ready), R6 (gate ready), R16, R18, R19, R21, R23 (rename
EXECUTED 2026-05-09 commit cf41bc2), R24, R25,
R26, R27, R28, R29, R31, R32 (descoped), R34,
R35, R36, R37, R38, R39, R40, R41 (procedure), R42, R43, R44, R45
(helper), R46, R47, R48, R49 (partial), R50 (done), R51 (done), R52
(partial), R53, R54, R55 (policy doc), R56, R57, R58, R59, R60, R61,
R62, R63, R64, R65, R66, R67, R68, R69, R70, R71, R72, R73, R74,
R75, R76 (env helper landed cf41bc2), R77, R78, R79, R80 (PineScript slice), R81, R82,
R83, R84 (skeleton), R85 (plan), R86, R87, R88, R89, R90 (scaffold),
R91, R92, R93, R94, R95, R96, R97, R98, R99, R100, R101, R102,
R103, R104, R105, R106, R107, R108, R109, R110, R111, R112, R113,
R114, R115, R116, R117, R118, R119, R120, R121 (decision), R122,
R123, R124, R125, R126, R127, R128, R129, R130, R131, R132, R133,
R134, R135, R136, R137, R138, R139, R140 (scaffold), R141, R142
(scaffold), R143, R144, R145, R146, R147, R148, R149, R150, R151,
R152, R153, R154**.

Total: all 154 original numbered items have been triaged; R155 has
landed as the free bulk data-acquisition programme; R156 has landed as
the complementary-provider programme; R157 has landed as the first
dataset ingestion machinery; R158 is the diversified seed-universe
execution programme; R159-R167 are the post-ingestion trust layer;
R168-R177 are the next execution / portfolio / solo-governance layer;
R178-R190 are the local-first platform-hardening layer. That does
**not**
mean all are fully implemented. Current truth: most items have landed
code, a scaffold, a locked plan, an external blocker, or an explicit
descope; the state list above is the canonical "still needs work or
needs clear status visibility" set. "Plan-locked" and "scaffold
landed" are not synonyms for "done". Future updates must keep that
distinction visible.

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

Batch 17 (final residual closure) lands the GitHub Pages docs
workflow (R31), the file-split plan covering R49-R52
(`docs/FILE_SPLIT_PLAN.md`), the mutmut sweep procedure on a
non-Windows host (R41 in `docs/MUTATION_TESTING.md`), the Aurora
rename execution checklist (R23 in
`docs/AURORA_RENAME_CHECKLIST.md`), and explicit "in-repo prep
complete; execution permanently external" closure for R2-R6 against
`BLOCKERS.md`. No new tests required (workflow + procedure + plan
docs); existing suite remains green.

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

AURORA v1.5 has a working protocol spine plus the new in-repo
hardening layer:

- ProtocolPolicy as code.
- DataProviderRegistry with provenance and tier posture.
- SnapshotStore with hash binding. A pluggable `SnapshotBackend`
  interface exists and R19 wires successful freezes through the backend
  mirror path.
- ExperimentRegistry lineage.
- ValidationPipeline with mandatory gates.
- AgentAuditGateway with scoped tokens and hash-chained audit.
- Paper / live guard layer with broker safety primitives.
- Sphinx API reference + zero-to-live operator guide (R14, R15).
- Mutation-testing target list (R12) + protocol fuzz suite (R13).
- LLM auditor augmenter scaffold (R8).
- RAG over research history (R9) + auto-research loop (R10).
- Lean live deploy gate with provenance + operator-flag triple-gate (R1).

Latest verified snapshot from this workspace:

- Full fast suite:
  `python -m pytest tests/ -m "not slow and not integration" --ignore=tests/test_config.py --ignore=tests/test_property.py -q`
  -> 3368 passed, 23 skipped, 10 deselected.
- Ruff:
  `ruff check .` passed.
- Build:
  `python -m build --wheel` produced `aurora-1.5.0-py3-none-any.whl`
  with no build warnings.
- CLI:
  wheel import smoke passed for the renamed `aurora.*` modules.

Earlier audit snapshots also recorded coverage, mypy, pre-commit and
strict Sphinx docs as green. Re-run those before cutting a release if
they matter to the release gate.

Reference reports:

- `docs/v4_0_SPINE_REPORT.md`
- `docs/roadmap/BLOCKERS.md`
- `CHANGELOG.md`
- `CLAUDE.md`

External research references reviewed on 2026-05-09:

- `C:\Users\HP\Downloads\HFT_2024___Oxford___lecture_notes_2024.pdf`
  -- Oxford lecture notes on market microstructure and algorithmic
  trading. Treat as the main source reference for Candidate A:
  realistic execution, limit-order behaviour, market impact, optimal
  execution, market making, portfolio execution and cointegrated-asset
  trading. It should influence execution models, replay, fills, TCA and
  broker reconciliation before live capital.
- `C:\Users\HP\Downloads\ssrn-3247865.pdf` -- "151 Trading
  Strategies". Treat as a strategy catalogue, not as an implementation
  mandate. It should feed Candidate E: strategy atlas, benchmark
  templates, candidate triage, clone detection and the strategy
  graveyard. No strategy should enter production merely because it
  appears in this PDF.
- `https://github.com/skfolio/skfolio` -- skfolio, a Python portfolio
  optimisation and risk-management library built on top of
  scikit-learn. Treat as the main source reference for Candidate F:
  portfolio optimiser design, risk measures, constraints, transaction
  costs, model selection, walk-forward and purged cross-validation.
  Use it as a benchmark / design reference first; only consider an
  optional dependency after licence, dependency weight and API fit are
  reviewed.
- `https://github.com/Y-Research-SBU/QuantAgent` -- QuantAgent, a
  multi-agent LLM reference project for market analysis. Treat as the
  source reference for Candidate G: agentic research support and
  decision explanation. It must not become a live-trading authority,
  OOS reader or broker-control path.
- `https://github.com/nautechsystems/nautilus_trader` -- production-
  grade event-driven trading engine. Treat as a reference for Candidate
  A: deterministic event flow, backtest/live parity, execution reports,
  venue/instrument modelling and replay/reconciliation boundaries.
- `https://github.com/QuantConnect/Lean` -- modular event-driven
  algorithmic trading engine with backtest/live workflow, data,
  brokerage, research, optimisation and reporting modules. Treat as a
  reference for Candidate A and Candidate C, especially engine
  modularity, data/event abstractions and live deployment gates.
- `https://github.com/microsoft/qlib` -- AI-oriented quant research
  platform covering data processing, model training, backtesting,
  risk modelling, portfolio optimisation and order execution. Treat as
  a reference for Candidate B / F / G, but only through the research
  ledger and data-contract gates.
- `https://github.com/microsoft/RD-Agent` -- Microsoft's R&D-Agent
  project, referenced by Qlib for LLM-assisted quant R&D. Treat as a
  reference for Candidate G and automated research, with the same
  no-OOS / no-live authority limits as QuantAgent.
- `https://github.com/polakowo/vectorbt` -- vectorised research and
  large parameter-sweep framework. Treat as a reference for Candidate B
  and Candidate E: fast sweeps, broadcasting, indicator experiments and
  the need to record every tried variant to avoid silent overfitting.
- `https://github.com/stefan-jansen/zipline-reloaded` -- maintained
  Zipline fork. Treat as a reference for event-driven backtesting,
  data bundles, calendars and the user-facing research API.
- `https://github.com/dcajasn/Riskfolio-Lib` and
  `https://github.com/PyPortfolio/PyPortfolioOpt` -- portfolio
  optimisation references alongside skfolio. Treat as reference
  libraries for Candidate F, not automatic dependencies.
- `https://github.com/freqtrade/freqtrade` -- mature open-source crypto
  bot. Treat as a reference for dry-run/live workflow, exchange UX,
  lookahead checks, recursive-signal checks and operator controls. GPL
  licensing means design reference only unless legal review says
  otherwise.

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
`pyproject.toml` (`aurora.research.auto_loop` registered)

`AutoResearchLoop` wraps `ResearchFactory` with a `generate -> submit
-> log` cycle. Tier guard inherited from the factory. Review-queue cap
defers submission rather than piling up. Dry-run mode for cron-bring-up.
Per-cycle JSONL summaries land at `$QF_AUTO_LOOP_LOG` for replay /
audit. Per-cycle generator seed = `seed_base + cycle_index` for
reproducibility.

Caveat: the original commit (`9593e86`) created
`research/auto_loop/__init__.py` and `loop.py` but did not register
`aurora.research.auto_loop` in `[tool.setuptools].packages` and
`[tool.setuptools.package-dir]`. That meant the package worked under
editable install but would have been missing from any wheel built
from the repo. The packaging entries were added in a follow-up; the
wheel now ships `aurora/research/auto_loop/loop.py`.

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

Current state: the roadmap is triaged, but not empty. Most in-repo
items now have either landed code, a documented decision, or a
deliberate scaffold. The next work should be fewer, deeper tracks
rather than more numbered tasks.

### Track 1. Finish Remaining In-Repo Work

Do this before starting the new candidate programmes:

1. **R49 + R52** -- finish the remaining oversized-module splits:
   `cli/cmd_run.py`, `reporting/daily_ops/builder.py` and
   `core/data_layer.py`. R50 and R51 are already structurally closed.
2. **R34 + R45** -- finish the two codebase-wide sweeps: audit-log
   rotation wiring and timezone helper adoption.
3. **R39 + R140** -- surface the graveyard in CLI/dashboard and connect
   lifecycle SLA decisions to the auto-research loop.
4. **R21 + R41** -- run the first full mutation sweep and publish the
   report.
5. **R48** -- make the operator decision for `experimental/`: keep,
   archive or delete each speculative module.
6. **R65** -- decide whether an external coverage dashboard is worth
   the extra service dependency.

Why first: these are the remaining local cleanup / structure tasks.
They reduce future risk and avoid burying unfinished core work under
another layer of features.

### Track 2. Strategic Programmes To Promote Next

Promote these only after the Track 1 list is reduced again. Some code
slices already exist, but the programmes should not be marked complete
until their acceptance bars are explicitly checked:

1. **Candidate C -- Data integrity programme.** Data contract,
   point-in-time / bitemporal availability, Security Master, corporate
   actions, market calendars and lineage.
2. **Candidate B -- Research honesty programme.** Degrees-of-freedom
   ledger, DSR / PBO style pressure checks, purged CV, robustness
   budget, mandatory benchmarks and graveyard / similarity checks.
3. **Candidate A -- Execution integrity programme.** Broker-event
   replay, reconciliation, order lifecycle state machine, realistic
   fills and TCA.
4. **Candidate F -- Portfolio optimisation and risk validation.**
   skfolio-style portfolio models, constraints, risk measures,
   transaction costs, stress tests and walk-forward / purged
   validation.
5. **Candidate E -- Strategy atlas and benchmark catalogue.** Curated
   map from strategy literature to Aurora support level, data
   requirements, implementation difficulty, validation risk and
   benchmark / graveyard status.
6. **Candidate D -- Strategy risk register.** Model-risk record,
   single-operator approval, lifecycle states and live-promotion
   refusal when evidence is stale.
7. **Candidate G -- Agentic research support.** QuantAgent-style
   multi-agent analysis, source-required reasoning, explanation packs
   and strict no-live / no-OOS authority boundaries.

Recommended order: C -> B -> A -> F -> E -> D -> G. Data truth comes
before research truth; research truth comes before live execution;
portfolio construction needs realistic costs; the strategy atlas is
useful only after validation rules can reject weak ideas; governance
should exist before autonomous-looking agents are allowed near
promotion decisions.

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

Status: in-repo prep complete (skeleton adapters + mock-friendly tests + first-slice plan in BLOCKERS.md); execution permanently external (per-feed credentials + provider terms). See [`BLOCKERS.md`](BLOCKERS.md#r2-real-alt-data-feeds).
Priority: medium
Effort: 1 week per feed (FRED is the recommended first slice)
Area: data/integrations

### R3. Compliance reporting endpoints (blocked)

Status: in-repo prep complete (skeleton modules + first-slice plan
for 13F in BLOCKERS.md); execution permanently external (legal
review + regulator credentials). See
[`BLOCKERS.md`](BLOCKERS.md#r3-compliance-reporting-endpoints).
Priority: medium-low until live execution is closer
Effort: 2 to 3 weeks plus legal review
Area: compliance

### R4. Real execution adapters (blocked)

Status: in-repo prep complete (broker adapters + triple-gate +
kill-switch + audit log + R100 trade simulator); execution
permanently external (funded broker accounts + per-venue
reconciliation). See
[`BLOCKERS.md`](BLOCKERS.md#r4-real-execution-adapters).
Priority: medium-low, high risk
Effort: 3 to 4 weeks for a serious first slice
Area: execution/live

### R5. GPU triage backend (gated)

Status: gate primitive landed in 2026-05-08 batch 12 (R40 benchmark scaffold under `examples/benchmarks/`); the gate "CPU benchmark proves a real bottleneck" can now be evaluated against the committed baseline. Until that bar is met, GPU work stays deferred. See [`BLOCKERS.md`](BLOCKERS.md#r5-gpu-triage-backend-gated).
Priority: low-medium
Effort: 1 week
Area: performance

### R6. Rust core engine (gated)

Status: gate primitive landed in 2026-05-08 batch 12 (R40 benchmark scaffold). Profile a representative end-to-end run via the four committed benchmarks; only if the top hot path beats Python + numba does the Rust extension justify the toolchain cost. Until the profile output points there, Rust stays deferred. See [`BLOCKERS.md`](BLOCKERS.md#r6-rust-core-engine-gated).
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
  repo top-level dir is still `Aurora`; the package itself is now
  `aurora` via `package-dir` remapping, with `aurora` kept as a
  compatibility shim).
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

### R22. Retire the legacy `aurora/data_cache_qf` ghost directory

Status: completed in follow-up
Evidence: `core/config.py`, `core/features.py`, `tests/test_config.py`,
`.gitignore` (entry retained as defence in depth)

The legacy default cache path `aurora/data_cache_qf/` was created
as a side effect of `DataConfig` and `FeatureStore` constructors using
that string as a hardcoded default. The empty top-level
`aurora/` directory it produced shadowed the real `aurora`
package on filesystems where Python's path resolution favoured the
on-disk subdirectory over the installed package, breaking the
pre-rename `python -m aurora.cli.forge` path and any subprocess
test that imported `aurora.cli`.

Fix:

- `core.config.DataConfig.cache_dir` now defaults to
  `runtime_paths.cache_dir()` via a `default_factory`. Honours
  `$QF_CACHE_DIR` / `$QF_DATA_DIR`; falls back to the platformdirs
  user-data dir.
- `core.features.FeatureStore.__init__(root=None)` resolves the same
  way; explicit `root=` callers are unchanged.
- `tests/test_config.py::test_default_config` updated to assert the
  new contract (`cfg.data.cache_dir == str(runtime_paths.cache_dir())`).
- The on-disk `aurora/` ghost directory was deleted.

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

### R23. Rename project from "Aurora" to "AURORA"

Status: completed in 2026-05-09 (commit `cf41bc2`). `pyproject.toml` `name = "aurora"`; package-dir map re-routes `aurora.*` to the on-disk dirs; CLI entry `aurora`; `forge` kept as deprecated alias. `aurora/__init__.py` shim re-exports aurora and emits `DeprecationWarning`. `core/env_compat.py::aurora_env(new, old)` reads `AU_*` first, falls back to `QF_*` with `DeprecationWarning`. Wheel builds as `aurora-1.5.0-py3-none-any.whl`. Verified: `import aurora` ok, `python -W error::DeprecationWarning -c "import aurora"` raises as designed, `aurora --version` -> `aurora 1.5.0`. 550 files touched; 3370 fast tests + 3 slow/integration green; ruff + mypy + sphinx + pre-commit all green. Per `docs/AURORA_RENAME_CHECKLIST.md`.
Priority: high
Effort: 1 to 2 weeks (touches every file that references the project)
Area: branding / packaging / docs

Decision: the project is renamed to **AURORA**. Same product, new
name. Pattern alignment with the existing strategy codenames (JADE,
NAOMI). Aurora = dawn / light / Latin classical female register.

Scope of change:

- `pyproject.toml`: `name = "aurora"`, scripts `aurora = "aurora.cli.forge:main"`,
  package list (`aurora.*`) and package-dir map.
- Repository top-level directory rename: `Aurora/` -> `Aurora/`.
- Package import path: `aurora.*` -> `aurora.*` across ~230 modules.
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
   `aurora` namespace for one release cycle, so external
   consumers (sp500_ls_v2, naomi, jade) do not break overnight.
3. Update CHANGELOG with the rename + the deprecation window for the
   shim.
4. Tag a release before the shim removal.

Definition of done:

- `import aurora` works; `import aurora` works AND emits a
  DeprecationWarning during the shim window.
- `aurora --version` returns the new package version.
- All 13 docs under `docs/` reference Aurora consistently.
- Tests green under the new import path.
- Wheel build produces `aurora-X.Y.Z-py3-none-any.whl`.

Risk note retained for history: the rename touched almost everything,
so future namespace cleanup should remain isolated from semantic fixes.

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

Status: placeholder set in 2026-05-08 batch (commit `678e0cb`);
R23 rename is complete, but the real canonical repository URL is still
an operator decision.
Priority: low
Effort: 5 minutes once decided
Area: docs / packaging

`docs/index.rst` no longer carries the `anthropics/aurora`
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

Status: completed in 2026-05-08 batch 17; evidence: `.github/workflows/docs.yml` builds Sphinx with `-W` (warnings as errors) on push to main and deploys to GitHub Pages via `actions/deploy-pages@v4`. Decision and rationale in `docs/DOCS_HOSTING.md`.
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

Status: completed 2026-05-10. Per-writer wiring landed: `compliance/soc2_audit.py`, `agent_gateway/audit.py`, `governance/approvals.py`, `research/auto_loop/loop.py`, `research/factory/factory.py`, `research/ledger.py`, `core/witness.py` all route appends through `aurora.core.audit_rotation.append_with_rotation` with `RotationPolicy.from_env()` honour for `AU_AUDIT_ROTATE_*` env vars. Hash chain preserved via `prior_chain_hash` rotation_anchor rows. Tests: `tests/test_audit_rotation.py` + `tests/test_audit_rotation_wiring.py` (5 tests).
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

R7 covered the backend interface and R19 wired successful freezes to
the backend mirror path. Neither addresses what to do if
`snapshots_index.sqlite` is corrupted or a parquet blob's hash no
longer matches its declared `sha256`. Write the recovery runbook plus
a `forge data repair` CLI helper that walks the blob directory,
recomputes hashes, and rebuilds the index from blobs whose content
matches their filename.

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

Status: completed 2026-05-10. CLI subcommands shipped under `forge research graveyard`: `list` / `show <strategy_id>` / `filter --reason --asset-class --since`. JSON output deterministic (sort_keys + sorted entries). Optional dashboard tile added in `reporting/daily_ops/_sections_meta.py::_section_graveyard` (opt-in via `DailyOpsConfig.include_graveyard=True`). Tests: `tests/test_cli_graveyard.py` (10 tests).
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

Status: procedure documented in 2026-05-08 batch 17; execution gated on a Linux/macOS/WSL host. Evidence: `docs/MUTATION_TESTING.md` "R41 -- First full sweep procedure" section. mutmut native-Windows is unsupported (upstream issue 397) so the actual sweep runs on a CI Linux runner; capture procedure + acceptance bar (>=85% kill rate) is recorded.
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

Status: completed 2026-05-10. Sweep migrated 43 ad-hoc tz idioms across 17 production files (agent_gateway/{gateway,tokens}, triage/engine, research/factory/{factory,outcomes}, core/{data_providers/*,data_layer,snapshots,realtime}, deployment/preflight, marketdata/{taq_reconstruction,auction_imbalance,dark_pool_prints}). Helper extended with `to_utc(Timestamp|Series)`, `to_utc_naive`, `utc_now_naive`, `ensure_utc`. Tests: `tests/test_timezone.py` + `tests/test_tz_helper_adoption.py` (13 tests).
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

Status: completed in 2026-05-08 batch (commit `8f98b26`); evidence: `docs/MODULE_STATUS.md`
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

Status: completed 2026-05-10. `cli/cmd_run.py` (1239 lines) split into
71-line shim re-exporting from 4 sibling modules:
`_cmd_run_analytical.py` (196), `_cmd_run_research.py` (503),
`_cmd_run_misc.py` (145), `_cmd_run_register.py` (313). Public surface
preserved at `aurora.cli.cmd_run`. All `cli/cmd_*.py` now ≤800 lines.
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

Status: completed structurally. `deployment/brokers.py` has been
replaced by the `deployment/brokers/` package with per-broker modules
and a public re-export surface. `deployment/brokers/base.py` is now 772
lines, below the project limit. Verification on 2026-05-09: ruff
passed, fast suite passed, package build passed, and wheel imports
passed. Future broker work belongs under R4 / Candidate A, not this
mechanical split.
Priority: medium
Effort: 2 to 3 days
Area: refactor
Suggested path: `deployment/brokers/`

Convert to a package: one file per broker (`paper.py`, `alpaca.py`,
`ib.py`, `coinbase.py`, `kraken.py`) plus a base `__init__.py` that
re-exports the public surface. Tests already partition by broker.

### R51. Split `reporting/tearsheet.py` (1313 lines)

Status: completed structurally. `reporting/tearsheet.py` has been
replaced by the `reporting/tearsheet/` package split by report section,
with the public render surface preserved. Verification on 2026-05-09:
ruff passed, fast suite passed, package build passed, and wheel imports
passed. Future reporting features belong to the reporting candidates,
not this mechanical split.
Priority: low
Effort: 2 days
Area: refactor

Split by section: hero header, metrics table, equity curves, drawdown
section, factor section, attribution section. Same exported entry
point; new internal modules do the rendering.

### R52. Split remaining oversized modules

Status: completed 2026-05-10. Splits landed:
`reporting/daily_ops/builder.py` 994 → 166-line module composing existing
`_PerfPanelsMixin` / `_MetaPanelsMixin` / `_AlertChecksMixin`.
`core/data_layer.py` 933 → 67-line shim + `_data_layer_constants.py` (114),
`_data_layer_oos_guard.py` (272), `_data_layer_loaders.py` (265). Earlier:
`analytics/metrics_full.py` → package, `research/factory/factory.py` →
package (split landed 2026-05-10), `deployment/preflight.py` → package.
Public surfaces preserved. All production files now ≤800 lines.
Priority: low
Effort: 1 day per file
Area: refactor

Production files still over 800 lines after the partial split:

- `reporting/daily_ops/builder.py` (900).
- `core/data_layer.py` (841).

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
- Infra DSNs: `AURORA_PG_DSN`, `AURORA_REDIS_URL`,
  `AURORA_TIMESCALE_DSN`, `AZURE_STORAGE_CONNECTION_STRING`.

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
  still describes an older nested `aurora/` package path, but the
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
`python -m mypy aurora/`, because the canonical package is now
`aurora` and the repo still uses the flat Layout B source layout).

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

R22 retired the `aurora/data_cache_qf` ghost dir; one or two
hardcoded paths slipped through. `dataeng/airflow_dags.py` was
flagged by the path audit. Sweep the remaining modules and route
every disk-write through `runtime_paths.cache_dir()` or the
appropriate `$QF_*` env var.

### R76. R23 sub-task: env var migration plan

Status: completed in 2026-05-09 alongside R23 (commit `cf41bc2`); evidence: `core/env_compat.py::aurora_env(new, old)` reads `AU_*` first, falls back to `QF_*` with `DeprecationWarning`. Migration table + shim window timeline live in `docs/ENV_VAR_MIGRATION_PLAN.md`. Active readers under `core/runtime_paths` and friends migrated; remaining `QF_*` env-var defaults inside per-component dataclasses (`AlertConfig`, `EncryptionConfig`, `TwoFactorConfig`, `PIIHandlerConfig`) are operator-overridable and intentionally left as the legacy default name during the shim window.
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
then filter through validation. Aurora today runs GA on existing
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
Suggested paths: `strategies/symphony.py` (consolidated), `deployment/allocator.py`

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
Suggested path: `strategies/symphony.py` (consolidated)

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
Suggested path: `strategies/symphony.py::SectorRotator` (consolidated)

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
Suggested paths: `strategies/rule_codegen.py`,
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

Status: completed 2026-05-10. Auto-loop integration: `research/auto_loop/loop.py::AutoResearchLoop.run_cycle()` runs `_evaluate_slas()` at step 0. Default action: archives expired strategies via `lifecycle.archive(sla)`. Opt-in via `AU_LIFECYCLE_REVALIDATE_ON_EXPIRY=1`: queue for revalidation instead. `CycleSummary` now reports `sla_evaluated`, `sla_archived`, `sla_revalidate_queued`. Tests: `tests/test_lifecycle_sla.py` + `tests/test_lifecycle_sla_auto_loop.py` (5 tests).
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

### R155. Free bulk daily market-data programme

Status: completed 2026-05-10 + integrated into main 2026-05-10 (see `docs/roadmap/R155_R158_INTEGRATION_REPORT.md`). Provider connectors under `core/data_providers/` with mock-friendly injectable HTTP clients (no live network in tests): `finance_database_universe.py`, `nasdaq_trader_universe.py`, `stooq_daily.py`, `yfinance_daily.py`, `yahooquery_daily.py`, `binance_public_data_daily.py`, `coingecko_daily.py`, `ccxt_daily.py`, `fred_daily.py`, `akshare_experimental_daily.py`, `fallback_chain.py`, `_free_bulk_common.py`. `ProviderRole` enum + `ProviderDescriptor` extend `DataProviderRegistry`. CLI subcommands: `aurora data universe fetch/diff`, `aurora data backfill daily`, `aurora data provider-status`, `aurora data coverage-report`. Storage via `data_contracts/timeseries_store` libraries `universe`/`prices_daily`/`crypto_daily`/`macro_daily`/`experimental_daily`. AKShare gated behind `AU_ENABLE_AKSHARE=1`. Tests: `tests/test_data_providers_free_bulk.py` (27 tests). Live network ops + per-provider hardening (auth flows, rate-limit calibration, vendor terms review) remain operator follow-up.
Priority: high
Effort: 2 to 4 weeks for first usable version; longer for full
provider hardening
Area: data / ingestion / provider registry
Source: 2026-05-09 provider review; checked against public docs,
GitHub repositories and live endpoint probes
Suggested paths: `core/data_providers/`, `data_contracts/`,
`cli/cmd_data.py`, `tests/test_data_providers_free_bulk.py`

Goal: give AURORA the largest practical free daily-market-data surface
without pretending that free data is institutional quality. The system
should maximise ticker coverage, but every downloaded dataset must pass
contracts, provenance, calendar checks and source-specific warnings
before it can feed backtests, GA, validation or research factory jobs.

Provider policy:

- Use `FinanceDatabase` as the broad global symbol universe source. It
  provides a large catalogue of equities, ETFs, funds, indices,
  currencies, cryptocurrencies and money-market symbols, but it is not
  a price source.
- Use `Nasdaq Trader` as the official current US listed-symbol source.
  It is useful for NASDAQ / NYSE / NYSE American style universe
  construction and for cross-checking active US symbols.
- Use `Stooq` as the preferred free daily OHLCV price source for broad
  public-market coverage where available. Live probing showed that some
  CSV download paths now require an API key / CAPTCHA flow, so the
  implementation must support a configured key and must fail with a
  clear operator message when unauthenticated downloads are blocked.
- Use `yfinance` / `yahooquery` only as fallback global providers.
  They are useful because Yahoo coverage is broad, but the interface is
  unofficial, fragile and suitable for personal / research use rather
  than production truth.
- Use `Binance Public Data` as the primary free crypto OHLCV source for
  Binance spot and futures. Prefer official ZIP archives for historical
  backfills and verify symbol / interval / checksum where available.
- Use `CoinGecko` for broad crypto universe metadata and non-Binance
  crypto coverage. Respect free-plan limits and record rate-limit /
  freshness warnings in provenance.
- Use `CCXT` as the optional multi-exchange crypto adapter for OHLCV
  where public exchange APIs permit it. Treat exchange-specific gaps,
  symbol formats and rate limits as first-class provider metadata.
- Use `FRED` for macro, rates, yields and economic series. These are
  not ticker prices, but they are important context features for
  strategy filters, regimes and risk reports.
- Use `AKShare` as an experimental Asia / China provider. It is useful
  for extra coverage, but should stay behind an explicit experimental
  provider flag until stability, licensing, data semantics and tests are
  reviewed.

Do not use these as the bulk free base:

- `Alpha Vantage` free tier: too few requests for large-scale daily
  ticker backfills.
- `EODHD` free tier: too few calls and too little free history for this
  goal.
- `Financial Modeling Prep` free tier: useful for small tests, not for
  mass historical ingestion.
- `Marketstack` free tier: too limited for the target use case.
- `OpenBB`: useful as a future integration layer, but not itself a
  free bulk historical-data source.

Implementation plan for another AI agent:

1. Add a `FreeBulkProviderRegistry` or extend the existing
   `DataProviderRegistry` with explicit provider roles: universe
   source, price source, crypto source, macro source and experimental
   source.
2. Add provider descriptors with licence / terms notes, rate-limit
   notes, auth requirements, supported asset classes, supported
   intervals, adjustment posture and reliability warning level.
3. Implement universe downloaders first:
   `finance_database_universe` and `nasdaq_trader_universe`.
   Output a normalised symbol table with provider symbol, canonical
   symbol, exchange, asset class, currency where available, active flag
   and source timestamp.
4. Implement daily OHLCV backfill providers in this order:
   `stooq_daily`, `yfinance_daily`, `yahooquery_daily`. Stooq should be
   tried first; Yahoo providers fill missing symbols and must mark
   themselves as unofficial fallback evidence.
5. Implement crypto providers:
   `binance_public_data_daily` for official ZIP archive backfills,
   `coingecko_daily` for broad crypto series / metadata, and
   `ccxt_daily` for optional exchange-specific OHLCV.
6. Implement `fred_daily` for macro / rates / yield series. Keep macro
   identifiers separate from tradeable tickers so strategies do not
   confuse context series with assets that can be bought.
7. Add `akshare_experimental_daily` behind an explicit opt-in flag such
   as `--experimental-provider akshare`; never include it silently in
   default production datasets.
8. Store raw downloads, normalised bars and provenance separately.
   Provenance must include provider name, provider URL / endpoint,
   retrieved_at, source timestamp if available, auth mode, provider
   version / package version, query parameters, row count, date range,
   symbol count and data-contract hash.
9. Run Candidate C data contracts before any snapshot is approved:
   required columns, monotonic dates, duplicate rows, zero / negative
   prices, impossible returns, missing bars, timezone policy, adjustment
   posture and calendar gaps.
10. Add provider fallback logic that records exactly what happened:
    source selected, sources rejected, missing symbols, symbols
    substituted, data differences and warnings. Never silently merge
    conflicting bars from multiple providers.
11. Add CLI commands:
    `aurora data universe fetch`,
    `aurora data universe diff`,
    `aurora data backfill daily`,
    `aurora data provider-status`,
    `aurora data coverage-report`.
12. Add a coverage report that answers in plain terms: how many
    symbols were requested, how many were found, how many have usable
    daily history, date-range coverage, provider split, failure reasons
    and warnings.

Acceptance criteria:

- AURORA can build a free global candidate universe from
  FinanceDatabase plus US-listed symbols from Nasdaq Trader.
- AURORA can backfill daily bars from Stooq where configured /
  available, then fallback to Yahoo-based providers with clear
  unofficial-source warnings.
- AURORA can ingest Binance daily crypto archives and FRED macro daily
  series through the same provenance and contract path.
- Every provider output is normalised into the same daily-bar schema:
  symbol, date, open, high, low, close, volume, currency where known,
  provider, adjusted/raw posture and retrieval metadata.
- No provider can write an approved snapshot unless the data contract
  passes or an audited operator exception is recorded.
- Tests use local fixtures and mocked HTTP responses. They must not
  depend on live network availability.
- Tests cover Stooq auth-required response, Nasdaq Trader symbol file,
  Yahoo fallback warning, Binance ZIP parsing, FRED macro series,
  duplicate dates, impossible prices, missing bars, provider mismatch
  and coverage-report counts.

Risk notes:

- Free data maximises coverage, not correctness. The whole point of
  this item is to get many symbols cheaply while making data weakness
  visible.
- Stooq is the best free bulk candidate, but automation can require an
  API key / CAPTCHA-derived download link. Treat that as an operator
  setup requirement, not a bug.
- Yahoo-based sources are broad but unofficial. They are acceptable for
  research fallback, not as silent production truth.
- Crypto coverage should prefer official exchange archives when
  possible because generic exchange APIs can revise, limit or throttle
  history.
- This item depends heavily on Candidate C. If the data-contract gate
  is weak, R155 will simply download bad evidence faster.

### R156. Complementary free provider programme

Status: completed 2026-05-10. All 8 providers shipped under `core/data_providers/`: openfigi_mapper.py, sec_edgar_companyfacts.py, dbnomics_macro.py, ecb_data_portal.py, coinmetrics_community.py, tiingo_daily.py (env-gated), dukascopy_fx_history.py (env-gated), marketdata_app_limited.py (env-gated). Eight new ProviderRole entries: IDENTITY_MAPPING, FUNDAMENTALS, MACRO_MULTI_SOURCE, CRYPTO_METRICS, FX_REFERENCE, OPTIONAL_PRICE_FALLBACK, FX_TICK_RESEARCH, OPTIONS_LIMITED. Default registry registers all eight as deferred scaffold stubs so `aurora data provider-status --include-complementary` lists them. CLI subcommands: `aurora data identity map`, `data fundamentals fetch`, `data macro search`, `data macro fetch`, `data crypto-metrics fetch`. SEC EDGAR carries point-in-time gate via `assert_pit_safe`/`filter_pit_safe`. Coin Metrics provenance always carries `community_non_commercial_licence` warning unless `AU_COINMETRICS_LICENCE_OVERRIDE=1`. Tests: `tests/test_openfigi_mapper.py` (12), `tests/test_sec_edgar_companyfacts.py` (16), `tests/test_dbnomics_macro.py` (10), `tests/test_ecb_data_portal.py` (10), `tests/test_coinmetrics_community.py` (9), `tests/test_tiingo_daily.py` (9), `tests/test_dukascopy_fx_history.py` (6), `tests/test_marketdata_app_limited.py` (9), `tests/test_cli_data_r156.py` (10) — 91 new tests, all green. Live network operations + per-provider hardening (auth flows, real .bi5 LZMA decompression for Dukascopy, vendor-terms review) remain operator follow-up.
Priority: high for SEC EDGAR / OpenFIGI / DBnomics / Coin Metrics;
medium for ECB / Tiingo; low-deferred for Dukascopy / MarketData.app
Effort: 2 to 4 weeks for the first four providers; 1 to 2 extra weeks
for the optional providers
Area: data / identity / fundamentals / macro / crypto / FX
Source: 2026-05-10 provider review; checked against public docs and
provider terms / limits where available
Suggested paths: `core/data_providers/`, `data_contracts/`,
`marketdata/`, `altdata/`, `cli/cmd_data.py`,
`tests/test_data_providers_complementary.py`

Goal: extend R155 with free providers that add missing evidence, not
just more OHLCV. R155 covers broad daily prices, universes, crypto
OHLCV and FRED macro. R156 should add official fundamentals, reliable
identifier mapping, wider macro, better crypto metrics and optional
FX/tick research data. Do not duplicate R155 with another pile of
thin price wrappers.

Providers to add:

- `sec_edgar_companyfacts`: official SEC EDGAR provider for U.S.
  company facts, XBRL concepts, submissions metadata and CIK / ticker
  mapping. Use the nightly bulk archives where possible:
  `companyfacts.zip` and `submissions.zip`. This is fundamentals and
  filings evidence, not OHLCV.
- `openfigi_mapper`: free identifier-mapping provider for FIGI, ticker,
  ISIN, CUSIP, SEDOL, exchange code and related metadata. This belongs
  in the Security Master / instrument identity layer, not the price
  layer.
- `dbnomics_macro`: free macro provider aggregating many public
  statistical sources. Use it as a broader macro complement to FRED.
  Preserve original provider, dataset code, series code and licence in
  provenance because DBnomics redistributes upstream data.
- `coinmetrics_community`: crypto metrics provider using the Community
  API. Treat it as non-commercial / community-licensed evidence for
  crypto network metrics, asset reference data and selected market
  data. It complements Binance and CoinGecko; it does not replace
  exchange-grade OHLCV.
- `ecb_data_portal`: official ECB provider for euro-area macro,
  interest rates and EUR FX reference rates through the ECB Data Portal
  / SDMX API. Add after DBnomics unless a strategy specifically needs
  ECB-native series.
- `tiingo_daily`: optional EOD fallback provider requiring an operator
  API token. Use for daily equities / ETFs / mutual funds / crypto
  where available. Do not make it a default bulk provider until free
  limits and terms are calibrated.
- `dukascopy_fx_history`: optional FX / tick / bars provider. Useful
  for intraday FX research, execution simulation and tick-derived bars.
  Defer if the current product focus remains daily equities.
- `marketdata_app_limited`: optional small-scope provider for delayed
  stocks / options with a free credit budget and one-year history. Use
  only for options experiments or smoke tests, not for mass ingestion.

Do not add as new providers for now:

- `Alpha Vantage`: 25 requests / day free tier is too small for
  AURORA's provider goals. Keep it out unless a future item wants a
  toy/demo provider.
- `EODHD free`: 20 requests / day and one-year free history are too
  limited for bulk research.
- `Financial Modeling Prep free`: useful for small demos, but not a
  strong free bulk source.
- `Marketstack`: broad marketing coverage, but the free plan is too
  small for AURORA's use case.
- `Twelve Data free`, `Polygon free`, `Finnhub free`: potentially
  useful for narrow experiments, but not better than the current R155
  stack plus R156 priorities.
- `Nasdaq Data Link`: keep as a reference / paid or mixed-free dataset
  discovery surface, not a default free provider.
- `Kaggle`: useful for manual experiments, not a reproducible provider
  unless a specific dataset licence and version pin are reviewed.

Implementation order:

1. Implement `openfigi_mapper` first because it improves every other
   provider by making symbols less ambiguous. Add bulk mapping,
   warning-vs-error handling, optional API key, rate-limit metadata and
   Security Master integration.
2. Implement `sec_edgar_companyfacts` second. Start with ticker/CIK
   mapping, submissions metadata and companyfacts bulk ZIP ingestion.
   Store facts with filing date, period, form, accession number,
   taxonomy tag, unit, value, frame and source URL.
3. Implement `dbnomics_macro` third. It should expose provider /
   dataset / series discovery plus series fetch. Store upstream
   provider and licence in provenance.
4. Implement `coinmetrics_community` fourth. Add asset discovery,
   reference-data fetch and selected community metrics. Store usage
   as community / non-commercial unless legal review says otherwise.
5. Implement `ecb_data_portal` after DBnomics if native ECB series
   are needed. Focus on EUR FX reference rates and policy / money
   market series first.
6. Implement `tiingo_daily` only after the default free stack is
   stable. Require `AU_TIINGO_API_TOKEN`; never silently assume a token
   exists.
7. Defer `dukascopy_fx_history` until AURORA has a clear FX / intraday
   testing need. If implemented, keep it out of daily-equity default
   workflows.
8. Defer `marketdata_app_limited` until options workflows need a cheap
   delayed-data smoke provider.

Data model requirements:

- Add provider roles if needed:
  `IDENTITY_MAPPING`, `FUNDAMENTALS`, `MACRO_MULTI_SOURCE`,
  `CRYPTO_METRICS`, `FX_REFERENCE`, `OPTIONAL_PRICE_FALLBACK`,
  `FX_TICK_RESEARCH`, `OPTIONS_LIMITED`.
- Every provider descriptor must include free-tier posture, auth
  requirement, rate-limit notes, licence / terms URL, default enabled
  flag and whether the provider may be used for production evidence.
- All outputs must carry provenance: provider, endpoint / URL, query
  params, retrieved_at, source timestamp, package version if any,
  licence note, auth mode, row count, date range and source-specific
  identifiers.
- SEC facts must be point-in-time aware. Strategies cannot use a fact
  before its filing / accepted / available timestamp.
- OpenFIGI mappings must preserve ambiguity: if multiple mappings are
  returned, store all candidates or require an explicit exchange /
  market filter. Never silently pick the first match.
- DBnomics and ECB series must be marked macro/context, not tradeable
  assets.
- Coin Metrics data must be labelled community / non-commercial unless
  operator configuration explicitly allows a different licence posture.

CLI additions:

- `aurora data identity map --source openfigi --symbol AAPL --exchange US`
- `aurora data fundamentals fetch --source sec-edgar --ticker AAPL`
- `aurora data macro search --source dbnomics --query inflation`
- `aurora data macro fetch --source ecb --series <series-key>`
- `aurora data crypto-metrics fetch --source coinmetrics --asset btc`
- `aurora data provider-status --include-complementary`

Acceptance criteria:

- OpenFIGI maps at least ticker + exchange to one or more candidate
  identifiers and preserves warnings / no-match responses.
- SEC EDGAR ingests ticker/CIK mapping and at least one companyfacts
  fixture with point-in-time metadata.
- DBnomics ingests one macro fixture with provider / dataset / series
  provenance.
- Coin Metrics ingests one asset reference fixture and one metrics
  fixture, with community licence warning.
- ECB ingests one EUR FX reference-rate fixture or SDMX fixture.
- Tiingo, Dukascopy and MarketData.app are either implemented behind
  explicit env-gated optional providers or left as documented deferred
  sub-items.
- No tests make live network calls. Use local fixtures and injected
  HTTP clients.
- Provider status clearly separates R155 bulk providers from R156
  complementary providers.
- Documentation explains in plain language what each source is good
  for and what it must not be used for.

Risk notes:

- More providers can make AURORA less trustworthy if they create silent
  conflicts. Add source comparison and warnings, not blind merging.
- SEC data is official but not simple. Facts can be amended, tagged
  inconsistently or reported under different units. Treat parsing as a
  data-contract problem.
- Identifier mapping is not truth by itself. OpenFIGI improves symbol
  hygiene, but exchange, currency, listing window and corporate actions
  still matter.
- Free crypto community data may be unsuitable for commercial use. Keep
  licence flags visible.
- Tiingo may be useful, but requiring a token means it should be an
  operator-configured fallback, not a default assumption.
- Dukascopy is valuable for FX / tick research, but adding it before
  AURORA needs intraday FX would create complexity without immediate
  payoff. Classic trap: more machinery, same coffee.

### R157. First real data ingestion and approved snapshot

Status: completed 2026-05-10. Manifest-driven first-dataset
orchestrator (`core/data_providers/first_dataset/` package: `_manifest`,
`_results`, `_walker`, `_persist`, `_freeze`, `_adapters`, `__init__`;
all ≤285 lines), contract-gated TimeSeriesStore persistence, and at
least one approved SnapshotStore freeze, all covered by 17 unit
tests with no live network.
Priority: high
Effort: 3 to 5 days for a small audited dataset; longer only if live
provider limits / auth flows fight back
Area: data / ingestion / snapshots / validation / reproducibility
Source: 2026-05-10 post-R155/R156 review. AURORA has provider
connectors, but local runtime inspection found zero approved snapshots
and no persisted OHLCV dataset.
Suggested paths: `cli/cmd_data.py`, `core/data_providers/`,
`data_contracts/timeseries_store.py`, `data_contracts/validator.py`,
`core/snapshots.py`, `tests/test_first_real_ingestion.py`,
`docs/FIRST_DATASET.md`

Why it matters: R155 and R156 prove AURORA can talk to many free
providers in a testable way. They do not prove AURORA has any real
local market history. The current runtime truth is still: no approved
snapshots, no persisted daily OHLCV cache, and only test / research
symbols such as `SPY`, `SPY_SYN` and `XYZ` appearing in logs. R157 is
the bridge from "provider layer exists" to "AURORA has fuel".

Scope decision:

- Start deliberately small. Do not attempt a global bulk download in
  this item.
- Use a canonical seed universe that exercises multiple provider roles
  without creating data sprawl.
- Prefer official / primary providers first, then fallbacks with loud
  provenance warnings.
- Persist data before using it. Printing fetched rows to the terminal
  is not a dataset.
- The first dataset is an operational smoke dataset, not production
  research truth.

Canonical seed universe:

- US ETFs / equities daily prices:
  `SPY`, `QQQ`, `DIA`, `IWM`, `TLT`, `GLD`, `AAPL`, `MSFT`.
- Crypto daily prices:
  `BTCUSDT`, `ETHUSDT` from Binance Public Data.
- Macro / rates context:
  `DGS10`, `T10Y2Y`, `UNRATE` from FRED if available through the
  configured macro provider; otherwise use one DBnomics or ECB fixture
  only after recording the fallback.
- Identity / fundamentals:
  OpenFIGI mapping for `SPY`, `AAPL`, `MSFT`; SEC EDGAR company facts
  for `AAPL` and `MSFT`.

Provider order:

1. For daily ETF/equity prices, try `stooq` first if configured and not
   blocked by API-key / CAPTCHA requirements.
2. If Stooq is blocked, use `yfinance_daily` or `yahooquery_daily` as
   fallback and mark the data as unofficial / community reliability.
3. For crypto, use `binance_public_data` first. Do not use CoinGecko
   as the primary OHLCV source for BTC/ETH if Binance archive data is
   available.
4. For macro, use `fred_macro` first for U.S. series. Use `dbnomics`
   or `ecb_data_portal` only as a clearly labelled macro-context
   fallback or complement.
5. For identity, use `openfigi_mapper`. Preserve ambiguity; do not
   silently select the first mapping if multiple instruments match.
6. For fundamentals, use `sec_edgar_companyfacts` with point-in-time
   metadata. Do not allow facts to be read before their available time.

Implementation steps:

1. Add a first-dataset manifest format, for example
   `config/first_dataset.yaml`, containing symbols, provider order,
   start/end date, frequency, asset class, expected storage library and
   whether fallbacks are allowed.
2. Add a CLI command such as:
   `aurora data bootstrap-first-dataset --manifest config/first_dataset.yaml`.
3. The command must fetch raw provider output, normalise it, validate it
   with data contracts, then write it to `timeseries_store` libraries:
   `prices_daily`, `crypto_daily`, `macro_daily`, `identity`,
   `fundamentals`.
4. Store raw-response metadata and normalised rows separately enough
   that provenance can answer: provider, URL / endpoint, retrieved_at,
   source timestamp, query params, auth mode, package version, row
   count, date range, warning flags and data-contract hash.
5. Add a coverage report:
   symbols requested, symbols fetched, symbols failed, provider used,
   fallback used, rows per symbol, date coverage, missing bars and
   warnings.
6. Freeze at least one approved snapshot from persisted local data,
   not from an ad-hoc network call. The snapshot index must move from
   zero rows to at least one row in a controlled test / local run.
7. Add a minimal strategy smoke run that loads `SPY` from the local
   persisted dataset and runs a simple moving-average or buy-and-hold
   backtest without calling any live provider.
8. Add `docs/FIRST_DATASET.md` explaining how to bootstrap, verify,
   inspect and delete / rebuild the first dataset.

Acceptance criteria:

- `aurora data provider-status --include-complementary` lists the
  providers needed for the first dataset and reports missing auth /
  env-gated providers clearly.
- The first-dataset command can run in dry-run mode and show exactly
  what it would fetch without writing data.
- The first-dataset command can run with mocked providers in tests and
  write deterministic rows into `timeseries_store`.
- The persisted dataset includes at least:
  one ETF/equity daily series, one crypto daily series, one macro
  series, one OpenFIGI identity mapping and one SEC EDGAR facts record.
- Data-contract validation runs before persistence is marked approved.
- No approved snapshot is created if prices contain duplicate dates,
  non-monotonic dates, zero / negative prices, impossible OHLC order,
  missing required fields or missing provenance.
- At least one approved snapshot is created from local persisted data
  in a controlled test path.
- A strategy smoke test proves AURORA can run from local persisted data
  without hitting the network.
- The coverage report explains failures in plain language.
- Live-network tests are optional and marked integration. Unit tests
  use fixtures / injected clients only.

Suggested commands for the operator:

```bash
aurora data provider-status --include-complementary
aurora data bootstrap-first-dataset --manifest config/first_dataset.yaml --dry-run
aurora data bootstrap-first-dataset --manifest config/first_dataset.yaml
aurora data coverage-report --dataset first
aurora data freeze --dataset first --symbol SPY
aurora run --symbol SPY --source snapshot --strategy ma_cross
```

Definition of done:

- `snapshots_index.sqlite` has at least one approved local snapshot for
  the first dataset after the operator command runs.
- The first dataset can be inspected and rebuilt without manual file
  surgery.
- `ruff` passes.
- Focused tests for R157 pass.
- The fast suite passes or any unrelated known failures are documented
  with exact file / test names.
- Documentation states which data came from official sources, which
  came from fallbacks, and which data is not production-grade.

Out of scope:

- Downloading every symbol from every provider.
- Deciding paid provider strategy.
- Running live trading from this dataset.
- Treating Yahoo fallback data as institutional truth.
- Solving all corporate actions and survivorship bias in one pass.

Risk notes:

- The danger is not failing to download data; the danger is downloading
  data and trusting it too much. Keep warnings visible.
- A tiny audited dataset is more valuable than a huge unverified one.
- If Stooq requires API-key / CAPTCHA setup, do not block R157. Use a
  labelled fallback and record the operator action needed for Stooq.
- If external providers change response formats, fail closed and keep
  the fixture-based tests deterministic.

### R158. Diversified seed universe and first real persisted dataset

Status: completed 2026-05-10. Diversified seed manifest with 10
sections (133 symbols) covering broad US ETFs, sector ETFs, large
caps, international ETFs, bonds, commodities, FX, crypto, macro and
SEC fundamentals. Adds trust levels, symbol normalisation, FX
section + `fx_daily` library, strict persistence gates, multi-symbol
freeze and a `manifest-summary` CLI; 16 unit tests + 4 smoke research
tests, all hermetic.
Priority: high
Effort: 3 to 7 days for the first usable version; longer only if live
provider limits, symbol mapping or auth flows fight back
Area: data / universe design / ingestion / validation / local evidence
Source: 2026-05-10 operator request after verifying that R157 created
the ingestion machinery but the local runtime still had zero persisted
timeseries rows and zero approved snapshots.
Suggested paths: `config/first_dataset.yaml`,
`config/diversified_seed_dataset.yaml`,
`core/data_providers/first_dataset/`, `cli/cmd_data.py`,
`data_contracts/timeseries_store.py`, `data_contracts/validator.py`,
`data_contracts/security_master.py`, `docs/FIRST_DATASET.md`,
`tests/test_first_real_ingestion.py`

Goal: turn R157 from a small smoke dataset into a genuinely useful
free seed universe. The result should be broad enough to test market
regimes, sector rotation, risk-off/risk-on behaviour, bonds,
commodities, FX, crypto, macro filters and basic fundamentals, while
remaining small enough that a human can inspect failures.

Core design decision:

- Do not start by downloading "everything". Start with a diversified
  canonical universe of roughly 90 symbols / series.
- Keep this as a seed universe, not as production truth.
- Prefer boring, liquid and recognisable assets over exotic coverage.
- Every symbol must declare its asset group, intended provider chain,
  storage library, expected fields, fallback policy and trust warning.
- The command must produce a local evidence report saying what was
  actually downloaded. A manifest alone is not evidence.
- AURORA must distinguish requested symbols from persisted symbols.
  This is the main lesson from R157.

Recommended manifest structure:

```yaml
name: diversified_seed
start: "2015-01-01"
end: null
frequency: "1d"
sections:
  us_market:
    library: prices_daily
    symbols: [...]
    providers: [stooq, yfinance_daily, yahooquery_daily]
    allow_fallback: true
    trust_level: research_seed
  us_sectors:
    library: prices_daily
    symbols: [...]
    providers: [stooq, yfinance_daily, yahooquery_daily]
    allow_fallback: true
    trust_level: research_seed
  us_large_caps:
    library: prices_daily
    symbols: [...]
    providers: [stooq, yfinance_daily, yahooquery_daily]
    allow_fallback: true
    trust_level: research_seed
  international:
    library: prices_daily
    symbols: [...]
    providers: [stooq, yfinance_daily, yahooquery_daily]
    allow_fallback: true
    trust_level: research_seed
  bonds_rates_etfs:
    library: prices_daily
    symbols: [...]
    providers: [stooq, yfinance_daily, yahooquery_daily]
    allow_fallback: true
    trust_level: research_seed
  commodities:
    library: prices_daily
    symbols: [...]
    providers: [stooq, yfinance_daily, yahooquery_daily]
    allow_fallback: true
    trust_level: research_seed
  fx:
    library: fx_daily
    symbols: [...]
    providers: [stooq, yahooquery_daily, dukascopy_fx_history]
    allow_fallback: true
    trust_level: reference_seed
  crypto:
    library: crypto_daily
    symbols: [...]
    providers: [binance_public_data, ccxt_daily, coingecko_daily]
    allow_fallback: true
    trust_level: research_seed
  macro:
    library: macro_daily
    symbols: [...]
    providers: [fred_macro, dbnomics_macro, ecb_data_portal]
    allow_fallback: true
    trust_level: context_seed
  fundamentals:
    library: fundamentals
    symbols: [...]
    providers: [sec_edgar_companyfacts]
    allow_fallback: false
    trust_level: official_pit
```

Canonical diversified seed universe:

1. Broad US market ETFs:
   `SPY`, `QQQ`, `DIA`, `IWM`, `VTI`, `RSP`.

2. US sector ETFs:
   `XLE`, `XLF`, `XLK`, `XLV`, `XLI`, `XLY`, `XLP`, `XLU`,
   `XLB`, `XLRE`, `XLC`.

3. US large caps:
   `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`,
   `BRK-B`, `JPM`, `V`, `MA`, `UNH`, `LLY`, `XOM`, `CVX`,
   `WMT`, `COST`, `HD`, `PG`, `KO`, `PEP`, `MCD`, `JNJ`,
   `PFE`, `AVGO`, `AMD`, `NFLX`, `ADBE`, `CRM`, `ORCL`.

4. International ETFs:
   `EFA`, `EEM`, `VEA`, `VWO`, `EWJ`, `EWU`, `EWG`, `EWQ`,
   `EWC`, `EWA`, `INDA`, `FXI`, `MCHI`, `EWZ`, `EWW`.

5. Bonds and rates ETFs:
   `TLT`, `IEF`, `SHY`, `BIL`, `HYG`, `LQD`, `TIP`, `AGG`,
   `BND`.

6. Commodities:
   `GLD`, `SLV`, `USO`, `UNG`, `DBC`, `DBA`, `CPER`, `PPLT`,
   `PALL`.

7. FX references:
   `EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `USDCAD`, `AUDUSD`,
   `NZDUSD`, `DXY`.

8. Crypto:
   `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`,
   `ADAUSDT`, `DOGEUSDT`, `LINKUSDT`, `AVAXUSDT`, `DOTUSDT`.

9. Macro / rates / risk context:
   `DGS1`, `DGS2`, `DGS5`, `DGS10`, `DGS30`, `T10Y2Y`,
   `T10Y3M`, `FEDFUNDS`, `SOFR`, `UNRATE`, `CPIAUCSL`,
   `CORESTICKM159SFRBATL`, `PAYEMS`, `VIXCLS`, `BAMLH0A0HYM2`.

10. SEC fundamentals:
    `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `META`, `TSLA`,
    `BRK-B`, `JPM`, `V`, `UNH`, `LLY`, `XOM`, `WMT`, `COST`,
    `PG`, `JNJ`, `AVGO`, `AMD`, `NFLX`.

Fundamental fields to attempt:

- revenue
- net_income
- operating_income
- free_cash_flow
- total_assets
- total_liabilities
- shareholders_equity
- shares_outstanding
- eps
- gross_margin
- operating_margin
- return_on_equity
- debt_to_equity

Implementation plan for another AI agent:

1. Add `config/diversified_seed_dataset.yaml`.
   Keep `config/first_dataset.yaml` as the tiny smoke manifest from
   R157. Do not overwrite it unless the docs say both manifests are
   intentionally merged.

2. Extend the first-dataset manifest parser only if needed.
   It must support:
   section name, symbols, providers, library, allow_fallback, start,
   end, frequency, trust_level, asset_group, expected_fields and
   notes.

3. Add a plain inspection command:
   `aurora data manifest-summary --manifest config/diversified_seed_dataset.yaml`.
   It should print requested symbols by section and total requested
   count. This avoids confusing "planned" with "downloaded".

4. Reuse the R157 bootstrap path:
   `aurora data bootstrap-first-dataset --manifest config/diversified_seed_dataset.yaml`.
   If the current command name is too specific to `first`, rename or
   alias it to a more general command such as
   `aurora data bootstrap-manifest`, while keeping the old command as a
   compatibility alias.

5. Add per-section provider adapters where gaps exist:
   equities / ETFs through Stooq first, then yfinance/yahooquery;
   crypto through Binance Public Data first, then CCXT/CoinGecko;
   macro through FRED first, then DBnomics/ECB; fundamentals through
   SEC EDGAR only.

6. Add a symbol-normalisation layer for provider-specific symbols.
   Examples:
   `BRK-B` may need provider-specific spelling.
   FX pairs may need `EURUSD`, `EURUSD=X`, `EUR/USD` or Stooq-specific
   names depending on provider.
   `DXY` may be an index, ETF proxy or provider-specific symbol.
   The mapping must be explicit and recorded in provenance.

7. Add a `requested_vs_persisted` report.
   It must include:
   requested symbols, attempted symbols, persisted symbols, failed
   symbols, selected provider, rejected providers, fallback used,
   row count, first date, last date, warnings, contract errors and
   local storage path / content hash.

8. Persist successful data to TimeSeriesStore libraries:
   `prices_daily`, `crypto_daily`, `macro_daily`, `fx_daily`,
   `fundamentals`, and `identity` if identifier mapping is included.

9. Apply strict data-contract gates before marking any symbol usable:
   required columns, date monotonicity, duplicate dates, impossible
   OHLC order, zero / negative prices, empty frames, missing
   provenance, extreme return spikes, timezone policy, calendar gaps
   and adjustment posture.

10. Freeze approved snapshots only after persistence.
    Add support for freezing a whole manifest or at least freezing one
    symbol per major section:
    `SPY`, `QQQ`, `TLT`, `GLD`, `EFA`, `BTCUSDT`, `DGS10`.

11. Add a smoke research run from local data only:
    one broad-market test on `SPY`, one sector-relative test using
    `XLK` versus `XLF`, one risk-regime test using `SPY`, `TLT`,
    `DGS10` and `VIXCLS`, and one crypto test using `BTCUSDT`.
    These tests are not to prove alpha. They prove the dataset is
    actually usable by AURORA without live network calls.

12. Update `docs/FIRST_DATASET.md` or add
    `docs/DIVERSIFIED_SEED_DATASET.md`.
    The doc must explain:
    what is requested, what was downloaded, how to rebuild it, how to
    delete it, which providers were used, which fallbacks are unofficial
    and why this dataset is not institutional truth.

13. Add tests with injected clients / fixtures.
    Unit tests must not use live network. Live download tests may exist
    only as integration tests and must be opt-in.

Suggested operator commands:

```bash
aurora data provider-status --include-complementary
aurora data manifest-summary --manifest config/diversified_seed_dataset.yaml
aurora data bootstrap-first-dataset --manifest config/diversified_seed_dataset.yaml --dry-run
aurora data bootstrap-first-dataset --manifest config/diversified_seed_dataset.yaml
aurora data coverage-report --dataset diversified_seed
aurora data freeze --dataset diversified_seed --symbol SPY --library prices_daily
aurora data freeze --dataset diversified_seed --symbol BTCUSDT --library crypto_daily
aurora data freeze --dataset diversified_seed --symbol DGS10 --library macro_daily
```

Acceptance criteria:

- The repo contains a diversified seed manifest with the sections and
  symbols listed above, or a documented smaller subset if a provider
  limitation blocks live ingestion.
- The system can tell the user, in plain language, the difference
  between requested symbols and actually persisted symbols.
- A dry run shows provider order, fallback policy and expected storage
  library without writing files.
- A mocked-provider test persists at least one successful symbol per
  major section:
  US market, sectors, large caps, international, bonds, commodities,
  FX, crypto, macro and fundamentals.
- A real operator run writes at least:
  20 daily price series, 2 crypto daily series, 5 macro series and 5
  fundamentals records, unless external providers block the run. Any
  block must be reported with exact provider and reason.
- The coverage report names failures by symbol and reason. "Failed" is
  not enough.
- Fallback data is labelled. Yahoo-based data must never appear as
  official institutional truth.
- At least three approved snapshots are created from local persisted
  data:
  one equity / ETF snapshot, one crypto snapshot and one macro
  snapshot.
- The local runtime check after the run shows non-zero rows in
  `timeseries_index.sqlite` and non-zero rows in
  `snapshots_index.sqlite`.
- A local-data-only smoke run proves the data can feed AURORA without
  hitting live providers.
- `ruff` passes.
- Focused R158 tests pass.
- The fast suite passes or unrelated known failures are documented with
  exact test names.

Out of scope:

- Downloading thousands of symbols.
- Building a survivorship-free institutional equity master.
- Claiming corporate-action completeness.
- Treating free provider data as live-trading grade.
- Adding paid providers.
- Optimising strategies from this dataset before the data report is
  inspected.

Risk notes:

- The biggest risk is silent false confidence. The output must say
  exactly what exists locally.
- FX and index symbols are provider-fragile. Build explicit mappings
  instead of guessing.
- `BRK-B` and other special symbols often differ by provider. Test
  those paths directly.
- Macro series are context data, not tradeable tickers. Keep their
  library separate from prices.
- Fundamentals must keep point-in-time availability metadata. A fact
  reported later must not be visible earlier.
- If live providers block access, do not fake success. Persist nothing,
  write the failure report and leave clear operator instructions.

### R159. Instrument Master and symbol identity layer

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 1 to 2 weeks
Area: data / identity / security master / symbol hygiene
Source: post-R158 data trust review. A diversified dataset is not safe
until every ticker is tied to a real instrument identity.
Suggested paths: `data_contracts/security_master.py`,
`core/data_providers/openfigi_mapper.py`,
`core/data_providers/nasdaq_trader_universe.py`,
`core/data_providers/finance_database_universe.py`,
`data_contracts/timeseries_store.py`, `cli/cmd_data.py`,
`tests/test_security_master.py`

Goal: make AURORA understand what each symbol actually represents.
`AAPL` is not just a string. It is a listed equity, on an exchange, in
a currency, with identifiers, sector metadata, listing dates and
provider-specific aliases.

Why this comes first: almost every later data-quality check depends on
knowing the asset identity. Without this, corporate actions,
fundamentals, calendar rules, provider fallbacks and delisting checks
can silently attach to the wrong thing.

Implementation plan:

1. Define a canonical `InstrumentRecord` model with:
   canonical_symbol, provider_symbol, asset_class, exchange, country,
   currency, company_name, sector, industry, CIK, FIGI, ISIN, CUSIP
   where available, active flag, first_seen, last_seen, listing_start,
   listing_end and source provenance.
2. Add explicit alias mapping for provider-specific symbols.
   Examples: `BRK-B`, `BRK.B`, Yahoo-specific suffixes, Stooq-specific
   suffixes, FX pair spellings and index proxy symbols.
3. Create `aurora data identity build` from FinanceDatabase, Nasdaq
   Trader, OpenFIGI and SEC CIK mapping where available.
4. Create `aurora data identity resolve SYMBOL` so operators can see
   the exact identity AURORA will use before downloading prices or
   fundamentals.
5. Refuse ambiguous automatic mapping unless the manifest provides an
   explicit override.
6. Store identity records in TimeSeriesStore or a dedicated lightweight
   identity store with content hash and provider provenance.
7. Wire R158 bootstrap so every persisted symbol links to one identity
   record or carries a loud `identity_unresolved` warning.

Acceptance criteria:

- R158 symbols resolve to identity records or explicit unresolved
  warnings.
- `BRK-B` and at least one FX pair have provider-specific mapping tests.
- Identity records include provenance, retrieval time and source.
- Ambiguous OpenFIGI results do not silently choose the first match.
- Coverage report shows identity status per symbol.
- Unit tests use fixtures, not live provider calls.

### R160. Corporate actions and market calendars layer

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 2 to 4 weeks
Area: data / corporate actions / calendars / survivorship controls
Source: post-R158 data trust review. Price history without corporate
actions and calendars can make backtests look correct while being
structurally wrong.
Suggested paths: `data_contracts/corporate_actions.py`,
`data_contracts/calendars.py`, `data_contracts/security_master.py`,
`data_contracts/validator.py`, `core/snapshots.py`,
`tests/test_marketdata_corporate_actions.py`, `tests/test_calendars.py`

Goal: attach real-world trading context to each stored price series:
splits, dividends, ticker changes, delistings, holidays, early closes
and asset-specific trading sessions.

Implementation plan:

1. Extend corporate-action models to cover at least:
   split, reverse split, cash dividend, special dividend, ticker change,
   merger, spin-off, delisting and trading suspension.
2. Store action date, announcement date if known, effective date,
   available time, source, adjustment factor and affected instrument id.
3. Add market-calendar records by asset group:
   NYSE-style equities, ETF calendar, FRED macro calendar, crypto
   always-on calendar and FX weekday calendar.
4. Validate daily price series against their calendar:
   expected sessions, allowed missing sessions, holiday gaps, duplicate
   sessions and weekend bars.
5. Add an adjustment-status field to price provenance:
   raw, split-adjusted, dividend-adjusted, total-return or unknown.
6. Block approved snapshots when adjustment status is unknown for
   equities / ETFs unless the manifest explicitly marks the series as
   reference-only.
7. Add a `corporate-actions report` command that explains which events
   were found and whether the price series appears compatible with them.

Acceptance criteria:

- At least one split and one dividend fixture are validated end to end.
- Calendar validation distinguishes closed-market gaps from missing
  data.
- Crypto daily data is not falsely flagged for weekend sessions.
- Equity data with unknown adjustment posture cannot become approved
  production truth.
- Snapshot provenance records calendar id and adjustment posture.

### R161. Data quality score, quarantine and coverage dashboard

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: very high
Effort: 1 to 2 weeks
Area: data / validation / dashboard / quarantine
Source: post-R158 data trust review. The system must tell the operator
which downloaded data is usable, suspicious or rejected.
Suggested paths: `data_contracts/validator.py`,
`data_contracts/timeseries_store.py`,
`core/data_providers/first_dataset/_results.py`, `cli/cmd_data.py`,
`reporting/daily_ops/`, `tests/test_data_contracts.py`

Goal: every downloaded symbol gets a visible quality decision:
approved, warning, quarantined or rejected.

Implementation plan:

1. Define a `DataQualityReport` model with row count, date range,
   missing sessions, duplicate dates, non-monotonic dates, impossible
   OHLC, zero / negative prices, extreme returns, volume anomalies,
   provider fallback, cross-provider disagreement and provenance
   completeness.
2. Convert validator output into a numeric score plus plain-language
   reasons. Do not hide hard failures behind a score.
3. Add quarantine metadata to stored timeseries records. Quarantined
   data may be inspected but cannot feed GA, validation, promotion or
   approved snapshots.
4. Add `aurora data quality-report --dataset NAME`.
5. Add `aurora data quarantine --library LIB --symbol SYMBOL --reason TEXT`.
6. Add `aurora data approve --library LIB --symbol SYMBOL --version VERSION`
   gated by successful validation.
7. Show quality status in daily ops reporting.

Acceptance criteria:

- Bad fixtures are rejected for duplicate dates, impossible OHLC and
  missing provenance.
- Warning fixtures can persist but are labelled warning-only.
- Quarantined series cannot be frozen into approved snapshots.
- Coverage report separates requested, persisted, approved,
  quarantined and rejected.
- The user can see why a symbol failed without reading logs.

### R162. Point-in-time fundamentals dataset

Status: open
Priority: high
Effort: 2 to 4 weeks
Area: data / fundamentals / point-in-time / SEC
Source: post-R158 data trust review. Fundamentals are valuable only if
AURORA knows when the market could have known them.
Suggested paths: `core/data_providers/sec_edgar_companyfacts.py`,
`data_contracts/timeseries_store.py`, `data_contracts/validator.py`,
`validation/`, `tests/test_sec_edgar_companyfacts.py`

Goal: ingest basic SEC company facts with point-in-time availability,
not just final reported numbers.

Implementation plan:

1. Define a normalised fundamentals schema:
   company id, canonical symbol, CIK, fiscal period, period end,
   filing date, accepted timestamp, available time, tag, unit, value,
   source filing id and amendment flag.
2. Build a curated first field map:
   revenue, net income, operating income, free cash flow, total assets,
   total liabilities, equity, shares outstanding, EPS, gross margin,
   operating margin, ROE and debt-to-equity.
3. Store raw SEC facts separately from derived ratios.
4. Derive ratios only from facts whose available time is at or before
   the decision time.
5. Add a point-in-time read API:
   `fundamentals_at(symbol, decision_time)`.
6. Add tests proving future filings are invisible before their accepted
   timestamp.
7. Add coverage output for missing tags, inconsistent units and
   restated / amended facts.

Acceptance criteria:

- At least five R158 large caps have persisted fundamentals fixtures.
- A future filing cannot leak into an earlier strategy date.
- Derived ratios record which raw facts produced them.
- Missing fields are reported as missing, not filled with fake zeros.
- Fundamentals carry SEC provenance and point-in-time metadata.

### R163. Liquidity, cost and capacity dataset

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 2 to 3 weeks
Area: data / execution realism / capacity / costs
Source: post-R158 data trust review plus existing R125-R133 cost and
capacity primitives.
Suggested paths: `core/spread_model.py`, `core/slippage_calibration.py`,
`analytics/capacity.py`, `deployment/dynamic_caps.py`,
`data_contracts/timeseries_store.py`, `validation/robustness_suite.py`

Goal: give every tradable symbol practical trading constraints:
volume, estimated spread, estimated slippage, expected impact and
capacity warnings.

Implementation plan:

1. Compute rolling ADV, dollar volume, volatility and turnover from
   persisted daily prices.
2. Estimate a default spread proxy for assets without direct spread
   data. Record it as estimated, not observed.
3. Use existing cost / slippage / capacity primitives to produce
   capacity bands by symbol.
4. Add optional observed cost inputs later from broker fills or TCA.
5. Store liquidity features in a separate library such as
   `liquidity_daily`.
6. Add validation gates:
   reject strategies whose average order size exceeds configured ADV
   participation, whose capacity-adjusted Sharpe collapses or whose
   turnover makes costs dominate gross edge.
7. Add a `aurora data liquidity-report --dataset NAME` command.

Acceptance criteria:

- R158 price data produces liquidity records for ETFs / equities.
- Thin or low-volume symbols are flagged.
- Strategies can request capacity-adjusted metrics.
- Estimated spread / slippage is labelled as estimated.
- No strategy promotion may ignore liquidity warnings without an
  explicit override in the audit log.

### R164. Mandatory benchmark comparison pack

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 1 to 2 weeks
Area: validation / reporting / anti-self-deception
Source: post-R158 data trust review. Strategy metrics are weak without
simple comparison baselines.
Suggested paths: `research/strategy_benchmarks.py`,
`validation/pipeline.py`, `reporting/`, `tests/test_random_baseline.py`

Goal: every strategy report must compare against simple baselines
before it can be promoted.

Mandatory baseline set:

- cash
- buy and hold on the main asset
- equal weight where a basket exists
- 60/40 proxy for equity / bond strategies
- simple momentum
- simple mean reversion
- random entries with comparable turnover
- previous approved production version where available

Implementation plan:

1. Add a `BenchmarkPack` model and deterministic runner.
2. Wire it into ValidationPipeline as a required reporting gate.
3. Store benchmark result hashes alongside validation reports.
4. Add a plain-language result:
   beats baseline, ties baseline, fails baseline or inconclusive.
5. Require an explicit justification when promoting a strategy that
   does not beat the relevant naive baseline.

Acceptance criteria:

- A strategy validation report cannot omit benchmark results.
- Random baseline uses fixed seeds and records the seed.
- Reports show absolute metrics and excess-over-benchmark metrics.
- Promotion gate can block strategies that fail required baselines.

### R165. Research degrees-of-freedom ledger enforcement

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: very high
Effort: 2 to 3 weeks
Area: research / audit / anti-overfit / governance
Source: Candidate B promoted after R158. AURORA already has research
ledger pieces, but the ledger must become mandatory for generated,
tested and rejected ideas.
Suggested paths: `research/ledger.py`, `research/factory/`,
`research/auto_loop/`, `ga/`, `validation/`, `tests/test_research_factory.py`

Goal: record the true amount of searching AURORA did before showing a
winner.

Implementation plan:

1. Define required ledger events:
   universe selected, provider set, date range, feature set, parameter
   grid, random seed, generated candidate, rejected candidate,
   modified candidate, validation run, override, OOS unlock, promotion
   and retirement.
2. Add a `trial_pressure_score` based on number of candidates,
   parameter choices, filters, data revisions and rejected variants.
3. Wire GA, research factory and auto-loop so a candidate cannot reach
   validation without a ledger trail.
4. Add graveyard linkage so rejected strategies are searchable and not
   rediscovered as "new".
5. Add report text that says how much search pressure preceded the
   chosen result.
6. Keep the ledger append-only and hash-linked where practical.

Acceptance criteria:

- Generated candidates create ledger events automatically.
- Rejected candidates are counted, not discarded silently.
- Validation reports include trial pressure.
- Promotion is blocked if required ledger events are missing.
- OOS unlock events are recorded with actor, reason and timestamp.

### R166. Reproducible evidence pack for datasets and strategies

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 2 to 3 weeks
Area: reporting / reproducibility / audit / export
Source: post-R158 data trust review. AURORA should be able to explain
exactly what data and decisions produced a result.
Suggested paths: `reporting/`, `data_contracts/lineage.py`,
`data_contracts/lineage_producer.py`, `core/witness.py`,
`research/bundle.py`, `core/snapshots.py`

Goal: produce a self-contained evidence pack for a dataset, snapshot or
strategy validation.

Evidence pack contents:

- manifest used
- requested versus persisted report
- provider provenance
- data-contract results
- quality / quarantine decisions
- identity records
- corporate-action and calendar status
- snapshots and content hashes
- policy hash
- validation report
- benchmark pack
- research ledger excerpt
- warnings and manual overrides
- exact commands to reproduce

Implementation plan:

1. Add `aurora report evidence-pack --dataset NAME` and
   `aurora report evidence-pack --validation VALIDATION_ID`.
2. Export JSON plus human-readable HTML or Markdown.
3. Include hashes for every included artefact.
4. Add `aurora report reproduce --evidence-pack PATH` as a verification
   command that checks hashes and reruns lightweight validations.
5. Keep large raw data out of the report by default, but include
   content hashes and storage locations.

Acceptance criteria:

- Evidence pack generation works for the diversified seed dataset.
- Hash verification fails if an included artefact changes.
- A human can read the pack and see what data was trusted, rejected or
  warned.
- Strategy evidence pack includes benchmarks and ledger pressure.
- The pack is deterministic enough for tests to compare stable fields.

### R167. Incremental data refresh, versioning and diff

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: very high
Effort: 2 to 4 weeks
Area: data / refresh / versioning / reproducibility
Source: post-R158 improvement. Downloading once is not enough;
providers revise histories, add bars, remove rows and change formats.
Suggested paths: `data_contracts/timeseries_store.py`,
`core/data_providers/first_dataset/`, `cli/cmd_data.py`,
`core/universe_gate.py`, `validation/pipeline.py`

Goal: make data updates explicit and auditable. AURORA must know what
changed between yesterday's dataset and today's dataset.

Implementation plan:

1. Add `aurora data refresh --manifest PATH` to fetch only the needed
   incremental range where possible.
2. Add `aurora data diff --library LIB --symbol SYMBOL --old OLD --new NEW`.
3. Detect:
   new rows, removed rows, changed historical rows, changed metadata,
   changed provider, changed adjustment posture, changed quality score
   and changed content hash.
4. Add dataset-level diff summaries:
   symbols added, symbols removed, symbols changed, symbols unchanged,
   symbols newly quarantined and symbols newly approved.
5. Mark affected snapshots and validation reports as stale when their
   underlying data changes.
6. Add `aurora data stale-report` to list strategies / reports that
   should be rerun after data refresh.
7. Keep old versions readable. Never overwrite historical versions
   without an explicit replace flag and audit record.

Acceptance criteria:

- A second fetch of the same fixture creates either no new version or a
  version marked unchanged.
- A changed historical bar is detected and reported.
- A new bar extends the date range and updates coverage.
- Changed data marks dependent snapshots / validations as stale.
- Old versions remain loadable.
- Diff output is readable in table and JSON forms.

Recommended execution order for R159-R167:

1. R159 identity.
2. R161 quality / quarantine.
3. R167 refresh / diff.
4. R160 corporate actions / calendars.
5. R162 point-in-time fundamentals.
6. R163 liquidity / costs / capacity.
7. R164 benchmarks.
8. R165 research ledger enforcement.
9. R166 evidence packs.

Reason: first know what each asset is, then decide whether downloaded
data is usable, then make updates auditable. Only after that does it
make sense to build richer fundamentals, execution realism, benchmark
gates, ledger pressure and evidence packaging.

### R168. Canonical execution event schema and order state machine

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 1 to 2 weeks
Area: execution / broker events / replay foundation
Source: Candidate A promoted after R159-R167 planning. HFT lecture
notes, NautilusTrader, LEAN and FIX-style order-state references all
point to the same need: broker activity must be represented as events,
not as ad-hoc status strings.
Suggested paths: `execution/events.py`, `execution/order_state.py`,
`deployment/brokers/`, `deployment/brokers/base.py`,
`tests/test_paper_events.py`, `tests/test_execution_reconnect_reject.py`

Goal: define one canonical event language for order lifecycle events
so paper, backtest and live adapters can be compared and replayed.

Event types to model:

- order created
- submitted
- broker acknowledged
- partially filled
- filled
- cancel requested
- cancelled
- replace requested
- replaced
- rejected
- expired
- commission / fee
- financing / borrow fee
- position update
- cash update
- margin update
- reconnect / disconnect
- unknown external fill

State machine:

- created
- submitted
- acknowledged
- partially filled
- filled
- cancel pending
- cancelled
- replace pending
- replaced
- rejected
- expired
- unknown
- reconciled

Implementation plan:

1. Add immutable `ExecutionEvent` and `OrderStateTransition` models.
2. Add a deterministic state reducer:
   `reduce_order_state(current_state, event)`.
3. Validate impossible transitions. Example: filled order cannot later
   become submitted again.
4. Allow duplicate broker events to be recognised and ignored when
   their event id and payload match.
5. Preserve out-of-order events in a warning stream rather than
   silently discarding them.
6. Wire the paper broker first. Real adapters can follow later.
7. Add JSON serialisation with stable field ordering for audit logs.

Acceptance criteria:

- Paper broker emits canonical execution events.
- State reducer handles partial fill, cancel pending, reject, replace
  reject, duplicate event and out-of-order event fixtures.
- Event logs are deterministic and hashable.
- Unknown external fills are represented instead of crashing the
  replay path.

### R169. Execution replay and broker reconciliation engine

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 2 to 4 weeks
Area: execution / reconciliation / paper-live parity
Source: Candidate A promoted. R168 provides the event language; R169
uses it to rebuild session state and compare it with broker / engine
state.
Suggested paths: `execution/replay.py`, `execution/reconciliation.py`,
`execution/reconciliation_driver.py`, `deployment/brokers/`,
`reporting/daily_ops/`, `tests/test_reconciliation_driver.py`

Goal: rebuild orders, fills, positions, cash and realised PnL from
event logs alone, then explain mismatches.

Implementation plan:

1. Add `ExecutionReplayState` with orders, fills, positions, cash,
   fees, realised PnL, open orders and warnings.
2. Add `replay_execution_events(events)` returning final state plus
   replay diagnostics.
3. Add `reconcile_engine_vs_replay(engine_state, replay_state)`.
4. Add `reconcile_broker_vs_engine(broker_snapshot, engine_state)`.
5. Classify mismatches:
   missing fill, duplicate fill, orphan order, stale order, cash
   mismatch, position mismatch, commission mismatch, unknown broker
   event and replay gap.
6. Add CLI:
   `aurora live reconcile --events PATH`
   and `aurora live replay-events --events PATH`.
7. Add daily ops section for reconciliation status.

Acceptance criteria:

- Replay from paper events reconstructs expected positions and cash.
- Duplicate fills and missing commissions are detected.
- Restart between acknowledge and fill is covered by tests.
- Reconciliation output names the specific mismatch, not just fail.
- Live adapters are not required for completion; paper and fixtures are
  enough for the first implementation.

### R170. Realistic execution models and TCA report

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 2 to 4 weeks
Area: execution / fills / slippage / transaction cost analysis
Source: Candidate A promoted. HFT lecture notes support modelling
spread, queue, impact, latency and execution costs before trusting
paper/live results.
Suggested paths: `execution/fill_models.py`,
`execution/market_impact.py`, `execution/cautious_limit.py`,
`execution/portfolio_execution.py`, `analytics/cost_breakdown.py`,
`core/slippage_calibration.py`, `tests/test_fill_models_constraints.py`

Goal: make execution simulation less naive and produce a clear TCA
report after paper/live sessions.

Implementation plan:

1. Add fill-model interfaces for market, limit, stop and stop-limit
   orders.
2. Model spread-aware fills, partial fills, latency, stale quotes,
   reject probability, tick size, minimum lot and volume participation.
3. Add conservative queue-position approximation for limit orders.
4. Add market-impact estimate with temporary cost and longer-lived
   impact split.
5. Add simple execution algorithms:
   TWAP, VWAP, POV, cautious limit and implementation shortfall
   baseline.
6. Add TCA report fields:
   arrival price, execution price, effective spread, realised spread,
   slippage, delay cost, opportunity cost, unfilled quantity,
   commissions and fees.
7. Wire TCA into daily ops and evidence packs when executions exist.

Acceptance criteria:

- Fill models produce deterministic output under a fixed seed.
- Partial fills, rejects and latency are covered by tests.
- TCA decomposes at least one paper session fixture.
- Strategies cannot report net performance without naming execution
  cost assumptions.

### R171. Portfolio allocation core inspired by skfolio

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 2 to 4 weeks
Area: portfolio / optimisation / allocation
Source: Candidate F promoted. skfolio, Riskfolio-Lib and
PyPortfolioOpt are references for API shape and risk measures, not
automatic dependencies.
Suggested paths: `portfolio/allocation.py`,
`portfolio/constraints.py`, `portfolio/risk_measures.py`,
`portfolio/optimizers.py`, `validation/portfolio_validation.py`,
`tests/test_portfolio_execution.py`

Goal: add a clean portfolio-allocation interface with simple reliable
allocators before adding clever optimisation.

First allocators:

- equal weight
- inverse volatility
- risk parity / risk budgeting
- maximum diversification
- minimum variance
- mean-risk baseline
- benchmark tracking baseline

Constraints:

- long-only / long-short
- minimum and maximum weights
- gross and net exposure
- group exposure
- turnover
- cash
- leverage
- concentration
- per-strategy capital caps

Implementation plan:

1. Define `PortfolioProblem`, `PortfolioConstraints` and
   `PortfolioSolution`.
2. Keep optimisers behind a common interface.
3. Include costs and turnover in the objective or validation summary.
4. Add deterministic fallback allocators that do not require heavy
   dependencies.
5. Add optional dependency review before wrapping skfolio or another
   optimiser.
6. Make constraint violations hard failures, not warnings.

Acceptance criteria:

- Equal weight, inverse volatility and minimum variance pass tests.
- Constraint violations are detected.
- Optimiser output includes weights, expected risk, realised risk,
  turnover, costs and warnings.
- No optimiser may ignore transaction costs silently.

### R172. Portfolio stress, attribution and reporting

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium-high
Effort: 2 to 3 weeks
Area: portfolio / risk / reporting
Source: Candidate F and Candidate H promoted. R171 chooses weights;
R172 explains whether those weights are robust and what drove returns.
Suggested paths: `portfolio/stress.py`, `portfolio/attribution.py`,
`reporting/portfolio_analytics.py`, `reporting/factor_tearsheet.py`,
`tests/test_portfolio_analytics_report.py`

Goal: turn portfolio allocation from a weight vector into an
operator-readable risk report.

Implementation plan:

1. Add stress tests for noisy covariance, higher costs, missing assets,
   correlated drawdown, liquidity shock and concentration shock.
2. Add contribution to return and contribution to risk.
3. Add benchmark-relative attribution.
4. Add rolling return, rolling volatility, rolling Sharpe and drawdown
   tables.
5. Add exposure by sector, asset class, country and strategy family
   where metadata exists.
6. Wire reports to evidence packs.

Acceptance criteria:

- Portfolio report works with R158-style seed data fixtures.
- Contributions sum to portfolio return within tolerance.
- Stress scenarios are deterministic.
- Report includes policy hash, snapshot hash and data-quality status.

### R173. Strategy atlas and curated idea catalogue

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium-high
Effort: 2 to 4 weeks
Area: research / strategy catalogue / idea governance
Source: Candidate E promoted. The 151-strategy paper and curated
sources are useful as idea metadata, not as proof that a strategy
works.
Suggested paths: `research/strategy_atlas.py`,
`research/idea_sources.py`, `research/strategy_benchmarks.py`,
`research/graveyard.py`, `tests/test_idea_sources.py`

Goal: create a controlled atlas of strategies AURORA can understand,
classify and validate honestly.

Atlas status values:

- supported
- candidate
- blocked
- rejected
- benchmark-only
- external-data-only
- needs-engine-support

Implementation plan:

1. Define `StrategyAtlasEntry` with name, source, asset class, required
   data, required engine capabilities, cost sensitivity, overfit risk,
   implementation difficulty, benchmark expectation and status.
2. Ingest curated sources as metadata only:
   source title, claim, data needs, assumptions and testability.
3. Add the first supported slice:
   ETF momentum rotation, dual momentum, multi-asset trend following,
   volatility targeting, ETF mean reversion, simple pairs,
   KNN single-stock example and controlled alpha-combo ensemble.
4. Mark options-heavy, structured-credit, tax, exotic fixed-income and
   legal / regulatory strategies as blocked unless data and engine
   support exist.
5. Query graveyard and similarity before allowing a new template from
   the atlas.
6. Add CLI:
   `aurora research atlas list`, `show`, `classify`, `link-source`.

Acceptance criteria:

- Blocked atlas entries cannot be promoted without audited override.
- Each supported entry has a benchmark expectation.
- Source claims are not treated as validation evidence.
- Atlas status appears in strategy evidence packs.

### R174. Literature scout and full-paper ingestion pipeline

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium-high
Effort: 2 to 4 weeks
Area: research / papers / evidence extraction
Source: operator request for AURORA to search papers and read them
reliably. This item turns papers into structured research inputs
without letting them bypass validation.
Suggested paths: `research/literature/`, `research/idea_sources.py`,
`research/strategy_atlas.py`, `docs/`, `tests/test_idea_sources.py`

Goal: let AURORA discover, ingest, summarise and extract structured
claims from papers in a reproducible way.

Implementation plan:

1. Add `PaperRecord` with title, authors, year, source, URL or local
   path, DOI / SSRN id where available, license note, ingestion time,
   content hash and extraction status.
2. Add paper ingestion from local PDFs first. Web search can come
   later through explicit operator action.
3. Extract structured fields:
   strategy idea, asset class, sample period, universe, data frequency,
   reported metrics, transaction costs, assumptions, limitations,
   replication requirements and red flags.
4. Add quote limits and page references for extracted claims.
5. Link paper claims to StrategyAtlas entries as unvalidated source
   evidence.
6. Add `aurora research papers ingest PATH`,
   `aurora research papers list`,
   `aurora research papers claims PAPER_ID`.
7. Add a reliability score:
   reproducible data available, costs included, OOS included,
   multiple-testing addressed, survivorship handled, code available,
   sample size adequate.

Acceptance criteria:

- Local PDF ingestion stores content hash and extracted metadata.
- Extracted claims keep page references where possible.
- A paper claim cannot promote a strategy by itself.
- StrategyAtlas can link to one or more paper claims.
- Tests use small fixture documents, not live web calls.

### R175. Solo-operator risk record and approval

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high before serious paper/live capital
Effort: 1 to 2 weeks
Area: governance / approval / model risk / solo operator
Source: Candidate D promoted, adapted for single-user AURORA. A
technically valid strategy still needs intended use, limits, expiry and
explicit approval before paper/live promotion, but it does not need
fake committee roles.
Suggested paths: `governance/approvals.py`, `research/lifecycle.py`,
`agent_gateway/`, `validation/pipeline.py`, `tests/test_lifecycle_sla.py`

Goal: require a current local risk record and a deliberate
single-operator approval before a strategy can move toward paper,
canary or live.

Implementation plan:

1. Add `StrategyRiskRecord` with intended use, limitations,
   assumptions, operator name / id, risk limits, validation evidence,
   data contract, policy hash, snapshot hash, strategy hash, expiry and
   revalidation date.
2. Add solo states:
   drafted, reviewed_by_operator, approved_for_shadow,
   approved_for_paper, approved_for_canary, approved_for_live,
   retired.
3. Block promotion if risk record is missing, expired or inconsistent
   with validation evidence.
4. Record overrides with reason, timestamp, operator id, affected
   hashes and audit hash.
5. Surface risk status in daily ops, preflight and evidence packs.
6. Keep optional multi-reviewer fields out of the critical path unless
   a future multi-user mode is explicitly enabled.

Acceptance criteria:

- Promotion fails without a current risk record.
- Solo approval state is enforced.
- Expired records trigger revalidation or archive.
- Overrides are visible in audit and evidence pack output.
- No second-human approval is required by default.

### R176. Agentic evidence review and explanation layer

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium
Effort: 2 to 4 weeks
Area: agents / explanation / operator UX / safety
Source: Candidate G promoted. QuantAgent-style specialist roles are
useful only as reviewers of evidence, not as trading authorities.
Suggested paths: `agent_gateway/`, `research/llm_assistant.py`,
`reporting/`, `tests/test_agent_gateway.py`

Goal: add bounded specialist agents that read evidence packs and
produce operator-facing explanations, objections and follow-up
questions.

Agent roles:

- data-quality reviewer
- strategy-summary reviewer
- risk reviewer
- execution-cost reviewer
- regime reviewer
- report explainer

Implementation plan:

1. Agents may consume evidence packs, validation reports, audit trails
   and approved snapshots only.
2. Agents may not read locked OOS / FORWARD data without the normal
   ceremony.
3. Agents may not submit, cancel, modify or approve broker orders.
4. Every agent output must cite evidence ids:
   policy hash, snapshot hash, validation hash, strategy hash and
   source report.
5. Preserve disagreements between agents instead of forcing one
   polished answer.
6. Add prompt-injection tests for malicious strategy descriptions,
   poisoned research notes, hostile web text, secret requests and
   OOSGuard bypass attempts.

Acceptance criteria:

- Agents fail closed when evidence is missing or hashes mismatch.
- Agent output cannot promote a strategy.
- Prompt-injection fixtures cannot reveal secrets or bypass OOSGuard.
- Explanation pack includes thesis, evidence, objections, risks,
  missing data and next checks.

### R177. Research-to-live preflight bundle

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high before paper/live
Effort: 2 to 3 weeks
Area: deployment / live readiness / safety gates
Source: synthesis item after R168-R176. AURORA needs one final bundle
that proves data, validation, execution and governance are ready before
paper or live.
Suggested paths: `deployment/preflight/`, `validation/pipeline.py`,
`execution/reconciliation.py`, `governance/approvals.py`,
`reporting/daily_ops/`, `docs/ZERO_TO_LIVE.md`

Goal: combine the required gates into one operator-readable preflight
before paper, canary or live deployment.

Required checks:

- data quality approved
- identity resolved
- corporate-action / calendar status acceptable
- latest data refresh reviewed
- validation current
- benchmark pack current
- research ledger complete
- evidence pack reproducible
- risk record approved
- execution model named
- kill switch armed
- broker / paper adapter healthy
- reconciliation clean or explained
- capital limits set
- rollback plan present

Implementation plan:

1. Add `aurora live preflight --strategy STRATEGY_ID`.
2. Return pass, warn or fail per gate.
3. Fail closed for missing evidence.
4. Allow operator overrides only with reason and audit hash.
5. Export preflight bundle into evidence pack and daily ops.

Acceptance criteria:

- A strategy cannot enter paper/live when required evidence is missing.
- Preflight output is readable in table and JSON.
- Override path is audited.
- Tests cover missing data, stale validation, failed reconciliation and
  expired approval.

Recommended execution order for R168-R177:

1. R168 execution events.
2. R169 replay / reconciliation.
3. R170 execution models / TCA.
4. R171 portfolio allocation core.
5. R172 portfolio stress / attribution.
6. R173 strategy atlas.
7. R174 literature ingestion.
8. R175 risk register.
9. R176 agentic evidence review.
10. R177 research-to-live preflight.

Reason: execution event truth should precede live-readiness claims;
portfolio construction should wait for data and cost realism; strategy
ideas and papers should feed the atlas, not bypass validation; agents
should explain evidence only after evidence exists.

### R178. Data licence, provider terms and usage-policy registry

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high
Effort: 1 to 2 weeks
Area: data / governance / compliance / provider policy
Source: final platform-hardening pass. R155-R158 add many free and
fallback providers; AURORA must know what each source permits before
using it in research, redistribution, reports or live workflows.
Suggested paths: `core/data_providers/`, `data_contracts/lineage.py`,
`docs/`, `cli/cmd_data.py`, `tests/test_data_providers_free_bulk.py`

Goal: store provider terms, licence posture and allowed usage in a
machine-readable way.

Implementation plan:

1. Add `ProviderTermsRecord` with provider, source URL, licence URL,
   free / paid / token-gated status, personal-use warning,
   redistribution policy, commercial-use warning, attribution
   requirement, rate-limit policy and reviewed_at timestamp.
2. Add allowed usage labels:
   smoke_test, personal_research, internal_research, redistribution,
   paper_trading, live_trading and report_export.
3. Attach terms records to provider descriptors and provenance.
4. Add `aurora data provider-terms` to print allowed and blocked uses.
5. Make evidence packs include provider terms for all data used.
6. Add policy gates so a dataset with personal-use-only warnings cannot
   be silently used in live or exported reports without an audited
   override.

Acceptance criteria:

- Yahoo-style fallback providers carry an unofficial / personal-use
  warning.
- CoinMetrics community-style data carries non-commercial warning by
  default.
- Provider terms appear in coverage reports and evidence packs.
- A blocked usage produces a plain-language failure.

### R179. Local telemetry and metrics contract

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium before live
Effort: 1 to 2 weeks
Area: observability / local monitoring / operations
Source: final platform-hardening pass, adapted for solo use. Daily ops
exists, but AURORA needs consistent run ids, metrics and local logs.
It does not need Prometheus, Grafana or OpenTelemetry as a default.
Suggested paths: `monitoring/`, `reporting/daily_ops/`,
`core/witness.py`, `agent_gateway/audit.py`, `deployment/`,
`tests/test_infra_redis_cache.py`

Goal: make every important run locally observable with shared
identifiers, structured events and simple metrics.

Required correlation ids:

- run_id
- dataset_id
- snapshot_hash
- policy_hash
- strategy_id
- validation_id
- broker_order_id
- internal_order_id
- evidence_pack_id

Implementation plan:

1. Define a small internal telemetry interface first:
   emit_metric and emit_event. Span-style tracing is optional.
2. Use JSONL local telemetry as the default sink.
3. Emit metrics for data freshness, provider failures, validation gate
   failures, order latency, fill latency, rejected orders, open-order
   age, reconciliation diffs, drawdown, exposure and kill-switch state.
4. Add optional OpenTelemetry / Prometheus bridge only if live use
   proves local files are not enough.
5. Add `aurora ops metrics-tail` or equivalent local inspection.
6. Document metric names and labels.

Acceptance criteria:

- Local telemetry sink records deterministic test events.
- Data bootstrap, validation and paper execution emit core metrics.
- Metrics include correlation ids where available.
- Missing telemetry sink never breaks core execution.
- No external monitoring service is required.

### R180. Local incident notes and lightweight postmortems

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium before live
Effort: 1 to 2 weeks
Area: operations / local incident notes / postmortems
Source: final platform-hardening pass, adapted for solo operation.
Disaster recovery and daily ops exist, but failures need a structured
local note instead of an enterprise incident platform.
Suggested paths: `monitoring/`, `reporting/daily_ops/`,
`docs/DISASTER_RECOVERY.md`, `docs/ZERO_TO_LIVE.md`,
`execution/reconciliation.py`

Goal: turn live, data-quality or validation failures into local
incident notes with timeline, impact and corrective actions.

Incident types:

- stale data
- bad tick / bad bar
- provider outage
- broker disconnected
- missing fill
- duplicate fill
- rejected order spike
- margin warning
- drawdown breach
- kill switch fired
- reconciliation mismatch
- OOS leak attempt
- evidence hash mismatch

Implementation plan:

1. Add `IncidentRecord` with id, severity, opened_at, closed_at,
   affected strategies, affected symbols, evidence hashes, timeline,
   root cause, impact and action items.
2. Add `aurora ops note open`, `append`, `close`, `postmortem`.
   Keep `incident` as an alias if already implemented.
3. Auto-suggest incident notes for severe reconciliation, data-quality
   and kill-switch events, but do not spam-create records for every
   warning.
4. Generate postmortem Markdown from incident records.
5. Link incidents to evidence packs and daily ops.

Acceptance criteria:

- Incidents can be opened and closed deterministically in tests.
- Severe preflight / reconciliation failure can suggest or create a
  local incident note.
- Postmortem includes timeline, impact, root cause and follow-ups.
- Closed incident is immutable except for audited append-only notes.

### R181. Point-in-time feature store and signal cache

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high for ML / factor research
Effort: 2 to 4 weeks
Area: features / ML / point-in-time / caching
Source: final platform-hardening pass plus qlib / Feast-style feature
store references. R162 stores fundamentals; R181 stores reusable
features and signals safely.
Suggested paths: `core/features.py`, `data_contracts/timeseries_store.py`,
`ml/`, `research/auto_gen/`, `validation/`

Goal: compute and store features with point-in-time availability,
owner, lineage, tests and reproducible hashes.

Implementation plan:

1. Define `FeatureDefinition` with name, version, inputs, lookback,
   owner, frequency, point-in-time policy, null policy and code hash.
2. Add `FeatureStore` backed by TimeSeriesStore libraries.
3. Add `feature_at(symbol, decision_time)` that refuses future
   availability.
4. Store signal outputs separately from raw features.
5. Add cache keys based on input hashes, feature version and policy
   hash.
6. Add feature drift / missingness report.
7. Add CLI:
   `aurora features build`, `features list`, `features validate`.

Acceptance criteria:

- Future feature values cannot leak into earlier decision times.
- Recomputing the same feature from the same inputs gives the same
  content hash.
- Missingness and drift are reported.
- Feature store entries link back to dataset and code lineage.

### R182. Strategy, model and feature registry

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high for research-to-live
Effort: 2 to 3 weeks
Area: registry / lifecycle / ML / strategy governance
Source: final platform-hardening pass. R175 covers risk approval;
R182 covers the technical registry of versions, aliases and artefacts.
Suggested paths: `registry/`, `research/bundle.py`,
`research/lifecycle.py`, `ml/`, `data_contracts/lineage.py`

Goal: keep strategies, models, features and bundles versioned with
clear lifecycle stages and aliases.

Implementation plan:

1. Add registry records for:
   strategy_version, model_version, feature_set_version,
   data_contract_version, validation_id, evidence_pack_id,
   lifecycle_stage and aliases.
2. Support aliases such as latest, candidate, paper, canary, live and
   retired.
3. Ensure aliases cannot move without audit evidence.
4. Link registry records to risk records, evidence packs and ledger
   pressure.
5. Add CLI:
   `aurora registry list`, `show`, `promote`, `alias`, `retire`.

Acceptance criteria:

- Registry can answer which exact model / strategy is live.
- Alias movement is audited.
- Retired versions remain inspectable.
- Promotion refuses missing validation or evidence pack.

### R183. Futures engine and continuous-contract handling

Status: open
Priority: medium
Effort: 3 to 6 weeks
Area: multi-asset / futures / data / execution
Source: final platform-hardening pass. Futures appear in strategy
sources and crypto providers, but continuous futures need explicit
contract handling before serious use.
Suggested paths: `markets/futures.py`, `data_contracts/security_master.py`,
`data_contracts/calendars.py`, `core/data_providers/`, `execution/`

Goal: support futures contracts without pretending an ETF-like price
series is the same thing as a tradable futures chain.

Implementation plan:

1. Add `FuturesContract` with root, exchange, expiry, first notice
   date, last trade date, multiplier, tick size, margin, currency and
   settlement type.
2. Add roll rules:
   volume roll, open-interest roll, calendar roll and fixed-days-before
   expiry roll.
3. Add continuous contract construction with adjustment mode:
   raw, back-adjusted, ratio-adjusted and Panama-style where supported.
4. Store mapping from continuous symbol to actual contract over time.
5. Add futures-specific cost, margin and session handling.
6. Keep live futures trading out of scope until broker support and
   risk approval exist.

Acceptance criteria:

- Continuous series records its roll schedule.
- Backtest can recover which real contract was active on a date.
- Roll yield / roll gap is visible in report.
- No futures strategy can run without contract specs and roll rule.

### R184. Options chain, Greeks and assignment engine

Status: open
Priority: medium
Effort: 4 to 8 weeks
Area: multi-asset / options / pricing / risk
Source: final platform-hardening pass. Options appear in alt-data and
strategy sources, but should stay blocked until chains, Greeks and
assignment are explicit.
Suggested paths: `markets/options_strategies.py`,
`altdata/options_flow.py`, `data_contracts/security_master.py`,
`validation/`, `execution/`

Goal: represent options as actual contracts with expiry, strike, right,
multiplier, implied volatility, Greeks, exercise and assignment risk.

Implementation plan:

1. Add `OptionContract` with underlying, expiry, strike, right,
   style, multiplier, exchange, currency and settlement.
2. Add option chain store with quote timestamp and availability time.
3. Add Greeks and implied-volatility fields with source provenance.
4. Add simple pricing / validation checks:
   no negative option prices, intrinsic value sanity, expiry handling.
5. Add assignment / exercise event models.
6. Add multi-leg strategy representation.
7. Keep production options trading out of scope until data and broker
   support are reviewed.

Acceptance criteria:

- Fixture option chain stores and loads with point-in-time timestamps.
- Expired options are handled explicitly.
- Multi-leg payoff fixture is correct.
- Assignment / exercise events can be represented in execution replay.

### R185. Crypto derivatives, funding and exchange capability matrix

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium
Effort: 2 to 4 weeks
Area: crypto / derivatives / exchange capability / risk
Source: final platform-hardening pass. Binance public data and CCXT
exist, but crypto spot, futures, perpetuals and funding are different
instruments.
Suggested paths: `core/data_providers/binance_public_data_daily.py`,
`core/data_providers/ccxt_daily.py`, `deployment/brokers/`,
`data_contracts/security_master.py`, `execution/`

Goal: model crypto spot, futures and perpetuals separately with
funding, margin mode and exchange capability checks.

Implementation plan:

1. Add instrument records for crypto spot, dated futures and perpetuals.
2. Store funding rates and funding timestamps for perpetuals.
3. Add exchange capability matrix:
   spot supported, futures supported, margin supported, order types,
   min size, tick size, rate limits and sandbox availability.
4. Add risk checks for leverage, funding drag, exchange downtime and
   symbol delisting.
5. Add dry-run capability checks before any crypto paper/live session.

Acceptance criteria:

- BTC spot and BTC perpetual are distinct instruments.
- Funding can be applied to a simple perpetual PnL fixture.
- Unsupported exchange capability blocks order submission.
- Evidence pack states spot / futures / perpetual assumptions.

### R186. Local extension API and optional plugin contract

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: low-medium
Effort: 1 to 3 weeks
Area: developer experience / local extensions / optional plugins
Source: final platform-hardening pass, adapted for solo use. AURORA
needs clean local extension points before it needs a public plugin
ecosystem.
Suggested paths: `core/data_providers/`, `strategies/`, `validation/`,
`deployment/brokers/`, `reporting/`, `docs/`

Goal: define versioned interfaces for local providers, strategies,
validators, broker adapters and report renderers, with public plugin
support explicitly optional.

Interfaces:

- DataProvider
- Strategy
- Signal
- Feature
- Validator
- BrokerAdapter
- ExecutionModel
- RiskModel
- ReportRenderer
- AuditSink

Implementation plan:

1. Add explicit `interface_version` fields.
2. Add compatibility policy:
   deprecated_after, removed_after and migration notes.
3. Add local extension discovery from configured safe directories only.
4. Add allowlist / denylist for plugin loading.
5. Add `aurora extensions list`, `validate`, `explain`. Keep
   `plugins` as an alias only if already exposed.
6. Add docs with one minimal local provider and one minimal local
   strategy extension.

Acceptance criteria:

- Example local extension loads in tests.
- Incompatible interface version fails with clear message.
- Extension cannot bypass OOSGuard, validation gates or audit sinks.
- Extension loading is opt-in, not automatic from arbitrary paths.
- No marketplace or public plugin registry is required.

### R187. Operator doctor, health checks and environment diagnosis

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: high for usability
Effort: 1 to 2 weeks
Area: CLI / developer experience / operations
Source: final platform-hardening pass. The project has many moving
parts; operators need one command that says what is healthy and what is
missing.
Suggested paths: `cli/cmd_data.py`, `deployment/preflight/`,
`core/runtime_paths.py`, `docs/ZERO_TO_LIVE.md`

Goal: add `aurora doctor` as the first command an operator runs when
something feels broken.

Checks:

- package import and version
- runtime paths
- writable data / cache / snapshot dirs
- Python version
- optional dependencies
- provider credentials / env vars
- provider terms reviewed
- first dataset present
- snapshots present
- ruff / tests availability
- broker sandbox config
- audit log writable
- OOS lock status

Implementation plan:

1. Add health-check registry with individual check objects.
2. Add table and JSON output.
3. Classify pass, warn, fail and skipped.
4. Link each failure to a doc or suggested command.
5. Keep checks read-only by default.

Acceptance criteria:

- `aurora doctor` runs without network by default.
- Missing first dataset is reported clearly.
- Runtime-path permission failures are detected.
- JSON output is stable enough for tests.

### R188. Local release, provenance and compatibility hardening

Status: completed (2026-05-10 session; see docs/roadmap/R159_R190_SESSION_REPORT.md)
Priority: medium; high only before public release
Effort: 1 to 3 weeks
Area: local release / reproducibility / compatibility
Source: final platform-hardening pass, adapted for solo use. AURORA
still needs reproducible local wheels and compatibility discipline, but
public signing is optional unless the project is published.
Suggested paths: `.github/workflows/`, `pyproject.toml`,
`docs/AURORA_RENAME_CHECKLIST.md`, `docs/ENV_VAR_MIGRATION_PLAN.md`,
`CHANGELOG.md`

Goal: make local release artefacts traceable and compatibility-safe.
Add public signing only if AURORA is distributed outside the operator's
machine.

Implementation plan:

1. Add release checklist:
   full tests, typecheck, ruff, docs, build, SBOM, vulnerability scan,
   evidence pack, changelog and tag.
2. Add clean local wheel verification first.
3. Add PyPI Trusted Publishing plan only if publishing to PyPI.
4. Add Sigstore / keyless signing decision only before public
   distribution.
5. Add lightweight build provenance:
   commit, Python version, dependency lock / freeze, wheel hash and
   build timestamp.
6. Define retirement date for `aurora` import shim and `QF_*`
   environment variable fallback.
7. Add release verification command:
   install wheel in clean env, import `aurora`, CLI smoke, legacy shim
   warning check.

Acceptance criteria:

- Release checklist exists and is referenced from docs.
- Wheel smoke test runs from built artefact.
- Shim retirement plan has dates / versions.
- Public artefact signing is documented as optional until distribution.

### R189. Solo-operator research/live cockpit

Status: open
Priority: medium
Effort: 3 to 6 weeks
Area: local dashboard / UX / operations
Source: final platform-hardening pass. R85 has a dashboard upgrade
plan; R189 turns the mature evidence, data and execution layers into
one local operator cockpit.
Suggested paths: `monitoring/dashboard.py`,
`reporting/daily_ops/`, `reporting/`, `docs/DASHBOARD_UPGRADE_PLAN.md`

Goal: provide one local UI for research state, data quality,
strategies, evidence, paper/live status and local incident notes.

Panels:

- data coverage and quality
- provider status and terms warnings
- snapshots and stale reports
- strategy lifecycle
- validation results
- benchmark comparison
- evidence packs
- portfolio exposure
- execution / reconciliation
- incident notes and runbooks
- preflight status

Implementation plan:

1. Keep Streamlit as the default unless a separate dependency decision
   approves a new UI.
2. Make each panel pure-data first, UI second.
3. Add tests for panel data builders without launching UI.
4. Link UI actions to CLI commands rather than duplicating logic.
5. Keep live controls read-only by default. Any action button that can
   affect paper/live state must call the same audited CLI/library path
   used outside the dashboard.

Acceptance criteria:

- Dashboard can run with local fixture data.
- Missing data appears as a warning, not a crash.
- Panels do not bypass CLI / library permission checks.
- Data builders have deterministic tests.
- No hosted dashboard, auth system or multi-user permissions are
  required by default.

### R190. Performance, memory and scaling budget

Status: open
Priority: medium-high before large universes
Effort: 2 to 4 weeks
Area: performance / memory / scalability
Source: final platform-hardening pass. R40 created benchmarks and R5 /
R6 gate Rust / GPU. R190 defines practical performance budgets before
R158 expands toward larger datasets.
Suggested paths: `examples/benchmarks/`, `data_contracts/timeseries_store.py`,
`core/snapshots.py`, `validation/`, `research/auto_gen/`

Goal: know when AURORA is slow, why it is slow and what budget a
dataset or strategy run must respect.

Implementation plan:

1. Define benchmark scenarios:
   single asset, 100 assets, 1,000 assets, 10,000 parameter sets,
   snapshot load, validation pipeline, feature build, evidence pack,
   execution replay and portfolio allocation.
2. Track wall time, peak memory, output hash and row count.
3. Add memory-budget warnings for large TimeSeriesStore reads.
4. Add chunked / streaming path design for large datasets.
5. Add regression thresholds stored per-machine or per-CI profile.
6. Keep Rust / GPU / distributed work blocked until this report proves
   the bottleneck.

Acceptance criteria:

- Benchmark runner emits JSON with time, memory and output hash.
- At least three R158-related scenarios are benchmarked.
- Performance regression is detectable in CI or local comparison.
- Scaling recommendation says: optimise Python, chunk data, use numba,
  distribute, Rust, GPU or do nothing.

Recommended execution order for R178-R190:

1. R187 operator doctor.
2. R178 provider terms registry.
3. R190 performance budget.
4. R181 feature store.
5. R182 registry.
6. R179 local telemetry.
7. R180 local incident notes.
8. R188 local release hardening.
9. R189 solo cockpit.
10. R183 futures.
11. R184 options.
12. R185 crypto derivatives.
13. R186 local extension API.

Reason: operator diagnosis and provider policy should come before more
complex data use; performance budget should happen before large
universes; feature / model registries come before serious ML; local
telemetry and incident notes are enough until real live pressure proves
otherwise; futures, options and crypto derivatives need the data trust
and execution layers already in place; UI should surface mature state,
not invent it.

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

These may be promoted into numbered R155+ items when they are concrete
enough to implement. Treat them as seven strategic programmes, not as a
pile of loose wishes. The point is to stop Aurora / AURORA from
fooling itself with bad data, overfit research, unrealistic execution,
uncurated strategy sprawl or unowned model risk, while also keeping
portfolio optimisation and agentic analysis inside hard safety rails.

Promotion note: the first concrete post-R158 slices have already been
promoted into R159-R167. Do not add duplicate new items for Instrument
Master, corporate actions / calendars, data-quality quarantine,
point-in-time fundamentals, liquidity / capacity, mandatory
benchmarks, research ledger enforcement, evidence packs or data
refresh / diff. Future candidate promotion should either implement the
remaining unpromoted parts of these programmes or explicitly supersede
the relevant R159-R167 item.

Second promotion note: the first concrete execution / portfolio /
research-governance slices have been promoted into R168-R177. Do not
duplicate canonical execution events, execution replay,
realistic execution / TCA, portfolio allocation, portfolio reporting,
strategy atlas, paper ingestion, solo-operator approval, agentic
evidence review or research-to-live preflight as new candidate items.
Extend or supersede the relevant R168-R177 entry instead.

Final promotion note: solo-operator platform hardening has been
promoted into R178-R190. Do not add duplicate items for provider terms,
local telemetry, local incident notes, feature store, model / strategy
registry, futures, options, crypto derivatives, local extension API,
doctor command, local release hardening, solo cockpit or performance
budgets. If a future idea fits those areas, attach it to the relevant
R178-R190 item.

Source references:

- `C:\Users\HP\Downloads\HFT_2024___Oxford___lecture_notes_2024.pdf`
  supports Candidate A. Use it as a design reference for limit order
  books, market impact, optimal execution, fill probability, market
  making, portfolio execution and cointegrated-asset trading.
- `C:\Users\HP\Downloads\ssrn-3247865.pdf` supports Candidate E. Use
  it as a curated strategy catalogue and benchmark source, not as a
  blanket request to implement 151 strategies.
- `https://github.com/skfolio/skfolio` supports Candidate F. Use it as
  a reference for portfolio optimisation, risk measures, constraints,
  transaction costs, stress tests, scikit-learn-style model selection,
  walk-forward validation and purged cross-validation.
- `https://github.com/Y-Research-SBU/QuantAgent` supports Candidate G.
  Use it as a reference for multi-agent market-analysis UX and
  explanation, not as a trading brain.
- `https://github.com/nautechsystems/nautilus_trader` and
  `https://github.com/QuantConnect/Lean` support Candidate A. Use them
  as references for deterministic event flow, backtest/live parity,
  modular engine boundaries, brokerage abstractions and replayable
  execution state.
- `https://github.com/microsoft/qlib`,
  `https://github.com/microsoft/RD-Agent` and
  `https://github.com/polakowo/vectorbt` support Candidate B / E / G.
  Use them as references for ML research workflows, fast sweeps,
  automated factor proposals and the extra audit needed when research
  gets faster.
- `https://github.com/stefan-jansen/zipline-reloaded` supports
  Candidate C and Candidate A. Use it as a reference for event-driven
  backtesting, data bundles, calendars and a researcher-friendly API.
- `https://github.com/dcajasn/Riskfolio-Lib` and
  `https://github.com/PyPortfolio/PyPortfolioOpt` support Candidate F
  as portfolio-optimisation references alongside skfolio.
- `https://github.com/freqtrade/freqtrade` supports Candidate A for
  crypto live/dry-run operator UX, exchange capability checks and
  lookahead / recursive-signal analysis.
- `https://github.com/manahl/arctic` supports Candidate C as a design
  reference for local / institutional time-series storage. Use the
  storage ideas, not necessarily the dependency.
- `https://github.com/quantopian/alphalens` and
  `https://github.com/quantopian/pyfolio` support reporting /
  validation follow-ups: factor tear sheets, IC decay, turnover,
  quantile returns, drawdown and benchmark comparison.
- R-Finance `PerformanceAnalytics`, `PortfolioAnalytics` and
  `PortfolioAttribution` support Candidate F as references for
  portfolio analytics: contribution, rolling risk, attribution and
  reporting tables.
- `https://www.quantpedia.com/`, QuantStart, Ernie Chan / EpChan and
  similar curated strategy sources support Candidate E as idea sources
  for the strategy atlas. Treat them as references requiring
  independent validation, not as truth.

### Candidate A. Execution integrity programme

Why it matters: after a paper or live session, Aurora should be
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
- Limit-order simulation has an explicit fill-probability model that
  accounts for price improvement, queue position, available liquidity
  and time-to-fill.
- Market-impact modelling distinguishes at least temporary execution
  cost from longer-lived price impact, even if the first version uses a
  conservative simplified model.
- Execution algorithms expose a small set of calibrated baselines:
  TWAP / VWAP / POV, Almgren-Chriss-style schedule, implementation
  shortfall and a cautious limit-order schedule.
- Market-making work remains gated until inventory risk, quote
  cancellation, fill uncertainty and live kill-switch controls are
  covered by tests.
- Portfolio execution handles cross-asset orders as a portfolio-level
  problem, not as independent single-symbol orders when correlation or
  shared liquidity risk matters.
- Cointegrated / pairs execution is treated as a specialist extension:
  it must prove spread construction, mean-reversion assumptions and
  joint execution costs before promotion.
- NautilusTrader-style backtest/live parity is evaluated as a design
  reference: the same strategy intent should produce comparable event
  streams in backtest, paper and live, with explicit differences
  recorded instead of hidden.
- LEAN-style modular engine boundaries are reviewed before changing
  core execution: data feed, transaction handler, brokerage adapter,
  result handler, realtime handler and algorithm surface should remain
  separable.
- Freqtrade-style dry-run and live controls are reviewed for crypto
  flows: operator status, exchange capability checks, pair whitelist /
  blacklist, lookahead checks and recursive-signal checks.
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
- Qlib-style automated research workflows are allowed only if every
  generated factor, model, dataset, seed, parameter choice and rejection
  enters the research ledger.
- Vectorbt-style large parameter sweeps must record the full explored
  search space, not just the winner. Fast experimentation increases the
  need for audit, not the right to skip it.
- RD-Agent / LLM-assisted factor mining must operate through locked
  evidence packs and append-only logs. Agent-generated hypotheses are
  research inputs, not validation evidence by themselves.
- Manual overrides are recorded with author, timestamp and reason.
- Tests prove the ledger is append-only and survives resume / retry.

Reason not to start immediately: it is strategically important but
touches research UX, validation reporting and the factory. Best done
after the roadmap truth / CI batch, otherwise it becomes another big
feature sitting on soft ground. Glamorous? No. Useful? Painfully.

### Candidate E. Strategy atlas and benchmark catalogue

Why it matters: the "151 Trading Strategies" PDF is useful because it
maps a wide strategy universe across options, equities, ETFs, fixed
income, futures, FX, volatility, crypto, macro and more. It is dangerous
if treated as a shopping list. Aurora / AURORA should turn it into
a curated atlas that says what each idea needs, what the engine already
supports, what is out of scope, and which benchmarks or graveyard
entries should exist before anyone promotes a new strategy.

Recommended promotion target: merge with R38 / R39 / R87 / R92 / R103
/ R104 if the next work is strategy lifecycle, templates or similarity
checks. Promote as its own item only if the project starts systematic
strategy-catalogue work.

Definition of ready:

- A `StrategyAtlas` record exists for each curated idea: name, asset
  class, data requirements, required engine capabilities, cost
  sensitivity, likely overfit risk, implementation difficulty,
  validation gates and owner.
- The atlas classifies each idea as supported, candidate, blocked,
  rejected, benchmark-only or external-data-only.
- The first curated slice covers only strategies Aurora can test
  honestly today: ETF momentum rotation, dual momentum, multi-asset
  trend following, volatility targeting, ETF mean reversion, simple
  stat-arb / pairs, KNN single-stock as an ML example, and controlled
  alpha-combo ensembles.
- Options-heavy, convertibles, structured-credit, tax-arbitrage,
  exotic fixed-income and legal / regulatory strategies are marked as
  blocked unless data, pricing, execution and compliance support exists.
- Every atlas entry links to a benchmark expectation: cash,
  buy-and-hold, equal weight, simple momentum / mean reversion, random
  strategy with comparable turnover, or an existing approved strategy.
- Before a strategy template is implemented, similarity checks and the
  strategy graveyard are queried so the project does not rebuild a
  rejected edge under a new name.
- Strategy templates generated from the atlas cannot bypass data
  contracts, OOSGuard, realistic costs, benchmark comparison or the
  research ledger.
- Vectorbt-style fast strategy sweeps are classified as atlas input
  only when the full sweep config, rejected variants and parameter
  ranges are recorded.
- Curated idea sources such as Quantpedia, QuantStart, Ernie Chan /
  EpChan and EliteQuant links are ingested as idea metadata only:
  source, claim, asset class, required data, assumptions, testability
  and status. No source claim is accepted as validation evidence.
- Tests prove that blocked / rejected / benchmark-only entries cannot
  be promoted as production strategies without an explicit audited
  override.

Reason not to start immediately: the atlas is high leverage but only
after the data and research honesty layers are firm. Otherwise the PDF
becomes a menu of tempting backtests. Tempting backtests are cheap;
trustworthy ones are not.

### Candidate C. Data integrity programme

Why it matters: every backtest and validation run should prove that
the input data is sane before the strategy sees it. Bad data can look
like alpha: split errors, duplicated bars, wrong timezone, missing
holidays, impossible prices, currency mistakes, stale snapshots or
vendor-specific quirks. If Aurora lets that through silently, the
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
- Zipline-style data bundles and LEAN-style data abstractions are
  reviewed as references for separating raw vendor data, adjusted data,
  asset metadata, calendars and ingestion history.
- An Arctic-style time-series store design is evaluated for local
  research storage: versioned symbols, library / namespace separation,
  chunked reads, metadata, fast date-range access and deterministic
  snapshot hashes. The first implementation may use existing local
  storage; Arctic is a design reference unless a dependency decision
  approves it.
- A validator runs before backtest, GA, validation and factory submit.
- The detector flags duplicated timestamps, non-monotonic indexes,
  suspicious gaps, zero or negative prices, impossible returns,
  unadjusted split jumps, stale snapshots and mixed timezone inputs.
- Failures are classified as hard fail, warning or operator-approved
  exception, with the decision written into the run provenance.
- Tests cover clean data, common vendor quirks, split-like jumps,
  holiday gaps, duplicate rows, stale snapshots, timezone mismatch and
  time-series-store round trips.

Reason not to start immediately: this is probably the strongest next
feature after CI hardening, but it should be designed as a shared
contract used by the whole engine. If implemented piecemeal, every
module will invent its own definition of "valid data", and that way
lies sadness with a nice traceback.

### Candidate F. Portfolio optimisation and risk validation

Why it matters: strategy selection is only half the problem. The other
half is deciding how much capital each strategy or asset receives under
real constraints: turnover, transaction costs, drawdown, tail risk,
concentration, sector / group exposure, leverage, cash, liquidity and
out-of-sample decay. skfolio is useful because it shows a mature shape
for portfolio optimisation with a scikit-learn-style API, model
selection, risk measures, stress testing, constraints and purged /
walk-forward validation. Aurora should learn from that shape before
inventing another half-optimizer that looks clever until costs arrive.

Recommended promotion target: merge with the portfolio / monitoring
cluster around R113, R115, R118, R132, R133 and R154 if the next work
is portfolio construction, capacity or common-cause risk. Promote as a
standalone item only if portfolio allocation becomes the next product
surface.

Definition of ready:

- A portfolio-allocation interface accepts expected returns, realised
  returns, covariance / risk estimates, costs, constraints and
  benchmark references without depending on one concrete optimiser.
- Baseline allocators are available and tested: equal weight, inverse
  volatility, risk parity / risk budgeting, maximum diversification,
  mean-risk and benchmark tracking.
- Risk measures include at least variance, semi-variance, CVaR, maximum
  drawdown, average drawdown and turnover-aware net performance.
- Constraints cover min / max weights, long-only / long-short, gross
  and net exposure, group exposure, turnover, cash, leverage,
  concentration and per-strategy capital caps.
- Transaction costs and management / borrow fees are part of the
  optimisation objective or validation report, not an afterthought
  applied only after the chosen portfolio looks good.
- Model selection supports walk-forward and purged / embargoed
  validation where the data shape requires it.
- Stress tests compare allocation behaviour under bad covariance
  estimates, noisy returns, missing assets, liquidity shocks,
  correlated drawdowns and higher costs.
- The first implementation may wrap internal primitives only. A
  skfolio adapter or optional dependency is allowed only after licence,
  dependency weight, Python compatibility and API stability are
  reviewed.
- Riskfolio-Lib is reviewed for richer risk-measure coverage, risk
  contribution reports, factor-risk constraints and drawdown-aware
  allocation.
- PyPortfolioOpt is reviewed for a simpler classical baseline:
  efficient frontier, Black-Litterman, covariance shrinkage and
  hierarchical risk parity.
- R-Finance-style portfolio analytics are reviewed for reporting:
  rolling returns, rolling volatility, rolling Sharpe, drawdown tables,
  contribution to return, contribution to risk, exposure tables,
  benchmark-relative attribution and monthly / yearly summaries.
- skfolio remains the main API-shape reference because its model
  selection, walk-forward, purged CV and sklearn-compatible interface
  match Aurora's validation direction better than a pure optimiser.
- Reports compare every optimiser against simple baselines: equal
  weight, inverse volatility, cash / no-trade and the previous
  production allocation.
- Tests prove that an optimiser cannot silently violate constraints,
  leak future data through validation, or improve headline Sharpe by
  ignoring transaction costs.

Reason not to start immediately: Aurora already has useful
portfolio pieces, but a serious optimiser should sit on top of data
contracts, research honesty and realistic execution costs. Otherwise it
will allocate capital beautifully to evidence that should have been
rejected earlier. Elegant nonsense is still nonsense.

### Candidate H. Factor tear sheets and analytics reporting

Why it matters: a strategy can pass headline metrics while hiding that
its signal has weak information content, high turnover, unstable
quantiles, regime-specific decay or benchmark-relative
underperformance. Alphalens and pyfolio are useful references because
they separate factor quality, portfolio behaviour and benchmark
comparison into operator-readable reports. Aurora already has many
validation primitives; Candidate H turns them into consistent research
reports.

Recommended promotion target: merge with reporting / validation work
around R81, R82, R84, R98, R104, R105, R126, R127 and Candidate F.
Promote as a standalone item only when strategy research reports become
the next user-facing surface.

Definition of ready:

- A `FactorTearSheet` can report forward returns by quantile,
  Information Coefficient, IC decay, turnover, rank autocorrelation,
  long / short spread, drawdowns, monthly returns and
  benchmark-relative performance.
- A `PortfolioAnalyticsReport` can report rolling returns, rolling
  volatility, rolling Sharpe, drawdown table, contribution to return,
  contribution to risk, exposure by group and benchmark attribution.
- Reports accept plain arrays / DataFrames and do not require a
  strategy object. That keeps them useful for factors, strategies and
  portfolio allocators.
- Reports include data-contract hash, policy hash, snapshot hash,
  factor / strategy hash and cost assumptions.
- Reports refuse to run when forward-return labels overlap forbidden
  OOS tiers or when index alignment is ambiguous.
- HTML / text renderers are deterministic so report output can be
  tested and archived.

Reason not to start immediately: reporting is most valuable after the
data contract, ledger and portfolio primitives exist. Building pretty
reports over weak evidence is just arts and crafts with Sharpe ratios.

### Candidate D. Strategy risk register and approval workflow

Why it matters: a strategy can be technically valid and still be a bad
idea to run. Aurora / AURORA needs a simple model-risk layer that
answers: what is this strategy for, when should it not be used, who
owns it, what evidence promoted it, what risk limits apply, when does
it expire, and who approved the move toward live.

Recommended promotion target: merge with R38 / R39 / R140 / R152 if
the next work is lifecycle governance, or promote as its own
model-risk item before any serious paper-to-live workflow.

Definition of ready:

- Each promoted strategy has a risk record with intended use,
  limitations, assumptions, operator id, optional reviewer, approval status,
  validation evidence, data contract, policy hash, snapshot hash,
  strategy hash, risk limits and expiry / revalidation date.
- Promotion uses a single-operator approval flow by default: the
  operator reviews the evidence, records limits, records the approval
  state and the audit chain stores the evidence. Optional reviewer /
  risk-owner fields may exist, but they are not required in solo mode.
- Lifecycle states are explicit: draft, researching, rejected,
  quarantined, validated, OOS-approved, shadow, paper, canary, live,
  degraded, retired and graveyard.
- Live promotion refuses strategies without a current risk record,
  current validation, current data contract and unresolved warnings
  below the operator-defined threshold.
- Tests cover approval state, expired risk records, rejected promotion,
  override evidence and audit-chain persistence.

Reason not to start immediately: this is governance, not alpha. In
solo mode it should stay small: one explicit approval, one reason, one
audit trail. No bureaucracy cosplay required.

### Candidate G. Agentic research support and explanation layer

Why it matters: QuantAgent is interesting because it presents market
analysis as a coordinated set of specialist agents instead of a single
chat box. That is useful for research triage, explanation and
operator-facing summaries. It is also risky if copied literally:
financial agents can sound confident while quietly mixing weak sources,
stale data, prompt injection and unvalidated reasoning. Aurora /
AURORA should use this pattern only as a controlled support layer above
the existing protocol spine, never as an authority that can inspect
locked OOS data or submit orders.

Recommended promotion target: merge with R8 / R9 / R10 / R43 / R44
and Candidate D if the next work is agent gateway, auditor UX or
research automation. Promote as its own item only after data contracts,
research ledger and approval workflow are strong enough to constrain
the agents.

Definition of ready:

- Agent roles are explicit and limited: data-quality reviewer,
  strategy-summary reviewer, risk reviewer, execution-cost reviewer,
  regime reviewer and report explainer.
- Agents consume evidence packs, validation reports, audit trails and
  approved snapshots; they do not fetch arbitrary market data as truth
  unless the source passes the data-contract gate.
- Agents cannot read OOS_LOCKED / FORWARD data without the same
  ceremony and audit controls as any other caller.
- Agents cannot submit, cancel, modify or approve broker orders. They
  can propose questions, risks and explanations only.
- Every agent output cites the evidence it used: snapshot hash, policy
  hash, validation hash, strategy hash, data contract and source file /
  report where applicable.
- Disagreements between agents are preserved in the report instead of
  being collapsed into false consensus.
- The final output is an operator-facing explanation pack: thesis,
  evidence, objections, risks, missing data, required follow-up and
  explicit non-authority warning.
- Prompt-injection tests cover malicious strategy descriptions,
  poisoned research notes, hostile web text and attempts to reveal
  secrets or bypass OOSGuard.
- Qlib / RD-Agent-style automated quant R&D is permitted only as a
  proposal engine. It may suggest factors, model variants or research
  questions, but the normal validation pipeline decides whether
  anything is credible.
- QuantAgent-style specialist agents can be used for separate market,
  technical, risk and execution commentary, but they must preserve
  disagreement and cite evidence instead of producing one polished
  answer with hidden uncertainty.
- Tool access is allowlisted. Destructive filesystem actions, secret
  reads, broker actions and direct roadmap edits require an audited
  human-approved path.
- Tests prove that agents fail closed when evidence is missing,
  hashes mismatch, OOS access is attempted, or the report tries to
  promote a strategy without the required validation gates.

Reason not to start immediately: agentic analysis is useful only when
the evidence layer is trustworthy. Before that, it mostly creates
well-written uncertainty. The prose gets better; the truth does not.

---

## Implementation Playbook For AI Agents

This section is for the next AI agent that turns the candidate
programmes into code. Follow it as an execution order. Do not implement
everything at once. Each phase must land tests, update docs and pass
the local verification gates before the next phase starts.

Global rules for every phase:

- Keep the existing flat package layout and import boundary.
- Prefer small new modules over expanding already-large files.
- Use internal primitives first. External projects are design
  references, not code to copy.
- Do not add a new dependency until there is a short written decision:
  licence, maintenance status, dependency size, Python compatibility,
  API stability and fallback if removed.
- Every new persistent artifact must use `aurora.core.runtime_paths`
  or an existing runtime-path helper. No hardcoded user paths.
- Every feature that can affect strategy promotion must preserve
  `policy_hash`, `snapshot_hash`, `strategy_hash` and audit evidence.
- A feature is not done until at least one negative test proves it
  refuses unsafe input.
- Run, at minimum:
  `python -m ruff check .`,
  `python -m mypy .`, and the focused pytest files touched by the
  phase. Run the full fast suite before claiming the whole programme is
  complete.

### Phase 1 -- Data integrity gate (Candidate C)

Goal: make bad data fail before backtest, GA, validation or factory
submit can use it.

Suggested modules:

- `data_contracts/contract.py`
- `data_contracts/validator.py`
- `data_contracts/security_master.py`
- `data_contracts/corporate_actions.py`
- `data_contracts/lineage.py`
- `data_contracts/timeseries_store.py`
- CLI wiring in `cli/forge.py` only through a thin subcommand module if
  the CLI split has landed.

Implementation steps:

1. Add immutable dataclasses for `DataContract`, `ContractField`,
   `AvailabilityPolicy`, `CorporateActionPolicy` and
   `DataValidationResult`.
2. Add a validator that checks required columns, monotonic timestamps,
   duplicate rows, timezone policy, null policy, zero / negative prices,
   impossible returns, stale snapshots and suspicious split-like jumps.
3. Add optional point-in-time columns: `event_time`, `available_time`,
   `ingested_time`, `revision_time`. Fail if a caller asks for data
   whose `available_time` is later than the decision time.
4. Add a minimal Security Master record mapping internal symbol, vendor
   symbol, broker symbol, exchange, currency, listing window and active
   state.
5. Add lineage output that records contract version, input hash,
   snapshot hash, policy hash, validator version and decision outcome.
6. Add a local time-series store abstraction with:
   namespace / library name;
   symbol;
   version;
   date-range read;
   metadata;
   content hash;
   append / replace policy;
   deterministic snapshot export.
7. Start with an internal filesystem / parquet / sqlite implementation
   if it fits existing dependencies. Add an Arctic adapter only after a
   dependency decision.
8. Add CLI commands only after the library API is tested:
   `forge data validate`, `forge data contract-show`,
   `forge data lineage`, `forge data store-put`,
   `forge data store-read`.

Reference usage:

- Use Zipline data bundles as inspiration for separating raw data,
  adjusted data, asset metadata and calendars.
- Use LEAN data abstractions as inspiration for keeping vendor data,
  engine data and algorithm-facing data separate.
- Use Arctic as inspiration for library / symbol organisation,
  metadata, fast date-range reads and versioned time-series storage.

Tests:

- Clean data passes.
- Missing required column fails.
- Duplicate timestamp fails.
- Non-monotonic timestamp fails.
- Mixed timezone input fails.
- Zero / negative price fails.
- Split-like jump warns or fails according to contract severity.
- `available_time > decision_time` fails.
- Validator result preserves policy and snapshot hashes.
- Time-series store round-trip preserves index, columns, metadata and
  content hash.
- Date-range read returns only the requested range.
- Replacing a series changes the version / hash.

### Phase 2 -- Research honesty ledger (Candidate B)

Goal: make every research choice visible, especially failed variants.

Suggested modules:

- `research/ledger.py`
- `research/pressure.py`
- `validation/research_pressure.py`
- `research/factory/` integration points

Implementation steps:

1. Add append-only `ResearchLedger` records for universe, features,
   parameters, filters, cost model, validation windows, seed, data
   contract, strategy hash, rejection reason and user override.
2. Add a small JSONL-backed writer using runtime paths. Include replay
   / resume safety: retrying a run must not corrupt previous records.
3. Add `ResearchPressureScore`: number of variants, parameter count,
   data length, number of manual interventions and OOS touches.
4. Wire the ledger into factory submit / batch / promote paths without
   changing strategy semantics.
5. Add validation-report text that explains research pressure in plain
   language.
6. Add optional hooks for PBO / Deflated Sharpe / purged CV only where
   existing primitives support them. Do not fake advanced statistics.

Reference usage:

- Use Qlib as a reference for end-to-end research workflow shape.
- Use vectorbt as a warning and reference: fast sweeps are powerful
  only if every tried variant is recorded.
- Use RD-Agent only as a proposal-engine pattern. Agent-generated
  factors are hypotheses, not evidence.

Tests:

- Ledger is append-only.
- Retry does not overwrite previous records.
- Rejected candidates are recorded.
- Manual override requires author and reason.
- Promotion report includes research pressure.
- Large parameter sweep records all tried parameter ranges.
- Missing ledger blocks promotion when policy requires it.

### Phase 3 -- Execution event replay and reconciliation (Candidate A)

Goal: rebuild a paper/live session from broker events alone.

Suggested modules:

- `execution/events.py`
- `execution/order_state.py`
- `execution/replay.py`
- `execution/reconciliation.py`
- `execution/fill_models.py`
- `analytics/tca.py`
- integration with `deployment/brokers.py` or the split broker package

Implementation steps:

1. Add canonical broker event dataclasses:
   `OrderCreated`, `OrderSubmitted`, `OrderAcknowledged`,
   `OrderPartiallyFilled`, `OrderFilled`, `CancelRequested`,
   `OrderCancelled`, `ReplaceRequested`, `OrderReplaced`,
   `OrderRejected`, `OrderExpired`, `CommissionReported`,
   `CashUpdated`, `PositionUpdated`, `Disconnected`,
   `Reconnected`.
2. Add `OrderLifecycleState` and a transition function. Unknown,
   duplicate and out-of-order events must produce explicit warnings or
   reconciliation diffs, not silent success.
3. Add replay that reconstructs order state, positions, cash, realised
   PnL, commissions and open orders.
4. Add reconciliation that compares replayed state against engine /
   broker state and reports positions, cash, PnL, open orders, orphan
   fills and missing commissions.
5. Add realistic fill models:
   market order with spread and depth;
   limit order with fill probability;
   partial fill;
   latency;
   rejection;
   stale quote refusal;
   min lot / tick size checks.
6. Add a basic TCA report: arrival price, average fill price,
   effective spread, slippage, delay cost, opportunity cost and
   unfilled quantity.
7. Keep live broker integration behind existing triple gates. Do not
   connect new real brokers in this phase.

Reference usage:

- Use NautilusTrader as a reference for deterministic event-driven
  architecture and backtest/live parity.
- Use LEAN as a reference for modular engine boundaries.
- Use Freqtrade as a reference for dry-run operator UX and crypto
  exchange capability checks.
- Use the Oxford HFT notes as a reference for limit-order fills,
  market impact, execution cost and market making.

Tests:

- Full fill rebuilds final position and cash.
- Partial fill then cancel leaves correct residual quantity.
- Duplicate fill is detected.
- Out-of-order event is detected.
- Restart between ack and fill replays correctly.
- Fill without local order creates an orphan diff.
- Missing commission creates a reconciliation diff.
- Limit order can remain unfilled.
- Stale quote refuses fill.
- TCA values are finite and sign-consistent.

### Phase 4 -- Portfolio optimisation and risk validation (Candidate F)

Goal: allocate capital under constraints, costs and validation, not by
headline Sharpe alone.

Suggested modules:

- `portfolio/allocation.py`
- `portfolio/constraints.py`
- `portfolio/risk_measures.py`
- `portfolio/optimizers.py`
- `portfolio/analytics.py`
- `portfolio/attribution.py`
- `portfolio/stress.py`
- `validation/portfolio_validation.py`

Implementation steps:

1. Add a common `PortfolioOptimizer` interface with `fit`, `predict`
   and `summary` methods. Keep it internal and lightweight.
2. Implement simple baselines first: equal weight, inverse volatility,
   cash / no-trade and benchmark tracker.
3. Add risk measures: variance, semi-variance, CVaR, maximum drawdown,
   average drawdown and turnover-aware net return.
4. Add constraints: min / max weights, long-only / long-short, gross
   exposure, net exposure, group exposure, cash floor, turnover and
   per-strategy capital cap.
5. Add one classical optimiser only after baselines pass. Prefer a
   small internal mean-risk or risk-budgeting implementation before
   optional dependency adapters.
6. Add walk-forward validation. Add purged / embargoed validation only
   if labels or windows overlap.
7. Add stress tests for noisy covariance, higher costs, missing assets,
   correlated drawdowns and liquidity shocks.
8. Add portfolio analytics reports:
   rolling returns;
   rolling volatility;
   rolling Sharpe;
   drawdown table;
   contribution to return;
   contribution to risk;
   exposure by group;
   benchmark-relative attribution;
   monthly / yearly summary.
9. Add optional adapters later:
   `SkfolioAdapter`, `RiskfolioAdapter`, `PyPortfolioOptAdapter`.
   Each adapter must be optional and skipped cleanly when dependency is
   absent.

Reference usage:

- skfolio is the main API-shape reference.
- Riskfolio-Lib is the reference for broad risk measures and risk
  contribution reporting.
- PyPortfolioOpt is the reference for classical efficient frontier,
  Black-Litterman, shrinkage and HRP baselines.
- R-Finance PerformanceAnalytics / PortfolioAnalytics /
  PortfolioAttribution are references for report shape, rolling risk,
  contribution tables and attribution terminology.

Tests:

- Weights sum to expected budget.
- Constraints cannot be violated silently.
- Costs reduce or preserve net performance; they never improve it.
- Walk-forward split does not use future data.
- Missing asset is handled according to policy.
- Equal weight and inverse volatility baselines are reproducible.
- Rolling analytics return finite values or documented NaN warmup.
- Contribution to return sums to portfolio return within tolerance.
- Contribution to risk sums to total risk within tolerance for the
  supported risk model.
- Optional adapters skip cleanly when dependency is not installed.

### Phase 4b -- Factor tear sheets and analytics reporting (Candidate H)

Goal: turn factor and strategy outputs into operator-readable reports
that reveal signal quality, turnover, decay and benchmark-relative
behaviour.

Suggested modules:

- `reporting/factor_tearsheet.py`
- `reporting/portfolio_analytics.py`
- `reporting/report_renderers.py`
- `validation/factor_diagnostics.py`

Implementation steps:

1. Add factor alignment helpers that accept factor values, forward
   returns, groups / sectors, costs and benchmark returns.
2. Add Information Coefficient, IC decay, rank autocorrelation,
   quantile returns, long / short spread, turnover and factor drawdown.
3. Add portfolio analytics report output: rolling returns, rolling
   volatility, rolling Sharpe, drawdown table, benchmark attribution
   and monthly / yearly summary.
4. Add deterministic text renderer first. HTML/PDF can come later
   through existing reporting infrastructure.
5. Include provenance in every report: policy hash, snapshot hash,
   data contract hash, factor / strategy hash and cost assumptions.
6. Refuse ambiguous index alignment, future-labelled data and forbidden
   OOS tier overlap.

Reference usage:

- Use Alphalens for factor tear-sheet structure.
- Use pyfolio for return / drawdown / benchmark report structure.
- Use R-Finance reporting packages as terminology references for
  performance and attribution tables.

Tests:

- IC sign matches a synthetic predictive factor.
- Random factor has near-zero IC within tolerance.
- Quantile report orders buckets correctly.
- Turnover is zero for constant ranks.
- Report refuses misaligned indexes.
- Report refuses forward returns that overlap forbidden OOS tiers.
- Text renderer output is deterministic.

### Phase 5 -- Strategy atlas and benchmark catalogue (Candidate E)

Goal: turn strategy references into a curated map, not a strategy
dump.

Suggested modules:

- `research/strategy_atlas.py`
- `research/strategy_benchmarks.py`
- `research/idea_sources.py`
- `research/strategy_graveyard.py` integration
- docs page under `docs/`

Implementation steps:

1. Add `StrategyAtlasEntry` with name, asset class, data needs,
   required engine support, cost sensitivity, overfit risk,
   implementation difficulty, benchmark expectation, status and owner.
2. Add statuses: `SUPPORTED`, `CANDIDATE`, `BLOCKED`, `REJECTED`,
   `BENCHMARK_ONLY`, `EXTERNAL_DATA_ONLY`.
3. Seed the first atlas slice with only testable ideas:
   ETF momentum rotation, dual momentum, multi-asset trend following,
   volatility targeting, ETF mean reversion, simple pairs, simple
   stat-arb, KNN single-stock example and controlled alpha combo.
4. Mark options-heavy, structured-credit, convertibles, tax-arbitrage
   and compliance-sensitive ideas as blocked until data, pricing,
   execution and legal review exist.
5. Add benchmark mapping for each entry: cash, buy-and-hold, equal
   weight, simple momentum / mean reversion, random comparable
   turnover or current production strategy.
6. Before implementing any template, query similarity and graveyard.
7. Add `IdeaSource` records for Quantpedia, QuantStart, Ernie Chan /
   EpChan, EliteQuant and future curated sources. Store source name,
   URL, claim summary, asset class, data needs, assumptions,
   testability and confidence.
8. Add docs that explain why the atlas refuses many tempting ideas.

Reference usage:

- Use the "151 Trading Strategies" PDF as the catalogue source.
- Use vectorbt-style sweeps only as atlas input when the full sweep
  config and rejected variants are recorded.
- Use Quantpedia / QuantStart / Ernie Chan-style sources only as idea
  discovery. Their claims must be re-tested under Aurora data
  contracts and validation gates.

Tests:

- Blocked entry cannot be promoted.
- Benchmark-only entry cannot become production.
- Entry without data requirements fails validation.
- Entry without benchmark expectation fails validation.
- Similar-to-graveyard entry is flagged.
- Source claim without independent validation cannot be promoted.
- Idea source loads deterministically and preserves URL / assumption
  metadata.
- Seed atlas loads deterministically.

### Phase 6 -- Strategy risk register and approval workflow (Candidate D)

Goal: require ownership and approval before paper/live promotion.

Suggested modules:

- `governance/risk_register.py`
- `governance/approvals.py`
- `governance/lifecycle.py`
- integration with `agent_gateway/` and `research/factory/`

Implementation steps:

1. Add `StrategyRiskRecord` with intended use, limitations,
   assumptions, operator id, optional reviewer, approval status,
   evidence hashes, risk limits, expiry and revalidation date.
2. Add lifecycle states: draft, researching, rejected, quarantined,
   validated, OOS-approved, shadow, paper, canary, live, degraded,
   retired, graveyard.
3. Add single-operator approval flow: operator reviews evidence,
   records limits, chooses approval state and signs the decision into
   the audit chain. Optional reviewer fields stay non-blocking unless
   multi-user mode is explicitly enabled.
4. Add promotion gate: refuse promotion if risk record is missing,
   expired, unapproved, hash-mismatched or warning threshold exceeded.
5. Store approval events in the audit chain.

Tests:

- Promotion without risk record fails.
- Expired risk record fails.
- Invalid approval state transition fails.
- Hash mismatch fails.
- Override requires author, reason and audit event.
- Retired strategy cannot be promoted without new record.

### Phase 7 -- Agentic research support (Candidate G)

Goal: let agents explain and challenge evidence, not create authority.

Suggested modules:

- `agent_gateway/research_agents.py`
- `agent_gateway/evidence_pack.py`
- `agent_gateway/agent_roles.py`
- `agent_gateway/prompt_injection_tests.py`
- reporting integration for explanation packs

Implementation steps:

1. Add explicit agent roles: data-quality reviewer, strategy-summary
   reviewer, risk reviewer, execution-cost reviewer, regime reviewer
   and report explainer.
2. Add an `EvidencePack` object containing only approved inputs:
   snapshot hash, policy hash, validation hash, strategy hash, data
   contract, audit references and source report paths.
3. Agents may read evidence packs and produce comments. They may not
   read locked OOS / FORWARD data, submit orders, approve promotions,
   read secrets or modify code.
4. Add disagreement-preserving report output. Do not collapse agent
   disagreement into a fake consensus.
5. Add source-required mode: every material claim must point to an
   evidence item.
6. Add prompt-injection fixtures: malicious strategy text, hostile web
   snippet, poisoned research note, secret-exfiltration request and
   OOS-bypass request.
7. Add hard fail-closed behaviour when evidence is missing, hash
   verification fails or the agent asks for a forbidden tool.

Reference usage:

- Use QuantAgent as a UX/reference for specialist market-analysis
  agents.
- Use Qlib / RD-Agent as references for automated research proposal
  flow.
- Keep all agent suggestions downstream of data contracts, research
  ledger, validation reports and approval workflow.

Tests:

- Agent cannot access locked OOS evidence.
- Agent cannot request broker action.
- Agent output without source fails in source-required mode.
- Prompt-injection fixture is refused.
- Missing evidence pack fails closed.
- Disagreement appears in final explanation pack.

Final programme stop condition:

- All seven phases either landed or have an explicit written blocker.
- `ruff`, `mypy`, focused tests and full fast pytest pass.
- Roadmap entries are updated with evidence paths.
- No new dependency was added without a dependency decision note.
- No feature can promote a strategy without data contract, research
  ledger, validation evidence and risk approval.

## Commit Plan

Recommended separation per future task: one commit per Rxx item, scoped
narrowly. The session 2026-05-08 pass landed eight item-scoped commits
(`064c535`, `2a506eb`, `bd90417`, `105046b`, `8a644df`, `9593e86`,
`e06761b`, `56160f9`) plus the earlier R11 commit (`1b600a7`).

Avoid bundling unrelated agent-local files (`.claude/`, `AGENTS.md`)
unless they are intentionally part of project policy.

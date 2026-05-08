# QuantForge Roadmap

Status: living roadmap
Last updated: 2026-05-08
Source: migrated from Desktop and normalised after v1.4 review
Scope: post-v1.4 backlog for QA, docs, AI, data, execution, performance and production hardening

Rule: this is a backlog, not an execution order. Work should move from
confidence to automation to production, not from the most spectacular item to
the most expensive incident.

---

## Current State

QuantForge v1.4 has a working protocol spine:

- ProtocolPolicy as code.
- DataProviderRegistry with provenance and tier posture.
- SnapshotStore with hash binding.
- ExperimentRegistry lineage.
- ValidationPipeline with mandatory gates.
- AgentAuditGateway with scoped tokens and hash-chained audit.
- Paper/live guard layer with broker safety primitives.

Verification snapshot from this workspace:

- `tests/test_spine_e2e.py`: 15 passed.
- Property suites: `tests/test_property.py` and `tests/test_property_v2.py` are active work.
- Collection observed: 2830 tests total; fast-suite selection collected 2794 tests after documented ignores and marker deselection.
- Full fast-suite pass was not re-verified in this roadmap update. Do not claim it unless run again.

Reference reports:

- `docs/v4_0_SPINE_REPORT.md`
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
Evidence: `tests/test_property.py`, `tests/test_property_v2.py`, `tests/conftest.py`, `CLAUDE.md`

Added coverage areas:

- Strategy signal bounds for BollingerMR, DualMomentum and ATRBreakout.
- Wrapper invariants for StopWrapper and VolTargetWrapper.
- ProtocolPolicy hash determinism and mutation sensitivity.
- Tier split partition invariants.
- Cost model invariants.
- Engine and metrics finite-value invariants.
- Hypothesis profiles: dev, ci and thorough.

Note: property tests exposed that Calmar can be `inf` when max drawdown is zero.
That is mathematically valid. Callers should handle it explicitly where finite
rankings are required.

Follow-up tracked as R16 below (Calmar/MAR zero-MDD policy decision).

---

## Recommended Execution Order

### Phase 1: Make the project easier to trust

Goal: reduce blind spots before adding more surface area.

Recommended order:

1. R15 API reference auto-generated.
2. R14 Guide from zero to live.
3. R12 Mutation testing.
4. R13 Protocol fuzzing.

Reason: documentation and test strength should lead production integrations.
Otherwise QuantForge becomes bigger before it becomes clearer. That is how
platforms learn to trip over their own shoelaces.

### Phase 2: Make research memory useful

Goal: turn past experiments into searchable operational knowledge.

Recommended order:

1. R9 RAG over research history.
2. R10 Continuous auto-research loop.
3. R8 LLM augmenter for Auditor.

Reason: first build memory, then automate loops, then add LLM observations.
Doing this backwards creates confident commentary on incomplete context.

### Phase 3: Harden data and production foundations

Goal: make real data and deployment reproducible before live complexity.

Recommended order:

1. R7 Distributed snapshots.
2. R2 Real alt-data feeds, one feed at a time.
3. R1 Lean live export.
4. R3 Compliance reporting endpoints.
5. R4 Real execution adapters.

Reason: live trading and compliance should depend on durable data provenance,
not on hope, cached files and heroic vibes.

### Phase 4: Optimise only measured bottlenecks

Goal: speed up what is proven slow.

Recommended order:

1. R5 GPU triage backend, only after CPU triage benchmarks prove bottleneck.
2. R6 Rust core engine, only after profiling identifies hot paths worth moving.

Reason: GPU and Rust can help, but they are not substitutes for measurement.
Speeding up the wrong path is still wrong, just with better branding.

---

## Active Backlog

### R12. Mutation testing

Status: next recommended QA item
Priority: high
Effort: 3 to 4 days
Area: QA
Suggested path: test tooling, CI profile, mutation config

Problem:

The suite is large, but size does not prove that tests catch broken behaviour.
Mutation testing checks whether small code changes are killed by tests.

Scope:

- Evaluate `mutmut` first.
- Start with `core/metrics.py`, `core/engine.py`, `core/costs.py`,
  `validation/pipeline.py` and `core/data_tiers.py`.
- Add a fast mutation profile for local use.
- Add an optional CI/nightly profile, not blocking every PR at first.

Definition of done:

- Mutation tool installed/configured.
- First report generated and documented.
- At least one weak-test area converted into stronger tests.
- Clear command documented in `CLAUDE.md` or docs.

Risk:

Mutation testing can be slow and noisy. Keep the first target narrow.

### R13. Protocol fuzzing

Status: pending
Priority: high
Effort: 1 week
Area: QA/security/protocol
Suggested paths: `tests/test_protocol_fuzz.py`, `cli/forge.py`,
`core/data_layer.py`, `core/data_tiers.py`, `agent_gateway/`

Problem:

The protocol has ceremony rules, tier gates and CLI entry points. These should
be attacked with malformed inputs before real operators do it accidentally.

Scope:

- Fuzz OOSGuard phases and unlock sequences.
- Fuzz tier names, date boundaries and empty/duplicated indices.
- Fuzz CLI argument parsing for tier-sensitive commands.
- Fuzz AgentGateway staged actions for invalid symbols, limits and signatures.

Definition of done:

- Hypothesis-based fuzz tests added.
- No unauthorized OOS_LOCKED or FORWARD read accepted.
- CLI returns clean argument errors, not tracebacks.
- Gateway rejects malformed actions deterministically.

### R15. API reference auto-generated

Status: pending
Priority: high
Effort: 3 to 4 days
Area: docs
Suggested paths: `docs/api/`, `docs/conf.py`, `.github/workflows/docs.yml`

Problem:

QuantForge has grown enough that manual API documentation will rot.

Scope:

- Use Sphinx with autodoc or mkdocs-material plus mkdocstrings.
- Generate reference pages for public packages only.
- Exclude experimental/private internals unless explicitly documented.
- Add a docs build command.

Definition of done:

- Docs build locally.
- Public modules render without import failures.
- CI/docs workflow exists or is documented as manual.
- README links to generated API reference.

Recommendation:

Prefer Sphinx if the priority is Python API completeness. Prefer MkDocs if the
priority is a nicer operator guide. For this repo, Sphinx first is the safer
choice.

### R14. Guide from zero to live

Status: pending
Priority: high
Effort: 1 week
Area: docs/onboarding
Suggested path: `docs/ZERO_TO_LIVE.md`

Problem:

The architecture is strong, but a new operator needs one guided path from
install to backtest, validation, paper and guarded live.

Scope:

- Installation and environment setup.
- Run a deterministic smoke backtest.
- Freeze or load a snapshot.
- Validate a strategy.
- Submit to research factory.
- Review queue and promotion ceremony.
- Paper trading path.
- Live trading checklist, without encouraging blind live deployment.

Definition of done:

- A fresh clone can follow the guide.
- Every command either works offline or states required credentials/data.
- All live steps include safety gates and explicit warnings.

### R9. RAG over research history

Status: pending
Priority: medium-high
Effort: 1 to 2 weeks
Area: AI/research memory
Suggested paths: `research/rag.py`, `research/factory/`, runtime archive paths

Problem:

ResearchFactory archives failures and review candidates, but that knowledge is
not easily searchable by an agent or operator.

Scope:

- Index research archive, review queue and experiment metadata.
- Support questions like which strategies failed due to leakage, costs,
  regime fragility or drawdown.
- Keep storage local by default.
- Make vector backend optional.

Definition of done:

- Query API exists.
- CLI or script can search historical research outcomes.
- Tests cover empty archive, corrupted rows and deterministic retrieval.

### R10. Continuous auto-research loop

Status: pending
Priority: medium
Effort: 1 week
Area: AI/research automation
Suggested path: `research/auto_loop/`

Problem:

Research generation exists in pieces, but not as a controlled scheduled loop.

Scope:

- Daily generation of N hypotheses.
- Submit through ResearchFactory.
- Write weekly report.
- Respect rate limits, budget, data tier rules and review queue caps.

Definition of done:

- Loop can run dry-run mode.
- Loop cannot access OOS_LOCKED/FORWARD.
- Outputs are auditable and resumable.
- Failures are archived with reasons.

Dependency:

Best done after R9, so the loop can learn from prior failures instead of
repeating them with fresh enthusiasm.

### R8. LLM augmenter for Auditor

Status: pending
Priority: medium
Effort: 1 week
Area: AI/auditor
Suggested path: `agents/auditor/llm_augmenter.py`

Problem:

Auditor reviewers are deterministic and safe, but may miss qualitative
observations.

Scope:

- Add provider abstraction for OpenAI/Anthropic-style clients.
- Prompt templates per reviewer.
- LLM findings capped at MEDIUM severity.
- No LLM finding can override deterministic HARD_FAIL/PASS authority.

Definition of done:

- Mocked tests pass offline.
- Cap logic prevents severity escalation.
- Prompt templates include policy hash and strategy context.
- No credentials stored in repo.

### R7. Distributed snapshots

Status: pending
Priority: medium-high before real feeds/live
Effort: 2 weeks
Area: data/provenance
Suggested path: `core/snapshots_distributed.py`

Problem:

SnapshotStore is local SQLite plus parquet. That is fine for one machine, but
weak for teams, replication and production data provenance.

Scope:

- Add backend interface.
- Support local, PostgreSQL metadata and S3-compatible object storage.
- Preserve sha256 and policy_hash semantics.
- Keep local backend as default.

Definition of done:

- Existing local behaviour unchanged.
- New backend contract tested with fake/object-store temp implementation.
- Integrity verification works across backends.
- Migration path documented.

### R2. Real alt-data feeds

Status: pending
Priority: medium
Effort: 1 week per feed
Area: data/integrations
Suggested path: `altdata/`

Problem:

Alt-data adapters are mock-friendly. Production research needs real providers,
rate limits, credentials and backfill.

Recommended feed order:

1. FRED macro, easiest and highest signal-to-noise.
2. SEC filings, strong provenance and public-data posture.
3. On-chain crypto, useful but provider-specific.
4. Options flow, high value but vendor-sensitive.
5. Reddit/Twitter/news, noisy and API-policy fragile.
6. Satellite/geospatial, expensive and specialist.

Definition of done per feed:

- Credentials via environment variables only.
- Rate limiting per provider.
- Backfill path.
- Metadata includes source, as-of date and content hash where possible.
- Integration tests are marked and skipped safely without credentials.

### R1. Lean live-trading export

Status: pending
Priority: medium
Effort: 1 week for first real path
Area: live/export
Suggested path: `exports/lean/live.py`

Problem:

Current Lean export is a scaffold with provenance. Real live deployment needs
LEAN cloud/project integration and pre-deploy checks.

Scope:

- Package export as Lean project.
- Verify provenance before deploy.
- Add optional Lean CLI/cloud API integration.
- Keep dry-run mandatory by default.

Definition of done:

- Exported project can be validated locally or via Lean tooling.
- Metadata verification blocks mismatched policy/spec hash.
- Live deploy requires explicit operator flag.

### R3. Compliance reporting endpoints

Status: pending
Priority: medium-low until live execution is closer
Effort: 2 to 3 weeks plus legal/domain review
Area: compliance
Suggested path: `compliance/`

Problem:

MiFID II, 13F and CTA modules exist, but production reporting needs exact
schemas, filing rules and possibly external endpoints.

Scope:

- Split into jurisdiction-specific deliverables.
- Add schema validation.
- Add fixture-based golden files.
- Document legal assumptions.

Definition of done:

- At least one report type has schema/golden-file validation.
- Inputs and assumptions are explicit.
- No report is described as regulator-ready without review.

### R4. Real execution adapters

Status: pending
Priority: medium-low, high risk
Effort: 3 to 4 weeks for serious first slice
Area: execution/live
Suggested paths: `execution/`, `deployment/brokers/`

Problem:

Broker adapters and execution algorithms exist, but serious execution needs
partial fills, reconciliation, order routing, venue details and failure modes.

Recommended order:

1. Paper execution simulator with partial fills and slippage.
2. Broker reconciliation hardening.
3. One broker real adapter deepened end to end.
4. Smart order routing only after real fill/reconcile data exists.

Definition of done:

- Partial fills modelled.
- Reconciliation detects broker/local drift.
- Kill switch and audit log remain non-bypassable.
- Live operations require explicit operator ceremony.

### R5. GPU triage backend

Status: deferred until benchmark proves need
Priority: low-medium
Effort: 1 week
Area: performance
Suggested path: `triage/gpu_backend.py`

Problem:

Triage is CPU numpy. GPU may help for very large variant screens.

Gate before starting:

- Benchmark CPU triage on realistic workload.
- Identify target speedup and memory limits.
- Confirm CuPy/PyTorch install posture.

Definition of done:

- CPU and GPU outputs match within tolerance.
- Lazy import keeps base install light.
- Fallback path remains deterministic.

### R6. Rust core engine

Status: deferred until profiler proves need
Priority: low-medium
Effort: 4 to 6 weeks
Area: performance/native
Suggested path: `core/engine_rs/`

Problem:

Rust/PyO3 may speed up hot paths, but adds build complexity.

Gate before starting:

- Profile real workloads.
- Identify functions where Python/Numba are not enough.
- Define exact parity tests against Python engine.

Definition of done:

- Native extension optional.
- Python fallback remains canonical.
- Cross-platform wheel/build story documented.
- Engine parity tests pass.

---

### R16. Calmar / MAR policy for zero-MDD inputs

Status: pending, design call
Priority: low
Effort: half a day
Area: metrics/contract
Suggested path: `core/metrics.py`, `tests/test_property_v2.py`

Problem:

R11 property test surfaced that `compute_metrics` returns `Calmar = inf` and
`MAR = inf` when MDD == 0 (constant positive returns). Mathematically valid
but not always usable as a ranking key.

Decision options:

- Keep current behaviour and document the contract in `Metrics` docstring.
- Return `None` or `nan` when MDD == 0 to force callers to handle explicitly.
- Return a large sentinel (e.g. `1e9`) to keep numeric comparisons working.

Definition of done:

- One option chosen and applied in `core/metrics.py`.
- Property test in `tests/test_property_v2.py` updated to match the new
  contract.
- `Metrics` docstring documents the rule.

### R17. Markov switching API drift

Status: pending or accept-as-wontfix
Priority: low
Effort: half a day to 2 days depending on choice
Area: regime/ML
Suggested path: `regime/markov_switching.py`,
`tests/test_markov_switching.py`

Problem:

9 pre-existing failures in `tests/test_markov_switching.py` come from
statsmodels API drift. They are unrelated to QuantForge logic but make the
baseline test command report failures.

Decision options:

- Pin statsmodels to a version that still exposes the old API.
- Update `regime/markov_switching.py` to use the current statsmodels API
  and re-green the tests.
- Mark the test module with `@pytest.mark.skip(reason="statsmodels API drift")`
  and document as wontfix in `CLAUDE.md`.

Definition of done:

- One option chosen and applied.
- Baseline test command no longer reports markov failures (skipped or fixed).
- Decision recorded in `CHANGELOG.md`.

### R18. Lint config cosmetic false positive

Status: pending
Priority: very low
Effort: 1 hour
Area: tests
Suggested path: `tests/test_lint_config.py`

Problem:

`test_lint_config::test_no_unmarked_live_data_loads` is documented as a
cosmetic AST scanner false positive in `CLAUDE.md`. Either fix the scanner
or skip the test with a comment explaining why.

Definition of done:

- Test either passes or is skipped with a clear reason.
- `CLAUDE.md` known-issues list shrinks accordingly.

---

## Deferred Or Split Items

These are not rejected. They are too broad to start as single tasks:

- "Alt-data feeds reales" must be split provider by provider.
- "Exchange execution adapters reales" must be split broker by broker and
  failure mode by failure mode.
- "Compliance endpoints reales" must be split by jurisdiction/report and
  reviewed against actual filing requirements.
- "Rust core engine" must start with profiling, not enthusiasm.

---

## Suggested Next Task

Recommended next item: R15 API reference auto-generated.

Why:

- Low risk.
- High clarity gain.
- Helps reveal broken imports and unclear public/private APIs.
- Pairs well with the newly expanded property-based tests.

Second choice: R12 mutation testing, if the priority is test strength over docs.

---

## Commit Plan

Recommended separation:

1. Documentation/roadmap sync.
2. Property-based testing extension.
3. Next roadmap implementation task.

Avoid bundling unrelated agent-local files unless they are intentionally part of
project policy.


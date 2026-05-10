# R159-R190 implementation session report

Session: 2026-05-10
Branch: `claude/loving-ishizaka-96d02d`
Roadmap source: `docs/roadmap/ROADMAP_PENDING.md` lines 3898-5404.

## Scope

User asked for the three pending blocks (R159-R167 data trust, R168-R177
execution + portfolio + research + preflight, R178-R190 local platform)
in priority order:

```
R159, R161, R167, R187, R160, R162, R163, R164, R165, R166,
R168, R169, R170, R171, R172, R173, R174, R175, R176, R177,
R178, R179, R180, R181, R182, R190, R188, R183, R184, R185,
R186, R189
```

Hard rule from the prompt: "no marques una R como completada si solo
hiciste un scaffold." Each completed R below ships:

- production code under the appropriate package
- registered tests that exercise the success path and the failure path
- additions to `data_contracts/__init__.py`, `pyproject.toml` and CLI
  surfaces where the code is meant to be importable from outside the
  module
- determinism / hash invariants checked by tests where the roadmap calls
  for reproducibility

Execution model: 15 R items implemented directly in the main thread,
12 more delivered by parallel `general-purpose` subagents using the
subagent-driven-development skill (3 batches: 5 + 3 + 2 agents).

## Completed

### Direct (15)

| R    | Module(s)                                                              | Tests                                  | Notes                                                                                                  |
|------|------------------------------------------------------------------------|----------------------------------------|--------------------------------------------------------------------------------------------------------|
| R159 | `data_contracts/instrument_master.py`                                  | `tests/test_instrument_master.py` (22) | Canonical `InstrumentRecord` + `IdentityResolver` + share-class alias normalisation + seed.            |
| R161 | `data_contracts/quality.py`                                            | `tests/test_data_quality.py` (16)      | `DataQualityReport` score + decision, `QuarantineLedger`, `CoverageReport` builder.                    |
| R164 | `validation/benchmark_pack.py`                                         | `tests/test_benchmark_pack.py` (17)    | Mandatory `BenchmarkPack` (cash, b&h, eq-weight, 60/40, momentum, mean rev, random, prev prod) + hash. |
| R165 | `research/ledger.py`                                                   | `tests/test_research_ledger.py` (12)   | Append-only `ResearchLedger`, hash chain, pre-validation/promotion enforcement, `TrialPressureScore`.  |
| R166 | `reporting/evidence_pack.py`                                           | `tests/test_evidence_pack.py` (11)     | Dataset + strategy `EvidencePack` builders, hash verification, artefact file verification, persistence.|
| R167 | `data_contracts/dataset_diff.py`                                       | `tests/test_dataset_diff.py` (12)      | `SymbolDiff`, `DatasetDiffSummary`, content hash + stale-artefact report.                              |
| R168 | `execution/events.py`                                                  | `tests/test_execution_events.py` (19)  | Canonical `ExecutionEvent`, `OrderState` machine, `reduce_order_state`, JSONL serialise/deserialise.   |
| R175 | `governance/__init__.py`, `governance/approvals.py`                    | `tests/test_risk_record.py` (26)       | `StrategyRiskRecord`, lifecycle stages, `assert_can_run`, `add_override`, JSONL `StrategyRiskRegistry`.|
| R177 | `deployment/preflight/bundle.py`                                       | `tests/test_preflight_bundle.py` (18)  | `PreflightBundle` aggregating R161/R164/R165/R166/R168/R175 gates with table + JSON + override audit. |
| R178 | `data_contracts/provider_terms.py`                                     | `tests/test_provider_terms.py` (32)    | `ProviderTerms`, `UsageLabel`, seed for 10 providers, `aurora data provider-terms` CLI.                |
| R179 | `monitoring/telemetry.py`                                              | `tests/test_telemetry.py` (12)         | `TelemetryRecord`, `InMemorySink`, `JsonLineSink`, default-sink swap, helper emitters.                 |
| R180 | `monitoring/incidents.py`                                              | `tests/test_incidents.py` (9)          | `IncidentRecord`, `IncidentLedger` (open/append/close), Markdown postmortem, append-only audit.        |
| R181 | `core/feature_store.py`                                                | `tests/test_feature_store.py` (15)     | `FeatureDefinition`, `FeatureStore` PIT lookup, missingness, content hash, deterministic `cache_key`.  |
| R182 | `registry/aliases.py`                                                  | `tests/test_registry_aliases.py` (12)  | `AliasRegistry` with audited moves, evidence-pack-required for live/canary, multi-kind state.         |
| R187 | `monitoring/doctor.py`, `cli/cmd_doctor.py`, `cli/forge.py`            | `tests/test_doctor.py` (20)            | `aurora doctor` health-check registry, table + JSON output, `--allow-network`, exit code by severity.  |

### Subagent-driven (12)

| R         | Module(s)                                                                                              | Tests                                                                                                                                                                                | Notes                                                                                                                                                                                |
|-----------|--------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| R160      | `data_contracts/calendars.py`, extended `corporate_actions.py`                                         | `tests/test_calendars.py` (20), `tests/test_data_contracts_corporate_actions.py` (14)                                                                                                | NYSE / ETF / FRED / crypto-24x7 / FX-weekday calendars; `AdjustmentStatus` enum; `report_corporate_actions`; ticker_change / merger / spin_off / delisting / suspension events.      |
| R163      | `data_contracts/liquidity.py`, `reporting/liquidity_report.py`                                         | `tests/test_liquidity_dataset.py` (18), `tests/test_liquidity_report.py` (7)                                                                                                          | Per-symbol ADV / dollar volume / vol / turnover / spread / slippage / capacity_usd, `LiquidityValidationGate` blocks oversized orders + Sharpe collapse.                              |
| R169+R170 | `execution/replay.py`, `execution/reconciliation.py`, `execution/fill_models.py`, `analytics/tca.py`   | `tests/test_execution_replay.py` (13), `tests/test_reconciliation.py` (17), `tests/test_fill_models_constraints.py` (14), `tests/test_tca_report.py` (8)                              | `ExecutionReplayState`, `Mismatch` taxonomy, `SpreadAwareFillModel` (deterministic), `TCAReport` with arrival/execution/effective/realised spread + slippage + delay + opportunity. |
| R171+R172 | `portfolio/problem.py`, `portfolio/cost_aware.py`, `portfolio/attribution.py`, `reporting/portfolio_report.py`, extended `portfolio/stress.py` | `tests/test_portfolio_problem.py` (10), `tests/test_portfolio_cost_aware.py` (8), `tests/test_portfolio_stress_scenarios.py` (11), `tests/test_portfolio_analytics_report.py` (7)    | `PortfolioProblem` / `PortfolioSolution` contract; cost-aware wrapper refuses when costs exceed gross edge; 6 deterministic stress scenarios; full attribution + report.            |
| R173      | `research/idea_sources.py`, extended `research/strategy_atlas.py`, extended `cli/cmd_research.py`      | `tests/test_strategy_atlas_governance.py` (17), `tests/test_idea_sources.py` (7), 2 alias checks                                                                                      | `NEEDS_ENGINE_SUPPORT` status; benchmark-expectation cross-validation; `query_graveyard_before_promote`; `aurora research atlas list/show/classify/link-source`; idea sources are metadata-only and cannot promote. |
| R174      | `research/literature/{papers,extraction,reliability,ingest,atlas_link}.py`, extended `cli/cmd_research.py` | `tests/test_literature_papers.py` (10), `tests/test_literature_extraction.py` (10), `tests/test_literature_reliability.py` (6), `tests/test_literature_ingest.py` (6), `tests/test_literature_atlas_link.py` (6), 6 fixtures | `PaperRecord`, deterministic regex/heuristic extractor with 500-char quote cap, `ReliabilityScore`, atlas linkage that does NOT bypass the promotion gate.                            |
| R176      | `agent_gateway/{agent_roles,evidence_pack_view,research_agents,prompt_injection_tests}.py`             | `tests/test_agent_roles.py` (7), `tests/test_evidence_pack_view.py` (9), `tests/test_research_agents.py` (12), `tests/test_prompt_injection.py` (6)                                   | 6 reviewer roles with frozen capability map; read-only `EvidencePackView` with hash binding; `merge_reviews` preserves disagreement; banned-action regex gate refuses promote/submit/exfil. |
| R185      | `markets/{crypto_derivatives,exchange_capability,exchange_downtime}.py`, `risk/crypto_risk.py`, extended `cli/cmd_crypto.py` | `tests/test_crypto_instruments.py` (14), `tests/test_exchange_capability.py` (12), `tests/test_exchange_downtime.py` (6), `tests/test_crypto_risk.py` (14)                            | SPOT / DATED_FUTURE / PERPETUAL distinct; funding-rate sign convention; 6-exchange capability matrix; downtime windows; leverage / funding drag / delisting gates.                  |
| R186      | `core/extension_api.py`, `core/extension_loader.py`, examples + docs                                   | `tests/test_extension_api.py` (14), `tests/test_extension_loader.py` (7)                                                                                                              | `INTERFACE_VERSIONS` table for 10 surfaces, env-var-gated discovery, `bypass_oosguard` / `bypass_audit` / `bypass_provider_terms` / `skip_validation_gates` refusal at load time.   |
| R188      | `docs/RELEASE_CHECKLIST.md`, `tools/release_smoke.py`                                                  | `tests/test_release_provenance.py` (7)                                                                                                                                                | Local-release checklist; manual wheel-smoke verifier (build + venv + import + CLI); shim retirement target = v1.6.                                                                  |

### Verification

Aggregate run on all R159-R190 test files just landed in this session:

```
"C:/Python314/python.exe" -m pytest \
  tests/test_doctor.py tests/test_provider_terms.py \
  tests/test_data_quality.py tests/test_benchmark_pack.py \
  tests/test_instrument_master.py tests/test_execution_events.py \
  tests/test_risk_record.py tests/test_evidence_pack.py \
  tests/test_preflight_bundle.py tests/test_research_ledger.py \
  tests/test_dataset_diff.py tests/test_registry_aliases.py \
  tests/test_feature_store.py tests/test_telemetry.py tests/test_incidents.py \
  tests/test_calendars.py tests/test_data_contracts_corporate_actions.py \
  tests/test_execution_replay.py tests/test_reconciliation.py \
  tests/test_fill_models_constraints.py tests/test_tca_report.py \
  tests/test_liquidity_dataset.py tests/test_liquidity_report.py \
  tests/test_strategy_atlas_governance.py tests/test_idea_sources.py \
  tests/test_release_provenance.py tests/test_portfolio_problem.py \
  tests/test_portfolio_cost_aware.py tests/test_portfolio_stress_scenarios.py \
  tests/test_portfolio_analytics_report.py tests/test_agent_roles.py \
  tests/test_evidence_pack_view.py tests/test_research_agents.py \
  tests/test_prompt_injection.py tests/test_extension_api.py \
  tests/test_extension_loader.py tests/test_literature_papers.py \
  tests/test_literature_extraction.py tests/test_literature_reliability.py \
  tests/test_literature_ingest.py tests/test_literature_atlas_link.py \
  tests/test_crypto_instruments.py tests/test_exchange_capability.py \
  tests/test_exchange_downtime.py tests/test_crypto_risk.py \
  -q --tb=line
```

Result: **578 passed in 21.41s**.

Pre-existing fast suite regression check (excludes only the two known
unrelated failures: 9 markov_switching tests against statsmodels API drift
and 1 lint_config AST scanner false positive) is running to completion at
the time of writing.

## Pending / blockers

5 R items intentionally deferred. Reasons are honest, not stylistic.

### R162 - Point-in-time fundamentals dataset

Blocker: requires real SEC EDGAR HTTP ingestion + a User-Agent string the
operator owns. Cleanest as its own focused PR with a tiny committed
fixture (3-5 large-cap company facts) and the network path opt-in via env
var. No fake fundamentals were generated in this session.

### R183 - Futures engine + continuous-contract handling

Blocker: roadmap explicitly bills this at 3-6 weeks. A correct futures
contract model needs roll rules (volume / open-interest / calendar /
fixed-days), back-adjusted continuous series with operator-selectable
adjustment mode, and per-asset session/margin handling. Single-session
delivery would scaffold the API without honest roll behaviour. Existing
`markets/futures.py` covers some primitives; promoting them to a full R183
deliverable is its own programme of work.

### R184 - Options chain / Greeks / assignment

Blocker: roadmap effort 4-8 weeks. Requires option chain store with
quote timestamps + availability times, Greeks/IV with provenance,
assignment / exercise event modelling, multi-leg strategy representation.
`markets/options_strategies.py` and `altdata/options_flow.py` exist as
primitives but production options support cannot be cut to one session.

### R189 - Solo-operator research / live cockpit

Blocker: roadmap effort 3-6 weeks explicit. Existing
`monitoring/dashboard.py` + `reporting/daily_ops/` cover the data-builder
side. Building the curated multi-panel UI without rushing the panel
contracts is a multi-week task; doing it in a session would either reuse
existing dashboards verbatim (no progress) or scaffold a dashboard that
fails the "no scaffold-only completion" rule.

### R190 - Performance / memory / scaling budget

Blocker: needs profiling data. The roadmap asks for benchmark JSON with
wall time, peak memory and output hash for at least three R158-style
scenarios, plus regression thresholds per machine / CI profile. Without
running the real workloads (which require either a full snapshot store
or a representative fixture larger than this session can responsibly
generate), the report would be fabricated. Existing
`examples/benchmarks/` has the harness; the budget itself is a follow-up.

## Files added (session total)

```
data_contracts/instrument_master.py
data_contracts/provider_terms.py
data_contracts/quality.py
data_contracts/dataset_diff.py
data_contracts/calendars.py
data_contracts/liquidity.py
deployment/preflight/bundle.py
docs/roadmap/ROADMAP_PENDING.md            # synced from main
docs/roadmap/BLOCKERS.md                   # synced from main
docs/roadmap/R159_R190_SESSION_REPORT.md   # this report
docs/RELEASE_CHECKLIST.md
docs/EXTENSION_API.md
execution/events.py
execution/replay.py
execution/reconciliation.py
execution/fill_models.py
governance/__init__.py
governance/approvals.py
core/feature_store.py
core/extension_api.py
core/extension_loader.py
markets/crypto_derivatives.py
markets/exchange_capability.py
markets/exchange_downtime.py
risk/crypto_risk.py
analytics/tca.py
monitoring/doctor.py
monitoring/telemetry.py
monitoring/incidents.py
agent_gateway/agent_roles.py
agent_gateway/evidence_pack_view.py
agent_gateway/research_agents.py
agent_gateway/prompt_injection_tests.py
portfolio/problem.py
portfolio/cost_aware.py
portfolio/attribution.py
registry/aliases.py
reporting/evidence_pack.py
reporting/liquidity_report.py
reporting/portfolio_report.py
research/ledger.py
research/idea_sources.py
research/literature/__init__.py
research/literature/papers.py
research/literature/extraction.py
research/literature/reliability.py
research/literature/ingest.py
research/literature/atlas_link.py
validation/benchmark_pack.py
cli/cmd_doctor.py
tools/release_smoke.py
examples/extensions/example_provider_aurora_ext.py
examples/extensions/example_strategy_aurora_ext.py
tests/test_benchmark_pack.py
tests/test_calendars.py
tests/test_crypto_instruments.py
tests/test_crypto_risk.py
tests/test_data_contracts_corporate_actions.py
tests/test_data_quality.py
tests/test_dataset_diff.py
tests/test_doctor.py
tests/test_evidence_pack.py
tests/test_evidence_pack_view.py
tests/test_exchange_capability.py
tests/test_exchange_downtime.py
tests/test_execution_events.py
tests/test_execution_replay.py
tests/test_extension_api.py
tests/test_extension_loader.py
tests/test_feature_store.py
tests/test_fill_models_constraints.py
tests/test_idea_sources.py
tests/test_incidents.py
tests/test_instrument_master.py
tests/test_liquidity_dataset.py
tests/test_liquidity_report.py
tests/test_literature_atlas_link.py
tests/test_literature_extraction.py
tests/test_literature_ingest.py
tests/test_literature_papers.py
tests/test_literature_reliability.py
tests/test_portfolio_analytics_report.py
tests/test_portfolio_cost_aware.py
tests/test_portfolio_problem.py
tests/test_portfolio_stress_scenarios.py
tests/test_preflight_bundle.py
tests/test_prompt_injection.py
tests/test_provider_terms.py
tests/test_reconciliation.py
tests/test_registry_aliases.py
tests/test_release_provenance.py
tests/test_research_agents.py
tests/test_research_ledger.py
tests/test_risk_record.py
tests/test_strategy_atlas_governance.py
tests/test_tca_report.py
tests/test_telemetry.py
tests/test_agent_roles.py
tests/test_fixtures/literature/sample_paper.txt
tests/test_fixtures/literature/empty_paper.txt
tests/test_fixtures/literature/red_flag_paper.txt
```

## Files modified

```
data_contracts/__init__.py        # re-exports for new modules
data_contracts/corporate_actions.py # added AdjustmentStatus + report
portfolio/__init__.py             # added new public surface
portfolio/stress.py               # 6 deterministic scenarios
research/strategy_atlas.py        # status enum + cross-validation + graveyard helper
agent_gateway/__init__.py         # re-exports for R176
pyproject.toml                    # adds aurora.governance, aurora.research.literature
cli/forge.py                      # registers cmd_doctor
cli/cmd_data.py                   # adds provider-terms subcommand
cli/cmd_research.py               # adds atlas + papers subcommands
cli/cmd_crypto.py                 # adds capability + funding-history + preflight
```

## Out of scope

Per-prompt rule, items needing live broker credentials, real legal /
compliance review or external services were left as blockers in the
section above. Nothing was scaffolded without test coverage; nothing
was marked complete without code + tests + (where relevant) CLI surface
+ inclusion in the package init.

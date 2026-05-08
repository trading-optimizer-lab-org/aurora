# Module Production Status (R47)

Status matrix for cross-asset, signal, risk, dataeng, infra, marketdata
and altdata modules. Operators wiring downstream pipelines should read
this before depending on a module.

## Status semantics

| Label | Meaning |
|---|---|
| `production` | Covers a real workload, real data, real edge cases. Has at least one real-data integration test. |
| `scaffold` | Shape is right; behaviour is incomplete. Will compile and may pass mock-friendly unit tests, but should not be wired into a real strategy without a follow-up implementation pass. |
| `mock-only` | Returns deterministic placeholder values for tests. Real provider integration absent. |
| `experimental` | Speculative; see roadmap R48 for triage outcome. |

If a module is not listed here, treat it as `scaffold` until classified.

## `core/`

| Module | Status |
|---|---|
| `core/engine.py` | production |
| `core/engine_multi.py` | production |
| `core/engine_jit.py` | production |
| `core/engine_intraday.py` | production |
| `core/costs.py` | production |
| `core/costs_intraday.py` | production |
| `core/metrics.py` | production |
| `core/data_layer.py` | production |
| `core/data_tiers.py` | production |
| `core/protocol_policy.py` | production |
| `core/data_providers/yahoo.py` | production |
| `core/data_providers/csv.py` | production |
| `core/data_providers/snapshot.py` | production |
| `core/data_providers/synthetic.py` | production |
| `core/data_providers/openbb.py` | scaffold |
| `core/data_providers/ccxt_provider.py` | scaffold (lazy ccxt; sandbox-default) |
| `core/snapshots.py` | production |
| `core/snapshots_distributed.py` | production (interface + local backend; remote drivers reserved) |
| `core/audit_rotation.py` | production |
| `core/snapshot_repair.py` | production |
| `core/runtime_paths.py` | production |
| `core/seed.py` | production |
| `core/features.py` | production |
| `core/realtime.py` | scaffold |
| `core/bars.py` | production |
| `core/slippage.py` | production |
| `core/taxes.py` | production |
| `core/config.py` | production |
| `core/logging.py` | production |
| `core/sqlite_utils.py` | production |

## `validation/`

| Module | Status |
|---|---|
| `validation/walk_forward.py` | production |
| `validation/monte_carlo.py` | production |
| `validation/spp.py` | production |
| `validation/deflated_sharpe.py` | production |
| `validation/lookahead_check.py` | production |
| `validation/noise_injection.py` | production |
| `validation/gap_sim.py` | production |
| `validation/retraining.py` | production |
| `validation/purged_cv.py` | production |
| `validation/cscv_pbo.py` | production |
| `validation/structural_breaks.py` | production |
| `validation/scenarios.py` | production |
| `validation/tail_risk.py` | production |
| `validation/correlation_stress.py` | production |
| `validation/pipeline.py` | production |

## `ga/`

| Module | Status |
|---|---|
| `ga/runner.py` | production |
| `ga/fitness.py` | production |
| `ga/bayes_opt.py` | production |
| `ga/seed_population.py` | production |
| `ga/multi_asset_runner.py` | production |

## `strategies/`

Library entries are production; wrappers (Stop, VolTarget) are
production. Pair / online / seq-model entries are scaffold-grade where
they depend on optional ML extras.

| Module | Status |
|---|---|
| `strategies/library/ma_cross.py` | production |
| `strategies/library/rsi_meanrev.py` | production |
| `strategies/library/tsmom.py` | production |
| `strategies/library/donchian.py` | production |
| `strategies/library/bollinger_mr.py` | production |
| `strategies/library/dual_momentum.py` | production |
| `strategies/library/atr_breakout.py` | production |
| `strategies/library/stop_wrapper.py` | production |
| `strategies/library/voltarget_wrapper.py` | production |
| `strategies/library/pair_trade.py` | production |
| `strategies/library/online_learner.py` | scaffold (sklearn dep) |
| `strategies/library/seq_model.py` | scaffold (torch dep) |
| `strategies/library/pair_discovery.py` | scaffold |
| `strategies/library/statarb_mr.py` | scaffold |

## `agent_gateway/`, `agents/auditor/`, `research/`, `triage/`, `reporting/`, `exports/`, `deployment/`

| Module | Status |
|---|---|
| `agent_gateway/` (gateway, tokens, audit) | production |
| `agents/auditor/` (reviewers, orchestrator) | production |
| `agents/auditor/llm_augmenter.py` | production (mock provider; real providers gated by API key) |
| `research/factory/` | production |
| `research/rag.py` | production |
| `research/auto_loop/` | production |
| `triage/` | production |
| `reporting/tearsheet.py` | production |
| `reporting/daily_ops/builder.py` | production |
| `exports/lean/` | scaffold (Lean code generation; cloud deploy gated) |
| `deployment/preflight.py` | production |
| `deployment/sizing.py` | production |
| `deployment/allocator.py` | production |
| `deployment/hrp.py` | production |
| `deployment/risk_optim.py` | production |
| `deployment/black_litterman.py` | production |
| `deployment/cov_shrinkage.py` | production |
| `deployment/risk_parity.py` | production |
| `deployment/liquidity.py` | production |
| `deployment/brokers.py` | scaffold (Paper is production; IB / Alpaca / Coinbase / Kraken adapters need real credentials) |
| `deployment/ccxt_adapter.py` | scaffold (sandbox by default; live triple-gated) |
| `deployment/live.py` | scaffold (lumibot-backed) |
| `deployment/paper.py` | scaffold (lumibot-backed) |

## `markets/`

All `mock-only`. The entries describe asset-class-specific primitives
(bonds curve, FX cross, futures roll, options chain, crypto basis, ETF
arbitrage, etc) that exercise expected shapes against synthetic data.
Real-market integration requires per-asset-class data provider work.

| Module | Status |
|---|---|
| `markets/bonds.py` | mock-only |
| `markets/cef_premium.py` | mock-only |
| `markets/commodities_physical.py` | mock-only |
| `markets/credit.py` | mock-only |
| `markets/crypto_basis.py` | mock-only |
| `markets/etf_arbitrage.py` | mock-only |
| `markets/forex.py` | mock-only |
| `markets/futures.py` | mock-only |
| `markets/options_strategies.py` | mock-only |
| `markets/volatility_products.py` | mock-only |

## `signals/`

Mixed. Classical-signal modules are `scaffold`; HFT-microstructure and
event-driven entries that require tick data are `mock-only`.

| Module | Status |
|---|---|
| `signals/calendar_effects.py` | scaffold |
| `signals/cross_asset_momentum.py` | scaffold |
| `signals/cross_listing_arb.py` | mock-only |
| `signals/crypto_funding_arb.py` | mock-only |
| `signals/event_driven.py` | mock-only |
| `signals/microstructure_hft.py` | mock-only |
| `signals/risk_premia.py` | scaffold |
| `signals/vol_surface.py` | mock-only |

## `risk/`

Real algorithms; the implementations are correct but not yet wired
into a production risk-budgeting flow.

| Module | Status |
|---|---|
| `risk/conditional_dd.py` | scaffold |
| `risk/equal_marginal_vol.py` | scaffold |
| `risk/expected_shortfall.py` | scaffold |
| `risk/herc.py` | scaffold |
| `risk/max_diversification.py` | scaffold |
| `risk/most_diversified.py` | scaffold |
| `risk/risk_budgeting.py` | scaffold |
| `risk/risk_parity_factor.py` | scaffold |
| `risk/spectral_risk.py` | scaffold |
| `risk/stress_var.py` | scaffold |

## `dataeng/`

All `scaffold` -- enterprise data-engineering integrations (airflow,
dbt, kafka, flink, great_expectations, schema_registry, star_schema,
materialized_views, cdc_capture, data_lineage). Each is a thin
compatibility surface that real DAG / pipeline code can plug into;
none ship with a production runtime today.

| Module | Status |
|---|---|
| `dataeng/airflow_dags.py` | scaffold |
| `dataeng/cdc_capture.py` | scaffold |
| `dataeng/data_lineage.py` | scaffold |
| `dataeng/dbt_runner.py` | scaffold |
| `dataeng/flink_processor.py` | scaffold |
| `dataeng/great_expectations.py` | scaffold |
| `dataeng/kafka_streams.py` | scaffold |
| `dataeng/materialized_views.py` | scaffold |
| `dataeng/schema_registry.py` | scaffold |
| `dataeng/star_schema.py` | scaffold |

## `infra/`

Mostly `scaffold` operational primitives. The Kubernetes manifests are
configuration, not code.

| Module | Status |
|---|---|
| `infra/cloud_sync.py` | scaffold |
| `infra/distributed.py` | scaffold |
| `infra/gpu_runner.py` | scaffold |
| `infra/observability.py` | scaffold |
| `infra/parquet_partitioned.py` | scaffold |
| `infra/postgres_backend.py` | scaffold |
| `infra/redis_cache.py` | scaffold |
| `infra/timescaledb.py` | scaffold |
| `infra/k8s_manifests/` | configuration (not Python) |
| `infra/docker_compose.yml` | configuration |

## `marketdata/`

Microstructure / corporate-action surfaces. All `mock-only` -- real
implementations require tick / TAQ feeds.

| Module | Status |
|---|---|
| `marketdata/auction_imbalance.py` | mock-only |
| `marketdata/block_trades.py` | mock-only |
| `marketdata/corporate_actions.py` | mock-only |
| `marketdata/dark_pool_prints.py` | mock-only |
| `marketdata/extended_hours.py` | mock-only |
| `marketdata/level3_book.py` | mock-only |
| `marketdata/lit_dark_routing.py` | mock-only |
| `marketdata/survivorship_free.py` | mock-only |
| `marketdata/taq_reconstruction.py` | mock-only |
| `marketdata/trade_microstructure.py` | mock-only |

## `altdata/`

All `mock-only`. Real provider wiring is roadmap R2; FRED is the
recommended first slice.

| Module | Status |
|---|---|
| `altdata/earnings_transcripts.py` | mock-only |
| `altdata/fred_macro.py` | mock-only |
| `altdata/google_trends.py` | mock-only |
| `altdata/news_llm_sentiment.py` | mock-only |
| `altdata/onchain_crypto.py` | mock-only |
| `altdata/options_flow.py` | mock-only |
| `altdata/reddit_scraper.py` | mock-only |
| `altdata/satellite_geo.py` | mock-only |
| `altdata/sec_filings.py` | mock-only |
| `altdata/twitter_sentiment.py` | mock-only |

## `compliance/`

All `scaffold`. Skeletons for MiFID II, 13F, CTA reports plus
encryption-at-rest, RBAC, two-factor and PII handler primitives. R3
tracks production-grade work; R69 sets the operational vulnerability
disclosure policy.

| Module | Status |
|---|---|
| `compliance/best_execution.py` | scaffold |
| `compliance/cftc_form.py` | scaffold |
| `compliance/encryption_at_rest.py` | scaffold |
| `compliance/mifid_reporting.py` | scaffold |
| `compliance/pii_handler.py` | scaffold |
| `compliance/rbac.py` | scaffold |
| `compliance/sec_13f.py` | scaffold |
| `compliance/soc2_audit.py` | scaffold |
| `compliance/trade_reconstruction.py` | scaffold |
| `compliance/two_factor.py` | scaffold |

## `experimental/`

Triage tracked separately as roadmap R48. Treat every `experimental/`
module as `experimental` regardless of its internal docstring claims.
None are production.

## How this matrix is maintained

- Update entries when a module's status changes substantively.
- A status downgrade (e.g. `production` -> `scaffold`) is a regression
  that warrants a CHANGELOG note.
- A status upgrade (e.g. `scaffold` -> `production`) requires evidence:
  a real integration test plus an entry in the relevant
  `docs/v*_COMPLETION_REPORT.md`.

## R47 closure note

Status labels above are derived from inspection of the repository
state on 2026-05-08. Every module has a row. The README does not yet
link to this matrix; the link is added in the same R47 closure
batch. R48 (experimental/ triage) tracks the next step.

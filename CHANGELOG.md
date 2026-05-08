# Changelog

All notable changes to QuantForge are documented here. Detailed batch reports
live in `docs/v1_COMPLETION_REPORT.md`, `docs/v1_1_COMPLETION_REPORT.md`,
`docs/v1_2_COMPLETION_REPORT.md`, and `docs/v1_3_COMPLETION_REPORT.md`.

## [1.4.0] - 2026-05-07

Protocol-tier audit rounds 1-4 + extra robustness work. Tightens the
OOS-sagrado contract end to end. Cumulative test count > 2500.

### Added
- `forge freeze` CLI subcommand for registering a hash-verified snapshot
  via `SnapshotStore.freeze(...)`.
- `forge search-multi` CLI subcommand for multi-asset GA that loads each
  asset via `load_tier(...)`, honoring tier ceremony rules.
- `forge validate --tier {oos_dev,oos_locked,forward}` knob; locked tiers
  additionally require `--i-understand-ceremony`.
- `LiveConfig.bypass_validation_check` + `QFPaperStrategy.bind(bypass_validation_check=...)`
  flag for explicit operator override of the new validation marker gate.
- `DataSnapshot.git_hash`, `forge_version`, `seed`, `config_hash` fields
  for reproducibility metadata; persisted to the SQLite snapshot index
  with a forward-compatible ALTER migration.
- Tests `tests/test_protocol_round4.py` covering all P1/P2/P3/E fixes
  plus a multi-process OOSGuard concurrency test.

### Changed
- `QFLiveStrategy.initialize()` and `QFPaperStrategy.initialize()` now
  call `check_validation_marker(strategy_name)` once per session. A
  failed marker permanently halts the session unless
  `bypass_validation_check=True` is set (warning logged).
- `core/data_tiers.split_by_tier` and `load_up_to_tier` cap on the
  *date component* (`idx.normalize()`) so intraday bars on a boundary
  date sort into the correct tier (P1.2 round-4 audit fix).
- `core/data_layer.load_asset` deduplicates timestamps via
  `s[~s.index.duplicated(keep="last")]` before tier slicing.
- `OOSGuard.record_oos_violation` and `_record_external_authorized_read`
  now mirror the event to the SOC2 audit JSONL trail (best-effort, never
  propagates errors). The SOC2 JSONL is canonical; the OOS lock is
  informational.
- `--tier full` requires both `QF_ALLOW_FULL_TIER=1` AND an active
  `OOSGuard("explicit_unlock_full_tier")` (P2.3).
- `run_multi_asset_ga` no longer requires `price_dict_oos` for the
  IS-only fitness signature; the legacy 3-arg shape stays supported via
  the deprecated `multi_asset_fitness` shim.

### Fixed
- `f2_full_validate` skips the OOS Calmar gate when the lockbox is
  active so a sealed run does not double-charge the gate.

## [1.3.1] - 2026-05-07

Audit-batch hardening for packaging, infrastructure, and documentation. No
behavior changes to research / GA / validation. Cumulative test count rises
to ~1330.

### Added
- `quantforge.deployment` re-exports `equal_weight`, `equal_vol`,
  `inverse_dd`, `risk_parity_allocator` (alias of `risk_parity_weights`),
  and `preflight_checks` (alias of `run_preflight`) so the documented
  public allocator / preflight surface matches the imports.
- `quantforge.regime` re-exports `BayesAlphaModel` (alias of
  `bayesian_rolling_alpha`), `BayesAlphaResult`, and `MarkovSwitchingMean`.
- `STRATEGY_AUTHOR.md`: Wrapper strategies section documenting the
  `is_wrapper=True` sentinel, the `base: Strategy = None` ctor convention,
  and the `wrapper_factory` pattern required by `run_ga`.
- `RESEARCH_PROTOCOL.md`: Snapshot freezing section covering
  `SnapshotStore.freeze(..., locked=True)`, hash verification, and the
  `_ALLOWED_UNLOCK_PHASES = {"explicit_unlock"}` ceremony.
- CI: dedicated `extras-resolution` job that installs `[dev,all]` and
  smoke-imports every optional extras path (`portfolio`, `report`, `dl`,
  `rl`, `monitoring`, `llm`, `live`).
- `Makefile` with `count-tests`, `test`, `lint`, `format`, `coverage`
  targets.

### Changed
- `quantforge/__init__.py`: dropped dead outer `try/except ImportError`
  around `importlib.metadata` (always present on Python 3.10+); `__all__`
  now appends conditionally instead of advertising symbols that resolve to
  `None`.
- `tests/conftest.py`: cache `torch`, `quantforge.core.seed`, and
  `quantforge.ga.fitness` imports at module load; the autouse fixture now
  reseeds without re-importing per test.
- `.pre-commit-config.yaml`: reordered ruff hooks so `ruff-format` runs
  first, then `ruff --fix` on the formatted layout.
- `.coveragerc`: dropped `*/__init__.py` from `omit` so the 80% gate
  catches regressions in package surface modules.
- `pyproject.toml`: declared `platformdirs>=4.0` as a base dependency
  (used by the XDG-compliant cache resolver).
- `docs/API_REFERENCE.md`: updated `deployment` table to canonical names
  (`run_preflight`, `risk_parity_allocator`) and added entries for the
  documented but unlisted regime symbols (`MarkovSwitchingMean`,
  `BayesAlphaModel`) and ML-microstructure / fracdiff symbols
  (`signed_volume`, `order_flow_imbalance`, `frac_diff_ffd`, `find_min_d`).
- `README.md`: cumulative test count updated to ~1330 and points at
  `make count-tests` as the authoritative source.

### Fixed
- `tests/test_audit_fixes.py` / `test_validation_audit_fixes.py` /
  `test_lint_config.py`: removed dead imports (`os`, `sys`, `pytest`,
  `child_rng`, `PROJECT_ROOT`).
- `tests/test_lint_config.py` no longer duplicates the YAML pre-commit
  checks owned by `tests/test_pre_commit.py`.

## [1.3.0] - 2026-05-07

Intraday + DL/RL + dashboard + brokers + LLM + drift. 205 new tests
(cumulative 946). Three SDD batches (M, N, O) of 5 agents each.

### Added
- Intraday infrastructure: `core/engine_intraday.py` (RTH/24h/ETH minute
  engine), `core/bars.py` (tick/volume/dollar bars per AFML Ch. 2),
  `core/costs_intraday.py` (bid-ask scaling, U-shape participation,
  sqrt impact), `core/realtime.py` (yfinance polling, ring buffer, replay).
- Microstructure features: `ml/microstructure.py`.
- Deep learning + RL: `ml/lstm.py`, `ml/transformer.py`, `ml/rl_agent.py`,
  `strategies/library/seq_model.py`, `ml/features_pipeline.py`.
- Monitoring: `monitoring/dashboard.py` (Streamlit), `monitoring/alerts.py`
  (email + webhook), `monitoring/drift.py`.
- Multi-broker abstraction: `deployment/brokers.py`.
- LLM research assistant: `research/llm_assistant.py`.

## [1.2.0] - 2026-05-06

Regime detection, persistence, stress and scenarios. 177 new tests
(cumulative 741). Three SDD batches (J, K, L) of 5 agents each.

### Added
- Regime: `regime/hmm.py`, `regime/bayes_alpha.py`,
  `regime/markov_switching.py`, `regime/hurst.py`,
  `strategies/library/online_learner.py`.
- Registry: `registry/registry.py` (SQLite backtest registry),
  `registry/versioning.py`, `registry/journal.py` (trade journal),
  `registry/experiments.py`, plus 6 new `forge` ML subcommands.
- Validation + risk: `validation/scenarios.py` (synthetic crashes),
  `validation/tail_risk.py`, `validation/correlation_stress.py`,
  `deployment/liquidity.py`, `core/taxes.py`.

## [1.1.0] - 2026-05-06

ML pipeline, portfolio optimization, analytics + execution. 275 new tests
(cumulative 564). Three SDD batches (G, H, I) of 5-6 agents each.

### Added
- ML: `validation/purged_cv.py` (Purged K-Fold + embargo),
  `ml/labels.py` (triple-barrier, meta-labeling),
  `ml/feature_importance.py` (MDI/MDA/SFI), `ml/fracdiff.py`,
  `validation/structural_breaks.py`, `validation/cscv_pbo.py`.
- Portfolio: `deployment/hrp.py`, `deployment/risk_optim.py` (CVaR/CDaR),
  `deployment/black_litterman.py`, `deployment/cov_shrinkage.py`,
  `deployment/risk_parity.py`.
- Analytics + execution: `analytics/metrics_full.py` (56 metrics),
  `analytics/factor_analysis.py` (Alphalens-style),
  `analytics/attribution.py`, `analytics/round_trip.py`,
  `core/slippage.py`, `reporting/tearsheet.py` v2.

## [1.0.0] - 2026-05-06

Foundation: backtest engine, strategies, GA, validation gates,
deployment, CLI. 289 tests across six SDD batches (A-F).

### Added
- Core: multi-asset engine, numba JIT kernels (RSI 193x speedup),
  costs (ZERO/IBKR/CONSERVATIVE), unified metrics
  (Calmar/Sharpe/Sortino/DSR/PSR), seed-based reproducibility,
  pydantic v2 config, structured logging.
- Strategies: BollingerMR, DualMomentum, ATRBreakout, PairTrade,
  StopWrapper.
- Validation: WF rolling/expanding/anchored, noise injection,
  gap simulation, retraining cadence, integrated Pipeline v2.
- Deployment: risk-per-trade sizing (fixed/vol-target/Kelly),
  Lumibot live wrapper, strategy allocator, 10-check preflight.
- Search: joblib distributed GA, Bayesian optimization (skopt),
  GA seed populations, multi-asset GA (PairTrade).
- Infra: integration + property-based tests, hardened OOSGuard
  (file lock + git hash), feature store with provenance,
  CLI with 8 subcommands.

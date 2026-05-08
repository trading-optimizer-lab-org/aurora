# Changelog

All notable changes to QuantForge are documented here. Detailed batch reports
live under `docs/archive/version_reports/`.

## [1.4.1] - 2026-05-08

Roadmap execution session. Closed R1, R7-R15, R17, R20, R22, R30, R33,
plus Phase 0 / Phase 1 truth + CI hardening items.

### Added
- `tests/test_property.py` reincorporated to baseline + new
  `tests/test_property_v2.py` with 17 property invariants for strategy
  bounds, ProtocolPolicy hash determinism, tier-split partition,
  cost-model identity, engine + metrics finiteness (R11, commit `1b600a7`).
- `agents/auditor/llm_augmenter.py` LLM augmenter scaffold with three-
  layer severity capping; `MockLLMProvider` deterministic offline +
  `AnthropicLLMProvider` lazy-imported (R8, commit `105046b`).
- `research/rag.py` keyword index over the ResearchFactory archive +
  review queue (R9, commit `8a644df`).
- `research/auto_loop/` continuous research loop with cycle summaries,
  review-queue cap and dry-run mode (R10, commit `9593e86`).
- `core/snapshots_distributed.py` `SnapshotBackend` interface with
  `LocalSnapshotBackend` reference (R7, commit `e06761b`).
- `exports/lean/live.py` Lean live deploy gate with provenance +
  operator-flag triple-gate (R1, commit `56160f9`).
- `tests/test_protocol_fuzz.py` Hypothesis adversarial fuzz suite (R13,
  commit `bd90417`).
- Mutation testing setup: `[tool.mutmut]` in `pyproject.toml`,
  `mutmut_config.py`, `docs/MUTATION_TESTING.md`, Makefile targets (R12,
  commit `2a506eb`).
- `docs/conf.py` Sphinx + autodoc + autosummary + napoleon + furo +
  myst-parser. New `[docs]` extra in `pyproject.toml` (R15, commit
  `064c535`).
- `docs/ZERO_TO_LIVE.md` operator guide from clean clone to guarded
  live (R14, commit `064c535`).
- `docs/roadmap/ROADMAP_PENDING.md` and `docs/roadmap/BLOCKERS.md`
  capturing the 154-item backlog with explicit blocker semantics.
- `SECURITY.md` vulnerability disclosure policy (R69).
- `core/engine.py` one-shot warning when `run_backtest` runs under
  zero-cost model unless `acknowledge_zero_costs=True` is passed (R46).
- `Makefile` `setup`, `docs`, `docs-clean`, `mutate`, `mutate-results`,
  `mutate-full`, `property-thorough` targets; `PYTHON ?= python`
  override.
- `CONTRIBUTING.md` updated to match the flat Layout B install path
  (`pip install -e ".[dev,ga,docs,mutate]"`).
- `quantforge.research.auto_loop` registered in
  `[tool.setuptools].packages` and `package-dir`; ships in the wheel.
- `[tool.ruff.lint].ignore` adds `N999`; the `QuantForge` capitalised
  repo dir is intentional.

### Changed
- `core/config.py` `DataConfig.cache_dir` default resolves through
  `runtime_paths.cache_dir()`; honours `$QF_CACHE_DIR` / `$QF_DATA_DIR`
  / platformdirs.
- `core/features.py` `FeatureStore.__init__(root=None)` resolves the
  same way.
- `deployment/preflight.py` validation marker now lands at
  `<project>/.qf_cache/.validation_passed_*.json` instead of the
  ghost `quantforge/data_cache_qf/` path (R22).
- `core/metrics.py` Calmar / MAR explicitly handle `MDD == 0`:
  `cagr > 0 -> +inf`, `cagr < 0 -> -inf`, `cagr == 0 -> 0.0`. Documented
  in the `compute_metrics` docstring (R16).
- `.github/workflows/lint.yml` two jobs: `ruff-full` permissive and
  `ruff-strict` blocking on the curated post-v1.4 surface.
- `.github/workflows/tests.yml` removed `--ignore=tests/test_property.py`
  and `--ignore=tests/test_config.py` flags; sets
  `HYPOTHESIS_PROFILE=ci` env.

### Fixed
- The `quantforge/data_cache_qf/` ghost directory no longer regenerates
  during test runs and no longer shadows the package on filesystems
  where Python path resolution favoured the on-disk subdirectory (R22).
- `tests/test_config.py::test_default_config` updated to assert the
  new `runtime_paths.cache_dir()` contract.
- Removed the placeholder `https://github.com/anthropics/quantforge`
  link from `docs/index.rst`.
- `core/data_layer.py` docstring example for `OOSGuard` now uses
  `tempfile.gettempdir()` instead of the Linux-specific `/tmp` (R74).

### Documented
- `docs/MUTATION_TESTING.md` numba JIT shadow-mutations workaround
  (R72).
- Closed previously reported failures: `test_markov_switching.py`
  passes in current workspace (R17 closed); strict Sphinx build `-W`
  passes (R20 closed); pre-commit suite passes locally (R30 closed,
  superseded by R59 for CI wiring).

### Verification snapshot
- `python -m pytest tests/ -m "not slow and not integration"` ->
  2781 passed, 23 skipped, 10 deselected.
- Coverage: 80.40% against the 80% threshold.
- `mypy`: clean across 321 source files.
- `ruff check .`: clean.
- `pre-commit run --all-files`: clean.
- `python -m sphinx -b html -W docs docs/_build/html-strict`: clean.
- `python -m build`: produces sdist + wheel.

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

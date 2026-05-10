# Aurora

Standalone Python quant research engine. Backtest + GA + validation gates + paper/live with hash-bound provenance and 7-stage protocol spine.

Renamed from QuantForge to Aurora in v1.5.0 (R23). The legacy `quantforge`
namespace remains importable as a thin compat shim that emits a
`DeprecationWarning`; the shim is removed in v1.6.

## Layout

Flat layout (Layout B). `pyproject.toml` at repo root. Subpackages live as top-level dirs (`core/`, `strategies/`, `validation/`, etc) and map to `aurora.<name>` via `[tool.setuptools.package-dir]`.

```
QuantForge/                  <- repo root + package root (dir name unchanged)
├── pyproject.toml
├── __init__.py              <- aurora package init
├── core/                    <- aurora.core
├── strategies/              <- aurora.strategies
├── validation/              <- aurora.validation
├── ga/                      <- aurora.ga
├── ml/                      <- aurora.ml
├── agent_gateway/           <- aurora.agent_gateway
├── agents/auditor/          <- aurora.agents.auditor
├── research/factory/        <- aurora.research.factory
├── triage/                  <- aurora.triage
├── reporting/daily_ops/     <- aurora.reporting.daily_ops
├── exports/lean/            <- aurora.exports.lean
├── quantforge/              <- back-compat shim package (removed in v1.6)
├── tests/                   <- pytest suite
├── docs/                    <- ARCHITECTURE, RESEARCH_PROTOCOL, version reports
├── examples/
└── config/                  <- ships in wheel (YAML configs)
```

## Test command

```
"C:/Python314/python.exe" -m pytest tests/ -m "not slow and not integration" \
    --ignore=tests/test_config.py --ignore=tests/test_property.py
```

Baseline: 2828+ pass, 10 pre-existing fail (9 markov_switching statsmodels API drift + 1 lint_config AST scanner false positive).

## Runtime paths

ALL runtime artifacts go through `aurora.core.runtime_paths`. Never hardcode paths.

Env var overrides. The canonical `AU_*` names ship in v1.5; the legacy
`QF_*` names are still read with a `DeprecationWarning` until v1.6
(see `core/env_compat.py::aurora_env`).

| Canonical (AU_) | Legacy (QF_, deprecated) | Purpose | Default |
|---|---|---|---|
| `AU_DATA_DIR` | `QF_DATA_DIR` | base data dir | `platformdirs.user_data_dir("aurora")` |
| `AU_CACHE_DIR` | `QF_CACHE_DIR` | price/data cache | `$AU_DATA_DIR/cache` |
| `AU_SNAPSHOT_ROOT` | `QF_SNAPSHOT_ROOT` | SnapshotStore root (parquet+sqlite) | `$AU_DATA_DIR/snapshots` |
| `AU_AUDIT_LOG` | `QF_AUDIT_LOG` | SOC2 audit JSONL | `$AU_DATA_DIR/audit_trail.jsonl` |
| `AU_GATEWAY_AUDIT` | `QF_GATEWAY_AUDIT` | agent gateway chain | `$AU_DATA_DIR/gateway_audit.jsonl` |
| `AU_OOS_LOCK` | `QF_OOS_LOCK` | OOSGuard lock | `$AU_DATA_DIR/.oos_lock.json` |
| `AU_RESEARCH_ARCHIVE` | `QF_RESEARCH_ARCHIVE` | factory archive JSONL | `$AU_DATA_DIR/research_archive.jsonl` |
| `AU_REVIEW_QUEUE` | `QF_REVIEW_QUEUE` | factory review queue | `$AU_DATA_DIR/research_review_queue.jsonl` |

Tests use `monkeypatch.setenv("AU_<VAR>", str(tmp_path / ...))` (or the
legacy `QF_<VAR>` form during the shim window) for isolation.

## Import boundary

Aurora is a LIBRARY. Never import from consumer projects (sp500_ls_v2, naomi, jade, etc). Pure stdlib + declared `pyproject.toml` deps only.

## CLI

```
aurora --version
aurora policy show / verify
aurora data list-providers / fetch / verify
aurora agent token-issue / commit / push
aurora audit run
aurora research submit / batch / review-queue / promote
aurora triage run / list-promising
aurora ops daily / alerts
aurora crypto fetch / submit-order
aurora export lean / verify
aurora freeze
```

The legacy `forge` entry point is kept as a deprecated alias for one
release cycle; it dispatches to the same `aurora.cli.forge:main`.

## Protocol spine (v4.0)

```
ProtocolPolicy (frozen + hashed) ->
DataProviderRegistry (6 providers, tier-gated, PIT-aware) ->
SnapshotStore (sha256, locked phase, policy_hash bound) ->
ExperimentRegistry (lineage) ->
ValidationPipeline (9 mandatory gates) ->
AgentAuditGateway (scoped tokens, hash-chained audit, triple-gate live) ->
Paper/Live Guard Pipeline (5 broker adapters, KillSwitch+AuditLog+RateLimiter)
```

policy_hash propagates: `spec.policy_hash == snapshot.policy_hash == validation.policy_hash == audit.policy_hash`.

## Tier protocol

5 tiers: `IS_TRAIN`, `IS_VALID`, `OOS_DEV`, `OOS_LOCKED`, `FORWARD`.

4 ceremonies (env flag + `OOSGuard` context required):
- `explicit_unlock_snapshot`
- `explicit_unlock_oos_locked`
- `explicit_unlock_forward`
- `explicit_unlock_full_tier`

## Style

- Caveman mode active by default in chat (terse, drop articles, fragments OK)
- Code/commits/security: write normal English
- No emojis in code unless requested
- Prefer Edit over Write for existing files

## Known issues

- 9 `test_markov_switching.py` failures: statsmodels API drift, pre-existing, unrelated to Aurora
- 1 `test_lint_config::test_no_unmarked_live_data_loads`: cosmetic AST scanner false positive

## Status

v1.5.0 -- Aurora rename (R23). 2828+ tests passing. Hash provenance preserved.
v1.4.0 -- extracted from MODELO SP500 on 2026-05-08.

<!-- CONTEXT-OPTIMIZER:START -->
## Context Optimization - Auto-injected Section
> _Last updated: 2026-05-10 15:56:36 | Active decisions: 0_
> _This section is auto-generated by session_start.py_

_(No decisions recorded)_

### Session Summary (Previous)
# Context Summary

_This file is auto-updated by session_end.py_

## Last Updated
2026-05-09 12:19:36

## Session Info
- Session ID: f73ea010-6fdf-4a38-b948-74b2cc32500d
- End reason: other

## Decision Summary
- Active: 0
- Superseded: 0
- Total: 0

<!-- CONTEXT-OPTIMIZER:END -->

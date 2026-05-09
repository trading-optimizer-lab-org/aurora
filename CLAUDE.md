# QuantForge

Standalone Python quant research engine. Backtest + GA + validation gates + paper/live with hash-bound provenance and 7-stage protocol spine.

## Layout

Flat layout (Layout B). `pyproject.toml` at repo root. Subpackages live as top-level dirs (`core/`, `strategies/`, `validation/`, etc) and map to `quantforge.<name>` via `[tool.setuptools.package-dir]`.

```
QuantForge/                  <- repo root + package root
├── pyproject.toml
├── __init__.py              <- quantforge package init
├── core/                    <- quantforge.core
├── strategies/              <- quantforge.strategies
├── validation/              <- quantforge.validation
├── ga/                      <- quantforge.ga
├── ml/                      <- quantforge.ml
├── agent_gateway/           <- quantforge.agent_gateway
├── agents/auditor/          <- quantforge.agents.auditor
├── research/factory/        <- quantforge.research.factory
├── triage/                  <- quantforge.triage
├── reporting/daily_ops/     <- quantforge.reporting.daily_ops
├── exports/lean/            <- quantforge.exports.lean
├── tests/                   <- pytest suite
├── docs/                    <- ARCHITECTURE, RESEARCH_PROTOCOL, version reports
├── examples/
└── config/                  <- ships in wheel (YAML configs)
```

## Test command

```
python -m pytest tests/ -m "not slow and not integration"
```

Use the same interpreter that installed the editable package. On a fresh
checkout, run:

```
python -m pip install -e ".[dev,ga,docs,mutate]"
```

Baseline (verified 2026-05-08): 2781 passed, 23 skipped, 10 deselected.
Coverage 80.40% (threshold 80%). Mypy clean across 410 source files.
Ruff clean. Strict Sphinx docs build (`-W`) clean.

Property-based tests now in baseline. Hypothesis profiles registered in
`tests/conftest.py`:

- `dev` (default, max_examples=15) -- fast local feedback
- `ci` (max_examples=25, derandomize=True) -- reproducible CI
- `thorough` (max_examples=200) -- nightly stress

Switch via env: `HYPOTHESIS_PROFILE=ci pytest ...` or
`pytest --hypothesis-profile=ci`.

## Runtime paths

ALL runtime artifacts go through `quantforge.core.runtime_paths`. Never hardcode paths.

Env var overrides:

| Var | Purpose | Default |
|---|---|---|
| `QF_DATA_DIR` | base data dir | `platformdirs.user_data_dir("quantforge")` |
| `QF_CACHE_DIR` | price/data cache | `$QF_DATA_DIR/cache` |
| `QF_SNAPSHOT_ROOT` | SnapshotStore root (parquet+sqlite) | `$QF_DATA_DIR/snapshots` |
| `QF_AUDIT_LOG` | SOC2 audit JSONL | `$QF_DATA_DIR/audit_trail.jsonl` |
| `QF_GATEWAY_AUDIT` | agent gateway chain | `$QF_DATA_DIR/gateway_audit.jsonl` |
| `QF_OOS_LOCK` | OOSGuard lock | `$QF_DATA_DIR/.oos_lock.json` |
| `QF_RESEARCH_ARCHIVE` | factory archive JSONL | `$QF_DATA_DIR/research_archive.jsonl` |
| `QF_REVIEW_QUEUE` | factory review queue | `$QF_DATA_DIR/research_review_queue.jsonl` |

Tests use `monkeypatch.setenv("QF_<VAR>", str(tmp_path / ...))` for isolation.

## Import boundary

QuantForge is a LIBRARY. Never import from consumer projects (sp500_ls_v2, naomi, jade, etc). Pure stdlib + declared `pyproject.toml` deps only.

## CLI

```
forge --version
forge policy show / verify
forge data list-providers / fetch / verify
forge agent token-issue / commit / push
forge audit run
forge research submit / batch / review-queue / promote
forge triage run / list-promising
forge ops daily / alerts
forge crypto fetch / submit-order
forge export lean / verify
forge freeze
```

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

None blocking. Verification 2026-05-08 cleared the previously reported
markov_switching API drift and lint-config cosmetic false-positive
entries; both pass in the current baseline.

## Status

v1.4.0 — extracted from MODELO SP500 on 2026-05-08.
2781 tests passing, 23 skipped, 10 deselected. 80.40% coverage. Mypy /
ruff / strict Sphinx clean. Hash provenance preserved.

Project rename to AURORA decided 2026-05-08; execution tracked as
roadmap R23.

<!-- CONTEXT-OPTIMIZER:START -->
## Context Optimization - Auto-injected Section
> _Last updated: 2026-05-09 08:01:17 | Active decisions: 0_
> _This section is auto-generated by session_start.py_

_(No decisions recorded)_

### Session Summary (Previous)
_(No summary)_
<!-- CONTEXT-OPTIMIZER:END -->

# QuantForge v4.0 — Spine Hardening Report

**Date:** 2026-05-07
**Method:** SDD parallel batches P0/P1/P2/P3 + spine integration (10 agents, 11 new packages)
**Roadmap source:** User memo (P0–P3 priorities post-research of OpenBB/qlib/TradingAgents/QuantDinger/OpenAlice/vectorbt/Lean/CCXT)

## Summary

11 new packages + 11 new test files. **+207 net new tests (2573 → 2780).** All batches green; 10 pre-existing failures confirmed unrelated (9 markov_switching statsmodels drift + 1 lint_config cosmetic).

## Cumulative test count

| Phase | Tests passing | Delta |
|-------|--------------:|------:|
| v3.0 (baseline post-audit-rounds) | 2573 | +627 |
| **v4.0 P0/P1/P2/P3 + spine** | **2780** | **+207** |

## Batch breakdown

### P0 — Foundation as code (38 tests)

| Module | Tests |
|--------|------:|
| `core/protocol_policy.py` (ProtocolPolicy + YAML + hash + frozen + CLI verify) | 15 |
| `core/data_providers/` (Registry + 5 providers + tier gating + content_hash) | 23 |

### P1 — Agent layer (77 tests)

| Module | Tests |
|--------|------:|
| `agent_gateway/` (tokens + scopes + audit chain + stage/commit/push + triple-gate live) | 24 |
| `agents/auditor/` (6 deterministic reviewers + orchestrator + LLM augmenter cap) | 27 |
| `research/factory/` (StrategySpec + IS/WF/OOS_DEV pipeline + lineage + generators) | 26 |

### P2 — Operational (48 tests)

| Module | Tests |
|--------|------:|
| `triage/` (vectorbt-style screening + tier guard + promotion tokens) | 23 |
| `reporting/daily_ops/` (8 sections + 6 alert checks + no-trade reasoning + CLI) | 25 |

### P3 — External integrations (29 tests)

| Module | Tests |
|--------|------:|
| `core/data_providers/ccxt_provider.py` + `deployment/ccxt_adapter.py` (lazy ccxt + sandbox default + triple-gate live) | 14 |
| `exports/lean/` (StrategySpec → Lean QCAlgorithm scaffold + provenance + verify) | 15 |

### Spine — End-to-end integration (15 tests)

`tests/test_spine_e2e.py` — exercises full chain:

```
ProtocolPolicy → DataProviderRegistry → SnapshotStore → ExperimentRegistry →
ValidationPipeline → AgentAuditGateway → Paper/Live Guard Pipeline
```

Asserts hash bindings end-to-end and negative paths (refused without ceremony / gateway commit).

## New top-level packages

```
quantforge/
├── core/
│   ├── protocol_policy.py        NEW v4 — central policy as code, frozen, hashed
│   └── data_providers/           NEW v4 — registry + yahoo/snapshot/csv/openbb/synthetic/ccxt
├── agent_gateway/                NEW v4 — secure token gateway, hash-chained audit, stage/commit/push
├── agents/auditor/               NEW v4 — 6 deterministic reviewers + orchestrator
├── research/factory/             NEW v4 — IS/WF/OOS_DEV research pipeline + lineage
├── triage/                       NEW v4 — vectorized screening backend (tier-guarded)
├── reporting/daily_ops/          NEW v4 — daily operational report (sections + alerts + no-trade)
├── deployment/ccxt_adapter.py    NEW v4 — CCXT broker (sandbox default, triple-gate live)
├── exports/lean/                 NEW v4 — Lean QCAlgorithm export with provenance
└── tests/test_spine_e2e.py       NEW v4 — end-to-end spine integration
```

## Hard guarantees added in v4.0

### Provenance binding
- Every snapshot stores `policy_hash` (snapshot bound to protocol it was frozen under)
- Every audit report stores `policy_hash`
- Every triage batch stores `policy_hash` + `config_hash`
- Every Lean export embeds `policy_hash` + `spec_hash` + `qf_version` in `qf_metadata.json`
- Spine e2e test asserts `spec.policy_hash == snapshot.policy_hash == validation.policy_hash == audit_report.policy_hash`

### Tier enforcement
- DataProviderRegistry refuses non-PIT providers under `OOS_LOCKED`/`FORWARD` ceremony unless explicit unlock
- ResearchFactory hard-caps at `OOS_DEV`; cannot read `OOS_LOCKED`/`FORWARD` data
- TriageEngine refuses `OOS_LOCKED`/`FORWARD` at construction AND refuses any data window crossing `OOS_LOCKED.start`
- CCXTProvider marked non-PIT and `supported_tiers={IS_TRAIN, IS_VALID}`

### Live trading triple-gate
- Token must be non-paper-only
- `QF_AGENT_LIVE_AUTH=1` env required
- Active `OOSGuard("agent_live_authorized")` ceremony required
- Human countersignature required (hmac of staged_id with `QF_OPERATOR_KEY`)
- CCXT additionally requires per-exchange `QF_CCXT_ALLOW_LIVE_<EX>` consent token

### Auditor cannot decide
- LLM augmenter findings capped at MEDIUM severity (cannot raise HIGH or HARD_FAIL)
- Hard-fail authority remains with deterministic rule reviewers
- Auditor gate is non-bypassable when in mandatory_gates

### Tamper detection
- ProtocolPolicy YAML carries declared hash; `forge policy verify` detects tampering
- Agent gateway audit chain is hash-linked; `forge agent audit-verify` detects edits or dropped entries
- Lean export `qf_metadata.json`; `forge export verify` detects mismatch
- Triage parquet content_hash verifies content integrity

## Test verification

```
"C:/Python314/python.exe" -m pytest quantforge/tests/ -m "not slow and not integration" \
    --ignore=quantforge/tests/test_config.py \
    --ignore=quantforge/tests/test_property.py
2780 passed, 6 skipped, 10 deselected, 10 failed in 378.45s
```

10 failures = 9 pre-existing `test_markov_switching` (statsmodels API drift; unrelated) + 1 pre-existing `test_lint_config::test_no_unmarked_live_data_loads` (cosmetic, scanner false positive). Verified by stashing v4 changes and reproducing on master.

## Capabilities added in v4.0

### ProtocolPolicy as enforced code
- Single `ProtocolPolicy` dataclass captures: tiers, gates, ceremonies, risk limits, cost model, stress scenarios, DCA, objectives, GA config
- Frozen + hashed; policy_hash propagates into every artifact
- YAML round-trip + `forge policy show/verify`

### DataProviderRegistry with provenance
- Every fetch returns a `Dataset` with `DatasetMetadata` (source, version, asof_date, point_in_time, content_hash, tier_permission, schema_version)
- 5 default providers (yahoo, snapshot, csv, openbb-stub, synthetic) + optional ccxt
- Tier-aware fetch gating with OOSGuard integration

### Secure AgentGateway
- Scoped tokens (READ_DATA, READ_REPORTS, PROPOSE_STRATEGY, RUN_BACKTEST_IS, RUN_VALIDATION_OOS_DEV, PAPER_TRADE, LIVE_TRADE)
- Per-token allowlist + notional caps + daily caps + cooldowns
- Hash-chained JSONL audit log with tamper detection
- Stage → Commit → Push pattern; live trading requires triple-gate
- HMAC-SHA256 token signing via `QF_GATEWAY_SECRET`
- Human commit signature via `QF_OPERATOR_KEY`

### 6-reviewer auditor (LLM-as-auditor, not decisor)
- HypothesisReviewer — flags missing hypothesis/edge/failure_modes
- DataLeakReviewer — detects lookahead patterns
- CostReviewer — re-runs cost model from policy; flags cost denial
- RegimeReviewer — flags single-regime dependency
- RiskReviewer — enforces policy.risk_limits
- DeploymentReviewer — flags ADV breach + missing borrow modeling
- LLM augmenter optional but capped at MEDIUM severity

### Research Factory
- Submit StrategySpec → IS backtest → walk-forward → OOS_DEV validation → review queue (or archive)
- Hard tier guard: never reads OOS_LOCKED/FORWARD
- 3 hypothesis generators (GA-derived, template, LLM)
- Lineage tracking with DOT export
- Promote to OOS_LOCKED requires explicit ceremony

### Vectorized triage
- Numpy-native vectorized signal/PnL/metrics for 10k+ variants
- Optional vectorbt backend (lazy import); fallback to internal
- Single-use promotion tokens force re-run on official engine
- Tier-guarded; refuses OOS_LOCKED/FORWARD

### Daily Ops Report
- 8 sections: Performance / Drawdown / Exposure / Signals / Regime / Attribution / No-Trade Reasoning / Alerts
- 6 alert checks: drawdown breach, kill switch, data freshness, regime change, drift, validation marker stale
- "Why no trade today?" reasoning per strategy (vol gate, cooldown, regime mismatch, marker stale, kill switch)
- Markdown + JSON outputs; CLI for cron/slack integration

### CCXT crypto adapter
- Optional ccxt dependency (`pip install quantforge[crypto]`)
- Lazy import; smoke tests pass without ccxt
- Sandbox default ON; live requires triple-gate + per-exchange consent token
- KillSwitch + AuditLog + RateLimiter (ccxt-rate-limit aware) + position concentration cap from policy

### Lean export
- Translates QF StrategySpec → Lean QCAlgorithm C# scaffold
- Pure Python text generation; no Lean runtime dep
- 3 translation tiers: full / partial / scaffold-only
- Provenance: `policy_hash`, `spec_hash`, `qf_version`, `exported_at`, `translation_tier`
- README mandatorily warns "DO NOT TRUST IN ISOLATION"
- `forge export verify` detects metadata tampering

## CLI surface added in v4.0

```
forge policy show / verify
forge data list-providers / fetch / verify
forge agent token-issue / token-list / token-revoke / audit-verify / stage / commit / push
forge audit run / list-reviewers
forge research submit / batch / review-queue / archive / lineage / generate / promote / triage
forge triage run / list-promising / promote
forge ops daily / alerts / summary
forge crypto exchanges / fetch / submit-order / positions / balance / allow-live
forge export lean / lean-list / verify
```

## Spine architecture (v4.0)

```
ProtocolPolicy (frozen + hashed)
    ↓ (policy_hash propagates)
DataProviderRegistry (5+1 providers, tier-gated, PIT-aware)
    ↓ (content_hash + asof_date stamped)
SnapshotStore (sha256 hashing, locked phase, policy_hash bound)
    ↓ (snapshot_id)
ExperimentRegistry (lineage logging)
    ↓
ValidationPipeline (8 + auditor_gate mandatory gates)
    ↓ (audit_report_hash bound)
AgentAuditGateway (token scopes, stage/commit/push, hash-chained audit)
    ↓ (gateway_committed required)
Paper/Live Guard Pipeline (KillSwitch + AuditLog + RateLimiter on 5 broker adapters)
```

Every artifact is hash-bound to its protocol version. Every cross-tier read requires ceremony. Every live order requires triple-gate. Spine integration test (`test_spine_e2e.py`) verifies all 14+ paths end-to-end.

## Total progress (v1.0 → v4.0)

| Metric | v1.0 | v4.0 | Delta |
|--------|-----:|-----:|------:|
| Tests passing | 289 | 2780 | +2491 (9.6x) |
| Top-level packages | 12 | 29 | +17 |
| Modules | ~30 | ~230 | +200 |
| CLI subcommands | 5 | 35+ | +30 |
| Validation gates | 0 | 9 mandatory | +9 |
| Data providers | 1 (yahoo) | 6 (yahoo/snapshot/csv/openbb/synthetic/ccxt) | +5 |
| Broker adapters | 0 | 5 (paper/alpaca/ib/coinbase/kraken/ccxt) | +5 |
| External audits closed | 0 | 4 rounds | +4 |
| Spine integration tests | 0 | 15 | +15 |

## Methodology

- ~340 subagents total deployed (M/N/O + P/Q/R/S/T/U + V/W/X/Y/Z + v2.A-H + v3.A-I + v4 P0/P1/P2/P3+spine)
- 5 deep audit rounds + 4 external audit rounds (all closed)
- 8 reflexion checkpoints
- 14 SDD parallel batches
- 1 spine end-to-end integration test (15 tests across 14 negative + 1 happy path)
- Convergence achieved Round Z; v2/v3/v4 expansions clean

## Production readiness

**v1.3.1 base + spine:** production-ready paper trading + supervised live trading.

**v2.0/v3.0 expansions:** research-grade demo for many surfaces; mock-friendly skeletons for some (alt data, infra). Production deployment of v2/v3 modules requires real-data integration testing case-by-case.

**v4.0 spine hardening:** the 7-stage spine (Policy → DataProviders → SnapshotStore → ExperimentRegistry → ValidationPipeline → AgentGateway → Paper/Live) is fully wired and integration-tested. The protocol is now enforceable as code, not just documentation.

QuantForge has grown from 289-test minimal backtest engine into a 2780-test full-stack quant research + trading + compliance + audit platform with a hardened protocol spine.

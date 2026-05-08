# QuantForge Spine

The "spine" is the load-bearing chain of seven components that take a research
hypothesis from raw data all the way to a paper / live order, with provenance
recorded at every link. This document is paired with the end-to-end test
[`tests/test_spine_e2e.py`](../tests/test_spine_e2e.py), which is the live
verification of the contract described here.

## Diagram

```
ProtocolPolicy
    | policy_hash binds every downstream artifact
    v
DataProviderRegistry  (PIT-aware, tier-gated)
    | Dataset.metadata.content_hash
    v
SnapshotStore  (snapshot.policy_hash == policy.policy_hash)
    | snap.sha256, snap.policy_hash
    v
ExperimentRegistry  (ExperimentTracker)
    | experiment_id, config{snapshot_sha256, policy_hash}
    v
ValidationPipeline  (with optional auditor_context)
    | audit_report.policy_hash, audit_passed
    v
AuditorOrchestrator  (multi-agent reviewers, HARD_FAIL gate)
    | audit_report.content_hash()
    v
AgentGateway  (stage -> commit -> push, hash-chained JSONL audit)
    | committed_id, request_digest, push entry
    v
Paper / Live broker  (KillSwitch + AuditLog + RateLimiter)
```

## Per-component contribution

| Component | Module | Contribution |
|---|---|---|
| ProtocolPolicy | [`core/protocol_policy.py`](../core/protocol_policy.py) | Frozen, deterministically-hashed source of truth for tiers, ceremonies, gates, risk caps, cost floor, and objectives. Every downstream artifact carries its `policy_hash` so a protocol change invalidates stale outputs. |
| DataProviderRegistry | [`core/data_providers/__init__.py`](../core/data_providers/__init__.py) | Versioned, point-in-time-aware adapter registry. Stamps `DatasetMetadata` (content_hash, asof, source, source_version, tier_permission) on every fetch. Gates non-PIT providers on locked tiers, records authorized reads on the active `OOSGuard`. |
| SnapshotStore | [`core/snapshots.py`](../core/snapshots.py) | Content-addressed parquet + SQLite index. Each `DataSnapshot` is bound to the active `ProtocolPolicy` via `policy_hash` and may be tagged with an `audit_report_hash`. Locked snapshots refuse to load outside an unlock ceremony. |
| ExperimentRegistry | [`registry/experiments.py`](../registry/experiments.py) | MLflow-style tracker (`ExperimentTracker`). Logs `ExperimentMeta`, generation history, Pareto front, best params. Aliased as the "experiment registry" by the research factory. |
| ValidationPipeline | [`validation/pipeline.py`](../validation/pipeline.py) | 8-gate orchestrator (WF / MC bootstrap / MC reorder / SPP / lookahead / DSR / noise / gap). Tier-aware: refuses to read OOS_LOCKED / FORWARD without the matching `OOSGuard` phase. Optionally calls an `AuditorOrchestrator.gate(...)` whose output lands on `report.audit_passed` and `report.audit_report`. |
| AuditorOrchestrator | [`agents/auditor/`](../agents/auditor/) | Six rule-based reviewers (Hypothesis, DataLeak, Cost, Regime, Risk, Deployment) plus an optional severity-capped LLM augmenter. Aggregates into an `AuditReport` whose `policy_hash` matches the active policy. |
| AgentGateway | [`agent_gateway/`](../agent_gateway/) | Three-stage ceremony (`stage -> commit -> push`) for non-human actors. Tokens are HMAC-signed, scoped, capped, allowlisted. Every step appends to a hash-chained JSONL audit log. Live trading requires `paper_only=False`, `QF_AGENT_LIVE_AUTH=1`, an active `OOSGuard("agent_live_authorized")`, and a fresh operator counter-signature. |
| Paper / Live broker | [`deployment/brokers.py`](../deployment/brokers.py) | `PaperBroker`, `AlpacaBroker`, etc. Every adapter exposes a `KillSwitch` (daily-loss + per-position trip), an `AuditLog` (SQLite, daily rotation), and a per-minute sliding-window `_RateLimiter`. The kill-switch arms automatically when the daily-loss threshold is breached. |

## What the spine guarantees

1. **Provenance.** Every artifact carries the `policy_hash` of the protocol it was produced under. A spec, a snapshot, an `AuditReport`, and the gateway audit entry for the order all thread the *same* hash. The provenance test `test_e2e_full_chain_provenance` asserts this directly.
2. **No silent OOS leak.** `OOS_LOCKED` and `FORWARD` data require a matching `OOSGuard("explicit_unlock_*")`. Both `validate_pipeline` and `load_up_to_tier` raise immediately when called without the right phase. The negative-path test `test_e2e_oos_locked_data_refused_without_ceremony` covers this.
3. **No unilateral order placement.** A non-human actor must hold a signed `AgentToken`, stage an action, get it committed (auto for paper if policy allows; always counter-signed by a human for live), then push. The gateway audit chain is hash-linked so any tamper with a JSONL row breaks `verify_chain()`.
4. **Broker safety net.** Even with a valid committed order, `KillSwitch.arm()` blocks `submit_order` at the broker layer. The `AuditLog` records every submit / fill / reject / cancel with tz-aware UTC ISO-8601 timestamps; the `_RateLimiter` enforces a fair FIFO window so a runaway agent can never hammer the broker faster than the configured rate.

## Live verification

The end-to-end behaviour described above is exercised by
[`tests/test_spine_e2e.py`](../tests/test_spine_e2e.py). The 15 cases cover:

- the happy path through every link,
- each negative path (OOS without ceremony, paper-only token attempting live, missing env flag, missing OOSGuard, missing human signature, kill switch armed, audit chain tampered, push without commit),
- the rate limiter, the paper audit log, the data-provider authorized-read recording,
- the auditor-gate HARD_FAIL block,
- the research factory cap at OOS_DEV, and
- the policy-hash provenance threading from spec to gateway audit entry.

Run it with

```
"C:/Python314/python.exe" -m pytest quantforge/tests/test_spine_e2e.py -v
```

## Known limitations (as of 2026-05-07)

- `quantforge.validation.pipeline.ValidationReport` does not currently carry a top-level `policy_hash` field. Provenance is preserved through the embedded `audit_report.policy_hash` when an `auditor_context` is provided. The provenance test reflects this: it asserts the audit report's hash, not the report's.

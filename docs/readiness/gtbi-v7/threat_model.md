# GTBI V7 Canonical Successor Threat Model

Status: accepted for the owner-controlled successor topology.

Scope: `GTBI_V7_CANONICAL_SUCCESSOR_1`, repository
`trading-optimizer-lab-org/aurora`, GitHub-hosted runners, immutable release
assets, Actions artifacts, the frozen historical data release and the final V7
result release. The retired multi-party topology is not in scope.

## Protected boundaries

- Scientific rows stop at `2020-12-31`; `locked_start=2021-01-01` is excluded.
- Research execution is GitHub Actions only. Local machines may inspect, edit,
  test synthetic fixtures and verify hashes, but cannot run research.
- V6 remains `historical_reference_only`; V7 makes no V6-equivalence claim.
- Canonical inputs, code, execution plans and results are content-addressed.
- The repository owner explicitly accepted ordinary GitHub-hosted runners and
  GitHub as the preservation/control boundary for this successor.
- Incremental net spend is capped at zero USD. A non-zero current net Actions
  charge fails closed.

## Main threats and controls

1. **Locked leakage or look-ahead.** Physical data-pack exclusion, CLI guards,
   workflow input checks, result-date validation and negative tests.
2. **Local canonical execution.** `GITHUB_ACTIONS=true` guard on every research
   entry point and tests proving the local override is absent from V7.
3. **Input or artifact substitution.** SHA-256 manifests, immutable release
   IDs, campaign fingerprints and exact commit binding.
4. **Partial results presented as complete.** Terminal-identity equations,
   row-count reconciliation, best-candidate membership and fail-closed final
   validation.
5. **Runner interruption.** Immutable checkpoints, selective retry and
   deterministic merge. The transient-recovery test deliberately interrupts
   one unit and must recover only that unit.
6. **Dependency or workflow drift.** Immutable wheelhouse, pinned source SHA,
   workflow-policy checks and scientific-output equivalence across 1/2/4
   processes.
7. **Credential exposure.** No long-lived campaign secrets are required by the
   successor. Evidence is redacted and scanned before publication.
8. **Accidental deletion.** Local changes are preserved before cleanup. No
   worktree or GitHub object is deleted without an exact allowlist and a
   separate receipt; the current completion performs no deletions.
9. **Unexpected cost.** Public-repository Actions usage and current billing
   export are reconciled. Any positive incremental net amount blocks closure.
10. **Consumer breakage.** Versioned result schemas, a complete consumer
    registry and migration tests bind consumers to the frozen inventory.

## Accepted residual risks

- GitHub and its hosted-runner control plane are trusted. A malicious provider
  host could inspect guest memory. This is explicitly accepted for historical,
  non-locked V7 data.
- The frozen Yahoo-derived universe is survivorship-biased, not point-in-time
  and retrospectively adjusted. V7 is a historical research reference, not a
  causal production claim.
- GitHub artifact retention is finite. Canonical V6 and V7 result bytes are
  retained in immutable release assets and verified local preservation copies.
- One repository owner may perform multiple logical roles under the explicit
  simplification directive. Automated checks still prevent silent boundary or
  digest changes.

No unresolved critical or high residual risk is accepted. Any future change to
the local-run guard, locked boundary, canonical schemas or scientific digest
invalidates this acceptance and requires a new receipt.

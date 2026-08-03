# GTBI V7 Master Plan: Readiness, Reorganization And Maximum Performance

| Field | Value |
|---|---|
| Version | `7.1` |
| Status | `CANONICAL SUCCESSOR READY FOR TERMINAL RECONCILIATION` |
| Audited at | `2026-07-29T11:42:58+02:00` |
| Repository | `trading-optimizer-lab-org/aurora` |
| Scientific execution environment | GitHub Actions only |
| Security lease deadman | GitHub-native automated control, never the laptop and never scientific execution |
| External non-scientific runtimes | Closed, attested allowlist in section 4.2 |
| Current document state | `TRACKED_CANONICAL_PRETERMINAL` |
| Canonical target path | `docs/plans/gtbi-v7-master-plan.md` |

### Owner Simplification Directive

The repository owner explicitly authorizes the simplified operating model
recorded in
`docs/readiness/gtbi-v7/owner_simplification_directive.json`. That directive
has precedence over every conflicting requirement in this document.

In particular:

- three external or independent audits are not required;
- different people, external custodians, dual control and independent
  reviewers are not required;
- the repository owner may approve and hold every operational responsibility;
- automated structural, scientific, temporal, security and cost checks remain
  mandatory;
- the verified GitHub V6 preservation lease is sufficient preservation;
- historical role names remain only as capability labels and do not create
  vacancies or gate blockers;
- the `0 USD` incremental-spend cap and all locked-data boundaries remain
  unchanged.

Any later use of words such as `independent`, `distinct`, `custodian`,
`witness`, `three audits` or `external copy` describes the retired
high-separation model. It is optional guidance, not a requirement, dependency
or reason to return `NO-GO`.

### Canonical Successor Amendment

The repository owner explicitly authorizes the already approved and completed
`gtbi_v7_new_reference_v1` campaign as this plan's canonical successor
generation. The authorization is recorded in
`docs/readiness/gtbi-v7/canonical_successor_authorization.json` and its
deterministic reconciliation receipt. This amendment has precedence over every
later statement that limits this document to V6-equivalent execution.

The immutable identity is:

```text
successor_generation=GTBI_V7_CANONICAL_SUCCESSOR_1
product=GTBI V7 Performance Engine
campaign_id=gtbi_v7_new_reference_v1
scientific_baseline=gtbi-v7-frozen-data-lake-v1
source_scientific_commit=e262264031ce70ee8e50d3f28d4771fb9072670b
final_recovery_run=30757436940
locked_start=2021-01-01
locked_authorized=false
maximum_incremental_net_spend_usd=0
```

The historical V6-equivalent generation remains permanently and correctly
closed as `NO_GO_CLOSED`. It is never reopened, relabelled or presented as
reproduced. V6 remains `historical_reference_only`; the successor makes no V6
equivalence, point-in-time, survivorship-free or causal-market-alignment claim.

The successor campaign was separately authorized before its scientific run,
used a frozen content-addressed input, evaluated all 72,000 terminal strategy
identities and produced zero passing candidates. Promoting that complete run
therefore does not select a favourable strategy or alter its historical
outputs. Its existing evaluation may satisfy the scientific execution evidence
of the successor path after exact receipt, row-count, digest and boundary
verification. It must not be rerun merely to change the project label.

`G2` and later gates may now be evaluated under the successor identity. They
remain fail-closed until their own applicable evidence and state transitions
verify. Requirements belonging only to the retired V6-equivalent lineage or to
the retired high-separation operating model are not successor dependencies.
The normal successor terminal target is `COMPLETED_CLEAN`; `ABANDONED_CLEAN`
remains the failure/abandonment alternative. Locked access remains prohibited
unless the owner gives a new explicit authorization in a future task.

### Canonical Successor Execution Status

The successor implementation and evidence reconciliation has completed 21 of
the 22 remaining applicable tasks. The sole remaining task is `PREV7-1003`,
which must run from the reviewed GitHub commit and emit the fail-closed
`COMPLETED_CLEAN` receipt. The current machine-readable state is:

```text
docs/readiness/gtbi-v7-successor/preterminal_reconciliation.json
status=ready_for_terminal_reconciliation
completed_task_count=21
terminal_task_id=PREV7-1003
blockers=[]
locked_data_accessed=false
incremental_net_spend_usd=0
```

The terminal receipt is generated only by
`.github/workflows/gtbi-v7-successor-close.yml`. That workflow runs tests and
administrative reconciliation only. It performs no research, backtest,
optimization or locked-data access.

## 1. Purpose

This is the proposed single GTBI V7 master document. It becomes canonical only
after `PREV7-0000` publishes it through a pull request created from the latest
`origin/main`.

Superseded document:

```text
docs/plans/gtbi-v7-maximum-performance.md
```

The current path remains the editing source for this review cycle. After
publication, it becomes a compatibility redirect to:

```text
docs/plans/gtbi-v7-master-plan.md
```

It defines the exact work required to:

1. Preserve the scientific evidence that is about to expire.
2. Build one unified `GTBI V7 Performance Engine`.
3. Preserve V6 as a historical result with incomplete original lineage and use
   the owner-authorized V7 canonical successor as the active reference.
4. Put GitHub governance in place without blocking the sole current owner.
5. Reorganize GitHub and the local editing environment safely.
6. Implement the complete V7 performance architecture in Aurora without a
   high-risk repository-wide rewrite.
7. Measure and use the four CPUs available in each GitHub runner.
8. Prove scientific equivalence before any performance optimization is accepted.
9. Prepare, but not authorize, a full campaign.

This document specifies planning, implementation and validation through the
canonical smoke. It does not by itself authorize:

- starting code implementation;
- launching tests, benchmarks or smokes;
- changing V6 science while implementing V7;
- opening locked data;
- using data after `2020-12-31` for train or validation;
- executing a full campaign;
- deleting branches, worktrees, releases, packages or artifacts without a
  reviewed inventory and explicit approval.

### 1.1 Document Quality Gate

Before `PREV7-0000`, freeze the exact master-plan SHA-256, verify the explicit
owner directive and run the deterministic structural validator. Acceptance
requires unique task IDs, no unknown references or dependency cycles, complete
gate assignment, contiguous execution-order numbering, balanced code fences,
valid tables/URLs and no stale forbidden term. A byte edit invalidates the
generated status until the contracts are regenerated and checked again.

No external auditor, signature, trusted auditor key, sequential audit round,
independence attestation or separate person is required. The owner directive
plus passing automated checks is the complete quality gate.

The remainder of this section documents the retired signed-audit design for
historical compatibility with existing schemas and tools. It is non-normative,
optional and cannot block `PREV7-0000` or any later gate.

The pre-genesis quality evidence has an exact import contract:

```text
docs/readiness/gtbi-v7/master_plan_quality_receipts.jsonl
docs/readiness/gtbi-v7/master_plan_quality_receipt_set.json
docs/readiness/gtbi-v7/master_plan_audit_scope_manifest.json
config/gtbi/schemas/v7/operational/master_plan_audit_scope_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/master_plan_audit_receipt_v1.schema.json
config/gtbi/schemas/v7/operational/master_plan_quality_receipt_set_v1.schema.json
```

The scope manifest binds the exact master-plan identity and exactly four
mandatory review dimensions:
`architecture_and_state_reachability`, `scientific_and_temporal_integrity`,
`security_and_custody`, and `operations_and_billing`. It also contains the
complete ordered structural-check registry named above, tool-independent
acceptance predicates, required evidence classes and `scope_manifest_digest`.
It uses `GTBI_MASTER_PLAN_AUDIT_SCOPE_V1`, omitting only that digest field.
Every round must cover every registered dimension and check; a free-form scope
description or a receipt for only one specialty is insufficient.

The scope manifest also contains
`ordered_forbidden_term_rules[token,match_mode,allowed_section_or_path_patterns,reason]`.
The structural validator scans the exact candidate bytes using those frozen
rules. An occurrence outside an allowlisted compatibility, quotation, migration
or explanatory location fails the round. The registry itself, its ordering and
every exception are part of `scope_manifest_digest`; an auditor cannot invent a
new exception while reviewing the file.

Each receipt contains exactly:

```text
schema_version
signed_payload[
  schema_version
  round_sequence
  auditor_actor_id
  auditor_role
  auditor_independence_attestation
  tool_or_model_identity
  tool_or_model_version
  scope_manifest_digest
  canonical_serialization_profile_digest
  hash_domain_registry_digest
  reviewed_master_plan_sha256
  reviewed_master_plan_byte_length
  reviewed_master_plan_git_blob_id
  started_at_utc
  ended_at_utc
  finding_count
  result
  audit_payload_digest
]
signature_algorithm
signing_key_id
signature
receipt_digest
```

`result=CLEAN` requires `finding_count=0`. Sequences are exactly `1,2,3`;
auditor actor IDs and signing-key IDs are pairwise distinct, no auditor is the
document author or implementer, each receipt reviews the same exact SHA-256
and byte length, and round `n+1` starts only after round `n` ends. A byte edit
invalidates the entire set. The receipt set contains the ordered three receipt
digests, reviewed master-plan identity, independence-validation result and
`master_plan_quality_receipt_set_digest`, under this exact field contract:

```text
schema_version
reviewed_master_plan_sha256
reviewed_master_plan_byte_length
reviewed_master_plan_git_blob_id
canonical_serialization_profile_digest
hash_domain_registry_digest
scope_manifest_digest
ordered_receipt_digests
auditor_actor_ids
signing_key_ids
pairwise_actor_independence_verified
pairwise_key_independence_verified
non_author_non_implementer_verified
strict_nonoverlap_verified
complete_scope_verified
all_results_clean
master_plan_quality_receipt_set_digest
```

Actor and key arrays follow round order; `ordered_receipt_digests` has exactly
three entries. Before round 1, the candidate bytes of
`canonical_serialization_v1.json` and `hash_domain_registry_v1.json` are also
frozen outside Git, their raw-byte bootstrap digests are calculated by the
non-recursive rule in section 16, and every receipt binds those same values.
Neither bootstrap file may change between rounds or during genesis. The nested
signed payload uses
`GTBI_MASTER_PLAN_AUDIT_PAYLOAD_V1`, with only `audit_payload_digest`
omitted. The stored digest uses the mandatory `sha256:<64 lowercase hex>`
grammar; the frozen signature algorithm removes exactly the literal
`sha256:` prefix, hex-decodes the 64-character suffix and signs those raw
32 bytes. It rejects a missing/different prefix, mixed-case or malformed hex,
and a non-canonical algorithm/key encoding. The outer receipt binds that
payload, its digest, algorithm, key and signature under
`GTBI_MASTER_PLAN_AUDIT_RECEIPT_V1`, with only
`receipt_digest` omitted. The set uses
`GTBI_MASTER_PLAN_QUALITY_RECEIPT_SET_V1`, with only each object's own digest
field omitted. Before PR 1, the signed bytes are held in the external bootstrap
transaction record. PR 1 imports those exact bytes and the structural validator
recomputes every digest, verifies all three signatures and rejects self-review,
overlap, reordering, stale bytes or a missing round. The runbook core may cite
only that verified set digest.

### 1.2 How To Use This Document

This file is intentionally complete rather than short. Use it in this order:

| Need | Authoritative section |
|---|---|
| Understand the product boundary and immutable science | Sections 2 and 3 |
| Confirm what may run locally or in GitHub | Section 4 |
| Refresh current repository, artifact and governance facts | Section 5 |
| Assign owner-controlled responsibilities | Section 6 |
| Resolve source-of-truth, custody and identity questions | Section 7 |
| Determine whether work is reachable | Sections 8 through 10 |
| Execute one task and record its evidence | The task's gate section, 11 through 21 |
| Follow the shortest valid sequence | Section 22 primary priority map |
| Decide go, no-go or terminal closure | Sections 23 and 24 |
| Check exclusions and external authorities | Sections 25 and 26 |

The master task matrix is the inventory, the detailed gate section is the task
procedure, the dependency graph decides reachability and section 22's primary
priority map decides priority among concurrently ready tasks. Task IDs mentioned
elsewhere in section 22 are explanatory references, not additional priority
assignments. If those four views disagree, the structural validator fails and no
view wins by prose precedence. Machine records and signed receipts remain
authoritative after publication; unchecked Markdown boxes are reader aids only.

## 2. Unified V7 Decision

The proposed target, pending the formal `PREV7-0101` and `PREV7-0103`
records, is:

```text
product=GTBI V7 Performance Engine
scientific_baseline=gtbi-v7-frozen-data-lake-v1
scientific_lineage=GTBI_V7_CANONICAL_SUCCESSOR_1
v6_equivalence_claim=false
execution_environment=GitHub Actions
security_control_plane_deadman=github_native_non_scientific
```

V7 includes:

- all readiness and preservation work in this document;
- complete GitHub and local reorganization;
- exact frozen canonical-successor scientific semantics;
- maximum measured use of four vCPU per runner;
- preplanned profile-selected internal execution;
- FeatureStore;
- multilevel reuse and dedupe;
- non-gating vectorized prefilter diagnostics;
- cost and memory-aware scheduling;
- efficient artifacts;
- hierarchical merge;
- checkpoint and selective recovery;
- scientific and runtime diagnostics.

`GTBI Fast Strict V6 Performance v2` remains a preserved historical reference.
It is not the successor baseline and cannot supply an equivalence claim.

`GTBI Clean Portfolio` is not part of this V7. Shared capital, portfolio
sizing and portfolio risk change the science and must be implemented later as
a separately named research product after V7 is validated.

The existing branch `codex/gtbi-clean-portfolio-sizing-v7` is reference-only.
It must not be used as the implementation base.

The target implementation branch will be created from the latest fetched
`origin/main`:

```text
codex/gtbi-v7-performance-engine
```

Before creating it:

```text
git fetch origin --prune
base_sha=origin/main
```

The local `main` reference must never be assumed current.

The full campaign remains `NO-GO` until gates G0 through G8 are green for the
same immutable authorization attempt and the separate owner dispatch receipt
is valid. G9 and G10 are post-full preservation, retirement and project-
completion gates and therefore cannot be prerequisites for dispatch.

### 2.1 Repository Terminology

The following names are disjoint throughout this plan:

```text
canonical_source_repository =
    trading-optimizer-lab-org/aurora

source_execution_transport_repository =
    new disposable repository created for exactly one campaign
    preferred_visibility=public
    fallback_visibility=private only with approved four-CPU larger runners

independent_destination_repository =
    separately administered repository in the disaster-copy owner's account

canonical_primary_asset_store =
    immutable primary private Release-asset repository approved by the licence policy

canonical_mirror_asset_store =
    independently published mirror private Release-asset repository

canonical_asset_stores =
    collective name for the primary and mirror stores; never one repository
    presented as two copies
```

`source repository` without a qualifier always means the canonical Aurora
repository. In the preferred topology, scientific matrix jobs run only in the
public disposable execution repository from an attested template bound to the
canonical source SHA. Public visibility is deliberate: the standard Linux
runner currently provides four
CPUs and 16 GB there, versus two CPUs and 8 GB in a private repository. No
licensed input, plaintext scientific output, credential or unrelated run is
stored there. Provisioning or deleting that repository never changes the
canonical source, asset store or independent destination.
This is the preferred topology only after the licence decision explicitly
approves encrypted public Actions transport; section 17 defines the fail-closed
private larger-runner replacement when it does not.

## 3. Immutable Scientific Rules

### 3.1 Dates

```text
train_end=2010-12-31
validation_start=2011-01-01
validation_end=2020-12-31
historical_post_validation_start=2021-01-01
train_start_policy=earliest_eligible_session_in_frozen_historical_execution_pack
```

Legacy schemas may continue to emit `locked_start=2021-01-01` for byte and
consumer compatibility, but every V7 schema marks it deprecated and emits the
unambiguous fields below:

```text
historical_exclusion_start=2021-01-01
historical_post_validation_contaminated=true
pristine_locked=false until a new forward lock is authenticated
new_forward_available=false until that lock contains an eligible session
first_market_session_locked=null until approved
first_market_session_locked_by_market_digest_or_null=null until approved
forward_lock_calendar_manifest_digest_or_null=null until approved
later_required_approval_utc_or_null=null until approved
```

`locked_start` is only an alias of `historical_exclusion_start`: rows on or
after that date are excluded from train and validation. It never claims that
the already observed period is pristine. A future pristine lock uses the
separate `first_market_session_locked` field and manifest.

Rules:

- Train and validation must never read a row after `2020-12-31`.
- Train has no user-overridable synthetic start date. Its global and per-instrument
  first eligible sessions come from the frozen historical execution-pack
  manifest; adding older rows, filling a pre-listing history or changing that
  policy creates a new data and campaign identity.
- No scientific market observation, effective event, availability timestamp,
  membership/eligibility fact, metric or derived value on or after
  `2021-01-01` may be mounted, read or consumed by historical selection,
  ranking or execution. Operational provenance created later, such as retrieval
  time, attestation, invoice or manifest creation time, is permitted only in a
  separately typed metadata field and can never enter a feature, signal,
  eligibility decision, filter, score or ranking.
- The sole exception is an exact recovered V6 static-universe identity used
  only to reproduce the already contaminated reference. Workers may mount its
  symbol/eligibility manifest but no post-2020 market observation or metric;
  outputs must remain labelled `survivorship_biased_reference`.
- No scientific modification may cite a `2021+` result as its justification.
  Human exposure to previously observed results cannot be undone or proven
  absent; controls therefore prove only present asset isolation, input
  non-consumption and review provenance.
- Existing `2021+` results have already been observed and are therefore
  contaminated historical post-validation evidence, not pristine locked
  evidence. V7 remains historically contaminated research until genuinely new
  forward observations accumulate.
- A new pristine forward lock starts separately per market on the first session
  whose open UTC is strictly after the later of the independent
  `Locked approver` approval and repository-owner authorization, under the
  frozen calendar manifest. Neither approval substitutes for the other.
- The new forward start is written once, hashed and never moved backwards.

### 3.2 Trading Contract

Until a separate scientific ADR changes it:

- long or cash only;
- next-session open execution;
- execution and signal construction use no future row relative to their frozen
  reference semantics;
- no data after `2020-12-31` in train or validation;
- same universe and eligibility rules as the approved V6 contract;
- same entries, exits, costs, ordering and final filters as the approved V6
  contract;
- deterministic results for the same input bytes and manifest.

The document separates two identities that must never be conflated:

```text
v6_reference_equivalence:
  reproduces exact frozen V6 semantics, including any authenticated static-
  universe, retrospective-adjustment or calendar-date alignment contamination
  reference_index_order_confirmed=true is still required
  no_lookahead_confirmed=false whenever any fact was unavailable at its real
  decision cutoff
  historical_causal_claim_allowed=false whenever any temporal component is
  contaminated or unverifiable

causal_historical_evaluation:
  separately named scientific identity
  universe_temporal_model=point_in_time
  adjustment_temporal_model=as_known_each_session
  cross_market_alignment_model=causal_asof_utc
  every scientific fact satisfies available_at_utc<=decision_cutoff_utc
  no_lookahead_confirmed=true
  historical_causal_claim_allowed may be true only through the frozen
  conjunction below
```

Therefore `no_lookahead_confirmed` is not an unconditional label for the V6
reference. The unambiguous fields are
`reference_index_order_confirmed`, `no_lookahead_confirmed`,
`universe_point_in_time_claim_allowed`,
`adjustment_point_in_time_claim_allowed`,
`causal_cross_market_claim_allowed` and
`historical_causal_claim_allowed`. Universe claims are scoped by the frozen
`universe_temporal_model`:

```text
point_in_time:
  membership, eligibility, market-cap observations, listing effective dates,
  delisting effective dates and aliases are known as of each historical session

static_post_period:
  the exact V6 static universe is preserved for reference equivalence
  result_classification=survivorship_biased_reference
  observation_timestamp_state=unknown_unverifiable when no authenticated
    historical observation timestamp exists
  exact_universe_identity_digest is mandatory
  no point-in-time or survivorship-free claim is permitted
  no statement may imply that the static universe was knowable at a historical
    decision time
```

The snapshot must select exactly one mode and prove its required evidence. A
static universe discovered after the tested period cannot be described as
lookahead-free merely because price indicators use causal windows.
Missing historical availability timestamps do not by themselves force
`NO-GO` when the selected mode is `static_post_period`: they must be recorded
as `unknown_unverifiable`, force the explicit survivorship-bias label and
prohibit every point-in-time, causal-universe and survivorship-free claim.
The same missing evidence is blocking when the selected mode is
`point_in_time`.

### 3.3 Performance Contract

Performance work may change:

- execution order;
- caching;
- process layout;
- serialization;
- partitioning;
- scheduling;
- checkpointing;
- artifact transport;
- merge topology;
- telemetry.

Performance work may not change:

- eligible observations;
- signals;
- entry or exit dates;
- fills;
- trade returns;
- annual metrics;
- final filter decisions;
- ranking;
- locked boundaries.

## 4. GitHub-Only Policy

### 4.1 Never Executed Locally

The laptop must not execute:

- backtests;
- research campaigns;
- optimization;
- strategy evaluation;
- performance benchmarks;
- smoke campaigns;
- heavy merges;
- mass downloads;
- data snapshot builds;
- scientific equivalence suites;
- project test suites.

### 4.2 Allowed Locally

The laptop may be used for:

- reading and searching files;
- editing code and documentation;
- inspecting already downloaded artifacts;
- non-destructive Git commands;
- preparing commits and pushes;
- querying GitHub with `gh` or the GitHub API;
- read-only inventory of paths and metadata;
- the one-time owner-authorized, byte-for-byte preservation transfers described
  in `PREV7-0003` and `PREV7-0005`, with no scientific processing.

Any local result is informational only. Every executable acceptance check is
run again in GitHub Actions and only the GitHub result is authoritative.

All scientific execution and acceptance run only in GitHub Actions. The closed
allowlist of external, non-scientific managed runtimes is:

1. the source and destination lease-deadman control planes that revoke local
   credentials and restore deny-all when Actions is unavailable;
2. the fixed-operation App/key brokers and HSM/KMS proxies that retain keys and
   provider tokens, perform only manifest-bound calls and return only permitted
   byte streams, public material, one-use attested handoffs or receipts;
3. the temporary `bootstrap_preservation_controller`, used only for the exact
   artifact `8251391531` preservation ceremony before the normal path is safe.
   Its closed operation allowlist is: read that artifact, stream its opaque
   bytes into the named immutable escrow object, execute the bounded
   write/read/restore/reversal probes against that object and namespace, emit
   the handover/closure receipts, uninstall only its own temporary App
   installation and destroy only its own imported bootstrap key after verified
   handover; and
4. the destination-controlled cold verifier, used only for bounded restore,
   offline decrypt, hash and manifest verification of retained ciphertext.

Each entry has a frozen workload identity, deployed-code/configuration digest,
provider/account/region, exact operation/data allowlist, output-receipt schema,
credential and plaintext lifecycle, teardown or retention policy and negative
authorization tests. None may evaluate, filter, rank or classify strategies,
build scientific features, simulate trades, merge scientific rows or publish a
scientific conclusion. The bootstrap controller is removed after the
`PREV7-0003` handover and closure receipt; the other runtimes remain only for
their stated control or recovery duties. None is hosted on the laptop. Their
versioned code/configuration, deployment identity, permissions, liveness and
receipts are reviewed from Git, while all scientific acceptance remains in
GitHub Actions. `PREV7-0604` rejects any external runtime not in this exact
allowlist or any allowed runtime whose identity, digest, operation, input or
output exceeds its registered contract.

Git hooks must not silently start tests, downloads or research. The repository
must document any hook that executes code.

### 4.3 PREV7-0604: Central Execution And External-Runtime Enforcement

All scientific and repository-workflow protected entry points require a
role-specific GitHub identity:

```text
GITHUB_ACTIONS=true
RUNNER_ENVIRONMENT=github-hosted
validated_github_execution_receipt=true

canonical_controller:
  GITHUB_REPOSITORY_ID=canonical_source_repository_id

scientific_or_merge_job:
  GITHUB_REPOSITORY_ID=source_execution_transport_repository_id
  GITHUB_SHA=execution_repository_commit_sha

independent_copy_or_capsule_job:
  GITHUB_REPOSITORY_ID=independent_destination_repository_id
```

The closed external-runtime allowlist uses a separate entrypoint and never
spoofs these GitHub variables. It requires the registered external workload
identity and attestation, deployed digest, operation/data manifest and fresh
lease from section 4.2; it rejects `GITHUB_ACTIONS=true` as a substitute.
Cross-mode tests prove no external identity can enter a scientific/merge path
and no Actions job can invoke an unregistered external operation.

Environment variables alone are not proof because a local user can spoof them.
Before assets are staged, a protected controller validates the dispatch capsule
and GitHub API run/job/repository-ID/ref/SHA/role identity, obtains and verifies the
expected GitHub OIDC claims, and writes a short-lived
`github_execution_receipt.json` bound to campaign, workflow run ID, job ID,
attempt, code SHA, capsule digest and expiry. The scientific container receives
that read-only receipt but no credential. Publication accepts outputs only when
the receipt, GitHub API job evidence and artifact/package attestation agree.
A replayed, locally fabricated or expired receipt cannot acquire private
inputs, checkpoint publication or canonical status.

No software guard can stop a determined local user from editing their own copy
and doing private computation; the enforceable guarantee is that such bytes
cannot enter any accepted evidence, checkpoint, merge or canonical result.

The old environment escape hatch must not authorize research automatically.
GTBI V7 has no local execution bypass. If an emergency local bypass remains
for unrelated legacy Aurora code, it must:

1. default to disabled;
2. require a unique explicit value;
3. emit an audit record;
4. be covered by a failing CI test if enabled in repository workflows;
5. never be used for canonical results.

The historical V7 CLI exposes no `--include-locked` option and cannot accept a
post-2020 data asset. Future forward evaluation, if ever approved, uses a
separate command, workflow, package identity and protected environment.

## 5. Verified Reference Snapshot

These facts were verified at the audit timestamp. They are not permanent.
`PREV7-0001` creates and validates the inventory generator. G0 uses its initial
snapshot; every later gate preflight reruns that pinned generator, stores a new
append-only snapshot and compares it with the previous accepted snapshot.
Completing the task once never makes its old inventory current.

### 5.1 Branches

| Reference | SHA |
|---|---|
| `origin/main` | `56251bbdd76a994b5032b912e9266253af3f4091` |
| V6 branch `codex/gtbi-github-only-external-pack-72000` | `cb80c5065c127322a303d58aea0f6c05337a6c9e` |
| current V7 reference branch `codex/gtbi-clean-portfolio-sizing-v7` | `c4df224a2ff4f04e83963ab357c01e2d79048936` |

The current V7 reference branch is divergent and must not be rebased into the
new implementation branch. At the audit snapshot its merge base with
`origin/main` is `3dd8be5821c3c68f2b0712fc998ee8880de59dc9`; it has `192`
reference-branch-only commits and is missing `120` `origin/main` commits. These
counts are inventory facts, not a merge or rebase instruction, and
`PREV7-0001` must refresh them.

### 5.2 V6 Final Result At Immediate Risk

```text
run_id=29162930823
artifact_id=8251391531
artifact=global-technical-buy-indicator-long-hold-fast-strict-v6-results
size_bytes=1962204087
digest=sha256:870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b
expires_at=2026-08-10T18:16:37Z
leaderboard_rows=72000
filtered_leaderboard_rows=0
early_rejected_rows=0
yearly_trade_performance_rows=1947000
canonical_leaderboard_rows=3600
canonical_filtered_leaderboard_rows=0
canonical_yearly_trade_performance_rows=87150
best_candidate_id=lhv1_0405081ff8_fam_43_v1006
best_adjusted_return_time_risk=0.0005410569585308
strict_final_pass=true
```

The legacy `best_adjusted_return_time_risk` above is the adjusted metric of the
score-best row, not the maximum adjusted metric in the leaderboard.
The legacy `strict_final_pass=true` is a package-integrity/strict-merge
completion flag hard-coded by the final V6 merger after its coverage checks.
It does not mean that a candidate passed the scientific filters; zero
canonical and zero alias-expanded filtered rows prove that none did. V7 keeps
that legacy field only through the compatibility manifest, renames its
unambiguous native equivalent `package_integrity_pass`, and never derives
`final_filter_pass`, `passing_candidate_count` or a scientific claim from it.

Preserving this artifact is priority `P0`. No refactor takes priority over it.

### 5.3 Missing V6 Reproducibility Inputs

The source data artifact from run `27936694743` expired on `2026-07-06`.

```text
artifact=free-global-yahoo-daily-data-lake
size_bytes=3184328263
status=expired
```

The derived data artifact from run `29148013009` also expired:

```text
artifact=gtbi-external-pack-data
size_bytes=375673933
status=expired
```

The remaining final result from run `29148013009` is not a substitute for the
missing input data.

V6 is not fully reproducible until all required input bytes are recovered and
authenticated. The owner-authorized canonical-successor amendment does not
change that classification. It permits the separately authorized V7 campaign
to complete this plan only under its own identity and limitations.

### 5.4 Governance

Verified state:

```text
repository_visibility=public
admin_collaborators=1
admin_login=gomez5757
teams=0
branch_protection=absent
rulesets=absent
dependabot_security_updates=disabled
secret_scanning=enabled
secret_scanning_non_provider_patterns=enabled
secret_scanning_push_protection=enabled
secret_scanning_validity_checks=enabled
web_commit_signoff_required=false
allow_forking=true
delete_branch_on_merge=false
queued_legacy_runs=12
in_progress_legacy_runs=0
registered_artifact_records=326415
registered_worktrees=30
dirty_worktrees=9
prunable_missing_worktree_paths=1
target_branch_exists=false
private_asset_repository_exists=false
pr_20_state=open
pr_20_mergeable=true
pr_20_head_sha=3139bd1843274748a05c25a8c3f88fa65ea5cec4
pr_20_base_sha=56251bbdd76a994b5032b912e9266253af3f4091
pr_20_failed_checks=12
local_main_sha=0ca928bd1f901c47a1c411fd95ba626e772152f6
origin_main_sha=56251bbdd76a994b5032b912e9266253af3f4091
```

Independent review and separate-person locked approval are not required under
the owner simplification directive. Locked access itself remains prohibited
unless the owner later authorizes the exact operation.

## 6. Roles And Approval Model

The only mandatory human authority is the repository owner, `gomez5757`.
Codex or another named engineer may implement owner-approved technical work.
All other names in this section are retained solely as capability labels for
compatibility with existing schemas and historical runbooks. They may all map
to the owner or automation, and a vacant label never blocks a task or gate.
Separation-of-duty and incompatibility rules in the retired model are optional
hardening recommendations.

| Role | Responsibility | Legacy separated assignment (optional) |
|---|---|---|
| Repository owner | V7 identity, budget and destructive approvals | `gomez5757` |
| Implementer | Code, workflows, tests and evidence | Codex or assigned engineer |
| Workflow reviewer | Reviews Actions, permissions and recovery | Vacant |
| Scientific reviewer | Reviews equivalence and locked boundaries | Vacant |
| Independent security reviewer | Reviews the threat model, provider-host trust, App custody and residual-risk acceptance independently of the implementer, owner and App managers | Vacant |
| Licence and acceptable-use reviewer | Reviews provider/data licences, GitHub Actions acceptable use and publication/processing constraints | Vacant |
| Independent redaction reviewer | Reviews proposed public evidence independently of its author and repository owner | Vacant |
| Source App manager | Creates, installs, rotates and removes source-side GitHub Apps under owner-approved manifests; performs no scientific or workflow approval | Vacant |
| Destination App manager | Creates, installs, rotates and removes destination-side GitHub Apps under destination-owner-approved manifests; performs no source action | Vacant |
| Source deadman operator | Operates the source external deadman without scientific or destination access | Vacant |
| Source deadman deputy | Independently restores or retires the source deadman when the primary is unavailable | Vacant |
| Destination deadman operator | Operates the destination external deadman without source or scientific access | Vacant |
| Destination deadman deputy | Independently restores or retires the destination deadman when the primary is unavailable | Vacant |
| Source key-broker custodian | Controls source sign-only broker policy and witnessed key lifecycle, without full authorization power | Vacant |
| Destination key-broker custodian | Independently controls destination sign-only broker policy and witnessed key lifecycle | Vacant |
| Workflow initiator | Starts the exact reviewed workflow after approval; recorded per run and ineligible to approve that same deployment or authorization | Vacant |
| Locked approver | Approves creation or access to new forward lock | Vacant |
| Independent disaster-copy owner | Exclusively performs routine destination administration, credential custody and restore evidence; sealed break-glass succession is separate | Vacant |
| Source break-glass custodian | Holds sealed source-account recovery custody; never performs routine approval or implementation | Vacant |
| Destination break-glass custodian | Holds sealed destination-account recovery custody; never has source access or routine destination duties | Vacant |
| Source account-root custodian | Holds one sealed root/IAM recovery role for exactly one named source failure domain; every additional source broker/WORM/KMS failure domain has a different registered root custodian | Vacant |
| Destination account-root custodian | Holds one sealed root/IAM recovery role for exactly one named destination failure domain; every additional destination broker/WORM/KMS failure domain has a different registered root custodian | Vacant |
| Source billing-payer authorizer | Authorizes source-domain monetary reservations and payments but cannot authorize science, Apps, brokers, WORM/KMS or campaign dispatch | Vacant |
| Destination billing-payer authorizer | Authorizes destination-domain monetary reservations and payments but cannot authorize source resources, science, Apps, brokers, WORM/KMS or campaign dispatch | Vacant |
| Source App-custody organization owner | Holds irreducible owner authority only over source App-custody organizations; cannot authorize science, full execution or destination custody | Vacant |
| Destination App-custody organization owner | Holds irreducible owner authority only over destination App-custody organizations; cannot authorize source resources, science or full execution | Vacant |
| Source App-manager JIT approver | One of exactly two indexed, distinct source-custody actors required to activate a source App manager; has no App key, manager or campaign authority | Vacant (two assignments required) |
| Destination App-manager JIT approver | One of exactly two indexed, distinct destination-custody actors required to activate a destination App manager; has no source, App key, manager or campaign authority | Vacant (two assignments required) |
| Source dual-control witness | Witnesses one exact source key/App/destructive ceremony without holding its key, manager, root, payer or authorization authority | Vacant |
| Destination dual-control witness | Independently witnesses one exact destination key/App/destructive ceremony without source or operational authority | Vacant |

The canonical role enum is versioned once in the role-registry schema and is
the only accepted vocabulary for `owner_role`, `required_approver_roles`,
receipts and incompatibility rules:

```text
repository_owner
implementer
workflow_reviewer
scientific_reviewer
independent_security_reviewer
licence_and_acceptable_use_reviewer
independent_redaction_reviewer
source_app_manager
destination_app_manager
source_deadman_operator
source_deadman_deputy
destination_deadman_operator
destination_deadman_deputy
source_key_broker_custodian
destination_key_broker_custodian
workflow_initiator
locked_approver
independent_disaster_copy_owner
source_break_glass_custodian
destination_break_glass_custodian
source_account_root_custodian
destination_account_root_custodian
source_billing_payer_authorizer
destination_billing_payer_authorizer
source_app_custody_organization_owner
destination_app_custody_organization_owner
source_app_manager_jit_approver
destination_app_manager_jit_approver
source_dual_control_witness
destination_dual_control_witness
```

Aliases, display labels and free-form role strings are invalid in machine
records. One role may have several explicitly indexed assignments only where
the schema requires one different custodian per named failure domain.

Rules:

- At least two additional trusted GitHub collaborators must exist before
  independent scientific and workflow approvals can both be satisfied.
  Repository-owner
  approvals for storage, budget, environment and destructive actions remain
  mandatory from G0.
- Until then, branch protection may require PRs and checks with zero required
  approvals. It must still block force-push and deletion.
- CODEOWNERS review becomes mandatory only after an eligible reviewer exists.
- The role registry freezes immutable actor IDs, named deputies and a symmetric
  incompatibility matrix. It explicitly requires owner, implementer,
  scientific reviewer, workflow reviewer, independent security reviewer,
  locked approver and independent
  disaster-copy owner to be distinct whenever those roles participate in the
  same decision. The licence/acceptable-use and redaction reviewers are
  distinct from the author and repository owner for what they sign; the
  workflow initiator is distinct from that deployment's approver and full
  authorizer. The matrix may permit one qualified independent reviewer to hold
  another non-conflicting review role. Inside each custody domain, the owner
  or destructive authorizer, billing-payer authorizer, App manager, deadman
  operator, deadman deputy, key-broker custodian, break-glass custodian and
  every account-root/IAM custodian, App-custody organization owner and each
  indexed JIT approver are distinct people. The two JIT approvers in one
  domain are also distinct from one another. The domain's dual-control witness
  is distinct from the operation's owner, manager, custodian, root, payer,
  implementer and JIT approvers. Root custodians for
  separate broker/WORM/KMS failure domains are also distinct from one another.
  No actor
  controls any two of deadman deployment, sign-only broker policy, App
  configuration and campaign authorization. No person can
  satisfy incompatible roles
  through another login, bot or delegated App. A role may remain vacant, but
  every dependent task then remains blocked rather than silently assigning the
  duty to the repository owner.
- No human holds a privileged source-custody role and a privileged destination-
  custody role. Separate accounts, organizations or logins do not make the same
  person independent.
- “Zero standing App-manager access” means zero standing delegated App-manager
  access. A GitHub organization owner retains irreducible platform power to
  administer Apps and installations. Source and destination organization
  owners are different actors in different custody domains, use separately
  administered authentication/recovery, generate WORM alerts for every owner
  action and cannot approve their own scientific, workflow, security or
  cleanup decision. This residual platform risk is explicit and independently
  accepted; the plan never claims that GitHub can technically remove it.
- Repository/organization owners, reviewers, App managers, deadman operators
  and deputies, key-broker custodians, account-root custodians, billing-payer
  authorizers and the independent disaster-copy owner
  use phishing-resistant authentication, maintain two registered
  authenticators and have documented recovery custody. The source
  break-glass custodian is distinct from every owner, implementer, reviewer,
  locked approver, disaster-copy owner and App manager, with no routine
  repository access, no normal approval role and no campaign secret. Quarterly
  access review tests every privileged role, deputy, broker policy, App
  installation, break-glass path, role incompatibility and recovery custody.
- The destination break-glass custodian is distinct from every source role and
  from the independent destination owner. Destination succession preserves
  exclusive destination custody: two phishing-resistant authenticators,
  separately held recovery material, quarterly total-owner-loss restoration
  and immediate key rotation after offboarding or compromise are mandatory.
- `licence reviewer`, `security reviewer`, `App manager`, `redaction reviewer` and `workflow
  initiator` are never informal labels. Their immutable actor IDs, assignment,
  deputy, incompatibilities and authentication evidence are required fields in
  the role registry and every affected task or run receipt.
- Offboarding, role loss, suspected compromise or loss of an owner, reviewer,
  App manager, deadman operator or deputy, key-broker custodian, account-root
  custodian, billing-payer authorizer or break-glass custodian immediately
  suspends affected Apps and lease activation, rotates
  keys and broker policy, removes actor access and invalidates every pending
  approval, authorization envelope, dispatch capsule and unconsumed recovery
  capsule that depended on that actor or snapshot. A tested break-glass
  procedure can restore source ownership but cannot approve scientific,
  workflow, locked or destructive actions.
- Each custody domain freezes a
  `domain_owner_succession_manifest.json` before any campaign resource exists.
  It names a same-domain successor pool, quorum, authenticators, recovery
  materials, provider account/organization, maximum activation time and
  narrower emergency permissions. On owner loss, that domain's break-glass
  custodian, account-root custodian and dual-control witness may jointly
  suspend/revoke, activate exactly one pre-registered successor and rotate
  local credentials. They cannot approve science, expand budget/scope, delete
  retained evidence, command the other domain or self-appoint an unregistered
  actor. The successor must issue fresh role, security and authorization
  receipts; every approval from the missing owner is invalid. Total-owner-loss,
  one-custodian-loss, conflicting-successor and cross-domain-denial drills are
  required before G3B and quarterly thereafter.
- `gtbi-forward-locked` remains disabled while the locked approver role is
  vacant.
- `PREV7-0308` remains blocked while the disaster-copy owner is vacant or has
  any source-organization administrative credential that could alter both
  copies.
- `gtbi-full` may be created while roles are vacant, but it remains disabled
  until independent scientific and workflow reviews exist. Repository-owner
  authorization is additional and never substitutes for those reviews.

`config/gtbi/governance/role_registry.json` is the canonical role registry and
is validated as a bipartite actor/role assignment problem, not by informal
counting. Any `role_registry.csv` is a generated, digest-bound projection whose
rows must compare exactly with that JSON and cannot authorize an action.
`role_incompatibility_matrix.csv` enumerates every
forbidden pair above; the readiness generator proves each required ceremony has
a complete distinct-actor matching, reports the exact minimum and available
actor counts by custody domain, and blocks the task when no matching exists.
Deputies and successors are tested by removing each primary actor in turn; a
name listed twice never creates two people.

`disabled` has one technical meaning: the relevant App installation is
suspended, deployment branch/tag rules deny every ref, every token issued
through a controlled route is revoked where the provider supports revocation,
and a negative-access probe proves that no issued token can currently access
the installation. GitHub provides no exhaustive token inventory, so the plan
does not claim to enumerate every token. Managed App and campaign-recipient
private keys remain encrypted and non-exportable only in their disjoint external
broker/HSM compartments while their frozen rotation or recovery-retention
policy requires them. GitHub environments retain only audience-bound broker
client identities or reduced short-lived tokens; disabled state makes those
routes unusable, not magically reconstructible after key deletion. Activation requires
a digest-bound receipt and creates an immutable lease whose canonical schema
includes `lease_id`, monotonically increasing `generation`,
repository/run/attempt, installation IDs, environment IDs, exact secret names
and value fingerprints, state, heartbeat sequence/deadline, absolute expiry,
expected-record version and cleanup-receipt digest. State changes are atomic
compare-and-swap transitions in the owning custody domain's authoritative
registry. An old heartbeat
cannot extend a newer generation, and an old cleanup cannot remove or suspend
resources owned by a replacement lease. An in-run finalizer attempts to suspend
the installation, revoke active tokens, remove only exact
lease-generation-bound transient secrets and restore deny-all rules.

The runbook freezes `max_campaign_lease_ttl_seconds=21600`,
`max_external_security_operation_lease_ttl_seconds=3900` and
`lease_expiry_safety_margin_seconds=120`. Creation must satisfy:

```text
campaign_lease_expiry <= active_authorization_expiry
operation_lease_expiry <= campaign_lease_expiry
operation_lease_expiry <= active_authorization_expiry
provider_token_expiry <= operation_lease_expiry
bounded_operation_finish + safety_margin <= operation_lease_expiry
```

The broker refuses to mint when the provider's fixed token lifetime cannot fit
these inequalities. No activation may choose an arbitrary distant absolute
expiry, and a continuation generation is required before a later segment can
receive a fresh lease.

Cleanup never depends on a cancelled workflow producing its own terminal
artifact or on the opposite custody domain being reachable. Source and
destination have separate sovereign lease registries. Each registry is
authoritative only for resources owned by its own domain and creates,
respectively, `source_campaign_terminal_manifest.json` or
`destination_campaign_terminal_manifest.json` through one irreversible
compare-and-swap transition from the current local lease generation. Each
local schema contains:

```text
campaign_id
custody_domain
lease_id
generation
terminal_state
terminal_cause
local_security_state
last_accepted_heartbeat_sequence
last_registry_sequence
absolute_expiry_utc
last_trusted_utc
trusted_time_attestation_digest
boot_id
monotonic_counter_at_attestation
terminalized_at_utc
previous_registry_event_digest
expected_record_version
terminal_manifest_digest
```

`terminal_state` is one of
`completed|failed|cancelled|expired|security_revoked`; `local_security_state` is
`active|security_abandoned|retired`. A local manifest is valid
even when cancellation occurs before the first scientific job starts. A second
local terminal transition, old generation or conflicting cause is rejected.
Each deadman terminalizes and cleans only its own exact generation-bound
resources and never waits for, calls or holds credentials for the other
domain.

Lease mutation authority is explicit and deny-by-default:

| Actor | Allowed CAS mutation | Forbidden |
|---|---|---|
| Protected activation controller | Create one next-generation lease from an exact approved authorization/capsule and move it to active | Editing an existing generation, extending absolute expiry, terminal cleanup |
| Exact admitted workload heartbeat identity | Increase only `last_accepted_heartbeat_sequence` and move `heartbeat_deadline` forward no further than the frozen heartbeat interval and never past `absolute_expiry_utc` | Changing state, resources, generation, policy, absolute expiry or cleanup |
| In-run finalizer | Terminalize the exact current generation and request its manifest-bound cleanup | Activation, renewal, another generation/domain or unmanifested resource |
| Domain deadman or Actions reaper | Irreversibly terminalize/expire the exact current local generation and clean only its manifest-bound local resources | Activation, heartbeat renewal, expiry extension, cross-domain cleanup or generation replacement |
| Read-only joint reconciler | Append a joint receipt referencing two already terminal local manifests | Any lease or resource mutation |

For a created generation, `campaign_id`, custody domain, `lease_id`,
`generation`, repository/run/attempt, App/installations/environments, exact
secret names/value fingerprints, admitted resource manifest, authorization/
capsule/policy digests, trusted-time policy and `absolute_expiry_utc` are
immutable. A heartbeat may change only its sequence, bounded deadline,
trusted-time attestation reference and record version. Terminalization may add
only terminal cause/time, local security state and cleanup receipt. Every API
request carries expected record version and exact generation; stale, duplicate,
out-of-order, cross-domain and post-terminal writes fail. Tests cover every
allowed cell and prove every forbidden cell, absolute-expiry extension,
resource substitution, heartbeat-after-terminal and deadman/reaper activation
fails.

All protected readiness/gate state is written by one monofunction
state-controller App. It may open or update a PR containing only schema-valid
append-only state events and regenerated projections; it cannot approve,
merge, dispatch workflows, alter environments, administer Apps or access
scientific assets. External dual-WORM event heads are authoritative. Git
contains reviewed projections. The controller performs compare-and-swap
against both prior WORM heads and the protected `main` blob digest; partial
publication leaves an explicit recovery transaction that can only complete the
same bytes or roll forward with a compensating event.

After both local cleanups, a non-admin reconciler with read-only access to the
two attestation feeds may create
`joint_campaign_terminal_manifest.json`. It binds both local terminal-manifest
digests, cleanup-receipt digests, states and generations, but has no cleanup,
App, broker, registry-write or scientific authority. Reconciliation may remain
`pending_remote_domain` during an outage without delaying either local
cleanup. Conflicting campaign or generation identities fail reconciliation;
they do not overwrite either sovereign record. These post-execution control
records belong to the append-only security evidence chains, not to the already
immutable scientific result package.

Because force-cancel can skip that finalizer and GitHub does not guarantee
timely `schedule` execution, each custody domain has two independent cleanup
paths:

1. an always-on deadman service outside GitHub Actions, operated in a reviewed
   managed control plane rather than on the laptop, receives authenticated App
   webhooks and independently polls the authoritative lease registry;
2. a protected Actions reaper outside every campaign concurrency group uses
   scheduled polling and manual recovery as a secondary path only.

The deadman receives no scientific/data/result payload or App, asset or
scientific credential. Its sole inbound-authentication secret is the
domain-specific GitHub webhook HMAC value described below, and its
broker necessarily retains each monofunction App's complete residual authority;
the plan does not mislabel that authority as suspension-only. App private keys
are imported through the selected `APP_PRIVATE_KEY_IMPORT` ceremony into
separate non-exportable brokers and are never
delivered to an operator, workflow, environment, JWT client or Actions secret.
The external deadman and secondary Actions reaper use different non-exportable
App-key objects in different broker/provider/account/region/IAM failure domains.
Each authenticates an exact lease-generation request to its own broker; that
broker itself verifies the frozen
repository/installation/action/body allowlist, mints any required JWT/token
internally, performs the suspension/revocation and returns only an attested
receipt. A client cannot request or receive a JWT, installation token or
arbitrary GitHub API call. At absolute lease expiry the broker refuses every
non-cleanup operation, revokes active tokens where supported and attempts
immediate installation suspension and generation-bound cleanup. Worker admission stops
at least one provider token lifetime plus clock/network margin before expiry,
so no accepted job can rely on a token surviving the lease.

Both paths publish liveness heartbeats to independently monitored registries.
A deadman alarm fires before the cleanup SLA can be breached. Full preflight
requires fresh healthy receipts from both paths in both custody domains and
refuses to activate any installation if one path is stale, disabled or unable
to execute a signed no-op suspension test. An optional notification may reduce
latency but is never relied upon, and `workflow_run` from another repository is
not treated as a cross-repository trigger.

G7 force-cancels fixtures while deliberately disabling each path and its broker
failure domain in turn and proves the other path, using its different key and
broker, completes cleanup inside the SLA without a job from the cancelled run.
It also tests total deadman/broker-health loss as fail-closed, stale and
replayed heartbeat, finalizer/reaper race, old-generation cleanup and
reactivation during cleanup. Failure to prove or perform cleanup blocks every
later token mint and full authorization.

The source Actions reaper runs only from protected canonical `main`. Its fixed
fan-out uses one `gtbi-security-control-<managed-app-id>` environment and one
job per managed App. Each compartment holds only a short-lived, audience-bound
client credential for that App's non-exportable broker endpoint; it never holds
the App private key, a GitHub JWT or an installation token. The broker performs
the one named suspension internally. No reaper job or environment aggregates
multiple broker clients or managed-App authorities.

A private key cannot be limited to suspension: its broker can exercise every
permission of that App over every installation. Therefore each managed App is
campaign-specific, monofunction, installed on exactly one allowlisted
repository and has no additional installation; these facts are rechecked before
each internal JWT or token mint. Broker request allowlists and audit
reconciliation are additional controls, not a claimed GitHub permission
boundary. Compromise of a broker or App key is recorded as compromise of that
App's full residual authority, and every such key rotates on retirement or
suspected disclosure.

A separate `gtbi-security-control` coordinator environment holds only a
secret-controller App capability with `Environments: write`, used to remove
exact lease-bound environment secrets. A distinct
`gtbi-environment-policy-control` compartment holds a campaign-specific
environment-policy App with the minimum unavoidable `Administration: write`
permission on only the disposable repository, used solely for the exact
environment-policy endpoints needed to restore frozen deny-all deployment
  rules. Its broader residual authority, one-repository installation,
  endpoint/method/body allowlist and complete API-audit reconciliation are frozen
  in the threat model. Every checkpoint, merge and final-result recipient
  private key lives only in an external, non-exportable OIDC key broker outside
  GitHub environment secrets. The secret-controller App is installed only on
  the disposable repository and its allowlisted environments contain
  lease-bound ephemeral values; API tests prove it cannot create, replace or
  delete any recovery key. Neither controller can ask a broker to destroy a
  checkpoint key before its dual-copy restore/recovery conditions, or any last
  result-recipient key while the corresponding canonical result remains
  retained. Neither has Actions
artifact, scientific asset, package, code, checkpoint or canonical publication
permission. Reaper workflow SHA, App/key/installation IDs, lease schema and
permitted API endpoints are allowlisted; every other endpoint is a failing
audit event. Suspension keys never enter campaign environments or scientific
jobs.

Checkpoint-recipient, merge-recipient and final-result-recipient keypairs are
generated natively inside their owning HSM/broker. Only public keys and
attested key IDs leave that boundary. Secure import is reserved for
GitHub-generated App private keys. A negative G7 test injects a synthetic
campaign private key into an Actions-bound route and must prove rejection
before any scientific worker starts.

No production key, App-key import, broker object or key-policy version may be
created, imported, activated, rotated, disabled, destroyed or changed without
a current signed receipt from the owning domain's canonical
`source_key_broker_custodian` or `destination_key_broker_custodian`. The
receipt binds operation, key/broker ID, before/after policy digests, actor/JIT
lease, dual-control witness, expiry and rollback/teardown manifest. It grants no
scientific, App-installation, dispatch or opposite-domain authority. Tasks
`PREV7-0204`, `PREV7-0308`, `PREV7-0610`, `PREV7-0611`, `PREV7-0805` and every
later lifecycle operation require the applicable receipt explicitly.

Loss, compromise or incapacity of that custodian does not require a receipt
from the lost actor. Each domain pre-registers a sealed
`key_custody_succession_manifest` naming its break-glass custodian, account-root
custodian, dual-control witness and an independently authenticated successor
candidate. By unanimous use of those three distinct emergency roles, the
manifest may only suspend the broker, revoke the former custodian, activate the
successor and rotate/recover existing campaign keys under unchanged or narrower
policy. It cannot create a campaign, expand scope, authorize science/dispatch
or destroy the last recoverable key. The resulting succession and
negative-access receipts enter both WORM registries; ordinary lifecycle resumes
only after the canonical role registry accepts the successor.

Force-cancel can leave a running job's `GITHUB_TOKEN` valid until the job ends
or the token expires. The disposable G7/campaign repository therefore also has
one monofunction `run-control` App installed nowhere else, with the minimum
unavoidable `Actions: write` permission. The deadman and Actions reaper use
different non-exportable run-control keys/brokers in disjoint failure domains.
Each broker accepts only `cancel` and, after the frozen grace interval,
`force-cancel` for exact current-generation run IDs recorded in the lease;
every other Actions endpoint, repository or generation is denied and audited.
Cleanup first requests normal cancellation, then force cancellation if needed,
suspends all other campaign Apps and leaves deny-all policies active.
Retirement cannot claim token revocation: it waits until every job is terminal
or the maximum platform token lifetime plus margin has elapsed and negative
access probes pass. The App's broad residual one-repository Actions authority
is recorded in the threat model and independently accepted.

The independent destination runs its own deadman service and protected
`gtbi-destination-lease-reaper` under destination-owner custody. Those two
destination compartments hold only their distinct audience-bound broker client
identities; their two distinct destination-replicator App keys remain
non-exportable in separate broker failure domains. They poll the destination
lease registry and emit chained cleanup receipts. No source repository, source
App, source reaper or source actor receives either key, broker client identity
or destination token. Source and destination cleanup receipts
bind the same campaign and their own local generations and terminal manifests.
Each cleanup is locally complete when its own receipt verifies. Joint campaign
reconciliation is complete only when both are available and consistent.

### PREV7-0610 And PREV7-0611: External Deadman Control Planes

The source and destination deadman services are separate P0 deliverables, not
an implied property of a workflow. Each has one accountable primary operator,
a distinct operational deputy and a task-record approval set. `PREV7-0610`
requires the source owner, workflow reviewer, source account-root custodian,
source billing-payer authorizer and source key-broker custodian.
`PREV7-0611` requires the independent destination owner, that workflow
reviewer, destination account-root custodian, destination billing-payer
authorizer and destination key-broker custodian. The payer receipts reserve the
exact native-currency deployment and standing-service ceiling approved under
`PREV7-0309`; a preliminary terms decision without those receipts cannot create
or run a resource. Each task freezes and proves:

```text
provider_account_region_and_failure_domain
service_and_deployment_digest
source_build_attestation_and_sbom
runtime_identity_and_minimum_iam
primary_operator_and_distinct_deputy
break_glass_and_incident_roles
deadman_key_id_and_non_exportable_broker_failure_domain
actions_reaper_key_id_and_non_exportable_broker_failure_domain
run_control_deadman_key_id_and_broker_failure_domain
run_control_reaper_key_id_and_broker_failure_domain
broker_pair_independence_and_single-outage_cleanup_receipt_set
webhook_sender_allowlist_and_HMAC_custody_policy
webhook_event_id_timestamp_nonce_and_replay_window
trusted_time_policy_digest_and_maximum_clock_skew
polling_and_egress_endpoint_allowlist
authoritative_CAS_lease_registry_identity
append_only_log_and_attestation_sink
monitor_alarm_and_liveness_receipt_policy
backup_restore_failover_and_disaster_test
patch_vulnerability_rotation_and_incident_runbook
native_currency_billing_domain_and_hard_budget
campaign_tenant_retention_and_teardown_manifest
active_job_cancel_force_cancel_and_token_expiry_policy
```

The source operator/deputy have no destination credentials; destination roles
have no source administrative or scientific access. The two services, brokers,
registries, logs and monitors are placed in separately controlled failure
domains. Neither sees scientific payloads, result plaintext or asset
credentials. Webhooks are advisory input only: authenticated sender, event ID,
timestamp, nonce and body digest are replay checked, then authoritative state
is reread from the CAS lease registry before action. Polling remains available
when webhook delivery fails.

GitHub webhook authentication uses one random HMAC secret per App and custody
domain. It lives only in that domain's external secret manager, is mounted
read-only into the deadman service, never enters Actions, a repository, log,
evidence bundle or the opposite domain, and is compared in constant time over
the exact raw request body. The policy freezes secret-manager object/version,
access identity, rotation period and bounded old/new overlap. Suspected
disclosure revokes both versions, rotates the webhook configuration under the
two-approver App-manager ceremony, disables webhook-triggered wakeups until a
signed test passes and relies on polling meanwhile. HMAC authenticates advisory
delivery only; no webhook can directly authorize cleanup or scientific action.

Webhook availability controls are frozen per domain:

```text
maximum_raw_body_bytes=1048576
per_sender_sustained_requests_per_second=20
per_sender_burst_requests=100
global_sustained_requests_per_second=100
verified_event_queue_capacity=10000
webhook_verification_concurrency=32
cleanup_polling_reserved_workers>=2
```

The managed edge rejects an oversized body with `413` before unbounded
allocation, applies per-sender and global limits before application work, and
permits only the GitHub webhook route/method/content type. The service streams
the bounded raw body into HMAC verification, replay checks before queueing and
stores only the fixed event envelope. Queue admission is bounded; overflow,
invalid-auth and repeated-event traffic is counted and dropped while the
authoritative registry-polling path continues. Webhook parsing, advisory queue
and cleanup polling use separate bounded pools, budgets and circuit breakers;
no webhook load can consume the reserved polling/terminal-cleanup capacity.
Provider DDoS/WAF limits, autoscaling ceiling, hard billing alarm and
backpressure policy are part of the deployment manifest. G7 floods valid,
invalid, replayed, oversized and slow requests above every limit and must prove
bounded memory/CPU/cost, polling and expiry cleanup inside SLA, no event loss
below the admitted limit and recovery after the flood.

Each domain freezes an independent trusted-time policy. It uses at least two
authenticated, independently operated time sources or one managed signed-time
attestation plus an independent monitor. UTC is used only for externally
comparable timestamps; elapsed lease and heartbeat intervals use a
suspend-inclusive monotonic source such as Linux `CLOCK_BOOTTIME`, never
`CLOCK_MONOTONIC` when that clock stops during suspend. The frozen policy
records the exact clock ID/capabilities and survives wall-clock correction.
Every accepted time
attestation is persisted atomically in the authoritative CAS registry with
`last_trusted_utc`, `absolute_expiry_utc`, `boot_id`,
`monotonic_counter_at_attestation`, attestation digest and registry version.
The persisted row is `trusted_time_attestation_event_v1` and contains exactly
`schema_version,custody_domain_id,sequence,previous_event_digest_or_null,`
`trusted_time_policy_digest,source_attestation_set_digest,last_trusted_utc,`
`absolute_expiry_utc,boot_id,monotonic_clock_id,`
`monotonic_counter_at_attestation,maximum_clock_skew_seconds,`
`trusted_time_liveness_max_age_seconds,expected_registry_version,actor_id,`
`actor_attestation_digest,event_digest`. `event_digest` uses
`GTBI_TRUSTED_TIME_ATTESTATION_EVENT_V1` with only itself omitted. Sequence
zero requires a null predecessor; every later row requires the exact prior
accepted event and CAS version.
`current_trusted_utc` is
accepted only while source agreement and wall/monotonic correlation remain
inside `maximum_clock_skew_seconds=30` and the latest attestation is at most
`trusted_time_liveness_max_age_seconds=120` old. A forward jump, backward jump,
rollback, stale attestation, local time-source loss or excessive disagreement
among that same domain's authenticated time sources blocks signing, lease
activation and renewal. A discrepancy with the other custody domain is
reconciliation evidence only and never blocks local expiry or cleanup. Expiry cleanup is
still allowed fail-safe from the last accepted attestation plus monotonic
elapsed time. After a process or host restart, suspend/resume/hibernate event,
VM clone or snapshot restore, a changed `boot_id`, restored registry snapshot,
missing suspend-inclusive monotonic continuity or unavailable trusted-time
attestation can never extend a lease: the domain immediately treats every
affected lease as expired, suspends local access, prohibits renewal and requires
a fresh independently authenticated attestation plus a new lease generation.
Rollback to an older registry version or time-attestation digest is rejected.
Neither domain consumes the other domain's clock as authority.

Deployment is reproducible from a digest-pinned artifact and attested SBOM.
Outbound traffic is deny-by-default except the frozen GitHub and control-plane
endpoints. GitHub-generated App keys are sign-only and non-exportable after
the selected `APP_PRIVATE_KEY_IMPORT` ceremony;
operators cannot download raw key bytes. Security logs and terminal manifests
are append-only and copied to the opposite independent audit domain without
granting control authority.

“Append-only” everywhere in this plan means provider-enforced WORM, not merely
a hash-linked mutable file. Every task, lease, authorization, cost, security,
replication and cleanup event plus each published chain head is a new immutable
object/version with sequence, previous digest, object/version ID,
`retain_until_utc`, writer identity and policy digest. No mutable pointer is the
sole source of truth. Each domain periodically anchors its accepted head in the
opposite domain and in a third independently operated trusted-timestamp/
transparency service; an accepted restore starts from a known independent
anchor and verifies every successor.

Before G7 and every full, maximal log/storage administrators in each domain
must fail to overwrite, delete, purge or shorten retention of an event, head or
anchor. A new internally coherent replacement chain without the previously
accepted external anchor is rejected. Anchor provider/account, timestamp token,
retention, cadence, maximum unanchored-event/time window, administrator and
negative-test receipts are frozen in the runbook.

Every WORM store also has a versioned encryption manifest. It declares either
provider-managed encryption with the provider/account/service identity and
documented survivability guarantees, or customer-managed encryption with exact
provider, account, region, key ID/version, algorithm, key administrators,
root-custodian failure domain, rotation policy and a key
`retain_until_utc >= latest protected object retain_until_utc`. A storage
administrator cannot administer that key, and a key administrator cannot
rewrite storage or its retention policy.

Before G7 and every full, each customer-managed-key domain proves by negative
test that maximal key/root administrators cannot disable the key, schedule or
perform deletion, shorten key retention, replace policy with a destructive
one, or retire an old version while retained ciphertext still depends on it.
Rotation tests restore retained objects through both old and new key versions.
Provider-managed encryption is acceptable only with an independently reviewed
receipt proving the retained object remains decryptable for its entire frozen
retention period; unknown revocation, account-closure or key-survivability
semantics are `NO-GO`.

G7 tests cold restore, provider-zone loss, broker outage, registry failover,
webhook replay/spoofing, stale heartbeat, total Actions outage and one complete
deadman-domain loss. Loss of fresh liveness, inability to restore or any
deployment/IAM/key/endpoint drift is fail-closed and immediate `NO-GO`.
`PREV7-0714`, `PREV7-0906`, `PREV7-0907`, `PREV7-0910` through
`PREV7-0912`, `PREV7-0914` and, when a billing dispute exists, `PREV7-0913`
consume each task's teardown manifest to remove only the relevant smoke or
campaign tenant while preserving required audit evidence and any shared
hardened service.

## 7. Canonical Sources Of Truth

### 7.1 Code

```text
GitHub repository origin/main = canonical code
```

No local worktree, Desktop file, download or chat attachment is canonical.

### 7.2 Large Scientific Assets

Default architecture:

```text
Primary:
GitHub Actions artifacts or private GitHub Release assets by immutable
repository, run/release and asset IDs plus reconstructed payload digest

Optional mirror:
second GitHub asset only when it fits the existing budget and the owner chooses
to create it; no different owner, account or provider is required

Index:
small hashed manifest committed to /provenance/ and bound to a verified
artifact attestation; add a separate signature only after the signing mechanism
is tested
```

Proposed primary private asset repository:

```text
trading-optimizer-lab-org/aurora-research-assets-primary
```

Proposed private mirror repository:

```text
trading-optimizer-lab-org/aurora-research-assets-mirror
```

Rules:

- Never publish vendor-derived raw or normalized data in the public code
  repository.
- The current V7 input is the owner-supplied frozen local data lake recorded in
  `docs/readiness/gtbi-v7/local_data_lake_receipt.json`; it does not require a
  provider download. Before scientific execution, the exact frozen bytes are
  transferred once to immutable GitHub storage and the worker receives only
  the scientific view ending on `2020-12-31`. `tiingo_daily` is optional and
  used only if the owner later requests a fresh snapshot.
- Canonical references use package digests, never mutable tags.
- Release parts are at most `1900 MiB`.
- Existing versions cannot be overwritten by the publishing workflow.
- If an optional mirror exists, it must reconstruct to the same SHA-256.
- No non-GitHub archive, independent owner, separate payer or external
  custodian is required.
- Restoration is tested from a clean GitHub runner.
- The manifest remains valid even if a human-readable tag moves.
- Absolute undeletability cannot be guaranteed while one administrator owns
  every GitHub resource. The plan provides content addressing, two copies,
  auditability and restore testing.

### 7.3 Private Asset Authentication

A public GitHub workflow cannot assume that its default `GITHUB_TOKEN` can
read a separate private repository or private package.

Required read design:

Every `credential_type=...installation token` below describes the credential
held internally by its external fixed-operation broker, never a credential
delivered to Actions. Repository/permission scope is the provider-enforced
ceiling; manifest, endpoint, object and byte restrictions are enforced because
the broker performs the call itself.

```text
credential_type=dedicated read-only GitHub App installation token
app_scope=private asset Release repositories only
contents_permission=read
packages_permission=none
metadata_permission=read
token_lifetime=provider_expiry, never assumed to equal job lifetime
token_safety_margin_minutes>=10
pat_allowed=false
```

Primary and mirror publishing each use their own physically separate GitHub
App, private key, installation and environment. Neither App is installed on
the other repository:

```text
credential_type=dedicated publish-only GitHub App installation token
contents_permission=write
packages_permission=none
metadata_permission=read
```

The disposable execution-repository checkout uses only that job's read-only
`GITHUB_TOKEN`; the asset-read App is installed only on the private asset
repositories, not on Aurora or the execution repository, and an API test proves
it cannot read either code repository. The read App is never granted write
permission and cannot mint a write-capable token. Both repository-specific
publish Apps are unavailable to read, compute, recovery and merge jobs.

A separate source checkpoint **handoff writer** uses a protected OIDC exchange
with a source-owned external content-addressed object store. It receives one
manifest/digest/size-bound write-once capability and cannot read or write
Aurora code, move Git tags, publish final results, overwrite an object, list
unrelated keys or access primary canonical asset repositories.

```text
credential_type=OIDC-bound external object-store write capability
contents_permission=none
packages_permission=none
object_store_permission=put-if-absent for one exact content-addressed object
```

This OIDC identity writes only the external immutable handoff object. It is not
the GitHub checkpoint publisher. The later `gtbi-checkpoint-publish` deployment
uses a separate selected-repository App token to copy already sealed ciphertext
into the dedicated GitHub checkpoint namespace; it has no OIDC unwrap or handoff
write authority. Schemas name these identities
`checkpoint_handoff_writer_oidc` and `checkpoint_repository_publisher_app`;
the generic term `checkpoint writer` is forbidden in machine policy.

A separate external checkpoint-cleanup broker route is introduced only for
approved deletion batches after retention predicates pass. It accepts an exact
immutable object-version/digest manifest and cannot upload, overwrite, list or
delete any canonical object. Policy, storage audit and post-run reconciliation
reject and alert on every operation except deletion of those exact
manifest-listed checkpoint versions.

```text
credential_type=OIDC-bound external checkpoint cleanup broker
contents_permission=none
packages_permission=none
object_store_permission=delete exact manifest-listed checkpoint versions only
```

A third source result-transport App is installed only on the one disposable
campaign repository and only for the bounded validation/restore window. It can
read Actions metadata and artifacts, but no contents, packages, environments,
administration or workflow configuration:

```text
credential_type=dedicated result-transport read GitHub App installation token
actions_permission=read
contents_permission=none
packages_permission=none
metadata_permission=read
```

A fourth dispatch-only App is installed only on the one disposable campaign
repository. Its sole purpose is to create the reviewed `workflow_dispatch` run
for the immutable execution ref:

```text
credential_type=dedicated dispatch-only GitHub App installation token
actions_permission=write
contents_permission=none
packages_permission=none
administration_permission=none
metadata_permission=read
```

The canonical protected dispatch controller asks the external fixed-operation
broker to dispatch only after validating and atomically consuming the
destination-owned capsule. The broker internally mints the token, accepts only
the fixed endpoint/method/body containing `dispatch_capsule_digest`, captures
the returned run identity, revokes the token and suspends the installation.
The controller receives only that run identity and attested receipt. Recovery requires a separate
current recovery capsule and bounded activation lease. GitHub's `Actions:
write` permission is broader than dispatch and can technically operate on runs.
Therefore the host workflow has a fixed endpoint/method/body allowlist
containing only the one dispatch call, and reconciles the App audit log before
accepting the run. The short lease, immediate suspension and one-repository
installation bound the unavoidable residual capability. The App has no
contents, artifact-read, package or administration permission and no
installation on any other repository; the threat model records compromise of
the App key as an explicit residual risk rather than claiming the permission is
narrower than GitHub provides.

Rules:

- Store each long-lived private key in exactly one external non-exportable
  broker/HSM compartment, never as a GitHub repository or environment secret.
  Every managed App used by both an external deadman and an Actions reaper must
  have two distinct cleanup-capable keys in two broker failure domains; any
  separate operational key is a third object. The same private key is never
  copied between compartments. GitHub environments hold only audience-bound
  client identities or already reduced short-lived tokens. Both App keys retain
  the App's complete permission set; compartmentation improves custody and
  rotation but does not create endpoint-level least privilege.
- Keep the asset-read, dependency-extract, canonical-publish, checkpoint-write,
  cleanup, result-transport-read and dispatch-only installations, keys,
  environments and namespaces physically disjoint.
- Never expose credentials to forked pull requests.
- Never use `pull_request_target` to execute untrusted code.
- The external broker mints a short-lived installation token internally; no
  workflow, host step or container receives it. The broker executes only the
  fixed, manifest-bound GitHub API operation and streams the permitted bytes or
  immutable write body while returning an attested receipt.
- Record `token_expires_at` in protected operational state and never start a
  transfer or scientific unit whose bounded completion and checkpoint upload
  can cross the safety margin.
- Before that margin, stop assigning units, flush durable checkpoints, revoke
  the token when supported and end successfully as an incomplete technical
  slice; selective recovery continues in a newly authorized job.
- An App private key and every resulting JWT/installation token are visible
  only inside the external broker's fixed-operation proxy and are never
  returned to a workflow step. The trusted host downloader or uploader receives
  only the broker's scoped byte stream and receipt. The
  scientific container receives neither private key,
  installation token, OIDC token nor Git credential.
- Credential processes remain outside the no-network scientific container and
  its PID namespace. Even symbol-thread mode runs entirely inside that
  container. The scientific process and uploader never share a writable
  directory: closed batches are validated without credentials and copied with
  no-follow, regular-file-only semantics into a separate immutable upload
  directory before a checkpoint write capability is minted.
- Mask token-derived values and disable shell tracing around authentication.
- Set `persist-credentials: false` on checkout unless a reviewed step needs
  Git credentials.
- Record asset/object digest, not credentials, in manifests.
- Test read, publish, expiry and revoked-access behavior.
- Rotate the App private key after any suspected disclosure.
- Scope credentials to the download or publish step, remove token files and
  environment variables before scientific execution, and prove that the
  container cannot inspect host `/proc`, inherit credentials or reach the
  network.
- Never upload raw or normalized licensed data as a public Actions artifact.

The emergency primary and mirror Release repositories are two storage
representations under the same administrative domain. They protect against
artifact expiry and single-copy corruption, but not against organization-wide
administrator deletion. That residual risk is tolerated only for emergency
preservation. Before G8, the independent GitHub disaster copy, destination-
owned non-GitHub immutable archive, second owner, phishing-resistant 2FA,
recovery-code custody, total-primary-organization restore and GitHub-platform-
read-denied restore are mandatory. Scientific execution remains GitHub-only,
but durable preservation no longer has GitHub as a single platform failure
domain.

In the preferred topology, scientific compute runs in the dedicated public
disposable execution repository, not in canonical Aurora or a private storage
repository. It contains only the reviewed workflow/template and public Aurora
code at the approved SHA. Every real-campaign result bundle, checkpoint, merge
input and merge output is encrypted and authenticated before any Actions upload;
logs and job summaries contain only allowlisted non-sensitive operational
fields. Current standard GitHub-hosted Linux runners expose four CPUs and 16 GB
for public repositories but two CPUs and 8 GB for private repositories, so
private standard compute would invalidate the four-CPU assumptions. The sole
fallback is the licence-approved private disposable topology using a measured
four-CPU larger-runner pool. Preflight and the capacity smoke reverify these
provider facts instead of treating them as permanent.

Capacity rules:

- each GitHub Release asset remains below GitHub's strict `2 GiB` per-file
  limit, so this plan uses parts of at most `1900 MiB`;
- every published Release part and external checkpoint object has a digest in
  the manifest;
- restoration verifies the reconstructed payload digest, not only transport
  success.

An archive attestation proves which workflow copied and published the archive.
It does not retroactively prove how the original V6 result was computed.
Original-build provenance and archive-copy provenance remain separate fields.

### 7.4 Asset Identity

This section defines only the post-retrieval
`scientific_asset_manifest_v1` compatibility wrapper used to preserve an
existing V6 scientific asset and its custody copies. It is not
`data_manifest_v1`, `data_snapshot_identity_v1`, `scientific_manifest_v1`,
`engine_result_manifest_v1`, `scientific_output_manifest_v1` or
`output_manifest_v1`, and none of those objects inherits this field list.
The wrapper records what was known when the preserved object was retrieved;
it cannot make a later V7 result true retroactively.

Every stored `scientific_asset_manifest_v1` must include:

```text
schema_version
asset_type
product
campaign_id
source_run_id
source_commit_sha
reconstructed_payload_sha256
policy_hash
workflow_path
workflow_sha256
created_at_utc
retrieval_cutoff_utc
train_end
validation_start
validation_end
locked_start
historical_exclusion_start
historical_post_validation_contaminated
pristine_locked
new_forward_available
first_market_session_locked
first_market_session_locked_by_market_digest_or_null
forward_lock_calendar_manifest_digest_or_null
later_required_approval_utc_or_null
provider
provider_terms_review_id
reproducibility_classification
evaluation_identity
selection_split
scoring_profile
min_selection_trades_per_year
score_formula_manifest_digest
final_filter_registry_digest
reuse_recovered_v6_inputs
oracle_b_status
semantic_oracle_coverage_manifest_digest
semantic_oracle_effective_branch_coverage_pct
semantic_oracle_non_equivalent_mutants_survived
v6_historical_reproduction_confirmed
synthetic_engine_equivalence_confirmed
engine_equivalence_confirmed
optimized_vs_reference_equivalence_confirmed
missing_v6_dependency_layers
universe_definition_sha256
exact_universe_identity_digest
universe_temporal_model
universe_temporal_manifest_digest
universe_temporal_coverage_pct
universe_point_in_time_claim_allowed
observation_timestamp_state
price_data_vintage_utc
source_event_cutoff_utc
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
corporate_action_knowledge_coverage_pct
historical_adjustment_vintage_contaminated
adjustment_point_in_time_claim_allowed
adjustment_policy_sha256
calendar_policy_sha256
currency_policy_sha256
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
cross_market_temporal_contaminated
causal_cross_market_claim_allowed
reference_index_order_confirmed
no_lookahead_confirmed
historical_causal_claim_allowed
data_digest
data_manifest_digest
historical_execution_pack_digest
reference_engine_code_sha
reference_engine_tree_digest
reference_entrypoint_digest
reference_dependency_lock_digest
reference_runtime_digest
reference_engine_isolation_policy_digest
numerical_environment_digest
scientific_numerical_semantics_digest
approved_numerical_execution_profile_registry_digest
approved_hardware_profile_registry_digest
canonical_serialization_profile_digest
hash_domain_registry_digest
file_count
row_count
first_date
last_date
symbol_source_end_manifest_digest
artificial_truncation_manifest_digest
compressed_size_bytes
uncompressed_size_bytes
source_object_sha256
primary_release_repository_id
primary_release_id
primary_release_asset_count
primary_release_parts
mirror_release_repository_id
mirror_release_id
mirror_release_asset_count
mirror_release_parts
independent_github_disaster_repository_id
independent_github_disaster_release_id
independent_github_disaster_asset_count
independent_github_disaster_release_parts
platform_outage_archive_provider
platform_outage_archive_object_version
platform_outage_archive_manifest_digest
platform_outage_archive_server_side_encryption_mode
platform_outage_archive_kms_provider_account_key_version_or_null
platform_outage_archive_kms_administrator_identity_or_null
platform_outage_archive_kms_retain_until_utc_or_null
platform_outage_archive_kms_deletion_protection_receipt_digest_or_null
platform_outage_archive_kms_admin_negative_test_receipt_digest_or_null
platform_outage_archive_lock_mode
platform_outage_archive_object_lock_until_utc
platform_outage_archive_legal_hold_state
platform_outage_archive_retention_policy_digest
platform_outage_archive_admin_negative_test_receipt_digest
retention_funding_manifest_digest
recovery_objective_policy_digest
latest_restore_receipt_digest
attestation_reference
asset_manifest_digest
```

`asset_manifest_digest =
HASH[GTBI_SCIENTIFIC_ASSET_MANIFEST_V1](typed
scientific_asset_manifest_v1 payload)` under `self_field` storage, omitting
only `asset_manifest_digest` from the hash preimage. Every field whose fact is
not yet established at wrapper creation has an explicit schema state rather
than a fabricated value: boolean result claims are `false`, optional evidence
digests and future timestamps are null, counts unavailable from the retrieved
payload are null, and `missing_v6_dependency_layers` names every unresolved
layer. A later restore or V7 equivalence event appends a separately
self-authenticating receipt or result object and never rewrites this archived
wrapper. In particular, archival preservation alone cannot set
`v6_historical_reproduction_confirmed`,
`synthetic_engine_equivalence_confirmed`,
`engine_equivalence_confirmed` or
`optimized_vs_reference_equivalence_confirmed` to true.

`source_object_sha256` is the SHA-256 of the exact source object bytes before
multipart publication. `reconstructed_payload_sha256` is the SHA-256 of the
exact uncompressed reconstructed payload bytes. They may coincide only when
the source object is already that payload; neither field is an unspecified
generic `sha256`. `policy_hash`, `exact_universe_identity_digest` and
`observation_timestamp_state` are mandatory in the manifest, snapshot,
scientific context, runbook, summary and completion record, and their
propagation is checked end to end.

Each `primary_release_parts`, `mirror_release_parts` and
`independent_github_disaster_release_parts` entry has exact
`part_index`, repository ID, release ID, asset ID, immutable asset name,
`size_bytes` and SHA-256. Indices are contiguous from zero and each array count
equals its own declared asset count; reconstruction from each array must equal
the one `reconstructed_payload_sha256` declared for all three GitHub custody
repositories. Array type is defined by schema and `[]` is never part of a field
name. A known-answer fixture serializes one manifest, reconstructs all three
custodies and proves byte-identical canonical JSON and payload hashes.

In this compatibility schema `locked_start` is deprecated but retained by that
exact name and must equal `historical_exclusion_start=2021-01-01`; no
differently named compatibility alias is emitted.

### 7.5 Complete V6 Dependency Chain

The archive must distinguish:

| Layer | Required evidence |
|---|---|
| C code and workflow | Commit object, tree, workflow bytes, dependency files and archival bundle |
| D0 universe | Listing source, filters, temporal model, membership/listing/delisting effective dates, market-cap knowledge dates and survivorship classification |
| D1 raw prices | Provider bytes or immutable normalized source |
| D2 normalized panel | Schema, adjustments, currency and calendar |
| D3 derived V6 pack | Exact transformation code and output digest |
| S strategy pack | Every strategy definition and canonical hash |
| R final result | Leaderboard, yearly output, trades, rules and summary |

If any layer cannot be recovered, the archive must say `incomplete` and name
the exact missing layer. It must not claim full reproducibility.

## 8. Master Dependency Graph

```text
G0 Emergency preservation
  -> G1A V7 identity
  -> G3A Minimum GitHub and asset security
  -> G2 Provenance and durable assets
  -> G4 Repository and worktree baseline

G1B Owner acceptance and automated review

G4 + G1B
  -> G5 Scientific contract and oracles
  -> G6A GTBI integration and performance implementation

G6A + G3B
  -> G6B independently controlled deadman and recovery infrastructure

G6B + G3B
  -> G7 CI, equivalence, fault injection and canonical smoke
  -> G8 Full authorization package
  -> separate approved full-run runbook core and authorization envelope
  -> G9 Result preservation and legacy retirement
  -> G10 Approved cleanup and broad repository modernization
```

G1B and G3B do not block documentation, non-scientific infrastructure
scaffolding, schema implementation through G4, synthetic unit CI or explicitly
non-acceptance exploratory performance benchmarks. G1B does block final
scientific-contract approval and G5 completion. G3B does not block G5 or G6A;
it becomes mandatory before G6B, canonical/equivalence acceptance, real-data
execution and every downstream scientific claim. Under the owner directive,
the repository owner may accept `PREV7-0503`, `PREV7-0505` and `PREV7-0509`
after their automated checks pass. No separate reviewer or authenticated
third-party receipt is required. This preserves the acyclic path
`G1B -> G5 -> G6A -> G3B -> G6B -> G7`.

No dependent gate may be completed while one of its prerequisites is red.

The broad physical package-layout modernization is not on the critical path.
It starts only after the first validated performance campaign, except for the
small GTBI module extraction required by G6A.

Exact gate map:

| Gate | Gate prerequisites | Required tasks or condition |
|---|---|---|
| `G0` | None | `PREV7-0000`, `PREV7-0001`, `PREV7-0002`, `PREV7-0003`, `PREV7-0004`, `PREV7-0005`, `PREV7-0006`, `PREV7-0007`, `PREV7-0008`, `PREV7-0009`, `PREV7-0010`, `PREV7-0012`, plus conditional safety task `PREV7-0011` terminally satisfied by either its direct no-go receipt or the exact `G0_READY_EXCEPT_0011` alternative-completion transaction |
| `G1A` | `G0` | `PREV7-0101`, `PREV7-0102`, `PREV7-0103` |
| `G1B` | None | `PREV7-0201`, explicit owner acceptance and passing automated role/policy checks; no distinct reviewer or custodian is required |
| `G3A` | `G1A` | `PREV7-0202`, `PREV7-0204`, `PREV7-0205`, `PREV7-0206`, `PREV7-0210` |
| `G2` | `G3A` | `PREV7-0301` through `PREV7-0307`, plus `PREV7-0309` |
| `G4` | `G2` | `PREV7-0400` through `PREV7-0405`; cleanup tasks `0406` and `0407` remain post-campaign |
| `G5` | `G4`, `G1B` | `PREV7-0501` through `PREV7-0509` |
| `G6A` | `G5` | `PREV7-0601` through `PREV7-0609` |
| `G3B` | `G1B`, `G3A`, `G6A` | `PREV7-0203`, `PREV7-0207`, `PREV7-0208`, `PREV7-0209`, `PREV7-0308` |
| `G6B` | `G6A`, `G3B` | `PREV7-0610`, `PREV7-0611` |
| `G7` | `G6B`, `G3B` | `PREV7-0701` through `PREV7-0708`, plus `PREV7-0710` through `PREV7-0715`, and dynamic condition `current_G7_attempt_generation` has a successful authenticated terminal disposition, a closed dispatch registry, zero admitted nonterminal operations and the terminal cleanup child receipt for that same generation |
| `G8` | `G7`, `G3B` | `PREV7-0310`, `PREV7-0800` through `PREV7-0805` and `PREV7-0807` through `PREV7-0816` |
| `G9` | Exact final green `G8_ATTEMPT-n` plus its bound consumed dispatch-capsule receipt, not live/unexpired G8 authority | `PREV7-0806`, `PREV7-0901`, `PREV7-0902`, `PREV7-0904`, `PREV7-0905`, `PREV7-0906`, `PREV7-0907`, `PREV7-0903` and terminally satisfied `PREV7-0913` |
| `G9X` | `G6B` | Abandoned-clean safety track only: completed `PREV7-0714` plus condition `G7 green OR exact G7_ATTEMPT_DISPOSITION=failed_abandoned_clean receipt`, then `PREV7-0814`, `PREV7-0910`, `PREV7-0914`, `PREV7-0911`, `PREV7-0912` and terminally satisfied `PREV7-0913`; it never greens `G8`, `G9` or `G10` |
| `G10` | `G9` | `PREV7-0406`, `PREV7-0407`, `PREV7-1001`, `PREV7-1002`, `PREV7-1003` |

Ranges mean the listed task IDs, not every integer that happens to fall
between their suffixes. The structural validator expands the matrix and writes
the exact resolved task list into `gate_status.csv`.

Every task has exactly one primary `gate` in `task_status.csv`, derived from
the first applicable non-conditional row above. The explicit exceptions are:
`PREV7-0308 -> G3B`; `PREV7-0610` and `PREV7-0611 -> G6B`;
`PREV7-0910`, `PREV7-0914`, `PREV7-0911` and
`PREV7-0912 -> G9X`; `PREV7-0913 -> G9`. `PREV7-0814` retains primary gate
`G8`, while `G9X` consumes it as a shared prerequisite. A shared required task
does not acquire a second primary gate.

G8 is current authority only until its envelope/capsule expires or its bound
configuration changes. After the capsule is consumed, G9 does not require that
short-lived authority to remain live for the 30-day restore/retention window;
it requires the immutable consumed-G8 attempt, capsule-consumption and dispatch
receipts plus unchanged scientific identity. Continuations and recovery have
their own authority generations. Expiry therefore stops new privileged work
without making already authorized result preservation impossible.

The static gate contract lives in `gate_definitions.csv` with exactly:

```text
gate_id
prerequisite_gate_ids
required_task_ids
required_condition
branch_policy
gate_definition_digest
```

`required_task_ids` is the canonical resolved list promised by the map above,
not only a digest. `gate_status.csv` references that immutable definition and
has exactly:

```text
gate_id
gate_attempt_id
gate_version
status
prerequisite_gate_ids
gate_definition_digest
evaluated_required_task_ids
required_task_id_set_digest
required_condition_digest
selected_branch_id_or_null
inventory_snapshot_digest_or_null
evidence_bundle_digest
blocking_reason
evaluated_at_utc
evaluated_commit_sha
```

Every gate transition is also appended to
`docs/readiness/gtbi-v7/gate_events.jsonl`. A task transition that consumes or
changes a gate is accepted only when the task event and gate event name the
same state-controller transaction ID, evaluated commit and previous gate
head. The state-controller either publishes both events or neither.

`gate_events.jsonl` has exactly:

```text
schema_version
event_id
transaction_id
gate_id
gate_attempt_id
previous_status_or_null
new_status
expected_gate_version
previous_gate_event_digest_or_null
required_task_id_set_digest
required_condition_digest
selected_branch_id_or_null
inventory_snapshot_digest_or_null
evidence_bundle_digest
actor_id
actor_role
transitioned_at_utc
evaluated_commit_sha
event_digest
```

`evidence_bundle_digest` is never an unexplained placeholder. It is
`HASH[GTBI_GATE_EVIDENCE_BUNDLE_V1]` over canonical JSON:

```text
schema_version
gate_id
gate_attempt_id
evidence_items[]
```

Each item contains evidence class, immutable locator, content digest, producer
task/attempt and freshness/expiry. Items are sorted by
`(evidence_class, content_digest, immutable_locator)`. The sequence-zero red
genesis uses the known-answer empty payload `evidence_items=[]`; its published
digest is non-null and fixtures freeze its exact bytes/digest. Every later
transition recomputes the complete evidence set. Removing, reordering or
substituting one item changes the digest.

Allowed gate states are `red`, `green` and `not_applicable`. Only a
machine-selected conditional safety track such as `G9X` may be
`not_applicable`; a scientific/governance gate cannot use that state. Gate
events are append-only and a fresh preflight may turn a previously green gate
red when inventory, terms, evidence freshness or dependencies drift. That does
not reopen completed tasks; it blocks new dependants and creates remediation
attempts where needed.

## 9. Task Record Standard

Every task must be tracked with:

```text
id
current_attempt_id
next_attempt_sequence
task_version
title
gate
priority
owner_role
owner_actor_id
status
dependencies
exact_inputs
entry_conditions
blocking_reason
github_issue
pull_request
exact_outputs
acceptance_criteria
evidence_paths
evidence_sha256
evidence_classification
private_evidence_id
redaction_review
acceptance_workflow
acceptance_run_id
rollback
approved_by
approved_at
required_approver_roles
approval_receipt_set_digest
alternative_completion_receipt_set_digest
activation_condition
alternative_completion
cancel_condition
superseded_by
rollback_trigger
started_at
completed_at
notes
repository_id
base_ref
base_sha
working_branch
head_sha
merge_sha
files_touched
acceptance_command
expected_result
merge_dependency
estimated_work_hours
estimated_elapsed_hours
external_lead_time_hours
planning_state
planning_blocker_code_or_null
planned_start_utc
due_at_utc
latest_start_utc
schedule_owner_actor_id
required_participant_role_ids
required_participant_actor_ids
participant_availability_manifest_digest
participant_max_concurrent_tasks_by_actor
review_lead_time_hours
provider_or_hiring_lead_time_hours
budget_currency
estimated_cost_entries_by_domain
```

Allowed status values:

```text
blocked
ready
in_progress
review
done
cancelled
```

Priority meanings:

```text
P0 = preservation, scientific integrity, security or authorization blocker
P1 = required delivery or operational-readiness work
P2 = post-campaign cleanup or broad modernization
```

Rules:

- a task cannot become `ready` until every dependency is done or green;
- a task cannot become `ready` until `owner_actor_id`, `exact_inputs`,
  `entry_conditions`, `exact_outputs`, `acceptance_criteria`,
  `cancel_condition`, `rollback` and `rollback_trigger` are concrete and
  machine-verifiable for that attempt; a matrix summary is not a substitute
  for its live operational row;
- a task cannot become `ready` unless `planning_state=complete` and its
  `planning_blocker_code_or_null` is null;
- a task cannot become `ready` when its schedule owner, required participants,
  actor availability, concurrency ceiling, latest start, due time,
  effort/review/provider lead-time estimate, currency or per-domain cost
  estimate is absent or stale; a missed `latest_start_utc` creates a blocking
  event and invokes the
  applicable no-go/abandonment controller rather than silently compressing the
  work;
- a dependency cancelled on an unselected conditional branch counts as
  terminally satisfied only when its immutable `alternative_completion` and
  `superseded_by` receipt verify; an ordinary cancellation never satisfies a
  dependency;
- a task cannot become `done` without exact output and evidence digests;
- `cancelled` requires a reason and an approved replacement or proof that it is
  no longer required;
- approval records include the actor, UTC timestamp, reviewed commit and
  evidence-bundle digest;
- `required_approver_roles` plus `approval_receipt_set_digest` are the
  authoritative approval record. `approved_by` is a compatibility/display
  projection only: it contains the sole accountable approver for a
  single-approver task and is null for multi-approver tasks;
- where independence is required, author and approver cannot be the same
  account;
- unconditional tasks set `activation_condition=always`. A conditional task
  records a machine-evaluable predicate, and a non-selected branch reaches
  `cancelled` only with the immutable `alternative_completion` receipt and
  `superseded_by` task or terminal state that satisfied the obligation;
- status history and attempt history are append-only in Git, even though
  `task_status.csv` stores only the current obligation row and its
  `current_attempt_id`;
- secrets, credential material and reusable authenticated URLs are never
  accepted as evidence.

Legal task-state transitions are machine-enforced:

```text
blocked -> ready | cancelled
ready -> in_progress | blocked | cancelled
in_progress -> review | blocked | cancelled
review -> done | in_progress | blocked | cancelled
done -> no outgoing transition
cancelled -> no outgoing transition
```

`done` and `cancelled` never reopen. `task_status.csv` models the matrix
obligation, not each execution attempt. Before a nonterminal obligation starts
or retries, CI appends exactly one `attempt_created` record to
`task_attempts.jsonl`, assigns its immutable `task_attempt_id` to
`current_attempt_id`, and atomically increments `next_attempt_sequence`.
An attempt has its own inputs, status, timestamps, terminal reason and evidence.
A failed attempt returns only the still-nonterminal obligation to `blocked`;
the next attempt receives a new ID and cannot reuse the prior attempt's
authorization, secrets or evidence. A terminal obligation is never retried; a
plan migration creates a new versioned task event rather than mutating terminal
history.

`task_attempts.jsonl` records exactly:

```text
schema_version
task_id
task_attempt_id
attempt_sequence
actor_id
actor_role
previous_attempt_status_or_null
attempt_status
expected_attempt_version
created_at_utc
started_at_utc_or_null
ended_at_utc_or_null
input_digest
authorization_receipt_set_digest_or_null
evidence_digest_or_null
terminal_reason_or_null
transition_receipt_digest
transitioned_at_utc
evaluated_commit_sha
event_id
previous_attempt_event_digest_or_null
event_digest
```

Allowed `attempt_status` values are `created`, `in_progress`, `review`,
`succeeded`, `failed` and `cancelled`. Legal transitions are
`created -> in_progress|cancelled`, `in_progress -> review|failed|cancelled`,
`review -> succeeded|in_progress|failed|cancelled`, with no outgoing transition
from a terminal state. Cancellation from review requires a terminal reason,
invalidates every pending approval and is covered by obligation/attempt
reconciliation tests. The attempt log is a protected
append-only hash chain. CI requires one current attempt for `in_progress` or
`review`, a successful current attempt before `done`, and no attempt ID or
sequence reuse.

`task_events.jsonl` has the following exact ordered schema:

```text
schema_version
event_id
transaction_id
task_id
task_attempt_id_or_null
event_sequence
previous_status_or_null
new_status
actor_id
actor_role
transitioned_at_utc
evaluated_commit_sha
expected_task_version
dependency_snapshot_digest
gate_snapshot_digest
evidence_digest_or_null
alternative_completion_receipt_set_digest_or_null
previous_task_event_digest_or_null
event_digest
```

All ten canonical readiness records listed in section 10, including the
delivery manifest, have versioned JSON, JSONL or CSV schemas under
`config/gtbi/schemas/readiness/`. Schemas fix the exact field set, primitive
types, nullability, array ordering, UTC format and lower-case SHA-256 grammar;
the ordered field lists in this document define semantics, not JSON byte order.
Bytes are UTF-8 without BOM and LF terminated. Every JSON and JSONL object uses
the single RFC 8785 profile frozen in
`config/gtbi/contracts/canonical_serialization_v1.json`, including its required
member ordering; no schema-order serializer or implementation-default
`json.dumps` is accepted. CSV uses RFC 4180 quoting, header order from schema
and lexicographic row order by its declared primary key. Validators hash those
canonical bytes and Git blobs, never a platform-transformed worktree.
`.gitattributes` enforces LF for JSON, JSONL, CSV and Markdown.
The master plan itself is audited only after it is materialized as UTF-8
without BOM, LF-only and exactly one final LF. The audit receipt records its
byte length, SHA-256 and Git blob ID. Before PR 1 stages the plan,
`.gitattributes` already exists in that candidate tree and `git check-attr`
must report the frozen text/eol rules. CI reads
`git cat-file blob <proposed-sha>:docs/plans/gtbi-v7-master-plan.md`
and requires its SHA-256/length to equal the audited bytes; the same check is
repeated against the PR-1 merge SHA on `main`. A checkout conversion, BOM,
CRLF, missing final LF or changed blob invalidates the audit and blocks
genesis.

For `task_events.jsonl`, exact types are: `schema_version`, `event_id`,
`transaction_id`, `task_id`, `actor_id`, `actor_role`,
`new_status`, `transitioned_at_utc`, `evaluated_commit_sha`,
`dependency_snapshot_digest`, `gate_snapshot_digest`,
and `event_digest` are required strings;
`task_attempt_id_or_null`, `previous_status_or_null`,
`previous_task_event_digest_or_null`, `evidence_digest_or_null` and
`alternative_completion_receipt_set_digest_or_null` are string or null;
`event_sequence` and `expected_task_version` are unsigned 64-bit integers.
Digest strings are `sha256:<64 lowercase hex>`, commit SHAs are 40 lower-case
hex, timestamps are UTC RFC 3339 with `Z`, and IDs use their schema-declared
ASCII grammar. `task_attempts.jsonl` and `gate_events.jsonl` use the same
primitive rules; their sequence/version fields are unsigned integers and only
fields explicitly suffixed `_or_null` may be null.

`inventory_snapshot_digest_or_null` is null only in the sequence-zero red gate
events/projections created by `PREV7-0000`, before the authoritative inventory
exists. The first accepted `PREV7-0001` transaction appends a new event for
every gate with the exact inventory digest; every later evaluation requires a
non-null value. A genesis fixture proves that no invented digest is required
and rejects a null after that first inventory transaction.

For every task, gate and attempt chain, sequence zero requires both predecessor
status and predecessor digest to be null; every later sequence requires both
to be non-null and equal to the prior accepted event. Attempt timestamps and
receipts are state-dependent: `started_at_utc_or_null` is non-null from
`in_progress`; `ended_at_utc_or_null` and `terminal_reason_or_null` are
non-null only for terminal states; authorization/evidence digests are required
exactly when the state contract consumes them. Genesis and every legal
nonterminal/terminal state have explicit fixtures.

Every self-authenticating object uses a registered typed hash domain:

```text
GTBI_TASK_DEFINITION_V1
GTBI_GATE_DEFINITION_V1
GTBI_V6_PRESERVATION_MANIFEST_V1
GTBI_READINESS_TASK_EVENT_V1
GTBI_READINESS_GATE_EVENT_V1
GTBI_READINESS_ATTEMPT_EVENT_V1
GTBI_TRUSTED_TIME_ATTESTATION_EVENT_V1
GTBI_LEASE_TERMINAL_MANIFEST_V1
GTBI_PRIVATE_EVIDENCE_MANIFEST_EVENT_V1
GTBI_TASK_REMEDIATION_EVENT_V1
GTBI_OUTPUT_CONSUMER_REMEDIATION_EVENT_V1
GTBI_CHECKPOINT_BATCH_V1
GTBI_SCIENTIFIC_UNIT_RESULT_V1
GTBI_OPERATIONAL_ATTEMPT_V1
GTBI_SCIENTIFIC_ASSET_MANIFEST_V1
GTBI_DATA_SNAPSHOT_V1
GTBI_DATA_MANIFEST_V1
GTBI_EXACT_UNIVERSE_IDENTITY_V1
GTBI_INSTRUMENT_IDENTITY_SET_V1
GTBI_INPUT_PARTITION_MANIFEST_V1
GTBI_INPUT_PARTITION_MANIFEST_SET_V1
GTBI_CAMPAIGN_CONSUMPTION_EVENT_V1
GTBI_CAMPAIGN_STATE_EVENT_V1
GTBI_EXTERNAL_ATTEMPT_EVENT_V1
GTBI_CAMPAIGN_RUN_EVENT_V1
GTBI_CAMPAIGN_RUN_REGISTRY_SEAL_V1
GTBI_PUBLICATION_ATTESTATION_EVENT_V1
GTBI_RECOVERY_TASK_EVENT_V1
GTBI_AUTHORITY_GENERATION_EVENT_V1
GTBI_EXTERNAL_SECURITY_OPERATION_LEASE_EVENT_V1
GTBI_G7_ATTEMPT_EVENT_V1
GTBI_G7_ATTEMPT_DISPOSITION_EVENT_V1
GTBI_FULL_DISPOSITION_EVENT_V1
GTBI_EXTERNAL_SECURITY_OBSERVATION_V1
GTBI_RESOURCE_CLEANUP_EVENT_V1
GTBI_COST_RECONCILIATION_EVENT_V1
GTBI_GATE_EVIDENCE_BUNDLE_V1
GTBI_MASTER_PLAN_AUDIT_SCOPE_V1
GTBI_MASTER_PLAN_AUDIT_PAYLOAD_V1
GTBI_MASTER_PLAN_AUDIT_RECEIPT_V1
GTBI_MASTER_PLAN_QUALITY_RECEIPT_SET_V1
GTBI_SCIENTIFIC_SCHEMA_SET_V1
GTBI_OPERATIONAL_SCHEMA_SET_V1
GTBI_SCIENTIFIC_NUMERICAL_SEMANTICS_V1
GTBI_NUMERICAL_EXECUTION_PROFILE_V1
GTBI_RUNTIME_THREADPOOL_OBSERVATION_V1
GTBI_CANONICAL_TIMING_ATTRIBUTION_V1
GTBI_NUMERICAL_EXECUTION_PROFILE_REGISTRY_V1
GTBI_NUMERICAL_EXECUTION_PROFILE_MAP_V1
GTBI_OBSERVED_HARDWARE_PROFILE_V1
GTBI_APPROVED_HARDWARE_PROFILE_REGISTRY_V1
GTBI_OBSERVED_HARDWARE_PROFILE_MAP_V1
GTBI_EXECUTION_TREE_MANIFEST_V1
GTBI_EXECUTION_WORKFLOW_BUNDLE_V1
GTBI_PARALLEL_MODE_EQUIVALENCE_POLICY_V1
GTBI_NUMERICAL_EXECUTION_PROFILE_ASSIGNMENT_V1
GTBI_SCIENTIFIC_CONTRACT_V1
GTBI_SCIENTIFIC_MANIFEST_V1
GTBI_ENGINE_RESULT_V1
GTBI_CANONICAL_STRATEGY_PAYLOAD_V1
GTBI_STRATEGY_ID_SET_V1
GTBI_CANDIDATE_ID_SET_V1
GTBI_STRATEGY_CANDIDATE_BIJECTION_V1
GTBI_STRATEGY_PACK_MANIFEST_V1
GTBI_FEATURE_DEMAND_MANIFEST_V1
GTBI_SCIENTIFIC_SYMBOL_ELIGIBILITY_SET_V1
GTBI_PHYSICAL_DATA_LAYOUT_MANIFEST_V1
GTBI_COST_PROFILE_V1
GTBI_MATRIX_PARTITION_MANIFEST_V1
GTBI_CANDIDATE_SYMBOL_PAIR_SET_V1
GTBI_PHYSICAL_EVALUATION_TILE_MANIFEST_V1
GTBI_ORDERED_TRADE_FRAGMENT_MANIFEST_V1
GTBI_ANNUAL_METRIC_PARTIAL_STATE_MANIFEST_V1
GTBI_SCIENTIFIC_FRAGMENT_RESULT_V1
GTBI_SCIENTIFIC_FRAGMENT_BUNDLE_V1
GTBI_FRAGMENT_REDUCTION_MANIFEST_V1
GTBI_ECONOMIC_HASH_V1
GTBI_FEATURE_SET_HASH_V1
GTBI_SIGNAL_GROUP_HASH_V1
GTBI_EXIT_GROUP_HASH_V1
GTBI_SIMULATION_GROUP_HASH_V1
GTBI_UNIT_REUSE_KEY_SET_V1
GTBI_CANONICAL_MAP_V1
GTBI_JOB_ASSIGNMENT_MANIFEST_V1
GTBI_JOB_ASSIGNMENT_MANIFEST_SET_V1
GTBI_PLANNED_REDUCTION_TOPOLOGY_MANIFEST_V1
GTBI_JOB_RESULT_MANIFEST_V1
GTBI_JOB_LOGICAL_PAYLOAD_V1
GTBI_BLOCK_RESULT_MANIFEST_V1
GTBI_BLOCK_LOGICAL_PAYLOAD_V1
GTBI_SUPERBLOCK_RESULT_MANIFEST_V1
GTBI_SUPERBLOCK_LOGICAL_PAYLOAD_V1
GTBI_RESOLVED_BLOCK_OUTPUTS_V1
GTBI_RESOLVED_SUPERBLOCK_OUTPUTS_V1
GTBI_OUTPUT_MANIFEST_V1
GTBI_RUNBOOK_CORE_V1
GTBI_SCIENTIFIC_CONTEXT_KEY_V1
GTBI_COMPLETE_REUSE_KEY_V1
GTBI_AUTHORIZATION_ENVELOPE_V1
GTBI_DISPATCH_CAPSULE_V1
GTBI_CONTINUATION_AUTHORIZATION_ENVELOPE_V1
GTBI_CONTINUATION_OPERATION_CAPSULE_V1
GTBI_RECOVERY_AUTHORIZATION_ENVELOPE_V1
GTBI_RECOVERY_DISPATCH_CAPSULE_V1
gtbi_master_plan_v1
gtbi_execution_plan_v1
gtbi-selection-bias-method-v1
gtbi-v7-unit-id-v1
gtbi-v7-success-record-v1
gtbi-v7-durable-result-v1
gtbi-v7-scientific-output-v1
```

The registry also contains this exhaustive schema-to-domain binding. The
logical schema ID is stable even when its file is nested under a subsystem
directory. `digest_result_name` is the only accepted name by which consumers
refer to the computed value:

```text
logical_schema_id | hash_domain_id | digest_result_name
task_definition_v1 | GTBI_TASK_DEFINITION_V1 | task_definition_digest
gate_definition_v1 | GTBI_GATE_DEFINITION_V1 | gate_definition_digest
v6_preservation_manifest_v1 | GTBI_V6_PRESERVATION_MANIFEST_V1 | preservation_manifest_digest
readiness_task_event_v1 | GTBI_READINESS_TASK_EVENT_V1 | event_digest
readiness_gate_event_v1 | GTBI_READINESS_GATE_EVENT_V1 | event_digest
readiness_attempt_event_v1 | GTBI_READINESS_ATTEMPT_EVENT_V1 | event_digest
trusted_time_attestation_event_v1 | GTBI_TRUSTED_TIME_ATTESTATION_EVENT_V1 | event_digest
lease_terminal_manifest_v1 | GTBI_LEASE_TERMINAL_MANIFEST_V1 | terminal_manifest_digest
private_evidence_manifest_event_v1 | GTBI_PRIVATE_EVIDENCE_MANIFEST_EVENT_V1 | event_digest
task_remediation_event_v1 | GTBI_TASK_REMEDIATION_EVENT_V1 | event_digest
output_consumer_remediation_event_v1 | GTBI_OUTPUT_CONSUMER_REMEDIATION_EVENT_V1 | event_digest
checkpoint_batch_v1 | GTBI_CHECKPOINT_BATCH_V1 | content_digest
scientific_unit_result_v1 | GTBI_SCIENTIFIC_UNIT_RESULT_V1 | scientific_result_digest
operational_attempt_preimage_v1 | GTBI_OPERATIONAL_ATTEMPT_V1 | operational_attempt_digest
scientific_asset_manifest_v1 | GTBI_SCIENTIFIC_ASSET_MANIFEST_V1 | asset_manifest_digest
data_snapshot_identity_v1 | GTBI_DATA_SNAPSHOT_V1 | data_digest
data_manifest_v1 | GTBI_DATA_MANIFEST_V1 | data_manifest_digest
exact_universe_identity_v1 | GTBI_EXACT_UNIVERSE_IDENTITY_V1 | exact_universe_identity_digest
instrument_identity_set_v1 | GTBI_INSTRUMENT_IDENTITY_SET_V1 | instrument_set_digest
input_partition_manifest_v1 | GTBI_INPUT_PARTITION_MANIFEST_V1 | input_partition_manifest_digest
input_partition_manifest_set_v1 | GTBI_INPUT_PARTITION_MANIFEST_SET_V1 | input_partition_manifest_set_digest
campaign_consumption_event_v1 | GTBI_CAMPAIGN_CONSUMPTION_EVENT_V1 | event_digest
campaign_state_event_v1 | GTBI_CAMPAIGN_STATE_EVENT_V1 | event_digest
external_attempt_event_v1 | GTBI_EXTERNAL_ATTEMPT_EVENT_V1 | event_digest
campaign_run_event_v1 | GTBI_CAMPAIGN_RUN_EVENT_V1 | event_digest
campaign_run_registry_seal_v1 | GTBI_CAMPAIGN_RUN_REGISTRY_SEAL_V1 | campaign_run_registry_digest
publication_attestation_event_v1 | GTBI_PUBLICATION_ATTESTATION_EVENT_V1 | event_digest
recovery_task_event_v1 | GTBI_RECOVERY_TASK_EVENT_V1 | event_digest
authority_generation_event_v1 | GTBI_AUTHORITY_GENERATION_EVENT_V1 | generation_digest
external_security_operation_lease_event_v1 | GTBI_EXTERNAL_SECURITY_OPERATION_LEASE_EVENT_V1 | event_digest
g7_attempt_event_v1 | GTBI_G7_ATTEMPT_EVENT_V1 | event_digest
g7_attempt_disposition_event_v1 | GTBI_G7_ATTEMPT_DISPOSITION_EVENT_V1 | event_digest
full_disposition_event_v1 | GTBI_FULL_DISPOSITION_EVENT_V1 | event_digest
external_security_observation_v1 | GTBI_EXTERNAL_SECURITY_OBSERVATION_V1 | observation_digest
resource_cleanup_event_v1 | GTBI_RESOURCE_CLEANUP_EVENT_V1 | event_digest
cost_reconciliation_event_v1 | GTBI_COST_RECONCILIATION_EVENT_V1 | event_digest
gate_evidence_bundle_v1 | GTBI_GATE_EVIDENCE_BUNDLE_V1 | evidence_bundle_digest
master_plan_audit_scope_manifest_v1 | GTBI_MASTER_PLAN_AUDIT_SCOPE_V1 | scope_manifest_digest
master_plan_audit_payload_v1 | GTBI_MASTER_PLAN_AUDIT_PAYLOAD_V1 | audit_payload_digest
master_plan_audit_receipt_v1 | GTBI_MASTER_PLAN_AUDIT_RECEIPT_V1 | receipt_digest
master_plan_quality_receipt_set_v1 | GTBI_MASTER_PLAN_QUALITY_RECEIPT_SET_V1 | master_plan_quality_receipt_set_digest
scientific_schema_set_v1 | GTBI_SCIENTIFIC_SCHEMA_SET_V1 | scientific_schema_set_digest
operational_schema_set_v1 | GTBI_OPERATIONAL_SCHEMA_SET_V1 | operational_schema_set_digest
scientific_numerical_semantics_v1 | GTBI_SCIENTIFIC_NUMERICAL_SEMANTICS_V1 | scientific_numerical_semantics_digest
numerical_execution_profile_v1 | GTBI_NUMERICAL_EXECUTION_PROFILE_V1 | numerical_execution_profile_digest
runtime_threadpool_observation_v1 | GTBI_RUNTIME_THREADPOOL_OBSERVATION_V1 | runtime_threadpool_observation_digest
canonical_timing_attribution_v1 | GTBI_CANONICAL_TIMING_ATTRIBUTION_V1 | canonical_timing_attribution_digest
numerical_execution_profile_registry_v1 | GTBI_NUMERICAL_EXECUTION_PROFILE_REGISTRY_V1 | approved_numerical_execution_profile_registry_digest
numerical_execution_profile_map_v1 | GTBI_NUMERICAL_EXECUTION_PROFILE_MAP_V1 | numerical_execution_profile_map_digest
observed_hardware_profile_v1 | GTBI_OBSERVED_HARDWARE_PROFILE_V1 | observed_hardware_digest
approved_hardware_profile_registry_v1 | GTBI_APPROVED_HARDWARE_PROFILE_REGISTRY_V1 | approved_hardware_profile_registry_digest
observed_hardware_profile_map_v1 | GTBI_OBSERVED_HARDWARE_PROFILE_MAP_V1 | observed_hardware_profile_map_digest
execution_tree_manifest_v1 | GTBI_EXECUTION_TREE_MANIFEST_V1 | execution_tree_digest
execution_workflow_bundle_v1 | GTBI_EXECUTION_WORKFLOW_BUNDLE_V1 | execution_workflow_bundle_digest
parallel_mode_equivalence_policy_v1 | GTBI_PARALLEL_MODE_EQUIVALENCE_POLICY_V1 | parallel_mode_equivalence_policy_digest
numerical_execution_profile_assignment_v1 | GTBI_NUMERICAL_EXECUTION_PROFILE_ASSIGNMENT_V1 | numerical_execution_profile_assignment_digest
scientific_contract_v1 | GTBI_SCIENTIFIC_CONTRACT_V1 | contract_digest
scientific_manifest_v1 | GTBI_SCIENTIFIC_MANIFEST_V1 | scientific_manifest_digest
engine_result_manifest_v1 | GTBI_ENGINE_RESULT_V1 | engine_result_digest
canonical_strategy_payload_v1 | GTBI_CANONICAL_STRATEGY_PAYLOAD_V1 | canonical_strategy_payload_digest
strategy_id_set_v1 | GTBI_STRATEGY_ID_SET_V1 | strategy_id_set_digest
candidate_id_set_v1 | GTBI_CANDIDATE_ID_SET_V1 | candidate_id_set_digest
strategy_candidate_bijection_v1 | GTBI_STRATEGY_CANDIDATE_BIJECTION_V1 | strategy_candidate_bijection_digest
strategy_pack_manifest_v1 | GTBI_STRATEGY_PACK_MANIFEST_V1 | strategy_pack_digest
feature_demand_manifest_v1 | GTBI_FEATURE_DEMAND_MANIFEST_V1 | feature_demand_manifest_digest
scientific_symbol_eligibility_set_v1 | GTBI_SCIENTIFIC_SYMBOL_ELIGIBILITY_SET_V1 | complete_scientific_symbol_set_digest
physical_data_layout_manifest_v1 | GTBI_PHYSICAL_DATA_LAYOUT_MANIFEST_V1 | physical_data_layout_digest
cost_profile_v1 | GTBI_COST_PROFILE_V1 | cost_profile_digest
matrix_partition_manifest_v1 | GTBI_MATRIX_PARTITION_MANIFEST_V1 | matrix_partition_manifest_digest
candidate_symbol_pair_set_v1 | GTBI_CANDIDATE_SYMBOL_PAIR_SET_V1 | candidate_symbol_pair_set_digest
physical_evaluation_tile_manifest_v1 | GTBI_PHYSICAL_EVALUATION_TILE_MANIFEST_V1 | physical_evaluation_tile_manifest_digest
ordered_trade_fragment_manifest_v1 | GTBI_ORDERED_TRADE_FRAGMENT_MANIFEST_V1 | ordered_trade_fragment_manifest_digest
annual_metric_partial_state_manifest_v1 | GTBI_ANNUAL_METRIC_PARTIAL_STATE_MANIFEST_V1 | annual_metric_partial_state_manifest_digest
scientific_fragment_result_v1 | GTBI_SCIENTIFIC_FRAGMENT_RESULT_V1 | scientific_fragment_result_digest
scientific_fragment_bundle_v1 | GTBI_SCIENTIFIC_FRAGMENT_BUNDLE_V1 | scientific_fragment_bundle_digest
fragment_reduction_manifest_v1 | GTBI_FRAGMENT_REDUCTION_MANIFEST_V1 | fragment_reduction_manifest_digest
economic_hash_v1 | GTBI_ECONOMIC_HASH_V1 | economic_hash
feature_set_hash_v1 | GTBI_FEATURE_SET_HASH_V1 | feature_set_hash
signal_group_hash_v1 | GTBI_SIGNAL_GROUP_HASH_V1 | signal_group_hash
exit_group_hash_v1 | GTBI_EXIT_GROUP_HASH_V1 | exit_group_hash
simulation_group_hash_v1 | GTBI_SIMULATION_GROUP_HASH_V1 | simulation_group_hash
unit_reuse_key_set_v1 | GTBI_UNIT_REUSE_KEY_SET_V1 | unit_reuse_key_set_digest
canonical_map_v1 | GTBI_CANONICAL_MAP_V1 | canonical_map_digest
job_assignment_manifest_v1 | GTBI_JOB_ASSIGNMENT_MANIFEST_V1 | job_assignment_manifest_digest
job_assignment_manifest_set_v1 | GTBI_JOB_ASSIGNMENT_MANIFEST_SET_V1 | job_assignment_manifest_set_digest
planned_reduction_topology_manifest_v1 | GTBI_PLANNED_REDUCTION_TOPOLOGY_MANIFEST_V1 | planned_reduction_topology_manifest_digest
job_result_manifest_v1 | GTBI_JOB_RESULT_MANIFEST_V1 | manifest_digest
job_logical_payload_v1 | GTBI_JOB_LOGICAL_PAYLOAD_V1 | logical_payload_digest
block_result_manifest_v1 | GTBI_BLOCK_RESULT_MANIFEST_V1 | manifest_digest
block_logical_payload_v1 | GTBI_BLOCK_LOGICAL_PAYLOAD_V1 | logical_payload_digest
superblock_result_manifest_v1 | GTBI_SUPERBLOCK_RESULT_MANIFEST_V1 | manifest_digest
superblock_logical_payload_v1 | GTBI_SUPERBLOCK_LOGICAL_PAYLOAD_V1 | logical_payload_digest
resolved_block_outputs_v1 | GTBI_RESOLVED_BLOCK_OUTPUTS_V1 | resolved_outputs_digest
resolved_superblock_outputs_v1 | GTBI_RESOLVED_SUPERBLOCK_OUTPUTS_V1 | resolved_outputs_digest
output_manifest_v1 | GTBI_OUTPUT_MANIFEST_V1 | output_manifest_digest
runbook_core_v1 | GTBI_RUNBOOK_CORE_V1 | runbook_core_digest
scientific_context_key_v1 | GTBI_SCIENTIFIC_CONTEXT_KEY_V1 | scientific_context_key_digest
complete_reuse_key_v1 | GTBI_COMPLETE_REUSE_KEY_V1 | complete_reuse_key_digest
authorization_envelope_v1 | GTBI_AUTHORIZATION_ENVELOPE_V1 | authorization_envelope_digest
dispatch_capsule_v1 | GTBI_DISPATCH_CAPSULE_V1 | dispatch_capsule_digest
continuation_authorization_envelope_v1 | GTBI_CONTINUATION_AUTHORIZATION_ENVELOPE_V1 | authorization_envelope_digest
continuation_operation_capsule_v1 | GTBI_CONTINUATION_OPERATION_CAPSULE_V1 | capsule_digest
recovery_authorization_envelope_v1 | GTBI_RECOVERY_AUTHORIZATION_ENVELOPE_V1 | authorization_envelope_digest
recovery_dispatch_capsule_v1 | GTBI_RECOVERY_DISPATCH_CAPSULE_V1 | capsule_digest
master_plan_v1 | gtbi_master_plan_v1 | master_plan_digest
execution_plan_v1 | gtbi_execution_plan_v1 | execution_plan_digest
selection_bias_method_v1 | gtbi-selection-bias-method-v1 | method_digest
unit_identity_v1 | gtbi-v7-unit-id-v1 | unit_id
success_record_v1 | gtbi-v7-success-record-v1 | success_record_digest
durable_result_v1 | gtbi-v7-durable-result-v1 | durable_result_digest
scientific_output_manifest_v1 | gtbi-v7-scientific-output-v1 | scientific_output_digest
```

The two schema-set payloads each contain exactly
`schema_version,classification,ordered_schemas[]`, where every row is
`logical_schema_id,relative_path,schema_version,sha256` and ordering is unsigned
UTF-8 byte order by logical schema ID then relative path. The scientific set
admits only `classification=scientific`; the operational set admits
`operational|transport` and includes classification in each row. Their union is
exactly the schema catalog with no overlap or unclassified row.

This block is the exhaustive domain set for the current plan version.
Each versioned JSON Schema that contains a self/computed digest, predecessor
digest, event digest or CAS-head digest declares exactly one
`hash_domain_id`. CI derives the schema-domain inventory and requires exact
set equality with `hash_domain_registry_v1.json`: no missing domain, orphan
registry row, duplicate string, case-fold collision or generic fallback is
permitted. Adding a digest-bearing schema or chain requires an explicit new
domain and plan/schema/registry version change before any receipt is accepted.
CI also derives the three-column binding above from the schemas and requires
exact row equality, including the digest result name. Every schema additionally
declares `digest_storage=self_field|external_result`. For `self_field`, the
result-named field is present in the stored object and omitted from its typed
preimage. For `external_result`, that name is absent from the preimage schema,
all declared fields are hashed and the result is stored only in the explicitly
named containing record or receipt. CI rejects an absent/extra self field, an
external result inserted into its own preimage, or a storage mode inconsistent
with the normative field list. A schema cannot reuse a
domain assigned to another logical schema, even when both schemas call their
digest result `event_digest`; the only permitted repeated result names
are those shown above. A domain cannot be selected dynamically from untrusted
payload data.

Every other schema field whose name ends in `_digest`, `_hash`, `_sha256` or
is a typed digest alias declares one `x-gtbi-digest-reference`:

```text
registered_object[logical_schema_id, hash_domain_id, digest_result_name]
raw_bytes[media_type, encoding_or_binary, path_or_member_identity]
signed_external_attestation[issuer_identity_schema, signature_policy_digest]
provider_native[provider, algorithm, normalization]
chain_head[logical_schema_id, hash_domain_id, sequence_policy_digest]
compatibility_alias[primary_field]
```

`raw_bytes` always means lower-case SHA-256 over the exact bytes and records
byte length; it cannot cover a parsed object whose semantics depend on field
types or ordering. `provider_native` is operational transport evidence only and
can never identify science, data, code, policy or authorization. A compatibility
alias must equal its primary field byte for byte. CI resolves the complete
reference graph, rejects an untyped 64-hex string, dangling schema/domain,
algorithm ambiguity, circular alias, signed-attestation without verified
issuer/signature policy or chain head without predecessor semantics. This is
how referenced file/policy/component digests remain closed without pretending
that each reference field is another self-authenticating stored object.

Its digest is SHA-256 over `domain || 0x00 || canonical_payload`, where
`canonical_payload` contains the exact preimage schema field set. A
`self_field` object omits only its computed digest field; an
`external_result` object hashes every declared preimage field. A chained object
includes the predecessor digest or null. Serialization uses exclusively the
global RFC 8785 JCS profile. A field list in this document defines membership
and collection semantics, never JSON object-member byte order.
`terminal_manifest_digest`, each `event_digest` and checkpoint
`content_digest` therefore cannot hash itself. Known-answer, genesis,
reordering, predecessor-substitution and single-byte-tamper fixtures are
mandatory for every domain.

The runbook, initial authorization, continuation authorization, recovery
authorization and all three capsule classes have complete versioned schemas.
Their digest is the registered-domain hash over the entire schema-typed object
with only that object's own digest field omitted; optional fields are present
as explicit nulls and ordered collections retain schema order. No prose subset,
file byte hash, nested digest list or implementation-selected field set may
substitute. Known-answer vectors cover every field, nullability, reordering and
single-field mutation for all seven authorization domains.

For CSV projections, list/set columns (`dependencies`, `files_touched`,
`required_approver_roles`, gate prerequisites and task sets) are
canonical compact JSON arrays sorted by their declared semantic key; scalar
null is an empty CSV field and an empty list is `[]`. Booleans are lower-case
`true|false`; integer fields contain base-10 digits without sign unless their
schema explicitly permits negative values.
`approved_by` is a nullable scalar actor ID: one ID for a single accountable
approver and an empty CSV field for multi-approver tasks, whose authoritative
actors live only in the signed receipt set.
`estimated_cost_entries_by_domain` is a canonical compact JSON object with
lexicographically sorted domain keys. Each value has exactly
`currency`, `native_minor_units`, `rate_snapshot_digest`,
`tax_and_fee_policy_digest`, `consolidated_currency`,
`consolidated_minor_units`,
`consolidated_minor_units_per_native_minor_unit_numerator`,
`consolidated_minor_units_per_native_minor_unit_denominator`,
`conservative_spread_numerator`, `conservative_spread_denominator`,
`rounding_mode=ceil_per_domain` and `fx_snapshot_digest`; monetary integers are
unsigned and currencies are frozen ISO 4217 codes. The schema, not field-name
guessing, remains authoritative and fixtures cover every nullable and list
column.

`participant_max_concurrent_tasks_by_actor` is a canonical compact JSON object
whose keys are exactly the distinct actor IDs in
`required_participant_actor_ids` and whose unsigned integer values are that
actor's frozen simultaneous-task limit. Missing, extra, zero or duplicate
actor coverage blocks scheduling; a single scalar cannot stand in for several
participants.

Every FX snapshot represents conversion to `consolidated_currency` as one
reduced rational `consolidated_minor_units_per_native_minor_unit_numerator /
consolidated_minor_units_per_native_minor_unit_denominator`, plus separately
versioned tax/fee and conservative-spread rational multipliers. Apply tax/fee,
then spread, then FX using unbounded integers and round the final amount toward
positive infinity once per billing domain; sums occur only after per-domain
rounding. Direction, timestamp/source, scale and validity are explicit.
Known-answer vectors cover sub-minor fractions, inverse quotes, zero, large
values, taxes/spread and currencies with 0/2/3 minor digits.

The protected `task_definitions.csv` contains one complete immutable planning
definition per matrix task:

```text
task_id
task_definition_digest
title
gate
priority
owner_role
dependencies
required_approver_roles
approval_policy_digest
required_evidence_classification
exact_inputs
entry_conditions
exact_outputs
acceptance_criteria
activation_condition
alternative_completion
cancel_condition
rollback
rollback_trigger
repository_id
planned_files
acceptance_command
expected_result
merge_dependency
estimated_work_hours
estimated_elapsed_hours
external_lead_time_hours
planning_state
planning_blocker_code_or_null
planned_start_utc
due_at_utc
latest_start_utc
schedule_owner_role
required_participant_role_ids
required_participant_actor_ids
participant_availability_manifest_digest
participant_max_concurrent_tasks_by_actor
review_lead_time_hours
provider_or_hiring_lead_time_hours
budget_currency
estimated_cost_entries_by_domain
```

`task_definition_digest` and `gate_definition_digest` are `self_field`
digests. Their typed preimages contain every field in their respective rows
except the digest field itself. Consumers never substitute a raw CSV-row hash,
the complete CSV blob hash or `task_version` for either immutable definition
identity.

The four participant fields in `task_definitions.csv` are copied canonically
from the same task row in `task_planning_inputs.csv`. Publication fails unless
the role array, actor array, availability-manifest digest and per-actor
concurrency map are byte-for-byte equal after schema canonicalization.

The genesis source for schedule/cost fields is the reviewed
`task_planning_inputs.csv`, with exactly one row for every matrix task and:

```text
task_id
estimated_work_hours
estimated_elapsed_hours
external_lead_time_hours
planning_state
planning_blocker_code_or_null
earliest_start_utc
due_at_utc
schedule_owner_role
required_participant_role_ids
required_participant_actor_ids
participant_availability_manifest_digest
participant_max_concurrent_tasks_by_actor
review_lead_time_hours
provider_or_hiring_lead_time_hours
budget_currency
estimated_cost_entries_by_domain
estimate_basis_digest
approved_at_utc
```

`planning_state` is exactly
`complete|blocked_missing_actor|blocked_missing_price|`
`blocked_missing_external_input|blocked_no_feasible_schedule`.
`planning_blocker_code_or_null` is null only for `complete`; every blocked
state uses a registered machine-readable blocker code. In
`task_planning_inputs.csv`, `earliest_start_utc` and `due_at_utc`; in
`task_definitions.csv`, `planned_start_utc`, `due_at_utc` and
`latest_start_utc`; and in `task_status.csv`, the corresponding schedule
projection may be null only while `planning_state!=complete` and
`status=blocked`. A null is a typed unavailable value, never a zero-duration
or no-deadline claim. Tasks without an external deadline still receive a
reviewed internal due date before `planning_state` can become `complete`.
Participant actor arrays may be empty only for a blocked missing-actor row
whose required role array is non-empty; its availability manifest is a
canonical zero-capacity manifest, and its per-actor concurrency object is
`{}`. Cost entries may be empty only when a reviewed no-charge receipt proves
that the task can consume no billable domain; an unknown price is
`blocked_missing_price`, never zero cost.

`PREV7-0000` validates complete coverage and solves a resource-constrained
schedule: dependencies, actor availability windows, vacations/absence,
per-actor maximum concurrent tasks, review latency, provider/hiring lead time
and external expiries. It derives `planned_start_utc` and
`latest_start_utc` backwards from those constraints and blocks publication
when any latest safe start has already passed. A vacant required role has zero
capacity until a registered actor and availability receipt exist. Missing
estimates are not silently replaced with zero, and two tasks cannot consume
the same actor beyond that actor's frozen concurrency ceiling.

The matrix is a readable index; `task_definitions.csv` is the exact static
contract from which live rows are initialized. `PREV7-0000` computes the
critical path backwards from each external expiry, especially
`2026-08-10T18:16:37Z`, and fails closed if the latest safe start has already
passed.

Publication itself requires `planning_state=complete` for `PREV7-0000` and
every G0 task on the preservation/closure path, including both branches of
`EMERGENCY_ESCROW` and `G0_BOOTSTRAP_DISPOSITION`. Their actors, availability,
effort, elapsed time, provider lead time, due/latest-start times, native-
currency caps and teardown capacity are reviewed inside
`BOOTSTRAP_FOUNDATION_TXN-1` before the PR-1 candidate is generated. Later
tasks may enter the genesis records in a typed blocked planning state; they
cannot become ready, green a gate or enter an execution plan until a reviewed
successor planning-input row makes them complete. This permits an honest
blocked future plan without weakening the immediately expiring G0 schedule.

The protected `task_delivery_manifest.csv` maps every implementation task to:

```text
task_id
repository_id
base_ref
base_sha
working_branch
planned_files
acceptance_command
expected_result
acceptance_workflow
merge_dependency
rollback_command_or_manifest
```

`PREV7-0000` generates it from the matrix and live task rows. Readiness rejects
any implementation task that lacks a concrete delivery row or whose row
disagrees with `task_status.csv`.

Public task evidence and redacted summaries are stored under:

```text
docs/readiness/gtbi-v7/<task-id>/
```

Evidence is classified before publication:

```text
public
private
secret_prohibited
```

Rules:

- `public` evidence may be committed only after automated secret scanning,
  licence review and an independent redaction review;
- `private` evidence is stored in the approved private evidence package by
  immutable digest only after a credential-free, no-network plaintext scan for
  provider secrets, PEM/private-key material, tokens, signed/authenticated
  URLs, embedded credentials and project-specific secret patterns; the public
  task record contains only
  `private_evidence_id`, SHA-256, classification, schema version and a
  non-authenticated logical locator;
- plaintext private-evidence intake exists only inside an attested no-network
  `tmpfs` or locked-memory namespace with swap, core dumps, shell history,
  tracing, debug logging and crash uploads disabled. The intake controller
  registers every buffer and file descriptor before first write, zeroizes and
  unmounts them on success, failure, cancellation and host loss, and appends a
  signed `private_plaintext_destruction_receipt.json` after a clean namespace
  inspection. Ordinary runner disks, caches, workspace paths and artifact
  staging directories are forbidden. A missing destruction receipt is an open
  security incident and blocks evidence acceptance. On abrupt host loss the
  independent platform supervisor, not the vanished process, must attest VM/
  namespace destruction, ephemeral-volume revocation and absence of any
  durable attachment before issuing the terminal receipt;
- access logs, raw provider terms, raw security findings, licensed rows,
  detailed trade data and operational identifiers are private unless the
  repository owner and licence reviewer explicitly classify a redacted form
  as public;
- private evidence locators never contain installation tokens, signed URLs,
  query credentials, private repository clone URLs with embedded credentials
  or decryption material;
- `secret_prohibited` material includes App private keys, installation tokens,
  environment secrets and signing keys. It is neither committed nor archived
  as evidence; tests record only pass/fail, actor, time and the tested
  permission boundary;
- CI rejects a `done` task whose evidence lacks classification, hash or
  redaction status, rejects public or private evidence with any unresolved
  secret-detector match, and rejects public evidence matching licensed-data
  detectors. A detector match is resolved as a false positive only by an
  independent dismissal receipt bound to the exact evidence digest, detector
  rule, byte range/finding ID and non-secret rationale; changing any byte or
  finding invalidates that receipt;
- protected restore CI resolves every `private_evidence_id`, verifies its
  digest, repeats the secret scan before any parser or consumer sees it and
  proves it is available to the authorized environment without exposing its
  storage credential to scientific workers;
- the private package has its own canonical
  `private_evidence_manifest.json`, with one immutable row per object containing
  schema version, campaign ID, manifest sequence, evidence ID, schema,
  lifecycle state, classification, plaintext digest,
  ciphertext digest, size, `source_object_version`,
  `destination_object_version_or_null`, `source_recipient_key_id`,
  `destination_recipient_key_id_or_null`, source wrapped-key-envelope digest,
  destination wrapped-key-envelope digest or null, creation time, retention
  deadline, legal-hold state, predecessor digest and `event_digest`;
  `event_digest` uses `GTBI_PRIVATE_EVIDENCE_MANIFEST_EVENT_V1` over the exact
  row with only itself omitted; sequence zero has a null predecessor and every
  successor names the immediately prior accepted row;
  manifest and objects are encrypted and copied to source and independently
  administered destination WORM stores before G8;
- the destination fields may be null only while evidence is
  `bootstrap_accepted`; migration to `production_accepted` appends a successor
  manifest row with destination object/key/envelope fields non-null and never
  rewrites the bootstrap row;
- source and destination recipient private keys are generated and retained in
  separate non-exportable brokers under disjoint owners/accounts/regions; no
  domain holds, exports or can invoke the other's private key. A
  source-denied restore uses only the destination envelope/key and a
  destination-denied restore uses only the source envelope/key, then compares
  the same plaintext digest. Loss of one key domain follows the
  `RECIPIENT_KEY_DOMAIN_LOSS` rewrap protocol; simultaneous loss fails closed;
- neither domain may destroy its recipient key while it is the last restorable
  key for any retained object. Key destruction requires unexpired opposite-
  domain restore proof for every affected manifest row, an independently
  restored replacement envelope/key when rotation applies, expiry/legal-hold
  checks and dual-approved destruction receipts anchored in both WORM chains;
- its RBAC grants read only to the named restore role, append only to the
  evidence-intake broker and retention/destruction only through a dual-approved
  manifest after the frozen retention period; repository owners, scientific
  workers and publishers have no direct private-evidence read or delete access;
- quarterly source-loss and destination-loss restore drills independently
  deny the other domain and verify every manifest row, object version,
  decryptability, recipient envelope/key and hash-chain head. Missing,
  unreadable, prematurely expired, silently replaced or single-domain-only
  private evidence blocks G8, G9 and every clean terminal state;
- G8 requires zero open secret-scanning alerts across repository history,
  Actions evidence and private-evidence intake. Every true finding has a
  revocation/rotation receipt and every false positive has an independently
  reviewed dismissal receipt; neither receipt preserves the secret value.

Emergency G0 preservation does not wait for a reviewer who does not yet exist.
Until G1B, detailed preservation evidence remains private. The public
repository may receive only a generated provisional receipt with an opaque
preservation digest and no provider or repository identifiers:

```text
task_id
private_evidence_id
archive_sha256
size_bytes
preserved_at_utc
primary_restore_passed
mirror_restore_passed
redaction_status=pending_independent_review
```

`source_run_id`, `source_artifact_id`, repository/account identifiers, object
versions and authenticated locators remain only in the private manifest. The
receipt passes automated licence and secret checks and repository-owner review,
but it is not final public evidence and never claims a redaction review already
occurred. G1B reviewers must independently review its source and either approve
or replace the redaction before G8.

## 10. Master Task Matrix

This table is the immutable planning and dependency index. It is not the live
task record. All mutable fields required by section 9 are maintained in:

```text
docs/readiness/gtbi-v7/task_status.csv
docs/readiness/gtbi-v7/gate_status.csv
docs/readiness/gtbi-v7/gate_definitions.csv
docs/readiness/gtbi-v7/task_events.jsonl
docs/readiness/gtbi-v7/task_attempts.jsonl
docs/readiness/gtbi-v7/gate_events.jsonl
docs/readiness/gtbi-v7/conditional_branch_registry.csv
docs/readiness/gtbi-v7/task_definitions.csv
docs/readiness/gtbi-v7/task_planning_inputs.csv
docs/readiness/gtbi-v7/task_delivery_manifest.csv
```

After `PREV7-0000`, changing an ID, dependency, gate requirement, scientific
rule or authorization rule requires a reviewed plan-version pull request,
explicit migration of all affected task-status, gate-status, task-event,
task-attempt and conditional-branch records and invalidation of evidence
whose assumptions changed. Editing prose cannot silently redefine a completed
task.

`task_definitions.csv` and `task_status.csv` each have one row per matrix ID.
The definition row uses its exact static schema above; the live row uses the
exact task-record columns from section 9 and supplies its current actor,
attempt, schedule, evidence and status. CI fails when an ID is missing,
duplicated, references an unknown dependency
or claims `done` without acceptance evidence. A dependency may be a task ID or
one of the gate IDs defined in section 8. `gate_status.csv` maps every gate to
its required task IDs and evidence, and CI rejects unknown, cyclic or
prematurely green gates.

`task_events.jsonl` records every obligation-status transition with task ID,
current immutable attempt ID or null, previous and new status, actor, UTC
timestamp, commit SHA and
evidence digest. CI reconciles
its latest event with `task_status.csv`. Each event also has a monotonic
per-task sequence, globally unique event ID and previous-event digest. CI
compares the proposed file with protected `main`, requires the previous byte
stream as an exact prefix and rejects deletion, reordering, mutation, duplicate
IDs or a broken hash chain.

`task_attempts.jsonl` records every attempt creation and attempt-state
transition under the exact schema in section 9. CI independently verifies its
prefix, hash chain, monotonic per-task attempt sequence and reconciliation with
`task_status.csv`; an attempt event cannot stand in for an obligation-status
event or vice versa.

`conditional_branch_registry.csv` contains exactly the schema and mandatory
rows in the branch registry below. CI requires one selected branch or one
verified not-yet-decided blocked state, rejects a successor outside the matrix
and verifies every cancelled conditional task against its named alternative-
completion receipt.

| ID | P | Owner | Dependencies | Required output |
|---|---:|---|---|---|
| PREV7-0000 | P0 | Implementer | None | Master plan, canonical-serialization/hash-domain bootstrap objects, owner simplification directive, passing structural validation, complete initial task/gate/event/definition/planning records and minimal bootstrap-closure controller published from latest `origin/main` |
| PREV7-0001 | P0 | Implementer | PREV7-0000 | Regenerated emergency GitHub inventory plus non-blocking local-state receipt `inventoried\|unavailable` |
| PREV7-0002 | P0 | Repository owner | PREV7-0001 | Approved cancellation manifest plus API receipts and terminal states for legacy runs |
| PREV7-0009 | P0 | Repository owner | PREV7-0001 | GitHub-native owner-controlled access foundation, provider/account/region/cost cap and tested bootstrap/import/rotation/recovery/teardown paths |
| PREV7-0006 | P0 | Repository owner | PREV7-0001, PREV7-0009 | Emergency private asset storage and evidence-classification policy |
| PREV7-0007 | P0 | Source App manager | PREV7-0006, PREV7-0009, PREV7-0010 | Short-lived private asset authentication approved jointly by repository owner and source key-broker custodian |
| PREV7-0010 | P0 | Source App manager | PREV7-0006, PREV7-0009 | Monofunction readiness-state-controller App, protected CAS/WORM event publisher, recovery/rollback proof and bootstrap-event reconciliation |
| PREV7-0011 | P0 | Repository owner | PREV7-0000 | Conditional bootstrap no-go closer for partial G0 resources, evidence and costs; cancelled on normal progress only in the atomic `G0_READY_EXCEPT_0011 -> G0_GREEN` transaction |
| PREV7-0012 | P0 | Repository owner | PREV7-0000 | Verified GitHub V6 preservation lease and expiry monitor; no external escrow or separate custodian is required |
| PREV7-0008 | P0 | Implementer | PREV7-0001, PREV7-0006, PREV7-0007 | Registered fail-closed V6 final, locked-evidence and recovered-byte preservation/restore workflows |
| PREV7-0003 | P0 | Implementer | PREV7-0001, PREV7-0006, PREV7-0007, PREV7-0008 | Durable V6 final-result archive, requiring the live PREV7-0012 escrow-guard receipt and promoting the emergency escrow bytes when that branch was selected |
| PREV7-0004 | P0 | Implementer | PREV7-0001, PREV7-0006, PREV7-0007, PREV7-0008 | Locked evidence archive |
| PREV7-0005 | P0 | Implementer | PREV7-0001, PREV7-0006, PREV7-0007, PREV7-0008 | V6 dependency-chain recovery report and preservation of recovered bytes |
| PREV7-0101 | P0 | Repository owner | PREV7-0000 | Unified V7 target recorded only after bootstrap genesis exists |
| PREV7-0102 | P0 | Implementer | PREV7-0101 | V7 identity and exclusions ADR |
| PREV7-0103 | P1 | Repository owner | PREV7-0102 | Scope and non-goals approval |
| PREV7-0201 | P0 | Repository owner | PREV7-0001, PREV7-0009 | Owner-controlled responsibility registry mapping legacy capability labels to the owner or automation; no vacancies, incompatibility separation or additional people required |
| PREV7-0202 | P1 | Repository owner | PREV7-0001 | Stage-one main protection; stage two pending reviewer |
| PREV7-0203 | P1 | Repository owner | PREV7-0201 | CODEOWNERS with the repository owner |
| PREV7-0204 | P1 | Source App manager | PREV7-0007, PREV7-0201 | Production source-App definitions, keys, negative-permission evidence and exact installation-request manifests, plus only the keyless proposed definition/repository-class request for destination-owned `gtbi-dependency-extract`; no destination key creation, repository creation or installation authorization |
| PREV7-0210 | P1 | Repository owner | PREV7-0204 | Exact source App installations and complete GitHub environment set authorized by the owner; destination-owned `gtbi-dependency-extract` remains an uninstalled keyless request until PREV7-0308, disposable repositories remain owner-created through the isolated-org ceremony and locked access stays disabled |
| PREV7-0205 | P1 | Implementer | PREV7-0202 | Pinned Actions and minimum permissions |
| PREV7-0206 | P1 | Implementer | PREV7-0202 | Dependabot, CodeQL, secret scanning and push-protection baseline |
| PREV7-0207 | P0 | Repository owner | PREV7-0201, PREV7-0202, PREV7-0203 | Stage-two protection and owner-approved automated environment checks |
| PREV7-0208 | P0 | Repository owner | PREV7-0201 | Verified GitHub preservation lease and restore procedure |
| PREV7-0209 | P0 | Repository owner | PREV7-0201, PREV7-0202, PREV7-0205, PREV7-0604, PREV7-0608, PREV7-0609 | Automated final-architecture threat checks, local-run guard digest/negative tests and zero unresolved critical/high risks accepted by the owner |
| PREV7-0301 | P0 | Repository owner | PREV7-0006, PREV7-0101 | Production asset, funded-retention and exact RPO/RTO policy finalized with recurring review owner and expiry |
| PREV7-0302 | P0 | Repository owner | PREV7-0201, PREV7-0301 | Versioned provider/data terms inventory plus repository-owner acceptance |
| PREV7-0309 | P0 | Repository owner | PREV7-0001, PREV7-0302 | Versioned GitHub Actions acceptable-use and pricing envelope, selected `CAPACITY_TOPOLOGY`, current capacity/source receipt and control reserves |
| PREV7-0303 | P1 | Implementer | PREV7-0301 | Versioned transport-classified `scientific_asset_manifest_v1` schema, registered hash domain, lifecycle/nullability validator and immutable-wrapper fixtures |
| PREV7-0304 | P0 | Implementer | PREV7-0003, PREV7-0007, PREV7-0205, PREV7-0302, PREV7-0303 | Emergency V6 archive promoted to production policy |
| PREV7-0305 | P0 | Implementer | PREV7-0304 | Clean-runner restoration proof |
| PREV7-0306 | P0 | Implementer | PREV7-0005 | Reproducibility classification |
| PREV7-0307 | P1 | Implementer | PREV7-0301, PREV7-0302, PREV7-0303, PREV7-0305, PREV7-0306 | Authenticated V6 input identity, or hashed no-V7-baseline decision plus separately scoped future-reference proposal that leaves G5/full blocked |
| PREV7-0308 | P0 | Independent disaster-copy owner | G2, PREV7-0208, PREV7-0301, PREV7-0302, PREV7-0309 | Independently administered destination foundation, account-root/payer/key-custodian receipts, storage and lease registry; destination-owned `gtbi-dependency-extract` App, GitHub-generated private key securely imported into its destination broker, source-owner selected-repository installations and restore-ready control plane |
| PREV7-0310 | P0 | Independent disaster-copy owner | PREV7-0304, PREV7-0305, PREV7-0307, PREV7-0308, PREV7-0708, PREV7-0800, PREV7-0808, PREV7-0810, PREV7-0813 | Final pre-authorization dependency and exact execution-commit copy plus total-primary-loss restore proof |
| PREV7-0400 | P1 | Implementer | PREV7-0001, PREV7-0003 | Complete resumable GitHub artifact, release and package inventory |
| PREV7-0401 | P1 | Implementer | PREV7-0001, PREV7-0400 | Workflow and branch registry |
| PREV7-0402 | P1 | Implementer | PREV7-0001 | Worktree and dirty-change registry |
| PREV7-0403 | P1 | Repository owner | PREV7-0402 | Preservation decision for every dirty worktree |
| PREV7-0404 | P1 | Implementer | PREV7-0403 | Fresh primary editing clone |
| PREV7-0405 | P1 | Implementer | PREV7-0404 | One active worktree per active branch |
| PREV7-0406 | P2 | Repository owner | PREV7-0405, PREV7-0903 | Post-campaign quarantine plan and durable restore proof for redundant copies |
| PREV7-0407 | P2 | Repository owner | PREV7-0406 | Approved deletion after grace period |
| PREV7-0502 | P1 | Implementer | PREV7-0001, PREV7-0202, PREV7-0401 | PR 20 resolved or replaced on `main`, with exact disposition receipt |
| PREV7-0501 | P0 | Implementer | PREV7-0001, PREV7-0103, PREV7-0202, PREV7-0401, PREV7-0404, PREV7-0405, PREV7-0502 | New branch from freshly fetched `origin/main` containing or postdating the exact PR-20 disposition |
| PREV7-0503 | P0 | Scientific reviewer | PREV7-0103, PREV7-0201, PREV7-0306 | Independently approved frozen scientific contract |
| PREV7-0504 | P0 | Implementer | PREV7-0204, PREV7-0503 | Immutable forward proposal, two required approval receipts and non-circular activation record when available, otherwise hashed and attested no-forward decision |
| PREV7-0505 | P0 | Implementer | PREV7-0503 | Synthetic semantic oracle plus authenticated scientific-reviewer acceptance receipt |
| PREV7-0506 | P0 | Implementer | PREV7-0306, PREV7-0307, PREV7-0503 | Historical golden baseline |
| PREV7-0507 | P1 | Implementer | PREV7-0503 | Versioned result schemas |
| PREV7-0508 | P1 | Implementer | PREV7-0401, PREV7-0507 | Output-consumer registry and migration tests against the frozen inventory digest and cutoff |
| PREV7-0509 | P0 | Workflow reviewer | PREV7-0508 | Permanent output-consumer remediation controller and immutable child-generation registry, accepted by the scientific reviewer; normally done with zero open children |
| PREV7-0601 | P1 | Implementer | PREV7-0501, PREV7-0503 | FeatureStore ADR accepted and GTBI modules extracted behind its single authoritative interface |
| PREV7-0602 | P1 | Implementer | PREV7-0601 | Thin CLI wrappers |
| PREV7-0603 | P1 | Implementer | PREV7-0205, PREV7-0504, PREV7-0507, PREV7-0602 | Canonical root-level workflows |
| PREV7-0604 | P0 | Implementer | PREV7-0504, PREV7-0602 | Central GitHub-only execution guard |
| PREV7-0605 | P1 | Implementer | PREV7-0505, PREV7-0506, PREV7-0507, PREV7-0601, PREV7-0609 | Deterministic one/two/four-worker execution, registered scientific-numerical semantics, approved execution-profile registry and byte-equivalence policy/report selected from the frozen representative baseline |
| PREV7-0606 | P1 | Implementer | PREV7-0505, PREV7-0506, PREV7-0507, PREV7-0601, PREV7-0609 | Equivalent event-first optimizations selected from the frozen representative baseline profile |
| PREV7-0607 | P1 | Implementer | PREV7-0603, PREV7-0605, PREV7-0606, PREV7-0609 | Benchmarked candidate-major/symbol-major/hybrid physical tiling, exact pair-set coverage, cost scheduling, execution plan/profile assignment and durable checkpoints |
| PREV7-0608 | P1 | Implementer | PREV7-0507, PREV7-0603, PREV7-0607 | Hierarchical deterministic fragment reduction/merge with exact global/tile/bundle pair-set closure, complete execution/hardware profile maps and canonical timing attribution, plus protected `gtbi-v7-package-close.yml`, its registration check and task-delivery-manifest mapping |
| PREV7-0609 | P1 | Implementer | PREV7-0601, PREV7-0603 | Baseline runtime/scientific instrumentation, source/workflow identity manifests, approved hardware-profile registry, runtime-threadpool observation and canonical-attribution schemas, representative cost/profile evidence and frozen optimization evidence; post-optimization telemetry equivalence is accepted later by PREV7-0703 |
| PREV7-0610 | P0 | Source deadman operator | G3B, PREV7-0204, PREV7-0207, PREV7-0209, PREV7-0309, PREV7-0603, PREV7-0607, PREV7-0609 | Reproducible source deadman, broker, authoritative attempt/lease registries, monitoring, exact root/payer/key-custodian/witness receipts, restore and teardown proof |
| PREV7-0611 | P0 | Destination deadman operator | G3B, PREV7-0207, PREV7-0209, PREV7-0308, PREV7-0309, PREV7-0603, PREV7-0607, PREV7-0609 | Independently administered destination deadman, broker, lease registry, monitoring, exact root/payer/key-custodian/witness receipts, restore and teardown proof |
| PREV7-0701 | P0 | Implementer | PREV7-0601, PREV7-0602, PREV7-0603, PREV7-0604, PREV7-0605, PREV7-0606, PREV7-0607, PREV7-0608, PREV7-0609 | Required credential-free synthetic CI suite |
| PREV7-0711 | P0 | Repository owner | G6B, PREV7-0309, PREV7-0701 | Disposable G7 validation repository created interactively by the owner in the isolated campaign organization from the approved template, then independently attested by immutable repository ID; first real G7 resource after full governance |
| PREV7-0710 | P0 | Repository owner | PREV7-0309, PREV7-0701, PREV7-0711 | Source-account and source external-control billing authorization and reservation for every real G7 smoke |
| PREV7-0712 | P0 | Independent disaster-copy owner | PREV7-0308, PREV7-0309, PREV7-0701, PREV7-0711 | Destination-account and destination external-control billing authorization and reservation for every real G7 smoke |
| PREV7-0713 | P0 | Licence and acceptable-use reviewer | PREV7-0710, PREV7-0712 | Consolidated G7 budget, FX and exact repository/workload receipt set with no missing or duplicate billing domain |
| PREV7-0715 | P0 | Repository owner | PREV7-0711, PREV7-0713 | Append-only `G7_ATTEMPT-n` controller with per-attempt authorization, budget, keys, leases, evidence and terminal cleanup generation |
| PREV7-0702 | P0 | Implementer | PREV7-0505, PREV7-0506, PREV7-0701, PREV7-0713, PREV7-0715 | Equivalence proof on the authorized G7 validation repository |
| PREV7-0703 | P1 | Implementer | PREV7-0702, PREV7-0713 | One, two and four worker benchmark |
| PREV7-0704 | P1 | Implementer | PREV7-0603, PREV7-0607, PREV7-0608, PREV7-0703, PREV7-0713, PREV7-0715 | Ordered recovery-then-merge-only proof with distinct immutable phase receipts |
| PREV7-0705 | P1 | Implementer | PREV7-0308, PREV7-0610, PREV7-0611, PREV7-0704, PREV7-0713 | Fault-injection proof plus exact G7 ephemeral-key handoff runtime receipt |
| PREV7-0706 | P0 | Implementer | PREV7-0702, PREV7-0703, PREV7-0704, PREV7-0705 | Canonical smoke |
| PREV7-0707 | P1 | Implementer | PREV7-0706, PREV7-0713 | 360-job capacity smoke |
| PREV7-0708 | P0 | Implementer | PREV7-0308, PREV7-0610, PREV7-0611, PREV7-0707 | Full-scale encrypted transport, segmented replication, reverse-recovery and hierarchical-merge smoke |
| PREV7-0714 | P0 | Repository owner | PREV7-0711, PREV7-0713, PREV7-0715 | Terminal current-generation G7 validation cleanup after the G7 attempt is terminal, its dispatch registry is closed and every admitted operation is terminal, or after matching source/destination-owner formal-abandonment receipts; all leases/credentials/tenants revoked and repository deny-all |
| PREV7-0800 | P0 | Workflow reviewer | G7, PREV7-0207, PREV7-0708, PREV7-0714, PREV7-0814 | V7 implementation merged by protected PR, then revalidated on the merged SHA through a fresh immutable G7 attempt with terminal cleanup receipt |
| PREV7-0814 | P0 | Repository owner | PREV7-0714 | Immutable full-disposition controller initialized as `pending`, with immutable decision deadline/escalation, nonterminal intent/deadline states `abandonment_pending_remote` and `security_abandoned_pending_remote`, dispatch boundary and completed/abandoned branches |
| PREV7-0815 | P0 | Licence and acceptable-use reviewer | PREV7-0309, PREV7-0708, PREV7-0714, PREV7-0800, PREV7-0814 | Multi-party capped pre-ID authorization for campaign repository/App/key provisioning only |
| PREV7-0808 | P0 | Repository owner | PREV7-0204, PREV7-0308, PREV7-0800, PREV7-0814, PREV7-0815 | Owner-completed disposable campaign repository, source-App installation and destination-installation ceremony receipts |
| PREV7-0810 | P0 | Implementer | PREV7-0808 | Exact reviewed execution bundle committed once in the campaign repository, with immutable commit/tree/mapping identity |
| PREV7-0811 | P0 | Repository owner | PREV7-0309, PREV7-0708, PREV7-0810 | Exact full source-account and source external-control monetary authorization and reservation |
| PREV7-0812 | P0 | Independent disaster-copy owner | PREV7-0308, PREV7-0309, PREV7-0708, PREV7-0810 | Exact full destination-account and destination external-control monetary authorization and reservation |
| PREV7-0813 | P0 | Licence and acceptable-use reviewer | PREV7-0811, PREV7-0812 | Consolidated exact full budget, FX and reservation receipt set with no missing or duplicate billing domain |
| PREV7-0801 | P0 | Implementer | PREV7-0310, PREV7-0808, PREV7-0810, PREV7-0813, G0, G1A, G1B, G2, G3A, G3B, G4, G5, G6A, G6B, G7 | Go/no-go evidence bundle bound to the current role-registry digest plus independent redaction-review receipt, including execution identity, monetary authorizations, owner installation and independent-restore receipts |
| PREV7-0805 | P0 | Implementer | PREV7-0308, PREV7-0309, PREV7-0610, PREV7-0611, PREV7-0801 | Immutable proposed full-run runbook core, exact source/destination key-broker custodian operation receipts and digest |
| PREV7-0802 | P0 | Scientific reviewer | PREV7-0801, PREV7-0805 | Scientific sign-off on exact runbook-core digest |
| PREV7-0803 | P0 | Workflow reviewer | PREV7-0801, PREV7-0805 | Operational sign-off on exact runbook-core digest |
| PREV7-0809 | P0 | Licence and acceptable-use reviewer | PREV7-0309, PREV7-0805 | Exact-workload acceptable-use approval receipt bound to the runbook-core digest |
| PREV7-0816 | P0 | Independent security reviewer | PREV7-0610, PREV7-0611, PREV7-0708, PREV7-0805 | Final security approval for the exact runbook-core digest, deployed IAM/Apps/keys/deadmen, destructive-path tests and accepted residual risks |
| PREV7-0804 | P0 | Repository owner | PREV7-0802, PREV7-0803, PREV7-0805, PREV7-0809, PREV7-0816 | Explicit authorization receipt and immutable authorization envelope for the exact runbook core and security approval |
| PREV7-0807 | P0 | Independent disaster-copy owner | PREV7-0310, PREV7-0804 | Final authorization/evidence sync to independent destination, restore proof and immutable dispatch capsule bound to the exact current G8 preauthorization attempt |
| PREV7-0806 | P0 | Implementer | G8, PREV7-0805, PREV7-0807 | Approved full campaign executed only after revalidating the current G8 attempt/condition/evidence and consuming the immutable dispatch capsule |
| PREV7-0901 | P1 | Implementer | PREV7-0806 | Final result verification |
| PREV7-0902 | P1 | Implementer | PREV7-0901 | Durable final result, recovery evidence and audit publication to primary and mirror |
| PREV7-0904 | P1 | Independent disaster-copy owner | PREV7-0902 | Destination-pulled final result, recovery/audit evidence, independent restore and source-access revocation |
| PREV7-0905 | P0 | Repository owner | PREV7-0904 | `full_disposition=completed` CAS plus immediate source/destination lease stop, App suspension, credential revocation and deny-all receipt |
| PREV7-0906 | P0 | Independent disaster-copy owner | PREV7-0905 | Destination campaign control-plane retirement after recovery predicates and immutable billing/dispute-evidence export; reconciliation or bounded `DISPUTED_CLEAN` recorded |
| PREV7-0907 | P0 | Repository owner | PREV7-0905 | Source campaign and G7 validation repositories, packages, checkpoints and external-control tenants independently physically retired after recovery predicates and immutable billing/dispute-evidence export |
| PREV7-0903 | P2 | Repository owner | PREV7-0905 | Legacy rollback observation and retirement, concurrent with the recovery-retention window |
| PREV7-0910 | P0 | Repository owner | PREV7-0814 | Conditional immediate abandoned-campaign security cleanup when `full_disposition=abandoned`, including one immutable inventory/no-action-or-revocation substitution receipt per cancelled pre-dispatch task |
| PREV7-0914 | P0 | Independent disaster-copy owner | PREV7-0910 | Conditional post-dispatch recovery-only dual-restore capsule and receipts, or pre-dispatch no-ciphertext alternative-completion receipt, including one immutable result/preservation substitution receipt per cancelled dispatch/result task |
| PREV7-0911 | P0 | Independent disaster-copy owner | PREV7-0910, PREV7-0914 | Conditional delayed destination physical cleanup, independent receipt and reconciliation-or-bounded-`DISPUTED_CLEAN` state for the abandoned branch |
| PREV7-0912 | P0 | Repository owner | PREV7-0910, PREV7-0914 | Conditional delayed source physical cleanup and independent receipt; joint reconciliation waits for both domains in PREV7-0913 |
| PREV7-0913 | P0 | Licence and acceptable-use reviewer | PREV7-0814, PREV7-0903, PREV7-0906, PREV7-0907, PREV7-0911, PREV7-0912 | Final selected-campaign-branch reconciler: verifies normal or abandoned substitution receipts; normal completion requires every billing domain reconciled or pre-authorized `NO_INVOICE_EXPECTED_CLEAN`, while a dispute emits nonterminal `CAMPAIGN_DISPUTED_CLEAN` and keeps the task active; only the abandoned branch may close through its approved bounded financial exception |
| PREV7-1001 | P2 | Implementer | PREV7-0407 | Repository layout ADR |
| PREV7-1002 | P2 | Implementer | PREV7-1001 | Staged non-GTBI package modernization |
| PREV7-1003 | P0 | Workflow reviewer | PREV7-0913, PREV7-1002 | Final successful-project reconciler, with actor distinct from implementer, last-change author and repository owner: verifies every other G10 obligation and a reconciled or pre-authorized-no-invoice normal campaign-clean receipt, then alone emits project-terminal `COMPLETED_CLEAN` |

Conditional activation is resolved in the live task records:

```text
PREV7-0714:
  activation_condition=
    (
      g7_attempt_terminal
      && g7_dispatch_registry_closed
      && every_admitted_G7_operation_terminal
    )
    || formal_G7_abandonment
  a completed PREV7-0713 alone is insufficient
  an empty started-operation set is insufficient
  closes only the current immutable G7_ATTEMPT-n generation

PREV7-0815, PREV7-0808, PREV7-0810, PREV7-0811, PREV7-0812, PREV7-0813,
PREV7-0310, PREV7-0801, PREV7-0805, PREV7-0802, PREV7-0803,
PREV7-0809, PREV7-0816, PREV7-0804, PREV7-0807, PREV7-0806, PREV7-0901,
PREV7-0902 and PREV7-0904:
  full_disposition=pending
  current_trusted_utc < disposition_decision_due_at_utc
  source_local_security_state=active
  destination_local_security_state=active

PREV7-0905:
  PREV7-0904 verified
  atomically transition full_disposition pending -> completed

PREV7-0906:
  full_disposition=completed
  recovery_window_and_dual_restore_predicates=true
  immutable_billing_or_dispute_evidence_exported=true

PREV7-0907:
  full_disposition=completed and PREV7-0905 shared security receipt verified
  source recovery and evidence-export predicates=true

PREV7-0903:
  full_disposition=completed

PREV7-0910:
  full_disposition=abandoned

PREV7-0914:
  full_disposition=abandoned
  dispatch_boundary_state=post_dispatch -> execute recovery-only dual restore
  dispatch_boundary_state=pre_dispatch -> execute bounded inventory and emit
    verified no-capsule/no-ciphertext/no-recovery-required receipt
  the selected abandoned sub-branch completes PREV7-0914; it never substitutes
    its own output for itself

PREV7-0911:
  full_disposition=abandoned and PREV7-0910/PREV7-0914 terminally satisfied
  destination recovery and evidence-export predicates=true

PREV7-0912:
  full_disposition=abandoned and PREV7-0910/PREV7-0914 terminally satisfied
  source recovery and evidence-export predicates=true
  completes resource retirement with resource_cleanup_state=
    RECONCILED_CLEAN or DISPUTED_CLEAN

PREV7-0913:
  activation_condition=selected FULL_DISPOSITION branch has reached its
    source and destination cleanup receipts
  normal branch: PREV7-0906 and PREV7-0907 are direct receipts;
    PREV7-0911 and PREV7-0912 require their named alternative-completion
    receipts
  abandoned branch: PREV7-0911 and PREV7-0912 are direct receipts;
    PREV7-0906 and PREV7-0907 require their named alternative-completion
    receipts
  normal completion_condition=every billing domain is RECONCILED_CLEAN or
    pre-authorized NO_INVOICE_EXPECTED_CLEAN
  normal disputed state=CAMPAIGN_DISPUTED_CLEAN, task remains active and
    G9/G10 remain red
  abandoned completion_condition=every billing domain is RECONCILED_CLEAN, or
    is DISPUTED_CLEAN with the branch-limited terminal financial exception,
    immutable exported dispute evidence, deadline, accountable owner and
    reserved maximum liability
  terminal_output=CAMPAIGN_COMPLETED_CLEAN only for reconciled or
    pre-authorized-no-invoice normal branch,
    or ABANDONED_CLEAN for terminal abandoned branch

PREV7-1003:
  activation_condition=PREV7-0913 emitted CAMPAIGN_COMPLETED_CLEAN and every
    other G10 task is done
  completion_condition=all G10 acceptance predicates and final inventory,
    migration, cleanup and rollback receipts verify against one commit
  terminal_output=COMPLETED_CLEAN
```

The ranges above mean only matrix IDs that exist. Every branch cancellation
records `alternative_completion_receipt_set_digest` against the frozen
conditional-branch mapping. The registry freezes task-by-task substitutions
before either branch can be selected:

```text
abandoned branch:
  PREV7-0815 -> PREV7-0910 pre-ID-authority-inert receipt
  PREV7-0808 -> PREV7-0910 repository/App/key inventory-and-revocation receipt
  PREV7-0810 -> PREV7-0910 execution-bundle-inert-or-quarantined receipt
  PREV7-0811 -> PREV7-0910 source-reservation-release receipt
  PREV7-0812 -> PREV7-0910 destination-reservation-release receipt
  PREV7-0813 -> PREV7-0910 consolidated-budget-authority-inert receipt
  PREV7-0310 -> PREV7-0910 destination-copy-not-authorizing-or-not-required receipt
  PREV7-0801 -> PREV7-0910 go-no-go-authority-inert receipt
  PREV7-0805 -> PREV7-0910 runbook-proposal-inert receipt
  PREV7-0802 -> PREV7-0910 scientific-signoff-non-authorizing receipt
  PREV7-0803 -> PREV7-0910 workflow-signoff-non-authorizing receipt
  PREV7-0809 -> PREV7-0910 acceptable-use-signoff-non-authorizing receipt
  PREV7-0816 -> PREV7-0910 security-signoff-non-authorizing receipt
  PREV7-0804 -> PREV7-0910 authorization-envelope-unconsumed-or-revoked receipt
  PREV7-0807 -> PREV7-0910 dispatch-capsule-unconsumed-or-revoked receipt
  PREV7-0806 -> PREV7-0914 no-dispatch/no-ciphertext or post-dispatch recovery receipt
  PREV7-0901 -> PREV7-0914 no-result-to-verify or recovered-result-verification receipt
  PREV7-0902 -> PREV7-0914 no-result-to-publish or recovered-preservation receipt
  PREV7-0904 -> PREV7-0914 no-destination-result or destination-restore receipt
  PREV7-0905 -> PREV7-0910 security-cleanup receipt
  PREV7-0906 -> PREV7-0911 destination-retirement receipt
  PREV7-0907 -> PREV7-0912 source-retirement receipt
  PREV7-0903 -> PREV7-0912 legacy-rollback-not-applicable receipt

completed branch:
  PREV7-0910 -> PREV7-0905 completed-disposition receipt
  PREV7-0914 -> PREV7-0904 dual-restore/no-recovery-needed receipt
  PREV7-0911 -> PREV7-0906 destination-retirement receipt
  PREV7-0912 -> PREV7-0907 source-retirement receipt
```

Every substitution above is a separate row keyed by
`(branch_id,cancelled_task_id)` in `conditional_branch_registry.csv`; its
receipt binds the cancelled task definition/event digest, selection predicate,
dispatch-boundary state, relevant inventory, successor task/event digest and
the exact no-action, revocation, recovery or cleanup fact. A task already
terminal before branch selection is retained as direct historical evidence and
is not cancelled or replaced. The `PREV7-0903` alternative receipt is emitted
and anchored by `PREV7-0912` before `PREV7-0913` can start. No task may use
`PREV7-0913`, `CAMPAIGN_COMPLETED_CLEAN` or `ABANDONED_CLEAN` as the evidence
that satisfies one of `PREV7-0913`'s own prerequisites. Authenticated
no-dispute receipts are separate inputs, not a circular terminal output. No
conditional task is required for a gate whose branch was not selected, but
every unselected dependency must be terminally satisfied by its exact mapped
receipt. `ABANDONED_CLEAN` is only the aggregate terminal disposition after all
such rows reconcile; it is never a task-level substitute.

The same rule applies to earlier alternatives. `task_status.csv` and the
versioned `conditional_branch_registry.csv` freeze each branch before its
predicate is evaluated:

```text
branch_id
task_id
predicate_schema_digest
predicate_evidence_digest
selected_successor
unselected_alternative_completion
invalidated_evidence_classes
affected_gates
decision_actor_id
decision_receipt_digest
```

Initial mandatory branches are:

| Branch | Machine-evaluable decision | Selected path | Alternative completion |
|---|---|---|---|
| `V6_FINAL_SOURCE` | Authenticated remote artifact ID/digest is still downloadable | GitHub-only preservation download | Owner-authorized byte-for-byte local source transfer with pre/post digest and provenance-limitation receipt |
| `EMERGENCY_ESCROW` | Live resource-constrained schedule still proves normal PREV7-0003 dual-copy restore before `2026-08-03T18:16:37Z` and before the measured last safe escrow start | Keep the nonterminal armed monitor active and continue normal preservation; never mark `not_required` | On lost/stale margin or last safe start, automatically run the already authorized PREV7-0012 external non-scientific fixed-artifact byte stream from artifact 8251391531 into its pre-provisioned immutable external escrow object, verify size/SHA-256 and later promote those exact bytes through PREV7-0003 |
| `V6_INPUT_IDENTITY` | Complete authenticated original V6 input chain exists | `reuse_recovered_v6_inputs=true` and this V7 may continue | `reuse_recovered_v6_inputs=false`; emit a separately named reference proposal, keep G5/G6A/G7/full red and require a separate product/campaign plan |
| `G0_BOOTSTRAP_DISPOSITION` | Every G0 predicate except conditional `PREV7-0011` is true, or an authenticated hard bootstrap failure exists | Atomically consume `G0_READY_EXCEPT_0011`, cancel `PREV7-0011` and green G0 | Run `PREV7-0011` through the minimal bootstrap-closure controller, consume its failure-close receipt in `NO_GO_CLOSE-n` and never green G0 |
| `PR20_DISPOSITION` | Reviewed reusable subset passes the frozen compatibility and CI criteria | Merge exact approved subset | Close/supersede PR 20 with replacement commit and rejection-evidence digest |
| `LOCAL_ADMINISTRATION` | The named laptop/path is reachable and its read-only inventory authenticates current state | Execute `PREV7-0402` through `PREV7-0407` normally | Freeze `unavailable_deferred_noncanonical`; emit distinct no-local-action alternative-completion receipts for `0402..0407`, proving remote canonical independence and scheduling a non-gating administrative successor if the path reappears |
| `EXECUTION_TOPOLOGY` | Licence and acceptable-use decisions approve public ciphertext transport and hosted plaintext | Public disposable four-CPU runner topology | Private four-CPU larger-runner topology only after its own licence, cost, capacity, security and equivalence receipts; otherwise `NO-GO` |
| `CAPACITY_TOPOLOGY` | Current account/plan/support and runner-group receipt proves at least 360 scientific jobs plus every shared source/destination control reserve, and proves required environment approvals for the selected visibility | Freeze exact 360-job topology and current capacity receipt before G2 | `NO-GO`; revise this plan/topology and obtain a new reviewed branch-row digest before G6A, never silently continue with lower capacity |
| `FORWARD_LOCK` | Distinct locked approver and owner authorize a first eligible future session | Create immutable future-forward namespace and start | `attested_no_forward_lock`; historical V7 remains unchanged |
| `G7_DISPOSITION` | Current G7 attempt succeeds before its deadline, or both custody domains authorize formal abandonment and finish cleanup | Successful attempt reaches `completed` and may green G7 | Failed/indeterminate attempt reaches `abandoned`, then only exact cleanup proof reaches `failed_abandoned_clean`; this can feed G9X but never green G7 |
| `ABANDONED_DISPATCH_BOUNDARY` | Formal abandonment inventory proves whether any dispatch capsule was consumed or any ciphertext was admitted | `pre_dispatch`: run the no-recovery branch of `PREV7-0914`, require its no-capsule/no-ciphertext receipt and do not activate decrypt/restore | `post_dispatch`: run the recovery-only branch of `PREV7-0914`, require terminal operation reconciliation and retained recipient keys before source/destination cleanup |
| `FULL_DISPOSITION` | Before deadline, frozen controller CAS may select completed; owner intents or deadline expiry enter a nonterminal remote-pending security state until both domains authorize abandoned | Normal G9 only from active `pending`; abandoned-clean task chain only from terminal `abandoned` | First intent enters `abandonment_pending_remote`; deadline enters `security_abandoned_pending_remote`; both stop dispatch and permit only evidence-preserving security cleanup until matching dual-owner receipts select `abandoned`; the non-selected chain closes only through mapped receipts |
| `APP_PRIVATE_KEY_IMPORT` | GitHub-generated App private key must enter its owning non-exportable broker | Direct provider-to-broker callback/import | Attested ephemeral administrative workstation with pinned read-only image digest, endpoint allowlist, no persistent disk/clipboard/swap, dual control, witnessed key destruction and immutable receipt; otherwise `NO-GO` |

Any prose alternative not represented in this registry is non-executable and
blocks the owning task. Changing a predicate, successor or invalidation rule is
a plan migration that invalidates every receipt derived from the old row.

`PREV7-0715` and the full-authorization controller are permanent controller
obligations, not reusable execution tasks. Once initialized they create
immutable child generations `G7_ATTEMPT-n` and `FULL_AUTH_ATTEMPT-n`. Each
child follows:

```text
created -> awaiting_approval -> authorized -> consumed
consumed -> dispatch_reconciling
dispatch_reconciling -> running | failed | dispatch_indeterminate
running -> succeeded | failed
created | awaiting_approval | authorized -> expired | cancelled
```

No child can be expired or cancelled after consumption. Every retry creates a
new sequence with fresh budget, inputs, approvals, keys, leases and evidence.
Downstream records name the exact child generation and reject controller-level
receipts or receipts from another generation.

`FULL_AUTH_ATTEMPT-n` is the owner-authorization/envelope generation; it is not
a gate attempt. G8 separately creates `G8_PREAUTH_ATTEMPT-n` and then the final
green `G8_ATTEMPT-n`. The authorization envelope carries the exact
`full_authorization_attempt_id`; the preauthorization binds that envelope
digest, and the final G8 attempt binds the preauthorization plus destination
sync/capsule receipt. G9 consumes the exact final `G8_ATTEMPT-n` and capsule
consumption receipt. No one of these three ID namespaces is an alias for or
valid substitute for another, and uniqueness/replay fixtures cover each
linkage.

Capsule consumption and the dispatch boundary are one compare-and-swap in the
authoritative full-attempt record:

```text
authorized -> consumed
capsule_digest=<exact digest>
dispatch_boundary_state=post_dispatch
github_dispatch_ack_state=confirmed|unknown
github_dispatch_receipt_digest_or_null=<exact receipt or null>
```

The complete acknowledgement enum is
`not_dispatched|confirmed|unknown`: `pre_dispatch` requires
`not_dispatched` and a null receipt; `post_dispatch` requires `confirmed` or
`unknown`, with a receipt required only for `confirmed`.
The CAS sets `dispatch_boundary_state=post_dispatch` before the external
dispatch call. If acknowledgement is ambiguous, only
`github_dispatch_ack_state=unknown`; the boundary remains post-dispatch and
the child enters `dispatch_reconciling`. The controller performs bounded,
idempotency-key-bound queries against the authoritative workflow-dispatch,
Actions-runs and Jobs APIs until it finds exactly one matching run or the
frozen reconciliation deadline expires. A matching run moves the child to
`running`; a cryptographically or provider-authenticated proven absence after
the deadline moves it to `failed`. An ambiguous, unavailable or conflicting
API response at the bounded deadline moves it to terminal-security state
`dispatch_indeterminate`. That state preserves `post_dispatch`, denies every
new dispatch/retry, expires or revokes all leases, preserves recipient keys,
ciphertext and evidence, and permits only inventory, restore, provider
reconciliation and abandoned-clean recovery. A later provider answer appends a
successor reconciliation event and never rewrites the indeterminate record. A
consumed capsule is
never reused, even when no run was ultimately created; any retry starts a
fresh generation only after the failed generation has terminal security,
operation and cost receipts. This protocol applies identically to G7, full and
recovery dispatches. There is no third boundary state and no state in which a
consumed capsule is pre-dispatch.

For a hard no-go after `PREV7-0000` but before a G7/full branch exists, the
state controller creates `NO_GO_CLOSE-n`. When G0 is incomplete it first
consumes the verified `PREV7-0011` bootstrap-failure close receipt. It executes
every active teardown manifest, preserves evidence, closes or bounds every
cost domain and emits `NO_GO_CLOSED`. This is a terminal safety state, never
scientific success and never a green substitute for G0 through G10.

`NO_GO_CLOSE-n` is an immutable child controller, not an untracked shortcut.
It may be created only when `PREV7-0000` is done, either G0 is green or an
authenticated G0-failure receipt exists, a machine-readable hard-no-go receipt
exists, and no G7 or full attempt has been consumed. If any G7 attempt exists,
its `PREV7-0714` cleanup and formal abandonment path apply; if any full attempt
exists, `FULL_DISPOSITION` and G9/G9X apply instead. Its state machine is:

```text
created -> inventory_frozen -> cleanup_running -> reconciliation
reconciliation -> NO_GO_CLOSED | failed
```

`failed` is immutable but not an impasse: the controller must create
`NO_GO_CLOSE-n+1` as a child whose `predecessor_close_digest` is the failed
head, whose inventory is the union of all predecessor inventories plus a fresh
provider query, and whose budget/cleanup receipts cover every still-open
obligation. Only one child may be current. Failed-child, owner-loss,
provider-outage and repeated-compensation fixtures prove eventual safe closure
without rewriting any prior generation.

The repository owner initiates it; the licence and acceptable-use reviewer
approves financial closure when that role exists, otherwise the bootstrap
owner records the missing-independent-review limitation and reserves maximum
liability. Its canonical record freezes:

```text
no_go_close_id
trigger_receipt_digest
bootstrap_g0_incomplete
failed_g0_predicate_set_digest_or_null
bootstrap_close_receipt_digest_or_null
evaluated_commit_sha
task_and_gate_head_digest
resource_inventory_digest
billing_domain_manifest_digest
teardown_manifest_digest
retained_evidence_manifest_digest
cleanup_receipt_set_digest
financial_closure_receipt_set_digest
terminal_financial_exception_or_null
terminal_state
closed_at_utc
event_chain_head_digest
```

It cannot mark a scientific task done, green a gate, mutate a terminal task or
erase an unresolved obligation. Every task it cancels must still carry its
normal immutable alternative-completion receipt. `NO_GO_CLOSED` is accepted
only after negative-access checks, retained-evidence restoration and every
resource/cost reconciliation equation pass.

## 11. Gate G0: Emergency Preservation

### PREV7-0000: Publish The Master Plan Safely

Actions:

1. As the sole safety-critical bootstrap exception, execute
   `BOOTSTRAP_FOUNDATION_TXN-1` before any repository PR. Its first atomic
   action creates an external provider-native transaction/closure record with
   idempotency key, maximum native-currency liability, ordered steps,
   compensations, teardown deadline and a provider-side closure route that
   remains executable if Git, GitHub or every later step fails. Before any
   charged resource, register provisional immutable actor IDs for repository
   owner, source App manager, source App-custody organization owner, exactly
   two distinct source App-manager JIT approvers, source account-root
   custodian, source billing-payer authorizer, source key-broker custodian,
   source break-glass custodian with current deputy/recovery evidence and a
   distinct source dual-control witness, plus a distinct provisional licence
   and acceptable-use reviewer for the exact opaque preservation operation.
   Every actor, recovery path and incompatibility is bound to the transaction
   record before any App, key, account resource or charge exists.
2. Within that transaction, freeze provider/account/region/terms,
   native-currency cap, teardown owner and retention; provision exactly one
   compliance-mode immutable escrow namespace with provider-managed encryption
   or independently protected KMS. Through an owner-authorized, witnessed JIT
   ceremony, create one dedicated bootstrap-preservation GitHub App, install it
   only on the API-attested numeric repository ID whose human-readable name is
   `trading-optimizer-lab-org/aurora`, grant only
   `Metadata: read` and `Actions: read`, and register its App ID, installation
   ID, key-generation ID and exact permission receipt. Import the
   GitHub-generated private key by the frozen `APP_PRIVATE_KEY_IMPORT` ceremony
   into the broker; no human, workflow or file receives it. Provision a
   bootstrap-only external preservation broker/controller that retains the App
   key, internally mints each short-lived installation token, performs only the
   fixed read of artifact `8251391531` and the fixed `PUT-if-absent` stream into
   that namespace, and returns only destination bytes plus receipts. It has no
   workflow, code, write, dispatch, scientific, locked-data or general GitHub
   authority. No artifact byte may leave GitHub until the provisional licence
   reviewer binds the exact source ownership/terms, encrypted payload class,
   destination provider/account/region/jurisdiction, retention and prohibited
   uses in `bootstrap_preservation_licence_receipt.json`; denial or ambiguity
   forbids every byte transfer, leaves the existing GitHub artifact read-only
   until its provider expiry and closes the bootstrap transaction as
   `NO_GO_CLOSED` with the exact licence blocker. The plan must not claim a
   source-only preservation copy because this bootstrap App has no write
   permission and no such destination exists.
3. Arm that external controller immediately, before PR 1. Prove positive
   fixed-artifact metadata/read and negative access to another artifact, run,
   repository, content, workflow dispatch, mutation and administration; also
   prove synthetic destination write/read-back, retention, delete/overwrite
   denial, token expiry and complete transaction rollback. It polls the artifact and
   schedule and automatically streams the exact remote bytes at the frozen
   last-safe start without GitHub Actions, the laptop or a repository workflow.
   All actors sign `emergency_escrow_foundation_receipt.json`; the transaction
   also emits `bootstrap_foundation_closure_receipt.json`, initially `armed`,
   whose independent teardown/close path is tested before another step starts.
   Both receipts are embedded in PR 1 and later migrated to canonical role/WORM
   registries. A missing actor, cap, immutable destination, broker-proxy test,
   armed monitor or closure proof aborts and compensates the transaction.
   Normal closure after `PREV7-0003` suspends and uninstalls the dedicated App,
   revokes every token, destroys the broker key under witnessed receipt, removes
   the temporary controller and proves post-close negative access. A retained
   escrow object has recovery-only storage authority and no GitHub credential.
4. Fetch and prune `origin`.
5. Resolve the current `origin/main` SHA through GitHub and Git.
6. Create a documentation branch from that exact SHA.
7. Add this content as `docs/plans/gtbi-v7-master-plan.md`.
8. Replace both old plan paths with short redirects.
9. Import the exact externally retained canonical-serialization profile,
   hash-domain registry, audit-scope manifest, three-round quality receipts and
   receipt-set object
   defined in sections 1.1 and 16. Verify the two raw-byte bootstrap digests
   first, then recompute every registered-domain digest, verify signatures,
   actor/key independence, strict sequence, non-overlapping times, complete
   scope and exact equality with the candidate master-plan bytes. A failed
   check aborts PR 1 and returns the document to quality round zero.
10. Generate the initial `task_status.csv`, `gate_status.csv`,
   `gate_definitions.csv`,
   `task_events.jsonl`, `task_attempts.jsonl`, `gate_events.jsonl`,
   `conditional_branch_registry.csv`, `task_definitions.csv`,
   `task_planning_inputs.csv` and
   `task_delivery_manifest.csv` from the exact matrix and branch table, with no
   fabricated completion.
   Every task row contains every section-9 field. Unknown actor assignments,
   inputs or acceptance details remain explicitly `blocked`; no placeholder
   value can make a task `ready`.
   Before generating those projections, create and review one
   `task_planning_inputs.csv` row per matrix task under the typed planning-state
   rules in section 9. Every G0 preservation or closure row must be
   `planning_state=complete`; a later task with a genuine unavailable actor,
   price or external input uses the exact blocked state and blocker code,
   never an invented date, actor, duration or cost.
   The generator also computes the dependency critical path, lead times,
   latest starts and per-domain cost estimates backwards from every immutable
   expiry/deadline. A missed normal-preservation safety start immediately
   selects `EMERGENCY_ESCROW`/`PREV7-0012`; any other missed hard latest start
   creates a blocker and activates `PREV7-0011` when G0 is not yet green.
11. Deploy the repository-side bootstrap-closure controller whose closed
   allowlist can
   append only provisional `PREV7-0000`, `PREV7-0001`, `PREV7-0002`,
   `PREV7-0009`, `PREV7-0006`, `PREV7-0011`, `PREV7-0012` and
   `NO_GO_CLOSE-n` events,
   freeze inventories and record teardown/cost receipts. It has no
   general readiness, gate-green, workflow, environment, App, scientific or
   merge authority.
12. Add a structural plan validator, quality-receipt validator and append-only
    event validator to CI.
13. Open a pull request containing documentation, the exact canonicalization
    profile/domain registry and quality receipt set, initial status records,
   validators and an optional preservation-only emergency-escrow workflow as a
   post-genesis replacement path. The already armed external controller remains
   authoritative until that workflow has merged, is pinned to an immutable
   workflow/tree SHA, passes an actual synthetic OIDC stream test and the
   authority-handover CAS records exactly one current guard. No PR or workflow
   registration is required for protection during genesis.
14. Merge after required checks pass.
15. Execute the two-PR genesis protocol. Before the master plan is staged in
    the PR-1 candidate tree, materialize `.gitattributes`, verify its effective
    attributes and regenerate the plan as the canonical LF/UTF-8 bytes audited
    above. PR 1 contains schemas, validators, `.gitattributes`, the
    matrix-derived records and genesis events bound to the exact base SHA,
    proposed head SHA, actor, approval and audited master-plan
    SHA-256/length/blob ID. A post-merge check hashes the Git blob bytes from
    `main`, not a transformed checkout, and requires exact equality. PR 2
    appends, without rewriting PR 1,
    the PR-1 merge SHA, CI run/result, WORM migration status and terminal
    bootstrap event. `PREV7-0001` cannot become ready until PR 2 merges and its
    append-only prefix check passes.

Every genesis event written before `PREV7-0006` is explicitly classified
`provisional_git_bootstrap`; it is not called WORM-accepted evidence until the
dual-domain import and anchor ceremony in `PREV7-0006` succeeds.

No GTBI implementation code is included in this pull request. The exceptional
escrow workflow is operational preservation plumbing, not scientific
execution.
Until the genesis protocol completes, the readiness records do not exist by design
and no later task may start. The proposed document itself is not evidence that
an emergency action occurred.

`BOOTSTRAP_FOUNDATION_TXN-1` is independently closable before `PREV7-0000`
exists. Any failed step atomically stops further provisioning and creates
`BOOTSTRAP_FOUNDATION_CLOSE-n` with states:

```text
created -> inventory_frozen -> compensation_running -> reconciliation
reconciliation -> FOUNDATION_CLOSED | failed
failed -> FOUNDATION_CLOSE-(n+1)
```

Each successor preserves the prior event/receipt set and retries only
unresolved idempotent compensations. The provider-side controller revokes
tokens/App installation, disables the guard, tears down every non-retained
   resource, suspends/uninstalls the bootstrap App, revokes every token,
   destroys its broker key, closes or reserves maximum liability and retains the signed
transaction/teardown evidence. If exact V6 bytes were already escrowed, their
immutable object is retained and its access is reduced to recovery-only rather
than deleted. This path requires no Git branch, task row, later reviewer or
laptop. A later successful genesis imports the entire external chain; a failed
genesis can still end safely at `FOUNDATION_CLOSED`.

### PREV7-0012: Safety-Deadline Emergency Escrow

The provisional external monitor is armed before genesis PR 1 and records its
events in `BOOTSTRAP_FOUNDATION_TXN-1`. Immediately after genesis, those events
are imported without rewriting into `PREV7-0012`, and the
resource-constrained scheduler evaluates
`EMERGENCY_ESCROW`. If normal dual-copy preservation and both clean restores
are currently projected to finish no later than `2026-08-03T18:16:37Z`, it
appends a nonterminal `armed_normal_path` receipt. The task remains
`in_progress`: the external non-scientific monitor re-evaluates the resource-constrained
schedule and remote-artifact availability at least every 30 minutes and after
every task/provider/actor failure until `PREV7-0003` has verified both durable
copies and both clean restores. The immutable
`last_safe_escrow_start_at_utc` is derived from a measured worst-case stream,
read-back and retry duration plus clock margin. At or before that instant, or
immediately on a missing/stale estimate, delay, failed prerequisite or lost
margin, the already authorized escrow manifest automatically selects the
escrow branch; it does not wait for a new human approval.

Before a tested post-genesis handover, the external broker/controller uses the
`emergency_escrow_foundation_receipt.json` created inside `PREV7-0000` and
streams the still-remote artifact bytes directly into the pre-provisioned
immutable external object. After handover, the registered immutable-SHA
workflow may perform that exact operation through broker mediation; the
workflow never receives a GitHub App token. Both paths verify provider artifact ID,
name, expected `1962204087` bytes, GitHub digest
`sha256:870ab8a0ded260b7761b7c706c239c4fce712d2fd7f7c8fb1d41dc1dffedda5b`,
destination version/retention and a read-back digest. It never extracts,
parses or recalculates the payload and never uses the laptop.

This escrow is an emergency continuity copy, not G0 completion, Oracle-B
evidence or a substitute for primary/mirror custody. `PREV7-0003` must later
promote the exact bytes into both approved stores, perform both clean restores
and bind the escrow/promoted-object digest equality. `PREV7-0012` becomes
`done` only after that receipt; an initial normal-path forecast can never close
or cancel it. `PREV7-0003` consumes the nonterminal
`escrow_guard_armed_receipt_digest`, not terminal completion of this task.
Failure to escrow by the
safety deadline stops every non-preservation task and invokes `PREV7-0011`;
the final GitHub artifact expiry remains `2026-08-10T18:16:37Z`.

### PREV7-0001: Regenerate Inventory

Create:

```text
scripts/generate_gtbi_v7_inventory.py
.github/workflows/gtbi-v7-inventory.yml
docs/project_inventory/schema.json
docs/project_inventory/audit_metadata.json
docs/project_inventory/branches.csv
docs/project_inventory/worktrees.csv
docs/project_inventory/workflows.csv
docs/project_inventory/runs_active.csv
docs/project_inventory/artifacts_critical.csv
docs/project_inventory/artifact_counts.json
docs/project_inventory/releases.csv
docs/project_inventory/packages.csv
docs/project_inventory/collaborators.csv
docs/project_inventory/environments.csv
docs/project_inventory/privileged_surfaces.csv
docs/project_inventory/security_settings.json
```

The script, query manifest and workflow are pinned outputs of the task. Current
CSV/JSON files are a convenience view, not immutable history. Every gate
preflight publishes a content-addressed inventory snapshot to the approved
evidence store and appends its logical ID, SHA-256, query-manifest digest,
workflow run ID and default-branch SHA to the gate evidence. A gate cannot reuse
an older snapshot merely because `PREV7-0001` is already `done`.

`audit_metadata.json` must include:

```text
audited_at_utc
repository
default_branch
default_branch_sha
gh_cli_version
query_manifest_sha256
inventory_scope
complete
```

Repository, Actions, artifact, release, package, collaborator and environment
inventory is executed in GitHub and is authoritative for remote state. GitHub
runners cannot see laptop worktrees, so `worktrees.csv` and dirty-path metadata
come from a separate local, read-only administrative scan using Git and
filesystem metadata only. That scan runs no test, download, backtest or project
code. It is authoritative only for local cleanup at its recorded timestamp.
Public evidence redacts the user-home prefix; exact local paths, when needed for
rollback, remain private evidence.

Local state is never a prerequisite for remote preservation or scientific
gates. If the laptop/path is unavailable, the owner emits
`local_state_receipt.json` with `state=unavailable`, last known inventory
digest/time or null, affected path classes and the assertion that no canonical
asset, credential, campaign authority or GitHub-only execution depends on
them. `worktrees.csv` is then a schema-valid empty/unavailable projection, not
fabricated completeness. G0 and later scientific gates consume the complete
remote inventory plus this explicit receipt. When local access returns,
`PREV7-0402` through `PREV7-0405` may append a fresh administrative inventory
and cleanup chain without changing scientific evidence or reopening a gate.

This P0 inventory is deliberately bounded. It resolves exact metadata for the
known V6 artifact, every artifact associated with known preservation and
post-validation runs, active runs, current releases and packages, while
recording repository-wide artifact counts without enumerating all `326,415`
records. It sets:

```text
inventory_scope=emergency_preservation
complete=true
```

for that declared scope only. It never claims to be the complete cleanup
inventory. `PREV7-0400` performs the full resumable enumeration after the V6
result is safe.

### PREV7-0002: Stop Legacy Capacity Waste

Actions:

1. Generate an exact cancellation candidate list.
2. Exclude any run that publishes or preserves canonical evidence.
3. Require repository-owner approval.
4. Cancel only approved run IDs.
5. Record API response and final state.

No broad cancellation by workflow name is allowed.
If refreshed inventory still shows zero queued or active legacy runs, the task
completes with an empty cancellation manifest and API evidence; it never
creates work merely to exercise cancellation.

### PREV7-0006: Bootstrap Emergency Private Storage

Before downloading the expiring V6 artifact:

1. Create the two private Release-asset repositories.
2. Confirm the repository owner can publish and restore from GitHub Actions.
3. Calculate primary, mirror, restore-test and temporary working bytes from the
   inventory. Confirm approved storage capacity and billing for that measured
   total plus a documented safety margin; `20 GiB` is a floor, not an assumed
   sufficient amount or cap. Before any paid write, freeze payer actor/account,
   native ISO 4217 currency, integer minor-unit storage/transfer/request/tax
   caps, pricing source and validity, safety reserve, alert thresholds,
   automatic-spend prevention where supported and an owner approval receipt.
   An unavailable or uncapped price leaves the task blocked.
4. Disable automatic deletion for the preservation package.
5. Create a private test asset.
6. Restore the test asset on a clean GitHub runner.
7. Record package visibility, permissions and retention.
8. Freeze the public, private and prohibited evidence classifications from
   section 9.
9. Prove that public evidence validation rejects a synthetic secret and a
   synthetic licensed-data row.
10. Import every `provisional_git_bootstrap` event created before WORM storage
    existed, preserving its byte order, event digest and Git blob identity.
    This task creates two provider-enforced bootstrap WORM stores under
    separate service identities, records primary/mirror object versions,
    anchors the imported chain head in the independent timestamp service and
    proves restore/reconciliation. G0 cannot become green before this
    migration. Bootstrap WORM is durable emergency evidence but not yet
    independent-destination evidence. `PREV7-0308` copies and re-anchors the
    complete chain into the destination custody domain; G8 accepts no earlier
    event until source WORM, destination WORM and current anchor all verify.
    Git remains a readable snapshot, not the authority.

The evidence-custody state is explicit:

```text
bootstrap_accepted:
  two source bootstrap WORM stores under disjoint service identities
  current externally anchored head
  readiness-state-controller handover receipt

production_accepted:
  bootstrap_accepted
  destination WORM copy under independent ownership
  source/destination reconciliation and fresh external anchor
```

`bootstrap_accepted` is sufficient only through G2. `production_accepted` is
mandatory for G3B and every later gate. This prevents a circular dependency on
`PREV7-0308` while preserving the independent-destination requirement.

This bootstrap is deliberately independent from later V7 implementation
details. Its only purpose is to prevent loss of existing scientific evidence.

### PREV7-0009: Bootstrap Emergency App And Broker Custody

Before any private scientific asset credential or any post-foundation App,
key, account resource or charge exists:

1. Restore and validate the provisional actors/receipts already created by
   `BOOTSTRAP_FOUNDATION_TXN-1`: source App manager, source App-custody
   organization owner, exactly two distinct indexed source App-manager JIT
   approvers, source dual-control witness, source key-broker custodian, source
   break-glass custodian, source account-root custodian and source billing-payer
   authorizer with the incompatibilities defined in section 12. A missing or
   changed actor closes/no-goes the foundation transaction; it is not silently
   replaced after resources exist. Complete this validation before creating
   anything beyond the one dedicated bootstrap App, immutable escrow namespace
   and broker/controller already authorized inside that transaction. The App
   manager has no standing organization-owner access: each
   activation is time-bounded, approved by both JIT actors, witnessed and
   closed with a negative-access receipt.
   Record immutable actor IDs, deputies, current authentication/recovery
   evidence and incompatibilities in the provisional role registry.
2. Freeze provider, account, region, service terms, billing owner, monetary
   cap, support/expiry dates and teardown responsibility for the emergency
   broker/HSM.
3. Create a non-exportable broker key domain and a separate encrypted
   configuration backup/restore path. Prove issue, revoke, restore, rotate and
   teardown with synthetic identities.
4. Freeze `APP_PRIVATE_KEY_IMPORT`. Prefer direct provider-to-broker import.
   The attested-workstation alternative is admissible only under the exact
   no-persistence, no-clipboard, endpoint-allowlist, dual-control and witnessed
   destruction contract in section 10.
5. Configure exact OIDC trust and one-use nonce verification for the
   preservation workflows. No long-lived App key enters Actions secrets.
6. Record a joint owner/custodian approval. A missing custodian or unbounded
   broker cost leaves this task and G0 red.

The task definition requires independent receipts from
`source_app_manager`, `source_app_custody_organization_owner`, both indexed
`source_app_manager_jit_approver` actors, `source_dual_control_witness`,
`source_key_broker_custodian`, `source_break_glass_custodian`,
`source_account_root_custodian` and `source_billing_payer_authorizer`; the
repository owner remains accountable but cannot substitute for any of them.

### PREV7-0010: Deploy The Readiness State Controller

After emergency storage and custody exist, the source App manager creates and
the repository owner installs one monofunction `readiness-state-controller`
App. Its only write authority is the protected readiness-record namespace and
the matching provider-enforced WORM event chain. It has no Actions, repository
administration, release, package, issue, scientific-asset, checkpoint, merge,
result, dispatch, cleanup or locked-data permission.

The task delivers:

```text
infra/readiness_state_controller/
config/gtbi/schemas/readiness/
docs/readiness/gtbi-v7/state_controller_manifest.json
docs/readiness/gtbi-v7/state_controller_recovery_receipt.json
```

`state_controller_manifest.json` is not prose. For the exact App installation
it freezes App/installation/repository/owner IDs, repository selection,
permission names and levels, allowed refs, allowed readiness path prefixes,
GitHub REST/GraphQL API methods and endpoints, request-body schema digests,
WORM provider/account/region/object prefixes, OIDC workload identity and every
explicitly denied permission/endpoint. The only Git write is creation/update
of the named readiness-state PR branch and append-only readiness paths; it
cannot merge that PR. If GitHub forces a token permission wider than one
allowlisted method, a separate broker mediates the token and enforces exact
endpoint/method/body/repository/ref/path before making the call; the workflow
never receives that token. CI performs positive calls for every allowlisted
operation and negative calls for code, workflow, Actions, environment,
administration, release, package, issue, dispatch, merge and non-readiness
paths. Any unlisted successful call is `NO-GO`.

The initial exact profile is:

```text
repository_selection=[canonical_source_repository_id]
github_app_permissions:
  metadata=read
  contents=write
  pull_requests=write
allowed_base_ref=refs/heads/main
allowed_head_ref_prefix=refs/heads/gtbi-readiness-state/
allowed_changed_path_prefixes=[docs/readiness/gtbi-v7/]
allowed_rest_methods:
  GET /repos/{owner}/{repo}
  GET /repos/{owner}/{repo}/git/ref/heads/main
  GET /repos/{owner}/{repo}/git/commits/{sha}
  GET /repos/{owner}/{repo}/git/trees/{sha}
  POST /repos/{owner}/{repo}/git/blobs
  POST /repos/{owner}/{repo}/git/trees
  POST /repos/{owner}/{repo}/git/commits
  POST /repos/{owner}/{repo}/git/refs
  PATCH /repos/{owner}/{repo}/git/refs/heads/gtbi-readiness-state/{transaction_id}
  POST /repos/{owner}/{repo}/pulls
merge_methods=[]
graphql_mutations=[]
```

Because `contents: write` cannot be restricted by GitHub to one path, every
write is obligatorily broker-mediated. The broker keeps the App key/token,
reconstructs and compares the proposed parent/tree, permits only regular files
under the prefix, rejects deletion/modification outside it, validates canonical
serialization and event-chain CAS, and itself performs the allowlisted call.
The controller receives only the fixed receipt and never an installation token.
The App's residual repository-wide contents authority is recorded in the
threat model and requires independent acceptance; a direct-token path is
forbidden.

Acceptance proves exact Git/WORM compare-and-swap, append-only prefix
enforcement, event/gate atomicity, replay rejection, stale-head rejection,
partial-write recovery, independent WORM reconciliation, key rotation,
installation suspension/removal, deny-all rollback and negative permissions.
The controller signs no scientific result and cannot approve its own change.

Before this task is done, only `PREV7-0000`, `PREV7-0001`, `PREV7-0002`,
`PREV7-0009`, `PREV7-0006`, `PREV7-0010`, conditional `PREV7-0011`,
`PREV7-0012` and the `NO_GO_CLOSE-n` or
`BOOTSTRAP_FOUNDATION_CLOSE-n` child may append events, and only under the
`provisional_git_bootstrap` protocol. Those events cannot green any gate. This
task imports and reconciles them into both source bootstrap WORM stores,
publishes the exact migration receipt and permanently disables provisional
event publication in the same atomic handover transaction that appends
`PREV7-0010`'s own terminal receipt. It reconciles the events already imported by
`PREV7-0006`, adopts their exact WORM head and emits the controller-handover
receipt. Every later state transition must come from the installed
controller and pass the exact approver-role policy frozen in its task/gate
definition. A Workflow reviewer is required only where that policy names one;
G0 does not invent a vacant reviewer.

### PREV7-0011: Close A Partial Bootstrap Safely

This conditional safety task exists from the moment `PREV7-0000` is done. It
activates when an authenticated hard no-go occurs before G0 completes and no
G7/full attempt has been consumed. It freezes the partial inventory, revokes
every credential already created, tears down every non-retained resource,
preserves the maximal safe evidence subset, closes or bounds each cost domain
and emits the bootstrap-failure receipt consumed by `NO_GO_CLOSE-n`.

On normal progress, once every other G0 predicate is true, the controller
records `G0_READY_EXCEPT_0011`. One atomic transaction then cancels
`PREV7-0011` with that receipt and transitions G0 to green; neither state can be
published alone. It cannot repair missing scientific evidence or convert a
failed bootstrap into readiness. If the full controller does not yet exist, the
minimal controller deployed by `PREV7-0000` may execute only the no-go path,
then seal its chain for later import; safe closure never depends on
`PREV7-0010`.

### PREV7-0007: Configure Private Asset Authentication

Actions:

1. Under the source App manager, create one read-only GitHub App plus two physically separate publish-only
   Apps, one for primary and one for mirror, as described in section 7.3. All
   three use different keys; the two publishers use disjoint installations.
2. Install the read App only on the exact two private Release repositories and
   bind every reduced token to one installation/repository. Install each
   publisher only on its own repository. The read App has no write permission,
   either publisher has no Aurora code-write permission, and none has
   organization administration.
3. Bootstrap `gtbi-assets-read`, `gtbi-assets-primary-publish` and
   `gtbi-assets-mirror-publish` as the three minimum preservation environments,
   restricted to exact reviewed refs.
4. Put each reduced authentication route only in its corresponding preservation
   environment; no environment can select both publishers.
5. Record all App and installation IDs and their disjoint permission policies
   without recording private key material.
6. Require repository-owner and source-key-broker-custodian approval receipts
   bound to the exact App/installations/environment digest and selected
   private-key-import route.

### PREV7-0008: Register Emergency Preservation Workflows

The fixed final-result path consumes canonical
`v6_preservation_manifest_v1` with exactly:

```text
schema_version
source_repository
source_run_id
source_artifact_id
source_artifact_name
source_size_bytes
source_archive_digest
source_expires_at_utc
maximum_archive_bytes
maximum_member_count
maximum_total_uncompressed_bytes
maximum_compression_ratio
part_size_bytes
preservation_manifest_digest
```

`preservation_manifest_digest` is a `self_field` digest under
`GTBI_V6_PRESERVATION_MANIFEST_V1`; its preimage omits only that field. The
workflow accepts this reviewed object by exact digest and never accepts
individual source coordinates or limits as dispatch inputs.

Create on a branch from the latest `origin/main`:

```text
.github/workflows/gtbi-v6-emergency-preserve.yml
.github/workflows/gtbi-v6-emergency-restore.yml
```

Register them through a narrowly scoped pull request before attempting
dispatch. They are preservation infrastructure, not GTBI implementation. All
workflows:

- have only `workflow_dispatch`;
- use an immutable manifest already reviewed on the dispatch ref.
  `gtbi-v6-emergency-preserve.yml` has two closed modes,
  `final_result` and `evidence_batch`; it does not delegate to a third workflow.
  The final-
  result path hard-codes run `29162930823`, artifact `8251391531`, expected
  name, size, digest and expiry. The evidence-batch path accepts only a
  `preservation_manifest_digest` that resolves from the reviewed registry and
  whose object allowlist is limited to `PREV7-0004` locked evidence or
  `PREV7-0005` recovered bytes;
- accept no arbitrary URL, repository, archive path, shell fragment or
  scientific date input;
- run only from a unique preservation tag whose expected commit SHA, tree
  digest, workflow path/blob digest and complete workflow-bundle digest are
  frozen in the approved manifest. Before every credentialed operation the
  external broker independently resolves that tag through Git/GitHub, requires
  exact equality and performs the fixed API call itself; mutable `main`, a
  branch name or tag-name equality alone is never trusted. A moved/recreated
  tag or changed workflow aborts and is an incident;
- use `actions: read` and `contents: read` for the preservation job, no default
  write permission, pinned Actions and a job timeout; private publishing uses
  only the fixed-operation external publisher broker; no App token leaves it;
- use the target-specific `gtbi-assets-primary-publish` or
  `gtbi-assets-mirror-publish` environment for publication and
  `gtbi-assets-read` with one exact installation for restore verification;
- verify repository, actor, ref, manifest and environment before minting a
  token;
- run an authorization smoke proving that the reviewed job can mint and use a
  reduced short-lived token, an ordinary pull request and fork cannot access
  it, and a revoked token cannot restore the synthetic private test asset;
- stream and validate each allowlisted object as specified by `PREV7-0003`;
- never expose a token to the archive inspection subprocess;
- emit a public-safe manifest and private detailed evidence;
- fail closed on any identity, digest, size, licence or restore mismatch.

The PR records the default-branch registration SHA. Direct push to `main` is
not an acceptable shortcut even though branch protection is not yet present.
Fixtures prove that a digest cannot select a different path, repository, run,
artifact or local file than its reviewed manifest. Each `PREV7-0004` and
`PREV7-0005` batch has its own restore run, object-level digest reconciliation
and completion receipt before either task can become done.

### PREV7-0003: Preserve V6 Final Result

This task deliberately does not list `PREV7-0012` as an ordinary dependency:
`PREV7-0012` remains nonterminal until this task finishes, so a `done`
dependency would be circular. Its machine-readable `entry_conditions` instead
require `PREV7-0012.status=in_progress`, a current verified
`escrow_guard_armed_receipt_digest`, a live monitor lease and no terminal
bootstrap-foundation closure. The state validator evaluates that dynamic guard
in the same transaction that moves `PREV7-0003` to `ready` or `in_progress`.
Loss or staleness immediately blocks the transition and invokes the selected
escrow/no-go path. Completion of `PREV7-0003` then supplies the dual-restore
receipt that allows `PREV7-0012` to become `done`.

Actions:

1. Resolve and verify the exact historical ref
   `refs/heads/codex/gtbi-github-only-external-pack-72000` through Git and the
   GitHub API, require it to equal
   `cb80c5065c127322a303d58aea0f6c05337a6c9e`, then immediately create the
   protected immutable archive tag
   `gtbi-v6-fast-strict-run-29162930823`. The tag ruleset permits initial
   creation only and blocks update/deletion without separately audited
   break-glass.
2. Verify the commit tree and run workflow bytes through both Git and GitHub.
3. Query artifact `8251391531` metadata and verify its expected size, name,
   expiry and digest before transfer.
4. Preflight free disk for the raw archive, one working copy or split set and
   a safety margin; abort before download if the measured budget is
   insufficient.
5. Stream the REST artifact archive to a file with redirect following,
   fail-on-HTTP-error, bounded retries and an exact maximum byte count. Do not
   use a helper that automatically extracts the archive.
6. Verify downloaded byte count and GitHub archive digest before inspection.
7. Validate the ZIP central directory, member paths, declared uncompressed
   total and compression ratio. Stream each member only to the hash function to
   calculate the internal file manifest; never extract the whole archive.
8. Split the verified raw archive into parts of at most `1900 MiB` without
   retaining unnecessary duplicate copies.
9. Publish the private primary Release asset under immutable repository,
   release and asset IDs and verify its reconstructed payload digest.
10. Publish private mirror release assets.
11. Store the detailed manifest privately. Commit only the generated
   provisional G0 receipt allowed by section 9 to `provenance/v6/`; it cannot
   become final authorization evidence until independent redaction review.
12. Reconstruct the raw archive from primary on a clean runner.
13. Reconstruct it from the mirror on another clean runner.
14. Confirm byte-identical archive SHA-256 and the complete streamed member-hash
    manifest from both restores.
15. Enumerate and secret-scan every Git object reachable by the proposed source
    closure, including refs, tags, trees, blobs, submodule metadata and LFS
    pointers, before any immutable bundle publication. Create a source
    `git bundle` or equivalently complete repository bundle containing the
    commit and every object required to check it out only when that scan has no
    unresolved secret. Verify it in a repository with no existing Aurora
    objects. Inventory Git submodules and LFS pointers and preserve their exact
    external objects by digest, or classify the source layer incomplete. A
    true secret is revoked/rotated and excluded from the ordinary evidence
    package; any necessary incident custody uses a separate restricted
    incident procedure and never the normal immutable archive.
16. Publish that source bundle and dependency-file manifest to primary and
    mirror storage by digest.
17. Record branch ref, commit, tree, workflow, dependency files, source-bundle and tag
    digests separately from the result archive digest.

Deadline:

```text
before 2026-08-10T18:16:37Z
```

If preservation is not verified before the deadline, all non-preservation work
stops.

The remote artifact is the preferred source. `PREV7-0001` also inventories any
already downloaded local copy as non-canonical emergency evidence without
publishing its private path. If the remote bytes disappear before preservation,
the repository owner may authorize one byte-only local transfer: enumerate only
regular files, reject links/devices, build a canonical per-file manifest with
SHA-256, bind it to the owner authorization receipt, upload without parsing or
recalculation, and restore/rehash on a clean GitHub runner. A separate signature
is optional and cannot be required until the signing mechanism in section 14
has been tested.
Such a copy becomes equivalent to the remote artifact only if a previously
trusted internal member manifest proves every file and metadata field required
by the output contract. Otherwise it is labelled
`recovered_local_result_incomplete_transport_identity`; it preserves evidence
but cannot satisfy Oracle B or full V6 archive equivalence.

### PREV7-0004: Preserve Locked Evidence

Archive:

- every locked or post-validation run manifest;
- commit SHA;
- workflow;
- inputs;
- access logs;
- result summary;
- artifact digests;
- dates first observed.

Mark all observed `2021+` evidence as:

```text
historical_post_validation_contaminated=true
pristine_locked=false
```

### PREV7-0005: Recover V6 Dependency Chain

Search only existing GitHub resources and already stored local read-only
copies. Do not recalculate.

A local survivor is not automatically canonical. It is accepted as the exact
original layer only when its complete bytes match a previously recorded trusted
digest and identity. If no trusted digest exists, classify it as
`unverified_local_survivor` and do not claim full V6 reproducibility.

When a sole surviving local file is worth preserving, the repository owner may
approve a one-time non-scientific byte transfer to private GitHub storage. The
transfer performs no parsing, normalization, feature generation or backtest;
records source path classification, operator, size and pre/post SHA-256; and
deletes no local source. Future restoration, preparation and all scientific
execution remain GitHub-only. The manifest records this provenance limitation
even after the bytes are durable.

For C, D0, D1, D2, D3, S and R, report:

```text
found
missing
candidate_copy
copy_sha256
authenticated
reproducible
```

Gate G0 passes only when:

- the master plan is tracked and reviewable from a branch based on the latest
  `origin/main`;
- `PREV7-0002` has reconciled every legacy queued/in-progress run to an
  immutable terminal-state receipt;
- the nonterminal `PREV7-0012` emergency-escrow monitor remained armed until
  `PREV7-0003` completed; if its last-safe-start trigger fired, the exact
  emergency object has a verified promotion chain, and in either branch
  `PREV7-0012` closes only from the completed `PREV7-0003` dual-copy/restore
  receipt;
- emergency private storage has passed a clean-runner restore;
- source App-manager/key-broker custody has distinct actors, bounded cost,
  tested import/rotation/recovery/teardown and joint approval;
- private access uses a tested short-lived credential;
- V6 final result is durably restored from both copies;
- locked evidence is preserved;
- every V6 dependency layer is classified honestly.
- every provisional bootstrap event has been migrated to both source bootstrap
  WORM stores, anchored and handed to the deployed readiness state controller;
- `bootstrap_accepted=true`, `destination_worm_required=false` at G0, and the
  two-PR genesis chain is complete.

## 12. Gates G1A And G1B: V7 Identity And Roles

### Unified V7 Target

`PREV7-0101` is satisfied by the repository-owner decision to unify the
readiness and V7 performance plans.

ADR `docs/adr/0003-gtbi-v7-identity.md` records:

```text
product=GTBI V7 Performance Engine
reference_engine=GTBI Fast Strict V6
clean_portfolio_in_scope=false
scientific_change_allowed=false
full_run_authorized=false
```

The ADR also records that any future Clean Portfolio implementation uses a
different product name, contract, baseline and validation campaign.

### Reviewer Readiness

Minimum safe target:

```text
repository_owner=1
additional_trusted_collaborators>=2
scientific_reviewer=1
workflow_reviewer=1
independent_security_reviewer=1 before PREV7-0209
licence_and_acceptable_use_reviewer=1 before G2
independent_redaction_reviewer=1 before public evidence is final
source_app_manager=1 recruited as the first atomic step of PREV7-0009,
  before any App installation, key or external resource
destination_app_manager=1 before destination App installation
source_deadman_operator=1 before PREV7-0610
source_deadman_deputy=1 before PREV7-0610
destination_deadman_operator=1 before PREV7-0611
destination_deadman_deputy=1 before PREV7-0611
source_key_broker_custodian=1 recruited as the first atomic step of PREV7-0009,
  before any broker/HSM key or external resource
destination_key_broker_custodian=1 before PREV7-0611
source_account_root_custodian=1 before any source external-provider account/resource
destination_account_root_custodian=1 before any destination external-provider account/resource
source_billing_payer_authorizer=1 before any source reservation
destination_billing_payer_authorizer=1 before any destination reservation
source_app_custody_organization_owner=1 before any source App-custody resource
destination_app_custody_organization_owner=1 before any destination App-custody resource
source_app_manager_jit_approver=2 distinct indexed actors before source App-manager activation
destination_app_manager_jit_approver=2 distinct indexed actors before destination App-manager activation
source_dual_control_witness=1 before any source key/App/destructive ceremony
destination_dual_control_witness=1 before any destination key/App/destructive ceremony
workflow_initiator=1 before any protected dispatch
locked_approver=1 or attested_no_forward_lock
independent_disaster_copy_owner=1 before G3B/G8
destination_break_glass_custodian=1 before PREV7-0308 completes
source_break_glass_custodian=1 before G3B
phishing_resistant_auth_and_two_authenticators=all_privileged_humans
```

`PREV7-0201` creates
`config/gtbi/governance/role_registry.json` and its schema
`config/gtbi/schemas/readiness/role_registry.schema.json`. Each assignment
contains immutable actor ID, role, custody domain, status, effective/expiry
time, deputy actor ID, authentication-evidence digest, recovery-evidence
digest, incompatibility-set digest, approving actors and transition-event
digest. It onboards source and destination owners, deputies, reviewers, App
managers, App-custody organization owners/JIT approvers, dual-control witnesses, broker custodians,
deadman operators and break-glass actors; tests
negative access and all required incompatibilities. The registry also requires
the exact two indexed canonical JIT-approver assignments for each App-manager
activation. `PREV7-0610`, `PREV7-0611`, `PREV7-0801` and `PREV7-0808` consume
the exact current registry digest and become blocked on expiry, vacancy or
drift.

Account-root custodians are emergency-only identities with hardware-backed
authentication, separately held recovery material, no daily workload role and
two-person activation evidence. Billing payer authorizers control the exact
native-currency account/reservation ceiling but cannot approve science,
workflow code, dispatch, evidence or their own charges. Source and destination
root/payer actors and credentials are disjoint; none may be the implementer,
workflow initiator or scientific/workflow/security reviewer for the same
campaign. Each provider account records succession, support-mediated recovery,
invoices, payer account, tax identity, offboarding and total-custodian-loss
drills. Loss or compromise suspends new leases/dispatch, rotates recovery paths
and invalidates dependent monetary receipts without granting a reviewer or
operator replacement authority.

`additional_trusted_collaborators>=2` is only the G1B reviewer bootstrap floor,
not the staffing count for a full. The full remains blocked until every
distinct source and destination role above has a different eligible human or a
task explicitly records that the role is not activated.

The scientific, workflow and independent security reviewers are named,
eligible actors. The security reviewer is distinct from the implementation
author, repository owner and every App manager for each threat/residual-risk
decision signed. The scientific and workflow reviewers are different people
and both are independent from the implementation author. The repository owner supplies a
third authorization for budget and full dispatch; it does not replace either
review. The licence/acceptable-use reviewer and redaction reviewer are
independent of the document/evidence author and repository owner for the
decisions they sign. The workflow initiator is distinct from the environment
approver and owner authorizing that same full. In each domain, owner/authorizer,
App manager, deadman operator, deadman deputy, key-broker custodian and
break-glass custodian are pairwise distinct and separately registered. Source
and destination privileged roles have no cross-domain credentials, and the
same human cannot occupy a privileged role in both domains.

The frozen role registry includes immutable actor IDs, authentication-policy
receipts, recovery-custody owner, last access review and offboarding test for
every privileged human. G1B cannot pass with a single recoverable source owner
and no distinct break-glass custodian, even if branch protection itself is
green.

Gate `G1A`, which permits implementation and non-locked smoke preparation,
passes only when:

- V7 identity ADR is merged;
- scope and non-goals are explicit;
- the repository owner has frozen the implementation target.

Gate `G1B`, which is required before `G8` and any full authorization, passes
only when both distinct reviewer paths are real, not merely named in
CODEOWNERS. A documented reviewer vacancy is useful evidence, but it does not
satisfy `G1B`. The separate source break-glass custodian, privileged-human
authentication policy, two-authenticator evidence, recovery custody and current
access review must also be real; a paper procedure with no eligible custodian
does not pass.

`PREV7-0208` separately verifies the disaster-copy owner through GitHub actor
and destination-organization IDs, phishing-resistant 2FA policy evidence,
recovery-code custody, App installations and negative source-admin access
tests. The owner need not be a collaborator on the public source repository,
but must control the independent destination and must not share a source
administrative credential. A named vacancy or self-attestation cannot satisfy
the task.

## 13. Gate G2: Provenance, Data And Durable Storage

### PREV7-0301: Funded Retention And Recovery Objectives

The repository owner freezes a versioned production asset policy before any
production asset is accepted. For every primary, mirror, disaster, platform-
outage, checkpoint, audit/log, source-bundle and final-result class it records:

```text
custody_domain
provider_account_region
named_operational_owner_actor_id
named_payer_actor_or_organization_id
funding_reservation_receipt_digest
funded_through_utc
renewal_review_due_utc
migration_lead_time_days
minimum_required_migration_lead_time_days
migration_duration_evidence_digest
minimum_retention_until_utc
rpo_seconds_or_exact_batch_bound
rto_seconds
restore_test_frequency_days
latest_restore_test_receipt_digest
```

`minimum_required_migration_lead_time_days` is
`ceil((p95_verified_full_migration_seconds+p95_verified_restore_seconds+
maximum_incident_response_seconds+safety_margin_seconds)/86400)` from the
frozen evidence and policy named by `migration_duration_evidence_digest`.
The evidence records its measurement window, complete sample set, p95 method
and every component; a missing/stale sample set or lead time below that integer
blocks new acceptance.

The mandatory objectives are: zero data-loss RPO and `24h` RTO for canonical
final/reference assets; zero data-loss RPO and `4h` RTO for immutable audit/log
chains; at most one unacknowledged checkpoint batch per planned-job chain,
with a frozen aggregate worst case of at most `job_count` batches, and `6h`
RTO for checkpoints; and `24h` RTO for the emergency V6 package. A stricter asset-
specific value may replace these, never a weaker one.

Zero RPO applies only after the asset/event acceptance boundary. A bootstrap
event is `bootstrap_accepted` after both disjoint source-bootstrap WORM writes,
the current independent anchor and controller-handover receipt verify; that
class may satisfy only G0 through G2. It becomes `production_accepted` after
the independently owned destination WORM write, source/destination
reconciliation and fresh anchor; only that class may satisfy G3B or any later
gate. An asset is accepted only after its gate-specific required primary,
mirror, disaster-copy and external-archive publication receipts verify.
Anything earlier is `provisional_unaccepted` and cannot satisfy a gate.

The GitHub-only maintenance workflow
`.github/workflows/aurora-maintenance-retention.yml` runs with pinned
dependencies and read-only/default-deny permissions. It verifies current
funding, retention locks, payer/account identity, recovery-objective tests and
migration lead time, then emits an immutable review receipt. It cannot renew,
delete or weaken a policy by itself; each custody owner performs any approved
renewal in its own domain. A missing payer, expired funded period, missed
quarterly review, insufficient migration lead time, stale/failed restore test
or RPO/RTO breach immediately invalidates G2 and every derived authorization.
`PREV7-0301` remains the accountable readiness obligation for this recurring
control; later receipts append to its operational registry without reopening
the completed planning task.

### Licence Decision

The licence and acceptable-use reviewer authors and signs the decision; the
repository owner separately accepts its operational constraints. The immutable
`licence_review_receipt_digest` binds both actor IDs, the exact source terms,
payload/storage classes and decision bytes. It records:

- source terms reviewed;
- whether raw data may be redistributed;
- whether normalized data may be redistributed;
- whether derived features may be redistributed;
- whether trade-level, ticker-level and aggregate result files may be
  redistributed;
- whether encrypted raw, derived, checkpoint and result ciphertext may transit
  a public-repository Actions artifact, including metadata, retention,
  jurisdiction and third-party downloadability;
- whether GitHub may act as the infrastructure/data processor while licensed
  inputs are transiently decrypted in an ephemeral GitHub-hosted runner,
  including permitted regions, subprocessors, retention and incident terms;
- whether the public read-only GHCR runtime image, private Releases, external
  checkpoint object store, Actions caches, Actions artifacts and runner
  temporary disks are each permitted storage/transport classes;
- permitted visibility;
- retention obligations.

Default until approved:

```text
raw_data_visibility=private
normalized_data_visibility=private
derived_data_visibility=private
trade_detail_visibility=private
aggregate_result_visibility=private
public_actions_ciphertext_transport=unapproved
github_hosted_plaintext_processing=unapproved
```

The four-CPU public disposable architecture is legal only when
`public_actions_ciphertext_transport=approved` for every payload class it
actually carries. Encryption is not treated as automatic licence permission. If
approval is denied or ambiguous, full dispatch is `NO-GO` unless the owner has
provisioned a GitHub-hosted private larger-runner pool with at least four
effective CPUs, 15,000 MiB usable memory and the required measured concurrency,
then rerun all capacity, security, cost and equivalence evidence for that exact
private topology. Standard private two-CPU runners are never silently
substituted into the four-worker plan.

Every GitHub-hosted topology, public or private, additionally requires
`github_hosted_plaintext_processing=approved` for the exact licensed payloads
mounted inside the runner. If that decision is denied or ambiguous, this
GitHub-only project has no compliant scientific execution topology and remains
`NO-GO`; ciphertext transport approval cannot cure unapproved plaintext
processing.

### PREV7-0309: GitHub Actions Acceptable Use And Pricing

Technical capacity does not imply permission to consume it. Before G2 can pass,
the independent licence and acceptable-use reviewer records a versioned
preliminary decision and maximum workload envelope:

```text
github_actions_acceptable_use=approved|denied|ambiguous
terms_url
terms_version_or_retrieved_at_utc
terms_document_sha256
reviewer_actor_id
reviewed_workload_envelope_digest
repository_visibility
runner_class
maximum_concurrent_jobs
source_control_reserve_when_shared
destination_control_reserve_when_shared
capacity_limit_source_and_receipt_digest
environment_required_reviewer_capability_receipt_digest
maximum_runner_minutes
scientific_workload_purpose
public_repository_development_test_nexus
support_case_id
support_response_digest
billing_domain_manifest_digest
external_control_plane_terms_decision_digest
```

The reviewed workload description includes the `360`-job capacity target,
scientific computation, expected duration, artifact/Packages traffic, retries,
disposable repository, visibility and whether the work is reasonably connected
to development, testing and validation of Aurora. It distinguishes GitHub
Actions product terms and acceptable-use restrictions from provider-data
licences and from technical service limits.

`CAPACITY_TOPOLOGY` must be selected before G2. A current API/plan/Support and
bounded-smoke receipt proves either `360` scientific jobs with source and
destination control in independently reserved pools, or
`maximum_concurrent_jobs >= 360 + source_control_reserve_when_shared +
destination_control_reserve_when_shared`. The same receipt proves that the
chosen repository visibility/plan supports every required environment reviewer
and protection used by this plan. A lower, unknown, stale or merely advertised
limit selects `NO-GO`; G6A cannot begin under an improvised lower-concurrency
topology.

The same reviewer separately approves the selected external deadman, key-
broker, registry, monitoring and immutable-log providers, accounts, regions,
metadata classes, retention, subprocessors, security terms and pricing. The
destination object-storage provider receives scientific ciphertext and is
reviewed separately for that exact payload, licence, jurisdiction, encryption,
object-lock, deletion and pricing policy. The source checkpoint handoff store is
another explicit billing/control domain with its exact ciphertext class,
write-once/one-use IAM, retention, size ceiling, deletion and pricing policy.
Deadman/control services receive no
scientific payload. A missing or ambiguous external-control-plane or platform-
outage-storage decision remains `NO-GO` even if GitHub Actions itself is
approved.

The preliminary billing-domain manifest has one row for every independently
billed source, disposable execution, destination, storage, Packages, transfer,
deadman service, key broker, external lease registry, monitoring and immutable-
log domain. Each row freezes account/organization, prospective payer actor,
plan, visibility, runner/service class, native ISO 4217 currency, current
pricing snapshot/validity, tax/fee policy and maximum native minor-unit
category/total envelope. An already existing repository uses its immutable ID.
A repository not yet created uses `repository_id=null` plus an immutable
organization/account ID, content-addressed template digest, intended
visibility, unique campaign-purpose selector and the task that must resolve its
real ID before any spend. A null repository ID can approve only the preliminary
maximum envelope, never a smoke or full dispatch.

Source and destination owner approval receipts are intentionally absent at this
preliminary stage. `PREV7-0710` and `PREV7-0712` approve the exact smoke domains
after `PREV7-0711` resolves the G7-validation-repository ID; `PREV7-0713` approves
their consolidated cap. The full campaign repository ID is resolved by
`PREV7-0808`; `PREV7-0810` freezes its execution commit, `PREV7-0811` and
`PREV7-0812` approve exact full source/destination domains, and `PREV7-0813`
reconciles and reserves them before destination copy or runbook construction.
Those receipts are frozen into the runbook core before `PREV7-0809`
exact-workload acceptable-use approval. A separate consolidated budget
currency, conservative dated FX
snapshot and safety reserve produce a total cap without replacing any native-
domain cap. Missing, unresolved-at-dispatch or cross-subsidized domains are
forbidden.

If the current terms make the public or private GitHub-hosted workload
prohibited, the decision is `denied`. If interpretation remains material or
ambiguous, obtain a written GitHub Support response for the exact account,
repository visibility, runner class and workload; until then the decision stays
`ambiguous`. `denied` or `ambiguous` is immediate `NO-GO`. A later terms,
pricing, plan, visibility, runner-class or workload change invalidates the
decision and every derived capacity/cost approval.

This is not the final exact-workload approval. `PREV7-0809` later proves that
the immutable `runbook_core.json` workload is a subset of this envelope and
obtains a fresh reviewer receipt on that exact core digest.

### Reproducibility Classification

Allowed V6 classifications:

```text
fully_reproducible
result_preserved_inputs_incomplete
historical_reference_only
```

If the exact original inputs are missing, the project must not label a newly
downloaded snapshot as the original V6 dataset.

The classification is carried unchanged into every scientific asset manifest,
runbook core and final summary:

| Classification | Required state |
|---|---|
| `fully_reproducible` | Complete authenticated V6 dependency chain, `reuse_recovered_v6_inputs=true`, Oracle B exact and `v6_historical_reproduction_confirmed=true` |
| `result_preserved_inputs_incomplete` | Final V6 result preserved but one or more named dependency layers missing; Oracle B unavailable and no rerun-reproduction claim |
| `historical_reference_only` | Preserved historical result or separately named reference proposal only; it cannot serve as this V7 campaign's baseline or green G5/G6A/G7 |

`optimized_vs_reference_equivalence_confirmed` answers only whether two engines
agree on the same current inputs. It never substitutes for
`v6_historical_reproduction_confirmed`. A contradictory combination, unnamed
missing layer or unavailable Oracle B paired with a V6-reproduction claim
blocks G5, G6A, G7 and full authorization.

```text
oracle_b_status=exact_match|mismatch|unavailable_missing_original_inputs
missing_v6_dependency_layers=sorted unique subset of C,D0,D1,D2,D3,S,R
```

`oracle_b_status=mismatch` is always blocking; it cannot be downgraded to a new
reference without a separate investigated scientific decision and identity.

### Promote The Emergency V6 Archive

`PREV7-0304` does not upload a second unnecessary copy of the artifact.

It:

1. validates the emergency package against the approved licence and manifest
   policy;
2. adds any missing metadata or attestation;
3. changes its registry status from `emergency` to `canonical`;
4. republishes only if the emergency package fails the production policy;
5. preserves the original digest and audit trail.

### PREV7-0305: Production Clean-Runner Restore

This task restores the complete `PREV7-0304` production manifest separately
from each then-required custody copy. Each attempt starts on a fresh
GitHub-hosted runner and freezes:

```text
asset_manifest_digest
expected_object_ids_and_versions
expected_payload_and_internal_file_digests
primary_copy_identity
mirror_copy_identity
restore_source_selected
denied_nonselected_source_identity
runtime_and_workflow_digests
restore_started_at_utc
restore_completed_at_utc
restore_duration_seconds
restore_rto_seconds
```

The primary-source attempt denies mirror credentials; the mirror-source
attempt denies primary credentials. Both reconstruct every manifest object,
verify byte-for-byte payload and internal-file equality, reject an extra,
missing, truncated, reordered or digest-mismatched object, and publish
OIDC/workflow-attested private restore reports plus an allowlisted public
receipt. A separate signature is optional until its mechanism is tested. The clean runner
has no pre-existing cache or local copy and cannot fall back to another source.
The task closes only when both attempts pass inside the approved RTO and their
reconstructed set digests are identical. Failure, timeout or accidental access
to the denied source keeps G2 red and triggers the manifest-bound rollback to
the last independently restored production package.

The shared read-only App does not weaken this test: each attempt receives only
one reduced token bound to one repository installation, and the protected
broker/controller policy for that attempt is unable to select the denied
installation. Negative fixtures request the other installation and must fail
before token mint; the runner never receives an App private key or reusable
broker identity.

### V6 Input Identity Or Separate Reference Proposal

`PREV7-0307` makes an explicit binary decision:

```text
reuse_recovered_v6_inputs=true
```

only when the complete V6 input chain is restored and authenticated. Otherwise
it records `reuse_recovered_v6_inputs=false`, emits a
`new_reference_proposal.json` under a distinct product/campaign identity and
keeps `G2`, `G4`, `G5`, `G6A`, `G3B`, `G6B`, `G7`, `G8`, `G9`, `G9X` and
`G10` red, then activates `NO_GO_CLOSE-n`. It may gather the following
requirements for that future separate plan, but it does not download, designate
or approve a replacement V7 snapshot here:

- provider;
- retrieval cutoff;
- universe source;
- `universe_temporal_model=point_in_time|static_post_period`;
- point-in-time membership, eligibility, market-cap, listing and delisting
  effective timestamps, provider publication timestamps and per-fact
  `available_at_utc` when the mode is `point_in_time`;
- explicit `survivorship_biased_reference=true` and prohibited claims when the
  recovered V6 mode is `static_post_period`; this mode requires
  `exact_universe_identity_digest` and permits
  `observation_timestamp_state=unknown_unverifiable` when no authenticated
  observation timestamp exists, without making a causal or historical-
  knowability claim;
- immutable `instrument_id`, exchange/listing identity, source symbol and
  versioned alias/normalization manifest;
- delisted policy;
- prices and corporate-action adjustments;
- `price_data_vintage_utc`, the latest source-byte vintage represented in the
  snapshot;
- `source_event_cutoff_utc`, the overall latest event-knowledge timestamp
  present, as RFC 3339 or `unknown_unverifiable`;
- `adjustment_temporal_model=as_known_each_session|retrospectively_adjusted_reference`;
- a corporate-action knowledge manifest with event type, effective date,
  provider publication/knowledge timestamp when authenticated or null plus
  `observation_timestamp_state=unknown_unverifiable` in the retrospective
  reference, source vintage and applied transform for every split, dividend or
  correction;
- currency treatment;
- calendars;
- exchange timezone, session open/close UTC and half-session/DST policy;
- per-observation `available_at_utc` when the selected temporal model requires
  authenticated availability; otherwise a null timestamp plus
  `observation_timestamp_state=unknown_unverifiable`;
- `decision_time_policy_digest` defining each symbol's signal
  `decision_cutoff_utc`;
- `cross_market_alignment_model=v6_calendar_date_reference|causal_asof_utc`;
- first and last allowed dates;
- schema;
- code SHA;
- dependency lock;
- per-file hashes.

The global universe authority is registered `exact_universe_identity_v1`:

```text
schema_version
universe_id
universe_temporal_model
observation_timestamp_state
source_event_cutoff_utc
instrument_alias_and_listing_manifest_digest
membership_and_eligibility_policy_digest
ordered_instruments[
  universe_ordinal,
  canonical_instrument_id, source_symbol_identity,
  market_mic, listing_currency,
  listing_effective_date_or_null, delisting_effective_date_or_null,
  ordered_membership_intervals[
    first_session_date, last_session_date, membership_state,
    source_fact_digest, available_at_utc_or_null
  ]
]
instrument_count
exact_universe_identity_digest
```

Universe ordinals are contiguous from zero under the frozen V6 source-universe
order. Membership intervals are non-overlapping, maximal adjacent equal-state
runs and cover every session represented by that instrument. A
`static_post_period` reference records the exact static membership with
unverifiable availability as null and
`observation_timestamp_state=unknown_unverifiable`; it cannot fabricate
historical knowledge. A `point_in_time` identity requires authenticated
availability no later than every applicable decision cutoff.

The object uses `GTBI_EXACT_UNIVERSE_IDENTITY_V1`, `self_field` storage and
omits only its own digest. Alias/listing normalization is a referenced,
versioned child object, not an implicit ticker transform. Changing order,
identity, listing, membership interval, source fact, availability, temporal
mode or cutoff changes the digest and invalidates every dependent snapshot and
reuse key.

The three data identities are distinct and have one normative relationship:

```text
historical_execution_pack_digest =
  SHA-256 of the canonical content-addressed historical execution-pack bytes,
  excluding the outer data manifest and data-snapshot identity object

data_manifest_digest =
  HASH[GTBI_DATA_MANIFEST_V1] over data_manifest_v1

data_digest =
  HASH[GTBI_DATA_SNAPSHOT_V1] over data_snapshot_identity_v1
```

The historical execution-pack byte stream is exact and archive-format
independent. It is:

```text
ASCII("GTBI-HISTORICAL-EXECUTION-PACK-V1\0")
for each ordered_partition_members row in canonical partition_id order:
  uint32_be(len(utf8(logical_path)))
  utf8(logical_path)
  uint64_be(byte_size)
  exact raw file bytes
```

`logical_path` is NFC-normalized UTF-8 with `/` separators, is relative,
contains no empty, `.` or `..` component and is unique. Directories, symlinks,
hard links, alternate streams and unmanifested members are forbidden. The
encoded `byte_size` must equal both the manifest value and the following raw
byte count. `historical_execution_pack_byte_length` is the length of this
complete framed stream, including magic, path lengths, paths and byte-length
fields. The SHA-256 is calculated incrementally over that exact stream; ZIP,
tar, transport compression, filesystem traversal order, timestamps and file
permissions never enter its identity. A parser must consume exactly the
declared member count and reject trailing bytes.

`data_manifest_v1` contains exactly:

```text
schema_version
historical_execution_pack_digest
historical_execution_pack_byte_length
ordered_partition_members[
  partition_id, partition_scheme_id, partition_axis_and_bounds,
  logical_path, schema_version, byte_size, row_count,
  content_sha256, minimum_session_date, maximum_session_date,
  instrument_set_digest
]
exact_universe_identity_digest
universe_temporal_manifest_digest
instrument_alias_and_listing_manifest_digest
price_data_vintage_utc
source_event_cutoff_utc
observation_timestamp_state
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
calendar_policy_sha256
currency_policy_sha256
historical_min_observation_date
historical_max_observation_date
historical_exclusion_start
data_manifest_digest
```

It uses `GTBI_DATA_MANIFEST_V1`, `self_field` storage and omits only
`data_manifest_digest` from its typed preimage. The historical execution-pack
digest is a `raw_bytes` reference with exact byte length. Every other digest or
SHA field has the registered reference type required by section 9.

`data_snapshot_identity_v1` contains exactly:

```text
schema_version
data_manifest_digest
historical_execution_pack_digest
historical_execution_pack_byte_length
ordered_partition_members[
  partition_id, partition_scheme_id, partition_axis_and_bounds,
  logical_path, schema_version, byte_size, row_count,
  content_sha256, minimum_session_date, maximum_session_date,
  instrument_set_digest
]
exact_universe_identity_digest
universe_temporal_manifest_digest
instrument_alias_and_listing_manifest_digest
price_data_vintage_utc
source_event_cutoff_utc
observation_timestamp_state
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
calendar_policy_sha256
currency_policy_sha256
historical_min_observation_date
historical_max_observation_date
historical_exclusion_start
data_digest
```

The snapshot uses `GTBI_DATA_SNAPSHOT_V1`, `self_field` storage and omits only
`data_digest` from its typed preimage. The manifest and snapshot carry the same
historical execution-pack digest and byte length.
Both partition arrays are sorted by `partition_id` under the canonical
serialization profile and are exhaustive: an extra, missing or reordered
partition, changed byte, universe/vintage/policy field or execution-pack byte
changes `data_manifest_digest` and `data_digest`. The snapshot's partition and
scientific-identity fields, including `data_manifest_digest`, must equal the
exact projection of the complete registered data manifest. The stored snapshot
adds only its `data_digest` self field, which is absent from its typed preimage,
avoiding recursion. Every FeatureStore key, unit, checkpoint, runbook, merge
and result uses this same typed `data_digest`; neither component digest alone
is accepted as its substitute.

Each partition row also has a non-circular typed child identity:

```text
instrument_identity_set_v1:
  schema_version
  set_scope=partition
  parent_exact_universe_identity_digest
  ordered_instrument_identities[
    canonical_instrument_id, source_symbol_identity,
    market_mic, listing_currency
  ]
  instrument_count
  instrument_set_digest

input_partition_manifest_v1:
  schema_version
  data_manifest_digest
  historical_execution_pack_digest
  partition_id
  partition_scheme_id
  partition_axis_and_bounds
  logical_path
  partition_schema_version
  byte_size
  row_count
  content_sha256
  minimum_session_date
  maximum_session_date
  instrument_set_digest
  input_partition_manifest_digest

input_partition_manifest_set_v1:
  schema_version
  data_digest
  ordered_entries[partition_id, input_partition_manifest_digest]
  partition_count
  input_partition_manifest_set_digest
```

Each partition's instrument set is sorted by the frozen canonical instrument
ordering, contains exactly the instruments whose rows are physically present
in that partition and uses `GTBI_INSTRUMENT_IDENTITY_SET_V1`, omitting only
`instrument_set_digest`. The same instrument may appear in only the explicitly
approved temporal/physical partition dimensions; duplicate physical ownership
for the same session row is forbidden. Its parent universe digest prevents a
partition-local symbol spelling from becoming a new scientific identity.
`partition_scheme_id` selects one reviewed physical scheme and
`partition_axis_and_bounds` is a typed discriminated union for its symbol,
session-date or hybrid bounds. Across all members, the row-key sets are
pairwise disjoint and their union equals the historical execution-pack row set
exactly. The daily row key is
`(canonical_instrument_id,source_symbol_identity,market_mic,session_date)`;
the source schema must reject a duplicate key before partitioning.
Minimum/maximum dates are summaries, not ownership rules.

The partition child omits only its own digest and uses
`GTBI_INPUT_PARTITION_MANIFEST_V1`; it deliberately does not contain
`data_digest`, because the parent snapshot already hashes the source row. The
set is created only after `data_digest`, uses
`GTBI_INPUT_PARTITION_MANIFEST_SET_V1` and omits only its own digest. Its entries
must be the exact ordered projection of `ordered_partition_members`; every
child's repeated fields must equal that parent row byte-for-byte. This gives
workers a verifiable child reference without changing or recursively defining
the authoritative data identity.

Every worker receives the same content-addressed bytes.

The requirements above are mode-conditional, not contradictory. Authenticated
per-observation `available_at_utc` is mandatory only for
`point_in_time`, `as_known_each_session` and `causal_asof_utc` claims. A named
`static_post_period` or `retrospectively_adjusted_reference` may preserve the
exact recovered reference without inventing timestamps; every unavailable
timestamp is encoded as `observation_timestamp_state=unknown_unverifiable`,
the exact static-universe/vintage digest remains mandatory, and all causal,
point-in-time, survivorship-free and historical-knowability claims are forced
false. A mixed manifest cannot use the retrospective exception for one field
while claiming causal status for the aggregate result.

In `point_in_time` mode every universe, listing, delisting, eligibility and
market-cap fact consumed by a decision satisfies:

```text
fact_effective_at_utc <= decision_cutoff_utc
fact_available_at_utc <= decision_cutoff_utc
```

Same-date publication is insufficient when it occurred after that exchange's
decision cutoff. Missing availability is not imputed. Fixtures cover
publication before and after the close on the same civil date, exchange time
zones, delayed delisting knowledge and market-cap revisions.

Observation time and knowledge time are separate boundaries. A bar dated on or
before `2020-12-31` can still be contaminated by a split, dividend, delisting
or provider revision learned later, including one learned before 2021 but
after the strategy's decision session. In `as_known_each_session` mode, every
value exposed to a decision at session `t` may consume only events whose
authenticated knowledge timestamp is no later than that decision timestamp.
`source_event_cutoff_utc` is only a snapshot-wide ceiling and never substitutes
for this per-session inequality. In
`retrospectively_adjusted_reference` mode, retrospective adjustments are
allowed only to reproduce a named historical reference; the manifest sets
`historical_adjustment_vintage_contaminated=true`, the result is labelled
historical/exploratory, and no point-in-time or pristine historical-data claim
is permitted. If event knowledge timestamps cannot be authenticated, the
cutoff is `unknown_unverifiable`, retrospective mode is mandatory and the same
prohibited claims apply. The mode, source vintage and contamination flag are
never inferred from the absence of post-2020 rows.

`as_known_each_session` requires
`corporate_action_knowledge_coverage_pct=100`,
`historical_adjustment_vintage_contaminated=false` and
`adjustment_point_in_time_claim_allowed=true`. Retrospective mode always sets
the last field false and reports measured knowledge coverage rather than
silently treating unknown events as timely.

Cross-market observation availability is independent from corporate-action
knowledge. In `causal_asof_utc` mode, every stock decision uses an as-of
backward join satisfying:

```text
benchmark_or_fx_available_at_utc <= decision_cutoff_utc
```

The contract freezes exchange time zones, session close, publication delay,
DST, half sessions, holidays and non-overlapping trading days. Same-calendar-
date SPY close is unavailable to a Tokyo or London decision if its
`available_at_utc` is later. No forward fill may cross an unapproved staleness
limit.

Oracle B first authenticates how V6 aligned global stocks, SPY and FX. If V6
used calendar-date joins, V7 Performance preserves that exact reference
behavior for equivalence but sets
`cross_market_temporal_contaminated=true`,
`cross_market_alignment_model=v6_calendar_date_reference` and
`causal_cross_market_claim_allowed=false`. It may not describe the result as a
causal point-in-time global backtest. A corrected
`causal_asof_utc` evaluation is a separately named scientific identity and
cannot replace the frozen V6 baseline inside this performance-only V7.

The one aggregate causal field has this exact formula:

```text
historical_causal_claim_allowed =
  no_lookahead_confirmed
  AND universe_point_in_time_claim_allowed
  AND adjustment_point_in_time_claim_allowed
  AND causal_cross_market_claim_allowed
  AND universe_temporal_coverage_pct=100
  AND corporate_action_knowledge_coverage_pct=100
  AND rows_on_or_after_historical_exclusion_start=0
  AND locked_rows_loaded=0
```

Any false, unknown or missing conjunct forces `false`. Tests enumerate every
single-false and missing combination. V6 reference equivalence cannot set this
field true merely because it reproduces the old result.

The historical execution pack is physically bounded:

```text
max_observation_date=2020-12-31
rows_on_or_after_2021_01_01=0
```

Recovered raw inputs may be archived unchanged for provenance, but they are
never mounted directly into V7 workers. A verified preparation job creates the
historical-only pack and records source and output digests. Any future forward
data lives in a different package namespace, manifest and protected
environment with credentials unavailable to historical workflows.

### Snapshot Integrity Contract

Before a recovered authenticated V6 snapshot can enter this plan's oracle,
benchmark or smoke, a
GitHub workflow emits `snapshot_integrity_report.json` and proves:

- the manifest schema, partition set, file sizes, row counts and per-file
  hashes are complete and no unmanifested file is present;
- every row has an immutable `instrument_id` derived under a versioned schema
  from provider instrument/listing identity, exchange MIC or frozen equivalent
  and effective listing interval; source/normalized symbols are aliases only;
- `(instrument_id, session_date)` is unique at the declared row grain, while a
  fixture with the same ticker on two exchanges remains two instruments;
- dates use the frozen timezone and session-calendar policy, are ordered within
  each instrument and stay inside the declared historical boundary;
- every row has authenticated exchange/session identity, `session_open_utc`
  and `session_close_utc`; `available_at_utc` is required and authenticated only
  for point-in-time/as-known/causal modes, while a static or retrospectively
  adjusted reference requires null plus
  `observation_timestamp_state=unknown_unverifiable`; causal mode
  proves every benchmark/FX as-of join is backward at the decision cutoff,
  including Tokyo, London, New York, DST, half-day, holiday and publication-
  delay fixtures;
- required OHLCV and corporate-action fields have the exact frozen dtypes;
- finite OHLC prices are positive, `high` is not below open, close or low,
  `low` is not above open, close or high, and volume is non-negative;
- missing, stale, suspended and zero-volume observations are classified by the
  frozen policy rather than silently filled;
- split, dividend and adjusted-price transformations reconcile to their source
  events within the contract's exact tolerance;
- every applied corporate-action or revision has a source vintage. Under
  `as_known_each_session`, its authenticated event-knowledge timestamp is
  mandatory and an event learned after the session whose decision value it
  changes is rejected. Under `retrospectively_adjusted_reference`, that
  timestamp may be null only with
  `observation_timestamp_state=unknown_unverifiable`; event type, effective
  date, transform and source vintage remain mandatory, and the manifest sets
  `historical_adjustment_vintage_contaminated=true` plus the corresponding
  prohibited-claims classification;
- currency identity and any conversion series, timestamp and lag are explicit;
- universe membership, aliases, cross-listings, delisted handling and the
  benchmark symbol match the frozen universe manifest;
- the universe temporal model is singular and complete: `point_in_time` proves
  every eligibility input was knowable on its effective session, while
  `static_post_period` proves exact V6-universe identity and labels every
  result `survivorship_biased_reference`;
- every partition reports first date, last date, symbol count, missingness,
  duplicate count, invalid-row count and source-to-normalized row reconciliation;
- each symbol's genuine source-history end and artificial historical-pack
  truncation flag reconcile to the source manifest for provenance; unknown is
  explicit and no classification changes the frozen V6 terminal-frame rule;
- the historical execution pack has zero rows after `2020-12-31`.

Any proposed difference between recovered V6 inputs and a future separately
created snapshot is specified in `snapshot_difference_report.json`. A
difference never inherits the V6 identity and cannot be executed or accepted
under this plan; it requires its own approved product/campaign plan.

### PREV7-0308: Independent Destination Foundation

After G2 and `PREV7-0208`, but before destination deadman deployment or any G7
fault/transport smoke:

1. Before any destination resource or charge, register the independent
   `destination_account_root_custodian` and
   `destination_billing_payer_authorizer` with recovery/succession evidence.
   Then create a private GitHub destination repository in a different organization
   or account with an independent owner, immutable repository ID, phishing-
   resistant 2FA and separately held recovery codes. Register the distinct
   destination break-glass custodian, succession policy and quarterly total-
   owner-loss recovery test.
2. Review the data licence for that exact destination, storage topology and
   jurisdiction.
3. Establish destination-owned protected environments, storage namespaces,
   including a non-GitHub immutable/versioned object-lock archive, attestation
   trust, external lease registry and key-broker account controlled exclusively
   by destination roles. No source owner, App, workflow or recovery code can
   mint destination write/delete credentials.
4. Add destination storage, control plane, key broker, registry, monitoring,
   logs, backup and transfer as explicit billing domains, even when a current
   rate is zero.
5. Freeze the destination organization/repository IDs, owner actor ID,
   break-glass identity, protected workflow roots, OIDC trust policy and
   ownership manifest.
6. Disable automatic deletion and mutable overwrite, prove source actors cannot
   alter the destination, restore a bounded synthetic object while the source
   organization is denied, and separately restore from the non-GitHub archive
   while all GitHub asset/package/release reads are denied.
7. Pull the complete bootstrap task/gate/attempt event chain into destination
   WORM, preserve byte order and digests, publish the current independent
   anchor and reconcile source/destination heads. Only events with both WORM
   copies and that anchor are production-accepted for G3B/G8.

`PREV7-0308` therefore requires current
`required_approver_roles=[destination_account_root_custodian,
destination_billing_payer_authorizer]` receipts in addition to its accountable
destination owner. Neither approver may be a source-domain actor.

This foundation deliberately does not claim that final V7 dependencies already
exist. `PREV7-0611` deploys and proves the destination deadman/reaper against
this foundation; `PREV7-0708` uses it for the full-scale synthetic transport
smoke.

### PREV7-0310: Final Dependency Copy And Total-Loss Restore

After G7 and `PREV7-0800` have produced the exact merged V7 identity and
`PREV7-0808` has created/frozen the disposable execution repository,
`PREV7-0810` has created its exact execution commit and `PREV7-0811` through
`PREV7-0813` have authorized every exact full billing domain, but before the
evidence bundle or final G8 authorization:

1. From the destination organization, pull every pre-authorization dependency
   by immutable allowlisted digest with temporary source read access, then
   revoke that access. A source-push workflow is not the trust anchor.
2. Copy without changing payload bytes: complete canonical source bundle and
   protected tags, complete disposable execution repository bundle/commit and
   installation receipts, historical execution pack, data and strategy packs, runtime OCI
   manifest and every layer, dependency lock, wheelhouse, SBOM, provenance
   attestations, vulnerability report/database identity, contracts, execution
   plans, schemas and pre-authorization audit evidence.
3. Seal the same content-addressed dependency set into the destination-owned
   non-GitHub compliance-mode object-lock archive and record provider object
   versions, minimum `retain_until_utc`, legal-hold state, retention-policy
   digest and a complete manifest digest. The manifest also binds server-side
   encryption mode and, for every customer-managed KMS/SSE key, provider,
   account, immutable key/version ID, independent key administrator,
   deletion-protection state and a key `retain_until_utc` no earlier than the
   last protected object. Storage administrators cannot administer those keys.
   Before authorization, maximal key administrators must fail to disable,
   delete, schedule deletion or shorten key retention; rotation rewraps or
   re-encrypts without changing the authenticated plaintext digest and both old
   and new versions restore before retirement. Neither source nor destination
   administrator can delete, overwrite, purge versions, remove the lock or
   shorten retention during the protected interval; current negative
   authorization receipts prove every operation fails.
4. Freeze an inventory and ownership manifest binding the destination IDs,
   protected destination workflow path and full SHA, OIDC
   issuer/subject/audience, attestation policy and every signing/key-custody
   receipt. A login string alone is not a trust root.
5. Prove through a negative authorization test that source administrators and
   source Apps cannot alter, re-tag or delete the destination copy.
6. Restore on a clean GitHub runner while denying access to the primary
   organization and both source-owned Release repositories; verify every reconstructed
   payload, OCI layer and internal file digest.
7. Restore the same set from the non-GitHub archive while all GitHub asset,
   package and release reads are denied, then compare the complete reconstructed
   digest.
8. Repeat both total-primary-loss restores before every full authorization and at
   least quarterly while canonical assets remain active.
9. During an approved full, the destination asynchronously pulls each sealed
   checkpoint microbatch by immutable digest and emits an append-only receipt
   chained to the previous destination receipt. Recovery accepts source or
   destination bytes only after verifying the same checkpoint identity and
   digest.

“Temporary source read access” is implemented by a destination-owned
`gtbi-dependency-extract` GitHub App whose private key is generated/imported
only after the destination broker exists and remains there. `PREV7-0204`
freezes only its keyless proposed definition and repository-class request.
During `PREV7-0308`, the destination App manager creates/attests the App,
securely imports its GitHub-generated private key into the destination broker
under the destination key-custodian receipt, and the source owner installs it only on
the exact canonical code and private asset repositories named in a frozen
repository-class manifest. Per class it receives only the unavoidable read
permissions (`Metadata: read`, `Contents: read`, and, only where required,
`Actions: read` or `Packages: read`); it has no write, administration,
environment, secret, issue, workflow-dispatch or organization permission. The
destination workload requests a broker-mediated fixed read operation whose
internally held installation token lasts at most ten minutes and is bound to
exact repository IDs, immutable refs/object IDs, API methods/endpoints, byte
ceilings and manifest digest. The broker performs every call and returns only
bytes plus an attested receipt; no workflow, host, container or protected
environment receives a reduced token, and the source never receives a
destination credential. The
installation is suspended by default, activated for one extraction lease,
re-suspended immediately and uninstalled after the final dependency copy.
Positive tests restore every repository class. Negative tests deny list/read
outside selected repositories, mutable refs, unrelated runs/artifacts/packages,
all writes, token reuse after expiry/suspension and access after uninstall.
`gtbi-dependency-extract` is distinct from the campaign checkpoint replicator
and cannot consume campaign artifacts.

GitHub grants `actions:read` at repository level; run IDs and artifact-name
prefixes are validation rules, not a permission boundary. Therefore the full
campaign runs in a new disposable source execution/transport repository
containing no unrelated workflow, run or artifact. Its visibility and runner
class are the exact licence-approved topology; public standard Linux is the
preferred case and private four-CPU larger runner is the sole fallback. It is created
from a reviewed content-addressed template, binds the approved Aurora code SHA
and runbook core, denies ordinary collaborators, disables issues/discussions/
wiki, permits only reviewed full-commit-SHA-pinned allowlisted Actions, and is
frozen before capsule consumption. Its workflows have no `pull_request`,
`pull_request_target`, `push` or public-input dispatch path; only the protected
capsule-consumption controller can create the approved run. Forks cannot receive
source environments, installation tokens or accepted evidence. The
destination-owned replicator App is installed only on that
repository with short-lived `actions:read`. It has no source write permission
and no destination credential is disclosed to the source. Every API response
must additionally match the allowlisted campaign run IDs, artifact-name prefix,
workflow SHA and artifact digest, but those checks are defence in depth. The
installation is created and verified in `PREV7-0808`, then remains suspended
and tokenless until capsule consumption activates its exact lease. Completion,
expiry finalizers and the destination-owned deadman/reaper suspend it, and its
API access log is reconciled against the planned microbatch inventory.
Repository deletion is allowed only after
dual-copy final restore, checkpoint reconciliation, credential revocation and
an owner-approved cleanup receipt; retention expiry is the fail-safe.

`PREV7-0807` performs the second phase after authorization: the destination
pulls the immutable runbook core, authorization envelope, all approval/current-
state receipts and final evidence bundle, restores them without primary access
and issues a destination-owned attested sync receipt. The protected destination
workflow then constructs, attests and durably stores the non-circular
`dispatch_capsule.json`; the source only restores, verifies and retains
identical bytes. Its GitHub OIDC claims, workflow SHA, repository/owner IDs,
payload digests and optional signature must match the trust root frozen by
`PREV7-0308`. The capsule contains only the authorization-envelope digest,
disaster-sync receipt digest, campaign/tag/SHA, creation time and bounded
expiry. The full can start only from that capsule. During execution the
destination replicates checkpoints and receipts; G9 adds block/final manifests,
canonical results and audit evidence after they exist.

An owner name in a document is insufficient; GitHub API evidence must prove
the independent account, repository, permissions, protection and restore run.

### Transfer Efficiency

Do not make every worker download a complete large data lake.

Partition by stable scientific unit:

```text
shared benchmark data
shared metadata
symbol partitions
feature partitions when scientifically equivalent
```

A worker downloads only required partitions. Partitioning must not change
cross-sectional calculations or relative-strength inputs.

The planner benchmarks three exact physical layouts over the same immutable
representative batch:

```text
candidate_major:
  few canonical candidates x every required symbol partition

symbol_major:
  every required canonical candidate/simulation group x few symbol partitions

hybrid:
  bounded candidate/simulation groups x bounded symbol partitions
```

The scientific unit remains one complete canonical strategy over the complete
frozen universe. Candidate/symbol tiling is only a physical execution layout.
It is permitted because GTBI has no shared-capital portfolio state and each
symbol's position state is independent after its market, relative-strength and
cross-sectional inputs are frozen. Any cross-sectional calculation is computed
once from the full authenticated date cross-section and partitioned only after
that exact result exists.

Each physical tile binds the scientific context, an ordered set of canonical
unit ordinals, an ordered set of symbol-partition IDs and the exact Cartesian
candidate-symbol pair-set digest. It emits per-symbol trade fragments with
original symbol ordinal and per-symbol trade ordinal. The deterministic
reducer requires every planned pair exactly once, rejects overlap or omission,
and reconstructs V6 order `symbol_ordinal, trade_ordinal` before drawdown,
ranking, top/bottom-trade selection or any order-sensitive metric. No fragment
may be filtered, ranked or declared a terminal candidate result. A canonical
unit becomes terminal only after all its fragments reconcile and its complete
metrics match the reference.

This layout choice is made by cold end-to-end benchmark, including bytes
transferred, feature work, fragment serialization and merge. The planner may
select candidate-major when transfer is cheap, symbol-major when common data/
features dominate, or hybrid when output/merge pressure dominates. It may not
assume one layout is faster and may not change layout after the execution plan
is authorized.

Evaluation code never calls Tiingo, Yahoo, a broker, a provider API or any live-data
endpoint. All scientific bytes are staged and verified before the worker
subprocess starts; asset credentials are then removed. Contract tests replace
network clients with a fail-closed stub so an accidental provider request
fails the job instead of changing the dataset.

Gate G2 passes only when:

- primary GitHub storage exists and restores successfully;
- the owner-reviewed licence decision and owner acceptance are recorded;
- preliminary GitHub Actions acceptable-use decision is `approved` for the
  maximum workload envelope and its terms/pricing and billing-domain manifests
  are current;
- `CAPACITY_TOPOLOGY` has a current receipt proving the exact 360-job
  scientific capacity, any shared control reserves and every required
  environment-review capability for the selected visibility/plan;
- restoration from scratch succeeds;
- data identity is complete;
- V6 reproducibility classification is approved.

`PREV7-0308` makes the independently administered destination foundation real
before G7 testing, so G7 never depends on promised infrastructure. It records
owners, immutable destination IDs, custody and authentication boundaries and
proves a synthetic restore. `PREV7-0310` is the distinct post-G7 task that
copies every final pre-authorization dependency and proves total-primary-loss
restoration. Only `PREV7-0310` can satisfy the G8 dependency-copy requirement.

## 14. Gates G3A And G3B: GitHub Governance

### Main Protection In Two Stages

Stage 1, while only one collaborator exists:

- pull request required;
- a minimal required-check set is enabled only after each exact check name,
  source App and current-main result are proven available and green;
- required approvals set to zero;
- force-push blocked;
- branch deletion blocked;
- conversations resolved;
- branch updated before merge.
- administrator enforcement enabled and every App, deploy-key and actor bypass
  removed for the protected branch; emergency recovery changes the reviewed
  ruleset explicitly rather than silently bypassing it.

Stage 2, after a reviewer exists:

- one approval required;
- CODEOWNERS review required;
- stale approvals dismissed;
- last-push approval required when supported;
- critical gates use ruleset-required workflows sourced from protected `main`
  when supported; otherwise each required status is bound to the expected
  GitHub App and reconciled to the reviewed workflow digest;
- changes to `.github/workflows/`, Actions policy or required-check
  configuration require workflow CODEOWNER approval and cannot be approved by
  their author;
- `gtbi-v7-full-*` tags protected from update and deletion;
- ruleset bypass list empty for normal actors and workflows.

Never enable a rule that leaves no eligible approver.

Stage-one protection cannot require a missing or currently irreparable legacy
check and cannot use a bypass to disguise failure. Bootstrap checks cover plan
structure, workflow security and package integrity. As CI failures are fixed,
required coverage increases; a check rename uses an audited add-new,
prove-green, remove-old migration. Before stage two and G7, the full
non-waivable GTBI check set is required and green on the exact merge SHA.
Stage-one status checks are accepted only from the expected immutable workflow
or independent policy App. A pull request cannot satisfy a required check by
declaring another job with the same display name. Where GitHub cannot bind the
workflow identity safely, the plan uses a ruleset-required workflow already
registered on protected `main`.

### CODEOWNERS

Cover:

```text
/.github/workflows/
/.github/CODEOWNERS
/.github/rulesets/
/core/execution_policy.py
/core/runtime_paths.py
/gtbi/
/infra/github_performance/
/pyproject.toml
/config/gtbi/
/provenance/
/docs/readiness/gtbi-v7/
/security/gtbi-v7/
/schemas/gtbi-v7/
/containers/gtbi-v7/
/requirements/gtbi-v7.lock
/scripts/*gtbi*
/scripts/strategy_packs/
/tests/*gtbi*
/docs/adr/
/docs/plans/gtbi*
```

All listed owners must be valid collaborators or teams before the file is made
blocking.

Ownership is role-specific:

```text
scientific reviewer:
  /gtbi/
  /config/gtbi/
  /scripts/*gtbi*
  /scripts/strategy_packs/
  /tests/*gtbi*

workflow reviewer:
  /.github/workflows/
  /core/execution_policy.py
  /infra/github_performance/
  /containers/gtbi-v7/
  /requirements/gtbi-v7.lock
  /pyproject.toml

both reviewers:
  /.github/CODEOWNERS
  /.github/rulesets/
  /core/runtime_paths.py
  /provenance/
  /docs/adr/
  /docs/plans/gtbi*
  /docs/readiness/gtbi-v7/
  /security/gtbi-v7/
  /schemas/gtbi-v7/
```

This mapping is exhaustive for every protected path listed above. The
`gtbi-codeowners-coverage` validator expands Git attributes and path patterns
against the exact pull-request tree, rejects a protected path with zero or
multiple unclassified ownership classes, and rejects a newly introduced
security, schema, provenance, GTBI, workflow or readiness path until the table
and generated CODEOWNERS both classify it. Generated CODEOWNERS is compared
byte-for-byte with this table; hand-written drift is blocking.

GitHub treats multiple CODEOWNERS on one pattern as alternatives, not as an
all-of requirement. Therefore CODEOWNERS supplies routing only. A separate
required `gtbi-dual-role-review` check queries the pull-request review API,
resolves immutable actor IDs against the frozen role registry, and requires one
current non-dismissed approval from each distinct role for a change touching
both classes. Stage two requires two approvals on those changes. The check also
protects `CODEOWNERS`, the role registry and its own workflow; an author,
fallback owner, stale review or duplicate actor cannot satisfy both roles.
The role registry requires a distinct `source_dual_control_witness` and
`destination_dual_control_witness` for destructive, key-custody succession and
emergency-closure receipts. A witness cannot simultaneously be owner, App
manager, key custodian, account-root custodian, billing payer, implementer,
JIT approver or the other domain's witness.

### Environments

`PREV7-0007` bootstraps the first three preservation environments:
`gtbi-assets-read`, `gtbi-assets-primary-publish` and
`gtbi-assets-mirror-publish`.
`PREV7-0204` revalidates them against the production policy and creates the
checkpoint-write, cleanup, result-transport-read, dispatch-only,
repository-retire, secret-controller and environment-policy-controller Apps,
plus only the keyless proposed definition and frozen repository-class request
for the later destination-owned `gtbi-dependency-extract` App, the managed-App
cleanup-key-pair inventory,
bounded test installations/namespaces, installation policies and the remaining
environments. Exact production
campaign installations cannot exist before the disposable repository;
`PREV7-0808` requires the distinct registered source App manager to prepare and
attest the exact App/key manifest, and the repository/organization owner to
perform GitHub's provider-required installation authorization for the exact
selected repository. Both sign the ceremony receipt. It then freezes the
returned IDs and permissions. No workflow claims to create an App installation
through a nonexistent general REST endpoint:

```text
gtbi-assets-read
gtbi-assets-primary-publish
gtbi-assets-mirror-publish
gtbi-checkpoint-compact
gtbi-checkpoint-publish
gtbi-merge
gtbi-result-validate
gtbi-dispatch
gtbi-smoke
gtbi-real-data-smoke
gtbi-scientific-review
gtbi-workflow-review
gtbi-acceptable-use-review
gtbi-security-review
gtbi-full-authorization
gtbi-full
gtbi-forward-locked
gtbi-cleanup
gtbi-security-control
gtbi-environment-policy-control
gtbi-repository-retire
```

The environment registry has one row per concrete environment instance, with
explicit `repository_id`, `repository_scope`, purpose, protection policy and
credential classes. The exhaustive placement rule is:

```text
canonical source repository:
  gtbi-assets-read
  gtbi-assets-primary-publish
  gtbi-assets-mirror-publish
  gtbi-result-validate
  gtbi-dispatch
  gtbi-scientific-review
  gtbi-workflow-review
  gtbi-acceptable-use-review
  gtbi-security-review
  gtbi-full-authorization
  gtbi-forward-locked
  gtbi-security-control
  gtbi-security-control-<managed-app-id> for each managed App
  gtbi-environment-policy-control
  gtbi-repository-retire

one-campaign disposable execution repository:
  gtbi-full
  gtbi-checkpoint-compact
  gtbi-checkpoint-publish
  gtbi-merge
  gtbi-cleanup

exact disposable smoke repository:
  gtbi-smoke
  gtbi-real-data-smoke
  smoke-scoped copies of every production environment exercised by that smoke
```

`gtbi-acceptable-use-review` accepts only the registered licence and
acceptable-use reviewer; `gtbi-security-review` accepts only the registered
independent security reviewer. Neither contains scientific data,
publisher/decrypt credentials, App private keys or a route that can dispatch a
campaign. `PREV7-0204` creates their versioned definitions and negative-
permission tests; `PREV7-0210` creates the concrete canonical-source instances,
freezes repository/environment IDs and protection rules, and proves that the
scientific, workflow, owner, acceptable-use and security approval identities
are distinct wherever the ceremony requires them.

The canonical `gtbi-assets-read` is limited to preservation, oracle preparation
and other explicitly approved source-side reads; production matrix workers use
only the campaign repository's `gtbi-full`. `gtbi-result-validate` stays in the
canonical source repository so its archival-validation private key is never
installed in a disposable repository. A smoke-scoped copy never receives a
production recipient key or production installation. GitHub environments are
never assumed to inherit or share approval state across repositories.
Provisioning applies the frozen reviewers, branch/tag rules, wait policy and
deny-all defaults to the new repository and proves the settings by API, but
creates no campaign secret. Only after capsule consumption may the security
controller install lease-bound ephemeral secrets; the independent reaper
removes them and restores deny-all.
The separately controlled pre-core recipient keys are not transient activation
secrets: checkpoint keys follow their recovery-window custody policy and final-
result keys follow the longer canonical-result archival policy below.

Rules:

- `gtbi-assets-read`: exposes only a fixed-operation broker route after the
  repository owner approves an exact trusted ref. The broker internally mints
  and retains the read-only installation token, performs the manifest-bound
  read and returns bytes plus a receipt; the route is unavailable to pull
  requests and forks.
- `gtbi-dependency-extract`: is created only in `PREV7-0308`, after the
  destination broker/custody domain exists, and is destination-owned and
  suspended by default. Its
  source installations are limited to the selected canonical code/private-asset
  repositories in the frozen repository-class manifest. A destination-broker
  lease may mint internally at most a ten-minute reduced read token; the broker
  keeps it, performs only the immutable-object GET calls bound to endpoint/
  method allowlists, byte ceilings and the dependency-copy manifest, and
  returns only bytes plus receipts. No workflow receives the token. It cannot
  write, administer, dispatch, read environments/secrets or
  consume campaign artifacts. `PREV7-0308` records each owner-authorized
  installation; the final dependency-copy receipt records re-suspension and
  uninstall.
- `gtbi-assets-primary-publish` and `gtbi-assets-mirror-publish`: each is
   restricted to protected `main`, requires repository-owner approval and
  contains only its own repository-specific fixed-operation publish-broker
  client identity; the App key, JWT and installation token remain inside that
  broker. Each receives
  immutable ciphertext plus the independent result-validation receipt, copies
  those bytes unchanged and cannot decrypt them. Each has no scientific
  execution, asset-read, checkpoint-write or campaign-merge identity. A single
  job or environment can never possess both publisher routes; publication to
  both repositories uses two separately attested deployments and receipts.
- `gtbi-checkpoint-compact`: contains only an audience- and workload-bound OIDC
  route to the external source checkpoint-recipient key broker; the long-lived
  private key is non-exportable and never exists in a GitHub environment or
  repository secret. An authenticated host downloader first restores only
  manifest-bound ciphertext into an immutable, no-follow input directory using
  its registered job-scoped transport token and then destroys that token,
  environment value and credential process before any decrypting container
  starts. The protected host asks the broker to
  unwrap only the manifest-bound batch data key into a one-use attested handoff,
  removes its OIDC credential and starts a fresh no-network container. That
  container decrypts,
  validates, canonically compacts and re-encrypts the batches, destroys
  plaintext and one-use data-key material, and seals the exact output
  ciphertext, upload manifest and attestation in a new local immutable handoff
  directory. After that container and every decryption/key capability have
  terminated, the host obtains a one-object, digest-bound `PUT` credential and
  uploads only those sealed bytes to the source-owned content-addressed
  write-once checkpoint handoff store. This
  environment has no checkpoint-write, Actions, contents, package, scientific-
  asset-read, canonical-publish, cleanup or destination identity.
- `gtbi-checkpoint-publish`: contains exactly the client identity for the
  checkpoint-write fixed-operation broker and no App key, JWT, installation
  token or private decryption key. It receives only the immutable handoff
  object and attestation produced by a separate successful
  `gtbi-checkpoint-compact` deployment. It receives a digest-bound `GET`
  credential for the write-once handoff store, restores into a new immutable
  no-follow directory, opens each regular file by descriptor
  with no-follow semantics, verifies the frozen ciphertext and manifest digests,
  asks the broker to publish those exact bytes to the dedicated checkpoint
  namespace, verifies the broker's remote-digest/token-revocation receipt. It
  cannot decrypt, transform or
  regenerate a payload and has no scientific asset-read, canonical-publish,
  cleanup or destination identity. The handoff storage is one-use,
  content-addressed, immutable, read-only to the publisher and inaccessible to
  every scientific container. Its provider, account, region, IAM, object-lock,
  server-side encryption, retention, size ceiling, budget, deletion and cleanup
  receipt are frozen as a separate billing/control domain. The environment
  inventory and runbook freeze the two
  distinct environment IDs, actor/approval policies, App/installation ID,
  recipient key ID and public-key digest, handoff schema, key
  creation/rotation/expiry policy, private-key custody mechanism and
  destruction-receipt schema. Rotation cannot strand an approved recovery
  window.
- `gtbi-merge`: contains only an audience- and workload-bound OIDC route to the
  external campaign merge-recipient key broker; the long-lived private key is
  non-exportable. Its job also receives GitHub's ephemeral repository token restricted to
  `actions:read, contents:none` in that disposable repository. Uploading a new
  Actions artifact uses the job-scoped artifact runtime channel and does not
  justify `actions:write`; run deletion/cancellation remains isolated in the
  separately approved cleanup path.
  It restores authenticated ciphertext, obtains only the exact one-use
  manifest-bound data key from the broker, removes OIDC/transport credentials,
  decrypts and merges inside a no-network trusted container, then
  encrypts every block output to the same merge recipient and wraps the final
  output data key for the separate source result-validator and independent
  destination recipients. It has no asset-read,
  checkpoint-package, repository-administration or canonical-publish App.
- `gtbi-result-validate`: contains an audience- and workload-bound OIDC route to
  the external source final-result-recipient key broker plus a dedicated
  short-lived result-transport read App installed only on the
  one disposable campaign repository with `actions:read` and no write/content/
  package permission. A host downloader restores only the manifest-bound final
  ciphertext, removes the token, obtains only the exact one-use data key from
  the broker, removes OIDC credentials, and a fresh no-network container
  authenticates and decrypts it, validates every schema, digest and row equation, destroys
  plaintext and emits an attested approval digest. It has no asset-read,
  publish, checkpoint, merge or repository-administration capability. The same
  protected role performs later source-side clean-runner restore validation;
  the independent destination uses its disjoint recipient key.
- Final-result envelopes are archival, not merely campaign-temporary. While a
  result is canonical, at least two independently controlled, tested recipient
  keys remain capable of restoring its data key: one source archival validator
  and one independent destination custodian. Rotation first unwraps and rewraps
  the same data key for the replacement public key inside a fresh no-network
  decrypt/rewrap container. After that container terminates and destroys all
  key material, a separate credentialed host phase publishes the sealed new
  envelope and restores the complete result from
  both custody domains and emits an attested rotation receipt. Only then may the
  retired key be destroyed. The final capable key can be destroyed only after
  the result's approved retention ends and a destructive manifest explicitly
  retires the result itself.
- Total loss of a source recipient-key domain is the named incident
  `RECIPIENT_KEY_DOMAIN_LOSS`, not an ordinary rotation. When the independent
  destination still holds a valid recipient envelope, a recovery-only workflow
  restores the manifest-bound data key inside the destination broker, rewraps
  it to a freshly generated source public key and emits only the new envelope
  plus ciphertext/manifests. It has no scientific, merge, ranking or publication
  path and no network inside the decrypt/rewrap container. Source and
  destination custodians separately approve the exact incident/ciphertext/new
  key IDs; both WORM stores receive the receipts, and clean-runner restore from
  the new source envelope must pass before the incident closes. Loss of both
  capable domains is recorded as unrecoverable data loss and blocks every clean
  success claim.
- `gtbi-dispatch`: contains only the dispatch-only App identity. It accepts one
  already validated capsule digest from the canonical controller, invokes only
  the allowlisted workflow-dispatch endpoint in the one frozen disposable
  repository and immediately revokes/suspends its lease after recording the run
  ID. It has no scientific, asset, checkpoint, merge or publication key.
- `gtbi-smoke`: synthetic fixtures only, no private credential and no manual
  approval.
- `gtbi-real-data-smoke`: trusted refs only, includes the read-only App
  authentication needed by that job and requires the configured approval.
- `gtbi-scientific-review`: no asset credential; only the named scientific
  reviewer may approve a job that verifies and records an exact runbook-core
  digest.
- `gtbi-workflow-review`: no asset credential; only the distinct workflow
  reviewer may approve a job that verifies and records that same digest.
- `gtbi-acceptable-use-review`: no asset or dispatch credential; only the
  registered licence and acceptable-use reviewer may approve the exact
  workload, provider-terms observation and budget/usage envelope.
- `gtbi-security-review`: no asset or dispatch credential; only the independent
  security reviewer may approve the exact deployed IAM/App/key/deadman state,
  vulnerability receipt and accepted residual-risk set.
- `gtbi-full-authorization`: contains no asset, App or signing credential; only
  the repository owner may approve the exact runbook-core digest and current
  authorization-envelope creation.
- `gtbi-full`: trusted protected full tags only; contains only the read-only App
  authentication needed by full workers. It contains no checkpoint-write,
  canonical-publish or cleanup identity and remains disabled until independent
  scientific/workflow reviews, owner authorization, destination-owned capsule
  and unused campaign-consumption ticket are verified. Repository-owner authorization is recorded in the
  immutable authorization envelope and the protected deployment approval is
  performed by an eligible actor who did not initiate that deployment.
- `gtbi-forward-locked`: disabled until an independent locked approver exists.
- `gtbi-cleanup`: contains only the dedicated cleanup-App identity, is disabled
  by default, is installed solely on the disposable campaign namespace and
  requires a fresh owner approval for every immutable deletion batch. Its
  technically possible non-delete package operations are policy-forbidden,
  audited and fail post-run reconciliation.
- `gtbi-security-control`: accessible only to the protected immutable lease
  reaper coordinator workflow. It contains only the disjoint secret-controller
  App described by the activation-lease policy. Each
  `gtbi-security-control-<managed-app-id>` subenvironment contains only the
  audience-bound client identity for one named non-exportable cleanup-key
  broker for that App and can be selected only by the fixed reviewed
  source-reaper matrix. Every broker carries the full residual authority of its
  monofunction App; no workflow receives its key, JWT or installation token, and
  no broker request can carry campaign payload or arbitrary API input.
- `gtbi-environment-policy-control`: contains only the campaign-specific
  environment-policy App with `Administration: write` on the exact disposable
  repository. It exposes no arbitrary API input and may call only the reviewed
  environment-policy endpoints needed to restore deny-all. It is never
  installed on Aurora, asset repositories or the independent destination.
- `gtbi-repository-retire` contains no repository-creation credential. The
  repository owner creates the one disposable repository interactively inside
  the isolated campaign organization from the reviewed template, while a
  second actor records its immutable organization/repository ID, visibility and
  tree digest. A separate campaign-specific `gtbi-repository-retire` App may be
  installed only after that ID exists, selected-repository scope must contain
  exactly that one repository, and it remains suspended until an owner-approved
  terminal removal manifest names that same ID. It has no organization-wide
  installation, no create-repository path and cannot name Aurora, canonical
  asset repositories or any pre-existing repository.
- Prevent self-review is enabled when a second approver exists.
- Administrator bypass is disabled on checkpoint-compact, checkpoint-publish,
  merge,
  result-validate, dispatch, scientific-review,
  workflow-review, acceptable-use-review, security-review,
  full-authorization, full, forward-locked, cleanup and
  every security-control compartment and repository-retire environment; a
  bypassed deployment can never generate an accepted approval receipt.
- Environment deployment-branch restrictions use exact protected refs, not a
  broad wildcard.
- A workflow cannot both execute unreviewed branch code and receive a private
  asset credential.
- A job declares exactly one environment. It never combines private-read and
  checkpoint-write identities. Full workers use only `gtbi-full`; separate
  `gtbi-checkpoint-compact` and `gtbi-checkpoint-publish` deployments use
  disjoint jobs, runners, credentials and immutable handoff directories. No job,
  environment, actor session or reusable runner can possess a checkpoint
  private key and checkpoint publication capability at the same time. Neither
  job can read source scientific assets.
- The workflow initiator and protected-environment approver are different
  eligible actors whenever prevent-self-review is active.
- Before the 360-job capacity smoke, a deployment-approval fixture proves that
  one review of the exact environment and run releases all intended pending
  matrix jobs without administrator bypass, repeated clicks or jobs receiving
  secrets before approval. If the configured GitHub plan or protection rule
  cannot do this reliably, the 360-job topology is redesigned before G7 rather
  than weakening environment protection.

Every ephemeral plaintext data-key handoff uses the frozen
`ephemeral_key_handoff_v1` profile: a broker CAS consumes one nonce bound to
campaign, repository, workflow, job, attempt, operation, recipient and
ciphertext/manifest digest; the key is written once to a mode-`0400` anonymous
`tmpfs`/sealed-memory object and passed by an already-open descriptor, never by
argv, environment, workflow output, log or persistent filesystem. Swap and core
dumps are disabled; the key is read once, its descriptor is closed, the buffer
is explicitly overwritten where the runtime permits, and the memory object is
unmounted before any network/upload credential is obtained. G7 must prove the
selected GitHub runner/runtime supports this profile; inability to disable
swap/core dumps or to keep the handoff off persistent storage is `NO-GO`.
These guest controls do not remove the separately declared provider-host trust
assumption.

`PREV7-0705` is the sole producer of
`g7_ephemeral_key_handoff_test_receipt_digest`. The receipt is generated by the
exact G7 fault-injection workflow and runtime image, binds campaign and
`G7_ATTEMPT-n`, profile digest, broker-policy digest, runner-image digest,
tested swap/core-dump/tmpfs/destructor assertions, negative leakage probes,
result, trusted UTC and expiry, and is independently anchored before G7 can
green. It is pre-core evidence for a later full run; no full-run key or
post-core authorization receipt is required to create it.

Approval evidence is never trusted merely because a CSV field names an actor.
Protected approval jobs query GitHub's API and write an
`approval_receipts.json` containing:

```text
runbook_core_digest
role
actor_login
actor_id
environment
deployment_id
review_state
review_submitted_at
workflow_run_id
executed_ref_sha
api_response_digest
```

G8 verifies actor IDs against the frozen role registry, requires distinct
scientific, workflow and owner actors, checks successful protected-environment
reviews, and rejects stale, dismissed, bypassed or digest-mismatched receipts.

### Workflow Security

Required:

- repository Actions default workflow permission is read-only and workflows
  cannot create or approve pull requests;
- allowed-Actions policy is restricted to an explicit reviewed full-commit-SHA
  allowlist; GitHub-owned Actions receive no mutable-tag exception;
- workflows from forks require approval and never receive write tokens or
  protected environments;
- every external Action, including GitHub-owned Actions, is pinned to a full
  commit SHA;
- same-repository reusable workflows use only local paths from the executed
  commit; every external reusable workflow is pinned as
  `owner/repository/path@<full-commit-sha>`. A structural validator checks both
  step-level `uses:` and job-level `jobs.<id>.uses`; provider policy alone is
  not treated as sufficient;
- explicit job permissions;
- `contents: read` by default;
- `id-token: write` only for jobs listed in the frozen
  `oidc_workload_registry.json`: execution-receipt/attestation jobs and the
  exact checkpoint-compaction, merge, result-validation, key-provision,
  key-rotation, abandoned-recovery or reaper broker clients that require an
  OIDC exchange; every other job sets it to `none`;
- `attestations: write` only for the exact protected attestation job when
  GitHub's attestation action requires it; all other jobs set
  `attestations: none`, and jobs outside the OIDC registry set
  `id-token: none`;
- `packages: write` only for publishing jobs;
- no untrusted PR secrets;
- no `pull_request_target` execution of untrusted code;
- strategy, archive and scientific payload values are never echoed to
  stdout/stderr, job summaries, annotations, `GITHUB_OUTPUT`, `GITHUB_ENV` or
  `GITHUB_PATH`; logs use fixed error codes and allowlisted numeric counters;
- every value visible in public Actions metadata, including workflow/run/job/
  step names, `workflow_dispatch` inputs, matrix JSON, check names, artifact
  envelope names, concurrency-group strings and environment URLs, contains
  only allowlisted counters, fixed labels, opaque campaign/job IDs and
  non-sensitive digests. It never contains a ticker, candidate/strategy ID,
  family/concept, rule, metric, licensed source name, private asset locator or
  other scientific payload. A private manifest maps opaque IDs to protected
  meanings only after authenticated download;
- any unavoidable inspection of untrusted text disables workflow-command
  interpretation with a fresh unpredictable stop token, strips control
  characters and writes only to a private sealed diagnostic file;
- shell tracing is disabled around every credential, private input and
  scientific step. The host wrapper redirects complete container stdout/stderr,
  Python tracebacks and native crash diagnostics into a bounded private raw
  diagnostic file instead of the Actions console, catches every terminal exit
  and emits publicly only an allowlisted fixed error code and numeric counters.
  The private file follows the same no-follow, schema/size, secret-scan,
  encryption and recipient-custody path as other diagnostics; if it cannot be
  sealed safely it is destroyed and the fixed `PRIVATE_DIAGNOSTIC_SEAL_FAILED`
  code is emitted;
- concurrency groups for campaigns;
- timeouts on every job;
- dependency lock and verified wheelhouse;
- lock entries and wheels verified by cryptographic hash;
- dependency installation uses the reviewed interpreter with
  `--no-index --require-hashes` from the verified wheelhouse; DNS and package
  index access are fail-closed during installation and scientific execution;
- the installed distribution inventory, native-library inventory and import
  smoke are hashed and compared with the approved dependency manifest;
- the lock and wheelhouse are generated only by a protected dependency-build
  workflow from allowlisted official indexes, with `--only-binary=:all:`,
  hashes for every transitive wheel, dependency-review approval and provenance
  or source metadata for each file; an sdist, mutable URL, VCS dependency,
  unexpected index or unreviewed lock change blocks G7;
- container `FROM` image pinned by digest;
- SBOM, vulnerability scan and provenance attestation verified before the
  runtime digest is approved;
- workflow inputs validated against a strict schema and passed through
  environment variables or argument arrays, never interpolated into shell
  programs or `eval`;
- strategy records have bounded byte size, nesting depth and collection
  lengths, finite typed parameters and allowlisted rule enums; expressions,
  templates, imports, regex supplied as code and dynamic call targets are
  rejected;
- artifact and archive paths normalized, confined to the job workspace and
  rejected on traversal, symlink escape, device file, archive bomb, declared
  size overflow or unexpected file type;
- no pickle, joblib or other code-executing deserialization for downloaded
  scientific assets;
- public logs contain no raw rows, licensed trade detail, private candidate or
  ticker metrics, credentials or local absolute paths; debug tracing is
  disabled for credential and data steps, and only licence-approved aggregate
  fields may be printed;
- no dynamic or mutable `uses:` target;
- Dependabot security updates;
- secret scanning and push protection enabled;
- CodeQL findings triaged before becoming blocking.

Each OIDC registry row freezes broker ID, issuer, audience, the exact customized
`sub` template and immutable repository/owner-ID binding, `repository_id`,
`repository_owner_id`, repository visibility, the required presence and exact
value or required absence of `environment`, workflow path/SHA,
`uses_reusable_workflow`, executed ref/SHA, event name, actor/actor ID, `run_id`,
`run_attempt`, `check_run_id`, runner environment, campaign/job role, maximum
token age and the exact broker operation. Before any broker trust is enabled,
the repository's current OIDC subject mode and customization are queried and
frozen. Never infer the mode from repository age or name: use GitHub's immutable
owner/repository-ID subject format only when the API proves it active; otherwise
opt into that format when available or use a reviewed custom subject that
includes both `repository_owner_id` and `repository_id`. A name-only repository
subject is forbidden. The broker
validates those claims plus JWT `jti`, `nbf`, `iat` and `exp` itself.
When `uses_reusable_workflow=true`, the row also requires exact
`job_workflow_ref` and reusable-workflow commit SHA. When false, both claims
must be absent; an unexpected claim is rejected. `workflow_ref`,
`workflow_sha`, `repository_id`, `repository_owner_id`, `run_id`, `run_attempt`,
`check_run_id` and `runner_environment` are checked directly against their
actual GitHub OIDC claims. `environment` is required and checked when the job
references the frozen GitHub environment and must be absent otherwise.
`check_run_id` is then checked a second time through the controller-issued nonce
and an independently verified GitHub Jobs-API mapping to the token's repository,
run, attempt, workflow, ref, SHA and environment state. The API lookup is
defence in depth and cannot replace direct validation of the signed claim.

Signature verification precedes every claim check. The frozen trust profile is:

```text
issuer=https://token.actions.githubusercontent.com
openid_configuration=https://token.actions.githubusercontent.com/.well-known/openid-configuration
jwks_uri=https://token.actions.githubusercontent.com/.well-known/jwks
allowed_jws_algorithms=[RS256]
tls_minimum_version=1.2
http_redirects_allowed=false
jwks_cache_max_age_seconds=21600
```

The broker validates the discovery document issuer and exact HTTPS host,
normal certificate chain/hostname and response size/content type, then verifies
JWT signature, `kid` and `alg` against the allowlist before reading any claim.
It never accepts `none`, algorithm substitution, an embedded `jwk`/`jku`/`x5u`
or a key supplied by the caller. An unknown `kid` triggers at most one
rate-limited synchronous JWKS refresh; failure to obtain a current valid set,
an over-age cache without refresh, duplicate key IDs, malformed key material,
TLS failure or issuer/JWKS drift fails closed. A previously cached key may be
used only inside the frozen cache age and JWT lifetime. Rotation fixtures add
and remove keys across overlap; negative fixtures cover forged signature,
wrong algorithm, unknown/duplicate `kid`, stale cache, hostile discovery/JWKS
redirect, TLS/hostname failure, oversized response and outage.

The protected controller issues the operation nonce only after querying the
GitHub Jobs API and binding the exact `run_id`, `check_run_id`, job name,
attempt, repository/workflow/ref/environment, operation and manifest digest.
The broker independently verifies that Jobs-API mapping against the token
claims, then atomically consumes the short-lived nonce before releasing one
result or performing one operation. Another job in the same workflow cannot
reuse or proxy it. Replay, fork, pull-request, wrong reusable-workflow, wrong
job/check-run, wrong environment/ref/SHA, stale token and confused-deputy
fixtures must fail.

G3A/G3B inventory and acceptance also cover every privileged surface:

```text
organization_owners
repository_admins
GitHub_Apps_and_installations
deploy_keys
webhooks
rulesets_and_bypass_actors
branch_protection
environment_reviewers_and_branch_policies
hosted_and_self_hosted_runner_configuration
Actions_default_permissions
allowed_Actions_policy
fork_approval_policy
repository_and_environment_variable_names
secret_names_and_update_metadata_without_values
PAT_policy
OIDC_and_artifact_attestation_policy
package_and_release_write_identities
```

Organization policy permits GitHub App installation or repository-selection
changes only by named organization owners; member App requests are disabled.
The API-verifiable inventory freezes App ID, installation ID, owner account,
selected repository IDs, granted permissions and suspension state. Private-key
state is a separate ceremony-controlled inventory because GitHub does not offer
the controller a complete REST inventory of every App private key. For every
production App:

- the App is owned by a dedicated minimal App-custody organization whose
  delegated App managers are not source/destination repository owners or
  workflow actors. No human retains standing delegated App-manager access;
  irreducible organization-owner authority is governed as the explicit
  residual risk in section 6. The registered App-manager role is
  activated just in time for one exact ceremony through two distinct custody-
  organization approvers and a time-bounded privileged-access lease;
- a two-actor owner/App-manager ceremony immediately before core freeze records
  the complete visible GitHub key inventory, destroys superseded downloaded
  material and binds the complete approved campaign key-set manifest. For every
  managed App used by deadman and reaper, that manifest contains the two
  distinct role-labelled public-key fingerprints, key IDs, brokers and failure
  domains; any separate operational key is a third role-labelled entry;
- the selected broker must support reviewed secure import; the approved key is
  imported into a sign-only, non-exportable key object through either a
  provider-supported direct one-time callback or an ephemeral attested
  administrative workstation dedicated to that ceremony. The latter boots
  from a measured read-only image, has no clipboard, sync client, persistent
  disk, backup, shell history or general logging, sends the PEM only to the
  pinned broker endpoint, records workload/host identity and public-key
  fingerprint, then proves memory/session destruction. An ordinary laptop,
  browser download directory, clipboard, synced folder, persistent filesystem
  or reusable administrator session is forbidden. If GitHub or the broker
  forces such a path, the ceremony is `NO-GO`;
- the import receipt binds App ID, GitHub key fingerprint, broker public-key
  fingerprint, attested host/workload identity, import time, destruction time
  and absence-proof digest without preserving the PEM;
- the broker attests the exact key on every JWT signature and refuses use
  outside the campaign, App, lease generation, endpoint and expiry;
- any observed unmanifested key, unauthorized replacement or unexplained
  key-management event invalidates every pending core, envelope and capsule and
  is immediate `NO-GO`;
- ceremony close removes the temporary App-manager grant, revokes its sessions,
  proves no eligible standing delegated manager remains and exports the complete
  privileged-access/key-management event set to external WORM logs. The
  repository installation owner independently retains only the ability to
  suspend/uninstall the App as a security fail-safe; App-side suspension is
  never the sole shutdown boundary.

Immediately before every installation-token mint, activation, replication,
publication or cleanup action, the protected controller re-queries and matches
the API-verifiable tuple and verifies the current broker attestation and
bounded-age ceremony receipt. GitHub cannot prove through that API that an App
manager has never created an unobserved additional private key; this is an
explicit residual platform risk, not claimed as technically eliminated.
Ordinary standing delegated App-manager access therefore remains a high unresolved risk
and keeps G3B red. G3B can proceed only after the independent security reviewer
verifies the just-in-time two-approver custody, zero-standing-delegated-manager state,
external WORM audit export, installation-owner uninstall test and classifies
the bounded residual no higher than medium with owner, expiry and receipt. An added App,
changed permission, changed repository selection, owner drift, stale ceremony
or inventory mismatch blocks the action and invalidates the authorization-
state snapshot.

G3A and G3B remain red while any privileged identity, bypass or write path is
unknown.

### PREV7-0209: Threat Model

Before G7, publish and independently review:

```text
docs/readiness/gtbi-v7/threat_model.md
docs/readiness/gtbi-v7/threat_control_test_matrix.csv
docs/readiness/gtbi-v7/residual_risk_registry.csv
```

The model covers source, independent destination, GitHub-hosted runner guest
processes and workflows,
workflow supply chain, Apps, OIDC, environments, packages, releases,
checkpoints, merge, publication and local non-canonical machines. It includes
malicious/compromised implementer, reviewer, owner, runner guest process,
workflow, dependency,
artifact, source organization and destination organization; replay, confused
deputy, credential exfiltration, TOCTOU, manifest substitution, rollback,
partial-loss and total-loss scenarios. It explicitly models the full authority
of every App private key, the one-repository `Administration: write`
environment-policy controller, source/destination reaper separation,
cross-repository trigger loss, stale lease generations, owner installation
ceremonies, destination-owner loss and unacceptable or unexpectedly repriced
GitHub Actions usage. It also models individual, pairwise and three-party
collusion among each domain's owner/full authorizer, account-root custodians,
billing-payer authorizer, App-custody organization owner, both JIT approvers,
App manager, deadman operator/deputy, key-broker custodian, storage
administrator, WORM/KMS key administrator and break-glass custodian. Mandatory
cases include root+App-manager, root+deadman, App-custody-owner+full-authorizer,
storage-admin+KMS-admin and every cross-domain shared-human case. It proves
that no single actor or forbidden pair can deploy cleanup authority, change
signing/retention policy, reconfigure an App and authorize the same campaign.

It also treats every external control/evidence dependency as a separate trust
boundary: source and destination WORM/object-lock providers, recipient/App key
brokers and KMS/HSMs, CAS lease registries, deadman hosting, monitoring/
alerting, trusted-time/timestamp/transparency services, billing/payer systems,
DNS/TLS/certificate infrastructure, the bootstrap preservation controller, the
destination cold-verifier downloader/offline-decrypt/publisher phases and
provider support/account-recovery
control planes. For each, model malicious or mistaken provider operator or
support agent, account-root/payer compromise, API/control-plane compromise,
regional and account-wide outage, correlated provider failure, silent
rollback/deletion, retention or key-policy bypass, repricing/billing lockout,
legal/administrative account suspension, hostile recovery and dependency on
shared upstream identity/DNS/TLS. The matrix identifies whether prevention,
independent replication, fail-closed operation, local sovereign cleanup or
explicit residual acceptance handles each failure. Two named “independent”
domains are not accepted when they share the same root account, payer, support
recovery, identity tenant, KMS administrator, DNS zone, provider control plane
or single human.

Every threat maps to trust boundary, protected asset, control, negative test,
evidence, owner and residual severity. G3B and G7 require zero unresolved
critical or high residual risks. Accepted medium/low risks require an expiry,
owner and explicit repository-owner receipt; an undocumented risk cannot be
implicitly accepted.

The reviewed evidence includes the exact `PREV7-0604` local-run guard digest,
all protected entrypoints and negative tests proving a laptop, missing
`GITHUB_ACTIONS=true` or an unapproved local override cannot execute research.
A changed guard invalidates `PREV7-0209`.

The provider host, hypervisor and control plane are an explicit trust assumption
for ordinary GitHub-hosted runners: a hostile host can read guest memory,
mounted plaintext and one-use keys and can bypass guest namespace/seccomp
controls. The plan makes no confidentiality claim against that actor.
`runner_host_trust_model=github_provider_host_in_tcb` is permitted only when the
data licence, asset policy, security reviewer and repository owner explicitly
accept that boundary. If protection from the provider host is required, the
ordinary hosted topology is `NO-GO`; the only alternative is a separately
approved confidential-compute runner whose hardware attestation measurement is
verified by the broker before key release. No marketing label or guest-only
attestation is accepted as confidential compute.
That alternative is not executable inside this plan: selecting it activates
`NO_GO_CLOSE-n` here and requires a separate reviewed campaign plan with its own
runner provider, attestation root, broker-release policy, licence, budget,
capacity, recovery and equivalence gates. No placeholder confidential-compute
fields may green this V7.

### Signing

Do not require signed commits or tags until a working signing mechanism is
documented and tested.

Preferred mechanisms:

- GitHub-verified merge commits;
- GitHub artifact attestations using OIDC;
- release manifests bound to verified artifact attestations from the publishing
  workflow; a separate signature is added only after its mechanism is tested.

Restoration verifies the attestation subject, repository, workflow ref,
issuer, payload digest and policy before trusting it. Merely finding an
attestation object is not sufficient.

The attestation policy freezes the expected OIDC audience, issuer, repository
ID, repository owner ID, protected workflow path and digest, ref type, exact
tag or main SHA, event name, subject-name pattern and subject digest. The
attestation job has only `contents: read`, `id-token: write` and
`attestations: write` as required by the pinned GitHub-owned action. A token or
attestation with a fork, pull-request merge ref, unexpected reusable workflow,
different audience or mutable subject is rejected.

Gate `G3A` passes when minimum branch, workflow and asset protections allow
implementation and non-locked smokes without deadlock.

Gate `G3B` passes only when valid independent scientific, workflow and security
reviewers can exercise their exact approval paths, the disaster-copy owner and
custody foundation are independently verified, and PREV7-0209 has zero
unresolved critical/high findings plus only explicitly accepted bounded
residuals. Recording that any required actor is missing does not satisfy `G3B`
and can never authorize a full run.

## 15. Gate G4: GitHub And Local Reorganization

### PREV7-0400: Complete The Resumable GitHub Inventory

After the V6 final result is durably preserved, enumerate all artifact,
release and package records. The inventory workflow:

- uses the maximum supported page size and a resumable cursor;
- records request URL without credentials, page number, response ETag, rate
  limit, UTC cutoff and page digest;
- checkpoints after every page and resumes without restarting;
- deduplicates by immutable artifact, release or package-version ID;
- retains only records created at or before the frozen cutoff;
- pauses before exhausting the API rate budget;
- repeats the boundary pages and requires two consecutive identical retained
  ID-set digests before declaring completeness;
- reconciles retained, post-cutoff, deleted-during-scan and inaccessible counts;
- writes `complete=false` with an exact reason rather than silently truncating.

Final outputs:

```text
docs/project_inventory/artifacts.csv
docs/project_inventory/releases_complete.csv
docs/project_inventory/packages_complete.csv
docs/project_inventory/inventory_reconciliation.json
```

No cleanup or retirement decision may use an incomplete inventory.
The final reconciliation also proves bootstrap
`gtbi-v7-inventory.yml` and target
`aurora-maintenance-inventory.yml` return the same retained-ID set, migrates
the immutable cursor/query evidence, disables bootstrap dispatch and archives
the bootstrap workflow.

### PREV7-0401: GitHub Workflow And Branch Registry

Every branch, workflow, run family, artifact class, release and package family
gets:

```text
owner
purpose
product
status
canonical_replacement
retention_class
last_verified_at
decision
```

Allowed decision values:

```text
keep
migrate
archive
disable
delete_after_approval
unknown
```

Individual inventory is mandatory for:

- canonical artifacts;
- scientific references;
- data snapshots;
- strategy packs;
- active campaign artifacts;
- every artifact proposed for deletion.

The remaining historical ephemeral artifacts are classified by exact naming
family, workflow and retention rule. G4 does not require manually reviewing
all `326415` records one by one.

Gate G4 cannot pass while a branch, workflow, canonical asset, active run or
deletion candidate remains `unknown`.

### Workflow Layout

All runnable and reusable workflow files remain directly under:

```text
.github/workflows/
```

Target names:

```text
aurora-ci-tests.yml
aurora-ci-lint.yml
aurora-ci-security.yml
aurora-ci-package.yml
gtbi-performance-campaign.yml
gtbi-performance-recovery.yml
gtbi-performance-merge-only.yml
gtbi-campaign-transport-provision.yml
gtbi-campaign-dispatch.yml
gtbi-campaign-transport-retire.yml
gtbi-campaign-key-provision.yml
gtbi-result-validate.yml
gtbi-v7-package-close.yml
gtbi-lease-reaper.yml
aurora-maintenance-inventory.yml
aurora-maintenance-artifacts.yml
aurora-maintenance-retention.yml
gtbi-v6-emergency-preserve.yml
gtbi-v6-emergency-restore.yml
_reusable-gtbi-prepare.yml
_reusable-gtbi-execute-shard.yml
_reusable-gtbi-verify-shard.yml
_reusable-gtbi-publish-checkpoint.yml
_reusable-gtbi-compact-checkpoints.yml
_reusable-gtbi-resolve-block-inputs.yml
_reusable-gtbi-merge-block.yml
_reusable-gtbi-publish.yml
```

`task_delivery_manifest.csv` assigns
`.github/workflows/gtbi-v7-package-close.yml`, its schemas and package-close
tests to `PREV7-0608`; G6A cannot pass until the workflow exists on the reviewed
tree, is registered through the protected default-branch path and its
credential-free synthetic close/reject fixtures pass.

The independent destination keeps separately protected workflows for
authorization/capsule creation, campaign-consumption registration, checkpoint
replication and total-source-loss restore. Their repository IDs, paths and full
SHAs are frozen in the disaster trust manifest; source workflow files are not
substitutes.

Do not place workflows in `.github/workflows/reusable/`; GitHub does not
register nested workflow files.

Manual-dispatch registration rule:

- a new `workflow_dispatch` path must exist on protected default-branch
  `main` before it is used for branch-ref smokes;
- the registration PR may install the reviewed workflow shell and reusable
  workflow calls, but full mode remains fail-closed behind G8, environment and
  manifest checks;
- no plan assumes that an unmerged workflow file can be dispatched by path;
- the dispatched run records both default-branch registration SHA and executed
  ref SHA.

Retired workflow YAML moves to:

```text
docs/archive/workflows/
```

It must not remain under `.github/workflows/`.

The two V6 emergency workflows remain registered until the primary and mirror
have both passed production-policy restore. They are then disabled for new
dispatch, retained through the recovery window and archived under the same
retirement procedure; their historical runs and manifests are never deleted.

`gtbi-v7-inventory.yml` is the bootstrap-only inventory workflow created by
`PREV7-0001`. `PREV7-0400` migrates its immutable query/receipt state into
`aurora-maintenance-inventory.yml`, verifies identical retained-ID sets,
disables new bootstrap dispatch and archives the bootstrap YAML. Both names
cannot remain active after G4.

### Artifact Retention And Cleanup

Classes:

```text
ephemeral-worker
checkpoint
block-merge
final-result
scientific-reference
data-snapshot
strategy-pack
audit-evidence
```

Target retention, subject to the recorded licence and repository policy:

| Class | Actions copy | Durable copy | Deletion condition |
|---|---:|---|---|
| `ephemeral-worker` | Fixed 3 days from upload, retention expiry only | Required encrypted checkpoint coverage until verified block merge | GitHub expires it on schedule; no scientific condition delays expiry |
| `checkpoint` | 7 days for smoke | Dedicated source external content-addressed object store; recovery-required full checkpoints also copied independently through the recovery window | Final result verified, 30-day recovery window elapsed, final dual restore green and financial state `RECONCILED_CLEAN`, or `DISPUTED_CLEAN` with immutable dispute evidence exported and maximum liability reserved |
| `block-merge` | 7 days | None after verified final merge | Final digest and row equations verified |
| `final-result` | Fixed 7 days from upload | Primary, mirror and independent disaster copy | Explicit supersession and owner approval |
| `scientific-reference` | Fixed 7 days from upload | Primary, mirror and independent disaster copy | Never automatic |
| `data-snapshot` | Fixed 7 days from upload | Policy-controlled primary, mirror and independent disaster copy | Licence-compliant supersession only |
| `strategy-pack` | Fixed 7 days from upload | Policy-controlled primary, mirror and independent disaster copy | Explicit supersession only |
| `audit-evidence` | Fixed 7 days from upload | Primary, mirror and independent disaster copy for at least the lifetime of the bound canonical result | Only after every bound canonical result is validly deleted and the audit/legal policy permits it |

Every Actions upload sets an explicit numeric `retention-days`; repository and
organization policy are queried immediately before upload and must permit the
frozen value. A workflow default, the phrase “short copy”, silent provider
clamping or a value outside the current provider maximum is invalid.

### Durable Retention Funding And Recovery Objectives

Indefinite scientific retention is an operational obligation, not a free
assumption. `retention_funding_manifest.json` records, for every durable class
and custody domain:

```text
payer_actor_and_account
native_currency
pricing_snapshot_and_valid_until
approved_minor_unit_cap_per_period
tax_transfer_request_and_restore_allowances
warning_and_hard_alert_thresholds
funded_through_utc
next_review_due_utc
primary_and_deputy_on_call
provider_escalation_target_and_deadline
approved_migration_destination_or_null
migration_lead_time_days
minimum_required_migration_lead_time_days
migration_duration_evidence_digest
latest_restore_receipt_digest
```

The funding review repeats at least quarterly and early enough to complete an
approved byte-identical migration before any account, key, contract or payment
expiry. A missed review, failed payment, price above cap or insufficient
migration lead time blocks new campaigns and raises an owner incident; it never
authorizes deletion. Canonical final results, scientific references and their
bound audit evidence remain funded while retained.

The minimum recovery objectives are:

| Asset/state | RPO | RTO | Test and escalation |
|---|---:|---:|---|
| Accepted final result, scientific reference, data snapshot or strategy pack | Zero accepted objects/bytes | 24 hours | Quarterly clean restore from each custody copy; page primary and deputy immediately on failure |
| Append-only authorization, lease, cost and security records | Zero accepted events | 4 hours | Monthly chain replay plus quarterly total-owner-loss restore |
| Active recovery-required checkpoint stream | At most one not-yet-acknowledged sealed microbatch per planned-job chain; aggregate maximum equals admitted `job_count` | 6 hours | Every campaign proves selective recovery; a missing replication acknowledgement stops new assignment for that chain and a full-concurrency failure proves the aggregate bound |
| Emergency V6 preservation package before G2 | Zero bytes after each accepted publish receipt | 24 hours | Primary and mirror clean-runner restore before G0 |

RPO is measured only after the named acceptance or acknowledgement boundary.
RTO starts at authenticated incident declaration and ends only after complete
digest-verified restoration. Each breach records incident ID, detected/start/
restore times, affected manifests, cause, owner, deputy, escalation receipt and
corrective action. An unresolved breach keeps the owning gate red.

A destination-controlled cold verifier outside GitHub runs at least quarterly
and during every total-GitHub-outage exercise. Its workload identity, measured
boot/attestation policy, image, code and configuration digests, destination
account/region, network-deny policy, recipient-key broker route and WORM receipt
schema are frozen before use. A first authenticated phase downloads only the
manifest-bound ciphertext and then destroys every transport credential. A
fresh no-network attested phase receives a one-use manifest-bound decryption
capability, restores into encrypted ephemeral storage, verifies bytes, schema,
hashes and manifest, emits only the approved digest/row-count receipt, then
zeroizes plaintext, keys and storage before termination. A separate
credentialed publisher may append only that attested receipt to destination
WORM after the decrypting phase has ended. The verifier has no scientific
execution, strategy evaluation/filter/rank, publication or source-control
authority. It proves the platform-outage archive can meet RTO while all GitHub
APIs, Actions, Releases and Packages are denied. This operational verifier is
managed infrastructure, never the user's laptop.

The cleanup workflow removes only object versions from the dedicated external,
non-canonical checkpoint namespace after resolving their immutable IDs and
digests from the verified final manifest. It never deletes by prefix or mutable
name alone and its broker has no access to canonical namespaces.
Checkpoint versions are eligible only after the 30-day recovery window,
successful source/destination restore proofs and either
`RECONCILED_CLEAN`, or `DISPUTED_CLEAN` with immutable dispute evidence
exported, accountable owner, deadline and reserved maximum liability. A billing
dispute alone never keeps execution resources alive indefinitely.

Actions artifacts expire under the frozen repository retention policy; the
checkpoint cleanup broker cannot delete them. No early Actions-artifact deletion
is required. A later ADR that requires early deletion must introduce a fifth
disjoint App with `actions:write`, an exact artifact-ID manifest and
independent approval.

The three-day ephemeral-worker clock starts at upload and never waits for block
verification. Before a worker is released, every sealed batch needed to
reconstruct its result must have a verified durable source or destination
checkpoint copy and chained receipt. Block merge is planned to finish well
inside retention, but an expired Actions artifact is reconstructed from
checkpoints; GitHub retention is never treated as conditional storage.

Cleanup workflow requirements:

- dry-run is mandatory;
- a dedicated external cleanup broker route and `gtbi-cleanup` environment are
  disabled outside an approved batch, cannot modify code or upload/overwrite
  objects and are reconciled to prove no non-delete operation occurred;
- explicit allowlist of deletion-candidate IDs and immutable object-version
  digests; canonical object IDs are a denylist, never deletion targets;
- explicit protected active run IDs;
- pagination checkpoint;
- maximum `500` deletions per invocation;
- API rate-budget check before each page;
- resumable cursor;
- deletion log;
- approval receipts, role/ruleset snapshots, object-store access logs and deletion
  evidence replicated with the canonical result and retained for the same
  lifetime;
- no deletion while a dependent campaign is active;
- admission, dispatch and cleanup share one authoritative
  `asset_dependency_fence_registry`. A cleanup batch atomically acquires an
  exclusive generation/fencing token before its final inventory; while held,
  every campaign admission/dispatch touching those assets is rejected. The
  broker revalidates the same token immediately before each object deletion
  and the registry releases it only after the terminal deletion/abort receipt.
  A stale generation or admission that raced the fence aborts without delete;
- an immutable deletion manifest, cumulative deletion ceiling and fresh
  repository-owner environment approval for every batch;
- a new inventory reconciliation immediately before each destructive batch;
- automatic credential revocation and environment disablement after each
  batch, whether it succeeds or fails.

### PREV7-0402, PREV7-0403, PREV7-0404 And PREV7-0405: Local Inventory And Canonical Structure

Target:

```text
$env:USERPROFILE\AuroraWorkspace\
├── primary\
│   └── aurora-main\
├── worktrees\
│   ├── active\
│   ├── review\
│   └── archive-pending\
├── manifests\
├── downloads\
│   ├── temporary\
│   └── verified\
└── logs\
```

Large local read-only cache:

```text
E:\AuroraData\
├── artifact-cache\
├── verified-copies\
├── manifests\
└── quarantine\
```

These are optional administrative locations for this Windows machine. They are
never embedded in Python, workflow YAML, manifests or scientific identities.
Aurora code continues to resolve runtime locations through
`aurora.core.runtime_paths` and approved environment variables.

Migration rules:

1. Close active Codex tasks and terminal processes that reference a worktree.
2. Inventory all worktrees and untracked files.
3. Preserve dirty changes with commits, patches or bundles.
4. Create a fresh primary editing clone instead of moving an unknown old
   clone.
5. Verify remote URL and `main` SHA.
6. Recreate one active worktree at a time.
7. Validate each worktree before proceeding.
8. Before any copy or quarantine, classify every untracked/dirty regular file
   with the licence/evidence secret scanner. Active credentials, tokens,
   private keys or signed URLs are never copied as ordinary files: revoke/
   rotate them first and retain only redacted incident/rotation receipts.
   Licensed/private data is copied only to its approved encrypted custody class
   with least-privilege ACL and no sync/backup leakage. Then create a per-path
   manifest containing classification, type, size, modification time,
   Git/worktree identity when applicable and SHA-256; preserve the permitted
   durable copy outside quarantine.
9. Restore that durable copy to a separate test path, recompute the manifest
   and prove byte identity before moving the redundant source to quarantine.
10. Keep quarantine for at least `30` complete days.
11. Delete only after a second inventory, a fresh restore proof, zero live
    references and explicit approval bound to the exact per-path manifest.

Desktop and Downloads are never canonical sources.

Gate G4 passes when the GitHub/canonical structure is green and local
administration has exactly one terminal disposition:
`reorganized_verified` or `unavailable_deferred_noncanonical`. In the latter
case no deletion is attempted and the deferred local chain remains
administrative, not a blocker for G5/G6A/G6B/G7 or project safety.
Specifically:

- when local state is available, there is one primary local editing clone,
  each active branch has one worktree, every dirty change is preserved and no
  active task references a removed path;
- when unavailable, the current signed unavailable receipt proves canonical
  execution and evidence are remote and no local cleanup/deletion was claimed.
  The frozen `LOCAL_ADMINISTRATION` branch generates one task-specific
  alternative-completion receipt for each `PREV7-0402` through
  `PREV7-0407`; each states `action_performed=false`,
  `canonical_dependency=false`, the common unavailable-receipt digest and the
  later administrative successor trigger. Thus the static tasks and G4/G10
  reconcile without pretending the laptop was cleaned;
- GitHub inventory has no unknown items.

## 16. Gate G5: Scientific Contract And Oracles

G5 freezes science and accepts only `PREV7-0505` semantic branch coverage/
mutation evidence and `PREV7-0506` exact historical Oracle-B evidence. It does
not assert optimized-engine equivalence. Synthetic optimized-versus-reference
equivalence belongs to G6A implementation checks; historical real-data
equivalence belongs exclusively to the authorized G7 canonical smokes.

### PREV7-0502: Resolve Or Replace PR 20

Current audited pull request:

```text
url=https://github.com/trading-optimizer-lab-org/aurora/pull/20
title=Complete universal GitHub performance recovery and scale validation
state=open
mergeable=true
failed_checks=12
```

Current failing groups:

```text
bandit
mypy
precommit
ruff-full
pytest Linux
pytest Windows
```

Actions:

1. Refresh the PR head SHA and checks.
2. Classify every failure as introduced or pre-existing.
3. Review the performance framework independently from GTBI.
4. Merge only the verified reusable parts.
5. Replace the PR with smaller PRs if unrelated failures or scope make review
   unsafe.
6. Record which PR and commit supplies every dependency used by V7.

### Contract

Freeze in a versioned machine-readable file:

```text
config/gtbi/contracts/fast_strict_v6_performance_v2.json
```

That file is the registered `scientific_contract_v1` object, not a prose
summary. Its top-level payload is exactly:

```text
schema_version
product
evaluation_identity
reference_semantics_id
train_start_policy
train_end
validation_start
validation_end
historical_exclusion_start
historical_post_validation_start
selection_split
scoring_profile
min_selection_trades_per_year
trading_contract_digest
entry_signal_semantics_digest
exit_semantics_digest
fill_and_next_session_open_policy_digest
position_state_policy_digest
cost_slippage_policy_digest
trade_attribution_policy_digest
annual_metric_registry_digest
score_formula_manifest_digest
final_filter_registry_digest
numeric_state_and_ordering_policy_digest
universe_and_eligibility_policy_digest
universe_temporal_model
adjustment_policy_sha256
adjustment_temporal_model
calendar_policy_sha256
currency_policy_sha256
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
randomness_and_seed_policy_digest
scientific_schema_set_digest
canonical_serialization_profile_digest
hash_domain_registry_digest
contract_digest
```

It uses `GTBI_SCIENTIFIC_CONTRACT_V1`, `self_field` storage and omits only
`contract_digest` from its canonical preimage. Every referenced policy digest
resolves through the contract's immutable member manifest to either a
registered typed object or exact versioned file bytes with path, size,
SHA-256 and Git blob identity. The manifest is exhaustive: a feature, signal,
simulation, metric, filter, score, tie-break, output or temporal dependency
used by either engine but absent from the contract is fatal. Code/runtime/data,
strategy pack and per-job execution profiles remain separate context
identities and do not enter this scientific contract.

The dispatchable immutable input closure is registered
`scientific_manifest_v1`:

```text
schema_version
campaign_id
scientific_context_key_digest
contract_digest
data_digest
strategy_pack_digest
policy_hash
execution_plan_digest
ordered_assets[
  asset_role, asset_ordinal, logical_schema_id,
  object_or_raw_content_digest, byte_size, classification
]
asset_count
scientific_manifest_digest
```

The schema fixes the complete allowed/required role registry. It contains every
scientific input and every immutable pre-execution planning object needed by a
worker or offline verifier, including all contract/policy members, data and
partition identities, strategy payloads, feature demand, per-unit symbol-
eligibility and complete-reuse objects, canonical/global maps, physical
layout, cost profile, execution/matrix/assignment/reduction plans, approved
numerical and hardware registries, dependency/runtime identities and schema/
serialization registries. Repeated roles use contiguous ordinals; rows are
sorted by `(asset_role, asset_ordinal)` and no mutable provider locator enters
the preimage. A separate authenticated locator map resolves each digest to an
immutable source and independent-destination object version.

The manifest uses `GTBI_SCIENTIFIC_MANIFEST_V1`, `self_field` storage and
omits only its own digest. Its repeated top-level digests must equal the
corresponding role rows. A missing, extra, duplicate, mutable or unresolved
asset blocks dispatch. The workflow receives only the manifest digest plus an
authorized immutable locator and derives every effective input from the
restored typed object.

The audited candidate baseline at V6 code SHA
`cb80c5065c127322a303d58aea0f6c05337a6c9e` contains these hard conditions:

The normative producer chain for final run `29162930823` is frozen before any
formula is copied:

```text
.github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml
  mode=optimized_evaluation_v6_merge_existing
.github/workflows/gtbi-fast-strict-v6-worker.yml
scripts/global_technical_buy_indicator.py
scripts/gtbi_fast_strict.py
scripts/run_gtbi_fast_strict_worker.py
scripts/merge_gtbi_fast_strict_block.py
scripts/gtbi_fast_strict_results.py
scripts/merge_gtbi_fast_strict_final.py
scripts/validate_gtbi_fast_strict_artifact.py
requirements/gtbi-fast-strict.lock
```

The run API path, workflow input payload, sparse-checkout file set, command
arguments and every file above are bound to that exact commit in the recovered
producer manifest. In particular, alias-expanded leaderboard order comes from
`gtbi_fast_strict_results._rank_leaderboard`; filtered order comes from
`gtbi_fast_strict_results._filtered_leaderboard`; and final best fields come
from `merge_gtbi_fast_strict_final`. Similar helper or merger functions
elsewhere in the same historical tree are non-authoritative unless the run's
actual call graph proves they executed. `PREV7-0503` freezes a static and
runtime call-graph receipt so a same-named legacy path cannot silently redefine
V6 semantics.

```text
validation_min_trades_each_year>=100
validation_avg_trade_return_positive_years=10_of_10
validation_median_trade_return_positive_years>=7_of_10
validation_profit_factor_each_year>=1.05
validation_global_median_trade_return_pct>0
validation_global_profit_factor>=1.4
validation_trades_per_year>=150
validation_global_avg_trade_return_pct<=5*validation_global_median_trade_return_pct
validation_max_positive_profit_contribution_share<=0.25
train_2003_2010_avg_trade_return_positive_years=8_of_8
train_2003_2010_profit_factor_each_year>=1.05
train_2003_2010_avg_trade_return_pct_each_year>=0
```

The contract freezes the following V6 metric semantics, not merely the names
and thresholds:

```text
selection_split=validation
scoring_profile=strict_quality
min_selection_trades_per_year=100
train_years =
  max(
    (Timestamp(2010-12-31)
      - earliest parseable train trade exit_date).days / 365.25,
    1.0)
  when at least one parseable train exit exists
train_years_fallback_when_no_parseable_train_exit =
  max(
    (Timestamp(2010-12-31)-Timestamp(1900-01-01)).days/365.25,
    1.0)
validation_years =
  max((Timestamp(2020-12-31)-Timestamp(2011-01-01)).days/365.25, 1.0)
combined_years = max(train_years + validation_years, 1.0)
validation_trades_per_year =
  count(validation return_pct rows surviving
        pd.to_numeric(errors="coerce").dropna()) / validation_years
validation_min_trades_each_year =
  min(reindexed validation yearly trades over every integer year 2011..2020)
validation_avg_trade_return_positive_years =
  count(reindexed yearly avg_trade_return_pct > 0)
validation_median_trade_return_positive_years =
  count(reindexed yearly median_trade_return_pct > 0)
validation_profit_factor_each_year =
  sum(finite positive trade returns)
  / abs(sum(finite negative trade returns))
validation_max_positive_profit_contribution_share =
  annual_profit[year] =
    fill_missing(yearly_avg_trade_return_pct, 0) * yearly_trades
  max(annual_profit)
  / sum(annual_profit values strictly > 0)
  when that positive sum > 0
  otherwise 1
train_2003_2010_avg_trade_return_positive_years =
  count(reindexed yearly avg_trade_return_pct > 0 over 2003..2010)
```

Every missing yearly row is reindexed into the required range with
`trades=0` and non-trade metrics missing, so it necessarily fails the trade
minimum and positive-year requirements. The frozen annual-PF minimum uses
Pandas' default skip-NaN reduction: an individual missing year's PF is omitted
when another non-missing annual PF exists, while an all-missing result becomes
the failing negative-infinity default. This quirk does not rescue a missing
year because the other hard annual conditions already fail. Global summaries
convert
`return_pct` with `pd.to_numeric(errors="coerce")` and drop only NaN/missing
values. The preserved V6 global-summary code does not explicitly remove
positive or negative infinity; those rows remain in the global trade count and
follow the frozen Pandas/NumPy arithmetic behavior. By contrast, the annual
summary first groups every row having a parseable exit year and increments
that year's `trades`, then includes a row in annual return, win-rate and
profit-factor calculations only when its converted return is finite. Annual
holding-day means likewise use only finite converted holding values, while
their annual `trades` denominator remains the full parseable-exit-year row
count. This asymmetric global/annual behavior is covered by executable
fixtures even when the authenticated V6 artifact contains no such row. A win
is strictly `return_pct>0`. Profit factor is positive-return sum divided by the
absolute negative-return sum. A global summary with no surviving converted
return recursively emits the empty-summary missing metrics; with at least one
surviving return and no negative return it emits positive infinity. An annual
bucket with closed trades but no finite return emits missing average, median
and win rate but positive-infinity PF. Global trade standard deviations use
`ddof=0`; Sharpe and Sortino
multiply by
`sqrt(max(trades_per_year,1))`, with Sortino using negative-return deviation
when at least two losses exist and the overall deviation otherwise.
The input train range still begins at the first eligible session in the frozen
pack, but V6's train metric annualization begins at the earliest parseable
train trade exit, not at that first input session; a no-train-exit candidate
uses the unusual `1900-01-01` fallback above. Combined summary annualization
uses the exact sum of those train and validation durations.
Holding statistics independently apply
`pd.to_numeric(errors="coerce").dropna()` to all `holding_days` rows; they are
not inner-joined to the surviving-return subset. Exit-year concentration uses
the original selected-split trade-frame row count as its denominator. These
two denominators are frozen separately and fixtures include a row with a
missing return and a row with a missing holding duration.

V6 `validation_max_drawdown_pct` is not a shared-capital portfolio drawdown.
It compounds the complete-return sequence in the exact frozen V6 row order:
historical execution-pack symbol iteration order, then each symbol's simulator
trade order. It floors each gross factor at `1e-12`, accumulates log returns and
measures drawdown from the running log-equity maximum. V7 preserves this
apparently unusual order for equivalence and labels the field
`v6_trade_sequence_max_drawdown_pct`; the legacy column remains a byte-
compatible alias. A future calendar-ordered portfolio drawdown belongs only to
the separate Clean Portfolio product.

The validation concentration check above is profit contribution, whereas the
V6 ranking score's `return_concentration` is the maximum count of selected-
split exits in one exit year divided by total selected-split trades. They are
different fields and cannot be substituted.

The authoritative Fast Strict V6 leaderboard `score` is
`_strict_quality_score`, because the executed
`scoring_profile=strict_quality` path unconditionally replaces the earlier
generic candidate score. It uses the following field-specific finite defaults:

```text
adjusted =
  finite(adjusted_return_time_risk)
  otherwise -1000000
median =
  finite(validation_median_trade_return_pct)
  otherwise 0
pf =
  min(
    finite(validation_profit_factor) otherwise 0,
    5)
yearly_trades =
  min(
    finite(validation_trades_per_year) otherwise 0,
    500)
concentration =
  finite(validation_max_profit_contribution_share)
  otherwise 1
strict_quality_pass =
  Python bool(row.get("strict_quality_pass"))
failure_count =
  float(row.get("strict_quality_failure_count", 99))
validation_positive_years_score_component =
  float(row.get("validation_positive_years", 0))
validation_median_positive_years_score_component =
  float(row.get("validation_median_positive_years", 0))
train_positive_years_score_component =
  float(row.get("train_2003_2010_positive_years", 0))
minimum_yearly_trades_score_component =
  min(float(row.get("validation_min_yearly_trades", 0)), 150)

if strict_quality_pass:
  score =
      1000000
    + adjusted * 10000
    + median * 100
    + pf * 10
    + yearly_trades * 0.1
    - concentration * 100
else:
  score =
      -1000000
    - failure_count * 10000
    + validation_positive_years_score_component * 500
    + validation_median_positive_years_score_component * 250
    + train_positive_years_score_component * 250
    + minimum_yearly_trades_score_component
    + median * 100
    + pf * 10
```

The first five score inputs use the finite helper shown above. The failure
count and four annual-count/minimum inputs use direct Python `float` conversion
with only the named absent-key defaults; V6 applies no finite cleaning or lower
clipping to them. A present NaN can therefore propagate to the score, while a
missing failure count becomes `99`. V7's typed schema rejects malformed
production rows before scoring, but the isolated reference adapter and
boundary fixtures preserve this legacy behavior. `strict_quality_failures` is
the semicolon join, without spaces, of failures in the exact condition order
listed above; neither merge nor reporting may reorder it.

The executed path first computes the legacy generic `_candidate_score` and its
minimum-yearly-trades override, then replaces that value with the strict score.
Those precursor calculations are not the final leaderboard ranking formula;
an optimized engine may omit them only after proving over the accepted input
domain that doing so cannot change an exception, diagnostic or output. The
contract freezes V6's current Python truth/default and non-finite behavior for
every authoritative score input through executable boundary fixtures; V7 does
not “clean up” those edge cases. The broader stability/near-miss selector in V6
source is diagnostic research output only. It never sets
`strict_quality_pass`, never enters `filtered_leaderboard.csv` and cannot
replace any hard condition above.

The serialized V6 compatibility CSV is an output oracle, not a lossless
formula-input store. Recomputing `score` from the decimal component columns in
that CSV differs from the stored score in `10,450` of `72,000` alias rows by
exactly one binary64 ULP at most; the largest observed absolute difference is
`2.3283064365386963e-10`. The complete ranking and best row are unchanged.
This is caused by independently serialized floating-point components and must
not be “repaired” by rewriting the preserved score. Exact score known-answer
fixtures therefore freeze the pre-score binary64 component bit patterns
(hexadecimal form), field-specific defaults and Python operation order
captured from the isolated V6 reference. Oracle B compares the authoritative
stored score/output directly. A diagnostic recomputation from compatibility
CSV may assert `ulp_distance<=1` and identical ordering, but can never replace
the exact reference-output comparison or define a new tolerance for V7
results.

Its audited adjusted metric is:

```text
validation_global_avg =
    finite(validation_avg_trade_return_pct)
    otherwise negative_infinity
holding =
    max(
      finite(validation_avg_holding_days) otherwise 0,
      1)
drawdown =
    max(
      abs(finite(validation_max_drawdown_pct) otherwise 0),
      0.01)
adjusted_return_time_risk =
    validation_global_avg / (holding * drawdown)
    when validation_global_avg is finite
    otherwise negative_infinity
```

Unfiltered ranking is Pandas
`sort_values(["score","candidate_id"], ascending=[False,True],
kind="mergesort", na_position="last")`; filtered ranking uses the same stable
operation over `["adjusted_return_time_risk","candidate_id"]`. The explicit
`na_position="last"` records the executed Pandas default instead of leaving
missing/NaN placement to another implementation.

V6 summary selection follows the actual Fast Strict final merger:

```text
best_candidate_id:
  first row of score-ranked leaderboard

best_filtered_candidate_id:
  first row of filtered leaderboard ordered by
  adjusted_return_time_risk DESC, candidate_id ASC
```

`best_adjusted_return_time_risk` is the adjusted metric of
the score-best `best_candidate_id`; despite its legacy name, it is not
necessarily the maximum adjusted metric. V7 adds separate, non-ranking
diagnostics `max_adjusted_candidate_id` and `max_adjusted_return_time_risk`.
They select finite adjusted values by
`adjusted_return_time_risk DESC`,
`validation_median_trade_return_pct DESC`, then `candidate_id ASC`, and are
null/missing when no finite value exists. These diagnostic fields do not alter
leaderboard order, final filters or legacy best selection.

These values are a reconciliation checklist, not authority by prose. Before
freezing the contract, `PREV7-0503` compares them with the V6 artifact
manifest, the exact V6 source tree and the recovered dependency chain. Any
difference blocks G5 and is resolved explicitly; it is never silently adopted.

### Engine Equivalence Is Not Strategy Confirmation

G6A and G7 validate implementation equivalence, coverage, deterministic
selection and operational correctness. They do not establish that the selected
strategy has confirmatory out-of-sample efficacy. Validation 2011-2020 has
already been reused to compare and rank a large family, and historical
post-2020 evidence has already been contaminated by prior inspection.
Therefore every completed or diagnostic `summary.json`, equivalence report and
human-facing result handoff carries:

```text
engine_equivalence_confirmed
strategy_selection_evidence=exploratory
validation_reused_for_selection=true
confirmatory_strategy_validity=false
multiple_testing_original_candidates=72000
multiple_testing_canonical_candidates=3600
```

`engine_equivalence_confirmed` is a compatibility alias and must equal
`optimized_vs_reference_equivalence_confirmed` byte-for-byte in every result
summary and equivalence report that claims historical equivalence. The
pre-execution `scientific_manifest_v1` contains neither field because it cannot
contain a future result. Accepted G7 output
requires both to be `true`; before `PREV7-0702`, G6A records both as `false` and
uses only `synthetic_engine_equivalence_confirmed=true`. Incomplete or
diagnostic output keeps the historical aliases false. A disagreement is a
schema and acceptance failure, never a third scientific state.

The words `validated`, `approved`, `passing` and `best` refer only to the frozen
V6 engine/filter contract unless they are explicitly qualified otherwise.
Promotion as a confirmatory investment result is prohibited without a new
forward period whose first market session was locked before observation under
the two-approval forward-lock protocol.

V7 additionally emits a separate, non-gating selection-bias diagnostic over
the complete set of `3600` canonical candidates. Its method, candidate family,
temporal/transversal dependence treatment, block-resampling unit, random seeds,
confidence construction and multiplicity procedure are frozen before any
diagnostic result is calculated. The diagnostic never changes V6 filters,
ranking, best-row selection or equivalence acceptance; it quantifies how much
confidence is lost by searching many dependent variants and is labelled
exploratory rather than presented as a repaired forward test.

Freeze the diagnostic independently in:

```text
config/gtbi/contracts/selection_bias_diagnostic_v1.json
config/gtbi/schemas/selection_bias_diagnostics.schema.json
config/gtbi/contracts/canonical_serialization_v1.json
config/gtbi/contracts/hash_domain_registry_v1.json
```

The method contract includes:

```text
method_version
method_digest
candidate_set_digest
canonical_candidates_expected=3600
aliases_excluded=true
target_statistic
null_hypothesis
dependence_model
resampling_unit
block_length
bootstrap_draws
prng
effective_seed
nonfinite_policy
missing_candidate_policy
multiplicity_method
confidence_method
selection_scope=current_frozen_pack_only
prior_search_history_complete
non_gating=true
exploratory=true
```

### Canonical Serialization And Hash Domains

Every scientific JSON digest uses the frozen
`canonical_serialization_v1.json` profile and a registered domain from
`hash_domain_registry_v1.json`. The profile is RFC 8785 JSON Canonicalization
Scheme after schema-driven typed pre-normalization:

- object members use the RFC 8785 UTF-16 code-unit ordering and arrays preserve
  their declared order;
- output is UTF-8 without BOM or insignificant whitespace;
- strings contain valid Unicode scalar values, are not silently normalized,
  and reject lone surrogates or invalid encodings;
- ordinary integers are restricted to the exact interoperable range
  `[-9007199254740991,9007199254740991]`; a schema that genuinely needs a
  larger integer uses the explicit typed decimal-string representation defined
  by the profile;
- ordinary non-integer numbers are finite IEEE-754 binary64 values serialized
  by RFC 8785's shortest round-trip rule;
- negative zero canonicalizes to numeric zero where the schema declares the
  sign semantically irrelevant and is rejected otherwise;
- NaN and infinities are never JSON numbers; a schema represents them with its
  frozen typed state object or a null value plus an explicit state field;
- dates, timestamps, decimal money, digests and identifiers use their
  schema-defined normalized string forms before canonicalization.

No implementation-local `json.dumps` default, locale, Decimal rendering or
Unicode normalization is accepted as canonical. Each digest is:

```text
SHA-256(UTF8(registered_domain_string) || one literal 0x00 byte ||
        JCS(typed_pre_normalized_payload))
```

The delimiter is one byte with hexadecimal value `00`, not the two characters
backslash and zero. The serialization profile and domain registry are bootstrap
objects. Their identities are exactly:

```text
canonical_serialization_profile_digest =
  SHA-256(exact bytes of config/gtbi/contracts/canonical_serialization_v1.json)

hash_domain_registry_digest =
  SHA-256(exact bytes of config/gtbi/contracts/hash_domain_registry_v1.json)
```

The exact byte stream includes its encoding and final-newline state. Repository
path, Git blob ID and tree digest are recorded in separate manifest fields and
are never concatenated into either bootstrap hash. Neither bootstrap object
invokes itself or the other, and the registry contains no self-digest. Every
scientific asset, result, evidence and runbook manifest carries both bootstrap
digests; CI rejects a missing or mismatched value before interpreting any
registered-domain digest. After those two raw-byte identities are verified,
all registered object digests use the formula above. Domain strings are unique,
versioned and centrally registered; reusing one domain for a different object
type is a schema error.
The profile ships known-answer vectors for reordered objects, Unicode,
boundary integers, binary64 values, negative zero, typed non-finite states,
lists and cross-domain separation. Bootstrap known-answer vectors include the
exact input byte hex, expected SHA-256, repository path and independent Git
blob/tree identity for both files.

`method_digest` is not hashed recursively. Its registered domain is
`gtbi-selection-bias-method-v1`; its payload is the complete typed method
contract with `method_digest` omitted. The stored value must equal the formula
above. Changing any other method field changes the digest; changing only input
object order does not.

Its result reconciles exactly the canonical candidate set and binds contract,
data, canonical-map and canonical-leaderboard digests. Reordered input produces
identical typed results and digest. `prior_search_history_complete=false` unless
the project can authenticate every earlier human and machine search; therefore
the diagnostic never claims to correct undisclosed prior selection, repeated
inspection or researcher degrees of freedom.

The frozen scientific contract also includes:

- dates;
- universe identity;
- eligibility;
- entry rules;
- exit rules;
- costs;
- next-session-open semantics;
- tie ordering;
- annual aggregation;
- filters;
- complete V6 `score` formula, component weights, units, clipping and
  missing/non-finite defaults;
- ranking;
- seed policy;
- float and rounding policy;
- locked policy.

`PREV7-0503` generates a machine-readable score/metric formula manifest from
the exact preserved V6 source and validates it with hand-calculated boundary
fixtures. A prose label such as “composite score” is not a scientific
definition and cannot authorize V7.

The frozen V6 annual-output contract includes:

```text
trade_split_and_year_attribution=exit_date
train_exit_date<=2010-12-31
validation_exit_date=2011-01-01..2020-12-31
train_validation_simulation_mode=single_continuous_stateful_frame
train_validation_boundary_state_reset=false
open_position_at_2010_12_31=carries_into_validation_until_V6_exit_rule
cross_boundary_trade_split=validation_when_exit_date>=2011-01-01
validation_feature_warmup=full_authenticated_pre_validation_history
validation_warmup_rows_are_not_validation_outcomes
frame_terminal_open_position=V6_end_of_data_exit_on_last_included_bar
frame_terminal_exit_price=last_bar_open_when_after_entry_and_valid_otherwise_last_bar_close
signal_on_terminal_bar_without_next_session=no_entry
yearly_row_emitted_only_when_closed_trades>0
win_rate_unit=fraction_0_to_1
profit_factor=sum_positive_returns/abs(sum_negative_returns)
profit_factor_when_no_negative_return=positive_infinity
annual_return_metrics_accept_finite_converted_returns_only
annual_trades_count_all_rows_with_parseable_exit_year
strict_filter_numeric_policy=V6_finite_conversion_with_field_specific_default
spy_return_pct=(last_available_close/first_available_close-1)*100
spy_calendar_group=year_of_session
scientific_price_columns=open_high_low_close_volume
adj_close_carried_but_not_consumed_by_V6_evaluator
commission_pct=0
slippage_pct=0
simultaneous_positions_per_symbol=1
exit_trigger_priority=stop_loss_take_profit_trailing_stop_exit_ma_market_exit_max_holding
same_bar_stop_and_take_priority=stop_loss
post_exit_signal_on_exit_bar_may_reenter_at_following_session_open
```

The output schema defines one canonical token and CSV representation for
positive infinity and missing numeric values. Parsers, Parquet, CSV and merge
round trips must preserve the same semantic value. A missing required year is
not a yearly row, but the hard filter reindexes it internally to zero trades.

The frame is simulated once in chronological order; 1 January 2011 is an
attribution boundary, not a portfolio, signal or indicator reset. A position
opened in train and closed in validation is one validation trade because
attribution uses exit date. Feature warm-up may read authenticated pre-2011
history but no warm-up row is counted as a validation outcome. Oracle-B
source/run evidence must confirm these exact values before G5; a different
preserved V6 behavior is a contract mismatch and blocks this V7 rather than
being silently adopted.

V6 strict filtering converts required numeric values through its frozen
finite-only helper. Therefore a non-finite global profit factor uses the
failing default, and an all-infinite annual-profit-factor minimum also uses the
failing default. V7 preserves this edge behavior even though positive infinity
would ordinarily mean no losses. Correcting it would be a separately approved
scientific change and a differently named baseline.

The preserved V6 execution frame is physically bounded before simulation.
Its simulator closes a position still open at the frame's terminal included
bar with `exit_reason=end_of_data`; a signal on that terminal bar cannot enter
because no next-session open exists. This rule applies identically whether the
terminal row is a natural source-history end or the historical pack boundary.
On every ordinary bar it updates high-water first, applies the trigger priority
listed above, and executes a triggered exit at the next included session's
valid open, falling back to that session's close only when the open is
non-finite or non-positive. If stop and take-profit barriers are both touched
on one bar, the stop wins. After an exit, a signal on the exit bar may open a
new position at the following session; earlier overlapping signals are
discarded. A penultimate-bar entry that is still open at the terminal bar exits
on that terminal bar's close because entry and terminal exit indices coincide.
The evaluator charges no commission, spread or slippage, and consumes raw
`open`, `high`, `low`, `close` and `volume`; it carries `adj_close` in the
frame but does not use it in V6 signal, simulation or benchmark calculations.
`PREV7-0503` must cite the exact preserved source lines and a hand-calculated
fixture before freezing this contract. If the recovered V6 source or Oracle B
disagrees, G5 is blocked; no guessed default is allowed.

The historical pack still records genuine source-history end, artificial
pack-boundary end and `unknown` as provenance. Unknown classification blocks
any claim about delisting or natural history completeness, but it does not
change the frozen V6 terminal-frame execution rule. No post-2020 existence,
price or status is consulted to classify or execute a historical trade.

### Two Independent Oracles

Oracle A, semantic:

- minimal synthetic immutable fixtures;
- manually defined expected signals, entries, exits and metrics;
- tests algorithm semantics;
- independent implementation;
- no shared optimized helper functions.

Oracle A is not accepted from one illustrative fixture. Before G5, generate:

```text
config/gtbi/contracts/semantic_oracle_coverage_manifest.json
config/gtbi/schemas/semantic_oracle_coverage_manifest.schema.json
```

The manifest inventories every effective entry, market-regime, stock-trend,
relative-strength, guardrail, fill, stop, exit, terminal-frame, annual metric,
filter, score and tie-order primitive/branch used by all `720` signal bundles
and five exit variants. Each row binds hand-calculated fixture IDs, expected
typed outputs, boundary values, missing/non-finite/default cases and an
independent reviewer receipt. Required effective-branch coverage is `100%`.
Mutation testing uses a frozen operator manifest; every non-equivalent mutant
must be killed, while any claimed equivalent mutant requires independent
classification and evidence. Shared wrong interpretations cannot pass merely
because reference and optimized engines agree.

The denominator is generated mechanically from the preserved V6 reference
tree by a versioned AST/bytecode branch registry. It freezes reference code
SHA, tree, entrypoint, dependency lock, runtime and the exact effective-branch
set before fixtures are counted. Manual omission of a branch cannot improve
coverage.

Oracle B, historical:

- approved V6 output files;
- tests migration equivalence against known outputs;
- only valid if the exact input identity is known;
- if inputs are incomplete, it is evidence of output preservation, not full
  rerun reproducibility.

Oracle B normalizes every required historical file/table independently under
its schema: exact file set, key columns, row order, types, missing/non-finite
representation and value digest. `exact_match=true` only when every required
output exists and every normalized row/field difference count is zero. A
single aggregate package digest or leaderboard-only match is insufficient.

If the exact V6 inputs are recovered, Oracle B must reproduce the approved V6
historical output. If they are not recovered, Oracle B is formally
`unavailable_missing_original_inputs`; this V7 remains `NO-GO`. A separately
named snapshot/reference engine may be proposed only for a different
product/campaign and never substitutes for Oracle B or this plan's V6 identity.

The reference engine is itself an independently identified executable asset,
not a mode flag inside the optimized engine. Every equivalence report, runbook
core and reference result binds:

```text
reference_engine_code_sha
reference_engine_tree_digest
reference_entrypoint_digest
reference_dependency_lock_digest
reference_runtime_digest
reference_engine_isolation_policy_digest
```

The reference tree is the preserved V6 implementation. A separately
implemented frozen reference tree when Oracle B is unavailable belongs to a
different product/campaign and cannot satisfy this V7. An eligible reference tree may share
the scientific contract, input bytes and output schema, but it cannot import,
call, monkeypatch or dynamically load optimized feature, signal, simulation,
metric, filter, scheduling or merge modules. Its entrypoint runs in a separate
process and environment from the optimized engine. The isolation policy lists
the only permitted shared data/schema packages, and static import-graph plus
runtime module-inventory checks enforce that boundary.

`PREV7-0506` constructs the executable reference without reimplementing or
copy-pasting V6 logic into V7. It restores the exact source bundle rooted at
commit `cb80c5065c127322a303d58aea0f6c05337a6c9e`, verifies its tree and
`requirements/gtbi-fast-strict.lock`, and builds a separately content-addressed
reference image with the preserved Python `3.12` runtime and dependency
wheelhouse. The optimized V7 image uses its own lock and cannot mount the V6
source. `gtbi/reference_v6/entrypoint.py` is only a protocol adapter that
launches that immutable image and validates the normalized result contract; it
cannot import or execute V6 scientific modules inside the V7 process.

The reference-image manifest binds source bundle/tree, Dockerfile, Python
runtime, lock, wheelhouse, native libraries, image/layer digests, entrypoint
and isolation policy. It must name the exact executable path inside the
preserved V6 tree, module/command, working directory, fixed argument schema and
environment allowlist actually used by run `29162930823`; these values are
recovered from commit/workflow/run evidence and cannot be guessed, replaced by
a new adapter implementation or inherited from V7 defaults.
`reference_source_entrypoint_path`, `reference_source_command_digest` and
`reference_source_argument_schema_digest` are mandatory non-null manifest
fields. Oracle B runs the image in a distinct no-network job and
compares outputs only through the frozen file/table contract. A build from
`origin/main`, a reconstructed subset of V6, Python other than the preserved
runtime or the V7 lock is ineligible.

`equivalence_report.json` names both complete executable identities, input and
contract digests, comparison tolerances, row-level differences and isolation
evidence. A missing identity field, common result-producing implementation,
unexpected shared module or digest mismatch blocks G6A and G7. Independent
oracles mean independent executable paths; comparing an optimized path with
itself under two command-line flags is prohibited.

### New Forward Lock

Activation is a four-object protocol with no self-reference:

1. `forward_lock_proposal.json` is immutable and contains the historical base,
   contract, access policy and proposed activation rule, but no approval time.
2. `locked_approval_receipt.json` authenticates the independent locked
   approver and binds the proposal digest.
3. `owner_forward_authorization_receipt.json` authenticates the repository
   owner and binds the same proposal digest.
4. `forward_lock_activation.json` binds the proposal and both receipts, computes
   the later approval instant in UTC and records the first fully unobserved
   eligible session separately for every configured market.

The proposal records:

```text
proposal_created_at_utc
historical_base_snapshot_digest
contract_digest
access_policy
forward_lock_calendar_manifest_digest
configured_market_mics
activation_rule=first_market_session_whose_open_utc_is_strictly_after_later_required_approval
```

The locked approver is independent from the actor who created or accessed the
proposal. GitHub API evidence authenticates the approver ID and protected
environment review; repository-owner authorization is separately required.
The frozen calendar manifest identifies every market MIC, timezone, calendar
version, session-open/close UTC, holidays, half sessions and DST interpretation.
Let `approval_cutoff_utc=max(locked_approved_at_utc,
owner_authorized_at_utc)`. For each market, the first locked session is the
first session whose `session_open_utc > approval_cutoff_utc`; a session already
open or completed at approval is never pristine. The activation record contains
`proposal_digest,locked_approval_receipt_digest,owner_forward_authorization_receipt_digest,`
`locked_approved_at_utc,owner_authorized_at_utc,activated_at_utc,`
`approval_cutoff_utc,forward_lock_calendar_manifest_digest,`
`first_market_session_locked_by_market` and its digest,
`first_market_session_locked` and `future_data_namespace`.
`first_market_session_locked` is the minimum session-open UTC in the per-market
map, encoded as an RFC 3339 `Z` timestamp, and is only a global lower-bound
summary; symbol eligibility uses its
market-specific entry. A cross-market decision consumes no observation from a
market before that market's boundary. Future observations receive their own
snapshot digest and never mutate
`historical_base_snapshot_digest`. No ordinary `workflow_dispatch` can read
the forward namespace.

If no independent locked approver exists, `PREV7-0504` produces a hashed,
GitHub-attested decision:

```text
new_forward_available=false
forward_access_disabled=true
first_market_session_locked=null
first_market_session_locked_by_market_digest_or_null=null
forward_lock_calendar_manifest_digest_or_null=null
later_required_approval_utc_or_null=null
reason=no_independent_locked_approver
decision_created_at_utc
historical_base_snapshot_digest
contract_digest
actor_id
attested_no_forward_decision_digest
```

The implementer owns generation and verification of either output. A forward
manifest cannot become valid without the independent locked approver and
separate owner authorization; the no-forward output requires neither access to
locked data nor a fictional approval from a vacant role.

This allows historical work ending on `2020-12-31` to proceed without falsely
claiming that a pristine forward test exists.

### Immutable Task Remediation Generations

A terminal readiness task is historical evidence and is never reopened,
rewritten or given another attempt. If later evidence invalidates any terminal
task, its gate becomes red and the owning permanent controller appends an
immutable child `TASK_REMEDIATION-<parent-task-id>-<sequence>` to
`conditional_branch_registry.csv` and the hash-chained
`task_remediation_registry.jsonl`. The child records parent task/event/evidence
digests, discovery receipt, exact failed predicate, unchanged versus replaced
scope, approvers, deadline, rollback, acceptance command and successor evidence
digest. Each row also records schema version, remediation event ID, per-parent
sequence, previous remediation-event digest and `event_digest` under
`GTBI_TASK_REMEDIATION_EVENT_V1`, omitting only `event_digest`. A gate resolves
only the latest accepted generation for each parent;
older terminal events remain immutable provenance and can never satisfy the
current gate after invalidation. Child creation cannot change scientific
identity, expand authority or waive a predicate; such a change requires a new
plan/campaign identity. Sequence, stale-evidence, concurrent-child,
failed-child-successor and gate-red/green fixtures are mandatory.

### PREV7-0508: Register Output Consumers

The registry binds the exact complete `PREV7-0401` inventory digest and its
UTC cutoff. A later-discovered pre-cutoff consumer invalidates G5 and requires
an immutable conditional child task
`OUTPUT_CONSUMER_REMEDIATION-<sequence>`; terminal `PREV7-0508` is never
reopened and cannot receive a new attempt. Permanent controller `PREV7-0509`
appends each generation to
`output_consumer_remediation_registry.jsonl`, links it from
`conditional_branch_registry.csv`, records the discovery receipt,
migration/rollback tests and replacement registry digest, and makes G5 plus all
dependent gates `red` until the registered child is terminally done. The static
validator permits only children produced by `PREV7-0509`; arbitrary external
successors remain forbidden. A post-cutoff consumer cannot consume V7 until it
is added through the same reviewed child-task mechanism.
Every remediation row has schema version, event ID, sequence,
previous-event digest, inventory-cutoff digest, discovered-consumer identity,
discovery/migration/rollback/replacement digests, task/event linkage, actor and
`event_digest` under `GTBI_OUTPUT_CONSUMER_REMEDIATION_EVENT_V1`, with only
`event_digest` omitted.

Create:

```text
docs/readiness/gtbi-v7/output_consumers.csv
```

Required fields:

```text
consumer_id
consumer_type
repository_or_location
owner
input_path_pattern
required_columns_or_schema
current_version
target_version
migration_test
rollback
status
```

The inventory searches repository code, workflows, tests, notebooks,
documentation and known external handoffs. The repository owner must explicitly
record any external consumer that cannot be discovered by code search; absence
is never inferred from `no matches`. Every registered consumer gets a fixture-
based compatibility or migration test before G7, and no legacy output is
retired while its consumer status is unresolved.

Gate G5 passes when:

- G1B is green with a currently available independent scientific reviewer;
- `PREV7-0503` is owned and signed by that reviewer, and the `PREV7-0505` plus
  `PREV7-0509` evidence sets carry that reviewer's authenticated acceptance;
- contract is frozen;
- both oracle roles are clearly separated;
- applicable equivalence evidence is green;
- new forward lock exists or is explicitly deferred as blocked;
- output-consumer registry and migration-test plan are complete;
- `PREV7-0509` is done and its immutable registry has zero open remediation
  generations.

## 17. Gates G6A And G6B: GTBI Performance And Controlled Recovery

### V6 Performance Baseline

The last approved V6 performance evidence reported:

```text
strategies_requested=72000
canonical_strategies_evaluated=3600
strategies_resolved_by_dedupe=68400
timeouts=0
mean_seconds_per_canonical_strategy=13.53
mean_signal_seconds=3.79
mean_simulation_seconds=2.26
mean_feature_seconds=1.22
```

These values are reference observations, not permanent promises. The V7
benchmark must regenerate them from the preserved evidence and record its exact
run and manifest.

### Profile-Guided Optimization

Optimization starts from a GitHub-only representative profile, not from an
assumed bottleneck. `PREV7-0609` records two separate profiles:

```text
cold_start_profile:
  checkout
  runtime_image_pull
  asset_authentication
  asset_download
  verification
  decompression
  physical_data_load
  process_pool_start

steady_state_profile:
  feature_build
  signal_generation
  simulation
  annual_metrics
  serialization
  checkpoint_sealing
```

The representative batch contains every feature, signal, exit and expected-cost
bucket present in the 72,000-pack. A dedicated benchmark job may use deterministic
function profiling, sampled allocation tracing and per-phase RSS/I/O counters,
but profiling is disabled in canonical campaigns unless its measured overhead
is at most the accepted telemetry budget. Profile output contains only
allowlisted function/module identities, aggregate timings, allocation classes
and counters; it cannot emit rows, symbols, candidate parameters or trade
detail.

Each proposed optimization has an immutable A/B record containing:

```text
same_input_and_contract_digests
same_decoded_scientific_output_digest
profile_before
profile_after
cold_wall_before
cold_wall_after
warm_wall_before
warm_wall_after
runner_minutes_before
runner_minutes_after
peak_rss_before
peak_rss_after
artifact_bytes_before
artifact_bytes_after
```

An optimization is retained only when applicable equivalence checks are exact,
the repeated frozen benchmark is faster end to end and no accepted resource or
security bound regresses. Microbenchmark wins cannot override a slower final
artifact.

### Physical Data-Access Plan

The preparation workflow builds, from the same authenticated historical rows,
one or more candidate physical layouts whose decoded typed arrays are
scientifically identical. It benchmarks:

- projected columnar reads with row-group and symbol-partition pruning;
- compressed transfer versus decompression cost;
- read-only memory-mapped arrays;
- one decompression/load per job shared by persistent workers;
- bounded asynchronous prefetch of the next immutable partition;
- contiguous dtype-stable arrays for the actual feature-demand manifest.

No worker independently downloads or decompresses the same job-local input
four times. No speculative prefetch may exceed the disk/memory budget, extend
credential lifetime or alter deterministic assignment. The selected layout is
content-addressed, schema-versioned and bound to the source data digest; a
physical layout change never changes the scientific snapshot identity. Cold
end-to-end time, total transferred bytes and peak disk/RSS decide whether a
layout is accepted.

The selected layout is closed by registered
`physical_data_layout_manifest_v1`:

```text
schema_version
layout_id
layout_mode
data_digest
historical_execution_pack_digest
input_partition_manifest_set_digest
instrument_set_digest
feature_demand_manifest_digest
decoded_array_schema_digest
dtype_precision_and_missing_value_policy_digest
ordered_members[
  relative_path, source_partition_id, projection_id,
  compression_codec, byte_size, sha256,
  decoded_row_count, decoded_row_key_set_digest
]
member_count
decoded_global_row_key_set_digest
decoded_scientific_content_digest
physical_data_layout_digest
```

Paths are normalized relative POSIX paths and rows use canonical path order.
Members are immutable exact bytes; their decoded row-key subsets are disjoint
and union exactly to the execution-pack row set. The decoded schema, values,
ordering, dtype, missing-value state and temporal availability must match the
authenticated source layout, as proven by the separately signed
`physical_data_layout_equivalence_receipt_digest`. The manifest uses
`GTBI_PHYSICAL_DATA_LAYOUT_MANIFEST_V1`, `self_field` storage and omits only
its own digest. Compression, row groups, projections or memory mapping may
change this physical digest, but can never change `data_digest` or the decoded
scientific-content digest.

V7 optimizes in this strict order:

1. Scientific correctness.
2. Complete coverage.
3. Zero lost units.
4. Zero unresolved technical failures.
5. Wall time to a verified final artifact.
6. Runner minutes.
7. Useful four-vCPU saturation.
8. Peak memory.
9. Artifact count and bytes.
10. Selective recovery cost.

The 72,000-strategy input is closed by registered
`strategy_pack_manifest_v1`:

```text
schema_version
pack_id
pack_format
record_schema_digest
expected_record_count
ordered_source_files[path, byte_size, sha256, first_source_position,
  last_source_position, record_count]
ordered_records[source_position, strategy_id, candidate_id,
  canonical_strategy_payload_digest]
strategy_id_set_digest
candidate_id_set_digest
strategy_candidate_bijection_digest
strategy_pack_digest
```

Its four child objects are exact:

```text
canonical_strategy_payload_v1:
  schema_version
  record_schema_digest
  normalized_complete_strategy_record
  canonical_strategy_payload_digest

strategy_id_set_v1:
  schema_version
  ordered_strategy_ids
  strategy_count
  strategy_id_set_digest

candidate_id_set_v1:
  schema_version
  ordered_candidate_ids
  candidate_count
  candidate_id_set_digest

strategy_candidate_bijection_v1:
  schema_version
  ordered_pairs[strategy_id, candidate_id]
  pair_count
  strategy_id_set_digest
  candidate_id_set_digest
  strategy_candidate_bijection_digest
```

The complete normalized strategy record includes identity and provenance fields
defined by the frozen source-record schema as well as effective rules; it is not
the metadata-excluding `economic_hash`. Each object uses its corresponding
registered domain, `self_field` storage and omits only its own digest. ID sets
and bijection pairs are sorted by canonical unsigned UTF-8 bytes. Every pack
record references one restored payload object, every ID appears once, both set
counts equal `expected_record_count`, and the bijection projects exactly to both
sets. Neither a scalar count nor the later economic dedupe map can satisfy this
source-pack closure.

Source positions are contiguous from zero across the complete ordered pack;
paths and IDs use canonical unsigned UTF-8 order where their schema calls for
sorting. `strategy_id` and `candidate_id` are each unique and their mapping is
bijective. Every canonical strategy payload is parsed under the frozen record
schema, normalized before hashing and reconciled to its exact source bytes and
source position. A reordered, duplicated, omitted, extra, malformed or
differently normalized record changes or invalidates the pack. The schema uses
`GTBI_STRATEGY_PACK_MANIFEST_V1`, `self_field` storage and omits only
`strategy_pack_digest` from its preimage.

### V7 End-To-End Architecture

```text
immutable scientific manifest
    -> one-time environment and input preparation
    -> canonical effective-rule hashing
    -> feature and signal demand plan
    -> multilevel reuse and dedupe
    -> cost and memory estimates
    -> longest-processing-time job plan
    -> GitHub jobs with immutable preassigned approved internal executor
    -> atomic terminal record per canonical unit in bounded checkpoint batches
    -> job bundles
    -> block merges
    -> final deterministic merge
    -> coverage, equivalence and locked verification
    -> content-addressed publication
```

### Canonical Evaluation Unit

The primary schedulable unit is:

```text
canonical_evaluation_unit
```

Required fields:

```text
unit_id
canonical_strategy_id
economic_hash
feature_set_hash
signal_group_hash
exit_group_hash
simulation_group_hash
estimated_seconds
estimated_memory_mib
symbol_partition_ids
complete_scientific_symbol_set_digest
aliases
effective_seed
data_digest
strategy_pack_digest
contract_digest
policy_hash
code_sha
execution_tree_digest
execution_workflow_bundle_digest
scientific_context_key_digest
complete_reuse_key_digest
```

Equality of `economic_hash` is necessary but never sufficient for reuse of a
complete final result. Complete reuse additionally requires exact
`complete_reuse_key_digest`, scientific-context, seed and complete scientific
symbol-set
identity. Other hashes may reuse only their explicitly scoped intermediate
calculations and never imply equal final metrics.

For each `economic_hash`, normalize every `strategy_id` under the frozen
identity schema, sort by `(normalized UTF-8 bytes, original UTF-8 bytes)` and
choose the smallest original ID as `canonical_strategy_id`; aliases use that
same total order. A normalization collision is recorded and cannot create an
ordering tie. `unit_id` is
`sha256` with domain `gtbi-v7-unit-id-v1` over canonical JSON containing
`economic_hash`, `canonical_strategy_id`, `complete_reuse_key_digest`,
`effective_seed`, `policy_hash` and `complete_scientific_symbol_set_digest`.
Input file
order, shard order and worker completion order cannot select the
representative.

The mapping authority is:

```text
canonical_map_v1:
  schema_version
  strategy_pack_digest
  scientific_context_key_digest
  global_unit_reuse_key_set_digest
  representative_selection_rule_id=normalized_utf8_then_original_utf8_v1
  ordered_rows[
    source_position, strategy_id, candidate_id,
    canonical_strategy_id, unit_id, economic_hash,
    canonical_strategy_payload_digest,
    economic_payload_canonical_bytes_sha256,
    complete_reuse_key_digest, alias_ordinal, is_representative
  ]
  original_strategy_count
  canonical_unit_count
  canonical_map_digest
```

Rows follow original source position; `alias_ordinal` is contiguous from zero
inside each economic group under the representative byte order. Exactly one row
per group has `is_representative=true`, and its strategy ID equals
`canonical_strategy_id`. `canonical_strategy_payload_digest` authenticates that
original full pack record; `economic_payload_canonical_bytes_sha256` is the raw
SHA-256 of the exact metadata-excluding typed bytes fed to the registered
`economic_hash`, enabling collision comparison without pretending the two
digests have the same domain. The map uses `GTBI_CANONICAL_MAP_V1` and
`self_field` storage, omitting only `canonical_map_digest`; its CSV is a strict
projection, never the hash authority.

Aliases are expanded only after canonical evaluation. The final output
preserves every original `strategy_id`, its unique `candidate_id`, canonical
mapping and original ordered source position.

### Repository-Compatible Code Structure

Aurora currently uses a flat package layout. Preserve it.

Create or consolidate:

```text
gtbi/
├── contracts.py
├── data.py
├── features.py
├── signals.py
├── simulation.py
├── metrics.py
├── filters.py
├── scheduling.py
├── checkpoints.py
├── merge.py
├── telemetry.py
└── cli.py
```

Existing top-level packages are not moved in the performance project.

Because Aurora uses an explicit flat-layout package map, the same pull request
must update:

```text
pyproject.toml
gtbi/__init__.py
infra/github_performance/__init__.py
```

Required package declarations:

```text
aurora.gtbi -> gtbi
aurora.gtbi.reference_v6 -> gtbi/reference_v6
aurora.infra -> infra
aurora.infra.github_performance -> infra/github_performance
aurora.infra.gtbi_deadman -> infra/gtbi_deadman
```

`pyproject.toml` also declares the non-Python deployment resources under
`infra/gtbi_deadman/deploy/**` as explicit package data, or builds them as a
separate content-addressed deployment artifact referenced by the wheel. They
may not be present only because tests run from the source tree. Wheel and
installed-package tests must import all declared packages and load every
required deadman deployment resource from a built wheel/artifact in a clean
environment, not from the repository working directory.

The same package-data contract includes
`config/gtbi/contracts/*.json` and
`config/gtbi/performance/**/*.json` and
`config/gtbi/schemas/**/*.json`. Runtime consumers load them through
`importlib.resources`, never repository-relative paths. A clean wheel test
enumerates every contract/schema/deployment resource from its frozen manifest,
loads it after installation and verifies its digest.

Import and path boundaries:

- `aurora.gtbi` imports only Aurora library modules, standard library and
  declared dependencies, never consumer projects or `scripts/`;
- reusable performance infrastructure does not import GTBI science;
- every runtime path resolves through `aurora.core.runtime_paths`;
- no Python module or workflow contains a user-specific drive or home path.

Scripts become thin wrappers:

```text
parse arguments
validate manifest
call gtbi service
write versioned outputs
```

No scientific Python is embedded in workflow YAML.

Source and workflow identity are not implementation-defined aliases. Before
benchmarking, CI materializes and validates these exact registered objects:

```text
execution_tree_manifest_v1:
  schema_version
  source_commit_sha
  ordered_entries[path, git_mode, git_blob_id, byte_size, sha256]
  execution_tree_digest

execution_workflow_bundle_v1:
  schema_version
  source_commit_sha
  execution_tree_digest
  operational_schema_set_digest
  ordered_workflow_entries[path, git_mode, git_blob_id, byte_size, sha256]
  ordered_action_entries[path, git_mode, git_blob_id, byte_size, sha256]
  ordered_wrapper_entries[path, git_mode, git_blob_id, byte_size, sha256]
  execution_workflow_bundle_digest
```

`execution_tree_manifest_v1` covers every installed result-producing Python
module, scientific contract/schema/config resource, reference-engine resource
and dependency-lock input, and no documentation, test or generated output.
`execution_workflow_bundle_v1` covers every dispatched workflow, composite or
JavaScript action, thin CLI wrapper and operational/transport schema used by
the campaign. Path lists are generated from reviewed allowlists, sorted by
unsigned UTF-8 bytes and checked against the built wheel/container and executed
Git tree. A runtime-imported or dispatched file absent from the applicable
manifest, an extra allowlisted file not shipped, a symlink/submodule, or a
mode/blob/size/byte mismatch is fatal. Both schemas use `self_field` storage
and their registered canonical preimages omit only the named digest.

### PREV7-0605 And PREV7-0703: Four-CPU Execution And Benchmark

Preferred public-topology canonical jobs use:

```text
runs-on=ubuntu-24.04
runtime_container=<immutable OCI digest>
```

Do not use `ubuntu-latest` for canonical runs. Record the effective GitHub
runner image version, kernel, CPU model and runtime-container digest.
`ubuntu-24.04` is still a mutable hosted-runner label: G7 records the exact
runner-image release that passed equivalence, and the approved runbook core contains
an exact tested image-version allowlist. A full job on an untested image
aborts before private asset access and requires the affected smoke and runbook-core
approval to be refreshed.

The licence-triggered private fallback uses only the exact GitHub-hosted
four-CPU larger-runner group/label frozen in the runbook core. It is not
`self-hosted`, never uses a standard private two-CPU label, and must pass the
same image, resource, security, equivalence and capacity checks before
authorization.

The runtime image is built from the reviewed Dockerfile and the single
`requirements/gtbi-v7.lock`, scanned, supplied with an SBOM and published by
digest. It contains code dependencies only, never data, strategy packs,
credentials or locked material. Canonical workflow YAML references
`ghcr.io/...@sha256:<digest>`, never a mutable image tag.

The runtime image is a public, read-only GHCR package so the trusted host job
can pull it by digest before requesting any broker-mediated private-asset read.
Making this dependency-only image public exposes no scientific data and avoids
long-lived `container.credentials`. Data, strategy packs, checkpoints, detailed
results and private evidence remain private packages. A private runtime image
is prohibited unless a separately reviewed pre-job authentication design proves
equivalent short-lived credentials without embedding a reusable secret in the
workflow.

The workflow does not run science in the credential-holding job process. Guest
container isolation protects against scientific/workflow process compromise,
not against the trusted GitHub provider host described in the threat model.
Instead:

1. Trusted host steps pull the public runtime image by digest.
2. A short-lived read token downloads and verifies only the assigned private
   inputs into a staging directory.
3. The token process exits, token files and environment values are removed and
   revocation or expiry state is recorded.
4. The host launches the pinned scientific container with a separate PID and
   network namespace, non-root user, `--network=none`, read-only root
   filesystem, all capabilities dropped, `no-new-privileges`, bounded PIDs,
   a seccomp profile denying socket/device/mount/ptrace syscalls, read-only
   input mounts and one empty, bounded, writable raw-result mount containing no
   sensitive input bytes. A normal bind mount is never described or relied on
   as write-only.
5. Periodic checkpoints are written atomically as closed batches. The
   seccomp profile denies socket/device/mount/ptrace plus `symlink`,
   `symlinkat`, `link`, `linkat`, `mknod` and `mknodat` where the runtime
   supports that filtering. Even if a kernel/runtime permits an attempted
   special object, the host validator treats every symlink, hard link, FIFO,
   socket, device or non-regular payload as fatal; isolation and no-follow
   validation are both required controls.
6. A credential-free validator opens every member with no-follow semantics,
   enforces regular files only, allowlisted relative paths, schemas, row and
   byte limits and licence/redaction policy. It copies each opened descriptor
   exactly once into a temporary host-owned directory while hashing those
   copied bytes, compares the copied size/digest with the closed manifest,
   `fsync`s files and directory, then atomically renames the complete batch into
   a read-only sealed upload directory that is never mounted in the scientific
   container. Re-reading a mutable source path after validation is forbidden.
   The validator runs in a fresh process/mount namespace with an explicit
   allowlisted environment and closed inherited descriptors; `GITHUB_TOKEN`,
   `ACTIONS_*` runtime credentials, OIDC variables, input credentials and host
   credential paths are absent. It has no network and cannot inspect another
   host process.
7. A credential-free encryption subprocess encrypts each sealed batch with a
   fresh random data key,
   authenticates the complete ciphertext/manifest and wraps that data key for
   two distinct recipients: the source checkpoint-recipient public key and the
   independent destination recovery public key. Neither private key is present
   in the worker. After that subprocess exits and its plaintext/data-key
   absence is verified, the isolated uploader transfers the ciphertext, both
   labelled wrapped-key envelopes and manifest through a uniquely named
   short-retention Actions artifact using only the job-scoped artifact runtime
   channel, not a repository/package-write App. During the worker matrix, the independent
   destination polls the allowlisted run, pulls each new encrypted batch,
   verifies its execution receipt, recipient labels and ciphertext digest,
   stores it durably and emits a chained replication receipt. Replication is a
   sequence of idempotent jobs of at most `330` minutes, never one campaign-long
   job. Each segment restores an immutable cursor containing the last accepted
   provider artifact ID, artifact digest, receipt-chain head and source API page
   cursor; it closes by publishing the next cursor and segment receipt before
   expiry. A protected dispatcher starts the next segment from those exact
   bytes. Overlap replays are harmless and a gap, conflicting digest or missing
   predecessor blocks completion.

   Validation/encryption/upload may form a bounded two-slot pipeline so network
   transfer overlaps later scientific calculation. The upload subprocess starts
   only after validation, encryption, wrapped-key creation, plaintext deletion
   and data-key destruction for that batch. It runs under a distinct
   unprivileged UID and mount/PID namespace, receives only the read-only sealed
   ciphertext directory plus the job-scoped artifact runtime channel, and
   cannot mount or traverse input, raw-result, validator, key or checkpoint-
   plaintext paths. The scientific container and validator never receive that
   channel. At most one sealed batch is uploading and one awaits upload; a full
   queue stops new unit assignment and applies backpressure rather than creating
   unbounded disk/artifact state. Encryption/validation CPU counts against the
   same four-core ceiling, so the frozen phase-concurrency policy temporarily
   stops assignment to enough already-created scientific workers and leaves
   them idle when measured contention would exceed it; it never changes the
   assigned execution profile or spawns an unregistered pool. Pipeline-on and
   pipeline-off must produce identical checkpoint, receipt and final logical
   digests; only timing may differ.

   After the worker matrix releases its capacity, a bounded authenticated
   downloader normally restores still-live encrypted artifacts from the
   disposable source execution repository using a job-scoped `GITHUB_TOKEN`
   with only `actions:read` and `contents:none` for that repository. That token
   is a registered credential lifecycle object: issue/use/expiry and destruction
   are inventoried, it writes only manifest-bound bytes into an immutable input
   directory, and its environment value, process and any credential file are
   destroyed before authentication, decryption or compaction starts.
   The ciphertext is not a scientific input until locally authenticated and
   decrypted. If those artifacts are absent or expired, an explicitly
   authorized recovery-only reverse path uses a source-owned external recovery
   ingress object store, not a source App or token installed in the destination.
   The source recovery broker creates one opaque, one-use, digest- and
   object-version-bound `PUT-if-absent` capability for the exact unresolved
   ciphertext object and delivers it through the protected destination
   deployment without logging or persisting it. The destination reads its own
   copy with its own credential, verifies its receipt chain and cursor, and
   uploads only the allowlisted ciphertext and wrapped source-recipient keys.
   It receives no source read, list, overwrite, delete or administrative
   permission. The source later reads the immutable ingress object through a
   separate source-only digest-bound `GET`, verifies the destination receipt
   chain, object version and frozen unresolved-batch manifest, and consumes both
   capabilities. No App is installed across custody domains and neither side
   receives the other's repository credential. A separate
   `gtbi-checkpoint-compact` host phase then launches a fresh container with no
   network or publication identity and decrypts into a new
   host-owned directory, repeats no-follow/schema/digest validation, compacts
   the batches, re-encrypts the exact canonical payload and destroys plaintext
   and one-use key material before sealing an immutable local handoff. Only
   after that no-network container has terminated does the host obtain one
   digest-bound `PUT` capability and copy those exact bytes to the approved
   content-addressed write-once handoff store. Only after that upload and
   compact environment have terminated does a different
   `gtbi-checkpoint-publish` deployment, with no private key or decryption
   capability, uses a digest-bound `GET` and asks its fixed-operation broker to
   mint and retain the reduced checkpoint-write token, publish the exact sealed
   ciphertext to the dedicated source checkpoint namespace, verify the remote
   digest and revoke the credential. The deployment receives only the broker
   receipt. A clean-runner recovery fixture proves both
   the normal and reverse paths and proves no shared runner, process,
   environment, directory permission or actor session bridges the two
   capabilities. These phases never compete with the 360 scientific jobs. Block
   and final merge payloads use the same non-canonical staging discipline.

The reviewed transport profile freezes an interoperable multi-recipient AEAD
format, implementation binary/container digest, algorithm suite, recipient-key
IDs, nonce rules, associated-data schema and ciphertext size limits. The
GitHub execution receipt binds ciphertext digest, closed plaintext-manifest
digest and both recipient-key IDs. Campaign private keys exist only in their
respective external non-exportable source/destination OIDC brokers, remain available through
the approved recovery window and are then destroyed only after a dual-copy
restore proof and owner-approved key-destruction receipt.
8. The raw scientific directory is never exposed to a credentialed process.
   A raw batch rejected by the no-follow, file-type, schema, size, secret or
   licence checks is destroyed and cannot be uploaded anywhere. A separate
   bounded diagnostic that contains only the frozen redacted schema may be
   sealed and uploaded as ciphertext to the dedicated private diagnostic
   namespace under the multi-recipient custody path above. It is never a
   scientific payload, checkpoint substitute or public Actions artifact.
9. Canonical publication uses four runners in three phases. A transport job without canonical
   credentials stages immutable bytes. A fresh validator runner with no private
   credential restores, parses and validates the staged object and emits an
   attested approval digest. Separate third-phase
   `gtbi-assets-primary-publish` and `gtbi-assets-mirror-publish` runners each
   receive only those approved transport bytes and manifest; each canonical
   publish App
   copies bytes unchanged, verifies the remote digest and removes credentials.
   Each performs no archive extraction or scientific deserialization. A later
   read-only clean-runner restore independently verifies the canonical object.
   A digest or byte difference
   leaves the unreferenced version marked `invalid_quarantined`, never moves a
   canonical pointer to it, and blocks publication. Any later deletion requires
   its own owner-approved remediation manifest; the checkpoint cleanup broker
   cannot touch that namespace.

G7 proves that the scientific container cannot read host `/proc` credentials,
reach DNS or any socket, alter read-only inputs, access the sealed upload
directory, escape through links/devices, or inherit App, OIDC, Git or
environment credentials. It verifies the configured link/special-file syscall
denials and separately proves that any attempted or fixture-injected
socket/FIFO/device/symlink/hard-link output is rejected before a token-holding
uploader can observe it. Python stubs are defence in depth, not the network or
file-type boundary.

The Dockerfile pins every base image by digest, has no embedded secret and
exposes no network service. Scientific execution always runs non-root, without
privileged mode or added capabilities and with read-only scientific inputs.
Failure of the GitHub workspace-permission smoke blocks G7; there is no root
execution exception. Build and scientific execution use separate jobs and
permissions.

At the start of every job, detect and record:

```text
logical_cpu_count
physical_cpu_count
cpuset_cpu_count
cgroup_cpu_quota
memory_total_mb
memory_cgroup_limit_mb
disk_free_mb
python_version
numpy_version
blas_backend
```

Default limits for the currently audited runner:

```text
available_cpu_workers=4
memory_budget_mb=12288
parallel_unit_memory_limit_mb=10240
disk_budget_mb=10240
```

The effective CPU limit is the minimum of affinity, cpuset and cgroup quota,
not merely `os.cpu_count()`. The executor must never exceed detected CPU or
memory and never silently downgrades its immutable profile. If startup
resources do not satisfy the assigned profile's minimums, the job exits before
private asset access with a structured recoverable admission failure. A later
authorized recovery may assign a different already approved profile and emits
the required substitution receipt.

Compare exactly the same immutable batch using:

```text
workers=1
workers=2
workers=4
```

V7 benchmarks three internal modes.

Mode A, symbol threads:

```text
candidate_processes=1
symbol_threads=4
blas_threads=1
```

Use only when measured NumPy or Pandas work releases the GIL.

Mode B, candidate processes:

```text
candidate_processes=4
symbol_threads=1
blas_threads=1
start_method=spawn
```

Use for independent canonical units dominated by Python simulation.

Mode C, large vectorized operation:

```text
candidate_processes=1
symbol_threads=1
blas_threads=4
```

Use only when one measured numeric operation dominates.

Never allow:

```text
candidate_processes=4
symbol_threads=4
blas_threads=4
```

The total expected active CPU threads must not exceed four.

For process execution:

- use processes;
- use an explicit `spawn` multiprocessing context;
- create one persistent pool per job;
- initialize immutable shared data once per worker;
- feed the next ready unit when a worker finishes;
- checkpoint each complete unit or authenticated scientific fragment
  independently;
- avoid sending large DataFrames through process queues.

`fork` and `forkserver` are deliberately excluded from the accepted V7
profiles. `fork` can inherit unsafe multithreaded state; `forkserver` requires
an internal Unix socket that conflicts with the frozen no-socket scientific
seccomp policy. Because the process pool persists for the complete job, its
one-time `spawn` cost is amortized. An alternative start method may enter only
through a separately reviewed security/performance ADR proving both an
equivalent isolation profile and a material cold end-to-end improvement; it is
never an automatic optimization.

For NumPy and Pandas operations that release the GIL:

- test threads against processes;
- keep only the faster equivalent implementation.

When four worker processes are used:

```text
OMP_NUM_THREADS=1
OMP_THREAD_LIMIT=1
OMP_DYNAMIC=FALSE
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
MKL_DYNAMIC=FALSE
BLIS_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
NUMBA_NUM_THREADS=1
VECLIB_MAXIMUM_THREADS=1
POLARS_MAX_THREADS=1
RAYON_NUM_THREADS=1
```

Set these before importing NumPy, Pandas or any BLAS consumer. Runtime
introspection verifies the loaded thread pools and applies an equivalent
`threadpoolctl` limit where supported. If PyArrow is loaded, the process also
calls and verifies `pyarrow.set_cpu_count(1)` and
`pyarrow.set_io_thread_count(1)` in multi-process mode; any other native
executor must be explicitly present in the frozen thread-pool registry with a
tested limiter. A process reporting more compute or I/O threads than its
execution profile fails the performance check. This prevents hidden
oversubscription across BLAS, Arrow and Rayon-backed libraries.

The pre-plan selector is activated only after each mode passes exact
equivalence. It runs before `execution_plan_digest` is frozen and chooses the
immutable per-job assignment using:

```text
execution_mode
worker_count
symbol_worker_count
blas_thread_count
expected_seconds
expected_memory_mib
```

If evidence is insufficient, V7 uses the fastest already validated
conservative mode. A worker never reruns the selector or changes its assigned
mode during scientific execution.

Determinism rules:

- stable sort before every order-sensitive reduction;
- deterministic tie breakers based on canonical IDs;
- fixed partition boundaries;
- fixed seed derivation from the scientific manifest;
- `PYTHONHASHSEED`, locale and timezone are fixed before interpreter startup
  and recorded in the execution profile;
- no aggregation in process-completion order;
- pairwise or otherwise fixed floating-point reduction order;
- explicit numeric dtypes;
- exact comparison after normalization of non-scientific metadata;
- tolerance comparisons allowed only for fields whose contract explicitly
  defines the tolerance.

Numerical identity is split so reproducibility does not falsely require GitHub
to allocate one physical CPU model to all 360 jobs:

```text
scientific_numerical_semantics_digest:
python_implementation_and_version
numpy_version
pandas_version
scipy_version_or_null
blas_vendor_version_and_loaded_library_digests
PYTHONHASHSEED
locale
timezone
platform_and_architecture
minimum_required_ISA
numeric_dtype_policy_digest
floating_reduction_order_policy_digest
parallel_mode_equivalence_policy_digest

numerical_execution_profile_digest:
execution_mode
candidate_processes
symbol_threads
blas_threads
start_method_or_null
shared_data_mode
OMP_NUM_THREADS
OMP_THREAD_LIMIT
OMP_DYNAMIC
OPENBLAS_NUM_THREADS
MKL_NUM_THREADS
MKL_DYNAMIC
BLIS_NUM_THREADS
NUMEXPR_NUM_THREADS
NUMBA_NUM_THREADS
VECLIB_MAXIMUM_THREADS
POLARS_MAX_THREADS
RAYON_NUM_THREADS
pyarrow_cpu_count_or_null
pyarrow_io_thread_count_or_null
native_thread_pool_registry_digest
phase_concurrency_policy_digest

observed_hardware_digest:
runner_cpu_model
reported_ISA
effective_cgroup_quota
effective_memory_limit
runner_image_identity
```

`numerical_environment_digest` remains a compatibility alias for
`scientific_numerical_semantics_digest`, never for the observed hardware.
Scientific semantics are frozen in the runbook and emitted by every scientific,
checkpoint, reconstruction and merge job. A different semantics digest cannot
reuse a FeatureStore, checkpoint or result and cannot merge into the campaign.
The alias is accepted only when its bytes equal
`scientific_numerical_semantics_digest`; a distinct value or a missing primary
field is invalid.

Thread/process counts and their native-pool reports are operational execution
profiles, not different scientific mathematics. The runbook freezes one
`approved_numerical_execution_profile_registry_digest`; every admitted profile
has passed byte-identical reference equivalence for every applicable primitive,
mode transition and representative workload. The immutable execution plan
assigns one approved profile to each unit/job. A recovery may choose another
registered profile only under the already approved recovery rule and must
produce the same `scientific_result_digest`; any difference is a conflict, not
a tolerance.

Every job emits its `numerical_execution_profile_digest`, runtime thread-pool
observation digest and hardware digest.
Execution and hardware profiles may differ only when each belongs to its
closed approved registry, matches the plan assignment, meets CPU/memory/ISA
admission and has passed byte-identical equivalence against the reference
profile; otherwise the job is rejected. The final package binds complete
per-job execution-profile and hardware-profile maps but does not require every
operational profile digest to be equal. `scientific_context_key_digest` binds
the common approved-profile registry and equivalence policy, never one job's
chosen worker/thread count.

These identities use the registered schemas and domains
`scientific_numerical_semantics_v1`,
`numerical_execution_profile_v1`,
`runtime_threadpool_observation_v1`,
`numerical_execution_profile_registry_v1`,
`numerical_execution_profile_map_v1`,
`observed_hardware_profile_v1`,
`approved_hardware_profile_registry_v1` and
`observed_hardware_profile_map_v1`. Registry payloads contain a unique,
canonically sorted list of complete profile objects and their digests. Map
payloads contain every planned job exactly once, its plan-assigned profile,
its actual profile, the approved substitution receipt or null, and the
observed hardware digest. Empty, duplicate, unknown or unassigned rows fail
closed.

Their exact top-level payloads are:

```text
scientific_numerical_semantics_v1:
  schema_version
  the complete scientific_numerical_semantics_digest field set above

numerical_execution_profile_v1:
  schema_version
  profile_id
  applicable_runner_profile_ids
  the complete numerical_execution_profile_digest field set above

runtime_threadpool_observation_v1:
  schema_version
  campaign_id
  planned_job_id
  assigned_profile_digest
  ordered_phases[
    phase,
    ordered_processes[
      process_ordinal,
      ordered_loaded_libraries[
        user_api, internal_api, version, threading_layer_or_null,
        architecture_or_null, library_content_digest, observed_num_threads
      ],
      pyarrow_cpu_count_or_null,
      pyarrow_io_thread_count_or_null,
      ordered_native_executors[executor_id, observed_compute_threads,
        observed_io_threads]
    ]
  ]
  compliant
  ordered_violation_codes

numerical_execution_profile_registry_v1:
  schema_version
  reference_profile_digest
  ordered_profiles[profile_id, numerical_execution_profile_digest,
    complete_profile]
  applicability_matrix_digest
  parallel_mode_equivalence_report_digest
  approved_numerical_execution_profile_registry_digest

parallel_mode_equivalence_policy_v1:
  schema_version
  reference_profile_digest
  required_primitive_fixture_manifest_digest
  required_transition_fixture_manifest_digest
  required_representative_workload_manifest_digest
  scientific_fields_requiring_byte_identity
  allowed_operational_metadata_differences
  parallel_mode_equivalence_policy_digest

numerical_execution_profile_assignment_v1:
  schema_version
  campaign_id
  execution_plan_id
  approved_numerical_execution_profile_registry_digest
  ordered_jobs[planned_job_id, assigned_profile_digest]
  numerical_execution_profile_assignment_digest

numerical_execution_profile_map_v1:
  schema_version
  campaign_id
  execution_plan_digest
  approved_numerical_execution_profile_registry_digest
  ordered_jobs[planned_job_id, assigned_profile_digest, actual_profile_digest,
    runtime_threadpool_observation_digest,
    substitution_receipt_digest_or_null]
  numerical_execution_profile_map_digest

observed_hardware_profile_v1:
  schema_version
  the complete observed_hardware_digest field set above

approved_hardware_profile_registry_v1:
  schema_version
  ordered_profiles[hardware_profile_id, hardware_match_predicate,
    minimum_effective_cpu, minimum_memory_mib, minimum_ISA,
    equivalence_receipt_digest]
  approved_hardware_profile_registry_digest

observed_hardware_profile_map_v1:
  schema_version
  campaign_id
  execution_plan_digest
  approved_hardware_profile_registry_digest
  ordered_jobs[planned_job_id, observed_hardware_digest,
    matched_hardware_profile_id, admission_receipt_digest]
  observed_hardware_profile_map_digest
```

The scientific-semantics, execution-profile, runtime-thread-pool-observation and
hardware identity schemas use `digest_storage=external_result`; the two
registries, two maps, equivalence policy and assignment use
`digest_storage=self_field` and omit only their named digest field from the
registered canonical preimage. Profile IDs are labels, never authority: every
decision verifies the complete typed object, registered digest and applicable
equivalence/admission receipt.

The approved execution profile contains only declared limits and immutable
registries known before dispatch. It never contains an observed
`threadpoolctl` report. Runtime introspection produces the separate typed
observation above once after imports and again at every registered phase
transition. Absolute library paths, process IDs and timestamps are operational
attempt metadata, not members of that observation; library identity uses
authenticated content digests. A missing phase/process/library, an unregistered
native executor, a noncompliant observation or a map row that does not bind the
accepted attempt is fatal.

### Shared Data Between Processes

Default shared-data order:

1. Read-only memory-mapped NumPy arrays.
2. Linux sealed `memfd` mappings when the runtime and explicit `spawn`
   handoff have passed the security and replacement-worker fixtures.
3. Per-worker loading only when the partition is small.
4. Per-process immutable loading only when measured faster than transfer.
5. `multiprocessing.shared_memory` only as an experimental profile with
   mutation detection; its Python API does not provide an OS-enforced
   read-only mapping and therefore it is never the default immutable store.

The process start method remains explicit `spawn`.

Memory-mapped files, sealed `memfd` objects and experimental
`multiprocessing.shared_memory` are admitted only inside
the scientific container's dedicated, size-bounded `tmpfs`, mounted
`nodev,nosuid,noexec` and absent from every host upload path. The parent creates
each segment with mode `0600`, records its schema, shape, dtype, byte count and
content digest, and gives children only the exact immutable descriptor needed
for their assigned arrays. Each child verifies that descriptor and opens a
read-only mapping before evaluation. Memory-mapped backing files are closed,
made non-writable and opened with read-only access before children start.
`memfd` payloads receive the Linux write/grow/shrink/seal seals before handoff.
The parent retains the source descriptor until the persistent worker pool is
terminal so a replacement worker can receive the same immutable bytes; names
and paths are removed as soon as the selected mechanism still permits that
replacement. Experimental `multiprocessing.shared_memory` uses non-writeable
NumPy views plus before/after payload digests as mutation detection, not as a
security boundary; any mutation invalidates the job and that profile.
All descriptors close on success, exception, timeout and cancellation.
Container teardown is the final fail-safe and the host verifies that no shared-
data path escaped into raw results. The planner includes shared pages, pool
workers and the `resource_tracker` helper in its PID and memory budgets.
`multiprocessing.Manager`, remote managers and any socket-backed shared-state
service are forbidden.

No job may exceed `12288 MiB` RSS. If estimated concurrent memory exceeds
`10240 MiB`, the scheduler reduces active units. A unit that exceeds the
parallel budget runs alone and records:

```text
memory_isolated=true
```

An OOM is a technical failure. Recovery may use fewer workers only through a
lower-concurrency profile already present in the frozen approved registry,
assigned by the recovery planner and bound to an approved substitution receipt.
It cannot change scientific inputs or mutate a running job's profile.

### Equivalent Optimizations

Implement only behind feature flags until equivalence is proven:

- FeatureStore keyed by immutable instrument identity and data digest;
- canonical effective-rule hash;
- deduplication with traceable canonical strategy;
- vectorized non-gating prefilter diagnostics;
- full-metric completion for every V6 canonical unit;
- event-first signal processing;
- symbol buckets;
- NumPy arrays instead of row iteration;
- preallocated trade buffers;
- one-pass annual aggregation;
- compact serialization;
- lazy top-trade materialization.

No approximate filter may reject a candidate.

### FeatureStore

Before `PREV7-0601` changes code, an accepted ADR selects
`GTBIFeatureStore` as the single authoritative interface, persistence model,
key contract and adapter boundary. Static import and wheel tests reject direct
use of any superseded feature cache or legacy store outside the approved
adapter module. If semantic equivalence is uncertain for a feature, that
feature remains uncached until Oracle A and reference equivalence prove it.

The FeatureStore key is:

```text
data_digest
instrument_id
feature_name
parameters_hash
cutoff_date
feature_schema_version
feature_definition_digest
contract_digest
evaluation_identity
universe_temporal_model
universe_temporal_manifest_digest
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
calendar_policy_sha256
currency_policy_sha256
code_sha
execution_tree_digest
dependency_lock_digest
runtime_container_digest
numerical_environment_digest
scientific_numerical_semantics_digest
approved_numerical_execution_profile_registry_digest
canonical_serialization_profile_digest
hash_domain_registry_digest
policy_hash
scientific_context_key_digest
```

Initial common demand candidates, confirmed against the actual 72,000-pack
before materialization:

```text
ema_10, ema_20, ema_50
sma_50, sma_100, sma_150, sma_200
atr_14, adv_20
rolling_high_10, rolling_high_20, rolling_high_50, rolling_high_252
rolling_low_10, rolling_low_20, rolling_low_50
return_20d, return_63d, return_126d, return_252d
close_position_range_10, close_position_range_20, close_position_range_50
rs_ratio_vs_spy_20d, rs_ratio_vs_spy_63d
rs_ratio_vs_spy_126d, rs_ratio_vs_spy_252d
```

This is not a promise to build unused columns. The generated demand manifest
is authoritative and records formula, lookback, lag, dtype and warm-up policy
for every requested feature.

The registered `feature_demand_manifest_v1` is exact:

```text
schema_version
strategy_pack_digest
contract_digest
scientific_context_key_digest
ordered_features[
  feature_ordinal, feature_name, feature_definition_digest,
  ordered_typed_parameters, lookback_sessions, decision_lag_sessions,
  source_column_set_digest, output_dtype, missing_value_policy_digest,
  warmup_policy_digest, temporal_availability_policy_digest
]
feature_count
feature_demand_manifest_digest
```

Feature ordinals are contiguous from zero and rows are sorted by canonical
unsigned UTF-8 bytes of `(feature_name, feature_definition_digest,
canonical_typed_parameters)`. The manifest contains every feature that any
canonical strategy can demand and no feature inferred only from an alias.
Every parameter is schema typed; display strings cannot identify a formula.
It uses `GTBI_FEATURE_DEMAND_MANIFEST_V1`, `self_field` storage and omits only
its own digest. The planner rejects an unregistered feature, an unused row, a
missing effective demand, duplicate keys or any disagreement between the
manifest and the actual FeatureStore dependency graph.

Rules:

- build a `feature_demand_manifest` before calculation;
- calculate each required feature once per instrument and parameters;
- preserve exact temporal indices;
- use only information available at each bar;
- store contiguous arrays without reducing numeric precision;
- expose read-only views;
- separate common features from rare on-demand features;
- never materialize an unused feature;
- never cache a result without complete code, data, formula and contract
  identity;
- reject a cache entry when its key fields, embedded manifest or payload hash
  disagree, even if the transport cache key matched.

Every persistent FeatureStore object is published with a single-writer,
content-addressed commit protocol. A builder writes into a unique private
staging directory, computes and verifies every payload digest, writes a
versioned manifest last, `fsync`s files and directory, then atomically renames
the closed directory to its digest-derived immutable name. The authoritative
catalog may point to it only after that rename and a second read-back
verification. Concurrent builders for the same key either adopt the already
verified identical object or fail on any byte, manifest or identity
disagreement; they never overwrite it. Readers ignore staging paths, entries
without the closed marker, catalog rows whose generation is stale and objects
whose declared length or digest differs.

Crash recovery removes only abandoned staging directories whose creator lease
is terminal and whose grace period has expired. It never deletes a closed
object merely because no current job references it. Retention and eviction are
separate, receipt-bearing control-plane operations over immutable object IDs;
neither may run in a scientific worker or during an active campaign. A corrupt
entry is quarantined, reported and rebuilt from frozen source inputs. Falling
back to recomputation is allowed; accepting partial, stale or mismatched cached
bytes is not.

Common features may be materialized once as immutable campaign partitions only
when a cold end-to-end benchmark proves that build-once plus transfer is faster
than rebuilding per job. Rare features stay job-local. The decision includes
preparation, download, decompression and cleanup time, not just feature-build
CPU.

Cache on and off must produce identical signals, trades and metrics.

### Multilevel Dedupe

Hashes:

```text
economic_hash
feature_set_hash
signal_group_hash
exit_group_hash
simulation_group_hash
```

Every V7 hash above is `sha256:<64 lowercase hex>` calculated only by the
section 16 formula over schema-typed payload bytes, the frozen
`canonical_serialization_profile_digest` and its distinct registered hash
domain. Legacy SHA-1 candidate IDs remain identity strings only and are never
trusted for dedupe, integrity or security.

Canonical JSON rules:

- use the single frozen RFC 8785 plus typed pre-normalization profile from
  section 16; this section defines no second serializer;
- explicit schema version;
- typed booleans, nulls, integers and floating-point values are never coerced
  through display strings;
- non-finite numeric parameters are rejected before hashing unless the frozen
  schema defines one explicit canonical token;
- negative zero follows the schema-specific canonicalize-or-reject rule;
- Unicode strings are not silently normalized and invalid scalar sequences are
  rejected;
- semantically ordered lists retain order, while set-like collections are
  sorted only where the schema declares them unordered;
- effective parameters only;
- no strategy ID, notes, source labels, job ID or shard ID;
- collision and near-collision tests;
- byte-for-byte canonical-JSON comparison whenever two records share a hash.

`economic_hash_v1` is an `external_result` preimage under
`GTBI_ECONOMIC_HASH_V1`. Its payload includes every effective result-changing
field:

```text
evaluator_semantic_schema_version
family_and_concept_when_they_change_mapping_or_effective_defaults
entry_rules
market_regime_rules
stock_trend_rules
relative_strength_rules
exit_rules
effective_guardrails
effective_numeric_parameters
execution_semantics
effective_random_seed_or_derivation_rule
policy_hash_when_it_changes_evaluation
```

It excludes identity-only metadata:

```text
strategy_id
candidate_id
planned_job_id
github_job_id
shard_id
slot
research_source_ids
notes
labels
```

Intermediate reuse uses four separately versioned normative payload schemas:

```text
feature_set_hash_v1:
  scientific_context_key_digest
  ordered_feature_definition_and_parameter_digests
  feature_demand_manifest_digest
  input_partition_manifest_digest
  dtype_precision_and_missing_value_policy_digest
  warmup_lag_and_temporal_availability_policy_digest

signal_group_hash_v1:
  feature_set_hash
  entry_rules
  market_regime_rules
  stock_trend_rules
  relative_strength_rules
  effective_entry_guardrails_and_parameters
  decision_time_and_signal_lag_semantics
  effective_signal_seed_or_derivation

exit_group_hash_v1:
  exit_rules
  effective_exit_guardrails_and_parameters
  stop_take_trailing_holding_and_terminal_exit_semantics
  exit_decision_time_and_lag_semantics
  effective_exit_seed_or_derivation

simulation_group_hash_v1:
  signal_group_hash
  exit_group_hash
  universe_and_eligibility_digest
  costs_slippage_fill_and_next_session_open_semantics
  position_state_calendar_corporate_action_currency_semantics
  train_validation_frame_and_boundary_semantics
  effective_simulation_seed_or_derivation
```

Each schema has its own JSON Schema and registered hash domain. Its field list
is exhaustive for the object reused at that level; an implementation cannot
add an un-hashed dependency. Mutation tests change every effective rule,
parameter, formula, lag, temporal policy, precision, seed and execution
semantic one at a time and require exactly the affected hash levels to change.

The single exact context schema is `scientific_context_key_v1`:

```text
schema_version
contract_digest
data_digest
strategy_pack_digest
policy_hash
code_sha
execution_tree_digest
execution_workflow_bundle_digest
dependency_lock_digest
runtime_container_digest
numerical_environment_digest
scientific_numerical_semantics_digest
approved_numerical_execution_profile_registry_digest
parallel_mode_equivalence_policy_digest
canonical_serialization_profile_digest
hash_domain_registry_digest
evaluation_identity
selection_split
scoring_profile
min_selection_trades_per_year
score_formula_manifest_digest
final_filter_registry_digest
historical_exclusion_start
source_event_cutoff_utc
exact_universe_identity_digest
observation_timestamp_state
universe_temporal_model
universe_temporal_manifest_digest
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
calendar_policy_sha256
currency_policy_sha256
```

`scientific_context_key_digest` uses registered domain
`GTBI_SCIENTIFIC_CONTEXT_KEY_V1`. The exact complete-result reuse object is:

```text
complete_reuse_key_v1:
  scientific_context_key_digest
  economic_hash
  effective_seed
  complete_scientific_symbol_set_digest
```

Its `complete_reuse_key_digest` uses
`GTBI_COMPLETE_REUSE_KEY_V1`. An economic hash alone is never reused across
campaigns. `contract_digest` independently contains the same mandatory typed
temporal-policy set rather than serving as an opaque assertion. `unit_id`,
canonical units, result bundles, every checkpoint record, reconstructed
bundles, block manifests, final merge identities, scientific manifests,
`summary.json`, `_SUCCESS` and the runbook core bind and verify the exact
context and complete-reuse digests. If randomness exists, the effective seed
is either an explicit economic field or is deterministically derived from the
complete economic payload under a versioned domain. There is no ambient,
job-order or process-derived seed.
`complete_scientific_symbol_set_digest` is the result of registered
`scientific_symbol_eligibility_set_v1`:

```text
schema_version
scientific_context_key_digest
exact_universe_identity_digest
economic_hash
eligibility_policy_digest
ordered_instruments[
  historical_source_iteration_ordinal,
  canonical_instrument_id, source_symbol_identity, market_mic,
  listing_currency,
  ordered_eligibility_intervals[
    first_session_date, last_session_date,
    eligibility_state, reason_code
  ]
]
instrument_count
complete_scientific_symbol_set_digest
```

Historical source ordinals are contiguous from zero and reproduce the exact
V6 execution-pack symbol iteration order; they are not replaced by ticker or
partition sort order. Eligibility intervals are non-overlapping, session
aligned, maximal adjacent equal-state runs and cover every in-frame session
for that instrument exactly once. `eligibility_state` is a closed enum that
includes eligible and every scientifically distinct exclusion state; reason
codes come from the frozen eligibility policy. The object uses
`GTBI_SCIENTIFIC_SYMBOL_ELIGIBILITY_SET_V1`, `self_field` storage and omits
only its own digest.

The object is independent of physical partition boundaries. Repartitioning
the same ordered identities and interval states cannot change the complete
reuse key, unit ID, V6 trade sequence or scientific result; changing one
instrument, source ordinal, eligibility interval or reason must change all
applicable identities. Reducers reconstruct trade order by
`historical_source_iteration_ordinal` and each symbol's simulator trade order,
never by partition, tile, completion or lexical ticker order.

Complete-reuse keys are collected only through:

```text
unit_reuse_key_set_v1:
  schema_version
  set_scope=global|job
  parent_global_unit_reuse_key_set_digest_or_null
  ordered_entries[
    assignment_ordinal, unit_id, canonical_strategy_id,
    complete_reuse_key_digest
  ]
  unit_count
  unit_reuse_key_set_digest
```

The global set contains all canonical units, has contiguous global assignment
ordinals and a null parent. Each job set is the unique ordered subset referenced
by its assigned tiles, preserves those global ordinals and names the global
digest as parent. Both use `GTBI_UNIT_REUSE_KEY_SET_V1` and `self_field`
storage, omitting only `unit_reuse_key_set_digest`. The union of distinct job
references may repeat a unit across jobs in symbol-major mode and therefore is
not used to recount canonical units; global-set membership remains the
cardinality authority.

Physical tiling has seven separately registered payloads:

```text
candidate_symbol_pair_set_v1:
  schema_version
  set_scope
  parent_candidate_symbol_pair_set_digest_or_null
  ordered_pairs[canonical_unit_id, symbol_partition_id]
  pair_count
  candidate_symbol_pair_set_digest

physical_evaluation_tile_manifest_v1:
  schema_version
  campaign_id
  execution_plan_id
  tile_id
  layout_mode
  physical_data_layout_digest
  scientific_context_key_digest
  ordered_canonical_unit_ordinals
  ordered_symbol_partition_ids
  global_candidate_symbol_pair_set_digest
  tile_candidate_symbol_pair_set_digest
  input_partition_manifest_set_digest
  ordered_input_partition_manifest_digests
  expected_fragment_schema_digest
  physical_evaluation_tile_manifest_digest

ordered_trade_fragment_manifest_v1:
  schema_version
  campaign_id
  scientific_context_key_digest
  canonical_unit_id
  symbol_partition_id
  input_partition_manifest_digest
  normalized_trade_row_schema_digest
  ordered_trade_rows
  trade_row_count
  ordered_trade_fragment_manifest_digest

annual_metric_partial_state_manifest_v1:
  schema_version
  campaign_id
  scientific_context_key_digest
  canonical_unit_id
  symbol_partition_id
  ordered_split_year_states[
    split, year, parseable_exit_trade_count, finite_return_count,
    finite_return_sum, positive_return_sum, negative_return_sum,
    winning_trade_count, sorted_finite_returns,
    finite_holding_count, finite_holding_sum
  ]
  annual_metric_partial_state_manifest_digest

scientific_fragment_result_v1:
  schema_version
  campaign_id
  execution_plan_digest
  physical_evaluation_tile_manifest_digest
  canonical_unit_id
  symbol_partition_id
  input_partition_manifest_digest
  ordered_trade_fragment_manifest_digest
  annual_metric_partial_state_manifest_digest
  fragment_row_count
  scientific_fragment_result_digest

scientific_fragment_bundle_v1:
  schema_version
  campaign_id
  execution_plan_digest
  physical_evaluation_tile_manifest_digest
  global_candidate_symbol_pair_set_digest
  bundle_candidate_symbol_pair_set_digest
  ordered_fragments[
    canonical_unit_id, symbol_partition_id,
    scientific_fragment_result_digest, fragment_size_bytes
  ]
  fragment_count
  uncompressed_size_bytes
  scientific_fragment_bundle_digest

fragment_reduction_manifest_v1:
  schema_version
  campaign_id
  execution_plan_digest
  level
  planned_reduction_node_id
  expected_candidate_symbol_pair_set_digest
  consumed_candidate_symbol_pair_set_digest
  ordered_consumed_fragment_result_digests
  ordered_forwarded_fragment_result_digests
  ordered_completed_canonical_unit_ids
  ordered_completed_scientific_result_digests
  unresolved_candidate_symbol_pair_set_digest
  fragment_reduction_manifest_digest
```

All seven use `self_field` storage and omit only their named digest field. The
pair-set digest is a registered-object reference whose typed source rows are
`(canonical_unit_id,symbol_partition_id)` sorted by canonical unsigned UTF-8
bytes; the global digest-reference closure must resolve it. The global set has
`set_scope=global` and null parent, and is exactly the Cartesian product of
every canonical unit in the global reuse-key set with every symbol partition
declared by the execution plan. Every tile, bundle and reduction subset has
the matching scope, names the global set as parent, states its exact count and
is a true subset. A tile's subset must equal the Cartesian product of its
ordered units and symbol partitions; a bundle's subset must equal its ordered
fragment pairs. A tile may contain many pairs for scheduling efficiency, but
each fragment result is attributable
to exactly one canonical unit and one symbol partition. The final canonical
result is never reused from a fragment key; complete-result reuse still requires
the full `complete_reuse_key_digest` and complete universe.
`input_partition_manifest_digest` resolves to the exact partition object inside
the authenticated `data_snapshot_identity_v1` closure; it is not a newly
invented set digest. Trade rows preserve the frozen V6 symbol/trade ordering.
The annual partial state is only a deterministic accelerator. Reducers
recompute it independently from the authenticated ordered trade rows and reject
any mismatch before using it; final metrics and result identity remain
derivable from the trades even if the accelerator is discarded.
Fragment bundles are bounded transport/checkpoint groupings, not scientific
aggregation. They preserve each child digest and pair identity, contain no
metric or filter decision, and may be regrouped only by reconstructing and
verifying every child. Bundle size/count limits are frozen in the runbook.

`policy_hash` is exactly the lower-case 64-hex SHA-256 value of the active
Aurora `ProtocolPolicy`. Snapshot, FeatureStore, unit, result bundle,
checkpoint, reconstructed bundle, block, final merge, scientific manifest,
summary, `_SUCCESS`, runbook and final evidence must all carry the same value.
A changed or malformed policy hash invalidates every reuse and merge.

Within one already identical scientific context, effective seed and symbol
partition, `economic_hash` defines which strategy aliases belong to the same
complete economic evaluation. Actual reuse is authorized only by equality of
the full `complete_reuse_key_digest`; `economic_hash` alone never authorizes
cross-campaign, cross-context, cross-seed or cross-partition reuse. Every other
hash shares only the exact intermediate object it describes.

Before dedupe, the strategy-pack validator requires exactly `72,000` records
and exactly `72,000` unique non-empty `strategy_id` values in the original
frozen CSV. That V6 asset has no source `candidate_id` column. Under versioned
schema `gtbi-v7-candidate-identity-v1`, preparation derives
`candidate_id=strategy_id`, preserves original row position and emits an
authenticated `strategy_candidate_identity_map.csv` with exactly 72,000
one-to-one rows before dedupe. The derived map must then contain exactly
`72,000` unique non-empty `candidate_id` values, a frozen one-to-one
`strategy_id -> candidate_id` map, one unique source position per record and no
unmanifested file. A repeated ID is a pack-integrity failure even when both
payloads are byte-identical; economic dedupe never repairs identity
corruption. The validator records the sorted strategy-ID set, sorted
candidate-ID set, mapping and ordered-record digests.

For the approved V6 72,000-pack identity it also requires exactly `3,600`
unique canonical economic groups, `720` unique signal bundles and `5` effective
exit variants per signal bundle, matching the preserved strict-pack manifest.
These values are pack-integrity invariants, not scheduler hints. A different
count creates a different pack/campaign identity and cannot inherit V6
equivalence.

### Diagnostic Prefilter And Full-Metric Completion

The preserved Fast Strict V6 full artifact has:

```text
canonical_evaluations=3600
leaderboard_rows=72000
early_rejected_rows=0
total_strategies_early_rejected=0
```

Therefore canonical V6-equivalent execution may not terminate a valid strategy
after learning that it cannot pass final filters. Passing/failing equivalence is
insufficient: V6 also published the unfiltered metrics and yearly rows for every
one of the `3,600` canonical evaluations and all `72,000` aliases.

V7 may calculate cheap vectorized facts early, but they are diagnostics and
scheduling hints only:

```text
would_fail_train_year
would_fail_validation_year
maximum_executable_trades
would_fail_minimum_trade_count
would_fail_positive_year_count
```

They never alter terminal state, skip simulation, omit annual rows or remove a
candidate from the unfiltered leaderboard. Every approved V6 canonical unit
must complete signal generation, simulation and all frozen metrics before final
filtering. Global median, global profit factor, average-to-median ratio, profit
concentration, drawdown and ranking are always calculated from that complete
result.

The diagnostic signal bound, when emitted, uses an exact upper bound on
executable next-session entries and accounts for position exclusivity, calendar
boundaries and the exact execution contract. An approximate bound is labelled
`approximate_non_gating=true` and cannot affect scheduling when doing so could
change deterministic assignment.

The compatibility file `early_rejected_strategies.csv` remains present but is
empty for this V6 baseline. `canonical_units_early_rejected`,
`aliases_expanded_to_early_rejected`, `early_rejected_rows` and
`total_strategies_early_rejected` must all equal zero. A future contract that
permits terminal early rejection needs a new scientific identity, separate
oracles and a differently named campaign.

A genuinely unsupported configuration is not an early rejection. For this
72,000-pack baseline any unsupported unit blocks completion, as defined in the
pre-dispatch manifest.

Differential tests prove that diagnostic-prefilter on and off produce identical
full leaderboard, yearly rows, metrics, filters and ranking byte for byte.

### Fast Simulation

Implementation priorities:

1. Convert required columns to arrays once.
2. Avoid `iterrows`.
3. Avoid repeated `concat`.
4. Preallocate trade buffers.
5. Reuse masks.
6. Separate signal generation from trade simulation.
7. Process integer indices internally.
8. Materialize timestamps only for outputs.
9. Aggregate annual metrics in one pass.
10. Preserve original output precision.

Numba may be tested behind an optional feature flag. It cannot become required
unless GitHub builds are reproducible and reference outputs remain exact.

### Scheduling

Build cost profiles from GitHub telemetry:

```text
feature_seconds
signal_seconds
simulation_seconds
metrics_seconds
artifact_seconds
peak_rss_mb
symbols_processed
signals_processed
trades_processed
```

The planner consumes one registered `cost_profile_v1`, never an untyped CSV:

```text
schema_version
profile_id
source_campaign_or_benchmark_ids
source_timing_evidence_index_digest
source_hardware_profile_set_digest
source_numerical_execution_profile_set_digest
estimator_version
fallback_policy_digest
ordered_cost_rows[
  cost_key, feature_set_hash_or_null, signal_group_hash_or_null,
  exit_group_hash_or_null, physical_layout_mode_or_null,
  sample_count, censored_sample_count,
  estimated_seconds, estimated_memory_mib,
  estimate_confidence_state
]
cost_row_count
cost_profile_digest
```

`cost_key` has a schema-defined ASCII grammar and rows use canonical unsigned
UTF-8 key order. Source evidence is authenticated and records completed,
failed and right-censored attempts; timeout observations cannot silently
vanish. The fallback is total for an unseen key and produces a deterministic,
conservative estimate. Cost estimates affect assignment order only, never
scientific rules, candidate coverage, filters or ranking. This object uses
`GTBI_COST_PROFILE_V1`, `self_field` storage and omits only its own digest.
Changing telemetry, estimator, fallback or any estimate changes the plan and
requires a new execution-plan digest.

Use deterministic reuse-aware longest-processing-time scheduling, abbreviated
`reuse-aware LPT`:

1. Select the frozen candidate-major, symbol-major or hybrid physical layout
   from the cold end-to-end benchmark.
2. Construct the exhaustive canonical-unit/symbol-partition pair set and cover
   it once with deterministic physical tiles.
3. Partition by required data locality.
4. Group by `feature_set_hash` and then `signal_group_hash` so reusable work
   remains in one job where memory permits; in symbol-major mode, prefer
   evaluating all reusable signal/exit groups while each symbol partition is
   resident.
5. Estimate aggregate tile cost, transfer/output bytes and peak memory.
6. Order expensive tiles first and assign each to the least-loaded immutable
   job queue.
7. Split a tile only on a deterministic candidate or symbol boundary when its
   predicted imbalance exceeds the frozen `max_reuse_group_imbalance_pct` or
   memory budget; preserve exact pair-set coverage, record the split and keep
   every reuse group whole unless that exact split predicate is true.
8. Preserve deterministic canonical-unit identity, evaluated set and complete
   pair-set coverage.

Cost estimate inputs:

```text
historical_seconds
symbol_count
feature_cost
signal_cost
simulation_cost
expected_trade_count
exit_complexity
memory_estimate
previous_timeout_rate
input_transfer_bytes
fragment_output_bytes
layout_mode
```

Capacity:

```text
total_compute_slots =
    active_github_jobs
    * effective_workers_per_job
```

With `360` active jobs and `4` effective workers, the theoretical ceiling is
`1440` CPU slots. V7 must measure useful saturation and must not assume the
ceiling is attainable.

Job count:

```text
verified_matrix_capacity =
    capacity_smoke_proven_concurrency

scientific_parallelism_target = 360

available_github_concurrency =
    max(
        0,
        verified_matrix_capacity
        - source_control_reserve_when_shared
        - destination_control_reserve_when_shared
        - measured_non_gtbi_active_jobs
    )

job_count =
    min(
        scientific_parallelism_target,
        available_github_concurrency,
        ceil(total_estimated_compute / target_compute_per_job)
    )
```

For disjoint control pools, each corresponding shared reserve is exactly zero;
its independent pool-capacity receipt is mandatory. `verified_matrix_capacity`
is total usable capacity in the selected scientific/shared pool, not an
already capped scientific value. Thus a verified shared capacity of 362 with
two reserved control slots permits 360 scientific jobs, while 360 total shared
slots with two reserves permits only 358 and fails the selected
`CAPACITY_TOPOLOGY`.

The execution plan may contain fewer than `360` logical jobs when that reduces checkout, environment,
download, upload and merge overhead.
The selected full topology still proves it can schedule up to 360 simultaneous
scientific jobs plus its control reserves; a smaller logical plan does not
weaken that capacity requirement.

The account limit is an owner-supplied upper bound, not assumed discoverable
from a standard GitHub API. The capacity smoke proves the usable matrix
capacity; the preflight uses API evidence only for current run/job occupancy.
It refuses to assume queued jobs are active CPU. Unrelated runs
are never cancelled without the approved inventory decision from
`PREV7-0002`; if capacity is unavailable, the campaign waits or replans before
authorization rather than silently changing topology mid-run.

Scientific capacity can never consume the last control-plane slot. The source
deadman/reaper has at least one physically runnable protected control slot and
the independent destination deadman/reaper has at least one in its separately
administered pool. When science and source control share an account or runner
pool, `source_control_reserve>=1` is subtracted from verified capacity; the same
rule applies independently to destination capacity. A physically separate,
smoke-proven control pool satisfies the reserve without reducing the scientific
pool. Therefore `360` scientific workers are allowed only when the saturation
smoke proves that all 360 can run while both reserved reapers dispatch, execute
and revoke a synthetic lease within SLA. Otherwise:

```text
scientific_parallelism <=
  verified_shared_pool_capacity
  - source_control_reserve
  - destination_control_reserve_when_shared
```

Planner and final reconciler being non-overlapping does not waive either
reserve. Matrix partitioning is defined for every admitted planner result:

```text
matrix_a_size=min(job_count,256)
matrix_b_size=max(job_count-256,0)
max_parallel_a=matrix_a_size
max_parallel_b=matrix_b_size
fail_fast_a=false
fail_fast_b=false
```

The exact projection consumed by the workflow is registered
`matrix_partition_manifest_v1`:

```text
schema_version
campaign_id
execution_plan_id
ordered_rows[
  planned_job_id, matrix_id, matrix_ordinal,
  ordered_tile_ordinals
]
job_count
matrix_a_size
matrix_b_size
max_parallel_a
max_parallel_b
matrix_b_present
fail_fast_a
fail_fast_b
matrix_partition_manifest_digest
```

Rows are ordered by `(matrix_id, matrix_ordinal)`, both ordinals are contiguous
inside their declared matrix and each planned job appears once. `matrix_id` is
exactly `A` or `B`; B has no rows and `matrix_b_present=false` when omitted.
The equations above are schema invariants. The object uses
`GTBI_MATRIX_PARTITION_MANIFEST_V1`, `self_field` storage and omits only its
own digest. CI derives it independently from the execution plan and workflow
matrix JSON and requires byte-identical typed content.

When `job_count=0`, no scientific workflow is dispatched and the controller
waits or replans. For `1..256`, matrix B is omitted and reconciliation records
its control status as `skipped_not_required`, never as a missing scientific
job. For `257..360`, both matrices exist. Thus exactly `360` gives A=`256` and
B=`104` while every smaller valid plan remains defined.

The registered `execution_plan_v1` payload is exact:

```text
schema_version
campaign_id
execution_plan_id
scientific_context_key_digest
global_unit_reuse_key_set_digest
canonical_map_digest
policy_hash
strategy_pack_digest
data_digest
ordered_units[assignment_ordinal, unit_id, complete_reuse_key_digest,
  terminalization_owner_kind, terminalization_owner_id,
  estimated_seconds, estimated_memory_mib]
physical_data_layout_digest
global_candidate_symbol_pair_set_digest
matrix_partition_manifest_digest
ordered_symbol_partitions[
  symbol_partition_ordinal, symbol_partition_id,
  ordered_historical_source_iteration_ordinals,
  ordered_input_partition_manifest_digests
]
ordered_tiles[tile_ordinal, tile_id, physical_evaluation_tile_manifest_digest,
  tile_candidate_symbol_pair_set_digest,
  ordered_unit_assignment_ordinals, ordered_symbol_partition_ids,
  estimated_seconds, estimated_memory_mib]
ordered_jobs[planned_job_id, matrix_id, matrix_ordinal,
  ordered_tile_ordinals, estimated_seconds, estimated_memory_mib]
numerical_execution_profile_assignment_digest
ordered_reduction_nodes[
  reduction_node_ordinal, planned_reduction_node_id, level,
  owner_kind, owner_id, ordered_child_job_or_reduction_node_ids,
  expected_candidate_symbol_pair_set_digest,
  ordered_terminalized_unit_assignment_ordinals
]
ordered_blocks[
  planned_block_id, ordered_planned_job_ids,
  ordered_owned_reduction_node_ordinals
]
ordered_superblocks_or_empty[
  planned_superblock_id, ordered_planned_block_ids,
  ordered_owned_reduction_node_ordinals
]
matrix_a_size
matrix_b_size
max_parallel_a
max_parallel_b
scheduling_policy_digest
cost_profile_digest
execution_plan_digest
```

Assignment, symbol-partition and tile ordinals are independently contiguous
from zero. Symbol partitions contain disjoint historical source ordinals whose
ordered union is exactly the complete frozen universe order; their input
partition references close exactly to the rows needed for those instruments
and dates under the selected physical layout. Every
canonical unit appears exactly once in `ordered_units`; every required
canonical-unit/symbol-partition pair appears exactly once across
`ordered_tiles`; and every tile appears in exactly one planned job. Every
planned job appears in exactly one matrix and one block; every reduction node
has one owner and a cycle-free child set; every block appears exactly once in
either the direct final-merge set or one superblock. Every canonical unit names
exactly one terminalization owner, either its locally complete planned job or
one declared reduction node, and that owner names it back exactly once. A unit
cannot be terminalized by both. The assignment object covers exactly the same
planned-job, reduction-node and terminalization-owner sets.
The schema uses `gtbi_execution_plan_v1`, `self_field` storage and omits only
`execution_plan_digest` from its canonical preimage. Provider run/job/artifact
IDs and observed timing never enter this immutable plan.

`execution_plan_id` is a non-authenticating immutable label allocated before
the mutually referencing pre-plan objects are built. Its grammar is
`ep-[a-z0-9][a-z0-9._-]{0,62}`; it is unique inside `campaign_id`, is frozen in
the runbook core and may never be reused for different bytes. The same exact
label appears in the execution plan, numerical-profile assignment, every
physical tile and matrix-partition manifest. It prevents circular digests but
never substitutes for `execution_plan_digest`, which remains the scientific
assignment authority after plan closure.

Both matrices set `strategy.fail-fast: false`. Reconciliation, checkpoint flush
and recovery-manifest jobs use the explicit equivalent of
`always() && !cancelled()`, inventory every planned work identity, pair subset
and attempt even when a parent job fails, and cannot be skipped merely because
a matrix child failed.
An operator cancellation stops new work but still preserves already sealed
checkpoints through a separately authorized finalizer when GitHub permits it.

Concurrency policy:

```yaml
# Workflow root. Never place this shared group under jobs.<job_id>.
concurrency:
  group: gtbi-v7-full
  queue: max
  cancel-in-progress: false
```

Only one approved full campaign for the same product and contract may run at a
time. The protected campaign registry normally prevents a second dispatch.
`queue: max` is the current GitHub backstop: unlike the default `single` queue,
it does not replace an existing pending run, permits at most 100 pending runs
and cannot be combined with `cancel-in-progress: true`. Any unexpectedly queued
duplicate is cancelled by the controller before resource activation and is a
failing audit event.

Before dispatch, one protected compare-and-swap campaign-operation registry
admits at most one recovery or merge operation in total for a campaign, not one
per stage. It assigns an immutable `operation_id`; a second request of either
kind is rejected before GitHub enqueue until the previous operation is terminal
and the campaign state allows the next transition. Admitted recovery and merge-
only workflows share:

```yaml
concurrency:
  group: gtbi-v7-control
  queue: max
  cancel-in-progress: false
```

The disposable repository contains exactly one campaign. The literal group is
mandatory because full/recovery workflows accept only capsule digests and
GitHub evaluates root concurrency before a job can restore `campaign_id`.
`campaign_id`, once restored, is still checked by the authoritative CAS
registry, but is never a caller input or concurrency expression. Capsule digest
must never be the concurrency-group key.

They never cancel original workers. The CAS registry is the authority and
`queue: max` prevents silent replacement if a dispatch race or controller bug
still reaches GitHub. A separate smoke workflow uses this distinct root-level
policy:

```yaml
concurrency:
  group: gtbi-v7-smoke-${{ inputs.contract_digest }}
  queue: single
  cancel-in-progress: true
```

Its validated digest input cannot contain control characters or exceed the
frozen 64-hex grammar. A shared `jobs.*.concurrency` group is prohibited
for matrix children because it would serialize the matrix. Static workflow
tests assert the concurrency mapping is root-level, no child job uses the
campaign-wide group, and simultaneous recovery/merge requests cause all but the
single state-valid request to be rejected before enqueue.

Each active job consumes only its immutable assigned queue; workers never claim
from a mutable cross-job global queue. Candidate-process mode keeps at least
four assigned candidate-major work items ready. Symbol-thread mode keeps one
assigned physical tile with enough symbol work to occupy its thread pool. Only
a recovery manifest may reassign an unresolved canonical unit, physical tile,
reduction node or exact missing pair subset to a new job, preserving the
original assignment and reason as provenance.

Memory scheduling rejects a concurrent combination when estimated memory
exceeds `10240 MiB`. It does not reject the scientific unit.

### Canonical V7 Workflow Inputs

Synthetic, benchmark and pre-authorization smoke modes may expose the reviewed
technical controls below:

```text
campaign_mode
scientific_manifest_digest
scientific_manifest_asset
runtime_container_digest
execution_mode=auto
intra_job_workers=4
max_symbol_workers=4
max_candidate_processes=4
blas_threads=1
work_item_timeout_seconds
job_timeout_minutes
max_initial_technical_attempts_per_work_identity=3
max_total_technical_attempts_per_work_identity=5
max_github_jobs=360
source_control_reserve_when_shared
destination_control_reserve_when_shared
control_pool_separation_receipt_set_digest
target_compute_seconds_per_job
memory_budget_mb=12288
telemetry_interval_seconds=0.5
enable_feature_store=true
enable_multilevel_dedupe=true
diagnostic_prefilter_only=true
enable_terminal_early_stopping=false
enable_cost_scheduling=true
enable_block_merge=true
test_mode
test_unit_limit
```

The scientific manifest supplies dates, data, contract and strategy-pack
digests. Users cannot override locked or validation dates through ordinary
workflow inputs.

The planner rejects any assignment whose conservative p99 compute, result
validation, encryption, artifact upload, terminal receipt and safety margin do
not fit within `job_timeout_minutes`. No GitHub-hosted job is allowed to depend
on running for six hours. Long-lived controller and replication duties use
bounded idempotent segments with durable cursors; scientific jobs never rely on
continuation within the same process.

```text
0 < job_timeout_minutes <= 330
0 < work_item_timeout_seconds
work_item_timeout_seconds
  + minimum_terminalization_margin_seconds
  <= job_timeout_minutes * 60
```

The same admission check applies to the sum of assigned work-item budgets and
shared preparation under the selected intra-job execution mode.

Full mode exposes exactly one semantic input:

```text
dispatch_capsule_digest
```

Before any full job is created, the protected independent-destination
controller performs an atomic create-if-absent in the authoritative
campaign-consumption registry keyed by
`(campaign_id,dispatch_capsule_digest)` and emits an attested consumption
ticket bound to the immediately preceding `dispatch_preflight_receipt_digest`.
The immutable consumption row additionally binds schema version, sequence,
previous-event digest, expected CAS version, authority generation, consuming
operation/run identity, trusted consumption time, ticket/attestation digest and
`event_digest` under `GTBI_CAMPAIGN_CONSUMPTION_EVENT_V1`, with only
`event_digest` omitted.
That canonical receipt contains trusted query time, current provider state,
remaining authorization/capsule lifetime, admitted plan/budget digests and all
preflight decisions. It expires after a short frozen interval; no worker starts
from a stale receipt. The source keeps a verified read-only mirror, never a
competing writer.
Campaign state moves only through this CAS table:

```text
RESERVED -> INITIAL_RUNNING
INITIAL_RUNNING -> RECOVERY_REQUIRED | READY_TO_MERGE | TERMINAL_FAILED
RECOVERY_REQUIRED -> RECOVERY_PENDING | RECOVERY_AUTH_REQUIRED
RECOVERY_AUTH_REQUIRED -> RECOVERY_PENDING | TERMINAL_FAILED
RECOVERY_PENDING -> RECOVERING
RECOVERING -> RECOVERY_REQUIRED | RECOVERY_AUTH_REQUIRED | READY_TO_MERGE |
              TERMINAL_FAILED
READY_TO_MERGE -> MERGE_PENDING
MERGE_PENDING -> MERGING
MERGING -> VERIFIED_COMPLETE | READY_TO_MERGE | RECOVERY_REQUIRED |
           TERMINAL_FAILED
any nonterminal state -> SECURITY_REVOKED | ABANDONED
```

`INCOMPLETE` is a diagnostic package status, never a campaign state.
`RECOVERY_AUTH_REQUIRED` is nonterminal but cannot dispatch work: it records
that the frozen attempt ceiling is exhausted and waits for a fresh, valid
recovery authorization envelope and independently synchronized recovery
capsule. Only their one-time consumption may move it to `RECOVERY_PENDING`.
If the owner declines recovery or the bounded decision deadline expires, the
controller selects `TERMINAL_FAILED` or `ABANDONED` through its authorized
terminal branch; it never remains silently runnable.
Each transition binds expected version, previous event digest, operation ID,
attempt number, unresolved-work/pair/block manifest and evidence digest. Recovery and
merge pending/running states are mutually exclusive. A failed technical merge
may return to `READY_TO_MERGE` only with unchanged scientific inputs; a merge
  that discovers unresolved canonical units, tiles, reduction nodes or pair
  subsets returns to `RECOVERY_REQUIRED`. A second
initial dispatch or transition not listed above aborts. Only manifests bound to
the original capsule may append attempts. GitHub concurrency is additional
protection, not the state authority.
The transition row is `campaign_state_event_v1` and also binds schema version,
campaign ID, sequence, previous/new state, authority generation, trusted UTC,
actor/attestation and `event_digest` under
`GTBI_CAMPAIGN_STATE_EVENT_V1`, with only `event_digest` omitted.

It restores the dispatch capsule, destination-owned disaster-sync receipt,
authorization envelope and bound runbook core from immutable storage by digest;
verifies both disaster and primary copies, the five authenticated approval
receipts, current authorization state, protected tag, executed SHA and every
bound manifest; and derives every effective parameter from the core bytes. It
rejects any extra input, environment override, default fallback, mutable tag or
command-line replacement. The dispatch actor cannot supply dates, worker
counts, timeouts, budget, network policy, recovery policy or scientific
identity separately.

Initial recovery and merge-only modes accept exactly:

```text
dispatch_capsule_digest
recovery_or_block_manifest_digest
```

The second manifest may select only unresolved canonical units, tiles,
reduction nodes, exact missing pair subsets or already authorized blocks from
the original execution plan. It cannot replace scientific,
performance, budget or security inputs.

When the original technical-attempt ceiling is exhausted, or the campaign is
incomplete because its envelope, budget admission or infrastructure window
ended, the protected authorization path creates
`recovery_authorization_envelope.json`, has the
independent destination copy and restore it, and freezes a choice-free
`recovery_dispatch_capsule.json`. Execution accepts only
`recovery_dispatch_capsule_digest`. It restores the destination sync receipt,
recovery envelope, original runbook core and original authorization envelope as
historical evidence, exact
unresolved-work/pair manifest, prior attempts, additional ceiling and incremental
budget. Only the recovery envelope and recovery capsule must be current; they
carry five fresh independent receipts: scientific review, workflow review,
exact-workload acceptable-use review, deployed-security review and repository-
owner authorization. Each binds the unchanged runbook-core/workload digest,
current terms and security configuration/observation state, exact unresolved
manifest, additional ceiling, incremental budget and expiry. They also
revalidate roles, protection and vulnerability state. Expiry of the original
envelope does not invalidate an otherwise valid recovery, but no original
approval substitutes for any fresh recovery receipt. Recovery cannot change any
scientific or runtime identity.

`recovery_authorization_envelope.json` is canonical typed JSON under
`GTBI_RECOVERY_AUTHORIZATION_ENVELOPE_V1` with this exhaustive ordered
preimage, omitting only its own digest:

```text
schema_version
campaign_id
original_runbook_core_digest
original_authorization_envelope_digest
original_dispatch_capsule_digest
unresolved_work_and_pair_manifest_digest
prior_attempt_set_digest
unchanged_scientific_identity_set_digest
unchanged_runtime_identity_set_digest
additional_attempt_ceiling
incremental_budget_manifest_digest
scientific_recovery_approval_receipt_digest
workflow_recovery_approval_receipt_digest
acceptable_use_recovery_approval_receipt_digest
security_recovery_approval_receipt_digest
owner_recovery_authorization_receipt_digest
recovery_approval_receipt_set_digest
current_terms_and_workload_digest
approved_external_security_configuration_digest
approved_external_security_transition_policy_digest
current_external_security_observation_digest
current_role_review_protection_snapshot_digest
fresh_vulnerability_scan_receipt_digest
created_at_utc
valid_until_utc
executed_ref_sha
canonical_code_sha
execution_repository_commit_sha
```

Any missing, expired, repeated-actor or non-independent receipt, terms drift,
security drift or workload difference rejects the envelope before a recovery
capsule can be created.

### One-Time Preparation

Every campaign prepares once in dependency order:

```text
data_manifest
strategy_pack_manifest
dependency_lock
verified_wheelhouse
canonical_map
feature_demand_manifest
scientific_symbol_eligibility_sets
complete_reuse_key_objects
input_partition_manifest_set
physical_data_layout_manifest
cost_profile
execution_plan
matrix_partition_manifest
job_assignment_manifest_set
planned_reduction_topology_manifest
scientific_manifest
```

Workers:

- verify SHA-256 before calculation;
- download each required partition once;
- never reinstall dependencies per unit;
- never download another scientific worker's artifact;
- use dependency caches keyed by the complete lock digest;
- treat caches only as transport acceleration: verify every wheel and input
  against the approved manifest before use;
- never place private data, strategy packs, checkpoints, licensed rows,
  credentials or detailed results in GitHub Actions cache; cache only public
  dependency material that is safe for an untrusted pull request to read;
- never restore scientific inputs or executable dependencies from a cache
  written by an untrusted pull-request workflow.

### Efficient Job Artifacts

Each job creates exactly one final compressed logical result bundle containing:

```text
job_assignment_manifest.json
job_result_manifest.json
checkpoint.jsonl
physical_evaluation_tile_manifests.jsonl
scientific_fragments.parquet
canonical_outcomes.parquet
leaderboard.parquet
yearly_performance.parquet
timing_diagnostics.parquet
resource_samples.parquet
errors.jsonl
```

`scientific_fragments.parquet` is mandatory and contains every tile fragment
produced by that job. The three canonical tables contain only units whose full
symbol-partition set is locally complete; they are valid empty typed tables in
symbol-major/hybrid jobs. A block or superblock emits a canonical unit only at
the unique reduction node assigned by the execution plan after all of that
unit's fragments reconcile. The plan assigns every canonical unit exactly one
such node and rejects a fragment routed to any other node. CSV is generated only
by the final merge for human use.

Before upload, the host validates that closed bundle, encrypts and authenticates
it to the frozen campaign merge-recipient public key, deletes the plaintext
staging bytes and uploads only ciphertext plus a non-sensitive envelope
manifest. This final bundle is distinct from the bounded, uniquely named
encrypted checkpoint microbatch artifacts emitted during execution. The
execution plan freezes maximum microbatches, maximum bytes and upload cadence
per job; budget and transport smoke count both classes. A worker cannot create
an unmanifested artifact name or use checkpoints as an unbounded per-unit
artifact stream.

`job_assignment_manifest.json` is frozen before execution and binds job,
ordered units, ordered physical tiles, their pair-set coverage, reuse groups
and scientific identities. It is the typed
`job_assignment_manifest_v1` object:

```text
schema_version
campaign_id
execution_plan_digest
planned_job_id
matrix_id
matrix_ordinal
ordered_referenced_units[
  assignment_ordinal, unit_id, canonical_strategy_id,
  complete_reuse_key_digest
]
ordered_assigned_tiles[
  tile_ordinal, tile_id, physical_evaluation_tile_manifest_digest,
  tile_candidate_symbol_pair_set_digest
]
unit_reuse_key_set_digest
assigned_candidate_symbol_pair_set_digest
assigned_candidate_symbol_pair_count
job_assignment_manifest_digest
```

The referenced-unit list is the unique ordered union of units named by the
assigned tiles; it does not assert that those units finish locally. The assigned
pair set is the disjoint union of the tile subsets and must equal the exact
execution-plan subset for that job. The object uses `self_field` storage under
`GTBI_JOB_ASSIGNMENT_MANIFEST_V1`, omitting only
`job_assignment_manifest_digest`. A derived assignment file, an unregistered
digest or a transport-order-dependent list is invalid.

The complete assignment inventory is one typed object:

```text
job_assignment_manifest_set_v1:
  schema_version
  campaign_id
  execution_plan_digest
  ordered_entries[planned_job_id, job_assignment_manifest_digest]
  planned_job_count
  job_assignment_manifest_set_digest
```

Entries follow execution-plan job order and cover every planned job exactly
once. It uses `GTBI_JOB_ASSIGNMENT_MANIFEST_SET_V1` with `self_field` storage,
omitting only its own digest. Each restored child is independently validated
and must be the exact projection of the same execution plan; hashing only a
list of filenames or trusting a scalar count is forbidden.

`job_result_manifest.json` is a required inner bundle member with its own
versioned schema. Payload files close first; the manifest then lists each
payload path, schema, bytes, rows and digest in canonical path order, excluding
itself and the compressed outer container; the outer container is created only
after that manifest validates. After upload,
`job_artifact_receipt.json` records provider artifact ID, immutable name,
ciphertext bytes, ciphertext digest, encryption suite, recipient key ID and
authenticated envelope digest without changing either inner manifest. It
contains no plaintext payload digest unless that digest is already classified
as non-sensitive in the runbook.
Its `manifest_digest` is a `self_field` under
`GTBI_JOB_RESULT_MANIFEST_V1`; only `manifest_digest` is omitted from that
manifest's typed preimage.

The reconstruction-stable `job_logical_payload_digest` is
`HASH[GTBI_JOB_LOGICAL_PAYLOAD_V1]` over exactly:

```text
schema_version
campaign_id
scientific_context_key_digest
unit_reuse_key_set_digest
job_assignment_manifest_digest
ordered_logical_payload_members[
  path, schema_version, row_count, logical_content_digest
]
```

The member array contains exactly, in canonical path order:

```text
canonical_outcomes.parquet
leaderboard.parquet
physical_evaluation_tile_manifests.jsonl
scientific_fragments.parquet
yearly_performance.parquet
```

It excludes `job_assignment_manifest.json` because its digest is already a
separate field, and excludes `job_result_manifest.json`, `checkpoint.jsonl`,
`timing_diagnostics.parquet`, `resource_samples.parquet`, `errors.jsonl`,
outer compression, encryption and transport receipts. Adding another logical
scientific output requires a schema/domain version bump. Physical tile and
fragment members are scientific intermediates and may never be moved to the
operational-evidence inventory merely because they are not final leaderboard
rows. Run/workflow/job/attempt/generation IDs, timestamps, provider locators
and telemetry are forbidden in this preimage.
Original and reconstructed bundles are equivalent only through this digest;
their operational manifests and receipts remain distinct.
`job_result_manifest.json` stores this digest as a required field but that field
is not recursively included in its own logical preimage.

Block merges restore and authenticate encrypted job bundles through
`gtbi-merge`, merge inside a no-network trusted container and upload only
encrypted block bundles. The final merge uploads only a bundle encrypted to the
distinct source result-validator and independent-destination recipients.
Plaintext scientific outputs appear only inside bounded merge/validation
containers and an explicitly authorized restore session, never as an Actions
artifact, public log or canonical stored object.

Result-bundle identity:

```text
artifact_schema_version
outcome_schema_version
run_id
planned_job_id
github_job_id
github_run_attempt
code_sha
execution_tree_digest
execution_workflow_bundle_digest
dependency_lock_digest
runtime_container_digest
numerical_environment_digest
scientific_numerical_semantics_digest
approved_numerical_execution_profile_registry_digest
numerical_execution_profile_digest
observed_hardware_digest
policy_hash
unit_reuse_key_set_digest
job_assignment_manifest_digest
data_digest
strategy_pack_digest
contract_digest
execution_plan_digest
job_bundle_state
referenced_unit_count
locally_terminal_unit_count
expected_tile_count
completed_tile_count
expected_candidate_symbol_pair_set_digest_and_count
accounted_candidate_symbol_pair_set_digest_and_count
unresolved_candidate_symbol_pair_set_digest_and_count
job_logical_payload_digest
```

`unit_reuse_key_set_digest` is
`HASH[GTBI_UNIT_REUSE_KEY_SET_V1]` over the ordered list of
`(unit_id, canonical_strategy_id, complete_reuse_key_digest)` for every
referenced unit, sorted by the immutable `assignment_ordinal ASC` from
`job_assignment_manifest.json`; ordinals are contiguous from zero and each
unit ID appears once. Reordering transport rows cannot change this order. The
per-unit `complete_reuse_key_digest` remains in
`job_assignment_manifest.json` and each canonical outcome/checkpoint record; a
multi-unit bundle never pretends that one unit key identifies all others.

`referenced_unit_count` is the cardinality of the unique `unit_id` set
referenced by the tiles assigned to that exact `planned_job_id` by the immutable
`job_assignment_manifest.json`. `locally_terminal_unit_count` counts only
complete canonical outcomes produced locally after all partitions for that unit
have reconciled; it may legitimately be zero in symbol-major or hybrid jobs.
The final-merge
`job_assignment_manifest.csv` is only its alias-expanded human projection and
is checked later against the JSON set/digest; it is not an input to worker
acceptance.

A structurally valid job bundle has exactly one state:

```text
job_bundle_state=complete|partial_recoverable
locally_terminal_unit_ids subset_of referenced_unit_ids
locally_terminal_unit_ids subset_of units_owned_for_terminalization_by_this_job
extra_unit_ids = {}
conflicting_terminal_outcomes = {}
accounted_pair_set subset_of expected_pair_set
unresolved_pair_set = expected_pair_set - accounted_pair_set
accounted_pair_set intersection unresolved_pair_set = {}
completed_tile_ids subset_of expected_tile_ids
```

For `complete`, completed tiles equal expected tiles, accounted pairs equal
expected pairs, the unresolved set is empty and every unit whose declared
terminalization owner is this job is locally terminal. For
`partial_recoverable`,
accounted pairs may be a strict subset, every accepted fragment remains usable
and the exact complement is frozen for selective recovery. A partial bundle is
valid evidence but cannot make its GitHub scientific job successful, close its
block, satisfy campaign coverage or contribute a missing canonical outcome.
Every locally terminal outcome must be reconstructible solely from the
accounted pairs in that same bundle or from explicitly named, already accepted
predecessor fragments in its recovery assignment, and this job must be its
unique terminalization owner. Candidate-major is only the
special case in which each referenced unit is normally locally terminal; no
generic schema equates referenced and terminal unit counts.

An alias is not another canonical unit. Alias multiplicity is preserved in the
canonical map and is expanded only by the final merge when calculating the
original-strategy total.

Never create one artifact per strategy.

If a worker artifact is absent or expires, the protected
`gtbi-checkpoint-compact` deployment uses separate sequential phases: a
credentialed host restores and seals the immutable input, then terminates its
credentials; a fresh no-network container reconstructs the exact same logical
result bundle from verified checkpoint chains, orders and encodes payloads
canonically, seals encrypted handoff bytes and emits a
`reconstructed_job_bundle_receipt.json`; the disjoint
credentialed host/publisher phase starts only after the container terminates,
and `gtbi-checkpoint-publish` publishes only those exact bytes. No process or
container ever has network/publication capability and plaintext/key material
at the same time. Every planned
job resolves to exactly
one accepted source, original artifact or reconstructed bundle. If both exist,
their registered `job_logical_payload_digest` values must match; otherwise
merge blocks.

### Checkpoint And Recovery

Checkpoint record states:

```text
evaluated
early_rejected
fragment_bundle_completed
fragment_reduction_completed
timed_out
unsupported_approved
unsupported_unapproved
runtime_error
```

An original alias resolved by `economic_hash` has
`identity_resolution=deduped_alias`; this is mapping provenance, not a
scientific evaluator outcome.

Scientifically complete canonical states for this 72,000-pack baseline:

```text
evaluated
```

`early_rejected` is a schema-compatibility state only and its required count is
zero for this baseline. It cannot be emitted by the V6-equivalent evaluator.

`timed_out` and `runtime_error` are technical attempt outcomes requiring
recovery. They must never be counted as scientific failures or accepted as
complete campaign states.

For another campaign, `unsupported_approved` is complete only when the
scientific manifest lists that exact strategy ID and approved reason before
dispatch. For this approved 72,000-pack baseline:

```text
canonical_units_unsupported_approved=0
canonical_units_unsupported_unapproved=0
```

Any unsupported unit blocks this specific baseline campaign. The approved
unsupported state exists only for a different future manifest that explicitly
allows it before dispatch.

Checkpoint identity includes:

```text
campaign_id
runbook_core_digest
contract_digest
policy_hash
data_digest
strategy_pack_digest
record_identity
unit_id_or_null
unit_attempt_number_or_null
tile_id_or_null
tile_attempt_number_or_null
reduction_node_id_or_null
reduction_attempt_number_or_null
physical_evaluation_tile_manifest_digest_or_null
global_candidate_symbol_pair_set_digest
tile_candidate_symbol_pair_set_digest_or_null
fragment_reduction_manifest_digest_or_null
code_sha
execution_tree_digest
execution_workflow_bundle_digest
dependency_lock_digest
runtime_container_digest
numerical_environment_digest
scientific_numerical_semantics_digest
approved_numerical_execution_profile_registry_digest
schema_version
```

### Durable Checkpoint Transport

An atomic file on the runner is not a durable checkpoint because the runner
disk disappears after cancellation or VM loss.

V7 persists completed identities in immutable checkpoint microbatches:

```text
checkpoint_batch_max_records=20
checkpoint_batch_max_seconds=120
1<=checkpoint_fragment_bundle_max_fragments<=64
checkpoint_fragment_bundle_max_uncompressed_bytes<=16777216
checkpoint_batch_max_uncompressed_bytes<=134217728
github_actions_artifact_hard_limit_per_job=500
github_actions_artifact_safety_reserve_per_job=20
max_planned_actions_artifacts_per_job=480
checkpoint_name=<campaign_id>-<planned_job_id>-<workflow_run_id>-<recovery_generation_id>-<sequence>
```

A fragment bundle is sealed when either of its two limits is reached; a
checkpoint batch is published when its record, byte or time limit is reached.
The runbook freezes the exact values selected by the transport benchmark and
budgets the compressed/ciphertext expansion. The execution plan proves that
every job's checkpoint microbatches, final result bundle and control evidence
fit within `max_planned_actions_artifacts_per_job`; equality with or overflow
of the provider hard limit is forbidden. External content-addressed checkpoint
objects do not consume this Actions count, but every Actions handoff does.
The pinned upload action uses compression level zero for precompressed or
encrypted payloads, and the transport smoke proves the resulting digest,
restoration and measured upload time. Before any normal job exit,
cancellation acknowledgement or final bundle upload, every completed unsent
record is force-flushed as a final partial batch, replicated and durably
acknowledged; a job with 1 through 19 total records therefore still publishes
one valid batch. Failure to acknowledge that flush leaves the job unresolved
and recoverable, never successfully closed. Each JSONL line is one batch
object, not one ambiguous unit row:

```text
campaign_id
planned_job_id
workflow_run_id
github_job_id
github_run_attempt
recovery_generation_id
sequence
fork_parent_digest_or_null
previous_batch_digest_or_null
created_at_utc
record_count
records[]
content_digest
```

Each `records[]` entry is a discriminated union. All variants begin with:

```text
record_kind=scientific_outcome_record|scientific_fragment_bundle_record|scientific_fragment_reduction_record|technical_attempt_record
record_identity
unit_id_or_null
unit_attempt_number_or_null
tile_id_or_null
tile_attempt_number_or_null
reduction_node_id_or_null
reduction_attempt_number_or_null
record_state
scientific_context_key_digest
complete_reuse_key_digest_or_null
physical_evaluation_tile_manifest_digest_or_null
global_candidate_symbol_pair_set_digest
tile_candidate_symbol_pair_set_digest_or_null
fragment_reduction_manifest_digest_or_null
operational_attempt_digest
```

`record_identity` uses this exhaustive ASCII grammar and no ambient run/job
field:

```text
scientific_outcome_record:
  U/<unit_id>
scientific_fragment_bundle_record:
  B/<tile_id>/<bundle_candidate_symbol_pair_set_digest>
scientific_fragment_reduction_record:
  R/<planned_reduction_node_id>
technical_attempt_record:
  T/<work_identity_kind>/<work_identity_id>/<work_attempt_number>
```

`/` is reserved and therefore forbidden inside every component ID; digest
components retain their `sha256:<64 lowercase hex>` grammar. The campaign,
context and global pair-set bindings remain separate required fields and are
never smuggled into string concatenation. A repeated canonical outcome or
reduction node therefore collides deliberately and must have an identical
registered scientific/reduction digest; a repeated bundle with the same tile
and subset must have identical authenticated children; each technical attempt
has a unique identity. Different bundle partitioning may create different
bundle records, but child pair reconciliation still permits each scientific
fragment exactly once. Known-answer fixtures cover every branch, reserved
characters, maximum lengths, retry equivalence, deliberate collisions and
cross-campaign non-equivalence through the separately bound campaign field.

All variants also carry the complete typed
`operational_attempt_preimage_v1` object:

```text
schema_version
record_kind
record_state
record_identity
unit_id_or_null
unit_attempt_number_or_null
tile_id_or_null
tile_attempt_number_or_null
reduction_node_id_or_null
reduction_attempt_number_or_null
planned_job_id
workflow_run_id
github_job_id
github_run_attempt
recovery_generation_id
numerical_execution_profile_digest
runtime_threadpool_observation_digest
observed_hardware_digest
physical_evaluation_tile_manifest_digest_or_null
global_candidate_symbol_pair_set_digest
tile_candidate_symbol_pair_set_digest_or_null
fragment_reduction_manifest_digest_or_null
trusted_started_at_utc
trusted_ended_at_utc
timing_resource_telemetry_locator_or_null[
  immutable_object_id, object_version, byte_size, schema_version,
  plaintext_or_logical_digest
]
transport_locator_or_null[
  provider_artifact_id_or_external_object_id, immutable_name_or_version,
  byte_size, transport_digest
]
error_classification_or_null
technical_error_code_or_null
scientific_result_digest_or_null
scientific_fragment_bundle_digest_or_null
```

The inline object, or every non-null locator it names, is recoverable and
content-addressed independently of the final job artifact. A verifier restores
the located bytes, checks size/schema/digest and recalculates
`operational_attempt_digest`; an opaque digest or mutable locator is invalid.
Fields repeated by the batch/common/variant schemas must be byte-for-byte
equal. Exactly one identity branch is active: a complete outcome has non-null
unit/attempt/complete-reuse fields and null tile/tile-subset/bundle/reduction
fields; a fragment bundle has non-null tile/attempt/tile-subset/bundle fields
and null unit/complete-reuse/canonical-result/reduction fields; a fragment
reduction has non-null reduction-node/attempt/reduction-manifest fields and null
unit/tile/bundle/complete-reuse/canonical-result fields; and a technical attempt
identifies exactly one unit, tile or reduction branch and carries the same
non-null error code in both places. Every variant binds the same global
pair-set digest.

`scientific_outcome_record` then requires:

```text
record_state=evaluated|early_rejected|unsupported_approved
result_schema_version
result_size_bytes
scientific_result_digest
result_payload_or_content_addressed_locator
technical_error_code_or_null=null
scientific_fragment_bundle_digest_or_null=null
```

`scientific_fragment_bundle_record` then requires:

```text
fragment_bundle_schema_version
fragment_bundle_size_bytes
fragment_count
scientific_fragment_bundle_digest
bundle_candidate_symbol_pair_set_digest
fragment_bundle_payload_or_content_addressed_locator
scientific_result_digest_or_null=null
technical_error_code_or_null=null
record_state=fragment_bundle_completed
```

`scientific_fragment_reduction_record` then requires:

```text
record_state=fragment_reduction_completed
reduction_result_schema_version
reduction_result_size_bytes
fragment_reduction_manifest_digest
reduction_payload_or_content_addressed_locator
scientific_result_digest_or_null=null
scientific_fragment_bundle_digest_or_null=null
technical_error_code_or_null=null
```

`technical_attempt_record` then requires:

```text
record_state=timed_out|runtime_error|unsupported_unapproved
result_schema_version_or_null=null
result_size_bytes=0
scientific_result_digest_or_null=null
scientific_fragment_bundle_digest_or_null=null
result_payload_or_content_addressed_locator_or_null=null
technical_error_code
```

Only `evaluated`, `early_rejected` or manifest-approved scientific terminal
states may use `scientific_outcome_record`.
`scientific_fragment_bundle_record` and
`scientific_fragment_reduction_record` are mergeable, nonterminal partial
results; every child remains individually authenticated and neither record
satisfies canonical coverage by itself. A reduction record is accepted only
when its consumed, forwarded, completed and unresolved pair sets reconcile
exactly with its immutable planned reduction node. `timed_out`, `runtime_error`
and unapproved unsupported attempts use
`technical_attempt_record`; they never satisfy scientific coverage or supply a
mergeable scientific payload. `record_state` is the terminal state of that
checkpoint record, not necessarily of its canonical strategy: only an accepted
`scientific_outcome_record` can close canonical scientific coverage.

`scientific_result_digest` uses `GTBI_SCIENTIFIC_UNIT_RESULT_V1` over the
complete schema-typed scientific outcome only: canonical unit identity,
scientific-context and complete-reuse identities, terminal scientific state,
normalized trades, annual rows, metrics, filter decisions and deterministic
scientific diagnostics. It excludes run/job/attempt IDs, timestamps, timings,
hardware telemetry, transport locators, logs and error text.
`operational_attempt_digest` uses `GTBI_OPERATIONAL_ATTEMPT_V1` over the
entire `operational_attempt_preimage_v1` object above. The digest itself is not
inside that object. Scientific-outcome checkpoint dedupe and
equivalence compare only non-null `scientific_result_digest`; technical-attempt
records are reconciled by `operational_attempt_digest` and can never deduplicate
or satisfy a scientific outcome. Fragment-bundle dedupe first verifies the
registered bundle digest and then each registered
`scientific_fragment_result_digest` plus its exact candidate-symbol pair; it
never promotes a bundle to a complete result. Audit and retry reconciliation
verify the operational digest for all four variants. No digest has an implicit
or prose-defined preimage.

Records are sorted by
`(record_identity, record_kind)`,
`record_count=len(records)`, and fixtures cover both one-record and
twenty-record batches, including mixed
canonical/fragment-bundle/fragment-reduction/technical records and attempt
numbers. Sequence zero
requires `previous_batch_digest_or_null=null`; a recovery generation additionally
requires `fork_parent_digest_or_null` to equal the last trusted digest of its
parent chain, while an original generation requires it to be null. Every later
batch in the same generation requires the exact prior accepted digest and a
null fork parent. `workflow_run_id` plus the controller-assigned monotonic
`recovery_generation_id` makes chain identity globally unique even when
`github_run_attempt` restarts at one. A duplicate
`(record_identity,record_kind)` within a batch, unsorted record, mismatched
count or digest fails validation.
`content_digest` is exactly `HASH[GTBI_CHECKPOINT_BATCH_V1]` over the typed
batch object with the `content_digest` field omitted; all other fields,
including both predecessor fields and ordered `records[]`, are present. The
known-answer registry freezes empty/predecessor and 1/20-record vectors and
rejects hashing a null placeholder or the digest field itself.

For `evaluated`, the checkpoint contains the complete mergeable canonical
outcome, annual rows, diagnostics and any result components needed to
reconstruct final outputs, or a content-addressed locator whose bytes,
size, schema and digest are restored and verified before the unit is considered
durable. A digest without recoverable bytes is not a checkpoint. No mutable tag
or job artifact is the sole locator.
For `fragment_bundle_completed`, the same recoverability rule applies to the
complete typed bundle and every child fragment payload. Recovery may schedule
only missing candidate-symbol pairs and must still reconstruct the full
canonical result before terminal coverage.
For `fragment_reduction_completed`, the same rule applies to the complete typed
reduction manifest, every consumed or forwarded child reference and every
completed canonical result it names. A digest without restorable bytes cannot
close a reduction node.

Transport:

- GitHub Actions artifact with a unique immutable name for synthetic smoke and
  non-sensitive non-canonical campaigns;
- encrypted source-owned external checkpoint objects, published through the
  one-object OIDC write capability, for any real-data smoke whose licence
  decision restricts derived detail;
- encrypted short-retention Actions microbatch plus destination-owned durable
  replica during an approved full; compacted source external checkpoint object
  by digest after matrix capacity is released;
- final job bundle consolidates and references every checkpoint batch.

For an approved full, the independent destination asynchronously pulls each
published checkpoint digest and records a chained replication receipt within
the microbatch deadline plus the measured transfer allowance. Checkpoint RPO is
explicitly **per planned-job chain**. Each chain has exactly 20 exposure
record credits shared by active fragment-bundle assemblers, complete canonical
outcomes, completed-but-unsealed records and records in its one sealed
unacknowledged microbatch. Before starting a candidate-major canonical unit or
opening a fragment bundle, the controller atomically reserves one credit; it
starts nothing when credits are exhausted. Each bundle independently enforces
its child-count and byte limits. A large physical tile is consumed through this
bounded deterministic iterator, not as one unbounded in-flight operation. On
size/byte/time trigger it stops new work, seals currently completed records and
lets already running work drain into already reserved bounded bundle buffers.
Those later completions cannot form another published batch until the first
destination acknowledgement releases their credits; they remain inside the
same 20-record exposure bound. The 120-second trigger measures from the first
unsealed completion, not from assignment of a potentially long-running unit.
Normal exit force-flushes the remaining partial batch and waits for its durable
acknowledgement.

Thus each chain has at most one sealed unacknowledged microbatch and at most 20
not-yet-destination-durable records. In candidate-major mode this is at most 20
complete units; in fragmented modes it is at most
`20 * checkpoint_fragment_bundle_max_fragments` candidate-symbol pairs and the
frozen byte cap. With 360 scientific jobs the runbook computes and budgets both
exact aggregate bounds rather than labelling every record a unit. Source
deletion is forbidden until its destination receipt exists.
Recovery can restore either copy and must compare both when both are available.

Recovery trusts a batch only after digest, chain, campaign identity and
work-result validation against every checkpoint-identity field. Missing final job
artifacts do not invalidate already published checkpoint batches.

A retry starts a new uniquely named generation with sequence zero and null
`previous_batch_digest_or_null`; its separate `fork_parent_digest_or_null`
cites the last trusted parent digest, or is null only when no predecessor
exists.
Forked chains are reconciled by `record_identity`, variant and registered
scientific result or fragment-bundle digest under the duplicate rules below; an
unexplained chain gap or cycle blocks recovery.

Execution is idempotent and at least once, not falsely claimed as exactly once.
If a runner finishes a work item but loses its acknowledgement, recovery may
produce the same record again:

- identical unit outcomes collapse by `unit_id`, identity fields and
  `scientific_result_digest`; identical fragment bundles collapse only after
  every child pair/digest verifies; identical fragment-reduction records
  collapse only after their planned node, complete typed manifest and every
  consumed/forwarded/completed child digest verify; technical attempts never
  satisfy scientific coverage;
- the deterministic retained attempt is the lowest
  `(work_attempt_number, content_digest)`; timestamps remain operational metadata
  and never affect scientific selection;
- any duplicate with a different result or identity blocks the merge;
- no duplicate can increase evaluated, rejected or failure row counts.

Before any scientific work attempt starts, the external attempt registry
atomically
increments one unsigned monotonic counter keyed by
`(campaign_id, work_identity_kind, work_identity_id)` and returns that value as
`work_attempt_number`. `work_identity_kind` is exactly
`canonical_unit|physical_tile|fragment_reduction`.
Workers cannot choose, reuse or decrement it. A lost reservation remains an
audited unused attempt number; it is never recycled. Recovery-generation,
split-chain, collision and counter-race fixtures prove uniqueness and enforce
the frozen maximum technical attempts.
Checkpoint and diagnostic projections place that same number into exactly one
of `unit_attempt_number_or_null`, `tile_attempt_number_or_null` or
`reduction_attempt_number_or_null`; the other two are null. Their corresponding
identity field must equal the registry key.
Each lifecycle transition appends `external_attempt_event_v1` with schema
version, campaign/work identity, authority generation, epoch, attempt number,
assigned work/pair-subset digest, sequence, previous-event digest, expected CAS
version, prior status, new status, trusted UTC, actor/attestation, terminal
evidence digest or null, terminal reason or null and `event_digest` under
`GTBI_EXTERNAL_ATTEMPT_EVENT_V1`, with only `event_digest` omitted. The only
legal state paths are:

```text
reserved -> started -> succeeded
reserved -> started -> technical_failed
reserved -> reservation_unused
```

`reservation_unused` proves that execution never started and is terminal.
`succeeded` proves that the exact assigned work or pair subset has durable
accepted output; it does not by itself claim that a parent tile, reduction tree
or canonical unit is scientifically complete. `technical_failed` names exactly
one timeout, OOM, infrastructure or runtime-error classification and its
durable diagnostic. A started attempt cannot become unused; a terminal attempt
cannot transition again. Sequence-zero, every legal transition, every illegal
transition, stale CAS, duplicate event and terminal-evidence mismatch have
known-answer fixtures.

The registry is an authoritative source-domain service, not an unnamed
external dependency. `work_attempt_registry_manifest.json` freezes its owner,
provider/account/region, deployment and schema digest, hash-chain head,
strong-consistency/CAS contract, IAM and operation allowlist, KMS/object-lock
policy, hard budget, backup/restore identities, RPO, RTO, monitoring route and
teardown manifest. It is deployed by `PREV7-0610`, independently restored and
fault-tested by G6B/G7, included in the immutable external-security
configuration and runbook core, and retained until package closure. A registry
outage stops new attempts; no local or inferred counter is permitted. Its
append-only counter/event chain is synchronously copied to the destination
WORM domain. Failover is active/passive: a destination recovery registry may
become the single writer only after source fencing is provider-authenticated,
both domain owners consume a recovery authorization and the epoch increases;
the old epoch can never write again. Split-brain, stale-replica and failback
fixtures are mandatory.

### Timeout And Worker Replacement

Every canonical unit, physical tile and fragment-reduction node executes with a
parent-controlled deadline.

The benchmark defines `work_item_timeout_seconds` from the measured slow-family,
tile and reduction distributions plus a documented safety margin. It is fixed
in the approved
runbook core. A timeout changes only the recovery route, never the scientific
outcome. Recovery may use an already proven equivalent execution mode and one
worker, but cannot alter rules, dates, data or precision.

On timeout:

1. place every work item in its own cgroup/process group and terminate that complete
   tree, not only the direct Python child;
2. wait exactly `10` seconds;
3. kill it if still alive;
4. verify no descendant, file descriptor, mapped file or shared-memory segment
   belonging to the work item remains, then release its handles;
5. record the technical attempt;
6. replace the worker before accepting more work;
7. send the exact work identity and dependent missing pair subset to selective
   recovery;
8. never mark a dependent scientific unit complete.

A stuck canonical unit, physical tile or fragment-reduction node must not
permanently block the persistent pool.

Timeout, OOM and infrastructure attempts share the frozen
`max_initial_technical_attempts_per_work_identity=3`; the separately approved
absolute campaign ceiling is
`max_total_technical_attempts_per_work_identity=5`. Exhausting the initial
three leaves that work identity and every dependent unit/pair unresolved and
blocks completion; it never manufactures a failure row. The default terminal
diagnostic is `campaign_incomplete`, and the campaign controller atomically
enters `RECOVERY_AUTH_REQUIRED`. Further execution requires a
`recovery_authorization_envelope` approved through the scientific, workflow,
acceptable-use, independent-security and owner environments. It binds all five
fresh receipt digests, current terms/deployed-security observations, the
original runbook-core and dispatch-capsule
digests, exact unresolved work identities and pair subsets, prior attempt
digests, unchanged scientific and runtime identities, and for every identity an
explicit remaining attempt allowance no greater than
`5 - attempts_already_reserved`, incremental
budget and expiry. It may select only a previously proven equivalent execution
mode. Before execution, the independent destination copies/restores it and an
immutable recovery dispatch capsule binds that sync receipt. A rule, date,
data, precision, code, dependency or contract change is forbidden and creates
a new campaign identity rather than appending incompatible attempts.
Exhausting the absolute fifth attempt makes that work identity and its
dependent coverage permanently unresolved for this campaign; no recovery
envelope may increase that ceiling or reset it by splitting or renaming the
same planned work.

The original authorization envelope is immutable provenance only during
recovery. Recovery authorization has its own creation time, absolute expiry,
fresh role/review/protection snapshots, acceptable-use/terms receipt,
deployed-security configuration/observation receipt, vulnerability receipt,
incremental budget and one-time consumption-registry key.

Each exhausted-attempt event creates a conditional operational task
`RECOVERY-<campaign_id>-<sequence>` in the immutable campaign recovery registry,
not a silently edited readiness task. Its record includes unresolved-work and
pair-set manifest digest, owner, all five
scientific/workflow/acceptable-use/security/
owner approval receipts, `gtbi-scientific-review`, `gtbi-workflow-review`,
`gtbi-acceptable-use-review`, `gtbi-security-review` and
`gtbi-full-authorization` deployment
IDs, independent-destination sync receipt, incremental budget, expiry, status
and final evidence digest. No task is created when recovery is not needed;
once created, it cannot be omitted from campaign completion accounting.

Each recovery task follows:

```text
created -> awaiting_approval -> authorized -> consumed
consumed -> dispatch_reconciling
dispatch_reconciling -> running | failed | dispatch_indeterminate
running -> succeeded | failed
created | awaiting_approval | authorized -> expired | cancelled
```

Expiry/cancellation after consumption is invalid. Every new authorization uses
a new sequence and cannot reuse a capsule, receipt, lease or budget. An
ambiguous dispatch follows the bounded idempotency/API reconciliation protocol
in section 10 and cannot skip directly to retry.

Recovery:

- launches only missing or invalid canonical units, tiles, reduction nodes or
  exact missing pair subsets;
- never restarts a successful work identity or an already accepted pair;
- verifies input identity;
- retries transient failures;
- replans OOM work only onto an already approved lower-concurrency execution
  profile with an immutable substitution receipt;
- keeps the same scientific inputs;
- produces the same final merge.

Never relaunch a complete full campaign to repair an artifact or merge.

### Hierarchical Merge

Use:

```text
job outputs
-> merge blocks
-> merge superblocks when required
-> final merge
```

The final merge downloads block outputs, not thousands of worker artifacts.

The immutable execution plan chooses block and optional superblock membership
before dispatch. Its exact merge projection is
`planned_reduction_topology_manifest.json`:

```text
schema_version
campaign_id
execution_plan_digest
ordered_blocks[
  planned_block_id, ordered_planned_job_ids,
  referenced_unit_set_digest,
  owned_terminalization_unit_set_digest,
  expected_candidate_symbol_pair_set_digest_and_count,
  ordered_owned_reduction_node_ids
]
ordered_superblocks[
  planned_superblock_id, ordered_planned_block_ids,
  referenced_unit_set_digest,
  owned_terminalization_unit_set_digest,
  expected_candidate_symbol_pair_set_digest_and_count,
  ordered_owned_reduction_node_ids
]
direct_final_block_ids
final_superblock_ids
planned_job_count
planned_block_count
planned_superblock_count
planned_reduction_node_count
planned_reduction_topology_manifest_digest
```

It uses `GTBI_PLANNED_REDUCTION_TOPOLOGY_MANIFEST_V1` and `self_field` storage,
omitting only its own digest. Every job, block, superblock, pair and reduction
node is present exactly once at the applicable level; parent/child references
are cycle-free and the union is exactly the execution-plan topology. CI
recomputes this projection from `execution_plan_v1` and requires byte-identical
typed content before dispatch.

After worker upload/recovery/compaction,
`resolved_block_inputs.json` maps every planned job to exactly one original or
reconstructed bundle and records provider artifact ID, immutable name,
transport digest and registered `job_logical_payload_digest`. Runtime artifact identifiers are
never pretended to exist before upload. A block contains at most `180` worker bundles and stays below
the measured download, decompression, file-count, disk and memory budgets.
Block jobs never discover inputs by wildcard alone: each receives the exact
resolved manifest. Superblocks are added only when
the final merge would otherwise exceed a measured budget. Retries preserve the
same membership and block identity.

Each successful block emits canonical `block_result_manifest.json`; each
superblock emits `superblock_result_manifest.json`. Both contain schema
version, campaign/plan/context/policy hashes, level and immutable planned
block ID, ordered child IDs and child logical payload digests, expected and
terminalization-owned/referenced/terminal unit sets and counts, output-member
manifest/digests, code/runtime
identity, attempt/generation and their own typed manifest digest with that
digest field omitted from its preimage. Publication adds a separate provider
artifact receipt without rewriting the logical manifest.
The job, block and superblock manifest domains are respectively
`GTBI_JOB_RESULT_MANIFEST_V1`, `GTBI_BLOCK_RESULT_MANIFEST_V1` and
`GTBI_SUPERBLOCK_RESULT_MANIFEST_V1`; each uses `self_field` storage named
`manifest_digest`.

Each level also emits a reconstruction-stable logical digest. A block uses
`HASH[GTBI_BLOCK_LOGICAL_PAYLOAD_V1]`; a superblock uses
`HASH[GTBI_SUPERBLOCK_LOGICAL_PAYLOAD_V1]`. Their exhaustive typed preimage is:

```text
schema_version
campaign_id
scientific_context_key_digest
policy_hash
level
planned_block_or_superblock_id
ordered_child_ids
ordered_child_logical_payload_digests
referenced_unit_ids_and_count
owned_terminalization_unit_ids_and_count
terminal_unit_ids_and_count
expected_candidate_symbol_pair_set_digest_and_count
accounted_candidate_symbol_pair_set_digest_and_count
owned_reduction_node_ids_and_count
completed_reduction_node_ids_and_count
ordered_logical_output_members[
  path, schema_version, row_count, logical_content_digest
]
```

At both block and superblock levels,
`ordered_logical_output_members` contains exactly, in canonical path order:

```text
canonical_outcomes.parquet
fragment_reduction_manifest.json
leaderboard.parquet
unresolved_scientific_fragments.parquet
yearly_performance.parquet
```

`fragment_reduction_manifest.json` binds every consumed fragment digest, every
forwarded unresolved fragment digest and each newly completed canonical result
digest. A fragment disappears from the unresolved table only in the same
logical object that proves its unique canonical reduction. The final merge
requires the unresolved table to be empty and every planned pair to be consumed
exactly once. Every intermediate level requires its accounted pair set to equal
its planned subset and its completed plus forwarded reduction ownership to equal
its owned-node set. Its terminal units must equal exactly the units assigned to
terminalization nodes owned by that level; referenced units owned by a later
level remain nonterminal without being treated as missing. It cannot defer a
missing child or its own reduction, or accept a foreign terminal result, at the
final merge. All resolution maps, result manifests, checkpoints, diagnostics,
telemetry, errors and transport records are operational inputs/evidence and are
excluded. A new logical scientific member requires a schema/domain version
bump.

Exclusion from the logical scientific digest never means deletion. Every block
and superblock result manifest has a second exhaustive
`ordered_operational_evidence_members` inventory. It binds path, schema version,
row/record count, byte count and content digest for the operational evidence
produced at that level. The merge performs these deterministic operations:

```text
timing_diagnostics.parquet:
  union every accepted canonical-unit, physical-tile or fragment-reduction
    operational attempt
  sort by campaign_id, record_identity, planned_job_id,
    github_run_attempt, github_job_id

canonical_timing_summary.parquet:
  derive exactly one operational summary row per canonical unit from the
    accepted timing rows and the frozen tile/reduction graph
  reject a missing, duplicated or unreferenced attempt and any attribution
    whose component digests do not close to that canonical unit
  sort by campaign_id, unit_id

resource_samples.parquet:
  union every valid sampler row
  sort by campaign_id, planned_job_id, github_run_attempt, github_job_id,
    sampler_generation, sample_sequence, pid, phase

errors.jsonl:
  validate and canonicalize every structured error record
  sort by campaign_id, record_identity, error_code,
    operational_attempt_digest

checkpoint.jsonl and child manifests/receipts:
  retain by immutable child identity and digest
  do not concatenate them into a fabricated checkpoint chain

numerical_execution_profile_map.json and observed_hardware_profile_map.json:
  derive one row per planned job from authenticated accepted attempt receipts
  bind each accepted runtime_threadpool_observation_digest
  reject missing, duplicate, unknown, unapproved, noncompliant or unassigned
    profile/observation rows
  sort by planned_job_id under the canonical unsigned UTF-8 ordering
```

At final merge, `timing_diagnostics.csv` is the deterministic CSV projection of
the accepted attempt table and `canonical_timing_summary.csv` is the
deterministic projection of its one-row-per-canonical-unit reduction;
`resource_samples.parquet` preserves the accepted typed samples and
`resource_summary.json` derives only from those rows;
`errors.jsonl` preserves the accepted canonical structured-error ledger;
`failure_report.json` and the alias-expanded timeout, unsupported, runtime-error
and missing CSVs derive from the reconciled canonical outcomes/attempt ledger
plus `canonical_map.csv`. `operational_evidence_index.json` exhaustively binds
all retained operational members and
`checkpoint_evidence_index.json` binds each child checkpoint, manifest and
receipt by immutable identity/digest or durable versioned locator. Each level
checks input and output row/record equations, so an omitted, duplicated,
conflicting or malformed diagnostic/error/sample/index row blocks package
closure even though those rows do not change `job_logical_payload_digest`,
`block_logical_payload_digest`, `superblock_logical_payload_digest` or
`scientific_output_digest`.

Attempt/generation/run/job IDs, trusted times, provider artifact identifiers,
transport/encryption digests, telemetry and receipts are excluded from the
logical scientific preimage only. They remain bound by the operational result
manifest, operational-evidence index and receipts.
Each result manifest stores its applicable logical digest as a required field;
that field is excluded from the logical preimage and included normally in the
separate typed result-manifest digest.

`resolved_block_outputs.json` and, when used,
`resolved_superblock_outputs.json` map every planned block exactly once to an
original or reconstructed logical result. Deterministic acceptance and retry
dedupe use only the applicable registered job/block/superblock logical-payload
digest after verifying the same planned identity. Equal digests are operational
duplicates and the lowest technical attempt is selected only as the transport
source. Different logical digests for the same planned identity are conflicts
and block final merge; no collection of separately compared operational fields
may override that result. The final merge consumes only this exact resolution
map, never wildcards or “latest” artifacts.
Each resolution map carries a `self_field` named `resolved_outputs_digest`.
Its typed preimage contains exactly schema version, campaign ID,
execution-plan/context/policy digests, level, and the ordered rows
`(planned_identity,selected_source_type,selected_attempt_identity,`
`logical_payload_digest,artifact_receipt_digest,`
`reconstruction_receipt_digest_or_null)`. Block and superblock maps use
`GTBI_RESOLVED_BLOCK_OUTPUTS_V1` and
`GTBI_RESOLVED_SUPERBLOCK_OUTPUTS_V1` respectively, omitting only
`resolved_outputs_digest`.

Merge requirements:

- stream Parquet row groups and use bounded-memory external sorting when a
  table exceeds the measured merge memory budget;
- deterministic sort keys;
- input bundle hash verification;
- referenced, terminalization-owned and terminal unit-set/count verification;
- exact expected/accounted pair-set and owned/completed reduction-node
  verification at every level;
- no row loss;
- identical retry duplicates collapsed without double counting;
- conflicting duplicate canonical units rejected;
- alias expansion traceability;
- corrupt and empty bundle rejection;
- final missing-unit rejection and intermediate owner-aware forwarding;
- summary counts derived from actual rows;
- final numerical-execution and observed-hardware maps cover exactly every
  planned job, reconcile to their approved registries and map digests, and
  preserve every approved recovery substitution;
- `best_candidate_id` must exist in leaderboard;
- empty leaderboard implies null best candidate;
- `canonical_units_evaluated` equals canonical-leaderboard rows;
- `total_strategies_evaluated` equals alias-expanded leaderboard rows.

### Telemetry

Sample CPU and memory every `0.5` seconds by phase.

One lightweight sampler per job observes the parent and children; workers do
not each run a sampler. It uses monotonic time for durations, UTC only for
labels, buffers samples and writes them in batches. Benchmark telemetry on and
off on the same batch:

```text
telemetry_overhead_pct<=1.0
```

If the default interval exceeds that budget, increase the interval
deterministically and record the selected value in the execution profile.

Record:

```text
timestamp
sampler_generation
sample_sequence
run_id
planned_job_id
github_job_id
github_run_attempt
pid
phase
wall_seconds
cpu_seconds
effective_cpu_cores
cpu_percent_process
cpu_percent_system
peak_rss_mb
process_tree_rss_mb
process_tree_pss_mb
cgroup_memory_current_mb
vms_mb
thread_count
child_process_count
queue_depth
active_workers
completed_units
download_bytes
upload_bytes
io_read_mb
io_write_mb
cache_hits
cache_misses
deduped_count
early_rejected_count
timeout_count
runtime_error_count
```

For each sample interval:

```text
raw_effective_cores =
  delta(cumulative_process_tree_cpu_seconds)
  / delta(suspend_inclusive_monotonic_wall_seconds)
effective_cpu_cores =
  min(raw_effective_cores, effective_cgroup_cpu_quota_cores)
```

The sampler discovers the complete process tree, handles worker replacement
without double-counting prior PIDs and labels warm-up samples separately.
Missing/invalid intervals are counted and excluded under a frozen maximum-
missing-sample policy; they are never silently treated as zero. Per-phase
statistics use only that phase's valid post-warm-up population and report its
sample count and missing count.

Phases:

```text
runner_startup
checkout
environment_prepare
artifact_download
data_load
feature_build
signal_build
simulation
annual_metrics
serialization
artifact_upload
idle_wait
```

Per-phase summary:

```text
seconds
cpu_seconds
mean_effective_cores
p50_effective_cores
p95_effective_cores
peak_rss_mb
io_read_mb
io_write_mb
worker_utilization_pct
```

Memory acceptance uses the cgroup value when available; summed child RSS is
diagnostic because shared mapped pages can otherwise be counted more than
once.

### V7 Diagnostic Outputs

Every V7 campaign first closes an immutable scientific/result package at the
end of deterministic merge and internal schema validation. It then produces a
public-safe Actions handoff and external publication/restore attestations:

```text
github_actions_artifact=global-technical-buy-indicator-v7-performance-results
durable_result_identity=<campaign_id>@sha256:<durable_result_digest>
publication_attestation_chain=publication_attestation.jsonl
```

The licence decision controls the Actions artifact contents. For a real
campaign, that artifact contains only allowlisted non-sensitive manifests,
validation status, ciphertext-envelope metadata and private-package digests.
The final encrypted scientific bundle may be present as ciphertext, but no
plaintext detailed result is. The canonical publisher copies only validated
ciphertext and cannot decrypt it. Plaintext exists only in the protected
validator/authorized restore container. The output compatibility contract
applies to the decoded logical private result package.

```text
_SUCCESS
_INCOMPLETE
_PACKAGE_CLOSED
output_manifest.json
scientific_output_manifest.json
engine_result_manifest.json
scientific_manifest.json
scientific_contract.json
schema_catalog.json
hash_domain_registry_v1.json
canonical_serialization_profile.json
scientific_schema_set.json
operational_schema_set.json
strategy_pack_manifest.json
data_snapshot_identity.json
data_manifest.json
exact_universe_identity.json
input_partition_manifest_set.json
input_partition_manifests.jsonl
instrument_identity_sets.jsonl
feature_demand_manifest.json
scientific_symbol_eligibility_sets.jsonl
complete_reuse_keys.jsonl
global_unit_reuse_key_set.json
canonical_map.json
physical_data_layout_manifest.json
cost_profile.json
execution_plan.json
matrix_partition_manifest.json
job_assignment_manifest_set.json
job_assignment_manifests.jsonl
planned_reduction_topology_manifest.json
candidate_symbol_pair_set.json
physical_evaluation_tile_manifest_set.json
final_fragment_reduction_manifest.json
scientific_fragment_index.json
execution_tree_manifest.json
execution_workflow_bundle.json
scientific_numerical_semantics.json
parallel_mode_equivalence_policy.json
approved_numerical_execution_profile_registry.json
numerical_execution_profile_assignment.json
numerical_execution_profile_map.json
runtime_threadpool_observations.jsonl
approved_hardware_profile_registry.json
observed_hardware_profile_map.json
parallel_mode_equivalence_report.json
job_assignment_manifest.csv
job_result_receipts.csv
resolved_block_inputs.json
campaign_run_registry.jsonl
authority_generation_registry.jsonl
external_security_operation_lease_registry.jsonl
github_job_status.csv
workflow_check_status.csv
canonical_map.csv
dedupe_map.csv
feature_manifest.csv
timing_diagnostics.csv
canonical_timing_summary.csv
resource_samples.parquet
resource_summary.json
errors.jsonl
operational_evidence_index.json
checkpoint_evidence_index.json
cost_reconciliation_report.json
recovery_task_registry.jsonl
equivalence_report.json
coverage_report.json
failure_report.json
strict_validation.json
selection_bias_diagnostics.json
early_rejected_strategies.csv
timeout_strategies.csv
unsupported_strategies.csv
runtime_errors.csv
missing_strategies.csv
slow_deferred_strategies.csv
canonical_leaderboard.parquet
canonical_filtered_leaderboard.parquet
leaderboard.csv
filtered_leaderboard.csv
yearly_trade_performance.csv
top_indicator_rules.jsonl
top_trades_sample.csv
summary.json
v6_output_compatibility_manifest.json
output_migration_map.csv
```

This is the mandatory V7 core path catalog, not permission to omit a preserved
V6 consumer output. The exact decoded private package path set is the union of
all non-marker core paths, every path classified `emitted` by
`v6_output_compatibility_manifest.json`, `output_manifest.json` itself and
exactly one state-appropriate marker from
`_SUCCESS|_INCOMPLETE|_PACKAGE_CLOSED`; every `replaced` path is accounted for
by `output_migration_map.csv`. The entries inside `output_manifest.json` are
exactly that resolved package path set minus `output_manifest.json` and all
three marker names. Thus the manifest never hashes itself, only the one actual
marker exists, and an unlisted extra or required missing member is rejected.
The JSON/JSONL identity files above contain the exact registered typed objects,
not summaries reconstructed from CSV. Their sets close every referenced child
digest and count: all input partitions and instrument sets, all 3,600
per-unit eligibility and complete-reuse objects, the global reuse set, every
job assignment and the complete reduction topology. Exact historical price
rows and retained fragment bytes remain in their authenticated encrypted
stores and are referenced by immutable dual-restorable locators; the package
does not duplicate licensed or multi-gigabyte data merely to be self-
describing. An offline verifier supplied with those retained objects, the
package and the frozen runtime can resolve the entire digest graph without
consulting mutable GitHub state.
The two final profile maps are reconstructed only from authenticated per-job
receipts, cover exactly the planned-job set in `execution_plan.json`, and
reconcile their registered digests to `summary.json`. The approved registries
and equivalence report are immutable inputs referenced by the runbook; the
final package carries exact copies so an offline verifier can validate every
assignment and substitution without consulting mutable infrastructure.
`scientific_fragment_index.json` contains every accepted fragment result digest,
its canonical unit/symbol partition, reduction node, consumed reduction-
manifest digest and durable encrypted source/destination locator/version. The
final package need not duplicate all intermediate fragment bytes, but package
closure proves dual restore of the complete indexed set and freezes a retention
deadline no earlier than the recovery/audit window. Neither source cleanup nor
checkpoint compaction may remove a fragment before its canonical reduction,
dual-copy restore and retained index entry are all verified.

The three marker paths above are schema members but mutually exclusive package
states. Exactly one exists in a closed package:

```text
scientific_success: _SUCCESS only
diagnostic_incomplete: _INCOMPLETE only
transport_closed_without_scientific_claim: _PACKAGE_CLOSED only
```

`_PACKAGE_CLOSED` is permitted only for a transport-only package that contains
no scientific success claim. A package cannot contain any pair of these
markers, and a scientific consumer accepts only `_SUCCESS`.

The private complete package freezes these diagnostic schemas. It contains only
facts known by package closure. Result validation, publication, destination
restore, cost-tail reconciliation and cleanup happen later and append to
`publication_attestation.jsonl`, whose events bind `durable_result_digest`,
previous-event digest, actor, operation, run/job identity and receipt digest.
They also bind schema version, campaign ID, sequence, trusted UTC and
`event_digest` under `GTBI_PUBLICATION_ATTESTATION_EVENT_V1`, with only
`event_digest` omitted.
That external chain is never inserted into or used to rewrite the closed
package. Every event is copied to source and independent-destination immutable
storage and advances a content-addressed CAS head; a missing predecessor,
conflicting head or source-only event blocks operational completion.

`campaign_run_registry.jsonl` is the authoritative source-owned append-only CAS
registry for preclosure GitHub execution. Each canonical row records campaign,
monotonic sequence/epoch, authority generation, workflow/run ID, run attempt,
role, exact admitted operation/plan digest, admission capsule/lease digest,
predecessor digest and `HASH[GTBI_CAMPAIGN_RUN_EVENT_V1]` event digest with that
field omitted. The destination asynchronously mirrors and attests each head.
After every planned operation is either admitted or
terminally cancelled and no continuation/recovery/compaction/merge admission
remains possible, the controller CAS-seals the registry with exact ordered run
IDs/count, head digest and destination sync receipt under
`GTBI_CAMPAIGN_RUN_REGISTRY_SEAL_V1`, omitting only its
`campaign_run_registry_digest` field. That computed field is the same value
reported by `summary.json`; it is not a second digest over a different
preimage. A run absent from this
registry is unauthorized and cannot contribute bytes; a run added after the
seal is a conflict that invalidates package closure.

Package closure runs in a separate protected
`gtbi-v7-package-close.yml` workflow triggered only after the authoritative
campaign CAS registry has sealed its complete set of admitted planning,
scientific, continuation, recovery, compaction and merge workflow run IDs. No
new run may be admitted after that seal. Its sole privileged job uses the
existing `gtbi-result-validate` environment and validator route; it has no
dispatch, campaign-admission, publisher or arbitrary GitHub-write authority.
The closer restores the proposed
package and sealed registry, queries every job, check suite and run attempt of
every admitted run ID with complete pagination, validates
all rows/digests/equations, writes the final package and marker, and then
records its own workflow/job receipt only in the external operational
attestation chain. The package's zero-in-progress predicate applies to the
entire sealed admitted-run set, never to the currently executing package-closer
job. The
closer cannot add or change a scientific row; any validation failure emits only
`_INCOMPLETE` evidence and blocks publication.

`github_job_status.csv` has one row per immutable GitHub job ID across every
workflow in the sealed campaign-run registry. It
does not include result-validation, publication, restore or cleanup jobs:

```text
workflow_run_id, github_job_id, job_name, job_role, github_run_attempt, planned_job_id,
status_raw, conclusion_raw, status_normalized, conclusion_normalized,
started_at_utc, completed_at_utc, source_api_digest
```

Raw provider values are preserved verbatim. Normalization covers every current
GitHub value, including statuses `requested|queued|pending|waiting|in_progress|
completed` and conclusions `success|failure|cancelled|skipped|timed_out|stale|
neutral|action_required|null`, plus an
`unknown_provider_value` fail-closed bucket. `requested`, `queued`, `pending`,
`waiting`, `in_progress` and null conclusion are nonterminal and must be zero at
package closure. `timed_out`, `stale`, `action_required`,
unexpected `neutral` and unknown values map to recovery-required or terminal
failure under the frozen table; none disappears from accounting. Pagination
and reruns append new job IDs; they never replace prior rows.

Startup failures that occur before GitHub creates a job ID belong to the
separate `workflow_check_status.csv` ledger keyed by workflow run/check-suite
ID, raw provider state and evidence digest. They are never fabricated as
`github_job_status.csv` rows. Its `workflow_checks_startup_failure` count is
blocking and reconciles independently.

```text
workflow_run_id,check_suite_id,check_run_id_or_null,status_raw,
conclusion_raw,normalized_failure_class,created_at_utc,completed_at_utc_or_null,
source_api_digest
```

`timing_diagnostics.csv` has one row per accepted operational attempt. Its
discriminated identity prevents a physical tile or a reduction from being
misreported as one candidate:

```text
campaign_id
run_id
planned_job_id
github_job_id
github_run_attempt
record_identity
attempt_scope=canonical_unit|physical_tile|fragment_reduction
unit_attempt_number_or_null
tile_attempt_number_or_null
reduction_attempt_number_or_null
unit_id_or_null
tile_id_or_null
reduction_node_id_or_null
canonical_strategy_id_or_null
physical_evaluation_tile_manifest_digest_or_null
global_candidate_symbol_pair_set_digest
tile_candidate_symbol_pair_set_digest_or_null
fragment_reduction_manifest_digest_or_null
family_or_null
concept_or_null
market_overlay_or_null
trend_filter_or_null
relative_strength_filter_or_null
exit_rule_or_null
aggressiveness_or_null
execution_mode
effective_workers
seconds_total
seconds_data_load
seconds_feature_build
seconds_signal
seconds_simulation
seconds_train
seconds_validation
seconds_metrics
seconds_serialization
symbols_total
symbols_processed
raw_signals_total
trades_total
train_trades
validation_trades
scientific_fragments_produced
scientific_fragments_consumed
peak_rss_mb
result_status
reject_reason
error_code
timeout
early_rejected
runtime_error
scientific_result_digest_or_null
operational_attempt_digest
```

Exactly one scope branch is non-null. Candidate metadata is required only for
`canonical_unit`; a multi-candidate tile cannot invent one family or concept.
`seconds_*` are measured attempt timings and are never split proportionally
across candidates. `canonical_timing_summary.csv` has exactly one row per
canonical unit. Each row is the CSV projection of registered
`canonical_timing_attribution_v1` and records:

```text
schema_version
campaign_id
unit_id
canonical_strategy_id
ordered_operational_attempt_digests
ordered_tile_ids
fragment_reduction_manifest_digest_or_null
cpu_seconds_sum
critical_path_wall_seconds
seconds_data_load_attributed
seconds_feature_build_attributed
seconds_signal_attributed
seconds_simulation_attributed
seconds_train_attributed
seconds_validation_attributed
seconds_metrics_attributed
seconds_serialization_attributed
physical_tiles
scientific_fragments
technical_attempts
terminal_scientific_state
scientific_result_digest_or_null
canonical_timing_attribution_digest
```

Attribution follows the frozen execution DAG: shared tile work is charged once
to the tile and referenced, never divided or duplicated into candidate rows.
The canonical summary reports exact CPU sums and critical-path wall time; it
does not claim that shared phase wall time belongs exclusively to one strategy.
Its row count equals `total_canonical_units`.
`canonical_timing_attribution_digest` uses
`GTBI_CANONICAL_TIMING_ATTRIBUTION_V1`, `self_field` storage and omits only that
named digest field. The ordered attempt list contains every accepted
contributing attempt exactly once; the ordered tile list equals the execution
plan's complete tile set for that unit.

Allowed `result_status` values are:

```text
evaluated
early_rejected
physical_tile_completed
fragment_reduction_completed
timed_out
unsupported_approved
unsupported_unapproved
runtime_error
```

Dedupe is recorded in `canonical_map.csv` and `dedupe_map.csv` as identity
resolution, not fabricated as an evaluator attempt.
`physical_tile_completed` and `fragment_reduction_completed` are operational
success states only. Neither increments `canonical_units_evaluated` nor closes
scientific coverage without the resulting accepted canonical outcome.
The schema retains `early_rejected` for compatibility, but a V6-equivalent
72,000-pack campaign must contain zero rows with that status.

`recovery_task_registry.jsonl` always exists. It is empty when no attempt
ceiling was exhausted; otherwise each canonical JSON line contains the
conditional recovery task ID, unresolved-work/pair manifest digest, prior attempt
set digest, approval/deployment receipt digests, incremental budget, independent
sync receipt, recovery dispatch-capsule digest or null,
`capsule_created`, `capsule_consumed`, exact status and final evidence digest.
It also contains schema version, campaign ID, sequence, previous-event digest,
trusted UTC, actor/attestation and `event_digest` under
`GTBI_RECOVERY_TASK_EVENT_V1`, omitting only `event_digest`. Its hash chain and
task/capsule counts reconcile with summary fields. A consumed
capsule permits `succeeded|failed|dispatch_indeterminate`;
`expired|cancelled` requires `capsule_consumed=false`. An indeterminate row is
immutable terminal-security evidence. A later provider answer appends a linked
successor reconciliation event or task and never rewrites it.
`recovery_tasks_dispatch_indeterminate_unreconciled` counts only those rows
without a valid terminal successor. `_SUCCESS` requires that count to be zero;
otherwise only `_INCOMPLETE`, diagnostic `_PACKAGE_CLOSED` or the formal
abandoned-clean route is permitted.

`authority_generation_registry.jsonl` always exists and contains the immutable
initial authority generation plus every continuation generation. Each
hash-chained canonical line records generation ID/type, previous generation
digest, original envelope/capsule digests, remaining-manifest digest, unchanged
scientific/runtime identity-set digest, remaining ceilings, current security
snapshot and approval-set digests, destination sync/capsule digests,
created/valid/consumed times, terminal status and `generation_digest` under
`GTBI_AUTHORITY_GENERATION_EVENT_V1`, omitting only `generation_digest`.
Exactly one generation may be
current; a continuation with an expanded scope/ceiling or a broken predecessor
blocks package closure.

`external_security_operation_lease_registry.jsonl` always exists and has one
hash-chained row per requested lease, including denied requests. It records the
operation/target identity, authority generation, approved external-security
configuration/transition-policy digests, current signed observation digest and
receipt-set digests, oldest constituent completion, issue/expiry/consume
times, single-use CAS result, terminal sealed-or-compensated receipt and denial
reason. The row additionally binds schema version, campaign ID, sequence,
previous-event digest, expected CAS version, actor/attestation and
`event_digest` under `GTBI_EXTERNAL_SECURITY_OPERATION_LEASE_EVENT_V1`,
omitting only `event_digest`. Package closure requires every issued lease
consumed at most once and
terminal, no lease spanning two operations or targets, and no unexplained
partial privileged side effect.

Alias-expanded terminal schemas are:

```text
early_rejected_strategies.csv:
  strategy_id, canonical_strategy_id, stage, reason, split, year, actual,
  threshold, seconds_until_reject, symbols_processed, scientifically_safe

timeout_strategies.csv:
  strategy_id, canonical_strategy_id, final_work_identity_kind,
  final_work_identity_id, final_work_attempt_number,
  affected_candidate_symbol_pair_set_digest_or_null, timeout_seconds,
  last_stage, seconds_total, recovery_exhausted, technical_error_code

unsupported_strategies.csv:
  strategy_id, canonical_strategy_id, approval_status, reason_code,
  rule_path, detail_schema_version

runtime_errors.csv:
  strategy_id, canonical_strategy_id, final_work_identity_kind,
  final_work_identity_id, final_work_attempt_number,
  affected_candidate_symbol_pair_set_digest_or_null, error_code, stage,
  recovery_exhausted, sanitized_error_digest

missing_strategies.csv:
  strategy_id, canonical_strategy_id, expected_unit_id,
  unresolved_work_identities,
  missing_candidate_symbol_pair_set_digest_or_null, missing_reason,
  last_inventory_digest
```

Public copies may omit private descriptive columns only through the versioned
redaction schema; they retain campaign identity, counts and digests. The
complete private package always retains the frozen schemas above. Raw exception
messages and stack traces are private evidence and never appear in public CSV.

V6 compatibility outputs are governed by:

```text
v6_output_compatibility_manifest.json
output_migration_map.csv
```

The manifest is generated from the preserved V6 artifact and freezes relative
path, schema, row grain, sort order, required or optional status and V7
replacement. It covers at least:

```text
annual_trade_equity_curve.csv
bottom_100_trades_by_return.csv
compiled_signal_plan.csv
concept_precheck_diagnostics.csv
event_store_manifest.csv
exit_group_manifest.csv
long_hold_adjusted_holding_ge25.csv
long_hold_quality_leaderboard.csv
selected_symbol_trades.csv
signal_group_manifest.csv
slow_queue_manifest.csv
strategy_to_signal_map.csv
symbol_entry_counts_by_year.csv
ticker_trade_summary.csv
top_100_trades_by_return.csv
trade_return_distribution.csv
```

Legacy `final_summary.json`, canonical-detail paths and failure CSVs are either
emitted deterministically or mapped to a versioned replacement. No consumer
file disappears silently. `slow_deferred_strategies.csv` remains an empty
compatibility output because an approved V7 campaign permits no deferred
terminal units.

`_SUCCESS` is a canonical JSON completion record, not an empty marker. It is
written last, only after schemas, row equations, digests and the compatibility
manifest all pass. For this fixed 72,000-pack baseline it is forbidden unless:

```text
canonical_units_evaluated=3600
canonical_units_early_rejected=0
canonical_units_unsupported_approved=0
canonical_units_unsupported_unapproved=0
canonical_units_timed_out_unresolved=0
canonical_units_runtime_error_unresolved=0
canonical_units_missing=0
leaderboard_rows=72000
```

A diagnostic package with any unresolved, unsupported or early-rejected unit
may close only with canonical `_INCOMPLETE`, which records the same manifests
and category counts but is never accepted as a scientific result, never
published as final and cannot satisfy a gate. `_PACKAGE_CLOSED` may attest
transport closure only and carries no scientific-success meaning. `_SUCCESS`
includes:

```text
schema_version
campaign_id
code_sha
policy_hash
execution_tree_digest
execution_workflow_bundle_digest
scientific_manifest_digest
scientific_context_key_digest
exact_universe_identity_digest
observation_timestamp_state
execution_plan_digest
engine_result_digest
scientific_output_digest
summary_content_sha256
output_manifest_digest
expected_output_count
verified_output_count
canonical_units_terminal
original_strategies_terminal
completed_at_utc
```

`summary_content_sha256` is the lower-case SHA-256 of the exact canonical
`summary.json` bytes and must equal that member's `sha256` in
`output_manifest.json`; it is a `raw_bytes` digest reference with recorded byte
length, not a second parsed-summary hash domain.

The final completion equations are normative:

```text
canonical_units_terminal
  = cardinality(unique accepted canonical unit_id over every declared
    terminalization owner)
  = sum(terminal_unit_count over disjoint planned job/reduction owner nodes)
  = 3600

original_strategies_terminal
  = sum(alias_multiplicity for every terminal canonical unit_id)
  = 72000

canonical_units_terminal
  = summary.canonical_units_terminal
  = cardinality(distinct accepted unit_id after joining the authoritative
    assignment manifest to accepted scientific terminal outcomes)

original_strategies_terminal
  = summary.original_strategies_terminal
  = summary.total_strategies_evaluated
  = 72000
```

The execution plan, assignment manifests, reduction manifests and canonical map
carry the expected counts; job/reduction receipts carry their exact referenced,
owned, terminal and pair sets, not only scalar claims. Merge rejects missing,
extra, duplicate or conflicting unit IDs, pair sets or reduction nodes,
overlapping planned partitions, an alias mapped to more than one canonical
unit, a terminal outcome emitted by a non-owner, or any disagreement among
`_SUCCESS`, summary and decoded rows.
The broader category partition equations below remain useful for
`_INCOMPLETE`; they cannot relax the stricter `_SUCCESS` predicate.

`output_manifest.json` is canonical JSON and lists every required payload
relative path, schema identity, size, decoded row count for tabular/JSONL
outputs (otherwise null) and SHA-256, but excludes itself and all three
completion markers: `_SUCCESS`, `_INCOMPLETE` and `_PACKAGE_CLOSED`. It is
written and hashed after every payload passes validation. Its external
`output_manifest_digest` is
`HASH[GTBI_OUTPUT_MANIFEST_V1](typed output_manifest_v1 payload)`; the payload
contains no self-digest field. The one permitted
marker is then written last and points to that manifest digest, avoiding a hash
cycle. Restore and merge consumers accept scientific completion only when the
sole marker is `_SUCCESS`, the manifest, all payload digests and all
terminal-count equations agree. `_INCOMPLETE` and `_PACKAGE_CLOSED` are
diagnostic/transport evidence only and are rejected by every scientific,
ranking, gate and publication consumer.
`expected_output_count` and `verified_output_count` count those listed payloads
only; the manifest and completion marker are verified separately.

Every V6 output marked `emitted` in
`v6_output_compatibility_manifest.json` must appear in
`output_manifest.json`. A `replaced` output appears in
`output_migration_map.csv` with old/new schemas, consumer and migration test.
No required or emitted compatibility file may exist outside both inventories.

`engine_result_digest` is computed from registered
`engine_result_manifest_v1` before any equivalence decision:

```text
schema_version
scientific_context_key_digest
canonical_map_digest
ordered_engine_result_members[
  path, schema_version, row_count, logical_content_digest
]
selection_result[
  best_candidate_id,
  best_adjusted_return_time_risk,
  best_adjusted_return_time_risk_state,
  best_canonical_strategy_id,
  best_canonical_candidate_id,
  best_canonical_adjusted_return_time_risk,
  best_canonical_adjusted_return_time_risk_state,
  best_filtered_candidate_id,
  best_filtered_adjusted_return_time_risk,
  best_filtered_adjusted_return_time_risk_state,
  best_filtered_canonical_strategy_id,
  best_filtered_canonical_candidate_id,
  best_filtered_canonical_adjusted_return_time_risk,
  best_filtered_canonical_adjusted_return_time_risk_state,
  max_adjusted_candidate_id,
  max_adjusted_return_time_risk,
  max_adjusted_return_time_risk_state,
  max_adjusted_canonical_strategy_id,
  max_adjusted_canonical_candidate_id,
  max_canonical_adjusted_return_time_risk,
  max_canonical_adjusted_return_time_risk_state,
  canonical_units_passing_final_filters,
  original_strategy_ids_passing_final_filters,
  aliases_passing_final_filters
]
engine_result_digest
```

Its schema fixes the complete path set and order: every normalized scientific
result table, rule/trade table and V6-compatible scientific output that the
reference engine can produce is present exactly once. Operational diagnostics,
timestamps, hardware, costs, equivalence status, `engine_result_digest` and
`scientific_output_digest` are absent. It uses
`GTBI_ENGINE_RESULT_V1`, `self_field` storage and omits only its own digest.
Reference and optimized engine-result manifests must be byte-identical in
typed content before equivalence status is determined; comparing only their
scalar digests without restoring both objects is forbidden.

Every authoritative scientific manifest, `summary.json`, checkpoint,
reconstructed bundle, merge manifest and `_SUCCESS` repeats and verifies
`policy_hash`, `scientific_context_key_digest`,
`exact_universe_identity_digest` and `observation_timestamp_state`. A missing,
null, inconsistent or mutated value blocks reuse, merge and publication.

`scientific_output_digest =
HASH[gtbi-v7-scientific-output-v1](typed scientific_output_manifest payload)`
under the registered domain. The hashed typed payload explicitly omits its own
`scientific_output_digest` field. The stored manifest then carries the
computed value. The separate `scientific_output_manifest.json` lists only
normalized logical scientific outputs and intrinsic scientific summary/
selection fields: canonical and alias-expanded leaderboards, filtered
leaderboards, yearly performance, rule/trade result tables, canonical mapping
and deterministic best/max/passing selection. Every table is schema-typed,
sorted by its canonical key and hashed over decoded normalized values. It
excludes run/job/artifact IDs, timestamps, equivalence determination,
publication/restore/cleanup state, costs, timing, hardware, logs and transport
metadata. The separately hashed `equivalence_report.json` binds both compared
`engine_result_digest` values, their restored object comparison and the
resulting equivalence state. Two executions with identical science therefore
have the same `scientific_output_digest` even when their equivalence or
operational package identities differ. The output manifest still binds the
scientific manifest, equivalence report and every operational payload.

The durable result identity is exact and does not depend on archive container
bytes:

```text
success_record_digest =
  HASH[gtbi-v7-success-record-v1](typed _SUCCESS object)

durable_result_digest =
  HASH[gtbi-v7-durable-result-v1]({
    schema_version,
    campaign_id,
    output_manifest_digest,
    success_record_digest
  })
```

`HASH[domain]` is the section 16 registered-domain formula. The publication
receipt stores `output_manifest_digest`, `success_record_digest`,
`durable_result_digest`, `durable_result_identity` and every primary/mirror/
destination object version. Changing a listed payload changes the output
manifest; changing `_SUCCESS` changes its digest; reordering transport files
without changing typed objects changes neither. Reconstruction must recompute
all three before accepting the identity.

Exact row contracts:

```text
canonical_map_rows=total_strategies_mapped
canonical_leaderboard_rows=canonical_units_evaluated
canonical_filtered_leaderboard_rows=canonical_units_passing_final_filters
leaderboard_rows=aliases_expanded_to_leaderboard
filtered_leaderboard_rows=aliases_expanded_to_filtered_leaderboard
early_rejected_rows=aliases_expanded_to_early_rejected
timeout_rows=aliases_expanded_to_timeout
unsupported_rows=aliases_expanded_to_unsupported_approved+aliases_expanded_to_unsupported_unapproved
runtime_error_rows=aliases_expanded_to_runtime_error
missing_rows=aliases_expanded_to_missing
```

Definitions:

- `canonical_leaderboard.parquet` has one row per fully evaluated canonical
  economic hash.
- `canonical_filtered_leaderboard.parquet` has exactly the
  `final_filter_pass=true` row set from the canonical leaderboard, retains
  identical shared row digests and metrics, then applies its own frozen
  filtered ordering. “Projection” never means preserving the score-ranked
  source order.
- `leaderboard.csv` expands canonical results to every original strategy ID.
- An early-rejected canonical unit and its aliases do not appear in either
  leaderboard.
- A unit that completes all metrics but fails one or more final quality filters
  remains `evaluated` and appears in the unfiltered leaderboard; it is absent
  only from `filtered_leaderboard.csv`. Final-filter failure is never
  relabelled as early rejection.
- Every canonical and alias-expanded leaderboard row carries
  `final_filter_pass` plus `final_filter_vector_digest`, whose canonical payload
  contains every filter name, threshold, actual value, numeric state and
  decision in registry order.
- `filtered_candidates` and `passing_candidate_count` are legacy
  alias-expanded counts, never a count of distinct economic strategies.
  Reports lead with both the canonical and original-ID counts and never call
  alias rows independent discoveries.
- `canonical_map.csv` includes every loaded original strategy regardless of
  evaluation result, with frozen columns
  `source_position,strategy_id,candidate_id,canonical_strategy_id,unit_id,`
  `economic_hash,canonical_strategy_payload_digest,`
  `economic_payload_canonical_bytes_sha256,complete_reuse_key_digest,`
  `alias_ordinal,is_representative`. Rows are sorted by source position;
  aliases within a canonical group use the byte-order rule, and the rows must
  be the exact projection of registered `canonical_map_v1`.
- `dedupe_map.csv` has one row per original strategy and names its canonical
  unit, both source/economic payload digests and whether it is the
  representative.
- `timing_diagnostics.csv` has one row per accepted operational attempt across
  canonical, physical-tile and fragment-reduction scopes; it is not
  alias-expanded. `canonical_timing_summary.csv` has exactly one derived row
  per canonical unit and cannot fabricate per-candidate ownership of shared
  tile time.
- `yearly_trade_performance.csv` is alias-expanded for evaluated strategies and
  preserves the V6 row grain: one row per strategy, split and exit calendar
  year only when at least one closed trade is attributed to that group. It
  does not fabricate zero-trade rows. Final filters independently reindex
  every required train or validation year and treat an absent group as zero
  trades exactly as V6 does.
- Every loaded original strategy appears in exactly one of six alias-expanded
  terminal outputs: leaderboard, early rejected, timeout, unsupported, runtime
  error or `missing_strategies.csv`.
- A canonical unit with an unresolved missing result appears in coverage and
  failure reports but is not fabricated into a scientific row.
- `best_canonical_strategy_id` and `best_canonical_candidate_id` both come from
  the same canonical-leaderboard row and reconcile through the frozen
  one-to-one `strategy_id -> candidate_id` map.
- `leaderboard.csv` remains ordered by the V6-compatible
  `score DESC, candidate_id ASC`; `best_candidate_id` is exactly its first row,
  matching the Fast Strict V6 final merger.
- The canonical leaderboard uses `score DESC`, then canonical candidate ID and
  canonical strategy ID byte order. `best_canonical_strategy_id` and
  `best_canonical_candidate_id` come from exactly its first row.
- `best_adjusted_return_time_risk` is the adjusted metric of
  score-best `best_candidate_id`; it is not asserted to be the maximum.
- `max_adjusted_candidate_id` and `max_adjusted_return_time_risk` are separate
  diagnostics selected only among finite values by adjusted metric,
  validation median and candidate ID. The canonical equivalents use the same
  numeric keys followed by canonical candidate/strategy byte order.
- `best_filtered_candidate_id` is the first row after the frozen filtered
  ordering `adjusted_return_time_risk DESC, candidate_id ASC`, and
  `best_filtered_adjusted_return_time_risk` is its metric.
- `best_filtered_canonical_strategy_id` and
  `best_filtered_canonical_candidate_id` are the first canonical filtered row
  ordered by adjusted metric, canonical candidate ID and canonical strategy ID.
  Their adjusted metric and numeric state are reported separately.
- Empty canonical and expanded leaderboards require every unfiltered best ID
  and metric above to be null; every corresponding numeric state is `missing`.
- Evaluated rows may contain V6-defined non-finite scientific metrics. Their
  canonical semantic tokens and CSV representation are frozen; merge never
  converts them silently to zero or drops the row.
- Frozen output encoding is: typed Parquet `float64` preserves IEEE `+inf`,
  `-inf` and null/NaN under the schema's declared normalization; compatibility
  CSV writes exact ASCII `inf`, `-inf` and an empty field for missing/NaN with
  the frozen compatibility quoting rules and `\n`; strict canonical JSON forbids non-standard numeric
  literals and writes `null` plus the schema-declared companion state
  `finite`, `positive_infinity`, `negative_infinity` or `missing` wherever a
  non-finite scientific metric is representable. Digests are calculated only
  after this encoding and stable row/column ordering.
- Every candidate/strategy identifier must satisfy the frozen ASCII grammar.
  All ID ties are compared as unsigned UTF-8 bytes. For every numeric tie key,
  the ordering registry explicitly places `+inf`, finite values, `-inf` and
  missing/NaN; validation-median fallback treats missing/NaN as `-inf`.
- `filtered_leaderboard.csv` is exactly the projection, in frozen order, of
  leaderboard rows whose `final_filter_pass=true`. Its strategy-ID
  set, row digests and all shared metrics equal that projection; row-count
  inequality alone is not acceptance evidence.
- `best_filtered_candidate_id` and
  `best_filtered_adjusted_return_time_risk` are both null exactly when
  `filtered_leaderboard_rows=0`; otherwise the ID exists in
  `filtered_leaderboard.csv` and the metric equals that row. Its numeric state
  is `missing` when empty and otherwise equals the selected row's state.
- The four filtered-canonical best fields are null/missing exactly when
  `canonical_filtered_leaderboard_rows=0`; otherwise both IDs exist in the same
  canonical filtered row and reconcile through `canonical_map.csv`.
- `total_strategies_timed_out` and `total_strategies_runtime_error` count only
  unresolved terminal aliases. Recovered failed attempts are counted in
  `technical_attempts_timed_out` and `technical_attempts_runtime_error`, so
  successful recovery never erases operational evidence or corrupts terminal
  scientific accounting.

`summary.json` includes:

```text
total_strategies_requested
total_strategies_loaded
total_strategies_mapped
canonical_map_rows
github_only_run
requires_local_machine
optimized_evaluation_mode
evaluation_identity
selection_split
scoring_profile
min_selection_trades_per_year
score_formula_manifest_digest
final_filter_registry_digest
policy_hash
scientific_manifest_digest
scientific_context_key_digest
global_unit_reuse_key_set_digest
physical_data_layout_digest
physical_layout_mode
feature_demand_manifest_digest
cost_profile_digest
matrix_partition_manifest_digest
global_candidate_symbol_pair_set_digest
candidate_symbol_pairs_expected
candidate_symbol_pairs_accounted
total_physical_tiles
symbol_partition_count
scientific_fragments_expected
scientific_fragments_accounted
unresolved_scientific_fragments
exact_universe_identity_digest
observation_timestamp_state
reproducibility_classification
reuse_recovered_v6_inputs
oracle_b_status
semantic_oracle_coverage_manifest_digest
semantic_oracle_effective_branch_coverage_pct
semantic_oracle_non_equivalent_mutants_survived
v6_historical_reproduction_confirmed
synthetic_engine_equivalence_confirmed
engine_equivalence_confirmed
optimized_vs_reference_equivalence_confirmed
reference_engine_code_sha
reference_engine_tree_digest
reference_entrypoint_digest
reference_dependency_lock_digest
reference_runtime_digest
reference_engine_isolation_policy_digest
numerical_environment_digest
scientific_numerical_semantics_digest
approved_numerical_execution_profile_registry_digest
numerical_execution_profile_map_digest
numerical_execution_profile_map_rows
runtime_threadpool_observation_rows
runtime_threadpool_observations_compliant
runtime_threadpool_observations_noncompliant
approved_hardware_profile_registry_digest
observed_hardware_profile_map_digest
observed_hardware_profile_map_rows
missing_v6_dependency_layers
strategy_selection_evidence
validation_reused_for_selection
confirmatory_strategy_validity
multiple_testing_original_candidates
multiple_testing_canonical_candidates
total_canonical_units
canonical_units_accounted
original_strategies_accounted
canonical_units_terminal
original_strategies_terminal
canonical_units_evaluated
canonical_units_early_rejected
canonical_units_unsupported_approved
canonical_units_unsupported_unapproved
canonical_units_timed_out_unresolved
canonical_units_runtime_error_unresolved
canonical_units_missing
aliases_of_canonical_units_missing
aliases_resolved_by_dedupe
aliases_expanded_to_leaderboard
aliases_expanded_to_early_rejected
aliases_expanded_to_timeout
aliases_expanded_to_unsupported_approved
aliases_expanded_to_unsupported_unapproved
aliases_expanded_to_runtime_error
aliases_expanded_to_missing
canonical_leaderboard_rows
canonical_filtered_leaderboard_rows
canonical_units_passing_final_filters
original_strategy_ids_passing_final_filters
aliases_passing_final_filters
leaderboard_rows
canonical_yearly_trade_performance_rows
early_rejected_rows
timeout_rows
unsupported_approved_rows
unsupported_unapproved_rows
unsupported_rows
runtime_error_rows
missing_rows
yearly_trade_performance_rows
total_strategies_evaluated
total_strategies_early_rejected
total_strategies_timed_out
total_strategies_unsupported
total_strategies_runtime_error
total_strategies_missing
total_strategies_failed
technical_attempts_timed_out
technical_attempts_runtime_error
technical_attempts_duplicate_identical
technical_attempts_duplicate_conflicting
work_attempts_reserved
work_attempts_started
work_attempts_terminal
work_attempt_reservations_unused
work_attempts_succeeded
work_attempts_technical_failed
canonical_unit_attempts
physical_tile_attempts
fragment_reduction_attempts
accepted_operational_attempts
timing_diagnostics_rows
canonical_timing_summary_rows
authority_generations_created
authority_generations_consumed
continuation_authority_generations_created
continuation_authority_generations_consumed
active_authority_generation_id
active_authority_generation_digest
authority_generation_registry_rows
external_security_operation_leases_requested
external_security_operation_leases_issued
external_security_operation_leases_denied
external_security_operation_leases_consumed
external_security_operation_leases_expired_unused
external_security_operation_leases_terminal
external_security_operation_lease_registry_rows
recovery_tasks_created
recovery_tasks_terminal
recovery_tasks_succeeded
recovery_tasks_failed
recovery_tasks_dispatch_indeterminate
recovery_tasks_dispatch_indeterminate_unreconciled
recovery_tasks_expired
recovery_tasks_cancelled
recovery_dispatch_capsules_created
recovery_dispatch_capsules_consumed
recovery_task_registry_rows
filtered_leaderboard_rows
filtered_candidates
passing_candidate_count
campaign_run_registry_digest
campaign_run_registry_sealed_at_utc
campaign_workflow_runs_admitted
github_jobs_requested
github_jobs_completed
github_jobs_failed
github_jobs_success
github_jobs_conclusion_failure
github_jobs_cancelled
github_jobs_skipped
github_jobs_requested_status
github_jobs_queued
github_jobs_pending
github_jobs_waiting
github_jobs_in_progress
github_jobs_timed_out
github_jobs_stale
github_jobs_action_required
workflow_checks_startup_failure
github_jobs_neutral_unexpected
github_jobs_unknown_provider_value
github_job_status_rows
workflow_check_status_rows
scientific_jobs_requested
scientific_jobs_completed
scientific_jobs_failed
scientific_job_attempts_requested
scientific_job_attempts_completed
scientific_job_attempts_failed
preclosure_control_recovery_merge_jobs_requested
preclosure_control_recovery_merge_jobs_completed
preclosure_control_recovery_merge_jobs_failed
total_jobs_requested
total_jobs_completed
total_jobs_failed
candidate_count_per_job
candidate_count_per_job_is_uniform
candidate_timeout_seconds
candidate_timeout_semantics
work_item_timeout_seconds
package_integrity_pass
strict_final_pass
github_run_ids
canonical_units_per_job_min
canonical_units_per_job_mean
canonical_units_per_job_max
effective_workers_per_job
total_compute_slots
wall_seconds
runner_minutes
github_actions_acceptable_use_decision
pricing_snapshot_digest
budget_currency
reserved_total_cost_minor_units
observed_total_cost_minor_units
provider_billed_total_cost_minor_units
cost_reconciliation_state
mean_effective_cores_scientific
p95_memory_mib
historical_min_observation_date
historical_max_observation_date
rows_on_or_after_historical_exclusion_start
locked_rows_loaded
price_data_vintage_utc
source_event_cutoff_utc
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
corporate_action_knowledge_coverage_pct
historical_adjustment_vintage_contaminated
adjustment_point_in_time_claim_allowed
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
cross_market_temporal_contaminated
causal_cross_market_claim_allowed
universe_temporal_model
universe_temporal_manifest_digest
universe_temporal_coverage_pct
universe_point_in_time_claim_allowed
reference_index_order_confirmed
no_lookahead_confirmed
historical_causal_claim_allowed
survivorship_biased_reference
train_start_policy
train_end
validation_start
validation_end
locked_start
historical_exclusion_start
historical_post_validation_contaminated
pristine_locked
new_forward_available
first_market_session_locked
first_market_session_locked_by_market_digest_or_null
forward_lock_calendar_manifest_digest_or_null
later_required_approval_utc_or_null
validation_boundary_policy_digest
canonical_serialization_profile_digest
hash_domain_registry_digest
scientific_schema_set_digest
operational_schema_set_digest
code_sha
execution_tree_digest
execution_workflow_bundle_digest
data_digest
strategy_pack_digest
contract_digest
engine_result_digest
scientific_output_digest
execution_plan_digest
numerical_execution_profile_assignment_digest
best_candidate_id
best_canonical_strategy_id
best_canonical_candidate_id
best_canonical_adjusted_return_time_risk
best_canonical_adjusted_return_time_risk_state
best_filtered_canonical_strategy_id
best_filtered_canonical_candidate_id
max_adjusted_candidate_id
max_adjusted_canonical_strategy_id
max_adjusted_canonical_candidate_id
best_filtered_candidate_id
best_adjusted_return_time_risk
best_adjusted_return_time_risk_state
max_adjusted_return_time_risk
max_adjusted_return_time_risk_state
max_canonical_adjusted_return_time_risk
max_canonical_adjusted_return_time_risk_state
best_filtered_adjusted_return_time_risk
best_filtered_adjusted_return_time_risk_state
best_filtered_canonical_adjusted_return_time_risk
best_filtered_canonical_adjusted_return_time_risk_state
```

`package_integrity_pass` is the native V7 package-closure decision.
`strict_final_pass` is retained only as the V6 compatibility alias and must
equal `package_integrity_pass`; neither is a candidate-quality field.
Candidate quality is represented only by `final_filter_pass` on result rows
and by the canonical/alias passing counts. A package with zero passing
candidates may therefore have both package-integrity fields true. Conversely,
no candidate may be reported as passing merely because either package field is
true. The compatibility schema and known-answer fixtures enforce all four
truth-table combinations that are logically admissible and reject the
ambiguous inference.

Fixed identity values:

```text
github_only_run=true
requires_local_machine=false
optimized_evaluation_mode=gtbi_v7_performance_engine
evaluation_identity=v6_reference_equivalence
selection_split=validation
scoring_profile=strict_quality
min_selection_trades_per_year=100
universe_temporal_model=static_post_period
survivorship_biased_reference=true
universe_point_in_time_claim_allowed=false
no_lookahead_confirmed=false
historical_causal_claim_allowed=false
strategy_selection_evidence=exploratory
validation_reused_for_selection=true
confirmatory_strategy_validity=false
multiple_testing_original_candidates=72000
multiple_testing_canonical_candidates=3600
semantic_oracle_effective_branch_coverage_pct=100
semantic_oracle_non_equivalent_mutants_survived=0
github_actions_acceptable_use_decision=approved
locked_start=historical_exclusion_start=2021-01-01
historical_max_observation_date=2020-12-31
rows_on_or_after_historical_exclusion_start=0
locked_rows_loaded=0
historical_post_validation_contaminated=true
```

An accepted V7 result requires `engine_equivalence_confirmed=true`; incomplete,
failed or diagnostic packages set it to `false`. It never implies
`confirmatory_strategy_validity=true`.

`historical_max_observation_date`,
`rows_on_or_after_historical_exclusion_start` and `locked_rows_loaded` are
derived independently from the authenticated historical execution pack and
worker access log; they are not copied from dispatch inputs. They must reconcile
with the snapshot-integrity report, every worker manifest and the final
coverage report. Any observation or read at or after
`historical_exclusion_start` is a scientific-invalidity event, not a recoverable
worker failure.

`locked_start` is deprecated compatibility output only. Consumers must use the
explicit fields. `pristine_locked=false` implies
`first_market_session_locked=null`; `new_forward_available=true` requires an
authenticated forward-lock activation record, both required approval receipts
and a non-null per-market session map/calendar digest. Each market boundary
must open strictly after the later approval instant; the scalar first session
is only the minimum summary and cannot authorize another market.
`universe_temporal_model=static_post_period` requires
`survivorship_biased_reference=true`; `point_in_time` requires it to be false
and requires complete temporal-membership evidence.

Required accounting equations:

```text
total_strategies_requested = total_strategies_loaded = 72000
total_strategies_mapped = total_strategies_loaded
canonical_map_rows = total_strategies_mapped
total_canonical_units = multiple_testing_canonical_candidates = 3600
canonical_units_accounted = total_canonical_units = 3600
original_strategies_accounted = total_strategies_loaded = 72000
candidate_symbol_pairs_expected =
    total_canonical_units * symbol_partition_count
symbol_partition_count =
    count(ordered_symbol_partitions in execution_plan)
set(global_candidate_symbol_pair_set) =
    set(total_canonical_units) CartesianProduct
    set(ordered_symbol_partitions.symbol_partition_id)
candidate_symbol_pairs_accounted =
    count(distinct canonical_unit_id, symbol_partition_id
          in accepted scientific fragments)
candidate_symbol_pairs_expected = candidate_symbol_pairs_accounted
scientific_fragments_expected = candidate_symbol_pairs_expected
scientific_fragments_accounted = candidate_symbol_pairs_accounted
unresolved_scientific_fragments = 0
set(accepted_fragment_pair) = set(candidate_symbol_pair_set)
set(consumed_fragment_pair) = set(candidate_symbol_pair_set)
timing_diagnostics_rows = accepted_operational_attempts
work_attempts_reserved =
    work_attempts_started + work_attempt_reservations_unused
work_attempts_started =
    canonical_unit_attempts
    + physical_tile_attempts
    + fragment_reduction_attempts
work_attempts_terminal =
    work_attempts_succeeded + work_attempts_technical_failed
accepted_operational_attempts = work_attempts_terminal
work_attempts_terminal = work_attempts_started for _SUCCESS
canonical_timing_summary_rows = total_canonical_units
runtime_threadpool_observation_rows =
    numerical_execution_profile_map_rows =
    observed_hardware_profile_map_rows =
    count(planned_job_id in execution_plan)
runtime_threadpool_observations_compliant =
    runtime_threadpool_observation_rows
runtime_threadpool_observations_noncompliant = 0
total_canonical_units =
    canonical_units_evaluated
    + canonical_units_early_rejected
    + canonical_units_unsupported_approved
    + canonical_units_unsupported_unapproved
    + canonical_units_timed_out_unresolved
    + canonical_units_runtime_error_unresolved
    + canonical_units_missing
aliases_resolved_by_dedupe =
    total_strategies_mapped - total_canonical_units
aliases_resolved_by_dedupe = 68400
canonical_leaderboard_rows = canonical_units_evaluated
canonical_filtered_leaderboard_rows =
    canonical_units_passing_final_filters =
    count(canonical_leaderboard where final_filter_pass=true)
leaderboard_rows = aliases_expanded_to_leaderboard
early_rejected_rows = aliases_expanded_to_early_rejected
timeout_rows = aliases_expanded_to_timeout
unsupported_approved_rows = aliases_expanded_to_unsupported_approved
unsupported_unapproved_rows = aliases_expanded_to_unsupported_unapproved
unsupported_rows = unsupported_approved_rows + unsupported_unapproved_rows
runtime_error_rows = aliases_expanded_to_runtime_error
missing_rows = aliases_expanded_to_missing
total_strategies_evaluated = leaderboard_rows
total_strategies_early_rejected = early_rejected_rows
total_strategies_timed_out = timeout_rows
total_strategies_unsupported = unsupported_rows
total_strategies_runtime_error = runtime_error_rows
total_strategies_missing = missing_rows
total_strategies_failed =
    timeout_rows
    + unsupported_unapproved_rows
    + runtime_error_rows
    + missing_rows
total_strategies_loaded = original_strategies_accounted =
    leaderboard_rows
    + early_rejected_rows
    + timeout_rows
    + unsupported_rows
    + runtime_error_rows
    + missing_rows
original_strategies_accounted =
    total_strategies_evaluated
    + total_strategies_early_rejected
    + total_strategies_timed_out
    + total_strategies_unsupported
    + total_strategies_runtime_error
    + total_strategies_missing
missing_rows = aliases_of_canonical_units_missing
aliases_of_canonical_units_missing=0 when canonical_units_missing=0
original_strategy_ids_passing_final_filters = filtered_leaderboard_rows
aliases_passing_final_filters =
    original_strategy_ids_passing_final_filters
    - canonical_units_passing_final_filters
passing_candidate_count =
    filtered_candidates =
    original_strategy_ids_passing_final_filters
campaign_workflow_runs_admitted =
    count(distinct workflow_run_id in sealed campaign_run_registry)
set(distinct github_job_status.workflow_run_id) =
    set(workflow_run_id in sealed campaign_run_registry)
github_jobs_requested =
    scientific_job_attempts_requested
    + preclosure_control_recovery_merge_jobs_requested
github_jobs_completed =
    scientific_job_attempts_completed
    + preclosure_control_recovery_merge_jobs_completed
github_jobs_failed =
    scientific_job_attempts_failed
    + preclosure_control_recovery_merge_jobs_failed
github_jobs_completed =
    github_jobs_success
    + github_jobs_failed
    + github_jobs_cancelled
    + github_jobs_skipped
github_jobs_failed =
    github_jobs_conclusion_failure
    + github_jobs_timed_out
    + github_jobs_stale
    + github_jobs_action_required
    + github_jobs_neutral_unexpected
    + github_jobs_unknown_provider_value
github_jobs_requested =
    github_jobs_completed
    + github_jobs_requested_status
    + github_jobs_queued
    + github_jobs_pending
    + github_jobs_waiting
    + github_jobs_in_progress
github_job_status_rows = github_jobs_requested
workflow_check_status_rows = count(workflow_check_status.csv)
workflow_checks_startup_failure =
    count(workflow_check_status where normalized_failure_class=startup_failure)
package_closure_requires workflow_checks_startup_failure=0
total_jobs_requested = scientific_jobs_requested
total_jobs_completed = scientific_jobs_completed
total_jobs_failed = scientific_jobs_failed
scientific_jobs_requested =
    scientific_jobs_completed + scientific_jobs_failed
authority_generation_registry_rows = authority_generations_created
authority_generations_created =
    1 + continuation_authority_generations_created
authority_generations_consumed =
    1 + continuation_authority_generations_consumed
0 <= continuation_authority_generations_consumed
    <= continuation_authority_generations_created
active_authority_generation_id/digest =
    sole current consumed unexpired generation at package closure,
    otherwise null only when no new privileged operation is permitted
external_security_operation_lease_registry_rows =
    external_security_operation_leases_requested
external_security_operation_leases_requested =
    external_security_operation_leases_issued
    + external_security_operation_leases_denied
external_security_operation_leases_issued =
    external_security_operation_leases_consumed
    + external_security_operation_leases_expired_unused
external_security_operation_leases_issued =
    external_security_operation_leases_terminal
recovery_tasks_created =
    recovery_tasks_terminal
recovery_tasks_terminal =
    recovery_tasks_succeeded
    + recovery_tasks_failed
    + recovery_tasks_dispatch_indeterminate
    + recovery_tasks_expired
    + recovery_tasks_cancelled
recovery_dispatch_capsules_created =
    count(recovery_task_registry rows where capsule_created=true)
recovery_dispatch_capsules_consumed =
    count(recovery_task_registry rows where capsule_consumed=true)
recovery_dispatch_capsules_consumed =
    recovery_tasks_succeeded
    + recovery_tasks_failed
    + recovery_tasks_dispatch_indeterminate
0 <= recovery_dispatch_capsules_consumed <= recovery_dispatch_capsules_created
recovery_task_registry_rows = recovery_tasks_created
recovery_tasks_dispatch_indeterminate_unreconciled = 0 for _SUCCESS
candidate_timeout_semantics =
    legacy_candidate_major when physical_layout_mode=candidate_major
    otherwise not_applicable_physical_tiling
candidate_timeout_seconds =
    work_item_timeout_seconds when candidate_timeout_semantics=legacy_candidate_major
    otherwise null
candidate_count_per_job =
    canonical_units_per_job_min
    when canonical_units_per_job_min=canonical_units_per_job_max,
    otherwise null
candidate_count_per_job_is_uniform =
    canonical_units_per_job_min = canonical_units_per_job_max
filtered_leaderboard =
    exact_row_projection(
        leaderboard where final_filter_pass=true)
    ordered by adjusted_return_time_risk DESC, candidate_id ASC
filtered_leaderboard_rows =
    count(leaderboard where final_filter_pass=true)
filtered_leaderboard shared row digests and metrics =
    corresponding leaderboard row digests and metrics
canonical_filtered_leaderboard =
    exact_row_projection(
        canonical_leaderboard where final_filter_pass=true)
    ordered by adjusted_return_time_risk DESC,
               candidate_id ASC,
               canonical_strategy_id ASC
canonical_filtered_leaderboard shared row digests and metrics =
    corresponding canonical_leaderboard row digests and metrics
best_candidate_id = leaderboard[0].candidate_id
    when leaderboard_rows>0, otherwise null
best_canonical_strategy_id =
    canonical_leaderboard[0].canonical_strategy_id
    when canonical_leaderboard_rows>0, otherwise null
best_canonical_candidate_id =
    canonical_leaderboard[0].candidate_id
    when canonical_leaderboard_rows>0, otherwise null
count(canonical_map rows where
    strategy_id=best_canonical_strategy_id
    AND canonical_strategy_id=best_canonical_strategy_id) = 1
candidate_id of that unique row =
    best_canonical_candidate_id
max_adjusted_candidate_id =
    first_finite_row(
        leaderboard ordered by
        adjusted_return_time_risk DESC,
        validation_median_trade_return_pct DESC,
        candidate_id ASC).candidate_id
    or null when no finite adjusted value exists
max_adjusted_canonical_strategy_id,
max_adjusted_canonical_candidate_id =
    first_finite_row(
        canonical_leaderboard ordered by
        adjusted_return_time_risk DESC,
        validation_median_trade_return_pct DESC,
        candidate_id ASC,
        canonical_strategy_id ASC)
    or both null when no finite adjusted value exists
best_filtered_candidate_id =
    filtered_leaderboard[0].candidate_id
    when filtered_leaderboard_rows>0, otherwise null
best_filtered_canonical_strategy_id =
    canonical_filtered_leaderboard[0].canonical_strategy_id
    when canonical_filtered_leaderboard_rows>0, otherwise null
best_filtered_canonical_candidate_id =
    canonical_filtered_leaderboard[0].candidate_id
    when canonical_filtered_leaderboard_rows>0, otherwise null
count(canonical_map rows where
    strategy_id=best_filtered_canonical_strategy_id
    AND canonical_strategy_id=best_filtered_canonical_strategy_id) = 1
candidate_id of that unique row =
    best_filtered_canonical_candidate_id
best_adjusted_return_time_risk =
    finite_or_null(
        leaderboard[best_candidate_id].adjusted_return_time_risk)
    when best_candidate_id is not null, otherwise null
best_adjusted_return_time_risk_state =
    numeric_state(
        leaderboard[best_candidate_id].adjusted_return_time_risk)
    when best_candidate_id is not null, otherwise missing
best_canonical_adjusted_return_time_risk =
    finite_or_null(
        canonical_leaderboard[best_canonical_strategy_id]
            .adjusted_return_time_risk)
    when best_canonical_strategy_id is not null, otherwise null
best_canonical_adjusted_return_time_risk_state =
    numeric_state(
        canonical_leaderboard[best_canonical_strategy_id]
            .adjusted_return_time_risk)
    when best_canonical_strategy_id is not null, otherwise missing
max_adjusted_return_time_risk =
    finite_or_null(
        leaderboard[max_adjusted_candidate_id]
            .adjusted_return_time_risk)
    when max_adjusted_candidate_id is not null, otherwise null
max_adjusted_return_time_risk_state =
    numeric_state(
        leaderboard[max_adjusted_candidate_id]
            .adjusted_return_time_risk)
    when max_adjusted_candidate_id is not null, otherwise missing
max_canonical_adjusted_return_time_risk =
    finite_or_null(
        canonical_leaderboard[max_adjusted_canonical_strategy_id]
            .adjusted_return_time_risk)
    when max_adjusted_canonical_strategy_id is not null, otherwise null
max_canonical_adjusted_return_time_risk_state =
    numeric_state(
        canonical_leaderboard[max_adjusted_canonical_strategy_id]
            .adjusted_return_time_risk)
    when max_adjusted_canonical_strategy_id is not null, otherwise missing
best_filtered_adjusted_return_time_risk =
    finite_or_null(
        filtered_leaderboard[best_filtered_candidate_id]
            .adjusted_return_time_risk)
    when best_filtered_candidate_id is not null, otherwise null
best_filtered_adjusted_return_time_risk_state =
    numeric_state(
        filtered_leaderboard[best_filtered_candidate_id]
            .adjusted_return_time_risk)
    when best_filtered_candidate_id is not null, otherwise missing
best_filtered_canonical_adjusted_return_time_risk =
    finite_or_null(
        canonical_filtered_leaderboard[
            best_filtered_canonical_strategy_id]
            .adjusted_return_time_risk)
    when best_filtered_canonical_strategy_id is not null, otherwise null
best_filtered_canonical_adjusted_return_time_risk_state =
    numeric_state(
        canonical_filtered_leaderboard[
            best_filtered_canonical_strategy_id]
            .adjusted_return_time_risk)
    when best_filtered_canonical_strategy_id is not null, otherwise missing
yearly_trade_performance_rows =
    count(alias-expanded distinct
          (strategy_id, split, V6_attributed_exit_year)
          groups having at least one closed trade)
canonical_yearly_trade_performance_rows =
    count(canonical distinct
          (canonical_strategy_id, split, V6_attributed_exit_year)
          groups having at least one closed trade)
strict_final_pass = package_integrity_pass
package_integrity_pass = true only for a verified _SUCCESS package
package_integrity_pass does not imply
    canonical_units_passing_final_filters > 0
engine_equivalence_confirmed =
    optimized_vs_reference_equivalence_confirmed
github_only_run = true
requires_local_machine = false
```

`canonical_units_accounted` and `original_strategies_accounted` are inventory
fields and remain exact in `_INCOMPLETE`; they do not claim scientific success.
`canonical_units_terminal` and `original_strategies_terminal` are
success-only fields: they are non-null only in `_SUCCESS`, where the stricter
completion equations require `3600`, `72000` and every original strategy in
`leaderboard.csv`. They are null in `_INCOMPLETE` and `_PACKAGE_CLOSED`.
Timeout, unsupported, runtime-error or missing dispositions therefore reconcile
the accounted inventory but can never inflate a scientific-terminal count.

At accepted completion:

```text
github_jobs_queued=0
github_jobs_requested_status=0
github_jobs_pending=0
github_jobs_waiting=0
github_jobs_in_progress=0
```

Counts alone are insufficient. Merge joins every canonical outcome to the
frozen canonical map, requires exactly the declared sorted alias set and
cardinality for that `canonical_strategy_id`, and expands all aliases to the
same one of six partitions: evaluated, early rejected, unsupported, timed out,
runtime error or missing. A missing canonical unit therefore emits all of its
aliases in `missing_strategies.csv`; an alias in the wrong partition, in two
partitions or in none blocks completion even when aggregate totals happen to
match. Approved and unapproved unsupported aliases remain distinguishable.

Job counting is also frozen. `scientific_jobs_*` describes the unique original
worker-job identities in the immutable plan and backs the legacy
`total_jobs_*` fields. `scientific_job_attempts_*` counts every actual initial
or recovery GitHub worker job ID.
`preclosure_control_recovery_merge_jobs_*` counts every planner, checkpoint/
recovery controller and block/final merge job ID across the sealed admitted-run
set. `github_jobs_*` is their complete attempt-level
sum. The separate package-closer job and later independent result-validation, publication, restore, cleanup and
financial-tail jobs are counted in the external publication/operations
attestation chain, not inserted retrospectively into the package. Reruns never
rewrite an old job ID or disappear from cost/failure evidence.

For logical scientific jobs, `completed` means every assigned tile/work item
and candidate-symbol pair is durably accounted with
`job_bundle_state=complete`; it does not require every referenced canonical unit
to terminalize locally. `failed` means at least one assigned work identity or
pair remains unresolved after the recovery ceiling. Canonical-unit completion
is reconciled separately across its declared job/reduction terminalization
owners. A failed initial attempt later recovered increments attempt-level
failure counts but not terminal `scientific_jobs_failed`. Thus:

```text
scientific_jobs_requested =
    scientific_jobs_completed + scientific_jobs_failed
```

`total_strategies_failed` is a deprecated V6 transport-compatibility field.
It means unresolved non-scientific terminal aliases and must never be used as
a strategy-quality metric. Canonical scientific status remains separated into
evaluated, early rejected, unsupported, timed out, runtime error and missing.
Approved unsupported aliases are scientifically complete for a future manifest
that permits them and are excluded from this legacy failure aggregate;
unapproved unsupported aliases remain failures. New consumers use the explicit
fields and may not infer scientific failure from this legacy aggregate.

An approved campaign requires:

```text
canonical_units_evaluated=3600
canonical_units_early_rejected=0
canonical_leaderboard_rows=3600
aliases_expanded_to_leaderboard=72000
aliases_expanded_to_early_rejected=0
leaderboard_rows=72000
early_rejected_rows=0
total_strategies_evaluated=72000
total_strategies_early_rejected=0
canonical_units_unsupported_approved=0
canonical_units_unsupported_unapproved=0
canonical_units_timed_out_unresolved=0
canonical_units_runtime_error_unresolved=0
canonical_units_missing=0
technical_attempts_duplicate_conflicting=0
```

### G6A Acceptance

Gate G6A passes only when:

- optimized and reference engines are equivalent on the complete synthetic
  semantic oracle, with `synthetic_engine_equivalence_confirmed=true`;
- all optimizations can be disabled independently;
- the pre-plan selector only chooses validated modes;
- worker pools are persistent;
- effective CPU and memory are measured;
- every canonical unit has traceable identity;
- technical failures cannot become scientific outcomes;
- output schemas and counts are internally consistent.

G6A does not claim historical real-data equivalence because the authorized G7
repository and workload do not yet exist. `PREV7-0702` performs that proof on
the recovered historical execution pack; only then may
`optimized_vs_reference_equivalence_confirmed` and its compatibility alias
become true. G7 cannot green without that real proof.

Gate G6B passes only after `PREV7-0610` and `PREV7-0611` independently prove
their source and destination deadman, broker, lease-registry, monitoring,
restore and teardown paths with G3B already green. Passing G6A cannot imply
G6B, and no deadman deployment is admitted merely because implementation tests
passed.

## 18. Gate G7: CI, Tests And Smokes

All tests execute in GitHub.

### Required CI Jobs

```text
static
unit
scientific-contract
semantic-oracle
historical-golden
workflow-schema
security
package
performance-equivalence
```

Matrix policy:

- package and import tests run on the minimum supported Python and the exact
  canonical runtime Python;
- the scientific, equivalence and performance jobs run only in the pinned
  Linux runtime container;
- Windows verifies installation and non-scientific compatibility, never
  supplies canonical numerical evidence;
- tests do not use network after approved assets and wheels are staged;
- automatic test retries cannot turn a flaky first failure into a green
  required check.

Pre-existing failures are not a blanket waiver. Each exception requires an
issue, owner, exact failing-test fingerprint, reason, expiry date and proof
that it cannot affect GTBI. GTBI contract, locked-boundary, data-identity,
merge, recovery, packaging and security failures are never waivable.

### Mandatory Tests

Scientific:

- contract-manifest fixtures resolve every scientific dependency used by both
  engines, reject an unmanifested policy/module/schema member, and require a
  `contract_digest` change for every one-field date, signal, exit, fill, cost,
  metric, filter, score, tie-break, temporal or output-semantic mutation;
- source-identity fixtures generate the exact execution-tree and workflow-
  bundle manifests from a clean Git tree and built runtime, reject an
  imported/dispatched extra, omitted file, symlink, mode/blob/byte mismatch or
  mutable ref, and reproduce both registered digests independently;
- every identity proves `reference_index_order_confirmed=true`;
- only the separately named causal identity may prove
  `historical_causal_claim_allowed=true`; contaminated V6 reference equivalence
  must prove it false;
- next-session open;
- train ends on `2010-12-31`;
- boundary fixtures carry an open 2010 position and all indicator state into
  2011 without reset, attribute the cross-boundary trade by exit date, permit
  pre-2011 warm-up without counting it as validation and reject an independent
  validation restart;
- validation starts on `2011-01-01`;
- validation ends on `2020-12-31`;
- no locked reads;
- reproducibility-classification truth-table fixtures reject Oracle B/V6
  reproduction claims when original inputs are incomplete or a new snapshot is
  used, keep G5/G6A/G7/full red for this V7 in either case, and propagate the
  same classification fields through asset manifest, runbook core and summary;
- historical execution-pack schema and every partition have
  `max_observation_date<=2020-12-31`;
- snapshot integrity rejects duplicate instrument-dates, OHLC inconsistencies,
  negative volume, an unmanifested partition, wrong dtypes, a corporate-action
  mismatch and a currency series with the wrong lag;
- a split, dividend or provider revision learned after a decision session,
  including one learned later inside 2011-2020, cannot change that session's
  value in `as_known_each_session` mode; the same fixture is accepted
  only as `retrospectively_adjusted_reference` with
  `historical_adjustment_vintage_contaminated=true` and point-in-time claims
  disabled;
- strict point-in-time adjustment claims require 100% authenticated event-
  knowledge coverage; one unknown timestamp forces retrospective
  classification and `adjustment_point_in_time_claim_allowed=false`;
- cross-market fixtures prove Tokyo, London and New York decisions use only
  SPY/FX observations whose `available_at_utc<=decision_cutoff_utc`, including
  DST, half sessions, holidays and delayed publication; a same-date but later-
  available SPY close is rejected in causal mode;
- when Oracle B authenticates V6 calendar-date alignment, equivalence preserves
  those exact rows but requires `cross_market_temporal_contaminated=true` and
  `causal_cross_market_claim_allowed=false`; silently substituting an as-of
  join fails V6 equivalence and requires a new scientific identity;
- historical CLI rejects local execution, `--include-locked`, date overrides
  and any asset with post-2020 rows;
- entry and exit equality;
- trade equality;
- annual metric equality;
- exit-date split/year attribution, data-derived train-start policy, sparse
  yearly-row grain, fractional win rate, positive-infinity profit factor and
  SPY first/last-available-close return equality;
- train annualization fixtures distinguish the first eligible input session
  from the first parseable train exit, prove the no-train-exit
  `1900-01-01` fallback, and prove combined duration is exactly train duration
  plus validation duration;
- artificial pack-boundary and genuine symbol-end fixtures both preserve the
  V6 terminal-frame `end_of_data` exit, while a signal on the terminal bar
  cannot enter without a next session; fixtures prove last-bar-open pricing,
  invalid-open close fallback and same-bar entry close pricing; neither fixture
  reads a post-2020 bar;
- simulator-order fixtures prove stop-before-take behavior when both barriers
  are touched, high-water update before trailing-stop evaluation, the complete
  six-trigger priority, suppression of overlapping signals, permitted
  exit-bar-signal re-entry at the following open, zero commission/slippage and
  invariant outputs when only `adj_close` is perturbed;
- universe fixtures prove point-in-time membership, listing, delisting,
  eligibility and market-cap effective/availability timestamps against each
  decision cutoff or, for exact static V6 reproduction, force
  `survivorship_biased_reference` and reject stronger claims;
- shuffled instrument, partition, worker-completion and recovery orders preserve
  the exact non-gating prefilter diagnostics, complete-result digests and final
  filter decisions;
- filtered leaderboard is the exact final-filter projection of leaderboard,
  including identical shared row digests, metrics and verified
  `final_filter_vector_digest`;
- a fixture where twenty original aliases map to one passing economic hash
  reports `original_strategy_ids_passing_final_filters=20`,
  `canonical_units_passing_final_filters=1` and
  `aliases_passing_final_filters=19`, with one canonical filtered row and
  twenty alias-expanded filtered rows;
- filter-decision equality;
- ranking equality.
- selection-bias diagnostics reconcile exactly 3,600 canonical IDs, exclude
  aliases, bind method/candidate/data/contract/map/leaderboard digests, remain
  identical under input reordering and retain explicit
  `prior_search_history_complete=false` when prior searches are not fully
  authenticated.
- selection-bias `method_digest` excludes its own field, is stable under JSON
  object reordering and changes when any other frozen method field changes;
- canonical-serialization known-answer tests cover Unicode ordering and invalid
  surrogates, exact integer boundaries, binary64 shortest-round-trip values,
  negative zero, typed non-finite states, arrays and distinct hash domains;
- every scientific digest implementation matches the versioned RFC 8785
  profile and rejects unregistered domains or ambiguous number/string forms;
- schema-catalog tests classify every digest/hash/SHA field by the closed
  reference-kind union, resolve its schema/domain/issuer/chain/alias target and
  reject an untyped hex value, dangling target, algorithm ambiguity, circular
  alias or provider-native identity used for science;
- bootstrap tests identify the serialization profile and domain registry by
  exact known-answer input-byte hex and raw reviewed file-byte digests without
  circular dependency, record path/blob/tree identity separately, then reject
  a modified profile, registry self-digest, reused domain or asset manifest
  missing either bootstrap digest;
- reference and optimized engines have different frozen executable identities,
  run in separate processes, pass static import-graph and runtime
  module-inventory isolation checks, and produce equivalent signals, trades,
  annual metrics, filters and ranking on the same immutable fixtures;
- semantic-oracle coverage reconciles every effective primitive and branch used
  by all 720 signal bundles and five exit variants to hand-calculated boundary,
  missing, non-finite and default fixtures; coverage below 100% or any surviving
  non-equivalent frozen mutant blocks G5;
- a deliberately introduced optimized-module import in the reference tree
  fails CI, and comparing one executable path with itself cannot produce an
  accepted equivalence report;
- CI rejects any manifest, report or summary in which the historical
  `engine_equivalence_confirmed` alias differs from
  `optimized_vs_reference_equivalence_confirmed`; G6A requires only the
  separately named synthetic-equivalence field, while G7 requires both
  historical aliases to be true after `PREV7-0702`;

CI integrity:

- required checks report the tested commit SHA;
- task-state fixtures enumerate every legal obligation transition, reject
  terminal reopen and represent retries only as new immutable
  `task_attempt_id` records in `task_attempts.jsonl`, reconciled to
  `current_attempt_id` and `next_attempt_sequence`;
- readiness-schema fixtures validate exact field set/types/nullability and the
  single RFC 8785 canonical member ordering for
  task, gate, task-event, attempt, gate-event, branch and delivery records,
  canonical UTF-8/LF bytes and append-only event digests;
- task/gate atomicity fixtures reject a task event that consumes a different
  gate head or lacks the same state-controller transaction ID;
- task-readiness fixtures reject `ready` when owner actor, exact inputs, entry
  conditions, acceptance criteria, cancellation or rollback fields are absent,
  placeholders or not machine-verifiable;
- planning-schema fixtures require `task_definitions.csv` and
  `task_planning_inputs.csv` to carry identical participant roles, actors,
  availability-manifest digest and per-actor concurrency map for every task,
  and reject missing, extra, zero or stale participant coverage;
- conditional-branch fixtures require every prose alternative to resolve
  through the frozen registry, reject two selected successors, an unknown
  successor, stale predicate evidence or cancellation without the named
  alternative-completion receipt;
- local-administration fixtures make `0402..0407` terminate through distinct
  no-action receipts when the laptop is unavailable, prove no remote/scientific
  dependency exists and reject any claim that local deletion occurred;
- gate-graph fixtures prove
  `G1B -> G5 -> G6A -> G3B -> G6B -> G7` is acyclic, assign
  `0601..0609` only to G6A and `0610..0611` only to G6B, require the
  scientific-reviewer ownership/acceptance receipts for `0503`, `0505` and
  `0509`, and reject both the former circular unsplit-gate topology and any G5
  completion without G1B;
- abandonment-graph fixtures prove G9X is reachable after formal G7
  abandonment, requires completed current-generation G7 cleanup, and cannot
  green G8/G9/G10;
- bootstrap fixtures prove the two-PR genesis, provisional-event classification,
  dual-WORM migration/anchor and `PREV7-0009` actor/custody prerequisites; the
  pre-genesis fixture also creates the dedicated bootstrap App through the
  owner/JIT/witness ceremony, imports its key into the broker, proves exact
  `Actions: read` scope plus negative access, exercises only the registered
  write/read/restore/reversal escrow probes, and proves uninstall/key
  destruction/post-close denial;
- external-runtime fixtures admit only the registered deadmen, fixed-operation
  brokers, temporary bootstrap controller and destination cold verifier with
  exact identity/digest/operation/data/output contracts, and reject any
  scientific calculation or unregistered external runtime;
- wheel-install fixtures import `aurora.gtbi.reference_v6` and
  `aurora.infra.gtbi_deadman` and load every declared deadman deployment
  resource plus every GTBI contract/schema through `importlib.resources`
  without the source tree;
- V6 reference-image fixtures require the non-null preserved source entrypoint,
  command/argument schema and Python 3.12 lock/wheelhouse digests recovered from
  run `29162930823`, execute that path rather than V7 scientific modules, and
  reject a guessed path, reconstructed V6 subset, V7 lock or adapter-side
  scientific implementation;
- emergency-preservation workflow fixtures allow exactly the preserve and
  restore workflows, prove both closed preserve modes, and reject a third
  evidence-batch workflow or arbitrary path input;
- workflow schema tests require campaign concurrency at YAML root, reject a
  shared campaign-wide `jobs.*.concurrency` group and preserve matrix
  `max-parallel` semantics; full/control groups use current `queue: max`
  without `cancel-in-progress: true`, and two concurrent recovery/merge
  requests make the protected operation registry reject all but the one valid
  transition before GitHub enqueue;
- matrix planner fixtures cover job counts `0,1,255,256,257,359,360`, omit an
  empty B matrix, preserve exact requested job totals and distinguish
  `skipped_not_required` control status from missing science; every plan binds
  `matrix_partition_manifest_digest`, A/B sizes, A/B max-parallel and
  `matrix_b_present`;
- GitHub status fixtures preserve every raw status/conclusion, map requested/
  waiting/pending as nonterminal and timed_out/stale/action_required/
  unknown as recovery-required or terminal failure; startup failures without a
  GitHub job ID are preserved in the workflow/check-suite ledger and no
  provider value can vanish from accounting;
- campaign-state race fixtures reject simultaneous recovery and merge, merge
  before `READY_TO_MERGE`, a second initial dispatch and an invalid transition;
  sequential recovery and technical merge retry follow the exact CAS table;
  exhaustion enters `RECOVERY_AUTH_REQUIRED`, cannot dispatch there, and leaves
  it only through one-time consumption of a fresh recovery authorization and
  independently synchronized recovery capsule or an authorized terminal
  branch; initial attempts stop at three, recovery can reserve only the
  pre-funded fourth/fifth attempts, and a sixth attempt is impossible;
- recovery-authorization fixtures require five current, actor-independent
  scientific, workflow, acceptable-use, deployed-security and owner receipts
  bound to the unchanged runbook/workload, current terms/security observations,
  exact unresolved manifest and incremental budget; any missing, stale,
  repeated-actor or drifted receipt blocks capsule creation;
- G7/full controller fixtures use immutable child generations, enforce
  created/approval/consumption/running terminal states, forbid cancellation
  after consumption and reject receipt reuse between generations;
- continuation-authority fixtures expire the initial envelope during a
  multi-wave campaign, prove no privileged operation starts while authority is
  absent, consume one independently restored child capsule without a second
  initial dispatch, preserve every scientific/runtime/plan hash and ceiling,
  and reject added units, increased budget, changed assignment, replay or use
  as recovery after attempt exhaustion;
- capsule fixtures atomically bind consumption and post-dispatch state, treating
  ambiguous dispatch acknowledgement conservatively as post-dispatch;
- dispatch-reconciliation fixtures force an ambiguous API acknowledgement,
  require `consumed -> dispatch_reconciling`, find exactly one run by frozen
  idempotency key or prove bounded absence before `failed`, reject conflicting
  matches, forbid capsule reuse and apply the same protocol to G7, full and
  recovery generations;
- generated files and schemas are rebuilt and checked for a clean diff;
- every task has exactly one accountable `owner_role`; multi-party decisions
  use `required_approver_roles` plus a verified receipt-set digest, with
  `approved_by` null and incompatibility checks on actor IDs;
- role fixtures reject every forbidden same-domain pairing among owner/
  destructive authorizer, billing-payer authorizer, App manager, deadman
  operator, deadman deputy, key-broker custodian, break-glass custodian and
  every account-root custodian, App-custody organization owner and each indexed
  JIT approver; require exactly two distinct JIT approvers per custody domain
  and reject either one matching the other, the owner or the App manager;
  reject one actor as root custodian for separate broker/WORM/KMS failure
  domains, reject every cross-domain privileged pairing, prove the canonical
  role enum covers every task/receipt role exactly, and cover the collusion
  cases frozen in the threat-control matrix;
- no changed or newly failing test is hidden by the pre-existing-failure
  registry;
- acceptable-use fixtures reject denied/ambiguous/expired decisions, changed
  terms/workload/visibility/runner class and a required-but-missing Support
  response;
- monetary-budget fixtures use integer minor units, cover exact-boundary and
  one-unit-over cases for every category and total, and reject changed/unknown
  prices, currency conversion and unreserved tax or fees; source and
  destination approval sets cover every billing-domain row exactly once and
  reject a missing or duplicate row;
- retention-operations fixtures reject expired or unfunded durable storage,
  insufficient migration lead time, failed payment and stale restore evidence,
  and reconcile incident timing and accepted-byte/event boundaries for every
  RPO/RTO class; the maintenance workflow is read-only/default-deny and a
  missing quarterly receipt makes G2 stale;
- release-manifest fixtures require contiguous primary/mirror part arrays,
  exact part count/size/digests and equal reconstructed whole-payload SHA-256;
- total-GitHub-outage fixtures restore/decrypt/hash the platform-outage archive
  with the destination cold verifier inside RTO, prove its identity/image/
  configuration attestation, phase/network/key/plaintext separation and WORM
  receipt, prove zeroization, and reject exfiltration, replay, rollback, wrong
  workload identity, altered manifest and forged receipt; they also prove it
  cannot execute science or publish a scientific result;
- cost-reconciliation fixtures reject a rewritten event, missing predecessor,
  duplicate sequence, conflicting head and reservation release before a
  provider-backed `reconciled` head or pre-authorized
  `NO_INVOICE_EXPECTED_CLEAN` subtype; appending reconciliation evidence never
  changes the scientific result digest;
- append-only custody fixtures prove every event/head/anchor is provider-WORM,
  maximal administrators cannot overwrite/delete/purge/shorten retention,
  cross-domain and third-party timestamp anchors meet cadence, and a coherent
  replacement chain without the previously accepted anchor is rejected;
- accepted-event fixtures require both WORM copies and the independent anchor
  receipt before claiming zero-RPO acceptance;
- delayed-invoice and disputed-invoice fixtures export immutable provider
  statements, usage and dispute evidence, then retire every billable campaign
  repository/tenant/storage resource into `DISPUTED_CLEAN` without claiming
  financial or successful project completion; later reconciliation changes
  only the append-only cost ledger, while abandoned/no-go closure additionally
  requires its branch-limited terminal-exception receipt;
- resource-cleanup fixtures prove the runbook core contains only the schema
  digest plus `NOT_STARTED`, and that every later cleanup state derives from an
  external append-only CAS/hash chain rather than a rewritten core;
- checkpoint-batch fixtures validate one-record and twenty-record `records[]`
  objects, sorted record identities, all four discriminated-union variants,
  fragment child-count/byte limits, reduction-node ownership/closure, record
  count and full batch digest; record-identity fixtures freeze all four ASCII
  derivations, reject reserved separators/oversize components and prove the
  intended retry-collision and cross-campaign binding behavior;
- external-attempt lifecycle fixtures cover reservation, start, success,
  technical failure and unused reservation; reject start-after-unused,
  terminal-after-terminal, terminal-without-required evidence, stale CAS,
  wrong work identity/subset and any attempt-counter reset by split or rename;
- artifact-budget fixtures enforce the current `500`-artifact provider ceiling,
  the frozen reserve of `20`, at most `480` planned Actions artifacts per job,
  exact campaign-wide count/byte/storage equations and compression level zero
  for precompressed or encrypted payloads;
- checkpoint-RPO fixtures run all `360` planned scientific jobs concurrently,
  prove each planned-job chain has at most one unacknowledged microbatch and 20
  shared in-flight/unsealed/sealed exposure credits, delay acknowledgement
  while all four processes finish, forbid a second batch or new assignment,
  force-flush 1 through 19 final records, and bound aggregate exposure to
  `min(total_canonical_units, 360 * 20)=3,600` complete units in
  candidate-major mode or to
  `min(candidate_symbol_pairs_expected,
  360 * 20 * checkpoint_fragment_bundle_max_fragments)` candidate-symbol pairs
  plus the frozen aggregate byte cap in fragmented modes;
- checkpoint-deletion fixtures admit `RECONCILED_CLEAN` or bounded
  `DISPUTED_CLEAN` only after 30 days and dual restore, while preserving
  immutable dispute evidence and maximum liability;
- reverse-recovery fixtures prove one-use `PUT-if-absent` and disjoint `GET`
  capabilities are digest/object-version bound, never logged, and that no
  source App/token is installed on a destination repository and no destination
  credential enters the source domain;
- evidence-bundle fixtures require an eligible independent redaction-review
  actor and receipt bound to the exact public/private digests; threat-model and
  App-residual-risk fixtures require the separately registered independent
  security-review actor;
- final-security fixtures require a current `PREV7-0816` receipt for the exact
  runbook/deployed state, independently re-query external IAM, Apps, brokers,
  keys, lease registries, deadmen, WORM/KMS and monitors both at envelope
  creation and immediately before capsule CAS, invalidate on any drift, and
  reject reuse of the first query as the second receipt;
- OIDC fixtures enforce the frozen immutable/custom subject mode and
  owner/repository IDs, `uses_reusable_workflow`, exact or absent
  `job_workflow_ref`/`job_workflow_sha`, workflow/ref/SHA,
  repository/run/attempt, exact presence/value or absence of `environment`,
  direct signed-claim validation plus independent Jobs-API binding of
  `check_run_id`, nonce and `jti`;
- key-custody fixtures prove campaign recipient keys are generated natively in
  their brokers, App-key import follows the selected hardened branch and no
  campaign private key can traverse Actions;
- run-control fixtures prove normal then force cancellation of exact
  generation run IDs through either disjoint broker, reject arbitrary Actions
  calls and delay retirement until terminal jobs or token expiry;
- output-package fixtures require every emitted V6 file in expected/output
  inventories, every replaced file in the migration map, empty
  `slow_deferred_strategies.csv`, and reject
  `best_candidate_id` absent from `leaderboard.csv`,
  `total_strategies_evaluated` unequal to its rows, or an empty leaderboard
  with non-null best ID;
- package-close fixtures seal a CAS campaign-run registry containing multiple
  initial, continuation, recovery, compaction and merge run IDs, require complete
  paginated job/check-suite coverage for every admitted run and reject
  `_SUCCESS` when one admitted run/job is absent, nonterminal or added after the
  seal; workflow-inventory fixtures require registered
  `.github/workflows/gtbi-v7-package-close.yml` and its exact
  `PREV7-0608` task-delivery-manifest assignment;
- scientific-manifest fixtures require the complete role registry, contiguous
  repeated-role ordinals, repeated/top-level digest equality and independent
  restoration of every immutable asset; they reject a missing, extra,
  duplicate, mutable-locator-dependent or unresolved row;
- scientific-digest fixtures compute the registered `engine_result_manifest`
  before equivalence status, require exact typed member and selection-result
  equality between reference and optimized engines, and exclude
  `scientific_output_digest` from its own typed hash input;
- completion fixtures require `summary_content_sha256` to equal the exact
  output-manifest member bytes and reject a parsed-object digest, altered
  whitespace, encoding change or mismatched byte length;
- checkpoint/result fixtures prove operational run/job/time/telemetry changes
  alter only `operational_attempt_digest`, while any trade, metric, filter,
  context or reuse-key change alters `scientific_result_digest`; checkpoint
  records missing either context digest are rejected; discriminated-union
  fixtures require payload plus non-null scientific digest for a scientific
  outcome, require authenticated bundle/reduction payloads for their respective
  partial records, require every scientific payload field to be null for a
  technical attempt, and prove only the complete outcome can satisfy canonical
  scientific coverage; they restore every non-null
  operational preimage locator and reject an opaque, mutable, missing,
  size/schema-mismatched or digest-mismatched operational attempt;
- logical-payload fixtures freeze known-answer vectors for job, block and
  superblock domains, prove original and reconstructed bundles remain equal
  when only run/job/attempt/transport fields change, and reject any changed
  assignment, child, context, unit set or logical output member; they require
  exactly the five named job-level scientific logical members and the five
  named block/superblock scientific logical members, including tile, fragment
  and reduction evidence, and reject inclusion of checkpoints, diagnostics,
  telemetry, errors or operational manifests in a logical digest;
- data-identity fixtures independently mutate the execution-pack bytes, data
  manifest, partition membership/order/content, universe, alias/listing
  identity, vintage, temporal/adjustment/availability/calendar/currency policy
  and historical boundary, require `data_digest` to change, reject component
  digests as substitutes and prove the manifest/data-digest relationship is
  non-recursive; child-partition fixtures recompute every registered partition
  digest and the complete set from the parent rows, reject a changed/reordered/
  duplicated/missing child, unknown scheme, malformed bounds, overlapping or
  uncovered execution-pack row key and prove the child objects do not
  recursively redefine `data_digest`;
- exact-universe fixtures require contiguous frozen source ordinals, complete
  non-overlapping membership intervals, listing/alias identity and the
  temporal-mode-specific availability contract; they reject ticker
  normalization by convention, static membership presented as point-in-time,
  or any reordered, missing, duplicated or altered instrument/fact;
- feature-demand fixtures derive the registered manifest independently from
  all 3,600 canonical payloads, reject a missing, extra, duplicate, reordered
  or differently typed effective demand and mutate formula, parameter,
  lookback, lag, dtype, warm-up and temporal-availability fields one at a time;
- physical-layout fixtures authenticate every exact member byte, independently
  decode its row-key subset, require disjoint complete execution-pack coverage
  and byte-identical typed scientific content, and reject a path, projection,
  codec, dtype, missing-value, row count, row-key or decoded-content
  substitution;
- policy/universe provenance fixtures mutate `policy_hash`,
  `exact_universe_identity_digest` or `observation_timestamp_state` in each
  asset, snapshot, checkpoint, runbook, merge, summary and success schema and
  require end-to-end rejection;
- temporal-mode fixtures accept null/unknown-unverifiable availability only
  for a named static/retrospective reference with every causal claim false, and
  reject the same unknown timestamp under point-in-time/as-known/causal modes;
- forward-lock fixtures cover approval before open, during a session and after
  close across Tokyo, London and New York, holidays, half sessions and DST;
  they require the frozen calendar digest and per-market map, exclude every
  session whose open is not strictly after the later approval, and reject use
  of the scalar minimum as another market's boundary;
- all seven authorization/runbook/capsule domains have known-answer vectors,
  complete-field mutation coverage and self-digest exclusion tests;
- master-plan byte fixtures reject BOM, CRLF, missing/extra final newline,
  ineffective `.gitattributes` and any difference between the audited
  SHA-256/length/blob ID, the proposed PR Git blob and the merged `main` blob;
- task-remediation fixtures preserve terminal parent events, create only
  monotonic controller-owned children, keep affected gates red until the
  latest child passes and reject concurrent/arbitrary successors;
- branch-registry fixtures enumerate every conditional task, require a distinct
  non-circular substitution row/receipt for each cancelled task, include
  `PREV7-0816`, reject `ABANDONED_CLEAN` as a task-level substitute and prove
  `PREV7-0913` starts only after all selected-branch prerequisites reconcile;
  pre-dispatch abandonment completes the no-recovery branch of `PREV7-0914`
  with no-capsule/no-ciphertext evidence, while post-dispatch runs only its
  recovery branch, and neither branch uses a task's own output to cancel itself;
- G7-generation fixtures change `current_G7_attempt_generation` after a green
  attempt, require the new generation's own success/closed-dispatch/
  zero-nonterminal/cleanup tuple and reject reuse of any earlier cleanup child;
- G8 transaction fixtures complete `PREV7-0804`, build preauthorization with
  every G8 predicate except `PREV7-0807`, bind envelope plus capsule to it,
  permit only the `PREV7-0807` sync/capsule evidence delta in the final green
  event and reject any self-reference or intervening drift;
- G9 expiry fixtures consume an exact green G8 attempt, expire initial authority
  during the retention window and still permit preservation under its consumed
  receipt while denying all new privileged work without continuation;
- dispatch-indeterminate fixtures force provider/API ambiguity through the
  bounded deadline, require terminal-security denial plus post-dispatch
  preservation, reconcile its dedicated task/capsule counters, forbid
  `_SUCCESS` while it is unresolved, and forbid cleanup/retry until a successor
  reconciliation or abandoned-clean route exists;
- G7 failure fixtures require `abandoned -> failed_abandoned_clean` only after
  both-domain cleanup and prove that it can reach G9X but never G7/G8/G9/G10;
- cleanup fixtures interrupt every `PREV7-0905` substep and prove idempotent
  resume, run source/destination physical cleanup independently under one-
  domain outage, and let only `PREV7-0913` reconcile both receipts;
- NO-GO fixtures fail a closure generation at each phase and require exactly
  one successor with union inventory and no orphan resource or liability;
- owner/key succession fixtures cover total owner loss, custodian loss,
  conflicting successors, witness separation and the prohibition on science,
  budget expansion, opposite-domain action or last-key destruction;
- private-evidence fixtures prove tmpfs/locked-memory-only intake, disabled
  swap/core/logging, zeroization/unmount and destruction receipts on success,
  error, cancellation and simulated host loss; public G0 receipts reject every
  provider/repository/run/artifact identifier;
- CODEOWNERS coverage fixtures classify every protected path exactly once,
  reject a newly added unclassified path and compare generated routing with the
  normative ownership table;
- financial fixtures accept `NO_INVOICE_EXPECTED_CLEAN` only when that
  settlement model was frozen before dispatch and all lag/usage/zero-or-bounded
  charge/payer/WORM predicates hold; they reject retrospective selection and
  keep normal completion red for an expected but missing invoice;
- capsule-retention fixtures prove abandonment CAS-revokes rather than deletes
  capsule records and retains their WORM tombstones while secret-key
  destruction follows a separate manifest;
- final-project fixtures evaluate every G10 predicate except the not-yet-
  emitted `PREV7-1003` receipt, then atomically append task/terminal/gate events
  and reject any self-satisfying or partially appended transaction;
- critical and high security findings are zero before G7.

Performance:

- one, two and four workers produce identical canonical outputs;
- oversubscription fixtures preload each supported OpenMP, BLAS, BLIS, MKL,
  NumExpr, Numba, PyArrow, Polars or Rayon-backed executor, verify dynamic
  threading is disabled where applicable, enforce the frozen process/thread
  ceiling before science starts and fail an unregistered or unbounded native
  pool;
- runtime thread-pool fixtures prove that approved profiles contain only
  pre-dispatch declarations, emit a complete typed observation for every
  registered phase/process after imports, reject path/PID/time-dependent
  identity, and fail a missing library, hidden executor, excess thread,
  noncompliant observation or profile-map mismatch;
- every job, checkpoint, reconstructed bundle and merge receipt carries the
  frozen `scientific_numerical_semantics_digest` and equal compatibility alias
  `numerical_environment_digest`; a one-field Python, NumPy, Pandas, SciPy,
  loaded-BLAS-library, dtype, reduction, seed, locale, timezone, platform/ISA
  or equivalence-policy difference rejects reuse and merge;
- one-, two- and four-worker fixtures use distinct registered
  `numerical_execution_profile_digest` values, prove byte-identical scientific
  results, and merge only when the immutable execution plan or an approved
  substitution receipt assigns those profiles; changing an execution profile
  without changing the registry and assignment is rejected rather than treated
  as a new scientific context;
- recovery fixtures switch from each approved Mode A/B/C profile to every
  other applicable approved profile, preserve checkpoint scientific identity,
  emit the new operational-attempt profile, and accept only a byte-identical
  `scientific_result_digest`;
- different physical CPU models emit different `observed_hardware_digest`
  values but may merge only when both are in the frozen hardware registry and a
  byte-identical equivalence fixture passed; changing scientific numerical
  semantics always rejects reuse;
- cache on and off are equivalent;
- FeatureStore refuses reuse after any data, formula, cutoff, contract, code,
  dependency lock, runtime container, scientific numerical semantics,
  approved-execution-profile registry, serialization profile or hash-domain
  registry change; changing only the approved per-job profile assignment
  cannot alter a FeatureStore payload and is tested for byte equivalence;
- two concurrent builders for the same FeatureStore key publish one identical
  closed object, never expose staging bytes to a reader and reject a conflicting
  payload instead of selecting a winner;
- crash fixtures interrupt FeatureStore publication before payload close,
  before manifest close, before atomic rename and before catalog commit; readers
  accept none of those partial states, recovery removes only lease-expired
  staging data and deterministic recomputation produces the reference object;
- corrupt-length, corrupt-digest, stale-catalog-generation and premature-
  eviction fixtures quarantine or ignore the entry and recompute, while an
  active campaign prevents retention cleanup of every referenced closed object;
- changing only universe/adjustment/decision-time/availability/cross-market/
  calendar/currency temporal policy invalidates FeatureStore, unit, checkpoint,
  reconstruction and final reuse even when price bytes are unchanged;
- every candidate physical data layout decodes to the same typed-array,
  missing-value, index and scientific-output digests as the reference layout;
- candidate-major, symbol-major and hybrid physical evaluation fixtures cover
  the same exhaustive candidate-symbol pair set exactly once, reconstruct the
  same V6 symbol/trade order, trades, annual rows, sequence drawdown, rankings
  and scientific-output digest, while reporting their different transfer,
  serialization and merge costs;
- fragment fixtures reject an omitted/duplicated/overlapping/misrouted pair,
  a tile subset not equal to its unit-partition Cartesian product, a bundle
  subset not equal to its child-fragment pairs, a subset with the wrong global
  parent,
  an altered fragment under an unchanged logical payload, premature candidate
  terminalization, reduction at a non-designated node and a final package with
  any unresolved fragment; an interrupted block forwards authenticated
  fragments without losing their scientific identity;
- global-pair fixtures independently form the Cartesian product of all
  canonical units and declared symbol partitions, require its typed set digest
  and count to equal the execution plan and reject a scalar-only, sparse,
  foreign or physically reordered replacement;
- data-identity fixtures recompute `data_manifest_digest` and `data_digest`
  through their distinct registered domains, require the snapshot partition and
  scientific-identity fields to equal the exact data-manifest projection, and
  independently stream the exact execution-pack framing in deliberately
  shuffled filesystem order; they reject a changed partition or raw byte,
  duplicate/absolute/traversal/NFD path, symlink, false encoded length,
  unmanifested or trailing byte, changed universe or temporal policy,
  self-digest recursion or untyped digest reference;
- archive-wrapper fixtures recompute `asset_manifest_digest`, require the
  schema to remain in the transport subset, reject any true result claim
  without its authenticated evidence and prove that appending a later restore
  receipt never mutates the sealed V6 wrapper;
- a four-process fixture proves each job-local input is downloaded,
  authenticated and decompressed once rather than once per worker;
- process-start fixtures enforce explicit `spawn`, reject direct `fork` and
  `forkserver`, and prove that no credential, unexpected file descriptor,
  environment secret or writable parent state reaches a child;
- profile-guided A/B records cover the complete representative feature/signal/
  exit/cost buckets, redact scientific payloads and reject a microbenchmark win
  that slows cold end-to-end final-artifact delivery;
- execution-plan fixtures prove contiguous unit, symbol-partition and tile
  ordinals, exact one-time
  unit/symbol-partition/tile/job/matrix/block/superblock coverage, disjoint
  complete historical-source-ordinal coverage by symbol partitions, exact
  input-partition closure, equality with the numerical-profile assignment set
  and invariant plan digest under shuffled source or completion order;
- cost-profile fixtures preserve completed, failed and censored observations,
  deterministically cover unseen keys through the frozen fallback and prove
  that changing a source, estimator, confidence state, estimate or fallback
  changes scheduling identity without changing any scientific candidate;
- matrix-partition fixtures independently derive A/B rows from every accepted
  execution plan, enforce the `0..360` equations, omit B only when empty and
  reject a duplicate, missing, foreign, reordered or inconsistently assigned
  planned job or tile;
- dedupe canonical and expanded outputs are traceable;
- complete-result reuse fixtures prove equal `economic_hash` values with
  different context, seed or complete scientific symbol set do not reuse,
  repartitioning the identical ordered symbol set leaves the complete key and
  result unchanged, while equal
  `complete_reuse_key_digest` values reuse exactly one canonical evaluation and
  expand all aliases deterministically;
- symbol-eligibility fixtures reconstruct every per-unit interval from frozen
  data and policy, require contiguous historical source ordinals and complete
  non-overlapping session coverage, preserve exact V6 symbol/trade ordering
  across every physical layout, and reject a changed identity, source ordinal,
  interval boundary, state, reason or lexically resorted ticker list;
- strategy-pack fixtures require exactly 72,000 restored source records, reject
  empty or duplicate strategy/candidate IDs, a non-bijective map,
  nondeterministic/gapped source positions, a payload/source-byte mismatch or
  disagreement among either registered ID set, the bijection and pack rows;
  the subsequent economic-dedupe fixture rejects any count other than 3,600
  canonical groups, 720 signal bundles or five exit variants per signal bundle;
- shuffled input, shard and completion orders produce the same representative,
  byte-sorted alias list, `unit_id`, registered canonical-map object and best
  IDs; map fixtures reject a changed source payload digest, economic canonical
  bytes, complete-reuse key, representative flag, alias ordinal or CSV row
  projection;
- a changed effective seed, policy hash, dependency lock, runtime container or
  scientific numerical semantics cannot reuse a checkpoint or complete result;
  an execution-profile-only change is accepted solely through the frozen
  approved registry, plan assignment or substitution receipt and exact
  scientific-result equivalence;
- diagnostic-prefilter on and off produce byte-identical complete outputs and
  never emit a terminal early rejection;
- the preserved V6 baseline fixture requires `3,600` canonical evaluated units,
  `72,000` unfiltered leaderboard rows and zero canonical or alias-expanded
  early-rejection rows;
- when recovered V6 inputs make Oracle B available, the historical golden also
  requires `1,947,000` alias-expanded yearly rows, `87,150` canonical yearly
  rows, zero canonical and alias-expanded filtered rows,
  `best_candidate_id=lhv1_0405081ff8_fam_43_v1006` and legacy
  `best_adjusted_return_time_risk=0.0005410569585308`; that best row has
  `score=-1043458.3756854916`, and an exact strict-score fixture reproduces it
  from the instrumented pre-score binary64 bit patterns for its five failures,
  annual counts, minimum trades, median and PF rather than from the overwritten
  generic score or rounded compatibility CSV components;
- a complete V6 CSV diagnostic proves `10,450/72,000` alias rows can differ by
  one ULP when score is recomputed from their serialized decimal components,
  maximum absolute difference is `2.3283064365386963e-10`, and both the full
  stable ordering and best row remain identical; it never weakens the exact
  direct reference-output comparison;
- ranking fixtures freeze Pandas mergesort stability, descending/ascending key
  directions and `na_position="last"` independently for unfiltered and filtered
  leaderboards, including tied IDs, NaN, positive infinity and negative
  infinity;
- compatibility fixtures prove the V6 artifact's
  `strict_final_pass=true` together with zero filtered rows, map that field
  only to `package_integrity_pass`, and reject every parser or report that
  interprets it as a candidate passing the final filters;
- safe-boundary fixtures cover `99/100` annual trades, `1499/1500` total
  validation trades, profit factor exactly `1.05`, average exactly zero and
  the last possible seventh positive-median year; exact zero passes the
  non-negative train-minimum check but still fails the separate eight-positive-
  train-years requirement;
- a missing required year produces no compatibility CSV row but is reindexed
  to zero trades by the filter and fails exactly as V6;
- historical-boundary fixtures include a final allowed observation on
  `2020-12-31`, reject an observation on `2021-01-01`, and prove that final
  `historical_max_observation_date`, `rows_on_or_after_historical_exclusion_start`
  and `locked_rows_loaded` equal the independently scanned manifests and access
  logs rather than requested input values;
- temporal-classification fixtures allow post-2020 operational provenance
  timestamps but prove they cannot enter any scientific value, while same-date
  universe/listing/delisting/eligibility/market-cap facts published after a
  decision cutoff are unavailable;
- causal-claim truth-table fixtures force
  `historical_causal_claim_allowed=false` for every single false, missing or
  unknown conjunct and prove a contaminated V6 reference can pass exact
  equivalence while never passing the causal claim;
- every scientific worker fixture proves its mounted historical pack has
  `rows_on_or_after_2021_01_01=0`, and a deliberately injected post-boundary
  partition blocks merge even when no strategy reads that partition;
- event-first agrees with reference;
- hand-calculated fixtures cover every V6 score component, weight, clipping,
  missing/non-finite default and final tie order;
- recovery agrees with uninterrupted execution;
- checkpoint compaction reconstructs the same logical job-result payload digest
  when the original Actions artifact is missing or expired;
- checkpoint-compaction fixtures prove `gtbi-checkpoint-compact` has the private
  one-use broker data key but no publication/network capability,
  `gtbi-checkpoint-publish` has the write identity but no private key, the
  content-addressed handoff store accepts exactly one digest-bound `PUT` only
  after the decrypting container terminates and later permits only the matching
  publisher `GET`, and no job, environment, runner, writable path or actor
  session ever combines decryption with checkpoint-namespace publication;
- the destination replicator App is installed only on the disposable campaign
  transport repository, has repository-level `actions:read` and no write
  permission, rejects every run/workflow/prefix/digest outside the frozen
  allowlist, emits a complete chained receipt set, and its installation is
  suspended only by the destination-owned lease reaper on completion, failure
  or expiry; a source reaper cannot mint its token;
- source and destination fixtures independently restore the same plaintext
  digest from their own wrapped data-key envelope; neither private key can
  unwrap the other labelled envelope and no private key reaches a worker;
- platform-outage fixtures reconstruct the exact dependency and final-result
  digests from destination-owned non-GitHub object-lock storage while all
  GitHub asset/package/release reads are denied, prove compliance mode and the
  frozen retention/hold state, and prove both source identities and a maximal
  destination storage administrator cannot delete, overwrite, purge versions,
  remove the lock or shorten retention; when customer-managed SSE/KMS is used,
  a distinct maximal key administrator cannot disable/delete/schedule deletion
  or shorten key retention, and rotation restores through both key versions;
  provider-managed encryption fixtures instead prove the exact retained-object
  survivability/restore contract, while unknown account-closure or revocation
  semantics fail closed;
- archival-key rotation fixtures rewrap the unchanged result data key, restore
  the complete canonical result from both custody domains before retiring the
  old key, and reject destruction that would leave fewer than two independently
  controlled live recipients while the result is retained;
- force-cancel fixtures skip every in-run finalizer yet independently scheduled
  source and destination reapers suspend only their own Apps, remove only their
  lease-generation-bound ephemeral state, restore source deny-all and emit
  linked reconciled cleanup receipts inside the frozen SLA;
- G7 cleanup fixtures fail before `PREV7-0708` and still execute
  `PREV7-0714`, revoke every started validation resource and preserve the
  failure evidence without falsely greening G7;
- G7 task-controller fixtures prove completed `PREV7-0713` dependencies alone
  cannot activate `PREV7-0714`; only the machine-evaluated condition that all
  actually started G7 operations are terminal or formal G7 abandonment can do
  so;
- G7 disposition fixtures require distinct matching source/destination
  abandonment receipts, keep a unilateral/mismatched case in
  `abandonment_pending_remote`, automatically move both `pending` and that
  intent state to `security_abandoned_pending_remote` at the trusted deadline,
  forbid completion/new dispatch/reactivation from either pending-remote state,
  preserve local fail-safe cleanup without greening a gate, permit only
  dual-receipt transition to `abandoned`, and reject every transition out of
  `completed|abandoned`;
- G7 rerun fixtures close `G7_ATTEMPT-n`, reject reopening or reuse of its
  receipts/keys/leases/reservation, then admit `G7_ATTEMPT-n+1` only after fresh
  authorization, provider state, budget and generation-bound cleanup;
- cancellation before the first scientific job still causes each reachable
  sovereign lease registry or deadman to create its own irreversible local CAS
  terminal manifest; duplicate, conflicting and old-generation local attempts
  fail, either domain cleans while the other is unavailable, and the read-only
  joint reconciler later binds both local manifests without cleanup authority;
- trusted-time fixtures cover forward jump, backward jump, rollback, stale or
  unavailable local source and wall/monotonic divergence; activation and
  renewal fail closed beyond the frozen local-source skew, while monotonic
  expiry cleanup still proceeds. A completely isolated or disagreeing remote
  custody clock is reconciliation evidence only and cannot block local cleanup;
- trusted-time restart fixtures cover process restart, host reboot with changed
  `boot_id`, suspend/resume, hibernation, VM clone/snapshot restore, restored
  older registry snapshot and loss of suspend-inclusive monotonic continuity;
  when fresh authenticated time is unavailable they expire/suspend rather than
  renew or extend any lease;
- external-deadman fixtures verify reproducible digest-pinned deployment,
  minimum IAM, sign-only broker, per-domain HMAC secret-manager custody,
  constant-time raw-body verification, overlap rotation and incident fallback,
  authenticated anti-replay webhooks, polling fallback, deny-by-default egress
  allowlist that rejects wildcard DNS, redirects, literal IPs, IPv6, proxies
  and metadata endpoints, immutable logs, cold restore, registry/broker
  failover, separate source/destination failure domains, hard billing caps and
  complete campaign-tenant retirement without deleting retained evidence;
- lease fixtures reject a replayed or stale heartbeat, an old generation
  cleanup, a finalizer/reaper race and reactivation during cleanup unless the
  compare-and-swap transition owns the current generation;
- environment-controller fixtures prove that secret deletion uses only the
  secret-controller App, deployment-policy restoration uses only the separate
  one-repository `Administration: write` App, and both reject every non-
  allowlisted endpoint, repository or lease generation;
- review-environment fixtures require concrete protected
  `gtbi-acceptable-use-review` and `gtbi-security-review` instances on the
  canonical source repository, their exclusive registered reviewer roles and
  deployment IDs, and prove both environments lack campaign-dispatch,
  scientific-data, decrypt and publishing credentials;
- recovery-key isolation fixtures prove checkpoint, merge and final-result
  recipient keys exist only in external non-exportable OIDC brokers and the
  environment secret-controller cannot create, replace, read or delete them;
- `RECIPIENT_KEY_DOMAIN_LOSS` fixtures destroy the synthetic source recipient
  domain, recover only from the independent destination envelope, rewrap to a
  new source key under dual approval, restore identical plaintext and prove the
  recovery-only path cannot evaluate, merge, rank, publish or access any
  unmanifested object; simultaneous loss of both domains must fail closed;
- private-key inventory/lint fixtures reject any App, checkpoint, merge or
  result-recipient private key in a GitHub environment, repository/organization
  secret, workflow, job, artifact, log or ordinary filesystem;
- evidence-intake fixtures scan public and private plaintext before immutable
  storage and again on restore, detect PEM/tokens/signed URLs/embedded and
  project-specific secrets, and require rotation/revocation or reviewed
  false-positive receipts bound to exact evidence digest/rule/finding/byte
  range with zero open alerts before G8; repository-closure fixtures scan every
  reachable Git object before bundle publication and forbid the normal
  immutable bundle when a true secret remains;
- private-evidence custody fixtures deny source and restore every row only with
  the destination envelope/key, repeat with destination denied and source-only
  restore, compare identical plaintext digests, reject cross-domain private-key
  access and prevent destruction of the last restorable recipient key;
- OIDC broker-client fixtures verify every frozen issuer/audience/subject,
  repository/owner ID, visibility, exact environment presence/value or absence,
  workflow/ref/SHA, event, actor, run ID/attempt, signed `check_run_id`, runner
  environment, JWT time/jti values and operation; independently bind the
  controller nonce and Jobs-API mapping for that same `check_run_id` to the
  identity, consume it by CAS, and reject replay, proxy job, fork, pull request,
  wrong reusable workflow, wrong environment/ref/SHA and stale-token requests;
- external-security operation-lease fixtures re-query every required external
  domain for each token mint/use, key handoff, checkpoint seal/upload/
  replication, private input read, merge, encryption, publication and cleanup;
  they reject stale, unreachable or drifted state, cross-operation/target/retry
  lease reuse and a second privileged side effect after expiry; atomic fixtures
  prove an admitted operation either emits one complete sealed object plus
  terminal receipt or removes/revokes its partial object without beginning a
  later phase;
- OIDC signature fixtures verify the pinned issuer/discovery/JWKS host and
  `RS256` signature before claims, exercise valid key overlap/rotation and
  reject `none`/algorithm substitution, forged signatures, caller-supplied key
  URLs, unknown or duplicate `kid`, stale/unrefreshable JWKS, redirect,
  oversized response and TLS/hostname failure;
- ephemeral-key handoff fixtures prove keys never traverse argv, environment,
  workflow outputs, logs, persistent disk, swap or core dumps; the sealed
  memory/`tmpfs` descriptor is consumed once, closed and removed before any
  upload credential is minted;
- runner-host trust fixtures require explicit provider-host TCB acceptance for
  ordinary GitHub-hosted execution and reject any claim that namespaces,
  seccomp or guest memory protect against a malicious provider host; a
  confidential-compute alternative releases keys only after exact hardware
  measurement attestation;
- fixed-operation-broker fixtures prove no workflow, environment, host step or
  container can request or receive an App private key, JWT or installation
  token for asset read, dependency extraction, dispatch, publication,
  checkpoint write or deadman/reaper control; they reject token/JWT/key material
  in environment variables, files, process arguments, logs and child processes,
  reject installation-token creation endpoints from every client identity and
  record each broker's full residual App authority rather than claiming a
  narrower permission;
- deadman/reaper broker-failure fixtures prove two distinct key objects and two
  provider/account/region/IAM broker domains per managed App, then take each
  broker completely offline and require the other path to suspend/clean the
  exact lease generation inside the SLA;
- App-policy fixtures reject member installation requests, an unexpected App,
  changed permission, added repository selection, stale/mismatched two-actor
  key-ceremony evidence, broker key-fingerprint drift and a token mint whose
  live API-verifiable installation tuple differs from the frozen inventory;
  require the four distinct source-owner/source-App-manager/destination-owner/
  destination-App-manager receipts and their JIT/access-closure evidence;
  selected-repository negative tests exercise every protected repository class,
  permission and endpoint allowlist including `gtbi-dependency-extract`, and
  tests do not pretend that GitHub exposes a complete private-key inventory API;
- App-key import fixtures accept only the direct callback or attested ephemeral
  workstation path, bind host/workload and public-key fingerprints, prove
  transient material destruction and reject clipboard, ordinary laptop,
  persistent disk, sync, backup, reusable session or missing absence evidence;
- result-transport fixtures prove its App can read only Actions artifacts from
  the one manifest-bound disposable repository, cannot read contents/packages/
  environments, is revoked after validation and cannot access another campaign;
- dependency-extract fixtures prove its destination-owned App is suspended by
  default, reads only the exact immutable objects from each allowlisted
  canonical repository class during one bounded extraction lease, cannot read
  mutable refs, unrelated Actions artifacts/packages or campaign artifacts,
  cannot write/administer/dispatch, cannot exceed its endpoint/byte ceiling,
  and cannot mint or use a token after re-suspension or uninstall;
- dispatch fixtures prove the canonical `GITHUB_TOKEN` cannot start the
  cross-repository campaign, the dispatch-only installation is bound to one
  repository/ref/workflow/capsule, the host issues exactly one allowlisted
  dispatch API call, records the returned run, immediately suspends the
  installation and rejects replay, cancellation, rerun, deletion, arbitrary
  inputs and another repository; the unavoidable broader `Actions: write`
  capability is present in the reviewed residual-risk record;
- repository-lifecycle fixtures prove the owner-created disposable repository
  has the reviewed template/visibility and immutable ID, prove the separate
  selected-repository `gtbi-repository-retire` App remains suspended before
  terminal cleanup, and reject creation through automation or deletion of
  Aurora, any canonical store, any pre-existing repository, any different
  repository ID or a campaign repository lacking final restore/revocation
  proof;
- preparation-order fixtures prove the immutable execution commit exists before
  destination copy and exact full monetary authorization, and prove
  `PREV7-0805` cannot create or modify repository content; campaign-key
  provisioning fixtures require fresh, domain-local source and destination
  key-broker custodian receipts bound to each exact broker operation and reject
  substitution by an owner, payer, App manager or earlier generic approval;
- disposition fixtures cover abandonment before repository creation, after App
  installation, after key creation and after destination copy; each reaches
  `ABANDONED_CLEAN` through tasks `PREV7-0910`, `PREV7-0914`,
  `PREV7-0911`, `PREV7-0912` and the financial reconciliation condition, while the
  completed route cancels those tasks only with
  `PREV7-0905`/`PREV7-0906`/`PREV7-0907` replacement receipts;
- disposition deadline fixtures leave one domain unreachable past
  `disposition_decision_due_at_utc`, prove escalation and independent local
  `security_abandoned` suspension without destructive remote authority, and
  refuse project terminality until both authoritative receipts arrive;
- post-dispatch abort fixtures run during workers, after a checkpoint, during
  merge and before final restore; all revoke execution immediately but preserve
  recipient keys, ciphertext, manifests and receipts until inventory, dual
  restore and recovery-window completion, while a proven pre-dispatch
  no-ciphertext abort may destroy campaign keys;
- abandoned recovery-only fixtures prove `PREV7-0914` restores only existing
  manifest-bound ciphertext under a fresh one-use capsule, cannot evaluate,
  assign, merge, rank or publish, and supplies the two receipts needed for
  physical cleanup;
- financial-tail fixtures assign every `DISPUTED_CLEAN` state to
  `PREV7-0913`, enforce its due date/escalation/budget, forbid campaign-resource
  recreation and block project completion until all billing domains reconcile;
- disposition authorization fixtures reject unilateral source abandonment as
  authority over destination, while proving each local deadman still revokes
  its own expired or security-revoked lease when the other domain is offline;
- every planned block input resolves exactly once to an original or
  reconstructed bundle; provider artifact IDs appear only in
  `resolved_block_inputs.json`, never the pre-dispatch manifest;
- hash-contract fixtures carry known-answer vectors for feature, signal, exit,
  simulation, unit-reuse-set, checkpoint-content, job-result, block,
  superblock and resolved-output domains; mutate every effective payload field
  one at a time, prove non-effective metadata does not change scientific reuse
  hashes, prove a multi-unit bundle key is the ordered set of its distinct unit
  keys, and reject self-inclusion of any digest field;
- hierarchical-resolution fixtures create original/retry/reconstructed child
  bundles, accept only digest-identical operational duplicates, choose the
  frozen lowest attempt, reject conflicting logical payloads or memberships,
  and prove block then superblock then final merge consumes only the exact
  resolved maps with no wildcard or latest-artifact discovery;
- operational-evidence merge fixtures union two jobs into one block, two blocks
  into one superblock/final input and prove exact retention, canonical ordering
  and row/record equations for timing, resource and structured-error evidence;
  they reject one omitted row, one duplicated attempt, one conflicting error,
  one malformed schema and any attempt to insert operational evidence into a
  logical scientific digest; sampler fixtures require contiguous
  `(sampler_generation,sample_sequence)` per job attempt, use those fields as
  the total ordering key, reproduce `resource_summary.json` exactly from the
  final `resource_samples.parquet` and reject a summary or operational/
  checkpoint evidence index that omits or substitutes one bound member;
- job/final completion fixtures reject missing, extra, duplicate and
  conflicting unit IDs, overlapping planned partitions, alias multiplicity
  drift, a terminal result from a non-owner and scalar-count forgery; fixtures
  cover both complete and partial-recoverable job bundles, require exact
  accounted/unresolved pair complements, and prove that terminalization owners
  across jobs and reduction nodes are disjoint and exhaustive. The accepted
  fixture proves `3600` unique canonical units, `72000` original strategies
  after alias expansion, and exact equality among `_SUCCESS`, summary,
  canonical map, execution plan and decoded terminal rows;
- assignment/topology fixtures independently recompute every
  `job_assignment_manifest_v1`, its registered set object and the planned
  reduction-topology projection from `execution_plan_v1`; they reject a missing
  job, tile, unit, pair, block, superblock, reduction node, terminalization
  owner, cycle, foreign child, duplicate ownership or unregistered aggregate
  digest;
- fragment-science fixtures authenticate each input partition, preserve exact
  V6 trade order, merge sorted finite-return states deterministically and
  recompute every annual partial state from ordered trade rows; they reject a
  changed trade, count, sum, order, median multiset, holding accumulator,
  partition digest or accelerator-only result;
- package-closure fixtures run the closer only after the prior compute run is
  terminal, prove its own in-progress job is excluded from the closed-run
  ledger and appended later to operational attestations, and reject an
  in-workflow closer that attempts to certify itself as terminal;
- an exhausted-attempt fixture cannot resume without the independently synced
  recovery capsule, and its always-present recovery registry and summary counts
  reconcile exactly;
- hierarchical merge agrees with direct fixture merge;
- every best ID exists in its stated leaderboard, every reported best metric
  equals that exact row, and empty leaderboards force the corresponding IDs
  and metrics to null;
- a fixture where score ordering and adjusted-metric selection disagree proves
  that `best_candidate_id` remains the first V6 score-ranked row while the
  separate `max_adjusted_candidate_id` selects the maximum finite adjusted
  metric;
- a leaderboard with no finite adjusted value proves that
  `best_candidate_id` remains the first score-ranked row, its legacy
  `best_adjusted_return_time_risk` reports the selected row's missing numeric
  state, and both maximum-adjusted diagnostics are null/missing;
- adjusted-metric ties prove the exact validation-median and candidate-ID
  tie policy only for the new maximum-adjusted diagnostics;
- filtered-best ties prove the exact V6 ordering
  `adjusted_return_time_risk DESC, candidate_id ASC`, without inserting a
  validation-median tie breaker;
- a direct Fast Strict V6 merger fixture in which score-best and
  maximum-adjusted differ proves that the V7 compatibility summary reproduces
  the score-best legacy fields byte for byte and keeps maximum-adjusted fields
  diagnostically separate;
- compatibility tests reject every summary ID absent from its stated
  leaderboard and reject equality assumptions between score-best and
  maximum-adjusted fields;
- canonical-best tests prove that canonical score-best comes from the first
  score-ranked canonical row, while canonical maximum-adjusted uses the finite
  adjusted, validation-median, candidate-ID and canonical-strategy-ID ordering;
  all-nonfinite canonical inputs retain score-best and null/missing
  maximum-adjusted diagnostics;
- filtered-canonical-best tests require both canonical IDs in the same passing
  row, exact canonical-map reconciliation, exact adjusted metric/state and all
  four filtered-canonical fields null/missing when no canonical unit passes;
- strict-filter fixtures prove the exact V6 non-finite policy: profit factor
  `+inf` and an all-`+inf` annual minimum are converted by the frozen finite
  helper to the failing sentinel for strict-quality checks, while the
  unfiltered scientific row and its canonical non-finite representation remain
  present;
- global/annual aggregation fixtures distinguish no surviving converted global
  return (missing PF) from at least one surviving non-negative global return
  (`+inf` PF), and from an annual bucket containing closed trades but no finite
  return (missing average/median/win rate, `+inf` PF and nonzero trades);
- schema tests require `work_item_timeout_seconds` and prove the exact
  conditional compatibility mapping for `candidate_timeout_seconds`; a
  physically tiled campaign emits null plus
  `candidate_timeout_semantics=not_applicable_physical_tiling`, never a false
  candidate deadline;
- shared-data fixtures run the same unit through private load, read-only mmap,
  sealed `memfd` where supported and experimental
  `multiprocessing.shared_memory`, require byte-identical results and content
  digests, count mapped pages/processes correctly, reject descriptor-mismatched
  access, prove kernel write/grow/shrink denial for the sealed profiles, detect
  any experimental shared-memory mutation, replace a worker after initial
  attachment without changing bytes and prove path/name/descriptor cleanup
  after success, exception, timeout and cancellation with no escaped host file
  or socket-backed manager;
- planner tests reject a unit or job queue whose conservative compute plus
  terminalization margin exceeds the frozen `job_timeout_minutes<=330`;
- completion tests reject an empty, early or digest-inconsistent `_SUCCESS`,
  require exactly one of `_SUCCESS|_INCOMPLETE|_PACKAGE_CLOSED`, require
  `output_manifest.json` to exclude itself and all three markers, reject either
  non-success marker in every scientific/ranking/gate/publication consumer,
  and prove that writing the manifest before the final marker has no hash
  cycle;
- durable-result identity tests reconstruct the same identity from typed
  manifest and success objects, change it after any payload or success-record
  change, preserve it under transport-file reordering and reject a publication
  receipt whose three digests do not recompute;
- manifest-causality tests reject equivalence or other post-execution result
  fields in `scientific_manifest_v1`, prove identical normalized engine outputs
  retain the same `scientific_output_digest` before and after equivalence is
  determined, and require the separate equivalence report to bind both restored
  `engine_result_digest` values and its decision;
- package-closure fixtures prove the immutable package contains no future
  validation/publication/restore/cleanup job fact, later operations append only
  to the external attestation chain and never rewrite `_SUCCESS`, summary or
  output manifest;
- scientific-output fixtures produce identical
  `scientific_output_digest` under different run IDs, timestamps, costs,
  hardware and publication paths, but change it after any normalized scientific
  table or scientific summary value changes;
- diagnostics tests enforce the frozen columns, one row per canonical
  technical attempt, allowed statuses, redaction schema and exact
  alias-terminal row equations;
- every required V6 compatibility output exists with its frozen schema and
  row grain.

Compare the same immutable representative batch with:

```text
workers=1
workers=2
workers=4
cache=cold
cache=warm
```

Normalize only non-scientific metadata such as run IDs and timestamps.
Canonical scientific records must match byte for byte after stable ordering and
normalization of declared non-scientific metadata, NaN representation and
negative zero. Archive and Parquet container bytes may differ only when their
decoded typed scientific records and schema digests are identical. No numeric
tolerance is introduced unless the frozen contract already defines it.

Workflow:

- every action pinned by SHA;
- every external reusable workflow pinned by full commit SHA and every local
  reusable workflow resolved from the same executed commit; both step and job
  `uses:` forms are linted;
- no `C:\` path;
- no `self-hosted`;
- no unbounded matrix;
- permissions explicit;
- concurrency configured;
- timeouts configured;
- malicious input, artifact-name and archive path-traversal fixtures rejected;
- a local process spoofing `GITHUB_ACTIONS`, repository, run and job variables
  cannot forge or replay the bound GitHub execution receipt, restore private
  assets, publish checkpoints or produce an accepted canonical output;
- the full entrypoint accepts only `dispatch_capsule_digest`, restores the
  destination-owned sync receipt, exact authorization envelope and immutable
  runbook core, derives every effective parameter from verified core bytes and
  rejects an extra input, environment override, stale or dismissed approval,
  expired envelope, missing independent copy or mismatched digest;
- cross-repository identity fixtures distinguish canonical and execution commit
  SHAs, verify every execution-tree file against the frozen mapping/bundle,
  reject an unmanifested generated file and reject comparing `GITHUB_SHA`
  directly with the canonical repository SHA;
- product-transition fixtures prove code merge stops at `V7_PARALLEL`, reject a
  skipped transition or unregistered consumer/in-flight V6 run, exercise the
  protected V6 pointer and code revert before archival, and forbid retired YAML
  while the 30-day observation or any migration is incomplete;
- replaying an already consumed initial dispatch capsule aborts atomically,
  while a separately authorized recovery capsule can append only unresolved
  units after the original envelope expires;
- scientific and workflow approval receipts are API-authenticated, refer to
  distinct registered actors and the exact runbook-core digest;
- exact hosted-runner image version is inside the tested runbook-core allowlist;
- wheelhouse generation provenance, binary-only policy,
  `--no-index --require-hashes`, installed inventory and native libraries all
  match the approved dependency manifest;
- container user, PID namespace, no-network namespace, workspace permissions,
  capabilities, read-only input mounts and bounded output mount are verified
  on GitHub;
- the scientific container cannot inspect host credential processes or
  `/proc`, resolve DNS, open or create a socket/FIFO/device, inherit a
  credential, access the sealed upload directory or mutate an input;
- upload-boundary fixtures reject symlinks, hard-link substitution, FIFO,
  socket, device, traversal, oversize, wrong schema, licence violation and
  digest races before any write token is minted; only the immutable validated
  copy is visible to the uploader;
- pipelined-upload fixtures run science, validation and one ciphertext upload
  concurrently, prove the uploader can read only the sealed ciphertext
  descriptors and no raw/input/key/process path, prove the other phases have no
  artifact runtime channel, enforce the two-slot/backpressure and four-core
  ceilings, and require pipeline-on/off logical/checkpoint/receipt equality;
- credential-scope tests prove the asset-read App cannot access Aurora code,
  the checkpoint OIDC writer cannot access canonical Release repositories or
  overwrite/list unrelated objects, and the cleanup broker is absent from
  canonical namespaces, deletes only manifest-listed object versions and
  performs no upload/overwrite operation during the approved batch;
- disposable-execution-repository tests scan every Actions artifact, log, summary
  and annotation and prove that every real-campaign scientific job, checkpoint,
  block and final payload is authenticated ciphertext; they also query workflow
  run/check/job/artifact/environment metadata and reject any non-allowlisted
  matrix value, input, name, concurrency string, URL or scientific/private
  identifier. Wrong-key, tampered, truncated, replayed and plaintext uploads
  fail before merge or publication;
- log-injection fixtures place Actions command syntax, ANSI/control bytes and
  multiline payloads in every untrusted text field and prove no workflow
  command, output, environment, path, annotation or public log is altered;
- crash-output fixtures raise Python exceptions and native-process failures
  containing tickers, rules, private paths, shell metacharacters and credential-
  shaped canaries; public logs expose only the fixed code/counters, while the
  encrypted private diagnostic is bounded, restorable by the intended
  recipient and absent from every other surface;
- merge-key separation tests prove workers possess only the merge public key,
  block/final merges cannot canonical-publish, the final merge cannot decrypt
  either final-result recipient envelope, the source validator and independent
  destination cannot unwrap each other's labelled envelope, and the canonical
  publisher cannot decrypt results or mint an asset-read/checkpoint-write
  capability;
- the 360-job approval fixture proves one legitimate review releases the
  intended matrix without bypass or per-job approval drift;
- the capacity fixture proves exactly 360 simultaneous scientific workers only
  when source/destination control jobs have independently reserved pools or
  additional shared slots, and proves that 360 total shared slots with one
  required control slot, 359 scientific slots, stale capacity evidence or an
  unsupported environment-review topology all fail G2/G7;
- budget fault tests reserve worst-case minutes/bytes/attempts before dispatch,
  refuse an uncovered job and reconcile released unused reservation;
- provider-limit tests reject stale/current-state drift, private/public
  capacity substitution, oversized artifacts, matrix/job-duration overflow,
  insufficient API quota and a stale dispatch-preflight receipt;
- locked environment inaccessible to normal dispatch.

### PREV7-0705: Fault Injection

Inject and recover from:

- worker cancellation;
- runner loss;
- empty artifact;
- corrupt artifact;
- missing block;
- duplicate unit;
- mismatched data digest;
- mismatched contract digest;
- mismatched runbook-core or authorization-envelope digest;
- forged, stale or wrong-destination disaster-sync receipt and dispatch capsule;
- role, review, ruleset or environment drift between controller start and a
  worker token mint;
- stale or dismissed approval;
- unexpected runner image version;
- expired and revoked installation token;
- attempted scientific network access;
- timeout;
- merge interruption.

The same task executes the exact `ephemeral_key_handoff_v1` positive and
negative fixture and emits the immutable
`g7_ephemeral_key_handoff_test_receipt_digest`. A stale receipt, a receipt from
another attempt/workflow/image/profile, persistent key residue, a log/env/argv
leak, enabled core dump/swap, or key availability concurrent with publication
credentials fails G7.

### Canonical Smoke Order

1. `PREV7-0701`: tiny synthetic fixture CI with no private data, external
   control-plane tenant or billable real-smoke resource.
2. `PREV7-0711` through `PREV7-0713`, then `PREV7-0715`: create the real G7
   validation repository, reserve every source/destination billing domain and
   open one immutable attempt generation.
3. Real-data single-unit smoke.
4. Real-data multi-unit equivalence smoke.
5. One/two/four-worker benchmark.
6. Recovery smoke.
7. Merge-only smoke.
8. Fault injection.
9. Capacity smoke.
10. Full-scale synthetic transport smoke.

Steps 6 and 7 are the two ordered phases of `PREV7-0704`. The task controller
first freezes and verifies `recovery_phase_receipt_digest`; only that successful
receipt may activate the merge-only phase. It then freezes
`merge_only_phase_receipt_digest` against the recovered manifest and closes the
task only when both receipts and their ordering edge verify. A merge-only run
started before recovery completion, or using a different manifest, is rejected
and cannot be hidden inside one combined task status.

The canonical scientific smoke uses at most `100` jobs and includes fast and
slow families. It requires:

```text
locked_rows_loaded=0
missing_units=0
unresolved_timeouts=0
unresolved_runtime_errors=0
empty_artifacts_accepted=0
duplicate_scientific_rows_counted=0
identical_retry_duplicates_collapsed>=1 in the duplicate-injection fixture
terminal_coverage_pct=100
```

### PREV7-0711, PREV7-0710, PREV7-0712, PREV7-0713 And PREV7-0715: G7 Repository, Authorization And Attempt

`PREV7-0701` is the only G7 task allowed before this authorization group and is
purely synthetic, credential-free CI. `PREV7-0711` then creates the disposable
G7 validation repository from the
approved content-addressed template and freezes its real repository ID,
visibility, account, plan and runner group. No smoke approval uses a prospective
or null repository ID.

The planner then freezes exact job, retry, storage, Packages, transfer,
destination and external-control-plane maxima against the current billing-
domain manifest:

- `PREV7-0710` has the repository owner accountable plus
  `required_approver_roles=[source_billing_payer_authorizer]`, and approves
  every source-account and source external-control-plane native-currency cap;
- `PREV7-0712` has one accountable owner, the independent destination owner,
  plus `required_approver_roles=[destination_billing_payer_authorizer]`,
  and approves every destination-account and destination external-control-
  plane native-currency cap;
- `PREV7-0713` has one accountable owner, the licence/acceptable-use reviewer,
  verifies both signed receipt sets and approves the consolidated budget-
  currency ceiling, conservative FX/safety policy and exact workload/repository
  identity. Its reconciliation proves every billing-domain manifest row occurs
  exactly once across the two approval sets; a missing or duplicate payer,
  provider, account, region, transfer direction, tax/fee or currency row is
  `NO-GO`.

Each task records `required_approver_roles` and an
`approval_receipt_set_digest`; one actor cannot satisfy both domain approvals.

An atomic reservation covers worst-case cost in every billing domain before
the first real-data, benchmark, recovery, fault, capacity or transport job
starts. A free public compute rate may reserve zero compute
cost, but it never implies zero artifact, Packages, transfer, destination or
tax/fee cost. A changed rate, plan, account, payer, currency, repository
visibility or runner class invalidates the authorization. Smoke completion
reconciles observed use per domain and cannot borrow from the future full-run
budget.

The 360-job capacity smoke uses negligible scientific work. Its purpose is
runner scheduling and artifact reliability, not research. While all 360
scientific placeholders are active, the source and destination control planes
must each dispatch a reserved synthetic reaper, revoke a lease and publish its
WORM receipt within SLA. Failure of either control job to start immediately
proves that 360 is not an admissible scientific parallelism for that pool.

`PREV7-0715` creates the executable G7 attempt registry. Every real validation
or rerun is a new immutable `G7_ATTEMPT-n` generation with a unique attempt ID,
exact workflow/ref/input digests, source and destination monetary receipts,
new keys and leases, current provider-state snapshot, operation inventory,
evidence prefix and terminal cleanup receipt. A closed generation never
reopens. A rerun must pass the same acceptable-use, budget, trusted-time,
installation, protection and capacity preflight again and may reuse the
deny-all validation repository only after proving the prior generation
terminal and inaccessible. No receipt, reservation, key, lease or partial
success from generation `n` silently authorizes generation `n+1`.
Every attempt-generation transition appends `g7_attempt_event_v1` containing
schema version, campaign/repository identity, attempt ID/generation, sequence,
previous-event digest, previous/new attempt state, decision deadline, exact
workflow/ref/input/budget/security digests, trusted UTC, actor/attestation and
`event_digest` under `GTBI_G7_ATTEMPT_EVENT_V1`, omitting only
`event_digest`.
`PREV7-0714` completes when the permanent cleanup controller and its first
generation are proven; later attempts do not reopen that terminal task. The
controller emits a distinct terminal cleanup child receipt for every
`G7_ATTEMPT-n`, including the post-merge generation consumed by
`PREV7-0800`.
G7 is therefore not derived from terminal task rows alone. Its canonical
projection also binds `current_G7_attempt_generation` and remains red unless
that exact generation has a successful authenticated terminal disposition, a
closed dispatch registry, zero admitted nonterminal operations and its own
terminal cleanup child receipt. A receipt from an earlier generation cannot
green the current one; changing the current generation appends a gate event
that invalidates the prior dynamic condition without reopening any task.

Each generation also owns one immutable two-domain disposition record:

```text
G7_ATTEMPT_DISPOSITION =
  pending
  | abandonment_pending_remote
  | security_abandoned_pending_remote
  | completed
  | abandoned
  | failed_abandoned_clean
```

Every disposition transition appends `g7_attempt_disposition_event_v1` with
schema version, campaign/attempt generation, sequence, previous-event digest,
previous/new disposition, dispatch-boundary/admitted-operation/ciphertext-set
digests, receipt set, cleanup evidence or null, decision deadline, trusted UTC,
actor/attestation and `event_digest` under
`GTBI_G7_ATTEMPT_DISPOSITION_EVENT_V1`, omitting only `event_digest`.

`pending -> completed` requires a successful authenticated terminal attempt, closed
dispatch registry and terminal status for every admitted operation, and is
permitted only before the immutable decision deadline while both local
security states remain `active`.
Formal abandonment starts with one domain-owner intent and atomically changes
`pending -> abandonment_pending_remote`; that state stops new admission but is
not terminal. It changes to `abandoned` only after the source repository owner
and independent destination owner, using different actors and custody
credentials, sign matching receipts over campaign ID, attempt ID/generation,
dispatch-boundary inventory, admitted-operation set digest, ciphertext set
digest, cost ceiling, key-retention plan and cleanup manifest. Those receipts
are anchored independently in both WORM chains. At the immutable decision
deadline, `pending` or `abandonment_pending_remote` automatically
CAS-transitions to `security_abandoned_pending_remote`; each domain separately
records `local_security_state=security_abandoned`, stops dispatch and
credentials, and cannot return to `active`. This state is nonterminal and
reaches `abandoned` only after the same two authoritative owner receipts arrive.
A receipt mismatch, missing domain, timeout, outage or unilateral owner intent
leaves one of the two pending-remote states, permits only local fail-safe lease
expiry and evidence-preserving cleanup, and cannot green a gate or claim formal
abandonment. No pending-remote state can transition to `completed`;
`completed` cannot transition again. A failed or indeterminate attempt that
has reached formal `abandoned` transitions exactly once to
`failed_abandoned_clean` after `PREV7-0714` verifies both-domain cleanup,
negative access, retained-evidence restore, terminal operations/leases and
bounded financial state. This terminal safety state never greens G7, but is
the exact formal abandonment receipt consumed by G9X. A generation abandoned
before dispatch may use the same transition only with a proved empty-
ciphertext boundary.
Accordingly, `PREV7-0714` has a conditional approval policy: normal terminal
cleanup consumes the repository-owner receipt; the abandonment path additionally
requires `required_approver_roles=[independent_disaster_copy_owner]` and the
matching two-domain receipt set.

Every real G7 proof runs in the disposable G7 validation repository under the
same approved identities and reservation. The 360-job capacity phase runs there
under the exact approved
visibility, source organization/account, billing plan, hosted-runner label or
larger-runner group, environment topology, review rule and reviewed
execution-template digest planned for the full. The preferred case is public
standard Linux. A capacity result from canonical Aurora, another owner, another
visibility, another plan or another runner class is invalid. The
selected-repository retire App follows the same manifest and denylist controls
used for a campaign repository. The receipt
freezes account/organization/repository IDs, visibility, plan snapshot,
runner-label/image, Actions policy and measured billing minutes. It expires
after seven days and immediately on a plan, limit, visibility, environment,
runner or Actions-policy change; full preflight re-queries all of them.
Every job also records `os.cpu_count()`, cgroup CPU quota, total memory and
runner context, free disk before credential/asset access and peak disk use.
Acceptance requires the effective CPU count to be exactly `4`, reported usable
memory to be at least `15000 MiB`, and free disk before asset access to meet the
frozen `minimum_free_disk_before_asset_access_mib`; measured
`peak_disk_used_mib` must remain within the frozen runner disk budget. A later
provider change blocks dispatch
rather than silently running the four-worker plan on two CPUs.

`PREV7-0714` is a terminal cleanup controller, not a success-only child. Its
first CAS closes the G7 dispatch registry. It may continue only after the
current `G7_ATTEMPT-n` is terminal and every operation admitted before that CAS
is terminal, or after the owner formally abandons G7 through the frozen
two-domain abandonment protocol above. An empty started-operation set never satisfies the normal
path. It then immediately revokes smoke leases/webhooks, suspends/removes
smoke-only App installations and seals lease/log records. Smoke recipient keys
are destroyed only after either a no-ciphertext inventory or the same
dual-restore/recovery-window predicate required in production; other
smoke-only broker tenants may then be removed. It restores run/usage evidence
and puts the G7 validation
repository in deny-all, so no new validation operation can race cleanup. It
runs after `PREV7-0708` on the
success path, but does
not require `PREV7-0708` to have succeeded. Its immutable security-retirement
receipt is required before `PREV7-0800`, while the repository remains available
only for protected investigation or an approved rerun until that merge is
revalidated. It remains deny-all so an expired G7 receipt can be rerun only as
a newly authorized `G7_ATTEMPT-n+1`, without creating an untracked repository.
`PREV7-0907` later deletes it only
after all smoke artifacts/evidence are independently restored, provider usage
and billing/dispute evidence are exported immutably and the full/no-full
disposition is final. An unresolved provider dispute keeps the financial ledger
open under the bounded evidence budget but does not keep the G7 repository or
tenant live. If the full is formally abandoned, `PREV7-0911` and `PREV7-0912`
perform destination and source physical deletion and emit the same class of
receipt without requiring a nonexistent full run.

Each capacity job publishes a tiny unique receipt and remains alive for the
same bounded observation window after readiness. The merge derives concurrency
from GitHub job start and completion timestamps and requires:

```text
capacity_jobs_requested=360
capacity_jobs_completed=360
capacity_job_failures=0
capacity_receipts_verified=360
observed_peak_concurrent_jobs>=360
capacity_jobs_effective_cpu_count_4=360
capacity_jobs_usable_memory_mib_at_least_15000=360
```

No capacity job receives a private asset credential or scientific data. If the
observed peak is lower, G7 records the measured account limit and remains red
until the owner changes capacity or approves a revised execution architecture;
the planner never pretends that requested jobs were concurrent.

### PREV7-0708: Full-Scale Transport And Recovery Smoke

The separate full-scale transport smoke uses `360` jobs and no scientific data,
but each job emits encrypted synthetic microbatches at the measured production
p95 byte size and cadence. It also emits encrypted final-result bundles and
encrypted block/final merge bundles under the exact production key separation.
It exercises the disposable execution/transport
repository, segmented destination replicator, durable cursor handoff, API
pagination, duplicate replay, source checkpoint compaction and block/final
transport manifests. The admitted synthetic volume is capped by the approved
smoke budget. Acceptance requires:

```text
synthetic_batches_planned=synthetic_batches_replicated
synthetic_batches_compacted=synthetic_batches_planned
transport_digest_conflicts=0
transport_cursor_gaps=0
transport_receipt_chain_errors=0
replicator_segment_failures=0
source_restore_failures=0
transport_rate_limit_exhausted=0
transport_lag_p95_seconds<=frozen_transport_lag_budget_seconds
transport_bytes_actual<=transport_bytes_budget
```

The report records API requests by endpoint, remaining rate limit, bytes,
replication lag and compaction time. A tiny receipt-only capacity smoke cannot
substitute for this transport proof.

### V7 Acceptance Thresholds

Required:

```text
scientific_differences=0
lost_units=0
unresolved_technical_failures=0
peak_rss_mb<12288
mean_effective_cores_cpu_bound>=3.2
worker_utilization_pct_cpu_bound>=80
telemetry_overhead_pct<=1.0
selected_mode_wall_seconds<=reference_mode_wall_seconds
full_run_authorized=false
```

An optimized mode is enabled only when it is strictly faster than the reference
on the frozen repeated benchmark. Equality selects the reference mode. If four
workers are not faster, the fastest scientifically equivalent mode is kept,
with deterministic ties preferring the simpler reference. The `3.2` core and
`80%` utilization targets apply only when the selected mode uses four workers
on a sufficiently long CPU-bound phase. V7 does not force four workers merely
because four CPUs exist.

The benchmark report separates startup, checkout, asset transfer, data load,
feature, signal, simulation, metrics, serialization and merge. It predicts
end-to-end wall time and runner minutes for at least `90`, `180` and `360`
GitHub jobs, includes p50/p95 and a conservative upper budget, and selects the
fastest verified final artifact rather than the fastest isolated calculation.

### Planned Implementation Files

Core:

```text
pyproject.toml
gtbi/__init__.py
gtbi/contracts.py
gtbi/data.py
gtbi/features.py
gtbi/feature_store.py
gtbi/signals.py
gtbi/simulation.py
gtbi/metrics.py
gtbi/filters.py
gtbi/scheduling.py
gtbi/checkpoints.py
gtbi/merge.py
gtbi/telemetry.py
gtbi/cli.py
gtbi/reference_v6/__init__.py
gtbi/reference_v6/entrypoint.py
containers/gtbi-v7/reference-v6.Dockerfile
requirements/gtbi-fast-strict.lock
provenance/v6/reference_image_manifest.json
config/gtbi/contracts/canonical_serialization_v1.json
config/gtbi/contracts/hash_domain_registry_v1.json
config/gtbi/contracts/selection_bias_diagnostic_v1.json
config/gtbi/performance/v7/parallel_mode_equivalence_policy_v1.json
config/gtbi/performance/v7/approved_numerical_execution_profiles.json
config/gtbi/performance/v7/approved_hardware_profiles.json
config/gtbi/schemas/v7/schema_catalog.json
config/gtbi/schemas/v7/scientific/
config/gtbi/schemas/v7/operational/
config/gtbi/schemas/v7/transport/
config/gtbi/schemas/v7/operational/master_plan_audit_scope_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/master_plan_audit_payload_v1.schema.json
config/gtbi/schemas/v7/operational/master_plan_audit_receipt_v1.schema.json
config/gtbi/schemas/v7/operational/master_plan_quality_receipt_set_v1.schema.json
config/gtbi/schemas/v7/scientific/scientific_numerical_semantics_v1.schema.json
config/gtbi/schemas/v7/operational/numerical_execution_profile_v1.schema.json
config/gtbi/schemas/v7/operational/runtime_threadpool_observation_v1.schema.json
config/gtbi/schemas/v7/operational/canonical_timing_attribution_v1.schema.json
config/gtbi/schemas/v7/operational/numerical_execution_profile_registry_v1.schema.json
config/gtbi/schemas/v7/operational/numerical_execution_profile_map_v1.schema.json
config/gtbi/schemas/v7/operational/observed_hardware_profile_v1.schema.json
config/gtbi/schemas/v7/operational/approved_hardware_profile_registry_v1.schema.json
config/gtbi/schemas/v7/operational/observed_hardware_profile_map_v1.schema.json
config/gtbi/schemas/v7/scientific/execution_tree_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/scientific_contract_v1.schema.json
config/gtbi/schemas/v7/transport/scientific_asset_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/data_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/data_snapshot_identity_v1.schema.json
config/gtbi/schemas/v7/scientific/scientific_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/engine_result_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/canonical_strategy_payload_v1.schema.json
config/gtbi/schemas/v7/scientific/strategy_id_set_v1.schema.json
config/gtbi/schemas/v7/scientific/candidate_id_set_v1.schema.json
config/gtbi/schemas/v7/scientific/strategy_candidate_bijection_v1.schema.json
config/gtbi/schemas/v7/scientific/strategy_pack_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/feature_demand_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/scientific_symbol_eligibility_set_v1.schema.json
config/gtbi/schemas/v7/scientific/canonical_map_v1.schema.json
config/gtbi/schemas/v7/scientific/exact_universe_identity_v1.schema.json
config/gtbi/schemas/v7/scientific/instrument_identity_set_v1.schema.json
config/gtbi/schemas/v7/scientific/input_partition_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/input_partition_manifest_set_v1.schema.json
config/gtbi/schemas/v7/operational/physical_data_layout_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/cost_profile_v1.schema.json
config/gtbi/schemas/v7/operational/matrix_partition_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/candidate_symbol_pair_set_v1.schema.json
config/gtbi/schemas/v7/operational/physical_evaluation_tile_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/ordered_trade_fragment_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/annual_metric_partial_state_manifest_v1.schema.json
config/gtbi/schemas/v7/scientific/scientific_fragment_result_v1.schema.json
config/gtbi/schemas/v7/scientific/scientific_fragment_bundle_v1.schema.json
config/gtbi/schemas/v7/scientific/fragment_reduction_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/job_assignment_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/job_assignment_manifest_set_v1.schema.json
config/gtbi/schemas/v7/operational/planned_reduction_topology_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/job_result_manifest_v1.schema.json
config/gtbi/schemas/v7/operational/execution_workflow_bundle_v1.schema.json
config/gtbi/schemas/v7/scientific/parallel_mode_equivalence_policy_v1.schema.json
config/gtbi/schemas/v7/operational/numerical_execution_profile_assignment_v1.schema.json
config/gtbi/schemas/selection_bias_diagnostics.schema.json
```

`schema_catalog.json` enumerates every required core, compatibility, manifest,
receipt, checkpoint, diagnostic and error schema by immutable schema ID,
relative path, classification and digest. Its `scientific` subset produces the
ordered `scientific_schema_set_digest` included in `contract_digest`; its
`operational|transport` subset produces the ordered
`operational_schema_set_digest` included in the execution-workflow bundle and
runbook core. An operational-only schema change therefore invalidates execution
authorization, compatibility tests and complete-result reuse because the
current conservative `scientific_context_key_v1` deliberately binds
`execution_workflow_bundle_digest`; it does not change `contract_digest` or
`scientific_output_digest`. Reuse across a later operational-only workflow
revision would require a separately versioned provenance-translation contract
and equivalence proof and is not assumed by V7. CI expands
`output_manifest.json`,
`v6_output_compatibility_manifest.json` and the hash-domain registry against
that catalog and rejects a missing, duplicate, unreferenced or digest-mismatched
schema. Directory names above are organizational prefixes, never substitutes
for individual versioned schema files.

Reusable performance infrastructure:

```text
infra/__init__.py
infra/github_performance/resource_detection.py
infra/github_performance/__init__.py
infra/github_performance/intra_job_executor.py
infra/github_performance/runtime_telemetry.py
infra/github_performance/execution_planner.py
infra/github_performance/shared_data.py
infra/github_performance/checkpoint.py
infra/github_performance/block_merge.py
infra/github_performance/sealed_batch_validator.py
infra/github_performance/sealed_batch_crypto.py
infra/github_performance/artifact_runtime_uploader.py
infra/github_performance/operational_evidence.py
infra/gtbi_deadman/__init__.py
infra/gtbi_deadman/service.py
infra/gtbi_deadman/lease_registry.py
infra/gtbi_deadman/webhook_auth.py
infra/gtbi_deadman/terminal_manifest.py
infra/gtbi_deadman/deploy/
containers/gtbi-v7/Dockerfile
requirements/gtbi-v7.lock
scripts/validate_gtbi_v7_plan.py
scripts/generate_gtbi_v7_inventory.py
scripts/preserve_gtbi_v6_artifact.py
scripts/restore_gtbi_v6_artifact.py
```

The container consumes `requirements/gtbi-v7.lock`; it does not maintain a
second dependency lock. CI fails if the built image's installed dependency
manifest differs from that lock.

Tests:

```text
tests/test_gtbi_v7_equivalence.py
tests/test_gtbi_v7_scientific_contract.py
tests/test_gtbi_v7_reference_isolation.py
tests/test_gtbi_v7_source_identity.py
tests/test_gtbi_v7_data_integrity.py
tests/test_gtbi_v7_feature_store.py
tests/test_gtbi_v7_physical_tiling.py
tests/test_gtbi_v7_canonical_serialization.py
tests/test_gtbi_v7_temporal_adjustments.py
tests/test_gtbi_v7_parallelism.py
tests/test_gtbi_v7_numerical_identity.py
tests/test_gtbi_v7_shared_data.py
tests/test_gtbi_v7_planner.py
tests/test_gtbi_v7_recovery.py
tests/test_gtbi_v7_merge.py
tests/test_gtbi_v7_telemetry.py
tests/test_gtbi_v7_sealed_transport.py
tests/test_gtbi_v7_output_compatibility.py
tests/test_gtbi_v7_output_consumers.py
tests/test_gtbi_v7_plan_structure.py
tests/test_gtbi_v7_master_plan_quality_receipts.py
tests/test_gtbi_v7_workflow_security.py
tests/test_gtbi_v7_deadman.py
tests/test_gtbi_v7_terminal_manifest.py
tests/test_gtbi_v6_archive_preservation.py
```

Gate G7 passes when all required GitHub checks are green and evidence is
attached to the readiness bundle.

## 19. Gate G8: Full Authorization Package

This document does not authorize the full.

### PREV7-0800: Merge And Revalidate The Canonical V7 Commit

Before building authorization evidence:

1. Open or refresh the V7 implementation pull request against protected
   `main`.
2. Require stage-two CODEOWNERS review and every G7 check on the final proposed
   merge.
3. Merge only through the protected pull-request path; no direct push.
4. Fetch `origin/main` and verify the GitHub merge result, local commit and tree.
5. Create a fresh authorized `G7_ATTEMPT-n+1` bound to that exact merged SHA,
   current G7 conditions and new budget/keys/leases; run the canonical
   scientific, recovery and merge-only smokes through it.
6. Verify workflow, contract, container, dependency and schema digests again.
7. Record the merged SHA as the sole eligible `canonical_code_sha` and legacy
   `code_sha` alias for the runbook core; the later disposable execution commit
   is a separate mapped identity.
8. Keep all V6 consumers and scheduled dispatches unchanged. Merging code moves
   `product_transition_state` only from `V6_ACTIVE` to `V7_PARALLEL`; it does
   not make a V7 result canonical.
9. Freeze a reviewed revert commit/PR recipe against the exact pre-merge main
   tree and prove it on a disposable branch. Before V7 becomes canonical, a
   regression, security finding or failed compatibility smoke returns through
   that protected revert path to `V6_REACTIVATED`.
10. Close that post-merge G7 attempt through `PREV7-0714` semantics and bind
    its success, evidence and terminal cleanup receipts to `PREV7-0800`.
11. Inventory in-progress V6 runs and consumers in the transition receipt; no
    cutover may orphan, reinterpret or silently cancel them.

If the merge method produces a different tree, dependency or workflow byte
from the reviewed candidate, all affected G7 evidence is rerun. Branch-only
smoke evidence never authorizes a full.
The merge transaction consumes the previously green G7 attempt but immediately
sets G7 red/pending-post-merge against the new commit. Only the successful,
cleaned `G7_ATTEMPT-n+1` can green it again and permit `PREV7-0800` to become
done. Thus neither the pre-merge nor the transient red state can authorize G8.

The product-transition state machine uses the only permitted canonical enum:

```text
V6_ACTIVE -> V7_PARALLEL
V7_PARALLEL -> V7_CANONICAL_V6_FROZEN
V7_CANONICAL_V6_FROZEN -> V7_CANONICAL_V6_DISABLED
V7_CANONICAL_V6_DISABLED -> V7_CANONICAL_V6_ARCHIVED
V7_PARALLEL | V7_CANONICAL_V6_FROZEN | V7_CANONICAL_V6_DISABLED
  -> V7_ROLLBACK_PENDING -> V6_REACTIVATED
V6_REACTIVATED -> V7_PARALLEL only through a new V7 attempt generation
```

The shorter token `V7_CANONICAL` is forbidden in machine records and schemas.

Every transition has a protected receipt, exact source/target commit and
consumer-registry digest. Rollback never mutates the failed V7 generation.

### PREV7-0814: Full-Disposition Controller

Before any full-specific repository, App installation, key or external tenant
is created, initialize an append-only disposition record with state `pending`,
`disposition_decision_due_at_utc`, source and destination escalation chains,
current resource inventory and a frozen dispatch boundary initially
`pre_dispatch`. The protected controller may atomically transition it to
`completed` only with the source-owner receipt and verified `PREV7-0904`
destination restore receipt, before the immutable decision deadline and while
both local security states are `active`. Abandonment is two-stage: `pending` becomes
`abandonment_pending_remote` on the first valid domain-owner intent, and becomes
`abandoned` only after separate source-owner and independent-destination-owner
receipts cover the same inventory, reason and dispatch boundary. Every
transition binds campaign ID, receipt-set digest, trusted UTC, expected record
version and previous-event digest. No transition back to `pending` exists.
The row is `full_disposition_event_v1` and also binds schema version, event
sequence, previous/new disposition, dispatch boundary, resource-inventory
digest, decision deadline, source/destination escalation state, actor/
attestation and `event_digest` under `GTBI_FULL_DISPOSITION_EVENT_V1`,
omitting only `event_digest`.

The exhaustive state enum is:

```text
FULL_DISPOSITION =
  pending
  | abandonment_pending_remote
  | security_abandoned_pending_remote
  | completed
  | abandoned
```

The decision deadline cannot silently extend. Before it expires, unanswered
approval is escalated in order to the registered domain deputy, succession
authority and break-glass custodian; break-glass can suspend access and preserve
evidence but cannot approve science or destructive cleanup. At or after the
deadline, each sovereign domain independently records
`local_security_state=security_abandoned`, stops local dispatch, expires local
leases, suspends local Apps and token routes and restores deny-all even if the
other domain is unavailable. The joint controller atomically changes
`pending|abandonment_pending_remote` to
`security_abandoned_pending_remote`. It is nonterminal, cannot transition to
`completed`, and can transition only to `abandoned` after both authoritative
owner receipts arrive. No project terminal state is claimed and no
retained data or recovery key is destroyed until the missing authoritative
receipt arrives. This bounds privileged exposure without granting one domain
destructive authority over the other.

The initial deadline is not arbitrary. Before provisioning, the runbook proves
it is later than the conservative upper bound for all authorized campaign
segments, continuation ceremonies, final merge/publication, independent
destination restore and security-retirement margin, yet no later than the
funded monitoring/deadman/retention horizon. If both inequalities cannot hold,
the full is `NO-GO`; the plan does not rely on extending the deadline during
execution.

The immutable dispatch boundary changes to `post_dispatch` before the first
scientific job can start, as part of the same CAS that consumes the dispatch
capsule. `pre_dispatch` abandonment may destroy campaign recipient keys only
after a complete inventory and negative proof show that no checkpoint, result
or other ciphertext was ever produced. `post_dispatch` abandonment enters
`aborting_preserve`: execution and access are revoked immediately, but
checkpoint/result recipient keys, encrypted payloads, manifests and recovery
receipts are preserved through inventory, independent dual restore and the
approved recovery window. A source abandonment intent can revoke source
resources immediately but cannot command destination deletion or change the
joint disposition without the destination receipt; destination lease expiry and
security revocation remain independently fail-safe during an outage.

All later full tasks declare `activation_condition`. Normal preparation,
execution, verification and preservation through `PREV7-0904` require
`full_disposition=pending`, an unexpired decision deadline and both local
security states `active`. `PREV7-0905` alone performs the successful
`pending -> completed` CAS; `PREV7-0906`, `PREV7-0907` and `PREV7-0903`
thereafter require `completed`. The abandonment security cleanup
performed by each domain controller/deadman begins in either pending-remote
state; `PREV7-0910` begins only when `full_disposition=abandoned` and performs
the formal joint abandoned cleanup. Delayed physical cleanups
`PREV7-0911` and `PREV7-0912` then run independently and may complete in either
order; only `PREV7-0913` waits for both. A branch not selected is
`cancelled` only after
its alternative branch publishes a terminal receipt. This controller exists
before the first resource so an interrupted preparation has an executable
cleanup owner rather than prose intent.

Initialization also creates source and destination pre-authorized delayed-
retirement manifests with exact local resource IDs, generation, activation
deadline, recovery predicates, maximum retention and allowed API operations.
If an owner disappears, an authenticated same-domain successor from the frozen
role registry may use only its local manifest to remove local ephemeral
resources after the delay and required restore/evidence checks. It receives no
opposite-domain or scientific authority and cannot change disposition.

### PREV7-0815: Capped Pre-ID Provisioning Authorization

Creating the real campaign repository, App keys and broker objects may itself
consume billable resources before their immutable IDs exist. This task closes
that bootstrap gap. The source owner, independent destination owner and
licence/acceptable-use reviewer approve one receipt set bound to the exact
organization/account IDs, reviewed template digest, intended visibility,
unique campaign-purpose selector, provider/service classes and a small native-
currency cap for repository/App/key/broker provisioning only. It explicitly
forbids scientific jobs, data transfer, checkpointing, result processing and
general full execution.

Every provisional charge is tagged to the campaign and later appears exactly
once in `PREV7-0811` through `PREV7-0813`; exact authorization either adopts
the charge or selects abandonment cleanup. Exceeding the pre-ID cap or creating
an unmanifested resource is `NO-GO`. This is not full monetary authorization.

### PREV7-0808: Owner App-Installation Ceremonies

GitHub workflows may validate and configure the disposable repository after its
immutable ID exists, but cannot create it. The owner creates it interactively
inside the isolated campaign organization; workflows also do not pretend that a
general REST endpoint can install arbitrary GitHub Apps. Before `PREV7-0801`
freezes the evidence bundle:

1. The repository owner approves and creates the empty disposable repository
   from the reviewed template, recording its immutable repository ID.
2. The distinct source App manager prepares/attests the App and key manifest;
   the repository/organization owner performs GitHub's interactive installation
   authorization for each source-owned campaign App on exactly that repository;
   both sign the receipt. Any provider-generated PEM follows only the reviewed
   direct broker callback or ephemeral attested-workstation import path from
   section 10; ordinary PCs, clipboard and persistent downloads are forbidden.
   No installation is granted organization-wide or to another repository.
3. The independent destination owner proves ownership of the destination
   replicator App and its protected reaper. The source repository owner
   completes the selected-repository installation ceremony for that
   destination-owned App without receiving any destination private key.
4. The distinct destination App manager prepares/attests each destination App
   and key manifest; the destination organization owner performs GitHub's
   installation authorization for the exact destination repositories; both
   sign the receipt under the same hardened direct/ephemeral import rule. No
   source actor receives destination credentials or administrative access.
5. Protected read-only verification records every App ID, installation ID,
   selected repository, permission set, owner actor, installation timestamp,
   current suspension state and policy digest. Unexpected or additional
   installations block G8.
6. All campaign installations finish suspended and all environments deny-all.
   Four separate immutable receipts are mandatory: source repository owner,
   source App manager, independent destination owner and destination App
   manager. Each binds immutable actor ID/role, JIT lease ID and expiry, App and
   installation IDs, selected repository IDs, exact permissions/endpoints, key
   manifest/import receipt, before/after suspension state, access-closure
   receipt, trusted UTC, `valid_until_utc` and previous receipt digest. All four
   are immutable inputs to both the evidence bundle and `runbook_core.json`;
   an aggregate receipt cannot substitute for a missing actor receipt.

Automation after this task may verify, suspend, activate under lease and remove
only these existing installations. It cannot create or silently broaden them.
The task cannot become ready until `APP_PRIVATE_KEY_IMPORT` is selected and
the exact direct-import proof or ephemeral-workstation attestation/destruction
receipt verifies for every App-key ceremony.

### PREV7-0810: Exact Execution Commit

After `PREV7-0808`, copy the reviewed execution bundle derived from
`canonical_code_sha` into the still-suspended campaign repository and create
exactly one execution commit. Record repository ID, commit, tree, workflow
bundle, generated-controller sources and a per-file source-to-execution
mapping. Git and GitHub API verification must agree. No scientific asset,
activation token, campaign secret or run exists, and no later task may rewrite
this commit. `PREV7-0310` copies and restores this already-existing identity;
`PREV7-0805` only verifies and freezes it.

### PREV7-0811, PREV7-0812 And PREV7-0813: Exact Full Monetary Authorization

Using the immutable campaign repository ID and execution commit from
`PREV7-0810`, freeze the exact full job/retry/runtime/storage/Packages/transfer/
tax/fee and external-control envelope:

- `PREV7-0811`, owned by the source repository owner, authorizes and reserves
  all source-account and source external-control-plane domains and requires the
  current `source_billing_payer_authorizer` receipt;
- `PREV7-0812`, owned independently by the destination owner, authorizes and
  reserves all destination-account and destination external-control-plane
  domains and requires the current `destination_billing_payer_authorizer`
  receipt;
- `PREV7-0813`, owned by the licence/acceptable-use reviewer, reconciles every
  preliminary manifest row exactly once, rejects missing or duplicate billing
  domains, applies the frozen conservative FX policy and binds the consolidated
  ceiling to repository ID, execution commit and workload envelope.

These are new full approvals, not reused smoke receipts. They occur before
`PREV7-0310`, so the destination copy/restore cost itself is already authorized.
Rate, payer, account, region, currency, plan, visibility, runner, repository,
execution commit or workload drift invalidates all three.

### PREV7-0801: Evidence Bundle

Create:

```text
docs/readiness/gtbi-v7/go-no-go/
├── summary.md
├── task_status_snapshot.csv
├── gate_status_snapshot.csv
├── task_definitions_snapshot.csv
├── gate_definitions_snapshot.csv
├── task_planning_inputs_snapshot.csv
├── task_events_snapshot.jsonl
├── task_attempts_snapshot.jsonl
├── gate_events_snapshot.jsonl
├── conditional_branch_registry_snapshot.csv
├── task_delivery_manifest_snapshot.csv
├── manifests.json
├── approval_status.json
├── ci_runs.json
├── equivalence_report.json
├── benchmark_report.json
├── recovery_report.json
├── fault_injection_report.json
├── storage_restore_report.json
├── licence_decision.md
├── github_actions_acceptable_use_decision.md
├── pricing_and_budget_decision.json
├── app_installation_ceremony_receipts.json
└── risk_register.csv
```

The ten snapshot files are immutable copies of the canonical live task/gate
status, task/gate definitions, planning inputs, task events, attempts, gate
events, conditional branches and delivery manifest under
`docs/readiness/gtbi-v7/` taken at bundle creation.
Their digests are recorded in `manifests.json`.

This directory is the public, redacted view of the authorization package.
`manifests.json` also lists every required private evidence object by logical
ID, classification, schema version and SHA-256. Raw access logs, private
security reports, licensed data samples and detailed trade evidence remain in
the private evidence package. No secret, signed URL or credential-bearing
locator may appear in either the public bundle or Git history. Protected CI
must restore and verify all private objects before G8 can pass.

`PREV7-0801` has `required_approver_roles=[independent_redaction_reviewer]`.
The reviewer must restore the proposed public subset and its private source
objects, verify every redaction and prohibited-field rule, run the secret and
licensed-data scanners, and sign a receipt bound to the exact public-bundle and
private-manifest digests. The implementer remains the accountable task owner
but cannot supply this approval. The task cannot become `done`, and G8 cannot
use the bundle, while that actor is vacant or the receipt is stale.

### PREV7-0816: Final Deployed-Security Approval

The independent security reviewer restores the exact `runbook_core_digest`,
role registry, deployed source/destination IAM, Apps/installations, broker key
attestations, run-control policy, deadman/reaper builds, lease schemas and G7
fault/destructive-path receipts. The reviewer verifies zero unresolved
critical/high findings and explicitly accepts each bounded residual risk with
owner and expiry. The resulting
`security_approval_receipt.json` binds all those digests, reviewer actor ID,
creation/expiry, current GitHub provider-state snapshot, the canonical
`approved_external_security_configuration_digest` and
`approved_external_security_transition_policy_digest`. The immutable
configuration contains source/destination IAM and permission policy versions,
account-root/payer boundaries, App/installation resource IDs and permission
ceilings, broker/key policy, lease-registry ACL/schema, deadman/reaper
deployment identity, WORM/object-lock/KMS policy and monitor/alert routing
configuration. Exact configuration drift invalidates approval.

Liveness timestamps/sequences, current lease records, App suspension/activation
state, current trusted time and no-op test receipts are not hashed into that
immutable configuration. They form signed
`external_security_observation_v1` events with trusted time, monotonic sequence,
previous-event digest and freshness limit. The transition policy enumerates
every allowed operational state transition and evidence required; an unknown,
backwards, missing-predecessor, stale or disallowed observation invalidates
authority. Design-time
`PREV7-0209` approval cannot substitute for this deployed-state approval.

The observation's exact typed fields are:

```text
schema_version
campaign_id
custody_domain_id
sequence
previous_event_digest_or_null
trusted_at_utc
valid_until_utc
freshness_limit_seconds
approved_external_security_configuration_digest
approved_external_security_transition_policy_digest
current_provider_state_snapshot_digest
current_lease_registry_head_digest
current_app_installation_state_digest
current_broker_key_state_digest
current_deadman_reaper_state_digest
current_monitor_alert_state_digest
no_op_test_receipt_set_digest
actor_id
actor_role
actor_attestation_digest
signature_receipt_digest
observation_digest
```

`observation_digest` uses `GTBI_EXTERNAL_SECURITY_OBSERVATION_V1`, omitting
only itself. `valid_until_utc` must equal the policy-defined addition of
`trusted_at_utc` and `freshness_limit_seconds`; a consumer independently
recomputes it. Sequence zero requires a null predecessor, every later
observation names the prior accepted digest and no sequence or validity window
may be reused or extended by replay.

### Full Gate Checklist

- [ ] Master plan tracked and merged from latest `origin/main`.
- [ ] Unified V7 identity approved.
- [ ] Scope and non-goals approved.
- [ ] V6 final result restored from emergency primary and mirror.
- [ ] Independently administered GitHub disaster copy restored with the
  primary organization treated as unavailable.
- [ ] V6 source commit, workflow, repository bundle and immutable archival tag
  restored and verified.
- [ ] V6 dependency chain classified.
- [ ] Data licence decision recorded.
- [ ] GitHub Actions product terms and acceptable use are approved for the exact
  workload/topology; any material ambiguity has a written Support response.
- [ ] Licence decision explicitly approves the exact public ciphertext
  transport classes, or the separately benchmarked private larger-runner
  topology has replaced them in every bound manifest.
- [ ] Primary and mirror restore tests green.
- [ ] Short-lived private authentication tested.
- [ ] Public evidence bundle has an independent redaction-review receipt and
  private-evidence restore is green.
- [ ] No secret or credential-bearing locator appears in Git history or
  authorization artifacts.
- [ ] Independent scientific and workflow review paths are actually available.
- [ ] `main` protected without deadlock.
- [ ] CODEOWNERS valid.
- [ ] Stage-two approval and stale-review rules active.
- [ ] Environments configured.
- [ ] Privileged humans use phishing-resistant authentication, two
  authenticators and tested recovery custody; source and destination
  break-glass custodians are distinct and their restoration tests are current.
- [ ] App installation policy, managed non-exportable cleanup-key-pair brokers,
  activation leases and
  both source and destination reaper force-cancel tests are green.
- [ ] Repository owner/App manager completed the exact GitHub App installation
  ceremonies; every production installation ID, permission and selected
  repository matches the owner and destination receipts.
- [ ] Actions pinned.
- [ ] Permissions minimal.
- [ ] Container base and runtime images pinned, scanned and attested.
- [ ] Disposable execution repository has the licence-approved visibility,
  contains no unrelated runs, and four-CPU/15,000-MiB capacity is freshly
  proven for its exact runner class.
- [ ] Every real-campaign scientific Actions payload and merge intermediate is encrypted;
  log/summary redaction and merge/publisher key separation tests are green.
- [ ] Secret scanning and push protection enabled.
- [ ] Scientific asset extraction and deserialization security tests green.
- [ ] Legacy queued runs resolved.
- [ ] New branch created from current `main`.
- [ ] PR 20 resolved or replaced.
- [ ] V7 implementation merged through protected PR and the exact merged SHA
  passed post-merge canonical, recovery and merge-only smokes.
- [ ] Scientific contract frozen.
- [ ] Historical `2021+` classified as contaminated.
- [ ] Historical execution pack physically contains zero rows from `2021+`.
- [ ] New forward lock defined or explicitly blocked.
- [ ] Semantic oracle green.
- [ ] Historical golden is green with recovered authenticated V6 inputs.
  `unavailable_missing_original_inputs` is an explicit V7 `NO-GO`, even if a
  separately named reference proposal exists.
- [ ] GitHub-only guard green.
- [ ] Dependency lock and wheelhouse verified.
- [ ] Runner label and runtime-container digest pinned.
- [ ] One, two and four worker equivalence green.
- [ ] Safe optimizations equivalent.
- [ ] Durable checkpoint transport and recovery green.
- [ ] Hierarchical merge green.
- [ ] Canonical and alias-expanded row equations green.
- [ ] Canonical and alias-expanded passing-candidate counts are reported
  separately and the twenty-alias fixture is green.
- [ ] Summary best IDs and every reported row count match the actual files.
- [ ] Engine-equivalence and exploratory-selection labels are present; no
  confirmatory strategy claim is emitted.
- [ ] V6 output compatibility manifest and migration map green.
- [ ] Output-consumer registry complete and every registered migration test
  green.
- [ ] Approved and unapproved unsupported units both equal zero for the
  72,000-pack baseline.
- [ ] Fault injection green.
- [ ] Canonical smoke green.
- [ ] 360-job capacity smoke green.
- [ ] Full-scale synthetic transport, segmented replicator and reverse-recovery
  smoke green.
- [ ] Artifact restoration green.
- [ ] Capped multi-party pre-ID provisioning authorization is current and
  reconciled into the exact full billing sets.
- [ ] Full-disposition controller exists before any campaign resource.
- [ ] Exact execution commit exists, is immutable and is independently restored.
- [ ] Technical-resource and worst-case monetary budgets are approved in the
  frozen pricing currency against a current pricing snapshot; source,
  destination and consolidated full receipts cover each billing domain exactly
  once.
- [ ] Scientific reviewer approved the exact runbook-core digest through its
  protected environment and API-authenticated receipt.
- [ ] Workflow reviewer approved the exact runbook-core digest through its
  protected environment and API-authenticated receipt.
- [ ] Licence and acceptable-use reviewer approved the exact final workload and
  billing-domain manifest bound to that same runbook-core digest.
- [ ] Independent security reviewer approved the exact deployed IAM, Apps,
  brokers, run-control/deadman state and G7 destructive-path evidence bound to
  that same runbook-core digest.
- [ ] Repository owner explicitly authorized that same runbook-core digest and
  the final authorization envelope is current and unexpired.
- [ ] Independent destination restored the runbook core, envelope and approval
  evidence; its sync receipt and the immutable dispatch capsule are current.

### Full Runbook Core And Authorization Envelope

After the evidence bundle and before either independent sign-off, generate a
separate proposed immutable `runbook_core.json` containing:

`master_plan_digest` hashes the exact reviewed canonical master-plan file bytes
under the registered `gtbi_master_plan_v1` domain.
`execution_plan_digest` hashes the canonical scientific assignment/merge plan
under `gtbi_execution_plan_v1`. Result bundles, `_SUCCESS`, summaries and the
runbook all use that same `execution_plan_digest`; any ambiguous legacy
plan-hash field is forbidden.

```text
campaign_id
product
master_plan_digest
master_plan_quality_receipt_set_digest
scientific_context_key_digest
global_unit_reuse_key_set_digest
exact_universe_identity_digest
exact_universe_identity_schema_digest
data_manifest_schema_digest
data_snapshot_identity_schema_digest
observation_timestamp_state
code_sha
canonical_code_sha
execution_repository_commit_sha
execution_tree_digest
execution_workflow_bundle_digest
canonical_to_execution_mapping_manifest_digest
workflow_sha
workflow_digests
workflow_registration_sha
executed_ref_sha
dispatch_ref
protected_full_tag
protected_execution_tag
initial_product_transition_state
product_transition_registry_digest
v6_consumer_registry_digest
v6_revert_recipe_and_drill_digest
runner_label
runner_image_version
runner_image_version_allowlist
runner_host_trust_model
runner_host_trust_acceptance_receipt_digest
confidential_compute_attestation_policy_digest_or_null
broker_key_release_measurement_policy_digest_or_null
expected_runner_cpu_count
expected_runner_memory_mib
expected_runner_disk_mib
minimum_free_disk_before_asset_access_mib
peak_disk_used_mib_limit
github_provider_limit_policy_digest
runtime_container_digest
runtime_sbom_digest
runtime_attestation_digest
vulnerability_scanner_name
vulnerability_scanner_version
vulnerability_database_timestamp
vulnerability_database_digest
vulnerability_report_digest
vulnerability_policy_digest
vulnerability_exception_manifest_digest
vulnerability_exception_expiry
secret_scanning_policy_and_custom_pattern_digest
secret_scanning_zero_open_alerts_receipt_digest
private_evidence_intake_scan_receipt_set_digest
private_evidence_manifest_schema_digest
private_evidence_manifest_bootstrap_head_digest
private_evidence_manifest_production_head_digest
private_evidence_source_worm_store_identity_digest
private_evidence_destination_worm_store_identity_digest
private_evidence_source_recipient_key_id
private_evidence_destination_recipient_key_id
private_evidence_source_recipient_broker_identity_digest
private_evidence_destination_recipient_broker_identity_digest
private_evidence_dual_restore_receipt_set_digest
private_evidence_key_domain_loss_and_destruction_policy_digest
threat_model_digest
threat_control_test_matrix_digest
residual_risk_registry_digest
trusted_computing_base_manifest_digest
oidc_workload_registry_digest
oidc_custom_subject_template_digest
oidc_job_check_run_binding_policy_digest
oidc_nonce_issuer_policy_digest
frozen_role_registry_digest
privileged_human_auth_policy_digest
app_custody_organization_manifest_digest
app_manager_just_in_time_access_policy_digest
app_manager_zero_standing_access_receipt_digest
app_key_management_worm_audit_anchor_digest
installation_owner_uninstall_test_receipt_digest
source_break_glass_custody_receipt_digest
destination_break_glass_custody_receipt_digest
privileged_access_review_digest
scientific_manifest_digest
scientific_manifest_schema_digest
engine_result_manifest_schema_digest
contract_digest
scientific_schema_set_digest
operational_schema_set_digest
policy_hash
selection_split
scoring_profile
min_selection_trades_per_year
score_formula_manifest_digest
final_filter_registry_digest
evaluation_identity
selection_bias_diagnostic_method_digest
reproducibility_classification
reuse_recovered_v6_inputs
oracle_b_status
semantic_oracle_coverage_manifest_digest
semantic_oracle_effective_branch_coverage_pct
semantic_oracle_non_equivalent_mutants_survived
v6_historical_reproduction_confirmed
synthetic_engine_equivalence_confirmed
engine_equivalence_confirmed
optimized_vs_reference_equivalence_confirmed
reference_engine_code_sha
reference_engine_tree_digest
reference_entrypoint_digest
reference_dependency_lock_digest
reference_runtime_digest
reference_engine_isolation_policy_digest
numerical_environment_digest
scientific_numerical_semantics_digest
parallel_mode_equivalence_policy_digest
approved_numerical_execution_profile_registry_digest
approved_hardware_profile_registry_digest
observed_hardware_profile_map_schema_digest
numerical_execution_profile_map_schema_digest
runtime_threadpool_observation_schema_digest
canonical_timing_attribution_schema_digest
missing_v6_dependency_layers
strategy_selection_evidence
validation_reused_for_selection
confirmatory_strategy_validity
multiple_testing_original_candidates
multiple_testing_canonical_candidates
data_digest
data_manifest_digest
historical_execution_pack_digest
input_partition_manifest_set_digest
instrument_identity_set_schema_digest
input_partition_manifest_schema_digest
input_partition_manifest_set_schema_digest
historical_min_observation_date
historical_max_observation_date
price_data_vintage_utc
source_event_cutoff_utc
adjustment_temporal_model
corporate_action_knowledge_manifest_digest
corporate_action_knowledge_coverage_pct
historical_adjustment_vintage_contaminated
adjustment_point_in_time_claim_allowed
decision_time_policy_digest
market_observation_availability_policy_digest
cross_market_alignment_model
cross_market_temporal_contaminated
causal_cross_market_claim_allowed
universe_temporal_model
universe_temporal_manifest_digest
universe_temporal_coverage_pct
universe_point_in_time_claim_allowed
reference_index_order_confirmed
no_lookahead_confirmed
historical_causal_claim_allowed
calendar_policy_sha256
currency_policy_sha256
survivorship_biased_reference
historical_exclusion_start
historical_post_validation_contaminated
pristine_locked
new_forward_available
first_market_session_locked
first_market_session_locked_by_market_digest_or_null
forward_lock_calendar_manifest_digest_or_null
later_required_approval_utc_or_null
forward_lock_proposal_digest_or_null
locked_approval_receipt_digest_or_null
owner_forward_authorization_receipt_digest_or_null
forward_lock_activation_digest_or_null
attested_no_forward_decision_digest_or_null
train_start_policy
validation_boundary_policy_digest
canonical_serialization_profile_digest
hash_domain_registry_digest
strategy_pack_digest
strategy_record_schema_digest
canonical_strategy_payload_schema_digest
strategy_id_set_digest
candidate_id_set_digest
strategy_candidate_bijection_digest
strategy_id_set_schema_digest
candidate_id_set_schema_digest
strategy_candidate_bijection_schema_digest
canonical_map_digest
canonical_map_schema_digest
expected_original_strategy_count
expected_canonical_unit_count
expected_unique_signal_bundle_count
expected_exit_variants_per_signal_bundle
dependency_lock_digest
wheelhouse_manifest_digest
dependency_provenance_digest
feature_demand_manifest_digest
feature_demand_manifest_schema_digest
scientific_symbol_eligibility_set_schema_digest
physical_data_layout_digest
physical_data_layout_manifest_schema_digest
physical_data_layout_equivalence_receipt_digest
global_candidate_symbol_pair_set_digest
candidate_symbol_pair_set_schema_digest
physical_evaluation_tile_manifest_schema_digest
ordered_trade_fragment_manifest_schema_digest
annual_metric_partial_state_manifest_schema_digest
scientific_fragment_result_schema_digest
scientific_fragment_bundle_schema_digest
fragment_reduction_manifest_schema_digest
profile_guided_optimization_report_digest
cost_profile_digest
cost_profile_schema_digest
execution_plan_digest
execution_plan_id
matrix_partition_manifest_digest
matrix_partition_manifest_schema_digest
matrix_a_size
matrix_b_size
max_parallel_a
max_parallel_b
matrix_b_present
g7_validation_repository_id
g7_attempt_registry_identity_digest
g7_attempt_schema_digest
bound_g7_attempt_id
work_attempt_registry_identity_digest
work_attempt_registry_manifest_digest
external_attempt_event_schema_digest
capacity_smoke_execution_receipt_digest
capacity_smoke_security_retirement_receipt_digest
capacity_smoke_cost_reconciliation_head_digest
capacity_smoke_evidence_valid_until_utc
full_scale_transport_smoke_receipt_digest
job_assignment_manifest_set_digest
job_assignment_manifest_schema_digest
job_result_manifest_schema_digest
planned_reduction_topology_manifest_digest
selected_execution_mode_policy
numerical_execution_profile_assignment_digest
unsupported_approved_manifest_digest
output_compatibility_manifest_digest
output_consumer_registry_digest
licence_decision_digest
public_actions_ciphertext_transport_decision_digest
github_hosted_plaintext_processing_decision_digest
github_actions_acceptable_use_decision
github_actions_acceptable_use_decision_digest
github_actions_terms_document_digest
github_actions_support_response_digest
external_control_plane_terms_decision_digest
platform_outage_storage_terms_decision_digest
reviewed_workload_digest
billing_domain_manifest_digest
billing_domain_approval_receipt_set_digest
pre_id_provisioning_authorization_receipt_set_digest
source_full_billing_approval_receipt_digest
destination_full_billing_approval_receipt_digest
consolidated_full_billing_approval_receipt_set_digest
consolidated_fx_snapshot_digest
pricing_snapshot_digest
pricing_snapshot_valid_until_utc
job_count
max_effective_compute_threads_per_job
max_parallel
source_control_reserve_when_shared
destination_control_reserve_when_shared
control_pool_separation_receipt_set_digest
work_item_timeout_seconds
job_timeout_minutes
max_initial_campaign_wall_minutes
max_continuation_authority_generations
authority_segment_manifest_set_digest
max_initial_technical_attempts_per_work_identity
max_total_technical_attempts_per_work_identity
checkpoint_policy
checkpoint_batch_max_records
checkpoint_batch_max_seconds
checkpoint_fragment_bundle_max_fragments
checkpoint_fragment_bundle_max_uncompressed_bytes
checkpoint_batch_max_uncompressed_bytes
checkpoint_transport
github_actions_artifact_hard_limit_per_job
github_actions_artifact_safety_reserve_per_job
max_planned_actions_artifacts_per_job
actions_artifacts_planned_per_job_max
actions_artifacts_planned_total
actions_artifact_plaintext_bytes_planned_total
actions_artifact_ciphertext_bytes_planned_total
actions_artifact_storage_headroom_bytes
actions_artifact_upload_compression_level
source_execution_transport_repository_id
source_execution_transport_repository_visibility
source_execution_transport_template_digest
source_execution_transport_repository_policy_digest
source_execution_transport_owner_creation_receipt_digest
source_repository_retire_app_id
source_repository_retire_installation_id
source_repository_retire_permission_and_endpoint_digest
source_dispatch_app_id
source_dispatch_installation_id
source_dispatch_permission_digest
source_dispatch_endpoint_allowlist_digest
source_result_transport_read_app_id
source_result_transport_read_installation_id
source_result_transport_read_permission_digest
source_transport_retirement_manifest_digest
destination_dependency_extract_app_id
destination_dependency_extract_installation_id_set_digest
destination_dependency_extract_repository_class_manifest_digest
destination_dependency_extract_permission_and_endpoint_digest
destination_dependency_extract_lease_policy_digest
destination_dependency_extract_install_suspend_uninstall_receipt_set_digest
checkpoint_disaster_replication_policy_digest
checkpoint_encryption_profile_digest
result_bundle_encryption_profile_digest
campaign_merge_recipient_public_key_digest
campaign_merge_recipient_key_id
campaign_merge_private_key_custody_policy_digest
campaign_merge_key_broker_identity_digest
ephemeral_key_handoff_profile_digest
g7_ephemeral_key_handoff_test_receipt_digest
source_result_validator_recipient_public_key_digest
source_result_validator_recipient_key_id
source_result_validator_private_key_custody_policy_digest
source_result_validator_key_broker_identity_digest
destination_final_result_recipient_public_key_digest
destination_final_result_recipient_key_id
canonical_result_archival_key_policy_digest
minimum_live_result_recipient_keys=2
result_key_rotation_and_destruction_policy_digest
recipient_key_domain_loss_recovery_policy_digest
recipient_key_domain_loss_receipt_schema_digest
source_checkpoint_uploader_public_key_digest
source_checkpoint_recipient_key_id
source_checkpoint_private_key_custody_policy_digest
source_checkpoint_key_broker_identity_digest
source_checkpoint_key_rotation_policy_digest
source_checkpoint_key_destruction_receipt_schema_digest
destination_checkpoint_recovery_public_key_digest
destination_recipient_key_broker_identity_digest
checkpoint_replication_source_grant_policy_digest
checkpoint_reverse_recovery_policy_digest
source_recovery_ingress_provider_account_store_digest
source_recovery_ingress_immutable_object_policy_digest
source_recovery_ingress_put_if_absent_capability_schema_digest
source_recovery_ingress_get_capability_schema_digest
source_recovery_ingress_retention_and_cleanup_policy_digest
replicator_segment_max_minutes
replicator_cursor_schema_digest
encrypted_checkpoint_artifact_prefix
recovery_policy
merge_policy
network_policy
canonical_output_schema_version
alias_output_schema_version
expected_outputs
scientific_output_manifest_schema_digest
scientific_output_hash_domain=gtbi-v7-scientific-output-v1
publication_attestation_chain_schema_digest
checkpoint_namespace
checkpoint_compact_environment_id
checkpoint_publish_environment_id
checkpoint_immutable_handoff_schema_digest
checkpoint_capability_separation_policy_digest
checkpoint_handoff_store_manifest_digest
checkpoint_handoff_store_iam_policy_digest
checkpoint_handoff_store_retention_cleanup_policy_digest
checkpoint_handoff_store_budget_receipt_digest
retention_policy_digest
privileged_app_inventory_digest
asset_read_app_id
asset_read_primary_installation_id
asset_read_mirror_installation_id
asset_read_permission_digest
asset_read_environment_id
primary_asset_publish_app_id
primary_asset_publish_installation_id
primary_asset_publish_permission_digest
mirror_asset_publish_app_id
mirror_asset_publish_installation_id
mirror_asset_publish_permission_digest
asset_primary_publish_environment_id
asset_mirror_publish_environment_id
app_installation_policy_digest
owner_app_installation_ceremony_receipt_set_digest
destination_app_installation_ceremony_receipt_set_digest
source_owner_app_installation_ceremony_receipt_digest
source_app_manager_ceremony_receipt_digest
destination_owner_app_installation_ceremony_receipt_digest
destination_app_manager_ceremony_receipt_digest
app_private_key_ceremony_receipt_set_digest
app_private_key_secure_import_policy_digest
app_private_key_import_receipt_schema_digest
app_private_key_residual_risk_acceptance_digest
activation_lease_policy_digest
activation_lease_schema_digest
source_activation_lease_registry_identity_digest
destination_activation_lease_registry_identity_digest
domain_terminal_manifest_schema_digest
joint_terminal_reconciliation_schema_digest
full_disposition_registry_identity_digest
initial_full_disposition_record_digest
disposition_decision_due_at_utc
disposition_escalation_policy_digest
initial_dispatch_boundary_state=pre_dispatch
initial_github_dispatch_ack_state=not_dispatched
post_dispatch_abort_preservation_policy_digest
abandoned_recovery_capsule_schema_digest
abandoned_recovery_only_policy_digest
financial_tail_reconciliation_policy_digest
financial_tail_due_at_utc
source_lease_reaper_workflow_digest
destination_lease_reaper_workflow_digest
source_deadman_deployment_digest
destination_deadman_deployment_digest
deadman_control_plane_manifest_set_digest
deadman_webhook_auth_policy_digest
deadman_backup_restore_failover_receipt_set_digest
deadman_campaign_teardown_manifest_set_digest
source_deadman_liveness_receipt_digest
destination_deadman_liveness_receipt_digest
deadman_and_reaper_key_broker_pair_policy_digest
deadman_and_reaper_broker_failure_domain_manifest_digest
single_broker_outage_cleanup_receipt_set_digest
webhook_hmac_custody_and_rotation_policy_digest
webhook_hmac_latest_rotation_test_receipt_digest
source_trusted_time_policy_digest
destination_trusted_time_policy_digest
source_trusted_time_liveness_receipt_digest
destination_trusted_time_liveness_receipt_digest
maximum_clock_skew_seconds=30
trusted_time_liveness_max_age_seconds=120
trusted_time_registry_schema_digest
trusted_time_restart_fail_closed_policy_digest
append_only_worm_policy_digest
append_only_worm_encryption_manifest_digest
append_only_worm_kms_deletion_protection_receipt_set_digest
append_only_worm_kms_admin_negative_test_receipt_set_digest
append_only_cross_domain_anchor_policy_digest
third_party_timestamp_transparency_policy_digest
latest_append_only_anchor_receipt_set_digest
append_only_admin_negative_test_receipt_set_digest
deadman_health_max_age_seconds
lease_cleanup_sla_seconds
managed_app_cleanup_key_pair_inventory_digest
managed_app_cleanup_key_pair_rotation_policy_digest
source_secret_controller_app_id
source_secret_controller_installation_id
source_secret_controller_permission_digest
source_environment_policy_controller_app_id
source_environment_policy_controller_installation_id
source_environment_policy_controller_permission_digest
lease_reaper_api_endpoint_allowlist_digest
disaster_copy_manifest_digest
destination_foundation_manifest_digest
platform_outage_archive_manifest_digest
platform_outage_archive_restore_receipt_digest
platform_outage_archive_compliance_lock_receipt_digest
platform_outage_archive_admin_negative_test_receipt_digest
platform_outage_archive_kms_policy_digest
platform_outage_archive_kms_deletion_protection_receipt_digest
platform_outage_archive_kms_admin_negative_test_receipt_digest
retention_funding_manifest_digest
recovery_objective_policy_digest
recovery_objective_latest_test_receipt_set_digest
final_pre_authorization_restore_receipt_digest
campaign_consumption_registry_policy_digest
campaign_consumption_registry_identity_digest
dispatch_preflight_receipt_schema_digest
dispatch_preflight_max_age_seconds
budget_schema_version
cost_reconciliation_ledger_schema_digest
campaign_cost_reconciliation_head_schema_digest
dispute_evidence_manifest_schema_digest
dispute_evidence_retention_deadline_policy_digest
dispute_evidence_budget_receipt_digest
resource_cleanup_state_schema_digest
initial_resource_cleanup_state=NOT_STARTED
budget_currency
max_total_cost_minor_units
max_compute_cost_minor_units
max_storage_cost_minor_units
max_transfer_cost_minor_units
max_packages_cost_minor_units
tax_and_fee_policy_digest
monetary_budget_safety_reserve_pct
max_initial_github_jobs
max_recovery_github_jobs
max_merge_github_jobs
max_control_publish_github_jobs
max_total_runner_minutes
max_recovery_runner_minutes
max_control_publish_runner_minutes
max_storage_bytes
max_transfer_bytes
max_technical_attempts_total
technical_capacity_safety_reserve_pct
budget_stop_policy
worst_case_job_reservation_policy_digest
```

`runbook_core_v1` uses `digest_storage=external_result`:
`runbook_core_digest =
HASH[GTBI_RUNBOOK_CORE_V1](typed runbook_core_v1 payload)`. The digest is not a
member of the payload and is stored by the authorization envelope, dispatch
capsule and approval receipts that consume the immutable core.

`selected_execution_mode_policy` is exactly
`immutable_per_job_profile_assignment_v1`; it is not one global A/B/C label.
`numerical_execution_profile_assignment_digest` resolves every planned job to
one approved profile before authorization, while
`max_effective_compute_threads_per_job` is the authorization ceiling across
those assignments. A worker with a different actual profile is inadmissible
unless the recovery protocol supplies the pre-authorized substitution receipt.

The immutable runbook core never stores a mutable current cleanup state. It
binds only `resource_cleanup_state_schema_digest` and the initial
`NOT_STARTED` value. Every later transition to `IN_PROGRESS`,
`RECONCILED_CLEAN` or `DISPUTED_CLEAN` is an event in the external append-only
resource-cleanup chain with sequence, previous-event digest, actor, evidence
and CAS version. Status views are derived from that chain and cannot rewrite
the core or final scientific package.
Each `resource_cleanup_event_v1` also binds schema version, campaign and
billing/resource-domain identity, previous/new state, expected CAS version,
trusted UTC, inventory/cleanup/negative-access receipt digests and
`event_digest` under `GTBI_RESOURCE_CLEANUP_EVENT_V1`, omitting only
`event_digest`.

The forward decision is exhaustive and exclusive. Exactly one branch is
present in the core:

```text
forward_enabled:
  proposal, locked-approval, owner-authorization and activation digests non-null
  attested_no_forward_decision_digest_or_null=null

forward_disabled:
  all four forward digests null
  attested_no_forward_decision_digest_or_null non-null
```

Any mixed, all-null or self-authorized combination blocks authorization.

`github_actions_acceptable_use_decision` must equal `approved`.
`github_actions_support_response_digest` is required when the independent
review classified any applicable term as ambiguous; otherwise it is explicitly
null. The terms and pricing snapshots must still be current at dispatch.

Each billing domain enforces integer minor units in its own frozen ISO 4217
currency; floating-point money is prohibited. `budget_currency` is only the
separate consolidated reporting/ceiling currency. The ordered pricing snapshot
set enumerates effective rates for each domain's exact plan, runner, storage,
Packages and transfer classes, tax/fee treatment, payer, source URL and
retrieval time. Preflight recomputes every category from the worst permitted
technical reservation, applies each domain's tax/fee and safety policy, then
uses the conservative frozen FX snapshot to prove both native and consolidated
limits:

```text
for every billing_domain:
  reserved_compute_native_minor <= max_compute_native_minor
  reserved_storage_native_minor <= max_storage_native_minor
  reserved_transfer_native_minor <= max_transfer_native_minor
  reserved_packages_native_minor <= max_packages_native_minor
  sum(reserved_category_native_minor) <= max_domain_total_native_minor
sum(conservative_fx(reserved_domain_native_minor))
  <= max_total_cost_minor_units in budget_currency
```

An unavailable rate, missing payer approval, currency conversion, changed
price, expired snapshot or fallback runner class aborts before capsule
consumption. Completion reconciles provider-billed and independently computed
costs by domain/category before consolidating them; one domain cannot borrow
from another. A technical-minute ceiling is never treated as a financial
ceiling.

`technical_capacity_safety_reserve_pct` applies only to runner minutes, job
count, bytes and request capacity:

```text
reserved_technical_capacity =
  ceil(worst_case_measured_capacity * (100 + technical_capacity_safety_reserve_pct) / 100)
```

Monetary safety is represented only by native-currency minor-unit caps and
their explicitly approved monetary reserve fields. CI rejects either reserve
being substituted for the other.

Provider billing may lag scientific completion. The immutable scientific
`summary.json` then uses
`cost_reconciliation_state=observed_pending_provider` and null provider-billed
fields; it is never rewritten later. The package's compatibility
`cost_reconciliation_report.json` is likewise a frozen closure-time snapshot,
not a mutable current index. An external append-only
cost-reconciliation ledger uses immutable, monotonically numbered objects
with exact filename
`cost_reconciliation_report.<20-digit zero-padded unsigned sequence>.json`,
starting at sequence zero, plus an atomically published content-addressed
`campaign_cost_reconciliation_head.json` index outside the
scientific package. No prior report or index version is overwritten. Each event
binds the campaign/result digest,
previous-event digest, sequence, state
`observed_pending_provider|reconciled|no_invoice_expected_clean|disputed`,
provider statement or authoritative final-usage evidence and
authenticated actor; the index binds the complete ordered chain and current
head. A conflicting sequence, missing predecessor or two heads is blocking.
Each `cost_reconciliation_event_v1` additionally binds schema version, billing
domain/currency, native and consolidated integer minor-unit amounts, pricing/
FX/tax policy digests, trusted UTC, actor attestation and `event_digest` under
`GTBI_COST_RECONCILIATION_EVENT_V1`, omitting only `event_digest`.
Unused monetary reservation is not released and overall project completion
cannot be claimed until the current head is `reconciled` or the frozen model's
validated `no_invoice_expected_clean`; scientific row
identity never depends on invoice timing.

Every billing-domain row freezes before dispatch one settlement model:
`INVOICE_EXPECTED`, `USAGE_EXPORT_IS_FINAL` or
`ZERO_CHARGE_NO_INVOICE_EXPECTED`, with provider terms evidence, statement lag,
authoritative usage endpoint, payer and dispute deadline. A successful branch
may reach `NO_INVOICE_EXPECTED_CLEAN` only for the latter two models after the
frozen lag plus safety margin, complete authenticated usage export, zero or
fully reserved/bounded observed charge, no open dispute, payer approval and
WORM evidence. This is a normal reconciled terminal subtype, not a waiver and
cannot be selected retrospectively. An `INVOICE_EXPECTED` row still requires
the final statement.

If a provider violates its frozen model and never supplies required evidence,
the controller may reach `terminal_financial_exception` only on an abandoned
or no-go branch after the frozen statement deadline, documented contact
attempts and escalation. It reserves the maximum remaining liability, exports
all evidence to WORM and requires joint licence/acceptable-use reviewer plus
payer approval. The normal successful branch permits only `reconciled` or the
pre-authorized `NO_INVOICE_EXPECTED_CLEAN`; every other pending/disputed domain
emits `CAMPAIGN_DISPUTED_CLEAN`, keeps `PREV7-0913` active, keeps G9 and G10 red
and retains the append-only reconciler.

For compatibility, `code_sha` must equal `canonical_code_sha`; it is never
interpreted as the disposable repository commit. `executed_ref_sha` must equal
`execution_repository_commit_sha`. The mapping manifest is a bijection for
copied files plus an explicit allowlist for generated execution-only files.

`max_initial_campaign_wall_minutes` is at most `1320`, but that ceiling is not
assumed to be the available time and is not a claim that the entire campaign
must finish in one authority generation. Immediately before atomically
consuming the capsule, preflight proves for the exact first authority segment:

```text
conservative_current_segment_wall_minutes
  + finalization_margin_minutes
  <= floor(
       (
         min(authorization_envelope_valid_until_utc,
             dispatch_capsule_valid_until_utc)
         - current_trusted_utc
         - maximum_clock_skew_seconds
       ) / 60
     )
```

The segment bound includes only operations assigned to the first immutable
authority-generation manifest plus its mandatory checkpoint/replication and
safe-stop finalizer. Separately, the runbook proves that the complete campaign
fits within its total budget and a frozen
`max_continuation_authority_generations`, with every remaining segment
individually bounded by the same 24-hour rule and no increase to scope or
ceilings. Merge, validation, publication and cleanup appear in the segment
where they are actually authorized, never all in the initial bound. The first
segment is also bounded by `max_initial_campaign_wall_minutes`. If either
inequality or the bounded-generation feasibility proof fails, preflight
aborts before reserving the campaign-consumption key and requires a newly
reviewed authorization envelope and destination-generated capsule. Expiry
stops new tokens and assignment; sealed work remains recoverable under a fresh
recovery/continuation authorization rather than silently extending the original
envelope.

Because the fixed campaign may legitimately outlive the maximum 24-hour
initial envelope, continuation is a complete protocol rather than an implied
exception. Before the active authority expires, or after expiry before any new
privileged operation, the same five independent approval roles may issue a
`continuation_authorization_envelope.json` for an immutable child generation.
It binds the original runbook core, original authorization envelope and
consumed dispatch capsule, exact current campaign-state head, exact remaining
planned job/unit/block/operation IDs, accepted checkpoint/result digests,
remaining attempt and native-currency budgets, current role/GitHub snapshots,
approved external-security configuration/transition-policy digests, current
signed external-security observation digest, new creation/expiry and previous authority-generation
digest. The independent destination copies/restores it and emits the
choice-free `continuation_operation_capsule.json`; one CAS consumption advances
the authority-generation head without creating a second campaign dispatch.

A continuation cannot add or remove scientific units, change assignment,
ordering semantics, code/runtime/data/pack/contract/policy/plan hashes, alter
filters or dates, reopen a terminal operation, increase any original ceiling,
or authorize work outside the exact remaining manifest. It may only reduce
remaining scope or budgets. Original capsule consumption remains the unique
initial-dispatch provenance. If the refresh is absent, expired, mismatched or
not independently synchronized, new tokens, assignment, checkpoint batches,
merges and publication stop; already sealed work is preserved. Recovery after
an exhausted attempt ceiling remains the distinct recovery-authorization
protocol and cannot be smuggled through continuation.

The runbook freezes the approved provider-limit, acceptable-use and pricing
policies. The same preflight queries a fresh current-state receipt from
GitHub's API and the versioned official terms/policy registry. It verifies that
the terms digest and acceptable-use decision still apply, then verifies matrix
expansion, job/workflow duration,
artifact count/size/retention, storage quota, API rate, concurrency, billing and
environment/deployment limits against the exact approved-visibility execution
repository, account and runner group. Every planned artifact class includes
compressed p99 bytes plus
safety reserve. A limit with no reliable API is verified by the current
documented policy and a bounded smoke. Current occupancy may reduce admitted
parallelism without changing science only within the runbook's frozen scheduler
rules; a changed term, provider limit, price, plan, visibility, runner class or policy
invalidates the current-state approval and requires review when it changes the
execution plan. Unknown, expired or exceeded limits abort before capsule
consumption.

Immediately before the destination registry CAS consumes the dispatch capsule,
the preflight also re-queries every source and destination external security
object represented by
`approved_external_security_configuration_digest`. Canonical equality of the
immutable configuration is mandatory. Dynamic App/lease/deadman/liveness/time
state is accepted only as a fresh, signed, monotonic
`current_external_security_observation_digest` whose chain starts at the
envelope's authorization observation and whose transitions are all permitted
by `approved_external_security_transition_policy_digest`. Unreachable, unknown,
stale, backwards, missing-predecessor, configuration-drifted or disallowed
state aborts before capsule consumption. This second query is not satisfied by
reusing the envelope-creation receipt.

Each admitted job performs a second local resource preflight before requesting
an asset/broker credential: expected runner identity, effective CPU quota,
usable memory and current free disk must match the runbook minimums. It records
initial/peak/final disk in telemetry and summary. Insufficient disk exits
without downloading data or consuming a scientific unit; it is a technical
capacity failure eligible only for the frozen recovery policy.

The runbook core contains immutable pre-core evidence-receipt digests, but no
post-core scientific, workflow, acceptable-use, security or owner authorization receipt.
It is hashed before those reviews. Scientific review, workflow review,
exact-workload acceptable-use review, deployed-security review and
repository-owner authorization each record that exact `runbook_core_digest`.
Any byte, input, budget or policy change creates a new core digest and
invalidates all five approvals.

### PREV7-0809: Exact-Workload Acceptable-Use Approval

The licence and acceptable-use reviewer independently restores the exact
runbook core and preliminary `PREV7-0309` decision. A protected check proves
that `reviewed_workload_digest` from the core is a subset of the approved
maximum envelope and matches every final repository, billing domain, plan,
visibility, runner class, job count, parallelism, duration, purpose, payload
class, storage/transfer class and retry ceiling. It rechecks current terms,
Support response when required, external-control-plane provider decisions and
pricing validity. It verifies the `PREV7-0815` provisioning cap and
`PREV7-0811` through `PREV7-0813` exact full receipts, including exactly-once
billing-domain coverage and adoption of every provisional charge.

Only an exact `approved` decision emits
`acceptable_use_approval_receipt.json`, bound to reviewer actor ID,
`runbook_core_digest`, `reviewed_workload_digest`, preliminary-decision digest,
GitHub terms/Support and external-control-plane terms digests, billing-domain
manifest, provisioning/full approval receipt-set digests, UTC creation/expiry
and current GitHub state. Any workload or terms difference requires a new preliminary
decision, core and all approvals.

After all five authenticated receipts exist, a protected workflow creates
`authorization_envelope.json` containing:

```text
schema_version
campaign_id
full_authorization_attempt_id
runbook_core_digest
scientific_approval_receipt_digest
workflow_approval_receipt_digest
acceptable_use_approval_receipt_digest
security_approval_receipt_digest
owner_full_authorization_receipt_digest
approval_receipt_set_digest
frozen_role_registry_digest
current_collaborator_role_snapshot_digest
current_ruleset_and_branch_protection_snapshot_digest
current_environment_protection_snapshot_digest
current_review_state_snapshot_digest
current_github_provider_state_snapshot_digest
approved_external_security_configuration_digest
approved_external_security_transition_policy_digest
authorization_external_security_observation_digest
fresh_vulnerability_scan_receipt_digest
created_at_utc
valid_until_utc
executed_ref_sha
canonical_code_sha
execution_repository_commit_sha
protected_full_tag
protected_execution_tag
```

The envelope is canonical JSON, content-addressed and immutable. Its
`valid_until_utc` is bounded by the earliest approval, role snapshot,
environment state, vulnerability database/report or App-key policy expiry.
It is additionally bounded to at most `24` hours after `created_at_utc`.
Verification permits at most the single frozen
`maximum_clock_skew_seconds=30` and never extends expiry. A later initial
dispatch requires a complete new envelope and capsule.
Creating it does not alter the runbook core or retroactively change what was
reviewed.
`PREV7-0804` closes only after initializing the permanent full-authorization
controller and proving its first `FULL_AUTH_ATTEMPT-n`; later expired,
invalidated or recovery authorizations create new immutable child generations
and never reopen the terminal readiness task.

G8 uses a two-phase transaction and never requires a capsule to bind a gate
event that the capsule itself is needed to create. `PREV7-0804` first creates
the envelope and becomes terminal under its normal dependencies. Once every G8
predicate except `PREV7-0807` is current, the gate controller emits immutable
`G8_PREAUTH_ATTEMPT-n` with its condition, evidence-bundle and chain-head
digests. It is not a green gate and authorizes no execution. The authorization
envelope is one input to that preauthorization identity.

After `PREV7-0807` has copied and independently restored that envelope, core and
evidence, its protected destination workflow freezes, attests and stores
`dispatch_capsule.json`; the source retains only an identical verified copy:

```text
schema_version
campaign_id
authorization_envelope_digest
g8_preauth_attempt_id
g8_preauth_condition_digest
g8_preauth_evidence_bundle_digest
g8_preauth_chain_head_digest
independent_disaster_sync_receipt_digest
executed_ref_sha
canonical_code_sha
execution_repository_commit_sha
protected_full_tag
protected_execution_tag
created_at_utc
valid_until_utc
```

The capsule adds no scientific or operational choice; its expiry cannot exceed
the envelope expiry or `created_at_utc + 24h`, with the same frozen
`maximum_clock_skew_seconds=30`. Changing the envelope, receipt, SHA or tag
creates a new capsule. The authoritative destination campaign-consumption registry enforces
one initial dispatch per capsule digest; the source mirrors its attested state.
The gate controller then atomically appends the `PREV7-0807` terminal receipt
and a final `G8_ATTEMPT-n` green event whose parent is the bound
`G8_PREAUTH_ATTEMPT-n`; the only permitted evidence delta is the exact
destination sync/capsule receipt set.
`PREV7-0806` verifies that final G8 event
is the deterministic child of the capsule-bound preauthorization and consumes
the capsule by CAS. Any intervening task, evidence, role, protection, security
configuration or disallowed observation change invalidates the transaction.

The approval workflow is:

1. `PREV7-0802` verifies the immutable runbook core and evidence, then waits on
   `gtbi-scientific-review`; only the registered scientific reviewer can
   approve it.
2. `PREV7-0803` independently verifies the same bytes, then waits on
   `gtbi-workflow-review`; only the distinct workflow reviewer can approve it.
3. `PREV7-0809` independently verifies the exact workload, preliminary terms/
   Support decision, pre-ID provisioning receipt and exact source/destination/
   consolidated full billing receipts, then publishes its protected
   acceptable-use receipt bound to the same core digest.
4. `PREV7-0816` independently verifies the deployed security state and
   publishes its protected receipt bound to the same core digest.
5. All four review jobs publish authenticated API-derived receipts bound to
   the exact core digest.
6. `PREV7-0804` verifies all four review receipts and waits on
   `gtbi-full-authorization`; only the
   repository owner, who is not any reviewer or the workflow initiator,
   authorizes that core digest.
7. Immediately before envelope creation, the protected job re-queries actor
   roles, current reviews, rulesets, branch and environment protection through
   GitHub's API, repeats the vulnerability scan using the approved scanner,
   policy and database rules, independently queries every source/destination
   external security domain named by
   `approved_external_security_configuration_digest`, and freezes its current
   signed observation chain. Exact configuration equality plus a fresh,
   monotonic observation reachable through the approved transition policy is
   required; unknown, unreachable, stale, backwards or disallowed state aborts.
8. Dismissal, role change, ruleset/environment change, external IAM/App/broker/
   key/lease/deadman/WORM/KMS/monitor change, evidence change,
   vulnerability-policy failure, expiry or runbook-core change invalidates the
   envelope before dispatch.
9. `PREV7-0807` independently copies/restores the authorization objects,
   issues the disaster-sync receipt and constructs, attests and stores the
   choice-free dispatch capsule. The source only verifies and mirrors those
   exact bytes.

`PREV7-0805` begins only after `PREV7-0808` has created the empty
approved-visibility repository and completed every owner installation
ceremony, `PREV7-0810` has already created the immutable execution commit,
`PREV7-0813` has consolidated exact full monetary approval and `PREV7-0310`
has restored those bytes independently. It verifies the immutable repository
ID, template/content digest, execution commit/tree/workflow-bundle/mapping,
environment policy, installation receipts, monetary receipts and
suspended/deny-all state. It creates no repository content and makes no
execution commit. Generated controller/template files already have their own
reviewed source and digest; any unmanifested or changed file is `NO-GO`.
While the repository still contains no scientific asset or run, protected
read-only verification rechecks every production source and destination-owned
installation for dispatch, checkpoint replication/publication, cleanup,
result-transport read, dependency extraction, merge, secret control and
environment-policy control.
It freezes each actual App/installation ID, selected-repository scope,
permission set, environment policy, suspension state and owner receipt in the
runbook core. No not-yet-existing installation ID is invented. The
transport-provisioning App and every campaign App remain suspended. No
scientific asset, activation token or lease-bound campaign secret enters the
repository before authorization and capsule consumption.

The same pre-core phase invokes a protected key-provision workflow that
asks each designated external non-exportable OIDC key broker/HSM to generate
fresh campaign merge, source checkpoint-recipient and source final-result-
recipient key pairs natively. Before either source operation, the workflow
consumes a fresh signed `source_key_broker_custodian` operation receipt bound
to the exact campaign, broker, requested key policy, OIDC subject, dual-control
witness, native-currency reservation and rollback/teardown manifest. Private
keys never cross the broker boundary or
use the App-key import ceremony; environments receive only workload-bound
broker routes. The public-key digests, recipient IDs, custody/expiry policy and
attested creation receipts enter the core. The independent destination
generates its own checkpoint and final-result recipient keys only after
consuming the equivalent fresh signed `destination_key_broker_custodian`
operation receipt, and returns only public material plus an attested custody
receipt. Both custodian receipts and their verified expiry/state-query receipts
are immutable runbook-core inputs; a generic owner, payer, App-manager or
earlier provisioning approval cannot substitute for either one. A failed or
abandoned core
may trigger key destruction only while the immutable dispatch boundary is
  `pre_dispatch` and a complete, dual-domain negative inventory proves that no
  ciphertext was created. After dispatch, execution routes are revoked but
  recipient keys and ciphertext remain until independent dual restore and the
  approved recovery/retention window complete; only then may a separately
  approved destruction manifest run. Every destruction is domain-local and
  emits a receipt chained into both WORM registries. No key can be silently
  reused by another campaign.

Also as part of `PREV7-0805`, verify from both workflow registries that creating
the planned tags cannot trigger an unapproved campaign. Create the previously
unused canonical authorization tag `gtbi-v7-full-<campaign_id>` at
`canonical_code_sha` and the disposable execution tag
`gtbi-v7-exec-<campaign_id>` at `execution_repository_commit_sha` under their
active tag rulesets, verify both through Git and the GitHub API, and only then
hash the runbook core. A tag-triggered workflow, movable tag or pre-existing tag
name blocks authorization.

Full dispatch runs from the canonical protected controller in
`gtbi-dispatch`. The controller sends the fixed-operation broker only the
reviewed workflow identity at `gtbi-v7-exec-<campaign_id>` and
`dispatch_capsule_digest`; the broker internally mints and retains the
short-lived dispatch-only App token, performs that one call and returns the run
identity plus receipt. The entry workflow aborts before asset access unless
that digest restores
the destination-owned sync receipt, exact immutable envelope and exact runbook
core. It re-queries the current roles, reviews, rulesets, branch/environment
protection and capsule/envelope expiry immediately before any credential or
private asset access; every value must match the frozen envelope and all
authenticated receipts.
`PREV7-0806` first re-evaluates the exact current G8 attempt ID, G8 condition
digest, evidence-bundle digest and gate-event head against the authorization
envelope. It then performs the single authoritative capsule-consumption/
dispatch-boundary compare-and-swap defined in section 10. Any stale gate,
different evidence, previously consumed capsule or ambiguous pre-dispatch
state aborts before asset access.
Every execution job requires
`GITHUB_SHA=execution_repository_commit_sha`, verifies the execution tree and
workflow-bundle digests, and verifies their frozen mapping to
`canonical_code_sha`; it never compares a commit from one repository directly
with a commit SHA from another. Workflow and registration digests, runner-image policy,
container, dependencies, data, strategy pack, contract, plans, dates, worker
topology, timeouts, budget, network, checkpoint, recovery, merge and retention
policies are all derived from and compared with the runbook core. Any extra
input or difference aborts. Moving or reusing that tag is forbidden.

This is not a one-time controller check. Every sensitive operation obtains a
single-use, short-lived `external_security_operation_lease` immediately before
its first privileged side effect. Sensitive operations include every token
mint or use, key-broker handoff, checkpoint seal/upload/replication, worker
private-asset read, block/superblock/final merge input read, result encryption,
publication and cleanup/revocation. The lease binds campaign and operation ID,
operation class, exact target resource IDs, authorization capsule/envelope
digests, GitHub authorization-state digest,
`approved_external_security_configuration_digest`,
`approved_external_security_transition_policy_digest`,
`current_external_security_observation_digest`, source receipts and
`max_external_security_snapshot_age_seconds`; it is consumed once and cannot
authorize another operation, retry or target.

The runbook freezes
`max_external_security_snapshot_age_seconds=300`. Age is measured using trusted
UTC from the oldest successful constituent query's completion to lease issue.
If constructing the snapshot exceeds that bound, every constituent query is
repeated; a mixture of individually fresh but temporally inconsistent receipts
is invalid.

Immediately before issuing the lease, the protected controller independently
re-queries every external IAM, account-root/payer, App/installation,
broker/key-policy, lease-registry ACL, deadman/reaper, WORM/KMS and monitor
object needed by that operation. Canonical equality of immutable configuration,
a complete allowed transition chain, observation freshness within the frozen
maximum age and reachability are mandatory.
Initial workers use the original capsule/envelope while current. Later
planned operations use the original digests as immutable dispatch provenance
plus the current consumed continuation generation. Recovery jobs preserve the
original and continuation-generation digests as immutable provenance but use
their current recovery capsule and recovery envelope. Drift, stale evidence or
an unreachable domain blocks the new operation and all new assignment/
publication.

An operation already inside its first privileged side effect may finish only
under its exact unexpired lease and only through the frozen atomicity policy:
either it publishes the fully sealed, digest-verifiable object and terminal
receipt, or its compensating action removes/revokes the partial object and
records failure. It cannot mint another token, open another target, begin a
second checkpoint batch or cross into a later merge/publication/cleanup phase
without a new full re-query and lease. Already validated checkpoints and
scientific outcomes remain immutable; authorization drift marks the campaign
technically incomplete rather than changing them.

Before dispatch, the planner atomically reserves the worst permitted
consumption of every admitted job from its timeout, maximum upload/download
bytes, storage retention and attempt allowance, plus the technical and
monetary safety percentages. It reserves both physical units and integer
minor-unit cost in each frozen category and total.
Only a fully covered batch can launch. Initial workers, control/publication,
merge and recovery have separate ceilings and reservations. Completion
reconciles actual billed/observed consumption and provider invoices against the
pricing snapshot, then releases only the unused reservation; another batch may
then be admitted. Running jobs are never relied
upon to stop at the exact instant a global counter is reached. If the next job
cannot be fully reserved, assignment stops, validated checkpoints flush, an
incomplete recovery manifest is written and no budget stop becomes a scientific
outcome.

## 20. Gate G9: After An Approved Full

### Verify

Check:

- requested units;
- loaded units;
- evaluated rows;
- early rejects;
- timeouts;
- unsupported;
- runtime errors;
- deduped mappings;
- duplicates;
- missing units;
- best candidate existence;
- locked boundaries;
- manifests and hashes.

### Preserve

Publish:

- final result package by digest;
- private mirror;
- independently administered GitHub disaster copy;
- destination-owned non-GitHub immutable platform-outage archive;
- manifests;
- attestations;
- telemetry;
- equivalence evidence;
- cost report;
- source and destination local terminal manifests, cleanup receipts and the
  joint reconciliation manifest when both domains are available;
- exact restoration instructions.

Primary and mirror publication is `PREV7-0902`. The independent destination
then pulls those immutable objects under `PREV7-0904`, verifies and restores
them into both its GitHub disaster repository and non-GitHub object-lock
archive with source write access absent, revokes temporary source read access
and issues its own attested completion receipt. It restores once with the
source organization denied and once with GitHub asset/package/release reads
denied. Source workflows never push or delete either independent final copy.

### PREV7-0903: V6 To V7 Cutover And Rollback Window

The transition registry permits only:

```text
V6_ACTIVE
  -> V7_PARALLEL
  -> V7_CANONICAL_V6_FROZEN
  -> V7_CANONICAL_V6_DISABLED
  -> V7_CANONICAL_V6_ARCHIVED
V7_PARALLEL | V7_CANONICAL_V6_FROZEN | V7_CANONICAL_V6_DISABLED
  -> V7_ROLLBACK_PENDING
  -> V6_REACTIVATED
V6_REACTIVATED
  -> V7_PARALLEL only through a new immutable V7 generation
```

`PREV7-0800` may reach only `V7_PARALLEL`. After `PREV7-0901`, `PREV7-0902`,
`PREV7-0904` and `PREV7-0905` verify the exact accepted V7 result, the repository
owner changes the canonical result/consumer registry to
`V7_CANONICAL_V6_FROZEN`. The receipt lists every consumer, V6 run still in
flight, workflow, schema mapping, owner and migration status. Existing V6 runs
finish under their old identity; their outputs never overwrite V7.

For at least 30 complete days, V6 workflows remain frozen and dispatch-disabled
but restorable. Monitoring compares consumer reads, output schemas, canonical
digests, alerts and rollback drills. A wrong V7 pointer, consumer breakage,
unexplained metric difference, restore failure or high/critical security
finding triggers a protected pointer rollback to the immutable V6 result and a
new incident; it never rewrites either result. Code rollback uses the exact
protected revert recipe from `PREV7-0800`. Scientific failure requires a new
campaign identity rather than relabelling V6 or V7 bytes.

Only after the observation window has no unresolved trigger, every consumer is
migrated or explicitly retired, all V6 runs are terminal and a clean restore
drill passes may the owner set `V7_CANONICAL_V6_DISABLED`, move retired YAML
outside `.github/workflows/`, and finally set
`V7_CANONICAL_V6_ARCHIVED`. The task receipt binds previous/current state,
canonical pointers, consumer registry, monitoring interval, rollback-drill
digest and approval. Skipping a state or lacking the tested revert keeps G9
red.

### PREV7-0905: Retire Disposable Campaign Transport

Immediately after `PREV7-0904` has proved independent restore, execute the
non-destructive security phase of the reviewed retirement manifest against the
immutable disposable repository ID. Its first CAS changes
`full_disposition=pending` to `completed`; failure of that transition stops the
task. The task itself is a resumable idempotent state machine:

```text
NOT_STARTED
  -> COMPLETION_CAS_COMMITTED
  -> SECURITY_RETIREMENT_IN_PROGRESS
  -> SECURITY_RETIRED
```

Every substep has a provider idempotency key, expected-before/accepted-after
state and immutable receipt. Restart resumes from the first unverified substep;
it never repeats the disposition CAS, invents success or leaves a successful
campaign in a non-resumable half-clean state. Then:

1. Stop every remaining dispatch and recovery lease.
2. The source reaper suspends source installations; the destination reaper
   independently suspends its replicator installation and emits the linked
   receipt. No source key performs a destination action.
3. Remove lease-bound environment secrets and restore deny-all policies.
4. Revoke campaign webhooks and token routes, disable external tenant actions,
   freeze the terminal lease/CAS registry and preserve source/destination API,
   run, usage, cost and security logs.
5. Verify source and independent-destination restore once more after revocation
   and emit `campaign_transport_security_retirement_receipt.json`.

No repository, package, checkpoint, billing evidence or external-control log is
deleted by `PREV7-0905`.

### PREV7-0906 And PREV7-0907: Delayed Physical Retirement

Physical retirement separates recoverability from invoice settlement. Deletion
of checkpoint-bearing storage still waits for the recovery predicates, but a
provider dispute can never force campaign repositories, tenants or other
billable execution resources to remain live after the evidence needed to prove
the dispute has been exported immutably:

```text
checkpoint_recovery_window_elapsed_days>=30
latest_source_restore=success
latest_destination_restore=success
audit_and_billing_evidence_preserved=true
canonical_result_recipient_keys_live>=2
provider_statements_and_usage_exported=true
dispute_evidence_manifest_digest!=null
```

If cost reconciliation is `reconciled`, cleanup records
`resource_cleanup_state=RECONCILED_CLEAN`. If it is `disputed`, the owner first freezes a
minimal, immutable, destination-restorable dispute evidence set, explicit
evidence-retention deadline and separately approved dispute-storage budget, then
retires every campaign repository, package, tenant, endpoint and temporary
storage that is not itself the sole retained evidence. It records
`resource_cleanup_state=DISPUTED_CLEAN`. This is an economic cleanup state, not
a scientific success or project-completion state. The append-only cost ledger
may later transition to `reconciled`; unresolved financial reconciliation still
blocks successful `COMPLETED_CLEAN`. It can contribute to
`ABANDONED_CLEAN` or `NO_GO_CLOSED` only through the explicitly approved
branch-limited `terminal_financial_exception`; it cannot prolong privileged
access or unbounded campaign billing.

`PREV7-0906` is destination-owned. It removes only destination campaign App
installations, webhooks, deadman/broker/registry campaign tenants, IAM bindings,
endpoints and alarms; destroys or rotates only campaign keys whose recovery
obligations ended; seals retained registry/log chains; proves absence of
destination access; and emits an independently attested destination retirement
receipt. Durable final/disaster copies and archival result keys remain under
their separate retention policy, including the non-GitHub object-lock archive.

In parallel after the shared `PREV7-0905` security receipt, `PREV7-0907` uses
the suspended selected-repository
`gtbi-repository-retire` App and cleanup identities constrained to the frozen
IDs to remove source campaign
installations, webhooks, external campaign tenants, temporary environments,
packages, expired checkpoints and the disposable repository. It never removes
canonical source, canonical assets, durable results, billing/audit evidence or
the independent copy. API and negative-access proofs confirm absence, and
`campaign_transport_physical_retirement_receipt.json` binds only the shared
security-retirement receipt plus source-local deleted immutable IDs, preserved-
evidence manifest, archival-key policy and source restore receipt. It never
waits for, embeds or authenticates the destination retirement receipt.
`PREV7-0913` alone binds and reconciles both sovereign receipts.

Failure at any phase leaves G9 red and triggers bounded remediation; it never
permits deletion of the canonical source, canonical assets, durable results or
independent copy.

### PREV7-0910 Through PREV7-0914: Abandoned-Full Cleanup And Reconciliation

If the controller atomically sets `full_disposition=abandoned`, no full task may
dispatch or continue provisioning. The controller has already verified the
distinct source/destination owner receipt set. `PREV7-0910` immediately
inventories all resources created since `PREV7-0814`, stops leases, and
permanently CAS-revokes every unconsumed capsule in its WORM consumption
registry before publishing the authenticated abandonment attestation. Capsule
objects and their revocation/tombstone receipts remain immutable provenance;
only secret key material may later be destroyed under its separate manifest.
Each custody domain's own deadman/reaper independently observes it through its
allowlisted attestation feed, suspends its own App installations, revokes its
own token routes and webhooks, restores local deny-all and terminalizes its
local lease registry. The repository owner cannot execute a destination action;
the independent destination owner signs that local receipt.

Key handling is selected from the immutable dispatch boundary. For
`abandoned_pre_dispatch`, each domain may destroy its own campaign keys only
after proving the complete inventory contains no ciphertext. For
`aborting_preserve`, each domain revokes key *use* by execution paths but
retains its own checkpoint/result recipient keys and all encrypted
checkpoints/results, manifests and receipts until complete inventory,
independent dual restore and the recovery window succeed. Only a later
destruction manifest may remove those keys. Fixtures cover abandonment while
workers run, after the first checkpoint, during block/final merge and before
final destination restore. Canonical code/assets, G7 evidence, required
audit/terms records and every billing record needed for reconciliation are
preserved in both branches.

`PREV7-0914` makes post-dispatch preservation executable. It is activated only
for `full_disposition=abandoned` with `dispatch_boundary_state=post_dispatch`
and consumes a new destination-generated, one-use recovery-only capsule and
fresh bounded source/destination recovery leases. Its allowlist permits only
inventory, authentication, decryption and restoration of already existing
manifest-bound ciphertext. It cannot evaluate a strategy, assign work, create a
scientific checkpoint, merge new results, rank, publish a result or resume the
aborted campaign. Source and destination independently restore and attest the
same available plaintext-set digest; missing or incomplete ciphertext remains
explicitly recorded rather than invented. The task revokes its leases and emits
the two restore receipts required by `PREV7-0911` and `PREV7-0912`. In the
pre-dispatch branch it is cancelled only after the no-ciphertext inventory
receipt proves there is nothing to restore.

`PREV7-0911` waits for destination negative-access/restore proof,
provider-backed usage records and applicable recovery predicates. The
destination owner exports the minimal immutable billing/dispute evidence set
and then removes only destination campaign repositories, temporary execution
storage and external-control tenants. A dispute produces
`resource_cleanup_state=DISPUTED_CLEAN` under the bounded evidence budget; it
does not retain those live resources. The owner seals its local terminal chain
and emits its independent receipt.

`PREV7-0912` independently verifies the same shared abandonment/recovery
predicates plus source negative-access, restore and provider-billing evidence;
it does not wait for or consume destination credentials. The source owner
removes only source campaign/G7 repositories, packages, temporary execution
storage and external-control tenants and seals the source chain. `PREV7-0913`
alone invokes the read-only joint reconciler after both independent receipts.
If either cost ledger remains disputed, the cleanup
receipt records `DISPUTED_CLEAN` and reserves maximum liability. No actor holds
credentials for both cleanup domains.

`PREV7-0913` is the single accountable financial tail controller for either
normal or abandoned cleanup. It always activates after the selected branch's
source/destination cleanup receipts. For the normal branch, `PREV7-0906` and
`PREV7-0907` are direct evidence while `PREV7-0911` and `PREV7-0912` are
satisfied by their exact substitution receipts. For abandonment the inverse
mapping applies. It owns any reconciliation due date, provider escalation,
bounded evidence budget and append-only statement ingestion. It cannot
recreate a campaign resource or alter the scientific package. For the normal
branch it becomes done only when every domain is `reconciled` or has the
pre-authorized settlement subtype `NO_INVOICE_EXPECTED_CLEAN`, and then alone
emits `CAMPAIGN_COMPLETED_CLEAN`; a disputed or pending domain emits the
nonterminal view `CAMPAIGN_DISPUTED_CLEAN`, leaves the task active and cannot
green G9 or G10. For the abandoned branch it becomes done when every domain is
reconciled or has reached the branch-limited approved
`terminal_financial_exception` with maximum liability reserved, then emits
`ABANDONED_CLEAN`. The normal clean receipt greens G9 but is not yet a terminal
project state because G10 remains. The abandoned receipt is project-terminal,
greens only `G9X` and is not green G8/G9/G10.

If the campaign instead reaches verified completion, `PREV7-0905`,
`PREV7-0906` and `PREV7-0907` satisfy the same immediate and delayed cleanup
obligations; `PREV7-0910`, `PREV7-0914`, `PREV7-0911` and `PREV7-0912` are
cancelled with those replacement receipt digests. If abandonment is selected,
each unexecuted full/G9 task is cancelled only with its task-specific,
non-circular `PREV7-0910`, `PREV7-0914`, `PREV7-0911` or `PREV7-0912`
substitution receipt from the frozen branch registry. The later
`ABANDONED_CLEAN` receipt only proves aggregate reconciliation and cannot
substitute for any task. A cancelled branch without every named alternative
completion is invalid.

### Retire Legacy

Only after final restoration succeeds:

1. Verify every registered consumer against the output migration map.
2. Disable new dispatches of replaced workflows without deleting history.
3. Observe a `30`-day rollback window with no unresolved consumer issue.
4. Move YAML to documentation archive.
5. Archive superseded branches.
6. Register redundant worktrees and copies as candidates for G10 quarantine;
   do not move or delete them in G9.
7. Let ephemeral Actions artifacts expire under frozen retention; delete only
   approved external checkpoint-object versions through the separate cleanup
   process.
8. Preserve scientific references permanently.

## 21. Gate G10: Repository-Wide Modernization

This work is required to complete the overall project cleanup, but it is not
allowed to contaminate the V6 performance critical path.

### PREV7-1001: Layout ADR

Document:

- current flat package mapping;
- stable public imports;
- desired ownership boundaries;
- migration stages;
- compatibility shims;
- rollback per stage.

### PREV7-1002: Staged Migration

Allowed order:

1. Verify that the GTBI extraction, wrapper conversion and compatibility shims
   delivered by `PREV7-0601`/`PREV7-0602` remain byte-identical to their
   accepted manifests; do not extract or move GTBI again here.
2. Inventory only non-GTBI package boundaries still requiring modernization.
3. Keep existing public imports working.
4. Move one non-GTBI ownership boundary and its tests per PR without changing
   test semantics.
5. Remove duplicate non-GTBI helpers only after equivalence proof.
6. Consider broader non-GTBI package movement only in separate PRs.

Never move every package in one PR.

Each migration PR must:

- change one ownership boundary;
- preserve public imports;
- pass full GitHub CI;
- include rollback;
- avoid scientific changes;
- avoid workflow cleanup in the same diff.

### PREV7-1003: Final Successful-Project Reconciliation

After `PREV7-1002`, an independent workflow reviewer verifies the exact
normal-branch `CAMPAIGN_COMPLETED_CLEAN` receipt, every other G10 task, the final
GitHub/local inventories, all destructive manifests, compatibility tests,
rollback paths and the absence of active references to removed locations. The
review is bound to one final commit and one complete evidence-bundle digest.

`PREV7-1003` cannot repair, reinterpret or waive a failed predicate. It either
emits the sole successful project-terminal receipt:

```text
terminal_output=COMPLETED_CLEAN
```

or leaves G10 red with exact blockers. This separates a cleanly closed
scientific campaign from completion of the broader repository project.

`PREV7-1003` first evaluates the following predicate set while its own task is
still `review`; the set deliberately excludes G10 and the task's not-yet-
created terminal receipt. If every predicate is true, one atomic transaction
appends the `PREV7-1003` success event, `COMPLETED_CLEAN` receipt and green G10
event with the same expected versions and evidence digest. A partial append or
version race fails closed and is retried through a new task attempt, never by
assuming its own output.

The pre-terminal G10 predicate set is:

- every approved redundant copy completed quarantine and second inventory;
- every destructive batch has its own immutable manifest, approval and
  reconciliation;
- the layout ADR is approved;
- staged migrations preserve public imports and pass GitHub CI;
- no active task, branch, worktree, consumer or rollback path references a
  removed location;
- the final GitHub inventory contains no unexplained duplicate, orphaned
  workflow or unknown canonical owner; local administrative state is either
  `reorganized_verified` or carries the explicit
  `unavailable_deferred_noncanonical` receipt proving that no canonical asset,
  authority, credential, workflow or GitHub-only execution depends on it.
  Reappearance of that laptop later triggers only its local cleanup chain and
  cannot invalidate scientific/project completion;
- the current `PREV7-1003` review attempt has verified this exact evidence set
  and the atomic terminal transaction remains admissible.

## 22. Exact Execution Order

The numbers express priority and dependency order, not global synchronization
barriers. A task starts as soon as its own matrix dependencies are green.
`PREV7-0000` is the sole bootstrap exception and must merge first so every
later action has a tracked task row, event chain and acceptance validator.
Preservation still does not wait for legacy-run cleanup. After the inventory,
`PREV7-0002`,
and read-only evidence discovery may run alongside the storage and final-result
preservation path without delaying it. `PREV7-0004` and `PREV7-0005` are not
completed until recovered bytes and private evidence are durably stored.

The following table is the sole normative priority assignment in this
document. A validator must parse comma-separated IDs, require every task-matrix
ID exactly once, reject unknown or duplicate IDs, require contiguous
`priority_step` values from 1 through 46 and reject any dependency assigned to
a later step than its dependent. Tasks in the same step may run concurrently
only when their individual dependency rows permit it.

| priority_step | primary_task_ids |
|---:|---|
| 1 | `PREV7-0000` |
| 2 | `PREV7-0012` |
| 3 | `PREV7-0001` |
| 4 | `PREV7-0009` |
| 5 | `PREV7-0006` |
| 6 | `PREV7-0010` |
| 7 | `PREV7-0007` |
| 8 | `PREV7-0008` |
| 9 | `PREV7-0003`, `PREV7-0004`, `PREV7-0005` |
| 10 | `PREV7-0002` |
| 11 | `PREV7-0011` |
| 12 | `PREV7-0101` |
| 13 | `PREV7-0102`, `PREV7-0103` |
| 14 | `PREV7-0201` |
| 15 | `PREV7-0204`, `PREV7-0210` |
| 16 | `PREV7-0202`, `PREV7-0205`, `PREV7-0206` |
| 17 | `PREV7-0301`, `PREV7-0302`, `PREV7-0303`, `PREV7-0304`, `PREV7-0305`, `PREV7-0306`, `PREV7-0307`, `PREV7-0309` |
| 18 | `PREV7-0400`, `PREV7-0401`, `PREV7-0402`, `PREV7-0403`, `PREV7-0404`, `PREV7-0405` |
| 19 | `PREV7-0502` |
| 20 | `PREV7-0501` |
| 21 | `PREV7-0503`, `PREV7-0504`, `PREV7-0505`, `PREV7-0506`, `PREV7-0507`, `PREV7-0508`, `PREV7-0509` |
| 22 | `PREV7-0601`, `PREV7-0602`, `PREV7-0603`, `PREV7-0604`, `PREV7-0605`, `PREV7-0606`, `PREV7-0607`, `PREV7-0608`, `PREV7-0609` |
| 23 | `PREV7-0701` |
| 24 | `PREV7-0203`, `PREV7-0207`, `PREV7-0208`, `PREV7-0209`, `PREV7-0308` |
| 25 | `PREV7-0610`, `PREV7-0611` |
| 26 | `PREV7-0711`, `PREV7-0710`, `PREV7-0712`, `PREV7-0713`, `PREV7-0715` |
| 27 | `PREV7-0702`, `PREV7-0703`, `PREV7-0704`, `PREV7-0705`, `PREV7-0706`, `PREV7-0707`, `PREV7-0708`, `PREV7-0714` |
| 28 | `PREV7-0814`, `PREV7-0910`, `PREV7-0914`, `PREV7-0911`, `PREV7-0912` |
| 29 | `PREV7-0800` |
| 30 | `PREV7-0815`, `PREV7-0808` |
| 31 | `PREV7-0810` |
| 32 | `PREV7-0811`, `PREV7-0812`, `PREV7-0813` |
| 33 | `PREV7-0310` |
| 34 | `PREV7-0801` |
| 35 | `PREV7-0805` |
| 36 | `PREV7-0802`, `PREV7-0803` |
| 37 | `PREV7-0809`, `PREV7-0816` |
| 38 | `PREV7-0804` |
| 39 | `PREV7-0807` |
| 40 | `PREV7-0806` |
| 41 | `PREV7-0901`, `PREV7-0902`, `PREV7-0904`, `PREV7-0905` |
| 42 | `PREV7-0903`, `PREV7-0906`, `PREV7-0907` |
| 43 | `PREV7-0913` |
| 44 | `PREV7-0406`, `PREV7-0407` |
| 45 | `PREV7-1001`, `PREV7-1002` |
| 46 | `PREV7-1003` |

The numbered explanation below is non-normative. It expands the purpose and
conditional behavior of the matching priority step; task IDs inside its prose
do not create or alter an assignment.

```text
1. PREV7-0000 publish the master plan, initial operational records and validators from fetched origin/main
2. PREV7-0012 immediately arm the pre-provisioned external non-scientific
   bootstrap-preservation guard,
   monitor it until PREV7-0003 dual restore and execute automatically on lost margin
3. PREV7-0001 regenerate inventory
4. PREV7-0009 adopt and validate the provisional emergency App-manager/key-
   broker custody before any post-foundation credential
5. PREV7-0006 bootstrap emergency private storage and migrate/anchor provisional events
6. PREV7-0010 deploy the full readiness-state controller and disable provisional publication
7. PREV7-0007 configure short-lived private authentication under joint custody
8. PREV7-0008 register the fail-closed preservation and restore workflows on main
9. PREV7-0003 preserve V6 final result before expiry; PREV7-0004 preserve locked
   evidence and PREV7-0005 classify/preserve the V6 dependency chain as soon as
   their common prerequisites are ready
10. PREV7-0002 resolves legacy queued runs in parallel after PREV7-0001 and never
   blocks steps 4 through 9
11. PREV7-0011 remains live as the conditional bootstrap no-go closer and is
    cancelled only atomically with G0 green
12. PREV7-0101 record the unified V7 target
13. PREV7-0102 and PREV7-0103 freeze V7 identity and scope
14. PREV7-0201 freeze the complete role registry, incompatibilities and
    privileged-human authentication/recovery, or record the blocker
15. PREV7-0204 define production Apps and exact installation requests, then
    PREV7-0210 performs owner-authorized installations/environments with locked
    access disabled
16. PREV7-0202, PREV7-0205 and PREV7-0206 establish minimum governance and security
17. PREV7-0301 through PREV7-0307 establish durable provenance and the snapshot
    decision; PREV7-0309 approves the preliminary Actions/price envelope
18. PREV7-0400 through PREV7-0405 complete inventory and establish the repository baseline
19. PREV7-0502 resolve or replace PR 20
20. PREV7-0501 create the clean branch from freshly fetched origin/main containing
    or postdating the exact PR-20 disposition
21. Only after G1B is actually green, not merely blocked/reported,
    PREV7-0503 through PREV7-0509 freeze science, schemas, oracles, consumers and
    the permanent remediation controller
22. PREV7-0601 through PREV7-0609 implement equivalent V7 performance
23. PREV7-0701 immediately runs credential-free synthetic CI over that
    implementation, before external deadman or G7 infrastructure is admitted
24. PREV7-0203, PREV7-0207, PREV7-0208 and PREV7-0209 activate independent
    review, final protection, disaster-copy ownership and threat-model
    acceptance; PREV7-0308 creates the destination foundation
25. PREV7-0610 and PREV7-0611 deploy/restore both independent deadman control
    planes
26. PREV7-0711 creates the G7 validation repository,
    PREV7-0710/PREV7-0712 separately approve source and destination billing
    domains, PREV7-0713 proves complete, non-duplicated coverage, and
    PREV7-0715 opens the immutable G7 attempt generation
27. PREV7-0702 through PREV7-0706 prove real-data equivalence, worker scaling,
    recovery, merge and fault behavior only after those reservations;
    PREV7-0707 and PREV7-0708 prove capacity and full-scale transport/recovery;
    on success, failure or abandonment, PREV7-0714 revokes every smoke-only
    access path and applies deny-all
28. PREV7-0814 initializes the immutable full-disposition controller; if the
    project stops here or later, PREV7-0910, PREV7-0914 and PREV7-0911 through
    PREV7-0913 provide the
    executable `ABANDONED_CLEAN` route
29. On the normal branch, PREV7-0800 merges V7 by protected PR, creates a fresh
    G7 attempt for the exact merged main SHA, revalidates it and closes that
    generation's cleanup
30. PREV7-0815 authorizes only capped pre-ID provisioning; PREV7-0808 creates
    the disposable campaign repository and completes source/destination
    App-installation ceremonies
31. PREV7-0810 creates and verifies the exact immutable execution commit
32. PREV7-0811 and PREV7-0812 authorize exact source/destination full costs;
    PREV7-0813 proves complete, non-duplicated billing coverage and reservation
33. PREV7-0310 copies that exact execution commit and every other final pre-
    authorization dependency to the independent destination and proves total-
    primary-loss restore
34. PREV7-0801 creates the evidence bundle, including those immutable
    installation receipts
35. PREV7-0805 verifies those existing resources, provisions campaign recipient
    keys and hashes the immutable proposed full-run runbook core
36. PREV7-0802 and PREV7-0803 review and approve that exact runbook-core digest
37. PREV7-0809 approves acceptable use and PREV7-0816 approves the deployed
    security state for the exact final workload/core digest
38. PREV7-0804 obtains repository-owner authorization and freezes the current authorization envelope
39. PREV7-0807 independently copies and restores authorization evidence, then freezes the dispatch capsule
40. PREV7-0806 executes only from that dispatch capsule, authorization envelope and immutable runbook core
41. PREV7-0901, PREV7-0902 and PREV7-0904 verify and preserve independently;
    PREV7-0905 immediately revokes access and applies deny-all
42. After PREV7-0905, PREV7-0903's legacy rollback window runs in parallel with
    the recovery/cost-retention window; when its predicates pass, PREV7-0906 and
    PREV7-0907 physically retire destination/source campaign control planes and
    disposable transport
43. PREV7-0913 verifies selected-branch substitution receipts; it emits
    `CAMPAIGN_COMPLETED_CLEAN` on the normal branch only after every financial
    domain reconciles, otherwise remains active as `CAMPAIGN_DISPUTED_CLEAN`;
    abandonment may close through the bounded exception and emit terminal
    `ABANDONED_CLEAN`
44. PREV7-0406 and PREV7-0407 quarantine and delete only approved redundant copies
45. PREV7-1001 and PREV7-1002 continue broad modernization
46. PREV7-1003 independently reconciles successful-project evidence and alone
    emits project-terminal `COMPLETED_CLEAN`
```

## 23. Go Or No-Go Rules

Immediate `NO-GO` conditions:

- master plan not tracked from the latest `origin/main`;
- V6 artifact not preserved before expiry;
- V7 identity ADR not merged;
- exact scientific contract missing;
- semantic oracle lacks 100% effective-branch coverage or leaves a non-
  equivalent frozen mutant alive;
- input data identity unknown;
- on the historical V6-equivalent lineage, `reuse_recovered_v6_inputs` is not
  true or Oracle B is unavailable/mismatched; on the canonical-successor
  lineage, the owner authorization, frozen campaign identity, complete terminal
  accounting or explicit non-equivalence limitations are missing;
- private storage unavailable;
- private storage authentication not proven;
- licence decision missing;
- GitHub Actions acceptable use denied, ambiguous, expired or not approved for
  the exact workload, visibility, account and runner topology;
- GitHub-hosted plaintext processing denied, ambiguous or not approved for
  every licensed input mounted by the workflow;
- external deadman/key-broker/registry/monitor/log provider terms, region,
  metadata handling or pricing is denied, ambiguous, expired or unapproved;
- non-GitHub platform-outage storage licence, jurisdiction, object-lock,
  encryption, deletion or pricing decision is denied, ambiguous, expired or
  unapproved;
- public ciphertext transport unapproved without a fully revalidated private
  four-CPU larger-runner replacement;
- GitHub protection would deadlock;
- historical worker pack contains any observation after `2020-12-31`;
- adjustment temporal mode, source-event cutoff, data vintage or corporate-
  action knowledge manifest is missing, internally inconsistent or paired with
  a stronger point-in-time claim than its evidence permits;
- cross-market decision cutoff/availability policy is missing, an as-of join
  consumes a later observation, or V6 calendar-date contamination is presented
  as causal;
- in `point_in_time` mode, any universe/listing/delisting/eligibility/market-cap
  fact lacks effective or availability timestamps, is consumed after its
  decision cutoff, or the aggregate causal claim is true with a false/unknown
  conjunct; in `static_post_period` mode, missing historical availability is
  allowed only as `unknown_unverifiable` with exact static-universe identity,
  `survivorship_biased_reference` classification and every point-in-time,
  causal-universe and survivorship-free claim false;
- locked boundary can be bypassed;
- reference executable identity or isolation evidence is incomplete, or the
  reference imports any optimized result-producing module;
- canonical serialization profile or hash-domain registry is missing,
  ambiguous or mismatched;
- scientific numerical semantics or its equal compatibility alias is missing
  or differs across runbook, worker, checkpoint, reconstruction, merge or final
  result;
- an actual numerical execution profile is absent from the frozen approved
  registry, differs from its immutable job assignment without an approved
  substitution receipt, exceeds its thread/process ceiling, or produces
  non-byte-identical scientific output;
- the final numerical-execution or observed-hardware profile map omits,
  duplicates or misassigns a planned job;
- observed hardware is outside the frozen equivalent-profile registry, or
  physical CPU identity is incorrectly required to be identical instead of
  separately attested;
- ordinary GitHub-hosted execution lacks explicit provider-host TCB acceptance,
  claims guest isolation protects against a malicious host, or a required
  confidential-compute path releases a key without exact measurement
  attestation;
- optimized output differs from reference;
- physical tiling omits, duplicates, overlaps or misroutes any canonical-unit/
  symbol-partition pair, changes V6 symbol/trade order, terminalizes a partial
  candidate or leaves any scientific fragment unresolved at package closure;
- recovery loses, duplicates or misattributes any work identity, attempt,
  candidate-symbol pair or reduction node;
- source or destination reaper, lease-generation or owner-installation evidence
  is missing or stale;
- either external deadman deployment, operator/deputy, broker, registry,
  webhook-auth, restore/failover, liveness, billing or teardown evidence is
  missing, stale or drifted;
- a managed App lacks distinct deadman/reaper key objects and broker failure
  domains, either single-broker outage test fails, or both cleanup paths depend
  on one provider/account/region/IAM authority;
- App private-key ceremony evidence is stale, an unmanifested or unauthorized
  replacement key is observed or the residual unobservable-key risk lacks
  explicit acceptance;
- any production App has standing delegated human manager access, its just-in-time
  two-approver lease/WORM audit/zero-access close receipt is absent, or the
  installation owner cannot independently uninstall it;
- an App private key traverses an ordinary laptop, clipboard, synchronized or
  persistent filesystem, backup, reusable session or any path other than the
  selected direct import or attested ephemeral-workstation ceremony;
- any long-lived App, checkpoint, merge or result-recipient private key exists
  in a GitHub secret/environment or is returned by its broker, or any workflow,
  environment, host, container, deadman/reaper client can request or receive a
  JWT, installation token or arbitrary API action;
- a campaign checkpoint/merge/result private key is generated outside its
  owning broker/HSM or traverses Actions;
- active current-generation jobs cannot be normally cancelled and then
  force-cancelled through the two disjoint run-control brokers, or retirement
  occurs before every job is terminal/token-expired and negative access passes;
- any public/private evidence intake or restored private evidence lacks a
  passing secret scan, any secret alert remains unresolved, or a confirmed
  secret lacks revocation/rotation evidence;
- a broker-client job is absent from the frozen OIDC registry, signature/JWKS/
  TLS verification or any required claim/nonce/CAS check is missing,
  stale or replayable, or `id-token: write` is granted outside that registry;
- an ephemeral data key traverses argv, environment, workflow output, log,
  persistent disk, swap or core dump, or its sealed-memory one-use handoff and
  destruction receipt are missing;
- either domain's trusted-time attestation is stale, unavailable, rolled back
  or outside the approved skew at signing, activation or renewal;
- any append-only event/head/anchor is mutable, lacks provider-enforced
  retention or a current cross-domain/third-party anchor, or an administrator
  can replace the chain without detection from the accepted anchor;
- either local terminal lease state lacks its own authoritative CAS terminal
  manifest, has conflicting local heads or is altered by the opposite domain;
- joint terminal reconciliation, when both local records are available, does
  not bind the exact two locally verified cleanup receipts;
- current pricing differs from the approved snapshot, or the worst-case
  monetary reservation exceeds any category or total budget;
- pre-ID campaign provisioning lacks its three-role capped receipt, exceeds
  that cap or is not reconciled exactly once into the full billing sets;
- any checkpoint or sole recovery-bearing payload is physically deleted before
  the 30-day recovery window and dual restore complete, or billing/dispute
  evidence is deleted before its immutable retention rule permits it;
- a billing dispute is used to retain a live campaign repository, App,
  endpoint, control-plane tenant or unbounded temporary storage after the
  minimal immutable evidence set has been exported and the bounded dispute
  budget/deadline applies;
- a `DISPUTED_CLEAN` state lacks an active `PREV7-0913` owner, due date,
  escalation path or bounded evidence budget;
- a full-specific resource exists without the disposition controller, or an
  abandoned campaign has not reached `ABANDONED_CLEAN`;
- the exact deployed security state lacks a current independent
  `PREV7-0816` approval bound to the runbook-core digest;
- a joint abandonment transition lacks distinct source- and destination-owner
  receipts, or one domain treats the other domain's intent as local destructive
  authority;
- an abandonment decision has no immutable due time/escalation chain, a local
  domain stays privileged after that deadline, or post-dispatch abort destroys
  a recipient key/ciphertext before inventory, dual restore and recovery-window
  completion;
- post-dispatch abandonment lacks a fresh recovery-only capsule and dual restore
  receipts from `PREV7-0914`, or that task can evaluate, assign, merge, rank or
  publish;
- any job, environment, reusable runner, actor session or writable handoff
  combines checkpoint-recipient private-key/data-key access with checkpoint-
  namespace publication capability;
- the checkpoint compact/publish handoff lacks a frozen content-addressed
  write-once store, one-object PUT/GET separation, retention, budget or cleanup
  receipt;
- the non-GitHub archive is not in provider-enforced compliance mode, lacks a
  frozen retain-until/legal-hold policy, or a destination administrator can
  overwrite, delete, purge versions, remove the lock or shorten retention;
- a customer-managed archive SSE/KMS key lacks a retained immutable version,
  deletion protection, independent administrator and passing disable/delete/
  retention-shortening negative test through every protected object lifetime;
- any durable asset lacks a current funded retention period, named payer,
  quarterly review,
  `migration_lead_time_days>=minimum_required_migration_lead_time_days` with
  current `migration_duration_evidence_digest`, or
  latest passing restore receipt, or an RPO/RTO breach remains unresolved;
- final merge counts do not equal actual rows;
- V7 code merge changes a canonical product pointer, the V6/V7 transition skips
  a state, any consumer/in-flight V6 run is unaccounted for, or the protected
  V6 pointer/code rollback drill is missing or stale;
- the closed result package contains or is rewritten with a later validation,
  publication, restore, cleanup or invoice event, or its best/equivalence
  science lacks the normalized `scientific_output_digest`;
- a GitHub raw status/conclusion is dropped or mapped to success by default;
- a terminal task reopens, a retry lacks a new immutable attempt ID, or a G7
  generation reuses a prior attempt's authorization, key, lease or budget;
- canonical and alias accounting equations fail;
- any unsupported unit exists in the 72,000-pack baseline;
- any unsupported unit lacks prior approval;
- best candidate does not exist in leaderboard;
- a required workflow uses a mutable Action tag;
- a container base or runtime image is referenced by mutable tag;
- an archive or downloaded asset requires executable deserialization;
- canonical runtime image is not pinned by digest;
- any full input differs from the approved manifest.

`FULL GO` requires `G0`, `G1A`, `G1B`, `G2`, `G3A`, `G3B`, `G4`, `G5`,
`G6A`, `G6B`, `G7` and `G8` to be green. G9 verifies and preserves the approved full; G10 is
then required for total project-cleanup completion.

## 24. Completion Definition

There are three valid terminal project states:

```text
COMPLETED_CLEAN:
  G0,G1A,G1B,G2,G3A,G3B,G4,G5,G6A,G6B,G7,G8,G9,G10 green
  active_generation=GTBI_V7_CANONICAL_SUCCESSOR_1
  V6 remains historical_reference_only and NO_GO_CLOSED
  full_disposition=completed
  normal G9 cleanup receipts verified
  PREV7-0913 done and terminal_output=CAMPAIGN_COMPLETED_CLEAN
  PREV7-1003 done and terminal_output=COMPLETED_CLEAN

ABANDONED_CLEAN:
  full_disposition=abandoned
  G9X green; G8,G9,G10 remain red
  no successful full scientific result claimed; any post-dispatch work is
  explicitly recorded as an aborted partial execution
  PREV7-0910, PREV7-0914, PREV7-0911 and PREV7-0912 verified
  PREV7-0913 done and terminal_output=ABANDONED_CLEAN
  source and destination cost ledgers reconciled or closed through approved
  terminal_financial_exception with maximum liability reserved
  every created campaign resource absent or retained only by an approved
  immutable audit/retention rule

NO_GO_CLOSED:
  PREV7-0000 done
  G0 green OR authenticated_G0_failure_receipt with PREV7-0011 close receipt
  no successful G7 or full scientific result claimed
  exact NO_GO_CLOSE-n controller receipt verified
  every resource created before the no-go absent or retained only by an
  approved immutable evidence/retention rule
  every cost domain reconciled or bounded by terminal_financial_exception
```

`CAMPAIGN_DISPUTED_CLEAN` is deliberately absent from that list. It is a
resource-clean, financially unresolved campaign state with an active
reconciler, not a terminal project state and not permission to green G9/G10.
`ABANDONED_CLEAN` is a safe closed project, not scientific completion and not
green G8/G9/G10. It cannot be described as a successful full.
`NO_GO_CLOSED` is likewise safe operational closure, not readiness,
equivalence, validation or scientific success.

The GTBI V7 master readiness, performance and reorganization project is
complete only when G10 is green and:

- V6 evidence is durably preserved and restorable;
- reproducibility limitations are stated exactly;
- the unified GTBI V7 product is approved;
- GitHub is canonical and protected without deadlock;
- the laptop cannot produce canonical research results;
- local worktrees are inventoried and safe;
- data, packs and results are content-addressed;
- dependencies and final results restore from the destination-owned non-GitHub
  immutable archive with GitHub asset reads denied;
- GTBI is modular without a repository-wide high-risk rewrite;
- four CPUs per eligible runner are used only after measured equivalence;
- recovery and merge are deterministic;
- source and destination campaign deadman tenants, webhooks, IAM, broker keys
  and endpoints are independently retired after their retention predicates;
- every billing domain and consolidated monetary budget is reconciled or has
  the pre-authorized `NO_INVOICE_EXPECTED_CLEAN` terminal subtype;
  the terminal financial exception is confined to `ABANDONED_CLEAN` or
  `NO_GO_CLOSED` and can never satisfy successful G10 completion;
- `PREV7-0913` is done;
- `PREV7-1003` is done and its final project receipt verifies;
- locked data cannot be opened by ordinary workflow dispatch;
- every task has evidence, owner, status and dependency;
- a full remains impossible without explicit authorization.

At the current proposed-document state:

```text
IMPLEMENTATION_STATUS=NO-GO
SMOKE_STATUS=NO-GO
FULL_STATUS=NO-GO
FULL_RUN_AUTHORIZED=false
LOCKED_ACCESS_AUTHORIZED=false
```

These statuses advance without circularity only through the task and gate
records:

```text
implementation_ready:
  G0,G1A,G3A,G2,G4,G5 green
  and the exact applicable task selected from PREV7-0601 through PREV7-0609
  is ready

synthetic_ci_ready:
  registered reviewed workflow
  synthetic fixtures only
  no private or locked credential

non_locked_smoke_ready:
  required tasks selected from PREV7-0601 through PREV7-0609 merged on their
  reviewed branches
  exact applicable prerequisites among G0,G1A,G3A,G2,G4,G5,G6A,G3B,G6B green
  exact smoke task ready
  historical execution pack max date <= 2020-12-31

full_ready:
  G0,G1A,G1B,G2,G3A,G3B,G4,G5,G6A,G6B,G7,G8 green
  exact immutable runbook core, current authenticated authorization envelope,
  independent disaster-sync receipt and dispatch capsule valid

forward_locked_ready:
  separate future-forward contract, manifest, environment and independent
  locked approval; never implied by historical V7 completion
```

Changing a status requires a recorded task transition and evidence. This plan
alone authorizes none of them.

## 25. Explicit Non-Goals

V7 will not:

- increase threads without measurement;
- combine four processes with four symbol threads;
- create one GitHub job per tiny unit;
- reinstall the environment per unit;
- repeatedly download the same data within a job;
- pickle large DataFrames between workers when mapped arrays are available;
- introduce approximate scientific rejection;
- infer strategy-quality failure from timeout or runtime error; the deprecated
  compatibility-only `total_strategies_failed` operational aggregate remains
  separately defined and cannot support a scientific claim;
- rerun a full campaign to repair merge or publication;
- compare performance using different batches;
- claim four CPUs are used without telemetry;
- mix Clean Portfolio research into the V6-equivalent engine;
- move all Aurora packages in one pull request;
- open historical or new locked data during implementation.

## 26. Technical References

- GitHub-hosted runners:
  <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>
- GitHub-hosted larger runners:
  <https://docs.github.com/en/actions/reference/runners/larger-runners>
- GitHub Actions limits:
  <https://docs.github.com/en/actions/reference/limits>
- Official `actions/upload-artifact` limits and compression controls:
  <https://github.com/actions/upload-artifact#limitations>
- GitHub terms for additional products and features, including Actions:
  <https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features>
- GitHub Release asset limits:
  <https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases>
- GitHub Container Registry:
  <https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry>
- GitHub App installation authentication:
  <https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation>
- GitHub App permission reference:
  <https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps>
- GitHub App private-key management and platform limits:
  <https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps>
- Suspending a GitHub App installation:
  <https://docs.github.com/en/apps/maintaining-github-apps/suspending-a-github-app-installation>
- Workflow concurrency, including the current `queue: max` limit/compatibility
  rules revalidated at implementation and dispatch time:
  <https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency>
- Workflow-run and job status/conclusion APIs, revalidated when the normalization
  registry is frozen:
  <https://docs.github.com/en/rest/actions/workflow-runs>
- Deployment environments:
  <https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments>
- Artifact attestations:
  <https://docs.github.com/en/actions/concepts/security/artifact-attestations>
- GitHub Actions OpenID Connect claims and subject customization:
  <https://docs.github.com/en/actions/reference/security/oidc>
- RFC 8785 JSON Canonicalization Scheme:
  <https://www.rfc-editor.org/rfc/rfc8785>
- Python `concurrent.futures`:
  <https://docs.python.org/3/library/concurrent.futures.html>
- Python `multiprocessing`:
  <https://docs.python.org/3/library/multiprocessing.html>
- Python `os.memfd_create`:
  <https://docs.python.org/3/library/os.html#os.memfd_create>
- NumPy thread safety:
  <https://numpy.org/doc/stable/reference/thread_safety.html>
- PyArrow CPU and I/O thread-pool controls:
  <https://arrow.apache.org/docs/python/api/misc.html>
- Joblib thread control:
  <https://joblib.readthedocs.io/en/latest/user_guide/parallel.html>

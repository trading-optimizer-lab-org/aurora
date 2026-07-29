# ADR 0003: GTBI V7 Identity

Status: `PROPOSED_BLOCKED_BY_G0`

Decision owner: repository owner

Prepared by: implementer

Formal task: `PREV7-0102`

## Context

The repository owner requested one unified plan covering the GTBI V7
performance engine and the preparation, preservation, governance and cleanup
needed to make that engine trustworthy.

The current scientific reference is GTBI Fast Strict V6. V7 is an execution
and operational-quality project. It is not permission to alter the strategy,
the data boundaries, the ranking, the filters or the locked period.

## Identity

```text
product=GTBI V7 Performance Engine
reference_engine=GTBI Fast Strict V6
clean_portfolio_in_scope=false
scientific_change_allowed=false
full_run_authorized=false
```

## Decision

GTBI V7 will preserve the effective scientific behaviour of GTBI Fast Strict
V6 while improving execution speed, resource use, resumability, evidence,
recovery and reproducibility.

The following are in scope:

- GitHub-only scientific execution;
- exact V6 scientific equivalence;
- measured use of the four available runner CPUs;
- deterministic one, two and four worker execution;
- reusable features and computations;
- safe deduplication;
- cost and memory-aware scheduling;
- efficient checkpoints, artifacts and hierarchical merges;
- selective recovery;
- runtime and scientific diagnostics;
- repository, workflow and evidence governance required by the master plan.

The following are out of scope:

- changing entry or exit economics;
- changing train, validation or locked boundaries;
- using observations from `2021-01-01` onward in train or validation;
- relaxing final filters or changing the final ranking;
- converting the work into Clean Portfolio V7;
- treating a newly produced baseline as a substitute for the exact V6
  reference;
- authorizing a smoke, campaign or full run through this ADR;
- accepting local research output as canonical evidence.

## Immutable Boundaries

```text
train_end=2010-12-31
validation_start=2011-01-01
validation_end=2020-12-31
historical_exclusion_start=2021-01-01
locked_start=2021-01-01
execution_environment=GitHub Actions
scientific_change=false
```

## Authorization State

This file prepares the output of `PREV7-0102`; it does not complete it.

Formal acceptance is prohibited until:

1. `PREV7-0000` and G0 have valid evidence;
2. `PREV7-0101` has a valid readiness event;
3. this exact ADR is reviewed through the required pull request;
4. the repository owner records the separate `PREV7-0103` scope and
   non-goals approval.

Until then:

```text
g1a_status=blocked
full_run_authorized=false
```

## Consequences

- Performance work must prove equivalence against the exact V6 reference.
- Any scientific mismatch is a defect, not an accepted V7 improvement.
- Clean Portfolio work must use a separate identity, plan and authorization.
- No workflow may infer full-run authority from this document.
- Editing this ADR after approval requires a new digest and approval event.

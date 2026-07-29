# GTBI V7 Owner Decisions

Recorded at: `2026-07-29`

Source: direct instruction from the repository owner in the Codex task.

## Decisions

1. The first two items from the owner's personal action list are removed.
   Three independent audits, different reviewers, external custodians and
   dual-person approvals are not required. The owner-controlled model replaces
   them.

2. The maximum spending level is the current spending level. No increase is
   authorized. The public-safe billing projection observed on 29 July 2026
   records `0 USD` net Actions cost in the current period and the existing
   Enterprise Cloud unit at `21 USD` per full month. Incremental net spending
   is capped at `0 USD`. A discount or price change requires new authorization.
   Taxes, foreign exchange and the private gross-usage response are not
   represented by this public projection.

3. The repository owner explicitly accepts the existing frozen local data lake
   as the current V7 input. It does not need to be downloaded again. Before a
   GitHub-only scientific run it must be transferred once to immutable GitHub
   storage and restricted to observations no later than `2020-12-31`.
   `tiingo_daily` is only an optional provider for a future owner-requested
   refresh.

4. The repository owner authorizes creation and use of the private resources
   covered by the preparation plan. This authorization is explicit. The
   zero-increase budget, least-privilege, identity, cleanup and evidence rules
   remain technical requirements of the plan rather than conditions added to
   the owner's authorization.

5. All remaining owner decisions are deferred until the relevant step occurs.
   Deferral grants no implicit approval. The affected task must pause and ask
   for the exact decision when it becomes actionable.

## Operational Interpretation

- Owner action items 1 and 2: removed from the immediate owner queue.
- Budget: `NO_INCREASE_FROM_CURRENT_BASELINE`.
- Incremental net-spend cap: `0 USD`.
- Existing Enterprise Cloud unit: `21 USD` per full month, before tax and FX.
- Actions net amount at the observed billing snapshot: `0 USD`.
- Discount or price drift: `STOP_AND_REAUTHORIZE`.
- Licence owner acceptance: `ACCEPTED_EXPLICITLY`.
- Independent audits required: `0`.
- Distinct reviewers/custodians required: `NO`.
- GitHub V6 preservation lease: `ACCEPTED_AS_SUFFICIENT`.
- Current V7 input: `OWNER_SUPPLIED_FROZEN_LOCAL_DATA_LAKE`.
- Local data: `4,693` symbols, `4,400` downloaded successfully, `3.02 GiB`.
- GitHub transfer: required once before a GitHub-only V7 scientific run because
  the original Actions artifact expired on `2026-07-06`.
- Tiingo: optional future refresh only; no token is required now.
- GitHub `read:packages`: `GRANTED_VERIFIED`.
- Organization packages found: `0` across container, Maven, npm, NuGet and
  RubyGems.
- Private-resource owner authorization: `AUTHORIZED_EXPLICITLY`.
- Other decisions: `DEFERRED_UNTIL_ACTIONABLE`.
- Execution status: `TECHNICAL_PREPARATION_AUTHORIZED`; scientific execution
  still requires its normal data, locked and reproducibility gates.

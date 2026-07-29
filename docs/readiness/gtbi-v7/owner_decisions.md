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

3. The repository owner explicitly accepts the licences presented so far. No
   independent licence reviewer is required. Yahoo is retained only as the
   provenance of historical evidence; future V7 snapshots use the existing
   `tiingo_daily` connector under Tiingo's free Starter terms.

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
- Yahoo-derived future V7 input: `PROHIBITED`.
- Future V7 provider: `TIINGO_DAILY`.
- Tiingo activation: `TOKEN_REQUIRED`; free-tier capacity is `500` unique
  symbols per month.
- GitHub `read:packages`: owner-authorized but awaiting the interactive OAuth
  approval GitHub requires; it does not block technical preparation.
- Private-resource owner authorization: `AUTHORIZED_EXPLICITLY`.
- Other decisions: `DEFERRED_UNTIL_ACTIONABLE`.
- Execution status: `TECHNICAL_PREPARATION_AUTHORIZED`; scientific execution
  still requires its normal data, locked and reproducibility gates.

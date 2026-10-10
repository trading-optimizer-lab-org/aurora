# SPY strategy catalog: status

**Status: FROZEN (2026-10-10).** The request, controller and governance
workflows were removed, so no catalog run can be requested or launched. The
evaluation engine workflows are kept, dormant. `catalog-prepare` (which ran
on every push to `main`) was removed. The campaign registry is unchanged (its `active` flags are
read by the engine's unit tests), but nothing consumes it to start a run.

## Why it was frozen

Both held-out validations of the catalog's best train-period strategies were
negative. Validation window 2011-01-01 to 2020-12-31; the locked window
(2021 onward) was never opened.

| Selection | Source | Strategies | Negative alpha vs SPY | Best validation result |
|---|---|---:|---:|---|
| Selected-12 (DEHB + catalog) | run 31936904501, 2026-08-16 | 12 | 12 | +9.5%/yr, alpha -4.2%, beat SPY 3/10 years |
| Atlas-1 Pareto 14 | run 36248188742, 2026-09-26 | 14 | 13 | +15.8%/yr, alpha +2.1%, beat SPY 4/10 years |

Train-period returns of the selected-12 were +9% to +19% per year; in
validation they fell to -7.5% to +9.5%. That gap is the signature of
selection overfitting on a single asset.

Re-running a catalog does not help: the engine is deterministic, so the same
catalog returns the same results. Each further look at 2011-2020 also weakens
it as a held-out test.

## What was removed (2026-10-10)

- Request path: intent issues, signed requester App, tickets, authority
  ledger, `catalog-cloud-intake`, `catalog-fast-controller`,
  `catalog-run-controller`.
- Automation: `catalog-run-watchdog` and `catalog-request-reconciler` (every
  15 minutes), `catalog-artifact-keeper` (never succeeded on schedule: listing
  328k artifacts returns HTTP 500), `catalog-capacity-calibration`,
  `catalog-ledger-guard`.
- Qualification and audit: `catalog-cloud-qualification`,
  `catalog-controller-qualification`, `catalog-live-controls-qualification`,
  `catalog-future-architecture`, `catalog-fast-authority-maintenance`,
  `catalog-controller-policy-check`, the `catalog-live-controls-audit` action.
- Secrets used only by the removed audit jobs (auditor App key, enterprise
  billing, cache verifier and package inventory tokens).

The operating prompts in `docs/runbooks/` and the request-layer Python
(`infra/sp500_megarun/catalog_requester*`, `scripts/*catalog_cloud*`,
`scripts/submit_catalog_run_request.py` and similar) are still in the tree
with their unit tests, but no workflow invokes them any more.

Request history: about 28 requests between 2026-08-31 and 2026-09-24. Three
reached SUCCESS (two 8-recipe canaries and one 37,258-recipe run that rebuilt
earlier checkpoints with 0 s of evaluation). The rest were BLOCKED by the
pipeline itself (reduction, gate publication, terminalization, expiry).

All removed files remain in git history before this change.

## What remains

- Engine: `catalog-optimized-run`, `catalog-optimized-worker`,
  `catalog-component-worker`, `catalog-recovery-wave`,
  `catalog-optimized-verify-only`, `catalog-prepare-one`, `catalog-atlas-prepare-one`, reference oracle and
  worker, determinism and equivalence diagnostics, `sp500-atlas-*`.
- Python code under `infra/sp500_megarun/` and `scripts/`, with its unit tests.
- Catalog definitions under `config/sp500_megarun_strategy_catalog_v1/`.

## Reviving it

The engine expects a sealed plan that the removed controller used to produce,
so it cannot be launched as-is. A new catalog run needs a small
`workflow_dispatch` entry point that builds the plan and calls
`catalog-optimized-run.yml`. The campaign definition manifests under
`config/catalog_campaign_definitions/` include the removed controller
workflow in their provenance closure, so they must be regenerated too. Build
that only when there is a genuinely new catalog to evaluate.

The frozen train runtime input pack
(`sp500-megarun-dehb-runtime-inputs-31418682679`) and its feature smoke
artifacts **expire on 2026-11-08**. Download and store them elsewhere before
that date if any future run should reuse exactly the same inputs.

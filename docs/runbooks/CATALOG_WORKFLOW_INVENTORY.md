# Inventario cerrado de workflows de catálogo

Este documento registra **todos** los workflows presentes durante la migración del controlador. La clasificación usa disparadores, llamadas locales y comandos ejecutados; no se basa solo en el nombre del archivo.

## Resultado

- Workflows inventariados: **181**.
- Hash canónico del inventario final: `60f7edc0170f59933597ab5ae3cfebc122e774a3f69f80c4091f4d51bcc7280c`.
- Estado final del validador de topología: **READY**.
- Campaña activa: `sp500-optimized-catalog-v1` mediante `optimized_catalog_v1`.
- Los Atlas antiguos y sus wrappers quedan inactivos y sin disparador público. Su código se conserva para trazabilidad, pero no existe un llamador autorizado.
- Antes de la migración había **23 incumplimientos relevantes**: 10 entradas públicas de cómputo, 3 interfaces sin sellar, 8 trabajos sin el entorno protegido, 1 motor con llamadores no autorizados y 1 motor que no era exclusivamente reutilizable.

## Leyenda

- `heavy=yes`: puede preparar, evaluar, reducir o llamar a cómputo de catálogo/Atlas.
- `active_engine`: único motor productivo registrado.
- `production_worker`: trabajador interno del motor activo.
- `keeper_maintenance`: mantenimiento semanal fijo, limitado y de solo lectura.
- `inactive_legacy` / `inactive_helper`: conservado sin entrada pública y sin llamador productivo.
- `control_or_lightweight`: control, CI, documentación o trabajo ajeno a la ejecución de catálogos.

## Inventario completo

| path | current triggers (antes) | heavy | engine_id | registered campaign keys | target trigger | migration action | test enforcing it |
|---|---|---:|---|---|---|---|---|
| .github/workflows/_aurora-future-run-v3.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/_aurora-merge-level-v3.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/_aurora-recovery-plan-v3.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/_aurora-retry-shard-v3.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/_stock-protocol-original-290-event-study.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/aurora-maintenance-inventory.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/aurora-maintenance-retention.yml | schedule, workflow_dispatch | no | - | - | schedule, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/body-wick-selected-prior-period.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/body-wick-sr-15m-21symbols-backtest.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/body-wick-sr-15m-overnight-age-sweep.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/btc-5m-all-features-5methods-trainonly-1h-180jobs.yml | push, workflow_dispatch | no | - | - | push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/btc-5m-all-features-5methods-trainonly-9h-max500-real180.yml | push, workflow_dispatch | no | - | - | push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/btc-5m-all-features-5methods-trainonly-9h-wave.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/btc-5m-pf105-statistical-robustness.yml | push, workflow_dispatch | no | - | - | push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/calmar-gt1-pvalue-bootstrap-173495.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/catalog-artifact-keeper.yml | not present | yes | - | sp500-optimized-catalog-v1 | schedule | created as the sole bounded read-only keeper path | keeper topology and repository topology receipts |
| .github/workflows/catalog-capacity-calibration.yml | not present | no | - | - | schedule | created as the fixed synthetic read-only capacity calibration | capacity calibration and repository topology tests |
| .github/workflows/catalog-component-determinism.yml | workflow_call | no | - | - | workflow_call | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-component-worker.yml | workflow_call | yes | optimized_catalog_v1 | sp500-optimized-catalog-v1 | workflow_call | sealed worker inputs and protected environment | sealed heavy engine and environment tests |
| .github/workflows/catalog-controller-policy-check.yml | pull_request, push | no | - | - | pull_request, push | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-equivalence-diagnostic.yml | workflow_call | yes | - | - | workflow_call | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-future-architecture.yml | workflow_call, workflow_dispatch | yes | - | - | workflow_call | removed direct dispatch; internal synthetic helper only | repository topology receipt |
| .github/workflows/catalog-ledger-guard.yml | not present | no | - | - | issue_comment | created as edit/delete tamper guard | tamper guard topology test |
| .github/actions/catalog-live-controls-audit/action.yml | local composite action used only by five protected jobs | no | - | - | exactly five fixed protected job-level callers | protected audit implementation; each caller obtains credentials from `catalog-production`, emits an immutable secret-free receipt artifact, and discards credentials | repository topology receipt |
| .github/workflows/catalog-live-controls-qualification.yml | workflow_dispatch | no | - | - | workflow_dispatch | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-optimized-run.yml | workflow_call, workflow_dispatch | yes | optimized_catalog_v1 | sp500-optimized-catalog-v1 | workflow_call | removed direct dispatch; sealed active engine | sealed heavy engine and environment tests |
| .github/workflows/catalog-optimized-verify-only.yml | workflow_call | no | - | - | workflow_call | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-optimized-worker.yml | workflow_call | yes | optimized_catalog_v1 | sp500-optimized-catalog-v1 | workflow_call | sealed worker inputs and protected environment | sealed heavy engine and environment tests |
| .github/workflows/catalog-recovery-wave.yml | not present | yes | optimized_catalog_v1 | sp500-optimized-catalog-v1 | workflow_call | created as the bounded selective-recovery worker path | recovery policy, sealed inputs and topology tests |
| .github/workflows/catalog-reference-oracle.yml | workflow_call | no | - | - | workflow_call | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-reference-worker.yml | workflow_call | yes | - | - | workflow_call | audited; retained closed/lightweight or internal-only role | repository topology receipt |
| .github/workflows/catalog-request-reconciler.yml | not present | no | - | - | schedule, workflow_dispatch | created as bounded delivery fallback | bounded reconciler topology test |
| .github/workflows/catalog-run-controller.yml | not present | yes | - | - | issues, workflow_call | created as sole public signed-request entrypoint | controller trigger, writer, ordering and gate tests |
| .github/workflows/catalog-run-watchdog.yml | not present | no | - | - | schedule | created as read-only discovery and controller re-entry only | watchdog authority and topology tests |
| .github/workflows/concurrency-smoke-500.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/docs.yml | pull_request, push, workflow_dispatch | no | - | - | pull_request, push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/free-15m-equity-universe-download.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-benchmark.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-ci.yml | pull_request, workflow_dispatch | no | - | - | pull_request, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-merge-only.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-policy.yml | pull_request, workflow_dispatch | no | - | - | pull_request, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-reference.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-replan.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/github-performance-validation.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/global-technical-buy-indicator-355jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/global-technical-buy-indicator-final-recheck-parallel.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/global-technical-buy-indicator-final-recheck.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-inventory.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-master-plan-quality.yml | pull_request, push, workflow_dispatch | no | - | - | pull_request, push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-new-reference-merge-recovery.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-new-reference-worker.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-new-reference.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-no-go-close.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-readiness-state-controller.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-stage-two-required.yml | pull_request, push, workflow_dispatch | no | - | - | pull_request, push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/gtbi-v7-successor-close.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/lint.yml | pull_request, push | no | - | - | pull_request, push | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/literature-campaign-to-backtest.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/literature-pdf-text-extract-29855.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/literature-sharpe2-paper-variants-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/literature-strategy-backtest-9419-9h.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/literature-strategy-idea-discovery-9h.yml | push, workflow_dispatch | no | - | - | push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/minervini-sepa-marketcap2b-daily-screener.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/minervini-sepa-usa-europe-50m-daily-screener.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-93-high-fidelity-behavior-reference.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-93-max-free-full-runner.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-93-max-free-runner.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-93-max-free-source-probe.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-current-data-quality-tests.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-five-forward-proxies.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-five-forward-proxy-ci.yml | pull_request, workflow_dispatch | no | - | - | pull_request, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-proxy-real-correlation-audit.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-yfinance-sec-current-score.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-yfinance-sec-remerge.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openap-yfinance-sec-repair-merge.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/openassetpricing-correlation-audit.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-aqr-factor-sharpe2-360stages.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-cboe-sentiment-sharpe2-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-operable-ensemble-sharpe2-360stages.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-sharpe2-nightly-30min-until-0630.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-sharpe2-nightly-novel-30min-until-0630.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-sharpe2-overnight-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-spy-daily-event-sharpe2-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-spy-monthly-sharpe2-quick-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-spy-weekly-regime-sharpe2-quick-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-spy-weekly-sharpe2-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/paper-spy-weekly-sharpe2-quick-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/property-thorough.yml | schedule, workflow_dispatch | no | - | - | schedule, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/security.yml | pull_request, push, schedule | no | - | - | pull_request, push, schedule | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-26-paper-locked-strategy-report.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-26-paper-replication-backtest.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-atlas-calibration.yml | workflow_call, workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-atlas-controller.yml | workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-atlas-pilot.yml | workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-atlas-postrun.yml | workflow_call, workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-atlas-run.yml | workflow_call, workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-atlas-segment.yml | workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-autonomous-discovery.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-catalog-optimization-qualification.yml | workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-dehb-cache-conflict-diagnostic.yml | push, workflow_dispatch | no | - | - | push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-continuous-bootstrap-v2.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-continuous-coordinator-v2.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-continuous-reducer-v2.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-continuous-smoke-v2.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-continuous-supervisor-v2.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-continuous-worker-pool-v2.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-cross-runner-determinism.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-dehb-mega-controller-v1.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-event-study-factory-core1950.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-f024-inverse-diagnostic.yml | workflow_call | no | - | - | workflow_call | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-long-short-daily-campaign.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-megarun-dehb-official-smoke.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-megarun-dehb-registry-preflight.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-megarun-free-data-audit.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-megarun-macro-feature-smoke-f032.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-megarun-normalization-probe.yml | push, workflow_dispatch | no | - | - | push, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-megarun-preflight-240.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-only-outperforming-study-finder.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-search-method-benchmark-expanded.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-search-method-benchmark-short.yml | workflow_dispatch | no | - | - | workflow_dispatch | removed every catalog and Atlas launch mode | repository topology receipt |
| .github/workflows/sp500-selected-validation-12-once.yml | workflow_call, workflow_dispatch | no | - | - | workflow_call, workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-strategy-catalog-overnight.yml | workflow_call, workflow_dispatch | yes | - | - | workflow_call | removed public trigger; retained inactive internal compatibility | legacy launcher has no public trigger |
| .github/workflows/sp500-weekly-hedge-dehb-policy1995-downside-1wave-80jobs-1h.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-weekly-hedge-dehb-policy1995-downside-6waves-80jobs-1h.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-weekly-hedge-dehb-policy1995-downside-6waves-80jobs-9h.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sp500-weekly-hedge-policy1995-autostart-9h.yml | workflow_run | no | - | - | workflow_run | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-15m-support-resistance-2015-retest.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-15m-support-resistance-355jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-daily-direction-accuracy-355jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-daily-direction-funnel-top-all-features-4waves-1h.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-monthly-annual-dominance-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-monthly-tf21-ma10-locked-table.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-monthly-trend-following-paper21-355jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-global-random-train-yearly-calmar-beat-counts.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-global-random-train-yearly-calmar.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-global-random-yearly-outperformance.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-longshort-locked-strategy-report.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-longshort-sharpe2-355jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-noleverage-50ideas-nightly-until-0700.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-noleverage-50ideas-v2-nightly-until-0700.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/spy-weekly-noleverage-global-random-nightly-until-0700.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/sr-15m-equity-universe-feature-search.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-36-tests-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-36-tests-finalize-recovery.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-original-290-event-study-checkpointed.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-original-290-event-study-finalize-recovery.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-original-290-event-study-merge-only.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-original-290-event-study-recovery.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-original-290-event-study.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/stock-protocol-scientific-full-universe-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-20-etf-proxy-2000-no-locked-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-cashfloor-controller-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-corr95-drawdown-guard-mdd25-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-corr95-feature-sweep-mdd25-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-cppi-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-daily-tactical-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-floor-controller-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-invvol-guard-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-mdd15-trainonly-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-multiasset-corr95-mdd25-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-path-cppi-expanded-universe-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-path-cppi-focused-cv-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-path-cppi-focused-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-path-cppi-mdd15-trainonly-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-path-cppi-refined-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-regime-timing-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-static-smooth-hardstress-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-static-smooth-mdd15-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-strict-final-gt-initial-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/swr-tsmom-corr95-360jobs.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/tests.yml | pull_request, push | no | - | - | pull_request, push | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/tradingview-minervini-indicator-small.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/typecheck.yml | pull_request, push | no | - | - | pull_request, push | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-merge-now.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-no-long-spy-quality-merge-now.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-no-long-spy-quality-stop.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-no-long-spy-quality.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend-stop.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/weekly-spy-dehb-real-500-parallel-1h-momentum-trend.yml | workflow_dispatch | no | - | - | workflow_dispatch | outside catalog execution scope; inventoried with no change | repository topology receipt |
| .github/workflows/wheel.yml | pull_request, push | no | - | - | pull_request, push | outside catalog execution scope; inventoried with no change | repository topology receipt |

## Regla de mantenimiento

Cualquier alta, baja o cambio de un workflow debe regenerar este inventario y su recibo. Si el hash, el número de filas, el rol, el llamador o el disparador no coinciden, la auditoría devuelve `BLOCKED` antes de reservar autoridad o ejecutar ciencia.

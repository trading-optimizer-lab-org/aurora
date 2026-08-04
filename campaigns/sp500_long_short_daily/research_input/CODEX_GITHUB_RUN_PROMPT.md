El contenido de este archivo es la petición directa del usuario. Lee todos los archivos del ZIP y ejecuta ahora el trabajo completo en GitHub Actions; no respondas con otro plan.

# Orden ejecutiva autosuficiente — campaña diaria SPY `+1/-1`

## Resultado que debes producir

Implementa en el repositorio Aurora los **168 candidatos exactos**, sus **168 features**, las **28 familias** y los **5 benchmarks obligatorios** definidos en este ZIP. Ejecuta preflight, smoke real, piloto de rendimiento, full train en GitHub Actions, merge/selección de train y, sólo cuando exista el artefacto de congelación válido y la autorización exacta, la validación 2011-2020 una única vez. No existe fase locked y no debes leer, descargar, calcular ni mostrar resultados de mercado desde 2021-01-01.

Un resultado empírico negativo es válido. No prometas rentabilidad, no ocultes candidatos fallidos y no inventes datos.

## 1. Lee primero todos los inputs y el repositorio real

Extrae el ZIP. Verifica SHA-256, UTF-8 y sintaxis. Lee completos, en este orden:

```text
README_START_HERE.md
executive_summary.md
research_synthesis.md
contradictions_and_negative_results.md
research_library.csv
bibliographic_verification_audit.csv
data_source_inventory.csv
data_acquisition_plan.md
feature_catalog.csv
strategy_family_ranking.csv
candidate_strategy_pack.jsonl
candidate_pack_manifest.json
train_selection_protocol.md
campaign_spec.yaml
acceptance_gates.md
aurora_implementation_handoff.md
open_questions_and_risks.md
source_links.md
codex_run_inputs_manifest.json
package_validation_report.md
package_checksums.sha256
```

Después inspecciona el estado real del repositorio y lee entero `docs/GITHUB_RUN_MASTER_STANDARD.md`, el framework `_aurora-future-run-v3.yml`, los contratos, snapshots, FeatureStore y workflows existentes. La especificación del ZIP manda sobre decisiones de esta campaña; el estándar del repositorio manda sobre integración, seguridad y operación cuando no contradiga el ZIP.

Comandos iniciales preparados:

```bash
pwd
git status --short --branch
find .github/workflows -maxdepth 3 -type f -print | sort
find docs campaigns src tests -maxdepth 5 -type f 2>/dev/null | sort | head -1000
grep -R "_aurora-future-run-v3\|GITHUB_RUN_MASTER_STANDARD\|FeatureStore\|locked" .github docs src campaigns -n 2>/dev/null | head -1000 || true
sha256sum package_checksums.sha256 codex_run_inputs_manifest.json candidate_pack_manifest.json 2>/dev/null || true
```

No respondas con otro plan. Inspecciona, edita, prueba, publica y ejecuta.

## 2. Contrato inmutable de mercado

Aplica a candidatos y benchmarks:

```text
instrument = SPY
position_values = [-1, +1]
absolute_exposure = 1.0
cash_allowed = false
partial_exposure_allowed = false
leverage_allowed = false
volatility_scaling_allowed = false
commission_bps = 0
slippage_bps = 0
borrow_cost_bps = 0
financing_bps = 0
switching_cost_bps = 0
market_impact_bps = 0
train_end = 2010-12-31
validation_start = 2011-01-01
validation_end = 2020-12-31
locked_start = 2021-01-01
locked_opened = false
```

La decisión se toma después del cierre regular de SPY en `t`, sólo con datos cuyo `available_at/release_time <= decision_time_t`. El cambio entra en vigor en la siguiente apertura negociable de SPY `t+1`. Hasta esa apertura se conserva la posición anterior. Empate, banda neutral no cruzada o input no resuelto: conservar la posición anterior. En el primer día evaluable, aplica la regla; empate exacto inicial: `+1`.

La cartera permanece siempre `+1` o `-1`. No conviertas silenciosamente un paper long/cash en long/short. Implementa exactamente el signo, parámetros y variantes del JSONL.

## 3. Contabilidad de retorno y dividendos

Usa una única función auditada de retorno total open-to-open para candidatos y benchmarks. Reconstruye un open corporativamente consistente a partir de OHLC raw, splits y distribuciones; no supongas que `adjusted close` define un `adjusted open`.

- Long recibe distribuciones.
- Short debe distribuciones.
- Con costes cero y la misma posición/intervalo, exige `short_return == -long_return` dentro de tolerancia numérica.
- Benchmarks y candidatos usan el mismo calendario, sesiones y ledger.

## 4. Cinco benchmarks obligatorios

Implementa y reporta por separado:

1. `buy_and_hold_spy_total_return`: `+1` todos los días.
2. `always_long`: `+1` todos los días; debe coincidir exactamente con buy-and-hold.
3. `always_short`: `-1` todos los días.
4. `symmetric_sma_200`: después de cierre `t`, `+1` si `SPY_TR_CLOSE_t > SMA200_t`, `-1` si menor, empate conserva posición; apertura `t+1`.
5. `symmetric_momentum_12m`: después de cierre `t`, `+1` si `SPY_TR_CLOSE_t/SPY_TR_CLOSE_{t-252}-1 > 0`, `-1` si menor, empate conserva posición; apertura `t+1`.

## 5. Datos gratuitos y fail-closed

Ningún candidato depende de una fuente `not_free`, `rejected_bias` o `rejected_unverifiable`. No sustituyas silenciosamente datos. `proxy_only` debe conservar su etiqueta, superar pruebas de procedencia y quedar rechazado explícitamente si no alcanza el gate. Para `usable_after_repair`, completa exactamente la reparación documentada antes del full.

Reglas críticas:

- SPY: reconciliar Stooq/Yahoo únicamente como comprobación y escoger una serie raw canónica tras cotejarla con State Street; snapshot y hash de bytes.
- Dividendos/splits: State Street u otra fuente oficial documentada; tests manuales alrededor de cada evento.
- ALFRED/macroeconomía: joins por vintage y fecha/hora de publicación; nunca usar el valor final revisado como histórico.
- Cboe: respetar primera difusión histórica de VIX, VIX3M, SKEW, VVIX y backfills.
- CFTC: fecha de publicación, no sólo fecha de posiciones; no adelantar el informe.
- Breadth: no usar constituyentes actuales como historia; exchange breadth es proxy.
- Familia overnight: usar `SPY_TR_OPEN_t/SPY_TR_CLOSE_{t-1}-1` ya conocido al cierre `t`; no descargar ES de pago.

## 6. Paths recomendados

Adapta a convenciones reales sin cambiar la semántica:

```text
campaigns/sp500_long_short_daily/campaign_spec.yaml
campaigns/sp500_long_short_daily/candidates/candidate_strategy_pack.jsonl
campaigns/sp500_long_short_daily/candidates/candidate_pack_manifest.json
campaigns/sp500_long_short_daily/features/feature_catalog.csv
campaigns/sp500_long_short_daily/sources/data_source_inventory.csv
campaigns/sp500_long_short_daily/sources/research_library.csv
campaigns/sp500_long_short_daily/config/acceptance_gates.md
campaigns/sp500_long_short_daily/src/
campaigns/sp500_long_short_daily/tests/
.github/workflows/sp500-long-short-daily-campaign.yml
```

Workflow recomendado: `.github/workflows/sp500-long-short-daily-campaign.yml`.
Branch recomendado: `codex/sp500-long-short-daily-research`.

Artifacts recomendados:

```text
sp500-ls-preflight-<run_id>
sp500-ls-smoke-<run_id>
sp500-ls-pilot-<run_id>
sp500-ls-full-train-<run_id>-<shard>
sp500-ls-train-merged-<run_id>
sp500-ls-train-freeze-<run_id>
sp500-ls-validation-once-<run_id>
sp500-ls-final-verified-<run_id>
```

## 7. Implementación exacta, deduplicación y FeatureStore

- Parsear las 168 líneas; recalcular `canonical_hash`; exigir 168 IDs/hashes únicos y seis variantes por cada una de las 28 familias.
- Implementar adapters, schemas, tests y mapping de cada campo.
- Reutilizar FeatureStore para features idénticas; deduplicar por hash/formula/datasets/availability, no por nombre.
- Usar una implementación causal de referencia fila a fila. Las optimizaciones/vectorización sólo se aceptan si producen posiciones, retornos y hashes equivalentes.
- Markov: sólo probabilidades filtradas; reinicios deterministas; prohibido smoothing.
- Logit/elastic net: features y grids predeclarados, normalización train-only y tuning cronológico anidado.
- No cambiar umbrales, pesos, parámetros, datasets ni signos por resultados.

## 8. Tests obligatorios antes del smoke

Como mínimo:

```text
package schema/UTF-8/hash/count tests
candidate canonical hash and duplicate tests
all positions exactly -1/+1
all six cost fields exactly zero
initial-position and tie-state tests
NYSE holiday/next-session-open tests
close-t information cannot affect close-t execution
SPY open-to-open long/short/dividend/split hand calculations
buy-and-hold == always-long reconciliation
always-short == negative always-long reconciliation
SMA-200 benchmark reference case
252-session momentum benchmark reference case
ALFRED vintage/release as-of join tests
CFTC publication-lag test
Cboe first-dissemination/backfill test
breadth current-membership leakage rejection
adjusted-close-as-open leakage rejection
Markov filtered-vs-smoothed leakage rejection
nested walk-forward isolation
validation freeze immutability
locked-date firewall
clean rerun determinism
optimized-vs-reference equivalence
```

Toda prueba que detecte lookahead, locked breach, coste no cero, cash/leverage, retorno mal contabilizado o falta de determinismo bloquea la campaña.

## 9. GitHub Actions: preflight, smoke, piloto y full

No ejecutes backtests, descargas masivas ni merges pesados en el PC local. Local sólo para inspección, edición, lint y unit tests pequeños. GitHub Actions hace el trabajo pesado.

Orden:

1. `preflight`: paquete, schemas, conectividad mínima, licencias/terms, locked firewall; sin selección.
2. `smoke`: dos candidatos simples y los cinco benchmarks en un tramo train corto; mecánica real y doble ejecución determinista.
3. `pilot`: familias representativas en train; benchmark de layouts y procesos.
4. `full_train`: todos los candidatos, folds walk-forward y rejections.
5. `merge_and_select`: cobertura exacta, múltiples pruebas, ranking/Pareto y freeze.
6. `validation_once`: sólo con ack exacto y artefacto freeze verificado.
7. `verify`: hashes, cobertura, reproducibilidad, gates y estado final.

El piloto debe medir al menos `candidate_blocks`, `family_blocks` y `cost_balanced_blocks`, y procesos 1..`min(4,vCPU)`. Mide wall time, startup/merge overhead, memoria, FeatureStore hit rate y granularidad de recuperación. Elige automáticamente el plan medido más rápido que conserve resultados. No supongas que 360 jobs es óptimo. Nunca excedas 360 jobs estándar concurrentes ni 4 vCPU útiles por runner.

Smoke pasa sólo si:

- todos los tests críticos pasan;
- dos ejecuciones limpias tienen hashes idénticos;
- los cinco benchmarks están presentes y reconciliados;
- no hay fechas posteriores a 2020-12-31;
- el artifact es completo y descargable.

Piloto pasa sólo si:

- produce `scheduler_plan.json` determinista basado en medición;
- resultado optimizado equivale a referencia;
- merge/retry/checkpoint funciona;
- estimación de coste/unidades cubre todo el full.

Full train pasa técnicamente sólo si las 168 estrategias están presentes con resultado o rechazo explícito y los cinco benchmarks están completos.

## 10. Train, métricas, ranking y múltiples pruebas

Desarrollo y ranking sólo en train. Usa walk-forward exterior anual 1998-2010, embargo y tuning cronológico anidado según `train_selection_protocol.md`.

Métricas mínimas para candidato y benchmark:

```text
CAGR
total_return
annual_return
Sharpe
Sortino
Calmar
max_drawdown
worst_year
volatility
daily_hit_rate
monthly_hit_rate
positive_years
turnover
long_days
short_days
position_switches
rolling_1y
rolling_3y
rolling_5y
skew
CVaR
performance_by_market_regime
```

Calcula el score de train exacto, la frontera Pareto y los gates. Aplica White Reality Check, Hansen SPA, CSCV/PBO, Deflated Sharpe Ratio y stationary/block bootstrap. No selecciones mediante validación.

## 11. Freeze y validación única

Antes de validar, crea y sube `train_selection_freeze.json` con IDs/orden de finalistas, métricas OOF, código, datos, entorno y hashes. Descarga y verifica el artifact.

Autorización exacta requerida:

```text
OPEN_VALIDATION_2011_2020_ONCE
```

Comando orientativo:

```bash
gh workflow run sp500-long-short-daily-campaign.yml   -f phase=validation_once   -f campaign_spec_path=campaigns/sp500_long_short_daily/campaign_spec.yaml   -f validation_ack=OPEN_VALIDATION_2011_2020_ONCE   -f train_freeze_artifact=<artifact-o-hash-verificado>
```

Si no hay finalistas train elegibles, no abras validación: entrega `NEGATIVE_RESULT`. Una vez abierta, no retunes, no reponderes, no repares según resultado y no ejecutes una segunda búsqueda. Un error upstream genuino invalida técnicamente la validación y exige una campaña/version nueva; no autoriza una repetición silenciosa.

## 12. Firewall 2021+

En cada job y antes de cada artifact:

- limita consultas y descargas a `<=2020-12-31`;
- escanea índices, columnas, filenames, parquet metadata, cache keys y logs;
- ante cualquier observación `>=2021-01-01`, termina con `TECHNICAL_FAILURE_LOCKED_BREACH` sin imprimir valores;
- no implementes workflow, input o CLI para locked/live/post-2020.

## 13. Checkpoints y recuperación

- Checkpoint por unidad/shard/fold con input hash, commit, seed y output hash.
- Merge jerárquico y cobertura exacta.
- Al fallar, relanza únicamente unidades `failed` o `pending` con inputs idénticos.
- Nunca relances todo el full si sólo faltan unidades concretas.
- Si cambia código/datos/hash, invalida sólo dependencias afectadas según el DAG; registra el motivo.
- No reutilices un cache cuyo rango de fechas, vintage, schema o hash no coincida.

Comandos `gh` orientativos:

```bash
gh workflow run sp500-long-short-daily-campaign.yml -f phase=preflight -f campaign_spec_path=campaigns/sp500_long_short_daily/campaign_spec.yaml
gh run list --workflow sp500-long-short-daily-campaign.yml --limit 30
gh run view <RUN_ID> --log-failed
gh run download <RUN_ID> -D artifacts/<RUN_ID>
gh workflow run sp500-long-short-daily-campaign.yml -f phase=smoke -f campaign_spec_path=campaigns/sp500_long_short_daily/campaign_spec.yaml
gh workflow run sp500-long-short-daily-campaign.yml -f phase=pilot -f campaign_spec_path=campaigns/sp500_long_short_daily/campaign_spec.yaml
gh workflow run sp500-long-short-daily-campaign.yml -f phase=full_train -f campaign_spec_path=campaigns/sp500_long_short_daily/campaign_spec.yaml
gh workflow run sp500-long-short-daily-campaign.yml -f phase=merge_and_select -f campaign_spec_path=campaigns/sp500_long_short_daily/campaign_spec.yaml
```

Adapta nombres de inputs sólo tras inspeccionar el framework real y documenta el mapping.

## 14. Outputs finales esperados

El artifact final debe incluir como mínimo:

```text
RESULT_STATUS.md
final_manifest.json
train_selection_freeze.json
candidate_and_benchmark_metrics.csv
train_daily_returns.parquet
validation_daily_returns.parquet       # sólo si se abrió
annual_returns.csv
rolling_metrics.csv
regime_metrics.csv
fold_metrics.csv
eligibility_and_rejections.csv
multiple_testing_results.json
causality_audit.json
data_lineage.jsonl
raw_manifest.jsonl
scheduler_plan.json
environment_lock.txt
implementation_mapping.md
```

Además entrega año a año, reglas completas, near-misses, cobertura, tiempos por fase/shard, retries, unidades pendientes/fallidas, hashes y limitaciones de proxy.

## 15. Definiciones de estado

- `POSITIVE_VALIDATED_RESULT`: al menos un finalista congelado supera todos los gates técnicos y de validación.
- `NEGATIVE_RESULT`: datos/código son válidos pero ningún finalista supera gates; o train termina válidamente sin finalistas elegibles.
- `VALIDATION_NOT_OPENED`: train/freeze válido, pero no se proporcionó la autorización exacta.
- `TECHNICAL_FAILURE`: resultado no interpretable por datos, lookahead, locked breach, retorno, coste, cobertura, reproducibilidad, merge o infraestructura.

Nunca conviertas un fallo técnico en retorno cero ni un resultado negativo en una nueva búsqueda sobre validación.

## 16. Prohibiciones exactas

No:

- abrir, calcular o mostrar 2021+;
- usar validación para crear, escoger, filtrar, reparar o reponderar;
- usar cash, posición 0, exposición parcial, leverage o volatility scaling;
- aplicar cualquier coste distinto de cero a métricas headline;
- depender de datos pagados o usar fallbacks silenciosos;
- usar adjusted close como adjusted open sin reconstrucción;
- usar constituyentes actuales para historia;
- usar macro final revisada cuando se requieran vintages;
- usar Markov smoothing;
- borrar candidatos o fallos del merge;
- ejecutar el full pesado localmente;
- relanzar todo cuando sólo faltan unidades;
- afirmar éxito sin artifact completo verificado.

## 17. Publicación y respuesta final

Crea commits intencionales, sube la branch y abre draft PR; no hagas merge automático. Verifica cada run y descarga artifacts. Continúa hasta terminar el run autorizado salvo bloqueo real o autorización adicional obligatoria.

La respuesta final debe empezar por el estado empírico e incluir branch, commit, draft PR, workflow/run IDs, artifacts/hashes, cobertura exacta por familia, resultados train OOF, freeze, validación o motivo de no apertura, White RC/SPA/PBO/DSR, ranking/Pareto, near-misses, tiempos, limitaciones y confirmación explícita de que 2021+ permaneció cerrado.

# OBSOLETO - Mejoras Pendientes a Implementar

Este documento queda archivado como contexto historico. No describe el estado
actual de QuantForge v1.4.

Motivo: su tesis principal sobre filtracion de OOS en el GA fue cerrada por la
ruta de fitness IS-only y el endurecimiento del spine v1.4. La referencia viva
para pendientes es `C:\Users\HP\Desktop\quantforge_roadmap_pendiente.txt`.

---

Respuesta directa: QuantForge es un motor propio de investigación cuantitativa para crear, probar, optimizar, validar y preparar estrategias para paper/live. No es solo un backtester: intenta ser una plataforma completa anti-overfit.

Lo más importante: la idea es buena y encaja con lo que necesitas, pero ahora mismo le falta cerrar una contradicción grave: la documentación dice que el OOS es sagrado, pero parte del algoritmo genético está usando OOS dentro de la optimización. Eso puede fabricar estrategias aparentemente buenas pero contaminadas. La serpiente se muerde la cola, con corbata y métricas bonitas.

No he tocado ni modificado nada.

## Qué Es

QuantForge está en quantforge. Por lo que he visto, pretende cubrir todo este flujo:

- Cargar datos.
- Ejecutar backtests.
- Crear señales de estrategias.
- Optimizar parámetros con algoritmo genético.
- Validar con walk-forward, Monte Carlo, SPP, DSR y checks anti-lookahead.
- Medir costes, slippage, métricas, atribución y riesgo.
- Preparar paper/live con preflight y sizing.
- Registrar experimentos y versiones.

La propia documentación lo define como: "motor de backtesting + algoritmo genético con disciplina militante anti-overfit" en README.md.

## Qué Tiene Bien

Tiene bastante estructura seria:

- Motor single-asset y multi-asset.
- Capa de costes y slippage.
- Validaciones: walk-forward, Monte Carlo, SPP, DSR, lookahead, noise, gaps, escenarios, tail risk, CSCV/PBO.
- Optimización genética.
- Portfolio/risk: HRP, Black-Litterman, risk parity, CVaR, sizing.
- ML/regime: labels, feature importance, HMM, Hurst, Markov switching.
- Reporting y tearsheets.
- Registro de experimentos.
- Preflight/paper/live.
- Tests abundantes según los informes internos.

Como arquitectura, está mucho más cerca de una plataforma de research seria que de un script suelto.

## Problema Principal

El mayor problema está en la frontera entre investigar y validar.

En ARCHITECTURE.md la regla es clara: el OOS debe estar protegido. Pero en la práctica, el comando de búsqueda carga datos con OOS y se los pasa al GA:

- forge.py (line 123) carga include_oos=True.
- forge.py (line 128) pasa IS y OOS a run_ga.
- fitness.py (line 8) calcula fitness usando OOS.
- fitness.py (line 26) devuelve Calmar/Sharpe OOS como objetivo.

Eso rompe el principio más importante del motor. Si el GA elige candidatos mirando OOS, el OOS deja de ser validación y pasa a ser parte del entrenamiento.

## Qué Le Falta

Prioridad real:

### 1. Separar datasets correctamente

Ahora QuantForge usa básicamente IS/OOS. Tu protocolo actual necesita algo más estricto:

- IS_TRAIN
- IS_VALID
- WF
- OOS_DEV
- OOS_LOCKED
- FORWARD/PAPER

Y OOS_LOCKED no debería poder abrirse salvo validación final explícita.

### 2. Arreglar la optimización genética

El GA no debería optimizar sobre OOS. Debería optimizar solo con IS/WF interno y después consultar OOS_DEV una vez el candidato ya pase gates previos.

### 3. Snapshots congelados

data_layer.py descarga de yfinance si falta caché. Eso no sirve para validación formal. Para declarar algo robusto/live, necesita snapshots inmutables con fecha, hash y procedencia.

### 4. Integración real con JADE/HEDGE

QuantForge parece un motor general, pero todavía no veo que sea la fuente canónica de JADE. Antes de usarlo como juez, necesita adaptadores que reproduzcan exactamente resultados ya conocidos.

### 5. Un único pipeline obligatorio

pipeline.py ejecuta varias validaciones, pero otras quedan como módulos sueltos u opcionales. Para tu proyecto, los gates no deberían depender de "me acordé de activar este flag".

### 6. Reproducibilidad de entorno

La carpeta tiene mucho código, pero las dependencias parecen incompletas. requirements.txt no refleja todo lo que QuantForge importa. También __init__.py dice versión 0.1.0, mientras los informes hablan de v1.2 completa.

### 7. Live todavía no es producción seria

Hay base de live/paper, pero le falta cerrar posición real, reconciliación broker, fills parciales, auditoría, kill switch, límites por estrategia/slot, calendario, errores de datos y trazabilidad completa.

### 8. Documentación alineada

Hay documentación potente, pero parte está desfasada. El README dice unas fases, los completion reports dicen otras, y hay texto corrupto por codificación. No es grave para investigar, pero sí para operar.

## Mi Diagnóstico

- Hecho: QuantForge es una plataforma cuantitativa ambiciosa y bastante avanzada.
- Hecho: tiene una contradicción seria entre la regla anti-overfit y la implementación del GA.
- Suposición razonable: nació para resolver exactamente los problemas que estás teniendo con JADE: sobreoptimización, OOS débil, costes, validación dispersa y falta de trazabilidad.
- Mi opinión: no metería más funciones v1.3 todavía. Primero cerraría el núcleo. Si no, añades más piezas encima de una frontera IS/OOS mal protegida. Eso es construir un castillo con radar, piscina y cimientos de mantequilla.

## Siguiente Paso Recomendado

Yo haría esto:

1. Convertir QuantForge en el juez oficial, no todavía en el motor live.
2. Corregir GA para que no use OOS como objetivo.
3. Crear splits compatibles con tu RESEARCH_PROTOCOL.md.
4. Añadir snapshots congelados obligatorios.
5. Validar que QuantForge reproduce métricas conocidas antes de confiar en nuevas optimizaciones.

En resumen: QuantForge tiene muy buena pinta como base, pero ahora mismo le falta blindar la frontera anti-overfit. Esa es la pieza crítica antes de usarlo para decidir qué estrategia es válida.

---

## Análisis Exhaustivo Complementario

Auditoría completa del código (4 sub-agentes paralelos sobre core+ml, strategies+regime+ga+validation, deployment+registry+analytics+reporting+cli, tests+examples+docs+infra). 110 hallazgos NUEVOS no listados arriba.

### A. Críticos (bloquean uso serio, fix antes de fase 3)

| Ubicación | Gap | Por qué crítico |
|-----------|-----|-----------------|
| costs_intraday.py:108 + engine_jit.py:108 | Bug Corwin-Schultz: `sqrt(2*beta) - sqrt(beta)` mal escrito → siempre 0 / NaN | Estimador bid-ask roto, intraday spread = 0 silencioso |
| engine_intraday.py:74 | `_in_session_mask()` asume índice naive sin tz — RTH/ETH falla en datos UTC | Intraday inutilizable en producción con cualquier feed serio |
| taxes.py:241 | NAV path referencia variable no definida `prev_shares_prev_p_value(...)` | Backtest tax-aware corrompe NAV silencioso |
| data_layer.py + OOSGuard | `OOSGuard` (líneas 45-100) infra existe pero GA nunca entra en context manager | OOS contamination indetectable a pesar de tener tooling lockbox advisory |
| validation/lookahead_check.py:33-35 | AST scanner solo busca `[i+`, `[t+`. NO detecta: `.shift(-1)`, `.iloc[i+1:]`, `df[df.index > x]`, groupby fwd-fill, lambda, numba | Falsos negativos garantizados — escáner no protege |
| Repo root | NO `pyproject.toml` / `setup.py` / `setup.cfg` / lockfile | Paquete no instalable, examples usan `sys.path.insert` hack, CI imposible |
| .github/workflows/ | NO CI/CD pipeline | Sin gate automático, todo manual |
| engine_multi.py:136-139 | `_align()` por intersección sin calendario de festivos — equity USA + crypto roto | Multi-asset misalignment, holidays mal cortados |

### B. Altos (cerrar antes de v1.x estable)

**Engine / costs / fills**
- costs.py:25-31 — round-trip 2x spread asume cierre instantáneo, no modela parciales / queue
- costs.py:83-85 — borrow short ignora T+1 settle y disponibilidad real
- realtime.py:173-181 — `fetch_latest()` sin staleness vs wall-clock, no backfill huecos
- realtime.py:222-223 — sin heartbeat detection, market halt invisible
- bars.py:269-270 — partial bar trailing sin re-index timestamp

**ML leakage**
- labels.py:143-156 — triple-barrier no enforce que `events` no vea futuro (sin guard)
- labels.py:164-165 — slice `loc[t0:t1_target]` inclusivo en ambos extremos → bias
- labels.py:194 — first-touch return no ajusta slippage en barrera

**Validación**
- validation/walk_forward.py:79-82 — modo expanding permite OOS overlap (incorrecto académicamente)
- validation/monte_carlo.py:68-69 — circular bootstrap NO implementado, edges wrap rompe independencia
- validation/retraining.py:80-81 — train_window roll con cadence < window → IS overlapping
- validation/cscv_pbo.py:95-99 — sampling uniforme combos, sin stratification

**Allocator / risk**
- allocator.py:287-373 — weights aplican lag t-1 pero NO modelo coste de rebalance
- risk_optim.py:174-253 — linprog dense O(T*N) memoria, T>1300 + N=50 explota
- risk_optim.py:117-128 — feasibility check no detecta conflictos asset-level
- liquidity.py:80-88 — thresholds ADV (1M/10M/100M) hardcoded, no calibración

**Tests / reproducibilidad**
- core/seed.py:24-28 — sin seed Numba JIT (RNG no propaga a engine_jit)
- Sin pytest-cov, sin .coveragerc, sin coverage gate
- test_live_deployment.py solo mocks, sin integración real Alpaca/IB
- Sin pre-commit, sin black/ruff/mypy enforced

### C. Medios (gaps técnicos importantes)

**Estrategias library**
- atr_breakout.py:62-63 — comentario "anti-lookahead" pero usa `prices[i]` (off-by-one vs convention)
- donchian.py:30 — mismo issue: rolling max usa `[i-period:i]` cerrado pero signal vista bar i
- stop_wrapper.py:57-58 — `lockout_until=i+1+lockout` → off-by-one
- online_learner.py:143 — regressor branch no llama `partial_fit(classes=...)` → inconsistente

**Regime**
- regime/hmm.py:174 — sin tolerance param convergencia, solo n_iter=100
- regime/markov_switching.py:261 — shape check (T,K,T) frágil con versión statsmodels
- regime/hurst.py:150,246 — clip H a [0,1] silencia inestabilidad sin flag
- regime/bayes_alpha.py:161-170 — fallback OLS singular usa `y.std()` denominador erróneo

**GA**
- ga/runner.py:114 — `cxBlend` puede crear genes fuera bounds, clip post-hoc
- ga/runner.py:165 — `varOr lambda_=population` overshoots si pop < lambda
- ga/runner.py:177 — NSGA-II ties no broken deterministically
- ga/fitness.py:8-24 — pesos tupla `(1,1,1,-1)` sin normalizar (Calmar ratio vs MDD %)
- ga/bayes_opt.py:239 — kernel Matern fijo trata categorical como real

**Validación adicional**
- validation/spp.py:72-80 — grid simétrico alrededor midpoint, NO best params actuales
- validation/spp.py — child RNG sin seed propagation a workers
- validation/deflated_sharpe.py:25-39 — N_trials=1 sin warning multiplicidad
- validation/pipeline.py:174-180 — DSR skip si n_trials==1 (single-param strategies bypassan gate)
- validation/purged_cv.py:130-145 — purga train pero NO test side overlaps
- validation/tail_risk.py:62-68 — tail blocks 3x weight sin renormalizar epochs
- validation/correlation_stress.py:77 — Cholesky reescala mean/std post pero target corr asume std=1

**Black-Litterman / cov**
- black_litterman.py:234-251 — pinv si singular sin warning, posterior cov puede no PSD
- black_litterman.py:122-172 — confidence=1.0 → Omega[i,i]=0 → solver mal condicionado
- cov_shrinkage.py:138-170 — `_optimal_shrinkage_factor` doble loop O(T*N²)

**Registry / journal / versioning**
- registry.py:163-203 — INSERT OR IGNORE devuelve `lastrowid` stale en duplicados
- registry.py:214-262 — `json_extract` falla si valor null/non-numeric
- journal.py:263-295 — sign convention BUY=neg / SELL=pos sin docstring
- versioning.py:86-116 — `inspect.getsource` falla en numba/Cython; hash inestable

**Tearsheet / analytics**
- tearsheet.py:85-101 — drawdown abierto al final → recovery_days NaN
- metrics_full.py — solapa con core/metrics.py (deduplicación pendiente)
- attribution.py:67-100 — duck-type sin runtime check
- analytics/factor_analysis.py — modelo factor no documentado (Fama-French / custom)

**Preflight / sizing / liquidity**
- sizing.py:38-55 — `vol_target_size` no define lookback
- preflight.py:75-90 — `min_bars=200` hardcoded sin adaptar a strategy lookback
- preflight.py:93-106 — runtime lookahead test single-point, sin power calc / CI
- preflight.py:228-260 — NTP solo `pool.ntp.org`, sin fallback list
- liquidity.py:275-373 — redistribución loop puede terminar con slack residual

**CLI**
- cli/forge.py — sin `--dry-run`, `--resume`, `--config-schema`, `--log-level`
- forge.py:61-75 — config sin schema enforcement, malformed YAML pasa
- forge.py:36-49 — strategy library import duro, sin fallback

**Tests / infra**
- Sin `conftest.py` ni `pytest.ini` — fixtures duplicadas
- test_integration.py:40 define `SLOW_TEST_THRESHOLD_SEC=30.0` pero nunca usa marker
- Sin `@pytest.mark.slow` (suite no separa rápido/lento)
- Sin test JIT-vs-no-JIT regression (engine.py vs engine_jit.py)
- Sin test pipeline.py con todas las gates obligatorias
- test_property.py solo 4 tests hypothesis (cobertura property superficial)
- Multi-asset E2E con HRP/BL no testeado integrado
- core/features.py — cache invalidation edge cases no testeados
- validation/lookahead_check.py — sin variante intraday/minute-bar
- Walk-forward windows multi-asset NO definidos

**Docs / infra repo**
- Sin `CHANGELOG.md`
- Sin `CONTRIBUTING.md`
- Sin `STRATEGY_AUTHOR.md` / tutorial añadir indicador custom
- Sin glosario (Calmar, DSR, SPP, PBO, MAR, CSCV)
- Sin diagrama arquitectura visual
- Sin API reference auto-gen (sphinx / mkdocs)
- Sin `.env.example` para Alpaca/IB creds
- Sin `Dockerfile`
- Sin `py.typed` marker (mypy no enforced)
- Examples sin "expected output" file (regresión imposible)

### D. Bajos (mejoras incrementales)

- metrics.py:61 — `mdd==0` produce inf/inf (guard threshold borderline)
- engine_intraday.py:231 — borrow crypto usa `bars_per_day*365` calendar
- engine.py:89-100 — slippage rejection silente, revierte a base
- engine.py:77 — bounds tolerance `1e-9` pero downstream asume exacto
- bars.py:327-330 — tick bars JIT sin pre-flight NaN check
- engine_multi.py:191 — attribution aditivo ignora compounding rebalance
- taxes.py:187 — wash-sale solo same-symbol (no cross-symbol)
- taxes.py:214 — long-term threshold 365d hardcoded
- slippage.py:103 — `volume_limit=2.5%` sin variación intraday
- realtime.py:138 — yfinance nanosegundos truncados
- data_layer.py:240 — fence date off-by-one (2012-12-31 vs 2012-12-30)
- config.py:29-35 — magic numbers sin docstring
- validation/noise_injection.py:79 — noise=-100% → precio negativo (clip silencioso cambia distribución)
- validation/scenarios.py:70-105 — escenarios hardcoded (2000/2008/2022), falta LTCM 1998, flash crash
- ma_cross.py:28-29 — cumsum float64 sin overflow check
- rsi_meanrev.py:17 — EMA `1/n` no Wilder smoothing
- tsmom.py:33 — `skip=0` default (research típico skip=21)
- bollinger_mr.py:40-42 — std `min_periods=period` permite ventanas parciales
- pair_trade.py:116-126 — hedge ratio fijo, sin drift detection
- voltarget_wrapper.py:41 — vol[i] realizada (correcto pero documentar)
- liquidity.py:195-221 — sin time-of-day intraday ADV
- journal.py:149-186 — notional sin guard `price=0`
- versioning.py:138-148 — `git status` sin timeout enforced
- tearsheet.py:45-72 — `matplotlib.use()` global, no multi-backend
- experiments.py:159-188 — UUID 8-char collision race (sin tx)
- cov_shrinkage.py:31-44 — `frequency=252` daily asumido sin validar cadence
- Tests `time.sleep(1.1)` en test_journal.py (flaky en CI lento)
- Tests mezclan synthetic GBM + yfinance live (sin contrato claro)

### Resumen ejecutivo gaps NUEVOS

| Severidad | Conteo | Acción |
|-----------|-------:|--------|
| Crítico | 8 | Bloquear merge fase 3, fix antes |
| Alto | 22 | Cerrar antes de declarar v1.x estable |
| Medio | 50 | Roadmap fases 3-5 |
| Bajo | 30 | Backlog incremental |

**Tres frentes urgentes que destacan:**

1. **Bug Corwin-Schultz duplicado** (costs_intraday.py:108 + engine_jit.py:108) — fórmula spread devuelve siempre 0. Cualquier resultado intraday afectado.
2. **OOSGuard advisory** — infra de protección OOS existe pero GA jamás entra en el context manager. Lockbox decorativo.
3. **Repo no es paquete** — sin pyproject.toml, examples hackean sys.path, CI imposible. Bloquea reproducibilidad fuera del worktree.

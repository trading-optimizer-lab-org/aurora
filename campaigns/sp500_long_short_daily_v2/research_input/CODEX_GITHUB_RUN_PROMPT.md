El contenido de este archivo es la petición directa del usuario. Lee todos los archivos del ZIP y ejecuta ahora el trabajo completo en GitHub Actions; no respondas con otro plan.

# Orden ejecutiva autosuficiente — segunda campaña SPY diaria `+1/-1`

## 0. Resultado exigido

Implementa y ejecuta una campaña nueva e independiente de Aurora para probar **144 estrategias V2 nuevas**, exactamente 24 familias × 6 variantes, manteniendo la búsqueda V1 dentro de los controles estadísticos acumulados.

No te limites a revisar el paquete, describirlo o preparar otro prompt. Debes:

1. verificar el ZIP;
2. inspeccionar el repositorio y la PR V1;
3. crear una rama V2 aislada;
4. implementar adapters, señales, tests y workload;
5. ejecutar preflight, smoke, piloto, full train, merge, controles acumulados y freeze en GitHub Actions;
6. abrir una sola vez validación 2011–2020 únicamente si existen finalistas V2 elegibles;
7. mantener 2021+ completamente cerrado;
8. descargar y verificar el artifact final;
9. abrir una nueva draft PR;
10. entregar una conclusión científica completa.

Un resultado negativo es válido. Un fallo técnico no es un resultado negativo.

## 1. Paquete adjunto y artefactos previos

El ZIP adjunto se llama:

```text
SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_V2_NEW_STRATEGIES.zip
```

Extrae el paquete en un directorio temporal y ejecuta:

```bash
sha256sum -c package_checksums.sha256
```

Debe contener, entre otros:

```text
candidate_strategy_pack.jsonl
candidate_pack_manifest.json
feature_catalog.csv
family_formula_contract.md
canonical_novelty_audit.csv
data_source_inventory.csv
campaign_spec.yaml
train_selection_protocol.md
acceptance_gates.md
prior_campaign_reference.json
prior_campaign/SP500_LONG_SHORT_DIARIO_RESEARCH_AURORA_FINAL.zip
prior_campaign/sp500-ls-train-yahoo-fallback-r8-results.zip
```

Verifica obligatoriamente:

```text
V1 research ZIP SHA-256:
a8db7fd9ab2422d81601104234a80185e317b6cc2fae07914c5bca6c7e421925

V1 final-results ZIP SHA-256:
164ce2d50909c5224e5260fa185516e9ecee368d948201852f35a72fa0780775
```

El artifact V1 corresponde a:

```text
repository = trading-optimizer-lab-org/aurora
run_id = 30985200320
artifact_id = 8922049799
scientific_commit = e2d643609208c1d66b86a8800d1f9abd4415b60c
PR = 114
status = NEGATIVE_RESULT
V1 declared candidates = 168
V1 evaluated candidates = 65
V1 rejected candidates = 103
V1 frozen finalists = 0
V1 validation opened = false
V1 locked opened = false
```

Si cualquiera de los dos hashes previos no coincide, termina la promoción científica con:

```text
COMBINED_MULTIPLICITY_INCOMPLETE
```

Puedes resolver el problema técnico y repetir train, pero no puedes abrir validación mientras el historial V1 no esté verificado.

## 2. Repositorio, rama y aislamiento

Repositorio:

```text
trading-optimizer-lab-org/aurora
```

Inspecciona primero:

```bash
git status --short --branch
git remote -v
git branch --show-current
gh pr view 114 --repo trading-optimizer-lab-org/aurora --json state,isDraft,mergedAt,headRefName,headRefOid,baseRefName
gh workflow view _aurora-future-run-v3.yml --repo trading-optimizer-lab-org/aurora
find docs .github campaigns infra config tests -maxdepth 5 -type f | sort
```

Lee completos:

```text
docs/GITHUB_RUN_MASTER_STANDARD.md
.github/workflows/_aurora-future-run-v3.yml
campaigns/sp500_long_short_daily/implementation_mapping.md
infra/sp500_long_short_daily/contracts.py
infra/sp500_long_short_daily/data.py
infra/sp500_long_short_daily/ledger.py
infra/sp500_long_short_daily/signals.py
infra/sp500_long_short_daily/statistics.py
infra/sp500_long_short_daily/workload.py
tests/test_sp500_long_short_daily_campaign.py
```

Base de rama:

- Si PR #114 sigue sin fusionar, crea V2 desde su `head` remoto verificado.
- Si PR #114 ya está fusionada y V1 existe en `main`, crea V2 desde `main`.
- No reconstruyas V1 desde memoria.
- No modifiques la candidata V1, sus resultados ni su PR.

Rama recomendada:

```text
codex/sp500-long-short-daily-research-v2
```

Paths nuevos:

```text
campaigns/sp500_long_short_daily_v2/
campaigns/sp500_long_short_daily_v2/input_package/
campaigns/sp500_long_short_daily_v2/research_input/
campaigns/sp500_long_short_daily_v2/prior_campaign/
infra/sp500_long_short_daily_v2/
config/sp500_long_short_daily_v2_train_v3.yaml
.github/workflows/sp500-long-short-daily-v2-campaign.yml
tests/test_sp500_long_short_daily_v2_campaign.py
```

Workload recomendado:

```text
aurora.infra.sp500_long_short_daily_v2.workload:TRAIN_WORKLOAD
```

## 3. Contrato inmutable

```text
instrument = SPY
allowed positions = [-1,+1]
absolute exposure = 1.0
cash = forbidden
position 0 = forbidden
partial exposure = forbidden
leverage = forbidden
volatility scaling = forbidden

decision = after SPY regular close t
information cutoff = available_at <= close_t
execution = next tradable SPY regular open t+1
holding return = audited total return from open t+1 to open t+2
tie/missing/no-event = preserve previous position
initial position = +1 until first lawful directional signal

commission_bps = 0
slippage_bps = 0
borrow_cost_bps = 0
financing_bps = 0
switching_cost_bps = 0
market_impact_bps = 0
```

Boundaries:

```text
train_end = 2010-12-31
validation_start = 2011-01-01
validation_end = 2020-12-31
locked_start = 2021-01-01
locked_opened = false
```

No request, file, dataframe, cache, filename, metadata field or log puede exponer datos de mercado `>=2021-01-01`.

## 4. Contabilidad y datos

### Target SPY

Reutiliza exactamente el ledger total-return auditado en V1. No uses adjusted close como adjusted open. Para toda sesión:

```text
long receives distributions
short owes distributions
short_daily_return = -long_daily_return
```

Candidatos y benchmarks comparten idéntico ledger, calendario y retorno.

### SPY predictor OHLCV

Usa raw OHLCV acotado a train, reconciliado con la instantánea V1. Normaliza splits consistentemente en open/high/low/close y de forma inversa en volumen. Las distribuciones no entran en la geometría OHLC.

### Predictor ETFs

Panel sectorial fijo:

```text
XLB XLE XLF XLI XLK XLP XLU XLV XLY
```

Panel de riesgo fijo:

```text
DIA QQQ IWM IEF TLT SPY
```

Concentración:

```text
RSP SPY
```

Para predictor ETFs:

```text
Q_t = split-normalized price-only close
dividends excluded
no pre-inception synthesis
no current-constituent reconstruction
no future fill
```

Verifica identidad, inception y primer raw bar. Fechas esperadas que debes confirmar:

```text
DIA 1998-01-14
sector SPDR inception 1998-12-16; listing 1998-12-22
QQQ 1999-03-10
IWM 2000-05-22
IEF 2002-07-22
TLT 2002-07-22
RSP 2003-04-24
```

Fuente operativa primaria: Yahoo bounded chart snapshot. Stooq es sólo adjudicador secundario y nunca fallback silencioso.

## 5. Las 24 familias y 144 fórmulas congeladas

Notación:

```text
P_t = split-normalized price-only SPY close
O_t,H_t,L_t = split-normalized price-only SPY OHLC
V_t = split-normalized volume
r_t = ln(P_t/P_(t-1))
r_on_t = ln(O_t/P_(t-1))
r_id_t = ln(P_t/O_t)
Q_{symbol,t} = split-normalized price-only predictor ETF close
```

Todas las ventanas terminan en `t`. Score positivo → `+1`; score negativo → `-1`; score cero/ausente → conservar estado. Para familias de eventos, sólo el evento cambia el estado.

### `overnight_intraday_tug` — Overnight–intraday tug of war
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Trading and non-trading intervals can reflect different information and inventory mechanisms; the sign is tested both ways ex ante.
- `TUG_CONT_1` — base_t = SUM_{i=0..0}(r_on_(t-i) - r_id_(t-i)); score_t = base_t
- `TUG_CONT_5` — base_t = SUM_{i=0..4}(r_on_(t-i) - r_id_(t-i)); score_t = base_t
- `TUG_CONT_20` — base_t = SUM_{i=0..19}(r_on_(t-i) - r_id_(t-i)); score_t = base_t
- `TUG_REVERSE_1` — base_t = SUM_{i=0..0}(r_on_(t-i) - r_id_(t-i)); score_t = -base_t
- `TUG_REVERSE_5` — base_t = SUM_{i=0..4}(r_on_(t-i) - r_id_(t-i)); score_t = -base_t
- `TUG_REVERSE_20` — base_t = SUM_{i=0..19}(r_on_(t-i) - r_id_(t-i)); score_t = -base_t

### `semivariance_balance` — Daily signed semivariance balance
Datasets: `V2DS001, V2DS003`.
Rationale: Asymmetric upside and downside variation may reveal a risk state not captured by total realized volatility.
- `SEMIVAR_BAL_5` — up_t=SUM(r_s^2*I[r_s>0], s=t-4..t); down_t=SUM(r_s^2*I[r_s<0], same window); score_t=up_t-down_t
- `SEMIVAR_BAL_10` — up_t=SUM(r_s^2*I[r_s>0], s=t-9..t); down_t=SUM(r_s^2*I[r_s<0], same window); score_t=up_t-down_t
- `SEMIVAR_BAL_20` — up_t=SUM(r_s^2*I[r_s>0], s=t-19..t); down_t=SUM(r_s^2*I[r_s<0], same window); score_t=up_t-down_t
- `SEMIVAR_BAL_40` — up_t=SUM(r_s^2*I[r_s>0], s=t-39..t); down_t=SUM(r_s^2*I[r_s<0], same window); score_t=up_t-down_t
- `SEMIVAR_BAL_63` — up_t=SUM(r_s^2*I[r_s>0], s=t-62..t); down_t=SUM(r_s^2*I[r_s<0], same window); score_t=up_t-down_t
- `SEMIVAR_BAL_126` — up_t=SUM(r_s^2*I[r_s>0], s=t-125..t); down_t=SUM(r_s^2*I[r_s<0], same window); score_t=up_t-down_t

### `signed_volume_pressure` — Signed abnormal-volume pressure
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Direction weighted by abnormal volume tests whether high-information moves are more persistent than low-volume moves.
- `SIGNED_VOL_1` — abvol_s=ln(V_s/MEDIAN(V_u,u=s-251..s)); sv_s=sign(r_s)*abvol_s; score_t=SUM(sv_s,s=t-0..t)
- `SIGNED_VOL_3` — abvol_s=ln(V_s/MEDIAN(V_u,u=s-251..s)); sv_s=sign(r_s)*abvol_s; score_t=SUM(sv_s,s=t-2..t)
- `SIGNED_VOL_5` — abvol_s=ln(V_s/MEDIAN(V_u,u=s-251..s)); sv_s=sign(r_s)*abvol_s; score_t=SUM(sv_s,s=t-4..t)
- `SIGNED_VOL_10` — abvol_s=ln(V_s/MEDIAN(V_u,u=s-251..s)); sv_s=sign(r_s)*abvol_s; score_t=SUM(sv_s,s=t-9..t)
- `SIGNED_VOL_20` — abvol_s=ln(V_s/MEDIAN(V_u,u=s-251..s)); sv_s=sign(r_s)*abvol_s; score_t=SUM(sv_s,s=t-19..t)
- `SIGNED_VOL_63` — abvol_s=ln(V_s/MEDIAN(V_u,u=s-251..s)); sv_s=sign(r_s)*abvol_s; score_t=SUM(sv_s,s=t-62..t)

### `autocorrelation_switch` — Rolling autocorrelation continuation/reversal switch
Datasets: `V2DS001, V2DS003`.
Rationale: Estimated positive serial dependence continues the corresponding recent move; negative dependence reverses it.
- `AC_SWITCH_L1_W63` — rho_t=PearsonCorr(r_s,r_(s-1)) over the last 63 valid paired observations; recent_t=SUM(r_s,s=t-0..t); score_t=rho_t*recent_t
- `AC_SWITCH_L2_W63` — rho_t=PearsonCorr(r_s,r_(s-2)) over the last 63 valid paired observations; recent_t=SUM(r_s,s=t-1..t); score_t=rho_t*recent_t
- `AC_SWITCH_L5_W126` — rho_t=PearsonCorr(r_s,r_(s-5)) over the last 126 valid paired observations; recent_t=SUM(r_s,s=t-4..t); score_t=rho_t*recent_t
- `AC_SWITCH_L10_W126` — rho_t=PearsonCorr(r_s,r_(s-10)) over the last 126 valid paired observations; recent_t=SUM(r_s,s=t-9..t); score_t=rho_t*recent_t
- `AC_SWITCH_L20_W252` — rho_t=PearsonCorr(r_s,r_(s-20)) over the last 252 valid paired observations; recent_t=SUM(r_s,s=t-19..t); score_t=rho_t*recent_t
- `AC_SWITCH_L63_W504` — rho_t=PearsonCorr(r_s,r_(s-63)) over the last 504 valid paired observations; recent_t=SUM(r_s,s=t-62..t); score_t=rho_t*recent_t

### `variance_ratio_switch` — Variance-ratio continuation/reversal switch
Datasets: `V2DS001, V2DS003`.
Rationale: A variance ratio above one supports continuation of the recent q-period move; below one supports reversal.
- `VR_SWITCH_Q2_W126` — VR_t(q=2,W=126) = variance_of_q_period_sums/(q*variance_of_1_period_returns), using overlapping returns and Lo-MacKinlay finite-sample denominator inside the trailing window; dir_t=sign(SUM(r_s,s=t-1..t)); score_t=dir_t*(VR_t-1)
- `VR_SWITCH_Q5_W126` — VR_t(q=5,W=126) = variance_of_q_period_sums/(q*variance_of_1_period_returns), using overlapping returns and Lo-MacKinlay finite-sample denominator inside the trailing window; dir_t=sign(SUM(r_s,s=t-4..t)); score_t=dir_t*(VR_t-1)
- `VR_SWITCH_Q10_W252` — VR_t(q=10,W=252) = variance_of_q_period_sums/(q*variance_of_1_period_returns), using overlapping returns and Lo-MacKinlay finite-sample denominator inside the trailing window; dir_t=sign(SUM(r_s,s=t-9..t)); score_t=dir_t*(VR_t-1)
- `VR_SWITCH_Q20_W252` — VR_t(q=20,W=252) = variance_of_q_period_sums/(q*variance_of_1_period_returns), using overlapping returns and Lo-MacKinlay finite-sample denominator inside the trailing window; dir_t=sign(SUM(r_s,s=t-19..t)); score_t=dir_t*(VR_t-1)
- `VR_SWITCH_Q5_W504` — VR_t(q=5,W=504) = variance_of_q_period_sums/(q*variance_of_1_period_returns), using overlapping returns and Lo-MacKinlay finite-sample denominator inside the trailing window; dir_t=sign(SUM(r_s,s=t-4..t)); score_t=dir_t*(VR_t-1)
- `VR_SWITCH_Q20_W504` — VR_t(q=20,W=504) = variance_of_q_period_sums/(q*variance_of_1_period_returns), using overlapping returns and Lo-MacKinlay finite-sample denominator inside the trailing window; dir_t=sign(SUM(r_s,s=t-19..t)); score_t=dir_t*(VR_t-1)

### `close_location_pressure` — Close-location pressure
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Where the close lies inside the daily range is an OHLC pressure statistic unavailable to close-only momentum rules.
- `CLV_MEAN_1` — clv_s = (2*P_s-H_s-L_s)/(H_s-L_s), with clv_s=0 when H_s=L_s; score_t = MEAN(clv_s, s=t-0..t)
- `CLV_MEAN_3` — clv_s = (2*P_s-H_s-L_s)/(H_s-L_s), with clv_s=0 when H_s=L_s; score_t = MEAN(clv_s, s=t-2..t)
- `CLV_MEAN_5` — clv_s = (2*P_s-H_s-L_s)/(H_s-L_s), with clv_s=0 when H_s=L_s; score_t = MEAN(clv_s, s=t-4..t)
- `CLV_MEAN_10` — clv_s = (2*P_s-H_s-L_s)/(H_s-L_s), with clv_s=0 when H_s=L_s; score_t = MEAN(clv_s, s=t-9..t)
- `CLV_MEAN_20` — clv_s = (2*P_s-H_s-L_s)/(H_s-L_s), with clv_s=0 when H_s=L_s; score_t = MEAN(clv_s, s=t-19..t)
- `CLV_MEAN_63` — clv_s = (2*P_s-H_s-L_s)/(H_s-L_s), with clv_s=0 when H_s=L_s; score_t = MEAN(clv_s, s=t-62..t)

### `gap_body_interaction` — Gap/body agreement and rejection
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Agreement measures information continuation through the close; rejection uses the intraday direction when the opening gap is reversed.
- `GAP_BODY_AGREE_1` — x_s = (r_on_s + r_id_s) if sign(r_on_s)=sign(r_id_s) and both nonzero else 0; y_s = r_id_s if sign(r_on_s) != sign(r_id_s) and both nonzero else 0; score_t = SUM_{s=t-0..t}(x_s)
- `GAP_BODY_AGREE_5` — x_s = (r_on_s + r_id_s) if sign(r_on_s)=sign(r_id_s) and both nonzero else 0; y_s = r_id_s if sign(r_on_s) != sign(r_id_s) and both nonzero else 0; score_t = SUM_{s=t-4..t}(x_s)
- `GAP_BODY_AGREE_20` — x_s = (r_on_s + r_id_s) if sign(r_on_s)=sign(r_id_s) and both nonzero else 0; y_s = r_id_s if sign(r_on_s) != sign(r_id_s) and both nonzero else 0; score_t = SUM_{s=t-19..t}(x_s)
- `GAP_REJECT_BODY_1` — x_s = (r_on_s + r_id_s) if sign(r_on_s)=sign(r_id_s) and both nonzero else 0; y_s = r_id_s if sign(r_on_s) != sign(r_id_s) and both nonzero else 0; score_t = SUM_{s=t-0..t}(y_s)
- `GAP_REJECT_BODY_5` — x_s = (r_on_s + r_id_s) if sign(r_on_s)=sign(r_id_s) and both nonzero else 0; y_s = r_id_s if sign(r_on_s) != sign(r_id_s) and both nonzero else 0; score_t = SUM_{s=t-4..t}(y_s)
- `GAP_REJECT_BODY_20` — x_s = (r_on_s + r_id_s) if sign(r_on_s)=sign(r_id_s) and both nonzero else 0; y_s = r_id_s if sign(r_on_s) != sign(r_id_s) and both nonzero else 0; score_t = SUM_{s=t-19..t}(y_s)

### `range_volatility_ratio` — Range-volatility conditioned direction
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Range-based volatility is efficient; this rule continues an established direction when short-run range volatility is below its long-run state and reverses it when volatility expands.
- `PARK_RATIO_5_20` — pk_s = ln(H_s/L_s)^2/(4*ln(2)); rv_short_t=MEAN(pk,5); rv_long_t=MEAN(pk,20); trend_t=ln(P_t/P_(t-20)); score_t = sign(trend_t)*(rv_long_t-rv_short_t)
- `PARK_RATIO_10_40` — pk_s = ln(H_s/L_s)^2/(4*ln(2)); rv_short_t=MEAN(pk,10); rv_long_t=MEAN(pk,40); trend_t=ln(P_t/P_(t-40)); score_t = sign(trend_t)*(rv_long_t-rv_short_t)
- `PARK_RATIO_20_63` — pk_s = ln(H_s/L_s)^2/(4*ln(2)); rv_short_t=MEAN(pk,20); rv_long_t=MEAN(pk,63); trend_t=ln(P_t/P_(t-63)); score_t = sign(trend_t)*(rv_long_t-rv_short_t)
- `PARK_RATIO_20_126` — pk_s = ln(H_s/L_s)^2/(4*ln(2)); rv_short_t=MEAN(pk,20); rv_long_t=MEAN(pk,126); trend_t=ln(P_t/P_(t-126)); score_t = sign(trend_t)*(rv_long_t-rv_short_t)
- `PARK_RATIO_63_252` — pk_s = ln(H_s/L_s)^2/(4*ln(2)); rv_short_t=MEAN(pk,63); rv_long_t=MEAN(pk,252); trend_t=ln(P_t/P_(t-252)); score_t = sign(trend_t)*(rv_long_t-rv_short_t)
- `PARK_RATIO_126_504` — pk_s = ln(H_s/L_s)^2/(4*ln(2)); rv_short_t=MEAN(pk,126); rv_long_t=MEAN(pk,504); trend_t=ln(P_t/P_(t-504)); score_t = sign(trend_t)*(rv_long_t-rv_short_t)

### `sector_etf_breadth` — Fixed-sector ETF breadth
Datasets: `V2DS004, V2DS009, V2DS008`.
Rationale: A fixed ETF panel provides broad participation information without using current S&P 500 constituents as historical membership.
- `SECTOR_POSRET_20` — For each of XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY compute ln(Q_t/Q_(t-20)); score_t=mean(sign(component_return)); require all 9 components.
- `SECTOR_POSRET_63` — For each of XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY compute ln(Q_t/Q_(t-63)); score_t=mean(sign(component_return)); require all 9 components.
- `SECTOR_POSRET_126` — For each of XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY compute ln(Q_t/Q_(t-126)); score_t=mean(sign(component_return)); require all 9 components.
- `SECTOR_ABOVE_SMA_50` — For each fixed sector ETF compute sign(Q_t-SMA_50(Q)); score_t=mean(component_sign); require all 9.
- `SECTOR_ABOVE_SMA_100` — For each fixed sector ETF compute sign(Q_t-SMA_100(Q)); score_t=mean(component_sign); require all 9.
- `SECTOR_ABOVE_SMA_200` — For each fixed sector ETF compute sign(Q_t-SMA_200(Q)); score_t=mean(component_sign); require all 9.

### `momentum_consistency` — Directional consistency of daily returns
Datasets: `V2DS001, V2DS003`.
Rationale: The fraction of positive versus negative days measures path consistency independent of return magnitude.
- `POS_FRAC_5` — score_t = MEAN(I[r_s>0]-I[r_s<0], s=t-4..t); zero returns contribute 0
- `POS_FRAC_10` — score_t = MEAN(I[r_s>0]-I[r_s<0], s=t-9..t); zero returns contribute 0
- `POS_FRAC_20` — score_t = MEAN(I[r_s>0]-I[r_s<0], s=t-19..t); zero returns contribute 0
- `POS_FRAC_40` — score_t = MEAN(I[r_s>0]-I[r_s<0], s=t-39..t); zero returns contribute 0
- `POS_FRAC_63` — score_t = MEAN(I[r_s>0]-I[r_s<0], s=t-62..t); zero returns contribute 0
- `POS_FRAC_126` — score_t = MEAN(I[r_s>0]-I[r_s<0], s=t-125..t); zero returns contribute 0

### `range_body_pressure` — Intraday body pressure
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Normalizing the open-to-close body by the full range distinguishes directional conviction from absolute movement.
- `BODY_RANGE_1` — body_s = (P_s-O_s)/(H_s-L_s), with body_s=0 when H_s=L_s; score_t = MEAN(body_s, s=t-0..t)
- `BODY_RANGE_3` — body_s = (P_s-O_s)/(H_s-L_s), with body_s=0 when H_s=L_s; score_t = MEAN(body_s, s=t-2..t)
- `BODY_RANGE_5` — body_s = (P_s-O_s)/(H_s-L_s), with body_s=0 when H_s=L_s; score_t = MEAN(body_s, s=t-4..t)
- `BODY_RANGE_10` — body_s = (P_s-O_s)/(H_s-L_s), with body_s=0 when H_s=L_s; score_t = MEAN(body_s, s=t-9..t)
- `BODY_RANGE_20` — body_s = (P_s-O_s)/(H_s-L_s), with body_s=0 when H_s=L_s; score_t = MEAN(body_s, s=t-19..t)
- `BODY_RANGE_63` — body_s = (P_s-O_s)/(H_s-L_s), with body_s=0 when H_s=L_s; score_t = MEAN(body_s, s=t-62..t)

### `fifty_two_week_state` — Trailing-high reference-price state
Datasets: `V2DS001, V2DS003`.
Rationale: Distance from a salient trailing high can summarize trend and anchoring with one bounded statistic.
- `HIGH_STATE_63_0p9` — ratio_t=P_t/MAX(P_s,s=t-62..t); long_event_t=I[ratio_t>0.9]; short_event_t=I[ratio_t<0.9]; equality preserves state
- `HIGH_STATE_63_0p95` — ratio_t=P_t/MAX(P_s,s=t-62..t); long_event_t=I[ratio_t>0.95]; short_event_t=I[ratio_t<0.95]; equality preserves state
- `HIGH_STATE_126_0p9` — ratio_t=P_t/MAX(P_s,s=t-125..t); long_event_t=I[ratio_t>0.9]; short_event_t=I[ratio_t<0.9]; equality preserves state
- `HIGH_STATE_126_0p95` — ratio_t=P_t/MAX(P_s,s=t-125..t); long_event_t=I[ratio_t>0.95]; short_event_t=I[ratio_t<0.95]; equality preserves state
- `HIGH_STATE_252_0p9` — ratio_t=P_t/MAX(P_s,s=t-251..t); long_event_t=I[ratio_t>0.9]; short_event_t=I[ratio_t<0.9]; equality preserves state
- `HIGH_STATE_252_0p95` — ratio_t=P_t/MAX(P_s,s=t-251..t); long_event_t=I[ratio_t>0.95]; short_event_t=I[ratio_t<0.95]; equality preserves state

### `regression_trend_tstat` — Rolling log-price slope t-statistic
Datasets: `V2DS001, V2DS003`.
Rationale: Slope significance combines direction and path consistency, unlike raw endpoint momentum.
- `REG_TSTAT_20` — Fit OLS ln(P_s)=a+b*j on j=0..19 for s=t-19..t; compute Newey-West HAC t-stat of b with lag=floor(4*(W/100)^(2/9)); score_t=tstat_b
- `REG_TSTAT_40` — Fit OLS ln(P_s)=a+b*j on j=0..39 for s=t-39..t; compute Newey-West HAC t-stat of b with lag=floor(4*(W/100)^(2/9)); score_t=tstat_b
- `REG_TSTAT_63` — Fit OLS ln(P_s)=a+b*j on j=0..62 for s=t-62..t; compute Newey-West HAC t-stat of b with lag=floor(4*(W/100)^(2/9)); score_t=tstat_b
- `REG_TSTAT_126` — Fit OLS ln(P_s)=a+b*j on j=0..125 for s=t-125..t; compute Newey-West HAC t-stat of b with lag=floor(4*(W/100)^(2/9)); score_t=tstat_b
- `REG_TSTAT_189` — Fit OLS ln(P_s)=a+b*j on j=0..188 for s=t-188..t; compute Newey-West HAC t-stat of b with lag=floor(4*(W/100)^(2/9)); score_t=tstat_b
- `REG_TSTAT_252` — Fit OLS ln(P_s)=a+b*j on j=0..251 for s=t-251..t; compute Newey-West HAC t-stat of b with lag=floor(4*(W/100)^(2/9)); score_t=tstat_b

### `momentum_acceleration` — Momentum acceleration
Datasets: `V2DS001, V2DS003`.
Rationale: Acceleration isolates change in directional drift rather than the level of momentum.
- `MOM_ACCEL_5_20` — short_drift_t=ln(P_t/P_(t-5))/5; long_drift_t=ln(P_t/P_(t-20))/20; score_t=short_drift_t-long_drift_t
- `MOM_ACCEL_10_63` — short_drift_t=ln(P_t/P_(t-10))/10; long_drift_t=ln(P_t/P_(t-63))/63; score_t=short_drift_t-long_drift_t
- `MOM_ACCEL_20_126` — short_drift_t=ln(P_t/P_(t-20))/20; long_drift_t=ln(P_t/P_(t-126))/126; score_t=short_drift_t-long_drift_t
- `MOM_ACCEL_21_252` — short_drift_t=ln(P_t/P_(t-21))/21; long_drift_t=ln(P_t/P_(t-252))/252; score_t=short_drift_t-long_drift_t
- `MOM_ACCEL_63_252` — short_drift_t=ln(P_t/P_(t-63))/63; long_drift_t=ln(P_t/P_(t-252))/252; score_t=short_drift_t-long_drift_t
- `MOM_ACCEL_126_504` — short_drift_t=ln(P_t/P_(t-126))/126; long_drift_t=ln(P_t/P_(t-504))/504; score_t=short_drift_t-long_drift_t

### `sector_dispersion_state` — Sector-dispersion conditioned SPY direction
Datasets: `V2DS001, V2DS004, V2DS009, V2DS008`.
Rationale: The rule continues the market direction under relatively coherent sectors and reverses it when dispersion is unusually high.
- `SECTOR_DISP_20_STATE20` — component_ret_i,t=ln(Q_i,t/Q_i,t-20); disp_t=STD_i(component_ret_i,t); baseline_t=MEDIAN(disp_s,s=t-99..t); spy_dir_t=sign(ln(P_t/P_(t-20))); score_t=spy_dir_t*(baseline_t-disp_t)
- `SECTOR_DISP_20_STATE63` — component_ret_i,t=ln(Q_i,t/Q_i,t-20); disp_t=STD_i(component_ret_i,t); baseline_t=MEDIAN(disp_s,s=t-314..t); spy_dir_t=sign(ln(P_t/P_(t-20))); score_t=spy_dir_t*(baseline_t-disp_t)
- `SECTOR_DISP_63_STATE20` — component_ret_i,t=ln(Q_i,t/Q_i,t-63); disp_t=STD_i(component_ret_i,t); baseline_t=MEDIAN(disp_s,s=t-99..t); spy_dir_t=sign(ln(P_t/P_(t-63))); score_t=spy_dir_t*(baseline_t-disp_t)
- `SECTOR_DISP_63_STATE63` — component_ret_i,t=ln(Q_i,t/Q_i,t-63); disp_t=STD_i(component_ret_i,t); baseline_t=MEDIAN(disp_s,s=t-314..t); spy_dir_t=sign(ln(P_t/P_(t-63))); score_t=spy_dir_t*(baseline_t-disp_t)
- `SECTOR_DISP_126_STATE20` — component_ret_i,t=ln(Q_i,t/Q_i,t-126); disp_t=STD_i(component_ret_i,t); baseline_t=MEDIAN(disp_s,s=t-99..t); spy_dir_t=sign(ln(P_t/P_(t-126))); score_t=spy_dir_t*(baseline_t-disp_t)
- `SECTOR_DISP_126_STATE63` — component_ret_i,t=ln(Q_i,t/Q_i,t-126); disp_t=STD_i(component_ret_i,t); baseline_t=MEDIAN(disp_s,s=t-314..t); spy_dir_t=sign(ln(P_t/P_(t-126))); score_t=spy_dir_t*(baseline_t-disp_t)

### `cyclical_defensive_leadership` — Cyclical-versus-defensive ETF leadership
Datasets: `V2DS004, V2DS009, V2DS008`.
Rationale: Cyclical leadership is a direct market-risk appetite proxy; pairs and horizons are fully fixed.
- `LEAD_XLY_XLP_20` — ratio_s=Q_{XLY,s}/Q_{XLP,s}; score_t=ln(ratio_t/ratio_(t-20))
- `LEAD_XLY_XLP_63` — ratio_s=Q_{XLY,s}/Q_{XLP,s}; score_t=ln(ratio_t/ratio_(t-63))
- `LEAD_XLI_XLU_20` — ratio_s=Q_{XLI,s}/Q_{XLU,s}; score_t=ln(ratio_t/ratio_(t-20))
- `LEAD_XLI_XLU_63` — ratio_s=Q_{XLI,s}/Q_{XLU,s}; score_t=ln(ratio_t/ratio_(t-63))
- `LEAD_XLF_XLU_20` — ratio_s=Q_{XLF,s}/Q_{XLU,s}; score_t=ln(ratio_t/ratio_(t-20))
- `LEAD_XLF_XLU_63` — ratio_s=Q_{XLF,s}/Q_{XLU,s}; score_t=ln(ratio_t/ratio_(t-63))

### `tail_imbalance` — Robust tail-event state
Datasets: `V2DS001, V2DS003`.
Rationale: Large robustly standardized tails are tested as reversal events with state persistence.
- `TAIL_REV_Z1p5_63` — med_t=MEDIAN(r_s,63); mad_t=MEDIAN(|r_s-med_t|,63); z_t=(r_t-med_t)/(1.4826*mad_t), undefined if mad_t=0; long_event_t=I[z_t<=-1.5]; short_event_t=I[z_t>=1.5]; otherwise preserve prior state
- `TAIL_REV_Z2p0_63` — med_t=MEDIAN(r_s,63); mad_t=MEDIAN(|r_s-med_t|,63); z_t=(r_t-med_t)/(1.4826*mad_t), undefined if mad_t=0; long_event_t=I[z_t<=-2.0]; short_event_t=I[z_t>=2.0]; otherwise preserve prior state
- `TAIL_REV_Z1p5_126` — med_t=MEDIAN(r_s,126); mad_t=MEDIAN(|r_s-med_t|,126); z_t=(r_t-med_t)/(1.4826*mad_t), undefined if mad_t=0; long_event_t=I[z_t<=-1.5]; short_event_t=I[z_t>=1.5]; otherwise preserve prior state
- `TAIL_REV_Z2p0_126` — med_t=MEDIAN(r_s,126); mad_t=MEDIAN(|r_s-med_t|,126); z_t=(r_t-med_t)/(1.4826*mad_t), undefined if mad_t=0; long_event_t=I[z_t<=-2.0]; short_event_t=I[z_t>=2.0]; otherwise preserve prior state
- `TAIL_REV_Z1p5_252` — med_t=MEDIAN(r_s,252); mad_t=MEDIAN(|r_s-med_t|,252); z_t=(r_t-med_t)/(1.4826*mad_t), undefined if mad_t=0; long_event_t=I[z_t<=-1.5]; short_event_t=I[z_t>=1.5]; otherwise preserve prior state
- `TAIL_REV_Z2p0_252` — med_t=MEDIAN(r_s,252); mad_t=MEDIAN(|r_s-med_t|,252); z_t=(r_t-med_t)/(1.4826*mad_t), undefined if mad_t=0; long_event_t=I[z_t<=-2.0]; short_event_t=I[z_t>=2.0]; otherwise preserve prior state

### `amihud_price_impact` — Signed Amihud-style price impact
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: Moves occurring with lower dollar volume receive more weight as potential price-impact states.
- `SIGNED_IMPACT_1` — dvol_s=P_s*V_s; scale_s=MEDIAN(dvol_u,u=s-251..s); impact_s=r_s*scale_s/dvol_s; score_t=SUM(impact_s,s=t-0..t), undefined when dvol_s<=0
- `SIGNED_IMPACT_3` — dvol_s=P_s*V_s; scale_s=MEDIAN(dvol_u,u=s-251..s); impact_s=r_s*scale_s/dvol_s; score_t=SUM(impact_s,s=t-2..t), undefined when dvol_s<=0
- `SIGNED_IMPACT_5` — dvol_s=P_s*V_s; scale_s=MEDIAN(dvol_u,u=s-251..s); impact_s=r_s*scale_s/dvol_s; score_t=SUM(impact_s,s=t-4..t), undefined when dvol_s<=0
- `SIGNED_IMPACT_10` — dvol_s=P_s*V_s; scale_s=MEDIAN(dvol_u,u=s-251..s); impact_s=r_s*scale_s/dvol_s; score_t=SUM(impact_s,s=t-9..t), undefined when dvol_s<=0
- `SIGNED_IMPACT_20` — dvol_s=P_s*V_s; scale_s=MEDIAN(dvol_u,u=s-251..s); impact_s=r_s*scale_s/dvol_s; score_t=SUM(impact_s,s=t-19..t), undefined when dvol_s<=0
- `SIGNED_IMPACT_63` — dvol_s=P_s*V_s; scale_s=MEDIAN(dvol_u,u=s-251..s); impact_s=r_s*scale_s/dvol_s; score_t=SUM(impact_s,s=t-62..t), undefined when dvol_s<=0

### `volatility_of_volatility` — Volatility-of-volatility conditioned direction
Datasets: `V2DS001, V2DS003`.
Rationale: Instability of volatility may distinguish orderly trend from disorderly transition; both mappings are tested.
- `VOV_CONT_RV20_W20` — rv_t=STD(r_s,20)*sqrt(252); vov_t=STD(diff(ln(rv_s)),20); zvov_t=expanding_zscore(vov_t,min=252); dir_t=sign(ln(P_t/P_(t-20))); score_t = dir_t*(-zvov_t)
- `VOV_REVERSE_RV20_W20` — rv_t=STD(r_s,20)*sqrt(252); vov_t=STD(diff(ln(rv_s)),20); zvov_t=expanding_zscore(vov_t,min=252); dir_t=sign(ln(P_t/P_(t-20))); score_t = dir_t*zvov_t
- `VOV_CONT_RV20_W63` — rv_t=STD(r_s,20)*sqrt(252); vov_t=STD(diff(ln(rv_s)),63); zvov_t=expanding_zscore(vov_t,min=252); dir_t=sign(ln(P_t/P_(t-20))); score_t = dir_t*(-zvov_t)
- `VOV_REVERSE_RV20_W63` — rv_t=STD(r_s,20)*sqrt(252); vov_t=STD(diff(ln(rv_s)),63); zvov_t=expanding_zscore(vov_t,min=252); dir_t=sign(ln(P_t/P_(t-20))); score_t = dir_t*zvov_t
- `VOV_CONT_RV63_W63` — rv_t=STD(r_s,63)*sqrt(252); vov_t=STD(diff(ln(rv_s)),63); zvov_t=expanding_zscore(vov_t,min=252); dir_t=sign(ln(P_t/P_(t-20))); score_t = dir_t*(-zvov_t)
- `VOV_REVERSE_RV63_W63` — rv_t=STD(r_s,63)*sqrt(252); vov_t=STD(diff(ln(rv_s)),63); zvov_t=expanding_zscore(vov_t,min=252); dir_t=sign(ln(P_t/P_(t-20))); score_t = dir_t*zvov_t

### `cross_asset_etf_risk_appetite` — Fixed-ETF risk-appetite leadership
Datasets: `V2DS005, V2DS009, V2DS008`.
Rationale: Relative performance of growth, small caps, Dow and Treasury ETFs supplies predeclared cross-market information.
- `RISK_RATIO_QQQ_SPY_63` — ratio_s=Q_{QQQ,s}/Q_{SPY,s}; score_t=ln(ratio_t/ratio_(t-63)); candidate begins only after both ETFs exist plus 63 sessions
- `RISK_RATIO_IWM_SPY_63` — ratio_s=Q_{IWM,s}/Q_{SPY,s}; score_t=ln(ratio_t/ratio_(t-63)); candidate begins only after both ETFs exist plus 63 sessions
- `RISK_RATIO_IWM_DIA_63` — ratio_s=Q_{IWM,s}/Q_{DIA,s}; score_t=ln(ratio_t/ratio_(t-63)); candidate begins only after both ETFs exist plus 63 sessions
- `RISK_RATIO_DIA_SPY_63` — ratio_s=Q_{DIA,s}/Q_{SPY,s}; score_t=ln(ratio_t/ratio_(t-63)); candidate begins only after both ETFs exist plus 63 sessions
- `RISK_RATIO_SPY_IEF_63` — ratio_s=Q_{SPY,s}/Q_{IEF,s}; score_t=ln(ratio_t/ratio_(t-63)); candidate begins only after both ETFs exist plus 63 sessions
- `RISK_RATIO_SPY_TLT_63` — ratio_s=Q_{SPY,s}/Q_{TLT,s}; score_t=ln(ratio_t/ratio_(t-63)); candidate begins only after both ETFs exist plus 63 sessions

### `equal_weight_concentration` — Equal-weight versus cap-weight leadership
Datasets: `V2DS006, V2DS009, V2DS008`.
Rationale: Equal-weight leadership is a directly observable proxy for broad participation and concentration.
- `RSP_SPY_5` — ratio_s=Q_RSP,s/Q_SPY,s; score_t=ln(ratio_t/ratio_(t-5))
- `RSP_SPY_20` — ratio_s=Q_RSP,s/Q_SPY,s; score_t=ln(ratio_t/ratio_(t-20))
- `RSP_SPY_63` — ratio_s=Q_RSP,s/Q_SPY,s; score_t=ln(ratio_t/ratio_(t-63))
- `RSP_SPY_126` — ratio_s=Q_RSP,s/Q_SPY,s; score_t=ln(ratio_t/ratio_(t-126))
- `RSP_SPY_189` — ratio_s=Q_RSP,s/Q_SPY,s; score_t=ln(ratio_t/ratio_(t-189))
- `RSP_SPY_252` — ratio_s=Q_RSP,s/Q_SPY,s; score_t=ln(ratio_t/ratio_(t-252))

### `skewness_state` — Rolling return skewness state
Datasets: `V2DS001, V2DS003`.
Rationale: Rolling asymmetry may identify persistent positive or negative tail states; both directional interpretations are declared.
- `SKEW_CONT_20` — g_t = unbiased_sample_skew(r_s, s=t-19..t); score_t = g_t
- `SKEW_CONT_63` — g_t = unbiased_sample_skew(r_s, s=t-62..t); score_t = g_t
- `SKEW_CONT_126` — g_t = unbiased_sample_skew(r_s, s=t-125..t); score_t = g_t
- `SKEW_CONTRA_20` — g_t = unbiased_sample_skew(r_s, s=t-19..t); score_t = -g_t
- `SKEW_CONTRA_63` — g_t = unbiased_sample_skew(r_s, s=t-62..t); score_t = -g_t
- `SKEW_CONTRA_126` — g_t = unbiased_sample_skew(r_s, s=t-125..t); score_t = -g_t

### `cusum_change_state` — Two-sided Page CUSUM direction state
Datasets: `V2DS001, V2DS003`.
Rationale: Sequential change detection supplies a state machine distinct from fixed lookback momentum.
- `CUSUM_K0_H3` — z_t=(r_t-expanding_mean(r,min=252))/expanding_std(r,min=252); gplus_t=max(0,gplus_(t-1)+z_t-0); gminus_t=min(0,gminus_(t-1)+z_t+0); if gplus_t>=3: emit +1 and reset both to 0; elif gminus_t<=-3: emit -1 and reset both; else preserve prior position
- `CUSUM_K0_H5` — z_t=(r_t-expanding_mean(r,min=252))/expanding_std(r,min=252); gplus_t=max(0,gplus_(t-1)+z_t-0); gminus_t=min(0,gminus_(t-1)+z_t+0); if gplus_t>=5: emit +1 and reset both to 0; elif gminus_t<=-5: emit -1 and reset both; else preserve prior position
- `CUSUM_K0p25_H3` — z_t=(r_t-expanding_mean(r,min=252))/expanding_std(r,min=252); gplus_t=max(0,gplus_(t-1)+z_t-0.25); gminus_t=min(0,gminus_(t-1)+z_t+0.25); if gplus_t>=3: emit +1 and reset both to 0; elif gminus_t<=-3: emit -1 and reset both; else preserve prior position
- `CUSUM_K0p25_H5` — z_t=(r_t-expanding_mean(r,min=252))/expanding_std(r,min=252); gplus_t=max(0,gplus_(t-1)+z_t-0.25); gminus_t=min(0,gminus_(t-1)+z_t+0.25); if gplus_t>=5: emit +1 and reset both to 0; elif gminus_t<=-5: emit -1 and reset both; else preserve prior position
- `CUSUM_K0p5_H3` — z_t=(r_t-expanding_mean(r,min=252))/expanding_std(r,min=252); gplus_t=max(0,gplus_(t-1)+z_t-0.5); gminus_t=min(0,gminus_(t-1)+z_t+0.5); if gplus_t>=3: emit +1 and reset both to 0; elif gminus_t<=-3: emit -1 and reset both; else preserve prior position
- `CUSUM_K0p5_H5` — z_t=(r_t-expanding_mean(r,min=252))/expanding_std(r,min=252); gplus_t=max(0,gplus_(t-1)+z_t-0.5); gminus_t=min(0,gminus_(t-1)+z_t+0.5); if gplus_t>=5: emit +1 and reset both to 0; elif gminus_t<=-5: emit -1 and reset both; else preserve prior position

### `causal_shallow_tree` — Frozen causal shallow decision tree
Datasets: `V2DS001, V2DS002, V2DS003`.
Rationale: A shallow tree permits only a small number of interpretable interactions among ten fixed causal features.
- `TREE_D1_LEAF126` — Features fixed in order: r_on_1, r_id_1, clv_1, body_1, ret_5, ret_20, semivar_balance_20, positive_day_balance_20, signed_abnormal_volume_5, parkinson_ratio_5_20. At the first SPY session of each month fit sklearn DecisionTreeClassifier(criterion='log_loss',splitter='best',max_depth=1,min_samples_leaf=126,min_samples_split=2,max_features=None,random_state=20260805,max_leaf_nodes=None,min_impurity_decrease=0.0,class_weight=None,ccp_alpha=0.0) on an expanding sample. Label for decision date s is I[target open-to-open total return earned from open s+1 to open s+2 > 0]; at close t only labels whose ending open has already occurred may be used. Require >=1260 complete labeled rows and both classes. Missing predictors use medians fitted on that training sample. score_t=P(y=1|x_t)-0.5; probability equality or pre-fit period preserves prior state.
- `TREE_D1_LEAF252` — Features fixed in order: r_on_1, r_id_1, clv_1, body_1, ret_5, ret_20, semivar_balance_20, positive_day_balance_20, signed_abnormal_volume_5, parkinson_ratio_5_20. At the first SPY session of each month fit sklearn DecisionTreeClassifier(criterion='log_loss',splitter='best',max_depth=1,min_samples_leaf=252,min_samples_split=2,max_features=None,random_state=20260805,max_leaf_nodes=None,min_impurity_decrease=0.0,class_weight=None,ccp_alpha=0.0) on an expanding sample. Label for decision date s is I[target open-to-open total return earned from open s+1 to open s+2 > 0]; at close t only labels whose ending open has already occurred may be used. Require >=1260 complete labeled rows and both classes. Missing predictors use medians fitted on that training sample. score_t=P(y=1|x_t)-0.5; probability equality or pre-fit period preserves prior state.
- `TREE_D2_LEAF126` — Features fixed in order: r_on_1, r_id_1, clv_1, body_1, ret_5, ret_20, semivar_balance_20, positive_day_balance_20, signed_abnormal_volume_5, parkinson_ratio_5_20. At the first SPY session of each month fit sklearn DecisionTreeClassifier(criterion='log_loss',splitter='best',max_depth=2,min_samples_leaf=126,min_samples_split=2,max_features=None,random_state=20260805,max_leaf_nodes=None,min_impurity_decrease=0.0,class_weight=None,ccp_alpha=0.0) on an expanding sample. Label for decision date s is I[target open-to-open total return earned from open s+1 to open s+2 > 0]; at close t only labels whose ending open has already occurred may be used. Require >=1260 complete labeled rows and both classes. Missing predictors use medians fitted on that training sample. score_t=P(y=1|x_t)-0.5; probability equality or pre-fit period preserves prior state.
- `TREE_D2_LEAF252` — Features fixed in order: r_on_1, r_id_1, clv_1, body_1, ret_5, ret_20, semivar_balance_20, positive_day_balance_20, signed_abnormal_volume_5, parkinson_ratio_5_20. At the first SPY session of each month fit sklearn DecisionTreeClassifier(criterion='log_loss',splitter='best',max_depth=2,min_samples_leaf=252,min_samples_split=2,max_features=None,random_state=20260805,max_leaf_nodes=None,min_impurity_decrease=0.0,class_weight=None,ccp_alpha=0.0) on an expanding sample. Label for decision date s is I[target open-to-open total return earned from open s+1 to open s+2 > 0]; at close t only labels whose ending open has already occurred may be used. Require >=1260 complete labeled rows and both classes. Missing predictors use medians fitted on that training sample. score_t=P(y=1|x_t)-0.5; probability equality or pre-fit period preserves prior state.
- `TREE_D3_LEAF126` — Features fixed in order: r_on_1, r_id_1, clv_1, body_1, ret_5, ret_20, semivar_balance_20, positive_day_balance_20, signed_abnormal_volume_5, parkinson_ratio_5_20. At the first SPY session of each month fit sklearn DecisionTreeClassifier(criterion='log_loss',splitter='best',max_depth=3,min_samples_leaf=126,min_samples_split=2,max_features=None,random_state=20260805,max_leaf_nodes=None,min_impurity_decrease=0.0,class_weight=None,ccp_alpha=0.0) on an expanding sample. Label for decision date s is I[target open-to-open total return earned from open s+1 to open s+2 > 0]; at close t only labels whose ending open has already occurred may be used. Require >=1260 complete labeled rows and both classes. Missing predictors use medians fitted on that training sample. score_t=P(y=1|x_t)-0.5; probability equality or pre-fit period preserves prior state.
- `TREE_D3_LEAF252` — Features fixed in order: r_on_1, r_id_1, clv_1, body_1, ret_5, ret_20, semivar_balance_20, positive_day_balance_20, signed_abnormal_volume_5, parkinson_ratio_5_20. At the first SPY session of each month fit sklearn DecisionTreeClassifier(criterion='log_loss',splitter='best',max_depth=3,min_samples_leaf=252,min_samples_split=2,max_features=None,random_state=20260805,max_leaf_nodes=None,min_impurity_decrease=0.0,class_weight=None,ccp_alpha=0.0) on an expanding sample. Label for decision date s is I[target open-to-open total return earned from open s+1 to open s+2 > 0]; at close t only labels whose ending open has already occurred may be used. Require >=1260 complete labeled rows and both classes. Missing predictors use medians fitted on that training sample. score_t=P(y=1|x_t)-0.5; probability equality or pre-fit period preserves prior state.


Implementa exactamente `candidate_strategy_pack.jsonl`; la lista anterior repite las decisiones esenciales y no autoriza reinterpretaciones.

## 6. Novedad y cardinalidad

Exige:

```text
V2 candidates = 144
strategy IDs = V2STRAT0001 through V2STRAT0144
V2 families = 24
variants per family = 6
features = 144
benchmarks = 5
terminal units = 149
unique V2 economic signatures = 144
exact V1 hash collisions = 0
```

Recalcula cada firma económica con la canonicalización del manifest. Revisa también solapamiento semántico mediante `canonical_novelty_audit.csv`.

Una familia cercana a V1 sólo es admisible si conserva la diferencia congelada: por ejemplo, signed semivariance no es realized-volatility state; momentum acceleration no es endpoint momentum; fixed-ETF breadth no es constituent breadth.

## 7. Cumulative multiple testing: no reset

La búsqueda histórica total es:

```text
V1 declared = 168
V2 declared = 144
total binding = 312
```

Reglas obligatorias:

1. DSR binding usa 312 trials.
2. FDR se calcula sobre 312 declaraciones.
3. Los 103 rechazos V1 permanecen declarados con `p=1` únicamente para bookkeeping FDR; nunca reciben retorno cero.
4. WRC/SPA/PBO combinados cargan las 65 series diarias V1 evaluadas y todas las V2 evaluadas.
5. Usa un intervalo causal común de al menos 1.500 sesiones.
6. Compara contra el más fuerte de los cinco benchmarks.
7. Bootstrap final: mínimo 5.000 repeticiones deterministas.
8. Sensibilidad de bloques: 5, 10, 15, 20 y 60.
9. Conserva y publica resultados V1, V2 y combinados por separado.
10. Si no puedes reconstruir las 65 series V1 o el intervalo común, no hay finalistas y no se abre validación.

## 8. Benchmarks

Implementa exactamente:

```text
buy_and_hold_spy_total_return = +1
always_long = +1
always_short = -1
symmetric_sma_200:
  +1 if audited TR close_t > SMA200_t
  -1 if audited TR close_t < SMA200_t
  tie holds
symmetric_momentum_12m:
  +1 if audited TR close_t / audited TR close_(t-252) - 1 > 0
  -1 if < 0
  tie holds
```

`buy_and_hold` debe coincidir con `always_long`. `always_short` debe ser el negativo diario exacto.

## 9. Tests obligatorios

Antes del smoke, implementa al menos:

```text
package and embedded-prior SHA tests
UTF-8/CSV/JSON/JSONL/YAML schema tests
144/24x6/144/5 cardinality tests
canonical signature and V1 collision tests
all six costs exactly zero
positions only -1/+1
initial +1 and state persistence
next-session-open timing
holiday and extraordinary closure tests
corporate-action and ex-dividend hand calculations
long/short daily-return identity
adjusted-close-as-open rejection
OHLC inequalities and split normalization
volume inverse split normalization
overnight + intraday = close-to-close identity
CLV and body hand calculations
Parkinson range hand calculation
semivariance hand calculation
MAD zero and robust-tail threshold tests
variance-ratio reference fixture
autocorrelation paired-window fixture
Newey-West slope t-stat reference fixture
fixed-ETF inception rejection
panel completeness and no future fill
price-only ETF ratio test
sector breadth/dispersion hand calculation
CUSUM recursion and reset test
tree label-delay anti-lookahead test
tree monthly refit test
tree exact hyperparameter test
reference-vs-optimized equality for every family
two-clean-run deterministic hashes
V1 artifact ingestion and 65-stream count
312-trial DSR/FDR tests
combined WRC/SPA/PBO common-window tests
checkpoint recovery and partial retry
merge exact coverage 149/149
validation freeze immutability
locked firewall scanning data, cache, filenames, Parquet metadata and logs
```

## 10. Ejecución en GitHub Actions

El entorno local de Codex sólo puede hacer inspección, edición, lint, tipos y unit tests pequeños/sintéticos. Descargas completas, backtests, bootstrap, merge y validación se ejecutan en GitHub Actions.

### Preflight

Debe verificar:

- todos los hashes;
- V1 artifacts;
- schemas;
- cardinalidad;
- adapters;
- fuente y cobertura;
- fórmula de referencia;
- locked firewall;
- capacidad de extraer 65 V1 daily streams.

### Smoke

Ejecuta al menos:

```text
V2STRAT0001
V2STRAT0031
V2STRAT0091
V2STRAT0103
V2STRAT0139
five benchmarks
```

Haz dos ejecuciones limpias y exige hash científico idéntico.

### Pilot

Mide:

```text
candidate_blocks
family_blocks
cost_balanced_blocks
processes 1..min(4,vCPU)
```

Mide wall time, startup, merge, memoria, CPU, FeatureStore hit rate, artifact size y granularidad de recuperación. Elige la configuración medida más rápida y exacta. No presupongas 360 jobs.

### Full train

Ejecuta 144 candidatos y cinco benchmarks. Cada candidato termina como `evaluated` o `rejected` con causa. Cero missing/unsupported silenciosos.

### Merge and select

- cobertura 149/149;
- no duplicados;
- métricas OOF;
- ranking congelado;
- Pareto;
- WRC/SPA/FDR/DSR/PBO acumulados;
- un máximo de un finalista por familia y 20 total;
- sólo track `pre_2011_evidence`.

## 11. Train gates

Un finalista debe superar todos:

```text
CAGR > 0
Sharpe > 0.30
Calmar > 0.25
max drawdown > -55%
positive years >= 60%
median rolling 3y CAGR > 0
worst outer-fold CAGR > -30%
single-year contribution <= 60%
at least half neighboring variants CAGR>0 and Sharpe>0
DSR probability > 0.80 using 312 trials
candidate SPA p <= 0.10
candidate FDR q <= 0.10
global combined SPA p <= 0.10
combined PBO < 0.50
```

No representante diagnóstico puede abrir validación.

## 12. Freeze y autorización de validación

Antes de leer validación, crea y verifica:

```text
v2_train_selection_freeze.json
```

Incluye:

- commit SHA;
- hashes de código, datos, entorno, V1 artifacts y V2 candidates;
- 149 unidades terminales;
- ranking y Pareto;
- todos los tests acumulados;
- lista finalista;
- reglas/params;
- estado locked;
- confirmación de track pre-2011;
- autorización requerida.

Esta petición concede una sola autorización exacta:

```text
OPEN_VALIDATION_2011_2020_ONCE_V2
```

Sólo abre validación si hay al menos un finalista elegible. Si no hay, entrega `NEGATIVE_RESULT` sin leerla.

Los 12 candidatos `post_2010_research` no son elegibles para una validación temporal 2011–2020.

## 13. Validación one-shot

Para finalistas congelados únicamente:

- 2011-01-01 a 2020-12-31;
- una ejecución;
- sin retune;
- sin nueva variante;
- sin cambio de signo;
- sin reparación motivada por resultado;
- sin reordenar por validación;
- sin segundo intento.

Aplica todos los gates de `acceptance_gates.md`. Si ninguno pasa, `NEGATIVE_RESULT`.

## 14. Locked absoluto

Prohíbe cualquier dato `>=2021-01-01`, incluso para:

- comprobar APIs;
- completar calendario;
- probar schema;
- reconciliar corporate actions;
- crear ejemplos;
- mostrar logs;
- rellenar caché.

Ante una observación locked:

```text
TECHNICAL_FAILURE_LOCKED_BREACH
```

No imprimas su valor.

## 15. Workflow y comandos preparados

Primero inspecciona los inputs reales:

```bash
gh workflow view _aurora-future-run-v3.yml   --repo trading-optimizer-lab-org/aurora   --yaml
```

El comando esperado, siguiendo el patrón V1, es:

```bash
gh workflow run _aurora-future-run-v3.yml   --repo trading-optimizer-lab-org/aurora   --ref codex/sp500-long-short-daily-research-v2   -f spec_path=config/sp500_long_short_daily_v2_train_v3.yaml   -f workload=aurora.infra.sp500_long_short_daily_v2.workload:TRAIN_WORKLOAD   -f run_label=sp500-ls-v2-new-strategies-r1   -f retention_days=90   -f execution_mode=optimized   -f forced_job_count=0
```

Adapta únicamente nombres de inputs si el workflow real lo exige; documenta el mapping. Usa:

```bash
gh run list --repo trading-optimizer-lab-org/aurora --workflow _aurora-future-run-v3.yml --limit 30
gh run view <RUN_ID> --repo trading-optimizer-lab-org/aurora --log-failed
gh run download <RUN_ID> --repo trading-optimizer-lab-org/aurora -D artifacts/<RUN_ID>
```

Relanza sólo unidades failed/pending con inputs y hashes idénticos. Nunca relances todo por comodidad.

## 16. Artifacts y outputs

Nombres recomendados:

```text
sp500-ls-v2-preflight-<run_id>
sp500-ls-v2-smoke-<run_id>
sp500-ls-v2-pilot-<run_id>
sp500-ls-v2-full-train-<run_id>-<shard>
sp500-ls-v2-train-merged-<run_id>
sp500-ls-v2-freeze-<run_id>
sp500-ls-v2-validation-once-<run_id>
sp500-ls-v2-final-verified-<run_id>
```

Artifact final mínimo:

```text
RESULT_STATUS.md
final_manifest.json
v2_train_selection_freeze.json
candidate_and_benchmark_metrics.csv
v2_train_daily_returns.parquet
validation_daily_returns.parquet  # sólo si se abrió legítimamente
annual_returns.csv
rolling_metrics.csv
regime_metrics.csv
fold_metrics.csv
eligibility_and_rejections.csv
family_coverage.csv
pareto_frontier.csv
near_misses.csv
combined_multiple_testing_results.json
v1_ingestion_audit.json
cumulative_trial_ledger.csv
causality_audit.json
data_lineage.jsonl
raw_manifest.jsonl
scheduler_plan.json
environment_lock.txt
implementation_mapping.md
scientific_warnings.md
```

## 17. Estados finales

```text
POSITIVE_VALIDATED_RESULT
NEGATIVE_RESULT
VALIDATION_NOT_OPENED
COMBINED_MULTIPLICITY_INCOMPLETE
TECHNICAL_FAILURE
```

`POSITIVE_VALIDATED_RESULT` exige al menos un finalista pre-2011 congelado que supere train acumulado y validación one-shot.

`NEGATIVE_RESULT` exige campaña técnicamente válida sin candidato final confirmado.

## 18. Commits y draft PR

Commits sugeridos:

```text
chore: ingest and verify SP500 V2 research package
feat: add split-normalized OHLCV and fixed ETF panel
feat: implement 24 V2 signal families
test: add V2 causal and cumulative multiplicity regression tests
ci: add SP500 V2 GitHub Actions campaign
feat: add V1 plus V2 selection freeze and validation guard
```

Abre una **nueva draft PR**. No hagas merge automático. No cierres ni reescribas PR #114.

## 19. Verificación final y respuesta

No declares terminado hasta comprobar:

- rama remota;
- commits;
- draft PR nueva;
- CI;
- run final;
- artifact descargado;
- hashes;
- 144/144 terminales o rechazos explícitos;
- 5/5 benchmarks;
- 312 trials contabilizados;
- 65 streams V1 ingeridos;
- WRC/SPA/FDR/DSR/PBO acumulados;
- freeze;
- validación una sola vez o motivo científico correcto para no abrir;
- locked cerrado.

Tu respuesta final empieza con el estado y muestra:

- repository, branch, commit y PR;
- run IDs y artifacts;
- cobertura;
- evaluadas/rechazadas;
- top train OOF;
- Pareto;
- estadísticas acumuladas;
- finalistas;
- validación;
- tiempos, jobs y retries;
- limitaciones;
- confirmación explícita de que 2021+ no se abrió.

Continúa hasta completar la ejecución. No sustituyas el trabajo por un plan.

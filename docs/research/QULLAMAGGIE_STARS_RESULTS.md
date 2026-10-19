# Qullamaggie fase 3, selección de "5 estrellas": resultados

Run de GitHub: [39126912375](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39126912375). Reglas:
[QULLAMAGGIE_STARS_PREREGISTRATION.md](QULLAMAGGIE_STARS_PREREGISTRATION.md). Sesgo de supervivencia sin corregir.
Periodo bloqueado (2021+) sin leer.

## Resumen en español

- **Sus 9 criterios "5 estrellas", contados, no distinguen las buenas rupturas**: AUC 0,49 en 1995-2010 y 0,48 en
  2011-2020 (0,5 = azar). La rentabilidad media no sube con el número de estrellas.
- **El modelo entrenado solo con 1995-2010 sí ordena, también fuera de muestra**: AUC 0,64 en entrenamiento, 0,60
  en 2011-2020 (0,58 en 2011-2015, 0,60 en 2016-2020). Lo que más pesa: ADR alto (+0,36), base estrecha (-0,20 por
  cada unidad de rango), industria fuerte (+0,12), mercado subiendo en el mes (+0,12) y hueco de apertura (+0,11).
  Varios signos van **al revés** de lo que se atribuye a sus mejores operaciones (mercado no estirado, sin hueco,
  volumen seco).
- **Rupturas diarias con el modelo**: pierden mucho menos (2011-2020 de -21,6%/año a entre -1,7% y +0,9%; caída de
  -92% a -16%/-32%) y el PF fuera de muestra sube de 0,97 a 1,04-1,20, pero no hay beneficio.
- **Rupturas intradía con el modelo, las 3 mejores del día** (`I_BO_MODEL_N3`): 12,7-14,5%/año, Sortino 2,07-2,44,
  caída -14% a -17%, positivas en los dos tramos; no pasan por rendir menos que el SPY (15,1%).
- **Cartera mixta (todos los EP + las 3 rupturas mejor puntuadas): las 8 versiones pasan los criterios en
  2016-2020.** La mejor, `I_MIX_MODEL_N3_E0`: **39,8%/año, Sortino 4,45, caída -18,5%**; 2016-2018 22,7%/año
  (Sortino 2,51) y 2019-2020 70,1% (Sortino 7,40). Frente al EP solo de la fase 2 (2016-2018: 5,3%/año), la
  selección de rupturas arregla el tramo flojo.
- **Pero no es una prueba**: deflated Sharpe máximo 0,30 (249.166 pruebas), 2016-2020 ya visto y las piezas (EP,
  salida, rango de apertura) se eligieron mirando ese periodo. El modelo sí es limpio para 2011-2020 (nunca lo
  vio). La única confirmación posible es el periodo bloqueado 2021+ o paper trading.

## Informe completo (generado por el código)

# Qullamaggie phase 3: 5-star setup selection (pre-registered, 24 trials)

24 of 24 trials; deflated Sharpe over 249,166 trials. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. Columns per period: monthly Sortino | CAGR | max drawdown of the portfolio.

SPY: 1995-2010 0.54 | 8.4% | -55.2% · 2011-2020 1.60 | 13.8% | -33.7% · 2016-2020 1.45 | 15.1% | -33.7%.

## 1. How well the scores rank breakouts (daily SCAN35 stream)

Model trained on 10,715 trades of 1995-2010 (1,072 in the top 10%). Coefficients (standardised features): intercept -2.273, steady -0.001, tight -0.196, dryup +0.085, near10 +0.008, mkt1m +0.115, gap +0.112, indrs +0.123, rs -0.069, m1 +0.072, adr +0.358.

| period | AUC stars | AUC model |
|---|---|---|
| train | 0.489 | 0.638 |
| validation | 0.478 | 0.601 |
| val1 | 0.519 | 0.579 |
| val2 | 0.463 | 0.601 |

Average trade return by number of stars (trades in brackets):

| stars | 1995-2010 | 2011-2020 |
|---|---|---|
| 0 | +0.30% (56) | +3.27% (40) |
| 1 | +0.61% (589) | -1.01% (466) |
| 2 | -0.52% (1841) | +0.09% (1767) |
| 3 | -0.66% (3024) | -0.47% (2965) |
| 4 | -0.36% (2762) | -0.45% (2937) |
| 5 | -0.68% (1693) | -0.46% (1716) |
| 6 | -0.51% (583) | -0.08% (676) |
| 7 | +0.87% (150) | -0.47% (172) |
| 8 | +2.65% (15) | -1.36% (35) |
| 9 | -0.41% (2) | +0.66% (3) |

## 2. Daily breakouts with selection, 1995-2020

| trial | 1995-2010 Sortino | CAGR | max DD | 2011-2020 Sortino | CAGR | max DD | trades 11-20 | PF 11-20 | best 5% captured | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| D_BO_STARS_N1_E0 | -0.10 | 3.0% | -11.8% | -0.65 | -1.3% | -22.0% | 347 | 0.89 | 6% | 0.00 | no |
| D_BO_STARS_N1_E3_C10 | -0.14 | 2.8% | -10.9% | -0.26 | -0.1% | -11.0% | 260 | 1.04 | 4% | 0.00 | no |
| D_BO_STARS_N3_E0 | -0.97 | -2.5% | -45.1% | -0.83 | -3.8% | -32.9% | 922 | 0.94 | 16% | 0.00 | no |
| D_BO_STARS_N3_E3_C10 | -0.91 | -1.9% | -43.0% | -0.58 | -2.2% | -22.8% | 677 | 1.00 | 11% | 0.00 | no |
| D_BO_MODEL_N1_E0 | 0.40 | 4.4% | -11.8% | -0.19 | -0.1% | -17.3% | 375 | 1.11 | 14% | 0.00 | no |
| D_BO_MODEL_N1_E3_C10 | 0.48 | 4.6% | -11.5% | -0.08 | 0.2% | -16.1% | 275 | 1.20 | 11% | 0.00 | no |
| D_BO_MODEL_N3_E0 | 0.19 | 3.9% | -29.9% | -0.38 | -1.7% | -31.6% | 1,071 | 1.04 | 32% | 0.00 | no |
| D_BO_MODEL_N3_E3_C10 | 0.76 | 6.9% | -17.2% | 0.15 | 0.9% | -23.4% | 809 | 1.17 | 26% | 0.00 | no |

## 3. Intraday setups with selection, 2016-2020

| trial | 2016-2018 Sortino | CAGR | max DD | 2019-2020 Sortino | CAGR | max DD | 2016-2020 Sortino | CAGR | max DD | trades | PF | best 5% captured | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| I_BO_STARS_N1_E0 | 1.43 | 5.9% | -11.3% | 1.85 | 6.7% | -7.0% | 1.59 | 6.2% | -11.3% | 108 | 1.66 | 2% | 0.04 | no |
| I_BO_STARS_N1_E3_C10 | 1.28 | 3.7% | -6.4% | 2.14 | 5.3% | -5.1% | 1.62 | 4.4% | -6.4% | 85 | 1.93 | 1% | 0.03 | no |
| I_BO_STARS_N3_E0 | 0.61 | 3.6% | -17.3% | 0.92 | 5.2% | -10.9% | 0.74 | 4.2% | -17.3% | 307 | 1.37 | 5% | 0.01 | no |
| I_BO_STARS_N3_E3_C10 | 1.91 | 6.1% | -10.1% | 1.31 | 4.7% | -5.4% | 1.68 | 5.5% | -10.1% | 227 | 1.54 | 3% | 0.03 | no |
| I_BO_MODEL_N1_E0 | 3.41 | 11.4% | -13.0% | -1.22 | -5.1% | -13.0% | 0.96 | 4.5% | -14.2% | 113 | 1.15 | 4% | 0.01 | no |
| I_BO_MODEL_N1_E3_C10 | 3.17 | 8.9% | -7.5% | -1.41 | -4.7% | -15.8% | 0.71 | 3.2% | -15.8% | 84 | 1.33 | 3% | 0.01 | no |
| I_BO_MODEL_N3_E0 | 2.74 | 18.5% | -16.6% | 1.19 | 8.8% | -11.9% | 2.07 | 14.5% | -16.6% | 327 | 1.65 | 18% | 0.04 | no |
| I_BO_MODEL_N3_E3_C10 | 3.33 | 15.3% | -8.4% | 1.46 | 8.9% | -14.2% | 2.44 | 12.7% | -14.2% | 248 | 1.88 | 14% | 0.07 | no |
| I_MIX_STARS_N1_E0 | 1.70 | 10.9% | -13.3% | 8.42 | 72.4% | -16.9% | 4.74 | 32.4% | -16.9% | 734 | 1.43 | 32% | 0.28 | YES |
| I_MIX_STARS_N1_E3_C10 | 1.72 | 7.5% | -9.3% | 6.47 | 52.5% | -21.4% | 4.23 | 23.7% | -21.4% | 500 | 1.37 | 22% | 0.12 | YES |
| I_MIX_STARS_N3_E0 | 0.92 | 7.2% | -17.5% | 6.98 | 63.6% | -18.2% | 3.49 | 27.0% | -18.2% | 930 | 1.38 | 34% | 0.15 | YES |
| I_MIX_STARS_N3_E3_C10 | 1.51 | 7.7% | -9.3% | 6.87 | 50.3% | -21.5% | 4.15 | 23.1% | -21.5% | 640 | 1.33 | 23% | 0.11 | YES |
| I_MIX_MODEL_N1_E0 | 2.30 | 14.2% | -17.5% | 7.29 | 57.6% | -15.4% | 4.54 | 30.0% | -17.5% | 743 | 1.37 | 34% | 0.22 | YES |
| I_MIX_MODEL_N1_E3_C10 | 2.13 | 10.6% | -9.9% | 5.14 | 40.5% | -22.5% | 3.64 | 21.8% | -22.5% | 499 | 1.31 | 23% | 0.10 | YES |
| I_MIX_MODEL_N3_E0 | 2.51 | 22.7% | -18.5% | 7.40 | 70.1% | -15.2% | 4.45 | 39.8% | -18.5% | 946 | 1.45 | 41% | 0.30 | YES |
| I_MIX_MODEL_N3_E3_C10 | 2.78 | 17.0% | -10.8% | 6.99 | 55.5% | -20.3% | 4.75 | 31.1% | -20.3% | 654 | 1.44 | 30% | 0.16 | YES |

## 4. Pre-registered criteria (2011-2020 daily, 2016-2020 intraday)

Passed: I_MIX_STARS_N1_E0, I_MIX_STARS_N1_E3_C10, I_MIX_STARS_N3_E0, I_MIX_STARS_N3_E3_C10, I_MIX_MODEL_N1_E0, I_MIX_MODEL_N1_E3_C10, I_MIX_MODEL_N3_E0, I_MIX_MODEL_N3_E3_C10.

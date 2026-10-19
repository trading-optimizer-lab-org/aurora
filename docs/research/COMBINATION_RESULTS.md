# Fase 7a, combinar las mejores estrategias: resultados

Run de GitHub: [39147489147](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39147489147). Reglas:
[COMBINATION_PREREGISTRATION.md](COMBINATION_PREREGISTRATION.md). Detalle fijado antes de ver resultados: la
volatilidad del reparto por riesgo tiene un suelo del 2% anual (una estrategia sin operaciones no puede llevarse
todo el peso); los pesos se fijan cada mes y se aplican a diario. Sesgo de supervivencia sin corregir. Periodo
bloqueado (2021+) sin leer.

## Comprobaciones

Las 8 estrategias reconstruidas coinciden con sus resultados publicados (diferencia máxima 4e-14).

## Resumen en español

- **Las intradía casi no se parecen entre sí ni al mercado** (correlaciones mensuales 0,13-0,26). Las diarias de
  compra sí se parecen mucho entre ellas y al SPY (0,39-0,77). Los cortos parabólicos van al revés que las diarias
  (-0,2 a -0,3), pero de la mano de los EP de noticias (+0,58): las dos viven de las euforias.
- **Juntar las 3 intradía a partes iguales sube el Sortino de 2-3,4 a 4,92** (`INTRADAY_EQ`): 16,5%/año, caída
  máxima -7,7%, peor mes -2,1%. Es la única combinación que pasa los criterios (rinde algo más que el SPY con una
  quinta parte de su caída).
- **Las 8 juntas** (`ALL_EQ`, `ALL_RP`): Sortino 3,2, caída -7% a -10%, y el deflated Sharpe más alto de toda la
  búsqueda (0,71-0,72), aunque no llega a 0,95 y rinden menos que el SPY.
- **Lo más robusto en 26 años**: las 5 diarias repartidas por riesgo (`DAILY_RP`): Sortino 2,65 en 1995-2010 y 2,78
  en 2011-2020, caída máxima -5,8% / -8,4%, pero solo 9-10%/año.
- **La cobertura con SPY baja las caídas y el peor mes pero también la rentabilidad**: el Sortino no mejora salvo
  en 1995-2010. **Apuntar a un 15% de volatilidad empeora** en todos los grupos.
- **Sortino 10: no.** El máximo es 4,92. Con correlaciones de ~0,2 entre estrategias de Sortino ~3, el límite es
  ~6,7 aunque se junten infinitas (3 x raíz de 1/0,2). Para llegar a 10 harían falta ~20 estrategias de Sortino 3
  con correlación ~0,05 entre ellas.

## Informe completo (generado por el código)

# Phase 7a: combining the best strategy streams (pre-registered, 12 combinations)

Deflated Sharpe over 249,210 trials. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. Risk-parity volatilities are floored at 2% a year.

## 1. Monthly-return correlations, 2016-2020

| | ACCUM | SQUEEZE | LOWVOL | IPO | PARA_SHORT | EP_EARN | EP_NEWS | BO_TOP3 | SPY |
|---|---|---|---|---|---|---|---|---|---|
| ACCUM | +1.00 | +0.74 | +0.57 | +0.47 | -0.28 | +0.22 | +0.14 | +0.17 | +0.56 |
| SQUEEZE | +0.74 | +1.00 | +0.66 | +0.48 | -0.31 | +0.24 | +0.18 | +0.12 | +0.77 |
| LOWVOL | +0.57 | +0.66 | +1.00 | +0.39 | -0.22 | +0.14 | +0.14 | +0.02 | +0.64 |
| IPO | +0.47 | +0.48 | +0.39 | +1.00 | -0.11 | +0.18 | +0.12 | +0.25 | +0.41 |
| PARA_SHORT | -0.28 | -0.31 | -0.22 | -0.11 | +1.00 | +0.14 | +0.58 | +0.06 | -0.22 |
| EP_EARN | +0.22 | +0.24 | +0.14 | +0.18 | +0.14 | +1.00 | +0.21 | +0.22 | +0.26 |
| EP_NEWS | +0.14 | +0.18 | +0.14 | +0.12 | +0.58 | +0.21 | +1.00 | +0.13 | +0.20 |
| BO_TOP3 | +0.17 | +0.12 | +0.02 | +0.25 | +0.06 | +0.22 | +0.13 | +1.00 | +0.23 |
| SPY | +0.56 | +0.77 | +0.64 | +0.41 | -0.22 | +0.26 | +0.20 | +0.23 | +1.00 |

## 2. Streams alone, 2016-2020

| stream | Sortino | CAGR | max DD | total | worst month | positive months |
|---|---|---|---|---|---|---|
| ACCUM | 1.58 | 15.9% | -23.1% | +109% | -13.1% | 67% |
| SQUEEZE | 1.71 | 15.7% | -23.0% | +107% | -9.0% | 72% |
| LOWVOL | 1.72 | 12.6% | -14.9% | +81% | -7.9% | 63% |
| IPO | 1.48 | 11.6% | -16.1% | +73% | -9.6% | 65% |
| PARA_SHORT | 0.72 | 3.3% | -10.8% | +18% | -5.0% | 53% |
| EP_EARN | 3.29 | 15.2% | -8.7% | +103% | -6.2% | 67% |
| EP_NEWS | 3.35 | 16.9% | -15.1% | +118% | -6.0% | 47% |
| BO_TOP3 | 2.07 | 14.5% | -16.6% | +97% | -5.7% | 50% |
| SPY | 1.45 | 15.1% | -33.7% | +102% | -12.5% | 77% |

Daily streams over the long history (1995-2010 / 2011-2020): ACCUM Sortino 2.03 / 1.80; SQUEEZE Sortino 1.85 / 1.69; LOWVOL Sortino 1.22 / 2.11; IPO Sortino 2.20 / 2.33; PARA_SHORT Sortino 0.18 / 0.91.

## 3. Combinations, 2016-2020

| combination | Sortino | CAGR | max DD | total | worst month | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|
| INTRADAY_EQ | 4.92 | 16.5% | -7.7% | +114% | -2.1% | 62% | 0.39 | YES |
| INTRADAY_RP | 4.14 | 14.6% | -6.8% | +97% | -3.1% | 60% | 0.33 | no |
| INTRADAY_RPH | 3.33 | 12.3% | -6.6% | +78% | -4.1% | 58% | 0.19 | no |
| INTRADAY_RPH_VT | 1.93 | 15.1% | -21.2% | +102% | -5.3% | 57% | 0.10 | no |
| DAILY_EQ | 2.07 | 12.2% | -13.3% | +78% | -7.6% | 67% | 0.33 | no |
| DAILY_RP | 2.20 | 9.3% | -8.4% | +56% | -5.7% | 67% | 0.46 | no |
| DAILY_RPH | 1.72 | 5.6% | -4.4% | +31% | -3.2% | 60% | 0.11 | no |
| DAILY_RPH_VT | 0.78 | 6.8% | -14.3% | +39% | -10.2% | 55% | 0.01 | no |
| ALL_EQ | 3.20 | 14.0% | -10.3% | +92% | -5.3% | 73% | 0.71 | no |
| ALL_RP | 3.23 | 11.6% | -6.8% | +73% | -4.5% | 70% | 0.72 | no |
| ALL_RPH | 2.88 | 8.3% | -3.7% | +49% | -2.7% | 63% | 0.46 | no |
| ALL_RPH_VT | 1.71 | 13.1% | -13.9% | +85% | -8.7% | 55% | 0.16 | no |

## 4. DAILY set over the long history

| combination | 1995-2010 Sortino | CAGR | max DD | total | worst month | positive | 2011-2020 Sortino | CAGR | max DD | total | worst month | positive |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DAILY_EQ | 2.39 | 13.9% | -10.6% | +704% | -6.1% | 68% | 2.54 | 12.2% | -13.3% | +215% | -7.6% | 68% |
| DAILY_RP | 2.65 | 9.9% | -5.8% | +350% | -3.4% | 73% | 2.78 | 8.7% | -8.4% | +131% | -5.7% | 69% |
| DAILY_RPH | 2.81 | 8.4% | -3.8% | +262% | -2.7% | 73% | 2.06 | 5.0% | -4.7% | +63% | -3.2% | 63% |
| DAILY_RPH_VT | 1.99 | 14.6% | -14.1% | +785% | -9.2% | 63% | 1.21 | 8.4% | -21.3% | +123% | -10.2% | 59% |
| SPY | 0.54 | 8.4% | -55.2% | +264% | -16.5% | 62% | 1.60 | 13.8% | -33.7% | +263% | -12.5% | 71% |

## 5. Pre-registered criteria (2016-2020; 2011-2020 for DAILY)

Passed: INTRADAY_EQ.

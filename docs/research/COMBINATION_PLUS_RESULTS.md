# Fases 7b y 7c, más estrategias intradía, apalancamiento y combinación total: resultados

Run de GitHub: [39149435566](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39149435566). Reglas:
[COMBINATION_PLUS_PREREGISTRATION.md](COMBINATION_PLUS_PREREGISTRATION.md). Sesgo de supervivencia sin corregir
(perjudica a los cortos). Periodo bloqueado (2021+) sin leer. La referencia `INTRADAY_EQ` reproduce la fase 7a
(Sortino 4,92, 16,5%/año, caída -7,7%).

## Resumen en español

- **De las 5 estrategias nuevas solo una vale algo**: el EP vendido al cierre del día (`EP_DAY`: Sortino 2,65,
  14,3%/año, caída -14,7%), pero se parece a los EP que ya teníamos (correlación 0,37-0,45) y al mercado.
- **Los cortos no funcionan con estos datos**: cortos parabólicos para varios días (-7,9%/año), rupturas a la baja
  (-22,2%/año) y cortos parabólicos en el día con un mes de **-58%** (una subida violenta de una acción en corto).
  Faltan las acciones que se hundieron y desaparecieron, que eran sus mejores cortos, pero también enseñan el
  riesgo de cola de los cortos.
- **Añadirlas empeora la combinación**: las 8 intradía juntas bajan a Sortino 1,6-2,4 y las 13 a 2,4-2,7, frente a
  4,92 con las 3 de la fase 7a. Mezclar estrategias malas no diversifica: diluye.
- **El apalancamiento de la combinación intradía de la 7a sí funciona** (aproximación a nivel de cuenta):

  | apalancamiento | Sortino | al año | caída máx. | total 2016-2020 | peor mes |
  |---|---|---|---|---|---|
  | 1x | 4,92 | 16,5% | -7,7% | +114% | -2,1% |
  | 1,5x | 4,64 | 23,6% | -11,7% | +188% | -3,2% |
  | 2x | 4,50 | 30,6% | -15,6% | +280% | -4,3% |
  | 3x | 4,36 | 44,9% | -23,1% | +537% | -6,6% |

  Pasan los criterios las tres. El Sortino baja un poco por el coste del margen. En la práctica los límites de
  posición, la liquidez de las acciones pequeñas y el margen permitido (2x de un día a otro en EE.UU.) hacen que el
  3x sea optimista.
- **Sortino 10: no**. Con lo encontrado, el techo práctico está en torno a 4,5-5. Subir más requiere estrategias
  nuevas que ganen por su cuenta y casi no se parezcan a las nuestras (otros mercados), no más variantes de las
  mismas acciones.

## Informe completo (generado por el código)

# Phases 7b and 7c: more intraday streams, leverage and the full combination (pre-registered, 18 trials)

18 of 18 trials; deflated Sharpe over 249,228 trials. 2016-2020. Survivorship bias NOT adjusted (hurts the short streams). Locked period from 2021-01-01 never read. Short candidates: {'PS_candidates': 4129, 'BD_candidates': 10298, 'PS_entries': 2823, 'BD_entries': 5944}.

## 1. Monthly-return correlations of the 13 streams and SPY, 2016-2020

| | ACCUM | SQUEEZE | LOWVOL | IPO | PARA_SHORT | EP_EARN | EP_NEWS | BO_TOP3 | EP_DAY | BO_DAY | PS_DAY | PS_SWING | BD_DAY | SPY |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ACCUM | +1.00 | +0.74 | +0.57 | +0.47 | -0.28 | +0.22 | +0.14 | +0.17 | +0.39 | +0.00 | +0.32 | -0.14 | -0.10 | +0.56 |
| SQUEEZE | +0.74 | +1.00 | +0.66 | +0.48 | -0.31 | +0.24 | +0.18 | +0.12 | +0.46 | -0.04 | +0.37 | -0.24 | -0.13 | +0.77 |
| LOWVOL | +0.57 | +0.66 | +1.00 | +0.39 | -0.22 | +0.14 | +0.14 | +0.02 | +0.38 | +0.01 | +0.33 | -0.10 | -0.02 | +0.64 |
| IPO | +0.47 | +0.48 | +0.39 | +1.00 | -0.11 | +0.18 | +0.12 | +0.25 | +0.12 | +0.11 | +0.15 | -0.06 | -0.02 | +0.41 |
| PARA_SHORT | -0.28 | -0.31 | -0.22 | -0.11 | +1.00 | +0.14 | +0.58 | +0.06 | +0.05 | +0.13 | -0.69 | +0.15 | +0.47 | -0.22 |
| EP_EARN | +0.22 | +0.24 | +0.14 | +0.18 | +0.14 | +1.00 | +0.21 | +0.22 | +0.37 | +0.14 | -0.01 | -0.20 | +0.05 | +0.26 |
| EP_NEWS | +0.14 | +0.18 | +0.14 | +0.12 | +0.58 | +0.21 | +1.00 | +0.13 | +0.45 | +0.17 | -0.13 | -0.03 | +0.01 | +0.20 |
| BO_TOP3 | +0.17 | +0.12 | +0.02 | +0.25 | +0.06 | +0.22 | +0.13 | +1.00 | -0.01 | +0.38 | -0.01 | -0.42 | +0.04 | +0.23 |
| EP_DAY | +0.39 | +0.46 | +0.38 | +0.12 | +0.05 | +0.37 | +0.45 | -0.01 | +1.00 | +0.15 | +0.17 | +0.03 | +0.09 | +0.20 |
| BO_DAY | +0.00 | -0.04 | +0.01 | +0.11 | +0.13 | +0.14 | +0.17 | +0.38 | +0.15 | +1.00 | -0.02 | +0.20 | +0.02 | -0.11 |
| PS_DAY | +0.32 | +0.37 | +0.33 | +0.15 | -0.69 | -0.01 | -0.13 | -0.01 | +0.17 | -0.02 | +1.00 | -0.07 | -0.70 | +0.41 |
| PS_SWING | -0.14 | -0.24 | -0.10 | -0.06 | +0.15 | -0.20 | -0.03 | -0.42 | +0.03 | +0.20 | -0.07 | +1.00 | +0.10 | -0.42 |
| BD_DAY | -0.10 | -0.13 | -0.02 | -0.02 | +0.47 | +0.05 | +0.01 | +0.04 | +0.09 | +0.02 | -0.70 | +0.10 | +1.00 | -0.27 |
| SPY | +0.56 | +0.77 | +0.64 | +0.41 | -0.22 | +0.26 | +0.20 | +0.23 | +0.20 | -0.11 | +0.41 | -0.42 | -0.27 | +1.00 |

## 2. The five new streams alone

| stream | 2016-18 Sortino | 2019-20 Sortino | 2016-20 Sortino | CAGR | max DD | total | worst month | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| EP_DAY | 1.52 | 3.75 | 2.65 | 14.3% | -14.7% | +95% | -6.4% | 55% | 0.16 | no |
| BO_DAY | 2.61 | 0.42 | 1.38 | 5.2% | -9.5% | +29% | -2.2% | 57% | 0.03 | no |
| PS_DAY | 2.54 | 0.16 | 0.46 | 5.9% | -67.4% | +33% | -58.2% | 67% | 0.01 | no |
| PS_SWING | -0.39 | -0.22 | -0.29 | -7.9% | -49.4% | -34% | -34.5% | 47% | 0.00 | no |
| BD_DAY | -0.91 | -0.90 | -0.89 | -22.2% | -74.8% | -71% | -17.2% | 32% | 0.00 | no |

## 3. Combinations (7c)

| combination | 2016-18 Sortino | 2019-20 Sortino | 2016-20 Sortino | CAGR | max DD | total | worst month | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| INTRADAY_EQ (7a, reference) | 2.96 | 7.60 | 4.92 | 16.5% | -7.7% | +114% | -2.1% | 62% | - | - |
| INTRA8_EQ | 1.54 | 1.77 | 1.64 | 6.7% | -10.9% | +38% | -3.8% | 60% | 0.05 | no |
| INTRA8_RP | 1.65 | 3.50 | 2.44 | 7.5% | -9.7% | +44% | -2.8% | 65% | 0.16 | no |
| ALL13_EQ | 1.56 | 3.77 | 2.36 | 8.9% | -6.3% | +53% | -4.1% | 65% | 0.41 | no |
| ALL13_RP | 1.26 | 7.34 | 2.71 | 8.6% | -5.7% | +51% | -3.8% | 67% | 0.65 | no |

## 4. Leverage (account level)

| combination | 2016-18 Sortino | 2019-20 Sortino | 2016-20 Sortino | CAGR | max DD | total | worst month | positive months | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| INTRADAY_EQ_L1.5 | 2.72 | 7.27 | 4.64 | 23.6% | -11.7% | +188% | -3.2% | 57% | 0.35 | YES |
| INTRADAY_EQ_L2 | 2.61 | 7.10 | 4.50 | 30.6% | -15.6% | +280% | -4.3% | 57% | 0.33 | YES |
| INTRADAY_EQ_L3 | 2.50 | 6.92 | 4.36 | 44.9% | -23.1% | +537% | -6.6% | 57% | 0.31 | YES |
| INTRA8_EQ_L1.5 | 1.32 | 1.59 | 1.44 | 8.4% | -16.1% | +50% | -5.7% | 58% | 0.04 | no |
| INTRA8_EQ_L2 | 1.22 | 1.50 | 1.34 | 10.1% | -21.1% | +62% | -7.6% | 57% | 0.03 | no |
| INTRA8_EQ_L3 | 1.12 | 1.37 | 1.23 | 12.9% | -30.5% | +83% | -11.4% | 53% | 0.03 | no |
| ALL13_EQ_L1.5 | 1.40 | 3.52 | 2.18 | 12.1% | -9.8% | +77% | -6.2% | 62% | 0.34 | no |
| ALL13_EQ_L2 | 1.34 | 3.41 | 2.10 | 15.2% | -13.3% | +103% | -8.3% | 60% | 0.31 | YES |
| ALL13_EQ_L3 | 1.29 | 3.31 | 2.04 | 21.5% | -19.8% | +165% | -12.4% | 58% | 0.27 | YES |

SPY: 1.45 | 15.1% | -33.7% | +102% | -12.5% | 77% (Sortino | CAGR | max DD | total | worst month | positive months).

## 5. Pre-registered criteria on 2016-2020

Passed: INTRADAY_EQ_L1.5, INTRADAY_EQ_L2, INTRADAY_EQ_L3, ALL13_EQ_L2, ALL13_EQ_L3.

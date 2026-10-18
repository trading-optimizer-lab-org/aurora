# Qullamaggie fase 2, exposición según el "viento": resultados

Run de GitHub: [39122737620](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39122737620).
Reglas: [QULLAMAGGIE_WIND_PREREGISTRATION.md](QULLAMAGGIE_WIND_PREREGISTRATION.md). Detalle de implementación
fijado antes de ver datos reales: los percentiles del último año exigen al menos 126 de las 252 sesiones con
valor (si no, un solo hueco dejaba el semáforo sin verde durante un año). Sesgo de supervivencia sin corregir.
Periodo bloqueado (2021+) sin leer.

## Comprobaciones

- Las filas `E0` (sin ajuste) reproducen exactamente los estudios anteriores: `D_BO_E0` = `QBO_STOP_SCAN5_M0_XQ3_20`,
  `D_EP_E0` = `QEP_N1_A35_M0_XQ3_20`, `I_BO_E0` y `I_EP_E0` = sus filas de la fase 1 (diferencia 0).
- La fase 1 se volvió a calcular con el código reorganizado
  ([run 39122737570](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39122737570)): diferencia máxima
  3e-13.
- El semáforo reparte los días como estaba previsto: ~30% verde, ~39% amarillo, ~30% rojo, en todos los periodos.

## Resumen en español

- **Con datos diarios el viento no salva nada.** Las rupturas siguen perdiendo con todas las políticas (caídas de
  -82% a -97%); la mejor (`E4`, viento + Nasdaq) solo pierde menos. En los EP diarios el viento empeora: lo mejor
  sigue siendo no ajustar (`D_EP_E0`: Sortino 2,24 y 11,1%/año en 2011-2020, pero pierde frente al SPY).
- **En las rupturas intradía sí ayuda, y de forma pareja en los dos tramos.** Sin ajuste (`I_BO_E0`): 3,9%/año en
  2016-2020. Con viento, margen 2× en verde y posiciones del 10% (`I_BO_E3_C10`): 16,9%/año, Sortino 1,40, caída
  -39%; 13,2%/año en 2016-2018 y 22,5% en 2019-2020. Con el Nasdaq además (`I_BO_E4_C10`): 12,6%/año y caída -30%.
- **Posiciones más pequeñas (10%) ganan siempre a las grandes (20%)** en rupturas y en la mezcla: cogen más
  operaciones del racimo bueno (en `I_BO_E3` capturan el 56% del 5% de mejores operaciones frente al 43%). Es la
  explicación de la fase 1: el problema era la capacidad, no solo la entrada.
- **EP intradía**: ya era lo mejor sin ajuste (`I_EP_E0`: Sortino 4,72, 26,2%/año, caída -16,8%) y el viento no lo
  mejora en Sortino. 6 de sus 7 versiones pasan los criterios en 2016-2020, pero 2016-2018 sigue flojo (2,5-9,9%/año).
- **La mezcla de rupturas + EP en una cartera** (su estilo real): `I_MIX_E3_C10` 38,2%/año, Sortino 2,74, caída -45%
  (2016-2018: 17,8%/año; 2019-2020: 75,5%); `I_MIX_E4_C10` 29,9%/año, Sortino 2,63, caída -32,6%. No pasan por la
  caída (límite -25%).
- **Nada es estadísticamente sólido**: deflated Sharpe máximo 0,18 con 249.142 pruebas acumuladas, y todo lo
  intradía es 2016-2020, ya visto. Es la mejor pista hasta ahora, no una prueba.

## Informe completo (generado por el código)

# Qullamaggie phase 2: exposure by the breakout wind (pre-registered, 35 trials)

35 of 35 trials; deflated Sharpe over 249,142 trials. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. Columns per period: monthly Sortino | CAGR | max drawdown of the portfolio.

Share of days in each state: train {'yellow': 0.385, 'red': 0.316, 'green': 0.3}; validation {'yellow': 0.397, 'green': 0.302, 'red': 0.301}; val1 {'yellow': 0.397, 'red': 0.32, 'green': 0.282}; val2 {'yellow': 0.396, 'green': 0.322, 'red': 0.282}; p1 {'yellow': 0.381, 'green': 0.316, 'red': 0.304}; p2 {'yellow': 0.42, 'green': 0.331, 'red': 0.25}; all {'yellow': 0.396, 'green': 0.322, 'red': 0.282}

SPY: 1995-2010 0.54 | 8.4% | -55.2% · 2011-2020 1.60 | 13.8% | -33.7% · 2016-2020 1.45 | 15.1% | -33.7%.

## 1. Daily setups, 1995-2020

| trial | 1995-2010 Sortino | CAGR | max DD | 2011-2020 Sortino | CAGR | max DD | 2011-15 Sortino | 2016-20 Sortino | trades 11-20 | PF 11-20 | best 5% captured | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D_BO_E0 | -1.07 | -15.2% | -96.3% | -1.29 | -21.6% | -92.5% | -1.56 | -1.09 | 5,558 | 0.97 | 74% | 0.00 | no |
| D_BO_E1 | -0.86 | -9.4% | -90.4% | -1.17 | -16.9% | -86.8% | -1.69 | -0.81 | 4,667 | 0.98 | 62% | 0.00 | no |
| D_BO_E2 | -1.16 | -17.3% | -96.2% | -1.03 | -19.0% | -91.4% | -1.65 | -0.53 | 4,667 | 0.98 | 52% | 0.00 | no |
| D_BO_E3_C20 | -0.66 | -13.9% | -97.0% | -1.12 | -25.6% | -95.5% | -1.64 | -0.78 | 4,667 | 0.98 | 60% | 0.00 | no |
| D_BO_E3_C10 | -0.60 | -10.4% | -94.2% | -1.16 | -23.3% | -93.0% | -1.67 | -0.87 | 4,667 | 0.98 | 65% | 0.00 | no |
| D_BO_E4_C20 | -0.34 | -6.9% | -90.6% | -0.81 | -16.8% | -85.5% | -1.43 | -0.48 | 3,654 | 1.01 | 43% | 0.00 | no |
| D_BO_E4_C10 | -0.27 | -4.2% | -82.5% | -0.85 | -15.4% | -81.8% | -1.37 | -0.60 | 3,654 | 1.01 | 47% | 0.00 | no |
| D_EP_E0 | 0.18 | 3.7% | -16.3% | 2.24 | 11.1% | -27.3% | -0.28 | 3.84 | 936 | 1.22 | 97% | 0.00 | no |
| D_EP_E1 | -0.11 | 3.0% | -9.2% | 2.17 | 8.3% | -29.4% | -0.84 | 3.77 | 643 | 1.25 | 61% | 0.00 | no |
| D_EP_E2 | -0.24 | 2.5% | -9.9% | 1.67 | 7.8% | -36.4% | -0.94 | 2.99 | 643 | 1.25 | 61% | 0.00 | no |
| D_EP_E3_C20 | -0.21 | 2.6% | -10.2% | 1.68 | 7.8% | -37.1% | -0.94 | 2.95 | 643 | 1.25 | 62% | 0.00 | no |
| D_EP_E3_C10 | -0.06 | 3.1% | -8.1% | 1.07 | 4.5% | -30.8% | -0.95 | 1.96 | 643 | 1.25 | 62% | 0.00 | no |
| D_EP_E4_C20 | -0.32 | 2.5% | -10.0% | -0.13 | -0.7% | -27.4% | -1.34 | 0.35 | 421 | 0.98 | 32% | 0.00 | no |
| D_EP_E4_C10 | -0.18 | 3.0% | -7.9% | -0.22 | -0.5% | -25.8% | -1.38 | 0.20 | 421 | 0.98 | 32% | 0.00 | no |

## 2. Intraday setups, 2016-2020

| trial | 2016-2018 Sortino | CAGR | max DD | 2019-2020 Sortino | CAGR | max DD | 2016-2020 Sortino | CAGR | max DD | trades | PF | best 5% captured | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| I_BO_E0 | 0.21 | 0.9% | -38.2% | 0.68 | 8.5% | -34.6% | 0.39 | 3.9% | -49.8% | 2,956 | 1.42 | 49% | 0.00 | no |
| I_BO_E1 | 0.93 | 10.3% | -27.2% | 0.31 | 2.9% | -37.5% | 0.64 | 7.3% | -52.2% | 2,518 | 1.41 | 39% | 0.01 | no |
| I_BO_E2 | 0.85 | 9.5% | -28.7% | 0.59 | 7.8% | -40.6% | 0.72 | 8.8% | -54.2% | 2,518 | 1.41 | 37% | 0.01 | no |
| I_BO_E3_C20 | 1.36 | 19.4% | -32.4% | 0.64 | 6.6% | -39.1% | 1.02 | 14.1% | -56.7% | 2,518 | 1.41 | 43% | 0.02 | no |
| I_BO_E3_C10 | 1.24 | 13.2% | -20.5% | 1.57 | 22.5% | -25.6% | 1.40 | 16.9% | -38.9% | 2,518 | 1.41 | 56% | 0.03 | no |
| I_BO_E4_C20 | 1.24 | 12.1% | -33.7% | 0.72 | 8.0% | -41.7% | 0.89 | 10.5% | -46.6% | 2,080 | 1.44 | 33% | 0.01 | no |
| I_BO_E4_C10 | 0.83 | 6.7% | -23.5% | 1.54 | 22.0% | -26.8% | 1.18 | 12.6% | -29.8% | 2,080 | 1.44 | 43% | 0.02 | no |
| I_EP_E0 | 1.01 | 5.3% | -15.5% | 8.59 | 65.3% | -14.8% | 4.72 | 26.2% | -16.8% | 636 | 1.40 | 97% | 0.18 | YES |
| I_EP_E1 | 1.24 | 5.6% | -12.8% | 6.02 | 42.3% | -16.8% | 3.71 | 19.0% | -16.8% | 421 | 1.31 | 66% | 0.11 | YES |
| I_EP_E2 | 1.87 | 9.9% | -20.9% | 6.06 | 61.2% | -23.6% | 4.05 | 28.2% | -23.6% | 421 | 1.31 | 59% | 0.14 | YES |
| I_EP_E3_C20 | 1.52 | 8.2% | -20.9% | 6.74 | 68.6% | -22.1% | 4.28 | 29.2% | -22.1% | 421 | 1.31 | 66% | 0.14 | YES |
| I_EP_E3_C10 | 0.97 | 4.5% | -14.5% | 6.05 | 46.7% | -21.2% | 3.66 | 19.8% | -21.2% | 421 | 1.31 | 66% | 0.08 | YES |
| I_EP_E4_C20 | 0.92 | 4.5% | -12.8% | 6.89 | 52.8% | -16.4% | 4.10 | 21.7% | -16.4% | 296 | 1.22 | 41% | 0.06 | YES |
| I_EP_E4_C10 | 0.59 | 2.5% | -9.2% | 5.65 | 33.6% | -17.2% | 3.38 | 14.0% | -17.2% | 296 | 1.22 | 41% | 0.03 | no |
| I_MIX_E0 | 0.67 | 8.7% | -32.7% | 4.02 | 54.4% | -32.1% | 1.71 | 25.2% | -50.5% | 3,511 | 1.42 | 53% | 0.07 | no |
| I_MIX_E1 | 1.28 | 16.7% | -30.2% | 2.19 | 31.9% | -35.2% | 1.68 | 22.6% | -50.6% | 2,888 | 1.39 | 39% | 0.06 | no |
| I_MIX_E2 | 1.32 | 17.9% | -31.1% | 2.24 | 36.1% | -38.5% | 1.72 | 24.9% | -53.4% | 2,888 | 1.39 | 36% | 0.07 | no |
| I_MIX_E3_C20 | 1.36 | 22.6% | -37.4% | 2.48 | 46.6% | -44.6% | 1.87 | 31.7% | -63.1% | 2,888 | 1.39 | 43% | 0.07 | no |
| I_MIX_E3_C10 | 1.45 | 17.8% | -26.2% | 4.32 | 75.5% | -28.1% | 2.74 | 38.2% | -45.0% | 2,888 | 1.39 | 56% | 0.17 | no |
| I_MIX_E4_C20 | 1.68 | 17.7% | -23.2% | 2.83 | 56.5% | -43.7% | 2.23 | 31.9% | -48.8% | 2,341 | 1.41 | 31% | 0.08 | no |
| I_MIX_E4_C10 | 1.34 | 10.5% | -19.1% | 3.82 | 65.5% | -28.6% | 2.63 | 29.9% | -32.6% | 2,341 | 1.41 | 39% | 0.10 | no |

## 3. Pre-registered criteria (2011-2020 daily, 2016-2020 intraday)

Passed: I_EP_E0, I_EP_E1, I_EP_E2, I_EP_E3_C20, I_EP_E3_C10, I_EP_E4_C20.


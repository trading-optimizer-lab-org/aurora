# Qullamaggie fase 4, tamaño y gestión de la posición: resultados

Run de GitHub: [39130036578](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39130036578). Reglas:
[QULLAMAGGIE_SIZING_PREREGISTRATION.md](QULLAMAGGIE_SIZING_PREREGISTRATION.md). Sesgo de supervivencia sin corregir.
Periodo bloqueado (2021+) sin leer.

## Comprobaciones

- `SIZE_S2_P0_C0_X0` (sin herramientas) reproduce `I_MIX_MODEL_N3_E0` de la fase 3 (diferencia 2e-14).
- La fase 3 se recalculó con su código reorganizado
  ([run 39130036521](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39130036521)): idéntica.

## Resumen en español

- **13 de las 16 combinaciones pasan los criterios en 2016-2020**, pero las herramientas de "apretar" a las
  ganadoras aportan poco sobre la cartera base (0,5% de riesgo, posiciones del 20%, sin margen).
- **Efecto medio de cada herramienta** (frente a no usarla):
  - Su tamaño real (0,25%, posiciones del 10%): **-18,9 puntos de rentabilidad al año**, caída casi igual. Aquí
    arriesgar poco cuesta mucho.
  - Añadir a la ganadora: +2,1 puntos al año, pero más caída (-2,4 puntos) y menos Sortino (-0,55).
  - Colchón con margen: **empeora** (-4,7 puntos al año, -7,5 puntos de caída), sobre todo en 2019-2020.
  - Vender un tercio en fuerza: la única que mejora un poco todo (+0,27 de Sortino, caída algo menor).
- **La mejor combinación**: `SIZE_S2_P0_C0_X1` (base + vender en fuerza): **40,5%/año, +447% en 2016-2020, Sortino
  4,81, caída -15,7%**; 2016-2018 21,4%/año (Sortino 2,49), 2019-2020 74,8% (Sortino 8,53). Deflated Sharpe 0,40,
  el más alto de toda la búsqueda, pero lejos de 0,95.
- **La más rentable**: `SIZE_S2_P1_C0_X0` (base + añadir a la ganadora): 43,0%/año, +496%, caída -22,9%.
- Elegir ahora la mejor de estas 16 es otra selección sobre 2016-2020. La diferencia con la base es pequeña: la
  conclusión práctica es quedarse con la base y, como mucho, vender en fuerza.

## Informe completo (generado por el código)

# Qullamaggie phase 4: sizing and position management (pre-registered, 16 trials)

16 of 16 trials on `I_MIX_MODEL_N3` (2016-2020); deflated Sharpe over 249,182 trials. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. Columns per period: monthly Sortino | CAGR | max drawdown | total return of the portfolio. S1 = 0.25% risk, 10% cap; S2 = 0.5%, 20%. P1 = add 50% at +2R; C1 = profit cushion (2x risk and margin); X1 = sell a third 30% above the SMA10.

SPY: 2016-2018 1.05 | 9.2% | -19.3% | +30% · 2019-2020 1.87 | 24.6% | -33.7% | +55% · 2016-2020 1.45 | 15.1% | -33.7% | +102%.

## 1. All trials

| trial | 2016-18 Sortino | CAGR | max DD | total | 2019-20 Sortino | CAGR | max DD | total | 2016-20 Sortino | CAGR | max DD | total | max invested | best 5% captured | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SIZE_S1_P0_C0_X0 | 2.40 | 11.6% | -10.0% | +39% | 6.61 | 30.7% | -12.6% | +71% | 4.08 | 18.9% | -12.6% | +138% | 100% | 100% | 0.15 | YES |
| SIZE_S1_P0_C0_X1 | 2.40 | 11.1% | -7.6% | +37% | 7.81 | 32.8% | -9.3% | +76% | 4.47 | 19.3% | -9.3% | +142% | 100% | 100% | 0.23 | YES |
| SIZE_S1_P0_C1_X0 | 2.24 | 11.2% | -10.0% | +37% | 6.33 | 26.4% | -30.6% | +60% | 3.71 | 17.1% | -30.6% | +120% | 163% | 100% | 0.06 | no |
| SIZE_S1_P0_C1_X1 | 2.29 | 10.8% | -8.1% | +36% | 7.06 | 26.5% | -23.8% | +60% | 3.95 | 16.9% | -23.8% | +118% | 136% | 100% | 0.08 | YES |
| SIZE_S1_P1_C0_X0 | 2.11 | 12.9% | -12.2% | +44% | 6.30 | 36.2% | -13.2% | +86% | 3.74 | 21.8% | -13.2% | +167% | 100% | 100% | 0.15 | YES |
| SIZE_S1_P1_C0_X1 | 2.06 | 12.1% | -9.6% | +41% | 7.23 | 37.3% | -12.5% | +89% | 3.98 | 21.6% | -12.5% | +166% | 100% | 100% | 0.18 | YES |
| SIZE_S1_P1_C1_X0 | 1.83 | 11.9% | -11.3% | +40% | 5.93 | 30.6% | -14.8% | +71% | 3.26 | 19.1% | -14.8% | +139% | 104% | 100% | 0.09 | YES |
| SIZE_S1_P1_C1_X1 | 1.98 | 12.6% | -10.0% | +43% | 6.40 | 27.7% | -31.7% | +63% | 3.33 | 18.4% | -31.7% | +133% | 175% | 100% | 0.06 | no |
| SIZE_S2_P0_C0_X0 | 2.51 | 22.7% | -18.5% | +84% | 7.40 | 70.1% | -15.2% | +190% | 4.45 | 39.8% | -18.5% | +434% | 100% | 94% | 0.30 | YES |
| SIZE_S2_P0_C0_X1 | 2.49 | 21.4% | -14.7% | +79% | 8.53 | 74.8% | -13.9% | +206% | 4.81 | 40.5% | -15.7% | +447% | 100% | 98% | 0.40 | YES |
| SIZE_S2_P0_C1_X0 | 2.38 | 19.8% | -15.5% | +72% | 9.83 | 55.5% | -15.3% | +142% | 4.45 | 33.0% | -15.9% | +316% | 184% | 98% | 0.20 | YES |
| SIZE_S2_P0_C1_X1 | 2.67 | 19.9% | -14.6% | +72% | 10.09 | 59.7% | -18.2% | +156% | 5.07 | 34.5% | -18.2% | +340% | 171% | 98% | 0.27 | YES |
| SIZE_S2_P1_C0_X0 | 2.33 | 26.6% | -22.9% | +103% | 6.19 | 71.4% | -19.4% | +194% | 3.81 | 43.0% | -22.9% | +496% | 100% | 90% | 0.27 | YES |
| SIZE_S2_P1_C0_X1 | 2.25 | 24.6% | -18.3% | +93% | 7.07 | 73.5% | -16.5% | +202% | 3.99 | 42.3% | -19.4% | +483% | 100% | 90% | 0.30 | YES |
| SIZE_S2_P1_C1_X0 | 2.75 | 26.0% | -19.7% | +100% | 7.37 | 51.6% | -28.1% | +130% | 4.19 | 35.7% | -28.1% | +359% | 153% | 98% | 0.14 | no |
| SIZE_S2_P1_C1_X1 | 2.55 | 23.4% | -18.0% | +88% | 8.12 | 54.9% | -21.3% | +140% | 4.29 | 35.2% | -21.3% | +351% | 194% | 98% | 0.15 | YES |

## 2. Average effect of each tool (mean with it minus mean without, over the other 8 combinations)

| tool | Sortino 2016-20 | CAGR 2016-20 | max DD 2016-20 | CAGR 2016-18 | CAGR 2019-20 |
|---|---|---|---|---|---|
| pyramid | -0.55 | +2.1% | -2.4% | +2.7% | +0.8% |
| cushion | -0.13 | -4.7% | -7.5% | -0.9% | -11.7% |
| strength | +0.27 | +0.1% | +0.6% | -0.8% | +1.8% |
| S1 (his size) | -0.57 | -18.9% | +1.4% | -11.3% | -32.9% |

## 3. Pre-registered criteria on 2016-2020

Passed: SIZE_S1_P0_C0_X0, SIZE_S1_P0_C0_X1, SIZE_S1_P0_C1_X1, SIZE_S1_P1_C0_X0, SIZE_S1_P1_C0_X1, SIZE_S1_P1_C1_X0, SIZE_S2_P0_C0_X0, SIZE_S2_P0_C0_X1, SIZE_S2_P0_C1_X0, SIZE_S2_P0_C1_X1, SIZE_S2_P1_C0_X0, SIZE_S2_P1_C0_X1, SIZE_S2_P1_C1_X1.


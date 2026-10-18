# Qullamaggie fase 1, ejecución intradía (2016-2020): resultados

Run de GitHub: [39118575331](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39118575331)
(intento 2, tras añadir las claves de Alpaca): 15.717 días candidatos, 1.555 llamadas a Alpaca, 26.377 entradas
intradía entre todas las variantes. Descartados: 254 sin histórico diario en Alpaca, 30 por precios que no cuadran,
16 sin minutos. Reglas: [QULLAMAGGIE_INTRADAY_PREREGISTRATION.md](QULLAMAGGIE_INTRADAY_PREREGISTRATION.md).
Sesgo de supervivencia sin corregir. Nada posterior a 2020-12-31.

## Resumen en español

- **Ahora la mecánica se parece a la suya**: el 38-47% de las rupturas se paran el mismo día (él ~37%), stop
  mediano 1,9-2,8% (él 2,5%), entrada mediana en el minuto 8-17 (él 10), acierto 23-28% (él 25-31%).
- **En las rupturas la ejecución sí importa**: con la entrada en el rango de apertura el profit factor por
  operación pasa de 0,96-0,98 (versión diaria, mismo periodo) a 1,22-1,51. Su selección más estricta (ADR ≥ 5%)
  es la mejor (mediana 1,43).
- **Pero la ventaja depende del momento**: rupturas con PF ~1,05 en 2016-2018 y ~1,5 en 2019-2020. Y la cartera con
  0,5% de riesgo no la captura: entre -10% y +9,5% al año, caídas de -31% a -66%. Explicación probable (inferencia):
  la ganancia está en pocas operaciones enormes (el 5% mejor suma 1,5-3,5 veces el total) que llegan en racimos en
  mercados calientes, con docenas de señales al día; con posiciones del 20% la cartera solo coge unas pocas.
- **Episodic Pivot intradía**: en 2019-2020 ganan las 24 variantes (cartera +14% a +134% al año, Sortino 1,6 a
  12,9) y en 2016-2018 pierden todas por operación (PF 0,42-0,87). 6 combinaciones pasan los criterios en 2016-2020; la mejor,
  `IEP_N1_Q05_K1_XQ3_20` (hueco ≥ 10% en acción que no había subido, volumen al ritmo de la mitad de su media diaria,
  compra al romper el primer minuto, venta con la SMA20): Sortino 4,81, 38%/año, caída -23,8%. Pero el deflated
  Sharpe máximo es 0,25 y todas pierden en 2016-2018: no es robusto, depende de 2019-2020.
- **Conclusión**: su ejecución explica parte de su ventaja en las rupturas, y su rentabilidad depende de estar
  muy expuesto en las rachas buenas. Eso apunta a la fase 2 (exposición según cómo funcionan las rupturas
  recientes). 2016-2020 ya se había visto en datos diarios, así que esto es una pista, no una prueba.

## Informe completo (generado por el código)

# Qullamaggie phase 1: intraday execution on one-minute bars, 2016-2020 (pre-registered, 48 trials)

48 of 48 trials; deflated Sharpe over 249,107 trials. Candidate days 15,717; intraday entries found 26,377; dropped: no_minutes 16, no_daily 254, price_mismatch 30. Survivorship bias NOT adjusted. Nothing after 2020-12-31 was requested.

SPY 2016-2020: Sortino 1.45, CAGR 15.1%, max DD -33.7%. His record: ~37% same-day stops, median stop 2.5% (breakout) / 3.8% (EP), median entry minute 10, 25-31% winners.

## 1. Reference: the daily-bar versions on 2016-2020 (not trials)

| trial | 2016-18 trades | PF | 2019-20 trades | PF | 2016-20 trades | win | PF | avg | total | Sortino | CAGR | max DD | same-day stops | median stop | entry minute | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REF_BO_SCAN35_M0 | 3,349 | 0.83 | 3,777 | 1.06 | 7,126 | 31% | 0.96 | -0.12% | -833% | -2.04 | -46.1% | -96.3% | 15% | 5.4% | - | - | - |
| REF_BO_SCAN35_M1 | 2,162 | 0.80 | 3,247 | 1.08 | 5,409 | 31% | 0.98 | -0.06% | -351% | -1.85 | -33.9% | -89.7% | 14% | 5.5% | - | - | - |
| REF_EP_N1_A35_M0 | 294 | 1.04 | 403 | 1.42 | 697 | 29% | 1.27 | +1.04% | +724% | 3.37 | 23.0% | -28.5% | 0% | 4.2% | - | - | - |

## 2. All trials

| trial | 2016-18 trades | PF | 2019-20 trades | PF | 2016-20 trades | win | PF | avg | total | Sortino | CAGR | max DD | same-day stops | median stop | entry minute | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IBO_SCAN35_M0_K1_XQ3_10 | 2,691 | 1.03 | 3,163 | 1.37 | 5,854 | 24% | 1.22 | +0.39% | +2,260% | 0.07 | -2.9% | -66.0% | 47% | 1.9% | 8 | 0.00 | no |
| IBO_SCAN35_M0_K1_XQ3_20 | 2,612 | 1.04 | 3,054 | 1.43 | 5,666 | 24% | 1.26 | +0.45% | +2,543% | -0.03 | -4.0% | -58.7% | 47% | 1.8% | 8 | 0.00 | no |
| IBO_SCAN35_M0_K5_XQ3_10 | 2,447 | 1.03 | 2,825 | 1.37 | 5,272 | 26% | 1.22 | +0.42% | +2,218% | 0.15 | -0.4% | -57.3% | 39% | 2.2% | 16 | 0.00 | no |
| IBO_SCAN35_M0_K5_XQ3_20 | 2,379 | 1.03 | 2,726 | 1.44 | 5,105 | 26% | 1.26 | +0.49% | +2,524% | -0.05 | -3.5% | -53.9% | 39% | 2.2% | 16 | 0.00 | no |
| IBO_SCAN35_M0_K30_XQ3_10 | 1,642 | 1.01 | 1,905 | 1.39 | 3,547 | 33% | 1.22 | +0.47% | +1,680% | -0.47 | -8.2% | -55.9% | 22% | 2.9% | 43 | 0.00 | no |
| IBO_SCAN35_M0_K30_XQ3_20 | 1,598 | 1.06 | 1,855 | 1.43 | 3,453 | 33% | 1.27 | +0.57% | +1,981% | -0.44 | -8.5% | -54.6% | 22% | 2.9% | 43 | 0.00 | no |
| IBO_SCAN35_M1_K1_XQ3_10 | 1,711 | 1.02 | 2,709 | 1.40 | 4,420 | 23% | 1.26 | +0.46% | +2,019% | -0.25 | -7.7% | -61.4% | 46% | 1.9% | 8 | 0.00 | no |
| IBO_SCAN35_M1_K1_XQ3_20 | 1,686 | 0.98 | 2,625 | 1.47 | 4,311 | 23% | 1.29 | +0.50% | +2,154% | -0.39 | -8.6% | -64.1% | 46% | 1.9% | 8 | 0.00 | no |
| IBO_SCAN35_M1_K5_XQ3_10 | 1,571 | 1.00 | 2,409 | 1.41 | 3,980 | 26% | 1.26 | +0.50% | +1,984% | 0.00 | -2.5% | -58.9% | 38% | 2.2% | 16 | 0.00 | no |
| IBO_SCAN35_M1_K5_XQ3_20 | 1,546 | 0.98 | 2,332 | 1.48 | 3,878 | 26% | 1.29 | +0.57% | +2,202% | -0.17 | -4.1% | -58.1% | 38% | 2.2% | 16 | 0.00 | no |
| IBO_SCAN35_M1_K30_XQ3_10 | 1,053 | 0.99 | 1,629 | 1.45 | 2,682 | 33% | 1.28 | +0.61% | +1,643% | -0.62 | -8.0% | -55.6% | 20% | 2.9% | 43 | 0.00 | no |
| IBO_SCAN35_M1_K30_XQ3_20 | 1,037 | 0.96 | 1,594 | 1.49 | 2,631 | 33% | 1.30 | +0.64% | +1,688% | -0.75 | -10.4% | -60.0% | 20% | 2.9% | 43 | 0.00 | no |
| IBO_SCAN5_M0_K1_XQ3_10 | 1,300 | 1.09 | 2,082 | 1.51 | 3,382 | 25% | 1.35 | +0.71% | +2,402% | 0.57 | 6.0% | -49.8% | 47% | 2.3% | 9 | 0.01 | no |
| IBO_SCAN5_M0_K1_XQ3_20 | 1,263 | 1.12 | 2,019 | 1.56 | 3,282 | 25% | 1.40 | +0.80% | +2,628% | 0.52 | 6.0% | -47.6% | 47% | 2.3% | 9 | 0.01 | no |
| IBO_SCAN5_M0_K5_XQ3_10 | 1,197 | 1.12 | 1,849 | 1.51 | 3,046 | 28% | 1.36 | +0.81% | +2,465% | 0.54 | 5.8% | -51.5% | 38% | 2.8% | 16 | 0.01 | no |
| IBO_SCAN5_M0_K5_XQ3_20 | 1,164 | 1.15 | 1,792 | 1.58 | 2,956 | 28% | 1.42 | +0.93% | +2,742% | 0.39 | 3.9% | -49.8% | 39% | 2.7% | 16 | 0.00 | no |
| IBO_SCAN5_M0_K30_XQ3_10 | 833 | 1.02 | 1,254 | 1.57 | 2,087 | 34% | 1.36 | +0.88% | +1,838% | 0.08 | 0.4% | -49.9% | 22% | 3.6% | 43 | 0.00 | no |
| IBO_SCAN5_M0_K30_XQ3_20 | 808 | 1.13 | 1,223 | 1.62 | 2,031 | 34% | 1.43 | +1.07% | +2,178% | 0.05 | -0.2% | -47.3% | 22% | 3.6% | 43 | 0.00 | no |
| IBO_SCAN5_M1_K1_XQ3_10 | 810 | 1.16 | 1,787 | 1.55 | 2,597 | 25% | 1.44 | +0.88% | +2,280% | 0.38 | 2.5% | -45.1% | 46% | 2.3% | 9 | 0.00 | no |
| IBO_SCAN5_M1_K1_XQ3_20 | 799 | 1.09 | 1,737 | 1.61 | 2,536 | 25% | 1.45 | +0.91% | +2,310% | 0.32 | 2.0% | -44.3% | 46% | 2.3% | 9 | 0.00 | no |
| IBO_SCAN5_M1_K5_XQ3_10 | 746 | 1.20 | 1,583 | 1.56 | 2,329 | 28% | 1.46 | +1.02% | +2,365% | 0.89 | 9.5% | -42.1% | 37% | 2.8% | 17 | 0.01 | no |
| IBO_SCAN5_M1_K5_XQ3_20 | 731 | 1.16 | 1,538 | 1.64 | 2,269 | 28% | 1.49 | +1.09% | +2,481% | 0.56 | 5.5% | -39.4% | 37% | 2.8% | 17 | 0.01 | no |
| IBO_SCAN5_M1_K30_XQ3_10 | 526 | 1.11 | 1,075 | 1.67 | 1,601 | 35% | 1.50 | +1.21% | +1,941% | 0.49 | 4.3% | -30.9% | 20% | 3.7% | 43 | 0.00 | no |
| IBO_SCAN5_M1_K30_XQ3_20 | 515 | 1.05 | 1,053 | 1.72 | 1,568 | 36% | 1.51 | +1.26% | +1,974% | -0.06 | -0.7% | -42.9% | 20% | 3.7% | 43 | 0.00 | no |
| IEP_N0_Q05_K1_XQ3_10 | 448 | 0.77 | 943 | 1.32 | 1,391 | 24% | 1.15 | +0.60% | +831% | 2.10 | 27.4% | -35.6% | 55% | 4.2% | 2 | 0.09 | no |
| IEP_N0_Q05_K1_XQ3_20 | 447 | 0.80 | 938 | 1.53 | 1,385 | 24% | 1.31 | +1.19% | +1,650% | 4.12 | 40.1% | -25.9% | 55% | 4.2% | 2 | 0.23 | no |
| IEP_N0_Q05_K5_XQ3_10 | 307 | 0.77 | 652 | 1.23 | 959 | 30% | 1.09 | +0.48% | +463% | 2.62 | 19.6% | -19.1% | 38% | 6.4% | 16 | 0.06 | YES |
| IEP_N0_Q05_K5_XQ3_20 | 306 | 0.87 | 648 | 1.41 | 954 | 30% | 1.25 | +1.27% | +1,215% | 3.75 | 27.0% | -21.0% | 38% | 6.4% | 16 | 0.15 | YES |
| IEP_N0_Q05_K30_XQ3_10 | 133 | 0.55 | 294 | 1.40 | 427 | 37% | 1.15 | +0.90% | +386% | 1.81 | 7.1% | -18.1% | 22% | 8.3% | 46 | 0.01 | no |
| IEP_N0_Q05_K30_XQ3_20 | 133 | 0.59 | 292 | 1.59 | 425 | 37% | 1.30 | +1.75% | +743% | 2.53 | 10.6% | -15.7% | 22% | 8.3% | 46 | 0.03 | no |
| IEP_N0_Q10_K1_XQ3_10 | 376 | 0.76 | 617 | 1.15 | 993 | 26% | 1.01 | +0.05% | +51% | 1.03 | 12.1% | -32.5% | 53% | 4.5% | 2 | 0.02 | no |
| IEP_N0_Q10_K1_XQ3_20 | 375 | 0.79 | 617 | 1.31 | 992 | 26% | 1.12 | +0.50% | +499% | 2.25 | 22.4% | -25.2% | 53% | 4.5% | 2 | 0.12 | no |
| IEP_N0_Q10_K5_XQ3_10 | 244 | 0.64 | 385 | 1.08 | 629 | 32% | 0.92 | -0.46% | -286% | 0.73 | 5.7% | -18.4% | 36% | 6.9% | 24 | 0.01 | no |
| IEP_N0_Q10_K5_XQ3_20 | 243 | 0.72 | 385 | 1.19 | 628 | 32% | 1.02 | +0.11% | +66% | 1.54 | 11.6% | -17.1% | 36% | 6.9% | 24 | 0.05 | no |
| IEP_N0_Q10_K30_XQ3_10 | 110 | 0.47 | 179 | 1.53 | 289 | 38% | 1.14 | +0.83% | +240% | 1.65 | 5.9% | -10.8% | 21% | 8.4% | 45 | 0.02 | no |
| IEP_N0_Q10_K30_XQ3_20 | 110 | 0.51 | 179 | 1.64 | 289 | 38% | 1.22 | +1.31% | +379% | 1.96 | 7.5% | -8.2% | 21% | 8.4% | 45 | 0.04 | no |
| IEP_N1_Q05_K1_XQ3_10 | 307 | 0.63 | 625 | 1.56 | 932 | 25% | 1.26 | +0.98% | +909% | 3.12 | 25.7% | -25.1% | 54% | 4.2% | 2 | 0.09 | no |
| IEP_N1_Q05_K1_XQ3_20 | 307 | 0.68 | 625 | 1.84 | 932 | 25% | 1.47 | +1.75% | +1,635% | 4.81 | 38.1% | -23.8% | 54% | 4.2% | 2 | 0.25 | YES |
| IEP_N1_Q05_K5_XQ3_10 | 209 | 0.72 | 427 | 1.40 | 636 | 32% | 1.19 | +0.93% | +589% | 3.17 | 16.3% | -17.8% | 34% | 6.4% | 18 | 0.05 | YES |
| IEP_N1_Q05_K5_XQ3_20 | 209 | 0.85 | 427 | 1.65 | 636 | 33% | 1.40 | +1.97% | +1,253% | 4.72 | 26.2% | -16.8% | 34% | 6.4% | 18 | 0.18 | YES |
| IEP_N1_Q05_K30_XQ3_10 | 82 | 0.51 | 195 | 1.35 | 277 | 40% | 1.14 | +0.78% | +215% | 1.66 | 5.3% | -18.0% | 19% | 8.2% | 49 | 0.01 | no |
| IEP_N1_Q05_K30_XQ3_20 | 82 | 0.62 | 195 | 1.67 | 277 | 40% | 1.40 | +2.25% | +622% | 2.56 | 9.3% | -15.2% | 19% | 8.2% | 49 | 0.02 | no |
| IEP_N1_Q10_K1_XQ3_10 | 259 | 0.63 | 378 | 1.33 | 637 | 27% | 1.05 | +0.19% | +119% | 1.22 | 9.0% | -21.1% | 53% | 4.4% | 2 | 0.02 | no |
| IEP_N1_Q10_K1_XQ3_20 | 259 | 0.68 | 378 | 1.56 | 637 | 27% | 1.20 | +0.80% | +512% | 2.39 | 17.2% | -21.3% | 53% | 4.4% | 2 | 0.10 | YES |
| IEP_N1_Q10_K5_XQ3_10 | 167 | 0.52 | 222 | 1.22 | 389 | 33% | 0.93 | -0.40% | -154% | 0.76 | 4.0% | -17.1% | 35% | 6.8% | 25 | 0.00 | no |
| IEP_N1_Q10_K5_XQ3_20 | 167 | 0.62 | 222 | 1.38 | 389 | 33% | 1.06 | +0.30% | +117% | 1.85 | 8.3% | -16.1% | 35% | 6.8% | 25 | 0.03 | no |
| IEP_N1_Q10_K30_XQ3_10 | 71 | 0.42 | 102 | 1.67 | 173 | 42% | 1.17 | +0.98% | +169% | 2.25 | 5.4% | -6.8% | 18% | 7.9% | 47 | 0.04 | no |
| IEP_N1_Q10_K30_XQ3_20 | 71 | 0.53 | 102 | 1.90 | 173 | 42% | 1.35 | +1.99% | +343% | 2.79 | 7.4% | -6.2% | 18% | 7.9% | 47 | 0.10 | no |

## 3. Pre-registered criteria on 2016-2020

Passed: IEP_N0_Q05_K5_XQ3_10, IEP_N0_Q05_K5_XQ3_20, IEP_N1_Q05_K1_XQ3_20, IEP_N1_Q05_K5_XQ3_10, IEP_N1_Q05_K5_XQ3_20, IEP_N1_Q10_K1_XQ3_20.

## 4. Median trade-level PF 2016-2020 by rule

### IBO: by selection

| selection | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| SCAN35 | 1.01 | 1.43 | 1.26 |
| SCAN5 | 1.12 | 1.57 | 1.43 |

### IBO: by market

| market | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| M0 | 1.05 | 1.47 | 1.31 |
| M1 | 1.03 | 1.52 | 1.37 |

### IBO: by opening range

| opening range | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| K1 | 1.06 | 1.49 | 1.32 |
| K30 | 1.03 | 1.53 | 1.33 |
| K5 | 1.07 | 1.50 | 1.33 |

### IBO: by exit

| exit | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| XQ3_10 | 1.03 | 1.48 | 1.32 |
| XQ3_20 | 1.05 | 1.53 | 1.35 |

### IEP: by neglect

| neglect | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| N0 | 0.74 | 1.36 | 1.15 |
| N1 | 0.62 | 1.56 | 1.20 |

### IEP: by volume

| volume | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| Q05 | 0.70 | 1.47 | 1.26 |
| Q10 | 0.63 | 1.35 | 1.09 |

### IEP: by opening range

| opening range | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| K1 | 0.72 | 1.43 | 1.18 |
| K30 | 0.52 | 1.62 | 1.20 |
| K5 | 0.72 | 1.30 | 1.08 |

### IEP: by exit

| exit | 2016-2018 | 2019-2020 | 2016-2020 |
|---|---|---|---|
| XQ3_10 | 0.63 | 1.34 | 1.14 |
| XQ3_20 | 0.68 | 1.58 | 1.27 |


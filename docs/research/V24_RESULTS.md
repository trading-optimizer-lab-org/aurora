# v24 results: long-only small caps on one-minute bars (208,032 configurations)

Pre-registered in [V24_PREREGISTRATION.md](V24_PREREGISTRATION.md).

| run | GitHub run | what happened |
|---|---|---|
| v24 data | 39591258262 | the mover store (100 largest absolute gaps of each session outside the v23 liquid set) |
| v24, attempt 1 | 39594220034 (2026-10-21 11:44-14:12 UTC) | 298 of 300 shards finished; shards 10 and 255 lost their runner ("The hosted runner lost communication with the server") at about 47 minutes, so select and the report did not run |
| **v24, attempt 2** | **39594220034** (2026-10-21 14:15-15:31 UTC) | **this report**: the two failed shards rerun unchanged, then select, placebos and report |

208,032 of 208,032 configurations, no errors, 500 placebos for each selected configuration, R4 costs.

## Summary

- **The pre-registered criterion is not met, and no long family passes.** All 28 families have a negative
  walk-forward monthly Sortino at the middle costs; every one fails the gate. No family's yearly pick scored 1.0 on
  the data before, so `COMBO24` held no position in any year (0% a year; its Sortino of -2.82 is a zero return
  measured against T-bills).
- **The longs lose before costs.** Without any cost (gross) only 4 of 28 families are above zero: PH (power hour)
  0.78, NB (noise-area breakout) 0.67, PX (patterns) 0.60, SP (in-play opening range) 0.13. In sample, the median Sortino
  of every entry and exit value of every family is negative (-1.2 to -3.3). Costs make it worse; they are not the cause.
- **Best families** (middle costs): PX (high tight flag and pennant on gap-ups, $8-20) -0.12 and 1.4% a year,
  PH -0.50, NB -0.60, LH -0.79. In the 2023-07+ segment only PX is positive (0.47, 6.3% a year, drawdown -9.7%), with
  SPA p 1.000: not distinguishable from luck over 208,032 trials.
- **Trades**: the mean net return a trade is negative in 26 of 28 families (PH +0.3%, PX +0.8%); win rates 16-37%;
  the worst single trades lose 13-75% of the position.
- **The new universes add nothing on the long side.** The liquid scope (v23's 100 most liquid small caps) was picked
  only by RG and GF, both failing; the moderate gappers (mover_up) were picked by LP and D2, both failing. The picks
  lean on a 10% stop, held to the close or to the third close, $8-20, on day-2 and gap-up names.
- **No look-ahead signs**: every family falls monotonically from low to middle to high costs, the gross result is the
  best in every family, nothing sits near the Sortino cap, and the results are negative.
- With v14-v24, no small-cap long rule on one-minute or daily bars has passed in this data; every passing family of
  the series is a short.

## Report

Configurations evaluated 208032 of 208032; errors 0. R4 costs (middle) unless stated; 500 placebos for each selected configuration; a configuration can be picked only with at least 50 trades and a trade in 40% of the months before. Target: COMBO24 monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | years placebo-ok | gate | PBO | SPA p (best t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DL | -1.67 | -0.89 | -1.97 | -4.1% | -36.1% | -1.58 | -1.82 | -1.67 | -1.39 | 3/9 | fail | 10% | 1.000 (0.9) |
| SR | -1.59 | -1.58 | -1.58 | -6.8% | -46.6% | -1.46 | -1.80 | -1.59 | -1.16 | 2/9 | fail | 0% | 1.000 (0.8) |
| LV | -0.93 | -1.04 | -0.87 | -3.5% | -33.7% | -0.80 | -1.15 | -0.93 | -0.47 | 2/9 | fail | 0% | 1.000 (-1.1) |
| LE | -1.42 | -1.28 | -1.48 | -4.1% | -31.7% | -1.29 | -1.65 | -1.42 | -0.97 | 1/9 | fail | 0% | 1.000 (-0.9) |
| LO | -2.16 | -2.14 | -2.15 | -3.2% | -24.9% | -2.07 | -2.29 | -2.15 | -1.79 | 2/9 | fail | 0% | 0.940 (0.6) |
| LM | -1.50 | -1.60 | -1.43 | -11.1% | -67.0% | -1.36 | -1.73 | -1.50 | -0.99 | 1/9 | fail | 0% | 1.000 (-2.0) |
| LS | -1.57 | -1.77 | -1.47 | -7.6% | -50.4% | -1.46 | -1.76 | -1.57 | -1.13 | 1/9 | fail | 0% | 1.000 (-0.5) |
| LP | -1.17 | -0.88 | -1.31 | -5.8% | -53.6% | -1.04 | -1.38 | -1.18 | -0.68 | 3/9 | fail | 0% | 0.944 (0.6) |
| LC | -1.77 | -1.58 | -1.84 | -3.7% | -35.9% | -1.59 | -2.02 | -1.76 | -1.17 | 1/9 | fail | 0% | 1.000 (-0.1) |
| LX | -1.66 | -1.58 | -1.72 | -2.4% | -20.3% | -1.41 | -2.04 | -1.63 | -0.82 | 1/9 | fail | 0% | 1.000 (-1.4) |
| LR | -1.18 | -1.07 | -1.26 | -1.4% | -15.7% | -1.03 | -1.42 | -1.17 | -0.48 | 0/9 | fail | 0% | 1.000 (-0.1) |
| SP | -1.08 | 0.65 | -1.60 | -5.6% | -49.3% | -0.79 | -1.54 | -0.91 | 0.13 | 1/9 | fail | 0% | 1.000 (-0.8) |
| NB | -0.60 | -0.17 | -0.74 | -8.7% | -63.0% | -0.15 | -1.26 | -0.46 | 0.67 | 1/9 | fail | 0% | 0.919 (0.5) |
| LH | -0.79 | -0.45 | -1.18 | -2.6% | -26.2% | -0.64 | -1.02 | -0.77 | -0.18 | 5/9 | fail | 3% | 0.997 (0.6) |
| PH | -0.50 | 0.66 | -1.08 | -2.5% | -55.3% | -0.18 | -1.01 | -0.51 | 0.78 | 6/9 | fail | 10% | 0.994 (0.6) |
| MP | -1.57 | -1.77 | -1.51 | -11.8% | -66.9% | -1.44 | -1.77 | -1.57 | -0.82 | 0/9 | fail | 2% | 1.000 (-0.7) |
| AB | -1.35 | -1.66 | -1.34 | -10.3% | -61.6% | -1.25 | -1.52 | -1.35 | -0.93 | 0/9 | fail | 0% | 0.967 (0.7) |
| HR | -1.37 | -0.68 | -1.62 | -10.1% | -61.1% | -1.26 | -1.56 | -1.35 | -1.01 | 1/9 | fail | 10% | 0.998 (1.0) |
| MD | -0.87 | -1.21 | -0.74 | -2.5% | -29.0% | -0.74 | -1.10 | -0.85 | -0.46 | 0/9 | fail | 8% | 0.998 (0.2) |
| RG | -2.03 | -2.11 | -1.98 | -7.5% | -49.5% | -1.86 | -2.26 | -1.96 | -1.36 | 5/9 | fail | 0% | 1.000 (-1.1) |
| GF | -1.70 | -2.18 | -1.49 | -6.5% | -44.5% | -1.58 | -1.87 | -1.70 | -1.20 | 4/9 | fail | 4% | 1.000 (-0.8) |
| D2 | -1.42 | -1.24 | -1.51 | -2.5% | -25.5% | -1.32 | -1.59 | -1.38 | -1.04 | 3/9 | fail | 19% | 0.983 (0.8) |
| IX | -1.23 | -1.04 | -1.35 | -11.6% | -68.5% | -1.03 | -1.53 | -1.23 | -0.50 | 3/9 | fail | 0% | 0.999 (0.7) |
| PX | -0.12 | 0.03 | -0.23 | 1.4% | -32.9% | 0.09 | -0.48 | -0.13 | 0.60 | 1/9 | fail | 0% | 1.000 (0.3) |
| CK | -1.89 | -2.29 | -1.81 | -6.6% | -45.3% | -1.72 | -2.14 | -1.88 | -1.05 | 4/9 | fail | 0% | 1.000 (0.3) |
| WO | -1.72 | -1.96 | -1.56 | -5.8% | -42.4% | -1.54 | -1.93 | -1.70 | -0.89 | 8/9 | fail | 8% | 0.916 (0.7) |
| HG | -1.35 | -1.42 | -1.31 | -7.8% | -53.0% | -1.15 | -1.67 | -1.36 | -0.70 | 0/9 | fail | 0% | 1.000 (-1.4) |
| TS | -1.33 | -1.07 | -1.48 | -8.8% | -60.3% | -1.24 | -1.49 | -1.32 | -0.87 | 3/9 | fail | 5% | 1.000 (0.7) |

## 2. COMBO24 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO24 | -2.82 | -2.92 | -2.96 | 0.0% | 0.0% | +0% | -3.37 | 0.00 | - | not met |

Members by year: 2018: none; 2019: none; 2020: none; 2021: none; 2022: none; 2023: none; 2024: none; 2025: none; 2026: none

COMBO24 by year: 2018 +0.0%, 2019 +0.0%, 2020 +0.0%, 2021 +0.0%, 2022 +0.0%, 2023 +0.0%, 2024 +0.0%, 2025 +0.0%, 2026 +0.0%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| DL | -2.38 | -5.3% | -16.4% |
| SR | -1.78 | -8.3% | -28.1% |
| LV | -0.56 | 0.5% | -13.3% |
| LE | -1.33 | -3.4% | -17.8% |
| LO | -2.54 | -3.6% | -12.4% |
| LM | -1.47 | -11.3% | -38.0% |
| LS | -1.70 | -8.5% | -26.6% |
| LP | -1.40 | -10.8% | -45.5% |
| LC | -1.59 | -2.5% | -17.2% |
| LX | -2.14 | -4.8% | -15.4% |
| LR | -1.19 | 0.0% | -5.8% |
| SP | -2.18 | -11.8% | -34.8% |
| NB | -1.29 | -16.5% | -63.0% |
| LH | -1.53 | -1.9% | -12.6% |
| PH | -0.56 | -0.7% | -33.3% |
| MP | -2.46 | -10.8% | -31.2% |
| AB | -1.39 | -9.2% | -43.2% |
| HR | -1.83 | -18.3% | -49.9% |
| MD | -0.38 | 1.5% | -18.1% |
| RG | -2.10 | -7.3% | -22.1% |
| GF | -1.83 | -2.2% | -11.2% |
| D2 | -2.56 | -6.3% | -20.8% |
| IX | -1.44 | -15.3% | -54.3% |
| PX | 0.47 | 6.3% | -9.7% |
| CK | -1.82 | -7.2% | -22.1% |
| WO | -1.26 | -0.5% | -11.9% |
| HG | -1.76 | -9.3% | -33.7% |
| TS | -1.42 | -6.4% | -29.4% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| DL | 2.5 | -3.2% | 33% | -36% |
| SR | 4.5 | -2.3% | 29% | -73% |
| LV | 3.8 | -1.4% | 22% | -33% |
| LE | 3.8 | -1.8% | 27% | -24% |
| LO | 2.6 | -1.9% | 37% | -18% |
| LM | 7.2 | -2.6% | 24% | -62% |
| LS | 4.0 | -2.8% | 24% | -60% |
| LP | 4.7 | -1.8% | 30% | -52% |
| LC | 4.3 | -1.3% | 33% | -14% |
| LX | 4.5 | -0.9% | 36% | -13% |
| LR | 2.8 | -0.9% | 34% | -15% |
| SP | 8.5 | -2.1% | 31% | -60% |
| NB | 12.3 | -0.4% | 28% | -45% |
| LH | 4.2 | -1.0% | 30% | -43% |
| PH | 5.0 | +0.3% | 26% | -29% |
| MP | 4.3 | -2.0% | 16% | -26% |
| AB | 5.5 | -2.7% | 20% | -46% |
| HR | 6.6 | -2.2% | 22% | -75% |
| MD | 3.3 | -1.1% | 19% | -43% |
| RG | 4.2 | -2.7% | 30% | -52% |
| GF | 3.9 | -2.2% | 35% | -31% |
| D2 | 1.9 | -2.7% | 28% | -58% |
| IX | 11.6 | -1.3% | 30% | -50% |
| PX | 3.3 | +0.8% | 25% | -23% |
| CK | 5.2 | -2.0% | 32% | -17% |
| WO | 4.7 | -2.5% | 33% | -46% |
| HG | 7.0 | -1.8% | 28% | -27% |
| TS | 5.5 | -3.1% | 26% | -74% |

## 5. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| DL | level | h20 -2.45 (1) / h60 -2.39 (3) / h252 -2.37 (5) / l20 -2.41 (0) / l60 -2.37 (0) / sma20d -2.40 (0) / sma50d -2.36 (0) / sma200d -2.31 (0) |
| DL | setup | break_up -2.34 (5) / fail_dn -2.43 (4) / retest_up -2.39 (0) |
| DL | vol | 0.0 -2.33 (4) / 2.0 -2.43 (5) |
| DL | window | open -2.40 (9) / midlate -2.40 (0) / all -2.35 (0) |
| DL | stop | lvl1 -2.40 (0) / pct10 -2.36 (9) |
| DL | exit | r2 -2.35 (0) / nextlevel -2.50 (0) / ema9 -2.68 (0) / close -2.26 (2) / d3 -2.06 (7) / trail10 -2.35 (0) |
| DL | scope | liquid -2.70 (0) / mover_up -2.35 (4) / mover_dn -2.43 (0) / gapup -2.15 (3) / runner -2.16 (2) / gapdown -2.54 (0) |
| DL | band | 1-3 -2.34 (1) / 3-8 -2.34 (1) / 8-20 -2.47 (7) |
| SR | level | pmh -2.50 (4) / pml -2.45 (0) / pdh -2.50 (0) / pdl -2.39 (0) / pdc -2.49 (3) / orh5 -2.63 (0) / orl5 -2.48 (0) / orh15 -2.68 (2) / orl15 -2.50 (0) / orh30 -2.71 (0) / orl30 -2.49 (0) / h5 -2.49 (0) / l5 -2.58 (0) / round1 -2.25 (0) / round050 -2.34 (0) / pivot -2.45 (0) / r1 -2.52 (0) / s1 -2.33 (0) |
| SR | setup | break_up -2.43 (9) / fail_dn -2.53 (0) / retest_up -2.48 (0) |
| SR | vol | 0.0 -2.49 (1) / 2.0 -2.48 (8) |
| SR | window | open -2.39 (4) / midlate -2.56 (5) / all -2.50 (0) |
| SR | stop | lvl1 -2.55 (0) / pct10 -2.40 (9) |
| SR | exit | r2 -2.46 (0) / nextlevel -2.61 (0) / ema9 -2.78 (0) / close -2.33 (0) / d3 -2.10 (8) / be1r -2.45 (1) |
| SR | scope | mover_up -2.75 (2) / mover_dn -2.73 (0) / gapdown -2.33 (0) / day2 -2.14 (7) |
| SR | band | 1-3 -2.52 (0) / 3-8 -2.43 (4) / 8-20 -2.49 (5) |
| LV | setup | reclaim -2.71 (0) / bounce -2.68 (0) / revert_lo -2.76 (0) / break_hi -2.45 (9) |
| LV | after | 15 -2.67 (3) / 60 -2.68 (6) |
| LV | vol | 0.0 -2.71 (1) / 2.0 -2.66 (8) |
| LV | stop | swing -2.78 (0) / pct10 -2.58 (9) |
| LV | exit | r2 -2.70 (1) / vwapx -2.80 (0) / ema9 -2.97 (0) / t30 -2.79 (1) / close -2.57 (0) / d3 -2.19 (7) |
| LV | scope | mover_up -3.11 (0) / mover_dn -3.12 (0) / gapdown -2.36 (0) / day2 -2.06 (9) |
| LV | band | 1-3 -2.78 (0) / 3-8 -2.59 (2) / 8-20 -2.63 (7) |
| LE | pair | 9/20 -2.58 (0) / 20/50 -2.54 (3) / 50/200 -2.47 (6) |
| LE | tf | 1 -2.65 (1) / 5 -2.54 (0) / 15 -2.43 (8) |
| LE | setup | cross -2.46 (8) / pullback -2.63 (1) |
| LE | side | long -2.53 (9) |
| LE | stop | swing -2.71 (0) / pct10 -2.36 (9) |
| LE | exit | crossback -2.56 (1) / r2 -2.72 (0) / t30 -2.81 (2) / close -2.46 (0) / d3 -2.21 (6) |
| LE | scope | mover_up -2.97 (0) / mover_dn -3.04 (0) / gapdown -2.23 (0) / day2 -1.87 (9) |
| LE | band | 1-3 -2.72 (0) / 3-8 -2.44 (3) / 8-20 -2.41 (6) |
| LO | ind | rsi2 -2.71 (3) / rsi7 -2.57 (1) / rsi14 -2.51 (4) / stoch14 -2.95 (1) |
| LO | tf | 1 -2.73 (3) / 5 -2.60 (6) |
| LO | lvl | x10 -2.65 (7) / x20 -2.67 (2) |
| LO | side | long -2.66 (9) |
| LO | confirm | none -2.67 (5) / turn -2.65 (4) |
| LO | near | any -2.54 (8) / level -2.73 (1) |
| LO | stop | swing -2.72 (0) / pct10 -2.58 (9) |
| LO | exit | mid -2.75 (0) / r2 -2.65 (4) / t30 -2.68 (1) / close -2.50 (4) |
| LO | scope | mover_up -2.95 (0) / mover_dn -2.91 (2) / gapdown -2.52 (2) / day2 -2.41 (5) |
| LO | band | 1-3 -2.68 (3) / 3-8 -2.62 (5) / 8-20 -2.67 (1) |
| LM | set | 12/26/9 -2.76 (7) / 5/35/5 -2.77 (2) |
| LM | tf | 1 -2.79 (1) / 5 -2.75 (8) |
| LM | signal | cross -2.68 (0) / zero -2.62 (9) / div -2.90 (0) |
| LM | side | long -2.77 (9) |
| LM | stop | swing -2.87 (0) / pct10 -2.58 (9) |
| LM | exit | crossback -3.00 (0) / r2 -2.89 (1) / t30 -2.96 (0) / close -2.73 (0) / d3 -2.42 (8) |
| LM | scope | mover_up -3.16 (0) / mover_dn -3.18 (0) / gapdown -2.44 (2) / day2 -2.09 (7) |
| LM | band | 1-3 -2.87 (0) / 3-8 -2.70 (0) / 8-20 -2.61 (9) |
| LS | kc | 1.5 -2.47 (4) / 2.0 -2.60 (5) |
| LS | bars | 10 -2.57 (2) / 20 -2.50 (7) |
| LS | side | long -2.53 (9) |
| LS | vol | 0.0 -2.59 (5) / 2.0 -2.48 (4) |
| LS | stop | swing -2.63 (2) / pct10 -2.43 (7) |
| LS | exit | r2 -2.45 (1) / ema9 -2.91 (0) / t30 -2.73 (2) / close -2.40 (0) / d3 -2.09 (6) |
| LS | scope | mover_up -2.91 (0) / mover_dn -2.92 (0) / gapdown -2.39 (0) / day2 -1.84 (9) |
| LS | band | 1-3 -2.73 (0) / 3-8 -2.37 (6) / 8-20 -2.44 (3) |
| LP | pattern | double_bottom -2.68 (0) / asc_triangle -2.66 (0) / bull_flag -1.95 (9) |
| LP | size | small -2.48 (6) / large -2.23 (3) |
| LP | after | 15 -2.34 (0) / 60 -2.31 (9) |
| LP | stop | pattern -2.43 (0) / pct10 -2.25 (9) |
| LP | exit | r2 -2.14 (0) / measured -2.33 (0) / ema9 -2.77 (0) / close -2.13 (1) / d3 -2.11 (8) |
| LP | scope | mover_up -2.86 (7) / mover_dn -2.91 (0) / gapdown -2.17 (0) / day2 -1.76 (2) |
| LP | band | 1-3 -2.52 (0) / 3-8 -2.26 (0) / 8-20 -2.20 (9) |
| LC | candle | engulf -2.70 (5) / pin -2.79 (2) / inside -2.63 (2) / doji -2.79 (0) |
| LC | cside | long -2.72 (9) |
| LC | at | pm -2.74 (2) / pd -2.67 (1) / vwap -2.82 (3) / hod -2.73 (3) |
| LC | tf | 1 -2.74 (6) / 5 -2.70 (3) |
| LC | stop | swing -2.83 (1) / pct10 -2.67 (8) |
| LC | exit | r1 -2.75 (1) / r2 -2.67 (3) / t15 -2.88 (0) / t30 -2.84 (1) / close -2.54 (4) |
| LC | scope | mover_up -3.10 (0) / mover_dn -3.10 (0) / gapdown -2.34 (0) / day2 -2.22 (9) |
| LC | band | 1-3 -2.76 (0) / 3-8 -2.67 (6) / 8-20 -2.73 (3) |
| LX | mult | 5.0 -2.88 (2) / 10.0 -2.66 (7) |
| LX | candle | lowwick -2.76 (0) / bigup -2.70 (9) |
| LX | after | 15 -2.73 (4) / 60 -2.74 (5) |
| LX | stop | swing -2.92 (0) / pct10 -2.67 (9) |
| LX | exit | r1 -2.75 (1) / r2 -2.70 (7) / t15 -2.96 (1) / t30 -2.93 (0) / close -2.59 (0) |
| LX | scope | mover_up -3.16 (0) / mover_dn -3.12 (0) / gapdown -2.41 (1) / day2 -2.15 (8) |
| LX | band | 1-3 -2.86 (0) / 3-8 -2.63 (7) / 8-20 -2.71 (2) |
| LR | k | 1 -2.75 (1) / 5 -2.61 (0) / 15 -2.53 (0) / 30 -2.47 (5) / 60 -2.43 (3) |
| LR | side | long -2.57 (9) |
| LR | filter | none -2.51 (0) / vwap -2.46 (0) / rvol -2.42 (3) / gapdir -2.82 (6) |
| LR | stop | range -2.57 (0) / half -2.82 (0) / pct10 -2.36 (9) |
| LR | exit | r1 -2.73 (0) / r2 -2.60 (4) / r3 -2.53 (3) / close -2.49 (2) / d3 -2.13 (0) / ema9 -2.82 (0) |
| LR | scope | mover_up -2.78 (0) / mover_dn -2.85 (0) / gapdown -2.31 (0) / day2 -1.67 (9) |
| LR | band | 1-3 -2.64 (0) / 3-8 -2.50 (6) / 8-20 -2.52 (3) |
| SP | sel | top5 -3.01 (8) / top10 -3.08 (1) / top20 -3.14 (0) / rv3 -3.20 (0) / rv6 -3.13 (0) |
| SP | k | 5 -3.15 (0) / 15 -3.12 (0) / 30 -3.06 (9) |
| SP | candle | green -3.06 (6) / any -3.16 (3) |
| SP | gapdir | any -3.16 (0) / up -3.07 (9) |
| SP | stop | atr10 -3.25 (0) / atr25 -3.13 (0) / range -2.42 (9) |
| SP | exit | close -3.09 (0) / r2 -3.18 (0) / r5 -3.13 (0) / trail10 -3.12 (0) / vwapx -3.14 (0) / next_open -2.98 (9) |
| SP | scope | inplay -3.11 (9) |
| SP | band | 1-3 -3.07 (1) / 3-8 -3.06 (8) / 8-20 -3.21 (0) |
| NB | k | 0.5 -2.68 (0) / 1.0 -2.61 (3) / 1.5 -2.51 (6) / 2.0 -2.41 (0) |
| NB | check | 1m -2.70 (0) / 30m -2.35 (9) |
| NB | filter | none -2.60 (0) / vwap -2.59 (1) / rv2 -2.52 (8) |
| NB | stop | pct5 -2.65 (4) / pct10 -2.49 (5) |
| NB | exit | bound -2.68 (0) / close -2.44 (1) / r2 -2.67 (0) / trail10 -2.72 (0) / next_open -2.10 (8) |
| NB | scope | liquid -2.86 (0) / mover_up -2.55 (0) / gapup -2.22 (9) / inplay -2.75 (0) |
| NB | band | 1-3 -2.49 (0) / 3-8 -2.54 (1) / 8-20 -2.73 (8) |
| LH | up | 0.02 -2.19 (1) / 0.05 -2.06 (0) / 0.1 -1.86 (0) / 0.2 -1.95 (8) |
| LH | filter | none -2.46 (0) / vwap -1.64 (4) / hod -1.90 (5) |
| LH | at | 270 -1.88 (2) / 330 -2.06 (7) / 360 -2.14 (0) |
| LH | stop | pct10 -1.97 (9) / pct20 -2.10 (0) |
| LH | exit | close -2.52 (0) / next_open -2.04 (1) / d2 -1.86 (4) / d3 -1.72 (4) |
| LH | scope | liquid -2.11 (0) / mover_up -2.17 (0) / gapup -1.98 (5) / runner -1.83 (4) |
| LH | band | 1-3 -1.99 (5) / 3-8 -2.08 (1) / 8-20 -2.03 (3) |
| PH | after | 240 -1.96 (7) / 270 -1.90 (0) / 300 -1.85 (2) |
| PH | day | 0.0 -1.97 (0) / 0.05 -1.92 (0) / 0.1 -1.78 (9) |
| PH | vol | 0.0 -1.87 (5) / 2.0 -1.90 (4) |
| PH | stop | swing -2.07 (0) / pct5 -1.91 (9) / pct10 -1.71 (0) |
| PH | exit | close -2.06 (0) / next_open -1.68 (0) / d2 -1.63 (8) / d3 -1.69 (1) / trail5 -2.47 (0) |
| PH | scope | liquid -2.36 (0) / mover_up -2.28 (2) / gapup -1.24 (4) / runner -1.69 (3) |
| PH | band | 1-3 -1.96 (0) / 3-8 -1.85 (0) / 8-20 -1.81 (9) |
| MP | impulse | m3 -2.59 (0) / m6 -2.47 (5) / m10 -2.32 (4) |
| MP | retrace | 0.33 -2.37 (9) / 0.5 -2.55 (0) |
| MP | vol | any -2.49 (3) / dry -2.45 (6) |
| MP | window | open -2.42 (7) / all -2.52 (2) |
| MP | stop | pb -2.52 (0) / pct5 -2.41 (9) |
| MP | exit | r2 -2.57 (0) / r3 -2.47 (1) / trail5 -2.54 (0) / trail10 -2.42 (0) / ema9 -2.59 (0) / close -2.18 (8) |
| MP | scope | gapup -2.53 (2) / runner -2.64 (2) / mover_up -2.74 (0) / liquid -2.26 (0) / day2 -2.10 (5) |
| MP | band | 1-3 -2.61 (0) / 3-8 -2.54 (0) / 8-20 -2.24 (9) |
| AB | run | 0.05 -2.33 (0) / 0.1 -2.13 (2) / 0.2 -1.96 (7) |
| AB | retr | 38-62 -2.07 (2) / 24-50 -2.18 (7) |
| AB | entry | atC -2.24 (1) / breakB -2.03 (8) |
| AB | stop | pb -2.23 (2) / pct10 -2.03 (7) |
| AB | exit | measured -2.13 (0) / r2 -2.17 (0) / trail10 -2.23 (0) / close -1.86 (3) / ema9 -2.48 (1) / d3 -1.79 (5) |
| AB | scope | gapup -2.10 (4) / runner -2.25 (3) / mover_up -2.40 (1) / liquid -2.14 (0) / day2 -1.73 (1) |
| AB | band | 1-3 -2.36 (0) / 3-8 -2.12 (1) / 8-20 -1.82 (8) |
| HR | dir | up -1.86 (8) / down -1.87 (1) |
| HR | move | 0.08 -1.86 (9) / 0.15 -1.87 (0) |
| HR | entry | resume -1.73 (8) / hold -1.90 (0) / dip -1.92 (1) |
| HR | stop | pb -1.86 (0) / pct10 -1.80 (6) / pct20 -1.97 (3) |
| HR | exit | r2 -1.80 (0) / trail10 -2.07 (0) / trail20 -1.82 (2) / close -1.64 (1) / next_open -1.68 (6) / t15 -1.91 (0) / ema9 -2.11 (0) |
| HR | scope | gapup -1.64 (0) / runner -1.69 (7) / mover_up -1.80 (2) / mover_dn -1.94 (0) / liquid -2.42 (0) |
| HR | band | 1-3 -1.94 (1) / 3-8 -1.96 (1) / 8-20 -1.66 (7) |
| MD | drop | 0.1 -2.26 (1) / 0.2 -1.99 (8) / 0.3 -2.12 (0) |
| MD | window | 30 -2.11 (6) / 60 -2.15 (3) |
| MD | trig | green5 -2.19 (0) / vwapre -2.04 (9) / hl -2.18 (0) / rsi -2.10 (0) |
| MD | stop | lod -2.16 (1) / pct10 -2.10 (8) |
| MD | exit | r2 -2.07 (0) / openx -2.12 (0) / trail10 -2.23 (0) / close -1.96 (2) / next_open -1.99 (5) / ema9 -2.39 (2) |
| MD | scope | gapup -2.19 (3) / runner -2.11 (5) / day2 -2.00 (1) / mover_up -2.27 (0) / liquid -2.11 (0) |
| MD | band | 1-3 -2.28 (0) / 3-8 -2.19 (2) / 8-20 -1.93 (7) |
| RG | gap | 0.0 -2.49 (0) / -0.02 -2.31 (5) / -0.05 -2.22 (4) |
| RG | after | 5 -2.32 (5) / 15 -2.36 (4) |
| RG | context | any -2.37 (3) / red2 -2.36 (5) / up20 -2.32 (1) |
| RG | vol | 0.0 -2.32 (6) / 2.0 -2.36 (3) |
| RG | stop | lod -2.44 (4) / pct10 -2.25 (5) |
| RG | exit | r2 -2.22 (0) / trail10 -2.40 (0) / ema9 -2.75 (0) / close -2.28 (0) / next_open -2.28 (2) / d3 -1.95 (7) |
| RG | scope | liquid -2.25 (7) / mover_dn -2.32 (2) / gapdown -2.41 (0) |
| RG | band | 1-3 -2.39 (3) / 3-8 -2.18 (3) / 8-20 -2.45 (3) |
| GF | gap | -0.04 -2.32 (0) / -0.08 -1.99 (1) / -0.15 -1.83 (8) |
| GF | trig | orh5 -1.97 (4) / orh15 -1.99 (1) / vwapre -2.09 (0) / hl -2.12 (1) / t30 -2.07 (3) |
| GF | stop | lod -2.08 (7) / pct10 -2.00 (2) |
| GF | exit | fill -2.12 (0) / half -2.12 (1) / close -2.09 (0) / next_open -1.81 (0) / d3 -1.94 (7) / r2 -2.02 (1) |
| GF | scope | liquid -1.74 (7) / mover_dn -2.57 (0) / gapdown -1.89 (2) |
| GF | band | 1-3 -2.33 (1) / 3-8 -2.02 (1) / 8-20 -1.72 (7) |
| D2 | day1 | 0.2 -1.86 (4) / 0.5 -1.98 (5) / 1.0 -2.27 (0) |
| D2 | loc | any -1.94 (8) / top20 -2.10 (1) |
| D2 | trig | pmh -1.97 (2) / orh5 -2.05 (4) / orh15 -1.98 (3) / vwap -1.94 (0) / open -2.05 (0) |
| D2 | stop | lod -2.03 (4) / pct10 -2.00 (5) |
| D2 | exit | r2 -1.90 (1) / trail10 -2.14 (0) / close -1.82 (0) / next_open -1.79 (8) / d3 -1.89 (0) / ema9 -2.41 (0) |
| D2 | scope | day2 -1.78 (1) / liquid -2.44 (1) / mover_up -1.93 (7) |
| D2 | band | 1-3 -2.06 (1) / 3-8 -2.04 (2) / 8-20 -1.97 (6) |
| IX | ind | supertrend -2.60 (0) / psar -2.74 (1) / heikin -2.88 (1) / ichimoku -2.82 (0) / cci -2.79 (0) / willr -2.86 (0) / mfi -2.72 (0) / obv -2.82 (0) / aroon -2.82 (0) / don20 -2.69 (2) / don55 -2.82 (4) / kelt -2.45 (1) / roc -2.85 (0) / trix -2.82 (0) / adx -2.82 (0) / stack -2.59 (0) |
| IX | tf | 1 -2.86 (3) / 5 -2.76 (2) / 15 -2.82 (4) |
| IX | filter | none -2.82 (0) / vwap -2.76 (8) / ema50 -2.82 (1) |
| IX | stop | swing -2.82 (0) / pct10 -2.76 (9) |
| IX | exit | opp -2.82 (0) / r2 -2.82 (0) / trail10 -2.82 (0) / ema9 -2.91 (0) / close -2.74 (1) / d3 -2.36 (8) |
| IX | scope | liquid -2.95 (0) / mover_up -2.94 (0) / gapup -2.52 (5) / runner -2.43 (4) |
| IX | band | 1-3 -2.82 (0) / 3-8 -2.82 (1) / 8-20 -2.82 (8) |
| PX | pattern | inv_hs -2.70 (0) / triple_bottom -2.76 (0) / cup_handle -2.53 (1) / rectangle -2.81 (0) / pennant -1.98 (4) / htf -1.78 (4) |
| PX | size | small -2.55 (1) / large -2.27 (8) |
| PX | after | 15 -2.42 (6) / 60 -2.41 (3) |
| PX | vol | 0.0 -2.44 (0) / 2.0 -2.40 (9) |
| PX | stop | pb -2.49 (3) / pct10 -2.35 (6) |
| PX | exit | measured -2.59 (0) / r2 -2.41 (0) / trail10 -2.45 (0) / ema9 -2.85 (0) / close -2.22 (5) / d3 -2.04 (4) |
| PX | scope | liquid -2.67 (0) / mover_up -2.80 (0) / gapup -2.26 (6) / runner -2.23 (3) |
| PX | band | 1-3 -2.57 (0) / 3-8 -2.43 (0) / 8-20 -2.18 (9) |
| CK | pattern | hammer -2.83 (0) / bull_engulf -2.78 (5) / morning_star -2.75 (1) / piercing -2.73 (0) / three_white -2.70 (2) / harami -2.82 (0) / tweezer -2.82 (0) / marubozu -2.82 (1) / dragonfly -2.81 (0) |
| CK | tf | 1 -2.83 (2) / 5 -2.73 (4) / 15 -2.80 (3) |
| CK | context | drop -2.58 (3) / lod -2.82 (0) / vwap -2.82 (6) / level -2.82 (0) / trend -2.79 (0) |
| CK | vol | 0.0 -2.85 (7) / 2.0 -2.76 (2) |
| CK | stop | pb -2.80 (1) / pct10 -2.78 (8) |
| CK | exit | r1 -2.81 (0) / r2 -2.78 (0) / trail10 -2.76 (2) / t30 -2.84 (0) / close -2.72 (7) |
| CK | scope | liquid -2.88 (0) / mover_up -2.84 (0) / mover_dn -2.81 (0) / gapup -2.45 (9) |
| CK | band | 1-3 -2.74 (6) / 3-8 -2.79 (1) / 8-20 -2.82 (2) |
| WO | drop | 0.1 -2.28 (3) / 0.2 -2.13 (0) / 0.3 -2.11 (6) |
| WO | reds | 4 -2.17 (3) / 7 -2.17 (6) |
| WO | climax | 3.0 -2.14 (7) / 6.0 -2.20 (2) |
| WO | confirm | hh -2.15 (8) / c3 -2.19 (1) |
| WO | stop | lod -2.14 (3) / pct10 -2.20 (6) |
| WO | exit | r2 -2.13 (3) / t30 -2.40 (0) / tovwap -2.14 (0) / trail10 -2.21 (1) / close -2.04 (2) / next_open -2.05 (3) |
| WO | scope | liquid -2.31 (3) / mover_up -2.16 (3) / mover_dn -2.13 (2) / gapup -2.15 (0) / runner -2.12 (1) / gapdown -2.17 (0) |
| WO | band | 1-3 -2.21 (3) / 3-8 -2.15 (3) / 8-20 -2.15 (3) |
| HG | adx | 25 -2.72 (1) / 30 -2.62 (8) |
| HG | tf | 1 -2.76 (5) / 5 -2.57 (4) |
| HG | touch | ema20 -2.76 (2) / ema9 -2.75 (0) / vwap -2.52 (7) |
| HG | stop | pb -2.81 (0) / pct10 -2.52 (9) |
| HG | exit | r2 -2.81 (0) / trail10 -2.76 (0) / crossback -2.87 (0) / close -2.53 (2) / d3 -2.24 (7) |
| HG | scope | liquid -3.22 (0) / mover_up -2.94 (0) / gapup -2.30 (7) / runner -2.44 (2) |
| HG | band | 1-3 -2.70 (0) / 3-8 -2.68 (0) / 8-20 -2.64 (9) |
| TS | ctx | up -1.97 (6) / high -2.05 (0) / lead -1.95 (3) |
| TS | dip | 0.03 -2.10 (7) / 0.06 -1.99 (2) / 0.1 -1.91 (0) |
| TS | trig | vwapre -1.93 (1) / green5 -2.09 (0) / rsi2 -2.08 (0) / pdc -1.86 (8) |
| TS | stop | lod -2.05 (8) / pct10 -1.93 (1) |
| TS | exit | r2 -2.29 (0) / close -2.17 (0) / next_open -2.07 (0) / d3 -1.89 (0) / d5 -1.65 (4) / g5 -1.73 (5) |
| TS | scope | liquid -2.02 (0) / mover_dn -1.95 (9) / mover_up -1.99 (0) |
| TS | band | 1-3 -2.05 (2) / 3-8 -1.95 (5) / 8-20 -1.94 (2) |

## 6. Latest pick of each family

- DL 2026: DL_DAILY|823 = {'level': 'h20', 'setup': 'break_up', 'vol': 2.0, 'window': 'open', 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '3-8'}
- SR 2026: SR_LONG|18851 = {'level': 'orh15', 'setup': 'break_up', 'vol': 2.0, 'window': 'midlate', 'stop': 'pct10', 'exit': 'd3', 'scope': 'day2', 'band': '8-20'}
- LV 2026: LV_VWAP|2303 = {'setup': 'break_hi', 'after': 60, 'vol': 2.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'day2', 'band': '8-20'}
- LE 2026: LE_EMA|2039 = {'pair': '50/200', 'tf': 15, 'setup': 'cross', 'side': 'long', 'stop': 'pct10', 'exit': 'd3', 'scope': 'day2', 'band': '8-20'}
- LO 2026: LO_OSC|3163 = {'ind': 'rsi14', 'tf': 1, 'lvl': 'x10', 'side': 'long', 'confirm': 'none', 'near': 'any', 'stop': 'pct10', 'exit': 'close', 'scope': 'gapdown', 'band': '3-8'}
- LM 2026: LM_MACD|599 = {'set': '12/26/9', 'tf': 5, 'signal': 'zero', 'side': 'long', 'stop': 'pct10', 'exit': 'd3', 'scope': 'day2', 'band': '8-20'}
- LS 2026: LS_SQUEEZE|839 = {'kc': 2.0, 'bars': 20, 'side': 'long', 'vol': 0.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'day2', 'band': '8-20'}
- LP 2026: LP_PATTERN|1418 = {'pattern': 'bull_flag', 'size': 'large', 'after': 60, 'stop': 'pct10', 'exit': 'close', 'scope': 'mover_up', 'band': '8-20'}
- LC 2026: LC_CANDLE|238 = {'candle': 'engulf', 'cside': 'long', 'at': 'pm', 'tf': 5, 'stop': 'pct10', 'exit': 'close', 'scope': 'day2', 'band': '3-8'}
- LX 2026: LX_CLIMAX|919 = {'mult': 10.0, 'candle': 'bigup', 'after': 60, 'stop': 'pct10', 'exit': 'r2', 'scope': 'gapdown', 'band': '3-8'}
- LR 2026: LR_ORB|4295 = {'k': 60, 'side': 'long', 'filter': 'gapdir', 'stop': 'pct10', 'exit': 'close', 'scope': 'day2', 'band': '8-20'}
- SP 2026: SP_INPLAY|1185 = {'sel': 'top10', 'k': 30, 'candle': 'green', 'gapdir': 'up', 'stop': 'range', 'exit': 'next_open', 'scope': 'inplay', 'band': '1-3'}
- NB 2026: NB_NOISE|2120 = {'k': 1.5, 'check': '30m', 'filter': 'rv2', 'stop': 'pct10', 'exit': 'close', 'scope': 'gapup', 'band': '8-20'}
- LH 2026: LH_LATE|3306 = {'up': 0.2, 'filter': 'hod', 'at': 330, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '1-3'}
- PH 2026: PH_POWER|824 = {'after': 240, 'day': 0.1, 'vol': 0.0, 'stop': 'pct5', 'exit': 'd3', 'scope': 'gapup', 'band': '8-20'}
- MP 2026: MP_MICRO|3419 = {'impulse': 'm10', 'retrace': 0.33, 'vol': 'dry', 'window': 'open', 'stop': 'pct5', 'exit': 'close', 'scope': 'day2', 'band': '8-20'}
- AB 2026: AB_ABCD|2117 = {'run': 0.2, 'retr': '24-50', 'entry': 'breakB', 'stop': 'pct10', 'exit': 'close', 'scope': 'gapup', 'band': '8-20'}
- HR 2026: HR_HALT|155 = {'dir': 'up', 'move': 0.08, 'entry': 'resume', 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '8-20'}
- MD 2026: MD_MORNDIP|1760 = {'drop': 0.2, 'window': 30, 'trig': 'vwapre', 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '8-20'}
- RG 2026: RG_RED2GREEN|3020 = {'gap': -0.05, 'after': 5, 'context': 'red2', 'vol': 2.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'mover_dn', 'band': '8-20'}
- GF 2026: GF_GAPFILL|1118 = {'gap': -0.15, 'trig': 'orh5', 'stop': 'lod', 'exit': 'd3', 'scope': 'liquid', 'band': '8-20'}
- D2 2026: D2_GO|789 = {'day1': 0.2, 'loc': 'top20', 'trig': 'orh15', 'stop': 'lod', 'exit': 'next_open', 'scope': 'mover_up', 'band': '1-3'}
- IX 2026: IX_IND|14960 = {'ind': 'kelt', 'tf': 5, 'filter': 'vwap', 'stop': 'pct10', 'exit': 'close', 'scope': 'gapup', 'band': '8-20'}
- PX 2026: PX_PATTERN|6896 = {'pattern': 'htf', 'size': 'large', 'after': 60, 'vol': 2.0, 'stop': 'pct10', 'exit': 'close', 'scope': 'gapup', 'band': '8-20'}
- CK 2026: CK_CANDLE|3839 = {'pattern': 'bull_engulf', 'tf': 1, 'context': 'drop', 'vol': 2.0, 'stop': 'pct10', 'exit': 'close', 'scope': 'gapup', 'band': '8-20'}
- WO 2026: WO_WASH|3966 = {'drop': 0.3, 'reds': 4, 'climax': 6.0, 'confirm': 'hh', 'stop': 'lod', 'exit': 'close', 'scope': 'mover_dn', 'band': '1-3'}
- HG 2026: HG_GRAIL|1436 = {'adx': 30, 'tf': 5, 'touch': 'vwap', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '8-20'}
- TS 2026: TS_TREND|373 = {'ctx': 'up', 'dip': 0.03, 'trig': 'pdc', 'stop': 'lod', 'exit': 'g5', 'scope': 'mover_dn', 'band': '3-8'}

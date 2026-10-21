# v25 results: short-only small caps on one-minute bars (213,000 configurations)

Pre-registered in [V25_PREREGISTRATION.md](V25_PREREGISTRATION.md).

| run | GitHub run | what happened |
|---|---|---|
| **v25** | **39597073559** (2026-10-21; canary 14:13 UTC, report 17:03 UTC) | **this report**; it waited for v24's first attempt, then ran; shards 190 and 250 took 2 h 17 min and 2 h 23 min (the rest 21-113 min) |

213,000 of 213,000 configurations, no errors, 500 placebos for each selected configuration, R4 costs.

## Summary

- **The pre-registered criterion is not met.** `COMBO25`: walk-forward monthly Sortino **2.33** (3.76 in 2018-2020,
  **1.67** in 2021-2026), 10.3% a year, drawdown -10.9%, +136% in total, PBO 0%, 2023-07+ **0.72**, deflated Sharpe
  0.00 over 213,000 trials. Weak lately: +2.8% in 2025 (MP alone qualified) and +5.8% in 2026 to date.
- **Four families pass the gate**, all of them v24's long rules run on the mirror image (reciprocal prices):
  PS (mirrored high tight flag) 3.30, AS (mirrored ABCD) 3.08, IS (mirrored indicators) 2.51, MP (morning pop, the
  mirror of the morning dip) 1.40. GU (mirrored gap fill) 3.33 and HD (mirrored Holy Grail) 1.76 score well but fail
  the placebo test in most years (3/9 and 1/9).
- **The same bet again: short a gap-up or a runner, hold it to the third close, 10% stop**, $3-8. The passing
  families' picks all use the gapup or runner scope and, except MP, the d3 exit. The new universes (liquid, movers) add
  nothing: never picked by a passing family.
- **v23's short rules do not carry to the scopes v23 did not have.** XV, XE, XO, XM, XQ, XP, XC, XX and XR (v23's own
  short rules on movers, gap-downs and day-2 names) all fail (-0.64 to -1.69); in v23 the same rules passed on gap-ups
  and runners. The daily-level shorts (DD) and support-resistance shorts (SR) fail too.
- **Fragile to costs and squeezes.** At the high costs only AS (0.47) and PS (0.55) stay above zero; the passing
  families' worst single trades lose 148-194% of the position (overnight squeezes through the stop), XQ's worst
  -1,142%.
- **Different from the existing books** (not pre-registered, measured after the report): daily correlation of
  COMBO25 with COMBO19 0.35, with DS1 0.14, with RU 0.07, with COMBO23 0.59; monthly with RU -0.15.
- **No look-ahead signs**: every family falls from low to middle to high costs; GU's gross Sortino sits at the cap of
  20 but falls to 3.33 at the middle and -0.45 at the high costs; the placebo gate rejects GU and HD.

## Report

Configurations evaluated 213000 of 213000; errors 0. R4 costs (middle) unless stated; 500 placebos for each selected configuration; a configuration can be picked only with at least 50 trades and a trade in 40% of the months before. Target: COMBO25 monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | years placebo-ok | gate | PBO | SPA p (best t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DD | -0.66 | 1.32 | -1.20 | 0.4% | -15.4% | -0.48 | -1.29 | -0.64 | 0.51 | 8/9 | fail | 0% | 0.637 (2.4) |
| SR | -1.15 | -0.37 | -1.39 | -3.2% | -29.4% | -0.98 | -1.57 | -1.15 | -0.42 | 7/9 | fail | 0% | 1.000 (0.3) |
| XV | -1.16 | 0.71 | -1.51 | -8.9% | -62.0% | -1.04 | -1.52 | -1.15 | -0.50 | 4/9 | fail | 0% | 1.000 (-0.7) |
| XE | -1.37 | 2.65 | -2.00 | -6.4% | -56.9% | -1.15 | -1.85 | -1.37 | -0.05 | 5/9 | fail | 0% | 1.000 (-0.4) |
| XO | -1.06 | 0.58 | -1.48 | -1.9% | -25.8% | -0.75 | -1.54 | -1.04 | 0.02 | 7/9 | fail | 0% | 1.000 (-0.4) |
| XM | -1.20 | 1.30 | -1.65 | -6.1% | -52.4% | -0.96 | -1.68 | -1.20 | 0.05 | 5/9 | fail | 0% | 1.000 (-0.2) |
| XQ | -0.64 | 1.31 | -1.01 | -5.9% | -55.2% | -0.51 | -1.05 | -0.63 | -0.04 | 4/9 | fail | 0% | 1.000 (-0.7) |
| XP | -1.09 | -0.44 | -1.32 | -0.8% | -12.6% | -0.91 | -1.54 | -1.09 | -0.19 | 4/9 | fail | 0% | 0.001 (3.9) |
| XC | -1.28 | 1.38 | -1.89 | -1.9% | -27.0% | -1.03 | -1.67 | -1.25 | -0.42 | 4/9 | fail | 0% | 1.000 (-1.1) |
| XX | -1.69 | -1.07 | -1.94 | -1.6% | -15.3% | -1.38 | -2.11 | -1.68 | -0.72 | 3/9 | fail | 0% | 1.000 (-2.0) |
| XR | -1.18 | 0.23 | -1.65 | -1.6% | -22.2% | -0.84 | -1.78 | -1.19 | 0.36 | 5/9 | fail | 0% | 0.989 (0.1) |
| SB | -0.40 | -0.67 | -0.34 | 1.1% | -8.9% | 0.49 | -1.54 | -0.29 | 4.71 | 0/9 | fail | 0% | 1.000 (-1.0) |
| NL | -0.99 | -0.46 | -1.17 | -2.5% | -23.0% | -0.65 | -1.49 | -0.95 | 0.40 | 9/9 | fail | 0% | 1.000 (-0.2) |
| LL | -0.78 | -1.01 | -0.68 | -1.6% | -20.7% | -0.61 | -1.45 | -0.75 | 0.82 | 2/9 | fail | 0% | 1.000 (-1.4) |
| PL | -1.59 | -1.74 | -1.57 | -4.7% | -37.5% | -1.48 | -1.84 | -1.59 | -1.10 | 4/9 | fail | 1% | 1.000 (-1.7) |
| MB | 0.19 | 0.39 | 0.08 | 3.4% | -20.4% | 0.92 | -0.79 | 0.25 | 4.81 | 6/9 | fail | 0% | 0.785 (1.1) |
| AS | 3.08 | 4.65 | 2.64 | 20.9% | -15.2% | 3.89 | 0.47 | 3.19 | 10.10 | 9/9 | pass | 0% | 0.000 (6.8) |
| HS | 0.53 | 0.50 | 0.55 | 4.3% | -7.7% | 0.94 | -0.15 | 0.56 | 2.89 | 9/9 | fail | 0% | 0.117 (3.0) |
| MP | 1.40 | 3.63 | 0.76 | 11.7% | -17.4% | 2.38 | -0.27 | 1.67 | 6.72 | 8/9 | pass | 0% | 0.000 (5.0) |
| GR | -0.71 | -0.92 | -0.57 | 0.3% | -13.0% | -0.50 | -1.34 | -0.70 | 0.52 | 7/9 | fail | 0% | 0.358 (1.6) |
| GU | 3.33 | 4.71 | 2.74 | 20.5% | -18.4% | 4.82 | -0.45 | 3.52 | 20.00 | 3/9 | fail | 0% | 0.000 (6.9) |
| D2 | -0.45 | 2.87 | -1.01 | 0.6% | -23.8% | -0.23 | -1.03 | -0.42 | 1.00 | 7/9 | fail | 2% | 0.894 (0.9) |
| IS | 2.51 | 7.01 | 1.57 | 20.4% | -20.6% | 3.94 | -1.04 | 2.71 | 17.12 | 8/9 | pass | 0% | 0.000 (6.1) |
| PS | 3.30 | 4.11 | 2.78 | 20.2% | -11.2% | 4.06 | 0.55 | 3.41 | 9.37 | 8/9 | pass | 0% | 0.000 (5.1) |
| CS | 0.19 | 0.23 | 0.16 | 3.5% | -17.9% | 1.05 | -1.00 | 0.29 | 4.25 | 6/9 | fail | 0% | 0.213 (2.2) |
| BT | -0.60 | 0.59 | -0.92 | -0.2% | -18.7% | -0.01 | -1.50 | -0.51 | 2.31 | 9/9 | fail | 0% | 1.000 (-0.2) |
| HD | 1.76 | 3.47 | 1.16 | 17.0% | -21.3% | 2.87 | -1.16 | 1.91 | 13.82 | 1/9 | fail | 0% | 0.000 (5.3) |
| TD | -0.70 | -1.04 | -0.45 | -2.0% | -34.6% | -0.43 | -1.68 | -0.66 | 1.47 | 9/9 | fail | 0% | 1.000 (-0.7) |

## 2. COMBO25 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO25 | 2.33 | 3.76 | 1.67 | 10.3% | -10.9% | +136% | 0.72 | 0.00 | 0% | not met |

Members by year: 2018: AS, CS, D2, GR, XE; 2019: AS, CS, HD, IS, MP, PS; 2020: AS, CS, IS, MP, PS; 2021: AS, D2, IS, MP, PS; 2022: AS, IS, MP, PS; 2023: AS, GU, IS, MP, PS; 2024: AS, GU, IS, MP; 2025: MP; 2026: AS, GU

COMBO25 by year: 2018 +4.4%, 2019 +12.6%, 2020 +22.1%, 2021 +9.9%, 2022 +10.9%, 2023 +6.7%, 2024 +16.2%, 2025 +2.8%, 2026 +5.8%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| DD | -1.66 | -3.4% | -15.1% |
| SR | -1.64 | -8.1% | -26.4% |
| XV | -1.47 | -16.0% | -45.0% |
| XE | -2.26 | -16.3% | -48.1% |
| XO | -1.60 | -3.8% | -14.7% |
| XM | -1.88 | -15.2% | -46.8% |
| XQ | -1.12 | -17.1% | -48.5% |
| XP | -1.66 | -3.0% | -12.6% |
| XC | -2.13 | -5.2% | -16.2% |
| XX | -2.03 | -2.0% | -7.1% |
| XR | -2.12 | -2.9% | -9.7% |
| SB | -0.49 | 2.4% | -6.3% |
| NL | -1.31 | -5.4% | -23.0% |
| LL | -0.96 | -2.7% | -20.7% |
| PL | -1.69 | -6.3% | -22.8% |
| MB | -0.15 | 3.5% | -12.6% |
| AS | 2.84 | 28.9% | -15.2% |
| HS | 0.39 | 6.1% | -7.7% |
| MP | 0.23 | 5.8% | -16.1% |
| GR | -1.10 | 0.3% | -6.6% |
| GU | 1.55 | 15.4% | -18.4% |
| D2 | -1.53 | -6.4% | -23.8% |
| IS | 1.52 | 19.2% | -20.6% |
| PS | 2.51 | 20.3% | -10.3% |
| CS | 0.89 | 9.9% | -12.9% |
| BT | -1.47 | -5.3% | -18.7% |
| HD | 1.00 | 14.0% | -21.3% |
| TD | 0.11 | 4.9% | -10.2% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| DD | 4.2 | -0.1% | 37% | -30% |
| SR | 6.1 | -1.5% | 35% | -263% |
| XV | 9.0 | -2.6% | 37% | -270% |
| XE | 11.6 | -1.4% | 35% | -139% |
| XO | 9.4 | -0.5% | 39% | -25% |
| XM | 12.5 | -1.3% | 39% | -139% |
| XQ | 7.1 | -2.7% | 35% | -1142% |
| XP | 3.4 | -0.3% | 36% | -68% |
| XC | 7.0 | -0.7% | 40% | -18% |
| XX | 5.9 | -0.7% | 39% | -14% |
| XR | 7.3 | -0.2% | 42% | -139% |
| SB | 15.0 | +1.0% | 48% | -49% |
| NL | 8.1 | -0.3% | 38% | -18% |
| LL | 7.4 | -0.4% | 50% | -183% |
| PL | 2.5 | -3.0% | 30% | -122% |
| MB | 10.3 | +0.4% | 35% | -16% |
| AS | 19.5 | +2.8% | 47% | -171% |
| HS | 7.0 | +1.9% | 42% | -43% |
| MP | 28.3 | +1.2% | 44% | -194% |
| GR | 5.2 | -0.0% | 42% | -77% |
| GU | 30.2 | +1.9% | 46% | -156% |
| D2 | 5.8 | +0.4% | 41% | -104% |
| IS | 41.9 | +1.3% | 44% | -148% |
| PS | 17.9 | +3.0% | 49% | -192% |
| CS | 29.5 | +0.4% | 46% | -21% |
| BT | 17.4 | +0.0% | 47% | -68% |
| HD | 42.5 | +1.2% | 44% | -325% |
| TD | 13.3 | -0.3% | 41% | -79% |

## 5. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| DD | level | h20 -2.51 (2) / h60 -2.46 (3) / h252 -2.46 (3) / l20 -2.58 (0) / l60 -2.56 (0) / l252 -2.54 (0) / sma20d -2.53 (0) / sma50d -2.47 (1) / sma200d -2.45 (0) |
| DD | setup | break_dn -2.45 (5) / fail_up -2.56 (2) / retest_dn -2.51 (2) |
| DD | vol | 0.0 -2.44 (9) / 2.0 -2.56 (0) |
| DD | window | open -2.53 (7) / midlate -2.53 (0) / all -2.46 (2) |
| DD | stop | lvl1 -2.49 (0) / pct10 -2.53 (9) |
| DD | exit | r2 -2.49 (0) / nextlevel -2.63 (0) / ema9 -2.75 (0) / close -2.36 (0) / d3 -2.02 (9) / trail10 -2.49 (0) |
| DD | scope | liquid -2.77 (0) / mover_up -2.52 (0) / mover_dn -2.50 (0) / gapup -2.31 (1) / runner -2.22 (8) / gapdown -2.61 (0) |
| DD | band | 1-3 -2.46 (1) / 3-8 -2.46 (8) / 8-20 -2.60 (0) |
| SR | level | pmh -2.49 (0) / pml -2.69 (1) / pdh -2.54 (0) / pdl -2.52 (0) / pdc -2.50 (2) / orh5 -2.54 (0) / orl5 -2.73 (2) / orh15 -2.55 (0) / orl15 -2.77 (0) / orh30 -2.56 (0) / orl30 -2.80 (1) / h5 -2.54 (0) / l5 -2.65 (0) / round1 -2.32 (3) / round050 -2.39 (0) / pivot -2.51 (0) / r1 -2.53 (0) / s1 -2.55 (0) |
| SR | setup | break_dn -2.53 (6) / fail_up -2.56 (2) / retest_dn -2.58 (1) |
| SR | vol | 0.0 -2.54 (8) / 2.0 -2.58 (1) |
| SR | window | open -2.49 (6) / midlate -2.63 (0) / all -2.56 (3) |
| SR | stop | lvl1 -2.61 (0) / pct10 -2.51 (9) |
| SR | exit | r2 -2.51 (0) / nextlevel -2.68 (0) / ema9 -2.82 (0) / close -2.40 (4) / d3 -2.08 (5) / be1r -2.49 (0) |
| SR | scope | mover_up -2.82 (0) / mover_dn -2.73 (0) / gapdown -2.40 (2) / day2 -2.29 (7) |
| SR | band | 1-3 -2.59 (0) / 3-8 -2.52 (3) / 8-20 -2.58 (6) |
| XV | setup | loss -2.80 (3) / reject -2.80 (0) / revert_hi -2.80 (0) / break_lo -2.60 (6) |
| XV | after | 15 -2.75 (9) / 60 -2.79 (0) |
| XV | vol | 0.0 -2.78 (9) / 2.0 -2.74 (0) |
| XV | stop | swing -2.85 (0) / pct10 -2.69 (9) |
| XV | exit | r2 -2.71 (0) / vwapx -2.86 (0) / ema9 -3.07 (0) / t30 -2.95 (0) / close -2.57 (3) / d3 -2.18 (6) |
| XV | scope | mover_up -3.18 (0) / mover_dn -3.13 (0) / gapdown -2.24 (4) / day2 -2.26 (5) |
| XV | band | 1-3 -2.86 (0) / 3-8 -2.71 (5) / 8-20 -2.73 (4) |
| XE | pair | 9/20 -2.60 (2) / 20/50 -2.58 (7) / 50/200 -2.49 (0) |
| XE | tf | 1 -2.62 (9) / 5 -2.58 (0) / 15 -2.47 (0) |
| XE | setup | cross -2.52 (0) / pullback -2.60 (9) |
| XE | side | short -2.56 (9) |
| XE | stop | swing -2.78 (0) / pct10 -2.41 (9) |
| XE | exit | crossback -2.62 (0) / r2 -2.68 (0) / t30 -2.94 (0) / close -2.52 (4) / d3 -2.15 (5) |
| XE | scope | mover_up -3.08 (0) / mover_dn -3.03 (0) / gapdown -1.96 (1) / day2 -1.99 (8) |
| XE | band | 1-3 -2.68 (0) / 3-8 -2.48 (2) / 8-20 -2.46 (7) |
| XO | ind | rsi2 -2.71 (7) / rsi7 -2.61 (1) / rsi14 -2.56 (1) / stoch14 -2.89 (0) |
| XO | tf | 1 -2.73 (7) / 5 -2.61 (2) |
| XO | lvl | x10 -2.68 (0) / x20 -2.65 (9) |
| XO | side | short -2.66 (9) |
| XO | confirm | none -2.63 (8) / turn -2.69 (1) |
| XO | near | any -2.51 (7) / level -2.75 (2) |
| XO | stop | swing -2.72 (0) / pct10 -2.59 (9) |
| XO | exit | mid -2.75 (0) / r2 -2.67 (0) / t30 -2.67 (0) / close -2.51 (9) |
| XO | scope | mover_up -2.94 (0) / mover_dn -2.91 (0) / gapdown -2.45 (0) / day2 -2.47 (9) |
| XO | band | 1-3 -2.68 (0) / 3-8 -2.63 (6) / 8-20 -2.68 (3) |
| XM | set | 12/26/9 -2.75 (8) / 5/35/5 -2.73 (1) |
| XM | tf | 1 -2.74 (9) / 5 -2.72 (0) |
| XM | signal | cross -2.67 (4) / zero -2.65 (5) / div -2.86 (0) |
| XM | side | short -2.73 (9) |
| XM | stop | swing -2.86 (0) / pct10 -2.64 (9) |
| XM | exit | crossback -2.99 (0) / r2 -2.81 (0) / t30 -3.02 (0) / close -2.64 (6) / d3 -2.33 (3) |
| XM | scope | mover_up -3.21 (0) / mover_dn -3.19 (0) / gapdown -2.08 (1) / day2 -2.11 (8) |
| XM | band | 1-3 -2.83 (0) / 3-8 -2.63 (3) / 8-20 -2.72 (6) |
| XQ | kc | 1.5 -2.52 (1) / 2.0 -2.64 (8) |
| XQ | bars | 10 -2.64 (5) / 20 -2.52 (4) |
| XQ | side | short -2.58 (9) |
| XQ | vol | 0.0 -2.59 (7) / 2.0 -2.56 (2) |
| XQ | stop | swing -2.65 (1) / pct10 -2.51 (8) |
| XQ | exit | r2 -2.45 (0) / ema9 -3.00 (0) / t30 -2.81 (0) / close -2.26 (2) / d3 -1.68 (7) |
| XQ | scope | mover_up -2.99 (0) / mover_dn -2.94 (0) / gapdown -2.10 (3) / day2 -2.04 (6) |
| XQ | band | 1-3 -2.78 (1) / 3-8 -2.45 (3) / 8-20 -2.51 (5) |
| XP | pattern | double_top -2.81 (1) / desc_triangle -2.83 (1) / bear_flag -1.75 (7) |
| XP | size | small -2.51 (2) / large -2.22 (7) |
| XP | after | 15 -2.39 (8) / 60 -2.35 (1) |
| XP | stop | pattern -2.40 (2) / pct10 -2.32 (7) |
| XP | exit | r2 -2.16 (0) / measured -2.39 (0) / ema9 -2.89 (0) / close -1.92 (1) / d3 -1.72 (8) |
| XP | scope | mover_up -3.10 (3) / mover_dn -2.88 (0) / gapdown -1.66 (1) / day2 -2.02 (5) |
| XP | band | 1-3 -2.49 (0) / 3-8 -2.26 (3) / 8-20 -2.21 (6) |
| XC | candle | engulf -2.73 (0) / pin -2.75 (9) / inside -2.73 (0) / doji -2.75 (0) |
| XC | cside | short -2.74 (9) |
| XC | at | pm -2.74 (0) / pd -2.73 (0) / vwap -2.82 (1) / hod -2.66 (8) |
| XC | tf | 1 -2.71 (3) / 5 -2.75 (6) |
| XC | stop | swing -2.77 (0) / pct10 -2.72 (9) |
| XC | exit | r1 -2.71 (0) / r2 -2.65 (0) / t15 -2.86 (0) / t30 -2.80 (0) / close -2.61 (9) |
| XC | scope | mover_up -3.13 (0) / mover_dn -3.01 (0) / gapdown -2.51 (0) / day2 -2.27 (9) |
| XC | band | 1-3 -2.74 (0) / 3-8 -2.68 (7) / 8-20 -2.77 (2) |
| XX | mult | 5.0 -2.83 (8) / 10.0 -2.70 (1) |
| XX | candle | upwick -2.72 (0) / bigdown -2.83 (9) |
| XX | after | 15 -2.77 (4) / 60 -2.77 (5) |
| XX | stop | swing -2.86 (1) / pct10 -2.73 (8) |
| XX | exit | r1 -2.76 (0) / r2 -2.67 (0) / t15 -2.99 (0) / t30 -2.88 (0) / close -2.56 (9) |
| XX | scope | mover_up -3.22 (0) / mover_dn -3.14 (0) / gapdown -2.53 (4) / day2 -2.35 (5) |
| XX | band | 1-3 -2.89 (0) / 3-8 -2.72 (2) / 8-20 -2.71 (7) |
| XR | k | 1 -2.51 (0) / 5 -2.45 (2) / 15 -2.52 (3) / 30 -2.61 (1) / 60 -2.62 (3) |
| XR | side | short -2.53 (9) |
| XR | filter | none -2.51 (0) / vwap -2.47 (2) / rvol -2.58 (2) / gapdir -2.58 (5) |
| XR | stop | range -2.66 (1) / half -2.72 (2) / pct10 -2.38 (6) |
| XR | exit | r1 -2.56 (0) / r2 -2.45 (0) / r3 -2.46 (1) / close -2.44 (5) / d3 -2.00 (3) / ema9 -2.83 (0) |
| XR | scope | mover_up -2.89 (0) / mover_dn -2.89 (0) / gapdown -1.41 (5) / day2 -2.15 (4) |
| XR | band | 1-3 -2.71 (0) / 3-8 -2.49 (1) / 8-20 -2.45 (8) |
| SB | sel | top5 -2.46 (8) / top10 -2.76 (1) / top20 -3.00 (0) / rv3 -3.20 (0) / rv6 -3.07 (0) |
| SB | k | 5 -2.99 (8) / 15 -2.99 (1) / 30 -2.98 (0) |
| SB | candle | green -2.91 (9) / any -3.04 (0) |
| SB | gapdir | any -3.13 (8) / up -2.78 (1) |
| SB | stop | atr10 -3.19 (0) / atr25 -2.98 (0) / range -2.59 (9) |
| SB | exit | close -2.90 (3) / r2 -3.08 (1) / r5 -3.01 (5) / trail10 -2.98 (0) / vwapx -3.00 (0) / next_open -2.91 (0) |
| SB | scope | inplay -2.98 (9) |
| SB | band | 1-3 -2.88 (2) / 3-8 -2.91 (7) / 8-20 -3.14 (0) |
| NL | k | 0.5 -2.81 (0) / 1.0 -2.70 (0) / 1.5 -2.57 (1) / 2.0 -2.49 (8) |
| NL | check | 1m -2.72 (3) / 30m -2.58 (6) |
| NL | filter | none -2.63 (0) / vwap -2.64 (2) / rv2 -2.61 (7) |
| NL | stop | pct5 -2.67 (6) / pct10 -2.60 (3) |
| NL | exit | bound -2.82 (0) / close -2.52 (7) / r2 -2.59 (1) / trail10 -2.69 (1) / next_open -2.59 (0) |
| NL | scope | liquid -3.04 (0) / mover_dn -2.62 (0) / gapdown -1.14 (9) / inplay -2.86 (0) |
| NL | band | 1-3 -2.54 (0) / 3-8 -2.61 (9) / 8-20 -2.88 (0) |
| LL | up | 0.02 -2.54 (0) / 0.05 -2.36 (0) / 0.1 -2.14 (0) / 0.2 -2.20 (9) |
| LL | filter | none -2.25 (1) / vwap -2.22 (3) / hod -2.49 (5) |
| LL | at | 270 -2.26 (7) / 330 -2.34 (2) / 360 -2.39 (0) |
| LL | stop | pct10 -2.19 (7) / pct20 -2.46 (2) |
| LL | exit | close -2.80 (0) / next_open -2.42 (0) / d2 -2.03 (2) / d3 -1.89 (7) |
| LL | scope | liquid -2.59 (0) / mover_dn -2.36 (0) / gapdown -1.65 (9) / mover_up -2.44 (0) |
| LL | band | 1-3 -2.24 (5) / 3-8 -2.30 (4) / 8-20 -2.46 (0) |
| PL | after | 240 -2.15 (5) / 270 -2.17 (2) / 300 -2.16 (2) |
| PL | day | 0.0 -2.23 (1) / 0.05 -2.20 (0) / 0.1 -2.07 (8) |
| PL | vol | 0.0 -2.15 (8) / 2.0 -2.17 (1) |
| PL | stop | swing -2.17 (2) / pct5 -2.10 (6) / pct10 -2.22 (1) |
| PL | exit | close -2.40 (1) / next_open -2.17 (0) / d2 -1.87 (7) / d3 -1.73 (1) / trail5 -2.64 (0) |
| PL | scope | liquid -2.52 (1) / mover_dn -2.42 (0) / gapdown -1.57 (7) / gapup -2.05 (1) |
| PL | band | 1-3 -2.08 (2) / 3-8 -2.17 (2) / 8-20 -2.27 (5) |
| MB | impulse | m3 -2.56 (0) / m6 -2.33 (3) / m10 -2.06 (6) |
| MB | retrace | 0.33 -2.26 (9) / 0.5 -2.33 (0) |
| MB | vol | any -2.32 (3) / dry -2.30 (6) |
| MB | window | open -2.27 (9) / all -2.35 (0) |
| MB | stop | pb -2.48 (0) / pct5 -2.07 (9) |
| MB | exit | r2 -2.22 (0) / r3 -2.09 (0) / trail5 -2.57 (0) / trail10 -2.22 (0) / ema9 -2.61 (0) / close -1.83 (9) |
| MB | scope | gapdown -1.67 (3) / mover_dn -2.58 (0) / liquid -2.29 (0) / gapup -2.55 (3) / runner -2.36 (3) |
| MB | band | 1-3 -2.44 (0) / 3-8 -2.20 (9) / 8-20 -2.20 (0) |
| AS | run | 0.05 -2.30 (0) / 0.1 -2.03 (0) / 0.2 -1.86 (9) |
| AS | retr | 38-62 -2.00 (3) / 24-50 -2.07 (6) |
| AS | entry | atC -2.06 (9) / breakB -2.00 (0) |
| AS | stop | pb -2.13 (0) / pct10 -1.96 (9) |
| AS | exit | measured -1.99 (0) / r2 -1.93 (0) / trail10 -2.25 (0) / close -1.70 (0) / ema9 -2.72 (0) / d3 -1.11 (9) |
| AS | scope | gapdown -1.56 (0) / mover_dn -2.36 (0) / liquid -2.43 (0) / gapup -1.99 (4) / runner -1.68 (5) |
| AS | band | 1-3 -2.30 (0) / 3-8 -1.91 (9) / 8-20 -1.82 (0) |
| HS | dir | up -1.99 (0) / down -1.97 (9) |
| HS | move | 0.08 -1.92 (2) / 0.15 -2.06 (7) |
| HS | entry | resume -2.00 (5) / hold -1.98 (1) / dip -1.97 (3) |
| HS | stop | pb -1.91 (2) / pct10 -1.84 (7) / pct20 -2.25 (0) |
| HS | exit | r2 -1.66 (3) / trail10 -2.34 (0) / trail20 -1.89 (1) / close -1.50 (5) / next_open -1.30 (0) / t15 -2.14 (0) / ema9 -2.39 (0) |
| HS | scope | gapup -1.76 (0) / runner -1.23 (9) / mover_up -2.03 (0) / mover_dn -2.02 (0) / liquid -2.63 (0) |
| HS | band | 1-3 -2.23 (1) / 3-8 -1.69 (7) / 8-20 -1.91 (1) |
| MP | drop | 0.1 -1.87 (9) / 0.2 -1.51 (0) / 0.3 -1.90 (0) |
| MP | window | 30 -1.74 (3) / 60 -1.72 (6) |
| MP | trig | green5 -1.69 (4) / vwapre -1.73 (5) / hl -1.77 (0) / rsi -1.75 (0) |
| MP | stop | lod -1.77 (0) / pct10 -1.69 (9) |
| MP | exit | r2 -1.48 (0) / openx -1.56 (0) / trail10 -2.08 (0) / close -1.25 (5) / next_open -1.11 (4) / ema9 -2.44 (0) |
| MP | scope | gapup -1.30 (2) / runner -0.95 (7) / mover_up -1.80 (0) / gapdown -1.93 (0) / mover_dn -2.03 (0) |
| MP | band | 1-3 -1.91 (0) / 3-8 -1.67 (8) / 8-20 -1.64 (1) |
| GR | gap | 0.0 -2.60 (0) / -0.02 -2.44 (0) / -0.05 -2.34 (9) |
| GR | after | 5 -2.47 (4) / 15 -2.47 (5) |
| GR | context | any -2.49 (9) / red2 -2.44 (0) / up20 -2.47 (0) |
| GR | vol | 0.0 -2.36 (6) / 2.0 -2.52 (3) |
| GR | stop | lod -2.53 (0) / pct10 -2.36 (9) |
| GR | exit | r2 -2.40 (0) / trail10 -2.59 (0) / ema9 -2.92 (0) / close -2.41 (0) / next_open -2.35 (0) / d3 -1.82 (9) |
| GR | scope | liquid -2.63 (0) / mover_up -2.53 (0) / gapup -2.18 (9) |
| GR | band | 1-3 -2.58 (1) / 3-8 -2.37 (2) / 8-20 -2.36 (6) |
| GU | gap | -0.04 -2.21 (0) / -0.08 -1.88 (1) / -0.15 -1.61 (8) |
| GU | trig | orh5 -1.96 (0) / orh15 -2.00 (5) / vwapre -1.90 (0) / hl -1.88 (0) / t30 -1.95 (4) |
| GU | stop | lod -2.01 (0) / pct10 -1.79 (9) |
| GU | exit | fill -2.12 (0) / half -2.16 (0) / close -1.95 (0) / next_open -1.69 (0) / d3 -1.24 (9) / r2 -2.00 (0) |
| GU | scope | liquid -2.01 (0) / mover_up -2.25 (0) / gapup -1.33 (9) |
| GU | band | 1-3 -2.10 (0) / 3-8 -1.48 (9) / 8-20 -1.90 (0) |
| D2 | day1 | 0.2 -2.03 (3) / 0.5 -2.13 (2) / 1.0 -2.28 (4) |
| D2 | loc | any -2.08 (9) / top20 -2.22 (0) |
| D2 | trig | pmh -2.19 (0) / orh5 -2.07 (9) / orh15 -2.19 (0) / vwap -2.05 (0) / open -2.29 (0) |
| D2 | stop | lod -2.20 (0) / pct10 -2.10 (9) |
| D2 | exit | r2 -2.04 (0) / trail10 -2.38 (0) / close -2.01 (1) / next_open -1.85 (4) / d3 -1.69 (4) / ema9 -2.72 (0) |
| D2 | scope | day2 -1.85 (6) / liquid -2.46 (0) / mover_up -2.14 (3) / mover_dn -2.20 (0) |
| D2 | band | 1-3 -2.38 (0) / 3-8 -2.03 (0) / 8-20 -2.03 (9) |
| IS | ind | supertrend -2.71 (0) / psar -2.85 (0) / heikin -2.90 (1) / ichimoku -2.82 (0) / cci -2.81 (2) / willr -2.88 (2) / mfi -2.79 (2) / obv -2.82 (0) / aroon -2.82 (0) / don20 -2.82 (0) / don55 -2.82 (0) / kelt -2.67 (0) / roc -2.90 (2) / trix -2.82 (0) / adx -2.82 (0) / stack -2.81 (0) |
| IS | tf | 1 -2.91 (9) / 5 -2.82 (0) / 15 -2.82 (0) |
| IS | filter | none -2.82 (0) / vwap -2.82 (9) / ema50 -2.82 (0) |
| IS | stop | swing -2.82 (0) / pct10 -2.82 (9) |
| IS | exit | opp -2.82 (0) / r2 -2.82 (0) / trail10 -2.82 (0) / ema9 -2.98 (0) / close -2.82 (0) / d3 -2.40 (9) |
| IS | scope | liquid -3.03 (0) / mover_up -3.05 (0) / gapup -2.60 (4) / runner -2.41 (5) |
| IS | band | 1-3 -2.82 (0) / 3-8 -2.82 (9) / 8-20 -2.82 (0) |
| PS | pattern | inv_hs -2.81 (0) / triple_bottom -2.91 (0) / cup_handle -2.59 (0) / rectangle -2.92 (0) / pennant -2.10 (0) / htf -2.01 (9) |
| PS | size | small -2.67 (4) / large -2.48 (5) |
| PS | after | 15 -2.59 (7) / 60 -2.59 (2) |
| PS | vol | 0.0 -2.59 (6) / 2.0 -2.59 (3) |
| PS | stop | pb -2.61 (0) / pct10 -2.56 (9) |
| PS | exit | measured -2.60 (0) / r2 -2.49 (0) / trail10 -2.61 (0) / ema9 -2.94 (0) / close -2.43 (0) / d3 -1.78 (9) |
| PS | scope | liquid -2.87 (0) / mover_up -3.01 (0) / gapup -2.48 (9) / runner -2.29 (0) |
| PS | band | 1-3 -2.69 (0) / 3-8 -2.52 (7) / 8-20 -2.48 (2) |
| CS | pattern | hammer -2.83 (1) / bull_engulf -2.82 (1) / morning_star -2.82 (0) / piercing -2.76 (6) / three_white -2.78 (0) / harami -2.82 (1) / tweezer -2.85 (0) / marubozu -2.83 (0) / dragonfly -2.82 (0) |
| CS | tf | 1 -2.84 (9) / 5 -2.80 (0) / 15 -2.82 (0) |
| CS | context | drop -2.55 (8) / lod -2.82 (0) / vwap -2.86 (0) / level -2.84 (0) / trend -2.83 (1) |
| CS | vol | 0.0 -2.87 (8) / 2.0 -2.81 (1) |
| CS | stop | pb -2.82 (0) / pct10 -2.82 (9) |
| CS | exit | r1 -2.82 (0) / r2 -2.81 (0) / trail10 -2.81 (0) / t30 -2.86 (0) / close -2.79 (9) |
| CS | scope | liquid -2.93 (0) / mover_up -2.89 (0) / mover_dn -2.82 (0) / gapup -2.52 (9) |
| CS | band | 1-3 -2.81 (0) / 3-8 -2.82 (9) / 8-20 -2.84 (0) |
| BT | drop | 0.1 -2.30 (3) / 0.2 -2.14 (5) / 0.3 -2.24 (1) |
| BT | reds | 4 -2.15 (8) / 7 -2.30 (1) |
| BT | climax | 3.0 -2.17 (4) / 6.0 -2.29 (5) |
| BT | confirm | hh -2.23 (0) / c3 -2.23 (9) |
| BT | stop | lod -2.26 (0) / pct10 -2.19 (9) |
| BT | exit | r2 -2.11 (1) / t30 -2.37 (0) / tovwap -2.39 (0) / trail10 -2.34 (0) / close -2.03 (7) / next_open -1.92 (1) |
| BT | scope | liquid -2.47 (0) / mover_up -2.25 (0) / mover_dn -2.26 (0) / gapup -2.14 (0) / runner -1.93 (9) / gapdown -2.32 (0) |
| BT | band | 1-3 -2.24 (2) / 3-8 -2.16 (7) / 8-20 -2.28 (0) |
| HD | adx | 25 -2.81 (8) / 30 -2.75 (1) |
| HD | tf | 1 -2.87 (9) / 5 -2.72 (0) |
| HD | touch | ema20 -2.86 (2) / ema9 -2.87 (7) / vwap -2.63 (0) |
| HD | stop | pb -2.89 (0) / pct10 -2.67 (9) |
| HD | exit | r2 -2.83 (0) / trail10 -2.83 (0) / crossback -2.94 (0) / close -2.72 (1) / d3 -2.26 (8) |
| HD | scope | liquid -3.28 (0) / mover_up -3.05 (0) / gapup -2.42 (8) / runner -2.28 (1) |
| HD | band | 1-3 -2.78 (0) / 3-8 -2.79 (9) / 8-20 -2.76 (0) |
| TD | ctx | up -2.22 (3) / high -2.28 (1) / lead -2.08 (5) |
| TD | dip | 0.03 -2.41 (0) / 0.06 -2.22 (0) / 0.1 -2.01 (9) |
| TD | trig | vwapre -2.10 (9) / green5 -2.23 (0) / rsi2 -2.26 (0) / pdc -2.22 (0) |
| TD | stop | lod -2.27 (0) / pct10 -2.15 (9) |
| TD | exit | r2 -2.42 (0) / close -2.35 (0) / next_open -2.35 (0) / d3 -2.02 (5) / d5 -2.01 (0) / g5 -2.04 (4) |
| TD | scope | liquid -2.35 (0) / mover_dn -2.11 (0) / mover_up -2.15 (9) |
| TD | band | 1-3 -2.21 (0) / 3-8 -2.17 (9) / 8-20 -2.24 (0) |

## 6. Latest pick of each family

- DD 2026: DD_DAILY|29137 = {'level': 'sma50d', 'setup': 'fail_up', 'vol': 0.0, 'window': 'all', 'stop': 'pct10', 'exit': 'd3', 'scope': 'runner', 'band': '3-8'}
- SR 2026: SR_SHORT|3583 = {'level': 'pml', 'setup': 'fail_up', 'vol': 0.0, 'window': 'open', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapdown', 'band': '3-8'}
- XV 2026: XV_VWAP|1867 = {'setup': 'break_lo', 'after': 15, 'vol': 0.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapdown', 'band': '3-8'}
- XE 2026: XE_EMA|239 = {'pair': '9/20', 'tf': 1, 'setup': 'pullback', 'side': 'short', 'stop': 'pct10', 'exit': 'd3', 'scope': 'day2', 'band': '8-20'}
- XO 2026: XO_OSC|2782 = {'ind': 'rsi7', 'tf': 5, 'lvl': 'x20', 'side': 'short', 'confirm': 'none', 'near': 'any', 'stop': 'pct10', 'exit': 'close', 'scope': 'day2', 'band': '3-8'}
- XM 2026: XM_MACD|107 = {'set': '12/26/9', 'tf': 1, 'signal': 'cross', 'side': 'short', 'stop': 'pct10', 'exit': 'close', 'scope': 'day2', 'band': '8-20'}
- XQ 2026: XQ_SQUEEZE|234 = {'kc': 1.5, 'bars': 10, 'side': 'short', 'vol': 2.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapdown', 'band': '1-3'}
- XP 2026: XP_PATTERN|1256 = {'pattern': 'bear_flag', 'size': 'large', 'after': 15, 'stop': 'pattern', 'exit': 'd3', 'scope': 'gapdown', 'band': '8-20'}
- XC 2026: XC_CANDLE|1919 = {'candle': 'pin', 'cside': 'short', 'at': 'hod', 'tf': 5, 'stop': 'pct10', 'exit': 'close', 'scope': 'day2', 'band': '8-20'}
- XX 2026: XX_CLIMAX|359 = {'mult': 5.0, 'candle': 'bigdown', 'after': 15, 'stop': 'pct10', 'exit': 'close', 'scope': 'day2', 'band': '8-20'}
- XR 2026: XR_ORB|2492 = {'k': 15, 'side': 'short', 'filter': 'gapdir', 'stop': 'half', 'exit': 'close', 'scope': 'gapdown', 'band': '8-20'}
- SB 2026: SB_INPLAY|37 = {'sel': 'top5', 'k': 5, 'candle': 'green', 'gapdir': 'any', 'stop': 'range', 'exit': 'close', 'scope': 'inplay', 'band': '3-8'}
- NL 2026: NL_NOISE|2419 = {'k': 2.0, 'check': '1m', 'filter': 'rv2', 'stop': 'pct5', 'exit': 'close', 'scope': 'gapdown', 'band': '3-8'}
- LL 2026: LL_LATE|2922 = {'up': 0.2, 'filter': 'vwap', 'at': 270, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapdown', 'band': '1-3'}
- PL 2026: PL_POWER|2922 = {'after': 300, 'day': 0.1, 'vol': 0.0, 'stop': 'swing', 'exit': 'd3', 'scope': 'gapdown', 'band': '1-3'}
- MB 2026: MB_MICRO|3046 = {'impulse': 'm10', 'retrace': 0.33, 'vol': 'any', 'window': 'open', 'stop': 'pct5', 'exit': 'close', 'scope': 'gapdown', 'band': '3-8'}
- AS 2026: AS_ABCD|1975 = {'run': 0.2, 'retr': '24-50', 'entry': 'atC', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- HS 2026: HS_HALT|2989 = {'dir': 'down', 'move': 0.15, 'entry': 'resume', 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '3-8'}
- MP 2026: MP_MORNPOP|334 = {'drop': 0.1, 'window': 30, 'trig': 'vwapre', 'stop': 'pct10', 'exit': 'next_open', 'scope': 'runner', 'band': '3-8'}
- GR 2026: GR_GREEN2RED|2699 = {'gap': -0.05, 'after': 5, 'context': 'any', 'vol': 0.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '8-20'}
- GU 2026: GU_GAPFILL|1609 = {'gap': -0.15, 'trig': 't30', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- D2 2026: D2_FADE|272 = {'day1': 0.2, 'loc': 'any', 'trig': 'orh5', 'stop': 'pct10', 'exit': 'd3', 'scope': 'mover_up', 'band': '8-20'}
- IS 2026: IS_IND|15835 = {'ind': 'roc', 'tf': 1, 'filter': 'vwap', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- PS 2026: PS_PATTERN|6475 = {'pattern': 'htf', 'size': 'large', 'after': 15, 'vol': 0.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- CS 2026: CS_CANDLE|10918 = {'pattern': 'piercing', 'tf': 1, 'context': 'drop', 'vol': 0.0, 'stop': 'pct10', 'exit': 'close', 'scope': 'gapup', 'band': '3-8'}
- BT 2026: BT_BLOWOFF|3883 = {'drop': 0.3, 'reds': 4, 'climax': 3.0, 'confirm': 'c3', 'stop': 'pct10', 'exit': 'next_open', 'scope': 'runner', 'band': '3-8'}
- HD 2026: HD_GRAIL|235 = {'adx': 25, 'tf': 1, 'touch': 'ema9', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- TD 2026: TD_TREND|3562 = {'ctx': 'lead', 'dip': 0.1, 'trig': 'vwapre', 'stop': 'pct10', 'exit': 'g5', 'scope': 'mover_up', 'band': '3-8'}

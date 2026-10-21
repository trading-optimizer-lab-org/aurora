# v22 results: technical analysis on small caps (88,254 configurations)

Pre-registered in [V22_PREREGISTRATION.md](V22_PREREGISTRATION.md). Three runs, the first two void for the intraday
families:

| run | GitHub run | what changed | intraday result |
|---|---|---|---|
| v22 | 39556504856 (report 39562299158) | first run | void: runner longs entered before the 40% rise that defines the scope |
| v22b | 39563542063 | runners traded once risen; close signals filled at the next open | IF_FLAG and COMBO22 void: the flag search skipped the same rule |
| **v22c** | **39570586899** (2026-10-21 08:36-09:24 UTC) | flags on live bars only; a runner is risen only by the bars before the entry bar | **this report** |

88,254 of 88,254 configurations, no errors, 500 placebos for each selected configuration, R4 costs (v21's calibration
on 27,782 measured quote legs).

## Summary

- **The pre-registered criterion is met, without margin.** `COMBO22`: walk-forward monthly Sortino **4.93** (12.78 in
  2018-2020, **4.03** in 2021-2026), 15.3% a year, drawdown -5.9%, PBO 0%, 2023-07+ **4.15**. Every year positive
  (+3.5% to +33.4%). Deflated Sharpe 0.00 over 88,254 trials.
- **Daily technical analysis mostly fails.** Of 15 daily families only two pass: RS (RSI(14) at 90, short in an
  uptrend above SMA50, out on a close below SMA5) 3.35 and GP (a gap-up of 20-40% that closes below its open, short
  at the close for one to five sessions) 2.80. Moving-average crosses, Donchian breakouts, Bollinger bands, MACD, stochastics, ADX, candles,
  bases, divergences, IBS and climax volume are all negative after costs; their median configuration has a Sortino of
  about -2.
- **What works intraday is the known edge, timed by an indicator.** Every intraday pick is a **short** in a gap-up or
  a runner, nearly always held to the **third close** with a 10-20% stop: IV (a close 1-1.5 deviations below VWAP after the rise) 5.99,
  IF (a bear flag) 3.22, IR (one-minute RSI(7) at 80) 1.52, IE (EMA 5/13 cross down) 1.55, IM 0.81. This is the same
  small-cap fade found in v19-v21 (XS1, RU, GX); the indicator chooses the entry minute, not a new source of return.
- **Fragile to costs.** At the high costs (half-spreads x2, borrow x3) IV falls to 0.44, IF 0.74, RS 0.93 and GP -0.05;
  at the auction costs (opening and closing legs at the session spread) they hold (IV 6.29, RS 3.75, GP 3.05).
- **Lower than v19-v20.** COMBO22 4.93 compares with COMBO19 7.86 (per-trade quotes) and COMBO20 7.70; technical
  analysis did not add an independent stream.
- **Caveats.** The 2023-07+ window was seen before by the researcher (v14-v21); the borrow model is a today snapshot of
  IBKR; shorts held overnight in small caps carry squeeze risk (worst IV trade -146% of the position).

## v22b against v22c (intraday)

| family | v22b | v22c | note |
|---|---|---|---|
| IV | 5.97 | 5.99 | not affected by the flag bug; the stricter runner rule changes little |
| IF | 20.00 | 3.22 | the look-ahead was here |
| IR | 1.67 | 1.52 | |
| IE | 1.55 | 1.55 | |
| IM | 0.81 | 0.81 | |
| COMBO22 | 4.27 (void) | 4.93 | |

## Full report


Configurations evaluated 88254 of 88254; errors 0. R4 costs (middle) unless stated; 500 placebos for each selected configuration; a configuration can be picked only with at least 50 trades and a trade in 40% of the months before. Target: COMBO22 monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | years placebo-ok | gate | PBO | SPA p (best t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RS | 3.35 | 11.52 | 2.43 | 12.6% | -17.6% | 3.85 | 0.93 | 3.75 | 5.95 | 9/9 | pass | 0% | 0.003 (4.2) |
| BB | -0.62 | -1.04 | -0.35 | -6.9% | -62.5% | -0.50 | -0.85 | -0.62 | -0.30 | 4/9 | fail | 0% | 0.976 (0.7) |
| MA | -0.05 | 0.88 | -0.31 | -9.8% | -88.6% | 0.05 | -0.26 | -0.06 | 0.21 | 7/9 | fail | 0% | 0.962 (0.6) |
| DN | -0.65 | -0.52 | -0.70 | -18.3% | -87.1% | -0.57 | -0.80 | -0.63 | -0.40 | 2/9 | fail | 0% | 0.994 (0.4) |
| FB | -1.56 | -1.24 | -1.70 | -35.7% | -98.1% | -1.42 | -1.82 | -1.46 | -1.15 | 1/9 | fail | 0% | 1.000 (-1.0) |
| CS | -1.12 | -0.63 | -1.58 | -13.2% | -75.4% | -1.04 | -1.25 | -1.11 | -0.92 | 5/9 | fail | 0% | 1.000 (0.2) |
| MC | -0.74 | 0.02 | -0.99 | -20.1% | -93.7% | -0.56 | -1.04 | -0.71 | -0.01 | 5/9 | fail | 0% | 0.995 (0.0) |
| SO | -0.48 | -0.19 | -0.62 | -9.9% | -67.4% | -0.36 | -0.69 | -0.43 | -0.11 | 3/9 | fail | 0% | 0.942 (0.4) |
| AX | -1.24 | -0.56 | -1.59 | -29.4% | -95.9% | -1.08 | -1.53 | -1.25 | -0.79 | 0/9 | fail | 0% | 1.000 (-0.1) |
| VC | -0.24 | 0.33 | -0.57 | -0.7% | -35.2% | -0.10 | -0.51 | -0.25 | 0.15 | 9/9 | fail | 15% | 0.961 (1.3) |
| EX | -0.72 | -0.23 | -1.01 | -2.7% | -26.8% | -0.63 | -1.14 | -0.66 | -0.24 | 8/9 | fail | 0% | 0.669 (2.2) |
| IB | -1.56 | -1.44 | -1.60 | -9.9% | -61.6% | -1.26 | -2.03 | -1.42 | -0.35 | 9/9 | fail | 0% | 0.460 (0.6) |
| VO | -0.22 | -0.29 | -0.17 | 0.3% | -29.9% | -0.14 | -0.60 | -0.17 | 0.14 | 9/9 | fail | 0% | 0.004 (4.3) |
| DV | -1.03 | -0.28 | -1.43 | -24.6% | -93.9% | -0.92 | -1.25 | -1.02 | -0.69 | 1/9 | fail | 0% | 1.000 (-0.2) |
| GP | 2.80 | 2.83 | 3.04 | 17.4% | -16.7% | 3.43 | -0.05 | 3.05 | 6.82 | 9/9 | pass | 0% | 0.000 (5.2) |
| IE | 1.55 | 4.14 | 0.60 | 11.9% | -12.9% | 2.75 | -1.44 | 1.73 | 15.69 | 5/9 | fail | 0% | 0.007 (4.2) |
| IV | 5.99 | 18.95 | 4.71 | 23.9% | -10.4% | 7.87 | 0.44 | 6.29 | 20.00 | 9/9 | pass | 0% | 0.000 (7.7) |
| IR | 1.52 | 3.97 | 0.97 | 16.9% | -24.3% | 2.52 | -1.00 | 1.64 | 12.93 | 9/9 | pass | 0% | 0.002 (4.7) |
| IM | 0.81 | 2.47 | 0.43 | 7.4% | -19.0% | 1.69 | -1.59 | 0.96 | 10.55 | 7/9 | fail | 0% | 0.008 (3.6) |
| IF | 3.22 | 5.29 | 2.25 | 12.1% | -6.4% | 3.84 | 0.74 | 3.35 | 9.96 | 9/9 | pass | 0% | 0.001 (5.2) |

## 2. COMBO22 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO22 | 4.93 | 12.78 | 4.03 | 15.3% | -5.9% | +250% | 4.15 | 0.00 | 0% | met |

Members by year: 2018: GP, IF, IR, IV, VC, VO; 2019: GP, IE, IF, IM, IR, IV, RS, VO; 2020: IF, IV, RS; 2021: IE, IF, IV, RS, VO; 2022: EX, IF, IV; 2023: IF, IR, IV; 2024: IE, IF, IR, IV; 2025: GP, IV; 2026: GP, IV

COMBO22 by year: 2018 +8.6%, 2019 +3.5%, 2020 +33.4%, 2021 +5.8%, 2022 +4.0%, 2023 +30.8%, 2024 +4.0%, 2025 +31.6%, 2026 +18.6%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| RS | 4.80 | 18.9% | -8.7% |
| BB | -0.63 | -6.6% | -40.5% |
| MA | -0.94 | -24.4% | -66.6% |
| DN | -0.95 | -31.1% | -74.0% |
| FB | -1.97 | -34.1% | -76.8% |
| CS | -1.89 | -21.5% | -61.6% |
| MC | -1.59 | -40.2% | -81.8% |
| SO | -1.30 | -26.3% | -64.7% |
| AX | -1.59 | -38.6% | -82.5% |
| VC | -0.58 | -2.7% | -23.2% |
| EX | -1.03 | -1.8% | -13.4% |
| IB | -1.58 | -10.1% | -32.9% |
| VO | -0.22 | 3.0% | -16.0% |
| DV | -1.46 | -23.4% | -69.8% |
| GP | 5.28 | 41.1% | -16.7% |
| IE | 0.39 | 7.0% | -12.9% |
| IV | 4.28 | 25.3% | -10.4% |
| IR | 0.09 | 3.9% | -24.3% |
| IM | 0.37 | 7.0% | -19.0% |
| IF | 2.59 | 13.6% | -6.4% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| RS | 4.0 | +8.0% | 67% | -230% |
| BB | 6.9 | -2.1% | 41% | -97% |
| MA | 11.2 | -0.2% | 40% | -96% |
| DN | 8.0 | -1.2% | 37% | -101% |
| FB | 15.8 | -4.2% | 38% | -146% |
| CS | 5.7 | -3.6% | 55% | -89% |
| MC | 18.1 | -1.9% | 34% | -95% |
| SO | 7.7 | -1.3% | 49% | -98% |
| AX | 19.8 | -1.1% | 35% | -93% |
| VC | 4.9 | +0.4% | 35% | -75% |
| EX | 3.0 | -0.1% | 50% | -410% |
| IB | 13.0 | -1.5% | 44% | -85% |
| VO | 3.3 | +2.2% | 62% | -521% |
| DV | 13.7 | -2.6% | 40% | -95% |
| GP | 14.3 | +4.0% | 62% | -390% |
| IE | 48.3 | +1.0% | 50% | -195% |
| IV | 38.0 | +3.0% | 56% | -146% |
| IR | 47.2 | +0.9% | 41% | -132% |
| IM | 49.4 | +0.8% | 52% | -307% |
| IF | 12.6 | +3.8% | 56% | -169% |

## 5. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| RS | n | 2 -2.55 (0) / 3 -2.28 (0) / 5 -1.90 (0) / 14 -1.60 (9) |
| RS | lvl | 5 -1.96 (0) / 10 -2.09 (9) / 25 -2.41 (0) |
| RS | side | long -2.01 (0) / short -2.36 (9) |
| RS | trend | none -2.06 (0) / up200 -2.16 (7) / down200 -2.00 (0) / up50 -2.39 (2) |
| RS | entry | close -2.03 (0) / open -2.31 (9) |
| RS | exit | rsi50 -2.14 (0) / sma5 -2.19 (8) / t3 -2.43 (1) / t5 -2.15 (0) / t10 -1.79 (0) |
| RS | stop | none -1.85 (9) / 0.1 -2.44 (0) / 0.2 -2.28 (0) |
| RS | band | 1-3 -2.04 (0) / 3-8 -2.09 (9) / 8-20 -2.38 (0) |
| BB | n | 10 -2.62 (1) / 20 -2.16 (4) / 50 -2.16 (4) |
| BB | k | 2.0 -2.33 (1) / 2.5 -2.14 (5) / 3.0 -2.38 (3) |
| BB | mode | revert -2.04 (9) / break -2.36 (0) |
| BB | side | long -1.87 (9) / short -2.56 (0) |
| BB | trend | none -2.34 (2) / up200 -2.19 (7) |
| BB | entry | close -2.17 (9) / open -2.33 (0) |
| BB | exit | mid -2.40 (0) / opp -2.17 (9) / t5 -2.30 (0) / t10 -2.13 (0) / atr2 -2.33 (0) |
| BB | stop | none -1.98 (8) / 0.1 -2.45 (0) / 0.2 -2.34 (1) |
| BB | band | 1-3 -2.09 (2) / 3-8 -2.31 (2) / 8-20 -2.57 (5) |
| MA | pair | 5/20 -2.18 (0) / 10/50 -1.99 (0) / 20/100 -1.92 (3) / 50/200 -1.70 (6) / 10/20 -2.06 (0) / 20/50 -1.88 (0) |
| MA | type | sma -2.05 (2) / ema -1.98 (7) |
| MA | signal | cross -2.16 (2) / pullback -1.95 (7) |
| MA | side | long -1.28 (9) / short -2.42 (0) |
| MA | entry | close -2.00 (9) / open -2.03 (0) |
| MA | exit | crossback -1.79 (9) / closefast -2.28 (0) / atr3 -1.98 (0) / t20 -1.82 (0) |
| MA | stop | none -1.84 (9) / 0.1 -2.23 (0) / 0.2 -2.15 (0) |
| MA | band | 1-3 -1.97 (2) / 3-8 -1.99 (0) / 8-20 -2.09 (7) |
| DN | n | 10 -2.21 (0) / 20 -2.18 (1) / 55 -2.11 (0) / 120 -2.10 (3) / 252 -1.99 (5) |
| DN | vol | 0.0 -2.16 (4) / 1.5 -2.18 (3) / 3.0 -2.03 (2) |
| DN | loc | any -2.17 (4) / top25 -2.05 (5) |
| DN | side | long -1.57 (9) / short -2.40 (0) |
| DN | entry | close -2.05 (9) / open -2.16 (0) |
| DN | exit | low5 -2.10 (0) / low10 -2.00 (0) / low20 -2.00 (1) / atr2 -2.29 (0) / atr3 -2.16 (0) / t10 -2.20 (0) / t20 -2.05 (1) / t40 -1.95 (7) |
| DN | stop | none -1.94 (7) / 0.08 -2.31 (0) / 0.15 -2.16 (2) |
| DN | band | 1-3 -1.97 (7) / 3-8 -2.16 (0) / 8-20 -2.27 (2) |
| FB | n | 20 -2.33 (2) / 55 -2.30 (2) / 252 -2.10 (5) |
| FB | within | 1 -2.16 (9) / 3 -2.29 (0) |
| FB | vol | 0.0 -2.43 (2) / 2.0 -2.02 (7) |
| FB | side | short -2.50 (1) / long -1.95 (8) |
| FB | exit | t3 -2.54 (0) / t5 -2.35 (1) / t10 -2.11 (0) / target20 -1.96 (6) / reclaim -1.92 (2) |
| FB | stop | none -2.03 (8) / 0.1 -2.39 (0) / 0.2 -2.25 (1) |
| FB | band | 1-3 -2.03 (2) / 3-8 -2.26 (6) / 8-20 -2.56 (1) |
| CS | pattern | bull_engulf -1.62 (4) / bear_engulf -1.92 (0) / hammer -1.50 (3) / shooting_star -2.03 (0) / doji_low -1.49 (0) / doji_high -1.79 (1) / inside_up -1.77 (0) / inside_down -1.88 (0) / outside_up -1.71 (0) / outside_down -1.81 (0) / nr7_up -1.67 (1) / nr7_down -2.15 (0) / three_white -2.01 (0) / three_black -2.08 (0) |
| CS | context | any -2.86 (0) / move5 -1.62 (3) / move20 -1.57 (5) / move3 -1.71 (1) |
| CS | entry | close -1.76 (8) / open -1.89 (1) |
| CS | exit | t1 -2.05 (1) / t3 -1.77 (0) / t5 -1.76 (3) / t10 -1.69 (1) / target10 -1.79 (4) |
| CS | stop | extreme -1.89 (0) / 0.1 -1.98 (0) / none -1.43 (9) |
| CS | band | 1-3 -1.93 (1) / 3-8 -1.78 (2) / 8-20 -1.70 (6) |
| MC | set | 12/26/9 -2.26 (4) / 5/35/5 -2.27 (2) / 3/10/16 -2.29 (3) |
| MC | signal | sig -2.24 (6) / zero -2.26 (2) / hist -2.35 (1) / div -2.27 (0) |
| MC | side | long -1.66 (9) / short -2.57 (0) |
| MC | trend | none -2.30 (0) / up200 -2.28 (7) / down200 -2.26 (2) |
| MC | entry | close -2.23 (8) / open -2.31 (1) |
| MC | exit | opp -2.47 (0) / t5 -2.43 (0) / t10 -2.16 (0) / t20 -1.83 (1) / atr3 -1.85 (8) |
| MC | stop | none -2.12 (4) / 0.1 -2.48 (0) / 0.2 -2.35 (5) |
| MC | band | 1-3 -2.20 (3) / 3-8 -2.28 (3) / 8-20 -2.40 (3) |
| SO | set | 14/3 -2.34 (2) / 5/3 -2.37 (7) |
| SO | lvl | 20 -2.47 (0) / 10 -2.28 (9) |
| SO | signal | cross -2.20 (8) / leave -2.59 (1) |
| SO | side | long -1.92 (9) / short -2.74 (0) |
| SO | trend | none -2.49 (1) / up200 -2.32 (8) / down200 -2.31 (0) |
| SO | entry | close -2.27 (9) / open -2.47 (0) |
| SO | exit | opp -1.97 (9) / t3 -2.63 (0) / t5 -2.38 (0) / t10 -2.09 (0) |
| SO | stop | none -2.19 (9) / 0.1 -2.54 (0) / 0.2 -2.44 (0) |
| SO | band | 1-3 -2.19 (7) / 3-8 -2.34 (2) / 8-20 -2.73 (0) |
| AX | thr | 20 -2.27 (3) / 25 -2.17 (3) / 30 -2.03 (3) |
| AX | signal | dicross -2.03 (4) / pullback -2.30 (5) |
| AX | side | long -1.53 (9) / short -2.59 (0) |
| AX | entry | close -2.00 (9) / open -2.27 (0) |
| AX | exit | dicross -1.96 (0) / atr3 -2.04 (3) / t10 -2.25 (0) / t20 -2.02 (6) |
| AX | stop | none -1.94 (6) / 0.1 -2.29 (0) / 0.2 -2.12 (3) |
| AX | band | 1-3 -2.08 (0) / 3-8 -2.24 (2) / 8-20 -2.37 (7) |
| VC | len | 10 -1.31 (1) / 20 -1.61 (3) / 40 -2.26 (5) |
| VC | tight | 0.1 -2.47 (2) / 0.2 -1.54 (0) / 0.3 -1.23 (7) |
| VC | prior | 0.0 -1.49 (2) / 0.3 -1.46 (7) / 1.0 -2.16 (0) |
| VC | dry | any -1.53 (8) / yes -1.71 (1) |
| VC | bvol | 1.5 -1.56 (1) / 3.0 -1.67 (8) |
| VC | entry | close -1.54 (9) / open -1.69 (0) |
| VC | exit | low10 -1.53 (0) / low20 -1.40 (4) / ma10 -1.86 (0) / t20 -1.69 (0) / t60 -1.14 (4) / target20 -1.82 (0) / target50 -1.70 (1) |
| VC | stop | baselow -1.43 (8) / 0.08 -1.81 (1) / 0.15 -1.56 (0) |
| VC | band | 1-3 -1.88 (1) / 3-8 -1.57 (0) / 8-20 -1.54 (8) |
| EX | ma | 10 -1.66 (8) / 20 -1.62 (0) / 50 -2.07 (1) |
| EX | atr | 3 -1.78 (0) / 4 -1.55 (1) / 6 -1.75 (7) / 8 -1.99 (1) |
| EX | side | short -2.30 (8) / long -1.42 (1) |
| EX | confirm | none -1.57 (9) / color -1.74 (0) / lowerhigh -2.04 (0) |
| EX | entry | close -1.68 (1) / open -1.84 (8) |
| EX | exit | backma -1.50 (0) / t3 -2.05 (3) / t5 -1.87 (5) / t10 -1.75 (0) / target20 -1.64 (1) / target30 -1.55 (0) |
| EX | stop | none -1.55 (5) / atr1 -1.97 (0) / 0.2 -1.87 (1) / c50 -1.64 (3) |
| EX | band | 1-3 -1.72 (4) / 3-8 -1.67 (5) / 8-20 -1.96 (0) |
| IB | thr | 0.05 -2.49 (9) / 0.1 -2.65 (0) / 0.2 -2.78 (0) |
| IB | side | long -2.67 (6) / short -2.67 (3) |
| IB | trend | none -2.82 (0) / up200 -2.41 (8) / down200 -2.64 (1) |
| IB | prior | any -3.17 (0) / move10 -1.98 (9) |
| IB | exit | nextopen -2.82 (0) / nextclose -2.43 (6) / ibsrev -2.60 (3) / t3 -2.71 (0) |
| IB | band | 1-3 -2.58 (3) / 3-8 -2.77 (5) / 8-20 -3.04 (1) |
| VO | mult | 3 -1.63 (0) / 5 -1.65 (2) / 10 -1.67 (7) |
| VO | candle | upwick -1.44 (3) / lowwick -1.53 (0) / bigup -1.75 (6) / bigdown -1.87 (0) |
| VO | after | any -1.93 (0) / up50 -1.40 (9) / down30 -1.66 (0) |
| VO | entry | close -1.55 (4) / open -1.76 (5) |
| VO | exit | t1 -1.84 (2) / t3 -1.66 (7) / t5 -1.62 (0) / t10 -1.62 (0) / target20 -1.57 (0) |
| VO | stop | none -1.34 (9) / 0.1 -1.90 (0) / 0.2 -1.67 (0) |
| VO | band | 1-3 -1.61 (2) / 3-8 -1.62 (7) / 8-20 -1.78 (0) |
| DV | rsi | 5 -2.02 (2) / 14 -1.69 (7) |
| DV | look | 20 -1.86 (7) / 55 -1.89 (2) |
| DV | side | long -1.47 (9) / short -2.44 (0) |
| DV | confirm | none -2.08 (4) / color -1.74 (5) |
| DV | entry | close -1.79 (9) / open -1.95 (0) |
| DV | exit | t5 -2.10 (0) / t10 -1.87 (0) / t20 -1.78 (2) / rsi50 -1.85 (2) / atr3 -1.67 (5) |
| DV | stop | none -1.66 (8) / 0.1 -2.08 (0) / 0.2 -1.91 (1) |
| DV | band | 1-3 -1.82 (0) / 3-8 -1.65 (7) / 8-20 -2.33 (2) |
| GP | gap | 0.05 -2.31 (0) / 0.1 -1.79 (0) / 0.2 -1.46 (2) / 0.3 -1.32 (1) / 0.4 -1.28 (6) |
| GP | dir | up -1.60 (9) / down -1.59 (0) |
| GP | close | cont -1.64 (0) / fade -1.54 (9) |
| GP | entry | close -1.46 (9) / open -1.72 (0) |
| GP | exit | t1 -1.77 (5) / t3 -1.57 (3) / t5 -1.57 (1) / fill -1.54 (0) / target20 -1.51 (0) |
| GP | stop | none -1.31 (9) / 0.1 -1.82 (0) / 0.2 -1.64 (0) |
| GP | band | 1-3 -1.62 (6) / 3-8 -1.61 (3) / 8-20 -1.57 (0) |
| IE | pair | 5/13 -2.15 (7) / 9/20 -2.10 (1) / 20/50 -1.87 (1) |
| IE | mult | 1 -2.16 (8) / 3 -2.05 (0) / 5 -1.94 (1) |
| IE | side | long -2.21 (0) / short -1.76 (9) |
| IE | scope | gapup -2.15 (5) / runner -1.94 (4) / gapdown -2.01 (0) |
| IE | after | 15 -1.97 (8) / 60 -2.10 (1) |
| IE | exit | crossback -2.42 (0) / close -2.02 (0) / d3 -1.72 (9) / next_open -1.90 (0) |
| IE | stop | swing -2.29 (0) / pct10 -1.88 (2) / pct20 -1.90 (7) |
| IE | band | 1-3 -2.35 (2) / 3-8 -1.93 (7) / 8-20 -1.86 (0) |
| IV | k | 1.0 -2.02 (7) / 1.5 -2.05 (2) / 2.0 -1.98 (0) / 3.0 -1.85 (0) |
| IV | mode | revert -2.11 (0) / break -1.76 (9) |
| IV | side | long -2.09 (0) / short -1.83 (9) |
| IV | scope | gapup -2.04 (0) / runner -1.89 (9) / gapdown -1.98 (0) |
| IV | after | 15 -1.94 (7) / 60 -1.98 (2) |
| IV | exit | tovwap -2.73 (0) / close -1.88 (0) / d3 -1.65 (9) / next_open -1.68 (0) |
| IV | stop | ext -2.19 (0) / pct10 -1.85 (0) / pct20 -1.88 (9) |
| IV | band | 1-3 -2.14 (0) / 3-8 -1.87 (9) / 8-20 -1.88 (0) |
| IR | n | 7 -1.98 (9) / 14 -1.83 (0) |
| IR | lvl | 80 -1.96 (9) / 90 -1.87 (0) |
| IR | side | long -2.09 (0) / short -1.53 (9) |
| IR | scope | gapup -1.97 (0) / runner -1.65 (9) / gapdown -2.02 (0) |
| IR | confirm | none -1.94 (9) / turn -1.88 (0) |
| IR | exit | rsi50 -2.26 (0) / close -1.80 (0) / d3 -1.78 (9) / next_open -1.76 (0) |
| IR | stop | ext -2.02 (0) / pct10 -1.82 (6) / pct20 -1.87 (3) |
| IR | band | 1-3 -1.88 (0) / 3-8 -1.95 (9) / 8-20 -1.90 (0) |
| IM | set | 12/26/9 -2.05 (1) / 5/35/5 -2.09 (8) |
| IM | signal | cross -2.15 (8) / zero -1.98 (1) |
| IM | side | long -2.23 (0) / short -1.84 (9) |
| IM | scope | gapup -2.21 (5) / runner -1.98 (4) / gapdown -2.02 (0) |
| IM | after | 15 -2.03 (9) / 60 -2.13 (0) |
| IM | exit | opp -2.50 (0) / close -2.07 (0) / d3 -1.74 (9) / next_open -1.92 (0) |
| IM | stop | swing -2.34 (0) / pct10 -1.90 (0) / pct20 -1.90 (9) |
| IM | band | 1-3 -2.40 (3) / 3-8 -1.97 (6) / 8-20 -1.89 (0) |
| IF | pole | 0.1 -1.54 (9) / 0.2 -1.54 (0) / 0.4 -2.17 (0) |
| IF | retrace | 0.38 -1.70 (2) / 0.5 -1.75 (3) / 0.62 -1.75 (4) |
| IF | side | long -1.78 (0) / short -1.64 (9) |
| IF | scope | gapup -1.39 (3) / runner -1.72 (6) / gapdown -2.02 (0) |
| IF | exit | close -1.56 (0) / r2 -1.90 (0) / trail20 -1.82 (0) / d3 -1.68 (8) / next_open -1.53 (1) |
| IF | stop | flag -1.81 (0) / pct10 -1.64 (2) / pct20 -1.70 (7) |
| IF | band | 1-3 -1.93 (0) / 3-8 -1.57 (9) / 8-20 -1.67 (0) |

## 6. Latest pick of each family

- RS 2026: RS_RSI|7885 = {'n': 14, 'lvl': 10, 'side': 'short', 'trend': 'up50', 'entry': 'open', 'exit': 'sma5', 'stop': 'none', 'band': '3-8'}
- BB 2026: BB_BOLL|4420 = {'n': 50, 'k': 2.0, 'mode': 'revert', 'side': 'long', 'trend': 'up200', 'entry': 'close', 'exit': 'opp', 'stop': 'none', 'band': '3-8'}
- MA 2026: MA_CROSS|2160 = {'pair': '50/200', 'type': 'ema', 'signal': 'pullback', 'side': 'long', 'entry': 'close', 'exit': 'crossback', 'stop': 'none', 'band': '1-3'}
- DN 2026: DN_DONCHIAN|7263 = {'n': 252, 'vol': 0.0, 'loc': 'top25', 'side': 'long', 'entry': 'close', 'exit': 't40', 'stop': 'none', 'band': '1-3'}
- FB 2026: FB_FAILBREAK|819 = {'n': 252, 'within': 1, 'vol': 2.0, 'side': 'short', 'exit': 't5', 'stop': 'none', 'band': '1-3'}
- CS 2026: CS_CANDLE|935 = {'pattern': 'hammer', 'context': 'move20', 'entry': 'close', 'exit': 't10', 'stop': 'none', 'band': '8-20'}
- MC 2026: MC_MACD|171 = {'set': '12/26/9', 'signal': 'sig', 'side': 'long', 'trend': 'up200', 'entry': 'open', 'exit': 'atr3', 'stop': 'none', 'band': '1-3'}
- SO 2026: SO_STOCH|937 = {'set': '14/3', 'lvl': 10, 'signal': 'cross', 'side': 'long', 'trend': 'up200', 'entry': 'close', 'exit': 'opp', 'stop': 'none', 'band': '3-8'}
- AX 2026: AX_ADX|448 = {'thr': 25, 'signal': 'pullback', 'side': 'long', 'entry': 'close', 'exit': 'atr3', 'stop': 0.2, 'band': '3-8'}
- VC 2026: VC_BASE|3582 = {'len': 10, 'tight': 0.3, 'prior': 0.3, 'dry': 'any', 'bvol': 1.5, 'entry': 'close', 'exit': 'target50', 'stop': 'baselow', 'band': '1-3'}
- EX 2026: EX_EXTEND|1824 = {'ma': 10, 'atr': 6, 'side': 'short', 'confirm': 'none', 'entry': 'open', 'exit': 't5', 'stop': 'none', 'band': '1-3'}
- IB 2026: IB_IBS|39 = {'thr': 0.05, 'side': 'long', 'trend': 'up200', 'prior': 'move10', 'exit': 'nextclose', 'band': '1-3'}
- VO 2026: VO_CLIMAX|2260 = {'mult': 10, 'candle': 'upwick', 'after': 'up50', 'entry': 'close', 'exit': 't3', 'stop': 'none', 'band': '3-8'}
- DV 2026: DV_DIVERGE|749 = {'rsi': 14, 'look': 20, 'side': 'long', 'confirm': 'none', 'entry': 'close', 'exit': 'rsi50', 'stop': 'none', 'band': '8-20'}
- GP 2026: GP_GAPDAY|1549 = {'gap': 0.4, 'dir': 'up', 'close': 'fade', 'entry': 'close', 'exit': 't5', 'stop': 'none', 'band': '3-8'}
- IE 2026: IE_EMA|241 = {'pair': '5/13', 'mult': 1, 'side': 'short', 'scope': 'gapup', 'after': 15, 'exit': 'd3', 'stop': 'pct20', 'band': '3-8'}
- IV 2026: IV_VWAPBAND|1609 = {'k': 1.5, 'mode': 'break', 'side': 'short', 'scope': 'runner', 'after': 15, 'exit': 'd3', 'stop': 'pct20', 'band': '3-8'}
- IR 2026: IR_RSI1M|313 = {'n': 7, 'lvl': 80, 'side': 'short', 'scope': 'runner', 'confirm': 'none', 'exit': 'd3', 'stop': 'pct20', 'band': '3-8'}
- IM 2026: IM_MACD|1105 = {'set': '5/35/5', 'signal': 'cross', 'side': 'short', 'scope': 'gapup', 'after': 15, 'exit': 'd3', 'stop': 'pct20', 'band': '3-8'}
- IF 2026: IF_FLAG|169 = {'pole': 0.1, 'retrace': 0.38, 'side': 'short', 'scope': 'gapup', 'exit': 'd3', 'stop': 'pct20', 'band': '3-8'}

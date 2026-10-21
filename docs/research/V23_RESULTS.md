# v23 results: technical analysis on one-minute bars of small caps (105,336 configurations)

Pre-registered in [V23_PREREGISTRATION.md](V23_PREREGISTRATION.md) (with its v23b amendment, made before any result).

| run | GitHub run | what happened |
|---|---|---|
| v23 | 39563557605 | cancelled before any result (superseded by v23b) |
| v23b | 39570591050 | the canary failed: the worker pool could not pickle the patched runner |
| **v23b** | **39577478170** (2026-10-21 09:25-12:51 UTC) | **this report** |

105,336 of 105,336 configurations, no errors, 500 placebos for each selected configuration, R4 costs.

## Summary

- **The pre-registered criterion is not met.** `COMBO23`: walk-forward monthly Sortino **2.93** (7.15 in 2018-2020,
  **1.66** in 2021-2026), 12.4% a year, drawdown -10.7%, PBO 0%, 2023-07+ **0.37**. From 2025 on no family qualified
  for the book (each family's pick scored below 1.0 on the data before), so the book held cash in 2025-2026.
  Deflated Sharpe 0.00 over 105,336 trials.
- **Best families** (walk-forward, middle costs): EM (EMA 9/20 pullback, short) 2.82, PT (bear flag, short) 2.71 and
  2023-07+ 3.76, OR (30-minute opening range low with volume, short) 2.36, SR (round-number break down, short) 1.96,
  MD 1.63, VW 1.44, SQ 1.24, OS 1.10; candles (CD) and climax bars (VC) fail.
- **Every pick is again a short of a gap-up or a runner, held to the third close with a 10% stop** (d3 picked in all
  nine years by SR, VW, EM, MD, SQ, PT, OR). The long side was never picked in any family or year.
- **The new data adds nothing.** The scope of the 100 most liquid small caps (non-event days, downloaded for v23) has
  the worst median configuration of every family (about -3.0 to -3.3) and was never picked.
- **Fragile to costs and to squeezes.** At the high costs every family is near or below zero (EM -0.85, PT 0.50,
  SR 0.27); the worst single trades lose 100-317% of the position (overnight gaps through the stop).
- **No look-ahead signs**: results fall with costs (EM gross 20.0 against 2.82 at the middle and -0.85 at the high
  costs), the placebo gate holds, and no family sits at the Sortino cap at the middle costs.

## Report

Configurations evaluated 105336 of 105336; errors 0. R4 costs (middle) unless stated; 500 placebos for each selected configuration; a configuration can be picked only with at least 50 trades and a trade in 40% of the months before. Target: COMBO23 monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | years placebo-ok | gate | PBO | SPA p (best t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SR | 1.96 | 8.35 | 1.01 | 11.7% | -18.4% | 2.49 | 0.27 | 2.01 | 5.85 | 9/9 | pass | 0% | 0.000 (6.5) |
| VW | 1.44 | 3.36 | 0.88 | 14.8% | -21.9% | 2.30 | -0.92 | 1.55 | 8.42 | 8/9 | pass | 0% | 0.001 (5.4) |
| EM | 2.82 | 4.35 | 2.41 | 27.1% | -21.1% | 4.34 | -0.85 | 3.01 | 20.00 | 8/9 | pass | 0% | 0.000 (6.8) |
| OS | 1.10 | 1.80 | 0.71 | 9.8% | -20.5% | 2.33 | -0.51 | 1.24 | 7.44 | 8/9 | pass | 0% | 0.383 (2.5) |
| MD | 1.63 | 1.82 | 1.54 | 18.0% | -22.7% | 2.90 | -1.28 | 1.77 | 15.98 | 7/9 | pass | 0% | 0.000 (4.2) |
| SQ | 1.24 | 3.14 | 0.46 | 11.1% | -15.3% | 2.24 | -1.26 | 1.38 | 12.87 | 8/9 | pass | 0% | 0.003 (4.3) |
| PT | 2.71 | 2.74 | 2.68 | 15.1% | -11.0% | 3.36 | 0.50 | 2.80 | 10.66 | 7/9 | pass | 0% | 0.001 (4.5) |
| CD | -0.22 | 1.57 | -0.68 | 1.2% | -31.1% | 0.46 | -1.14 | -0.14 | 3.26 | 9/9 | fail | 0% | 0.820 (1.2) |
| VC | -1.35 | -0.42 | -1.85 | -3.4% | -34.6% | -0.97 | -1.85 | -1.31 | 0.06 | 8/9 | fail | 0% | 1.000 (-0.6) |
| OR | 2.36 | 6.57 | 1.42 | 18.4% | -22.1% | 3.22 | -0.27 | 2.48 | 9.83 | 6/9 | pass | 0% | 0.000 (4.9) |

## 2. COMBO23 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO23 | 2.93 | 7.15 | 1.66 | 12.4% | -10.7% | +180% | 0.37 | 0.00 | 0% | not met |

Members by year: 2018: OS, PT, SR; 2019: EM, OR, SR; 2020: EM, PT, SR; 2021: EM, OR, SR; 2022: EM, OR, SR; 2023: EM, OR, SR; 2024: EM, OR; 2025: none; 2026: none

COMBO23 by year: 2018 +9.7%, 2019 +12.7%, 2020 +34.1%, 2021 +17.8%, 2022 +8.1%, 2023 +30.4%, 2024 +1.6%, 2025 +0.0%, 2026 +0.0%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| SR | 1.07 | 11.6% | -18.4% |
| VW | 0.68 | 11.5% | -21.9% |
| EM | 1.79 | 25.0% | -21.1% |
| OS | 0.21 | 5.8% | -20.5% |
| MD | 1.80 | 24.1% | -22.7% |
| SQ | 0.61 | 9.3% | -15.3% |
| PT | 3.76 | 21.9% | -8.8% |
| CD | -1.33 | -7.1% | -30.8% |
| VC | -1.69 | -1.5% | -11.8% |
| OR | 1.23 | 15.9% | -22.1% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| SR | 10.5 | +2.8% | 41% | -101% |
| VW | 34.0 | +1.2% | 39% | -194% |
| EM | 46.7 | +1.4% | 42% | -317% |
| OS | 37.3 | +0.6% | 45% | -62% |
| MD | 52.7 | +0.9% | 38% | -200% |
| SQ | 29.7 | +1.1% | 43% | -156% |
| PT | 12.1 | +3.0% | 44% | -130% |
| CD | 23.1 | +0.2% | 41% | -35% |
| VC | 13.3 | -0.7% | 41% | -27% |
| OR | 23.0 | +2.1% | 43% | -168% |

## 5. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| SR | level | pmh -2.43 (0) / pml -2.57 (0) / pdh -2.41 (0) / pdl -2.56 (0) / pdc -2.54 (0) / orh5 -2.52 (0) / orl5 -2.61 (2) / orh15 -2.49 (0) / orl15 -2.66 (4) / orh30 -2.54 (0) / orl30 -2.71 (0) / h5 -2.36 (0) / l5 -2.60 (0) / round1 -2.33 (0) / round050 -2.39 (3) / pivot -2.44 (0) / r1 -2.42 (0) / s1 -2.58 (0) |
| SR | setup | break_up -2.42 (0) / break_dn -2.48 (1) / fail_up -2.71 (0) / fail_dn -2.43 (0) / retest_up -2.48 (0) / retest_dn -2.53 (8) |
| SR | vol | 0.0 -2.47 (9) / 2.0 -2.54 (0) |
| SR | window | open -2.47 (9) / midlate -2.55 (0) / all -2.49 (0) |
| SR | stop | lvl1 -2.56 (0) / pct10 -2.44 (9) |
| SR | exit | r2 -2.51 (0) / nextlevel -2.59 (0) / ema9 -2.73 (0) / t30 -2.55 (0) / close -2.31 (0) / d3 -2.07 (9) |
| SR | scope | liquid -2.98 (0) / gapup -2.32 (0) / runner -2.21 (9) |
| SR | band | 1-3 -2.47 (0) / 3-8 -2.51 (9) / 8-20 -2.55 (0) |
| VW | setup | reclaim -2.65 (0) / loss -2.57 (3) / bounce -2.64 (0) / reject -2.69 (0) / revert_lo -2.77 (0) / revert_hi -2.76 (0) / break_hi -2.23 (0) / break_lo -2.56 (6) |
| VW | after | 15 -2.61 (9) / 60 -2.66 (0) |
| VW | vol | 0.0 -2.67 (9) / 2.0 -2.60 (0) |
| VW | stop | swing -2.76 (0) / pct10 -2.45 (9) |
| VW | exit | r2 -2.71 (0) / vwapx -2.69 (0) / ema9 -2.88 (0) / t30 -2.69 (0) / close -2.34 (0) / d3 -2.12 (9) |
| VW | scope | liquid -3.32 (0) / gapup -2.42 (1) / runner -2.26 (8) |
| VW | band | 1-3 -2.71 (0) / 3-8 -2.59 (9) / 8-20 -2.54 (0) |
| EM | pair | 9/20 -2.56 (7) / 20/50 -2.49 (1) / 50/200 -2.34 (1) |
| EM | tf | 1 -2.60 (8) / 5 -2.46 (1) / 15 -2.32 (0) |
| EM | setup | cross -2.35 (0) / pullback -2.56 (9) |
| EM | side | long -2.51 (0) / short -2.39 (9) |
| EM | stop | swing -2.69 (0) / pct10 -2.18 (9) |
| EM | exit | crossback -2.43 (0) / r2 -2.70 (0) / t30 -2.74 (0) / close -2.28 (0) / d3 -2.01 (9) |
| EM | scope | liquid -3.25 (0) / gapup -2.21 (6) / runner -1.97 (3) |
| EM | band | 1-3 -2.63 (0) / 3-8 -2.38 (9) / 8-20 -2.32 (0) |
| OS | ind | rsi2 -2.67 (3) / rsi7 -2.52 (0) / rsi14 -2.44 (2) / stoch14 -2.86 (4) |
| OS | tf | 1 -2.69 (7) / 5 -2.56 (2) |
| OS | lvl | x10 -2.64 (1) / x20 -2.62 (8) |
| OS | side | long -2.61 (0) / short -2.64 (9) |
| OS | confirm | none -2.62 (7) / turn -2.63 (2) |
| OS | near | any -2.52 (8) / level -2.68 (1) |
| OS | stop | swing -2.73 (0) / pct10 -2.49 (9) |
| OS | exit | mid -2.72 (0) / r2 -2.64 (0) / t30 -2.66 (0) / close -2.47 (9) |
| OS | scope | liquid -2.99 (0) / gapup -2.47 (1) / runner -2.28 (8) |
| OS | band | 1-3 -2.63 (0) / 3-8 -2.63 (9) / 8-20 -2.62 (0) |
| MD | set | 12/26/9 -2.75 (3) / 5/35/5 -2.73 (6) |
| MD | tf | 1 -2.78 (9) / 5 -2.71 (0) |
| MD | signal | cross -2.69 (9) / zero -2.58 (0) / div -2.87 (0) |
| MD | side | long -2.78 (0) / short -2.69 (9) |
| MD | stop | swing -2.88 (0) / pct10 -2.51 (9) |
| MD | exit | crossback -2.88 (0) / r2 -2.83 (0) / t30 -2.88 (0) / close -2.50 (0) / d3 -2.33 (9) |
| MD | scope | liquid -3.25 (0) / gapup -2.55 (2) / runner -2.36 (7) |
| MD | band | 1-3 -2.80 (0) / 3-8 -2.73 (9) / 8-20 -2.61 (0) |
| SQ | kc | 1.5 -2.49 (0) / 2.0 -2.67 (9) |
| SQ | bars | 10 -2.64 (4) / 20 -2.54 (5) |
| SQ | side | long -2.63 (0) / short -2.53 (9) |
| SQ | vol | 0.0 -2.63 (5) / 2.0 -2.55 (4) |
| SQ | stop | swing -2.69 (0) / pct10 -2.49 (9) |
| SQ | exit | r2 -2.54 (0) / ema9 -2.87 (0) / t30 -2.64 (0) / close -2.20 (0) / d3 -2.05 (9) |
| SQ | scope | liquid -3.31 (0) / gapup -2.31 (9) / runner -2.16 (0) |
| SQ | band | 1-3 -2.72 (0) / 3-8 -2.46 (9) / 8-20 -2.49 (0) |
| PT | pattern | double_top -2.59 (0) / double_bottom -2.77 (0) / asc_triangle -2.69 (0) / desc_triangle -2.75 (1) / bull_flag -1.86 (0) / bear_flag -1.98 (8) |
| PT | size | small -2.50 (2) / large -2.41 (7) |
| PT | after | 15 -2.45 (9) / 60 -2.44 (0) |
| PT | stop | pattern -2.55 (0) / pct10 -2.37 (9) |
| PT | exit | r2 -2.43 (0) / measured -2.59 (0) / ema9 -2.91 (0) / close -2.20 (0) / d3 -1.86 (9) |
| PT | scope | liquid -2.90 (0) / gapup -2.31 (5) / runner -2.19 (4) |
| PT | band | 1-3 -2.61 (0) / 3-8 -2.41 (9) / 8-20 -2.19 (0) |
| CD | candle | engulf -2.54 (0) / pin -2.60 (6) / inside -2.51 (0) / doji -2.61 (3) |
| CD | cside | long -2.57 (0) / short -2.54 (9) |
| CD | at | pm -2.55 (0) / pd -2.52 (0) / vwap -2.65 (0) / hod -2.51 (9) |
| CD | tf | 1 -2.56 (0) / 5 -2.55 (9) |
| CD | stop | swing -2.62 (0) / pct10 -2.47 (9) |
| CD | exit | r1 -2.59 (0) / r2 -2.43 (0) / t15 -2.70 (0) / t30 -2.60 (0) / close -2.20 (9) |
| CD | scope | liquid -3.33 (0) / gapup -2.42 (0) / runner -2.22 (9) |
| CD | band | 1-3 -2.58 (0) / 3-8 -2.48 (9) / 8-20 -2.59 (0) |
| VC | mult | 5.0 -2.76 (8) / 10.0 -2.47 (1) |
| VC | candle | upwick -2.52 (3) / lowwick -2.71 (0) / bigup -2.54 (0) / bigdown -2.66 (6) |
| VC | after | 15 -2.61 (8) / 60 -2.61 (1) |
| VC | stop | swing -2.72 (0) / pct10 -2.43 (9) |
| VC | exit | r1 -2.63 (0) / r2 -2.54 (0) / t15 -2.74 (0) / t30 -2.65 (0) / close -2.35 (9) |
| VC | scope | liquid -3.32 (0) / gapup -2.51 (0) / runner -2.12 (9) |
| VC | band | 1-3 -2.68 (0) / 3-8 -2.47 (5) / 8-20 -2.53 (4) |
| OR | k | 1 -2.79 (0) / 5 -2.61 (0) / 15 -2.49 (7) / 30 -2.42 (2) / 60 -2.40 (0) |
| OR | side | long -2.56 (0) / short -2.57 (9) |
| OR | filter | none -2.59 (0) / vwap -2.52 (0) / rvol -2.44 (9) / gapdir -2.72 (0) |
| OR | stop | range -2.52 (0) / half -2.75 (0) / pct10 -2.42 (9) |
| OR | exit | r1 -2.70 (0) / r2 -2.61 (0) / r3 -2.55 (0) / close -2.41 (0) / d3 -2.19 (9) / ema9 -2.79 (0) |
| OR | scope | liquid -3.17 (0) / gapup -2.22 (2) / runner -2.30 (7) |
| OR | band | 1-3 -2.62 (0) / 3-8 -2.58 (9) / 8-20 -2.45 (0) |

## 6. Latest pick of each family

- SR 2026: SR_LEVEL|55186 = {'level': 'round050', 'setup': 'break_dn', 'vol': 0.0, 'window': 'open', 'stop': 'pct10', 'exit': 'd3', 'scope': 'runner', 'band': '3-8'}
- VW 2026: VW_VWAP|538 = {'setup': 'loss', 'after': 15, 'vol': 0.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'runner', 'band': '3-8'}
- EM 2026: EM_EMA|355 = {'pair': '9/20', 'tf': 1, 'setup': 'pullback', 'side': 'short', 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- OS 2026: OS_OSC|6838 = {'ind': 'rsi14', 'tf': 5, 'lvl': 'x20', 'side': 'short', 'confirm': 'turn', 'near': 'any', 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '3-8'}
- MD 2026: MD_MACD|1258 = {'set': '5/35/5', 'tf': 1, 'signal': 'cross', 'side': 'short', 'stop': 'pct10', 'exit': 'd3', 'scope': 'runner', 'band': '3-8'}
- SQ 2026: SQ_SQUEEZE|985 = {'kc': 2.0, 'bars': 10, 'side': 'short', 'vol': 0.0, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- PT 2026: PT_PATTERN|2065 = {'pattern': 'bear_flag', 'size': 'large', 'after': 15, 'stop': 'pct10', 'exit': 'd3', 'scope': 'gapup', 'band': '3-8'}
- CD 2026: CD_CANDLE|5758 = {'candle': 'doji', 'cside': 'short', 'at': 'hod', 'tf': 5, 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '3-8'}
- VC 2026: VC_CLIMAX|89 = {'mult': 5.0, 'candle': 'upwick', 'after': 15, 'stop': 'pct10', 'exit': 'close', 'scope': 'runner', 'band': '8-20'}
- OR 2026: OR_ORB|5011 = {'k': 30, 'side': 'short', 'filter': 'rvol', 'stop': 'pct10', 'exit': 'd3', 'scope': 'runner', 'band': '3-8'}

# v19 results: small caps, entry x exit grids (5,542 configurations)

Pre-registered in [V19_PREREGISTRATION.md](V19_PREREGISTRATION.md). GitHub run 39454310861 (2026-10-20): 300 real
shards x 4 processes, selection, 300 placebo shards x 4 processes, report; 6,094 of 6,094 units, no errors. Diagnostic
run 39456656320. Walk-forward 2018-01 to 2026-10-16 on the v18b inputs. Nothing in 2018-2026 is clean for the
researcher (v19 was designed after v18's whole-sample results), and v19 contains v18's winners as neighbours.

## Summary

- **The pre-registered criterion is met, by far.** `COMBO19`: walk-forward monthly Sortino **13.79** (20.00, the cap,
  in 2018-2020; **10.09** in 2021-2026), 25.9% a year, maximum drawdown **-7.0%**, worst month -2.8%, 13 losing
  months of 106, PBO 0%; 2023-07 to 2026-10: Sortino 15.62, 28.3% a year, drawdown -2.8%. Yearly: +5.5%, +19.5%,
  +82.9%, +14.7%, +11.0%, +27.1%, +23.4%, +31.8%, +24.2% (2026 to October). Deflated Sharpe 0.00 over all trials.
- **The exit matters more than the entry.** Short small caps that gap up, enter during the day, and **hold to the
  close of the third session** instead of covering at the close: across all XS1 configurations the median Sortino is
  0.95 with the close exit, 4.31 covering at the next open and **5.42** with d3; the same holds in XS2 (0.82 -> 4.12)
  and XS4 (0.30 -> 3.93). In the picks' trades 79% (XS1), 97% (XS2) and 65% (XS4) of the profit comes from the nights
  after the entry day. Every walk-forward year picked d3 in XS1, XS2 and XS4.

| family | what it is (latest pick) | WF Sortino | 2018-20 | 2021-26 | CAGR | max DD | high costs | gate | 2023-07+ |
|---|---|---|---|---|---|---|---|---|---|
| XS1_GAPFADE | gap-up >= 30%, short the 15-minute-low break, stop 20%, hold to the third close | 12.75 | 20.00 | 8.59 | 41.0% | -7.5% | 6.36 | fail (5/9) | 6.44 |
| XS2_RUNFADE | up >= 80% at 11:30 and below VWAP, short, stop 20%, hold to the third close | 6.10 | 16.80 | 3.90 | 32.6% | -11.2% | 1.70 | pass | 4.53 |
| XS4_PMFADE | gap-up >= 30% opening 5% below the premarket high, 5-minute-low break, hold to the third close | 5.77 | 13.88 | 4.99 | 22.9% | -6.9% | 3.92 | fail (4/9) | 6.13 |
| DS1_RUNUP | close 4x the low of the 5 sessions before, short the next open, no stop, out at -50% or after 20 sessions | 7.01 | 5.08 | 7.90 | 82.0% | -34.4% | 3.46 | pass | 13.40 |
| ON1_NIGHTSHORT | gap-up >= 30-50% closing 10% below its open, short the close, hold two closes | 4.35 | 2.47 | 5.90 | 21.4% | -14.2% | 3.02 | pass | 7.32 |
| ON2_NIGHTLONG | down >= 40% in a day, buy the close, sell the next open | 2.72 | 5.11 | 2.46 | 12.5% | -12.7% | 2.28 | pass | 2.55 |

  High costs = half-spreads x2 and borrow fees x3. Monthly correlations of these streams are 0.0-0.45.
- **Trades** (the book's middle-cost trades in the picked years): XS1 28.9 a month, +5.0% a trade, 60% winners;
  XS2 36.4, +3.2%, 56%; XS4 15.2, +7.3%, 57%; DS1 6.4, +19.8%, 78%; ON1 7.8, +6.4%, 68%. The ten best trades make
  5-17% of each family's profit; XS1, XS4 and ON1 are positive in every year.
- **Every long failed again**: gap-and-go (XL1 -0.74), gap-down bounce (XL2 -0.78), crash bounce over days (DL1 -1.76),
  momentum (DL2 -0.86, drawdown -95%). The one exception is the one-night bounce after a 40% fall (ON2 2.72). Event
  shorts (DS2 0.90) and day-two fades (XS3 0.60) are weak.
- **Data check** (diagnostic): the first minute bar's open matches the daily open on the same raw scale (median
  difference 0, 99th percentile 1.1%); the last minute close differs from the official close by a median 0.07% (the
  closing auction). The total of a multi-day trade does not depend on that close (it runs from the entry to the exit),
  so the overnight profits are not a scale artefact.
- **Caveats, in order of importance:** (1) borrow: these trades hold shorts overnight in small caps on their gap
  days (31% of XS1's trades below $2); availability and fees come from a 2026 IBKR snapshot by price and size cells,
  not from each stock that day, and a short that cannot be located does not happen; (2) the researcher had seen v18's
  whole-sample results (overnight and multi-day small-cap shorts work) before designing v19, so the good 2018-2026
  numbers are not an independent test; (3) the deflated Sharpe is 0.00; (4) two of the strongest families (XS1, XS4)
  fail the placebo gate in some years, as v14-v16's gap fades did.

## Full report

Units 6094 of 6094; errors 0. Design 2016-01-04 to 2026-10-16 (crypto from 2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | years placebo-ok | gate | PBO | best config (design Sortino, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XS1 | 12.75 | 20.00 | 8.59 | 41.0% | -7.5% | +1944% | 15.01 | 6.36 | 5/9 | fail | 0% | XS1_GAPFADE|383 (14.06, p 0.00) |
| XS2 | 6.10 | 16.80 | 3.90 | 32.6% | -11.2% | +1095% | 8.37 | 1.70 | 8/9 | pass | 0% | XS2_RUNFADE|47 (11.25, p 0.00) |
| XS3 | 0.60 | 3.53 | -0.00 | 4.4% | -13.8% | +46% | 0.81 | -0.02 | 6/9 | fail | 0% | XS3_DAY2FADE|21 (2.91, p 0.01) |
| XS4 | 5.77 | 13.88 | 4.99 | 22.9% | -6.9% | +512% | 6.38 | 3.92 | 4/9 | fail | 0% | XS4_PMFADE|59 (7.35, p 0.03) |
| XL1 | -0.74 | -0.78 | -0.76 | -1.8% | -23.0% | -15% | -0.65 | -0.92 | 2/9 | fail | 0% | XL1_GAPGO|164 (0.39, p 0.12) |
| XL2 | -0.78 | -1.68 | -0.10 | -0.3% | -20.2% | -3% | -0.62 | -1.06 | 0/9 | fail | 1% | XL2_GAPDOWNLONG|148 (1.17, p 0.10) |
| DS1 | 7.01 | 5.08 | 7.90 | 82.0% | -34.4% | +19188% | 7.24 | 3.46 | 9/9 | pass | 0% | DS1_RUNUP|1834 (14.33, p 0.00) |
| DS2 | 0.90 | -0.84 | 1.69 | 12.9% | -38.9% | +190% | 1.02 | -0.29 | 9/9 | fail | 6% | DS2_EVENTSHORT|10 (0.77, p 0.00) |
| DL1 | -1.76 | -1.46 | -1.89 | -14.5% | -74.9% | -75% | -1.67 | -1.92 | 0/9 | fail | 19% | DL1_CRASHBOUNCE|187 (-1.09, p 0.00) |
| DL2 | -0.86 | -0.32 | -1.07 | -25.9% | -95.3% | -93% | -0.73 | -1.11 | 0/9 | fail | 31% | DL2_MOMO|152 (-0.49, p 0.01) |
| ON1 | 4.35 | 2.47 | 5.90 | 21.4% | -14.2% | +448% | 4.63 | 3.02 | 9/9 | pass | 3% | ON1_NIGHTSHORT|13 (9.41, p 0.00) |
| ON2 | 2.72 | 5.11 | 2.46 | 12.5% | -12.7% | +183% | 2.96 | 2.28 | 9/9 | pass | 2% | ON2_NIGHTLONG|25 (2.52, p 0.00) |

## 2. Combination (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |
|---|---|---|---|---|---|---|---|---|---|
| COMBO | 13.79 | 20.00 | 10.09 | 25.9% | -7.0% | +655% | 0.00 | 0% | met |

Members by year: 2018: DS1, ON1; 2019: DS1, ON1, XL1, XS2; 2020: DS1, ON1, XS2; 2021: DS1, ON1, XS2, XS3; 2022: DS1, ON1, XS1, XS2, XS3; 2023: DS1, ON1, XS1, XS2, XS3, XS4; 2024: DS1, ON1, XS1, XS2, XS3, XS4; 2025: DS1, ON1, XS1, XS2, XS3, XS4; 2026: DS1, ON1, XS1, XS2, XS3, XS4

COMBO by year: 2018 +5.5%, 2019 +19.5%, 2020 +82.9%, 2021 +14.7%, 2022 +11.0%, 2023 +27.1%, 2024 +23.4%, 2025 +31.8%, 2026 +24.2%

## The gross record and the 2023-07+ segment

| family | WF Sortino gross (no costs) | WF Sortino middle | 2023-07 to 2026-10 middle | CAGR there | max DD there |
|---|---|---|---|---|---|
| XS1 | 20.00 | 12.75 | 6.44 | 35.5% | -7.5% |
| XS2 | 17.00 | 6.10 | 4.53 | 30.8% | -11.1% |
| XS3 | 1.38 | 0.60 | -0.44 | 2.5% | -13.8% |
| XS4 | 8.19 | 5.77 | 6.13 | 35.2% | -5.9% |
| XL1 | -0.46 | -0.74 | -1.16 | -5.8% | -23.0% |
| XL2 | -0.28 | -0.78 | 0.21 | 5.1% | -4.5% |
| DS1 | 10.37 | 7.01 | 13.40 | 190.7% | -34.4% |
| DS2 | 2.06 | 0.90 | 2.13 | 44.7% | -38.9% |
| DL1 | -1.45 | -1.76 | -2.21 | -20.9% | -55.3% |
| DL2 | -0.44 | -0.86 | -1.53 | -40.3% | -83.0% |
| ON1 | 5.66 | 4.35 | 7.32 | 28.8% | -9.6% |
| ON2 | 3.40 | 2.72 | 2.55 | 18.3% | -12.7% |

## Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| XS1 | 28.9 | +5.0% | 60% | -168% |
| XS2 | 36.4 | +3.2% | 56% | -130% |
| XS3 | 8.9 | +2.6% | 48% | -158% |
| XS4 | 15.2 | +7.3% | 57% | -373% |
| XL1 | 7.5 | -0.5% | 32% | -49% |
| XL2 | 4.6 | +0.1% | 37% | -29% |
| DS1 | 6.4 | +19.8% | 78% | -324% |
| DS2 | 6.7 | +3.9% | 64% | -310% |
| DL1 | 8.0 | -3.1% | 36% | -67% |
| DL2 | 24.2 | -1.9% | 33% | -84% |
| ON1 | 7.8 | +6.4% | 68% | -276% |
| ON2 | 6.2 | +3.5% | 54% | -80% |

## Entry and exit choices

Median 2018-2026 Sortino (middle costs, whole period, so in sample) of all configurations with each value, and in brackets the number of walk-forward years that picked it.

| family | dimension | value median (years picked) |
|---|---|---|
| XS1 | gap | 0.2 0.24 (3) / 0.3 0.88 (6) / 0.5 1.29 (0) / 1.0 0.65 (0) |
| XS1 | band | low -0.09 (7) / high 1.46 (2) |
| XS1 | trig | open 0.55 (0) / orl1 0.77 (0) / orl5 1.60 (0) / orl15 1.27 (8) / orl30 0.51 (0) / vwaploss 1.28 (0) / t30 0.48 (1) / t60 0.19 (0) |
| XS1 | stop | hod 0.32 (0) / pct20 1.38 (9) |
| XS1 | exit | close 0.95 (0) / vwap -0.28 (0) / t60 -0.72 (0) / r2 0.68 (0) / trail20 -0.44 (0) / fill 0.67 (0) / next_open 4.31 (0) / d3 5.42 (9) |
| XS2 | up | 0.4 -0.06 (5) / 0.8 1.47 (4) |
| XS2 | trig | lowerhigh 2.19 (0) / vwaploss 3.02 (3) / hodfail -0.51 (0) / backside 0.96 (1) / t120 0.23 (5) |
| XS2 | band | low 0.02 (7) / high 2.14 (2) |
| XS2 | stop | hod 0.37 (0) / pct20 1.16 (9) |
| XS2 | exit | close 0.82 (0) / vwap -0.85 (0) / r2 0.51 (0) / trail20 -0.51 (0) / next_open 2.54 (0) / d3 4.12 (9) |
| XS3 | day1 | 0.5 -1.28 (3) / 1.0 -0.87 (6) |
| XS3 | trig | open -0.71 (3) / orl5 -0.91 (3) / orl15 -1.28 (3) / vwaploss -0.72 (0) / t30 -1.33 (0) |
| XS3 | band | low -1.81 (0) / high 0.26 (9) |
| XS3 | stop | hod -1.14 (1) / pct20 -1.01 (8) |
| XS3 | exit | close -0.94 (0) / vwap -1.58 (0) / trail20 -1.43 (0) / next_open -0.43 (6) / d3 -0.56 (1) / d5 -0.24 (2) |
| XS4 | gap | 0.3 1.48 (9) / 0.6 1.13 (0) |
| XS4 | drop | 0.05 1.78 (9) / 0.1 1.52 (0) / 0.2 0.27 (0) |
| XS4 | trig | open 1.34 (0) / orl1 0.63 (0) / orl5 1.61 (9) |
| XS4 | stop | pmh 1.38 (3) / hod 1.04 (6) |
| XS4 | exit | close 0.30 (0) / vwap -0.82 (0) / r2 0.27 (0) / next_open 3.37 (0) / d3 3.93 (9) |
| XS4 | band | low 0.23 (3) / high 1.94 (6) |
| XL1 | gap | 0.2 -1.52 (5) / 0.4 -1.74 (3) / 0.8 -1.82 (1) |
| XL1 | band | low -1.91 (0) / high -1.55 (9) |
| XL1 | trig | orh1 -2.20 (0) / orh5 -1.92 (0) / orh15 -1.19 (2) / pmhbreak -1.84 (1) / vwapreclaim -1.68 (1) / hod13 -1.20 (5) |
| XL1 | stop | lod -1.80 (1) / pct10 -1.66 (8) |
| XL1 | exit | close -1.46 (0) / vwap -1.59 (0) / trail10 -1.92 (0) / trail20 -1.59 (6) / next_open -1.56 (3) / d3 -1.87 (0) / d5 -2.01 (0) |
| XL2 | gap | -0.2 -2.06 (1) / -0.35 -1.58 (8) |
| XL2 | band | low -2.16 (2) / high -1.09 (7) |
| XL2 | trig | orh5 -1.60 (7) / orh15 -1.57 (1) / vwapreclaim -1.76 (1) / t30 -1.80 (0) |
| XL2 | stop | lod -1.69 (7) / pct10 -1.77 (2) |
| XL2 | exit | close -1.57 (1) / vwap -1.93 (3) / fill -1.63 (3) / next_open -1.26 (2) / d3 -1.52 (0) |
| DS1 | rise | 0.5 -0.65 (0) / 1.0 -0.29 (0) / 2.0 0.90 (2) / 3.0 1.04 (7) |
| DS1 | window | 1 0.25 (0) / 5 0.13 (8) / 20 -0.10 (1) |
| DS1 | trig | open 1.09 (8) / lowclose -0.58 (0) / redclose -0.48 (0) / redclose_c 0.17 (1) / gapdown 0.38 (0) |
| DS1 | hold | 3 -0.28 (0) / 10 0.40 (1) / 20 0.25 (8) |
| DS1 | stop | 0.25 -0.58 (0) / 0.5 -0.19 (0) / 1.0 0.22 (0) / none 1.11 (9) |
| DS1 | exit | time 0.24 (4) / target50 0.24 (4) / strength -0.18 (1) |
| DS2 | event | offer_spike 0.26 (6) / rsplit -0.80 (3) / deficiency -0.79 (0) / offering -0.59 (0) |
| DS2 | hold | 5 -0.52 (0) / 10 -0.51 (8) / 20 -0.64 (0) / 60 -0.80 (1) |
| DS2 | stop | 0.25 -0.84 (0) / 0.5 -0.71 (0) / none -0.15 (9) |
| DS2 | exit | time -0.65 (4) / target50 -0.63 (5) |
| DL1 | fall | 0.3 -1.93 (4) / 0.5 -1.74 (5) |
| DL1 | news | any -1.83 (6) / none -1.82 (3) |
| DL1 | trig | open -2.14 (0) / greenclose -1.78 (0) / highclose -1.55 (9) |
| DL1 | hold | 1 -1.90 (0) / 3 -1.72 (2) / 5 -1.78 (1) / 10 -1.88 (6) |
| DL1 | stop | 0.2 -1.85 (9) / 0.5 -1.82 (0) / none -1.79 (0) |
| DL1 | exit | time -1.93 (1) / target30 -1.75 (4) / weak -1.83 (4) |
| DL2 | up | 0.2 -1.50 (9) / 0.5 -1.39 (0) |
| DL2 | trig | open -1.66 (0) / redclose -1.30 (3) / highclose -1.36 (6) |
| DL2 | hold | 5 -1.28 (1) / 10 -1.46 (0) / 20 -1.50 (1) / 40 -1.44 (7) |
| DL2 | stop | 0.1 -1.44 (0) / 0.2 -1.45 (5) / 0.3 -1.40 (4) |
| DL2 | exit | time -1.47 (1) / trail20 -1.38 (8) / ma10 -1.44 (0) |
| ON1 | setup | gapfail30 5.65 (8) / gapfail50 4.04 (1) / weak50 0.77 (0) / weak100 0.27 (0) / run200red 0.75 (0) |
| ON1 | exit | next_open 0.65 (0) / next_close 0.83 (0) / close2 1.56 (7) / close3 1.85 (2) |
| ON1 | band | low 2.21 (1) / high 0.96 (8) |
| ON1 | stop | none 1.37 (3) / 0.3 1.19 (6) |
| ON2 | setup | strong20 -1.21 (0) / strong30 -1.26 (0) / strong50 -1.41 (0) / crash20 -1.00 (0) / crash40 0.22 (9) |
| ON2 | exit | next_open -1.02 (9) / next_close -1.26 (0) / close3 -1.31 (0) |
| ON2 | band | low -1.35 (0) / high -1.07 (9) |

## Latest pick of each family

- XS1 2026: XS1_GAPFADE|447 = {'gap': 0.3, 'band': 'high', 'trig': 'orl15', 'stop': 'pct20', 'exit': 'd3'}
- XS2 2026: XS2_RUNFADE|239 = {'up': 0.8, 'trig': 't120', 'band': 'high', 'stop': 'pct20', 'exit': 'd3'}
- XS3 2026: XS3_DAY2FADE|15 = {'day1': 0.5, 'trig': 'open', 'band': 'high', 'stop': 'hod', 'exit': 'next_open'}
- XS4 2026: XS4_PMFADE|59 = {'gap': 0.3, 'drop': 0.05, 'trig': 'orl5', 'stop': 'hod', 'exit': 'd3', 'band': 'high'}
- XL1 2026: XL1_GAPGO|136 = {'gap': 0.2, 'band': 'high', 'trig': 'pmhbreak', 'stop': 'pct10', 'exit': 'trail20'}
- XL2 2026: XL2_GAPDOWNLONG|123 = {'gap': -0.35, 'band': 'high', 'trig': 'orh5', 'stop': 'lod', 'exit': 'next_open'}
- DS1 2026: DS1_RUNUP|1834 = {'rise': 3.0, 'window': 5, 'trig': 'open', 'hold': 20, 'stop': 'none', 'exit': 'target50'}
- DS2 2026: DS2_EVENTSHORT|10 = {'event': 'offer_spike', 'hold': 10, 'stop': 'none', 'exit': 'time'}
- DL1 2026: DL1_CRASHBOUNCE|299 = {'fall': 0.5, 'news': 'any', 'trig': 'highclose', 'hold': 3, 'stop': 0.2, 'exit': 'weak'}
- DL2 2026: DL2_MOMO|43 = {'up': 0.2, 'trig': 'redclose', 'hold': 5, 'stop': 0.3, 'exit': 'trail20'}
- ON1 2026: ON1_NIGHTSHORT|25 = {'setup': 'gapfail50', 'exit': 'close2', 'band': 'low', 'stop': 0.3}
- ON2 2026: ON2_NIGHTLONG|25 = {'setup': 'crash40', 'exit': 'next_open', 'band': 'high'}

Selection check: picks that differ from the selection job: none.

COMBO19 over 2023-07-01 to 2026-10-16: Sortino 15.62, CAGR 28.3%, max DD -2.8%.
Pre-registered criterion (walk-forward >= 4, halves >= 3, PBO < 20%, 2023-07+ >= 3): met.

# v19r results: the v19 grid under realistic costs (R3)

Amendment of [V19_PREREGISTRATION.md](V19_PREREGISTRATION.md) (R3: measured event-day half-spreads, 1.5x at the
open, slippage on stop-type fills, IBKR tiered all-in commissions with SEC and FINRA sale fees, borrow availability
x0.8 and fees doubled with a 100% floor). GitHub run 39462806354 (2026-10-20): 6,110 of 6,110 units, no errors;
spread calibration run 39461295472. The v19 results under the older R1 costs are in [V19_RESULTS.md](V19_RESULTS.md).

## Summary

- **The criterion is still met under realistic costs.** `COMBO19` walk-forward monthly Sortino **8.45** (14.44 in
  2018-2020, **6.98** in 2021-2026), 16.9% a year, maximum drawdown **-4.0%**, worst month -1.9%, 19 losing months of
  106, PBO 0%; 2023-07 to 2026-10: Sortino 8.64, 22.9% a year, drawdown -2.6%. Yearly: +7.5%, +8.9%, +37.0%, +9.3%,
  +4.6%, +17.4%, +11.5%, +37.8%, +19.3% (2026 to October). Deflated Sharpe 0.00.
- **R1 against R3** (walk-forward Sortino, middle costs; high = R3 with half-spreads x2 and borrow fees x3):

| family | v19 (R1) | v19r (R3) | R3 high | CAGR R3 | max DD R3 | 2023-07+ R3 | trades a month | mean net a trade |
|---|---|---|---|---|---|---|---|---|
| XS1_GAPFADE | 12.75 | **5.21** | 1.10 | 21.9% | -7.5% | 2.49 | 29.0 | +3.6% |
| ON1_NIGHTSHORT | 4.35 | **4.05** | 1.35 | 18.5% | -12.4% | 9.38 | 9.6 | +5.8% |
| DS1_RUNUP | 7.01 | **3.94** | 1.17 | 38.3% | -21.2% | 10.09 | 6.5 | +13.2% |
| XS2_RUNFADE | 6.10 | 2.67 | 0.07 | 16.8% | -12.9% | 2.67 | 34.9 | +2.3% |
| XS4_PMFADE | 5.77 | 1.42 | 0.01 | 8.4% | -7.8% | 0.96 | 14.9 | +5.3% |
| ON2_NIGHTLONG | 2.72 | -0.57 | -1.02 | -3.9% | -53.0% | -1.24 | 9.0 | -0.5% |
| COMBO19 | 13.79 | **8.45** | | 16.9% | -4.0% | 8.64 | | |

- **What survives** is the same idea in three forms: short small caps after a failed gap or an extreme run, and hold
  for days. Every walk-forward year still picks the d3 exit in XS1 (median Sortino of all XS1 configurations: d3 2.35,
  next open 1.83, every same-day exit below zero) and no stop in DS1. Under R3 XS1 moves to the $1-$5 band, whose
  measured spreads are below the old table, and away from $5-$20, whose measured spreads are above it.
- **What dies:** the one-night long after a crash (ON2 2.72 -> -0.57), XS4 (5.77 -> 1.42), every other long.
- **Fragility:** doubling the realistic spreads and tripling the realistic borrow fees takes the survivors to
  Sortino 1.1-1.35. The edge is real before costs (gross XS1 15.67, ON1 7.02, DS1 6.44) but costs take most of it, so
  the result rests on executing near the measured average spread and on borrow being available.
- **Caveats** as in v19: borrow availability and fees are estimates from a 2026 snapshot (no historical source); the
  researcher saw v18's whole-sample results before v19; the deflated Sharpe is 0.00.

## Full report

Units 6110 of 6110; errors 0. Design 2016-01-04 to 2026-10-16 (crypto from 2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | years placebo-ok | gate | PBO | best config (design Sortino, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XS1 | 5.21 | 20.00 | 3.53 | 21.9% | -7.5% | +469% | 6.18 | 1.10 | 8/9 | pass | 0% | XS1_GAPFADE|383 (8.08, p 0.00) |
| XS2 | 2.67 | 5.44 | 1.92 | 16.8% | -12.9% | +292% | 3.55 | 0.07 | 9/9 | pass | 0% | XS2_RUNFADE|167 (5.01, p 0.00) |
| XS3 | 0.13 | 2.94 | -0.55 | 3.0% | -9.9% | +29% | 0.43 | -0.73 | 6/9 | fail | 7% | XS3_DAY2FADE|21 (0.86, p 0.01) |
| XS4 | 1.42 | 4.44 | 0.96 | 8.4% | -7.8% | +103% | 1.85 | 0.01 | 3/9 | fail | 0% | XS4_PMFADE|187 (3.31, p 0.00) |
| XL1 | -1.33 | -1.38 | -1.30 | -3.0% | -27.9% | -24% | -1.18 | -1.58 | 3/9 | fail | 8% | XL1_GAPGO|165 (-0.19, p 0.10) |
| XL2 | -1.20 | -2.12 | -0.77 | -1.5% | -22.3% | -13% | -1.01 | -1.52 | 0/9 | fail | 5% | XL2_GAPDOWNLONG|148 (0.65, p 0.08) |
| DS1 | 3.94 | 2.38 | 5.01 | 38.3% | -21.2% | +1624% | 4.16 | 1.17 | 9/9 | pass | 0% | DS1_RUNUP|1834 (10.28, p 0.00) |
| DS2 | 0.19 | -1.15 | 0.82 | 3.6% | -38.4% | +37% | 0.31 | -1.26 | 8/9 | fail | 0% | DS2_EVENTSHORT|10 (0.07, p 0.00) |
| DL1 | -1.77 | -1.55 | -1.87 | -12.3% | -68.5% | -68% | -1.68 | -1.92 | 0/9 | fail | 17% | DL1_CRASHBOUNCE|417 (-1.15, p 0.27) |
| DL2 | -1.06 | -0.90 | -1.13 | -38.2% | -98.6% | -99% | -0.97 | -1.22 | 1/9 | fail | 10% | DL2_MOMO|152 (-0.65, p 0.01) |
| ON1 | 4.05 | 2.04 | 5.40 | 18.5% | -12.4% | +343% | 4.54 | 1.35 | 9/9 | pass | 4% | ON1_NIGHTSHORT|28 (7.63, p 0.00) |
| ON2 | -0.57 | 2.38 | -1.02 | -3.9% | -53.0% | -30% | -0.31 | -1.02 | 7/9 | fail | 5% | ON2_NIGHTLONG|25 (1.81, p 0.00) |

## 2. Combination (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |
|---|---|---|---|---|---|---|---|---|---|
| COMBO | 8.45 | 14.44 | 6.98 | 16.9% | -4.0% | +294% | 0.00 | 0% | met |

Members by year: 2018: DS1, ON1, XL1, XS2; 2019: DS1, ON1, XL1, XS1, XS2; 2020: DS1, ON1, XS1, XS2; 2021: DS1, ON1, XS1, XS2, XS3; 2022: DS1, ON1, XS1, XS2, XS3; 2023: DS1, ON1, XS1, XS2, XS3; 2024: DS1, ON1, XS1, XS2, XS4; 2025: DS1, ON1, XS1, XS2, XS4; 2026: DS1, ON1, XS1, XS2, XS4

COMBO by year: 2018 +7.5%, 2019 +8.9%, 2020 +37.0%, 2021 +9.3%, 2022 +4.6%, 2023 +17.4%, 2024 +11.5%, 2025 +37.8%, 2026 +19.3%

## The gross record and the 2023-07+ segment

| family | WF Sortino gross (no costs) | WF Sortino middle | 2023-07 to 2026-10 middle | CAGR there | max DD there |
|---|---|---|---|---|---|
| XS1 | 15.67 | 5.21 | 2.49 | 19.1% | -7.5% |
| XS2 | 12.80 | 2.67 | 2.67 | 21.5% | -10.7% |
| XS3 | 1.42 | 0.13 | -1.01 | 1.0% | -9.9% |
| XS4 | 5.90 | 1.42 | 0.96 | 10.0% | -7.8% |
| XL1 | -0.69 | -1.33 | -1.21 | -2.4% | -16.7% |
| XL2 | -0.32 | -1.20 | -0.47 | 2.5% | -5.3% |
| DS1 | 6.44 | 3.94 | 10.09 | 84.9% | -19.5% |
| DS2 | 1.94 | 0.19 | 1.10 | 20.9% | -33.9% |
| DL1 | -1.48 | -1.77 | -2.22 | -16.9% | -47.4% |
| DL2 | -0.80 | -1.06 | -1.64 | -49.0% | -89.5% |
| ON1 | 7.02 | 4.05 | 9.38 | 32.1% | -8.6% |
| ON2 | 0.29 | -0.57 | -1.24 | -15.1% | -48.5% |

## Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| XS1 | 29.0 | +3.6% | 58% | -170% |
| XS2 | 34.9 | +2.3% | 53% | -155% |
| XS3 | 7.6 | +2.1% | 53% | -159% |
| XS4 | 14.9 | +5.3% | 57% | -375% |
| XL1 | 4.1 | -1.4% | 29% | -75% |
| XL2 | 3.4 | -1.0% | 35% | -44% |
| DS1 | 6.5 | +13.2% | 75% | -474% |
| DS2 | 6.7 | +1.5% | 62% | -312% |
| DL1 | 4.6 | -4.5% | 33% | -60% |
| DL2 | 14.5 | -4.1% | 29% | -84% |
| ON1 | 9.6 | +5.8% | 67% | -277% |
| ON2 | 9.0 | -0.5% | 43% | -91% |

## Entry and exit choices

Median 2018-2026 Sortino (middle costs, whole period, so in sample) of all configurations with each value, and in brackets the number of walk-forward years that picked it.

| family | dimension | value median (years picked) |
|---|---|---|
| XS1 | gap | 0.2 -1.16 (3) / 0.3 -0.55 (4) / 0.5 0.01 (2) / 1.0 -0.26 (0) |
| XS1 | band | low -0.80 (9) / high -0.19 (0) |
| XS1 | trig | open -0.94 (0) / orl1 -1.07 (0) / orl5 -0.24 (0) / orl15 -0.26 (4) / orl30 -0.62 (0) / vwaploss 0.07 (2) / t30 -0.38 (2) / t60 -0.44 (1) |
| XS1 | stop | hod -0.95 (0) / pct20 0.08 (9) |
| XS1 | exit | close -0.17 (0) / vwap -1.12 (0) / t60 -1.51 (0) / r2 -0.22 (0) / trail20 -1.28 (0) / fill -0.43 (0) / next_open 1.83 (0) / d3 2.35 (9) |
| XS2 | up | 0.4 -0.93 (3) / 0.8 0.58 (6) |
| XS2 | trig | lowerhigh 0.43 (0) / vwaploss 1.40 (7) / hodfail -1.24 (0) / backside -0.02 (1) / t120 -0.44 (1) |
| XS2 | band | low -0.41 (7) / high 0.19 (2) |
| XS2 | stop | hod -0.38 (0) / pct20 0.35 (9) |
| XS2 | exit | close -0.05 (0) / vwap -1.30 (0) / r2 -0.30 (1) / trail20 -1.10 (0) / next_open 1.12 (1) / d3 1.51 (7) |
| XS3 | day1 | 0.5 -1.85 (2) / 1.0 -1.37 (7) |
| XS3 | trig | open -1.30 (3) / orl5 -1.60 (2) / orl15 -1.75 (2) / vwaploss -1.33 (0) / t30 -1.69 (2) |
| XS3 | band | low -2.00 (0) / high -0.87 (9) |
| XS3 | stop | hod -1.63 (0) / pct20 -1.48 (9) |
| XS3 | exit | close -1.44 (0) / vwap -1.95 (0) / trail20 -1.84 (0) / next_open -1.18 (8) / d3 -1.29 (0) / d5 -1.32 (1) |
| XS4 | gap | 0.3 -0.02 (9) / 0.6 -0.04 (0) |
| XS4 | drop | 0.05 0.27 (8) / 0.1 0.17 (1) / 0.2 -0.58 (0) |
| XS4 | trig | open 0.27 (1) / orl1 -0.76 (0) / orl5 0.20 (8) |
| XS4 | stop | pmh 0.19 (4) / hod -0.36 (5) |
| XS4 | exit | close -0.53 (0) / vwap -1.41 (0) / r2 -0.58 (0) / next_open 1.42 (1) / d3 1.64 (8) |
| XS4 | band | low -0.65 (3) / high 0.28 (6) |
| XL1 | gap | 0.2 -2.05 (3) / 0.4 -2.09 (3) / 0.8 -1.99 (3) |
| XL1 | band | low -2.18 (1) / high -1.92 (8) |
| XL1 | trig | orh1 -2.46 (0) / orh5 -2.21 (0) / orh15 -1.68 (2) / pmhbreak -2.26 (0) / vwapreclaim -1.89 (1) / hod13 -1.49 (6) |
| XL1 | stop | lod -2.10 (1) / pct10 -1.94 (8) |
| XL1 | exit | close -1.78 (0) / vwap -1.98 (0) / trail10 -2.29 (0) / trail20 -1.93 (3) / next_open -1.85 (6) / d3 -2.08 (0) / d5 -2.17 (0) |
| XL2 | gap | -0.2 -2.20 (0) / -0.35 -1.74 (9) |
| XL2 | band | low -2.16 (2) / high -1.55 (7) |
| XL2 | trig | orh5 -1.92 (7) / orh15 -1.84 (1) / vwapreclaim -1.78 (1) / t30 -1.79 (0) |
| XL2 | stop | lod -1.79 (7) / pct10 -1.86 (2) |
| XL2 | exit | close -1.77 (0) / vwap -2.12 (1) / fill -1.76 (5) / next_open -1.61 (2) / d3 -1.82 (1) |
| DS1 | rise | 0.5 -1.73 (0) / 1.0 -1.34 (0) / 2.0 -0.30 (2) / 3.0 0.09 (7) |
| DS1 | window | 1 -0.68 (0) / 5 -0.87 (8) / 20 -1.21 (1) |
| DS1 | trig | open -0.27 (8) / lowclose -1.32 (0) / redclose -1.36 (0) / redclose_c -0.89 (1) / gapdown -0.43 (0) |
| DS1 | hold | 3 -1.04 (0) / 10 -0.73 (8) / 20 -0.93 (1) |
| DS1 | stop | 0.25 -1.67 (0) / 0.5 -1.21 (0) / 1.0 -0.69 (0) / none 0.31 (9) |
| DS1 | exit | time -0.82 (2) / target50 -0.80 (6) / strength -1.08 (1) |
| DS2 | event | offer_spike -0.65 (6) / rsplit -1.06 (3) / deficiency -1.58 (0) / offering -2.10 (0) |
| DS2 | hold | 5 -1.04 (1) / 10 -1.07 (8) / 20 -1.25 (0) / 60 -1.48 (0) |
| DS2 | stop | 0.25 -1.66 (0) / 0.5 -1.34 (0) / none -1.11 (9) |
| DS2 | exit | time -1.35 (2) / target50 -1.27 (7) |
| DL1 | fall | 0.3 -2.02 (2) / 0.5 -1.79 (7) |
| DL1 | news | any -1.92 (6) / none -1.89 (3) |
| DL1 | trig | open -2.21 (0) / greenclose -1.91 (0) / highclose -1.66 (9) |
| DL1 | hold | 1 -2.00 (0) / 3 -1.79 (2) / 5 -1.90 (2) / 10 -1.97 (5) |
| DL1 | stop | 0.2 -1.96 (3) / 0.5 -1.89 (5) / none -1.86 (1) |
| DL1 | exit | time -2.01 (4) / target30 -1.82 (2) / weak -1.94 (3) |
| DL2 | up | 0.2 -1.86 (8) / 0.5 -1.66 (1) |
| DL2 | trig | open -1.97 (0) / redclose -1.63 (4) / highclose -1.68 (5) |
| DL2 | hold | 5 -1.65 (1) / 10 -1.76 (0) / 20 -1.77 (0) / 40 -1.74 (8) |
| DL2 | stop | 0.1 -1.85 (0) / 0.2 -1.71 (2) / 0.3 -1.64 (7) |
| DL2 | exit | time -1.70 (7) / trail20 -1.80 (1) / ma10 -1.74 (1) |
| ON1 | setup | gapfail30 2.83 (8) / gapfail50 2.30 (1) / weak50 0.22 (0) / weak100 -0.12 (0) / run200red 0.07 (0) |
| ON1 | exit | next_open 0.15 (0) / next_close 0.48 (0) / close2 1.09 (6) / close3 1.17 (3) |
| ON1 | band | low 1.61 (2) / high 0.46 (7) |
| ON1 | stop | none 0.96 (4) / 0.3 0.40 (5) |
| ON2 | setup | strong20 -1.47 (0) / strong30 -1.34 (0) / strong50 -1.41 (0) / crash20 -1.26 (0) / crash40 0.11 (9) |
| ON2 | exit | next_open -1.11 (7) / next_close -1.33 (0) / close3 -1.38 (2) |
| ON2 | band | low -1.34 (5) / high -1.20 (4) |

## Latest pick of each family

- XS1 2026: XS1_GAPFADE|607 = {'gap': 0.5, 'band': 'low', 'trig': 'vwaploss', 'stop': 'pct20', 'exit': 'd3'}
- XS2 2026: XS2_RUNFADE|167 = {'up': 0.8, 'trig': 'vwaploss', 'band': 'high', 'stop': 'pct20', 'exit': 'd3'}
- XS3 2026: XS3_DAY2FADE|141 = {'day1': 1.0, 'trig': 'open', 'band': 'high', 'stop': 'pct20', 'exit': 'next_open'}
- XS4 2026: XS4_PMFADE|59 = {'gap': 0.3, 'drop': 0.05, 'trig': 'orl5', 'stop': 'hod', 'exit': 'd3', 'band': 'high'}
- XL1 2026: XL1_GAPGO|417 = {'gap': 0.8, 'band': 'low', 'trig': 'hod13', 'stop': 'pct10', 'exit': 'next_open'}
- XL2 2026: XL2_GAPDOWNLONG|123 = {'gap': -0.35, 'band': 'high', 'trig': 'orh5', 'stop': 'lod', 'exit': 'next_open'}
- DS1 2026: DS1_RUNUP|1822 = {'rise': 3.0, 'window': 5, 'trig': 'open', 'hold': 10, 'stop': 'none', 'exit': 'target50'}
- DS2 2026: DS2_EVENTSHORT|11 = {'event': 'offer_spike', 'hold': 10, 'stop': 'none', 'exit': 'target50'}
- DL1 2026: DL1_CRASHBOUNCE|302 = {'fall': 0.5, 'news': 'any', 'trig': 'highclose', 'hold': 3, 'stop': 0.5, 'exit': 'weak'}
- DL2 2026: DL2_MOMO|152 = {'up': 0.5, 'trig': 'redclose', 'hold': 5, 'stop': 0.3, 'exit': 'ma10'}
- ON1 2026: ON1_NIGHTSHORT|25 = {'setup': 'gapfail50', 'exit': 'close2', 'band': 'low', 'stop': 0.3}
- ON2 2026: ON2_NIGHTLONG|29 = {'setup': 'crash40', 'exit': 'close3', 'band': 'high'}

Selection check: picks that differ from the selection job: none.

COMBO19 over 2023-07-01 to 2026-10-16: Sortino 8.64, CAGR 22.9%, max DD -2.6%.
Pre-registered criterion (walk-forward >= 4, halves >= 3, PBO < 20%, 2023-07+ >= 3): met.

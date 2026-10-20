# v18 results: small caps, wide (302 configurations)

Pre-registered in [V18_PREREGISTRATION.md](V18_PREREGISTRATION.md) (two amendments). Three runs: 39423482318 (a
bookkeeping error in the multi-day books: positions were rebalanced to a constant weight every day, which let W2
show +70,553%; discarded), 39427477103 (fixed; the trade-level diagnostic 39431219007 then found warrants and
duplicated tickers) and **39433812183 (v18b: clean universe, the result below)**. Walk-forward over 2018-01 to
2026-10; the 2023-07+ window had been opened before (sealed test of v16) and v18 was designed knowing that result,
so that segment is out of sample for the selection rule but not for the researcher.

## Summary

- **The pre-registered criterion is met.** `COMBO18` (v18 families chosen each year on earlier data): walk-forward
  monthly Sortino **4.15** over 2018-2026 (16.95 in 2018-2020, **3.50** in 2021-2026), 30.0% a year, maximum
  drawdown **-18.9%**, total +906%, PBO 0%; over 2023-07 to 2026-10: Sortino 9.42, 43.4% a year, drawdown -18.4%.
  Yearly: +12.0%, +17.8%, +54.8%, +6.3%, +28.3%, +17.2%, +15.4%, +68.6%, +58.6% (2026 to October).
- **What drives it** (short small caps after extreme runs, or overnight after a faded gap):

| family | rule | WF Sortino | 2018-20 | 2021-26 | CAGR | max DD | gross | high costs | 2023-07+ |
|---|---|---|---|---|---|---|---|---|---|
| H2_FADEOVERNIGHT | short at the close a gap-up of 30%+ that closed 10%+ below its open; cover at the next open | 4.25 | 1.36 | 6.58 | 11.6% | -7.4% | 6.33 | 2.50 | 6.05 |
| W1_FADEGRID | after +100-300% within 5 sessions, short the first close below the prior day's low; 3-10 days | 3.97 | 1.29 | 4.80 | 42.0% | -30.6% | 6.70 | 1.34 | 6.43 |
| W2_SUPERNOVA | after +300-500% within 20 sessions, short the next open; 10-20 days | 3.67 | 9.14 | 3.43 | 99.3% | -59.5% | 4.93 | 1.99 | 4.42 |
| F1_TIMEFADE | short a gap-up below VWAP at a fixed minute | 2.03 | 4.47 | 1.20 | 10.2% | -7.8% | | -0.09 | |
| F5_EXTFADE | short a lower high once the price is 20-50% above VWAP | 1.96 | 1.55 | 2.13 | 8.6% | -9.4% | 2.63 | 1.53 | 4.26 |
| F7_PMFADEOPEN | short the open of a gap that already fell 10-20% from its premarket high | 1.57 | 6.03 | 0.66 | 7.6% | -7.7% | 2.20 | 1.18 | 1.28 |

  High costs = half-spreads x2 and borrow fees x3. The gross column is the walk-forward without any cost.
- **Caveats, in order of importance:** (1) borrow: the availability of these stocks comes from a snapshot of
  today's IBKR file by price and size cells, not from each stock at the moment of the trade, which for stocks
  after a +300% run is the weakest point of the model; today's file has the recent W1/W2 names mostly borrowable but
  at a median fee of about 110% a year and up to 850%; (2) W2 has a 59.5% drawdown and a PBO of 81% (which of its
  configurations wins is unstable); (3) no stop was better than a 50% stop for W1, and W2 had none: squeezes and
  gaps make single losses of -200% to -330% on a position; (4) the deflated Sharpe is 0.00 over all trials of the
  search; (5) the 2023-07+ segment is not clean for the researcher.
- **The small-cap longs, again, lost** after costs (G1-G9: walk-forward Sortino from -2.18 to 0.16 at middle
  costs). Before costs only G1 (0.86) and G5 (0.66) were clearly positive, and the inverted losers (G6) made 0.86
  gross but 0.14 after costs: a small edge in the short direction that the spreads of these stocks eat.

## Full report

Units 2416 of 2416; errors 0. Design 2016-01-04 to 2026-10-16 (crypto from 2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | years placebo-ok | gate | PBO | best config (design Sortino, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 | 2.03 | 4.47 | 1.20 | 10.2% | -7.8% | +135% | 3.69 | -0.09 | 6/9 | pass | 20% | F1_TIMEFADE|10 (1.69, p 0.00) |
| F2 | 1.15 | 1.21 | 1.12 | 8.0% | -16.5% | +96% | 2.22 | -0.36 | 1/9 | fail | 15% | F2_VWAPREJECT|5 (1.49, p 0.01) |
| F3 | 2.42 | 5.73 | 1.55 | 9.9% | -8.9% | +129% | 2.96 | 1.45 | 1/9 | fail | 3% | F3_ORLMULTI|9 (2.34, p 0.14) |
| F4 | -1.02 | -0.77 | -1.12 | -1.4% | -20.2% | -11% | -0.87 | -1.26 | 0/9 | fail | 1% | F4_HODFAIL|5 (-0.86, p 0.91) |
| F5 | 1.96 | 1.55 | 2.13 | 8.6% | -9.4% | +106% | 2.19 | 1.53 | 6/9 | pass | 0% | F5_EXTFADE|7 (1.71, p 0.00) |
| F6 | -1.67 | -1.29 | -1.87 | -1.3% | -16.5% | -11% | -1.35 | -2.10 | 6/9 | fail | 0% | F6_CLOSEFADE|0 (-1.57, p 0.00) |
| F7 | 1.57 | 6.03 | 0.66 | 7.6% | -7.7% | +90% | 1.79 | 1.18 | 7/9 | pass | 5% | F7_PMFADEOPEN|1 (2.60, p 0.00) |
| F9 | 0.29 | 4.73 | -0.51 | 3.9% | -24.9% | +40% | 1.19 | -0.95 | 4/9 | fail | 0% | F9_CATALYST|1 (2.69, p 0.06) |
| F10 | -0.18 | 1.07 | -0.44 | 2.2% | -7.9% | +22% | 0.15 | -0.70 | 7/9 | fail | 0% | F10_FLOATROT|0 (-0.12, p 0.01) |
| F11 | -0.87 | 0.95 | -1.31 | 1.2% | -4.4% | +11% | -0.83 | -0.95 | 6/9 | fail | 15% | F11_REPEAT|1 (-0.58, p 0.08) |
| F12 | -0.93 | 1.28 | -1.39 | -0.9% | -20.2% | -8% | -0.67 | -1.35 | 0/9 | fail | 46% | F12_SRFADE|3 (-0.79, p 0.92) |
| F13 | -0.87 | 1.42 | -1.42 | -0.1% | -12.9% | -1% | -0.59 | -1.32 | 1/9 | fail | 75% | F13_OFFFADE|2 (0.12, p 0.01) |
| F14 | 1.20 | 3.85 | 0.72 | 7.8% | -10.7% | +93% | 1.68 | 0.38 | 0/9 | fail | 0% | F14_DILUTIONFADE|5 (1.10, p 0.61) |
| F15 | 0.72 | 2.61 | 0.26 | 5.4% | -10.7% | +58% | 1.20 | -0.04 | 8/9 | fail | 17% | F15_HALTFADE|1 (1.24, p 0.00) |
| F16 | 0.60 | 1.19 | 0.30 | 5.1% | -14.6% | +54% | 1.34 | -0.40 | 2/9 | fail | 8% | F16_OPENDRIVE|1 (1.74, p 0.06) |
| F17 | -1.22 | -2.05 | -0.71 | -2.6% | -23.4% | -21% | -0.65 | -1.88 | 0/9 | fail | 0% | F17_GAPFILL|5 (-0.77, p 1.00) |
| F18 | -0.60 | 1.07 | -1.07 | 0.6% | -15.0% | +5% | -0.23 | -1.16 | 6/9 | fail | 71% | F18_AFTERNOONFADE|2 (-0.43, p 0.00) |
| F19 | 0.82 | 2.00 | 0.11 | 5.4% | -9.8% | +59% | 1.41 | -0.13 | 0/9 | fail | 27% | F19_SECONDPUSH|3 (0.82, p 0.22) |
| F20 | 1.88 | 4.05 | 1.51 | 10.0% | -8.6% | +131% | 2.68 | 0.69 | 1/9 | fail | 9% | F20_HOTPREMARKET|1 (2.19, p 0.17) |
| F21 | 0.04 | 2.38 | -0.38 | 2.7% | -7.0% | +27% | 0.32 | -0.43 | 4/9 | fail | 0% | F21_LOWFLOAT|4 (0.11, p 0.00) |
| G1 | 0.16 | 0.36 | 0.15 | 3.0% | -11.2% | +30% | 0.40 | -0.25 | 3/9 | fail | 15% | G1_DIPVWAP|1 (0.10, p 0.00) |
| G2 | -0.32 | 2.00 | -0.90 | 1.5% | -15.8% | +14% | -0.13 | -0.65 | 2/9 | fail | 5% | G2_RECLAIM|1 (0.25, p 0.00) |
| G3 | -1.57 | -1.25 | -1.71 | -3.6% | -29.7% | -27% | -1.48 | -1.72 | 1/9 | fail | 75% | G3_GAPDOWNREV|4 (-1.17, p 0.18) |
| G4 | -1.55 | -0.97 | -1.84 | -13.4% | -72.4% | -72% | -1.47 | -1.67 | 0/9 | fail | 52% | G4_PANICBUY|7 (0.63, p 0.14) |
| G5 | -0.16 | -0.01 | -0.21 | 1.9% | -15.8% | +18% | 0.11 | -0.59 | 7/9 | fail | 2% | G5_EARNGO|5 (0.09, p 0.00) |
| G6 | 0.14 | 1.10 | -0.26 | 3.0% | -8.2% | +30% | 0.38 | -0.27 | 5/9 | fail | 10% | G6_INVERTED|2 (0.05, p 0.00) |
| G7 | -0.49 | -0.76 | -0.39 | 1.6% | -8.4% | +15% | -0.33 | -0.76 | 1/9 | fail | 10% | G7_HODRECLAIM|0 (-0.34, p 0.04) |
| G8 | -2.18 | -2.19 | -2.26 | -1.9% | -16.4% | -15% | -2.05 | -2.33 | 2/9 | fail | 41% | G8_LATEPUSH|3 (-1.55, p 0.02) |
| G9 | -1.45 | -1.01 | -1.63 | -7.5% | -53.2% | -50% | -1.33 | -1.66 | 0/9 | fail | 7% | G9_FIRSTPULLBACK|1 (-1.06, p 0.73) |
| H1 | -1.11 | -0.31 | -1.35 | -8.1% | -58.8% | -52% | -0.96 | -1.35 | 9/9 | fail | 33% | H1_STRONGCLOSE|6 (-0.64, p 0.00) |
| H2 | 4.25 | 1.36 | 6.58 | 11.6% | -7.4% | +161% | 4.80 | 2.50 | 9/9 | pass | 25% | H2_FADEOVERNIGHT|0 (4.66, p 0.00) |
| W1 | 3.97 | 1.29 | 4.80 | 42.0% | -30.6% | +2074% | 4.27 | 1.34 | 9/9 | pass | 0% | W1_FADEGRID|3 (4.60, p 0.00) |
| W2 | 3.67 | 9.14 | 3.43 | 99.3% | -59.5% | +42627% | 3.77 | 1.99 | 9/9 | pass | 81% | W2_SUPERNOVA|2 (7.82, p 0.00) |
| W3 | -1.12 | -1.90 | -1.08 | -36.7% | -99.0% | -98% | -1.05 | -1.24 | 1/9 | fail | 42% | W3_RSPLITLONG|2 (-0.55, p 0.03) |
| W4 | -1.63 | -1.07 | -1.85 | -33.5% | -97.4% | -97% | -1.52 | -1.81 | 0/9 | fail | 100% | W4_DEFICLONG|1 (-0.65, p 0.99) |
| W5 | -2.18 | -1.94 | -2.31 | -21.1% | -87.6% | -88% | -2.14 | -2.25 | 0/9 | fail | 65% | W5_OFFERBOUNCE|2 (-1.82, p 0.93) |
| W6 | -2.32 | -1.79 | -2.57 | -70.8% | -100.0% | -100% | -2.26 | -2.42 | 0/9 | fail | 15% | W6_CRASHBOUNCE|0 (-2.10, p 1.00) |
| W9 | -0.87 | -1.12 | -0.91 | -5.0% | -43.3% | -36% | -0.80 | -1.10 | 7/9 | fail | 3% | W9_OFFSPIKE|1 (-0.74, p 0.00) |
| W14 | -0.92 | -0.06 | -1.14 | -1.8% | -19.7% | -15% | -0.80 | -1.13 | 9/9 | fail | 52% | W14_OFFERDAYSHORT|0 (-0.67, p 0.00) |
| W16 | -0.97 | -1.69 | -0.54 | -12.0% | -70.8% | -68% | -0.85 | -1.34 | 0/9 | fail | 99% | W16_EARNDRIFT|1 (0.67, p 0.00) |
| W7 | 0.48 | -0.89 | 1.48 | 6.4% | -88.8% | +73% | 0.69 | -2.08 | 9/9 | fail | 23% | W7_LOTTERYSHORT|2 (0.49, p 0.00) |
| W8 | -1.50 | -1.07 | -1.85 | -18.2% | -83.2% | -83% | -1.08 | -2.10 | 3/9 | fail | 0% | W8_SRWEEKLY|1 (-1.08, p 0.72) |
| W11 | -0.20 | -0.00 | -0.33 | 0.4% | -25.4% | +4% | -0.20 | -0.20 | 0/9 | fail | 100% | W11_IWMTOM|1 (0.28, p 0.39) |

## 2. Combination (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |
|---|---|---|---|---|---|---|---|---|---|
| COMBO | 4.15 | 16.95 | 3.50 | 30.0% | -18.9% | +906% | 0.00 | 0% | met |

Members by year: 2018: F15, W1, W2; 2019: F1, F3, W2; 2020: F1, F7, W2; 2021: F1, W2; 2022: F1, F7, W2; 2023: F1, F16, F7, W2; 2024: F1, F20, F7, W2; 2025: F7, H2, W2; 2026: H2, W1, W2

COMBO by year: 2018 +12.0%, 2019 +17.8%, 2020 +54.8%, 2021 +6.3%, 2022 +28.3%, 2023 +17.2%, 2024 +15.4%, 2025 +68.6%, 2026 +58.6%

## The gross record and the 2023-07+ segment

| family | WF Sortino gross (no costs) | WF Sortino middle | 2023-07 to 2026-10 middle | CAGR there | max DD there |
|---|---|---|---|---|---|
| F1 | 8.39 | 2.03 | -0.01 | 4.4% | -7.8% |
| F2 | 4.88 | 1.15 | 1.17 | 10.6% | -10.5% |
| F3 | 4.04 | 2.42 | 0.59 | 6.9% | -8.9% |
| F4 | -0.59 | -1.02 | -1.28 | -1.8% | -11.9% |
| F5 | 2.63 | 1.96 | 4.26 | 18.0% | -3.5% |
| F6 | -0.47 | -1.67 | -2.65 | -5.0% | -16.1% |
| F7 | 2.20 | 1.57 | 1.28 | 10.1% | -7.7% |
| F9 | 3.71 | 0.29 | -1.27 | -5.1% | -24.9% |
| F10 | 0.93 | -0.18 | -0.72 | 2.0% | -7.9% |
| F11 | -0.76 | -0.87 | -1.21 | 1.6% | -3.4% |
| F12 | -0.03 | -0.93 | -1.86 | -5.6% | -18.2% |
| F13 | 0.03 | -0.87 | -1.64 | -3.2% | -10.4% |
| F14 | 2.67 | 1.20 | 0.18 | 5.3% | -10.7% |
| F15 | 2.24 | 0.72 | 0.33 | 6.1% | -9.0% |
| F16 | 3.39 | 0.60 | -0.34 | 2.3% | -14.6% |
| F17 | 1.00 | -1.22 | -1.69 | -4.3% | -14.6% |
| F18 | 0.67 | -0.60 | -1.82 | -4.3% | -15.0% |
| F19 | 2.75 | 0.82 | -0.22 | 3.5% | -9.8% |
| F20 | 4.45 | 1.88 | 0.64 | 7.9% | -8.6% |
| F21 | 0.97 | 0.04 | -0.34 | 3.4% | -7.0% |
| G1 | 0.86 | 0.16 | 0.62 | 7.2% | -7.9% |
| G2 | 0.24 | -0.32 | -0.40 | 2.6% | -6.1% |
| G3 | -1.27 | -1.57 | -1.80 | -4.6% | -16.3% |
| G4 | -1.32 | -1.55 | -2.03 | -18.9% | -50.2% |
| G5 | 0.66 | -0.16 | -0.95 | -1.5% | -15.8% |
| G6 | 0.86 | 0.14 | 0.25 | 5.3% | -8.2% |
| G7 | 0.01 | -0.49 | -0.81 | 2.3% | -7.3% |
| G8 | -1.68 | -2.18 | -2.50 | -2.8% | -9.1% |
| G9 | -1.10 | -1.45 | -2.17 | -13.6% | -41.4% |
| H1 | -0.62 | -1.11 | -1.13 | -10.2% | -42.4% |
| H2 | 6.33 | 4.25 | 6.05 | 18.2% | -7.4% |
| W1 | 6.70 | 3.97 | 6.43 | 96.8% | -30.6% |
| W2 | 4.93 | 3.67 | 4.42 | 165.4% | -59.5% |
| W3 | 0.33 | -1.12 | -0.63 | -45.3% | -92.5% |
| W4 | -0.98 | -1.63 | -2.26 | -49.8% | -89.8% |
| W5 | -2.06 | -2.18 | -2.35 | -24.0% | -61.1% |
| W6 | -2.13 | -2.32 | -2.86 | -88.7% | -99.9% |
| W9 | -0.60 | -0.87 | -0.56 | 2.4% | -8.1% |
| W14 | -0.50 | -0.92 | -1.18 | -4.1% | -15.2% |
| W16 | -0.50 | -0.97 | -0.57 | -4.3% | -35.1% |
| W7 | 3.29 | 0.48 | 1.93 | 67.3% | -58.6% |
| W8 | -0.55 | -1.50 | -1.93 | -17.7% | -48.2% |
| W11 | -0.20 | -0.20 | -0.72 | -2.6% | -25.4% |

COMBO18 over 2023-07-01 to 2026-10-16: Sortino 9.42, CAGR 43.4%, max DD -18.4%.
Pre-registered criterion (walk-forward >= 4, halves >= 3, PBO < 20%, 2023-07+ >= 3): met.

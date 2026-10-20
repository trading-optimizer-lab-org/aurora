# v17 results: independent streams (design period)

GitHub run 39419245244 (2026-10-20; the report job was rerun after a GitHub rate limit on the artifact
downloads): 300 shards x 4 processes, 4,576 of 4,576 units (v14-v17), no errors. Pre-registered in
[V17_PREREGISTRATION.md](V17_PREREGISTRATION.md). Design 2016-01 to 2023-06 only. The quoted-spread cost study
(section 1 of the pre-registration) runs separately.

## Summary

- **One new independent stream passes the gate: N3 `EARNGO`** (liquid stocks, an earnings 8-K the session before or
  that day and a gap of 4% or more; trade with the gap on the break of the 5-minute range, exit at the close):
  walk-forward Sortino **3.09** (4.46 in 2018-2020, 1.69 in 2021-2023H1), 18.4% a year, drawdown -11.8%, placebo
  6 of 6 years, PBO 14%, spreads x2 1.15, daily correlation with S1 **0.00**.
- **N4 `OPENFADE`** (short small-cap no-news gaps of 50% or more at the open) 4.29 (8.76 / 2.16), 11.5% a year,
  drawdown -4.3%, but placebo 3 of 6 (gate failed) and correlation 0.43 with S1: another form of the gap fade.
  N6 `PMFADE` 2.63 (fails the gate, correlation 0.39).
- **Failed:** liquid no-news fades (N1, 0.05) and bounces (N2, -1.40), late small-cap fades (N5 0.72), offering-day
  shorts (N7 -1.20), halt trades (N8 -1.20), index gap fades (N9 -0.11), VIX spikes (N10 -0.35), weekly reversals
  (N11 0.20), sector reversal (N12 0.36).
- **COMBO17** (v14-v17 families, design only) 8.56 (10.10 / 6.45), 12.9% a year, drawdown -2.9%, PBO 0%. It is
  built mostly on the same small-cap gap fades whose frozen versions failed the sealed test (COMBO16 0.46 over
  2023-07 to 2026-10), so this design number should not be taken as an estimate of the future.

## Cost study: quoted spreads of the gap-fade trades (design period)

10417 trades; entry quotes found for 10415, exit quotes for 10405.

| raw price | trades | table half-spread | measured at entry (median) | measured at exit (median) |
|---|---|---|---|---|
| 10-20 | 1629 | 0.10% | 0.27% | 0.21% |
| 2-5 | 4320 | 0.40% | 0.24% | 0.26% |
| 5-10 | 2471 | 0.20% | 0.24% | 0.24% |
| <2 | 1997 | 0.75% | 0.39% | 0.40% |

| stream | walk-forward Sortino, table costs | measured costs | CAGR measured | max DD measured |
|---|---|---|---|---|
| S1 | 6.55 | 6.48 | 18.8% | -6.4% |
| B8R1 | 5.50 | 5.91 | 23.3% | -6.0% |

Run 39419245445. The quoted half-spreads of these trades are below the price-tier table under $5, close to it at $5-10 (0.24% against 0.20%) and about twice it at $10-20; with each trade's own measured cost S1 makes 6.48 and B8R1 5.91 over the design period, so the spread table did not flatter them, and spreads are not why they failed the sealed test.

## Full report

Units 4576 of 4576; errors 0. Design 2016-01-04 to 2023-06-30 (crypto from 2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | years placebo-ok | gate | PBO | best config (design Sortino, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | 0.07 | 0.44 | -0.37 | 1.7% | -7.8% | +10% | 0.38 | -0.43 | 1/6 | fail | 0% | A1_GAPGO|22 (0.60, p 0.03) |
| A2 | -1.35 | -1.62 | -0.90 | -5.5% | -27.0% | -27% | -1.17 | -1.64 | 0/6 | fail | 23% | A2_PMHIGH|6 (-1.02, p 0.29) |
| A3 | -0.49 | 0.73 | -1.44 | -1.1% | -20.4% | -6% | -0.17 | -0.97 | 4/6 | fail | 44% | A3_VWAPPB|11 (-0.40, p 0.01) |
| A4 | -1.61 | -1.81 | -1.29 | -6.2% | -34.7% | -30% | -1.41 | -1.90 | 0/6 | fail | 17% | A4_DAY2|7 (-1.02, p 0.99) |
| A5 | -1.18 | -0.97 | -1.52 | -3.8% | -23.9% | -19% | -0.99 | -1.49 | 1/6 | fail | 8% | A5_LOWFLOAT|14 (-0.58, p 0.06) |
| A6 | -0.67 | -0.91 | -0.43 | -0.3% | -9.9% | -2% | -0.55 | -0.89 | 3/6 | fail | 50% | A6_HALTUP|1 (-0.65, p 0.00) |
| A7 | -1.41 | -1.78 | -0.87 | -5.1% | -32.1% | -25% | -1.11 | -1.81 | 0/6 | fail | 27% | A7_GAPDOWN|14 (-0.28, p 0.28) |
| B8 | 4.85 | 4.32 | 5.71 | 24.4% | -8.4% | +231% | 11.00 | -1.12 | 3/6 | fail | 11% | B8_GAPFADE|13 (6.74, p 0.00) |
| B9 | -0.34 | -1.03 | 1.58 | 0.5% | -11.3% | +3% | 1.26 | -1.57 | 5/6 | fail | 1% | B9_LATEFADE|2 (-0.62, p 0.00) |
| C15 | 0.58 | 0.80 | 0.21 | 5.7% | -18.7% | +36% | 1.60 | -1.36 | 6/6 | fail | 2% | C15_INPLAY|4 (1.03, p 0.00) |
| C16 | 0.41 | 0.04 | 1.79 | 4.9% | -26.6% | +30% | 0.41 | 0.41 | 0/6 | fail | 0% | C16_NOISE|3 (0.12, p 0.30) |
| C17 | -0.28 | 0.17 | -0.89 | 0.6% | -14.8% | +3% | -0.28 | -0.28 | 6/6 | fail | 42% | C17_LETFFLOW|5 (-0.15, p 0.00) |
| B10 | 0.70 | -0.51 | 1.22 | 7.5% | -36.0% | +48% | 1.77 | -0.60 | 6/6 | fail | 55% | B10_OVERNIGHT|0 (0.46, p 0.00) |
| B11 | 1.75 | 4.33 | -0.05 | 19.3% | -42.3% | +164% | 2.85 | 0.00 | 6/6 | pass | 13% | B11_FIRSTRED|4 (3.97, p 0.00) |
| B12 | 1.59 | 1.65 | 1.50 | 31.8% | -35.3% | +355% | 2.50 | -0.09 | 6/6 | pass | 22% | B12_FADE|7 (4.88, p 0.00) |
| B13 | 0.50 | 1.79 | 0.21 | 7.6% | -52.6% | +50% | 1.10 | -0.72 | 6/6 | fail | 0% | B13_DILUTION|0 (1.06, p 0.00) |
| B14 | -1.61 | -1.86 | -1.23 | -13.6% | -58.3% | -55% | -1.12 | -2.09 | 0/6 | fail | 35% | B14_DELIST|0 (-1.66, p 0.28) |
| C18 | -0.65 | -0.49 | -0.80 | -12.4% | -64.4% | -52% | 0.23 | -1.68 | 5/6 | fail | 79% | C18_SMALLNIGHT|1 (2.67, p 0.00) |
| C19 | 0.62 | 0.31 | 1.15 | 10.1% | -52.6% | +69% | 0.64 | 0.58 | 1/6 | fail | 0% | C19_PEAD|5 (0.79, p 0.04) |
| C20 | 0.54 | 1.21 | -0.12 | 8.4% | -44.8% | +56% | 0.64 | 0.35 | 5/6 | fail | 42% | C20_INSIDER|0 (0.82, p 0.02) |
| C21 | -0.32 | 0.07 | -0.78 | -9.0% | -56.6% | -41% | -0.25 | -0.47 | 2/6 | fail | 27% | C21_ACTIVIST|0 (0.15, p 0.59) |
| C22 | -0.30 | 0.11 | -0.58 | -1.6% | -24.3% | -9% | -0.30 | -0.32 | 1/6 | fail | 56% | C22_RUSSELL|3 (0.06, p 0.22) |
| D23 | 0.26 | -0.14 | 0.67 | 3.2% | -42.0% | +19% | 0.26 | 0.26 | 5/6 | fail | 72% | D23_VIXTERM|3 (2.43, p 0.00) |
| D24 | 0.41 | 0.63 | 0.06 | 3.7% | -8.8% | +22% | 0.41 | 0.41 | 0/6 | fail | 47% | D24_TOM|1 (1.31, p 0.07) |
| D25 | 1.75 | 1.36 | 2.95 | 5.9% | -5.7% | +37% | 1.75 | 1.75 | 5/6 | pass | 18% | D25_MONTHEND|1 (2.53, p 0.00) |
| D26 | 0.97 | 0.73 | 1.47 | 10.7% | -31.5% | +74% | 0.97 | 0.97 | 0/6 | fail | 49% | D26_SECTORS|1 (1.62, p 0.00) |
| E27 | 1.30 | 1.83 | 0.87 | 10.3% | -20.6% | +71% | 1.30 | 1.30 | 1/6 | fail | 33% | E27_CTREND|2 (1.20, p 0.10) |
| E28 | 1.67 | 0.63 | 2.76 | 24.3% | -82.0% | +230% | 1.67 | 1.67 | 0/6 | fail | 45% | E28_CXMOM|0 (1.49, p 0.05) |
| E29 | 0.11 | -0.28 | 0.83 | -8.0% | -81.1% | -37% | 0.11 | 0.11 | 3/6 | fail | 13% | E29_CHOURLY|4 (1.82, p 0.00) |
| E30 | 0.58 | 0.57 | 0.60 | 7.1% | -75.6% | +46% | 0.58 | 0.58 | 0/6 | fail | 19% | E30_FUNDING|2 (0.65, p 0.88) |
| B8R1 | 5.50 | 5.96 | 4.86 | 22.4% | -6.6% | +204% | 8.37 | 1.79 | 3/6 | fail | 13% | B8R1_GAPFADE|13 (7.94, p 0.00) |
| B8R2 | 4.60 | 3.89 | 5.96 | 19.1% | -6.6% | +161% | 8.33 | 0.52 | 3/6 | fail | 14% | B8R2_GAPFADE|13 (6.23, p 0.00) |
| AH1 | -0.56 | -1.02 | 0.19 | -6.0% | -44.5% | -29% | -0.32 | -0.97 | 0/6 | fail | 10% | AH1_AHFADE|3 (-0.65, p 0.24) |
| AH2 | 5.83 | 6.32 | 5.24 | 24.3% | -6.6% | +231% | 8.89 | 1.96 | 3/6 | fail | 61% | AH2_B8LATE|10 (8.97, p 0.00) |
| AH3 | -0.36 | -0.63 | -0.04 | -1.8% | -40.7% | -9% | 0.09 | -1.06 | 6/6 | fail | 16% | AH3_EARNAH|3 (0.32, p 0.00) |
| AH4 | -0.31 | 0.16 | -0.54 | -22.3% | -86.7% | -75% | -0.18 | -0.56 | 0/6 | fail | 20% | AH4_NIGHTPM|3 (-0.45, p 0.10) |
| S1 | 6.55 | 7.93 | 5.06 | 19.1% | -6.3% | +161% | 9.51 | 2.72 | 6/6 | pass | 0% | S1_B8NEWS|5 (8.50, p 0.00) |
| S2 | 3.76 | 3.20 | 4.90 | 10.9% | -4.6% | +76% | 5.08 | 1.80 | 6/6 | pass | 46% | S2_B8SHELF|3 (4.93, p 0.00) |
| S3 | 3.39 | 5.21 | 2.24 | 8.7% | -4.3% | +58% | 4.29 | 1.93 | 6/6 | pass | 71% | S3_B8FIRST|1 (3.62, p 0.00) |
| S4 | 0.01 | -0.08 | 0.10 | 1.5% | -13.5% | +8% | 0.51 | -0.78 | 3/6 | fail | 29% | S4_PARABOLIC|1 (0.25, p 0.00) |
| S5 | 2.89 | 15.32 | 0.40 | 41.9% | -39.9% | +582% | 6.11 | -0.44 | 6/6 | pass | 0% | S5_BACKSIDE|0 (2.57, p 0.00) |
| S6 | -0.79 | -1.23 | -0.58 | -2.5% | -18.6% | -13% | -0.36 | -1.32 | 2/6 | fail | 75% | S6_GAPDOWN|1 (0.03, p 0.01) |
| L1 | -1.10 | -1.32 | -0.76 | -4.3% | -32.6% | -21% | -0.87 | -1.42 | 0/6 | fail | 13% | L1_NEWSGO|7 (-0.47, p 0.62) |
| L2 | -0.71 | -0.71 | -1.41 | -0.5% | -13.5% | -2% | -0.41 | -1.18 | 0/6 | fail | 30% | L2_PANIC|1 (1.41, p 0.00) |
| L3 | -1.57 | -1.40 | -1.73 | -4.6% | -23.3% | -23% | -1.42 | -1.81 | 0/6 | fail | 52% | L3_R2G|1 (-1.23, p 0.99) |
| L4 | -2.02 | -1.42 | -2.57 | -25.6% | -81.8% | -80% | -1.91 | -2.19 | 0/6 | fail | 40% | L4_MICROPB|3 (-1.51, p 0.97) |
| L5 | 0.52 | 1.18 | -0.43 | 2.5% | -4.5% | +15% | 0.91 | -0.14 | 6/6 | fail | 74% | L5_PMHOD|1 (0.47, p 0.01) |
| S7 | 2.58 | 7.55 | 0.77 | 22.8% | -31.0% | +208% | 3.33 | 1.32 | 6/6 | pass | 0% | S7_DAY2FADE|1 (2.98, p 0.00) |
| S8 | -0.81 | 1.21 | -1.40 | -13.2% | -65.6% | -54% | -0.67 | -1.05 | 5/6 | fail | 0% | S8_RETAIL|0 (-0.71, p 0.06) |
| S9 | -0.33 | -0.97 | 0.43 | -7.4% | -73.3% | -34% | -0.27 | -0.43 | 6/6 | fail | 25% | S9_OFFERSPIKE|0 (-0.34, p 0.00) |
| S10 | -0.64 | -0.99 | -0.07 | -8.7% | -66.6% | -39% | -0.56 | -0.78 | 6/6 | fail | 59% | S10_RSPLIT|1 (-0.42, p 0.00) |
| S11 | -1.59 | -1.86 | -1.18 | -30.5% | -88.4% | -86% | -1.55 | -1.66 | 3/6 | fail | 43% | S11_DEFICIENCY|0 (-1.47, p 0.81) |
| L8 | -0.93 | -0.54 | -1.57 | -33.4% | -93.3% | -89% | -0.68 | -1.34 | 5/6 | fail | 53% | L8_NEWSDRIFT|3 (-0.94, p 0.00) |
| L6 | -0.63 | -0.47 | -0.84 | -29.2% | -88.7% | -85% | -0.46 | -0.94 | 0/6 | fail | 46% | L6_MAXREV|2 (-0.75, p 0.99) |
| L7 | -0.62 | -0.16 | -1.46 | -6.5% | -37.8% | -31% | -0.26 | -1.21 | 0/6 | fail | 0% | L7_SHORTRATIO|0 (-0.34, p 0.51) |
| N1 | 0.05 | -0.71 | 1.04 | 1.2% | -37.3% | +7% | 0.52 | -0.68 | 1/6 | fail | 4% | N1_LIQFADE|2 (0.06, p 0.03) |
| N2 | -1.40 | -1.33 | -1.51 | -16.6% | -63.3% | -63% | -1.17 | -1.78 | 2/6 | fail | 2% | N2_LIQBOUNCE|2 (-1.07, p 0.58) |
| N3 | 3.09 | 4.46 | 1.69 | 18.4% | -11.8% | +153% | 4.40 | 1.15 | 6/6 | pass | 14% | N3_EARNGO|0 (3.21, p 0.00) |
| N4 | 4.29 | 8.76 | 2.16 | 11.5% | -4.3% | +82% | 5.04 | 3.00 | 3/6 | fail | 44% | N4_OPENFADE|1 (3.96, p 0.01) |
| N5 | 0.72 | 1.65 | -0.49 | 2.4% | -2.4% | +14% | 1.25 | -0.14 | 4/6 | fail | 61% | N5_LATEFADE|1 (0.64, p 0.00) |
| N6 | 2.63 | 4.79 | 1.05 | 9.5% | -7.7% | +65% | 3.29 | 1.52 | 3/6 | fail | 14% | N6_PMFADE|0 (3.13, p 0.01) |
| N7 | -1.20 | -1.66 | -0.91 | -1.5% | -12.9% | -8% | -0.84 | -1.68 | 0/6 | fail | 40% | N7_OFFERDAY|0 (-1.33, p 0.75) |
| N8 | -1.20 | -0.81 | -1.77 | -0.4% | -5.3% | -2% | -1.06 | -1.42 | 0/6 | fail | 83% | N8_HALTDOWN|1 (0.13, p 0.00) |
| N9 | -0.11 | -0.14 | -0.06 | 0.3% | -19.1% | +2% | -0.11 | -0.11 | 1/6 | fail | 13% | N9_IDXGAP|7 (-0.02, p 0.14) |
| N10 | -0.35 | -0.39 | -0.30 | -0.9% | -30.6% | -5% | -0.35 | -0.35 | 1/6 | fail | 45% | N10_VIXSPIKE|1 (-0.12, p 0.77) |
| N12 | 0.36 | 0.38 | 0.34 | 5.0% | -57.2% | +31% | 0.36 | 0.36 | 0/6 | fail | 67% | N12_SECTORREV|1 (0.53, p 0.67) |
| N11 | 0.20 | 0.71 | -0.28 | -3.8% | -79.1% | -19% | 0.33 | -0.05 | 0/6 | fail | 13% | N11_WEEKREV|2 (0.31, p 0.14) |

## 2. Combination (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |
|---|---|---|---|---|---|---|---|---|---|
| COMBO | 8.56 | 10.10 | 6.45 | 12.9% | -2.9% | +94% | 0.00 | 0% | met |

Members by year: 2018: B11, B12, C18, C21, N10, N3, S1, S2, S3, S7; 2019: B11, B12, D25, N3, S1, S2, S3, S7; 2020: B11, B12, C22, N3, S1, S2, S3, S7; 2021: AH2, B11, B12, B8R1, D23, D25, N3, N4, S1, S2, S3, S5, S7; 2022: AH2, B11, B12, B8R1, C18, C20, D23, L5, N3, N4, N6, S1, S2, S3, S5, S7; 2023: AH2, B11, B12, B8R1, D23, D25, N3, N4, N6, S1, S2, S3, S5, S7

COMBO by year: 2018 +11.0%, 2019 +12.3%, 2020 +23.0%, 2021 +15.9%, 2022 +1.5%, 2023 +7.7%

## Daily correlation of every family stream with S1 (2018-2023H1)

B10 -0.08, L5 -0.07, AH1 -0.06, A2 -0.05, C21 -0.05, N11 -0.05, C16 -0.04, L8 -0.04, C17 -0.04, A1 -0.04, A3 -0.04, A7 -0.03, L6 -0.03, S8 -0.03, AH4 -0.03, L7 -0.02, C20 -0.02, L4 -0.02, C19 -0.02, N12 -0.01, L1 -0.01, L2 -0.01, S9 -0.01, L3 -0.01, A4 -0.01, C18 -0.00, D25 -0.00, N3 +0.00, AH3 +0.00, D26 +0.01, S6 +0.01, N10 +0.01, E29 +0.01, S10 +0.01, C22 +0.01, A6 +0.01, B9 +0.02, B13 +0.02, S11 +0.02, A5 +0.02, N2 +0.02, E27 +0.02, N8 +0.02, N7 +0.02, E30 +0.03, C15 +0.03, E28 +0.03, D23 +0.03, N9 +0.03, B11 +0.03, D24 +0.04, B14 +0.05, S7 +0.07, S4 +0.09, B12 +0.14, N1 +0.15, N5 +0.19, S5 +0.21, N6 +0.39, N4 +0.43, S3 +0.47, S2 +0.54, COMBO +0.67, B8R2 +0.81, AH2 +0.82, B8 +0.82, B8R1 +0.83

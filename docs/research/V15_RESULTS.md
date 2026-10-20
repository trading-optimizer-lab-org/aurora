# v15 results: IBKR-calibrated shorts and the after-hours session

GitHub run 39414563648 (2026-10-20): prepare, 300 shards x 4 processes, report over the v14 and v15 parts; 3,584 of
3,584 units, no errors. Data run 39411050195. Pre-registered in [V15_PREREGISTRATION.md](V15_PREREGISTRATION.md)
(with the amendment that replaced iBorrowDesk, which refuses GitHub's servers, by IBKR's own public short-stock
file). Design 2016-01 to 2023-06; the sealed test has not been opened.

## Summary

- **B8 survives IBKR's real availability.** Under R1 (IBKR-like account: no locate fee, no borrow on intraday
  shorts, each short weighted by the share of comparable stocks IBKR could lend), the gap fade `B8R1` made a
  walk-forward Sortino of **5.50** (5.96 in 2018-2020, 4.86 in 2021-2023H1), 22.4% a year, maximum drawdown -6.6%,
  total +204%, positive every year (+25%, +14%, +34%, +21%, +15%, +14% in 2023H1). With half-spreads 1.5x
  (`B8R2`): 4.60, 19.1% a year, -6.6%; with 2x: 1.79.
- **Covering in the after-hours helps a little:** `AH2_B8LATE` (B8 held to 17:00 or 19:55 when not stopped) 5.83,
  24.3% a year, drawdown -6.6%; it is the same trades (correlation 0.96 with B8R1) and its PBO is 61%, so the
  cover time is not a reliable choice.
- **Both still fail the pre-registered gate** on the placebo count (3 of 6 years with p <= 0.05; 4 needed): in the
  early years the training windows are short and random gap-ups shorted at the same minute also earn. The
  placebo p-value of their best configuration over the whole design period is 0.00.
- **The other after-hours ideas fail:** shorting runners that fade in the after-hours (AH1) -0.56, earnings moves in
  the after-hours (AH3) -0.36, short at the close and cover in the next premarket (AH4) -0.31 (drawdown -87%).
- **`COMBO15`** (v14 families with B8 replaced by B8R1, plus v15; families enter each year only on earlier data):
  **2.18** (2.52 / 1.65), 16.9% a year, drawdown -15.3%, total +136%, PBO 0%. Not 4: B8R1 and AH2 only enter from
  2021, when their placebo p-value on earlier data first reaches 0.05.

## IBKR availability (snapshot of 2026-10-20 applied to the small-cap event days of the 60 sessions before)

1,651 events; 78% borrowable (at least $10,000 worth or 1,000 shares available). Cells (p = share borrowable;
fee = median annual borrow fee of the borrowable ones):

| raw price | shares unknown | < 10M | 10-50M | > 50M |
|---|---|---|---|---|
| < $2 | 0.48 (65%) | 0.90 (86%) | 0.92 (75%) | 0.85 (81%) |
| $2-5 | 0.68 (53%) | 0.87 (126%) | 0.89 (96%) | 0.88 (99%) |
| $5-10 | 0.70 (22%) | 0.86 (153%) | 0.84 (47%) | 0.97 (56%) |
| $10-20 | 0.72 (13%) | 0.81 (117%) | 0.92 (11%) | 0.94 (0.5%) |

Caveats: a single snapshot of today's survivors, a few weeks after the events; delisted stocks (probably harder to
borrow) are not in it, so the availability is probably still generous; fees matter only for overnight shorts.

## Full report

Units 3584 of 3584; errors 0. Design 2016-01-04 to 2023-06-30 (crypto from 2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.

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

## 2. Combination (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |
|---|---|---|---|---|---|---|---|---|---|
| COMBO | 2.18 | 2.52 | 1.65 | 16.9% | -15.3% | +136% | 0.00 | 0% | not met |

Members by year: 2018: B11, B12, C18, C21; 2019: B11, B12, D25; 2020: B11, B12, C22; 2021: AH2, B11, B12, B8R1, D23, D25; 2022: AH2, B11, B12, B8R1, C18, C20, D23; 2023: AH2, B11, B12, B8R1, D23, D25

COMBO by year: 2018 +7.0%, 2019 +18.7%, 2020 +47.5%, 2021 +12.6%, 2022 -7.1%, 2023 +20.3%

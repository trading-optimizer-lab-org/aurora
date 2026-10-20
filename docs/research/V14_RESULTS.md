# v14 results: many independent ideas on survivorship-free data

GitHub run 39399894228 (2026-10-20): prepare, 300 shards x 4 processes, report; 2,752 of 2,752 units (344
configurations x 8 placebo blocks), no errors. Data run 39399187834. Pre-registered in
[V14_PREREGISTRATION.md](V14_PREREGISTRATION.md). Design 2016-01 to 2023-06; the sealed test (2023-07 to 2026-10)
has not been opened. Target: monthly Sortino 4.

## Summary

- **The design criterion is not met.** The pre-registered combination (`COMBO`, families chosen each year on
  earlier data only) made a walk-forward Sortino of **2.00** over 2018-2023H1 (2.52 in 2018-2020, 1.13 in
  2021-2023H1), 16.0% a year, maximum drawdown -18.4%, total +126%, PBO 0%, deflated Sharpe 0.00.
- **One family reaches 4 on its own: B8 `GAPFADE`** (short small caps that open 30-50% or more above the prior
  close when they break the low of the first 5 minutes; cover at the close). Walk-forward Sortino **4.85** (4.32 in
  2018-2020, 5.71 in 2021-2023H1), 24.4% a year, drawdown -8.4%, total +231%, positive every year (+30%, +13%,
  +30%, +20%, +25%, +16% in 2023H1), correlation about 0 with every other family. It failed the pre-registered
  gate on the placebo count (3 of 6 years with p <= 0.05; 4 needed) and is very cost-sensitive: 11.0 at the low
  costs, -1.12 at the high ones.
- **The B8 edge is real before costs and sits everywhere** (diagnostic below): the average trade gains 4.5-6.6%
  gross in every price band, every shares-outstanding band and every year. What decides it is the cost of the
  short: with a 1% locate fee it is 2.77, with 2% it is 0.22; with spreads 1.5x it is 3.0. The high scenario fails
  mostly because it forbids shorts in stocks whose shares outstanding are unknown (a third of the weight and the
  best bucket) or below 10 million. Historical borrow availability and fees are not in any free data set, so
  whether B8 can be traded is not settled by this backtest.
- **Three families pass the gate:** B11 `FIRSTRED` 1.75 (4.33 then -0.05: it stopped working after 2020), B12
  `FADE` 1.59 (1.65 / 1.50; 31.8% a year, drawdown -35%; -0.09 at high costs), D25 `MONTHEND` 1.75 (1.36 / 2.95;
  5.9% a year, drawdown -5.7%, the steadiest stream found).
- **Published ideas that did not survive costs and walk-forward:** stocks-in-play ORB (C15, Zarattini and Aziz)
  0.58, SPY/QQQ intraday momentum and noise area (C16) 0.41, the leveraged-ETF flow (C17) -0.28, PEAD 0.62,
  insider clusters 0.54, activists -0.32, Russell additions -0.30, VIX term structure 0.26, every small-cap long
  intraday idea (A1-A7) between -1.61 and 0.07, crypto trend 1.30 and crypto momentum 1.67 (drawdown -82%).
- Data: 23,514 of 23,931 FINRA symbols have Alpaca bars (95-99% of FINRA symbol-days each year); 8,722 symbols
  that were liquid at some point are delisted or unknown to Alpaca today, so this universe really contains the
  losers. Alpaca has no bars before 2016, so the first weeks of 2016 have no history for the rolling filters.

## B8 diagnostic (after the run, not pre-registered; run 39402925095, `scripts/run_v14_diag.py`)

The walk-forward picks of the run (config 0 in 2018-2020: gap >= 30%, PMV >= $250k; 1 in 2021: PMV >= $1M; 13 in
2022-2023: gap >= 50%, PMV >= $1M; all break of the 5-minute low, cover at the close), each cost changed alone:

| costs | Sortino 2018-2023H1 | CAGR | max DD |
|---|---|---|---|
| middle, as run (spreads by price tier, locate 0.5% below $10) | 4.85 | 24.4% | -8.4% |
| spreads x0.5 | 7.29 | 31.5% | -7.6% |
| spreads x1.5 | 3.00 | 17.6% | -11.0% |
| spreads x2 | 1.62 | 11.2% | -14.1% |
| no locate fee | 7.68 | 32.6% | -7.5% |
| locate 1% below $10 | 2.77 | 16.7% | -11.3% |
| locate 2% below $10 | 0.22 | 2.7% | -25.2% |
| locate 3% below $10 | -1.10 | -9.6% | -52.3% |
| locate 1% on every trade | 1.78 | 12.3% | -13.6% |
| only stocks >= $2 with >= 10M known shares | 0.78 | 4.6% | -10.9% |
| the same with locate 1.5% / 0.5% | -0.62 | -2.1% | -23.8% |
| high scenario (spreads x2, locate 1.5% / 0.5%, the rule) | -1.12 | -5.9% | -34.9% |

Trades of the last pick (gap >= 50%, PMV >= $1M), 2018-2023H1, middle costs:

| group | trades | mean net | profit factor | mean gross | share of weight |
|---|---|---|---|---|---|
| price < $2 | 220 | +1.8% | 1.28 | +4.5% | 15% |
| $2-5 | 519 | +5.0% | 1.88 | +6.6% | 37% |
| $5-10 | 326 | +3.5% | 1.51 | +4.6% | 28% |
| $10-20 | 192 | +5.9% | 1.98 | +6.2% | 20% |
| shares unknown | 458 | +6.1% | 2.09 | +7.5% | 33% |
| < 10M shares | 211 | +4.6% | 1.68 | +6.1% | 13% |
| 10-50M | 373 | +2.3% | 1.34 | +3.8% | 31% |
| > 50M | 215 | +3.0% | 1.52 | +4.4% | 23% |
| 2018 / 2019 / 2020 | 92 / 139 / 422 | +7.1% / +3.4% / +3.8% | 2.63 / 1.50 / 1.53 | | |
| 2021 / 2022 / 2023H1 | 278 / 172 / 154 | +3.5% / +4.9% / +4.7% | 1.57 / 2.00 / 1.83 | | |

Daily correlations of the main streams over 2018-2023H1: B8 with B11 -0.00, B12 0.16, D25 -0.02, C15 -0.00,
crypto 0.02; PEAD, insiders and sectors 0.58-0.78 with each other.

## Full report

Units 2752 of 2752; errors 0. Design 2016-01-04 to 2023-06-30 (crypto from 2018); walk-forward from 2018. Middle costs unless stated. Target: COMBO monthly Sortino 4.

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

## 2. Combination (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | DSR | PBO | design criterion |
|---|---|---|---|---|---|---|---|---|---|
| COMBO | 2.00 | 2.52 | 1.13 | 16.0% | -18.4% | +126% | 0.00 | 0% | not met |

Members by year: 2018: B11, B12, C18, C21; 2019: B11, B12, D25; 2020: B11, B12, C22; 2021: B11, B12, B8, D23, D25; 2022: B11, B12, B8, C18, C20, D23; 2023: B11, B12, B8, D23, D25

COMBO by year: 2018 +7.0%, 2019 +18.7%, 2020 +47.5%, 2021 +9.6%, 2022 -9.4%, 2023 +21.7%

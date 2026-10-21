# v20 results: small caps, a wide grid under realistic costs (38,762 configurations)

Pre-registered in [V20_PREREGISTRATION.md](V20_PREREGISTRATION.md). GitHub run 39474595370 (2026-10-20, 18:25-20:33
UTC): canary, 600 shards x 4 processes, report; 38,762 of 38,762 configurations, 200 placebos each, no errors. R3
costs (realistic) in the middle scenario.

## Summary

- **The pre-registered criterion is met.** `COMBO20`: walk-forward monthly Sortino **7.70** (11.00 in 2018-2020,
  **6.49** in 2021-2026), 12.7% a year, maximum drawdown **-2.9%**, PBO 0%, 2023-07+ **5.84**; positive every year
  (+7.5%, +12.2%, +19.4%, +8.8%, +7.3%, +10.3%, +10.0%, +21.9%, +14.8% to October 2026). Deflated Sharpe 0.00.
- **Families that work** (all short small caps after a gap or a run, held for days): RU run-up shorts 5.80 (38.7% a
  year, drawdown -21%, 2023-07+ 8.70), GX gap fade with filters 4.41, PM premarket fade 4.38, GF gap fade 3.63, RF
  runner fade 2.91, NS overnight short 1.59. **Longs fail again** (LG -0.57, CB -0.49, MO -0.71, GD -1.01), as do
  day-two fades (D2 -0.81) and event shorts (EV -0.38).
- **Costs matter more than anything**: gross records (no costs) 8-15 for the gap families, middle 3.6-4.4, high costs
  (spreads x2, borrow x3) 0.5-1.1. RU holds up best at high costs (2.18).
- **False discovery rate:** 24,872 of 38,762 configurations beat their own placebos after Benjamini-Hochberg, but
  that count includes configurations that lose money: the placebo (a random stock of the same scope with the same
  timing and exits) loses more than zero under these costs, so beating it is a weak bar. It shows the setups select
  better stocks than chance, not that every configuration is tradable.

## Full report

Configurations evaluated 38762 of 38762; errors or skipped 0. 200 placebos each. R3 costs (middle) unless stated. Target: COMBO20 monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | gross | years placebo-ok | gate | PBO | best config (design Sortino, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GF | 3.63 | 6.80 | 2.77 | 12.6% | -7.8% | +184% | 4.15 | 0.62 | 10.96 | 7/9 | pass | 0% | GF_GAPFADE|4883 (7.92, p 0.00) |
| GX | 4.41 | 8.12 | 3.40 | 13.4% | -5.7% | +201% | 5.16 | 1.12 | 13.75 | 5/9 | fail | 0% | GX_GAPFILTER|437 (7.50, p 0.00) |
| RF | 2.91 | 9.57 | 2.33 | 15.1% | -8.6% | +244% | 3.47 | 0.52 | 8.37 | 9/9 | pass | 0% | RF_RUNFADE|366 (5.62, p 0.00) |
| D2 | -0.81 | -0.12 | -1.11 | 0.9% | -7.9% | +8% | -0.64 | -1.28 | 0.05 | 5/9 | fail | 9% | D2_DAY2FADE|41 (0.55, p 0.06) |
| PM | 4.38 | 8.08 | 3.80 | 13.3% | -6.1% | +200% | 4.99 | 1.09 | 14.87 | 4/9 | fail | 0% | PM_PMFADE|125 (6.02, p 0.00) |
| GD | -1.01 | -2.01 | -0.52 | -0.3% | -15.0% | -3% | -0.76 | -1.58 | 0.47 | 7/9 | fail | 10% | GD_GAPDOWN|751 (0.59, p 0.06) |
| LG | -0.57 | -0.79 | -0.45 | 0.1% | -28.0% | +1% | -0.41 | -0.85 | 0.15 | 2/9 | fail | 7% | LG_GAPGO|322 (0.31, p 0.03) |
| RU | 5.80 | 4.56 | 6.32 | 38.7% | -21.2% | +1675% | 6.07 | 2.18 | 9.64 | 9/9 | pass | 0% | RU_RUNUP|10897 (10.28, p 0.00) |
| NS | 1.59 | 1.72 | 1.55 | 9.3% | -13.8% | +119% | 1.76 | 0.32 | 2.86 | 9/9 | pass | 10% | NS_NIGHTSHORT|666 (6.10, p 0.00) |
| EV | -0.38 | -1.08 | 0.18 | -0.6% | -34.5% | -5% | -0.25 | -1.24 | 0.70 | 9/9 | fail | 0% | EV_EVENTSHORT|53 (0.63, p 0.00) |
| CB | -0.49 | -1.25 | 0.32 | -5.2% | -60.1% | -37% | -0.41 | -0.64 | -0.29 | 9/9 | fail | 6% | CB_CRASHLONG|735 (0.82, p 0.00) |
| MO | -0.71 | -1.30 | -0.09 | -6.3% | -61.1% | -43% | -0.60 | -0.92 | -0.28 | 7/9 | fail | 16% | MO_MOMOLONG|665 (0.51, p 0.00) |

## 2. COMBO20 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO20 | 7.70 | 11.00 | 6.49 | 12.7% | -2.9% | +185% | 5.84 | 0.00 | 0% | met |

Members by year: 2018: LG, NS, RF, RU; 2019: NS, RF, RU; 2020: GF, GX, NS, RF, RU; 2021: D2, GF, NS, RF, RU; 2022: GF, NS, PM, RF, RU; 2023: GF, GX, NS, PM, RF, RU; 2024: GF, GX, NS, RF, RU; 2025: GF, GX, NS, PM, RF, RU; 2026: GF, GX, NS, PM, RF, RU

COMBO20 by year: 2018 +7.5%, 2019 +12.2%, 2020 +19.4%, 2021 +8.8%, 2022 +7.3%, 2023 +10.3%, 2024 +10.0%, 2025 +21.9%, 2026 +14.8%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| GF | 2.09 | 13.0% | -6.8% |
| GX | 2.29 | 12.3% | -5.7% |
| RF | 1.66 | 15.4% | -8.6% |
| D2 | -1.64 | -0.3% | -7.9% |
| PM | 2.73 | 14.5% | -6.1% |
| GD | -0.89 | 1.5% | -7.0% |
| LG | 0.09 | 4.4% | -13.9% |
| RU | 8.70 | 83.9% | -21.2% |
| NS | 1.12 | 11.1% | -13.8% |
| EV | 0.50 | 7.7% | -10.7% |
| CB | 0.71 | 9.4% | -16.9% |
| MO | -1.31 | -2.1% | -12.7% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| GF | 16.5 | +4.9% | 62% | -170% |
| GX | 15.6 | +4.2% | 58% | -170% |
| RF | 29.5 | +3.2% | 59% | -134% |
| D2 | 4.6 | +1.1% | 50% | -113% |
| PM | 13.1 | +5.0% | 59% | -170% |
| GD | 5.9 | +0.3% | 42% | -47% |
| LG | 3.4 | +0.2% | 28% | -50% |
| RU | 5.4 | +18.0% | 78% | -397% |
| NS | 4.7 | +6.2% | 69% | -160% |
| EV | 4.9 | -0.5% | 64% | -449% |
| CB | 5.3 | -1.1% | 43% | -88% |
| MO | 5.5 | -2.0% | 31% | -75% |

## 5. False discovery rate over all configurations (Benjamini-Hochberg, q = 5%)

Whole-period Sortino of each configuration against its 200 placebos; p empirical (rank) and p from the placebos' normal z-score. 24872 of 38762 configurations survive with the empirical p, 25542 with the z-score p.

| family | configurations | survive (empirical) | survive (z) | best three by z (Sortino, z) |
|---|---|---|---|---|
| GF | 13860 | 5723 | 6129 | GF_GAPFADE|6879 (3.78, 12.8); GF_GAPFADE|4883 (7.92, 11.7); GF_GAPFADE|11379 (-0.22, 10.8) |
| GX | 972 | 629 | 667 | GX_GAPFILTER|437 (7.50, 15.3); GX_GAPFILTER|467 (6.92, 14.6); GX_GAPFILTER|410 (6.61, 14.4) |
| RF | 1344 | 1298 | 1308 | RF_RUNFADE|356 (3.31, 80.0); RF_RUNFADE|404 (3.28, 72.2); RF_RUNFADE|692 (3.42, 65.4) |
| D2 | 864 | 232 | 260 | D2_DAY2FADE|516 (-0.41, 6.5); D2_DAY2FADE|603 (0.38, 6.3); D2_DAY2FADE|517 (-0.15, 6.0) |
| PM | 768 | 284 | 305 | PM_PMFADE|325 (2.08, 8.6); PM_PMFADE|749 (-0.25, 8.1); PM_PMFADE|717 (0.09, 7.5) |
| GD | 864 | 222 | 205 | GD_GAPDOWN|57 (-0.25, 7.0); GD_GAPDOWN|24 (-0.82, 7.0); GD_GAPDOWN|21 (-0.48, 6.7) |
| LG | 1080 | 18 | 25 | LG_GAPGO|1046 (-1.29, 3.5); LG_GAPGO|1036 (-1.94, 3.3); LG_GAPGO|281 (-0.60, 3.3) |
| RU | 14400 | 14118 | 14194 | RU_RUNUP|10297 (6.90, 48.7); RU_RUNUP|10875 (9.22, 47.1); RU_RUNUP|10897 (10.28, 46.6) |
| NS | 1280 | 1280 | 1280 | NS_NIGHTSHORT|402 (4.22, 58.8); NS_NIGHTSHORT|323 (3.77, 56.8); NS_NIGHTSHORT|322 (3.77, 48.6) |
| EV | 360 | 282 | 299 | EV_EVENTSHORT|53 (0.63, 18.5); EV_EVENTSHORT|51 (0.36, 16.1); EV_EVENTSHORT|47 (0.18, 15.1) |
| CB | 2160 | 628 | 683 | CB_CRASHLONG|1441 (0.26, 18.8); CB_CRASHLONG|1453 (0.26, 18.5); CB_CRASHLONG|1811 (0.15, 17.9) |
| MO | 810 | 158 | 187 | MO_MOMOLONG|641 (0.20, 13.3); MO_MOMOLONG|647 (0.38, 13.0); MO_MOMOLONG|665 (0.51, 12.8) |

## 6. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| GF | gap | 0.15 -0.68 (0) / 0.2 -0.39 (3) / 0.3 -0.06 (0) / 0.4 0.01 (6) / 0.5 -0.07 (0) / 0.75 -0.28 (0) / 1.0 -0.62 (0) |
| GF | band | 1-2 -1.02 (0) / 2-5 0.82 (9) / 5-10 0.72 (0) / 10-20 -0.59 (0) |
| GF | trig | open -0.49 (0) / orl1 -0.56 (0) / orl5 -0.20 (0) / orl15 -0.26 (5) / orl30 -0.45 (1) / orl60 -0.69 (0) / vwaploss 0.07 (0) / t15 -0.10 (2) / t30 -0.26 (1) / t60 -0.27 (0) / t120 -0.49 (0) |
| GF | stop | hod -0.69 (0) / pct10 -0.31 (0) / pct20 0.10 (4) / pct30 -0.10 (5) / pct50 -0.66 (0) |
| GF | exit | close -1.02 (0) / r2 -1.15 (0) / trail20 -1.71 (0) / next_open -0.06 (0) / d2 0.10 (1) / d3 0.23 (5) / d4 0.19 (1) / d5 0.26 (2) / d7 0.28 (0) |
| GX | gap | 0.3 0.53 (9) / 0.5 0.33 (0) |
| GX | band | 1-2 -0.81 (0) / 2-5 0.81 (7) / 5-20 1.32 (2) |
| GX | news | any 0.65 (7) / none 0.16 (2) |
| GX | pmv | 0.0 0.42 (7) / 1000000.0 0.49 (2) / 5000000.0 0.37 (0) |
| GX | float | any 3.32 (9) / <10M 0.16 (0) / >=10M 0.28 (0) |
| GX | trig | orl15 0.24 (8) / vwaploss 0.53 (0) / t30 0.41 (1) |
| GX | exit | next_open 0.22 (0) / d3 0.48 (9) / d5 0.58 (0) |
| RF | up | 0.4 -0.64 (2) / 0.6 0.21 (5) / 0.8 0.40 (2) / 1.2 0.13 (0) |
| RF | trig | lowerhigh 0.61 (1) / vwaploss 0.86 (7) / hodfail -1.06 (0) / backside 0.28 (0) / t120 0.27 (0) / t180 -0.01 (1) / t240 -0.30 (0) |
| RF | band | 1-2 -0.98 (0) / 2-5 1.14 (9) / 5-10 1.19 (0) / 10-20 -0.14 (0) |
| RF | stop | hod -0.35 (0) / pct20 0.30 (3) / pct30 0.17 (6) |
| RF | exit | close -0.86 (3) / next_open 0.14 (0) / d3 0.38 (5) / d5 0.42 (1) |
| D2 | day1 | 0.5 -1.53 (3) / 1.0 -1.41 (6) / 2.0 -1.68 (0) |
| D2 | trig | open -1.35 (0) / orl5 -1.58 (3) / orl15 -1.68 (1) / orl30 -1.79 (0) / vwaploss -1.38 (5) / t30 -1.63 (0) |
| D2 | band | 1-2 -1.78 (0) / 2-5 -1.81 (1) / 5-10 -1.34 (1) / 10-20 -1.13 (7) |
| D2 | stop | hod -1.51 (1) / pct20 -1.47 (8) / pct30 -1.64 (0) |
| D2 | exit | close -1.79 (0) / next_open -1.64 (7) / d3 -1.48 (2) / d5 -1.38 (0) |
| PM | gap | 0.3 0.22 (9) / 0.6 -0.25 (0) |
| PM | drop | 0.05 0.29 (9) / 0.1 0.21 (0) / 0.2 -0.64 (0) |
| PM | trig | open 0.19 (0) / orl1 -0.10 (0) / orl5 -0.02 (1) / orl15 -0.23 (8) |
| PM | stop | pmh -0.38 (1) / pct20 0.24 (8) |
| PM | exit | close -0.79 (0) / next_open 0.25 (0) / d3 0.30 (7) / d5 0.42 (2) |
| PM | band | 1-2 -1.21 (1) / 2-5 1.15 (7) / 5-10 0.93 (1) / 10-20 -0.19 (0) |
| GD | side | short -1.17 (7) / long -1.73 (2) |
| GD | gap | -0.2 -1.38 (7) / -0.35 -1.46 (2) / -0.5 -1.62 (0) |
| GD | trig | or5 -1.41 (0) / or15 -1.55 (3) / vwap -1.35 (1) / t30 -1.65 (5) |
| GD | band | 1-2 -1.90 (2) / 2-5 -1.42 (0) / 5-10 -1.14 (7) / 10-20 -1.31 (0) |
| GD | stop | ext -1.49 (1) / pct10 -1.34 (8) / pct20 -1.63 (0) |
| GD | exit | close -1.76 (4) / next_open -1.32 (2) / d3 -1.20 (3) |
| LG | gap | 0.2 -1.70 (6) / 0.4 -1.83 (3) / 0.8 -1.89 (0) |
| LG | trig | orh1 -2.21 (0) / orh5 -2.01 (0) / orh15 -1.52 (2) / pmhbreak -1.89 (0) / vwapreclaim -1.67 (1) / hod13 -1.49 (6) |
| LG | band | 1-2 -1.89 (0) / 2-5 -1.83 (1) / 5-10 -1.83 (8) / 10-20 -1.62 (0) |
| LG | stop | lod -1.94 (0) / pct10 -1.76 (8) / pct20 -1.76 (1) |
| LG | exit | close -1.68 (0) / trail20 -1.78 (2) / next_open -1.70 (7) / d3 -1.90 (0) / d5 -1.98 (0) |
| RU | rise | 0.5 -1.77 (0) / 1.0 -1.24 (0) / 1.5 -0.77 (3) / 2.0 -0.39 (0) / 3.0 0.03 (6) / 5.0 -0.10 (0) |
| RU | window | 1 -0.43 (3) / 3 -0.58 (4) / 5 -0.69 (2) / 20 -1.13 (0) |
| RU | trig | open -0.14 (5) / lowclose -1.41 (0) / redclose -1.35 (0) / close_c -0.20 (4) / gapdown -0.33 (0) |
| RU | hold | 2 -0.84 (2) / 3 -0.70 (0) / 5 -0.52 (0) / 10 -0.55 (5) / 20 -0.73 (2) / 30 -0.85 (0) |
| RU | stop | 0.25 -1.46 (0) / 0.5 -1.03 (0) / 1.0 -0.51 (0) / none 0.37 (9) |
| RU | exit | time -0.49 (2) / target30 -0.48 (3) / target50 -0.46 (2) / strength -0.68 (2) / trail30 -1.33 (0) |
| NS | gap | 0.2 0.84 (2) / 0.3 1.15 (7) / 0.5 0.87 (0) / 1.0 -0.08 (0) |
| NS | drop | 0.0 0.73 (0) / 0.05 0.67 (1) / 0.1 0.59 (7) / 0.2 0.39 (1) |
| NS | loc | any 0.72 (1) / low25 0.49 (8) |
| NS | exit | next_open -0.27 (0) / next_close 0.23 (0) / close2 0.77 (5) / close3 0.99 (4) / close5 0.92 (0) |
| NS | band | 1-2 0.40 (0) / 2-5 2.07 (2) / 5-10 1.05 (7) / 10-20 -0.49 (0) |
| NS | stop | none 0.80 (9) / 0.3 0.35 (0) |
| EV | event | offer_spike -0.54 (9) / rsplit -1.42 (0) / deficiency -1.70 (0) / offering -2.15 (0) |
| EV | hold | 3 -1.48 (6) / 5 -1.57 (2) / 10 -1.40 (0) / 20 -1.60 (1) / 40 -1.69 (0) |
| EV | stop | 0.25 -1.79 (0) / 0.5 -1.63 (1) / none -1.33 (8) |
| EV | exit | time -1.60 (1) / target30 -1.55 (8) / target50 -1.58 (0) |
| EV | band | 1-5 -1.05 (9) / 5-20 -1.78 (0) |
| CB | fall | 0.25 -1.67 (1) / 0.4 -1.48 (8) / 0.6 -1.62 (0) |
| CB | news | any -1.60 (3) / none -1.55 (6) |
| CB | trig | close_c -0.81 (7) / open -1.86 (0) / greenclose -1.70 (2) / highclose -1.59 (0) |
| CB | hold | 1 -1.70 (5) / 2 -1.57 (1) / 3 -1.47 (0) / 5 -1.52 (2) / 10 -1.57 (1) |
| CB | stop | 0.2 -1.65 (0) / 0.5 -1.56 (0) / none -1.53 (9) |
| CB | exit | time -1.66 (1) / target20 -1.50 (8) / weak -1.58 (0) |
| CB | band | 1-5 -1.71 (0) / 5-20 -1.48 (9) |
| MO | up | 0.2 -1.55 (2) / 0.5 -1.43 (3) / 1.0 -1.52 (4) |
| MO | trig | open -1.71 (0) / redclose -1.33 (8) / highclose -1.47 (1) |
| MO | hold | 3 -1.47 (6) / 5 -1.45 (1) / 10 -1.57 (0) / 20 -1.52 (0) / 40 -1.50 (2) |
| MO | stop | 0.1 -1.69 (0) / 0.2 -1.43 (3) / 0.3 -1.40 (6) |
| MO | exit | time -1.44 (1) / trail20 -1.60 (4) / ma10 -1.45 (4) |
| MO | band | 1-5 -1.56 (0) / 5-20 -1.45 (9) |

## 7. Latest pick of each family

- GF 2026: GF_GAPFADE|6649 = {'gap': 0.4, 'band': '2-5', 'trig': 'orl30', 'stop': 'pct30', 'exit': 'd5'}
- GX 2026: GX_GAPFILTER|406 = {'gap': 0.3, 'band': '5-20', 'news': 'none', 'pmv': 0.0, 'float': 'any', 'trig': 'orl15', 'exit': 'd3'}
- RF 2026: RF_RUNFADE|690 = {'up': 0.8, 'trig': 'lowerhigh', 'band': '2-5', 'stop': 'pct20', 'exit': 'd3'}
- D2 2026: D2_DAY2FADE|229 = {'day1': 0.5, 'trig': 'vwaploss', 'band': '10-20', 'stop': 'hod', 'exit': 'next_open'}
- PM 2026: PM_PMFADE|125 = {'gap': 0.3, 'drop': 0.05, 'trig': 'orl15', 'stop': 'pct20', 'exit': 'd5', 'band': '2-5'}
- GD 2026: GD_GAPDOWN|131 = {'side': 'short', 'gap': -0.2, 'trig': 't30', 'band': '5-10', 'stop': 'pct10', 'exit': 'd3'}
- LG 2026: LG_GAPGO|322 = {'gap': 0.2, 'trig': 'hod13', 'band': '2-5', 'stop': 'pct10', 'exit': 'next_open'}
- RU 2026: RU_RUNUP|10897 = {'rise': 3.0, 'window': 5, 'trig': 'open', 'hold': 20, 'stop': 'none', 'exit': 'target50'}
- NS 2026: NS_NIGHTSHORT|546 = {'gap': 0.3, 'drop': 0.1, 'loc': 'low25', 'exit': 'close3', 'band': '2-5', 'stop': 'none'}
- EV 2026: EV_EVENTSHORT|14 = {'event': 'offer_spike', 'hold': 3, 'stop': 'none', 'exit': 'target30', 'band': '1-5'}
- CB 2026: CB_CRASHLONG|735 = {'fall': 0.4, 'news': 'any', 'trig': 'close_c', 'hold': 1, 'stop': 'none', 'exit': 'target20', 'band': '5-20'}
- MO 2026: MO_MOMOLONG|647 = {'up': 1.0, 'trig': 'redclose', 'hold': 3, 'stop': 0.3, 'exit': 'ma10', 'band': '5-20'}

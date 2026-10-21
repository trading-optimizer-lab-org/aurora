# v21 results: small caps, a five-times-larger grid with new ideas (192,114 configurations)

Pre-registered in [V21_PREREGISTRATION.md](V21_PREREGISTRATION.md). GitHub run 39482229828: started by itself after
v20 and v19q (2026-10-20 19:17 UTC), calibration, canary, 600 shards x 4 processes, report (2026-10-21 04:03 UTC);
192,114 of 192,114 configurations, 200 placebos each, no errors. R4 costs: half-spreads by tier and time of the leg,
calibrated on 27,782 measured quote legs (open / session / last minute): under $2 0.66% / 0.47% / 0.58%, $2-5 0.80% /
0.36% / 0.48%, $5-10 0.82% / 0.40% / 0.46%, $10-20 0.99% / 0.51% / 0.45%.

## Summary

- **The pre-registered criterion is not met.** `COMBO21`: walk-forward monthly Sortino **1.87** (18.19 in 2018-2020,
  **1.16** in 2021-2026), 9.2% a year, drawdown -9.6%, 2023-07+ 0.75.
- **Why:** the combination rule let in a new family, RX_DAY2GAP (short the open of the day after a big day), every
  year. Its early configurations traded rarely and looked flawless (2018-2020 Sortino at the cap of 20), then it lost
  62.7% with single trades of -1,726% (squeezes with no stop). Recomputed without RX (an exploratory check, not the
  pre-registered rule, with an approximate weighting) the combination is about 7.8, in line with v20: the bigger grid
  did not find new edges, and the plateau score was fooled by a family that barely traded.
- **The same families as v20 carry it**: RV run-up shorts 5.09 (36.3% a year, drawdown -22%, 2023-07+ 6.73), PB
  premarket fade 4.17, GA gap fade 3.28, GB filtered gap fade 3.07, NT overnight short 1.52; R4's dearer opening legs
  lower them a little against v20.
- **The new ideas did not help:** the regime filter (IWM up or down) is worse than none in every family (the
  walk-forward chose "any" in most years; shorts did worst in falling markets); the split exit (half at the close)
  and the close-based stops were rarely chosen; the new long after a collapsed run (DK -0.66) and RX failed; the
  twenty filters show only that premarket dollar volume and early relative volume help a little, while news, filings,
  earnings, repeat runners and high short ratio hurt.
- The false discovery count (134,938 of 192,114 beat their placebos) has the same weakness as in v20.

## Full report

Configurations evaluated 192114 of 192114; errors 0. 200 placebos each. R4 costs (middle) unless stated. Target: COMBO21 monthly Sortino 4.

R4 half-spreads (open / session / last minute): <$2 0.66% / 0.47% / 0.58%; $2-5 0.80% / 0.36% / 0.48%; $5-10 0.82% / 0.40% / 0.46%; $10-20 0.99% / 0.51% / 0.45%

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | low cost | high cost | gross | years placebo-ok | gate | PBO | best config (design Sortino, p) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GA | 3.28 | 6.29 | 2.79 | 11.4% | -7.6% | +158% | 3.78 | 0.64 | 9.70 | 6/9 | pass | 0% | GA_GAPFADE|8625 (7.58, p 0.00) |
| GB | 3.07 | 6.67 | 2.10 | 11.4% | -5.6% | +157% | 3.69 | 0.19 | 9.96 | 7/9 | pass | 0% | GB_GAPFILTER|4149 (8.25, p 0.00) |
| RB | 0.71 | 4.81 | 0.18 | 6.3% | -13.1% | +71% | 0.99 | -0.62 | 2.75 | 9/9 | fail | 0% | RB_RUNFADE|3268 (6.37, p 0.00) |
| DB | -0.49 | 0.18 | -0.66 | 0.8% | -13.6% | +7% | -0.38 | -1.21 | 0.29 | 3/9 | fail | 0% | DB_DAY2FADE|207 (0.64, p 0.14) |
| PB | 4.17 | 7.82 | 3.57 | 12.8% | -6.1% | +189% | 4.85 | 0.98 | 14.59 | 7/9 | pass | 0% | PB_PMFADE|759 (5.82, p 0.00) |
| GE | -0.69 | -1.58 | -0.69 | -1.9% | -24.4% | -15% | -0.57 | -1.01 | -0.18 | 8/9 | fail | 12% | GE_GAPDOWN|3005 (0.59, p 0.03) |
| LB | -1.74 | -1.12 | -1.98 | -9.6% | -63.1% | -59% | -1.67 | -1.85 | -1.48 | 1/9 | fail | 13% | LB_GAPGO|986 (0.25, p 0.01) |
| RV | 5.09 | 10.06 | 5.29 | 36.3% | -22.3% | +1421% | 5.33 | 2.04 | 8.27 | 9/9 | pass | 0% | RV_RUNUP|42462 (9.96, p 0.00) |
| NT | 1.52 | 1.60 | 1.49 | 9.1% | -14.0% | +115% | 1.75 | 0.19 | 2.93 | 9/9 | pass | 0% | NT_NIGHTSHORT|2983 (6.11, p 0.00) |
| EW | -0.32 | -0.99 | 0.11 | 0.3% | -24.7% | +3% | -0.18 | -1.05 | 1.08 | 9/9 | fail | 0% | EW_EVENTSHORT|207 (0.51, p 0.00) |
| CC | -0.52 | -0.75 | -0.43 | -3.4% | -56.2% | -26% | -0.41 | -0.70 | -0.25 | 7/9 | fail | 8% | CC_CRASHLONG|2615 (1.39, p 0.00) |
| MP | -1.20 | -0.92 | -1.37 | -10.5% | -68.7% | -62% | -1.10 | -1.37 | -0.89 | 7/9 | fail | 29% | MP_MOMOLONG|1859 (1.71, p 0.00) |
| DK | -0.66 | 1.39 | -1.12 | -3.9% | -49.1% | -30% | -0.51 | -0.93 | -0.20 | 9/9 | fail | 6% | DK_DEADCATLONG|260 (0.20, p 0.00) |
| RX | 0.16 | 20.00 | -0.08 | 2.1% | -62.7% | +20% | 0.19 | -0.08 | 0.32 | 9/9 | fail | 0% | RX_DAY2GAP|10323 (4.38, p 0.00) |

## 2. COMBO21 (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO21 | 1.87 | 18.19 | 1.16 | 9.2% | -9.6% | +117% | 0.75 | 0.00 | 0% | not met |

Members by year: 2018: CC, DK, LB, NT, RB, RV, RX; 2019: DB, NT, RB, RV, RX; 2020: GB, NT, PB, RB, RV, RX; 2021: DB, GA, GB, NT, PB, RB, RV, RX; 2022: GA, GB, NT, PB, RB, RV, RX; 2023: GA, GB, NT, PB, RB, RV, RX; 2024: GA, GB, NT, PB, RB, RV, RX; 2025: GA, GB, NT, PB, RB, RV, RX; 2026: GA, GB, NT, PB, RB, RV, RX

COMBO21 by year: 2018 +4.3%, 2019 +5.3%, 2020 +24.9%, 2021 +8.3%, 2022 +5.6%, 2023 +7.5%, 2024 +0.8%, 2025 +17.1%, 2026 +9.2%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| GA | 2.17 | 13.4% | -7.6% |
| GB | 2.28 | 12.2% | -5.6% |
| RB | -0.04 | 3.7% | -13.1% |
| DB | -0.52 | 1.5% | -13.6% |
| PB | 2.48 | 13.6% | -6.1% |
| GE | -0.92 | -5.3% | -24.4% |
| LB | -2.25 | -17.8% | -49.9% |
| RV | 6.73 | 82.9% | -22.3% |
| NT | 1.01 | 10.5% | -14.0% |
| EW | 0.37 | 6.8% | -10.8% |
| CC | -0.18 | 0.7% | -30.9% |
| MP | -1.25 | -2.9% | -14.8% |
| DK | -1.50 | -14.8% | -41.3% |
| RX | -0.39 | -15.8% | -62.7% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| GA | 16.4 | +4.7% | 63% | -170% |
| GB | 16.3 | +4.1% | 59% | -358% |
| RB | 18.9 | +1.9% | 59% | -558% |
| DB | 6.2 | +0.4% | 57% | -618% |
| PB | 13.1 | +4.9% | 60% | -170% |
| GE | 4.9 | -0.8% | 42% | -248% |
| LB | 4.0 | -4.3% | 21% | -50% |
| RV | 4.3 | +22.3% | 80% | -397% |
| NT | 4.7 | +6.1% | 69% | -160% |
| EW | 3.5 | -1.3% | 67% | -212% |
| CC | 3.5 | -0.7% | 53% | -96% |
| MP | 3.9 | -5.0% | 28% | -51% |
| DK | 4.0 | -1.3% | 54% | -78% |
| RX | 1.8 | +9.3% | 79% | -1726% |

## 5. False discovery rate over all configurations (Benjamini-Hochberg, q = 5%)

134938 of 192114 configurations survive with the empirical p, 137764 with the placebos' z-score p.

| family | configurations | survive (empirical) | survive (z) | best three by z (Sortino, z) |
|---|---|---|---|---|
| GA | 48384 | 24567 | 25896 | GA_GAPFADE|8625 (7.58, 11.4); GA_GAPFADE|14715 (3.41, 11.2); GA_GAPFADE|14547 (2.87, 11.1) |
| GB | 17280 | 9822 | 10411 | GB_GAPFILTER|17035 (5.72, 14.9); GB_GAPFILTER|17034 (6.96, 14.6); GB_GAPFILTER|14587 (5.72, 14.5) |
| RB | 13440 | 12592 | 12678 | RB_RUNFADE|2814 (3.10, 75.5); RB_RUNFADE|2815 (3.13, 70.7); RB_RUNFADE|3150 (3.08, 67.4) |
| DB | 6048 | 1234 | 1338 | DB_DAY2FADE|3392 (-0.67, 8.7); DB_DAY2FADE|2528 (-0.79, 8.0); DB_DAY2FADE|4189 (-0.04, 6.9) |
| PB | 6480 | 2461 | 2666 | PB_PMFADE|2607 (1.87, 8.6); PB_PMFADE|6087 (-0.27, 8.3); PB_PMFADE|2631 (1.93, 8.2) |
| GE | 3456 | 658 | 635 | GE_GAPDOWN|228 (-0.42, 7.2); GE_GAPDOWN|1240 (-1.87, 7.0); GE_GAPDOWN|84 (-0.65, 6.9) |
| LB | 3240 | 90 | 126 | LB_GAPGO|1916 (-1.36, 3.9); LB_GAPGO|843 (-0.75, 3.3); LB_GAPGO|3108 (-1.94, 3.2) |
| RV | 60000 | 59978 | 59994 | RV_RUNUP|42330 (8.88, 58.9); RV_RUNUP|42462 (9.96, 57.2); RV_RUNUP|41267 (6.74, 56.6) |
| NT | 6912 | 6762 | 6807 | NT_NIGHTSHORT|2310 (2.79, 59.0); NT_NIGHTSHORT|2313 (2.79, 53.1); NT_NIGHTSHORT|1231 (4.86, 50.3) |
| EW | 1440 | 1074 | 1124 | EW_EVENTSHORT|1131 (-1.78, 19.7); EW_EVENTSHORT|1138 (-1.38, 18.1); EW_EVENTSHORT|195 (0.48, 16.1) |
| CC | 7776 | 2827 | 2946 | CC_CRASHLONG|6525 (0.41, 20.1); CC_CRASHLONG|6490 (-0.50, 20.0); CC_CRASHLONG|6507 (0.46, 18.2) |
| MP | 2430 | 731 | 806 | MP_MOMOLONG|1996 (0.83, 17.0); MP_MOMOLONG|1132 (0.56, 16.8); MP_MOMOLONG|1924 (0.30, 16.0) |
| DK | 4860 | 2020 | 2119 | DK_DEADCATLONG|3273 (-0.80, 16.3); DK_DEADCATLONG|4101 (-1.01, 15.6); DK_DEADCATLONG|3255 (-0.83, 15.0) |
| RX | 10368 | 10122 | 10218 | RX_DAY2GAP|8158 (-0.70, 57.0); RX_DAY2GAP|8170 (-0.64, 53.0); RX_DAY2GAP|9598 (-0.78, 52.8) |

## 6. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| GA | gap | 0.2 -0.50 (2) / 0.3 -0.35 (2) / 0.4 -0.35 (5) / 0.5 -0.47 (0) / 0.75 -0.74 (0) / 1.0 -1.03 (0) / 1.5 -1.60 (0) / 2.0 -2.04 (0) |
| GA | band | 1-2 -1.32 (0) / 2-5 -0.12 (9) / 5-10 -0.41 (0) / 10-20 -1.27 (0) |
| GA | trig | open -0.92 (0) / orl5 -0.78 (0) / orl15 -0.88 (5) / orl30 -1.02 (1) / vwaploss -0.56 (1) / t30 -0.90 (2) / t60 -0.93 (0) / belowopen -0.83 (0) / pmhfail -1.35 (0) |
| GA | stop | hod -1.07 (0) / pct10 -0.68 (0) / pct20 -0.63 (3) / pct30 -0.93 (6) / pct50 -1.44 (0) / cpct30 -0.53 (0) / cpct50 -1.13 (0) |
| GA | exit | close -1.48 (0) / next_open -1.00 (0) / d2 -0.86 (2) / d3 -0.69 (4) / d5 -0.62 (2) / d7 -0.59 (0) / half3 -1.12 (0) / g5 -0.73 (1) |
| GA | regime | any -0.44 (8) / iwm_up -0.68 (1) / iwm_down -1.49 (0) |
| GB | gap | 0.3 -0.74 (9) / 0.5 -0.94 (0) |
| GB | band | 1-2 -1.28 (0) / 2-5 -0.32 (9) / 5-20 -0.43 (0) |
| GB | filt | none 0.49 (0) / news_none 0.35 (0) / news_yes -1.23 (0) / pmv1M 0.56 (3) / pmv5M 0.35 (0) / float_lt10M -0.70 (0) / float_ge10M -0.59 (0) / rv5_3 0.41 (1) / rv5_10 0.49 (5) / runs60_0 0.45 (0) / runs60_2 -2.06 (0) / shelf30 -1.26 (0) / offer -2.35 (0) / earn -2.37 (0) / sr_hi -2.14 (0) / sr_lo -1.11 (0) / off_hi -1.53 (0) / off_lo -0.61 (0) / cat_none 0.35 (0) / cat_801 -1.80 (0) |
| GB | trig | orl15 -0.91 (5) / vwaploss -0.69 (0) / t30 -0.95 (2) / belowopen -0.85 (2) |
| GB | stop | pct20 -0.76 (6) / pct30 -1.06 (3) / cpct30 -0.73 (0) |
| GB | exit | next_open -1.02 (0) / d3 -0.81 (4) / d5 -0.68 (0) / g5 -0.83 (5) |
| GB | regime | any -0.39 (7) / iwm_up -0.66 (2) / iwm_down -1.35 (0) |
| RB | up | 0.4 -0.64 (3) / 0.6 -0.30 (4) / 0.8 -0.19 (2) / 1.2 -0.38 (0) / 2.0 -1.07 (0) |
| RB | trig | lowerhigh -0.11 (0) / vwaploss 0.03 (2) / hodfail -1.18 (0) / backside -0.32 (0) / t120 -0.53 (1) / t180 -0.60 (2) / t240 -0.85 (0) / belowopen -0.51 (4) |
| RB | band | 1-2 -1.09 (0) / 2-5 0.28 (9) / 5-10 0.03 (0) / 10-20 -0.85 (0) |
| RB | stop | hod -0.90 (0) / pct20 -0.39 (6) / pct30 -0.63 (2) / cpct30 -0.19 (1) |
| RB | exit | close -1.25 (1) / next_open -0.61 (0) / d3 -0.23 (4) / d5 -0.20 (2) / d7 -0.18 (0) / half3 -0.72 (2) / g5 -0.33 (0) |
| RB | regime | any -0.01 (5) / iwm_up -0.41 (4) / iwm_down -1.06 (0) |
| DB | day1 | 0.5 -1.53 (3) / 1.0 -1.54 (6) / 2.0 -1.87 (0) |
| DB | trig | open -1.46 (4) / orl5 -1.62 (0) / orl15 -1.73 (2) / orl30 -1.85 (0) / vwaploss -1.46 (3) / t30 -1.70 (0) / belowopen -1.63 (0) |
| DB | band | 1-2 -1.81 (0) / 2-5 -1.78 (3) / 5-10 -1.44 (4) / 10-20 -1.41 (2) |
| DB | stop | hod -1.62 (0) / pct20 -1.63 (2) / pct30 -1.79 (0) / cpct30 -1.29 (7) |
| DB | exit | close -1.97 (0) / next_open -1.81 (0) / d3 -1.55 (4) / d5 -1.46 (0) / d7 -1.41 (5) / g5 -1.60 (0) |
| DB | regime | any -1.44 (9) / iwm_up -1.60 (0) / iwm_down -1.83 (0) |
| PB | gap | 0.3 -0.47 (9) / 0.6 -0.86 (0) |
| PB | drop | 0.05 -0.42 (9) / 0.1 -0.54 (0) / 0.2 -1.12 (0) |
| PB | trig | open -0.30 (0) / orl1 -0.49 (0) / orl5 -0.48 (1) / orl15 -0.63 (8) / pmhfail -1.32 (0) |
| PB | stop | pmh -1.04 (1) / pct20 -0.66 (8) / cpct30 -0.34 (0) |
| PB | exit | close -1.28 (0) / next_open -0.77 (0) / d3 -0.50 (8) / d5 -0.41 (1) / d7 -0.38 (0) / g5 -0.57 (0) |
| PB | band | 1-2 -1.25 (1) / 2-5 0.10 (7) / 5-10 -0.12 (1) / 10-20 -0.99 (0) |
| PB | regime | any -0.12 (9) / iwm_up -0.45 (0) / iwm_down -1.34 (0) |
| GE | side | short -1.41 (8) / long -1.78 (1) |
| GE | gap | -0.2 -1.47 (7) / -0.35 -1.60 (1) / -0.5 -1.87 (1) |
| GE | trig | or5 -1.60 (1) / or15 -1.69 (4) / vwap -1.50 (0) / t30 -1.78 (4) |
| GE | band | 1-2 -1.88 (2) / 2-5 -1.53 (0) / 5-10 -1.43 (7) / 10-20 -1.62 (0) |
| GE | stop | ext -1.61 (2) / pct10 -1.51 (7) / pct20 -1.80 (0) |
| GE | exit | close -1.87 (5) / next_open -1.70 (0) / d3 -1.46 (2) / d5 -1.41 (2) |
| GE | regime | any -1.46 (7) / iwm_up -1.83 (0) / iwm_down -1.46 (2) |
| LB | gap | 0.2 -1.58 (5) / 0.4 -1.77 (3) / 0.8 -1.93 (1) |
| LB | trig | orh1 -2.01 (0) / orh5 -1.88 (0) / orh15 -1.50 (3) / pmhbreak -1.81 (1) / vwapreclaim -1.58 (2) / hod13 -1.73 (3) |
| LB | band | 1-2 -1.79 (0) / 2-5 -1.68 (1) / 5-10 -1.78 (4) / 10-20 -1.77 (4) |
| LB | stop | lod -1.88 (0) / pct10 -1.68 (9) / pct20 -1.72 (0) |
| LB | exit | close -1.69 (0) / trail20 -1.79 (0) / next_open -1.68 (8) / d3 -1.81 (1) / d5 -1.87 (0) |
| LB | regime | any -1.83 (2) / iwm_up -1.69 (6) / iwm_down -1.77 (1) |
| RV | rise | 0.5 -1.22 (0) / 1.0 -0.63 (1) / 2.0 -0.04 (0) / 3.0 0.19 (8) / 5.0 -0.06 (0) |
| RV | window | 1 -0.38 (1) / 3 -0.28 (6) / 5 -0.29 (2) / 20 -0.54 (0) |
| RV | trig | open 0.04 (2) / lowclose -1.00 (0) / redclose -0.91 (0) / close_c -0.00 (7) / gapdown -0.10 (0) |
| RV | hold | 3 -0.50 (1) / 5 -0.28 (0) / 10 -0.23 (6) / 20 -0.35 (2) / 30 -0.43 (0) |
| RV | stop | 0.5 -0.96 (0) / 1.0 -0.50 (0) / c50 -0.09 (0) / none 0.23 (9) |
| RV | exit | time -0.21 (4) / target30 -0.17 (2) / target50 -0.19 (3) / strength -0.43 (0) / green -0.87 (0) |
| RV | vol | any -0.42 (2) / x3 -0.32 (7) |
| RV | regime | any -0.20 (8) / iwm_up -0.34 (0) / iwm_down -0.46 (1) |
| NT | gap | 0.15 -0.01 (0) / 0.2 0.17 (2) / 0.3 0.27 (7) / 0.5 0.01 (0) / 1.0 -0.73 (0) / 1.5 -1.30 (0) |
| NT | drop | 0.0 -0.23 (0) / 0.05 -0.25 (1) / 0.1 -0.25 (7) / 0.2 -0.50 (1) |
| NT | loc | any -0.20 (1) / low25 -0.42 (8) |
| NT | exit | next_open -1.06 (0) / next_close -0.45 (0) / close2 -0.15 (4) / close3 -0.03 (5) / close5 0.12 (0) / green5 -0.25 (0) |
| NT | band | 1-2 -0.44 (0) / 2-5 0.77 (2) / 5-10 -0.07 (7) / 10-20 -1.06 (0) |
| NT | stop | none -0.15 (9) / 0.3 -0.46 (0) |
| NT | regime | any 0.25 (9) / iwm_up -0.26 (0) / iwm_down -0.73 (0) |
| EW | event | offer_spike -0.74 (9) / rsplit -1.77 (0) / deficiency -1.76 (0) / offering -2.01 (0) |
| EW | hold | 3 -1.70 (6) / 5 -1.71 (2) / 10 -1.58 (0) / 20 -1.70 (0) / 40 -1.70 (1) |
| EW | stop | 0.25 -1.81 (0) / 0.5 -1.70 (0) / none -1.47 (9) |
| EW | exit | time -1.60 (1) / target30 -1.59 (8) / target50 -1.60 (0) / green -1.88 (0) |
| EW | band | 1-5 -1.24 (9) / 5-20 -1.94 (0) |
| EW | regime | any -1.71 (3) / iwm_up -1.70 (3) / iwm_down -1.59 (3) |
| CC | fall | 0.25 -1.57 (4) / 0.4 -1.42 (5) / 0.6 -1.56 (0) |
| CC | news | any -1.53 (5) / none -1.49 (4) |
| CC | trig | close_c -0.88 (7) / open -1.73 (0) / greenclose -1.61 (0) / highclose -1.53 (2) |
| CC | hold | 1 -1.70 (0) / 2 -1.52 (0) / 3 -1.45 (0) / 5 -1.48 (1) / 10 -1.52 (1) / 20 -1.42 (7) |
| CC | stop | 0.2 -1.58 (1) / 0.5 -1.49 (0) / none -1.47 (8) |
| CC | exit | time -1.54 (0) / target20 -1.48 (8) / weak -1.54 (1) |
| CC | band | 1-5 -1.56 (1) / 5-20 -1.47 (8) |
| CC | regime | any -1.63 (0) / iwm_up -1.66 (3) / iwm_down -1.26 (6) |
| MP | up | 0.2 -1.51 (3) / 0.5 -1.36 (4) / 1.0 -1.51 (2) |
| MP | trig | open -1.62 (2) / redclose -1.32 (6) / highclose -1.47 (1) |
| MP | hold | 3 -1.47 (5) / 5 -1.42 (1) / 10 -1.49 (0) / 20 -1.44 (0) / 40 -1.45 (3) |
| MP | stop | 0.1 -1.64 (0) / 0.2 -1.41 (2) / 0.3 -1.34 (7) |
| MP | exit | time -1.41 (2) / trail20 -1.52 (2) / ma10 -1.42 (5) |
| MP | band | 1-5 -1.45 (0) / 5-20 -1.46 (9) |
| MP | regime | any -1.56 (0) / iwm_up -1.34 (6) / iwm_down -1.44 (3) |
| DK | peak | 2.0 -1.47 (6) / 3.0 -1.43 (3) / 5.0 -1.49 (0) |
| DK | fall | 0.5 -1.44 (8) / 0.7 -1.48 (1) |
| DK | trig | open -1.34 (7) / greenclose -1.51 (2) / highclose -1.55 (0) |
| DK | hold | 1 -1.72 (0) / 3 -1.41 (0) / 5 -1.38 (3) / 10 -1.38 (1) / 20 -1.41 (5) |
| DK | stop | 0.2 -1.53 (1) / 0.3 -1.46 (0) / none -1.39 (8) |
| DK | exit | time -1.55 (0) / target20 -1.41 (6) / target50 -1.41 (3) |
| DK | band | 1-5 -1.49 (6) / 5-20 -1.44 (3) |
| DK | regime | any -1.54 (3) / iwm_up -1.50 (1) / iwm_down -1.30 (5) |
| RX | day1 | 0.3 -0.54 (4) / 0.5 -0.52 (0) / 1.0 -0.79 (5) |
| RX | gap2 | 0.0 -0.63 (2) / 0.1 -0.46 (7) / 0.2 -0.73 (0) |
| RX | hold | 1 -0.84 (0) / 2 -0.59 (0) / 3 -0.57 (0) / 5 -0.54 (0) / 10 -0.53 (9) / 20 -0.56 (0) |
| RX | stop | 0.25 -1.15 (0) / 0.5 -0.72 (0) / c50 -0.39 (0) / none -0.31 (9) |
| RX | exit | time -0.42 (5) / target30 -0.61 (4) / strength -0.61 (0) / green -0.77 (0) |
| RX | band | 1-2 -0.92 (0) / 2-5 -0.61 (4) / 5-10 -0.52 (0) / 10-20 -0.51 (5) |
| RX | regime | any -0.41 (7) / iwm_up -0.57 (2) / iwm_down -0.94 (0) |

## 7. Latest pick of each family

- GA 2026: GA_GAPFADE|14196 = {'gap': 0.4, 'band': '2-5', 'trig': 'orl30', 'stop': 'pct30', 'exit': 'd5', 'regime': 'any'}
- GB 2026: GB_GAPFILTER|3405 = {'gap': 0.3, 'band': '2-5', 'filt': 'pmv1M', 'trig': 't30', 'stop': 'pct30', 'exit': 'g5', 'regime': 'any'}
- RB 2026: RB_RUNFADE|6876 = {'up': 0.8, 'trig': 't120', 'band': '2-5', 'stop': 'cpct30', 'exit': 'd5', 'regime': 'any'}
- DB 2026: DB_DAY2FADE|210 = {'day1': 0.5, 'trig': 'open', 'band': '5-10', 'stop': 'cpct30', 'exit': 'd7', 'regime': 'any'}
- PB 2026: PB_PMFADE|759 = {'gap': 0.3, 'drop': 0.05, 'trig': 'orl15', 'stop': 'pct20', 'exit': 'd5', 'band': '2-5', 'regime': 'any'}
- GE 2026: GE_GAPDOWN|813 = {'side': 'short', 'gap': -0.35, 'trig': 'or15', 'band': '5-10', 'stop': 'pct10', 'exit': 'd5', 'regime': 'any'}
- LB 2026: LB_GAPGO|1868 = {'gap': 0.4, 'trig': 'vwapreclaim', 'band': '2-5', 'stop': 'pct10', 'exit': 'next_open', 'regime': 'iwm_down'}
- RV 2026: RV_RUNUP|42465 = {'rise': 3.0, 'window': 5, 'trig': 'open', 'hold': 20, 'stop': 'none', 'exit': 'target50', 'vol': 'x3', 'regime': 'any'}
- NT 2026: NT_NIGHTSHORT|3102 = {'gap': 0.3, 'drop': 0.1, 'loc': 'low25', 'exit': 'close3', 'band': '2-5', 'stop': 'none', 'regime': 'any'}
- EW 2026: EW_EVENTSHORT|54 = {'event': 'offer_spike', 'hold': 3, 'stop': 'none', 'exit': 'target30', 'band': '1-5', 'regime': 'any'}
- CC 2026: CC_CRASHLONG|2909 = {'fall': 0.4, 'news': 'any', 'trig': 'close_c', 'hold': 20, 'stop': 'none', 'exit': 'target20', 'band': '5-20', 'regime': 'iwm_down'}
- MP 2026: MP_MOMOLONG|1132 = {'up': 0.5, 'trig': 'redclose', 'hold': 3, 'stop': 0.3, 'exit': 'ma10', 'band': '5-20', 'regime': 'iwm_up'}
- DK 2026: DK_DEADCATLONG|431 = {'peak': 2.0, 'fall': 0.5, 'trig': 'greenclose', 'hold': 5, 'stop': 'none', 'exit': 'target50', 'band': '5-20', 'regime': 'iwm_down'}
- RX 2026: RX_DAY2GAP|2080 = {'day1': 0.3, 'gap2': 0.1, 'hold': 10, 'stop': 'none', 'exit': 'target30', 'band': '2-5', 'regime': 'iwm_up'}

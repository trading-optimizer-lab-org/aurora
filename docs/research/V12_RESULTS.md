# v12 results: everything that could raise the Sortino of the intraday book

GitHub run 39277053568 (2026-10-19), 29,160,000 evaluations on 320 runners (shard 125 failed on a cache timeout and
was rerun, attempt 2). Pre-registered in [V12_PREREGISTRATION.md](V12_PREREGISTRATION.md). Target monthly Sortino 4.

## Summary

- **Nothing reaches 4, and the wider search did worse than v11.** `PICK` (the best worse-half Sortino of 2016-2020)
  went from 8.35 on 2016-2020 to **1.75** in 2021-2026: 7.0% a year, drawdown -8.3%, total +48%. `ENS5`, `ENS10`
  and `ENS25` are the same cluster (1.69-1.71). `ENS10_PLUS` (with the crypto trend streams) 1.17, 12.5% a year,
  drawdown -30.2%. The v11 robust pick, from a grid 120 times smaller, had made 3.59.
- **Why:** with 29 million configurations the robust score favours books that barely trade in the quiet years
  (2018 +2%, 2019 +1%) and so look smooth; that smoothness did not repeat. The more levers, the more ways to fit the
  design window.
- **What helps, out of sample** (median 2021-2026 Sortino of the configurations with a robust score of at least 3):
  no lever value lifts it above 2.12. Best: exit `XQ3_20`, sets `MIX1` and `MIXS3`, no freshness filter (2.12 each).
  Harmful: a higher gap floor (15%: 0.88, 20%: 0.62), relative strength above the 90th percentile (0.88), the VIX
  regime (1.12), a full Nasdaq hedge (1.38), equity-curve overlays `EQ20`/`EQ50` (1.38). The EP close-entry and
  earnings-only sets produced no robust configuration. Position limits, heat limits, sector limits and risk per
  trade did not change the median (1.62).
- Deflated Sharpe 0.00 everywhere. This led to v13 (pre-registered walk-forward and CPCV on a small set fixed in
  advance).

The headline count of the report below (29,007,519) is the evaluations with a finite Sharpe; the other 152,481 made
no trade. Every lever row counts all 29,160,000.

## Full report

29,007,519 evaluations (expected 29,160,000); chosen on 2016-2020 by the worse half; judged on 2021-01-01 to 2026-10-16 and its halves. Owner's target: monthly Sortino of 4. Deflated Sharpe over 29,260,405 trials. Extra streams with a robust score >= 2 for ENS10_PLUS: 20.

## 1. Picks and ensembles

| strategy | Sortino 2016-20 | Sortino 2021-26 | 2021-23 | 2024-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PICK (DSR 0.00) | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| ENS5 (DSR 0.00) | 8.38 | 1.71 | 1.30 | 2.04 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +53% | +4% | -0% | +11% | +6% | +17% | +3% |
| ENS10 (DSR 0.00) | 8.39 | 1.69 | 1.28 | 2.03 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +53% | +4% | -0% | +11% | +6% | +17% | +3% |
| ENS25 (DSR 0.00) | 8.39 | 1.69 | 1.27 | 2.02 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +53% | +4% | -0% | +11% | +6% | +17% | +3% |
| ENS10_PLUS (DSR 0.00) | 5.80 | 1.17 | 1.16 | 1.20 | 12.5% | -30.2% | +98% | +25% | +101% | -19% | +36% | +123% | +40% | -22% | +30% | +28% | +10% | -2% |
| SPY | 1.45 | 1.22 | 0.74 | 2.38 | 14.7% | -24.5% | +120% | +12% | +22% | -5% | +31% | +18% | +29% | -18% | +26% | +25% | +18% | +13% |

PICK = `Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M0_H4_S0_NONE_HG0`

## 2. The 25 most robust configurations

| configuration | Sortino 2016-20 | Sortino 2021-26 | 2021-23 | 2024-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M0_H4_S0_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M8_H0_S0_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M0_H6_S0_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M0_H6_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M8_H4_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M8_H4_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M0_H6_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M8_H0_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M8_H0_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M12_H4_S0_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M12_H4_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M0_H0_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M0_H0_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M0_H4_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M12_H0_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M8_H6_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M0_H4_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M0_H6_S2_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M0_H4_S2_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M0_H0_S2_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M12_H6_S2_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M12_H6_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_G10_RS70_F1_R0.5_C35_M8_H6_S0_NONE_HG0 | 8.42 | 1.65 | 1.23 | 1.98 | 6.9% | -8.5% | +47% | +7% | +33% | +2% | +1% | +54% | +4% | -1% | +11% | +6% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M8_H4_S2_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |
| Q12_MIX1_XQ3_10_M1_N50_G10_RS70_F1_R0.5_C35_M8_H4_S0_NONE_HG0 | 8.35 | 1.75 | 1.34 | 2.08 | 7.0% | -8.3% | +48% | +7% | +33% | +2% | +1% | +52% | +4% | -0% | +11% | +7% | +17% | +3% |

## 3. What helps: per lever value, configurations with a robust score >= 3 and their median 2021-2026 Sortino

| lever = value | evaluations | robust >= 3 | share | median Sortino 2021-26 |
|---|---|---|---|---|
| cap=0.2 | 14,580,000 | 135,210 | 0.93% | 1.62 |
| cap=0.35 | 14,580,000 | 218,805 | 1.50% | 1.62 |
| exit=XG10_50_20_3 | 2,916,000 | 305 | 0.01% | 1.62 |
| exit=XN1_2_20_0 | 2,916,000 | 39,281 | 1.35% | 1.62 |
| exit=XN1_2_20_5 | 2,916,000 | 32,744 | 1.12% | 1.88 |
| exit=XN1_3_20_0 | 2,916,000 | 29,420 | 1.01% | 1.88 |
| exit=XN2_4_20_0 | 2,916,000 | 29,144 | 1.00% | 1.88 |
| exit=XQ1_20 | 2,916,000 | 72,615 | 2.49% | 1.62 |
| exit=XQ3_10 | 2,916,000 | 28,194 | 0.97% | 1.62 |
| exit=XQ3_20 | 2,916,000 | 46,258 | 1.59% | 2.12 |
| exit=XQ5_20 | 2,916,000 | 28,124 | 0.96% | 1.38 |
| exit=XQC20 | 2,916,000 | 47,930 | 1.64% | 1.12 |
| fresh=False | 14,580,000 | 65,735 | 0.45% | 2.12 |
| fresh=True | 14,580,000 | 288,280 | 1.98% | 1.62 |
| gapmin=0.1 | 9,720,000 | 322,814 | 3.32% | 1.62 |
| gapmin=0.15 | 9,720,000 | 11,482 | 0.12% | 0.88 |
| gapmin=0.2 | 9,720,000 | 19,719 | 0.20% | 0.62 |
| heat=0.0 | 9,720,000 | 116,501 | 1.20% | 1.62 |
| heat=0.04 | 9,720,000 | 118,482 | 1.22% | 1.62 |
| heat=0.06 | 9,720,000 | 119,032 | 1.22% | 1.62 |
| hedge=0.0 | 9,720,000 | 190,570 | 1.96% | 1.62 |
| hedge=0.5 | 9,720,000 | 114,263 | 1.18% | 1.62 |
| hedge=1.0 | 9,720,000 | 49,182 | 0.51% | 1.38 |
| max_pos=0 | 9,720,000 | 122,042 | 1.26% | 1.62 |
| max_pos=12 | 9,720,000 | 120,981 | 1.24% | 1.62 |
| max_pos=8 | 9,720,000 | 110,992 | 1.14% | 1.62 |
| overlay=DD15OFF | 5,832,000 | 41,818 | 0.72% | 1.62 |
| overlay=DDH10 | 5,832,000 | 67,228 | 1.15% | 1.88 |
| overlay=EQ20 | 5,832,000 | 101,407 | 1.74% | 1.38 |
| overlay=EQ50 | 5,832,000 | 80,821 | 1.39% | 1.38 |
| overlay=NONE | 5,832,000 | 62,741 | 1.08% | 1.88 |
| regime=BR50 | 2,916,000 | 13,209 | 0.45% | 1.38 |
| regime=M1 | 2,916,000 | 65,146 | 2.23% | 1.62 |
| regime=M1_BR50 | 2,916,000 | 56,693 | 1.94% | 1.62 |
| regime=M1_N50 | 2,916,000 | 71,803 | 2.46% | 1.62 |
| regime=N20 | 2,916,000 | 28,284 | 0.97% | 1.62 |
| regime=N50 | 2,916,000 | 36,394 | 1.25% | 1.88 |
| regime=NEMA | 2,916,000 | 28,894 | 0.99% | 1.38 |
| regime=NHNL | 2,916,000 | 17,569 | 0.60% | 1.62 |
| regime=NONE | 2,916,000 | 34,541 | 1.18% | 1.38 |
| regime=VIX25 | 2,916,000 | 1,482 | 0.05% | 1.12 |
| risk=0.005 | 9,720,000 | 157,851 | 1.62% | 1.62 |
| risk=0.01 | 9,720,000 | 115,049 | 1.18% | 1.62 |
| risk=0.015 | 9,720,000 | 81,115 | 0.83% | 1.62 |
| rs=0.0 | 9,720,000 | 255,960 | 2.63% | 1.62 |
| rs=0.7 | 9,720,000 | 93,417 | 0.96% | 1.88 |
| rs=0.9 | 9,720,000 | 4,638 | 0.05% | 0.88 |
| sector=0 | 14,580,000 | 167,854 | 1.15% | 1.62 |
| sector=2 | 14,580,000 | 186,161 | 1.28% | 1.62 |
| set=ALL | 2,916,000 | 548 | 0.02% | 0.12 |
| set=BO_ALL | 2,916,000 | 30 | 0.00% | -0.38 |
| set=EP_CLOSE | 2,916,000 | 0 | 0.00% | - |
| set=EP_EARN | 2,916,000 | 0 | 0.00% | - |
| set=EP_N0 | 2,916,000 | 61,673 | 2.11% | 1.38 |
| set=EP_N1 | 2,916,000 | 58,438 | 2.00% | 1.38 |
| set=EP_NEWS | 2,916,000 | 59,858 | 2.05% | 0.88 |
| set=MIX1 | 2,916,000 | 67,397 | 2.31% | 2.12 |
| set=MIX3 | 2,916,000 | 96,540 | 3.31% | 1.88 |
| set=MIXS3 | 2,916,000 | 9,531 | 0.33% | 2.12 |

Extra streams in ENS10_PLUS: CT_ma_ensemble_L1, CT_ma_ensemble_L1.5, CT_ma_ensemble_L2, CT_ma_ensemble_L2.5, CT_ma_ensemble_L3, CT_donchian_20_10_L1, CT_donchian_20_10_L1.5, CT_donchian_20_10_L2, CT_donchian_20_10_L2.5, CT_donchian_20_10_L3, CT_ma_ensemble_alts_L1, CT_ma_ensemble_alts_L1.5, CT_ma_ensemble_alts_L2, CT_ma_ensemble_alts_L2.5, CT_ma_ensemble_alts_L3, CT_btc_buy_hold_L1, CT_btc_buy_hold_L1.5, CT_btc_buy_hold_L2, CT_btc_buy_hold_L2.5, CT_btc_buy_hold_L3.

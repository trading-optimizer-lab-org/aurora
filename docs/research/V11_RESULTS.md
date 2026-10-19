# v11 results: a Sortino-first combination of independent strategies

GitHub run 39267908447 (2026-10-19), 235,963 configurations on 320 runners, gate passed. Pre-registered in
[V11_PREREGISTRATION.md](V11_PREREGISTRATION.md). Target monthly Sortino 4; stated expectation 2.5-3.

## Summary

- **No pre-registered combination reaches 4.** `COMBO_GREEDY` went from 11.98 on 2016-2020 to **1.85** in
  2021-2026 (14.8% a year, drawdown -14.0%): the greedy step added diversifiers whose edge vanished (crypto
  Donchian 0.65, turn of the month 0.29). `COMBO_FAMILY` 0.91, `COMBO_FAMILY_EQ` 1.26.
- **The robust selection works for the intraday book.** The best worst-half design Sortino of the QB grid,
  `QB_MIX3_XQ3_20_DAY_GAP_M1_R1_C35_G1_P0_M8` (Qullamaggie EPs plus the 3 best model breakouts, Nasdaq filter on,
  1% risk, 35% cap, at most 8 positions, 1x), made a **monthly Sortino of 3.59 in 2021-2026, 38.4% a year, total
  +554%, drawdown -37.6%**. It is the best out-of-sample Sortino of any configuration chosen by a pre-registered
  rule in this whole search.
- The six best robust QB configurations are all this cluster (`MIX3`, base exit, day-low stop, Nasdaq filter): their
  2021-2026 Sortinos are 2.84-4.05 (4.05 for the second, with no position limit). Across the 30 shortlisted QB
  configurations the median is 1.51; the ones without the Nasdaq filter fell to about 1.4-1.5.
- Deflated Sharpe 0.00 everywhere; survivorship flatters the stock books; 2021-2026 had been opened before for
  related books.

## Full report

235,963 of 235,963 configurations; shortlist 70 streams. Chosen on 2016-2020 only; judged on 2021-01-01 to 2026-10-16. Owner's target: monthly Sortino of 4.

## 1. Combinations

| combination | Sortino 2016-20 | Sortino 2021-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | worst month | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMBO_GREEDY (DSR 0.00) | 11.98 | 1.85 | 14.8% | -14.0% | +122% | -5.1% | +21% | +37% | +8% | +24% | +72% | +25% | -3% | +29% | +13% | +23% | +3% |
| COMBO_FAMILY (DSR 0.00) | 3.86 | 0.91 | 9.2% | -12.0% | +66% | -6.0% | +11% | +18% | +4% | +7% | +61% | +18% | -5% | +8% | +6% | +20% | +7% |
| COMBO_FAMILY_EQ (DSR 0.00) | 3.92 | 1.26 | 14.0% | -18.9% | +113% | -8.0% | +14% | +28% | +6% | +6% | +94% | +28% | -9% | +15% | +10% | +37% | +5% |
| SPY | 1.45 | 1.22 | 14.7% | -24.5% | +120% | -9.2% | +12% | +22% | -5% | +31% | +18% | +29% | -18% | +26% | +25% | +18% | +13% |

Greedy path (2016-2020 Sortino as streams are added): 4.90 -> 6.81 -> 11.08 -> 11.98

## 2. Members of COMBO_GREEDY (weights fixed from 2016-2020 volatility)

| stream | Sortino 2016-20 | Sortino 2021-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | worst month | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QB_MIX3_XQ3_20_DAY_GAP_M1_R1_C35_G1_P0_M8 (12%) | 4.90 | 3.59 | 38.4% | -37.6% | +554% | -14.8% | +47% | +36% | +31% | -0% | +164% | +98% | -8% | +76% | +5% | +141% | -19% |
| CT_donchian_20_10_L1 (27%) | 4.57 | 0.65 | 8.8% | -26.5% | +63% | -15.1% | +33% | +64% | -20% | +47% | +88% | +30% | -20% | +27% | +14% | +8% | -1% |
| SEASON_ETOM4-4_ISPY (45%) | 2.94 | 0.29 | 5.1% | -19.4% | +33% | -8.2% | +4% | +10% | +13% | +12% | +31% | +5% | -0% | +18% | +1% | -5% | +11% |
| QB_MIX1_XG20_20_50_0_DAY_RS63_NONE_R0.5_C35_G1_P0_M0 (16%) | 4.64 | 1.52 | 23.8% | -52.5% | +243% | -14.0% | +34% | +70% | +27% | +36% | +76% | +9% | +18% | +20% | +40% | +60% | -1% |

## 3. COMBO_FAMILY members (best robust score per family)

| stream | Sortino 2016-20 | Sortino 2021-26 | CAGR 2021-26 | max DD 2021-26 | total 2021-26 | worst month | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QB_MIX3_XQ3_20_DAY_GAP_M1_R1_C35_G1_P0_M8 | 4.90 | 3.59 | 38.4% | -37.6% | +554% | -14.8% | +47% | +36% | +31% | -0% | +164% | +98% | -8% | +76% | +5% | +141% | -19% |
| CT_ma_ensemble_L1 | 4.75 | 1.09 | 13.6% | -32.5% | +109% | -15.4% | +29% | +73% | -16% | +42% | +125% | +44% | -22% | +33% | +34% | +6% | -0% |
| MR_U500_126_K20_M_SPY200_IV_X2 | 1.69 | 0.42 | 0.9% | -77.4% | +5% | -54.0% | +8% | +75% | -4% | -6% | +216% | -10% | -28% | +9% | +30% | +56% | -27% |
| LT_IWM_L1_SMA100_W_V30_IEF | 1.46 | -0.14 | 0.8% | -40.4% | +4% | -9.7% | +14% | +7% | +5% | +7% | +30% | -2% | -23% | +9% | -1% | +14% | +11% |
| TSMOM_L126_KSCALED_SETRISK_RM | 1.16 | 0.38 | 6.0% | -30.9% | +40% | -11.4% | +6% | +7% | +2% | +0% | +22% | +15% | +18% | -13% | +1% | +8% | +8% |
| SEASON_ETOM4-4_IIWM | 1.62 | -0.08 | 1.6% | -21.8% | +10% | -8.6% | +6% | +2% | +9% | +11% | +24% | -0% | +1% | +17% | -5% | -6% | +5% |
| XSETF_L126_K1_SETRISK_MLS | 0.66 | 0.14 | 3.6% | -43.2% | +23% | -9.3% | -13% | +0% | +7% | -16% | +71% | +5% | -5% | -19% | -4% | +39% | +14% |

## 4. Daily correlations of the COMBO_GREEDY members, 2021-2026

| | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| 1 | +1.00 | +0.08 | +0.02 | +0.44 |
| 2 | +0.08 | +1.00 | +0.09 | +0.13 |
| 3 | +0.02 | +0.09 | +1.00 | +0.21 |
| 4 | +0.44 | +0.13 | +0.21 | +1.00 |

Hindsight bound (not tradable): the best 2021-2026 Sortino among the 70 shortlisted streams is 4.05 (QB_MIX3_XQ3_20_DAY_RS63_M1_R1_C35_G1_P0_M0).


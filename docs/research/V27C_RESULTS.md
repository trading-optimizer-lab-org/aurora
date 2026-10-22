# v27 C results: v26's picks with a rotation filter and adds

Pre-registered in [V27_PREREGISTRATION.md](V27_PREREGISTRATION.md), section C; run 39735247154 (2026-10-22).

## Summary

- **Neither extension is ever picked.** In every family and every walk-forward year the selection chose rotation `any` and adds `none`. Their in-sample medians are below no filter and no adds in every family: a low share rotation leaves out the trades that pay (the heavily traded gappers), and adding to a short as it rises adds to the squeezes.
- **COMBO27C (6.28) is not an improvement over COMBO26 (5.58) and must not be used.** Its candidates were all of v26's yearly picks, including picks chosen on data after the year they are now picked for (for example the 2026 pick, chosen on 2018-2025, may be picked for 2018). That candidate set leaks later data into earlier years. The pre-registration did not foresee it. The only valid finding of C is the comparison of the rotation and add values, made within each pick.

## Report

Configurations evaluated 2428 of 2428; errors 0. R4 costs (middle) unless stated; 500 placebos for each selected configuration; a configuration can be picked only with at least 50 trades and a trade in 40% of the months before. Target: COMBO27C monthly Sortino 4.

## 1. Families

| family | WF Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | low | high | auction | gross | years placebo-ok | gate | PBO | SPA p (best t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v19:DS1 | 1.36 | 2.37 | 1.03 | 8.2% | -6.8% | 1.68 | 0.55 | 1.58 | 2.56 | 9/9 | pass | 9% | 0.000 (5.1) |
| v19:ON1 | 2.68 | 5.18 | 2.17 | 12.9% | -12.1% | 3.18 | 0.62 | 2.73 | 6.87 | 9/9 | pass | 1% | 0.000 (4.7) |
| v19:XS1 | 4.29 | 20.00 | 2.69 | 20.8% | -8.0% | 5.23 | 0.31 | 4.45 | 13.06 | 8/9 | pass | 0% | 0.000 (5.3) |
| v19:XS2 | 3.18 | 9.77 | 2.04 | 14.3% | -9.9% | 4.19 | 0.52 | 3.33 | 14.07 | 9/9 | pass | 0% | 0.000 (4.9) |
| v20:GF | 2.22 | 5.79 | 1.80 | 11.2% | -8.2% | 2.66 | 0.24 | 2.30 | 5.79 | 8/9 | pass | 0% | 0.000 (5.4) |
| v20:NS | 1.75 | 3.29 | 1.25 | 8.4% | -10.8% | 1.97 | 0.33 | 1.82 | 3.30 | 9/9 | pass | 1% | 0.000 (5.0) |
| v20:RF | 3.59 | 5.64 | 3.03 | 14.5% | -5.9% | 4.41 | 1.31 | 3.75 | 9.31 | 9/9 | pass | 0% | 0.000 (5.8) |
| v20:RU | 4.30 | 6.76 | 3.91 | 30.8% | -19.2% | 4.67 | 2.09 | 4.56 | 6.72 | 9/9 | pass | 0% | 0.000 (5.6) |
| v22:IF | 2.80 | 3.95 | 2.27 | 11.7% | -5.6% | 3.29 | 0.06 | 2.88 | 8.20 | 8/9 | pass | 0% | 0.000 (5.0) |
| v22:IR | 2.34 | 3.19 | 1.86 | 15.2% | -10.4% | 3.22 | -0.37 | 2.48 | 10.18 | 9/9 | pass | 0% | 0.000 (4.6) |
| v22:IV | 6.82 | 14.63 | 5.68 | 25.4% | -9.7% | 8.87 | 0.81 | 7.14 | 20.00 | 9/9 | pass | 0% | 0.000 (7.4) |
| v23:EM | 3.31 | 7.50 | 2.53 | 19.7% | -10.4% | 4.57 | -0.47 | 3.52 | 16.34 | 9/9 | pass | 0% | 0.000 (6.7) |
| v23:MD | 1.67 | 1.41 | 1.93 | 12.4% | -18.8% | 2.49 | -0.76 | 1.80 | 9.85 | 8/9 | pass | 0% | 0.000 (4.6) |
| v23:OR | 4.94 | 13.98 | 3.17 | 13.5% | -4.2% | 5.99 | 1.28 | 5.14 | 14.57 | 8/9 | pass | 0% | 0.000 (6.3) |
| v23:OS | 2.67 | 3.15 | 2.52 | 14.8% | -12.8% | 3.73 | -0.38 | 2.85 | 12.88 | 9/9 | pass | 0% | 0.000 (6.5) |
| v23:PT | 2.55 | 2.68 | 2.61 | 10.1% | -5.6% | 3.07 | 0.27 | 2.64 | 7.26 | 9/9 | pass | 0% | 0.001 (4.3) |
| v23:SQ | 2.37 | 2.20 | 2.45 | 14.1% | -11.2% | 3.32 | -0.57 | 2.54 | 10.80 | 9/9 | pass | 0% | 0.000 (5.6) |
| v23:SR | 3.91 | 12.47 | 2.61 | 14.1% | -8.3% | 4.46 | 1.23 | 3.99 | 8.54 | 9/9 | pass | 0% | 0.000 (5.5) |
| v23:VW | 3.14 | 10.73 | 2.18 | 14.8% | -7.7% | 3.87 | 0.28 | 3.27 | 9.54 | 9/9 | pass | 0% | 0.000 (5.8) |
| v25:AS | 5.48 | 11.83 | 4.66 | 20.6% | -7.3% | 6.52 | 0.48 | 5.67 | 17.70 | 9/9 | pass | 0% | 0.000 (7.7) |
| v25:IS | 4.47 | 10.10 | 3.45 | 20.2% | -9.2% | 6.04 | -0.26 | 4.74 | 20.00 | 9/9 | pass | 0% | 0.000 (6.5) |
| v25:MP | 4.16 | 5.80 | 3.91 | 18.7% | -9.6% | 5.16 | 0.86 | 4.30 | 12.68 | 9/9 | pass | 0% | 0.000 (8.6) |
| v25:PS | 4.25 | 4.29 | 4.22 | 15.2% | -7.4% | 5.17 | 0.95 | 4.42 | 11.67 | 8/9 | pass | 0% | 0.000 (7.1) |

## 2. COMBO27C (families chosen each year on earlier data only)

| stream | Sortino 2018+ | 2018-20 | 2021+ | CAGR | max DD | total | 2023-07+ | DSR | PBO | criterion |
|---|---|---|---|---|---|---|---|---|---|---|
| COMBO27C | 6.28 | 15.26 | 4.85 | 14.3% | -4.9% | +224% | 3.97 | 0.00 | 0% | met |

Members by year: 2018: v19:DS1, v19:ON1, v19:XS2, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP; 2019: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2020: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2021: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2022: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2023: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2024: v19:DS1, v19:ON1, v19:XS1, v19:XS2, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SQ, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2025: v19:DS1, v19:ON1, v19:XS1, v20:GF, v20:NS, v20:RF, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS; 2026: v19:DS1, v19:ON1, v19:XS1, v20:GF, v20:NS, v20:RU, v22:IF, v22:IR, v22:IV, v23:EM, v23:MD, v23:OR, v23:OS, v23:PT, v23:SR, v23:VW, v25:AS, v25:IS, v25:MP, v25:PS

COMBO27C by year: 2018 +12.1%, 2019 +9.3%, 2020 +23.6%, 2021 +12.7%, 2022 +6.6%, 2023 +19.9%, 2024 +12.2%, 2025 +25.0%, 2026 +5.8%

## 3. The 2023-07+ segment

| family | Sortino | CAGR | max DD |
|---|---|---|---|
| v19:DS1 | 1.73 | 13.0% | -6.3% |
| v19:ON1 | 1.36 | 11.3% | -12.1% |
| v19:XS1 | 1.84 | 16.6% | -8.0% |
| v19:XS2 | 1.08 | 10.2% | -9.9% |
| v20:GF | 1.63 | 13.8% | -8.2% |
| v20:NS | 0.69 | 7.7% | -10.8% |
| v20:RF | 2.61 | 17.4% | -5.9% |
| v20:RU | 4.10 | 43.8% | -19.2% |
| v22:IF | 1.84 | 12.0% | -5.6% |
| v22:IR | 1.03 | 10.6% | -10.4% |
| v22:IV | 5.55 | 28.9% | -9.7% |
| v23:EM | 3.17 | 25.6% | -10.4% |
| v23:MD | 1.19 | 11.4% | -9.7% |
| v23:OR | 3.31 | 14.9% | -4.2% |
| v23:OS | 1.84 | 15.6% | -12.8% |
| v23:PT | 3.16 | 17.1% | -5.4% |
| v23:SQ | 2.34 | 18.6% | -8.8% |
| v23:SR | 2.99 | 17.8% | -8.3% |
| v23:VW | 1.78 | 14.5% | -7.7% |
| v25:AS | 4.67 | 28.1% | -7.3% |
| v25:IS | 3.48 | 23.3% | -9.2% |
| v25:MP | 3.04 | 21.5% | -9.6% |
| v25:PS | 3.42 | 18.5% | -7.4% |

## 4. Trades of each family's walk-forward stream (middle costs, trades the book took)

| family | trades a month | mean net return a trade | win rate | worst trade |
|---|---|---|---|---|
| v19:DS1 | 3.9 | +5.0% | 66% | -281% |
| v19:ON1 | 7.8 | +5.2% | 66% | -151% |
| v19:XS1 | 30.9 | +3.2% | 58% | -170% |
| v19:XS2 | 28.9 | +2.8% | 55% | -191% |
| v20:GF | 17.0 | +3.9% | 60% | -170% |
| v20:NS | 3.7 | +7.5% | 70% | -154% |
| v20:RF | 30.9 | +3.0% | 60% | -96% |
| v20:RU | 5.4 | +13.1% | 75% | -281% |
| v22:IF | 12.4 | +4.4% | 57% | -169% |
| v22:IR | 47.2 | +2.1% | 57% | -473% |
| v22:IV | 37.5 | +3.2% | 55% | -146% |
| v23:EM | 41.9 | +2.1% | 52% | -185% |
| v23:MD | 52.4 | +1.8% | 57% | -200% |
| v23:OR | 21.2 | +4.4% | 61% | -170% |
| v23:OS | 51.7 | +2.1% | 58% | -189% |
| v23:PT | 12.7 | +3.9% | 55% | -169% |
| v23:SQ | 30.3 | +2.0% | 53% | -156% |
| v23:SR | 12.6 | +5.3% | 55% | -168% |
| v23:VW | 26.1 | +3.3% | 59% | -193% |
| v25:AS | 21.7 | +4.5% | 57% | -183% |
| v25:IS | 39.5 | +2.4% | 54% | -182% |
| v25:MP | 26.5 | +3.8% | 54% | -194% |
| v25:PS | 29.4 | +4.0% | 62% | -156% |

## 5. Entry and exit choices

Median 2018-2026 Sortino (middle costs, in sample) of all configurations with each value, and in brackets the walk-forward years that picked it.

| family | dimension | value median (years) |
|---|---|---|
| v19:DS1 | base | v19:DS1_RUNUP|1369 -0.63 (6) / v19:DS1_RUNUP|13869 0.09 (1) / v19:DS1_RUNUP|13878 0.09 (0) / v19:DS1_RUNUP|21449 -0.08 (1) / v19:DS1_RUNUP|2630 -0.55 (0) / v19:DS1_RUNUP|4 0.16 (1) |
| v19:DS1 | rot | any 1.37 (8) / r05 -0.57 (0) / r1 -0.14 (0) / r2 0.06 (1) |
| v19:DS1 | add | none -0.11 (9) |
| v19:ON1 | base | v19:ON1_NIGHTSHORT|17469 1.23 (7) / v19:ON1_NIGHTSHORT|2349 1.23 (0) / v19:ON1_NIGHTSHORT|27551 0.28 (1) / v19:ON1_NIGHTSHORT|3600 1.34 (0) / v19:ON1_NIGHTSHORT|9910 1.91 (1) |
| v19:ON1 | rot | any 3.08 (9) / r05 -0.23 (0) / r1 0.89 (0) / r2 1.57 (0) |
| v19:ON1 | add | none 1.26 (9) |
| v19:XS1 | base | v19:XS1_GAPFADE|10734 -1.05 (0) / v19:XS1_GAPFADE|1304 -1.74 (2) / v19:XS1_GAPFADE|1313 -1.79 (2) / v19:XS1_GAPFADE|14369 -0.84 (2) / v19:XS1_GAPFADE|5283 -2.37 (0) / v19:XS1_GAPFADE|70 -2.34 (0) / v19:XS1_GAPFADE|8934 -1.31 (3) / v19:XS1_GAPFADE|9078 -1.39 (0) / v19:XS1_GAPFADE|9474 -1.18 (0) |
| v19:XS1 | rot | any -0.71 (9) / r05 -2.08 (0) / r1 -1.83 (0) / r2 -1.53 (0) |
| v19:XS1 | add | none 0.32 (9) / a10 -1.59 (0) / a20 -1.99 (0) / a30 -2.00 (0) |
| v19:XS2 | base | v19:XS2_RUNFADE|10878 -0.96 (2) / v19:XS2_RUNFADE|1304 -2.05 (0) / v19:XS2_RUNFADE|1844 -1.99 (0) / v19:XS2_RUNFADE|1853 -2.05 (0) / v19:XS2_RUNFADE|3878 -1.50 (5) / v19:XS2_RUNFADE|5120 -1.40 (1) / v19:XS2_RUNFADE|5263 -1.04 (0) / v19:XS2_RUNFADE|6218 -1.23 (0) / v19:XS2_RUNFADE|7693 -1.50 (1) |
| v19:XS2 | rot | any -0.78 (9) / r05 -1.74 (0) / r1 -1.55 (0) / r2 -1.47 (0) |
| v19:XS2 | add | none 0.39 (9) / a10 -1.28 (0) / a20 -1.75 (0) / a30 -1.81 (0) |
| v20:GF | base | v20:GF_GAPFADE|14360 -0.99 (1) / v20:GF_GAPFADE|20370 -1.07 (1) / v20:GF_GAPFADE|21639 -0.93 (0) / v20:GF_GAPFADE|2384 -1.60 (1) / v20:GF_GAPFADE|24365 -1.40 (1) / v20:GF_GAPFADE|25454 -1.07 (2) / v20:GF_GAPFADE|5118 -1.84 (2) / v20:GF_GAPFADE|7683 -1.72 (0) / v20:GF_GAPFADE|8958 -1.77 (1) |
| v20:GF | rot | any 0.31 (9) / r05 -2.03 (0) / r1 -1.70 (0) / r2 -1.40 (0) |
| v20:GF | add | none 0.43 (9) / a10 -1.44 (0) / a20 -1.78 (0) / a30 -1.89 (0) |
| v20:NS | base | v20:NS_NIGHTSHORT|13689 0.10 (1) / v20:NS_NIGHTSHORT|16380 0.47 (1) / v20:NS_NIGHTSHORT|17478 0.02 (0) / v20:NS_NIGHTSHORT|22680 0.51 (0) / v20:NS_NIGHTSHORT|2538 0.75 (1) / v20:NS_NIGHTSHORT|26462 0.34 (0) / v20:NS_NIGHTSHORT|28982 0.79 (0) / v20:NS_NIGHTSHORT|7578 0.42 (6) |
| v20:NS | rot | any 2.12 (9) / r05 -1.08 (0) / r1 0.05 (0) / r2 0.86 (0) |
| v20:NS | add | none 0.40 (9) |
| v20:RF | base | v20:RF_RUNFADE|13111 -1.18 (2) / v20:RF_RUNFADE|15314 -1.62 (0) / v20:RF_RUNFADE|16565 -1.50 (0) / v20:RF_RUNFADE|17285 -1.40 (2) / v20:RF_RUNFADE|21999 -1.39 (0) / v20:RF_RUNFADE|429 -1.36 (1) / v20:RF_RUNFADE|5120 -1.13 (2) / v20:RF_RUNFADE|7684 -1.18 (2) / v20:RF_RUNFADE|8773 -1.35 (0) |
| v20:RF | rot | any -0.52 (9) / r05 -1.76 (0) / r1 -1.58 (0) / r2 -1.40 (0) |
| v20:RF | add | none -0.13 (9) / a10 -1.32 (0) / a20 -1.69 (0) / a30 -1.86 (0) |
| v20:RU | base | v20:RU_RUNUP|13878 0.09 (8) / v20:RU_RUNUP|16395 -0.11 (1) / v20:RU_RUNUP|16397 -0.31 (0) / v20:RU_RUNUP|16526 -0.31 (0) / v20:RU_RUNUP|16920 -0.76 (0) / v20:RU_RUNUP|18911 0.09 (0) / v20:RU_RUNUP|18928 -0.02 (0) / v20:RU_RUNUP|21437 -0.31 (0) |
| v20:RU | rot | any 1.95 (9) / r05 -0.80 (0) / r1 -0.24 (0) / r2 -0.17 (0) |
| v20:RU | add | none -0.18 (9) |
| v22:IF | base | v22:IF_FLAG|14360 -1.11 (5) / v22:IF_FLAG|14540 -0.94 (1) / v22:IF_FLAG|5659 -1.37 (0) / v22:IF_FLAG|6732 -1.80 (0) / v22:IF_FLAG|6748 -1.34 (1) / v22:IF_FLAG|6919 -1.20 (0) / v22:IF_FLAG|9107 -1.58 (0) / v22:IF_FLAG|9123 -1.09 (2) |
| v22:IF | rot | any -0.35 (9) / r05 -1.96 (0) / r1 -1.52 (0) / r2 -1.21 (0) |
| v22:IF | add | none 0.16 (9) / a10 -1.35 (0) / a20 -1.62 (0) / a30 -1.71 (0) |
| v22:IR | base | v22:IR_RSI1M|1477 -1.81 (1) / v22:IR_RSI1M|1637 -1.68 (0) / v22:IR_RSI1M|1646 -1.65 (0) / v22:IR_RSI1M|1835 -0.89 (4) / v22:IR_RSI1M|5471 -1.62 (0) / v22:IR_RSI1M|5472 -1.58 (0) / v22:IR_RSI1M|5479 -1.30 (2) / v22:IR_RSI1M|5650 -0.89 (2) / v22:IR_RSI1M|5651 -1.24 (0) |
| v22:IR | rot | any -1.08 (9) / r05 -1.75 (0) / r1 -1.57 (0) / r2 -1.46 (0) |
| v22:IR | add | none 0.03 (9) / a10 -1.43 (0) / a20 -1.70 (0) / a30 -1.74 (0) |
| v22:IV | base | v22:IV_VWAPBAND|1304 -0.60 (3) / v22:IV_VWAPBAND|5119 -0.83 (6) / v22:IV_VWAPBAND|8943 -1.21 (0) / v22:IV_VWAPBAND|8944 -1.74 (0) / v22:IV_VWAPBAND|8954 -1.64 (0) / v22:IV_VWAPBAND|9304 -1.74 (0) |
| v22:IV | rot | any -0.46 (9) / r05 -1.82 (0) / r1 -1.42 (0) / r2 -1.20 (0) |
| v22:IV | add | none 0.10 (9) / a10 -1.26 (0) / a20 -1.75 (0) / a30 -1.75 (0) |
| v23:EM | base | v23:EM_EMA|15324 -2.23 (0) / v23:EM_EMA|16915 -1.43 (1) / v23:EM_EMA|16924 -1.46 (3) / v23:EM_EMA|16944 -1.88 (1) / v23:EM_EMA|5479 -1.73 (0) / v23:EM_EMA|8934 -1.92 (1) / v23:EM_EMA|9294 -1.52 (3) |
| v23:EM | rot | any -0.99 (9) / r05 -2.25 (0) / r1 -1.99 (0) / r2 -1.74 (0) |
| v23:EM | add | none -0.26 (9) / a10 -1.80 (0) / a20 -2.02 (0) / a30 -2.02 (0) |
| v23:MD | base | v23:MD_MACD|1664 -1.43 (1) / v23:MD_MACD|1835 -1.30 (5) / v23:MD_MACD|1837 -1.59 (0) / v23:MD_MACD|1844 -1.32 (0) / v23:MD_MACD|2024 -1.38 (1) / v23:MD_MACD|4219 -2.06 (1) / v23:MD_MACD|44 -1.82 (1) / v23:MD_MACD|4419 -2.19 (0) / v23:MD_MACD|5839 -1.76 (0) |
| v23:MD | rot | any -0.96 (9) / r05 -1.87 (0) / r1 -1.75 (0) / r2 -1.59 (0) |
| v23:MD | add | none -0.29 (9) / a10 -1.58 (0) / a20 -1.80 (0) / a30 -1.90 (0) |
| v23:OR | base | v23:OR_ORB|1844 -1.58 (0) / v23:OR_ORB|413 -1.73 (1) / v23:OR_ORB|5130 -1.91 (0) / v23:OR_ORB|5490 -1.77 (3) / v23:OR_ORB|5650 -1.14 (5) / v23:OR_ORB|5659 -1.16 (0) |
| v23:OR | rot | any -0.13 (9) / r05 -2.10 (0) / r1 -1.93 (0) / r2 -1.58 (0) |
| v23:OR | add | none -0.21 (9) / a10 -1.59 (0) / a20 -1.93 (0) / a30 -1.96 (0) |
| v23:OS | base | v23:OS_OSC|15657 -1.48 (1) / v23:OS_OSC|16179 -1.31 (1) / v23:OS_OSC|16915 -1.24 (2) / v23:OS_OSC|16916 -1.48 (0) / v23:OS_OSC|17096 -1.15 (1) / v23:OS_OSC|17097 -1.11 (0) / v23:OS_OSC|17104 -0.81 (4) / v23:OS_OSC|8054 -1.60 (0) / v23:OS_OSC|9286 -1.52 (0) |
| v23:OS | rot | any -0.89 (9) / r05 -1.65 (0) / r1 -1.50 (0) / r2 -1.35 (0) |
| v23:OS | add | none 0.24 (9) / a10 -1.24 (0) / a20 -1.68 (0) / a30 -1.76 (0) |
| v23:PT | base | v23:PT_PATTERN|10554 -1.51 (1) / v23:PT_PATTERN|13262 -1.44 (2) / v23:PT_PATTERN|1673 -2.07 (1) / v23:PT_PATTERN|5470 -1.06 (5) / v23:PT_PATTERN|5479 -1.10 (0) / v23:PT_PATTERN|5650 -1.05 (0) / v23:PT_PATTERN|6516 -1.63 (0) / v23:PT_PATTERN|9294 -1.42 (0) |
| v23:PT | rot | any -0.36 (8) / r05 -2.01 (0) / r1 -1.73 (0) / r2 -1.36 (1) |
| v23:PT | add | none 0.05 (9) / a10 -1.42 (0) / a20 -1.73 (0) / a30 -1.82 (0) |
| v23:SQ | base | v23:SQ_SQUEEZE|11482 -2.49 (0) / v23:SQ_SQUEEZE|11597 -1.98 (1) / v23:SQ_SQUEEZE|13109 -1.75 (2) / v23:SQ_SQUEEZE|3850 -2.27 (1) / v23:SQ_SQUEEZE|5470 -1.66 (5) / v23:SQ_SQUEEZE|5488 -1.73 (0) / v23:SQ_SQUEEZE|5839 -1.78 (0) / v23:SQ_SQUEEZE|6730 -1.75 (0) |
| v23:SQ | rot | any -1.10 (9) / r05 -2.23 (0) / r1 -2.15 (0) / r2 -2.00 (0) |
| v23:SQ | add | none -0.63 (9) / a10 -1.88 (0) / a20 -2.17 (0) / a30 -2.19 (0) |
| v23:SR | base | v23:SR_LEVEL|10554 -0.42 (2) / v23:SR_LEVEL|1655 -0.58 (3) / v23:SR_LEVEL|1664 -0.55 (0) / v23:SR_LEVEL|1673 -0.71 (3) / v23:SR_LEVEL|8043 -0.92 (0) / v23:SR_LEVEL|9294 -0.61 (1) |
| v23:SR | rot | any 0.25 (9) / r05 -1.29 (0) / r1 -0.97 (0) / r2 -0.88 (0) |
| v23:SR | add | none 1.59 (9) / a10 -0.61 (0) / a20 -1.15 (0) / a30 -1.15 (0) |
| v23:VW | base | v23:VW_VWAP|4221 -1.58 (0) / v23:VW_VWAP|4230 -1.63 (0) / v23:VW_VWAP|4399 -1.44 (0) / v23:VW_VWAP|5470 -1.04 (6) / v23:VW_VWAP|5650 -0.99 (3) / v23:VW_VWAP|5659 -1.05 (0) / v23:VW_VWAP|6732 -1.50 (0) |
| v23:VW | rot | any -0.56 (9) / r05 -2.06 (0) / r1 -1.73 (0) / r2 -1.51 (0) |
| v23:VW | add | none -0.02 (9) / a10 -1.31 (0) / a20 -1.88 (0) / a30 -1.98 (0) |
| v25:AS | base | v25:AS_ABCD|10554 -0.58 (4) / v25:AS_ABCD|13101 -1.52 (0) / v25:AS_ABCD|13109 -0.88 (2) / v25:AS_ABCD|13281 -1.77 (0) / v25:AS_ABCD|14369 -0.74 (2) / v25:AS_ABCD|9294 -0.61 (1) |
| v25:AS | rot | any 0.43 (9) / r05 -1.59 (0) / r1 -1.29 (0) / r2 -0.97 (0) |
| v25:AS | add | none 0.62 (9) / a10 -0.86 (0) / a20 -1.43 (0) / a30 -1.48 (0) |
| v25:IS | base | v25:IS_IND|11842 -1.77 (0) / v25:IS_IND|13101 -1.78 (0) / v25:IS_IND|13109 -1.22 (5) / v25:IS_IND|16755 -2.11 (0) / v25:IS_IND|16924 -1.47 (3) / v25:IS_IND|5679 -1.55 (0) / v25:IS_IND|9294 -1.74 (1) |
| v25:IS | rot | any -0.82 (9) / r05 -1.99 (0) / r1 -1.94 (0) / r2 -1.53 (0) |
| v25:IS | add | none -0.21 (9) / a10 -1.59 (0) / a20 -1.99 (0) / a30 -2.01 (0) |
| v25:MP | base | v25:MP_MORNPOP|16915 -0.68 (0) / v25:MP_MORNPOP|17095 -0.62 (0) / v25:MP_MORNPOP|17122 -0.70 (1) / v25:MP_MORNPOP|18382 -0.90 (1) / v25:MP_MORNPOP|5470 -0.26 (5) / v25:MP_MORNPOP|5652 -0.81 (0) / v25:MP_MORNPOP|9060 -1.21 (2) |
| v25:MP | rot | any 0.08 (9) / r05 -1.16 (0) / r1 -0.87 (0) / r2 -0.77 (0) |
| v25:MP | add | none 1.17 (9) / a10 -0.73 (0) / a20 -1.03 (0) / a30 -1.12 (0) |
| v25:PS | base | v25:PS_PATTERN|1844 -0.86 (1) / v25:PS_PATTERN|1846 -1.59 (0) / v25:PS_PATTERN|1848 -2.09 (0) / v25:PS_PATTERN|1853 -0.86 (6) / v25:PS_PATTERN|411 -1.93 (2) / v25:PS_PATTERN|595 -1.70 (0) |
| v25:PS | rot | any 0.32 (9) / r05 -2.11 (0) / r1 -1.96 (0) / r2 -1.58 (0) |
| v25:PS | add | none -0.19 (9) / a10 -1.51 (0) / a20 -2.08 (0) / a30 -2.20 (0) |

## 6. Latest pick of each family

- v19:DS1 2026: v19:DS1_RUNUP|0 = {'base': 'v19:DS1_RUNUP|1369', 'rot': 'any', 'add': 'none'}
- v19:ON1 2026: v19:ON1_NIGHTSHORT|0 = {'base': 'v19:ON1_NIGHTSHORT|17469', 'rot': 'any', 'add': 'none'}
- v19:XS1 2026: v19:XS1_GAPFADE|48 = {'base': 'v19:XS1_GAPFADE|14369', 'rot': 'any', 'add': 'none'}
- v19:XS2 2026: v19:XS2_RUNFADE|0 = {'base': 'v19:XS2_RUNFADE|10878', 'rot': 'any', 'add': 'none'}
- v20:GF 2026: v20:GF_GAPFADE|80 = {'base': 'v20:GF_GAPFADE|25454', 'rot': 'any', 'add': 'none'}
- v20:NS 2026: v20:NS_NIGHTSHORT|28 = {'base': 'v20:NS_NIGHTSHORT|7578', 'rot': 'any', 'add': 'none'}
- v20:RF 2026: v20:RF_RUNFADE|0 = {'base': 'v20:RF_RUNFADE|13111', 'rot': 'any', 'add': 'none'}
- v20:RU 2026: v20:RU_RUNUP|0 = {'base': 'v20:RU_RUNUP|13878', 'rot': 'any', 'add': 'none'}
- v22:IF 2026: v22:IF_FLAG|0 = {'base': 'v22:IF_FLAG|14360', 'rot': 'any', 'add': 'none'}
- v22:IR 2026: v22:IR_RSI1M|112 = {'base': 'v22:IR_RSI1M|5650', 'rot': 'any', 'add': 'none'}
- v22:IV 2026: v22:IV_VWAPBAND|0 = {'base': 'v22:IV_VWAPBAND|1304', 'rot': 'any', 'add': 'none'}
- v23:EM 2026: v23:EM_EMA|96 = {'base': 'v23:EM_EMA|9294', 'rot': 'any', 'add': 'none'}
- v23:MD 2026: v23:MD_MACD|64 = {'base': 'v23:MD_MACD|2024', 'rot': 'any', 'add': 'none'}
- v23:OR 2026: v23:OR_ORB|64 = {'base': 'v23:OR_ORB|5650', 'rot': 'any', 'add': 'none'}
- v23:OS 2026: v23:OS_OSC|96 = {'base': 'v23:OS_OSC|17104', 'rot': 'any', 'add': 'none'}
- v23:PT 2026: v23:PT_PATTERN|0 = {'base': 'v23:PT_PATTERN|10554', 'rot': 'any', 'add': 'none'}
- v23:SQ 2026: v23:SQ_SQUEEZE|32 = {'base': 'v23:SQ_SQUEEZE|13109', 'rot': 'any', 'add': 'none'}
- v23:SR 2026: v23:SR_LEVEL|0 = {'base': 'v23:SR_LEVEL|10554', 'rot': 'any', 'add': 'none'}
- v23:VW 2026: v23:VW_VWAP|64 = {'base': 'v23:VW_VWAP|5650', 'rot': 'any', 'add': 'none'}
- v25:AS 2026: v25:AS_ABCD|0 = {'base': 'v25:AS_ABCD|10554', 'rot': 'any', 'add': 'none'}
- v25:IS 2026: v25:IS_IND|32 = {'base': 'v25:IS_IND|13109', 'rot': 'any', 'add': 'none'}
- v25:MP 2026: v25:MP_MORNPOP|96 = {'base': 'v25:MP_MORNPOP|9060', 'rot': 'any', 'add': 'none'}
- v25:PS 2026: v25:PS_PATTERN|0 = {'base': 'v25:PS_PATTERN|1844', 'rot': 'any', 'add': 'none'}

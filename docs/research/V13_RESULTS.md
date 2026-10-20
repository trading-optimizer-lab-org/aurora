# v13 results: an honest estimate without overfitting

GitHub run 39304746624 (2026-10-19), one job; pre-registered in [V13_PREREGISTRATION.md](V13_PREREGISTRATION.md)
(two earlier runs stopped before any result: the gate on rebuilt inputs, then the runner's memory). Target: a
walk-forward monthly Sortino of 4 over 2018-2026, at least 3 in both halves, PBO below 20%, on the
survivorship-free universe.

## Summary

- **Not reached, on either universe.** On the survivorship-free universe the primary `WF_ENS5` made a walk-forward
  Sortino of **0.61** (7.2% a year, drawdown -68.7%), `WF_ONE` 0.82, `WF_DIV` 0.95 (9.9% a year, -26.7%); SPY 1.17.
  PBO 29%.
- **On the earlier survivors-only panel the same rules give 3.45** (`WF_ENS5`: 29.9% a year, -31.4%, 3.61 and 3.57
  in the halves) and `WF_ONE` 4.06 (34.6% a year), but the second half of `WF_ONE` is 2.58 and the PBO is 53%, so
  it fails there too.
- **The gap between the two universes is the main finding.** With delisted and newer stocks included, the
  Qullamaggie book loses almost all of its edge: 2021 goes from +78% to -19% and 2025 from +160% to +72%. If this is
  survivorship and not a data artefact, every stock result of v10-v12 was inflated by the survivors-only list. A
  diagnostic (below) separates the causes.
- **Gate passed:** the v11 robust pick rebuilt on the v11 inputs made 3.586781, exactly as published; on the
  rebuilt v12 inputs it made 3.48 (2021+ Yahoo prices re-downloaded), so the published 3.59 carries about 0.1 of
  data noise.
- **Universe:** 33,577 Alpaca `us_equity` assets; 10,067 on NYSE, NASDAQ or AMEX with a plain ticker (8,382
  active, 1,685 inactive); 9,853 with bars, 7,052 kept after the data checks (254 failed) and the liquidity floor
  (1,081 never reached it); 149 reused tickers cut to their last segment. Alpaca lists only 1,685 inactive tickers,
  far fewer than the real number of delistings since 2016, so this universe still leans towards survivors: the true
  figures are probably no better than these.
- Peak memory 14.6 GB (swap added); 3,195 Alpaca calls for the new candidates' minute bars; 3,801 candidate columns.

## Full report

144 configurations fixed in advance; yearly walk-forward 2018-2026 chosen only on earlier data by plateau score; combinatorial cross-validation (252 splits) for the PBO. Target: monthly Sortino 4 in the walk-forward record, at least 3 in both halves, PBO below 20%.

Survivorship-free universe: {'assets': 33577, 'kept': 10067, 'by_status': {'active': 8382, 'inactive': 1685}, 'by_exchange': {'NASDAQ': 6653, 'NYSE': 3067, 'AMEX': 347}, 'below_liquidity_floor': 1081, 'alpaca_calls': 0, 'symbols_with_bars': 9853, 'kept_series': 7052, 'segmented': 149, 'failed_checks': 254}

## FULL (survivorship-free)

| strategy | Sortino 2018-26 | Sortino 2018-21 | Sortino 2022-26 | CAGR | max DD | total | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WF_ONE (not reached) | 0.82 | 0.84 | 0.80 | 10.0% | -66.1% | +131% | -1% | -5% | +70% | -23% | +11% | +28% | +28% | +57% | -34% |
| WF_ENS5 (not reached) | 0.61 | 0.54 | 0.65 | 7.2% | -68.7% | +84% | -1% | -6% | +40% | -19% | +11% | +24% | +30% | +72% | -44% |
| WF_DIV (not reached) | 0.95 | 1.19 | 0.73 | 9.9% | -26.7% | +128% | -7% | -6% | +37% | +23% | -17% | +34% | +39% | +17% | -15% |
| SPY | 1.17 | 1.52 | 0.84 | 14.4% | -33.7% | +227% | -5% | +31% | +18% | +29% | -18% | +26% | +25% | +18% | +13% |

CPCV over 252 splits: PBO 29%; test Sortino of the chosen configuration: median 1.00, 10th-90th percentile -0.11 to 2.86, share >= 4: 0%.

Yearly choices (WF_ONE): 2018: V13_MIX3_XQ3_20_M1_R0.5_C35_M8 (2.20); 2019: V13_MIX3_XQ3_20_M1_R0.5_C35_M8 (0.93); 2020: V13_MIX1_XQ3_20_M1_N50_R1_C35_M8 (-0.04); 2021: V13_MIX3_XQ3_20_N50_R0.5_C35_M0 (1.77); 2022: V13_MIX3_XQ3_20_M1_N50_R1_C35_M0 (1.12); 2023: V13_MIX3_XQ3_20_M1_N50_R0.5_C35_M0 (0.91); 2024: V13_MIX3_XQ3_20_M1_N50_R0.5_C35_M0 (0.94); 2025: V13_EP_N1_XQ3_20_M1_N50_R1_C35_M0 (1.70); 2026: V13_EP_N1_XQ3_20_M1_N50_R1_C35_M8 (1.81)

## SURVIVORS (earlier panel)

| strategy | Sortino 2018-26 | Sortino 2018-21 | Sortino 2022-26 | CAGR | max DD | total | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WF_ONE (not reached) | 4.06 | 5.30 | 2.58 | 34.6% | -35.0% | +1259% | -3% | -1% | +134% | +130% | -5% | +31% | +4% | +151% | -20% |
| WF_ENS5 (not reached) | 3.45 | 3.61 | 3.57 | 29.9% | -31.4% | +893% | -3% | +0% | +84% | +78% | -6% | +39% | +7% | +160% | -14% |
| WF_DIV (not reached) | 1.92 | 2.39 | 1.46 | 17.0% | -25.1% | +297% | -7% | +0% | +57% | +46% | -20% | +43% | +20% | +51% | -9% |
| SPY | 1.17 | 1.52 | 0.84 | 14.4% | -33.7% | +227% | -5% | +31% | +18% | +29% | -18% | +26% | +25% | +18% | +13% |

CPCV over 252 splits: PBO 53%; test Sortino of the chosen configuration: median 2.67, 10th-90th percentile 0.95 to 4.86, share >= 4: 21%.

Yearly choices (WF_ONE): 2018: V13_MIX1_XQ3_20_M1_R0.5_C35_M8 (5.44); 2019: V13_MIX3_XQ3_20_M1_R0.5_C35_M8 (3.07); 2020: V13_MIX3_XQ5_20_M1_N50_R1_C35_M8 (1.37); 2021: V13_MIX3_XQ3_20_M1_N50_R1_C35_M0 (3.89); 2022: V13_MIX3_XQ3_20_M1_N50_R0.5_C35_M8 (3.93); 2023: V13_MIX3_XQ3_20_M1_R0.5_C35_M0 (3.21); 2024: V13_MIX3_XQ3_20_M1_R0.5_C35_M0 (2.65); 2025: V13_MIX3_XQ3_20_M1_N50_R1_C20_M0 (3.22); 2026: V13_MIX3_XQ3_20_M1_N50_R1_C35_M8 (4.44)

Diversifiers chosen each year (score, kept if >= 1.5): crypto 2018: donchian_20_10 (6.79); 2019: btc_buy_hold (1.43); 2020: ma_ensemble_alts (1.42); 2021: ma_ensemble (4.45); 2022: ma_ensemble (3.31); 2023: tsmom_28 (2.20); 2024: ma_ensemble_alts (3.16); 2025: ma_ensemble_alts (3.11); 2026: tsmom_28 (2.67); index trend 2018: LT_SPY_L1_SMA200_W_V0_IEF (4.42); 2019: LT_QQQ_L1_SMA150_W_V20_IEF (1.33); 2020: LT_QQQ_L1_SMA50_W_V0_IEF (1.57); 2021: LT_QQQ_L1_SMA150_W_V30_IEF (1.91); 2022: LT_QQQ_L1_SMA150_W_V20_IEF (1.59); 2023: LT_QQQ_L3_SMA150_W_V20_CASH (1.18); 2024: LT_QQQ_L1_SMA150_W_V20_CASH (1.37); 2025: LT_QQQ_L3_NONE_W_V20_CASH (1.41); 2026: LT_QQQ_L1_SMA200_W_V20_CASH (1.46).

## Diagnostic after the run (not pre-registered; the verdict above stands)

GitHub runs 39374599437 and 39376623416, `scripts/run_v13_diag.py`: the same 144 configurations and walk-forward on
subsets of the full panel (the model's top-N re-ranked inside each subset), the trades of one fixed configuration
(`V13_MIX3_XQ3_20_M1_R1_C35_M8`, the v11 pick's settings) by ticker group, and a price comparison.

| subset of the full panel | tickers | WF_ENS5 2018-26 | 2018-21 | 2022-26 | CAGR | max DD | median of the 144 |
|---|---|---|---|---|---|---|---|
| all (reproduces the run) | 7,052 | 0.61 | 0.54 | 0.65 | 7.2% | -68.7% | 0.71 |
| earlier list only | 3,910 | 5.08 | 5.12 | 5.11 | 40.9% | -31.2% | 3.49 |
| earlier list + inactive | 4,856 | 3.51 | 2.86 | 4.86 | 33.5% | -45.1% | 2.74 |
| active only | 6,106 | 1.23 | 0.91 | 1.47 | 15.5% | -49.8% | 0.84 |
| no warrants, units, rights or funds | 5,799 | 0.32 | 0.59 | 0.16 | 2.4% | -71.3% | 0.63 |
| operating companies only | 5,706 | 0.36 | 0.59 | 0.23 | 2.9% | -71.3% | 0.63 |

Trades of the fixed configuration on the full panel (return per piece, weighted by the fraction sold):

| group | pieces | tickers | mean return | profit factor | share below -20% |
|---|---|---|---|---|---|
| earlier list, operating | 1,325 | 663 | +4.2% | 2.07 | 0.8% |
| not in the list, still active, operating | 576 | 293 | -2.2% | 0.74 | 5.9% |
| inactive (delisted), operating | 140 | 85 | -2.4% | 0.43 | 1.4% |
| funds (all groups) | 51 | 34 | +7.4% | 3.83 | 0.0% |
| warrants, rights, units (all groups) | 9 | 7 | -3.0% | 0.48 | 11.1% |

- **Not a data artefact.** The full subset reproduces the run exactly; the earlier list's daily returns match between
  the two panels (median share of days differing by more than 2%: 0.0; 25 of 1,736 tickers above 1%).
- **Not the instrument type.** Warrants and funds are a handful of trades; removing them makes it worse (funds were
  winners).
- **The earlier list itself is the edge.** The same rules on operating companies that are not in the list lose
  money in every listing cohort (listed by 2016: PF 1.08 against 1.76 for the list; 2016-2020: 0.51 against 3.30;
  2021 on: 0.87 against 1.18). The list was compiled after the fact from stocks that still had data at its creation,
  so membership carries information about the future; delisted stocks add a further loss (5.08 -> 3.51 when added).
- **Consequence:** the stock results of phases 1-7 and v10-v12, and the v11 pick's 3.59, were measured on this
  list and are inflated. The honest estimate of the Qullamaggie-style book is a Sortino of about 0.6-1.2, at or below
  SPY's 1.17 over the same years.

# v19q results: the v19r picks with each trade's own quoted spreads

Amendment v19q of [V19_PREREGISTRATION.md](V19_PREREGISTRATION.md). GitHub run 39468048575 (2026-10-20): 11,364
trades of the v19r walk-forward picks of the COMBO19 member families, 20,434 quote windows fetched from Alpaca (SIP),
20,213 with quotes.

## Summary

- **Each trade's real spread changes little.** COMBO19 with every trade's own measured half-spreads (the rest of
  R3 unchanged): walk-forward monthly Sortino **7.86** (12.16 in 2018-2020, **6.64** in 2021-2026), 16.2% a year,
  maximum drawdown -3.9%, 2023-07+ 8.00; with R3's tier spreads 8.51. The pre-registered criterion is still met.
- By family (tier -> measured): XS1 5.21 -> **5.09**, ON1 4.05 -> **4.04**, DS1 4.05 -> **3.97**, XS2 2.67 -> 2.20,
  XS4 1.42 -> 1.33, XS3 0.13 -> -0.28.
- The measured entries cost about what the tiers say (XS1 mean 0.40% against 0.41%); the exits cost more (XS1
  0.50% against 0.41%, XS2 0.60% against 0.42%), because they are mostly at the last minute or the open, where
  spreads are wider. v21's R4 costs are calibrated on these quotes by tier and time of day.
- Check: the tier column reproduces v19r for every intraday family and ON1. For DS1 (4.05 against v19r's 3.94) it
  leaves out the 0.5% short-sale-restriction charge of daily shorts opened 10% or more below the prior close, so
  DS1's measured 3.97 is slightly flattering too (COMBO19 8.51 against 8.45 for the same reason).

## Report

11364 trades; entry quotes found for 11281, exit quotes for 11200 (missing legs keep the R3 tier value).

## Measured half-spreads against the R3 tiers

| family | leg | n with quotes | measured median | measured mean | R3 tier mean |
|---|---|---|---|---|---|
| XS1 | entry | 3035 | 0.30% | 0.40% | 0.41% |
| XS1 | exit | 3034 | 0.36% | 0.50% | 0.41% |
| XS2 | entry | 3713 | 0.30% | 0.45% | 0.40% |
| XS2 | exit | 3679 | 0.38% | 0.60% | 0.42% |
| XS3 | entry | 802 | 0.43% | 0.75% | 0.38% |
| XS3 | exit | 808 | 0.50% | 0.95% | 0.48% |
| XS4 | entry | 1586 | 0.31% | 0.44% | 0.38% |
| XS4 | exit | 1556 | 0.33% | 0.52% | 0.37% |
| XL1 | entry | 432 | 0.22% | 0.33% | 0.35% |
| XL1 | exit | 434 | 0.26% | 0.46% | 0.40% |
| DS1 | entry | 694 | 0.40% | 0.58% | 0.56% |
| DS1 | exit | 682 | 0.35% | 0.51% | 0.38% |
| ON1 | entry | 1019 | 0.29% | 0.35% | 0.38% |
| ON1 | exit | 1007 | 0.36% | 0.49% | 0.38% |

## Walk-forward with each cost (middle scenario)

| stream | Sortino tier (R3) | Sortino measured | 2018-20 | 2021-26 | CAGR | max DD | 2023-07+ | mean cost a trade (tier / measured) |
|---|---|---|---|---|---|---|---|---|
| XS1 | 5.21 | 5.09 | 20.00 | 3.50 | 21.5% | -7.9% | 2.46 | 2.14% / 2.26% |
| XS2 | 2.67 | 2.20 | 4.58 | 1.57 | 14.8% | -14.7% | 2.24 | 1.95% / 2.24% |
| XS3 | 0.13 | -0.28 | 1.78 | -0.80 | 2.0% | -11.7% | -1.28 | 1.36% / 2.30% |
| XS4 | 1.42 | 1.33 | 4.38 | 0.87 | 8.0% | -8.8% | 0.81 | 1.56% / 1.80% |
| XL1 | -1.33 | -1.32 | -1.39 | -1.28 | -3.1% | -28.2% | -1.18 | 0.93% / 1.01% |
| DS1 | 4.05 | 3.97 | 2.40 | 5.03 | 38.5% | -20.6% | 9.84 | 4.55% / 4.72% |
| ON1 | 4.05 | 4.04 | 2.04 | 5.35 | 18.3% | -12.1% | 8.89 | 2.09% / 2.19% |
| COMBO19 | 8.51 | 7.86 | 12.16 | 6.64 | 16.2% | -3.9% | 8.00 |  |

# US stock strategy catalog (pre-registered)

Survivorship bias NOT adjusted (owner's choice): results are optimistic. Locked period from 2021-01-01 never read. Monthly metrics on excess returns over T-bills.

## Train

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months | invested |
|---|---|---|---|---|---|---|
| spy | 0.53 | 0.37 | 8.4% | -55.2% | 62% | - |
| equal_weight_universe | 1.61 | 1.01 | 22.1% | -55.1% | 70% | - |
| felipe_5d | -0.64 | -0.46 | -2.9% | -53.5% | 46% | 24% |
| felipe_s20 | 0.19 | 0.11 | 3.8% | -47.5% | 47% | 45% |
| qulla_s10 | -0.53 | -0.37 | -5.2% | -69.3% | 44% | 45% |
| qulla_s20 | -0.01 | -0.00 | 0.5% | -63.9% | 45% | 54% |
| qulla_half3 | -0.48 | -0.34 | -2.9% | -50.6% | 46% | 36% |
| pullback_s20 | 0.11 | 0.07 | 2.2% | -59.2% | 50% | 72% |
| burst_fast | -0.29 | -0.20 | -5.0% | -80.3% | 47% | 61% |
| burst_5d | -0.25 | -0.16 | -3.8% | -72.4% | 49% | 54% |
| ep_s20 | -0.24 | -0.14 | 2.9% | -7.0% | 73% | 3% |
| darvas_s20 | 0.98 | 0.42 | 9.6% | -33.3% | 57% | 31% |
| weinstein_s20 | 1.27 | 0.56 | 13.2% | -40.4% | 59% | 39% |
| felipe_5d_noind | -0.73 | -0.55 | -5.2% | -65.5% | 44% | 33% |
| felipe_s20_noind | -0.28 | -0.18 | -2.5% | -55.9% | 43% | 54% |
| qulla_s10_noind | -0.77 | -0.55 | -10.3% | -86.7% | 42% | 54% |
| qulla_s20_noind | -0.20 | -0.12 | -3.1% | -73.3% | 47% | 62% |
| qulla_half3_noind | -0.53 | -0.38 | -5.2% | -71.5% | 44% | 46% |
| pullback_s20_noind | 0.11 | 0.07 | 2.1% | -57.4% | 50% | 75% |
| burst_fast_noind | -0.40 | -0.28 | -7.7% | -84.4% | 43% | 67% |
| burst_5d_noind | -0.31 | -0.21 | -4.7% | -78.8% | 47% | 61% |
| ep_s20_noind | -0.36 | -0.24 | 2.3% | -9.0% | 60% | 8% |
| darvas_s20_noind | 0.95 | 0.44 | 10.5% | -34.1% | 53% | 40% |
| weinstein_s20_noind | 1.24 | 0.59 | 14.2% | -38.0% | 55% | 49% |
| bnf_reversion | 16.87 | 3.61 | 157.7% | -26.5% | 88% | 65% |
| blend_t | 5.60 | 2.05 | 39.6% | -21.7% | 70% | - |

## Validation

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months | invested |
|---|---|---|---|---|---|---|
| spy | 1.59 | 0.98 | 13.8% | -33.7% | 71% | - |
| equal_weight_universe | 1.25 | 0.79 | 14.2% | -42.3% | 68% | - |
| felipe_5d | -0.36 | -0.23 | -2.0% | -43.7% | 43% | 24% |
| felipe_s20 | 0.84 | 0.44 | 6.2% | -29.3% | 43% | 45% |
| qulla_s10 | -0.40 | -0.25 | -4.8% | -69.1% | 40% | 45% |
| qulla_s20 | 0.09 | 0.05 | -0.2% | -58.5% | 43% | 54% |
| qulla_half3 | -0.45 | -0.28 | -3.8% | -58.6% | 38% | 36% |
| pullback_s20 | 0.68 | 0.36 | 6.7% | -50.6% | 49% | 72% |
| burst_fast | 0.47 | 0.25 | 4.0% | -62.3% | 50% | 61% |
| burst_5d | 0.38 | 0.20 | 2.7% | -59.2% | 47% | 54% |
| ep_s20 | 0.22 | 0.11 | 1.0% | -10.4% | 55% | 3% |
| darvas_s20 | 0.29 | 0.15 | 1.6% | -24.5% | 45% | 31% |
| weinstein_s20 | 0.37 | 0.18 | 2.1% | -30.6% | 48% | 39% |
| felipe_5d_noind | -0.65 | -0.44 | -5.7% | -61.7% | 38% | 33% |
| felipe_s20_noind | -0.41 | -0.28 | -4.7% | -64.9% | 39% | 54% |
| qulla_s10_noind | -1.00 | -0.78 | -14.2% | -85.5% | 34% | 54% |
| qulla_s20_noind | -0.50 | -0.35 | -8.6% | -75.3% | 38% | 62% |
| qulla_half3_noind | -0.75 | -0.53 | -9.0% | -79.8% | 42% | 46% |
| pullback_s20_noind | 0.54 | 0.30 | 5.3% | -52.5% | 49% | 75% |
| burst_fast_noind | 0.15 | 0.09 | -0.5% | -71.2% | 43% | 67% |
| burst_5d_noind | 0.40 | 0.21 | 2.7% | -69.5% | 42% | 61% |
| ep_s20_noind | 0.98 | 0.48 | 3.2% | -13.0% | 51% | 8% |
| darvas_s20_noind | 0.09 | 0.05 | 0.6% | -31.6% | 45% | 40% |
| weinstein_s20_noind | 0.37 | 0.20 | 2.4% | -35.8% | 48% | 49% |
| bnf_reversion | 3.26 | 1.65 | 34.1% | -57.4% | 72% | 65% |
| blend_t | 1.88 | 0.92 | 12.8% | -27.8% | 59% | - |

## Pre-registered criteria (validation 2011-2020)

Passed: none

- **felipe_5d**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 6656
- **felipe_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.11; signals 6656
- **qulla_s10**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 15033
- **qulla_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; signals 15033
- **qulla_half3**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 15033
- **pullback_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.10; signals 53053
- **burst_fast**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.05; signals 34179
- **burst_5d**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.03; signals 34179
- **ep_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; PASS max drawdown no deeper than -25%); deflated Sharpe 0.02; signals 251
- **darvas_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; PASS max drawdown no deeper than -25%); deflated Sharpe 0.02; signals 8973
- **weinstein_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.03; signals 11963
- **felipe_5d_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 11512
- **felipe_s20_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 11512
- **qulla_s10_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 27656
- **qulla_s20_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 27656
- **qulla_half3_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.00; signals 27656
- **pullback_s20_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.07; signals 103832
- **burst_fast_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; signals 70458
- **burst_5d_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.03; signals 70458
- **ep_s20_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; PASS max drawdown no deeper than -25%); deflated Sharpe 0.11; signals 554
- **darvas_s20_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; signals 12378
- **weinstein_s20_noind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.03; signals 17338
- **bnf_reversion**: FAILED (PASS monthly Sortino >= 2.0; PASS annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.86; signals 439115
- **blend_t**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.56; signals 0

## Every signal traded on its own (train, Amendment 1)

| strategy | trades | win_rate | avg_return | median_return | avg_R | profit_factor | total_return | total_R | avg_days | top5pct_share |
|---|---|---|---|---|---|---|---|---|---|---|
| felipe_5d | 4,041 | 38% | -0.36% | -2.73% | -0.11 | 0.89 | -1,445% | -427 | 3.8 | - |
| felipe_s20 | 3,696 | 24% | -0.20% | -4.23% | -0.09 | 0.95 | -737% | -340 | 10.3 | - |
| qulla_s10 | 7,042 | 24% | -0.47% | -3.56% | -0.16 | 0.87 | -3,309% | -1,153 | 5.5 | - |
| qulla_s20 | 6,692 | 20% | +0.00% | -4.09% | -0.08 | 1.00 | +13% | -542 | 8.3 | 152364% |
| qulla_half3 | 7,278 | 34% | -0.48% | -2.34% | -0.14 | 0.84 | -3,480% | -1,023 | 4.4 | - |
| pullback_s20 | 17,720 | 29% | +0.31% | -4.02% | +0.03 | 1.07 | +5,424% | +502 | 11.9 | 938% |
| burst_fast | 18,776 | 24% | -0.37% | -3.07% | -0.03 | 0.90 | -7,015% | -548 | 5.2 | - |
| burst_5d | 19,672 | 38% | -0.29% | -2.99% | -0.02 | 0.92 | -5,689% | -316 | 3.8 | - |
| ep_s20 | 118 | 29% | +0.06% | -4.09% | -0.13 | 1.01 | +8% | -15 | 12.9 | 3806% |
| darvas_s20 | 3,217 | 39% | +2.09% | -3.40% | +0.08 | 1.38 | +6,739% | +272 | 17.3 | 191% |
| weinstein_s20 | 4,381 | 39% | +2.40% | -3.28% | +0.11 | 1.45 | +10,532% | +485 | 17.1 | 169% |
| felipe_5d_noind | 7,067 | 38% | -0.45% | -2.80% | -0.12 | 0.86 | -3,160% | -816 | 3.8 | - |
| felipe_s20_noind | 6,401 | 23% | -0.54% | -4.32% | -0.13 | 0.88 | -3,486% | -844 | 10.2 | - |
| qulla_s10_noind | 12,989 | 23% | -0.79% | -3.68% | -0.19 | 0.79 | -10,301% | -2,532 | 5.4 | - |
| qulla_s20_noind | 12,266 | 19% | -0.45% | -4.22% | -0.14 | 0.90 | -5,520% | -1,660 | 8.1 | - |
| qulla_half3_noind | 13,491 | 33% | -0.69% | -2.49% | -0.16 | 0.78 | -9,252% | -2,143 | 4.3 | - |
| pullback_s20_noind | 32,907 | 29% | +0.16% | -3.97% | +0.01 | 1.03 | +5,129% | +482 | 12.0 | 1757% |
| burst_fast_noind | 37,986 | 24% | -0.51% | -3.06% | -0.06 | 0.86 | -19,262% | -2,152 | 5.2 | - |
| burst_5d_noind | 39,810 | 38% | -0.26% | -2.93% | -0.02 | 0.93 | -10,399% | -854 | 3.8 | - |
| ep_s20_noind | 279 | 30% | +0.00% | -4.06% | -0.05 | 1.00 | +0% | -15 | 12.3 | 497125% |
| darvas_s20_noind | 4,414 | 39% | +1.84% | -3.37% | +0.08 | 1.33 | +8,102% | +348 | 17.3 | 206% |
| weinstein_s20_noind | 6,321 | 39% | +2.05% | -3.42% | +0.09 | 1.38 | +12,926% | +594 | 17.0 | 187% |
| bnf_reversion | 33,776 | 48% | +1.22% | -0.26% | - | 1.68 | +41,051% | - | 3.7 | 90% |

## Every signal traded on its own (validation, Amendment 1)

| strategy | trades | win_rate | avg_return | median_return | avg_R | profit_factor | total_return | total_R | avg_days | top5pct_share |
|---|---|---|---|---|---|---|---|---|---|---|
| felipe_5d | 1,841 | 40% | -0.09% | -2.42% | -0.05 | 0.97 | -161% | -100 | 3.9 | - |
| felipe_s20 | 1,701 | 28% | +0.55% | -3.66% | +0.10 | 1.14 | +936% | +164 | 10.8 | 438% |
| qulla_s10 | 3,590 | 24% | -0.22% | -2.97% | -0.10 | 0.93 | -806% | -350 | 5.6 | - |
| qulla_s20 | 3,405 | 21% | +0.20% | -3.33% | -0.02 | 1.06 | +684% | -51 | 8.3 | 1164% |
| qulla_half3 | 3,709 | 35% | -0.20% | -1.90% | -0.10 | 0.92 | -726% | -379 | 4.5 | - |
| pullback_s20 | 7,830 | 32% | +1.09% | -3.61% | +0.11 | 1.27 | +8,538% | +877 | 12.7 | 252% |
| burst_fast | 8,254 | 26% | +0.16% | -2.76% | +0.02 | 1.05 | +1,334% | +153 | 5.6 | 1244% |
| burst_5d | 8,829 | 39% | +0.11% | -2.56% | -0.00 | 1.03 | +940% | -39 | 3.8 | 1332% |
| ep_s20 | 133 | 35% | +0.01% | -4.00% | +0.10 | 1.00 | +2% | +13 | 13.6 | 22023% |
| darvas_s20 | 1,478 | 41% | +0.93% | -3.02% | +0.04 | 1.16 | +1,371% | +56 | 16.8 | 342% |
| weinstein_s20 | 1,869 | 39% | +1.00% | -3.42% | +0.04 | 1.18 | +1,862% | +74 | 16.5 | 325% |
| felipe_5d_noind | 3,094 | 39% | -0.41% | -2.59% | -0.10 | 0.86 | -1,279% | -318 | 3.9 | - |
| felipe_s20_noind | 2,855 | 26% | -0.03% | -3.78% | -0.02 | 0.99 | -72% | -50 | 10.5 | - |
| qulla_s10_noind | 6,363 | 23% | -0.72% | -3.19% | -0.19 | 0.79 | -4,552% | -1,205 | 5.3 | - |
| qulla_s20_noind | 6,021 | 19% | -0.17% | -3.58% | -0.11 | 0.95 | -1,053% | -636 | 8.0 | - |
| qulla_half3_noind | 6,569 | 35% | -0.37% | -2.08% | -0.13 | 0.85 | -2,417% | -876 | 4.3 | - |
| pullback_s20_noind | 14,236 | 33% | +0.92% | -3.52% | +0.08 | 1.22 | +13,041% | +1,190 | 12.7 | 282% |
| burst_fast_noind | 16,737 | 25% | -0.13% | -2.85% | -0.02 | 0.96 | -2,098% | -330 | 5.4 | - |
| burst_5d_noind | 17,971 | 38% | -0.15% | -2.76% | -0.04 | 0.95 | -2,634% | -692 | 3.7 | - |
| ep_s20_noind | 275 | 35% | +0.52% | -3.95% | +0.22 | 1.10 | +142% | +60 | 13.9 | 588% |
| darvas_s20_noind | 1,899 | 40% | +0.54% | -3.12% | +0.02 | 1.10 | +1,034% | +35 | 16.8 | 555% |
| weinstein_s20_noind | 2,530 | 40% | +0.87% | -3.07% | +0.04 | 1.16 | +2,192% | +90 | 16.5 | 359% |
| bnf_reversion | 29,419 | 45% | +0.11% | -0.44% | - | 1.05 | +3,224% | - | 3.7 | 709% |

## Industry filter (IND50) minus no filter, validation years (Jacobs' claim)

| strategy | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | years better |
|---|---|---|---|---|---|---|---|---|---|---|---|
| felipe_5d | +10.4% | +3.7% | +1.5% | +1.3% | +12.5% | -2.8% | +0.8% | +1.5% | +6.7% | -2.0% | 8/10 |
| felipe_s20 | +6.7% | +20.9% | +23.9% | +10.6% | +20.1% | -4.0% | +6.1% | -3.0% | +18.3% | +9.4% | 8/10 |
| qulla_s10 | +18.8% | +8.7% | -2.8% | +3.1% | +4.7% | +15.8% | +11.1% | +5.1% | +6.0% | +20.3% | 9/10 |
| qulla_s20 | +14.9% | +4.8% | +9.0% | -3.7% | +3.1% | +6.1% | +10.9% | +6.3% | +19.2% | +14.8% | 9/10 |
| qulla_half3 | +17.6% | +13.7% | +5.5% | -2.5% | +10.7% | +18.4% | -2.6% | -2.1% | -1.5% | -22.2% | 5/10 |
| pullback_s20 | -7.9% | +13.6% | -16.4% | -11.7% | +4.9% | +8.3% | +4.1% | +3.4% | -16.8% | +48.9% | 6/10 |
| burst_fast | -4.7% | +18.8% | +19.3% | +3.3% | +15.3% | +6.2% | -22.9% | -5.6% | +3.3% | +32.9% | 7/10 |
| burst_5d | -7.7% | +9.1% | +20.4% | -4.8% | +22.3% | -3.8% | -21.7% | +6.2% | -4.3% | -42.4% | 4/10 |
| ep_s20 | +3.8% | -3.8% | -1.8% | +0.9% | +2.5% | -19.8% | -14.0% | +0.4% | +4.4% | +2.6% | 6/10 |
| darvas_s20 | +4.8% | +3.2% | +0.8% | -3.5% | +0.3% | -0.2% | +3.6% | -0.4% | +3.5% | -2.9% | 6/10 |
| weinstein_s20 | +2.6% | +2.4% | -1.3% | -6.2% | +0.2% | -5.5% | +4.2% | -4.4% | +4.7% | -0.5% | 5/10 |

## Data

```json
{
  "symbols_in_panel": 2938,
  "calendar": [
    "1993-01-04",
    "2020-12-31"
  ],
  "cash": {
    "source": "FRED DTB3"
  },
  "panel": {
    "source": "local",
    "symbols_requested": 4471,
    "status": {
      "ok": 3156,
      "missing": 1208,
      "dropped": 107
    },
    "drop_reasons": {
      ">=2 reversing one-day spikes (bad ticks)": 83,
      "price jump on a split day (mis-adjusted split)": 31,
      "non-positive prices": 7
    },
    "issue_counts": {
      "duplicate_dates": 0,
      "unsorted": 0,
      "missing_prices": 0,
      "non_positive_prices": 7,
      "ohlc_inconsistent": 1,
      "negative_volume": 0,
      "zero_volume_days": 1488,
      "spike_days": 801,
      "reversing_spikes": 189,
      "split_days": 1510,
      "split_day_spikes": 31,
      "adj_factor_jumps": 105,
      "adj_factor_above_1": 0,
      "stale_runs": 399,
      "off_calendar_dates": 0,
      "missing_calendar_days": 1
    }
  }
}
```

# US stock strategy catalog v2 (pre-registered)

Designed after seeing v1, so validation is not a clean out-of-sample test. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read.
Deflated Sharpe uses 38 trials (v2 + v1).

## Portfolio, train

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months | invested |
|---|---|---|---|---|---|---|
| spy | 0.53 | 0.37 | 8.4% | -55.2% | 62% | - |
| pullback_stage2 | 0.30 | 0.18 | 5.2% | -57.5% | 49% | 67% |
| pullback_ind85 | 0.65 | 0.35 | 9.6% | -54.4% | 53% | 58% |
| pullback_rank_ind | 0.10 | 0.06 | 1.9% | -55.1% | 46% | 71% |
| pullback_rank_close | 0.14 | 0.09 | 3.1% | -50.5% | 47% | 71% |
| pullback_rank_random | -0.09 | -0.06 | -0.3% | -58.7% | 47% | 71% |
| pullback_risk025 | 0.21 | 0.13 | 4.0% | -48.9% | 48% | 65% |
| weinstein_s50 | 1.55 | 0.78 | 19.9% | -43.3% | 59% | 63% |
| darvas_s50 | 1.31 | 0.66 | 17.1% | -45.9% | 62% | 55% |
| felipe_s50 | 0.80 | 0.43 | 12.0% | -45.9% | 51% | 62% |
| qulla_traits_s20 | 0.14 | 0.07 | 3.7% | -37.4% | 57% | 12% |
| bnf_large | 6.45 | 2.07 | 58.5% | -27.0% | 81% | 49% |
| parabolic_short | 0.83 | 0.52 | 7.3% | -26.4% | 71% | 4% |
| pullback_breadth | 0.51 | 0.30 | 8.2% | -54.6% | 51% | 75% |
| felipe_s20_breadth | -0.02 | -0.01 | 1.4% | -47.2% | 47% | 49% |

## Portfolio, validation

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months | invested |
|---|---|---|---|---|---|---|
| spy | 1.59 | 0.98 | 13.8% | -33.7% | 71% | - |
| pullback_stage2 | 0.67 | 0.34 | 6.4% | -53.9% | 42% | 67% |
| pullback_ind85 | 0.62 | 0.35 | 5.6% | -33.6% | 46% | 58% |
| pullback_rank_ind | 0.25 | 0.16 | 1.9% | -50.5% | 50% | 71% |
| pullback_rank_close | -0.00 | -0.00 | -1.1% | -63.0% | 48% | 71% |
| pullback_rank_random | 0.03 | 0.02 | -1.1% | -56.9% | 48% | 71% |
| pullback_risk025 | 0.67 | 0.35 | 5.7% | -41.7% | 42% | 65% |
| weinstein_s50 | 1.28 | 0.65 | 11.0% | -31.1% | 57% | 63% |
| darvas_s50 | 1.26 | 0.60 | 9.2% | -24.8% | 55% | 55% |
| felipe_s50 | 1.39 | 0.73 | 15.1% | -30.5% | 52% | 62% |
| qulla_traits_s20 | 0.80 | 0.25 | 3.3% | -16.8% | 49% | 12% |
| bnf_large | 2.24 | 1.13 | 17.6% | -45.7% | 72% | 49% |
| parabolic_short | 3.26 | 0.58 | 5.9% | -6.7% | 64% | 4% |
| pullback_breadth | 0.85 | 0.44 | 8.8% | -41.4% | 44% | 75% |
| felipe_s20_breadth | 0.73 | 0.37 | 5.5% | -30.7% | 46% | 49% |

## Pre-registered criteria (validation 2011-2020)

Passed: none

- **pullback_stage2**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.07; signals 31050
- **pullback_ind85**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.06; signals 19857
- **pullback_rank_ind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.02; signals 53053
- **pullback_rank_close**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; signals 53053
- **pullback_rank_random**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; signals 53053
- **pullback_risk025**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.07; signals 53053
- **weinstein_s50**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.27; signals 11963
- **darvas_s50**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; PASS max drawdown no deeper than -25%); deflated Sharpe 0.22; signals 8973
- **felipe_s50**: FAILED (FAIL monthly Sortino >= 2.0; PASS annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.34; signals 6656
- **qulla_traits_s20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; PASS max drawdown no deeper than -25%); deflated Sharpe 0.04; signals 1073
- **bnf_large**: FAILED (PASS monthly Sortino >= 2.0; PASS annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.54; signals 167980
- **parabolic_short**: FAILED (PASS monthly Sortino >= 2.0; FAIL annualised return above SPY; PASS max drawdown no deeper than -25%); deflated Sharpe 0.29; signals 1735
- **pullback_breadth**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.12; signals 58485
- **felipe_s20_breadth**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.07; signals 7293

## Every signal traded on its own (train)

| strategy | trades | win_rate | avg_return | median_return | avg_R | profit_factor | total_return | total_R | avg_days | top5pct_share |
|---|---|---|---|---|---|---|---|---|---|---|
| weinstein_s50 | 3,754 | 40% | +6.80% | -4.41% | +0.32 | 1.96 | +25,531% | +1,217 | 40.2 | 106% |
| darvas_s50 | 2,751 | 40% | +6.52% | -4.32% | +0.28 | 1.90 | +17,939% | +761 | 40.7 | 113% |
| bnf_large | 14,644 | 48% | +1.00% | -0.30% | - | 1.51 | +14,576% | - | 3.6 | 102% |
| pullback_ind85 | 6,460 | 30% | +1.23% | -3.92% | +0.14 | 1.27 | +7,940% | +886 | 12.1 | 268% |
| felipe_s50 | 3,629 | 20% | +1.28% | -4.91% | +0.10 | 1.25 | +4,660% | +374 | 18.6 | 356% |
| pullback_stage2 | 10,580 | 29% | +0.70% | -3.84% | +0.07 | 1.16 | +7,443% | +766 | 11.9 | 413% |
| pullback_breadth | 18,801 | 29% | +0.45% | -3.95% | +0.03 | 1.10 | +8,403% | +636 | 11.9 | 640% |
| parabolic_short | 1,251 | 52% | +0.54% | +1.40% | +0.11 | 1.08 | +681% | +141 | 4.0 | 286% |
| qulla_traits_s20 | 660 | 21% | -0.06% | -4.37% | -0.03 | 0.99 | -42% | -18 | 8.3 | - |
| felipe_s20_breadth | 4,099 | 24% | -0.30% | -4.29% | -0.12 | 0.93 | -1,239% | -497 | 10.3 | - |

## Every signal traded on its own (validation)

| strategy | trades | win_rate | avg_return | median_return | avg_R | profit_factor | total_return | total_R | avg_days | top5pct_share |
|---|---|---|---|---|---|---|---|---|---|---|
| parabolic_short | 483 | 65% | +5.70% | +7.81% | +0.36 | 2.35 | +2,753% | +175 | 3.9 | 32% |
| weinstein_s50 | 1,656 | 40% | +4.23% | -4.28% | +0.19 | 1.58 | +7,013% | +321 | 36.5 | 137% |
| darvas_s50 | 1,308 | 41% | +4.12% | -4.09% | +0.17 | 1.56 | +5,387% | +227 | 37.7 | 141% |
| felipe_s50 | 1,681 | 23% | +2.42% | -4.21% | +0.43 | 1.54 | +4,064% | +724 | 18.9 | 188% |
| pullback_stage2 | 4,635 | 32% | +1.39% | -3.55% | +0.15 | 1.34 | +6,446% | +692 | 12.4 | 212% |
| pullback_ind85 | 3,182 | 34% | +1.33% | -3.51% | +0.16 | 1.33 | +4,225% | +520 | 12.8 | 195% |
| qulla_traits_s20 | 308 | 21% | +1.13% | -3.40% | +0.08 | 1.31 | +348% | +25 | 8.2 | 257% |
| pullback_breadth | 8,275 | 32% | +1.11% | -3.55% | +0.12 | 1.27 | +9,177% | +972 | 12.7 | 250% |
| bnf_large | 10,842 | 46% | +0.30% | -0.37% | - | 1.17 | +3,270% | - | 3.6 | 246% |
| felipe_s20_breadth | 1,748 | 27% | +0.25% | -3.71% | +0.04 | 1.06 | +435% | +67 | 10.5 | 941% |

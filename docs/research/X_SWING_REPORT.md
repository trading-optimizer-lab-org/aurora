# US stocks, momentum swing rules from X traders (pre-registered)

Locked period from 2021-01-01 never read. Candidates are bias-adjusted (see the SEPA pre-registration); monthly metrics on excess returns over T-bills.

Survivorship bias, local minus French top momentum decile, per month: train 0.15%, validation 0.11%

## Train

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months | trades a year | win rate |
|---|---|---|---|---|---|---|---|
| spy | 0.54 | 0.38 | 8.4% | -55.2% | 62% | - | - |
| b1_hold5 | -1.15 | -0.98 | -7.9% | -79.5% | 44% | 211 | 39% |
| b1_hold5 (unadjusted) | -1.11 | -0.94 | -7.4% | -78.1% | 44% | | |
| b1_hold5_ind | -1.17 | -1.04 | -6.7% | -73.8% | 46% | 152 | 39% |
| b1_hold5_ind (unadjusted) | -1.14 | -1.00 | -6.4% | -72.4% | 46% | | |
| b1_ma20 | -0.38 | -0.24 | -3.2% | -77.8% | 41% | 134 | 25% |
| b1_ma20 (unadjusted) | -0.31 | -0.19 | -2.3% | -75.7% | 42% | | |
| b1_ma20_ind | -0.63 | -0.42 | -5.0% | -77.0% | 40% | 107 | 25% |
| b1_ma20_ind (unadjusted) | -0.57 | -0.38 | -4.3% | -75.3% | 40% | | |
| b2_ma20 | -0.40 | -0.28 | -5.0% | -73.4% | 44% | 216 | 27% |
| b2_ma20 (unadjusted) | -0.33 | -0.23 | -3.9% | -70.3% | 44% | | |
| b2_ma20_ind | -0.30 | -0.20 | -2.8% | -68.2% | 40% | 181 | 28% |
| b2_ma20_ind (unadjusted) | -0.23 | -0.15 | -1.8% | -64.8% | 41% | | |
| b3_quick | -0.17 | -0.11 | -0.3% | -60.7% | 45% | 229 | 25% |
| b3_quick (unadjusted) | -0.09 | -0.06 | 0.7% | -56.9% | 45% | | |
| b3_quick_ind | -0.27 | -0.20 | -1.0% | -66.5% | 55% | 181 | 25% |
| b3_quick_ind (unadjusted) | -0.20 | -0.15 | -0.2% | -64.3% | 55% | | |

## Validation

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months | trades a year | win rate |
|---|---|---|---|---|---|---|---|
| spy | 1.60 | 0.98 | 13.8% | -33.7% | 71% | - | - |
| b1_hold5 | -0.60 | -0.45 | -4.0% | -42.9% | 44% | 130 | 42% |
| b1_hold5 (unadjusted) | -0.57 | -0.42 | -3.8% | -41.4% | 44% | | |
| b1_hold5_ind | -0.58 | -0.42 | -3.0% | -36.2% | 44% | 93 | 41% |
| b1_hold5_ind (unadjusted) | -0.55 | -0.39 | -2.8% | -35.2% | 45% | | |
| b1_ma20 | 0.05 | 0.03 | 0.1% | -43.9% | 40% | 89 | 28% |
| b1_ma20 (unadjusted) | 0.12 | 0.07 | 0.7% | -42.2% | 42% | | |
| b1_ma20_ind | 0.06 | 0.03 | 0.2% | -39.0% | 39% | 68 | 29% |
| b1_ma20_ind (unadjusted) | 0.11 | 0.07 | 0.6% | -37.6% | 39% | | |
| b2_ma20 | 0.27 | 0.17 | 2.2% | -51.3% | 52% | 171 | 30% |
| b2_ma20 (unadjusted) | 0.34 | 0.22 | 3.0% | -50.8% | 52% | | |
| b2_ma20_ind | 0.02 | 0.02 | -0.4% | -41.4% | 45% | 136 | 29% |
| b2_ma20_ind (unadjusted) | 0.09 | 0.06 | 0.2% | -38.8% | 45% | | |
| b3_quick | 0.56 | 0.30 | 4.4% | -38.6% | 45% | 177 | 26% |
| b3_quick (unadjusted) | 0.63 | 0.34 | 5.1% | -38.0% | 46% | | |
| b3_quick_ind | 0.52 | 0.29 | 3.7% | -29.3% | 48% | 127 | 27% |
| b3_quick_ind (unadjusted) | 0.58 | 0.32 | 4.2% | -29.1% | 48% | | |

## Pre-registered criteria (validation 2011-2020, bias-adjusted)

- **b1_hold5**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; average invested 26%
- **b1_hold5_ind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.01; average invested 19%
- **b1_ma20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.14; average invested 46%
- **b1_ma20_ind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.13; average invested 36%
- **b2_ma20**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.25; average invested 64%
- **b2_ma20_ind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.13; average invested 56%
- **b3_quick**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.38; average invested 51%
- **b3_quick_ind**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.36; average invested 40%

## Industry filter A1, yearly return with minus without (unadjusted, descriptive)

| year | b1_hold5 | b1_ma20 | b2_ma20 | b3_quick |
|---|---|---|---|---|
| 1995 | +2.3% | -0.7% | +13.8% | -1.5% |
| 1996 | -5.7% | -21.9% | -1.9% | +9.0% |
| 1997 | -1.6% | -7.1% | +12.5% | +8.7% |
| 1998 | +8.7% | +1.8% | +6.9% | +0.4% |
| 1999 | +9.2% | -3.3% | -11.3% | -29.1% |
| 2000 | +1.8% | -5.6% | -0.3% | -14.3% |
| 2001 | -1.5% | -4.0% | -2.5% | +6.7% |
| 2002 | +5.6% | +3.8% | -1.3% | +6.3% |
| 2003 | -5.6% | +2.7% | -2.0% | -16.3% |
| 2004 | -6.6% | -4.1% | -6.7% | -9.3% |
| 2005 | +0.2% | -3.6% | +12.8% | +4.4% |
| 2006 | -2.3% | -5.3% | -2.5% | -12.1% |
| 2007 | +8.9% | +2.7% | +3.8% | +12.0% |
| 2008 | +6.7% | +2.7% | +2.5% | -9.5% |
| 2009 | -3.9% | +6.4% | +9.6% | +9.9% |
| 2010 | +0.9% | -3.9% | -5.0% | +12.2% |
| 2011 | +1.5% | +1.7% | +8.3% | +5.5% |
| 2012 | +1.3% | +5.3% | +7.1% | +4.4% |
| 2013 | +2.6% | -10.0% | -18.5% | +0.3% |
| 2014 | -1.1% | +0.9% | +2.2% | -9.8% |
| 2015 | +6.1% | +8.6% | -3.7% | +9.9% |
| 2016 | -4.3% | +0.7% | +1.9% | -5.2% |
| 2017 | +0.4% | -1.2% | -10.3% | -4.5% |
| 2018 | -6.7% | -6.9% | +10.6% | -1.9% |
| 2019 | +7.3% | +3.5% | -11.6% | -2.7% |
| 2020 | +1.9% | -9.1% | -32.9% | -10.4% |

## Data

```json
{
  "symbols": 2847,
  "with_industry": 2548,
  "industries": 141,
  "calendar": [
    "1993-01-29",
    "2020-12-31"
  ],
  "cash": {
    "source": "Yahoo ^IRX (FRED failed: FRED DTB3 unavailable: HTTPSConnectionPool(host='fred.stlouisfed.org', port=443): Read timed out. (read timeout=120))"
  }
}
```

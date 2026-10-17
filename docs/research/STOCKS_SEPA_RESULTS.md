# US stocks, Minervini / O'Neil style (pre-registered)

Locked period from 2021-01-01 never read. Candidates are bias-adjusted (see the pre-registration); monthly metrics on excess returns over T-bills.

Survivorship bias, local minus French top momentum decile, per month: train 0.13%, validation 0.13%

## Train

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months |
|---|---|---|---|---|---|
| spy | 0.53 | 0.37 | 8.4% | -55.2% | 62% |
| equal_weight_universe | 1.11 | 0.75 | 15.7% | -55.5% | 67% |
| template_rs_monthly | 1.36 | 0.73 | 26.4% | -61.6% | 74% |
| template_rs_monthly (unadjusted) | 1.43 | 0.76 | 27.8% | -61.5% | 74% |
| sepa_breakout | 0.95 | 0.47 | 14.6% | -46.7% | 65% |
| sepa_breakout (unadjusted) | 1.04 | 0.51 | 16.0% | -46.1% | 66% |
| canslim_breakout | 0.16 | 0.11 | 3.6% | -51.0% | 64% |
| canslim_breakout (unadjusted) | 0.24 | 0.16 | 4.7% | -48.8% | 64% |

## Validation

| strategy | sortino_monthly | sharpe_monthly | cagr | max_drawdown | positive_months |
|---|---|---|---|---|---|
| spy | 1.59 | 0.98 | 13.8% | -33.7% | 71% |
| equal_weight_universe | 1.24 | 0.80 | 13.6% | -41.9% | 68% |
| template_rs_monthly | 1.06 | 0.64 | 13.7% | -36.0% | 67% |
| template_rs_monthly (unadjusted) | 1.16 | 0.69 | 15.2% | -35.2% | 67% |
| sepa_breakout | 0.25 | 0.17 | 2.0% | -30.4% | 55% |
| sepa_breakout (unadjusted) | 0.36 | 0.24 | 3.4% | -29.9% | 55% |
| canslim_breakout | 0.49 | 0.33 | 4.7% | -33.5% | 57% |
| canslim_breakout (unadjusted) | 0.61 | 0.41 | 6.1% | -30.4% | 57% |

## Pre-registered criteria (validation 2011-2020, bias-adjusted)

- **template_rs_monthly**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.90; average invested 75%
- **sepa_breakout**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.49; average invested 78%
- **canslim_breakout**: FAILED (FAIL monthly Sortino >= 2.0; FAIL annualised return above SPY; FAIL max drawdown no deeper than -25%); deflated Sharpe 0.67; average invested 74%

## Data

```json
{
  "symbols": 3411,
  "nyse_breakpoint_symbols": 1483,
  "calendar": [
    "1993-01-29",
    "2020-12-31"
  ],
  "cash": {
    "source": "FRED DTB3"
  },
  "delisting_census": {
    "1995": {
      "tiingo_listed": 1597,
      "local_with_data": 1133
    },
    "2000": {
      "tiingo_listed": 2489,
      "local_with_data": 1572
    },
    "2005": {
      "tiingo_listed": 3267,
      "local_with_data": 1882
    },
    "2010": {
      "tiingo_listed": 4300,
      "local_with_data": 2278
    },
    "2015": {
      "tiingo_listed": 5601,
      "local_with_data": 2798
    },
    "2020": {
      "tiingo_listed": 6012,
      "local_with_data": 3411
    }
  }
}
```

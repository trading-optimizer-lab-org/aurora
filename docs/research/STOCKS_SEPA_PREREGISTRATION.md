# US stocks, Minervini / O'Neil style: pre-registration

Written and committed on 2026-10-17 **before any stock return was computed
for this study.** Only file schemas, row counts and first/last dates of the
local price files were inspected.

## Hypothesis

The best-known discretionary stock traders (Mark Minervini's SEPA, William
O'Neil's CAN SLIM) buy liquid stocks that are already in strong uptrends, lead
the market in relative strength and break out to new highs on heavy volume,
only while the overall market is in an uptrend, and cut every loser with a
tight stop. The academic analogues (price momentum, 52-week-high momentum)
are among the most robust anomalies. A mechanical version of these rules
should earn a high return with drawdowns limited by the stops and the market
filter.

## Data

- Prices: the local free US daily catalog (Yahoo, `free_us_daily`, 4,400
  stocks listed in June 2026; open/high/low/close, adjusted close, volume,
  splits). Prices are total-return adjusted with `adj_close / close`.
  Only rows before 2021-01-01 are read.
- Market filter: S&P 500 index (`^GSPC`) daily close. Benchmark: SPY total
  return. Cash: 3-month T-bill index as in the other studies.
- Survivorship-bias calibration: Kenneth French data library, "10 Portfolios
  Formed on Prior (12-2) Return", equal-weighted monthly (CRSP, all NYSE,
  AMEX and NASDAQ stocks, including those later delisted).
- Delisting census: Tiingo's public `supported_tickers.zip` (start and end
  dates of every ticker, including delisted ones), used only to report how
  much of each year's market is missing from the local catalog.

## Known bias and how it is handled

The local catalog contains only companies still listed in 2026. Companies
that went bankrupt or were acquired are missing, which overstates the return
of any rule that buys stocks. No free source of delisted prices could be
automated (Yahoo, Alpha Vantage and FMP free keys return nothing for delisted
symbols; Stooq blocks scripts; paid sources start at about $400).

The bias is measured, not ignored:

1. Each month-end, the local stocks with a real (split-unadjusted) price of
   at least $5 and 13 months of history are sorted on their return from
   month t-12 to t-2. The top decile uses breakpoints from stocks whose
   current listing is NYSE. Its equal-weighted return over the next month is
   compared with French's equal-weighted top decile ("Hi PRIOR").
2. For each period (train, validation) the bias `b` is the mean monthly
   difference, local minus French, floored at zero.
3. Every candidate's monthly return is reduced by `b` times its average
   invested fraction that month. **Pass criteria apply to these adjusted
   returns.** Unadjusted results are reported too.

## Universe, every trading day

The 1,000 stocks with the highest 50-day average dollar volume
(`close * volume`), among those with a real price of at least $10 and at
least 260 days of history.

## Indicators

- Moving averages of the adjusted close: 50, 150 and 200 days.
- 52-week high and low: max and min adjusted close over 252 days.
- RS rating (IBD style): `2*R63 + R126 + R189 + R252`, where `Rn` is the
  n-day return, ranked as a percentile 1-99 within the day's universe.
- Trend Template (Minervini), all eight must hold:
  1. close > MA150 and close > MA200
  2. MA150 > MA200
  3. MA200 above its value 21 trading days earlier
  4. MA50 > MA150 and MA50 > MA200
  5. close > MA50
  6. close at least 30% above the 52-week low
  7. close within 25% of the 52-week high
  8. RS rating >= 70
- Market filter (O'Neil "M"): S&P 500 close above its 200-day average.
- Breakout: close above the highest close of the previous 50 days, with
  volume at least 1.5 times its previous 50-day average.

## Execution and costs (all candidates)

Signals are computed at the close of day t and executed at the open of day
t+1. Costs: 10 bps of traded value per side. Stops are checked against the
day's low; a stop fills at the stop price, or at the open if the stock gaps
below it. Uninvested capital earns the T-bill rate. Positions are not
resized after entry.

## Candidates (3)

| Name | Rules |
|---|---|
| `template_rs_monthly` | Last trading day of each month: if the market filter holds, target the 20 stocks with the highest RS rating among those passing the Trend Template; otherwise hold no stocks. Positions not in the target are sold; new names are bought with 1/20 of equity each. No stops. |
| `sepa_breakout` | Daily. Entry: Trend Template + breakout + market filter. At most 10 positions, each 1/10 of equity at entry; if there are more signals than free slots, highest RS rating first. Exit: stop 8% below entry, or a close below MA50 (sold at the next open). |
| `canslim_breakout` | Same entries as `sepa_breakout`. Exit: stop 7% below entry, profit target +25% (fills at the target, or the open if it gaps above), or a close below MA50. |

Benchmarks (not trials): SPY buy and hold, and an equal-weighted portfolio
of the day's universe rebalanced monthly (it carries the same survivorship
bias as the candidates).

## Periods

| Period | Dates | Use |
|---|---|---|
| Warm-up | 1993-01-01 to 1994-12-31 | indicators only |
| Train | 1995-01-01 to 2010-12-31 | sanity check only, no tuning |
| Validation | 2011-01-01 to 2020-12-31 | pass/fail on the criteria below |
| Locked | 2021-01-01 onward | closed; opened once, only on the owner's request |

## Pass criteria (validation, bias-adjusted)

All three must hold:

1. Monthly Sortino ratio of returns in excess of T-bills >= 2.0.
2. Annualised return above SPY's over the same period.
3. Maximum drawdown no deeper than -25%.

Every candidate counts as a trial for the deflated Sharpe ratio. No other
candidate, parameter or rule will be added to the validation comparison.
Only a candidate that passes validation may be proposed for the locked test,
and only the best one by validation monthly Sortino.

## Not tested here

CAN SLIM's earnings rules (C and A: quarterly and annual EPS growth). They
need point-in-time earnings for delisted companies too (SEC financial
statement data sets, 2009 onward); that is a separate study if this one
shows promise.

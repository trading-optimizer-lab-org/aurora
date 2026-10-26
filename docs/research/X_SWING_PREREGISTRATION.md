# US stocks, momentum swing rules from X traders: pre-registration

Written and committed on 2026-10-26 **before any return was computed for this study**, at the owner's request (the
study proposed at the end of `X_IDEAS_CATALOG_2026-10.md`). Code: `research/x_swing.py`, `scripts/run_x_swing.py`,
tests `tests/test_x_swing.py`.

## Hypothesis

The rules that several public swing traders repeat (Qullamaggie via @Muninn, @FelipeGuirao, @ohiain, @Gaurav_Cx10 /
Stockbee, @SteveDJacobs) earn a high return with limited drawdowns on liquid US stocks: buy volatile stocks in strong
industries breaking out of tight ranges, or pulling back to rising averages, only in a rising market, risk a small
fixed fraction per trade, cut losers at the day's low.

## Data, universe, bias, periods

Exactly as `STOCKS_SEPA_PREREGISTRATION.md`: the local `free_us_daily` catalog (total-return adjusted prices), the
universe of the 1,000 stocks with the highest 50-day dollar volume among those at $10 or more with 260 days of
history, the French top-decile survivorship adjustment (the same `b` per period, times the invested fraction), the
3-month T-bill as cash, SPY as the benchmark.

| Period | Dates | Use |
|---|---|---|
| Warm-up | 1993-01-01 to 1994-12-31 | indicators only |
| Train | 1995-01-01 to 2010-12-31 | sanity check only, no tuning |
| Validation | 2011-01-01 to 2020-12-31 | pass/fail |
| Locked | 2021-01-01 onward | closed; opened once, only on the owner's request |

Industries are Yahoo's current classification (`company_metadata.parquet`), held fixed over time: a stock that
changed industry is filed under today's.

## Filters on every candidate

- **D1 market**: the S&P 500's 10-day simple average above its 20-day average at the signal close.
- **A2 volatility**: ADR = mean of (high / low - 1) over the 20 sessions up to the signal session, >= 4%.
- **A1 industry strength** (on or off, see below): each day, an industry's strength is the median RS rating (the
  SEPA study's IBD-style rating) of its stocks in the universe, for industries with 3 or more such stocks; industries
  are ranked as percentiles 0-100; the stock's industry must be at 50 or more.

## Entries (signal and purchase at the close of session t)

EMAs of the adjusted close; "rising" means above its value 5 sessions before.

- **B1 breakout at the close** (Felipe Guirao): EMA8 > EMA20 > EMA50, all three rising; the 7 sessions before t all
  closed at or above their EMA20 and their range (highest high / lowest low - 1) is at most 3 ADR; the close of t is
  above the highest high of those 7 sessions; t's range (high - low) is larger than the session before's; t closes in
  the top 21% of its range; stop at t's low, and the stop distance (close - low) / close is at most 2.5 ADR.
  Felipe's "CML" indicator is replaced by the stacked, rising EMAs.
- **B2 pullback to rising EMAs** (ohiain): EMA9 > EMA21, both rising, close above EMA50; at t-1 the low touched
  EMA9 or lower, the close held at or above EMA21, and volume was under its 50-day average; at t the close is above
  t-1's high. Stop at t-1's low.
- **B3 momentum burst** (Stockbee / Gaurav): close up 4% or more on the day; volume above the session before's and
  at least 100,000 shares; at t-1 the range (high / low - 1) was at most the ADR at t-1, volume at most its 50-day
  average, and the close above EMA21. Stop at t's low.

## Exits

- **C3 hold 5**: sold at the close of the 5th session after the entry.
- **C1 MA20 trail**: sold at the first close under the 20-day simple average.
- **C4 quick**: at the close of the 3rd session, sold if the close is at or under the entry; at the first close at
  or over entry + 2R (R = entry - stop) half is sold and the stop of the rest moves to the entry; the rest is sold at
  the first close under EMA9.

The stop is checked every session after the entry against the low; it fills at the stop, or at the open if the
stock opens under it. Exits at a close fill at that close.

## Sizing and execution

Risk 0.5% of equity a trade (C5): shares = 0.5% x equity / (entry - stop), capped at 20% of equity a position and by
the cash available (no leverage). When there are more signals than cash, the highest RS rating first. One position
a stock. Costs 10 bps of traded value per side. Cash earns the T-bill rate. Buying at the signal's close assumes a
market-on-close order placed minutes before the close.

## Candidates (8 trials)

| Name | Entry | Exit |
|---|---|---|
| `b1_hold5` | B1 | C3 |
| `b1_ma20` | B1 | C1 |
| `b2_ma20` | B2 | C1 |
| `b3_quick` | B3 | C4 |

each with A1 on (`_ind`) and off: 8 candidates. All use D1 and A2.

## Pass criteria (validation 2011-2020, bias-adjusted)

As the SEPA study, all three: monthly Sortino of returns over T-bills >= 2.0; annualised return above SPY's;
maximum drawdown no deeper than -25%. Every candidate counts as a trial for the deflated Sharpe ratio (8 trials). No
other rule will be added to this comparison. Only a passing candidate, the best by validation Sortino, may be
proposed for the locked test.

Reported too (descriptive, not criteria): each candidate's yearly return with and without A1, to check
@SteveDJacobs' claim that the industry filter helps every year; trades a year; win rate.

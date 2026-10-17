# US stock strategy catalog from X traders: pre-registration

Written and committed on 2026-10-17 **before any return of these strategies
was computed.** The ideas come from docs/research/X_IDEAS_CATALOG_2026-10.md
(Qullamaggie via @Muninn, @FelipeGuirao, @ohiain, @Gaurav_Cx10 / Stockbee,
@SteveDJacobs, Weinstein / Darvas, and BNF). The owner accepts survivorship
bias for this catalog, so **no bias adjustment is applied**; results are
optimistic for that reason.

## Data

- Prices: the local `free_us_daily` catalog (Yahoo; stocks listed in June
  2026). On GitHub the same symbols are downloaded again from Yahoo with
  `auto_adjust=False`, ending 2020-12-31, so no locked data is read. Adjusted
  OHLC = raw OHLC x `adj_close / close`.
- Symbols: those in `company_metadata.parquet` that pass the data checks in
  `research/stock_data_checks.py`. A symbol is dropped if it has non-positive
  prices, OHLC inconsistent on >1% of days, two or more reversing one-day
  spikes (bad ticks), a >50% move on a split day (mis-adjusted split), adjusted
  close above close, or >5% of trading days missing.
- Index: S&P 500 (`^GSPC`); benchmark SPY total return; cash: 3-month T-bill
  index as in the other studies.

## Periods

Warm-up 1993-1994 · Train 1995-2010 (no tuning) · Validation 2011-2020
(pass/fail) · Locked 2021+ (never read; opened once only on owner request).

## Universe (every day)

The 1,500 stocks with the highest 50-day average dollar volume
(`close x volume`), with at least 260 days of history.

## Common filters (trend candidates, unless the table says otherwise)

- `MF` market filter: S&P 500 10-day SMA above its 20-day SMA (Muninn).
- `ADR4`: 20-day average daily range `mean(high/low - 1)` >= 4%.
- `IND50`: stock's industry in the top half of industries by industry RS.
  Industry RS = median IBD-style RS percentile (`2*R63+R126+R189+R252`) of the
  industry's universe members, recomputed every Friday, industries with >= 3
  members ranked as percentiles (Jacobs). Industry = current Yahoo industry.

## Setups (signal at the close of day t; filled at that close, as the
sources enter in the last minutes of the session)

- **S1 felipe_breakout**: EMA8 > EMA20 > EMA50, each above its value 5 days
  earlier; some close below EMA50 within the last 60 days (first leg); the 7
  previous days all closed at or above EMA20 and their high-low range is at
  most 2.5 x ADR; today closes above the 7-day high, with a green body larger
  than yesterday's absolute body, and closes in the top 21.4% of its range.
  Stop: today's low, signal skipped if the stop is more than 2.5 x ADR away.
- **S2 qulla_breakout**: yesterday's close at least 30% above the lowest low
  of the prior 63 days; yesterday's close above SMA10 and SMA20, SMA10 > SMA20,
  SMA20 rising (vs 5 days ago); 10-day high-low range at most 3 x ADR; today
  closes above the prior 10-day high. Stop: today's low, but no further than
  1 x ADR below the close.
- **S3 pullback_921** (ohiain): EMA9 > EMA21, both rising (vs 5 days ago); in
  one of the last 3 days the low touched EMA21 x 1.01 or EMA9 on volume below
  its 50-day average; today closes above yesterday's high and above EMA9.
  Stop: lowest low of the last 4 days.
- **S4 momentum_burst** (Stockbee): close up >= 4% on the day, volume above
  yesterday's, yesterday's range below ADR, close above EMA21. Stop: today's low.
- **S5 episodic_pivot**: open >= 10% above yesterday's close, volume >= 3 x its
  prior 50-day average, close above open, yesterday's close < 1.3 x the close
  126 days earlier, no other >= 10% gap in the prior 63 days. Stop: today's low.
- **S6 darvas_52w**: close above the prior 252-day high with volume >= 1.5 x its
  prior 50-day average. Stop: lowest low of the last 10 days.
- **S7 weinstein_stage2**: close above SMA150, SMA150 above its value 20 days
  earlier, close above the prior 50-day high, volume >= 1.5 x prior 50-day
  average. Stop: lowest low of the last 10 days.
- **S8 bnf_reversion** (mean reversion, own exits): deviation `close/SMA10 - 1`
  in the stock's own lowest 10% of the last 250 days when the stock and the
  S&P 500 are both above their SMA200, otherwise in its lowest 1%. Next day a
  limit buy at yesterday's low minus 0.5 x ADR (strong regime) or 1.5 x ADR
  (weak regime), in dollars of yesterday's close; filled at the lower of the
  open and the limit. Exit at the close when RSI(2) >= 85, or after 3 days if
  below the entry price, or after 5 days. No ADR/IND/MF filters; no stop.

## Exits (plus the setup's stop, checked against each day's low; a stop fills
at the stop or at the open if the stock gaps below it)

- `X5`: sell at the close of the 5th day after entry (Felipe).
- `XS10` / `XS20`: sell at the first close below SMA10 / SMA20 (Muninn).
- `XH3`: sell half at the close of day 3 and move the stop to the entry price;
  trail the rest with XS10 (Qullamaggie's rule, tested by Muninn).
- `XF`: if the close on day 3 is not above the entry, sell; otherwise XS10
  (Gaurav / Stockbee "no follow-through").

## Sizing and costs

Risk 0.5% of equity per trade: `shares = 0.005 x equity / (entry - stop)`,
position capped at 20% of equity, no leverage (entries stop when cash runs
out). When signals exceed capacity, highest stock RS first. S8 positions are
10% of equity each. Costs 10 bps of traded value per side. Cash earns T-bills.

## Candidates (24 trials)

| # | Name | Setup | Exit | Filters |
|---|---|---|---|---|
| 1 | felipe_5d | S1 | X5 | MF ADR4 IND50 |
| 2 | felipe_s20 | S1 | XS20 | MF ADR4 IND50 |
| 3 | qulla_s10 | S2 | XS10 | MF ADR4 IND50 |
| 4 | qulla_s20 | S2 | XS20 | MF ADR4 IND50 |
| 5 | qulla_half3 | S2 | XH3 | MF ADR4 IND50 |
| 6 | pullback_s20 | S3 | XS20 | MF ADR4 IND50 |
| 7 | burst_fast | S4 | XF | MF ADR4 IND50 |
| 8 | burst_5d | S4 | X5 | MF ADR4 IND50 |
| 9 | ep_s20 | S5 | XS20 | MF ADR4 IND50 |
| 10 | darvas_s20 | S6 | XS20 | MF ADR4 IND50 |
| 11 | weinstein_s20 | S7 | XS20 | MF ADR4 IND50 |
| 12-22 | same as 1-11 with suffix `_noind` | | | MF ADR4 (no IND50) |
| 23 | bnf_reversion | S8 | own | none |
| 24 | blend_t | 1/3 each of felipe_5d, pullback_s20, bnf_reversion, rebalanced monthly (Felipe's "Portfolio T") | | |

Benchmarks (not trials): SPY, and the equal-weighted universe.

## Pass criteria (validation 2011-2020)

All three: monthly Sortino of excess returns over T-bills >= 2.0; annualised
return above SPY; maximum drawdown no deeper than -25%. Deflated Sharpe uses
all 24 trials. Only the best passing candidate by validation Sortino may be
proposed for the locked test. The IND50 vs `_noind` comparison is also
reported year by year to check Jacobs' claim.

## Amendment 1 (2026-10-17): trade-level evaluation of every signal

Added at the owner's request after the first local portfolio results were
seen. It changes no setup, exit, filter or criterion above; it only adds a
second, descriptive view of the same 23 rules (the blend is a portfolio and
has no trades of its own).

- **Every signal is traded on its own**, with no capital limit and no
  ranking. The only exclusion: a new signal in a stock that still has an
  open trade from the same rule is skipped (no overlapping trades in one
  stock).
- Same entry, stop and exit rules and the same 10 bps per side as above.
  `XH3` counts as one trade: half the return at day 3 plus half at the final
  exit. S8 counts only signals whose next-day limit order fills. Trades still
  open on 2020-12-31 are closed at that close. Maximum holding 250 days.
- Per trade: net return in %, and R = net return / initial risk
  (`(entry - stop) / entry`; S8 has no stop and reports no R).
- Reported for train and validation (by entry date) and per year: number of
  trades, win rate, average and median return, average R, **profit factor**
  (sum of winning returns / |sum of losing returns|), **total return** (sum
  of all trade returns, i.e. the profit of putting 1 unit in every trade),
  total R, average days held, and the share of total profit from the best 5%
  of trades.
- This view is descriptive: no pass/fail. It answers whether a rule has an
  edge per trade; the portfolio view above answers whether one account can
  trade it.

# Qullamaggie's literal rules on US stocks: pre-registration

Written and committed on 2026-10-18 **before any result of this study was computed**. The research behind the
rules is in [QULLAMAGGIE_RESEARCH_2026-10.md](QULLAMAGGIE_RESEARCH_2026-10.md). Earlier grids (v1-v7) already
tested rough versions (`S2`, `S5`, `S9`) with close entries and generic exits; this study tests his own entry,
stock selection, stop, selling and market rules. Exact rules are the code in `research/qullamaggie.py`.

Unchanged from v1-v7: the price panel (survivors only, owner accepts the bias), 10 bps per side, cash earns
T-bills, 0.5% risk per trade with a 20% position cap (his own range: 0.3-0.5% risk, positions mostly 10-15%,
never above 20%), train 1995-2010, validation 2011-2020 (also split 2011-2015 / 2016-2020), the portfolio pass
criteria on 2011-2020 (monthly Sortino >= 2, CAGR above SPY, max drawdown no deeper than -25%) and the trade-level
statistics (every signal traded on its own). **2021+ is never read.** The Nasdaq Composite (`^IXIC`, Yahoo)
is downloaded up to 2020-12-31 for the market filter.

## Definitions (all from data up to the prior close unless stated)

- `ADR` = mean of `H/L` over 20 sessions - 1 (his formula). `DV` = 20-day mean of close x volume.
- Eligible: close >= $1, `DV` >= $1.5M, `ADR` >= `a`, at least 63 sessions of history.
- Leader scan: percentile of the 21-, 63- and 126-day gains among all panel stocks that day; a stock is a leader
  when it is eligible and in the **top 2% on any of the three**. Watchlist = leader on any of the last 63 sessions.
- Market filter `M1`: Nasdaq Composite SMA10 > SMA20, both higher than the session before. `M0` = no filter.

## Setups

**Breakout (`QBO`)**, on day t:
- on the watchlist; prior move: within the last 63 sessions some close was >= 1.30 x the lowest low of the 63
  sessions before it;
- base: last 5 sessions have a narrower high-low range and a higher lowest low than the 5 sessions before;
  SMA10 > SMA20, SMA20 above its value 5 sessions earlier, close >= SMA20;
- pivot = highest high of the last 10 sessions.
- Fill `STOP` (his entry when the level breaks): when the high reaches the pivot, buy at max(open, pivot). Initial
  stop = entry x (1 - ADR), the widest stop he allows. If the day's low reaches it, the trade is stopped out that
  day (daily bars cannot tell the order, so this is the pessimistic reading). Otherwise the stop moves to the
  day's low (his "low of day" stop) from the next session.
- Fill `CLOSE`: buy at the close if it is above the pivot; stop = the day's low; skipped when the stop is more than
  1 ADR away.

**Episodic Pivot (`QEP`)**, on day t: opens >= 10% above the prior close, volume >= 3 x its 20-day average,
eligible the day before; buy at the close; stop = the day's low, skipped when more than 1.5 ADR away. `N1`
additionally requires a gain below 30% over the prior 126 sessions ("not rallied"), `N0` does not.

**Parabolic short (`QPS`)**, on day t: the prior close is >= 1.5 x (`P50`) or 2 x (`P100`) the lowest low of the
prior 10 sessions, after 3 higher closes in a row; day t closes red (below its open and the prior close); short at
the close, stop = the day's high. Liquidity as above, no ADR or market filter.

## Exits

Longs: `XQ3_10`, `XQ3_20`, `XQ5_10`, `XQ5_20` = sell 1/2 at the close of day 3 (or 1/3 at day 5), move the stop
to the entry price, sell the rest at the first close below the SMA10 (or SMA20), checked from the partial day on.
Until then only the stop applies. Shorts: `XQC10`, `XQC20` = cover at the first close at or below the SMA10
(SMA20). Maximum hold 250 sessions as before.

## Trials (85)

- `QBO_<STOP|CLOSE>_<NOSCAN35|SCAN35|SCAN5>_<M0|M1>_<exit>`: 2 x 3 x 2 x 4 = 48. `NOSCAN35` = eligible with
  ADR >= 3.5% but no leader scan (measures the scan); `SCAN35` / `SCAN5` = leader scan with ADR >= 3.5% / 5%.
- `QEP_<N0|N1>_<A35|A5>_<M0|M1>_<exit>`: 2 x 2 x 2 x 4 = 32.
- `QPS_<P50|P100>_<XQC10|XQC20>`: 4.
- `QCOMBO`: one long book holding both canonical setups (below) with exit `XQ3_10`.

**Canonical (his literal beginner rules, judged first):** `QBO_STOP_SCAN35_M1_XQ3_10`,
`QEP_N1_A35_M1_XQ3_10`, `QPS_P50_XQC10`, `QCOMBO`.

## Reporting

- All 85 trials: trade-level count, win rate, average and median return, profit factor, total return, average R,
  holding days, per period; portfolio Sortino, CAGR and drawdown per period; pass/fail.
- Train-only selection: per setup, the best trial by train monthly Sortino with >= 100 train trades, then its
  validation result.
- Deflated Sharpe over these 85 plus all 248,974 earlier trials (v1-v7).
- Realism checks against his real record: share of breakouts stopped out on the entry day (his: ~37% with the
  10-day exit), median initial stop, win rate (his: 25-31%).

## Execution

GitHub (`qullamaggie.yml`) on the cached price panel: 12 shards (6 breakout, 4 EP, 1 short, 1 combo groups),
4 workers each, then a merge job.

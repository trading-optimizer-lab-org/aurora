# One-shot locked test of the phase 7 intraday combination: pre-registration

Written and committed on 2026-10-19, **before any price, bar or filing from 2021-01-01 onward was read**, on the
owner's explicit request ("probar esa combinación una única vez en el periodo bloqueado 2021+"). The locked
period of the stock studies has never been opened.

## What is tested

`INTRADAY_EQ` from phase 7a ([COMBINATION_RESULTS.md](COMBINATION_RESULTS.md)): the daily equal-weight average of
three streams, built by `combination.intraday_streams` with every rule unchanged:

- `EP_EARN`: Qullamaggie episodic pivots (gap >= 10%, 5-minute opening range, volume pace 0.5, stop at the low of
  the day, exit XQ3_20) on days with an SEC 8-K Item 2.02 filing that day or the session before;
- `EP_NEWS`: the same entries without such a filing, with the "not rallied" filter (N1);
- `BO_TOP3`: the three breakouts a day with the best score from the logistic model trained on 1995-2010 only,
  entered on the opening-range break;
- 0.5% risk per trade, 20% position cap, 10 bps a side, T-bills on cash, one-minute Alpaca SIP bars.

Window: **2021-01-04 to 2026-09-30** (the last complete month before the run). Nothing after 2026-09-30 is read.

## Pass criteria (primary, INTRADAY_EQ at 1x)

1. Monthly Sortino >= 2.0;
2. annualised return above SPY's over the same window;
3. maximum drawdown no deeper than -25%.

Reported for information only: the three components, INTRADAY_EQ at 2x account leverage (as in phase 7c),
SPY, yearly returns, worst month and worst day, and the 2016-2020 values for comparison (Sortino 4.92, 16.5% a
year, max drawdown -7.7%).

## Data for 2021+

- **Daily prices**: the same 4,471-symbol list, downloaded from Yahoo the same way as the panel. Each series is
  spliced onto the cached 1992-2020 panel with one price factor and one volume factor (medians of the ratios over
  October-December 2020, at least 40 common sessions, ratios within 1% of the median); the 2021+ part goes through
  the same data checks as the panel. Symbols Yahoo no longer serves (delisted or renamed since 2020) have no 2021+
  prices, and companies listed after 2020 are not in the list. Both biases are reported with coverage counts.
- **Benchmarks**: ^GSPC, SPY and ^IXIC from Yahoo, spliced the same way; T-bills from FRED.
- **Minute bars**: Alpaca SIP for the candidate days, fetched as in phase 1; kept only in the Actions cache.
- **Filings**: SEC 8-K Item 2.02 dates from 2020-11-01 to 2026-09-30.
- 1992-2020 values are the cached ones unchanged, so the breakout model and every indicator before 2021 are
  identical to phase 7.

## Safeguards

- **Rehearsal gate**: the same code first recomputes EP_EARN, EP_NEWS and BO_TOP3 for 2016-2020 from the caches
  and must match the published streams (`docs/research/data/combination_streams_7a.csv`) within 1e-9. If it does
  not, nothing from 2021+ is downloaded.
- **One opening**: data preparation (downloads, coverage counts, no strategy result) may be retried after a
  failure. Just before the strategy is computed, the workflow uploads an "opened" marker; it refuses to run if a
  marker or a published result exists. Whatever the outcome, the window is then spent for this combination.
- The result is published as it comes out, pass or fail.

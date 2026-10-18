# Qullamaggie phase 1, intraday execution (2016-2020): pre-registration

Written and committed on 2026-10-18 **before any minute data was downloaded or any result computed**. Question:
does his edge come from the execution that daily bars could not test (entering on the opening-range high in the
first minutes, with the real low-of-day stop)? The daily study
([QULLAMAGGIE_RESULTS.md](QULLAMAGGIE_RESULTS.md)) found no edge with daily approximations; it measured a median
initial stop of 5.2% against his 2.5% and 15% same-day stop-outs against his 37%.

Exact rules are the code in `research/qullamaggie_intraday.py`. Everything not stated is as in
[QULLAMAGGIE_PREREGISTRATION.md](QULLAMAGGIE_PREREGISTRATION.md): price panel, eligibility, leader scan, breakout
base conditions, Nasdaq filter, costs (10 bps per side), 0.5% risk, 20% cap, exits after the entry day.

## Data

- One-minute bars, all US exchanges (`feed=sip`, unadjusted), from Alpaca's free historical API (available since
  2016), only for candidate days, plus unadjusted daily bars for the 20-day average volume. **Nothing after
  2020-12-31 is requested.** Minute data stays in the private Actions cache; only reports are published.
- Alpaca prices are put on the panel's adjusted scale with the day's ratio of panel close to Alpaca close. A
  candidate day is dropped when the Alpaca high or low differs from the panel's by more than 3% after scaling,
  when the symbol has no minute bars, or when Alpaca has no daily history; the counts are reported.

## Candidates (from the daily panel, as of the prior close)

- Breakout: the breakout setup of the daily study with the `SCAN35` or `SCAN5` selection, on days whose daily
  high reaches the pivot.
- Episodic pivot: eligible the day before (`A35`), opening >= 10% above the prior close; `N1` also requires a
  gain below 30% over the prior 126 sessions.

## Intraday rules (US Eastern time)

- Opening range of `k` = 1, 5 or 30 minutes (the 30-minute first candle of his 60-minute chart). Entries only
  after the opening range and before 11:00.
- Breakout trigger: max(opening-range high, pivot). EP trigger: the opening-range high, and the volume since the
  open must reach `q` x the 20-day average daily volume x min(1, minutes elapsed / 15), `q` = 0.5 or 1 (his
  "trade the average daily volume in the first 15-20 minutes").
- Fill: the first minute whose high exceeds the trigger, at max(trigger, that minute's open).
- Stop: the lowest low from the open through the entry minute (his low of day). Skipped when wider than 1 ADR
  (breakout) or 1.5 ADR (EP), as in his rules.
- Same day: stopped out at min(minute open, stop) in the first later minute whose low goes below the stop.
  Otherwise the stop stays there and the daily exits take over from the next day (`XQ3_10`, `XQ3_20`).

## Trials (48)

- `IBO_<SCAN35|SCAN5>_<M0|M1>_K<1|5|30>_<exit>`: 2 x 2 x 3 x 2 = 24.
- `IEP_<N0|N1>_Q<05|10>_K<1|5|30>_<exit>`: 2 x 2 x 3 x 2 = 24 (no market filter: it hurt EPs daily).

## Reporting

- Periods 2016-2018, 2019-2020 and 2016-2020. Trade-level and portfolio statistics as before; pass criteria
  (monthly Sortino >= 2, CAGR above SPY, max drawdown no deeper than -25%) on 2016-2020.
- Reference (not trials): the daily-bar versions of the same setups on 2016-2020.
- Realism: same-day stop-outs (his ~37%), median stop (2.5% / 3.8%), median entry minute (his 10), win rate.
- Deflated Sharpe over these 48 plus all 249,059 earlier trials.

## Limits

2016-2020 was already seen in daily form (it is part of the 2011-2020 validation), so a positive result here is
a lead, not proof. The clean tests remain forward paper trading and the locked 2021+ period, used once and only on
the owner's request.

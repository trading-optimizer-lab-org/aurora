# US stock strategy catalog v3 (wide grid): pre-registration

Written and committed on 2026-10-17 **before any v3 result was computed**,
after v1 and v2 results were seen. Everything not stated here (data, data
checks, universe, indicators, filters, setups S1-S9, exits, costs, sizing,
engines, trade-level view, periods) is as in
docs/research/STOCK_CATALOG_PREREGISTRATION.md (with Amendment 1) and
docs/research/STOCK_CATALOG_V2_PREREGISTRATION.md. Survivorship bias is not
adjusted (owner's choice). Locked period 2021+ is never read.

## Honest use of a wide grid

v3 tests hundreds of combinations, so some will look good by luck. Therefore:

1. **Selection uses the train period only (1995-2010).** Candidates with at
   least 300 train trades are ranked by train trade-level profit factor; the
   top 15 are the "train-selected" set.
2. Validation (2011-2020) is then reported for that set, and for everything
   else. Validation was partly seen in v1/v2, so a validation pass is only a
   reason to propose the locked test, never a result on its own.
3. Deflated Sharpe counts every v3 trial plus the 38 of v1 and v2.

## New setups (signal at the close of day t, filled at that close)

- **S10 vcp** (Minervini): the Trend Template of the SEPA study (close above
  SMA150 and SMA200, SMA150 > SMA200, SMA200 above its value 21 days earlier,
  SMA50 > SMA150 and SMA200, close > SMA50, close >= 1.3 x 52-week low and
  >= 0.75 x 52-week high, RS >= 70); three contracting 10-day ranges
  (`(max high - min low) / close` of days t-10..t-1 < days t-20..t-11 <
  days t-30..t-21); volume dry-up (mean volume of t-10..t-1 below 0.75 x its
  prior 50-day average); close above the high of t-10..t-1 with volume >= 1.5
  x the prior 50-day average. Stop: lowest low of t-10..t-1; skipped if more
  than 3 x ADR away.
- **S11 nr7**: yesterday's high-low range is the smallest of the last 7 days;
  yesterday's close above SMA50 and SMA50 above its value 10 days earlier;
  today closes above yesterday's high. Stop: yesterday's low.
- **S12 high52**: close at least 0.98 x the highest close of the last 252
  days, RS >= 80, close above SMA50. Stop: close x (1 - 2 x ADR).
- **S13 gap_go**: open >= 4% above yesterday's close, close above open,
  volume >= 2 x prior 50-day average, STAGE2. Stop: today's low.
- **S14 high_tight_flag** (Minervini "power play"): the highest close of
  t-50..t-10 is at least 1.9 x the lowest close of t-60..t-40; the 10 days
  t-10..t-1 range within 25% of their high; today closes above that high.
  Stop: lowest low of t-10..t-1.
- **S15 connors_rsi2**: close above SMA200 and RSI(2) below 10. Exit `XRSI`:
  first close above SMA5. Stop for sizing and protection: close x (1 - 3 x ADR).
- **S17 breakdown_short**: close below SMA150, SMA150 below its value 20 days
  earlier, close below the lowest low of the prior 50 days, volume >= 1.5 x
  prior 50-day average. **Short** at the close. Stop: highest high of the prior
  10 days; skipped if more than 3 x ADR away.

## New exits

- `XT3`: trailing stop at the highest close since entry x (1 - 3 x ADR at
  entry), raised after each close, checked against the next days' lows (the
  setup's initial stop still applies).
- `XRSI`: sell at the first close above SMA5 (S15 only).
- `XC20` (shorts): cover at the first close above SMA20.

## Grid (326 trials)

| Block | Setups | Exits | Filter sets | Trials |
|---|---|---|---|---|
| Long grid | S1, S2, S2T, S3, S4, S5, S6, S7, S10, S11, S12, S13, S14 | X5, XS10, XS20, XS50, XH3, XT3 | F0 none; F1 MF; F2 MF+IND50; F3 MF+IND50+ADR4 | 13 x 6 x 4 = 312 |
| Connors | S15 | XRSI | F0-F3 | 4 |
| Mean reversion | S8 (all), S8L (500 largest, stop) | own | none | 2 |
| Shorts | S9, S17 | S9: XPS, X5 · S17: XC20, X5 | none; ADR4 | 8 |

All filter sets include the universe. Names: `<setup>_<exit>_<filterset>`,
e.g. `S7_XS50_F2`.

## Pass criteria

As in v1: validation monthly Sortino >= 2.0, annualised return above SPY,
maximum drawdown no deeper than -25%. Only a train-selected candidate that
passes may be proposed for the locked test, on the owner's request.

## Execution

On GitHub only (`stock-ideas-v3.yml`), split into 12 parallel shards by setup
on the cached price panel, plus one job that merges the shards, applies the
selection rule and writes the report.

# US stock strategy catalog v4 (larger grid): pre-registration

Written and committed on 2026-10-17 **before any v4 result was computed**,
after v1-v3 results were seen. Everything not stated here (data, checks,
universe, indicators, costs, sizing at 0.5% risk / 20% cap, engines,
trade-level view, periods, pass criteria, train-only selection of the top 15
with >= 300 train trades) is as in the v1-v3 pre-registrations. Survivorship
bias not adjusted (owner's choice). Locked period 2021+ never read.

## Setups (16)

Kept from earlier catalogs (best or most stable): S1 felipe_breakout, S3
pullback_921, S6 darvas_52w, S7 weinstein_stage2, S12 high52, S13 gap_go,
S14 high_tight_flag. New:

- **S18 pocket_pivot** (Morales/Kacher): up close; volume above the largest
  down-day volume of the prior 10 days; close above SMA10 and SMA50; SMA50
  above its value 10 days earlier; close less than 5% above SMA10. Stop:
  lowest low of the last 3 days.
- **S19 ema_cross** (Seykota-style trend): EMA20 crosses above EMA50 today
  and close above SMA200. Stop: close x (1 - 3 x ADR).
- **S20 turtle55** (Donchian): close above the highest high of the prior 55
  days. Stop: close x (1 - 2 x ADR).
- **S21 squeeze** (Bollinger): band width `4 x std20 / SMA20` within 5% of
  its 120-day low on any of the prior 5 days; close above the upper band
  (SMA20 + 2 x std20); volume >= 1.5 x prior 50-day average. Stop: SMA20.
- **S22 ema21_reclaim** (Kell): EMA10 > EMA21 > SMA50, SMA50 above its value 10
  days earlier; yesterday closed below EMA21 and today closes above it. Stop:
  today's low.
- **S23 big_gap_quiet**: open >= 8% above yesterday's close, volume >= 4 x
  prior 50-day average, close in the top 25% of the day's range, yesterday's
  close below 1.2 x the close 63 days before it. Stop: today's low.
- **S24 leader_dip**: RS >= 90, three consecutive lower closes (today and the
  two days before), close above SMA50, SMA50 above its value 10 days earlier.
  Stop: close x (1 - 2 x ADR).
- **S25 ipo_breakout** (O'Neil / Gaurav): stocks with 20 to 250 days of
  history whose 20-day average dollar volume ranks within the top 1,500;
  close above the highest high since listing (before today) with volume >= 1.5
  x the prior 20-day average. Stop: lowest low of the last 10 days. This setup
  uses its own young-stock universe instead of the standard one.

## Exits (8)

- `XS20`, `XS50`, `XT3` as before.
- `XE21`: sell at the first close below EMA21 (Kell).
- `XT2` / `XT5`: trailing stop at the highest close since entry x
  (1 - 2 or 5 x ADR at entry).
- `XS50T60`: XS50, or sell at the close of day 60 at the latest.
- `XO25` (O'Neil profit-taking): sell half when the price reaches +25%
  (fills at the target, or the open if it gaps above), then trail the rest
  with XS50.

## Filter sets (6)

All include the standard universe (S25 its own one).

| Set | Filters |
|---|---|
| G0 | none |
| G1 | MF + IND50 + ADR4 (v3's best set) |
| G2 | SPX200 (S&P 500 above its SMA200, O'Neil's "M") + IND50 + ADR4 |
| G3 | MF + IND85 + ADR4 |
| G4 | MF + IND50 + ADR4 + RS80 (stock RS >= 80) |
| G5 | MF + IND50 + LIQ500 (500 largest by dollar volume; no ADR filter) |

## Grid

16 setups x 8 exits x 6 filter sets = **768 trials**, named
`<setup>_<exit>_<set>`. Deflated Sharpe over these plus the 364 of v1-v3
(1,132). Besides the train-only selection, the report lists, descriptively,
trials with PF >= 1.3 and >= 200 trades in **both** periods.

## Execution

GitHub only (`stock-ideas-v4.yml`), one shard per setup (16 parallel jobs)
on the cached price panel, plus a merge job.

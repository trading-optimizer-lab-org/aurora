# v15: real borrow availability and the after-hours session: pre-registration

Written and committed on 2026-10-20, before any v15 result was computed, at the owner's request ("Si" to adding
real borrow costs and after-hours data). v14 found one family with a walk-forward Sortino above 4, B8 `GAPFADE`
(4.85 at the middle costs), whose result depends on the cost of shorting; and it had no after-hours data. v15
measures shortability from IBKR's own records and tests four after-hours ideas. Everything else is as in
[V14_PREREGISTRATION.md](V14_PREREGISTRATION.md): universe, periods (design 2016-01-04 to 2023-06-30; sealed
2023-07-01 to 2026-10-16, opened only when the owner asks), placebos, walk-forward, gate, combination, criteria.
Exact rules are the code in `research/v15_ah.py` and `scripts/run_v15*.py`.

## 1. Data (`scripts/run_v15_data.py`)

- Alpaca SIP minute bars 16:00-19:59 ET on every v14 event day, every day with a close-to-close rise of 40% or more
  (raw close $1-$20) and every 8-K item 2.02 day of a stock with a 20-day dollar volume of $1M or more; and
  04:00-09:29 bars on the day after such a rise when v14 did not already have them.
- iBorrowDesk (IBKR's published availability and fee) for every symbol of the v14 small-cap event days from
  2025-10-21, the start of what it keeps, to 2026-10-16. It returns nothing for delisted symbols, so the
  calibration comes from survivors; delisted small caps were probably harder to borrow, so the availability it
  gives is probably too high (the result is optimistic in that respect). Only availability and fees are read from
  this window, never a return; the calibration needs the raw open and shares outstanding of those days, also read.

## 2. Availability and fee model (calibration)

For each calibration event (symbol-day of the v14 gap-up, runner or day-2 scopes, raw open $1-$20): IBKR shares
available at the open = the day's opening figure if published, else the last figure before that day. The event is
**borrowable** if that is at least max(1,000, $10,000 / raw open). Cells: raw open {< $2, $2-5, $5-10, $10-20} x
shares outstanding {unknown, < 10M, 10-50M, > 50M}; a cell with fewer than 30 events takes its price band's pooled
figures. Per cell: **p** = share borrowable, **fee** = median annual borrow fee of the borrowable events.

## 3. Cost models

- **R1 (an IBKR-like account):** the v14 middle half-spreads by price tier and $0.005 a share; no locate fee; an
  intraday short pays no borrow (no position at the close); an overnight short pays the cell's fee / 360 a night;
  every short's weight is multiplied by its cell's p (its expected availability). After-hours fills pay twice the
  half-spread.
- **R2:** R1 with half-spreads x1.5.

## 4. Hypotheses (104 configurations)

- `B8R1` and `B8R2`: the 36 B8 `GAPFADE` configurations of v14 under R1 and R2. 72.
- AH1 `AHFADE`: a close at least {40, 80}% above the prior close (raw close $1-$20); short at the close of the first
  after-hours bar (16:00-17:59) that closes {2, 5}% or more below the regular close; stop at the regular session's
  high (checked on the after-hours bars and at the next open); cover at the next open. R1. 4.
- AH2 `B8LATE`: B8 with the 5-minute-low entry, gap {30, 50, 100}%, premarket dollar volume {$250k, $1M}, covered at
  {16:00, 17:00, 19:55} (the stop stays live in the after-hours bars). R1. 18.
- AH3 `EARNAH`: 8-K item 2.02 days, raw close >= $3, 20-day dollar volume >= $5M, after-hours dollar volume (16:00-
  17:59) >= $500k; m = price at 17:59 / regular close - 1, |m| >= {3, 6}%; trade {the next session open to close
  with m, the next session open to close against m, from 18:00 to the next open with m}. R1. 6.
- AH4 `NIGHTPM`: a close at least {40, 80}% above the prior close (raw close $1-$20); short at the close; cover at the
  next day's premarket price at {08:00, 09:25} (the last bar at or before it; none: the open). R1. 4.

Sizing: AH1, AH3, AH4 take 5% of equity per trade, at most 10 a day, gross at most 100%; AH2 and B8R* use the v14
intraday sizing. All 104 count as trials for the deflated Sharpe.

## 5. Placebos, selection, combination, criteria

- Placebos (200 per configuration): B8R*, AH2: as B8 in v14; AH1, AH4: the trade moved to a random runner of the same
  day (close >= +20%, raw close $1-$20) with the same entry time and rule; AH3: to a random other liquid stock with
  after-hours bars that day, same direction rule.
- Walk-forward, gate and combination exactly as v14. `COMBO15` = the v14 families with B8 replaced by `B8R1`, plus
  the v15 families.
- Success: as v14 for `COMBO15`. The specific question of v15: does `B8R1` keep a walk-forward Sortino of at least 4
  and pass the gate (placebo p <= 0.05 in at least two thirds of its years)?

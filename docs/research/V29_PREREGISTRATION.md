# v29: a $5,000 TradeZero account for one year: pre-registration

Written and committed on 2026-10-23, before any v29 result was computed, at the owner's request: a $5k TradeZero
account run by code through the API, the highest profit a year ahead with a chance of ruin of 1% or less, with
realistic costs (plan approved with "si"). The trades are COMBO28's members of
[V28_RESULTS.md](V28_RESULTS.md), the picks of the v28 report (run 39915126980), unchanged: v29 builds the account,
not new signals. Exact rules: `scripts/run_v29.py` (on `scripts/run_v28_after.py`), the IEX data in
`scripts/run_v29_iex.py`; tests in `tests/test_v29.py`. Workflows: `v29.yml`, `v29-canary.yml`, `v29-iex.yml`.

## 1. TradeZero International's costs (its fee schedule as of 2026-10-01)

- **Commissions**: $0.005 a share, at least $0.49 and at most $7.95 an order, on both orders of every trade (entries
  at an open or a level and stop exits are marketable; the free resting-limit rule is not assumed). SEC fee $0.0000206
  of the sale value, FINRA TAF $0.000249 a share sold, the reporting fee ($0.00005 a share, at least $0.01) on both
  orders. Half-spreads: R4 with v26's extended-session legs, as in v28.
- **Shares**: a position is `floor(weight x equity / price)` shares; a trade of less than one share is not taken.
- **Locates**: once a trade, as a fraction of its value, by the name's state at the entry (all known by then):
  - HOT: on the Reg SHO threshold list in the five sessions before, or an open at least 50% over the prior close, or
    a prior close at least twice the 20-session low, or short interest at least 20% of the shares outstanding;
  - ETB (easy to borrow, no locate): not HOT, price $10 or more, at least 50 million shares, $20M of prior 20-day
    dollar volume;
  - HTB: the rest.
  The locate prices are unknown before the account exists, so they are a grid: HTB 0.25/0.5/1/2%, HOT
  1/2/3/5/8%. **Base: HTB 1%, HOT 3%.** Sell-back credit on trades closed the session they open: 0 (base), 25%, 50%.
  Extra unavailability of HOT locates: 0 (base; R4 already scales by availability), 25%, 50% (seeded).
- **Overnight borrow**: R4's (v15's table, doubled, at least 100% a year), charged on whole hundreds of shares (odd
  lots round up, as TradeZero states).
- **Margin**: TradeZero International's by price (v28 section 6), gross at most 2x.
- **Fixed costs in dollars**: a server, $6 a month, always; real-time SIP data (Alpaca Algo Trader Plus), $99 a month,
  only in the PAID plan. The API is free; ZeroPro is not needed. Margin interest is not charged (shorts borrow no
  cash). Taxes are not modelled.

## 2. Two data plans

- **FREE**: only the members whose entries are decided on daily data (v19/v20 daily specs and the C event shorts:
  orders for the open or the close); no extended-session stops (nobody watches the night); no data fee.
- **PAID**: all members (intraday 1-minute entries and the premarket entries need real-time data), the picks'
  extended-session stops with one bar of latency: a stop seen on a night bar is filled at the next night bar's open
  (only limit orders work at night), or at the next session's open when the night has no later bar. Data fee charged.

## 3. One year from $5,000

- The daily return of a book depends on the equity through the share rounding, the commission minimum and the
  liquidity caps, so every book is computed at five equity levels: $2.5k, $5k, $10k, $25k, $60k. A path uses the
  level at or below its equity (the $2.5k level below it).
- **Paths**: 4,000 stationary block-bootstrap paths of 252 sessions (mean block 20 sessions, seed 29) from the
  walk-forward 2018-01-01 to the data's last day; equity starts at $5,000, moves by the book's return of its level,
  pays the fixed costs each session (a month's cost x 12 / 252); a session losing more than the equity ends the path.
- **Ruin**: the equity at or under $1,250 (-75%) at any time in the year. Also reported: under $2,500 (-50%), the
  chance of ending under $5,000, the 10th and 90th percentiles.
- **The choice**: the highest median ending equity with a chance of ruin of at most 1%, at the base costs (middle
  spreads, base locates), for each plan and overall. A safer twin (a chance of -50% of at most 1%) is reported.
- Also reported for each choice: the historical path from $5,000 on 2018-01-02 with the levels, and every historical
  twelve-month window starting in a month of 2018-01..2025-10 (worst, median).

## 4. Construction grid

Plan (FREE, PAID) x risk 0.5/1/1.5/2/3/4% x cap 5/10/20/40% x at most 5/10/20 open x at most 3/5 new a day x gross
1/2x x price floor none/$2.50 x **no night in HOT names** off/on (skip a HOT trade that would be held over a close) x
**locate gate** off/on (skip a trade whose locate is at least its family's mean net return a trade in the earlier
years of the book; nothing skipped in the first year). Order of entry by the size of the move (A28's), no sector cap,
v26's book rules otherwise. 4,608 books.

## 5. Battery around each choice

The locate grid (20 cells), sell-back credit 25/50%, HOT unavailability 25/50%, spreads x1.5/x2 and the high costs,
PAID with v28's stops (no latency) and with no extended-session stops, PAID without the data fee, a sleeve of v10's
SPY 3x trend pick (LT; 25% or 50% of the equity, margin 75% of it; LT was chosen on data up to 2020, so 2018-2020 are
in its sample), starts of $2.5k and $10k, the 50 worst trades at $5k.

## 6. Free real-time data (IEX), measured, not chosen

Whether the intraday members still work when their signals come from IEX's free real-time feed instead of SIP.
`v29-iex.yml` downloads Alpaca's IEX one-minute bars (04:00-15:59) of every symbol of the v18 event store, the v23
liquid store and the v24 mover store on a seeded random order of days, within a 300-minute budget; the coverage is
reported. The evaluation (code committed before it runs): on the covered days, each intraday member's entries are
recomputed on stores whose bars are IEX's (each day's open, gap and premarket facts recomputed from them; the prior
days' facts kept), filled on SIP's bars at the first bar at least one minute after the IEX signal bar, at its open,
with the captured stop distance; compared with the SIP entries on the same days: trades, mean net return a trade,
Sortino of the stream. If IEX keeps at least 80% of the mean net return a trade and 70% of the trades, a FREE+IEX
plan is a candidate for v30. It does not enter v29's choice.

## 7. Caveats fixed now

The construction is chosen on the same 2018-2026 walk-forward stream it is measured on (as in v28); DSR 0; the
2023-07+ window is not clean for the researcher; locates are a grid, not quotes; entries at a close use that close
(all versions); the trades are the walk-forward picks of a search of 466,074 configurations.

## 8. Notes added before the IEX result (2026-10-24, after the download covered all 2,712 days)

- Section 6's evaluation is `scripts/run_v29_iex_eval.py` (`v29-iex-eval.yml`): the B intraday members of COMBO28
  (C:PM uses the premarket store, which was not downloaded, so it is left out); the criterion is pooled over those
  members, trade-weighted (per family shown); a candidate with no IEX bar that session is dropped (the bot would
  see nothing); SIP entries one minute late are shown for reference (not part of the criterion); v28's R4 middle
  costs; index minute bars stay SIP's.

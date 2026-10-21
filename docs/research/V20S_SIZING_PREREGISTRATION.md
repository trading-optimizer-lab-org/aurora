# v20s: position sizing of v20's RU stream: pre-registration

Written and committed on 2026-10-21, before any v20s result, at the owner's request ("hazlo ahora con RU (v20)"),
after v19s (V19S_RESULTS.md). Exact rules: `scripts/run_v19s.py --study ru`; tests in `tests/test_v19s.py`.

## Fixed

- The trades: v20's RU walk-forward stream (docs/research/data/v20_summary.json: each year's RU_RUNUP pick, chosen on
  earlier data only): short a small cap that has risen 150-300% within one to five sessions, held 2 to 20 sessions
  (out at a 30% or 50% target, a close above the prior day's high, or the time limit), every pick without a stop.
  Nothing is re-selected.
- Costs: R4, middle and high (half-spreads x2, borrow fees x3); borrow availability x0.8 and doubled fees with a 100%
  floor for overnight shorts; v19's short-sale charge for daily shorts opened 10% or more under the prior close.
- Liquidity: at most 1% of the 20-day dollar volume a position (v19's daily cap, on the starting account); at most 20
  positions open.

## Grid (168 books)

RU has no stop to size by, so the lever is the position size: 2.5%, 5% (v20's), 7.5%, 10%, 15%, 20%, 30% of the
account; gross exposure cap 1x, 1.5x, 2x, 3x; account $25,000, $100,000, $250,000; middle and high costs.

## Measures and choice

As v19s after its amendment: walk-forward 2018-2026 statistics (a day losing more than the account ends the book), a
stationary block bootstrap of 2,000 ten-year paths (the chance of 50%, 75% and 90% drawdowns), the yearly return on
fixed capital. **Choice**: for each account size, the highest median bootstrap CAGR at the middle costs among the
books with a chance of a 75% drawdown within ten years of at most 1% (middle costs) and gross exposure of at most 2x.

## Caveats stated in advance

RU's period and picks were seen before; no pick has a stop (its worst trade lost 397% of the position), so the
loss of one squeeze is about four times the position size; borrow for weeks in names that have just risen 150-300%
is the least measured cost of the series.

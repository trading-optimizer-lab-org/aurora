# v26s: sizing COMBO26 in one account with CenterPoint's commissions: pre-registration

Written and committed on 2026-10-22, after v26's results (docs/research/V26_RESULTS.md) and before any v26s result,
at the owner's request ("quiero aumentar el sizing porque hay mucho margen para hacerlo ... asume los costos por
accion de centerpoint"). Exact rules: `scripts/run_v26.py` (its `book` and `final` stages, unchanged except the
commission), workflow `.github/workflows/v26s.yml`.

## What changes from v26's one-account book

- **Commission**: CenterPoint's published rate, $0.003 a share a leg (under 500,000 shares a month), in place of R4's
  $0.0065. CenterPoint charges routing (ECN) fees on top, not published per venue; so a second scenario adds $0.003 a
  share for taking liquidity ($0.006 a leg). SEC and FINRA fees as in R4.
- **Sizing grid**: risk to the stop 0.25%, 0.5%, 1%, 1.5%, 2%, 3%, 4%, 6% (the daily 5% cap scaled alike); position caps
  20/40/60/100%; gross caps 1/1.5/2/3x; accounts $25k/$100k/$250k; middle and high costs (spreads x2, borrow x3).

## Fixed (as v26)

The trades of book A: COMBO26's members each year with their v26 picks (v26-report of run 39731260564), one position a
symbol, at most 20 open, v14's liquidity caps on the account, R4 spreads with the measured extended-session legs,
borrow from IBKR's table (availability x0.8, doubled fees): **CenterPoint's locate fees are not modelled** (not
published). Block bootstrap of 2,000 ten-year paths; a day losing more than the account ends the book.

## Choice (the owner's rule of v19s)

For each account and commission scenario: the highest median bootstrap CAGR at the middle costs with a chance of a
75% drawdown in ten years of at most 1% and gross exposure of at most 2x. The report also gives each book's yearly
return on the fixed starting capital (compounded CAGRs overstate it under liquidity caps) and the high-cost twin.

# v19s: position sizing of COMBO19 in one account: pre-registration

Written and committed on 2026-10-21, before any v19s result, at the owner's request ("es absurdo un drawdown tan bajo
de 3,9. quiero que sea lo mas alto posible bajando el riesgo de bancarrota al minimo al mismo tiempo"). Exact rules:
`scripts/run_v19s.py`; tests in `tests/test_v19s.py`.

## Why

COMBO19 (V19Q_RESULTS.md: Sortino 7.86, 16% a year, drawdown -3.9%) is an inverse-volatility average of its member
families' books: each family's book is sized for a whole account (0.5% risk to the stop, 20% cap, 100% gross) and then
weighted by about a quarter, so the account runs at roughly a quarter of the exposure its rules allow. The question:
how much more return is available, trading every member in one account, before the risk of ruin becomes material.

## Fixed

- The trades: v19r's walk-forward picks (docs/research/data/v19r_summary.json: each year, the members of COMBO19 and
  each family's pick for that year, chosen on earlier data only), traded together in one account. Nothing is
  re-selected.
- Costs: R4 (v21's calibration on 27,782 measured quote legs), middle and high (half-spreads x2, borrow fees x3);
  borrow availability x0.8 and doubled fees for overnight shorts; the short-sale restriction as in v19.
- Liquidity: at most 2% of the dollar volume traded before an intraday entry and 1% of the 20-day dollar volume for a
  daily one (v14's caps, as a fraction of the account, so a bigger account is held back more). At most five intraday
  trades a day a family, 20 positions open.

## Grid (336 books)

- risk to the stop per intraday trade: 0.5% (v19's), 1%, 1.5%, 2%, 3%, 4%, 6% (daily trades' 5% position cap scaled
  in proportion);
- cap on one position: 20%, 40%;
- cap on the account's gross exposure: 1x, 1.5x, 2x, 3x;
- account: $25,000, $100,000, $250,000;
- costs: middle, high.

## Measures

Walk-forward 2018-2026: monthly Sortino, CAGR, maximum drawdown, worst day and month. Ruin: a stationary block
bootstrap (mean block 20 sessions) of 2,000 ten-year paths of the book's daily returns, the same draws for every book:
the chance of a 50% and of a 90% drawdown within ten years, the median and 5th-percentile CAGR. Squeeze: the loss if
the largest position (the cap) doubles against the book.

## Choice (stated in advance)

For each account size: the book with the highest median bootstrap CAGR at the middle costs among those whose
high-cost twin has a chance of a 50% drawdown in ten years of at most 1%, with a position cap of at most 40% (a
squeeze costs at most 40% of the account) and gross exposure of at most 2x (Reg T for overnight shorts; IBKR asks more
margin for low-priced and volatile small caps, so 2x may not be available on every name).

## Caveats stated in advance

The picks and their period were seen before (no clean window); the bootstrap reshuffles history and cannot produce a
squeeze bigger than the worst one in the sample; borrow availability is a current IBKR snapshot, and bigger positions
need more shares to borrow than the snapshot guarantees.

## Amendment before any result (2026-10-21, the owner's request)

The first run (39606676199) computed the books and then failed while writing the report (a book whose equity went
below zero made its CAGR undefined); none of its numbers was read. At the owner's request ("elimina esto" for the
position-cap limit; "pon esto con costes realistas ... con 75% de caida en vez de 50"; "con mas servidores y cpu"):

- the cap on one position is no longer limited by the choice; the grid adds 60% and 100% caps (CAPS 20/40/60/100%);
- the ruin condition is a chance of a **75%** drawdown within ten years of at most 1% at the **middle (R4)** costs;
  the gross cap of 2x stays; the high costs are still reported;
- a day that loses more than the account ends the book (equity stays at zero, CAGR -100%);
- the grid runs as 84 parallel jobs (one per account, risk and cap; 4 processes each for the picks' trades), then a
  report job. Grid otherwise as above: 7 risks x 4 caps x 4 gross caps x 3 accounts x 2 costs = 672 books.

# v29 results: a $5,000 TradeZero account for one year

Pre-registered in [V29_PREREGISTRATION.md](V29_PREREGISTRATION.md). Run 39999263970 (canary 39997337216 on v28's
test summary; IEX data run 39997337207, section 6, evaluated later). Full report: the run's `v29-report` artifact;
data: `data/v29_summary.json`. 4,608 books, all shards succeeded.

## Summary

- **The choice is FREE** (daily-data members only, no data fee, no night stops): risk 2% (the 20% cap binds, so
  2-4% are the same book), cap 20%, at most 20 open and 3 new a session, gross 2x, no names under $2.50. One year
  from $5,000: **median $12,831** (p10 $4,482, p90 $31,569), chance of ruin (-75% at any time) 0.5%, of touching
  -50% 10.1%, of ending under $5,000 12.3%. Historical twelve-month windows (94): median $11,610, worst $1,913,
  9.6% end under $5,000. Worst day of the $5k-level stream -52%; worst trade -21% of the account (DS1, 2020-06-16).
- **Safer twin** (a chance of -50% of at most 1%): FREE, risk 1%, cap 10%, at most 5 open, locate gate on: median
  $7,349 (p10 $4,362), ruin 0.0%, -50% 0.5%, loss 17%.
- **PAID loses**: its best book ends at a median of $4,890 (loss in 51.6% of paths). The $105 a month is 25% of the
  account (without it the median is $6,726), and the intraday members' small edge a trade does not cover 1-3%
  locates. Its battery collapses under almost any change (the choice is a lucky point of the grid).
- **What decides it is the HOT locate**: 1,109 of FREE's 1,325 trades at $5k are HOT and they carry nearly all
  the profit. FREE meets the ruin rule with HOT locates up to 3% (median $12-13k); at 5% ruin is 1.8-2.0%
  (median ~$9k); at 8% it fails (ruin 7%, median ~$5k). HTB locates barely matter.
- **Other risks**: spreads x2 -> median $10,221, ruin 1.3%; the high costs (spreads x2, borrow x3) -> median
  $4,759, ruin 10%. Overnight borrow on HOT names is the second unknown. Sell-back credit hardly helps FREE (its
  trades are held overnight). SPY 3x sleeve: +$600 median, same ruin.
- The historical 2018+ path ($30M) is not meaningful: above $60k the books use the $60k level's liquidity caps.

## Caveats

The construction was chosen on the stream it is measured on; DSR 0; locate and borrow prices are assumptions until
quoted; 2023-07+ is not clean for the researcher; the members come from a search of 466,074 configurations.

## Section 6: free real-time data (IEX), run 40076893288

Download 39997337207 covered all 2,712 days; 349,744 of 556,679 candidate symbol-days (63%) had IEX bars that
session. Signals on IEX's bars, fills on SIP's one minute later, v28's R4 middle costs, the same picks
(`data/v29_iex_summary.json`; table in the run's `v29-iex-report` artifact).

| pooled over 19 intraday members | SIP (v28) | SIP 1 minute late | IEX |
|---|---|---|---|
| trades | 57,914 | 57,913 | 35,830 (62%) |
| mean net return a trade | 2.63% | 2.50% | 3.09% (118%) |

**The criterion is not met**: IEX keeps more than enough return a trade but only 62% of the trades (70% needed).
The trades it loses are the candidates with no IEX print; those it keeps are better a trade (names liquid enough to
print on IEX). Sortinos fall in 14 of 19 families (fewer trades); SQ keeps only 100 of 2,747. The minute of latency
alone costs little (2.63% -> 2.50%). So a FREE+IEX plan is not a v30 candidate under the pre-registered rule.

# v56 results: the locate fill rate for 150% a year at 5% ruin

Run 42066001391 (2026-11-05), pre-registered in V56_PREREGISTRATION.md. 48 books under TZC, close entries decided
on v55's IEX bars, 31 seeds, one-year paths from $5,000, ruin at or under $1,250.

## Answer: MET only if TradeZero fills every locate (W0)

| world (HOT / HTB fail) | chosen on 2018-2022 | 2018-2026 median | ruin base / HOT5 | 2023+ median / ruin | MET |
|---|---|---|---|---|---|
| W0 (0% / 0%) | DS0.20-NS0.60-RU0.25 | $13,041 (+161%) | 1.0% / 1.0% | $11,645 / 1.4% | **MET** |
| W10 (10% / 2%) | DS0.20-NS0.60-RU0.25 | $11,848 (+137%) | 0.8% / 0.8% | $10,651 / 1.3% | NOT MET |
| W25 (25% / 5%) | DS0.30-NS0.60-RU0.25 | $10,731 (+115%) | 9.2% / 9.3% | $8,875 / 20.4% | NOT MET |
| W50 (50% / 10%) | DS0.30-NS0.60-RU0.25 | $8,821 (+76%) | 8.3% / 8.5% | $7,018 / 17.9% | NOT MET |

In W0 the book chosen on 2018-2022 is also the hindsight best at all-sample ruin of 5% or less. Hindsight bests in
the other worlds: W10 the same book, W25 the same book at $10,142 (+103%) with 0.8% ruin, W50 DS0.30-NS0.60-RU0.20 at
$9,304 (+86%) with 1.4% ruin.

## Reading

- 150% a year at 5% ruin needs locates that almost never fail: between W0 (+161%) and W10 (+137%) the target is
  crossed at a HOT failure rate of roughly 5%. The real rate has to be measured on TradeZero's quotes.
- The chosen book sits on a cliff. One step up in DS (DS0.30-NS0.60-RU0.25) has 11% ruin in W0; one step up in NS
  (NS0.80) 6%; RU0.25 is the top of the grid. In W50 the same book has 7.5% ruin, against 1.0% in W0. If real
  failures are worse than measured, or cluster on the best trades, the book falls off the cliff.
- Books above $13,041 in W0 all have ruin of 5.5% or more (top: DS0.30-NS1.00-RU0.25, $14,546, 16%).
- Caveats as pre-registered: locate failures drawn at random, not clustered on the hottest days; 48 books on seen
  years; per-share locate prices as v50.

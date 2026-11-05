# v56: how many locates must TradeZero fill for 150% a year at 5% ruin: pre-registration

Written and committed on 2026-11-05, before any v56 number was computed. The owner asks for the book with the
highest annual return at a ruin of 5% or less, and at least 150% a year. v50 found that the largest cost under
TradeZero's rules is an assumption, not data: locates failing on 50% of HOT and 10% of HTB trades. Without failed
locates v49's book makes $12,731 from $5,000 (+155%) at 0.1% ruin. TradeZero's API lets a bot request a locate quote
and cancel it unpaid, so the real fill rate can be measured. v56 asks which fill rate the target needs, and which
book reaches it, on the data source the bot will use.

## 1. Engine (as v50, with v55's decision source)

- v50's TZC run (v49's ensemble of 31 seeds, TradeZero International costs, borrow by calendar day, margin interest,
  the 2:1 rule, the close-entry volume cap, v29's bootstrap of one-year paths from $5,000, ruin at or under
  $1,250), with the close entries decided on Alpaca's IEX bars as v55's **iex** source (IEX cache of run
  42048053366).
- Books: DS1 {0.10, 0.20, 0.30} x NS {0.40, 0.60, 0.80, 1.00} x RU {0.10, 0.15, 0.20, 0.25}, at most 5 new names a
  day: 48 books.
- Locate worlds (chance a locate fails, HOT / HTB): **W0** 0% / 0%, **W10** 10% / 2%, **W25** 25% / 5%,
  **W50** 50% / 10% (v49's assumption).

## 2. Selection and decision, per world

- The book is chosen on 2018-2022 paths only: the highest ensemble median among books with ensemble ruin at most 5%
  at base costs and at HOT 5%, on those paths.
- **MET** in a world if that book has, on all paths 2018-2026, ensemble median at least $12,500 (+150%) and ruin at
  most 5% at base and HOT 5%, and ruin at most 5% on 2023+ paths at base costs.
- Reading: the lowest-cost world in which v56 is MET is the locate fill rate the bot must find in TradeZero's real
  quotes. If W0 is NOT MET, no fill rate gets there with these members and a new source of return is needed.
- Descriptive: every book's median and ruin in every world on all, 2018-2022 and 2023+ paths, and the best book
  with all-sample ruin at most 5% in each world (chosen with hindsight, marked as such).

## 3. Caveats fixed now

- Every year has been seen in earlier studies; the 2018-2022 choice limits, but does not remove, the bias of picking
  among 48 books. v53 showed sizes picked with hindsight can fail; the 2023+ ruin test is the guard.
- Locate failures are seeded at random by symbol and day; real failures cluster on the hottest names and days,
  which may be the best trades. The measurement on TradeZero must report fill rates by tier and by day.
- The locate price per share is as v50; v56 does not model the Pre-Borrow versus Single Use choice.

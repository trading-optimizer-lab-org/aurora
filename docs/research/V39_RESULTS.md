# v39 results: volatility-cut sizes beyond v38's edge

Pre-registration: [V39_PREREGISTRATION.md](V39_PREREGISTRATION.md). Run 40324100238 (2026-10-26, all jobs
succeeded). Numbers in [data/v39_summary.json](data/v39_summary.json). The check reproduces v38's choice
($21,638, ruin 1.4%).

**Target not met.** The choice on 2018-2022 paths, DS1 40% RU 70% NS 30% ON1 20% without the cut, has a median of
$18,487 and ruin 14.4% on all paths (2018-22 $24,733 / 2.1%, 2023+ $10,148 / 30.3%). The rule picked the
book with the most risk that still passed on 2018-2022 paths, and that book fails on later ones.

- No book of the 108 has an all-paths median of $30,000. The highest at any ruin: DS1 30% RU 70% NS 30% ON1 20%
  without the cut, $24,635, ruin 1.3%. It was not chosen, and at HOT 5% its ruin is 2.5% and at the high costs 7.7%.
- The volatility cut lowers ruin and the stress tails but also the median: at p 0.5, DS1 20% RU 70% NS 40% ON1 0%
  has $21,539, ruin 0.0%, high costs $10,982 / 0.7%; without the cut the same book has $23,143, ruin 0.1%.
- Larger RU and NS sizes add about $1.5-3k over v38. RU's weight rests on 71 trades (v35 diagnostic).

## End of the $30,000 search (v35-v39)

As pre-registered, the search for this target stops here. Five pre-registered studies (account levers, member
sets, HOT rules, new members, a size per member, a volatility cut) never reached a $30,000 one-year median from
$5,000 at ruin at most 2.5%. The in-sample ceiling with these members and TradeZero's costs is about $23-25k, and
the books near it fail the stress costs. Any book picked from these tables is picked after five searches on the
same data and needs a clean test.

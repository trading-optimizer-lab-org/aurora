# v54dd results: maximum drawdown of the fixed daily books

Run 41599332841 (2026-11-03), descriptive only. Median ends match v54m (v49 $8,361 vs $8,375, margin pick $6,767 vs
$6,763; here 31 seeds are pooled, v54m averages per-seed medians).

- v49 DS0.20-NS0.40-RU0.20-N5: median max drawdown in a year 28%, 1 year in 10 over 53%; 2025-2026 33% and 50%.
- Margin pick DS0.00-NS0.40-RU0.15-N5: 25% and 42%; 2025-2026 30% and 49%.
- Single 2019-2026 sequence from $5,000: v49 54% at worst, margin pick 42%.
- Ruin (v29: falling under a fixed share of the $5,000 start) stays near 0% because these falls come after gains;
  measured from the account's own high, both books lose a quarter to a third in a typical year.

Data: data/v54dd_summary.json.

## Sizing on the account's high (run 41601486655, 2026-11-03)

The owner asked: positions grow with the account, but in a fall they stay the size of the high. Modelled as the
high's size level with returns scaled by high / equity (linear in size; TradeZero's margin and the 10%-of-volume
cap at close entries are not applied, so this is optimistic).

- v49: median ,361 -> ,292 (+11%), ruin 0.1% -> 0.6% (lockbox 0.0% -> 1.2%), 1 year in 100 drawdown 64% -> 73%
  (lockbox 65% -> 80%). Single sequence: max drawdown 54% -> 58%.
- Margin pick: ,767 -> ,178 (+6%), ruin 0.0% -> 0.4% (lockbox 1.1%), 1 in 100 57% -> 68% (lockbox 79%).
- For comparison, v49 with NS one step up (v54m) earns ,984 at ruin 0.2%: a similar gain bought with less tail.
- Reading: it adds leverage exactly in falls; the typical year barely changes, the worst years get much worse.

## Report (verbatim)

# v54dd report: maximum drawdown of the fixed daily books

One-year paths from $5,000 drawn from the sample's sessions, 31 seeds pooled. Drawdown: the largest fall of the account from its own highest value so far.

| book | sized on | set | sample | median end | ruin | median max drawdown | 1 year in 10 worse than | 1 year in 100 worse than |
|---|---|---|---|---|---|---|---|---|
| v49 | equity | base | all | $8,361 | 0.1% | 28% | 53% | 64% |
| v49 | equity | base | lock | $6,936 | 0.0% | 33% | 50% | 65% |
| v49 | equity | hot5 | all | $8,192 | 0.1% | 28% | 53% | 64% |
| v49 | equity | hot5 | lock | $6,744 | 0.0% | 33% | 52% | 66% |
| v49 | peak | base | all | $9,292 | 0.6% | 29% | 57% | 73% |
| v49 | peak | base | lock | $7,900 | 1.2% | 33% | 55% | 80% |
| v49 | peak | hot5 | all | $9,112 | 0.6% | 29% | 57% | 74% |
| v49 | peak | hot5 | lock | $7,681 | 1.4% | 34% | 56% | 82% |
| margin | equity | base | all | $6,767 | 0.0% | 25% | 42% | 57% |
| margin | equity | base | lock | $6,022 | 0.0% | 30% | 49% | 63% |
| margin | equity | hot5 | all | $6,672 | 0.0% | 25% | 43% | 58% |
| margin | equity | hot5 | lock | $5,863 | 0.0% | 31% | 50% | 64% |
| margin | peak | base | all | $7,178 | 0.4% | 26% | 44% | 68% |
| margin | peak | base | lock | $6,633 | 1.1% | 31% | 53% | 79% |
| margin | peak | hot5 | all | $7,080 | 0.4% | 26% | 44% | 69% |
| margin | peak | hot5 | lock | $6,464 | 1.3% | 31% | 54% | 81% |

Single sequence 2019-2026 from $5,000:

- v49, sized on equity: end $477,382, max drawdown 54%
- v49, sized on peak: end $837,447, max drawdown 58%
- margin, sized on equity: end $85,329, max drawdown 42%
- margin, sized on peak: end $105,353, max drawdown 44%

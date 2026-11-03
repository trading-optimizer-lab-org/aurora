# v54dd results: maximum drawdown of the fixed daily books

Run 41599332841 (2026-11-03), descriptive only. Median ends match v54m (v49 $8,361 vs $8,375, margin pick $6,767 vs
$6,763; here 31 seeds are pooled, v54m averages per-seed medians).

- v49 DS0.20-NS0.40-RU0.20-N5: median max drawdown in a year 28%, 1 year in 10 over 53%; 2025-2026 33% and 50%.
- Margin pick DS0.00-NS0.40-RU0.15-N5: 25% and 42%; 2025-2026 30% and 49%.
- Single 2019-2026 sequence from $5,000: v49 54% at worst, margin pick 42%.
- Ruin (v29: falling under a fixed share of the $5,000 start) stays near 0% because these falls come after gains;
  measured from the account's own high, both books lose a quarter to a third in a typical year.

Data: data/v54dd_summary.json.

## Report (verbatim)

# v54dd report: maximum drawdown of the fixed daily books

One-year paths from $5,000 drawn from the sample's sessions, 31 seeds pooled. Drawdown: the largest fall of the account from its own highest value so far.

| book | set | sample | median end | median max drawdown | 1 year in 10 worse than | 1 year in 100 worse than |
|---|---|---|---|---|---|---|
| v49 | base | all | $8,361 | 28% | 53% | 64% |
| v49 | base | lock | $6,936 | 33% | 50% | 65% |
| v49 | hot5 | all | $8,192 | 28% | 53% | 64% |
| v49 | hot5 | lock | $6,744 | 33% | 52% | 66% |
| margin | base | all | $6,767 | 25% | 42% | 57% |
| margin | base | lock | $6,022 | 30% | 49% | 63% |
| margin | hot5 | all | $6,672 | 25% | 43% | 58% |
| margin | hot5 | lock | $5,863 | 31% | 50% | 64% |

Single sequence 2019-2026 from $5,000:

- v49: end $477,382, max drawdown 54%
- margin: end $85,329, max drawdown 42%

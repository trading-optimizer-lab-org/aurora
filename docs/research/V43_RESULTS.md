# v43 results: the best book on one-minute bars

Run 40466407738: 115,200 replays, 1,382,400 books on 300 runners of 4 CPUs. Full tables in `V43_REPORT.md`.

- **Q1, realism: the book survives.** Central case (stop at the next bar's open, 10% of bar volume, liquidation
  at the next bar's VWAP): median $22,006, ruin 0.1% at base costs; HOT 5% $16,153 / 0.5%; high costs $10,252 /
  2.5%. The daily-like replay gives $21,944 / 0.1%, about 5% under v39's daily $23,143.
- The 96 realism cases span only $21,869 to $22,053 at base costs. Inference: almost every fill of this book is an
  auction (the open or the close), so stop fill rules, the volume cap and the liquidation fill barely matter. The
  identical results across the three liquidation fills suggest the broker's rule never triggered; the counts that
  would confirm it were not collected (a bug: the counters lived in the worker processes), so this is not verified.
- **Q2, the minute grid: not improved.** The walk-forward book's median is $21,697 with ruin 10.3% (it picked size
  x1.25 in 2019-2022). In 0 of 96 cases does the choice beat the shield's rule on the historical path. The best
  fixed rule in hindsight (stop x1.5) adds 0.14 log growth over nine years: noise.
- **Q3, from $2,000:** the shield's rule gives a median $8,296, ruin 0.3%, a 5.4% chance of halving.
- The book's worst yearly drawdown on the historical path is -70% in every top rule.

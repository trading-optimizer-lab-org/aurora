# The sealed test (2023-07-01 to 2026-10-16): protocol

Written and committed on 2026-10-20, before the sealed window was opened, at the owner's request ("si" to opening
it after v16 met its design criterion). The window has never been used by v14-v16 (the code refused any day after
2023-06-30). It is opened once, by `scripts/run_sealed.py open`, which sets the unlock of `research/v14_core.py`.

## 1. Freezing (design data only, before the window is opened)

`scripts/run_sealed.py freeze` reads the v14, v15 and v16 shard outputs (design period only) and writes
`docs/research/data/sealed_frozen.json`, which is committed before step 2 runs:

- For every family (the v14 B8 and v15's B8R2 excluded, as in COMBO16), the configuration with the best plateau
  score over all design months (the v14 score: the smaller monthly Sortino of the two halves, capped at 20, averaged
  over the configuration and its one-step neighbours).
- `COMBO16` members: the families whose chosen configuration has a plateau score of at least 1.0 and a placebo
  p-value of at most 0.05 over all design months; weights inverse to the volatility of the last 252 design
  sessions, at most 35% each (the rest in cash if the caps bind). Fixed for the whole window, no re-selection.
- `S1_B8NEWS` and `B8R1_GAPFADE` alone, each with its chosen configuration.

## 2. Opening

`scripts/run_sealed.py open` rebuilds the v14, v15 and v16 inputs through 2026-10-16 (crypto through 2026-09-30)
with the same code, runs only the frozen configurations, and reports for 2023-07-01 to 2026-10-16: monthly Sortino,
CAGR, maximum drawdown, total, every year, at the middle costs and at the high ones (half-spreads x2; for v14
families their high scenario). The IBKR availability table of v15 is reused unchanged.

## 3. Verdict (fixed now)

- `COMBO16` at the middle costs: monthly Sortino >= 4 = **success**; 3-4 = **promising**; below 3 = **failure**.
- `S1_B8NEWS` and `B8R1_GAPFADE` are reported with the same thresholds, as information.
- Whatever the result, the window is then spent for these families: nothing is re-selected on it.

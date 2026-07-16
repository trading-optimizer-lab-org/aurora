# Stock Protocol Scientific Rebuild Audit

## Baseline

- Reference commit: `42a6cd389bc9b67a46be2ca38a950bd869f8f401`.
- Reference run: `29391712261`.
- The reference artifact is audit evidence only. Its performance metrics are invalid for strategy selection.
- Data boundary: `2020-12-31`; locked starts at `2021-01-01`.

## Reproduced defects

| Area | Evidence in baseline | Consequence |
|---|---|---|
| Cross-sectional selection | `signals.py` sets `signal = score.notna() & isfinite(score)` | Every finite score is bought; binary zero is bought; top-percent and top-N are absent. |
| Momentum formulas | `shift(21).pct_change(252/126)` | Uses t-273/t-147 instead of t-252/t-126. |
| ATR | Absolute return times close | Not True Range; gaps and intraday ranges are mismeasured. |
| Split consistency | Raw OHLC mixed with adjusted close | Splits can create false breakouts and inconsistent stops. |
| Layer chaining | Stage jobs download only the data pack | Frozen outputs gate scheduling but are not consumed as input. |
| Variant fidelity | Unrecognised tests fall back to `price_score`; unrecognised exits fall back to time exit | Results are produced for rules that were never implemented. |
| Portfolio | Trades receive a weight column after execution | Weights do not alter cash, positions, equity or metrics. |
| Metrics | Individual trade returns are treated as a daily return series | CAGR, Sharpe, drawdown and costs do not describe a portfolio. |
| Costs | Fixed bps are subtracted once from every supplied return | Not per-side execution cost; no monetary cost or capacity logic. |
| Walk-forward | Calendar blocks are generated with `date_range(..., periods=21)` | No train/validation/test separation, purge or frozen holdout. |
| Robustness | Same generic trade backtest is run for robustness tasks | Shards are not real bootstrap/DSR/CSCV/FDR work. |
| Pareto | Finalizer writes the top 100 by Sharpe | Not a Pareto frontier. |
| Final counts | `25`, `11` and `partial=false` are hard-coded | Counts are not derived from actual artifacts. |
| Survivorship | Current-universe backfill | Results are preliminary and cannot estimate definitive profitability. |

## Required evidence before completion

Every acceptance criterion in the goal will be mapped to an automated test,
an artifact invariant, or an inspected GitHub run.  Completion requires all
three layers to be physical and hash-bound: selection, entry, and exit/risk;
portfolio metrics must come from daily equity; and the 2016-2020 holdout must
be evaluated once after a pre-2016 freeze.

# Open questions and risks

These are not requests for user clarification. Codex must resolve them conservatively or reject the affected candidate.

1. **Yahoo historical corrections.** The operational source worked in V1, but histories can change. Raw snapshots and cross-source checks are mandatory.
2. **OHLC split normalization.** High/low/open/volume must be transformed consistently. A correct close series does not prove the range fields are correct.
3. **ETF distribution convention.** Predictor ETF ratios are deliberately price-only. Mixing total-return and price-only predictors would change the frozen hypothesis.
4. **Fixed-sector panel history.** It avoids constituent survivorship but starts in December 1998, reducing independent regimes.
5. **RSP history.** Warmup may leave fewer than the required sessions or years; explicit rejection is acceptable.
6. **Combined common interval.** Cumulative WRC/SPA/PBO require at least 1,500 aligned sessions across all included return streams. If this cannot be achieved honestly, validation is blocked.
7. **V1 return extraction.** The embedded artifact must contain enough daily strategy returns to reconstruct all 65 V1 evaluable differentials. Summary metrics are not a substitute.
8. **Variance-ratio details.** Overlapping-return denominators and finite-sample corrections must match the formula contract and reference tests.
9. **CUSUM reset semantics.** Both accumulators reset after either threshold event; any other implementation is a different strategy.
10. **Tree label alignment.** At close `t`, the latest lawful training label ends at an opening that has already occurred. Off-by-one errors are a critical lookahead risk.
11. **Post-2010 track.** Twelve candidates are train-only research for purposes of genuine temporal validation.
12. **Meta-selection.** V2 exists after seeing V1 fail. Cumulative multiplicity partly addresses this, but no statistical correction can fully remove researcher degrees of freedom.
13. **Zero costs.** Headline results are deliberately gross and should not be represented as implementable net returns.
14. **Always-invested short state.** The forced `-1` alternative is not equivalent to the cash state used by many original studies.

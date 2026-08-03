# ADR 0004: GTBI V7 FeatureStore Boundary

## Decision

`core/gtbi_feature_store.py` is the single authoritative cache interface for
GTBI price-derived primitives. Strategy code may request primitives through
that interface but may not maintain a second independent implementation.

The cache is content-bound to the complete prepared OHLCV frame and benchmark
frame. In-place data changes therefore invalidate reuse. Cache keys preserve
effective integer and exact floating-point parameters. All rolling operations
remain backward-looking and preserve existing `shift` and `min_periods`
semantics.

## Compatibility rule

Cached and uncached evaluation must produce the same signals, entry/exit dates,
trade returns, yearly metrics and scientific digest. Runtime-only timing fields
may differ. A failed equivalence test disables promotion.

## Boundaries

- No locked rows are loaded.
- No strategy, threshold, ranking or final filter changes.
- The interface contains no I/O and cannot start local research.
- The original script keeps a compatibility import while the implementation
  lives in the package module.

## Status

Accepted under the owner simplification directive for the canonical successor.

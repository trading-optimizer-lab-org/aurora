# Hedging Decision (R121)

## Status

Decision: **forbid hedging at the engine level.** Operators that need
opposing positions on the same symbol model them as **two separate
strategies** running under the R71 isolation override.

## Why this decision

The Aurora engine today nets to a single position per symbol.
Supporting native hedging means:

- extending the engine state model to two parallel position legs per
  symbol,
- teaching the broker translation layer how to map two opposing legs
  to the broker's own hedging schema (Interactive Brokers, Lumibot,
  CCXT, Alpaca all express it differently),
- adding a dedicated audit invariant: long_leg + short_leg = 0 after
  netting, except when an opening leg is in flight,
- writing a regression suite that catches the obvious failure modes
  (one leg fills, the other is rejected; one leg hits the kill
  switch but the other does not; broker reconciliation reports a
  netted position when the engine model says two legs).

The maintenance cost is large and the benefit is small: every
hedging strategy that Aurora has run in production was actually
two strategies sharing a symbol, not a single-rule two-legged
position. The R71 isolation primitive already supports that pattern.

## Concrete rule

The engine refuses to accept a target weight whose sign is opposite
to the carried position when both are non-zero, unless the override
flag is set. The error message points at the documented R71 pattern.

```python
# pseudocode shape; live wiring is operator-side
if carried_position != 0 and target_weight * carried_position < 0:
    raise EngineHedgingRefused(
        "Engine refuses opposing-sign target on same symbol. "
        "Model the hedging leg as a separate strategy under "
        "deployment.strategy_isolation (R71)."
    )
```

## What to do instead

1. Define strategy A (the "primary" leg) under its own
   `StrategySpec`.
2. Define strategy B (the "hedge" leg) under a separate `StrategySpec`.
3. Run both under `deployment.strategy_isolation` (R71) so their
   weight maps and audit chains are separate.
4. The broker submits two orders -- one per strategy.
5. Reconciliation happens at the operator level (the broker reports
   a netted position; the operator's portfolio view shows both
   strategies' contributions).

## Out of scope

- Native two-legged orders sent atomically to the broker (some
  brokers support this -- see R4 broker adapter follow-up if it
  becomes the bottleneck).
- Multi-account hedging (operators with two account memberships
  already model this via two engine instances).
- Tax-aware hedging optimisation (covered by R114 tax-awareness; the
  decision there is operator-side).

## When to revisit

If a future strategy class genuinely requires the engine to reason
about both legs simultaneously (e.g. a delta-neutral options
overlay), reopen this decision. The implementation cost has not
changed; the use-case bar is the question.

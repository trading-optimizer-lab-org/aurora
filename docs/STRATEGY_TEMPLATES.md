# Strategy Templates Gallery (R87)

Starter strategies grouped by family. Each template lives under
`strategies/templates/` and is callable from the engine via
`from aurora.strategies.templates import <name>`.

## Trend following

### `trend_following_ma_cross(prices, fast=20, slow=50)`

Long when the fast SMA is above the slow SMA, flat otherwise.

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `fast`    | 20      | 5-50  | Fast SMA window (bars) |
| `slow`    | 50      | 50-200 | Slow SMA window (bars) |

Smoke expectation: positive Calmar over a 20-year SPY-like dataset
when transaction costs are realistic; sensitive to the slow window.

## Mean reversion

### `mean_reversion_rsi(prices, period=14, oversold=30, overbought=70)`

Long when RSI below `oversold`, short when above `overbought`.

| Parameter   | Default | Range | Notes |
|-------------|---------|-------|-------|
| `period`    | 14      | 5-30  | RSI window (bars) |
| `oversold`  | 30      | 20-40 | Long entry threshold |
| `overbought`| 70      | 60-80 | Short entry threshold |

Smoke expectation: works in rangebound markets; bleeds in strong
trends. Pair with R94 news filter to avoid trading mean reversion
through scheduled events.

## Breakout

### `breakout_donchian(prices, lookback=20)`

Long on close above trailing high; short on close below trailing low.

| Parameter   | Default | Range | Notes |
|-------------|---------|-------|-------|
| `lookback`  | 20      | 10-100 | Trailing window |

Smoke expectation: classic Turtle-style breakout. Works when costs
are low and trends persist; pairs with R95 vol filter to avoid
breakouts during volatility spikes.

## How to extend

Add a new template:

1. Drop the signal generator into
   `strategies/templates/starters.py`.
2. Add it to `strategies/templates/__init__.py`'s `__all__`.
3. Document the parameter cheat-sheet here (one section per
   template).
4. Add a property test asserting:
   - output shape equals input shape,
   - output values are in `{-1, 0, +1}` (or whatever the convention
     is for the family),
   - warm-up bars are zero.

Each new template should have a one-page rationale in this document
and a smoke backtest expected output (Sharpe / Calmar / MDD) for at
least one canonical asset path.

## Out of scope

- Pairs trading (handled by `strategies/library/pair_trade.py`).
- Vol-targeting overlay (handled by
  `deployment/vol_target_forecast.py`).
- Regime-switching (the regime detector lives in `regime/`; the
  template gallery exposes only single-regime starters).

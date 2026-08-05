# Incremental research synthesis

## 1. Why another campaign is scientifically defensible

V1 did not show that all possible daily SPY signals fail. It showed that none of its 65 evaluable strategies survived its predeclared multiple-testing gate, while 103 others were not economically evaluated because their data or frozen specification failed. The correct continuation is therefore not to retune those winners or open validation, but to freeze a materially different candidate universe before observing new train results.

## 2. Overnight and intraday components

Research has long separated returns earned during trading and non-trading periods. V2 does not assume that either component is universally bullish or bearish. It freezes continuation and reversal interpretations of the overnight-minus-intraday difference and separately tests gap/body agreement and rejection.

## 3. OHLC geometry and range information

Close-only momentum discards the path represented by open, high and low. V2 adds close location, normalized body and range-based volatility states. Range estimators are evidence about volatility measurement, not direct proof of return direction; the directional mapping is explicitly identified as a model inference.

## 4. Signed risk and tails

Upside and downside variation are not necessarily equivalent. V2 tests daily signed-semivariance balance, rolling skew, robust tail reversals and volatility-of-volatility. Daily data are a coarse proxy for high-frequency semivariance, and this limitation is binding.

## 5. Serial dependence

Variance ratios, rolling autocorrelation and regression slope t-statistics test properties that are not equivalent to endpoint momentum. The estimators and finite-sample conventions are frozen so Codex cannot choose the most favorable implementation after seeing performance.

## 6. Volume and liquidity

Volume can distinguish information-driven continuation from risk-sharing reversal in theory and cross-sectional evidence. V2 uses signed abnormal volume and a signed Amihud-style impact measure. Because SPY volume contains hedging and creation/redemption activity, external validity remains uncertain.

## 7. Fixed-ETF breadth and leadership

V1 could not execute constituent breadth causally. V2 replaces it with a fixed nine-sector ETF panel and explicitly signed ratios. This avoids current-member survivorship, but it shortens train and does not recreate true point-in-time S&P 500 breadth.

## 8. Change detection and interpretable ML

Two-sided Page CUSUM creates a transparent persistent state. The shallow-tree family fixes every feature, hyperparameter, target-alignment rule, refit date and seed. It is permitted only because the V1 logit family was rejected for an incomplete grid; V2 closes that specification gap before performance is observed.

## 9. What would falsify V2

The package should produce a negative result if:

- no candidate survives cumulative multiple testing;
- apparent performance depends on a narrow crisis window;
- fixed-ETF families have insufficient train history;
- OHLC or volume data cannot be reconciled;
- the combined V1+V2 test cannot be reproduced;
- a finalist fails the one-shot validation gate.

No gate may be loosened after observing train.

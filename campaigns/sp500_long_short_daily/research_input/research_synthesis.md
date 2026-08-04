# Research synthesis: causal daily S&P 500 long/short hypotheses

## 1. What this evidence can and cannot establish

The research question is unusually narrow: decide after the close using only causally available information, execute at the next SPY open, and remain exactly long or short with no cash or leverage scaling. Many papers study a different universe, horizon, execution price, long/cash overlay, volatility-scaled futures portfolio or cross-section. Their findings can motivate hypotheses, but they cannot be copied as results for this contract.

Every library row separates: **(a) the published study claim**, **(b) the model inference used to construct a candidate**, and **(c) unverified or non-transferable items**. The conservative count of 160 verified primary sources refers to exact bibliographic/original-record identity, not complete forensic replication or numerical-result extraction for all 249 records.

## 2. Trend and time-series momentum have the clearest directional translation

Moving-average and range-break rules have explicit bullish and bearish states in the classic technical-rule literature [SRC0001]. The central methodological counterweight is that searching many related rules materially changes inference [SRC0002]. Later time-series momentum evidence broadens the mechanism across liquid futures [SRC0023], but the published implementation often uses multiple assets and volatility scaling, neither of which is allowed here.

**Inference retained:** test simple unscaled SPY price/SMA, crossover, breakout, own-return sign and equal-weight multi-horizon votes. **Not inferred:** that the multi-asset Sharpe ratio transfers to SPY, or that a long/cash timing paper validates a permanent short state.

The principal adverse regime is a sharp rebound after stress. Momentum-crash evidence [SRC0033] implies that every trend finalist must disclose crisis declines, rebound months, worst short-run reversal and concentration of gains in benign trends. This is a failure-mode requirement, not a discretionary guardrail selected after validation.

## 3. Reversal is plausible at short horizons, but execution timing matters

Short-horizon negative autocorrelation and contrarian profits appear in several foundational studies [SRC0042; SRC0043]. Later work connects reversals to liquidity provision and separates temporary pressure from information [SRC0049]. Volume can change the interpretation of serial correlation [SRC0050].

**Inference retained:** direct sign reversal over 1-20 sessions and high-volume-gated variants. **Main uncertainty:** a close-to-close reversal may not survive execution at the next open because part of the correction can occur overnight. Therefore open-to-next-open returns, gap decomposition and turnover are mandatory outputs.

## 4. Volatility evidence contains several different signals, not one

VIX is an option-implied volatility index and is strongly related contemporaneously to equity moves [SRC0056]. That relation does not by itself establish next-day prediction. The variance risk premium literature instead studies the gap between option-implied and expected/realized variance [SRC0060]. Work separating VIX, expected variance and the variance premium shows why their signs must not be conflated [SRC0062].

The package therefore separates:

- VIX changes as a near-term risk-off continuation hypothesis;
- VIX extremes as a panic-reversal hypothesis;
- VIX term structure as contango/backwardation risk state;
- a transparent free VRP proxy, with an explicit warning that `VIX² - realized variance` is not exact model-free variance;
- tail/skew/crash-transition combinations as higher-risk research variants.

Contradictory signs are not averaged away. They remain separate candidate trials and increase the effective multiplicity count.

## 5. Yield-curve and credit indicators are slow but causally interpretable

The term spread has a long history as a predictor of activity and recessions [SRC0112; SRC0113]. Credit-spread research identifies components related to intermediary risk-bearing and future activity [SRC0139]. These mechanisms support risk-on/risk-off signs, but they operate with variable horizons and can be early for equities.

**Inference retained:** fixed signs for term spreads and changes in credit/financial-condition measures. **Mandatory caveat:** revised latest-vintage series cannot be treated as historical real-time observations. ALFRED or archived releases must drive as-of joins. Ex-post NBER recession dates are evaluation annotations only.

## 6. Valuation forecasts are weak, unstable and best handled with constraints/combinations

A broad evaluation of equity-premium predictors finds that many popular variables fail to beat the historical mean out of sample in important samples [SRC0115]. Economic constraints can improve some forecasts [SRC0116], while simple combinations may be more stable than selecting one predictor [SRC0117].

The candidate pack uses sign forecasts only, carries monthly values after their release, and keeps model fitting inside train-only nested walk-forward. These families rank below simple trend because their forecast error is large, revision risk is material and the bearish state can be rare.

## 7. Breadth and correlation are conceptually useful but data-limited

Participation, volume and internal co-movement can distinguish broad from narrow moves. However, historical S&P 500 breadth requires point-in-time membership. A current constituent list creates survivorship bias. No free official continuous membership-plus-price panel was verified. Consequently, free exchange-wide advance/decline archives are labelled **proxies**, never S&P breadth equivalents.

Breadth/correlation candidates remain in the pack because the hypotheses are testable after data repair, but they cannot pass the runnable-data gate if provenance, calendar, issue definitions or as-of universe are unresolved.

## 8. Sentiment, positioning, cross-asset and calendar effects are secondary tracks

Survey, positioning and media measures can represent either continuation or contrarian pressure. The sign depends on horizon, and release timestamps are often more important than the observation date. Cross-asset indicators additionally create time-zone and instrument-inception problems. Calendar anomalies have long samples but a very large multiple-testing surface and documented instability.

These families are retained with fixed definitions, low priority and strict no-repair-after-performance rules. Google Trends is rejected for core use because historical samples are re-normalized and not reliably reproducible point-in-time.


## 8A. Overnight/futures evidence is implemented with a free SPY proxy

Reliable long-history contract-level ES intraday data are generally not available under the zero-dollar data constraint. The executable variants therefore use the corporate-action-consistent SPY opening gap already fully known by close `t`, with continuation, reversal, five-session, z-score and VIX-filtered mappings. Futures research motivates the hypothesis but is not a required dataset. This preserves the zero-cost data rule while making the proxy limitation explicit.

## 9. Regime and machine-learning models are tools, not privileged evidence

Markov-switching models can summarize latent states [SRC0179], but bull/bear identification is model-dependent and random walks can reproduce apparent phase properties [SRC0181]. Only **filtered** probabilities are causal; smoothed probabilities are forbidden.

Regularized logistic models are limited to six small, predeclared feature sets. They use deterministic nested train-only tuning, the one-standard-error rule and expanding train-only normalization. They rank below simple rules because a flexible model can exploit the same finite sample many times.

## 10. Multiple testing is part of the signal definition

The campaign evaluates all 168 candidates as one disclosed search universe. It requires White's Reality Check [SRC0183], Hansen's SPA [SRC0184], Deflated Sharpe Ratio [SRC0186], CSCV/PBO [SRC0185] and transparent rejected/near-miss logs. Post-publication decay evidence [SRC0188] is the reason post-2010 sources are tracked separately.

## 11. Final research-priority ranking

| Rank | Family | Tier | Evidence | Free-data feasibility | Candidates | Why it ranks here |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Price versus simple moving average | A | high | high | 6 | Direct symmetric price-state signal with long historical evidence. |
| 2 | Own-return time-series momentum | A | high | high | 6 | Strong directional mechanism but publication after the train boundary. |
| 3 | Short-horizon return reversal | A | high | high | 6 | Direct contrarian sign with substantial liquidity-based evidence. |
| 4 | VIX term-structure risk state | A | medium_high | high | 6 | Causal option-market stress state with explicit bullish/bearish sign. |
| 5 | Fixed equal-weight simple-rule ensemble | A | high | high | 6 | Forecast-combination evidence supports fixed votes without validation weighting. |
| 6 | Multi-horizon trend vote | A | high | high | 6 | Reduces single-horizon dependence while remaining interpretable. |
| 7 | Fast/slow moving-average crossover | A | high | high | 6 | Classic symmetric trend rule. |
| 8 | Prior-range price breakout | A | high | high | 6 | Classic directional support/resistance rule. |
| 9 | Volume-gated reversal | B | medium_high | high | 6 | Economic liquidity mechanism improves interpretability of reversal. |
| 10 | Free variance-risk-premium proxy | B | high | medium_high | 6 | Strong literature, but free VIX-squared minus realized variance is not exact VRP. |
| 11 | VIX extreme panic reversal | B | medium_high | medium_high | 6 | Extreme fear may precede rebound; opposing sign is separately tested. |
| 12 | VIX level/change continuation | B | medium_high | high | 6 | Simple causal stress-change signal. |
| 13 | Realized-volatility shock state | B | high | medium | 6 | Useful state variable; paired continuation/reversal variants expose ambiguity. |
| 14 | Yield-curve regime | B | high | high | 6 | Highly interpretable slow risk state with official daily data. |
| 15 | Credit-spread widening/tightening | B | high | high | 6 | Credit risk appetite has direct risk-on/risk-off sign. |
| 16 | Financial-conditions state | B | high | high | 6 | Economically strong but point-in-time reconstruction is difficult. |
| 17 | Sector correlation/dispersion proxy | C | high | medium_high | 6 | Conceptually useful internal-risk state with substantial data caveats. |
| 18 | Exchange breadth trend proxy | C | medium | high | 6 | Participation may confirm direction, but free data are proxies. |
| 19 | Exchange breadth thrust proxy | C | medium | high | 6 | Extreme participation is directional but data provenance is weaker. |
| 20 | Cross-asset risk-off score | C | medium_high | high | 6 | Fixed score captures credit/rates/dollar/commodity state. |
| 21 | Monetary and inflation regime | C | high | medium_high | 6 | Slow causal state with explicit real-time joins. |
| 22 | Constrained equity-premium forecast | C | high | medium | 6 | Strong research debate and explicit negative evidence demand lower priority. |
| 23 | Sentiment and positioning | C | medium_high | medium | 6 | Useful secondary state; paired continuation/contrarian variants. |
| 24 | Calendar seasonality | C | medium | high | 6 | Causal and cheap, but multiplicity is severe. |
| 25 | SPY overnight/gap directional proxy | D | medium_high | medium_high | 6 | Free SPY gap proxy is causal; paid ES data are excluded and transfer risk remains. |
| 26 | Filtered two-state regime model | D | high | high | 6 | Causal only with filtered probabilities and strong complexity penalty. |
| 27 | Nested elastic-net logistic direction model | D | high | high | 6 | Interpretable ML baseline, not a black box; train-only nested tuning. |
| 28 | Trend adjusted by volatility state | D | high | medium_high | 6 | Volatility may condition trend reliability, but exposure remains exactly one. |

The top of this table is the starting order for computation, not a promise of profitability. A family can move forward only through the predefined train protocol and one-time validation; no narrative judgement can override a failed data or causal gate.

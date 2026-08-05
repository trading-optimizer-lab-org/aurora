# Executive summary

## Conclusion

The strongest pre-backtest programme is a **frozen, disclosed competition**, not a single preferred indicator. Simple price trend, own-return momentum, short-horizon reversal, VIX term structure and fixed parsimonious ensembles receive the highest research priority. Credit, yield-curve, volatility-state, breadth-proxy, sentiment, cross-asset, regime and regularized-model families remain included because their hypotheses are distinct, but they carry stronger data, transfer or complexity penalties.

There is **no empirically validated winner in this ZIP**. Published findings only justify hypotheses. They do not establish that a daily SPY-only, next-open, permanently directional, unscaled and zero-cost implementation will outperform.

## Package scale

- Literature records: **249**.
- Exact bibliographic identities counted as verified primary sources: **160**.
- Evidence-track split: **168** records dated no later than 2010; **81** post-2010 research records, segregated and penalized.
- Data sources assessed: **73**; free and usable now/after repair: **55**.
- Strategy families: **28**.
- Candidate variants: **168**.
- Canonical features: **168**.
- Mandatory benchmarks: **5**.
- All six cost fields: **0** exactly.
- Locked period opened: **false**.

## Five highest-priority families before any backtest

| Rank | Family ID | Family | Why it ranks here |
| ---: | --- | --- | --- |
| 1 | `price_trend_sma` | Price versus simple moving average | Direct symmetric price-state signal with long historical evidence. |
| 2 | `time_series_momentum` | Own-return time-series momentum | Strong directional mechanism but publication after the train boundary. |
| 3 | `short_horizon_reversal` | Short-horizon return reversal | Direct contrarian sign with substantial liquidity-based evidence. |
| 4 | `vix_term_structure` | VIX term-structure risk state | Causal option-market stress state with explicit bullish/bearish sign. |
| 5 | `simple_rule_ensemble` | Fixed equal-weight simple-rule ensemble | Forecast-combination evidence supports fixed votes without validation weighting. |

This is an evidence/data/complexity ordering, not a performance ranking.

## Twenty priority candidates before any backtest

| Rank | ID | Family | Variant | Evidence track | Priority | Complexity | Main failure modes |
| ---: | --- | --- | --- | --- | ---: | ---: | --- |
| 1 | `STRAT0001` | `price_trend_sma` | `SMA_50` | `pre_2011_evidence` | 100 | 1 | whipsaw in sideways markets; sharp rebound after short state |
| 2 | `STRAT0007` | `time_series_momentum` | `RET_21` | `post_2010_research` | 98 | 1 | momentum crashes; horizon instability |
| 3 | `STRAT0002` | `price_trend_sma` | `SMA_100` | `pre_2011_evidence` | 97 | 1 | whipsaw in sideways markets; sharp rebound after short state |
| 4 | `STRAT0013` | `short_horizon_reversal` | `REV_1` | `pre_2011_evidence` | 96 | 1 | overnight correction before next open; high turnover |
| 5 | `STRAT0008` | `time_series_momentum` | `RET_63` | `post_2010_research` | 95 | 1 | momentum crashes; horizon instability |
| 6 | `STRAT0003` | `price_trend_sma` | `SMA_150` | `pre_2011_evidence` | 94 | 1 | whipsaw in sideways markets; sharp rebound after short state |
| 7 | `STRAT0019` | `vix_term_structure` | `VIX_VIX3M_100` | `pre_2011_evidence` | 94 | 2 | short history; backfilled dissemination; crisis whipsaw |
| 8 | `STRAT0014` | `short_horizon_reversal` | `REV_2` | `pre_2011_evidence` | 93 | 1 | overnight correction before next open; high turnover |
| 9 | `STRAT0025` | `simple_rule_ensemble` | `CORE_3` | `pre_2011_evidence` | 93 | 3 | correlated votes; hidden effective multiplicity |
| 10 | `STRAT0009` | `time_series_momentum` | `RET_126` | `post_2010_research` | 92 | 1 | momentum crashes; horizon instability |
| 11 | `STRAT0031` | `trend_ensemble` | `VOTE_21_63_126` | `post_2010_research` | 92 | 2 | correlated horizons; rebound losses |
| 12 | `STRAT0004` | `price_trend_sma` | `SMA_200` | `pre_2011_evidence` | 91 | 1 | whipsaw in sideways markets; sharp rebound after short state |
| 13 | `STRAT0037` | `dual_ma_cross` | `MA_10_50` | `pre_2011_evidence` | 91 | 1 | lag and whipsaw |
| 14 | `STRAT0020` | `vix_term_structure` | `VIX_VIX3M_095` | `pre_2011_evidence` | 91 | 2 | short history; backfilled dissemination; crisis whipsaw |
| 15 | `STRAT0015` | `short_horizon_reversal` | `REV_3` | `pre_2011_evidence` | 90 | 1 | overnight correction before next open; high turnover |
| 16 | `STRAT0043` | `price_breakout` | `DONCHIAN_20` | `pre_2011_evidence` | 90 | 1 | false breakouts; sparse switches |
| 17 | `STRAT0026` | `simple_rule_ensemble` | `CORE_5` | `pre_2011_evidence` | 90 | 3 | correlated votes; hidden effective multiplicity |
| 18 | `STRAT0010` | `time_series_momentum` | `RET_189` | `post_2010_research` | 89 | 1 | momentum crashes; horizon instability |
| 19 | `STRAT0032` | `trend_ensemble` | `VOTE_63_126_252` | `post_2010_research` | 89 | 2 | correlated horizons; rebound losses |
| 20 | `STRAT0049` | `volume_conditioned_reversal` | `REV1_VOL20_Z1` | `pre_2011_evidence` | 89 | 2 | volume definition changes; overnight recovery |

## Frozen scientific decisions

1. A paper that goes long/cash is not silently converted to long/short. A bearish state exists only where a direct sign or explicit economic mechanism supports it.
2. VIX level, expected variance, realized variance, term structure and variance risk premium are not treated as the same signal.
3. Macro and survey values are joined by historical release time; final revised histories are prohibited when vintages exist.
4. Markov models may use filtered probabilities only. Smoothed full-sample states are prohibited.
5. Current S&P 500 constituents cannot reconstruct historical breadth. Exchange breadth is labelled as a proxy.
6. The six overnight/futures-family candidates use a free, corporate-action-consistent SPY overnight-gap proxy. Paid ES data remain catalogued but are not dependencies.
7. All 168 candidates are frozen before performance. A candidate must receive results or an explicit rejection row.
8. Train selects; validation confirms once; 2021+ remains inaccessible.

## Main limitations

- SPY begins in 1993, giving relatively few independent market regimes before the 2010 train boundary.
- Many source papers use different markets, horizons, close-to-close returns, cash states, leverage or volatility scaling; transfer to this exact contract is an inference.
- Zero costs materially overstate external implementability for permanent shorts and high-turnover rules, although zero is the required experimental assumption.
- Corporate-action reconstruction of an adjusted open is a critical technical gate.
- Free breadth, variance-premium and some cross-asset series are proxies rather than exact institutional datasets.
- The 168-candidate search creates substantial multiple-testing risk; White RC, Hansen SPA, CSCV/PBO and Deflated Sharpe are mandatory.
- The 2011-2020 validation period may be used only once and may not select or repair candidates.

## What would count as a valid outcome

- `POSITIVE_VALIDATED_RESULT`: at least one frozen finalist passes every predeclared validation and technical gate.
- `NEGATIVE_RESULT`: computation is valid but no finalist passes.
- `TECHNICAL_FAILURE`: data, causality, accounting or reproducibility failure makes results uninterpretable.
- `VALIDATION_NOT_OPENED`: train completed but the exact validation authorization was not supplied.

# Contradictions, negative results and failure modes

## Direct conclusion

The literature does not support one universally superior daily sign. The most dangerous error would be to merge contradictory mechanisms into a single retrospective story. This package preserves the contradictions as separate trials and predefines how they can fail.

| Conflict | Strongest case for A | Strongest case for B | Decision in this package |
| --- | --- | --- | --- |
| Trend continuation vs. panic rebound | Own-return continuation and technical buy/sell evidence are broad. | Momentum can crash during violent rebounds after market stress. | Keep trend and panic-reversal rules separate; report rebound-event performance and never tune a crash filter on validation. |
| Rising volatility is bearish vs. high fear predicts positive returns | VIX jumps accompany risk-off price pressure. | High variance premium or extreme fear may imply compensation/reversal. | Separate VIX change, VIX extreme, term structure and VRP; count every sign variant in multiplicity. |
| Term inversion is bearish vs. equities can rally while inverted | Curve inversion predicts recession risk at long/variable leads. | The exact equity timing is unstable and policy regimes change. | Use fixed sign as a slow state only; judge daily strategy empirically without ex-post recession timing. |
| High sentiment follows trends vs. high sentiment is contrarian | Positioning can reveal informed demand or persistent risk appetite. | Crowding/optimism can forecast lower future returns. | Trend and contrarian signs are different candidates; release lag and horizon are explicit. |
| Breadth improves confidence vs. breadth divergence can persist | Broad participation often supports healthier trends. | Narrow leadership can persist, and free historical breadth is a proxy. | Require point-in-time/proxy labels; no current-member reconstruction. |
| Latent regimes are real vs. regime labels are model artifacts | Filtered switching models can capture persistent state changes. | State count, distribution and labels are unstable; random walks can mimic phases. | Two states only, filtered probabilities only, complexity penalty, deterministic restarts. |
| Valuation predicts long-horizon returns vs. weak short-horizon timing | Present-value logic is economically strong. | Out-of-sample monthly forecasts are noisy and unstable. | Lower priority; constrained sign forecasts and equal combinations only. |
| Calendar regularities vs. publication decay/data mining | Long histories contain recurring calendar means. | Many slices create false discoveries and effects can decay. | Six predefined calendar candidates; no month/day mining. |
| Published significance vs. replication/post-publication decay | Peer-reviewed findings can be genuine in their samples. | Returns often attenuate after publication and under corrected definitions. | Evidence motivates tests; it does not bypass train/validation gates. |
| Zero costs simplify mechanism vs. make high-turnover rules unrealistic | The user explicitly requested zero costs to isolate gross signal behavior. | Shorting, opening execution and switching are not free in reality. | All calculations use exact zero; turnover and a non-binding sensitivity report are still recorded, never used for acceptance. |

## Negative evidence that changes the protocol

- **Data snooping:** the best member of a large technical-rule family is not evaluated as if it were the only rule tested. Reality Check/SPA and the full candidate count are mandatory.
- **Equity-premium forecast failures:** a model that looks plausible in-sample but does not beat simple baselines in train walk-forward is rejected before validation.
- **Post-publication attenuation:** post-2010 papers are a separate track. Their existence cannot be silently projected back to 2010.
- **Survivorship:** current S&P constituents cannot create historical breadth, correlation or sector leadership.
- **Revisions:** latest NFCI, macro and model-based index histories can leak future revisions. If no vintage/reconstruction passes, the candidate is classified as a data failure.
- **Backfilled indexes:** a calculated historical value before live dissemination is not automatically causally available.
- **Open execution:** signals measured at the close are not credited with the close price. Next-open gaps are part of realized strategy performance.

## Required negative controls

1. Random signs generated from the fixed seed, with the same open-to-open accounting.
2. Permanently long, permanently short and symmetric 200-day price/SMA benchmarks.
3. Label-permutation and circular-shift controls that preserve return autocorrelation blocks.
4. Intentionally leaked variants in test-only code to verify the causality detector catches close/open and vintage leakage; leaked variants never enter the candidate universe.
5. Duplicate-candidate injection in test fixtures to verify canonical hashing/deduplication.

## What counts as a valid negative result

A campaign is scientifically successful even when no strategy passes. The final artifact must then say `NEGATIVE_RESULT`, preserve the complete tested universe and diagnostics, and state whether failure came from economics (no robust edge), data feasibility, causal timing, multiplicity, validation degradation or a combination. It must not create a second candidate search after seeing validation.


## Final package audit additions

- Six formerly research-only ES-dependent candidates were not allowed to remain executable because their required dataset was classified `not_free`. They now use only the explicitly documented SPY overnight-gap proxy; ES remains a literature/data-inventory item, not a dependency.
- Buy-and-hold and 12-month momentum benchmarks were added because the required five-benchmark contract cannot be satisfied by always-long, always-short and SMA-200 alone.
- Bibliographic identity verification was reduced conservatively to 160 exact primary identities after correcting metadata mismatches. No numerical paper result is treated as independently replicated solely because its citation is verified.

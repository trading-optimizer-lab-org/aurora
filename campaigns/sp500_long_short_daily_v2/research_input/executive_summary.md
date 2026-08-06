# Executive summary — V2 incremental research

## Conclusion before testing

The new package contains **plausible hypotheses, not profitable findings**. No V2 strategy has been backtested here.

The strongest design change is practical: most candidates rely only on the already audited SPY ledger and free raw OHLCV. The fixed-ETF families use actual ETF histories rather than reconstructing historical S&P 500 membership. This should materially reduce the 61% technical/data rejection rate observed in V1, but it does not imply that statistical performance will improve.

## Counts

| Item | Count |
|---|---:|
| Total research/context records after V2 | 269 |
| Exact verified primary bibliographic identities | 176 |
| New incremental records | 20 |
| V2 datasets inventoried | 10 |
| Free potentially executable datasets | 9 |
| New families | 24 |
| New candidates/features | 144 |
| Pre-2011-evidence candidates | 132 |
| Post-2010-research candidates | 12 |
| V1 + V2 declared trials for multiplicity | 312 |
| Benchmarks | 5 |

## Five highest-priority families

1. `overnight_intraday_tug`
2. `semivariance_balance`
3. `signed_volume_pressure`
4. `autocorrelation_switch`
5. `variance_ratio_switch`

Their priority reflects evidence quality, causal daily implementability and free-data feasibility. It is not based on V2 returns.

## Twenty candidates prioritized before train

| # | ID | Family | Variant | Track | Priority | Datasets |
|---|---|---|---|---|---|---|
| 1 | V2STRAT0001 | overnight_intraday_tug | TUG_CONT_1 | pre_2011_evidence | 118 | V2DS001, V2DS002, V2DS003 |
| 2 | V2STRAT0031 | semivariance_balance | SEMIVAR_BAL_5 | pre_2011_evidence | 116 | V2DS001, V2DS003 |
| 3 | V2STRAT0091 | signed_volume_pressure | SIGNED_VOL_1 | pre_2011_evidence | 114 | V2DS001, V2DS002, V2DS003 |
| 4 | V2STRAT0061 | autocorrelation_switch | AC_SWITCH_L1_W63 | pre_2011_evidence | 112 | V2DS001, V2DS003 |
| 5 | V2STRAT0002 | overnight_intraday_tug | TUG_CONT_5 | pre_2011_evidence | 110 | V2DS001, V2DS002, V2DS003 |
| 6 | V2STRAT0055 | variance_ratio_switch | VR_SWITCH_Q2_W126 | pre_2011_evidence | 110 | V2DS001, V2DS003 |
| 7 | V2STRAT0013 | close_location_pressure | CLV_MEAN_1 | pre_2011_evidence | 108 | V2DS001, V2DS002, V2DS003 |
| 8 | V2STRAT0032 | semivariance_balance | SEMIVAR_BAL_10 | pre_2011_evidence | 108 | V2DS001, V2DS003 |
| 9 | V2STRAT0007 | gap_body_interaction | GAP_BODY_AGREE_1 | pre_2011_evidence | 106 | V2DS001, V2DS002, V2DS003 |
| 10 | V2STRAT0092 | signed_volume_pressure | SIGNED_VOL_3 | pre_2011_evidence | 106 | V2DS001, V2DS002, V2DS003 |
| 11 | V2STRAT0025 | range_volatility_ratio | PARK_RATIO_5_20 | pre_2011_evidence | 104 | V2DS001, V2DS002, V2DS003 |
| 12 | V2STRAT0062 | autocorrelation_switch | AC_SWITCH_L2_W63 | pre_2011_evidence | 104 | V2DS001, V2DS003 |
| 13 | V2STRAT0003 | overnight_intraday_tug | TUG_CONT_20 | pre_2011_evidence | 102 | V2DS001, V2DS002, V2DS003 |
| 14 | V2STRAT0056 | variance_ratio_switch | VR_SWITCH_Q5_W126 | pre_2011_evidence | 102 | V2DS001, V2DS003 |
| 15 | V2STRAT0103 | sector_etf_breadth | SECTOR_POSRET_20 | pre_2011_evidence | 102 | V2DS004, V2DS009, V2DS008 |
| 16 | V2STRAT0014 | close_location_pressure | CLV_MEAN_3 | pre_2011_evidence | 100 | V2DS001, V2DS002, V2DS003 |
| 17 | V2STRAT0033 | semivariance_balance | SEMIVAR_BAL_20 | pre_2011_evidence | 100 | V2DS001, V2DS003 |
| 18 | V2STRAT0085 | momentum_consistency | POS_FRAC_5 | pre_2011_evidence | 100 | V2DS001, V2DS003 |
| 19 | V2STRAT0008 | gap_body_interaction | GAP_BODY_AGREE_5 | pre_2011_evidence | 98 | V2DS001, V2DS002, V2DS003 |
| 20 | V2STRAT0019 | range_body_pressure | BODY_RANGE_1 | pre_2011_evidence | 98 | V2DS001, V2DS002, V2DS003 |

## Critical scientific correction

The V1 artifact is a mandatory input. DSR and FDR use 312 declared hypotheses. The binding combined WRC/SPA/PBO analysis includes all 65 V1 evaluable return streams and every V2 evaluable stream over a common causal interval. The 103 V1 technical/data rejections remain declared trials; they are never assigned zero returns.

## Validation

Only candidates marked `pre_2011_evidence` may be promoted as genuinely temporal 2011–2020 validations. `post_2010_research` candidates may receive train diagnostics but cannot earn `POSITIVE_VALIDATED_RESULT` from the 2011–2020 window.

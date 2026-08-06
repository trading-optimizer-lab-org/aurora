# Acceptance gates — V2

## A. Technical gates

| Gate | Pass condition | Failure |
|---|---|---|
| Package | All required files parse, internal hashes pass and embedded prior ZIP hashes match. | `TECHNICAL_FAILURE_PACKAGE` |
| Cardinality | Exactly 144 unique V2 candidates, 24 families × 6, 144 features and five benchmarks. | `TECHNICAL_FAILURE_CARDINALITY` |
| Novelty | No exact V2 economic-signature collision and no exact V1 hash collision; semantic near-neighbors disclosed. | `TECHNICAL_FAILURE_DUPLICATE` |
| Position | Every eligible state is exactly `-1` or `+1`; exposure is exactly 1. | `TECHNICAL_FAILURE_POSITION` |
| Costs | All six headline cost fields are numeric zero. | `TECHNICAL_FAILURE_COST` |
| Timing | Information available by close `t`; position changes only at next SPY open. | `TECHNICAL_FAILURE_LOOKAHEAD` |
| Return ledger | V1 audited SPY total-return ledger reused or byte-equivalent correction formally versioned; long/short identity passes. | `TECHNICAL_FAILURE_LEDGER` |
| Determinism | Two clean smoke executions produce identical scientific hashes. | `TECHNICAL_FAILURE_NONDETERMINISM` |
| Locked | Zero market observations dated 2021-01-01 or later. | `TECHNICAL_FAILURE_LOCKED_BREACH` |

## B. Data gates

- Source is `usable_now` or has completed every `usable_after_repair` step.
- Post-warmup expected-session coverage >= 98%.
- At least 1,000 eligible sessions and five complete train years.
- Fixed-ETF identity, inception and first raw bar verified.
- No synthetic pre-inception data.
- No current-constituent historical reconstruction.
- No adjusted-close-derived open/high/low.
- Predictor ETF series are split-normalized price-only; the target is audited total return.
- All panel components required by a rule are present on a session.
- Raw snapshot and normalized output hashes are present.

Failure is `DATA_INELIGIBLE`, never a zero-return candidate.

## C. Cumulative-statistics gate

Before any finalist can exist:

- embedded V1 result artifact hash passes;
- 65 V1 evaluable streams are loaded;
- all 144 V2 terminal records exist as evaluated or explicitly rejected;
- FDR and DSR count 312 declared trials;
- combined WRC/SPA/PBO use V1+V2 evaluable streams;
- common interval contains at least 1,500 sessions;
- bootstrap seeds and block sensitivities are reproducible.

Failure is `COMBINED_MULTIPLICITY_INCOMPLETE` and prohibits validation.

## D. Train and validation gates

The exact train gate is in `train_selection_protocol.md` and is binding. The V1 validation success gates remain binding for V2 finalists:

1. validation CAGR > 0;
2. Sharpe >= 0.45;
3. Calmar >= 0.35;
4. maximum drawdown > -45%;
5. at least six positive calendar years;
6. median rolling three-year CAGR > 0;
7. benchmark superiority condition from V1;
8. Sharpe at least 0.10 above the best always-long/SMA200/momentum12 benchmark;
9. no single year contributes >50% of positive validation log growth;
10. both long and short occur on at least 5% of sessions;
11. train-to-validation degradation limits pass;
12. hashes and all technical gates remain unchanged.

If no candidate passes, the correct scientific status is `NEGATIVE_RESULT`.

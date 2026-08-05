# START HERE — S&P 500 daily long/short research package

## Direct result

This ZIP is the completed, structurally validated research specification requested for the Aurora campaign. It contains **249** distinct literature records, **160** primary-source identities conservatively verified by exact bibliographic metadata, **73** data-source assessments (**55** free sources classified as `usable_now` or `usable_after_repair`), **28** strategy families, **168** canonical feature definitions, **168** exact `+1/-1` candidate variants and **5** mandatory benchmarks.

It is **not a performance claim**. No train, validation or locked-period backtest was run during this research phase. No market observation or return from **2021-01-01 onward** was opened, calculated or used.

## Immutable research contract

- Target: SPY as the tradeable representation of the S&P 500.
- Position: exactly `+1` or `-1` from the first evaluable session; `abs(position)=1.0` always; no cash, partial exposure or leverage.
- Decision: after close `t`, using only values whose historical release/availability time is no later than that decision.
- Execution: next tradable SPY regular-session open `t+1`; until then the prior position remains in force.
- Tie/missing input: preserve the prior position; initial exact tie initializes at `+1` as specified per candidate.
- Return ledger: open-to-next-open SPY total return, including distributions; long receives and short owes distributions.
- Costs: commissions, slippage, borrow, financing, switching and market impact are exactly zero.
- Train: through `2010-12-31`.
- Validation: `2011-01-01..2020-12-31`, opened once only after train selection is frozen and hashed.
- Locked: `>=2021-01-01`, closed throughout this campaign; no locked workflow exists.

## Verification terminology

`verified_bibliographic_identity_exact` means title, authors, year and a stable primary locator were cross-checked. It does **not** mean every table, coefficient, sample endpoint or published transaction-cost assumption was re-extracted or replicated. The `study_claim`, `model_inference`, `unverified_items` and `claim_extraction_status` fields preserve that distinction.

## Mandatory benchmarks

1. Buy-and-hold SPY total return.
2. Always long `+1`.
3. Always short `-1`.
4. Symmetric 200-session moving average, with next-open execution.
5. Symmetric causal 12-month/252-session momentum, with next-open execution.

Buy-and-hold and always-long must be reported separately and must reconcile exactly under the common ledger.

## Recommended reading order

1. `executive_summary.md`
2. `research_synthesis.md`
3. `contradictions_and_negative_results.md`
4. `data_acquisition_plan.md` and `data_source_inventory.csv`
5. `candidate_pack_manifest.json`, `feature_catalog.csv` and `candidate_strategy_pack.jsonl`
6. `train_selection_protocol.md`, `acceptance_gates.md` and `campaign_spec.yaml`
7. `aurora_implementation_handoff.md`
8. `CODEX_GITHUB_RUN_PROMPT.md`
9. `bibliographic_verification_audit.csv` and `package_validation_report.md`

## Completion standard for the next phase

A successful Aurora run may validly end with `NEGATIVE_RESULT`. It must still produce reproducible data hashes, train-only out-of-fold results for every candidate and benchmark, explicit data/technical rejections, multiplicity diagnostics, a frozen train ranking/Pareto frontier, one validation result set only when authorized, and proof that 2021+ remained closed.

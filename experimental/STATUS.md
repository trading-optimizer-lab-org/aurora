# `experimental/` Triage (R48)

The `experimental/` directory holds 20 speculative modules that explore
ideas at the edge of the Aurora surface. Every module here is
`experimental` for production-status purposes per
[`docs/MODULE_STATUS.md`](../docs/MODULE_STATUS.md). None are
production. None are imported by core code paths.

R48 triage decision per module is recorded below.

## Decision policy

For each module, one of:

- **keep**: module stays in tree as a documented experiment; one-
  paragraph rationale at the top of the file is required.
- **archive**: module moves to a separate `aurora-experimental` repo
  (or equivalent) once that repository exists. Until then, stays in
  tree but is marked archive-bound here.
- **delete**: module is removed in a follow-up PR.

A module that is `archive` or `delete` is excluded from the wheel
package list at the time of removal.

## Status table

| Module | Decision | Rationale |
|---|---|---|
| `ai_auto_ceo.py` | archive | LLM-driven CEO simulation. Interesting but tangential to a quant engine; belongs in a separate repo. |
| `climate_carbon_aware.py` | keep | Climate factor exposure is an emerging research area; a thin module preserves the option to pick it up. |
| `competitor_pnl_reverse.py` | archive | Reverse-engineering competitor PnL is speculative and lacks reliable data inputs. |
| `dao_governance.py` | archive | DAO governance is out of scope for a backtest engine. |
| `dex_aggregator.py` | keep | DEX aggregation has legitimate quant relevance for crypto strategies. |
| `earnings_call_live.py` | keep | Earnings-call live transcription is a real research direction; ties to R2 alt-data. |
| `federated_learning.py` | keep | Federated learning is a credible privacy-preserving training direction. |
| `news_entropy_regime.py` | keep | News entropy as a regime detector is a published research idea worth keeping. |
| `prediction_markets.py` | keep | Prediction-market data is a legitimate alt-data source. |
| `quantum_placeholder.py` | delete | Placeholder for quantum portfolio optimization with no real implementation; remove. |
| `self_modifying_strategy.py` | archive | Self-modifying code is interesting but a research project, not engine work. |
| `smart_contract_escrow.py` | archive | Smart contract execution is out of scope; not a quant primitive. |
| `strategy_breeding.py` | keep | Strategy crossover / breeding is research-relevant; pairs with R77. |
| `strategy_lending.py` | archive | Lending mechanics are a separate product surface. |
| `strategy_nft.py` | delete | NFT-based strategy distribution adds nothing over R91 strategy publish / import bundles. |
| `synthetic_alpha.py` | keep | Synthetic alpha generators are useful for adversarial testing (pairs with R144). |
| `trade_vs_claude.py` | delete | Vendor-specific stunt module; remove. |
| `trader_dna.py` | archive | Trader-DNA fingerprinting is an interesting direction but redundant with R92 strategy DNA. |
| `twitter_alpha_bot.py` | archive | Twitter trading is a research direction with serious license / ToS risk. |
| `zk_performance_proof.py` | archive | Zero-knowledge proofs of strategy performance is a separate engineering project. |

## Action plan

R48 closure does not delete or archive files in this commit. Two
operator decisions are required first:

1. Whether to spin up an `aurora-experimental` repository for the
   `archive` set, or just delete that set as well.
2. Whether to keep `experimental/` in the wheel package list. Today
   it ships in the wheel; once the triage PR runs, the kept set
   stays in the wheel but everything moved out is excluded.

When the operator confirms, the follow-up PR:

1. Creates the destination repository (or skips for delete-only).
2. Moves the `archive` modules and updates this matrix.
3. Removes the `delete` modules from the wheel package list and the
   directory.
4. Renames `experimental/STATUS.md` to `EXPERIMENTAL_TRIAGE.md` under
   `docs/archive/` for history.

## What stays as evidence

The 20 unit tests under `tests/test_experimental_*.py` keep passing
on the kept modules. Tests against deleted modules are removed in
the same PR.

# SP500 daily long/short V2 — new-strategy research package

This is an **incremental, frozen second campaign**, not a rerun of V1.

## Direct contents

- 269 deduplicated research/context records in `research_library.csv`.
- 176 primary bibliographic identities verified exactly.
- 20 new incremental records in `incremental_research_library.csv`.
- 10 V2 dataset contracts; 9 are free and potentially executable (`usable_now` or `usable_after_repair`).
- 24 new families × 6 variants = **144 new candidates**.
- 144 unique economic signatures and no exact collision with the 168 V1 canonical hashes.
- The exact V1 research ZIP and exact V1 final-results artifact are embedded under `prior_campaign/`.
- `CODEX_GITHUB_RUN_PROMPT.md` is the direct, self-contained execution order for Codex.

## Immutable market contract

```text
instrument = SPY
position ∈ {-1,+1}
abs(position) = 1.0
cash = forbidden
leverage = forbidden
decision = after close t
execution = next tradable SPY open t+1
all six headline cost fields = 0
train_end = 2010-12-31
validation = 2011-01-01..2020-12-31, one shot after freeze
locked_start = 2021-01-01
locked_opened = false
```

## Why V2 is different

V1 ended correctly as a negative result: 65 candidates were evaluable, 103 were rejected, and none survived the frozen multiple-testing gate. V2 therefore avoids merely adding nearby SMA/momentum parameters. It prioritizes:

- overnight/intraday decomposition;
- OHLC geometry;
- signed semivariance, tails and higher moments;
- serial-dependence diagnostics;
- signed abnormal volume and price impact;
- fixed ETF sector breadth and leadership;
- sequential change detection;
- a completely frozen shallow interpretable tree.

V2 **does not reset multiplicity**. The binding analysis counts 168 V1 + 144 V2 = 312 declared trials.

## Start order

1. Verify `package_checksums.sha256`.
2. Read `prior_campaign_reference.json`.
3. Read `family_formula_contract.md`.
4. Parse and hash `candidate_strategy_pack.jsonl`.
5. Read `train_selection_protocol.md` and `acceptance_gates.md`.
6. Execute `CODEX_GITHUB_RUN_PROMPT.md`.

No validation or locked returns were used to build this package.

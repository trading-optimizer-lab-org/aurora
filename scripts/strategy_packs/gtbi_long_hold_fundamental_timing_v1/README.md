# GTBI Long Hold Fundamental Timing Pack V1

This zip contains a new external GTBI strategy pack designed after the previous V5 full run found **0 valid strategies**, **0 real near-misses**, median trade failures, and extreme drawdown in short-hold/fast-exit strategies.

## Core idea

The user will first select companies using fundamentals. This pack is only a technical timing overlay for when to buy and sell those already-interesting companies.

## Exact contents

- Strategies: **72,000**
- Concepts: **60**
- Families: **10**
- Strategies per concept: **1,200**
- Shards: **360**
- Strategies per shard: **200**
- Minimum target average holding days: **25**

## Files

- `strategy_pack_long_hold_v1.jsonl`: complete JSONL pack, 72,000 strategies.
- `strategy_pack_long_hold_v1.csv`: flat index of all strategies.
- `strategy_pack_long_hold_v1_shards/`: 360 JSONL shards.
- `concept_catalog.csv`: concept/family catalog.
- `run_config.json`: intended run parameters.
- `codex_prompt.md`: exact prompt to give Codex.
- `validation_checklist.md`: checks Codex must run.

## Main design changes from prior pack

1. Wider stops.
2. Wider or disabled take profits.
3. Soft exits delayed until minimum holding time.
4. EMA50/SMA50/ATR trailing exits instead of quick EMA10 exits.
5. Max holding windows of 45, 63, 84, 100, and 126 days.
6. Drawdown and median-trade diagnostics required from the first smoke.
7. Designed to avoid 2-day average holds that dominated earlier candidates.

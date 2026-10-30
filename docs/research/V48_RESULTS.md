# v48 results: per-name sizes judged on an ensemble of trade sets

Run 41068227728 (canary 41054977181), 2026-10-30. Pre-registration: `V48_PREREGISTRATION.md`. 126 books, 31 seeds
(history plus 30 that drop 10% of candidates), 4,000 one-year paths from $5,000, ruin at or under $1,250.

## Verdict: Q1 NOT MET, Q3 NOT MET

- Checks reproduced: base seed 0 $21,975 / 0.1% (v47 $22,006 / 0.1%); base TZA seed 0 $20,742 / 5.9% (v47 same).
- The choice on 2018-2022 paths is the base sizes at 5 new a day (DS0.20-NS0.40-RU0.70-N5, early ruin 2.3%).
  On all paths its ensemble ruin is 5.2% (HOT 5% 6.1%), so Q1 fails. Under TZA: ensemble ruin 7.7%, Q3 fails.

## The honest base

| book | ens median | ens ruin | p90 ruin | seed 0 | 2023+ ens | HOT 5% ens | from $2k |
|---|---|---|---|---|---|---|---|
| base RU0.70 N3 | $18,409 | 5.3% | 12.6% | $21,975 / 0.1% | $17,360 / 9.0% | $13,765 / 6.4% | $8,292 / 0.3% |
| base, TZA rules | $18,650 | 7.9% | 16.9% | $20,742 / 5.9% | $12,065 | $17,920 / 8.1% | - |

The seed-0 0.1% is luck: dropping 10% of candidates gives 5.3% mean ruin and 12.6% at the 90th percentile.

## Books with ensemble ruin at most 2.5% at base and HOT 5% (all paths)

| book | ens median | ens ruin | p90 ruin | 2018-22 | 2023+ | HOT 5% | from $2k |
|---|---|---|---|---|---|---|---|
| DS0.20-NS0.40-RU0.30-N5 | $14,534 | 1.4% | 4.0% | $13,764 / 0.8% | $15,342 / 2.8% | $11,222 / 1.9% | $5,947 / 0.3% |
| DS0.20-NS0.40-RU0.25-N5 | $14,051 | 0.6% | 0.5% | $13,276 / 0.1% | $14,922 / 1.8% | $10,888 / 1.2% | $5,628 / 0.4% |
| DS0.20-NS0.40-RU0.20-N5 | $13,450 | 0.2% | 0.4% | $12,666 / 0.1% | $14,486 / 1.0% | $10,470 / 0.6% | $5,299 / 0.4% |
| DS0.20-NS0.40-RU0.15-N5 | $12,797 | 0.2% | 0.4% | $12,036 / 0.1% | $13,834 / 0.9% | $9,996 / 0.6% | $4,918 / 0.4% |

None of them was tested under TZA rules (only the choice and the base were, as pre-registered).

## What the grid shows

- RU size is the ruin dial. RU 0.50 gives 2.4-2.9% ruin at ~$15-17k; RU 0.30 gives 1.4% at $14.5k; RU 0.25 gives
  0.6% at $14.1k. Safe books keep ~76-79% of the honest base median.
- Raising DS1 above 0.20 is bad: DS1 0.25 or 0.30 lifts ensemble ruin to 10-14% at every RU size, mostly on 2023+
  paths (23-27%).
- NS 0.40 beats 0.30 and 0.25 at every RU size with no extra ruin.
- 5 new a day is about equal to 3 (+$100, same ruin).
- The capacity story in RUINA_SOLUCION_ES.md is wrong: the account takes 72 of 230 RU candidates at every RU size
  (0.70 and 0.25 alike). The left-out RU candidates are not blocked by the gross cap. Smaller RU cuts ruin only by
  cutting each trade's weight, which is why the median falls.

## Caveats

All years 2018-2026 were seen before. The dropout ensemble is one model of which trades fill.

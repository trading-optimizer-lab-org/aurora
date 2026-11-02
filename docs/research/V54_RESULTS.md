# v54 results: the FREE daily book chosen year by year

Run 41497719624 (2026-11-02), pre-registered in V54_PREREGISTRATION.md. The pipeline reproduces v50's answer
exactly ($9,065, ruin 0.1% on all 2018-2026 paths).

## Verdict: DOES NOT SURVIVE

Choosing the sizes each year from the years before gives selection ruin (2019-2024) of 25.4% (expanding window) and
24.8% (last 3 years), far over 2.5%.

## Why

- The walk-forward picks bigger sizes than v49/v50: DS 40%, NS 80%, RU 25% in 2019-2020, then RU 25% through
  2024. On the years it had seen, those books looked safe (training ruin 0.0-0.3%).
- **RU at 25% instead of 20% is a cliff.** With the same DS 20% and NS 60%, 2024 sums to -46% at RU 25% and +74% at
  RU 20% (seed 0, simple sum of daily returns at the $5,000 level). Nothing before 2024 showed it.
- The rolling window also lands on DS 40% in 2024-2026 and loses 51% in 2026; its lockbox ruin is 40.9%.

## The fixed books (chosen on the whole period, so in hindsight)

| book | sel 2019-24 median / ruin | lock 2025-26 median / ruin | all median / ruin | stress ruin, worst | every year positive |
|---|---|---|---|---|---|
| v49 DS0.20-NS0.40-RU0.20-N5 | $8,800 / 0.0% | $6,948 / 0.0% | $8,375 / 0.1% | 0.2% | yes, +29% to +155% |
| v50 DS0.20-NS0.60-RU0.20-N5 | $9,669 / 0.2% | $6,713 / 0.6% | $8,984 / 0.2% | 0.7% | yes, +27% to +177% |

They make money in every year 2019-2026 and keep ruin under 1% in every stress set. But their size, RU 20%, is the
one just under the cliff, and that was learned from the same years they are graded on.

## Reading

The members (DS1, NS, RU) hold up year after year at v49's sizes; what does not hold up is choosing the size from
the past, because the past never showed how close RU 25% was to the edge. The honest position: the v49 book's sizes
are safe on 2018-2026 with no margin above them, and a rule that sizes up when recent years look calm would have
ruined the account. If the book is used, its sizes should be treated as a ceiling, not a starting point, and the
lockbox years (median about $6.7-6.9k from $5,000) are weaker than the earlier ones.

Data: data/v54_summary.json (aggregates only).

## Report (verbatim)

# v54 report: the FREE daily book chosen year by year

Pre-registered in V54_PREREGISTRATION.md. 126 size books under TZC. Check: v50's answer on all 2018-2026 paths here $9,065, ruin 0.1% (v50: $9,065, 0.1%).

**No walk-forward procedure keeps selection ruin (2019-2024) at or under 2.5%: DOES NOT SURVIVE.**

| plan | sel med | sel ruin | sel HOT5 ruin | lock med | lock ruin | lock HOT5 ruin | all med | all ruin | borrow x2 all | locates never fail all | locates fail half as often all | history end | history low |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| wf-exp | $9,871 | 25.4% | 25.9% | $6,713 | 0.6% | 0.7% | $8,986 | 21.7% | $7,126 / 25.9% | $16,027 / 8.4% | $12,160 / 14.1% | $595,943 | $4,755 |
| wf-roll3 | $10,745 | 24.8% | 25.3% | $3,271 | 40.9% | 41.3% | $8,343 | 30.0% | $6,004 / 33.9% | $12,361 / 24.8% | $9,872 / 29.5% | $80,836 | $4,755 |
| fixed-v49 | $8,800 | 0.0% | 0.0% | $6,948 | 0.0% | 0.0% | $8,375 | 0.1% | $7,129 / 0.2% | $12,737 / 0.2% | $9,988 / 0.1% | $477,383 | $4,877 |
| fixed-v50 | $9,669 | 0.2% | 0.2% | $6,713 | 0.6% | 0.7% | $8,984 | 0.2% | $7,485 / 0.5% | $13,898 / 0.7% | $10,763 / 0.4% | $564,836 | $4,816 |

## wf-exp: the book of each test year

| year | book | train med | train ruin | train HOT5 ruin | year sum at $5k |
|---|---|---|---|---|---|
| 2019 | DS0.40-NS0.80-RU0.25-N5 | $10,697 | 0.0% | 0.0% | +97% |
| 2020 | DS0.40-NS0.80-RU0.25-N5 | $10,973 | 0.0% | 0.0% | +246% |
| 2021 | DS0.20-NS0.80-RU0.25-N5 | $12,172 | 0.0% | 0.1% | +133% |
| 2022 | DS0.20-NS0.60-RU0.25-N5 | $12,021 | 0.2% | 0.2% | +36% |
| 2023 | DS0.20-NS0.60-RU0.25-N5 | $10,699 | 0.1% | 0.2% | +71% |
| 2024 | DS0.20-NS0.60-RU0.25-N5 | $10,296 | 0.1% | 0.1% | -46% |
| 2025 | DS0.20-NS0.60-RU0.20-N5 | $9,584 | 0.1% | 0.1% | +56% |
| 2026 | DS0.20-NS0.60-RU0.20-N5 | $9,214 | 0.1% | 0.1% | +42% |

## wf-roll3: the book of each test year

| year | book | train med | train ruin | train HOT5 ruin | year sum at $5k |
|---|---|---|---|---|---|
| 2019 | DS0.40-NS0.80-RU0.25-N5 | $10,697 | 0.0% | 0.0% | +97% |
| 2020 | DS0.40-NS0.80-RU0.25-N5 | $10,973 | 0.0% | 0.0% | +246% |
| 2021 | DS0.20-NS0.80-RU0.25-N5 | $12,172 | 0.0% | 0.1% | +133% |
| 2022 | DS0.20-NS0.60-RU0.25-N5 | $13,323 | 0.2% | 0.2% | +36% |
| 2023 | DS0.20-NS0.60-RU0.25-N5 | $12,064 | 0.3% | 0.4% | +71% |
| 2024 | DS0.40-NS0.60-RU0.25-N5 | $9,886 | 0.1% | 0.1% | +23% |
| 2025 | DS0.40-NS0.60-RU0.20-N5 | $8,738 | 0.0% | 0.0% | +98% |
| 2026 | DS0.40-NS0.60-RU0.20-N5 | $10,446 | 0.1% | 0.2% | -51% |

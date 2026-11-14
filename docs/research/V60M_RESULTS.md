# v60m results: the short margin rule does not cap size

Run 43595006536 (2026-11-14), pre-registered in V60M_PREREGISTRATION.md. Control reproduced: DS0.20-NS0.60-RU0.25 under tzi in W0 $13,041, ruin 1.0%.

## Verdict

- The margin rule is not the brake. Under every rule (tzi, TradeZero's strict 4-8 PM column, its lenient overnight 1/6, none) medians differ by a few hundred dollars and nearly every candidate is taken; the margin check binds on 0-6% of days.
- The account is mostly idle: mean gross exposure 0.11 to 0.38 of equity across the five books. Mean gross rises from 0.19 to 0.35 between the second and last book, so size does buy exposure.
- What limits the median is the split by period. In F0C1 the 2018-2022 median keeps rising with size ($12,547 -> $23,279 at DS0.45-NS1.50-RU0.50, ruin 15%) while 2023-2026 falls ($10,383 -> $3,162, ruin 51%). The all-years median averages the two, so it barely moves.
- RU's 64 of 175 is the one-position-a-symbol rule against DS1 (same signal), not margin.

## Consequence for v61

Choosing on 2018-2022 alone would pick sizes that 2023-2026 punishes. v61 should hold the ruin limit in each period, not only in 2018-2022. The engine's tzi rule can stay.

## Report (verbatim)

# v60m report: does the short margin rule cap a bigger size?

Pre-registered in V60M_PREREGISTRATION.md. Diagnostic only, chooses nothing. v58's engine (TZC, IEX, 31 seeds, one-year paths from $5,000, ruin = touching $1,250), 2:1 gross and the 15:45 2:1 rule kept in every rule. Exposure and trade counts: $5,000 level, base costs, seed 0, F0C1.

| book | margin rule | W0 all | F0C1 all | F0C1 2018-2022 | F0C1 2023-2026 | HOT5 ruin F0C1 | mean gross | mean tzi margin | days margin >90% | taken / candidates |
|---|---|---|---|---|---|---|---|---|---|---|
| DS0.10-NS0.40-RU0.10 | tzi | $8,466 / 0.0% | $7,831 / 0.0% | $8,020 / 0.0% | $7,474 / 0.0% | 0.0% | 0.11 | 0.07 | 0% | DS1 274/296, NS 210/212, RU 64/175 |
| DS0.10-NS0.40-RU0.10 | tzus | $8,435 / 0.0% | $7,834 / 0.0% | $8,020 / 0.0% | $7,490 / 0.0% | 0.0% | 0.11 | 0.07 | 0% | DS1 275/296, NS 206/212, RU 64/175 |
| DS0.10-NS0.40-RU0.10 | tz6 | $8,443 / 0.0% | $7,809 / 0.0% | $8,020 / 0.0% | $7,441 / 0.0% | 0.0% | 0.11 | 0.07 | 0% | DS1 275/296, NS 210/212, RU 64/175 |
| DS0.10-NS0.40-RU0.10 | none | $8,443 / 0.0% | $7,809 / 0.0% | $8,020 / 0.0% | $7,441 / 0.0% | 0.0% | 0.11 | 0.07 | 0% | DS1 275/296, NS 210/212, RU 64/175 |
| DS0.20-NS0.60-RU0.25 | tzi | $13,041 / 1.0% | $11,634 / 1.1% | $12,547 / 0.9% | $10,383 / 1.4% | 1.2% | 0.19 | 0.12 | 0% | DS1 274/296, NS 203/212, RU 64/175 |
| DS0.20-NS0.60-RU0.25 | tzus | $13,052 / 1.0% | $11,773 / 1.1% | $12,526 / 0.9% | $10,637 / 1.3% | 1.2% | 0.19 | 0.12 | 0% | DS1 274/296, NS 195/212, RU 64/175 |
| DS0.20-NS0.60-RU0.25 | tz6 | $13,090 / 1.1% | $11,623 / 1.2% | $12,547 / 0.9% | $10,330 / 1.9% | 1.4% | 0.20 | 0.12 | 1% | DS1 275/296, NS 209/212, RU 64/175 |
| DS0.20-NS0.60-RU0.25 | none | $13,090 / 1.1% | $11,623 / 1.2% | $12,547 / 0.9% | $10,330 / 1.9% | 1.4% | 0.20 | 0.12 | 1% | DS1 275/296, NS 209/212, RU 64/175 |
| DS0.20-NS1.00-RU0.25 | tzi | $14,116 / 7.5% | $12,805 / 7.5% | $14,193 / 10.5% | $10,932 / 4.4% | 8.0% | 0.23 | 0.14 | 1% | DS1 273/296, NS 195/212, RU 64/175 |
| DS0.20-NS1.00-RU0.25 | tzus | $13,771 / 7.5% | $12,560 / 7.5% | $14,164 / 10.5% | $10,307 / 4.1% | 8.0% | 0.22 | 0.13 | 0% | DS1 272/296, NS 185/212, RU 64/175 |
| DS0.20-NS1.00-RU0.25 | tz6 | $14,149 / 7.6% | $12,664 / 7.7% | $14,193 / 10.5% | $10,517 / 5.6% | 8.3% | 0.24 | 0.15 | 1% | DS1 274/296, NS 204/212, RU 64/175 |
| DS0.20-NS1.00-RU0.25 | none | $14,149 / 7.6% | $12,664 / 7.7% | $14,193 / 10.5% | $10,517 / 5.6% | 8.3% | 0.24 | 0.15 | 1% | DS1 274/296, NS 204/212, RU 64/175 |
| DS0.30-NS1.00-RU0.25 | tzi | $14,546 / 16.0% | $12,587 / 17.2% | $14,682 / 15.3% | $9,723 / 21.5% | 18.1% | 0.27 | 0.17 | 1% | DS1 271/296, NS 190/212, RU 64/175 |
| DS0.30-NS1.00-RU0.25 | tzus | $14,490 / 15.9% | $12,809 / 16.8% | $14,824 / 14.7% | $9,884 / 21.4% | 17.6% | 0.26 | 0.16 | 0% | DS1 264/296, NS 179/212, RU 64/175 |
| DS0.30-NS1.00-RU0.25 | tz6 | $13,638 / 16.4% | $12,173 / 17.5% | $14,894 / 15.0% | $8,550 / 23.4% | 18.4% | 0.28 | 0.18 | 2% | DS1 272/296, NS 202/212, RU 64/175 |
| DS0.30-NS1.00-RU0.25 | none | $13,638 / 16.4% | $12,173 / 17.5% | $14,894 / 15.0% | $8,550 / 23.4% | 18.4% | 0.28 | 0.18 | 2% | DS1 272/296, NS 202/212, RU 64/175 |
| DS0.45-NS1.50-RU0.50 | tzi | $13,494 / 28.3% | $11,204 / 29.9% | $23,279 / 15.2% | $3,162 / 51.2% | 31.1% | 0.35 | 0.21 | 2% | DS1 256/296, NS 150/212, RU 62/175 |
| DS0.45-NS1.50-RU0.50 | tzus | $13,678 / 25.8% | $11,487 / 27.4% | $21,554 / 15.2% | $4,298 / 45.4% | 28.4% | 0.34 | 0.20 | 1% | DS1 247/296, NS 147/212, RU 59/175 |
| DS0.45-NS1.50-RU0.50 | tz6 | $13,936 / 27.4% | $11,348 / 29.2% | $24,111 / 14.6% | $3,372 / 50.7% | 30.4% | 0.38 | 0.24 | 6% | DS1 268/296, NS 166/212, RU 64/175 |
| DS0.45-NS1.50-RU0.50 | none | $13,936 / 27.4% | $11,348 / 29.2% | $24,111 / 14.6% | $3,372 / 50.7% | 30.4% | 0.38 | 0.24 | 6% | DS1 268/296, NS 166/212, RU 64/175 |

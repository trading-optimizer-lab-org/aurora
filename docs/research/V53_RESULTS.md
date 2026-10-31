# v53 results: the whole grid by walk-forward, 2018-2026 out of sample

Run 41226223974 (2026-10-31), pre-registered in V53_PREREGISTRATION.md. 6,802,444,800 configuration scorings
(every configuration of the v51 grid on each of 32 training windows and scores), 32 books chosen.

## Verdict: NOT MET

No procedure keeps selection ruin (2018-2024) at or under 2.5%: the eight procedures range from 44.6% to 69.3% at
base and 44.9% to 69.5% at HOT 5%. By the pre-registered rule no procedure is chosen and the lockbox does not decide.
Traded in sequence from $5,000 through 2018-2026, every procedure's account reaches $0.

## What happened

- **2018-2019**: every procedure picks short books (RUNUP, STRONG, RUN100/RUN40 shorts) and they work out of sample
  (+35% and +12% to +43%, simple sums of daily returns at the $5,000 level).
- **2020-2022**: the shorts chosen on the years before lose: -50% to -347% a year (simple sums; shorts can lose more
  than the equity). This is where every account is ruined. No training rule, ruin cap, window or capped score saw it
  coming: train ruin was 0.0% for every one of these books.
- **2023-2026**: CRASH-long enters the books (from 2023 for the expanding raw score, from 2024 for the rolling ones)
  and the yearly sums become +200% to +1,100%.

## Why the lockbox medians are not evidence

The lockbox medians ($14k to $2.9M from $5,000 in a year) come from one-year paths drawn from 2025-2026 sessions of
CRASH-long books. v52 showed CRASH-long's profit is a handful of extreme trades (top 1% = 103% of the total in
2016-2017; trimmed PF 1.24 in 2023+); the block bootstrap repeats those days, so the median compounds outliers. The
capped-score procedures, which damp those outliers, have lockbox ruin of 47-55%. These numbers are reported, not
used: the procedure that would have earned them was ruined before reaching 2025.

## Reading

- Choosing from the past with this grid and these rules does not survive 2020-2022: the short edge of 2016-2019 did
  not carry forward, and the long edge appears only after 2022. A book chosen in advance would have been ruined
  between them.
- The capped score and the stricter ruin rule changed little (r25 and r10 pick the same books in most years).
- Caveats from the pre-registration stand: the design came after seeing v51 and v52; 2016-2017 short tiers lack short
  interest; extended-session limit fills are optimistic. "Year return at $5k" is a simple sum of daily returns, not a
  compounded return.

Data: data/v53_summary.json (aggregate statistics and configuration names only).

## Report (verbatim)

# v53 report: the whole grid by walk-forward, every year chosen out of sample

Pre-registered in V53_PREREGISTRATION.md. Configuration scorings: 6,802,444,800 (every configuration on every training window and score). Books chosen: 32.

**No procedure keeps selection ruin at or under 2.5% at base and HOT 5%: NOT MET.**

## Procedures (out of sample)

| procedure | sel med | sel ruin | lock med | lock ruin | lock HOT5 med | lock HOT5 ruin | all med | all ruin | borrow x2 all | locates never fail all | half rates all | history from $5k |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| exp/raw/r25 | $3,956 | 44.6% | $1,100,113 | 0.0% | $1,080,376 | 0.0% | $14,156 | 33.3% | $10,705 / 35.6% | $4,692 / 49.4% | $9,022 / 42.8% | $0 |
| exp/raw/r10 | $3,956 | 44.6% | $965,060 | 0.0% | $949,816 | 0.0% | $13,892 | 33.4% | $10,471 / 35.7% | $4,591 / 49.5% | $8,953 / 42.8% | $0 |
| exp/cap25/r25 | $3,289 | 44.9% | $14,071 | 54.8% | $13,934 | 54.9% | $3,891 | 46.0% | $2,952 / 47.7% | $46 / 62.1% | $394 / 57.0% | $0 |
| exp/cap25/r10 | $3,289 | 44.9% | $14,071 | 54.8% | $13,934 | 54.9% | $3,891 | 46.0% | $2,952 / 47.7% | $46 / 62.1% | $394 / 57.0% | $0 |
| roll3/raw/r25 | $22 | 65.6% | $2,921,557 | 10.4% | $2,865,338 | 10.4% | $2,258 | 52.9% | $1,580 / 54.4% | $0 / 66.0% | $73 / 59.5% | $0 |
| roll3/raw/r10 | $22 | 65.6% | $2,921,557 | 10.4% | $2,865,338 | 10.4% | $2,258 | 52.9% | $1,580 / 54.4% | $0 / 66.0% | $73 / 59.5% | $0 |
| roll3/cap25/r25 | $0 | 69.3% | $407,544 | 47.2% | $392,014 | 47.2% | $141 | 61.8% | $19 / 63.9% | $0 / 72.1% | $0 / 68.3% | $0 |
| roll3/cap25/r10 | $0 | 69.3% | $407,544 | 47.2% | $392,014 | 47.2% | $141 | 61.8% | $19 / 63.9% | $0 / 72.1% | $0 / 68.3% | $0 |

## exp/raw/r25: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | STRONG-short c_pm20 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUN40-short r_pm0 d3c/t0.00/s1.00 [price0-1 str0 dv0 so:u10 tier:all age:all] 30%, 3 new | $25,127 | 0.0% | +43% |
| 2020 | GAPUP-short o_hodf d2c/t0.50/s0.00 [price1-4 str0 dv0 so:all tier:all age:all] 20% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + STRONG-short c_pm10 d2c/t0.25/s0.00 [price2-4 str0 dv0 so:all tier:hot age:all] 10%, 3 new | $22,505 | 0.0% | +74% |
| 2021 | RUNUP-short c_pm0 d10c/t0.25/s0.00 [price0-4 str0 dv3 so:known tier:hot age:all] 30% + GAPUP-short o_0931 d3c/t0.00/s0.00 [price0-4 str1 dv0 so:all tier:all age:all] 10% + STRONG-short c_pm10 d10c/t0.25/s0.00 [price2-4 str0 dv0 so:all tier:hot age:all] 20%, 5 new | $20,870 | 0.0% | -50% |
| 2022 | RUNUP-short c_ah5 d10c/t0.50/s0.00 [price2-4 str0 dv2 so:all tier:hot age:old] 30% + STRONG-short c_ah5 d10c/t0.25/s1.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d5c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:all] 30%, 3 new | $16,241 | 0.0% | -35% |
| 2023 | RUN40-long r_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv2 so:all tier:all age:old] 30% + STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] 30%, 5 new | $12,928 | 0.1% | +283% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 40%, 5 new | $14,376 | 0.4% | +351% |
| 2025 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + RUN200-short r_t60 d2c/t0.25/s0.00 [price0-4 str0 dv1 so:all tier:all age:old] 30%, 5 new | $27,642 | 0.2% | +509% |
| 2026 | CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price0-4 str2 dv0 so:all tier:all age:all] 30%, 5 new | $36,025 | 2.4% | +639% |

## exp/raw/r10: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | STRONG-short c_pm20 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUN40-short r_pm0 d3c/t0.00/s1.00 [price0-1 str0 dv0 so:u10 tier:all age:all] 30%, 3 new | $25,127 | 0.0% | +43% |
| 2020 | GAPUP-short o_hodf d2c/t0.50/s0.00 [price1-4 str0 dv0 so:all tier:all age:all] 20% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + STRONG-short c_pm10 d2c/t0.25/s0.00 [price2-4 str0 dv0 so:all tier:hot age:all] 10%, 3 new | $22,505 | 0.0% | +74% |
| 2021 | RUNUP-short c_pm0 d10c/t0.25/s0.00 [price0-4 str0 dv3 so:known tier:hot age:all] 30% + GAPUP-short o_0931 d3c/t0.00/s0.00 [price0-4 str1 dv0 so:all tier:all age:all] 10% + STRONG-short c_pm10 d10c/t0.25/s0.00 [price2-4 str0 dv0 so:all tier:hot age:all] 20%, 5 new | $20,870 | 0.0% | -50% |
| 2022 | RUNUP-short c_ah5 d10c/t0.50/s0.00 [price2-4 str0 dv2 so:all tier:hot age:old] 30% + STRONG-short c_ah5 d10c/t0.25/s1.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d5c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:all] 30%, 3 new | $16,241 | 0.0% | -35% |
| 2023 | RUN40-long r_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv2 so:all tier:all age:old] 30% + STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.25 [price0-4 str0 dv0 so:all tier:all age:all] 30%, 5 new | $12,928 | 0.1% | +283% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 40%, 5 new | $14,376 | 0.4% | +351% |
| 2025 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + RUN200-short r_t60 d2c/t0.25/s0.00 [price0-4 str0 dv1 so:all tier:all age:old] 30%, 5 new | $27,642 | 0.2% | +509% |
| 2026 | CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price0-4 str2 dv0 so:all tier:all age:all] 20%, 5 new | $33,646 | 0.0% | +610% |

## exp/cap25/r25: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | RUNUP-short c_rl5 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-3 str0 dv0 so:all tier:all age:old] 20% + RUN100-short r_pm0 d1c/t0.25/s0.00 [price0-3 str0 dv0 so:known tier:all age:all] 30%, 3 new | $31,577 | 0.0% | +12% |
| 2020 | GAPUP-short o_hodf d2c/t0.25/s0.00 [price1-2 str0 dv0 so:all tier:all age:all] 20% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-3 str1 dv1 so:all tier:all age:old] 20%, 5 new | $37,956 | 0.0% | -83% |
| 2021 | RUNUP-short c_pm0 d10c/t0.25/s0.00 [price0-4 str0 dv3 so:known tier:hot age:old] 30% + RUNUP-short c_pm5 d10c/t0.25/s0.00 [price1-4 str0 dv0 so:u50 tier:hot age:all] 20% + GAPDN-long o_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 5 new | $15,535 | 0.0% | -68% |
| 2022 | STRONG-short c_ah5 d5c/t0.25/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:all tier:all age:all] 30% + GAPDN-long o_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30%, 5 new | $12,924 | 0.0% | +52% |
| 2023 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 20%, 5 new | $11,194 | 0.1% | +291% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + CRASH-long c_ah0 d1pm/t0.00/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 10%, 5 new | $16,751 | 0.0% | +206% |
| 2025 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 20% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 10%, 5 new | $19,409 | 0.0% | +338% |
| 2026 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + RUN200-short r_hodf d10c/t0.25/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] 10%, 5 new | $28,571 | 0.2% | +248% |

## exp/cap25/r10: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | RUNUP-short c_rl5 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-3 str0 dv0 so:all tier:all age:old] 20% + RUN100-short r_pm0 d1c/t0.25/s0.00 [price0-3 str0 dv0 so:known tier:all age:all] 30%, 3 new | $31,577 | 0.0% | +12% |
| 2020 | GAPUP-short o_hodf d2c/t0.25/s0.00 [price1-2 str0 dv0 so:all tier:all age:all] 20% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-3 str1 dv1 so:all tier:all age:old] 20%, 5 new | $37,956 | 0.0% | -83% |
| 2021 | RUNUP-short c_pm0 d10c/t0.25/s0.00 [price0-4 str0 dv3 so:known tier:hot age:old] 30% + RUNUP-short c_pm5 d10c/t0.25/s0.00 [price1-4 str0 dv0 so:u50 tier:hot age:all] 20% + GAPDN-long o_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 5 new | $15,535 | 0.0% | -68% |
| 2022 | STRONG-short c_ah5 d5c/t0.25/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:all tier:all age:all] 30% + GAPDN-long o_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30%, 5 new | $12,924 | 0.0% | +52% |
| 2023 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 20%, 5 new | $11,194 | 0.1% | +291% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + CRASH-long c_ah0 d1pm/t0.00/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 10%, 5 new | $16,751 | 0.0% | +206% |
| 2025 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 20% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 10%, 5 new | $19,409 | 0.0% | +338% |
| 2026 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:all age:all] 20% + RUN200-short r_hodf d10c/t0.25/s0.00 [price0-3 str0 dv0 so:all tier:all age:all] 10%, 5 new | $28,571 | 0.2% | +248% |

## roll3/raw/r25: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | STRONG-short c_pm20 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUN40-short r_pm0 d3c/t0.00/s1.00 [price0-1 str0 dv0 so:u10 tier:all age:all] 30%, 3 new | $25,127 | 0.0% | +43% |
| 2020 | STRONG-short c_pm20 d10c/t0.25/s0.00 [price1-4 str0 dv0 so:all tier:all age:old] 30% + STRONG-short c_pm20 d10c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] 30%, 3 new | $19,780 | 0.0% | -347% |
| 2021 | RUNUP-short c_pm10 d3c/t0.50/s0.00 [price0-4 str0 dv3 so:known tier:hot age:all] 30% + STRONG-short c_pm0 d1c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:hot age:all] 30% + RUNUP-short c_rl10 d10c/t0.25/s0.00 [price0-3 str0 dv0 so:u50 tier:all age:all] 30%, 5 new | $22,253 | 0.0% | -112% |
| 2022 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price3-4 str0 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:all tier:hot age:all] 30%, 3 new | $21,115 | 0.0% | -65% |
| 2023 | CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + RUN200-short r_t15 d2c/t0.50/s0.00 [price1-4 str0 dv1 so:o10 tier:all age:all] 30% + STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:old] 30%, 5 new | $46,286 | 0.0% | +206% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv1 so:all tier:nohot age:all] 30% + RUN200-short r_ah0 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30%, 5 new | $112,225 | 0.0% | +335% |
| 2025 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + STRONG-short c_pm20 d10c/t0.25/s0.00 [price2-4 str1 dv2 so:all tier:all age:all] 30% + RUN200-short r_ah0 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:all age:all] 30%, 5 new | $273,251 | 0.0% | +579% |
| 2026 | CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + RUN100-short r_hodf d5c/t0.00/s0.00 [price1-2 str0 dv0 so:u10 tier:hot age:all] 30%, 5 new | $386,707 | 0.0% | +1104% |

## roll3/raw/r10: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | STRONG-short c_pm20 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUN40-short r_pm0 d3c/t0.00/s1.00 [price0-1 str0 dv0 so:u10 tier:all age:all] 30%, 3 new | $25,127 | 0.0% | +43% |
| 2020 | STRONG-short c_pm20 d10c/t0.25/s0.00 [price1-4 str0 dv0 so:all tier:all age:old] 30% + STRONG-short c_pm20 d10c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] 30%, 3 new | $19,780 | 0.0% | -347% |
| 2021 | RUNUP-short c_pm10 d3c/t0.50/s0.00 [price0-4 str0 dv3 so:known tier:hot age:all] 30% + STRONG-short c_pm0 d1c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:hot age:all] 30% + RUNUP-short c_rl10 d10c/t0.25/s0.00 [price0-3 str0 dv0 so:u50 tier:all age:all] 30%, 5 new | $22,253 | 0.0% | -112% |
| 2022 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price3-4 str0 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:all tier:hot age:all] 30%, 3 new | $21,115 | 0.0% | -65% |
| 2023 | CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + RUN200-short r_t15 d2c/t0.50/s0.00 [price1-4 str0 dv1 so:o10 tier:all age:all] 30% + STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:old] 30%, 5 new | $46,286 | 0.0% | +206% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv1 so:all tier:nohot age:all] 30% + RUN200-short r_ah0 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30%, 5 new | $112,225 | 0.0% | +335% |
| 2025 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + STRONG-short c_pm20 d10c/t0.25/s0.00 [price2-4 str1 dv2 so:all tier:all age:all] 30% + RUN200-short r_ah0 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:all age:all] 30%, 5 new | $273,251 | 0.0% | +579% |
| 2026 | CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + RUN100-short r_hodf d5c/t0.00/s0.00 [price1-2 str0 dv0 so:u10 tier:hot age:all] 30%, 5 new | $386,707 | 0.0% | +1104% |

## roll3/cap25/r25: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | RUNUP-short c_rl5 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-3 str0 dv0 so:all tier:all age:old] 20% + RUN100-short r_pm0 d1c/t0.25/s0.00 [price0-3 str0 dv0 so:known tier:all age:all] 30%, 3 new | $31,577 | 0.0% | +12% |
| 2020 | STRONG-short c_pm20 d10c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-3 str1 dv0 so:all tier:all age:old] 20%, 5 new | $48,407 | 0.0% | -241% |
| 2021 | STRONG-short c_pm0 d1c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:hot age:all] 30% + RUNUP-short c_rl10 d10c/t0.25/s0.00 [price0-3 str0 dv0 so:u50 tier:all age:all] 30% + RUNUP-short c_rl10 d10c/t0.25/s0.00 [price1-3 str0 dv0 so:u50 tier:all age:all] 30%, 3 new | $16,560 | 0.0% | -157% |
| 2022 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price3-4 str0 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:all tier:hot age:old] 30%, 3 new | $21,239 | 0.0% | -72% |
| 2023 | RUN200-short r_t15 d2c/t0.50/s0.00 [price1-4 str0 dv1 so:o10 tier:all age:all] 30% + STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:old] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str2 dv1 so:all tier:all age:all] 30%, 3 new | $23,932 | 0.0% | -11% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price1-4 str0 dv0 so:all tier:all age:all] 30% + RUN200-short r_ah0 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30%, 5 new | $114,284 | 0.0% | +335% |
| 2025 | CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + STRONG-short c_pm20 d10c/t0.25/s0.00 [price2-4 str1 dv2 so:all tier:all age:all] 30% + RUN200-short r_ah0 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:all age:all] 30%, 5 new | $274,413 | 0.0% | +571% |
| 2026 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + RUN100-short r_hodf d5c/t0.00/s0.00 [price1-2 str0 dv0 so:u10 tier:hot age:all] 30% + GAPUP-short o_0945 d10c/t0.25/s0.00 [price0-3 str0 dv3 so:u50 tier:hot age:old] 20%, 5 new | $584,048 | 0.0% | +976% |

## roll3/cap25/r10: the book of each test year

| year | book | train med | train ruin | year return at $5k |
|---|---|---|---|---|
| 2018 | RUNUP-short c_rl5 d5c/t0.00/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + RUNUP-short c_ah0 d10c/t0.25/s0.00 [price1-4 str1 dv2 so:all tier:hot age:all] 30% + RUN100-short r_open1 d1c/t0.50/s1.00 [price0-4 str0 dv0 so:all tier:nohot age:old] 30%, 3 new | $29,103 | 0.0% | +35% |
| 2019 | RUNUP-short c_rl5 d5c/t0.50/s0.00 [price0-4 str0 dv2 so:known tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price0-3 str0 dv0 so:all tier:all age:old] 20% + RUN100-short r_pm0 d1c/t0.25/s0.00 [price0-3 str0 dv0 so:known tier:all age:all] 30%, 3 new | $31,577 | 0.0% | +12% |
| 2020 | STRONG-short c_pm20 d10c/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% + RUNUP-short c_rl5 d10c/t0.25/s0.00 [price0-4 str0 dv1 so:known tier:all age:all] 30% + CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-3 str1 dv0 so:all tier:all age:old] 20%, 5 new | $48,407 | 0.0% | -241% |
| 2021 | STRONG-short c_pm0 d1c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:hot age:all] 30% + RUNUP-short c_rl10 d10c/t0.25/s0.00 [price0-3 str0 dv0 so:u50 tier:all age:all] 30% + RUNUP-short c_rl10 d10c/t0.25/s0.00 [price1-3 str0 dv0 so:u50 tier:all age:all] 30%, 3 new | $16,560 | 0.0% | -157% |
| 2022 | STRONG-short c_ah10 d10c/t0.25/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price3-4 str0 dv2 so:all tier:all age:all] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str0 dv3 so:all tier:hot age:old] 30%, 3 new | $21,239 | 0.0% | -72% |
| 2023 | RUN200-short r_t15 d2c/t0.50/s0.00 [price1-4 str0 dv1 so:o10 tier:all age:all] 30% + STRONG-short c_ah10 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:hot age:old] 30% + RUNUP-short c_ah5 d10c/t0.25/s0.00 [price2-4 str2 dv1 so:all tier:all age:all] 30%, 3 new | $23,932 | 0.0% | -11% |
| 2024 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + CRASH-long c_ah0 d1pm/t0.25/s1.00 [price1-4 str0 dv0 so:all tier:all age:all] 30% + RUN200-short r_ah0 d5c/t0.00/s0.00 [price1-4 str0 dv1 so:all tier:all age:old] 30%, 5 new | $114,284 | 0.0% | +335% |
| 2025 | CRASH-long c_ah0 d1pm/t0.50/s0.00 [price0-4 str0 dv0 so:all tier:nohot age:all] 30% + STRONG-short c_pm20 d10c/t0.25/s0.00 [price2-4 str1 dv2 so:all tier:all age:all] 30% + RUN200-short r_ah0 d10c/t0.25/s0.00 [price2-4 str0 dv1 so:all tier:all age:all] 30%, 5 new | $274,413 | 0.0% | +571% |
| 2026 | CRASH-long c_ah0 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30% + RUN100-short r_hodf d5c/t0.00/s0.00 [price1-2 str0 dv0 so:u10 tier:hot age:all] 30% + GAPUP-short o_0945 d10c/t0.25/s0.00 [price0-3 str0 dv3 so:u50 tier:hot age:old] 20%, 5 new | $584,048 | 0.0% | +976% |

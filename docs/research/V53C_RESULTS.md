# v53c results: the size chosen out of sample too

Run 41320222009 (2026-11-01), pre-registered in V53C_PREREGISTRATION.md.

## Verdict: NOT MET

No (procedure, variant) keeps selection ruin (2018-2024) at or under 2.5%: 27.6% to 51.7% at base. Every sequence
from $5,000 through 2018-2026 ends at $0.

## What happened

- 2018 starts at scale 0.10. The 2018 books earn, so the history of 2018 alone allows scale 0.75 for 2019; after a
  good 2019, the rule allows 0.75 to 1.00 for 2020.
- 2020 is the year v53's short books lose most (v53: -50% to -347% simple sums at full size). At 0.75-1.00 the
  accounts are ruined there, before the rule can learn from it.
- After 2020 the rule falls back to 0.15-0.25 or cash, too late.

## Reading

v53b's scale 0.25 met its rule only because it was chosen on 2018-2024 with the 2020-2022 losses in view. A size rule
that sees only the past scales up on 2018-2019 and is ruined in 2020. With this grid there is no out-of-sample way,
for the books or for their size, to keep ruin at 2.5% or less: the 2020-2022 short losses are not foreseeable from
the years before them.

Data: data/v53c_summary.json (aggregate statistics only).

## Report (verbatim)

# v53c report: the size chosen out of sample too

Pre-registered in V53C_PREREGISTRATION.md. Each year's scale from the procedure's own earlier years only.

**No (procedure, variant) keeps selection ruin at or under 2.5% at base and HOT 5%: NOT MET.**

## Every (procedure, variant), out of sample

| procedure | variant | scale by year 2018-2026 | sel med | sel ruin | sel HOT5 ruin | lock med | lock ruin | all med | all ruin | borrow x2 all | locates never fail all | half rates all | history end | history low |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| exp/raw/r25 | safe | 0.10 0.75 1.00 0.50 0.15 0.15 0.15 0.15 0.15 | $3,450 | 41.8% | 41.9% | $6,626 | 0.0% | $4,305 | 34.0% | $3,813 / 34.8% | $1,311 / 51.5% | $3,371 / 42.1% | $0 | $0 |
| exp/raw/r25 | best | 0.10 0.75 0.75 0.50 cash cash cash cash cash | $4,296 | 27.6% | 27.9% | $3,740 | 0.0% | $4,256 | 22.5% | $3,891 / 24.3% | $4,310 / 32.1% | $4,334 / 28.3% | $0 | $0 |
| exp/raw/r10 | safe | 0.10 0.75 1.00 0.50 0.15 0.15 0.15 0.15 0.15 | $3,450 | 41.8% | 41.9% | $6,444 | 0.0% | $4,279 | 34.0% | $3,790 / 34.8% | $1,299 / 51.6% | $3,346 / 42.1% | $0 | $0 |
| exp/raw/r10 | best | 0.10 0.75 0.75 0.50 cash cash cash cash cash | $4,296 | 27.6% | 27.9% | $3,740 | 0.0% | $4,256 | 22.5% | $3,891 / 24.3% | $4,310 / 32.1% | $4,334 / 28.3% | $0 | $0 |
| exp/cap25/r25 | safe | 0.10 0.75 1.00 0.50 0.25 0.25 0.25 0.25 0.25 | $2,495 | 45.9% | 46.1% | $6,695 | 0.0% | $3,950 | 37.9% | $3,623 / 39.0% | $818 / 55.4% | $1,953 / 49.1% | $0 | $0 |
| exp/cap25/r25 | best | 0.10 0.75 0.75 0.50 cash cash 0.25 0.25 0.25 | $3,572 | 33.5% | 33.8% | $6,695 | 0.0% | $4,179 | 26.5% | $3,932 / 28.1% | $3,545 / 39.8% | $3,281 / 39.3% | $0 | $0 |
| exp/cap25/r10 | safe | 0.10 0.75 1.00 0.50 0.25 0.25 0.25 0.25 0.25 | $2,495 | 45.9% | 46.1% | $6,695 | 0.0% | $3,950 | 37.9% | $3,623 / 39.0% | $818 / 55.4% | $1,953 / 49.1% | $0 | $0 |
| exp/cap25/r10 | best | 0.10 0.75 0.75 0.50 cash cash 0.25 0.25 0.25 | $3,572 | 33.5% | 33.8% | $6,695 | 0.0% | $4,179 | 26.5% | $3,932 / 28.1% | $3,545 / 39.8% | $3,281 / 39.3% | $0 | $0 |
| roll3/raw/r25 | safe | 0.10 0.75 1.00 0.25 0.25 0.25 0.25 0.25 0.25 | $1,533 | 50.6% | 50.8% | $14,474 | 0.0% | $3,595 | 40.2% | $3,130 / 42.9% | $132 / 55.8% | $1,388 / 50.7% | $0 | $0 |
| roll3/raw/r25 | best | 0.10 0.75 0.75 0.25 0.25 0.25 cash 0.25 0.25 | $3,249 | 40.8% | 41.0% | $14,474 | 0.0% | $4,530 | 31.9% | $4,229 / 33.3% | $719 / 53.6% | $1,723 / 50.5% | $0 | $0 |
| roll3/raw/r10 | safe | 0.10 0.75 1.00 0.25 0.25 0.25 0.25 0.25 0.25 | $1,533 | 50.6% | 50.8% | $14,474 | 0.0% | $3,595 | 40.2% | $3,130 / 42.9% | $132 / 55.8% | $1,388 / 50.7% | $0 | $0 |
| roll3/raw/r10 | best | 0.10 0.75 0.75 0.25 0.25 0.25 cash 0.25 0.25 | $3,249 | 40.8% | 41.0% | $14,474 | 0.0% | $4,530 | 31.9% | $4,229 / 33.3% | $719 / 53.6% | $1,723 / 50.5% | $0 | $0 |
| roll3/cap25/r25 | safe | 0.10 0.75 1.00 0.25 0.25 0.25 0.25 0.25 0.25 | $1,412 | 51.7% | 51.9% | $15,202 | 0.0% | $3,417 | 41.5% | $3,250 / 42.8% | $150 / 56.1% | $1,384 / 50.9% | $0 | $0 |
| roll3/cap25/r25 | best | 0.10 0.75 0.75 0.25 0.25 0.25 cash 0.25 0.25 | $2,460 | 44.3% | 44.4% | $15,202 | 0.0% | $3,936 | 34.3% | $3,605 / 36.7% | $782 / 53.6% | $1,506 / 51.1% | $0 | $0 |
| roll3/cap25/r10 | safe | 0.10 0.75 1.00 0.25 0.25 0.25 0.25 0.25 0.25 | $1,412 | 51.7% | 51.9% | $15,202 | 0.0% | $3,417 | 41.5% | $3,250 / 42.8% | $150 / 56.1% | $1,384 / 50.9% | $0 | $0 |
| roll3/cap25/r10 | best | 0.10 0.75 0.75 0.25 0.25 0.25 cash 0.25 0.25 | $2,460 | 44.3% | 44.4% | $15,202 | 0.0% | $3,936 | 34.3% | $3,605 / 36.7% | $782 / 53.6% | $1,506 / 51.1% | $0 | $0 |

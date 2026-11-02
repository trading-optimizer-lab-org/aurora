# v54m results: the cost of a safety margin on the fixed daily book

Run 41514842362 (2026-11-02), pre-registered in V54M_PREREGISTRATION.md. v54's daily account returns, no new
simulation. Check: v49's fixed book here $8,375 all-sample, ruin 0.1%, as in v54.

## Verdict by the pre-registered rule: margin is DEAR

- **v49's book has no margin, on two members, not one.** One step up in RU (25%) has all-sample ruin 8.9% and a
  -52% 2024; one step up in DS (30%) has ruin 5.5% (15.3% if locates fail half as often). Only NS has room (60%:
  ruin 0.2%).
- **Margin pick: DS0.00-NS0.40-RU0.15-N5** (DS1 left out). All-sample $6,763 against v49's $8,375 (-19%), lockbox
  $6,034 against $6,948, selection $6,979 against $8,800. Ruin 0.0% at base, HOT 5% and every stress set; every
  calendar year positive at $5k (+10% to +82%).
- 10 of 126 books have margin; the next is DS0.20-NS0.00-RU0.15 at $6,701 (lockbox $6,628, the best lockbox among
  them).

## Reading

Buying a step of margin costs about a fifth of the median, more than the 10% the rule called cheap. The choice is
a plain trade-off: v49's sizes earn more but sit one step from a cliff on two members; the margin pick earns about
$1,700 less a year from $5,000 in the median and has no tested cliff next to it. Both are still chosen on the same
2019-2026 they are graded on.

Data: data/v54m_summary.json (the verdict, the margin flags and the grades of the books in the tables).

## Report (verbatim)

# v54m report: the cost of a safety margin on the fixed daily book

Pre-registered in V54M_PREREGISTRATION.md. 126 v54 books held fixed 2019-2026. v49's book DS0.20-NS0.40-RU0.20-N5: all $8,375, ruin 0.1%; lockbox $6,948.

**Margin pick: DS0.00-NS0.40-RU0.15-N5. All $6,763 against v49's $8,375 (-19%); lockbox $6,034 against $6,948. Margin is dear.**

## v49's book, its neighbours and the margin pick

| book | sel med | lock med | all med | all ruin | all HOT5 ruin | borrow x2 ruin | locates never fail ruin | locates fail half as often ruin | years 2019-2026 at $5k, % | margin |
|---|---|---|---|---|---|---|---|---|---|---|
| DS0.20-NS0.40-RU0.20-N5 (v49) | $8,800 | $6,948 | $8,375 | 0.1% | 0.1% | 0.2% | 0.2% | 0.1% | +52 +155 +101 +29 +55 +68 +55 +42 | no |
| DS0.30-NS0.40-RU0.20-N5 (v49 +1 step) | $9,510 | $7,915 | $9,213 | 5.5% | 5.7% | 8.2% | 11.8% | 15.3% | +58 +150 +111 +31 +57 +105 +77 +54 | no |
| DS0.20-NS0.60-RU0.20-N5 (v49 +1 step) | $9,669 | $6,713 | $8,984 | 0.2% | 0.2% | 0.5% | 0.7% | 0.4% | +68 +177 +130 +27 +64 +74 +56 +42 | no |
| DS0.20-NS0.40-RU0.25-N5 (v49 +1 step) | $8,329 | $7,048 | $7,948 | 8.9% | 9.1% | 10.7% | 0.3% | 0.1% | +55 +161 +105 +37 +62 -52 +57 +42 | no |
| DS0.00-NS0.40-RU0.15-N5 **margin pick** | $6,979 | $6,034 | $6,763 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +57 +58 +82 +20 +41 +10 +36 +32 | yes |
| DS0.00-NS0.60-RU0.15-N5 (pick +1 step) | $7,653 | $5,770 | $7,237 | 0.1% | 0.2% | 0.3% | 0.3% | 0.4% | +73 +80 +111 +18 +50 +16 +37 +32 | no |
| DS0.00-NS0.40-RU0.20-N5 (pick +1 step) | $7,202 | $6,602 | $7,069 | 0.1% | 0.1% | 0.2% | 0.5% | 0.1% | +66 +62 +88 +29 +50 +5 +48 +42 | no |

## The best books with margin (10 of 126)

| book | sel med | lock med | all med | all ruin | all HOT5 ruin | borrow x2 ruin | locates never fail ruin | locates fail half as often ruin | years 2019-2026 at $5k, % | margin |
|---|---|---|---|---|---|---|---|---|---|---|
| DS0.00-NS0.40-RU0.15-N5 | $6,979 | $6,034 | $6,763 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +57 +58 +82 +20 +41 +10 +36 +32 | yes |
| DS0.00-NS0.40-RU0.15-N8 | $6,979 | $6,034 | $6,763 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +57 +58 +82 +20 +41 +10 +36 +32 | yes |
| DS0.20-NS0.00-RU0.15-N5 | $6,679 | $6,628 | $6,701 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +19 +103 +27 +23 +29 +54 +43 +31 | yes |
| DS0.20-NS0.00-RU0.15-N8 | $6,679 | $6,628 | $6,701 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +19 +103 +27 +23 +29 +54 +43 +31 | yes |
| DS0.20-NS0.00-RU0.00-N5 | $6,150 | $6,550 | $6,285 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +11 +111 +20 +3 +5 +48 +44 +31 | yes |
| DS0.20-NS0.00-RU0.00-N8 | $6,150 | $6,550 | $6,285 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +11 +111 +20 +3 +5 +48 +44 +31 | yes |
| DS0.00-NS0.40-RU0.00-N5 | $6,350 | $4,829 | $5,996 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +31 +48 +70 -2 +17 +20 +9 -1 | yes |
| DS0.00-NS0.40-RU0.00-N8 | $6,350 | $4,829 | $5,996 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +31 +48 +70 -2 +17 +20 +9 -1 | yes |
| DS0.00-NS0.00-RU0.15-N5 | $5,529 | $5,925 | $5,603 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +27 +11 +12 +22 +24 -8 +27 +22 | yes |
| DS0.00-NS0.00-RU0.15-N8 | $5,529 | $5,925 | $5,603 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | +27 +11 +12 +22 +24 -8 +27 +22 | yes |

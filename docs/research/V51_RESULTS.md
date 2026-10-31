# v51 results

Run 41213703767 (20 factory jobs, select, 300 account jobs, pick, 300 book jobs, pick2, 51 confirmation jobs and the
final job, all success; about 18 minutes). Data run 41206767350: 123,632 events, 355,876 symbol-days of one-minute
bars 04:00-19:59, 355,608 with bars (2.2 GB, Actions cache only). Pre-registration: `V51_PREREGISTRATION.md`
(section 6 lists the amendments made after a code review and before the run). The report below is the final job's
artifact; aggregate tables are in `data/v51_summary.json`.

## Verdict

- 212,576,400 configurations scored (setup x side x entry x exit x filter set), 5,941,467 pass the vetoes. 173 of the
  193 selected configurations are eligible alone; all 13,140 books of 1-3 of the 12 best singles are eligible on
  2018-2022 paths.
- Answer by the pre-registered rule (highest ensemble median on 2018-2022 paths among confirmed books with design
  ruin at most 2.5%): **STRONG-short c_ah5 d2c/t0.50 [$5-20, close +50%, $3M] 30% + RUNUP-short c_ah5 d10c
  [close 4x the five-session low, $1M] 30% + FADE-short c_pm0 d1pm/t0.50/s1.00 [$2-20] 30%, 5 new a day**.
  2018-2022 paths: median $27,834, ruin 0.0%. 2023+ paths: median **$2,172, ruin 50.1%**. All paths: median
  **$11,215, ruin 22.1%** (HOT 5% $10,858, 22.3%). The historical path from $5,000 ends at $0 (2026).
  Target **NOT MET**: the design-chosen book does not survive 2023+.
- v50's book in v51's terms: $13,461, ruin 6.9% (HOT 5% $12,731, 7.2%); v50's own engine reported $9,065, 0.1%.
- Failed locates: in every confirmed book "locates never fail" lowers the median or raises ruin a lot (the answer
  $1,562; v50's book $5,632 with ruin 40.7%). The seeded failures remove HOT shorts that squeeze; the chosen
  configurations fit that particular draw. The locate assumption remains the largest unknown.

## Post hoc, not an answer

Chosen after seeing 2023+, so biased; reported because it is the clearest pattern of the run. Of the 51 confirmed
books, the 6 with all-paths ruin at most 2.5% all hold **CRASH-long c_1555 d1pm** (buy at 15:55 a small cap down 20%
or more at 15:49, sell the next premarket with a resting limit at the close +3%, else at the open; target 25%). The
best: CRASH-long c_1555 d1pm/t0.25/s1.00 [$1M] 30% + RUNUP-short c_ah5 d10c 30% + FADE-short c_pm0 d1pm/t0.50/s1.00
30%, 5 new a day: all paths median $51,191, ruin 0.0%; 2018-2022 $22,960, 0.1%; 2023+ $158,270, 0.0%; borrow x2
$42,744, 0.0%; locates never fail $62,230, 9.1%; locates failing half as often $57,767, 0.5%; symbol halves
$19,600 / 0.0% and $21,844 / 11.2%.

CRASH-long alone, unfiltered, at the $1,000 reference size under TZC: 15,858 trades 2018-2026, PF 1.77 in 2018-2022
(7,050 trades, mean +1.7%) and 1.32 in 2023+ (8,808, +0.9%); PF by year 1.05, 1.27, 2.42, 1.15, 1.30, 1.23, 1.13,
1.50, 1.33; worst trade -71%. A long: no locate, no borrow, no short-sale rule.

## Caveats

- Hundreds of millions of configurations on 2018-2026: every figure is biased upward; the pre-registered choice
  shows how much (design $27,834, 2023+ $2,172).
- Resting limits in the premarket and after hours fill when one bar trades through the limit by 0.1%; a single
  odd-lot print can do that, so extended-session fills are optimistic.
- The 15:55 entries decide on SIP bars to 15:49; live, a free IEX snapshot gives slightly different prices.
- Some top configurations look like data errors (GAPDN-short entries that pass the short-sale rule after a 15% gap
  down, 73 trades in 2018-2022 and 2 after); none is in the answer or the post hoc book.
- One-year paths above $60,000 keep the $60,000 level's sizes (capped at 1% of dollar volume); the historical paths
  of the post hoc books compound without limit and are not meaningful.

## Report (verbatim from run 41213703767)

# v51 report: every small-cap setup on one-minute bars

Pre-registered in V51_PREREGISTRATION.md. Configurations scored: 212,576,400 (5,941,467 pass the vetoes).

**NOT MET.** Answer: STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] at 30% + RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] at 30% + FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] at 30%, 5 new a day.

- all paths: median $11,215, ruin 22.1% (HOT 5%: $10,858, 22.3%)
- 2018-2022 paths: median $27,834, ruin 0.0%; 2023+ paths: median $2,172, ruin 50.1%

## Confirmed books

| book | new | all med | all ruin | HOT5 med | HOT5 ruin | design med | later med | borrow x2 | locates never fail | half rates | half 0 | half 1 | history from $5k |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 5 | $11,215 | 22.1% | $10,858 | 22.3% | $27,834 | $2,172 | $8,996 | $1,562 | $4,892 | $7,974 | $7,821 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 5 | $11,112 | 22.2% | $10,768 | 22.4% | $27,586 | $2,091 | $8,963 | $1,418 | $4,915 | $7,974 | $7,863 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 5 | $10,304 | 27.6% | $9,989 | 27.7% | $27,580 | $1,072 | $8,638 | $915 | $2,287 | $7,866 | $7,977 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 5 | $10,195 | 27.7% | $9,886 | 27.8% | $27,328 | $1,012 | $8,595 | $894 | $2,328 | $7,865 | $8,008 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 3 | $11,061 | 22.1% | $10,710 | 22.3% | $26,777 | $2,172 | $8,872 | $3,531 | $7,950 | $7,968 | $7,810 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $10,882 | 22.0% | $10,576 | 22.1% | $26,567 | $2,215 | $8,872 | $1,415 | $4,750 | $7,875 | $7,703 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 3 | $10,959 | 22.3% | $10,615 | 22.5% | $26,532 | $2,091 | $8,840 | $3,456 | $8,052 | $7,974 | $7,844 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 3 | $10,170 | 27.7% | $9,856 | 27.8% | $26,527 | $1,072 | $8,523 | $2,605 | $5,035 | $7,863 | $7,923 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $10,819 | 21.9% | $10,505 | 22.1% | $26,521 | $2,189 | $8,751 | $1,379 | $4,587 | $7,832 | $7,675 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $9,947 | 27.5% | $9,667 | 27.6% | $26,252 | $1,092 | $8,464 | $878 | $2,239 | $7,751 | $7,835 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 3 | $10,057 | 27.7% | $9,750 | 27.9% | $26,251 | $1,011 | $8,477 | $2,766 | $5,470 | $7,862 | $7,974 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $9,907 | 27.5% | $9,627 | 27.6% | $26,155 | $1,074 | $8,385 | $894 | $2,187 | $7,744 | $7,851 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 5 | $10,758 | 22.1% | $10,429 | 22.3% | $26,119 | $2,085 | $8,741 | $1,313 | $4,590 | $7,838 | $7,694 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 5 | $10,771 | 21.9% | $10,444 | 22.1% | $25,949 | $2,127 | $8,728 | $1,229 | $4,539 | $7,882 | $7,642 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 5 | $9,902 | 27.7% | $9,604 | 27.9% | $25,733 | $1,022 | $8,397 | $917 | $2,182 | $7,744 | $7,765 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 3 | $10,686 | 22.1% | $10,364 | 22.3% | $25,654 | $2,084 | $8,686 | $1,269 | $4,489 | $7,832 | $7,694 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 5 | $9,921 | 27.6% | $9,626 | 27.7% | $25,597 | $1,047 | $8,378 | $797 | $2,147 | $7,792 | $7,729 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 3 | $10,754 | 22.0% | $10,448 | 22.2% | $25,550 | $2,215 | $8,771 | $2,940 | $7,583 | $7,870 | $7,673 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 3 | $10,703 | 21.9% | $10,380 | 22.1% | $25,521 | $2,126 | $8,679 | $1,194 | $4,454 | $7,878 | $7,642 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 3 | $10,686 | 22.0% | $10,377 | 22.2% | $25,491 | $2,189 | $8,643 | $3,414 | $7,593 | $7,832 | $7,655 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 3 | $9,846 | 27.8% | $9,550 | 27.9% | $25,264 | $1,022 | $8,340 | $874 | $2,134 | $7,734 | $7,765 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 3 | $9,832 | 27.6% | $9,547 | 27.7% | $25,259 | $1,091 | $8,353 | $2,205 | $4,711 | $7,751 | $7,796 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 3 | $9,872 | 27.6% | $9,570 | 27.7% | $25,130 | $1,047 | $8,326 | $769 | $2,089 | $7,788 | $7,729 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 3 | $9,788 | 27.5% | $9,514 | 27.7% | $25,059 | $1,073 | $8,279 | $2,614 | $4,986 | $7,744 | $7,819 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 5 | $10,373 | 20.0% | $10,083 | 20.1% | $24,152 | $2,743 | $8,696 | $3,134 | $9,038 | $7,596 | $7,894 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20% | 5 | $10,256 | 20.0% | $9,976 | 20.1% | $23,924 | $2,694 | $8,654 | $3,061 | $8,981 | $7,567 | $7,945 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20% | 5 | $10,107 | 22.0% | $9,826 | 22.2% | $23,867 | $2,235 | $8,735 | $2,373 | $8,394 | $7,499 | $7,910 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20% | 5 | $10,019 | 21.9% | $9,748 | 22.1% | $23,672 | $2,182 | $8,698 | $2,395 | $8,389 | $7,506 | $7,959 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% | 5 | $40,049 | 8.5% | $39,134 | 8.6% | $23,613 | $85,123 | $36,677 | $41,200 | $36,431 | $15,490 | $22,177 | $4,432,460,068,342 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 3 | $10,241 | 20.0% | $9,955 | 20.2% | $23,302 | $2,738 | $8,597 | $5,850 | $10,503 | $7,596 | $7,860 | $0 |
| RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% | 5 | $46,915 | 0.4% | $45,677 | 0.4% | $23,071 | $114,645 | $39,376 | $55,774 | $50,357 | $22,139 | $19,624 | $8,735,014,838,258 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 20% | 5 | $10,336 | 22.4% | $10,081 | 22.6% | $23,054 | $2,257 | $8,469 | $1,347 | $4,661 | $7,518 | $7,516 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20% | 3 | $10,129 | 20.0% | $9,851 | 20.2% | $23,031 | $2,690 | $8,546 | $6,133 | $10,533 | $7,567 | $7,891 | $0 |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] 30%; STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 5 | $49,399 | 9.1% | $48,300 | 9.1% | $23,002 | $140,937 | $45,326 | $49,960 | $44,336 | $16,423 | $31,311 | $23,648,692,587,372 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $10,066 | 19.7% | $9,805 | 19.9% | $22,980 | $2,824 | $8,571 | $2,937 | $8,676 | $7,531 | $7,750 | $0 |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 5 | $51,191 | 0.0% | $49,817 | 0.0% | $22,960 | $158,270 | $42,744 | $62,230 | $57,767 | $19,600 | $21,844 | $74,763,111,738,924 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 20%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 5 | $10,284 | 22.6% | $10,033 | 22.7% | $22,913 | $2,206 | $8,446 | $1,271 | $4,628 | $7,510 | $7,543 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $9,975 | 19.8% | $9,720 | 19.9% | $22,898 | $2,750 | $8,450 | $3,025 | $8,562 | $7,508 | $7,748 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% | 5 | $39,578 | 8.5% | $38,678 | 8.5% | $22,839 | $86,170 | $36,492 | $41,244 | $36,751 | $15,510 | $22,270 | $4,259,523,545,120 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 20%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30% | 5 | $11,448 | 8.6% | $11,094 | 8.7% | $22,698 | $4,182 | $9,216 | $4,761 | $6,604 | $8,027 | $7,906 | $3,623,697 |
| FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 5 | $50,884 | 0.0% | $49,503 | 0.0% | $22,608 | $160,202 | $42,838 | $62,901 | $57,995 | $19,691 | $21,975 | $72,543,377,872,058 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30% | 5 | $11,382 | 8.8% | $11,030 | 9.0% | $22,564 | $4,133 | $9,228 | $4,765 | $6,753 | $8,012 | $7,947 | $3,703,261 |
| FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30% | 5 | $46,452 | 0.4% | $45,193 | 0.4% | $22,520 | $117,057 | $39,242 | $56,848 | $51,090 | $22,074 | $19,698 | $7,475,456,466,742 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 5 | $10,000 | 20.0% | $9,725 | 20.1% | $22,492 | $2,700 | $8,476 | $3,108 | $8,450 | $7,514 | $7,702 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] 30% | 5 | $9,979 | 20.0% | $9,713 | 20.1% | $22,383 | $2,721 | $8,428 | $2,948 | $8,406 | $7,523 | $7,655 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 20% | 5 | $10,123 | 22.4% | $9,885 | 22.5% | $22,287 | $2,276 | $8,357 | $1,226 | $4,529 | $7,386 | $7,408 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 20%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 3 | $9,946 | 19.8% | $9,691 | 19.9% | $22,166 | $2,820 | $8,457 | $5,330 | $9,913 | $7,528 | $7,707 | $0 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $39,563 | 8.5% | $38,739 | 8.5% | $22,151 | $90,155 | $36,544 | $39,130 | $35,644 | $15,793 | $21,786 | $4,278,398,555,951 |
| RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30%; FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $46,206 | 0.4% | $45,087 | 0.4% | $21,793 | $119,119 | $39,165 | $53,671 | $49,143 | $22,416 | $19,430 | $8,271,121,518,809 |
| RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] 30%; CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] 30%; FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] 30% | 5 | $45,488 | 0.5% | $44,354 | 0.5% | $21,402 | $119,760 | $38,690 | $54,227 | $48,996 | $22,453 | $19,392 | $8,050,455,564,480 |
| **v50** RUNUP-short c_open d5c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] v50:DS1 20%; RUNUP-short c_open d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] v50:RU 20%; FADE-short c_1555 d3c/t0.00/s0.00 [price2-2 str0 dv1 so:all tier:all age:all] v50:NS 60% | 5 | $13,461 | 6.9% | $12,731 | 7.2% | $11,549 | $15,444 | $8,951 | $5,632 | $10,571 | $9,613 | $8,164 | $5,063,410 |

v50's book in v51's terms is marked; v50 itself reported a median of $9,065.

## The 12 singles

| configuration | design med (best size) | size | new |
|---|---|---|---|
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:all] | $12,438 | 40% | 5 |
| STRONG-short c_ah5 d2c/t0.50/s0.00 [price3-4 str1 dv2 so:all tier:all age:all] | $11,522 | 40% | 3 |
| FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] | $11,426 | 40% | 5 |
| CRASH-long c_1555 d1pm/t0.25/s1.00 [price0-4 str0 dv1 so:all tier:all age:all] | $11,397 | 40% | 5 |
| RUNUP-short c_ah5 d10c/t0.00/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] | $11,381 | 40% | 3 |
| FADE-short c_pm0 d1pm/t0.50/s1.00 [price2-4 str0 dv0 so:all tier:all age:all] | $11,225 | 40% | 5 |
| CRASH-long c_1555 d1pm/t0.25/s0.00 [price0-4 str0 dv0 so:all tier:all age:old] | $11,169 | 40% | 5 |
| RUNUP-short c_ah5 d10c/t0.50/s0.00 [price0-4 str2 dv1 so:all tier:all age:all] | $10,986 | 40% | 3 |
| FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] | $10,682 | 40% | 5 |
| FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-4 str0 dv1 so:all tier:all age:all] | $10,395 | 40% | 5 |
| FADE-short c_pm0 d1pm/t0.25/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] | $10,392 | 40% | 5 |
| FADE-short c_pm0 d1pm/t0.00/s1.00 [price2-3 str0 dv0 so:all tier:all age:all] | $10,166 | 40% | 5 |

Books run: 13,140; eligible: 13,140.

## Each group's best configurations (factory, $1,000 reference size, TZC costs)

| group | events | entry | exit | filters | score | trades | PF 2018-22 | PF 2023+ | worst |
|---|---|---|---|---|---|---|---|---|---|
| RUNUP-short | 8,502 | c_ah5 | d10c/t0.25/s0.00 | price0-4 str2 dv1 so:all tier:all age:all  | 288.74 | 105 | 29.87 | 3.84 | -106.2% |
| RUNUP-short | 8,502 | c_ah5 | d10c/t0.25/s0.00 | price0-4 str2 dv0 so:all tier:all age:all  | 185.05 | 115 | 18.13 | 4.27 | -106.2% |
| RUNUP-short | 8,502 | c_ah5 | d10c/t0.00/s0.00 | price0-4 str2 dv1 so:all tier:all age:all  | 157.86 | 104 | 16.79 | 2.52 | -106.2% |
| RUNUP-short | 8,502 | c_ah5 | d10c/t0.50/s0.00 | price0-4 str2 dv1 so:all tier:all age:all  | 155.12 | 104 | 16.51 | 2.54 | -106.2% |
| RUNUP-short | 8,502 | c_1555b | d3c/t0.25/s0.00 | price2-3 str0 dv1 so:known tier:all age:all  | 143.60 | 188 | 11.56 | 0.99 | -111.0% |
| RUNUP-short | 8,502 | c_1555b | d3c/t0.25/s0.00 | price2-3 str0 dv2 so:known tier:all age:all  | 141.16 | 164 | 12.57 | 0.99 | -111.0% |
| RUNUP-short | 8,502 | c_ah5 | d10c/t0.00/s0.00 | price0-4 str2 dv0 so:all tier:all age:all  | 140.85 | 114 | 14.04 | 2.89 | -106.2% |
| RUNUP-short | 8,502 | c_1555b | d3c/t0.25/s0.00 | price2-3 str0 dv3 so:known tier:hot age:all  | 139.57 | 130 | 14.68 | 0.92 | -111.0% |
| RUNUP-short | 8,502 | c_1555b | d3c/t0.25/s0.00 | price2-3 str0 dv3 so:known tier:all age:all  | 139.57 | 132 | 14.68 | 0.91 | -111.0% |
| RUNUP-short | 8,502 | c_1555b | d3c/t0.25/s0.00 | price2-3 str0 dv1 so:known tier:hot age:all  | 137.92 | 183 | 11.29 | 0.98 | -111.0% |
| RUNUP-short | 8,502 | c_open | d5c/t0.50/s0.00 | price0-4 str2 dv1 so:all tier:all age:all v50:DS1 | n/a | 377 | 2.22 | 1.97 | -208.4% |
| RUNUP-short | 8,502 | c_open | d10c/t0.50/s0.00 | price0-4 str2 dv1 so:all tier:all age:all v50:RU | n/a | 377 | 2.67 | 3.45 | -207.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.00/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 39.45 | 2121 | 1.31 | 0.90 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.00/s0.00 | price0-3 str0 dv0 so:all tier:all age:old  | 38.01 | 1848 | 1.33 | 0.82 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.00/s0.00 | price0-4 str0 dv0 so:all tier:all age:old  | 36.29 | 2080 | 1.27 | 0.83 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.00/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 36.13 | 2408 | 1.24 | 0.89 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1pm/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:hot age:all  | 34.66 | 2074 | 1.27 | 1.02 | -77.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.00/s1.00 | price0-3 str0 dv1 so:all tier:all age:all  | 34.58 | 1921 | 1.30 | 0.86 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.00/s0.00 | price0-3 str0 dv1 so:all tier:all age:old  | 34.37 | 1677 | 1.33 | 0.82 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1pm/t0.50/s0.00 | price0-4 str0 dv0 so:all tier:hot age:all  | 33.78 | 2074 | 1.27 | 1.03 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.50/s0.00 | price0-4 str0 dv0 so:all tier:hot age:all  | 33.56 | 2074 | 1.26 | 0.97 | -82.1% |
| RUNUP-long | 8,502 | c_ah5 | d1o/t0.25/s0.00 | price0-4 str0 dv1 so:all tier:all age:all  | 33.19 | 2202 | 1.25 | 1.06 | -77.1% |
| STRONG-short | 23,604 | c_ah10 | d10c/t0.25/s0.00 | price2-4 str0 dv2 so:all tier:hot age:all  | 360.97 | 92 | 35.05 | 7.10 | -67.9% |
| STRONG-short | 23,604 | c_ah10 | d5c/t0.25/s0.00 | price2-4 str0 dv2 so:all tier:hot age:all  | 290.91 | 92 | 28.44 | 3.73 | -51.9% |
| STRONG-short | 23,604 | c_ah10 | d5c/t0.25/s0.00 | price2-4 str0 dv1 so:all tier:hot age:all  | 180.49 | 112 | 16.04 | 4.74 | -51.9% |
| STRONG-short | 23,604 | c_ah10 | d10c/t0.25/s0.00 | price2-4 str0 dv1 so:all tier:hot age:old  | 178.48 | 99 | 18.50 | 8.95 | -67.9% |
| STRONG-short | 23,604 | c_ah10 | d10c/t0.25/s0.00 | price2-4 str0 dv1 so:all tier:hot age:all  | 169.44 | 112 | 15.12 | 9.26 | -67.9% |
| STRONG-short | 23,604 | c_ah10 | d5c/t0.25/s0.00 | price2-3 str0 dv1 so:all tier:hot age:all  | 167.46 | 97 | 17.75 | 4.80 | -51.9% |
| STRONG-short | 23,604 | c_ah5 | d2c/t0.50/s0.00 | price3-4 str1 dv2 so:all tier:all age:all  | 165.46 | 120 | 13.17 | 0.70 | -185.8% |
| STRONG-short | 23,604 | c_ah10 | d5c/t0.50/s0.00 | price2-4 str0 dv2 so:all tier:hot age:all  | 160.87 | 92 | 16.18 | 2.70 | -110.2% |
| STRONG-short | 23,604 | c_ah10 | d10c/t0.50/s0.00 | price2-4 str0 dv2 so:all tier:hot age:all  | 155.61 | 92 | 15.68 | 5.16 | -73.2% |
| STRONG-short | 23,604 | c_rl10 | d3c/t0.25/s0.00 | price0-3 str1 dv0 so:u50 tier:nohot age:all  | 155.39 | 134 | 14.17 | 1.32 | -129.4% |
| STRONG-long | 23,604 | c_1555 | d5c/t0.50/s0.00 | price0-4 str0 dv2 so:all tier:nohot age:old  | 94.89 | 2404 | 1.37 | 0.92 | -96.1% |
| STRONG-long | 23,604 | c_1555 | d5c/t0.25/s1.00 | price0-4 str0 dv2 so:all tier:nohot age:old  | 89.10 | 2405 | 1.35 | 0.95 | -96.1% |
| STRONG-long | 23,604 | c_1555 | d10c/t0.25/s0.00 | price1-4 str0 dv3 so:o10 tier:nohot age:all  | 88.85 | 749 | 2.09 | 1.25 | -83.1% |
| STRONG-long | 23,604 | c_1555 | d10c/t0.25/s0.00 | price0-4 str0 dv2 so:all tier:nohot age:old  | 85.94 | 2403 | 1.34 | 0.96 | -97.0% |
| STRONG-long | 23,604 | c_1555 | d5c/t0.50/s0.00 | price0-4 str0 dv2 so:all tier:nohot age:all  | 84.00 | 2914 | 1.29 | 0.87 | -96.1% |
| STRONG-long | 23,604 | c_1555 | d10c/t0.25/s0.00 | price1-4 str0 dv3 so:o10 tier:nohot age:old  | 83.99 | 701 | 2.08 | 1.20 | -83.1% |
| STRONG-long | 23,604 | c_1555 | d5c/t0.50/s0.00 | price0-4 str0 dv2 so:o10 tier:nohot age:all  | 82.85 | 1590 | 1.49 | 1.06 | -96.1% |
| STRONG-long | 23,604 | c_1555 | d10c/t0.25/s0.00 | price0-4 str0 dv3 so:o10 tier:nohot age:all  | 82.26 | 783 | 1.98 | 1.19 | -83.1% |
| STRONG-long | 23,604 | c_1555 | d5c/t0.50/s0.00 | price0-4 str0 dv2 so:o10 tier:nohot age:old  | 81.84 | 1469 | 1.52 | 1.07 | -96.1% |
| STRONG-long | 23,604 | c_1555 | d10c/t0.25/s0.00 | price2-4 str0 dv3 so:o10 tier:nohot age:all  | 81.80 | 657 | 2.17 | 1.25 | -59.6% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.25/s1.00 | price2-4 str0 dv0 so:all tier:all age:all  | 106.82 | 344 | 3.66 | 1.14 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.50/s1.00 | price2-4 str0 dv0 so:all tier:all age:all  | 105.18 | 344 | 3.62 | 1.12 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.25/s1.00 | price2-4 str0 dv1 so:all tier:all age:all  | 101.71 | 307 | 3.83 | 1.16 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.50/s1.00 | price2-2 str0 dv0 so:all tier:all age:all  | 101.62 | 198 | 5.34 | 0.93 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.50/s0.00 | price2-2 str0 dv0 so:all tier:all age:all  | 101.62 | 198 | 5.34 | 0.75 | -355.0% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.00/s1.00 | price2-4 str0 dv1 so:all tier:all age:all  | 100.19 | 307 | 3.78 | 1.16 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.25/s1.00 | price2-2 str0 dv0 so:all tier:all age:all  | 99.95 | 198 | 5.27 | 0.96 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.25/s0.00 | price2-2 str0 dv0 so:all tier:all age:all  | 99.95 | 198 | 5.27 | 0.77 | -355.0% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.25/s1.00 | price2-3 str0 dv0 so:all tier:all age:all  | 95.65 | 283 | 3.92 | 1.14 | -102.1% |
| FADE-short | 4,365 | c_pm0 | d1pm/t0.00/s1.00 | price2-3 str0 dv0 so:all tier:all age:all  | 93.82 | 283 | 3.86 | 1.12 | -102.1% |
| FADE-short | 4,365 | c_1555 | d3c/t0.00/s0.00 | price2-2 str0 dv1 so:all tier:all age:all v50:NS | n/a | 195 | 3.36 | 2.13 | -89.2% |
| FADE-long | 4,365 | c_1030 | d1pm/t0.00/s1.00 | price1-3 str1 dv2 so:all tier:all age:all  | 39.93 | 311 | 2.33 | 0.87 | -56.5% |
| FADE-long | 4,365 | c_orb | d1pm/t0.00/s0.00 | price1-4 str0 dv2 so:all tier:all age:all  | 39.67 | 428 | 1.95 | 0.94 | -62.9% |
| FADE-long | 4,365 | c_1030 | d1pm/t0.00/s0.00 | price0-3 str1 dv2 so:all tier:hot age:all  | 39.45 | 371 | 2.17 | 0.77 | -56.5% |
| FADE-long | 4,365 | c_1030 | d1pm/t0.00/s0.00 | price2-3 str1 dv2 so:all tier:all age:all  | 39.00 | 221 | 2.76 | 0.84 | -56.5% |
| FADE-long | 4,365 | c_orb | d1pm/t0.00/s1.00 | price1-3 str0 dv2 so:all tier:all age:all  | 36.96 | 377 | 2.03 | 0.91 | -62.9% |
| FADE-long | 4,365 | c_orb | d1pm/t0.00/s0.25 | price1-4 str0 dv2 so:all tier:all age:all  | 35.69 | 428 | 1.85 | 0.90 | -27.4% |
| FADE-long | 4,365 | c_1030 | d1pm/t0.00/s1.00 | price1-4 str0 dv2 so:all tier:all age:all  | 35.46 | 715 | 1.47 | 0.96 | -66.9% |
| FADE-long | 4,365 | c_1030 | d1pm/t0.00/s0.25 | price1-3 str0 dv2 so:all tier:all age:all  | 35.30 | 613 | 1.56 | 0.96 | -28.0% |
| FADE-long | 4,365 | c_1200 | d1pm/t0.00/s0.00 | price2-3 str0 dv0 so:all tier:all age:young  | 34.96 | 118 | 3.39 | 1.29 | -30.2% |
| FADE-long | 4,365 | c_1200 | d1pm/t0.00/s0.25 | price2-3 str0 dv0 so:all tier:all age:young  | 34.96 | 118 | 3.39 | 1.31 | -26.0% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.25/s0.25 | price0-4 str0 dv0 so:all tier:all age:all  | 1084.70 | 15858 | 1.77 | 1.32 | -70.7% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 1075.08 | 15858 | 1.76 | 1.36 | -81.3% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.50/s0.25 | price0-4 str0 dv0 so:all tier:all age:all  | 1063.42 | 15857 | 1.75 | 1.31 | -70.7% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.50/s1.00 | price0-4 str0 dv0 so:all tier:all age:all  | 1054.26 | 15857 | 1.75 | 1.34 | -82.6% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.25/s0.25 | price0-4 str0 dv1 so:all tier:all age:all  | 1037.11 | 13560 | 1.85 | 1.30 | -70.7% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.50/s0.25 | price0-4 str0 dv1 so:all tier:all age:all  | 1026.08 | 13560 | 1.84 | 1.29 | -70.7% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.25/s1.00 | price0-4 str0 dv1 so:all tier:all age:all  | 1020.42 | 13560 | 1.84 | 1.34 | -81.3% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.25/s0.25 | price0-4 str0 dv0 so:all tier:all age:old  | 1019.86 | 13326 | 1.82 | 1.34 | -70.7% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.50/s1.00 | price0-4 str0 dv1 so:all tier:all age:all  | 1009.87 | 13560 | 1.83 | 1.32 | -82.6% |
| CRASH-long | 31,502 | c_1555 | d1pm/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:all age:old  | 1004.94 | 13326 | 1.81 | 1.37 | -81.3% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.25/s0.00 | price0-3 str1 dv0 so:u10 tier:nohot age:old  | 224.63 | 139 | 20.04 | 2.55 | -84.9% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.25/s1.00 | price0-3 str1 dv0 so:u10 tier:nohot age:old  | 224.63 | 139 | 20.04 | 1.96 | -104.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.50/s0.00 | price0-3 str1 dv0 so:u10 tier:nohot age:old  | 213.44 | 139 | 19.09 | 1.96 | -181.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.00/s0.00 | price0-3 str1 dv0 so:u10 tier:nohot age:old  | 213.44 | 139 | 19.09 | 2.09 | -181.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.00/s1.00 | price0-3 str1 dv0 so:u10 tier:nohot age:old  | 213.44 | 139 | 19.09 | 1.97 | -104.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.50/s1.00 | price0-3 str1 dv0 so:u10 tier:nohot age:old  | 213.44 | 139 | 19.09 | 1.85 | -104.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.25/s1.00 | price0-4 str1 dv0 so:u10 tier:nohot age:old  | 190.85 | 151 | 15.46 | 2.14 | -104.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.25/s0.00 | price0-4 str1 dv0 so:u10 tier:nohot age:old  | 190.85 | 151 | 15.46 | 2.77 | -84.9% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.50/s1.00 | price0-4 str1 dv0 so:u10 tier:nohot age:old  | 182.12 | 151 | 14.80 | 2.03 | -104.6% |
| GAPUP-short | 8,338 | o_hodf | d1m/t0.50/s0.00 | price0-4 str1 dv0 so:u10 tier:nohot age:old  | 182.12 | 151 | 14.80 | 2.15 | -181.6% |
| GAPUP-long | 8,338 | o_pm10 | d1pm/t0.25/s0.00 | price0-1 str0 dv0 so:known tier:nohot age:old  | 27.80 | 350 | 1.88 | 0.91 | -60.8% |
| GAPUP-long | 8,338 | o_pm10 | d1pm/t0.25/s0.00 | price0-1 str0 dv0 so:known tier:nohot age:all  | 26.30 | 398 | 1.73 | 0.90 | -60.8% |
| GAPUP-long | 8,338 | o_orb | d10c/t0.25/s0.25 | price1-4 str0 dv2 so:all tier:nohot age:old  | 25.87 | 1218 | 1.21 | 0.95 | -66.8% |
| GAPUP-long | 8,338 | o_vwap | d1pm/t0.25/s0.00 | price2-3 str0 dv1 so:o10 tier:nohot age:old  | 25.49 | 900 | 1.29 | 1.02 | -63.7% |
| GAPUP-long | 8,338 | o_vwap | d1pm/t0.25/s0.00 | price2-3 str0 dv0 so:o10 tier:nohot age:old  | 25.43 | 1049 | 1.24 | 0.99 | -63.9% |
| GAPUP-long | 8,338 | o_0931 | d1m/t0.00/s0.25 | price4-4 str2 dv1 so:known tier:all age:old  | 24.96 | 108 | 3.27 | 0.67 | -27.8% |
| GAPUP-long | 8,338 | o_vwap | d1pm/t0.25/s0.00 | price2-4 str0 dv1 so:o10 tier:nohot age:old  | 24.90 | 1300 | 1.20 | 1.01 | -63.7% |
| GAPUP-long | 8,338 | o_vwap | d1pm/t0.25/s1.00 | price2-4 str0 dv0 so:o10 tier:nohot age:old  | 24.83 | 1459 | 1.17 | 0.99 | -63.9% |
| GAPUP-long | 8,338 | o_vwap | d1pm/t0.25/s0.00 | price2-4 str0 dv2 so:o10 tier:nohot age:old  | 24.66 | 938 | 1.27 | 0.83 | -63.7% |
| GAPUP-long | 8,338 | o_pm10 | d1pm/t0.25/s0.00 | price0-1 str0 dv0 so:o10 tier:nohot age:all  | 24.28 | 298 | 1.77 | 1.20 | -60.8% |
| GAPDN-short | 9,776 | o_0945 | d2c/t0.50/s1.00 | price3-4 str0 dv3 so:all tier:all age:old  | 62.52 | 75 | 5.28 | 0.00 | -36.7% |
| GAPDN-short | 9,776 | o_0945 | d2c/t0.00/s1.00 | price3-4 str0 dv3 so:all tier:all age:old  | 60.85 | 75 | 5.17 | 0.00 | -36.7% |
| GAPDN-short | 9,776 | o_0945 | d2c/t0.50/s0.00 | price3-4 str0 dv3 so:all tier:nohot age:old  | 59.54 | 74 | 5.13 | 0.00 | -36.7% |
| GAPDN-short | 9,776 | o_0945 | d2c/t0.00/s1.00 | price3-4 str0 dv3 so:all tier:nohot age:all  | 57.89 | 74 | 5.02 | 0.00 | -36.7% |
| GAPDN-short | 9,776 | o_0931 | d2c/t0.50/s0.00 | price3-4 str0 dv3 so:all tier:all age:all  | 57.82 | 90 | 4.66 | 0.66 | -36.7% |
| GAPDN-short | 9,776 | o_0931 | d2c/t0.50/s0.00 | price3-4 str0 dv3 so:all tier:all age:old  | 57.04 | 88 | 4.66 | 0.40 | -36.7% |
| GAPDN-short | 9,776 | o_0931 | d2c/t0.00/s1.00 | price3-4 str0 dv3 so:all tier:all age:all  | 56.25 | 90 | 4.56 | 0.66 | -36.7% |
| GAPDN-short | 9,776 | o_0931 | d2c/t0.00/s0.00 | price3-4 str0 dv3 so:all tier:all age:old  | 55.50 | 88 | 4.56 | 0.40 | -36.7% |
| GAPDN-short | 9,776 | o_0931 | d2c/t0.50/s0.00 | price3-4 str0 dv3 so:all tier:nohot age:all  | 55.09 | 89 | 4.53 | 0.66 | -36.7% |
| GAPDN-short | 9,776 | o_0931 | d2c/t0.50/s1.00 | price3-4 str0 dv3 so:all tier:nohot age:old  | 54.34 | 87 | 4.53 | 0.40 | -36.7% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.25/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:all  | 295.48 | 4869 | 1.74 | 1.28 | -51.6% |
| GAPDN-long | 9,776 | o_1555 | d1pm/t0.25/s0.00 | price0-4 str0 dv1 so:all tier:nohot age:old  | 293.74 | 5202 | 1.55 | 0.67 | -53.7% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.50/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:all  | 291.99 | 4869 | 1.73 | 1.27 | -51.6% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.00/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:all  | 288.68 | 4869 | 1.72 | 1.25 | -51.6% |
| GAPDN-long | 9,776 | o_1555 | d1pm/t0.25/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:old  | 284.30 | 6164 | 1.46 | 0.72 | -53.7% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.50/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:old  | 282.88 | 4229 | 1.79 | 1.19 | -51.6% |
| GAPDN-long | 9,776 | o_1555 | d1pm/t0.50/s0.00 | price0-4 str0 dv1 so:all tier:nohot age:old  | 282.66 | 5202 | 1.53 | 0.69 | -53.7% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.25/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:old  | 281.67 | 4229 | 1.79 | 1.20 | -51.6% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.00/s0.00 | price0-4 str0 dv0 so:all tier:nohot age:old  | 279.57 | 4229 | 1.78 | 1.18 | -51.6% |
| GAPDN-long | 9,776 | o_ah0 | d1pm/t0.50/s0.00 | price1-4 str0 dv0 so:all tier:nohot age:all  | 277.44 | 4306 | 1.77 | 1.38 | -51.6% |
| RUN40-short | 13,240 | r_t0 | d2c/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 267.34 | 6734 | 1.39 | 1.10 | -1151.0% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 262.68 | 6735 | 1.39 | 1.16 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.50/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 260.96 | 6734 | 1.38 | 1.16 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.00/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 259.99 | 6733 | 1.38 | 1.16 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:nohot age:all  | 256.70 | 5008 | 1.48 | 1.04 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.25/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 246.39 | 5943 | 1.41 | 1.16 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.50/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 243.46 | 5942 | 1.41 | 1.16 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d1c/t0.00/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 242.52 | 5941 | 1.41 | 1.16 | -1003.8% |
| RUN40-short | 13,240 | r_t0 | d2c/t0.25/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 241.23 | 5942 | 1.40 | 1.10 | -1151.0% |
| RUN40-short | 13,240 | r_t0 | d2c/t0.50/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 239.93 | 6733 | 1.35 | 1.11 | -1151.0% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.25/s1.00 | price0-4 str0 dv2 so:all tier:all age:old  | 119.69 | 5593 | 1.25 | 1.13 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.50/s1.00 | price0-4 str0 dv2 so:all tier:all age:old  | 115.12 | 5593 | 1.24 | 1.10 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.25/s0.00 | price1-4 str0 dv2 so:all tier:all age:old  | 114.38 | 4949 | 1.26 | 1.10 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.50/s0.00 | price1-4 str0 dv2 so:all tier:all age:old  | 111.22 | 4949 | 1.25 | 1.06 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.00/s0.00 | price0-4 str0 dv2 so:all tier:all age:old  | 96.07 | 5593 | 1.20 | 1.08 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.25/s1.00 | price1-4 str0 dv2 so:known tier:all age:old  | 95.77 | 3585 | 1.32 | 1.10 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.25/s0.00 | price0-4 str0 dv2 so:known tier:all age:old  | 95.63 | 4040 | 1.28 | 1.14 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.25/s1.00 | price0-4 str0 dv2 so:all tier:all age:all  | 94.95 | 6610 | 1.16 | 1.15 | -63.1% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.25/s0.25 | price0-4 str0 dv2 so:all tier:all age:old  | 94.17 | 5593 | 1.19 | 1.09 | -29.9% |
| RUN40-long | 13,240 | r_ah0 | d1pm/t0.00/s0.00 | price1-4 str0 dv2 so:all tier:all age:old  | 93.87 | 4949 | 1.21 | 1.05 | -63.1% |
| RUN60-short | 6,175 | r_t0 | d3c/t0.25/s0.00 | price0-3 str0 dv2 so:u10 tier:all age:old  | 154.69 | 197 | 15.32 | 1.96 | -157.4% |
| RUN60-short | 6,175 | r_t0 | d2c/t0.50/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 144.35 | 2851 | 1.52 | 1.33 | -987.9% |
| RUN60-short | 6,175 | r_t0 | d3c/t0.25/s0.00 | price1-3 str0 dv2 so:u10 tier:all age:old  | 142.71 | 173 | 14.72 | 1.87 | -157.4% |
| RUN60-short | 6,175 | r_t0 | d2c/t0.00/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 140.63 | 2851 | 1.51 | 1.35 | -987.9% |
| RUN60-short | 6,175 | r_t0 | d1c/t0.25/s1.00 | price3-4 str0 dv2 so:all tier:all age:young  | 136.92 | 84 | 13.68 | 0.38 | -557.5% |
| RUN60-short | 6,175 | r_t0 | d1c/t0.25/s0.00 | price3-4 str0 dv2 so:all tier:all age:young  | 136.92 | 84 | 13.68 | 0.32 | -1003.8% |
| RUN60-short | 6,175 | r_t0 | d2c/t0.50/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 134.87 | 2594 | 1.54 | 1.32 | -987.9% |
| RUN60-short | 6,175 | r_t0 | d2c/t0.25/s0.00 | price0-4 str0 dv0 so:all tier:all age:all  | 134.82 | 2852 | 1.49 | 1.43 | -987.9% |
| RUN60-short | 6,175 | r_t0 | d2c/t0.25/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 131.01 | 2595 | 1.53 | 1.42 | -987.9% |
| RUN60-short | 6,175 | r_t0 | d2c/t0.00/s0.00 | price0-3 str0 dv0 so:all tier:all age:all  | 130.87 | 2594 | 1.53 | 1.33 | -987.9% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.00 | price0-2 str0 dv1 so:o10 tier:nohot age:old  | 52.04 | 647 | 1.81 | 0.86 | -72.9% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.25 | price0-2 str0 dv1 so:o10 tier:nohot age:old  | 50.56 | 647 | 1.79 | 0.91 | -29.9% |
| RUN60-long | 6,175 | r_1555 | d1m/t0.00/s0.25 | price0-1 str0 dv1 so:all tier:nohot age:old  | 49.03 | 702 | 1.74 | 0.71 | -30.3% |
| RUN60-long | 6,175 | r_1555 | d1m/t0.00/s0.25 | price0-2 str0 dv1 so:o10 tier:nohot age:old  | 48.20 | 677 | 1.70 | 0.86 | -30.3% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.00 | price0-2 str0 dv0 so:o10 tier:nohot age:old  | 48.19 | 878 | 1.57 | 0.95 | -72.9% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.00 | price0-3 str0 dv1 so:o10 tier:nohot age:old  | 47.74 | 771 | 1.63 | 0.80 | -72.9% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.00 | price0-4 str0 dv1 so:o10 tier:nohot age:old  | 46.94 | 825 | 1.57 | 0.80 | -72.9% |
| RUN60-long | 6,175 | r_1555 | d1m/t0.00/s0.25 | price0-1 str0 dv1 so:o10 tier:nohot age:old  | 46.83 | 366 | 2.25 | 0.90 | -30.3% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.25 | price0-1 str0 dv1 so:all tier:nohot age:old  | 46.37 | 667 | 1.76 | 0.83 | -29.9% |
| RUN60-long | 6,175 | r_ah0 | d1m/t0.00/s0.25 | price0-2 str0 dv0 so:o10 tier:nohot age:old  | 46.17 | 878 | 1.54 | 1.01 | -29.9% |
| RUN100-short | 2,384 | r_1555 | d2c/t0.25/s0.00 | price2-2 str0 dv2 so:all tier:all age:old  | 141.55 | 126 | 13.20 | 2.30 | -77.1% |
| RUN100-short | 2,384 | r_t0 | d10c/t0.25/s0.00 | price2-4 str0 dv1 so:all tier:all age:all  | 117.89 | 453 | 3.57 | 2.41 | -909.3% |
| RUN100-short | 2,384 | r_t0 | d10c/t0.25/s0.00 | price1-4 str0 dv1 so:all tier:all age:all  | 107.74 | 649 | 2.75 | 2.29 | -909.3% |
| RUN100-short | 2,384 | r_t15 | d10c/t0.25/s0.00 | price2-4 str0 dv1 so:all tier:all age:all  | 101.26 | 439 | 3.29 | 2.16 | -735.4% |
| RUN100-short | 2,384 | r_pm0 | d1pm/t0.50/s0.00 | price2-4 str0 dv1 so:o10 tier:hot age:all  | 100.90 | 121 | 10.01 | 0.84 | -355.0% |
| RUN100-short | 2,384 | r_pm0 | d1pm/t0.50/s1.00 | price2-4 str0 dv1 so:o10 tier:hot age:all  | 100.90 | 121 | 10.01 | 1.28 | -101.2% |
| RUN100-short | 2,384 | r_pm0 | d1pm/t0.00/s1.00 | price2-4 str0 dv1 so:o10 tier:hot age:all  | 100.90 | 121 | 10.01 | 1.26 | -101.2% |
| RUN100-short | 2,384 | r_pm0 | d1pm/t0.00/s0.00 | price2-4 str0 dv1 so:o10 tier:hot age:all  | 100.90 | 121 | 10.01 | 0.82 | -355.0% |
| RUN100-short | 2,384 | r_t0 | d10c/t0.25/s0.00 | price0-4 str0 dv1 so:all tier:all age:all  | 100.60 | 741 | 2.45 | 2.35 | -909.3% |
| RUN100-short | 2,384 | r_t0 | d5c/t0.25/s0.00 | price1-3 str0 dv1 so:all tier:nohot age:old  | 98.70 | 195 | 5.84 | 1.86 | -260.8% |
| RUN100-long | 2,384 | r_ah0 | d1o/t0.00/s0.00 | price0-4 str0 dv0 so:all tier:nohot age:old  | 33.56 | 598 | 1.68 | 0.79 | -64.8% |
| RUN100-long | 2,384 | r_ah0 | d1m/t0.00/s0.25 | price0-4 str0 dv0 so:all tier:nohot age:old  | 32.56 | 598 | 1.66 | 0.84 | -29.8% |
| RUN100-long | 2,384 | r_ah0 | d1m/t0.00/s1.00 | price0-4 str0 dv0 so:all tier:nohot age:old  | 32.47 | 598 | 1.66 | 0.84 | -72.9% |
| RUN100-long | 2,384 | r_ah0 | d1o/t0.00/s0.00 | price0-0 str0 dv0 so:all tier:nohot age:all  | 32.23 | 145 | 3.93 | 1.06 | -64.8% |
| RUN100-long | 2,384 | r_1555 | d1o/t0.00/s0.00 | price0-0 str0 dv0 so:all tier:nohot age:all  | 31.58 | 152 | 3.68 | 0.92 | -65.4% |
| RUN100-long | 2,384 | r_ah0 | d1m/t0.00/s0.25 | price0-0 str0 dv0 so:all tier:nohot age:all  | 31.38 | 145 | 3.85 | 0.97 | -29.8% |
| RUN100-long | 2,384 | r_1555 | d1o/t0.00/s0.25 | price0-0 str0 dv0 so:all tier:nohot age:all  | 31.00 | 152 | 3.63 | 0.99 | -28.2% |
| RUN100-long | 2,384 | r_ah0 | d1o/t0.00/s0.25 | price0-0 str0 dv0 so:all tier:nohot age:all  | 30.85 | 145 | 3.80 | 1.15 | -29.8% |
| RUN100-long | 2,384 | r_1555 | d1m/t0.00/s0.25 | price0-1 str0 dv1 so:all tier:nohot age:old  | 30.81 | 189 | 3.00 | 0.41 | -29.9% |
| RUN100-long | 2,384 | r_ah0 | d1o/t0.00/s0.00 | price0-4 str0 dv1 so:all tier:all age:old  | 30.46 | 1515 | 1.28 | 0.72 | -82.3% |
| RUN200-short | 642 | r_t15 | d5c/t0.00/s0.00 | price0-4 str0 dv1 so:known tier:all age:old  | 439.30 | 114 | 42.44 | 4.49 | -125.1% |
| RUN200-short | 642 | r_t15 | d5c/t0.50/s0.00 | price0-4 str0 dv1 so:known tier:all age:old  | 420.76 | 115 | 40.69 | 4.07 | -125.1% |
| RUN200-short | 642 | r_t15 | d5c/t0.00/s0.00 | price0-4 str0 dv1 so:known tier:all age:all  | 414.43 | 125 | 36.73 | 5.27 | -125.1% |
| RUN200-short | 642 | r_t15 | d5c/t0.50/s0.00 | price0-4 str0 dv1 so:known tier:all age:all  | 399.05 | 126 | 35.40 | 4.65 | -125.1% |
| RUN200-short | 642 | r_t15 | d5c/t0.00/s0.00 | price0-3 str0 dv1 so:known tier:all age:all  | 344.35 | 114 | 34.11 | 4.93 | -125.1% |
| RUN200-short | 642 | r_t15 | d5c/t0.50/s0.00 | price0-3 str0 dv1 so:known tier:all age:all  | 338.34 | 115 | 33.53 | 4.41 | -125.1% |
| RUN200-short | 642 | r_t0 | d5c/t0.50/s0.00 | price0-4 str0 dv1 so:known tier:all age:old  | 328.83 | 119 | 31.45 | 4.10 | -148.7% |
| RUN200-short | 642 | r_t0 | d5c/t0.00/s0.00 | price0-4 str0 dv1 so:known tier:all age:old  | 327.83 | 118 | 31.35 | 4.54 | -148.7% |
| RUN200-short | 642 | r_t15 | d5c/t0.25/s0.00 | price0-4 str0 dv1 so:known tier:all age:old  | 313.59 | 116 | 30.58 | 6.31 | -72.0% |
| RUN200-short | 642 | r_t15 | d5c/t0.25/s0.00 | price0-4 str0 dv1 so:known tier:all age:all  | 297.09 | 127 | 26.61 | 7.02 | -72.0% |
| RUN200-long | 642 | r_ah0 | d1o/t0.25/s1.00 | price0-4 str0 dv2 so:known tier:hot age:all  | 18.80 | 145 | 2.88 | 0.60 | -60.3% |
| RUN200-long | 642 | r_ah0 | d1o/t0.25/s0.00 | price0-4 str0 dv2 so:known tier:all age:all  | 18.61 | 171 | 2.60 | 0.68 | -60.3% |
| RUN200-long | 642 | r_ah0 | d1o/t0.00/s1.00 | price0-4 str0 dv2 so:known tier:all age:all  | 18.15 | 171 | 2.56 | 0.43 | -68.2% |
| RUN200-long | 642 | r_ah0 | d1o/t0.50/s0.00 | price0-4 str0 dv2 so:known tier:all age:old  | 18.11 | 159 | 2.68 | 0.67 | -62.1% |
| RUN200-long | 642 | r_ah0 | d1o/t0.50/s0.00 | price0-4 str0 dv2 so:known tier:all age:all  | 18.01 | 171 | 2.55 | 0.70 | -62.1% |
| RUN200-long | 642 | r_ah0 | d1o/t0.25/s1.00 | price0-4 str0 dv2 so:known tier:all age:old  | 17.74 | 159 | 2.64 | 0.69 | -60.3% |
| RUN200-long | 642 | r_ah0 | d1o/t0.25/s0.00 | price1-4 str0 dv2 so:known tier:all age:all  | 17.65 | 154 | 2.70 | 0.62 | -60.3% |
| RUN200-long | 642 | r_ah0 | d1o/t0.00/s0.00 | price0-4 str0 dv0 so:o10 tier:all age:old  | 17.39 | 236 | 1.90 | 0.63 | -74.4% |
| RUN200-long | 642 | r_ah0 | d1o/t0.00/s1.00 | price0-4 str0 dv2 so:known tier:all age:old  | 16.92 | 159 | 2.57 | 0.41 | -68.2% |
| RUN200-long | 642 | r_ah0 | d1o/t0.00/s1.00 | price0-4 str0 dv0 so:all tier:all age:old  | 16.44 | 532 | 1.43 | 0.60 | -82.3% |

## Where the edge is: each entry's best exit unfiltered (2018-2022)

| group | entry | best exit unfiltered | trades | PF 2018-22 | PF 2023+ | mean | best filtered score |
|---|---|---|---|---|---|---|---|
| RUNUP-short | c_1555 | d5c/t0.25/s0.00 | 423 | 1.87 | 1.25 | 6.6% | 95.44 |
| RUNUP-short | c_ah0 | d5c/t0.50/s0.00 | 348 | 1.95 | 1.16 | 9.0% | 118.71 |
| RUNUP-short | c_ah5 | d10c/t0.50/s0.00 | 196 | 2.48 | 2.07 | 16.0% | 155.12 |
| RUNUP-short | c_ah10 | d10c/t0.50/s0.00 | 114 | 2.77 | 2.70 | 17.3% | 82.68 |
| RUNUP-short | c_pm0 | d10c/t0.50/s0.00 | 386 | 2.42 | 2.06 | 12.2% | 114.14 |
| RUNUP-short | c_pm5 | d10c/t0.50/s0.00 | 289 | 2.70 | 2.47 | 14.8% | 119.09 |
| RUNUP-short | c_pm10 | d10c/t0.50/s0.00 | 218 | 2.81 | 2.52 | 16.2% | 101.96 |
| RUNUP-short | c_pm20 | d10c/t0.50/s0.00 | 127 | 2.61 | 3.53 | 17.1% | 51.06 |
| RUNUP-short | c_open | d10c/t0.25/s0.00 | 595 | 1.85 | 1.72 | 6.7% | 124.45 |
| RUNUP-short | c_0945 | d5c/t0.00/s0.00 | 297 | 2.16 | 1.50 | 8.8% | 81.04 |
| RUNUP-short | c_1030 | d5c/t0.00/s0.00 | 254 | 2.46 | 1.45 | 9.1% | 85.52 |
| RUNUP-short | c_1200 | d5c/t0.50/s0.00 | 230 | 2.42 | 1.42 | 8.4% | 78.52 |
| RUNUP-short | c_1555b | d5c/t0.50/s0.00 | 197 | 2.60 | 1.22 | 7.9% | 91.67 |
| RUNUP-short | c_rl5 | d10c/t0.50/s0.00 | 231 | 3.03 | 2.05 | 14.7% | 95.78 |
| RUNUP-short | c_rl10 | d10c/t0.50/s0.00 | 192 | 3.22 | 2.16 | 15.9% | 91.10 |
| RUNUP-short | c_rl20 | d10c/t0.50/s0.00 | 133 | 3.82 | 2.30 | 19.3% | 96.64 |
| RUNUP-short | c_orb | d10c/t0.50/s0.00 | 234 | 2.55 | 1.74 | 10.4% | 105.43 |
| RUNUP-short | c_vwap | d5c/t0.00/s0.00 | 280 | 2.14 | 1.49 | 8.4% | 76.36 |
| RUNUP-short | c_hodf | d10c/t0.00/s0.00 | 92 | 3.79 | 2.22 | 21.1% | 69.00 |
| RUNUP-long | c_ah5 | d1o/t0.00/s0.00 | 746 | 1.24 | 0.89 | 1.7% | 39.45 |
| RUNUP-long | c_pm20 | d3c/t0.25/s0.00 | 249 | 1.14 | 0.99 | 1.8% | 26.20 |
| RUNUP-long | c_rl20 | d10c/t0.25/s0.00 | 578 | 1.12 | 0.89 | 1.6% | 17.81 |
| STRONG-short | c_ah0 | d2c/t0.25/s0.00 | 2118 | 1.16 | 0.88 | 1.2% | 71.95 |
| STRONG-short | c_ah5 | d2c/t0.25/s0.00 | 887 | 1.56 | 1.07 | 4.5% | 135.17 |
| STRONG-short | c_ah10 | d10c/t0.25/s0.00 | 455 | 1.84 | 1.70 | 7.9% | 360.97 |
| STRONG-short | c_pm0 | d1c/t0.25/s0.00 | 2230 | 1.24 | 1.07 | 1.8% | 107.27 |
| STRONG-short | c_pm5 | d5c/t0.25/s0.00 | 1351 | 1.39 | 1.07 | 3.8% | 106.61 |
| STRONG-short | c_pm10 | d5c/t0.25/s0.00 | 935 | 1.71 | 1.19 | 6.5% | 133.55 |
| STRONG-short | c_pm20 | d5c/t0.25/s0.00 | 525 | 2.22 | 1.71 | 9.8% | 128.55 |
| STRONG-short | c_rl5 | d1m/t0.50/s0.00 | 1417 | 1.31 | 0.98 | 2.0% | 105.46 |
| STRONG-short | c_rl10 | d5c/t0.25/s0.00 | 1080 | 1.52 | 0.97 | 4.5% | 128.94 |
| STRONG-short | c_rl20 | d5c/t0.25/s0.00 | 641 | 1.91 | 1.11 | 7.4% | 116.67 |
| STRONG-short | c_hodf | d5c/t0.25/s0.00 | 336 | 1.81 | 1.19 | 7.2% | 54.42 |
| STRONG-long | c_ah5 | d1o/t0.00/s0.00 | 1831 | 1.11 | 0.96 | 0.7% | 59.82 |
| STRONG-long | c_rl20 | d1pm/t0.25/s0.00 | 1073 | 1.18 | 1.00 | 1.0% | 55.23 |
| FADE-short | c_1555 | d1m/t0.50/s1.00 | 376 | 1.88 | 0.83 | 2.2% | 69.15 |
| FADE-short | c_ah0 | d1m/t0.50/s0.00 | 289 | 2.11 | 1.04 | 2.6% | 70.87 |
| FADE-short | c_ah5 | d2c/t0.25/s0.00 | 65 | 2.04 | 1.17 | 4.7% | 13.50 |
| FADE-short | c_pm0 | d1pm/t0.00/s1.00 | 324 | 2.17 | 1.04 | 4.1% | 105.18 |
| FADE-short | c_pm5 | d0c/t0.25/s1.00 | 169 | 2.70 | 0.95 | 5.1% | 57.43 |
| FADE-short | c_pm10 | d0c/t0.25/s1.00 | 96 | 3.22 | 0.87 | 7.3% | 42.60 |
| FADE-short | c_rl5 | d1pm/t0.00/s0.25 | 146 | 1.24 | 0.68 | 1.0% | 13.39 |
| FADE-short | c_rl10 | d0c/t0.00/s0.25 | 83 | 1.27 | 0.54 | 1.1% | 4.45 |
| FADE-long | c_rl20 | d10c/t0.25/s0.00 | 159 | 1.18 | 0.68 | 2.0% | 18.05 |
| CRASH-long | c_1555 | d1pm/t0.25/s0.25 | 7050 | 1.77 | 1.32 | 1.7% | 1084.70 |
| CRASH-long | c_ah0 | d1pm/t0.25/s0.25 | 3827 | 2.16 | 1.61 | 2.7% | 886.89 |
| CRASH-long | c_ah5 | d1pm/t0.25/s0.25 | 720 | 2.10 | 1.51 | 3.5% | 158.10 |
| CRASH-long | c_ah10 | d1pm/t0.25/s0.25 | 190 | 2.28 | 1.56 | 5.7% | 48.86 |
| CRASH-long | c_pm5 | d5c/t0.25/s0.00 | 1657 | 1.25 | 0.98 | 2.4% | 109.31 |
| CRASH-long | c_pm10 | d5c/t0.50/s0.00 | 728 | 1.32 | 1.03 | 4.0% | 48.18 |
| CRASH-long | c_pm20 | d5c/t0.50/s0.00 | 197 | 1.21 | 0.72 | 3.5% | 16.55 |
| CRASH-long | c_0945 | d5c/t0.00/s0.00 | 7179 | 1.22 | 0.59 | 2.2% | 491.00 |
| CRASH-long | c_1030 | d5c/t0.50/s0.00 | 7179 | 1.18 | 0.81 | 1.7% | 299.80 |
| CRASH-long | c_1200 | d5c/t0.50/s0.00 | 7179 | 1.18 | 0.80 | 1.6% | 324.67 |
| CRASH-long | c_1555b | d5c/t0.50/s0.00 | 7115 | 1.12 | 0.81 | 1.1% | 217.45 |
| CRASH-long | c_rl5 | d10c/t0.50/s0.00 | 4004 | 1.28 | 0.82 | 3.4% | 261.18 |
| CRASH-long | c_rl10 | d10c/t0.50/s0.00 | 2410 | 1.34 | 0.79 | 4.4% | 176.62 |
| CRASH-long | c_rl20 | d10c/t0.50/s0.00 | 761 | 1.48 | 0.79 | 7.0% | 124.34 |
| CRASH-long | c_orb | d5c/t0.00/s0.00 | 4314 | 1.49 | 0.62 | 4.5% | 598.31 |
| CRASH-long | c_vwap | d5c/t0.50/s0.00 | 6715 | 1.27 | 0.83 | 2.6% | 414.65 |
| CRASH-long | c_hodf | d5c/t0.50/s0.00 | 568 | 1.67 | 0.80 | 8.1% | 95.07 |
| GAPUP-short | o_0931 | d1c/t0.50/s0.00 | 2335 | 1.20 | 1.06 | 1.6% | 115.29 |
| GAPUP-short | o_0945 | d1c/t0.00/s0.00 | 2332 | 1.17 | 1.06 | 1.2% | 108.42 |
| GAPUP-short | o_orb | d1m/t0.50/s1.00 | 1852 | 1.22 | 0.88 | 1.3% | 94.63 |
| GAPUP-short | o_hodf | d3c/t0.50/s0.00 | 1563 | 1.33 | 1.08 | 3.1% | 115.69 |
| GAPUP-short | o_ah0 | d1m/t0.25/s1.00 | 1724 | 1.23 | 0.85 | 0.9% | 103.18 |
| GAPUP-short | o_ah10 | d5c/t0.25/s0.00 | 211 | 2.22 | 1.44 | 9.0% | 87.94 |
| GAPUP-short | o_pm0 | d0c/t0.50/s0.00 | 1857 | 1.41 | 1.03 | 1.8% | 150.50 |
| GAPUP-short | o_pm10 | d5c/t0.25/s0.00 | 566 | 1.40 | 1.19 | 4.0% | 54.16 |
| GAPDN-short | o_0931 | d2c/t0.50/s1.00 | 340 | 1.16 | 0.30 | 1.4% | 57.82 |
| GAPDN-short | o_0945 | d2c/t0.50/s1.00 | 282 | 1.32 | 0.16 | 2.7% | 62.52 |
| GAPDN-long | o_1555 | d1pm/t0.25/s0.00 | 4485 | 1.22 | 0.90 | 0.5% | 293.74 |
| GAPDN-long | o_ah0 | d1pm/t0.25/s0.00 | 2865 | 1.45 | 1.35 | 1.0% | 295.48 |
| GAPDN-long | o_ah10 | d1o/t0.50/s0.00 | 159 | 3.13 | 1.45 | 7.8% | 82.37 |
| GAPDN-long | o_pm10 | d1c/t0.25/s0.00 | 503 | 1.52 | 1.36 | 3.6% | 52.12 |
| RUN40-short | r_t0 | d2c/t0.25/s0.00 | 3400 | 1.39 | 1.10 | 3.4% | 267.34 |
| RUN40-short | r_t15 | d2c/t0.25/s0.00 | 3316 | 1.26 | 0.96 | 2.2% | 169.60 |
| RUN40-short | r_t60 | d3c/t0.25/s0.00 | 3085 | 1.11 | 0.80 | 1.0% | 82.82 |
| RUN40-short | r_hodf | d3c/t0.25/s0.00 | 2897 | 1.28 | 1.01 | 2.7% | 162.80 |
| RUN40-short | r_ah0 | d2c/t0.25/s0.00 | 2730 | 1.21 | 0.88 | 1.4% | 114.91 |
| RUN40-short | r_pm0 | d0c/t0.50/s0.00 | 2988 | 1.34 | 1.04 | 1.8% | 201.83 |
| RUN60-short | r_t0 | d2c/t0.50/s0.00 | 1383 | 1.52 | 1.33 | 5.5% | 144.35 |
| RUN60-short | r_t15 | d2c/t0.25/s0.00 | 1346 | 1.46 | 1.17 | 4.2% | 123.50 |
| RUN60-short | r_t60 | d2c/t0.25/s0.00 | 1254 | 1.34 | 1.00 | 3.1% | 87.83 |
| RUN60-short | r_hodf | d2c/t0.25/s0.00 | 1260 | 1.46 | 1.34 | 4.5% | 116.87 |
| RUN60-short | r_1555 | d2c/t0.25/s0.00 | 1335 | 1.25 | 0.91 | 1.9% | 65.99 |
| RUN60-short | r_ah0 | d2c/t0.25/s0.00 | 1135 | 1.26 | 0.97 | 2.2% | 68.06 |
| RUN60-short | r_pm0 | d5c/t0.25/s0.00 | 1187 | 1.34 | 1.04 | 3.3% | 81.80 |
| RUN100-short | r_t0 | d10c/t0.25/s0.00 | 470 | 1.83 | 2.63 | 8.3% | 117.89 |
| RUN100-short | r_t15 | d10c/t0.25/s0.00 | 452 | 1.64 | 2.28 | 6.9% | 101.26 |
| RUN100-short | r_t60 | d10c/t0.25/s0.00 | 412 | 1.66 | 2.05 | 6.9% | 63.39 |
| RUN100-short | r_hodf | d10c/t0.25/s0.00 | 433 | 1.59 | 3.09 | 6.9% | 78.84 |
| RUN100-short | r_1555 | d10c/t0.25/s0.00 | 448 | 1.44 | 1.50 | 4.5% | 48.79 |
| RUN100-short | r_ah0 | d2c/t0.25/s0.00 | 400 | 1.34 | 1.20 | 3.1% | 62.20 |
| RUN100-short | r_pm0 | d10c/t0.25/s0.00 | 369 | 1.79 | 1.60 | 6.8% | 58.63 |
| RUN100-short | r_open1 | d10c/t0.25/s0.00 | 581 | 1.41 | 1.52 | 4.0% | 55.83 |
| RUN200-short | r_t0 | d10c/t0.25/s0.00 | 121 | 4.57 | 5.94 | 16.3% | 152.71 |
| RUN200-short | r_t15 | d10c/t0.25/s0.00 | 119 | 4.90 | 7.03 | 16.5% | 125.07 |
| RUN200-short | r_t60 | d10c/t0.25/s0.00 | 111 | 5.03 | 4.54 | 16.4% | 108.15 |
| RUN200-short | r_hodf | d10c/t0.25/s0.00 | 117 | 6.92 | 6.13 | 18.4% | 138.44 |
| RUN200-short | r_1555 | d5c/t0.25/s0.00 | 116 | 2.94 | 2.52 | 11.0% | 170.62 |
| RUN200-short | r_ah0 | d5c/t0.25/s0.00 | 105 | 2.04 | 3.32 | 8.5% | 157.04 |
| RUN200-short | r_pm0 | d5c/t0.00/s0.00 | 82 | 3.56 | 1.98 | 15.9% | 61.04 |
| RUN200-short | r_open1 | d10c/t0.25/s0.00 | 134 | 2.26 | 4.25 | 9.3% | 103.32 |
| RUN200-long | r_1555 | d1m/t0.00/s0.25 | 227 | 1.20 | 0.62 | 2.4% | 9.63 |
| RUN200-long | r_ah0 | d1m/t0.00/s0.25 | 226 | 1.32 | 0.70 | 3.6% | 15.14 |

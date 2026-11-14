# v60 results: night-short gap filter x NS size, chosen on 2018-2022

Run 43590067498 (2026-11-14), pre-registered in V60_PREREGISTRATION.md. 20 books, DS1 0.20, RU 0.25, N5.

- Check: Gnone-NS0.60 in W0 gave $13,041 and 1.0% ruin: reproduced.
- **NOT IMPROVED**: every world chooses the control Gnone-NS0.60. The bot keeps the current book.
- Raising NS above 0.60 crosses a cliff on 2018-2022: ruin 0.4-0.9% at 0.60, 8.8-10.7% at 0.80 and above, for
  every gap filter up to 100%. G150 stays at 0.0% there, so the cliff comes from NS trades with gaps between 100%
  and 150% in those years (inferred from the table, trades not inspected).
- In hindsight G75-NS0.80 has the best 2023-2026 in F0C1 ($11,988 / 1.2% vs the control's $10,383 / 1.4%), but
  its 2018-2022 ruin of 9.1% rules it out under the pre-registered rule; picking it now would be overfitting.

F0C1 (central world), median / ruin:

| book | 2018-2022 | 2023-2026 | all years |
|---|---|---|---|
| Gnone-NS0.60 (control) | $12,547 / 0.9% | $10,383 / 1.4% | $11,634 / 1.1% |
| Gnone-NS0.80 | $13,463 / 8.9% | $11,397 / 2.0% | $12,643 / 6.3% |
| G75-NS0.80 | $11,810 / 9.1% | $11,988 / 1.2% | $11,948 / 5.9% |
| G100-NS1.00 | $11,785 / 10.6% | $11,257 / 1.7% | $11,624 / 7.0% |
| G150-NS1.00 | $11,617 / 0.0% | $9,269 / 1.5% | $10,612 / 0.6% |

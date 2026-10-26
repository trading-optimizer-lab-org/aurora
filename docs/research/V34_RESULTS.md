# v34 results: bigger positions with limit entries do not pass

Pre-registered in [V34_PREREGISTRATION.md](V34_PREREGISTRATION.md). Run 40219224330 (canary 40199723993), all jobs
succeeded. Data: `data/v34_summary.json`.

| members, size | median | 2023+ paths | HOT 5% | spreads x2 | ruin | -50% |
|---|---|---|---|---|---|---|
| A1, 20% | $12,831 | $20,528 | $9,000 | $10,221 | 0.5% | 10.1% |
| limit, 20% | $12,777 | $14,335 | $9,589 | $10,620 | 0.1% | 4.5% |
| limit, 25% | $14,804 | $18,247 | $10,613 | $11,985 | 4.9% | 12.7% |
| limit, 30% | $17,409 | $20,492 | $11,871 | $13,608 | 2.1% | 12.6% |
| limit, 40% | $13,387 | $8,472 | $7,833 | $9,425 | 18.3% | 34.4% |

- **No size passes.** Limit at 25% and 30% beat A1's median at the base costs, HOT 5% and spreads x2, but not on
  2023+ paths ($20,492 against $20,528 at 30%) and their ruin is above 1% (4.9%, 2.1%).
- Limit at 30% has the highest median of all books tested ($17,409), with ruin 2.1%: it breaks the owner's 1% rule.
- A1's members at 25-40% are worse at every size (ruin 18.7-30.3%).

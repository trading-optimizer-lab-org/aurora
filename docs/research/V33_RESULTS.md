# v33 results: no change to the FREE members raises A1's median

Pre-registered in [V33_PREREGISTRATION.md](V33_PREREGISTRATION.md). Runs: 40192951586 (re-pick grid, 25,410
configurations, 0 errors; picks; variants; arm members), its arms stage failed on v31's liquidation model reading a
limit fill's entry as the open; fixed and rerun on that run's members in 40196710344 (a second case: a limit fill
after a gap down, v31 added a short-sale-restriction cost the trade does not pay) and 40197390343 (all jobs
succeeded; the report). Canary 40190592325. Data: `data/v33_summary.json`.

## Summary

A1 reproduces ($12,831). One year from $5,000, A1's account, v31's liquidation at 15%:

| arm | median | 2018-22 paths | 2023+ paths | HOT 5% | spreads x2 | ruin | -50% | p10 | worst 5% mean |
|---|---|---|---|---|---|---|---|---|---|
| A1 | $12,831 | $9,022 | $20,528 | $9,000 | $10,221 | 0.5% | 10.1% | $4,482 | $2,569 |
| repick | $10,914 | $8,620 | $16,111 | $7,870 | $8,782 | 3.1% | 15.6% | $3,560 | $1,825 |
| limit | $12,777 | $11,585 | $14,335 | $9,589 | $10,620 | 0.1% | 4.5% | $5,817 | $3,501 |
| exit | $12,831 | $9,022 | $20,528 | $9,000 | $10,221 | 0.5% | 10.1% | $4,482 | $2,569 |
| nohot | $12,831 | $9,022 | $20,528 | $9,000 | $10,221 | 0.5% | 10.1% | $4,482 | $2,569 |
| no_night | $10,064 | $7,347 | $16,025 | $8,318 | $8,880 | 0.3% | 9.0% | $4,296 | $2,738 |
| all | $10,857 | $10,172 | $12,329 | $8,197 | $9,038 | 3.4% | 15.6% | $3,560 | $1,789 |

- **No arm passes** (each must beat A1's median at the base costs, on 2023+ paths, at HOT 5% and at spreads x2, with
  ruin at most 1%). v33's choice: none.
- **Re-picking under the account's costs lowers the median and raises ruin** ($10,914, ruin 3.1%). Its picks move
  ON1 and NS to ATR stops and two-session holds with days-to-cover filters; DS1 keeps ten sessions with no stop.
- **Limit entries keep the median and cut the tail**: $12,777 against $12,831, ruin 0.1% against 0.5%, -50% 4.5%
  against 10.1%, p10 $5,817 against $4,482, better at HOT 5%, spreads x2 and the high costs ($6,215 against
  $4,759). It loses on 2023+ paths ($14,335 against $20,528) and wins on 2018-2022 ($11,585 against $9,022). Chosen
  for DS1 and RU in some years (limits of 5-20% over the previous close).
- **The emergency exit and the HOT skip change nothing**: the exit was chosen for RU in four years and never fired
  in a taken trade at these levels (identical results); the HOT skip was never chosen.
- **The night shorts earn their tail**: without ON1 and NS the median falls to $10,064 (ruin 0.3%).

## Caveats

v29's, v31's and v32's caveats hold. Limit fills on daily bars need the high 1% through the limit; the order of the
fill and the high is unknown. The grid and the four changes were designed after seeing v28-v32.

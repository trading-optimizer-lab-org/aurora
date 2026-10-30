# v49 results

Run 41105727077 (5 book jobs, success). Its final job failed to download the run artifacts (failed after 5 retries)
and the re-run ended in startup_failure, so the report was built from the same artifacts by `v49f.yml`, run
41117083804. No backtest was repeated. Pre-registration: `V49_PREREGISTRATION.md`.

## Verdict

- Check: RU 0.30 under TZA reproduces v48b ($14,411, 1.0%).
- Answer by the pre-registered rule: **DS0.20 / NS0.40 / RU0.20 / N5 under TZC**. The one-year median from $5,000 is
  **$8,498** and ruin is **0.0%**, the ensemble mean of 31 seeds, base costs, all paths. Source: the table below,
  run 41117083804.
- Under TZC, books RU 0.40, 0.30 and 0.25 fail the 2.5% ruin bar: 15.0%, 10.5% and 7.1%. v48b's RU 0.30 is not
  safe once real costs and broker rules count.
- Borrow doubled (B2) costs about $1,000 of median and does not change the choice. Margin interest is worth about
  $60 (M0).
- The v48b figure of $14.4k drops to $8.5k. That sits under the reviewer's estimated range of $9-12k.

## Caveats

- Borrow rates are model rates, not TradeZero quotes. Recalls and buy-ins are not modelled.
- Every year 2018-2026 has been seen. TZC's margin interest is charged on every short, which is conservative.
- Locate failure rates of 50% (HOT) and 10% (HTB) are assumptions, not TradeZero data.

## Report (verbatim from run 41117083804)

# v49: the RU size dial with TradeZero's real borrow costs and broker rules

31 seeds, 4000 one-year paths from $5,000, ruin at or under $1,250. TZC = TZA plus borrow by calendar day, 9% margin interest, failed locates (HOT 50%, HTB 10%), the 2:1 rule at 15:45 enforced, close entries capped at 10% of 15:55-15:59 volume. M0 = no margin interest; B2 = borrow doubled.

Check (RU 0.30 under TZA vs v48b $14,411, 1.0%): **reproduced**.

## Answer: **DS0.20-NS0.40-RU0.20-N5**

TZC, base costs, all paths, ensemble mean of 31 seeds: one-year median from $5,000 **$8,498**, ruin **0.0%** (p90 over seeds 0.0%).

| book | set | ens median | ens ruin | p90 ruin | seed 0 | 2018-22 | 2023+ | HOT 5% |
|---|---|---|---|---|---|---|---|---|
| DS0.20-NS0.40-RU0.40-N5 | TZA | $15,201 | 7.1% | 15.6% | $16,823 / 6.0% | $18,210 / 0.6% | $11,392 / 17.0% | $14,653 / 7.3% |
| DS0.20-NS0.40-RU0.40-N5 | TZC | $8,536 | 15.0% | 22.8% | $9,071 / 13.0% | $11,073 / 1.3% | $4,918 / 33.4% | $8,345 / 15.1% |
| DS0.20-NS0.40-RU0.40-N5 | TZC-M0 | $8,604 | 14.8% | 22.8% | $9,150 / 12.8% | $11,138 / 1.3% | $4,983 / 33.2% | $8,409 / 15.0% |
| DS0.20-NS0.40-RU0.40-N5 | TZC-B2 | $7,432 | 15.7% | 22.6% | $7,836 / 14.8% | $10,135 / 1.4% | $3,837 / 35.5% | $7,268 / 15.9% |
| DS0.20-NS0.40-RU0.30-N5 | TZA | $14,411 | 1.0% | 2.5% | $15,689 / 0.1% | $16,221 / 0.7% | $12,039 / 1.6% | $13,917 / 1.0% |
| DS0.20-NS0.40-RU0.30-N5 | TZC | $8,365 | 10.5% | 10.8% | $8,781 / 10.6% | $10,173 / 1.0% | $6,044 / 22.7% | $8,187 / 10.6% |
| DS0.20-NS0.40-RU0.30-N5 | TZC-M0 | $8,431 | 10.5% | 10.8% | $8,861 / 10.6% | $10,227 / 1.0% | $6,110 / 22.7% | $8,247 / 10.5% |
| DS0.20-NS0.40-RU0.30-N5 | TZC-B2 | $7,313 | 10.9% | 11.1% | $7,620 / 10.8% | $9,363 / 1.1% | $4,822 / 23.7% | $7,157 / 10.9% |
| DS0.20-NS0.40-RU0.25-N5 | TZA | $13,929 | 0.4% | 0.1% | $15,113 / 0.1% | $15,481 / 0.1% | $11,915 / 1.0% | $13,464 / 0.5% |
| DS0.20-NS0.40-RU0.25-N5 | TZC | $8,204 | 7.1% | 8.1% | $8,613 / 7.5% | $9,777 / 0.0% | $6,181 / 18.9% | $8,032 / 7.3% |
| DS0.20-NS0.40-RU0.25-N5 | TZC-M0 | $8,262 | 7.1% | 8.0% | $8,679 / 7.5% | $9,829 / 0.0% | $6,246 / 18.7% | $8,090 / 7.2% |
| DS0.20-NS0.40-RU0.25-N5 | TZC-B2 | $7,202 | 8.0% | 9.0% | $7,496 / 8.5% | $9,029 / 0.1% | $4,986 / 20.7% | $7,051 / 8.1% |
| DS0.20-NS0.40-RU0.20-N5 | TZA | $13,385 | 0.0% | 0.1% | $14,506 / 0.0% | $14,624 / 0.1% | $11,848 / 0.0% | $12,945 / 0.0% |
| DS0.20-NS0.40-RU0.20-N5 | TZC | $8,498 | 0.0% | 0.0% | $8,923 / 0.0% | $9,373 / 0.0% | $7,351 / 0.0% | $8,332 / 0.0% |
| DS0.20-NS0.40-RU0.20-N5 | TZC-M0 | $8,556 | 0.0% | 0.0% | $8,985 / 0.0% | $9,421 / 0.0% | $7,421 / 0.0% | $8,389 / 0.0% |
| DS0.20-NS0.40-RU0.20-N5 | TZC-B2 | $7,519 | 0.0% | 0.0% | $7,843 / 0.0% | $8,685 / 0.0% | $6,102 / 0.1% | $7,370 / 0.0% |
| DS0.20-NS0.40-RU0.15-N5 | TZA | $12,763 | 0.0% | 0.1% | $13,780 / 0.0% | $13,777 / 0.1% | $11,598 / 0.0% | $12,356 / 0.0% |
| DS0.20-NS0.40-RU0.15-N5 | TZC | $8,275 | 0.0% | 0.0% | $8,694 / 0.0% | $8,959 / 0.0% | $7,332 / 0.0% | $8,117 / 0.0% |
| DS0.20-NS0.40-RU0.15-N5 | TZC-M0 | $8,329 | 0.0% | 0.0% | $8,757 / 0.0% | $9,002 / 0.0% | $7,398 / 0.0% | $8,171 / 0.0% |
| DS0.20-NS0.40-RU0.15-N5 | TZC-B2 | $7,357 | 0.0% | 0.0% | $7,653 / 0.0% | $8,332 / 0.0% | $6,131 / 0.1% | $7,211 / 0.0% |

Counts at $10,000, base costs, all sets together (forced 2:1 covers, failed locates, capped entries):

- DS0.20-NS0.40-RU0.15-N5: {'fills_cut_by_cap': 55, 'no_bars_session': 6, 'v49_no_locate': 981, 'v49_capped': 12}
- DS0.20-NS0.40-RU0.20-N5: {'fills_cut_by_cap': 55, 'no_bars_session': 6, 'v49_no_locate': 981, 'v49_capped': 12}
- DS0.20-NS0.40-RU0.25-N5: {'fills_cut_by_cap': 56, 'no_bars_session': 6, 'v49_no_locate': 981, 'v49_capped': 12, 'v49_forced_2to1': 9}
- DS0.20-NS0.40-RU0.30-N5: {'fills_cut_by_cap': 56, 'no_bars_session': 6, 'liquidations': 12, 'v49_no_locate': 981, 'v49_capped': 12}
- DS0.20-NS0.40-RU0.40-N5: {'fills_cut_by_cap': 59, 'no_bars_session': 6, 'liquidations': 24, 'v49_no_locate': 981, 'v49_capped': 12}

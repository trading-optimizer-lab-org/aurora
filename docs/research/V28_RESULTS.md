# v28 results: the small-cap megarun (466,074 configurations)

Pre-registered in [V28_PREREGISTRATION.md](V28_PREREGISTRATION.md); ideas list in
[SMALLCAP_PENDIENTE_ES.md](SMALLCAP_PENDIENTE_ES.md). Data: `data/v28_summary.json` (report),
`data/v28_after_summary.json` (after stages).

| run | GitHub run | what happened |
|---|---|---|
| v28 data | 39822387972 | SEC forms and full-text hits, XBRL facts, FTD, Reg SHO lists, FINRA short interest (2018+), VIX, gap-day premarket store |
| v28 build | 39825946914 | inputs with the fixed cash runway (cache `v28-inputs2-*`) |
| v28 main | 39830929424 | canary, 300 real shards (about 3 h) and the selection passed; placebo jobs skipped (default job condition after a skipped retry job, as in v26) |
| **v28 resume** | **39915126980** (2026-10-23) | that run's selection, then 500 placebos per pick and the report; 161 of 300 placebo shards first failed on a GitHub cache egress limit and passed on the automatic retry |
| **v28 after** | **39915381881** | one account under TradeZero margin, construction, battery, worst trades, symbol halves |
| v28 after canary | 39915381849 | passed on its second attempt (the first hit the same egress limit) |

466,074 of 466,074 configurations, no errors.

## Summary

- **The pre-registered criterion is met, but v28 adds almost nothing to v26.** `COMBO28`: walk-forward monthly
  Sortino **5.54** (15.28 in 2018-2020, 4.35 in 2021+), 13.2%/yr, max DD -4.5%, 2023-07+ 3.98, CPCV PBO 0%, DSR 0.00.
  COMBO26 was 5.58 (14.04/4.21), 13.2%/yr, DD -5.2%, 2023-07+ 3.75. Every year positive (+5.6% to +26.3%).
- **Block B (v26 entries, shield 2)**: all 23 families pass the gate again and most improve on v26, mainly from the
  d10 hold and the 50% profit target: DS1 2.84 -> 5.14, RU 2.72 -> 5.63, MP 2.77 -> 4.34, PS 4.14 -> 4.70,
  IV 4.74 -> 5.01, OR 4.42 -> 4.68. Of the 30 new filters only days to cover >= 3/5 is picked (EM, OS, MD, SQ, IS)
  and VIX < 15 once (XS2); FTD, Reg SHO, short interest, runway, going concern, dilution, mania, regimes, weekday,
  earnings and the squeeze model are not picked in 2026. Better families do not lift the combo: they are the same
  correlated members.
- **Block C (new shorts)**: every event family fails (EFFECT, PIPE, NT, GC, RENAME, S4, EARN, LOCKUP, SYMPATHY;
  Sortino -2.6 to -0.2). Premarket entries pass the gate (1.14) but only in 2018-2020 (7.26; 2021+ -0.09; SPA p 0.09);
  after-hours entries fail.
- **Block D (longs, books)**: PDUFA run-up passes (2.63, 2021+ 1.28, both symbol halves ~1.6; SPA p 0.12, so weak).
  Buyback, mania basket (DD -99.7%), factor books and leveraged ETF pairs fail.
- **Missing families**: CRYPTO, DESPAC, IPO and JANUARY never had an eligible configuration under run_v22's activity
  rule (50 trades and a trade in 40% of the earlier months). JANUARY can never meet it (one month a year), a flaw of
  the pre-registration; the three event families are too sparse (inferred from their event counts, not checked one
  by one).
- **Report gaps**: sections 4 (trades per family) and 5 (choice medians) of REPORT.md are empty in v28; the combo and
  gate are unaffected, and the worst trades are in the after report.

## One account (after report)

The owner's rule (p75 <= 1%, gross <= 2x, highest median bootstrap CAGR) under TradeZero International's margin and a
0.5% locate cost a short, middle costs, $100k:

| book | risk | cap | gross | max open | new/day | Sortino | CAGR | max DD | worst day | p75 |
|---|---|---|---|---|---|---|---|---|---|---|
| A28 | 1.5% | 40% | 2x | 10 | 5 | 5.71 | 234.7% | -51.4% | -48.7% | 1.0% |
| A26 | 1.0% | 20% | 2x | 20 | 3 | 2.87 | 58.8% | -40.5% | -26.2% | 0.0% |

Battery for A28 (CAGR / max DD / p75):

| change | result |
|---|---|
| margin none / TZ US | 223.7% / -51.4% / 1.2%; 224.6% / -51.6% / 1.7% |
| locate 0 / 1% / 2% / 3% | 301% / -51% / 0.4%; 179% / -55% / 2.7%; 94% / -63% / 15%; 35% / -81% / 53% |
| pre-borrow 0.5% / 1% a night | 124% / -60% / 7.6%; 49% / -77% / 40% |
| spreads x1.5 / x2 | 181% / -55% / 2.5%; 136% / -59% / 5.5% |
| high costs | 11.8% / -91% / 77% |
| entries 1 / 5 minutes late | 220% / -54% / 1.6%; 217% / -52% / 1.0% |
| account $1M | 200% / -59% / 0.5% |

- Margin by price barely binds at these sizes; locate and pre-borrow costs dominate. At 2% locate or 0.5% a night
  pre-borrow the book breaks the owner's p75 limit; at high costs it is close to ruin (DD -91%).
- One trade did most of the damage: DS1 short on 2024-12-13 at $1.85, -474% of the position, -52% of the account, a
  gap through the stop. Seven of A28's 20 worst trades are DS1 (the d10 run-up short).
- A28 is strongest after T+1 (2024-05-28: Sortino 6.75) and after Nasdaq's 2025 delisting rule (8.29); A26 is the
  opposite (5.58 before T+1, 1.54 after). Leaving out any one year keeps A28 between 4.81 and 6.54.

## Symbol halves (same picks on each SHA-256 half of the tickers)

All B families except XS2 and MD stay positive on both halves (DS1 4.32/2.09, RU 2.39/4.00, PS 3.51/1.48, OR 2.48/1.58).
Half Sortinos are lower than the full stream, as in v27 (fewer trades a month). PDUFA 1.67/1.55; premarket -0.16/0.36.
The picks saw both halves, so this is weaker than v27's holdout.

## Caveats

DSR 0.00 over all v28 and earlier trials; the 2023-07+ window is not clean for the researcher; borrow and locate are
modelled, not quoted; the tail (single trades of -474%) is real and the d10 hold makes it larger.

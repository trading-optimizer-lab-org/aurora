# v27 A and B results: v26 with each trade's own quotes, and on unseen symbol halves

Pre-registered in [V27_PREREGISTRATION.md](V27_PREREGISTRATION.md), sections A and B. B: run 39735247154; A: run 39735247479 (2026-10-22).

## Summary

- **B: the edge holds on symbols the selection never saw.** With each family's picks chosen on one half of the symbols, the equal-weight average of the family streams has a Sortino of 2.70 on the half it was picked on and **2.58 on the unseen half** (CAGR 6.7% and 6.8%). Single families are noisy on half the names (half the trades); v26's own picks on each half fall in the same range, so the lower numbers come from the smaller universe, not from overfitting to names.
- **A: each trade's own quotes cost a little more than the tier table.** 11,049 trades of book A ($100k, risk 1%, cap 40%, gross 1x), 21,662 of 22,098 legs quoted. Median measured half-spreads are at or below the tier values on most legs (premarket exits above), but the mean is higher (wide spreads on some legs). Book A: tier costs Sortino 4.60 (reproduces v26's 4.63), CAGR 112.6%, DD -54.2%; **measured costs Sortino 4.24, CAGR 103.4%, DD -54.6%, p75 0.2%**; measured x1.5: Sortino 2.62, CAGR 63%, DD -65%, p75 2.9%.
- Locate and pre-borrow fees of brokers that charge them are still not modelled.

## B. Holdout

Each family's walk-forward picks chosen on one half of the symbols (run_v22's selection on that half alone), measured on the same half and on the other; and v26's own picks (chosen on all symbols) on each half. Monthly Sortino 2018+, middle R4 costs.

| family | picked on half 0: on 0 | on 1 (unseen) | picked on half 1: on 1 | on 0 (unseen) | v26 picks on half 0 | on half 1 |
|---|---|---|---|---|---|---|
| v19:DS1 | 0.74 | 0.51 | 1.13 | 1.52 | 1.77 | 1.16 |
| v19:ON1 | 1.18 | 1.87 | 3.31 | 1.37 | 0.97 | 2.02 |
| v19:XS1 | 0.86 | 2.35 | 1.48 | 1.12 | 0.84 | 2.38 |
| v19:XS2 | 0.27 | 0.80 | 0.99 | 1.28 | 0.92 | 0.47 |
| v20:GF | 0.44 | 0.35 | 0.90 | 1.64 | 0.69 | 1.63 |
| v20:NS | 1.52 | 0.41 | 0.97 | 0.37 | 0.40 | 0.66 |
| v20:RF | 1.86 | 0.34 | 1.74 | 2.47 | 1.46 | 0.64 |
| v20:RU | 0.29 | 0.43 | 1.62 | 1.66 | 1.37 | 1.70 |
| v22:IF | 1.01 | 0.96 | -0.13 | 1.21 | 1.11 | 0.60 |
| v22:IR | 0.79 | 0.66 | 0.40 | -0.01 | 1.51 | 0.53 |
| v22:IV | 2.09 | 1.58 | 1.39 | 1.65 | 2.05 | 1.53 |
| v23:EM | 1.13 | 0.71 | 0.45 | 1.45 | 1.36 | 0.62 |
| v23:MD | 1.13 | 0.08 | 0.12 | -0.10 | 1.74 | -0.25 |
| v23:OR | 0.88 | 0.26 | 0.26 | 1.67 | 2.42 | 1.33 |
| v23:OS | 0.68 | 0.70 | -0.19 | 0.28 | 0.90 | 0.43 |
| v23:PT | 0.62 | 1.25 | 0.64 | 0.65 | 1.19 | 1.39 |
| v23:SQ | 1.17 | -0.04 | 0.21 | 1.05 | 1.71 | 0.36 |
| v23:SR | 1.58 | 0.93 | 0.85 | 1.51 | 2.30 | 1.07 |
| v23:VW | 1.46 | 2.67 | 0.93 | 1.25 | 1.19 | 1.15 |
| v25:AS | 2.35 | 2.20 | 2.00 | 1.67 | 2.10 | 1.96 |
| v25:IS | 1.05 | 0.63 | 0.44 | 1.33 | 1.50 | 0.55 |
| v25:MP | 0.62 | 0.15 | 0.46 | 1.37 | 1.12 | 0.97 |
| v25:PS | 3.74 | 1.35 | 1.01 | 3.45 | 3.08 | 0.97 |

Equal-weight average of the family streams: on the half they were picked on Sortino 2.70 (CAGR 6.7%); on the unseen half 2.58 (CAGR 6.8%).

## A. Quotes

11049 trades the book took (risk 1.00%, cap 40%, gross 1x); 21662 of 22098 legs with a quote in their minute (the tier value elsewhere). Half-spreads (half the quoted spread over the mid).

| leg | price | legs | quoted | median measured | tier value |
|---|---|---|---|---|---|
| open | <$2 | 196 | 196 | 0.4% | 0.7% |
| open | $2-5 | 363 | 363 | 0.4% | 0.8% |
| open | $5-10 | 268 | 267 | 0.4% | 0.8% |
| open | $10-20 | 230 | 229 | 0.5% | 1.0% |
| session | <$2 | 2353 | 2318 | 0.4% | 0.5% |
| session | $2-5 | 5951 | 5855 | 0.3% | 0.4% |
| session | $5-10 | 3019 | 2992 | 0.3% | 0.4% |
| close | <$2 | 1509 | 1473 | 0.5% | 0.6% |
| close | $2-5 | 3974 | 3862 | 0.4% | 0.5% |
| close | $5-10 | 2597 | 2536 | 0.3% | 0.5% |
| close | $10-20 | 559 | 545 | 0.3% | 0.4% |
| stop | <$2 | 133 | 132 | 0.4% | 0.6% |
| stop | $2-5 | 456 | 444 | 0.3% | 0.5% |
| stop | $5-10 | 258 | 250 | 0.2% | 0.5% |
| stop | $10-20 | 30 | 30 | 0.2% | 0.4% |
| ah | <$2 | 20 | 19 | 0.3% | 0.5% |
| ah | $2-5 | 52 | 50 | 0.4% | 0.4% |
| ah | $5-10 | 19 | 19 | 0.3% | 0.2% |
| ah | $10-20 | 10 | 10 | 0.5% | 0.2% |
| pm | <$2 | 17 | 12 | 0.7% | 0.5% |
| pm | $2-5 | 52 | 38 | 1.3% | 0.4% |
| pm | $5-10 | 27 | 19 | 0.4% | 0.2% |
| pm | $10-20 | 5 | 3 | 0.5% | 0.2% |

| half-spreads | Sortino | CAGR | max DD | worst day | p75 | median bootstrap CAGR |
|---|---|---|---|---|---|---|
| tier | 4.60 | 112.6% | -54.2% | -27.6% | 0.2% | 112.8% |
| measured | 4.24 | 103.4% | -54.6% | -27.6% | 0.2% | 103.7% |
| measured x1.5 | 2.62 | 63.0% | -65.2% | -27.6% | 2.9% | 63.2% |

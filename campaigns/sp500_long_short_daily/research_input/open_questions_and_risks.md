# Open questions and risks

## Must be resolved before the full train run

| Issue | Why it matters | Required resolution | Fail-closed outcome |
| --- | --- | --- | --- |
| SPY adjusted-open reconstruction | Adjusted close does not automatically define an adjusted open, and distributions affect open-to-open return. | Reconcile raw OHLC, splits and State Street distributions with hand-calculated event tests. | Core target data ineligible. |
| Stooq/Yahoo adjustment semantics | Providers can differ around events and corrections. | Snapshot both; document tolerance and choose one canonical raw series only after reconciliation. | Technical/data failure, not performance zero. |
| Cboe term-index live/backfill dates | A historical backfill may not have been known at the historical date. | Store first dissemination date or reconstruct from causal inputs. | Exclude pre-dissemination observations/candidate history. |
| Credit/financial-condition vintages | Latest histories can include future revisions. | Use ALFRED/archived releases or reconstruct; prove release-date joins. | Candidate data ineligible. |
| Breadth archive provenance | Exchange breadth is not S&P breadth and definitions may change. | Validate source, issue definitions, calendar and missing days; label as proxy. | Breadth families rejected from runnable set. |
| SPY overnight-gap reconstruction | Raw opening gaps can be corrupted by splits/distributions or retrospective adjustment factors. | Reconstruct `SPY_TR_OPEN_t` and `SPY_TR_CLOSE_{t-1}` from raw bars plus State Street actions; hand-test every event. Paid ES data are not a dependency. | Overnight/gap family is `DATA_INELIGIBLE`. |
| Source terms and redistribution | A free download may prohibit redistribution. | Store code, URLs and hashes; do not place restricted raw data in the ZIP/artifacts. | Use retrievable manifest only. |

## Must be resolved before validation is opened

- Train merge contains every candidate or an explicit rejection row.
- Candidate code, data snapshots, environment and finalist order are frozen and hashed.
- Multiple-testing outputs complete without numerical errors.
- No unresolved data repair decision was influenced by train ranking.
- GitHub artifact containing `train_selection_freeze.json` is downloadable and hash-verified.
- Validation acknowledgment is exactly `OPEN_VALIDATION_2011_2020_ONCE`.
- Workspace scan proves no 2021+ observations, caches or precomputed features.

## Scientific risks that cannot be eliminated

1. **Transfer risk:** multi-asset futures, cross-sectional stocks or monthly horizons may not transfer to SPY next-open trading.
2. **Power:** 1993-2010 provides a limited number of independent market regimes; daily observations do not equal independent observations.
3. **Structural change:** market microstructure, index composition, monetary regimes and option markets evolved.
4. **Publication bias:** the literature overrepresents positive findings, and post-publication returns may attenuate.
5. **Proxy risk:** free VRP, breadth and cross-asset proxies are not exact institutional datasets.
6. **Zero-cost external validity:** gross results can materially overstate implementable short/reversal performance.
7. **One validation set:** 2011-2020 can adjudicate this frozen universe once, not provide unlimited model development.

## What would invalidate the final conclusion

- discovery of lookahead or use of revised final values;
- a corporate-action/open-return error;
- a candidate or benchmark calculated with different timing;
- missing candidates hidden rather than logged;
- validation opened before the train freeze;
- any access to 2021+ outcomes during this campaign;
- code or data changing between train freeze and validation;
- a reported positive result that passes only after changing an acceptance threshold.

## Deliberately unanswered by this package

The package does not claim which candidate wins, what its train/validation returns are, or whether a live implementation is profitable after real costs. Those are empirical outputs for Aurora under the frozen protocol.

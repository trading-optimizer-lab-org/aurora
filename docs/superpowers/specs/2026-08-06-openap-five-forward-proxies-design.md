# OpenAP Five Forward Proxies Design

## Objective

Make `DivSeason`, `AnnouncementReturn`, `EarningsStreak`, `IndRetBig`, and
`DelNetFin` usable in Aurora's current stock score without representing an
official OpenAP portfolio mirror as an independently reconstructed signal.

Each signal is calculated for current US common stocks from public data and is
admitted to the score only after a chronological, out-of-sample validation
shows that the independently reconstructed portfolio behaves sufficiently like
the official OpenAP portfolio.

## Non-negotiable gates

- Historical development ends on `2010-12-31`.
- Historical validation covers `2011-01-01` through `2020-12-31`.
- Observations from `2021-01-01` onward are never used to choose formulas,
  parameters, aliases, weights, or acceptance.
- A current snapshot may use data known at the requested current `as_of`, but
  no post-snapshot return is inspected.
- Minimum validation Pearson correlation: `0.80`.
- Minimum validation Spearman correlation: `0.80`.
- Minimum validation sign agreement: `0.75`.
- Minimum common validation months: `60`.
- The signal must pass every gate to receive `current_usable=true` and enter
  the score.
- A failed signal remains available for diagnosis but contributes zero weight.
- `locked_opened=false`, `backtest_enabled=false`, and
  `validation_used_for_selection=false` are written to every final summary.

## Source-faithful formulas

### DivSeason

Official behavior is a binary monthly predictor for regular cash-dividend
payers. Aurora will:

1. Use completed, observed cash distributions from Yahoo public daily actions.
2. Exclude special distributions when a reliable regular/special distinction is
   available; otherwise mark the source limitation explicitly.
3. Infer payment frequency from the median and modal spacing of the latest
   eight completed payments:
   - quarterly: spacing from 2 through 4 months;
   - semiannual: spacing from 5 through 7 months;
   - annual: spacing from 10 through 14 months;
   - unknown: use the official quarterly fallback.
4. Exclude inferred monthly payers.
5. Return `1` when a completed payment occurred at the official lag set:
   - quarterly or unknown: 2, 5, 8, or 11 months;
   - semiannual: 5 or 11 months;
   - annual: 11 months.
6. Return `0` for an eligible payer with at least one payment in the previous
   12 completed months and no matching expected-payment lag.

Candidate variants may change only the frequency inference rule. The official
lag sets and binary output cannot be optimized.

### AnnouncementReturn

Aurora will use the latest completed earnings announcement and calculate the
sum of daily stock excess returns over trading days `[-2, +1]` around the
announcement date. Excess return is stock total return minus `Mkt-RF` minus
`RF` from Kenneth French's daily factors. The value remains active for no more
than six months.

Announcement-date sources are ordered by fidelity:

1. SEC `8-K` filings containing Item `2.02`, using the SEC acceptance timestamp.
2. Yahoo `get_earnings_dates`, when an actual reported EPS is present.
3. SEC `10-Q` or `10-K` filing date only as a diagnostic fallback; this variant
   can never pass the source-fidelity gate by itself.

If multiple source dates exist, Aurora selects the earliest timestamp that can
be proved publicly available and records the alternatives. The return window
must be complete before the value becomes available.

### EarningsStreak

Aurora will use Yahoo historical earnings rows containing announcement date,
reported EPS, consensus estimate, and a causal price. For each report:

```text
surprise = (reported_eps - consensus_eps) / prior_session_close
```

The signal exists only when the latest and immediately preceding surprises have
the same non-zero sign. Its value is the latest price-scaled surprise. It is
available after the reported timestamp and remains active for at most six
months.

SEC actual earnings without a historical consensus estimate are insufficient.
Such rows are reported as missing, never converted into a fabricated consensus
proxy.

### IndRetBig

Aurora will:

1. Map each issuer to Fama-French 48 industries from the latest SEC SIC known by
   formation month.
2. Compute prior-month unadjusted market equity from unadjusted close multiplied
   by point-in-time shares outstanding.
3. Rank firms within each industry and month.
4. Define big firms as relative rank strictly greater than `0.70`.
5. Calculate the simple arithmetic mean prior-month total return of big firms
   within the industry.
6. Assign that industry return to non-big firms and leave big firms missing.

Static Yahoo industry labels, current shares applied historically, and adjusted
price multiplied by shares are forbidden in the accepted implementation.

### DelNetFin

For the latest annual filing known by the formation date, Aurora maps SEC XBRL
facts to the Compustat-equivalent components:

```text
net_financial_assets =
    short_term_investments
  + other_investments
  - long_term_debt
  - current_debt
  - preferred_stock

DelNetFin =
  (net_financial_assets_t - net_financial_assets_t_minus_12m)
  / (0.5 * (assets_t + assets_t_minus_12m))
```

Aliases are selected by a deterministic precedence table. Missing required
components remain missing, except preferred stock, which follows the official
zero-if-missing rule. Filing acceptance timestamps determine availability.

## Architecture

### Formula layer

`research/openap_93/forward_proxy_formulas.py` contains pure calculation
functions. They receive normalized frames and return one row per symbol with
value, observation timestamp, source, formula variant, and caveat. No network
access or score weighting lives in this module.

### Public source layer

`scripts/run_openap_five_forward_proxies.py` extends the existing GitHub-only
YFinance and SEC collection path. It persists raw evidence for:

- Yahoo prices, cash distributions, and historical earnings dates;
- SEC submissions, filing acceptance times, SIC history, Item 2.02 detection,
  and Company Facts;
- Kenneth French daily factors and FF48 mapping.

Every current value records `available_at`, `source_ids`, source hashes, and
whether all required inputs were causal at `as_of`.

### Calibration and validation layer

`research/openap_93/forward_proxy_validation.py` forms monthly deciles from
each independent candidate variant and calculates the following-month high
minus low return using the independently collected stock panel. It compares
that return with the official OpenAP long-short series.

Candidate selection uses only development data through 2010. The selected
variant is frozen before the 2011-2020 validation is measured. No sign flipping
is allowed after the official direction has been applied. Validation emits
Pearson, Spearman, sign agreement, common months, tracking error, and subperiod
stability.

### Score integration layer

The current score consumes a signed cross-sectional percentile only when a
frozen validation certificate exists and all gates pass. Otherwise the feature
has `fidelity_class=unvalidated_proxy`, `current_usable=false`, and zero weight.

The certificate binds:

- signal and selected formula variant;
- source and code hashes;
- development and validation dates;
- all validation metrics;
- minimum-gate version;
- `locked_opened=false`.

Changing a formula, alias table, source precedence, or minimum gate invalidates
the certificate automatically.

## GitHub workflow

`.github/workflows/openap-five-forward-proxies.yml` uses Aurora's reusable
future-run contract and runs only by `workflow_dispatch`.

Jobs:

1. `contract`: validates GitHub-only execution and policy invariants.
2. `collect`: downloads public source data and preserves hashes.
3. `reconstruct`: calculates historical candidate variants and the current
   snapshot.
4. `select_train`: selects each formula variant using data through 2010.
5. `validate`: evaluates the frozen variants on 2011-2020.
6. `certify`: emits pass/fail certificates and score-ready current values.
7. `publish`: uploads one final artifact even when some signals fail.

## Outputs

Artifact `openap-five-forward-proxies-results` contains:

- `forward_proxy_current_values.parquet`
- `forward_proxy_current_values.csv`
- `forward_proxy_candidate_metrics.csv`
- `forward_proxy_validation_metrics.csv`
- `forward_proxy_certificates.jsonl`
- `forward_proxy_score_ready.csv`
- `forward_proxy_missing_inputs.csv`
- `forward_proxy_source_audit.csv`
- `forward_proxy_summary.json`

`forward_proxy_summary.json` reports each signal separately. It may report
fewer than five score-ready signals; it must never claim success by averaging a
strong signal with a weak one.

## Failure behavior

- Missing source data: signal fails closed and names every missing field.
- Fewer than 60 common validation months: signal is not certified.
- Any validation metric below its gate: signal is not certified.
- Source or formula drift after certification: current value is withheld until
  revalidation.
- SEC/Yahoo conflicts: keep both raw values, use documented source precedence,
  and report the conflict.
- Network or partial-artifact failure: `partial=true`; no score-ready file is
  accepted by downstream scoring.

## Verification

Tests are written before production changes and run in GitHub Actions. Required
behavioral coverage includes:

- every official formula on hand-calculated fixtures;
- event windows use trading sessions `[-2, +1]`;
- no value is available before its final required input;
- `IndRetBig` uses PIT SIC, PIT shares, unadjusted close, and arithmetic means;
- `DelNetFin` uses exact 12-month matching and average assets;
- train-selected variants cannot inspect validation;
- 2021+ observations cannot affect selection or validation;
- failed certificates contribute zero score weight;
- a formula/source hash change invalidates a certificate;
- final artifacts report `locked_opened=false`, `backtest_enabled=false`, and
  `validation_used_for_selection=false`.

## Acceptance definition

The feature is complete only when a GitHub run produces a non-partial artifact,
calculates current values independently, and certifies at least one of the five
signals against all out-of-sample gates. Each additional signal is accepted
individually. A source mirror is never counted as an independent success.
